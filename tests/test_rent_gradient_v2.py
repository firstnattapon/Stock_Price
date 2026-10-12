"""Rent_Gradient_V2 keeps every calculation of Rent_Gradient and only names its invalidation rules.

Offline. Checks that (1) the calculation functions are source-identical in V1 and V2, (2) the new
``StateManager.invalidate_*`` rules clear exactly the layers the old ``clear_results([...])`` call
sites did, and (3) no literal-list ``clear_results`` call is left at a call site.
"""
import importlib.util
import inspect
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load(name: str, relative: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


v1 = _load("rent_gradient_v1_for_v2_test", "pages/Rent_Gradient.py")
v2 = _load("rent_gradient_v2_test", "pages/Rent_Gradient_V2.py")

CALCULATION_FUNCTIONS = [
    "fit_rent_gradient_from_samples",
    "compute_rent_gradient_data",
    "resolve_cbd_anchor",
    "isochrone_max_distance_km",
    "build_rent_rings_geojson",
    "build_rent_nodes_geojson",
    "build_ring_report",
    "calculate_intersection",
    "compute_weighted_closeness",
    "compute_golden_land_opportunities",
    "_compute_centrality_impl",
    "find_cbd_anchors",
    "run_evidence_stage",
    "classify_anchor_confidence",
    "perform_calculation",
    "perform_network_analysis",
    "perform_rent_gradient",
]


@pytest.mark.parametrize("name", CALCULATION_FUNCTIONS)
def test_calculation_source_is_identical_in_v1_and_v2(name):
    assert inspect.getsource(getattr(v1, name)) == inspect.getsource(getattr(v2, name))


def test_config_constants_are_identical():
    for name in ("NETWORK_CONFIG", "ANCHOR_CONFIG", "RENT_CONFIG", "EVIDENCE_CONFIG", "OVERPASS_CONFIG"):
        assert getattr(v1, name) == getattr(v2, name), name


def _session_after(monkeypatch, call):
    """Fill every result key with a sentinel, run ``call``, return which keys were cleared."""
    sm = v2.StateManager
    keys = [sm.K_ISOCHRONE, sm.K_INTERSECTION, sm.K_NETWORK, sm.K_RENT_DATA,
            sm.K_AUTO_ANCHOR, sm.K_AUTO_ANCHOR_CLOSENESS, sm.K_AUTO_ANCHOR_EVIDENCE]
    fake = {key: "kept" for key in keys}
    monkeypatch.setattr(v2.st, "session_state", fake)
    call()
    return {key for key in keys if fake[key] is None}


@pytest.mark.parametrize(
    "rule, old_layers",
    [
        ("invalidate_markers", ["isochrone", "intersection", "rent"]),
        ("invalidate_anchors", ["anchor", "anchor_closeness", "anchor_evidence"]),
        ("invalidate_rent", ["rent"]),
    ],
)
def test_invalidation_rule_clears_the_same_layers_as_the_old_call(monkeypatch, rule, old_layers):
    new = _session_after(monkeypatch, getattr(v2.StateManager, rule))
    old = _session_after(monkeypatch, lambda: v2.StateManager.clear_results(old_layers))
    assert new == old and new


def test_marker_rule_keeps_network_and_anchors(monkeypatch):
    sm = v2.StateManager
    cleared = _session_after(monkeypatch, sm.invalidate_markers)
    assert cleared == {sm.K_ISOCHRONE, sm.K_INTERSECTION, sm.K_RENT_DATA}


def test_no_literal_layer_list_is_left_at_a_call_site():
    source = (ROOT / "pages/Rent_Gradient_V2.py").read_text(encoding="utf-8")
    assert not re.search(r"StateManager\.clear_results\(\[", source)
    assert "_refresh_rent()" in source


def test_refresh_rent_clears_rent_then_recomputes_quietly(monkeypatch):
    calls = []
    monkeypatch.setattr(v2.StateManager, "invalidate_rent", classmethod(lambda cls: calls.append("clear")))
    monkeypatch.setattr(v2, "perform_rent_gradient", lambda quiet=False: calls.append(("rent", quiet)))
    v2._refresh_rent()
    assert calls == ["clear", ("rent", True)]
