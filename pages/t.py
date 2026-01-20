import streamlit as st
import folium
from streamlit_folium import st_folium
import requests
from shapely.geometry import shape, mapping
from shapely.ops import unary_union
import json

# --- 1. การตั้งค่าหน้าเว็บ ---
st.set_page_config(
    page_title="Geoapify Map (Chiang Khong CBD)",
    page_icon="🌍",
    layout="wide"
)

# --- พิกัดเริ่มต้น (เชียงของ) ---
DEFAULT_LAT = 20.219443
DEFAULT_LON = 100.403630

# --- เตรียม Session State ---
if 'markers' not in st.session_state:
    st.session_state.markers = [{'lat': DEFAULT_LAT, 'lng': DEFAULT_LON}]

if 'isochrone_data' not in st.session_state:
    st.session_state.isochrone_data = None

if 'intersection_data' not in st.session_state:
    st.session_state.intersection_data = None  # เก็บข้อมูลพื้นที่ CBD

# เตรียมสี (เก็บไว้เหมือนเดิม)
if 'colors' not in st.session_state:
    st.session_state.colors = {
        'step1': '#2A9D8F', 'step2': '#E9C46A', 
        'step3': '#F4A261', 'step4': '#D62828'
    }

MARKER_COLORS = ['red', 'blue', 'green', 'purple', 'orange', 'black', 'pink', 'cadetblue']
HEX_COLORS = ['#D63E2A', '#38AADD', '#72B026', '#D252B9', '#F69730', '#333333', '#FF91EA', '#436978']

st.caption("🌍 Geoapify: ค้นหาจุดศูนย์กลาง (Local CBD)")
st.caption(f"📍 พิกัดเริ่มต้น: {DEFAULT_LAT}, {DEFAULT_LON}")

# --- 2. Sidebar ---
with st.sidebar:
    st.header("⚙️ การตั้งค่า")
    
    default_key = "4eefdfb0b0d349e595595b9c03a69e3d"
    api_key = st.text_input("API Key", value=default_key, type="password")
    
    st.markdown("---")
    
    # ปุ่มจัดการหมุด
    col_btn1, col_btn2 = st.columns(2)
    with col_btn1:
        if st.button("❌ ลบจุดล่าสุด", use_container_width=True):
            if st.session_state.markers:
                st.session_state.markers.pop()
                st.session_state.isochrone_data = None # Reset ผลลัพธ์เมื่อข้อมูลเปลี่ยน
                st.session_state.intersection_data = None
                st.rerun()
    with col_btn2:
        if st.button("🔄 รีเซ็ต (เชียงของ)", use_container_width=True):
            st.session_state.markers = [{'lat': DEFAULT_LAT, 'lng': DEFAULT_LON}]
            st.session_state.isochrone_data = None
            st.session_state.intersection_data = None
            st.rerun()
            
    st.write(f"📍 จำนวนจุด: **{len(st.session_state.markers)}**")
    
    # แสดงรายการจุด
    if st.session_state.markers:
        st.markdown("---")
        for i, m in enumerate(st.session_state.markers):
            color_name = MARKER_COLORS[i % len(MARKER_COLORS)]
            st.markdown(f"<span style='color:{color_name};'>●</span> จุดที่ {i+1} ({m['lat']:.4f}, {m['lng']:.4f})", unsafe_allow_html=True)

    st.markdown("---")
    
    map_style = st.selectbox("สไตล์แผนที่", ["OpenStreetMap", "CartoDB positron", "CartoDB dark_matter"])
    
    travel_mode = st.selectbox(
        "รูปแบบการเดินทาง",
        options=["drive", "walk", "bicycle", "transit"], 
        format_func=lambda x: {"drive": "🚗 ขับรถ", "walk": "🚶 เดินเท้า", "bicycle": "🚲 ปั่นจักรยาน", "transit": "🚌 ขนส่งสาธารณะ"}[x]
    )
    
    # ให้เลือกได้แค่ค่าเดียวสำหรับ CBD เพื่อความชัดเจน หรือหลายค่าก็ได้ (ในที่นี้รองรับหลายค่าแต่จะหา CBD ของค่าสูงสุดที่เลือก)
    # แก้ไขส่วน time_intervals
    time_intervals = st.multiselect(
        "ช่วงเวลา (นาที)", 
        options=[5, 10, 15, 20, 30, 45, 60], # เพิ่ม 20 ตรงนี้
        default=[5 , 10]
    )
    
    with st.expander("🎨 ตั้งค่าสีพื้นที่"):
        st.session_state.colors['step1'] = st.color_picker("≤ 10 นาที", st.session_state.colors['step1'])
        st.session_state.colors['step2'] = st.color_picker("11 - 20 นาที", st.session_state.colors['step2'])
        st.session_state.colors['step3'] = st.color_picker("21 - 30 นาที", st.session_state.colors['step3'])
        st.session_state.colors['step4'] = st.color_picker("> 30 นาที", st.session_state.colors['step4'])

    st.markdown("---")
    submit_button = st.button("🚀 คำนวณหา CBD", type="primary", use_container_width=True)

