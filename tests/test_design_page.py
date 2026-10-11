"""Design page: seeded + vectorised graph search, validated AI JSON, deterministic packed plan, Streamlit flow (offline)."""
import importlib.util
import json
import os
import random
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "pages/Design.py"
spec = importlib.util.spec_from_file_location("design_page_test", PAGE)
page = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = page
spec.loader.exec_module(page)

ROOMS = list(page.DEFAULT_ROOMS)


# ------------------------------------------------------------------- helpers
def reference_score(rooms, C, W, edges):
    """S*(G) written out from the docstring formula: sum of Q over edges minus W of every missing critical pair."""
    on = {frozenset(e) for e in edges}
    score = 0.0
    for i in range(len(rooms)):
        for j in range(i + 1, len(rooms)):
            if frozenset((rooms[i], rooms[j])) in on:
                score += C[i][j] * W[i][j]
            elif C[i][j] == 1 and W[i][j] == 3:
                score -= W[i][j]
    return score


def reference_violations(rooms, C, W, edges):
    """Critical pairs (W=3) that are 'must touch' but missing, or 'must stay apart' but linked."""
    on = {frozenset(e) for e in edges}
    return sum(1 for i in range(len(rooms)) for j in range(i + 1, len(rooms))
               if W[i][j] == 3 and ((C[i][j] == 1 and frozenset((rooms[i], rooms[j])) not in on)
                                    or (C[i][j] == -1 and frozenset((rooms[i], rooms[j])) in on)))


def is_connected(rooms, edges):
    seen, todo = {rooms[0]}, [rooms[0]]
    while todo:
        here = todo.pop()
        for a, b in edges:
            for x, y in ((a, b), (b, a)):
                if x == here and y not in seen:
                    seen.add(y)
                    todo.append(y)
    return len(seen) == len(rooms)


def random_matrices(rooms, rng):
    n = len(rooms)
    C = [[0] * n for _ in range(n)]
    W = [[0] * n for _ in range(n)]
    for i in range(n):
        for j in range(i + 1, n):
            C[i][j] = C[j][i] = rng.choice([-1, 0, 1])
            W[i][j] = W[j][i] = rng.choice([0, 1, 2, 3])
    return C, W


def engine_plan(seed=1, rooms=ROOMS):
    """One engine run on the default typology, rendered the way Tab 2 receives it."""
    C, W = page.build_default_matrices(rooms)
    space = [{"room": r, "net_area_sqm": page.DEFAULT_AREAS[r]} for r in rooms]
    res = page.run_engine(rooms, C, W, space, "concept", 100, 5, 0.7, seed)
    return res, page.plans_from_results(res)


PLAN_JSON = json.loads(engine_plan()[1][0])


# ------------------------------------------------------------------- engine
def test_default_typology_keeps_the_critical_rules():
    C, W = page.build_default_matrices(["Kitchen", "Dining", "Bedroom"])
    assert (C[0][1], W[0][1]) == (1, 3) == (C[1][0], W[1][0])          # kitchen next to dining
    assert (C[0][2], W[0][2]) == (-1, 3)                                # bedroom away from kitchen


@pytest.mark.parametrize("seed", range(5))
def test_scores_and_violations_match_the_written_formula(seed):
    rng = random.Random(seed)
    rooms = rng.sample(page.ROOM_OPTIONS, rng.randint(2, 8))
    C, W = random_matrices(rooms, rng)
    mc = page.MatrixController(rooms, C, W)
    pairs = [(a, b) for i, a in enumerate(rooms) for b in rooms[i + 1:]]
    for _ in range(20):
        edges = [e if rng.random() < .5 else e[::-1] for e in pairs if rng.random() < .5]
        assert mc.graph_score(edges) == pytest.approx(reference_score(rooms, C, W, edges))
        assert len(mc.get_violated_rules(edges)) == reference_violations(rooms, C, W, edges)
    best = sum(C[i][j] * W[i][j] for i in range(len(rooms)) for j in range(i + 1, len(rooms)) if C[i][j] * W[i][j] > 0)
    assert mc.max_theoretical_score() == (best or 1.0)


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_top_k_graphs_are_distinct_connected_and_ranked(seed):
    C, W = page.build_default_matrices(ROOMS)
    mc = page.MatrixController(ROOMS, C, W)
    best = mc.filter_best_graphs(N=300, top_k=8, T=0.7, seed=seed)
    assert len({frozenset(frozenset(e) for e in edges) for edges, _ in best}) == len(best)   # no duplicate graphs
    assert [s for _, s in best] == sorted((s for _, s in best), reverse=True)
    for edges, score in best:
        assert is_connected(ROOMS, edges)
        assert score == pytest.approx(reference_score(ROOMS, C, W, edges))


