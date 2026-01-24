import streamlit as st
import folium
from streamlit_folium import st_folium
import requests
from shapely.geometry import shape, mapping
import json
from typing import List, Dict, Any, Optional, Tuple
import networkx as nx
import osmnx as ox
import matplotlib.cm as cm
import matplotlib.colors as colors

# ============================================================================
# 1. CONSTANTS & CONFIGURATION
# ============================================================================

PAGE_CONFIG = {
    "page_title": "Geoapify CBD x Longdo GIS + Network Analysis",
    "page_icon": "🌍",
    "layout": "wide"
}

# --- Geoapify Configuration ---
DEFAULT_JSON_URL = "https://raw.githubusercontent.com/firstnattapon/Stock_Price/refs/heads/main/Geoapify_Map/geoapify_cbd_project.json"
DEFAULT_LAT = 20.219443
DEFAULT_LON = 100.403630
DEFAULT_GEOAPIFY_KEY = "4eefdfb0b0d349e595595b9c03a69e3d"

# --- Longdo GIS Configuration ---
LONGDO_API_KEY = "0a999afb0da60c5c45d010e9c171ffc8"
LONGDO_WMS_URL = f"https://ms.longdo.com/mapproxy/service?key={LONGDO_API_KEY}"

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

SESSION_KEYS_TO_SAVE = [
    'api_key', 'map_style_name', 'travel_mode', 'time_intervals', 
    'show_dol', 'show_cityplan', 'cityplan_opacity', 'show_population', 
    'show_traffic', 'colors',
    'net_radius', 'show_betweenness', 'show_closeness' # Added Network keys
]

# ============================================================================
# 2. LOGIC & CALCULATION HELPERS
# ============================================================================

def get_fill_color(minutes: float, colors_config: Dict[str, str]) -> str:
    """Determine polygon color based on travel time."""
    if minutes <= 10: return colors_config['step1']
    elif minutes <= 20: return colors_config['step2']
    elif minutes <= 30: return colors_config['step3']
    else: return colors_config['step4']

def get_border_color(original_marker_idx: Optional[int]) -> str:
    """Determine border color based on marker index."""
    if original_marker_idx is None: return '#3388ff'
    return HEX_COLORS[original_marker_idx % len(HEX_COLORS)]

def calculate_intersection(features: List[Dict], num_active_markers: int) -> Optional[Dict]:
    """Calculate the geometric intersection (CBD) of isochrones."""
    if num_active_markers < 2: return None
    polys_per_active_idx = {}
    
    for feat in features:
        active_idx = feat['properties']['active_index']
        geom = shape(feat['geometry'])
        if active_idx not in polys_per_active_idx:
            polys_per_active_idx[active_idx] = geom
        else:
            polys_per_active_idx[active_idx] = polys_per_active_idx[active_idx].union(geom)
    
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

@st.cache_data(show_spinner=False, ttl=3600)
def fetch_api_data_cached(api_key: str, travel_mode: str, ranges_str: str, marker_lat: float, marker_lon: float) -> Optional[List[Dict]]:
    """Fetch isochrone data from Geoapify API."""
    url = "https://api.geoapify.com/v1/isoline"
    params = {"lat": marker_lat, "lon": marker_lon, "type": "time", "mode": travel_mode, "range": ranges_str, "apiKey": api_key}
    try:
        response = requests.get(url, params=params, timeout=10)
        return response.json().get('features', []) if response.status_code == 200 else None
    except Exception:
        return None

def add_wms_layer(m: folium.Map, layers: str, name: str, show: bool, opacity: float = 1.0):
    """Helper to add Longdo WMS layers."""
    folium.WmsTileLayer(
        url=LONGDO_WMS_URL,
        layers=layers,
        name=name,
        fmt='image/png',
        transparent=True,
        version='1.1.1',
        attr=f'{name} / Longdo Map',
        show=show,
        opacity=opacity
    ).add_to(m)

