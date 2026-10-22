"""Rent_Gradient_new_v2 — ledger of every function copied from the two source pages, state/stability guards.

The page is one file made of three zones (see its docstring): ENGINE (pure functions copied verbatim from
``Rent_Gradient.py`` / ``Rent_Gradient_new.py``), SHELL (state, stages, layers, panels, views) and these tests.
The ledger below is what stops the copy from drifting: every top-level name of the two source pages must exist
in v2 with the *same source* unless it is listed — with a reason — in ``MODIFIED`` or ``REPLACED``.
"""
import ast
import copy
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
    "DEFAULT_CONFIG": "the default map centre (LAT / LON) of the merged page was moved",
    "MAP_STYLES": "adds the black (depthmap) and Esri dark basemaps for the Space Syntax layer, five more keyless "
                  "styles (Google roadmap/terrain/satellite, Esri street/topo) and max_native_zoom / labels",
    "_OVERPASS_LOCK": "one lock per server process (cache_resource) — a module-level RLock is rebuilt on every rerun",
    "StateManager": "cached remote defaults, config guard, layer/Space Syntax keys; no click-debounce state",
    "NETWORK_CONFIG": "the two click-debounce keys are gone (the map no longer adds pins)",
    "SESSION_KEYS_TO_SAVE": "the three anchor-detail layer checkboxes (and the Space Syntax settings)",
    "_render_sidebar_marker_input": "the only place a pin is entered: range-checked like the anchor centre, says where to read coordinates",
    "_render_sidebar_marker_list": "pin label readable on white and on black (CSS names such as black / pink were not)",
    "_render_sidebar_network_panel": "the three layer checkboxes moved to the layers panel",
    "_render_sidebar_rent_panel": "the two layer checkboxes moved to the layers panel",
    "render_sidebar": "pipeline order (… Space Syntax before Rent), returns the intents as a dict",
    "render_header": "one extra caption line about the Space Syntax layer",
    "render_map": "draws the registry layers from a Ctx instead of one 350-line function",
    "main": "stage table + Ctx + layers panel",
}
# Replaced by new SHELL code (the behaviour moved into the layer registry / panels / views).
REPLACED = {
    "should_add_marker": "the map no longer adds pins on click — Active Markers are entered in the sidebar only",
    "handle_map_click": "same: the map sends nothing back (st_folium returned_objects=[]), so a click is not an event",
    "_add_wms_layer": "→ _wms(): the three WMS overlays are registry rows that return the tile layer",
    "_add_map_legend": "→ legend_stack(): one box stacked from the legend section of every layer that is on",
    "_render_sidebar_map_settings": "→ _render_sidebar_layers_panel() + _render_sidebar_isochrone_settings()",
    "render_analytics_panel": "→ VIEWS + render_views(): st.tabs runs every tab on every rerun, a radio runs one",
}

# Rent_Gradient_new.py: copied with edits / not copied (and why). Everything else must be identical.
NEW_MODIFIED = {
    "fetch_graph": "calls this page's own _fetch_osm_graph (no cross-page import, no plain-osmnx fallback)",
    "load_bundled_graph": "reads the zip through this page's _load_graph_bytes / MAX_CACHE_ENTRY_BYTES",
}
NEW_REPLACED = {
    "PAGE_CONFIG": "the merged page has its own (Rent_Gradient.py's, retitled)",
    "MAP_STYLES": "the black/dark basemaps (and Esri Light Gray's zoom limit) were added to Rent_Gradient.py's MAP_STYLES",
    "_node_sort_key": "identical code, only the docstring differs — Rent_Gradient.py's copy is used",
    "DEFAULT_LAT": "the study centre is anchor_lat / anchor_lon (shared with the CBD-anchor search)",
    "DEFAULT_LON": "the study centre is anchor_lat / anchor_lon (shared with the CBD-anchor search)",
    "STUDY_BUFFER_RATIO": "ANCHOR_CONFIG['buffer_ratio'] (the same 20 %) is used by anchor_study_polygon",
    "BASE_PAGE_MODULE": "no cross-page import any more",
    "VIEW_LABELS": "→ SS_VIEW_LABELS (the map view is now the layer on the shared map)",
    "K_NET,K_META,K_RESULT": "→ SS_NET / SS_META / SS_RESULT (prefix ss_, no clash with the standalone page)",
    "K_AUTORUN": "one button loads and analyses, no autorun flag",
    "_base_page": "no cross-page import any more",
    "base_anchor": "→ rent_anchor_point() (reads StateManager)",
    "legend_html": "→ legend_space_syntax() + LegendBox (one legend box for all layers)",
    "build_map": "→ draw_space_syntax() (a layer on the shared map)",
    "_header": "→ render_header()",
    "_store_network": "→ _ss_load_network()",
    "_sidebar_study_area": "→ the study centre is the CBD-anchor panel's; radius/network type are in the Space Syntax panel",
    "_sidebar_analysis": "→ _render_sidebar_space_syntax_panel() (the Space Syntax panel)",
    "_sidebar_style": "→ _options_space_syntax() (display options under the layer checkbox in the layers panel)",
    "_run_analysis": "→ perform_space_syntax()",
    "_render_results": "→ view_space_syntax()",
    "main": "→ main() of the merged page",
}


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


def test_ledger_every_function_of_rent_gradient_new_py_is_in_v2_with_the_same_source():
    source, merged = top_level(NEW), top_level(PAGE)
    missing = [n for n in source if n not in merged and n not in NEW_REPLACED]
    assert not missing, f"dropped without a reason: {missing}"
    drifted = [n for n in source if n in merged and n not in NEW_REPLACED and n not in NEW_MODIFIED
               and source[n] != merged[n]]
    assert not drifted, f"copied code changed: {drifted}"
    stale = [n for n in NEW_MODIFIED if source[n] == merged[n]]
    assert not stale, f"listed as modified but identical: {stale}"
    assert all(n in source for n in list(NEW_MODIFIED) + list(NEW_REPLACED)), "ledger names a function that is not in the source page"
    assert [n for n in NEW_REPLACED if n in merged and source[n] == merged[n] and n != "_node_sort_key"] == []


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


def tile_layers(m):
    return [c for c in m._children.values() if isinstance(c, folium.TileLayer)]


@pytest.mark.parametrize("name", list(v2.MAP_STYLES))
def test_every_map_style_builds_its_tiles_and_labels_under_the_data_layers(name):
    style = v2.MAP_STYLES[name]
    m = v2.build_base_map(make_ctx(show={"map_style_name": name}))
    html = m.get_root().render()
    tiles = tile_layers(m)
    assert len(tiles) == (style["tiles"] is not None) + bool(style.get("labels"))
    if tiles:
        assert tiles[0].layer_name == name and tiles[0].control      # the LayerControl names the style, not a URL
        assert all(t.options["max_native_zoom"] == (style.get("max_native_zoom") or t.options["max_zoom"]) for t in tiles)
    if style.get("labels"):
        assert tiles[1].tiles == style["labels"] and not tiles[1].control
    if style.get("max_native_zoom"):
        assert f'"maxNativeZoom": {style["max_native_zoom"]}' in html
    assert layer_names(m) == []                                      # the basemap is not one of the data layers


