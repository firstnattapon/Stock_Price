"""Core — geometry helpers: distances, geodesic circles, the CBD intersection, travel-time colours, click debounce.

Definitions are cut verbatim from pages/Rent_Gradient.py (see tests/test_rg_v2_equivalence.py).
"""


import time
from math import atan2, cos, pi, radians, sin, sqrt
from pyproj import CRS, Transformer
from shapely.geometry import mapping, shape
from typing import Any, Dict, List, Optional

from .config import ANCHOR_CONFIG, HEX_COLORS, NETWORK_CONFIG


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


def approx_geom_area_km2(geojson_geom: Dict[str, Any]) -> Optional[float]:
    """พื้นที่โดยประมาณ (km²) ของ geometry ใน WGS84 — แม่นพอสำหรับแสดงผล."""
    try:
        geom = shape(geojson_geom)
        lat_c = geom.centroid.y
        return geom.area * 110.574 * 111.320 * cos(radians(lat_c))
    except Exception:
        return None


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Haversine distance in kilometres."""
    return calculate_distance_meters(lat1, lon1, lat2, lon2) / 1000.0


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
