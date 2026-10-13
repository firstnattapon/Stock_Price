"""Pure engine — WMS image analysis: city-plan colours, parcel lots, clusters, anchor confidence. No streamlit, no I/O.

Definitions are cut verbatim from pages/Rent_Gradient.py (see tests/test_rg_v2_equivalence.py).
"""


import json
from math import cos, floor, hypot, pi, radians
from pathlib import Path
from shapely.geometry import box
from shapely.ops import unary_union
from typing import Any, Dict, List, Optional, Tuple

from .compat import ndi, np
from .config import CELL_M, CITYPLAN_LEGEND_FILE, CITYPLAN_PROVISIONAL_LEGEND, EVIDENCE_CONFIG, PARCEL_CONFIG, ZONING_COLOR_TOLERANCE, _WEB_MERCATOR, _WEB_MERCATOR_INV
from .geo import calculate_distance_meters


def load_cityplan_legend(path: Optional[Path] = None) -> Tuple[List[Dict[str, Any]], str]:
    """``(legend, source)``; ``source`` is ``"file"`` or ``"provisional"`` (never raises)."""
    try:
        data = json.loads(Path(path or CITYPLAN_LEGEND_FILE).read_text(encoding="utf-8"))
        classes = data["classes"] if isinstance(data, dict) else data
        legend = [
            {"name": str(c["name"]), "rgb": [int(v) for v in c["rgb"]][:3],
             "weight": float(c.get("weight", 0.0)), "commercial": bool(c.get("commercial", False))}
            for c in classes
        ]
        if legend and all(len(c["rgb"]) == 3 for c in legend):
            return legend, "file"
    except Exception:
        pass
    return [dict(c) for c in CITYPLAN_PROVISIONAL_LEGEND], "provisional"


def wms_meters_per_pixel(bbox_3857: Tuple[float, float, float, float], width_px: int, lat: float) -> float:
    """Ground metres per pixel of a Web-Mercator window (3857 metres shrink by cos(lat))."""
    return (bbox_3857[2] - bbox_3857[0]) / max(width_px, 1) * cos(radians(lat))


