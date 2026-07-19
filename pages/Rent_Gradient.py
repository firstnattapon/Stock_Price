"""
Geoapify CBD x Longdo GIS + Network Analysis + Rent Gradient (Bid-Rent)
=======================================================================
Refactored: Modular Monolith Architecture
- Section 1: Constants & Configuration
- Section 2: State Manager (Centralized Session State)
- Section 3: Pure Functions (No st.* — testable, cacheable)
  - รวม Rent Gradient Engine ตามทฤษฎี Alonso-Muth-Mills: R(d) = R₀·e^(−λ·d)
- Section 4: Cached Wrappers (@st.cache_data)
- Section 5: UI Components (st.* allowed)
- Section 6: Business Logic Orchestrators
- Section 7: Main Execution
"""

import streamlit as st
import folium
from folium.plugins import Fullscreen, MeasureControl, MousePosition
from branca.element import MacroElement, Template
from streamlit_folium import st_folium
import requests
from shapely.geometry import shape, mapping
from shapely.ops import unary_union
from shapely import wkt
import json
import networkx as nx
import osmnx as ox
import matplotlib
import matplotlib.colors as colors
from typing import List, Dict, Any, Optional, Tuple
import time
import hashlib
import pickle
import os
from pathlib import Path
import zipfile
import io
import xml.etree.ElementTree as ET
import pandas as pd
from math import radians, sin, cos, sqrt, atan2, log, exp, pi

# scipy เป็น optional accelerator สำหรับ closeness (fallback เป็น networkx ถ้าไม่มี)
try:
    import numpy as np
    from scipy.sparse import csr_matrix
    from scipy.sparse.csgraph import dijkstra as csgraph_dijkstra
    HAS_SCIPY: bool = True
except Exception:
    HAS_SCIPY = False


# ============================================================================
# SECTION 1: CONSTANTS & CONFIGURATION
# ============================================================================

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
    "golden_land_weights": {
        "closeness": 0.50,
        "degree": 0.30,
        "low_traffic_bonus": 0.20,
    },
}

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
]

# Keys to persist as precomputed outputs (avoid recalculation after import)
RESULT_KEYS_TO_SAVE: List[str] = [
    "isochrone_data",
    "intersection_data",
    "network_data",
    "rent_gradient_data",
]

# GitHub Cache Repository Configuration
GITHUB_BUNDLE_URL: str = (
    "https://raw.githubusercontent.com/firstnattapon/Stock_Price/main/Geoapify_Map/%E0%B9%80%E0%B8%8A%E0%B8%B5%E0%B8%A2%E0%B8%87%E0%B8%82%E0%B8%AD%E0%B8%87.zip"
)


# ============================================================================
# SECTION 2: STATE MANAGER (Centralized Session State)
# ============================================================================

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

        # Ensure every marker dict has an 'active' key
        for m in st.session_state[cls.K_MARKERS]:
            m.setdefault("active", True)

    @staticmethod
    def _load_remote_defaults(defaults: Dict[str, Any]) -> Optional[List[Dict]]:
        """Attempt to load initial state from the remote JSON URL."""
        try:
            resp = requests.get(
                DEFAULT_CONFIG["JSON_URL"], timeout=TIMEOUT_INIT
            )
            if resp.status_code == 200:
                data: Dict[str, Any] = resp.json()
                # Merge remote settings into defaults
                for k in defaults:
                    if k in data:
                        defaults[k] = data[k]
                return data.get("markers")
        except Exception:
            pass
        return None

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
            layers = ["isochrone", "intersection", "network", "rent"]

        if "isochrone" in layers:
            st.session_state[cls.K_ISOCHRONE] = None
        if "intersection" in layers:
            st.session_state[cls.K_INTERSECTION] = None
        if "network" in layers:
            st.session_state[cls.K_NETWORK] = None
        if "rent" in layers:
            st.session_state[cls.K_RENT_DATA] = None

    @classmethod
    def reset(cls) -> None:
        """Reset to factory defaults."""
        st.session_state[cls.K_MARKERS] = [dict(cls._DEFAULT_MARKER)]
        st.session_state[cls.K_LAST_CLICK] = None
        cls.clear_results()

    @classmethod
    def import_config(cls, data: Dict[str, Any]) -> None:
        """Import settings + optional precomputed outputs from config."""
        if "markers" in data:
            st.session_state[cls.K_MARKERS] = data["markers"]

        settings = data.get("settings", {})
        for k, v in settings.items():
            if k in SESSION_KEYS_TO_SAVE:
                st.session_state[k] = v

        # Start from a clean slate so keys absent from the payload
        # don't keep stale results anchored to the previous CBD.
        cls.clear_results()

        precomputed_results = data.get("precomputed_results", {})
        for result_key in RESULT_KEYS_TO_SAVE:
            if result_key in precomputed_results:
                st.session_state[result_key] = precomputed_results[result_key]

        # Backward compatibility: allow old flat structure.
        for result_key in RESULT_KEYS_TO_SAVE:
            if result_key in data:
                st.session_state[result_key] = data[result_key]

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


