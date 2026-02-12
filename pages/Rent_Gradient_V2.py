import streamlit as st
import folium
from streamlit_folium import st_folium
import requests
from shapely.geometry import shape, mapping
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
from concurrent.futures import ThreadPoolExecutor, as_completed

# ============================================================================
# 1. CONSTANTS & CONFIGURATION (Simple & Stable)
# ============================================================================

PAGE_CONFIG = {
    "page_title": "Geoapify CBD x Longdo GIS + Network Analysis",
    "page_icon": "🌍",
    "layout": "wide"
}

class AppConfig:
    """Centralized Configuration for easier maintenance."""
    DEFAULT_LAT = 20.219443
    DEFAULT_LON = 100.403630
    DEFAULT_GEOAPIFY_KEY = "4eefdfb0b0d349e595595b9c03a69e3d"
    DEFAULT_LONGDO_KEY = "0a999afb0da60c5c45d010e9c171ffc8"
    JSON_URL = "https://raw.githubusercontent.com/firstnattapon/Stock_Price/refs/heads/main/Geoapify_Map/geoapify_cbd_project.json"
    
    # Network Analysis Limits
    CACHE_DIR = Path("./cache")
    CACHE_TTL = 3600
    CLICK_DEBOUNCE_SEC = 0.5
    CLICK_DIST_THRESHOLD_M = 10
    LARGE_GRAPH_THRESHOLD = 2000
    MIN_CLOSENESS_THRESHOLD = 0.0
    
    # Visuals
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
    
    TRAVEL_MODES = {
        "drive": "🚗 ขับรถ",
        "walk": "🚶 เดินเท้า",
        "bicycle": "🚲 ปั่นจักรยาน",
        "transit": "🚌 ขนส่งสาธารณะ"
    }

AppConfig.CACHE_DIR.mkdir(exist_ok=True)
LONGDO_WMS_URL = f"https://ms.longdo.com/mapproxy/service?key={AppConfig.DEFAULT_LONGDO_KEY}"

# Keys to persist in config file
SESSION_KEYS_TO_SAVE = [
    'api_key', 'map_style_name', 'travel_mode', 'time_intervals', 
    'show_dol', 'show_cityplan', 'cityplan_opacity', 'show_population', 
    'show_traffic', 'colors', 'show_betweenness', 'show_closeness'
]

# ============================================================================
# 2. CORE LOGIC (Pure Functions & Caching)
# ============================================================================

def get_fill_color(minutes: float, colors_config: Dict[str, str]) -> str:
    if minutes <= 10: return colors_config['step1']
    if minutes <= 20: return colors_config['step2']
    if minutes <= 30: return colors_config['step3']
    return colors_config['step4']

def get_border_color(idx: Optional[int]) -> str:
    if idx is None: return '#3388ff'
    return AppConfig.HEX_COLORS[idx % len(AppConfig.HEX_COLORS)]

def calculate_distance_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371000
    lat1_rad, lon1_rad = radians(lat1), radians(lon1)
    lat2_rad, lon2_rad = radians(lat2), radians(lon2)
    dlat, dlon = lat2_rad - lat1_rad, lon2_rad - lon1_rad
    a = sin(dlat/2)**2 + cos(lat1_rad) * cos(lat2_rad) * sin(dlon/2)**2
    c = 2 * atan2(sqrt(a), sqrt(1-a))
    return R * c

def should_add_marker(new_lat: float, new_lon: float) -> bool:
    last = st.session_state.get('last_processed_click')
    if not last: return True
    if time.time() - last['timestamp'] < AppConfig.CLICK_DEBOUNCE_SEC: return False
    if calculate_distance_meters(last['lat'], last['lon'], new_lat, new_lon) < AppConfig.CLICK_DIST_THRESHOLD_M: return False
    return True

def calculate_intersection(features: List[Dict], num_active_markers: int) -> Optional[Dict]:
    if num_active_markers < 2: return None
    polys = {}
    for feat in features:
        idx = feat['properties']['active_index']
        geom = shape(feat['geometry'])
        polys[idx] = polys.get(idx, geom).union(geom)
    
    if len(polys) < num_active_markers: return None
    
    try:
        common = list(polys.values())[0]
        for p in list(polys.values())[1:]:
            common = common.intersection(p)
            if common.is_empty: return None
        return mapping(common) if not common.is_empty else None
    except: return None

