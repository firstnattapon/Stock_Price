"""Rent_Gradient_new: space-syntax analysis, red→blue gradient, exports and the Streamlit flow (offline).

The analysis is checked three ways:
  1. hand-computed answers on tiny networks (a chain, a plus, a T, an L, a bent segment),
  2. an independent brute-force reference written with networkx (explicit state graph, explicit path
     walking) on random planar street networks, for angular / topological / metric depth, global and
     local radii — NC, TD and the Choice counts must agree exactly,
  3. the real Chiang Khong graphs bundled in ``Geoapify_Map/osmnx_cache.zip``.
Nothing here touches the network: Overpass is never called.
"""
import importlib.machinery
import importlib.util
import io
import json
import math
import sys
from pathlib import Path

import numpy as np
import pytest

nx = pytest.importorskip("networkx")
pytest.importorskip("scipy")
pytest.importorskip("shapely")
pytest.importorskip("streamlit")
pytest.importorskip("folium")
pytest.importorskip("matplotlib")
pd = pytest.importorskip("pandas")
from scipy.spatial import Delaunay  # noqa: E402
from streamlit.testing.v1 import AppTest  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "pages" / "Rent_Gradient_new"          # kept without ".py" so it is no longer a Streamlit page
BUNDLE = ROOT / "Geoapify_Map" / "osmnx_cache.zip"


def _load_page():
    loader = importlib.machinery.SourceFileLoader("rent_gradient_new_under_test", str(PAGE))   # no ".py" suffix
    spec = importlib.util.spec_from_file_location("rent_gradient_new_under_test", PAGE, loader=loader)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


rgn = _load_page()

LAT0, LON0 = 20.2, 100.4


# ----------------------------------------------------------------------------- helpers
def lonlat(x, y):
    """Local metres → (lon, lat) around (LON0, LAT0)."""
    return LON0 + x / (math.cos(math.radians(LAT0)) * 111_320.0), LAT0 + y / 110_574.0


def street_graph(nodes, edges, two_way=True):
    """OSMnx-like MultiDiGraph. ``nodes``: {id: (x_m, y_m)}; ``edges``: (a, b) or (a, b, [(x, y), …])."""
    g = nx.MultiDiGraph()
    for n, (x, y) in nodes.items():
        lon, lat = lonlat(x, y)
        g.add_node(n, x=lon, y=lat)
    for edge in edges:
        a, b = edge[0], edge[1]
        pts = edge[2] if len(edge) > 2 else [nodes[a], nodes[b]]
        length = float(sum(math.hypot(q[0] - p[0], q[1] - p[1]) for p, q in zip(pts[:-1], pts[1:])))
        geometry = rgn.LineString([lonlat(*p) for p in pts]) if len(edge) > 2 else None
        data = {"length": length, **({"geometry": geometry} if geometry is not None else {})}
        g.add_edge(a, b, **data)
        if two_way:
            rev = dict(data)
            if geometry is not None:
                rev["geometry"] = rgn.LineString(list(geometry.coords)[::-1])
            g.add_edge(b, a, **rev)
    return g


def chain(n_seg, seg_len=100.0):
    nodes = {i: (i * seg_len, 0.0) for i in range(n_seg + 1)}
    return street_graph(nodes, [(i, i + 1) for i in range(n_seg)])


def random_street_graph(seed, n_points=30, drop=0.30):
    """Delaunay street network with irregular angles (no accidental exact ties)."""
    rng = np.random.default_rng(seed)
    pts = rng.uniform(0, 1500, size=(n_points, 2))
    edges = set()
    for simplex in Delaunay(pts).simplices:
        for i in range(3):
            edges.add(tuple(sorted((int(simplex[i]), int(simplex[(i + 1) % 3])))))
    keep = [e for e in sorted(edges) if rng.random() > drop]
    g = nx.Graph()
    g.add_edges_from(keep)
    comp = max(nx.connected_components(g), key=len)
    keep = [e for e in keep if e[0] in comp and e[1] in comp]
    nodes = {n: tuple(pts[n]) for n in comp}
    return street_graph(nodes, keep)


def grid_graph(n, seed=0, spacing=95.0, jitter=14.0):
    rng = np.random.default_rng(seed)
    nodes = {(i, j): (i * spacing + rng.normal(0, jitter), j * spacing + rng.normal(0, jitter))
             for i in range(n) for j in range(n)}
    edges = [(a, (a[0] + di, a[1] + dj)) for a in nodes for di, dj in ((1, 0), (0, 1))
             if (a[0] + di, a[1] + dj) in nodes]
    return street_graph(nodes, edges)


def seg_of(net, graph, a, b):
    """Segment index of the street between graph nodes ``a`` and ``b``."""
    order = sorted(graph.nodes, key=rgn._node_sort_key)
    pair = sorted((order.index(a), order.index(b)))
    hits = np.flatnonzero((net.seg_a == pair[0]) & (net.seg_b == pair[1]))
    assert len(hits) == 1, (a, b, hits)
    return int(hits[0])


def run(graph, **kwargs):
    net = rgn.build_segment_network(graph)
    return net, rgn.analyse_network(net, **kwargs)


# ------------------------------------------------------------ independent reference
def reference_analysis(graph, net, kind, radius, turn=0.0):
    """Brute force with networkx: explicit state graph, explicit shortest-path walking."""
    order = sorted(graph.nodes, key=rgn._node_sort_key)
    pos = {n: net.node_xy[i] for i, n in enumerate(order)}
    simple = nx.Graph()
    simple.add_edges_from((u, v, {"length": d["length"]}) for u, v, d in graph.edges(data=True))
    segs = sorted(tuple(sorted(e, key=rgn._node_sort_key)) for e in simple.edges)
    sid = {e: i for i, e in enumerate(segs)}
    key = lambda x, y: tuple(sorted((x, y), key=rgn._node_sort_key))  # noqa: E731
    length = lambda x, y: simple[x][y]["length"]  # noqa: E731
    tie = rgn.ANALYSIS_CONFIG["tie_break_per_m"]
    states, metric = nx.DiGraph(), nx.DiGraph()
    for n in simple.nodes:
        for p in simple.neighbors(n):
            for q in simple.neighbors(n):
                if p == q:
                    continue
                h1 = pos[n] - pos[p]
                h2 = pos[q] - pos[n]
                h1, h2 = h1 / np.hypot(*h1), h2 / np.hypot(*h2)
                angle = math.degrees(math.acos(max(-1.0, min(1.0, float(h1 @ h2)))))
                step = 0.5 * (length(p, n) + length(n, q))
                if kind == "angular":
                    cost = angle / 90.0 + tie * step
                elif kind == "topological":
                    cost = (1.0 if turn <= 0 else float(angle > turn)) + tie * step
                else:
                    cost = step
                states.add_edge((p, n), (n, q), w=cost)
                metric.add_edge((p, n), (n, q), w=step)
    n_seg = len(segs)
    nc, td, ch = np.zeros(n_seg), np.zeros(n_seg), np.zeros(n_seg)
    for i, (a, b) in enumerate(segs):
        roots = [(a, b), (b, a)]
        if radius is None:
            inside = set(range(n_seg))
        else:
            near = nx.multi_source_dijkstra_path_length(metric, roots, weight="w")
            best = {}
            for st, d in near.items():
                k = sid[key(*st)]
                best[k] = min(best.get(k, math.inf), d)
            inside = {k for k, d in best.items() if d <= radius + 1e-9}
        sub = states.subgraph([st for k in inside for st in (segs[k], segs[k][::-1])])
        dist = nx.multi_source_dijkstra_path_length(sub, roots, weight="w")
        paths = nx.multi_source_dijkstra_path(sub, roots, weight="w")
        found = {}
        for st, d in dist.items():
            k = sid[key(*st)]
            if k not in found or d < found[k][0]:
                found[k] = (d, st)
        nc[i] = len(found)
        td[i] = sum(d for d, _ in found.values())
        for k, (_, st) in found.items():
            if k != i:
                for mid in paths[st][1:-1]:
                    ch[sid[key(*mid)]] += 1
    return segs, sid, nc, td, ch


