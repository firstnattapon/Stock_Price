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
import xml.etree.ElementTree as ET  # Added for KML parsing
from typing import List, Dict, Any, Optional
import io

# ============================================================================
# 1. CONSTANTS & CONFIGURATION
# ============================================================================

PAGE_CONFIG = {
    "page_title": "Geoapify CBD x Longdo GIS + Network Analysis",
    "page_icon": "🌍",
    "layout": "wide"
}

# --- API & Defaults ---
DEFAULT_CONFIG = {
    "JSON_URL": "https://raw.githubusercontent.com/firstnattapon/Stock_Price/refs/heads/main/Geoapify_Map/geoapify_cbd_project.json",
    "LAT": 20.219443,
    "LON": 100.403630,
    "GEOAPIFY_KEY": "4eefdfb0b0d349e595595b9c03a69e3d",
    "LONGDO_KEY": "0a999afb0da60c5c45d010e9c171ffc8"
}

LONGDO_WMS_URL = f"https://ms.longdo.com/mapproxy/service?key={DEFAULT_CONFIG['LONGDO_KEY']}"

# --- Visual Assets ---
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

# Keys to persist in config file
SESSION_KEYS_TO_SAVE = [
    'api_key', 'map_style_name', 'travel_mode', 'time_intervals', 
    'show_dol', 'show_cityplan', 'cityplan_opacity', 'show_population', 
    'show_traffic', 'colors', 'show_betweenness', 'show_closeness',
    'show_railway' # Added new setting
]

# ============================================================================
# 2. HELPER FUNCTIONS (Logic & Calculation)
# ============================================================================

def parse_kml_to_geojson(kml_content: bytes) -> Optional[Dict]:
    """
    Parses a simple KML (LineStrings/Points) to GeoJSON FeatureCollection.
    Robust enough for basic geometry display.
    """
    try:
        root = ET.fromstring(kml_content)
        ns = {'kml': 'http://www.opengis.net/kml/2.2'}
        
        # Determine namespace (sometimes KMLs don't use the default strictly)
        if '}' in root.tag:
            ns_url = root.tag.split('}')[0].strip('{')
            ns = {'kml': ns_url}

        features = []
        
        # Helper to parse coordinates string "lon,lat,alt ..."
        def parse_coords(coords_str):
            points = []
            for item in coords_str.strip().split():
                parts = item.split(',')
                if len(parts) >= 2:
                    points.append([float(parts[0]), float(parts[1])])
            return points

        # Find all Placemarks
        for placemark in root.findall('.//kml:Placemark', ns):
            name = placemark.find('kml:name', ns)
            name_text = name.text if name is not None else "Unnamed"
            
            # LineString
            line = placemark.find('.//kml:LineString/kml:coordinates', ns)
            if line is not None and line.text:
                coords = parse_coords(line.text)
                if coords:
                    features.append({
                        "type": "Feature",
                        "geometry": {"type": "LineString", "coordinates": coords},
                        "properties": {"name": name_text, "type": "railway_line"}
                    })
            
            # Point
            point = placemark.find('.//kml:Point/kml:coordinates', ns)
            if point is not None and point.text:
                coords = parse_coords(point.text)
                if coords:
                    features.append({
                        "type": "Feature",
                        "geometry": {"type": "Point", "coordinates": coords[0]},
                        "properties": {"name": name_text, "type": "station"}
                    })

        if not features:
            # Check for NetworkLink if no features found
            net_link = root.find('.//kml:NetworkLink', ns)
            if net_link is not None:
                return {"type": "NetworkLink", "features": [], "message": "This KML contains a NetworkLink. Please upload the source geometry file directly."}
            return None

        return {"type": "FeatureCollection", "features": features}

    except Exception as e:
        print(f"KML Parsing Error: {e}")
        return None

def get_fill_color(minutes: float, colors_config: Dict[str, str]) -> str:
    """Determine polygon color based on travel time."""
    if minutes <= 10: return colors_config['step1']
    if minutes <= 20: return colors_config['step2']
    if minutes <= 30: return colors_config['step3']
    return colors_config['step4']

