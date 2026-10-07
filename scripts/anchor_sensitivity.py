"""Sensitivity of the road-network anchor to the study area the user picks.

The anchor is the centre of the road network *inside the chosen circle*, so it can
move when the circle moves. This script re-runs the same search on one fixed,
already-downloaded graph with the circle shifted and rescaled, and reports how far
the anchor drifts. A small drift is necessary (not sufficient) evidence that the
anchor reflects the town rather than the user's choice of circle.

python scripts/anchor_sensitivity.py --graph cache/osm_graph_<hash>.pkl \
    --lat 20.219443 --lon 100.403630 --radius-km 10 --output cache/sensitivity.json

--graph accepts a GraphML file or an ``osm_graph_*.pkl`` cache entry (read through
the page's allow-list unpickler). Optional --reference LAT LON is a known centre
supplied by someone who knows the town; it is never inferred from the output.
Perturbed circles that leave the downloaded footprint are flagged, not hidden.
"""
import argparse
import importlib.util
import json
from pathlib import Path
import sys

import numpy as np
from pyproj.enums import TransformDirection

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("rent_gradient", ROOT / "pages/Rent_Gradient.py")
page = importlib.util.module_from_spec(spec)
spec.loader.exec_module(page)

DIRECTIONS = {"N": (0.0, 1.0), "E": (1.0, 0.0), "S": (0.0, -1.0), "W": (-1.0, 0.0)}


def graph_extent_m(graph, center):
    """Largest metric distance from ``center`` to any road node (the footprint radius)."""
    projection = page._anchor_projection(*center)
    lonlat = np.array([(float(d["x"]), float(d["y"])) for _, d in graph.nodes(data=True)])
    xy = np.column_stack(projection.transform(lonlat[:, 0], lonlat[:, 1]))
    return float(np.linalg.norm(xy, axis=1).max())


def shifted_center(center, east_m, north_m):
    projection = page._anchor_projection(*center)
    lon, lat = projection.transform(east_m, north_m, direction=TransformDirection.INVERSE)
    return float(lat), float(lon)


def run_sensitivity(graph, center, radius_m, objective="composite", shift_fraction=0.2,
                    scales=(0.8, 1.2), max_evaluations=2048, reference=None, seed=42):
    """Anchor drift under +-20% radius and 20%-of-radius centre shifts (pure, no I/O)."""
    extent = graph_extent_m(graph, center)

    def anchor_for(label, c, r, shift_m):
        result = page.automated_coarse_to_fine_anchor(
            graph, c, r, random_seed=seed, restarts=1, max_evaluations=max_evaluations,
            objective=objective,
            # a shrunken circle (e.g. 0.8 x 4 km) can be smaller than the default 4 km probe
            initial_radius_m=min(page.ANCHOR_CONFIG["initial_radius_m"], r),
        )
        a = result["anchor"]
        reach = shift_m + r  # farthest point of the perturbed circle from the base centre
        return {
            "case": label, "center": list(c), "radius_m": r,
            "anchor": {"lat": a["lat"], "lon": a["lon"], "node_id": a["node_id"]},
            "certification": result["certification"],
            "within_downloaded_footprint": bool(reach <= extent),
        }

    cases = [anchor_for("baseline", center, radius_m, 0.0)]
    for scale in scales:
        cases.append(anchor_for(f"radius x{scale:g}", center, radius_m * scale, 0.0))
    for name, (ux, uy) in DIRECTIONS.items():
        shift = shift_fraction * radius_m
        cases.append(anchor_for(
            f"centre {shift_fraction:.0%} {name}",
            shifted_center(center, ux * shift, uy * shift), radius_m, shift,
        ))

    base = cases[0]["anchor"]
    for case in cases:
        a = case["anchor"]
        case["drift_m"] = page.calculate_distance_meters(base["lat"], base["lon"], a["lat"], a["lon"])
        case["drift_ratio_of_radius"] = case["drift_m"] / radius_m
    drifts = [c["drift_m"] for c in cases[1:]]
    summary = {
        "objective": objective,
        "max_drift_m": max(drifts),
        "median_drift_m": float(np.median(drifts)),
        "share_within_150m": float(np.mean([d <= 150.0 for d in drifts])),
        "footprint_radius_m": extent,
        "uncovered_cases": [c["case"] for c in cases if not c["within_downloaded_footprint"]],
    }
    if reference:
        summary["baseline_error_to_reference_m"] = page.calculate_distance_meters(
            base["lat"], base["lon"], *reference)
    return {"summary": summary, "cases": cases}


def load_graph(path: Path):
    if path.suffix.lower() == ".pkl":
        return page._load_graph_bytes(path.read_bytes())
    import osmnx as ox
    return ox.load_graphml(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--graph", type=Path, required=True)
    parser.add_argument("--lat", type=float, default=20.219443)
    parser.add_argument("--lon", type=float, default=100.403630)
    parser.add_argument("--radius-km", type=float, default=10.0)
    parser.add_argument("--objective", choices=["composite", "closeness", "both"], default="both")
    parser.add_argument("--shift-fraction", type=float, default=0.2)
    parser.add_argument("--max-evaluations", type=int, default=2048)
    parser.add_argument("--reference", type=float, nargs=2, metavar=("LAT", "LON"))
    parser.add_argument("--output", type=Path, default=Path("cache/anchor-sensitivity.json"))
    args = parser.parse_args()

    graph = load_graph(args.graph)
    objectives = ["composite", "closeness"] if args.objective == "both" else [args.objective]
    report = {o: run_sensitivity(
        graph, (args.lat, args.lon), args.radius_km * 1000, objective=o,
        shift_fraction=args.shift_fraction, max_evaluations=args.max_evaluations,
        reference=tuple(args.reference) if args.reference else None,
    ) for o in objectives}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    for objective, data in report.items():
        s = data["summary"]
        print(f"[{objective}] max drift {s['max_drift_m']:.0f} m · median {s['median_drift_m']:.0f} m · "
              f"within 150 m: {s['share_within_150m']:.0%}"
              + (f" · error to reference {s['baseline_error_to_reference_m']:.0f} m"
                 if "baseline_error_to_reference_m" in s else ""))
        for case in data["cases"][1:]:
            flag = "" if case["within_downloaded_footprint"] else "  (outside downloaded footprint)"
            print(f"    {case['case']:<18} drift {case['drift_m']:8.0f} m{flag}")
    print(f"wrote {args.output}")


if __name__ == "__main__":
    sys.exit(main())
