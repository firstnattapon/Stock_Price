"""Regression tests for the principle-review fixes in pages/Rent_Gradient.py.

Covers F1 (betweenness key mismatch), F3/F16 (rank-normalised composite and pivot
screening), F4/F5 (fit uncertainty, Value Gap in index mode), F9/F10 (restricted
unpickling, narrow Overpass lock), F12/F13 (coverage-aware ring density, spacing)
and F2 (anchor sensitivity tooling). Everything is offline.
"""
import importlib.util
import io
import os
import pickle
import sys
import threading
import time
import zipfile
from math import cos, exp, log, pi, radians
from pathlib import Path

import networkx as nx
import numpy as np
import pytest
from pyproj.enums import TransformDirection

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("rent_gradient_principles_test", ROOT / "pages/Rent_Gradient.py")
page = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = page
spec.loader.exec_module(page)

sens_spec = importlib.util.spec_from_file_location("anchor_sensitivity_test", ROOT / "scripts/anchor_sensitivity.py")
sens = importlib.util.module_from_spec(sens_spec)
sys.modules[sens_spec.name] = sens
sens_spec.loader.exec_module(sens)

CENTER = (20.219443, 100.403630)
REAL_BUNDLE = ROOT / "Geoapify_Map" / "osmnx_cache.zip"
REAL_KEY = "d25de118f9e82b8a2e8768e70ec4b5d5"
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
    result = page.import_cache_from_zip(REAL_BUNDLE.read_bytes())
    assert result["imported"] == 2 and not result["errors"]
    graph = page.load_graph_from_cache(REAL_KEY)
    lon = np.mean([d["x"] for _, d in graph.nodes(data=True)])
    lat = np.mean([d["y"] for _, d in graph.nodes(data=True)])
    return graph, (float(lat), float(lon))


# --------------------------------------------------------------------------- F1
def test_edge_scores_by_pair_collapses_multigraph_keys_with_max():
    raw = {(1, 2, 0): 0.5, (1, 2, 1): 0.0, (4, 3, 0): 0.25, (7, 8): 0.1}
    assert page.edge_scores_by_pair(raw) == {(1, 2): 0.5, (3, 4): 0.25, (7, 8): 0.1}


def _star_with_parallel_edge():
    graph = nx.MultiDiGraph()
    for node, (x, y) in {1: (0, 0), 2: (1, 0), 3: (2, 0), 4: (3, 0), 5: (1, 1)}.items():
        graph.add_node(node, x=100 + x * 0.001, y=20 + y * 0.001)
    for u, v in [(1, 2), (2, 3), (3, 4), (2, 5)]:
        graph.add_edge(u, v, length=100.0)
        graph.add_edge(v, u, length=100.0)
    graph.add_edge(1, 2, length=130.0)  # parallel edge, the case that broke the lookup
    return graph


def test_golden_land_low_traffic_term_is_not_constant_on_multigraph():
    graph = _star_with_parallel_edge()
    raw = nx.edge_betweenness_centrality(graph.to_undirected(), weight="length")
    assert all(len(key) == 3 for key in raw)  # the shape that the old lookup missed
    closeness = {n: 1.0 for n in graph}
    ranked = page.compute_golden_land_opportunities(graph, closeness, raw, top_n=5, min_spacing_m=0)
    bonuses = {round(r["low_traffic_bonus"], 6) for r in ranked}
    assert len(bonuses) > 1 and min(bonuses) < 1.0


def test_centrality_edges_get_distinct_betweenness_scores(monkeypatch):
    graph = _star_with_parallel_edge()
    monkeypatch.setattr(page, "_fetch_osm_graph", lambda *a: (graph, True, None))
    result = page._compute_centrality_impl("POLYGON ((0 0, 1 0, 1 1, 0 0))", "drive")
    scores = [f["properties"]["betweenness"] for f in result["edges"]["features"]]
    assert max(scores) == pytest.approx(1.0) and min(scores) < 1.0
    assert len({f["properties"]["color"] for f in result["edges"]["features"]}) > 1


