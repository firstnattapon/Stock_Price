"""I/O — OSM graph disk cache, restricted unpickling, Overpass fetch with failover, isochrone API. No streamlit.

Definitions are cut verbatim from pages/Rent_Gradient.py (see tests/test_rg_v2_equivalence.py).
"""


import hashlib
import io
import json
import networkx as nx
import os
import osmnx as ox
import pickle
import requests
import threading
import time
import zipfile
from pathlib import Path
from shapely import wkt
from typing import Any, Dict, List, Optional, Tuple

from .config import ANCHOR_CONFIG, MAX_CACHE_ENTRY_BYTES, OVERPASS_CONFIG, TIMEOUT_API, _CACHE_FILE_RE, _OVERPASS_LOCK, _PICKLE_ALLOWED_CLASS_PREFIXES, _PICKLE_ALLOWED_GLOBALS, _PICKLE_SAFE_BUILTINS


# Cache Directory (disk-based OSM graph storage)
CACHE_DIR: Path = Path("./cache")


def safe_fetch_isochrone(
    api_key: str,
    travel_mode: str,
    ranges_str: str,
    marker_lat: float,
    marker_lon: float,
) -> Tuple[Optional[List[Dict[str, Any]]], Optional[str]]:
    """
    Fetch isochrone data from Geoapify with full error handling.

    Returns:
        ``(features_list, None)`` on success,
        ``(None, error_message)`` on failure.
    """
    url = "https://api.geoapify.com/v1/isoline"
    params: Dict[str, Any] = {
        "lat": marker_lat,
        "lon": marker_lon,
        "type": "time",
        "mode": travel_mode,
        "range": ranges_str,
        "apiKey": api_key,
    }

    try:
        response = requests.get(url, params=params, timeout=TIMEOUT_API)

        if response.status_code == 200:
            data = response.json()
            features = data.get("features")
            if features is None:
                return None, "API response missing 'features' data"
            return features, None
        elif response.status_code == 401:
            return None, "❌ Invalid API Key – Please check your Geoapify API key"
        elif response.status_code == 403:
            return None, "❌ API Key Forbidden – Check your account permissions"
        elif response.status_code == 429:
            return None, "⚠️ Rate Limit Exceeded – Please wait before retrying"
        else:
            return None, f"API Error (Status {response.status_code}): {response.text[:100]}"

    except requests.Timeout:
        return None, "⏱️ Request Timeout – API took too long to respond"
    except requests.ConnectionError:
        return None, "🌐 Connection Error – Check your internet connection"
    except requests.RequestException as e:
        return None, f"Network Error: {str(e)}"
    except json.JSONDecodeError:
        return None, "Invalid JSON response from API"
    except Exception as e:
        return None, f"Unexpected Error: {str(e)}"


def get_cache_key(polygon_wkt_str: str, network_type: str) -> str:
    """Generate a stable cache key from polygon bounds + network type."""
    polygon = wkt.loads(polygon_wkt_str)
    bounds = polygon.bounds  # (minx, miny, maxx, maxy)
    rounded_bounds = tuple(round(b, 3) for b in bounds)
    key_str = f"{rounded_bounds}_{network_type}"
    return hashlib.md5(key_str.encode()).hexdigest()


class _RestrictedUnpickler(pickle.Unpickler):
    """Allow-list unpickler: only graph data containers can be reconstructed."""

    def find_class(self, module: str, name: str) -> Any:
        if module == "builtins" and name in _PICKLE_SAFE_BUILTINS:
            return super().find_class(module, name)
        if (module, name) in _PICKLE_ALLOWED_GLOBALS:
            return super().find_class(module, name)
        if module.startswith(_PICKLE_ALLOWED_CLASS_PREFIXES):
            obj = super().find_class(module, name)
            if isinstance(obj, type):  # classes only, never helper functions
                return obj
        raise pickle.UnpicklingError(f"Blocked global in cache file: {module}.{name}")


def safe_pickle_loads(data: bytes) -> Any:
    """Deserialize ``data`` with the allow-list; raises ``UnpicklingError`` otherwise."""
    return _RestrictedUnpickler(io.BytesIO(data)).load()


def _load_graph_bytes(data: bytes) -> nx.MultiDiGraph:
    """Restricted load plus a shape check — never trust the file's own claims."""
    graph = safe_pickle_loads(data)
    if not isinstance(graph, nx.Graph):
        raise ValueError("Cache entry is not a NetworkX graph.")
    return graph


