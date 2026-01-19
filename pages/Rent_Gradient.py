import streamlit as st
import openrouteservice
import folium
from streamlit_folium import st_folium

# --- 1. การตั้งค่าหน้าเว็บ ---
st.set_page_config(
    page_title="Isochrone Map Generator",
    page_icon="🗺️",
    layout="wide"
)

# --- พิกัดเริ่มต้น ---
DEFAULT_LAT = 20.219443
DEFAULT_LON = 100.403630

# --- เตรียมตัวแปร Session State ---
if 'isochrone_data' not in st.session_state:
    st.session_state.isochrone_data = None

# 🟢 ส่วนสำคัญ 1: เช็คว่ามีการคลิกจากรอบที่แล้วหรือไม่ (ต้องทำก่อนวาด Input Box)
if 'temp_lat' in st.session_state and 'temp_lon' in st.session_state:
    # อัปเดตค่าลงใน key ของ widget โดยตรง "ก่อน" ที่ widget จะถูกสร้าง
    st.session_state.lat_input = st.session_state.temp_lat
    st.session_state.lon_input = st.session_state.temp_lon
    # ลบค่าทิ้ง เพื่อไม่ให้มันอัปเดตซ้ำซ้อน
    del st.session_state.temp_lat
    del st.session_state.temp_lon

st.title("🗺️ แผนที่คำนวณระยะการเดินทาง (Isochrone Map)")

# --- 2. Sidebar ---
with st.sidebar:
    st.header("⚙️ การตั้งค่า")
    default_key = "eyJvcmciOiI1YjNjZTM1OTc4NTExMTAwMDFjZjYyNDgiLCJpZCI6IjA0ZWVmNTA0Y2Y4YzQ3ZDZhZTYzNTFjNDEyZWY3OTRiIiwiaCI6Im11cm11cjY0In0="
    api_key = st.text_input("API Key", value=default_key, type="password")
    
    st.markdown("---")
    
    map_style = st.selectbox(
        "🎨 สไตล์แผนที่",
        options=["OpenStreetMap", "CartoDB positron", "CartoDB dark_matter"],
        index=0
    )
    
    travel_mode = st.selectbox(
        "รูปแบบการเดินทาง",
        options=["driving-car", "foot-walking", "cycling-regular"],
        format_func=lambda x: "🚗 ขับรถ" if x == "driving-car" else ("🚶 เดินเท้า" if x == "foot-walking" else "🚲 ปั่นจักรยาน")
    )
    
    time_minutes = st.slider("เวลาเดินทาง (นาที)", 1, 60, 15)
    
    submit_button = st.button("🚀 คำนวณพื้นที่", use_container_width=True)

# --- 3. ส่วนกำหนดพิกัด ---
col1, col2 = st.columns(2)

# กำหนดค่าเริ่มต้นให้กับ key ถ้ายังไม่มี (เพื่อป้องกัน error ในครั้งแรกสุด)
if "lat_input" not in st.session_state:
    st.session_state.lat_input = DEFAULT_LAT
if "lon_input" not in st.session_state:
    st.session_state.lon_input = DEFAULT_LON

with col1:
    # 🟢 ลบ on_change ออก เพื่อลดความซับซ้อน (Streamlit จะจัดการ key ให้อัตโนมัติ)
    st.number_input("ละติจูด (Latitude)", format="%.6f", key="lat_input")
with col2:
    st.number_input("ลองจิจูด (Longitude)", format="%.6f", key="lon_input")

# --- 4. Logic เรียก API ---
if submit_button:
    if not api_key:
        st.warning("⚠️ กรุณาใส่ API Key")
    else:
        with st.spinner('กำลังคำนวณ...'):
            try:
                client = openrouteservice.Client(key=api_key)
                # ดึงค่าจาก st.session_state โดยตรง
                current_lat = st.session_state.lat_input
                current_lon = st.session_state.lon_input
                
                range_seconds = time_minutes * 60
                
                isochrone = client.isochrones(
                    locations=[[current_lon, current_lat]],
                    profile=travel_mode,
                    range=[range_seconds]
                )
                
                st.session_state.isochrone_data = isochrone
                
            except Exception as e:
                st.error(f"❌ เกิดข้อผิดพลาด: {e}")

# --- 5. ฟังก์ชันวาดแผนที่ ---
def display_map():
    # ดึงค่าปัจจุบัน
    current_lat = st.session_state.lat_input
    current_lon = st.session_state.lon_input
    
    m = folium.Map(location=[current_lat, current_lon], zoom_start=13, tiles=map_style)
    
    if st.session_state.isochrone_data:
        area_color = '#00C896' if map_style != "CartoDB dark_matter" else '#FFD700'
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

    # 🟢 ส่วนสำคัญ 2: Logic รับค่าคลิกที่แก้ไขแล้ว
    if map_output['last_clicked']:
        clicked_lat = map_output['last_clicked']['lat']
        clicked_lng = map_output['last_clicked']['lng']
        
        # เช็คว่าค่าเปลี่ยนไปจริงไหม (ป้องกัน loop)
        # หมายเหตุ: เปรียบเทียบกับ session state ปัจจุบัน
        if abs(clicked_lat - st.session_state.lat_input) > 0.000001 or abs(clicked_lng - st.session_state.lon_input) > 0.000001:
            
            # ❌ อย่าแก้ st.session_state.lat_input ตรงนี้ (จะ error)
            # ✅ ให้ฝากค่าไว้ในตัวแปรชั่วคราวแทน
            st.session_state.temp_lat = clicked_lat
            st.session_state.temp_lon = clicked_lng
            
            # สั่งรันใหม่ -> เพื่อให้โค้ดส่วนบนสุด (ส่วนสำคัญ 1) ทำงาน
            st.rerun()

# เรียกใช้งาน
display_map()
