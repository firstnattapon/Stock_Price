import streamlit as st
import folium
from streamlit_folium import st_folium
import requests
from shapely.geometry import shape, mapping
import json
from typing import List, Dict, Any, Optional, Tuple

# ============================================================================
# 1. CONSTANTS & CONFIGURATION
# ============================================================================

PAGE_CONFIG = {
    "page_title": "Geoapify Map + DOL Lands",
    "page_icon": "🌍",
    "layout": "wide"
}

# --- Geoapify Configuration ---
DEFAULT_JSON_URL = "https://raw.githubusercontent.com/firstnattapon/Stock_Price/refs/heads/main/Geoapify_Map/geoapify_cbd_project.json"
DEFAULT_LAT = 20.219443
DEFAULT_LON = 100.403630
DEFAULT_GEOAPIFY_KEY = "4eefdfb0b0d349e595595b9c03a69e3d"

# --- Longdo / Department of Lands Configuration ---
LONGDO_API_KEY = "0a999afb0da60c5c45d010e9c171ffc8"
LONGDO_WMS_URL = f"https://ms.longdo.com/mapproxy/service?key={LONGDO_API_KEY}"

MARKER_COLORS = ['red', 'blue', 'green', 'purple', 'orange', 'black', 'pink', 'cadetblue']
HEX_COLORS = ['#D63E2A', '#38AADD', '#72B026', '#D252B9', '#F69730', '#333333', '#FF91EA', '#436978']

MAP_STYLES = {
    # ... (Group 1: Standard)
    "OpenStreetMap (มาตรฐาน)": {"tiles": "OpenStreetMap", "attr": None},
    "Google Maps (ผสม/Hybrid)": {"tiles": "https://mt1.google.com/vt/lyrs=y&x={x}&y={y}&z={z}", "attr": "Google Maps"},
    
    # ... (Group 2: Clean/Light for Data)
    "Esri Light Gray (แนะนำสำหรับดูที่ดิน)": {
        "tiles": "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}",
        "attr": "Tiles &copy; Esri"
    },
    
    # ... (Group 3: Satellite)
    "Esri Satellite (ดาวเทียมชัด)": {
        "tiles": "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        "attr": "Tiles &copy; Esri &mdash; Source: Esri"
    },

    # ... (Others kept for compatibility)
    "Google Maps (ถนน)": {"tiles": "https://mt1.google.com/vt/lyrs=m&x={x}&y={y}&z={z}", "attr": "Google Maps"},
    "CartoDB Positron": {"tiles": "CartoDB positron", "attr": None},
    "CartoDB Dark Matter": {"tiles": "CartoDB dark_matter", "attr": None},
}

TRAVEL_MODE_NAMES = {
    "drive": "🚗 ขับรถ",
    "walk": "🚶 เดินเท้า",
    "bicycle": "🚲 ปั่นจักรยาน",
    "transit": "🚌 ขนส่งสาธารณะ"
}

TIME_OPTIONS = [5, 10, 15, 20, 30, 45, 60]

# ============================================================================
# 2. HELPER FUNCTIONS
# ============================================================================

def get_fill_color(minutes: float, colors_config: Dict[str, str]) -> str:
    if minutes <= 10: return colors_config['step1']
    elif minutes <= 20: return colors_config['step2']
    elif minutes <= 30: return colors_config['step3']
    else: return colors_config['step4']

def get_border_color(original_marker_idx: Optional[int]) -> str:
    if original_marker_idx is None: return '#3388ff'
    return HEX_COLORS[original_marker_idx % len(HEX_COLORS)]

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
    except Exception:
        return None

@st.cache_data(show_spinner=False, ttl=3600)
def fetch_api_data_cached(api_key: str, travel_mode: str, ranges_str: str, marker_lat: float, marker_lon: float) -> Optional[List[Dict]]:
    url = "https://api.geoapify.com/v1/isoline"
    params = {"lat": marker_lat, "lon": marker_lon, "type": "time", "mode": travel_mode, "range": ranges_str, "apiKey": api_key}
    try:
        response = requests.get(url, params=params, timeout=10)
        return response.json().get('features', []) if response.status_code == 200 else None
    except Exception:
        return None

# ============================================================================
# 3. STATE MANAGEMENT
# ============================================================================

