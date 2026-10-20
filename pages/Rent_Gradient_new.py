"""
Rent Gradient (new) — Network Analysis แบบ Space Syntax
=======================================================
หน้านี้แยกจาก ``Rent_Gradient.py`` (ไม่แก้ไฟล์เดิม) แทนที่ Network Analysis แบบ betweenness / สี plasma
ด้วย **Segment Analysis ตามหลัก Space Syntax** แล้วไล่สี Gradient ให้ "ทุกช่วงถนน" ตามคะแนนการเข้าถึง

    🔴 แดง = เข้าถึงง่ายที่สุด (คะแนนสูง)  →  🟡 เหลือง  →  🟢 เขียว  →  🔵 น้ำเงิน = เข้าถึงยากที่สุด

หลักการ (Hillier & Iida 2005 · Turner 2007 · Hillier, Yang & Turner 2012)
  • 1 segment = ช่วงถนนระหว่างสองแยก (edge ของ OSM ที่ simplify แล้ว) — ไม่สนใจทิศทางวันเวย์
  • ระยะระหว่าง segment วัดได้ 3 แบบ
        angular      ผลรวมมุมเลี้ยว (เลี้ยว 90° = 1.0, ตรง = 0)      ← มาตรฐานของ Segment Analysis
        topological  จำนวนก้าว (นับเมื่อเลี้ยวเกินมุมที่กำหนด)
        metric       ระยะตามถนนจริง จากกลาง segment ถึงกลาง segment (เมตร)
  • รัศมี r (Radius) วัดเป็นเมตรตามถนนเสมอ: 400 / 800 / 1,600 / 3,200 m หรือ Global (n) = ทั้งโครงข่าย
  • ต่อ segment ที่เป็นจุดเริ่ม (origin) นับ
        NC = จำนวน segment ในรัศมี (รวมตัวเอง),  TD = ผลรวม depth ไปทุก segment ในรัศมี
        Integration  NAIN = NC^1.2 / (TD + 2)          → "เข้าถึงได้ง่ายจากทุกที่" (to-movement)
        Choice       NACH = log(CH + 1) / log(TD + 3)   → "ต้องผ่านบ่อย" (through-movement)
    CH = จำนวนคู่ (origin → destination) ที่เส้นทางสั้นที่สุด (มุมน้อยที่สุด) ผ่าน segment นั้น
  • คะแนน 0–100 ที่ใช้ไล่สี = ตำแหน่งของค่า NAIN / NACH ระหว่างต่ำสุด–สูงสุด (หรือเปอร์เซ็นไทล์)

ข้อตกลงการคำนวณ (ตั้งใจให้เรียบง่าย ตรวจย้อนได้)
  • สถานะ = (segment, ทิศที่วิ่งผ่าน) ไม่มี U-turn → ระยะสมมาตร d(i, j) = d(j, i) และไม่มีเส้นทาง "ลัดผี"
  • ต้นทุนของการต่อ segment s → t ที่แยกเดียวกัน = มุมเลี้ยวที่แยก + ครึ่งหนึ่งของความโค้งภายใน s และ t
    (วัดจากกลาง segment ถึงกลาง segment จึงนับความโค้งของปลายทางทั้งสองข้างเพียงครึ่งเดียว)
  • รัศมีแบบ metric: เลือก segment ที่ห่างไม่เกิน r เมตรตามถนน แล้วหา depth บนโครงข่ายย่อยนั้น
  • Global ที่มี segment เกิน ``max_exact_segments`` ใช้ pivot sampling (Eppstein–Wang, seed คงที่)
  • การโหลดถนนใช้ตัวโหลดเดิมของ ``Rent_Gradient.py`` (disk cache + Overpass failover) ถ้า import ได้

การคำนวณทั้งหมดอยู่ใน Section 2–4 (ไม่เรียก ``st.*`` ทดสอบ offline ได้ใน tests/test_rent_gradient_new.py)
"""

from __future__ import annotations

