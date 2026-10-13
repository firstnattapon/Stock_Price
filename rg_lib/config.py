"""Core — constants and configuration: API defaults, the ``*_CONFIG`` dicts, colours, URLs, file locations.

Definitions are cut verbatim from pages/Rent_Gradient.py (see tests/test_rg_v2_equivalence.py).
"""


import re
import threading
from pathlib import Path
from pyproj import Transformer
from typing import Any, Dict, List, Optional


PAGE_CONFIG: Dict[str, Any] = {
    "page_title": "Geoapify CBD x Longdo GIS + Network Analysis",
    "page_icon": "🌍",
    "layout": "wide",
}


DEFAULT_CONFIG: Dict[str, Any] = {
    "JSON_URL": (
        "https://raw.githubusercontent.com/firstnattapon/Stock_Price/"
        "refs/heads/main/Geoapify_Map/geoapify_cbd_project.json"
    ),
    "LAT": 20.219443,
    "LON": 100.403630,
    "GEOAPIFY_KEY": "4eefdfb0b0d349e595595b9c03a69e3d",
    "LONGDO_KEY": "0a999afb0da60c5c45d010e9c171ffc8",
}


LONGDO_WMS_URL: str = (
    f"https://ms.longdo.com/mapproxy/service?key={DEFAULT_CONFIG['LONGDO_KEY']}"
)


# --- Visual Assets ---
MARKER_COLORS: List[str] = [
    "red", "blue", "green", "purple", "orange", "black", "pink", "cadetblue"
]


HEX_COLORS: List[str] = [
    "#D63E2A", "#38AADD", "#72B026", "#D252B9",
    "#F69730", "#333333", "#FF91EA", "#436978",
]


MAP_STYLES: Dict[str, Dict[str, Optional[str]]] = {
    "Esri Light Gray (แนะนำสำหรับดูผังเมือง)": {
        "tiles": (
            "https://server.arcgisonline.com/ArcGIS/rest/services/"
            "Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}"
        ),
        "attr": "Tiles &copy; Esri",
    },
    "Google Maps (ผสม/Hybrid)": {
        "tiles": "https://mt1.google.com/vt/lyrs=y&x={x}&y={y}&z={z}",
        "attr": "Google Maps",
    },
    "OpenStreetMap (มาตรฐาน)": {
        "tiles": "OpenStreetMap",
        "attr": None,
    },
    "Esri Satellite (ดาวเทียมชัด)": {
        "tiles": (
            "https://server.arcgisonline.com/ArcGIS/rest/services/"
            "World_Imagery/MapServer/tile/{z}/{y}/{x}"
        ),
        "attr": "Tiles &copy; Esri",
    },
}


TRAVEL_MODE_NAMES: Dict[str, str] = {
    "drive": "🚗 ขับรถ",
    "walk": "🚶 เดินเท้า",
    "bicycle": "🚲 ปั่นจักรยาน",
    "transit": "🚌 ขนส่งสาธารณะ",
}


TIME_OPTIONS: List[int] = [5, 10, 15, 20, 30, 45, 60]


# Network Analysis Configuration
NETWORK_CONFIG: Dict[str, Any] = {
    "min_closeness_threshold": 0.0,
    "edge_weight_base": 2,
    "edge_weight_multiplier": 4,
    "cache_ttl_seconds": 3600,
    "click_debounce_seconds": 0.5,
    "click_distance_threshold_meters": 10,
    "large_graph_threshold": 2000,
    "betweenness_k_samples": 400,
    "closeness_exact_threshold": 3000,
    "closeness_k_pivots": 600,
    "golden_land_top_n": 10,
    "golden_land_min_spacing_m": 150.0,  # ไม่เลือกสองจุดที่ใกล้กว่านี้ (กันผลซ้ำที่ทางแยกเดียว)
    "golden_land_weights": {
        "closeness": 0.50,
        "degree": 0.30,
        "low_traffic_bonus": 0.20,
    },
}


