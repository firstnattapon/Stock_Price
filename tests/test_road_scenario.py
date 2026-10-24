"""Road scenario (🛣️ ถนนตัดใหม่): join new roads into the segment network, re-analyse, compare before → after.

Checked four ways:
  1. the joined network is the network OSM would give: a road between two existing junctions analyses exactly like
     building the whole street graph (with that road) from scratch,
  2. hand-made cases: a road ending mid-block splits that segment, an end near a junction reuses it, a crossing is
     a 4-way junction unless it is a bridge, a road that touches nothing changes no existing score at all,
  3. the comparison helpers (length-weighted pieces, Δ %, colours, the "missing link" suggestion, text input),
  4. the page itself (AppTest, offline): analyse → suggest → simulate → view + map layer + legend → clear.
Nothing here touches the network: Overpass is never called.
"""
import importlib.util
import sys
from pathlib import Path

import numpy as np
import pytest

nx = pytest.importorskip("networkx")
pytest.importorskip("scipy")
pytest.importorskip("streamlit")
pytest.importorskip("folium")

import test_rent_gradient_new as helpers  # noqa: E402  (street-network builders)

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "pages" / "Rent_Gradient.py"
NAME = "rent_gradient_road_scenario_under_test"


def _load():
    spec = importlib.util.spec_from_file_location(NAME, PAGE)
    module = importlib.util.module_from_spec(spec)
    sys.modules[NAME] = module
    spec.loader.exec_module(module)
    return module


rg = _load()


def latlon(x, y):
    lon, lat = helpers.lonlat(x, y)
    return lat, lon


def road(*points, name="ถนนใหม่"):
    return {"name": name, "points": [latlon(x, y) for x, y in points]}


def comb():
    """A spine (0–4) with a dead-end tooth up from every node; the tooth tips are 100 m apart."""
    nodes = {i: (i * 100.0, 0.0) for i in range(5)}
    nodes.update({10 + i: (i * 100.0, 120.0) for i in range(5)})
    edges = [(i, i + 1) for i in range(4)] + [(i, 10 + i) for i in range(5)]
    return helpers.street_graph(nodes, edges)


def analyse(net, **kwargs):
    kwargs.setdefault("radii", (None,))
    kwargs.setdefault("with_choice", True)
    return rg.analyse_network(net, **kwargs)


def everything(net):
    return np.ones(net.n_segments, dtype=bool)


def seg_at(net, x, y):
    """Segment whose midpoint is nearest to the test-plane point ``(x, y)``."""
    lat, lon = latlon(x, y)
    return int(np.argmin(np.hypot(net.seg_mid_lonlat[:, 0] - lon, net.seg_mid_lonlat[:, 1] - lat)))


# ----------------------------------------------------------------------------- 1. same as building it from OSM
@pytest.mark.parametrize("kind", ["angular", "topological", "metric"])
def test_a_road_between_two_junctions_analyses_exactly_like_the_street_graph_that_has_it(kind):
    full = helpers.grid_graph(5, seed=3)
    missing = [((1, 1), (2, 1)), ((2, 2), (2, 3))]
    without = full.copy()
    for a, b in missing:
        without.remove_edges_from([(a, b), (b, a)])
    base = rg.build_segment_network(without)
    roads = [{"name": f"link {i}", "points": [(without.nodes[n]["y"], without.nodes[n]["x"]) for n in pair]}
             for i, pair in enumerate(missing)]
    scenario = rg.add_new_roads(base, roads, snap_m=5)
    assert all(r["joins"] == 2 and r["free_ends"] == 0 for r in scenario.roads)
    assert scenario.net.n_nodes == base.n_nodes                         # both ends reused existing junctions
    assert scenario.net.n_segments == base.n_segments + 2 and scenario.is_new.sum() == 2

    reference = rg.build_segment_network(full)
    assert np.allclose(reference.node_xy, scenario.net.node_xy)       # same nodes, same local plane
    ref_index = {tuple(sorted(p)): s for s, p in enumerate(zip(reference.seg_a, reference.seg_b))}
    order = np.array([ref_index[tuple(sorted(p))] for p in zip(scenario.net.seg_a, scenario.net.seg_b)])
    mine = analyse(scenario.net, kind=kind, radii=(300.0, None))
    theirs = analyse(reference, kind=kind, radii=(300.0, None))
    for key in ("300", "n"):
        assert np.array_equal(mine.nc[key], theirs.nc[key][order])
        # metric depth uses the OSM length (drawn in the test's own plane) vs the road's length on the page's plane
        rtol = 1e-4 if kind == "metric" else 1e-9
        assert np.allclose(mine.td[key], theirs.td[key][order], rtol=rtol)
        assert np.allclose(mine.choice[key], theirs.choice[key][order], rtol=rtol)
        assert np.allclose(mine.integration[key], theirs.integration[key][order], rtol=rtol)


