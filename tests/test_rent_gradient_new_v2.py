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
}
# Replaced by new SHELL code (the behaviour moved into the layer registry / panels / views).
REPLACED = {}

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
    again = load(PAGE, "rent_gradient_new_v2_under_test")      # what a Streamlit rerun does: same name, fresh module
    assert again is not v2 and again._OVERPASS_LOCK is first
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
