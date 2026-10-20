"""
Rent Gradient v2 — ชั้นแผนที่ (Layers): Isochrone · CBD · Network · Space Syntax · Anchor · Rent Gradient
==========================================================================================================
หน้าเดียวที่รวมทุกฟังก์ชันของ ``Rent_Gradient.py`` กับ Space Syntax จาก ``Rent_Gradient_new.py``
โดยจัดเป็น "ชั้นแผนที่" บนแผนที่เดียว (เรียบง่าย · เสถียร · เร็ว) — ดูรายละเอียดที่ docs/rent-gradient-new-v2.md

อ่านไฟล์นี้อย่างไร: โค้ดแบ่งเป็น 3 โซน
  ENGINE  ฟังก์ชันคำนวณล้วน (ไม่เรียก ``st.*``) คัดลอกตรงตัวจากสองหน้าเดิม ล็อกด้วย tests/test_rent_gradient_new_v2.py
          → ผลคำนวณเท่าเดิมทุกตัวเลข ไม่ต้องอ่านหรือแก้ถ้าไม่ได้เปลี่ยนวิธีคำนวณ
  SHELL   state · stages (ปุ่ม Run ↔ ผลลัพธ์) · LAYERS (ตาราง) · แผงควบคุม · views · main()
  TESTS   ledger ครบทุกฟังก์ชัน + เทสต์ layer/stage/state
"""

from __future__ import annotations

import streamlit as st
import folium
from folium.plugins import Fullscreen, MeasureControl, MousePosition
from branca.element import MacroElement, Template
from streamlit_folium import st_folium
import requests
from shapely.geometry import LineString, shape, mapping, box
from shapely.ops import unary_union
from shapely import wkt
import json
import networkx as nx
import osmnx as ox
import matplotlib
import matplotlib.colors as colors
from typing import Callable, List, Dict, Any, Optional, Sequence, Tuple
from collections import OrderedDict
from dataclasses import dataclass, field
from html import escape
from concurrent.futures import ThreadPoolExecutor, wait
import time
import hashlib
import pickle
import os
import re
import threading
from pathlib import Path
import zipfile
import io
import xml.etree.ElementTree as ET
import pandas as pd
from math import radians, sin, cos, sqrt, atan2, log, exp, pi, floor, hypot

# Automated CBD search uses metric coordinates, independent of map projection.
from pyproj import CRS, Transformer

# scipy เป็น optional accelerator สำหรับ closeness (fallback เป็น networkx ถ้าไม่มี)
try:
    import numpy as np
    from scipy.sparse import csr_matrix
    from scipy.sparse.csgraph import connected_components as csgraph_components
    from scipy.sparse.csgraph import dijkstra as csgraph_dijkstra
    from scipy import ndimage as ndi
    HAS_SCIPY: bool = True
except Exception:
    HAS_SCIPY = False

# Space Syntax cannot run without scipy (graph search, ranks) — unlike the optional accelerators above
from scipy.sparse.csgraph import connected_components, dijkstra
from scipy.stats import rankdata


# ============================================================================
# SECTION 1: CONSTANTS & CONFIGURATION
# ============================================================================

PAGE_CONFIG: Dict[str, Any] = {
    "page_title": "Rent Gradient v2 — ชั้นแผนที่",
    "page_icon": "🗺️",
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
    # พื้นหลังมืดสำหรับชั้น Space Syntax (แดง→น้ำเงินอ่านง่ายที่สุดบนพื้นดำแบบ depthmap)
    "พื้นดำ (เหมือน depthmap)": {"tiles": None, "attr": None},
    "Dark (CARTO)": {
        "tiles": "https://basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png",
        "attr": "&copy; OpenStreetMap contributors &copy; CARTO",
    },
}

TRAVEL_MODE_NAMES: Dict[str, str] = {
    "drive": "🚗 ขับรถ",
    "walk": "🚶 เดินเท้า",
    "bicycle": "🚲 ปั่นจักรยาน",
    "transit": "🚌 ขนส่งสาธารณะ",
}

TIME_OPTIONS: List[int] = [5, 10, 15, 20, 30, 45, 60]

# Cache Directory (disk-based OSM graph storage)
CACHE_DIR: Path = Path("./cache")
CACHE_DIR.mkdir(exist_ok=True)

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


@st.cache_resource(show_spinner=False)
def _process_wide_lock() -> Any:
    """One lock per server process.

    Streamlit builds a fresh ``__main__`` module for every rerun, so a module-level ``RLock()`` is a *new*
    lock each run and cannot serialise downloads across sessions; ``cache_resource`` keeps one instance alive.
    """
    return threading.RLock()


_OVERPASS_LOCK = _process_wide_lock()

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
    "show_anchor_boundary", "show_evidence_zone", "show_evidence_clusters",
    "show_space_syntax", "ss_kind", "ss_turn", "ss_radii", "ss_choice", "ss_radius_m", "ss_network",
    "ss_palette", "ss_scale", "ss_thick", "ss_topn",
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


# ----------------------------------------------------------------------------
# Space Syntax (segment analysis) — constants copied verbatim from Rent_Gradient_new.py
# ----------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parents[1]

NETWORK_TYPES: Dict[str, str] = {
    "drive": "🚗 ถนนรถ (drive)",
    "all": "🛣️ ทุกถนน (all)",
    "walk": "🚶 เดินเท้า (walk)",
    "bike": "🚲 จักรยาน (bike)",
}

MIN_RADIUS_M, MAX_RADIUS_M = 1000, 10000

BUNDLED_CACHE_ZIP = ROOT / "Geoapify_Map" / "osmnx_cache.zip"

ANALYSIS_CONFIG: Dict[str, Any] = {
    "nain_exponent": 1.2,        # NAIN = NC^1.2 / (TD + 2)
    "nain_offset": 2.0,
    "nach_offset": 3.0,          # NACH = log(CH + 1) / log(TD + 3)
    "eps_cost": 1e-9,            # ต้นทุนศูนย์ (ตรงไปตรงมา) ต้องคงเป็นเส้นเชื่อมใน sparse matrix
    "tie_break_per_m": 1e-9,     # มุมเท่ากันทุกประการ → เลือกเส้นทางที่สั้นกว่า (ไม่กระทบ TD/NAIN)
    "simplify_tolerance_m": 5.0, # Douglas–Peucker ก่อนวัดความโค้ง/ทิศปลายถนน (ตัด jitter ของ OSM)
    "metric_depth_unit_m": 100.0,  # metric depth เทียบเป็น "บล็อก" 100 ม. ก่อนใส่สูตร NAIN / NACH
    "max_exact_segments": 4000,  # Global เกินนี้ → pivot sampling (2k segment ≈ 3 s, 4k ≈ 12 s รวม Choice)
    "n_pivots": 400,
    "seed": 0,
    "max_segments": 60000,
    "top_n": 10,
    "top_min_spacing_m": 250.0,  # ไม่เลือก 2 จุดใกล้กว่านี้ (กัน segment ติดกันของถนนเส้นเดียวซ้ำ)
}

DISTANCE_KINDS: Dict[str, Dict[str, str]] = {
    "angular": {"label": "Angular (มุมเลี้ยว)",
                "help": "มุมเลี้ยวสะสม เลี้ยว 90° = 1.0 ตรงต่อ = 0 — มาตรฐานของ Segment Analysis"},
    "topological": {"label": "Topological (จำนวนก้าว)",
                    "help": "นับจำนวนครั้งที่เปลี่ยน segment (หรือเลี้ยวเกินมุมที่กำหนด) — ใกล้เคียง Axial"},
    "metric": {"label": "Metric (ระยะทาง)",
               "help": "ระยะตามถนนจริง จากกลาง segment ถึงกลาง segment"},
}

# รัศมีเป็นเมตรตามถนน; None = Global (n)
RADIUS_OPTIONS: Dict[str, Optional[float]] = {
    "400 m": 400.0,
    "800 m": 800.0,
    "1,600 m": 1600.0,
    "3,200 m": 3200.0,
    "Global (n)": None,
}

DEFAULT_RADII: List[str] = ["800 m", "Global (n)"]

MEASURES: Dict[str, Dict[str, str]] = {
    "integration": {
        "title": "Integration (NAIN)",
        "thai": "เข้าถึงได้ง่าย",
        "hint": "ช่วงถนนที่เข้าถึงได้ง่ายจากทุกจุดในรัศมี — ศูนย์กลางการเข้าถึง (to-movement)",
    },
    "choice": {
        "title": "Choice (NACH)",
        "thai": "ทางผ่าน",
        "hint": "ช่วงถนนที่เส้นทางสั้นที่สุดระหว่างทุกคู่จุดต้องผ่าน (through-movement)",
    },
}

# จุดหยุดสีเรียงจากค่าต่ำ (น้ำเงิน) ไปค่าสูง (แดง) — ทุกชุดต้องเรียงทิศนี้
PALETTES: Dict[str, List[str]] = {
    "Spectrum (น้ำเงิน→แดง แบบ depthmap)": [
        "#1f2fff", "#00b4ff", "#00f0b4", "#32e600", "#f5f500", "#ff9a00", "#ff0000",
    ],
    "RdYlBu (นุ่มตา พิมพ์ขาวดำได้ดีกว่า)": [
        "#313695", "#4575b4", "#74add1", "#abd9e9", "#e0f3f8", "#ffffbf",
        "#fee090", "#fdae61", "#f46d43", "#d73027", "#a50026",
    ],
}

DEFAULT_PALETTE = next(iter(PALETTES))

MISSING_COLOR = "#7a7a7a"

SCALE_MODES: Dict[str, str] = {
    "linear": "Linear (ต่ำสุด–สูงสุด)",
    "quantile": "Quantile (ตามลำดับเปอร์เซ็นไทล์)",
}

SS_VIEW_LABELS: Dict[str, str] = {
    "png": "🖤 Segment map",
    "stats": "📊 สถิติ & อันดับ",
    "help": "📖 หลักการ",
}

# Space Syntax results live in the session (numpy arrays — recomputed in seconds), never in the config JSON
SS_NET, SS_META, SS_RESULT, SS_RUN, SS_KEY, SS_MASK = (
    "ss_net", "ss_meta", "ss_result", "ss_run", "ss_study_key", "ss_mask")
SS_STATE_KEYS = (SS_NET, SS_META, SS_RESULT, SS_RUN, SS_KEY, SS_MASK)

# Widgets that are drawn only sometimes: Streamlit forgets the state of a widget that was not rendered, so the
# value is written back on every run (see StateManager.initialize) and survives the widget being hidden.
KEEP_ALIVE_KEYS = ("ss_turn", "ss_measure", "ss_view_radius", "ss_palette", "ss_scale", "ss_thick", "ss_topn",
                   "ss_view", "cityplan_opacity")


# ============================================================================
# SECTION 2: STATE MANAGER (Centralized Session State)
# ============================================================================

@st.cache_data(show_spinner=False, ttl=600, max_entries=1)
def _remote_payload() -> Optional[Dict[str, Any]]:
    """Saved defaults from the project JSON — fetched once per server process (not once per session)."""
    try:
        resp = requests.get(DEFAULT_CONFIG["JSON_URL"], timeout=TIMEOUT_INIT)
        if resp.status_code == 200:
            data = resp.json()
            return data if isinstance(data, dict) else None
    except Exception:
        pass
    return None


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and abs(value) < float("inf")


def _valid_samples(value: Any) -> bool:
    return isinstance(value, list) and all(
        isinstance(row, dict) and all(_is_number(row.get(k)) for k in ("lat", "lon", "rent")) for row in value)


def _valid_markers(value: Any) -> bool:
    return isinstance(value, list) and all(
        isinstance(row, dict) and _is_number(row.get("lat")) and _is_number(row.get("lng")) for row in value)


# Per-key checks for imported settings; any other key is checked against the type of its default.
_SETTING_CHECKS: Dict[str, Callable[[Any], bool]] = {
    "map_style_name": lambda v: isinstance(v, str) and v in MAP_STYLES,
    "travel_mode": lambda v: v in TRAVEL_MODE_NAMES,
    "time_intervals": lambda v: isinstance(v, list) and all(t in TIME_OPTIONS for t in v),
    "cityplan_opacity": lambda v: _is_number(v) and 0.2 <= v <= 1.0,
    "anchor_radius_km": lambda v: _is_number(v) and 4.0 <= v <= 20.0,
    "anchor_lat": lambda v: _is_number(v) and -85.0 <= v <= 85.0,
    "anchor_lon": lambda v: _is_number(v) and -180.0 <= v <= 180.0,
    "colors": lambda v: isinstance(v, dict) and all(isinstance(v.get(k), str) for k in
                                                    ("step1", "step2", "step3", "step4")),
    "rent_samples": _valid_samples,
    "ss_kind": lambda v: v in DISTANCE_KINDS,
    "ss_network": lambda v: v in NETWORK_TYPES,
    "ss_palette": lambda v: v in PALETTES,
    "ss_scale": lambda v: v in SCALE_MODES,
    "ss_radii": lambda v: isinstance(v, list) and all(label in RADIUS_OPTIONS for label in v),
    "ss_radius_m": lambda v: _is_number(v) and MIN_RADIUS_M <= v <= MAX_RADIUS_M,
    "ss_turn": lambda v: _is_number(v) and 0 <= v <= 60,
    "ss_topn": lambda v: _is_number(v) and 0 <= v <= 25,
}


def _setting_ok(key: str, value: Any) -> bool:
    """True when an imported setting has a usable type/range (a bad value must not break the whole page)."""
    check = _SETTING_CHECKS.get(key)
    if check is not None:
        try:
            return bool(check(value))
        except Exception:
            return False
    default = StateManager._DEFAULTS.get(key)
    if default is None:
        return True                       # legacy / untyped keys keep the old permissive behaviour
    if isinstance(default, bool):
        return isinstance(value, bool)
    if isinstance(default, (int, float)):
        return _is_number(value)
    if isinstance(default, (str, list, dict)):
        return isinstance(value, type(default))
    return True


class StateManager:
    """
    Centralized session-state management.

    All reads / writes to ``st.session_state`` go through this class
    so that key names are defined once and typos are caught at the
    class level instead of buried in UI code.
    """

    # ---- Key constants (single source of truth) ----
    K_MARKERS: str = "markers"
    K_ISOCHRONE: str = "isochrone_data"
    K_INTERSECTION: str = "intersection_data"
    K_NETWORK: str = "network_data"
    K_LAST_CLICK: str = "last_processed_click"
    K_COLORS: str = "colors"
    K_API_KEY: str = "api_key"
    K_MAP_STYLE: str = "map_style_name"
    K_TRAVEL_MODE: str = "travel_mode"
    K_TIME_INTERVALS: str = "time_intervals"
    K_SHOW_DOL: str = "show_dol"
    K_SHOW_CITYPLAN: str = "show_cityplan"
    K_CITYPLAN_OPACITY: str = "cityplan_opacity"
    K_SHOW_POPULATION: str = "show_population"
    K_SHOW_TRAFFIC: str = "show_traffic"
    K_SHOW_BETWEENNESS: str = "show_betweenness"
    K_SHOW_CLOSENESS: str = "show_closeness"
    K_SHOW_RAILWAY: str = "show_railway"
    K_SHOW_GOLDEN: str = "show_golden_spots"
    K_UI_LOCKED: str = "ui_locked"
    K_RENT_SAMPLES: str = "rent_samples"
    K_RENT_DATA: str = "rent_gradient_data"
    K_SHOW_RENT_RINGS: str = "show_rent_rings"
    K_SHOW_RENT_NODES: str = "show_rent_nodes"
    K_RENT_UNIT: str = "rent_unit_label"
    K_AUTO_ANCHOR: str = "automated_anchor_data"
    K_AUTO_ANCHOR_CLOSENESS: str = "automated_anchor_closeness_data"
    K_AUTO_ANCHOR_EVIDENCE: str = "automated_anchor_evidence_data"

    # ---- Default values ----
    _DEFAULTS: Dict[str, Any] = {
        K_MARKERS: None,  # Will be set from remote JSON or fallback
        K_ISOCHRONE: None,
        K_INTERSECTION: None,
        K_NETWORK: None,
        K_LAST_CLICK: None,
        K_COLORS: {
            "step1": "#2A9D8F",
            "step2": "#E9C46A",
            "step3": "#F4A261",
            "step4": "#D62828",
        },
        K_API_KEY: DEFAULT_CONFIG["GEOAPIFY_KEY"],
        K_MAP_STYLE: "Esri Light Gray (แนะนำสำหรับดูผังเมือง)",
        K_TRAVEL_MODE: "drive",
        K_TIME_INTERVALS: [5],
        K_SHOW_DOL: False,
        K_SHOW_CITYPLAN: False,
        K_CITYPLAN_OPACITY: 0.7,
        K_SHOW_POPULATION: False,
        K_SHOW_TRAFFIC: False,
        K_SHOW_BETWEENNESS: False,
        K_SHOW_CLOSENESS: False,
        K_SHOW_RAILWAY: False,
        K_SHOW_GOLDEN: True,
        K_UI_LOCKED: False,
        K_RENT_SAMPLES: [],
        K_RENT_DATA: None,
        K_SHOW_RENT_RINGS: True,
        K_SHOW_RENT_NODES: False,
        K_RENT_UNIT: "บาท/ตร.ว./เดือน",
        K_AUTO_ANCHOR: None,
        K_AUTO_ANCHOR_CLOSENESS: None,
        K_AUTO_ANCHOR_EVIDENCE: None,
        # layer checkboxes that had no checkbox before (they were hidden entries of the map's LayerControl)
        "show_anchor_boundary": False,
        "show_evidence_zone": False,
        "show_evidence_clusters": False,
        "anchor_use_evidence": False,         # opt-in until real WMS fixtures calibrate the thresholds
        "rent_use_evidence_anchor": False,    # Rent keeps the composite anchor unless ticked
        "anchor_lat": DEFAULT_CONFIG["LAT"],
        "anchor_lon": DEFAULT_CONFIG["LON"],
        "anchor_radius_km": 10.0,
        # Space Syntax: analysis settings and display options are saved with the config; results stay in the session
        "show_space_syntax": True,
        "ss_kind": "angular",
        "ss_turn": 0,
        "ss_radii": list(DEFAULT_RADII),
        "ss_choice": True,
        "ss_radius_m": 3000,
        "ss_network": "drive",
        "ss_palette": DEFAULT_PALETTE,
        "ss_scale": "linear",
        "ss_thick": True,
        "ss_topn": ANALYSIS_CONFIG["top_n"],
        "ss_view": "stats",
    }

    _DEFAULT_MARKER: Dict[str, Any] = {
        "lat": DEFAULT_CONFIG["LAT"],
        "lng": DEFAULT_CONFIG["LON"],
        "active": True,
    }

    # ------------------------------------------------------------------ init
    @classmethod
    def initialize(cls) -> None:
        """Initialize all session-state variables with defaults.

        On first load, attempts to pull saved state from a remote JSON.
        Subsequent reruns are no-ops for keys that already exist.
        """
        first_run = cls.K_MARKERS not in st.session_state

        # Resolve starting defaults (possibly from remote)
        defaults = dict(cls._DEFAULTS)
        if first_run:
            defaults[cls.K_MARKERS] = cls._load_remote_defaults(defaults)

        # Fallback marker list
        if defaults[cls.K_MARKERS] is None:
            defaults[cls.K_MARKERS] = [dict(cls._DEFAULT_MARKER)]

        # Apply defaults using setdefault (idempotent)
        for key, value in defaults.items():
            st.session_state.setdefault(key, value)

        # A widget that is not drawn in a run loses its state; writing the value back keeps it for later.
        for key in KEEP_ALIVE_KEYS:
            if key in st.session_state:
                st.session_state[key] = st.session_state[key]

        # Ensure every marker dict has an 'active' key
        for m in st.session_state[cls.K_MARKERS]:
            m.setdefault("active", True)

    @staticmethod
    def _load_remote_defaults(defaults: Dict[str, Any]) -> Optional[List[Dict]]:
        """Merge the (cached) remote JSON into ``defaults``; returns its markers or ``None``."""
        data = _remote_payload()
        if not data:
            return None
        # Merge remote settings into defaults
        for k in defaults:
            if k in data:
                defaults[k] = data[k]
        return data.get("markers")

    # ------------------------------------------------------------- accessors
    @classmethod
    def get_markers(cls) -> List[Dict[str, Any]]:
        return st.session_state[cls.K_MARKERS]

    @classmethod
    def get_active_markers(cls) -> List[Tuple[int, Dict[str, Any]]]:
        """Return list of (original_index, marker_dict) for active markers."""
        return [
            (i, m)
            for i, m in enumerate(st.session_state[cls.K_MARKERS])
            if m.get("active", True)
        ]

    @classmethod
    def get_isochrone_data(cls) -> Optional[Dict[str, Any]]:
        return st.session_state[cls.K_ISOCHRONE]

    @classmethod
    def get_intersection_data(cls) -> Optional[Dict[str, Any]]:
        return st.session_state[cls.K_INTERSECTION]

    @classmethod
    def get_network_data(cls) -> Optional[Dict[str, Any]]:
        return st.session_state[cls.K_NETWORK]

    @classmethod
    def get_colors(cls) -> Dict[str, str]:
        return st.session_state[cls.K_COLORS]

    @classmethod
    def get_api_key(cls) -> str:
        return st.session_state[cls.K_API_KEY]

    @classmethod
    def get_travel_mode(cls) -> str:
        return st.session_state[cls.K_TRAVEL_MODE]

    @classmethod
    def get_time_intervals(cls) -> List[int]:
        return st.session_state[cls.K_TIME_INTERVALS]

    @classmethod
    def get_map_style_name(cls) -> str:
        return st.session_state[cls.K_MAP_STYLE]

    @classmethod
    def get_rent_samples(cls) -> List[Dict[str, Any]]:
        return st.session_state[cls.K_RENT_SAMPLES]

    @classmethod
    def set_rent_samples(cls, samples: List[Dict[str, Any]]) -> None:
        st.session_state[cls.K_RENT_SAMPLES] = samples

    @classmethod
    def get_rent_data(cls) -> Optional[Dict[str, Any]]:
        return st.session_state[cls.K_RENT_DATA]

    @classmethod
    def set_rent_data(cls, data: Optional[Dict[str, Any]]) -> None:
        st.session_state[cls.K_RENT_DATA] = data

    @classmethod
    def get_rent_unit(cls) -> str:
        return st.session_state[cls.K_RENT_UNIT]

    # -------------------------------------------------------------- mutators
    @classmethod
    def set_isochrone_data(cls, data: Optional[Dict[str, Any]]) -> None:
        st.session_state[cls.K_ISOCHRONE] = data

    @classmethod
    def set_intersection_data(cls, data: Optional[Dict[str, Any]]) -> None:
        st.session_state[cls.K_INTERSECTION] = data

    @classmethod
    def set_network_data(cls, data: Optional[Dict[str, Any]]) -> None:
        st.session_state[cls.K_NETWORK] = data

    @classmethod
    def add_marker(cls, lat: float, lng: float) -> None:
        st.session_state[cls.K_MARKERS].append(
            {"lat": lat, "lng": lng, "active": True}
        )

    @classmethod
    def remove_marker(cls, index: int) -> None:
        markers = st.session_state[cls.K_MARKERS]
        if 0 <= index < len(markers):
            markers.pop(index)

    @classmethod
    def pop_last_marker(cls) -> None:
        markers = st.session_state[cls.K_MARKERS]
        if markers:
            markers.pop()

    @classmethod
    def set_marker_active(cls, index: int, active: bool) -> None:
        st.session_state[cls.K_MARKERS][index]["active"] = active

    @classmethod
    def record_click(cls, lat: float, lon: float) -> None:
        st.session_state[cls.K_LAST_CLICK] = {
            "timestamp": time.time(),
            "lat": lat,
            "lon": lon,
        }

    @classmethod
    def get_last_click(cls) -> Optional[Dict[str, Any]]:
        return st.session_state.get(cls.K_LAST_CLICK)

    # ------------------------------------------------------- cache clearing
    @classmethod
    def clear_results(cls, layers: Optional[List[str]] = None) -> None:
        """
        Smart cache invalidation — clear only specified layers.

        Args:
            layers: ``['isochrone', 'intersection', 'network', 'rent']``.
                    ``None`` clears all.
        """
        if layers is None:
            layers = ["isochrone", "intersection", "network", "rent", "anchor", "anchor_closeness",
                      "anchor_evidence", "space_syntax"]

        if "anchor" in layers:
            st.session_state[cls.K_AUTO_ANCHOR] = None
            st.session_state[cls.K_AUTO_ANCHOR_EVIDENCE] = None  # it confirms this road result
            st.session_state[cls.K_RENT_DATA] = None
        if "anchor_evidence" in layers:
            st.session_state[cls.K_AUTO_ANCHOR_EVIDENCE] = None
        if "anchor_closeness" in layers:
            st.session_state[cls.K_AUTO_ANCHOR_CLOSENESS] = None

        if "isochrone" in layers:
            st.session_state[cls.K_ISOCHRONE] = None
        if "intersection" in layers:
            st.session_state[cls.K_INTERSECTION] = None
        if "network" in layers:
            st.session_state[cls.K_NETWORK] = None
        if "rent" in layers:
            st.session_state[cls.K_RENT_DATA] = None
        if "space_syntax" in layers:
            for key in SS_STATE_KEYS:
                st.session_state.pop(key, None)

    @classmethod
    def reset(cls) -> None:
        """Reset to factory defaults."""
        st.session_state[cls.K_MARKERS] = [dict(cls._DEFAULT_MARKER)]
        st.session_state[cls.K_LAST_CLICK] = None
        cls.clear_results()

    @classmethod
    def import_config(cls, data: Dict[str, Any]) -> List[str]:
        """Import settings + optional precomputed outputs from config.

        Values with the wrong type/range are skipped instead of breaking the page; their names are returned
        and kept in ``_import_skipped`` so the UI can say what was ignored.
        """
        skipped: List[str] = []
        if "markers" in data:
            if _valid_markers(data["markers"]):
                st.session_state[cls.K_MARKERS] = data["markers"]
            else:
                skipped.append("markers")

        settings = data.get("settings", {})
        for k, v in settings.items():
            if k in SESSION_KEYS_TO_SAVE:
                if _setting_ok(k, v):
                    st.session_state[k] = v
                else:
                    skipped.append(k)

        # The combined coordinate widget is UI-only. Keep it synchronized with
        # the legacy anchor_lat / anchor_lon keys used by saved configurations.
        if "anchor_lat" in settings or "anchor_lon" in settings:
            st.session_state["anchor_center_input"] = (
                f"{float(st.session_state['anchor_lat'])!r}, "
                f"{float(st.session_state['anchor_lon'])!r}"
            )

        # Start from a clean slate so keys absent from the payload
        # don't keep stale results anchored to the previous CBD.
        cls.clear_results()

        precomputed_results = data.get("precomputed_results", {})
        for result_key in RESULT_KEYS_TO_SAVE:
            if result_key in precomputed_results:
                if precomputed_results[result_key] is None or isinstance(precomputed_results[result_key], dict):
                    st.session_state[result_key] = precomputed_results[result_key]
                else:
                    skipped.append(result_key)

        # Backward compatibility: allow old flat structure.
        for result_key in RESULT_KEYS_TO_SAVE:
            if result_key in data:
                if data[result_key] is None or isinstance(data[result_key], dict):
                    st.session_state[result_key] = data[result_key]
                else:
                    skipped.append(result_key)

        st.session_state["_import_skipped"] = skipped
        return skipped

    @classmethod
    def export_config(cls) -> str:
        """Export config and currently computed outputs as a JSON string."""
        return json.dumps(
            {
                "format_version": 2,
                "markers": st.session_state[cls.K_MARKERS],
                "settings": {
                    k: st.session_state[k]
                    for k in SESSION_KEYS_TO_SAVE
                    if k in st.session_state
                },
                "precomputed_results": {
                    k: st.session_state.get(k)
                    for k in RESULT_KEYS_TO_SAVE
                },
            },
            indent=2,
            ensure_ascii=False,
        )


# ============================================================================
# SECTION 3: PURE FUNCTIONS (No st.* — testable, cacheable)
# ============================================================================

# --------------------------------------------------------------------- Geometry
def _anchor_projection(lat: float, lon: float) -> Transformer:
    """Local azimuthal equidistant coordinates in metres."""
    if not (-85 <= lat <= 85 and -180 <= lon <= 180):
        raise ValueError("Study centre requires latitude ±85° and longitude ±180°.")
    local = CRS.from_proj4(
        f"+proj=aeqd +lat_0={lat} +lon_0={lon} +datum=WGS84 +units=m"
    )
    return Transformer.from_crs("EPSG:4326", local, always_xy=True)


def anchor_study_polygon(lat: float, lon: float, radius_m: float):
    """Download footprint with 20% buffer, independent of seed and isochrones."""
    from shapely.geometry import Point
    from shapely.ops import transform
    from pyproj.enums import TransformDirection

    if not 1000 <= radius_m <= 20000:
        raise ValueError("Study radius must be between 1 and 20 km.")
    projection = _anchor_projection(lat, lon)
    polygon = transform(
        lambda x, y: projection.transform(x, y, direction=TransformDirection.INVERSE),
        Point(0, 0).buffer(radius_m * (1 + ANCHOR_CONFIG["buffer_ratio"]), quad_segs=64),
    )
    if not polygon.is_valid or polygon.bounds[2] - polygon.bounds[0] > 180:
        raise ValueError("Study areas crossing the antimeridian are not supported.")
    return polygon


def _node_sort_key(node: Any) -> Tuple[str, str]:
    """Type-aware ordering so ties never depend on graph insertion order."""
    return (type(node).__name__, str(node))


def _collapsed_csr(
    graph: nx.Graph, nodes: List[Any], default_length: Optional[float] = None
) -> "csr_matrix":
    """Symmetric CSR of the shortest road length between each pair of ``nodes``.

    Parallel and opposite-direction edges collapse to their minimum length and
    self loops are dropped. Pure numpy after one pass over the edges; this is the
    one road-matrix builder shared by the anchor search and network analysis.
    """
    index = {node: i for i, node in enumerate(nodes)}
    us: List[int] = []
    vs: List[int] = []
    raw: List[Any] = []
    for u, v, length in graph.edges(data="length", default=default_length):
        if u == v or u not in index or v not in index:
            continue
        us.append(index[u])
        vs.append(index[v])
        raw.append(length)
    if any(length is None for length in raw):
        raise ValueError("Every road edge must have length in metres.")
    try:
        lengths = np.asarray(raw, dtype=float)
    except (TypeError, ValueError) as exc:
        raise ValueError("Every road edge must have length in metres.") from exc
    if len(lengths) and (not np.isfinite(lengths).all() or (lengths <= 0).any()):
        raise ValueError("Road lengths must be finite and positive.")
    n = len(nodes)
    if not len(lengths):
        return csr_matrix((n, n), dtype=float)
    a = np.asarray(us, dtype=np.int64)
    b = np.asarray(vs, dtype=np.int64)
    lo, hi = np.minimum(a, b), np.maximum(a, b)
    pair = lo * n + hi
    order = np.lexsort((lengths, pair))  # by pair, then shortest length first
    pair_sorted = pair[order]
    first = np.concatenate(([True], pair_sorted[1:] != pair_sorted[:-1]))
    keep = order[first]
    rows = np.concatenate((lo[keep], hi[keep]))
    cols = np.concatenate((hi[keep], lo[keep]))
    vals = np.concatenate((lengths[keep], lengths[keep]))
    return csr_matrix((vals, (rows, cols)), shape=(n, n))


def _dijkstra_batches(matrix: "csr_matrix", sources: Any):
    """Yield ``(sources_in_batch, rows)`` with at most ``batch_size`` exact rows at once.

    Never materialises an all-pairs matrix: memory stays O(batch_size * V).
    """
    size = ANCHOR_CONFIG["batch_size"]
    for start in range(0, len(sources), size):
        part = sources[start:start + size]
        yield part, csgraph_dijkstra(matrix, directed=False, indices=part)


def _road_network(graph: nx.Graph) -> Dict[str, Any]:
    """Largest undirected road component as a CSR matrix plus WGS84 coordinates."""
    all_nodes = sorted(graph.nodes, key=_node_sort_key)
    full = _collapsed_csr(graph, all_nodes)
    n_components, labels = csgraph_components(full, directed=False)
    sizes = np.bincount(labels, minlength=n_components)
    first_index = np.full(n_components, len(all_nodes))
    np.minimum.at(first_index, labels, np.arange(len(all_nodes)))
    biggest = np.flatnonzero(sizes == sizes.max())
    component = biggest[np.argmin(first_index[biggest])]  # ties: lowest sorted node
    keep = np.flatnonzero(labels == component)
    nodes = [all_nodes[i] for i in keep]
    if len(nodes) < 2:
        raise ValueError("No connected roads available in the study area.")
    try:
        lonlat = np.array([(float(graph.nodes[n]["x"]), float(graph.nodes[n]["y"]))
                           for n in nodes])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("Every road node requires WGS84 x/y coordinates.") from exc
    return {"nodes": nodes, "matrix": full[keep][:, keep].tocsr(), "lonlat": lonlat,
            "components": int(n_components), "total_nodes": len(all_nodes)}


def _stability_cases(study_radius_m: float) -> List[Dict[str, Any]]:
    """Perturbed study circles: rescaled radius, and centre shifted N/E/S/W."""
    shift = ANCHOR_CONFIG["stability_shift"] * study_radius_m
    cases: List[Dict[str, Any]] = [
        {"case": f"radius x{scale:g}", "dx": 0.0, "dy": 0.0, "radius": study_radius_m * scale}
        for scale in ANCHOR_CONFIG["stability_scales"]
    ]
    for name, (ux, uy) in (("N", (0, 1)), ("E", (1, 0)), ("S", (0, -1)), ("W", (-1, 0))):
        cases.append({"case": f"centre {ANCHOR_CONFIG['stability_shift']:.0%} {name}",
                      "dx": ux * shift, "dy": uy * shift, "radius": study_radius_m})
    return cases


def find_cbd_anchors(
    graph: nx.MultiDiGraph,
    study_center: Tuple[float, float],
    study_radius_m: float = 10000.0,
    final_radius_m: float = 150.0,
    max_rows: Optional[int] = None,
    stability: bool = True,
) -> Dict[str, Any]:
    """Composite and Closeness-100% anchors from one road graph, without I/O.

    Deterministic: no seed, no restarts. Exact length-weighted SciPy Dijkstra on
    the largest undirected component (street accessibility, not one-way routing);
    parallel and reverse edges use the minimum length. Destinations and anchors
    lie inside the study circle; paths may use buffer nodes. Junctions have >=3
    distinct neighbours; density counts them within 500 metric metres.

    Both objectives share one distance pass, so each exact row (closeness) is
    computed once:

    * composite - junction candidates (all inside nodes only if none exist),
      Score = .5*C_rank + .3*degree_rank + .2*density_rank with degree/density
      as mid-rank percentiles over the candidate pool and C_rank = Phi((C -
      mean)/std) from the exact closeness of a fixed reference sample.
    * closeness - every inside node is a candidate, Score = C/(C + 1/R), strictly
      monotone in C, hence the raw length-weighted 1-median.

    Each objective is exhaustive when its candidate pool fits ``rows_budget``
    (``max_rows`` or ``max_row_nodes // V`` clamped): the global maximum of the
    fixed objective is then certified. Otherwise every candidate is ranked with
    the reference sample's distances (Eppstein-Wang pivots), the top-K are scored
    exactly and a local exhaustive climb (``final_radius_m``) polishes the best:
    seed-independent and stable, but not a global certificate. Neither proves an
    economic CBD.

    ``stability`` adds an *indicative* probe at almost no cost: the pivot rows are
    also summed per perturbed circle (radius x0.8/x1.2, centre shifted 20% of the
    radius N/E/S/W), the best few candidates of each case are scored exactly on
    that case's destinations, and the drift of the best one from the anchor is
    reported with a stable / check / unstable level. The exact oracle is
    ``scripts/anchor_sensitivity.py``.
    """
    if not HAS_SCIPY:
        raise RuntimeError("Automated CBD search requires SciPy and NumPy.")
    from scipy.spatial import cKDTree
    from scipy.special import ndtr

    started = time.perf_counter()
    anchor_study_polygon(*study_center, study_radius_m)
    if not 0 < final_radius_m <= study_radius_m:
        raise ValueError("Require 0 < final radius <= study radius.")
    if max_rows is not None and not 1 <= max_rows <= 10000:
        raise ValueError("Invalid row budget.")
    if not 2 <= len(graph) <= ANCHOR_CONFIG["max_nodes"]:
        raise ValueError("Road graph must contain 2–100,000 nodes; reduce the study area.")
    if CRS.from_user_input(graph.graph.get("crs", "EPSG:4326")) != CRS.from_epsg(4326):
        raise ValueError("Road graph must use WGS84 longitude/latitude (EPSG:4326).")

    net = _road_network(graph)
    nodes, matrix, lonlat = net["nodes"], net["matrix"], net["lonlat"]
    n = len(nodes)
    if (not np.isfinite(lonlat).all() or (np.abs(lonlat[:, 0]) > 180).any()
            or (np.abs(lonlat[:, 1]) > 90).any()):
        raise ValueError("Invalid road node coordinates.")
    projection = _anchor_projection(*study_center)
    xy = np.column_stack(projection.transform(lonlat[:, 0], lonlat[:, 1]))
    radial_distance = np.linalg.norm(xy, axis=1)
    eligible = np.flatnonzero(radial_distance <= study_radius_m)
    if len(eligible) < 2:
        raise ValueError("Fewer than two connected road nodes inside the study circle.")
    prep_done = time.perf_counter()

    degrees = np.diff(matrix.indptr).astype(float)  # distinct neighbours (no parallels)
    junctions = np.flatnonzero(degrees >= 3)
    composite_pool = eligible[degrees[eligible] >= 3]
    junction_fallback = len(composite_pool) == 0
    if junction_fallback:
        composite_pool = eligible
    pools = {"composite": composite_pool, "closeness": eligible}
    density = np.zeros(n)
    density_nodes = np.arange(n) if stability else eligible  # perturbed circles reach outside
    if len(junctions):
        # Inclusive radius with a sub-micrometre tolerance: lattice points that sit
        # exactly on the circle land at 500 ± 1e-9 m after the CRS round trip, so a
        # bare "<= 500" would depend on pyproj/libm rounding rather than geometry.
        density[density_nodes] = cKDTree(xy[junctions]).query_ball_point(
            xy[density_nodes], ANCHOR_CONFIG["density_radius_m"] + 1e-6, return_length=True)
    # Diagnostics (and the Closeness-100% record): share of the inside maximum.
    degree_norm = degrees / max(float(degrees[eligible].max()), 1.0)
    density_norm = density / max(float(density[eligible].max()), 1.0)

    def midrank(values, pool_nodes):
        """Mid-rank percentile of each value within ``pool_nodes``, in (0, 1)."""
        pool = np.sort(values[pool_nodes])
        return (np.searchsorted(pool, values, side="left")
                + np.searchsorted(pool, values, side="right")) / (2.0 * len(pool))

    degree_rank = midrank(degrees, composite_pool)
    density_rank = midrank(density, composite_pool)
    weights = {"closeness": 0.50, "degree": 0.30, "density": 0.20}
    n_destinations = len(eligible)
    rows_budget = int(max_rows) if max_rows else int(np.clip(
        ANCHOR_CONFIG["max_row_nodes"] // n, ANCHOR_CONFIG["min_rows"], ANCHOR_CONFIG["max_rows"]))

    # Fixed reference sample of destinations (constant seed): exact closeness
    # calibrates the composite normaliser and the summed distance rows rank every
    # candidate by pivot closeness. Its rows are shared, never recomputed.
    # The sample size is a property of the graph, not of the run: it fixes the composite
    # normaliser, so it must not move with ``max_rows`` or the objective would change
    # between a certified run and a screened one. Huge graphs use fewer pivots (their
    # rows cost the most) — at 100k nodes that is ~half of the previous pivot time.
    ref_target = float(ANCHOR_CONFIG["reference_nodes"])
    if n > ANCHOR_CONFIG["reference_shrink_above_nodes"]:
        ref_target = max(float(ANCHOR_CONFIG["reference_min_nodes"]),
                         ref_target * (ANCHOR_CONFIG["reference_shrink_above_nodes"] / n) ** 0.5)
    n_ref = min(n_destinations, int(round(ref_target)))
    ref_nodes = np.sort(np.random.default_rng(ANCHOR_CONFIG["reference_seed"]).choice(
        eligible, size=n_ref, replace=False))
    ref_c = np.empty(n_ref)
    pivot_sum = np.zeros(n)
    cases = _stability_cases(study_radius_m) if stability else []
    case_inside = np.zeros((n, len(cases)), dtype=bool)
    for k, case in enumerate(cases):
        case_inside[:, k] = np.hypot(xy[:, 0] - case["dx"], xy[:, 1] - case["dy"]) <= case["radius"]
    case_float = case_inside.astype(float)
    # Two strata of destinations for the perturbed circles: the base circle (the pivots
    # above) and the ring just outside it, which a x1.2 or shifted circle pulls in. Sampling
    # only the base circle would leave mass outside it invisible to the probe.
    outer_pool = (np.flatnonzero((radial_distance > study_radius_m) & case_inside.any(axis=1))
                  if cases else np.empty(0, dtype=int))
    n_out = min(len(outer_pool), int(ANCHOR_CONFIG["stability_outer_nodes"]))
    out_nodes = (np.sort(np.random.default_rng(ANCHOR_CONFIG["reference_seed"] + 1).choice(
        outer_pool, size=n_out, replace=False)) if n_out else np.empty(0, dtype=int))
    sources = np.concatenate((ref_nodes, out_nodes)).astype(int)
    case_pivot_sum = np.zeros((n, len(cases)))   # S1: sum over base pivots inside each circle
    case_outer_sum = np.zeros((n, len(cases)))   # S2: same over ring pivots
    case_ref_sum = np.zeros((len(sources), len(cases)))
    # Distances from each exact row to every case's destinations: a by-product of
    # the base pass, so the probe re-runs Dijkstra only for rows it has not seen.
    case_sums: Dict[int, np.ndarray] = {}
    filled = 0
    for part, rows_d in _dijkstra_batches(matrix, sources):
        position = np.arange(filled, filled + len(part))
        is_base = position < n_ref
        if is_base.any():
            ref_c[position[is_base]] = (n_destinations - 1) / rows_d[is_base][:, eligible].sum(axis=1)
            pivot_sum += rows_d[is_base].sum(axis=0)
        if cases:  # per-case sums over the pivots that fall inside each perturbed circle
            if is_base.any():
                case_pivot_sum += rows_d[is_base].T @ case_float[part[is_base]]
            if (~is_base).any():
                case_outer_sum += rows_d[~is_base].T @ case_float[part[~is_base]]
            chunk = rows_d @ case_float
            case_ref_sum[position] = chunk
            case_sums.update((int(i), row) for i, row in zip(part, chunk))
        filled += len(part)
    ref_mean, ref_std = float(ref_c.mean()), float(ref_c.std())

    # Stratified (Horvitz-Thompson) estimate of the summed distance to each case's
    # destinations: sum_u d(v,u) ~ (n1/k1) S1 + (n2/k2) S2, with n_j the nodes of stratum
    # j inside the circle and k_j the pivots of that stratum inside it.
    case_sum_hat = np.zeros((n, len(cases)))
    case_norm = []
    for k in range(len(cases)):
        n1c = int(case_inside[eligible, k].sum())
        n2c = int(case_inside[outer_pool, k].sum()) if len(outer_pool) else 0
        k1c = int(case_inside[ref_nodes, k].sum())
        k2c = int(case_inside[out_nodes, k].sum()) if n_out else 0
        w1 = n1c / k1c if k1c else 0.0
        w2 = n2c / k2c if k2c else 0.0
        if n2c and not k2c and k1c:       # no ring pivot inside: borrow the base mean distance
            w2 = n2c / k1c
            case_sum_hat[:, k] = w1 * case_pivot_sum[:, k] + w2 * case_pivot_sum[:, k]
        elif n1c and not k1c and k2c:
            w1 = n1c / k2c
            case_sum_hat[:, k] = w1 * case_outer_sum[:, k] + w2 * case_outer_sum[:, k]
        else:
            case_sum_hat[:, k] = w1 * case_pivot_sum[:, k] + w2 * case_outer_sum[:, k]
        # Per-case normaliser: exact closeness of the pivots inside the circle, weighted by
        # how many destinations each one represents.
        members = np.concatenate((ref_nodes[case_inside[ref_nodes, k]], out_nodes[case_inside[out_nodes, k]]))
        weights_k = np.concatenate((np.full(k1c, w1), np.full(k2c, w2)))
        pos_k = np.concatenate((np.flatnonzero(case_inside[ref_nodes, k]),
                                n_ref + np.flatnonzero(case_inside[out_nodes, k]))) if len(members) else np.empty(0, int)
        if len(members) > 1 and weights_k.sum() > 0:
            c_k = (n1c + n2c - 1) / np.maximum(case_ref_sum[pos_k, k], 1e-9)
            mu = float(np.average(c_k, weights=weights_k))
            var = float(np.average((c_k - mu) ** 2, weights=weights_k))
            case_norm.append((mu, var ** 0.5))
        else:
            case_norm.append((ref_mean, ref_std))
    exact_c: Dict[int, float] = {int(p): float(c) for p, c in zip(ref_nodes, ref_c)}
    pivots_done = time.perf_counter()

    def ensure_exact(candidates):
        """Exact closeness for every candidate lacking it (one shared row each)."""
        missing = [int(i) for i in candidates if int(i) not in exact_c]
        for part, rows_d in _dijkstra_batches(matrix, missing):
            for i, c in zip(part, (n_destinations - 1) / rows_d[:, eligible].sum(axis=1)):
                exact_c[int(i)] = float(c)
            if cases:
                case_sums.update((int(i), row) for i, row in zip(part, rows_d @ case_float))
        return len(missing)

    def closeness_component(c, objective, norm=None):
        """Closeness mapped onto 0..1 (scalar or array), fixed for the whole search."""
        if objective == "closeness":
            return c / (c + 1.0 / study_radius_m)
        mean, std = norm if norm is not None else (ref_mean, ref_std)
        if std <= 0:
            return np.full_like(np.asarray(c, dtype=float), 0.5)
        return ndtr((c - mean) / std)

    def components(i, objective):
        c = exact_c[i]
        cn = float(closeness_component(c, objective))
        if objective == "closeness":
            dn, jn = float(degree_norm[i]), float(density_norm[i])
            score = cn
        else:
            dn, jn = float(degree_rank[i]), float(density_rank[i])
            score = (weights["closeness"] * cn
                     + weights["degree"] * dn + weights["density"] * jn)
        return {"score": float(score), "closeness": float(c), "closeness_norm": cn,
                "degree_norm": dn, "density_norm": jn,
                "degree": int(degrees[i]), "junction_count": int(density[i])}

    def best_of(candidates, objective):
        # Scores are quantised so mathematically tied nodes stay tied whatever the
        # summation order or library version; the lowest node index then wins.
        return max((int(i) for i in candidates),
                   key=lambda i: (round(components(i, objective)["score"], 12), -i))

    def probe(objective, base_winner):
        """Indicative drift of the anchor under rescaled / shifted study circles."""
        # Candidates are every junction (all nodes for Closeness 100%) inside each
        # perturbed circle, not just those of the base circle: a x1.2 or shifted circle
        # can have its best node outside the base one.
        pool = (np.flatnonzero(degrees >= 3)
                if objective == "composite" and not junction_fallback else np.arange(n))
        picks: List[np.ndarray] = []
        case_ranks: List[Tuple[np.ndarray, np.ndarray]] = []
        for k in range(len(cases)):
            inside = case_inside[pool, k]
            cand = pool[inside]
            if objective == "composite" and len(cand):
                # degree/density percentiles are re-taken inside each perturbed circle
                case_ranks.append((midrank(degrees, cand), midrank(density, cand)))
            else:
                case_ranks.append((degree_rank, density_rank))
            if not len(cand):
                picks.append(cand)
                continue
            n_case = int(case_inside[:, k].sum())
            approx_c = (n_case - 1) / np.maximum(case_sum_hat[cand, k], 1e-9)
            if objective == "closeness":
                approx = approx_c
            else:
                approx = (weights["closeness"] * closeness_component(approx_c, objective, case_norm[k])
                          + weights["degree"] * case_ranks[k][0][cand]
                          + weights["density"] * case_ranks[k][1][cand])
            order = np.lexsort((cand, -approx))
            picks.append(cand[order[:int(ANCHOR_CONFIG["stability_top_m"])]])
        needed = sorted({int(i) for pick in picks for i in pick} - case_sums.keys())
        for part, rows_d in _dijkstra_batches(matrix, needed):
            case_sums.update((int(i), row) for i, row in zip(part, rows_d @ case_float))
        reach_limit = float(radial_distance.max())
        out = []
        for k, case in enumerate(cases):
            n_dest = int(case_inside[:, k].sum())
            best, best_key = None, None
            for i in picks[k]:
                i = int(i)
                c = (n_dest - 1) / case_sums[i][k] if case_sums[i][k] > 0 else 0.0
                if objective == "closeness":
                    score = c
                else:
                    score = (weights["closeness"] * float(closeness_component(c, objective, case_norm[k]))
                             + weights["degree"] * float(case_ranks[k][0][i])
                             + weights["density"] * float(case_ranks[k][1][i]))
                if best_key is None or (round(score, 12), -i) > best_key:
                    best, best_key = i, (round(score, 12), -i)
            if best is None:
                out.append({"case": case["case"], "drift_m": None, "node_id": None})
                continue
            drift = calculate_distance_meters(
                lonlat[base_winner, 1], lonlat[base_winner, 0], lonlat[best, 1], lonlat[best, 0])
            out.append({"case": case["case"], "drift_m": float(drift), "node_id": str(nodes[best]),
                        "lat": float(lonlat[best, 1]), "lon": float(lonlat[best, 0]),
                        "covered": bool(np.hypot(case["dx"], case["dy"]) + case["radius"] <= reach_limit)})
        drifts = [c["drift_m"] for c in out if c["drift_m"] is not None]
        if not drifts:
            return None
        worst = max(drifts)
        ratio = worst / study_radius_m
        level = ("stable" if ratio <= ANCHOR_CONFIG["stability_ok_ratio"]
                 else "check" if ratio <= ANCHOR_CONFIG["stability_warn_ratio"] else "unstable")
        return {"method": "pivot-screen + exact top-M per case (per-case pivot normaliser)",
                "indicative": True, "cases": out, "max_drift_m": float(worst),
                "median_drift_m": float(np.median(drifts)), "max_drift_ratio": float(ratio),
                "level": level}

    def solve(objective):
        """Exhaustive when the pool fits the row budget, else screen + refine."""
        pool = pools[objective]
        screening = None
        if len(pool) <= rows_budget:
            ensure_exact(pool)
            winner = best_of(pool, objective)
            certified, refined = True, True
        else:
            k_eff = n_ref - np.isin(pool, ref_nodes).astype(float)  # a pivot skips d(p,p)=0
            approx_c = k_eff / np.maximum(pivot_sum[pool], 1e-9)
            if objective == "closeness":
                approx_score = approx_c
            else:
                approx_score = (weights["closeness"] * closeness_component(approx_c, objective)
                                + weights["degree"] * degree_rank[pool]
                                + weights["density"] * density_rank[pool])
            top_k = min(int(ANCHOR_CONFIG["screen_top_k"]), rows_budget)
            order = np.lexsort((pool, -approx_score))  # score desc, node index asc
            chosen = [int(pool[j]) for j in order[:top_k]]
            extra = ensure_exact(chosen)
            tree = cKDTree(xy[pool])
            pool_set = set(pool.tolist())
            # every pool node that already has an exact row competes (pivots, and the
            # other objective's exhaustive pass), not only this objective's own picks
            scored = [i for i in exact_c if i in pool_set]
            current = best_of(scored, objective)
            refined = False
            for _ in range(int(ANCHOR_CONFIG["refine_iterations"])):
                around = [current] + [int(pool[j]) for j in
                                      tree.query_ball_point(xy[current], final_radius_m)]
                fresh = len([i for i in around if i not in exact_c])
                if extra + fresh > rows_budget:
                    break
                extra += ensure_exact(around)
                best = best_of(around, objective)
                if components(best, objective)["score"] > components(current, objective)["score"] + 1e-12:
                    current = best
                else:
                    refined = True
                    break
            winner, certified = current, False
            screening = {"pivots": n_ref, "screened_top_k": len(chosen),
                         "extra_rows": extra, "refine_converged": refined}

        anchor = dict(
            {"node_id": str(nodes[winner]), "lat": float(lonlat[winner, 1]),
             "lon": float(lonlat[winner, 0]), **components(winner, objective)},
            source=("Automated CBD Anchor — Closeness 100%"
                    if objective == "closeness" else "Automated CBD Anchor"),
        )
        warnings = []
        if not certified:
            warnings.append(
                f"กราฟเกินงบตรวจครบทุกโหนด: คัดผู้สมัครด้วย pivot closeness ({screening['pivots']} จุด) "
                f"แล้วประเมินแม่นยำ {screening['screened_top_k']} อันดับแรกและไต่ต่อเฉพาะที่ — "
                "เสถียร (ไม่ขึ้นกับ seed) แต่ไม่รับรอง global optimum")
        if net["components"] > 1:
            warnings.append(f"ใช้ component ใหญ่ที่สุด; ตัด {net['total_nodes'] - n} โหนดที่ไม่เชื่อมต่อ")
        boundary_margin = float(study_radius_m - radial_distance[winner])
        if boundary_margin < ANCHOR_CONFIG["boundary_warn_ratio"] * study_radius_m:
            warnings.append("Anchor ใกล้ขอบพื้นที่ศึกษา: ควรขยายพื้นที่แล้วเปรียบเทียบผล")
        if objective == "composite" and junction_fallback:
            warnings.append("ไม่พบทางแยกในพื้นที่ศึกษา: ใช้โหนดถนนทั่วไปเป็นผู้สมัคร Anchor แทน")

        # Report the weights that actually move the ranking, not only the nominal ones.
        if objective == "composite":
            spread_c = (float(ndtr((ref_c - ref_mean) / ref_std).std()) if ref_std > 0 else 0.0)
            influence = {
                "closeness": weights["closeness"] * spread_c,
                "degree": weights["degree"] * float(degree_rank[composite_pool].std()),
                "density": weights["density"] * float(density_rank[composite_pool].std()),
            }
            total_influence = sum(influence.values())
            effective = {k: (v / total_influence if total_influence > 0 else weights[k])
                         for k, v in influence.items()}
            win = components(winner, objective)
            contribution = {
                "closeness": weights["closeness"] * win["closeness_norm"] / win["score"],
                "degree": weights["degree"] * win["degree_norm"] / win["score"],
                "density": weights["density"] * win["density_norm"] / win["score"],
            } if win["score"] > 0 else dict(weights)
            scoring = "rank-v2"
            nominal = dict(weights)
            normalisation = {
                "closeness": {"type": "normal-cdf-z", "mean": ref_mean, "std": ref_std,
                              "reference_nodes": n_ref},
                "degree": {"type": "mid-rank-percentile", "pool": len(composite_pool)},
                "density": {"type": "mid-rank-percentile", "pool": len(composite_pool)},
            }
        else:
            effective = nominal = contribution = {"closeness": 1.0, "degree": 0.0, "density": 0.0}
            scoring = "closeness-bounded"
            normalisation = {"closeness": {"type": "C/(C+1/study_radius)"}}

        method = "exact-scipy" if certified else "pivot-screened-exact-scipy"
        if objective == "closeness":
            method += "-closeness-100"
        stability_result = probe(objective, winner) if cases else None
        if stability_result and stability_result["level"] != "stable":
            warnings.append(
                f"Anchor ขยับได้ถึง {stability_result['max_drift_m']:.0f} ม. "
                f"({stability_result['max_drift_ratio']:.0%} ของรัศมี) เมื่อวงศึกษาเปลี่ยน ±20% — "
                "ผลขึ้นกับวงที่เลือก (ประมาณการ)")
        return {
            "anchor": anchor, "converged": bool(refined), "method": method,
            "objective": objective, "density_source": "road-junctions-only",
            "globally_certified": certified,
            "certification": ("exhaustive-fixed-objective" if certified
                              else "pivot-screened-exact-top-k"),
            "screening": screening, "scoring": scoring, "nominal_weights": dict(nominal),
            "effective_weights": dict(effective), "winner_contribution": dict(contribution),
            "normalisation": normalisation,
            "study_center": list(study_center), "study_radius_m": study_radius_m,
            "evaluated_nodes": int(sum(1 for i in pool if int(i) in exact_c)),
            "graph_nodes": n, "candidate_nodes": int(len(pool)),
            "junction_fallback": bool(objective == "composite" and junction_fallback),
            "destination_nodes": int(n_destinations), "boundary_margin_m": boundary_margin,
            "warnings": warnings, "stability": stability_result,
        }

    results = {objective: solve(objective) for objective in ("composite", "closeness")}

    def top_nodes(objective: str, limit: int) -> List[int]:
        in_pool = set(pools[objective].tolist())
        ranked = sorted((i for i in exact_c if i in in_pool),
                        key=lambda i: (round(components(i, objective)["score"], 12), -i), reverse=True)
        return ranked[:limit]

    candidate_nodes: List[int] = []
    for i in top_nodes("composite", ANCHOR_CONFIG["candidate_export"]) + top_nodes(
            "closeness", ANCHOR_CONFIG["candidate_export"]):
        if i not in candidate_nodes:
            candidate_nodes.append(i)
    composite_pool_set = set(composite_pool.tolist())
    evidence_candidates = []
    for i in candidate_nodes:
        comp = components(i, "composite")
        evidence_candidates.append({
            "node_id": str(nodes[i]), "lat": float(lonlat[i, 1]), "lon": float(lonlat[i, 0]),
            "composite_score": comp["score"], "closeness_norm": comp["closeness_norm"],
            "degree": int(degrees[i]), "junction_count": int(density[i]),
            "in_composite_pool": bool(i in composite_pool_set),
        })
    finished = time.perf_counter()
    timings = {"prep_s": prep_done - started, "pivots_s": pivots_done - prep_done,
               "exact_s": finished - pivots_done, "compute_s": finished - started}
    for result in results.values():
        result["compute_seconds"] = timings["compute_s"]
        result["timings"] = timings
    return {**results, "timings": timings, "rows_budget": rows_budget,
            "evidence_candidates": evidence_candidates,
            "graph": {"nodes": n, "edges": int(matrix.nnz // 2),
                      "dropped_nodes": net["total_nodes"] - n},
            "study_center": list(study_center), "study_radius_m": study_radius_m}


# ----------------------------------------------------------------------------
# Evidence stage: official city plan (ผังเมืองรวม) + parcel layer (รูปแปลงที่ดิน)
# ----------------------------------------------------------------------------
# The study radius sets the area; the highest-weight DPT colour inside it (ผังสีสูงสุด) marks
# where to look; the DOL parcel layer is measured only there, and the densest cluster of small
# lots is the evidence anchor. In Thai towns the commercial core is ตึกแถว (shophouse) strips:
# narrow lots of roughly 16-40 ตร.ว. (64-160 m²) whose boundary lines cover a large share of the
# picture, usually inside the พาณิชยกรรม (red) zone. These functions measure that from WMS
# images; they are pure (image in, numbers out) so they are testable without a network.

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


def load_cityplan_legend(path: Optional[Path] = None) -> Tuple[List[Dict[str, Any]], str]:
    """``(legend, source)``; ``source`` is ``"file"`` or ``"provisional"`` (never raises)."""
    try:
        data = json.loads(Path(path or CITYPLAN_LEGEND_FILE).read_text(encoding="utf-8"))
        classes = data["classes"] if isinstance(data, dict) else data
        legend = [
            {"name": str(c["name"]), "rgb": [int(v) for v in c["rgb"]][:3],
             "weight": float(c.get("weight", 0.0)), "commercial": bool(c.get("commercial", False))}
            for c in classes
        ]
        if legend and all(len(c["rgb"]) == 3 for c in legend):
            return legend, "file"
    except Exception:
        pass
    return [dict(c) for c in CITYPLAN_PROVISIONAL_LEGEND], "provisional"


def wms_meters_per_pixel(bbox_3857: Tuple[float, float, float, float], width_px: int, lat: float) -> float:
    """Ground metres per pixel of a Web-Mercator window (3857 metres shrink by cos(lat))."""
    return (bbox_3857[2] - bbox_3857[0]) / max(width_px, 1) * cos(radians(lat))


def _ink_mask(rgba: np.ndarray) -> np.ndarray:
    """Pixels that are drawn lines: alpha when the layer is transparent, else non-background."""
    alpha = rgba[..., 3]
    if alpha.min() < 255:
        return alpha > PARCEL_CONFIG["alpha_threshold"]
    rgb = rgba[..., :3].astype(np.int32)
    key = (rgb[..., 0] // 16) * 256 + (rgb[..., 1] // 16) * 16 + (rgb[..., 2] // 16)
    values, counts = np.unique(key, return_counts=True)
    background = rgb[key == values[counts.argmax()]].mean(axis=0)
    return np.abs(rgb - background).sum(axis=-1) > PARCEL_CONFIG["opaque_bg_tolerance"]


def _component_axes(labels: np.ndarray, n: int, centroids: bool = False) -> Tuple[np.ndarray, ...]:
    """Principal-axis side lengths (major, minor; pixels) of every labelled cell.

    From second moments, so a rotated rectangle keeps its true proportions
    (a rectangle with sides a >= b has variances a²/12 and b²/12). With ``centroids`` the
    centre ``(x, y)`` of every cell (pixels) follows as the third and fourth arrays.
    """
    flat = labels.ravel()
    yy, xx = np.indices(labels.shape)
    count = np.maximum(np.bincount(flat, minlength=n + 1)[1:].astype(float), 1.0)

    def moment(values: np.ndarray) -> np.ndarray:
        return np.bincount(flat, weights=values.ravel().astype(float), minlength=n + 1)[1:] / count

    mx, my = moment(xx), moment(yy)
    cxx = moment(xx * xx) - mx ** 2 + 1 / 12  # +1/12: variance of a pixel's own footprint
    cyy = moment(yy * yy) - my ** 2 + 1 / 12
    cxy = moment(xx * yy) - mx * my
    half_trace = (cxx + cyy) / 2
    spread = np.sqrt(np.maximum(half_trace ** 2 - (cxx * cyy - cxy ** 2), 0.0))
    major = np.sqrt(12.0 * (half_trace + spread))
    minor = np.sqrt(12.0 * np.maximum(half_trace - spread, 1e-9))
    return (major, minor, mx, my) if centroids else (major, minor)


def _component_aspect(labels: np.ndarray, n: int) -> np.ndarray:
    """Principal-axis aspect ratio (>= 1) of every labelled cell; rotation-invariant."""
    major, minor = _component_axes(labels, n)
    return major / minor


def _parcel_cells(rgba: np.ndarray, m_per_px: float) -> Dict[str, Any]:
    """The lots (free cells between boundary lines) of a DOL window, measured once.

    Specks and cells cut by the window edge are dropped, a free region above
    ``giant_cell_ratio`` is "no parcels here". ``data`` is False when nothing is measurable
    (blank layer, too few lots); otherwise ``area_m2`` / ``aspect`` / ``cx`` / ``cy`` (pixels)
    hold one entry per kept lot and ``ink`` is the boundary-line mask.
    """
    cfg = PARCEL_CONFIG
    out: Dict[str, Any] = {"data": False, "ink": None, "ink_ratio": 0.0, "coverage": 0.0, "cell_count": 0}
    if rgba.ndim != 3 or rgba.shape[2] != 4 or m_per_px <= 0:
        return out
    ink = _ink_mask(rgba)
    ink_ratio = float(ink.mean())
    out.update(ink=ink, ink_ratio=ink_ratio)
    if ink_ratio < cfg["min_ink_ratio"]:
        return out
    closed = (ndi.binary_closing(ink, structure=np.ones((cfg["closing_size"],) * 2))
              if cfg["closing_size"] > 1 else ink)
    labels, n = ndi.label(~closed)  # 4-connected free cells; 8-connected lines already separate them
    if n == 0:
        return out
    area_px = np.bincount(labels.ravel(), minlength=n + 1)[1:]
    edge = np.unique(np.concatenate((labels[0], labels[-1], labels[:, 0], labels[:, -1])))
    edge = edge[edge > 0] - 1
    touches_edge = np.zeros(n, dtype=bool)
    touches_edge[edge] = True
    giant = area_px > cfg["giant_cell_ratio"] * labels.size
    keep = ~touches_edge & ~giant & (area_px >= cfg["speck_px"])
    out.update(coverage=float(1.0 - area_px[giant].sum() / labels.size), cell_count=int(keep.sum()))
    if int(keep.sum()) < cfg["min_cells"]:
        return out
    # The free cells sit *between* the lines, so they are smaller than the parcels by half a
    # line width on every side: parcel = (a + t)(b + t) = A + P t/2 + t². The line width t is
    # recovered from the data (each line borders two cells: t ~ ink / (perimeter / 2)).
    boundary = ((ndi.minimum_filter(labels, size=3) != labels)
                | (ndi.maximum_filter(labels, size=3) != labels)) & (labels > 0)
    perimeter_px = np.bincount(labels[boundary], minlength=n + 1)[1:].astype(float)
    line_px = float(np.clip(ink.sum() / max(perimeter_px[keep].sum() / 2.0, 1.0), 0.5, 8.0))
    parcel_px = area_px[keep] + perimeter_px[keep] * line_px / 2.0 + line_px ** 2
    major, minor, cx, cy = _component_axes(labels, n, centroids=True)
    out.update(data=True, area_m2=parcel_px * m_per_px ** 2,
               aspect=(major[keep] + line_px) / (minor[keep] + line_px), cx=cx[keep], cy=cy[keep])
    return out


def parcel_features(rgba: np.ndarray, m_per_px: float) -> Dict[str, Any]:
    """Parcel fragmentation of a DOL window: how thick the lines look and how small the cells are.

    ``ink_ratio`` is the share of the picture covered by boundary lines (the "thick" look);
    cells are the regions *between* lines (see :func:`_parcel_cells`). ``shophouse_share``
    counts cells of 40-160 m² with aspect >= 2.5 — the ตึกแถว signature. ``coverage`` is the
    share of the window that is not blank; a blank or unreadable layer returns
    ``data = False`` (no data is not the same as "low").
    """
    cfg = PARCEL_CONFIG
    empty = {"data": False, "coverage": 0.0, "score": None, "ink_ratio": 0.0, "cell_count": 0,
             "median_cell_m2": None, "small_share": None, "shophouse_share": None}
    cells = _parcel_cells(rgba, m_per_px)
    if not cells["data"]:
        return {**empty, "ink_ratio": cells["ink_ratio"], "coverage": cells["coverage"],
                "cell_count": cells["cell_count"]}
    area_m2, aspect = cells["area_m2"], cells["aspect"]
    low, high = cfg["shophouse_area_m2"]
    small_share = float(np.mean(area_m2 < cfg["small_cell_m2"]))
    shophouse_share = float(np.mean((area_m2 >= low) & (area_m2 <= high)
                                    & (aspect >= cfg["shophouse_min_aspect"])))
    ink_scaled = float(np.clip((cells["ink_ratio"] - cfg["ink_low"]) / (cfg["ink_high"] - cfg["ink_low"]), 0, 1))
    w = cfg["score_weights"]
    score = w["shophouse"] * shophouse_share + w["small"] * small_share + w["ink"] * ink_scaled
    return {"data": True, "coverage": cells["coverage"], "score": float(score), "ink_ratio": cells["ink_ratio"],
            "cell_count": cells["cell_count"], "median_cell_m2": float(np.median(area_m2)),
            "small_share": small_share, "shophouse_share": shophouse_share}


def _classify_colors(rgba: np.ndarray, legend: List[Dict[str, Any]], tolerance: float) -> np.ndarray:
    """Nearest-legend-colour class per pixel (-1 = transparent / no colour within tolerance),
    then a 3x3 majority vote so thin outlines and text do not count as a class."""
    h, w = rgba.shape[:2]
    rgb = rgba[..., :3].astype(np.float32)
    best = np.full((h, w), np.inf, dtype=np.float32)
    cls = np.full((h, w), -1, dtype=np.int16)
    for k, entry in enumerate(legend):
        dist = np.sqrt(((rgb - np.asarray(entry["rgb"], dtype=np.float32)) ** 2).sum(axis=-1))
        closer = (dist < best) & (dist <= tolerance)
        best[closer] = dist[closer]
        cls[closer] = k
    cls[rgba[..., 3] <= PARCEL_CONFIG["alpha_threshold"]] = -1
    votes = np.stack([ndi.uniform_filter((cls == k).astype(np.float32), size=3)
                      for k in range(len(legend))], axis=0)
    smoothed = votes.argmax(axis=0).astype(np.int16)
    smoothed[votes.max(axis=0) < 0.5] = -1
    return smoothed


# ------------------------------------------------------------- WMS fetch + evidence runner
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


def _wms_window(lat: float, lon: float, window_m: float) -> Tuple[float, float, float, float]:
    """EPSG:3857 bbox that covers ``window_m`` ground metres around (lat, lon)."""
    x, y = _WEB_MERCATOR.transform(lon, lat)
    half = (window_m / 2.0) / max(cos(radians(lat)), 1e-6)  # Mercator metres stretch by 1/cos(lat)
    return (x - half, y - half, x + half, y + half)


def _wms_params(layer: str, bbox: Tuple[float, float, float, float], px: int) -> Dict[str, Any]:
    return {
        "service": "WMS", "version": "1.1.1", "request": "GetMap", "layers": layer, "styles": "",
        "srs": "EPSG:3857", "bbox": ",".join(f"{v:.1f}" for v in bbox),
        "width": px, "height": px, "format": "image/png", "transparent": "true",
    }


def _wms_cache_file(params: Dict[str, Any]) -> Path:
    digest = hashlib.sha256(json.dumps(params, sort_keys=True).encode("utf-8")).hexdigest()[:40]
    return CACHE_DIR / f"wms_{digest}.png"


def load_cached_wms_image(layer: str, bbox: Tuple[float, float, float, float], px: int
                          ) -> Optional[np.ndarray]:
    """The cached window as RGBA, or ``None`` — never touches the network (for thumbnails)."""
    from PIL import Image

    try:
        cache_file = _wms_cache_file(_wms_params(layer, bbox, px))
        return np.asarray(Image.open(cache_file).convert("RGBA")) if cache_file.exists() else None
    except Exception:
        return None


def fetch_wms_image(
    layer: str, bbox: Tuple[float, float, float, float], px: int
) -> Tuple[Optional[np.ndarray], Dict[str, Any]]:
    """RGBA ``(px, px, 4)`` array of a WMS window, from the disk cache or one GetMap request.

    The cache key excludes the API key, so a result is reproducible offline and exports with
    the cache. Never raises: ``(None, {"error": ...})`` on any failure (HTTP status, XML
    service exception, undecodable image, timeout).
    """
    from PIL import Image

    params = _wms_params(layer, bbox, px)
    cache_file = _wms_cache_file(params)
    info: Dict[str, Any] = {"layer": layer, "cache_file": cache_file.name, "from_cache": False}
    try:
        if cache_file.exists():
            image = Image.open(cache_file).convert("RGBA")
            info["from_cache"] = True
            return np.asarray(image), info
    except Exception:
        pass  # unreadable cache entry: fetch again
    try:
        response = requests.get(
            LONGDO_WMS_URL, params=params, timeout=EVIDENCE_CONFIG["timeout_s"],
            headers={"User-Agent": "Rent_Gradient-evidence/1.0"},
        )
        if response.status_code != 200:
            return None, {**info, "error": f"HTTP {response.status_code}"}
        if "image" not in response.headers.get("Content-Type", "image/png"):
            return None, {**info, "error": "server returned a service exception, not an image"}
        image = Image.open(io.BytesIO(response.content))
        image.load()
        image = image.convert("RGBA")
        if image.size != (px, px):
            return None, {**info, "error": f"unexpected image size {image.size}"}
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        try:
            _atomic_write(cache_file, buffer.getvalue())
            _atomic_write(cache_file.with_suffix(".json"), json.dumps(
                {"layer": layer, "bbox": list(bbox), "px": px,
                 "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}).encode("utf-8"))
        except Exception:
            pass  # caching is best-effort
        return np.asarray(image), info
    except Exception as exc:
        return None, {**info, "error": " ".join(str(exc).split())[:160] or type(exc).__name__}


# ---------------------------------------------------------------- area-first evidence
# Everything below sits on one global lattice of 128 Web-Mercator-metre cells, so a tile is the
# same WMS request (and cache file) whatever the study centre or radius. Arrays are indexed
# [row j, column i] with j growing northwards (images are flipped once, on the way in).
def _evidence_geometry(center: Tuple[float, float], radius_m: float) -> Dict[str, Any]:
    """Study circle in Web-Mercator metres plus the lattice-cell box that holds it.

    The box is aligned to whole plan tiles, so a red zone that reaches out of the circle is still
    read whole (the circle admits zones and clusters, it never clips them).
    """
    lat, lon = center
    x0, y0 = _WEB_MERCATOR.transform(lon, lat)
    r = float(radius_m) / max(cos(radians(lat)), 1e-6)  # 3857 metres stretch by 1/cos(lat)
    n = _cells_per_tile(EVIDENCE_CONFIG["plan_tile_m"])
    i0, i1 = int(floor(floor((x0 - r) / CELL_M) / n)) * n, (int(floor(floor((x0 + r) / CELL_M) / n)) + 1) * n - 1
    j0, j1 = int(floor(floor((y0 - r) / CELL_M) / n)) * n, (int(floor(floor((y0 + r) / CELL_M) / n)) + 1) * n - 1
    return {"x0": x0, "y0": y0, "r": r, "lat": lat, "ground": cos(radians(lat)), "radius_m": float(radius_m),
            "i0": i0, "j0": j0, "ni": i1 - i0 + 1, "nj": j1 - j0 + 1}


def _circle_mask(geo: Dict[str, Any], x0: float, y0: float, r: float) -> np.ndarray:
    """Cells of the lattice box whose centre lies within ``r`` (3857 metres) of ``(x0, y0)``."""
    xs = (geo["i0"] + np.arange(geo["ni"]) + 0.5) * CELL_M
    ys = (geo["j0"] + np.arange(geo["nj"]) + 0.5) * CELL_M
    return (xs[None, :] - x0) ** 2 + (ys[:, None] - y0) ** 2 <= r * r


def _tile_bbox(tx: int, ty: int, tile_m: float) -> Tuple[float, float, float, float]:
    return (tx * tile_m, ty * tile_m, (tx + 1) * tile_m, (ty + 1) * tile_m)


def _cells_per_tile(tile_m: float) -> int:
    return int(round(tile_m / CELL_M))


def _lattice_tiles(geo: Dict[str, Any], tile_m: float, circle: np.ndarray) -> List[Tuple[int, int]]:
    """``(tx, ty)`` of every tile holding at least one study cell, nearest to the centre first."""
    n = _cells_per_tile(tile_m)
    found = []
    for tx in range(int(floor((geo["x0"] - geo["r"]) / tile_m)), int(floor((geo["x0"] + geo["r"]) / tile_m)) + 1):
        for ty in range(int(floor((geo["y0"] - geo["r"]) / tile_m)), int(floor((geo["y0"] + geo["r"]) / tile_m)) + 1):
            i_lo, j_lo = max(tx * n - geo["i0"], 0), max(ty * n - geo["j0"], 0)
            i_hi, j_hi = min((tx + 1) * n - geo["i0"], geo["ni"]), min((ty + 1) * n - geo["j0"], geo["nj"])
            if i_lo < i_hi and j_lo < j_hi and circle[j_lo:j_hi, i_lo:i_hi].any():
                x_lo, y_lo, x_hi, y_hi = _tile_bbox(tx, ty, tile_m)
                found.append((round(hypot((x_lo + x_hi) / 2 - geo["x0"], (y_lo + y_hi) / 2 - geo["y0"]), 3), ty, tx))
    found.sort()
    return [(tx, ty) for _, ty, tx in found]


def _paste(dst: np.ndarray, src: np.ndarray, i_off: int, j_off: int) -> None:
    """Copy ``src`` (south-up) into ``dst`` with its lower-left cell at ``(i_off, j_off)``; clips."""
    nj, ni = dst.shape[-2:]
    sj, si = src.shape[-2:]
    j_lo, i_lo = max(j_off, 0), max(i_off, 0)
    j_hi, i_hi = min(j_off + sj, nj), min(i_off + si, ni)
    if j_lo < j_hi and i_lo < i_hi:
        dst[..., j_lo:j_hi, i_lo:i_hi] = src[..., j_lo - j_off:j_hi - j_off, i_lo - i_off:i_hi - i_off]


def estimate_evidence_requests(center: Tuple[float, float], radius_m: float) -> Dict[str, Any]:
    """Upper bound of the WMS requests a run would send (plan tiles are exact, parcel tiles capped)."""
    cfg = EVIDENCE_CONFIG
    geo = _evidence_geometry(center, radius_m)
    circle = _circle_mask(geo, geo["x0"], geo["y0"], geo["r"])
    plan = min(len(_lattice_tiles(geo, cfg["plan_tile_m"], circle)), int(cfg["max_plan_tiles"]))
    return {"plan_tiles": plan, "parcel_tiles_max": int(cfg["max_parcel_tiles"]),
            "requests_max": min(plan + int(cfg["max_parcel_tiles"]), int(cfg["max_requests"])),
            "area_km2": pi * float(radius_m) ** 2 / 1e6}


# -------------------------------------------------------------- plan: colours → peak zone
def _legend_lut(legend: List[Dict[str, Any]], tolerance: float) -> np.ndarray:
    """Class (or -1) for every 5-bit-per-channel RGB value: one table look-up per pixel."""
    idx = np.arange(32768)
    rgb = np.stack([((idx >> 10) & 31) * 8 + 4, ((idx >> 5) & 31) * 8 + 4, (idx & 31) * 8 + 4],
                   axis=1).astype(np.float32)
    best = np.full(idx.shape, np.inf, dtype=np.float32)
    lut = np.full(idx.shape, -1, dtype=np.int8)
    for k, entry in enumerate(legend):
        dist = np.sqrt(((rgb - np.asarray(entry["rgb"], dtype=np.float32)) ** 2).sum(axis=1))
        closer = (dist < best) & (dist <= tolerance)
        best[closer] = dist[closer]
        lut[closer] = k
    return lut


def _is_red_family(r: int, g: int, b: int) -> bool:
    """Red or pink at any strength: red is the channel maximum, reasonably saturated and bright, hue
    between magenta-pink (-30°) and red-orange (+15°). Orange, brown, yellow, green, blue and purple
    are not. Scalar twin of the vectorised test in :func:`_plan_tile_shares`."""
    mx, mn = max(r, g, b), min(r, g, b)
    d = mx - mn
    return r == mx and mx >= 128 and 5 * d >= mx and 2 * (g - b) >= -d and 4 * (g - b) <= d


def _plan_tile_shares(rgba: np.ndarray, lut: np.ndarray, n_classes: int, cells: int) -> Dict[str, Any]:
    """Pixels per cell of every legend class and of **red** (the last channel), plus the painted /
    explained counts, the colour of the red pixels and a coarse colour histogram (diagnostics).

    Red is recognised by hue, not by an exact legend colour: the peak colour is the user's own
    definition ("สีแดง คือ โซนสูงสุด"), and Longdo's real shade is not known here.
    """
    if rgba.ndim != 3 or rgba.shape[2] != 4 or rgba.shape[0] != rgba.shape[1] or rgba.shape[0] % cells:
        raise ValueError(f"unexpected plan image shape {rgba.shape}")
    painted = rgba[..., 3] > PARCEL_CONFIG["alpha_threshold"]
    key = ((rgba[..., 0] >> 3).astype(np.int32) << 10) | ((rgba[..., 1] >> 3).astype(np.int32) << 5) \
        | (rgba[..., 2] >> 3).astype(np.int32)
    cls = lut[key]
    cls[~painted] = -1
    rgb = rgba[..., :3].astype(np.int16)
    mx, mn = rgb.max(axis=2), rgb.min(axis=2)
    d, gb = mx - mn, rgb[..., 1] - rgb[..., 2]
    red = painted & (rgb[..., 0] == mx) & (mx >= 128) & (5 * d >= mx) & (2 * gb >= -d) & (4 * gb <= d)
    px = rgba.shape[0] // cells
    shares = np.zeros((n_classes + 1, cells, cells), dtype=np.uint16)
    for k in range(n_classes):
        shares[k] = (cls == k).reshape(cells, px, cells, px).sum(axis=(1, 3))
    shares[n_classes] = red.reshape(cells, px, cells, px).sum(axis=(1, 3))
    sample = painted[::4, ::4]
    keys4 = (((rgba[::4, ::4, 0] >> 4).astype(np.int32) << 8) | ((rgba[::4, ::4, 1] >> 4).astype(np.int32) << 4)
             | (rgba[::4, ::4, 2] >> 4).astype(np.int32))[sample]
    values, counts = np.unique(keys4, return_counts=True)
    return {"shares": shares[:, ::-1, :], "painted": int(painted.sum()), "explained": int((cls >= 0).sum()),
            "pixels": int(painted.size), "red_pixels": int(red.sum()),
            "red_sum": rgb[red].sum(axis=0).astype(np.int64) if red.any() else np.zeros(3, dtype=np.int64),
            "colours": {int(v): int(n) for v, n in zip(values, counts)}}


def _peak_classes(legend: List[Dict[str, Any]]) -> List[int]:
    """Legend classes that count as the peak zone besides red-by-hue: those flagged ``commercial``."""
    return [k for k, c in enumerate(legend) if c.get("commercial")]


def _peak_zone(shares: np.ndarray, legend: List[Dict[str, Any]], cell_px2: int) -> Optional[Dict[str, Any]]:
    """The red zones of the loaded plan tiles: cells where ≥ ``peak_cell_share`` of the pixels are red
    (by hue) or a legend class flagged ``commercial``, grouped 8-connected; groups below
    ``zone_min_cells`` are dropped, ``None`` when none is left. Zones are whole: the study circle does
    not clip them (see :func:`_zones_in_scope`). A lower colour is never promoted when there is no red."""
    cfg = EVIDENCE_CONFIG
    classes = _peak_classes(legend) + [shares.shape[0] - 1]          # the last channel is red-by-hue
    mask = shares[classes].sum(axis=0) >= cfg["peak_cell_share"] * cell_px2
    if not mask.any():
        return None
    labels, n = ndi.label(mask, structure=np.ones((3, 3), dtype=bool))
    sizes = np.bincount(labels.ravel(), minlength=n + 1)[1:]
    big = np.flatnonzero(sizes >= cfg["zone_min_cells"]) + 1
    if not big.size:
        return None
    return {"classes": classes, "labels": labels, "big": big, "sizes": sizes, "mask": np.isin(labels, big)}


def _zones_in_scope(peak: Dict[str, Any], circle: np.ndarray) -> Optional[Dict[str, Any]]:
    """Keep the red zones that reach into the study circle — whole. ``None`` = no red inside the radius."""
    inside = np.unique(peak["labels"][circle & (peak["labels"] > 0)])
    big = np.intersect1d(peak["big"], inside)
    if not big.size:
        return None
    return {**peak, "big": big, "mask": np.isin(peak["labels"], big)}


def _mask_polygon(mask: np.ndarray, geo: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """GeoJSON (lon/lat, 5 dp) of a cell mask: row runs → boxes → union → light simplification."""
    boxes = []
    for j in np.flatnonzero(mask.any(axis=1)):
        d = np.diff(np.concatenate(([False], mask[j], [False])).astype(np.int8))
        for s, e in zip(np.flatnonzero(d == 1), np.flatnonzero(d == -1)):
            boxes.append(box((geo["i0"] + s) * CELL_M, (geo["j0"] + j) * CELL_M,
                             (geo["i0"] + e) * CELL_M, (geo["j0"] + j + 1) * CELL_M))
    if not boxes:
        return None
    geom = unary_union(boxes).simplify(CELL_M / 4.0)
    polys = [geom] if geom.geom_type == "Polygon" else [g for g in getattr(geom, "geoms", []) if g.geom_type == "Polygon"]

    def ring(coords) -> List[List[float]]:
        arr = np.asarray(coords, dtype=float)
        lon, lat = _WEB_MERCATOR_INV.transform(arr[:, 0], arr[:, 1])
        return [[round(float(a), 5), round(float(b), 5)] for a, b in zip(lon, lat)]

    rings = [[ring(p.exterior.coords)] + [ring(r.coords) for r in p.interiors] for p in polys]
    if not rings:
        return None
    return ({"type": "Polygon", "coordinates": rings[0]} if len(rings) == 1
            else {"type": "MultiPolygon", "coordinates": rings})


def _cell_lonlat(geo: Dict[str, Any], col: float, row: float) -> Tuple[float, float]:
    """``(lat, lon)`` of a (fractional) lattice-local cell position; ``+0.5`` is the cell centre."""
    lon, lat = _WEB_MERCATOR_INV.transform((geo["i0"] + col + 0.5) * CELL_M, (geo["j0"] + row + 0.5) * CELL_M)
    return float(lat), float(lon)


def _dominant_colours(histogram: Dict[int, int], legend: List[Dict[str, Any]], top: int = 6) -> List[Dict[str, Any]]:
    """Most common painted colours of the plan tiles (4 bits per channel), each with the legend class
    it matches (``None`` = unknown) and whether it counts as red — what to read when colours look off."""
    total = sum(histogram.values()) or 1
    out = []
    for key4, count in sorted(histogram.items(), key=lambda kv: (-kv[1], kv[0]))[:top]:
        r, g, b = ((key4 >> 8) & 15) * 16 + 8, ((key4 >> 4) & 15) * 16 + 8, (key4 & 15) * 16 + 8
        distances = [hypot(hypot(r - c["rgb"][0], g - c["rgb"][1]), b - c["rgb"][2]) for c in legend]
        best = min(range(len(legend)), key=lambda k: (distances[k], k), default=None)
        matched = legend[best]["name"] if best is not None and distances[best] <= ZONING_COLOR_TOLERANCE else None
        out.append({"hex": "#%02x%02x%02x" % (r, g, b), "share": count / total, "legend": matched,
                    "red": _is_red_family(r, g, b)})
    return out


def _zone_records(zone: Dict[str, Any], geo: Dict[str, Any], legend: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Largest zones of the peak class first (cells desc, then raster order)."""
    cfg = EVIDENCE_CONFIG
    labels, sizes = zone["labels"], zone["sizes"]
    first = {int(lab): int(np.flatnonzero(labels == lab)[0]) for lab in zone["big"]}
    order = sorted((int(lab) for lab in zone["big"]), key=lambda lab: (-int(sizes[lab - 1]), first[lab]))
    cell_km2 = (CELL_M * geo["ground"]) ** 2 / 1e6
    out = []
    for rank, lab in enumerate(order[: int(cfg["zone_top"])], start=1):
        rows, cols = np.nonzero(labels == lab)
        lat, lon = _cell_lonlat(geo, float(cols.mean()), float(rows.mean()))
        out.append({"rank": rank, "lat": lat, "lon": lon, "cells": int(sizes[lab - 1]),
                    "area_km2": float(sizes[lab - 1] * cell_km2), "polygon": _mask_polygon(labels == lab, geo)})
    return out


# ------------------------------------------------------------ parcels: ถี่ cluster of small lots
def _parcel_tile_scores(rgba: np.ndarray, m_per_px: float, cells: int) -> Optional[Dict[str, Any]]:
    """Per-cell frequency of small / ตึกแถว lots in one parcel tile (``None`` = no measurable lots).

    ``cover_*`` is the share of the cell's ground area taken by those lots — a few shophouses
    beside farmland stay low, a shophouse block saturates. Cells without drawn lines are no data.
    """
    cfg, ev = PARCEL_CONFIG, EVIDENCE_CONFIG
    if rgba.ndim != 3 or rgba.shape[2] != 4 or rgba.shape[0] != rgba.shape[1] or rgba.shape[0] % cells:
        raise ValueError(f"unexpected parcel image shape {rgba.shape}")
    parcels = _parcel_cells(rgba, m_per_px)
    if not parcels["data"]:
        return None
    px = rgba.shape[0] // cells
    cell_m2 = (px * m_per_px) ** 2
    area, aspect = parcels["area_m2"], parcels["aspect"]
    flat = (np.clip((parcels["cy"] // px).astype(int), 0, cells - 1) * cells
            + np.clip((parcels["cx"] // px).astype(int), 0, cells - 1))
    low, high = cfg["shophouse_area_m2"]
    small = area < cfg["small_cell_m2"]
    shop = (area >= low) & (area <= high) & (aspect >= cfg["shophouse_min_aspect"])

    def cover(sel: np.ndarray) -> np.ndarray:
        return np.bincount(flat[sel], weights=area[sel], minlength=cells * cells).reshape(cells, cells) / cell_m2

    cover_small, cover_shop = cover(small), cover(shop)
    ink_cell = parcels["ink"].reshape(cells, px, cells, px).mean(axis=(1, 3))
    ink_scaled = np.clip((ink_cell - cfg["ink_low"]) / (cfg["ink_high"] - cfg["ink_low"]), 0, 1)
    w, ref = cfg["score_weights"], ev["cover_ref"]
    score = (w["shophouse"] * np.clip(cover_shop / ref, 0, 1) + w["small"] * np.clip(cover_small / ref, 0, 1)
             + w["ink"] * ink_scaled)
    score[ink_cell < cfg["min_ink_ratio"]] = np.nan
    return {"score": score[::-1], "cover_small": cover_small[::-1], "cover_shop": cover_shop[::-1],
            "lots": int(area.size)}


def _smooth_nan(score: np.ndarray, size: int) -> np.ndarray:
    """Box mean over the cells that have data; cells without data stay NaN."""
    ok = np.isfinite(score)
    num = ndi.uniform_filter(np.where(ok, score, 0.0), size=size, mode="constant")
    den = ndi.uniform_filter(ok.astype(float), size=size, mode="constant")
    out = np.full(score.shape, np.nan)
    good = ok & (den > 1e-9)
    out[good] = num[good] / den[good]
    return out


def _hot_threshold(values: np.ndarray) -> float:
    """Smoothed score from which a cell is hot: ``hot_score`` when the red zone is that dense, else the
    densest quarter of its scored cells (never below ``hot_floor``). Real lot patterns are far less
    regular than the synthetic ones the 0.5 was set on, so "ถี่" must also work relative to the zone;
    how convincing the cluster is in absolute terms is left to the confidence."""
    cfg = EVIDENCE_CONFIG
    return float(min(cfg["hot_score"], max(cfg["hot_floor"], np.quantile(values, cfg["hot_quantile"]))))


def _clusters_of(
    smooth: np.ndarray,
    zones: Dict[str, Any],
    fields: Dict[str, np.ndarray],
    scanned: np.ndarray,
    geo: Dict[str, Any],
) -> Dict[str, Any]:
    """Every dense cluster of the red zones, whole — **independent of the study circle**.

    Hot cells are decided zone by zone (dense in absolute terms, or among the densest quarter of *that
    zone*), so a zone that enters when the radius grows never moves another zone's threshold, and a
    larger radius can only add candidates. ``touches_boundary`` = the cluster runs into a part of its
    zone that was not scanned (tile budget / failed tile). Choosing among them is :func:`_pick_cluster`.
    """
    cfg = EVIDENCE_CONFIG
    three = np.ones((3, 3), dtype=bool)
    labels_z, zone = zones["labels"], zones["mask"]
    finite = np.isfinite(smooth)
    nj, ni = smooth.shape
    hot = np.zeros(smooth.shape, dtype=bool)
    thr_map = np.full(smooth.shape, np.nan)
    objects = ndi.find_objects(labels_z)
    for lab in zones["big"]:
        box_ = objects[int(lab) - 1] if int(lab) <= len(objects) else None
        if box_ is None:
            continue
        sl = (slice(max(box_[0].start - 1, 0), min(box_[0].stop + 1, nj)),
              slice(max(box_[1].start - 1, 0), min(box_[1].stop + 1, ni)))
        scope = ndi.binary_dilation(labels_z[sl] == lab, structure=three) & finite[sl]
        if not scope.any():
            continue
        thr = _hot_threshold(smooth[sl][scope])
        mine = scope & (np.where(finite[sl], smooth[sl], -1.0) >= thr)
        hot[sl] |= mine
        thr_map[sl][mine] = thr
    labels, n = ndi.label(hot, structure=three)
    if n == 0:
        return {"clusters": [], "labels": labels}
    index = np.arange(1, n + 1)
    weights = np.where(hot, smooth, 0.0)
    cells = np.asarray(ndi.sum(hot, labels, index), dtype=float)
    mass = np.asarray(ndi.sum(weights, labels, index), dtype=float)
    first = np.asarray(ndi.minimum(np.arange(hot.size).reshape(hot.shape), labels, index), dtype=float)
    rim = ndi.binary_dilation(zone & ~scanned, structure=three)
    cut = np.asarray(ndi.maximum(rim.astype(float), labels, index))
    in_zone = np.asarray(ndi.mean(zone.astype(float), labels, index))
    cover_small = np.asarray(ndi.mean(np.where(hot, fields["cover_small"], 0.0), labels, index))
    cover_shop = np.asarray(ndi.mean(np.where(hot, fields["cover_shop"], 0.0), labels, index))
    centres = ndi.center_of_mass(weights, labels, index)
    cell_ha = (CELL_M * geo["ground"]) ** 2 / 1e4
    clusters = []
    for k in range(n):
        if cells[k] < cfg["cluster_min_cells"]:
            continue
        row, col = centres[k]
        lat, lon = _cell_lonlat(geo, float(col), float(row))
        clusters.append({
            "lat": lat, "lon": lon, "cells": int(cells[k]), "area_ha": float(cells[k] * cell_ha),
            "score": float(mass[k] / cells[k]), "mass": float(mass[k]),
            "cover_small": float(cover_small[k]), "cover_shop": float(cover_shop[k]),
            "in_zone": float(in_zone[k]) >= 0.5, "touches_boundary": bool(cut[k] > 0),
            "threshold": float(thr_map.flat[int(first[k])]),
            "_x": (geo["i0"] + float(col) + 0.5) * CELL_M, "_y": (geo["j0"] + float(row) + 0.5) * CELL_M,
            "_first": float(first[k]), "_label": k + 1})
    return {"clusters": clusters, "labels": labels}


def _pick_cluster(
    clusters: List[Dict[str, Any]], geo: Dict[str, Any], centre: Tuple[float, float], radius_m: float,
    top: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """The circle (``centre`` in 3857 metres, ``radius_m`` on the ground) admits clusters by centroid;
    they are ranked by ``mass / (1 + (distance / reach_m)²)`` — a smooth prior toward the study centre
    that does not depend on the radius, so a far village needs ≈ 10× the mass to beat a town at the
    centre. Ties: raster order."""
    reach = EVIDENCE_CONFIG["reach_m"]
    out = []
    for c in clusters:
        d = hypot(c["_x"] - centre[0], c["_y"] - centre[1]) * geo["ground"]
        if d <= radius_m:
            out.append({**c, "distance_m": float(d), "weighted_mass": float(c["mass"] / (1.0 + (d / reach) ** 2))})
    out.sort(key=lambda c: (-round(c["weighted_mass"], 12), c["_first"]))
    for rank, c in enumerate(out, start=1):
        c["rank"] = rank
    return out if top is None else out[: int(top)]


def _evidence_stability(clusters: List[Dict[str, Any]], geo: Dict[str, Any], best: Dict[str, Any]) -> Dict[str, Any]:
    """How far the winning cluster moves when the study circle changes (radius ×0.8 and ×1.2, centre ±0.2R, at most 1 km).

    Re-picks among the clusters already read — no request, so growth (×1.2) only sees red zones that were
    already scanned. Indicative, like the road probe.
    """
    cfg = EVIDENCE_CONFIG["stability"]
    x0, y0, radius = geo["x0"], geo["y0"], geo["radius_m"]
    step = min(cfg["shift"] * geo["r"], cfg["shift_max_m"] / geo["ground"])   # 3857 m; ≤ 1 km on the ground
    cases = [(x0, y0, cfg["shrink"] * radius), (x0, y0, cfg["grow"] * radius)]
    cases += [(x0 + dx * step, y0 + dy * step, radius) for dx, dy in ((0, 1), (1, 0), (0, -1), (-1, 0))]
    drifts = []
    for cx, cy, cr in cases:
        found = _pick_cluster(clusters, geo, (cx, cy), cr, top=1)
        drifts.append(hypot(found[0]["_x"] - best["_x"], found[0]["_y"] - best["_y"]) * geo["ground"]
                      if found else radius)
    worst = max(drifts)
    ratio = worst / max(radius, 1e-9)
    level = "stable" if ratio <= cfg["stable"] else ("check" if ratio <= cfg["check"] else "unstable")
    return {"cases": len(cases), "max_drift_m": float(worst), "median_drift_m": float(np.median(drifts)),
            "max_drift_ratio": float(ratio), "level": level}


def classify_anchor_confidence(
    anchor: Dict[str, Any],
    road_anchors: List[Dict[str, Any]],
    *,
    zoning_ok: Optional[bool],
    parcel_ok: Optional[bool],
    coverage: float,
    peak: Optional[Dict[str, Any]],
    cluster: Optional[Dict[str, Any]],
    stability_levels: List[Optional[str]],
    cfg: Dict[str, Any],
) -> Dict[str, Any]:
    """HIGH needs independent signals to agree: roads (an anchor within ``agree_radius_m``), the
    official plan (the peak colour is พาณิชยกรรม and the anchor sits in it) and the parcel
    structure (a dense cluster). Reasons are returned in Thai for the UI."""
    conf = cfg["confidence"]
    reasons: List[str] = []
    nearest = min((calculate_distance_meters(anchor["lat"], anchor["lon"], a["lat"], a["lon"])
                   for a in road_anchors), default=None)
    roads_ok = None if nearest is None else nearest <= cfg["agree_radius_m"]
    reasons.append(
        f"ถนน: anchor ถนนที่ใกล้สุดห่าง {nearest:,.0f} ม." + (" (สอดคล้อง)" if roads_ok else " (ไม่สอดคล้อง)")
        if nearest is not None else "ถนน: ไม่มี anchor อ้างอิง")
    if zoning_ok is None or not peak:
        reasons.append("ผังเมือง: ไม่มีข้อมูล (นอกพื้นที่ผังเมืองหรืออ่านภาพ/สีไม่ได้)")
    else:
        label = f"{peak['name']}" + (" (พาณิชยกรรม)" if peak.get("commercial") else "")
        reasons.append(f"ผังเมือง: สีสูงสุดที่พบ {label} {peak['area_km2']:.2f} ตร.กม."
                       + (" — anchor อยู่ในโซนนี้" if zoning_ok else " — anchor อยู่นอกโซนพาณิชยกรรม"))
    if cluster:
        reasons.append(f"แปลงที่ดิน: cluster แปลงเล็กถี่ {cluster['cells']} เซลล์ (~{cluster['area_ha']:,.0f} เฮกตาร์) "
                       f"คะแนน {cluster['score']:.2f}" + ("" if parcel_ok else " (ไม่เด่น)"))
    elif parcel_ok is False:
        reasons.append("แปลงที่ดิน: ไม่พบ cluster ที่ถี่พอในโซน")
    else:
        reasons.append("แปลงที่ดิน: ไม่มีข้อมูล")
    touches = bool(cluster and cluster.get("touches_boundary"))
    if touches:
        reasons.append("cluster ต่อเนื่องเข้าส่วนของโซนแดงที่ยังไม่ได้สแกน (เกินโควตาไทล์/ดึงไม่สำเร็จ)")
    unstable = "unstable" in stability_levels
    if unstable:
        reasons.append("ความนิ่ง: anchor ขยับมากเมื่อวงศึกษาเปลี่ยน (ไม่นิ่ง)")
    agreeing = sum(1 for f in (roads_ok, zoning_ok, parcel_ok) if f)
    if coverage >= conf["coverage_min"] and agreeing == 3 and not unstable and not touches:
        level = "HIGH"
    elif coverage >= conf["coverage_medium"] and agreeing >= 2:
        level = "MEDIUM"
    else:
        level = "LOW"
    return {"level": level, "reasons": reasons, "coverage": coverage,
            "signals": {"roads": roads_ok, "zoning": zoning_ok, "parcel": parcel_ok},
            "nearest_road_anchor_m": nearest}


def _fetch_tiles(
    fetcher: Callable[..., Tuple[Optional[np.ndarray], Dict[str, Any]]],
    jobs: List[Tuple[Any, str, Tuple[float, float, float, float]]],
    analyse: Callable[[Any, np.ndarray], Any],
    deadline: float,
    tally: Dict[str, Any],
) -> Dict[Any, Tuple[str, Any]]:
    """Fetch and analyse tiles in parallel → ``{key: (status, value)}``; never raises.

    ``status`` is ``ok`` (value = analysis), ``nodata`` (image fine, nothing measurable) or
    ``error``. Tiles unfinished at ``deadline`` are cancelled and counted as skipped.
    """
    cfg = EVIDENCE_CONFIG
    if not jobs:
        return {}

    def short(exc: BaseException) -> str:
        return f"{type(exc).__name__}: {' '.join(str(exc).split())[:120]}"

    def work(key: Any, layer: str, bbox: Tuple[float, float, float, float]):
        try:
            image, info = fetcher(layer, bbox, cfg["px"])
        except Exception as exc:  # one bad tile must not cancel the others
            return key, "error", None, {"error": short(exc)}
        if image is None:
            return key, "error", None, info
        try:
            value = analyse(key, image)
        except Exception as exc:
            return key, "error", None, {**info, "error": short(exc)}
        return key, ("ok" if value is not None else "nodata"), value, info

    pool = ThreadPoolExecutor(max_workers=max(1, int(cfg["parallel"])))
    out: Dict[Any, Tuple[str, Any]] = {}
    try:
        futures = [pool.submit(work, *job) for job in jobs]
        done, pending = wait(futures, timeout=max(0.0, deadline - time.perf_counter()))
        for future in futures:
            if future not in done:
                future.cancel()
                continue
            key, status, value, info = future.result()
            out[key] = (status, value)
            tally["fetched"] += 1
            tally["hits"] += bool(info.get("from_cache"))
            if status == "error":
                tally["errors"].append(f"{key[0]}#{key[1]},{key[2]}: {info.get('error', 'no image')}")
        if pending:
            tally["timed_out"] += len(pending)
            tally["errors"].append(f"หมดเวลา: ข้าม {len(pending)} ไทล์")
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    return out


def run_evidence_stage(
    found: Dict[str, Any],
    study_center: Tuple[float, float],
    study_radius_m: float,
    legend: Optional[List[Dict[str, Any]]] = None,
    legend_source: str = "provisional",
    fetcher: Callable[..., Tuple[Optional[np.ndarray], Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Scan the whole study circle for the dense small-parcel cluster inside the peak-colour zone.

    Plan tiles (ผังสี) → peak colour and its zones → parcel tiles only where that zone is →
    densest cluster of small / ตึกแถว lots → the evidence anchor. ``found`` (the road result) is
    used only to agree with the road anchors and, when the plan is unreadable, to say where to look.
    Never raises; without evidence the road anchors are left exactly as they are.
    """
    cfg = EVIDENCE_CONFIG
    fetcher = fetcher or fetch_wms_image
    started = time.perf_counter()
    deadline = started + float(cfg["deadline_s"])
    tally: Dict[str, Any] = {"fetched": 0, "hits": 0, "errors": [], "skipped": 0, "timed_out": 0}
    base: Dict[str, Any] = {
        "schema": EVIDENCE_SCHEMA, "method": "peak-zone-parcel-cluster", "status": "unavailable",
        "reason": None, "notes": [], "legend_source": legend_source,
        "study": {"center": [float(study_center[0]), float(study_center[1])],
                  "radius_m": float(study_radius_m), "area_km2": pi * float(study_radius_m) ** 2 / 1e6},
        "windows": {"px": cfg["px"], "plan_tile_m": cfg["plan_tile_m"], "parcel_tile_m": cfg["parcel_tile_m"],
                    "cell_m": CELL_M},
        "plan": {"state": "unavailable", "tiles": 0, "tiles_ok": 0, "explained": None, "peak": None, "zones": []},
        "parcel": {"region": None, "tiles_needed": 0, "tiles_ok": 0, "tiles_skipped": 0},
        "clusters": [], "evidence_anchor": None, "confidence": None, "stability": None,
        "fetch": {"requests": 0, "cache_hits": 0, "errors": [], "skipped_over_budget": 0, "seconds": 0.0},
    }

    def finish(**updates: Any) -> Dict[str, Any]:
        base["fetch"] = {"requests": tally["fetched"] - tally["hits"], "cache_hits": tally["hits"],
                         "errors": tally["errors"][:10],
                         "skipped_over_budget": tally["skipped"] + tally["timed_out"],
                         "seconds": time.perf_counter() - started}
        return {**base, **updates}

    try:
        legend = legend or load_cityplan_legend()[0]
        composite = (found or {}).get("composite") or {}
        closeness = (found or {}).get("closeness") or {}
        road_anchors = [a for a in (composite.get("anchor"), closeness.get("anchor"))
                        if a and a.get("lat") is not None and a.get("lon") is not None]
        geo = _evidence_geometry(study_center, study_radius_m)
        circle = _circle_mask(geo, geo["x0"], geo["y0"], geo["r"])
        n_plan, n_parcel = _cells_per_tile(cfg["plan_tile_m"]), _cells_per_tile(cfg["parcel_tile_m"])
        budget = int(cfg["max_requests"])

        # ---- plan pass: colours → peak zone
        lut = _legend_lut(legend, ZONING_COLOR_TOLERANCE)
        plan_all = _lattice_tiles(geo, cfg["plan_tile_m"], circle)
        plan_tiles = plan_all[: min(int(cfg["max_plan_tiles"]), budget)]
        tally["skipped"] += len(plan_all) - len(plan_tiles)
        plan_jobs = [(("plan", tx, ty), cfg["plan_layer"], _tile_bbox(tx, ty, cfg["plan_tile_m"]))
                     for tx, ty in plan_tiles]
        plan_out = _fetch_tiles(
            fetcher, plan_jobs,
            lambda key, image: _plan_tile_shares(image, lut, len(legend), n_plan), deadline, tally)
        shares = np.zeros((len(legend) + 1, geo["nj"], geo["ni"]), dtype=np.uint16)   # legend classes + red
        painted = explained = pixels = plan_ok = red_pixels = 0
        red_sum = np.zeros(3, dtype=np.int64)
        histogram: Dict[int, int] = {}
        for (_, tx, ty), (status, value) in sorted(plan_out.items(), key=lambda kv: kv[0]):
            if status != "ok":
                continue
            plan_ok += 1
            _paste(shares, value["shares"], tx * n_plan - geo["i0"], ty * n_plan - geo["j0"])
            painted += value["painted"]
            explained += value["explained"]
            pixels += value["pixels"]
            red_pixels += value["red_pixels"]
            red_sum += value["red_sum"]
            for key4, count in value["colours"].items():
                histogram[key4] = histogram.get(key4, 0) + count
        peak = None
        if plan_ok == 0:
            plan_state = "unavailable"
        elif painted < cfg["plan_min_painted"] * max(pixels, 1):
            plan_state = "blank"
        else:
            peak = _peak_zone(shares, legend, (cfg["px"] // n_plan) ** 2)
            peak = _zones_in_scope(peak, circle) if peak else None   # red inside the radius, zones whole
            plan_state = "ok" if peak else "no_peak"
        plan_info: Dict[str, Any] = {
            "state": plan_state, "tiles": len(plan_tiles), "tiles_ok": int(plan_ok),
            "explained": (explained / painted) if painted else None, "peak": None, "zones": [],
            "colours": _dominant_colours(histogram, legend)}

        # ---- search region: the peak zone, or (plan unreadable) a disc around the road anchor
        notes: List[str] = []
        zones: List[Dict[str, Any]] = []
        if peak:
            zone = peak["mask"]
            zones = _zone_records(peak, geo, legend)
            area_km2 = float(zone.sum() * (CELL_M * geo["ground"]) ** 2 / 1e6)
            seen = (red_sum / max(red_pixels, 1)).round().astype(int).tolist()     # the red Longdo really serves
            plan_info["peak"] = {"name": "สีแดง", "rgb": seen if red_pixels else [255, 0, 0], "weight": 1.0,
                                 "commercial": True, "cells": int(zone.sum()), "area_km2": area_km2}
            plan_info["zones"] = zones
            peak_zones = peak
            region_kind = "peak_zone"
        else:
            reason_text = {"unavailable": "ดึงภาพผังเมืองไม่สำเร็จ", "blank": "ผังเมืองว่าง/นอกพื้นที่ผังเมืองรวม",
                           "no_peak": "ไม่พบโซนพาณิชยกรรม (สีแดง) ในวงศึกษา"}[plan_state]
            anchor_ref = composite.get("anchor") if composite else None
            if not anchor_ref or anchor_ref.get("lat") is None:
                return finish(plan=plan_info, reason=f"{reason_text} และไม่มี anchor ถนนให้ใช้เป็นจุดค้นหา")
            fx, fy = _WEB_MERCATOR.transform(anchor_ref["lon"], anchor_ref["lat"])
            zone = _circle_mask(geo, fx, fy, cfg["fallback_radius_m"] / geo["ground"])
            peak_zones = {"labels": zone.astype(np.int32), "big": np.array([1]), "mask": zone}
            region_kind = "fallback_disc"
            notes.append(f"{reason_text} — ใช้เฉพาะแปลงที่ดินในรัศมี {cfg['fallback_radius_m'] / 1000:g} กม. รอบ anchor ถนน")

        # ---- parcel pass: tiles under the region, densest first
        jj, ii = np.nonzero(zone)
        gi, gj = (geo["i0"] + ii) // n_parcel, (geo["j0"] + jj) // n_parcel
        keys, counts = np.unique(np.stack([gj, gi], axis=1), axis=0, return_counts=True)
        # tile priority = zone cells / (1 + (distance to the study centre / reach)²): the same radius-free prior
        # as the cluster choice, so a far zone entering with a larger radius never evicts a town tile
        def tile_priority(count: int, tj: int, ti: int) -> Tuple[float, float, int, int]:
            d = hypot((ti + 0.5) * cfg["parcel_tile_m"] - geo["x0"], (tj + 0.5) * cfg["parcel_tile_m"] - geo["y0"]) * geo["ground"]
            return (-round(count / (1.0 + (d / cfg["reach_m"]) ** 2), 12), round(d, 3), tj, ti)

        ranked = sorted(zip(counts.tolist(), keys[:, 0].tolist(), keys[:, 1].tolist()),
                        key=lambda t: tile_priority(*t))
        needed = len(ranked)
        room = max(0, min(int(cfg["max_parcel_tiles"]), budget - len(plan_jobs)))
        chosen = [(ti, tj) for _, tj, ti in ranked[:room]]
        tally["skipped"] += needed - len(chosen)
        m_per_px = cfg["parcel_tile_m"] / cfg["px"] * geo["ground"]
        parcel_jobs = [(("parcel", ti, tj), cfg["parcel_layer"], _tile_bbox(ti, tj, cfg["parcel_tile_m"]))
                       for ti, tj in chosen]
        parcel_out = _fetch_tiles(
            fetcher, parcel_jobs, lambda key, image: _parcel_tile_scores(image, m_per_px, n_parcel), deadline, tally)
        fields = {name: np.full((geo["nj"], geo["ni"]), np.nan) for name in ("score", "cover_small", "cover_shop")}
        scanned = np.zeros((geo["nj"], geo["ni"]), dtype=bool)         # cells whose parcel tile was read
        parcel_ok = 0
        for (_, ti, tj), (status, value) in sorted(parcel_out.items(), key=lambda kv: kv[0]):
            if status == "error":
                continue
            parcel_ok += 1
            _paste(scanned, np.ones((n_parcel, n_parcel), dtype=bool), ti * n_parcel - geo["i0"], tj * n_parcel - geo["j0"])
            if status == "ok":
                for name in fields:
                    _paste(fields[name], value[name], ti * n_parcel - geo["i0"], tj * n_parcel - geo["j0"])
        coverage = parcel_ok / needed if needed else 0.0
        parcel_info = {"region": region_kind, "tiles_needed": needed, "tiles_ok": parcel_ok,
                       "tiles_skipped": needed - parcel_ok,
                       "lots": int(sum(v["lots"] for st_, v in parcel_out.values() if st_ == "ok")),
                       "best_score": None, "hot_threshold": None}
        have_parcels = bool(np.isfinite(fields["score"]).any())

        # ---- the clusters of the red zone(s), whole; the circle only admits them, the study-centre prior ranks them
        smooth = _smooth_nan(fields["score"], int(cfg["smooth_cells"]))
        zone_dilated = ndi.binary_dilation(zone, structure=np.ones((3, 3), dtype=bool))
        in_scope = zone_dilated & np.isfinite(smooth)
        if in_scope.any():
            parcel_info["best_score"] = float(smooth[in_scope].max())
        found_clusters = (_clusters_of(smooth, peak_zones, fields, scanned, geo)
                          if have_parcels else {"clusters": [], "labels": None})
        if found_clusters["clusters"]:
            parcel_info["hot_threshold"] = float(min(c["threshold"] for c in found_clusters["clusters"]))
        elif in_scope.any():
            parcel_info["hot_threshold"] = _hot_threshold(smooth[in_scope])
        picked = _pick_cluster(found_clusters["clusters"], geo, (geo["x0"], geo["y0"]), geo["radius_m"])
        clusters = picked[: int(cfg["cluster_top"])]
        for record in clusters:
            record["polygon"] = _mask_polygon(found_clusters["labels"] == record["_label"], geo)
        winner = clusters[0] if clusters else None
        if winner is None and not peak:
            return finish(plan=plan_info, parcel=parcel_info, notes=notes, reason=(
                "ไม่มีพื้นที่ให้ค้นหา (anchor ถนนอยู่นอกวงศึกษา)" if needed == 0
                else "ไม่พบ cluster แปลงเล็กถี่ใกล้ anchor ถนน" if have_parcels
                else "ดึงภาพ/อ่านข้อมูลผังเมืองและแปลงที่ดินไม่สำเร็จ — ใช้ผลจากถนนอย่างเดียว"))
        if winner is None:
            notes.append("ไม่พบ cluster แปลงเล็กถี่ในโซน — ใช้จุดกึ่งกลางโซนสีสูงสุดใหญ่สุดแทน" if have_parcels
                         else "อ่านรูปแปลงที่ดินไม่ได้ — ใช้จุดกึ่งกลางโซนสีสูงสุดใหญ่สุดแทน")
            inside_zones = [z for z in zones if calculate_distance_meters(
                z["lat"], z["lon"], study_center[0], study_center[1]) <= study_radius_m]
            if not inside_zones:       # the red only grazes the rim of the circle: no anchor inside the study area
                return finish(plan=plan_info, parcel=parcel_info, notes=notes,
                              reason="โซนแดงอยู่แค่ขอบวงศึกษา — จุดกึ่งกลางโซนอยู่นอกรัศมี")
            point, basis = inside_zones[0], "zone"
        else:
            point, basis = winner, "cluster"
        stability = _evidence_stability(found_clusters["clusters"], geo, winner) if winner else None

        # ---- confidence
        point_x, point_y = _WEB_MERCATOR.transform(point["lon"], point["lat"])
        cell_i, cell_j = int(floor(point_x / CELL_M)) - geo["i0"], int(floor(point_y / CELL_M)) - geo["j0"]
        inside = 0 <= cell_i < geo["ni"] and 0 <= cell_j < geo["nj"] and bool(zone_dilated[cell_j, cell_i])
        peak_info = plan_info["peak"]
        zoning_ok = bool(peak_info["commercial"] and inside) if peak_info else None
        conf_cfg = cfg["confidence"]
        parcel_flag = (bool(winner and winner["score"] >= conf_cfg["parcel_ok"]
                            and winner["cells"] >= cfg["cluster_min_cells"]) if have_parcels else None)
        anchor = {"node_id": None, "lat": point["lat"], "lon": point["lon"],
                  "score": float(winner["score"]) if winner else 0.0, "basis": basis,
                  "source": EVIDENCE_ANCHOR_SOURCE, "coverage": float(coverage)}
        stability_levels = [(composite.get("stability") or {}).get("level"), (stability or {}).get("level")]
        confidence = classify_anchor_confidence(
            anchor, road_anchors, zoning_ok=zoning_ok, parcel_ok=parcel_flag, coverage=float(coverage),
            peak=peak_info, cluster=winner, stability_levels=stability_levels, cfg=cfg)
        for record in clusters:
            for private in ("_x", "_y", "_first", "_label"):
                record.pop(private)
        clean = all(v == 0 for v in (len(tally["errors"]), tally["skipped"], tally["timed_out"]))
        status = "ok" if (clean and region_kind == "peak_zone" and basis == "cluster" and coverage >= 1.0) else "partial"
        return finish(status=status, notes=notes, plan=plan_info, parcel=parcel_info, clusters=clusters,
                      evidence_anchor=anchor, confidence=confidence, stability=stability)
    except Exception as exc:  # the road result must survive whatever goes wrong here
        return finish(reason=f"{type(exc).__name__}: {' '.join(str(exc).split())[:160]}")


def get_fill_color(minutes: float, colors_config: Dict[str, str]) -> str:
    """Determine polygon fill colour based on travel-time bucket."""
    if minutes <= 10:
        return colors_config["step1"]
    if minutes <= 20:
        return colors_config["step2"]
    if minutes <= 30:
        return colors_config["step3"]
    return colors_config["step4"]


def get_border_color(original_marker_idx: Optional[int]) -> str:
    """Determine border colour from marker index."""
    if original_marker_idx is None:
        return "#3388ff"
    return HEX_COLORS[original_marker_idx % len(HEX_COLORS)]


def calculate_distance_meters(
    lat1: float, lon1: float, lat2: float, lon2: float
) -> float:
    """Haversine distance in metres."""
    R = 6371000.0
    lat1_rad, lon1_rad = radians(lat1), radians(lon1)
    lat2_rad, lon2_rad = radians(lat2), radians(lon2)
    dlat = lat2_rad - lat1_rad
    dlon = lon2_rad - lon1_rad
    a = sin(dlat / 2) ** 2 + cos(lat1_rad) * cos(lat2_rad) * sin(dlon / 2) ** 2
    c = 2 * atan2(sqrt(a), sqrt(1 - a))
    return R * c


def should_add_marker(
    new_lat: float,
    new_lon: float,
    last_click: Optional[Dict[str, Any]],
) -> bool:
    """
    Debounce logic — returns ``True`` when a new marker should be added.

    Pure function: caller supplies ``last_click`` instead of reading
    ``st.session_state`` directly.
    """
    if last_click is None:
        return True

    time_diff = time.time() - last_click["timestamp"]
    if time_diff < NETWORK_CONFIG["click_debounce_seconds"]:
        return False

    distance = calculate_distance_meters(
        last_click["lat"], last_click["lon"], new_lat, new_lon
    )
    if distance < NETWORK_CONFIG["click_distance_threshold_meters"]:
        return False

    return True


def calculate_intersection(
    features: List[Dict[str, Any]], num_active_markers: int
) -> Optional[Dict[str, Any]]:
    """Calculate the geometric intersection (CBD) of isochrones."""
    if num_active_markers < 2:
        return None

    polys_per_active_idx: Dict[int, Any] = {}
    for feat in features:
        active_idx: int = feat["properties"]["active_index"]
        geom = shape(feat["geometry"])
        if active_idx in polys_per_active_idx:
            polys_per_active_idx[active_idx] = polys_per_active_idx[active_idx].union(geom)
        else:
            polys_per_active_idx[active_idx] = geom

    if len(polys_per_active_idx) < num_active_markers:
        return None

    active_indices = sorted(polys_per_active_idx.keys())
    try:
        intersection_poly = polys_per_active_idx[active_indices[0]]
        for idx in active_indices[1:]:
            intersection_poly = intersection_poly.intersection(polys_per_active_idx[idx])
            if intersection_poly.is_empty:
                return None
        if intersection_poly.is_empty:
            return None
        return mapping(intersection_poly)
    except Exception:
        return None


def edge_scores_by_pair(
    scores: Dict[Tuple[Any, ...], float]
) -> Dict[Tuple[Any, Any], float]:
    """Collapse edge scores keyed ``(u, v)`` or ``(u, v, key)`` onto ``sorted((u, v))``.

    NetworkX returns 3-tuple keys for MultiGraph edge betweenness and credits
    only one of several parallel edges, so the pair value is the maximum over
    its keys. Looking such a dict up with a 2-tuple silently yields nothing.
    """
    pairs: Dict[Tuple[Any, Any], float] = {}
    for key, value in scores.items():
        pair = tuple(sorted(key[:2]))
        if value > pairs.get(pair, float("-inf")):
            pairs[pair] = value
    return pairs


def compute_golden_land_opportunities(
    graph: nx.MultiDiGraph,
    closeness_cent: Dict[Any, float],
    edge_betweenness_cent: Dict[Tuple[Any, Any], float],
    top_n: int = 10,
    min_spacing_m: Optional[float] = None,
) -> List[Dict[str, Any]]:
    """
    Rank candidate nodes for "golden land" discovery.

    Principle / Equation:
    score = 0.50*closeness_norm + 0.30*degree_norm + 0.20*(1-edge_betweenness_norm)

    Selection is greedy non-maximum suppression: a node is skipped when a
    higher-ranked pick lies within ``min_spacing_m`` (default from
    ``NETWORK_CONFIG``; ``0`` disables), so adjacent nodes of one junction
    cluster cannot fill the whole top-N.
    """
    if not closeness_cent:
        return []

    weights = NETWORK_CONFIG["golden_land_weights"]
    max_close = max(closeness_cent.values()) or 1.0

    degree_dict = dict(graph.degree())
    max_degree = max(degree_dict.values()) if degree_dict else 1
    if max_degree <= 0:
        max_degree = 1

    edge_betweenness_cent = edge_scores_by_pair(edge_betweenness_cent)
    max_bet = max(edge_betweenness_cent.values()) if edge_betweenness_cent else 1.0
    if max_bet <= 0:
        max_bet = 1.0

    # Precompute mean adjacent edge-betweenness per node once.
    # This avoids repeated ``graph.edges(node)`` scans for every node.
    node_edge_score_sum: Dict[Any, float] = {}
    node_edge_count: Dict[Any, int] = {}
    for u, v in graph.edges():
        bet_norm = edge_betweenness_cent.get(tuple(sorted((u, v))), 0.0) / max_bet

        node_edge_score_sum[u] = node_edge_score_sum.get(u, 0.0) + bet_norm
        node_edge_count[u] = node_edge_count.get(u, 0) + 1

        if u != v:
            node_edge_score_sum[v] = node_edge_score_sum.get(v, 0.0) + bet_norm
            node_edge_count[v] = node_edge_count.get(v, 0) + 1

    ranked: List[Dict[str, Any]] = []
    for node, data in graph.nodes(data=True):
        close_norm = closeness_cent.get(node, 0.0) / max_close
        degree_norm = degree_dict.get(node, 0) / max_degree

        edge_count = node_edge_count.get(node, 0)
        if edge_count > 0:
            edge_bet_norm = node_edge_score_sum[node] / edge_count
        else:
            edge_bet_norm = 0.0

        low_traffic_bonus = 1.0 - edge_bet_norm
        score = (
            weights["closeness"] * close_norm
            + weights["degree"] * degree_norm
            + weights["low_traffic_bonus"] * low_traffic_bonus
        )
        ranked.append(
            {
                "node_id": int(node) if isinstance(node, int) else str(node),
                "lat": data["y"],
                "lon": data["x"],
                "score": score,
                "closeness_norm": close_norm,
                "degree_norm": degree_norm,
                "low_traffic_bonus": low_traffic_bonus,
            }
        )

    ranked.sort(key=lambda x: x["score"], reverse=True)
    spacing = (
        NETWORK_CONFIG["golden_land_min_spacing_m"]
        if min_spacing_m is None else float(min_spacing_m)
    )
    if spacing <= 0:
        return ranked[:top_n]
    picked: List[Dict[str, Any]] = []
    for cand in ranked:
        if len(picked) >= top_n:
            break
        if all(
            calculate_distance_meters(cand["lat"], cand["lon"], p["lat"], p["lon"]) >= spacing
            for p in picked
        ):
            picked.append(cand)
    return picked


def approx_geom_area_km2(geojson_geom: Dict[str, Any]) -> Optional[float]:
    """พื้นที่โดยประมาณ (km²) ของ geometry ใน WGS84 — แม่นพอสำหรับแสดงผล."""
    try:
        geom = shape(geojson_geom)
        lat_c = geom.centroid.y
        return geom.area * 110.574 * 111.320 * cos(radians(lat_c))
    except Exception:
        return None


# ----------------------------------------------------- Rent Gradient Engine
# ทฤษฎี Bid-Rent (Alonso-Muth-Mills): มูลค่า/ค่าเช่าที่ดินลดลงตามระยะจาก CBD
#   R(d) = R₀ · e^(−λ·d)
#   λ    = อัตราการลดลงของค่าเช่า (rent gradient) ต่อ km
#   d½   = ln(2)/λ = ระยะที่ค่าเช่าลดลงครึ่งหนึ่ง (half-value distance)

def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Haversine distance in kilometres."""
    return calculate_distance_meters(lat1, lon1, lat2, lon2) / 1000.0


def predict_rent(distance_km: float, r0: float, lam: float) -> float:
    """Bid-rent prediction: R(d) = R₀ · e^(−λ·d)."""
    return r0 * exp(-lam * distance_km)


def rent_color_for_norm(norm: float) -> str:
    """Map normalized rent 0..1 (ต่ำ→สูง) onto the sequential ramp (อ่อน→เข้ม)."""
    norm = max(0.0, min(1.0, norm))
    idx = int(round(norm * (len(RENT_RAMP) - 1)))
    return RENT_RAMP[idx]


# Two-sided 95% Student-t critical values for small degrees of freedom.
_T_CRIT_975: Dict[int, float] = {
    1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447, 7: 2.365,
    8: 2.306, 9: 2.262, 10: 2.228, 11: 2.201, 12: 2.179, 13: 2.160, 14: 2.145,
    15: 2.131, 16: 2.120, 17: 2.110, 18: 2.101, 19: 2.093, 20: 2.086,
    25: 2.060, 30: 2.042, 40: 2.021, 60: 2.000, 120: 1.980,
}


def t_critical_95(dof: int) -> float:
    """Two-sided 95% t quantile; interpolates conservatively (next-lower df)."""
    if dof < 1:
        return float("inf")
    usable = [k for k in _T_CRIT_975 if k <= dof]
    return _T_CRIT_975[max(usable)] if dof <= 120 else 1.960


def fit_rent_gradient_from_samples(
    samples: List[Dict[str, Any]],
    anchor_lat: float,
    anchor_lon: float,
) -> Optional[Dict[str, Any]]:
    """
    Fit R(d) = R₀·e^(−λd) จากตัวอย่างราคาจริงด้วย log-linear OLS.

    ln(R) = ln(R₀) − λ·d  →  regression เส้นตรงบน (d, ln R)

    Returns ``{r0, lam, r2, n_samples, points}`` หรือ ``None``
    เมื่อข้อมูลไม่พอ (ต้องมี ≥ 2 จุดที่ระยะต่างกัน และราคา > 0).
    """
    pts: List[Tuple[float, float]] = []  # (distance_km, ln_rent)
    for s in samples:
        try:
            lat = float(s["lat"])
            lon = float(s["lon"])
            rent = float(s["rent"])
        except (KeyError, TypeError, ValueError):
            continue
        if rent <= 0:
            continue
        d = haversine_km(anchor_lat, anchor_lon, lat, lon)
        pts.append((d, log(rent)))

    if len(pts) < 2:
        return None

    n = len(pts)
    mean_x = sum(p[0] for p in pts) / n
    mean_y = sum(p[1] for p in pts) / n
    sxx = sum((p[0] - mean_x) ** 2 for p in pts)
    if sxx <= 1e-12:  # ทุกจุดระยะเท่ากัน — fit ไม่ได้
        return None
    sxy = sum((p[0] - mean_x) * (p[1] - mean_y) for p in pts)

    slope = sxy / sxx
    intercept = mean_y - slope * mean_x
    lam = -slope
    r0 = exp(intercept)

    ss_tot = sum((p[1] - mean_y) ** 2 for p in pts)
    ss_res = sum((p[1] - (intercept + slope * p[0])) ** 2 for p in pts)
    r2 = 1.0 - (ss_res / ss_tot) if ss_tot > 1e-12 else 1.0

    # Uncertainty of the slope. With n = 2 the line is exact (no residual degrees
    # of freedom), so R² = 1 carries no information and no interval exists.
    dof = n - 2
    adj_r2: Optional[float] = None
    lam_se: Optional[float] = None
    lam_ci95: Optional[Tuple[float, float]] = None
    half_dist_ci95: Optional[Tuple[float, float]] = None
    if dof > 0:
        if ss_tot > 1e-12:
            adj_r2 = 1.0 - (1.0 - r2) * (n - 1) / dof
        lam_se = sqrt(ss_res / dof / sxx)
        margin = t_critical_95(dof) * lam_se
        lam_ci95 = (lam - margin, lam + margin)
        # d½ = ln2/λ is only bounded when the whole interval stays positive.
        if lam_ci95[0] > RENT_CONFIG["min_lambda"]:
            half_dist_ci95 = (log(2.0) / lam_ci95[1], log(2.0) / lam_ci95[0])

    return {
        "r0": r0,
        "lam": lam,
        "r2": r2,
        "adj_r2": adj_r2,
        "lam_se": lam_se,
        "lam_ci95": lam_ci95,
        "half_dist_ci95": half_dist_ci95,
        "dof": dof,
        "low_confidence": n < RENT_CONFIG["min_reliable_samples"],
        "n_samples": n,
        "points": [{"d": p[0], "rent": exp(p[1])} for p in pts],
    }


def resolve_cbd_anchor(
    intersection_data: Optional[Dict[str, Any]],
    network_data: Optional[Dict[str, Any]],
    isochrone_data: Optional[Dict[str, Any]],
    markers: List[Dict[str, Any]],
    automated_anchor: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """
    หาจุดยึด CBD สำหรับ Rent Gradient ตามลำดับความน่าเชื่อถือ:
    0) Automated CBD Anchor ที่ผู้ใช้สั่งค้นหา
    1) centroid ของ CBD Zone (จุดตัด isochrone)
    2) Integration Center จาก Network Analysis
    3) centroid ของ Travel Areas ทั้งหมด
    4) ค่าเฉลี่ยตำแหน่งหมุดที่ active
    """
    # An explicitly discovered road anchor takes precedence over polygon centroids.
    if automated_anchor:
        return dict(automated_anchor["anchor"])

    # 1) CBD intersection centroid
    try:
        feats = (intersection_data or {}).get("features") or []
        if feats:
            geom = shape(feats[0]["geometry"])
            c = geom.centroid
            return {"lat": c.y, "lon": c.x, "source": "CBD Zone (จุดตัด Isochrone)"}
    except Exception:
        pass

    # 2) Network Integration Center
    try:
        top = (network_data or {}).get("top_node")
        if top and top.get("score", -1) >= 0:
            return {"lat": top["lat"], "lon": top["lon"], "source": "Integration Center (Network)"}
    except Exception:
        pass

    # 3) Union centroid of all isochrones
    try:
        feats = (isochrone_data or {}).get("features") or []
        if feats:
            combined = unary_union([shape(f["geometry"]) for f in feats])
            c = combined.centroid
            return {"lat": c.y, "lon": c.x, "source": "จุดกึ่งกลาง Travel Areas"}
    except Exception:
        pass

    # 4) Mean of active markers
    active = [m for m in markers if m.get("active", True)]
    if active:
        lat = sum(m["lat"] for m in active) / len(active)
        lon = sum(m["lng"] for m in active) / len(active)
        return {"lat": lat, "lon": lon, "source": "ค่าเฉลี่ยตำแหน่งหมุด"}

    return None


def isochrone_max_distance_km(
    anchor_lat: float,
    anchor_lon: float,
    isochrone_data: Optional[Dict[str, Any]],
) -> float:
    """ระยะไกลสุดจากจุดยึดถึงขอบ Travel Areas (ใช้มุม bounding box ของแต่ละ feature)."""
    d_max = 0.0
    feats = (isochrone_data or {}).get("features") or []
    for f in feats:
        try:
            minx, miny, maxx, maxy = shape(f["geometry"]).bounds
        except Exception:
            continue
        for lon, lat in ((minx, miny), (minx, maxy), (maxx, miny), (maxx, maxy)):
            d = haversine_km(anchor_lat, anchor_lon, lat, lon)
            d_max = max(d_max, d)
    if d_max <= 0:
        d_max = RENT_CONFIG["default_d_max_km"]
    return max(d_max, RENT_CONFIG["min_d_max_km"])


def _geodesic_circle_coords(
    lat: float, lon: float, radius_km: float, n_points: int = 72
) -> List[List[float]]:
    """พิกัดวงกลมโดยประมาณรอบจุดศูนย์กลาง (แก้ความบิดเบี้ยวของลองจิจูดตามละติจูด)."""
    dlat = radius_km / 110.574
    dlon = radius_km / (111.320 * max(cos(radians(lat)), 1e-6))
    coords = []
    for i in range(n_points + 1):
        t = 2.0 * pi * i / n_points
        coords.append([lon + dlon * cos(t), lat + dlat * sin(t)])
    return coords


def build_rent_rings_geojson(
    anchor_lat: float,
    anchor_lon: float,
    d_max_km: float,
    r0: float,
    lam: float,
    is_index: bool,
    unit_label: str,
) -> Dict[str, Any]:
    """สร้างวงแหวนราคา (annuli) รอบ CBD — สีตามค่าเช่าคาดการณ์ที่กึ่งกลางวง."""
    n_rings = RENT_CONFIG["num_rings"]
    step = d_max_km / n_rings

    # ช่วงค่าเช่าทั้งหมดสำหรับ normalize สี (รองรับกรณี λ < 0 ที่ curve กลับทิศ)
    r_at_0 = predict_rent(0.0, r0, lam)
    r_at_max = predict_rent(d_max_km, r0, lam)
    r_lo, r_hi = min(r_at_0, r_at_max), max(r_at_0, r_at_max)
    r_span = (r_hi - r_lo) or 1.0

    features: List[Dict[str, Any]] = []
    for i in range(1, n_rings + 1):
        r_in = step * (i - 1)
        r_out = step * i
        rent_mid = predict_rent((r_in + r_out) / 2.0, r0, lam)
        norm = (rent_mid - r_lo) / r_span

        outer = _geodesic_circle_coords(anchor_lat, anchor_lon, r_out)
        rings = [outer]
        if r_in > 0:
            rings.append(list(reversed(_geodesic_circle_coords(anchor_lat, anchor_lon, r_in))))

        if is_index:
            rent_label = f"ดัชนี ≈ {rent_mid:.1f} / 100"
        else:
            rent_label = f"≈ {rent_mid:,.0f} {unit_label}"

        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "Polygon", "coordinates": rings},
                "properties": {
                    "band": f"{r_in:.1f} – {r_out:.1f} km",
                    "rent_mid": round(rent_mid, 2),
                    "rent_label": rent_label,
                    "color": rent_color_for_norm(norm),
                },
            }
        )

    return {"type": "FeatureCollection", "features": features}


def build_rent_nodes_geojson(
    nodes_geojson: Optional[Dict[str, Any]],
    anchor_lat: float,
    anchor_lon: float,
    r0: float,
    lam: float,
    d_max_km: float,
) -> Optional[Dict[str, Any]]:
    """ทาสีโหนดถนน (จาก Network Analysis) ตามค่าเช่าคาดการณ์ → Rent Heat."""
    feats = (nodes_geojson or {}).get("features") or []
    if not feats:
        return None

    r_at_0 = predict_rent(0.0, r0, lam)
    r_at_max = predict_rent(d_max_km, r0, lam)
    r_lo, r_hi = min(r_at_0, r_at_max), max(r_at_0, r_at_max)
    r_span = (r_hi - r_lo) or 1.0

    out_features: List[Dict[str, Any]] = []
    for f in feats:
        try:
            lon, lat = f["geometry"]["coordinates"]
        except (KeyError, ValueError, TypeError):
            continue
        rent = predict_rent(haversine_km(anchor_lat, anchor_lon, lat, lon), r0, lam)
        norm = (rent - r_lo) / r_span
        out_features.append(
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [lon, lat]},
                "properties": {
                    "type": "rent_node",
                    "rent": round(rent, 2),
                    "color": rent_color_for_norm(norm),
                },
            }
        )
    return {"type": "FeatureCollection", "features": out_features}


# ------------------------------------------------- Ring Report (สรุปรายวงแหวน)

def _ring_index_for_distance(
    d_km: float, step_km: float, n_rings: int
) -> Optional[int]:
    """คืน index วงแหวน (0-based) ของระยะ d_km — ``None`` เมื่ออยู่นอกวงนอกสุด."""
    if step_km <= 0 or d_km < 0:
        return None
    idx = int(d_km / step_km)
    if idx >= n_rings:
        # จุดที่อยู่บนขอบนอกสุดพอดีนับเป็นวงสุดท้าย
        return n_rings - 1 if d_km <= step_km * n_rings + 1e-9 else None
    return idx


def ring_coverage_areas_km2(
    coverage_geojson: Optional[Dict[str, Any]],
    anchor_lat: float,
    anchor_lon: float,
    step_km: float,
    n_rings: int,
) -> Optional[List[float]]:
    """พื้นที่ของ (วงแหวน ∩ พื้นที่ที่ดาวน์โหลดถนนจริง) ต่อวง หน่วย km² (pure).

    โหนด Network มีเฉพาะในพื้นที่ที่ดึงข้อมูลถนน (union ของ isochrone) จึงต้องหาร
    ความหนาแน่นด้วยพื้นที่ที่ครอบจริง ไม่ใช่พื้นที่วงแหวนเต็ม คำนวณในพิกัดเมตร
    (azimuthal equidistant รอบ anchor). คืน ``None`` เมื่อไม่มี/อ่านพื้นที่ไม่ได้.
    """
    if not coverage_geojson or step_km <= 0 or n_rings <= 0:
        return None
    try:
        from shapely.geometry import Point
        from shapely.ops import transform

        projection = _anchor_projection(anchor_lat, anchor_lon)
        geom = transform(
            lambda x, y, z=None: projection.transform(x, y), shape(coverage_geojson)
        )
        if geom.is_empty:
            return None
        if not geom.is_valid:
            geom = geom.buffer(0)
        origin = Point(0.0, 0.0)
        areas: List[float] = []
        for i in range(n_rings):
            outer = origin.buffer(step_km * (i + 1) * 1000.0, quad_segs=64)
            inner = origin.buffer(step_km * i * 1000.0, quad_segs=64) if i else None
            band = outer.difference(inner) if inner is not None else outer
            areas.append(float(band.intersection(geom).area) / 1e6)
        return areas
    except Exception:
        return None


def count_nodes_per_ring(
    nodes_geojson: Optional[Dict[str, Any]],
    anchor_lat: float,
    anchor_lon: float,
    step_km: float,
    n_rings: int,
) -> Tuple[List[int], List[List[float]], int]:
    """นับโหนดถนน (จาก Network Analysis) ต่อวงแหวน Rent Gradient.

    Returns:
        ``(counts, closeness_per_ring, outside_count)`` —
        โหนดที่ไกลกว่าวงนอกสุด (เช่น anchor เลื่อนหลังคำนวณ network)
        นับรวมใน ``outside_count`` เพื่อให้ยอดรวมครบทุกโหนด
    """
    counts: List[int] = [0] * n_rings
    closeness_per_ring: List[List[float]] = [[] for _ in range(n_rings)]
    outside = 0
    for f in ((nodes_geojson or {}).get("features") or []):
        try:
            lon, lat = f["geometry"]["coordinates"]
        except (KeyError, ValueError, TypeError):
            continue
        idx = _ring_index_for_distance(
            haversine_km(anchor_lat, anchor_lon, lat, lon), step_km, n_rings
        )
        if idx is None:
            outside += 1
            continue
        counts[idx] += 1
        closeness_per_ring[idx].append(
            float((f.get("properties") or {}).get("closeness", 0.0))
        )
    return counts, closeness_per_ring, outside


def build_ring_report(
    rent_data: Optional[Dict[str, Any]],
    network_data: Optional[Dict[str, Any]],
    samples: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """สรุปรายวงแหวน Rent Gradient สำหรับ scan หาโซนซื้อที่ดิน (pure).

    1 แถว = 1 วง: ช่วงระยะ, พื้นที่, ค่าเช่าคาดการณ์ และเมื่อมีผล Network
    Analysis จะเติมจำนวนโหนด, ความหนาแน่น, Closeness, Golden Spots และ
    Value Gap (= Closeness เฉลี่ย − ราคา normalize) ตามนิยามเดียวกับ
    ตาราง Golden Spots — ค่าบวกมาก = เข้าถึงง่ายแต่ราคาคาดการณ์ยังต่ำ
    """
    if not rent_data or "error" in rent_data:
        return []
    ring_feats = (rent_data.get("rings_geojson") or {}).get("features") or []
    if not ring_feats:
        return []

    model = rent_data["model"]
    anchor = rent_data["anchor"]
    # Value Gap compares network closeness with R(d)/R0. In index mode R(d)/R0
    # is an assumed decay (1/4 at the edge), so the gap would only echo that
    # assumption; it is reported only when the rent model is fitted to data.
    show_gap = not model.get("is_index")
    n_rings = len(ring_feats)
    d_max = model["d_max_km"]
    step = d_max / n_rings
    r0 = float(model.get("r0") or 0.0)

    nodes_fc = None
    if network_data and "error" not in network_data:
        nodes_fc = network_data.get("nodes")
    has_net = bool((nodes_fc or {}).get("features"))

    counts, closeness_per_ring, outside_nodes = count_nodes_per_ring(
        nodes_fc, anchor["lat"], anchor["lon"], step, n_rings
    )
    total_nodes = sum(counts) + outside_nodes
    coverage_areas = (
        ring_coverage_areas_km2(
            (network_data or {}).get("coverage_geojson"),
            anchor["lat"], anchor["lon"], step, n_rings,
        )
        if has_net else None
    )

    golden_per_ring: List[List[int]] = [[] for _ in range(n_rings)]
    golden_spots = (network_data or {}).get("golden_spots") or []
    for rank, spot in enumerate(golden_spots, start=1):
        idx = _ring_index_for_distance(
            haversine_km(anchor["lat"], anchor["lon"], spot["lat"], spot["lon"]),
            step,
            n_rings,
        )
        if idx is not None:
            golden_per_ring[idx].append(rank)

    samples_per_ring: List[int] = [0] * n_rings
    for s in samples or []:
        try:
            d = haversine_km(
                anchor["lat"], anchor["lon"], float(s["lat"]), float(s["lon"])
            )
        except (KeyError, TypeError, ValueError):
            continue
        idx = _ring_index_for_distance(d, step, n_rings)
        if idx is not None:
            samples_per_ring[idx] += 1

    rows: List[Dict[str, Any]] = []
    for i, feat in enumerate(ring_feats):
        props = feat.get("properties") or {}
        r_in, r_out = step * i, step * (i + 1)
        area_km2 = pi * (r_out ** 2 - r_in ** 2)
        row: Dict[str, Any] = {
            "วง": i + 1,
            "ช่วงระยะจาก CBD": props.get("band", f"{r_in:.1f} – {r_out:.1f} km"),
            "พื้นที่ (km²)": round(area_km2, 2),
            "ค่าเช่าคาดการณ์": props.get(
                "rent_label",
                format_rent_value(
                    predict_rent((r_in + r_out) / 2.0, r0, model["lam"]), model
                ),
            ),
        }
        if has_net:
            n_in = counts[i]
            cl = closeness_per_ring[i]
            cl_mean = (sum(cl) / len(cl)) if cl else 0.0
            rent_mid = float(props.get("rent_mid", 0.0))
            rent_norm = max(0.0, min(1.0, rent_mid / r0)) if r0 > 0 else 0.0
            row["โหนด Network"] = n_in
            row["% โหนด"] = (
                round(100.0 * n_in / total_nodes, 1) if total_nodes else 0.0
            )
            if coverage_areas is not None:
                covered = coverage_areas[i]
                row["พื้นที่ครอบคลุม (km²)"] = round(covered, 2)
                # หารด้วยพื้นที่ที่มีข้อมูลถนนจริง (ไม่ใช่วงแหวนเต็ม) กันค่าต่ำเกินจริงในวงนอก
                density_area = covered if covered > 1e-6 else area_km2
            else:
                density_area = area_km2
            row["โหนด/km²"] = round(n_in / density_area, 1) if density_area > 0 else 0.0
            row["Closeness เฉลี่ย"] = round(cl_mean, 3)
            row["Closeness สูงสุด"] = round(max(cl), 3) if cl else 0.0
            row["Golden Spots"] = ", ".join(map(str, golden_per_ring[i])) or "—"
            if show_gap:
                row["Value Gap"] = round(cl_mean - rent_norm, 3)
        row["ตัวอย่างราคา"] = samples_per_ring[i]
        rows.append(row)

    # โหนดนอกวงนอกสุด — แสดงเป็นแถวสุดท้ายให้ยอดรวมโหนดครบ
    if has_net and outside_nodes > 0:
        rows.append(
            {
                "วง": "—",
                "ช่วงระยะจาก CBD": f"> {d_max:.1f} km (นอกวงนอกสุด)",
                "พื้นที่ (km²)": None,
                **({"พื้นที่ครอบคลุม (km²)": None} if coverage_areas is not None else {}),
                "ค่าเช่าคาดการณ์": "นอกขอบเขตโมเดล",
                "โหนด Network": outside_nodes,
                "% โหนด": (
                    round(100.0 * outside_nodes / total_nodes, 1)
                    if total_nodes
                    else 0.0
                ),
                "โหนด/km²": None,
                "Closeness เฉลี่ย": None,
                "Closeness สูงสุด": None,
                "Golden Spots": "—",
                **({"Value Gap": None} if show_gap else {}),
                "ตัวอย่างราคา": 0,
            }
        )
    return rows


def compute_rent_gradient_data(
    intersection_data: Optional[Dict[str, Any]],
    network_data: Optional[Dict[str, Any]],
    isochrone_data: Optional[Dict[str, Any]],
    markers: List[Dict[str, Any]],
    samples: List[Dict[str, Any]],
    unit_label: str,
    automated_anchor: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    คำนวณ Rent Gradient ทั้งชุด (pure, JSON-serializable):
    anchor → fit/default model → rings + curve + rent heat.
    """
    anchor = resolve_cbd_anchor(
        intersection_data, network_data, isochrone_data, markers, automated_anchor
    )
    if anchor is None:
        return {"error": "ไม่พบจุดยึด CBD — กรุณาปักหมุดและคำนวณ Isochrone ก่อน"}

    d_max = isochrone_max_distance_km(anchor["lat"], anchor["lon"], isochrone_data)
    if automated_anchor and not isochrone_data:
        d_max = automated_anchor["study_radius_m"] / 1000.0

    fit = fit_rent_gradient_from_samples(samples, anchor["lat"], anchor["lon"])
    if fit is not None:
        r0, lam, r2 = fit["r0"], fit["lam"], fit["r2"]
        n_samples = fit["n_samples"]
        fit_stats = {
            key: fit[key]
            for key in ("adj_r2", "lam_se", "lam_ci95", "half_dist_ci95",
                        "dof", "low_confidence")
        }
        is_index = False
        samples_scatter = fit["points"]
        # ขยายขอบเขตกราฟ/วงแหวนให้คลุมตัวอย่างที่อยู่ไกลกว่า Travel Areas
        d_max = max(d_max, max((p["d"] for p in samples_scatter), default=0.0) * 1.05)
    else:
        r0 = RENT_CONFIG["base_index"]
        lam = log(RENT_CONFIG["edge_decay_ratio"]) / d_max
        r2 = None
        n_samples = 0
        fit_stats = {
            "adj_r2": None, "lam_se": None, "lam_ci95": None,
            "half_dist_ci95": None, "dof": 0, "low_confidence": False,
        }
        is_index = True
        samples_scatter = []

    inverted = lam < 0
    abs_lam = abs(lam)
    half_dist = (log(2.0) / abs_lam) if abs_lam > RENT_CONFIG["min_lambda"] else None

    # เส้นโค้ง Bid-Rent สำหรับกราฟ
    n_pts = RENT_CONFIG["curve_points"]
    curve_d = [d_max * i / (n_pts - 1) for i in range(n_pts)]
    curve_r = [predict_rent(d, r0, lam) for d in curve_d]

    rings = build_rent_rings_geojson(
        anchor["lat"], anchor["lon"], d_max, r0, lam, is_index, unit_label
    )
    rent_nodes = build_rent_nodes_geojson(
        (network_data or {}).get("nodes"), anchor["lat"], anchor["lon"], r0, lam, d_max
    )

    # เติมจำนวนโหนด Network ต่อวงลง tooltip ของ Rent Gradient Rings บนแผนที่
    nodes_fc = (network_data or {}).get("nodes") if network_data and "error" not in network_data else None
    ring_feats = rings["features"]
    n_rings = len(ring_feats)
    if nodes_fc and nodes_fc.get("features") and n_rings > 0:
        ring_step = d_max / n_rings
        node_counts, _closeness, _outside = count_nodes_per_ring(
            nodes_fc, anchor["lat"], anchor["lon"], ring_step, n_rings
        )
        for feat, count in zip(ring_feats, node_counts):
            feat["properties"]["nodes_label"] = f"{count:,} โหนด"
    else:
        for feat in ring_feats:
            feat["properties"]["nodes_label"] = "—"

    return {
        "anchor": anchor,
        "model": {
            "r0": r0,
            "lam": lam,
            "r2": r2,
            **fit_stats,
            "n_samples": n_samples,
            "is_index": is_index,
            "inverted": inverted,
            "unit": unit_label,
            "d_max_km": d_max,
            "half_dist_km": half_dist,
        },
        "curve": {"d": curve_d, "r": curve_r},
        "samples_scatter": samples_scatter,
        "rings_geojson": rings,
        "rent_nodes_geojson": rent_nodes,
    }


def format_rent_value(value: float, model: Dict[str, Any]) -> str:
    """แสดงผลราคา: โหมดดัชนี → 'ดัชนี xx/100', โหมดราคาจริง → 'x,xxx หน่วย'."""
    if model.get("is_index"):
        return f"ดัชนี {value:.1f}/100"
    return f"{value:,.0f} {model.get('unit', '')}".strip()


def _fit_dof(model: Dict[str, Any]) -> int:
    """Residual degrees of freedom; derived for results saved before ``dof`` existed."""
    return int(model.get("dof", model.get("n_samples", 0) - 2))


def fit_quality_label(model: Dict[str, Any]) -> str:
    """ป้ายคุณภาพการ fit ที่ระบุจำนวนตัวอย่างเสมอ (ไม่ใช้คำว่า calibrated เปล่า ๆ)."""
    if model.get("is_index") or model.get("r2") is None:
        return "โหมดดัชนี — ยังไม่ calibrate จากราคาจริง"
    n = model.get("n_samples", 0)
    parts = [f"n={n}"]
    if _fit_dof(model) > 0:
        parts.append(f"R²={model['r2']:.3f}")
        if model.get("adj_r2") is not None:
            parts.append(f"adj-R²={model['adj_r2']:.3f}")
    else:
        parts.append("R² ไม่มีความหมาย (2 จุดผ่านเส้นตรงได้พอดี)")
    return "calibrated (" + ", ".join(parts) + ")"


def fit_quality_warning(model: Dict[str, Any]) -> Optional[str]:
    """ข้อความเตือนเมื่อการ fit ยังไม่น่าเชื่อถือ — ``None`` เมื่อไม่มีประเด็น."""
    if model.get("is_index") or model.get("r2") is None:
        return None
    need = RENT_CONFIG["min_reliable_samples"]
    low = model.get("low_confidence")
    if low is None:  # results saved before the flag existed
        low = model.get("n_samples", 0) < need
    if low:
        return (
            f"ตัวอย่าง {model.get('n_samples', 0)} จุด น้อยกว่า {need} จุด — "
            "λ และ d½ ยังไม่น่าเชื่อถือ (2 จุดจะได้ R² = 1 เสมอ) ควรเพิ่มตัวอย่างก่อนใช้ตัดสินใจ"
        )
    ci = model.get("lam_ci95")
    if ci and ci[0] <= 0 <= ci[1]:
        return "ช่วงเชื่อมั่น 95% ของ λ คร่อมศูนย์ — ข้อมูลยังแยกไม่ออกว่าราคาลดลงตามระยะจริงหรือไม่"
    return None


def fit_interval_text(model: Dict[str, Any]) -> Optional[str]:
    """ช่วงเชื่อมั่น 95% ของ λ และ d½ เป็นข้อความ (``None`` เมื่อไม่มีองศาอิสระ)."""
    ci = model.get("lam_ci95")
    if not ci:
        return None
    text = f"λ 95% CI [{ci[0]:.4f}, {ci[1]:.4f}]"
    half_ci = model.get("half_dist_ci95")
    if half_ci:
        text += f" · d½ 95% CI [{half_ci[0]:.2f}, {half_ci[1]:.2f}] km"
    else:
        text += " · d½ ไม่มีขอบเขต (CI ของ λ รวมศูนย์)"
    return text


# ------------------------------------------------------------------ API calls
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


# -------------------------------------------------------------- Disk caching
def get_cache_key(polygon_wkt_str: str, network_type: str) -> str:
    """Generate a stable cache key from polygon bounds + network type."""
    polygon = wkt.loads(polygon_wkt_str)
    bounds = polygon.bounds  # (minx, miny, maxx, maxy)
    rounded_bounds = tuple(round(b, 3) for b in bounds)
    key_str = f"{rounded_bounds}_{network_type}"
    return hashlib.md5(key_str.encode()).hexdigest()


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


def _sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _build_bundle_manifest() -> Dict[str, Any]:
    return {
        "bundle_version": BUNDLE_VERSION,
        "app_name": "Rent_Gradient",
        "app_version": "streamlit-monolith",
        "config_schema_version": CONFIG_SCHEMA_VERSION,
        "cache_format_version": CACHE_FORMAT_VERSION,
        "created_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "platform_info": {"python": os.sys.version.split()[0], "os": os.name},
        "import_policy": {"mode": "fallback"},
    }


def export_bundle_zip() -> bytes:
    """Export all-in-one bundle.zip with separated config + cache files."""
    config_bytes = StateManager.export_config().encode("utf-8")
    cache_bytes = export_cache_as_zip() or b""
    manifest = _build_bundle_manifest()
    manifest["cache_present"] = bool(cache_bytes)
    manifest["integrity_checksums"] = {
        "config/config.json": _sha256_bytes(config_bytes),
        "cache/cache.zip": _sha256_bytes(cache_bytes),
    }
    manifest_bytes = json.dumps(manifest, indent=2, ensure_ascii=False).encode("utf-8")
    checksums = [
        f"{_sha256_bytes(manifest_bytes)}  manifest.json",
        f"{_sha256_bytes(config_bytes)}  config/config.json",
        f"{_sha256_bytes(cache_bytes)}  cache/cache.zip",
    ]
    checksum_bytes = ("\n".join(checksums) + "\n").encode("utf-8")
    readme_bytes = (
        "Rent_Gradient bundle.zip\n"
        "- manifest.json: compatibility & policy\n"
        "- config/config.json: user settings + precomputed results\n"
        "- cache/cache.zip: OSM graph cache archive\n"
    ).encode("utf-8")

    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", manifest_bytes)
        zf.writestr("config/config.json", config_bytes)
        zf.writestr("cache/cache.zip", cache_bytes)
        zf.writestr("checksums.sha256", checksum_bytes)
        zf.writestr("README.txt", readme_bytes)
    return out.getvalue()


def import_bundle_zip(bundle_bytes: bytes) -> Dict[str, Any]:
    """Import bundle.zip with validation and fallback policy."""
    result = {"success": False, "config_loaded": False, "cache_loaded": False, "warnings": [], "errors": []}
    try:
        with zipfile.ZipFile(io.BytesIO(bundle_bytes), "r") as zf:
            required = {"manifest.json", "config/config.json", "cache/cache.zip", "checksums.sha256"}
            names = set(zf.namelist())
            missing = required - names
            if missing:
                result["errors"].append(f"ไฟล์ไม่ครบใน bundle: {', '.join(sorted(missing))}")
                return result

            manifest = json.loads(zf.read("manifest.json"))
            if manifest.get("bundle_version") != BUNDLE_VERSION:
                result["errors"].append("bundle_version ไม่รองรับ")
                return result
            if manifest.get("config_schema_version") != CONFIG_SCHEMA_VERSION:
                result["errors"].append("config schema ไม่เข้ากัน")
                return result

            config_bytes = zf.read("config/config.json")
            cache_bytes = zf.read("cache/cache.zip")
            if len(cache_bytes) > MAX_CACHE_ENTRY_BYTES:
                result["warnings"].append("cache ใหญ่เกินกำหนด ระบบจะโหลดเฉพาะ config")
                cache_bytes = b""

            declared = manifest.get("integrity_checksums", {})
            if declared.get("config/config.json") != _sha256_bytes(config_bytes):
                result["errors"].append("checksum config ไม่ถูกต้อง")
                return result
            if declared.get("cache/cache.zip") != _sha256_bytes(cache_bytes if cache_bytes else b""):
                result["warnings"].append("checksum cache ไม่ถูกต้อง โหลดเฉพาะ config")
                cache_bytes = b""

            StateManager.import_config(json.loads(config_bytes.decode("utf-8")))
            result["config_loaded"] = True
            if cache_bytes:
                cache_result = import_cache_from_zip(cache_bytes)
                if cache_result.get("success"):
                    result["cache_loaded"] = True
                else:
                    result["warnings"].append("cache ใช้งานไม่ได้ โหลดเฉพาะ config")
            result["success"] = result["config_loaded"]
    except Exception as e:
        result["errors"].append(f"นำเข้า bundle ล้มเหลว: {str(e)}")
    return result



def download_github_bundle() -> Tuple[Optional[bytes], Optional[str]]:
    """Download fixed-source bundle ZIP from GitHub."""
    try:
        response = requests.get(GITHUB_BUNDLE_URL, timeout=TIMEOUT_GITHUB_DOWNLOAD)
        response.raise_for_status()
        return response.content, None
    except requests.RequestException as e:
        return None, f"ดาวน์โหลด Bundle จาก GitHub ไม่สำเร็จ: {str(e)}"


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


def compute_weighted_closeness(
    G_undir: nx.MultiGraph,
) -> Tuple[Dict[Any, float], str]:
    """
    Weighted closeness centrality สำหรับหา CBD node (Network 1-Median).

    หลักการ / สมการ:
        v* = argmin_v Σ_u d_len(v,u)  ⟺  argmax C(v) = (N−1) / Σ_u d_len(v,u)
        d_len = shortest path ถ่วงน้ำหนักด้วยความยาวถนนจริง (เมตร)

    ความเสถียร: คำนวณเฉพาะ Largest Connected Component (LCC) —
    โหนดนอก LCC ได้ค่า 0 จึงไม่มีสิทธิ์เป็น top node — และใช้ seed คงที่
    ทำให้ผลซ้ำได้ทุกครั้ง

    ความเร็ว:
      - N ≤ closeness_exact_threshold → exact ด้วย scipy.sparse.csgraph.dijkstra
      - N มากกว่า → Eppstein–Wang pivot sampling (k pivots, seed=42):
            Ĉ(v) = k / Σ_{p∈pivots} d_len(v,p)   (error ~ O(1/√k))
      - ไม่มี scipy → fallback nx.closeness_centrality(distance="length")

    Returns:
        ``(closeness_dict, method)`` โดย method ∈
        {"exact-scipy", "pivot-approx", "networkx-fallback", "trivial"}
    """
    closeness: Dict[Any, float] = {node: 0.0 for node in G_undir.nodes}
    if len(G_undir) < 2:
        return closeness, "trivial"

    lcc_nodes = max(nx.connected_components(G_undir), key=len)
    n = len(lcc_nodes)
    if n < 2:
        return closeness, "trivial"
    G_lcc = G_undir.subgraph(lcc_nodes)

    if not HAS_SCIPY:
        closeness.update(nx.closeness_centrality(G_lcc, distance="length"))
        return closeness, "networkx-fallback"

    # sparse adjacency (min length เมื่อมี parallel/reverse edges) — ตัวสร้างเดียวกับ anchor search
    nodelist = list(G_lcc.nodes)
    csr = _collapsed_csr(G_lcc, nodelist, default_length=1.0)

    if n <= NETWORK_CONFIG["closeness_exact_threshold"]:
        # all-pairs ที่ n <= 3000 (<= ~72 MB); แถวต่อแถวผ่านตัวช่วยเดียวกับ anchor search
        sums = np.empty(n)
        for part, rows_d in _dijkstra_batches(csr, np.arange(n)):
            sums[part] = rows_d.sum(axis=1)
        k_eff = n - 1
        method = "exact-scipy"
    else:
        k = min(NETWORK_CONFIG["closeness_k_pivots"], n)
        rng = np.random.default_rng(42)
        pivots = rng.choice(n, size=k, replace=False)
        sums = np.zeros(n)
        for _part, rows_d in _dijkstra_batches(csr, pivots):
            sums += rows_d.sum(axis=0)
        k_eff = k
        method = "pivot-approx"

    with np.errstate(divide="ignore", invalid="ignore"):
        scores = np.where(np.isfinite(sums) & (sums > 0), k_eff / sums, 0.0)
    for i, node in enumerate(nodelist):
        closeness[node] = float(scores[i])
    return closeness, method


def _compute_centrality_impl(
    polygon_wkt_str: str, network_type: str = "drive"
) -> Dict[str, Any]:
    """
    **Pure** centrality computation — no Streamlit calls.

    Returns a result dict with keys:
    ``edges``, ``nodes``, ``top_node``, ``stats``  — or  ``error``.
    """
    G, was_cached, error = _fetch_osm_graph(polygon_wkt_str, network_type)
    if error:
        return {"error": error}

    if G is None or len(G.nodes) < 2:
        return {
            "error": (
                "Not enough nodes found in the area. "
                "Try a larger region or check if OSM data is available."
            )
        }

    node_count = len(G.nodes)
    is_large_graph = node_count > NETWORK_CONFIG["large_graph_threshold"]

    G_undir = G.to_undirected()

    # Closeness centrality — weighted 1-median บน LCC (แม่น/เสถียร/เร็ว)
    closeness_cent, closeness_method = compute_weighted_closeness(G_undir)
    max_close = max(closeness_cent.values()) if closeness_cent else 1.0

    # Betweenness centrality (on undirected projection)
    # กราฟใหญ่: ประมาณค่าด้วย k-source sampling (เร็วขึ้นหลายสิบเท่า,
    # อันดับความสำคัญของถนนแทบไม่เปลี่ยน) — seed คงที่เพื่อผลซ้ำได้
    if is_large_graph:
        k_samples = min(NETWORK_CONFIG["betweenness_k_samples"], node_count)
        betweenness_cent: Dict[Any, float] = nx.edge_betweenness_centrality(
            G_undir, k=k_samples, weight="length", seed=42
        )
    else:
        betweenness_cent = nx.edge_betweenness_centrality(G_undir, weight="length")
    # MultiGraph results are keyed (u, v, key); the lookups below use (u, v).
    betweenness_cent = edge_scores_by_pair(betweenness_cent)
    max_bet = max(betweenness_cent.values()) if betweenness_cent else 1.0

    # Public colormap registry (Matplotlib >= 3.5).
    # matplotlib.cm.get_cmap was removed in newer Matplotlib releases.
    cmap_bet = matplotlib.colormaps["plasma"]

    # ---- Build edge GeoJSON features ----
    edges_geojson: List[Dict[str, Any]] = []
    for u, v, _k, data in G.edges(keys=True, data=True):
        score = betweenness_cent.get(tuple(sorted((u, v))), 0.0)
        norm_score = score / max_bet if max_bet > 0 else 0.0

        if "geometry" in data:
            geom = mapping(data["geometry"])
        else:
            geom = {
                "type": "LineString",
                "coordinates": [
                    [G.nodes[u]["x"], G.nodes[u]["y"]],
                    [G.nodes[v]["x"], G.nodes[v]["y"]],
                ],
            }

        edges_geojson.append(
            {
                "type": "Feature",
                "geometry": geom,
                "properties": {
                    "type": "road",
                    "betweenness": norm_score,
                    "color": colors.to_hex(cmap_bet(norm_score)),
                    "stroke_weight": (
                        NETWORK_CONFIG["edge_weight_base"]
                        + norm_score * NETWORK_CONFIG["edge_weight_multiplier"]
                    ),
                },
            }
        )

    # ---- Build node GeoJSON features ----
    nodes_geojson: List[Dict[str, Any]] = []
    top_node_data: Dict[str, Any] = {"score": -1.0, "lat": 0.0, "lon": 0.0}

    for node, data in G.nodes(data=True):
        score = closeness_cent.get(node, 0.0)
        norm_score = score / max_close if max_close > 0 else 0.0

        if score > top_node_data["score"]:
            top_node_data = {"lat": data["y"], "lon": data["x"], "score": score}

        if norm_score > NETWORK_CONFIG["min_closeness_threshold"]:
            nodes_geojson.append(
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "Point",
                        "coordinates": [data["x"], data["y"]],
                    },
                    "properties": {
                        "type": "intersection",
                        "closeness": norm_score,
                        "color": "#000000",
                        "radius": 2 + norm_score * 6,
                    },
                }
            )

    # ---- Golden land opportunity ranking ----
    golden_spots = compute_golden_land_opportunities(
        G,
        closeness_cent,
        betweenness_cent,
        top_n=NETWORK_CONFIG["golden_land_top_n"],
    )
    golden_geojson_features: List[Dict[str, Any]] = []
    for idx, spot in enumerate(golden_spots, start=1):
        golden_geojson_features.append(
            {
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [spot["lon"], spot["lat"]],
                },
                "properties": {
                    "type": "golden_spot",
                    "rank": idx,
                    "score": round(spot["score"], 4),
                },
            }
        )

    return {
        "edges": {"type": "FeatureCollection", "features": edges_geojson},
        "nodes": {"type": "FeatureCollection", "features": nodes_geojson},
        "golden_spots": golden_spots,
        "golden_spots_geojson": {
            "type": "FeatureCollection",
            "features": golden_geojson_features,
        },
        "top_node": top_node_data if top_node_data["score"] != -1.0 else None,
        # ~11 m simplification keeps exports small; area error is negligible.
        "coverage_geojson": mapping(
            wkt.loads(polygon_wkt_str).simplify(1e-4, preserve_topology=True)
        ),
        "stats": {
            "nodes_count": len(G.nodes),
            "edges_count": len(G.edges),
            "used_approximation": is_large_graph,
            "closeness_method": closeness_method,
            "was_cached": was_cached,
        },
    }


# ============================================================================
# SECTION 3b: ENGINE · SPACE SYNTAX — copied verbatim from Rent_Gradient_new.py (pure; ``render_depthmap_png``
# and ``histogram_figure`` import matplotlib / plotly lazily)
# ============================================================================

M_PER_DEG_LAT = 110_574.0


M_PER_DEG_LON_EQ = 111_320.0


@dataclass(frozen=True)
class SegmentNetwork:
    """Undirected segment map in local metres plus its directed transition graph.

    A *state* is a segment travelled in one direction: ``2s`` = ``seg_a → seg_b`` and
    ``2s + 1`` = ``seg_b → seg_a``. ``tr_from → tr_to`` is a legal move between two states at
    their shared node (never a U-turn) and ``tr_deflection_deg`` its change of heading
    (0 = straight on, 90 = right angle, 180 = hairpin).
    """

    origin: Tuple[float, float]          # (lat0, lon0) of the local plane
    node_xy: np.ndarray                  # (N, 2) metres
    seg_a: np.ndarray                    # (S,) node index of the start of the stored polyline
    seg_b: np.ndarray                    # (S,) node index of its end
    seg_len: np.ndarray                  # (S,) metres (OSM ``length`` when valid)
    seg_bend_deg: np.ndarray             # (S,) turning inside the segment, Σ|Δheading|
    seg_dir_a: np.ndarray                # (S, 2) unit vector leaving node a along the segment
    seg_dir_b: np.ndarray                # (S, 2) unit vector leaving node b along the segment
    seg_mid_xy: np.ndarray               # (S, 2) metres, midpoint along the polyline
    seg_mid_lonlat: np.ndarray           # (S, 2)
    seg_lonlat: List[np.ndarray]         # S polylines (k, 2) lon, lat — drawn as stored
    seg_xy: List[np.ndarray]             # S polylines (k, 2) in local metres
    seg_name: List[Optional[str]]
    seg_highway: List[Optional[str]]
    seg_component: np.ndarray            # (S,) connected-component id
    tr_from: np.ndarray                  # (T,) state
    tr_to: np.ndarray                    # (T,) state
    tr_deflection_deg: np.ndarray        # (T,)

    @property
    def n_segments(self) -> int:
        return len(self.seg_a)

    @property
    def n_nodes(self) -> int:
        return len(self.node_xy)

    def to_xy(self, lon: Any, lat: Any) -> np.ndarray:
        return _to_xy(lon, lat, self.origin[1], self.origin[0])


def _to_xy(lon: Any, lat: Any, lon0: float, lat0: float) -> np.ndarray:
    """Equirectangular projection to local metres (fine at city scale)."""
    lon = np.asarray(lon, dtype=float)
    lat = np.asarray(lat, dtype=float)
    x = (lon - lon0) * np.cos(np.radians(lat0)) * M_PER_DEG_LON_EQ
    y = (lat - lat0) * M_PER_DEG_LAT
    return np.stack([x, y], axis=-1)


def _first_text(value: Any) -> Optional[str]:
    """OSM tags may be a list when ways were merged; keep the first non-empty text."""
    if isinstance(value, (list, tuple)):
        value = next((v for v in value if v not in (None, "")), None)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _unit(vec: np.ndarray) -> np.ndarray:
    norm = float(np.hypot(vec[0], vec[1]))
    return vec / norm if norm > 1e-9 else np.zeros(2)


def _edge_lonlat(data: Dict[str, Any], p_u: np.ndarray, p_v: np.ndarray) -> np.ndarray:
    """Polyline (k, 2) lon/lat of one OSM edge, running from node u to node v."""
    coords = getattr(data.get("geometry"), "coords", None)
    if coords is not None:
        pts = np.asarray([c[:2] for c in coords], dtype=float)
        if len(pts) >= 2:
            if float(((pts[0] - p_u) ** 2).sum()) > float(((pts[0] - p_v) ** 2).sum()):
                pts = pts[::-1]  # geometry stored v → u
            return pts
    return np.vstack([p_u, p_v])


def _polyline_stats(
    xy: np.ndarray, chord: np.ndarray, tolerance_m: float
) -> Tuple[np.ndarray, np.ndarray, float]:
    """``(dir_a, dir_b, bend_deg)`` of a polyline in metres.

    The polyline is first straightened with Douglas–Peucker so OSM digitising jitter does not add
    fake turning. ``dir_a`` / ``dir_b`` are the first / last straight pieces pointing *out of* the
    segment at each end; ``bend_deg`` is the sum of heading changes between pieces. Using the same
    pieces for both makes turning add up exactly along a path that runs through a smooth curve.
    """
    pts = xy
    if len(xy) > 2 and tolerance_m > 0:
        simple = np.asarray(LineString(xy).simplify(tolerance_m, preserve_topology=False).coords)
        if len(simple) >= 2:
            pts = simple
    steps = np.diff(pts, axis=0)
    length = np.hypot(steps[:, 0], steps[:, 1])
    steps = steps[length > 1e-6] / length[length > 1e-6, None]
    if len(steps) == 0:                               # degenerate polyline: fall back to the node chord
        return _unit(chord), _unit(-chord), 0.0
    cosines = np.clip((steps[:-1] * steps[1:]).sum(axis=1), -1.0, 1.0)
    return steps[0], -steps[-1], float(np.degrees(np.arccos(cosines)).sum())


def _polyline_midpoints(xy: np.ndarray, lonlat: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """Point half-way along a polyline by arc length *in metres*: ``(local metres, lon/lat)``."""
    cum = np.concatenate([[0.0], np.cumsum(np.hypot(*np.diff(xy, axis=0).T))])
    if cum[-1] <= 0:
        return xy[0].copy(), lonlat[0].copy()
    half = cum[-1] / 2.0

    def at_half(points: np.ndarray) -> np.ndarray:
        return np.array([np.interp(half, cum, points[:, 0]), np.interp(half, cum, points[:, 1])])

    return at_half(xy), at_half(lonlat)


def build_segment_network(graph: Any) -> SegmentNetwork:
    """Collapse an OSMnx-style graph into an undirected segment map.

    Two-way streets (u→v plus v→u with the same geometry) become one segment; genuinely different
    parallel edges and loops are kept so every road can be drawn. Nodes need ``x`` (lon) / ``y``
    (lat); edges may carry ``length`` (m), ``geometry``, ``name`` and ``highway``.
    """
    nodes = sorted(graph.nodes, key=_node_sort_key)
    if len(nodes) < 2:
        raise ValueError("โครงข่ายถนนต้องมีอย่างน้อย 2 โหนด")
    index = {node: i for i, node in enumerate(nodes)}
    try:
        node_lonlat = np.array([(float(graph.nodes[n]["x"]), float(graph.nodes[n]["y"])) for n in nodes])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("ทุกโหนดต้องมีพิกัด x (lon) และ y (lat)") from exc
    lat0, lon0 = float(node_lonlat[:, 1].mean()), float(node_lonlat[:, 0].mean())
    node_xy = _to_xy(node_lonlat[:, 0], node_lonlat[:, 1], lon0, lat0)

    found: Dict[Tuple[Any, ...], Tuple[np.ndarray, Dict[str, Any]]] = {}
    for u, v, data in graph.edges(data=True):
        iu, iv = index[u], index[v]
        pts = _edge_lonlat(data, node_lonlat[iu], node_lonlat[iv])
        if iu > iv:
            iu, iv, pts = iv, iu, pts[::-1]
        forward = tuple(np.round(pts, 6).ravel().tolist())
        if iu == iv:                                 # a loop starts and ends at the same node: compare the
            backward = tuple(np.round(pts[::-1], 6).ravel().tolist())   # whole outline to pick one direction
            if backward < forward:
                pts, forward = pts[::-1], backward
        key = (iu, iv, forward)
        if key not in found:                         # the reverse twin of a two-way street
            found[key] = (pts, data)
    if not found:
        raise ValueError("โครงข่ายถนนไม่มีเส้นถนนที่ใช้ได้")

    keys = sorted(found)
    n_seg = len(keys)
    seg_a = np.array([k[0] for k in keys], dtype=np.int64)
    seg_b = np.array([k[1] for k in keys], dtype=np.int64)
    seg_len = np.empty(n_seg)
    seg_bend = np.empty(n_seg)
    seg_dir_a = np.empty((n_seg, 2))
    seg_dir_b = np.empty((n_seg, 2))
    seg_mid_xy = np.empty((n_seg, 2))
    seg_mid_lonlat = np.empty((n_seg, 2))
    seg_lonlat: List[np.ndarray] = []
    seg_xy: List[np.ndarray] = []
    seg_name: List[Optional[str]] = []
    seg_highway: List[Optional[str]] = []
    tol = float(ANALYSIS_CONFIG["simplify_tolerance_m"])
    for s, key in enumerate(keys):
        pts, data = found[key]
        xy = _to_xy(pts[:, 0], pts[:, 1], lon0, lat0)
        chord = node_xy[seg_b[s]] - node_xy[seg_a[s]]
        seg_dir_a[s], seg_dir_b[s], seg_bend[s] = _polyline_stats(xy, chord, tol)
        try:
            length = float(data.get("length"))
        except (TypeError, ValueError):
            length = float("nan")
        if not np.isfinite(length) or length <= 0:
            length = float(np.hypot(*np.diff(xy, axis=0).T).sum())
        seg_len[s] = max(length, 0.1)
        seg_mid_xy[s], seg_mid_lonlat[s] = _polyline_midpoints(xy, pts)
        seg_lonlat.append(pts)
        seg_xy.append(xy)
        seg_name.append(_first_text(data.get("name")))
        seg_highway.append(_first_text(data.get("highway")))

    # Legal moves: arrive at a node on one segment end, leave on a *different* segment's end.
    incident: List[List[Tuple[int, int]]] = [[] for _ in nodes]
    for s in range(n_seg):
        incident[seg_a[s]].append((s, 0))
        incident[seg_b[s]].append((s, 1))
    moves_from: List[np.ndarray] = []
    moves_to: List[np.ndarray] = []
    moves_defl: List[np.ndarray] = []
    for ends in incident:
        k = len(ends)
        if k < 2:
            continue
        segs = np.fromiter((e[0] for e in ends), dtype=np.int64, count=k)
        side = np.fromiter((e[1] for e in ends), dtype=np.int64, count=k)
        out = np.where(side[:, None] == 0, seg_dir_a[segs], seg_dir_b[segs])  # headings away from the node
        deflection = 180.0 - np.degrees(np.arccos(np.clip(out @ out.T, -1.0, 1.0)))
        arrive = np.where(side == 1, 2 * segs, 2 * segs + 1)
        depart = np.where(side == 0, 2 * segs, 2 * segs + 1)
        i_idx, j_idx = np.nonzero(segs[:, None] != segs[None, :])
        moves_from.append(arrive[i_idx])
        moves_to.append(depart[j_idx])
        moves_defl.append(deflection[i_idx, j_idx])
    empty_i, empty_f = np.empty(0, dtype=np.int64), np.empty(0)
    tr_from = np.concatenate(moves_from) if moves_from else empty_i
    tr_to = np.concatenate(moves_to) if moves_to else empty_i
    tr_defl = np.concatenate(moves_defl) if moves_defl else empty_f

    adjacency = csr_matrix((np.ones(n_seg), (seg_a, seg_b)), shape=(len(nodes), len(nodes)))
    _, labels = connected_components(adjacency, directed=False)
    return SegmentNetwork(
        origin=(lat0, lon0), node_xy=node_xy, seg_a=seg_a, seg_b=seg_b, seg_len=seg_len,
        seg_bend_deg=seg_bend, seg_dir_a=seg_dir_a, seg_dir_b=seg_dir_b, seg_mid_xy=seg_mid_xy,
        seg_mid_lonlat=seg_mid_lonlat, seg_lonlat=seg_lonlat, seg_xy=seg_xy, seg_name=seg_name,
        seg_highway=seg_highway, seg_component=labels[seg_a].astype(np.int64),
        tr_from=tr_from, tr_to=tr_to, tr_deflection_deg=tr_defl,
    )


def segments_in_circle(net: SegmentNetwork, lat: float, lon: float, radius_m: float) -> np.ndarray:
    """Boolean mask of segments whose midpoint lies within ``radius_m`` of ``(lat, lon)``."""
    centre = net.to_xy(lon, lat)
    return np.hypot(*(net.seg_mid_xy - centre).T) <= radius_m


@dataclass
class AnalysisResult:
    """Raw counts and normalised indices per radius (keys from :func:`radius_key`)."""

    kind: str
    turn_deg: float
    radii: List[Optional[float]]
    with_choice: bool
    nc: Dict[str, np.ndarray] = field(default_factory=dict)            # segments in radius (incl. origin)
    td: Dict[str, np.ndarray] = field(default_factory=dict)            # total depth
    choice: Dict[str, np.ndarray] = field(default_factory=dict)        # CH (ordered pairs)
    integration: Dict[str, np.ndarray] = field(default_factory=dict)   # NAIN
    choice_norm: Dict[str, np.ndarray] = field(default_factory=dict)   # NACH
    meta: Dict[str, Any] = field(default_factory=dict)


def radius_key(radius: Optional[float]) -> str:
    return "n" if radius is None else f"{radius:g}"


def radius_label(radius: Optional[float]) -> str:
    return "Global (n)" if radius is None else f"{radius:,.0f} m"


def state_costs(net: SegmentNetwork, kind: str, topological_turn_deg: float = 0.0) -> np.ndarray:
    """Cost of every legal move for one distance kind (all strictly positive).

    Angular and topological costs tie very often: every route that turns the same way between the
    same two headings has exactly the same total angle. TD / NAIN do not care, but which route
    Choice counts does, so a negligible per-metre term makes "equally straight → the shorter one".
    """
    s, t = net.tr_from // 2, net.tr_to // 2
    metric = 0.5 * (net.seg_len[s] + net.seg_len[t])
    if kind == "angular":
        cost = (net.tr_deflection_deg + 0.5 * (net.seg_bend_deg[s] + net.seg_bend_deg[t])) / 90.0
    elif kind == "topological":
        cost = (np.ones(len(s)) if topological_turn_deg <= 0
                else (net.tr_deflection_deg > topological_turn_deg).astype(float))
    elif kind == "metric":
        return np.maximum(metric, float(ANALYSIS_CONFIG["eps_cost"]))
    else:
        raise ValueError(f"ไม่รู้จักชนิดระยะ: {kind!r}")
    return np.maximum(cost + ANALYSIS_CONFIG["tie_break_per_m"] * metric, float(ANALYSIS_CONFIG["eps_cost"]))


def state_matrix(net: SegmentNetwork, kind: str, topological_turn_deg: float = 0.0) -> csr_matrix:
    n = 2 * net.n_segments
    return csr_matrix((state_costs(net, kind, topological_turn_deg), (net.tr_from, net.tr_to)), shape=(n, n))


def _subtree_sums(pred: np.ndarray, weights: np.ndarray) -> np.ndarray:
    """Sum of ``weights`` over every node's subtree in a shortest-path forest.

    ``pred[v]`` is the parent of ``v`` (negative for roots / unreached nodes). Hop depth comes from
    pointer jumping, then children are folded into parents one depth level at a time (deepest
    first), so the work stays inside numpy instead of a per-node Python loop.
    """
    n = len(pred)
    has_parent = pred >= 0
    total = np.asarray(weights, dtype=float).copy()
    if not has_parent.any():
        return total
    parent = np.where(has_parent, pred, np.arange(n))
    depth = has_parent.astype(np.int64)
    while True:
        grand = parent[parent]
        if np.array_equal(grand, parent):
            break
        depth = depth + depth[parent]
        parent = grand
    order = np.argsort(depth, kind="stable")
    sorted_depth = depth[order]
    top = int(sorted_depth[-1])
    bounds = np.searchsorted(sorted_depth, np.arange(top + 2))
    for level in range(top, 0, -1):
        block = order[bounds[level]:bounds[level + 1]]
        np.add.at(total, pred[block], total[block])
    return total


def _choice_contribution(pred: np.ndarray, rep: np.ndarray, reached: np.ndarray, origin: int) -> np.ndarray:
    """Per-segment count of destinations whose shortest path from ``origin`` runs *through* it.

    ``pred`` is the forest over the (local) states, ``rep[j]`` the cheaper state of segment ``j``,
    ``reached[j]`` whether ``j`` is a destination. Origin and destination themselves are excluded.
    """
    dest = reached.copy()
    dest[origin] = False
    weight = np.zeros(len(pred))
    idx = np.flatnonzero(dest)
    weight[2 * idx + rep[idx]] = 1.0
    beyond = _subtree_sums(pred, weight) - weight          # destinations strictly downstream of a state
    contribution = beyond[0::2] + beyond[1::2]
    contribution[origin] = 0.0
    return contribution


def _tree_from(matrix: csr_matrix, roots: Tuple[int, int], want_pred: bool, limit: float = np.inf):
    """Shortest distances (and parents) from the two states of one origin segment."""
    if want_pred:
        dist, pred, _ = dijkstra(matrix, directed=True, indices=list(roots), min_only=True,
                                 return_predecessors=True, limit=limit)
        return dist, pred
    return dijkstra(matrix, directed=True, indices=list(roots), min_only=True, limit=limit), None


def _empty_counters(n: int, with_choice: bool) -> Tuple[np.ndarray, np.ndarray, Optional[np.ndarray]]:
    return np.zeros(n), np.zeros(n), (np.zeros(n) if with_choice else None)


def _local_pass(
    net: SegmentNetwork, depth_matrix: csr_matrix, metric_matrix: csr_matrix,
    radii: Sequence[float], with_choice: bool, tick: Callable[[], None],
) -> Dict[float, Tuple[np.ndarray, np.ndarray, Optional[np.ndarray]]]:
    """Exact NC / TD (/ CH) for finite metric radii: one origin at a time, neighbourhood first."""
    n_seg = net.n_segments
    out = {r: _empty_counters(n_seg, with_choice) for r in radii}
    r_max = max(radii)
    for origin in range(n_seg):
        near, _ = _tree_from(metric_matrix, (2 * origin, 2 * origin + 1), False, limit=r_max)
        near_seg = near.reshape(-1, 2).min(axis=1)
        for r in radii:
            nc, td, ch = out[r]
            inside = np.flatnonzero(near_seg <= r)
            nc[origin] = len(inside)
            if len(inside) < 2:
                continue
            if len(inside) == n_seg:
                sub, local = depth_matrix, origin
            else:
                states = np.empty(2 * len(inside), dtype=np.int64)
                states[0::2], states[1::2] = 2 * inside, 2 * inside + 1
                sub = depth_matrix[states][:, states]
                local = int(np.searchsorted(inside, origin))
            dist, pred = _tree_from(sub, (2 * local, 2 * local + 1), with_choice)
            pair = dist.reshape(-1, 2)
            depth = pair.min(axis=1)
            reached = np.isfinite(depth)
            td[origin] = depth[reached].sum()
            if with_choice:
                ch[inside] += _choice_contribution(pred, pair.argmin(axis=1), reached, local)
        tick()
    return out


def _global_pass(
    net: SegmentNetwork, depth_matrix: csr_matrix, with_choice: bool, max_exact: int,
    n_pivots: int, seed: int, tick: Callable[[], None],
) -> Tuple[np.ndarray, np.ndarray, Optional[np.ndarray], Dict[str, Any]]:
    """NC / TD (/ CH) over each whole connected component; big components use pivot sampling."""
    n_seg = net.n_segments
    nc, td, ch = _empty_counters(n_seg, with_choice)
    rng = np.random.default_rng(seed)
    info: Dict[str, Any] = {"approximate": False, "pivots": 0, "sampled_components": 0}
    for comp in np.unique(net.seg_component):
        members = np.flatnonzero(net.seg_component == comp)
        size = len(members)
        nc[members] = size
        exact = size <= max_exact
        origins = members if exact else np.sort(rng.choice(members, size=min(n_pivots, size), replace=False))
        scale = 1.0 if exact else size / len(origins)
        if not exact:
            info.update(approximate=True, pivots=int(len(origins)),
                        sampled_components=info["sampled_components"] + 1)
        for origin in origins:
            dist, pred = _tree_from(depth_matrix, (2 * origin, 2 * origin + 1), with_choice)
            pair = dist.reshape(-1, 2)
            depth = pair.min(axis=1)
            reached = np.isfinite(depth)
            if exact:
                td[origin] = depth[reached].sum()
            else:                                   # Σ_p d(i, p) estimates Σ_j d(i, j) by symmetry
                td[members] += scale * depth[members]
            if with_choice:
                ch += scale * _choice_contribution(pred, pair.argmin(axis=1), reached, int(origin))
            tick()
    return nc, td, ch, info


def integration_index(nc: np.ndarray, td: np.ndarray, kind: str) -> np.ndarray:
    """Normalised integration NAIN = NC^1.2 / (TD + 2) (metric TD counted in 100 m blocks)."""
    unit = ANALYSIS_CONFIG["metric_depth_unit_m"] if kind == "metric" else 1.0
    return (np.power(nc, ANALYSIS_CONFIG["nain_exponent"])
            / (td / unit + ANALYSIS_CONFIG["nain_offset"]))


def choice_index(ch: np.ndarray, td: np.ndarray, kind: str) -> np.ndarray:
    """Normalised choice NACH = log(CH + 1) / log(TD + 3)."""
    unit = ANALYSIS_CONFIG["metric_depth_unit_m"] if kind == "metric" else 1.0
    return np.log(ch + 1.0) / np.log(td / unit + ANALYSIS_CONFIG["nach_offset"])


def analyse_network(
    net: SegmentNetwork,
    kind: str = "angular",
    radii: Sequence[Optional[float]] = (None,),
    with_choice: bool = True,
    topological_turn_deg: float = 0.0,
    max_exact_segments: Optional[int] = None,
    n_pivots: Optional[int] = None,
    seed: Optional[int] = None,
    progress: Optional[Callable[[float, str], None]] = None,
) -> AnalysisResult:
    """Space-syntax segment analysis of ``net`` for every radius in ``radii`` (``None`` = global).

    ``kind``: ``angular`` | ``topological`` | ``metric`` (``topological_turn_deg`` > 0 counts a step
    only for turns sharper than that). Returns an :class:`AnalysisResult` with, per radius, the raw
    NC / TD / CH and the normalised NAIN / NACH. Local radii are always exact; ``None`` (global) is
    exact up to ``max_exact_segments`` per connected component and pivot-sampled above it
    (``n_pivots`` origins, fixed ``seed``). ``progress(fraction, text)`` is called as it runs.
    """
    if kind not in DISTANCE_KINDS:
        raise ValueError(f"ไม่รู้จักชนิดระยะ: {kind!r}")
    wanted: List[Optional[float]] = []
    for r in radii:
        if r is not None and not (np.isfinite(r) and r > 0):
            raise ValueError("รัศมีต้องเป็นเมตรที่มากกว่า 0")
        if r not in wanted:
            wanted.append(r)
    if not wanted:
        raise ValueError("ต้องเลือกรัศมีอย่างน้อย 1 ค่า")
    if net.n_segments > ANALYSIS_CONFIG["max_segments"]:
        raise ValueError(f"โครงข่ายมี {net.n_segments:,} segment "
                         f"— เกินขีดจำกัด {ANALYSIS_CONFIG['max_segments']:,}")
    wanted.sort(key=lambda r: (r is None, r or 0.0))
    max_exact = int(ANALYSIS_CONFIG["max_exact_segments"] if max_exact_segments is None
                    else max_exact_segments)
    pivots = int(ANALYSIS_CONFIG["n_pivots"] if n_pivots is None else n_pivots)
    seed = int(ANALYSIS_CONFIG["seed"] if seed is None else seed)

    started = time.perf_counter()
    finite = [r for r in wanted if r is not None]
    total_ticks = net.n_segments * (1 if finite else 0)
    if None in wanted:
        sizes = np.bincount(net.seg_component)
        total_ticks += int(sum(s if s <= max_exact else min(pivots, s) for s in sizes))
    done = [0]

    def tick() -> None:
        done[0] += 1
        if progress is not None and (done[0] % 25 == 0 or done[0] == total_ticks):
            progress(min(done[0] / max(total_ticks, 1), 1.0), f"{done[0]:,}/{total_ticks:,} segment")

    depth_matrix = state_matrix(net, kind, topological_turn_deg)
    result = AnalysisResult(kind=kind, turn_deg=float(topological_turn_deg), radii=list(wanted),
                            with_choice=with_choice)
    info: Dict[str, Any] = {"approximate": False, "pivots": 0, "sampled_components": 0}
    if finite:
        metric_matrix = depth_matrix if kind == "metric" else state_matrix(net, "metric")
        for r, (nc, td, ch) in _local_pass(net, depth_matrix, metric_matrix, finite,
                                           with_choice, tick).items():
            result.nc[radius_key(r)], result.td[radius_key(r)] = nc, td
            if ch is not None:
                result.choice[radius_key(r)] = ch
    if None in wanted:
        nc, td, ch, info = _global_pass(net, depth_matrix, with_choice, max_exact, pivots, seed, tick)
        result.nc["n"], result.td["n"] = nc, td
        if ch is not None:
            result.choice["n"] = ch
    for key in result.nc:
        result.integration[key] = integration_index(result.nc[key], result.td[key], kind)
        if with_choice:
            result.choice_norm[key] = choice_index(result.choice[key], result.td[key], kind)
    result.meta = {
        "seconds": time.perf_counter() - started, "n_segments": net.n_segments,
        "approximate_global": info["approximate"], "pivots": info["pivots"],
        "sampled_components": info["sampled_components"], "max_exact_segments": max_exact,
    }
    if progress is not None:
        progress(1.0, "เสร็จสิ้น")
    return result


def _hex_rgb(color: str) -> np.ndarray:
    color = color.lstrip("#")
    return np.array([int(color[i:i + 2], 16) for i in (0, 2, 4)], dtype=float) / 255.0


def gradient_rgb(t: Any, palette: str = DEFAULT_PALETTE) -> np.ndarray:
    """RGB ``(N, 3)`` in 0..1 for ``t`` in [0, 1]: 0 = น้ำเงิน (ต่ำ) … 1 = แดง (สูง); NaN → gray."""
    stops = np.array([_hex_rgb(c) for c in PALETTES[palette]])
    xs = np.linspace(0.0, 1.0, len(stops))
    t = np.atleast_1d(np.asarray(t, dtype=float))
    clipped = np.clip(np.where(np.isfinite(t), t, 0.0), 0.0, 1.0)
    rgb = np.stack([np.interp(clipped, xs, stops[:, c]) for c in range(3)], axis=-1)
    rgb[~np.isfinite(t)] = _hex_rgb(MISSING_COLOR)
    return rgb


def gradient_hex(t: Any, palette: str = DEFAULT_PALETTE) -> List[str]:
    return ["#%02x%02x%02x" % tuple(int(round(c * 255)) for c in row) for row in gradient_rgb(t, palette)]


def gradient_css(palette: str = DEFAULT_PALETTE, direction: str = "90deg") -> str:
    stops = PALETTES[palette]
    parts = ", ".join(f"{c} {100 * i / (len(stops) - 1):.0f}%" for i, c in enumerate(stops))
    return f"linear-gradient({direction}, {parts})"


def scale_scores(values: Any, mode: str = "linear", mask: Optional[np.ndarray] = None) -> Dict[str, Any]:
    """Map raw index values to ``t`` in [0, 1] and a 0–100 score over the segments in ``mask``.

    ``linear``: position between the lowest and highest value (depthmap style).
    ``quantile``: percentile rank, so every colour band holds the same number of segments.
    Returns ``t``, ``score``, ``vmin``, ``vmax`` and legend ``ticks`` ``[(t, value), …]``.
    """
    if mode not in SCALE_MODES:
        raise ValueError(f"ไม่รู้จักโหมดสเกล: {mode!r}")
    values = np.asarray(values, dtype=float)
    use = np.isfinite(values)
    if mask is not None:
        use &= np.asarray(mask, dtype=bool)
    t = np.full(len(values), np.nan)
    out: Dict[str, Any] = {"t": t, "score": t.copy(), "mode": mode, "vmin": np.nan, "vmax": np.nan,
                           "ticks": [], "sorted": np.empty(0)}
    if not use.any():
        return out
    v = values[use]
    vmin, vmax = float(v.min()), float(v.max())
    marks = (0.0, 0.25, 0.5, 0.75, 1.0)
    if mode == "quantile":
        t[use] = (rankdata(v, method="average") - 1.0) / (len(v) - 1.0) if len(v) > 1 else 0.5
        ticks = list(zip(marks, np.quantile(v, marks).tolist()))
    else:
        t[use] = (v - vmin) / (vmax - vmin) if vmax > vmin else 0.5
        ticks = [(m, vmin + m * (vmax - vmin)) for m in marks]
    out.update(t=t, score=100.0 * t, vmin=vmin, vmax=vmax, ticks=ticks, sorted=np.sort(v))
    return out


def t_for_values(scaled: Dict[str, Any], x: Any) -> np.ndarray:
    """Colour position of arbitrary values under an existing :func:`scale_scores` mapping."""
    x = np.asarray(x, dtype=float)
    if scaled["mode"] == "quantile":
        ref = scaled["sorted"]                         # share of values below x, as in scale_scores
        return np.clip(np.searchsorted(ref, x, side="left") / max(len(ref) - 1, 1), 0.0, 1.0)
    span = scaled["vmax"] - scaled["vmin"]
    return np.clip((x - scaled["vmin"]) / span, 0.0, 1.0) if span > 0 else np.full(x.shape, 0.5)


def pick_top_segments(
    net: SegmentNetwork, score: np.ndarray, n: int, min_spacing_m: float,
    mask: Optional[np.ndarray] = None,
) -> List[int]:
    """Highest-scoring segments, skipping any whose midpoint is within ``min_spacing_m`` of a pick."""
    ok = np.isfinite(score)
    if mask is not None:
        ok &= np.asarray(mask, dtype=bool)
    candidates = np.flatnonzero(ok)
    candidates = candidates[np.argsort(-score[candidates], kind="stable")]
    chosen: List[int] = []
    for s in candidates:
        if all(np.hypot(*(net.seg_mid_xy[s] - net.seg_mid_xy[c])) >= min_spacing_m for c in chosen):
            chosen.append(int(s))
            if len(chosen) >= n:
                break
    return chosen


def top_spacing_m(net: SegmentNetwork, mask: np.ndarray) -> float:
    """Minimum distance between ranked picks: ≥ 250 m and ~4 % of the shown extent (no overlapping pins)."""
    pts = net.seg_mid_xy[np.asarray(mask, dtype=bool)]
    extent = float(max(np.ptp(pts[:, 0]), np.ptp(pts[:, 1]))) if len(pts) else 0.0
    return max(float(ANALYSIS_CONFIG["top_min_spacing_m"]), 0.04 * extent)


def result_columns(net: SegmentNetwork, result: AnalysisResult) -> Dict[str, np.ndarray]:
    """Flat ``{column: array}`` of every computed index, named like ``NAIN_800`` / ``NACH_n``."""
    cols: Dict[str, np.ndarray] = {}
    for key in result.integration:
        cols[f"NAIN_{key}"] = result.integration[key]
        cols[f"NC_{key}"] = result.nc[key]
        cols[f"TD_{key}"] = result.td[key]
        if result.with_choice:
            cols[f"NACH_{key}"] = result.choice_norm[key]
            cols[f"CH_{key}"] = result.choice[key]
    return cols


def segment_table(
    net: SegmentNetwork, result: AnalysisResult, mask: Optional[np.ndarray] = None,
) -> pd.DataFrame:
    """One row per segment (for CSV export and the highway summary)."""
    rows = np.arange(net.n_segments) if mask is None else np.flatnonzero(mask)
    frame = pd.DataFrame({
        "segment": rows,
        "name": [net.seg_name[s] for s in rows],
        "highway": [net.seg_highway[s] for s in rows],
        "length_m": np.round(net.seg_len[rows], 1),
        "mid_lat": np.round(net.seg_mid_lonlat[rows, 1], 6),
        "mid_lon": np.round(net.seg_mid_lonlat[rows, 0], 6),
    })
    for name, arr in result_columns(net, result).items():
        frame[name] = np.round(arr[rows], 6)
    return frame


def _plain(value: Any) -> Any:
    """numpy scalar → plain Python (NaN → None) so ``json`` accepts it."""
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, float) and not np.isfinite(value):
        return None
    return value


def segments_geojson(
    net: SegmentNetwork, columns: Dict[str, Sequence[Any]], mask: Optional[np.ndarray] = None,
    precision: int = 6,
) -> Dict[str, Any]:
    """FeatureCollection of the masked segments; ``columns`` become feature properties."""
    rows = np.arange(net.n_segments) if mask is None else np.flatnonzero(mask)
    features = [
        {
            "type": "Feature",
            "geometry": {"type": "LineString",
                         "coordinates": np.round(net.seg_lonlat[s], precision).tolist()},
            "properties": {"segment": int(s), **{name: _plain(col[s]) for name, col in columns.items()}},
        }
        for s in rows
    ]
    return {"type": "FeatureCollection", "features": features}


def highway_summary(
    net: SegmentNetwork, score: np.ndarray, value: np.ndarray, mask: np.ndarray,
) -> pd.DataFrame:
    """Length-weighted mean score per OSM ``highway`` class — a quick sanity check of the gradient."""
    idx = np.flatnonzero(mask & np.isfinite(score))
    frame = pd.DataFrame({
        "highway": [net.seg_highway[s] or "(ไม่ระบุ)" for s in idx],
        "length_km": net.seg_len[idx] / 1000.0,
        "score": score[idx],
        "value": value[idx],
    })
    rows = []
    for name, grp in frame.groupby("highway"):
        weight = grp["length_km"].to_numpy()
        rows.append({
            "highway": name, "segments": len(grp), "length_km": float(weight.sum()),
            "mean_score": float(np.average(grp["score"], weights=weight)),
            "mean_value": float(np.average(grp["value"], weights=weight)),
        })
    return pd.DataFrame(rows).sort_values("mean_score", ascending=False, ignore_index=True)


def render_depthmap_png(
    net: SegmentNetwork, t: np.ndarray, mask: np.ndarray, palette: str = DEFAULT_PALETTE, *,
    thick_by_score: bool = True, low_label: str = "low", high_label: str = "high", width_in: float = 10.0,
    dpi: int = 110,
) -> bytes:
    """Black-background segment map like depthmapX: each road coloured blue → red by ``t``."""
    from matplotlib.collections import LineCollection
    from matplotlib.figure import Figure

    idx = np.flatnonzero(np.asarray(mask, dtype=bool) & np.isfinite(t))
    if len(idx) == 0:
        raise ValueError("ไม่มี segment ให้วาด")
    idx = idx[np.argsort(t[idx], kind="stable")]          # draw the red (high) roads last, on top
    lines = [net.seg_xy[i] for i in idx]
    pts = np.concatenate(lines)
    x0, y0 = pts.min(axis=0)
    x1, y1 = pts.max(axis=0)
    pad = 0.02 * max(x1 - x0, y1 - y0, 1.0)
    span_x, span_y = max(x1 - x0, 1.0) + 2 * pad, max(y1 - y0, 1.0) + 2 * pad
    strip = 0.07                                            # band under the map reserved for the colour bar
    height_in = float(np.clip(width_in * span_y / span_x / (1.0 - strip), 4.0, 13.0))

    fig = Figure(figsize=(width_in, height_in), dpi=dpi, facecolor="black")
    ax = fig.add_axes([0, strip, 1, 1 - strip])
    ax.set_facecolor("black")
    ax.set_xlim(x0 - pad, x0 - pad + span_x)
    ax.set_ylim(y0 - pad, y0 - pad + span_y)
    ax.set_aspect("equal", adjustable="box")
    ax.axis("off")
    widths = (0.7 + 1.7 * t[idx]) if thick_by_score else 1.1
    ax.add_collection(LineCollection(lines, colors=gradient_rgb(t[idx], palette), linewidths=widths,
                                     capstyle="round", joinstyle="round"))
    bar = fig.add_axes([0.04, 0.018, 0.26, 0.012])
    bar.imshow(gradient_rgb(np.linspace(0, 1, 256), palette)[None, :, :], aspect="auto")
    bar.axis("off")
    fig.text(0.04, 0.034, low_label, color="white", fontsize=8, ha="left", va="bottom")
    fig.text(0.30, 0.034, high_label, color="white", fontsize=8, ha="right", va="bottom")
    buffer = io.BytesIO()
    fig.savefig(buffer, format="png", facecolor="black")
    return buffer.getvalue()


def histogram_figure(scaled: Dict[str, Any], palette: str, x_title: str) -> Any:
    """Histogram of the displayed index; every bar wears the colour it has on the map."""
    import plotly.graph_objects as go

    v = scaled["sorted"]
    counts, edges = np.histogram(v, bins=min(30, max(5, len(np.unique(v)))))
    centres = 0.5 * (edges[:-1] + edges[1:])
    fig = go.Figure(go.Bar(x=centres, y=counts, width=np.diff(edges) * 0.95,
                           marker={"color": gradient_hex(t_for_values(scaled, centres), palette)},
                           hovertemplate=f"{x_title} %{{x:.3f}}<br>%{{y:,}} segment<extra></extra>"))
    fig.update_layout(margin={"l": 10, "r": 10, "t": 10, "b": 10}, height=300, bargap=0.02,
                      xaxis_title=x_title, yaxis_title="จำนวน segment")
    return fig


def _display_mask(net: SegmentNetwork, meta: Dict[str, Any]) -> np.ndarray:
    if meta.get("radius_m"):
        mask = segments_in_circle(net, meta["lat"], meta["lon"], float(meta["radius_m"]))
        if mask.sum() >= 2:
            return mask
    return np.ones(net.n_segments, dtype=bool)


def _top_rows(net: SegmentNetwork, scaled: Dict[str, Any], values: np.ndarray, nc: np.ndarray,
              mask: np.ndarray, n: int) -> List[Dict[str, Any]]:
    picks = pick_top_segments(net, scaled["score"], n, top_spacing_m(net, mask), mask)
    return [{
        "rank": rank, "segment": s, "label": _segment_label(net, s), "name": net.seg_name[s] or "(ไม่มีชื่อ)",
        "highway": net.seg_highway[s] or "—", "length_m": float(net.seg_len[s]),
        "score": float(scaled["score"][s]), "value": float(values[s]), "nc": int(nc[s]),
        "lat": float(net.seg_mid_lonlat[s, 1]), "lon": float(net.seg_mid_lonlat[s, 0]),
    } for rank, s in enumerate(picks, start=1)]


def _segment_label(net: SegmentNetwork, s: int) -> str:
    name, kind = net.seg_name[s], net.seg_highway[s]
    return f"{name or '(ไม่มีชื่อ)'} · {kind}" if kind else (name or "(ไม่มีชื่อ)")


def _display_columns(net: SegmentNetwork, scaled: Dict[str, Any], values: np.ndarray, nc: np.ndarray,
                     palette: str, thick: bool) -> Dict[str, Any]:
    t = scaled["t"]
    return {
        "label": [_segment_label(net, s) for s in range(net.n_segments)],
        "score": np.round(scaled["score"], 1),
        "value": np.round(values, 4),
        "nc": nc.astype(int),
        "color": np.array(gradient_hex(t, palette)),
        "weight": np.round((1.2 + 2.6 * np.nan_to_num(t, nan=0.0)) if thick else np.full(len(t), 2.0), 2),
    }


# ============================================================================
# SECTION 4: CACHED WRAPPERS (@st.cache_data)
# ============================================================================

@st.cache_data(show_spinner=False, ttl=NETWORK_CONFIG["cache_ttl_seconds"], max_entries=16)
def fetch_api_data_cached(
    api_key: str,
    travel_mode: str,
    ranges_str: str,
    marker_lat: float,
    marker_lon: float,
) -> Tuple[Optional[List[Dict[str, Any]]], Optional[str]]:
    """Streamlit-cached wrapper around the isochrone API call."""
    return safe_fetch_isochrone(api_key, travel_mode, ranges_str, marker_lat, marker_lon)


@st.cache_data(show_spinner=False, ttl=NETWORK_CONFIG["cache_ttl_seconds"], max_entries=8)
def union_all_polygons_cached(features_json_str: str) -> str:
    """
    Union all polygon features → WKT string.

    Takes a JSON **string** so that the argument is hashable for caching.
    """
    features: List[Dict[str, Any]] = json.loads(features_json_str)
    polys = [shape(f["geometry"]) for f in features]
    if not polys:
        return ""
    combined = unary_union(polys)
    return combined.wkt


@st.cache_data(show_spinner=False, ttl=NETWORK_CONFIG["cache_ttl_seconds"], max_entries=4)
def compute_centrality_cached(
    polygon_wkt_str: str, network_type: str = "drive"
) -> Dict[str, Any]:
    """Streamlit-cached wrapper for the pure centrality computation."""
    return _compute_centrality_impl(polygon_wkt_str, network_type)


# ------------------------------------------------------------ KML → GeoJSON

# Path to the bundled KML file (resolved relative to this script)
_KML_FILE_PATH: Path = (
    Path(__file__).resolve().parent
    / "เวนคืนรถไฟเด่นชัย - เชียงราย - เชียงของ ตอน 1-2.kml"
)

_KML_NS: Dict[str, str] = {"kml": "http://www.opengis.net/kml/2.2"}


def _parse_coordinates(coord_text: str) -> List[List[float]]:
    """Parse a KML <coordinates> text block into [[lon, lat], ...]."""
    coords: List[List[float]] = []
    for token in coord_text.strip().split():
        parts = token.split(",")
        if len(parts) >= 2:
            try:
                coords.append([float(parts[0]), float(parts[1])])
            except ValueError:
                continue
    return coords


@st.cache_data(show_spinner=False, max_entries=1)
def _parse_kml_to_geojson() -> Optional[Dict[str, Any]]:
    """Parse the bundled railway KML into a GeoJSON FeatureCollection.

    Uses stdlib ``xml.etree.ElementTree`` — no extra dependencies.
    Result is cached by ``@st.cache_data`` so the 10 MB file is parsed
    only once per Streamlit server lifetime.
    """
    if not _KML_FILE_PATH.exists():
        return None

    try:
        tree = ET.parse(str(_KML_FILE_PATH))
        root = tree.getroot()
    except ET.ParseError:
        return None

    features: List[Dict[str, Any]] = []

    # -- LineStrings --
    for ls_el in root.iter(f"{{{_KML_NS['kml']}}}LineString"):
        coord_el = ls_el.find(f"{{{_KML_NS['kml']}}}coordinates")
        if coord_el is None or not coord_el.text:
            continue
        coords = _parse_coordinates(coord_el.text)
        if len(coords) >= 2:
            features.append({
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": coords},
                "properties": {},
            })

    # -- Polygons --
    for poly_el in root.iter(f"{{{_KML_NS['kml']}}}Polygon"):
        outer = poly_el.find(
            f"{{{_KML_NS['kml']}}}outerBoundaryIs/"
            f"{{{_KML_NS['kml']}}}LinearRing/"
            f"{{{_KML_NS['kml']}}}coordinates"
        )
        if outer is None or not outer.text:
            continue
        coords = _parse_coordinates(outer.text)
        if len(coords) >= 4:
            features.append({
                "type": "Feature",
                "geometry": {"type": "Polygon", "coordinates": [coords]},
                "properties": {},
            })

    if not features:
        return None

    return {"type": "FeatureCollection", "features": features}


# ============================================================================
# SECTION 5: UI COMPONENTS (st.* allowed)
# ============================================================================

# ----------------------------------------------------------------------------
# LAYERS — one row per map layer. Each layer draws a folium element from a read-only ``Ctx``
# (the session state is read once, in ``build_ctx``; a layer never touches ``st.session_state``).
#
# Add a layer in three steps:
#   1. write ``draw_x(ctx) -> folium element | None`` below (build it completely, return it; do not add to the map)
#   2. add a ``Layer(...)`` row to ``LAYERS`` at the z-position you want (the list runs bottom → top)
#   3. if it has a checkbox, add its ``show_key`` to ``StateManager._DEFAULTS`` and ``SESSION_KEYS_TO_SAVE``
# ----------------------------------------------------------------------------

REMEMBER_VIEW: bool = True        # keep the user's zoom/centre when the map is rebuilt (browser sessionStorage)
MAP_HEIGHT_PX: int = 900
COORD_DECIMALS: int = 5           # ~1 m: all a screen can show; the stored results keep full precision
TOOLTIP_STYLE = ("<style>.rgtip th{text-align:left;padding-right:8px;font-weight:600}"
                 ".rgtip td{text-align:right}</style>")
PANEL_GROUPS: Tuple[str, ...] = ("โครงข่ายถนน", "Rent Gradient", "Automated Anchor", "บริบท & overlay")


@dataclass(frozen=True)
class Ctx:
    """Everything the layers draw, as one read-only snapshot (built once per run)."""

    markers: List[Dict[str, Any]]
    colors: Dict[str, str]
    iso: Optional[Dict[str, Any]]
    inter: Optional[Dict[str, Any]]
    net: Optional[Dict[str, Any]]                    # Network Analysis result (never an error dict)
    rent: Optional[Dict[str, Any]]                   # Rent Gradient result (never an error dict)
    anchor: Optional[Dict[str, Any]]                 # Automated anchor — composite
    anchor_closeness: Optional[Dict[str, Any]]       # Automated anchor — closeness 100 %
    evidence: Optional[Dict[str, Any]]               # Evidence stage result (schema-checked)
    show: Dict[str, Any]                             # layer toggles and layer options
    center: Tuple[float, float]
    ss: Optional[Any] = None                         # Space Syntax view (see ``SpaceSyntaxView``)
    cache: Any = None                                # per-session LRU for display payloads


@dataclass(frozen=True)
class Layer:
    id: str
    title: str                                       # name in the map's LayerControl
    group: str                                       # heading in the layers panel (one of PANEL_GROUPS)
    draw: Callable[[Ctx], Optional[Any]]             # → folium element (FeatureGroup / TileLayer / GeoJson) or None
    available: Callable[[Ctx], bool]                 # is there anything to draw?
    show_key: Optional[str] = None                   # session key of the checkbox; None = drawn whenever available
    label: str = ""                                  # checkbox text in the panel (defaults to ``title``)
    hint: str = ""                                   # one-line explanation under the checkbox
    requires: str = ""                               # what to run first, shown while there is nothing to draw
    legend: Optional[Callable[[Ctx], str]] = None    # HTML section for the map legend
    legend_rank: int = 50                            # lower = higher in the legend box
    options: Optional[Callable[[Ctx, bool], None]] = None   # extra widgets shown while the layer is on
    start_hidden: bool = False                       # unticked = still on the map's LayerControl, just not shown
    panel_rank: int = 50                             # lower = higher inside its group in the layers panel


def lru_get(store: Any, key: Any, source: Any, build: Callable[[], Any], limit: int = 8) -> Any:
    """Per-session LRU for display payloads. An entry is reused only for the *same* ``source`` object.

    The entry keeps a reference to ``source`` so its ``id()`` cannot be recycled while the entry lives.
    """
    entry = store.get(key)
    if entry is not None and entry[0] is source:
        store.move_to_end(key)
        return entry[1]
    value = build()
    store[key] = (source, value)
    store.move_to_end(key)
    while len(store) > limit:
        store.popitem(last=False)
    return value


# ------------------------------------------------------------------ compact browser-side shapes
def _json_js(value: Any) -> str:
    """JSON that is safe to paste into an inline script (no ``</script>`` break-out)."""
    text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return (text.replace("</", "<\\/").replace("<!--", "<\\!--")
            .replace("\u2028", "\\u2028").replace("\u2029", "\\u2029"))


def _short(value: Any) -> Any:
    """Tooltip value: numbers rounded to 3 places, missing → dash."""
    if value is None or (isinstance(value, float) and value != value):
        return "—"
    return round(value, 3) if isinstance(value, float) else value


def line_rows(features: Sequence[Dict[str, Any]], color_key: str, weight_key: str,
              value_keys: Sequence[str] = ()) -> List[list]:
    """GeoJSON LineString features → ``[color, weight, tooltip values | 0, [lat, lon, lat, lon, …]]`` rows."""
    rows: List[list] = []
    for feature in features:
        geometry, props = feature["geometry"], feature["properties"]
        parts = geometry["coordinates"] if geometry["type"] == "MultiLineString" else [geometry["coordinates"]]
        values: Any = [_short(props.get(k)) for k in value_keys] if value_keys else 0
        for part in parts:
            flat: List[float] = []
            for lon, lat in part:
                flat.append(round(lat, COORD_DECIMALS))
                flat.append(round(lon, COORD_DECIMALS))
            rows.append([props[color_key], round(float(props[weight_key]), 2), values, flat])
    return rows


def point_rows(features: Sequence[Dict[str, Any]], fill_key: str, radius: Any, value_keys: Sequence[str] = (),
               stroke_key: Optional[str] = None, stroke: str = "#000000") -> List[list]:
    """GeoJSON Point features → ``[fill, stroke, radius, tooltip values | 0, lat, lon]`` rows."""
    rows: List[list] = []
    for feature in features:
        props = feature["properties"]
        try:
            lon, lat = feature["geometry"]["coordinates"]
        except (KeyError, TypeError, ValueError):
            continue
        r = props[radius] if isinstance(radius, str) else radius
        values: Any = [_short(props.get(k)) for k in value_keys] if value_keys else 0
        rows.append([props[fill_key], props[stroke_key] if stroke_key else stroke, round(float(r), 2), values,
                     round(lat, COORD_DECIMALS), round(lon, COORD_DECIMALS)])
    return rows


_TOOLTIP_JS = """
            var heads = {{ this.heads_json }};
            var tip = {sticky: true, opacity: 0.95};
            var tipHtml = function (layer) {
                var h = '<table class="rgtip">';
                for (var k = 0; k < heads.length; k++) {
                    h += '<tr><th>' + heads[k] + '</th><td>' + layer._vals[k] + '</td></tr>';
                }
                return h + '</table>';
            };
"""


class CompactLines(MacroElement):
    """Thousands of coloured polylines drawn in the browser from one compact JSON array.

    ``folium.GeoJson`` builds a style dict, a tooltip and a feature dict *per feature in Python* (about 0.1 ms
    each, every rerun) and ships them as GeoJSON; here the caller serialises the rows once (and caches them) and
    Leaflet builds the lines. Add it to a ``FeatureGroup`` — the group owns the LayerControl entry.
    """

    _template = Template("""
        {% macro script(this, kwargs) %}
        (function (group, rows, opacity, hover) {""" + _TOOLTIP_JS + """
            for (var i = 0; i < rows.length; i++) {
                var r = rows[i], flat = r[3], pts = new Array(flat.length >> 1);
                for (var j = 0; j < pts.length; j++) { pts[j] = [flat[2 * j], flat[2 * j + 1]]; }
                var line = L.polyline(pts, {color: r[0], weight: r[1], opacity: opacity, lineCap: "round", lineJoin: "round"});
                if (r[2]) { line._vals = r[2]; line.bindTooltip(tipHtml, tip); }
                group.addLayer(line);
            }
            if (hover) {
                group.on("mouseover", function (e) { var l = e.layer; l._w0 = l.options.weight; l.setStyle({weight: l._w0 + 3, opacity: 1}); });
                group.on("mouseout", function (e) { var l = e.layer; l.setStyle({weight: l._w0, opacity: opacity}); });
            }
        })({{ this._parent.get_name() }}, {{ this.rows_json }}, {{ this.opacity }}, {{ this.hover_js }});
        {% endmacro %}
        """)

    def __init__(self, rows_json: str, heads: Sequence[str] = (), opacity: float = 0.8, hover: bool = False):
        super().__init__()
        self._name = "CompactLines"
        self.rows_json = rows_json
        self.heads_json = _json_js(list(heads))
        self.opacity = float(opacity)
        self.hover_js = "true" if hover else "false"


class CompactPoints(MacroElement):
    """Circle markers from one compact JSON array (see :class:`CompactLines`)."""

    _template = Template("""
        {% macro script(this, kwargs) %}
        (function (group, rows, weight, fillOpacity) {""" + _TOOLTIP_JS + """
            for (var i = 0; i < rows.length; i++) {
                var r = rows[i];
                var dot = L.circleMarker([r[4], r[5]], {radius: r[2], fillColor: r[0], color: r[1], weight: weight, fillOpacity: fillOpacity});
                if (r[3]) { dot._vals = r[3]; dot.bindTooltip(tipHtml, tip); }
                group.addLayer(dot);
            }
        })({{ this._parent.get_name() }}, {{ this.rows_json }}, {{ this.weight }}, {{ this.fill_opacity }});
        {% endmacro %}
        """)

    def __init__(self, rows_json: str, heads: Sequence[str] = (), weight: float = 1.0, fill_opacity: float = 0.9):
        super().__init__()
        self._name = "CompactPoints"
        self.rows_json = rows_json
        self.heads_json = _json_js(list(heads))
        self.weight = float(weight)
        self.fill_opacity = float(fill_opacity)


class ViewMemory(MacroElement):
    """Remember the user's zoom/centre in the browser so rebuilding the map does not reset the view.

    ``token`` identifies the centre the app chose (last pin / anchor). When the app moves that centre the stored
    view is ignored, so adding a pin or finding an anchor still re-centres exactly as before.
    """

    _template = Template("""
        {% macro script(this, kwargs) %}
        (function (map) {
            try {
                var key = "rgv2_view", token = {{ this.token_json }};
                var saved = JSON.parse(window.sessionStorage.getItem(key) || "null");
                if (saved && saved.token === token) { map.setView(saved.center, saved.zoom, {animate: false}); }
                map.on("moveend", function () {
                    try {
                        var c = map.getCenter();
                        window.sessionStorage.setItem(key, JSON.stringify({token: token, center: [c.lat, c.lng], zoom: map.getZoom()}));
                    } catch (e) {}
                });
            } catch (e) {}
        })({{ this._parent.get_name() }});
        {% endmacro %}
        """)

    def __init__(self, token: str):
        super().__init__()
        self._name = "ViewMemory"
        self.token_json = _json_js(token)


class LegendBox(MacroElement):
    """One fixed box (bottom-left) holding the legend sections of every layer that is on."""

    _template = Template("{% macro html(this, kwargs) %}{{ this.box_html }}{% endmacro %}")

    def __init__(self, sections: Sequence[str]):
        super().__init__()
        self._name = "LegendBox"
        self.box_html = (
            '<div style="position:fixed; bottom:18px; left:12px; z-index:9999; max-width:250px; '
            'background:rgba(255,255,255,0.93); border:1px solid rgba(11,11,11,0.10); '
            'border-radius:8px; padding:8px 10px; font-size:12px; color:#0b0b0b; '
            'box-shadow:0 1px 4px rgba(0,0,0,0.18); line-height:1.45; '
            'font-family:system-ui, -apple-system, sans-serif;">'
            + '<div style="height:6px;"></div>'.join(sections)
            + "</div>"
        )


def _legend_swatch_row(color_css: str, label: str, extra_style: str = "") -> str:
    """HTML แถวเดียวของ legend: สี่เหลี่ยมสี + ป้ายข้อความ."""
    return (
        '<div style="display:flex; align-items:center; gap:6px; margin:1px 0;">'
        f'<span style="display:inline-block; width:14px; height:14px; border-radius:3px; '
        f'background:{color_css}; {extra_style}"></span>'
        f'<span>{label}</span></div>'
    )


# ------------------------------------------------------------------ layer drawing (one function per layer)
def _always(_ctx: Ctx) -> bool:
    return True


def draw_traffic(_ctx: Ctx) -> Any:
    return folium.TileLayer(
        tiles="https://mt1.google.com/vt?lyrs=h,traffic&x={x}&y={y}&z={z}",
        attr="Google Traffic", name="Google Traffic", overlay=True,
    )


def _wms(layers: str, name: str, opacity_key: Optional[str] = None) -> Callable[[Ctx], Any]:
    """Longdo WMS overlay (tiles are fetched by the browser only while the layer is on)."""
    def draw(ctx: Ctx) -> Any:
        return folium.WmsTileLayer(
            url=LONGDO_WMS_URL, layers=layers, name=name, fmt="image/png", transparent=True,
            version="1.1.1", attr=f"{name} / Longdo Map", show=True,
            opacity=float(ctx.show.get(opacity_key, 1.0)) if opacity_key else 1.0,
        )
    return draw


def draw_anchor_boundary(ctx: Ctx) -> Any:
    anchor = ctx.anchor
    group = folium.FeatureGroup(name="Automated Anchor study boundary", show=True)
    folium.Circle(anchor["study_center"], radius=anchor["study_radius_m"],
                  color="#184f95", fill=False, tooltip="Study boundary").add_to(group)
    return group


def draw_evidence_zone(ctx: Ctx) -> Any:
    evidence = ctx.evidence
    peak = evidence["plan"].get("peak")
    group = folium.FeatureGroup(name="Peak colour zone (ผังสีสูงสุด)", show=True)
    zone_color = "#d62828" if not peak else "#%02x%02x%02x" % tuple(peak["rgb"])
    for zone in evidence["plan"].get("zones", []):
        if zone.get("polygon"):
            folium.GeoJson(
                {"type": "Feature", "properties": {}, "geometry": zone["polygon"]},
                style_function=lambda _f, c=zone_color: {"color": c, "weight": 2, "fillColor": c,
                                                         "fillOpacity": 0.25, "dashArray": "6"},
                tooltip=f"ผังสีสูงสุด{(' ' + escape(str(peak['name']))) if peak else ''} ≈ {zone['area_km2']:.2f} ตร.กม.",
            ).add_to(group)
    return group


def draw_evidence_clusters(ctx: Ctx) -> Any:
    group = folium.FeatureGroup(name="Parcel clusters (แปลงถี่)", show=True)
    for cluster in ctx.evidence.get("clusters", []):
        if cluster.get("polygon"):
            folium.GeoJson(
                {"type": "Feature", "properties": {}, "geometry": cluster["polygon"]},
                style_function=lambda _f, top=(cluster["rank"] == 1): {
                    "color": "#7b2cbf", "weight": 3 if top else 1, "fillColor": "#7b2cbf",
                    "fillOpacity": 0.45 if top else 0.2},
                tooltip=(f"#{cluster['rank']} cluster แปลงเล็กถี่ · คะแนน {cluster['score']:.2f} · "
                         f"{cluster['area_ha']:,.0f} เฮกตาร์"),
            ).add_to(group)
    return group


def draw_rent_rings(ctx: Ctx) -> Any:
    rings = ctx.rent["rings_geojson"]
    ring_feats = rings.get("features") or []
    has_nodes_label = bool(ring_feats and "nodes_label" in ring_feats[0].get("properties", {}))
    tooltip_fields = ["band", "rent_label"]
    tooltip_aliases = ["ระยะจาก CBD:", "ค่าเช่าคาดการณ์:"]
    if has_nodes_label:
        tooltip_fields.append("nodes_label")
        tooltip_aliases.append("โหนด Network:")
    return folium.GeoJson(
        rings,
        name="Rent Gradient Rings",
        style_function=lambda x: {
            "fillColor": x["properties"]["color"],
            "color": x["properties"]["color"],
            "weight": 1,
            "fillOpacity": RENT_CONFIG["ring_fill_opacity"],
        },
        tooltip=folium.GeoJsonTooltip(fields=tooltip_fields, aliases=tooltip_aliases, localize=True),
    )


def draw_rent_heat(ctx: Ctx) -> Any:
    nodes = ctx.rent["rent_nodes_geojson"]
    rows = lru_get(ctx.cache, ("rows", "rent_heat", id(nodes)), nodes, lambda: _json_js(
        point_rows(nodes["features"], "color", 3, ("rent",), stroke_key="color")))
    group = folium.FeatureGroup(name="Rent Heat (Nodes)", show=True)
    CompactPoints(rows, heads=("ค่าเช่าคาดการณ์:",), weight=1, fill_opacity=0.85).add_to(group)
    return group


def draw_betweenness(ctx: Ctx) -> Any:
    edges = ctx.net["edges"]
    rows = lru_get(ctx.cache, ("rows", "betweenness", id(edges)), edges, lambda: _json_js(
        line_rows(edges["features"], "color", "stroke_weight", ("betweenness",))))
    group = folium.FeatureGroup(name="Road Betweenness", show=True)
    CompactLines(rows, heads=("Betweenness Score:",), opacity=0.8).add_to(group)
    return group


def draw_closeness(ctx: Ctx) -> Any:
    nodes = ctx.net["nodes"]
    rows = lru_get(ctx.cache, ("rows", "closeness", id(nodes)), nodes, lambda: _json_js(
        point_rows(nodes["features"], "color", "radius", ("closeness",), stroke="#000000")))
    group = folium.FeatureGroup(name="Node Integration", show=True)
    CompactPoints(rows, heads=("Integration Score:",), weight=1, fill_opacity=0.9).add_to(group)
    return group


def draw_golden(ctx: Ctx) -> Any:
    return folium.GeoJson(
        ctx.net["golden_spots_geojson"],
        name="Golden Land Spots",
        marker=folium.CircleMarker(),
        style_function=lambda x: {
            "fillColor": "#FFD60A",
            "color": "#8C6A00",
            "weight": 2,
            "radius": max(5, 12 - x["properties"]["rank"]),
            "fillOpacity": 0.85,
        },
        tooltip=folium.GeoJsonTooltip(fields=["rank", "score"], aliases=["Rank:", "Opportunity Score:"], localize=True),
    )


def draw_top_node(ctx: Ctx) -> Any:
    top = ctx.net["top_node"]
    group = folium.FeatureGroup(name="Integration Center (จุดตรงกลางที่สุด)", show=True)
    folium.Marker(
        [top["lat"], top["lon"]],
        popup=f"🏆 Center (Score: {top['score']:.4f})",
        icon=folium.Icon(color="orange", icon="star", prefix="fa"),
        tooltip="จุดที่อยู่ตรงกลางที่สุด",
    ).add_to(group)
    return group


def draw_travel_areas(ctx: Ctx) -> Any:
    clrs = ctx.colors
    return folium.GeoJson(
        ctx.iso,
        name="Travel Areas",
        style_function=lambda x: {
            "fillColor": get_fill_color(x["properties"]["travel_time_minutes"], clrs),
            "color": get_border_color(x["properties"]["original_index"]),
            "weight": 1,
            "fillOpacity": 0.2,
        },
    )


def draw_cbd_zone(ctx: Ctx) -> Any:
    return folium.GeoJson(
        ctx.inter,
        name="CBD Zone",
        style_function=lambda _x: {
            "fillColor": "#FFD700",
            "color": "#FF8C00",
            "weight": 3,
            "fillOpacity": 0.6,
            "dashArray": "5, 5",
        },
    )


def draw_railway(_ctx: Ctx) -> Any:
    railway_geojson = _parse_kml_to_geojson()
    if not (railway_geojson and railway_geojson.get("features")):
        return None
    return folium.GeoJson(
        railway_geojson,
        name="แนวรถไฟเชียงของ",
        style_function=lambda _x: {
            "color": "#E63946",
            "weight": 4,
            "opacity": 0.85,
            "dashArray": "8, 4",
            "fillOpacity": 0,
        },
        tooltip="แนวเวนคืนรถไฟเด่นชัย-เชียงราย-เชียงของ",
    )


def draw_cbd_anchor(ctx: Ctx) -> Any:
    """Automated anchors (composite / closeness / evidence) — or the Rent Gradient's own anchor when none."""
    group = folium.FeatureGroup(name="CBD Anchor", show=True)
    if ctx.anchor:
        anchor = ctx.anchor["anchor"]
        folium.Marker(
            [anchor["lat"], anchor["lon"]], tooltip="Automated CBD Anchor",
            popup=folium.Popup(f"<b>Automated CBD Anchor</b><br>Score: {anchor['score']:.4f}"
                               f"<br>Junctions / 500 m: {anchor['junction_count']}"
                               + _stability_popup(ctx.anchor), max_width=280),
            icon=folium.Icon(color="darkblue", icon="building", prefix="fa"),
        ).add_to(group)
    if ctx.anchor_closeness:
        anchor = ctx.anchor_closeness["anchor"]
        folium.Marker(
            [anchor["lat"], anchor["lon"]],
            tooltip="Automated CBD Anchor — Closeness 100%",
            popup=folium.Popup(
                f"<b>Automated CBD Anchor — Closeness 100%</b>"
                f"<br>Closeness norm: {anchor['closeness_norm']:.6f}"
                f"<br>Closeness: {anchor['closeness']:.8f} 1/m"
                f"<br>Degree: {anchor['degree']} (diagnostic)"
                f"<br>Junctions / 500 m: {anchor['junction_count']} (diagnostic)"
                + _stability_popup(ctx.anchor_closeness),
                max_width=320,
            ),
            icon=folium.Icon(color="green", icon="bullseye", prefix="fa"),
        ).add_to(group)
    if ctx.evidence:
        anchor, confidence = ctx.evidence["evidence_anchor"], ctx.evidence["confidence"]
        folium.Marker(
            [anchor["lat"], anchor["lon"]], tooltip="Automated CBD Anchor — Evidence",
            popup=folium.Popup(
                f"<b>Automated CBD Anchor — Evidence</b><br>Confidence: {escape(str(confidence['level']))}"
                f"<br>Cluster score: {anchor['score']:.3f}"
                f"<br>Parcel coverage: {anchor['coverage']:.0%}"
                + "".join(f"<br>• {escape(str(reason))}" for reason in confidence["reasons"]), max_width=360),
            icon=folium.Icon(color="purple", icon="star", prefix="fa"),
        ).add_to(group)
    if ctx.rent and not ctx.anchor:
        rent_anchor, rent_model = ctx.rent["anchor"], ctx.rent["model"]
        folium.Marker(
            [rent_anchor["lat"], rent_anchor["lon"]],
            tooltip=f"จุดยึด CBD — {escape(str(rent_anchor['source']))}",
            popup=folium.Popup(
                f"<b>CBD Anchor</b><br>{escape(str(rent_anchor['source']))}<br>"
                f"R₀ = {format_rent_value(rent_model['r0'], rent_model)}",
                max_width=260,
            ),
            icon=folium.Icon(color="darkblue", icon="building", prefix="fa"),
        ).add_to(group)
    return group


def draw_markers(ctx: Ctx) -> Any:
    group = folium.FeatureGroup(name="หมุดของฉัน", show=True)
    rent_model = ctx.rent["model"] if ctx.rent else None
    rent_anchor = ctx.rent["anchor"] if ctx.rent else None
    for i, marker in enumerate(ctx.markers):
        active = marker.get("active", True)
        popup_html = f"<b>จุดที่ {i+1}</b>"
        if rent_model and rent_anchor:
            d_km = haversine_km(rent_anchor["lat"], rent_anchor["lon"], marker["lat"], marker["lng"])
            est = predict_rent(d_km, rent_model["r0"], rent_model["lam"])
            popup_html += (
                f"<br>ระยะจาก CBD: {d_km:.2f} km"
                f"<br>ประเมิน: {format_rent_value(est, rent_model)}"
            )
        folium.Marker(
            [marker["lat"], marker["lng"]],
            popup=folium.Popup(popup_html, max_width=260),
            icon=folium.Icon(
                color=MARKER_COLORS[i % len(MARKER_COLORS)] if active else "gray",
                icon="map-marker" if active else "ban",
                prefix="fa",
            ),
        ).add_to(group)
    return group


# ------------------------------------------------------------------ legend sections
def legend_travel_areas(ctx: Ctx) -> str:
    clrs = ctx.colors
    return "".join([
        '<div style="font-weight:600; margin-bottom:2px;">เวลาเดินทาง</div>',
        _legend_swatch_row(clrs["step1"], "≤ 10 นาที"),
        _legend_swatch_row(clrs["step2"], "≤ 20 นาที"),
        _legend_swatch_row(clrs["step3"], "≤ 30 นาที"),
        _legend_swatch_row(clrs["step4"], "> 30 นาที"),
    ])


def legend_cbd_zone(_ctx: Ctx) -> str:
    return _legend_swatch_row("#FFD700", "CBD Zone", "border:2px dashed #FF8C00;")


def legend_golden(ctx: Ctx) -> str:
    if not (ctx.net and ctx.net.get("golden_spots")):
        return ""
    return _legend_swatch_row("#FFD60A", "💎 Golden Spot", "border:2px solid #8C6A00; border-radius:50%;")


def legend_rent_rings(ctx: Ctx) -> str:
    model = ctx.rent["model"]
    unit = "ดัชนี" if model["is_index"] else model["unit"]
    return (
        '<div style="font-weight:600; margin:4px 0 2px;">Rent Gradient</div>'
        '<div style="display:flex; align-items:center; gap:6px;">'
        f'<span style="display:inline-block; width:56px; height:10px; border-radius:3px; '
        f'background:linear-gradient(90deg, {RENT_RAMP[-1]}, {RENT_RAMP[0]});"></span>'
        f'<span>CBD → ขอบ ({escape(str(unit))})</span></div>'
    )


# ------------------------------------------------------------------ layer options (widgets under a checkbox)
def _options_cityplan(_ctx: Ctx, locked: bool) -> None:
    st.slider("ความโปร่งใส (ผังเมือง)", 0.2, 1.0, key="cityplan_opacity", disabled=locked)


# ------------------------------------------------------------------ Space Syntax layer
SS_TIP_HEADS: Tuple[str, ...] = ("ถนน:", "คะแนน (0–100):", "ค่าดัชนี:", "segment ในรัศมี:")
SS_DISPLAY_KEYS: Tuple[str, ...] = ("ss_measure", "ss_view_radius", "ss_palette", "ss_scale", "ss_thick", "ss_topn")


@dataclass(frozen=True)
class SpaceSyntaxView:
    """The loaded road network, its analysis and how to display it (read-only; built by ``build_ctx``)."""

    net: Any                    # SegmentNetwork
    meta: Dict[str, Any]        # where the network came from (source, centre, radius, network type)
    result: Any                 # AnalysisResult
    mask: Any                   # bool per segment: shown (inside the display radius)
    display: Dict[str, Any]     # measure, rkey, palette, scale, thick, top_n — already validated


def ss_display(show: Dict[str, Any], result: Any) -> Dict[str, Any]:
    """Display options for ``result``; anything missing or no longer valid falls back to a sensible default."""
    measures = ["integration"] + (["choice"] if result.with_choice else [])
    keys = [radius_key(r) for r in result.radii]
    measure = show.get("ss_measure") if show.get("ss_measure") in measures else "integration"
    rkey = show.get("ss_view_radius") if show.get("ss_view_radius") in keys else ("n" if "n" in keys else keys[-1])
    top_n = show.get("ss_topn")
    return {
        "measure": measure, "rkey": rkey,
        "palette": show.get("ss_palette") if show.get("ss_palette") in PALETTES else DEFAULT_PALETTE,
        "scale": show.get("ss_scale") if show.get("ss_scale") in SCALE_MODES else "linear",
        "thick": bool(show.get("ss_thick", True)),
        "top_n": int(ANALYSIS_CONFIG["top_n"] if top_n is None else top_n),
    }


def ss_line_rows(net: Any, columns: Dict[str, Any], mask: Any) -> List[list]:
    """Compact map rows of the masked segments (colour, weight, escaped tooltip values, flat lat/lon)."""
    rows: List[list] = []
    for s in np.flatnonzero(mask):
        flat = np.round(net.seg_lonlat[s][:, ::-1], COORD_DECIMALS).ravel().tolist()      # lon,lat → lat,lon
        rows.append([columns["color"][s], float(columns["weight"][s]),
                     [escape(str(columns["label"][s])), _short(float(columns["score"][s])),
                      _short(float(columns["value"][s])), int(columns["nc"][s])], flat])
    return rows


def ss_payload(ctx: Ctx) -> Dict[str, Any]:
    """Everything the map layer, legend and views need for the current display options.

    Built once per (analysis result, options) and kept in the session LRU, so ticking other layers, changing the
    view or rerunning for any other reason never rebuilds the scores, colours or the segment rows.
    """
    view = ctx.ss
    d = view.display
    key = ("ss", d["measure"], d["rkey"], d["palette"], d["scale"], d["thick"], d["top_n"])

    def build() -> Dict[str, Any]:
        result = view.result
        values = result.integration[d["rkey"]] if d["measure"] == "integration" else result.choice_norm[d["rkey"]]
        nc = result.nc[d["rkey"]]
        scaled = scale_scores(values, d["scale"], view.mask)
        columns = _display_columns(view.net, scaled, values, nc, d["palette"], d["thick"])
        top = _top_rows(view.net, scaled, values, nc, view.mask, d["top_n"]) if d["top_n"] else []
        return {"values": values, "nc": nc, "scaled": scaled, "columns": columns, "top": top,
                "rows_json": _json_js(ss_line_rows(view.net, columns, view.mask))}

    return lru_get(ctx.cache, key, view.result, build)


def draw_space_syntax(ctx: Ctx) -> Any:
    """Every road segment coloured by its score (red = easiest to reach … blue = hardest), plus the display circle
    and the top-N pins."""
    view, payload = ctx.ss, ss_payload(ctx)
    group = folium.FeatureGroup(name="🧭 Space Syntax (ไล่สีตามคะแนน)", show=True)
    CompactLines(payload["rows_json"], heads=SS_TIP_HEADS, opacity=0.95, hover=True).add_to(group)
    meta = view.meta
    if meta.get("radius_m"):
        folium.Circle([meta["lat"], meta["lon"]], radius=meta["radius_m"], color="#8a8a8a", weight=1.5,
                      dash_array="6", fill=False, tooltip="ขอบเขตที่แสดงผล").add_to(group)
    for row in payload["top"]:
        folium.Marker(
            [row["lat"], row["lon"]],
            tooltip=f"#{row['rank']} · คะแนน {row['score']:.1f} · {escape(str(row['label']))}",
            icon=folium.DivIcon(html=(
                '<div style="width:22px;height:22px;line-height:20px;border-radius:50%;text-align:center;'
                'background:#fff;color:#b00020;border:2px solid #b00020;font:700 11px system-ui;">'
                f"{row['rank']}</div>"), icon_size=(22, 22), icon_anchor=(11, 11)),
        ).add_to(group)
    return group


def legend_space_syntax(ctx: Ctx) -> str:
    payload, d = ss_payload(ctx), ctx.ss.display
    ticks = payload["scaled"]["ticks"]
    if not ticks:
        return ""
    return (
        f'<div style="font-weight:600; margin-bottom:4px;">{MEASURES[d["measure"]]["title"]} (คะแนน 0–100)</div>'
        f'<div style="height:12px; border-radius:3px; background:{gradient_css(d["palette"])};"></div>'
        '<div style="display:flex; justify-content:space-between; margin-top:2px;">'
        f'<span>🔵 ต่ำ {ticks[0][1]:.2f}</span><span>{ticks[-1][1]:.2f} สูง 🔴</span></div>'
        f'<div style="margin-top:3px; color:#555;">{SCALE_MODES[d["scale"]]} · {radius_label_for(d["rkey"])}</div>'
    )


def radius_label_for(rkey: str) -> str:
    return radius_label(None if rkey == "n" else float(rkey))


def _options_space_syntax(ctx: Ctx, locked: bool) -> None:
    """How the Space Syntax layer is shown (changing these never recomputes the analysis)."""
    view = ctx.ss
    if view is None:
        st.caption("รัน 🧮 วิเคราะห์ Space Syntax ที่แผง ④ ก่อน แล้วเลือกตัวชี้วัด/รัศมี/สีได้ที่นี่")
        return
    result = view.result
    measures = ["integration"] + (["choice"] if result.with_choice else [])
    keys = [radius_key(r) for r in result.radii]
    labels = {radius_key(r): radius_label(r) for r in result.radii}
    for widget_key, valid, fallback in (("ss_measure", measures, "integration"),
                                        ("ss_view_radius", keys, "n" if "n" in keys else keys[-1])):
        if st.session_state.get(widget_key) not in valid:                # a fresh analysis changed the choices
            st.session_state[widget_key] = fallback
    st.radio("ตัวชี้วัด", measures, horizontal=True, key="ss_measure", disabled=locked,
             format_func=lambda m: f"{MEASURES[m]['title']} — {MEASURES[m]['thai']}")
    st.selectbox("รัศมีที่แสดง", keys, key="ss_view_radius", disabled=locked, format_func=labels.get)
    st.caption(MEASURES[view.display["measure"]]["hint"])
    st.selectbox("ชุดสี", list(PALETTES), key="ss_palette", disabled=locked)
    st.radio("สเกลสี", list(SCALE_MODES), key="ss_scale", format_func=SCALE_MODES.get, disabled=locked,
             help="Quantile กระจายสีเท่ากันทุกช่วง เห็นความต่างในย่านที่ค่าใกล้กันชัดขึ้น")
    st.checkbox("เส้นหนาตามคะแนน", key="ss_thick", disabled=locked)
    st.slider("จำนวนจุดคะแนนสูงสุดที่แสดง", 0, 25, key="ss_topn", disabled=locked)
    st.caption("แนะนำพื้นหลัง “พื้นดำ (เหมือน depthmap)” ในสไตล์แผนที่ด้านบน")


# ------------------------------------------------------------------ the registry (bottom → top)
LAYERS: Tuple[Layer, ...] = (
    # tile overlays first: the browser always paints tiles below vector layers
    Layer("traffic", "Google Traffic", "บริบท & overlay", draw_traffic, _always, show_key="show_traffic",
          label="🚦 การจราจร (Google Traffic)"),
    Layer("wms_population", "ความหนาแน่นประชากร", "บริบท & overlay",
          _wms("thailand_population", "ความหนาแน่นประชากร"), _always, show_key="show_population",
          label="👥 ความหนาแน่นประชากร"),
    Layer("wms_cityplan", "ผังเมืองรวม", "บริบท & overlay", _wms("cityplan_dpt", "ผังเมืองรวม", "cityplan_opacity"),
          _always, show_key="show_cityplan", label="🏙️ ผังเมืองรวม", options=_options_cityplan),
    Layer("wms_dol", "รูปแปลงที่ดิน", "บริบท & overlay", _wms("dol", "รูปแปลงที่ดิน"), _always,
          show_key="show_dol", label="📜 รูปแปลงที่ดิน"),
    # automated-anchor details: small, unticked by default — they stay on the map's LayerControl (start_hidden)
    # exactly as before, and the checkbox now also decides whether they start visible
    Layer("anchor_boundary", "Automated Anchor study boundary", "Automated Anchor", draw_anchor_boundary,
          lambda c: bool(c.anchor), show_key="show_anchor_boundary", label="⭕ ขอบเขตพื้นที่ศึกษา (Anchor)",
          requires="ค้นหา CBD Anchor อัตโนมัติก่อน", start_hidden=True),
    Layer("evidence_zone", "Peak colour zone (ผังสีสูงสุด)", "Automated Anchor", draw_evidence_zone,
          lambda c: bool(c.evidence), show_key="show_evidence_zone", label="🟥 โซนผังสีสูงสุด (Evidence)",
          requires="เปิด Evidence แล้วค้นหา Anchor", start_hidden=True),
    Layer("evidence_clusters", "Parcel clusters (แปลงถี่)", "Automated Anchor", draw_evidence_clusters,
          lambda c: bool(c.evidence), show_key="show_evidence_clusters", label="🟪 cluster แปลงถี่ (Evidence)",
          requires="เปิด Evidence แล้วค้นหา Anchor", start_hidden=True),
    Layer("rent_rings", "Rent Gradient Rings", "Rent Gradient", draw_rent_rings,
          lambda c: bool(c.rent and c.rent.get("rings_geojson")), show_key="show_rent_rings",
          label="🌈 Rent Rings (วงแหวนราคา)", requires="คำนวณ Rent Gradient ก่อน",
          legend=legend_rent_rings, legend_rank=60),
    Layer("rent_heat", "Rent Heat (Nodes)", "Rent Gradient", draw_rent_heat,
          lambda c: bool(c.rent and c.rent.get("rent_nodes_geojson")), show_key="show_rent_nodes",
          label="🔥 Rent Heat (โหนดถนน)", hint="Rent Heat ต้องรัน Network Analysis ก่อน",
          requires="รัน Network Analysis แล้วคำนวณ Rent Gradient"),
    Layer("betweenness", "Road Betweenness", "โครงข่ายถนน", draw_betweenness,
          lambda c: bool(c.net and c.net.get("edges")), show_key="show_betweenness",
          label="Show Roads (Betweenness)", hint="🔴: ทางผ่านหลัก (High Traffic Flow)",
          requires="รัน Network Analysis ก่อน"),
    Layer("closeness", "Node Integration", "โครงข่ายถนน", draw_closeness,
          lambda c: bool(c.net and c.net.get("nodes")), show_key="show_closeness",
          label="Show Nodes (Integration)", hint="⚫: จุดเข้าถึงง่าย (Central Hub)",
          requires="รัน Network Analysis ก่อน"),
    Layer("golden", "Golden Land Spots", "โครงข่ายถนน", draw_golden,
          lambda c: bool(c.net and c.net.get("golden_spots_geojson")), show_key="show_golden_spots",
          label="Show Golden Spots", hint="💎: จุดทำเลที่ดินทอง (คะแนนรวมสูง)",
          requires="รัน Network Analysis ก่อน", legend=legend_golden, legend_rank=40),
    Layer("travel_areas", "Travel Areas", "โครงข่ายถนน", draw_travel_areas, lambda c: bool(c.iso),
          legend=legend_travel_areas, legend_rank=10),
    Layer("cbd_zone", "CBD Zone", "โครงข่ายถนน", draw_cbd_zone, lambda c: bool(c.inter),
          legend=legend_cbd_zone, legend_rank=20),
    Layer("space_syntax", "🧭 Space Syntax (ไล่สีตามคะแนน)", "โครงข่ายถนน", draw_space_syntax,
          lambda c: c.ss is not None, show_key="show_space_syntax", label="🧭 Space Syntax (แดง→น้ำเงิน)",
          hint="🔴 เข้าถึงง่ายที่สุด → 🔵 เข้าถึงยากที่สุด", requires="วิเคราะห์ Space Syntax ที่แผง ④ ก่อน",
          legend=legend_space_syntax, legend_rank=30, options=_options_space_syntax, panel_rank=10),
    Layer("railway", "แนวรถไฟเชียงของ", "บริบท & overlay", draw_railway, _always, show_key="show_railway",
          label="🚂 แนวรถไฟเชียงของ"),
    Layer("top_node", "Integration Center (จุดตรงกลางที่สุด)", "โครงข่ายถนน", draw_top_node,
          lambda c: bool(c.net and c.net.get("top_node"))),
    Layer("cbd_anchor", "CBD Anchor", "Automated Anchor", draw_cbd_anchor,
          lambda c: bool(c.anchor or c.anchor_closeness or c.evidence or c.rent)),
    Layer("markers", "หมุดของฉัน", "บริบท & overlay", draw_markers, lambda c: bool(c.markers)),
)

SHOW_KEYS: Tuple[str, ...] = tuple(layer.show_key for layer in LAYERS if layer.show_key) + (
    "cityplan_opacity", "map_style_name") + SS_DISPLAY_KEYS


def build_ctx() -> Ctx:
    """Read the session once and freeze what the layers need."""
    state = st.session_state
    markers = StateManager.get_markers()
    net = StateManager.get_network_data()
    rent = StateManager.get_rent_data()
    automated = state.get(StateManager.K_AUTO_ANCHOR)
    closeness = state.get(StateManager.K_AUTO_ANCHOR_CLOSENESS)
    evidence = state.get(StateManager.K_AUTO_ANCHOR_EVIDENCE)
    if not (evidence and evidence.get("schema") == EVIDENCE_SCHEMA and evidence.get("evidence_anchor")):
        evidence = None
    if markers:
        center = (markers[-1]["lat"], markers[-1]["lng"])
    else:
        center = (DEFAULT_CONFIG["LAT"], DEFAULT_CONFIG["LON"])
    if automated:
        center = (automated["anchor"]["lat"], automated["anchor"]["lon"])
    elif closeness:
        center = (closeness["anchor"]["lat"], closeness["anchor"]["lon"])
    show = {key: state.get(key, StateManager._DEFAULTS.get(key)) for key in SHOW_KEYS}
    if show["map_style_name"] not in MAP_STYLES:
        show["map_style_name"] = next(iter(MAP_STYLES))
    cache = state.get("layer_cache")
    if cache is None:
        cache = state["layer_cache"] = OrderedDict()
    ss_view = None
    if state.get(SS_NET) is not None and state.get(SS_RESULT) is not None:
        ss_view = SpaceSyntaxView(net=state[SS_NET], meta=state.get(SS_META) or {}, result=state[SS_RESULT],
                                  mask=state[SS_MASK], display=ss_display(show, state[SS_RESULT]))
    return Ctx(
        markers=markers, colors=StateManager.get_colors(), iso=StateManager.get_isochrone_data(),
        inter=StateManager.get_intersection_data(),
        net=net if net and "error" not in net else None,
        rent=rent if rent and "error" not in rent else None,
        anchor=automated, anchor_closeness=closeness, evidence=evidence,
        show=show, center=center, ss=ss_view, cache=cache,
    )


def render_layers(ctx: Ctx, m: Any, layers: Optional[Sequence[Layer]] = None) -> Tuple[List[Layer], List[str]]:
    """Draw every enabled layer that has data onto ``m`` (bottom → top). One failing layer never blanks the map.

    Returns the layers that were drawn and one warning per layer that could not be.
    """
    drawn: List[Layer] = []
    warnings: List[str] = []
    for layer in (LAYERS if layers is None else layers):
        visible = not layer.show_key or bool(ctx.show.get(layer.show_key))
        if not visible and not layer.start_hidden:
            continue
        try:
            if not layer.available(ctx):
                continue
            element = layer.draw(ctx)          # built completely first …
            if element is None:
                continue
            if not visible:
                element.show = False           # small layers the old map kept as unticked LayerControl entries
            element.add_to(m)                  # … then attached, so a failure leaves nothing half-drawn
        except Exception as exc:
            warnings.append(f"{layer.title}: {type(exc).__name__}: {exc}")
            continue
        if visible:
            drawn.append(layer)
    return drawn, warnings


def legend_stack(ctx: Ctx, drawn: Sequence[Layer]) -> Optional[Any]:
    """One legend box for the layers that were drawn (``None`` when there is nothing to explain)."""
    sections: List[str] = []
    for layer in sorted((l for l in drawn if l.legend is not None), key=lambda l: l.legend_rank):
        try:
            html = layer.legend(ctx)
        except Exception:
            continue                           # a legend is never worth losing the map for
        if html:
            sections.append(html)
    return LegendBox(sections) if sections else None


def build_base_map(ctx: Ctx) -> Any:
    """Tiles + survey tools. Layers, view memory, layer control and legend are added by ``render_map``."""
    style = MAP_STYLES[ctx.show["map_style_name"]]
    m = folium.Map(
        location=list(ctx.center),
        zoom_start=14,
        tiles=style["tiles"],
        attr=style["attr"],
        prefer_canvas=True,               # thousands of road segments: canvas, not one SVG node each
        control_scale=True,
    )
    header = m.get_root().header
    header.add_child(folium.Element(TOOLTIP_STYLE))
    if style["tiles"] is None:
        header.add_child(folium.Element("<style>.leaflet-container{background:#000 !important;}</style>"))
    # ---- เครื่องมือสำรวจทำเล ----
    Fullscreen(position="topleft").add_to(m)
    MeasureControl(
        position="topleft",
        primary_length_unit="kilometers",
        secondary_length_unit="meters",
        primary_area_unit="sqmeters",
    ).add_to(m)
    MousePosition(
        position="bottomright",
        separator=" , ",
        num_digits=5,
        prefix="พิกัด:",
    ).add_to(m)
    return m


def render_map(ctx: Ctx) -> Optional[Dict[str, Any]]:
    """Build and display the Folium map. Returns the ``st_folium`` output dict."""
    m = build_base_map(ctx)
    drawn, warnings = render_layers(ctx, m)
    if REMEMBER_VIEW:
        ViewMemory(f"{ctx.center[0]:.5f},{ctx.center[1]:.5f}").add_to(m)
    folium.LayerControl().add_to(m)
    legend = legend_stack(ctx, drawn)
    if legend is not None:
        m.get_root().add_child(legend)
    # returned_objects จำกัดเฉพาะ last_clicked → เลื่อน/ซูมแผนที่ไม่ trigger
    # Streamlit rerun ทั้งหน้า (เร็วขึ้นมากบน Streamlit Cloud)
    output = st_folium(
        m,
        height=MAP_HEIGHT_PX,
        use_container_width=True,
        key="main_map",
        returned_objects=["last_clicked"],
    )
    for warning in warnings:
        st.warning(f"⚠️ แสดงชั้นนี้ไม่ได้ — {warning}")
    return output


def _render_sidebar_config_section(locked: bool) -> None:
    """Config Import / Export expander."""
    with st.expander("💾 จัดการ Config (Export/Import)", expanded=False):
        # สร้าง bundle เฉพาะเมื่อผู้ใช้กดปุ่ม — ไม่ zip cache ก้อนใหญ่ทุก rerun
        if st.button("📦 เตรียม Bundle (.zip)", use_container_width=True, disabled=locked):
            st.session_state["_bundle_bytes"] = export_bundle_zip()
        if st.session_state.get("_bundle_bytes"):
            st.download_button(
                "⬇ Download Bundle (.zip)",
                st.session_state["_bundle_bytes"],
                "rent_gradient_bundle.zip",
                "application/zip",
                use_container_width=True,
                disabled=locked,
            )

        uploaded_bundle = st.file_uploader(
            "Upload Bundle (.zip)",
            type=["zip"],
            key="bundle_uploader",
        )
        if uploaded_bundle and st.button("ยืนยันการโหลด Bundle", use_container_width=True, disabled=locked):
            bundle_result = import_bundle_zip(uploaded_bundle.read())
            if bundle_result["success"]:
                mode = "config + cache" if bundle_result["cache_loaded"] else "config เท่านั้น"
                st.toast(f"✅ โหลด Bundle สำเร็จ ({mode})", icon="📦")
                for warn in bundle_result["warnings"]:
                    st.warning(warn)
                st.rerun()
            else:
                for err in bundle_result["errors"]:
                    st.error(err)

        st.markdown("---")
        st.markdown("##### Import Bundle from GitHub")
        st.caption("แหล่งข้อมูลคงที่: เชียงของ.zip")
        if st.button("นำเข้า Bundle จาก GitHub", use_container_width=True, disabled=locked):
            bundle_bytes, err = download_github_bundle()
            if err:
                st.error(err)
            elif not bundle_bytes:
                st.error("ไม่พบข้อมูล Bundle จาก GitHub")
            else:
                bundle_result = import_bundle_zip(bundle_bytes)
                if bundle_result["success"]:
                    mode = "config + cache" if bundle_result["cache_loaded"] else "config เท่านั้น"
                    st.toast(f"✅ โหลด Bundle จาก GitHub สำเร็จ ({mode})", icon="📥")
                    for warn in bundle_result["warnings"]:
                        st.warning(warn)
                    st.rerun()
                else:
                    for err_msg in bundle_result["errors"]:
                        st.error(err_msg)


def _render_sidebar_marker_input(locked: bool) -> None:
    """Manual coordinate input row."""
    c1, c2 = st.columns([0.7, 0.3])
    coords_input = c1.text_input(
        "Coords",
        placeholder="20.21, 100.40",
        label_visibility="collapsed",
        key="manual_coords",
        disabled=locked,
    )
    if c2.button("เพิ่ม", use_container_width=True, disabled=locked):
        try:
            lat_str, lng_str = coords_input.strip().split(",")
            StateManager.add_marker(float(lat_str), float(lng_str))
            StateManager.clear_results(["isochrone", "intersection", "rent"])
            st.rerun()
        except Exception:
            st.error("Format: Lat, Lng")


def _render_sidebar_marker_list(locked: bool) -> List[Tuple[int, Dict[str, Any]]]:
    """Render the marker list with toggle / delete controls. Returns active_list."""
    markers = StateManager.get_markers()

    # Delete last / Reset buttons
    c1, c2 = st.columns(2)
    if c1.button("❌ ลบจุดล่าสุด", use_container_width=True, disabled=locked) and markers:
        StateManager.pop_last_marker()
        StateManager.clear_results(["isochrone", "intersection", "rent"])
        st.rerun()
    if c2.button("🔄 รีเซ็ต", use_container_width=True, disabled=locked):
        StateManager.reset()
        st.rerun()

    active_list = StateManager.get_active_markers()
    st.write(f"📍 Active Markers: **{len(active_list)}**")

    if markers:
        st.markdown("---")
        for i, m in enumerate(markers):
            col1, col2, col3 = st.columns([0.15, 0.70, 0.15])

            prev_active = m.get("active", True)
            is_active = col1.checkbox(
                " ",
                value=prev_active,
                key=f"active_chk_{i}",
                label_visibility="collapsed",
                disabled=locked,
            )

            if is_active != prev_active:
                StateManager.set_marker_active(i, is_active)
                StateManager.clear_results(["isochrone", "intersection", "rent"])

            if is_active:
                style = (
                    f"color:{MARKER_COLORS[i % len(MARKER_COLORS)]}; font-weight:bold;"
                )
            else:
                style = "color:gray; text-decoration:line-through;"
            col2.markdown(
                f"<span style='{style}'>● จุดที่ {i+1}</span> "
                f"<span style='font-size:0.8em'>({m['lat']:.4f}, {m['lng']:.4f})</span>",
                unsafe_allow_html=True,
            )

            if col3.button("✕", key=f"del_btn_{i}", disabled=locked):
                StateManager.remove_marker(i)
                StateManager.clear_results(["isochrone", "intersection", "rent"])
                st.rerun()

    # Refresh active list after possible mutations
    return StateManager.get_active_markers()


def _render_sidebar_network_panel(locked: bool) -> bool:
    """
    Render the Network Analysis expander (cache management + run button).

    Returns ``True`` if the user clicked **Run Network Analysis**.
    """
    with st.expander("🕸️ วิเคราะห์โครงข่าย (Network Analysis)", expanded=True):
        st.caption("วิเคราะห์ความสำคัญของถนน (OSMnx)")

        can_analyze = StateManager.get_isochrone_data() is not None
        if can_analyze:
            st.info("✅ **Scope:** พื้นที่ Travel Areas ทั้งหมด", icon="🗺️")
        else:
            st.warning("⚠️ **Scope:** กรุณาคำนวณ Isochrone ก่อน", icon="🛑")

        # ---- Cache Management ----
        cache_stats = get_cache_stats()
        st.markdown("##### 💾 Cache Management")

        if cache_stats["count"] > 0:
            st.caption(
                f"📊 **{cache_stats['count']} ไฟล์** "
                f"({cache_stats['size_mb']:.1f} MB)"
            )

            if st.button(
                "📤 Export Cache (.zip)",
                use_container_width=True,
                key="export_cache_btn",
                disabled=locked,
            ):
                st.session_state["_cache_zip_bytes"] = export_cache_as_zip()
            if st.session_state.get("_cache_zip_bytes"):
                st.download_button(
                    "⬇ Download Ready",
                    data=st.session_state["_cache_zip_bytes"],
                    file_name="osmnx_cache.zip",
                    mime="application/zip",
                    use_container_width=True,
                )

            if st.button(
                "🗑️ ล้าง Cache",
                use_container_width=True,
                type="secondary",
                disabled=locked,
            ):
                clear_disk_cache()
                st.toast("ล้าง Cache สำเร็จ!", icon="✅")
                st.rerun()
        else:
            st.caption("📊 **Cache ว่างเปล่า**")


        st.markdown("---")
        do_network: bool = st.button(
            "🚀 Run Network Analysis",
            use_container_width=True,
            disabled=(not can_analyze) or locked,
        )

        # ---- Network results preview ----
        net_data = StateManager.get_network_data()
        if net_data and net_data.get("top_node"):
            top = net_data["top_node"]
            stats = net_data.get("stats", {})
            st.markdown("---")
            st.markdown("**🏆 จุดที่อยู่ตรงกลางที่สุด (Integration Center)**")
            st.caption(f"Score: {top['score']:.4f}")
            if stats.get("used_approximation"):
                st.caption("⚡ *ใช้ Approximation (กราฟขนาดใหญ่)*")
            closeness_method_labels = {
                "exact-scipy": "🧭 Closeness: exact (scipy, ถ่วงน้ำหนักเมตร)",
                "pivot-approx": "🧭 Closeness: pivot sampling (Eppstein–Wang)",
                "networkx-fallback": "🧭 Closeness: networkx fallback (ไม่มี scipy)",
            }
            method_label = closeness_method_labels.get(stats.get("closeness_method"))
            if method_label:
                st.caption(method_label)
            st.code(f"{top['lat']:.5f}, {top['lon']:.5f}")

            if st.button(
                "➕ เพิ่มจุดนี้ลงในรายการ",
                use_container_width=True,
                type="secondary",
                disabled=locked,
            ):
                StateManager.add_marker(top["lat"], top["lon"])
                StateManager.clear_results(["isochrone", "intersection", "rent"])
                st.toast("เพิ่มจุดใหม่เรียบร้อย! กรุณากดคำนวณใหม่", icon="✅")
                st.rerun()

        golden_spots = net_data.get("golden_spots") if net_data else None
        if golden_spots:
            st.markdown("---")
            st.markdown("**💎 ทำเลที่ดินทอง (ก่อนคนรู้)**")
            st.caption(
                "สมการคะแนน: 0.50×Closeness + 0.30×Degree + 0.20×(1-Betweenness)"
            )

            preview_lines = []
            for i, spot in enumerate(golden_spots[:5], start=1):
                preview_lines.append(
                    f"{i}. score={spot['score']:.4f} | "
                    f"{spot['lat']:.5f}, {spot['lon']:.5f}"
                )
            st.code("\n".join(preview_lines), language="text")

            best = golden_spots[0]
            if st.button(
                "➕ เพิ่มจุดทำเลที่ดินทองอันดับ 1",
                use_container_width=True,
                type="secondary",
                disabled=locked,
            ):
                StateManager.add_marker(best["lat"], best["lon"])
                StateManager.clear_results(["isochrone", "intersection", "rent"])
                st.toast("เพิ่มทำเลที่ดินทองแล้ว! กรุณากดคำนวณใหม่", icon="💎")
                st.rerun()

        st.caption("เปิด/ปิดชั้น Betweenness · Nodes · Golden Spots ที่แผง ⑥ ชั้นแผนที่")

    return do_network


def _sync_rent_samples_from_editor(edited_df: "pd.DataFrame") -> None:
    """แปลงตาราง data_editor → list ตัวอย่างราคา แล้ว sync เข้า session state."""
    new_samples: List[Dict[str, float]] = []
    for _, row in edited_df.iterrows():
        try:
            lat, lon, rent = float(row["lat"]), float(row["lon"]), float(row["rent"])
        except (TypeError, ValueError):
            continue
        if pd.isna(lat) or pd.isna(lon) or pd.isna(rent) or rent <= 0:
            continue
        new_samples.append({"lat": lat, "lon": lon, "rent": rent})

    if new_samples != StateManager.get_rent_samples():
        StateManager.set_rent_samples(new_samples)


_ANCHOR_CONTEXT_KEYS = ("study_center", "study_radius_m", "network_type")


def _anchor_search_context() -> Dict[str, Any]:
    return {
        "study_center": [st.session_state.anchor_lat, st.session_state.anchor_lon],
        "study_radius_m": st.session_state.anchor_radius_km * 1000,
        "network_type": TRAVEL_MODE_TO_NETWORK_TYPE.get(StateManager.get_travel_mode(), "drive"),
    }


def _anchor_context_matches(saved: Optional[Dict[str, Any]], current: Dict[str, Any]) -> bool:
    """Compare only the inputs that change the answer.

    Results saved by the earlier seeded search also carry ``random_seed`` and
    ``restarts``; those no longer matter and must not invalidate a saved result.
    """
    return bool(saved) and all(saved.get(k) == current.get(k) for k in _ANCHOR_CONTEXT_KEYS)


def _parse_anchor_center_input(value: str) -> Tuple[float, float]:
    """Parse a single "Lat, Lon" text field while preserving legacy state keys."""
    parts = [part.strip() for part in str(value).split(",")]
    example = "20.075226819421776, 100.5083729446834"
    if len(parts) != 2 or not all(parts):
        raise ValueError(f"กรุณากรอกพิกัดเป็น Lat, Lon เช่น {example}")
    try:
        lat, lon = (float(parts[0]), float(parts[1]))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"พิกัดไม่ถูกต้อง กรุณาใช้รูปแบบ Lat, Lon เช่น {example}") from exc
    if not (-85.0 <= lat <= 85.0):
        raise ValueError("Lat ต้องอยู่ระหว่าง -85 ถึง 85")
    if not (-180.0 <= lon <= 180.0):
        raise ValueError("Lon ต้องอยู่ระหว่าง -180 ถึง 180")
    return lat, lon


def _anchor_summary(label: str, result: Dict[str, Any], diagnostics: bool = False) -> None:
    """Compact, identical presentation for the composite and the Closeness-100% anchor."""
    anchor = result["anchor"]
    st.write(f"**{anchor['source']}** ({anchor['lat']:.6f}, {anchor['lon']:.6f})")
    st.caption(f"Score {anchor['score']:.4f} · {result['evaluated_nodes']} โหนดที่ประเมินแม่นยำ "
               f"จาก {result['candidate_nodes']} candidates")
    if diagnostics:
        st.caption(f"Closeness {anchor['closeness']:.8f} 1/m · Degree {anchor['degree']} · "
                   f"Junctions/500m {anchor['junction_count']} (diagnostics only)")
    st.caption("ตรวจคะแนนครบทุก candidate: ยืนยันคะแนนสูงสุดของ objective นี้แล้ว"
               if result.get("globally_certified")
               else "คัดด้วย pivot closeness แล้วประเมินแม่นยำ — ไม่รับรอง global optimum")
    effective = result.get("effective_weights")
    if effective and result.get("scoring") == "rank-v2":
        contribution = result["winner_contribution"]
        st.caption(
            "น้ำหนักที่มีผลจริงต่อการจัดอันดับ — "
            f"Closeness {effective['closeness']:.0%} · Degree {effective['degree']:.0%} · "
            f"Density {effective['density']:.0%} (ประกาศ 50/30/20); "
            f"สัดส่วนคะแนนที่ผู้ชนะ — {contribution['closeness']:.0%} / "
            f"{contribution['degree']:.0%} / {contribution['density']:.0%}"
        )
    stability = result.get("stability")
    if stability:
        badge = {"stable": "🟢 นิ่ง", "check": "🟡 ควรตรวจ", "unstable": "🔴 ไม่นิ่ง"}[stability["level"]]
        st.caption(
            f"ความนิ่งเมื่อวงศึกษาเปลี่ยน ±20% (ประมาณการ): {badge} — ขยับสูงสุด "
            f"{stability['max_drift_m']:.0f} ม. ({stability['max_drift_ratio']:.0%} ของรัศมี)"
        )
    for warning in result.get("warnings", []):
        st.warning(warning)


def _evidence_thumbnail(rgba: np.ndarray, size: int = 340) -> Any:
    """Cached window on a white card (transparent layers are invisible on a dark theme)."""
    from PIL import Image

    card = Image.new("RGBA", (rgba.shape[1], rgba.shape[0]), (255, 255, 255, 255))
    card.alpha_composite(Image.fromarray(rgba, "RGBA"))
    return card.convert("RGB").resize((size, size))


def _evidence_diagnostics(evidence: Dict[str, Any]) -> None:
    """What the stage actually read: the plan's dominant colours (and which count as red) and how many
    lots / how dense the parcels were — the numbers to look at when the answer looks wrong."""
    plan, parcel = evidence.get("plan") or {}, evidence.get("parcel") or {}
    with st.expander("วินิจฉัยการอ่านภาพ (สีผังเมือง + แปลงที่ดิน)"):
        explained = plan.get("explained")
        st.caption(f"ผังเมือง: {plan.get('state', '—')} · อ่านได้ {plan.get('tiles_ok', 0)}/{plan.get('tiles', 0)} ไทล์"
                   + (f" · legend อธิบายสีได้ {explained:.0%}" if explained is not None else ""))
        if plan.get("colours"):
            st.dataframe([{"สี": c["hex"], "สัดส่วน %": round(100 * c["share"], 1), "ตรง legend": c["legend"] or "—",
                           "นับเป็นแดง": c["red"]} for c in plan["colours"]], hide_index=True)
        if parcel.get("best_score") is not None:
            st.caption(f"แปลงที่ดิน: อ่านได้ {parcel.get('lots', 0):,} แปลงใน {parcel.get('tiles_ok', 0)}/"
                       f"{parcel.get('tiles_needed', 0)} ไทล์ · คะแนนความถี่สูงสุดในโซน {parcel['best_score']:.2f} · "
                       f"เกณฑ์ cluster {parcel['hot_threshold']:.2f}")
        elif parcel.get("tiles_needed"):
            st.caption(f"แปลงที่ดิน: อ่านได้ {parcel.get('lots', 0):,} แปลงใน {parcel.get('tiles_ok', 0)}/"
                       f"{parcel.get('tiles_needed', 0)} ไทล์ แต่ไม่มีเซลล์ที่วัดความถี่ได้")


def _evidence_summary(evidence: Dict[str, Any], composite: Optional[Dict[str, Any]]) -> None:
    """Peak colour, dense parcel cluster, confidence and stability of the evidence stage."""
    fetch = evidence.get("fetch", {})
    if evidence.get("schema") != EVIDENCE_SCHEMA:
        st.warning("ผลหลักฐานนี้มาจากเวอร์ชันเก่า (ยึดผู้สมัครจากถนน) — กดค้นหาอีกครั้งเพื่อคำนวณใหม่",
                   icon="⚠️")
        return
    if evidence.get("legend_source") == "provisional":
        st.warning("โซนแดงอ่านตามเฉดสี (ไม่ผูกกับ legend) แต่สีผังเมืองอื่นยังเป็นค่าชั่วคราว "
                   "(ยังไม่ calibrate กับภาพจริงของ Longdo) — ใช้เป็นหลักฐานประกอบ ไม่ใช่คำตอบสุดท้าย",
                   icon="⚠️")
    if evidence.get("status") == "unavailable" or not evidence.get("evidence_anchor"):
        st.warning(f"ไม่ได้หลักฐานเสริม: {evidence.get('reason') or 'ไม่ทราบสาเหตุ'} — ใช้ผลจากถนนอย่างเดียว")
        if fetch.get("errors"):
            st.caption("; ".join(fetch["errors"][:3]))
        _evidence_diagnostics(evidence)
        return
    anchor, confidence = evidence["evidence_anchor"], evidence["confidence"]
    study, plan, parcel = evidence["study"], evidence["plan"], evidence["parcel"]
    badge = {"HIGH": "🟢 สูง", "MEDIUM": "🟡 กลาง", "LOW": "🔴 ต่ำ"}[confidence["level"]]
    st.write(f"**{anchor['source']}** ({anchor['lat']:.6f}, {anchor['lon']:.6f})")
    st.caption(
        f"ความเชื่อมั่น: {badge} · คะแนน cluster {anchor['score']:.3f} · "
        f"ข้อมูลแปลงครบ {anchor['coverage']:.0%}"
        + (" · ข้อมูลบางส่วน" if evidence.get("status") == "partial" else ""))
    for reason in confidence["reasons"]:
        st.caption(f"• {reason}")
    for note in evidence.get("notes", []):
        st.caption(f"ℹ️ {note}")
    peak = plan.get("peak")
    st.caption(f"สแกนรัศมี {study['radius_m'] / 1000:g} กม. (≈ {study['area_km2']:,.0f} ตร.กม.)"
               + (f" · ผังสีสูงสุด: {peak['name']} {peak['area_km2']:.2f} ตร.กม. ({len(plan['zones'])} โซนใหญ่)"
                  if peak else " · ไม่พบโซนแดง (พาณิชยกรรม) ในวงศึกษา"))
    if peak:
        st.markdown(_legend_swatch_row(f"rgb({peak['rgb'][0]},{peak['rgb'][1]},{peak['rgb'][2]})",
                                       f"{peak['name']} (พาณิชยกรรม) — สีที่อ่านได้จริง "
                                       f"rgb({peak['rgb'][0]},{peak['rgb'][1]},{peak['rgb'][2]})"),
                    unsafe_allow_html=True)
    stability = evidence.get("stability")
    if stability:
        level = {"stable": "🟢 นิ่ง", "check": "🟡 ควรตรวจ", "unstable": "🔴 ไม่นิ่ง"}[stability["level"]]
        st.caption(f"ความนิ่งเมื่อวงศึกษาเปลี่ยน (ประมาณการ): {level} — ขยับสูงสุด "
                   f"{stability['max_drift_m']:.0f} ม. ({stability['max_drift_ratio']:.0%} ของรัศมี)")
    if composite:
        moved = calculate_distance_meters(
            composite["anchor"]["lat"], composite["anchor"]["lon"], anchor["lat"], anchor["lon"])
        st.caption(f"ห่างจาก anchor ① {moved:,.0f} ม.")
    st.caption(f"ดึงภาพ {fetch.get('requests', 0)} คำขอ · จากแคช {fetch.get('cache_hits', 0)} · "
               f"ผังเมือง {plan.get('tiles_ok', 0)}/{plan.get('tiles', 0)} ไทล์ · "
               f"แปลงที่ดิน {parcel.get('tiles_ok', 0)}/{parcel.get('tiles_needed', 0)} ไทล์ · "
               f"{fetch.get('seconds', 0.0):.1f} วินาที"
               + (f" · ข้าม {fetch['skipped_over_budget']} ไทล์ (เกินโควตา/หมดเวลา)"
                  if fetch.get("skipped_over_budget") else ""))
    st.checkbox("ใช้ Evidence Anchor คำนวณ Rent Gradient", key="rent_use_evidence_anchor",
                on_change=_on_rent_anchor_toggle,
                help="ค่าเริ่มต้น: Rent ใช้ anchor ① Composite — ติ๊กเมื่อยอมรับหลักฐานผังเมือง/แปลงที่ดินแล้ว")
    _evidence_diagnostics(evidence)
    with st.expander("รายละเอียดหลักฐาน (cluster + ภาพ)"):
        st.dataframe([
            {
                "อันดับ": c["rank"], "Lat": round(c["lat"], 5), "Lon": round(c["lon"], 5),
                "เซลล์": c["cells"], "เฮกตาร์": round(c["area_ha"]), "คะแนน": round(c["score"], 3),
                "ห่างศูนย์ (กม.)": round(c["distance_m"] / 1000, 1), "คะแนนถ่วงระยะ": round(c["weighted_mass"], 1),
                "แปลงเล็ก%": round(100 * c["cover_small"]), "ตึกแถว%": round(100 * c["cover_shop"]),
                "ในโซนสีสูงสุด": c["in_zone"], "สแกนไม่ครบ": c["touches_boundary"],
            }
            for c in evidence["clusters"]
        ], hide_index=True)
        windows, px = evidence["windows"], evidence["windows"]["px"]
        x, y = _WEB_MERCATOR.transform(anchor["lon"], anchor["lat"])
        left, right = st.columns(2)
        for column, layer, tile_m, title in (
                (left, EVIDENCE_CONFIG["parcel_layer"], windows["parcel_tile_m"], "รูปแปลงที่ดิน (dol)"),
                (right, EVIDENCE_CONFIG["plan_layer"], windows["plan_tile_m"], "ผังเมืองรวม (cityplan_dpt)")):
            image = load_cached_wms_image(
                layer, _tile_bbox(int(floor(x / tile_m)), int(floor(y / tile_m)), tile_m), px)
            if image is not None:
                column.image(_evidence_thumbnail(image), caption=f"{title} · ไทล์ {tile_m / 1000:g} กม.")
        st.download_button("ดาวน์โหลด Evidence JSON", json.dumps(evidence, ensure_ascii=False, indent=2),
                           "automated_cbd_evidence.json", "application/json")


def _render_sidebar_anchor_panel(locked: bool) -> bool:
    """One button, one road download, both anchors (Composite + Closeness 100%)."""
    with st.expander("🎯 Automated CBD Anchor", expanded=True):
        st.caption("กำหนดพื้นที่ศึกษา แล้วค้นหาจุดศูนย์กลางเชิงโครงข่ายถนน (ไม่ใช้ seed — ผลซ้ำได้เสมอ)")
        st.info(
            "ผลลัพธ์คือ **ศูนย์กลางเชิงโครงข่ายถนน** ของพื้นที่ที่เลือก (ขึ้นกับจุดศูนย์กลาง/รัศมี) "
            "ยังไม่ได้พิสูจน์ว่าตรงกับ CBD เชิงเศรษฐกิจ — ดูป้ายความนิ่งด้านล่าง "
            "และเทียบกับจุดที่ทราบก่อนใช้ตัดสินใจ",
            icon="ℹ️",
        )
        if "anchor_center_input" not in st.session_state:
            st.session_state["anchor_center_input"] = (
                f"{st.session_state.anchor_lat!r}, {st.session_state.anchor_lon!r}"
            )
        center_text = st.text_input(
            "ศูนย์พื้นที่ศึกษา Lat, Lon",
            key="anchor_center_input",
            placeholder="20.075226819421776, 100.5083729446834",
            disabled=locked,
            help=(
                "กรอกพิกัดเป็น Lat, Lon ในช่องเดียว เช่น "
                "20.075226819421776, 100.5083729446834"
            ),
        )
        center_valid = True
        try:
            center_lat, center_lon = _parse_anchor_center_input(center_text)
        except ValueError as exc:
            center_valid = False
            st.error(str(exc))
        else:
            if (
                center_lat != st.session_state.anchor_lat
                or center_lon != st.session_state.anchor_lon
            ):
                st.session_state.anchor_lat = center_lat
                st.session_state.anchor_lon = center_lon
        st.number_input("รัศมีพื้นที่ศึกษา (กม.)", 4.0, 20.0,
                        key="anchor_radius_km", step=0.5, disabled=locked)
        st.checkbox(
            "🗺️ Evidence: ผังสีสูงสุด + แปลงที่ดินถี่ cluster (ทดลอง)",
            key="anchor_use_evidence", disabled=locked,
            help=(
                "หลังหา anchor จากถนน จะอ่านผังเมืองรวม (cityplan_dpt) ทั้งวงศึกษา หาโซนสีสูงสุด "
                "(เช่น พาณิชยกรรม) แล้วดึงรูปแปลงที่ดิน (dol) เฉพาะในโซนนั้น เพื่อหา cluster ของแปลงเล็ก"
                "ถี่แบบตึกแถว — จุดกึ่งกลาง cluster คือ Evidence anchor พร้อมความเชื่อมั่น. "
                "ภาพถูกแคชบนดิสก์ (ไทล์เดิมไม่ถูกดึงซ้ำแม้เปลี่ยนจุดศูนย์กลาง/รัศมี) "
                "ถ้าดึงไม่ได้จะใช้ผลจากถนนอย่างเดียว"
            ),
        )
        if st.session_state.get("anchor_use_evidence") and center_valid:
            estimate = estimate_evidence_requests(
                (st.session_state.anchor_lat, st.session_state.anchor_lon),
                st.session_state.anchor_radius_km * 1000)
            st.caption(
                f"Evidence จะสแกนรัศมี {st.session_state.anchor_radius_km:g} กม. "
                f"(≈ {estimate['area_km2']:,.0f} ตร.กม.): ผังเมือง {estimate['plan_tiles']} ไทล์ + "
                f"แปลงที่ดินสูงสุด {estimate['parcel_tiles_max']} ไทล์ (ไม่เกิน {estimate['requests_max']} คำขอ)")

        context = _anchor_search_context()
        result = st.session_state.get(StateManager.K_AUTO_ANCHOR)
        closeness_result = st.session_state.get(StateManager.K_AUTO_ANCHOR_CLOSENESS)
        evidence_result = st.session_state.get(StateManager.K_AUTO_ANCHOR_EVIDENCE)
        if ((result and not _anchor_context_matches(result.get("context"), context))
                or (closeness_result
                    and not _anchor_context_matches(closeness_result.get("context"), context))
                or (evidence_result
                    and not _anchor_context_matches(evidence_result.get("context"), context))):
            StateManager.clear_results(["anchor", "anchor_closeness", "anchor_evidence"])
            st.rerun()

        if not HAS_SCIPY:
            st.error("กรุณาติดตั้ง scipy และ numpy เพื่อค้นหา Anchor")

        run_anchor = st.button(
            "🎯 ค้นหา CBD Anchor อัตโนมัติ",
            disabled=locked or not HAS_SCIPY or not center_valid,
            use_container_width=True,
        )

        if result:
            st.markdown("##### ① Composite (ใช้กับ Rent Gradient)")
            st.caption("Closeness 50% + Degree 30% + ความหนาแน่นทางแยกใน 500 ม. 20% "
                       "(แต่ละตัวแปลงเป็นอันดับ 0–1 ก่อนถ่วงน้ำหนัก) — junction เป็น candidate หลัก")
            _anchor_summary("composite", result)
        if closeness_result:
            st.markdown("##### ② Closeness 100% (เปรียบเทียบเท่านั้น)")
            st.caption("Score = Closeness อย่างเดียว (ระยะถนนเป็นเมตร) ทุก road node เป็น candidate; "
                       "Rent Gradient ยังคงใช้ตัวที่ ①")
            _anchor_summary("closeness", closeness_result, diagnostics=True)
        if evidence_result:
            st.markdown("##### ③ Evidence (ผังสีสูงสุด + แปลงที่ดินถี่)")
            _evidence_summary(evidence_result, result)
        elif result and st.session_state.get("anchor_use_evidence"):
            st.caption("เปิดตัวเลือกหลักฐานแล้ว — กดค้นหาอีกครั้ง (ใช้ถนนจากแคช) เพื่อตรวจผังเมือง/แปลงที่ดิน")
        shown = result or closeness_result
        if shown:
            timings = shown.get("timings", {})
            graph_info = shown.get("graph", {})
            st.caption(
                f"โหลดข้อมูลถนน {shown.get('load_seconds', 0.0):.2f} วินาที"
                f" ({graph_info.get('source', 'unknown')}) · คำนวณ {shown['compute_seconds']:.2f} วินาที"
                + (f" (เตรียม {timings['prep_s']:.2f} · pivot {timings['pivots_s']:.2f} · "
                   f"exact {timings['exact_s']:.2f})" if timings else "")
            )
            st.download_button(
                "ดาวน์โหลด Anchor JSON",
                json.dumps({"composite": result, "closeness": closeness_result,
                            "evidence": evidence_result}, ensure_ascii=False, indent=2),
                "automated_cbd_anchors.json",
                "application/json",
            )
            if st.button("ล้าง Anchor ที่ค้นหาไว้", disabled=locked):
                StateManager.clear_results(["anchor", "anchor_closeness", "anchor_evidence"])
                st.rerun()
        return run_anchor


def _render_sidebar_rent_panel(locked: bool) -> bool:
    """
    Render the Rent Gradient (Bid-Rent) expander.

    Returns ``True`` if the user clicked **คำนวณ Rent Gradient**.
    """
    with st.expander("💰 Rent Gradient (Bid-Rent)", expanded=True):
        st.caption("หลัก Alonso-Muth-Mills: **R(d) = R₀ · e^(−λ·d)** — ค่าเช่าลดลงตามระยะจาก CBD")

        can_run = (StateManager.get_isochrone_data() is not None
                   or st.session_state.get(StateManager.K_AUTO_ANCHOR) is not None)
        if not can_run:
            st.warning("⚠️ **Scope:** กรุณาคำนวณ Isochrone หรือค้นหา Automated Anchor ก่อน", icon="🛑")

        # ---- Calibration samples ----
        st.markdown("##### 🧾 ตัวอย่างราคาจริง (Calibration)")
        st.caption(
            "แนะนำ ≥ 5 จุดที่ระยะต่างกันเพื่อ fit λ จากตลาดจริง (2 จุดคำนวณได้ "
            "แต่ R² = 1 เสมอ จึงไม่บอกคุณภาพ) — เว้นว่างไว้ระบบจะใช้ดัชนี 0–100"
        )
        samples = StateManager.get_rent_samples()
        df = pd.DataFrame(samples, columns=["lat", "lon", "rent"], dtype="float64")
        edited_df = st.data_editor(
            df,
            num_rows="dynamic",
            hide_index=True,
            use_container_width=True,
            disabled=locked,
            column_config={
                "lat": st.column_config.NumberColumn("Lat", format="%.5f"),
                "lon": st.column_config.NumberColumn("Lon", format="%.5f"),
                "rent": st.column_config.NumberColumn("ราคา", min_value=0.0),
            },
        )
        if not locked:
            _sync_rent_samples_from_editor(edited_df)

        st.text_input("หน่วยราคา", key="rent_unit_label", disabled=locked)

        st.caption("เปิด/ปิด Rent Rings · Rent Heat ที่แผง ⑥ ชั้นแผนที่ (Rent Heat ต้องรัน Network Analysis ก่อน)")

        do_rent: bool = st.button(
            "🧮 คำนวณ Rent Gradient",
            use_container_width=True,
            disabled=(not can_run) or locked,
        )

        # ---- Model summary ----
        rent_data = StateManager.get_rent_data()
        if rent_data and "error" not in rent_data:
            model = rent_data["model"]
            st.markdown("---")
            c1, c2 = st.columns(2)
            c1.metric("λ (ต่อ km)", f"{model['lam']:.4f}")
            half = model.get("half_dist_km")
            c2.metric("d½ (km)", f"{half:.2f}" if half else "∞")

            c3, c4 = st.columns(2)
            r0_txt = f"{model['r0']:,.0f}" if not model["is_index"] else f"{model['r0']:.0f} (ดัชนี)"
            c3.metric("R₀ ที่ CBD", r0_txt)
            if model.get("r2") is not None:
                if _fit_dof(model) > 0:
                    c4.metric("R² (fit)", f"{model['r2']:.3f}", help=fit_quality_label(model))
                else:
                    c4.metric("R² (fit)", "—", help=fit_quality_label(model))
            else:
                c4.metric("Calibration", "ดัชนี (ไม่มีตัวอย่าง)")
            interval = fit_interval_text(model)
            if interval:
                st.caption(f"n = {model['n_samples']} · {interval}")
            quality_warning = fit_quality_warning(model)
            if quality_warning:
                st.warning(quality_warning, icon="📉")

            anchor = rent_data["anchor"]
            st.caption(
                f"จุดยึด CBD: **{anchor['source']}** "
                f"({anchor['lat']:.5f}, {anchor['lon']:.5f})"
            )
            if model.get("inverted"):
                st.warning(
                    "λ ติดลบ — ราคาตัวอย่างสูงขึ้นตามระยะจาก CBD "
                    "(gradient กลับทิศ) ตรวจสอบตำแหน่งตัวอย่างหรือจุดยึด CBD",
                    icon="↔️",
                )

    return do_rent


def _render_sidebar_isochrone_settings(locked: bool) -> None:
    """Travel mode + minutes for step ① (moved here from the old map-settings panel)."""
    st.markdown("##### 🚗 การเดินทาง (Isochrone)")
    st.selectbox(
        "โหมด",
        list(TRAVEL_MODE_NAMES.keys()),
        format_func=TRAVEL_MODE_NAMES.get,
        key="travel_mode",
        disabled=locked,
    )
    st.multiselect("เวลา (นาที)", TIME_OPTIONS, key="time_intervals", disabled=locked)


def _layer_available(layer: Layer, ctx: Ctx) -> bool:
    try:
        return bool(layer.available(ctx))
    except Exception:
        return False


def _render_sidebar_layers_panel(ctx: Ctx, locked: bool) -> None:
    """⑥ Every layer checkbox in one place, generated from ``LAYERS`` (same ``show_*`` keys as before)."""
    with st.expander("🗺️ ⑥ ชั้นแผนที่ (Layers)", expanded=True):
        st.selectbox("สไตล์แผนที่", list(MAP_STYLES.keys()), key="map_style_name", disabled=locked)
        for group in PANEL_GROUPS:
            rows = sorted((layer for layer in LAYERS if layer.group == group and layer.show_key),
                          key=lambda layer: layer.panel_rank)
            if not rows:
                continue
            st.markdown(f"**{group}**")
            for layer in rows:
                st.checkbox(layer.label or layer.title, key=layer.show_key, disabled=locked)
                if layer.hint:
                    st.caption(layer.hint)
                if layer.requires and not _layer_available(layer, ctx):
                    st.caption(f"⏳ ยังไม่มีข้อมูล — {layer.requires}")
                if layer.options is not None and st.session_state.get(layer.show_key):
                    layer.options(ctx, locked)


def _ss_status(params: Dict[str, Any]) -> None:
    """One line saying whether what is on the map still matches the sidebar settings."""
    state = st.session_state
    result = state.get(SS_RESULT)
    if state.get(SS_NET) is None:
        return
    if state.get(SS_KEY) not in (("demo",), ss_study_key()):
        st.warning("พื้นที่ศึกษา / ชนิดโครงข่ายที่ตั้งไว้ต่างจากที่โหลดอยู่ — กดวิเคราะห์เพื่ออัปเดต", icon="⚠️")
    elif result is not None and result.meta.get("params") != params:
        st.warning("ตั้งค่าเปลี่ยนไปจากที่คำนวณไว้ — กดวิเคราะห์เพื่ออัปเดตผล", icon="⚠️")
    elif result is not None:
        meta = state.get(SS_META) or {}
        st.caption(f"✅ ผลล่าสุด · {result.meta['n_segments']:,} segment · {result.meta['seconds']:.1f} วินาที"
                   f" · โครงข่าย: {meta.get('source', '—')}")


def _render_sidebar_space_syntax_panel(locked: bool) -> Dict[str, Any]:
    """④ Space Syntax — what to analyse. Returns the pressed buttons and the chosen parameters."""
    state = st.session_state
    with st.expander("🧭 ④ Space Syntax (เข้าถึงง่าย แดง→น้ำเงิน)", expanded=True):
        st.caption("ไล่สีทุกช่วงถนนตามคะแนนการเข้าถึง — Integration (NAIN) / Choice (NACH) แบบ Segment Analysis · "
                   "ผลขึ้นเป็นชั้นบนแผนที่ และเป็นมุมมอง 🧭 ใต้แผนที่")
        st.caption(f"ศูนย์พื้นที่ศึกษา: **{float(state['anchor_lat']):.5f}, {float(state['anchor_lon']):.5f}** "
                   "— แก้ได้ที่แผง ③ Automated CBD Anchor")
        st.slider("รัศมีที่แสดงผล (m)", MIN_RADIUS_M, MAX_RADIUS_M, step=250, key="ss_radius_m", disabled=locked,
                  help="คำนวณบนโครงข่ายที่กว้างกว่านี้ 20% แล้วแสดง/จัดอันดับเฉพาะในรัศมีนี้ เพื่อลด edge effect")
        st.selectbox("ชนิดโครงข่าย", list(NETWORK_TYPES), key="ss_network", format_func=NETWORK_TYPES.get,
                     disabled=locked)
        kind = st.selectbox("ระยะที่ใช้วัด (depth)", list(DISTANCE_KINDS), key="ss_kind", disabled=locked,
                            format_func=lambda k: DISTANCE_KINDS[k]["label"],
                            help="\n\n".join(f"**{v['label']}** — {v['help']}" for v in DISTANCE_KINDS.values()))
        if kind == "topological":
            st.slider("นับเป็น 1 ก้าวเมื่อเลี้ยวเกิน (°)", 0, 60, step=5, key="ss_turn", disabled=locked,
                      help="0 = ทุกการเปลี่ยน segment นับ 1 ก้าว · 20–30° = ถนนที่แทบตรงนับเป็นเส้นเดียว")
        st.multiselect("รัศมีวิเคราะห์ (เมตรตามถนน)", list(RADIUS_OPTIONS), key="ss_radii", disabled=locked,
                       help="Local (400–1,600 m) = ย่านเดินถึง · Global (n) = ทั้งโครงข่าย")
        st.checkbox("คำนวณ Choice (ทางผ่าน) ด้วย", key="ss_choice", disabled=locked,
                    help="ใช้เวลาเพิ่มราว 1–2 เท่า — ปิดไว้ถ้าต้องการเฉพาะ Integration")
        run = st.button("🧮 วิเคราะห์ Space Syntax", type="primary", use_container_width=True,
                        disabled=locked, key="ss_run_btn")
        demo = st.button("🧪 ตัวอย่างเชียงของ (ออฟไลน์)", use_container_width=True, disabled=locked,
                         key="ss_demo_btn",
                         help="ใช้กราฟถนนที่เก็บไว้ใน Geoapify_Map/osmnx_cache.zip — ไม่ต้องดาวน์โหลดจาก Overpass")
        params = ss_params()
        _ss_status(params)
    return {"run": run, "demo": demo, "params": params}


def render_sidebar() -> Dict[str, Any]:
    """
    Orchestrate the sidebar in pipeline order:
    ① จุดเริ่ม + Isochrone → ② Network → ③ Anchor (กำหนดพื้นที่ศึกษา) → ④ Space Syntax → ⑤ Rent Gradient
    (⑥ ชั้นแผนที่ is drawn by ``main`` after the stages ran, so it can show what has data).

    Returns the user's intents: ``calc / network / anchor / rent / space_syntax`` are True for the button that
    was pressed (``demo`` = the offline Space Syntax example), plus ``ss_params`` / ``active`` / ``locked``.
    """
    with st.sidebar:
        st.header("⚙️ การตั้งค่า")

        ui_locked = st.toggle("🔒 Lock Active Markers + เมนูทั้งหมด", key=StateManager.K_UI_LOCKED)
        _render_sidebar_config_section(ui_locked)
        st.markdown("---")
        _render_sidebar_marker_input(ui_locked)

        st.text_input("Geoapify API Key", key="api_key", type="password", disabled=ui_locked)

        active_list = _render_sidebar_marker_list(ui_locked)
        _render_sidebar_isochrone_settings(ui_locked)

        do_calc: bool = st.button(
            "🧩 ① คำนวณหา Isochrone CBD",
            type="primary",
            use_container_width=True,
            disabled=ui_locked,
        )
        st.markdown("---")

        do_network = _render_sidebar_network_panel(ui_locked)
        st.markdown("---")

        do_anchor = _render_sidebar_anchor_panel(ui_locked)
        st.markdown("---")

        space_syntax = _render_sidebar_space_syntax_panel(ui_locked)
        st.markdown("---")

        do_rent = _render_sidebar_rent_panel(ui_locked)
        st.markdown("---")

    return {"calc": do_calc, "network": do_network, "anchor": do_anchor, "rent": do_rent,
            "space_syntax": space_syntax["run"] or space_syntax["demo"], "demo": space_syntax["demo"],
            "ss_params": space_syntax["params"], "active": active_list, "locked": ui_locked}


def _stability_popup(result: Dict[str, Any]) -> str:
    stability = result.get("stability")
    if not stability:
        return ""
    return (f"<br>Stability: {stability['level']} "
            f"(max drift {stability['max_drift_m']:.0f} m, indicative)")


def render_header() -> None:
    """หัวเรื่อง + สรุปหลักการของหน้าแบบย่อ."""
    st.markdown("#### 💹 Rent Gradient — Bid-Rent CBD Analysis")
    st.caption(
        "① เริ่มใกล้ศูนย์กลางประชากร → ② Isochrone 20 นาทีหา C20 → "
        "③ Isochrone 5 นาทีหา C5 → ④ Golden Spots → ⑤ Rent Gradient"
    )


def render_metrics_row() -> None:
    """แถวตัวชี้วัดสรุปเหนือแผนที่."""
    active_n = len(StateManager.get_active_markers())
    inter_data = StateManager.get_intersection_data()
    net_data = StateManager.get_network_data()
    rent_data = StateManager.get_rent_data()

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("📍 หมุด Active", active_n)

    cbd_txt = "—"
    if inter_data:
        feats = inter_data.get("features") or []
        area = approx_geom_area_km2(feats[0]["geometry"]) if feats else None
        cbd_txt = f"{area:.2f} km²" if area is not None else "พบแล้ว"
    c2.metric("🎯 CBD Zone", cbd_txt)

    net_txt = "—"
    if net_data and "error" not in net_data:
        stats = net_data.get("stats", {})
        net_txt = f"{stats.get('nodes_count', 0):,} โหนด"
    c3.metric("🕸️ Network", net_txt)

    lam_txt, half_txt = "—", "—"
    if rent_data and "error" not in rent_data:
        model = rent_data["model"]
        lam_txt = f"{model['lam']:.4f}/km"
        half = model.get("half_dist_km")
        half_txt = f"{half:.2f} km" if half else "∞"
    c4.metric("📉 λ (Rent Gradient)", lam_txt)
    c5.metric("½ ราคา ที่ระยะ", half_txt)


def _build_bid_rent_figure(rent_data: Dict[str, Any]):
    """สร้างกราฟ Bid-Rent Curve (plotly) — โมเดล + จุดตัวอย่างจริง + เส้น d½."""
    import plotly.graph_objects as go  # lazy import — โหลดเมื่อใช้จริงเท่านั้น

    model = rent_data["model"]
    curve = rent_data["curve"]
    unit_text = "ดัชนีค่าเช่า (0–100)" if model["is_index"] else model["unit"]

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=curve["d"],
            y=curve["r"],
            mode="lines",
            name="Bid-Rent Curve (โมเดล)",
            line=dict(color=CHART_COLOR_CURVE, width=2.5),
            hovertemplate="ระยะ %{x:.2f} km<br>ค่าเช่า %{y:,.1f}<extra></extra>",
        )
    )

    scatter = rent_data.get("samples_scatter") or []
    if scatter:
        fig.add_trace(
            go.Scatter(
                x=[p["d"] for p in scatter],
                y=[p["rent"] for p in scatter],
                mode="markers",
                name="ตัวอย่างราคาจริง",
                marker=dict(
                    color=CHART_COLOR_SAMPLES,
                    size=10,
                    line=dict(color="#ffffff", width=1.5),
                ),
                hovertemplate="ระยะ %{x:.2f} km<br>ราคาจริง %{y:,.1f}<extra></extra>",
            )
        )

    half = model.get("half_dist_km")
    if half and half <= model["d_max_km"]:
        fig.add_vline(
            x=half,
            line_dash="dash",
            line_color=CHART_COLOR_MUTED,
            annotation_text=f"d½ = {half:.2f} km",
            annotation_font_color=CHART_COLOR_MUTED,
        )

    fig.update_layout(
        height=380,
        margin=dict(l=10, r=10, t=30, b=10),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
        xaxis=dict(
            title="ระยะทางจาก CBD (km)",
            gridcolor="rgba(137,135,129,0.25)",
            zeroline=False,
        ),
        yaxis=dict(
            title=unit_text,
            gridcolor="rgba(137,135,129,0.25)",
            zeroline=False,
            rangemode="tozero",
        ),
        font=dict(size=13),
    )
    return fig


def _build_golden_spots_df(
    golden_spots: List[Dict[str, Any]],
    rent_data: Optional[Dict[str, Any]],
) -> pd.DataFrame:
    """ตาราง Golden Spots — เสริมระยะจาก CBD, ราคาประเมิน และ Value Gap."""
    has_rent = bool(rent_data and "error" not in rent_data)
    rows = []
    for i, s in enumerate(golden_spots, start=1):
        row: Dict[str, Any] = {
            "อันดับ": i,
            "Score": round(s["score"], 4),
            "Lat": round(s["lat"], 5),
            "Lon": round(s["lon"], 5),
            "Closeness": round(s.get("closeness_norm", 0.0), 3),
            "Degree": round(s.get("degree_norm", 0.0), 3),
        }
        if has_rent:
            model = rent_data["model"]
            anchor = rent_data["anchor"]
            d_km = haversine_km(anchor["lat"], anchor["lon"], s["lat"], s["lon"])
            est = predict_rent(d_km, model["r0"], model["lam"])
            rent_norm = max(0.0, min(1.0, est / model["r0"])) if model["r0"] else 0.0
            row["ระยะจาก CBD (km)"] = round(d_km, 2)
            row["ค่าเช่าคาดการณ์"] = round(est, 1)
            # Value Gap: เข้าถึงง่าย (closeness สูง) แต่ราคายังต่ำ = โอกาส
            # ซ่อนในโหมดดัชนี: R(d)/R0 เป็นค่าสมมติ gap จึงสะท้อนสมมติฐานเอง
            if not model.get("is_index"):
                row["Value Gap"] = round(s.get("closeness_norm", 0.0) - rent_norm, 3)
        rows.append(row)
    return pd.DataFrame(rows)


def _summary_row(net: SegmentNetwork, meta: Dict[str, Any], mask: np.ndarray,
                 result: Optional[AnalysisResult]) -> None:
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Segment (แสดง / ทั้งหมด)", f"{int(mask.sum()):,} / {net.n_segments:,}")
    c2.metric("ความยาวถนนที่แสดง", f"{net.seg_len[mask].sum() / 1000:,.1f} km")
    c3.metric("แยก / จุดปลายถนน", f"{net.n_nodes:,}")
    c4.metric("เวลาคำนวณ", f"{result.meta['seconds']:.1f} s" if result else "—")
    st.caption(f"โครงข่าย: {meta['source']} · {NETWORK_TYPES.get(meta['network'], meta['network'])}")


def _render_help() -> None:
    st.markdown(
        """
##### อ่านสีอย่างไร
- 🔴 **แดง** = คะแนนสูงสุด — ช่วงถนนที่ *เข้าถึงได้ง่ายที่สุด* จากทุกจุดในรัศมี (ถนนสายหลักที่ตัดผ่านย่าน)
- 🟡🟢 **เหลือง / เขียว** = ปานกลาง
- 🔵 **น้ำเงิน** = เข้าถึงยากที่สุด (ซอยตัน / ถนนปลายทางที่ต้องเลี้ยวหลายครั้ง)
- คะแนน 0–100 = ตำแหน่งของค่า NAIN (หรือ NACH) ระหว่างต่ำสุดถึงสูงสุดของ segment ที่แสดง
  (หรือเปอร์เซ็นไทล์ ถ้าเลือกสเกล Quantile)

##### สูตร (Hillier, Yang & Turner 2012)
| ตัวชี้วัด | สูตร | ความหมาย |
|---|---|---|
| **Integration** NAIN | `NC^1.2 / (TD + 2)` | เข้าถึงง่ายจากทุกที่ (to-movement) |
| **Choice** NACH | `log(CH + 1) / log(TD + 3)` | เป็นทางผ่านของเส้นทางสั้นที่สุด (through-movement) |

`NC` = จำนวน segment ในรัศมี (รวมตัวเอง) · `TD` = ผลรวม depth จาก segment นี้ไปทุก segment ในรัศมี ·
`CH` = จำนวนคู่ (ต้นทาง → ปลายทาง) ที่เส้นทางสั้นที่สุดผ่าน segment นี้ (นับทั้งสองทิศ)

##### ระยะ (depth) และรัศมี
- **Angular**: ผลรวมมุมเลี้ยว เลี้ยว 90° = 1.0, ตรงต่อ = 0 (นับความโค้งภายใน segment ด้วย)
  — มาตรฐานของ Segment Analysis
- **Topological**: จำนวนก้าว (นับเมื่อเลี้ยวเกินมุมที่ตั้งไว้)
- **Metric**: เมตรตามถนน จากกลาง segment ถึงกลาง segment (ใส่สูตรด้วยหน่วยบล็อก 100 ม.)
- รัศมีวัดเป็นเมตรตามถนนเสมอ · **Global (n)** = ทั้งโครงข่ายที่เชื่อมถึงกัน
- ระยะ angular เท่ากันทุกประการเกิดบ่อย (เลี้ยวทางเดียวกันจากทิศเดิมไปทิศเดิม)
  จึงเลือกเส้นทางที่สั้นกว่าเป็นตัวตัดสิน

##### ข้อควรระวัง
- ค่าขึ้นกับข้อมูล OSM: ถนนที่ขาด/ไม่ได้เชื่อมต่อในแผนที่จะถูกมองว่าเข้าถึงยาก
- Global (n) ให้คะแนนสูงตรงกลางพื้นที่ศึกษาเสมอ (edge effect) — ใช้ buffer 20% ช่วย
  แต่ถ้าสนใจย่านเฉพาะ ให้ดู Local ประกอบ
- เป็นโครงข่ายถนนเท่านั้น ไม่รวมมูลค่าการใช้ที่ดิน ผังเมือง หรือราคาจริง
""")


def view_space_syntax(ctx: Ctx) -> None:
    """🧭 Space Syntax: summary, depthmap-style segment map (PNG), statistics + ranking + export, explanation."""
    view = ctx.ss
    if view is None:
        st.info("กด 🧮 วิเคราะห์ Space Syntax ที่แผง ④ ใน sidebar (หรือ 🧪 ตัวอย่างเชียงของ) — "
                "ผลจะขึ้นเป็นชั้นบนแผนที่และที่นี่", icon="🧭")
        with st.expander("📖 หลักการ Space Syntax"):
            _render_help()
        return
    net, meta, result, mask, d = view.net, view.meta, view.result, view.mask, view.display
    _summary_row(net, meta, mask, result)
    if result.meta.get("params") != ss_params():
        st.warning("ตั้งค่า Space Syntax เปลี่ยนไปจากที่คำนวณไว้ — กด 🧮 วิเคราะห์ ที่แผง ④ เพื่ออัปเดตผล")
    notes = [f"ระยะ: {DISTANCE_KINDS[result.kind]['label']}",
             "รัศมี: " + ", ".join(radius_label(r) for r in result.radii)]
    if result.meta["approximate_global"]:
        notes.append(f"⚡ Global ประมาณด้วย pivot {result.meta['pivots']:,} จุด (segment เกิน "
                     f"{result.meta['max_exact_segments']:,})")
    st.caption(" · ".join(notes))
    sub = st.radio("มุมมอง Space Syntax", list(SS_VIEW_LABELS), horizontal=True, key="ss_view",
                   format_func=SS_VIEW_LABELS.get, label_visibility="collapsed")
    measure, rkey, palette = d["measure"], d["rkey"], d["palette"]
    st.caption(f"แสดง: {MEASURES[measure]['title']} · รัศมี {radius_label_for(rkey)} · {SCALE_MODES[d['scale']]} "
               "— เปลี่ยนได้ที่แผง ⑥ ชั้นแผนที่")
    if sub == "help":
        _render_help()
        return
    payload = ss_payload(ctx)
    values, scaled, top = payload["values"], payload["scaled"], payload["top"]
    labels = {radius_key(r): radius_label(r) for r in result.radii}
    if sub == "png":                                     # drawn only when asked for, then kept in the LRU
        key = ("ss-png", measure, rkey, palette, d["scale"], d["thick"])
        try:
            png = lru_get(ctx.cache, key, result, lambda: render_depthmap_png(
                net, scaled["t"], mask, palette, thick_by_score=d["thick"]))
        except ValueError as exc:
            st.warning(str(exc))
            return
        st.image(png)
        st.download_button("⬇️ ดาวน์โหลดภาพ PNG", png, file_name=f"space_syntax_{measure}_{rkey}.png",
                           mime="image/png")
        st.caption(f"{MEASURES[measure]['title']} · รัศมี {labels[rkey]} · {int(mask.sum()):,} segment · "
                   "วาดเส้นคะแนนสูงทับเส้นคะแนนต่ำ")
        return

    # ---- stats & ranking ----
    index_name = "NAIN" if measure == "integration" else "NACH"
    s1, s2, s3, s4 = st.columns(4)
    shown = values[mask & np.isfinite(values)]
    s1.metric(f"{index_name} สูงสุด", f"{shown.max():.3f}")
    s2.metric(f"{index_name} มัธยฐาน", f"{np.median(shown):.3f}")
    s3.metric(f"{index_name} ต่ำสุด", f"{shown.min():.3f}")
    s4.metric("segment ที่ได้คะแนน ≥ 80", f"{int((scaled['score'][mask] >= 80).sum()):,}")
    anchor = rent_anchor_point()
    if anchor is not None:
        snapped = net.to_xy(anchor["lon"], anchor["lat"])
        nearest = int(np.argmin(np.hypot(*(net.seg_mid_xy - snapped).T)))
        if np.isfinite(scaled["score"][nearest]):
            st.info(f"📍 จุดยึด CBD ของ Rent Gradient ({anchor['source']}) อยู่ใกล้ segment คะแนน "
                    f"**{scaled['score'][nearest]:.0f}/100** ({_segment_label(net, nearest)})")
    st.plotly_chart(histogram_figure(scaled, palette, index_name), width="stretch")
    if top:
        st.markdown(f"**🏆 จุดที่ {MEASURES[measure]['thai']}สูงสุด** (ห่างกันอย่างน้อย "
                    f"{top_spacing_m(net, mask):,.0f} m)")
        table = pd.DataFrame(top).rename(columns={
            "rank": "อันดับ", "name": "ถนน", "highway": "ประเภท", "length_m": "ยาว (m)", "score": "คะแนน",
            "value": index_name, "nc": "NC", "lat": "Lat", "lon": "Lon"}).drop(columns=["segment", "label"])
        st.dataframe(table, hide_index=True, width="stretch", column_config={
            "ยาว (m)": st.column_config.NumberColumn(format="%.0f"),
            "คะแนน": st.column_config.NumberColumn(format="%.1f"),
            index_name: st.column_config.NumberColumn(format="%.3f"),
            "Lat": st.column_config.NumberColumn(format="%.5f"),
            "Lon": st.column_config.NumberColumn(format="%.5f")})
    with st.expander("🛣️ คะแนนเฉลี่ยตามประเภทถนน (ถ่วงด้วยความยาว)"):
        summary = highway_summary(net, scaled["score"], values, mask)
        st.dataframe(summary.rename(columns={
            "highway": "highway", "segments": "segment", "length_km": "ยาว (km)", "mean_score": "คะแนนเฉลี่ย",
            "mean_value": f"{index_name} เฉลี่ย"}), hide_index=True, width="stretch", column_config={
            "ยาว (km)": st.column_config.NumberColumn(format="%.1f"),
            "คะแนนเฉลี่ย": st.column_config.NumberColumn(format="%.1f"),
            f"{index_name} เฉลี่ย": st.column_config.NumberColumn(format="%.3f")})
    d1, d2 = st.columns(2)
    frame = segment_table(net, result, mask)
    d1.download_button("⬇️ CSV (ทุกรัศมี/ตัวชี้วัด)", frame.to_csv(index=False).encode("utf-8-sig"),
                       file_name="space_syntax_segments.csv", mime="text/csv")
    columns = {**payload["columns"], **result_columns(net, result)}
    geojson = json.dumps(segments_geojson(net, columns, mask), ensure_ascii=False)
    d2.download_button("⬇️ GeoJSON (พร้อมสี)", geojson, file_name="space_syntax_segments.geojson",
                       mime="application/geo+json")


def render_analytics_panel() -> None:
    """แท็บวิเคราะห์ใต้แผนที่: Bid-Rent Curve / Golden Spots / หมุด / หลักการ."""
    rent_data = StateManager.get_rent_data()
    net_data = StateManager.get_network_data()
    has_rent = bool(rent_data and "error" not in rent_data)
    golden_spots = (net_data or {}).get("golden_spots") if net_data else None
    locked = st.session_state.get(StateManager.K_UI_LOCKED, False)

    tab_curve, tab_rings, tab_gold, tab_marks, tab_theory = st.tabs(
        [
            "📈 Bid-Rent Curve",
            "🧾 Ring Report",
            "💎 Golden Spots",
            "📍 หมุด & ราคาประเมิน",
            "📐 หลักการ",
        ]
    )

    with tab_curve:
        if has_rent:
            model = rent_data["model"]
            st.plotly_chart(
                _build_bid_rent_figure(rent_data),
                use_container_width=True,
                config={"displayModeBar": False},
            )
            eq_r0 = f"{model['r0']:,.1f}" if not model["is_index"] else f"{model['r0']:.0f}"
            fit_txt = f" — {fit_quality_label(model)}"
            interval = fit_interval_text(model)
            if interval:
                fit_txt += f" · {interval}"
            st.caption(
                f"R(d) = {eq_r0} × e^(−{model['lam']:.4f}·d)"
                + fit_txt
            )
            quality_warning = fit_quality_warning(model)
            if quality_warning:
                st.warning(quality_warning, icon="📉")
        else:
            st.info("กด **🧮 คำนวณ Rent Gradient** ใน sidebar เพื่อสร้างเส้นโค้ง Bid-Rent", icon="💡")

    with tab_rings:
        if has_rent:
            ring_rows = build_ring_report(
                rent_data, net_data, StateManager.get_rent_samples()
            )
            has_net_cols = bool(net_data and "error" not in net_data and net_data.get("nodes", {}).get("features"))
            df_rings = pd.DataFrame(ring_rows)
            st.dataframe(df_rings, use_container_width=True, hide_index=True)

            csv_bytes = df_rings.to_csv(index=False).encode("utf-8-sig")
            st.download_button(
                "⬇ ดาวน์โหลด CSV",
                csv_bytes,
                "ring_report.csv",
                "text/csv",
            )

            if not has_net_cols:
                st.info(
                    "รัน **🚀 Network Analysis** เพื่อเติมจำนวนโหนด, Closeness "
                    "และ Value Gap รายวง",
                    icon="💡",
                )
            if rent_data["model"].get("is_index"):
                st.caption(
                    "**โหนด/km²** = ความหนาแน่นของโครงข่ายถนน หารด้วยพื้นที่ของวงที่มีข้อมูลถนนจริง · "
                    "**Closeness เฉลี่ย** = ความเข้าถึงง่ายเฉลี่ยของโหนดในวง · "
                    "**Value Gap ถูกซ่อน** ในโหมดดัชนี เพราะ R(d)/R₀ เป็นค่าสมมติ "
                    "(ลดเหลือ ¼ ที่ขอบ) — ใส่ตัวอย่างราคาจริงเพื่อ calibrate ก่อน"
                )
            else:
                st.caption(
                    "**โหนด/km²** = ความหนาแน่นของโครงข่ายถนน หารด้วยพื้นที่ของวงที่มีข้อมูลถนนจริง · "
                    "**Closeness เฉลี่ย** = ความเข้าถึงง่ายเฉลี่ยของโหนดในวง · "
                    "**Value Gap** = Closeness เฉลี่ย − (ค่าเช่าคาดการณ์/R₀) — "
                    "วงที่ Value Gap สูงคือวงที่โครงข่ายเข้าถึงดีแต่ราคาคาดการณ์ยังต่ำ "
                    "(ตัวชี้นำเชิงเปรียบเทียบ ไม่ใช่ราคาผิดปกติที่พิสูจน์แล้ว)"
                )
        else:
            st.info("กด **🧮 คำนวณ Rent Gradient** ใน sidebar เพื่อสร้างรายงานรายวง", icon="💡")

    with tab_gold:
        if golden_spots:
            df_gold = _build_golden_spots_df(golden_spots, rent_data)
            st.dataframe(df_gold, use_container_width=True, hide_index=True)
            if has_rent:
                if rent_data["model"].get("is_index"):
                    st.caption(
                        "Value Gap ถูกซ่อนในโหมดดัชนี (R(d)/R₀ เป็นค่าสมมติ) — "
                        "ใส่ตัวอย่างราคาจริงเพื่อ calibrate"
                    )
                else:
                    st.caption(
                        "**Value Gap** = Closeness − (ค่าเช่าคาดการณ์/R₀) — "
                        "ค่าบวกมาก = เข้าถึงง่ายแต่ราคายังต่ำ (ตัวชี้นำเชิงเปรียบเทียบ)"
                    )

            c1, c2, _sp = st.columns([0.3, 0.3, 0.4])
            csv_bytes = df_gold.to_csv(index=False).encode("utf-8-sig")
            c1.download_button(
                "⬇ ดาวน์โหลด CSV",
                csv_bytes,
                "golden_spots.csv",
                "text/csv",
                use_container_width=True,
            )
            rank = c2.selectbox(
                "เพิ่มอันดับลงแผนที่",
                list(range(1, len(golden_spots) + 1)),
                label_visibility="collapsed",
                format_func=lambda r: f"➕ เพิ่มอันดับ {r} ลงแผนที่",
            )
            if c2.button("ยืนยันเพิ่มหมุด", use_container_width=True, disabled=locked):
                spot = golden_spots[rank - 1]
                StateManager.add_marker(spot["lat"], spot["lon"])
                StateManager.clear_results(["isochrone", "intersection", "rent"])
                st.toast(f"เพิ่ม Golden Spot อันดับ {rank} แล้ว! กรุณากดคำนวณใหม่", icon="💎")
                st.rerun()
        else:
            st.info("รัน **🚀 Network Analysis** เพื่อค้นหาทำเลที่ดินทอง", icon="💡")

    with tab_marks:
        markers = StateManager.get_markers()
        if markers:
            rows = []
            for i, mk in enumerate(markers, start=1):
                row: Dict[str, Any] = {
                    "จุดที่": i,
                    "สถานะ": "✅ Active" if mk.get("active", True) else "⏸ ปิด",
                    "Lat": round(mk["lat"], 5),
                    "Lon": round(mk["lng"], 5),
                }
                if has_rent:
                    model = rent_data["model"]
                    anchor = rent_data["anchor"]
                    d_km = haversine_km(anchor["lat"], anchor["lon"], mk["lat"], mk["lng"])
                    row["ระยะจาก CBD (km)"] = round(d_km, 2)
                    row["ค่าเช่าคาดการณ์"] = format_rent_value(
                        predict_rent(d_km, model["r0"], model["lam"]), model
                    )
                rows.append(row)
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
            if not has_rent:
                st.caption("คำนวณ Rent Gradient เพื่อดูราคาประเมินของแต่ละหมุด")
        else:
            st.info("ยังไม่มีหมุด — คลิกบนแผนที่หรือกรอกพิกัดใน sidebar", icon="📍")

    with tab_theory:
        st.html(
            """
<style>
.rg-guide {
    max-width: 920px;
    margin: 0 auto;
    color: #edf7f4;
    font-family: inherit;
}
.rg-guide * { box-sizing: border-box; }
.rg-guide .principle {
    padding: 20px 22px;
    border: 1px solid rgba(83, 214, 162, .38);
    border-radius: 16px;
    background: linear-gradient(135deg, rgba(83, 214, 162, .13), #101c27);
}
.rg-guide .label {
    margin-bottom: 5px;
    color: #53d6a2;
    font-size: .76rem;
    font-weight: 900;
    letter-spacing: .08em;
}
.rg-guide h3 {
    margin: 0 0 7px;
    color: #ffffff;
    font-size: clamp(1.15rem, 2.6vw, 1.55rem);
}
.rg-guide p { margin: 0; color: #b6c9cd; line-height: 1.65; }
.rg-guide code {
    padding: 2px 6px;
    border-radius: 6px;
    color: #dffff3;
    background: rgba(83, 214, 162, .12);
}
.rg-guide .flow-title {
    margin: 22px 0 11px;
    color: #ffffff;
    font-size: 1.05rem;
    font-weight: 850;
}
.rg-guide .flow {
    display: grid;
    gap: 9px;
}
.rg-guide .step {
    display: grid;
    grid-template-columns: 38px 1fr;
    gap: 12px;
    align-items: start;
    padding: 13px 15px;
    border: 1px solid #29404e;
    border-radius: 13px;
    background: #101c27;
}
.rg-guide .number {
    display: grid;
    width: 34px;
    height: 34px;
    place-items: center;
    border-radius: 10px;
    color: #05251b;
    background: #53d6a2;
    font-weight: 950;
}
.rg-guide .step b {
    display: block;
    margin-bottom: 2px;
    color: #ffffff;
}
.rg-guide .step span {
    color: #9fb4ba;
    font-size: .88rem;
    line-height: 1.55;
}
.rg-guide .notes {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 9px;
    margin-top: 12px;
}
.rg-guide .note {
    padding: 13px 14px;
    border: 1px solid #29404e;
    border-radius: 12px;
    color: #adbec2;
    background: rgba(16, 28, 39, .72);
    font-size: .84rem;
}
.rg-guide .note b {
    display: block;
    margin-bottom: 3px;
    color: #ffcb6b;
}
.rg-guide .formula {
    margin-top: 12px;
    padding: 14px 16px;
    border-left: 4px solid #67b8ff;
    border-radius: 0 12px 12px 0;
    color: #c7d9dc;
    background: rgba(103, 184, 255, .08);
    font-size: .88rem;
}
.rg-guide .formula b { color: #8dccff; }
@media (max-width: 680px) {
    .rg-guide .notes { grid-template-columns: 1fr; }
}
</style>

<div class="rg-guide">
    <div class="principle">
        <div class="label">หลักการเลือกหมุดเริ่มต้น</div>
        <h3>หมุดเริ่มต้น = โหนดถนนที่ใกล้ “จุดกึ่งกลางประชากร” มากที่สุด</h3>
        <p>
            หมุดนี้มีหน้าที่สร้างขอบเขตค้นหา 20 นาทีเท่านั้น
            <strong>ไม่ใช่ CBD และไม่ใช่แปลงที่ต้องการลงทุน</strong>
        </p>
    </div>

    <div class="flow-title">🧭 Flow การหา CBD และ Rent Gradient</div>
    <div class="flow">
        <div class="step">
            <div class="number">1</div>
            <div>
                <b>ปักหมุดเริ่มต้น</b>
                <span>เลือกโหนดถนนที่ใกล้จุดกึ่งกลางประชากรมากที่สุด</span>
            </div>
        </div>

        <div class="step">
            <div class="number">2</div>
            <div>
                <b>คำนวณพื้นที่เดินทาง 20 นาที</b>
                <span>เลือกเวลา <code>[20]</code> ค่าเดียว เพื่อสร้างขอบเขตค้นหารอบกว้าง</span>
            </div>
        </div>

        <div class="step">
            <div class="number">3</div>
            <div>
                <b>รัน Network Analysis</b>
                <span>วิเคราะห์พื้นที่ 20 นาที แล้วหา <code>C20</code> = โหนดที่มี Closeness สูงสุด</span>
            </div>
        </div>

        <div class="step">
            <div class="number">4</div>
            <div>
                <b>ใช้ C20 เป็นหมุดใหม่</b>
                <span>ปิดหรือลบหมุดเดิม เลือกเวลา <code>[5]</code> แล้วคำนวณ Isochrone ใหม่จาก C20</span>
            </div>
        </div>

        <div class="step">
            <div class="number">5</div>
            <div>
                <b>รัน Network Analysis อีกครั้ง</b>
                <span>วิเคราะห์พื้นที่ 5 นาที แล้วหา <code>C5</code> = CBD Anchor ขั้นสุดท้าย</span>
            </div>
        </div>

        <div class="step">
            <div class="number">6</div>
            <div>
                <b>หา Golden Spots</b>
                <span>จัดอันดับจุดที่น่าสนใจรอบ C5 และตรวจประกอบด้วยผังเมือง รูปแปลง และประชากร</span>
            </div>
        </div>

        <div class="step">
            <div class="number">7</div>
            <div>
                <b>คำนวณ Rent Gradient</b>
                <span>ใช้ C5 เป็นจุดอ้างอิงของ <code>R(d) = R₀·e<sup>−λd</sup></code> เพื่อสร้าง Curve, Rings และ Rent Heat</span>
            </div>
        </div>
    </div>

    <div class="notes">
        <div class="note">
            <b>G20 ไม่ใช่ขั้นตอนหลัก</b>
            จุดกึ่งกลาง Travel Areas ใช้ชั่วคราวเฉพาะตอนที่ยังไม่มีผล Network
        </div>
        <div class="note">
            <b>สร้างพื้นที่ 5 นาทีใหม่</b>
            ต้องคำนวณจาก C20 ใหม่ ไม่ใช่ย่อรูปพื้นที่ 20 นาที
        </div>
        <div class="note">
            <b>รัน Network ใหม่เสมอ</b>
            หลังเปลี่ยนหมุดหรือเวลา เพื่อไม่ให้ C5 และ Golden Spots ใช้ผลเก่า
        </div>
    </div>

    <div class="formula">
        <b>หมายเหตุเรื่องราคา:</b>
        หากไม่มีตัวอย่างราคาจริงอย่างน้อย 2 จุดที่มีระยะต่างกัน
        ระบบจะแสดงดัชนีสัมพัทธ์ 0–100 ไม่ใช่ราคาตลาดจริง
    </div>
</div>
            """
        )


# ============================================================================
# SECTION 6: BUSINESS LOGIC ORCHESTRATORS
# ============================================================================

def perform_calculation(
    active_list: List[Tuple[int, Dict[str, Any]]]
) -> None:
    """Fetch isochrones for all active markers, compute CBD intersection."""
    # ---- Validation ----
    api_key = StateManager.get_api_key()
    if not api_key:
        st.warning("⚠️ กรุณาใส่ API Key")
        return
    if not active_list:
        st.warning("⚠️ กรุณาเลือกจุดอย่างน้อย 1 จุด")
        return
    time_intervals = StateManager.get_time_intervals()
    if not time_intervals:
        st.warning("⚠️ กรุณาเลือกช่วงเวลา")
        return

    travel_mode = StateManager.get_travel_mode()

    with st.spinner("กำลังคำนวณ Isochrone..."):
        all_features: List[Dict[str, Any]] = []
        ranges_str = ",".join(str(t * 60) for t in sorted(time_intervals))
        errors: List[str] = []

        for act_idx, (orig_idx, marker) in enumerate(active_list):
            features, error_msg = fetch_api_data_cached(
                api_key, travel_mode, ranges_str, marker["lat"], marker["lng"]
            )

            if features is None:
                errors.append(f"จุดที่ {orig_idx + 1}: {error_msg}")
                continue

            for f in features:
                f["properties"].update(
                    {
                        "travel_time_minutes": f["properties"].get("value", 0) / 60,
                        "original_index": orig_idx,
                        "active_index": act_idx,
                    }
                )
                all_features.append(f)

        # Display collected errors
        for error in errors:
            st.error(error)
        if not all_features:
            return  # All requests failed

        # Store isochrone results
        StateManager.set_isochrone_data(
            {"type": "FeatureCollection", "features": all_features}
        )

        # Calculate CBD intersection
        cbd_geom = calculate_intersection(all_features, len(active_list))
        if cbd_geom:
            StateManager.set_intersection_data(
                {
                    "type": "FeatureCollection",
                    "features": [
                        {
                            "type": "Feature",
                            "geometry": cbd_geom,
                            "properties": {"type": "cbd"},
                        }
                    ],
                }
            )
            st.toast("✅ พบพื้นที่ CBD!", icon="🎯")
        else:
            StateManager.set_intersection_data(None)
            st.toast("⚠️ ไม่พบพื้นที่ทับซ้อน", icon="⚠️")

        # Rent Gradient ผูกกับ CBD ใหม่ — รีเฟรชอัตโนมัติ (pure math, เร็วมาก)
        perform_rent_gradient(quiet=True)


def _run_network_analysis_with_progress(
    polygon_wkt_str: str, network_type: str
) -> Dict[str, Any]:
    """
    Thin UI wrapper that shows progress while the **cached** pure function runs.
    """
    progress_bar = st.progress(0)
    status_container = st.empty()

    try:
        # Stage 1: Prepare
        status_container.info("🔍 **Stage 1/3:** กำลังเตรียมข้อมูลพื้นที่...")
        progress_bar.progress(0.05)

        # Stage 2: Check cache
        is_cached = cached_graph_available(polygon_wkt_str, network_type)

        if is_cached:
            status_container.success("✅ **พบข้อมูลใน Cache!** กำลังโหลด...")
        else:
            status_container.warning(
                "⏳ **กำลังดาวน์โหลดข้อมูลครั้งแรก...** (อาจใช้เวลา 5-10 นาที)"
            )
        progress_bar.progress(0.10)

        # Stage 3: Compute
        status_container.info("🛣️ **Stage 2/3:** กำลังวิเคราะห์โครงข่ายถนน...")
        progress_bar.progress(0.30)

        result = compute_centrality_cached(polygon_wkt_str, network_type)

        progress_bar.progress(0.90)

        # Stage 4: Report
        if "error" in result:
            status_container.error(f"❌ {result['error']}")
        else:
            stats = result.get("stats", {})
            status_container.success(
                f"✅ **สำเร็จ!** วิเคราะห์ {stats.get('nodes_count', 0):,} โหนด "
                f"และ {stats.get('edges_count', 0):,} ถนน"
            )
        progress_bar.progress(1.0)

    finally:
        progress_bar.empty()
        status_container.empty()

    return result


def perform_network_analysis() -> None:
    """Orchestrate the full network analysis pipeline."""
    iso_data = StateManager.get_isochrone_data()
    if not iso_data:
        st.error("❌ No Isochrone data found. Please calculate isochrones first.")
        return

    with st.spinner(
        "กำลังรวมพื้นที่และวิเคราะห์โครงข่ายถนน (OSMnx)... อาจใช้เวลาสักครู่"
    ):
        try:
            # 1. Union all travel polygons
            feats_json = json.dumps(iso_data.get("features", []))
            combined_wkt = union_all_polygons_cached(feats_json)

            if not combined_wkt:
                st.error("❌ No polygons to analyze.")
                return

            # 2. Run analysis with progress UI
            net_type = TRAVEL_MODE_TO_NETWORK_TYPE.get(
                StateManager.get_travel_mode(), "drive"
            )
            result = _run_network_analysis_with_progress(combined_wkt, net_type)

            if "error" in result:
                st.error(f"❌ Network Analysis Failed: {result['error']}")
                st.info(
                    "💡 **Tips:**\n"
                    "- Try a larger area\n"
                    "- Check if the location has road data in OpenStreetMap\n"
                    "- Verify internet connection"
                )
            else:
                StateManager.set_network_data(result)
                score_info = (
                    f"Score: {result['top_node']['score']:.4f}"
                    if result.get("top_node")
                    else ""
                )
                st.toast(f"✅ Analysis Completed! {score_info}", icon="🏆")

                # มีโหนดถนนแล้ว — รีเฟรช Rent Gradient เพื่อสร้าง Rent Heat
                if StateManager.get_rent_data() is not None:
                    perform_rent_gradient(quiet=True)

        except Exception as e:
            st.error(f"❌ Processing Error: {e}")
            st.info(
                "💡 If the error persists, try a different location "
                "or smaller time intervals."
            )


def perform_automated_anchor() -> None:
    """Download one buffered graph, find both anchors in one pass, publish atomically."""
    context = _anchor_search_context()
    started = time.perf_counter()
    try:
        with st.spinner(
            "กำลังโหลดถนนพร้อม buffer 20% และค้นหา CBD… การโหลด OSM อาจใช้เวลานาน"
        ):
            polygon = anchor_study_polygon(*context["study_center"], context["study_radius_m"])
            fetch_started = time.perf_counter()
            graph, cached, error = _fetch_osm_graph(polygon.wkt, context["network_type"])
            load_seconds = time.perf_counter() - fetch_started
            if error or graph is None:
                raise ValueError(error or "No road graph returned.")
            found = find_cbd_anchors(
                graph, tuple(context["study_center"]), context["study_radius_m"])
            source = graph.graph.get("osm_source", "cache" if cached else "download")
            endpoint = graph.graph.get("overpass_endpoint", "disk-cache" if cached else "unknown")
            samples = StateManager.get_rent_samples()
            published = {}
            for objective, state_key in (
                ("composite", StateManager.K_AUTO_ANCHOR),
                ("closeness", StateManager.K_AUTO_ANCHOR_CLOSENESS),
            ):
                result = found[objective]
                result.update(
                    context=context,
                    graph_cached=cached,
                    graph_source_endpoint=endpoint,
                    graph={**found["graph"], "source": source, "endpoint": endpoint},
                    load_seconds=load_seconds,
                    total_seconds=time.perf_counter() - started,
                )
                anchor = result["anchor"]
                baseline = fit_rent_gradient_from_samples(samples, *context["study_center"])
                fitted = fit_rent_gradient_from_samples(samples, anchor["lat"], anchor["lon"])
                if baseline and fitted:
                    result["rent_fit_comparison"] = {
                        "center_r2": baseline["r2"],
                        "anchor_r2": fitted["r2"],
                        "delta_r2": fitted["r2"] - baseline["r2"],
                        "n_samples": fitted["n_samples"],
                    }
                published[state_key] = result
            published[StateManager.K_AUTO_ANCHOR_EVIDENCE] = None
            if st.session_state.get("anchor_use_evidence"):
                with st.spinner("กำลังตรวจผังเมืองรวมและรูปแปลงที่ดินของผู้สมัคร…"):
                    legend, legend_source = load_cityplan_legend()
                    evidence = run_evidence_stage(
                        found, tuple(context["study_center"]), context["study_radius_m"],
                        legend=legend, legend_source=legend_source)
                    evidence["context"] = context
                    published[StateManager.K_AUTO_ANCHOR_EVIDENCE] = evidence
            st.session_state.update(published)  # all anchors become visible together
            StateManager.clear_results(["rent"])
            perform_rent_gradient(quiet=True)
    except Exception as exc:
        st.error(f"ค้นหา Automated Anchor ไม่สำเร็จ: {exc}")
        return
    st.rerun()


def _rent_anchor_input() -> Optional[Dict[str, Any]]:
    """Anchor handed to the Rent Gradient: the composite one, or the evidence anchor on opt-in."""
    automated = st.session_state.get(StateManager.K_AUTO_ANCHOR)
    evidence = st.session_state.get(StateManager.K_AUTO_ANCHOR_EVIDENCE)
    if (automated and evidence and evidence.get("schema") == EVIDENCE_SCHEMA
            and evidence.get("evidence_anchor") and st.session_state.get("rent_use_evidence_anchor")):
        return {**automated, "anchor": dict(evidence["evidence_anchor"])}
    return automated


def _on_rent_anchor_toggle() -> None:
    StateManager.clear_results(["rent"])
    perform_rent_gradient(quiet=True)


def perform_rent_gradient(quiet: bool = False) -> None:
    """Orchestrate Rent Gradient computation (pure math — ไม่มี API call)."""
    iso_data = StateManager.get_isochrone_data()
    automated = _rent_anchor_input()
    if not iso_data and not automated:
        if not quiet:
            st.error("❌ กรุณาคำนวณ Isochrone หรือค้นหา Automated Anchor ก่อน")
        return

    data = compute_rent_gradient_data(
        StateManager.get_intersection_data(),
        StateManager.get_network_data(),
        iso_data,
        StateManager.get_markers(),
        StateManager.get_rent_samples(),
        StateManager.get_rent_unit(),
        automated_anchor=automated,
    )
    if "error" in data:
        StateManager.set_rent_data(None)
        if not quiet:
            st.error(f"❌ {data['error']}")
        return

    StateManager.set_rent_data(data)
    if not quiet:
        model = data["model"]
        mode = "โหมดดัชนี" if model["is_index"] else fit_quality_label(model)
        warn = fit_quality_warning(model)
        st.toast(
            f"💰 Rent Gradient พร้อม ({mode}) λ={model['lam']:.4f}"
            + (" — ⚠️ ตัวอย่างน้อย" if warn and "น้อยกว่า" in warn else ""),
            icon="⚠️" if warn else "✅",
        )


# ------------------------------------------------------------------ Space Syntax: data access
def fetch_graph(lat: float, lon: float, radius_m: float, network_type: str
                ) -> Tuple[Optional[Any], str, Optional[str]]:
    """``(graph, source_label, error)`` for the study circle plus its 20 % buffer.

    Uses this page's own loader (disk cache + Overpass failover) on the same polygon as the CBD-anchor search, so
    a graph already cached by the anchor search — or a bigger one that covers it — is reused, never downloaded twice.
    """
    try:
        polygon = anchor_study_polygon(lat, lon, radius_m)
        graph, cached, error = _fetch_osm_graph(polygon.wkt, network_type)
    except Exception as exc:
        return None, "", f"โหลดโครงข่ายถนนไม่สำเร็จ: {type(exc).__name__}: {exc}"
    if graph is None:
        return None, "", error
    label = graph.graph.get("osm_source") or ("cache" if cached else "download")
    return graph, f"Rent_Gradient cache/failover ({label})", None


def load_bundled_graph() -> Tuple[Optional[Any], str, Optional[str]]:
    """Largest road graph stored in ``Geoapify_Map/osmnx_cache.zip`` (Chiang Khong, works offline).

    Pickles are read through the allow-list unpickler (``_load_graph_bytes``), never plain ``pickle``.
    """
    if not BUNDLED_CACHE_ZIP.exists():
        return None, "", f"ไม่พบไฟล์ {BUNDLED_CACHE_ZIP.name}"
    best: Optional[Any] = None
    try:
        with zipfile.ZipFile(BUNDLED_CACHE_ZIP) as archive:
            for info in sorted(archive.infolist(), key=lambda i: i.filename):
                if not info.filename.endswith(".pkl") or info.file_size > MAX_CACHE_ENTRY_BYTES:
                    continue
                try:
                    graph = _load_graph_bytes(archive.read(info))
                except Exception:
                    continue
                if best is None or len(graph) > len(best):
                    best = graph
    except (zipfile.BadZipFile, OSError) as exc:
        return None, "", f"อ่าน {BUNDLED_CACHE_ZIP.name} ไม่ได้: {exc}"
    if best is None:
        return None, "", f"ไม่พบกราฟที่อ่านได้ใน {BUNDLED_CACHE_ZIP.name}"
    return best, f"ตัวอย่างเชียงของ ({BUNDLED_CACHE_ZIP.name})", None


def rent_anchor_point() -> Optional[Dict[str, Any]]:
    """The CBD anchor the Rent Gradient currently uses (read-only), as ``{lat, lon, source}``."""
    data = StateManager.get_rent_data()
    anchor = data.get("anchor") if isinstance(data, dict) else None
    try:
        return {"lat": float(anchor["lat"]), "lon": float(anchor["lon"]),
                "source": str(anchor.get("source", "CBD anchor"))}
    except (TypeError, KeyError, ValueError):
        return None


# ------------------------------------------------------------------ Space Syntax: stage (one button)
def ss_study_key() -> Tuple[Any, ...]:
    """What identifies the road network the analysis runs on: study centre, display radius, network type."""
    state = st.session_state
    return (round(float(state["anchor_lat"]), 6), round(float(state["anchor_lon"]), 6),
            float(state["ss_radius_m"]), state["ss_network"])


def ss_params() -> Dict[str, Any]:
    """The analysis settings currently chosen in the sidebar (radii sorted, global last)."""
    state = st.session_state
    kind = state["ss_kind"]
    radii = sorted((RADIUS_OPTIONS[label] for label in state["ss_radii"] if label in RADIUS_OPTIONS),
                   key=lambda r: (r is None, r or 0.0))
    return {"kind": kind, "turn": float(state["ss_turn"]) if kind == "topological" else 0.0,
            "radii": radii, "with_choice": bool(state["ss_choice"])}


def _ss_load_network(demo: bool) -> bool:
    """Make sure the segment network of the current study area is in the session. True when it is."""
    state = st.session_state
    key: Tuple[Any, ...] = ("demo",) if demo else ss_study_key()
    if state.get(SS_NET) is not None and state.get(SS_KEY) == key:
        return True                                  # same area: parameters changed only — no download, no rebuild
    with st.spinner("กำลังอ่านตัวอย่างจาก repo…" if demo else
                    "กำลังโหลดโครงข่ายถนน… (ครั้งแรกที่ยังไม่มี cache อาจใช้เวลานาน)"):
        if demo:
            graph, source, error = load_bundled_graph()
        else:
            graph, source, error = fetch_graph(key[0], key[1], key[2], key[3])
        if graph is None:
            st.error(error or "โหลดโครงข่ายถนนไม่สำเร็จ")
            return False
        try:
            net = build_segment_network(graph)
        except ValueError as exc:
            st.error(str(exc))
            return False
    meta = ({"source": source, "lat": net.origin[0], "lon": net.origin[1], "radius_m": None, "network": "drive"}
            if demo else
            {"source": source, "lat": key[0], "lon": key[1], "radius_m": key[2], "network": key[3]})
    meta.update(nodes=graph.number_of_nodes(), edges=graph.number_of_edges())
    state.update({SS_NET: net, SS_META: meta, SS_KEY: key, SS_MASK: _display_mask(net, meta)})
    state.pop(SS_RESULT, None)
    return True


def perform_space_syntax(intents: Dict[str, Any]) -> None:
    """Load the study-area road network if needed, then run the segment analysis (one button)."""
    state = st.session_state
    params = intents["ss_params"]
    if not params["radii"]:
        st.error("เลือกรัศมีอย่างน้อย 1 ค่า")
        return
    if not _ss_load_network(bool(intents.get("demo"))):
        return
    bar = st.progress(0.0, text="กำลังวิเคราะห์ Space Syntax…")
    try:
        result = analyse_network(
            state[SS_NET], kind=params["kind"], radii=params["radii"], with_choice=params["with_choice"],
            topological_turn_deg=params["turn"],
            progress=lambda frac, text: bar.progress(min(max(frac, 0.0), 1.0), text=f"กำลังวิเคราะห์… {text}"))
    except Exception as exc:  # surfaces ValueError (size limits) and anything unexpected
        st.error(f"วิเคราะห์ไม่สำเร็จ: {type(exc).__name__}: {exc}")
        return
    finally:
        bar.empty()
    result.meta["params"] = dict(params)
    state[SS_RESULT] = result
    state[SS_RUN] = int(state.get(SS_RUN, 0)) + 1
    st.toast(f"✅ Space Syntax เสร็จใน {result.meta['seconds']:.1f} วินาที", icon="🧭")


def handle_map_click(map_output: Optional[Dict[str, Any]], locked: bool) -> None:
    """Process a map click event — add marker if debounce passes."""
    if locked:
        return
    if not map_output:
        return
    clicked = map_output.get("last_clicked")
    if not clicked:
        return

    last = StateManager.get_last_click()
    if should_add_marker(clicked["lat"], clicked["lng"], last):
        StateManager.add_marker(clicked["lat"], clicked["lng"])
        StateManager.record_click(clicked["lat"], clicked["lng"])
        StateManager.clear_results(["isochrone", "intersection", "rent"])
        st.rerun()


# ============================================================================
# SECTION 7: MAIN EXECUTION
# ============================================================================

# stage table: the sidebar button that was pressed → the orchestrator it runs (order = pipeline order)
STAGES: Tuple[Tuple[str, Callable[[Dict[str, Any]], None]], ...] = (
    ("calc", lambda intents: perform_calculation(intents["active"])),
    ("network", lambda intents: perform_network_analysis()),
    ("rent", lambda intents: perform_rent_gradient()),
    ("anchor", lambda intents: perform_automated_anchor()),
    ("space_syntax", perform_space_syntax),
)


def run_stages(intents: Dict[str, Any]) -> None:
    for key, run in STAGES:
        if intents.get(key):
            run(intents)


def main() -> None:
    st.set_page_config(**PAGE_CONFIG)

    # Inject minimal CSS to fix spacing
    st.markdown(
        "<style>"
        ".block-container { padding-top: 2rem; padding-bottom: 0rem; } "
        "h1 { margin-bottom: 0px; } "
        "div[data-testid=\"stHorizontalBlock\"] button "
        "{ padding: 0rem 0.5rem; }"
        "</style>",
        unsafe_allow_html=True,
    )

    StateManager.initialize()
    skipped = st.session_state.pop("_import_skipped", None)
    if skipped:
        st.warning("ข้ามค่าที่ไม่ถูกต้องตอนนำเข้า config: " + ", ".join(skipped))

    intents = render_sidebar()                  # 1. sidebar → what the user asked for
    run_stages(intents)                         # 2. run it (cached, error-isolated orchestrators)
    ctx = build_ctx()                           # 3. one read-only snapshot for the layers
    with st.sidebar:
        _render_sidebar_layers_panel(ctx, intents["locked"])
    render_header()
    render_metrics_row()
    map_output = render_map(ctx)
    render_analytics_panel()
    handle_map_click(map_output, intents["locked"])


if __name__ == "__main__":
    main()
