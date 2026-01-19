import streamlit as st
import folium
from streamlit_folium import st_folium
import requests # 🟢 ใช้ requests ยิง API ตรงๆ ไม่ง้อ Library
import json
from datetime import datetime

# --- 1. การตั้งค่าหน้าเว็บ ---
st.set_page_config(
    page_title="TravelTime Map (Direct API)",
    page_icon="⏱️",
    layout="wide"
)

# --- พิกัดเริ่มต้น (สยามพารากอน) ---
DEFAULT_LAT = 13.746385 
DEFAULT_LON = 100.534966

# --- เตรียม Session State ---
if 'isochrone_data' not in st.session_state:
    st.session_state.isochrone_data = None

# Logic ป้องกันกระพริบ
if 'temp_lat' in st.session_state:
    st.session_state.lat_input = st.session_state.temp_lat
    st.session_state.lon_input = st.session_state.temp_lon
    del st.session_state.temp_lat
    del st.session_state.temp_lon

st.title("⏱️ แผนที่ TravelTime (แบบยิง API ตรง)")

# --- 2. Sidebar ---
with st.sidebar:
    st.header("⚙️ การตั้งค่า")
    
    # ค่า Default
    default_app_id = "9aef939d"
    default_api_key = "0f7019f3ef3242dbd3cc6bf776e2ebb6"
    
    app_id = st.text_input("App ID", value=default_app_id, type="password")
    api_key = st.text_input("API Key", value=default_api_key, type="password")
    
    st.markdown("---")
    
    travel_mode = st.selectbox(
        "รูปแบบการเดินทาง",
        options=["public_transport", "driving", "walking", "cycling"],
        index=0, 
        format_func=lambda x: {
            "public_transport": "🚌🚋 รถสาธารณะ (รถเมล์/BTS)",
            "driving": "🚗 ขับรถ",
            "walking": "🚶 เดินเท้า",
            "cycling": "🚲 ปั่นจักรยาน"
        }[x]
    )
    
    st.write("⏱️ เลือกช่วงเวลา (นาที):")
    time_intervals = st.multiselect(
        "ระบุเวลา (เลือกได้หลายค่า)",
        options=[5, 10, 15, 30, 45, 60],
        default=[15, 30]
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

# --- 4. Logic เรียก API (แบบ Direct HTTP Request) ---
if submit_button:
    if not api_key or not app_id:
        st.warning("⚠️ กรุณากรอก App ID และ API Key")
    elif not time_intervals:
        st.warning("⚠️ กรุณาเลือกเวลา")
    else:
        with st.spinner('กำลังยิงข้อมูลไป TravelTime Server...'):
            try:
                # 🟢 1. เตรียม URL และ Headers
                url = "https://api.traveltimeapp.com/v4/time-map"
                headers = {
                    "X-Application-Id": app_id,
                    "X-Api-Key": api_key,
                    "Content-Type": "application/json"
                }

                # 🟢 2. เตรียมข้อมูล (Payload) ตามรูปแบบของ TravelTime API
                # ต้องแปลงนาทีเป็นวินาที และสร้าง JSON structure เอง
                sorted_times = sorted(time_intervals)
                departure_time = datetime.now().isoformat()
                
                # สร้าง Payload แบบละเอียด
                payload = {
                    "departure_searches": [
                        {
                            "id": "public_transport_search",
                            "coords": {"lat": st.session_state.lat_input, "lng": st.session_state.lon_input},
                            "transportation": {"type": travel_mode},
                            "departure_time": departure_time,
                            "travel_time": t * 60, # วินาที
                            "range": {"enabled": True, "width": 900} if travel_mode == "public_transport" else {}
                        } for t in sorted_times # สร้างหลาย search ตามจำนวนเวลาที่เลือก
                    ]
                }
                
                # 🟢 3. ยิง Request
                response = requests.post(url, headers=headers, json=payload)
                
                # 🟢 4. ตรวจสอบผลลัพธ์
                if response.status_code == 200:
                    data = response.json()
                    
                    # แปลงข้อมูลดิบให้เป็น GeoJSON ที่ Folium เข้าใจ
                    # (ต้อง Manual นิดหน่อยเพราะเราไม่ได้ใช้ SDK)
                    features = []
                    for result in data['results']:
                        for shape in result['shapes']:
                            # สร้าง Polygon
                            shell = [[pt['lng'], pt['lat']] for pt in shape['shell']]
                            holes = [[[pt['lng'], pt['lat']] for pt in hole] for hole in shape['holes']]
                            
                            features.append({
                                "type": "Feature",
                                "properties": {
                                    "travel_