def test_untouched_segments_keep_every_array_and_come_first():
    net = rg.build_segment_network(comb())
    scenario = rg.add_new_roads(net, [road((100, 120), (300, 120))])
    n = net.n_segments
    assert np.array_equal(scenario.parent[:n], np.arange(n))           # nothing split: every old segment as it was
    for name in ("seg_a", "seg_b", "seg_len", "seg_bend_deg", "seg_dir_a", "seg_dir_b", "seg_mid_xy"):
        assert np.array_equal(getattr(scenario.net, name)[:n], getattr(net, name)), name
    assert scenario.net.seg_name[n:] == ["ถนนใหม่"] * (scenario.net.n_segments - n)
    assert set(scenario.net.seg_highway[n:]) == {rg.ROAD_SCENARIO_CONFIG["highway"]}


# ----------------------------------------------------------------------------- 2. joining, splitting, crossing
def long_street():
    return helpers.street_graph({0: (0.0, 0.0), 1: (200.0, 0.0)}, [(0, 1)])


def test_an_end_that_lands_mid_block_splits_the_segment_and_its_pieces_keep_the_length():
    net = rg.build_segment_network(long_street())
    scenario = rg.add_new_roads(net, [road((100, 4), (100, 150))], snap_m=10)
    old = np.flatnonzero(scenario.parent == 0)
    assert len(old) == 2 and scenario.net.seg_len[old].sum() == pytest.approx(net.seg_len[0])
    assert scenario.roads[0]["joins"] == 1 and scenario.roads[0]["free_ends"] == 1
    lon, lat = scenario.junctions[0]
    assert (lat, lon) == pytest.approx(latlon(100, 0), abs=1e-7)        # the road was pulled onto the street
    assert scenario.net.n_nodes == net.n_nodes + 2                      # the new junction + the dead end
    # a T: going straight along the old street costs nothing, turning into the new road costs a right angle
    result = analyse(scenario.net, radii=(None,))
    new = np.flatnonzero(scenario.is_new)[0]
    assert result.td["n"][new] == pytest.approx(2.0, abs=1e-6)


def test_an_end_within_join_distance_of_a_junction_uses_that_junction():
    net = rg.build_segment_network(long_street())
    scenario = rg.add_new_roads(net, [road((194, 3), (194, 150))], snap_m=10)   # 6 m from node 1
    assert scenario.net.n_segments == 2 and scenario.parent.tolist() == [0, -1]
    assert scenario.net.n_nodes == net.n_nodes + 1                      # only the dead end is new
    assert scenario.road.tolist() == [-1, 0]


def test_an_end_beyond_the_snap_distance_stays_a_dead_end():
    net = rg.build_segment_network(long_street())
    scenario = rg.add_new_roads(net, [road((100, 40), (100, 150))], snap_m=30)
    assert scenario.roads[0]["joins"] == 0 and scenario.roads[0]["free_ends"] == 2
    assert len(scenario.junctions) == 0 and scenario.net.seg_component[-1] != scenario.net.seg_component[0]


def test_a_crossing_is_a_four_way_junction_unless_the_road_is_a_bridge():
    net = rg.build_segment_network(long_street())
    crossing = rg.add_new_roads(net, [road((80, -100), (80, 100))], snap_m=5)
    assert crossing.roads[0]["crossings"] == 1 and crossing.net.n_segments == 4
    assert sorted(crossing.parent.tolist()) == [-1, -1, 0, 0] and len(crossing.junctions) == 1
    assert len(np.unique(crossing.net.seg_component)) == 1
    bridge = rg.add_new_roads(net, [road((80, -100), (80, 100))], snap_m=5, connect_crossings=False)
    assert bridge.roads[0]["crossings"] == 0 and bridge.net.n_segments == 2
    assert len(np.unique(bridge.net.seg_component)) == 2