# --- Network Centrality Helpers (OSMnx) ---

@st.cache_data(show_spinner=False, ttl=3600)
def process_network_analysis(center_lat: float, center_lon: float, radius: int, network_type: str = 'drive'):
    """
    Downloads OSM road network and calculates Centrality measures.
    Returns GeoJSON-compatible data for Edges (Betweenness) and Nodes (Closeness).
    """
    try:
        # 1. Download Graph
        G = ox.graph_from_point((center_lat, center_lon), dist=radius, network_type=network_type)
        # 2. Project to UTM for accurate metric calculation (optional but recommended for lengths)
        G_proj = ox.project_graph(G)
        
        # 3. Calculate Closeness Centrality (Node-based: Integration)
        # "เข้าถึงง่ายจากทุกจุด" -> Closeness
        closeness_cent = nx.closeness_centrality(G) # Using unprojected G for lat/lon compatibility or projected? Usually G is fine for topology.
        # Normalize and store in node attributes
        nx.set_node_attributes(G, closeness_cent, 'closeness')

        # 4. Calculate Edge Betweenness Centrality (Edge-based: Throughput)
        # "ทางผ่านหลักเชื่อมโซน" -> Edge Betweenness
        # Note: This is computationally expensive O(NM). 
        # Convert to undirected to speed up and represents physical road usage better
        G_undir = G.to_undirected() 
        betweenness_cent = nx.edge_betweenness_centrality(G_undir, weight='length')
        
        # Map edge betweenness back to original MultiDiGraph edges
        # We assign the undirected edge score to both directed edges
        edge_colors = {}
        max_bet = max(betweenness_cent.values()) if betweenness_cent else 1
        
        for u, v, k, data in G.edges(keys=True, data=True):
            # Try both directions from undirected calculation
            score = betweenness_cent.get(tuple(sorted((u, v))), 0)
            data['betweenness'] = score
            data['normalized_betweenness'] = score / max_bet if max_bet > 0 else 0

        # 5. Prepare Data for Folium (GeoJSON extraction)
        # Extract Edges for Betweenness Visualization
        edges_geojson = []
        cmap_bet = cm.get_cmap('plasma') # Blue to Yellow/Red
        
        for u, v, data in G.edges(data=True):
            if 'geometry' in data:
                geom = mapping(data['geometry'])
            else:
                # Create straight line if no geometry
                geom = {
                    "type": "LineString",
                    "coordinates": [[G.nodes[u]['x'], G.nodes[u]['y']], [G.nodes[v]['x'], G.nodes[v]['y']]]
                }
            
            score = data.get('normalized_betweenness', 0)
            color_rgba = cmap_bet(score)
            color_hex = colors.to_hex(color_rgba)
            
            edges_geojson.append({
                "type": "Feature",
                "geometry": geom,
                "properties": {
                    "type": "road",
                    "betweenness": score,
                    "color": color_hex,
                    "stroke_weight": 2 + (score * 4) # Thicker if more central
                }
            })

        # Extract Nodes for Closeness Visualization
        nodes_geojson = []
        max_close = max(closeness_cent.values()) if closeness_cent else 1
        cmap_close = cm.get_cmap('viridis')
        
        for node, data in G.nodes(data=True):
            score = closeness_cent[node]
            norm_score = score / max_close if max_close > 0 else 0
            
            color_rgba = cmap_close(norm_score)
            color_hex = colors.to_hex(color_rgba)
            
            # Only keep top 20% nodes to avoid clutter, or all? Let's keep top 30% for visual clarity
            if norm_score > 0.4: 
                nodes_geojson.append({
                    "type": "Feature",
                    "geometry": {
                        "type": "Point",
                        "coordinates": [data['x'], data['y']]
                    },
                    "properties": {
                        "type": "intersection",
                        "closeness": norm_score,
                        "color": color_hex,
                        "radius": 2 + (norm_score * 6)
                    }
                })
            
        return {
            "edges": {"type": "FeatureCollection", "features": edges_geojson},
            "nodes": {"type": "FeatureCollection", "features": nodes_geojson},
            "stats": {
                "nodes_count": len(G.nodes),
                "edges_count": len(G.edges)
            }
        }

    except Exception as e:
        return {"error": str(e)}

