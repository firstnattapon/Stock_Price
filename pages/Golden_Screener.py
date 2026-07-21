"""
Golden Screener — เครื่องมือสกรีนที่ดินยึดสมการมาตรฐานโลก
==========================================================
โซ่แกนกลาง:
  โครงข่าย (Hansen/Space Syntax) → ค่าเช่า (Bid-Rent) → มูลค่า (Cap Rate/Residual)
                                 → จังหวะเปลี่ยน (ΔCentrality = Land Value Capture)

Score(i) = Mask(i) × Σ_k w_k · z_k(i)
  S1 Integration : C(v) = (N−1)/Σ d_len          (Alonso 1964; Hillier 1996)
  S2 Flow        : edge betweenness รอบเซลล์      (Porta et al. 2009)
  S3 ΔCentrality : C(v|กราฟ+รถไฟ) − C(v|ปัจจุบัน)  (Debrezion 2007; Cervero & Kang 2011)
  S4 Access      : A_i = Σ_j e^(−β·d_ij)          (Hansen 1959; Huff 1963)
  S5 Value Gap   : (R̂(d)−ราคาจริง)/R̂(d) แบบ IDW   (Rosen 1974 hedonic residual)
  Mask           : ทับ buffer เวนคืน / หลุด LCC = 0 (non-compensatory MCDA — Malczewski 2004)

Value Translation (IVS/RICS):
  V̂(i) = R̂(d_i)·12 / cap_rate                    (Direct Capitalization)
  Residual Land Value = GDV − Cost − Fees − Finance − Profit

Architecture: Modular Monolith เดียวกับ Rent_Gradient.py
"""

import streamlit as st
import folium
from streamlit_folium import st_folium
import requests
import json
import hashlib
import pickle
import time
import xml.etree.ElementTree as ET
import pandas as pd
import networkx as nx
import osmnx as ox
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from math import radians, sin, cos, sqrt, atan2, log, exp

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
    "page_title": "Golden Screener — สกรีนที่ดินด้วยสมการมาตรฐานโลก",
    "page_icon": "🏆",
    "layout": "wide",
}

DEFAULT_CENTER: Tuple[float, float] = (20.219443, 100.403630)  # เชียงของ
GEOAPIFY_KEY: str = "4eefdfb0b0d349e595595b9c03a69e3d"

CACHE_DIR: Path = Path("./cache")
CACHE_DIR.mkdir(exist_ok=True)

KML_FILE_PATH: Path = (
    Path(__file__).resolve().parent
    / "เวนคืนรถไฟเด่นชัย - เชียงราย - เชียงของ ตอน 1-2.kml"
)
KML_NS: str = "{http://www.opengis.net/kml/2.2}"

SCREEN_CONFIG: Dict[str, Any] = {
    "radius_km": 2.5,           # รัศมีพื้นที่ศึกษา
    "cell_m": 180,              # ขนาดเซลล์กริด
    "closeness_exact_threshold": 3000,
    "closeness_k_pivots": 600,
    "betweenness_k_samples": 200,
    "large_graph_threshold": 1500,
    "rail_speed_factor": 4.0,   # รถไฟเร็วกว่าถนน → length หารด้วยค่านี้
    "station_spacing_km": 2.0,  # ระยะห่างสถานีจำลองบนแนวรถไฟ
    "hansen_beta": 0.8,         # ต่อ km
    "expro_buffer_m": 100,      # buffer แนวเวนคืน
    "cap_rate_pct": 6.0,
    "gap_idw_radius_km": 2.0,
    "cache_ttl_seconds": 3600,
    "top_n": 10,
    "weights": {  # default ตามแนว AHP — ผู้ใช้ปรับได้
        "s1_integration": 0.30,
        "s2_flow": 0.20,
        "s3_uplift": 0.25,
        "s4_access": 0.15,
        "s5_gap": 0.10,
    },
}

POI_CATEGORIES: str = (
    "education.school,commercial.marketplace,commercial.supermarket,"
    "healthcare.hospital,office.government"
)

SCORE_RAMP: List[str] = [
    "#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b",
]

FACTOR_LABELS: Dict[str, str] = {
    "s1_integration": "S1 Integration (ใกล้ทุกจุด)",
    "s2_flow": "S2 Flow (ศักยภาพค้าปลีก)",
    "s3_uplift": "S3 ΔCentrality (แรงยกจากรถไฟ)",
    "s4_access": "S4 Access (แรงดึงดูด POI)",
    "s5_gap": "S5 Value Gap (ส่วนลดจากโมเดล)",
}

TIMEOUT_API: int = 15


# ============================================================================
# SECTION 2: STATE MANAGER
# ============================================================================

class StateManager:
    K_CENTER: str = "gs_center"
    K_RESULT: str = "gs_result"
    K_SAMPLES: str = "gs_price_samples"

    _DEFAULTS: Dict[str, Any] = {
        K_CENTER: {"lat": DEFAULT_CENTER[0], "lon": DEFAULT_CENTER[1]},
        K_RESULT: None,
        K_SAMPLES: [],
    }

    @classmethod
    def initialize(cls) -> None:
        for key, value in cls._DEFAULTS.items():
            st.session_state.setdefault(key, value)

    @classmethod
    def get_center(cls) -> Dict[str, float]:
        return st.session_state[cls.K_CENTER]

    @classmethod
    def set_center(cls, lat: float, lon: float) -> None:
        st.session_state[cls.K_CENTER] = {"lat": lat, "lon": lon}

    @classmethod
    def get_result(cls) -> Optional[Dict[str, Any]]:
        return st.session_state[cls.K_RESULT]

    @classmethod
    def set_result(cls, data: Optional[Dict[str, Any]]) -> None:
        st.session_state[cls.K_RESULT] = data

    @classmethod
    def get_samples(cls) -> List[Dict[str, Any]]:
        return st.session_state[cls.K_SAMPLES]

    @classmethod
    def set_samples(cls, samples: List[Dict[str, Any]]) -> None:
        st.session_state[cls.K_SAMPLES] = samples


