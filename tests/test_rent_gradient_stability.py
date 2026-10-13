"""Failure-path stability of pages/Rent_Gradient.py (all offline).

Every test pins a path that used to fail or hang; the successful paths are pinned by the older
test files. Streamlit re-executes a page script on every rerun, which the module-level tests below
imitate by executing the file again under the same module name.
"""
import ast
import copy
import importlib.util
import io
import json
import logging
import pathlib
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PAGE_PATH = ROOT / "pages/Rent_Gradient.py"
MODULE = "rent_gradient_stability_test"


def load_page():
    spec = importlib.util.spec_from_file_location(MODULE, PAGE_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[MODULE] = module
    spec.loader.exec_module(module)
    return module


page = load_page()


class Response:
    def __init__(self, status_code, payload=None):
        self.status_code, self._payload = status_code, payload

    def json(self):
        return self._payload


# ------------------------------------------------- a failure is retried, never replayed from the cache
def test_failed_isochrone_fetch_is_retried_and_only_success_is_cached(monkeypatch):
    outcomes = iter([(None, "⏱️ Request Timeout"), ([{"type": "Feature"}], None)])
    calls = []
    monkeypatch.setattr(page, "safe_fetch_isochrone", lambda *args: calls.append(args) or next(outcomes))
    args = ("key", "drive", "300", 41.5, 100.5)          # a cache key no other test uses
    assert page.fetch_api_data_cached(*args) == (None, "⏱️ Request Timeout")
    assert page.fetch_api_data_cached(*args) == ([{"type": "Feature"}], None)
    assert page.fetch_api_data_cached(*args) == ([{"type": "Feature"}], None)
    assert len(calls) == 2


def test_failed_network_analysis_is_retried_and_only_success_is_cached(monkeypatch):
    outcomes = iter([{"error": "Overpass down"}, {"edges": {}, "stats": {}}])
    monkeypatch.setattr(page, "_compute_centrality_impl", lambda *args: next(outcomes))
    polygon = "POLYGON ((100.1 20.1, 100.2 20.1, 100.2 20.2, 100.1 20.1))"
    assert page.compute_centrality_cached(polygon, "drive") == {"error": "Overpass down"}
    assert page.compute_centrality_cached(polygon, "drive") == {"edges": {}, "stats": {}}
    assert page.compute_centrality_cached(polygon, "drive") == {"edges": {}, "stats": {}}
    assert next(outcomes, "exhausted") == "exhausted"      # the computation ran exactly twice


# ------------------------------------------------- module level state under per-rerun execution
def test_page_still_imports_when_the_cache_dir_cannot_be_created(monkeypatch):
    def refuse(self, *args, **kwargs):
        raise PermissionError("read-only file system")

    monkeypatch.setattr(pathlib.Path, "mkdir", refuse)
    try:
        module = load_page()
    finally:
        sys.modules[MODULE] = page
    assert module.CACHE_DIR == pathlib.Path("./cache")


def test_overpass_lock_is_one_lock_for_every_script_run():
    try:
        rerun = load_page()                                # what Streamlit does on every rerun
    finally:
        sys.modules[MODULE] = page
    assert rerun._OVERPASS_LOCK is page._OVERPASS_LOCK


def test_session_defaults_are_copies_not_the_class_level_objects(monkeypatch):
    monkeypatch.setattr(page.StateManager, "_load_remote_defaults", staticmethod(lambda defaults: None))
    sessions = []
    for _ in range(2):
        state = {}
        monkeypatch.setattr(page.st, "session_state", state)
        page.StateManager.initialize()
        sessions.append(state)
    first, second = sessions
    assert first["colors"] is not second["colors"]
    assert first["colors"] is not page.StateManager._DEFAULTS["colors"]
    first["time_intervals"].append(99)
    first["rent_samples"].append({"lat": 1.0, "lon": 2.0, "rent": 3.0})
    assert second["time_intervals"] == [5] and second["rent_samples"] == []
    assert page.StateManager._DEFAULTS["time_intervals"] == [5]


# ------------------------------------------------- imported / remote settings the page cannot consume
BAD_IMPORT = {
    "markers": [{"lat": "north", "lng": 100.0}],
    "settings": {
        "colors": {"step1": "#ffffff"},
        "rent_samples": [{"lat": 20.0, "lon": 100.0, "rent": float("nan")}],
    },
    "precomputed_results": {"isochrone_data": [1, 2, 3]},
}


def fresh_state(monkeypatch):
    state = dict(copy.deepcopy(page.StateManager._DEFAULTS))
    state["markers"] = [{"lat": 20.0, "lng": 100.0, "active": True}]
    monkeypatch.setattr(page.st, "session_state", state)
    return state


def test_import_config_skips_structures_the_page_cannot_use_and_names_them(monkeypatch):
    state = fresh_state(monkeypatch)
    before = copy.deepcopy(state)
    skipped = page.StateManager.import_config(copy.deepcopy(BAD_IMPORT))
    assert state == before                                 # nothing unusable reached the session
    assert sorted(skipped) == ["colors", "isochrone_data", "markers", "rent_samples"]


def test_a_valid_config_imports_whole_and_reports_nothing_skipped(monkeypatch):
    state = fresh_state(monkeypatch)
    state["rent_samples"] = [{"lat": 20.1, "lon": 100.2, "rent": 5000.0}]
    state["show_dol"] = True
    exported = json.loads(page.StateManager.export_config())
    before = copy.deepcopy(state)
    assert page.StateManager.import_config(exported) == []
    # the UI-only "Lat, Lon" widget key has always been synchronised by import_config
    assert {k: v for k, v in state.items() if k != "anchor_center_input"} == before
    assert json.loads(page.StateManager.export_config()) == exported


def test_bundle_import_reports_the_skipped_keys_as_a_warning(monkeypatch):
    fresh_state(monkeypatch)
    config = json.dumps(BAD_IMPORT).encode()
    manifest = {"bundle_version": page.BUNDLE_VERSION, "config_schema_version": page.CONFIG_SCHEMA_VERSION,
                "integrity_checksums": {"config/config.json": page._sha256_bytes(config),
                                        "cache/cache.zip": page._sha256_bytes(b"")}}
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr("manifest.json", json.dumps(manifest))
        zf.writestr("config/config.json", config)
        zf.writestr("cache/cache.zip", b"")
        zf.writestr("checksums.sha256", "")
    result = page.import_bundle_zip(buffer.getvalue())
    assert result["success"] and not result["errors"]
    assert any("markers" in warning and "colors" in warning for warning in result["warnings"])


def test_remote_defaults_with_unusable_structures_fall_back_to_the_built_in_ones(monkeypatch):
    remote = {"markers": "oops", "colors": {"step1": 1}, "show_dol": True}
    monkeypatch.setattr(page.requests, "get", lambda *args, **kwargs: Response(200, remote))
    defaults = copy.deepcopy(page.StateManager._DEFAULTS)
    assert page.StateManager._load_remote_defaults(defaults) is None
    assert defaults["colors"] == page.StateManager._DEFAULTS["colors"]
    assert defaults["show_dol"] is True                    # settings the page can use are still applied


def test_remote_defaults_with_usable_structures_are_applied_as_before(monkeypatch):
    remote = {"markers": [{"lat": 20.1, "lng": 100.1}], "show_dol": True,
              "colors": {"step1": "#111111", "step2": "#222222", "step3": "#333333", "step4": "#444444"}}
    monkeypatch.setattr(page.requests, "get", lambda *args, **kwargs: Response(200, remote))
    defaults = copy.deepcopy(page.StateManager._DEFAULTS)
    assert page.StateManager._load_remote_defaults(defaults) == remote["markers"]
    assert defaults["colors"] == remote["colors"] and defaults["show_dol"] is True


# ------------------------------------------------- an archive member over the limit is never inflated
def test_bundle_cache_member_over_the_limit_is_not_inflated(monkeypatch):
    monkeypatch.setattr(page, "MAX_CACHE_ENTRY_BYTES", 1024)
    monkeypatch.setattr(page.st, "session_state", copy.deepcopy(page.StateManager._DEFAULTS))
    config, cache = json.dumps({"markers": []}).encode(), b"\0" * 4096     # stands for a zip bomb
    manifest = {"bundle_version": page.BUNDLE_VERSION, "config_schema_version": page.CONFIG_SCHEMA_VERSION,
                "integrity_checksums": {"config/config.json": page._sha256_bytes(config),
                                        "cache/cache.zip": page._sha256_bytes(cache)}}
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps(manifest))
        zf.writestr("config/config.json", config)
        zf.writestr("cache/cache.zip", cache)
        zf.writestr("checksums.sha256", "")
    reads, real_read = [], zipfile.ZipFile.read
    monkeypatch.setattr(zipfile.ZipFile, "read",
                        lambda self, name, *args, **kwargs: reads.append(name) or real_read(self, name, *args, **kwargs))
    result = page.import_bundle_zip(buffer.getvalue())
    assert "cache/cache.zip" not in reads
    assert result["success"] and not result["cache_loaded"]
    assert any("ใหญ่เกินกำหนด" in warning for warning in result["warnings"])