# ============================================================================
# 3. STATE MANAGEMENT
# ============================================================================

def initialize_session_state():
    """Initialize all session state variables."""
    defaults = {
        'markers': [{'lat': DEFAULT_LAT, 'lng': DEFAULT_LON, 'active': True}],
        'isochrone_data': None,
        'intersection_data': None,
        'network_data': None, # [NEW] Store Network analysis result
        'colors': {'step1': '#2A9D8F', 'step2': '#E9C46A', 'step3': '#F4A261', 'step4': '#D62828'},
        'api_key': DEFAULT_GEOAPIFY_KEY,
        'map_style_name': "Esri Light Gray (แนะนำสำหรับดูผังเมือง)",
        'travel_mode': "drive",
        'time_intervals': [5],
        'show_dol': False,
        'show_cityplan': False,
        'cityplan_opacity': 0.7,
        'show_population': False,
        'show_traffic': False,
        # [NEW] Network Configs
        'net_radius': 1000,
        'show_betweenness': False,
        'show_closeness': False
    }
    
    if 'markers' not in st.session_state:
        try:
            response = requests.get(DEFAULT_JSON_URL, timeout=3)
            if response.status_code == 200:
                data = response.json()
                defaults.update({k: data.get(k, v) for k, v in defaults.items()})
        except Exception: pass

    for k, v in defaults.items():
        if k not in st.session_state: st.session_state[k] = v
    
    for m in st.session_state.markers:
        if 'active' not in m: m['active'] = True

def reset_state():
    st.session_state.markers = [{'lat': DEFAULT_LAT, 'lng': DEFAULT_LON, 'active': True}]
    clear_results()
    st.session_state.network_data = None

def clear_results():
    st.session_state.isochrone_data = None
    st.session_state.intersection_data = None

def generate_export_json() -> str:
    export_data = {
        "markers": st.session_state.markers,
        "settings": {k: st.session_state[k] for k in SESSION_KEYS_TO_SAVE if k in st.session_state}
    }
    return json.dumps(export_data, indent=2, ensure_ascii=False)

def apply_imported_config(uploaded_file):
    if uploaded_file is not None:
        try:
            data = json.load(uploaded_file)
            if "markers" in data: st.session_state.markers = data["markers"]
            if "settings" in data:
                for k, v in data["settings"].items():
                    if k in SESSION_KEYS_TO_SAVE: st.session_state[k] = v
            clear_results()
            st.toast("✅ โหลดการตั้งค่าสำเร็จ!", icon="💾")
        except Exception as e:
            st.error(f"เกิดข้อผิดพลาด: {e}")

# ============================================================================
# 4. UI COMPONENTS
# ============================================================================

