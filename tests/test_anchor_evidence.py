"""Evidence stage: peak-colour zone + dense small-parcel cluster, confidence, WMS fetching (all offline).

Real Longdo tiles are not available in CI; synthetic rasters reproduce the properties the
features rely on (line thickness, cell size, aspect, label clutter, zoning colours). Tests
that need captured real tiles live behind ``Geoapify_Map/fixtures/wms`` and are skipped when absent.
"""
import importlib.util
import json
import sys
import time
from math import cos, floor, hypot, radians
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


# ================================================================== lattice
CENTER = (20.219443, 100.403630)


def offset(origin, east_m=0.0, north_m=0.0):
    """Point ``east_m`` / ``north_m`` ground metres from ``origin`` (small distances)."""
    return (origin[0] + north_m / 111_320.0, origin[1] + east_m / (111_320.0 * cos(radians(origin[0]))))


def geometry(radius_m=10_000.0, center=CENTER):
    geo = page._evidence_geometry(center, radius_m)
    return geo, page._circle_mask(geo, geo["x0"], geo["y0"], geo["r"])


def test_lattice_is_global_so_two_centres_share_tiles_and_alignment_is_fixed():
    tiles = {}
    for name, center in (("a", CENTER), ("b", offset(CENTER, 300, -200))):
        geo, circle = geometry(10_000.0, center)
        tiles[name] = {kind: set(page._lattice_tiles(geo, size, circle))
                       for kind, size in (("plan", page.EVIDENCE_CONFIG["plan_tile_m"]),
                                          ("parcel", page.EVIDENCE_CONFIG["parcel_tile_m"]))}
    assert tiles["a"]["plan"] == tiles["b"]["plan"]                       # same 16 km tiles → same cache files
    assert len(tiles["a"]["parcel"] & tiles["b"]["parcel"]) > 0.9 * len(tiles["a"]["parcel"])
    bbox = page._tile_bbox(3, -2, 16384.0)
    assert bbox == (3 * 16384.0, -2 * 16384.0, 4 * 16384.0, -1 * 16384.0)
    assert page._wms_params("dol", bbox, 1024) == page._wms_params("dol", bbox, 1024)


@pytest.mark.parametrize("radius_km, plan_tiles", [(4, 4), (10, 9), (20, 16)])
def test_plan_tiles_fit_the_request_budget_for_every_radius(radius_km, plan_tiles):
    geo, circle = geometry(radius_km * 1000.0)
    tiles = page._lattice_tiles(geo, page.EVIDENCE_CONFIG["plan_tile_m"], circle)
    assert 1 <= len(tiles) <= plan_tiles
    estimate = page.estimate_evidence_requests(CENTER, radius_km * 1000.0)
    assert estimate["plan_tiles"] == len(tiles)
    assert estimate["requests_max"] <= page.EVIDENCE_CONFIG["max_requests"]
    assert estimate["area_km2"] == pytest.approx(np.pi * radius_km ** 2)
    # nearest tile first: the tile that holds the centre leads
    x, y = page._WEB_MERCATOR.transform(CENTER[1], CENTER[0])
    size = page.EVIDENCE_CONFIG["plan_tile_m"]
    assert tiles[0] == (int(floor(x / size)), int(floor(y / size)))


def test_circle_mask_covers_the_ground_area_of_the_study_radius():
    geo, circle = geometry(5000.0)
    cell_km2 = (page.CELL_M * geo["ground"]) ** 2 / 1e6
    assert circle.sum() * cell_km2 == pytest.approx(np.pi * 5.0 ** 2, rel=0.03)
    ys, xs = np.nonzero(circle)
    assert abs(xs.mean() - (geo["ni"] - 1) / 2) < 1.5 and abs(ys.mean() - (geo["nj"] - 1) / 2) < 1.5


def test_paste_clips_a_tile_that_hangs_over_the_study_box():
    dst = np.zeros((6, 6))
    page._paste(dst, np.ones((4, 4)), -2, 4)          # overlaps rows 4-5 / cols 0-1 only
    assert dst.sum() == 4 and dst[4:, :2].all()
    page._paste(dst, np.ones((4, 4)), 20, 20)         # fully outside: nothing happens
    assert dst.sum() == 4


# ================================================================== plan colours → peak zone
def peak_of(image, legend=LEGEND, circle=None):
    lut = page._legend_lut(legend, page.ZONING_COLOR_TOLERANCE)
    tile = page._plan_tile_shares(image, lut, len(legend), 128)
    ok = np.ones((128, 128), dtype=bool) if circle is None else circle
    return tile, page._peak_zone(tile["shares"], ok, legend, 64)


