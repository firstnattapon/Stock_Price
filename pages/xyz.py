import streamlit as st
import folium
from streamlit_folium import st_folium
from datetime import datetime
import requests

# --- 1. การตั้งค่าหน้าเว็บ ---
st.set_page_config(
    page_title="Multi-Point Isochrone",
    page_icon="📍",
    layout="wide"
)

# --- เตรียม Session State สำหรับเก็บหลายจุด ---
if 'markers' not in st.session_state:
    # เก็บ list ของ dictionary: [{'lat': 13.x, 'lng': 100.x}, ...]
    st.session_state.markers = [] 

if 'isochrone_data' not in st.session_state:
    st.session_state.isochrone_data = None

# ค่าเริ่มต้น (ถ้ายังไม่มีหมุดเลย ให้เริ่มแถวสยาม)
DEFAULT_LAT = 13.746385
DEFAULT_LON = 100.534966

st.title("📍 แผนที่คำนวณพื้นที่จากหลายจุด (Multi-Point)")
st.caption("ℹ️ วิธีใช้: **คลิกที่แผนที่** เพื่อเพิ่มหมุดใหม่ (เพิ่มได้หลายจุด) -> แล้วกด **คำนวณ**")

# --- 2. Sidebar ---
with st.sidebar:
    st.header("⚙️ การตั้งค่า")
    
    # Key
    default_app_id = "9aef939d"
    default_api_key = "0f7019f3ef3242dbd3cc6bf776e2ebb6"
    app_id = st.text_input("App ID", value=default_app_id, type="password")
    api_key = st.text_input("API Key", value=default_api_key, type="password")
    
    st.markdown("---")
    
    # จัดการหมุด
    st.write(f"📍 จำนวนหมุดปัจจุบัน: **{len(st.session_state.markers)}** จุด")
    col_btn1, col_btn2 = st.columns(2)
    with col_btn1:
        if st.button("❌ ลบจุดล่าสุด", use_container_width=True):
            if st.session_state.markers:
                st.session_state.markers.pop()
                st.rerun()
    with col_btn2:
        if st.button("🗑️ ล้างทั้งหมด", use_container_width=True):
            st.session_state.markers = []
            st.session_state.isochrone_data = None
            st.rerun()

    st.markdown("---")

    # ตั้งค่าแผนที่
    map_style_name = st.selectbox(
        "🎨 สไตล์แผนที่",
        options=["Light", "Dark", "Street", "Satellite"],
        index=0
    )
    
    map_tiles_dict = {
        "Light": "CartoDB positron",
        "Dark": "CartoDB dark_matter",
        "Street": "OpenStreetMap",
        "Satellite": "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
    }
    selected_tiles = map_tiles_dict[map_style_name]
    tile_attr = "Esri" if "Satellite" in map_style_name else None

    # โหมดเดินทาง
    travel_mode = st.selectbox(
        "รูปแบบการเดินทาง",
        options=["public_transport", "driving", "walking", "cycling"],
        index=0,
        format_func=lambda x: {"public_transport": "🚌 รถสาธารณะ", "driving": "🚗 ขับรถ", "walking": "🚶 เดินเท้า", "cycling": "🚲 จักรยาน"}[x]
    )
    
    # เวลา
    st.write("⏱️ ช่วงเวลา (นาที):")
    time_intervals = st.multiselect(
        "ระบุเวลา",
        options=[5, 10, 15, 30, 45, 60],
        default=[15]
    )
    
    submit_button = st.button("🚀 คำนวณทุกจุด", type="primary", use_container_width=True)

# --- 3. แสดงรายการพิกัด (Optional) ---
with st.expander("📝 ดูรายการพิกัดทั้งหมด"):
    if not st.session_state.markers:
        st.info("ยังไม่มีหมุด กรุณาคลิกบนแผนที่")
    else:
        for i, mk in enumerate(st.session_state.markers):
            st.text(f"จุดที่ {i+1}: {mk['lat']:.5f}, {mk['lng']:.5f}")