def render_sidebar():
    with st.sidebar:
        st.header("⚙️ การตั้งค่า")
        
        # --- Config Manager ---
        with st.expander("💾 จัดการ Config (Export/Import)", expanded=False):
            st.download_button("Download Config (.json)", generate_export_json(), "geo_cbd_config.json", "application/json", use_container_width=True)
            uploaded_file = st.file_uploader("Upload .json", type=["json"], label_visibility="collapsed")
            if uploaded_file and st.button("ยืนยันการโหลด", use_container_width=True):
                apply_imported_config(uploaded_file)
                st.rerun()

        st.markdown("---")
        
        # --- Manual Add ---
        with st.container():
            c1, c2 = st.columns([0.7, 0.3])
            coords = c1.text_input("Coords", placeholder="20.21, 100.40", label_visibility="collapsed", key="manual")
            if c2.button("เพิ่ม", use_container_width=True):
                try:
                    parts = coords.strip().replace(" ", "").split(',')
                    if len(parts) >= 2:
                        st.session_state.markers.append({'lat': float(parts[0]), 'lng': float(parts[1]), 'active': True})
                        clear_results()
                        st.rerun()
                except: st.error("พิกัดผิดพลาด")
            
        st.text_input("Geoapify API Key", key="api_key", type="password")
        
        # --- Controls ---
        c1, c2 = st.columns(2)
        if c1.button("❌ ลบจุดล่าสุด", use_container_width=True) and st.session_state.markers:
            st.session_state.markers.pop()
            clear_results()
            st.rerun()
        if c2.button("🔄 รีเซ็ต", use_container_width=True):
            reset_state()
            st.rerun()

        # --- Marker List ---
        active_list = [(i, m) for i, m in enumerate(st.session_state.markers) if m.get('active', True)]
        st.write(f"📍 Active Markers: **{len(active_list)}**")
        
        if st.session_state.markers:
            st.markdown("---")
            for i, m in enumerate(st.session_state.markers):
                col_chk, col_txt, col_del = st.columns([0.15, 0.70, 0.15])
                with col_chk:
                    is_active = st.checkbox(" ", value=m.get('active', True), key=f"active_chk_{i}", label_visibility="collapsed")
                    st.session_state.markers[i]['active'] = is_active
                with col_txt:
                    style = f"color:{MARKER_COLORS[i % len(MARKER_COLORS)]}; font-weight:bold;" if is_active else "color:gray; text-decoration:line-through;"
                    st.markdown(f"<span style='{style}'>● จุดที่ {i+1}</span> <span style='font-size:0.8em'>({m['lat']:.4f}, {m['lng']:.4f})</span>", unsafe_allow_html=True)
                with col_del:
                    if st.button("✕", key=f"del_btn_{i}"):
                        st.session_state.markers.pop(i)
                        clear_results()
                        st.rerun()

        st.markdown("---")
        
        # --- [NEW] Network Analysis Section ---
        with st.expander("🕸️ วิเคราะห์โครงข่าย (Network Analysis)", expanded=False):
            st.caption("วิเคราะห์ความสำคัญของถนน (OSMnx)")
            st.slider("รัศมีวิเคราะห์ (เมตร)", 500, 3000, key="net_radius", step=100, help="ยิ่งเยอะยิ่งช้า")
            
            analyze_net_btn = st.button("🚀 Run Network Analysis", use_container_width=True)
            
            st.markdown("##### Layer Controls")
            st.checkbox("Show Roads (Betweenness)", key="show_betweenness")
            st.caption("🔴: ทางผ่านหลัก (High Traffic Flow)")
            st.checkbox("Show Nodes (Integration)", key="show_closeness")
            st.caption("🟡: จุดเข้าถึงง่าย (Central Hub)")

        st.markdown("---")
        
        # --- Existing Settings ---
        with st.expander("⚙️ ตั้งค่าแผนที่ & Layers", expanded=True):
            st.selectbox("สไตล์แผนที่", list(MAP_STYLES.keys()), key="map_style_name")
            st.checkbox("🚦 การจราจร (Google Traffic)", key="show_traffic")
            st.checkbox("👥 ความหนาแน่นประชากร", key="show_population")
            
            col_cp_chk, col_cp_sld = st.columns([0.65, 0.35])
            with col_cp_chk: st.checkbox("🏙️ ผังเมืองรวม", key="show_cityplan")
            with col_cp_sld: 
                if st.session_state.show_cityplan: st.slider("Op.", 0.2, 1.0, key="cityplan_opacity", label_visibility="collapsed")
            
            st.checkbox("📜 รูปแปลงที่ดิน", key="show_dol")
            
            st.markdown("##### 🚗 การเดินทาง (Isochrone)")
            st.selectbox("โหมด", list(TRAVEL_MODE_NAMES.keys()), format_func=lambda x: TRAVEL_MODE_NAMES[x], key="travel_mode")
            st.multiselect("เวลา (นาที)", TIME_OPTIONS, key="time_intervals")
            
        do_calculate = st.button("🧩 คำนวณหา Isochrone CBD", type="primary", use_container_width=True)
        return do_calculate, analyze_net_btn, active_list