def test_a_road_through_an_existing_junction_joins_it_once():
    net = rg.build_segment_network(helpers.chain(3))                     # nodes at x = 0, 100, 200, 300
    scenario = rg.add_new_roads(net, [road((100, -80), (100, 80))], snap_m=5)
    assert scenario.roads[0]["crossings"] == 1 and len(scenario.junctions) == 1
    assert scenario.net.n_segments == net.n_segments + 2               # no old segment split, two new pieces
    assert (scenario.parent >= 0).sum() == net.n_segments


def test_a_later_road_can_join_an_earlier_new_road():
    net = rg.build_segment_network(long_street())
    scenario = rg.add_new_roads(net, [road((50, 0), (50, 150), name="A"), road((50, 75), (180, 75), name="B")],
                                snap_m=5)
    assert scenario.roads[1]["joins"] == 1                               # B's west end lands on A
    assert sum(1 for r in scenario.road if r == 0) == 2                  # … which splits A in two
    assert len(np.unique(scenario.net.seg_component)) == 1


def test_a_road_that_touches_nothing_changes_no_existing_score_at_all():
    net = rg.build_segment_network(comb())
    base = analyse(net, radii=(150.0, None))
    scenario = rg.add_new_roads(net, [road((0, 1000), (200, 1000))])
    after = analyse(scenario.net, radii=(150.0, None))
    mask, after_mask = everything(net), everything(scenario.net)
    for measure in ("integration", "choice"):
        for rkey in ("150", "n"):
            c = rg.compare_scenario(net, base, mask, scenario, after, after_mask, measure, rkey)
            assert np.array_equal(c["after"], c["before"]) and np.all(np.nan_to_num(c["pct"]) == 0.0)
            assert np.isfinite(c["new_value"])


def test_linking_dead_ends_makes_them_more_integrated_and_gives_the_link_through_movement():
    net = rg.build_segment_network(comb())
    base = analyse(net)
    scenario = rg.add_new_roads(net, [road((100, 120), (300, 120))])
    assert scenario.roads[0]["crossings"] == 1                           # it also passes the middle tooth's tip
    after = analyse(scenario.net)
    c = rg.compare_scenario(net, base, everything(net), scenario, after, everything(scenario.net),
                            "integration", "n")
    joined = [seg_at(net, x, 60) for x in (100, 200, 300)]               # the three teeth the link ties together
    assert len(set(joined)) == 3 and np.all(c["pct"][joined] > 5)
    choice = rg.compare_scenario(net, base, everything(net), scenario, after, everything(scenario.net),
                                 "choice", "n")
    assert np.all(after.choice["n"][scenario.is_new] > 0) and choice["new_rank"] > 0


# ----------------------------------------------------------------------------- 3. helpers
def test_split_pieces_are_folded_back_by_length():
    net = rg.build_segment_network(long_street())
    scenario = rg.add_new_roads(net, [road((50, 0), (50, 100))], snap_m=5)      # pieces of 50 m and 150 m
    values = np.zeros(scenario.net.n_segments)
    pieces = np.flatnonzero(scenario.parent == 0)
    lengths = scenario.net.seg_len[pieces]
    values[pieces] = [1.0, 3.0]
    expected = (lengths * [1.0, 3.0]).sum() / lengths.sum()
    assert rg.scenario_values(scenario, values)[0] == pytest.approx(expected)
    values[pieces[0]] = np.nan                                           # a missing piece is skipped, not zero
    assert rg.scenario_values(scenario, values)[0] == pytest.approx(3.0)


def test_delta_colours_run_blue_gray_red_and_clip():
    stops = rg.DELTA_STOPS
    assert rg.delta_hex([-50, -10, 0, 10, 50, np.nan], 10) == [stops[0], stops[0], stops[3], stops[-1], stops[-1],
                                                              stops[3]]
    assert rg.delta_limit(np.array([0.1, 0.2, np.nan]), np.ones(3, bool)) == 2 * rg.ROAD_SCENARIO_CONFIG["change_pct"]
    assert rg.delta_limit(np.linspace(0, 100, 101), np.ones(101, bool)) == pytest.approx(95.0)