def get_border_color(original_marker_idx: Optional[int]) -> str:
    """Determine border color based on marker index to differentiate sources."""
    if original_marker_idx is None: return '#3388ff'
    return HEX_COLORS[original_marker_idx % len(HEX_COLORS)]

def calculate_intersection(features: List[Dict], num_active_markers: int) -> Optional[Dict]:
    """Calculate the geometric intersection (CBD) of isochrones."""
    if num_active_markers < 2: return None
    
    # Group geometries by active index
    polys_per_active_idx = {}
    for feat in features:
        active_idx = feat['properties']['active_index']
        geom = shape(feat['geometry'])
        polys_per_active_idx[active_idx] = polys_per_active_idx.get(active_idx, geom).union(geom)
    
    if len(polys_per_active_idx) < num_active_markers: return None
    
    # Calculate intersection across all active markers
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
    params = {
        "lat": marker_lat, "lon": marker_lon, 
        "type": "time", "mode": travel_mode, 
        "range": ranges_str, "apiKey": api_key
    }
    try:
        response = requests.get(url, params=params, timeout=15)
        if response.status_code == 200:
            return response.json().get('features', [])
        return None
    except Exception:
        return None

@st.cache_data(show_spinner=False, ttl=3600)
def process_network_analysis(polygon_wkt_str: str, network_type: str = 'drive') -> Dict[str, Any]:
    """Downloads OSM road network Within the given Polygon and calculates Centrality."""
    try:
        # 1. Load Geometry & Download Graph
        polygon_geom = wkt.loads(polygon_wkt_str)
        G = ox.graph_from_polygon(polygon_geom, network_type=network_type, truncate_by_edge=True)
        
        if len(G.nodes) < 2:
            return {"error": "Not enough nodes found in the area."}

        # 2. Calculate Centrality Measures
        closeness_cent = nx.closeness_centrality(G) 
        max_close = max(closeness_cent.values()) if closeness_cent else 1
        
        G_undir = G.to_undirected() 
        betweenness_cent = nx.edge_betweenness_centrality(G_undir, weight='length')
        max_bet = max(betweenness_cent.values()) if betweenness_cent else 1
        
        # 3. Format Data for Visualization (GeoJSON preparation)
        edges_geojson = []
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
                    "stroke_weight": 2 + (norm_score * 4)
                }
            })

        nodes_geojson = []
        top_node_data = {"score": -1, "lat": 0, "lon": 0}

        for node, data in G.nodes(data=True):
            score = closeness_cent.get(node, 0)
            norm_score = score / max_close if max_close > 0 else 0
            
            if score > top_node_data["score"]:
                top_node_data = {"lat": data['y'], "lon": data['x'], "score": score}
            
            if norm_score > 0.0: 
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
            "stats": {"nodes_count": len(G.nodes), "edges_count": len(G.edges)}
        }

    except Exception as e:
        return {"error": str(e)}

# ============================================================================
# 3. STATE MANAGEMENT
# ============================================================================

def initialize_session_state():
    """Initialize all session state variables with defaults."""
    default_state = {
        'markers': [{'lat': DEFAULT_CONFIG['LAT'], 'lng': DEFAULT_CONFIG['LON'], 'active': True}],
        'isochrone_data': None,
        'intersection_data': None,
        'network_data': None,
        'railway_geojson': None, # New State for Railway Data
        'colors': {'step1': '#2A9D8F', 'step2': '#E9C46A', 'step3': '#F4A261', 'step4': '#D62828'},
        'api_key': DEFAULT_CONFIG['GEOAPIFY_KEY'],
        'map_style_name': "Esri Light Gray (แนะนำสำหรับดูผังเมือง)",
        'travel_mode': "drive",
        'time_intervals': [5],
        'show_dol': False,
        'show_cityplan': False,
        'cityplan_opacity': 0.7,
        'show_population': False,
        'show_traffic': False,
        'show_betweenness': False,
        'show_closeness': False,
        'show_railway': False # Default Off
    }

    # Load initial data from JSON if markers are missing
    if 'markers' not in st.session_state:
        try:
            resp = requests.get(DEFAULT_CONFIG['JSON_URL'], timeout=3)
            if resp.status_code == 200:
                data = resp.json()
                default_state.update({k: data.get(k, v) for k, v in default_state.items()})
        except Exception: 
            pass

    for key, value in default_state.items():
        if key not in st.session_state:
            st.session_state[key] = value

    for m in st.session_state.markers:
        m.setdefault('active', True)

