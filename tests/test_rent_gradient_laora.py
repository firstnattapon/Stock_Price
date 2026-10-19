"""Offline checks of rent_gradient_laora.core on small hand-made street graphs.

Distances are verified against values worked out by hand on a 100 m grid, the fit against
exact exponentials and a brute-force leave-one-out, and the unreachable / degenerate cases
against their documented behaviour. No network access, osmnx or streamlit needed.
"""
import sys
from math import cos, exp, log, radians, sqrt
from pathlib import Path

import networkx as nx
import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from rent_gradient_laora import core  # noqa: E402

LAT0, LON0 = 20.2, 100.4
STEP = 100.0  # metres between grid nodes


def ll(x_m: float, y_m: float):
    """(lon, lat) of a point x_m east / y_m north of the origin."""
    return (LON0 + x_m / (core.M_PER_DEG_LON_EQ * cos(radians(LAT0))),
            LAT0 + y_m / core.M_PER_DEG_LAT)


def pt(x_m: float, y_m: float):
    """(lat, lon) as the public API takes it."""
    lon, lat = ll(x_m, y_m)
    return (lat, lon)


def add_node(g, key, x_m, y_m):
    lon, lat = ll(x_m, y_m)
    g.add_node(key, x=lon, y=lat)


def add_road(g, u, v, length=STEP, **attrs):
    g.add_edge(u, v, length=length, **attrs)
    g.add_edge(v, u, length=length, **attrs)


def grid(n=5, **attrs):
    g = nx.MultiDiGraph()
    for i in range(n):
        for j in range(n):
            add_node(g, (i, j), i * STEP, j * STEP)
    for i in range(n):
        for j in range(n):
            if i + 1 < n:
                add_road(g, (i, j), (i + 1, j), **attrs)
            if j + 1 < n:
                add_road(g, (i, j), (i, j + 1), **attrs)
    return g


def two_streets():
    """Street A (y=0, anchor) and street B (y=100 m) joined only at x=400 m."""
    g = nx.MultiDiGraph()
    for i in range(5):
        add_node(g, ("A", i), i * STEP, 0)
        add_node(g, ("B", i), i * STEP, STEP)
    for i in range(4):
        add_road(g, ("A", i), ("A", i + 1))
        add_road(g, ("B", i), ("B", i + 1))
    add_road(g, ("A", 4), ("B", 4))
    return g


def one(res, kind):
    return float(res["distances"][kind][0])


# ------------------------------------------------------------------ distances
def test_single_point_anchor_on_grid():
    net = core.build_network(grid())
    anchor = core.anchor_from_points(net, [pt(0, 0)])
    mid = pt(250, 200)  # middle of the segment (2,2)-(3,2)
    res = core.distances_to_anchor(net, anchor, [mid])
    assert one(res, "metric") == pytest.approx(0.450, rel=1e-3)    # 400 m + half a segment
    assert one(res, "euclid") == pytest.approx(sqrt(250 ** 2 + 200 ** 2) / 1000, rel=1e-3)
    assert one(res, "topological") == 4.0                          # five segments, four steps
    assert one(res, "angular") == pytest.approx(1.0)               # one 90 degree turn
    assert res["units"] == core.DISTANCE_UNITS


def test_topological_turn_threshold_merges_straight_continuations():
    net = core.build_network(grid())
    anchor = core.anchor_from_points(net, [pt(0, 0)])
    res = core.distances_to_anchor(net, anchor, [pt(250, 200)], topological_turn_deg=30.0)
    assert one(res, "topological") == 1.0     # straight on, one real turn


def test_main_street_anchor_measures_to_nearest_point_of_the_street():
    net = core.build_network(grid())
    anchor = core.anchor_from_points(net, [pt(i * STEP, 0) for i in range(5)])
    res = core.distances_to_anchor(net, anchor, [pt(250, 300), pt(150, 0)])
    assert res["distances"]["metric"][0] == pytest.approx(0.350, rel=1e-3)
    assert res["distances"]["euclid"][0] == pytest.approx(0.300, rel=1e-3)
    assert res["distances"]["metric"][1] == pytest.approx(0.0, abs=1e-6)     # on the street
    assert res["distances"]["euclid"][1] == pytest.approx(0.0, abs=1e-6)
    assert res["distances"]["topological"][1] == 0.0


def test_metric_follows_the_roads_not_the_crow():
    net = core.build_network(two_streets())
    anchor = core.anchor_from_points(net, [pt(i * STEP, 0) for i in range(5)])
    res = core.distances_to_anchor(net, anchor, [pt(50, STEP)])    # on B, far end from the link
    assert one(res, "euclid") == pytest.approx(0.100, rel=1e-3)
    assert one(res, "metric") == pytest.approx(0.450, rel=1e-3)    # 100 + 300 + 50 round the link