# ============================================================================
# SECTION 3: PURE FUNCTIONS
# ============================================================================

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


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    return calculate_distance_meters(lat1, lon1, lat2, lon2) / 1000.0


def compute_weighted_closeness(
    G_undir: nx.MultiGraph,
) -> Tuple[Dict[Any, float], str]:
    """
    Weighted closeness (Network 1-Median) — สำเนาจาก Rent_Gradient.py:
        C(v) = (N−1) / Σ_u d_len(v,u)  บน Largest Connected Component
    exact ด้วย scipy csgraph หรือ Eppstein–Wang pivot sampling เมื่อกราฟใหญ่
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

    if n <= SCREEN_CONFIG["closeness_exact_threshold"]:
        dist = csgraph_dijkstra(csr, directed=False)
        sums = dist.sum(axis=1)
        k_eff = n - 1
        method = "exact-scipy"
    else:
        k = min(SCREEN_CONFIG["closeness_k_pivots"], n)
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


# ----------------------------------------------------------- OSM graph cache
def _graph_cache_key(lat: float, lon: float, radius_km: float) -> str:
    key_str = f"point_{round(lat, 4)}_{round(lon, 4)}_{round(radius_km, 2)}_drive"
    return hashlib.md5(key_str.encode()).hexdigest()


def load_graph_from_cache(cache_key: str) -> Optional[nx.MultiDiGraph]:
    cache_file = CACHE_DIR / f"osm_graph_{cache_key}.pkl"
    if cache_file.exists():
        try:
            with open(cache_file, "rb") as f:
                return pickle.load(f)
        except Exception:
            return None
    return None


def save_graph_to_cache(cache_key: str, graph: nx.MultiDiGraph) -> None:
    cache_file = CACHE_DIR / f"osm_graph_{cache_key}.pkl"
    try:
        with open(cache_file, "wb") as f:
            pickle.dump(graph, f, protocol=pickle.HIGHEST_PROTOCOL)
    except Exception:
        pass


def fetch_road_graph(
    lat: float, lon: float, radius_km: float
) -> Tuple[Optional[nx.MultiDiGraph], Optional[str]]:
    """ดึงกราฟถนนรอบจุดศูนย์กลาง (disk-cached)."""
    try:
        key = _graph_cache_key(lat, lon, radius_km)
        G = load_graph_from_cache(key)
        if G is not None:
            return G, None
        G = ox.graph_from_point(
            (lat, lon), dist=int(radius_km * 1000),
            network_type="drive", truncate_by_edge=True,
        )
        save_graph_to_cache(key, G)
        return G, None
    except Exception as e:
        return None, f"ดึงกราฟถนนไม่สำเร็จ: {str(e)}"


# ------------------------------------------------------------------ KML rail
def parse_kml_rail_lines() -> List[List[List[float]]]:
    """อ่านแนวรถไฟจาก KML ใน repo → list ของ LineString coords [[lon, lat], ...]."""
    if not KML_FILE_PATH.exists():
        return []
    try:
        tree = ET.parse(str(KML_FILE_PATH))
        root = tree.getroot()
    except ET.ParseError:
        return []

    lines: List[List[List[float]]] = []
    for ls_el in root.iter(f"{KML_NS}LineString"):
        coord_el = ls_el.find(f"{KML_NS}coordinates")
        if coord_el is None or not coord_el.text:
            continue
        coords: List[List[float]] = []
        for token in coord_el.text.strip().split():
            parts = token.split(",")
            if len(parts) >= 2:
                try:
                    coords.append([float(parts[0]), float(parts[1])])
                except ValueError:
                    continue
        if len(coords) >= 2:
            lines.append(coords)
    return lines


def clip_lines_to_radius(
    lines: List[List[List[float]]],
    center_lat: float, center_lon: float, radius_km: float,
) -> List[List[List[float]]]:
    """เก็บเฉพาะช่วงของเส้นที่อยู่ในรัศมีพื้นที่ศึกษา (แตกเส้นเป็นท่อนต่อเนื่อง)."""
    clipped: List[List[List[float]]] = []
    for line in lines:
        current: List[List[float]] = []
        for lon, lat in line:
            if haversine_km(center_lat, center_lon, lat, lon) <= radius_km:
                current.append([lon, lat])
            else:
                if len(current) >= 2:
                    clipped.append(current)
                current = []
        if len(current) >= 2:
            clipped.append(current)
    return clipped


def resample_stations(
    line: List[List[float]], spacing_km: float
) -> List[List[float]]:
    """วางสถานีจำลองทุก spacing_km ตามแนวเส้น (รวมจุดหัว-ท้าย)."""
    stations: List[List[float]] = [line[0]]
    acc = 0.0
    for i in range(1, len(line)):
        lon0, lat0 = line[i - 1]
        lon1, lat1 = line[i]
        seg = haversine_km(lat0, lon0, lat1, lon1)
        acc += seg
        if acc >= spacing_km:
            stations.append([lon1, lat1])
            acc = 0.0
    if stations[-1] != line[-1]:
        stations.append(line[-1])
    return stations


def inject_future_rail(
    G: nx.MultiDiGraph,
    rail_lines: List[List[List[float]]],
    speed_factor: float,
    station_spacing_km: float,
) -> Tuple[nx.MultiDiGraph, int]:
    """
    ยัดแนวรถไฟเข้ากราฟถนนเป็นโครงข่ายอนาคต:
    - สถานีจำลองทุก station_spacing_km
    - edge รถไฟ length = ระยะจริง / speed_factor (เร็วกว่าถนน)
    - เชื่อมสถานี → โหนดถนนใกล้สุดด้วย access edge ระยะจริง
    Returns (กราฟใหม่, จำนวนสถานี)
    """
    G_future = G.copy()
    node_ids = list(G.nodes)
    if not node_ids or not rail_lines:
        return G_future, 0

    xs = [G.nodes[n]["x"] for n in node_ids]
    ys = [G.nodes[n]["y"] for n in node_ids]

    def nearest_road_node(lon: float, lat: float) -> Tuple[Any, float]:
        best_i, best_d = 0, float("inf")
        for i in range(len(node_ids)):
            d = calculate_distance_meters(lat, lon, ys[i], xs[i])
            if d < best_d:
                best_d, best_i = d, i
        return node_ids[best_i], best_d

    n_stations = 0
    for li, line in enumerate(rail_lines):
        stations = resample_stations(line, station_spacing_km)
        prev_id = None
        prev_pt = None
        for si, (lon, lat) in enumerate(stations):
            sid = f"rail_{li}_{si}"
            G_future.add_node(sid, x=lon, y=lat, is_station=True)
            n_stations += 1

            road_node, access_m = nearest_road_node(lon, lat)
            G_future.add_edge(sid, road_node, length=max(access_m, 1.0))
            G_future.add_edge(road_node, sid, length=max(access_m, 1.0))

            if prev_id is not None:
                seg_m = calculate_distance_meters(prev_pt[1], prev_pt[0], lat, lon)
                rail_len = max(seg_m / speed_factor, 1.0)
                G_future.add_edge(prev_id, sid, length=rail_len)
                G_future.add_edge(sid, prev_id, length=rail_len)
            prev_id, prev_pt = sid, (lon, lat)

    return G_future, n_stations


# ----------------------------------------------------------------- Grid & S*
def build_grid(
    center_lat: float, center_lon: float, radius_km: float, cell_m: float
) -> List[Dict[str, float]]:
    """กริดเซลล์สี่เหลี่ยมคลุมวงกลมรัศมี radius_km รอบจุดศูนย์กลาง."""
    cell_km = cell_m / 1000.0
    dlat = cell_km / 110.574
    dlon = cell_km / (111.320 * max(cos(radians(center_lat)), 1e-6))
    n_steps = int(radius_km / cell_km) + 1

    cells: List[Dict[str, float]] = []
    for iy in range(-n_steps, n_steps + 1):
        for ix in range(-n_steps, n_steps + 1):
            lat = center_lat + iy * dlat
            lon = center_lon + ix * dlon
            if haversine_km(center_lat, center_lon, lat, lon) <= radius_km:
                cells.append({
                    "lat": lat, "lon": lon,
                    "half_dlat": dlat / 2, "half_dlon": dlon / 2,
                })
    return cells


def node_flow_scores(
    G_undir: nx.MultiGraph,
    edge_betweenness: Dict[Tuple[Any, Any], float],
) -> Dict[Any, float]:
    """S2: betweenness ระดับโหนด = ค่าเฉลี่ย betweenness ของ edge ที่ติดโหนด."""
    sums: Dict[Any, float] = {}
    counts: Dict[Any, int] = {}
    max_bet = max(edge_betweenness.values()) if edge_betweenness else 1.0
    if max_bet <= 0:
        max_bet = 1.0
    for u, v in G_undir.edges():
        b = edge_betweenness.get(tuple(sorted((u, v))), 0.0) / max_bet
        for node in (u, v):
            sums[node] = sums.get(node, 0.0) + b
            counts[node] = counts.get(node, 0) + 1
            if u == v:
                break
    return {
        n: (sums[n] / counts[n]) if counts.get(n) else 0.0
        for n in G_undir.nodes
    }


def hansen_access(
    cell_lat: float, cell_lon: float,
    pois: List[Dict[str, float]], beta: float,
) -> float:
    """S4: Hansen accessibility A_i = Σ_j e^(−β·d_ij) (d เป็น km)."""
    total = 0.0
    for p in pois:
        d = haversine_km(cell_lat, cell_lon, p["lat"], p["lon"])
        total += exp(-beta * d)
    return total


def fit_rent_gradient_from_samples(
    samples: List[Dict[str, Any]],
    anchor_lat: float,
    anchor_lon: float,
) -> Optional[Dict[str, Any]]:
    """Fit R(d)=R₀·e^(−λd) log-linear OLS — สำเนาจาก Rent_Gradient.py."""
    pts: List[Tuple[float, float]] = []
    used: List[Dict[str, Any]] = []
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
        used.append({"lat": lat, "lon": lon, "rent": rent, "d": d})

    if len(pts) < 2:
        return None
    n = len(pts)
    mean_x = sum(p[0] for p in pts) / n
    mean_y = sum(p[1] for p in pts) / n
    sxx = sum((p[0] - mean_x) ** 2 for p in pts)
    if sxx <= 1e-12:
        return None
    sxy = sum((p[0] - mean_x) * (p[1] - mean_y) for p in pts)
    slope = sxy / sxx
    intercept = mean_y - slope * mean_x
    return {"r0": exp(intercept), "lam": -slope, "n": n, "used": used}


def value_gap_idw(
    cell_lat: float, cell_lon: float,
    fit: Optional[Dict[str, Any]],
    radius_km: float,
) -> float:
    """
    S5: hedonic residual แบบ IDW —
    gap ของตัวอย่าง = (R̂(d) − ราคาจริง)/R̂(d)  (บวก = ถูกกว่าโมเดล)
    เซลล์ได้ค่าเฉลี่ยถ่วง 1/d ของตัวอย่างในรัศมี
    """
    if not fit:
        return 0.0
    num, den = 0.0, 0.0
    for s in fit["used"]:
        pred = fit["r0"] * exp(-fit["lam"] * s["d"])
        if pred <= 0:
            continue
        gap = (pred - s["rent"]) / pred
        d = haversine_km(cell_lat, cell_lon, s["lat"], s["lon"])
        if d > radius_km:
            continue
        w = 1.0 / max(d, 0.05)
        num += w * gap
        den += w
    return (num / den) if den > 0 else 0.0


def point_to_lines_distance_m(
    lat: float, lon: float,
    lines_local: List[List[Tuple[float, float]]],
    center_lat: float, center_lon: float,
) -> float:
    """ระยะ (m) จากจุดถึงแนวเส้น — ใช้พิกัด local equirectangular รอบ center."""
    px = (lon - center_lon) * 111320.0 * cos(radians(center_lat))
    py = (lat - center_lat) * 110574.0
    best = float("inf")
    for line in lines_local:
        for i in range(1, len(line)):
            x0, y0 = line[i - 1]
            x1, y1 = line[i]
            dx, dy = x1 - x0, y1 - y0
            seg2 = dx * dx + dy * dy
            if seg2 <= 1e-9:
                t = 0.0
            else:
                t = max(0.0, min(1.0, ((px - x0) * dx + (py - y0) * dy) / seg2))
            cx, cy = x0 + t * dx, y0 + t * dy
            d = sqrt((px - cx) ** 2 + (py - cy) ** 2)
            if d < best:
                best = d
    return best


def lines_to_local(
    lines: List[List[List[float]]], center_lat: float, center_lon: float
) -> List[List[Tuple[float, float]]]:
    """แปลง [[lon,lat],...] → local metric coords รอบ center."""
    kx = 111320.0 * cos(radians(center_lat))
    ky = 110574.0
    return [
        [((lon - center_lon) * kx, (lat - center_lat) * ky) for lon, lat in line]
        for line in lines
    ]


def zscores(values: List[float]) -> List[float]:
    n = len(values)
    if n == 0:
        return []
    mean = sum(values) / n
    var = sum((v - mean) ** 2 for v in values) / n
    sd = sqrt(var)
    if sd <= 1e-12:
        return [0.0] * n
    return [(v - mean) / sd for v in values]


def score_cells(
    cells: List[Dict[str, float]],
    node_coords: List[Tuple[Any, float, float]],   # (node_id, lat, lon)
    closeness_now: Dict[Any, float],
    closeness_future: Optional[Dict[Any, float]],
    flow: Dict[Any, float],
    pois: List[Dict[str, float]],
    fit: Optional[Dict[str, Any]],
    rail_lines: List[List[List[float]]],
    center_lat: float, center_lon: float,
    weights: Dict[str, float],
    beta: float,
    expro_buffer_m: float,
    gap_radius_km: float,
) -> List[Dict[str, Any]]:
    """
    Pure engine: ให้คะแนนทุกเซลล์
    Score(i) = Mask(i) × Σ_k w_k·z_k(i) → normalize 0–100
    """
    if not cells or not node_coords:
        return []

    lines_local = lines_to_local(rail_lines, center_lat, center_lon)

    # nearest node ต่อเซลล์ (vectorized ถ้ามี numpy)
    if HAS_SCIPY:
        node_lat = np.array([c[1] for c in node_coords])
        node_lon = np.array([c[2] for c in node_coords])
        kx = 111.320 * cos(radians(center_lat))
        nx_ = (node_lon - center_lon) * kx
        ny_ = (node_lat - center_lat) * 110.574
        cell_lat_arr = np.array([c["lat"] for c in cells])
        cell_lon_arr = np.array([c["lon"] for c in cells])
        cx = (cell_lon_arr - center_lon) * kx
        cy = (cell_lat_arr - center_lat) * 110.574
        d2 = (cx[:, None] - nx_[None, :]) ** 2 + (cy[:, None] - ny_[None, :]) ** 2
        nearest_idx = d2.argmin(axis=1)
    else:
        nearest_idx = []
        for c in cells:
            best_i, best_d = 0, float("inf")
            for i, (_nid, nlat, nlon) in enumerate(node_coords):
                d = (c["lat"] - nlat) ** 2 + (c["lon"] - nlon) ** 2
                if d < best_d:
                    best_d, best_i = d, i
            nearest_idx.append(best_i)

    raw: List[Dict[str, Any]] = []
    for ci, cell in enumerate(cells):
        nid = node_coords[int(nearest_idx[ci])][0]
        c_now = closeness_now.get(nid, 0.0)
        s3 = 0.0
        if closeness_future is not None:
            s3 = closeness_future.get(nid, 0.0) - c_now

        in_expro = (
            bool(lines_local)
            and point_to_lines_distance_m(
                cell["lat"], cell["lon"], lines_local, center_lat, center_lon
            ) <= expro_buffer_m
        )
        mask = 0 if (c_now <= 0.0 or in_expro) else 1

        raw.append({
            **cell,
            "node_id": nid,
            "s1": c_now,
            "s2": flow.get(nid, 0.0),
            "s3": s3,
            "s4": hansen_access(cell["lat"], cell["lon"], pois, beta),
            "s5": value_gap_idw(cell["lat"], cell["lon"], fit, gap_radius_km),
            "mask": mask,
            "mask_reason": (
                "แนวเวนคืน" if in_expro else ("หลุดโครงข่ายหลัก" if c_now <= 0 else "")
            ),
        })

    # z-score จากเฉพาะเซลล์ที่ผ่าน mask เพื่อไม่ให้เซลล์ตกรอบบิดสถิติ
    alive = [r for r in raw if r["mask"] == 1]
    if not alive:
        for r in raw:
            r["composite"] = 0.0
        return raw

    factor_keys = ["s1", "s2", "s3", "s4", "s5"]
    weight_keys = ["s1_integration", "s2_flow", "s3_uplift", "s4_access", "s5_gap"]

    # ปัจจัยที่ไม่มีข้อมูล (ทุกค่าเท่ากัน/เป็นศูนย์) → ตัดออกและ normalize น้ำหนักใหม่
    active: List[Tuple[str, str]] = []
    for fk, wk in zip(factor_keys, weight_keys):
        vals = [r[fk] for r in alive]
        if max(vals) - min(vals) > 1e-12 and weights.get(wk, 0) > 0:
            active.append((fk, wk))
    w_total = sum(weights[wk] for _fk, wk in active) or 1.0

    z_by_factor: Dict[str, List[float]] = {
        fk: zscores([r[fk] for r in alive]) for fk, _wk in active
    }
    for i, r in enumerate(alive):
        r["composite_raw"] = sum(
            (weights[wk] / w_total) * z_by_factor[fk][i] for fk, wk in active
        )

    lo = min(r["composite_raw"] for r in alive)
    hi = max(r["composite_raw"] for r in alive)
    span = (hi - lo) or 1.0
    for r in raw:
        if r["mask"] == 1:
            r["composite"] = 100.0 * (r["composite_raw"] - lo) / span
        else:
            r["composite"] = 0.0
    return raw


def score_color(score_0_100: float) -> str:
    idx = int(round((score_0_100 / 100.0) * (len(SCORE_RAMP) - 1)))
    return SCORE_RAMP[max(0, min(idx, len(SCORE_RAMP) - 1))]


# ------------------------------------------------- Value translation (IVS)
def direct_cap_value(
    rent_monthly: float, cap_rate_pct: float
) -> Optional[float]:
    """Direct Capitalization: V = (ค่าเช่า/เดือน × 12) / cap rate."""
    if cap_rate_pct <= 0:
        return None
    return rent_monthly * 12.0 / (cap_rate_pct / 100.0)


def residual_land_value(
    gdv: float, build_cost: float,
    fees_pct: float, finance_pct: float, profit_pct: float,
) -> Dict[str, float]:
    """Land Residual (RICS): มูลค่าที่ดิน = GDV − ต้นทุน − ค่าธรรมเนียม − ดอกเบี้ย − กำไร."""
    fees = build_cost * fees_pct / 100.0
    finance = build_cost * finance_pct / 100.0
    profit = gdv * profit_pct / 100.0
    land = gdv - build_cost - fees - finance - profit
    return {
        "fees": fees, "finance": finance, "profit": profit,
        "residual_land_value": land,
    }


# ============================================================================
# SECTION 4: CACHED WRAPPERS
# ============================================================================

@st.cache_resource(show_spinner=False)
def fetch_road_graph_cached(
    lat: float, lon: float, radius_km: float
) -> Tuple[Optional[nx.MultiDiGraph], Optional[str]]:
    return fetch_road_graph(lat, lon, radius_km)


@st.cache_data(show_spinner=False)
def parse_kml_rail_lines_cached() -> List[List[List[float]]]:
    return parse_kml_rail_lines()


@st.cache_data(show_spinner=False, ttl=SCREEN_CONFIG["cache_ttl_seconds"])
def fetch_pois_cached(
    lat: float, lon: float, radius_km: float
) -> Tuple[List[Dict[str, float]], Optional[str]]:
    """Geoapify Places API → POI ในพื้นที่ (graceful degrade เมื่อล้ม)."""
    try:
        resp = requests.get(
            "https://api.geoapify.com/v2/places",
            params={
                "categories": POI_CATEGORIES,
                "filter": f"circle:{lon},{lat},{int(radius_km * 1000)}",
                "limit": 100,
                "apiKey": GEOAPIFY_KEY,
            },
            timeout=TIMEOUT_API,
        )
        if resp.status_code != 200:
            return [], f"Places API status {resp.status_code}"
        pois = []
        for f in resp.json().get("features", []):
            try:
                lon_p, lat_p = f["geometry"]["coordinates"][:2]
                pois.append({
                    "lat": float(lat_p), "lon": float(lon_p),
                    "name": f.get("properties", {}).get("name", "POI"),
                })
            except (KeyError, ValueError, TypeError):
                continue
        return pois, None
    except requests.RequestException as e:
        return [], f"Places API ล้มเหลว: {str(e)}"


# ============================================================================
# SECTION 5-6: UI + ORCHESTRATOR
# ============================================================================

def run_screening(
    use_future: bool,
    weights: Dict[str, float],
    radius_km: float,
    cell_m: float,
    beta: float,
    expro_buffer_m: float,
    use_pois: bool,
) -> Dict[str, Any]:
    """Orchestrator: ดึงข้อมูล → คำนวณทุกชั้น → ผลลัพธ์ JSON-serializable."""
    center = StateManager.get_center()
    lat0, lon0 = center["lat"], center["lon"]
    t_start = time.perf_counter()

    G, err = fetch_road_graph_cached(lat0, lon0, radius_km)
    if err or G is None or len(G.nodes) < 2:
        return {"error": err or "กราฟถนนไม่พอสำหรับวิเคราะห์"}

    G_undir = G.to_undirected()

    closeness_now, method_now = compute_weighted_closeness(G_undir)

    # S2: edge betweenness (sampled บนกราฟใหญ่ — seed คงที่)
    if len(G.nodes) > SCREEN_CONFIG["large_graph_threshold"]:
        k = min(SCREEN_CONFIG["betweenness_k_samples"], len(G.nodes))
        edge_bet = nx.edge_betweenness_centrality(
            G_undir, k=k, weight="length", seed=42
        )
    else:
        edge_bet = nx.edge_betweenness_centrality(G_undir, weight="length")
    flow = node_flow_scores(G_undir, edge_bet)

    # S3: โครงข่ายอนาคต
    rail_lines_all = parse_kml_rail_lines_cached()
    rail_lines = clip_lines_to_radius(rail_lines_all, lat0, lon0, radius_km * 1.2)
    closeness_future = None
    n_stations = 0
    if use_future and rail_lines:
        G_future, n_stations = inject_future_rail(
            G, rail_lines,
            SCREEN_CONFIG["rail_speed_factor"],
            SCREEN_CONFIG["station_spacing_km"],
        )
        closeness_future, _ = compute_weighted_closeness(G_future.to_undirected())

    # S4: POIs
    pois: List[Dict[str, float]] = []
    poi_err: Optional[str] = None
    if use_pois:
        pois, poi_err = fetch_pois_cached(lat0, lon0, radius_km)

    # S5: rent fit — anchor คือ Integration Center ปัจจุบัน
    top_node = max(closeness_now, key=closeness_now.get)
    anchor_lat = G.nodes[top_node]["y"]
    anchor_lon = G.nodes[top_node]["x"]
    fit = fit_rent_gradient_from_samples(
        StateManager.get_samples(), anchor_lat, anchor_lon
    )

    cells = build_grid(lat0, lon0, radius_km, cell_m)
    node_coords = [(n, G.nodes[n]["y"], G.nodes[n]["x"]) for n in G.nodes]
    scored = score_cells(
        cells, node_coords, closeness_now, closeness_future, flow,
        pois, fit, rail_lines, lat0, lon0, weights, beta,
        expro_buffer_m, SCREEN_CONFIG["gap_idw_radius_km"],
    )

    ranked = sorted(
        (r for r in scored if r["mask"] == 1),
        key=lambda r: r["composite"], reverse=True,
    )

    return {
        "cells": scored,
        "top": ranked[: SCREEN_CONFIG["top_n"]],
        "anchor": {"lat": anchor_lat, "lon": anchor_lon},
        "rail_lines": rail_lines,
        "pois": pois,
        "fit": (
            {"r0": fit["r0"], "lam": fit["lam"], "n": fit["n"]} if fit else None
        ),
        "stats": {
            "nodes": len(G.nodes),
            "cells": len(scored),
            "cells_alive": sum(1 for r in scored if r["mask"] == 1),
            "closeness_method": method_now,
            "future_used": closeness_future is not None,
            "n_stations": n_stations,
            "n_pois": len(pois),
            "poi_error": poi_err,
            "elapsed_s": round(time.perf_counter() - t_start, 2),
        },
    }


def render_sidebar() -> Dict[str, Any]:
    with st.sidebar:
        st.header("🏆 Golden Screener")
        st.caption(
            "สกรีนที่ดินด้วยโซ่สมการมาตรฐานโลก: "
            "โครงข่าย → ค่าเช่า → มูลค่า → จังหวะเปลี่ยน"
        )

        center = StateManager.get_center()
        col1, col2 = st.columns(2)
        with col1:
            lat_in = st.number_input("Lat", value=float(center["lat"]), format="%.6f")
        with col2:
            lon_in = st.number_input("Lon", value=float(center["lon"]), format="%.6f")
        if lat_in != center["lat"] or lon_in != center["lon"]:
            StateManager.set_center(lat_in, lon_in)

        radius_km = st.slider("รัศมีพื้นที่ศึกษา (km)", 1.0, 5.0, SCREEN_CONFIG["radius_km"], 0.5)
        cell_m = st.select_slider("ขนาดเซลล์กริด (m)", options=[120, 150, 180, 240, 300], value=SCREEN_CONFIG["cell_m"])

        st.markdown("---")
        st.markdown("**⚖️ น้ำหนักปัจจัย** *(แนว AHP — ระบบ normalize ให้)*")
        w = {}
        w["s1_integration"] = st.slider(FACTOR_LABELS["s1_integration"], 0.0, 1.0, SCREEN_CONFIG["weights"]["s1_integration"], 0.05)
        w["s2_flow"] = st.slider(FACTOR_LABELS["s2_flow"], 0.0, 1.0, SCREEN_CONFIG["weights"]["s2_flow"], 0.05)
        w["s3_uplift"] = st.slider(FACTOR_LABELS["s3_uplift"], 0.0, 1.0, SCREEN_CONFIG["weights"]["s3_uplift"], 0.05)
        w["s4_access"] = st.slider(FACTOR_LABELS["s4_access"], 0.0, 1.0, SCREEN_CONFIG["weights"]["s4_access"], 0.05)
        w["s5_gap"] = st.slider(FACTOR_LABELS["s5_gap"], 0.0, 1.0, SCREEN_CONFIG["weights"]["s5_gap"], 0.05)

        st.markdown("---")
        use_future = st.toggle(
            "🚄 จำลองโครงข่ายอนาคต (รถไฟเด่นชัย–เชียงของ)", value=True,
            help="Land Value Capture: เทียบ centrality ก่อน/หลังมีรถไฟ (Debrezion 2007; MTR model)",
        )
        use_pois = st.toggle("📍 ดึง POI จริง (Geoapify Places)", value=True)
        beta = st.slider("β ของ Hansen (ต่อ km)", 0.2, 2.0, SCREEN_CONFIG["hansen_beta"], 0.1)
        expro_buffer_m = st.slider("Buffer แนวเวนคืน (m)", 0, 400, SCREEN_CONFIG["expro_buffer_m"], 25)

        st.markdown("---")
        st.markdown("**💰 ตัวอย่างราคาจริง** *(สำหรับ S5 Value Gap — บาท/ตร.ว./เดือน)*")
        samples_df = pd.DataFrame(
            StateManager.get_samples() or [{"lat": None, "lon": None, "rent": None}]
        )
        edited = st.data_editor(
            samples_df, num_rows="dynamic", use_container_width=True,
            key="gs_samples_editor", hide_index=True,
        )
        cleaned = [
            {"lat": r["lat"], "lon": r["lon"], "rent": r["rent"]}
            for _i, r in edited.iterrows()
            if pd.notna(r.get("lat")) and pd.notna(r.get("lon")) and pd.notna(r.get("rent"))
        ]
        StateManager.set_samples(cleaned)

        st.markdown("---")
        cap_rate = st.number_input(
            "Cap Rate (%) — Direct Capitalization", 1.0, 20.0,
            SCREEN_CONFIG["cap_rate_pct"], 0.5,
            help="V = NOI/r — มาตรฐาน IVS/RICS แปลงค่าเช่าเป็นมูลค่า",
        )

        run = st.button("🚀 Run Screening", type="primary", use_container_width=True)

    return {
        "run": run, "weights": w, "radius_km": radius_km, "cell_m": float(cell_m),
        "use_future": use_future, "use_pois": use_pois, "beta": beta,
        "expro_buffer_m": float(expro_buffer_m), "cap_rate": cap_rate,
    }


def render_map(result: Dict[str, Any], cap_rate: float) -> None:
    center = StateManager.get_center()
    m = folium.Map(
        location=[center["lat"], center["lon"]],
        zoom_start=14,
        tiles=(
            "https://server.arcgisonline.com/ArcGIS/rest/services/"
            "Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}"
        ),
        attr="Tiles &copy; Esri",
    )

    # กริดคะแนน
    for r in result["cells"]:
        if r["mask"] == 0:
            continue
        bounds = [
            [r["lat"] - r["half_dlat"], r["lon"] - r["half_dlon"]],
            [r["lat"] + r["half_dlat"], r["lon"] + r["half_dlon"]],
        ]
        folium.Rectangle(
            bounds=bounds,
            color=None,
            fill=True,
            fill_color=score_color(r["composite"]),
            fill_opacity=0.35,
        ).add_to(m)

    # แนวรถไฟ
    for line in result["rail_lines"]:
        folium.PolyLine(
            [[lat, lon] for lon, lat in line],
            color="#d62828", weight=3, dash_array="8,6",
            tooltip="แนวรถไฟเด่นชัย–เชียงราย–เชียงของ (จาก KML เวนคืน)",
        ).add_to(m)

    # Anchor (Integration Center)
    folium.Marker(
        [result["anchor"]["lat"], result["anchor"]["lon"]],
        icon=folium.Icon(color="blue", icon="star"),
        tooltip="Integration Center (จุดกลางโครงข่ายปัจจุบัน)",
    ).add_to(m)

    # Top-N
    fit = result.get("fit")
    for rank, r in enumerate(result["top"], start=1):
        popup_lines = [f"<b>🏆 อันดับ {rank} — คะแนน {r['composite']:.1f}/100</b>"]
        popup_lines.append(f"S1 Integration: {r['s1']:.5f}")
        popup_lines.append(f"S2 Flow: {r['s2']:.4f}")
        popup_lines.append(f"S3 ΔCentrality: {r['s3']:+.6f}")
        popup_lines.append(f"S4 Hansen Access: {r['s4']:.2f}")
        popup_lines.append(f"S5 Value Gap: {r['s5']:+.1%}")
        if fit:
            anchor = result["anchor"]
            d = haversine_km(anchor["lat"], anchor["lon"], r["lat"], r["lon"])
            rent_hat = fit["r0"] * exp(-fit["lam"] * d)
            v_hat = direct_cap_value(rent_hat, cap_rate)
            popup_lines.append(
                f"R̂(d): {rent_hat:,.0f} บาท/ตร.ว./ด. → "
                f"V̂ = {v_hat:,.0f} บาท/ตร.ว. (cap {cap_rate:.1f}%)"
            )
        folium.Marker(
            [r["lat"], r["lon"]],
            icon=folium.DivIcon(html=(
                '<div style="background:#d62828;color:#fff;border-radius:50%;'
                'width:26px;height:26px;line-height:26px;text-align:center;'
                f'font-weight:bold;border:2px solid #fff;">{rank}</div>'
            )),
            popup=folium.Popup("<br>".join(popup_lines), max_width=320),
        ).add_to(m)

    st_folium(m, height=560, use_container_width=True, returned_objects=[])


def render_results_table(result: Dict[str, Any]) -> None:
    rows = []
    for rank, r in enumerate(result["top"], start=1):
        rows.append({
            "อันดับ": rank,
            "คะแนน": round(r["composite"], 1),
            "lat": round(r["lat"], 6),
            "lon": round(r["lon"], 6),
            "S1": round(r["s1"], 5),
            "S2": round(r["s2"], 4),
            "S3 ΔC": round(r["s3"], 6),
            "S4": round(r["s4"], 2),
            "S5 Gap": f"{r['s5']:+.1%}",
        })
    df = pd.DataFrame(rows)
    st.dataframe(df, use_container_width=True, hide_index=True)
    st.download_button(
        "⬇️ ดาวน์โหลด Top-10 (CSV)",
        df.to_csv(index=False).encode("utf-8-sig"),
        file_name="golden_screener_top10.csv",
        mime="text/csv",
    )


def render_research_expander() -> None:
    with st.expander("📚 งานวิจัย/มาตรฐานที่รองรับแต่ละชั้น"):
        st.markdown("""
