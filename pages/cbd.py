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
    "page_title": "Geoapify Map (Chiang Khong CBD)",
    "page_icon": "🌍",
    "layout": "wide"
}

DEFAULT_JSON_URL = "https://raw.githubusercontent.com/firstnattapon/Stock_Price/refs/heads/main/Geoapify_Map/geoapify_cbd_project.json"

DEFAULT_LAT = 20.219443
DEFAULT_LON = 100.403630
DEFAULT_API_KEY = "4eefdfb0b0d349e595595b9c03a69e3d"

# DOL (กรมที่ดิน) WMS Configuration
DOL_WMS_URL = "https://landsmaps.dol.go.th/geoserver/DOL/wms"
DOL_LAYERS = "DOL:v_parcel_all"  # Layer แนวเขตที่ดิน

MARKER_COLORS = ['red', 'blue', 'green', 'purple', 'orange', 'black', 'pink', 'cadetblue']
HEX_COLORS = ['#D63E2A', '#38AADD', '#72B026', '#D252B9', '#F69730', '#333333', '#FF91EA', '#436978']

MAP_STYLES = {
    # =========================================================
    # 1. กลุ่มมาตรฐาน & สีอ่อน (Standard & Clean)
    # =========================================================
    "OpenStreetMap (มาตรฐาน)": {
        "tiles": "OpenStreetMap", 
        "attr": None
    },
    "Google Maps (ผสม/Hybrid)": {
        "tiles": "https://mt1.google.com/vt/lyrs=y&x={x}&y={y}&z={z}",
        "attr": "Google Maps"
    },
    "CartoDB Positron (สีอ่อน/สะอาด)": {
        "tiles": "CartoDB positron", 
        "attr": None
    },
    "CartoDB Voyager (เน้นสถานที่/นำทาง)": {
        "tiles": "CartoDB voyager",
        "attr": None
    },
    "Esri Light Gray (สีเทาอ่อน/เน้นข้อมูล)": { 
        # *แนะนำ: ทำให้สีของพื้นที่ CBD เด่นที่สุด*
        "tiles": "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}",
        "attr": "Tiles &copy; Esri"
    },

    # =========================================================
    # 2. กลุ่ม Google Maps (คุ้นเคย & ใช้งานง่าย)
    # =========================================================
    "Google Maps (ถนน)": {
        "tiles": "https://mt1.google.com/vt/lyrs=m&x={x}&y={y}&z={z}",
        "attr": "Google Maps"
    },
    "Google Maps (ดาวเทียม)": {
        "tiles": "https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}",
        "attr": "Google Maps"
    },
    "Google Maps (ภูมิประเทศ)": {
        "tiles": "https://mt1.google.com/vt/lyrs=p&x={x}&y={y}&z={z}",
        "attr": "Google Maps"
    },

    # =========================================================
    # 3. กลุ่มวิเคราะห์ความเจริญ & เมือง (Urban & Prosperity)
    # =========================================================
    "NASA Night Lights (แสงไฟเศรษฐกิจ)": {
        # *แนะนำ: ดูภาพรวมความเจริญจากแสงไฟ (Zoom out)*
        "tiles": "https://map1.vis.earthdata.nasa.gov/wmts-webmerc/VIIRS_CityLights_2012/default//GoogleMapsCompatible_Level8/{z}/{y}/{x}.jpg",
        "attr": "Imagery provided by NASA GIBS"
    },
    "OpenStreetMap (Hot Style - เน้นสิ่งปลูกสร้าง)": {
        # *แนะนำ: สีสด เห็นเขตตึกหนาแน่นชัดเจน*
        "tiles": "https://{s}.tile.openstreetmap.fr/hot/{z}/{x}/{y}.png",
        "attr": "&copy; OpenStreetMap contributors, Tiles style by Humanitarian OpenStreetMap Team hosted by OpenStreetMap France"
    },
    "OpenRailwayMap (โครงข่ายรถไฟฟ้า/ราง)": {
        # *แนะนำ: ดูว่า CBD เกาะแนวรถไฟฟ้าหรือไม่*
        "tiles": "https://{s}.tiles.openrailwaymap.org/standard/{z}/{x}/{y}.png",
        "attr": "Map data: &copy; OpenStreetMap contributors | Map style: &copy; OpenRailwayMap (CC-BY-SA)"
    },
    "Esri Dark Gray (โครงสร้างเมืองสีเข้ม)": {
        # *แนะนำ: พื้นหลังมืด ทำให้ Overlay สีสว่างๆ เด่นมาก*
        "tiles": "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}",
        "attr": "Tiles &copy; Esri"
    },
    "CartoDB Dark Matter (เมืองยามค่ำคืน)": {
        # *แนะนำ: ดู Modern และเห็นเส้นถนนชัดเจน*
        "tiles": "CartoDB dark_matter", 
        "attr": None
    },

    # =========================================================
    # 4. กลุ่มภูมิประเทศ & ภาพถ่ายทางอากาศ (Satellite & Topo)
    # =========================================================
    "Esri Satellite (ดาวเทียมชัด)": {
        "tiles": "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        "attr": "Tiles &copy; Esri &mdash; Source: Esri"
    },
    "Esri World Topo (ภูมิประเทศสวยงาม)": {
        "tiles": "https://server.arcgisonline.com/ArcGIS/rest/services/World_Topo_Map/MapServer/tile/{z}/{y}/{x}",
        "attr": "Tiles &copy; Esri"
    },
    "OpenTopoMap (ภูมิประเทศ/คอนทัวร์)": {
        "tiles": "https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png",
        "attr": "Map data: &copy; OpenStreetMap contributors, SRTM | Map style: &copy; OpenTopoMap (CC-BY-SA)"
    },

    # =========================================================
    # 5. กลุ่มการเดินทางเฉพาะทาง (Travel Modes)
    # =========================================================
    "OPNVKarte (ขนส่งสาธารณะ)": {
        "tiles": "https://tileserver.memomaps.de/tilegen/{z}/{x}/{y}.png",
        "attr": "Map <a href='https://memomaps.de/'>memomaps.de</a>"
    },
    "CyclOSM (สำหรับจักรยาน)": {
        "tiles": "https://{s}.tile-cyclosm.openstreetmap.fr/cyclosm/{z}/{x}/{y}.png",
        "attr": "CyclOSM | Map data: &copy; OpenStreetMap contributors"
    }
}

