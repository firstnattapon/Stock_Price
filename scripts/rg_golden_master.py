#!/usr/bin/env python
"""Golden master of a Rent_Gradient page: a SHA-256 digest of every observable output (46 cases).

    python scripts/rg_golden_master.py pages/Rent_Gradient.py    /tmp/v1.json
    python scripts/rg_golden_master.py pages/Rent_Gradient_v2.py /tmp/v2.json
    python scripts/rg_golden_master.py --compare /tmp/v1.json /tmp/v2.json      # exit 0 only if every digest is equal

Layer 1 = engine / I/O functions called with fixed inputs (anchors, closeness, centrality, rent, evidence, cache, bundle,
state); Layer 2 = Streamlit AppTest renders of the whole page (widget tree, toasts and errors after each click,
``st.session_state``, normalised Folium HTML). Volatile fields (timings, timestamps, hashes of generated media) are
dropped; everything else must match bit for bit, so a refactor that moves one float, one character of text or one
widget changes a digest. Run both pages in the SAME environment: digests are not portable across numpy / GEOS versions.
Extra options: ``--dump DIR`` writes the canonical text behind every digest, ``--only PREFIX`` runs the cases whose
name starts with PREFIX (plus the ones the UI cases need). Takes about a minute and touches only a temporary cache folder.
"""
import contextlib
import hashlib
import importlib.util
import io
import json
import re
import sys
import tempfile
import time
import zipfile
from pathlib import Path
from unittest import mock

if len(sys.argv) == 4 and sys.argv[1] == "--compare":
    first, second = (json.loads(Path(p).read_text(encoding="utf-8")) for p in sys.argv[2:4])
    names = sorted(first.keys() | second.keys())
    differing = [k for k in names if first.get(k) != second.get(k)]
    print(f"{len(names) - len(differing)}/{len(names)} digests equal; differing: {differing}")
    sys.exit(1 if differing else 0)

import networkx as nx
import numpy as np
from pyproj.enums import TransformDirection

PAGE_PATH = Path(sys.argv[1]).resolve()
OUT = Path(sys.argv[2])
DUMP = Path(sys.argv[sys.argv.index("--dump") + 1]) if "--dump" in sys.argv else None
ONLY = sys.argv[sys.argv.index("--only") + 1] if "--only" in sys.argv else None
REPO = PAGE_PATH.parent.parent                                  # pages/<page>.py -> the repo root
assert (REPO / "Geoapify_Map" / "osmnx_cache.zip").exists(), f"{REPO} is not the repo root"

spec = importlib.util.spec_from_file_location("rg_gm_page", PAGE_PATH)
page = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = page
spec.loader.exec_module(page)

def _holders(obj, name):
    """The page plus every package module that re-exports the very same object under ``name`` (layout-independent).
    A name the page does not re-export at all is patched in every package module that has it."""
    package = [m for n, m in list(sys.modules.items()) if m is not None and n.startswith("rg_lib.") and hasattr(m, name)]
    if not hasattr(obj, name):
        return package
    original = getattr(obj, name)
    return [obj] + [m for m in package if getattr(m, name) is original]


def set_everywhere(obj, name, value):
    for target in _holders(obj, name):
        setattr(target, name, value)


CENTER = (20.219443, 100.403630)
REAL_KEY = "d25de118f9e82b8a2e8768e70ec4b5d5"
VOLATILE = {"timings", "compute_seconds", "load_seconds", "total_seconds", "seconds", "saved_at",
            "fetched_at", "created_at_utc", "timestamp", "python", "integrity_checksums"}
TMP = Path(tempfile.mkdtemp(prefix="gm_"))
set_everywhere(page, "CACHE_DIR", TMP / "cache")
page.CACHE_DIR.mkdir()


# ------------------------------------------------------------------ canonical form
def canon(o):
    if isinstance(o, dict):
        return {str(k): canon(v) for k, v in sorted(o.items(), key=lambda kv: str(kv[0])) if str(k) not in VOLATILE}
    if isinstance(o, (list, tuple)):
        return [canon(v) for v in o]
    if isinstance(o, (set, frozenset)):
        return sorted((canon(v) for v in o), key=repr)
    if isinstance(o, (bool, str)) or o is None:
        return o
    if isinstance(o, (int, np.integer)):
        return int(o)
    if isinstance(o, (float, np.floating)):
        f = float(o)
        return repr(f)
    if isinstance(o, np.ndarray):
        return {"nd": list(o.shape), "v": canon(o.tolist())}
    if isinstance(o, (bytes, bytearray)):
        return "bytes:" + hashlib.sha256(bytes(o)).hexdigest()
    if hasattr(o, "wkt"):
        return "wkt:" + o.wkt
    if hasattr(o, "to_dict"):
        return canon(o.to_dict("records"))
    return "repr:" + re.sub(r"0x[0-9a-f]+", "0x", repr(o))


def digest(o):
    text = json.dumps(canon(o), sort_keys=True, ensure_ascii=False, allow_nan=True)
    return hashlib.sha256(text.encode("utf-8")).hexdigest(), text


RESULTS, DUMPS = {}, {}
NEEDED_BY_UI = {"anchors.grid.default", "centrality.grid", "intersection.cases", "rent.data", "evidence.stage"}


def case(name):
    def deco(fn):
        if ONLY and not (name.startswith(ONLY) or name in NEEDED_BY_UI):
            return fn
        try:
            value = fn()
        except Exception as exc:  # an exception is also an output
            value = {"EXC": type(exc).__name__, "msg": str(exc)[:200]}
        h, text = digest(value)
        RESULTS[name] = h
        DUMPS[name] = text
        return fn
    return deco


