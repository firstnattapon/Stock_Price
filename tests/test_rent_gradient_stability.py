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


