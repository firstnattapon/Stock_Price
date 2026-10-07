"""Capture real Longdo WMS windows so the CBD evidence stage can be calibrated offline.

Run this on a machine that can reach ms.longdo.com (the CI/sandbox cannot). It downloads, exactly as
served (no re-encoding), the same GetMap windows the evidence stage uses:

  * a city-plan (cityplan_dpt) overview of the whole study circle,
  * per named point: parcel (dol) windows and city-plan windows at several window sizes,
  * GetCapabilities and GetLegendGraphic (text / PNG) so layer names, zoom limits and legend colours
    can be read off,

into ``Geoapify_Map/fixtures/wms/`` with a ``manifest.json`` (no API key is ever written), then prints
the dominant opaque colours of every city-plan window next to the nearest provisional legend class —
that table is what you turn into ``Geoapify_Map/cityplan_legend.json`` — and the parcel features of
every dol window, so thresholds can be checked against what you see on the map.

python scripts/capture_wms_fixtures.py \
    --study-center 20.219443 100.403630 --radius-km 10 \
    --point core 20.2194 100.4036 --point mid 20.2300 100.4200 --point outskirts 20.2600 100.4700

Pick the points by eye: ``core`` = the town centre / old market (ตึกแถว), ``mid`` = a residential
street a few km out, ``outskirts`` = fields or new subdivisions. Commit the resulting folder.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import requests

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("rent_gradient", ROOT / "pages/Rent_Gradient.py")
page = importlib.util.module_from_spec(spec)
spec.loader.exec_module(page)

DEFAULT_OUT = ROOT / "Geoapify_Map" / "fixtures" / "wms"
PARCEL_WINDOWS_M = (500.0, 1000.0, 2000.0)   # several sizes: shows where the server stops drawing parcels
PLAN_WINDOWS_M = (500.0, 1500.0)
TIMEOUT_S = 30


def get(params: Dict[str, Any], session: Any = requests) -> Dict[str, Any]:
    """One WMS request; never raises. ``content`` is the raw body."""
    try:
        response = session.get(page.LONGDO_WMS_URL, params=params, timeout=TIMEOUT_S,
                               headers={"User-Agent": "Rent_Gradient-fixture-capture/1.0"})
        return {"status": response.status_code, "content_type": response.headers.get("Content-Type", ""),
                "content": response.content, "error": None}
    except Exception as exc:
        return {"status": None, "content_type": "", "content": b"", "error": f"{type(exc).__name__}: {exc}"}


def top_colours(rgba: np.ndarray, count: int = 8) -> List[Dict[str, Any]]:
    """Dominant opaque colours (16-level quantised histogram) with the nearest provisional class."""
    opaque = rgba[rgba[..., 3] >= 200][:, :3].astype(np.int32)
    if not len(opaque):
        return []
    key = (opaque[:, 0] // 16) * 256 + (opaque[:, 1] // 16) * 16 + (opaque[:, 2] // 16)
    values, inverse, counts = np.unique(key, return_inverse=True, return_counts=True)
    order = np.argsort(-counts)[:count]
    legend = page.CITYPLAN_PROVISIONAL_LEGEND
    rows = []
    for index in order:
        mean = opaque[inverse == index].mean(axis=0)
        distances = [float(np.linalg.norm(mean - np.array(c["rgb"]))) for c in legend]
        nearest = int(np.argmin(distances))
        rows.append({
            "rgb": [int(round(v)) for v in mean],
            "hex": "#%02x%02x%02x" % tuple(int(round(v)) for v in mean),
            "share_of_opaque": float(counts[index] / len(opaque)),
            "nearest_provisional_class": legend[nearest]["name"],
            "distance_to_it": distances[nearest],
        })
    return rows


def describe_image(content: bytes, kind: str, window_m: float, lat: float) -> Dict[str, Any]:
    """Decode a saved window and measure the things the evidence features depend on."""
    import io

    from PIL import Image

    rgba = np.asarray(Image.open(io.BytesIO(content)).convert("RGBA"))
    alpha = rgba[..., 3]
    info: Dict[str, Any] = {
        "size": [int(rgba.shape[1]), int(rgba.shape[0])],
        "transparent_share": float((alpha == 0).mean()),
        "min_alpha": int(alpha.min()),
        "m_per_px": window_m / rgba.shape[1],
    }
    if kind == "parcel":
        features = page.parcel_features(rgba, info["m_per_px"])
        info["parcel_features"] = {k: v for k, v in features.items() if isinstance(v, (int, float, bool, str))}
    else:
        info["top_colours"] = top_colours(rgba)
    return info


def capture(
    out_dir: Path,
    study_center: Tuple[float, float],
    radius_m: float,
    points: List[Tuple[str, float, float]],
    px: int = 1024,
    delay_s: float = 0.4,
    session: Any = requests,
    parcel_windows: Tuple[float, ...] = PARCEL_WINDOWS_M,
    plan_windows: Tuple[float, ...] = PLAN_WINDOWS_M,
) -> Dict[str, Any]:
    """Download everything, write ``manifest.json`` and return it."""
    out_dir.mkdir(parents=True, exist_ok=True)
    jobs: List[Dict[str, Any]] = [{
        "name": "overview", "kind": "overview", "layer": page.EVIDENCE_CONFIG["plan_layer"],
        "lat": study_center[0], "lon": study_center[1], "window_m": 2.0 * radius_m,
    }]
    for name, lat, lon in points:
        for window in parcel_windows:
            jobs.append({"name": name, "kind": "parcel", "layer": page.EVIDENCE_CONFIG["parcel_layer"],
                         "lat": lat, "lon": lon, "window_m": window})
        for window in plan_windows:
            jobs.append({"name": name, "kind": "plan", "layer": page.EVIDENCE_CONFIG["plan_layer"],
                         "lat": lat, "lon": lon, "window_m": window})
    manifest: Dict[str, Any] = {
        "captured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "source": "Longdo Map WMS (mapproxy)", "study_center": list(study_center), "radius_m": radius_m,
        "px": px, "files": [], "documents": [], "errors": [],
    }
    for job in jobs:
        bbox = page._wms_window(job["lat"], job["lon"], job["window_m"])
        params = page._wms_params(job["layer"], bbox, px)
        reply = get(params, session)
        time.sleep(delay_s)
        label = f"{job['name']}_{job['layer']}_{job['window_m']:g}m"
        if reply["error"] or reply["status"] != 200 or "image" not in reply["content_type"]:
            manifest["errors"].append({"file": label, "status": reply["status"],
                                       "content_type": reply["content_type"], "error": reply["error"],
                                       "body_start": reply["content"][:200].decode("utf-8", "replace")})
            continue
        path = out_dir / f"{label}.png"
        path.write_bytes(reply["content"])
        entry = {
            "file": path.name, "name": job["name"], "kind": job["kind"], "layer": job["layer"],
            "lat": job["lat"], "lon": job["lon"], "window_m": job["window_m"], "px": px,
            "bbox_3857": list(bbox), "bytes": len(reply["content"]),
            "sha256": hashlib.sha256(reply["content"]).hexdigest(),
        }
        try:
            entry.update(describe_image(reply["content"], job["kind"], job["window_m"], job["lat"]))
        except Exception as exc:
            entry["describe_error"] = f"{type(exc).__name__}: {exc}"
        manifest["files"].append(entry)

    documents = [
        ("capabilities.xml", {"service": "WMS", "version": "1.1.1", "request": "GetCapabilities"}),
        ("legend_cityplan_dpt.png", {
            "service": "WMS", "version": "1.1.1", "request": "GetLegendGraphic",
            "layer": page.EVIDENCE_CONFIG["plan_layer"], "format": "image/png"}),
    ]
    for filename, params in documents:
        reply = get(params, session)
        time.sleep(delay_s)
        if reply["error"] or reply["status"] != 200 or not reply["content"]:
            manifest["errors"].append({"file": filename, "status": reply["status"], "error": reply["error"]})
            continue
        (out_dir / filename).write_bytes(reply["content"])
        manifest["documents"].append({"file": filename, "bytes": len(reply["content"]),
                                      "content_type": reply["content_type"]})
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def print_report(manifest: Dict[str, Any]) -> None:
    print(f"\ncaptured {len(manifest['files'])} windows, {len(manifest['documents'])} documents, "
          f"{len(manifest['errors'])} errors")
    for error in manifest["errors"]:
        print(f"  ! {error['file']}: status {error.get('status')} {error.get('error') or error.get('body_start', '')[:80]}")
    print("\n== dol (parcel) windows ==")
    print(f"{'file':<44}{'m/px':>6}{'transp.':>9}{'ink':>7}{'cell m2':>9}{'small':>7}{'shop':>7}{'score':>7}")
    for e in manifest["files"]:
        if e["kind"] != "parcel":
            continue
        f = e.get("parcel_features", {})
        if f.get("data"):
            print(f"{e['file']:<44}{e['m_per_px']:>6.2f}{e['transparent_share']:>9.0%}{f['ink_ratio']:>7.1%}"
                  f"{f['median_cell_m2']:>9.0f}{f['small_share']:>7.0%}{f['shophouse_share']:>7.0%}{f['score']:>7.2f}")
        else:
            print(f"{e['file']:<44}{e['m_per_px']:>6.2f}{e['transparent_share']:>9.0%}  "
                  f"no data (ink {f.get('ink_ratio', 0.0):.1%}, cells {f.get('cell_count', 0)})")
    print("\n== city-plan windows: dominant opaque colours (build Geoapify_Map/cityplan_legend.json from these) ==")
    for e in manifest["files"]:
        if e["kind"] == "parcel":
            continue
        print(f"{e['file']}  (transparent {e['transparent_share']:.0%})")
        for c in e.get("top_colours", []):
            print(f"    {c['hex']}  {c['share_of_opaque']:>6.1%}   nearest provisional: "
                  f"{c['nearest_provisional_class']} (distance {c['distance_to_it']:.0f})")
    print("\nNext: read legend_cityplan_dpt.png / capabilities.xml, write cityplan_legend.json "
          '({"classes": [{"name", "rgb", "weight", "commercial"}]}), commit the fixtures folder.')


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--study-center", type=float, nargs=2, metavar=("LAT", "LON"),
                        default=(page.DEFAULT_CONFIG["LAT"], page.DEFAULT_CONFIG["LON"]))
    parser.add_argument("--radius-km", type=float, default=10.0)
    parser.add_argument("--point", nargs=3, action="append", metavar=("NAME", "LAT", "LON"),
                        help="repeatable; default: one 'core' point at the study centre")
    parser.add_argument("--px", type=int, default=page.EVIDENCE_CONFIG["px"])
    parser.add_argument("--delay", type=float, default=0.4, help="seconds between requests")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)
    center = (float(args.study_center[0]), float(args.study_center[1]))
    points = ([(n, float(a), float(b)) for n, a, b in args.point] if args.point
              else [("core", center[0], center[1])])
    manifest = capture(args.out, center, args.radius_km * 1000.0, points, px=args.px, delay_s=args.delay)
    print_report(manifest)
    print(f"\nwrote {args.out}")
    return 0 if manifest["files"] else 1


if __name__ == "__main__":
    sys.exit(main())
