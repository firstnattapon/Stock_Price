"""Rent_Gradient_new_v2 — ledger of every function copied from the two source pages, state/stability guards.

The page is one file made of three zones (see its docstring): ENGINE (pure functions copied verbatim from
``Rent_Gradient.py`` / ``Rent_Gradient_new.py``), SHELL (state, stages, layers, panels, views) and these tests.
The ledger below is what stops the copy from drifting: every top-level name of the two source pages must exist
in v2 with the *same source* unless it is listed — with a reason — in ``MODIFIED`` or ``REPLACED``.
"""
import ast
import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest

pytest.importorskip("streamlit")
pytest.importorskip("folium")

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "pages" / "Rent_Gradient.py"
NEW = ROOT / "pages" / "Rent_Gradient_new.py"
PAGE = ROOT / "pages" / "Rent_Gradient_new_v2.py"


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


v2 = load(PAGE, "rent_gradient_new_v2_under_test")


# ----------------------------------------------------------------------------- ledger
def top_level(path):
    """``{name: normalised source}`` of every top-level def / class / assignment (decorators included)."""
    text = Path(path).read_text(encoding="utf-8")
    lines = text.splitlines()
    out = {}
    for node in ast.parse(text).body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            name = node.name
        elif isinstance(node, ast.Assign):
            name = ",".join(n.id for t in node.targets for n in ast.walk(t) if isinstance(n, ast.Name))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            name = node.target.id
        else:
            continue
        start = min([node.lineno] + [d.lineno for d in getattr(node, "decorator_list", [])])
        source = "\n".join(line.rstrip() for line in lines[start - 1:node.end_lineno])
        out[name] = re.sub(r", max_entries=\d+", "", source)      # a bound on a cache is the only decorator change
    return out


# Copied with edits. Each entry says why it differs; the test fails if a listed name is in fact identical
# (so the list cannot rot) and if an unlisted name differs (so nothing drifts silently).
MODIFIED = {
    "PAGE_CONFIG": "page title/icon of the merged page",
    "MAP_STYLES": "adds the black (depthmap) and dark basemaps used by the Space Syntax layer",
    "_OVERPASS_LOCK": "one lock per server process (cache_resource) — a module-level RLock is rebuilt on every rerun",
    "StateManager": "cached remote defaults, config guard, layer/Space Syntax keys",
    "SESSION_KEYS_TO_SAVE": "the three anchor-detail layer checkboxes (and the Space Syntax settings)",
    "_render_sidebar_network_panel": "the three layer checkboxes moved to the layers panel",
    "_render_sidebar_rent_panel": "the two layer checkboxes moved to the layers panel",
    "render_sidebar": "pipeline order ①→⑤, returns the intents as a dict (⑥ layers panel is drawn by main)",
    "render_map": "draws the registry layers from a Ctx instead of one 350-line function",
    "main": "stage table + Ctx + layers panel",
}
# Replaced by new SHELL code (the behaviour moved into the layer registry / panels / views).
REPLACED = {
    "_add_wms_layer": "→ _wms(): the three WMS overlays are registry rows that return the tile layer",
    "_add_map_legend": "→ legend_stack(): one box stacked from the legend section of every layer that is on",
    "_render_sidebar_map_settings": "→ _render_sidebar_layers_panel() + _render_sidebar_isochrone_settings()",
}

# Names that exist in more than one source page and are intentionally taken from the base page.
NEW_REPLACED = {}


def test_ledger_every_function_of_rent_gradient_py_is_in_v2_with_the_same_source():
    base, merged = top_level(BASE), top_level(PAGE)
    missing = [n for n in base if n not in merged and n not in REPLACED]
    assert not missing, f"dropped without a reason: {missing}"
    drifted = [n for n in base if n in merged and n not in MODIFIED and base[n] != merged[n]]
    assert not drifted, f"copied code changed (list it in MODIFIED with a reason or restore it): {drifted}"
    stale = [n for n in MODIFIED if base[n] == merged[n]]
    assert not stale, f"listed as modified but identical: {stale}"
    still_there = [n for n in REPLACED if n in merged and base[n] == merged[n]]
    assert not still_there, f"listed as replaced but still copied verbatim: {still_there}"