@contextlib.contextmanager
def patched(obj, **attrs):
    with contextlib.ExitStack() as stack:
        for k, v in attrs.items():
            for target in _holders(obj, k):
                stack.enter_context(mock.patch.object(target, k, v))
        yield



# ------------------------------------------------------------------ fixtures
def road_grid(size=11, spacing=100):
    graph = nx.MultiDiGraph(crs="EPSG:4326")
    projection = page._anchor_projection(*CENTER)
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


page.import_cache_from_zip((REPO / "Geoapify_Map" / "osmnx_cache.zip").read_bytes())
REAL = page.load_graph_from_cache(REAL_KEY)
REAL_CENTER = (float(np.mean([d["y"] for _, d in REAL.nodes(data=True)])),
               float(np.mean([d["x"] for _, d in REAL.nodes(data=True)])))
GRID = road_grid()


def square_wkt(lat, lon, half=0.01):
    return f"POLYGON(({lon-half} {lat-half},{lon+half} {lat-half},{lon+half} {lat+half},{lon-half} {lat+half},{lon-half} {lat-half}))"


# ================================================================== LAYER 1 — engines
@case("anchors.grid.default")
def _():
    return page.find_cbd_anchors(GRID, CENTER, 4000)


@case("anchors.grid.nostability")
def _():
    return page.find_cbd_anchors(GRID, CENTER, 4000, stability=False)


@case("anchors.grid.screened")
def _():
    return page.find_cbd_anchors(GRID, CENTER, 4000, max_rows=40)


@case("anchors.grid.noscipy_error")
def _():
    with patched(page, HAS_SCIPY=False):
        return page.find_cbd_anchors(GRID, CENTER, 4000)


@case("anchors.grid.invalid_args")
def _():
    out = {}
    for label, kw in (("final>study", dict(final_radius_m=9999.0)), ("rows", dict(max_rows=0)),
                      ("radius", dict(study_radius_m=500.0))):
        try:
            page.find_cbd_anchors(GRID, CENTER, **{"study_radius_m": 4000, **kw})
        except Exception as exc:
            out[label] = [type(exc).__name__, str(exc)]
    return out


@case("anchors.real.default")
def _():
    return page.find_cbd_anchors(REAL, REAL_CENTER, 8000)


@case("anchors.real.screened")
def _():
    return page.find_cbd_anchors(REAL, REAL_CENTER, 8000, max_rows=150)


@case("anchors.polygon")
def _():
    return [page.anchor_study_polygon(*REAL_CENTER, r).wkt for r in (1000, 8000)]


@case("closeness.grid.exact")
def _():
    return page.compute_weighted_closeness(GRID.to_undirected())


@case("closeness.real.exact")
def _():
    return page.compute_weighted_closeness(REAL.to_undirected())


@case("closeness.real.pivot")
def _():
    with mock.patch.dict(page.NETWORK_CONFIG, {"closeness_exact_threshold": 100, "closeness_k_pivots": 150}):
        return page.compute_weighted_closeness(REAL.to_undirected())


@case("closeness.noscipy")
def _():
    with patched(page, HAS_SCIPY=False):
        return page.compute_weighted_closeness(GRID.to_undirected())


NETWORK = {}


@case("centrality.grid")
def _():
    with patched(page, _fetch_osm_graph=lambda *a: (GRID, True, None)):
        NETWORK["grid"] = page._compute_centrality_impl(square_wkt(*CENTER, 0.01), "drive")
    return NETWORK["grid"]


@case("centrality.real.exact_betweenness")
def _():
    with patched(page, _fetch_osm_graph=lambda *a: (REAL, False, None)):
        NETWORK["real"] = page._compute_centrality_impl(square_wkt(*REAL_CENTER, 0.05), "drive")
    return NETWORK["real"]


@case("centrality.real.sampled_betweenness")
def _():
    with patched(page, _fetch_osm_graph=lambda *a: (REAL, False, None)), \
            mock.patch.dict(page.NETWORK_CONFIG, {"large_graph_threshold": 50, "betweenness_k_samples": 60}):
        return page._compute_centrality_impl(square_wkt(*REAL_CENTER, 0.05), "drive")


@case("centrality.errors")
def _():
    out = []
    for fetched in ((None, False, "boom"), (None, False, None), (nx.MultiDiGraph(), False, None)):
        with patched(page, _fetch_osm_graph=lambda *a, f=fetched: f):
            out.append(page._compute_centrality_impl(square_wkt(*CENTER), "drive"))
    return out


@case("golden.variants")
def _():
    und = GRID.to_undirected()
    close, _ = page.compute_weighted_closeness(und)
    bet = nx.edge_betweenness_centrality(und, weight="length")
    return [page.compute_golden_land_opportunities(GRID, close, bet, top_n=n, min_spacing_m=s)
            for n, s in ((10, None), (5, 0), (7, 300.0))] + [page.compute_golden_land_opportunities(GRID, {}, {})]


