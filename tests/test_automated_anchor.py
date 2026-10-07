"""Offline correctness and Streamlit integration tests for the road-only CBD anchors."""
import importlib.util
import json
from pathlib import Path
import sys

import networkx as nx
import numpy as np
import pytest
from pyproj.enums import TransformDirection
from scipy.stats import rankdata

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("rent_gradient_test", ROOT / "pages/Rent_Gradient.py")
page = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = page
spec.loader.exec_module(page)
CENTER = (20.219443, 100.403630)


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


def find(graph=None, **kwargs):
    """Both anchors from one call."""
    options = dict(study_center=CENTER, study_radius_m=4000)
    options.update(kwargs)
    return page.find_cbd_anchors(road_grid() if graph is None else graph, **options)


def search(graph=None, objective="composite", **kwargs):
    return find(graph, **kwargs)[objective]


def road_with_off_center_junction():
    """A degree-2 network median plus one off-centre degree-3 junction."""
    graph = nx.MultiDiGraph(crs="EPSG:4326")
    projection = page._anchor_projection(*CENTER)
    coords = {
        0: (-300, 0), 1: (-200, 0), 2: (-100, 0), 3: (0, 0),
        4: (100, 0), 5: (200, 0), 6: (300, 0), 7: (-200, 100),
    }
    for node, (x, y) in coords.items():
        lon, lat = projection.transform(x, y, direction=TransformDirection.INVERSE)
        graph.add_node(node, x=lon, y=lat)
    for u, v in [(0, 1), (1, 2), (2, 3), (3, 4), (4, 5), (5, 6), (1, 7)]:
        graph.add_edge(u, v, length=100.0)
        graph.add_edge(v, u, length=100.0)
    return graph


def brute_force_composite(graph):
    """Independent reference for the documented rank-v2 composite (all nodes are
    destinations and reference nodes when the graph is small enough)."""
    simple = nx.Graph(graph)
    closeness = nx.closeness_centrality(simple, distance="length")
    nodes = sorted(simple)
    degree = {n: simple.degree(n) for n in nodes}
    projection = page._anchor_projection(*CENTER)
    inside = [n for n in nodes
              if np.hypot(*projection.transform(graph.nodes[n]["x"], graph.nodes[n]["y"])) <= 4000]
    junctions = [n for n in nodes if degree[n] >= 3]
    xy = {n: projection.transform(graph.nodes[n]["x"], graph.nodes[n]["y"]) for n in nodes}
    density = {n: sum(np.hypot(xy[n][0] - xy[j][0], xy[n][1] - xy[j][1]) <= 500 + 1e-6
                      for j in junctions) for n in inside}
    pool = [n for n in inside if degree[n] >= 3]
    c_all = np.array([closeness[n] for n in inside])
    mean, std = c_all.mean(), c_all.std()
    from scipy.special import ndtr

    def midrank(values):
        return (rankdata(values, method="average") - 0.5) / len(values)

    d_rank = dict(zip(pool, midrank([degree[n] for n in pool])))
    j_rank = dict(zip(pool, midrank([density[n] for n in pool])))
    score = {n: .5 * float(ndtr((closeness[n] - mean) / std)) + .3 * d_rank[n] + .2 * j_rank[n]
             for n in pool}
    best = max(pool, key=lambda n: (score[n], -nodes.index(n)))
    return best, score[best], closeness[best]


def test_exact_scores_match_networkx_and_an_independent_brute_force():
    graph = road_grid()
    result = search(graph)
    best, best_score, best_closeness = brute_force_composite(graph)
    anchor = result["anchor"]
    assert anchor["node_id"] == str(best) == "60"
    assert anchor["score"] == pytest.approx(best_score)
    assert anchor["closeness"] == pytest.approx(best_closeness)
    assert anchor["score"] == pytest.approx(
        .5 * anchor["closeness_norm"] + .3 * anchor["degree_norm"] + .2 * anchor["density_norm"])
    assert result["converged"] and result["density_source"] == "road-junctions-only"
    json.dumps(find(), allow_nan=False)