def aligned(net, graph, segs):
    """Permutation taking reference segment order to the page's segment order."""
    order = sorted(graph.nodes, key=rgn._node_sort_key)
    mine = {tuple(sorted((order[a], order[b]), key=rgn._node_sort_key)): i
            for i, (a, b) in enumerate(zip(net.seg_a, net.seg_b))}
    return np.array([mine[e] for e in segs])


# ================================================================ segment network
def test_two_way_street_is_one_segment_and_straight_on_costs_nothing():
    g = chain(2)
    net = rgn.build_segment_network(g)
    assert net.n_segments == 2 and net.n_nodes == 3
    assert len(net.tr_from) == 2  # a→b then b→a through the middle node
    assert np.allclose(net.tr_deflection_deg, 0.0, atol=0.05)
    assert np.allclose(net.seg_bend_deg, 0.0)


def test_parallel_roads_and_loops_are_kept_but_the_reverse_twin_is_not():
    nodes = {"a": (0.0, 0.0), "b": (200.0, 0.0), "c": (300.0, 0.0)}
    g = street_graph(nodes, [
        ("a", "b"),
        ("a", "b", [(0, 0), (100, 60), (200, 0)]),  # a genuinely different parallel road
        ("b", "c"),
        ("c", "c", [(300, 0), (330, 30), (300, 60), (270, 30), (300, 0)]),  # a cul-de-sac loop
    ])
    net = rgn.build_segment_network(g)
    assert net.n_segments == 4
    assert (net.seg_a == net.seg_b).sum() == 1  # the loop survives
    assert len({tuple(p.ravel().round(6)) for p in net.seg_lonlat}) == 4


def test_length_falls_back_to_geometry_when_osm_length_is_missing_or_invalid():
    g = chain(1)
    for _, _, d in g.edges(data=True):
        d["length"] = float("nan")
    net = rgn.build_segment_network(g)
    assert net.seg_len[0] == pytest.approx(100.0, rel=1e-3)


def test_bad_graphs_raise_value_error():
    with pytest.raises(ValueError):
        rgn.build_segment_network(nx.MultiDiGraph())
    g = nx.MultiDiGraph()
    g.add_node(1, x=100.4, y=20.2)
    g.add_node(2)  # no coordinates
    g.add_edge(1, 2, length=10.0)
    with pytest.raises(ValueError):
        rgn.build_segment_network(g)
    only_nodes = nx.MultiDiGraph()
    only_nodes.add_node(1, x=100.4, y=20.2)
    only_nodes.add_node(2, x=100.41, y=20.2)
    with pytest.raises(ValueError):
        rgn.build_segment_network(only_nodes)


def test_end_directions_and_bend_come_from_the_geometry():
    nodes = {"a": (0.0, 0.0), "b": (100.0, 100.0)}
    g = street_graph(nodes, [("a", "b", [(0, 0), (100, 0), (100, 100)])])  # east, then north
    net = rgn.build_segment_network(g)
    assert net.seg_bend_deg[0] == pytest.approx(90.0, abs=0.2)
    assert np.allclose(net.seg_dir_a[0], (1, 0), atol=1e-3)  # leaves a heading east
    assert np.allclose(net.seg_dir_b[0], (0, -1), atol=1e-3)  # leaves b heading south
    # half-way along the L, compared in lon/lat so the check does not depend on the page's local frame
    assert np.allclose(net.seg_mid_lonlat[0], lonlat(100.0, 0.0), atol=1e-6)


def test_digitising_jitter_does_not_count_as_turning():
    jitter = [(i * 25.0, 1.2 * (-1) ** i) for i in range(9)]  # ±1.2 m zig-zag on a straight road
    g = street_graph({"a": jitter[0], "b": jitter[-1]}, [("a", "b", jitter)])
    net = rgn.build_segment_network(g)
    assert net.seg_bend_deg[0] == pytest.approx(0.0, abs=1e-6)


def test_names_and_highway_tags_may_be_lists():
    g = chain(1)
    for _, _, d in g.edges(data=True):
        d["name"] = ["Sai Klang", "Other"]
        d["highway"] = ["secondary", "tertiary"]
    net = rgn.build_segment_network(g)
    assert net.seg_name == ["Sai Klang"] and net.seg_highway == ["secondary"]


def test_midpoint_is_by_arc_length_in_metres_not_degrees():
    # an L whose long leg is east-west: measured in raw degrees the east-west leg would look ~6 % too long
    xy = np.array([[0.0, 0.0], [100.0, 0.0], [100.0, 40.0]])
    lonlat_pts = np.array([lonlat(*p) for p in xy])
    mid_xy, mid_ll = rgn._polyline_midpoints(xy, lonlat_pts)
    assert np.allclose(mid_xy, [70.0, 0.0], atol=1e-9)  # 140 m long → 70 m along, still on the 1st leg
    assert np.allclose(mid_ll, lonlat(70.0, 0.0), atol=1e-9)
    same = rgn._polyline_midpoints(np.zeros((2, 2)), np.array([[100.4, 20.2], [100.4, 20.2]]))
    assert np.allclose(same[1], [100.4, 20.2])  # zero-length polyline does not divide by 0


def test_a_two_way_loop_road_is_one_segment():
    ring = [(300, 0), (330, 30), (300, 60), (270, 30), (300, 0)]
    g = street_graph({"a": (0, 0), "c": (300, 0)}, [("a", "c"), ("c", "c", ring)])
    assert rgn.build_segment_network(g).n_segments == 2  # ring + its reversed twin collapse


