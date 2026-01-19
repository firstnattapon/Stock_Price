import streamlit as st
import folium
from streamlit_folium import st_folium
from traveltimepy import TravelTimeSdk
from datetime import datetime

# --- 1. การตั้งค่าหน้าเว็บ ---
st.set_page_config(
    page_title="TravelTime Map",
    page_icon="⏱️",
    layout="wide"
)

# --- พิกัดเริ่มต้น (สยามพารากอน - เพื่อเทสต์รถไฟฟ้า) ---
DEFAULT_LAT = 13.746385 
DEFAULT_LON = 100.534966

# --- เตรียม Session State ---
if 'isochrone_data' not in st.session_state:
    st.session_state.isochrone_data = None

# 🟢 Logic ป้องกัน Error เวลารีรัน (Anti-flicker)
if 'temp_lat' in st.session_state:
    st.session_state.lat_input = st.session_state.temp_lat
    st.session_state.lon_input = st.session_state.temp_lon
    del st.session_state.temp_lat
    del st.session_state.temp_lon

st.title("⏱️ แผนที่ TravelTime (Public Transport & Drive)")

# --- 2. Sidebar ---
with st.sidebar:
    st.header("⚙️ ตั้งค่า TravelTime")
    
    # 🟢 ใส่ค่าเริ่มต้นที่คุณให้มาตรงนี้ครับ
    default_app_id = "9aef939d"
    default_api_key = "0f7019f3ef3242dbd3cc6bf776e2ebb6"
    
    app_id = st.text_input("App ID", value=default_app_id, type="password")
    api_key = st.text_input("API Key", value=default_api_key, type="password")
    
    st.markdown("---")
    
    # เลือกโหมดการเดินทาง
    travel_mode = st.selectbox(
        "รูปแบบการเดินทาง",
        options=["public_transport", "driving", "walking", "cycling"],
        index=0, # เริ่มต้นที่รถสาธารณะ
        format_func=lambda x: {
            "public_transport": "🚌🚋 รถสาธารณะ (รถเมล์/BTS)",
            "driving": "🚗 ขับรถ",
            "walking": "🚶 เดินเท้า",
            "cycling": "🚲 ปั่นจักรยาน"
        }[x]
    )
    
    # เลือกหลายช่วงเวลา
    st.write("⏱️ เลือกช่วงเวลา (นาที):")
    time_intervals = st.multiselect(
        "ระบุเวลา (เลือกได้หลายค่า)",
        options=[5, 10, 15, 30, 45, 60],
        default=[15, 30] # ค่าเริ่มต้น 15 และ 30 นาที
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
    if not api_key or not app_id:
        st.warning("⚠️ กรุณาตรวจสอบ App ID และ API Key")
    elif not time_intervals:
        st.warning("⚠️ เลือกเวลาอย่างน้อย 1 ค่า")
    else:
        with st.spinner('กำลังเชื่อมต่อระบบ TravelTime...'):
            try:
                sdk = TravelTimeSdk(app_id=app_id, api_key=api_key)
                
                # เรียงเวลาจากน้อยไปมาก และแปลงเป็นวินาที
                sorted_times = sorted(time_intervals)
                range_seconds = [t * 60 for t in sorted_times]
                
                # เรียก API
                geojson_result = sdk.time_map_geojson(
                    coordinates=[{"lat": st.session_state.lat_input, "lng": st.session_state.lon_input}],
                    transportation={"type": travel_mode},
                    travel_time=range_seconds,
                    departure_time=datetime.now().isoformat() 
                )
                
                st.session_state.isochrone_data = geojson_result
                
            except Exception as e:
                st.error(f"❌ เกิดข้อผิดพลาด: {e}")
                st.info("คำแนะนำ: ตรวจสอบโควต้า หรือลองลดจำนวนช่วงเวลาลง")

# --- 5. ฟังก์ชันเลือกสี ---
def get_color(seconds):
    minutes = seconds / 60
    if minutes <= 10: return '#2A9D8F'   # เขียว (ใกล้)
    elif minutes <= 20: return '#E9C46A' # เหลือง
    elif minutes <= 30: return '#F4A261' # ส้ม
    else: return '#E76F51'               # แดง (ไกล)

# --- 6. ฟังก์ชันวาดแผนที่ ---
def display_map():
    current_lat = st.session_state.lat_input
    current_lon = st.session_state.lon_input
    
    m = folium.Map(location=[current_lat, current_lon], zoom_start=13, tiles="CartoDB positron")
    
    if st.session_state.isochrone_data:
        folium.GeoJson(
            st.session_state.isochrone_data,
            name='TravelTime Area',
            style_function=lambda feature: {
                'fillColor': get_color(feature['properties']['travel_time']),
                'color': 'white',
                'weight': 1,
                'fillOpacity': 0.6
            },
            tooltip=folium.GeoJsonTooltip(
                fields=['travel_time'],
                aliases=['Time (sec):'],
                localize=True
            )
        ).add_to(m)
        
        folium.Marker([current_lat, current_lon], popup="จุดเริ่มต้น", icon=folium.Icon(color="red", icon="home")).add_to(m)
        st.caption("🟢 < 10 นาที | 🟡 10-20 นาที | 🟠 20-30 นาที | 🔴 > 30 นาที")
    else:
        folium.Marker([current_lat, current_lon], popup="Start", icon=folium.Icon(color="blue", icon="info-sign")).add_to(m)

    # แสดงแผนที่
    map_output = st_folium(m, width=1200, height=600, key="traveltime_map")

    # รับค่าคลิก
    if map_output['last_clicked']:
        clicked_lat = map_output['last_clicked']['lat']
        clicked_lng = map_output['last_clicked']['lng']
        
        if abs(clicked_lat - st.session_state.lat_input) > 0.000001:
            st.session_state.temp_lat = clicked_lat
            st.session_state.temp_lon = clicked_lng
            st.rerun()

# รันฟังก์ชัน
display_map()