def initialize_session_state():
    defaults = {
        'markers': [{'lat': DEFAULT_LAT, 'lng': DEFAULT_LON, 'active': True}],
        'isochrone_data': None,
        'intersection_data': None,
        'colors': {'step1': '#2A9D8F', 'step2': '#E9C46A', 'step3': '#F4A261', 'step4': '#D62828'},
        'api_key': DEFAULT_GEOAPIFY_KEY,
        'map_style_name': "Esri Light Gray (แนะนำสำหรับดูที่ดิน)", # Default to a clean map
        'travel_mode': "drive",
        'time_intervals': [5],
        'show_dol_layer': False # Checkbox state for DOL layer
    }
    
    # Load from default JSON if markers empty
    if 'markers' not in st.session_state:
        try:
            response = requests.get(DEFAULT_JSON_URL, timeout=3)
            if response.status_code == 200:
                data = response.json()
                defaults.update({k: data.get(k, v) for k, v in defaults.items()})
        except Exception: pass

    for k, v in defaults.items():
        if k not in st.session_state: st.session_state[k] = v
    
    # Ensure active key existence
    for m in st.session_state.markers:
        if 'active' not in m: m['active'] = True

def get_active_markers() -> List[Tuple[int, Dict]]:
    return [(i, m) for i, m in enumerate(st.session_state.markers) if m.get('active', True)]

# ============================================================================
# 4. MAIN APP
# ============================================================================

st.set_page_config(**PAGE_CONFIG)
st.markdown("""<style>.block-container { padding-top: 2rem; padding-bottom: 0rem; } h1 { margin-bottom: 0px; } div[data-testid="stHorizontalBlock"] button { padding: 0rem 0.5rem; }</style>""", unsafe_allow_html=True)

initialize_session_state()

# --- SIDEBAR ---
with st.sidebar:
    st.header("⚙️ การตั้งค่า")
    
    # 1. Manual Add
    with st.container():
        c1, c2 = st.columns([0.7, 0.3])
        coords = c1.text_input("Coords", placeholder="20.21, 100.40", label_visibility="collapsed", key="manual")
        if c2.button("เพิ่ม", use_container_width=True):
            try:
                parts = coords.replace(" ", "").split(',')
                lat, lng = float(parts[0]), float(parts[1])
                st.session_state.markers.append({'lat': lat, 'lng': lng, 'active': True})
                st.session_state.isochrone_data = None; st.session_state.intersection_data = None
                st.rerun()
            except: st.error("พิกัดผิด")
            
    st.markdown("---")
    st.text_input("Geoapify API Key", key="api_key", type="password")
    
    # 2. Controls
    c1, c2 = st.columns(2)
    if c1.button("❌ ลบจุดล่าสุด", use_container_width=True) and st.session_state.markers:
        st.session_state.markers.pop()
        st.session_state.isochrone_data = None; st.session_state.intersection_data = None
        st.rerun()
    if c2.button("🔄 รีเซ็ต", use_container_width=True):
        st.session_state.markers = [{'lat': DEFAULT_LAT, 'lng': DEFAULT_LON, 'active': True}]
        st.session_state.isochrone_data = None; st.session_state.intersection_data = None
        st.rerun()

    # 3. Marker List
    active_list = get_active_markers()
    st.write(f"📍 คำนวณ: **{len(active_list)}** / {len(st.session_state.markers)}")
    if st.session_state.markers:
        st.markdown("---")
        for i, m in enumerate(st.session_state.markers):
            is_active = st.checkbox(f"จุดที่ {i+1}", value=m.get('active', True), key=f"act_{i}")
            st.session_state.markers[i]['active'] = is_active
            if not is_active: st.caption(f"Skipped: ({m['lat']:.4f}, {m['lng']:.4f})")

    # 4. Settings
    st.markdown("---")
    with st.expander("⚙️ ตั้งค่าแผนที่ & สี", expanded=True):
        st.selectbox("สไตล์แผนที่", list(MAP_STYLES.keys()), key="map_style_name")
        
        # --- NEW: DOL Control in Sidebar ---
        st.markdown("##### 📜 ข้อมูลกรมที่ดิน")
        st.checkbox("แสดงเส้นแบ่งโฉนดที่ดิน (DOL)", value=False, key="show_dol_layer", help="ข้อมูลจาก Longdo Map / กรมที่ดิน")
        
        st.markdown("##### 🚗 การเดินทาง")
        st.selectbox("โหมด", list(TRAVEL_MODE_NAMES.keys()), format_func=lambda x: TRAVEL_MODE_NAMES[x], key="travel_mode")
        st.multiselect("เวลา (นาที)", TIME_OPTIONS, key="time_intervals")
        
    do_calculate = st.button("🚀 คำนวณหา CBD", type="primary", use_container_width=True)

