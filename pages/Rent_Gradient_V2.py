import streamlit as st
import folium
from streamlit_folium import st_folium
import requests
from shapely.geometry import shape, mapping, Point
from shapely.ops import unary_union
from shapely import wkt
import json
import networkx as nx
import osmnx as ox
import matplotlib.cm as cm
import matplotlib.colors as colors
from typing import List, Dict, Any, Optional, Tuple
import time
import hashlib
import pickle
import os
from pathlib import Path
import zipfile
import io
from math import radians, sin, cos, sqrt, atan2
import pandas as pd

# ============================================================================
# 1. CONSTANTS & CONFIGURATION
# ============================================================================

PAGE_CONFIG = {
    "page_title": "CBD NOOD Grading System — Geoapify + OSMnx",
    "page_icon": "🏢",
    "layout": "wide"
}

DEFAULT_CONFIG = {
    "JSON_URL": "https://raw.githubusercontent.com/firstnattapon/Stock_Price/refs/heads/main/Geoapify_Map/geoapify_cbd_project.json",
    "LAT": 20.219443,
    "LON": 100.403630,
    "GEOAPIFY_KEY": "4eefdfb0b0d349e595595b9c03a69e3d",
    "LONGDO_KEY": "0a999afb0da60c5c45d010e9c171ffc8"
}

LONGDO_WMS_URL = f"https://ms.longdo.com/mapproxy/service?key={DEFAULT_CONFIG['LONGDO_KEY']}"

MARKER_COLORS = ['red', 'blue', 'green', 'purple', 'orange', 'black', 'pink', 'cadetblue']
HEX_COLORS = ['#D63E2A', '#38AADD', '#72B026', '#D252B9', '#F69730', '#333333', '#FF91EA', '#436978']

MAP_STYLES = {
    "Esri Light Gray (แนะนำสำหรับดูผังเมือง)": {
        "tiles": "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}",
        "attr": "Tiles &copy; Esri"
    },
    "Google Maps (ผสม/Hybrid)": {
        "tiles": "https://mt1.google.com/vt/lyrs=y&x={x}&y={y}&z={z}",
        "attr": "Google Maps"
    },
    "OpenStreetMap (มาตรฐาน)": {"tiles": "OpenStreetMap", "attr": None},
    "Esri Satellite (ดาวเทียมชัด)": {
        "tiles": "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        "attr": "Tiles &copy; Esri"
    }
}

TRAVEL_MODE_NAMES = {
    "drive": "🚗 ขับรถ",
    "walk": "🚶 เดินเท้า",
    "bicycle": "🚲 ปั่นจักรยาน",
    "transit": "🚌 ขนส่งสาธารณะ"
}

TIME_OPTIONS = [5, 10, 15, 20, 30, 45, 60]

CACHE_DIR = Path("./cache")
CACHE_DIR.mkdir(exist_ok=True)

NETWORK_CONFIG = {
    'min_closeness_threshold': 0.0,
    'edge_weight_base': 2,
    'edge_weight_multiplier': 4,
    'cache_ttl_seconds': 3600,
    'click_debounce_seconds': 0.5,
    'click_distance_threshold_meters': 10,
    'large_graph_threshold': 2000,
}

TIMEOUT_API = 15
TIMEOUT_INIT = 3
TIMEOUT_GITHUB_LIST = 10
TIMEOUT_GITHUB_DOWNLOAD = 60

TRAVEL_MODE_TO_NETWORK_TYPE = {
    'drive': 'drive',
    'walk': 'walk',
    'bicycle': 'bike',
    'transit': 'drive',
}

SESSION_KEYS_TO_SAVE = [
    'api_key', 'map_style_name', 'travel_mode', 'time_intervals',
    'show_dol', 'show_cityplan', 'cityplan_opacity', 'show_population',
    'show_traffic', 'colors', 'show_betweenness', 'show_closeness'
]

# ============================================================================
# NOOD GRADING SYSTEM CONFIGURATION
# ============================================================================

NOOD_GRADES = {
    "A+": {
        "label": "A+ (Premium Core)",
        "color": "#FFD700",
        "fill_color": "#FFD700",
        "fill_opacity": 0.45,
        "description": "พื้นที่ Core ที่สุด — เดิน 5 นาทีถึงทุกจุด + Network Hub",
        "min_occupancy": 85,
        "emoji": "👑"
    },
    "A": {
        "label": "A (Prime CBD)",
        "color": "#FF8C00",
        "fill_color": "#FF8C00",
        "fill_opacity": 0.35,
        "description": "CBD หลัก — 5 นาทีถึงทุกจุด, Occupancy 80%+",
        "min_occupancy": 80,
        "emoji": "🏆"
    },
    "B+": {
        "label": "B+ (Strong Secondary)",
        "color": "#2196F3",
        "fill_color": "#2196F3",
        "fill_opacity": 0.28,
        "description": "รอง CBD — 10 นาที + ถนนหลัก (High Betweenness)",
        "min_occupancy": 75,
        "emoji": "🔵"
    },
    "B": {
        "label": "B (Secondary Zone)",
        "color": "#4CAF50",
        "fill_color": "#4CAF50",
        "fill_opacity": 0.22,
        "description": "พื้นที่รอง — 10 นาทีถึงทุกจุด, Occupancy 70%+",
        "min_occupancy": 70,
        "emoji": "🟢"
    },
    "C": {
        "label": "C (Emerging)",
        "color": "#9C27B0",
        "fill_color": "#9C27B0",
        "fill_opacity": 0.15,
        "description": "พื้นที่กำลังพัฒนา — 20 นาที, Occupancy 60%+",
        "min_occupancy": 60,
        "emoji": "🟣"
    },
    "D": {
        "label": "D (Peripheral / Land Bank)",
        "color": "#757575",
        "fill_color": "#757575",
        "fill_opacity": 0.10,
        "description": "พื้นที่รอบนอก — > 20 นาที หรือ Occupancy < 60%",
        "min_occupancy": 0,
        "emoji": "⚪"
    }
}

# NOOD Score weights
NOOD_WEIGHTS = {
    'travel_time': 0.40,
    'occupancy': 0.25,
    'network_centrality': 0.20,
    'population_density': 0.15
}

# ============================================================================
# 2. HELPER FUNCTIONS
# ============================================================================

def get_fill_color(minutes: float, colors_config: Dict[str, str]) -> str:
    if minutes <= 10: return colors_config['step1']
    if minutes <= 20: return colors_config['step2']
    if minutes <= 30: return colors_config['step3']
    return colors_config['step4']

def get_border_color(original_marker_idx: Optional[int]) -> str:
    if original_marker_idx is None: return '#3388ff'
    return HEX_COLORS[original_marker_idx % len(HEX_COLORS)]