import importlib.util
import io
import json
import sys
import time
import zipfile
from dataclasses import dataclass, field
from html import escape
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd
import streamlit as st
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import connected_components, dijkstra
from scipy.stats import rankdata
from shapely.geometry import LineString

ROOT = Path(__file__).resolve().parents[1]


# ============================================================================
# SECTION 1: CONSTANTS & CONFIGURATION
# ============================================================================

PAGE_CONFIG: Dict[str, Any] = {
    "page_title": "Rent Gradient — Space Syntax",
    "page_icon": "🧭",
    "layout": "wide",
}

# ค่าเริ่มต้นเดียวกับ Rent_Gradient.py (เชียงของ)
DEFAULT_LAT = 20.219443
DEFAULT_LON = 100.403630

NETWORK_TYPES: Dict[str, str] = {
    "drive": "🚗 ถนนรถ (drive)",
    "all": "🛣️ ทุกถนน (all)",
    "walk": "🚶 เดินเท้า (walk)",
    "bike": "🚲 จักรยาน (bike)",
}

# โหลดถนนเกินรัศมีที่แสดง 20% (ค่าเดียวกับ ANCHOR_CONFIG["buffer_ratio"] ของ Rent_Gradient.py)
# เพื่อลด edge effect: segment ริมขอบศึกษามีเพื่อนบ้านครบ จึงไม่ถูกลดคะแนนเพราะ "ขอบแผนที่"
STUDY_BUFFER_RATIO = 0.20
MIN_RADIUS_M, MAX_RADIUS_M = 1000, 10000

BUNDLED_CACHE_ZIP = ROOT / "Geoapify_Map" / "osmnx_cache.zip"
BASE_PAGE_MODULE = "rent_gradient_base_for_new"

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

VIEW_LABELS: Dict[str, str] = {
    "map": "🗺️ แผนที่",
    "png": "🖤 Segment map",
    "stats": "📊 สถิติ & อันดับ",
    "help": "📖 หลักการ",
}

SCALE_MODES: Dict[str, str] = {
    "linear": "Linear (ต่ำสุด–สูงสุด)",
    "quantile": "Quantile (ตามลำดับเปอร์เซ็นไทล์)",
}

MAP_STYLES: Dict[str, Dict[str, Optional[str]]] = {
    "พื้นดำ (เหมือน depthmap)": {"tiles": None, "attr": None},
    "Dark (CARTO)": {
        "tiles": "https://basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png",
        "attr": "&copy; OpenStreetMap contributors &copy; CARTO",
    },
    "Esri Light Gray": {
        "tiles": ("https://server.arcgisonline.com/ArcGIS/rest/services/"
                  "Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}"),
        "attr": "Tiles &copy; Esri",
    },
    "OpenStreetMap": {"tiles": "OpenStreetMap", "attr": None},
}

# session-state keys (prefix rgn_ กันชนกับหน้าอื่นที่ใช้ session เดียวกัน)
K_NET, K_META, K_RESULT = "rgn_net", "rgn_meta", "rgn_result"
K_AUTORUN = "rgn_autorun"


# ============================================================================
# SECTION 2: PURE FUNCTIONS — SEGMENT NETWORK (ไม่เรียก st.*)
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


def _node_sort_key(node: Any) -> Tuple[str, str]:
    """Type-aware ordering so segment ids never depend on graph insertion order."""
    return (type(node).__name__, str(node))


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


# ============================================================================
# SECTION 3: PURE FUNCTIONS — SPACE SYNTAX ANALYSIS (ไม่เรียก st.*)
# ============================================================================

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


# ============================================================================
# SECTION 4: PURE FUNCTIONS — GRADIENT, SCORES, RANKING, EXPORT (ไม่เรียก st.*)
# ============================================================================

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


# ============================================================================
# SECTION 5: DATA ACCESS (OSM graph via the Rent_Gradient.py loader)
# ============================================================================