def test_no_map_style_needs_an_api_key_and_the_carto_style_is_renamed():
    assert not any("cartocdn" in str(style) for style in v2.MAP_STYLES.values())
    assert not set(v2.LEGACY_MAP_STYLES) & set(v2.MAP_STYLES)
    assert all(name in v2.MAP_STYLES for name in v2.LEGACY_MAP_STYLES.values())
    assert v2.LEGACY_MAP_STYLES["Dark (CARTO)"] == "Dark (Esri Dark Gray)"
    assert v2.MAP_STYLES["Dark (Esri Dark Gray)"]["labels"]                # CARTO dark_all had place names too


def test_a_config_saved_with_the_carto_style_opens_on_its_replacement(monkeypatch):
    state = make_state(monkeypatch)
    assert v2.StateManager.import_config({"settings": {"map_style_name": "Dark (CARTO)"}}) == []
    assert state["map_style_name"] == "Dark (Esri Dark Gray)"


def test_render_map_asks_streamlit_folium_for_nothing_and_shows_layer_warnings(monkeypatch):
    calls, warned = [], []
    monkeypatch.setattr(v2, "st_folium", lambda m, **kw: calls.append(kw) or {})
    monkeypatch.setattr(v2.st, "warning", lambda text, *a, **k: warned.append(text))
    broken = v2.Layer("bad", "Bad", "บริบท & overlay", lambda c: 1 / 0, lambda c: True)
    monkeypatch.setattr(v2, "LAYERS", (broken,) + tuple(v2.LAYERS))
    assert v2.render_map(make_ctx()) is None
    assert calls[0]["returned_objects"] == []              # nothing comes back: a click / pan / zoom is not a rerun
    assert calls[0]["key"] == "main_map" and any("Bad" in w and "ZeroDivisionError" in w for w in warned)


def test_the_map_cannot_add_a_pin_and_the_click_machinery_is_gone():
    text = PAGE.read_text(encoding="utf-8")
    assert "last_clicked" not in text and "click_debounce" not in text
    for name in ("handle_map_click", "should_add_marker"):
        assert not hasattr(v2, name), name
    assert not hasattr(v2.StateManager, "record_click") and not hasattr(v2.StateManager, "get_last_click")
    assert "last_processed_click" not in v2.StateManager._DEFAULTS
    adders = {fn.name for fn in ast.parse(text).body if isinstance(fn, ast.FunctionDef)
              and any(isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "add_marker"
                      for n in ast.walk(fn))}
    # the typed coordinates, the two "add this point" buttons of the Network panel, the Golden Spots table button —
    # explicit commands only; neither main() nor render_map() (nor anything fed by the map) adds a pin
    assert adders == {"_render_sidebar_marker_input", "_render_sidebar_network_panel", "view_gold"}


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


# ----------------------------------------------------------------------------- Space Syntax as a layer
import contextlib  # noqa: E402

import numpy as np  # noqa: E402

sys.path.insert(0, str(ROOT / "tests"))
import test_rent_gradient_new as helpers  # noqa: E402  (street-network builders + the standalone Space Syntax page)

rgn = helpers.rgn


class Recorder:
    """Stands in for the Streamlit status widgets so the stage can run without a script runner."""

    def __init__(self):
        self.errors, self.toasts = [], []

    def install(self, monkeypatch):
        monkeypatch.setattr(v2.st, "spinner", lambda *a, **k: contextlib.nullcontext())
        monkeypatch.setattr(v2.st, "error", lambda text, *a, **k: self.errors.append(text))
        monkeypatch.setattr(v2.st, "toast", lambda text, *a, **k: self.toasts.append(text))
        monkeypatch.setattr(v2.st, "progress", lambda *a, **k: type("Bar", (), {
            "progress": staticmethod(lambda *x, **y: None), "empty": staticmethod(lambda: None)})())
        return self


def ss_session(monkeypatch, **extra):
    state = make_state(monkeypatch)
    state.update(extra)
    return state, Recorder().install(monkeypatch)


def stage(**override):
    intents = {"ss_params": v2.ss_params(), "demo": False}
    intents.update(override)
    v2.perform_space_syntax(intents)


def count_calls(monkeypatch, module, name):
    calls = []
    real = getattr(module, name)
    monkeypatch.setattr(module, name, lambda *a, **k: calls.append(1) or real(*a, **k))
    return calls


def test_the_engine_gives_exactly_the_numbers_of_the_standalone_space_syntax_page():
    graph = helpers.random_street_graph(5)
    for kind in ("angular", "topological", "metric"):
        old_net = rgn.build_segment_network(graph)
        new_net = v2.build_segment_network(graph)
        old = rgn.analyse_network(old_net, kind=kind, radii=(400.0, None), with_choice=True)
        new = v2.analyse_network(new_net, kind=kind, radii=(400.0, None), with_choice=True)
        for key in old.integration:
            assert np.array_equal(old.integration[key], new.integration[key], equal_nan=True), (kind, key)
            assert np.array_equal(old.choice_norm[key], new.choice_norm[key], equal_nan=True), (kind, key)
            assert np.array_equal(old.nc[key], new.nc[key]) and np.array_equal(old.td[key], new.td[key])
    assert np.array_equal(rgn.gradient_rgb([0, 0.3, 1.0]), v2.gradient_rgb([0, 0.3, 1.0]))


def test_one_button_loads_the_network_once_and_parameter_changes_only_re_analyse(monkeypatch):
    state, ui = ss_session(monkeypatch)
    graph = helpers.grid_graph(6)
    fetched = []
    monkeypatch.setattr(v2, "_fetch_osm_graph", lambda wkt, network_type: fetched.append((wkt, network_type))
                        or (graph, True, None))
    built, analysed = count_calls(monkeypatch, v2, "build_segment_network"), count_calls(monkeypatch, v2, "analyse_network")
    stage()
    assert ui.errors == [] and len(fetched) == len(built) == len(analysed) == 1
    assert fetched[0][1] == "drive" and state[v2.SS_RUN] == 1 and state[v2.SS_RESULT].kind == "angular"
    assert state[v2.SS_META]["radius_m"] == 3000.0 and state[v2.SS_MASK].shape == (state[v2.SS_NET].n_segments,)
    state["ss_kind"] = "metric"                                     # settings only: no download, no rebuild
    stage()
    assert len(fetched) == len(built) == 1 and len(analysed) == 2
    assert state[v2.SS_RESULT].kind == "metric" and state[v2.SS_RUN] == 2
    state["anchor_lat"] = state["anchor_lat"] + 0.01                # a different study area: a new network
    stage()
    assert len(fetched) == len(built) == 2
    state["ss_network"] = "walk"
    stage()
    assert len(fetched) == 3 and fetched[-1][1] == "walk"