SAMPLE_SETS = {
    "two": [{"lat": 20.22, "lon": 100.41, "rent": 5000}, {"lat": 20.25, "lon": 100.45, "rent": 2500}],
    "five": [{"lat": 20.2194 + i * 0.01, "lon": 100.4036 + i * 0.008, "rent": 9000 * (0.8 ** i)} for i in range(6)],
    "same_distance": [{"lat": 20.22, "lon": 100.41, "rent": 5000}, {"lat": 20.22, "lon": 100.41, "rent": 3000}],
    "bad_rows": [{"lat": "x", "rent": 1}, {"lat": 1, "lon": 2, "rent": -5}, {"lat": 20.3, "lon": 100.5, "rent": 100},
                 {"lat": 20.4, "lon": 100.6, "rent": 50}],
    "inverted": [{"lat": 20.22, "lon": 100.41, "rent": 1000}, {"lat": 20.3, "lon": 100.5, "rent": 4000},
                 {"lat": 20.4, "lon": 100.6, "rent": 9000}, {"lat": 20.5, "lon": 100.7, "rent": 12000}],
    "empty": [],
}


@case("rent.fit")
def _():
    return {k: page.fit_rent_gradient_from_samples(v, *CENTER) for k, v in SAMPLE_SETS.items()}


def feature_collection(boxes, minutes=(10,)):
    from shapely.geometry import box, mapping
    feats = []
    for ai, (x0, y0, x1, y1) in enumerate(boxes):
        for t in minutes:
            feats.append({"type": "Feature", "geometry": mapping(box(x0, y0, x1, y1)),
                          "properties": {"travel_time_minutes": t, "original_index": ai, "active_index": ai}})
    return {"type": "FeatureCollection", "features": feats}


ISO = feature_collection([(100.38, 20.20, 100.43, 20.24), (100.40, 20.21, 100.45, 20.26)], (10, 20))


@case("intersection.cases")
def _():
    feats = ISO["features"]
    return [page.calculate_intersection(feats, 2), page.calculate_intersection(feats, 1),
            page.calculate_intersection(feats, 3), page.calculate_intersection(feats[:2], 2),
            page.calculate_intersection(feature_collection([(0, 0, 1, 1), (5, 5, 6, 6)])["features"], 2),
            page.calculate_intersection([], 2)]


INTER = {"type": "FeatureCollection", "features": [{"type": "Feature", "properties": {"type": "cbd"},
                                                    "geometry": page.calculate_intersection(ISO["features"], 2)}]}
MARKERS = [{"lat": 20.21, "lng": 100.40, "active": True}, {"lat": 20.25, "lng": 100.44, "active": True},
           {"lat": 20.30, "lng": 100.50, "active": False}]


@case("anchor.resolve_priority")
def _():
    auto = {"anchor": {"lat": 20.1, "lon": 100.1, "source": "A"}}
    net = {"top_node": {"lat": 20.2, "lon": 100.2, "score": 0.5}}
    return [page.resolve_cbd_anchor(INTER, net, ISO, MARKERS, auto), page.resolve_cbd_anchor(INTER, net, ISO, MARKERS),
            page.resolve_cbd_anchor(None, net, ISO, MARKERS), page.resolve_cbd_anchor(None, None, ISO, MARKERS),
            page.resolve_cbd_anchor(None, None, None, MARKERS), page.resolve_cbd_anchor(None, None, None, []),
            page.resolve_cbd_anchor({"features": [{"geometry": None}]}, {"top_node": {"score": -1}}, {"features": []}, MARKERS)]


@case("iso.max_distance")
def _():
    return [page.isochrone_max_distance_km(20.22, 100.41, ISO), page.isochrone_max_distance_km(20.22, 100.41, None),
            page.isochrone_max_distance_km(20.22, 100.41, {"features": [{"geometry": {}}]})]


COMPUTED = {}


@case("rent.data")
def _():
    auto = page.find_cbd_anchors(GRID, CENTER, 4000)
    COMPUTED["auto"] = auto["composite"]
    nets = NETWORK["grid"]
    runs = {
        "auto_fit_noiso": page.compute_rent_gradient_data(None, None, None, [], SAMPLE_SETS["five"], "บาท", auto["composite"]),
        "auto_index_noiso": page.compute_rent_gradient_data(None, None, None, [], [], "บาท", auto["composite"]),
        "auto_iso": page.compute_rent_gradient_data(INTER, nets, ISO, MARKERS, SAMPLE_SETS["two"], "บาท", auto["composite"]),
        "cbd_fit_net": page.compute_rent_gradient_data(INTER, nets, ISO, MARKERS, SAMPLE_SETS["five"], "บาท"),
        "net_only": page.compute_rent_gradient_data(None, nets, ISO, MARKERS, [], "บาท"),
        "iso_only": page.compute_rent_gradient_data(None, None, ISO, MARKERS, SAMPLE_SETS["inverted"], "บาท"),
        "markers_only": page.compute_rent_gradient_data(None, None, None, MARKERS, [], "บาท"),
        "nothing": page.compute_rent_gradient_data(None, None, None, [], [], "บาท"),
    }
    COMPUTED["runs"] = runs
    return runs


@case("rent.ring_report")
def _():
    nets = NETWORK["grid"]
    out = {}
    for name, data in COMPUTED["runs"].items():
        out[name] = [page.build_ring_report(data, nets, SAMPLE_SETS["five"]), page.build_ring_report(data, None, [])]
    out["err"] = [page.build_ring_report({"error": "x"}, None, []), page.build_ring_report(None, None, [])]
    return out