def test_second_anchor_is_closeness_100_and_uses_all_inside_road_nodes():
    both = find(road_with_off_center_junction())
    composite, closeness = both["composite"], both["closeness"]

    # Composite keeps the junction-only candidate rule.
    assert composite["anchor"]["node_id"] == "1"
    assert composite["candidate_nodes"] == 1

    # Closeness 100% searches every inside road node and can select degree-2.
    assert closeness["objective"] == "closeness"
    assert closeness["method"] == "exact-scipy-closeness-100"
    assert closeness["candidate_nodes"] == closeness["destination_nodes"] == 8
    assert closeness["globally_certified"]
    assert closeness["anchor"]["node_id"] == "2"
    assert closeness["anchor"]["degree"] == 2
    assert closeness["anchor"]["score"] == pytest.approx(closeness["anchor"]["closeness_norm"])
    assert closeness["anchor"]["source"] == "Automated CBD Anchor — Closeness 100%"


def test_parallel_reverse_edges_take_minimum_not_sum():
    graph = road_grid()
    baseline = find(graph)
    graph.add_edge(0, 1, length=10000)
    graph.add_edge(1, 0, length=20000)
    result = find(graph)
    for objective in ("composite", "closeness"):
        assert result[objective]["anchor"] == baseline[objective]["anchor"]


def test_reproducible_with_reversed_insertion_order_and_repeated_calls():
    graph = road_grid()
    reordered = nx.MultiDiGraph(crs="EPSG:4326")
    reordered.add_nodes_from(reversed(list(graph.nodes(data=True))))
    reordered.add_edges_from(reversed(list(graph.edges(data=True))))
    first, again, other = find(graph), find(graph), find(reordered)
    for objective in ("composite", "closeness"):
        assert first[objective]["anchor"] == again[objective]["anchor"] == other[objective]["anchor"]
        assert first[objective]["stability"] == again[objective]["stability"]


def test_there_is_no_seed_or_restart_parameter_any_more():
    with pytest.raises(TypeError):
        find(random_seed=1)
    with pytest.raises(TypeError):
        find(restarts=4)
    assert not hasattr(page, "automated_coarse_to_fine_anchor")


def test_global_certificate_includes_every_candidate_and_finds_the_centre():
    result = search()
    assert result["globally_certified"]
    assert result["certification"] == "exhaustive-fixed-objective"
    assert result["evaluated_nodes"] == result["candidate_nodes"] == 117
    assert result["destination_nodes"] == 121
    assert result["anchor"]["node_id"] == "60"
    assert page.calculate_distance_meters(*CENTER, result["anchor"]["lat"],
                                          result["anchor"]["lon"]) < 1


@pytest.mark.parametrize("objective", ["composite", "closeness"])
def test_over_budget_search_is_screened_not_certified_and_matches_exhaustive(objective):
    grid = road_grid(size=21)
    exhaustive = search(grid, objective)
    screened = search(grid, objective, max_rows=60)
    assert exhaustive["globally_certified"]
    assert not screened["globally_certified"]
    assert screened["certification"] == "pivot-screened-exact-top-k"
    assert screened["method"].startswith("pivot-screened-exact-scipy")
    assert screened["screening"]["pivots"] > 0 and screened["screening"]["screened_top_k"] > 0
    assert screened["screening"]["extra_rows"] <= 60  # the screen never exceeds the budget
    assert any("global optimum" in w for w in screened["warnings"])
    assert screened["anchor"]["node_id"] == exhaustive["anchor"]["node_id"] == "220"


def test_one_objective_can_be_exhaustive_while_the_other_is_screened():
    grid = road_grid(size=21)
    full = find(grid)
    mixed = find(grid, max_rows=440)  # composite pool 437 fits, closeness pool 441 does not
    assert mixed["composite"]["certification"] == "exhaustive-fixed-objective"
    assert mixed["closeness"]["certification"] == "pivot-screened-exact-top-k"
    for objective in ("composite", "closeness"):
        assert mixed[objective]["anchor"]["node_id"] == full[objective]["anchor"]["node_id"]


def test_row_budget_defaults_scale_with_graph_size():
    assert find()["rows_budget"] == page.ANCHOR_CONFIG["max_rows"]
    assert page.ANCHOR_CONFIG["max_row_nodes"] // 40_000 == 750


def test_timings_and_graph_info_are_reported():
    result = find()
    timings = result["timings"]
    assert {"prep_s", "pivots_s", "exact_s", "compute_s"} <= set(timings)
    assert timings["compute_s"] >= timings["prep_s"] >= 0
    assert result["graph"] == {"nodes": 121, "edges": 220, "dropped_nodes": 0}
    assert result["composite"]["compute_seconds"] == timings["compute_s"]