def test_same_seed_same_answer_other_seed_other_answer():
    C, W = page.build_default_matrices(ROOMS)
    mc = page.MatrixController(ROOMS, C, W)
    first = mc.filter_best_graphs(N=100, top_k=5, T=0.7, seed=42)
    assert first == mc.filter_best_graphs(N=100, top_k=5, T=0.7, seed=42)
    assert first != mc.filter_best_graphs(N=100, top_k=5, T=0.7, seed=43)


def test_a_matrix_that_never_connects_is_fast_and_falls_back_to_the_chain():
    n = len(ROOMS)                                                      # every pair 'must stay apart': ~never connected
    C = [[0 if i == j else -1 for j in range(n)] for i in range(n)]
    W = [[0 if i == j else 3 for j in range(n)] for i in range(n)]
    mc = page.MatrixController(ROOMS, C, W)
    start = time.perf_counter()
    best = mc.filter_best_graphs(N=500, top_k=5, T=0.7, seed=1)
    assert time.perf_counter() - start < 1.5                            # the unvectorised search needed ~5 s here
    assert best[0][0] == list(zip(ROOMS, ROOMS[1:]))                    # fallback = rooms in a row
    assert all(is_connected(ROOMS, edges) for edges, _ in best)


def test_samples_with_too_few_edges_never_reach_the_graph_search(monkeypatch):
    n = len(ROOMS)
    C = [[0 if i == j else -1 for j in range(n)] for i in range(n)]
    W = [[0 if i == j else 3 for j in range(n)] for i in range(n)]
    mc = page.MatrixController(ROOMS, C, W)
    calls = []
    search = page.MatrixController._connected
    monkeypatch.setattr(page.MatrixController, "_connected", lambda self, mask: calls.append(1) or search(self, mask))
    mc.filter_best_graphs(N=500, top_k=5, T=0.7, seed=1)                # 500 graphs x 500 attempts = 250 000 draws
    assert len(calls) < 50                                              # a connected graph needs n-1 = 5 edges; these draws have ~0.2


def test_tiny_and_extreme_inputs_do_not_crash():
    one = page.MatrixController(["A"], [[0]], [[0]])
    assert one.filter_best_graphs(N=5, top_k=3, seed=1) == [([], 0.0)]
    two = page.MatrixController(["A", "B"], [[0, 1], [1, 0]], [[0, 3], [3, 0]])
    assert two.filter_best_graphs(N=5, top_k=3, seed=1) == [([("A", "B")], 3.0)]
    assert two.generate_graph(T=0, rng=np.random.default_rng(0)) == [("A", "B")]     # T=0 must not divide by zero


def test_blank_cells_never_poison_the_engine():
    _, W0 = page.build_default_matrices(["Bedroom", "Kitchen"])         # W(Bedroom, Kitchen) = 3
    mc = page.MatrixController(["Bedroom", "Kitchen"], [[0, np.nan], [np.nan, 0]], W0)    # user deleted the C cell
    assert mc.edge_score("Bedroom", "Kitchen") == 0.0 == mc.edge_score("Kitchen", "Bedroom")
    scores = [s for _, s in mc.filter_best_graphs(N=10, top_k=3, seed=1)]
    assert scores and not any(np.isnan(scores))