def test_the_total_is_the_existing_roads_plus_the_new_roads():
    net = rg.build_segment_network(comb())
    base = analyse(net)
    scenario = rg.add_new_roads(net, [road((100, 120), (300, 120))])
    after = analyse(scenario.net)
    mask = everything(net)
    c = rg.compare_scenario(net, base, mask, scenario, after, everything(scenario.net), "integration", "n")
    totals = c["totals"]
    km = net.seg_len / 1000.0
    assert totals["before"] == pytest.approx((c["before"] * km).sum())
    assert totals["old_after"] == pytest.approx((c["after"] * km).sum())
    new = scenario.is_new
    assert totals["new"] == pytest.approx((after.integration["n"][new] * scenario.net.seg_len[new] / 1000).sum())
    assert totals["new"] > 0 and totals["after"] == pytest.approx(totals["old_after"] + totals["new"])
    assert totals["km_new"] == pytest.approx(0.2, rel=1e-3) and totals["km_old"] == pytest.approx(km.sum())
    assert totals["mean_after"] == pytest.approx(totals["after"] / (totals["km_old"] + totals["km_new"]))
    assert totals["change_pct"] == pytest.approx(100 * (totals["after"] / totals["before"] - 1))
    # split pieces are counted once, by their own length: Σ over the scenario's existing pieces is the same total
    pieces = ~new
    assert totals["old_after"] == pytest.approx(
        (after.integration["n"][pieces] * scenario.net.seg_len[pieces] / 1000).sum())


def test_a_road_that_touches_nothing_only_adds_its_own_score_to_the_total():
    net = rg.build_segment_network(comb())
    base = analyse(net)
    scenario = rg.add_new_roads(net, [road((0, 1000), (200, 1000))])
    after = analyse(scenario.net)
    totals = rg.compare_scenario(net, base, everything(net), scenario, after, everything(scenario.net),
                                 "integration", "n")["totals"]
    assert totals["old_after"] == totals["before"] and totals["old_change_pct"] == 0.0
    assert totals["after"] == pytest.approx(totals["before"] + totals["new"]) and totals["change_pct"] > 0


def test_scenario_summary_has_a_row_per_measure_and_radius():
    net = rg.build_segment_network(comb())
    base = analyse(net, radii=(150.0, None))
    scenario = rg.add_new_roads(net, [road((100, 120), (300, 120))])
    after = analyse(scenario.net, radii=(150.0, None))
    table = rg.scenario_summary(net, base, everything(net), scenario, after, everything(scenario.net))
    assert list(zip(table["measure"], table["radius"])) == [
        ("integration", "150"), ("integration", "n"), ("choice", "150"), ("choice", "n")]
    assert (table["segments"] == net.n_segments).all() and table["new_value"].notna().all()
    assert np.allclose(table["total_after"], table["total_old_after"] + table["total_new"])
    integration = table[table["measure"] == "integration"]                 # NACH may be 0 everywhere locally
    assert (table["total_new"] >= 0).all() and (integration["total_new"] > 0).all()
    assert integration["network_change_pct"].notna().all()
    assert (table.loc[table["measure"] == "integration", "up"] > 0).all()   # the linked teeth


def test_the_suggested_shortcut_is_the_biggest_detour_and_a_straight_street_has_none():
    net = rg.build_segment_network(comb())
    found = rg.suggest_shortcut(net, everything(net))
    assert found is not None and found["detour"] == pytest.approx(320.0 / 200.0, rel=1e-3)
    assert found["straight_m"] == pytest.approx(200.0, rel=1e-3)
    assert rg.suggest_shortcut(rg.build_segment_network(helpers.chain(8)), np.ones(8, bool)) is None


def test_typed_roads_are_split_by_blank_lines_and_names():
    text = "# ถนน A\n20.2, 100.4\n20.21, 100.41\n\n20.3, 100.5\n20.31, 100.51\n# B\n\n20.4, 100.6\n20.41, 100.6\n"
    roads = rg.parse_new_roads(text)
    assert [r["name"] for r in roads] == ["ถนน A", "ถนนใหม่ 2", "B"]
    assert roads[0]["points"] == [(20.2, 100.4), (20.21, 100.41)]
    with pytest.raises(ValueError, match="บรรทัด 3"):
        rg.parse_new_roads("20.2, 100.4\n20.2, 100.41\nnot a point")
    with pytest.raises(ValueError, match="อย่างน้อย 2 จุด: เดี่ยว"):
        rg.parse_new_roads("# เดี่ยว\n20.2, 100.4")
    with pytest.raises(ValueError, match="ยังไม่มีแนวถนนใหม่"):
        rg.parse_new_roads("  \n# only a name\n")


