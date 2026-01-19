import streamlit as st
import folium
from streamlit_folium import st_folium
from datetime import datetime

# พยายาม Import Library (พร้อมดัก Error แจ้งเตือน)
try:
    from traveltimepy
except ImportError:
    st.error("❌ ไม่พบ Library 'traveltimepy' กรุณาพิมพ์คำสั่งนี้ใน Terminal: pip install traveltimepy")
    st.stop()

# --- 1. การตั้งค่าหน้าเว็บ ---
st.set_page_config(
    page_title="TravelTime Map Generator",
    page_icon="⏱️",
    layout="wide"
)

# --- พิกัดเริ่มต้น (สยามพารากอน - เพื่อทดสอบรถไฟฟ้า/เดิน) ---
DEFAULT_LAT = 13.746385 
DEFAULT_LON = 100.534966

# --- เตรียม Session State ---
if 'isochrone_data' not in st.session_state:
    st.session_state.isochrone_data = None

# 🟢 Logic: ป้องกันการกระพริบ (Anti-flicker) และอัปเดตค่าจากการคลิก
if 'temp_lat' in st.session_state and 'temp_lon' in st.session_state:
    st.session_state.lat_input = st.session_state.temp_lat
    st.session_state.lon_input = st.session_state.temp_lon
    # ลบค่าชั่วคราวทิ้ง
    del st.session_state.temp_lat
    del st.session_state.temp_lon

st.title("⏱️ แผนที่คำนวณระยะเวลาเดินทาง (TravelTime API)")
st.caption("รองรับ: รถสาธารณะ (BTS/MRT/รถเมล์), ขับรถ, เดินเท้า, ปั่นจักรยาน")

# --- 2. Sidebar: ตั้งค่า API และ Parameter ---
with st.sidebar:
    st.header("⚙️ การตั้งค่า")
    
    # 🟢 ค่า Default จากที่คุณให้มา
    default_app_id = "9aef939d"
    default_api_key = "0f7019f3ef3242dbd3cc6bf776e2ebb6"
    
    app_id = st.text_input("App ID", value=default_app_id, type="password")
    api_key = st.text_input("API Key", value=default_api_key, type="password")

    
    
    st.markdown("---")
    
    # เลือกโหมดการเดินทาง
    travel_mode = st.selectbox(
        "รูปแบบการเดินทาง",
        options=["public_transport", "driving", "walking", "cycling"],
        index=0, # Default เป็นรถสาธารณะ
        format_func=lambda x: {
            "public_transport": "🚌🚋 รถสาธารณะ (รถเมล์/BTS)",
            "driving": "🚗 ขับรถ",
            "walking": "🚶 เดินเท้า",
            "cycling": "🚲 ปั่นจักรยาน"
        }[x]
    )
    
    # เลือกเวลา (Multi-select)
    st.write("⏱️ เลือกช่วงเวลา (นาที):")
    time_intervals = st.multiselect(
        "ระบุเวลา (เลือกได้หลายค่า)",
        options=[5, 10, 15, 30, 45, 60],
        default=[15, 30] # ค่าเริ่มต้น
    )
    
    submit_button = st.button("🚀 คำนวณพื้นที่", use_container_width=True)

# --- 3. ส่วนกำหนดพิกัด (Input Boxes) ---
col1, col2 = st.columns(2)

# กำหนดค่าเริ่มต้นให้ Session State ถ้ายังไม่มี
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
        st.warning("⚠️ กรุณาเลือกเวลาอย่างน้อย 1 ค่า")
    else:
        with st.spinner('กำลังเชื่อมต่อระบบ TravelTime...'):
            try:
                # เริ่มต้น SDK
                sdk = traveltimepy.TravelTimeSdk(app_id=app_id, api_key=api_key)
                
                # เตรียมข้อมูลเวลา
                sorted_times = sorted(time_intervals)
                range_seconds = [t * 60 for t in sorted_times] # แปลงนาทีเป็นวินาที
                
                # เรียก API (ต้องใส่ departure_time เป็นปัจจุบัน)
                geojson_result = sdk.time_map_geojson(
                    coordinates=[{"lat": st.session_state.lat_input, "lng": st.session_state.lon_input}],
                    transportation={"type": travel_mode},
                    travel_time=range_seconds,
                    departure_time=datetime.now().isoformat()
                )
                
                # บันทึกผลลัพธ์
                st.session_state.isochrone_data = geojson_result
                
            except Exception as e:
                st.error(f"❌ เกิดข้อผิดพลาด: {e}")
                st.info("คำแนะนำ: ตรวจสอบโควต้า หรือลองลดจำนวนช่วงเวลาลง")

# --- 5. ฟังก์ชันเลือกสี (ตามเวลาเดินทาง) ---
def get_color(seconds):
    minutes = seconds / 60
    if minutes <= 10: return '#2A9D8F'   # เขียว (ใกล้)
    elif minutes <= 20: return '#E9C46A' # เหลือง
    elif minutes <= 30: return '#F4A261' # ส้ม
    elif minutes <= 45: return '#E76F51' # ส้มแดง
    else: return '#D62828'               # แดงเข้ม (ไกล)

# --- 6. ฟังก์ชันแสดงแผนที่ ---
def display_map():
    current_lat = st.session_state.lat_input
    current_lon = st.session_state.lon_input
    
    # สร้างแผนที่พื้นหลัง
    m = folium.Map(location=[current_lat, current_lon], zoom_start=13, tiles="CartoDB positron")
    
    # ถ้ามีข้อมูลจากการคำนวณ ให้วาดลงไป
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
        
        # ปักหมุดจุดเริ่มต้น
        folium.Marker([current_lat, current_lon], popup="จุดเริ่มต้น", icon=folium.Icon(color="red", icon="home")).add_to(m)
        
        # แสดงคำอธิบายสี
        st.markdown("**ความหมายสี:** 🟢 <10น. | 🟡 10-20น. | 🟠 20-30น. | 🔴 >30น.")
        
    else:
        # ปักหมุดจุดปัจจุบัน (กรณีเปิดมาครั้งแรก)
        folium.Marker([current_lat, current_lon], popup="Start", icon=folium.Icon(color="blue", icon="info-sign")).add_to(m)

    # แสดงผลแผนที่และรอรับค่าคลิก
    map_output = st_folium(m, width=1200, height=600, key="traveltime_map")

    # --- Logic: คลิกเพื่อเปลี่ยนพิกัด ---
    if map_output['last_clicked']:
        clicked_lat = map_output['last_clicked']['lat']
        clicked_lng = map_output['last_clicked']['lng']
        
        # เช็คว่าพิกัดเปลี่ยนไปจริงไหม (ป้องกัน Loop)
        if abs(clicked_lat - st.session_state.lat_input) > 0.000001:
            st.session_state.temp_lat = clicked_lat
            st.session_state.temp_lon = clicked_lng
            st.rerun()

# เรียกใช้งานฟังก์ชัน
display_map()