TRAVEL_MODE_NAMES = {
    "drive": "🚗 ขับรถ",
    "walk": "🚶 เดินเท้า",
    "bicycle": "🚲 ปั่นจักรยาน",
    "transit": "🚌 ขนส่งสาธารณะ"
}

TIME_OPTIONS = [5, 10, 15, 20, 30, 45, 60]

# ============================================================================
# 2. PURE HELPER FUNCTIONS (Logic & Calculation)
# ============================================================================

def get_fill_color(minutes: float, colors_config: Dict[str, str]) -> str:
    """Determine fill color based on travel time."""
    if minutes <= 10:
        return colors_config['step1']
    elif minutes <= 20:
        return colors_config['step2']
    elif minutes <= 30:
        return colors_config['step3']
    else:
        return colors_config['step4']

def get_border_color(original_marker_idx: Optional[int]) -> str:
    """Get border color for isochrone based on marker index."""
    if original_marker_idx is None:
        return '#3388ff'
    return HEX_COLORS[original_marker_idx % len(HEX_COLORS)]

def calculate_intersection(features: List[Dict], num_active_markers: int) -> Optional[Dict]:
    """Calculate geometric intersection of all active marker isochrones."""
    if num_active_markers < 2:
        return None
    
    # Group polygons by active_index
    polys_per_active_idx = {}
    
    for feat in features:
        active_idx = feat['properties']['active_index']
        geom = shape(feat['geometry'])
        
        if active_idx not in polys_per_active_idx:
            polys_per_active_idx[active_idx] = geom
        else:
            polys_per_active_idx[active_idx] = polys_per_active_idx[active_idx].union(geom)
    
    if len(polys_per_active_idx) < num_active_markers:
        return None
    
    active_indices = sorted(polys_per_active_idx.keys())
    
    try:
        intersection_poly = polys_per_active_idx[active_indices[0]]
        for idx in active_indices[1:]:
            intersection_poly = intersection_poly.intersection(polys_per_active_idx[idx])
            if intersection_poly.is_empty:
                return None
        
        return mapping(intersection_poly) if not intersection_poly.is_empty else None
    
    except Exception as e:
        st.error(f"Intersection calculation error: {e}")
        return None

