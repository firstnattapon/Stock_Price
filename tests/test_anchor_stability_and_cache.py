"""Stability probe, shared distance rows and covering-cache reuse (all offline)."""
import importlib.util
import sys
from pathlib import Path

import networkx as nx
import numpy as np
import pytest
import shapely.wkt
from pyproj.enums import TransformDirection
from shapely.geometry import Point, Polygon

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("anchor_stability_cache_test", ROOT / "pages/Rent_Gradient.py")
page = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = page
spec.loader.exec_module(page)

sens_spec = importlib.util.spec_from_file_location("anchor_sensitivity_probe_test", ROOT / "scripts/anchor_sensitivity.py")
sens = importlib.util.module_from_spec(sens_spec)
sys.modules[sens_spec.name] = sens
sens_spec.loader.exec_module(sens)

CENTER = (20.219443, 100.403630)
REAL_BUNDLE = ROOT / "Geoapify_Map" / "osmnx_cache.zip"
needs_real_graph = pytest.mark.skipif(not REAL_BUNDLE.exists(), reason="repo road-graph bundle missing")


def road_grid(size=11, spacing=100):
    graph = nx.MultiDiGraph(crs="EPSG:4326")
    projection = page._anchor_projection(*CENTER)
    for x in range(size):
        for y in range(size):
            lon, lat = projection.transform(
                (x - size // 2) * spacing, (y - size // 2) * spacing,
                direction=TransformDirection.INVERSE,
            )
            graph.add_node(x * size + y, x=lon, y=lat)
            for dx, dy in ((-1, 0), (0, -1)):
                if x + dx >= 0 and y + dy >= 0:
                    other = (x + dx) * size + y + dy
                    graph.add_edge(x * size + y, other, length=float(spacing))
                    graph.add_edge(other, x * size + y, length=float(spacing))
    return graph


@pytest.fixture
def real_graph(tmp_path, monkeypatch):
    monkeypatch.setattr(page, "CACHE_DIR", tmp_path)
    page.import_cache_from_zip(REAL_BUNDLE.read_bytes())
    graph = page.load_graph_from_cache("d25de118f9e82b8a2e8768e70ec4b5d5")
    lon = np.mean([d["x"] for _, d in graph.nodes(data=True)])
    lat = np.mean([d["y"] for _, d in graph.nodes(data=True)])
    return graph, (float(lat), float(lon))


def level_for(drift_m, radius_m):
    ratio = drift_m / radius_m
    return ("stable" if ratio <= page.ANCHOR_CONFIG["stability_ok_ratio"]
            else "check" if ratio <= page.ANCHOR_CONFIG["stability_warn_ratio"] else "unstable")


# ----------------------------------------------------------------------- probe
def test_probe_covers_the_six_perturbed_circles_and_a_symmetric_grid_is_stable():
    result = page.find_cbd_anchors(road_grid(21), CENTER, 4000.0)
    for objective in ("composite", "closeness"):
        stability = result[objective]["stability"]
        assert [c["case"] for c in stability["cases"]] == [
            "radius x0.8", "radius x1.2",
            "centre 20% N", "centre 20% E", "centre 20% S", "centre 20% W"]
        assert stability["indicative"] is True
        assert stability["level"] == level_for(stability["max_drift_m"], 4000.0)
        assert stability["max_drift_m"] >= stability["median_drift_m"] >= 0
        assert not any("ขยับได้ถึง" in w for w in result[objective]["warnings"]) or \
            stability["level"] != "stable"


def test_probe_can_be_switched_off_and_leaves_the_anchors_untouched():
    with_probe = page.find_cbd_anchors(road_grid(21), CENTER, 4000.0)
    without = page.find_cbd_anchors(road_grid(21), CENTER, 4000.0, stability=False)
    for objective in ("composite", "closeness"):
        assert without[objective]["stability"] is None
        assert with_probe[objective]["anchor"] == without[objective]["anchor"]


def test_probe_thresholds_define_the_level(monkeypatch):
    monkeypatch.setitem(page.ANCHOR_CONFIG, "stability_ok_ratio", -1.0)
    monkeypatch.setitem(page.ANCHOR_CONFIG, "stability_warn_ratio", -0.5)
    result = page.find_cbd_anchors(road_grid(21), CENTER, 4000.0)["composite"]
    assert result["stability"]["level"] == "unstable"
    assert any("ขยับได้ถึง" in w and "ประมาณการ" in w for w in result["warnings"])


def test_each_exact_row_is_computed_once_and_shared_by_both_anchors_and_the_probe(monkeypatch):
    rows = []
    real = page.csgraph_dijkstra
    monkeypatch.setattr(page, "csgraph_dijkstra",
                        lambda matrix, directed, indices: rows.append(len(indices))
                        or real(matrix, directed=directed, indices=indices))
    page.find_cbd_anchors(road_grid(11), CENTER, 4000.0)
    assert sum(rows) == 121  # every inside node exactly once; probe + 2 objectives add none
    rows.clear()
    page.find_cbd_anchors(road_grid(21), CENTER, 4000.0)
    assert sum(rows) == 441
    rows.clear()
    page.find_cbd_anchors(road_grid(21), CENTER, 4000.0, stability=False)
    assert sum(rows) == 441  # the probe costs no extra Dijkstra when the pass is exhaustive


@needs_real_graph
@pytest.mark.parametrize("radius", [8000.0, 5000.0])
def test_probe_level_agrees_with_the_exact_perturbation_oracle(real_graph, radius):
    graph, center = real_graph
    found = page.find_cbd_anchors(graph, center, radius)
    shared = {}
    for objective in ("composite", "closeness"):
        exact = sens.run_sensitivity(graph, center, radius, objective=objective, cache=shared)
        probe = found[objective]["stability"]
        assert probe["level"] == level_for(exact["summary"]["max_drift_m"], radius), (objective, radius)
        # the indicative probe must also be the right order of magnitude
        assert probe["max_drift_m"] == pytest.approx(exact["summary"]["max_drift_m"], rel=0.5, abs=250.0)


@needs_real_graph
def test_pure_closeness_anchor_moves_more_than_the_composite_when_the_circle_moves(real_graph):
    graph, center = real_graph
    found = page.find_cbd_anchors(graph, center, 8000.0)
    assert found["composite"]["stability"]["level"] == "stable"
    assert found["closeness"]["stability"]["level"] == "unstable"
    assert found["closeness"]["stability"]["max_drift_m"] > found["composite"]["stability"]["max_drift_m"]


# --------------------------------------------------------------- covering cache
def circle(lat, lon, radius_km):
    return Polygon(page._geodesic_circle_coords(lat, lon, radius_km, 96)).wkt


@pytest.fixture
def cache_env(tmp_path, monkeypatch):
    monkeypatch.setattr(page, "CACHE_DIR", tmp_path)
    monkeypatch.delenv("OVERPASS_ENDPOINTS", raising=False)
    downloads = []
    source = road_grid(21)

    def fake_download(polygon, network_type="drive", truncate_by_edge=True):
        downloads.append(network_type)
        graph = source.copy()
        return graph

    monkeypatch.setattr(page.ox, "graph_from_polygon", fake_download)
    return tmp_path, downloads


def test_contained_polygon_is_served_from_the_cache_without_downloading(cache_env):
    tmp_path, downloads = cache_env
    big, small = circle(*CENTER, 1.5), circle(*CENTER, 0.45)
    full, cached, error = page._fetch_osm_graph(big, "drive")
    assert (cached, error, full.graph["osm_source"]) == (False, None, "download")
    sidecar = next(tmp_path.glob("osm_graph_*.json"))
    meta = __import__("json").loads(sidecar.read_text(encoding="utf-8"))
    assert meta["version"] == 1 and meta["network_type"] == "drive" and meta["nodes"] == 441

    cropped, cached, error = page._fetch_osm_graph(small, "drive")
    assert (cached, error, len(downloads)) == (True, None, 1)
    assert cropped.graph["osm_source"] == "cache-crop" and cropped.graph["reused_from"]
    assert 2 <= len(cropped) < len(full)
    polygon = shapely.wkt.loads(small)
    outside = [n for n, d in cropped.nodes(data=True) if not polygon.contains(Point(d["x"], d["y"]))]
    for node in outside:  # same rule as graph_from_polygon(truncate_by_edge=True)
        neighbours = set(cropped.successors(node)) | set(cropped.predecessors(node))
        assert any(polygon.contains(Point(cropped.nodes[m]["x"], cropped.nodes[m]["y"])) for m in neighbours)

    again, cached, _ = page._fetch_osm_graph(small, "drive")  # the crop is now an exact entry
    assert again.graph["osm_source"] == "cache" and len(downloads) == 1
    assert page.cached_graph_available(small, "drive")


def test_partial_overlap_other_network_or_disabled_reuse_all_download(cache_env, monkeypatch):
    tmp_path, downloads = cache_env
    page._fetch_osm_graph(circle(*CENTER, 1.5), "drive")
    assert len(downloads) == 1
    shifted = circle(CENTER[0] + 0.012, CENTER[1], 0.8)  # sticks out of the cached footprint
    assert not page.cached_graph_available(shifted, "drive")
    _, cached, _ = page._fetch_osm_graph(shifted, "drive")
    assert not cached and len(downloads) == 2
    _, cached, _ = page._fetch_osm_graph(circle(*CENTER, 0.45), "walk")  # different network type
    assert not cached and downloads[-1] == "walk"
    monkeypatch.setitem(page.ANCHOR_CONFIG, "reuse_covering_cache", False)
    _, cached, _ = page._fetch_osm_graph(circle(*CENTER, 0.3), "drive")
    assert not cached and len(downloads) == 4


def test_corrupt_missing_or_legacy_sidecars_never_break_a_request(cache_env):
    tmp_path, downloads = cache_env
    page._fetch_osm_graph(circle(*CENTER, 1.5), "drive")
    for sidecar in tmp_path.glob("osm_graph_*.json"):
        sidecar.write_text("{not json", encoding="utf-8")
    graph, cached, error = page._fetch_osm_graph(circle(*CENTER, 0.45), "drive")
    assert error is None and graph is not None and not cached and len(downloads) == 2
    for sidecar in tmp_path.glob("osm_graph_*.json"):  # legacy pickle without any sidecar
        sidecar.unlink()
    assert page.find_covering_cache_key(circle(*CENTER, 0.2), "drive") is None


def test_the_smallest_covering_entry_is_chosen(cache_env):
    tmp_path, downloads = cache_env
    page._fetch_osm_graph(circle(*CENTER, 2.5), "drive")
    page._fetch_osm_graph(circle(*CENTER, 1.2), "drive")
    wanted = page.get_cache_key(circle(*CENTER, 1.2), "drive")
    assert page.find_covering_cache_key(circle(*CENTER, 0.4), "drive") == wanted


def test_anchor_pipeline_reports_the_cache_source(cache_env):
    tmp_path, downloads = cache_env
    larger = page.anchor_study_polygon(*CENTER, 2000.0)   # 2.4 km buffered footprint
    first, cached_first, _ = page._fetch_osm_graph(larger.wkt, "drive")
    smaller = page.anchor_study_polygon(*CENTER, 1000.0)  # 1.2 km footprint: contained
    second, cached_second, _ = page._fetch_osm_graph(smaller.wkt, "drive")
    assert (cached_first, cached_second) == (False, True) and len(downloads) == 1
    assert second.graph["osm_source"] == "cache-crop"
    result = page.find_cbd_anchors(second, CENTER, 1000.0)
    assert result["composite"]["anchor"]["node_id"]
