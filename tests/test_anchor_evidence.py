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