@st.cache_data(show_spinner=False, ttl=3600)
def fetch_api_data_cached(api_key: str, travel_mode: str, ranges_str: str, marker_lat: float, marker_lon: float) -> Optional[List[Dict]]:
    """Fetch isochrone data from Geoapify API with caching."""
    url = "https://api.geoapify.com/v1/isoline"
    params = {
        "lat": marker_lat,
        "lon": marker_lon,
        "type": "time",
        "mode": travel_mode,
        "range": ranges_str,
        "apiKey": api_key
    }
    try:
        response = requests.get(url, params=params, timeout=10)
        if response.status_code == 200:
            data = response.json()
            return data.get('features', [])
        return None
    except Exception:
        return None

# ============================================================================
# 3. STATE MANAGEMENT
# ============================================================================

def initialize_session_state():
    """Initialize all session state variables."""
    defaults = {
        'markers': [{'lat': DEFAULT_LAT, 'lng': DEFAULT_LON, 'active': True}],
        'isochrone_data': None,
        'intersection_data': None,
        'colors': {'step1': '#2A9D8F', 'step2': '#E9C46A', 'step3': '#F4A261', 'step4': '#D62828'},
        'api_key': DEFAULT_API_KEY,
        'map_style_name': list(MAP_STYLES.keys())[0],
        'travel_mode': "drive",
        'time_intervals': [5],
        'show_dol_layer': False,  # เพิ่ม: แสดง Layer กรมที่ดิน
        'dol_opacity': 0.6        # เพิ่ม: ความโปร่งใสของ Layer
    }

    if 'markers' not in st.session_state:
        try:
            response = requests.get(DEFAULT_JSON_URL, timeout=3)
            if response.status_code == 200:
                data = response.json()
                defaults.update({k: data.get(k, v) for k, v in defaults.items()})
        except Exception:
            pass

    for key, default_val in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = default_val
    
    # Ensure 'active' key exists
    for m in st.session_state.markers:
        if 'active' not in m:
            m['active'] = True

def get_active_markers() -> List[Tuple[int, Dict]]:
    return [(i, m) for i, m in enumerate(st.session_state.markers) if m.get('active', True)]

# ============================================================================
# 4. MAIN APP
# ============================================================================

st.set_page_config(**PAGE_CONFIG)

# CSS Adjustment
st.markdown("""
    <style>
        .block-container { padding-top: 2rem; padding-bottom: 0rem; }
        h1 { margin-bottom: 0px; }
        div[data-testid="stHorizontalBlock"] button { padding: 0rem 0.5rem; line-height: 1.5; }
    </style>
""", unsafe_allow_html=True)

initialize_session_state()

# ============================================================================
# SIDEBAR
# ============================================================================

