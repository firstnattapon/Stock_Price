"""Headless run of pages/Rent_Gradient_Laora.py with Streamlit's AppTest.

Offline: the road network is injected into session state, so nothing is downloaded. Checks that
the page renders cold, ranks the generating distance first for rents built from it, reports a
malformed anchor as an error rather than raising, and parses its inputs.
"""
import importlib.util
import io
import sys
from math import exp
from pathlib import Path

import pytest

pytest.importorskip("streamlit")
pd = pytest.importorskip("pandas")
pytest.importorskip("plotly")
from streamlit.testing.v1 import AppTest  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import test_rent_gradient_laora as helpers  # noqa: E402
from rent_gradient_laora import core  # noqa: E402

PAGE = ROOT / "pages" / "Rent_Gradient_Laora.py"


def _load_page_module():
    spec = importlib.util.spec_from_file_location("rent_gradient_laora_page_under_test", PAGE)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _app_with_network():
    graph = helpers.two_streets()
    net = core.build_network(graph)
    anchor_points = [helpers.pt(i * 100, 0) for i in range(5)]
    anchor = core.anchor_from_points(net, anchor_points)
    places = [helpers.pt(x, 100) for x in (50, 150, 250, 350)] + [helpers.pt(x, 0) for x in (50, 250)]
    metric = core.distances_to_anchor(net, anchor, places, kinds=["metric"])["distances"]["metric"]
    app = AppTest.from_file(str(PAGE), default_timeout=60)
    app.session_state["laora_net"] = net
    app.session_state["laora_graph"] = graph
    app.session_state["laora_meta"] = {"source": "test (synthetic)", "lat": helpers.LAT0,
                                       "lon": helpers.LON0, "radius": 2000, "network": "drive"}
    app.session_state["laora_samples"] = pd.DataFrame(
        [{"lat": p[0], "lon": p[1], "rent": 900 * exp(-1.4 * m)} for p, m in zip(places, metric)],
        dtype="float64")
    return app, anchor_points


def test_cold_start_asks_for_the_network_first():
    app = AppTest.from_file(str(PAGE), default_timeout=60).run()
    assert not app.exception
    assert app.info and "โหลดโครงข่ายถนน" in app.info[0].value


def test_compare_ranks_the_generating_distance_first():
    app, anchor_points = _app_with_network()
    app.run()
    assert not app.exception
    next(r for r in app.radio if r.key == "laora_anchor_mode").set_value("พิกัด lat, lon").run()
    next(t for t in app.text_area if t.key == "laora_anchor_text").set_value(
        "\n".join(f"{a}, {b}" for a, b in anchor_points)).run()
    next(b for b in app.button if "เทียบโมเดล" in b.label).click().run()
    assert not app.exception
    assert app.success and "Metric" in app.success[0].value
    table = app.dataframe[0].value
    assert table.iloc[0]["ระยะ"].startswith("Metric")
    assert table.iloc[0]["λ (ต่อหน่วย)"] == pytest.approx(1.4, rel=1e-6)
    assert len(app.tabs) == 4


def test_a_malformed_anchor_is_an_error_not_a_crash():
    app, _ = _app_with_network()
    app.run()
    next(r for r in app.radio if r.key == "laora_anchor_mode").set_value("พิกัด lat, lon").run()
    next(t for t in app.text_area if t.key == "laora_anchor_text").set_value("not a point").run()
    assert not app.exception
    assert any("lat, lon" in e.value for e in app.error)
    assert next(b for b in app.button if "เทียบโมเดล" in b.label).disabled


def test_input_parsers():
    page = _load_page_module()
    assert page.parse_points("20.2, 100.4\n\n20.3;100.5") == [(20.2, 100.4), (20.3, 100.5)]
    for bad in ("1,2,3", "a,b", "95,100"):
        with pytest.raises(ValueError):
            page.parse_points(bad)
    frame = page.samples_from_csv(io.StringIO("Lat,LON,Rent\n20.1,100.2,500\n"))
    assert frame.to_dict("records") == [{"lat": 20.1, "lon": 100.2, "rent": 500.0}]
    with pytest.raises(ValueError):
        page.samples_from_csv(io.StringIO("lat,lon\n1,2\n"))