def test_merge_matrix_edits_honours_either_triangle():
    base = np.array([[0, -1, 1], [-1, 0, 0], [1, 0, 0]], dtype=float)
    edited = base.copy()
    edited[1, 0] = 0                       # user cleared the LOWER cell of pair (0, 1)
    edited[2, 0] = 0                       # ... and the lower cell of (0, 2)
    edited[1, 2] = 1                       # ... and set the UPPER cell of (1, 2)
    merged = page.merge_matrix_edits(base, edited, -1, 1)
    assert merged.tolist() == [[0, 0, 0], [0, 0, 1], [0, 1, 0]]
    both = base.copy()
    both[0, 1], both[1, 0] = 1, 0          # both halves changed -> upper wins
    assert page.merge_matrix_edits(base, both, -1, 1)[1, 0] == 1
    blank = base.copy()
    blank[0, 1] = np.nan                   # blank cell == no rule
    assert page.merge_matrix_edits(base, blank, -1, 1)[0, 1] == 0
    assert page.merge_matrix_edits(base, np.full((3, 3), 9.0), -1, 1).max() == 1     # clipped into range


def test_negative_zero_quality_is_printed_as_zero():
    out = page.MatrixController(["A", "B"], [[0, -1], [-1, 0]], [[0, 0], [0, 0]]).to_adjacency_json([("A", "B")], [])
    assert out["Adjacency"] == [{"room1": "A", "room2": "B", "score": -1, "reason": "Q=0 (C=Indirect, W=Low)"}]   # was 'Q=-0'


def test_adjacency_json_contract():
    rooms = ["Kitchen", "Dining", "Bedroom"]
    C, W = page.build_default_matrices(rooms)
    out = page.MatrixController(rooms, C, W).to_adjacency_json(
        [("Kitchen", "Dining"), ("Dining", "Bedroom")], [{"room": "Kitchen", "net_area_sqm": 6.0}], "concept")
    assert out["Design_Concept"] == "concept" and out["Space_Requirement"][0]["room"] == "Kitchen"
    assert out["Adjacency"] == [
        {"room1": "Kitchen", "room2": "Dining", "score": 3, "reason": "Q=3 (C=Direct, W=High)"},
        {"room1": "Dining", "room2": "Bedroom", "score": -1, "reason": "Q=0 (C=Indirect, W=Low)"},   # was 'Q=-0'
    ]


# ------------------------------------------------------------------- AI JSON in, validated
@pytest.mark.parametrize("text", [
    '{"a": 1}',
    '```json\n{"a": 1}\n```',
    'Sure! Here is the JSON:\n```\n{"a": 1}\n```\nHope it helps',
    'Here you go: {"a": 1} — enjoy',
    '﻿  {"a": 1}  ',
])
def test_parse_json_text_accepts_what_chat_uis_add(text):
    assert page.parse_json_text(text) == {"a": 1}


@pytest.mark.parametrize("text", ["", "not json at all", '{"a": ', "```json\n{broken\n```"])
def test_parse_json_text_still_rejects_garbage(text):
    with pytest.raises(json.JSONDecodeError):
        page.parse_json_text(text)


def test_rules_from_ai_clamps_coerces_and_reports():
    data = {
        "Space_Requirement": [
            {"room": "Kitchen", "net_area_sqm": "6.5"},          # numeric string is fine
            {"room": "Dining", "net_area_sqm": 0},                # unusable area -> floor + warning
            {"room": "Kitchen", "net_area_sqm": 3},               # duplicate room -> dropped + warning
            {"room": "Bedroom", "net_area_sqm": None},
            "garbage",
        ],
        "Adjacency_Rules": [
            {"room1": "Kitchen", "room2": "Dining", "Connectivity_C": "1", "Importance_W": 7},     # W clamps to 3
            {"room1": "Dining", "room2": "Bedroom", "Connectivity_C": -5, "Importance_W": "x"},   # C clamps to -1, W -> 0
            {"room1": "Kitchen", "room2": "Attic", "Connectivity_C": 1, "Importance_W": 3},       # unknown room -> skipped
            {"room1": "Kitchen", "room2": "Kitchen"},                                              # self pair -> skipped
            "garbage",
        ],
        "Design_Concept": "open plan",
    }
    rules, warnings = page.rules_from_ai(data)
    assert rules["rooms"] == ["Kitchen", "Dining", "Bedroom"] and rules["concept"] == "open plan"
    assert [s["net_area_sqm"] for s in rules["space"]] == [6.5, page.MIN_AREA, page.MIN_AREA]
    assert (rules["C"][0][1], rules["W"][0][1]) == (1, 3) == (rules["C"][1][0], rules["W"][1][0])
    assert (rules["C"][1][2], rules["W"][1][2]) == (-1, 0)
    assert len(warnings) == 4                                     # duplicate + 2 bad areas + 3 skipped rules (one line)