with st.sidebar:
    st.header("⚙️ การตั้งค่า")
    
    # --- 1. Manual Add Marker (Goal 1) ---
    with st.container():
        st.caption("➕ เพิ่มจุดพิกัดเอง (Lat, Lon)")
        col_inp, col_add_btn = st.columns([0.7, 0.3])
        
        with col_inp:
            manual_coords = st.text_input(
                "Coords", 
                placeholder="20.21, 100.40", 
                label_visibility="collapsed",
                key="manual_coords_input"
            )
        
        with col_add_btn:
            if st.button("เพิ่ม", use_container_width=True):
                if manual_coords:
                    try:
                        # Parsing logic
                        parts = manual_coords.replace(" ", "").split(',')
                        if len(parts) == 2:
                            new_lat = float(parts[0])
                            new_lng = float(parts[1])
                            
                            # Validation range
                            if -90 <= new_lat <= 90 and -180 <= new_lng <= 180:
                                st.session_state.markers.append({'lat': new_lat, 'lng': new_lng, 'active': True})
                                st.session_state.isochrone_data = None
                                st.session_state.intersection_data = None
                                st.rerun()
                            else:
                                st.error("พิกัดไม่อยู่ในขอบเขต")
                        else:
                            st.error("รูปแบบผิด")
                    except ValueError:
                        st.error("ตัวเลขไม่ถูกต้อง")
                else:
                    st.warning("ใส่พิกัดก่อน")

    st.markdown("---")
    
    # --- 2. API Key ---
    st.text_input("API Key", key="api_key", type="password")
    
    st.markdown("---")
    
    # --- 3. DOL Land Boundary Overlay (ใหม่!) ---
    st.caption("🗺️ แนวเขตที่ดิน (กรมที่ดิน)")
    st.checkbox("แสดงแนวเขตโฉนดที่ดิน", key="show_dol_layer")
    
    if st.session_state.show_dol_layer:
        st.slider("ความโปร่งใส Layer", 0.0, 1.0, key="dol_opacity", step=0.1)
    
    st.markdown("---")
    
    # --- 4. Control Buttons ---
    col_btn1, col_btn2 = st.columns(2)
    with col_btn1:
        if st.button("❌ ลบจุดล่าสุด", use_container_width=True):
            if st.session_state.markers:
                st.session_state.markers.pop()
                st.session_state.isochrone_data = None
                st.session_state.intersection_data = None
                st.rerun()
    with col_btn2:
        if st.button("🔄 รีเซ็ตทั้งหมด", use_container_width=True):
            st.session_state.markers = [{'lat': DEFAULT_LAT, 'lng': DEFAULT_LON, 'active': True}]
            st.session_state.isochrone_data = None
            st.session_state.intersection_data = None
            st.rerun()
    
    # Stats
    active_list = get_active_markers()
    st.write(f"📍 จุดที่เลือกคำนวณ: **{len(active_list)}** / {len(st.session_state.markers)}")
    
    # --- 5. Marker List ---
    if st.session_state.markers:
        st.markdown("---")
        st.caption("✅ = นำมาคำนวณ | ❌ = ลบทิ้ง")
        for i, m in enumerate(st.session_state.markers):
            color_name = MARKER_COLORS[i % len(MARKER_COLORS)]
            col_chk, col_txt, col_del = st.columns([0.15, 0.70, 0.15])
            
            with col_chk:
                is_active = st.checkbox(" ", value=m.get('active', True), key=f"active_chk_{i}", label_visibility="collapsed")
                st.session_state.markers[i]['active'] = is_active
            
            with col_txt:
                style = f"color:{color_name}; font-weight:bold;" if is_active else "color:gray; text-decoration:line-through;"
                st.markdown(f"<span style='{style}'>● จุดที่ {i+1}</span><br><span style='font-size:0.8em; color:gray;'>({m['lat']:.4f}, {m['lng']:.4f})</span>", unsafe_allow_html=True)
            
            with col_del:
                if st.button("✕", key=f"del_btn_{i}"):
                    st.session_state.markers.pop(i)
                    st.session_state.isochrone_data = None
                    st.session_state.intersection_data = None
                    st.rerun()

    # --- 6. Settings & File Operations ---
    with st.expander("⚙️ ตั้งค่าแผนที่ & สี", expanded=False):
        st.selectbox("สไตล์แผนที่", list(MAP_STYLES.keys()), key="map_style_name")
        st.selectbox("รูปแบบการเดินทาง", list(TRAVEL_MODE_NAMES.keys()), format_func=lambda x: TRAVEL_MODE_NAMES[x], key="travel_mode")
        st.multiselect("ช่วงเวลา (นาที)", TIME_OPTIONS, key="time_intervals")
        st.caption("สีพื้นที่:")
        c1, c2 = st.columns(2)
        st.session_state.colors['step1'] = c1.color_picker("≤ 10", st.session_state.colors['step1'])
        st.session_state.colors['step2'] = c2.color_picker("11-20", st.session_state.colors['step2'])
        st.session_state.colors['step3'] = c1.color_picker("21-30", st.session_state.colors['step3'])
        st.session_state.colors['step4'] = c2.color_picker("> 30", st.session_state.colors['step4'])

    with st.expander("📂 Import / Export", expanded=False):
        export_data = {
            "markers": st.session_state.markers,
            "isochrone_data": st.session_state.isochrone_data,
            "intersection_data": st.session_state.intersection_data,
            "colors": st.session_state.colors,
            "api_key": st.session_state.api_key,
            "map_style_name": st.session_state.map_style_name,
            "travel_mode": st.session_state.travel_mode,
            "time_intervals": st.session_state.time_intervals,
            "show_dol_layer": st.session_state.show_dol_layer,
            "dol_opacity": st.session_state.dol_opacity
        }
        st.download_button("💾 Export JSON", json.dumps(export_data, indent=2), "geoapify_project.json", "application/json", use_container_width=True)
        
        uploaded = st.file_uploader("Import JSON", type=["json"])
        if uploaded:
            try:
                d = json.load(uploaded)
                st.session_state.markers = d.get("markers", st.session_state.markers)
                # Ensure active key
                for m in st.session_state.markers:
                    if 'active' not in m: m['active'] = True
                
                st.session_state.isochrone_data = d.get("isochrone_data")
                st.session_state.intersection_data = d.get("intersection_data")
                st.session_state.colors = d.get("colors", st.session_state.colors)
                st.session_state.api_key = d.get("api_key", DEFAULT_API_KEY)
                st.session_state.map_style_name = d.get("map_style_name", st.session_state.map_style_name)
                st.session_state.travel_mode = d.get("travel_mode", st.session_state.travel_mode)
                st.session_state.time_intervals = d.get("time_intervals", st.session_state.time_intervals)
                st.session_state.show_dol_layer = d.get("show_dol_layer", False)
                st.session_state.dol_opacity = d.get("dol_opacity", 0.6)
                st.success("Loaded!")
                if st.button("Refresh"): st.rerun()
            except Exception as e:
                st.error(f"Error: {e}")

    st.markdown("---")
    
    # Calculate Button
    do_calculate = st.button("🚀 คำนวณหา CBD", type="primary", use_container_width=True)