def test_disconnected_island_excluded():
    graph = road_grid()
    graph.add_node(999, x=CENTER[1], y=CENTER[0])
    result = search(graph)
    assert result["anchor"]["node_id"] == "60"
    assert result["graph_nodes"] == 121
    assert any("ไม่เชื่อมต่อ" in w for w in result["warnings"])


def test_buffer_paths_remain_available_but_destinations_stay_inside():
    # The shortest route between inside nodes leaves the study circle.
    graph = nx.MultiDiGraph(crs="EPSG:4326")
    projection = page._anchor_projection(*CENTER)
    for i, x in enumerate((-900, 900, 1100)):
        lon, lat = projection.transform(x, 0, direction=TransformDirection.INVERSE)
        graph.add_node(i, x=lon, y=lat)
    graph.add_edge(0, 1, length=10000)
    graph.add_edge(0, 2, length=2000)
    graph.add_edge(2, 1, length=200)
    for objective in ("composite", "closeness"):
        result = search(graph, objective, study_radius_m=1000)
        assert result["destination_nodes"] == 2
        assert result["graph_nodes"] == 3
        assert result["anchor"]["node_id"] != "2"
        assert result["anchor"]["closeness"] == pytest.approx(1 / 2200)


@pytest.mark.parametrize("length", [None, -1, 0, float("nan"), float("inf")])
def test_invalid_lengths_rejected(length):
    graph = road_grid()
    graph[0][1][0]["length"] = length
    with pytest.raises(ValueError, match="length|lengths"):
        find(graph)


def test_bad_graphs_and_resource_limits(monkeypatch):
    with pytest.raises(ValueError, match="2–100"):
        find(nx.MultiDiGraph())
    with pytest.raises(ValueError, match="row budget"):
        find(max_rows=0)
    with pytest.raises(ValueError, match="final radius"):
        find(final_radius_m=0)
    graph = road_grid()
    del graph.nodes[3]["x"]
    with pytest.raises(ValueError, match="x/y"):
        find(graph)
    monkeypatch.setattr(page, "HAS_SCIPY", False)
    with pytest.raises(RuntimeError, match="SciPy"):
        find()


def test_large_graph_never_raises_a_budget_error():
    # The old search raised when the evaluation budget was exceeded; the screen degrades instead.
    result = search(road_grid(size=21), max_rows=1)
    assert result["anchor"]["node_id"] and not result["globally_certified"]


def test_invalid_geometry_and_projection():
    with pytest.raises(ValueError, match="centre"):
        page.anchor_study_polygon(float("nan"), 100, 4000)
    with pytest.raises(ValueError, match="antimeridian"):
        page.anchor_study_polygon(20, 179.99, 10000)
    graph = road_grid()
    graph.graph["crs"] = "EPSG:3857"
    with pytest.raises(ValueError, match="WGS84"):
        find(graph)


def test_buffer_is_twenty_percent():
    polygon = page.anchor_study_polygon(*CENTER, 10000)
    projection = page._anchor_projection(*CENTER)
    for lon, lat in polygon.exterior.coords:
        assert np.linalg.norm(projection.transform(lon, lat)) == pytest.approx(12000, abs=.01)


def test_collapsed_csr_keeps_the_shortest_parallel_or_reverse_edge():
    graph = nx.MultiDiGraph()
    graph.add_edge("a", "b", length=30.0)
    graph.add_edge("b", "a", length=10.0)
    graph.add_edge("a", "b", length=20.0)
    graph.add_edge("a", "a", length=5.0)  # self loop dropped
    graph.add_edge("b", "c", length=7.0)
    matrix = page._collapsed_csr(graph, ["a", "b", "c"])
    assert matrix.toarray().tolist() == [[0, 10, 0], [10, 0, 7], [0, 7, 0]]
    assert (np.diff(matrix.indptr) == [1, 2, 1]).all()  # distinct neighbours, no duplicates