def test_input_that_cannot_make_a_road_is_a_value_error():
    net = rg.build_segment_network(long_street())
    with pytest.raises(ValueError):
        rg.add_new_roads(net, [])
    with pytest.raises(ValueError, match="ไม่เกิน"):
        rg.add_new_roads(net, [road((0, 50), (10, 50))] * (rg.ROAD_SCENARIO_CONFIG["max_roads"] + 1))
    with pytest.raises(ValueError, match="ที่เดียวกัน"):
        rg.add_new_roads(net, [road((0, 50), (0, 50))])
    with pytest.raises(ValueError, match="สั้นเกินไป"):
        rg.add_new_roads(net, [road((100, 3), (100, -3))], snap_m=10)       # both ends land on the same point


# ----------------------------------------------------------------------------- layer, context, config
def make_state(monkeypatch):
    state = dict(rg.StateManager._DEFAULTS)
    state["markers"] = []
    monkeypatch.setattr(rg.st, "session_state", state)
    return state


def scenario_state(monkeypatch, road_name="ถนนใหม่", points=((100, 120), (300, 120))):
    state = make_state(monkeypatch)
    net = rg.build_segment_network(comb())
    base = analyse(net, radii=(150.0, None))
    scenario = rg.add_new_roads(net, [road(*points, name=road_name)])
    after = analyse(scenario.net, radii=(150.0, None))
    state.update({rg.SS_NET: net, rg.SS_RESULT: base, rg.SS_MASK: everything(net), rg.SS_META: {"source": "test"},
                  rg.SS_SCENARIO: {"scenario": scenario, "result": after, "mask": everything(scenario.net),
                                   "base_result": base}})
    return state


def test_the_layer_shows_the_scenario_of_the_analysis_on_screen_only(monkeypatch):
    import folium

    state = scenario_state(monkeypatch)
    layer = next(layer for layer in rg.LAYERS if layer.id == "road_scenario")
    order = [layer.id for layer in rg.LAYERS]
    assert order.index("space_syntax") + 1 == order.index("road_scenario")
    assert "show_road_scenario" in rg.SESSION_KEYS_TO_SAVE
    ctx = rg.build_ctx()
    assert ctx.scenario is not None and layer.available(ctx)
    drawn, warnings = rg.render_layers(ctx, folium.Map())
    assert not warnings and "road_scenario" in [layer.id for layer in drawn]
    html = rg.legend_stack(ctx, drawn).box_html
    assert "ถนนตัดใหม่: Integration (NAIN) หลังตัดถนน" in html and rg.NEW_ROAD_COLOR in html
    lines = [c for c in rg.draw_road_scenario(ctx)._children.values() if isinstance(c, rg.CompactLines)]
    assert [c.hover_js for c in lines] == ["true", "false", "false"]    # one hover handler for the whole group
    state[rg.SS_RESULT] = analyse(state[rg.SS_NET], radii=(None,))     # a new analysis: the old scenario is stale
    assert rg.build_ctx().scenario is None and not layer.available(rg.build_ctx())
    rg.StateManager.clear_results(["space_syntax"])                    # cleared together with its analysis
    assert rg.SS_SCENARIO not in state


def rows(payload, key="rows_json"):
    return rg.json.loads(payload[key])