# --------------------------------------------------------------------------- F4
def _samples_along_meridian(distances_km, lam, r0, noise=None):
    out = []
    for i, d in enumerate(distances_km):
        rent = r0 * exp(-lam * d) * (1.0 if noise is None else noise[i])
        out.append({"lat": CENTER[0] + d / 110.574, "lon": CENTER[1], "rent": rent})
    return out


def test_two_samples_fit_is_flagged_not_trusted():
    fit = page.fit_rent_gradient_from_samples(
        _samples_along_meridian([1.0, 3.0], 0.3, 1000.0), *CENTER)
    assert fit["r2"] == pytest.approx(1.0)  # trivially exact: carries no information
    assert fit["dof"] == 0 and fit["lam_se"] is None and fit["lam_ci95"] is None
    assert fit["low_confidence"] is True
    model = {"is_index": False, "r2": fit["r2"], "n_samples": 2, "dof": 0,
             "low_confidence": True, "lam_ci95": None}
    assert "R² ไม่มีความหมาย" in page.fit_quality_label(model)
    assert page.fit_quality_warning(model) is not None


def test_fit_standard_error_and_interval_match_scipy_linregress():
    from scipy import stats

    rng = np.random.default_rng(7)
    distances = [0.4, 0.9, 1.5, 2.1, 2.8, 3.4, 4.1, 4.9]
    noise = np.exp(rng.normal(0.0, 0.08, len(distances)))
    samples = _samples_along_meridian(distances, 0.35, 1200.0, noise)
    fit = page.fit_rent_gradient_from_samples(samples, *CENTER)

    d = [page.haversine_km(*CENTER, s["lat"], s["lon"]) for s in samples]
    ref = stats.linregress(d, [log(s["rent"]) for s in samples])
    assert fit["lam"] == pytest.approx(-ref.slope)
    assert fit["lam_se"] == pytest.approx(ref.stderr)
    assert fit["dof"] == 6 and not fit["low_confidence"]
    t = stats.t.ppf(0.975, 6)
    assert fit["lam_ci95"][0] == pytest.approx(fit["lam"] - t * ref.stderr, rel=1e-3)
    assert fit["lam_ci95"][0] < 0.35 < fit["lam_ci95"][1]
    assert fit["half_dist_ci95"][0] < log(2) / 0.35 < fit["half_dist_ci95"][1]
    assert fit["adj_r2"] < fit["r2"]


def test_t_critical_values_are_conservative_between_table_rows():
    assert page.t_critical_95(1) == pytest.approx(12.706)
    assert page.t_critical_95(10) == pytest.approx(2.228)
    assert page.t_critical_95(35) == pytest.approx(2.042)  # next-lower row, never smaller
    assert page.t_critical_95(500) == pytest.approx(1.96)
    assert page.t_critical_95(0) == float("inf")


def test_interval_covering_zero_warns_even_with_enough_samples():
    model = {"is_index": False, "r2": 0.1, "n_samples": 8, "dof": 6,
             "low_confidence": False, "lam_ci95": [-0.1, 0.2]}
    assert "คร่อมศูนย์" in page.fit_quality_warning(model)
    assert page.fit_interval_text({"lam_ci95": [0.01, 0.2], "half_dist_ci95": None}).endswith(
        "d½ ไม่มีขอบเขต (CI ของ λ รวมศูนย์)")


def test_results_saved_before_the_new_fields_are_interpreted_not_misreported():
    old_big = {"is_index": False, "r2": 0.93, "n_samples": 30, "lam": 0.2}  # no dof / low_confidence
    assert "R² ไม่มีความหมาย" not in page.fit_quality_label(old_big)
    assert "R²=0.930" in page.fit_quality_label(old_big)
    assert page.fit_quality_warning(old_big) is None
    old_small = {"is_index": False, "r2": 1.0, "n_samples": 2, "lam": 0.2}
    assert "R² ไม่มีความหมาย" in page.fit_quality_label(old_small)
    assert page.fit_quality_warning(old_small) is not None