def test_off_network_offset_is_added_to_metric_only_when_asked():
    net = core.build_network(grid())
    anchor = core.anchor_from_points(net, [pt(0, 0)])
    p = [pt(250, 230)]                    # 30 m north of the segment (2,2)-(3,2)
    with_off = core.distances_to_anchor(net, anchor, p, include_offset=True)
    without = core.distances_to_anchor(net, anchor, p, include_offset=False)
    assert with_off["snap_offset_m"][0] == pytest.approx(30.0, rel=1e-2)
    assert one(with_off, "metric") - one(without, "metric") == pytest.approx(0.030, rel=2e-2)
    assert one(with_off, "euclid") == one(without, "euclid")


def test_angular_cost_of_a_u_turn_is_two_and_straight_is_zero():
    g = nx.MultiDiGraph()
    for key, xy in {0: (0, 0), 1: (100, 0), 2: (200, 0), 3: (0, 1)}.items():
        add_node(g, key, *xy)
    add_road(g, 0, 1)
    add_road(g, 1, 2)
    add_road(g, 1, 3, length=100.0)      # leaves node 1 almost back along road 0-1
    net = core.build_network(g)
    assert net.lg_deflection_deg.min() == pytest.approx(0.0, abs=1e-6)     # 0-1-2 is straight
    assert net.lg_deflection_deg.max() > 179.0
    anchor = core.anchor_from_points(net, [pt(0, 0)])
    res = core.distances_to_anchor(net, anchor, [pt(150, 0), pt(50, 0.5)], kinds=["angular"])
    assert res["distances"]["angular"][0] == pytest.approx(0.0, abs=1e-6)  # straight on
    assert res["distances"]["angular"][1] == pytest.approx(2.0, abs=0.02)  # doubling back


def test_edge_geometry_sets_the_direction_even_when_stored_reversed():
    class Geo:
        def __init__(self, coords):
            self.coords = coords

    g = nx.MultiDiGraph()
    add_node(g, 0, 0, 0)
    add_node(g, 1, 100, 0)
    # geometry runs 1 -> bend (60, 40) -> 0, i.e. b -> a
    g.add_edge(0, 1, length=120.0, geometry=Geo([ll(100, 0), ll(60, 40), ll(0, 0)]))
    net = core.build_network(g)
    ua, ub = net.seg_dir_a[0], net.seg_dir_b[0]
    assert ua == pytest.approx(np.array([60, 40]) / np.hypot(60, 40), abs=2e-3)
    assert ub == pytest.approx(np.array([-40, 40]) / np.hypot(40, 40), abs=2e-3)


def test_unreachable_points_are_nan_and_dropped_from_every_kind():
    g = grid(3)
    add_node(g, "far1", 5000, 5000)
    add_node(g, "far2", 5100, 5000)
    add_road(g, "far1", "far2")
    net = core.build_network(g)
    anchor = core.anchor_from_points(net, [pt(0, 0)])
    res = core.distances_to_anchor(net, anchor, [pt(150, 0), pt(5050, 5000)])
    assert np.isfinite(res["distances"]["metric"][0]) and np.isnan(res["distances"]["metric"][1])
    samples = [{"lat": pt(x, 0)[0], "lon": pt(x, 0)[1], "rent": 100 * exp(-x / 1000)}
               for x in (50, 150, 250)]
    samples.append({"lat": pt(5050, 5000)[0], "lon": pt(5050, 5000)[1], "rent": 10})
    out = core.compare_distance_models(samples, net, anchor)
    assert out["n_input"] == 4 and out["n_used"] == 3
    assert any("ตัดตัวอย่างออก 1" in w for w in out["warnings"])


def test_street_names_become_an_anchor():
    g = grid(4)
    for i in range(3):
        for u, v in (((i, 1), (i + 1, 1)),):
            for a, b in ((u, v), (v, u)):
                for key in g[a][b]:
                    g[a][b][key]["name"] = "Main Street"
    net = core.build_network(g)
    listed = core.list_street_names(net)
    assert listed == [("Main Street", pytest.approx(300.0))]       # 3 segments, counted once
    anchor = core.anchor_from_street_names(net, ["Main Street"])
    assert len(anchor.seg_idx) == 3 and len(anchor.node_idx) == 4
    with pytest.raises(ValueError):
        core.anchor_from_street_names(net, ["Nowhere Road"])