def load_graph_from_cache(cache_key: str) -> Optional[nx.MultiDiGraph]:
    """Load a cached OSM graph from disk (restricted unpickler; ``None`` if unsafe)."""
    cache_file = CACHE_DIR / f"osm_graph_{cache_key}.pkl"
    if cache_file.exists():
        try:
            return _load_graph_bytes(cache_file.read_bytes())
        except Exception:
            return None
    return None


def _atomic_write(path: Path, data: bytes) -> None:
    tmp_file = path.with_name(f"{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        tmp_file.write_bytes(data)
        os.replace(tmp_file, path)
    except Exception:
        try:
            tmp_file.unlink()
        except OSError:
            pass
        raise


def save_graph_to_cache(
    cache_key: str,
    graph: nx.MultiDiGraph,
    footprint_wkt: Optional[str] = None,
    network_type: Optional[str] = None,
) -> None:
    """Persist an OSM graph atomically so readers never see a partial file.

    With ``footprint_wkt`` and ``network_type`` a small JSON sidecar records which
    polygon the graph covers, so a later request wholly inside it can be served
    from this entry instead of downloading again (see ``_reuse_covering_graph``).
    """
    cache_file = CACHE_DIR / f"osm_graph_{cache_key}.pkl"
    try:
        _atomic_write(cache_file, pickle.dumps(graph, protocol=pickle.HIGHEST_PROTOCOL))
    except Exception:
        return  # Caching is best-effort
    if footprint_wkt and network_type:
        try:
            footprint = wkt.loads(footprint_wkt)
            meta = {
                "version": 1, "network_type": network_type,
                "footprint_wkt": wkt.dumps(footprint, rounding_precision=6),
                "bounds": list(footprint.bounds), "nodes": len(graph),
                "edges": graph.number_of_edges(),
                "saved_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "endpoint": graph.graph.get("overpass_endpoint"),
            }
            _atomic_write(cache_file.with_suffix(".json"),
                          json.dumps(meta, ensure_ascii=False).encode("utf-8"))
        except Exception:
            pass  # a missing sidecar only disables reuse of this entry


def _read_cache_sidecar(cache_key: str) -> Optional[Dict[str, Any]]:
    """Footprint metadata of a cache entry, or ``None`` (legacy entry / corrupt sidecar)."""
    try:
        meta = json.loads(
            (CACHE_DIR / f"osm_graph_{cache_key}.json").read_text(encoding="utf-8"))
        return meta if meta.get("version") == 1 and meta.get("footprint_wkt") else None
    except Exception:
        return None


def _footprint_covers(meta: Dict[str, Any], requested: Any) -> bool:
    """True when the cached download footprint contains the requested polygon.

    The stored footprint is rounded to 1e-6 degrees, so allow ~1 m of slack.
    """
    try:
        footprint = wkt.loads(meta["footprint_wkt"])
        if not footprint.is_valid:
            footprint = footprint.buffer(0)
        return bool(footprint.buffer(1e-5).contains(requested))
    except Exception:
        return False


def find_covering_cache_key(polygon_wkt_str: str, network_type: str) -> Optional[str]:
    """Key of the smallest cached graph of ``network_type`` whose footprint contains the polygon.

    Reads only the tiny sidecars. Partial coverage is never used (it would bias the
    analysis near the boundary) and entries without a sidecar are not indexed.
    """
    if not ANCHOR_CONFIG["reuse_covering_cache"] or not CACHE_DIR.exists():
        return None
    try:
        requested = wkt.loads(polygon_wkt_str)
    except (ValueError, TypeError):
        return None
    rx0, ry0, rx1, ry1 = requested.bounds
    best: Optional[Tuple[float, str]] = None
    for sidecar in CACHE_DIR.glob("osm_graph_*.json"):
        try:
            meta = json.loads(sidecar.read_text(encoding="utf-8"))
            if meta.get("version") != 1 or meta.get("network_type") != network_type:
                continue
            x0, y0, x1, y1 = meta["bounds"]
            if not (x0 <= rx0 and y0 <= ry0 and x1 >= rx1 and y1 >= ry1):
                continue  # cheap reject before parsing the footprint
            if not sidecar.with_suffix(".pkl").exists():
                continue
            footprint = wkt.loads(meta["footprint_wkt"])
            if not footprint.is_valid:
                footprint = footprint.buffer(0)
            if footprint.contains(requested) and (best is None or footprint.area < best[0]):
                best = (footprint.area, sidecar.stem[len("osm_graph_"):])
        except Exception:
            continue  # corrupt sidecar: ignore, never fail the request
    return best[1] if best else None


def cached_graph_available(polygon_wkt_str: str, network_type: str) -> bool:
    """True when a request can be served without Overpass (exact or covering cache)."""
    key = get_cache_key(polygon_wkt_str, network_type)
    if (CACHE_DIR / f"osm_graph_{key}.pkl").exists():
        meta = _read_cache_sidecar(key)
        try:
            if meta is None or _footprint_covers(meta, wkt.loads(polygon_wkt_str)):
                return True
        except (ValueError, TypeError):
            return False
    return find_covering_cache_key(polygon_wkt_str, network_type) is not None


def _reuse_covering_graph(
    polygon_wkt_str: str, polygon_geom: Any, network_type: str, cache_key: str
) -> Optional[nx.MultiDiGraph]:
    """Crop a covering cached graph to the polygon (same rule as ``graph_from_polygon``)."""
    source_key = find_covering_cache_key(polygon_wkt_str, network_type)
    if source_key is None or source_key == cache_key:
        return None
    superset = load_graph_from_cache(source_key)
    if superset is None:
        return None
    try:
        cropped = ox.truncate.truncate_graph_polygon(superset, polygon_geom, truncate_by_edge=True)
        cropped = ox.truncate.largest_component(cropped, strongly=False)
    except Exception:
        return None  # e.g. no nodes inside the polygon: fall back to a real download
    if len(cropped) < 2:
        return None
    cropped.graph["reused_from"] = source_key
    cropped.graph["osm_source"] = "cache-crop"
    save_graph_to_cache(cache_key, cropped, polygon_wkt_str, network_type)
    return cropped


def get_cache_stats() -> Dict[str, Any]:
    """Return ``{count, size_mb}`` for the disk cache."""
    if not CACHE_DIR.exists():
        return {"count": 0, "size_mb": 0.0}
    cache_files = list(CACHE_DIR.glob("osm_graph_*.pkl"))
    total_size = sum(f.stat().st_size for f in cache_files)
    return {"count": len(cache_files), "size_mb": total_size / (1024 * 1024)}


def clear_disk_cache() -> None:
    """Delete all cached OSM graphs."""
    if CACHE_DIR.exists():
        for cache_file in CACHE_DIR.glob("osm_graph_*.pkl"):
            try:
                cache_file.unlink()
            except Exception:
                pass


def export_cache_as_zip() -> Optional[bytes]:
    """Create an in-memory ZIP of all cached graphs."""
    if not CACHE_DIR.exists():
        return None
    cache_files = list(CACHE_DIR.glob("osm_graph_*.pkl"))
    if not cache_files:
        return None

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for cache_file in cache_files:
            zf.write(cache_file, cache_file.name)
    zip_buffer.seek(0)
    return zip_buffer.getvalue()


def import_cache_from_zip(zip_bytes: bytes) -> Dict[str, Any]:
    """Import cache entries from a ZIP archive."""
    result: Dict[str, Any] = {
        "success": False,
        "imported": 0,
        "skipped": 0,
        "errors": [],
    }

    try:
        CACHE_DIR.mkdir(exist_ok=True)
        zip_buffer = io.BytesIO(zip_bytes)
        with zipfile.ZipFile(zip_buffer, "r") as zf:
            for file_info in zf.infolist():
                name = file_info.filename
                # Exact file-name pattern: no path separators, no traversal.
                if not _CACHE_FILE_RE.match(name):
                    result["errors"].append(f"Skipped invalid file: {name}")
                    continue
                if file_info.file_size > MAX_CACHE_ENTRY_BYTES:
                    result["errors"].append(f"Skipped oversized file: {name}")
                    continue

                target_path = CACHE_DIR / name
                if target_path.exists():
                    result["skipped"] += 1
                    continue

                try:
                    # Validate through the allow-list (never plain pickle.load), then
                    # write our own serialisation so the stored bytes are known-good.
                    graph = _load_graph_bytes(zf.read(name))
                    save_graph_to_cache(name[len("osm_graph_"):-len(".pkl")], graph)
                    if not target_path.exists():
                        raise OSError("could not write cache entry")
                    result["imported"] += 1
                except Exception as e:
                    result["errors"].append(f"Failed to import {name}: {str(e)}")

        result["success"] = result["imported"] > 0 or result["skipped"] > 0
    except zipfile.BadZipFile:
        result["errors"].append("Invalid ZIP file format")
    except Exception as e:
        result["errors"].append(f"Import failed: {str(e)}")

    return result


def _fetch_osm_graph(
    polygon_wkt_str: str, network_type: str
) -> Tuple[Optional[nx.MultiDiGraph], bool, Optional[str]]:
    """
    Fetch an OSM graph for a polygon, with disk-cache lookup.

    Returns:
        ``(graph, was_cached, error_message)``
    """
    try:
        cache_key = get_cache_key(polygon_wkt_str, network_type)
        polygon_geom = wkt.loads(polygon_wkt_str)
    except (ValueError, TypeError) as exc:
        return None, False, f"Invalid geometry: {exc}"

    # A deployment may put its own/self-hosted endpoints first without code
    # changes. Values are base API URLs: OSMnx appends /status and /interpreter.
    env_endpoints = [
        value.strip().rstrip("/").removesuffix("/interpreter")
        for value in os.getenv("OVERPASS_ENDPOINTS", "").split(",")
        if value.strip()
    ]
    attempts = max(1, int(OVERPASS_CONFIG["attempts_per_endpoint"]))
    failures: List[str] = []

    def exact_hit() -> Optional[nx.MultiDiGraph]:
        """Exact-key entry, trusted only if its recorded footprint covers the request.

        The key is the md5 of bounds rounded to 3 dp, so a differently shaped polygon
        with the same bounds shares it. Entries without a sidecar (imported bundles,
        caches from before footprints were recorded) cannot be checked and are used as
        before, but labelled so the UI does not claim more than is known.
        """
        graph = load_graph_from_cache(cache_key)
        if graph is None:
            return None
        meta = _read_cache_sidecar(cache_key)
        if meta is None:
            graph.graph["osm_source"] = "cache (footprint unverified)"
            return graph
        if not _footprint_covers(meta, polygon_geom):
            return None  # same key, different shape: fall through to crop / download
        graph.graph["osm_source"] = "cache"
        return graph

    # Fast paths outside the lock: a cache hit (exact, or a cached graph that fully
    # covers this polygon) must not queue behind another session's download.
    G = exact_hit()
    if G is not None:
        return G, True, None
    G = _reuse_covering_graph(polygon_wkt_str, polygon_geom, network_type, cache_key)
    if G is not None:
        return G, True, None

    with _OVERPASS_LOCK:
        original_url = ox.settings.overpass_url
        # Re-check: a session that held the lock may have just filled the cache.
        G = exact_hit()
        if G is not None:
            return G, True, None

        endpoints: List[str] = []
        for endpoint in [*env_endpoints, original_url,
                         *OVERPASS_CONFIG["endpoints"]]:
            endpoint = str(endpoint).strip().rstrip("/").removesuffix("/interpreter")
            if endpoint and endpoint not in endpoints:
                endpoints.append(endpoint)
        try:
            for endpoint in endpoints:
                ox.settings.overpass_url = endpoint
                for attempt in range(1, attempts + 1):
                    try:
                        G = ox.graph_from_polygon(
                            polygon_geom,
                            network_type=network_type,
                            truncate_by_edge=True,
                        )
                        G.graph["overpass_endpoint"] = endpoint
                        G.graph["osm_source"] = "download"
                        save_graph_to_cache(cache_key, G, polygon_wkt_str, network_type)
                        return G, False, None
                    except ox._errors.InsufficientResponseError:
                        return None, False, (
                            "No OSM road data available for this area. "
                            "Try a different location, network mode, or larger region."
                        )
                    except (ox._errors.ValidationError,
                            ox._errors.GraphSimplificationError) as exc:
                        return None, False, f"Invalid OSM graph request: {exc}"
                    except Exception as exc:
                        short_error = " ".join(str(exc).split())[:300]
                        failures.append(
                            f"{endpoint} (attempt {attempt}/{attempts}): {short_error}"
                        )
                        if attempt < attempts:
                            time.sleep(float(OVERPASS_CONFIG["retry_backoff_seconds"]))
        finally:
            ox.settings.overpass_url = original_url

    details = " | ".join(failures)
    return None, False, (
        f"Failed to fetch OSM graph after trying {len(endpoints)} Overpass servers. "
        f"Check internet/proxy access or set OVERPASS_ENDPOINTS to a reachable base URL. "
        f"Attempts: {details}"
    )