def test_the_study_area_is_the_same_polygon_as_the_cbd_anchor_search(monkeypatch):
    state, _ = ss_session(monkeypatch)
    seen = []
    monkeypatch.setattr(v2, "_fetch_osm_graph", lambda wkt, nt: seen.append(wkt) or (helpers.chain(3), True, None))
    stage()
    expected = v2.anchor_study_polygon(state["anchor_lat"], state["anchor_lon"], 3000.0).wkt
    assert seen == [expected]


def test_failures_become_a_message_and_leave_the_previous_result_alone(monkeypatch):
    state, ui = ss_session(monkeypatch)
    monkeypatch.setattr(v2, "_fetch_osm_graph", lambda wkt, nt: (helpers.grid_graph(5), True, None))
    stage()
    kept = state[v2.SS_RESULT]
    monkeypatch.setattr(v2, "_fetch_osm_graph", lambda wkt, nt: (None, False, "OSM unavailable"))
    state["ss_radius_m"] = 5000                                     # new area → needs a download that now fails
    stage()
    assert any("OSM unavailable" in e for e in ui.errors) and state[v2.SS_RESULT] is kept
    ui.errors.clear()
    stage(ss_params={**v2.ss_params(), "radii": []})
    assert ui.errors == ["เลือกรัศมีอย่างน้อย 1 ค่า"]


def test_fetch_graph_reports_exceptions_instead_of_raising(monkeypatch):
    monkeypatch.setattr(v2, "_fetch_osm_graph", lambda *a: (_ for _ in ()).throw(RuntimeError("no route to host")))
    graph, source, error = v2.fetch_graph(*CENTER, 3000.0, "drive")
    assert graph is None and source == "" and "no route to host" in error
    monkeypatch.setattr(v2, "_fetch_osm_graph", lambda *a: (None, False, "no data"))
    assert v2.fetch_graph(*CENTER, 3000.0, "drive") == (None, "", "no data")
    graph = helpers.chain(2)
    graph.graph["osm_source"] = "cache"
    monkeypatch.setattr(v2, "_fetch_osm_graph", lambda *a: (graph, True, None))
    assert "cache" in v2.fetch_graph(*CENTER, 3000.0, "all")[1]


@pytest.fixture(scope="module")
def bundled():
    if not v2.BUNDLED_CACHE_ZIP.exists():
        pytest.skip("Geoapify_Map/osmnx_cache.zip is not available")
    graph, source, error = v2.load_bundled_graph()
    assert error is None, error
    return graph, source


def test_bundled_graph_loads_through_the_allow_list_unpickler(bundled):
    graph, source = bundled
    assert len(graph) == 1648 and "เชียงของ" in source


def test_bundled_graph_loader_skips_oversized_entries_and_rejects_a_hostile_pickle(tmp_path, monkeypatch):
    import pickle
    import zipfile

    archive = tmp_path / "osmnx_cache.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("osm_graph_big.pkl", pickle.dumps(list(range(100))))
    monkeypatch.setattr(v2, "BUNDLED_CACHE_ZIP", archive)
    loaded = []
    monkeypatch.setattr(v2, "MAX_CACHE_ENTRY_BYTES", 10)
    monkeypatch.setattr(v2, "_load_graph_bytes", lambda data: loaded.append(len(data)))
    graph, _, error = v2.load_bundled_graph()
    assert graph is None and error and loaded == []                  # never even read into memory

    class Evil:
        def __reduce__(self):
            return (exec, ("import sys; sys._rgv2_pwned = True",))

    monkeypatch.undo()
    evil = tmp_path / "evil.zip"
    with zipfile.ZipFile(evil, "w") as zf:
        zf.writestr("osm_graph_evil.pkl", pickle.dumps(Evil()))
    monkeypatch.setattr(v2, "BUNDLED_CACHE_ZIP", evil)
    graph, _, error = v2.load_bundled_graph()
    assert graph is None and error and not hasattr(sys, "_rgv2_pwned")
    monkeypatch.setattr(v2, "BUNDLED_CACHE_ZIP", tmp_path / "missing.zip")
    assert v2.load_bundled_graph()[2].startswith("ไม่พบไฟล์")


def test_demo_button_path_uses_the_bundled_graph_and_marks_the_network_as_the_demo(monkeypatch, bundled):
    state, ui = ss_session(monkeypatch)
    monkeypatch.setattr(v2, "load_bundled_graph", lambda: bundled[0:1] + (bundled[1], None))
    monkeypatch.setattr(v2, "_fetch_osm_graph", lambda *a: pytest.fail("the demo must not download anything"))
    stage(demo=True, ss_params={**v2.ss_params(), "radii": [800.0], "with_choice": False})
    assert ui.errors == [] and state[v2.SS_KEY] == ("demo",) and state[v2.SS_META]["radius_m"] is None
    assert state[v2.SS_RESULT].radii == [800.0] and state[v2.SS_NET].n_segments > 500


def test_clear_results_and_reset_forget_the_space_syntax_result(monkeypatch):
    state, _ = ss_session(monkeypatch)
    monkeypatch.setattr(v2, "_fetch_osm_graph", lambda *a: (helpers.grid_graph(5), True, None))
    stage()
    assert all(key in state for key in v2.SS_STATE_KEYS)
    v2.StateManager.clear_results(["rent"])                          # other stages leave it alone
    assert state[v2.SS_RESULT] is not None
    v2.StateManager.clear_results(["isochrone", "intersection", "rent"])
    assert state[v2.SS_RESULT] is not None
    v2.StateManager.reset()
    assert not any(key in state for key in v2.SS_STATE_KEYS)
    v2.StateManager.clear_results()                                  # nothing there: still fine


