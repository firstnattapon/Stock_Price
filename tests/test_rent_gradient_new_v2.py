"""Rent_Gradient_new_v2: layer stack on one map — registry, error isolation, LRU cache, Streamlit flow (offline)."""
import importlib.util
import re
import sys
from collections import OrderedDict
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("streamlit")
pytest.importorskip("folium")
from streamlit.testing.v1 import AppTest  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
import test_rent_gradient_new as helpers  # noqa: E402  (synthetic street graphs + the core page module)

PAGE = ROOT / "pages" / "Rent_Gradient_new_v2.py"
spec = importlib.util.spec_from_file_location("rent_gradient_new_v2_under_test", PAGE)
v2 = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = v2
spec.loader.exec_module(v2)
core = helpers.rgn

RINGS = {"type": "FeatureCollection", "features": [{
    "type": "Feature",
    "geometry": {"type": "Polygon", "coordinates": [[[100.40, 20.20], [100.41, 20.20], [100.41, 20.21],
                                                     [100.40, 20.20]]]},
    "properties": {"color": "#3987e5", "band": "0–1 km <b>", "rent_label": "100"}}]}
RENT = {"rings_geojson": RINGS, "model": {"is_index": True}}


def make_ctx(rent=None, cache=None, **overrides):
    graph = helpers.grid_graph(8)
    net = core.build_segment_network(graph)
    result = core.analyse_network(net, radii=(300.0, None), with_choice=True)
    mask = np.ones(net.n_segments, bool)
    style = {"palette": core.DEFAULT_PALETTE, "scale": "linear", "thick": True,
             "basemap": "พื้นดำ (เหมือน depthmap)", "top_n": 3}
    fields = dict(core=core, net=net, result=result, mask=mask, mask_key=v2.mask_digest(mask), run_id=1,
                  measure="integration", rkey="n", style=style, meta={}, rent_data=rent,
                  cache=OrderedDict() if cache is None else cache)
    fields.update(overrides)
    return v2.LayerContext(**fields)


# ----------------------------------------------------------------- loader
def test_core_loads_and_exposes_everything_v2_needs():
    module, error = v2.load_core()
    assert error is None and module is not None
    assert all(hasattr(module, name) for name in v2.REQUIRED_CORE)


def test_missing_or_incomplete_core_gives_a_clear_error_not_a_crash(tmp_path):
    module, error = v2.load_core(tmp_path / "Rent_Gradient_new.py")
    assert module is None and "Rent_Gradient_new.py" in error
    stub = tmp_path / "stub_core.py"
    stub.write_text("K_NET = 'x'\n")
    module, error = v2.load_core(stub)
    assert module is None and "ไม่มีสิ่งที่หน้านี้ใช้" in error and "scale_scores" in error
    broken = tmp_path / "broken_core.py"
    broken.write_text("raise RuntimeError('boom')\n")
    module, error = v2.load_core(broken)
    assert module is None and "boom" in error


# ----------------------------------------------------------------- cache
def test_lru_cache_hits_do_not_rebuild_and_the_oldest_entry_goes_first():
    store, calls = OrderedDict(), []

    def build(tag):
        calls.append(tag)
        return tag

    for key in "abc":
        v2.cache_get_or_build(store, key, lambda k=key: build(k), limit=3)
    assert v2.cache_get_or_build(store, "a", lambda: build("again"), limit=3) == "a"  # hit
    v2.cache_get_or_build(store, "d", lambda: build("d"), limit=3)  # evicts "b", not "a"
    assert list(store) == ["c", "a", "d"] and calls == ["a", "b", "c", "d"]


def test_mask_digest_changes_with_the_mask_only():
    a = np.array([True, False, True, True])
    assert v2.mask_digest(a) == v2.mask_digest(a.copy())
    assert v2.mask_digest(a) != v2.mask_digest(~a)


# ----------------------------------------------------------------- layers
def test_layers_are_unique_ordered_bottom_to_top_and_plain_functions():
    ids = [i for i, _, _ in v2.LAYERS]
    assert ids == ["rent_rings", "space_syntax"] and len(set(ids)) == len(ids)
    assert all(callable(fn) for _, _, fn in v2.LAYERS)


def test_enabled_layers_are_drawn_and_closed_ones_are_not_even_built():
    calls = []

    def spy(name, real):
        def layer(ctx):
            calls.append(name)
            return real(ctx)
        return layer

    layers = (("rent_rings", "rings", spy("rent_rings", v2.layer_rent_rings)),
              ("space_syntax", "ss", spy("space_syntax", v2.layer_space_syntax)))
    ctx = make_ctx(rent=RENT)
    fmap, drawn, warnings = v2.render_layers(ctx, ["space_syntax"], layers)
    assert calls == ["space_syntax"] and drawn == ["space_syntax"] and warnings == []
    assert "Rent Gradient Rings" not in fmap.get_root().render()
    fmap, drawn, _ = v2.render_layers(ctx, ["rent_rings", "space_syntax"], layers)
    assert drawn == ["rent_rings", "space_syntax"]  # z-order: rings first
    html = fmap.get_root().render()
    assert html.index("Rent Gradient Rings") < html.index("Space Syntax")
    assert "Rent Gradient (วงแหวนราคา)" in html and "(คะแนน 0–100)" in html  # both legends, stacked