def calculate_distance_meters(lat1, lon1, lat2, lon2):
    R = 6371000
    lat1_rad, lon1_rad = radians(lat1), radians(lon1)
    lat2_rad, lon2_rad = radians(lat2), radians(lon2)
    dlat = lat2_rad - lat1_rad
    dlon = lon2_rad - lon1_rad
    a = sin(dlat/2)**2 + cos(lat1_rad) * cos(lat2_rad) * sin(dlon/2)**2
    c = 2 * atan2(sqrt(a), sqrt(1-a))
    return R * c

def should_add_marker(new_lat, new_lon):
    last_click = st.session_state.get('last_processed_click')
    if last_click is None:
        return True
    time_diff = time.time() - last_click['timestamp']
    if time_diff < NETWORK_CONFIG['click_debounce_seconds']:
        return False
    distance = calculate_distance_meters(last_click['lat'], last_click['lon'], new_lat, new_lon)
    if distance < NETWORK_CONFIG['click_distance_threshold_meters']:
        return False
    return True

def calculate_intersection(features, num_active_markers):
    if num_active_markers < 2: return None
    polys_per_active_idx = {}
    for feat in features:
        active_idx = feat['properties']['active_index']
        geom = shape(feat['geometry'])
        polys_per_active_idx[active_idx] = polys_per_active_idx.get(active_idx, geom).union(geom)
    if len(polys_per_active_idx) < num_active_markers: return None
    active_indices = sorted(polys_per_active_idx.keys())
    try:
        intersection_poly = polys_per_active_idx[active_indices[0]]
        for idx in active_indices[1:]:
            intersection_poly = intersection_poly.intersection(polys_per_active_idx[idx])
            if intersection_poly.is_empty: return None
        return mapping(intersection_poly) if not intersection_poly.is_empty else None
    except Exception:
        return None

# ============================================================================
# NOOD GRADING FUNCTIONS
# ============================================================================

def calculate_nood_zones(features: List[Dict], num_active_markers: int) -> Dict[str, Any]:
    """
    คำนวณ NOOD Zones แบ่งตาม Grade จาก isochrone data.
    
    Logic:
    - Grade A: Intersection ของ isochrone 5 นาที (ทุกจุดถึงภายใน 5 นาที)
    - Grade B: Intersection ของ isochrone 10 นาที (ลบพื้นที่ Grade A ออก)
    - Grade C: Intersection ของ isochrone 20 นาที (ลบพื้นที่ Grade A+B ออก)
    - Grade D: พื้นที่ที่เหลือ
    """
    if num_active_markers < 1:
        return {}
    
    # Group polygons by time range and active index
    polys_by_time_and_idx = {}
    
    for feat in features:
        props = feat['properties']
        minutes = props.get('travel_time_minutes', 0)
        active_idx = props.get('active_index', 0)
        geom = shape(feat['geometry'])
        
        # Classify into time buckets
        if minutes <= 5:
            time_bucket = 5
        elif minutes <= 10:
            time_bucket = 10
        elif minutes <= 20:
            time_bucket = 20
        else:
            time_bucket = 999
        
        key = (time_bucket, active_idx)
        if key not in polys_by_time_and_idx:
            polys_by_time_and_idx[key] = geom
        else:
            polys_by_time_and_idx[key] = polys_by_time_and_idx[key].union(geom)
    
    # Calculate intersections for each time bucket
    zones = {}
    
    for time_bucket in [5, 10, 20, 999]:
        # Get all active indices that have this time bucket
        bucket_polys = {}
        for (tb, aidx), poly in polys_by_time_and_idx.items():
            if tb <= time_bucket:
                if aidx not in bucket_polys:
                    bucket_polys[aidx] = poly
                else:
                    bucket_polys[aidx] = bucket_polys[aidx].union(poly)
        
        if len(bucket_polys) < num_active_markers:
            continue
        
        # Calculate intersection across all active markers
        active_indices = sorted(bucket_polys.keys())
        try:
            intersection = bucket_polys[active_indices[0]]
            for idx in active_indices[1:]:
                intersection = intersection.intersection(bucket_polys[idx])
                if intersection.is_empty:
                    break
            
            if not intersection.is_empty:
                zones[time_bucket] = intersection
        except Exception:
            continue
    
    # For single marker, use direct polygons (no intersection needed)
    if num_active_markers == 1:
        single_polys = {}
        for feat in features:
            minutes = feat['properties'].get('travel_time_minutes', 0)
            geom = shape(feat['geometry'])
            
            if minutes <= 5:
                tb = 5
            elif minutes <= 10:
                tb = 10
            elif minutes <= 20:
                tb = 20
            else:
                tb = 999
            
            if tb not in single_polys:
                single_polys[tb] = geom
            else:
                single_polys[tb] = single_polys[tb].union(geom)
        
        # Accumulate: 10 min zone includes 5 min zone
        accumulated = {}
        running = None
        for tb in sorted(single_polys.keys()):
            if running is None:
                running = single_polys[tb]
            else:
                running = running.union(single_polys[tb])
            accumulated[tb] = running
        zones = accumulated
    
    # Create NOOD grade zones by subtracting inner zones from outer
    nood_zones = {}
    
    # Grade A: 5 minute zone
    if 5 in zones and not zones[5].is_empty:
        nood_zones['A'] = {
            'geometry': mapping(zones[5]),
            'area_sqkm': zones[5].area * 111 * 111,  # rough conversion
            'grade_info': NOOD_GRADES['A']
        }
    
    # Grade B: 10 min zone minus 5 min zone
    if 10 in zones and not zones[10].is_empty:
        zone_b = zones[10]
        if 5 in zones:
            try:
                zone_b = zones[10].difference(zones[5])
            except:
                pass
        if not zone_b.is_empty:
            nood_zones['B'] = {
                'geometry': mapping(zone_b),
                'area_sqkm': zone_b.area * 111 * 111,
                'grade_info': NOOD_GRADES['B']
            }
    
    # Grade C: 20 min zone minus 10 min zone
    if 20 in zones and not zones[20].is_empty:
        zone_c = zones[20]
        if 10 in zones:
            try:
                zone_c = zones[20].difference(zones[10])
            except:
                pass
        if not zone_c.is_empty:
            nood_zones['C'] = {
                'geometry': mapping(zone_c),
                'area_sqkm': zone_c.area * 111 * 111,
                'grade_info': NOOD_GRADES['C']
            }
    
    # Grade D: 30+ min zone minus 20 min zone
    if 999 in zones and not zones[999].is_empty:
        zone_d = zones[999]
        if 20 in zones:
            try:
                zone_d = zones[999].difference(zones[20])
            except:
                pass
        if not zone_d.is_empty:
            nood_zones['D'] = {
                'geometry': mapping(zone_d),
                'area_sqkm': zone_d.area * 111 * 111,
                'grade_info': NOOD_GRADES['D']
            }
    
    return nood_zones