def test_space_syntax_settings_survive_a_config_round_trip_but_the_result_stays_out_of_it(monkeypatch):
    state, _ = ss_session(monkeypatch)
    monkeypatch.setattr(v2, "_fetch_osm_graph", lambda *a: (helpers.grid_graph(5), True, None))
    stage()
    state.update(ss_kind="metric", ss_radii=["400 m"], ss_palette=next(reversed(v2.PALETTES)), show_space_syntax=False)
    exported = json.loads(v2.StateManager.export_config())
    assert exported["settings"]["ss_kind"] == "metric" and exported["settings"]["show_space_syntax"] is False
    assert "ss_result" not in json.dumps(exported) and not any(key in exported["precomputed_results"] for key in v2.SS_STATE_KEYS)
    state.update(ss_kind="angular", ss_radii=["800 m"], show_space_syntax=True)
    assert v2.StateManager.import_config(exported) == []
    assert state["ss_kind"] == "metric" and state["ss_radii"] == ["400 m"] and state["show_space_syntax"] is False
    bad = {"settings": {"ss_kind": "euclid", "ss_radii": ["7 m"], "ss_radius_m": 99999, "ss_palette": "nope"}}
    assert set(v2.StateManager.import_config(bad)) == {"ss_kind", "ss_radii", "ss_radius_m", "ss_palette"}


def test_widgets_that_are_sometimes_hidden_keep_their_value(monkeypatch):
    state = make_state(monkeypatch)
    state["ss_palette"] = next(reversed(v2.PALETTES))
    v2.StateManager.initialize()
    assert state["ss_palette"] == next(reversed(v2.PALETTES))
    assert {"ss_palette", "ss_scale", "ss_thick", "ss_topn", "cityplan_opacity"} <= set(v2.KEEP_ALIVE_KEYS)


def ss_ctx(graph=None, **show):
    graph = graph or helpers.grid_graph(8)
    net = v2.build_segment_network(graph)
    result = v2.analyse_network(net, radii=(300.0, None), with_choice=True)
    meta = {"source": "test", "lat": helpers.LAT0, "lon": helpers.LON0, "radius_m": 600.0, "network": "drive"}
    merged = {"ss_palette": v2.DEFAULT_PALETTE, "ss_scale": "linear", "ss_thick": True, "ss_topn": 3}
    merged.update(show)
    base = make_ctx(show={**{key: v2.StateManager._DEFAULTS.get(key) for key in v2.SHOW_KEYS}, **merged})
    mask = v2._display_mask(net, meta)
    view = v2.SpaceSyntaxView(net=net, meta=meta, result=result, mask=mask,
                              display=v2.ss_display(base.show, result))
    return v2.Ctx(**{**base.__dict__, "ss": view})


def test_display_options_fall_back_when_they_no_longer_fit_the_result():
    ctx = ss_ctx(ss_measure="choice", ss_view_radius="300", ss_palette="nope", ss_scale="log", ss_topn=None)
    d = ctx.ss.display
    assert d["measure"] == "choice" and d["rkey"] == "300" and d["palette"] == v2.DEFAULT_PALETTE
    assert d["scale"] == "linear" and d["top_n"] == v2.ANALYSIS_CONFIG["top_n"]
    gone = ss_ctx(ss_measure="choice", ss_view_radius="1600").ss.display
    assert gone["rkey"] == "n"
    result = v2.analyse_network(v2.build_segment_network(helpers.chain(4)), radii=(None,), with_choice=False)
    assert v2.ss_display({"ss_measure": "choice"}, result)["measure"] == "integration"


def test_the_space_syntax_layer_draws_every_shown_segment_the_circle_and_the_top_pins():
    ctx = ss_ctx()
    group = v2.draw_space_syntax(ctx)
    kinds = [type(child).__name__ for child in walk(group)]
    assert kinds.count("CompactLines") == 1 and kinds.count("Circle") == 1 and kinds.count("Marker") == 3
    rows = json.loads(v2.ss_payload(ctx)["rows_json"])
    assert len(rows) == int(ctx.ss.mask.sum()) and all(len(r[3]) >= 4 for r in rows)
    assert rows[0][2][1] == pytest.approx(v2.ss_payload(ctx)["columns"]["score"][np.flatnonzero(ctx.ss.mask)[0]])
    m = folium.Map(prefer_canvas=True)
    drawn, warnings = v2.render_layers(make_ctx(**{**ctx.__dict__, "show": {**ctx.show, "show_space_syntax": True}}), m)
    assert warnings == [] and "space_syntax" in {layer.id for layer in drawn}
    html = m.get_root().render()
    assert "L.polyline" in html and "คะแนน (0–100):" in html


def test_street_names_from_osm_are_escaped_in_the_map_rows_and_pins():
    graph = helpers.chain(3)
    for _, _, data in graph.edges(data=True):
        data["name"] = "<img src=x onerror=alert(1)>"
    ctx = ss_ctx(graph, ss_topn=2)
    page = folium.Map()
    v2.draw_space_syntax(ctx).add_to(page)
    html = page.get_root().render()
    assert "<img src=x" not in html                                       # never raw …
    assert "&lt;img src=x onerror=alert(1)&gt;" in html                   # … only as text in the tooltip rows
    assert "&lt;img src=x" in v2.ss_payload(ctx)["rows_json"] and "<img" not in v2.ss_payload(ctx)["rows_json"]


def test_changing_only_the_display_rebuilds_one_payload_and_everything_else_is_cached(monkeypatch):
    ctx = ss_ctx()
    calls = count_calls(monkeypatch, v2, "scale_scores")
    for _ in range(3):
        v2.draw_space_syntax(ctx)
        v2.legend_space_syntax(ctx)
    assert len(calls) == 1
    other = v2.Ctx(**{**ctx.__dict__, "ss": v2.SpaceSyntaxView(**{**ctx.ss.__dict__, "display": {**ctx.ss.display, "palette": next(reversed(v2.PALETTES))}})})
    v2.draw_space_syntax(other)
    assert len(calls) == 2
    fresh = v2.analyse_network(ctx.ss.net, radii=(300.0, None), with_choice=True)    # a new analysis → new payload
    again = v2.Ctx(**{**ctx.__dict__, "ss": v2.SpaceSyntaxView(**{**ctx.ss.__dict__, "result": fresh})})
    v2.draw_space_syntax(again)
    assert len(calls) == 3


def test_the_space_syntax_legend_shows_the_scale_and_sits_between_travel_areas_and_golden_spots():
    ctx = ss_ctx()
    html = v2.legend_space_syntax(ctx)
    assert "Integration (NAIN)" in html and "linear-gradient" in html and "ต่ำ" in html and "สูง" in html
    both = v2.Ctx(**{**rich_ctx().__dict__, "ss": ctx.ss, "show": {**rich_ctx().show, **ctx.show, "show_space_syntax": True}})
    drawn, _ = v2.render_layers(both, folium.Map())
    box = v2.legend_stack(both, drawn).box_html
    assert box.index("เวลาเดินทาง") < box.index("CBD Zone") < box.index("Integration (NAIN)") < box.index("Golden Spot")