def perform_calculation(active_list):
    """Execute Geoapify Logic."""
    if not st.session_state.api_key: st.warning("ใส่ API Key")
    elif not active_list: st.warning("เลือกจุด")
    elif not st.session_state.time_intervals: st.warning("เลือกเวลา")
    else:
        with st.spinner('กำลังคำนวณ Isochrone...'):
            all_feats = []
            ranges = ",".join([str(t*60) for t in sorted(st.session_state.time_intervals)])
            
            for act_idx, (orig_idx, m) in enumerate(active_list):
                feats = fetch_api_data_cached(st.session_state.api_key, st.session_state.travel_mode, ranges, m['lat'], m['lng'])
                if feats:
                    for f in feats:
                        f['properties'].update({
                            'travel_time_minutes': f['properties'].get('value',0)/60, 
                            'original_index': orig_idx, 
                            'active_index': act_idx
                        })
                        all_feats.append(f)
            
            if all_feats:
                st.session_state.isochrone_data = {"type": "FeatureCollection", "features": all_feats}
                cbd = calculate_intersection(all_feats, len(active_list))
                st.session_state.intersection_data = {"type": "FeatureCollection", "features": [{"type": "Feature", "geometry": cbd, "properties": {"type": "cbd"}}]} if cbd else None
                if cbd: st.success("✅ พบพื้นที่ CBD!")
                else: st.warning("⚠️ ไม่พบพื้นที่ทับซ้อน")

def perform_network_analysis(active_list):
    """Execute OSMnx Logic."""
    if not active_list:
        st.warning("กรุณาปักหมุดอย่างน้อย 1 จุดเพื่อเป็นศูนย์กลางการวิเคราะห์")
        return

    # Use the centroid of all active markers as the analysis center
    lats = [m['lat'] for _, m in active_list]
    lngs = [m['lng'] for _, m in active_list]
    center_lat = sum(lats) / len(lats)
    center_lon = sum(lngs) / len(lngs)
    
    with st.spinner(f'กำลังโหลดแผนที่และคำนวณ Centrality (Radius: {st.session_state.net_radius}m)... อาจใช้เวลาสักครู่'):
        result = process_network_analysis(center_lat, center_lon, st.session_state.net_radius)
        
        if "error" in result:
            st.error(f"เกิดข้อผิดพลาดในการวิเคราะห์ Network: {result['error']}")
        else:
            st.session_state.network_data = result
            st.toast(f"วิเคราะห์เสร็จสิ้น! (Nodes: {result['stats']['nodes_count']}, Edges: {result['stats']['edges_count']})", icon="🕸️")
            # Auto-enable layers so user sees result immediately
            st.session_state.show_betweenness = True
            st.session_state.show_closeness = True