@case("rent.helpers")
def _():
    models = [m["model"] for m in COMPUTED["runs"].values() if "model" in m]
    models += [{"is_index": False, "r2": 0.9, "n_samples": 3, "unit": "u"}, {"is_index": False, "r2": 1.0, "n_samples": 2, "dof": 0},
               {"is_index": False, "r2": 0.5, "n_samples": 9, "lam_ci95": (-0.1, 0.2), "half_dist_ci95": None, "adj_r2": 0.4, "low_confidence": False}]
    return [[page.fit_quality_label(m), page.fit_quality_warning(m), page.fit_interval_text(m), page._fit_dof(m),
             page.format_rent_value(1234.567, m)] for m in models] + [[page.t_critical_95(d) for d in (0, 1, 2, 7, 21, 31, 120, 500)]]


@case("rent.geometry")
def _():
    return [page.build_rent_rings_geojson(20.22, 100.4, 5.0, 100.0, 0.3, True, "u"),
            page.build_rent_rings_geojson(20.22, 100.4, 3.0, 5000.0, -0.2, False, "บาท"),
            page.build_rent_nodes_geojson(NETWORK["grid"]["nodes"], 20.22, 100.4, 100.0, 0.3, 5.0),
            page.build_rent_nodes_geojson(None, 20.22, 100.4, 100.0, 0.3, 5.0),
            page.ring_coverage_areas_km2(NETWORK["grid"]["coverage_geojson"], 20.22, 100.4, 1.0, 6),
            page.count_nodes_per_ring(NETWORK["grid"]["nodes"], 20.22, 100.4, 0.5, 6),
            [page._ring_index_for_distance(d, 1.0, 6) for d in (-1, 0, 0.999, 1.0, 5.9999, 6.0, 6.0000000001, 7)],
            [page.rent_color_for_norm(x) for x in (-1, 0, 0.3, 0.5, 1, 2)],
            [page.approx_geom_area_km2(g["geometry"]) for g in INTER["features"]], page.approx_geom_area_km2({})]


@case("click.debounce")
def _():
    out = []
    with mock.patch.object(time, "time", return_value=100.0):
        for last, lat, lon in ((None, 1, 1), ({"timestamp": 99.7, "lat": 1, "lon": 1}, 5, 5),
                               ({"timestamp": 99.5, "lat": 1, "lon": 1}, 5, 5),
                               ({"timestamp": 90.0, "lat": 20.0, "lon": 100.0}, 20.00001, 100.00001),
                               ({"timestamp": 90.0, "lat": 20.0, "lon": 100.0}, 20.01, 100.0)):
            out.append(page.should_add_marker(lat, lon, last))
    return out


@case("colors")
def _():
    clr = {"step1": "a", "step2": "b", "step3": "c", "step4": "d"}
    return [[page.get_fill_color(m, clr) for m in (0, 10, 10.1, 20, 30, 31)], [page.get_border_color(i) for i in (None, 0, 7, 8)]]


class FakeResp:
    def __init__(self, status=200, payload=None, text=""):
        self.status_code, self._p, self.text = status, payload, text

    def json(self):
        if isinstance(self._p, Exception):
            raise self._p
        return self._p


@case("iso.safe_fetch")
def _():
    import requests
    out = []
    plans = [FakeResp(200, {"features": [1, 2]}), FakeResp(200, {}), FakeResp(401), FakeResp(403), FakeResp(429),
             FakeResp(500, text="x" * 300), requests.Timeout(), requests.ConnectionError(), requests.RequestException("r"),
             FakeResp(200, json.JSONDecodeError("m", "d", 0)), RuntimeError("z")]
    for plan in plans:
        def fake_get(*a, _p=plan, **k):
            if isinstance(_p, Exception):
                raise _p
            return _p
        with mock.patch.object(page.requests, "get", fake_get):
            out.append(page.safe_fetch_isochrone("k", "drive", "300", 20.0, 100.0))
    return out


@case("kml.parse")
def _():
    return page._parse_kml_to_geojson()


@case("cache.keys_and_zip")
def _():
    out = {"key": page.get_cache_key(square_wkt(*CENTER), "drive"), "key2": page.get_cache_key(square_wkt(*CENTER), "walk")}
    out["stats"] = {"count": page.get_cache_stats()["count"]}
    members = {}
    with zipfile.ZipFile(io.BytesIO(page.export_cache_as_zip())) as zf:
        for n in zf.namelist():
            members[n] = hashlib.sha256(zf.read(n)).hexdigest()
    out["zip_names"] = sorted(members)
    bad = io.BytesIO()
    with zipfile.ZipFile(bad, "w") as zf:
        zf.writestr("../evil.pkl", b"x")
        zf.writestr("osm_graph_" + "a" * 32 + ".pkl", b"not a pickle")
    out["import_bad"] = page.import_cache_from_zip(bad.getvalue())
    out["import_notzip"] = page.import_cache_from_zip(b"nope")
    out["unpickle_block"] = None
    import pickle as _pk
    with contextlib.suppress(Exception):
        page.safe_pickle_loads(_pk.dumps(__import__("os").system))
    try:
        page.safe_pickle_loads(_pk.dumps(__import__("os").system))
    except Exception as exc:
        out["unpickle_block"] = type(exc).__name__
    return out


@case("cache.covering_and_footprint")
def _():
    poly = page.anchor_study_polygon(*REAL_CENTER, 8000)
    key = page.get_cache_key(poly.wkt, "drive")
    page.save_graph_to_cache(key, REAL, poly.wkt, "drive")
    small = page.anchor_study_polygon(*REAL_CENTER, 3000).wkt
    return {"has": page.cached_graph_available(poly.wkt, "drive"), "small": page.cached_graph_available(small, "drive"),
            "walk": page.cached_graph_available(small, "walk"), "cover": page.find_covering_cache_key(small, "drive") == key,
            "sidecar": page._read_cache_sidecar(key), "bytes": page.get_cache_stats()["count"]}