def test_space_syntax_row_is_in_the_registry_and_first_in_its_panel_group():
    layer = next(layer for layer in v2.LAYERS if layer.id == "space_syntax")
    assert layer.show_key == "show_space_syntax" and layer.group == "โครงข่ายถนน" and layer.options is not None
    rows = sorted((l for l in v2.LAYERS if l.group == layer.group and l.show_key), key=lambda l: l.panel_rank)
    assert rows[0].id == "space_syntax"
    order = [l.id for l in v2.LAYERS]
    assert order.index("cbd_zone") < order.index("space_syntax") < order.index("railway")
    assert not layer.available(make_ctx()) and layer.available(ss_ctx())


def test_the_study_centre_falls_back_to_markers_then_anchor_as_before(monkeypatch):
    state = make_state(monkeypatch)
    state["markers"] = [{"lat": 21.0, "lng": 101.0, "active": True}]
    assert v2.build_ctx().center == (21.0, 101.0)
    state[v2.StateManager.K_AUTO_ANCHOR] = {"anchor": {"lat": 20.5, "lon": 100.5}}
    assert v2.build_ctx().center == (20.5, 100.5)
    state[v2.StateManager.K_AUTO_ANCHOR] = None
    state[v2.StateManager.K_AUTO_ANCHOR_CLOSENESS] = {"anchor": {"lat": 20.6, "lon": 100.6}}
    assert v2.build_ctx().center == (20.6, 100.6)



# ----------------------------------------------------------------------------- views (the old tabs, one runs)
def dump(statement, strip_style=False):
    """``ast.dump`` of a statement; with ``strip_style`` every ``<style>…</style>`` inside a string literal is dropped."""
    if strip_style:
        statement = copy.deepcopy(statement)
        for node in ast.walk(statement):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                node.value = re.sub(r"<style>.*?</style>", "", node.value, flags=re.S)
    return ast.dump(statement)


def tab_bodies(path, strip_style=False):
    tree = ast.parse(Path(path).read_text(encoding="utf-8"))
    function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "render_analytics_panel")
    bodies = {}
    for node in ast.walk(function):
        if isinstance(node, ast.With) and isinstance(node.items[0].context_expr, ast.Name) \
                and node.items[0].context_expr.id.startswith("tab_"):
            bodies[node.items[0].context_expr.id] = [dump(statement, strip_style) for statement in node.body]
    return bodies


def view_statements(name, strip_style=False):
    tree = ast.parse(PAGE.read_text(encoding="utf-8"))
    function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
    body = function.body[1:]                                                  # skip the docstring
    if name != "view_theory":
        body = body[1:]                                                       # skip the shared-inputs line
    return [dump(statement, strip_style) for statement in body]


# Views that differ from the tab of Rent_Gradient.py they came from — each with its reason. The test fails if a listed
# view is in fact identical (the list cannot rot) and if an unlisted one differs (nothing drifts silently).
MODIFIED_VIEWS = {
    "view_marks": "the empty-state hint sends the user to ⚙️ การตั้งค่า — the map no longer adds pins on click",
    "view_theory": "only the <style> block: the cards take the page's text colour, so they read on white and on black",
}


@pytest.mark.parametrize("tab, view", [("tab_curve", "view_curve"), ("tab_rings", "view_rings"),
                                       ("tab_gold", "view_gold"), ("tab_marks", "view_marks"),
                                       ("tab_theory", "view_theory")])
def test_every_view_runs_exactly_the_statements_of_the_tab_it_came_from(tab, view):
    if view in MODIFIED_VIEWS:
        assert tab_bodies(BASE)[tab] != view_statements(view), f"{view} is listed as modified but identical"
    else:
        assert tab_bodies(BASE)[tab] == view_statements(view)


def test_the_theory_view_changed_only_its_style_block_and_still_says_the_same_thing():
    assert tab_bodies(BASE, strip_style=True)["tab_theory"] == view_statements("view_theory", strip_style=True)


def test_views_have_unique_keys_and_only_the_chosen_one_runs(monkeypatch):
    keys = [key for key, _, _ in v2.VIEWS]
    assert len(keys) == len(set(keys)) and keys[0] == "curve" and "space_syntax" in keys
    ran = []
    spies = tuple((key, label, (lambda ctx, key=key: ran.append(key))) for key, label, _ in v2.VIEWS)
    monkeypatch.setattr(v2, "VIEWS", spies)
    state = make_state(monkeypatch)
    monkeypatch.setattr(v2.st, "radio", lambda label, options, **kw: state[kw["key"]])
    for choice in ("curve", "space_syntax", "theory"):
        state["analytics_view"] = choice
        v2.render_views(make_ctx())
    assert ran == ["curve", "space_syntax", "theory"]
    state["analytics_view"] = "not a view"                              # a stale value falls back to the first view
    v2.render_views(make_ctx())
    assert ran[-1] == "curve" and state["analytics_view"] == "curve"


# ----------------------------------------------------------------------------- the whole page (AppTest, offline)
from streamlit.testing.v1 import AppTest  # noqa: E402


def app():
    import rent_gradient_new_v2_under_test
    rent_gradient_new_v2_under_test.main()


def make_app(monkeypatch, config=True, rendered=None, **state):
    """The page with the saved Chiang Khong results loaded (isochrone + network) and nothing fetched from the web."""
    monkeypatch.setattr(v2.StateManager, "_load_remote_defaults", staticmethod(lambda defaults: []))
    if rendered is not None:
        monkeypatch.setattr(v2, "st_folium", lambda m, **kw: rendered.append(m) or {})
    at = AppTest.from_function(app, default_timeout=180)
    if config:
        at.session_state["markers"] = CONFIG["markers"]
        for key, value in CONFIG["settings"].items():
            if key != "api_key":
                at.session_state[key] = value
        for key, value in PRE.items():
            at.session_state[key] = value
        at.session_state["show_betweenness"] = at.session_state["show_closeness"] = False
    for key, value in state.items():
        at.session_state[key] = value
    return at


def button(at, text):
    return next(b for b in at.button if text in b.label)


def map_layers(rendered):
    return layer_names(rendered[-1])


def test_cold_start_shows_every_panel_and_every_layer_checkbox(monkeypatch):
    rendered = []
    at = make_app(monkeypatch, config=False, rendered=rendered).run()
    assert not at.exception and not at.error
    labels = {b.label for b in at.button}
    assert {"🧩 ① คำนวณหา Isochrone CBD", "🚀 Run Network Analysis", "🎯 ค้นหา CBD Anchor อัตโนมัติ",
            "🧮 วิเคราะห์ Space Syntax", "🧪 ตัวอย่างเชียงของ (ออฟไลน์)", "🧮 คำนวณ Rent Gradient"} <= labels
    for layer in v2.LAYERS:
        if layer.show_key:
            at.checkbox(key=layer.show_key)                           # raises KeyError if the checkbox is missing
    assert at.radio(key="analytics_view").value == "curve" and not at.exception
    assert any("ชั้น Space Syntax" in c.value for c in at.caption)
    assert map_layers(rendered) == []                                 # nothing computed yet → an empty map, no crash
    assert any("ยังไม่มีข้อมูล" in c.value for c in at.caption)       # the layers panel says what to run first