@pytest.mark.parametrize("data", [[], {}, {"Adjacency_Rules": {}}, {"Adjacency_Rules": []}, {"Space_Requirement": [], "Adjacency_Rules": []}])
def test_rules_from_ai_refuses_unusable_json(data):
    with pytest.raises(ValueError):
        page.rules_from_ai(data)


def test_ai_rules_are_reordered_to_the_selection_and_ignored_for_other_rooms():
    rules, _ = page.rules_from_ai({"Space_Requirement": [{"room": "Kitchen", "net_area_sqm": 6}, {"room": "Dining", "net_area_sqm": 6},
                                                         {"room": "Bedroom", "net_area_sqm": 7}],
                                   "Adjacency_Rules": [{"room1": "Kitchen", "room2": "Dining", "Connectivity_C": 1, "Importance_W": 3}]})
    C, W, source = page.matrices_for(["Bedroom", "Dining", "Kitchen"], rules)
    assert source == "ai" and (C[1][2], W[1][2]) == (1, 3) and C[0][1] == 0
    assert page.matrices_for(["Bedroom", "Dining"], rules)[2] == "mismatch"
    assert page.matrices_for(["Bedroom", "Dining"], None)[2] == "default"


# ------------------------------------------------------------------- packed plan
@pytest.mark.parametrize("seed", range(5))
def test_treemap_tiles_the_site_exactly(seed):
    rng = random.Random(seed)
    items = [(f"r{i}", rng.uniform(0.5, 12)) for i in range(rng.randint(1, 8))]
    w, h = rng.uniform(2, 15), rng.uniform(2, 15)
    rects = page.generate_treemap(items, 0, 0, w, h)
    assert [r["room"] for r in rects] == [r for r, _ in items]
    assert sum(r["w"] * r["h"] for r in rects) == pytest.approx(w * h)
    total = sum(a for _, a in items)
    for (_, area), r in zip(items, rects):
        assert r["w"] * r["h"] == pytest.approx(w * h * area / total)             # area proportional to the request
        assert r["x"] >= -1e-9 and r["y"] >= -1e-9 and r["x"] + r["w"] <= w + 1e-9 and r["y"] + r["h"] <= h + 1e-9
    for i, a in enumerate(rects):                                                 # no two rooms overlap
        for b in rects[i + 1:]:
            assert min(a["x"] + a["w"], b["x"] + b["w"]) - max(a["x"], b["x"]) < 1e-9 \
                or min(a["y"] + a["h"], b["y"] + b["h"]) - max(a["y"], b["y"]) < 1e-9


def test_treemap_survives_zero_areas():
    rects = page.generate_treemap([("a", 0.0), ("b", 0.0), ("c", 0.0)], 0, 0, 6.0, 3.0)
    assert sum(r["w"] * r["h"] for r in rects) == pytest.approx(18.0)


def test_layout_seed_ignores_edge_order_and_orientation_and_is_frozen():
    edges = [("Kitchen", "Dining", 3), ("Bedroom", "Closet", 2)]
    shuffled = [("Closet", "Bedroom", 2), ("Dining", "Kitchen", 3)]
    assert page.layout_seed(ROOMS, edges) == page.layout_seed(ROOMS, shuffled)
    assert page.layout_seed(ROOMS, edges) != page.layout_seed(ROOMS, edges[:1])
    assert page.layout_seed(["A", "B"], [("A", "B", 3)]) == 3345218226   # frozen: changing it re-shuffles every saved plan


