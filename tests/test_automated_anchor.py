"""Offline correctness and Streamlit integration tests for the road-only CBD search."""
import importlib.util
import json
from pathlib import Path
import sys

import networkx as nx
import numpy as np
import pytest
from pyproj.enums import TransformDirection

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


def search(graph=None, **kwargs):
    options = dict(study_center=CENTER, study_radius_m=4000, restarts=4)
    options.update(kwargs)
    return page.automated_coarse_to_fine_anchor(road_grid() if graph is None else graph, **options)


def test_exact_scores_match_networkx_and_fixed_objective():
    graph = road_grid()
    result = search(graph)
    reference = nx.closeness_centrality(nx.Graph(graph), distance="length")
    for step in result["trace"]:
        assert step["closeness"] == pytest.approx(reference[int(step["node_id"])])
        assert step["score"] == pytest.approx(
            .5 * step["closeness_norm"] + .3 * step["degree_norm"] + .2 * step["density_norm"])
    assert result["anchor"]["node_id"] == "60"
    assert result["converged"]
    assert result["density_source"] == "road-junctions-only"
    json.dumps(result, allow_nan=False)


def test_parallel_reverse_edges_take_minimum_not_sum():
    graph = road_grid()
    baseline = search(graph)
    graph.add_edge(0, 1, length=10000)
    graph.add_edge(1, 0, length=20000)
    result = search(graph)
    assert result["anchor"] == baseline["anchor"]
    assert result["trace"] == baseline["trace"]


def test_reproducible_with_reversed_insertion_order():
    graph = road_grid()
    reordered = nx.MultiDiGraph(crs="EPSG:4326")
    reordered.add_nodes_from(reversed(list(graph.nodes(data=True))))
    reordered.add_edges_from(reversed(list(graph.edges(data=True))))
    assert search(graph)["trace"] == search(reordered)["trace"]


def test_fifty_seeds_converge_to_synthetic_ground_truth():
    result = search(restarts=50)
    assert result["converged"]
    assert len(result["restarts"]) == 50
    assert result["restart_max_distance_m"] <= 50
    assert page.calculate_distance_meters(*CENTER, result["anchor"]["lat"],
                                          result["anchor"]["lon"]) < 1


def test_global_certificate_is_independent_of_seed_and_includes_every_candidate():
    results = [search(random_seed=seed, restarts=1) for seed in range(10)]
    assert all(r["globally_certified"] for r in results)
    assert all(r["evaluated_nodes"] == r["candidate_nodes"] == 117 for r in results)
    assert all(r["destination_nodes"] == 121 for r in results)
    assert {r["anchor"]["node_id"] for r in results} == {"60"}


def test_large_graph_local_only_is_explicit():
    result = search(road_grid(size=21), restarts=1, max_evaluations=200)
    assert not result["globally_certified"]
    assert result["certification"] == "local-only"
    assert any("global optimum" in w for w in result["warnings"])


def test_trace_moves_uphill_and_contracts_to_150m():
    result = search()
    for run in range(len(result["restarts"])):
        trace = [s for s in result["trace"] if s["restart"] == run]
        last_score = result["restarts"][run]["seed"]["score"]
        for step in trace:
            assert step["score"] >= last_score
            if step["action"] == "move":
                assert step["score"] > last_score
            last_score = step["score"]
        assert trace[-1]["radius_m"] == 150
        assert trace[-1]["action"] == "converged"


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
    result = search(graph, study_radius_m=1000, initial_radius_m=1000, restarts=2)
    assert result["destination_nodes"] == 2
    assert result["graph_nodes"] == 3
    for step in result["trace"]:
        assert step["node_id"] != "2"
        assert step["closeness"] == pytest.approx(1 / 2200)


@pytest.mark.parametrize("length", [None, -1, 0, float("nan"), float("inf")])
def test_invalid_lengths_rejected(length):
    graph = road_grid()
    graph[0][1][0]["length"] = length
    with pytest.raises(ValueError, match="length|lengths"):
        search(graph)


def test_bad_graphs_and_resource_limits(monkeypatch):
    with pytest.raises(ValueError, match="2–100"):
        search(nx.MultiDiGraph())
    with pytest.raises(ValueError, match="budget"):
        search(max_evaluations=1)
    result = search(max_iterations=1)
    assert not result["converged"]
    assert any("best-so-far" in w for w in result["warnings"])
    monkeypatch.setattr(page, "HAS_SCIPY", False)
    with pytest.raises(RuntimeError, match="SciPy"):
        search()


