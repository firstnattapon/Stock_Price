import streamlit as st
import folium
from streamlit_folium import st_folium
from datetime import datetime
import requests

# --- 1. การตั้งค่าหน้าเว็บ ---
st.set_page_config(
    page_title="TravelTime Map Generator",
    page_icon="⏱️",
    layout="wide"
)

# --- พิกัดเริ่มต้น (สยามพารากอน) ---
DEFAULT_LAT = 13.746385 
DEFAULT_LON = 100.534966

# --- เตรียม Session State ---
if 'isochrone_data' not in st.session_state:
    st.session_state.isochrone_data = None

# Logic ป้องกันหน้าจอกระพริบ
if 'temp_lat' in st.session_state and 'temp_lon' in st.session_state:
    st.session_state.lat_input = st.session_state.temp_lat
    st.session_state.lon_input = st.session_state.temp_lon
    del st.session_state.temp_lat
    del st.session_state.temp_lon

st.title("⏱️ แผนที่คำนวณระยะเวลาเดินทาง (TravelTime API)")

# --- 2. Sidebar: ตั้งค่า ---
with st.sidebar:
    st.header("⚙️ การตั้งค่า")
    
    # Key เริ่มต้น
    default_app_id = "9aef939d"
    default_api_key = "0f7019f3ef3242dbd3cc6bf776e2ebb6"
    
    app_id = st.text_input("App ID", value=default_app_id, type="password")
    api_key = st.text_input("API Key", value=default_api_key, type="password")
    
    st.markdown("---")
    
    # 🟢 1. ส่วนเลือกสไตล์แผนที่ (เพิ่มใหม่)
    st.write("🎨 ปรับแต่งแผนที่:")
    map_style_name = st.selectbox(
        "เลือกสไตล์พื้นหลัง",
        options=["Light (สะอาดตา)", "Dark (โหมดมืด)", "Street (ถนนปกติ)", "Satellite (ดาวเทียม)"],
        index=0
    )
    
    # Mapping ชื่อที่เลือก ให้เป็นค่าที่ Folium เข้าใจ
    map_tiles_dict = {
        "Light (สะอาดตา)": "CartoDB positron",
        "Dark (โหมดมืด)": "CartoDB dark_matter",
        "Street (ถนนปกติ)": "OpenStreetMap",
        "Satellite (ดาวเทียม)": "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
    }
    selected_tiles = map_tiles_dict[map_style_name]
    # กำหนด attribution สำหรับแผนที่ดาวเทียม (จำเป็นต้องมี)
    tile_attr = "Esri" if "Satellite" in map_style_name else None

    st.markdown("---")
    
    # เลือกโหมดการเดินทาง
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

# --- 4. Logic เรียก API ---
if submit_button:
    if not api_key or not app_id:
        st.warning("⚠️ กรุณาตรวจสอบ App ID และ API Key")
    elif not time_intervals:
        st.warning("⚠️ กรุณาเลือกเวลาอย่างน้อย 1 ค่า")
    else:
        with st.spinner('กำลังเชื่อมต่อระบบ TravelTime...'):
            try:
                sorted_times = sorted(time_intervals)
                all_features = []
                
                # ยิง API
                for time_min in sorted_times:
                    payload = {
                        "departure_searches": [
                            {
                                "id": f"isochrone_{time_min}min",
                                "coords": {
                                    "lat": st.session_state.lat_input,
                                    "lng": st.session_state.lon_input
                                },
                                "transportation": {"type": travel_mode},
                                "departure_time": datetime.now().isoformat(),
                                "travel_time": time_min * 60
                            }
                        ]
                    }
                    
                    headers = {
                        "Content-Type": "application/json",
                        "X-Application-Id": app_id,
                        "X-Api-Key": api_key
                    }
                    
                    response = requests.post(
                        "https://api.traveltimeapp.com/v4/time-map",
                        json=payload,
                        headers=headers
                    )
                    
                    if response.status_code == 200:
                        result = response.json()
                        for search in result.get("results", []):
                            for shape in search.get("shapes", []):
                                coordinates = [[pt["lng"], pt["lat"]] for pt in shape["shell"]]
                                # จัดการรูเจาะ (Holes) ถ้ามี
                                holes = [[[pt["lng"], pt["lat"]] for pt in hole] for hole in shape.get("holes", [])]
                                
                                feature = {
                                    "type": "Feature",
                                    "geometry": {
                                        "type": "Polygon",
                                        "coordinates": [coordinates] + holes
                                    },
                                    "properties": {
                                        "travel_time": time_min * 60,
                                        "travel_time_minutes": time_min
                                    }
                                }
                                all_features.append(feature)
                    else:
                        st.error(f"❌ API Error: {response.status_code}")
                
                if all_features:
                    st.session_state.isochrone_data = {
                        "type": "FeatureCollection",
                        "features": all_features
                    }
                    st.success(f"✅ คำนวณสำเร็จ!")
                
            except Exception as e:
                st.error(f"❌ เกิดข้อผิดพลาด: {e}")

# --- 5. ฟังก์ชันเลือกสี ---
def get_color(seconds):
    minutes = seconds / 60
    if minutes <= 10: return '#2A9D8F'   # เขียว
    elif minutes <= 20: return '#E9C46A' # เหลือง
    elif minutes <= 30: return '#F4A261' # ส้ม
    else: return '#D62828'               # แดง

# --- 6. ฟังก์ชันแสดงแผนที่ ---
def display_map():
    current_lat = st.session_state.lat_input
    current_lon = st.session_state.lon_input
    
    # 🟢 2. สร้างแผนที่โดยใช้ tiles ที่เลือกจาก Sidebar
    # ถ้าเลือก Satellite ต้องระบุ attr ด้วย
    m = folium.Map(
        location=[current_lat, current_lon], 
        zoom_start=13, 
        tiles=selected_tiles, 
        attr=tile_attr 
    )
    
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
                fields=['travel_time_minutes'],
                aliases=['เวลา (นาที):'],
                localize=True
            )
        ).add_to(m)
        
        folium.Marker(
            [current_lat, current_lon], 
            popup="📍 จุดเริ่มต้น", 
            icon=folium.Icon(color="red", icon="home", prefix='fa')
        ).add_to(m)
        
        st.markdown("**ความหมายสี:** 🟢 ≤10น. | 🟡 10-20น. | 🟠 20-30น. | 🔴 >30น.")
        
    else:
        folium.Marker(
            [current_lat, current_lon], 
            popup="📍 คลิกแผนที่เพื่อเปลี่ยนจุด", 
            icon=folium.Icon(color="blue", icon="info-sign")
        ).add_to(m)

    map_output = st_folium(m, width=1200, height=600, key="traveltime_map")

    if map_output and map_output.get('last_clicked'):
        clicked_lat = map_output['last_clicked']['lat']
        clicked_lng = map_output['last_clicked']['lng']
        
        if abs(clicked_lat - st.session_state.lat_input) > 0.000001 or \
           abs(clicked_lng - st.session_state.lon_input) > 0.000001:
            st.session_state.temp_lat = clicked_lat
            st.session_state.temp_lon = clicked_lng
            st.rerun()

display_map()

# --- 7. Debug Info ---
if st.session_state.isochrone_data:
    with st.expander("📊 ข้อมูล GeoJSON"):
        st.json(st.session_state.isochrone_data)