ANCHOR_CONFIG: Dict[str, Any] = {
    # Serve a request from a cached graph whose download footprint fully contains it.
    "reuse_covering_cache": True,
    "buffer_ratio": 0.20,
    "density_radius_m": 500.0,
    "max_nodes": 100000,
    "batch_size": 16,
    # Exact Dijkstra rows are the only expensive step: one row costs ~V units, so
    # the exhaustive budget is max_row_nodes // V rows (V=2k -> 4096, V=40k -> ~750).
    "max_row_nodes": 30_000_000,
    "min_rows": 64,
    "max_rows": 4096,
    # Fixed, seed-independent reference sample of destinations. Its exact closeness
    # values calibrate the composite normaliser, and its distance rows rank every
    # candidate when the exhaustive pass does not fit the budget. These rows are
    # extra to the row budget and are never recomputed.
    "reference_nodes": 256,
    "reference_shrink_above_nodes": 25_000,  # beyond this the sample shrinks ~ 1/sqrt(V)
    "reference_min_nodes": 96,
    "reference_seed": 0,
    "screen_top_k": 256,
    "refine_iterations": 40,
    "candidate_export": 150,  # top nodes per objective handed to the evidence stage (it thins them by spacing)
    "boundary_warn_ratio": 0.40,
    # Indicative stability probe: how far does the anchor move if the user's circle
    # is rescaled / shifted? Drift is judged against the study radius.
    "stability_scales": (0.8, 1.2),
    "stability_shift": 0.20,
    "stability_top_m": 16,
    # Probe-only second stratum of pivots drawn from the ring outside the study circle
    # (the perturbed circles reach up to 1.2 R); the base anchor never depends on it.
    "stability_outer_nodes": 96,
    "stability_ok_ratio": 0.05,
    "stability_warn_ratio": 0.15,
}


# OSMnx uses one process-global Overpass URL. Keep downloads serialized while
# switching endpoints so concurrent Streamlit sessions cannot leak settings.
OVERPASS_CONFIG: Dict[str, Any] = {
    "endpoints": [
        "https://overpass-api.de/api",
        "https://maps.mail.ru/osm/tools/overpass/api",
        "https://overpass.private.coffee/api",
    ],
    "attempts_per_endpoint": 1,
    "retry_backoff_seconds": 1.0,
}


_OVERPASS_LOCK = threading.RLock()


# Rent Gradient (Bid-Rent Model: Alonso-Muth-Mills) Configuration
# หลักการ: ค่าเช่า/มูลค่าที่ดินลดลงแบบ negative exponential ตามระยะจาก CBD
#   R(d) = R₀ · e^(−λ·d)
RENT_CONFIG: Dict[str, Any] = {
    "base_index": 100.0,        # R₀ เมื่อยังไม่มีตัวอย่างราคาจริง (โหมดดัชนี 0–100)
    "edge_decay_ratio": 4.0,    # ค่า λ เริ่มต้น: ดัชนีลดเหลือ 1/4 ที่ขอบพื้นที่ศึกษา
    "num_rings": 6,             # จำนวนวงแหวนราคาบนแผนที่
    "ring_fill_opacity": 0.16,
    "curve_points": 80,         # ความละเอียดเส้นโค้ง Bid-Rent
    "min_lambda": 1e-6,
    "min_reliable_samples": 5,  # ต่ำกว่านี้ R²/λ ยังไม่น่าเชื่อถือ (2 จุด → R² = 1 เสมอ)
    "default_d_max_km": 5.0,
    "min_d_max_km": 0.3,
}


# Sequential ramp (อ่อน→เข้ม = ค่าเช่าต่ำ→สูง) สำหรับวงแหวน/heat ของ Rent Gradient
RENT_RAMP: List[str] = [
    "#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b",
]


# สีกราฟ Bid-Rent Curve (ผ่านการตรวจ colorblind-safe + contrast แล้ว)
CHART_COLOR_CURVE: str = "#2a78d6"


CHART_COLOR_SAMPLES: str = "#eb6834"


CHART_COLOR_MUTED: str = "#898781"


# Timeout constants (seconds)
TIMEOUT_API: int = 15


TIMEOUT_INIT: int = 3


TIMEOUT_GITHUB_LIST: int = 10


TIMEOUT_GITHUB_DOWNLOAD: int = 60


BUNDLE_VERSION: str = "1.0"


CACHE_FORMAT_VERSION: str = "1.0"


CONFIG_SCHEMA_VERSION: int = 2


MAX_CACHE_ENTRY_BYTES: int = 150 * 1024 * 1024


# Map Geoapify travel_mode -> OSMnx network_type
TRAVEL_MODE_TO_NETWORK_TYPE: Dict[str, str] = {
    "drive": "drive",
    "walk": "walk",
    "bicycle": "bike",
    "transit": "drive",  # OSMnx has no transit; fallback to drive
}