def compute_golden_land_opportunities(
    graph: nx.MultiDiGraph,
    closeness_cent: Dict[Any, float],
    edge_betweenness_cent: Dict[Tuple[Any, Any], float],
    top_n: int = 10,
) -> List[Dict[str, Any]]:
    """
    Rank candidate nodes for "golden land" discovery.

    Principle / Equation:
    score = 0.50*closeness_norm + 0.30*degree_norm + 0.20*(1-edge_betweenness_norm)
    """
    if not closeness_cent:
        return []

    weights = NETWORK_CONFIG["golden_land_weights"]
    max_close = max(closeness_cent.values()) or 1.0

    degree_dict = dict(graph.degree())
    max_degree = max(degree_dict.values()) if degree_dict else 1
    if max_degree <= 0:
        max_degree = 1

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
    return ranked[:top_n]


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

    return {
        "r0": r0,
        "lam": lam,
        "r2": r2,
        "n_samples": n,
        "points": [{"d": p[0], "rent": exp(p[1])} for p in pts],
    }


def resolve_cbd_anchor(
    intersection_data: Optional[Dict[str, Any]],
    network_data: Optional[Dict[str, Any]],
    isochrone_data: Optional[Dict[str, Any]],
    markers: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """
    หาจุดยึด CBD สำหรับ Rent Gradient ตามลำดับความน่าเชื่อถือ:
    1) centroid ของ CBD Zone (จุดตัด isochrone)
    2) Integration Center จาก Network Analysis
    3) centroid ของ Travel Areas ทั้งหมด
    4) ค่าเฉลี่ยตำแหน่งหมุดที่ active
    """
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


def compute_rent_gradient_data(
    intersection_data: Optional[Dict[str, Any]],
    network_data: Optional[Dict[str, Any]],
    isochrone_data: Optional[Dict[str, Any]],
    markers: List[Dict[str, Any]],
    samples: List[Dict[str, Any]],
    unit_label: str,
) -> Dict[str, Any]:
    """
    คำนวณ Rent Gradient ทั้งชุด (pure, JSON-serializable):
    anchor → fit/default model → rings + curve + rent heat.
    """
    anchor = resolve_cbd_anchor(intersection_data, network_data, isochrone_data, markers)
    if anchor is None:
        return {"error": "ไม่พบจุดยึด CBD — กรุณาปักหมุดและคำนวณ Isochrone ก่อน"}

    d_max = isochrone_max_distance_km(anchor["lat"], anchor["lon"], isochrone_data)

    fit = fit_rent_gradient_from_samples(samples, anchor["lat"], anchor["lon"])
    if fit is not None:
        r0, lam, r2 = fit["r0"], fit["lam"], fit["r2"]
        n_samples = fit["n_samples"]
        is_index = False
        samples_scatter = fit["points"]
        # ขยายขอบเขตกราฟ/วงแหวนให้คลุมตัวอย่างที่อยู่ไกลกว่า Travel Areas
        d_max = max(d_max, max((p["d"] for p in samples_scatter), default=0.0) * 1.05)
    else:
        r0 = RENT_CONFIG["base_index"]
        lam = log(RENT_CONFIG["edge_decay_ratio"]) / d_max
        r2 = None
        n_samples = 0
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

    return {
        "anchor": anchor,
        "model": {
            "r0": r0,
            "lam": lam,
            "r2": r2,
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


def load_graph_from_cache(cache_key: str) -> Optional[nx.MultiDiGraph]:
    """Load a cached OSM graph from disk."""
    cache_file = CACHE_DIR / f"osm_graph_{cache_key}.pkl"
    if cache_file.exists():
        try:
            with open(cache_file, "rb") as f:
                return pickle.load(f)
        except Exception:
            return None
    return None


def save_graph_to_cache(cache_key: str, graph: nx.MultiDiGraph) -> None:
    """Persist an OSM graph to disk."""
    cache_file = CACHE_DIR / f"osm_graph_{cache_key}.pkl"
    try:
        with open(cache_file, "wb") as f:
            pickle.dump(graph, f, protocol=pickle.HIGHEST_PROTOCOL)
    except Exception:
        pass  # Caching is best-effort


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
                if not name.startswith("osm_graph_") or not name.endswith(".pkl"):
                    result["errors"].append(f"Skipped invalid file: {name}")
                    continue

                target_path = CACHE_DIR / name
                if target_path.exists():
                    result["skipped"] += 1
                    continue

                try:
                    data = zf.read(name)
                    # Validate pickle
                    pickle.load(io.BytesIO(data))
                    with open(target_path, "wb") as f:
                        f.write(data)
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

        G = load_graph_from_cache(cache_key)
        if G is not None:
            return G, True, None

        G = ox.graph_from_polygon(
            polygon_geom, network_type=network_type, truncate_by_edge=True
        )
        save_graph_to_cache(cache_key, G)
        return G, False, None

    except ValueError as e:
        return None, False, f"Invalid geometry: {str(e)}"
    except ox._errors.InsufficientResponseError:
        return None, False, (
            "No OSM data available for this area. "
            "Try a different location or larger region."
        )
    except Exception as e:
        return None, False, f"Failed to fetch OSM graph: {str(e)}"


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

    # สร้าง sparse adjacency (เก็บ min length เมื่อมี parallel edges)
    nodelist = list(G_lcc.nodes)
    idx = {node: i for i, node in enumerate(nodelist)}
    best_len: Dict[Tuple[int, int], float] = {}
    for u, v, length in G_lcc.edges(data="length", default=1.0):
        if u == v:
            continue
        a, b = idx[u], idx[v]
        if a > b:
            a, b = b, a
        L = float(length)
        if L < best_len.get((a, b), float("inf")):
            best_len[(a, b)] = L

    rows = np.fromiter((k[0] for k in best_len), dtype=np.int32, count=len(best_len))
    cols = np.fromiter((k[1] for k in best_len), dtype=np.int32, count=len(best_len))
    vals = np.fromiter(best_len.values(), dtype=np.float64, count=len(best_len))
    csr = csr_matrix((vals, (rows, cols)), shape=(n, n))

    if n <= NETWORK_CONFIG["closeness_exact_threshold"]:
        dist = csgraph_dijkstra(csr, directed=False)
        sums = dist.sum(axis=1)
        k_eff = n - 1
        method = "exact-scipy"
    else:
        k = min(NETWORK_CONFIG["closeness_k_pivots"], n)
        rng = np.random.default_rng(42)
        pivots = rng.choice(n, size=k, replace=False)
        dist = csgraph_dijkstra(csr, directed=False, indices=pivots)
        sums = dist.sum(axis=0)
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
        "stats": {
            "nodes_count": len(G.nodes),
            "edges_count": len(G.edges),
            "used_approximation": is_large_graph,
            "closeness_method": closeness_method,
            "was_cached": was_cached,
        },
    }


# ============================================================================
# SECTION 4: CACHED WRAPPERS (@st.cache_data)
# ============================================================================

@st.cache_data(show_spinner=False, ttl=NETWORK_CONFIG["cache_ttl_seconds"])
def fetch_api_data_cached(
    api_key: str,
    travel_mode: str,
    ranges_str: str,
    marker_lat: float,
    marker_lon: float,
) -> Tuple[Optional[List[Dict[str, Any]]], Optional[str]]:
    """Streamlit-cached wrapper around the isochrone API call."""
    return safe_fetch_isochrone(api_key, travel_mode, ranges_str, marker_lat, marker_lon)


@st.cache_data(show_spinner=False, ttl=NETWORK_CONFIG["cache_ttl_seconds"])
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


@st.cache_data(show_spinner=False, ttl=NETWORK_CONFIG["cache_ttl_seconds"])
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


@st.cache_data(show_spinner=False)
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

def _add_wms_layer(
    m: folium.Map,
    layers: str,
    name: str,
    show: bool,
    opacity: float = 1.0,
) -> None:
    """Helper — add a Longdo WMS overlay to a Folium map."""
    folium.WmsTileLayer(
        url=LONGDO_WMS_URL,
        layers=layers,
        name=name,
        fmt="image/png",
        transparent=True,
        version="1.1.1",
        attr=f"{name} / Longdo Map",
        show=show,
        opacity=opacity,
    ).add_to(m)


def _legend_swatch_row(color_css: str, label: str, extra_style: str = "") -> str:
    """HTML แถวเดียวของ legend: สี่เหลี่ยมสี + ป้ายข้อความ."""
    return (
        '<div style="display:flex; align-items:center; gap:6px; margin:1px 0;">'
        f'<span style="display:inline-block; width:14px; height:14px; border-radius:3px; '
        f'background:{color_css}; {extra_style}"></span>'
        f'<span>{label}</span></div>'
    )


def _add_map_legend(m: folium.Map) -> None:
    """เพิ่มกล่อง Legend มุมล่างซ้าย อธิบายทุกเลเยอร์ที่กำลังแสดงอยู่."""
    clrs = StateManager.get_colors()
    rows: List[str] = []

    if StateManager.get_isochrone_data():
        rows.append('<div style="font-weight:600; margin-bottom:2px;">เวลาเดินทาง</div>')
        rows.append(_legend_swatch_row(clrs["step1"], "≤ 10 นาที"))
        rows.append(_legend_swatch_row(clrs["step2"], "≤ 20 นาที"))
        rows.append(_legend_swatch_row(clrs["step3"], "≤ 30 นาที"))
        rows.append(_legend_swatch_row(clrs["step4"], "> 30 นาที"))

    if StateManager.get_intersection_data():
        rows.append(_legend_swatch_row(
            "#FFD700", "CBD Zone", "border:2px dashed #FF8C00;"
        ))

    net_data = StateManager.get_network_data()
    if net_data and st.session_state.show_golden_spots and net_data.get("golden_spots"):
        rows.append(_legend_swatch_row(
            "#FFD60A", "💎 Golden Spot", "border:2px solid #8C6A00; border-radius:50%;"
        ))

    rent_data = StateManager.get_rent_data()
    if rent_data and "error" not in rent_data and st.session_state.show_rent_rings:
        model = rent_data["model"]
        unit = "ดัชนี" if model["is_index"] else model["unit"]
        rows.append(
            '<div style="font-weight:600; margin:4px 0 2px;">Rent Gradient</div>'
            '<div style="display:flex; align-items:center; gap:6px;">'
            f'<span style="display:inline-block; width:56px; height:10px; border-radius:3px; '
            f'background:linear-gradient(90deg, {RENT_RAMP[-1]}, {RENT_RAMP[0]});"></span>'
            f'<span>CBD → ขอบ ({unit})</span></div>'
        )

    if not rows:
        return

    html = (
        '<div style="position:fixed; bottom:18px; left:12px; z-index:9999; '
        'background:rgba(255,255,255,0.93); border:1px solid rgba(11,11,11,0.10); '
        'border-radius:8px; padding:8px 10px; font-size:12px; color:#0b0b0b; '
        'box-shadow:0 1px 4px rgba(0,0,0,0.18); line-height:1.45; '
        'font-family:system-ui, -apple-system, sans-serif;">'
        + "".join(rows)
        + "</div>"
    )
    legend = MacroElement()
    legend._template = Template(
        "{% macro html(this, kwargs) %}" + html + "{% endmacro %}"
    )
    m.get_root().add_child(legend)


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

        st.markdown("##### Layer Controls")
        st.checkbox("Show Roads (Betweenness)", key="show_betweenness", disabled=locked)
        st.caption("🔴: ทางผ่านหลัก (High Traffic Flow)")
        st.checkbox("Show Nodes (Integration)", key="show_closeness", disabled=locked)
        st.caption("⚫: จุดเข้าถึงง่าย (Central Hub)")
        st.checkbox("Show Golden Spots", key="show_golden_spots", disabled=locked)
        st.caption("💎: จุดทำเลที่ดินทอง (คะแนนรวมสูง)")

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


def _render_sidebar_rent_panel(locked: bool) -> bool:
    """
    Render the Rent Gradient (Bid-Rent) expander.

    Returns ``True`` if the user clicked **คำนวณ Rent Gradient**.
    """
    with st.expander("💰 Rent Gradient (Bid-Rent)", expanded=True):
        st.caption("หลัก Alonso-Muth-Mills: **R(d) = R₀ · e^(−λ·d)** — ค่าเช่าลดลงตามระยะจาก CBD")

        can_run = StateManager.get_isochrone_data() is not None
        if not can_run:
            st.warning("⚠️ **Scope:** กรุณาคำนวณ Isochrone ก่อน", icon="🛑")

        # ---- Calibration samples ----
        st.markdown("##### 🧾 ตัวอย่างราคาจริง (Calibration)")
        st.caption(
            "ใส่ ≥ 2 จุดที่ระยะต่างกันเพื่อ fit λ จากตลาดจริง — "
            "เว้นว่างไว้ระบบจะใช้ดัชนี 0–100"
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

        # ---- Layer toggles ----
        st.checkbox("🌈 Rent Rings (วงแหวนราคา)", key="show_rent_rings", disabled=locked)
        st.checkbox("🔥 Rent Heat (โหนดถนน)", key="show_rent_nodes", disabled=locked)
        st.caption("Rent Heat ต้องรัน Network Analysis ก่อน")

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
                c4.metric("R² (fit)", f"{model['r2']:.3f}")
            else:
                c4.metric("Calibration", "ดัชนี (ไม่มีตัวอย่าง)")

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


def _render_sidebar_map_settings(locked: bool) -> None:
    """Map & Layer settings expander."""
    with st.expander("⚙️ ตั้งค่าแผนที่ & Layers", expanded=True):
        st.selectbox("สไตล์แผนที่", list(MAP_STYLES.keys()), key="map_style_name", disabled=locked)
        st.checkbox("🚦 การจราจร (Google Traffic)", key="show_traffic", disabled=locked)
        st.checkbox("👥 ความหนาแน่นประชากร", key="show_population", disabled=locked)

        c1, c2 = st.columns([0.65, 0.35])
        c1.checkbox("🏙️ ผังเมืองรวม", key="show_cityplan", disabled=locked)
        if st.session_state.show_cityplan:
            c2.slider(
                "Op.", 0.2, 1.0, key="cityplan_opacity", label_visibility="collapsed", disabled=locked
            )

        st.checkbox("📜 รูปแปลงที่ดิน", key="show_dol", disabled=locked)
        st.checkbox("🚂 แนวรถไฟเชียงของ", key="show_railway", disabled=locked)

        st.markdown("##### 🚗 การเดินทาง (Isochrone)")
        st.selectbox(
            "โหมด",
            list(TRAVEL_MODE_NAMES.keys()),
            format_func=TRAVEL_MODE_NAMES.get,
            key="travel_mode",
            disabled=locked,
        )
        st.multiselect("เวลา (นาที)", TIME_OPTIONS, key="time_intervals", disabled=locked)


def render_sidebar() -> Tuple[bool, bool, bool, List[Tuple[int, Dict[str, Any]]]]:
    """
    Orchestrate the full sidebar — เรียงตามลำดับ pipeline:
    ① ปักหมุด → ② Isochrone CBD → ③ Network → ④ Rent Gradient → ตั้งค่าแผนที่

    Returns:
        ``(do_calculate, do_network, do_rent, active_markers_list)``
    """
    with st.sidebar:
        st.header("⚙️ การตั้งค่า")

        ui_locked = st.toggle("🔒 Lock Active Markers + เมนูทั้งหมด", key=StateManager.K_UI_LOCKED)
        _render_sidebar_config_section(ui_locked)
        st.markdown("---")
        _render_sidebar_marker_input(ui_locked)

        st.text_input("Geoapify API Key", key="api_key", type="password", disabled=ui_locked)

        active_list = _render_sidebar_marker_list(ui_locked)

        do_calc: bool = st.button(
            "🧩 ① คำนวณหา Isochrone CBD",
            type="primary",
            use_container_width=True,
            disabled=ui_locked,
        )
        st.markdown("---")

        do_network = _render_sidebar_network_panel(ui_locked)
        st.markdown("---")

        do_rent = _render_sidebar_rent_panel(ui_locked)
        st.markdown("---")

        _render_sidebar_map_settings(ui_locked)

    return do_calc, do_network, do_rent, active_list


def render_map() -> Optional[Dict[str, Any]]:
    """Build and display the Folium map. Returns the ``st_folium`` output dict."""
    style_conf = MAP_STYLES[StateManager.get_map_style_name()]
    markers = StateManager.get_markers()
    center = (
        [markers[-1]["lat"], markers[-1]["lng"]]
        if markers
        else [DEFAULT_CONFIG["LAT"], DEFAULT_CONFIG["LON"]]
    )

    m = folium.Map(
        location=center,
        zoom_start=14,
        tiles=style_conf["tiles"],
        attr=style_conf["attr"],
    )

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

    # ---- Traffic overlay ----
    if st.session_state.show_traffic:
        folium.TileLayer(
            tiles="https://mt1.google.com/vt?lyrs=h,traffic&x={x}&y={y}&z={z}",
            attr="Google Traffic",
            name="Google Traffic",
            overlay=True,
        ).add_to(m)

    # ---- Rent Gradient Layers (วาดก่อนเพื่อให้อยู่ใต้เลเยอร์วิเคราะห์อื่น) ----
    rent_data = StateManager.get_rent_data()
    rent_model = None
    rent_anchor = None
    if rent_data and "error" not in rent_data:
        rent_model = rent_data["model"]
        rent_anchor = rent_data["anchor"]

        if st.session_state.show_rent_rings and rent_data.get("rings_geojson"):
            folium.GeoJson(
                rent_data["rings_geojson"],
                name="Rent Gradient Rings",
                style_function=lambda x: {
                    "fillColor": x["properties"]["color"],
                    "color": x["properties"]["color"],
                    "weight": 1,
                    "fillOpacity": RENT_CONFIG["ring_fill_opacity"],
                },
                tooltip=folium.GeoJsonTooltip(
                    fields=["band", "rent_label"],
                    aliases=["ระยะจาก CBD:", "ค่าเช่าคาดการณ์:"],
                    localize=True,
                ),
            ).add_to(m)

        if st.session_state.show_rent_nodes and rent_data.get("rent_nodes_geojson"):
            folium.GeoJson(
                rent_data["rent_nodes_geojson"],
                name="Rent Heat (Nodes)",
                marker=folium.CircleMarker(),
                style_function=lambda x: {
                    "fillColor": x["properties"]["color"],
                    "color": x["properties"]["color"],
                    "weight": 1,
                    "radius": 3,
                    "fillOpacity": 0.85,
                },
                tooltip=folium.GeoJsonTooltip(
                    fields=["rent"],
                    aliases=["ค่าเช่าคาดการณ์:"],
                    localize=True,
                ),
            ).add_to(m)

        # จุดยึด CBD ของโมเดล
        folium.Marker(
            [rent_anchor["lat"], rent_anchor["lon"]],
            tooltip=f"จุดยึด CBD — {rent_anchor['source']}",
            popup=folium.Popup(
                f"<b>CBD Anchor</b><br>{rent_anchor['source']}<br>"
                f"R₀ = {format_rent_value(rent_model['r0'], rent_model)}",
                max_width=260,
            ),
            icon=folium.Icon(color="darkblue", icon="building", prefix="fa"),
        ).add_to(m)

    # ---- Network Analysis Layers ----
    net_data = StateManager.get_network_data()
    if net_data and "error" not in net_data:
        # Edges (Betweenness)
        if st.session_state.show_betweenness and net_data.get("edges"):
            folium.GeoJson(
                net_data["edges"],
                name="Road Betweenness",
                style_function=lambda x: {
                    "color": x["properties"]["color"],
                    "weight": x["properties"]["stroke_weight"],
                    "opacity": 0.8,
                },
                tooltip=folium.GeoJsonTooltip(
                    fields=["betweenness"],
                    aliases=["Betweenness Score:"],
                    localize=True,
                ),
            ).add_to(m)

        # Nodes (Closeness)
        if st.session_state.show_closeness and net_data.get("nodes"):
            folium.GeoJson(
                net_data["nodes"],
                name="Node Integration",
                marker=folium.CircleMarker(),
                style_function=lambda x: {
                    "fillColor": x["properties"]["color"],
                    "color": "#000000",
                    "weight": 1,
                    "radius": x["properties"]["radius"],
                    "fillOpacity": 0.9,
                },
                tooltip=folium.GeoJsonTooltip(
                    fields=["closeness"],
                    aliases=["Integration Score:"],
                    localize=True,
                ),
            ).add_to(m)

        # Golden Spots layer
        if st.session_state.show_golden_spots and net_data.get("golden_spots_geojson"):
            folium.GeoJson(
                net_data["golden_spots_geojson"],
                name="Golden Land Spots",
                marker=folium.CircleMarker(),
                style_function=lambda x: {
                    "fillColor": "#FFD60A",
                    "color": "#8C6A00",
                    "weight": 2,
                    "radius": max(5, 12 - x["properties"]["rank"]),
                    "fillOpacity": 0.85,
                },
                tooltip=folium.GeoJsonTooltip(
                    fields=["rank", "score"],
                    aliases=["Rank:", "Opportunity Score:"],
                    localize=True,
                ),
            ).add_to(m)

        # Top Node marker
        if net_data.get("top_node"):
            top = net_data["top_node"]
            folium.Marker(
                [top["lat"], top["lon"]],
                popup=f"🏆 Center (Score: {top['score']:.4f})",
                icon=folium.Icon(color="orange", icon="star", prefix="fa"),
                tooltip="จุดที่อยู่ตรงกลางที่สุด",
            ).add_to(m)

    # ---- Isochrone polygons ----
    iso_data = StateManager.get_isochrone_data()
    if iso_data:
        clrs = StateManager.get_colors()
        folium.GeoJson(
            iso_data,
            name="Travel Areas",
            style_function=lambda x: {
                "fillColor": get_fill_color(
                    x["properties"]["travel_time_minutes"], clrs
                ),
                "color": get_border_color(x["properties"]["original_index"]),
                "weight": 1,
                "fillOpacity": 0.2,
            },
        ).add_to(m)

    # ---- CBD intersection ----
    inter_data = StateManager.get_intersection_data()
    if inter_data:
        folium.GeoJson(
            inter_data,
            name="CBD Zone",
            style_function=lambda _x: {
                "fillColor": "#FFD700",
                "color": "#FF8C00",
                "weight": 3,
                "fillOpacity": 0.6,
                "dashArray": "5, 5",
            },
        ).add_to(m)

    # ---- WMS Layers ----
    _add_wms_layer(
        m, "thailand_population", "ความหนาแน่นประชากร",
        st.session_state.show_population,
    )
    _add_wms_layer(
        m, "cityplan_dpt", "ผังเมืองรวม",
        st.session_state.show_cityplan,
        opacity=st.session_state.cityplan_opacity,
    )
    _add_wms_layer(
        m, "dol", "รูปแปลงที่ดิน", st.session_state.show_dol
    )

    # ---- Railway KML Layer ----
    if st.session_state.show_railway:
        railway_geojson = _parse_kml_to_geojson()
        if railway_geojson and railway_geojson.get("features"):
            folium.GeoJson(
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
            ).add_to(m)

    # ---- Markers ----
    for i, marker in enumerate(markers):
        active = marker.get("active", True)
        popup_html = f"<b>จุดที่ {i+1}</b>"
        if rent_model and rent_anchor:
            d_km = haversine_km(
                rent_anchor["lat"], rent_anchor["lon"], marker["lat"], marker["lng"]
            )
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
        ).add_to(m)

    folium.LayerControl().add_to(m)
    _add_map_legend(m)

    # returned_objects จำกัดเฉพาะ last_clicked → เลื่อน/ซูมแผนที่ไม่ trigger
    # Streamlit rerun ทั้งหน้า (เร็วขึ้นมากบน Streamlit Cloud)
    return st_folium(
        m,
        height=900,
        use_container_width=True,
        key="main_map",
        returned_objects=["last_clicked"],
    )


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
            row["Value Gap"] = round(s.get("closeness_norm", 0.0) - rent_norm, 3)
        rows.append(row)
    return pd.DataFrame(rows)


def render_analytics_panel() -> None:
    """แท็บวิเคราะห์ใต้แผนที่: Bid-Rent Curve / Golden Spots / หมุด / หลักการ."""
    rent_data = StateManager.get_rent_data()
    net_data = StateManager.get_network_data()
    has_rent = bool(rent_data and "error" not in rent_data)
    golden_spots = (net_data or {}).get("golden_spots") if net_data else None
    locked = st.session_state.get(StateManager.K_UI_LOCKED, False)

    tab_curve, tab_gold, tab_marks, tab_theory = st.tabs(
        ["📈 Bid-Rent Curve", "💎 Golden Spots", "📍 หมุด & ราคาประเมิน", "📐 หลักการ"]
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
            fit_txt = (
                f" (fit จากตัวอย่าง {model['n_samples']} จุด, R² = {model['r2']:.3f})"
                if model.get("r2") is not None
                else " (โหมดดัชนี — ยังไม่ calibrate จากราคาจริง)"
            )
            st.caption(
                f"R(d) = {eq_r0} × e^(−{model['lam']:.4f}·d)"
                + fit_txt
            )
        else:
            st.info("กด **🧮 คำนวณ Rent Gradient** ใน sidebar เพื่อสร้างเส้นโค้ง Bid-Rent", icon="💡")

    with tab_gold:
        if golden_spots:
            df_gold = _build_golden_spots_df(golden_spots, rent_data)
            st.dataframe(df_gold, use_container_width=True, hide_index=True)
            if has_rent:
                st.caption(
                    "**Value Gap** = Closeness − (ค่าเช่าคาดการณ์/R₀) — "
                    "ค่าบวกมาก = เข้าถึงง่ายแต่ราคายังต่ำ (โอกาส 'ก่อนคนรู้')"
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
        cache_key = get_cache_key(polygon_wkt_str, network_type)
        is_cached = load_graph_from_cache(cache_key) is not None

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


def perform_rent_gradient(quiet: bool = False) -> None:
    """Orchestrate Rent Gradient computation (pure math — ไม่มี API call)."""
    iso_data = StateManager.get_isochrone_data()
    if not iso_data:
        if not quiet:
            st.error("❌ กรุณาคำนวณ Isochrone ก่อน เพื่อกำหนดขอบเขตพื้นที่")
        return

    data = compute_rent_gradient_data(
        StateManager.get_intersection_data(),
        StateManager.get_network_data(),
        iso_data,
        StateManager.get_markers(),
        StateManager.get_rent_samples(),
        StateManager.get_rent_unit(),
    )
    if "error" in data:
        StateManager.set_rent_data(None)
        if not quiet:
            st.error(f"❌ {data['error']}")
        return

    StateManager.set_rent_data(data)
    if not quiet:
        model = data["model"]
        mode = "โหมดดัชนี" if model["is_index"] else f"calibrated, R²={model['r2']:.3f}"
        st.toast(f"💰 Rent Gradient พร้อม ({mode}) λ={model['lam']:.4f}", icon="✅")


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

    # 1. Initialize State
    StateManager.initialize()

    # 2. Render Sidebar → capture user intents
    do_calc, do_net, do_rent, active_list = render_sidebar()

    # 3. Execute Business Logic (based on user intents)
    if do_calc:
        perform_calculation(active_list)

    if do_net:
        perform_network_analysis()

    if do_rent:
        perform_rent_gradient()

    # 4. Render Header + Metrics + Map + Analytics
    render_header()
    render_metrics_row()
    map_output = render_map()
    render_analytics_panel()

    # 5. Handle Map Click → mutate state & rerun
    handle_map_click(map_output, st.session_state[StateManager.K_UI_LOCKED])


if __name__ == "__main__":
    main()