# ============================================================================
# CALCULATION LOGIC
# ============================================================================

if do_calculate:
    active_markers_list = get_active_markers()
    if not st.session_state.api_key:
        st.warning("⚠️ ใส่ API Key ก่อนครับ")
    elif not active_markers_list:
        st.warning("⚠️ เลือกจุดอย่างน้อย 1 จุด")
    elif not st.session_state.time_intervals:
        st.warning("⚠️ เลือกช่วงเวลา")
    else:
        with st.spinner(f'กำลังวิเคราะห์ {len(active_markers_list)} จุด...'):
            try:
                all_features = []
                ranges_str = ",".join([str(t * 60) for t in sorted(st.session_state.time_intervals)])
                
                for active_idx, (orig_idx, marker) in enumerate(active_markers_list):
                    features = fetch_api_data_cached(
                        st.session_state.api_key, st.session_state.travel_mode,
                        ranges_str, marker['lat'], marker['lng']
                    )
                    if features:
                        for feat in features:
                            feat['properties']['travel_time_minutes'] = feat['properties'].get('value', 0) / 60
                            feat['properties']['original_index'] = orig_idx
                            feat['properties']['active_index'] = active_idx
                            all_features.append(feat)
                    else:
                        st.error(f"❌ API Error จุดที่ {orig_idx + 1}")
                
                if all_features:
                    st.session_state.isochrone_data = {"type": "FeatureCollection", "features": all_features}
                    cbd_geom = calculate_intersection(all_features, len(active_markers_list))
                    if cbd_geom:
                        st.session_state.intersection_data = {
                            "type": "FeatureCollection",
                            "features": [{"type": "Feature", "geometry": cbd_geom, "properties": {"type": "cbd"}}]
                        }
                        st.success(f"✅ พบพื้นที่ CBD ร่วมกัน!")
                    else:
                        st.session_state.intersection_data = None
                        st.warning("⚠️ ไม่พบพื้นที่ทับซ้อน (หรือมีจุดเดียว)")
                else:
                    st.error("❌ ไม่ได้รับข้อมูลจาก API")
            except Exception as e:
                st.error(f"Error: {e}")