def clear_results(keep_network: bool = False):
    """Clear calculation results to force re-computation on data change."""
    st.session_state.isochrone_data = None
    st.session_state.intersection_data = None
    if not keep_network:
        st.session_state.network_data = None 

def reset_state():
    """Reset to factory defaults."""
    st.session_state.markers = [{'lat': DEFAULT_CONFIG['LAT'], 'lng': DEFAULT_CONFIG['LON'], 'active': True}]
    clear_results()

# ============================================================================
# 4. UI COMPONENTS
# ============================================================================

def add_wms_layer(m: folium.Map, layers: str, name: str, show: bool, opacity: float = 1.0):
    """Helper to add Longdo WMS layers cleanly."""
    folium.WmsTileLayer(
        url=LONGDO_WMS_URL,
        layers=layers, name=name, fmt='image/png',
        transparent=True, version='1.1.1',
        attr=f'{name} / Longdo Map',
        show=show, opacity=opacity
    ).add_to(m)

def render_sidebar():
    with st.sidebar:
        st.header("⚙️ การตั้งค่า")
        
        # --- Config Import/Export ---
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
                except Exception as e: st.error(f"Error: {e}")

        st.markdown("---")
        
        # --- Manual Coordinate Input ---
        with st.container():
            c1, c2 = st.columns([0.7, 0.3])
            coords_input = c1.text_input("Coords", placeholder="20.21, 100.40", label_visibility="collapsed", key="manual_coords")
            if c2.button("เพิ่ม", use_container_width=True):
                try:
                    lat_str, lng_str = coords_input.strip().split(',')
                    st.session_state.markers.append({'lat': float(lat_str), 'lng': float(lng_str), 'active': True})
                    clear_results()
                    st.rerun()
                except: st.error("Format: Lat, Lng")
            
        st.text_input("Geoapify API Key", key="api_key", type="password")
        
        # --- List Controls ---
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
                col1, col2, col3 = st.columns([0.15, 0.70, 0.15])
                is_active = col1.checkbox(" ", value=m.get('active', True), key=f"active_chk_{i}", label_visibility="collapsed")
                st.session_state.markers[i]['active'] = is_active
                
                style = f"color:{MARKER_COLORS[i % len(MARKER_COLORS)]}; font-weight:bold;" if is_active else "color:gray; text-decoration:line-through;"
                col2.markdown(f"<span style='{style}'>● จุดที่ {i+1}</span> <span style='font-size:0.8em'>({m['lat']:.4f}, {m['lng']:.4f})</span>", unsafe_allow_html=True)
                
                if col3.button("✕", key=f"del_btn_{i}"):
                    st.session_state.markers.pop(i)
                    clear_results()
                    st.rerun()

        st.markdown("---")
        
        # --- Network Analysis Panel ---
        with st.expander("🕸️ วิเคราะห์โครงข่าย (Network Analysis)", expanded=True):
            st.caption("วิเคราะห์ความสำคัญของถนน (OSMnx)")
            can_analyze = st.session_state.isochrone_data is not None
            if can_analyze:
                st.info("✅ **Scope:** พื้นที่ Travel Areas ทั้งหมด", icon="🗺️")
            else:
                st.warning("⚠️ **Scope:** กรุณาคำนวณ Isochrone ก่อน", icon="🛑")
            
            do_network = st.button("🚀 Run Network Analysis", use_container_width=True, disabled=not can_analyze)

            if st.session_state.network_data and st.session_state.network_data.get('top_node'):
                top = st.session_state.network_data['top_node']
                st.markdown("---")
                st.markdown(f"**🏆 จุดที่อยู่ตรงกลางที่สุด (Integration Center)**")
                st.caption(f"Score: {top['score']:.4f}")
                st.code(f"{top['lat']:.5f}, {top['lon']:.5f}")
                
                if st.button("➕ เพิ่มจุดนี้ลงในรายการ", use_container_width=True, type="secondary"):
                    st.session_state.markers.append({'lat': top['lat'], 'lng': top['lon'], 'active': True})
                    clear_results()
                    st.toast("เพิ่มจุดใหม่เรียบร้อย! กรุณากดคำนวณใหม่", icon="✅")
                    st.rerun()

            st.markdown("##### Layer Controls")
            st.checkbox("Show Roads (Betweenness)", key="show_betweenness")
            st.checkbox("Show Nodes (Integration)", key="show_closeness")

        st.markdown("---")
        
        # --- Map Settings ---
        with st.expander("⚙️ ตั้งค่าแผนที่ & Layers", expanded=False):
            st.selectbox("สไตล์แผนที่", list(MAP_STYLES.keys()), key="map_style_name")
            st.checkbox("🚦 การจราจร (Google Traffic)", key="show_traffic")
            st.checkbox("👥 ความหนาแน่นประชากร", key="show_population")
            
            c1, c2 = st.columns([0.65, 0.35])
            c1.checkbox("🏙️ ผังเมืองรวม", key="show_cityplan")
            if st.session_state.show_cityplan:
                c2.slider("Op.", 0.2, 1.0, key="cityplan_opacity", label_visibility="collapsed")
            
            st.checkbox("📜 รูปแปลงที่ดิน", key="show_dol")
            
            # --- New Railway Feature ---
            st.markdown("##### 🚂 โครงข่ายคมนาคม")
            st.checkbox("รถไฟทางคู่ (เด่นชัย-เชียงของ)", key="show_railway")
            
            if st.session_state.show_railway:
                st.caption("ℹ️ หากไฟล์ KML ต้นฉบับเป็น NetworkLink ต้องอัปโหลดไฟล์ที่มีพิกัดจริง (Geometry) ที่นี่")
                uploaded_kml = st.file_uploader("Upload KML รถไฟ (ถ้ามี)", type=['kml'], label_visibility="collapsed")
                
                # Logic to Process KML only when uploaded/needed
                if uploaded_kml:
                    kml_content = uploaded_kml.read()
                    parsed = parse_kml_to_geojson(kml_content)
                    if parsed:
                        if parsed.get('type') == 'NetworkLink':
                             st.warning("⚠️ ไฟล์นี้เป็น NetworkLink (Link ไปที่อื่น) ไม่สามารถแสดงผลได้โดยตรง กรุณาใช้ไฟล์ต้นฉบับที่มีเส้นทาง")
                        else:
                             st.session_state.railway_geojson = parsed
                             st.toast("โหลดข้อมูลรถไฟสำเร็จ!", icon="🚂")
                elif st.session_state.railway_geojson is None:
                    # Optional: Could put default fallback logic here if we had a static geojson URL
                    st.info("รอการอัปโหลดไฟล์ KML เพื่อแสดงเส้นทาง")

            st.markdown("##### 🚗 การเดินทาง (Isochrone)")
            st.selectbox("โหมด", list(TRAVEL_MODE_NAMES.keys()), format_func=TRAVEL_MODE_NAMES.get, key="travel_mode")
            st.multiselect("เวลา (นาที)", TIME_OPTIONS, key="time_intervals")
            
        do_calc = st.button("🧩 คำนวณหา Isochrone CBD", type="primary", use_container_width=True)
        return do_calc, do_network, active_list