# Keys to persist in config file
SESSION_KEYS_TO_SAVE: List[str] = [
    "api_key", "map_style_name", "travel_mode", "time_intervals",
    "show_dol", "show_cityplan", "cityplan_opacity", "show_population",
    "show_traffic", "colors", "show_betweenness", "show_closeness",
    "show_railway", "show_golden_spots",
    "rent_samples", "rent_unit_label", "show_rent_rings", "show_rent_nodes",
    "anchor_lat", "anchor_lon", "anchor_radius_km",
    "anchor_use_evidence", "rent_use_evidence_anchor",
    "anchor_seed", "anchor_restarts",  # legacy: accepted from old configs, no longer used
]


# Keys to persist as precomputed outputs (avoid recalculation after import)
RESULT_KEYS_TO_SAVE: List[str] = [
    "isochrone_data",
    "intersection_data",
    "network_data",
    "rent_gradient_data",
    "automated_anchor_data",
    "automated_anchor_closeness_data",
    "automated_anchor_evidence_data",
]


# GitHub Cache Repository Configuration
GITHUB_BUNDLE_URL: str = (
    "https://raw.githubusercontent.com/firstnattapon/Stock_Price/main/Geoapify_Map/%E0%B9%80%E0%B8%8A%E0%B8%B5%E0%B8%A2%E0%B8%87%E0%B8%82%E0%B8%AD%E0%B8%87.zip"
)


PARCEL_CONFIG: Dict[str, Any] = {
    "alpha_threshold": 32,            # pixel counts as a drawn line above this alpha
    "opaque_bg_tolerance": 60,        # opaque images: colour distance from the dominant colour
    "closing_size": 1,                # >1 bridges gaps in boundary lines; off by default: a 3x3 closing
                                      # also fills real 2-px-wide cells (ตึกแถว at ~1.5 m/px)
    "speck_px": 6,                    # cells smaller than this are label clutter
    "giant_cell_ratio": 0.05,         # a free cell above 5% of the window is "no parcels here"
    "small_cell_m2": 200.0,           # 50 ตร.ว.
    "shophouse_area_m2": (40.0, 160.0),
    "shophouse_min_aspect": 2.5,
    "min_cells": 10,                  # fewer measurable cells -> no data
    "min_ink_ratio": 0.002,           # (almost) blank layer -> no data
    "ink_low": 0.03,                  # ink share that scores 0 / 1 in the blend
    "ink_high": 0.40,
    "score_weights": {"shophouse": 0.40, "small": 0.30, "ink": 0.30},
}


CITYPLAN_LEGEND_FILE: Path = (
    Path(__file__).resolve().parent.parent / "Geoapify_Map" / "cityplan_legend.json"
)


# PROVISIONAL colours after the DPT zoning convention — real tiles have not been compared
# yet. Replace with Geoapify_Map/cityplan_legend.json (written from the capture script's
# colour histogram); a wrong colour only lowers plan coverage, which counts as "no data".
CITYPLAN_PROVISIONAL_LEGEND: List[Dict[str, Any]] = [
    {"name": "พาณิชยกรรม", "rgb": [255, 0, 0], "weight": 1.00, "commercial": True},
    {"name": "ที่อยู่อาศัยหนาแน่นมาก", "rgb": [153, 76, 0], "weight": 0.80, "commercial": False},
    {"name": "ที่อยู่อาศัยหนาแน่นปานกลาง", "rgb": [255, 153, 0], "weight": 0.50, "commercial": False},
    {"name": "ที่อยู่อาศัยหนาแน่นน้อย", "rgb": [255, 255, 0], "weight": 0.25, "commercial": False},
    {"name": "สถาบันราชการและสาธารณูปโภค", "rgb": [0, 0, 255], "weight": 0.40, "commercial": False},
    {"name": "อุตสาหกรรมและคลังสินค้า", "rgb": [153, 51, 255], "weight": 0.10, "commercial": False},
    {"name": "เกษตรกรรมและชนบท", "rgb": [0, 176, 80], "weight": 0.00, "commercial": False},
    {"name": "อนุรักษ์และนันทนาการ", "rgb": [0, 100, 0], "weight": 0.00, "commercial": False},
]


ZONING_COLOR_TOLERANCE: float = 60.0  # RGB distance to a legend colour; beyond it = label/outline


CELL_M: float = 128.0               # one analysis cell, in Web-Mercator metres (~120 m on the ground at 20°N)


EVIDENCE_SCHEMA: int = 2            # 1 = the earlier candidate-first result (stale when loaded from a saved config)


EVIDENCE_ANCHOR_SOURCE: str = "Automated CBD Anchor — Evidence"