def calculate_nood_score(
    travel_time_score: float,
    occupancy_score: float = 0.75,
    network_centrality_score: float = 0.5,
    population_density_score: float = 0.5
) -> float:
    """
    Calculate composite NOOD Score (0-100).
    
    NOOD Score = (0.40 × Travel Time Score)
               + (0.25 × Occupancy Score)
               + (0.20 × Network Centrality Score)
               + (0.15 × Population Density Score)
    """
    score = (
        NOOD_WEIGHTS['travel_time'] * travel_time_score +
        NOOD_WEIGHTS['occupancy'] * occupancy_score +
        NOOD_WEIGHTS['network_centrality'] * network_centrality_score +
        NOOD_WEIGHTS['population_density'] * population_density_score
    )
    return round(score * 100, 1)

def get_travel_time_score(minutes: float) -> float:
    """Convert travel time in minutes to a 0-1 score (lower time = higher score)."""
    if minutes <= 5: return 1.0
    if minutes <= 10: return 0.8
    if minutes <= 15: return 0.6
    if minutes <= 20: return 0.4
    if minutes <= 30: return 0.2
    return 0.1

def determine_grade_from_score(nood_score: float) -> str:
    """Determine letter grade from composite NOOD score."""
    if nood_score >= 85: return "A+"
    if nood_score >= 75: return "A"
    if nood_score >= 65: return "B+"
    if nood_score >= 55: return "B"
    if nood_score >= 40: return "C"
    return "D"

# ============================================================================
# API & CACHING FUNCTIONS
# ============================================================================

def safe_fetch_isochrone(api_key, travel_mode, ranges_str, marker_lat, marker_lon):
    url = "https://api.geoapify.com/v1/isoline"
    params = {
        "lat": marker_lat, "lon": marker_lon,
        "type": "time", "mode": travel_mode,
        "range": ranges_str, "apiKey": api_key
    }
    try:
        response = requests.get(url, params=params, timeout=TIMEOUT_API)
        if response.status_code == 200:
            data = response.json()
            features = data.get('features')
            if features is None:
                return None, "API response missing 'features' data"
            return features, None
        elif response.status_code == 401:
            return None, "❌ Invalid API Key"
        elif response.status_code == 429:
            return None, "⚠️ Rate Limit Exceeded"
        else:
            return None, f"API Error (Status {response.status_code})"
    except requests.Timeout:
        return None, "⏱️ Request Timeout"
    except requests.ConnectionError:
        return None, "🌐 Connection Error"
    except Exception as e:
        return None, f"Unexpected Error: {str(e)}"

@st.cache_data(show_spinner=False, ttl=NETWORK_CONFIG['cache_ttl_seconds'])
def fetch_api_data_with_error(api_key, travel_mode, ranges_str, marker_lat, marker_lon):
    return safe_fetch_isochrone(api_key, travel_mode, ranges_str, marker_lat, marker_lon)

@st.cache_data(show_spinner=False, ttl=NETWORK_CONFIG['cache_ttl_seconds'])
def union_all_polygons(features_json_str):
    features = json.loads(features_json_str)
    polys = [shape(f['geometry']) for f in features]
    if not polys:
        return ""
    combined = unary_union(polys)
    return combined.wkt

# ============================================================================
# CACHE MANAGEMENT
# ============================================================================

def get_cache_key(polygon_wkt_str, network_type):
    polygon = wkt.loads(polygon_wkt_str)
    bounds = polygon.bounds
    rounded_bounds = tuple(round(b, 3) for b in bounds)
    key_str = f"{rounded_bounds}_{network_type}"
    return hashlib.md5(key_str.encode()).hexdigest()

def load_graph_from_cache(cache_key):
    cache_file = CACHE_DIR / f"osm_graph_{cache_key}.pkl"
    if cache_file.exists():
        try:
            with open(cache_file, 'rb') as f:
                return pickle.load(f)
        except Exception:
            return None
    return None

def save_graph_to_cache(cache_key, graph):
    cache_file = CACHE_DIR / f"osm_graph_{cache_key}.pkl"
    try:
        with open(cache_file, 'wb') as f:
            pickle.dump(graph, f, protocol=pickle.HIGHEST_PROTOCOL)
    except Exception:
        pass

def get_cache_stats():
    if not CACHE_DIR.exists():
        return {"count": 0, "size_mb": 0}
    cache_files = list(CACHE_DIR.glob("osm_graph_*.pkl"))
    total_size = sum(f.stat().st_size for f in cache_files)
    return {"count": len(cache_files), "size_mb": total_size / (1024 * 1024)}

def clear_cache():
    if CACHE_DIR.exists():
        for cache_file in CACHE_DIR.glob("osm_graph_*.pkl"):
            try:
                cache_file.unlink()
            except Exception:
                pass

def export_cache_as_zip():
    if not CACHE_DIR.exists():
        return None
    cache_files = list(CACHE_DIR.glob("osm_graph_*.pkl"))
    if not cache_files:
        return None
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
        for cache_file in cache_files:
            zf.write(cache_file, cache_file.name)
    zip_buffer.seek(0)
    return zip_buffer.getvalue()

def import_cache_from_zip(zip_bytes):
    result = {'success': False, 'imported': 0, 'skipped': 0, 'errors': []}
    try:
        CACHE_DIR.mkdir(exist_ok=True)
        zip_buffer = io.BytesIO(zip_bytes)
        with zipfile.ZipFile(zip_buffer, 'r') as zf:
            for file_info in zf.infolist():
                if not file_info.filename.startswith('osm_graph_') or not file_info.filename.endswith('.pkl'):
                    continue
                target_path = CACHE_DIR / file_info.filename
                if target_path.exists():
                    result['skipped'] += 1
                    continue
                try:
                    data = zf.read(file_info.filename)
                    test_buffer = io.BytesIO(data)
                    pickle.load(test_buffer)
                    with open(target_path, 'wb') as f:
                        f.write(data)
                    result['imported'] += 1
                except Exception as e:
                    result['errors'].append(f"Failed: {file_info.filename}: {str(e)}")
        result['success'] = result['imported'] > 0 or result['skipped'] > 0
    except Exception as e:
        result['errors'].append(f"Import failed: {str(e)}")
    return result

# GitHub Cache
GITHUB_CACHE_CONFIG = {
    "api_url": "https://api.github.com/repos/firstnattapon/Stock_Price/contents/Geoapify_Map",
    "raw_base_url": "https://raw.githubusercontent.com/firstnattapon/Stock_Price/main/Geoapify_Map"
}