def _ink_mask(rgba: np.ndarray) -> np.ndarray:
    """Pixels that are drawn lines: alpha when the layer is transparent, else non-background."""
    alpha = rgba[..., 3]
    if alpha.min() < 255:
        return alpha > PARCEL_CONFIG["alpha_threshold"]
    rgb = rgba[..., :3].astype(np.int32)
    key = (rgb[..., 0] // 16) * 256 + (rgb[..., 1] // 16) * 16 + (rgb[..., 2] // 16)
    values, counts = np.unique(key, return_counts=True)
    background = rgb[key == values[counts.argmax()]].mean(axis=0)
    return np.abs(rgb - background).sum(axis=-1) > PARCEL_CONFIG["opaque_bg_tolerance"]


def _component_axes(labels: np.ndarray, n: int, centroids: bool = False) -> Tuple[np.ndarray, ...]:
    """Principal-axis side lengths (major, minor; pixels) of every labelled cell.

    From second moments, so a rotated rectangle keeps its true proportions
    (a rectangle with sides a >= b has variances a²/12 and b²/12). With ``centroids`` the
    centre ``(x, y)`` of every cell (pixels) follows as the third and fourth arrays.
    """
    flat = labels.ravel()
    yy, xx = np.indices(labels.shape)
    count = np.maximum(np.bincount(flat, minlength=n + 1)[1:].astype(float), 1.0)

    def moment(values: np.ndarray) -> np.ndarray:
        return np.bincount(flat, weights=values.ravel().astype(float), minlength=n + 1)[1:] / count

    mx, my = moment(xx), moment(yy)
    cxx = moment(xx * xx) - mx ** 2 + 1 / 12  # +1/12: variance of a pixel's own footprint
    cyy = moment(yy * yy) - my ** 2 + 1 / 12
    cxy = moment(xx * yy) - mx * my
    half_trace = (cxx + cyy) / 2
    spread = np.sqrt(np.maximum(half_trace ** 2 - (cxx * cyy - cxy ** 2), 0.0))
    major = np.sqrt(12.0 * (half_trace + spread))
    minor = np.sqrt(12.0 * np.maximum(half_trace - spread, 1e-9))
    return (major, minor, mx, my) if centroids else (major, minor)


def _component_aspect(labels: np.ndarray, n: int) -> np.ndarray:
    """Principal-axis aspect ratio (>= 1) of every labelled cell; rotation-invariant."""
    major, minor = _component_axes(labels, n)
    return major / minor


def _parcel_cells(rgba: np.ndarray, m_per_px: float) -> Dict[str, Any]:
    """The lots (free cells between boundary lines) of a DOL window, measured once.

    Specks and cells cut by the window edge are dropped, a free region above
    ``giant_cell_ratio`` is "no parcels here". ``data`` is False when nothing is measurable
    (blank layer, too few lots); otherwise ``area_m2`` / ``aspect`` / ``cx`` / ``cy`` (pixels)
    hold one entry per kept lot and ``ink`` is the boundary-line mask.
    """
    cfg = PARCEL_CONFIG
    out: Dict[str, Any] = {"data": False, "ink": None, "ink_ratio": 0.0, "coverage": 0.0, "cell_count": 0}
    if rgba.ndim != 3 or rgba.shape[2] != 4 or m_per_px <= 0:
        return out
    ink = _ink_mask(rgba)
    ink_ratio = float(ink.mean())
    out.update(ink=ink, ink_ratio=ink_ratio)
    if ink_ratio < cfg["min_ink_ratio"]:
        return out
    closed = (ndi.binary_closing(ink, structure=np.ones((cfg["closing_size"],) * 2))
              if cfg["closing_size"] > 1 else ink)
    labels, n = ndi.label(~closed)  # 4-connected free cells; 8-connected lines already separate them
    if n == 0:
        return out
    area_px = np.bincount(labels.ravel(), minlength=n + 1)[1:]
    edge = np.unique(np.concatenate((labels[0], labels[-1], labels[:, 0], labels[:, -1])))
    edge = edge[edge > 0] - 1
    touches_edge = np.zeros(n, dtype=bool)
    touches_edge[edge] = True
    giant = area_px > cfg["giant_cell_ratio"] * labels.size
    keep = ~touches_edge & ~giant & (area_px >= cfg["speck_px"])
    out.update(coverage=float(1.0 - area_px[giant].sum() / labels.size), cell_count=int(keep.sum()))
    if int(keep.sum()) < cfg["min_cells"]:
        return out
    # The free cells sit *between* the lines, so they are smaller than the parcels by half a
    # line width on every side: parcel = (a + t)(b + t) = A + P t/2 + t². The line width t is
    # recovered from the data (each line borders two cells: t ~ ink / (perimeter / 2)).
    boundary = ((ndi.minimum_filter(labels, size=3) != labels)
                | (ndi.maximum_filter(labels, size=3) != labels)) & (labels > 0)
    perimeter_px = np.bincount(labels[boundary], minlength=n + 1)[1:].astype(float)
    line_px = float(np.clip(ink.sum() / max(perimeter_px[keep].sum() / 2.0, 1.0), 0.5, 8.0))
    parcel_px = area_px[keep] + perimeter_px[keep] * line_px / 2.0 + line_px ** 2
    major, minor, cx, cy = _component_axes(labels, n, centroids=True)
    out.update(data=True, area_m2=parcel_px * m_per_px ** 2,
               aspect=(major[keep] + line_px) / (minor[keep] + line_px), cx=cx[keep], cy=cy[keep])
    return out


def parcel_features(rgba: np.ndarray, m_per_px: float) -> Dict[str, Any]:
    """Parcel fragmentation of a DOL window: how thick the lines look and how small the cells are.

    ``ink_ratio`` is the share of the picture covered by boundary lines (the "thick" look);
    cells are the regions *between* lines (see :func:`_parcel_cells`). ``shophouse_share``
    counts cells of 40-160 m² with aspect >= 2.5 — the ตึกแถว signature. ``coverage`` is the
    share of the window that is not blank; a blank or unreadable layer returns
    ``data = False`` (no data is not the same as "low").
    """
    cfg = PARCEL_CONFIG
    empty = {"data": False, "coverage": 0.0, "score": None, "ink_ratio": 0.0, "cell_count": 0,
             "median_cell_m2": None, "small_share": None, "shophouse_share": None}
    cells = _parcel_cells(rgba, m_per_px)
    if not cells["data"]:
        return {**empty, "ink_ratio": cells["ink_ratio"], "coverage": cells["coverage"],
                "cell_count": cells["cell_count"]}
    area_m2, aspect = cells["area_m2"], cells["aspect"]
    low, high = cfg["shophouse_area_m2"]
    small_share = float(np.mean(area_m2 < cfg["small_cell_m2"]))
    shophouse_share = float(np.mean((area_m2 >= low) & (area_m2 <= high)
                                    & (aspect >= cfg["shophouse_min_aspect"])))
    ink_scaled = float(np.clip((cells["ink_ratio"] - cfg["ink_low"]) / (cfg["ink_high"] - cfg["ink_low"]), 0, 1))
    w = cfg["score_weights"]
    score = w["shophouse"] * shophouse_share + w["small"] * small_share + w["ink"] * ink_scaled
    return {"data": True, "coverage": cells["coverage"], "score": float(score), "ink_ratio": cells["ink_ratio"],
            "cell_count": cells["cell_count"], "median_cell_m2": float(np.median(area_m2)),
            "small_share": small_share, "shophouse_share": shophouse_share}


def _classify_colors(rgba: np.ndarray, legend: List[Dict[str, Any]], tolerance: float) -> np.ndarray:
    """Nearest-legend-colour class per pixel (-1 = transparent / no colour within tolerance),
    then a 3x3 majority vote so thin outlines and text do not count as a class."""
    h, w = rgba.shape[:2]
    rgb = rgba[..., :3].astype(np.float32)
    best = np.full((h, w), np.inf, dtype=np.float32)
    cls = np.full((h, w), -1, dtype=np.int16)
    for k, entry in enumerate(legend):
        dist = np.sqrt(((rgb - np.asarray(entry["rgb"], dtype=np.float32)) ** 2).sum(axis=-1))
        closer = (dist < best) & (dist <= tolerance)
        best[closer] = dist[closer]
        cls[closer] = k
    cls[rgba[..., 3] <= PARCEL_CONFIG["alpha_threshold"]] = -1
    votes = np.stack([ndi.uniform_filter((cls == k).astype(np.float32), size=3)
                      for k in range(len(legend))], axis=0)
    smoothed = votes.argmax(axis=0).astype(np.int16)
    smoothed[votes.max(axis=0) < 0.5] = -1
    return smoothed


def _wms_window(lat: float, lon: float, window_m: float) -> Tuple[float, float, float, float]:
    """EPSG:3857 bbox that covers ``window_m`` ground metres around (lat, lon)."""
    x, y = _WEB_MERCATOR.transform(lon, lat)
    half = (window_m / 2.0) / max(cos(radians(lat)), 1e-6)  # Mercator metres stretch by 1/cos(lat)
    return (x - half, y - half, x + half, y + half)


def _wms_params(layer: str, bbox: Tuple[float, float, float, float], px: int) -> Dict[str, Any]:
    return {
        "service": "WMS", "version": "1.1.1", "request": "GetMap", "layers": layer, "styles": "",
        "srs": "EPSG:3857", "bbox": ",".join(f"{v:.1f}" for v in bbox),
        "width": px, "height": px, "format": "image/png", "transparent": "true",
    }


# Everything below sits on one global lattice of 128 Web-Mercator-metre cells, so a tile is the
# same WMS request (and cache file) whatever the study centre or radius. Arrays are indexed
# [row j, column i] with j growing northwards (images are flipped once, on the way in).
def _evidence_geometry(center: Tuple[float, float], radius_m: float) -> Dict[str, Any]:
    """Study circle in Web-Mercator metres plus the lattice-cell box that holds it.

    The box is aligned to whole plan tiles, so a red zone that reaches out of the circle is still
    read whole (the circle admits zones and clusters, it never clips them).
    """
    lat, lon = center
    x0, y0 = _WEB_MERCATOR.transform(lon, lat)
    r = float(radius_m) / max(cos(radians(lat)), 1e-6)  # 3857 metres stretch by 1/cos(lat)
    n = _cells_per_tile(EVIDENCE_CONFIG["plan_tile_m"])
    i0, i1 = int(floor(floor((x0 - r) / CELL_M) / n)) * n, (int(floor(floor((x0 + r) / CELL_M) / n)) + 1) * n - 1
    j0, j1 = int(floor(floor((y0 - r) / CELL_M) / n)) * n, (int(floor(floor((y0 + r) / CELL_M) / n)) + 1) * n - 1
    return {"x0": x0, "y0": y0, "r": r, "lat": lat, "ground": cos(radians(lat)), "radius_m": float(radius_m),
            "i0": i0, "j0": j0, "ni": i1 - i0 + 1, "nj": j1 - j0 + 1}


def _circle_mask(geo: Dict[str, Any], x0: float, y0: float, r: float) -> np.ndarray:
    """Cells of the lattice box whose centre lies within ``r`` (3857 metres) of ``(x0, y0)``."""
    xs = (geo["i0"] + np.arange(geo["ni"]) + 0.5) * CELL_M
    ys = (geo["j0"] + np.arange(geo["nj"]) + 0.5) * CELL_M
    return (xs[None, :] - x0) ** 2 + (ys[:, None] - y0) ** 2 <= r * r


def _tile_bbox(tx: int, ty: int, tile_m: float) -> Tuple[float, float, float, float]:
    return (tx * tile_m, ty * tile_m, (tx + 1) * tile_m, (ty + 1) * tile_m)


def _cells_per_tile(tile_m: float) -> int:
    return int(round(tile_m / CELL_M))


def _lattice_tiles(geo: Dict[str, Any], tile_m: float, circle: np.ndarray) -> List[Tuple[int, int]]:
    """``(tx, ty)`` of every tile holding at least one study cell, nearest to the centre first."""
    n = _cells_per_tile(tile_m)
    found = []
    for tx in range(int(floor((geo["x0"] - geo["r"]) / tile_m)), int(floor((geo["x0"] + geo["r"]) / tile_m)) + 1):
        for ty in range(int(floor((geo["y0"] - geo["r"]) / tile_m)), int(floor((geo["y0"] + geo["r"]) / tile_m)) + 1):
            i_lo, j_lo = max(tx * n - geo["i0"], 0), max(ty * n - geo["j0"], 0)
            i_hi, j_hi = min((tx + 1) * n - geo["i0"], geo["ni"]), min((ty + 1) * n - geo["j0"], geo["nj"])
            if i_lo < i_hi and j_lo < j_hi and circle[j_lo:j_hi, i_lo:i_hi].any():
                x_lo, y_lo, x_hi, y_hi = _tile_bbox(tx, ty, tile_m)
                found.append((round(hypot((x_lo + x_hi) / 2 - geo["x0"], (y_lo + y_hi) / 2 - geo["y0"]), 3), ty, tx))
    found.sort()
    return [(tx, ty) for _, ty, tx in found]


def _paste(dst: np.ndarray, src: np.ndarray, i_off: int, j_off: int) -> None:
    """Copy ``src`` (south-up) into ``dst`` with its lower-left cell at ``(i_off, j_off)``; clips."""
    nj, ni = dst.shape[-2:]
    sj, si = src.shape[-2:]
    j_lo, i_lo = max(j_off, 0), max(i_off, 0)
    j_hi, i_hi = min(j_off + sj, nj), min(i_off + si, ni)
    if j_lo < j_hi and i_lo < i_hi:
        dst[..., j_lo:j_hi, i_lo:i_hi] = src[..., j_lo - j_off:j_hi - j_off, i_lo - i_off:i_hi - i_off]


def estimate_evidence_requests(center: Tuple[float, float], radius_m: float) -> Dict[str, Any]:
    """Upper bound of the WMS requests a run would send (plan tiles are exact, parcel tiles capped)."""
    cfg = EVIDENCE_CONFIG
    geo = _evidence_geometry(center, radius_m)
    circle = _circle_mask(geo, geo["x0"], geo["y0"], geo["r"])
    plan = min(len(_lattice_tiles(geo, cfg["plan_tile_m"], circle)), int(cfg["max_plan_tiles"]))
    return {"plan_tiles": plan, "parcel_tiles_max": int(cfg["max_parcel_tiles"]),
            "requests_max": min(plan + int(cfg["max_parcel_tiles"]), int(cfg["max_requests"])),
            "area_km2": pi * float(radius_m) ** 2 / 1e6}


def _legend_lut(legend: List[Dict[str, Any]], tolerance: float) -> np.ndarray:
    """Class (or -1) for every 5-bit-per-channel RGB value: one table look-up per pixel."""
    idx = np.arange(32768)
    rgb = np.stack([((idx >> 10) & 31) * 8 + 4, ((idx >> 5) & 31) * 8 + 4, (idx & 31) * 8 + 4],
                   axis=1).astype(np.float32)
    best = np.full(idx.shape, np.inf, dtype=np.float32)
    lut = np.full(idx.shape, -1, dtype=np.int8)
    for k, entry in enumerate(legend):
        dist = np.sqrt(((rgb - np.asarray(entry["rgb"], dtype=np.float32)) ** 2).sum(axis=1))
        closer = (dist < best) & (dist <= tolerance)
        best[closer] = dist[closer]
        lut[closer] = k
    return lut


def _is_red_family(r: int, g: int, b: int) -> bool:
    """Red or pink at any strength: red is the channel maximum, reasonably saturated and bright, hue
    between magenta-pink (-30°) and red-orange (+15°). Orange, brown, yellow, green, blue and purple
    are not. Scalar twin of the vectorised test in :func:`_plan_tile_shares`."""
    mx, mn = max(r, g, b), min(r, g, b)
    d = mx - mn
    return r == mx and mx >= 128 and 5 * d >= mx and 2 * (g - b) >= -d and 4 * (g - b) <= d


def _plan_tile_shares(rgba: np.ndarray, lut: np.ndarray, n_classes: int, cells: int) -> Dict[str, Any]:
    """Pixels per cell of every legend class and of **red** (the last channel), plus the painted /
    explained counts, the colour of the red pixels and a coarse colour histogram (diagnostics).

    Red is recognised by hue, not by an exact legend colour: the peak colour is the user's own
    definition ("สีแดง คือ โซนสูงสุด"), and Longdo's real shade is not known here.
    """
    if rgba.ndim != 3 or rgba.shape[2] != 4 or rgba.shape[0] != rgba.shape[1] or rgba.shape[0] % cells:
        raise ValueError(f"unexpected plan image shape {rgba.shape}")
    painted = rgba[..., 3] > PARCEL_CONFIG["alpha_threshold"]
    key = ((rgba[..., 0] >> 3).astype(np.int32) << 10) | ((rgba[..., 1] >> 3).astype(np.int32) << 5) \
        | (rgba[..., 2] >> 3).astype(np.int32)
    cls = lut[key]
    cls[~painted] = -1
    rgb = rgba[..., :3].astype(np.int16)
    mx, mn = rgb.max(axis=2), rgb.min(axis=2)
    d, gb = mx - mn, rgb[..., 1] - rgb[..., 2]
    red = painted & (rgb[..., 0] == mx) & (mx >= 128) & (5 * d >= mx) & (2 * gb >= -d) & (4 * gb <= d)
    px = rgba.shape[0] // cells
    shares = np.zeros((n_classes + 1, cells, cells), dtype=np.uint16)
    for k in range(n_classes):
        shares[k] = (cls == k).reshape(cells, px, cells, px).sum(axis=(1, 3))
    shares[n_classes] = red.reshape(cells, px, cells, px).sum(axis=(1, 3))
    sample = painted[::4, ::4]
    keys4 = (((rgba[::4, ::4, 0] >> 4).astype(np.int32) << 8) | ((rgba[::4, ::4, 1] >> 4).astype(np.int32) << 4)
             | (rgba[::4, ::4, 2] >> 4).astype(np.int32))[sample]
    values, counts = np.unique(keys4, return_counts=True)
    return {"shares": shares[:, ::-1, :], "painted": int(painted.sum()), "explained": int((cls >= 0).sum()),
            "pixels": int(painted.size), "red_pixels": int(red.sum()),
            "red_sum": rgb[red].sum(axis=0).astype(np.int64) if red.any() else np.zeros(3, dtype=np.int64),
            "colours": {int(v): int(n) for v, n in zip(values, counts)}}


def _peak_classes(legend: List[Dict[str, Any]]) -> List[int]:
    """Legend classes that count as the peak zone besides red-by-hue: those flagged ``commercial``."""
    return [k for k, c in enumerate(legend) if c.get("commercial")]


def _peak_zone(shares: np.ndarray, legend: List[Dict[str, Any]], cell_px2: int) -> Optional[Dict[str, Any]]:
    """The red zones of the loaded plan tiles: cells where ≥ ``peak_cell_share`` of the pixels are red
    (by hue) or a legend class flagged ``commercial``, grouped 8-connected; groups below
    ``zone_min_cells`` are dropped, ``None`` when none is left. Zones are whole: the study circle does
    not clip them (see :func:`_zones_in_scope`). A lower colour is never promoted when there is no red."""
    cfg = EVIDENCE_CONFIG
    classes = _peak_classes(legend) + [shares.shape[0] - 1]          # the last channel is red-by-hue
    mask = shares[classes].sum(axis=0) >= cfg["peak_cell_share"] * cell_px2
    if not mask.any():
        return None
    labels, n = ndi.label(mask, structure=np.ones((3, 3), dtype=bool))
    sizes = np.bincount(labels.ravel(), minlength=n + 1)[1:]
    big = np.flatnonzero(sizes >= cfg["zone_min_cells"]) + 1
    if not big.size:
        return None
    return {"classes": classes, "labels": labels, "big": big, "sizes": sizes, "mask": np.isin(labels, big)}


def _zones_in_scope(peak: Dict[str, Any], circle: np.ndarray) -> Optional[Dict[str, Any]]:
    """Keep the red zones that reach into the study circle — whole. ``None`` = no red inside the radius."""
    inside = np.unique(peak["labels"][circle & (peak["labels"] > 0)])
    big = np.intersect1d(peak["big"], inside)
    if not big.size:
        return None
    return {**peak, "big": big, "mask": np.isin(peak["labels"], big)}


def _mask_polygon(mask: np.ndarray, geo: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """GeoJSON (lon/lat, 5 dp) of a cell mask: row runs → boxes → union → light simplification."""
    boxes = []
    for j in np.flatnonzero(mask.any(axis=1)):
        d = np.diff(np.concatenate(([False], mask[j], [False])).astype(np.int8))
        for s, e in zip(np.flatnonzero(d == 1), np.flatnonzero(d == -1)):
            boxes.append(box((geo["i0"] + s) * CELL_M, (geo["j0"] + j) * CELL_M,
                             (geo["i0"] + e) * CELL_M, (geo["j0"] + j + 1) * CELL_M))
    if not boxes:
        return None
    geom = unary_union(boxes).simplify(CELL_M / 4.0)
    polys = [geom] if geom.geom_type == "Polygon" else [g for g in getattr(geom, "geoms", []) if g.geom_type == "Polygon"]

    def ring(coords) -> List[List[float]]:
        arr = np.asarray(coords, dtype=float)
        lon, lat = _WEB_MERCATOR_INV.transform(arr[:, 0], arr[:, 1])
        return [[round(float(a), 5), round(float(b), 5)] for a, b in zip(lon, lat)]

    rings = [[ring(p.exterior.coords)] + [ring(r.coords) for r in p.interiors] for p in polys]
    if not rings:
        return None
    return ({"type": "Polygon", "coordinates": rings[0]} if len(rings) == 1
            else {"type": "MultiPolygon", "coordinates": rings})


def _cell_lonlat(geo: Dict[str, Any], col: float, row: float) -> Tuple[float, float]:
    """``(lat, lon)`` of a (fractional) lattice-local cell position; ``+0.5`` is the cell centre."""
    lon, lat = _WEB_MERCATOR_INV.transform((geo["i0"] + col + 0.5) * CELL_M, (geo["j0"] + row + 0.5) * CELL_M)
    return float(lat), float(lon)


def _dominant_colours(histogram: Dict[int, int], legend: List[Dict[str, Any]], top: int = 6) -> List[Dict[str, Any]]:
    """Most common painted colours of the plan tiles (4 bits per channel), each with the legend class
    it matches (``None`` = unknown) and whether it counts as red — what to read when colours look off."""
    total = sum(histogram.values()) or 1
    out = []
    for key4, count in sorted(histogram.items(), key=lambda kv: (-kv[1], kv[0]))[:top]:
        r, g, b = ((key4 >> 8) & 15) * 16 + 8, ((key4 >> 4) & 15) * 16 + 8, (key4 & 15) * 16 + 8
        distances = [hypot(hypot(r - c["rgb"][0], g - c["rgb"][1]), b - c["rgb"][2]) for c in legend]
        best = min(range(len(legend)), key=lambda k: (distances[k], k), default=None)
        matched = legend[best]["name"] if best is not None and distances[best] <= ZONING_COLOR_TOLERANCE else None
        out.append({"hex": "#%02x%02x%02x" % (r, g, b), "share": count / total, "legend": matched,
                    "red": _is_red_family(r, g, b)})
    return out


def _zone_records(zone: Dict[str, Any], geo: Dict[str, Any], legend: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Largest zones of the peak class first (cells desc, then raster order)."""
    cfg = EVIDENCE_CONFIG
    labels, sizes = zone["labels"], zone["sizes"]
    first = {int(lab): int(np.flatnonzero(labels == lab)[0]) for lab in zone["big"]}
    order = sorted((int(lab) for lab in zone["big"]), key=lambda lab: (-int(sizes[lab - 1]), first[lab]))
    cell_km2 = (CELL_M * geo["ground"]) ** 2 / 1e6
    out = []
    for rank, lab in enumerate(order[: int(cfg["zone_top"])], start=1):
        rows, cols = np.nonzero(labels == lab)
        lat, lon = _cell_lonlat(geo, float(cols.mean()), float(rows.mean()))
        out.append({"rank": rank, "lat": lat, "lon": lon, "cells": int(sizes[lab - 1]),
                    "area_km2": float(sizes[lab - 1] * cell_km2), "polygon": _mask_polygon(labels == lab, geo)})
    return out


def _parcel_tile_scores(rgba: np.ndarray, m_per_px: float, cells: int) -> Optional[Dict[str, Any]]:
    """Per-cell frequency of small / ตึกแถว lots in one parcel tile (``None`` = no measurable lots).

    ``cover_*`` is the share of the cell's ground area taken by those lots — a few shophouses
    beside farmland stay low, a shophouse block saturates. Cells without drawn lines are no data.
    """
    cfg, ev = PARCEL_CONFIG, EVIDENCE_CONFIG
    if rgba.ndim != 3 or rgba.shape[2] != 4 or rgba.shape[0] != rgba.shape[1] or rgba.shape[0] % cells:
        raise ValueError(f"unexpected parcel image shape {rgba.shape}")
    parcels = _parcel_cells(rgba, m_per_px)
    if not parcels["data"]:
        return None
    px = rgba.shape[0] // cells
    cell_m2 = (px * m_per_px) ** 2
    area, aspect = parcels["area_m2"], parcels["aspect"]
    flat = (np.clip((parcels["cy"] // px).astype(int), 0, cells - 1) * cells
            + np.clip((parcels["cx"] // px).astype(int), 0, cells - 1))
    low, high = cfg["shophouse_area_m2"]
    small = area < cfg["small_cell_m2"]
    shop = (area >= low) & (area <= high) & (aspect >= cfg["shophouse_min_aspect"])

    def cover(sel: np.ndarray) -> np.ndarray:
        return np.bincount(flat[sel], weights=area[sel], minlength=cells * cells).reshape(cells, cells) / cell_m2

    cover_small, cover_shop = cover(small), cover(shop)
    ink_cell = parcels["ink"].reshape(cells, px, cells, px).mean(axis=(1, 3))
    ink_scaled = np.clip((ink_cell - cfg["ink_low"]) / (cfg["ink_high"] - cfg["ink_low"]), 0, 1)
    w, ref = cfg["score_weights"], ev["cover_ref"]
    score = (w["shophouse"] * np.clip(cover_shop / ref, 0, 1) + w["small"] * np.clip(cover_small / ref, 0, 1)
             + w["ink"] * ink_scaled)
    score[ink_cell < cfg["min_ink_ratio"]] = np.nan
    return {"score": score[::-1], "cover_small": cover_small[::-1], "cover_shop": cover_shop[::-1],
            "lots": int(area.size)}


def _smooth_nan(score: np.ndarray, size: int) -> np.ndarray:
    """Box mean over the cells that have data; cells without data stay NaN."""
    ok = np.isfinite(score)
    num = ndi.uniform_filter(np.where(ok, score, 0.0), size=size, mode="constant")
    den = ndi.uniform_filter(ok.astype(float), size=size, mode="constant")
    out = np.full(score.shape, np.nan)
    good = ok & (den > 1e-9)
    out[good] = num[good] / den[good]
    return out


def _hot_threshold(values: np.ndarray) -> float:
    """Smoothed score from which a cell is hot: ``hot_score`` when the red zone is that dense, else the
    densest quarter of its scored cells (never below ``hot_floor``). Real lot patterns are far less
    regular than the synthetic ones the 0.5 was set on, so "ถี่" must also work relative to the zone;
    how convincing the cluster is in absolute terms is left to the confidence."""
    cfg = EVIDENCE_CONFIG
    return float(min(cfg["hot_score"], max(cfg["hot_floor"], np.quantile(values, cfg["hot_quantile"]))))


def _clusters_of(
    smooth: np.ndarray,
    zones: Dict[str, Any],
    fields: Dict[str, np.ndarray],
    scanned: np.ndarray,
    geo: Dict[str, Any],
) -> Dict[str, Any]:
    """Every dense cluster of the red zones, whole — **independent of the study circle**.

    Hot cells are decided zone by zone (dense in absolute terms, or among the densest quarter of *that
    zone*), so a zone that enters when the radius grows never moves another zone's threshold, and a
    larger radius can only add candidates. ``touches_boundary`` = the cluster runs into a part of its
    zone that was not scanned (tile budget / failed tile). Choosing among them is :func:`_pick_cluster`.
    """
    cfg = EVIDENCE_CONFIG
    three = np.ones((3, 3), dtype=bool)
    labels_z, zone = zones["labels"], zones["mask"]
    finite = np.isfinite(smooth)
    nj, ni = smooth.shape
    hot = np.zeros(smooth.shape, dtype=bool)
    thr_map = np.full(smooth.shape, np.nan)
    objects = ndi.find_objects(labels_z)
    for lab in zones["big"]:
        box_ = objects[int(lab) - 1] if int(lab) <= len(objects) else None
        if box_ is None:
            continue
        sl = (slice(max(box_[0].start - 1, 0), min(box_[0].stop + 1, nj)),
              slice(max(box_[1].start - 1, 0), min(box_[1].stop + 1, ni)))
        scope = ndi.binary_dilation(labels_z[sl] == lab, structure=three) & finite[sl]
        if not scope.any():
            continue
        thr = _hot_threshold(smooth[sl][scope])
        mine = scope & (np.where(finite[sl], smooth[sl], -1.0) >= thr)
        hot[sl] |= mine
        thr_map[sl][mine] = thr
    labels, n = ndi.label(hot, structure=three)
    if n == 0:
        return {"clusters": [], "labels": labels}
    index = np.arange(1, n + 1)
    weights = np.where(hot, smooth, 0.0)
    cells = np.asarray(ndi.sum(hot, labels, index), dtype=float)
    mass = np.asarray(ndi.sum(weights, labels, index), dtype=float)
    first = np.asarray(ndi.minimum(np.arange(hot.size).reshape(hot.shape), labels, index), dtype=float)
    rim = ndi.binary_dilation(zone & ~scanned, structure=three)
    cut = np.asarray(ndi.maximum(rim.astype(float), labels, index))
    in_zone = np.asarray(ndi.mean(zone.astype(float), labels, index))
    cover_small = np.asarray(ndi.mean(np.where(hot, fields["cover_small"], 0.0), labels, index))
    cover_shop = np.asarray(ndi.mean(np.where(hot, fields["cover_shop"], 0.0), labels, index))
    centres = ndi.center_of_mass(weights, labels, index)
    cell_ha = (CELL_M * geo["ground"]) ** 2 / 1e4
    clusters = []
    for k in range(n):
        if cells[k] < cfg["cluster_min_cells"]:
            continue
        row, col = centres[k]
        lat, lon = _cell_lonlat(geo, float(col), float(row))
        clusters.append({
            "lat": lat, "lon": lon, "cells": int(cells[k]), "area_ha": float(cells[k] * cell_ha),
            "score": float(mass[k] / cells[k]), "mass": float(mass[k]),
            "cover_small": float(cover_small[k]), "cover_shop": float(cover_shop[k]),
            "in_zone": float(in_zone[k]) >= 0.5, "touches_boundary": bool(cut[k] > 0),
            "threshold": float(thr_map.flat[int(first[k])]),
            "_x": (geo["i0"] + float(col) + 0.5) * CELL_M, "_y": (geo["j0"] + float(row) + 0.5) * CELL_M,
            "_first": float(first[k]), "_label": k + 1})
    return {"clusters": clusters, "labels": labels}


def _pick_cluster(
    clusters: List[Dict[str, Any]], geo: Dict[str, Any], centre: Tuple[float, float], radius_m: float,
    top: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """The circle (``centre`` in 3857 metres, ``radius_m`` on the ground) admits clusters by centroid;
    they are ranked by ``mass / (1 + (distance / reach_m)²)`` — a smooth prior toward the study centre
    that does not depend on the radius, so a far village needs ≈ 10× the mass to beat a town at the
    centre. Ties: raster order."""
    reach = EVIDENCE_CONFIG["reach_m"]
    out = []
    for c in clusters:
        d = hypot(c["_x"] - centre[0], c["_y"] - centre[1]) * geo["ground"]
        if d <= radius_m:
            out.append({**c, "distance_m": float(d), "weighted_mass": float(c["mass"] / (1.0 + (d / reach) ** 2))})
    out.sort(key=lambda c: (-round(c["weighted_mass"], 12), c["_first"]))
    for rank, c in enumerate(out, start=1):
        c["rank"] = rank
    return out if top is None else out[: int(top)]


def _evidence_stability(clusters: List[Dict[str, Any]], geo: Dict[str, Any], best: Dict[str, Any]) -> Dict[str, Any]:
    """How far the winning cluster moves when the study circle changes (radius ×0.8 and ×1.2, centre ±0.2R, at most 1 km).

    Re-picks among the clusters already read — no request, so growth (×1.2) only sees red zones that were
    already scanned. Indicative, like the road probe.
    """
    cfg = EVIDENCE_CONFIG["stability"]
    x0, y0, radius = geo["x0"], geo["y0"], geo["radius_m"]
    step = min(cfg["shift"] * geo["r"], cfg["shift_max_m"] / geo["ground"])   # 3857 m; ≤ 1 km on the ground
    cases = [(x0, y0, cfg["shrink"] * radius), (x0, y0, cfg["grow"] * radius)]
    cases += [(x0 + dx * step, y0 + dy * step, radius) for dx, dy in ((0, 1), (1, 0), (0, -1), (-1, 0))]
    drifts = []
    for cx, cy, cr in cases:
        found = _pick_cluster(clusters, geo, (cx, cy), cr, top=1)
        drifts.append(hypot(found[0]["_x"] - best["_x"], found[0]["_y"] - best["_y"]) * geo["ground"]
                      if found else radius)
    worst = max(drifts)
    ratio = worst / max(radius, 1e-9)
    level = "stable" if ratio <= cfg["stable"] else ("check" if ratio <= cfg["check"] else "unstable")
    return {"cases": len(cases), "max_drift_m": float(worst), "median_drift_m": float(np.median(drifts)),
            "max_drift_ratio": float(ratio), "level": level}


def classify_anchor_confidence(
    anchor: Dict[str, Any],
    road_anchors: List[Dict[str, Any]],
    *,
    zoning_ok: Optional[bool],
    parcel_ok: Optional[bool],
    coverage: float,
    peak: Optional[Dict[str, Any]],
    cluster: Optional[Dict[str, Any]],
    stability_levels: List[Optional[str]],
    cfg: Dict[str, Any],
) -> Dict[str, Any]:
    """HIGH needs independent signals to agree: roads (an anchor within ``agree_radius_m``), the
    official plan (the peak colour is พาณิชยกรรม and the anchor sits in it) and the parcel
    structure (a dense cluster). Reasons are returned in Thai for the UI."""
    conf = cfg["confidence"]
    reasons: List[str] = []
    nearest = min((calculate_distance_meters(anchor["lat"], anchor["lon"], a["lat"], a["lon"])
                   for a in road_anchors), default=None)
    roads_ok = None if nearest is None else nearest <= cfg["agree_radius_m"]
    reasons.append(
        f"ถนน: anchor ถนนที่ใกล้สุดห่าง {nearest:,.0f} ม." + (" (สอดคล้อง)" if roads_ok else " (ไม่สอดคล้อง)")
        if nearest is not None else "ถนน: ไม่มี anchor อ้างอิง")
    if zoning_ok is None or not peak:
        reasons.append("ผังเมือง: ไม่มีข้อมูล (นอกพื้นที่ผังเมืองหรืออ่านภาพ/สีไม่ได้)")
    else:
        label = f"{peak['name']}" + (" (พาณิชยกรรม)" if peak.get("commercial") else "")
        reasons.append(f"ผังเมือง: สีสูงสุดที่พบ {label} {peak['area_km2']:.2f} ตร.กม."
                       + (" — anchor อยู่ในโซนนี้" if zoning_ok else " — anchor อยู่นอกโซนพาณิชยกรรม"))
    if cluster:
        reasons.append(f"แปลงที่ดิน: cluster แปลงเล็กถี่ {cluster['cells']} เซลล์ (~{cluster['area_ha']:,.0f} เฮกตาร์) "
                       f"คะแนน {cluster['score']:.2f}" + ("" if parcel_ok else " (ไม่เด่น)"))
    elif parcel_ok is False:
        reasons.append("แปลงที่ดิน: ไม่พบ cluster ที่ถี่พอในโซน")
    else:
        reasons.append("แปลงที่ดิน: ไม่มีข้อมูล")
    touches = bool(cluster and cluster.get("touches_boundary"))
    if touches:
        reasons.append("cluster ต่อเนื่องเข้าส่วนของโซนแดงที่ยังไม่ได้สแกน (เกินโควตาไทล์/ดึงไม่สำเร็จ)")
    unstable = "unstable" in stability_levels
    if unstable:
        reasons.append("ความนิ่ง: anchor ขยับมากเมื่อวงศึกษาเปลี่ยน (ไม่นิ่ง)")
    agreeing = sum(1 for f in (roads_ok, zoning_ok, parcel_ok) if f)
    if coverage >= conf["coverage_min"] and agreeing == 3 and not unstable and not touches:
        level = "HIGH"
    elif coverage >= conf["coverage_medium"] and agreeing >= 2:
        level = "MEDIUM"
    else:
        level = "LOW"
    return {"level": level, "reasons": reasons, "coverage": coverage,
            "signals": {"roads": roads_ok, "zoning": zoning_ok, "parcel": parcel_ok},
            "nearest_road_anchor_m": nearest}
