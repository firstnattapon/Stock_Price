import streamlit as st
import folium
from streamlit_folium import st_folium
import requests
from shapely.geometry import shape, mapping
import json
import io

# --- 1. การตั้งค่าหน้าเว็บ ---
st.set_page_config(
    page_title="Geoapify Map (Chiang Khong CBD)",
    page_icon="🌍",
    layout="wide"
)

# --- CSS: ปรับแต่งให้เต็มหน้าจอ ---
st.markdown("""
    <style>
        .block-container {
            padding-top: 2rem;
            padding-bottom: 0rem;
            padding-left: 2rem;
            padding-right: 2rem;
        }
        h1 { margin-bottom: 0px; }
    </style>
""", unsafe_allow_html=True)

# --- พิกัดเริ่มต้น (เชียงของ) ---
DEFAULT_LAT = 20.219443
DEFAULT_LON = 100.403630
DEFAULT_API_KEY = "4eefdfb0b0d349e595595b9c03a69e3d"

# --- MAP STYLES CONFIGURATION ---
MAP_STYLES = {
    "OpenStreetMap (มาตรฐาน)": {
        "tiles": "OpenStreetMap", 
        "attr": None
    },
    "CartoDB Positron (สีอ่อน/สะอาด)": {
        "tiles": "CartoDB positron", 
        "attr": None
    },
    "CartoDB Dark Matter (สีเข้ม)": {
        "tiles": "CartoDB dark_matter", 
        "attr": None
    },
    "Esri Satellite (ดาวเทียม)": {
        "tiles": "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        "attr": "Tiles &copy; Esri &mdash; Source: Esri, i-cubed, USDA, USGS, AEX, GeoEye, Getmapping, Aerogrid, IGN, IGP, UPR-EGP, and the GIS User Community"
    },
    "Esri Street Map (ถนนละเอียด)": {
        "tiles": "https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}",
        "attr": "Tiles &copy; Esri &mdash; Source: Esri"
    },
    "Esri Topo Map (ภูมิประเทศ)": {
        "tiles": "https://server.arcgisonline.com/ArcGIS/rest/services/World_Topo_Map/MapServer/tile/{z}/{y}/{x}",
        "attr": "Tiles &copy; Esri &mdash; Source: Esri"
    }
}

MARKER_COLORS = ['red', 'blue', 'green', 'purple', 'orange', 'black', 'pink', 'cadetblue']
HEX_COLORS = ['#D63E2A', '#38AADD', '#72B026', '#D252B9', '#F69730', '#333333', '#FF91EA', '#436978']

# --- เตรียม Session State (Initialize) ---
# เรากำหนดค่าเริ่มต้นให้ Session State หากยังไม่มีค่า
if 'markers' not in st.session_state:
    st.session_state.markers = [{'lat': DEFAULT_LAT, 'lng': DEFAULT_LON}]
if 'isochrone_data' not in st.session_state:
    st.session_state.isochrone_data = None
if 'intersection_data' not in st.session_state:
    st.session_state.intersection_data = None
if 'colors' not in st.session_state:
    st.session_state.colors = {
        'step1': '#2A9D8F', 'step2': '#E9C46A', 
        'step3': '#F4A261', 'step4': '#D62828'
    }
# Initialize widget states if not present (เพื่อรองรับ Import/Export)
if 'api_key' not in st.session_state: st.session_state.api_key = DEFAULT_API_KEY
if 'map_style_name' not in st.session_state: st.session_state.map_style_name = list(MAP_STYLES.keys())[0]
if 'travel_mode' not in st.session_state: st.session_state.travel_mode = "drive"
if 'time_intervals' not in st.session_state: st.session_state.time_intervals = [5]

st.markdown(f"📍 **พิกัดเริ่มต้น:** {DEFAULT_LAT}, {DEFAULT_LON} | 🌍 Geoapify: ค้นหาจุดศูนย์กลาง (Local CBD)")