def test_segments_in_circle_uses_midpoints():
    net = rgn.build_segment_network(chain(5))  # midpoints x = 50 … 450
    centre_lon, centre_lat = lonlat(50.0, 0.0)
    near = rgn.segments_in_circle(net, centre_lat, centre_lon, 120.0)
    assert near.sum() == 2 and near[0] and near[1]


# ================================================================ hand-computed analysis
def test_straight_chain_has_zero_depth_and_the_middle_carries_all_choice():
    g = chain(3)
    net, res = run(g, radii=(None,), with_choice=True)
    assert np.all(res.nc["n"] == 3)
    assert np.allclose(res.td["n"], 0.0, atol=1e-6)
    assert np.allclose(res.integration["n"], 3 ** 1.2 / 2.0, atol=1e-6)
    middle = seg_of(net, g, 1, 2)
    assert res.choice["n"][middle] == 2.0  # A→C and C→A
    assert res.choice["n"].sum() == 2.0
    assert res.choice_norm["n"][middle] == pytest.approx(1.0, abs=1e-6)  # ln(2+1)/ln(0+3)


def test_plus_junction_every_spoke_is_equally_integrated():
    nodes = {"o": (0, 0), "n": (0, 100), "s": (0, -100), "e": (100, 0), "w": (-100, 0)}
    g = street_graph(nodes, [("o", k) for k in "nsew"])
    _, res = run(g, radii=(None,), with_choice=True)
    assert np.all(res.nc["n"] == 4)
    assert np.allclose(res.td["n"], 2.0, atol=1e-3)  # opposite 0, two sides 1 each
    assert np.allclose(res.integration["n"], 4 ** 1.2 / 4.0, atol=1e-3)
    assert np.all(res.choice["n"] == 0)  # paths end at the junction, not beyond


def test_t_junction_the_spur_is_less_integrated_than_the_through_road():
    nodes = {"w": (-100, 0), "o": (0, 0), "e": (100, 0), "n": (0, 100)}
    g = street_graph(nodes, [("w", "o"), ("o", "e"), ("o", "n")])
    net, res = run(g, radii=(None,), with_choice=False)
    west, spur = seg_of(net, g, "w", "o"), seg_of(net, g, "o", "n")
    assert res.td["n"][west] == pytest.approx(1.0, abs=1e-3)  # east 0, spur 1
    assert res.td["n"][spur] == pytest.approx(2.0, abs=1e-3)  # west 1, east 1
    assert res.integration["n"][west] == pytest.approx(3 ** 1.2 / 3.0, abs=1e-3)
    assert res.integration["n"][spur] == pytest.approx(3 ** 1.2 / 4.0, abs=1e-3)
    assert res.integration["n"][west] > res.integration["n"][spur]


def test_right_angle_costs_one_and_a_hairpin_costs_two():
    g = street_graph({"a": (0, 0), "b": (100, 0), "c": (100, 100)}, [("a", "b"), ("b", "c")])
    _, res = run(g, radii=(None,), with_choice=False)
    assert np.allclose(res.td["n"], 1.0, atol=1e-3)
    assert np.allclose(res.integration["n"], 2 ** 1.2 / 3.0, atol=1e-3)
    # c doubles back beside a, so b → c turns ≈ 176.6°
    hairpin = street_graph({"a": (0, 0), "b": (100, 0), "c": (0, 6)}, [("a", "b"), ("b", "c")])
    _, res2 = run(hairpin, radii=(None,), with_choice=False)
    assert np.allclose(res2.td["n"], 176.6 / 90.0, atol=0.02)  # ≈ 176.6° turn → 1.96


def test_internal_bend_counts_half_at_the_ends_and_in_full_when_passing_through():
    #   a ──── b ┐            first : straight, east
    #            └──── c ──── d    bent  : east 100 m then north 100 m (a 90° bend inside the segment)
    #                              last  : straight, east (so the turn at c is another 90°)
    nodes = {"a": (-100, 0), "b": (0, 0), "c": (100, 100), "d": (200, 100)}
    g = street_graph(nodes, [("a", "b"), ("b", "c", [(0, 0), (100, 0), (100, 100)]), ("c", "d")])
    net, res = run(g, radii=(None,), with_choice=False)
    first, bent, last = seg_of(net, g, "a", "b"), seg_of(net, g, "b", "c"), seg_of(net, g, "c", "d")
    matrix = rgn.state_matrix(net, "angular")

    def depth_from(origin):
        return rgn._tree_from(matrix, (2 * origin, 2 * origin + 1), False)[0].reshape(-1, 2).min(axis=1)

    from_first = depth_from(first)
    assert from_first[bent] == pytest.approx(0.5, abs=5e-3)  # half of the bent segment's own 90°
    # through it: both half-bends meet (1.0) + the 90° turn at c (1.0)
    assert from_first[last] == pytest.approx(0.5 + 0.5 + 1.0, abs=5e-3)
    assert from_first[first] == 0.0
    from_bent = depth_from(bent)
    assert from_bent[first] == pytest.approx(0.5, abs=5e-3)
    assert from_bent[last] == pytest.approx(0.5 + 1.0, abs=5e-3)  # half its bend + the 90° turn at c
    assert np.allclose(res.td["n"][[first, bent, last]], [2.5, 2.0, 3.5], atol=0.02)


def test_depth_is_symmetric_between_any_two_segments():
    g = random_street_graph(4)
    net = rgn.build_segment_network(g)
    matrix = rgn.state_matrix(net, "angular")
    depth = np.array([rgn._tree_from(matrix, (2 * s, 2 * s + 1), False)[0].reshape(-1, 2).min(axis=1)
                      for s in range(net.n_segments)])
    assert np.allclose(depth, depth.T, atol=1e-7)


def test_radius_selects_segments_by_metric_distance_midpoint_to_midpoint():
    g = chain(5)
    net = rgn.build_segment_network(g)
    res = rgn.analyse_network(net, radii=(250.0, 350.0, None), with_choice=False)
    first, last = seg_of(net, g, 0, 1), seg_of(net, g, 4, 5)
    assert res.nc["250"][first] == 3  # itself + 100 m + 200 m
    assert res.nc["350"][first] == 4
    assert res.nc["n"][first] == 5
    assert res.nc["250"][seg_of(net, g, 2, 3)] == 5  # 200 m either side reaches all
    assert np.all(res.nc["250"] <= res.nc["350"]) and np.all(res.nc["350"] <= res.nc["n"])
    assert res.nc["250"][last] == 3