def perform_calculation(active_list):
    """Business Logic: Calculate Isochrones and Intersection."""
    if not st.session_state.api_key: return st.warning("กรุณาใส่ API Key")
    if not active_list: return st.warning("กรุณาเลือกจุดอย่างน้อย 1 จุด")
    if not st.session_state.time_intervals: return st.warning("กรุณาเลือกช่วงเวลา")

    with st.spinner('กำลังคำนวณ Isochrone...'):
        all_features = []
        ranges_str = ",".join(str(t * 60) for t in sorted(st.session_state.time_intervals))
        
        for act_idx, (orig_idx, marker) in enumerate(active_list):
            features = fetch_api_data_cached(
                st.session_state.api_key, st.session_state.travel_mode, 
                ranges_str, marker['lat'], marker['lng']
            )
            if features:
                for f in features:
                    f['properties'].update({
                        'travel_time_minutes': f['properties'].get('value', 0) / 60,
                        'original_index': orig_idx,
                        'active_index': act_idx
                    })
                    all_features.append(f)
        
        if all_features:
            st.session_state.isochrone_data = {"type": "FeatureCollection", "features": all_features}
            cbd_geom = calculate_intersection(all_features, len(active_list))
            
            if cbd_geom:
                st.session_state.intersection_data = {
                    "type": "FeatureCollection", 
                    "features": [{"type": "Feature", "geometry": cbd_geom, "properties": {"type": "cbd"}}]
                }
                st.success("✅ พบพื้นที่ CBD!")
            else:
                st.session_state.intersection_data = None
                st.warning("⚠️ ไม่พบพื้นที่ทับซ้อน")