def _base_page() -> Optional[Any]:
    """Load ``pages/Rent_Gradient.py`` read-only to reuse its disk cache + Overpass failover.

    Returns ``None`` when it cannot be imported; the page then falls back to plain osmnx.
    """
    if BASE_PAGE_MODULE in sys.modules:
        return sys.modules[BASE_PAGE_MODULE]
    path = ROOT / "pages" / "Rent_Gradient.py"
    try:
        spec = importlib.util.spec_from_file_location(BASE_PAGE_MODULE, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[BASE_PAGE_MODULE] = module
        spec.loader.exec_module(module)
        return module
    except Exception:
        sys.modules.pop(BASE_PAGE_MODULE, None)
        return None


def fetch_graph(lat: float, lon: float, radius_m: float, network_type: str
                ) -> Tuple[Optional[Any], str, Optional[str]]:
    """``(graph, source_label, error)`` for the study circle plus its 20 % buffer.

    Prefers the Rent_Gradient.py loader (same study polygon as its CBD-anchor search, so a graph
    already cached there is reused). Only if that page cannot be loaded or raises does it fall back
    to a plain osmnx download.
    """
    base = _base_page()
    reason = "import Rent_Gradient.py ไม่สำเร็จ"
    if base is not None:
        try:
            polygon = base.anchor_study_polygon(lat, lon, radius_m)
            graph, cached, error = base._fetch_osm_graph(polygon.wkt, network_type)
        except Exception as exc:
            reason = f"{type(exc).__name__}: {exc}"
        else:
            if graph is None:
                return None, "", error
            label = graph.graph.get("osm_source") or ("cache" if cached else "download")
            return graph, f"Rent_Gradient cache/failover ({label})", None
    try:
        import osmnx as ox

        graph = ox.graph_from_point((lat, lon), dist=radius_m * (1 + STUDY_BUFFER_RATIO),
                                    network_type=network_type, truncate_by_edge=True)
        return graph, f"osmnx โดยตรง ({reason})", None
    except Exception as exc:
        return None, "", f"โหลดโครงข่ายถนนไม่สำเร็จ: {type(exc).__name__}: {exc}"


def load_bundled_graph() -> Tuple[Optional[Any], str, Optional[str]]:
    """Largest road graph stored in ``Geoapify_Map/osmnx_cache.zip`` (Chiang Khong, works offline).

    Pickles are read through the allow-list unpickler of Rent_Gradient.py, never plain ``pickle``.
    """
    base = _base_page()
    if base is None:
        return None, "", "ใช้ตัวอย่างออฟไลน์ไม่ได้: import Rent_Gradient.py ไม่สำเร็จ"
    if not BUNDLED_CACHE_ZIP.exists():
        return None, "", f"ไม่พบไฟล์ {BUNDLED_CACHE_ZIP.name}"
    best: Optional[Any] = None
    size_limit = int(getattr(base, "MAX_CACHE_ENTRY_BYTES", 150 * 1024 * 1024))
    try:
        with zipfile.ZipFile(BUNDLED_CACHE_ZIP) as archive:
            for info in sorted(archive.infolist(), key=lambda i: i.filename):
                if not info.filename.endswith(".pkl") or info.file_size > size_limit:
                    continue
                try:
                    graph = base._load_graph_bytes(archive.read(info))
                except Exception:
                    continue
                if best is None or len(graph) > len(best):
                    best = graph
    except (zipfile.BadZipFile, OSError) as exc:
        return None, "", f"อ่าน {BUNDLED_CACHE_ZIP.name} ไม่ได้: {exc}"
    if best is None:
        return None, "", f"ไม่พบกราฟที่อ่านได้ใน {BUNDLED_CACHE_ZIP.name}"
    return best, f"ตัวอย่างเชียงของ ({BUNDLED_CACHE_ZIP.name})", None


def base_anchor() -> Optional[Dict[str, Any]]:
    """CBD anchor computed on the Rent_Gradient page in this session, if any (read-only)."""
    data = st.session_state.get("rent_gradient_data")
    anchor = data.get("anchor") if isinstance(data, dict) else None
    try:
        return {"lat": float(anchor["lat"]), "lon": float(anchor["lon"]),
                "source": str(anchor.get("source", "CBD anchor"))}
    except (TypeError, KeyError, ValueError):
        return None


# ============================================================================
# SECTION 6: RENDERING (Folium map · depthmap-style PNG · charts)
# ============================================================================

def legend_html(title: str, palette: str, low: str, high: str, note: str = "") -> str:
    """Gradient colour-bar legend (bottom-left of the Folium map)."""
    return (
        '<div style="position:fixed; bottom:42px; left:12px; z-index:9999; width:230px; '
        'background:rgba(255,255,255,0.93); border:1px solid rgba(11,11,11,0.10); border-radius:8px; '
        'padding:8px 10px; font-size:12px; color:#0b0b0b; box-shadow:0 1px 4px rgba(0,0,0,0.18); '
        'line-height:1.45; font-family:system-ui, -apple-system, sans-serif;">'
        f'<div style="font-weight:600; margin-bottom:4px;">{title}</div>'
        f'<div style="height:12px; border-radius:3px; background:{gradient_css(palette)};"></div>'
        '<div style="display:flex; justify-content:space-between; margin-top:2px;">'
        f'<span>🔵 {low}</span><span>{high} 🔴</span></div>'
        f'<div style="margin-top:3px; color:#555;">{note}</div></div>'
    )


def build_map(
    net: SegmentNetwork, geojson: Dict[str, Any], *, basemap: str, legend: str,
    study_circle: Optional[Tuple[float, float, float]] = None,
    top: Sequence[Dict[str, Any]] = (), anchor: Optional[Dict[str, Any]] = None,
) -> Any:
    """Folium map of the gradient-coloured segments (features carry ``color`` / ``weight``).

    Folium writes tooltip text into the page as HTML, and street names come from OpenStreetMap, so
    every free-text value (``label``, anchor source) is HTML-escaped here before it is embedded.
    """
    import folium
    from branca.element import MacroElement, Template
    from folium.plugins import Fullscreen, MousePosition

    style = MAP_STYLES[basemap]
    features = [
        {**f, "properties": {**f["properties"], "label": escape(str(f["properties"].get("label", "")))}}
        for f in geojson["features"]
    ]
    geojson = {**geojson, "features": features}
    if features:
        coords = np.concatenate([np.asarray(f["geometry"]["coordinates"]) for f in features])
        south, north = float(coords[:, 1].min()), float(coords[:, 1].max())
        west, east = float(coords[:, 0].min()), float(coords[:, 0].max())
    else:
        south, north, west, east = (net.origin[0],) * 2 + (net.origin[1],) * 2
    m = folium.Map(location=[(south + north) / 2, (west + east) / 2], zoom_start=14,
                   tiles=style["tiles"], attr=style["attr"], prefer_canvas=True, control_scale=True)
    if style["tiles"] is None:
        m.get_root().header.add_child(folium.Element(
            "<style>.leaflet-container{background:#000 !important;}</style>"))
    m.fit_bounds([[south, west], [north, east]])

    folium.GeoJson(
        geojson, name="Segments (ไล่สีตามคะแนน)",
        style_function=lambda f: {"color": f["properties"]["color"],
                                  "weight": f["properties"]["weight"], "opacity": 0.95},
        highlight_function=lambda f: {"weight": f["properties"]["weight"] + 3, "opacity": 1.0},
        tooltip=folium.GeoJsonTooltip(
            fields=["label", "score", "value", "nc"],
            aliases=["ถนน:", "คะแนน (0–100):", "ค่าดัชนี:", "segment ในรัศมี:"], localize=True, sticky=True),
    ).add_to(m)

    if study_circle is not None:
        lat, lon, radius = study_circle
        folium.Circle([lat, lon], radius=radius, color="#ffffff", weight=1, dash_array="6", fill=False,
                      tooltip="ขอบเขตที่แสดงผล").add_to(m)
    for row in top:
        folium.Marker(
            [row["lat"], row["lon"]],
            tooltip=f"#{row['rank']} · คะแนน {row['score']:.1f} · {escape(str(row['label']))}",
            icon=folium.DivIcon(html=(
                '<div style="width:22px;height:22px;line-height:20px;border-radius:50%;text-align:center;'
                'background:#fff;color:#b00020;border:2px solid #b00020;font:700 11px system-ui;">'
                f"{row['rank']}</div>"), icon_size=(22, 22), icon_anchor=(11, 11)),
        ).add_to(m)
    if anchor is not None:
        folium.Marker([anchor["lat"], anchor["lon"]], tooltip=f"จุดยึด CBD — {escape(str(anchor['source']))}",
                      icon=folium.Icon(color="darkblue", icon="building", prefix="fa")).add_to(m)

    Fullscreen(position="topleft").add_to(m)
    MousePosition(position="bottomright", separator=" , ", num_digits=5, prefix="พิกัด:").add_to(m)
    folium.LayerControl().add_to(m)
    macro = MacroElement()
    macro._template = Template("{% macro html(this, kwargs) %}" + legend + "{% endmacro %}")
    m.get_root().add_child(macro)
    return m


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


# ============================================================================
# SECTION 7: UI COMPONENTS (st.* allowed)
# ============================================================================

def _header() -> None:
    st.title("🧭 Rent Gradient — Network Analysis แบบ Space Syntax")
    st.caption(
        "ไล่สีทุกช่วงถนนตามคะแนนการเข้าถึง: 🔴 แดง = เข้าถึงง่ายที่สุด → 🔵 น้ำเงิน = เข้าถึงยากที่สุด · "
        "Integration (NAIN) / Choice (NACH) บน Angular Segment Analysis · "
        "หน้านี้แยกจาก Rent_Gradient.py")


def _store_network(net: SegmentNetwork, meta: Dict[str, Any]) -> None:
    st.session_state[K_NET] = net
    st.session_state[K_META] = meta
    st.session_state.pop(K_RESULT, None)
    st.session_state[K_AUTORUN] = True


def _sidebar_study_area() -> None:
    net = st.session_state.get(K_NET)
    with st.expander("🗺️ ขอบเขตศึกษา & โครงข่ายถนน", expanded=net is None):
        lat = st.number_input("Lat ศูนย์กลาง", value=float(st.session_state.get("anchor_lat", DEFAULT_LAT)),
                              format="%.6f", key="rgn_lat")
        lon = st.number_input("Lon ศูนย์กลาง", value=float(st.session_state.get("anchor_lon", DEFAULT_LON)),
                              format="%.6f", key="rgn_lon")
        radius = st.slider("รัศมีที่แสดงผล (m)", MIN_RADIUS_M, MAX_RADIUS_M, 3000, 250, key="rgn_radius",
                           help="คำนวณบนโครงข่ายที่กว้างกว่านี้ 20% แล้วแสดง/จัดอันดับเฉพาะในรัศมีนี้ "
                                "เพื่อลด edge effect")
        network_type = st.selectbox("ชนิดโครงข่าย", list(NETWORK_TYPES), key="rgn_network",
                                    format_func=lambda k: NETWORK_TYPES[k])
        if st.button("📥 โหลดโครงข่ายถนน (OSM)", width="stretch", key="rgn_load"):
            with st.spinner("กำลังโหลดโครงข่ายถนน… (ครั้งแรกที่ยังไม่มี cache อาจใช้เวลานาน)"):
                graph, source, error = fetch_graph(lat, lon, float(radius), network_type)
                if graph is None:
                    st.error(error or "โหลดไม่สำเร็จ")
                    return
                try:
                    built = build_segment_network(graph)
                except ValueError as exc:
                    st.error(str(exc))
                    return
            _store_network(built, {"source": source, "lat": lat, "lon": lon, "radius_m": float(radius),
                                   "network": network_type, "nodes": graph.number_of_nodes(),
                                   "edges": graph.number_of_edges()})
            st.rerun()
        if st.button("🧪 ตัวอย่างเชียงของ (ออฟไลน์)", width="stretch", key="rgn_demo",
                     help="ใช้กราฟถนนที่เก็บไว้ใน Geoapify_Map/osmnx_cache.zip "
                          "— ไม่ต้องดาวน์โหลดจาก Overpass"):
            with st.spinner("กำลังอ่านตัวอย่างจาก repo…"):
                graph, source, error = load_bundled_graph()
                if graph is None:
                    st.error(error or "โหลดไม่สำเร็จ")
                    return
                try:
                    built = build_segment_network(graph)
                except ValueError as exc:
                    st.error(str(exc))
                    return
            _store_network(built, {"source": source, "lat": built.origin[0], "lon": built.origin[1],
                                   "radius_m": None, "network": "drive", "nodes": graph.number_of_nodes(),
                                   "edges": graph.number_of_edges()})
            st.rerun()


def _sidebar_analysis() -> Dict[str, Any]:
    with st.expander("🧭 Space Syntax", expanded=True):
        kind = st.selectbox("ระยะที่ใช้วัด (depth)", list(DISTANCE_KINDS), key="rgn_kind",
                            format_func=lambda k: DISTANCE_KINDS[k]["label"],
                            help="\n\n".join(f"**{v['label']}** — {v['help']}"
                                              for v in DISTANCE_KINDS.values()))
        turn = 0.0
        if kind == "topological":
            turn = float(st.slider(
                "นับเป็น 1 ก้าวเมื่อเลี้ยวเกิน (°)", 0, 60, 0, 5, key="rgn_turn",
                help="0 = ทุกการเปลี่ยน segment นับ 1 ก้าว · 20–30° = ถนนที่แทบตรงนับเป็นเส้นเดียว"))
        labels = st.multiselect("รัศมีวิเคราะห์ (เมตรตามถนน)", list(RADIUS_OPTIONS), default=DEFAULT_RADII,
                                key="rgn_radii",
                                help="Local (400–1,600 m) = ย่านเดินถึง · Global (n) = ทั้งโครงข่าย")
        with_choice = st.checkbox("คำนวณ Choice (ทางผ่าน) ด้วย", value=True, key="rgn_choice",
                                  help="ใช้เวลาเพิ่มราว 1–2 เท่า — ปิดไว้ถ้าต้องการเฉพาะ Integration")
    radii = sorted((RADIUS_OPTIONS[label] for label in labels), key=lambda r: (r is None, r or 0.0))
    return {"kind": kind, "turn": turn, "radii": radii, "with_choice": bool(with_choice)}


def _sidebar_style() -> Dict[str, Any]:
    with st.expander("🎨 การแสดงผล", expanded=False):
        palette = st.selectbox("ชุดสี", list(PALETTES), key="rgn_palette")
        scale = st.radio("สเกลสี", list(SCALE_MODES), key="rgn_scale", format_func=lambda k: SCALE_MODES[k],
                         help="Quantile กระจายสีเท่ากันทุกช่วง เห็นความต่างในย่านที่ค่าใกล้กันชัดขึ้น")
        thick = st.checkbox("เส้นหนาตามคะแนน", value=True, key="rgn_thick")
        basemap = st.selectbox("พื้นหลังแผนที่", list(MAP_STYLES), key="rgn_basemap")
        top_n = st.slider("จำนวนจุดคะแนนสูงสุดที่แสดง", 0, 25, ANALYSIS_CONFIG["top_n"], key="rgn_topn")
    return {"palette": palette, "scale": scale, "thick": bool(thick), "basemap": basemap, "top_n": int(top_n)}


def _run_analysis(net: SegmentNetwork, params: Dict[str, Any]) -> None:
    if not params["radii"]:
        st.error("เลือกรัศมีอย่างน้อย 1 ค่า")
        return
    bar = st.progress(0.0, text="กำลังวิเคราะห์ Space Syntax…")
    try:
        result = analyse_network(
            net, kind=params["kind"], radii=params["radii"], with_choice=params["with_choice"],
            topological_turn_deg=params["turn"],
            progress=lambda frac, text: bar.progress(min(max(frac, 0.0), 1.0),
                                                     text=f"กำลังวิเคราะห์… {text}"))
    except Exception as exc:  # surfaces ValueError (size limits) and anything unexpected
        st.error(f"วิเคราะห์ไม่สำเร็จ: {type(exc).__name__}: {exc}")
        return
    finally:
        bar.empty()
    result.meta["params"] = dict(params)
    st.session_state[K_RESULT] = result


def _display_mask(net: SegmentNetwork, meta: Dict[str, Any]) -> np.ndarray:
    if meta.get("radius_m"):
        mask = segments_in_circle(net, meta["lat"], meta["lon"], float(meta["radius_m"]))
        if mask.sum() >= 2:
            return mask
    return np.ones(net.n_segments, dtype=bool)


def _summary_row(net: SegmentNetwork, meta: Dict[str, Any], mask: np.ndarray,
                 result: Optional[AnalysisResult]) -> None:
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Segment (แสดง / ทั้งหมด)", f"{int(mask.sum()):,} / {net.n_segments:,}")
    c2.metric("ความยาวถนนที่แสดง", f"{net.seg_len[mask].sum() / 1000:,.1f} km")
    c3.metric("แยก / จุดปลายถนน", f"{net.n_nodes:,}")
    c4.metric("เวลาคำนวณ", f"{result.meta['seconds']:.1f} s" if result else "—")
    st.caption(f"โครงข่าย: {meta['source']} · {NETWORK_TYPES.get(meta['network'], meta['network'])}")


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


def _render_results(net: SegmentNetwork, meta: Dict[str, Any], mask: np.ndarray, result: AnalysisResult,
                    style: Dict[str, Any]) -> None:
    measures = ["integration"] + (["choice"] if result.with_choice else [])
    keys = [radius_key(r) for r in result.radii]
    labels = {radius_key(r): radius_label(r) for r in result.radii}
    for widget_key, valid in (("rgn_measure", measures), ("rgn_view_radius", keys)):
        if st.session_state.get(widget_key, valid[0]) not in valid:   # a fresh analysis changed the options
            st.session_state.pop(widget_key, None)
    c1, c2, c3 = st.columns([1.3, 1, 1.6])
    measure = c1.radio("ตัวชี้วัด", measures, horizontal=True, key="rgn_measure",
                       format_func=lambda m: f"{MEASURES[m]['title']} — {MEASURES[m]['thai']}")
    default_key = "n" if "n" in keys else keys[-1]
    rkey = c2.selectbox("รัศมีที่แสดง", keys, index=keys.index(default_key), key="rgn_view_radius",
                        format_func=lambda k: labels[k])
    view = c3.radio("มุมมอง", list(VIEW_LABELS), horizontal=True, key="rgn_view",
                    format_func=VIEW_LABELS.get)
    st.caption(MEASURES[measure]["hint"])

    if view == "help":
        _render_help()
        return
    values = result.integration[rkey] if measure == "integration" else result.choice_norm[rkey]
    nc = result.nc[rkey]
    scaled = scale_scores(values, style["scale"], mask)
    index_name = "NAIN" if measure == "integration" else "NACH"
    palette = style["palette"]

    if view == "png":
        try:
            png = render_depthmap_png(net, scaled["t"], mask, palette, thick_by_score=style["thick"])
        except ValueError as exc:
            st.warning(str(exc))
            return
        st.image(png)
        st.download_button("⬇️ ดาวน์โหลดภาพ PNG", png, file_name=f"space_syntax_{measure}_{rkey}.png",
                           mime="image/png")
        st.caption(f"{MEASURES[measure]['title']} · รัศมี {labels[rkey]} · {int(mask.sum()):,} segment · "
                   "วาดเส้นคะแนนสูงทับเส้นคะแนนต่ำ")
        return

    top = _top_rows(net, scaled, values, nc, mask, style["top_n"]) if style["top_n"] else []
    if view == "map":
        low, high = scaled["ticks"][0][1], scaled["ticks"][-1][1]
        note = f"{SCALE_MODES[style['scale']]} · {labels[rkey]}"
        legend = legend_html(f"{MEASURES[measure]['title']} (คะแนน 0–100)", palette,
                             f"ต่ำ {low:.2f}", f"{high:.2f} สูง", note)
        geojson = segments_geojson(net, _display_columns(net, scaled, values, nc, palette, style["thick"]),
                                   mask, precision=5)
        circle = (meta["lat"], meta["lon"], meta["radius_m"]) if meta.get("radius_m") else None
        fmap = build_map(net, geojson, basemap=style["basemap"], legend=legend, study_circle=circle,
                         top=top, anchor=base_anchor())
        from streamlit_folium import st_folium

        st_folium(fmap, height=720, use_container_width=True, key="rgn_map", returned_objects=[])
        return

    # ---- stats & ranking ----
    s1, s2, s3, s4 = st.columns(4)
    shown = values[mask & np.isfinite(values)]
    s1.metric(f"{index_name} สูงสุด", f"{shown.max():.3f}")
    s2.metric(f"{index_name} มัธยฐาน", f"{np.median(shown):.3f}")
    s3.metric(f"{index_name} ต่ำสุด", f"{shown.min():.3f}")
    s4.metric("segment ที่ได้คะแนน ≥ 80", f"{int((scaled['score'][mask] >= 80).sum()):,}")
    anchor = base_anchor()
    if anchor is not None:
        snapped = net.to_xy(anchor["lon"], anchor["lat"])
        nearest = int(np.argmin(np.hypot(*(net.seg_mid_xy - snapped).T)))
        if np.isfinite(scaled["score"][nearest]):
            st.info(f"📍 จุดยึด CBD จากหน้า Rent_Gradient ({anchor['source']}) อยู่ใกล้ segment คะแนน "
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
    columns = {**_display_columns(net, scaled, values, nc, palette, style["thick"]),
               **result_columns(net, result)}
    geojson = json.dumps(segments_geojson(net, columns, mask), ensure_ascii=False)
    d2.download_button("⬇️ GeoJSON (พร้อมสี)", geojson, file_name="space_syntax_segments.geojson",
                       mime="application/geo+json")


# ============================================================================
# SECTION 8: MAIN EXECUTION
# ============================================================================

def main() -> None:
    st.set_page_config(**PAGE_CONFIG)
    _header()
    with st.sidebar:
        _sidebar_study_area()
        params = _sidebar_analysis()
        style = _sidebar_style()
        net = st.session_state.get(K_NET)
        run = st.button("🧮 วิเคราะห์ Space Syntax", type="primary", width="stretch", disabled=net is None,
                        key="rgn_run")

    net = st.session_state.get(K_NET)
    meta = st.session_state.get(K_META)
    if net is None:
        st.info("เริ่มจากแถบด้านข้าง: ① โหลดโครงข่ายถนน (หรือกด 🧪 ตัวอย่างเชียงของ) → "
                "② เลือกระยะ/รัศมี → ③ 🧮 วิเคราะห์ Space Syntax")
        return

    autorun = st.session_state.pop(K_AUTORUN, False)
    if run or autorun:
        _run_analysis(net, params)
    result = st.session_state.get(K_RESULT)
    mask = _display_mask(net, meta)
    _summary_row(net, meta, mask, result)
    if result is None:
        st.info("กด 🧮 วิเคราะห์ Space Syntax ที่แถบด้านข้างเพื่อคำนวณและไล่สี")
        return

    if result.meta.get("params") != params:
        st.warning("ตั้งค่า Space Syntax เปลี่ยนไปจากที่คำนวณไว้ — กด 🧮 วิเคราะห์ เพื่ออัปเดตผล")
    notes = [f"ระยะ: {DISTANCE_KINDS[result.kind]['label']}",
             "รัศมี: " + ", ".join(radius_label(r) for r in result.radii)]
    if result.meta["approximate_global"]:
        notes.append(f"⚡ Global ประมาณด้วย pivot {result.meta['pivots']:,} จุด (segment เกิน "
                     f"{result.meta['max_exact_segments']:,})")
    st.caption(" · ".join(notes))
    _render_results(net, meta, mask, result, style)


if __name__ == "__main__":
    main()
