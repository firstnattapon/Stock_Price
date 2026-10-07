"""Capture script (offline, fake server) and acceptance checks for real captured WMS fixtures.

The real-fixture checks run only when ``Geoapify_Map/fixtures/wms/manifest.json`` exists (it is
produced by ``scripts/capture_wms_fixtures.py`` on a machine that can reach Longdo).
"""
import importlib.util
import io
import json
from pathlib import Path
import sys

import numpy as np
import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("rent_gradient_fixtures_test", ROOT / "pages/Rent_Gradient.py")
page = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = page
spec.loader.exec_module(page)
spec_c = importlib.util.spec_from_file_location("capture_wms_fixtures", ROOT / "scripts/capture_wms_fixtures.py")
capture = importlib.util.module_from_spec(spec_c)
spec_c.loader.exec_module(capture)

FIXTURES = ROOT / "Geoapify_Map" / "fixtures" / "wms"
CENTER = (20.219443, 100.403630)


# ----------------------------------------------------------------------- fake Longdo server
def parcel_png(px):
    a = np.zeros((px, px, 4), dtype=np.uint8)
    a[::16, :] = (60, 60, 60, 255)
    a[:, ::5] = (60, 60, 60, 255)
    return a


def plan_png(px):
    a = np.zeros((px, px, 4), dtype=np.uint8)
    a[...] = (0, 176, 80, 255)
    a[px // 3: 2 * px // 3, px // 3: 2 * px // 3] = (255, 0, 0, 255)
    return a


def encode(a):
    buffer = io.BytesIO()
    Image.fromarray(a, "RGBA").save(buffer, format="PNG")
    return buffer.getvalue()


class Reply:
    def __init__(self, content=b"", status=200, content_type="image/png"):
        self.content, self.status_code, self.headers = content, status, {"Content-Type": content_type}


class FakeLongdo:
    def __init__(self, fail_layers=()):
        self.requests, self.fail_layers = [], set(fail_layers)

    def get(self, url, params=None, timeout=None, headers=None):
        self.requests.append((url, dict(params)))
        if params["request"] == "GetCapabilities":
            return Reply(b"<WMT_MS_Capabilities/>", content_type="text/xml")
        if params["request"] == "GetLegendGraphic":
            return Reply(encode(plan_png(32)))
        if params.get("layers") in self.fail_layers:
            return Reply(b"<ServiceException>no such layer</ServiceException>", content_type="text/xml")
        px = int(params["width"])
        return Reply(encode(parcel_png(px) if params["layers"] == "dol" else plan_png(px)))


# -------------------------------------------------------------------------- the checks
def check_fixture_dir(directory: Path):
    """Sanity checks shared by the fake-server run and the real captured folder."""
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["files"], "no windows captured"
    text = (directory / "manifest.json").read_text(encoding="utf-8")
    assert page.DEFAULT_CONFIG["LONGDO_KEY"] not in text                    # the key is never written
    for entry in manifest["files"]:
        image = Image.open(directory / entry["file"]).convert("RGBA")
        assert list(image.size) == entry["size"] == [entry["px"], entry["px"]]
        assert entry["m_per_px"] == pytest.approx(entry["window_m"] / entry["px"])
        if entry["kind"] == "parcel":
            assert "parcel_features" in entry
        else:
            assert "top_colours" in entry
    return manifest


# ------------------------------------------------------------------- capture script (offline)
def test_capture_downloads_every_window_and_never_stores_the_key(tmp_path):
    fake = FakeLongdo()
    manifest = capture.capture(
        tmp_path, CENTER, 5000.0, [("core", *CENTER), ("outskirts", 20.26, 100.47)],
        px=256, delay_s=0.0, session=fake)
    assert not manifest["errors"]
    kinds = [e["kind"] for e in manifest["files"]]
    assert kinds.count("overview") == 1
    assert kinds.count("parcel") == 2 * len(capture.PARCEL_WINDOWS_M)
    assert kinds.count("plan") == 2 * len(capture.PLAN_WINDOWS_M)
    assert {d["file"] for d in manifest["documents"]} == {"capabilities.xml", "legend_cityplan_dpt.png"}
    check_fixture_dir(tmp_path)
    for url, params in fake.requests:
        assert url == page.LONGDO_WMS_URL and "key" not in params
    overview = next(e for e in manifest["files"] if e["kind"] == "overview")
    assert overview["window_m"] == 10000.0 and overview["layer"] == "cityplan_dpt"
    plan = next(e for e in manifest["files"] if e["kind"] == "plan")
    names = [c["nearest_provisional_class"] for c in plan["top_colours"]]
    assert "พาณิชยกรรม" in names                                              # the red block is recognised
    dol = next(e for e in manifest["files"] if e["kind"] == "parcel")
    assert dol["parcel_features"]["data"] is False or "score" in dol["parcel_features"]


def test_capture_survives_a_rejected_layer_and_reports_it(tmp_path):
    manifest = capture.capture(tmp_path, CENTER, 5000.0, [("core", *CENTER)], px=128, delay_s=0.0,
                               session=FakeLongdo(fail_layers={"dol"}))
    assert [e["kind"] for e in manifest["files"]].count("parcel") == 0
    assert len(manifest["errors"]) == len(capture.PARCEL_WINDOWS_M)
    assert "ServiceException" in manifest["errors"][0]["body_start"]
    assert (tmp_path / "manifest.json").exists()
    out = io.StringIO()
    sys.stdout, saved = out, sys.stdout
    try:
        capture.print_report(manifest)
    finally:
        sys.stdout = saved
    assert "errors" in out.getvalue() and "cityplan_legend.json" in out.getvalue()


def test_capture_network_failures_are_recorded_not_raised(tmp_path):
    class Offline:
        def get(self, *a, **k):
            raise ConnectionError("no route to host")

    manifest = capture.capture(tmp_path, CENTER, 5000.0, [("core", *CENTER)], px=64, delay_s=0.0,
                               session=Offline())
    assert manifest["files"] == [] and manifest["errors"]
    assert "no route to host" in manifest["errors"][0]["error"]
    assert capture.main.__name__ == "main"


# ----------------------------------------------------- real captured fixtures (skipped if absent)
real = pytest.mark.skipif(not (FIXTURES / "manifest.json").exists(),
                          reason="run scripts/capture_wms_fixtures.py and commit Geoapify_Map/fixtures/wms")


@real
def test_real_fixtures_are_consistent_with_the_manifest():
    manifest = check_fixture_dir(FIXTURES)
    assert not manifest["errors"], manifest["errors"]


@real
def test_real_city_plan_colours_are_covered_by_the_legend_file():
    legend, source = page.load_cityplan_legend()
    assert source == "file", "write Geoapify_Map/cityplan_legend.json from the captured colours"
    manifest = json.loads((FIXTURES / "manifest.json").read_text(encoding="utf-8"))
    for entry in manifest["files"]:
        if entry["kind"] == "parcel":
            continue
        rgba = np.asarray(Image.open(FIXTURES / entry["file"]).convert("RGBA"))
        painted = rgba[..., 3] >= 200
        if not painted.any():
            continue
        classes = page._classify_colors(rgba, legend, page.ZONING_COLOR_TOLERANCE)
        assert (classes[painted] >= 0).mean() >= 0.85, entry["file"]        # <15% of plan colours unexplained


@real
def test_real_parcel_signature_is_stronger_in_the_core_than_in_the_outskirts():
    manifest = json.loads((FIXTURES / "manifest.json").read_text(encoding="utf-8"))
    target = page.EVIDENCE_CONFIG["parcel_window_m"]
    scores = {}
    for entry in manifest["files"]:
        if entry["kind"] == "parcel" and entry["window_m"] == target:
            features = entry.get("parcel_features", {})
            scores[entry["name"]] = features.get("score") if features.get("data") else None
    if not {"core", "outskirts"} <= scores.keys():
        pytest.skip("fixtures need points named 'core' and 'outskirts'")
    assert scores["core"] is not None, "the core window yields no parcel data: thresholds need calibration"
    assert scores["outskirts"] is None or scores["core"] > scores["outskirts"]
