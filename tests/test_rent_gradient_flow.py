"""Rent_Gradient_Flow: the plan-driven app built on Rent_Gradient_V2. Everything is offline.

Checks that (1) the page reuses V2 as its engine instead of copying it, (2) every guard written in the
plan (pages/Rent_Gradient_flowchart.mmd) decides the status of its node, (3) the live flowchart keeps the
whole plan and only adds colours, (4) the invalidation table equals what ``StateManager`` really clears,
and (5) the app runs end to end with Geoapify / OSM replaced by synthetic data, behind a tab named
"Rent Gradient v2".
"""
import ast
import importlib.util
import inspect
import re
import sys
from math import exp
from pathlib import Path

import networkx as nx
import pytest
from pyproj.enums import TransformDirection
from shapely.geometry import Point, mapping

ROOT = Path(__file__).resolve().parents[1]
FLOW_PATH = ROOT / "pages/Rent_Gradient_Flow.py"


def _load(name: str, relative: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


flow = _load("rent_gradient_flow_test", "pages/Rent_Gradient_Flow.py")
engine = flow.engine
sm = engine.StateManager
PLAN = engine._FLOWCHART_PATH.read_text(encoding="utf-8")

CENTER = (20.219443, 100.403630)
MARKERS = [
    {"lat": 20.2194, "lng": 100.4036, "active": True},
    {"lat": 20.2201, "lng": 100.4043, "active": True},
]


# --------------------------------------------------------------------------- helpers
def road_grid(size=11, spacing=100):
    graph = nx.MultiDiGraph(crs="EPSG:4326")
    projection = engine._anchor_projection(*CENTER)
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


def iso_features(markers=MARKERS):
    """What ``fetch_api_data_cached`` returns for each marker: one ~2 km polygon."""
    out = []
    for marker in markers:
        geom = Point(marker["lng"], marker["lat"]).buffer(0.02)
        out.append({"type": "Feature", "geometry": mapping(geom), "properties": {"value": 300}})
    return out


def iso_fc():
    feats = iso_features()
    for i, feat in enumerate(feats):
        feat["properties"].update(travel_time_minutes=5, original_index=i, active_index=i)
    return {"type": "FeatureCollection", "features": feats}


def samples_at(anchor, distances_km, lam=0.3, r0=1000.0):
    """Price samples due north of ``anchor`` that follow R(d) = r0 * exp(-lam * d)."""
    return [{"lat": anchor["lat"] + d / 111.19, "lon": anchor["lon"], "rent": r0 * exp(-lam * d)}
            for d in distances_km]


def rent_index():
    return engine.compute_rent_gradient_data(None, None, iso_fc(), MARKERS, [], "บาท")


def rent_fit(samples=None):
    anchor = rent_index()["anchor"]
    samples = samples if samples is not None else samples_at(anchor, [0.5, 1.5, 3.0])
    return engine.compute_rent_gradient_data(None, None, iso_fc(), MARKERS, samples, "บาท"), samples


def network_result():
    return {"stats": {"nodes_count": 1234}, "golden_spots": [{"score": 0.9}] * 3, "top_node": {"score": 1}}


def anchor_result():
    return engine.find_cbd_anchors(road_grid(), CENTER, 4000.0)["composite"]


def state(**layers):
    """A session state with the inputs ① needs, plus the named result layers."""
    base = {sm.K_API_KEY: "key", sm.K_MARKERS: [dict(m) for m in MARKERS], sm.K_TIME_INTERVALS: [5]}
    keys = {"iso": sm.K_ISOCHRONE, "cbd": sm.K_INTERSECTION, "net": sm.K_NETWORK, "rent": sm.K_RENT_DATA,
            "anchor": sm.K_AUTO_ANCHOR, "evidence": sm.K_AUTO_ANCHOR_EVIDENCE}
    extra = {k: layers.pop(name) for name, k in keys.items() if name in layers}
    base.update(extra)
    base.update(layers)  # raw session keys (api_key, anchor_use_evidence ...)
    return base


def status_of(session, key):
    return next(s for s in flow.evaluate_flow(flow.collect_facts(session)) if s.key == key)


# ============================================================ 1. reuse: a shell, not a copy
def test_engine_is_the_v2_module_shared_through_sys_modules():
    assert engine is sys.modules[flow.ENGINE_MODULE_NAME]
    assert Path(engine.__file__).name == "Rent_Gradient_V2.py"
    assert flow.load_engine() is engine  # a rerun reuses it, never re-executes V2


def test_page_defines_no_calculation_or_v2_ui_function():
    v2_tree = ast.parse((ROOT / "pages/Rent_Gradient_V2.py").read_text(encoding="utf-8"))
    flow_tree = ast.parse(FLOW_PATH.read_text(encoding="utf-8"))
    v2_defs = {n.name for n in v2_tree.body if isinstance(n, (ast.FunctionDef, ast.ClassDef))}
    flow_defs = {n.name for n in flow_tree.body if isinstance(n, (ast.FunctionDef, ast.ClassDef))}
    assert v2_defs & flow_defs == {"main"}  # the only shared name: each page has its own entry point


def test_runners_call_the_same_orchestrators_as_v2_main(monkeypatch):
    main_source = inspect.getsource(engine.main)
    for call in ("perform_calculation(active_list)", "perform_network_analysis()",
                 "perform_rent_gradient()", "perform_automated_anchor()"):
        assert call in main_source

    calls = []
    sentinel = [(0, {"lat": 1.0, "lng": 2.0})]
    monkeypatch.setattr(sm, "get_active_markers", classmethod(lambda cls: sentinel))
    monkeypatch.setattr(engine, "perform_calculation", lambda active: calls.append(("ISO", active)))
    monkeypatch.setattr(engine, "perform_network_analysis", lambda: calls.append(("NET",)))
    monkeypatch.setattr(engine, "perform_automated_anchor", lambda: calls.append(("ANC",)))
    monkeypatch.setattr(engine, "perform_rent_gradient", lambda: calls.append(("R1",)))
    for key in flow.RUNNERS:
        flow.RUNNERS[key]()
    assert calls == [("ISO", sentinel), ("NET",), ("ANC",), ("R1",)]


def test_session_keys_used_as_strings_still_exist_in_v2():
    for key in (flow.KEY_USE_EVIDENCE, flow.KEY_RENT_EVIDENCE_ANCHOR):
        assert key in sm._DEFAULTS and key in engine.SESSION_KEYS_TO_SAVE
    assert flow.KEY_ANCHOR_CENTER_TEXT in inspect.getsource(engine._render_sidebar_anchor_panel)


# ============================================================ 2. guards of the plan, node by node
def test_plan_nodes_and_statuses_cover_each_other():
    ids = flow.plan_node_ids(PLAN)
    assert set(ids) == {"GOAL", "ERR", "ISO", "NET", "ANC", "EVN", "R1", "INV"}
    keys = [s.key for s in flow.evaluate_flow(flow.FlowFacts())]
    assert keys == ["ISO", "NET", "ANC", "EVN", "R1", "GOAL"]
    assert set(ids) - set(keys) == {"ERR", "INV"}  # stop-node and the invalidation table are not cards


@pytest.mark.parametrize("node, phrases", [
    ("ISO", ["ต้องมี API key", "active marker", "เลือกเวลา", "ไม่ได้ feature เลย"]),
    ("NET", ["ต้องมี isochrone"]),
    ("ANC", ["R 4–20 กม."]),
    ("R1", ["ต้องมี isochrone ∨ auto anchor", "แก้ตาราง = sync อย่างเดียว"]),
])
def test_the_guard_wording_is_still_in_the_plan(node, phrases):
    block = next(line for line in PLAN.splitlines() if re.match(rf"\s+{node}\[", line))
    for phrase in phrases:
        assert phrase in block, f"{node}: plan no longer says {phrase!r}; update the guard in the page"


def test_iso_needs_key_marker_and_time_and_names_every_missing_one():
    ok = state()
    assert status_of(ok, "ISO").state == flow.READY
    for patch, reason in (
        ({sm.K_API_KEY: ""}, "ไม่มี API key"),
        ({sm.K_MARKERS: [{"lat": 1, "lng": 2, "active": False}]}, "หมุด active"),
        ({sm.K_TIME_INTERVALS: []}, "ยังไม่ได้เลือกเวลา"),
    ):
        got = status_of({**ok, **patch}, "ISO")
        assert got.state == flow.BLOCKED and reason in got.detail
    nothing = status_of({}, "ISO")
    assert nothing.state == flow.BLOCKED
    assert all(r in nothing.detail for r in ("API key", "หมุด active", "เวลา"))


def test_iso_done_reports_cbd_or_why_there_is_none():
    with_cbd = status_of(state(iso=iso_fc(), cbd={"features": [{"geometry": {}}]}), "ISO")
    assert with_cbd.state == flow.DONE and "พบ CBD" in with_cbd.detail and "2 isochrone" in with_cbd.detail
    no_cbd = status_of(state(iso=iso_fc()), "ISO")
    assert no_cbd.state == flow.DONE and "ไม่พบ CBD" in no_cbd.detail


def test_network_needs_an_isochrone_and_survives_marker_changes():
    assert status_of(state(), "NET").state == flow.BLOCKED
    assert status_of(state(iso=iso_fc()), "NET").state == flow.READY
    done = status_of(state(iso=iso_fc(), net=network_result()), "NET")
    assert done.state == flow.DONE and "1,234 โหนด" in done.detail and "3 จุด" in done.detail
    kept = status_of(state(net=network_result()), "NET")  # rule (a) cleared the isochrone, kept the network
    assert kept.state == flow.DONE and "ผลจากรอบก่อน" in kept.detail
    assert status_of(state(iso=iso_fc(), net={"error": "no data"}), "NET").state == flow.READY


def test_anchor_is_optional_and_guarded_by_scipy_and_a_valid_centre(monkeypatch):
    assert status_of(state(), "ANC").state == flow.IDLE
    assert status_of(state(anchor_center_input="not a coordinate"), "ANC").state == flow.BLOCKED
    assert status_of(state(anchor_center_input="20.2, 100.4"), "ANC").state == flow.IDLE
    monkeypatch.setattr(engine, "HAS_SCIPY", False)
    assert status_of(state(), "ANC").state == flow.BLOCKED
    monkeypatch.setattr(engine, "HAS_SCIPY", True)
    done = status_of(state(anchor=anchor_result()), "ANC")
    assert done.state == flow.DONE and "20.2" in done.detail and "Closeness 100%" in done.detail


def test_evidence_states_follow_the_toggle_and_the_stored_result():
    ok_ev = {"schema": engine.EVIDENCE_SCHEMA, "status": "ok", "evidence_anchor": {"lat": 1, "lon": 2},
             "confidence": {"level": "HIGH"}}
    cases = [
        (state(), flow.OFF),
        (state(anchor_use_evidence=True), flow.IDLE),                        # waits for the anchor
        (state(anchor_use_evidence=True, anchor=anchor_result()), flow.READY),  # on, no result yet
        (state(anchor_use_evidence=True, anchor=anchor_result(), evidence=ok_ev), flow.DONE),
        (state(anchor_use_evidence=True, evidence={**ok_ev, "status": "unavailable"}), flow.PARTIAL),
        (state(anchor_use_evidence=True, evidence={**ok_ev, "schema": 1}), flow.STALE),
    ]
    for session, expected in cases:
        assert status_of(session, "EVN").state == expected
    done = status_of(state(anchor_use_evidence=True, evidence=ok_ev), "EVN")
    assert "HIGH" in done.detail and "Composite" in done.detail
    used = status_of(state(anchor_use_evidence=True, evidence=ok_ev, rent_use_evidence_anchor=True), "EVN")
    assert "Evidence anchor" in used.detail


def test_rent_needs_isochrone_or_anchor():
    assert status_of(state(), "R1").state == flow.BLOCKED
    assert status_of(state(iso=iso_fc()), "R1").state == flow.READY
    assert status_of(state(anchor=anchor_result()), "R1").state == flow.READY  # auto anchor is enough


def test_rent_modes_come_from_real_v2_results():
    index = status_of(state(iso=iso_fc(), rent=rent_index()), "R1")
    assert index.state == flow.DONE and "INDEX" in index.detail
    fit, samples = rent_fit()
    got = status_of(state(iso=iso_fc(), rent=fit, rent_samples=samples), "R1")
    assert got.state == flow.DONE and "FIT n=3" in got.detail and "R²=" in got.detail
    two, two_samples = rent_fit(samples_at(rent_index()["anchor"], [0.5, 2.0]))
    two_detail = status_of(state(iso=iso_fc(), rent=two, rent_samples=two_samples), "R1").detail
    assert "FIT n=2" in two_detail and "R²" not in two_detail  # n = 2: R² means nothing


def test_a_model_without_r2_is_index_mode_exactly_as_v2_labels_it():
    fit, samples = rent_fit()
    odd = {**fit, "model": {**fit["model"], "r2": None}}   # is_index False, but no R²
    assert engine.fit_quality_label(odd["model"]).startswith("โหมดดัชนี")
    assert not flow.collect_facts(state(rent=odd, rent_samples=samples)).rent_fit


def test_editing_the_table_after_a_fit_marks_rent_stale():
    fit, samples = rent_fit()
    session = lambda table: state(iso=iso_fc(), rent=fit, rent_samples=table)  # noqa: E731
    assert status_of(session(samples), "R1").state == flow.DONE
    changed = [dict(samples[0], rent=samples[0]["rent"] * 2)] + samples[1:]
    moved = [dict(samples[0], lat=samples[0]["lat"] + 0.001)] + samples[1:]
    for table in (changed, moved, samples[:-1], samples + samples_at(fit["anchor"], [4.0]), []):
        got = status_of(session(table), "R1")
        assert got.state == flow.STALE and "fit ใหม่" in got.detail, table


def test_index_rent_is_stale_only_when_the_table_can_now_be_fitted():
    index = rent_index()
    anchor = index["anchor"]
    session = lambda table: state(iso=iso_fc(), rent=index, rent_samples=table)  # noqa: E731
    assert status_of(session([]), "R1").state == flow.DONE
    assert status_of(session(samples_at(anchor, [1.0])), "R1").state == flow.DONE     # one point cannot fit
    same_distance = samples_at(anchor, [1.0, 1.0])
    assert status_of(session(same_distance), "R1").state == flow.DONE                 # no spread in distance
    assert status_of(session(samples_at(anchor, [0.5, 2.0])), "R1").state == flow.STALE


def test_goal_lists_what_is_produced_and_what_is_missing():
    fit, samples = rent_fit()
    cases = {
        "none": (state(), flow.IDLE, ["ได้: —", "ต้อง ④", "ต้อง ③"]),
        "rent only": (state(iso=iso_fc(), rent=fit, rent_samples=samples), flow.PARTIAL,
                      ["Bid-Rent curve", "Rent Heat (ต้อง ③)", "Value Gap"]),
        "network only": (state(iso=iso_fc(), net=network_result()), flow.PARTIAL,
                         ["Golden table", "Bid-Rent curve (ต้อง ④)"]),
        "network + index": (state(iso=iso_fc(), net=network_result(), rent=rent_index()), flow.PARTIAL,
                            ["Rent Heat บนโหนด", "ต้อง FIT"]),
        "network + fit": (state(iso=iso_fc(), net=network_result(), rent=fit, rent_samples=samples), flow.DONE,
                          ["Rent Heat บนโหนด", "Value Gap"]),
    }
    for name, (session, expected, texts) in cases.items():
        got = status_of(session, "GOAL")
        assert got.state == expected, name
        assert all(t in got.detail for t in texts), (name, got.detail)
    assert "ขาด" not in status_of(cases["network + fit"][0], "GOAL").detail
    assert "Value Gap" in status_of(cases["network + index"][0], "GOAL").detail.split("ขาด:")[1]


def test_goal_is_not_done_while_the_fit_is_stale():
    fit, samples = rent_fit()
    session = state(iso=iso_fc(), net=network_result(), rent=fit, rent_samples=samples[:-1])
    assert status_of(session, "GOAL").state == flow.PARTIAL


def test_next_step_walks_the_plan_in_order():
    def step(session):
        facts = flow.collect_facts(session)
        return flow.next_step(flow.evaluate_flow(facts), facts)

    fit, samples = rent_fit()
    assert "แก้เงื่อนไขของ ①" in step({})
    assert "กดรัน ①" in step(state())
    assert "กดรัน ③" in step(state(iso=iso_fc(), rent=rent_index()))
    assert "ตัวอย่างราคา ≥ 2 จุด" in step(state(iso=iso_fc(), net=network_result(), rent=rent_index()))
    assert "fit" in step(state(iso=iso_fc(), net=network_result(), rent=fit, rent_samples=samples[:-1]))
    assert "ครบตามแผน" in step(state(iso=iso_fc(), net=network_result(), rent=fit, rent_samples=samples))
    assert "รัน ① ก่อน" in step(state(anchor=anchor_result(), rent=rent_index()))


@pytest.mark.parametrize("session", [
    {sm.K_NETWORK: {"error": "x"}}, {sm.K_RENT_DATA: {"error": "x"}}, {sm.K_RENT_DATA: {"model": {}}},
    {sm.K_ISOCHRONE: {}}, {sm.K_INTERSECTION: {"features": []}}, {sm.K_MARKERS: [{}]},
    {sm.K_AUTO_ANCHOR_EVIDENCE: {"schema": engine.EVIDENCE_SCHEMA}}, {sm.K_TIME_INTERVALS: None},
    {sm.K_RENT_DATA: {"anchor": {}, "model": {"is_index": False}, "samples_scatter": []}},
])
def test_odd_session_shapes_never_raise(session):
    statuses = flow.evaluate_flow(flow.collect_facts(session))
    assert len(statuses) == 6


def test_facts_see_the_ui_lock():
    assert flow.collect_facts({sm.K_UI_LOCKED: True}).locked
    assert not flow.collect_facts({}).locked


# ============================================================ 3. live flowchart
def test_live_flowchart_keeps_the_whole_plan_and_only_adds_colours():
    statuses = flow.evaluate_flow(flow.collect_facts(state(iso=iso_fc(), rent=rent_index())))
    live = flow.live_flowchart(PLAN, statuses)
    assert live.startswith(PLAN.rstrip("\n"))
    added = live[len(PLAN.rstrip("\n")):].splitlines()[1:]
    assert all(re.match(r"\s+(classDef st_\w+ |class [A-Z0-9,]+ st_\w+$)", line) for line in added), added
    assert flow.plan_node_ids(live) == flow.plan_node_ids(PLAN)


def _node_classes(live):
    """{node id: st_* class} read back from the ``class A,B st_x`` lines of a live flowchart."""
    colours = {}
    for line in live.splitlines():
        match = re.match(r"\s+class ([A-Z0-9,]+) (st_\w+)$", line)
        if match:
            colours.update({key: match.group(2) for key in match.group(1).split(",")})
    return colours


def test_live_flowchart_colours_match_the_statuses_and_skip_goal_and_err():
    statuses = flow.evaluate_flow(flow.collect_facts(state(iso=iso_fc(), rent=rent_index())))
    live = flow.live_flowchart(PLAN, statuses)
    colours = _node_classes(live)
    assert colours == {"ISO": "st_done", "NET": "st_ready", "ANC": "st_idle", "EVN": "st_idle", "R1": "st_done"}
    defined = set(re.findall(r"classDef (st_\w+) ", live))
    assert set(colours.values()) <= defined == set(flow.CLASS_STYLE)
    assert "GOAL" not in colours and "ERR" not in colours  # they keep the plan's own gold / red


def test_live_flowchart_ignores_statuses_of_nodes_the_plan_no_longer_has():
    trimmed = "\n".join(line for line in PLAN.splitlines() if not re.match(r"\s+EVN\[", line))
    assert "EVN" not in flow.plan_node_ids(trimmed)
    colours = _node_classes(flow.live_flowchart(trimmed, flow.evaluate_flow(flow.FlowFacts())))
    assert "EVN" not in colours and "ISO" in colours


def test_the_live_diagram_is_embedded_through_the_shared_html_builder(monkeypatch):
    shown = []
    monkeypatch.setattr(flow.st, "iframe", lambda markup, **kw: shown.append((markup, kw)), raising=False)
    live = flow.live_flowchart(PLAN, flow.evaluate_flow(flow.collect_facts(state())))
    flow._render_plan_diagram(live)
    markup, kwargs = shown[0]
    assert markup == engine._flowchart_html(live)                  # same builder as V2's own Flowchart tab
    assert "class ISO st_ready" in markup and "startOnLoad: false" in markup
    assert kwargs == {"height": engine._FLOWCHART_HEIGHT_PX}


def test_every_state_has_a_badge_and_a_mermaid_class():
    states = {flow.DONE, flow.READY, flow.BLOCKED, flow.STALE, flow.PARTIAL, flow.IDLE, flow.OFF}
    assert set(flow.STATE_BADGE) == set(flow.STATE_CLASS) == states
    assert set(flow.STATE_CLASS.values()) <= set(flow.CLASS_STYLE)


# ============================================================ 4. invalidation table == StateManager
LAYER_KEYS = [sm.K_ISOCHRONE, sm.K_INTERSECTION, sm.K_NETWORK, sm.K_RENT_DATA,
              sm.K_AUTO_ANCHOR, sm.K_AUTO_ANCHOR_CLOSENESS, sm.K_AUTO_ANCHOR_EVIDENCE]


def _cleared_by(monkeypatch, call):
    fake = {key: "kept" for key in LAYER_KEYS}
    monkeypatch.setattr(engine.st, "session_state", fake)
    call()
    return {key for key in LAYER_KEYS if fake[key] is None}


def test_invalidation_rules_equal_what_statemanager_clears(monkeypatch):
    actual = {
        "(a)": _cleared_by(monkeypatch, sm.invalidate_markers),
        "(b)": _cleared_by(monkeypatch, sm.invalidate_anchors),
        "(c)": _cleared_by(monkeypatch, sm.clear_results),
        "(d)": _cleared_by(monkeypatch, sm.invalidate_rent),
    }
    shown = {rule.code: set(rule.clears) for rule in flow.invalidation_rules()}
    assert shown == actual


def test_invalidation_table_lists_every_layer_either_cleared_or_kept():
    table = flow.invalidation_table_markdown().splitlines()
    assert table[0].startswith("| กติกา") and len(table) == 2 + 4
    for row in table[2:]:
        cleared, kept = row.split("|")[3], row.split("|")[4]
        labels = {x.strip() for x in (cleared + "·" + kept).split("·") if x.strip() not in ("", "—")}
        assert labels == set(flow._layer_labels().values())


# ============================================================ 5. the app, end to end (offline)
@pytest.fixture
def app(monkeypatch):
    """Geoapify and OSM are replaced; V2's own orchestrators, maths and widgets run for real."""
    from streamlit.testing.v1 import AppTest

    monkeypatch.setattr(sm, "_load_remote_defaults",
                        staticmethod(lambda defaults: [dict(m) for m in MARKERS]))
    monkeypatch.setattr(engine, "fetch_api_data_cached", lambda *args: (iso_features(), None))
    monkeypatch.setattr(engine, "_fetch_osm_graph", lambda *args: (road_grid(), True, None))
    monkeypatch.setattr(engine, "compute_centrality_cached",
                        lambda wkt, net: engine._compute_centrality_impl(wkt, net))

    def script():
        import rent_gradient_flow_test
        rent_gradient_flow_test.main()

    def start():
        at = AppTest.from_function(script, default_timeout=90).run()
        assert not at.exception
        return at

    return start


def run_button(at, key):
    """Press a Flow-tab button and let the script rerun (the on_click queues the node, main() runs it)."""
    at.button(key=f"flow_run_{key}").click()
    at.run()
    assert not at.exception, [e.value for e in at.exception]


TITLES = {s.key: s.title for s in flow.evaluate_flow(flow.FlowFacts())}


def badge(at, key):
    """The heading line of a node's card: ``**title** · <state badge>``."""
    return next(m.value for m in at.markdown if m.value.startswith(f"**{TITLES[key]}**"))


def details(at):
    """Every caption on the page (a card's detail line is one of them)."""
    return " ".join(c.value for c in at.caption)


def infos(at):
    return " ".join(i.value for i in at.info)


def progress_percent(at):
    """Value (0-100) of the plan progress bar; AppTest has no first-class accessor for st.progress."""
    return at.get("progress")[0].proto.value


def test_app_has_the_rent_gradient_v2_tab_before_the_flow_tab(app):
    at = app()
    labels = [t.label for t in at.tabs]
    assert flow.TAB_V2_LABEL in labels and flow.TAB_FLOW_LABEL in labels
    assert labels.index(flow.TAB_V2_LABEL) < labels.index(flow.TAB_FLOW_LABEL)
    assert flow.TAB_V2_LABEL.endswith("Rent Gradient v2")
    # V2 comes through whole: its sidebar buttons and its own analytics tabs
    button_labels = {b.label for b in at.button}
    assert {"🧩 ① คำนวณหา Isochrone CBD", "🚀 Run Network Analysis", "🧮 คำนวณ Rent Gradient"} <= button_labels
    assert {"📈 Bid-Rent Curve", "💎 Golden Spots", "🗺️ Flowchart"} <= set(labels)


def test_first_screen_blocks_everything_but_the_first_step(app):
    at = app()
    assert not at.button(key="flow_run_ISO").disabled
    assert not at.button(key="flow_run_ANC").disabled         # optional path is open
    for key in ("NET", "R1"):
        assert at.button(key=f"flow_run_{key}").disabled
    assert "กดรัน ①" in infos(at)
    assert progress_percent(at) == 0


def test_flow_buttons_run_the_whole_plan_and_the_board_is_fresh_in_the_same_pass(app):
    at = app()

    run_button(at, "ISO")                         # ① -> isochrone + CBD, Rent runs quietly after it
    assert at.session_state[sm.K_ISOCHRONE] and at.session_state[sm.K_INTERSECTION]
    assert at.session_state[sm.K_RENT_DATA]["model"]["is_index"]
    assert "✅ เสร็จ" in badge(at, "ISO") and "พบ CBD" in details(at)
    assert not at.button(key="flow_run_NET").disabled   # no second click needed to unlock ③
    assert not at.button(key="flow_run_R1").disabled

    run_button(at, "NET")                         # ③ -> network, Golden Spots
    assert at.session_state[sm.K_NETWORK]["golden_spots"]
    assert at.session_state[sm.K_RENT_DATA] is not None   # kept (and refreshed), not cleared
    assert "✅ เสร็จ" in badge(at, "NET") and "โหนด" in details(at)
    assert "ตัวอย่างราคา ≥ 2 จุด" in infos(at)

    anchor = at.session_state[sm.K_RENT_DATA]["anchor"]
    at.session_state[sm.K_RENT_SAMPLES] = samples_at(anchor, [0.5, 1.5, 3.0])
    at.run()
    assert "⚠️ ควรรันใหม่" in badge(at, "R1")           # table edited: sync only, the plan says re-run ④
    assert at.session_state[sm.K_RENT_DATA]["model"]["is_index"]   # ... and nothing was re-fitted behind our back

    run_button(at, "R1")                          # ④ -> FIT, Value Gap becomes possible
    assert not at.session_state[sm.K_RENT_DATA]["model"]["is_index"]
    assert "✅ เสร็จ" in badge(at, "R1") and "FIT n=3" in details(at)
    assert "✅ เสร็จ" in badge(at, "GOAL") and "Value Gap" in details(at)
    assert progress_percent(at) == 100


def test_marker_change_follows_rule_a_and_the_board_shows_it(app):
    at = app()
    run_button(at, "ISO")
    run_button(at, "NET")
    at.checkbox(key="active_chk_1").uncheck().run()      # V2's own sidebar control -> rule (a)
    assert not at.exception
    assert at.session_state[sm.K_ISOCHRONE] is None and at.session_state[sm.K_RENT_DATA] is None
    assert at.session_state[sm.K_NETWORK]                   # the plan keeps the network
    assert "ผลจากรอบก่อน" in details(at)
    assert at.button(key="flow_run_NET").disabled           # ... but it cannot be re-run until ① is
    assert at.button(key="flow_run_R1").disabled


def test_anchor_path_gives_rent_without_an_isochrone(app):
    at = app()
    run_button(at, "ANC")
    assert at.session_state[sm.K_AUTO_ANCHOR] and at.session_state[sm.K_RENT_DATA]
    assert at.session_state[sm.K_ISOCHRONE] is None
    assert "✅ เสร็จ" in badge(at, "ANC") and "✅ เสร็จ" in badge(at, "R1")
    assert at.button(key="flow_run_NET").disabled           # Golden Spots still need ①
    assert "รัน ① ก่อน" in infos(at)


def test_sidebar_buttons_still_work_inside_the_shell(app):
    at = app()
    next(b for b in at.button if b.label == "🧩 ① คำนวณหา Isochrone CBD").click().run()
    assert not at.exception and at.session_state[sm.K_ISOCHRONE]
    assert "✅ เสร็จ" in badge(at, "ISO")                  # the Flow tab reads the same state


def test_locking_the_ui_disables_the_flow_buttons(app):
    at = app()
    at.toggle(key=sm.K_UI_LOCKED).set_value(True).run()
    assert not at.exception
    assert all(at.button(key=f"flow_run_{k}").disabled for k in ("ISO", "NET", "ANC", "R1"))
    assert "ล็อกอยู่" in details(at)


def test_a_failing_flow_board_does_not_take_the_v2_workflow_down(app, monkeypatch):
    at = app()
    monkeypatch.setattr(flow, "collect_facts", lambda state: (_ for _ in ()).throw(RuntimeError("boom")))
    at.run()
    assert not at.exception                                   # the page survives ...
    assert any("แท็บ Flow แสดงผลไม่สำเร็จ" in e.value and "boom" in e.value for e in at.error)
    assert flow.TAB_V2_LABEL in [t.label for t in at.tabs]   # ... and V2's tab, map and sidebar are intact
    assert {"🧩 ① คำนวณหา Isochrone CBD", "🚀 Run Network Analysis"} <= {b.label for b in at.button}


def test_a_blocked_node_is_explained_and_not_run(monkeypatch):
    warnings, calls = [], []
    monkeypatch.setattr(flow.st, "session_state", {})
    monkeypatch.setattr(flow.st, "warning", lambda msg, **kw: warnings.append(msg))
    monkeypatch.setattr(engine, "perform_network_analysis", lambda: calls.append("NET"))
    flow.run_flow_node("NET")
    assert calls == [] and len(warnings) == 1 and "ต้องมี isochrone" in warnings[0]


def test_clicking_a_flow_button_only_queues_the_node(monkeypatch):
    session = {}
    monkeypatch.setattr(flow.st, "session_state", session)
    flow._queue_run("R1")
    assert session == {flow.PENDING_KEY: "R1"}