@case("osm.fetch_paths")
def _():
    poly = page.anchor_study_polygon(*REAL_CENTER, 3000).wkt
    g, was_cached, err = page._fetch_osm_graph(poly, "drive")
    return {"nodes": len(g) if g else None, "cached": was_cached, "err": err,
            "src": g.graph.get("osm_source") if g else None}


@case("legend.and_wms_params")
def _():
    legend, src = page.load_cityplan_legend()
    return {"legend": legend, "src": src, "win": page._wms_window(20.2, 100.4, 1000.0),
            "params": page._wms_params("dol", (1.0, 2.0, 3.0, 4.0), 64), "mpp": page.wms_meters_per_pixel((0, 0, 1000, 0), 100, 20.0)}


def synthetic_world():
    """Fake Longdo (green plan, red disc, shophouse lots inside it)."""
    from PIL import Image, ImageDraw
    from math import cos, radians
    rng = np.random.default_rng(0)

    def lots(wm, dm):
        im = Image.new("RGBA", (1024, 1024), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        wpx, dpx = wm / 1.5, dm / 1.5
        y = 0.0
        while y < 1024:
            h = dpx * (1 + rng.uniform(-.15, .15))
            d.line([(0, y), (1024, y)], fill=(60, 60, 60, 255), width=1)
            x = 0.0
            while x < 1024:
                w = wpx * (1 + rng.uniform(-.15, .15))
                d.line([(x, y), (x, y + h)], fill=(60, 60, 60, 255), width=1)
                x += w
            y += h
        return np.array(im)

    shop, sub = lots(4.5, 16.0), lots(20.0, 40.0)
    core = (CENTER[0] + 800 / 111320.0, CENTER[1] + 800 / (111320.0 * cos(radians(CENTER[0]))))
    x0, y0 = page._WEB_MERCATOR.transform(core[1], core[0])
    r = 700.0 / cos(radians(core[0]))

    def fetch(layer, bbox, px):
        xs = bbox[0] + (np.arange(px) + 0.5) * (bbox[2] - bbox[0]) / px
        ys = bbox[3] - (np.arange(px) + 0.5) * (bbox[3] - bbox[1]) / px
        inside = (xs[None, :] - x0) ** 2 + (ys[:, None] - y0) ** 2 <= r * r
        info = {"layer": layer, "from_cache": False}
        if layer == "dol":
            return np.where(inside[..., None], shop, sub).astype(np.uint8), info
        img = np.zeros((px, px, 4), dtype=np.uint8)
        img[...] = (60, 160, 60, 255)
        img[inside] = (255, 0, 0, 255)
        return img, info
    return fetch, core


@case("evidence.stage")
def _():
    fetch, core = synthetic_world()
    point = {"node_id": "a", "lat": CENTER[0] - 0.01, "lon": CENTER[1] - 0.01, "score": 0.8}
    found = {"composite": {"anchor": point, "stability": {"level": "stable"}}, "closeness": {"anchor": dict(point)}}
    outs = {"ok": page.run_evidence_stage(found, CENTER, 5000.0, fetcher=fetch)}
    outs["unstable"] = page.run_evidence_stage({**found, "composite": {**found["composite"], "stability": {"level": "unstable"}}},
                                               CENTER, 5000.0, fetcher=fetch)
    outs["no_image"] = page.run_evidence_stage(found, CENTER, 5000.0, fetcher=lambda *a: (None, {"error": "x"}))
    outs["no_roads"] = page.run_evidence_stage({}, CENTER, 5000.0, fetcher=lambda *a: (None, {"error": "x"}))
    outs["est"] = page.estimate_evidence_requests(CENTER, 5000.0)
    COMPUTED["evidence"] = outs["ok"]
    return outs


@case("evidence.confidence_table")
def _():
    anchor, peak = {"lat": 20.2, "lon": 100.4}, {"name": "พาณิชยกรรม", "commercial": True, "area_km2": 1.2}
    cluster = {"cells": 40, "area_ha": 55.0, "score": 0.8, "touches_boundary": False}
    rows = []
    for roads in ([{"lat": 20.2, "lon": 100.4}], [{"lat": 20.25, "lon": 100.4}], []):
        for zoning in (True, False, None):
            for parcel in (True, False, None):
                for cov in (1.0, 0.5, 0.2):
                    for st_levels in (["stable", "stable"], ["stable", "unstable"], [None, "check"]):
                        for touch in (False, True):
                            rows.append(page.classify_anchor_confidence(
                                anchor, roads, zoning_ok=zoning, parcel_ok=parcel, coverage=cov,
                                peak=peak if zoning is not None else None,
                                cluster={**cluster, "touches_boundary": touch} if parcel is not None else None,
                                stability_levels=st_levels, cfg=page.EVIDENCE_CONFIG))
    return rows


# ---------------------------------------------------------------- StateManager (dict-backed session)
@case("state.roundtrip")
def _():
    state = dict(page.StateManager._DEFAULTS)
    state.update(markers=[dict(m) for m in MARKERS], automated_anchor_data=COMPUTED["auto"],
                 rent_gradient_data=COMPUTED["runs"]["cbd_fit_net"], rent_samples=SAMPLE_SETS["five"])
    with mock.patch.object(page.st, "session_state", state):
        exported = page.StateManager.export_config()
        bundle = page.export_bundle_zip()
        page.StateManager.clear_results(["isochrone", "rent"])
        after_clear = {k: v for k, v in state.items() if v is None}
        page.StateManager.reset()
        after_reset = json.loads(json.dumps(canon(state), default=str))
        with zipfile.ZipFile(io.BytesIO(bundle)) as zf:
            names = sorted(zf.namelist())
            manifest = json.loads(zf.read("manifest.json"))
        res = page.import_bundle_zip(bundle)
        imported = dict(state)
        tamper = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(bundle)) as zin, zipfile.ZipFile(tamper, "w") as zout:
            for n in zin.namelist():
                zout.writestr(n, zin.read(n) + (b"x" if n == "config/config.json" else b""))
        res_tamper = page.import_bundle_zip(tamper.getvalue())
        missing = io.BytesIO()
        with zipfile.ZipFile(missing, "w") as zout:
            zout.writestr("manifest.json", "{}")
        res_missing = page.import_bundle_zip(missing.getvalue())
        res_garbage = page.import_bundle_zip(b"not a zip")

        def rewritten(patch_manifest):
            out = io.BytesIO()
            with zipfile.ZipFile(io.BytesIO(bundle)) as zin, zipfile.ZipFile(out, "w") as zout:
                for n in zin.namelist():
                    data = zin.read(n)
                    if n == "manifest.json":
                        m = json.loads(data)
                        patch_manifest(m)
                        data = json.dumps(m).encode("utf-8")
                    zout.writestr(n, data)
            return page.import_bundle_zip(out.getvalue())
        res_version = rewritten(lambda m: m.update(bundle_version="0.9"))
        res_schema = rewritten(lambda m: m.update(config_schema_version=1))
        res_cache_sum = rewritten(lambda m: m["integrity_checksums"].update({"cache/cache.zip": "0" * 64}))
        page.StateManager.import_config({"markers": [], "settings": {"anchor_lat": 20.5, "anchor_lon": 100.5, "nope": 1}})
    return {"exported": json.loads(exported), "names": names, "manifest": manifest, "after_clear": sorted(after_clear),
            "after_reset": after_reset, "res": res, "imported": imported, "tamper": res_tamper, "missing": res_missing,
            "garbage": res_garbage, "version": res_version, "schema": res_schema, "cache_sum": res_cache_sum, "final": state}