def render_map():
    style = MAP_STYLES[st.session_state.map_style_name]
    # Center map based on markers or default
    if st.session_state.markers:
        center = [st.session_state.markers[-1]['lat'], st.session_state.markers[-1]['lng']]
    else:
        center = [DEFAULT_LAT, DEFAULT_LON]

    m = folium.Map(location=center, zoom_start=14, tiles=style["tiles"], attr=style["attr"])

    # 1. Traffic Layer
    if st.session_state.show_traffic:
        folium.TileLayer(
            tiles="https://mt1.google.com/vt?lyrs=h,traffic&x={x}&y={y}&z={z}",
            attr="Google Traffic",
            name="Google Traffic",
            overlay=True,
            control=True
        ).add_to(m)

    # 2. [NEW] Network Analysis Layers
    if st.session_state.network_data:
        # 2.1 Betweenness (Edges)
        if st.session_state.show_betweenness and st.session_state.network_data.get("edges"):
            folium.GeoJson(
                st.session_state.network_data["edges"],
                name="Road Betweenness",
                style_function=lambda x: {
                    'color': x['properties']['color'],
                    'weight': x['properties']['stroke_weight'],
                    'opacity': 0.8
                },
                tooltip=folium.GeoJsonTooltip(fields=['betweenness'], aliases=['Betweenness Score:'], localize=True)
            ).add_to(m)
        
        # 2.2 Closeness (Nodes)
        if st.session_state.show_closeness and st.session_state.network_data.get("nodes"):
            folium.GeoJson(
                st.session_state.network_data["nodes"],
                name="Node Integration",
                marker=folium.CircleMarker(),
                style_function=lambda x: {
                    'fillColor': x['properties']['color'],
                    'color': '#ffffff',
                    'weight': 1,
                    'radius': x['properties']['radius'],
                    'fillOpacity': 0.9
                },
                tooltip=folium.GeoJsonTooltip(fields=['closeness'], aliases=['Integration Score:'], localize=True)
            ).add_to(m)

    # 3. Isochrones
    if st.session_state.isochrone_data:
        folium.GeoJson(
            st.session_state.isochrone_data, name='Travel Areas',
            style_function=lambda x: {
                'fillColor': get_fill_color(x['properties']['travel_time_minutes'], st.session_state.colors),
                'color': get_border_color(x['properties']['original_index']),
                'weight': 1, 'fillOpacity': 0.2
            }
        ).add_to(m)

    # 4. CBD Intersection
    if st.session_state.intersection_data:
        folium.GeoJson(
            st.session_state.intersection_data, name='CBD Zone',
            style_function=lambda x: {'fillColor': '#FFD700', 'color': '#FF8C00', 'weight': 3, 'fillOpacity': 0.6, 'dashArray': '5, 5'}
        ).add_to(m)

    # 5. WMS Layers
    add_wms_layer(m, 'thailand_population', 'ความหนาแน่นประชากร', st.session_state.show_population)
    add_wms_layer(m, 'cityplan_dpt', 'ผังเมืองรวม', st.session_state.show_cityplan, opacity=st.session_state.cityplan_opacity)
    add_wms_layer(m, 'dol', 'รูปแปลงที่ดิน', st.session_state.show_dol)

    # 6. Markers
    for i, marker in enumerate(st.session_state.markers):
        is_active = marker.get('active', True)
        folium.Marker(
            [marker['lat'], marker['lng']],
            popup=f"จุดที่ {i+1}",
            icon=folium.Icon(color=MARKER_COLORS[i%8] if is_active else "gray", icon="map-marker" if is_active else "ban", prefix='fa')
        ).add_to(m)

    folium.LayerControl().add_to(m)
    return st_folium(m, height=750, use_container_width=True, key="main_map")

# ============================================================================
# 5. MAIN APP EXECUTION
# ============================================================================

def main():
    st.set_page_config(**PAGE_CONFIG)
    st.markdown("""<style>.block-container { padding-top: 2rem; padding-bottom: 0rem; } h1 { margin-bottom: 0px; } div[data-testid="stHorizontalBlock"] button { padding: 0rem 0.5rem; }</style>""", unsafe_allow_html=True)
    
    initialize_session_state()
    
    do_calculate, do_network, active_list = render_sidebar()
    
    if do_calculate:
        perform_calculation(active_list)
        
    if do_network:
        perform_network_analysis(active_list)
        
    map_out = render_map()
    
    if map_out and map_out.get('last_clicked'):
        clat, clng = map_out['last_clicked']['lat'], map_out['last_clicked']['lng']
        if not st.session_state.markers or (abs(clat - st.session_state.markers[-1]['lat']) > 1e-5):
            st.session_state.markers.append({'lat': clat, 'lng': clng, 'active': True})
            clear_results() # Clear cache on new marker
            st.rerun()

if __name__ == "__main__":
    main()