def test_packed_plan_is_identical_across_python_processes():
    """The page used hash() of strings as layout seed, so every restart re-shuffled the same plan."""
    code = (
        "import importlib.util, json, sys\n"
        f"spec = importlib.util.spec_from_file_location('design_probe', {str(PAGE)!r})\n"
        "m = importlib.util.module_from_spec(spec); sys.modules['design_probe'] = m; spec.loader.exec_module(m)\n"
        "print(json.dumps(m.build_plan(json.loads(sys.argv[1]), 8.0, 4.0)['rects']))\n")
    procs = [subprocess.Popen([sys.executable, "-c", code, json.dumps(PLAN_JSON)], stdout=subprocess.PIPE, text=True,
                              env={**os.environ, "PYTHONHASHSEED": seed}) for seed in ("1", "2", "3")]
    outputs = {p.communicate()[0] for p in procs}
    assert all(p.returncode == 0 for p in procs) and len(outputs) == 1


def test_build_plan_reports_wrong_input_in_plain_words():
    with pytest.raises(ValueError, match="กฎจาก AI"):
        page.build_plan({"Space_Requirement": [], "Adjacency_Rules": []}, 8, 4)
    with pytest.raises(ValueError, match="ไม่พบข้อมูลที่จำเป็น"):
        page.build_plan({"Adjacency": []}, 8, 4)
    with pytest.raises(ValueError, match="ว่างเปล่า"):
        page.build_plan({"Space_Requirement": [], "Adjacency": []}, 8, 4)
    with pytest.raises(ValueError):
        page.build_plan([], 8, 4)


def test_build_plan_scales_to_the_site_and_ignores_unknown_rooms():
    data = {"Space_Requirement": [{"room": "A", "net_area_sqm": 4}, {"room": "B", "net_area_sqm": 12}, {"room": "A", "net_area_sqm": 9}],
            "Adjacency": [{"room1": "A", "room2": "B", "score": 3}, {"room1": "A", "room2": "Ghost", "score": 3},
                          {"room1": "A", "room2": "A", "score": 3}, "junk"]}
    plan = page.build_plan(data, 8.0, 4.0, circ_pct=25)
    assert plan["rooms"] == ["A", "B"] and plan["edges"] == [("A", "B", 3)]
    assert plan["t_net"] == 16 and plan["t_gross"] == pytest.approx(20) and plan["scale"] == pytest.approx(32 / 20)
    assert plan["circ_col"] == "Circulation_25%" and plan["df"]["Gross_sqm"].tolist() == [5.0, 15.0]
    areas = {r["room"]: r["w"] * r["h"] for r in plan["rects"]}
    assert areas == {"A": pytest.approx(8.0), "B": pytest.approx(24.0)}              # 4:12 of the 32 m² site
    assert len(plan["warnings"]) == 1                                                  # the duplicate 'A'


def test_check_openings_flags_what_the_prompt_forbids():
    rects = [{"room": "Bed", "x": 0, "y": 0, "w": 3.0, "h": 2.0}]
    furniture = [{"id": "F1", "room": "Bed", "type": "bed", "w_m": 2.0, "d_m": 1.6, "x_m": 1.5, "y_m": 0.0},      # sticks out east
                 {"id": "F2", "room": "Bed", "type": "desk", "w_m": 1.0, "d_m": 0.5, "x_m": 0.0, "y_m": 0.0},
                 {"id": "F3", "room": "Nowhere", "type": "x", "w_m": 99, "d_m": 99}]                          # not in plan: not judged
    openings = [{"id": "D1", "type": "door", "width_m": 0.7}, {"id": "W1", "type": "window", "width_m": 0.5},
                {"id": "D2", "type": "door", "width_m": 0.9}]
    warnings = page.check_openings(rects, openings, furniture)
    assert len(warnings) == 3 and "F1" in warnings[0] and "D1" in warnings[1] and "W1" in warnings[2]
    assert page.check_openings(rects, [{"type": "door", "width_m": "wide"}], [{"room": "Bed", "x_m": "?", "w_m": None}])   # junk values: no crash


