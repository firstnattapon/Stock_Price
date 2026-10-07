"""Reproducible, seed-free audit of the road-only CBD anchors; OSM download time is separate.

python scripts/benchmark_cbd_anchor.py --repeat 3 --output cache/cbd-audit.json
Optional ground truth is LAT LON; never infer truth from the algorithm's output.

One call finds both anchors (Composite and Closeness 100%) from one road graph.
The audit records the compute split (prepare / pivot rows / exact rows), whether
repeated runs return the identical anchors, each objective's certification and
the built-in (indicative) stability probe. Use scripts/anchor_sensitivity.py for
the exact perturbation check.
"""
import argparse
import importlib.util
import json
from pathlib import Path
import platform
import time

import osmnx as ox

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("rent_gradient", ROOT / "pages/Rent_Gradient.py")
page = importlib.util.module_from_spec(spec)
spec.loader.exec_module(page)

OBJECTIVES = ("composite", "closeness")


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--lat", type=float, default=20.219443)
    parser.add_argument("--lon", type=float, default=100.403630)
    parser.add_argument("--radius-km", type=float, default=10.0)
    parser.add_argument("--repeat", type=int, default=3,
                        help="Run the search this many times and require identical anchors")
    parser.add_argument("--max-rows", type=int, help="Override the exact-row budget (default: from graph size)")
    parser.add_argument("--network-type", choices=["drive", "walk", "bike"], default="drive")
    parser.add_argument("--graphml", type=Path, help="Reuse a local buffered OSM graph instead of downloading")
    parser.add_argument("--save-graphml", type=Path)
    parser.add_argument("--ground-truth", type=float, nargs=2, metavar=("LAT", "LON"))
    parser.add_argument("--samples", type=Path, help='JSON list of {"lat", "lon", "rent"} observations')
    parser.add_argument("--output", type=Path, default=Path("cache/cbd-audit.json"))
    args = parser.parse_args()
    started = time.perf_counter()
    if args.graphml:
        graph = ox.load_graphml(args.graphml)
        provenance = str(args.graphml)
        graph_cached = True
    else:
        footprint = page.anchor_study_polygon(args.lat, args.lon, args.radius_km * 1000)
        graph, graph_cached, error = page._fetch_osm_graph(
            footprint.wkt, args.network_type
        )
        if error or graph is None:
            raise RuntimeError(error or "OSM graph download returned no data")
        provenance = graph.graph.get(
            "overpass_endpoint", "disk-cache" if graph_cached else "unknown"
        )
    load_seconds = time.perf_counter() - started
    if args.save_graphml:
        args.save_graphml.parent.mkdir(parents=True, exist_ok=True)
        ox.save_graphml(graph, args.save_graphml)

    center = (args.lat, args.lon)
    runs = [page.find_cbd_anchors(graph, center, args.radius_km * 1000, max_rows=args.max_rows)
            for _ in range(max(1, args.repeat))]
    result = runs[0]
    identical = all(
        run[o]["anchor"]["node_id"] == result[o]["anchor"]["node_id"]
        and run[o]["anchor"]["score"] == result[o]["anchor"]["score"]
        for run in runs for o in OBJECTIVES
    )
    compute = [run["timings"]["compute_s"] for run in runs]
    result["audit"] = {
        "provenance": provenance, "graph_cached": graph_cached,
        "network_type": args.network_type,
        "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "python": platform.python_version(), "platform": platform.platform(),
        "osmnx": ox.__version__, "load_seconds": load_seconds,
        "total_seconds": load_seconds + compute[0],
        "repeat_runs": len(runs), "repeat_identical": identical,
        "compute_seconds_per_run": compute,
        "compute_within_10s": max(compute) <= 10,
        "total_within_10s": load_seconds + max(compute) <= 10,
        "certification": {o: result[o]["certification"] for o in OBJECTIVES},
        "stability": {o: (result[o]["stability"] or {}).get("level") for o in OBJECTIVES},
        "ground_truth_error_m": None,
        "ground_truth_within_150m": None,
        "rent_fit_comparison": None,
    }
    if args.ground_truth:
        errors = {o: page.calculate_distance_meters(
            *args.ground_truth, result[o]["anchor"]["lat"], result[o]["anchor"]["lon"])
            for o in OBJECTIVES}
        result["audit"].update(
            ground_truth_error_m=errors,
            ground_truth_within_150m={o: e <= 150 for o, e in errors.items()})
    if args.samples:
        samples = json.loads(args.samples.read_text(encoding="utf-8"))
        anchor = result["composite"]["anchor"]
        baseline = page.fit_rent_gradient_from_samples(samples, *center)
        fitted = page.fit_rent_gradient_from_samples(samples, anchor["lat"], anchor["lon"])
        if baseline and fitted:
            result["audit"]["rent_fit_comparison"] = {
                "center_r2": baseline["r2"], "anchor_r2": fitted["r2"],
                "delta_r2": fitted["r2"] - baseline["r2"],
                "note": "Log-rent in-sample fit comparison, not a significance test",
            }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False),
                           encoding="utf-8")
    print(json.dumps({
        "anchors": {o: result[o]["anchor"] for o in OBJECTIVES},
        "timings": result["timings"], "audit": result["audit"],
        "warnings": {o: result[o]["warnings"] for o in OBJECTIVES},
        "output": str(args.output),
    }, indent=2, ensure_ascii=True))


if __name__ == "__main__":
    main()