def test_legend_lut_maps_legend_colours_and_rejects_everything_else():
    lut = page._legend_lut(LEGEND, page.ZONING_COLOR_TOLERANCE)

    def klass(rgb):
        r, g, b = rgb
        return int(lut[((r >> 3) << 10) | ((g >> 3) << 5) | (b >> 3)])

    for k, entry in enumerate(LEGEND):
        assert klass(entry["rgb"]) == k
        assert klass([min(255, c + 4) for c in entry["rgb"]]) == k          # a little antialiasing
    assert klass((120, 120, 200)) == -1 and klass((0, 0, 0)) == -1
    # against a brute-force nearest-colour oracle where the answer is not a coin flip
    rng = np.random.default_rng(3)
    legend = np.array([c["rgb"] for c in LEGEND], dtype=float)
    checked = 0
    for rgb in rng.integers(0, 256, size=(400, 3)):
        dist = np.sqrt(((legend - rgb) ** 2).sum(axis=1))
        order = np.sort(dist)
        if order[0] < 40 and order[1] - order[0] > 16:
            assert klass(tuple(int(c) for c in rgb)) == int(dist.argmin())
            checked += 1
    assert checked > 5


def test_peak_is_the_red_commercial_zone_and_never_a_lower_colour():
    image = plan_window([(RED, (304, 704, 200, 600))], background=ORANGE, size=1024)   # 50 x 50 cells of red
    image[8:16, 800:824] = (*RED, 255)                                                    # a 3-cell speck
    tile, peak = peak_of(image)
    assert tile["explained"] == tile["painted"]
    assert peak["mask"].sum() == 50 * 50 and len(peak["big"]) == 1           # the speck is below zone_min_cells
    # no red zone: a plan that is orange / brown everywhere has NO peak — the next colour down is not "the highest zone"
    only_speck = plan_window([], background=ORANGE, size=1024)
    only_speck[8:16, 800:824] = (*RED, 255)
    assert peak_of(only_speck)[1] is None
    brown = plan_window([], background=(153, 76, 0), size=1024)               # ที่อยู่อาศัยหนาแน่นมาก, weight 0.8
    assert peak_of(brown)[1] is None


def test_red_is_recognised_by_hue_so_any_red_or_pink_shade_counts_and_no_other_colour_does():
    red = [(255, 0, 0), (150, 0, 0), (214, 140, 170), (255, 170, 190), (230, 60, 60), (200, 40, 120), (255, 60, 20)]
    other = [(255, 153, 0), (153, 76, 0), (255, 255, 0), (0, 176, 80), (0, 100, 0), (0, 0, 255), (153, 51, 255),
             (128, 128, 128), (255, 255, 255), (0, 0, 0), (250, 230, 235), (100, 0, 0)]
    assert all(page._is_red_family(*c) for c in red)
    assert not any(page._is_red_family(*c) for c in other)
    # the vectorised test used on the tiles is the same function
    rng = np.random.default_rng(11)
    image = np.dstack([rng.integers(0, 256, size=(128, 128, 3), dtype=np.uint8), np.full((128, 128), 255, np.uint8)])
    tile = page._plan_tile_shares(image, page._legend_lut(LEGEND, page.ZONING_COLOR_TOLERANCE), len(LEGEND), 16)
    assert tile["red_pixels"] == sum(page._is_red_family(*map(int, px)) for px in image.reshape(-1, 4)[:, :3])
    assert tile["shares"][-1].sum() == tile["red_pixels"] > 100


def test_commercial_flagged_classes_join_red_and_other_colours_never_do():
    legend = [
        {"name": "พาณิชยกรรม", "rgb": [255, 0, 0], "weight": 1.0, "commercial": True},
        {"name": "ย่านการค้าสีน้ำเงิน", "rgb": [30, 144, 255], "weight": 0.9, "commercial": True},
        {"name": "ที่อยู่อาศัย", "rgb": [255, 153, 0], "weight": 0.5, "commercial": False},
    ]
    image = plan_window([((255, 0, 0), (304, 504, 200, 400)), ((30, 144, 255), (504, 704, 400, 600))],
                        background=(255, 153, 0), size=1024)                    # two 25 x 25-cell blocks, corner to corner
    _, peak = peak_of(image, legend=legend)
    assert peak["mask"].sum() == 2 * 25 * 25 and len(peak["big"]) == 1
    flagless = [{**c, "commercial": False} for c in legend]                   # red still counts, blue does not
    _, peak = peak_of(image, legend=flagless)
    assert peak["mask"].sum() == 25 * 25


def test_zero_weight_classes_are_never_a_peak_and_unknown_colours_are_not_painted_over():
    farmland = plan_window([], background=GREEN, size=1024)
    _, peak = peak_of(farmland)
    assert peak is None
    unknown = plan_window([], background=(120, 120, 200), size=1024)
    tile, peak = peak_of(unknown)
    assert tile["painted"] == 1024 * 1024 and tile["explained"] == 0 and peak is None


def test_peak_zone_stays_inside_the_study_circle():
    image = plan_window([(RED, (0, 1024, 0, 1024))], background=ORANGE, size=1024)
    circle = np.zeros((128, 128), dtype=bool)
    circle[40:60, 40:60] = True
    _, peak = peak_of(image, circle=circle)
    assert peak["mask"].sum() == 400 and not peak["mask"][~circle].any()