# --------------------------------------------------------------------------- F5
def _nodes_fc(anchor, count=60, spread_km=4.0):
    feats = []
    for i in range(count):
        d = spread_km * (i + 0.5) / count
        feats.append({"type": "Feature",
                      "geometry": {"type": "Point",
                                   "coordinates": [anchor[1] + d / (111.32 * cos(radians(anchor[0]))), anchor[0]]},
                      "properties": {"closeness": max(0.1, 1.0 - d / 6.0)}})
    return {"type": "FeatureCollection", "features": feats}


def _rent_and_network(samples):
    anchor = {"anchor": {"lat": CENTER[0], "lon": CENTER[1], "source": "test"}, "study_radius_m": 5000.0}
    network = {"nodes": _nodes_fc(CENTER), "golden_spots": []}
    rent = page.compute_rent_gradient_data(None, network, None, [], samples, "บาท", automated_anchor=anchor)
    return rent, network


def test_value_gap_is_hidden_in_index_mode_and_shown_when_calibrated():
    index_rent, network = _rent_and_network([])
    assert index_rent["model"]["is_index"]
    rows = page.build_ring_report(index_rent, network, [])
    assert rows and all("Value Gap" not in row for row in rows)

    samples = _samples_along_meridian([0.5, 1.2, 2.0, 2.8, 3.6], 0.3, 900.0)
    fitted_rent, network = _rent_and_network(samples)
    assert not fitted_rent["model"]["is_index"]
    assert fitted_rent["model"]["low_confidence"] is False
    rows = page.build_ring_report(fitted_rent, network, samples)
    assert all("Value Gap" in row for row in rows)


def test_golden_spots_table_omits_value_gap_in_index_mode():
    spots = [{"score": 0.9, "lat": CENTER[0] + 0.01, "lon": CENTER[1], "closeness_norm": 0.8, "degree_norm": 1.0}]
    index_rent, _ = _rent_and_network([])
    assert "Value Gap" not in page._build_golden_spots_df(spots, index_rent).columns
    fitted, _ = _rent_and_network(_samples_along_meridian([0.5, 1.2, 2.0, 2.8, 3.6], 0.3, 900.0))
    assert "Value Gap" in page._build_golden_spots_df(spots, fitted).columns


# --------------------------------------------------------------------------- F9
class _Evil:
    """Pickle payload that would run a shell command if it were ever unpickled."""

    def __init__(self, marker):
        self.marker = str(marker)

    def __reduce__(self):
        return (os.system, (f"touch '{self.marker}'",))


def test_restricted_unpickler_blocks_arbitrary_callables(tmp_path):
    marker = tmp_path / "pwned"
    with pytest.raises(pickle.UnpicklingError, match="Blocked global"):
        page.safe_pickle_loads(pickle.dumps(_Evil(marker)))
    assert not marker.exists()


def test_cache_roundtrip_keeps_geometry_and_numpy_values(tmp_path, monkeypatch):
    from shapely.geometry import LineString

    monkeypatch.setattr(page, "CACHE_DIR", tmp_path)
    graph = nx.MultiDiGraph(crs="EPSG:4326")
    graph.add_node(1, x=np.float64(100.0), y=np.float64(20.0))
    graph.add_node(2, x=100.001, y=20.001)
    graph.add_edge(1, 2, length=np.float64(150.0), geometry=LineString([(100, 20), (100.001, 20.001)]))
    page.save_graph_to_cache("a" * 32, graph)
    loaded = page.load_graph_from_cache("a" * 32)
    assert loaded[1][2][0]["geometry"].length == pytest.approx(graph[1][2][0]["geometry"].length)
    assert not list(tmp_path.glob("*.tmp"))  # atomic write leaves no partial file behind


