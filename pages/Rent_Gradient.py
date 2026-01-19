import streamlit as st
import folium
from streamlit_folium import st_folium
import requests  # 🟢 ใช้ requests ยิง API ตรงๆ ไม่ต้องง้อ SDK

# --- 1. การตั้งค่าหน้าเว็บ ---
st.set_page_config(
    page_title="Isochrone Map (Geoapify)",
    page_icon="🌍",
    layout="wide"
)

# --- พิกัดเริ่มต้น (เชียงของ, เชียงราย) ---
DEFAULT_LAT = 20.219443
DEFAULT_LON = 100.403630

# --- เตรียมตัวแปร Session State ---
if 'isochrone_data' not in st.session_state:
    st.session_state.isochrone_data = None

# 🟢 Logic เดิม: เช็คค่าคลิกก่อนวาด Input (ป้องกัน Error)
if 'temp_lat' in st.session_state and 'temp_lon' in st.session_state:
    st.session_state.lat_input = st.session_state.temp_lat
    st.session_state.lon_input = st.session_state.temp_lon
    del st.session_state.temp_lat
    del st.session_state.temp_lon

st.title("🌍 แผนที่ระยะการเดินทาง (Powered by Geoapify)")

# --- 2. Sidebar ---
with st.sidebar:
    st.header("⚙️ การตั้งค่า Geoapify")
    
    # 🟢 ใส่ API Key ของ Geoapify
    default_key = "4eefdfb0b0d349e595595b9c03a69e3d" # ใส่ Key ของคุณที่นี่ถ้าขี้เกียจพิมพ์ใหม่
    api_key = st.text_input("API Key", value=default_key, type="password", help="สมัครฟรีที่ geoapify.com")
    
    st.markdown("---")
    
    map_style = st.selectbox(
        "🎨 สไตล์แผนที่",
        options=["OpenStreetMap", "CartoDB positron", "CartoDB dark_matter"],
        index=0
    )
    
    # 🟢 โหมดการเดินทางของ Geoapify (ชื่อพารามิเตอร์ต่างจากเจ้าอื่นนิดหน่อย)
    travel_mode = st.selectbox(
        "รูปแบบการเดินทาง",
        options=["drive", "walk", "bicycle", "transit"], 
        format_func=lambda x: {
            "drive": "🚗 ขับรถ",
            "walk": "🚶 เดินเท้า",
            "bicycle": "🚲 ปั่นจักรยาน",
            "transit": "🚌 ขนส่งสาธารณะ (Transit)"
        }[x]
    )
    
    time_minutes = st.slider("เวลาเดินทาง (นาที)", 1, 60, 15)
    
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

# --- 4. Logic เรียก API (Geoapify Version) ---
if submit_button:
    if not api_key:
        st.warning("⚠️ กรุณาใส่ API Key")
    else:
        with st.spinner('กำลังเชื่อมต่อ Geoapify...'):
            try:
                # 🟢 สร้าง URL สำหรับเรียก API
                # Geoapify ใช้ method GET ง่ายๆ เลย
                base_url = "https://api.geoapify.com/v1/isoline"
                params = {
                    "lat": st.session_state.lat_input,
                    "lon": st.session_state.lon_input,
                    "type": "time",            # คำนวณตามเวลา (ถ้าใส่ distance จะคำนวณตามระยะทาง)
                    "mode": travel_mode,       # drive, walk, etc.
                    "range": time_minutes * 60, # แปลงเป็นวินาที
                    "apiKey": api_key
                }
                
                # ยิง Request
                response = requests.get(base_url, params=params)
                
                if response.status_code == 200:
                    # แปลงผลลัพธ์เป็น JSON เก็บใส่ Session
                    st.session_state.isochrone_data = response.json()
                else:
                    st.error(f"❌ API Error: {response.status_code}")
                    st.json(response.json()) # แสดง error message จาก server
                
            except Exception as e:
                st.error(f"❌ เกิดข้อผิดพลาด: {e}")

# --- 5. ฟังก์ชันวาดแผนที่ ---
def display_map():
    current_lat = st.session_state.lat_input
    current_lon = st.session_state.lon_input
    
    m = folium.Map(location=[current_lat, current_lon], zoom_start=13, tiles=map_style)
    
    if st.session_state.isochrone_data:
        area_color = '#00C896' if map_style != "CartoDB dark_matter" else '#FFD700'
        
        # วาด GeoJSON จาก Geoapify
        folium.GeoJson(
            st.session_state.isochrone_data,
            name='Available Area',
            style_function=lambda x: {'fillColor': area_color, 'color': area_color, 'weight': 2, 'fillOpacity': 0.4}
        ).add_to(m)
        
        folium.Marker([current_lat, current_lon], popup="จุดที่คำนวณ", icon=folium.Icon(color="red", icon="home")).add_to(m)
    else:
        folium.Marker([current_lat, current_lon], popup="จุดปัจจุบัน", icon=folium.Icon(color="blue", icon="info-sign")).add_to(m)

    # แสดงแผนที่
    map_output = st_folium(m, width=1200, height=600, key="main_map")

    # 🟢 Logic รับค่าคลิก (คงเดิม)
    if map_output['last_clicked']:
        clicked_lat = map_output['last_clicked']['lat']
        clicked_lng = map_output['last_clicked']['lng']
        
        if abs(clicked_lat - st.session_state.lat_input) > 0.000001 or abs(clicked_lng - st.session_state.lon_input) > 0.000001:
            st.session_state.temp_lat = clicked_lat
            st.session_state.temp_lon = clicked_lng
            st.rerun()

# เรียกใช้งาน
display_map()
