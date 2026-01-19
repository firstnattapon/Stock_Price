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

# --- 🟢 ส่วนที่แก้ไข 1: เตรียมที่เก็บข้อมูลผลลัพธ์ (Data Cache) ---
if 'isochrone_data' not in st.session_state:
    st.session_state.isochrone_data = None  # เก็บข้อมูล JSON ที่ได้จาก API
if 'map_center' not in st.session_state:
    st.session_state.map_center = [13.7649, 100.5382] # เก็บจุดศูนย์กลางล่าสุด

st.title("🗺️ แผนที่คำนวณระยะการเดินทาง (Isochrone Map)")

# --- 2. Sidebar ---
with st.sidebar:
    st.header("⚙️ การตั้งค่า")
    
    default_key = "eyJvcmciOiI1YjNjZTM1OTc4NTExMTAwMDFjZjYyNDgiLCJpZCI6IjA0ZWVmNTA0Y2Y4YzQ3ZDZhZTYzNTFjNDEyZWY3OTRiIiwiaCI6Im11cm11cjY0In0="
    
    api_key = st.text_input(
        "OpenRouteService API Key", 
        value=default_key,
        type="password", 
        help="สมัครฟรีที่ openrouteservice.org"
    )
    
    st.markdown("---")
    
    travel_mode = st.selectbox(
        "รูปแบบการเดินทาง",
        options=["driving-car", "foot-walking", "cycling-regular"],
        index=0,
        format_func=lambda x: "🚗 ขับรถ" if x == "driving-car" else ("🚶 เดินเท้า" if x == "foot-walking" else "🚲 ปั่นจักรยาน")
    )
    
    time_minutes = st.slider("เวลาเดินทาง (นาที)", min_value=1, max_value=60, value=15)
    
    # ปุ่มกด
    submit_button = st.button("🚀 สร้างแผนที่", use_container_width=True)

# --- 3. ส่วนกำหนดพิกัด ---
col1, col2 = st.columns(2)
with col1:
    lat_input = st.number_input("ละติจูด (Latitude)", value=13.7649, format="%.6f")
with col2:
    lon_input = st.number_input("ลองจิจูด (Longitude)", value=100.5382, format="%.6f")

# --- 🟢 ส่วนที่แก้ไข 2: ย้าย Logic การเรียก API มาไว้ตรงนี้ (ทำแค่ครั้งเดียวตอนกดปุ่ม) ---
if submit_button:
    if not api_key:
        st.warning("⚠️ กรุณาใส่ API Key ก่อนเริ่มใช้งาน")
    else:
        with st.spinner('กำลังคำนวณเส้นทาง...'):
            try:
                client = openrouteservice.Client(key=api_key)
                range_seconds = time_minutes * 60
                center_point_ors = [lon_input, lat_input]
                
                # เรียก API
                isochrone = client.isochrones(
                    locations=[center_point_ors],
                    profile=travel_mode,
                    range=[range_seconds]
                )
                
                # ✅ บันทึกผลลัพธ์ลงใน Session State
                st.session_state.isochrone_data = isochrone
                st.session_state.map_center = [lat_input, lon_input] # จำพิกัดล่าสุดไว้
                
            except openrouteservice.exceptions.ApiError as api_err:
                 st.error(f"❌ API Key ผิดพลาด หรือโควต้าเต็ม: {api_err}")
            except Exception as e:
                st.error(f"❌ เกิดข้อผิดพลาด: {e}")

# --- 4. ฟังก์ชันวาดแผนที่ (ดึงข้อมูลจาก Session State มาวาด) ---
def display_map():
    # ใช้พิกัดจาก Session State (เพื่อให้แผนที่ไม่เด้งกลับไปค่า Default)
    center = st.session_state.map_center
    
    # สร้างแผนที่พื้นหลัง
    m = folium.Map(location=center, zoom_start=13, tiles="CartoDB positron")
    
    # ถ้ามีข้อมูล Isochrone (เคยคำนวณสำเร็จ) ให้วาดลงไป
    if st.session_state.isochrone_data:
        folium.GeoJson(
            st.session_state.isochrone_data,
            name='Available Area',
            style_function=lambda x: {
                'fillColor': '#00C896',
                'color': '#008F6B',
                'weight': 2,
                'fillOpacity': 0.4
            }
        ).add_to(m)
        
        # ปักหมุดตรงกลาง
        folium.Marker(
            center,
            popup="จุดเริ่มต้น",
            icon=folium.Icon(color="red", icon="home")
        ).add_to(m)
        
        st.success(f"✅ แสดงผลจากข้อมูลล่าสุด")
    else:
        # กรณีเริ่มแรกยังไม่มีข้อมูล ปักหมุดเทาๆ ไว้
        folium.Marker(center, icon=folium.Icon(color="gray", icon="info-sign")).add_to(m)

    # แสดงผลด้วย st_folium
    # key="main_map" สำคัญมาก! ช่วยให้ Streamlit จำ component นี้ได้
    st_folium(m, width=1200, height=600, key="main_map") 

    # แสดง JSON
    if st.session_state.isochrone_data:
        with st.expander("🛠️ ดูข้อมูล JSON ดิบ"):
            st.json(st.session_state.isochrone_data)

# --- เรียกฟังก์ชันแสดงผล ---
display_map()