def test_saved_results_come_back_as_layers_and_checkboxes_switch_them(monkeypatch):
    rendered = []
    at = make_app(monkeypatch, rendered=rendered).run()
    assert not at.exception and {"Travel Areas", "Integration Center (จุดตรงกลางที่สุด)", "หมุดของฉัน"} <= set(map_layers(rendered))
    assert "Road Betweenness" not in map_layers(rendered)
    at.checkbox(key="show_betweenness").check().run()
    assert not at.exception and "Road Betweenness" in map_layers(rendered)
    at.checkbox(key="show_betweenness").uncheck().run()
    assert "Road Betweenness" not in map_layers(rendered)
    at.checkbox(key="show_traffic").check().run()
    assert "Google Traffic" in map_layers(rendered)


def test_a_layer_that_fails_inside_the_page_only_shows_a_warning(monkeypatch):
    rendered = []
    monkeypatch.setattr(v2, "draw_traffic", lambda ctx: 1 / 0)
    monkeypatch.setattr(v2, "LAYERS", tuple(
        v2.Layer(**{**layer.__dict__, "draw": v2.draw_traffic}) if layer.id == "traffic" else layer for layer in v2.LAYERS))
    at = make_app(monkeypatch, rendered=rendered, show_traffic=True).run()
    assert not at.exception
    assert any("Google Traffic" in w.value and "ZeroDivisionError" in w.value for w in at.warning)
    assert "Travel Areas" in map_layers(rendered)                      # the other layers are still on the map


def test_skipped_config_values_are_reported_once(monkeypatch):
    at = make_app(monkeypatch, config=False, _import_skipped=["time_intervals", "colors"]).run()
    assert not at.exception
    assert any("ข้ามค่าที่ไม่ถูกต้อง" in w.value and "time_intervals" in w.value for w in at.warning)
    at.run()
    assert not any("ข้ามค่าที่ไม่ถูกต้อง" in w.value for w in at.warning)


@pytest.mark.parametrize("stale, now", [("Dark (CARTO)", "Dark (Esri Dark Gray)"),
                                        ("no such style", "Esri Light Gray (แนะนำสำหรับดูผังเมือง)")])
def test_a_session_left_on_a_removed_map_style_still_opens(monkeypatch, stale, now):
    rendered = []
    at = make_app(monkeypatch, config=False, rendered=rendered, map_style_name=stale).run()
    assert not at.exception and not at.error
    assert at.selectbox(key="map_style_name").value == now
    assert tile_layers(rendered[-1])[0].layer_name == now


def test_demo_button_runs_space_syntax_and_the_gradient_appears_as_a_layer_with_its_legend(monkeypatch):
    rendered = []
    at = make_app(monkeypatch, rendered=rendered, ss_radii=["400 m"], ss_choice=True).run()
    assert "🧭 Space Syntax (ไล่สีตามคะแนน)" not in map_layers(rendered)
    button(at, "ตัวอย่างเชียงของ").click().run(timeout=300)
    assert not at.exception and not at.error, [e.value for e in at.error]
    assert at.session_state["ss_result"].radii == [400.0] and at.session_state["ss_run"] == 1
    assert "🧭 Space Syntax (ไล่สีตามคะแนน)" in map_layers(rendered)
    html = rendered[-1].get_root().render()
    assert "Integration (NAIN) (คะแนน 0–100)" in html and "เวลาเดินทาง" in html     # one legend box, both sections
    assert html.count("position:fixed") == 1
    assert any("✅ ผลล่าสุด" in c.value for c in at.caption)
    at.checkbox(key="show_space_syntax").uncheck().run()
    assert "🧭 Space Syntax (ไล่สีตามคะแนน)" not in map_layers(rendered)
    at.checkbox(key="show_space_syntax").check().run()
    assert "🧭 Space Syntax (ไล่สีตามคะแนน)" in map_layers(rendered)


def test_display_options_change_the_map_without_recomputing_the_analysis(monkeypatch):
    rendered = []
    at = make_app(monkeypatch, rendered=rendered, ss_radii=["400 m", "800 m"], ss_choice=True).run()
    button(at, "ตัวอย่างเชียงของ").click().run(timeout=300)
    analysed = count_calls(monkeypatch, v2, "analyse_network")
    at.radio(key="ss_measure").set_value("choice").run()
    assert not at.exception and "Choice (NACH) (คะแนน 0–100)" in rendered[-1].get_root().render()
    at.selectbox(key="ss_view_radius").set_value("400").run()
    assert "400 m" in rendered[-1].get_root().render()
    palette = next(reversed(v2.PALETTES))
    at.selectbox(key="ss_palette").set_value(palette).run()
    at.radio(key="ss_scale").set_value("quantile").run()
    assert not at.exception and analysed == []                         # display only: never recomputed
    html = rendered[-1].get_root().render()
    assert v2.PALETTES[palette][0] in html and "Quantile" in html


def test_a_widget_that_was_hidden_remembers_its_value_when_it_comes_back(monkeypatch):
    at = make_app(monkeypatch, rendered=[], ss_radii=["400 m"], ss_choice=False).run()
    button(at, "ตัวอย่างเชียงของ").click().run(timeout=300)
    palette = next(reversed(v2.PALETTES))
    at.selectbox(key="ss_palette").set_value(palette).run()
    at.checkbox(key="show_space_syntax").uncheck().run()              # the display options disappear …
    assert not any(w.key == "ss_palette" for w in at.selectbox)
    at.checkbox(key="show_space_syntax").check().run()                # … and return with the chosen palette
    assert at.selectbox(key="ss_palette").value == palette


def test_space_syntax_view_runs_only_when_chosen_and_the_png_only_when_asked_for(monkeypatch):
    at = make_app(monkeypatch, rendered=[], ss_radii=["400 m"], ss_choice=False).run()
    button(at, "ตัวอย่างเชียงของ").click().run(timeout=300)
    png, histogram = count_calls(monkeypatch, v2, "render_depthmap_png"), count_calls(monkeypatch, v2, "histogram_figure")
    at.run()
    assert png == [] and histogram == []                               # the Bid-Rent view is showing
    at.radio(key="analytics_view").set_value("space_syntax").run()
    assert not at.exception and len(histogram) == 1 and png == []      # stats first, no PNG yet
    assert any("Segment (แสดง / ทั้งหมด)" in m.label for m in at.metric)
    at.radio(key="ss_view").set_value("png").run()
    assert len(png) == 1 and not at.exception
    at.run()
    at.radio(key="ss_view").set_value("stats").run()
    at.radio(key="ss_view").set_value("png").run()
    assert len(png) == 1                                               # the PNG is kept in the session LRU
    at.radio(key="ss_view").set_value("help").run()
    assert not at.exception and any("อ่านสีอย่างไร" in m.value for m in at.markdown)