# --- 2. Sidebar ---
with st.sidebar:
    st.header("⚙️ การตั้งค่า")

    # --- NEW: ส่วนจัดการไฟล์ Import/Export ---
    with st.expander("📂 จัดการไฟล์ (Import / Export)", expanded=False):
        # 1. Export Logic
        export_data = {
            "markers": st.session_state.markers,
            "isochrone_data": st.session_state.isochrone_data,
            "intersection_data": st.session_state.intersection_data,
            "colors": st.session_state.colors,
            "api_key": st.session_state.api_key,
            "map_style_name": st.session_state.map_style_name,
            "travel_mode": st.session_state.travel_mode,
            "time_intervals": st.session_state.time_intervals
        }
        json_str = json.dumps(export_data, indent=2)
        st.download_button(
            label="💾 บันทึกไฟล์ (Export JSON)",
            data=json_str,
            file_name="geoapify_cbd_project.json",
            mime="application/json",
            use_container_width=True
        )

        # 2. Import Logic
        uploaded_file = st.file_uploader("📂 เปิดไฟล์เดิม (Import JSON)", type=["json"])
        if uploaded_file is not None:
            try:
                data = json.load(uploaded_file)
                # Update Session State with loaded data
                st.session_state.markers = data.get("markers", st.session_state.markers)
                st.session_state.isochrone_data = data.get("isochrone_data", None)
                st.session_state.intersection_data = data.get("intersection_data", None)
                st.session_state.colors = data.get("colors", st.session_state.colors)
                st.session_state.api_key = data.get("api_key", DEFAULT_API_KEY)
                st.session_state.map_style_name = data.get("map_style_name", list(MAP_STYLES.keys())[0])
                st.session_state.travel_mode = data.get("travel_mode", "drive")
                st.session_state.time_intervals = data.get("time_intervals", [5])
                
                st.success("✅ โหลดข้อมูลสำเร็จ!")
                if st.button("🔄 กดเพื่อรีเฟรชหน้าจอ"):
                    st.rerun()
            except Exception as e:
                st.error(f"❌ ไฟล์ไม่ถูกต้อง: {e}")

    st.markdown("---")
    
    # Input API Key (ผูก key เพื่อให้ Save ได้)
    api_key = st.text_input("API Key", key="api_key", type="password")
    
    st.markdown("---")
    
    col_btn1, col_btn2 = st.columns(2)
    with col_btn1:
        if st.button("❌ ลบจุดล่าสุด", use_container_width=True):
            if st.session_state.markers:
                st.session_state.markers.pop()
                st.session_state.isochrone_data = None
                st.session_state.intersection_data = None
                st.rerun()
    with col_btn2:
        if st.button("🔄 รีเซ็ต", use_container_width=True):
            st.session_state.markers = [{'lat': DEFAULT_LAT, 'lng': DEFAULT_LON}]
            st.session_state.isochrone_data = None
            st.session_state.intersection_data = None
            st.rerun()
            
    st.write(f"📍 จำนวนจุด: **{len(st.session_state.markers)}**")
    
    if st.session_state.markers:
        st.markdown("---")
        for i, m in enumerate(st.session_state.markers):
            color_name = MARKER_COLORS[i % len(MARKER_COLORS)]
            st.markdown(f"<span style='color:{color_name};'>●</span> จุดที่ {i+1} ({m['lat']:.4f}, {m['lng']:.4f})", unsafe_allow_html=True)

    st.markdown("---")
    
    # Map Style (ผูก key)
    selected_style_name = st.selectbox(
        "สไตล์แผนที่", 
        list(MAP_STYLES.keys()), 
        key="map_style_name"
    )
    selected_style_config = MAP_STYLES[selected_style_name]
    
    # Travel Mode (ผูก key)
    travel_mode = st.selectbox(
        "รูปแบบการเดินทาง",
        options=["drive", "walk", "bicycle", "transit"], 
        format_func=lambda x: {"drive": "🚗 ขับรถ", "walk": "🚶 เดินเท้า", "bicycle": "🚲 ปั่นจักรยาน", "transit": "🚌 ขนส่งสาธารณะ"}[x],
        key="travel_mode"
    )
    
    # Time Intervals (ผูก key)
    time_intervals = st.multiselect(
        "ช่วงเวลา (นาที)", 
        options=[5, 10, 15, 20, 30, 45, 60],
        key="time_intervals"
    )
    
    with st.expander("🎨 ตั้งค่าสีพื้นที่"):
        # ไม่จำเป็นต้องผูก key ตรงนี้เพราะ st.color_picker อัพเดทตัวแปร st.session_state.colors['stepX'] ได้โดยตรงถ้าเราเขียน logic รับค่า แต่เพื่อให้ Import ทำงานง่าย เราใช้ค่าจาก session_state เป็น value
        c1 = st.color_picker("≤ 10 นาที", st.session_state.colors['step1'])
        c2 = st.color_picker("11 - 20 นาที", st.session_state.colors['step2'])
        c3 = st.color_picker("21 - 30 นาที", st.session_state.colors['step3'])
        c4 = st.color_picker("> 30 นาที", st.session_state.colors['step4'])
        
        # อัปเดตค่าสีกลับเข้า Session State (กรณีมีการเปลี่ยนสีแล้วกด Save)
        st.session_state.colors['step1'] = c1
        st.session_state.colors['step2'] = c2
        st.session_state.colors['step3'] = c3
        st.session_state.colors['step4'] = c4

    st.markdown("---")
    submit_button = st.button("🚀 คำนวณหา CBD", type="primary", use_container_width=True)

# --- 3. Logic คำนวณ Geometry ---
def calculate_intersection(features, num_markers):
    if num_markers < 2: return None
    polys_per_marker = {}
    for feat in features:
        m_idx = feat['properties']['marker_index']
        geom = shape(feat['geometry'])
        if m_idx not in polys_per_marker: polys_per_marker[m_idx] = geom
        else: polys_per_marker[m_idx] = polys_per_marker[m_idx].union(geom)
    if not polys_per_marker: return None
    intersection_poly = polys_per_marker[0]
    for i in range(1, num_markers):
        if i in polys_per_marker: intersection_poly = intersection_poly.intersection(polys_per_marker[i])
    if intersection_poly.is_empty: return None
    return mapping(intersection_poly)