def test_disconnected_components_are_analysed_separately():
    nodes = {0: (0, 0), 1: (100, 0), 2: (200, 0), 10: (0, 500), 11: (100, 500)}
    g = street_graph(nodes, [(0, 1), (1, 2), (10, 11)])
    net, res = run(g, radii=(None,), with_choice=True)
    lone = seg_of(net, g, 10, 11)
    assert res.nc["n"][lone] == 1 and res.td["n"][lone] == 0.0 and res.choice["n"][lone] == 0.0
    assert res.integration["n"][lone] == pytest.approx(0.5)  # 1 / (0 + 2)
    assert res.choice_norm["n"][lone] == 0.0
    assert np.all(res.nc["n"][net.seg_component != net.seg_component[lone]] == 2)


# ================================================================ independent reference
@pytest.mark.parametrize("seed", [0, 1, 2])
@pytest.mark.parametrize("kind,turn", [("angular", 0.0), ("topological", 0.0), ("topological", 35.0),
                                       ("metric", 0.0)])
@pytest.mark.parametrize("radius", [None, 500.0])
def test_nc_td_and_choice_match_a_brute_force_networkx_reference(seed, kind, turn, radius):
    graph = random_street_graph(seed, n_points=26)
    net = rgn.build_segment_network(graph)
    res = rgn.analyse_network(net, kind=kind, radii=(radius,), with_choice=True,
                              topological_turn_deg=turn, max_exact_segments=10 ** 9)
    segs, _, nc, td, ch = reference_analysis(graph, net, kind, radius, turn)
    perm = aligned(net, graph, segs)
    key = rgn.radius_key(radius)
    assert np.array_equal(res.nc[key][perm], nc)
    assert np.allclose(res.td[key][perm], td, rtol=0, atol=1e-6)
    assert np.array_equal(res.choice[key][perm], ch)
    assert nc.max() > 5 and ch.sum() > 0  # the comparison is not vacuous


def test_metric_total_depth_equals_midpoint_distance_computed_on_the_node_graph():
    graph = random_street_graph(7, n_points=24)
    net, res = run(graph, kind="metric", radii=(None,), with_choice=False)
    order = sorted(graph.nodes, key=rgn._node_sort_key)
    simple = nx.Graph()
    simple.add_edges_from((u, v, {"length": d["length"]}) for u, v, d in graph.edges(data=True))
    node_dist = dict(nx.all_pairs_dijkstra_path_length(simple, weight="length"))
    ends = [(order[a], order[b], float(L)) for a, b, L in zip(net.seg_a, net.seg_b, net.seg_len)]
    expected = np.zeros(net.n_segments)
    for i, (ai, bi, li) in enumerate(ends):
        for j, (aj, bj, lj) in enumerate(ends):
            if i != j:
                expected[i] += min(node_dist[x][y] for x in (ai, bi) for y in (aj, bj)) + li / 2 + lj / 2
    assert np.allclose(res.td["n"], expected, rtol=0, atol=1e-6)


def test_subtree_sums_on_a_hand_made_forest():
    pred = np.array([-9999, 0, 0, 1, 1, 2, -9999])  # node 6 is unreached
    sums = rgn._subtree_sums(pred, np.ones(7))
    assert sums.tolist() == [6, 3, 2, 1, 1, 1, 1]
    chain_pred = np.concatenate([[-9999], np.arange(999)])  # a 1,000-deep path (pointer jumping)
    assert rgn._subtree_sums(chain_pred, np.ones(1000))[0] == 1000
    assert np.array_equal(rgn._subtree_sums(np.full(4, -9999), np.arange(4.0)), np.arange(4.0))


# ================================================================ sampling & plumbing
def test_pivot_sampling_is_flagged_deterministic_and_close_to_exact():
    net = rgn.build_segment_network(grid_graph(14))
    exact = rgn.analyse_network(net, radii=(None,), with_choice=True, max_exact_segments=10 ** 9)
    first = rgn.analyse_network(net, radii=(None,), with_choice=True, max_exact_segments=50, n_pivots=150)
    again = rgn.analyse_network(net, radii=(None,), with_choice=True, max_exact_segments=50, n_pivots=150)
    assert not exact.meta["approximate_global"]
    assert first.meta["approximate_global"] and first.meta["pivots"] == 150
    assert np.array_equal(first.integration["n"], again.integration["n"])
    assert np.array_equal(first.nc["n"], exact.nc["n"])  # NC is exact even when sampling
    assert np.corrcoef(first.integration["n"], exact.integration["n"])[0, 1] > 0.95
    assert np.corrcoef(first.choice_norm["n"], exact.choice_norm["n"])[0, 1] > 0.9
    assert np.median(np.abs(first.integration["n"] / exact.integration["n"] - 1)) < 0.08


def test_local_radii_ignore_the_sampling_threshold():
    net = rgn.build_segment_network(grid_graph(8))
    a = rgn.analyse_network(net, radii=(300.0,), with_choice=True, max_exact_segments=1)
    b = rgn.analyse_network(net, radii=(300.0,), with_choice=True, max_exact_segments=10 ** 9)
    assert not a.meta["approximate_global"]
    assert np.array_equal(a.choice["300"], b.choice["300"])


def test_progress_callback_reports_up_to_one():
    net = rgn.build_segment_network(grid_graph(8))
    seen = []
    rgn.analyse_network(net, radii=(300.0, None), with_choice=False, progress=lambda f, t: seen.append(f))
    assert seen and seen[-1] == 1.0 and seen == sorted(seen) and all(0.0 <= f <= 1.0 for f in seen)


def test_invalid_requests_raise_value_error(monkeypatch):
    net = rgn.build_segment_network(chain(3))
    with pytest.raises(ValueError):
        rgn.analyse_network(net, kind="euclid")
    with pytest.raises(ValueError):
        rgn.analyse_network(net, radii=())
    with pytest.raises(ValueError):
        rgn.analyse_network(net, radii=(-5.0,))
    with pytest.raises(ValueError):
        rgn.analyse_network(net, radii=(float("nan"),))
    monkeypatch.setitem(rgn.ANALYSIS_CONFIG, "max_segments", 2)
    with pytest.raises(ValueError):
        rgn.analyse_network(net)


def test_duplicate_radii_are_merged_and_ordered_with_global_last():
    net = rgn.build_segment_network(chain(4))
    res = rgn.analyse_network(net, radii=(None, 300.0, 300.0, 150.0), with_choice=False)
    assert res.radii == [150.0, 300.0, None]
    assert set(res.nc) == {"150", "300", "n"}