def test_invalid_geometry_and_projection():
    with pytest.raises(ValueError, match="centre"):
        page.anchor_study_polygon(float("nan"), 100, 4000)
    with pytest.raises(ValueError, match="antimeridian"):
        page.anchor_study_polygon(20, 179.99, 10000)
    graph = road_grid()
    graph.graph["crs"] = "EPSG:3857"
    with pytest.raises(ValueError, match="WGS84"):
        search(graph)


def test_buffer_is_twenty_percent():
    polygon = page.anchor_study_polygon(*CENTER, 10000)
    projection = page._anchor_projection(*CENTER)
    for lon, lat in polygon.exterior.coords:
        assert np.linalg.norm(projection.transform(lon, lat)) == pytest.approx(12000, abs=.01)


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
    state = dict(page.StateManager._DEFAULTS)
    state["markers"] = []
    state["automated_anchor_data"] = search()
    monkeypatch.setattr(page.st, "session_state", state)
    exported = json.loads(page.StateManager.export_config())
    page.StateManager.clear_results()
    assert state["automated_anchor_data"] is None
    page.StateManager.import_config(exported)
    assert state["automated_anchor_data"]["anchor"]["node_id"] == "60"
    page.StateManager.import_config({"markers": []})
    assert state["automated_anchor_data"] is None
    assert state["rent_gradient_data"] is None


def test_streamlit_search_and_settings_invalidation(monkeypatch):
    from streamlit.testing.v1 import AppTest

    def app():
        import rent_gradient_test
        rent_gradient_test.main()

    monkeypatch.setattr(page.StateManager, "_load_remote_defaults", staticmethod(lambda defaults: []))
    monkeypatch.setattr(page, "_fetch_osm_graph", lambda *args: (road_grid(), True, None))
    at = AppTest.from_function(app).run(timeout=30)
    assert not at.exception
    button = next(b for b in at.button if b.label == "🎯 ค้นหา CBD Anchor อัตโนมัติ")
    button.click().run(timeout=30)
    assert not at.exception
    assert at.session_state["automated_anchor_data"]["anchor"]["source"] == "Automated CBD Anchor"
    assert at.session_state["rent_gradient_data"]["anchor"]["source"] == "Automated CBD Anchor"
    at.number_input(key="anchor_seed").set_value(43).run(timeout=30)
    assert not at.exception
    assert at.session_state["automated_anchor_data"] is None
    assert at.session_state["rent_gradient_data"] is None


def test_streamlit_download_failure_does_not_publish_partial_result(monkeypatch):
    from streamlit.testing.v1 import AppTest

    def app():
        import rent_gradient_test
        rent_gradient_test.main()

    monkeypatch.setattr(page.StateManager, "_load_remote_defaults", staticmethod(lambda defaults: []))
    monkeypatch.setattr(page, "_fetch_osm_graph", lambda *args: (None, False, "OSM unavailable"))
    at = AppTest.from_function(app).run(timeout=30)
    next(b for b in at.button if b.label == "🎯 ค้นหา CBD Anchor อัตโนมัติ").click().run(timeout=30)
    assert not at.exception
    assert any("OSM unavailable" in e.value for e in at.error)
    assert at.session_state["automated_anchor_data"] is None


def test_map_has_one_darkblue_automated_marker(monkeypatch):
    from streamlit.testing.v1 import AppTest

    def app():
        import rent_gradient_test
        rent_gradient_test.main()

    rendered = []
    monkeypatch.setattr(page.StateManager, "_load_remote_defaults", staticmethod(lambda defaults: []))
    monkeypatch.setattr(page, "_fetch_osm_graph", lambda *args: (road_grid(), True, None))
    monkeypatch.setattr(page, "st_folium", lambda m, **kwargs: rendered.append(m) or {})
    at = AppTest.from_function(app).run(timeout=30)
    next(b for b in at.button if b.label == "🎯 ค้นหา CBD Anchor อัตโนมัติ").click().run(timeout=30)
    assert not at.exception
    markers = [v for v in rendered[-1]._children.values() if isinstance(v, page.folium.Marker)]
    assert len(markers) == 1
    assert markers[0].icon.options["marker_color"] == "darkblue"
    html = rendered[-1].get_root().render()
    assert "Automated CBD Anchor" in html
    assert "Automated Anchor search paths" in html