@st.cache_data(ttl=3600, show_spinner=False)
def fetch_github_cache_list():
    try:
        response = requests.get(GITHUB_CACHE_CONFIG["api_url"], timeout=TIMEOUT_GITHUB_LIST)
        if response.status_code != 200:
            return []
        files = response.json()
        cache_files = []
        for f in files:
            if isinstance(f, dict) and f.get('name', '').endswith('_cache.zip'):
                cache_files.append({
                    'name': f['name'],
                    'download_url': f.get('download_url', ''),
                    'size_kb': f.get('size', 0) // 1024
                })
        return cache_files
    except Exception:
        return []

def download_github_cache(download_url):
    try:
        response = requests.get(download_url, timeout=TIMEOUT_GITHUB_DOWNLOAD)
        if response.status_code == 200:
            return response.content, None
        else:
            return None, f"ดาวน์โหลดล้มเหลว (HTTP {response.status_code})"
    except requests.Timeout:
        return None, "หมดเวลาในการดาวน์โหลด"
    except Exception as e:
        return None, f"เกิดข้อผิดพลาด: {str(e)}"

# ============================================================================
# NETWORK ANALYSIS
# ============================================================================

def _fetch_osm_graph(polygon_wkt_str, network_type):
    try:
        cache_key = get_cache_key(polygon_wkt_str, network_type)
        polygon_geom = wkt.loads(polygon_wkt_str)
        G = load_graph_from_cache(cache_key)
        if G is not None:
            return G, True, None
        G = ox.graph_from_polygon(polygon_geom, network_type=network_type, truncate_by_edge=True)
        save_graph_to_cache(cache_key, G)
        return G, False, None
    except ValueError as e:
        return None, False, f"Invalid geometry: {str(e)}"
    except Exception as e:
        return None, False, f"Failed to fetch OSM graph: {str(e)}"

@st.cache_data(show_spinner=False, ttl=NETWORK_CONFIG['cache_ttl_seconds'])
def _compute_centrality(polygon_wkt_str, network_type='drive'):
    G, was_cached, error = _fetch_osm_graph(polygon_wkt_str, network_type)
    if error:
        return {"error": error}
    if len(G.nodes) < 2:
        return {"error": "Not enough nodes found in the area."}

    node_count = len(G.nodes)
    is_large_graph = node_count > NETWORK_CONFIG['large_graph_threshold']

    closeness_cent = nx.closeness_centrality(G)
    max_close = max(closeness_cent.values()) if closeness_cent else 1

    G_undir = G.to_undirected()
    betweenness_cent = nx.edge_betweenness_centrality(G_undir, weight='length')
    max_bet = max(betweenness_cent.values()) if betweenness_cent else 1

    edges_geojson = []
    try:
        cmap_bet = cm.colormaps['plasma']
    except AttributeError:
        cmap_bet = cm.get_cmap('plasma')

    for u, v, k, data in G.edges(keys=True, data=True):
        score = betweenness_cent.get(tuple(sorted((u, v))), 0)
        norm_score = score / max_bet if max_bet > 0 else 0
        geom = mapping(data['geometry']) if 'geometry' in data else {
            "type": "LineString",
            "coordinates": [[G.nodes[u]['x'], G.nodes[u]['y']], [G.nodes[v]['x'], G.nodes[v]['y']]]
        }
        edges_geojson.append({
            "type": "Feature",
            "geometry": geom,
            "properties": {
                "type": "road",
                "betweenness": norm_score,
                "color": colors.to_hex(cmap_bet(norm_score)),
                "stroke_weight": NETWORK_CONFIG['edge_weight_base'] + (norm_score * NETWORK_CONFIG['edge_weight_multiplier'])
            }
        })

    nodes_geojson = []
    top_node_data = {"score": -1, "lat": 0, "lon": 0}
    for node, data in G.nodes(data=True):
        score = closeness_cent.get(node, 0)
        norm_score = score / max_close if max_close > 0 else 0
        if score > top_node_data["score"]:
            top_node_data = {"lat": data['y'], "lon": data['x'], "score": score}
        if norm_score > NETWORK_CONFIG['min_closeness_threshold']:
            nodes_geojson.append({
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [data['x'], data['y']]},
                "properties": {
                    "type": "intersection",
                    "closeness": norm_score,
                    "color": "#000000",
                    "radius": 2 + (norm_score * 6)
                }
            })

    return {
        "edges": {"type": "FeatureCollection", "features": edges_geojson},
        "nodes": {"type": "FeatureCollection", "features": nodes_geojson},
        "top_node": top_node_data if top_node_data["score"] != -1 else None,
        "stats": {
            "nodes_count": len(G.nodes),
            "edges_count": len(G.edges),
            "used_approximation": is_large_graph,
            "was_cached": was_cached
        }
    }

def process_network_analysis_with_ui(polygon_wkt_str, network_type='drive'):
    progress_bar = st.progress(0)
    status_container = st.empty()
    try:
        status_container.info("🔍 **Stage 1/3:** กำลังเตรียมข้อมูลพื้นที่...")
        progress_bar.progress(0.05)
        cache_key = get_cache_key(polygon_wkt_str, network_type)
        is_cached = load_graph_from_cache(cache_key) is not None
        if is_cached:
            status_container.success("✅ **พบข้อมูลใน Cache!** กำลังโหลด...")
        else:
            status_container.warning("⏳ **กำลังดาวน์โหลดข้อมูลครั้งแรก...**")
        progress_bar.progress(0.10)
        status_container.info("🛣️ **Stage 2/3:** กำลังวิเคราะห์โครงข่ายถนน...")
        progress_bar.progress(0.30)
        result = _compute_centrality(polygon_wkt_str, network_type)
        progress_bar.progress(0.90)
        if "error" in result:
            status_container.error(f"❌ {result['error']}")
        else:
            stats = result.get('stats', {})
            status_container.success(f"✅ **สำเร็จ!** {stats.get('nodes_count', 0):,} โหนด, {stats.get('edges_count', 0):,} ถนน")
        progress_bar.progress(1.0)
    finally:
        progress_bar.empty()
        status_container.empty()
    return result

# ============================================================================
# 3. STATE MANAGEMENT
# ============================================================================