# ================================================================ gradient & scores
def test_gradient_runs_from_blue_to_red_and_marks_missing_values():
    for name, palette in rgn.PALETTES.items():
        low, high, nan = rgn.gradient_hex([0.0, 1.0, np.nan], name)
        assert (low, high) == (palette[0], palette[-1])
        assert nan == rgn.MISSING_COLOR
        r0, g0, b0 = rgn.gradient_rgb([0.0], name)[0]
        r1, g1, b1 = rgn.gradient_rgb([1.0], name)[0]
        assert b0 > r0 and r1 > b1  # blue-dominant low, red-dominant high
    rgb = rgn.gradient_rgb(np.linspace(0, 1, 101))
    assert rgb.min() >= 0.0 and rgb.max() <= 1.0
    # clipped, never extrapolated
    assert np.allclose(rgn.gradient_rgb([-3.0, 7.0]), rgn.gradient_rgb([0.0, 1.0]))


def test_spectrum_goes_blue_cyan_green_yellow_red():
    low, quarter, middle, high = rgn.gradient_rgb([0.0, 0.25, 0.5, 1.0])
    assert low.argmax() == 2 and high.argmax() == 0  # blue-dominant → red-dominant
    assert middle.argmax() == 1 and middle[1] > 0.85  # green in the middle
    assert quarter[1] > 0.6 and quarter[2] > 0.6 and quarter[0] < 0.2  # cyan between blue and green
    yellow = rgn.gradient_rgb([0.72])[0]
    assert yellow[0] > 0.9 and yellow[1] > 0.7 and yellow[2] < 0.2  # yellow/orange before red


def test_gradient_css_lists_every_stop():
    name = next(k for k in rgn.PALETTES if k.startswith("RdYlBu"))
    css = rgn.gradient_css(name)
    assert css.startswith("linear-gradient(90deg") and css.count("#") == len(rgn.PALETTES[name])


def test_linear_scale_maps_min_to_blue_end_and_max_to_red_end():
    values = np.array([2.0, 4.0, 3.0, np.nan, 100.0])
    mask = np.array([True, True, True, True, False])  # 100 is outside the display circle
    scaled = rgn.scale_scores(values, "linear", mask)
    assert scaled["vmin"] == 2.0 and scaled["vmax"] == 4.0
    assert scaled["t"][:3].tolist() == [0.0, 1.0, 0.5]
    assert np.isnan(scaled["t"][3]) and np.isnan(scaled["t"][4])
    assert scaled["score"][1] == 100.0
    assert [round(v, 6) for _, v in scaled["ticks"]] == [2.0, 2.5, 3.0, 3.5, 4.0]


def test_quantile_scale_gives_every_colour_band_the_same_number_of_segments():
    values = np.concatenate([np.linspace(0, 1, 90) ** 6, np.linspace(5, 6, 10)])  # very skewed
    scaled = rgn.scale_scores(values, "quantile")
    bands = np.histogram(scaled["t"], bins=5, range=(0, 1))[0]
    assert bands.max() - bands.min() <= 2
    assert scaled["t"].min() == 0.0 and scaled["t"].max() == 1.0
    lin = rgn.scale_scores(values, "linear")
    # linear piles the segments into one band — which is exactly why the quantile scale exists
    assert np.histogram(lin["t"], bins=5, range=(0, 1))[0].max() > 60


def test_constant_values_get_the_middle_colour_and_empty_input_does_not_crash():
    flat = rgn.scale_scores(np.full(5, 0.7), "linear")
    assert np.all(flat["t"] == 0.5)
    assert np.all(rgn.scale_scores(np.full(5, 0.7), "quantile")["t"] == 0.5)
    nothing = rgn.scale_scores(np.array([np.nan, np.nan]), "linear")
    assert np.isnan(nothing["t"]).all() and nothing["ticks"] == []
    with pytest.raises(ValueError):
        rgn.scale_scores([1.0, 2.0], "bogus")


def test_t_for_values_agrees_with_scale_scores():
    values = np.array([1.0, 2.0, 4.0, 8.0, 16.0])
    for mode in ("linear", "quantile"):
        scaled = rgn.scale_scores(values, mode)
        assert np.allclose(rgn.t_for_values(scaled, values), scaled["t"], atol=1e-12)
        assert rgn.t_for_values(scaled, [-1e9, 1e9]).tolist() == [0.0, 1.0]  # outside the data → clipped


# ================================================================ ranking & exports
def test_top_segments_are_ranked_by_score_and_kept_apart():
    net = rgn.build_segment_network(chain(10))
    score = np.arange(net.n_segments, dtype=float)  # last segment scores highest
    close = rgn.pick_top_segments(net, score, 3, min_spacing_m=0.0)
    assert close == [9, 8, 7]
    spread = rgn.pick_top_segments(net, score, 3, min_spacing_m=250.0)
    mids = net.seg_mid_xy[spread, 0]
    assert spread[0] == 9 and np.all(np.diff(np.sort(mids)) >= 250.0 - 1e-6)
    masked = rgn.pick_top_segments(net, score, 2, 0.0, mask=score < 5)
    assert masked == [4, 3]
    assert rgn.pick_top_segments(net, np.full(net.n_segments, np.nan), 3, 0.0) == []


def test_top_spacing_grows_with_the_extent_but_never_below_the_floor():
    small = rgn.build_segment_network(chain(4))
    big = rgn.build_segment_network(chain(400, seg_len=100.0))
    floor = rgn.ANALYSIS_CONFIG["top_min_spacing_m"]
    assert rgn.top_spacing_m(small, np.ones(small.n_segments, bool)) == floor
    assert rgn.top_spacing_m(big, np.ones(big.n_segments, bool)) == pytest.approx(0.04 * 39_900.0, rel=0.01)


def test_geojson_export_is_valid_lonlat_with_properties():
    g = chain(3)
    net, res = run(g, radii=(None,), with_choice=True)
    columns = {"score": np.array([1.0, np.nan, 3.0]), "color": np.array(["#ff0000", "#00ff00", "#0000ff"]),
               **rgn.result_columns(net, res)}
    fc = rgn.segments_geojson(net, columns, mask=np.array([True, True, False]))
    json.dumps(fc)  # strictly serialisable (no numpy, no NaN)
    assert len(fc["features"]) == 2
    f0 = fc["features"][0]
    lon, lat = f0["geometry"]["coordinates"][0]
    assert 100.3 < lon < 100.5 and 20.1 < lat < 20.3  # lon first, then lat
    assert f0["properties"]["segment"] == 0 and f0["properties"]["color"] == "#ff0000"
    assert fc["features"][1]["properties"]["score"] is None  # NaN → null
    assert "NAIN_n" in f0["properties"] and "NACH_n" in f0["properties"]


def test_segment_table_has_one_row_per_displayed_segment_and_every_index():
    g = chain(4)
    net = rgn.build_segment_network(g)
    res = rgn.analyse_network(net, radii=(150.0, None), with_choice=True)
    frame = rgn.segment_table(net, res, mask=np.array([True, True, False, False]))
    assert len(frame) == 2
    for column in ("NAIN_150", "NAIN_n", "NACH_150", "NACH_n", "NC_n", "TD_n", "CH_n", "length_m", "mid_lat",
                   "mid_lon"):
        assert column in frame.columns
    assert rgn.segment_table(net, res).shape[0] == net.n_segments
    no_choice = rgn.analyse_network(net, radii=(None,), with_choice=False)
    assert not any(c.startswith(("NACH", "CH_")) for c in rgn.segment_table(net, no_choice).columns)


