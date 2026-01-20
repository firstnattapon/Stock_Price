import streamlit as st
import folium
from streamlit_folium import st_folium
import requests
from shapely.geometry import shape, mapping 
import json

# --- 1. การตั้งค่าหน้าเว็บ ---
st.set_page_config(
    page_title="Geoapify Map (Chiang Khong CBD)",
    page_icon="🌍",
    layout="wide"
)

# --- CSS: ปรับแต่ง UI ---
st.markdown("""
    <style>
        .block-container {
            padding-top: 2rem;
            padding-bottom: 0rem;
            padding-left: 2rem;
            padding-right: 2rem;
        }
        h1 { margin-bottom: 0px; }
        /* ปรับแต่งปุ่มและ Checkbox ให้ดูเหมาะสมในบรรทัด */
        div[data-testid="stVerticalBlock"] > div > div[data-testid="stHorizontalBlock"] button {
            padding: 0rem 0.5rem;
            line-height: 1.5;
        }
        /* ปรับระยะห่าง checkbox */
        div[data-testid="stMarkdownContainer"] p {
            margin-bottom: 0px;
        }
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
        "attr": "Tiles &copy; Esri &mdash; Source: Esri"
    },
    "Esri Street Map (ถนนละเอียด)": {
        "tiles": "https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}",
        "attr": "Tiles &copy; Esri &mdash; Source: Esri"
    }
}

MARKER_COLORS = ['red', 'blue', 'green', 'purple', 'orange', 'black', 'pink', 'cadetblue']
HEX_COLORS = ['#D63E2A', '#38AADD', '#72B026', '#D252B9', '#F69730', '#333333', '#FF91EA', '#436978']

# --- เตรียม Session State (Initialize) ---
# เพิ่ม key 'active' เพื่อรองรับการ Isolation
if 'markers' not in st.session_state:
    st.session_state.markers = [{'lat': DEFAULT_LAT, 'lng': DEFAULT_LON, 'active': True}]
    
if 'isochrone_data' not in st.session_state:
    st.session_state.isochrone_data = None
if 'intersection_data' not in st.session_state:
    st.session_state.intersection_data = None
if 'colors' not in st.session_state:
    st.session_state.colors = {
        'step1': '#2A9D8F', 'step2': '#E9C46A', 
        'step3': '#F4A261', 'step4': '#D62828'
    }

# Initialize widget states if not present
if 'api_key' not in st.session_state: st.session_state.api_key = DEFAULT_API_KEY
if 'map_style_name' not in st.session_state: st.session_state.map_style_name = list(MAP_STYLES.keys())[0]
if 'travel_mode' not in st.session_state: st.session_state.travel_mode = "drive"
if 'time_intervals' not in st.session_state: st.session_state.time_intervals = [5]

# --- 2. Sidebar ---
with st.sidebar:
    st.header("⚙️ การตั้งค่า")

    # --- ส่วนจัดการไฟล์ Import/Export ---
    with st.expander("📂 จัดการไฟล์ (Import / Export)", expanded=False):
        # 1. Export
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

        # 2. Import
        uploaded_file = st.file_uploader("📂 เปิดไฟล์เดิม (Import JSON)", type=["json"])
        if uploaded_file is not None:
            try:
                data = json.load(uploaded_file)
                st.session_state.markers = data.get("markers", st.session_state.markers)
                
                # Migration: Ensure older files obtain 'active' key
                for m in st.session_state.markers:
                    if 'active' not in m:
                        m['active'] = True

                st.session_state.isochrone_data = data.get("isochrone_data", None)
                st.session_state.intersection_data = data.get("intersection_data", None)
                st.session_state.colors = data.get("colors", st.session_state.colors)
                st.session_state.api_key = data.get("api_key", DEFAULT_API_KEY)
                
                st.success("✅ โหลดข้อมูลสำเร็จ!")
                if st.button("🔄 กดเพื่อรีเฟรชหน้าจอ"):
                    st.rerun()
            except Exception as e:
                st.error(f"❌ ไฟล์ไม่ถูกต้อง: {e}")

    st.markdown("---")
    
    # Input API Key
    api_key = st.text_input("API Key", key="api_key", type="password")
    
    st.markdown("---")
    
    # --- ปุ่มควบคุมหลัก ---
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
            
    # นับจำนวนจุดที่ Active
    active_count = sum(1 for m in st.session_state.markers if m.get('active', True))
    total_count = len(st.session_state.markers)
    st.write(f"📍 จุดที่เลือกคำนวณ: **{active_count}** / {total_count}")
    
    # --- รายการจุด (List of Markers) พร้อม Checkbox (Isolation) และ ปุ่มลบ ---
    if st.session_state.markers:
        st.markdown("---")
        st.caption("✅ = นำมาคำนวณ (Isolate) | ❌ = ลบทิ้ง")
        
        for i, m in enumerate(st.session_state.markers):
            color_name = MARKER_COLORS[i % len(MARKER_COLORS)]
            
            # แบ่งคอลัมน์: [Checkbox] [Text] [Delete]
            c_check, c_text, c_del = st.columns([0.15, 0.70, 0.15])
            
            with c_check:
                # Checkbox สำหรับ Isolation (Active/Inactive)
                is_active = st.checkbox(
                    " ", 
                    value=m.get('active', True), 
                    key=f"active_{i}",
                    label_visibility="collapsed"
                )
                # Update state ทันที
                st.session_state.markers[i]['active'] = is_active
            
            with c_text:
                # ปรับสี Text ตามสถานะ Active
                text_style = f"color:{color_name}; font-weight:bold;" if is_active else "color:gray; text-decoration:line-through;"
                st.markdown(
                    f"<span style='{text_style}'>● จุดที่ {i+1}</span><br>"
                    f"<span style='font-size:0.8em; color:gray;'>({m['lat']:.4f}, {m['lng']:.4f})</span>", 
                    unsafe_allow_html=True
                )
            
            with c_del:
                if st.button("✕", key=f"del_{i}", help=f"ลบจุดที่ {i+1} ถาวร"):
                    st.session_state.markers.pop(i)
                    st.session_state.isochrone_data = None
                    st.session_state.intersection_data = None
                    st.rerun()

    st.markdown("---")
    
    # Map Style & Parameters
    selected_style_name = st.selectbox("สไตล์แผนที่", list(MAP_STYLES.keys()), key="map_style_name")
    
    travel_mode = st.selectbox(
        "รูปแบบการเดินทาง",
        options=["drive", "walk", "bicycle", "transit"], 
        format_func=lambda x: {"drive": "🚗 ขับรถ", "walk": "🚶 เดินเท้า", "bicycle": "🚲 ปั่นจักรยาน", "transit": "🚌 ขนส่งสาธารณะ"}[x],
        key="travel_mode"
    )
    
    time_intervals = st.multiselect("ช่วงเวลา (นาที)", options=[5, 10, 15, 20, 30, 45, 60], key="time_intervals")
    
    with st.expander("🎨 ตั้งค่าสีพื้นที่"):
        c1 = st.color_picker("≤ 10 นาที", st.session_state.colors['step1'])
        c2 = st.color_picker("11 - 20 นาที", st.session_state.colors['step2'])
        c3 = st.color_picker("21 - 30 นาที", st.session_state.colors['step3'])
        c4 = st.color_picker("> 30 นาที", st.session_state.colors['step4'])
        
        st.session_state.colors['step1'] = c1
        st.session_state.colors['step2'] = c2
        st.session_state.colors['step3'] = c3
        st.session_state.colors['step4'] = c4

    st.markdown("---")
    submit_button = st.button("🚀 คำนวณหา CBD (เฉพาะจุดที่เลือก)", type="primary", use_container_width=True)

# --- 3. Logic คำนวณ Geometry ---
def calculate_intersection(features, num_active_markers):
    # ต้องมีอย่างน้อย 2 จุดที่ Active จึงจะหา Intersection ได้
    if num_active_markers < 2: return None
    
    polys_per_marker = {}
    
    # Group geometries by marker_index
    for feat in features:
        m_idx = feat['properties']['marker_index']
        geom = shape(feat['geometry'])
        
        if m_idx not in polys_per_marker: 
            polys_per_marker[m_idx] = geom
        else: 
            polys_per_marker[m_idx] = polys_per_marker[m_idx].union(geom)
            
    # ต้องมี Polygon ครบทุกจุดที่ Active
    if len(polys_per_marker) < num_active_markers:
        return None

    # เริ่มหา Intersection จากจุดแรกที่มีข้อมูล
    available_indices = list(polys_per_marker.keys())
    intersection_poly = polys_per_marker[available_indices[0]]
    
    for i in available_indices[1:]:
        intersection_poly = intersection_poly.intersection(polys_per_marker[i])
        
    if intersection_poly.is_empty: return None
    return mapping(intersection_poly)

# --- 4. Logic เรียก API ---
if submit_button:
    # กรองเฉพาะ Marker ที่ Active
    active_markers_list = [m for m in st.session_state.markers if m.get('active', True)]
    
    if not api_key: st.warning("⚠️ กรุณาใส่ API Key")
    elif not active_markers_list: st.warning("⚠️ กรุณาเลือกจุดอย่างน้อย 1 จุด (ติ๊กถูก)")
    elif not time_intervals: st.warning("⚠️ กรุณาเลือกเวลา")
    else:
        with st.spinner(f'กำลังวิเคราะห์ข้อมูล {len(active_markers_list)} จุด...'):
            try:
                base_url = "https://api.geoapify.com/v1/isoline"
                all_features = []
                ranges_seconds = ",".join([str(t * 60) for t in sorted(time_intervals)])
                
                # Loop เฉพาะ Active Markers
                # เราต้อง Track index เดิมไว้ เพื่อใช้อ้างอิงสี (original_index)
                for i, marker in enumerate(st.session_state.markers):
                    if not marker.get('active', True):
                        continue # ข้ามจุดที่ไม่ได้เลือก
                        
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
                            # เก็บ Index เดิมไว้เพื่อใช้อ้างอิงสีให้ตรงกับจุด
                            feature['properties']['marker_index'] = i 
                            all_features.append(feature)
                    else:
                        st.error(f"API Error at Marker {i+1}: {response.text}")

                if all_features:
                    st.session_state.isochrone_data = {"type": "FeatureCollection", "features": all_features}
                    
                    # หา Intersection เฉพาะกลุ่มที่ Active
                    cbd_geom = calculate_intersection(all_features, len(active_markers_list))
                    
                    if cbd_geom:
                        st.session_state.intersection_data = {
                            "type": "FeatureCollection",
                            "features": [{"type": "Feature", "geometry": cbd_geom, "properties": {"type": "cbd"}}]
                        }
                        st.success(f"✅ พบพื้นที่ CBD ร่วมกันของ {len(active_markers_list)} จุด!")
                    else:
                        st.session_state.intersection_data = None
                        if len(active_markers_list) > 1:
                            st.warning("⚠️ ไม่พบพื้นที่ทับซ้อนสำหรับจุดที่เลือก")
                        else:
                            st.success("✅ คำนวณพื้นที่ (จุดเดียว) สำเร็จ")
                else:
                    st.error("ไม่ได้รับข้อมูลจาก API")
                    
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

    # หา Center Map: เอาจุด Active ล่าสุด หรือจุดสุดท้ายถ้าไม่มี Active
    active_ms = [m for m in st.session_state.markers if m.get('active', True)]
    if active_ms:
        last_m = active_ms[-1]
        center = [last_m['lat'], last_m['lng']]
    elif st.session_state.markers:
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

    # 1. วาด Isochrone Layers
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

    # 2. วาด Intersection (CBD)
    if st.session_state.intersection_data:
        folium.GeoJson(
            st.session_state.intersection_data,
            name='🏆 Common CBD Area',
            style_function=lambda feature: {
                'fillColor': '#FFD700', 'color': '#FF8C00',
                'weight': 3, 'fillOpacity': 0.6, 'dashArray': '5, 5'
            },
            tooltip="🏆 พื้นที่จุดศูนย์กลาง (เข้าถึงได้ตามเงื่อนไขที่เลือก)"
        ).add_to(m)

    # 3. วาด Markers (แยกสี Active / Inactive)
    for i, marker in enumerate(st.session_state.markers):
        is_active = marker.get('active', True)
        
        if is_active:
            color_name = MARKER_COLORS[i % len(MARKER_COLORS)]
            icon_type = "map-marker"
            opacity = 1.0
            popup_msg = f"<b>จุดที่ {i+1}</b> (Active)<br>ใช้คำนวณ"
        else:
            color_name = "gray" # ใช้สีเทาสำหรับ Inactive
            icon_type = "ban"   # ไอคอนเครื่องหมายห้าม หรือ eye-slash
            opacity = 0.5
            popup_msg = f"<b>จุดที่ {i+1}</b> (Inactive)<br>ไม่ถูกนำมาคำนวณ"

        folium.Marker(
            [marker['lat'], marker['lng']],
            popup=popup_msg,
            icon=folium.Icon(color=color_name, icon=icon_type, prefix='fa'),
            opacity=opacity
        ).add_to(m)

    folium.LayerControl().add_to(m)

    map_output = st_folium(
        m, 
        height=850, 
        use_container_width=True, 
        key="geoapify_ck_map"
    )
    
    # Logic การเพิ่มจุดใหม่จากการคลิก
    if map_output and map_output.get('last_clicked'):
        clicked_lat = map_output['last_clicked']['lat']
        clicked_lng = map_output['last_clicked']['lng']
        
        is_new = True
        if st.session_state.markers:
            last_mk = st.session_state.markers[-1]
            # Debounce: ป้องกันการคลิกซ้ำตำแหน่งเดิม
            if abs(clicked_lat - last_mk['lat']) < 0.00001 and abs(clicked_lng - last_mk['lng']) < 0.00001:
                is_new = False
        
        if is_new:
            # เพิ่มจุดใหม่ โดยให้ active = True เสมอ
            st.session_state.markers.append({'lat': clicked_lat, 'lng': clicked_lng, 'active': True})
            
            # Reset ผลลัพธ์เก่า เพื่อให้ User กดคำนวณใหม่
            st.session_state.isochrone_data = None
            st.session_state.intersection_data = None
            st.rerun()

display_map()