def initialize_session_state():
    default_state = {
        'markers': [{'lat': DEFAULT_CONFIG['LAT'], 'lng': DEFAULT_CONFIG['LON'], 'active': True}],
        'isochrone_data': None,
        'intersection_data': None,
        'network_data': None,
        'nood_zones': None,
        'nood_scores': None,
        'last_processed_click': None,
        'colors': {'step1': '#2A9D8F', 'step2': '#E9C46A', 'step3': '#F4A261', 'step4': '#D62828'},
        'api_key': DEFAULT_CONFIG['GEOAPIFY_KEY'],
        'map_style_name': "Esri Light Gray (แนะนำสำหรับดูผังเมือง)",
        'travel_mode': "drive",
        'time_intervals': [5, 10],
        'show_dol': False,
        'show_cityplan': False,
        'cityplan_opacity': 0.7,
        'show_population': False,
        'show_traffic': False,
        'show_betweenness': False,
        'show_closeness': False,
        'show_nood_zones': True,
        'nood_occupancy': 75,
    }
    if 'markers' not in st.session_state:
        try:
            resp = requests.get(DEFAULT_CONFIG['JSON_URL'], timeout=TIMEOUT_INIT)
            if resp.status_code == 200:
                data = resp.json()
                default_state.update({k: data.get(k, v) for k, v in default_state.items()})
        except Exception:
            pass
    for key, value in default_state.items():
        st.session_state.setdefault(key, value)
    for m in st.session_state.markers:
        m.setdefault('active', True)

def clear_results(layers=None):
    if layers is None:
        layers = ['isochrone', 'intersection', 'network', 'nood']
    if 'isochrone' in layers:
        st.session_state.isochrone_data = None
    if 'intersection' in layers:
        st.session_state.intersection_data = None
    if 'network' in layers:
        st.session_state.network_data = None
    if 'nood' in layers:
        st.session_state.nood_zones = None
        st.session_state.nood_scores = None

def reset_state():
    st.session_state.markers = [{'lat': DEFAULT_CONFIG['LAT'], 'lng': DEFAULT_CONFIG['LON'], 'active': True}]
    st.session_state.last_processed_click = None
    clear_results()

def get_active_markers():
    return [(i, m) for i, m in enumerate(st.session_state.markers) if m.get('active', True)]

# ============================================================================
# 4. UI COMPONENTS
# ============================================================================

def add_wms_layer(m, layers, name, show, opacity=1.0):
    folium.WmsTileLayer(
        url=LONGDO_WMS_URL,
        layers=layers, name=name, fmt='image/png',
        transparent=True, version='1.1.1',
        attr=f'{name} / Longdo Map',
        show=show, opacity=opacity
    ).add_to(m)

def render_nood_dashboard():
    """Render NOOD Grading Dashboard in the main area."""
    nood_zones = st.session_state.get('nood_zones')
    
    if not nood_zones:
        return
    
    st.markdown("---")
    st.markdown("## 🏢 NOOD Asset Grading Dashboard")
    
    # Score Cards
    cols = st.columns(len(nood_zones))
    
    for i, (grade, zone_data) in enumerate(nood_zones.items()):
        grade_info = zone_data['grade_info']
        with cols[i]:
            # Travel time score
            if grade == 'A':
                tt_score = 1.0
                tt_label = "≤ 5 min"
            elif grade == 'B':
                tt_score = 0.8
                tt_label = "≤ 10 min"
            elif grade == 'C':
                tt_score = 0.4
                tt_label = "≤ 20 min"
            else:
                tt_score = 0.1
                tt_label = "> 20 min"
            
            # Get network score if available
            net_score = 0.5
            if st.session_state.network_data and st.session_state.network_data.get('top_node'):
                net_score = min(st.session_state.network_data['top_node']['score'] * 2, 1.0)
            
            occupancy_norm = st.session_state.get('nood_occupancy', 75) / 100
            nood_score = calculate_nood_score(tt_score, occupancy_norm, net_score)
            
            final_grade = determine_grade_from_score(nood_score)
            
            st.markdown(f"""
            <div style="
                background: linear-gradient(135deg, {grade_info['fill_color']}22, {grade_info['fill_color']}44);
                border-left: 4px solid {grade_info['color']};
                padding: 15px;
                border-radius: 8px;
                margin-bottom: 10px;
            ">
                <h3 style="margin:0; color:{grade_info['color']}">{grade_info['emoji']} Grade {grade}</h3>
                <p style="margin:5px 0; font-size:0.85em; color:#666">{grade_info['description']}</p>
                <hr style="margin:8px 0; border-color:{grade_info['color']}33">
                <p style="margin:3px 0">⏱️ Travel Time: <b>{tt_label}</b></p>
                <p style="margin:3px 0">📊 Min Occupancy: <b>{grade_info['min_occupancy']}%</b></p>
                <p style="margin:3px 0">🎯 NOOD Score: <b>{nood_score}</b></p>
                <p style="margin:3px 0">🏷️ Final Grade: <b>{final_grade}</b></p>
            </div>
            """, unsafe_allow_html=True)
    
    # NOOD Score Breakdown Table
    with st.expander("📊 NOOD Score Breakdown", expanded=False):
        st.markdown("### Scoring Formula")
        st.latex(r"""
        \text{NOOD Score} = (0.40 \times \text{Travel Time}) + (0.25 \times \text{Occupancy}) + (0.20 \times \text{Network}) + (0.15 \times \text{Population})
        """)
        
        st.markdown("### Weight Configuration")
        weight_df = pd.DataFrame([
            {"Factor": "⏱️ Travel Time Score", "Weight": "40%", "Description": "ยิ่งเดินทางถึงเร็ว ยิ่งดี"},
            {"Factor": "📊 Occupancy Rate", "Weight": "25%", "Description": "อัตราการเช่า (ผู้ใช้กำหนด)"},
            {"Factor": "🛣️ Network Centrality", "Weight": "20%", "Description": "จาก OSMnx Closeness Score"},
            {"Factor": "👥 Population Density", "Weight": "15%", "Description": "ความหนาแน่นประชากร"},
        ])
        st.dataframe(weight_df, use_container_width=True, hide_index=True)
        
        st.markdown("### Grade Thresholds")
        grade_df = pd.DataFrame([
            {"Grade": "A+", "NOOD Score": "≥ 85", "Travel Time": "≤ 5 min", "Occupancy": "85%+", "Strategy": "Premium / Flagship"},
            {"Grade": "A", "NOOD Score": "≥ 75", "Travel Time": "≤ 5 min", "Occupancy": "80%+", "Strategy": "Prime Commercial"},
            {"Grade": "B+", "NOOD Score": "≥ 65", "Travel Time": "≤ 10 min", "Occupancy": "75%+", "Strategy": "Strong Secondary"},
            {"Grade": "B", "NOOD Score": "≥ 55", "Travel Time": "≤ 10 min", "Occupancy": "70%+", "Strategy": "Standard Value"},
            {"Grade": "C", "NOOD Score": "≥ 40", "Travel Time": "≤ 20 min", "Occupancy": "60%+", "Strategy": "Emerging / Speculative"},
            {"Grade": "D", "NOOD Score": "< 40", "Travel Time": "> 20 min", "Occupancy": "< 60%", "Strategy": "Land Bank / Redevelopment"},
        ])
        st.dataframe(grade_df, use_container_width=True, hide_index=True)