# --- 4. Logic เรียก API (รองรับหลายจุด) ---
if submit_button:
    if not api_key or not app_id:
        st.warning("⚠️ กรุณาใส่ API Key")
    elif not st.session_state.markers:
        st.warning("⚠️ กรุณาคลิกเพิ่มหมุดบนแผนที่อย่างน้อย 1 จุด")
    elif not time_intervals:
        st.warning("⚠️ กรุณาเลือกเวลา")
    else:
        with st.spinner(f'กำลังคำนวณ {len(st.session_state.markers)} จุด...'):
            try:
                # สร้าง Payload สำหรับ Multi-Point
                departure_searches = []
                sorted_times = sorted(time_intervals)
                
                # Loop สร้าง search object ให้ครบทุกจุด x ทุกเวลา
                req_id_counter = 0
                for i, marker in enumerate(st.session_state.markers):
                    for time_min in sorted_times:
                        search_item = {
                            "id": f"search_{i}_{time_min}", # ID ไม่ซ้ำกัน
                            "coords": {"lat": marker['lat'], "lng": marker['lng']},
                            "transportation": {"type": travel_mode},
                            "departure_time": datetime.now().isoformat(),
                            "travel_time": time_min * 60
                        }
                        departure_searches.append(search_item)

                payload = {"departure_searches": departure_searches}
                
                headers = {
                    "Content-Type": "application/json",
                    "X-Application-Id": app_id,
                    "X-Api-Key": api_key
                }
                
                # ยิง API ครั้งเดียว (TravelTime รองรับ Batch Request)
                response = requests.post(
                    "https://api.traveltimeapp.com/v4/time-map",
                    json=payload,
                    headers=headers
                )
                
                if response.status_code == 200:
                    result = response.json()
                    all_features = []
                    
                    for search in result.get("results", []):
                        # แกะเวลาออกมาจาก search_id (เช่น search_0_15 -> 15)
                        search_id = search['search_id']
                        time_val = int(search_id.split('_')[-1]) 
                        
                        for shape in search.get("shapes", []):
                            coords = [[pt["lng"], pt["lat"]] for pt in shape["shell"]]
                            holes = [[[pt["lng"], pt["lat"]] for pt in hole] for hole in shape.get("holes", [])]
                            
                            feature = {
                                "type": "Feature",
                                "geometry": {"type": "Polygon", "coordinates": [coords] + holes},
                                "properties": {
                                    "travel_time_minutes": time_val
                                }
                            }
                            all_features.append(feature)
                    
                    st.session_state.isochrone_data = {"type": "FeatureCollection", "features": all_features}
                    st.success(f"✅ คำนวณสำเร็จ! ได้พื้นที่ทั้งหมด {len(all_features)} วง")
                    
                else:
                    st.error(f"❌ API Error: {response.status_code}")
                    st.code(response.text)
                    
            except Exception as e:
                st.error(f"❌ Error: {e}")

# --- 5. ฟังก์ชันเลือกสี ---
def get_color(minutes):
    if minutes <= 10: return '#2A9D8F'   # เขียว
    elif minutes <= 20: return '#E9C46A' # เหลือง
    elif minutes <= 30: return '#F4A261' # ส้ม
    else: return '#D62828'               # แดง

# --- 6. แสดงแผนที่ ---
def display_map():
    # หาจุดกึ่งกลางแผนที่ (ถ้ามีหมุด ให้เอาตัวล่าสุด ถ้าไม่มีเอาสยาม)
    if st.session_state.markers:
        last_m = st.session_state.markers[-1]
        center = [last_m['lat'], last_m['lng']]
    else:
        center = [DEFAULT_LAT, DEFAULT_LON]

    m = folium.Map(location=center, zoom_start=12, tiles=selected_tiles, attr=tile_attr)

    # 1. วาด Isochrones (พื้นที่)
    if st.session_state.isochrone_data:
        folium.GeoJson(
            st.session_state.isochrone_data,
            name='TravelTime Area',
            style_function=lambda feature: {
                'fillColor': get_color(feature['properties']['travel_time_minutes']),
                'color': 'white',
                'weight': 1,
                'fillOpacity': 0.5
            },
            tooltip=folium.GeoJsonTooltip(fields=['travel_time_minutes'], aliases=['นาที:'])
        ).add_to(m)

    # 2. วาดหมุดทั้งหมด (Markers)
    for i, marker in enumerate(st.session_state.markers):
        folium.Marker(
            [marker['lat'], marker['lng']],
            popup=f"จุดที่ {i+1}",
            icon=folium.Icon(color="red", icon="map-marker", prefix='fa')
        ).add_to(m)

    # 3. แสดงผลและรับค่าคลิก
    map_output = st_folium(m, width=1200, height=600, key="multi_map")

    # --- Logic: คลิกเพื่อเพิ่มจุด ---
    if map_output and map_output.get('last_clicked'):
        clicked_lat = map_output['last_clicked']['lat']
        clicked_lng = map_output['last_clicked']['lng']
        
        # เช็คว่าไม่ได้คลิกซ้ำจุดเดิม (ป้องกัน Loop)
        is_new = True
        if st.session_state.markers:
            last_mk = st.session_state.markers[-1]
            # ถ้าคลิกใกล้จุดเดิมมากๆ (เช่น กดเบิ้ล) ไม่ต้องเพิ่ม
            if abs(clicked_lat - last_mk['lat']) < 0.00001 and abs(clicked_lng - last_mk['lng']) < 0.00001:
                is_new = False
        
        if is_new:
            # ✅ เพิ่มจุดลงใน List
            st.session_state.markers.append({'lat': clicked_lat, 'lng': clicked_lng})
            st.rerun()

display_map()