def test_space_syntax_view_without_a_result_explains_what_to_press(monkeypatch):
    at = make_app(monkeypatch, config=False, rendered=[]).run()
    at.radio(key="analytics_view").set_value("space_syntax").run()
    assert not at.exception and any("วิเคราะห์ Space Syntax" in i.value for i in at.info)


def test_changing_the_settings_after_a_run_is_flagged_as_stale_not_silently_wrong(monkeypatch):
    at = make_app(monkeypatch, rendered=[], ss_radii=["400 m"], ss_choice=False).run()
    button(at, "ตัวอย่างเชียงของ").click().run(timeout=300)
    assert not any("ตั้งค่าเปลี่ยนไป" in w.value for w in at.warning)
    at.selectbox(key="ss_kind").set_value("metric").run()
    assert any("ตั้งค่าเปลี่ยนไปจากที่คำนวณไว้" in w.value for w in at.warning)
    at.radio(key="analytics_view").set_value("space_syntax").run()
    assert any("ตั้งค่า Space Syntax เปลี่ยนไปจากที่คำนวณไว้" in w.value for w in at.warning)


def test_locking_the_menus_also_locks_the_space_syntax_panel(monkeypatch):
    at = make_app(monkeypatch, config=False, rendered=[]).run()
    assert not button(at, "วิเคราะห์ Space Syntax").disabled
    at.toggle(key="ui_locked").set_value(True).run()
    assert button(at, "วิเคราะห์ Space Syntax").disabled and button(at, "ตัวอย่างเชียงของ").disabled
    assert at.slider(key="ss_radius_m").disabled and at.checkbox(key="show_space_syntax").disabled


def test_the_study_centre_is_shared_with_the_anchor_panel(monkeypatch):
    at = make_app(monkeypatch, config=False, rendered=[]).run()
    at.text_input(key="anchor_center_input").set_value("20.1, 100.2").run()
    assert any("20.10000, 100.20000" in c.value for c in at.caption)
    assert at.session_state["anchor_lat"] == 20.1 and at.session_state["anchor_lon"] == 100.2


def test_tab_bodies_still_work_with_results(monkeypatch):
    rent = v2.compute_rent_gradient_data(None, PRE["network_data"], PRE["isochrone_data"], CONFIG["markers"], [], "ดัชนี")
    at = make_app(monkeypatch, rendered=[], rent_gradient_data=rent).run()
    assert not at.exception
    for key in ("rings", "gold", "marks", "theory", "curve"):
        at.radio(key="analytics_view").set_value(key).run()
        assert not at.exception, key
    assert at.radio(key="analytics_view").value == "curve"


# ----------------------------------------------------------------------------- pins are typed in, never clicked in
def exact_button(at, label):
    return next(b for b in at.button if b.label == label)


def test_a_pin_typed_in_the_sidebar_is_added_active_and_makes_the_old_results_stale(monkeypatch):
    at = make_app(monkeypatch, rendered=[]).run()
    before = len(at.session_state["markers"])
    assert at.session_state["isochrone_data"] is not None and at.session_state["network_data"] is not None
    at.text_input(key="manual_coords").set_value("20.3, 100.5")
    exact_button(at, "เพิ่ม").click().run()
    assert not at.exception and not at.error
    assert at.session_state["markers"][-1] == {"lat": 20.3, "lng": 100.5, "active": True}
    assert len(at.session_state["markers"]) == before + 1
    assert at.session_state["isochrone_data"] is None and at.session_state["intersection_data"] is None
    assert at.session_state["rent_gradient_data"] is None
    assert at.session_state["network_data"] is not None            # the road analysis does not depend on the pins


@pytest.mark.parametrize("text, message", [
    ("abc, def", "พิกัดไม่ถูกต้อง"),
    ("hello", "กรุณากรอกพิกัดเป็น Lat, Lon"),
    ("20.3", "กรุณากรอกพิกัดเป็น Lat, Lon"),
    ("", "กรุณากรอกพิกัดเป็น Lat, Lon"),
    ("20.3, 100.5, 7", "กรุณากรอกพิกัดเป็น Lat, Lon"),
    ("95, 100", "Lat ต้องอยู่ระหว่าง"),
    ("20, 200", "Lon ต้องอยู่ระหว่าง"),
])
def test_coordinates_that_cannot_be_a_pin_are_explained_and_nothing_is_added(monkeypatch, text, message):
    at = make_app(monkeypatch, rendered=[]).run()
    before = [dict(m) for m in at.session_state["markers"]]
    at.text_input(key="manual_coords").set_value(text)
    exact_button(at, "เพิ่ม").click().run()
    assert not at.exception and any(message in e.value for e in at.error), [e.value for e in at.error]
    assert at.session_state["markers"] == before
    assert at.session_state["isochrone_data"] is not None          # a rejected entry must not throw results away


def test_locking_the_menus_locks_the_coordinate_entry_too(monkeypatch):
    at = make_app(monkeypatch, config=False, rendered=[]).run()
    assert not exact_button(at, "เพิ่ม").disabled and not at.text_input(key="manual_coords").disabled
    at.toggle(key="ui_locked").set_value(True).run()
    assert exact_button(at, "เพิ่ม").disabled and at.text_input(key="manual_coords").disabled


def test_the_sidebar_says_where_pins_are_entered_and_the_empty_view_points_there(monkeypatch):
    at = make_app(monkeypatch, config=False, rendered=[], analytics_view="marks").run()
    assert not at.exception and at.session_state["markers"] == []
    assert any("เพิ่ม Active Marker" in c.value and "Lat, Lng" in c.value for c in at.caption)
    hint = next(i.value for i in at.info if "ยังไม่มีหมุด" in i.value)
    assert "⚙️ การตั้งค่า" in hint and "คลิก" not in hint


PINS = [{"lat": 20.1, "lng": 100.1, "active": True}, {"lat": 20.2, "lng": 100.2, "active": False},
        {"lat": 20.3, "lng": 100.3, "active": True}]


def pin_states(at):
    return [(m["lat"], m["active"]) for m in at.session_state["markers"]]


def test_deleting_a_pin_keeps_the_on_off_state_of_the_pins_that_remain(monkeypatch):
    at = make_app(monkeypatch, config=False, rendered=[], markers=[dict(m) for m in PINS]).run()
    assert pin_states(at) == [(20.1, True), (20.2, False), (20.3, True)]
    next(b for b in at.button if b.key == "del_btn_0").click().run()
    assert not at.exception and pin_states(at) == [(20.2, False), (20.3, True)]      # was: [(20.2, True), (20.3, False)]
    assert at.checkbox(key="active_chk_0").value is False and at.checkbox(key="active_chk_1").value is True