def test_unsafe_or_non_graph_cache_file_is_ignored(tmp_path, monkeypatch):
    cache = tmp_path / "cache"
    cache.mkdir()
    marker = tmp_path / "pwned"
    monkeypatch.setattr(page, "CACHE_DIR", cache)
    (cache / f"osm_graph_{'b' * 32}.pkl").write_bytes(pickle.dumps(_Evil(marker)))
    (cache / f"osm_graph_{'c' * 32}.pkl").write_bytes(pickle.dumps({"not": "a graph"}))
    assert page.load_graph_from_cache("b" * 32) is None
    assert page.load_graph_from_cache("c" * 32) is None
    assert not marker.exists()


def test_bundle_import_rejects_code_traversal_and_oversize(tmp_path, monkeypatch):
    cache = tmp_path / "cache"
    cache.mkdir()
    marker = tmp_path / "pwned"
    monkeypatch.setattr(page, "CACHE_DIR", cache)
    good = nx.MultiDiGraph(crs="EPSG:4326")
    good.add_node(1, x=100.0, y=20.0)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(f"osm_graph_{'d' * 32}.pkl", pickle.dumps(_Evil(marker)))
        archive.writestr("osm_graph_/../../escape.pkl", b"x")
        archive.writestr("osm_graph_short.pkl", b"x")
        archive.writestr(f"osm_graph_{'e' * 32}.pkl", pickle.dumps(good))
        archive.writestr(f"osm_graph_{'f' * 32}.pkl", pickle.dumps(good) + b"0" * 64)
    monkeypatch.setattr(page, "MAX_CACHE_ENTRY_BYTES", len(pickle.dumps(good)) + 8)
    result = page.import_cache_from_zip(buffer.getvalue())

    assert result["imported"] == 1
    assert sorted(p.name for p in cache.iterdir()) == [f"osm_graph_{'e' * 32}.pkl"]
    errors = " | ".join(result["errors"])
    assert "Blocked global" in errors and "Skipped invalid file" in errors and "oversized" in errors
    assert not marker.exists()
    assert not (tmp_path / "escape.pkl").exists()


@needs_real_graph
def test_repo_osmnx_bundle_still_imports_under_the_allow_list(real_graph):
    graph, _ = real_graph
    assert len(graph.nodes) > 1000
    assert sum(1 for *_, d in graph.edges(data=True) if "geometry" in d) > 0


# -------------------------------------------------------------------------- F10
def test_cache_hit_does_not_wait_for_a_download_but_a_miss_does(tmp_path, monkeypatch):
    monkeypatch.setattr(page, "CACHE_DIR", tmp_path)
    polygon = "POLYGON ((100 20, 100.01 20, 100.01 20.01, 100 20.01, 100 20))"
    graph = nx.MultiDiGraph(crs="EPSG:4326")
    graph.add_node(1, x=100.0, y=20.0)
    graph.add_node(2, x=100.001, y=20.001)
    graph.add_edge(1, 2, length=100.0)
    page.save_graph_to_cache(page.get_cache_key(polygon, "drive"), graph)

    held, release = threading.Event(), threading.Event()

    def hold_lock():
        with page._OVERPASS_LOCK:
            held.set()
            release.wait(10)

    holder = threading.Thread(target=hold_lock)
    holder.start()
    assert held.wait(5)
    try:
        out = {}
        hit = threading.Thread(target=lambda: out.update(hit=page._fetch_osm_graph(polygon, "drive")))
        hit.start()
        hit.join(3)
        assert not hit.is_alive(), "a cache hit queued behind the lock"
        assert out["hit"][1] is True and out["hit"][2] is None

        monkeypatch.setattr(page.ox, "graph_from_polygon", lambda *a, **k: graph)
        miss = threading.Thread(target=lambda: out.update(miss=page._fetch_osm_graph(polygon, "walk")))
        miss.start()
        time.sleep(0.3)
        assert miss.is_alive(), "a download must stay serialised behind the lock"
    finally:
        release.set()
        holder.join(5)
    miss.join(5)
    assert out["miss"][2] is None and out["miss"][1] is False