def test_anchor_and_graph_validation():
    with pytest.raises(ValueError):
        core.build_network(nx.MultiDiGraph())
    net = core.build_network(grid(3))
    with pytest.raises(ValueError):
        core.anchor_from_points(net, [])
    with pytest.raises(ValueError):
        core.distances_to_anchor(net, core.anchor_from_points(net, [pt(0, 0)]), [pt(50, 0)],
                                 kinds=["teleport"])


# --------------------------------------------------------------------- fitting
def test_fit_recovers_an_exact_exponential():
    d = np.array([0.1, 0.4, 0.9, 1.5, 2.2])
    rent = 800.0 * np.exp(-0.9 * d)
    fit = core.fit_log_linear(d, rent)
    assert fit["lam"] == pytest.approx(0.9) and fit["r0"] == pytest.approx(800.0)
    assert fit["r2"] == pytest.approx(1.0) and fit["rmse_log"] == pytest.approx(0.0, abs=1e-9)
    assert fit["loo_rmse"] == pytest.approx(0.0, abs=1e-6)


def test_loo_rmse_matches_brute_force_leave_one_out():
    rng = np.random.default_rng(7)
    d = np.sort(rng.uniform(0.1, 3.0, 12))
    rent = 500.0 * np.exp(-0.7 * d + rng.normal(0, 0.15, 12))
    errors = []
    for i in range(len(d)):
        keep = np.arange(len(d)) != i
        sub = core.fit_log_linear(d[keep], rent[keep])
        errors.append(log(rent[i]) - log(sub["r0"] * exp(-sub["lam"] * d[i])))
    brute = sqrt(np.mean(np.square(errors)))
    assert core.fit_log_linear(d, rent)["loo_rmse"] == pytest.approx(brute, rel=1e-6)


def test_fit_small_or_degenerate_samples():
    assert core.fit_log_linear([1.0, 1.0, 1.0], [10, 20, 30]) is None       # no variation
    assert core.fit_log_linear([1.0], [10]) is None
    two = core.fit_log_linear([0.0, 1.0], [100, 50])
    assert two["r2"] == pytest.approx(1.0) and two["dof"] == 0
    assert two["loo_rmse"] is None and two["adj_r2"] is None and two["lam_ci95"] is None


def test_ranking_prefers_the_distance_that_generated_the_rents():
    net = core.build_network(two_streets())
    anchor = core.anchor_from_points(net, [pt(i * STEP, 0) for i in range(5)])
    xs = [50, 150, 250, 350]
    places = [pt(x, STEP) for x in xs] + [pt(x, 0) for x in (50, 250)]
    probe = core.distances_to_anchor(net, anchor, places, kinds=["metric"])["distances"]["metric"]
    lam = 1.4
    samples = [{"lat": p[0], "lon": p[1], "rent": 900.0 * exp(-lam * m)}
               for p, m in zip(places, probe)]
    out = core.compare_distance_models(samples, net, anchor)
    assert out["n_used"] == len(places) and out["criterion"] == "loo_rmse"
    assert out["ranking"][0] == "metric"
    assert out["models"]["metric"]["lam"] == pytest.approx(lam, rel=1e-6)
    assert out["models"]["metric"]["r2"] > 0.999999
    assert out["models"]["euclid"]["r2"] < out["models"]["metric"]["r2"]
    assert out["models"]["metric"]["unit"] == "km"
    assert len(out["points"]) == len(places)


def test_compare_with_no_usable_samples_or_too_few():
    net = core.build_network(grid(3))
    anchor = core.anchor_from_points(net, [pt(0, 0)])
    empty = core.compare_distance_models([{"lat": 1, "lon": 2, "rent": -5}, {"foo": 1}], net, anchor)
    assert empty["n_used"] == 0 and empty["ranking"] == [] and empty["warnings"]
    few = core.compare_distance_models(
        [{"lat": pt(50, 0)[0], "lon": pt(50, 0)[1], "rent": 90},
         {"lat": pt(150, 100)[0], "lon": pt(150, 100)[1], "rent": 70}], net, anchor)
    assert few["criterion"] == "r2"
    assert any("น้อยกว่า 3" in w for w in few["warnings"])


def test_binned_profile_groups_by_distance():
    rows = core.binned_profile([0.1, 0.4, 0.6, 1.2, float("nan")], [10, 20, 30, 40, 50], 0.5)
    assert [(r["from"], r["n"], r["mean_rent"]) for r in rows] == [
        (0.0, 2, 15.0), (0.5, 1, 30.0), (1.0, 1, 40.0)]
    assert core.binned_profile([], [], 0.5) == []
    with pytest.raises(ValueError):
        core.binned_profile([1.0], [1.0], 0)