# --- 3. Logic คำนวณ Geometry (Helper) ---
def calculate_intersection(features, num_markers):
    """
    ฟังก์ชันหาพื้นที่ทับซ้อน (Intersection) ของทุกจุด
    """
    if num_markers < 2:
        return None # จุดเดียวไม่มี Intersection กับใคร
    
    # จัดกลุ่ม Polygon ตามเวลา (value)
    # เราต้องการหา Intersection ของ Polygon ที่มาจากคนละ Marker แต่เวลาเดียวกัน (หรือเวลาที่กำหนด)
    # เพื่อความง่ายใน MVP: เราจะหา Intersection ของเวลา 'สูงสุด' ที่เลือก เพื่อดูขอบเขตที่กว้างที่สุดที่ทุกคนมาเจอกันได้
    
    polys_per_marker = {} # key: marker_index, value: list of polygons
    
    for feat in features:
        m_idx = feat['properties']['marker_index']
        geom = shape(feat['geometry'])
        
        if m_idx not in polys_per_marker:
            polys_per_marker[m_idx] = geom
        else:
            # ถ้า 1 marker มีหลายวง (หลายช่วงเวลา) ให้เอาวงที่ใหญ่ที่สุด (Union ตัวเอง) เพื่อเป็นตัวแทนความสามารถในการเดินทางของจุดนั้น
            polys_per_marker[m_idx] = polys_per_marker[m_idx].union(geom)
    
    # เริ่มต้นหา Intersection
    if not polys_per_marker:
        return None

    # เริ่มจาก Polygon ของจุดแรก
    intersection_poly = polys_per_marker[0]
    
    # Loop หาจุดตัดกับจุดอื่นๆ
    for i in range(1, num_markers):
        if i in polys_per_marker:
            intersection_poly = intersection_poly.intersection(polys_per_marker[i])
    
    if intersection_poly.is_empty:
        return None
        
    return mapping(intersection_poly)

