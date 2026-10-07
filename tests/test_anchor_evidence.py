"""Evidence stage: parcel fragmentation + zoning features, fusion, WMS fetching (all offline).

Real Longdo tiles are not available in CI; synthetic rasters reproduce the properties the
features rely on (line thickness, cell size, aspect, label clutter, zoning colours). Tests
that need captured real tiles live behind ``Geoapify_Map/fixtures/wms`` and are skipped when absent.
"""
import importlib.util
import json
import sys
from math import cos, radians
from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("anchor_evidence_test", ROOT / "pages/Rent_Gradient.py")
page = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = page
spec.loader.exec_module(page)

MPP = 1.5      # metres per pixel for a ~1.5 km window
SIZE = 1024


# ------------------------------------------------------------------ synthetic rasters
def dol_window(lot_w, lot_d, seed=0, jitter=0.15, line_px=1, specks=400, opaque=False, angle=0.0, mpp=MPP):
    """Transparent DOL-like layer: dark boundary lines (``line_px`` wide), parcel-number specks."""
    rng = np.random.default_rng(seed)
    big = SIZE * 2 if angle else SIZE
    im = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    wpx, dpx = lot_w / mpp, lot_d / mpp
    y = 0.0
    while y < big:
        h = dpx * (1 + rng.uniform(-jitter, jitter))
        d.line([(0, y), (big, y)], fill=(60, 60, 60, 255), width=line_px)
        x = 0.0
        while x < big:
            w = wpx * (1 + rng.uniform(-jitter, jitter))
            d.line([(x, y), (x, y + h)], fill=(60, 60, 60, 255), width=line_px)
            x += w
        y += h
    if angle:
        im = im.rotate(angle, resample=Image.NEAREST).crop(
            (SIZE // 2, SIZE // 2, SIZE // 2 + SIZE, SIZE // 2 + SIZE))
    a = np.array(im)
    ys, xs = rng.integers(0, SIZE, specks), rng.integers(0, SIZE, specks)
    a[ys, xs] = (60, 60, 60, 255)
    if opaque:
        rgb = a[..., :3].copy()
        rgb[a[..., 3] == 0] = (250, 250, 245)
        a = np.dstack([rgb, np.full((SIZE, SIZE), 255, dtype=np.uint8)])
    return a


SCENES = {
    "shophouse": (4.5, 16.0),
    "town": (12.0, 25.0),
    "suburb": (20.0, 40.0),
    "rural": (80.0, 120.0),
}


@pytest.fixture(scope="module")
def scene_features():
    return {name: page.parcel_features(dol_window(*dims), MPP) for name, dims in SCENES.items()}


# --------------------------------------------------------------------- parcel features
def test_parcel_features_separate_core_from_suburb_and_rural(scene_features):
    f = scene_features
    assert all(x["data"] for x in f.values())
    ink = [f[k]["ink_ratio"] for k in SCENES]
    cells = [f[k]["median_cell_m2"] for k in SCENES]
    assert ink == sorted(ink, reverse=True)                    # core lines are the thickest
    assert cells == sorted(cells)                              # core parcels are the smallest
    # parcel areas are corrected for the width of the boundary lines: they track the true lot size
    for name, (w, d) in SCENES.items():
        assert f[name]["median_cell_m2"] == pytest.approx(w * d, rel=0.3), name
    assert f["shophouse"]["shophouse_share"] > 0.9
    assert f["town"]["shophouse_share"] < 0.05 and f["suburb"]["shophouse_share"] == 0.0
    scores = [f[k]["score"] for k in SCENES]
    assert scores == sorted(scores, reverse=True)
    assert f["shophouse"]["score"] > 0.8 and f["rural"]["score"] < 0.05
    assert f["shophouse"]["score"] > 4 * f["town"]["score"]


def test_parcel_features_ignore_label_clutter_and_opaque_backgrounds():
    clean = page.parcel_features(dol_window(*SCENES["shophouse"], specks=0), MPP)
    cluttered = page.parcel_features(dol_window(*SCENES["shophouse"], specks=3000), MPP)
    opaque = page.parcel_features(dol_window(*SCENES["shophouse"], specks=400, opaque=True), MPP)
    for other in (cluttered, opaque):
        assert other["data"]
        assert other["shophouse_share"] == pytest.approx(clean["shophouse_share"], abs=0.08)
        assert other["score"] == pytest.approx(clean["score"], abs=0.08)


def test_shophouse_aspect_is_rotation_invariant():
    # 1 m/px with 2-px lines: the resolution the evidence stage requests for parcel windows
    straight = page.parcel_features(dol_window(*SCENES["shophouse"], line_px=2, mpp=1.0), 1.0)
    rotated = page.parcel_features(dol_window(*SCENES["shophouse"], line_px=2, angle=33.0, mpp=1.0), 1.0)
    assert straight["data"] and straight["shophouse_share"] > 0.8
    assert rotated["data"] and rotated["shophouse_share"] > 0.5


def test_too_coarse_a_window_cannot_resolve_shophouse_lots_and_says_so():
    # 4.5 m frontage is 1.5 px at 3 m/px: the cells close up. The evidence stage therefore
    # asks for <= 1.2 m/px windows; here the features must degrade to "no data", not invent a score.
    coarse = page.parcel_features(dol_window(*SCENES["shophouse"], line_px=2, mpp=3.0), 3.0)
    assert coarse["data"] is False and coarse["score"] is None


def test_blank_or_unreadable_layers_are_no_data_not_low():
    blank = page.parcel_features(np.zeros((SIZE, SIZE, 4), dtype=np.uint8), MPP)
    assert blank == {**blank, "data": False, "score": None, "coverage": 0.0, "cell_count": 0}
    rgb_only = page.parcel_features(np.zeros((SIZE, SIZE, 3), dtype=np.uint8), MPP)
    assert rgb_only["data"] is False and rgb_only["score"] is None
    assert page.parcel_features(dol_window(*SCENES["town"]), 0.0)["data"] is False  # unusable scale


def test_one_giant_free_region_is_not_counted_as_a_parcel():
    image = dol_window(*SCENES["shophouse"])
    image[: SIZE // 2] = 0                      # upper half: river / no parcel data
    half = page.parcel_features(image, MPP)
    assert half["data"] and half["coverage"] < 0.7
    assert half["shophouse_share"] > 0.85       # the cells that exist are still ตึกแถว


def test_component_aspect_is_the_side_ratio_of_a_rectangle():
    labels = np.zeros((60, 60), dtype=np.int64)
    labels[10:14, 5:21] = 1                     # 4 x 16 px
    labels[30:50, 30:40] = 2                    # 20 x 10 px
    aspects = page._component_aspect(labels, 2)
    assert aspects[0] == pytest.approx(4.0, rel=0.12)
    assert aspects[1] == pytest.approx(2.0, rel=0.1)


def test_meters_per_pixel_shrinks_with_latitude():
    bbox = (0.0, 0.0, 1024 * 2.0, 1024 * 2.0)   # 2 m of Web Mercator per pixel
    assert page.wms_meters_per_pixel(bbox, 1024, 0.0) == pytest.approx(2.0)
    assert page.wms_meters_per_pixel(bbox, 1024, 20.2) == pytest.approx(2.0 * cos(radians(20.2)))


# --------------------------------------------------------------------- zoning features
RED, ORANGE, YELLOW, GREEN, BLACK = (255, 0, 0), (255, 153, 0), (255, 255, 0), (0, 176, 80), (0, 0, 0)


def plan_window(blocks, background=None, size=512):
    """City-plan-like window: ``blocks`` = [(colour, (row0, row1, col0, col1))]."""
    a = np.zeros((size, size, 4), dtype=np.uint8)
    if background:
        a[...] = (*background, 255)
    for colour, (r0, r1, c0, c1) in blocks:
        a[r0:r1, c0:c1] = (*colour, 255)
    return a


LEGEND, SOURCE = page.load_cityplan_legend(Path("/nonexistent/legend.json"))


def test_missing_or_broken_legend_falls_back_to_the_labelled_provisional_one(tmp_path):
    assert SOURCE == "provisional" and any(c["commercial"] for c in LEGEND)
    broken = tmp_path / "legend.json"
    broken.write_text("{not json", encoding="utf-8")
    assert page.load_cityplan_legend(broken)[1] == "provisional"
    good = tmp_path / "good.json"
    good.write_text(json.dumps({"classes": [
        {"name": "พาณิชย์", "rgb": [200, 10, 10], "weight": 1.0, "commercial": True},
        {"name": "อยู่อาศัย", "rgb": [250, 200, 0], "weight": 0.4}]}), encoding="utf-8")
    legend, source = page.load_cityplan_legend(good)
    assert source == "file" and [c["name"] for c in legend] == ["พาณิชย์", "อยู่อาศัย"]
    assert legend[0]["commercial"] and not legend[1]["commercial"]


def test_zoning_centre_in_commercial_zone_scores_high():
    image = plan_window([(RED, (156, 356, 156, 356))], background=ORANGE)   # 200 px (300 m) red square
    z = page.zoning_features(image, LEGEND, m_per_px=1.5, radius_m=150.0)
    assert z["data"] and z["in_commercial"] is True and z["distance_to_commercial_m"] == 0.0
    assert z["commercial_share"] > 0.95 and z["zoning_intensity"] > 0.95
    assert z["plan_coverage"] > 0.95


def test_zoning_distance_to_the_commercial_zone_and_intensity_of_the_surroundings():
    image = plan_window([(RED, (60, 100, 60, 100))], background=ORANGE)     # red block ~ 230 px from the centre
    z = page.zoning_features(image, LEGEND, m_per_px=1.5, radius_m=200.0)
    assert z["in_commercial"] is False
    assert z["distance_to_commercial_m"] == pytest.approx(1.5 * np.hypot(255.5 - 99, 255.5 - 99), rel=0.03)
    assert z["commercial_share"] == pytest.approx(0.0, abs=0.01)
    assert z["zoning_intensity"] == pytest.approx(0.5, abs=0.02)            # all ปานกลาง (weight 0.5)
    assert set(z["class_shares"]) == {"ที่อยู่อาศัยหนาแน่นปานกลาง"}


def test_zoning_mixed_classes_weight_by_area():
    image = plan_window([(YELLOW, (0, 512, 256, 512))], background=RED)     # half red, half yellow
    z = page.zoning_features(image, LEGEND, m_per_px=1.5, radius_m=300.0)
    assert z["commercial_share"] == pytest.approx(0.5, abs=0.05)
    assert z["zoning_intensity"] == pytest.approx(0.5 * 1.0 + 0.5 * 0.25, abs=0.05)


def test_zoning_ignores_outlines_text_and_antialiasing():
    image = plan_window([(RED, (156, 356, 156, 356))], background=ORANGE)
    for r in range(0, 512, 16):                                              # thin black grid + text-like specks
        image[r, :] = (*BLACK, 255)
        image[:, r] = (*BLACK, 255)
    image[200:204, 250:260] = (*BLACK, 255)
    z = page.zoning_features(image, LEGEND, m_per_px=1.5, radius_m=150.0)
    assert set(z["class_shares"]) <= {"พาณิชยกรรม", "ที่อยู่อาศัยหนาแน่นปานกลาง"}
    assert z["commercial_share"] > 0.9 and z["in_commercial"] is True
    # colours that are not in the legend are "no data", never a made-up class
    unknown = plan_window([((120, 120, 200), (0, 512, 0, 512))])
    nothing = page.zoning_features(unknown, LEGEND, m_per_px=1.5, radius_m=150.0)
    assert nothing["data"] is False and nothing["zoning_intensity"] is None and nothing["plan_coverage"] < 0.02


def test_outside_the_published_plan_is_no_data_not_low_density():
    blank = page.zoning_features(np.zeros((512, 512, 4), dtype=np.uint8), LEGEND, m_per_px=1.5)
    assert blank["data"] is False and blank["plan_coverage"] == 0.0
    assert blank["zoning_intensity"] is None and blank["commercial_share"] is None
    assert blank["distance_to_commercial_m"] is None
    assert page.zoning_features(plan_window([]), [], m_per_px=1.5)["data"] is False


def test_zoning_with_a_file_legend_uses_its_colours_and_weights(tmp_path):
    legend = [{"name": "ย่านการค้า", "rgb": [180, 20, 20], "weight": 1.0, "commercial": True},
              {"name": "บ้าน", "rgb": [240, 220, 120], "weight": 0.2, "commercial": False}]
    image = plan_window([((180, 20, 20), (200, 312, 200, 312))], background=(240, 220, 120))
    z = page.zoning_features(image, legend, m_per_px=1.5, radius_m=50.0)
    assert z["in_commercial"] is True and z["class_shares"].keys() == {"ย่านการค้า"}
    wide = page.zoning_features(image, legend, m_per_px=1.5, radius_m=150.0)   # the disc now reaches the houses
    assert wide["class_shares"].keys() == {"ย่านการค้า", "บ้าน"}
    assert wide["zoning_intensity"] == pytest.approx(
        wide["class_shares"]["ย่านการค้า"] * 1.0 + wide["class_shares"]["บ้าน"] * 0.2)


# ================================================================== fusion and confidence
def cand(node_id, lat, lon, score=0.5, **kw):
    return {"node_id": node_id, "lat": lat, "lon": lon, "composite_score": score, **kw}


def test_candidate_selection_puts_both_road_anchors_first_and_enforces_spacing():
    lat0, lon0 = 20.2, 100.4
    step = 0.001  # ~109 m of latitude
    pool = [cand(f"n{i}", lat0 + i * step, lon0, score=1 - i * 0.01) for i in range(40)]
    anchors = [dict(pool[17], score=0.9), dict(pool[3], score=0.8)]
    picked = page.select_evidence_candidates(pool, anchors, limit=6, min_spacing_m=300.0)
    ids = [c["node_id"] for c in picked]
    assert ids[:2] == ["n17", "n3"]                                   # anchors first, in the given order
    assert len(ids) == len(set(ids)) == 6
    for a in picked:
        for b in picked:
            if a is not b:
                assert page.calculate_distance_meters(a["lat"], a["lon"], b["lat"], b["lon"]) >= 300.0
    # the best-ranked candidate not too close to an anchor comes right after them
    assert picked[2]["node_id"] == "n0"


def test_fusion_drops_a_missing_signal_instead_of_scoring_it_zero():
    w = {"road": 0.35, "parcel": 0.35, "zoning": 0.30}
    full = {"node_id": "a", "road_signal": 0.8, "parcel": {"data": True, "score": 0.8},
            "zoning": {"data": True, "zoning_intensity": 0.8}}
    no_parcel = {"node_id": "b", "road_signal": 0.8, "parcel": {"data": False},
                 "zoning": {"data": True, "zoning_intensity": 0.8}}
    nothing = {"node_id": "c", "road_signal": 0.8, "parcel": {"data": False}, "zoning": {"data": False}}
    fused = {c["node_id"]: c for c in page.fuse_evidence([full, no_parcel, nothing], w)}
    assert fused["a"]["evidence_score"] == pytest.approx(0.8) and fused["a"]["coverage"] == pytest.approx(1.0)
    assert fused["b"]["evidence_score"] == pytest.approx(0.8)       # not dragged down by the missing parcel data
    assert fused["b"]["coverage"] == pytest.approx(0.65)
    assert fused["c"]["evidence_score"] == pytest.approx(0.8) and fused["c"]["coverage"] == pytest.approx(0.35)


def test_fusion_ranks_best_first_and_breaks_ties_by_node_id():
    w = {"road": 1.0, "parcel": 1.0, "zoning": 1.0}
    rows = [{"node_id": nid, "road_signal": r, "parcel": {"data": True, "score": p},
             "zoning": {"data": True, "zoning_intensity": z}}
            for nid, r, p, z in (("b", 0.5, 0.5, 0.5), ("a", 0.5, 0.5, 0.5), ("c", 0.9, 0.9, 0.9), ("d", 0.1, 0.2, 0.1))]
    fused = page.fuse_evidence(rows, w)
    assert [c["node_id"] for c in fused] == ["c", "a", "b", "d"]
    assert [c["rank"] for c in fused] == [1, 2, 3, 4]


def winner(**kw):
    base = {"lat": 20.2, "lon": 100.4, "coverage": 1.0,
            "parcel": {"data": True, "score": 0.8, "small_share": 0.9, "shophouse_share": 0.7},
            "zoning": {"data": True, "in_commercial": True, "distance_to_commercial_m": 0.0}}
    base.update(kw)
    return base


ROAD_NEAR = [{"lat": 20.2, "lon": 100.4}]
ROAD_FAR = [{"lat": 20.25, "lon": 100.4}]


def test_confidence_high_needs_roads_plan_and_parcels_to_agree():
    cfg = page.EVIDENCE_CONFIG
    result = page.classify_anchor_confidence(winner(), ROAD_NEAR, "stable", cfg)
    assert result["level"] == "HIGH" and result["signals"] == {"roads": True, "zoning": True, "parcel": True}
    assert any("โซนพาณิชยกรรม" in r for r in result["reasons"])
    # an unstable road anchor, or too little data, takes HIGH away
    assert page.classify_anchor_confidence(winner(), ROAD_NEAR, "unstable", cfg)["level"] == "MEDIUM"
    assert page.classify_anchor_confidence(winner(coverage=0.5), ROAD_NEAR, "stable", cfg)["level"] == "MEDIUM"


def test_confidence_medium_low_and_reasons_for_missing_or_disagreeing_evidence():
    cfg = page.EVIDENCE_CONFIG
    far = page.classify_anchor_confidence(winner(), ROAD_FAR, "stable", cfg)
    assert far["level"] == "MEDIUM" and far["signals"]["roads"] is False
    assert any("ไม่สอดคล้อง" in r for r in far["reasons"]) and far["nearest_road_anchor_m"] > 5000
    only_roads = page.classify_anchor_confidence(
        winner(parcel={"data": False}, zoning={"data": False, "distance_to_commercial_m": None}, coverage=0.35),
        ROAD_NEAR, "stable", cfg)
    assert only_roads["level"] == "LOW" and only_roads["signals"]["zoning"] is None and only_roads["signals"]["parcel"] is None
    assert any("ไม่มีข้อมูล" in r for r in only_roads["reasons"])
    weak = page.classify_anchor_confidence(
        winner(parcel={"data": True, "score": 0.1, "small_share": 0.0, "shophouse_share": 0.0},
               zoning={"data": True, "in_commercial": False, "distance_to_commercial_m": 900.0}),
        ROAD_FAR, "check", cfg)
    assert weak["level"] == "LOW" and any("ไกล" in r for r in weak["reasons"])
    near_zone = page.classify_anchor_confidence(
        winner(zoning={"data": True, "in_commercial": False, "distance_to_commercial_m": 100.0}), ROAD_NEAR, "stable", cfg)
    assert near_zone["signals"]["zoning"] is True and near_zone["level"] == "HIGH"


# ====================================================================== WMS fetching
class FakeResponse:
    def __init__(self, content=b"", status=200, content_type="image/png"):
        self.content, self.status_code, self.headers = content, status, {"Content-Type": content_type}


def png_bytes(size=64, color=(10, 20, 30, 255)):
    import io

    buffer = io.BytesIO()
    Image.new("RGBA", (size, size), color).save(buffer, format="PNG")
    return buffer.getvalue()


@pytest.fixture
def wms_env(tmp_path, monkeypatch):
    monkeypatch.setattr(page, "CACHE_DIR", tmp_path)
    calls = []
    behaviour = {"response": lambda params: FakeResponse(png_bytes(64))}

    def fake_get(url, params=None, timeout=None, headers=None):
        calls.append({"url": url, "params": dict(params), "timeout": timeout})
        return behaviour["response"](params)

    monkeypatch.setattr(page.requests, "get", fake_get)
    return tmp_path, calls, behaviour


def test_wms_window_covers_the_requested_ground_size_and_params_are_a_getmap():
    lat, lon = 20.2194, 100.4036
    bbox = page._wms_window(lat, lon, 1000.0)
    assert page.wms_meters_per_pixel(bbox, 1024, lat) * 1024 == pytest.approx(1000.0, rel=1e-6)
    params = page._wms_params("dol", bbox, 1024)
    assert params["request"] == "GetMap" and params["srs"] == "EPSG:3857" and params["layers"] == "dol"
    assert params["transparent"] == "true" and params["width"] == params["height"] == 1024
    assert "key" not in params and "apiKey" not in params


def test_wms_fetch_caches_by_window_and_never_stores_the_key(wms_env):
    tmp_path, calls, _ = wms_env
    bbox = page._wms_window(20.2194, 100.4036, 1000.0)
    image, info = page.fetch_wms_image("dol", bbox, 64)
    assert image.shape == (64, 64, 4) and not info["from_cache"] and len(calls) == 1
    assert calls[0]["url"] == page.LONGDO_WMS_URL and calls[0]["params"]["layers"] == "dol"
    again, info2 = page.fetch_wms_image("dol", bbox, 64)
    assert info2["from_cache"] and len(calls) == 1 and np.array_equal(image, again)
    other, _ = page.fetch_wms_image("cityplan_dpt", bbox, 64)               # another layer: another entry
    assert len(calls) == 2
    stored = " ".join(p.read_text(encoding="utf-8") for p in tmp_path.glob("wms_*.json"))
    assert page.DEFAULT_CONFIG["LONGDO_KEY"] not in stored
    assert not any(page.DEFAULT_CONFIG["LONGDO_KEY"] in p.name for p in tmp_path.iterdir())


@pytest.mark.parametrize("response, expected", [
    (lambda p: FakeResponse(b"", status=500), "HTTP 500"),
    (lambda p: FakeResponse(b"<ServiceException/>", content_type="text/xml"), "service exception"),
    (lambda p: FakeResponse(b"not an image"), None),
    (lambda p: FakeResponse(png_bytes(32)), "unexpected image size"),
])
def test_wms_failures_return_an_error_and_cache_nothing(wms_env, response, expected):
    tmp_path, calls, behaviour = wms_env
    behaviour["response"] = response
    image, info = page.fetch_wms_image("dol", page._wms_window(20.2, 100.4, 1000.0), 64)
    assert image is None and "error" in info
    if expected:
        assert expected in info["error"]
    assert not list(tmp_path.glob("wms_*"))


def test_wms_timeout_and_corrupt_cache_entries_are_survivable(wms_env):
    tmp_path, calls, behaviour = wms_env
    bbox = page._wms_window(20.2, 100.4, 1000.0)

    def boom(params):
        raise page.requests.Timeout("slow server")

    behaviour["response"] = boom
    image, info = page.fetch_wms_image("dol", bbox, 64)
    assert image is None and "slow server" in info["error"]
    behaviour["response"] = lambda params: FakeResponse(png_bytes(64))
    page.fetch_wms_image("dol", bbox, 64)
    (next(tmp_path.glob("wms_*.png"))).write_bytes(b"corrupt")
    n = len(calls)
    healed, info = page.fetch_wms_image("dol", bbox, 64)
    assert healed is not None and not info["from_cache"] and len(calls) == n + 1


# ============================================================ run_evidence_stage (fake fetcher)
CENTER = (20.219443, 100.403630)
CORE = (20.2200, 100.4040)            # shophouse lots + commercial zone
OUT = (20.2290, 100.4040)             # ~1 km north: suburban lots, no commercial zone


def _near(bbox, point):
    """True when the window centre lies within ~0.01 deg of ``point`` (by Mercator centre)."""
    x, y = page._WEB_MERCATOR.transform(point[1], point[0])
    cx, cy = (bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2
    return abs(cx - x) < 40 and abs(cy - y) < 40


def make_fetcher(core=CORE, out=OUT, fail=(), calls=None, cached=False):
    """Serves a two-place world: a CBD-like core and a suburb; ``fail`` = kinds to fail."""
    plan = plan_window([(RED, (360, 664, 360, 664))], background=GREEN, size=1024)
    suburb_plan = plan_window([], background=GREEN, size=1024)

    def fetch(layer, bbox, px):
        if calls is not None:
            calls.append((layer, tuple(bbox), px))
        kind = "parcel" if layer == "dol" else "plan"
        span = (bbox[2] - bbox[0]) * cos(radians(CENTER[0]))
        if kind in fail:
            return None, {"layer": layer, "error": "HTTP 500", "from_cache": False}
        info = {"layer": layer, "from_cache": cached}
        if layer == "dol":
            lot = SCENES["shophouse"] if _near(bbox, core) else SCENES["suburb"]
            return dol_window(*lot, mpp=span / px), info
        if span > 6000:        # study-area overview: a red blob left of and below centre, green elsewhere
            return plan_window([(RED, (600, 700, 300, 400))], background=GREEN, size=1024), info
        return (plan if _near(bbox, core) else suburb_plan), info
    return fetch


def road_found(core_is_anchor=True, stability="stable", extra=()):
    core = {"node_id": "core", "lat": CORE[0], "lon": CORE[1], "score": 0.80}
    out = {"node_id": "out", "lat": OUT[0], "lon": OUT[1], "score": 0.90}
    composite_anchor, closeness_anchor = (core, core) if core_is_anchor else (out, out)
    candidates = [dict(core, composite_score=0.80), dict(out, composite_score=0.90), *extra]
    return {
        "composite": {"anchor": composite_anchor, "stability": {"level": stability}},
        "closeness": {"anchor": closeness_anchor},
        "evidence_candidates": candidates,
    }


@pytest.fixture
def small_config(monkeypatch):
    monkeypatch.setitem(page.EVIDENCE_CONFIG, "candidates", 4)
    monkeypatch.setitem(page.EVIDENCE_CONFIG, "parallel", 3)


def stage(found, fetcher, **kw):
    return page.run_evidence_stage(found, CENTER, 5000.0, fetcher=fetcher, **kw)


def test_stage_picks_the_core_over_a_better_road_score_when_the_evidence_says_so(small_config):
    result = stage(road_found(core_is_anchor=False), make_fetcher())
    assert result["status"] == "ok" and result["legend_source"] == "provisional"
    best = result["evidence_anchor"]
    assert best["node_id"] == "core" and best["source"] == "Automated CBD Anchor — Evidence"
    by_id = {c["node_id"]: c for c in result["candidates"]}
    assert by_id["core"]["evidence_score"] > by_id["out"]["evidence_score"]
    assert by_id["core"]["parcel"]["shophouse_share"] > by_id["out"]["parcel"]["shophouse_share"]
    assert by_id["core"]["zoning"]["in_commercial"] and not by_id["out"]["zoning"]["in_commercial"]
    assert by_id["out"]["is_composite_anchor"] and not by_id["core"]["is_composite_anchor"]
    # the evidence anchor sits ~1 km from the road anchors → the signals disagree: not HIGH
    assert result["confidence"]["level"] != "HIGH" and result["confidence"]["signals"]["roads"] is False
    assert [c["rank"] for c in result["candidates"]] == list(range(1, len(result["candidates"]) + 1))


def test_stage_is_high_confidence_when_roads_zoning_and_parcels_agree(small_config):
    result = stage(road_found(core_is_anchor=True), make_fetcher())
    confidence = result["confidence"]
    assert result["evidence_anchor"]["node_id"] == "core"
    assert confidence["level"] == "HIGH" and confidence["coverage"] == pytest.approx(1.0)
    assert all(confidence["signals"].values())
    # an unstable road anchor caps the confidence
    unstable = stage(road_found(core_is_anchor=True, stability="unstable"), make_fetcher())
    assert unstable["confidence"]["level"] != "HIGH"


def test_stage_reports_the_commercial_zone_from_the_study_area_overview(small_config):
    zone = stage(road_found(), make_fetcher())["commercial_zone"]
    assert zone and zone["area_km2"] > 0
    # the blob occupies rows 600-700 / cols 300-400 of a 1024 px, 10 km overview: SW of the centre
    assert zone["lat"] < CENTER[0] and zone["lon"] < CENTER[1]
    assert page.calculate_distance_meters(zone["lat"], zone["lon"], *CENTER) == pytest.approx(
        np.hypot((350 - 512) * 10000 / 1024, (650 - 512) * 10000 / 1024), rel=0.05)


def test_stage_without_any_image_is_unavailable_and_leaves_the_roads_alone(small_config):
    found = road_found()
    snapshot = json.dumps(found, sort_keys=True)
    result = stage(found, make_fetcher(fail=("parcel", "plan")))
    assert result["status"] == "unavailable" and result["evidence_anchor"] is None
    assert result["confidence"] is None and result["reason"]
    assert result["fetch"]["errors"] and "HTTP 500" in result["fetch"]["errors"][0]
    assert json.dumps(found, sort_keys=True) == snapshot            # the road result is untouched


def test_stage_with_one_layer_missing_is_partial_and_scores_on_what_exists(small_config):
    result = stage(road_found(core_is_anchor=False), make_fetcher(fail=("plan",)))
    assert result["status"] == "partial" and result["evidence_anchor"]["node_id"] == "core"
    winner = result["candidates"][0]
    assert winner["signals"]["zoning"] is None and winner["signals"]["parcel"] is not None
    assert winner["coverage"] == pytest.approx(0.70)                # road 0.35 + parcel 0.35
    assert result["confidence"]["level"] != "HIGH"                  # zoning is unknown, not "agreeing"


def test_stage_never_raises_whatever_the_fetcher_or_the_input_does(small_config):
    def exploding(layer, bbox, px):
        raise RuntimeError("proxy melted")

    broken = stage(road_found(), exploding)
    assert broken["status"] == "unavailable" and "proxy melted" in " ".join(broken["fetch"]["errors"])
    for found in ({}, {"composite": None}, {"composite": {"anchor": {}}, "closeness": {}}):
        result = stage(found, make_fetcher())
        assert result["status"] == "unavailable" and result["reason"] and result["evidence_anchor"] is None
    empty = stage(road_found() | {"evidence_candidates": []},
                  make_fetcher())
    assert empty["status"] in ("ok", "partial", "unavailable")  # roads anchors alone are still candidates


def test_stage_respects_the_request_budget_and_says_what_it_skipped(small_config, monkeypatch):
    monkeypatch.setitem(page.EVIDENCE_CONFIG, "max_requests", 3)
    calls = []
    result = stage(road_found(), make_fetcher(calls=calls))
    assert len(calls) == 3
    assert result["fetch"]["skipped_over_budget"] > 0 and result["status"] != "ok"


def test_stage_counts_cache_hits_and_requests(small_config):
    live = stage(road_found(), make_fetcher())
    assert live["fetch"]["cache_hits"] == 0 and live["fetch"]["requests"] > 0
    cached = stage(road_found(), make_fetcher(cached=True))
    assert cached["fetch"]["requests"] == 0 and cached["fetch"]["cache_hits"] == live["fetch"]["requests"]


def test_stage_result_is_json_safe_and_deterministic(small_config):
    first = stage(road_found(core_is_anchor=False), make_fetcher())
    second = stage(road_found(core_is_anchor=False), make_fetcher())
    text = json.dumps(first, sort_keys=True)                          # no numpy scalars / arrays
    for volatile in ("seconds",):
        first["fetch"].pop(volatile), second["fetch"].pop(volatile)
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
    assert len(text) < 60_000                                         # no raster is stored in the result