def test_the_layer_wears_the_space_syntax_colours_of_old_score_plus_change(monkeypatch):
    state = scenario_state(monkeypatch)
    ctx = rg.build_ctx()
    payload, layer = rg.scenario_payload(ctx), rg.ss_payload(ctx)
    cmp, shown = payload["cmp"], np.flatnonzero(ctx.ss.mask)
    assert payload["mode"] == "score" == state["ss_scn_color"]
    # before = the score the Space Syntax layer shows; before + change = after, and the colour is the after-score's
    assert np.allclose(cmp["score_before"][shown], layer["scaled"]["score"][shown])
    assert np.allclose(cmp["score_before"] + cmp["score_change"], cmp["score_after"])
    t = np.clip(cmp["score_after"][shown] / 100.0, 0.0, 1.0)
    assert [r[0] for r in rows(payload)] == rg.gradient_hex(t, ctx.ss.display["palette"])
    changed = shown[np.abs(cmp["score_change"][shown]) > 1.0][0]
    tip = rows(payload)[list(shown).index(changed)][2][1]
    b, c, a = (float(cmp[k][changed]) for k in ("score_before", "score_change", "score_after"))
    assert tip == f"{b:.1f} {c:+.1f} = {a:.1f}"
    # the new roads: same palette, on a magenta outline
    new = np.flatnonzero(ctx.scenario.scenario.is_new)
    t_new = np.clip(cmp["score_after_all"][new] / 100.0, 0.0, 1.0)
    assert [r[0] for r in rows(payload, "new_json")] == rg.gradient_hex(t_new, ctx.ss.display["palette"])
    assert {r[0] for r in rows(payload, "casing_json")} == {rg.NEW_ROAD_COLOR} and len(rows(payload, "casing_json")) == len(new)
    html = rg.legend_road_scenario(ctx)
    assert "หลังตัดถนน" in html and rg.gradient_css(ctx.ss.display["palette"]) in html


def test_a_road_that_changes_nothing_looks_exactly_like_the_space_syntax_layer(monkeypatch):
    scenario_state(monkeypatch, points=((0, 1000), (200, 1000)))
    ctx = rg.build_ctx()
    cmp = rg.scenario_payload(ctx)["cmp"]
    shown = np.flatnonzero(ctx.ss.mask)
    assert np.all(cmp["score_change"][shown] == 0.0)
    assert [r[0] for r in rows(rg.scenario_payload(ctx))] == list(rg.ss_payload(ctx)["columns"]["color"][shown])


def test_the_layer_can_still_show_the_change_itself(monkeypatch):
    state = scenario_state(monkeypatch)
    state["ss_scn_color"] = "delta"
    ctx = rg.build_ctx()
    payload = rg.scenario_payload(ctx)
    assert payload["mode"] == "delta" and rows(payload, "casing_json") == []
    shown = np.flatnonzero(ctx.ss.mask)
    assert [r[0] for r in rows(payload)] == rg.delta_hex(payload["cmp"]["pct"][shown], payload["limit"])
    assert {r[0] for r in rows(payload, "new_json")} == {rg.NEW_ROAD_COLOR}
    assert "เปลี่ยน" in rg.legend_road_scenario(ctx) and "เท่าเดิม" in rg.legend_road_scenario(ctx)
    assert "ss_scn_color" in rg.KEEP_ALIVE_KEYS and "ss_scn_color" in rg.SESSION_KEYS_TO_SAVE
    assert not rg._setting_ok("ss_scn_color", "rainbow") and rg._setting_ok("ss_scn_color", "delta")
    state["ss_scn_color"] = "rainbow"                                    # a stale value falls back to the colours
    assert rg.scenario_payload(rg.build_ctx())["mode"] == "score"


def test_scores_on_the_old_scale_add_up_and_may_pass_100():
    scaled = rg.scale_scores(np.array([1.0, 2.0, 3.0]), "linear")
    assert rg.score_on_scale(scaled, [1.0, 2.0, 3.5, np.nan]).tolist()[:3] == [0.0, 50.0, 125.0]
    assert np.isnan(rg.score_on_scale(scaled, [np.nan])[0])
    assert rg.score_on_scale(rg.scale_scores(np.array([2.0, 2.0]), "linear"), [2.0, 5.0]).tolist() == [50.0, 50.0]
    q = rg.scale_scores(np.array([1.0, 2.0, 3.0, 4.0, 5.0]), "quantile")
    on = rg.score_on_scale(q, [0.0, 1.0, 3.0, 5.0, 9.0])
    assert on.tolist() == [0.0, 0.0, 50.0, 100.0, 100.0]                  # bounded, never decreasing
    assert np.allclose(rg.score_on_scale(q, [1.0, 2.0, 3.0, 4.0, 5.0]), q["score"])