@case("state.accessors_and_defaults")
def _():
    out = {}
    state = {}
    with mock.patch.object(page.st, "session_state", state), \
            mock.patch.object(page.StateManager, "_load_remote_defaults", staticmethod(lambda d: None)):
        page.StateManager.initialize()
        out["defaults"] = dict(state)
        sm = page.StateManager
        sm.add_marker(1.0, 2.0)
        sm.set_marker_active(0, False)
        out["markers"] = [list(sm.get_markers()), sm.get_active_markers()]
        sm.remove_marker(5)
        sm.remove_marker(0)
        sm.pop_last_marker()
        sm.record_click(3.0, 4.0)
        out["click"] = {k: v for k, v in sm.get_last_click().items() if k != "timestamp"}
        out["getters"] = [sm.get_isochrone_data(), sm.get_intersection_data(), sm.get_network_data(), sm.get_colors(),
                          sm.get_api_key(), sm.get_travel_mode(), sm.get_time_intervals(), sm.get_map_style_name(),
                          sm.get_rent_samples(), sm.get_rent_data(), sm.get_rent_unit()]
        sm.set_rent_samples([1]); sm.set_rent_data({"a": 1}); sm.set_isochrone_data({"b": 1})
        sm.set_intersection_data({"c": 1}); sm.set_network_data({"d": 1})
        sm.clear_results(["anchor"])
        out["after_anchor_clear"] = {k: state[k] for k in ("rent_gradient_data", "isochrone_data", "intersection_data", "network_data")}
    return out


# ================================================================== LAYER 2 — rendered UI
def normalise_html(html):
    ids = {}

    def sub(m):
        return ids.setdefault(m.group(0), f"ID{len(ids)}")
    return re.sub(r"[0-9a-f]{32}", sub, html)


def widget_tree(block, depth=0):
    out = []
    for key in sorted(block.children):
        el = block.children[key]
        entry = {"type": el.type}
        proto = getattr(el, "proto", None)
        if proto is not None:
            from google.protobuf.json_format import MessageToDict
            text = re.sub(r"\$\$ID-[0-9a-f]+-", "$$ID-", json.dumps(MessageToDict(proto), sort_keys=True, ensure_ascii=False))
            text = re.sub(r"/mock/media/[0-9a-f]+", "/mock/media/H", text)          # download buttons: content hash
            text = re.sub(r"เตรียม \d+\.\d+ · pivot \d+\.\d+ · exact \d+\.\d+", "เตรียม S · pivot S · exact S", text)
            entry["proto"] = re.sub(r"\d+\.\d+ วินาที", "S วินาที", text)            # wall-clock captions
        if hasattr(el, "children") and el.children and el.type in ("expander", "tab", "column", "horizontal", "vertical", "container", "form", "popover", "status", "tabs", "sidebar", "main", "event", "root"):
            entry["children"] = widget_tree(el, depth + 1)
        elif hasattr(el, "children") and getattr(el, "children", None):
            entry["children"] = widget_tree(el, depth + 1)
        out.append(entry)
    return out