def test_figures_stay_small():
    plan = page.build_plan(PLAN_JSON, 8.0, 4.0)
    plain, rich = page.floorplan_fig(plan, overlay=False), page.floorplan_fig(plan, overlay=True)
    assert len(plain.data) == 1 and len(rich.data) <= 5                                # was 2 traces per adjacency link
    assert len(rich.layout.shapes) == len(plan["rooms"]) + 1
    assert len(page.network_fig(plan).data) <= len(page.EDGE_STYLE) + 1
    fig, skipped = page.openings_fig(plan, [{"id": "D1", "room": "Ghost"}, {"id": "D2", "room": plan["rooms"][0], "wall": "east"}],
                                     [{"id": "F1", "room": "Ghost"}, {"id": "F2", "room": plan["rooms"][0], "w_m": 1, "d_m": 1, "clearance_m": 0.5}])
    assert skipped == ["D1", "F1"] and len(fig.data) == 1


def test_engine_to_plan_roundtrip_for_every_rank():
    res, plans = engine_plan(seed=7)
    assert len(plans) == len(res["ranked"]) == 5 and len(set(plans)) == 5
    for rank, text in enumerate(plans, 1):
        plan = page.build_plan(json.loads(text), 8.0, 4.0)
        assert f"Rank #{rank}" in plan["concept"] and plan["rooms"] == ROOMS
        assert sum(r["w"] * r["h"] for r in plan["rects"]) == pytest.approx(32.0)


# ------------------------------------------------------------------- Streamlit flow
def _app():
    import design_page_test
    design_page_test.main()


def _open():
    from streamlit.testing.v1 import AppTest
    return AppTest.from_function(_app, default_timeout=30).run()


def _click(at, label):
    next(b for b in at.button if label in b.label).click().run()
    assert not at.exception
    return at


def _sent():
    at = _open()
    assert not at.exception
    _click(at, "Execute Graph Generation")
    return _click(at, "ส่ง Top-K")


def test_flow_from_rules_to_ranked_plans_and_back():
    at = _sent()
    assert len(at.session_state["plans"]) == 5 and at.session_state["rank"] == 0
    assert len(at.get("plotly_chart")) == 3 and not at.error
    _click(at, "Next")
    _click(at, "Next")
    assert at.session_state["rank"] == 2
    assert next(b for b in at.button if "Next" in b.label).disabled is False
    while at.session_state["rank"] > 0:
        _click(at, "Previous")
    assert at.session_state["rank"] == 0 and next(b for b in at.button if "Previous" in b.label).disabled
    _click(at, "รีเซ็ตข้อมูลทั้งหมด")
    assert at.session_state["plans"] == [] and at.session_state["graph_results"] is None and not at.get("plotly_chart")


def test_a_fresh_page_explains_the_next_step():
    at = _open()
    assert not at.exception and not at.error and not at.get("plotly_chart")
    assert sum("ยังไม่มี" in i.value for i in at.info) == 2                          # Tab 2 and Tab 3 hints instead of empty tabs


def test_manual_sizing_feeds_prompt_a_and_the_engine():
    at = _open()
    at.radio[0].set_value(page.MANUAL_MODE).run()
    next(n for n in at.number_input if n.label == "Bedroom (ตร.ม.)").set_value(9.0).run()
    _click(at, "Generate AI Prompt")
    prompt = json.loads(next(c.value for c in at.code if '"system_prompt"' in c.value))
    assert {"room": "Bedroom", "net_area_sqm": 9.0} in prompt["user_input"]["space_areas"]
    _click(at, "Execute Graph Generation")
    assert {"room": "Bedroom", "net_area_sqm": 9.0} in at.session_state["graph_results"]["space_req"]


def test_seed_makes_a_click_reproducible_and_is_reported():
    at = _open()
    next(n for n in at.number_input if "Seed" in n.label).set_value(12345).run()
    _click(at, "Execute Graph Generation")
    first = at.session_state["graph_results"]
    _click(at, "Execute Graph Generation")
    assert at.session_state["graph_results"] == first and first["seed"] == 12345
    assert any("12345" in s.value for s in at.success)