# ================================================================== parcels: frequency of small lots
TILE_MPP = 0.94         # parcel tile: 1 024 Web-Mercator m over 1 024 px at ~20°N


def test_cell_score_separates_the_four_scenes():
    scores = {name: page._parcel_tile_scores(dol_window(*dims, mpp=TILE_MPP), TILE_MPP, 8)
              for name, dims in SCENES.items()}
    mean = {name: float(np.nanmean(s["score"])) for name, s in scores.items()}
    assert mean["shophouse"] >= 0.8
    assert max(mean["town"], mean["suburb"], mean["rural"]) <= 0.35
    assert scores["shophouse"]["score"].shape == (8, 8) and scores["shophouse"]["cover_shop"].mean() > 0.8


def test_a_few_shophouses_beside_farmland_are_not_a_hot_cell():
    image = dol_window(*SCENES["rural"], mpp=TILE_MPP)
    patch = dol_window(*SCENES["shophouse"], mpp=TILE_MPP, specks=0)
    image[300:353, 300:343] = patch[:53, :43]                                  # ten ตึกแถว lots, 40 x 50 m
    result = page._parcel_tile_scores(image, TILE_MPP, 8)
    assert np.nanmax(result["score"]) < page.EVIDENCE_CONFIG["hot_score"]


def test_blank_or_unreadable_parcel_tiles_are_no_data():
    assert page._parcel_tile_scores(np.zeros((SIZE, SIZE, 4), dtype=np.uint8), TILE_MPP, 8) is None
    with pytest.raises(ValueError):
        page._parcel_tile_scores(np.zeros((1001, 1001, 4), dtype=np.uint8), TILE_MPP, 8)   # not a multiple of 8


