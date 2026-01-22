import streamlit as st
import folium
from streamlit_folium import st_folium
import requests
from shapely.geometry import shape, mapping
import json
from typing import List, Dict, Any, Optional

# ============================================================================
# 1. CONSTANTS & CONFIGURATION
# ============================================================================  

PAGE_CONFIG = {
    "page_title": "Geoapify & Longdo Map (Chiang Khong CBD)",
    "page_icon": "🌍",
    "layout": "wide"
}

DEFAULT_LAT = 20.219443
DEFAULT_LON = 100.403630
# ใส่ Key ที่คุณแก้ Domain แล้วที่นี่
DEFAULT_LONGDO_KEY = "d319a3926ede7cab2d778899e3d9661a" 
DEFAULT_GEOAPIFY_KEY = "4eefdfb0b0d349e595595b9c03a69e3d" # หรือ Key Geoapify ของคุณ

MARKER_COLORS = ['red', 'blue', 'green', 'purple', 'orange', 'black']
MAP_STYLES = {
    "OpenStreetMap (มาตรฐาน)": {"tiles": "OpenStreetMap", "attr": None},
    "Google Maps (ผสม/Hybrid)": {"tiles": "https://mt1.google.com/vt/lyrs=y&x={x}&y={y}&z={z}", "attr": "Google Maps"},
}

TRAVEL_MODE_NAMES = {"drive": "🚗 ขับรถ", "walk": "🚶 เดินเท้า"}
TIME_OPTIONS = [5, 10, 15, 20, 30]

# ============================================================================
# 2. HELPER FUNCTIONS
# ============================================================================

def get_fill_color(minutes: float, colors_config: Dict[str, str]) -> str:
    if minutes <= 10: return colors_config['step1']
    elif minutes <= 20: return colors_config['step2']
    elif minutes <= 30: return colors_config['step3']
    else: return colors_config['step4']

def calculate_intersection(features: List[Dict], num_active_markers: int) -> Optional[Dict]:
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
    except Exception: return None

@st.cache_data(show_spinner=False, ttl=3600)
def fetch_api_data_cached(api_key: str, travel_mode: str, ranges_str: str, marker_lat: float, marker_lon: float) -> Optional[List[Dict]]:
    url = "https://api.geoapify.com/v1/isoline"
    params = {"lat": marker_lat, "lon": marker_lon, "type": "time", "mode": travel_mode, "range": ranges_str, "apiKey": api_key}
    try:
        response = requests.get(url, params=params, timeout=10)
        if response.status_code == 200: return response.json().get('features', [])
        return None
    except Exception: return None

# ============================================================================
# 3. STATE & APP
# ============================================================================

st.set_page_config(**PAGE_CONFIG)
st.markdown("""<style>.block-container { padding-top: 2rem; padding-bottom: 0rem; } h1 { margin-bottom: 0px; }</style>""", unsafe_allow_html=True)

if 'markers' not in st.session_state:
    st.session_state.markers = [{'lat': DEFAULT_LAT, 'lng': DEFAULT_LON, 'active': True}]
    st.session_state.colors = {'step1': '#2A9D8F', 'step2': '#E9C46A', 'step3': '#F4A261', 'step4': '#D62828'}
    st.session_state.geoapify_key = DEFAULT_GEOAPIFY_KEY
    st.session_state.longdo_key = DEFAULT_LONGDO_KEY
    st.session_state.map_style_name = list(MAP_STYLES.keys())[0]
    st.session_state.travel_mode = "drive"
    st.session_state.time_intervals = [5]
    st.session_state.isochrone_data = None
    st.session_state.intersection_data = None

