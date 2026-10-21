"""I/O — WMS fetch + cache and ``run_evidence_stage`` (city plan + parcel evidence for the anchor). No streamlit.

Definitions are cut verbatim from pages/Rent_Gradient.py (see tests/test_rg_v2_equivalence.py).
"""


import hashlib
import io
import json
import requests
import time
from concurrent.futures import ThreadPoolExecutor, wait
from math import floor, hypot, pi
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from .compat import ndi, np
from .config import CELL_M, EVIDENCE_ANCHOR_SOURCE, EVIDENCE_CONFIG, EVIDENCE_SCHEMA, LONGDO_WMS_URL, ZONING_COLOR_TOLERANCE, _WEB_MERCATOR
from .geo import calculate_distance_meters
from .vision import _cells_per_tile, _circle_mask, _clusters_of, _dominant_colours, _evidence_geometry, _evidence_stability, _hot_threshold, _lattice_tiles, _legend_lut, _mask_polygon, _parcel_tile_scores, _paste, _peak_zone, _pick_cluster, _plan_tile_shares, _smooth_nan, _tile_bbox, _wms_params, _zone_records, _zones_in_scope, classify_anchor_confidence, load_cityplan_legend
from .osm import CACHE_DIR, _atomic_write


def _wms_cache_file(params: Dict[str, Any]) -> Path:
    digest = hashlib.sha256(json.dumps(params, sort_keys=True).encode("utf-8")).hexdigest()[:40]
    return CACHE_DIR / f"wms_{digest}.png"


def load_cached_wms_image(layer: str, bbox: Tuple[float, float, float, float], px: int
                          ) -> Optional[np.ndarray]:
    """The cached window as RGBA, or ``None`` — never touches the network (for thumbnails)."""
    from PIL import Image

    try:
        cache_file = _wms_cache_file(_wms_params(layer, bbox, px))
        return np.asarray(Image.open(cache_file).convert("RGBA")) if cache_file.exists() else None
    except Exception:
        return None