def perform_network_analysis():
    """Business Logic: Execute Network Analysis."""
    if not st.session_state.isochrone_data: return st.error("No Isochrone data found.")
    
    with st.spinner('กำลังรวมพื้นที่และวิเคราะห์โครงข่ายถนน (OSMnx)... อาจใช้เวลาสักครู่'):
        try:
            feats = st.session_state.isochrone_data.get('features', [])
            polys = [shape(f['geometry']) for f in feats]
            if not polys: return st.error("No polygons to analyze.")
            combined_polygon = unary_union(polys)
            
            result = process_network_analysis(combined_polygon.wkt)
            
            if "error" in result:
                st.error(f"Analysis Failed: {result['error']}")
            else:
                st.session_state.network_data = result
                score_info = f"Score: {result['top_node']['score']:.4f}" if result.get('top_node') else ""
                st.toast(f"Analysis Completed! {score_info}", icon="🏆")
                
        except Exception as e:
            st.error(f"Processing Error: {e}")

def render_map():
    """Render Folium Map with all layers."""
    style_conf = MAP_STYLES[st.session_state.map_style_name]
    center = [st.session_state.markers[-1]['lat'], st.session_state.markers[-1]['lng']] if st.session_state.markers else [DEFAULT_CONFIG['LAT'], DEFAULT_CONFIG['LON']]
    
    m = folium.Map(location=center, zoom_start=14, tiles=style_conf["tiles"], attr=style_conf["attr"])

    # --- Overlays ---
    if st.session_state.show_traffic:
        folium.TileLayer(
            tiles="https://mt1.google.com/vt?lyrs=h,traffic&x={x}&y={y}&z={z}",
            attr="Google Traffic", name="Google Traffic", overlay=True
        ).add_to(m)

    # --- Railway Layer (New) ---
    if st.session_state.show_railway and st.session_state.railway_geojson:
        folium.GeoJson(
            st.session_state.railway_geojson,
            name="Railway (Den Chai - Chiang Khong)",
            style_function=lambda x: {
                'color': 'black', 'weight': 3, 'dashArray': '10,5', 'opacity': 0.8
            },
            tooltip=folium.GeoJsonTooltip(fields=['name'], aliases=['Station/Line:'], localize=True)
        ).add_to(m)
        # Add white overlay for striped effect
        folium.GeoJson(
             st.session_state.railway_geojson,
             name="Railway Overlay",
             style_function=lambda x: {
                 'color': 'white', 'weight': 1.5, 'dashArray': '10,5', 'opacity': 0.8
             }
        ).add_to(m)

    # --- Network Analysis Layers ---
    net_data = st.session_state.network_data
    if net_data:
        if st.session_state.show_betweenness and net_data.get("edges"):
            folium.GeoJson(
                net_data["edges"], name="Road Betweenness",
                style_function=lambda x: {
                    'color': x['properties']['color'],
                    'weight': x['properties']['stroke_weight'],
                    'opacity': 0.8
                },
                tooltip=folium.GeoJsonTooltip(fields=['betweenness'], aliases=['Betweenness Score:'], localize=True)
            ).add_to(m)
        
        if st.session_state.show_closeness and net_data.get("nodes"):
            folium.GeoJson(
                net_data["nodes"], name="Node Integration",
                marker=folium.CircleMarker(),
                style_function=lambda x: {
                    'fillColor': x['properties']['color'], 'color': '#000000',
                    'weight': 1, 'radius': x['properties']['radius'], 'fillOpacity': 0.9
                },
                tooltip=folium.GeoJsonTooltip(fields=['closeness'], aliases=['Integration Score:'], localize=True)
            ).add_to(m)
        
        if net_data.get("top_node"):
            top = net_data["top_node"]
            folium.Marker(
                [top['lat'], top['lon']], popup=f"🏆 Center (Score: {top['score']:.4f})",
                icon=folium.Icon(color='orange', icon='star', prefix='fa'), tooltip="จุดที่อยู่ตรงกลางที่สุด"
            ).add_to(m)

    # --- Isochrones ---
    if st.session_state.isochrone_data:
        folium.GeoJson(
            st.session_state.isochrone_data, name='Travel Areas',
            style_function=lambda x: {
                'fillColor': get_fill_color(x['properties']['travel_time_minutes'], st.session_state.colors),
                'color': get_border_color(x['properties']['original_index']),
                'weight': 1, 'fillOpacity': 0.2
            }
        ).add_to(m)

    # --- CBD ---
    if st.session_state.intersection_data:
        folium.GeoJson(
            st.session_state.intersection_data, name='CBD Zone',
            style_function=lambda x: {'fillColor': '#FFD700', 'color': '#FF8C00', 'weight': 3, 'fillOpacity': 0.6, 'dashArray': '5, 5'}
        ).add_to(m)

    # --- WMS Layers ---
    add_wms_layer(m, 'thailand_population', 'ความหนาแน่นประชากร', st.session_state.show_population)
    add_wms_layer(m, 'cityplan_dpt', 'ผังเมืองรวม', st.session_state.show_cityplan, opacity=st.session_state.cityplan_opacity)
    add_wms_layer(m, 'dol', 'รูปแปลงที่ดิน', st.session_state.show_dol)

    # --- Markers ---
    for i, marker in enumerate(st.session_state.markers):
        active = marker.get('active', True)
        folium.Marker(
            [marker['lat'], marker['lng']], popup=f"จุดที่ {i+1}",
            icon=folium.Icon(color=MARKER_COLORS[i % len(MARKER_COLORS)] if active else "gray", icon="map-marker" if active else "ban", prefix='fa')
        ).add_to(m)

    folium.LayerControl().add_to(m)
    return st_folium(m, height=750, use_container_width=True, key="main_map")

# ============================================================================
# 5. MAIN EXECUTION
# ============================================================================

def main():
    st.set_page_config(**PAGE_CONFIG)
    st.markdown("""<style>.block-container { padding-top: 2rem; padding-bottom: 0rem; } h1 { margin-bottom: 0px; } div[data-testid="stHorizontalBlock"] button { padding: 0rem 0.5rem; }</style>""", unsafe_allow_html=True)
    
    initialize_session_state()
    
    do_calc, do_net, active_list = render_sidebar()
    
    if do_calc:
        perform_calculation(active_list)
        
    if do_net:
        perform_network_analysis()
        
    map_output = render_map()
    
    if map_output and map_output.get('last_clicked'):
        clicked = map_output['last_clicked']
        last_marker = st.session_state.markers[-1] if st.session_state.markers else None
        if not last_marker or abs(clicked['lat'] - last_marker['lat']) > 1e-5 or abs(clicked['lng'] - last_marker['lng']) > 1e-5:
            st.session_state.markers.append({'lat': clicked['lat'], 'lng': clicked['lng'], 'active': True})
            clear_results()
            st.rerun()

if __name__ == "__main__":
    main()