# --- API & Network Logic ---

def safe_fetch_isochrone(api_key: str, travel_mode: str, ranges: str, lat: float, lon: float) -> Tuple[Optional[List[Dict]], Optional[str]]:
    url = "https://api.geoapify.com/v1/isoline"
    params = {"lat": lat, "lon": lon, "type": "time", "mode": travel_mode, "range": ranges, "apiKey": api_key}
    try:
        resp = requests.get(url, params=params, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            return data.get('features'), None
        return None, f"API Error {resp.status_code}: {resp.text[:50]}"
    except Exception as e:
        return None, str(e)

@st.cache_data(show_spinner=False, ttl=AppConfig.CACHE_TTL)
def fetch_api_data_cached(api_key: str, travel_mode: str, ranges: str, lat: float, lon: float) -> Tuple[Optional[List[Dict]], Optional[str]]:
    return safe_fetch_isochrone(api_key, travel_mode, ranges, lat, lon)

def fetch_all_isochrones_parallel(active_list: List[Tuple[int, Dict]], api_key: str, mode: str, ranges: str) -> Tuple[List[Dict], List[str]]:
    """
    Optimization: Parallel API calls using ThreadPoolExecutor.
    Returns (all_features, errors)
    """
    all_features = []
    errors = []
    
    with ThreadPoolExecutor(max_workers=5) as executor:
        # Map futures to their original index for tracking (active_idx, orig_idx)
        future_map = {
            executor.submit(fetch_api_data_cached, api_key, mode, ranges, m['lat'], m['lng']): (i, orig_i)
            for i, (orig_i, m) in enumerate(active_list)
        }
        
        for future in as_completed(future_map):
            act_idx, orig_idx = future_map[future]
            try:
                feats, err = future.result()
                if feats:
                    for f in feats:
                        f['properties'].update({
                            'travel_time_minutes': f['properties'].get('value', 0) / 60,
                            'original_index': orig_idx,
                            'active_index': act_idx
                        })
                        all_features.append(f)
                else:
                    errors.append(f"จุดที่ {orig_idx+1}: {err}")
            except Exception as e:
                errors.append(f"จุดที่ {orig_idx+1}: System Error {str(e)}")
                
    return all_features, errors

@st.cache_data(show_spinner=False, ttl=AppConfig.CACHE_TTL)
def union_all_polygons_cached(features_json: str) -> str:
    """Stable caching for polygon union."""
    feats = json.loads(features_json)
    polys = [shape(f['geometry']) for f in feats]
    return unary_union(polys).wkt if polys else ""

# --- OSM Graph Cache Management ---

def get_cache_key(wkt_str: str, net_type: str) -> str:
    bounds = wkt.loads(wkt_str).bounds
    key = f"{tuple(round(b, 3) for b in bounds)}_{net_type}"
    return hashlib.md5(key.encode()).hexdigest()

def get_cache_path(key: str) -> Path:
    return AppConfig.CACHE_DIR / f"osm_graph_{key}.pkl"

def save_graph_cache(key: str, G):
    try:
        with open(get_cache_path(key), 'wb') as f: pickle.dump(G, f, pickle.HIGHEST_PROTOCOL)
    except: pass

def load_graph_cache(key: str):
    path = get_cache_path(key)
    if path.exists():
        try:
            with open(path, 'rb') as f: return pickle.load(f)
        except: return None
    return None

def fetch_osm_graph_logic(wkt_str: str, net_type: str) -> Tuple[Any, bool, Optional[str]]:
    """Pure logic for fetching graph (Cache -> Download -> Save)."""
    try:
        key = get_cache_key(wkt_str, net_type)
        G = load_graph_cache(key)
        if G: return G, True, None
        
        poly = wkt.loads(wkt_str)
        G = ox.graph_from_polygon(poly, network_type=net_type, truncate_by_edge=True)
        save_graph_cache(key, G)
        return G, False, None
    except Exception as e:
        return None, False, str(e)

@st.cache_data(show_spinner=False, ttl=AppConfig.CACHE_TTL)
def compute_centrality_cached(wkt_str: str, net_type: str) -> Dict[str, Any]:
    """Heavy computation logic wrapped in cache."""
    G, was_cached, err = fetch_osm_graph_logic(wkt_str, net_type)
    if err: return {"error": err}
    
    if len(G.nodes) < 2: return {"error": "Not enough nodes."}

    # Centrality Logic
    close_cent = nx.closeness_centrality(G)
    max_close = max(close_cent.values()) if close_cent else 1
    
    G_undir = G.to_undirected()
    bet_cent = nx.edge_betweenness_centrality(G_undir, weight='length')
    max_bet = max(bet_cent.values()) if bet_cent else 1
    
    # Process Edges
    edges_geo = []
    cmap = cm.get_cmap('plasma')
    base_w, mult_w = 2, 4
    
    for u, v, k, d in G.edges(keys=True, data=True):
        score = bet_cent.get(tuple(sorted((u, v))), 0)
        norm = score / max_bet
        geom = mapping(d.get('geometry', None)) or {
            "type": "LineString", "coordinates": [[G.nodes[u]['x'], G.nodes[u]['y']], [G.nodes[v]['x'], G.nodes[v]['y']]]
        }
        edges_geo.append({
            "type": "Feature", "geometry": geom,
            "properties": {
                "color": colors.to_hex(cmap(norm)), "stroke_weight": base_w + (norm * mult_w),
                "betweenness": norm
            }
        })
        
    # Process Nodes
    nodes_geo = []
    top = {"score": -1, "lat": 0, "lon": 0}
    
    for n, d in G.nodes(data=True):
        score = close_cent.get(n, 0)
        norm = score / max_close
        if score > top['score']: top = {"lat": d['y'], "lon": d['x'], "score": score}
        
        if norm > AppConfig.MIN_CLOSENESS_THRESHOLD:
            nodes_geo.append({
                "type": "Feature", "geometry": {"type": "Point", "coordinates": [d['x'], d['y']]},
                "properties": {"color": "#000000", "radius": 2 + (norm * 6), "closeness": norm}
            })
            
    return {
        "edges": {"type": "FeatureCollection", "features": edges_geo},
        "nodes": {"type": "FeatureCollection", "features": nodes_geo},
        "top_node": top if top['score'] != -1 else None,
        "stats": {"nodes": len(G.nodes), "edges": len(G.edges), "cached": was_cached}
    }

# ============================================================================
# 3. STATE & UI
# ============================================================================

def init_state():
    defaults = {
        'markers': [{'lat': AppConfig.DEFAULT_LAT, 'lng': AppConfig.DEFAULT_LON, 'active': True}],
        'isochrone_data': None, 'intersection_data': None, 'network_data': None,
        'last_processed_click': None,
        'colors': {'step1': '#2A9D8F', 'step2': '#E9C46A', 'step3': '#F4A261', 'step4': '#D62828'},
        'api_key': AppConfig.DEFAULT_GEOAPIFY_KEY,
        'map_style_name': "Esri Light Gray (แนะนำสำหรับดูผังเมือง)",
        'travel_mode': "drive",
        'time_intervals': [5],
        'show_dol': False, 'show_cityplan': False, 'cityplan_opacity': 0.7,
        'show_population': False, 'show_traffic': False, 'show_betweenness': False, 'show_closeness': False
    }
    
    # Load remote config once
    if 'markers' not in st.session_state:
        try:
            r = requests.get(AppConfig.JSON_URL, timeout=3)
            if r.status_code == 200: defaults.update(r.json())
        except: pass

    for k, v in defaults.items():
        st.session_state.setdefault(k, v)
        
    for m in st.session_state.markers: m.setdefault('active', True)

def clear_res(target=None):
    targets = target or ['isochrone', 'intersection', 'network']
    if 'isochrone' in targets: st.session_state.isochrone_data = None
    if 'intersection' in targets: st.session_state.intersection_data = None
    if 'network' in targets: st.session_state.network_data = None

def render_sidebar():
    with st.sidebar:
        st.header("⚙️ การตั้งค่า")
        
        # Config Managment
        with st.expander("💾 Config", expanded=False):
            st.download_button("Download .json", json.dumps({
                "markers": st.session_state.markers,
                "settings": {k: st.session_state[k] for k in SESSION_KEYS_TO_SAVE if k in st.session_state}
            }, indent=2), "config.json", "application/json", use_container_width=True)
            
            f = st.file_uploader("Upload .json", type=["json"], label_visibility="collapsed")
            if f and st.button("Load Config", use_container_width=True):
                try:
                    d = json.load(f)
                    st.session_state.markers = d.get("markers", st.session_state.markers)
                    for k,v in d.get("settings", {}).items(): 
                        if k in SESSION_KEYS_TO_SAVE: st.session_state[k] = v
                    clear_res()
                    st.rerun()
                except Exception as e: st.error(str(e))

        st.markdown("---")
        
        # Inputs
        c1, c2 = st.columns([0.7, 0.3])
        txt = c1.text_input("Coords", placeholder="Lat, Lng", label_visibility="collapsed", key="in_coords")
        if c2.button("เพิ่ม", use_container_width=True) and txt:
            try:
                lat, lng = map(float, txt.split(','))
                st.session_state.markers.append({'lat': lat, 'lng': lng, 'active': True})
                clear_res(['isochrone', 'intersection'])
                st.rerun()
            except: st.error("Invalid Format")
            
        st.text_input("API Key", key="api_key", type="password")
        
        # Actions
        c1, c2 = st.columns(2)
        if c1.button("❌ ลบจุดล่าสุด", use_container_width=True) and st.session_state.markers:
            st.session_state.markers.pop()
            clear_res(['isochrone', 'intersection'])
            st.rerun()
        if c2.button("🔄 รีเซ็ต", use_container_width=True):
            st.session_state.markers = [{'lat': AppConfig.DEFAULT_LAT, 'lng': AppConfig.DEFAULT_LON, 'active': True}]
            clear_res()
            st.rerun()
            
        # Markers
        active_list = [(i, m) for i, m in enumerate(st.session_state.markers) if m.get('active', True)]
        st.write(f"📍 Active Markers: **{len(active_list)}**")
        if st.session_state.markers:
            st.markdown("---")
            for i, m in enumerate(st.session_state.markers):
                c1, c2, c3 = st.columns([0.15, 0.7, 0.15])
                act = c1.checkbox("", value=m.get('active', True), key=f"chk_{i}")
                if act != m.get('active', True):
                    m['active'] = act
                    clear_res(['isochrone', 'intersection'])
                    st.rerun()
                
                style = f"color:{AppConfig.MARKER_COLORS[i%8]}; font-weight:bold;" if act else "color:gray; text-decoration:line-through;"
                c2.markdown(f"<span style='{style}'>● จุดที่ {i+1}</span> <small>({m['lat']:.4f}, {m['lng']:.4f})</small>", unsafe_allow_html=True)
                if c3.button("✕", key=f"del_{i}"):
                    st.session_state.markers.pop(i)
                    clear_res(['isochrone', 'intersection'])
                    st.rerun()
        
        st.markdown("---")
        
        # Analysis Controls
        with st.expander("🕸️ Network Analysis", expanded=True):
            can_run = st.session_state.isochrone_data is not None
            st.info("✅ Scope: พื้นที่ Travel Areas" if can_run else "⚠️ รอผลลัพธ์ Isochrone", icon="🗺️" if can_run else "🛑")
            
            # Cache UI
            files = list(AppConfig.CACHE_DIR.glob("osm_graph_*.pkl"))
            size = sum(f.stat().st_size for f in files) / (1024*1024)
            st.caption(f"💾 **Cache:** {len(files)} files ({size:.1f} MB)")
            
            if files and st.button("🗑️ Clear Cache", use_container_width=True):
                for f in files: f.unlink(missing_ok=True)
                st.toast("Cache Cleared!")
                st.rerun()
                
            run_net = st.button("🚀 Run Analysis", disabled=not can_run, use_container_width=True)
            
            if st.session_state.network_data:
                res = st.session_state.network_data
                if res.get('top_node'):
                    top = res['top_node']
                    st.success(f"🏆 Center Score: {top['score']:.4f}")
                    if st.button("➕ เพิ่มจุดนี้", use_container_width=True):
                        st.session_state.markers.append({'lat': top['lat'], 'lng': top['lon'], 'active': True})
                        clear_res(['isochrone', 'intersection'])
                        st.rerun()
                        
            st.checkbox("Show Roads (Betweenness)", key="show_betweenness")
            st.checkbox("Show Nodes (Integration)", key="show_closeness")

        # Visual Settings
        with st.expander("⚙️ Layers", expanded=True):
            st.selectbox("Style", list(AppConfig.MAP_STYLES.keys()), key="map_style_name")
            st.checkbox("🚦 Traffic", key="show_traffic")
            st.checkbox("👥 Population", key="show_population")
            c1, c2 = st.columns([0.7, 0.3])
            c1.checkbox("🏙️ City Plan", key="show_cityplan")
            if st.session_state.show_cityplan: c2.slider("Op.", 0.2, 1.0, key="cityplan_opacity", label_visibility="collapsed")
            st.checkbox("📜 Land Plots", key="show_dol")
            
            st.markdown("##### 🚗 Calc Settings")
            st.selectbox("Mode", list(AppConfig.TRAVEL_MODES.keys()), format_func=AppConfig.TRAVEL_MODES.get, key="travel_mode")
            st.multiselect("Time (min)", [5, 10, 15, 20, 30, 45, 60], key="time_intervals")
            
        run_calc = st.button("🧩 คำนวณ Isochrone", type="primary", use_container_width=True)
        
    return run_calc, run_net, active_list

# ============================================================================
# 4. MAIN WORKFLOW
# ============================================================================

def main():
    st.set_page_config(**PAGE_CONFIG)
    st.markdown("""<style>.block-container { padding-top: 1rem; } h1 { margin-bottom: 0px; } </style>""", unsafe_allow_html=True)
    init_state()
    
    do_calc, do_net, active_markers = render_sidebar()
    
    # 1. Isochrone Logic (Parallelized)
    if do_calc:
        if not st.session_state.api_key: st.warning("⚠️ Missing API Key")
        elif not active_markers: st.warning("⚠️ No active markers")
        elif not st.session_state.time_intervals: st.warning("⚠️ No time range")
        else:
            with st.spinner("⏳ Fetching Isochrones (Parallel)..."):
                ranges = ",".join(str(t*60) for t in sorted(st.session_state.time_intervals))
                feats, errs = fetch_all_isochrones_parallel(active_markers, st.session_state.api_key, st.session_state.travel_mode, ranges)
                
                if errs:
                    for e in errs: st.error(e)
                
                if feats:
                    st.session_state.isochrone_data = {"type": "FeatureCollection", "features": feats}
                    cbd = calculate_intersection(feats, len(active_markers))
                    if cbd:
                        st.session_state.intersection_data = {
                            "type": "FeatureCollection", 
                            "features": [{"type": "Feature", "geometry": cbd, "properties": {"type": "cbd"}}]
                        }
                        st.success("✅ CBD Found!")
                    else:
                        st.session_state.intersection_data = None
                        st.warning("⚠️ No Intersection")
    
    # 2. Network Logic
    if do_net and st.session_state.isochrone_data:
        progress = st.progress(0)
        status = st.empty()
        
        try:
            status.info("Stage 1: Preparing Polygon...")
            progress.progress(10)
            
            # Use cached union
            feats_json = json.dumps(st.session_state.isochrone_data.get('features', []))
            poly_wkt = union_all_polygons_cached(feats_json)
            
            if not poly_wkt:
                st.error("No valid polygon")
            else:
                progress.progress(30)
                status.info("Stage 2: Analyzing Network (this may take time)...")
                
                # Check cache first for UI feedback only (logic handled in compute_centrality_cached)
                is_cached = load_graph_cache(get_cache_key(poly_wkt, st.session_state.travel_mode)) is not None
                if not is_cached: status.warning("⏳ Downloading Graph (First run takes longer)...")
                
                res = compute_centrality_cached(poly_wkt, st.session_state.travel_mode)
                progress.progress(90)
                
                if "error" in res:
                    st.error(res['error'])
                else:
                    st.session_state.network_data = res
                    stats = res.get('stats', {})
                    status.success(f"✅ Active: {stats.get('nodes')} nodes, {stats.get('edges')} edges")
                    
        except Exception as e:
            st.error(f"Error: {e}")
        finally:
            progress.empty()
            time.sleep(2)
            status.empty()

    # 3. Map Rendering
    style = AppConfig.MAP_STYLES[st.session_state.map_style_name]
    center = [st.session_state.markers[-1]['lat'], st.session_state.markers[-1]['lng']] if st.session_state.markers else [AppConfig.DEFAULT_LAT, AppConfig.DEFAULT_LON]
    m = folium.Map(location=center, zoom_start=14, tiles=style["tiles"], attr=style["attr"])
    
    # Layers
    if st.session_state.show_traffic:
        folium.TileLayer("https://mt1.google.com/vt?lyrs=h,traffic&x={x}&y={y}&z={z}", attr="Google Traffic", name="Traffic", overlay=True).add_to(m)
        
    def add_wms(layer, name, show, op=1.0):
        folium.WmsTileLayer(url=LONGDO_WMS_URL, layers=layer, name=name, fmt='image/png', transparent=True, attr=name, show=show, opacity=op).add_to(m)
        
    add_wms('thailand_population', 'Population', st.session_state.show_population)
    add_wms('cityplan_dpt', 'City Plan', st.session_state.show_cityplan, st.session_state.cityplan_opacity)
    add_wms('dol', 'Land Plots', st.session_state.show_dol)
    
    # Overlays (Isochrone, CBD, Network)
    if st.session_state.isochrone_data:
        folium.GeoJson(st.session_state.isochrone_data, name='Isochrones', style_function=lambda x: {
            'fillColor': get_fill_color(x['properties']['travel_time_minutes'], st.session_state.colors),
            'color': get_border_color(x['properties']['original_index']), 'weight': 1, 'fillOpacity': 0.2
        }).add_to(m)
        
    if st.session_state.intersection_data:
        folium.GeoJson(st.session_state.intersection_data, name='CBD', style_function=lambda x: {
            'fillColor': '#FFD700', 'color': '#FF8C00', 'weight': 3, 'fillOpacity': 0.6, 'dashArray': '5, 5'
        }).add_to(m)
        
    net = st.session_state.network_data
    if net and 'error' not in net:
        if st.session_state.show_betweenness and net.get('edges'):
            folium.GeoJson(net['edges'], name="Edges", style_function=lambda x: {
                'color': x['properties']['color'], 'weight': x['properties']['stroke_weight'], 'opacity': 0.8
            }).add_to(m)
        if st.session_state.show_closeness and net.get('nodes'):
            folium.GeoJson(net['nodes'], name="Nodes", marker=folium.CircleMarker(), style_function=lambda x: {
                'fillColor': x['properties']['color'], 'color': '#000000', 'radius': x['properties']['radius'], 'fillOpacity': 0.9
            }).add_to(m)
        if net.get('top_node'):
            t = net['top_node']
            folium.Marker([t['lat'], t['lon']], icon=folium.Icon(color='orange', icon='star', prefix='fa'), popup=f"Score: {t['score']:.4f}").add_to(m)

    # Markers
    for i, mk in enumerate(st.session_state.markers):
        active = mk.get('active', True)
        icon = folium.Icon(color=AppConfig.MARKER_COLORS[i%8], icon="map-marker", prefix='fa') if active else folium.Icon(color='gray', icon='ban', prefix='fa')
        folium.Marker([mk['lat'], mk['lng']], icon=icon, popup=f"P{i+1}").add_to(m)

    folium.LayerControl().add_to(m)
    map_out = st_folium(m, height=800, use_container_width=True, key="main_map")
    
    # Click Logic
    if map_out and map_out.get('last_clicked'):
        c = map_out['last_clicked']
        if should_add_marker(c['lat'], c['lng']):
            st.session_state.markers.append({'lat': c['lat'], 'lng': c['lng'], 'active': True})
            st.session_state.last_processed_click = {'timestamp': time.time(), 'lat': c['lat'], 'lon': c['lng']}
            clear_res(['isochrone', 'intersection'])
            st.rerun()

if __name__ == "__main__":
    main()