# ============================================================================
# MAP RENDERING
# ============================================================================

style_config = MAP_STYLES[st.session_state.map_style_name]
center_point = [DEFAULT_LAT, DEFAULT_LON]
if st.session_state.markers:
    last_marker = st.session_state.markers[-1]
    center_point = [last_marker['lat'], last_marker['lng']]

m = folium.Map(location=center_point, zoom_start=11, tiles=style_config["tiles"], attr=style_config["attr"])

# ========== เพิ่ม DOL Land Boundary Layer ==========
if st.session_state.show_dol_layer:
    folium.raster_layers.WmsTileLayer(
        url=DOL_WMS_URL,
        layers=DOL_LAYERS,
        transparent=True,
        format="image/png",
        opacity=st.session_state.dol_opacity,
        name="แนวเขตที่ดิน (กรมที่ดิน)",
        overlay=True,
        control=True,
        attr="กรมที่ดิน"
    ).add_to(m)
# ===================================================

if st.session_state.isochrone_data:
    folium.GeoJson(
        st.session_state.isochrone_data, name='Areas',
        style_function=lambda x: {
            'fillColor': get_fill_color(x['properties']['travel_time_minutes'], st.session_state.colors),
            'color': get_border_color(x['properties']['original_index']),
            'weight': 1, 'fillOpacity': 0.2
        },
        tooltip=folium.GeoJsonTooltip(['travel_time_minutes'], aliases=['นาที:'])
    ).add_to(m)

if st.session_state.intersection_data:
    folium.GeoJson(
        st.session_state.intersection_data, name='CBD',
        style_function=lambda x: {'fillColor': '#FFD700', 'color': '#FF8C00', 'weight': 3, 'fillOpacity': 0.6, 'dashArray': '5, 5'},
        tooltip="🏆 CBD Area"
    ).add_to(m)

for i, marker in enumerate(st.session_state.markers):
    is_active = marker.get('active', True)
    color = MARKER_COLORS[i % len(MARKER_COLORS)] if is_active else "gray"
    icon = "map-marker" if is_active else "ban"
    opacity = 1.0 if is_active else 0.5
    folium.Marker(
        [marker['lat'], marker['lng']],
        popup=f"จุดที่ {i+1} {'(Active)' if is_active else '(Inactive)'}",
        icon=folium.Icon(color=color, icon=icon, prefix='fa'),
        opacity=opacity
    ).add_to(m)

folium.LayerControl().add_to(m)

map_output = st_folium(m, height=850, use_container_width=True, key="geoapify_main_map")

if map_output and map_output.get('last_clicked'):
    clicked_lat = map_output['last_clicked']['lat']
    clicked_lng = map_output['last_clicked']['lng']
    
    is_duplicate = False
    if st.session_state.markers:
        last = st.session_state.markers[-1]
        if abs(clicked_lat - last['lat']) < 1e-5 and abs(clicked_lng - last['lng']) < 1e-5:
            is_duplicate = True
    
    if not is_duplicate:
        st.session_state.markers.append({'lat': clicked_lat, 'lng': clicked_lng, 'active': True})
        st.session_state.isochrone_data = None
        st.session_state.intersection_data = None
        st.rerun()