# -------------------------------------------------------------------------- F12
def _disc_geojson(anchor, radius_km):
    return {"type": "Polygon", "coordinates": [page._geodesic_circle_coords(*anchor, radius_km, 180)]}


def test_ring_coverage_areas_follow_the_downloaded_polygon():
    step, n = 1.0, 6
    disc = page.ring_coverage_areas_km2(_disc_geojson(CENTER, 3.0), *CENTER, step, n)
    for i in range(3):
        assert disc[i] == pytest.approx(pi * ((i + 1) ** 2 - i ** 2), rel=0.02)
    # the fixture's flat-earth ellipse differs from the metric circle by a few metres,
    # so ring 4 may catch a sliver (<1% of its 22 km² area); rings 5-6 must be empty
    assert disc[3] < 0.2 and all(a < 0.01 for a in disc[4:])
    assert page.ring_coverage_areas_km2(None, *CENTER, step, n) is None
    assert page.ring_coverage_areas_km2({"type": "Polygon", "coordinates": []}, *CENTER, step, n) is None


def test_ring_density_uses_covered_area_not_the_full_annulus():
    rent, network = _rent_and_network([])
    step = rent["model"]["d_max_km"] / len(rent["rings_geojson"]["features"])
    network["coverage_geojson"] = _disc_geojson(CENTER, 2.5 * step)  # only half-covers ring 3
    rows = page.build_ring_report(rent, network, [])
    ring3 = rows[2]
    full = pi * ((3 * step) ** 2 - (2 * step) ** 2)
    assert ring3["พื้นที่ (km²)"] == pytest.approx(full, abs=0.01)
    assert ring3["พื้นที่ครอบคลุม (km²)"] < ring3["พื้นที่ (km²)"]
    if ring3["โหนด Network"]:
        assert ring3["โหนด/km²"] == pytest.approx(
            ring3["โหนด Network"] / ring3["พื้นที่ครอบคลุม (km²)"], rel=0.03)

    legacy = {k: v for k, v in network.items() if k != "coverage_geojson"}
    legacy_rows = page.build_ring_report(rent, legacy, [])
    assert "พื้นที่ครอบคลุม (km²)" not in legacy_rows[0]


# -------------------------------------------------------------------------- F13
def test_golden_spots_are_spatially_deduplicated():
    graph = nx.MultiDiGraph()
    closeness = {}
    for i in range(5):  # a tight cluster: ~11 m apart, all top scores
        graph.add_node(i, x=100.0 + i * 0.0001, y=20.0)
        closeness[i] = 1.0 - i * 0.001
    for j, offset in enumerate((0.01, 0.02, 0.03)):  # well separated, lower scores
        graph.add_node(10 + j, x=100.0 + offset, y=20.0)
        closeness[10 + j] = 0.5 - j * 0.01
    spread = page.compute_golden_land_opportunities(graph, closeness, {}, top_n=3)
    assert sorted(s["node_id"] for s in spread) == [0, 10, 11]
    clumped = page.compute_golden_land_opportunities(graph, closeness, {}, top_n=3, min_spacing_m=0)
    assert [s["node_id"] for s in clumped] == [0, 1, 2]


# --------------------------------------------------------------------- closeness
def test_weighted_closeness_exact_matches_networkx_and_pivot_ranks_agree(monkeypatch):
    from scipy import stats

    undirected = nx.Graph(road_grid(size=13)).to_undirected()
    exact, method = page.compute_weighted_closeness(nx.MultiGraph(undirected))
    assert method == "exact-scipy"
    reference = nx.closeness_centrality(undirected, distance="length")
    assert all(exact[n] == pytest.approx(reference[n]) for n in undirected)

    monkeypatch.setitem(page.NETWORK_CONFIG, "closeness_exact_threshold", 10)
    monkeypatch.setitem(page.NETWORK_CONFIG, "closeness_k_pivots", 100)
    approx, method = page.compute_weighted_closeness(nx.MultiGraph(undirected))
    assert method == "pivot-approx"
    nodes = list(undirected)
    assert stats.spearmanr([exact[n] for n in nodes], [approx[n] for n in nodes]).statistic > 0.9