def test_prompt_and_openings_view_stay_put_when_something_else_changes():
    at = _open()
    _click(at, "Generate AI Prompt")
    at.text_input[0].set_value("Another project").run()
    assert any('"system_prompt"' in c.value and "Another project" in c.value for c in at.code)   # followed the new input, did not vanish
    at = _sent()
    _click(at, "Visualize Openings")
    assert len(at.get("plotly_chart")) == 4
    at.toggle[0].set_value(False).run()
    assert not at.exception and len(at.get("plotly_chart")) == 4                     # any later rerun used to wipe it
    _click(at, "Next")
    assert len(at.get("plotly_chart")) == 4                                          # and it follows the new rank


def test_manual_trigger_keeps_the_ranked_plans_unless_the_json_was_changed():
    at = _sent()
    _click(at, "Manual Trigger")                                                     # the box still shows the active plan
    assert len(at.session_state["plans"]) == 5 and at.session_state["manual_plan"] is None
    box = at.text_area(key="manual_json")
    box.set_value(box.value + "\n").run()                                            # same JSON, one more newline
    _click(at, "Manual Trigger")
    assert at.session_state["plans"] == [] and at.session_state["manual_plan"]
    assert len(at.get("plotly_chart")) == 3 and not any("Next" in b.label for b in at.button)   # a pasted plan has no ◀/▶ bar


def test_pasting_a_fenced_ai_answer_loads_the_rules():
    rules = {"Space_Requirement": [{"room": r, "net_area_sqm": 5.0} for r in ROOMS],
             "Adjacency_Rules": [{"room1": "Kitchen", "room2": "Dining", "Connectivity_C": 1, "Importance_W": 3}],
             "Design_Concept": "AI concept"}
    at = _open()
    at.text_area(key="ai_json").set_value("Here you go\n```json\n" + json.dumps(rules) + "\n```").run()
    _click(at, "Load AI Rules")
    assert at.session_state["ai_rules"]["concept"] == "AI concept" and any("สำเร็จ" in s.value for s in at.success)
    _click(at, "Execute Graph Generation")
    assert at.session_state["graph_results"]["concept"] == "AI concept"
    assert {s["net_area_sqm"] for s in at.session_state["graph_results"]["space_req"]} == {5.0}


def test_bad_pastes_are_explained_not_crashes():
    at = _open()
    _click(at, "Load AI Rules")
    assert any("กรุณาวาง JSON" in w.value for w in at.warning)
    at.text_area(key="ai_json").set_value('{"nope": true}').run()
    _click(at, "Load AI Rules")
    assert any("Adjacency_Rules" in w.value for w in at.warning)
    at.text_area(key="manual_json").set_value("{broken").run()
    _click(at, "Manual Trigger")
    assert any("Expecting" in e.value for e in at.error) and not at.get("plotly_chart")
    at.text_area(key="manual_json").set_value(json.dumps({"Space_Requirement": [], "Adjacency_Rules": []})).run()
    _click(at, "Manual Trigger")
    assert any("กฎจาก AI" in e.value for e in at.error)


def test_manual_plan_with_awkward_numbers_still_renders():
    manual = {"Space_Requirement": [{"room": "A", "net_area_sqm": 0}, {"room": "B", "net_area_sqm": "x"}, {"room": "C", "net_area_sqm": 5}],
              "Adjacency": [{"room1": "A", "room2": "B", "score": "3"}, {"room1": "B", "room2": "C", "score": 2}], "Design_Concept": None}
    at = _open()
    assert at.text_area(key="manual_json").value == "{}"                              # the debug box starts as an empty object
    at.text_area(key="manual_json").set_value(json.dumps(manual)).run()
    _click(at, "Manual Trigger")
    assert not at.error and len(at.get("plotly_chart")) == 3
    assert sum("พื้นที่ไม่ถูกต้อง" in w.value for w in at.warning) == 2
    _click(at, "Visualize Openings")                                                  # the starter answer names rooms A / C
    assert len(at.get("plotly_chart")) == 4
