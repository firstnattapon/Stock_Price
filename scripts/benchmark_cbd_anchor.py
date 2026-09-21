"""Reproducible road-only ARPS audit; OSM download time is reported separately.

python scripts/benchmark_cbd_anchor.py --restarts 50 --output cache/cbd-audit.json
Optional ground truth is LAT LON; never infer truth from the algorithm's output.
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lat", type=float, default=20.219443)
    parser.add_argument("--lon", type=float, default=100.403630)
    parser.add_argument("--radius-km", type=float, default=10.0)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--restarts", type=int, default=50)
    parser.add_argument("--independent-seeds", type=int, default=0,
                        help="Additionally rerun the full search with seeds 0..N-1 (e.g. 50)")
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
    result = page.automated_coarse_to_fine_anchor(
        graph, (args.lat, args.lon), args.radius_km * 1000,
        random_seed=args.seed, restarts=args.restarts,
    )
    anchors = [r["anchor"] for r in result["restarts"]]
    pairwise = max(page.calculate_distance_meters(a["lat"], a["lon"], b["lat"], b["lon"])
                   for a in anchors for b in anchors)
    result["audit"] = {
        "provenance": provenance, "graph_cached": graph_cached,
        "network_type": args.network_type,
        "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "python": platform.python_version(), "platform": platform.platform(),
        "osmnx": ox.__version__, "load_seconds": load_seconds,
        "total_seconds": load_seconds + result["compute_seconds"],
        "unique_seed_nodes": len({r["seed"]["node_id"] for r in result["restarts"]}),
        "local_max_pairwise_anchor_distance_m": pairwise,
        "local_spread_within_50m": pairwise <= 50,
        "compute_within_10s": result["compute_seconds"] <= 10,
        "total_within_10s": load_seconds + result["compute_seconds"] <= 10,
        "ground_truth_error_m": None,
        "ground_truth_within_150m": None,
        "rent_fit_comparison": None,
    }
    if args.independent_seeds:
        independent = [page.automated_coarse_to_fine_anchor(
            graph, (args.lat, args.lon), args.radius_km * 1000,
            random_seed=seed, restarts=1,
        ) for seed in range(args.independent_seeds)]
        spread = max(page.calculate_distance_meters(
            a["anchor"]["lat"], a["anchor"]["lon"], b["anchor"]["lat"], b["anchor"]["lon"])
            for a in independent for b in independent)
        result["audit"]["independent_seed_audit"] = {
            "runs": len(independent), "max_pairwise_anchor_distance_m": spread,
            "spread_within_50m": spread <= 50,
            "max_compute_seconds": max(r["compute_seconds"] for r in independent),
            "all_globally_certified": all(r["globally_certified"] for r in independent),
            "anchors": [r["anchor"]["node_id"] for r in independent],
        }
    anchor = result["anchor"]
    if args.ground_truth:
        error = page.calculate_distance_meters(*args.ground_truth, anchor["lat"], anchor["lon"])
        result["audit"].update(ground_truth_error_m=error, ground_truth_within_150m=error <= 150)
    if args.samples:
        samples = json.loads(args.samples.read_text(encoding="utf-8"))
        first = result["restarts"][0]["seed"]
        baseline = page.fit_rent_gradient_from_samples(samples, first["lat"], first["lon"])
        fitted = page.fit_rent_gradient_from_samples(samples, anchor["lat"], anchor["lon"])
        if baseline and fitted:
            result["audit"]["rent_fit_comparison"] = {
                "seed_r2": baseline["r2"], "anchor_r2": fitted["r2"],
                "delta_r2": fitted["r2"] - baseline["r2"],
                "note": "Log-rent in-sample fit comparison, not a significance test",
            }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False),
                           encoding="utf-8")
    print(json.dumps({"anchor": anchor, "audit": result["audit"],
                      "warnings": result["warnings"], "output": str(args.output)},
                     indent=2, ensure_ascii=True))


if __name__ == "__main__":
    main()