def render_sidebar():
    with st.sidebar:
        st.header("⚙️ การตั้งค่า")

        # Config Import/Export
        with st.expander("💾 จัดการ Config (Export/Import)", expanded=False):
            export_data = json.dumps({
                "markers": st.session_state.markers,
                "settings": {k: st.session_state[k] for k in SESSION_KEYS_TO_SAVE if k in st.session_state}
            }, indent=2, ensure_ascii=False)
            st.download_button("Download Config (.json)", export_data, "geo_cbd_config.json", "application/json", use_container_width=True)
            uploaded_file = st.file_uploader("Upload .json", type=["json"], label_visibility="collapsed")
            if uploaded_file and st.button("ยืนยันการโหลด", use_container_width=True):
                try:
                    data = json.load(uploaded_file)
                    st.session_state.markers = data.get("markers", st.session_state.markers)
                    settings = data.get("settings", {})
                    for k, v in settings.items():
                        if k in SESSION_KEYS_TO_SAVE: st.session_state[k] = v
                    clear_results()
                    st.toast("✅ โหลดการตั้งค่าสำเร็จ!", icon="💾")
                    st.rerun()
                except Exception as e:
                    st.error(f"Error loading config: {e}")

        st.markdown("---")

        # Manual Coordinate Input
        with st.container():
            c1, c2 = st.columns([0.7, 0.3])
            coords_input = c1.text_input("Coords", placeholder="20.21, 100.40", label_visibility="collapsed", key="manual_coords")
            if c2.button("เพิ่ม", use_container_width=True):
                try:
                    lat_str, lng_str = coords_input.strip().split(',')
                    st.session_state.markers.append({'lat': float(lat_str), 'lng': float(lng_str), 'active': True})
                    clear_results(['isochrone', 'intersection', 'nood'])
                    st.rerun()
                except:
                    st.error("Format: Lat, Lng")

        st.text_input("Geoapify API Key", key="api_key", type="password")

        c1, c2 = st.columns(2)
        if c1.button("❌ ลบจุดล่าสุด", use_container_width=True) and st.session_state.markers:
            st.session_state.markers.pop()
            clear_results(['isochrone', 'intersection', 'nood'])
            st.rerun()
        if c2.button("🔄 รีเซ็ต", use_container_width=True):
            reset_state()
            st.rerun()

        active_list = get_active_markers()
        st.write(f"📍 Active Markers: **{len(active_list)}**")

        if st.session_state.markers:
            st.markdown("---")
            for i, m in enumerate(st.session_state.markers):
                col1, col2, col3 = st.columns([0.15, 0.70, 0.15])
                prev_active = m.get('active', True)
                is_active = col1.checkbox(" ", value=prev_active, key=f"active_chk_{i}", label_visibility="collapsed")
                if is_active != prev_active:
                    st.session_state.markers[i]['active'] = is_active
                    clear_results(['isochrone', 'intersection', 'nood'])
                style = f"color:{MARKER_COLORS[i % len(MARKER_COLORS)]}; font-weight:bold;" if is_active else "color:gray; text-decoration:line-through;"
                col2.markdown(f"<span style='{style}'>● จุดที่ {i+1}</span> <span style='font-size:0.8em'>({m['lat']:.4f}, {m['lng']:.4f})</span>", unsafe_allow_html=True)
                if col3.button("✕", key=f"del_btn_{i}"):
                    st.session_state.markers.pop(i)
                    clear_results(['isochrone', 'intersection', 'nood'])
                    st.rerun()

        st.markdown("---")

        # ===== NOOD GRADING PANEL =====
        with st.expander("🏢 NOOD Asset Grading", expanded=True):
            st.caption("ระบบให้เกรดพื้นที่อัตโนมัติจาก Isochrone + Network")
            st.checkbox("🗺️ แสดง NOOD Zones บนแผนที่", key="show_nood_zones")
            st.slider(
                "📊 Assumed Occupancy Rate (%)",
                min_value=0, max_value=100, step=5,
                key="nood_occupancy",
                help="กำหนด occupancy rate สำหรับคำนวณ NOOD Score"
            )
            
            st.markdown("##### Grade Legend")
            for grade_key, grade_data in NOOD_GRADES.items():
                st.markdown(
                    f"<span style='color:{grade_data['color']}; font-weight:bold'>"
                    f"{grade_data['emoji']} {grade_key}</span>: {grade_data['description'][:40]}...",
                    unsafe_allow_html=True
                )

        st.markdown("---")

        # Network Analysis Panel
        with st.expander("🕸️ วิเคราะห์โครงข่าย (Network Analysis)", expanded=False):
            st.caption("วิเคราะห์ความสำคัญของถนน (OSMnx)")
            can_analyze = st.session_state.isochrone_data is not None
            if can_analyze:
                st.info("✅ **Scope:** พื้นที่ Travel Areas ทั้งหมด", icon="🗺️")
            else:
                st.warning("⚠️ กรุณาคำนวณ Isochrone ก่อน", icon="🛑")

            cache_stats = get_cache_stats()
            st.markdown("##### 💾 Cache Management")
            if cache_stats['count'] > 0:
                st.caption(f"📊 **{cache_stats['count']} ไฟล์** ({cache_stats['size_mb']:.1f} MB)")
                if st.button("📤 Export Cache (.zip)", use_container_width=True, key="export_cache_btn"):
                    zip_data = export_cache_as_zip()
                    if zip_data:
                        st.download_button("📦 Download Ready", data=zip_data, file_name="osmnx_cache.zip",
                                           mime="application/zip", use_container_width=True)
                if st.button("🗑️ ล้าง Cache", use_container_width=True, type="secondary"):
                    clear_cache()
                    st.toast("ล้าง Cache สำเร็จ!", icon="✅")
                    st.rerun()
            else:
                st.caption("📊 **Cache ว่างเปล่า**")

            st.markdown("---")
            st.markdown("##### 🌐 Cache จาก GitHub")
            github_caches = fetch_github_cache_list()
            if github_caches:
                cache_options = ["-- เลือก Cache --"] + [f"{c['name']} ({c['size_kb']} KB)" for c in github_caches]
                selected_idx = st.selectbox("เลือก Cache", range(len(cache_options)),
                                            format_func=lambda i: cache_options[i], key="github_cache_select",
                                            label_visibility="collapsed")
                if selected_idx > 0:
                    selected_cache = github_caches[selected_idx - 1]
                    if st.button("📥 ดาวน์โหลด & นำเข้า", use_container_width=True, type="primary"):
                        with st.spinner(f"กำลังดาวน์โหลด {selected_cache['name']}..."):
                            zip_bytes, error = download_github_cache(selected_cache['download_url'])
                            if zip_bytes:
                                result = import_cache_from_zip(zip_bytes)
                                if result['success']:
                                    st.toast(f"นำเข้าสำเร็จ! ({result['imported']} ใหม่)", icon="✅")
                                    st.rerun()
                                else:
                                    for err in result['errors']:
                                        st.error(err)
                            else:
                                st.error(f"❌ {error}")
            else:
                st.caption("⚠️ ไม่พบ cache ใน GitHub")

            st.markdown("---")
            uploaded_cache = st.file_uploader("📥 Import Cache (.zip)", type=["zip"], key="cache_uploader")
            if uploaded_cache:
                if st.button("✅ ยืนยันการนำเข้า", use_container_width=True, type="secondary"):
                    result = import_cache_from_zip(uploaded_cache.read())
                    if result['success']:
                        st.toast(f"นำเข้าสำเร็จ! ({result['imported']} ใหม่)", icon="✅")
                        st.rerun()
                    else:
                        for err in result['errors']:
                            st.error(err)

            st.markdown("---")
            do_network = st.button("🚀 Run Network Analysis", use_container_width=True, disabled=not can_analyze)

            if st.session_state.network_data and st.session_state.network_data.get('top_node'):
                top = st.session_state.network_data['top_node']
                stats = st.session_state.network_data.get('stats', {})
                st.markdown("---")
                st.markdown(f"**🏆 Integration Center**")
                st.caption(f"Score: {top['score']:.4f}")
                if stats.get('used_approximation'):
                    st.caption("⚡ *Approximation (กราฟขนาดใหญ่)*")
                st.code(f"{top['lat']:.5f}, {top['lon']:.5f}")
                if st.button("➕ เพิ่มจุดนี้ลงในรายการ", use_container_width=True, type="secondary"):
                    st.session_state.markers.append({'lat': top['lat'], 'lng': top['lon'], 'active': True})
                    clear_results(['isochrone', 'intersection', 'nood'])
                    st.toast("เพิ่มจุดใหม่เรียบร้อย!", icon="✅")
                    st.rerun()

            st.markdown("##### Layer Controls")
            st.checkbox("Show Roads (Betweenness)", key="show_betweenness")
            st.caption("🔴: ทางผ่านหลัก (High Traffic Flow)")
            st.checkbox("Show Nodes (Integration)", key="show_closeness")
            st.caption("⚫: จุดเข้าถึงง่าย (Central Hub)")

        st.markdown("---")

        # Map Settings
        with st.expander("⚙️ ตั้งค่าแผนที่ & Layers", expanded=True):
            st.selectbox("สไตล์แผนที่", list(MAP_STYLES.keys()), key="map_style_name")
            st.checkbox("🚦 การจราจร (Google Traffic)", key="show_traffic")
            st.checkbox("👥 ความหนาแน่นประชากร", key="show_population")
            c1, c2 = st.columns([0.65, 0.35])
            c1.checkbox("🏙️ ผังเมืองรวม", key="show_cityplan")
            if st.session_state.show_cityplan:
                c2.slider("Op.", 0.2, 1.0, key="cityplan_opacity", label_visibility="collapsed")
            st.checkbox("📜 รูปแปลงที่ดิน", key="show_dol")
            st.markdown("##### 🚗 การเดินทาง (Isochrone)")
            st.selectbox("โหมด", list(TRAVEL_MODE_NAMES.keys()), format_func=TRAVEL_MODE_NAMES.get, key="travel_mode")
            st.multiselect("เวลา (นาที)", TIME_OPTIONS, key="time_intervals")

        do_calc = st.button("🧩 คำนวณหา Isochrone CBD + NOOD Grade", type="primary", use_container_width=True)

    return do_calc, do_network, active_list