# ------------------------------------------------------------------------ F3/F16
def test_composite_normalisers_are_fixed_and_weights_are_reported():
    runs = [page.find_cbd_anchors(road_grid(), CENTER, 4000.0) for _ in range(3)]
    assert len({str(r["composite"]["normalisation"]) for r in runs}) == 1
    assert len({r["composite"]["anchor"]["node_id"] for r in runs}) == 1
    result = runs[0]["composite"]
    assert result["scoring"] == "rank-v2" and result["nominal_weights"]["closeness"] == 0.5
    assert sum(result["effective_weights"].values()) == pytest.approx(1.0)
    assert sum(result["winner_contribution"].values()) == pytest.approx(1.0)
    anchor = result["anchor"]
    assert 0.0 < anchor["degree_norm"] < 1.0 and 0.0 < anchor["density_norm"] < 1.0
    assert 0.0 <= anchor["closeness_norm"] <= 1.0


def test_closeness_objective_scoring_is_unchanged():
    result = page.find_cbd_anchors(road_grid(), CENTER, 4000.0)["closeness"]
    anchor = result["anchor"]
    assert anchor["score"] == pytest.approx(anchor["closeness_norm"])
    assert anchor["closeness_norm"] == pytest.approx(
        anchor["closeness"] / (anchor["closeness"] + 1 / 4000.0))
    assert result["scoring"] == "closeness-bounded"
    assert result["effective_weights"] == {"closeness": 1.0, "degree": 0.0, "density": 0.0}


# Certified winners of the previous (ARPS + exhaustive audit) implementation on the real
# road graphs in the repo; the seed-free search must reproduce them exactly.
REAL_EXPECTED = [
    (12000.0, "composite", "2227109156", 0.925662),
    (12000.0, "closeness", "2431645447", 0.634651),
    (8000.0, "composite", "2227109156", 0.919497),
    (8000.0, "closeness", "2421755420", 0.574818),
]


@needs_real_graph
@pytest.mark.parametrize("radius,objective,node,score", REAL_EXPECTED)
def test_real_roads_reproduce_the_previous_certified_winners(real_graph, radius, objective, node, score):
    graph, center = real_graph
    result = page.find_cbd_anchors(graph, center, radius, stability=False)[objective]
    assert result["globally_certified"]
    assert result["anchor"]["node_id"] == node
    assert result["anchor"]["score"] == pytest.approx(score, abs=1e-6)


@needs_real_graph
def test_real_roads_composite_closeness_weight_is_no_longer_swamped(real_graph):
    graph, center = real_graph
    result = page.find_cbd_anchors(graph, center, 12000.0, stability=False)["composite"]
    effective = result["effective_weights"]
    # Measured on this graph before the fix: closeness ~27% vs nominal 50%, density ~50% vs 20%.
    assert effective["closeness"] > 0.40
    assert effective["density"] < 0.35
    assert result["globally_certified"]


@needs_real_graph
@pytest.mark.parametrize("budget", [60, 150, 300])
def test_over_budget_search_matches_the_exhaustive_anchor_for_both_objectives(real_graph, budget):
    graph, center = real_graph
    exhaustive = page.find_cbd_anchors(graph, center, 12000.0, stability=False)
    screened = page.find_cbd_anchors(graph, center, 12000.0, max_rows=budget, stability=False)
    for objective in ("composite", "closeness"):
        assert exhaustive[objective]["globally_certified"]
        assert screened[objective]["certification"] == "pivot-screened-exact-top-k"
        assert screened[objective]["screening"]["extra_rows"] <= budget
        assert screened[objective]["anchor"]["node_id"] == exhaustive[objective]["anchor"]["node_id"]