def test_road_names_typed_by_the_user_cannot_inject_html_into_the_map(monkeypatch):
    scenario_state(monkeypatch, road_name="<img src=x onerror=alert(1)>")
    ctx = rg.build_ctx()
    payload = rg.scenario_payload(ctx)
    assert "&lt;img src=x" in payload["new_json"] and "<img" not in payload["new_json"]


def test_road_settings_are_saved_and_checked_on_import(monkeypatch):
    state = make_state(monkeypatch)
    state.update(ss_new_roads="# A\n20.2, 100.4\n20.21, 100.41", ss_snap_m=45, ss_cross=False)
    exported = rg.json.loads(rg.StateManager.export_config())
    state.update(ss_new_roads="", ss_snap_m=30, ss_cross=True)
    assert rg.StateManager.import_config(exported) == []
    assert state["ss_new_roads"].startswith("# A") and state["ss_snap_m"] == 45 and state["ss_cross"] is False
    skipped = rg.StateManager.import_config({"settings": {"ss_snap_m": 500, "ss_new_roads": 7}})
    assert set(skipped) == {"ss_snap_m", "ss_new_roads"}


# ----------------------------------------------------------------------------- 4. the page (AppTest, offline)
def test_page_simulates_a_new_road_from_the_suggestion_and_clears_it(monkeypatch):
    from streamlit.testing.v1 import AppTest
    from folium.map import Layer

    rendered = []
    monkeypatch.setattr(rg.StateManager, "_load_remote_defaults", staticmethod(lambda defaults: []))
    monkeypatch.setattr(rg, "load_bundled_graph", lambda: (helpers.grid_graph(6, seed=1), "grid", None))
    monkeypatch.setattr(rg, "st_folium", lambda m, **kw: rendered.append(m) or {})

    def app():                                       # AppTest runs this function's source: import by name
        import rent_gradient_road_scenario_under_test
        rent_gradient_road_scenario_under_test.main()

    at = AppTest.from_function(app, default_timeout=180).run()
    assert not at.exception
    next(b for b in at.button if "จำลองคะแนน" in b.label).click().run()      # nothing analysed yet
    assert any("ยังไม่มีผล Space Syntax" in e.value for e in at.error)
    next(b for b in at.button if "ตัวอย่างเชียงของ" in b.label).click().run()
    assert not at.exception and at.session_state[rg.SS_RESULT] is not None
    next(b for b in at.button if "เสนอแนวตัวอย่าง" in b.label).click().run()
    assert at.text_area(key="ss_new_roads").value.startswith("# ทางลัดตัวอย่าง")
    next(b for b in at.button if "จำลองคะแนน" in b.label).click().run()
    assert not at.exception and not at.error
    assert at.radio(key="analytics_view").value == "road_scenario"
    assert [m.label for m in at.metric][-8:] == [
        "ถนนใหม่", "คะแนนถนนใหม่ (NAIN)", "NAIN เฉลี่ยถนนเดิม", "ช่วงถนนเดิม ขึ้น / ลง ≥ 1%",
        "ก่อนตัดถนน (ถนนเดิม)", "ถนนเดิม หลังตัดถนน", "+ ถนนใหม่", "= รวมหลังตัดถนน"]
    total = {m.label: m.value for m in at.metric}
    old_after, new, after = (float(total[k].lstrip("+").replace(",", ""))
                             for k in ("ถนนเดิม หลังตัดถนน", "+ ถนนใหม่", "= รวมหลังตัดถนน"))
    assert after == pytest.approx(old_after + new, abs=0.011)          # the page shows old + new = total
    names = [c.layer_name for c in rendered[-1]._children.values() if isinstance(c, Layer) and c.overlay]
    assert "🛣️ ถนนตัดใหม่ (คะแนนเปลี่ยน)" in names
    at.radio(key="ss_measure").set_value("choice").run()
    assert not at.exception and "คะแนนถนนใหม่ (NACH)" in [m.label for m in at.metric]
    at.text_area(key="ss_new_roads").input("bad line").run()
    next(b for b in at.button if "จำลองคะแนน" in b.label).click().run()
    assert any("บรรทัด 1" in e.value for e in at.error)
    assert at.session_state[rg.SS_SCENARIO] is not None                 # a typo keeps the last good scenario
    next(b for b in at.button if b.label == "ล้างผล").click().run()
    assert rg.SS_SCENARIO not in at.session_state and not at.exception