def test_automated_anchor_overrides_centroid_and_rent_works_without_isochrone():
    result = search()
    intersection = {"features": [{"geometry": {
        "type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]}}]}
    assert page.resolve_cbd_anchor(intersection, None, None, [], result) == result["anchor"]
    data = page.compute_rent_gradient_data(None, None, None, [], [], "index", result)
    assert data["anchor"] == result["anchor"]
    assert data["model"]["is_index"]
    assert data["rings_geojson"]["features"]


def test_state_roundtrip_and_full_clear(monkeypatch):
    both = find()
    state = dict(page.StateManager._DEFAULTS)
    state["markers"] = []
    state["automated_anchor_data"] = both["composite"]
    state["automated_anchor_closeness_data"] = both["closeness"]
    monkeypatch.setattr(page.st, "session_state", state)
    exported = json.loads(page.StateManager.export_config())
    page.StateManager.clear_results()
    assert state["automated_anchor_data"] is None
    assert state["automated_anchor_closeness_data"] is None
    page.StateManager.import_config(exported)
    assert state["automated_anchor_data"]["anchor"]["node_id"] == "60"
    assert state["automated_anchor_closeness_data"]["anchor"]["node_id"] == "60"
    page.StateManager.import_config({"markers": []})
    assert state["automated_anchor_data"] is None
    assert state["automated_anchor_closeness_data"] is None
    assert state["rent_gradient_data"] is None


def test_old_saved_context_with_seed_and_restarts_still_matches():
    current = {"study_center": [20.0, 100.0], "study_radius_m": 10000.0, "network_type": "drive"}
    legacy = dict(current, random_seed=42, restarts=4)
    assert page._anchor_context_matches(legacy, current)
    assert page._anchor_context_matches(current, current)
    assert not page._anchor_context_matches(dict(legacy, study_radius_m=9000.0), current)
    assert not page._anchor_context_matches(dict(legacy, network_type="walk"), current)
    assert not page._anchor_context_matches(None, current)


def test_single_coordinate_input_parser():
    value = "20.075226819421776, 100.5083729446834"
    assert page._parse_anchor_center_input(value) == (
        20.075226819421776,
        100.5083729446834,
    )
    assert page._parse_anchor_center_input(" 20.1 , 100.2 ") == (20.1, 100.2)
    with pytest.raises(ValueError, match="Lat, Lon"):
        page._parse_anchor_center_input("20.1")
    with pytest.raises(ValueError, match="Lat"):
        page._parse_anchor_center_input("90, 100.2")
    with pytest.raises(ValueError, match="Lon"):
        page._parse_anchor_center_input("20.1, 181")


def _app_test(monkeypatch, graph_factory=road_grid, fetch=None):
    from streamlit.testing.v1 import AppTest

    def app():
        import rent_gradient_test
        rent_gradient_test.main()

    monkeypatch.setattr(page.StateManager, "_load_remote_defaults", staticmethod(lambda defaults: []))
    monkeypatch.setattr(page, "_fetch_osm_graph",
                        fetch or (lambda *args: (graph_factory(), True, None)))
    return AppTest.from_function(app).run(timeout=30)


def _anchor_button(at):
    return next(b for b in at.button if b.label == "🎯 ค้นหา CBD Anchor อัตโนมัติ")


def test_streamlit_single_coordinate_input_updates_legacy_state(monkeypatch):
    from streamlit.testing.v1 import AppTest

    def app():
        import rent_gradient_test
        rent_gradient_test.main()

    monkeypatch.setattr(page.StateManager, "_load_remote_defaults", staticmethod(lambda defaults: []))
    at = AppTest.from_function(app).run(timeout=30)
    assert not at.exception

    center = at.text_input(key="anchor_center_input")
    center.set_value("20.075226819421776, 100.5083729446834").run(timeout=30)
    assert not at.exception
    assert at.session_state["anchor_lat"] == pytest.approx(20.075226819421776)
    assert at.session_state["anchor_lon"] == pytest.approx(100.5083729446834)


def test_streamlit_one_button_publishes_both_anchors_and_keeps_rent_on_composite(monkeypatch):
    at = _app_test(monkeypatch)
    assert not at.exception
    assert [b.label for b in at.button if "Closeness 100%" in b.label] == []  # no second button
    assert not at.number_input(key="anchor_radius_km").disabled
    with pytest.raises(KeyError):
        at.number_input(key="anchor_seed")  # seed/restart inputs are gone

    _anchor_button(at).click().run(timeout=30)
    assert not at.exception
    composite = at.session_state["automated_anchor_data"]
    closeness = at.session_state["automated_anchor_closeness_data"]
    assert composite["anchor"]["source"] == "Automated CBD Anchor"
    assert closeness["anchor"]["source"] == "Automated CBD Anchor — Closeness 100%"
    # The Closeness-100% anchor is comparison-only: Rent Gradient keeps using the composite.
    assert at.session_state["rent_gradient_data"]["anchor"]["source"] == "Automated CBD Anchor"
    assert set(composite["context"]) == {"study_center", "study_radius_m", "network_type"}
    assert composite["graph"]["source"] == "cache" and composite["load_seconds"] >= 0
    assert composite["stability"]["level"] in {"stable", "check", "unstable"}
    captions = " ".join(c.value for c in at.caption)
    assert "ความนิ่ง" in captions and "โหลดข้อมูลถนน" in captions


def test_streamlit_radius_change_clears_but_legacy_context_fields_do_not(monkeypatch):
    at = _app_test(monkeypatch)
    _anchor_button(at).click().run(timeout=30)
    assert at.session_state["automated_anchor_data"] is not None

    # Results saved by the old seeded search carry random_seed/restarts in their context.
    for key in ("automated_anchor_data", "automated_anchor_closeness_data"):
        at.session_state[key]["context"].update(random_seed=7, restarts=9)
    at.run(timeout=30)
    assert not at.exception
    assert at.session_state["automated_anchor_data"] is not None
    assert at.session_state["automated_anchor_closeness_data"] is not None

    at.number_input(key="anchor_radius_km").set_value(9.0).run(timeout=30)
    assert not at.exception
    assert at.session_state["automated_anchor_data"] is None
    assert at.session_state["automated_anchor_closeness_data"] is None
    assert at.session_state["rent_gradient_data"] is None


def test_streamlit_download_failure_does_not_publish_partial_result(monkeypatch):
    at = _app_test(monkeypatch, fetch=lambda *args: (None, False, "OSM unavailable"))
    _anchor_button(at).click().run(timeout=30)
    assert not at.exception
    assert any("OSM unavailable" in e.value for e in at.error)
    assert at.session_state["automated_anchor_data"] is None
    assert at.session_state["automated_anchor_closeness_data"] is None


def test_map_shows_both_anchors_and_no_search_path_layers(monkeypatch):
    rendered = []
    monkeypatch.setattr(page, "st_folium", lambda m, **kwargs: rendered.append(m) or {})
    at = _app_test(monkeypatch)
    _anchor_button(at).click().run(timeout=30)
    assert not at.exception
    markers = [v for v in rendered[-1]._children.values() if isinstance(v, page.folium.Marker)]
    assert sorted(m.icon.options["marker_color"] for m in markers) == ["darkblue", "green"]
    html = rendered[-1].get_root().render()
    assert "Automated CBD Anchor" in html and "Automated CBD Anchor — Closeness 100%" in html
    assert "Automated Anchor study boundary" in html
    assert "search paths" not in html
    assert "Stability:" in html


def test_old_saved_results_with_trace_still_render(monkeypatch):
    rendered = []
    monkeypatch.setattr(page, "st_folium", lambda m, **kwargs: rendered.append(m) or {})
    at = _app_test(monkeypatch)
    legacy = dict(find()["composite"], restarts=[{"seed": {"lat": 20.0, "lon": 100.0}}],
                  trace=[{"restart": 0, "action": "move", "lat": 20.1, "lon": 100.1}],
                  context={"study_center": [page.DEFAULT_CONFIG["LAT"], page.DEFAULT_CONFIG["LON"]],
                           "study_radius_m": 10000.0, "network_type": "drive",
                           "random_seed": 42, "restarts": 4})
    legacy.pop("stability")
    legacy.pop("timings")
    at.session_state["automated_anchor_data"] = legacy
    at.run(timeout=30)
    assert not at.exception
    assert at.session_state["automated_anchor_data"] is not None  # not wiped by the new context rule
    markers = [v for v in rendered[-1]._children.values() if isinstance(v, page.folium.Marker)]
    assert [m.icon.options["marker_color"] for m in markers] == ["darkblue"]


def test_road_search_exports_candidates_for_the_evidence_stage():
    found = find()
    candidates = found["evidence_candidates"]
    assert 1 <= len(candidates) <= 2 * page.ANCHOR_CONFIG["candidate_export"]
    ids = [c["node_id"] for c in candidates]
    assert len(ids) == len(set(ids))
    for key in ("node_id", "lat", "lon", "composite_score", "closeness_norm", "degree", "junction_count"):
        assert all(key in c for c in candidates)
    # both road winners are among the exported candidates, with their exact composite score
    by_id = {c["node_id"]: c for c in candidates}
    for objective in ("composite", "closeness"):
        assert str(found[objective]["anchor"]["node_id"]) in by_id
    best = max(candidates, key=lambda c: c["composite_score"])
    assert str(found["composite"]["anchor"]["node_id"]) == best["node_id"]
    json.dumps(candidates)                                             # JSON-safe
