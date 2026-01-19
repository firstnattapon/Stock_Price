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

# --- 🟢 ส่วนที่เพิ่ม: ตั้งค่าตัวแปรจำค่า (Session State) ---
if 'map_generated' not in st.session_state:
    st.session_state.map_generated = False

st.title("🗺️ แผนที่คำนวณระยะการเดินทาง (Isochrone Map)")
st.markdown("""
แอปพลิเคชันนี้ช่วยคำนวณพื้นที่ที่คุณสามารถเดินทางไปถึงได้ภายในเวลาที่กำหนด 
โดยใช้ข้อมูลจาก **OpenRouteService**
""")

# --- 2. Sidebar สำหรับตั้งค่าตัวแปร ---
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
    
    # 🟢 แก้ไขปุ่ม: เมื่อกดปุ่ม ให้ไปจำค่าใน session_state ว่า True
    if st.button("🚀 สร้างแผนที่", use_container_width=True):
        st.session_state.map_generated = True

# --- 3. ส่วนกำหนดพิกัด ---
col1, col2 = st.columns(2)
with col1:
    lat_input = st.number_input("ละติจูด (Latitude)", value=13.7649, format="%.6f")
with col2:
    lon_input = st.number_input("ลองจิจูด (Longitude)", value=100.5382, format="%.6f")

# --- 4. ฟังก์ชันหลักในการทำงาน ---
def generate_map():
    if not api_key:
        st.warning("⚠️ กรุณาใส่ API Key ก่อนเริ่มใช้งาน")
        return

    # แสดงสถานะกำลังทำงาน (ย้าย spinner มาไว้ข้างนอก try เพื่อให้ครอบคลุม)
    with st.spinner('กำลังเชื่อมต่อดาวเทียมและคำนวณเส้นทาง... โปรดรอสักครู่'):
        try:
            client = openrouteservice.Client(key=api_key)
            range_seconds = time_minutes * 60
            center_point_ors = [lon_input, lat_input]
            
            isochrone = client.isochrones(
                locations=[center_point_ors],
                profile=travel_mode,
                range=[range_seconds]
            )
            
            m = folium.Map(location=[lat_input, lon_input], zoom_start=13, tiles="CartoDB positron")
            
            folium.GeoJson(
                isochrone,
                name='Available Area',
                style_function=lambda x: {
                    'fillColor': '#00C896',
                    'color': '#008F6B',
                    'weight': 2,
                    'fillOpacity': 0.4
                }
            ).add_to(m)
            
            folium.Marker(
                [lat_input, lon_input],
                popup="จุดเริ่มต้น",
                tooltip="Start Here",
                icon=folium.Icon(color="red", icon="home")
            ).add_to(m)

            st.success(f"✅ คำนวณเสร็จสิ้น! พื้นที่ที่เดินทางได้ใน {time_minutes} นาที ({travel_mode})")
            
            # 🟢 ปรับตรงนี้: กำหนด key ให้ st_folium เพื่อป้องกันการรีโหลดซ้ำซ้อน
            st_folium(m, width=1200, height=600, key="isochrone_map")

            with st.expander("🛠️ ดูข้อมูล JSON ดิบ"):
                st.json(isochrone)

        except openrouteservice.exceptions.ApiError as api_err:
             st.error(f"❌ API Key ผิดพลาด หรือโควต้าเต็ม: {api_err}")
        except Exception as e:
            st.error(f"❌ เกิดข้อผิดพลาด: {e}")

# --- 🟢 ส่วนควบคุมการแสดงผล (Logic ใหม่) ---

# ถ้า session_state บอกว่าเคยกดสร้างแล้ว -> ให้รันฟังก์ชันสร้างแผนที่
if st.session_state.map_generated:
    generate_map()
# ถ้ายังไม่เคย -> โชว์แผนที่เปล่า
else:
    m_start = folium.Map(location=[lat_input, lon_input], zoom_start=13, tiles="CartoDB positron")
    folium.Marker([lat_input, lon_input], icon=folium.Icon(color="gray", icon="info-sign")).add_to(m_start)
    st_folium(m_start, width=1200, height=500, key="start_map")