EVIDENCE_CONFIG: Dict[str, Any] = {
    "px": 1024,
    "plan_tile_m": 16384.0,         # Web-Mercator metres per plan tile: 128x128 cells, 16 m/px (zones, not lots)
    "parcel_tile_m": 1024.0,        # per parcel tile: 8x8 cells, 1 m/px so 1-2 px boundary lines still leave ตึกแถว lots
    "parcel_window_m": 1000.0,      # nominal ground size of one parcel window (capture script / fixture tests)
    "parcel_layer": "dol",
    "plan_layer": "cityplan_dpt",
    "peak_cell_share": 0.40,        # a cell belongs to the peak zone when this share of its pixels is red
    "zone_min_cells": 4,            # a peak zone needs this many connected cells (~0.06 km²)
    "zone_top": 5,
    "plan_min_painted": 0.002,      # painted share of the plan pixels below this = blank / outside the plan
    "fallback_radius_m": 1500.0,    # plan unreadable: look this far around the composite road anchor instead
    "cover_ref": 0.50,              # a cell half covered by small lots already scores full
    "smooth_cells": 3,              # box mean over 3x3 cells before looking for hot cells
    "hot_score": 0.50,              # a smoothed cell this dense is hot in absolute terms ...
    "hot_quantile": 0.75,           # ... otherwise the densest quarter of the red zone is (never below hot_floor)
    "hot_floor": 0.10,
    "reach_m": 2000.0,              # cluster choice: mass / (1 + (distance from the study centre / reach)²) — radius-free
    "cluster_min_cells": 3,
    "cluster_top": 5,
    "max_plan_tiles": 16,
    "max_parcel_tiles": 16,
    "max_requests": 40,
    "parallel": 4,
    "timeout_s": 15,                # per request
    "deadline_s": 60.0,             # per run: unfinished tiles are dropped and reported
    "agree_radius_m": 300.0,        # evidence anchor vs a road anchor counts as "agreeing" within this
    "confidence": {"parcel_ok": 0.50, "coverage_min": 0.60, "coverage_medium": 0.40},
    "stability": {"shrink": 0.8, "grow": 1.2, "shift": 0.2, "shift_max_m": 1000.0, "stable": 0.05, "check": 0.15},
}


_WEB_MERCATOR = Transformer.from_crs("EPSG:4326", "EPSG:3857", always_xy=True)


_WEB_MERCATOR_INV = Transformer.from_crs("EPSG:3857", "EPSG:4326", always_xy=True)


# Two-sided 95% Student-t critical values for small degrees of freedom.
_T_CRIT_975: Dict[int, float] = {
    1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447, 7: 2.365,
    8: 2.306, 9: 2.262, 10: 2.228, 11: 2.201, 12: 2.179, 13: 2.160, 14: 2.145,
    15: 2.131, 16: 2.120, 17: 2.110, 18: 2.101, 19: 2.093, 20: 2.086,
    25: 2.060, 30: 2.042, 40: 2.021, 60: 2.000, 120: 1.980,
}


# A pickle can execute arbitrary code while it loads. Cache files and imported
# bundles are therefore read only through an allow-list that admits the graph
# containers OSMnx produces (NetworkX classes, shapely geometries rebuilt from
# WKB, NumPy scalars/dtypes and plain builtins) and rejects every other global.
_PICKLE_SAFE_BUILTINS = frozenset({
    "dict", "list", "set", "frozenset", "tuple", "int", "float", "complex",
    "str", "bytes", "bytearray", "bool", "slice", "range",
})


_PICKLE_ALLOWED_GLOBALS = frozenset({
    ("collections", "OrderedDict"), ("collections", "defaultdict"),
    ("numpy", "dtype"), ("numpy", "ndarray"),
    ("numpy.core.multiarray", "scalar"), ("numpy._core.multiarray", "scalar"),
    ("numpy.core.multiarray", "_reconstruct"), ("numpy._core.multiarray", "_reconstruct"),
    ("shapely.io", "from_wkb"), ("shapely", "from_wkb"),
})


_PICKLE_ALLOWED_CLASS_PREFIXES = ("networkx.classes.", "shapely.geometry.")


_CACHE_FILE_RE = re.compile(r"^osm_graph_[0-9a-f]{32}\.pkl$")


# Path to the bundled KML file (it lives in pages/, not next to this module)
_KML_FILE_PATH: Path = (
    Path(__file__).resolve().parent.parent / "pages"
    / "เวนคืนรถไฟเด่นชัย - เชียงราย - เชียงของ ตอน 1-2.kml"
)


_KML_NS: Dict[str, str] = {"kml": "http://www.opengis.net/kml/2.2"}


_ANCHOR_CONTEXT_KEYS = ("study_center", "study_radius_m", "network_type")