def test_v2_does_not_import_the_other_pages():
    text = PAGE.read_text(encoding="utf-8")
    assert "spec_from_file_location" not in text and "import_module" not in text and "runpy" not in text


# ----------------------------------------------------------------------------- state & stability guards
class FakeResponse:
    status_code = 200

    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return self.payload


def test_remote_defaults_are_fetched_once_per_ttl_not_once_per_session(monkeypatch):
    calls = []

    def fake_get(url, timeout):
        calls.append(url)
        return FakeResponse({"markers": [{"lat": 1.0, "lng": 2.0}], "travel_mode": "walk"})

    v2._remote_payload.clear()
    monkeypatch.setattr(v2.requests, "get", fake_get)
    defaults = dict(v2.StateManager._DEFAULTS)
    first = v2.StateManager._load_remote_defaults(defaults)
    second = v2.StateManager._load_remote_defaults(dict(v2.StateManager._DEFAULTS))
    assert first == second == [{"lat": 1.0, "lng": 2.0}] and defaults["travel_mode"] == "walk"
    assert len(calls) == 1
    v2._remote_payload.clear()


def test_a_failing_remote_fetch_is_not_retried_by_every_session(monkeypatch):
    calls = []

    def boom(url, timeout):
        calls.append(url)
        raise v2.requests.ConnectionError("offline")

    v2._remote_payload.clear()
    monkeypatch.setattr(v2.requests, "get", boom)
    assert v2.StateManager._load_remote_defaults(dict(v2.StateManager._DEFAULTS)) is None
    assert v2.StateManager._load_remote_defaults(dict(v2.StateManager._DEFAULTS)) is None
    assert len(calls) == 1
    v2._remote_payload.clear()


def test_overpass_lock_is_one_object_for_the_whole_process_even_though_streamlit_re_executes_the_module():
    first = v2._OVERPASS_LOCK
    try:
        again = load(PAGE, "rent_gradient_new_v2_under_test")  # what a Streamlit rerun does: same name, fresh module
        assert again is not v2 and again._OVERPASS_LOCK is first
    finally:
        sys.modules["rent_gradient_new_v2_under_test"] = v2
    assert hasattr(v2._OVERPASS_LOCK, "acquire") and hasattr(v2._OVERPASS_LOCK, "release")
    with v2._OVERPASS_LOCK:                      # re-entrant, as the downloader nests it
        with v2._OVERPASS_LOCK:
            pass


def test_every_cache_data_wrapper_is_bounded():
    text = PAGE.read_text(encoding="utf-8")
    decorators = re.findall(r"@st\.cache_data\((.*)\)\n", text)
    assert decorators and all("max_entries=" in d for d in decorators), decorators


def make_state(monkeypatch):
    state = dict(v2.StateManager._DEFAULTS)
    state["markers"] = []
    monkeypatch.setattr(v2.st, "session_state", state)
    return state


def test_import_config_ignores_values_of_the_wrong_type_and_keeps_the_good_ones(monkeypatch):
    state = make_state(monkeypatch)
    payload = {
        "markers": [{"lat": 20.2, "lng": 100.4, "active": True}],
        "settings": {
            "travel_mode": "walk",                   # good
            "show_traffic": "yes",                   # bool expected
            "anchor_radius_km": 500,                 # out of range
            "time_intervals": ["x"],                 # not minutes
            "map_style_name": "no such style",
            "rent_samples": [{"lat": 1, "lon": 2, "rent": "n/a"}],
            "colors": {"step1": 1},
            "anchor_use_evidence": True,             # good
        },
        "precomputed_results": {"network_data": ["not", "a", "dict"], "isochrone_data": None},
    }
    skipped = v2.StateManager.import_config(payload)
    assert state["travel_mode"] == "walk" and state["anchor_use_evidence"] is True
    assert state["markers"] == payload["markers"]
    assert state["show_traffic"] is False and state["anchor_radius_km"] == 10.0
    assert state["time_intervals"] == [5] and state["map_style_name"] == v2.StateManager._DEFAULTS["map_style_name"]
    assert state["network_data"] is None
    assert set(skipped) == {"show_traffic", "anchor_radius_km", "time_intervals", "map_style_name",
                            "rent_samples", "colors", "network_data"}
    assert state["_import_skipped"] == skipped
    assert v2.StateManager.import_config({"markers": "oops"}) == ["markers"]