# --- 4. Logic เรียก API ---
if submit_button:
    if not api_key: st.warning("⚠️ กรุณาใส่ API Key")
    elif not st.session_state.markers: st.warning("⚠️ กรุณาเพิ่มหมุด")
    elif not time_intervals: st.warning("⚠️ กรุณาเลือกเวลา")
    else:
        with st.spinner(f'กำลังวิเคราะห์ข้อมูล...'):
            try:
                base_url = "https://api.geoapify.com/v1/isoline"
                all_features = []
                ranges_seconds = ",".join([str(t * 60) for t in sorted(time_intervals)])
                for i, marker in enumerate(st.session_state.markers):
                    params = {
                        "lat": marker['lat'], "lon": marker['lng'],
                        "type": "time", "mode": travel_mode,
                        "range": ranges_seconds, "apiKey": api_key
                    }
                    response = requests.get(base_url, params=params)
                    if response.status_code == 200:
                        data = response.json()
                        for feature in data.get('features', []):
                            seconds = feature['properties'].get('value', 0)
                            feature['properties']['travel_time_minutes'] = seconds / 60
                            feature['properties']['marker_index'] = i
                            all_features.append(feature)
                if all_features:
                    st.session_state.isochrone_data = {"type": "FeatureCollection", "features": all_features}
                    cbd_geom = calculate_intersection(all_features, len(st.session_state.markers))
                    if cbd_geom:
                        st.session_state.intersection_data = {
                            "type": "FeatureCollection",
                            "features": [{"type": "Feature", "geometry": cbd_geom, "properties": {"type": "cbd"}}]
                        }
                        st.success(f"✅ พบพื้นที่ CBD ร่วมกัน!")
                    else:
                        st.session_state.intersection_data = None
                        st.warning("⚠️ ไม่พบพื้นที่ทับซ้อน" if len(st.session_state.markers) > 1 else "✅ คำนวณสำเร็จ")
            except Exception as e: st.error(f"❌ Error: {e}")

# --- 5. Helper Functions ---
def get_fill_color(minutes):
    c = st.session_state.colors
    if minutes <= 10: return c['step1']
    elif minutes <= 20: return c['step2']
    elif minutes <= 30: return c['step3']
    else: return c['step4']

def get_border_color(marker_idx):
    return HEX_COLORS[marker_idx % len(HEX_COLORS)] if marker_idx is not None else '#3388ff'

# --- 6. Display Map ---
def display_map():
    # ใช้ Config ที่เลือกจาก Sidebar
    selected_style_config = MAP_STYLES[st.session_state.map_style_name]

    if st.session_state.markers:
        last_m = st.session_state.markers[-1]
        center = [last_m['lat'], last_m['lng']]
    else:
        center = [DEFAULT_LAT, DEFAULT_LON]

    m = folium.Map(
        location=center, 
        zoom_start=11, 
        tiles=selected_style_config["tiles"],
        attr=selected_style_config["attr"]
    )

    if st.session_state.isochrone_data:
        folium.GeoJson(
            st.session_state.isochrone_data,
            name='Travel Areas',
            style_function=lambda feature: {
                'fillColor': get_fill_color(feature['properties']['travel_time_minutes']),
                'color': get_border_color(feature['properties']['marker_index']),
                'weight': 1, 'fillOpacity': 0.2
            },
            tooltip=folium.GeoJsonTooltip(fields=['travel_time_minutes'], aliases=['นาที:'])
        ).add_to(m)

    if st.session_state.intersection_data:
        folium.GeoJson(
            st.session_state.intersection_data,
            name='🏆 Common CBD Area',
            style_function=lambda feature: {
                'fillColor': '#FFD700', 'color': '#FF8C00',
                'weight': 3, 'fillOpacity': 0.6, 'dashArray': '5, 5'
            },
            tooltip="🏆 พื้นที่จุดศูนย์กลาง (เข้าถึงได้ทุกคน)"
        ).add_to(m)

    for i, marker in enumerate(st.session_state.markers):
        color_name = MARKER_COLORS[i % len(MARKER_COLORS)]
        folium.Marker(
            [marker['lat'], marker['lng']],
            popup=f"จุดที่ {i+1} ({color_name})",
            icon=folium.Icon(color=color_name, icon="map-marker", prefix='fa')
        ).add_to(m)

    folium.LayerControl().add_to(m)

    map_output = st_folium(
        m, 
        height=850, 
        use_container_width=True, 
        key="geoapify_ck_map"
    )
    
    if map_output and map_output.get('last_clicked'):
        clicked_lat = map_output['last_clicked']['lat']
        clicked_lng = map_output['last_clicked']['lng']
        is_new = True
        if st.session_state.markers:
            last_mk = st.session_state.markers[-1]
            if abs(clicked_lat - last_mk['lat']) < 0.00001 and abs(clicked_lng - last_mk['lng']) < 0.00001:
                is_new = False
        if is_new:
            st.session_state.markers.append({'lat': clicked_lat, 'lng': clicked_lng})
            st.rerun()

display_map()