def test_over_budget_screen_on_synthetic_grid_finds_the_centre_for_every_budget():
    anchors = {
        page.find_cbd_anchors(road_grid(size=21), CENTER, 4000.0, max_rows=budget)[o]["anchor"]["node_id"]
        for budget in (40, 80, 120) for o in ("composite", "closeness")
    }
    assert anchors == {str(10 * 21 + 10)}


# ---------------------------------------------------------------------------- F2
def test_sensitivity_report_is_complete_and_flags_uncovered_circles():
    report = sens.run_sensitivity(road_grid(), CENTER, 2000.0, objective="composite")
    cases = {c["case"]: c for c in report["cases"]}
    assert set(cases) == {"baseline", "radius x0.8", "radius x1.2", "centre 20% N",
                          "centre 20% E", "centre 20% S", "centre 20% W"}
    assert cases["baseline"]["drift_m"] == 0.0
    # The 11 x 11 test grid reaches only ~0.7 km from the centre, so shifted 2 km circles exceed it.
    assert report["summary"]["uncovered_cases"]
    assert report["summary"]["max_drift_m"] >= report["summary"]["median_drift_m"]
    assert 0.0 <= report["summary"]["share_within_150m"] <= 1.0


@needs_real_graph
def test_sensitivity_on_real_roads_reports_reference_error(real_graph):
    graph, center = real_graph
    report = sens.run_sensitivity(graph, center, 8000.0, objective="composite", reference=center)
    assert report["summary"]["baseline_error_to_reference_m"] >= 0.0
    assert report["summary"]["uncovered_cases"] == []


# ------------------------------------------------------------------- Streamlit UI
def _run_rent_app(monkeypatch, samples):
    from streamlit.testing.v1 import AppTest

    def app():
        import rent_gradient_principles_test
        rent_gradient_principles_test.main()

    monkeypatch.setattr(page.StateManager, "_load_remote_defaults", staticmethod(lambda defaults: []))
    monkeypatch.setattr(page, "_fetch_osm_graph", lambda *args: (road_grid(), True, None))
    at = AppTest.from_function(app).run(timeout=30)
    next(b for b in at.button if b.label == "🎯 ค้นหา CBD Anchor อัตโนมัติ").click().run(timeout=30)
    assert not at.exception
    at.session_state["rent_samples"] = samples
    next(b for b in at.button if b.label == "🧮 คำนวณ Rent Gradient").click().run(timeout=30)
    assert not at.exception
    return at


def test_ui_warns_when_only_two_samples_are_used(monkeypatch):
    at = _run_rent_app(monkeypatch, _samples_along_meridian([1.0, 3.0], 0.3, 1000.0))
    model = at.session_state["rent_gradient_data"]["model"]
    assert model["low_confidence"] and model["lam_ci95"] is None
    warnings = " ".join(w.value for w in at.warning)
    assert "น้อยกว่า 5 จุด" in warnings
    assert not any("R² (fit)" == m.label and m.value not in ("—",) for m in at.metric)


def test_ui_shows_interval_and_no_warning_with_enough_samples(monkeypatch):
    rng = np.random.default_rng(3)
    samples = _samples_along_meridian(
        [0.5, 1.2, 2.0, 2.8, 3.6, 4.4], 0.3, 900.0, np.exp(rng.normal(0, 0.05, 6)))
    at = _run_rent_app(monkeypatch, samples)
    model = at.session_state["rent_gradient_data"]["model"]
    assert not model["low_confidence"] and model["lam_ci95"][0] < 0.3 < model["lam_ci95"][1]
    assert not any("น้อยกว่า 5 จุด" in w.value for w in at.warning)
    assert any("95% CI" in c.value for c in at.caption)