def perform_calculation(active_list):
    if not st.session_state.api_key:
        st.warning("⚠️ กรุณาใส่ API Key")
        return
    if not active_list:
        st.warning("⚠️ กรุณาเลือกจุดอย่างน้อย 1 จุด")
        return
    if not st.session_state.time_intervals:
        st.warning("⚠️ กรุณาเลือกช่วงเวลา")
        return

    with st.spinner('กำลังคำนวณ Isochrone + NOOD Grades...'):
        all_features = []
        ranges_str = ",".join(str(t * 60) for t in sorted(st.session_state.time_intervals))
        errors = []

        for act_idx, (orig_idx, marker) in enumerate(active_list):
            features, error_msg = fetch_api_data_with_error(
                st.session_state.api_key, st.session_state.travel_mode,
                ranges_str, marker['lat'], marker['lng']
            )
            if features is None:
                errors.append(f"จุดที่ {orig_idx + 1}: {error_msg}")
                continue
            for f in features:
                f['properties'].update({
                    'travel_time_minutes': f['properties'].get('value', 0) / 60,
                    'original_index': orig_idx,
                    'active_index': act_idx
                })
                all_features.append(f)

        if errors:
            for error in errors:
                st.error(error)
            if not all_features:
                return

        if all_features:
            st.session_state.isochrone_data = {"type": "FeatureCollection", "features": all_features}
            
            # Calculate CBD intersection
            cbd_geom = calculate_intersection(all_features, len(active_list))
            if cbd_geom:
                st.session_state.intersection_data = {
                    "type": "FeatureCollection",
                    "features": [{"type": "Feature", "geometry": cbd_geom, "properties": {"type": "cbd"}}]
                }
                st.toast("✅ พบพื้นที่ CBD!", icon="🎯")
            else:
                st.session_state.intersection_data = None

            # Calculate NOOD Zones
            nood_zones = calculate_nood_zones(all_features, len(active_list))
            if nood_zones:
                st.session_state.nood_zones = nood_zones
                grades_found = ", ".join(nood_zones.keys())
                st.toast(f"🏢 NOOD Grades: {grades_found}", icon="🏢")
            else:
                st.session_state.nood_zones = None

def perform_network_analysis():
    if not st.session_state.isochrone_data:
        st.error("❌ No Isochrone data found.")
        return
    with st.spinner('กำลังวิเคราะห์โครงข่ายถนน...'):
        try:
            feats_json = json.dumps(st.session_state.isochrone_data.get('features', []))
            combined_wkt = union_all_polygons(feats_json)
            if not combined_wkt:
                return st.error("❌ No polygons to analyze.")
            net_type = TRAVEL_MODE_TO_NETWORK_TYPE.get(st.session_state.travel_mode, 'drive')
            result = process_network_analysis_with_ui(combined_wkt, net_type)
            if "error" in result:
                st.error(f"❌ {result['error']}")
            else:
                st.session_state.network_data = result
                st.toast("✅ Analysis Completed!", icon="🏆")
        except Exception as e:
            st.error(f"❌ Processing Error: {e}")

