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

# --- กำหนดพิกัดเริ่มต้น (เชียงของ, เชียงราย) ---
DEFAULT_LAT = 20.219443
DEFAULT_LON = 100.403630

# --- เตรียมตัวแปรจำค่า (Session State) ---
if 'isochrone_data' not in st.session_state:
    st.session_state.isochrone_data = None  # เก็บข้อมูล JSON
if 'map_center' not in st.session_state:
    st.session_state.map_center = [DEFAULT_LAT, DEFAULT_LON] # เก็บจุดศูนย์กลาง

st.title("🗺️ แผนที่คำนวณระยะการเดินทาง (Isochrone Map)")

# --- 2. Sidebar ตั้งค่า ---
with st.sidebar:
    st.header("⚙️ การตั้งค่า")
    
    # API Key
    default_key = "eyJvcmciOiI1YjNjZTM1OTc4NTExMTAwMDFjZjYyNDgiLCJpZCI6IjA0ZWVmNTA0Y2Y4YzQ3ZDZhZTYzNTFjNDEyZWY3OTRiIiwiaCI6Im11cm11cjY0In0="
    api_key = st.text_input("API Key", value=default_key, type="password")
    
    st.markdown("---")
    
    # 🟢 เพิ่ม: ตัวเลือกสไตล์แผนที่
    map_style = st.selectbox(
        "🎨 สไตล์แผนที่",
        options=["OpenStreetMap", "CartoDB positron", "CartoDB dark_matter"],
        index=0,
        format_func=lambda x: "มาตรฐาน (สี)" if x == "OpenStreetMap" else ("คลีน (ขาว-เทา)" if x == "CartoDB positron" else "โหมดมืด (Dark)")
    )
    
    # ตัวเลือกการเดินทาง
    travel_mode = st.selectbox(
        "รูปแบบการเดินทาง",
        options=["driving-car", "foot-walking", "cycling-regular"],
        format_func=lambda x: "🚗 ขับรถ" if x == "driving-car" else ("🚶 เดินเท้า" if x == "foot-walking" else "🚲 ปั่นจักรยาน")
    )
    
    time_minutes = st.slider("เวลาเดินทาง (นาที)", 1, 60, 15)
    
    # ปุ่มคำนวณ
    submit_button = st.button("🚀 คำนวณพื้นที่", use_container_width=True)

# --- 3. ส่วนกำหนดพิกัด ---
col1, col2 = st.columns(2)
with col1:
    lat_input = st.number_input("ละติจูด (Latitude)", value=DEFAULT_LAT, format="%.6f")
with col2:
    lon_input = st.number_input("ลองจิจูด (Longitude)", value=DEFAULT_LON, format="%.6f")

# --- 4. Logic การเรียก API (ทำเมื่อกดปุ่มเท่านั้น) ---
if submit_button:
    if not api_key:
        st.warning("⚠️ กรุณาใส่ API Key")
    else:
        with st.spinner('กำลังคำนวณ...'):
            try:
                client = openrouteservice.Client(key=api_key)
                range_seconds = time_minutes * 60
                center_point_ors = [lon_input, lat_input] # ORS ใช้ [Lon, Lat]
                
                # เรียก API
                isochrone = client.isochrones(
                    locations=[center_point_ors],
                    profile=travel_mode,
                    range=[range_seconds]
                )
                
                # บันทึกผลลัพธ์
                st.session_state.isochrone_data = isochrone
                st.session_state.map_center = [lat_input, lon_input]
                
            except Exception as e:
                st.error(f"❌ เกิดข้อผิดพลาด: {e}")

# --- 5. ฟังก์ชันวาดแผนที่ ---
def display_map():
    center = st.session_state.map_center
    
    # 🟢 ใช้สไตล์แผนที่จากที่เลือกใน Sidebar
    m = folium.Map(location=center, zoom_start=13, tiles=map_style)
    
    # วาดข้อมูล Isochrone (ถ้ามี)
    if st.session_state.isochrone_data:
        # เลือกสีตาม Theme (ถ้าแผนที่มืด ให้ใช้สีสว่าง)
        area_color = '#00C896' if map_style != "CartoDB dark_matter" else '#FFD700'
        
        folium.GeoJson(
            st.session_state.isochrone_data,
            name='Available Area',
            style_function=lambda x: {
                'fillColor': area_color,
                'color': area_color,
                'weight': 2,
                'fillOpacity': 0.4
            }
        ).add_to(m)
        
        # ปักหมุด
        folium.Marker(center, popup="จุดเริ่มต้น", icon=folium.Icon(color="red", icon="home")).add_to(m)
        st.success("✅ แสดงผลข้อมูล")
    else:
        # หมุดเริ่มต้น (ยังไม่คำนวณ)
        folium.Marker(center, icon=folium.Icon(color="gray", icon="info-sign")).add_to(m)

    # แสดงผล
    st_folium(m, width=1200, height=600, key="main_map")

# เรียกฟังก์ชันแสดงผล
display_map()