def test_highway_summary_is_length_weighted():
    g = chain(4)
    for (u, v, d) in g.edges(data=True):
        d["highway"] = "primary" if min(u, v) < 2 else "residential"
    net = rgn.build_segment_network(g)
    score = np.array([10.0, 30.0, 50.0, 90.0])
    summary = rgn.highway_summary(net, score, score / 100.0, np.ones(4, bool))
    primary = summary.set_index("highway").loc["primary"]
    assert primary["segments"] == 2 and primary["mean_score"] == pytest.approx(20.0, abs=1e-6)
    assert summary.iloc[0]["highway"] == "residential"  # sorted by mean score, descending


# ================================================================ rendering
def _png_pixels(net, t, mask):
    from PIL import Image

    png = rgn.render_depthmap_png(net, t, mask, thick_by_score=False)
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    return np.asarray(Image.open(io.BytesIO(png)).convert("RGB")).astype(int)


def _red(img):
    return int(((img[..., 0] > 200) & (img[..., 1] < 60) & (img[..., 2] < 60)).sum())


def _blue(img):
    return int(((img[..., 2] > 200) & (img[..., 0] < 80)).sum())


def _corner_network():
    """A blue road along the bottom of the data and a red road up the right-hand side."""
    g = street_graph({"a": (0, 0), "b": (400, 0), "c": (400, 400)}, [("a", "b"), ("b", "c")])
    net = rgn.build_segment_network(g)
    t = np.zeros(net.n_segments)
    red_road = seg_of(net, g, "b", "c")
    t[red_road] = 1.0
    return net, t, red_road


def test_depthmap_png_is_black_with_blue_and_red_ends():
    net, t, _ = _corner_network()
    img = _png_pixels(net, t, np.ones(net.n_segments, bool))
    assert img.shape[1] == int(10.0 * 110)
    assert img[2, 2].tolist() == [0, 0, 0]  # black background
    map_area = img[: int(img.shape[0] * 0.92)]  # above the colour-bar strip
    assert _red(map_area) > 300 and _blue(map_area) > 300  # one red road, one blue road
    with pytest.raises(ValueError):
        rgn.render_depthmap_png(net, np.full(net.n_segments, np.nan), np.ones(net.n_segments, bool))


def test_depthmap_png_honours_the_mask():
    net, t, red_road = _corner_network()
    hidden = np.ones(net.n_segments, bool)
    hidden[red_road] = False
    img = _png_pixels(net, t, hidden)
    assert _red(img[: int(img.shape[0] * 0.92)]) == 0
    assert _blue(img[: int(img.shape[0] * 0.92)]) > 300


def test_depthmap_png_keeps_the_colour_bar_clear_of_the_roads():
    net, t, _ = _corner_network()
    img = _png_pixels(net, t, np.ones(net.n_segments, bool))
    height, width = img.shape[:2]
    lit = img.sum(axis=2) > 60
    bottom_road = lit[int(height * 0.88):int(height * 0.93)]  # the road along the bottom edge of the data
    assert bottom_road.any(axis=0).sum() > width * 0.5  # … spans the picture, just above the bar strip
    assert not lit[int(height * 0.93):, int(width * 0.32):].any()  # nothing but the legend below it


def test_folium_map_carries_the_gradient_colours_legend_and_study_circle():
    g = chain(3)
    net, res = run(g, radii=(None,), with_choice=False)
    mask = np.ones(net.n_segments, bool)
    scaled = rgn.scale_scores(res.integration["n"], "linear", mask)
    cols = rgn._display_columns(net, scaled, res.integration["n"], res.nc["n"], rgn.DEFAULT_PALETTE, True)
    fc = rgn.segments_geojson(net, cols, mask)
    legend = rgn.legend_html("Integration (NAIN)", rgn.DEFAULT_PALETTE, "ต่ำ 0.1", "0.9 สูง", "Linear")
    fmap = rgn.build_map(net, fc, basemap="พื้นดำ (เหมือน depthmap)", legend=legend,
                         study_circle=(LAT0, LON0, 500.0),
                         top=[{"rank": 1, "lat": LAT0, "lon": LON0, "score": 99.0, "label": "x"}],
                         anchor={"lat": LAT0, "lon": LON0, "source": "test"})
    html = fmap.get_root().render()
    assert "background:#000" in html and "linear-gradient(90deg" in html
    assert "Integration (NAIN)" in html and "ขอบเขตที่แสดงผล" in html
    assert cols["color"][0] in html or cols["color"][0].lower() in html.lower()


def test_street_names_from_osm_cannot_inject_html_into_the_map():
    payload = '<img src=x onerror="alert(1)"></script><script>alert(2)</script>'
    g = chain(2)
    for _, _, d in g.edges(data=True):
        d["name"] = payload
    net, res = run(g, radii=(None,), with_choice=False)
    mask = np.ones(net.n_segments, bool)
    scaled = rgn.scale_scores(res.integration["n"], "linear", mask)
    cols = rgn._display_columns(net, scaled, res.integration["n"], res.nc["n"], rgn.DEFAULT_PALETTE, True)
    assert payload in cols["label"][0]  # data stays exact for exports
    black = "พื้นดำ (เหมือน depthmap)"
    fmap = rgn.build_map(net, rgn.segments_geojson(net, cols, mask), basemap=black, legend="",
                         top=[{"rank": 1, "lat": LAT0, "lon": LON0, "score": 9.0, "label": payload}],
                         anchor={"lat": LAT0, "lon": LON0, "source": payload})
    html = fmap.get_root().render()
    assert "<img src=x" not in html and "<script>alert(2)" not in html and "</script><script>" not in html
    assert "&lt;img src=x" in html
    exported = json.loads(json.dumps(rgn.segments_geojson(net, cols, mask)))
    assert exported["features"][0]["properties"]["label"] == payload  # the export is not mangled


@pytest.mark.parametrize("style", list(rgn.MAP_STYLES))
def test_every_basemap_builds(style):
    net = rgn.build_segment_network(chain(2))
    scaled = rgn.scale_scores(np.array([1.0, 2.0]), "linear")
    values = np.array([1.0, 2.0])
    cols = rgn._display_columns(net, scaled, values, np.array([2, 2]), rgn.DEFAULT_PALETTE, False)
    fmap = rgn.build_map(net, rgn.segments_geojson(net, cols), basemap=style, legend="")
    assert fmap.get_root().render()


