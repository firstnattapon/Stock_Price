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

st.title("🗺️ แผนที่คำนวณระยะการเดินทาง (Isochrone Map)")
st.markdown("""
แอปพลิเคชันนี้ช่วยคำนวณพื้นที่ที่คุณสามารถเดินทางไปถึงได้ภายในเวลาที่กำหนด 
โดยใช้ข้อมูลจาก **OpenRouteService**
""")

# --- 2. Sidebar สำหรับตั้งค่าตัวแปร ---
with st.sidebar:
    st.header("⚙️ การตั้งค่า")
    
    # ใส่ Default Key ที่คุณให้มา (ถ้าต้องการเปลี่ยน สามารถลบและพิมพ์ใหม่ในหน้าเว็บได้)
    default_key = "eyJvcmciOiI1YjNjZTM1OTc4NTExMTAwMDFjZjYyNDgiLCJpZCI6IjA0ZWVmNTA0Y2Y4YzQ3ZDZhZTYzNTFjNDEyZWY3OTRiIiwiaCI6Im11cm11cjY0In0="
    
    api_key = st.text_input(
        "OpenRouteService API Key", 
        value=default_key, # <--- ใส่ค่าเริ่มต้นตรงนี้
        type="password", 
        help="สมัครฟรีที่ openrouteservice.org"
    )
    
    st.markdown("---")
    
    # เลือกรูปแบบการเดินทาง
    travel_mode = st.selectbox(
        "รูปแบบการเดินทาง",
        options=["driving-car", "foot-walking", "cycling-regular"],
        index=0,
        format_func=lambda x: "🚗 ขับรถ" if x == "driving-car" else ("🚶 เดินเท้า" if x == "foot-walking" else "🚲 ปั่นจักรยาน")
    )
    
    # เลือกเวลา (นาที)
    time_minutes = st.slider("เวลาเดินทาง (นาที)", min_value=1, max_value=60, value=15)
    
    # ปุ่มกดเพื่อคำนวณ
    submit_button = st.button("🚀 สร้างแผนที่", use_container_width=True)

# --- 3. ส่วนกำหนดพิกัด (Layout แบบ 2 คอลัมน์) ---
col1, col2 = st.columns(2)
with col1:
    # ตั้งค่าเริ่มต้นเป็น อนุสาวรีย์ชัยสมรภูมิ
    lat_input = st.number_input("ละติจูด (Latitude)", value=13.7649, format="%.6f")
with col2:
    lon_input = st.number_input("ลองจิจูด (Longitude)", value=100.5382, format="%.6f")

# --- 4. ฟังก์ชันหลักในการทำงาน ---
def generate_map():
    if not api_key:
        st.warning("⚠️ กรุณาใส่ API Key ก่อนเริ่มใช้งาน")
        return

    # แสดงสถานะกำลังทำงาน
    with st.spinner('กำลังเชื่อมต่อดาวเทียมและคำนวณเส้นทาง... โปรดรอสักครู่'):
        try:
            client = openrouteservice.Client(key=api_key)
            
            # แปลงเวลาเป็นวินาที
            range_seconds = time_minutes * 60
            
            # พิกัดสำหรับ ORS ต้องเป็น [Lon, Lat]
            center_point_ors = [lon_input, lat_input]
            
            # ขอข้อมูล Isochrone
            isochrone = client.isochrones(
                locations=[center_point_ors],
                profile=travel_mode,
                range=[range_seconds]
            )
            
            # สร้างแผนที่ Folium (พิกัดต้องเป็น [Lat, Lon])
            m = folium.Map(location=[lat_input, lon_input], zoom_start=13, tiles="CartoDB positron")
            
            # วาดพื้นที่ (Polygon)
            folium.GeoJson(
                isochrone,
                name='Available Area',
                style_function=lambda x: {
                    'fillColor': '#00C896', # สีเขียวมินต์
                    'color': '#008F6B',     # สีขอบ
                    'weight': 2,
                    'fillOpacity': 0.4
                }
            ).add_to(m)
            
            # ปักหมุดจุดเริ่มต้น
            folium.Marker(
                [lat_input, lon_input],
                popup="จุดเริ่มต้น",
                tooltip="Start Here",
                icon=folium.Icon(color="red", icon="home")
            ).add_to(m)

            # --- 5. แสดงผลแผนที่ ---
            st.success(f"✅ คำนวณเสร็จสิ้น! พื้นที่ที่เดินทางได้ใน {time_minutes} นาที ({travel_mode})")
            st_folium(m, width=1200, height=600)

            # แสดงข้อมูล JSON ดิบ (เผื่ออยากดูโครงสร้างข้อมูล)
            with st.expander("🛠️ ดูข้อมูล JSON ดิบ"):
                st.json(isochrone)

        except openrouteservice.exceptions.ApiError as api_err:
             st.error(f"❌ API Key ผิดพลาด หรือโควต้าเต็ม: {api_err}")
             st.warning("ลองเช็ค API Key ที่ dashboard.openrouteservice.org อีกครั้ง")
        except Exception as e:
            st.error(f"❌ เกิดข้อผิดพลาด: {e}")

# --- เรียกใช้งานเมื่อกดปุ่ม ---
if submit_button:
    generate_map()
else:
    # แสดงแผนที่ว่างๆ เริ่มต้น
    m_start = folium.Map(location=[lat_input, lon_input], zoom_start=13, tiles="CartoDB positron")
    folium.Marker([lat_input, lon_input], icon=folium.Icon(color="gray", icon="info-sign")).add_to(m_start)
    st_folium(m_start, width=1200, height=500)