def test_cells_without_drawn_lines_are_nan_not_low():
    image = dol_window(*SCENES["shophouse"], mpp=TILE_MPP, specks=0)
    image[:, SIZE // 2:] = 0                                                   # right half: no lines at all
    result = page._parcel_tile_scores(image, TILE_MPP, 8)
    assert np.isnan(result["score"][:, 4:]).all() and np.isfinite(result["score"][:, :4]).all()


# ================================================================== clusters
def cluster_world(radius_m=3000.0):
    geo, circle = geometry(radius_m)
    shape_ = (geo["nj"], geo["ni"])
    fields = {name: np.full(shape_, np.nan) for name in ("score", "cover_small", "cover_shop")}
    return geo, circle, fields


def hot(fields, rows, cols, value=0.9):
    for name in fields:
        fields[name][rows, cols] = value if name == "score" else 0.5


def pick(geo, circle, fields, region=None, top=5):
    smooth = page._smooth_nan(fields["score"], 3)
    region = circle if region is None else region
    return page._find_clusters(smooth, region, circle, region, fields, geo, top)


def test_clusters_rank_by_mass_and_tie_break_in_raster_order():
    geo, circle, fields = cluster_world()
    c = geo["nj"] // 2
    hot(fields, slice(c - 12, c - 6), slice(c - 12, c - 6))      # 6 x 6 = 36 cells, south-west
    hot(fields, slice(c + 6, c + 10), slice(c + 6, c + 10))      # 4 x 4 = 16 cells, north-east
    found = pick(geo, circle, fields)
    assert [k["cells"] for k in found] == [36, 16] and [k["rank"] for k in found] == [1, 2]
    assert found[0]["lat"] < found[1]["lat"] and found[0]["lon"] < found[1]["lon"]
    # two equal blobs: the one met first in raster order (lower row) wins, every time
    geo, circle, fields = cluster_world()
    hot(fields, slice(c + 6, c + 10), slice(c - 10, c - 6))
    hot(fields, slice(c - 10, c - 6), slice(c + 6, c + 10))
    first = pick(geo, circle, fields)
    assert first[0]["cells"] == first[1]["cells"] and first[0]["lat"] < first[1]["lat"]
    assert [k["lat"] for k in pick(geo, circle, fields)] == [k["lat"] for k in first]


def test_hot_cells_outside_the_zone_or_the_circle_and_tiny_clusters_are_ignored():
    geo, circle, fields = cluster_world()
    c = geo["nj"] // 2
    hot(fields, slice(c - 4, c), slice(c - 4, c))                # 16 cells inside the zone
    hot(fields, slice(c + 2, c + 3), slice(c + 1, c + 3))        # 2 cells inside the zone: below cluster_min_cells
    hot(fields, slice(c + 8, c + 14), slice(c + 8, c + 14))      # dense, but outside the zone
    region = np.zeros_like(circle)
    region[c - 5:c + 3, c - 5:c + 3] = True
    found = pick(geo, circle, fields, region=region)
    assert len(found) == 1 and found[0]["cells"] == 16 and found[0]["in_zone"] is True
    assert pick(geo, np.zeros_like(circle), fields) == []


def test_a_cluster_on_the_circle_edge_is_flagged():
    geo, circle, fields = cluster_world()
    c = geo["nj"] // 2
    hot(fields, slice(c - 3, c + 1), slice(c - 3, c + 1))
    inner = pick(geo, circle, fields)
    assert inner[0]["touches_boundary"] is False
    geo, circle, fields = cluster_world()
    row = int(np.nonzero(circle.any(axis=1))[0][-1])
    col = int(np.nonzero(circle[row])[0][0])
    hot(fields, slice(row - 3, row + 1), slice(col, col + 4))
    edge = pick(geo, circle, fields)
    assert edge and edge[0]["touches_boundary"] is True


def test_smoothing_ignores_cells_without_data():
    score = np.full((5, 5), np.nan)
    score[2, 2], score[2, 3] = 1.0, 0.0
    smooth = page._smooth_nan(score, 3)
    assert smooth[2, 2] == pytest.approx(0.5) and smooth[2, 3] == pytest.approx(0.5)
    assert np.isnan(smooth[0, 0]) and np.isnan(smooth[2, 1])


# ================================================================== confidence
ROAD_NEAR = [{"lat": 20.2, "lon": 100.4}]
ROAD_FAR = [{"lat": 20.25, "lon": 100.4}]
ANCHOR = {"lat": 20.2, "lon": 100.4}
PEAK = {"name": "พาณิชยกรรม", "commercial": True, "area_km2": 1.2}
CLUSTER = {"cells": 40, "area_ha": 55.0, "score": 0.8, "touches_boundary": False}


def confidence(**kw):
    args = dict(road_anchors=ROAD_NEAR, zoning_ok=True, parcel_ok=True, coverage=1.0, peak=PEAK,
                cluster=CLUSTER, stability_levels=["stable", "stable"])
    args.update(kw)
    return page.classify_anchor_confidence(
        ANCHOR, args.pop("road_anchors"), cfg=page.EVIDENCE_CONFIG, **args)


def test_confidence_high_needs_roads_plan_and_parcels_to_agree():
    result = confidence()
    assert result["level"] == "HIGH" and result["signals"] == {"roads": True, "zoning": True, "parcel": True}
    assert any("พาณิชยกรรม" in r for r in result["reasons"]) and any("cluster" in r for r in result["reasons"])
    # an unstable anchor (roads or evidence), too little data, or a cluster cut by the circle take HIGH away
    assert confidence(stability_levels=["stable", "unstable"])["level"] == "MEDIUM"
    assert confidence(stability_levels=["unstable", None])["level"] == "MEDIUM"
    assert confidence(coverage=0.5)["level"] == "MEDIUM"
    cut = confidence(cluster={**CLUSTER, "touches_boundary": True})
    assert cut["level"] == "MEDIUM" and any("ขอบวง" in r for r in cut["reasons"])


def test_confidence_medium_low_and_reasons_for_missing_or_disagreeing_evidence():
    far = confidence(road_anchors=ROAD_FAR)
    assert far["level"] == "MEDIUM" and far["signals"]["roads"] is False and far["nearest_road_anchor_m"] > 5000
    assert any("ไม่สอดคล้อง" in r for r in far["reasons"])
    no_plan = confidence(zoning_ok=None, peak=None)                          # unreadable plan: never HIGH
    assert no_plan["level"] == "MEDIUM" and no_plan["signals"]["zoning"] is None
    assert any("ไม่มีข้อมูล" in r for r in no_plan["reasons"])
    assert confidence(zoning_ok=None, peak=None, parcel_ok=None, cluster=None, coverage=0.2)["level"] == "LOW"
    weak = confidence(road_anchors=ROAD_FAR, zoning_ok=False, parcel_ok=False, cluster={**CLUSTER, "score": 0.3})
    assert weak["level"] == "LOW" and any("นอกโซนพาณิชยกรรม" in r for r in weak["reasons"])
    assert any("ไม่เด่น" in r for r in weak["reasons"])
    assert confidence(road_anchors=[])["signals"]["roads"] is None


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


# ============================================================ run_evidence_stage (fake world)
CORE = offset(CENTER, 800, 800)       # a ตึกแถว quarter inside a red (พาณิชยกรรม) block, ~1.1 km from the centre
OUT = offset(CENTER, -1500, -1500)    # suburb: a better-scoring *road* node that evidence must not prefer
BLOB_M = 700.0                        # ground radius of the red block / shophouse quarter
_PARCEL_IMAGES = {}


def _parcel_scene(kind):
    if kind not in _PARCEL_IMAGES:
        dims = SCENES[kind] if isinstance(kind, str) else kind
        _PARCEL_IMAGES[kind] = dol_window(*dims, mpp=TILE_MPP, specks=300)
    return _PARCEL_IMAGES[kind]


MID_LOTS = (8.0, 14.0)      # a mid-density town: lots of ~110 m², not ตึกแถว — scores ~0.4, below the absolute 0.5


def make_world(blobs=((CORE, BLOB_M),), fail=(), calls=None, memo=None, plan="ok", delay=0.0,
               red=RED, dense=None, inside_scene="shophouse", dense_scene="shophouse"):
    """A fake Longdo: ``cityplan_dpt`` is green with a red disc per blob, ``dol`` is shophouse lots
    inside a blob and suburban lots elsewhere. Pixels are placed by their Web-Mercator position, so
    any bbox of the lattice is served consistently. ``memo`` emulates the disk cache."""
    def disc_list(items):
        out = []
        for point, radius_m in items:
            x, y = page._WEB_MERCATOR.transform(point[1], point[0])
            out.append((x, y, radius_m / cos(radians(point[0]))))
        return out

    discs, dense_discs = disc_list(blobs), disc_list(dense or ())

    def inside_of(xs, ys, items):
        mask = np.zeros((len(ys), len(xs)), dtype=bool)
        for x, y, r in items:
            if abs(xs.mean() - x) < r + (xs[-1] - xs[0]) and abs(ys.mean() - y) < r + (ys[0] - ys[-1]):
                mask |= (xs[None, :] - x) ** 2 + (ys[:, None] - y) ** 2 <= r * r
        return mask

    def fetch(layer, bbox, px):
        if delay:
            time.sleep(delay)
        key = (layer, tuple(bbox))
        if calls is not None:
            calls.append(key)
        kind = "parcel" if layer == "dol" else "plan"
        info = {"layer": layer, "from_cache": bool(memo is not None and key in memo)}
        if memo is not None:
            memo.add(key)
        if kind in fail:
            return None, {"layer": layer, "error": "HTTP 500", "from_cache": False}
        xs = bbox[0] + (np.arange(px) + 0.5) * (bbox[2] - bbox[0]) / px
        ys = bbox[3] - (np.arange(px) + 0.5) * (bbox[3] - bbox[1]) / px
        inside = inside_of(xs, ys, discs)
        if kind == "plan":
            if plan == "blank":
                return np.zeros((px, px, 4), dtype=np.uint8), info
            image = np.zeros((px, px, 4), dtype=np.uint8)
            image[...] = (*(GREEN if plan in ("ok", "nored") else (120, 120, 200)), 255)
            if plan == "ok":
                image[inside] = (*red, 255)
            return image, info
        if not inside.any():
            return _parcel_scene("suburb").copy(), info
        picture = np.where(inside[..., None], _parcel_scene(inside_scene if dense is None else "town"),
                           _parcel_scene("suburb"))
        if dense is not None:
            picture = np.where(inside_of(xs, ys, dense_discs)[..., None], _parcel_scene(dense_scene), picture)
        return picture.astype(np.uint8), info

    return fetch


def road_found(anchor=CORE, stability="stable"):
    point = {"node_id": "a", "lat": anchor[0], "lon": anchor[1], "score": 0.8}
    return {"composite": {"anchor": point, "stability": {"level": stability}}, "closeness": {"anchor": dict(point)}}


def stage(found, fetcher, radius_m=5000.0, center=CENTER, **kw):
    return page.run_evidence_stage(found, center, radius_m, fetcher=fetcher, **kw)


def dist_m(a, b):
    return page.calculate_distance_meters(a[0], a[1], b[0], b[1])


def test_stage_anchors_on_the_dense_cluster_inside_the_peak_colour_zone():
    result = stage(road_found(anchor=OUT), make_world())
    assert result["schema"] == page.EVIDENCE_SCHEMA and result["status"] == "ok" and result["reason"] is None
    anchor = result["evidence_anchor"]
    assert anchor["source"] == "Automated CBD Anchor — Evidence" and anchor["basis"] == "cluster"
    assert dist_m((anchor["lat"], anchor["lon"]), CORE) < 150               # the road anchor was 2 km away
    peak = result["plan"]["peak"]
    assert peak["name"] == "สีแดง" and peak["commercial"] and peak["rgb"] == [255, 0, 0]
    assert result["plan"]["state"] == "ok" and result["plan"]["explained"] == pytest.approx(1.0)
    assert result["parcel"]["region"] == "peak_zone" and result["parcel"]["tiles_skipped"] == 0
    best = result["clusters"][0]
    assert best["in_zone"] and best["score"] > 0.7 and best["polygon"]["type"] in ("Polygon", "MultiPolygon")
    assert result["plan"]["zones"][0]["area_km2"] == pytest.approx(np.pi * 0.7 ** 2, rel=0.2)
    # the road anchors disagree (2 km away), the plan and the parcels agree → not HIGH
    assert result["confidence"]["signals"] == {"roads": False, "zoning": True, "parcel": True}
    assert result["confidence"]["level"] == "MEDIUM"


def test_stage_is_high_confidence_when_roads_plan_and_parcels_agree():
    result = stage(road_found(anchor=CORE), make_world())
    assert result["confidence"]["level"] == "HIGH" and result["confidence"]["coverage"] == pytest.approx(1.0)
    assert result["stability"]["level"] == "stable"
    # an unstable road anchor caps the confidence
    assert stage(road_found(anchor=CORE, stability="unstable"), make_world())["confidence"]["level"] != "HIGH"


def test_the_anchor_does_not_depend_on_the_radius_or_on_where_the_circle_is_centred():
    reference = stage(road_found(), make_world(), radius_m=5000.0)["evidence_anchor"]
    for radius_m in (4000.0, 10_000.0, 20_000.0):
        other = stage(road_found(), make_world(), radius_m=radius_m)["evidence_anchor"]
        assert (other["lat"], other["lon"]) == (reference["lat"], reference["lon"])
    shifted = stage(road_found(), make_world(), center=offset(CENTER, 300, -250))["evidence_anchor"]
    assert dist_m((shifted["lat"], shifted["lon"]), (reference["lat"], reference["lon"])) <= 128.0


def test_a_second_run_costs_no_request_and_a_wider_circle_only_fetches_new_tiles():
    memo, calls = set(), []
    world = make_world(memo=memo, calls=calls)
    first = stage(road_found(), world, radius_m=4000.0)
    seen = set(calls)
    assert first["fetch"]["cache_hits"] == 0 and first["fetch"]["requests"] == len(calls) > 0
    calls.clear()
    again = stage(road_found(), world, radius_m=4000.0)
    assert again["fetch"]["requests"] == 0 and again["fetch"]["cache_hits"] == len(calls) and set(calls) == seen
    calls.clear()
    wider = stage(road_found(), world, radius_m=20_000.0)
    new = set(calls) - seen
    assert new and all(layer == "cityplan_dpt" for layer, _ in new)       # only more of the plan
    assert wider["fetch"]["requests"] == len(new) and seen <= set(calls)
    assert wider["evidence_anchor"] == again["evidence_anchor"] | {"coverage": wider["evidence_anchor"]["coverage"]}


def test_request_budget_is_respected_and_what_was_skipped_is_reported(monkeypatch):
    monkeypatch.setitem(page.EVIDENCE_CONFIG, "max_parcel_tiles", 2)
    calls = []
    result = stage(road_found(), make_world(calls=calls))
    assert sum(1 for layer, _ in calls if layer == "dol") == 2
    assert result["parcel"]["tiles_needed"] > 2 and result["fetch"]["skipped_over_budget"] > 0
    assert result["status"] == "partial" and result["confidence"]["coverage"] < 0.6
    assert result["confidence"]["level"] != "HIGH"
    monkeypatch.setitem(page.EVIDENCE_CONFIG, "max_requests", 3)
    monkeypatch.setitem(page.EVIDENCE_CONFIG, "max_parcel_tiles", 16)
    calls.clear()
    stage(road_found(), make_world(calls=calls))
    assert len(calls) <= 3


def test_a_zone_bigger_than_the_budget_is_scanned_from_the_study_centre_outwards(monkeypatch):
    monkeypatch.setitem(page.EVIDENCE_CONFIG, "max_parcel_tiles", 4)
    calls = []
    result = stage(road_found(), make_world(blobs=((CENTER, 3000.0),), calls=calls), radius_m=5000.0)
    x, y = page._WEB_MERCATOR.transform(CENTER[1], CENTER[0])
    fetched = [bbox for layer, bbox in calls if layer == "dol"]
    assert len(fetched) == 4 and result["parcel"]["tiles_needed"] > 20
    for bbox in fetched:                                           # the 2 x 2 block of tiles around the centre
        assert hypot((bbox[0] + bbox[2]) / 2 - x, (bbox[1] + bbox[3]) / 2 - y) < 1000
    assert result["status"] == "partial" and result["confidence"]["level"] != "HIGH"


def test_a_slow_server_hits_the_deadline_instead_of_hanging(monkeypatch):
    monkeypatch.setitem(page.EVIDENCE_CONFIG, "deadline_s", 0.3)
    monkeypatch.setitem(page.EVIDENCE_CONFIG, "parallel", 1)
    started = time.perf_counter()
    result = stage(road_found(), make_world(delay=0.5))
    assert time.perf_counter() - started < 3.0
    assert result["status"] == "unavailable" and result["fetch"]["skipped_over_budget"] > 0
    assert any("หมดเวลา" in e for e in result["fetch"]["errors"])


@pytest.mark.parametrize("plan_kind, state", [("blank", "blank"), ("mismatch", "no_peak")])
def test_an_unreadable_plan_falls_back_to_the_parcels_around_the_road_anchor(plan_kind, state):
    result = stage(road_found(anchor=CORE), make_world(plan=plan_kind))
    assert result["plan"]["state"] == state and result["plan"]["peak"] is None
    assert result["status"] == "partial" and result["parcel"]["region"] == "fallback_disc"
    assert dist_m((result["evidence_anchor"]["lat"], result["evidence_anchor"]["lon"]), CORE) < 300
    assert any("รอบ anchor ถนน" in n for n in result["notes"])
    assert result["confidence"]["signals"]["zoning"] is None and result["confidence"]["level"] != "HIGH"
    # without a road anchor there is nowhere to look
    nowhere = stage({}, make_world(plan=plan_kind))
    assert nowhere["status"] == "unavailable" and "anchor ถนน" in nowhere["reason"]
    outside = stage(road_found(anchor=offset(CENTER, 30_000, 0)), make_world(plan=plan_kind))
    assert outside["status"] == "unavailable" and "นอกวงศึกษา" in outside["reason"]   # nothing to scan around it


def test_with_no_red_zone_in_the_radius_the_stage_does_not_fall_to_a_lower_colour():
    # the plan is green everywhere: no พาณิชยกรรม ⇒ no peak zone ⇒ parcels around the road anchor, flagged
    # partial, never HIGH (a lower colour such as dense residential is never promoted to "the highest zone")
    result = stage(road_found(anchor=CORE), make_world(plan="nored"), radius_m=10_000.0)
    assert result["plan"]["state"] == "no_peak" and result["plan"]["peak"] is None and result["plan"]["zones"] == []
    assert result["status"] == "partial" and result["parcel"]["region"] == "fallback_disc"
    assert dist_m((result["evidence_anchor"]["lat"], result["evidence_anchor"]["lon"]), CORE) < 300
    assert any("พาณิชยกรรม" in n and "รอบ anchor ถนน" in n for n in result["notes"])
    assert result["confidence"]["signals"]["zoning"] is None and result["confidence"]["level"] != "HIGH"


def test_several_red_zones_give_the_densest_cluster_whatever_centre_was_entered():
    town, village = CORE, offset(CENTER, -2600, -1800)
    world = ((town, 800.0), (village, 350.0))
    results = [stage(road_found(anchor=town), make_world(world), radius_m=10_000.0, center=center)
               for center in (CENTER, village, offset(CENTER, 2000, 2500))]
    for result in results:
        assert len(result["plan"]["zones"]) == 2
        assert dist_m((result["evidence_anchor"]["lat"], result["evidence_anchor"]["lon"]), town) < 150
    assert len({(r["evidence_anchor"]["lat"], r["evidence_anchor"]["lon"]) for r in results}) == 1


@pytest.mark.parametrize("shade", [(214, 140, 170), (255, 170, 190), (190, 30, 30)])
def test_the_red_zone_is_found_whatever_shade_of_red_the_server_draws(shade):
    # Longdo's real red is not known: a legend colour that is not (255, 0, 0) must not lose the zone
    reference = stage(road_found(anchor=OUT), make_world(), radius_m=10_000.0)
    result = stage(road_found(anchor=OUT), make_world(red=shade), radius_m=10_000.0)
    assert result["status"] == "ok" and result["plan"]["peak"]["rgb"] == list(shade)
    assert result["evidence_anchor"] == reference["evidence_anchor"] | {"coverage": result["evidence_anchor"]["coverage"]}
    seen = {c["hex"]: c for c in result["plan"]["colours"]}
    assert any(c["red"] and c["legend"] is None for c in seen.values()) or shade == (190, 30, 30)
    assert result["plan"]["colours"][0]["share"] > 0.5 and json.dumps(result["plan"]["colours"])


def test_a_mid_density_town_still_gets_its_densest_cluster_and_an_honest_confidence():
    # lots of ~110 m² score ~0.4: below the absolute 0.5, but the densest quarter of the red zone is still "ถี่"
    dense = ((offset(CORE, 500, 0), 350.0),)
    world = make_world(blobs=((CORE, 1000.0),), dense=dense, dense_scene=MID_LOTS)
    result = stage(road_found(anchor=CORE), world, radius_m=10_000.0)
    assert result["status"] == "ok" and result["evidence_anchor"]["basis"] == "cluster"
    assert dist_m((result["evidence_anchor"]["lat"], result["evidence_anchor"]["lon"]), dense[0][0]) < 250
    parcel = result["parcel"]
    assert 0 < parcel["best_score"] < page.EVIDENCE_CONFIG["hot_score"] and parcel["hot_threshold"] < 0.5
    assert parcel["lots"] > 1000
    assert result["confidence"]["signals"]["parcel"] is False and result["confidence"]["level"] != "HIGH"


def test_the_hot_threshold_is_absolute_when_the_zone_is_dense_and_relative_when_it_is_not():
    cfg = page.EVIDENCE_CONFIG
    dense = np.full(100, 0.8)
    assert page._hot_threshold(dense) == cfg["hot_score"]
    mid = np.concatenate([np.full(75, 0.1), np.linspace(0.3, 0.45, 25)])
    assert cfg["hot_floor"] <= page._hot_threshold(mid) < cfg["hot_score"]
    assert page._hot_threshold(np.full(50, 0.01)) == cfg["hot_floor"]


def test_parcels_that_cannot_be_read_leave_the_centre_of_the_peak_zone():
    result = stage(road_found(anchor=CORE), make_world(fail=("parcel",)))
    assert result["status"] == "partial" and result["evidence_anchor"]["basis"] == "zone"
    assert dist_m((result["evidence_anchor"]["lat"], result["evidence_anchor"]["lon"]), CORE) < 150
    assert result["clusters"] == [] and result["confidence"]["level"] == "LOW"
    assert result["confidence"]["coverage"] == 0.0 and result["fetch"]["errors"]


def test_stage_without_any_image_is_unavailable_and_leaves_the_roads_alone():
    found = road_found()
    snapshot = json.dumps(found, sort_keys=True)
    result = stage(found, make_world(fail=("parcel", "plan")))
    assert result["status"] == "unavailable" and result["evidence_anchor"] is None and result["confidence"] is None
    assert result["reason"] and result["fetch"]["errors"] and "HTTP 500" in result["fetch"]["errors"][0]
    assert json.dumps(found, sort_keys=True) == snapshot            # the road result is untouched


def test_stage_never_raises_whatever_the_fetcher_or_the_input_does():
    def exploding(layer, bbox, px):
        raise RuntimeError("proxy melted")

    broken = stage(road_found(), exploding)
    assert broken["status"] == "unavailable" and "proxy melted" in " ".join(broken["fetch"]["errors"])
    assert stage(road_found(), lambda layer, bbox, px: (np.zeros((7, 7, 4), dtype=np.uint8), {}))["status"] == "unavailable"
    for found in (None, {}, {"composite": None}, {"composite": {"anchor": {}}, "closeness": {}}):
        result = stage(found, make_world())
        assert result["status"] in ("ok", "partial") and result["confidence"]["signals"]["roads"] is None
    assert page.run_evidence_stage(road_found(), (float("nan"), 100.4), 5000.0, fetcher=make_world())["status"] == "unavailable"


def test_stage_result_is_json_safe_deterministic_and_small():
    first = stage(road_found(), make_world())
    second = stage(road_found(), make_world())
    text = json.dumps(first, sort_keys=True)                          # no numpy scalars / arrays
    first["fetch"].pop("seconds"), second["fetch"].pop("seconds")
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
    assert len(text) < 60_000                                         # no raster is stored in the result
    assert "_x" not in text and "_y" not in text


def test_a_bigger_quarter_far_away_keeps_winning_when_the_circle_grows():
    # two quarters; the bigger one is far east. Growing the circle must not change the answer.
    near, far = offset(CENTER, -600, 300), offset(CENTER, 3200, 0)
    world = ((near, 450.0), (far, 800.0))
    big = stage(road_found(), make_world(world), radius_m=5000.0)
    assert dist_m((big["evidence_anchor"]["lat"], big["evidence_anchor"]["lon"]), far) < 200
    wide = stage(road_found(), make_world(world), radius_m=9000.0)
    assert (wide["evidence_anchor"]["lat"], wide["evidence_anchor"]["lon"]) == (
        big["evidence_anchor"]["lat"], big["evidence_anchor"]["lon"])


def test_stability_probe_calls_out_a_winner_that_flips_when_the_circle_shrinks():
    near, far = offset(CENTER, -500, 0), offset(CENTER, 3350, 0)       # the bigger quarter sits at 84 % of R = 4 km
    result = stage(road_found(), make_world(((near, 400.0), (far, 450.0))), radius_m=4000.0)
    assert dist_m((result["evidence_anchor"]["lat"], result["evidence_anchor"]["lon"]), far) < 250
    assert result["stability"]["level"] == "unstable" and result["stability"]["max_drift_ratio"] > 0.15
    assert result["confidence"]["level"] != "HIGH" and any("ไม่นิ่ง" in r for r in result["confidence"]["reasons"])
    calm = stage(road_found(), make_world(), radius_m=5000.0)["stability"]
    assert calm["level"] == "stable" and calm["cases"] == 5 and calm["max_drift_m"] <= 0.05 * 5000


def test_a_quarter_cut_by_the_circle_edge_is_flagged_and_cannot_be_high_confidence():
    edge = offset(CENTER, 3700, 0)
    result = stage(road_found(anchor=edge), make_world(((edge, 600.0),)), radius_m=4000.0)
    assert result["clusters"] and result["clusters"][0]["touches_boundary"] is True
    assert result["confidence"]["level"] != "HIGH" and any("ขอบวง" in r for r in result["confidence"]["reasons"])


def test_the_estimate_shown_before_a_run_matches_what_a_run_requests():
    calls = []
    estimate = page.estimate_evidence_requests(CENTER, 10_000.0)
    result = stage(road_found(), make_world(calls=calls), radius_m=10_000.0)
    assert result["plan"]["tiles"] == estimate["plan_tiles"]
    assert len(calls) <= estimate["requests_max"]