# --- 4. Logic เรียก API ---
if submit_button:
    if not api_key:
        st.warning("⚠️ กรุณาใส่ API Key")
    elif not st.session_state.markers:
        st.warning("⚠️ กรุณาเพิ่มหมุด")
    elif not time_intervals:
        st.warning("⚠️ กรุณาเลือกเวลา")
    else:
        with st.spinner(f'กำลังวิเคราะห์ข้อมูลจาก {len(st.session_state.markers)} จุด...'):
            try:
                base_url = "https://api.geoapify.com/v1/isoline"
                all_features = []
                ranges_seconds = ",".join([str(t * 60) for t in sorted(time_intervals)])
                
                # 1. Fetch Data
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
                    else:
                        st.error(f"❌ API Error จุดที่ {i+1}: {response.status_code}")
                
                # 2. Process Data & Calculate Intersection
                if all_features:
                    st.session_state.isochrone_data = {"type": "FeatureCollection", "features": all_features}
                    
                    # คำนวณ Intersection (CBD Logic)
                    cbd_geom = calculate_intersection(all_features, len(st.session_state.markers))
                    if cbd_geom:
                        st.session_state.intersection_data = {
                            "type": "FeatureCollection",
                            "features": [{
                                "type": "Feature",
                                "geometry": cbd_geom,
                                "properties": {"type": "cbd"}
                            }]
                        }
                        st.success(f"✅ พบพื้นที่ CBD ร่วมกัน!")
                    else:
                        st.session_state.intersection_data = None
                        if len(st.session_state.markers) > 1:
                            st.warning("⚠️ ไม่พบพื้นที่ทับซ้อน (จุดห่างกันเกินไป)")
                        else:
                            st.success("✅ คำนวณสำเร็จ (จุดเดียวไม่มีพื้นที่ทับซ้อน)")
                            
            except Exception as e:
                st.error(f"❌ เกิดข้อผิดพลาด: {e}")

# --- 5. Helper Functions ---
def get_fill_color(minutes):
    c = st.session_state.colors
    if minutes <= 10: return c['step1']
    elif minutes <= 20: return c['step2']
    elif minutes <= 30: return c['step3']
    else: return c['step4']

def get_border_color(marker_idx):
    if marker_idx is not None:
        return HEX_COLORS[marker_idx % len(HEX_COLORS)]
    return '#3388ff'

# --- 6. Display Map ---
def display_map():
    # Center logic
    if st.session_state.markers:
        last_m = st.session_state.markers[-1]
        center = [last_m['lat'], last_m['lng']]
    else:
        center = [DEFAULT_LAT, DEFAULT_LON]

    m = folium.Map(location=center, zoom_start=11, tiles=map_style)

    # 1. วาด Isochrones ปกติ (Background)
    if st.session_state.isochrone_data:
        folium.GeoJson(
            st.session_state.isochrone_data,
            name='Travel Areas',
            style_function=lambda feature: {
                'fillColor': get_fill_color(feature['properties']['travel_time_minutes']),
                'color': get_border_color(feature['properties']['marker_index']),
                'weight': 1, 
                'fillOpacity': 0.2  # ลดความเข้มลงเพื่อให้เห็น CBD ชัดขึ้น
            },
            tooltip=folium.GeoJsonTooltip(fields=['travel_time_minutes'], aliases=['นาที:'])
        ).add_to(m)

    # 2. วาด Intersection Area (CBD) - Highlight
    if st.session_state.intersection_data:
        folium.GeoJson(
            st.session_state.intersection_data,
            name='🏆 Common CBD Area',
            style_function=lambda feature: {
                'fillColor': '#FFD700',  # สีทอง
                'color': '#FF8C00',      # ขอบส้มเข้ม
                'weight': 3, 
                'fillOpacity': 0.6,
                'dashArray': '5, 5'
            },
            tooltip="🏆 พื้นที่จุดศูนย์กลาง (เข้าถึงได้ทุกคน)"
        ).add_to(m)

    # 3. วาด Markers
    for i, marker in enumerate(st.session_state.markers):
        color_name = MARKER_COLORS[i % len(MARKER_COLORS)]
        folium.Marker(
            [marker['lat'], marker['lng']],
            popup=f"จุดที่ {i+1} ({color_name})",
            icon=folium.Icon(color=color_name, icon="map-marker", prefix='fa')
        ).add_to(m)

    # Layer Control เพื่อเปิด-ปิด Layer ได้
    folium.LayerControl().add_to(m)

    map_output = st_folium(m, width=1200, height=600, key="geoapify_ck_map")
    
    # Logic การคลิกเพิ่มจุด
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
