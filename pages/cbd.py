import streamlit as st
import folium
from streamlit_folium import st_folium
import requests
from shapely.geometry import shape, mapping
import json
from typing import List, Dict, Any, Optional
import io

# ============================================================================
# 1. CONSTANTS & CONFIGURATION
# ============================================================================

PAGE_CONFIG = {
    "page_title": "Geoapify CBD x Longdo GIS",
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

# Keys to save in Export (Added 'cityplan_opacity')
SESSION_KEYS_TO_SAVE = [
    'api_key', 'map_style_name', 'travel_mode', 'time_intervals', 
    'show_dol', 'show_cityplan', 'cityplan_opacity', 'show_population', 'colors'
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
    
    # Group geometries by active marker index (Union concentric rings first)
    for feat in features:
        active_idx = feat['properties']['active_index']
        geom = shape(feat['geometry'])
        if active_idx not in polys_per_active_idx:
            polys_per_active_idx[active_idx] = geom
        else:
            polys_per_active_idx[active_idx] = polys_per_active_idx[active_idx].union(geom)
    
    if len(polys_per_active_idx) < num_active_markers: return None
    
    # Find intersection across all markers
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
    """Fetch isochrone data from Geoapify API with caching."""
    url = "https://api.geoapify.com/v1/isoline"
    params = {"lat": marker_lat, "lon": marker_lon, "type": "time", "mode": travel_mode, "range": ranges_str, "apiKey": api_key}
    try:
        response = requests.get(url, params=params, timeout=10)
        return response.json().get('features', []) if response.status_code == 200 else None
    except Exception:
        return None

def add_wms_layer(m: folium.Map, layers: str, name: str, show: bool, opacity: float = 1.0):
    """Helper to add Longdo WMS layers to the map with opacity control."""
    folium.WmsTileLayer(
        url=LONGDO_WMS_URL,
        layers=layers,
        name=name,
        fmt='image/png',
        transparent=True,
        version='1.1.1',
        attr=f'{name} / Longdo Map',
        show=show,
        opacity=opacity  # Inject opacity here
    ).add_to(m)

# ============================================================================
# 3. STATE MANAGEMENT & IO HANDLERS
# ============================================================================

def initialize_session_state():
    """Initialize all session state variables."""
    defaults = {
        'markers': [{'lat': DEFAULT_LAT, 'lng': DEFAULT_LON, 'active': True}],
        'isochrone_data': None,
        'intersection_data': None,
        'colors': {'step1': '#2A9D8F', 'step2': '#E9C46A', 'step3': '#F4A261', 'step4': '#D62828'},
        'api_key': DEFAULT_GEOAPIFY_KEY,
        'map_style_name': "Esri Light Gray (แนะนำสำหรับดูผังเมือง)",
        'travel_mode': "drive",
        'time_intervals': [5],
        'show_dol': False,
        'show_cityplan': False,
        'cityplan_opacity': 0.7,  # Default opacity
        'show_population': False
    }
    
    # Load default data from remote JSON only if markers are missing and not previously loaded
    if 'markers' not in st.session_state:
        try:
            response = requests.get(DEFAULT_JSON_URL, timeout=3)
            if response.status_code == 200:
                data = response.json()
                defaults.update({k: data.get(k, v) for k, v in defaults.items()})
        except Exception: pass

    for k, v in defaults.items():
        if k not in st.session_state: st.session_state[k] = v
    
    # Ensure active flag exists for all markers
    for m in st.session_state.markers:
        if 'active' not in m: m['active'] = True

def reset_state():
    """Reset markers and results."""
    st.session_state.markers = [{'lat': DEFAULT_LAT, 'lng': DEFAULT_LON, 'active': True}]
    clear_results()

def clear_results():
    """Clear calculation results (used when markers change)."""
    st.session_state.isochrone_data = None
    st.session_state.intersection_data = None

def generate_export_json() -> str:
    """Serialize current state to JSON string."""
    export_data = {
        "markers": st.session_state.markers,
        "settings": {k: st.session_state[k] for k in SESSION_KEYS_TO_SAVE if k in st.session_state}
    }
    return json.dumps(export_data, indent=2, ensure_ascii=False)

def apply_imported_config(uploaded_file):
    """Parse JSON file and update session state."""
    if uploaded_file is not None:
        try:
            data = json.load(uploaded_file)
            
            # 1. Update Markers
            if "markers" in data and isinstance(data["markers"], list):
                st.session_state.markers = data["markers"]
            
            # 2. Update Settings
            if "settings" in data and isinstance(data["settings"], dict):
                for k, v in data["settings"].items():
                    if k in SESSION_KEYS_TO_SAVE:
                        st.session_state[k] = v
            
            # 3. Cleanup & UI Feedback
            clear_results()
            st.toast("✅ โหลดการตั้งค่าสำเร็จ!", icon="💾")
            
        except json.JSONDecodeError:
            st.error("ไฟล์ JSON ไม่ถูกต้อง")
        except Exception as e:
            st.error(f"เกิดข้อผิดพลาด: {e}")

# ============================================================================
# 4. UI COMPONENTS
# ============================================================================

def render_sidebar():
    with st.sidebar:
        st.header("⚙️ การตั้งค่า")
        
        # --- 0. Config Manager (Import/Export) ---
        with st.expander("💾 จัดการ Config (Export/Import)", expanded=False):
            # Export
            st.caption("📤 **Save Data**")
            json_str = generate_export_json()
            st.download_button(
                label="Download Config (.json)",
                data=json_str,
                file_name="geo_cbd_config.json",
                mime="application/json",
                use_container_width=True
            )
            
            # Import
            st.markdown("---")
            st.caption("📥 **Load Data**")
            uploaded_file = st.file_uploader("Upload .json file", type=["json"], label_visibility="collapsed")
            if uploaded_file is not None:
                # Check if this file is different from the last processed one or if user wants to force load
                if st.button("ยืนยันการโหลดไฟล์", use_container_width=True):
                    apply_imported_config(uploaded_file)
                    st.rerun()

        st.markdown("---")
        
        # --- 1. Manual Add ---
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
                    else: st.error("รูปแบบผิด (ต้องมี , คั่น)")
                except: st.error("พิกัดผิดพลาด")
            
        st.text_input("Geoapify API Key", key="api_key", type="password")
        
        # --- 2. Controls ---
        c1, c2 = st.columns(2)
        if c1.button("❌ ลบจุดล่าสุด", use_container_width=True) and st.session_state.markers:
            st.session_state.markers.pop()
            clear_results()
            st.rerun()
        if c2.button("🔄 รีเซ็ต", use_container_width=True):
            reset_state()
            st.rerun()

        # --- 3. Marker List ---
        active_list = [(i, m) for i, m in enumerate(st.session_state.markers) if m.get('active', True)]
        st.write(f"📍 คำนวณ: **{len(active_list)}** / {len(st.session_state.markers)}")
        
        if st.session_state.markers:
            st.markdown("---")
            for i, m in enumerate(st.session_state.markers):
                color_name = MARKER_COLORS[i % len(MARKER_COLORS)]
                col_chk, col_txt, col_del = st.columns([0.15, 0.70, 0.15])
                
                with col_chk:
                    is_active = st.checkbox(" ", value=m.get('active', True), key=f"active_chk_{i}", label_visibility="collapsed")
                    st.session_state.markers[i]['active'] = is_active
                
                with col_txt:
                    style = f"color:{color_name}; font-weight:bold;" if is_active else "color:gray; text-decoration:line-through;"
                    st.markdown(f"<span style='{style}'>● จุดที่ {i+1}</span><br><span style='font-size:0.8em; color:gray;'>({m['lat']:.6f}, {m['lng']:.6f})</span>", unsafe_allow_html=True)
                
                with col_del:
                    if st.button("✕", key=f"del_btn_{i}"):
                        st.session_state.markers.pop(i)
                        clear_results()
                        st.rerun()

        # --- 4. Settings Expander ---
        st.markdown("---")
        with st.expander("⚙️ ตั้งค่าแผนที่ & Layers", expanded=True):
            st.selectbox("สไตล์แผนที่", list(MAP_STYLES.keys()), key="map_style_name")
            
            st.markdown("##### 🗺️ ข้อมูลพิเศษ (Longdo)")
            st.checkbox("👥 ความหนาแน่นประชากร", key="show_population")
            
            # --- Modified City Plan UI with Opacity Slider ---
            col_cp_chk, col_cp_sld = st.columns([0.65, 0.35])
            with col_cp_chk:
                st.checkbox("🏙️ ผังเมืองรวม", key="show_cityplan")
            with col_cp_sld:
                if st.session_state.show_cityplan:
                    st.slider("ความโปร่ง", 0.0, 1.0, key="cityplan_opacity", label_visibility="collapsed")
            # -----------------------------------------------

            st.checkbox("📜 รูปแปลงที่ดิน (กรมที่ดิน)", key="show_dol")
            
            st.markdown("##### 🚗 การเดินทาง")
            st.selectbox("โหมด", list(TRAVEL_MODE_NAMES.keys()), format_func=lambda x: TRAVEL_MODE_NAMES[x], key="travel_mode")
            st.multiselect("เวลา (นาที)", TIME_OPTIONS, key="time_intervals")
            
            st.caption("🎨 สีพื้นที่ตามเวลาเดินทาง:")
            c1, c2 = st.columns(2)
            st.session_state.colors['step1'] = c1.color_picker("≤ 10 นาที", st.session_state.colors['step1'])
            st.session_state.colors['step2'] = c2.color_picker("11-20 นาที", st.session_state.colors['step2'])
            st.session_state.colors['step3'] = c1.color_picker("21-30 นาที", st.session_state.colors['step3'])
            st.session_state.colors['step4'] = c2.color_picker("> 30 นาที", st.session_state.colors['step4'])
            
        do_calculate = st.button("🚀 คำนวณหา CBD", type="primary", use_container_width=True)
        return do_calculate, active_list

def perform_calculation(active_list):
    """Execute the core business logic for CBD calculation."""
    if not st.session_state.api_key: st.warning("ใส่ API Key")
    elif not active_list: st.warning("เลือกจุด")
    elif not st.session_state.time_intervals: st.warning("เลือกเวลา")
    else:
        with st.spinner('กำลังวิเคราะห์...'):
            all_feats = []
            ranges = ",".join([str(t*60) for t in sorted(st.session_state.time_intervals)])
            
            # Fetch data for each active marker
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
            
            # Process results
            if all_feats:
                st.session_state.isochrone_data = {"type": "FeatureCollection", "features": all_feats}
                cbd = calculate_intersection(all_feats, len(active_list))
                st.session_state.intersection_data = {"type": "FeatureCollection", "features": [{"type": "Feature", "geometry": cbd, "properties": {"type": "cbd"}}]} if cbd else None
                
                if cbd: st.success("✅ พบพื้นที่ CBD!")
                else: st.warning("⚠️ ไม่พบพื้นที่ทับซ้อน")

def render_map():
    """Construct and render the Folium map."""
    style = MAP_STYLES[st.session_state.map_style_name]
    center = [st.session_state.markers[-1]['lat'], st.session_state.markers[-1]['lng']] if st.session_state.markers else [DEFAULT_LAT, DEFAULT_LON]

    m = folium.Map(location=center, zoom_start=14, tiles=style["tiles"], attr=style["attr"])

    # 1. Isochrones Layer
    if st.session_state.isochrone_data:
        folium.GeoJson(
            st.session_state.isochrone_data, name='Travel Areas',
            style_function=lambda x: {
                'fillColor': get_fill_color(x['properties']['travel_time_minutes'], st.session_state.colors),
                'color': get_border_color(x['properties']['original_index']),
                'weight': 1, 'fillOpacity': 0.2
            }
        ).add_to(m)

    # 2. CBD Intersection Layer
    if st.session_state.intersection_data:
        folium.GeoJson(
            st.session_state.intersection_data, name='CBD Zone',
            style_function=lambda x: {'fillColor': '#FFD700', 'color': '#FF8C00', 'weight': 3, 'fillOpacity': 0.6, 'dashArray': '5, 5'}
        ).add_to(m)

    # 3. WMS Layers (Using Helper with Opacity)
    add_wms_layer(m, 'thailand_population', 'ความหนาแน่นประชากร', st.session_state.show_population)
    
    # *** Apply opacity specifically to City Plan ***
    add_wms_layer(m, 'cityplan_dpt', 'ผังเมืองรวม (DPT)', st.session_state.show_cityplan, opacity=st.session_state.cityplan_opacity)
    
    add_wms_layer(m, 'dol', 'รูปแปลงที่ดิน (DOL)', st.session_state.show_dol)

    # 4. Markers Layer
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
    
    # Render Sidebar & Get Actions
    do_calculate, active_list = render_sidebar()
    
    # Process Logic
    if do_calculate:
        perform_calculation(active_list)
        
    # Render Map & Handle Clicks
    map_out = render_map()
    
    if map_out and map_out.get('last_clicked'):
        clat, clng = map_out['last_clicked']['lat'], map_out['last_clicked']['lng']
        # Prevent duplicate adds from same click event
        if not st.session_state.markers or (abs(clat - st.session_state.markers[-1]['lat']) > 1e-5):
            st.session_state.markers.append({'lat': clat, 'lng': clng, 'active': True})
            clear_results()
            st.rerun()

if __name__ == "__main__":
    main()
