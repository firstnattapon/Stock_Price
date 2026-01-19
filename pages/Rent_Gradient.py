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

# --- พิกัดเริ่มต้น (เชียงของ, เชียงราย) ---
DEFAULT_LAT = 20.219443
DEFAULT_LON = 100.403630

# --- เตรียมตัวแปรจำค่า (Session State) ---
if 'isochrone_data' not in st.session_state:
    st.session_state.isochrone_data = None
# ใช้ตัวแปรนี้สำหรับกำหนดจุดศูนย์กลางแผนที่
if 'map_center' not in st.session_state:
    st.session_state.map_center = [DEFAULT_LAT, DEFAULT_LON]

st.title("🗺️ แผนที่คำนวณระยะการเดินทาง (Isochrone Map)")
st.caption("ℹ️ Tip: คุณสามารถ **คลิกที่แผนที่** เพื่อเปลี่ยนจุดเริ่มต้นได้เลย")

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

# --- 3. ส่วนกำหนดพิกัด (เชื่อมกับ Session State) ---
col1, col2 = st.columns(2)

# ฟังก์ชัน Callback (ไม่จำเป็นต้องใช้ในกรณีนี้ แต่เขียนไว้เผื่อ)
def on_input_change():
    # เมื่อแก้ตัวเลข อัปเดต map_center ด้วย
    st.session_state.map_center = [st.session_state.lat_input, st.session_state.lon_input]

with col1:
    # key="lat_input" ทำให้เราสามารถแก้ค่านี้จากโค้ดได้
    st.number_input("ละติจูด (Latitude)", value=DEFAULT_LAT, format="%.6f", key="lat_input", on_change=on_input_change)
with col2:
    st.number_input("ลองจิจูด (Longitude)", value=DEFAULT_LON, format="%.6f", key="lon_input", on_change=on_input_change)

# --- 4. Logic เรียก API ---
if submit_button:
    if not api_key:
        st.warning("⚠️ กรุณาใส่ API Key")
    else:
        with st.spinner('กำลังคำนวณ...'):
            try:
                client = openrouteservice.Client(key=api_key)
                # ดึงค่าจาก input ที่อาจเปลี่ยนไปแล้ว
                current_lat = st.session_state.lat_input
                current_lon = st.session_state.lon_input
                
                range_seconds = time_minutes * 60
                
                isochrone = client.isochrones(
                    locations=[[current_lon, current_lat]],
                    profile=travel_mode,
                    range=[range_seconds]
                )
                
                st.session_state.isochrone_data = isochrone
                # อัปเดตจุดศูนย์กลางแผนที่ให้ไปโฟกัสจุดที่คำนวณ
                st.session_state.map_center = [current_lat, current_lon]
                
            except Exception as e:
                st.error(f"❌ เกิดข้อผิดพลาด: {e}")

# --- 5. ฟังก์ชันวาดและรับค่าคลิก ---
def display_map():
    # ใช้พิกัดปัจจุบันจาก Input Box
    current_lat = st.session_state.lat_input
    current_lon = st.session_state.lon_input
    
    # สร้างแผนที่
    m = folium.Map(location=[current_lat, current_lon], zoom_start=13, tiles=map_style)
    
    # ถ้ามีข้อมูล Isochrone ให้วาด
    if st.session_state.isochrone_data:
        area_color = '#00C896' if map_style != "CartoDB dark_matter" else '#FFD700'
        folium.GeoJson(
            st.session_state.isochrone_data,
            name='Available Area',
            style_function=lambda x: {'fillColor': area_color, 'color': area_color, 'weight': 2, 'fillOpacity': 0.4}
        ).add_to(m)
        
        # ปักหมุดจุดที่คำนวณไว้ล่าสุด
        folium.Marker([current_lat, current_lon], popup="จุดที่คำนวณ", icon=folium.Icon(color="red", icon="home")).add_to(m)
    else:
        # ปักหมุดตำแหน่งปัจจุบัน
        folium.Marker([current_lat, current_lon], popup="จุดปัจจุบัน", icon=folium.Icon(color="blue", icon="info-sign")).add_to(m)

    # 🟢 แสดงแผนที่และรับค่าการคลิก (Click Event)
    map_output = st_folium(m, width=1200, height=600, key="main_map")

    # --- 🟢 Logic การคลิกเปลี่ยนพิกัด ---
    if map_output['last_clicked']:
        clicked_lat = map_output['last_clicked']['lat']
        clicked_lng = map_output['last_clicked']['lng']
        
        # เช็คว่าพิกัดเปลี่ยนไปจากเดิมไหม (เพื่อป้องกันการรีรันซ้ำซ้อน)
        if clicked_lat != st.session_state.lat_input or clicked_lng != st.session_state.lon_input:
            st.session_state.lat_input = clicked_lat
            st.session_state.lon_input = clicked_lng
            st.rerun() # รีโหลดหน้าเว็บเพื่ออัปเดตตัวเลขในช่อง

# เรียกใช้งาน
display_map()