def ui_snapshot(at, rendered):
    snap = {"exception": [str(e.value) for e in at.exception], "main": widget_tree(at.main), "sidebar": widget_tree(at.sidebar),
            "toasts": [t.value for t in at.toast] if hasattr(at, "toast") else None,
            "state": {k: v for k, v in at.session_state.to_dict().items() if not k.startswith("$$") and k != "main_map"
                      and not k.startswith("FormSubmitter")}}
    snap["map_html"] = normalise_html(rendered[-1].get_root().render()) if rendered else None
    return snap


EVENTS = []
RENDERED = []
CALLS = []


@contextlib.contextmanager
def recorded(*names):
    """Log every call (with its arguments) of the given ``streamlit`` functions while the page runs. A toast or a warning
    shown just before ``st.rerun()`` is gone from the final render, but the user saw it."""
    def wrap(name, real):
        def call(*args, **kwargs):
            CALLS.append([name, [repr(a) for a in args], {k: repr(v) for k, v in sorted(kwargs.items())}])
            return real(*args, **kwargs)
        return call
    with contextlib.ExitStack() as stack:
        for name in names:
            stack.enter_context(mock.patch.object(page.st, name, wrap(name, getattr(page.st, name))))
        yield


def run_app(seed=None, interact=None, map_output=None, record=()):
    """Render the page with AppTest. ``map_output`` is what the (patched) map component returns on every run — a click is
    ``{"last_clicked": {"lat": .., "lng": ..}}`` — and ``record`` names the streamlit functions whose calls are logged."""
    from streamlit.testing.v1 import AppTest
    rendered = RENDERED
    rendered.clear()
    EVENTS.clear()
    CALLS.clear()

    def app():
        import rg_gm_page
        rg_gm_page.main()
    with patched(page, st_folium=lambda m, **kw: rendered.append(m) or (map_output or {}), _fetch_osm_graph=lambda *a: (GRID, True, None)), \
            mock.patch.object(page.StateManager, "_load_remote_defaults", staticmethod(lambda d: None)), recorded(*record):
        at = AppTest.from_function(app, default_timeout=90)
        for k, v in (seed or {}).items():
            at.session_state[k] = v
        at.run()
        if interact:
            interact(at)
        snap = ui_snapshot(at, rendered)
        snap["events"] = [dict(e) for e in EVENTS]
        if record:
            snap["calls"] = [list(c) for c in CALLS]
        return snap


def rich_seed(locked=False, index_mode=False):
    ctx = {"study_center": [page.DEFAULT_CONFIG["LAT"], page.DEFAULT_CONFIG["LON"]], "study_radius_m": 10000.0, "network_type": "drive"}
    found = page.find_cbd_anchors(GRID, (page.DEFAULT_CONFIG["LAT"], page.DEFAULT_CONFIG["LON"]), 4000)
    comp, clo = dict(found["composite"], context=ctx), dict(found["closeness"], context=ctx)
    evidence = dict(COMPUTED["evidence"], context=ctx)
    rent = page.compute_rent_gradient_data(INTER, NETWORK["grid"], ISO, MARKERS, [] if index_mode else SAMPLE_SETS["five"], "บาท", comp)
    seed = {"markers": [dict(m) for m in MARKERS], "isochrone_data": ISO, "intersection_data": INTER, "network_data": NETWORK["grid"],
            "rent_samples": [] if index_mode else SAMPLE_SETS["five"], "rent_gradient_data": rent,
            "automated_anchor_data": comp, "automated_anchor_closeness_data": clo, "automated_anchor_evidence_data": evidence,
            "show_traffic": True, "show_population": True, "show_cityplan": True, "show_dol": True, "show_railway": True,
            "show_betweenness": True, "show_closeness": True, "show_golden_spots": True, "show_rent_rings": True,
            "show_rent_nodes": True, "anchor_use_evidence": True, "rent_use_evidence_anchor": True, "ui_locked": locked}
    return seed


@case("ui.default")
def _():
    return run_app()


@case("ui.rich")
def _():
    return run_app(rich_seed())


@case("ui.rich_locked")
def _():
    return run_app(rich_seed(locked=True))


@case("ui.rich_index_mode")
def _():
    return run_app(rich_seed(index_mode=True))


def feedback(at, label):
    """Everything the user was told after one run (toasts vanish on the next run, so log them now),
    plus a digest of the whole session state: a handler that forgets to refresh something shows up here even
    when a later click would hide it."""
    state = {k: v for k, v in at.session_state.to_dict().items() if not k.startswith("$$") and k != "main_map"}
    EVENTS.append({"after": label, "state_digest": digest(state)[0],
                   "map_digest": digest(normalise_html(RENDERED[-1].get_root().render()))[0] if RENDERED else None,
                   "widgets_digest": digest(widget_tree(at.sidebar) + widget_tree(at.main))[0],
                   **{kind: [getattr(e, "value", None) for e in getattr(at, kind)]
                      for kind in ("toast", "error", "warning", "info", "success", "exception")}})


def click(at, label):
    button = next(b for b in at.button if b.label == label)
    if button.disabled:
        EVENTS.append({"after": label, "state": "disabled"})
        return "disabled"
    button.click().run()
    feedback(at, label)
    at.run()   # the sidebar is drawn before the handlers run, so it shows pre-click state until the next rerun
    return "clicked"