def test_no_basemap_needs_an_api_key():
    assert not any("cartocdn" in str(style) for style in rgn.MAP_STYLES.values())   # CARTO watermarks keyless tiles


def test_histogram_bars_wear_their_map_colours():
    scaled = rgn.scale_scores(np.linspace(0, 1, 200), "linear")
    fig = rgn.histogram_figure(scaled, rgn.DEFAULT_PALETTE, "NAIN")
    colours = list(fig.data[0].marker.color)
    assert colours[0] != colours[-1] and len(colours) == len(fig.data[0].x)
    assert colours[0].lower() == rgn.gradient_hex(rgn.t_for_values(scaled, [fig.data[0].x[0]]))[0]


# ================================================================ data access
def test_fetch_graph_falls_back_to_plain_osmnx_when_the_base_page_is_missing(monkeypatch):
    monkeypatch.setattr(rgn, "_base_page", lambda: None)
    calls = {}

    class FakeOx:
        @staticmethod
        def graph_from_point(point, dist, network_type, truncate_by_edge):
            calls.update(point=point, dist=dist, network_type=network_type)
            return chain(2)

    monkeypatch.setitem(sys.modules, "osmnx", FakeOx)
    graph, source, error = rgn.fetch_graph(LAT0, LON0, 2000.0, "drive")
    assert error is None and graph is not None and "osmnx" in source
    assert calls["dist"] == pytest.approx(2000.0 * (1 + rgn.STUDY_BUFFER_RATIO))
    assert calls["network_type"] == "drive"


def test_fetch_graph_reports_failures_instead_of_raising(monkeypatch):
    monkeypatch.setattr(rgn, "_base_page", lambda: None)

    class BrokenOx:
        @staticmethod
        def graph_from_point(*args, **kwargs):
            raise RuntimeError("no route to host")

    monkeypatch.setitem(sys.modules, "osmnx", BrokenOx)
    graph, source, error = rgn.fetch_graph(LAT0, LON0, 2000.0, "drive")
    assert graph is None and source == "" and "no route to host" in error


def test_fetch_graph_uses_the_base_loader_and_its_study_polygon(monkeypatch):
    class FakePolygon:
        wkt = "POLYGON((0 0, 1 0, 1 1, 0 0))"

    class FakeBase:
        seen = {}

        @staticmethod
        def anchor_study_polygon(lat, lon, radius):
            FakeBase.seen["polygon"] = (lat, lon, radius)
            return FakePolygon()

        @staticmethod
        def _fetch_osm_graph(wkt, network_type):
            FakeBase.seen["fetch"] = (wkt, network_type)
            graph = chain(2)
            graph.graph["osm_source"] = "cache"
            return graph, True, None

    monkeypatch.setattr(rgn, "_base_page", lambda: FakeBase)
    graph, source, error = rgn.fetch_graph(LAT0, LON0, 3000.0, "all")
    assert error is None and "cache" in source
    assert FakeBase.seen == {"polygon": (LAT0, LON0, 3000.0), "fetch": (FakePolygon.wkt, "all")}


def test_base_anchor_is_read_only_and_tolerates_missing_state(monkeypatch):
    monkeypatch.setattr(rgn.st, "session_state", {})
    assert rgn.base_anchor() is None
    state = {"rent_gradient_data": {"anchor": {"lat": "20.2", "lon": 100.4}}}
    monkeypatch.setattr(rgn.st, "session_state", state)
    assert rgn.base_anchor() == {"lat": 20.2, "lon": 100.4, "source": "CBD anchor"}
    monkeypatch.setattr(rgn.st, "session_state", {"rent_gradient_data": {"anchor": {"lat": None}}})
    assert rgn.base_anchor() is None


# ================================================================ real Chiang Khong data
@pytest.fixture(scope="module")
def bundled():
    if not BUNDLE.exists():
        pytest.skip("Geoapify_Map/osmnx_cache.zip is not available")
    graph, source, error = rgn.load_bundled_graph()
    assert error is None, error
    return graph, source


def test_bundled_graph_loads_through_the_allow_list_unpickler(bundled):
    graph, source = bundled
    assert len(graph) == 1648 and "เชียงของ" in source  # the larger of the two cached graphs


def test_bundled_graph_loader_needs_the_base_page_for_its_safe_unpickler(monkeypatch):
    monkeypatch.setattr(rgn, "_base_page", lambda: None)
    graph, source, error = rgn.load_bundled_graph()
    assert graph is None and source == "" and "Rent_Gradient.py" in error       # never falls back to plain pickle


def test_bundled_graph_loader_skips_oversized_entries(tmp_path, monkeypatch):
    import pickle
    import zipfile

    class FakeBase:
        MAX_CACHE_ENTRY_BYTES = 10
        loaded = []

        @staticmethod
        def _load_graph_bytes(data):
            FakeBase.loaded.append(len(data))
            return chain(2)

    archive = tmp_path / "osmnx_cache.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("osm_graph_big.pkl", pickle.dumps(list(range(100))))
    monkeypatch.setattr(rgn, "BUNDLED_CACHE_ZIP", archive)
    monkeypatch.setattr(rgn, "_base_page", lambda: FakeBase)
    graph, _, error = rgn.load_bundled_graph()
    assert graph is None and error and FakeBase.loaded == []  # never even read into memory


def test_bundled_graph_loader_rejects_a_hostile_pickle(tmp_path, monkeypatch):
    import pickle
    import zipfile

    class Evil:
        def __reduce__(self):
            return (exec, ("import sys; sys._rgn_new_pwned = True",))

    archive = tmp_path / "osmnx_cache.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("osm_graph_evil.pkl", pickle.dumps(Evil()))
    monkeypatch.setattr(rgn, "BUNDLED_CACHE_ZIP", archive)
    graph, _, error = rgn.load_bundled_graph()
    assert graph is None and error  # blocked global ⇒ no graph …
    assert not hasattr(sys, "_rgn_new_pwned")  # … and the payload never ran


def test_real_network_main_roads_are_more_accessible_than_cul_de_sacs(bundled):
    graph, _ = bundled
    net = rgn.build_segment_network(graph)
    assert 2000 < net.n_segments < 2400 and len(np.unique(net.seg_component)) == 1
    res = rgn.analyse_network(net, kind="angular", radii=(800.0, None), with_choice=True)
    assert not res.meta["approximate_global"]
    mask = np.ones(net.n_segments, bool)
    for key in ("800", "n"):
        for arr in (res.integration[key], res.choice_norm[key]):
            assert np.isfinite(arr).all() and arr.min() >= 0
    nain = res.integration["n"]
    scaled = rgn.scale_scores(nain, "linear", mask)
    summary = rgn.highway_summary(net, scaled["score"], nain, mask).set_index("highway")
    assert summary.loc["trunk", "mean_score"] > summary.loc["residential", "mean_score"]
    degree = np.bincount(np.concatenate([net.seg_a, net.seg_b]), minlength=net.n_nodes)
    dead_end = (degree[net.seg_a] == 1) | (degree[net.seg_b] == 1)
    assert nain[dead_end].mean() < nain[~dead_end].mean()  # spurs are harder to reach
    top = rgn.pick_top_segments(net, scaled["score"], 5, 1000.0)
    assert {net.seg_highway[s] for s in top} <= {"trunk", "secondary", "trunk_link", "tertiary", "primary"}
    assert np.corrcoef(res.integration["n"], res.integration["800"])[0, 1] < 0.99  # radii really matter