def fetch_wms_image(
    layer: str, bbox: Tuple[float, float, float, float], px: int
) -> Tuple[Optional[np.ndarray], Dict[str, Any]]:
    """RGBA ``(px, px, 4)`` array of a WMS window, from the disk cache or one GetMap request.

    The cache key excludes the API key, so a result is reproducible offline and exports with
    the cache. Never raises: ``(None, {"error": ...})`` on any failure (HTTP status, XML
    service exception, undecodable image, timeout).
    """
    from PIL import Image

    params = _wms_params(layer, bbox, px)
    cache_file = _wms_cache_file(params)
    info: Dict[str, Any] = {"layer": layer, "cache_file": cache_file.name, "from_cache": False}
    try:
        if cache_file.exists():
            image = Image.open(cache_file).convert("RGBA")
            info["from_cache"] = True
            return np.asarray(image), info
    except Exception:
        pass  # unreadable cache entry: fetch again
    try:
        response = requests.get(
            LONGDO_WMS_URL, params=params, timeout=EVIDENCE_CONFIG["timeout_s"],
            headers={"User-Agent": "Rent_Gradient-evidence/1.0"},
        )
        if response.status_code != 200:
            return None, {**info, "error": f"HTTP {response.status_code}"}
        if "image" not in response.headers.get("Content-Type", "image/png"):
            return None, {**info, "error": "server returned a service exception, not an image"}
        image = Image.open(io.BytesIO(response.content))
        image.load()
        image = image.convert("RGBA")
        if image.size != (px, px):
            return None, {**info, "error": f"unexpected image size {image.size}"}
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        try:
            _atomic_write(cache_file, buffer.getvalue())
            _atomic_write(cache_file.with_suffix(".json"), json.dumps(
                {"layer": layer, "bbox": list(bbox), "px": px,
                 "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}).encode("utf-8"))
        except Exception:
            pass  # caching is best-effort
        return np.asarray(image), info
    except Exception as exc:
        return None, {**info, "error": " ".join(str(exc).split())[:160] or type(exc).__name__}


def _fetch_tiles(
    fetcher: Callable[..., Tuple[Optional[np.ndarray], Dict[str, Any]]],
    jobs: List[Tuple[Any, str, Tuple[float, float, float, float]]],
    analyse: Callable[[Any, np.ndarray], Any],
    deadline: float,
    tally: Dict[str, Any],
) -> Dict[Any, Tuple[str, Any]]:
    """Fetch and analyse tiles in parallel → ``{key: (status, value)}``; never raises.

    ``status`` is ``ok`` (value = analysis), ``nodata`` (image fine, nothing measurable) or
    ``error``. Tiles unfinished at ``deadline`` are cancelled and counted as skipped.
    """
    cfg = EVIDENCE_CONFIG
    if not jobs:
        return {}

    def short(exc: BaseException) -> str:
        return f"{type(exc).__name__}: {' '.join(str(exc).split())[:120]}"

    def work(key: Any, layer: str, bbox: Tuple[float, float, float, float]):
        try:
            image, info = fetcher(layer, bbox, cfg["px"])
        except Exception as exc:  # one bad tile must not cancel the others
            return key, "error", None, {"error": short(exc)}
        if image is None:
            return key, "error", None, info
        try:
            value = analyse(key, image)
        except Exception as exc:
            return key, "error", None, {**info, "error": short(exc)}
        return key, ("ok" if value is not None else "nodata"), value, info

    pool = ThreadPoolExecutor(max_workers=max(1, int(cfg["parallel"])))
    out: Dict[Any, Tuple[str, Any]] = {}
    try:
        futures = [pool.submit(work, *job) for job in jobs]
        done, pending = wait(futures, timeout=max(0.0, deadline - time.perf_counter()))
        for future in futures:
            if future not in done:
                future.cancel()
                continue
            key, status, value, info = future.result()
            out[key] = (status, value)
            tally["fetched"] += 1
            tally["hits"] += bool(info.get("from_cache"))
            if status == "error":
                tally["errors"].append(f"{key[0]}#{key[1]},{key[2]}: {info.get('error', 'no image')}")
        if pending:
            tally["timed_out"] += len(pending)
            tally["errors"].append(f"หมดเวลา: ข้าม {len(pending)} ไทล์")
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    return out


def run_evidence_stage(
    found: Dict[str, Any],
    study_center: Tuple[float, float],
    study_radius_m: float,
    legend: Optional[List[Dict[str, Any]]] = None,
    legend_source: str = "provisional",
    fetcher: Callable[..., Tuple[Optional[np.ndarray], Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Scan the whole study circle for the dense small-parcel cluster inside the peak-colour zone.

    Plan tiles (ผังสี) → peak colour and its zones → parcel tiles only where that zone is →
    densest cluster of small / ตึกแถว lots → the evidence anchor. ``found`` (the road result) is
    used only to agree with the road anchors and, when the plan is unreadable, to say where to look.
    Never raises; without evidence the road anchors are left exactly as they are.
    """
    cfg = EVIDENCE_CONFIG
    fetcher = fetcher or fetch_wms_image
    started = time.perf_counter()
    deadline = started + float(cfg["deadline_s"])
    tally: Dict[str, Any] = {"fetched": 0, "hits": 0, "errors": [], "skipped": 0, "timed_out": 0}
    base: Dict[str, Any] = {
        "schema": EVIDENCE_SCHEMA, "method": "peak-zone-parcel-cluster", "status": "unavailable",
        "reason": None, "notes": [], "legend_source": legend_source,
        "study": {"center": [float(study_center[0]), float(study_center[1])],
                  "radius_m": float(study_radius_m), "area_km2": pi * float(study_radius_m) ** 2 / 1e6},
        "windows": {"px": cfg["px"], "plan_tile_m": cfg["plan_tile_m"], "parcel_tile_m": cfg["parcel_tile_m"],
                    "cell_m": CELL_M},
        "plan": {"state": "unavailable", "tiles": 0, "tiles_ok": 0, "explained": None, "peak": None, "zones": []},
        "parcel": {"region": None, "tiles_needed": 0, "tiles_ok": 0, "tiles_skipped": 0},
        "clusters": [], "evidence_anchor": None, "confidence": None, "stability": None,
        "fetch": {"requests": 0, "cache_hits": 0, "errors": [], "skipped_over_budget": 0, "seconds": 0.0},
    }

    def finish(**updates: Any) -> Dict[str, Any]:
        base["fetch"] = {"requests": tally["fetched"] - tally["hits"], "cache_hits": tally["hits"],
                         "errors": tally["errors"][:10],
                         "skipped_over_budget": tally["skipped"] + tally["timed_out"],
                         "seconds": time.perf_counter() - started}
        return {**base, **updates}

    try:
        legend = legend or load_cityplan_legend()[0]
        composite = (found or {}).get("composite") or {}
        closeness = (found or {}).get("closeness") or {}
        road_anchors = [a for a in (composite.get("anchor"), closeness.get("anchor"))
                        if a and a.get("lat") is not None and a.get("lon") is not None]
        geo = _evidence_geometry(study_center, study_radius_m)
        circle = _circle_mask(geo, geo["x0"], geo["y0"], geo["r"])
        n_plan, n_parcel = _cells_per_tile(cfg["plan_tile_m"]), _cells_per_tile(cfg["parcel_tile_m"])
        budget = int(cfg["max_requests"])

        # ---- plan pass: colours → peak zone
        lut = _legend_lut(legend, ZONING_COLOR_TOLERANCE)
        plan_all = _lattice_tiles(geo, cfg["plan_tile_m"], circle)
        plan_tiles = plan_all[: min(int(cfg["max_plan_tiles"]), budget)]
        tally["skipped"] += len(plan_all) - len(plan_tiles)
        plan_jobs = [(("plan", tx, ty), cfg["plan_layer"], _tile_bbox(tx, ty, cfg["plan_tile_m"]))
                     for tx, ty in plan_tiles]
        plan_out = _fetch_tiles(
            fetcher, plan_jobs,
            lambda key, image: _plan_tile_shares(image, lut, len(legend), n_plan), deadline, tally)
        shares = np.zeros((len(legend) + 1, geo["nj"], geo["ni"]), dtype=np.uint16)   # legend classes + red
        painted = explained = pixels = plan_ok = red_pixels = 0
        red_sum = np.zeros(3, dtype=np.int64)
        histogram: Dict[int, int] = {}
        for (_, tx, ty), (status, value) in sorted(plan_out.items(), key=lambda kv: kv[0]):
            if status != "ok":
                continue
            plan_ok += 1
            _paste(shares, value["shares"], tx * n_plan - geo["i0"], ty * n_plan - geo["j0"])
            painted += value["painted"]
            explained += value["explained"]
            pixels += value["pixels"]
            red_pixels += value["red_pixels"]
            red_sum += value["red_sum"]
            for key4, count in value["colours"].items():
                histogram[key4] = histogram.get(key4, 0) + count
        peak = None
        if plan_ok == 0:
            plan_state = "unavailable"
        elif painted < cfg["plan_min_painted"] * max(pixels, 1):
            plan_state = "blank"
        else:
            peak = _peak_zone(shares, legend, (cfg["px"] // n_plan) ** 2)
            peak = _zones_in_scope(peak, circle) if peak else None   # red inside the radius, zones whole
            plan_state = "ok" if peak else "no_peak"
        plan_info: Dict[str, Any] = {
            "state": plan_state, "tiles": len(plan_tiles), "tiles_ok": int(plan_ok),
            "explained": (explained / painted) if painted else None, "peak": None, "zones": [],
            "colours": _dominant_colours(histogram, legend)}

        # ---- search region: the peak zone, or (plan unreadable) a disc around the road anchor
        notes: List[str] = []
        zones: List[Dict[str, Any]] = []
        if peak:
            zone = peak["mask"]
            zones = _zone_records(peak, geo, legend)
            area_km2 = float(zone.sum() * (CELL_M * geo["ground"]) ** 2 / 1e6)
            seen = (red_sum / max(red_pixels, 1)).round().astype(int).tolist()     # the red Longdo really serves
            plan_info["peak"] = {"name": "สีแดง", "rgb": seen if red_pixels else [255, 0, 0], "weight": 1.0,
                                 "commercial": True, "cells": int(zone.sum()), "area_km2": area_km2}
            plan_info["zones"] = zones
            peak_zones = peak
            region_kind = "peak_zone"
        else:
            reason_text = {"unavailable": "ดึงภาพผังเมืองไม่สำเร็จ", "blank": "ผังเมืองว่าง/นอกพื้นที่ผังเมืองรวม",
                           "no_peak": "ไม่พบโซนพาณิชยกรรม (สีแดง) ในวงศึกษา"}[plan_state]
            anchor_ref = composite.get("anchor") if composite else None
            if not anchor_ref or anchor_ref.get("lat") is None:
                return finish(plan=plan_info, reason=f"{reason_text} และไม่มี anchor ถนนให้ใช้เป็นจุดค้นหา")
            fx, fy = _WEB_MERCATOR.transform(anchor_ref["lon"], anchor_ref["lat"])
            zone = _circle_mask(geo, fx, fy, cfg["fallback_radius_m"] / geo["ground"])
            peak_zones = {"labels": zone.astype(np.int32), "big": np.array([1]), "mask": zone}
            region_kind = "fallback_disc"
            notes.append(f"{reason_text} — ใช้เฉพาะแปลงที่ดินในรัศมี {cfg['fallback_radius_m'] / 1000:g} กม. รอบ anchor ถนน")

        # ---- parcel pass: tiles under the region, densest first
        jj, ii = np.nonzero(zone)
        gi, gj = (geo["i0"] + ii) // n_parcel, (geo["j0"] + jj) // n_parcel
        keys, counts = np.unique(np.stack([gj, gi], axis=1), axis=0, return_counts=True)
        # tile priority = zone cells / (1 + (distance to the study centre / reach)²): the same radius-free prior
        # as the cluster choice, so a far zone entering with a larger radius never evicts a town tile
        def tile_priority(count: int, tj: int, ti: int) -> Tuple[float, float, int, int]:
            d = hypot((ti + 0.5) * cfg["parcel_tile_m"] - geo["x0"], (tj + 0.5) * cfg["parcel_tile_m"] - geo["y0"]) * geo["ground"]
            return (-round(count / (1.0 + (d / cfg["reach_m"]) ** 2), 12), round(d, 3), tj, ti)

        ranked = sorted(zip(counts.tolist(), keys[:, 0].tolist(), keys[:, 1].tolist()),
                        key=lambda t: tile_priority(*t))
        needed = len(ranked)
        room = max(0, min(int(cfg["max_parcel_tiles"]), budget - len(plan_jobs)))
        chosen = [(ti, tj) for _, tj, ti in ranked[:room]]
        tally["skipped"] += needed - len(chosen)
        m_per_px = cfg["parcel_tile_m"] / cfg["px"] * geo["ground"]
        parcel_jobs = [(("parcel", ti, tj), cfg["parcel_layer"], _tile_bbox(ti, tj, cfg["parcel_tile_m"]))
                       for ti, tj in chosen]
        parcel_out = _fetch_tiles(
            fetcher, parcel_jobs, lambda key, image: _parcel_tile_scores(image, m_per_px, n_parcel), deadline, tally)
        fields = {name: np.full((geo["nj"], geo["ni"]), np.nan) for name in ("score", "cover_small", "cover_shop")}
        scanned = np.zeros((geo["nj"], geo["ni"]), dtype=bool)         # cells whose parcel tile was read
        parcel_ok = 0
        for (_, ti, tj), (status, value) in sorted(parcel_out.items(), key=lambda kv: kv[0]):
            if status == "error":
                continue
            parcel_ok += 1
            _paste(scanned, np.ones((n_parcel, n_parcel), dtype=bool), ti * n_parcel - geo["i0"], tj * n_parcel - geo["j0"])
            if status == "ok":
                for name in fields:
                    _paste(fields[name], value[name], ti * n_parcel - geo["i0"], tj * n_parcel - geo["j0"])
        coverage = parcel_ok / needed if needed else 0.0
        parcel_info = {"region": region_kind, "tiles_needed": needed, "tiles_ok": parcel_ok,
                       "tiles_skipped": needed - parcel_ok,
                       "lots": int(sum(v["lots"] for st_, v in parcel_out.values() if st_ == "ok")),
                       "best_score": None, "hot_threshold": None}
        have_parcels = bool(np.isfinite(fields["score"]).any())

        # ---- the clusters of the red zone(s), whole; the circle only admits them, the study-centre prior ranks them
        smooth = _smooth_nan(fields["score"], int(cfg["smooth_cells"]))
        zone_dilated = ndi.binary_dilation(zone, structure=np.ones((3, 3), dtype=bool))
        in_scope = zone_dilated & np.isfinite(smooth)
        if in_scope.any():
            parcel_info["best_score"] = float(smooth[in_scope].max())
        found_clusters = (_clusters_of(smooth, peak_zones, fields, scanned, geo)
                          if have_parcels else {"clusters": [], "labels": None})
        if found_clusters["clusters"]:
            parcel_info["hot_threshold"] = float(min(c["threshold"] for c in found_clusters["clusters"]))
        elif in_scope.any():
            parcel_info["hot_threshold"] = _hot_threshold(smooth[in_scope])
        picked = _pick_cluster(found_clusters["clusters"], geo, (geo["x0"], geo["y0"]), geo["radius_m"])
        clusters = picked[: int(cfg["cluster_top"])]
        for record in clusters:
            record["polygon"] = _mask_polygon(found_clusters["labels"] == record["_label"], geo)
        winner = clusters[0] if clusters else None
        if winner is None and not peak:
            return finish(plan=plan_info, parcel=parcel_info, notes=notes, reason=(
                "ไม่มีพื้นที่ให้ค้นหา (anchor ถนนอยู่นอกวงศึกษา)" if needed == 0
                else "ไม่พบ cluster แปลงเล็กถี่ใกล้ anchor ถนน" if have_parcels
                else "ดึงภาพ/อ่านข้อมูลผังเมืองและแปลงที่ดินไม่สำเร็จ — ใช้ผลจากถนนอย่างเดียว"))
        if winner is None:
            notes.append("ไม่พบ cluster แปลงเล็กถี่ในโซน — ใช้จุดกึ่งกลางโซนสีสูงสุดใหญ่สุดแทน" if have_parcels
                         else "อ่านรูปแปลงที่ดินไม่ได้ — ใช้จุดกึ่งกลางโซนสีสูงสุดใหญ่สุดแทน")
            inside_zones = [z for z in zones if calculate_distance_meters(
                z["lat"], z["lon"], study_center[0], study_center[1]) <= study_radius_m]
            if not inside_zones:       # the red only grazes the rim of the circle: no anchor inside the study area
                return finish(plan=plan_info, parcel=parcel_info, notes=notes,
                              reason="โซนแดงอยู่แค่ขอบวงศึกษา — จุดกึ่งกลางโซนอยู่นอกรัศมี")
            point, basis = inside_zones[0], "zone"
        else:
            point, basis = winner, "cluster"
        stability = _evidence_stability(found_clusters["clusters"], geo, winner) if winner else None

        # ---- confidence
        point_x, point_y = _WEB_MERCATOR.transform(point["lon"], point["lat"])
        cell_i, cell_j = int(floor(point_x / CELL_M)) - geo["i0"], int(floor(point_y / CELL_M)) - geo["j0"]
        inside = 0 <= cell_i < geo["ni"] and 0 <= cell_j < geo["nj"] and bool(zone_dilated[cell_j, cell_i])
        peak_info = plan_info["peak"]
        zoning_ok = bool(peak_info["commercial"] and inside) if peak_info else None
        conf_cfg = cfg["confidence"]
        parcel_flag = (bool(winner and winner["score"] >= conf_cfg["parcel_ok"]
                            and winner["cells"] >= cfg["cluster_min_cells"]) if have_parcels else None)
        anchor = {"node_id": None, "lat": point["lat"], "lon": point["lon"],
                  "score": float(winner["score"]) if winner else 0.0, "basis": basis,
                  "source": EVIDENCE_ANCHOR_SOURCE, "coverage": float(coverage)}
        stability_levels = [(composite.get("stability") or {}).get("level"), (stability or {}).get("level")]
        confidence = classify_anchor_confidence(
            anchor, road_anchors, zoning_ok=zoning_ok, parcel_ok=parcel_flag, coverage=float(coverage),
            peak=peak_info, cluster=winner, stability_levels=stability_levels, cfg=cfg)
        for record in clusters:
            for private in ("_x", "_y", "_first", "_label"):
                record.pop(private)
        clean = all(v == 0 for v in (len(tally["errors"]), tally["skipped"], tally["timed_out"]))
        status = "ok" if (clean and region_kind == "peak_zone" and basis == "cluster" and coverage >= 1.0) else "partial"
        return finish(status=status, notes=notes, plan=plan_info, parcel=parcel_info, clusters=clusters,
                      evidence_anchor=anchor, confidence=confidence, stability=stability)
    except Exception as exc:  # the road result must survive whatever goes wrong here
        return finish(reason=f"{type(exc).__name__}: {' '.join(str(exc).split())[:160]}")
