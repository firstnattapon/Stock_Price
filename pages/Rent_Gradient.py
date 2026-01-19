import streamlit as st
import openrouteservice
import folium
from streamlit_folium import st_folium

# --- 1. การตั้งค่าหน้าเว็บ ---
st.set_page_config(
    page_title="Multi-Isochrone Map",
    page_icon="🗺️",
    layout="wide"
)

# --- พิกัดเริ่มต้น (เชียงของ, เชียงราย) ---
DEFAULT_LAT = 20.219443
DEFAULT_LON = 100.403630

# --- เตรียมตัวแปร Session State ---
if 'isochrone_data' not in st.session_state:
    st.session_state.isochrone_data = None

# 🟢 Logic เดิม: เช็คค่าคลิกก่อนวาด Input
if 'temp_lat' in st.session_state and 'temp_lon' in st.session_state:
    st.session_state.lat_input = st.session_state.temp_lat
    st.session_state.lon_input = st.session_state.temp_lon
    del st.session_state.temp_lat
    del st.session_state.temp_lon

st.title("🗺️ แผนที่ระยะการเดินทางแบบหลายช่วงเวลา (Multi-Isochrone)")

# --- 2. Sidebar ---
with st.sidebar:
    st.header("⚙️ การตั้งค่า")
    default_key = "eyJvcmciOiI1YjNjZTM1OTc4NTExMTAwMDFjZjYyNDgiLCJpZCI6IjA0ZWVmNTA0Y2Y4YzQ3ZDZhZTYzNTFjNDEyZWY3OTRiIiwiaCI6Im11cm11cjY0In0="
    api_key = st.text_input("API Key", value=default_key, type="password")
    
    st.markdown("---")
    
    map_style = st.selectbox(
        "🎨 สไตล์แผนที่",
        options=["CartoDB positron", "OpenStreetMap", "CartoDB dark_matter"],
        index=0
    )
    
    travel_mode = st.selectbox(
        "รูปแบบการเดินทาง",
        options=["driving-car", "foot-walking", "cycling-regular"],
        format_func=lambda x: "🚗 ขับรถ" if x == "driving-car" else ("🚶 เดินเท้า" if x == "foot-walking" else "🚲 ปั่นจักรยาน")
    )
    
    # 🟢 เปลี่ยนจาก Slider เป็น MultiSelect เพื่อเลือกหลายเวลา
    st.write("⏱️ เลือกช่วงเวลา (นาที):")
    time_intervals = st.multiselect(
        "ระบุเวลาที่ต้องการ (เลือกได้หลายค่า)",
        options=[5, 10, 15, 20, 30, 45, 60],
        default=[5, 10, 15] # ค่าเริ่มต้น: 5, 10, 15 นาที
    )
    
    submit_button = st.button("🚀 คำนวณพื้นที่", use_container_width=True)

# --- 3. ส่วนกำหนดพิกัด ---
col1, col2 = st.columns(2)

if "lat_input" not in st.session_state:
    st.session_state.lat_input = DEFAULT_LAT
if "lon_input" not in st.session_state:
    st.session_state.lon_input = DEFAULT_LON

with col1:
    st.number_input("ละติจูด (Latitude)", format="%.6f", key="lat_input")
with col2:
    st.number_input("ลองจิจูด (Longitude)", format="%.6f", key="lon_input")

# --- 4. Logic เรียก API ---
if submit_button:
    if not api_key:
        st.warning("⚠️ กรุณาใส่ API Key")
    elif not time_intervals:
        st.warning("⚠️ กรุณาเลือกช่วงเวลาอย่างน้อย 1 ค่า")
    else:
        with st.spinner('กำลังคำนวณหลายช่วงเวลา...'):
            try:
                client = openrouteservice.Client(key=api_key)
                current_lat = st.session_state.lat_input
                current_lon = st.session_state.lon_input
                
                # 🟢 เรียงลำดับเวลา และแปลงเป็นวินาที
                sorted_times = sorted(time_intervals)
                range_seconds = [t * 60 for t in sorted_times]
                
                # เรียก API โดยส่ง list ของ range ไป
                isochrone = client.isochrones(
                    locations=[[current_lon, current_lat]],
                    profile=travel_mode,
                    range=range_seconds,
                    attributes=['total_pop'] # ข้อมูลเสริม
                )
                
                st.session_state.isochrone_data = isochrone
                
            except Exception as e:
                st.error(f"❌ เกิดข้อผิดพลาด: {e}")

# --- 5. ฟังก์ชันช่วยเลือกสี (Color Helper) ---
def get_color(value_seconds):
    minutes = value_seconds / 60
    if minutes <= 5:
        return '#2A9D8F'  # เขียวเข้ม (ใกล้สุด)
    elif minutes <= 10:
        return '#E9C46A'  # เหลือง
    elif minutes <= 15:
        return '#F4A261'  # ส้ม
    else:
        return '#E76F51'  # แดง (ไกลสุด)

# --- 6. ฟังก์ชันวาดแผนที่ ---
def display_map():
    current_lat = st.session_state.lat_input
    current_lon = st.session_state.lon_input
    
    m = folium.Map(location=[current_lat, current_lon], zoom_start=13, tiles=map_style)
    
    if st.session_state.isochrone_data:
        # 🟢 วาด GeoJson โดยใช้ style_function แยกสีตามเวลา
        folium.GeoJson(
            st.session_state.isochrone_data,
            name='Isochrones',
            style_function=lambda feature: {
                'fillColor': get_color(feature['properties']['value']), # ใช้ฟังก์ชันเลือกสี
                'color': 'white',       # สีเส้นขอบ
                'weight': 1,            # ความหนาเส้นขอบ
                'fillOpacity': 0.5      # ความโปร่งแสง
            },
            tooltip=folium.GeoJsonTooltip(
                fields=['value'],
                aliases=['Time (sec):'],
                localize=True
            )
        ).add_to(m)
        
        # ปักหมุด
        folium.Marker([current_lat, current_lon], popup="จุดเริ่มต้น", icon=folium.Icon(color="red", icon="home")).add_to(m)
        
        # 🟢 แสดงคำอธิบายสี (Legend) แบบง่ายๆ
        st.markdown("""
        **ความหมายสี:** 🟢 < 5 นาที | 🟡 5-10 นาที | 🟠 10-15 นาที | 🔴 > 15 นาที
        """, unsafe_allow_html=True)
        
    else:
        folium.Marker([current_lat, current_lon], popup="จุดปัจจุบัน", icon=folium.Icon(color="blue", icon="info-sign")).add_to(m)

    # แสดงแผนที่
    map_output = st_folium(m, width=1200, height=600, key="main_map")

    # Logic รับค่าคลิก (เหมือนเดิม)
    if map_output['last_clicked']:
        clicked_lat = map_output['last_clicked']['lat']
        clicked_lng = map_output['last_clicked']['lng']
        
        if abs(clicked_lat - st.session_state.lat_input) > 0.000001 or abs(clicked_lng - st.session_state.lon_input) > 0.000001:
            st.session_state.temp_lat = clicked_lat
            st.session_state.temp_lon = clicked_lng
            st.rerun()

# เรียกใช้งาน
display_map()