# ------------------------------------------------- one failing section does not blank the page
def app_test(monkeypatch):
    from streamlit.testing.v1 import AppTest

    def app():
        import rent_gradient_stability_test
        rent_gradient_stability_test.main()

    monkeypatch.setattr(page.StateManager, "_load_remote_defaults", staticmethod(lambda defaults: []))
    return AppTest.from_function(app)


def explode(*args, **kwargs):
    raise RuntimeError("section exploded")


def test_streamlit_a_failing_header_section_still_renders_the_rest_of_the_page(monkeypatch):
    monkeypatch.setattr(page, "render_metrics_row", explode)
    at = app_test(monkeypatch).run(timeout=30)
    assert [e.value for e in at.exception] == ["section exploded"]    # shown in place, like Streamlit's own box
    assert len(at.tabs) == 5                                          # the analytics panel after it still renders
    assert any(b.label == "🚀 Run Network Analysis" for b in at.sidebar.button)


def test_streamlit_a_failing_sidebar_panel_keeps_the_other_panels_and_reset(monkeypatch):
    monkeypatch.setattr(page, "_render_sidebar_network_panel", explode)
    at = app_test(monkeypatch).run(timeout=30)
    assert [e.value for e in at.exception] == ["section exploded"]
    labels = {b.label for b in at.sidebar.button}
    assert {"🔄 รีเซ็ต", "🧮 คำนวณ Rent Gradient", "🎯 ค้นหา CBD Anchor อัตโนมัติ"} <= labels
    assert len(at.tabs) == 5


def test_streamlit_a_failing_calculation_step_does_not_stop_the_page(monkeypatch):
    monkeypatch.setattr(page, "perform_rent_gradient", explode)
    at = app_test(monkeypatch)
    at.session_state["isochrone_data"] = {"type": "FeatureCollection", "features": []}    # enables the button
    at.run(timeout=30)
    assert not at.exception
    next(b for b in at.sidebar.button if b.label == "🧮 คำนวณ Rent Gradient").click().run(timeout=30)
    assert [e.value for e in at.exception] == ["section exploded"]
    assert len(at.tabs) == 5