def test_a_saved_config_still_round_trips(monkeypatch):
    state = make_state(monkeypatch)
    state.update(travel_mode="bicycle", show_golden_spots=False, rent_samples=[{"lat": 1.0, "lon": 2.0, "rent": 3.0}])
    exported = json.loads(v2.StateManager.export_config())
    state.update(travel_mode="drive", show_golden_spots=True, rent_samples=[])
    assert v2.StateManager.import_config(exported) == []
    assert state["travel_mode"] == "bicycle" and state["show_golden_spots"] is False
    assert state["rent_samples"] == [{"lat": 1.0, "lon": 2.0, "rent": 3.0}]


# ----------------------------------------------------------------------------- layers
from collections import OrderedDict  # noqa: E402

import folium  # noqa: E402
import networkx as nx  # noqa: E402
from pyproj.enums import TransformDirection  # noqa: E402

CENTER = (20.219443, 100.403630)
CONFIG = json.loads((ROOT / "Geoapify_Map" / "เชียงของ-cbd.json").read_text(encoding="utf-8"))
PRE = CONFIG["precomputed_results"]


def road_grid(size=11, spacing=100):
    graph = nx.MultiDiGraph(crs="EPSG:4326")
    projection = v2._anchor_projection(*CENTER)
    for x in range(size):
        for y in range(size):
            lon, lat = projection.transform((x - size // 2) * spacing, (y - size // 2) * spacing,
                                            direction=TransformDirection.INVERSE)
            graph.add_node(x * size + y, x=lon, y=lat)
            for dx, dy in ((-1, 0), (0, -1)):
                if x + dx >= 0 and y + dy >= 0:
                    other = (x + dx) * size + y + dy
                    graph.add_edge(x * size + y, other, length=float(spacing))
                    graph.add_edge(other, x * size + y, length=float(spacing))
    return graph


POLY = {"type": "Polygon", "coordinates": [[[100.40, 20.20], [100.41, 20.20], [100.41, 20.21], [100.40, 20.20]]]}
EVIDENCE = {
    "schema": v2.EVIDENCE_SCHEMA, "status": "ok",
    "evidence_anchor": {"lat": 20.2, "lon": 100.4, "score": 0.9, "coverage": 0.8,
                        "source": "Automated CBD Anchor — Evidence"},
    "confidence": {"level": "HIGH", "reasons": ["เหตุผล <b>x</b>"]},
    "plan": {"peak": {"rgb": [214, 40, 40], "name": "พาณิชยกรรม"}, "zones": [{"polygon": POLY, "area_km2": 1.2}]},
    "clusters": [{"rank": 1, "polygon": POLY, "score": 0.7, "area_ha": 12.0}],
}


def make_ctx(**overrides):
    fields = dict(
        markers=[], colors=dict(v2.StateManager._DEFAULTS["colors"]), iso=None, inter=None, net=None, rent=None,
        anchor=None, anchor_closeness=None, evidence=None,
        show={key: v2.StateManager._DEFAULTS.get(key) for key in v2.SHOW_KEYS}, center=CENTER, ss=None,
        cache=OrderedDict())
    fields.update(overrides)
    show = fields["show"]
    show.setdefault("map_style_name", next(iter(v2.MAP_STYLES)))
    return v2.Ctx(**fields)


GOLDEN = {"golden_spots": [{"lat": 20.21, "lon": 100.40, "score": 0.5}],
          "golden_spots_geojson": {"type": "FeatureCollection", "features": [{
              "type": "Feature", "geometry": {"type": "Point", "coordinates": [100.40, 20.21]},
              "properties": {"type": "golden_spot", "rank": 1, "score": 0.5}}]}}
CBD_ZONE = {"type": "FeatureCollection", "features": [{"type": "Feature", "geometry": POLY,
                                                       "properties": {"type": "cbd"}}]}


def rich_ctx(**show):
    """A context with every base layer's data present (Chiang Khong fixture + a synthetic road grid)."""
    iso, net = PRE["isochrone_data"], dict(PRE["network_data"], **GOLDEN)
    markers = CONFIG["markers"]
    found = v2.find_cbd_anchors(road_grid(), CENTER, 4000)
    rent = v2.compute_rent_gradient_data(None, net, iso, markers, [], "ดัชนี", automated_anchor=found["composite"])
    base_show = {key: v2.StateManager._DEFAULTS.get(key) for key in v2.SHOW_KEYS}
    base_show.update({key: True for key in v2.SHOW_KEYS if key.startswith("show_")})
    base_show.update(show)
    return make_ctx(iso=iso, inter=CBD_ZONE, net=net, rent=rent, markers=markers,
                    anchor=found["composite"], anchor_closeness=found["closeness"], evidence=EVIDENCE,
                    show=base_show)


def walk(element):
    for child in element._children.values():
        yield child
        yield from walk(child)


def layer_names(m):
    """Overlay layers that were added to the map (the base tile layer is not one of them)."""
    return [c.layer_name for c in m._children.values() if isinstance(c, folium.map.Layer) and c.overlay]


def test_layer_registry_is_consistent():
    ids = [layer.id for layer in v2.LAYERS]
    assert len(ids) == len(set(ids)) and all(layer.group in v2.PANEL_GROUPS for layer in v2.LAYERS)
    keys = [layer.show_key for layer in v2.LAYERS if layer.show_key]
    assert len(keys) == len(set(keys))
    assert all(k in v2.StateManager._DEFAULTS and k in v2.SESSION_KEYS_TO_SAVE for k in keys), keys
    assert all(callable(layer.draw) and callable(layer.available) for layer in v2.LAYERS)
    assert set(v2.SHOW_KEYS) >= set(keys) | {"cityplan_opacity", "map_style_name"}
    # tile overlays sit below every vector layer, markers on top
    order = [layer.id for layer in v2.LAYERS]
    assert order[:4] == ["traffic", "wms_population", "wms_cityplan", "wms_dol"] and order[-1] == "markers"


def test_the_registry_keeps_the_old_vector_stacking_order():
    order = [layer.id for layer in v2.LAYERS]
    old = ["rent_rings", "rent_heat", "betweenness", "closeness", "golden", "travel_areas", "cbd_zone", "railway"]
    assert [i for i in order if i in old] == old


def test_every_checkbox_that_existed_still_has_its_key_default_and_label():
    defaults = v2.StateManager._DEFAULTS
    assert defaults["show_golden_spots"] is True and defaults["show_rent_rings"] is True
    for key in ("show_traffic", "show_population", "show_cityplan", "show_dol", "show_railway", "show_betweenness",
                "show_closeness", "show_rent_nodes", "show_anchor_boundary", "show_evidence_zone",
                "show_evidence_clusters"):
        assert defaults[key] is False, key
    labels = {layer.show_key: layer.label for layer in v2.LAYERS if layer.show_key}
    assert labels["show_betweenness"] == "Show Roads (Betweenness)"
    assert labels["show_rent_nodes"] == "🔥 Rent Heat (โหนดถนน)"


def test_layers_draw_only_what_is_on_and_in_registry_order():
    ctx = rich_ctx()
    drawn_ids = [layer.id for layer in v2.render_layers(ctx, folium.Map())[0]]
    expected = [layer.id for layer in v2.LAYERS if layer.available(ctx)
                and (layer.show_key is None or ctx.show[layer.show_key])]
    assert drawn_ids == expected
    assert {"betweenness", "closeness", "golden", "rent_rings", "travel_areas", "cbd_zone", "railway", "top_node",
            "cbd_anchor", "markers"} <= set(drawn_ids) and drawn_ids[-1] == "markers"
    off = rich_ctx(show_betweenness=False, show_closeness=False, show_golden_spots=False)
    m = folium.Map()
    drawn, warnings = v2.render_layers(off, m)
    assert warnings == [] and not {"betweenness", "closeness", "golden"} & {layer.id for layer in drawn}
    assert "Road Betweenness" not in layer_names(m) and "Rent Gradient Rings" in layer_names(m)


def test_a_layer_without_data_is_skipped_and_a_broken_layer_only_adds_a_warning():
    empty = make_ctx()
    drawn, warnings = v2.render_layers(empty, folium.Map())
    assert drawn == [] and warnings == []

    def boom(_ctx):
        raise RuntimeError("layer exploded")

    layers = (
        v2.Layer("bad", "Bad layer", "บริบท & overlay", boom, lambda c: True),
        v2.Layer("good", "Good layer", "บริบท & overlay", lambda c: folium.FeatureGroup(name="Good layer"),
                 lambda c: True),
        v2.Layer("raises_in_available", "Worse", "บริบท & overlay", lambda c: None, lambda c: 1 / 0),
    )
    m = folium.Map()
    drawn, warnings = v2.render_layers(empty, m, layers)
    assert [layer.id for layer in drawn] == ["good"] and layer_names(m) == ["Good layer"]
    assert len(warnings) == 2 and "layer exploded" in warnings[0] and "ZeroDivisionError" in warnings[1]
    assert m.get_root().render()                      # the map still builds


def test_a_new_layer_is_one_function_and_one_row():
    marker = v2.Layer("extra", "Extra", "บริบท & overlay",
                      lambda c: folium.FeatureGroup(name="Extra"), lambda c: True, show_key="show_extra",
                      legend=lambda c: "<b>extra legend</b>")
    ctx = make_ctx(show={"show_extra": True})
    m = folium.Map()
    drawn, _ = v2.render_layers(ctx, m, (marker,))
    assert layer_names(m) == ["Extra"]
    assert "extra legend" in v2.legend_stack(ctx, drawn).box_html
    assert v2.render_layers(make_ctx(show={"show_extra": False}), folium.Map(), (marker,))[0] == []


def test_unticked_anchor_details_stay_on_the_layer_control_but_start_hidden():
    ctx = rich_ctx(show_anchor_boundary=False, show_evidence_zone=False, show_evidence_clusters=False)
    m = folium.Map()
    drawn, warnings = v2.render_layers(ctx, m)
    assert warnings == []
    hidden = {c.layer_name: c.show for c in m._children.values() if isinstance(c, folium.FeatureGroup)}
    assert hidden["Automated Anchor study boundary"] is False
    assert hidden["Peak colour zone (ผังสีสูงสุด)"] is False and hidden["Parcel clusters (แปลงถี่)"] is False
    assert not {"anchor_boundary", "evidence_zone", "evidence_clusters"} & {layer.id for layer in drawn}
    folium.LayerControl().add_to(m)
    html = m.get_root().render()
    assert "Automated Anchor study boundary" in html and "Peak colour zone" in html
    shown = rich_ctx(show_anchor_boundary=True)
    m2 = folium.Map()
    v2.render_layers(shown, m2)
    assert {c.layer_name: c.show for c in m2._children.values()
            if isinstance(c, folium.FeatureGroup)}["Automated Anchor study boundary"] is True


def test_anchor_markers_keep_their_colours_and_the_rent_anchor_only_shows_without_an_automated_one():
    ctx = rich_ctx()
    group = v2.draw_cbd_anchor(ctx)
    icons = sorted(m.icon.options["marker_color"] for m in walk(group)
                   if isinstance(m, folium.Marker) and m.icon is not None)
    assert icons == ["darkblue", "green", "purple"]
    only_rent = make_ctx(rent=ctx.rent)
    assert [m.icon.options["marker_color"] for m in walk(v2.draw_cbd_anchor(only_rent))
            if isinstance(m, folium.Marker) and m.icon is not None] == ["darkblue"]
    assert not v2.LAYERS[[layer.id for layer in v2.LAYERS].index("cbd_anchor")].available(make_ctx())


def test_text_that_comes_from_results_is_escaped_in_popups_and_tooltips():
    nasty = dict(EVIDENCE, confidence={"level": "<img src=x onerror=1>", "reasons": ["<script>alert(1)</script>"]})
    html = folium.Map()
    group = v2.draw_cbd_anchor(make_ctx(evidence=nasty))
    group.add_to(html)
    page_html = html.get_root().render()
    assert "<img src=x" not in page_html and "<script>alert(1)" not in page_html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page_html or "\\u0026lt;script" in page_html


def test_legend_sections_stack_in_rank_order_and_empty_ones_disappear():
    ctx = rich_ctx()
    drawn, _ = v2.render_layers(ctx, folium.Map())
    box = v2.legend_stack(ctx, drawn)
    html = box.box_html
    assert html.index("เวลาเดินทาง") < html.index("CBD Zone") < html.index("Golden Spot") < html.index("Rent Gradient")
    assert html.count("position:fixed") == 1                      # one box, not one per layer
    no_golden = rich_ctx()
    no_golden = v2.Ctx(**{**no_golden.__dict__, "net": dict(no_golden.net, golden_spots=[])})
    assert "Golden Spot" not in v2.legend_stack(no_golden, drawn).box_html
    assert v2.legend_stack(make_ctx(), []) is None


def test_compact_rows_are_lat_lon_pairs_rounded_to_a_metre_and_script_safe():
    feature = {"geometry": {"type": "LineString", "coordinates": [[100.4036301, 20.2194432], [100.4040001, 20.2200009]]},
               "properties": {"color": "#ff0000", "stroke_weight": 3.456, "betweenness": 0.123456}}
    rows = v2.line_rows([feature], "color", "stroke_weight", ("betweenness",))
    assert rows == [["#ff0000", 3.46, [0.123], [20.21944, 100.40363, 20.22, 100.404]]]
    multi = dict(feature, geometry={"type": "MultiLineString", "coordinates": [
        [[100.1, 20.1], [100.2, 20.2]], [[100.3, 20.3], [100.4, 20.4]]]})
    assert len(v2.line_rows([multi], "color", "stroke_weight")) == 2
    assert v2.line_rows([multi], "color", "stroke_weight")[0][2] == 0         # no tooltip values → 0 (falsy)
    point = {"geometry": {"type": "Point", "coordinates": [100.40363123, 20.21944321]},
             "properties": {"color": "#000000", "radius": 4.5, "closeness": 0.5}}
    assert v2.point_rows([point], "color", "radius", ("closeness",)) == [["#000000", "#000000", 4.5, [0.5], 20.21944, 100.40363]]
    assert v2.point_rows([{"geometry": {"type": "Point", "coordinates": []}, "properties": {}}], "color", 3) == []
    text = v2._json_js(["</script><!--   ถนน"])
    assert "</" not in text and "<!--" not in text and " " not in text and "ถนน" in text
    assert json.loads(text.replace("\\/", "/").replace("<\\!--", "<!--")) == ["</script><!--   ถนน"]


def test_compact_layers_render_into_the_map_script():
    group = folium.FeatureGroup(name="Road Betweenness")
    rows = v2._json_js([["#ff0000", 3.0, [0.1], [20.1, 100.1, 20.2, 100.2]]])
    v2.CompactLines(rows, heads=("Betweenness Score:",), opacity=0.8).add_to(group)
    v2.CompactPoints(v2._json_js([["#000", "#000", 4, [0.5], 20.1, 100.1]]), heads=("Integration Score:",)).add_to(group)
    m = folium.Map(prefer_canvas=True)
    group.add_to(m)
    html = m.get_root().render()
    assert "L.polyline" in html and "L.circleMarker" in html and '"Betweenness Score:"' in html
    assert "[[\"#ff0000\",3.0,[0.1],[20.1,100.1,20.2,100.2]]]" in html or '[["#ff0000",3.0' in html
    assert "preferCanvas" in html


def test_view_memory_is_keyed_by_the_centre_and_can_be_switched_off(monkeypatch):
    ctx = make_ctx()
    shown = []
    monkeypatch.setattr(v2, "st_folium", lambda m, **kw: shown.append(m) or {})
    monkeypatch.setattr(v2.st, "warning", lambda *a, **k: None)
    v2.render_map(ctx)
    html = shown[-1].get_root().render()
    assert "rgv2_view" in html and f'"{CENTER[0]:.5f},{CENTER[1]:.5f}"' in html
    monkeypatch.setattr(v2, "REMEMBER_VIEW", False)
    v2.render_map(ctx)
    assert "rgv2_view" not in shown[-1].get_root().render()


def test_the_base_map_uses_the_canvas_renderer_and_the_black_style_has_a_black_background():
    black = make_ctx(show={"map_style_name": "พื้นดำ (เหมือน depthmap)"})
    m = v2.build_base_map(black)
    html = m.get_root().render()
    assert "preferCanvas" in html and "background:#000" in html
    light = v2.build_base_map(make_ctx())
    assert "background:#000" not in light.get_root().render()


def test_render_map_asks_streamlit_folium_only_for_clicks_and_shows_layer_warnings(monkeypatch):
    calls, warned = [], []
    monkeypatch.setattr(v2, "st_folium", lambda m, **kw: calls.append(kw) or {"last_clicked": None})
    monkeypatch.setattr(v2.st, "warning", lambda text, *a, **k: warned.append(text))
    broken = v2.Layer("bad", "Bad", "บริบท & overlay", lambda c: 1 / 0, lambda c: True)
    monkeypatch.setattr(v2, "LAYERS", (broken,) + tuple(v2.LAYERS))
    out = v2.render_map(make_ctx())
    assert out == {"last_clicked": None} and calls[0]["returned_objects"] == ["last_clicked"]
    assert calls[0]["key"] == "main_map" and any("Bad" in w and "ZeroDivisionError" in w for w in warned)


def test_lru_reuses_an_entry_only_for_the_same_source_object():
    store, built = OrderedDict(), []
    source_a, source_b = {"a": 1}, {"a": 1}

    def build(tag):
        built.append(tag)
        return tag

    assert v2.lru_get(store, "k", source_a, lambda: build("a1")) == "a1"
    assert v2.lru_get(store, "k", source_a, lambda: build("a2")) == "a1"          # hit
    assert v2.lru_get(store, "k", source_b, lambda: build("b1")) == "b1"          # equal but not the same object
    for i in range(10):
        v2.lru_get(store, ("x", i), None, lambda i=i: build(i), limit=4)
    assert len(store) == 4 and "k" not in store and built[:2] == ["a1", "b1"]


def test_heavy_layer_rows_are_built_once_per_result_not_once_per_rerun(monkeypatch):
    ctx = rich_ctx()
    calls = []
    real = v2.line_rows
    monkeypatch.setattr(v2, "line_rows", lambda *a, **k: calls.append(1) or real(*a, **k))
    for _ in range(4):
        v2.draw_betweenness(ctx)
    assert len(calls) == 1
    fresh = dict(ctx.net, edges=json.loads(json.dumps(ctx.net["edges"])))   # a new analysis = a new result object
    v2.draw_betweenness(make_ctx(net=fresh, cache=ctx.cache))
    assert len(calls) == 2


def test_the_network_layers_carry_every_feature_of_the_saved_result():
    ctx = rich_ctx()
    v2.draw_betweenness(ctx)
    rows = json.loads(v2.lru_get(ctx.cache, ("rows", "betweenness", id(ctx.net["edges"])), ctx.net["edges"], lambda: None))
    assert len(rows) == len(ctx.net["edges"]["features"])
    assert all(len(r) == 4 and len(r[3]) % 2 == 0 and len(r[3]) >= 4 for r in rows)
    group = v2.draw_closeness(ctx)
    nodes = json.loads(v2.lru_get(ctx.cache, ("rows", "closeness", id(ctx.net["nodes"])), ctx.net["nodes"], lambda: None))
    assert len(nodes) == len(ctx.net["nodes"]["features"]) and isinstance(group, folium.FeatureGroup)