def test_a_layer_without_data_is_hidden_and_a_broken_layer_only_adds_a_warning():
    ctx = make_ctx(rent=None)
    fmap, drawn, warnings = v2.render_layers(ctx, ["rent_rings", "space_syntax"])
    assert drawn == ["space_syntax"] and warnings == []
    for bad in ({"error": "x"}, {"rings_geojson": None}, {"rings_geojson": {"features": []}}, "text", 5):
        assert v2.layer_rent_rings(make_ctx(rent=bad)) is None

    def boom(_ctx):
        raise RuntimeError("layer exploded")

    layers = (("rent_rings", "rings", boom), ("space_syntax", "ss", v2.layer_space_syntax))
    fmap, drawn, warnings = v2.render_layers(ctx, ["rent_rings", "space_syntax"], layers)
    assert drawn == ["space_syntax"] and len(warnings) == 1 and "layer exploded" in warnings[0]
    assert fmap.get_root().render()  # the map still builds


def test_layer_text_from_osm_and_the_rent_page_is_escaped():
    graph = helpers.chain(3)
    for _, _, d in graph.edges(data=True):
        d["name"] = "<img src=x onerror=alert(1)>"
    net = core.build_segment_network(graph)
    result = core.analyse_network(net, radii=(None,), with_choice=False)
    mask = np.ones(net.n_segments, bool)
    ctx = make_ctx(rent=RENT, net=net, result=result, mask=mask, mask_key=v2.mask_digest(mask))
    html = v2.render_layers(ctx, ["rent_rings", "space_syntax"])[0].get_root().render()
    assert "<img src=x" not in html and "&lt;img src=x" in html
    assert "<b>" not in html
    assert re.search(r"(&|\\u0026)lt;b(&|\\u0026)gt;", html)  # folium JSON-encodes "&" as \u0026


def test_toggling_layers_reuses_the_cached_layer_data(monkeypatch):
    built = []
    real = core.segments_geojson
    monkeypatch.setattr(core, "segments_geojson", lambda *a, **k: built.append(1) or real(*a, **k))
    ctx = make_ctx()
    for enabled in (["space_syntax"], ["rent_rings"], ["space_syntax"], ["rent_rings", "space_syntax"]):
        v2.render_layers(ctx, enabled)
    assert len(built) == 1  # one GeoJSON for four renders
    v2.render_layers(make_ctx(cache=ctx.cache, measure="choice"), ["space_syntax"])
    v2.render_layers(make_ctx(cache=ctx.cache, run_id=2), ["space_syntax"])  # a new analysis invalidates
    assert len(built) == 3


def test_choice_and_local_radius_are_selectable():
    ctx = make_ctx(measure="choice", rkey="300")
    html = v2.render_layers(ctx, ["space_syntax"])[0].get_root().render()
    assert "Choice (NACH)" in html and "300 m" in html


# ----------------------------------------------------------------- Streamlit flow
def _app(rent=None):
    net = core.build_segment_network(helpers.grid_graph(8))
    app = AppTest.from_file(str(PAGE), default_timeout=120)
    app.session_state["rgn_net"] = net
    app.session_state["rgn_meta"] = {"source": "test", "lat": helpers.LAT0, "lon": helpers.LON0,
                                     "radius_m": None, "network": "drive", "nodes": net.n_nodes,
                                     "edges": net.n_segments}
    app.session_state["rgn_autorun"] = True
    if rent is not None:
        app.session_state["rent_gradient_data"] = rent
    return app


def _w(widgets, text):
    return next(w for w in widgets if text in w.label)


def test_cold_start_and_page_flow_without_exceptions():
    cold = AppTest.from_file(str(PAGE), default_timeout=120).run()
    assert not cold.exception and cold.info and "โหลดโครงข่ายถนน" in cold.info[0].value
    app = _app().run()
    assert not app.exception and not app.error
    assert _w(app.multiselect, "เลเยอร์บนแผนที่").value == ["rent_rings", "space_syntax"]
    assert any("ยังไม่มีผล Rent Gradient" in c.value for c in app.caption)  # rings enabled, no data
    assert any("เลเยอร์ที่แสดง" in c.value for c in app.caption)


def test_page_toggles_layers_measure_and_radius_and_shows_rent_rings_when_available():
    app = _app(rent=RENT).run()
    assert not app.exception and not any("ยังไม่มีผล Rent Gradient" in c.value for c in app.caption)
    assert any("Rent rings" in c.value for c in app.caption if "เลเยอร์ที่แสดง" in c.value)
    _w(app.multiselect, "เลเยอร์บนแผนที่").set_value(["space_syntax"]).run()
    assert not app.exception
    _w(app.multiselect, "เลเยอร์บนแผนที่").set_value([]).run()
    assert not app.exception and any("ยังไม่ได้เปิดเลเยอร์" in i.value for i in app.info)
    _w(app.multiselect, "เลเยอร์บนแผนที่").set_value(["space_syntax"]).run()
    _w(app.radio, "ตัวชี้วัด").set_value("choice").run()
    _w(app.selectbox, "รัศมีที่แสดง").set_value("800").run()
    assert not app.exception and not app.error


def test_a_new_analysis_invalidates_the_cache_through_the_run_counter():
    app = _app().run()
    first = app.session_state["rgv2_run"]
    app.run()  # plain rerun: same result, same counter
    assert app.session_state["rgv2_run"] == first
    _w(app.button, "วิเคราะห์ Space Syntax").click().run()
    assert app.session_state["rgv2_run"] == first + 1 and not app.exception