# --- SIDEBAR ---
with st.sidebar:
    st.header("⚙️ ตั้งค่า")
    
    # API Keys
    with st.expander("🔑 API Keys", expanded=True):
        st.session_state.geoapify_key = st.text_input("Geoapify Key", value=st.session_state.geoapify_key, type="password")
        st.session_state.longdo_key = st.text_input("Longdo Key (WMS)", value=st.session_state.longdo_key, type="password")
        if st.session_state.longdo_key:
            st.caption("✅ พร้อมใช้งาน (โหมด WMS)")

    # Marker Control
    c1, c2 = st.columns(2)
    if c1.button("❌ ลบจุดล่าสุด", use_container_width=True):
        if st.session_state.markers:
            st.session_state.markers.pop()
            st.rerun()
    if c2.button("🔄 รีเซ็ต", use_container_width=True):
        st.session_state.markers = [{'lat': DEFAULT_LAT, 'lng': DEFAULT_LON, 'active': True}]
        st.session_state.isochrone_data = None
        st.session_state.intersection_data = None
        st.rerun()

    # Calculate
    st.markdown("---")
    st.selectbox("โหมด", list(TRAVEL_MODE_NAMES.keys()), key="travel_mode")
    st.multiselect("เวลา (นาที)", TIME_OPTIONS, key="time_intervals")
    do_calc = st.button("🚀 คำนวณพื้นที่", type="primary", use_container_width=True)

# Calculation Logic
if do_calc:
    with st.spinner('กำลังคำนวณ...'):
        all_features = []
        ranges_str = ",".join([str(t*60) for t in sorted(st.session_state.time_intervals)])
        active_list = [(i, m) for i, m in enumerate(st.session_state.markers) if m.get('active', True)]
        
        for active_idx, (orig_idx, marker) in enumerate(active_list):
            feats = fetch_api_data_cached(st.session_state.geoapify_key, st.session_state.travel_mode, ranges_str, marker['lat'], marker['lng'])
            if feats:
                for f in feats:
                    f['properties'].update({'travel_time_minutes': f['properties'].get('value',0)/60, 'original_index': orig_idx, 'active_index': active_idx})
                    all_features.append(f)
        
        if all_features:
            st.session_state.isochrone_data = {"type": "FeatureCollection", "features": all_features}
            cbd = calculate_intersection(all_features, len(active_list))
            st.session_state.intersection_data = {"type": "FeatureCollection", "features": [{"type": "Feature", "geometry": cbd, "properties": {"type": "cbd"}}]} if cbd else None

# --- MAP RENDERING ---
style_cfg = MAP_STYLES[st.session_state.map_style_name]
center = [st.session_state.markers[-1]['lat'], st.session_state.markers[-1]['lng']] if st.session_state.markers else [DEFAULT_LAT, DEFAULT_LON]
m = folium.Map(location=center, zoom_start=15, tiles=style_cfg["tiles"], attr=style_cfg["attr"])

# 1. แสดง Isochrone
if st.session_state.isochrone_data:
    folium.GeoJson(st.session_state.isochrone_data, name='Isochrones', style_function=lambda x: {'fillColor': get_fill_color(x['properties']['travel_time_minutes'], st.session_state.colors), 'color': 'none', 'fillOpacity': 0.2}).add_to(m)

# 2. แสดง CBD
if st.session_state.intersection_data:
    folium.GeoJson(st.session_state.intersection_data, name='CBD Area', style_function=lambda x: {'fillColor': '#FFD700', 'color': '#FF8C00', 'weight': 3, 'fillOpacity': 0.6}).add_to(m)

# 3. แสดงชั้นข้อมูลกรมที่ดิน (WMS) -- ไฮไลท์ของรอบนี้!
if st.session_state.longdo_key:
    wms_url = f"https://ms.longdo.com/mapproxy/service/wms?apikey={st.session_state.longdo_key}"
    folium.raster_layers.WmsTileLayer(
        url=wms_url,
        layers="dol_parcels",
        fmt="image/png",
        transparent=True,
        attr="Longdo Map / กรมที่ดิน",
        name="📜 แปลงที่ดิน (WMS)",
        overlay=True,
        control=True,
        show=True,
        version="1.1.1"
    ).add_to(m)

# Markers
for i, marker in enumerate(st.session_state.markers):
    folium.Marker([marker['lat'], marker['lng']], popup=f"จุดที่ {i+1}").add_to(m)

folium.LayerControl(collapsed=False).add_to(m)
st_folium(m, height=700, use_container_width=True)