def render_map():
    style_conf = MAP_STYLES[st.session_state.map_style_name]
    center = [st.session_state.markers[-1]['lat'], st.session_state.markers[-1]['lng']] if st.session_state.markers else [DEFAULT_CONFIG['LAT'], DEFAULT_CONFIG['LON']]
    m = folium.Map(location=center, zoom_start=14, tiles=style_conf["tiles"], attr=style_conf["attr"])

    # Traffic overlay
    if st.session_state.show_traffic:
        folium.TileLayer(
            tiles="https://mt1.google.com/vt?lyrs=h,traffic&x={x}&y={y}&z={z}",
            attr="Google Traffic", name="Google Traffic", overlay=True
        ).add_to(m)

    # Network Analysis Layers
    net_data = st.session_state.network_data
    if net_data and 'error' not in net_data:
        if st.session_state.show_betweenness and net_data.get("edges"):
            folium.GeoJson(
                net_data["edges"], name="Road Betweenness",
                style_function=lambda x: {
                    'color': x['properties']['color'],
                    'weight': x['properties']['stroke_weight'],
                    'opacity': 0.8
                },
                tooltip=folium.GeoJsonTooltip(fields=['betweenness'], aliases=['Betweenness:'], localize=True)
            ).add_to(m)
        if st.session_state.show_closeness and net_data.get("nodes"):
            folium.GeoJson(
                net_data["nodes"], name="Node Integration",
                marker=folium.CircleMarker(),
                style_function=lambda x: {
                    'fillColor': x['properties']['color'], 'color': '#000000',
                    'weight': 1, 'radius': x['properties']['radius'], 'fillOpacity': 0.9
                },
                tooltip=folium.GeoJsonTooltip(fields=['closeness'], aliases=['Integration:'], localize=True)
            ).add_to(m)
        if net_data.get("top_node"):
            top = net_data["top_node"]
            folium.Marker(
                [top['lat'], top['lon']], popup=f"🏆 Center (Score: {top['score']:.4f})",
                icon=folium.Icon(color='orange', icon='star', prefix='fa'), tooltip="Integration Center"
            ).add_to(m)

    # Isochrones
    if st.session_state.isochrone_data:
        folium.GeoJson(
            st.session_state.isochrone_data, name='Travel Areas',
            style_function=lambda x: {
                'fillColor': get_fill_color(x['properties']['travel_time_minutes'], st.session_state.colors),
                'color': get_border_color(x['properties']['original_index']),
                'weight': 1, 'fillOpacity': 0.15
            }
        ).add_to(m)

    # ===== NOOD ZONES =====
    if st.session_state.get('show_nood_zones') and st.session_state.get('nood_zones'):
        for grade, zone_data in st.session_state.nood_zones.items():
            grade_info = zone_data['grade_info']
            nood_geojson = {
                "type": "FeatureCollection",
                "features": [{
                    "type": "Feature",
                    "geometry": zone_data['geometry'],
                    "properties": {
                        "grade": grade,
                        "label": grade_info['label'],
                        "min_occupancy": f"{grade_info['min_occupancy']}%"
                    }
                }]
            }
            folium.GeoJson(
                nood_geojson,
                name=f"NOOD Grade {grade}",
                style_function=lambda x, gi=grade_info: {
                    'fillColor': gi['fill_color'],
                    'color': gi['color'],
                    'weight': 3,
                    'fillOpacity': gi['fill_opacity'],
                    'dashArray': '8, 4'
                },
                tooltip=folium.GeoJsonTooltip(
                    fields=['grade', 'label', 'min_occupancy'],
                    aliases=['Grade:', 'Classification:', 'Min Occupancy:'],
                    localize=True
                )
            ).add_to(m)

    # CBD Zone
    if st.session_state.intersection_data:
        folium.GeoJson(
            st.session_state.intersection_data, name='CBD Zone',
            style_function=lambda x: {
                'fillColor': '#FFD700', 'color': '#FF8C00',
                'weight': 3, 'fillOpacity': 0.5, 'dashArray': '5, 5'
            }
        ).add_to(m)

    # WMS Layers
    add_wms_layer(m, 'thailand_population', 'ความหนาแน่นประชากร', st.session_state.show_population)
    add_wms_layer(m, 'cityplan_dpt', 'ผังเมืองรวม', st.session_state.show_cityplan, opacity=st.session_state.cityplan_opacity)
    add_wms_layer(m, 'dol', 'รูปแปลงที่ดิน', st.session_state.show_dol)

    # Markers
    for i, marker in enumerate(st.session_state.markers):
        active = marker.get('active', True)
        folium.Marker(
            [marker['lat'], marker['lng']], popup=f"จุดที่ {i+1}",
            icon=folium.Icon(
                color=MARKER_COLORS[i % len(MARKER_COLORS)] if active else "gray",
                icon="map-marker" if active else "ban", prefix='fa'
            )
        ).add_to(m)

    folium.LayerControl().add_to(m)
    return st_folium(m, height=900, use_container_width=True, key="main_map")

# ============================================================================
# 5. MAIN EXECUTION
# ============================================================================

def main():
    st.set_page_config(**PAGE_CONFIG)
    st.markdown("""<style>
        .block-container { padding-top: 1.5rem; padding-bottom: 0rem; }
        h1 { margin-bottom: 0px; }
        div[data-testid="stHorizontalBlock"] button { padding: 0rem 0.5rem; }
    </style>""", unsafe_allow_html=True)

    initialize_session_state()

    do_calc, do_net, active_list = render_sidebar()

    # Header with NOOD branding
    st.markdown("""
    <h1 style="text-align:center">
        🏢 CBD NOOD Grading System
    </h1>
    <p style="text-align:center; color:#666; margin-bottom:0">
        Local CBD NOOD Analysis — Isochrone × Network × Asset Grading
    </p>
    """, unsafe_allow_html=True)

    if do_calc:
        perform_calculation(active_list)

    if do_net:
        perform_network_analysis()

    # Render NOOD Dashboard (above map)
    render_nood_dashboard()

    # Render Map
    map_output = render_map()

    # Handle map clicks
    if map_output and map_output.get('last_clicked'):
        clicked = map_output['last_clicked']
        if should_add_marker(clicked['lat'], clicked['lng']):
            st.session_state.markers.append({'lat': clicked['lat'], 'lng': clicked['lng'], 'active': True})
            st.session_state.last_processed_click = {
                'timestamp': time.time(),
                'lat': clicked['lat'],
                'lon': clicked['lng']
            }
            clear_results(['isochrone', 'intersection', 'nood'])
            st.rerun()

if __name__ == "__main__":
    main()