| ชั้น | สมการ | ใช้จริงโดย |
|---|---|---|
| S1 Integration | `C(v) = (N−1)/Σ d_len` | Alonso 1964; Hillier 1996 (Space Syntax Ltd ใช้วางผังจริง); Chiaradia 2012 |
| S2 Flow | edge betweenness (weight = เมตร) | Porta et al. 2009 — ร้านค้าเกาะถนน betweenness สูง (Bologna/Barcelona) |
| S3 ΔCentrality | `ΔC = C(อนาคต) − C(ปัจจุบัน)` | Land Value Capture: Debrezion 2007 meta-analysis (+5–25% รอบสถานี); Cervero & Kang 2011; โมเดล Rail+Property ของ MTR ฮ่องกง |
| S4 Access | Hansen 1959: `A = Σ e^(−βd)` | UK DfT / World Bank ใช้ประเมินโครงการคมนาคม; Huff 1963 อยู่ใน Esri Business Analyst |
| S5 Value Gap | hedonic residual (Rosen 1974) | Zillow/ดัชนีราคาธนาคารกลางทั่วโลก |
| Mask | non-compensatory MCDA | Malczewski 2004; Hakimi 1964 (facility location) |
| Value | `V = NOI/r` (Direct Cap), Land Residual | มาตรฐานประเมิน IVS 105 / RICS Red Book |
| Real Options | `V_land = max(NPV วันนี้, มูลค่าการรอ)` | Titman 1985; Capozza & Helsley 1990 — อธิบาย premium ที่ดินเปล่าใกล้โครงสร้างพื้นฐานใหม่ |
""")


def render_residual_calculator() -> None:
    with st.expander("🏗️ Land Residual Calculator (สมการที่ developer ใช้ประมูลที่ดิน)"):
        st.latex(r"Land = GDV - Cost - Fees - Finance - Profit")
        c1, c2 = st.columns(2)
        with c1:
            gdv = st.number_input("GDV มูลค่าโครงการเมื่อเสร็จ (บาท)", value=10_000_000.0, step=500_000.0)
            build = st.number_input("ต้นทุนก่อสร้าง (บาท)", value=6_000_000.0, step=500_000.0)
        with c2:
            fees = st.number_input("ค่าธรรมเนียม/วิชาชีพ (% ของค่าก่อสร้าง)", value=8.0, step=1.0)
            finance = st.number_input("ต้นทุนการเงิน (% ของค่าก่อสร้าง)", value=6.0, step=1.0)
        profit = st.slider("กำไร developer (% ของ GDV)", 5.0, 30.0, 15.0, 1.0)
        res = residual_land_value(gdv, build, fees, finance, profit)
        land = res["residual_land_value"]
        if land > 0:
            st.success(f"💰 เพดานราคาที่ดินที่ควรจ่าย ≈ **{land:,.0f} บาท**")
        else:
            st.error(f"โครงการนี้จ่ายค่าที่ดินไม่ได้ (residual = {land:,.0f} บาท) — GDV ต่ำไปหรือต้นทุนสูงไป")


def main() -> None:
    st.set_page_config(**PAGE_CONFIG)
    StateManager.initialize()

    st.title("🏆 Golden Screener — สกรีนที่ดินด้วยสมการมาตรฐานโลก")
    st.caption(
        "Score(i) = Mask(i) × Σ wₖ·zₖ(i) · "
        "โครงข่าย → ค่าเช่า → มูลค่า → จังหวะเปลี่ยน (Land Value Capture)"
    )

    controls = render_sidebar()

    if controls["run"]:
        with st.spinner("กำลังคำนวณทุกชั้น (โครงข่าย × 2, POI, กริด)…"):
            result = run_screening(
                controls["use_future"], controls["weights"],
                controls["radius_km"], controls["cell_m"],
                controls["beta"], controls["expro_buffer_m"],
                controls["use_pois"],
            )
        StateManager.set_result(result)

    result = StateManager.get_result()
    if result is None:
        st.info("ตั้งค่าใน sidebar แล้วกด **🚀 Run Screening** — ครั้งแรกอาจใช้เวลาดึงกราฟถนนจาก OSM")
    elif result.get("error"):
        st.error(result["error"])
    else:
        stats = result["stats"]
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("โหนดถนน", f"{stats['nodes']:,}")
        c2.metric("เซลล์ผ่าน Mask", f"{stats['cells_alive']:,}/{stats['cells']:,}")
        c3.metric("สถานีจำลอง", stats["n_stations"])
        c4.metric("POI", stats["n_pois"])
        c5.metric("เวลา", f"{stats['elapsed_s']}s")
        st.caption(
            f"Closeness: `{stats['closeness_method']}` · "
            f"โครงข่ายอนาคต: {'✅' if stats['future_used'] else '—'} · "
            + (f"⚠️ {stats['poi_error']} (ข้าม S4)" if stats.get("poi_error") else "")
        )

        render_map(result, controls["cap_rate"])
        st.subheader("🎯 Top-10 เซลล์ทองคำ")
        render_results_table(result)

    render_residual_calculator()
    render_research_expander()

    st.warning(
        "⚠️ เครื่องมือ**คัดกรอง**เท่านั้น ไม่ใช่คำแนะนำการลงทุน — "
        "ก่อนตัดสินใจต้องตรวจสีผังเมือง เอกสารสิทธิ์ แนวเวนคืนทางการ "
        "น้ำท่วม และสภาพหน้างานจริงเสมอ",
        icon="⚠️",
    )


main()
