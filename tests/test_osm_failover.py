"""Overpass failover tests: no internet access is used."""
import importlib.util
from pathlib import Path
import sys

import networkx as nx
import requests

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("rent_gradient_failover_test", ROOT / "pages/Rent_Gradient.py")
page = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = page
spec.loader.exec_module(page)

POLYGON = "POLYGON ((100 20, 100.01 20, 100.01 20.01, 100 20.01, 100 20))"


def graph():
    result = nx.MultiDiGraph(crs="EPSG:4326")
    result.add_node(1, x=100.0, y=20.0)
    result.add_node(2, x=100.001, y=20.001)
    result.add_edge(1, 2, length=100.0)
    return result


def configure(monkeypatch, tmp_path, endpoints, attempts=2):
    monkeypatch.setattr(page, "CACHE_DIR", tmp_path)
    monkeypatch.setitem(page.OVERPASS_CONFIG, "endpoints", endpoints)
    monkeypatch.setitem(page.OVERPASS_CONFIG, "attempts_per_endpoint", attempts)
    monkeypatch.setitem(page.OVERPASS_CONFIG, "retry_backoff_seconds", 0)
    monkeypatch.delenv("OVERPASS_ENDPOINTS", raising=False)


def test_connection_refused_retries_then_uses_backup_and_cache(monkeypatch, tmp_path):
    primary = "https://primary.example/api"
    backup = "https://backup.example/api"
    configure(monkeypatch, tmp_path, [primary, backup])
    monkeypatch.setattr(page.ox.settings, "overpass_url", primary)
    calls = []

    def fake_download(*args, **kwargs):
        endpoint = page.ox.settings.overpass_url
        calls.append(endpoint)
        if endpoint == primary:
            raise requests.ConnectionError("connection refused")
        return graph()

    monkeypatch.setattr(page.ox, "graph_from_polygon", fake_download)
    downloaded, cached, error = page._fetch_osm_graph(POLYGON, "drive")

    assert error is None
    assert not cached
    assert calls == [primary, primary, backup]
    assert downloaded.graph["overpass_endpoint"] == backup
    assert page.ox.settings.overpass_url == primary

    calls.clear()
    downloaded, cached, error = page._fetch_osm_graph(POLYGON, "drive")
    assert error is None
    assert cached
    assert calls == []
    assert downloaded.graph["overpass_endpoint"] == backup


def test_environment_endpoint_is_first_and_interpreter_suffix_is_removed(monkeypatch, tmp_path):
    configure(monkeypatch, tmp_path, ["https://backup.example/api"], attempts=1)
    original = "https://primary.example/api"
    monkeypatch.setattr(page.ox.settings, "overpass_url", original)
    monkeypatch.setenv("OVERPASS_ENDPOINTS", " https://self-hosted.example/api/interpreter/ ")
    calls = []

    def fake_download(*args, **kwargs):
        calls.append(page.ox.settings.overpass_url)
        return graph()

    monkeypatch.setattr(page.ox, "graph_from_polygon", fake_download)
    downloaded, cached, error = page._fetch_osm_graph(POLYGON, "walk")

    assert error is None
    assert not cached
    assert calls == ["https://self-hosted.example/api"]
    assert downloaded.graph["overpass_endpoint"] == calls[0]
    assert page.ox.settings.overpass_url == original


def test_all_servers_fail_with_actionable_bounded_diagnostics(monkeypatch, tmp_path):
    primary = "https://primary.example/api"
    backup = "https://backup.example/api"
    configure(monkeypatch, tmp_path, [backup], attempts=1)
    monkeypatch.setattr(page.ox.settings, "overpass_url", primary)

    def fake_download(*args, **kwargs):
        raise requests.ConnectionError("connection refused " + "x" * 1000)

    monkeypatch.setattr(page.ox, "graph_from_polygon", fake_download)
    downloaded, cached, error = page._fetch_osm_graph(POLYGON, "bike")

    assert downloaded is None
    assert not cached
    assert "after trying 2 Overpass servers" in error
    assert primary in error and backup in error
    assert "OVERPASS_ENDPOINTS" in error
    assert len(error) < 1000
    assert page.ox.settings.overpass_url == primary


def test_empty_osm_response_is_not_retried_on_other_servers(monkeypatch, tmp_path):
    primary = "https://primary.example/api"
    configure(monkeypatch, tmp_path, ["https://backup.example/api"])
    monkeypatch.setattr(page.ox.settings, "overpass_url", primary)
    calls = []

    def fake_download(*args, **kwargs):
        calls.append(page.ox.settings.overpass_url)
        raise page.ox._errors.InsufficientResponseError("empty")

    monkeypatch.setattr(page.ox, "graph_from_polygon", fake_download)
    downloaded, cached, error = page._fetch_osm_graph(POLYGON, "drive")

    assert downloaded is None
    assert not cached
    assert calls == [primary]
    assert "No OSM road data" in error
    assert page.ox.settings.overpass_url == primary