# --- CALCULATION LOGIC ---
if do_calculate:
    if not st.session_state.api_key: st.warning("ใส่ API Key")
    elif not active_list: st.warning("เลือกจุด")
    elif not st.session_state.time_intervals: st.warning("เลือกเวลา")
    else:
        with st.spinner('กำลังวิเคราะห์...'):
            all_feats = []
            ranges = ",".join([str(t*60) for t in sorted(st.session_state.time_intervals)])
            for act_idx, (orig_idx, m) in enumerate(active_list):
                feats = fetch_api_data_cached(st.session_state.api_key, st.session_state.travel_mode, ranges, m['lat'], m['lng'])
                if feats:
                    for f in feats:
                        f['properties'].update({'travel_time_minutes': f['properties'].get('value',0)/60, 'original_index': orig_idx, 'active_index': act_idx})
                        all_feats.append(f)
            
            if all_feats:
                st.session_state.isochrone_data = {"type": "FeatureCollection", "features": all_feats}
                cbd = calculate_intersection(all_feats, len(active_list))
                st.session_state.intersection_data = {"type": "FeatureCollection", "features": [{"type": "Feature", "geometry": cbd, "properties": {"type": "cbd"}}]} if cbd else None
                if cbd: st.success("✅ พบพื้นที่ CBD!")
                else: st.warning("⚠️ ไม่พบพื้นที่ทับซ้อน")

# ============================================================================
# MAP RENDERING
# ============================================================================

style = MAP_STYLES[st.session_state.map_style_name]
center = [st.session_state.markers[-1]['lat'], st.session_state.markers[-1]['lng']] if st.session_state.markers else [DEFAULT_LAT, DEFAULT_LON]

m = folium.Map(location=center, zoom_start=14, tiles=style["tiles"], attr=style["attr"])

# 1. Add Isochrones (Base Analysis)
if st.session_state.isochrone_data:
    folium.GeoJson(
        st.session_state.isochrone_data, name='Travel Areas',
        style_function=lambda x: {
            'fillColor': get_fill_color(x['properties']['travel_time_minutes'], st.session_state.colors),
            'color': get_border_color(x['properties']['original_index']),
            'weight': 1, 'fillOpacity': 0.2
        },
        tooltip=folium.GeoJsonTooltip(['travel_time_minutes'], aliases=['นาที:'])
    ).add_to(m)

# 2. Add CBD Intersection (Highlight)
if st.session_state.intersection_data:
    folium.GeoJson(
        st.session_state.intersection_data, name='CBD Zone',
        style_function=lambda x: {'fillColor': '#FFD700', 'color': '#FF8C00', 'weight': 3, 'fillOpacity': 0.6, 'dashArray': '5, 5'},
        tooltip="🏆 Potential CBD"
    ).add_to(m)

# 3. Add DOL Layer (Overlay on top of analysis but below markers)
#    Note: Added 'show' parameter controlled by session state or LayerControl
dol_layer = folium.WmsTileLayer(
    url=LONGDO_WMS_URL,
    layers='dol',
    name='Department of Lands (รูปแปลงที่ดิน)',
    fmt='image/png',       # format
    transparent=True,      # Important: Allows seeing map below
    version='1.1.1',
    attr='Department of Lands / Longdo Map',
    show=st.session_state.show_dol_layer  # Controlled by sidebar checkbox
)
dol_layer.add_to(m)

# 4. Add Markers
for i, marker in enumerate(st.session_state.markers):
    is_active = marker.get('active', True)
    folium.Marker(
        [marker['lat'], marker['lng']],
        popup=f"จุดที่ {i+1}",
        icon=folium.Icon(color=MARKER_COLORS[i%8] if is_active else "gray", icon="map-marker" if is_active else "ban", prefix='fa'),
        opacity=1.0 if is_active else 0.5
    ).add_to(m)

# 5. Controls
folium.LayerControl().add_to(m)

# 6. Render
map_out = st_folium(m, height=750, use_container_width=True, key="main_map")

# 7. Click Handler
if map_out and map_out.get('last_clicked'):
    clat, clng = map_out['last_clicked']['lat'], map_out['last_clicked']['lng']
    # Check duplicate click (simple debounce)
    if not st.session_state.markers or (abs(clat - st.session_state.markers[-1]['lat']) > 1e-5):
        st.session_state.markers.append({'lat': clat, 'lng': clng, 'active': True})
        st.session_state.isochrone_data = None; st.session_state.intersection_data = None
        st.rerun()