# ================================================================ Streamlit flow
def _app_with_network():
    graph = grid_graph(9)
    net = rgn.build_segment_network(graph)
    app = AppTest.from_file(str(PAGE), default_timeout=120)
    app.session_state["rgn_net"] = net
    app.session_state["rgn_meta"] = {"source": "test (synthetic)", "lat": LAT0, "lon": LON0, "radius_m": None,
                                     "network": "drive", "nodes": net.n_nodes, "edges": net.n_segments}
    app.session_state["rgn_autorun"] = True
    return app, net


def _widget(widgets, text):
    return next(w for w in widgets if text in w.label)


def test_cold_start_asks_for_the_network_first():
    app = AppTest.from_file(str(PAGE), default_timeout=120).run()
    assert not app.exception
    assert app.info and "โหลดโครงข่ายถนน" in app.info[0].value
    assert any("🧪" in b.label for b in app.sidebar.button)
    assert _widget(app.sidebar.button, "วิเคราะห์ Space Syntax").disabled


def test_a_session_left_on_a_removed_basemap_still_opens():
    app = AppTest.from_file(str(PAGE), default_timeout=120)
    app.session_state["rgn_basemap"] = "Dark (CARTO)"
    app.run()
    assert not app.exception
    assert app.selectbox(key="rgn_basemap").value == next(iter(rgn.MAP_STYLES))


def test_page_analyses_and_every_view_renders_without_errors():
    app, net = _app_with_network()
    app.run()
    assert not app.exception and not app.error
    assert {m.label for m in app.metric} >= {"Segment (แสดง / ทั้งหมด)", "เวลาคำนวณ"}
    assert _widget(app.metric, "Segment").value == f"{net.n_segments:,} / {net.n_segments:,}"
    for view in ("png", "stats", "help", "map"):
        _widget(app.radio, "มุมมอง").set_value(view).run()
        assert not app.exception, view
    _widget(app.radio, "มุมมอง").set_value("stats").run()
    table = app.dataframe[0].value
    assert list(table["อันดับ"])[:2] == [1, 2] and table["คะแนน"].iloc[0] >= table["คะแนน"].iloc[-1]
    assert any("CSV" in d.proto.label for d in app.get("download_button"))


def test_page_switches_measure_radius_scale_and_palette():
    app, _ = _app_with_network()
    app.run()
    assert _widget(app.radio, "ตัวชี้วัด").options[-1].startswith("Choice")
    _widget(app.radio, "ตัวชี้วัด").set_value("choice").run()
    assert not app.exception
    _widget(app.selectbox, "รัศมีที่แสดง").set_value("800").run()
    assert not app.exception
    _widget(app.radio, "สเกลสี").set_value("quantile").run()
    _widget(app.selectbox, "ชุดสี").select(next(k for k in rgn.PALETTES if k.startswith("RdYlBu"))).run()
    _widget(app.selectbox, "พื้นหลังแผนที่").select("Esri Light Gray").run()
    assert not app.exception and not app.error


def test_changing_settings_warns_until_the_analysis_is_rerun_and_errors_are_friendly():
    app, _ = _app_with_network()
    app.run()
    _widget(app.selectbox, "ระยะที่ใช้วัด").select("metric").run()
    assert any("ตั้งค่า Space Syntax เปลี่ยนไป" in w.value for w in app.warning)
    _widget(app.button, "วิเคราะห์ Space Syntax").click().run()
    assert not app.warning and not app.exception
    assert any("Metric" in c.value for c in app.caption)
    _widget(app.multiselect, "รัศมีวิเคราะห์").set_value([]).run()
    _widget(app.button, "วิเคราะห์ Space Syntax").click().run()
    assert any("เลือกรัศมีอย่างน้อย" in e.value for e in app.error) and not app.exception


def test_reordering_the_radii_is_not_a_settings_change():
    app, _ = _app_with_network()
    app.run()
    _widget(app.multiselect, "รัศมีวิเคราะห์").set_value(["Global (n)", "800 m"]).run()
    assert not any("เปลี่ยนไป" in w.value for w in app.warning)


def test_a_new_analysis_may_drop_the_measure_or_radius_that_was_on_screen():
    app, _ = _app_with_network()
    app.run()
    _widget(app.multiselect, "รัศมีวิเคราะห์").set_value(["400 m", "800 m", "1,600 m", "Global (n)"]).run()
    _widget(app.button, "วิเคราะห์ Space Syntax").click().run()
    _widget(app.radio, "ตัวชี้วัด").set_value("choice").run()
    _widget(app.selectbox, "รัศมีที่แสดง").set_value("1600").run()
    assert _widget(app.selectbox, "รัศมีที่แสดง").value == "1600" and not app.exception
    _widget(app.checkbox, "คำนวณ Choice").uncheck().run()
    _widget(app.multiselect, "รัศมีวิเคราะห์").set_value(["800 m"]).run()
    _widget(app.button, "วิเคราะห์ Space Syntax").click().run()
    assert not app.exception and not app.error
    assert _widget(app.radio, "ตัวชี้วัด").value == "integration"
    assert _widget(app.selectbox, "รัศมีที่แสดง").value == "800"


def test_choice_can_be_switched_off():
    app, _ = _app_with_network()
    app.run()
    _widget(app.checkbox, "คำนวณ Choice").uncheck().run()
    _widget(app.button, "วิเคราะห์ Space Syntax").click().run()
    assert not app.exception
    assert _widget(app.radio, "ตัวชี้วัด").options == ["Integration (NAIN) — เข้าถึงได้ง่าย"]


def test_demo_button_loads_the_bundled_chiang_khong_graph_and_runs():
    if not BUNDLE.exists():
        pytest.skip("Geoapify_Map/osmnx_cache.zip is not available")
    app = AppTest.from_file(str(PAGE), default_timeout=240).run()
    _widget(app.sidebar.button, "ตัวอย่างเชียงของ").click().run()
    assert not app.exception and not app.error
    assert _widget(app.metric, "Segment").value == "2,172 / 2,172"
    assert any("ตัวอย่างเชียงของ" in c.value for c in app.caption)