def test_a_pin_added_after_the_last_one_was_deleted_starts_active(monkeypatch):
    at = make_app(monkeypatch, config=False, rendered=[], markers=[dict(m) for m in PINS]).run()
    at.checkbox(key="active_chk_2").uncheck().run()                                  # the last pin is switched off …
    exact = next(b for b in at.button if "ลบจุดล่าสุด" in b.label)
    exact.click().run()                                                              # … and deleted
    at.text_input(key="manual_coords").set_value("20.4, 100.4")
    exact_button(at, "เพิ่ม").click().run()
    assert pin_states(at) == [(20.1, True), (20.2, False), (20.4, True)]
    assert at.checkbox(key="active_chk_2").value is True


def test_reset_and_a_config_import_start_the_pin_checkboxes_afresh(monkeypatch):
    state = make_state(monkeypatch)
    state.update({"markers": [dict(m) for m in PINS], "active_chk_0": True, "active_chk_1": False, "other": 1})
    v2.StateManager.reset()
    assert "active_chk_0" not in state and "active_chk_1" not in state and state["other"] == 1
    state["active_chk_0"] = False
    v2.StateManager.import_config({"markers": [dict(m) for m in PINS]})
    assert "active_chk_0" not in state


def test_the_active_marker_count_follows_the_ticks_of_the_same_run(monkeypatch):
    at = make_app(monkeypatch, config=False, rendered=[], markers=[dict(m, active=True) for m in PINS]).run()
    counts = lambda: [m.value for m in at.markdown if "Active Markers:" in m.value]
    assert counts() == ["📍 Active Markers: **3**"]
    at.checkbox(key="active_chk_1").uncheck().run()
    assert counts() == ["📍 Active Markers: **2**"]                                  # was one run behind: still **3**
    assert at.metric[0].value == "2"


# ----------------------------------------------------------------------------- white and black
def css_palettes(css):
    """``(light, dark)`` custom properties of ``MAP_CHROME_CSS``: ``{name: value}``."""
    def read(block):
        return {name: value.strip() for name, value in re.findall(r"--(rg-[a-z]+):([^;}]+)", block)}
    light = re.search(r":root\{(.*?)\}", css, re.S).group(1)
    dark = re.search(r"prefers-color-scheme:dark\)\{:root\{(.*?)\}\}", css, re.S).group(1)
    return read(light), read(dark)


def rgb_of(value):
    if value.startswith("#"):
        return tuple(int(value[i:i + 2], 16) for i in (1, 3, 5))
    return tuple(int(float(p)) for p in re.match(r"rgba?\(([^)]*)\)", value).group(1).split(",")[:3])


def contrast(a, b):
    def luminance(rgb):
        lin = [c / 255 / 12.92 if c / 255 <= 0.03928 else ((c / 255 + 0.055) / 1.055) ** 2.4 for c in rgb]
        return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]
    hi, lo = sorted((luminance(rgb_of(a)), luminance(rgb_of(b))), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def test_the_map_panels_carry_a_white_and_a_black_palette():
    light, dark = css_palettes(v2.MAP_CHROME_CSS)
    assert set(dark) <= set(light)                                  # black only overrides what white defines
    assert {"rg-panel", "rg-text", "rg-muted", "rg-line", "rg-link", "rg-shadow", "rg-icon"} <= set(dark)
    used = set(re.findall(r"var\(--(rg-[a-z]+)\)", v2.MAP_CHROME_CSS))
    assert used <= set(light), used - set(light)                    # no rule refers to a colour that is not defined
    assert all(light[name] != dark[name] for name in ("rg-panel", "rg-text", "rg-muted", "rg-link"))


@pytest.mark.parametrize("name", ["rg-text", "rg-muted", "rg-link"])
def test_map_panel_text_is_readable_in_both_palettes(name):
    for palette in css_palettes(v2.MAP_CHROME_CSS):
        assert contrast(palette[name], palette["rg-panel"]) >= 4.5, (name, palette)


def test_the_base_map_carries_the_panel_colours_and_the_legend_has_none_of_its_own():
    html = v2.build_base_map(make_ctx()).get_root().render()
    assert v2.MAP_CHROME_CSS in html and "prefers-color-scheme:dark" in html
    ctx = rich_ctx()
    drawn, _ = v2.render_layers(ctx, folium.Map())
    legend = v2.legend_stack(ctx, drawn).box_html
    assert 'class="rg-legend"' in legend
    assert not re.search(r"background:\s*(rgba?\(|#fff|white)", legend.split(">", 1)[0])    # the box itself
    assert not re.search(r"(?<![-\w])color:\s*#", legend)                                   # no fixed text colour


def test_a_pin_label_reads_on_white_and_on_black():
    labels = [v2._marker_label_html(i, {"lat": 20.21944, "lng": 100.40363}, True) for i in range(len(v2.HEX_COLORS) + 2)]
    assert not any(re.search(r"(?<![-\w])color:", label) for label in labels), "text takes the theme's colour"
    for i, label in enumerate(labels):
        assert f"background:{v2.HEX_COLORS[i % len(v2.HEX_COLORS)]}" in label        # the dot is the pin's colour …
        assert "rgba(128,128,128" in label                                           # … ringed so no hue vanishes
        assert f"จุดที่ {i + 1}" in label and "(20.2194, 100.4036)" in label
    off = v2._marker_label_html(0, {"lat": 20.1, "lng": 100.2}, False)
    assert "line-through" in off and "opacity:.45" in off and "background:" not in off and "#D63E2A" not in off


def theory_css():
    function = next(n for n in ast.parse(PAGE.read_text(encoding="utf-8")).body
                    if isinstance(n, ast.FunctionDef) and n.name == "view_theory")
    html = next(n.value for n in ast.walk(function) if isinstance(n, ast.Constant) and isinstance(n.value, str)
                and "<style>" in n.value)
    return re.search(r"<style>(.*?)</style>", html, re.S).group(1)


def test_the_theory_cards_take_the_page_colours_instead_of_fixed_light_on_dark_ones():
    css = theory_css()
    assert set(re.findall(r"#[0-9a-fA-F]{3,8}\b", css)) <= {"#1f7a70", "#fff"}      # one accent, white on the badge
    assert "rgba(" not in css and "color-mix(in srgb, currentColor" in css
    text_colours = set(re.findall(r"(?<![-\w])color:\s*([^;]+);", css))
    assert text_colours <= {"inherit", "var(--rg-muted)", "#fff"}, text_colours
