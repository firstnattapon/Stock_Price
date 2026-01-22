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
    "page_title": "Geoapify & Longdo Map (Chiang Khong CBD)",
    "page_icon": "🌍",
    "layout": "wide"
}

DEFAULT_JSON_URL = "https://raw.githubusercontent.com/firstnattapon/Stock_Price/refs/heads/main/Geoapify_Map/geoapify_cbd_project.json"

DEFAULT_LAT = 20.219443
DEFAULT_LON = 100.403630
DEFAULT_GEOAPIFY_KEY = "4eefdfb0b0d349e595595b9c03a69e3d"
# คุณสามารถใส่ Default Longdo Key ที่นี่ได้ถ้ามี
DEFAULT_LONGDO_KEY = "" 

MARKER_COLORS = ['red', 'blue', 'green', 'purple', 'orange', 'black', 'pink', 'cadetblue']
HEX_COLORS = ['#D63E2A', '#38AADD', '#72B026', '#D252B9', '#F69730', '#333333', '#FF91EA', '#436978']

MAP_STYLES = {
    "OpenStreetMap (มาตรฐาน)": {"tiles": "OpenStreetMap", "attr": None},
    "Google Maps (ผสม/Hybrid)": {"tiles": "https://mt1.google.com/vt/lyrs=y&x={x}&y={y}&z={z}", "attr": "Google Maps"},
    "CartoDB Positron (สีอ่อน/สะอาด)": {"tiles": "CartoDB positron", "attr": None},
    "Esri Satellite (ดาวเทียมชัด)": {"tiles": "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}", "attr": "Tiles &copy; Esri"},
    "Esri World Topo (ภูมิประเทศ)": {"tiles": "https://server.arcgisonline.com/ArcGIS/rest/services/World_Topo_Map/MapServer/tile/{z}/{y}/{x}", "attr": "Tiles &copy; Esri"},
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
    except Exception as e:
        st.error(f"Intersection error: {e}")
        return None

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
# 3. STATE MANAGEMENT
# ============================================================================

def initialize_session_state():
    defaults = {
        'markers': [{'lat': DEFAULT_LAT, 'lng': DEFAULT_LON, 'active': True}],
        'isochrone_data': None,
        'intersection_data': None,
        'colors': {'step1': '#2A9D8F', 'step2': '#E9C46A', 'step3': '#F4A261', 'step4': '#D62828'},
        'geoapify_key': DEFAULT_GEOAPIFY_KEY,
        'longdo_key': DEFAULT_LONGDO_KEY,  # เพิ่ม State สำหรับ Longdo Key
        'map_style_name': list(MAP_STYLES.keys())[0],
        'travel_mode': "drive",
        'time_intervals': [5]
    }

    if 'markers' not in st.session_state:
        try:
            response = requests.get(DEFAULT_JSON_URL, timeout=3)
            if response.status_code == 200:
                data = response.json()
                # Load existing keys but prefer defaults if missing
                defaults.update({k: data.get(k, v) for k, v in defaults.items()})
        except Exception: pass

    for key, default_val in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = default_val
    
    for m in st.session_state.markers:
        if 'active' not in m: m['active'] = True

def get_active_markers() -> List[Tuple[int, Dict]]:
    return [(i, m) for i, m in enumerate(st.session_state.markers) if m.get('active', True)]

# ============================================================================
# 4. MAIN APP
# ============================================================================

st.set_page_config(**PAGE_CONFIG)
st.markdown("""<style>.block-container { padding-top: 2rem; padding-bottom: 0rem; } h1 { margin-bottom: 0px; }</style>""", unsafe_allow_html=True)

initialize_session_state()

# --- SIDEBAR ---
with st.sidebar:
    st.header("⚙️ การตั้งค่า")
    
    # 1. Manual Add
    with st.container():
        c1, c2 = st.columns([0.7, 0.3])
        coords = c1.text_input("Coords", placeholder="20.21, 100.40", label_visibility="collapsed", key="manual_coords_input")
        if c2.button("เพิ่ม", use_container_width=True):
            if coords:
                try:
                    parts = coords.replace(" ", "").split(',')
                    if len(parts) == 2:
                        lat, lng = float(parts[0]), float(parts[1])
                        st.session_state.markers.append({'lat': lat, 'lng': lng, 'active': True})
                        st.session_state.isochrone_data = None
                        st.session_state.intersection_data = None
                        st.rerun()
                except: st.error("พิกัดผิด")
    
    st.markdown("---")
    
    # 2. API Keys Section
    with st.expander("🔑 API Keys", expanded=True):
        st.session_state.geoapify_key = st.text_input("Geoapify Key", value=st.session_state.geoapify_key, type="password")
        
        # --- NEW: Longdo API Key Input ---
        st.session_state.longdo_key = st.text_input(
            "Longdo Map Key", 
            value=st.session_state.longdo_key, 
            type="password",
            help="ใส่ Key เพื่อแสดงชั้นข้อมูลแปลงที่ดิน (สมัครฟรีที่ map.longdo.com)"
        )
        if not st.session_state.longdo_key:
            st.caption("⚠️ ต้องมี Longdo Key เพื่อดูแปลงที่ดิน")
    
    st.markdown("---")
    
    # 3. Control Buttons
    c1, c2 = st.columns(2)
    if c1.button("❌ ลบจุดล่าสุด", use_container_width=True):
        if st.session_state.markers:
            st.session_state.markers.pop()
            st.session_state.isochrone_data = None
            st.session_state.intersection_data = None
            st.rerun()
    if c2.button("🔄 รีเซ็ต", use_container_width=True):
        st.session_state.markers = [{'lat': DEFAULT_LAT, 'lng': DEFAULT_LON, 'active': True}]
        st.session_state.isochrone_data = None
        st.session_state.intersection_data = None
        st.rerun()

    # 4. Marker List
    if st.session_state.markers:
        st.markdown("---")
        for i, m in enumerate(st.session_state.markers):
            col_chk, col_txt, col_del = st.columns([0.15, 0.70, 0.15])
            is_active = col_chk.checkbox(" ", value=m.get('active', True), key=f"active_chk_{i}")
            st.session_state.markers[i]['active'] = is_active
            style = f"color:{MARKER_COLORS[i%len(MARKER_COLORS)]}; font-weight:bold;" if is_active else "color:gray;"
            col_txt.markdown(f"<span style='{style}'>● จุดที่ {i+1}</span>", unsafe_allow_html=True)
            if col_del.button("✕", key=f"del_btn_{i}"):
                st.session_state.markers.pop(i)
                st.rerun()

    # 5. Settings
    with st.expander("🎨 ตั้งค่าแผนที่", expanded=False):
        st.selectbox("สไตล์", list(MAP_STYLES.keys()), key="map_style_name")
        st.selectbox("โหมดเดินทาง", list(TRAVEL_MODE_NAMES.keys()), format_func=lambda x: TRAVEL_MODE_NAMES[x], key="travel_mode")
        st.multiselect("เวลา (นาที)", TIME_OPTIONS, key="time_intervals")

    # 6. Calculate
    st.markdown("---")
    do_calc = st.button("🚀 คำนวณพื้นที่ (CBD)", type="primary", use_container_width=True)

# ============================================================================
# CALCULATION LOGIC
# ============================================================================

if do_calc:
    active_list = get_active_markers()
    if not st.session_state.geoapify_key: st.warning("⚠️ ขาด Geoapify Key")
    elif not active_list: st.warning("⚠️ เลือกจุดก่อน")
    elif not st.session_state.time_intervals: st.warning("⚠️ เลือกเวลา")
    else:
        with st.spinner('กำลังคำนวณ...'):
            all_features = []
            ranges_str = ",".join([str(t*60) for t in sorted(st.session_state.time_intervals)])
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
                if cbd: st.success("✅ พบพื้นที่ร่วม!")
                else: st.warning("ไม่พบพื้นที่ทับซ้อน")

# ============================================================================
# MAP RENDERING
# ============================================================================

style_cfg = MAP_STYLES[st.session_state.map_style_name]
center = [st.session_state.markers[-1]['lat'], st.session_state.markers[-1]['lng']] if st.session_state.markers else [DEFAULT_LAT, DEFAULT_LON]

m = folium.Map(location=center, zoom_start=11, tiles=style_cfg["tiles"], attr=style_cfg["attr"])

# --- 1. แสดง Isochrone Areas ---
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

# --- 2. แสดง CBD Intersection ---
if st.session_state.intersection_data:
    folium.GeoJson(
        st.session_state.intersection_data, name='CBD Area (Overlap)',
        style_function=lambda x: {'fillColor': '#FFD700', 'color': '#FF8C00', 'weight': 3, 'fillOpacity': 0.6, 'dashArray': '5, 5'},
        tooltip="🏆 พื้นที่ศักยภาพ (CBD)"
    ).add_to(m)

# --- 3. เพิ่มชั้นข้อมูลแปลงที่ดินกรมที่ดิน (Longdo Map / DOL Layer) ---
if st.session_state.longdo_key:
    # URL สำหรับชั้นข้อมูลแปลงที่ดิน (dol_parcels) แบบ WMTS/XYZ
    # ใช้ Mode: GoogleMapsCompatible เพื่อให้ตรงกับ Projection ของ Folium
    dol_url = f"https://ms.longdo.com/mapproxy/service/render/wmts/dol_parcels/GoogleMapsCompatible/{{z}}/{{x}}/{{y}}.png?apikey={st.session_state.longdo_key}"
    
    folium.TileLayer(
        tiles=dol_url,
        attr="Longdo Map / กรมที่ดิน",
        name="📜 แปลงที่ดิน (กรมที่ดิน)",
        overlay=True,  # ให้ซ้อนทับแผนที่ฐาน
        control=True,  # แสดงในปุ่มเลือก Layer
        opacity=0.7,   # ปรับความโปร่งใสให้เห็นถนนด้านล่าง
        show=False     # ค่าเริ่มต้นปิดไว้ (ผู้ใช้ต้องติ๊กเปิดเอง)
    ).add_to(m)

# --- 4. แสดง Markers ---
for i, marker in enumerate(st.session_state.markers):
    is_active = marker.get('active', True)
    folium.Marker(
        [marker['lat'], marker['lng']],
        popup=f"จุดที่ {i+1}",
        icon=folium.Icon(color=MARKER_COLORS[i % len(MARKER_COLORS)] if is_active else "gray", icon="map-marker" if is_active else "ban", prefix='fa'),
        opacity=1.0 if is_active else 0.5
    ).add_to(m)

folium.LayerControl(collapsed=False).add_to(m)

map_out = st_folium(m, height=700, use_container_width=True, key="main_map")

# Handle Click to Add
if map_out and map_out.get('last_clicked'):
    clat, clng = map_out['last_clicked']['lat'], map_out['last_clicked']['lng']
    last = st.session_state.markers[-1] if st.session_state.markers else None
    if not last or (abs(clat - last['lat']) > 1e-5 or abs(clng - last['lng']) > 1e-5):
        st.session_state.markers.append({'lat': clat, 'lng': clng, 'active': True})
        st.session_state.isochrone_data = None
        st.session_state.intersection_data = None
        st.rerun()