def fake_isoline(api_key, travel_mode, ranges_str, lat, lon):
    from shapely.geometry import box, mapping
    feats = []
    for r in ranges_str.split(","):
        half = int(r) / 60 * 0.002
        feats.append({"type": "Feature", "geometry": mapping(box(lon - half, lat - half, lon + half, lat + half)), "properties": {"value": int(r)}})
    return feats, None


@case("ui.flow.iso_network_rent")
def _():
    seed = {"markers": [{"lat": 20.2194, "lng": 100.4036, "active": True}, {"lat": 20.2250, "lng": 100.4100, "active": True}],
            "rent_samples": SAMPLE_SETS["five"], "time_intervals": [5, 10]}
    steps = []

    def interact(at):
        with patched(page, fetch_api_data_cached=fake_isoline):
            click(at, "🧩 ① คำนวณหา Isochrone CBD")
        steps.append(["iso", sorted(k for k, v in at.session_state.to_dict().items() if v is not None)])
        click(at, "🚀 Run Network Analysis")
        click(at, "🧮 คำนวณ Rent Gradient")
        click(at, "🎯 ค้นหา CBD Anchor อัตโนมัติ")
        at.run()
    out = run_app(seed, interact)
    out["steps"] = steps
    return out


@case("ui.flow.errors")
def _():
    states = []

    def interact(at):
        states.append(click(at, "🧩 ① คำนวณหา Isochrone CBD"))      # empty api key
        at.text_input(key="api_key").set_value("k").run()
        states.append(click(at, "🧩 ① คำนวณหา Isochrone CBD"))      # no marker
        at.session_state["markers"] = [{"lat": 20.2, "lng": 100.4, "active": True}]
        at.multiselect(key="time_intervals").set_value([]).run()
        states.append(click(at, "🧩 ① คำนวณหา Isochrone CBD"))      # no interval
        at.multiselect(key="time_intervals").set_value([5]).run()
        with patched(page, fetch_api_data_cached=lambda *a: (None, "bad key")):
            states.append(click(at, "🧩 ① คำนวณหา Isochrone CBD"))  # every request fails
        states.append(click(at, "🚀 Run Network Analysis"))
        states.append(click(at, "🧮 คำนวณ Rent Gradient"))
        with patched(page, _fetch_osm_graph=lambda *a: (None, False, "OSM unavailable")):
            states.append(click(at, "🎯 ค้นหา CBD Anchor อัตโนมัติ"))
    out = run_app({"markers": [], "api_key": ""}, interact)
    out["click_states"] = states
    return out


@case("ui.flow.marker_edits")
def _():
    def interact(at):
        at.text_input(key="manual_coords").set_value("20.30, 100.50").run()
        next(b for b in at.button if b.label == "เพิ่ม").click().run()
        next(b for b in at.button if b.label == "❌ ลบจุดล่าสุด").click().run()
        at.checkbox(key="active_chk_0").uncheck().run()
        next(b for b in at.button if b.label == "🔄 รีเซ็ต").click().run()
    return run_app(rich_seed(), interact)


def bundle_bytes():
    state = dict(page.StateManager._DEFAULTS)
    state.update(markers=[dict(m) for m in MARKERS], rent_samples=SAMPLE_SETS["five"], automated_anchor_data=COMPUTED["auto"],
                 rent_gradient_data=COMPUTED["runs"]["cbd_fit_net"])
    with mock.patch.object(page.st, "session_state", state):
        return page.export_bundle_zip()


@case("ui.flow.map_click")
def _():
    """A click on the map adds a marker and makes the isochrone / CBD / rent stale; nothing happens while locked."""
    payload = {"last_clicked": {"lat": 20.31, "lng": 100.52}}
    return {"rich": run_app(rich_seed(), map_output=payload),
            "locked": run_app(rich_seed(locked=True), map_output=payload),
            "no_click": run_app(rich_seed(), map_output={"last_clicked": None})}


@case("ui.flow.bundle_import")
def _():
    """The sidebar's two ways to import a bundle (GitHub button, uploaded file): success, failure, empty and tampered."""
    good = bundle_bytes()
    tampered = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(good)) as zin, zipfile.ZipFile(tampered, "w") as zout:
        for name in zin.namelist():
            zout.writestr(name, zin.read(name) + (b"x" if name == "config/config.json" else b""))
    shown = ("toast", "warning", "error", "rerun")

    def from_github(outcome):
        def interact(at):
            with patched(page, download_github_bundle=lambda: outcome):
                click(at, "นำเข้า Bundle จาก GitHub")
        return run_app({"markers": []}, interact, record=shown)

    class Upload:
        def __init__(self, data):
            self.data = data

        def read(self):
            return self.data

    def from_file(data):
        with mock.patch.object(page.st, "file_uploader", lambda *a, **k: Upload(data)):
            return run_app({"markers": []}, lambda at: click(at, "ยืนยันการโหลด Bundle"), record=shown)

    return {"github_ok": from_github((good, None)), "github_error": from_github((None, "HTTP 500")),
            "github_empty": from_github((None, None)), "github_tampered": from_github((tampered.getvalue(), None)),
            "upload_ok": from_file(good), "upload_garbage": from_file(b"not a zip")}


# ------------------------------------------------------------------ write
OUT.write_text(json.dumps(RESULTS, indent=1, sort_keys=True), encoding="utf-8")
if DUMP:
    DUMP.mkdir(parents=True, exist_ok=True)
    for name, text in DUMPS.items():
        (DUMP / f"{name}.json").write_text(text, encoding="utf-8")
print(f"{len(RESULTS)} digests -> {OUT}")
