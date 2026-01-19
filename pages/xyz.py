import streamlit as st
import folium
from streamlit_folium import st_folium
from datetime import datetime
import requests

# --- 1. การตั้งค่าหน้าเว็บ ---
st.set_page_config(
    page_title="Custom Color Isochrone",
    page_icon="🎨",
    layout="wide"
)

# --- เตรียม Session State ---
if 'markers' not in st.session_state:
    st.session_state.markers = [] 

if 'isochrone_data' not in st.session_state:
    st.session_state.isochrone_data = None

# 🟢 เตรียมตัวแปรเก็บสี (ค่าเริ่มต้น)
if 'colors' not in st.session_state:
    st.session_state.colors = {
        'step1': '#2A9D8F', # เขียว (ใกล้สุด)
        'step2': '#E9C46A', # เหลือง
        'step3': '#F4A261', # ส้ม
        'step4': '#D62828'  # แดง (ไกลสุด)
    }

DEFAULT_LAT = 13.746385
DEFAULT_LON = 100.534966

st.title("🎨 แผนที่คำนวณพื้นที่ (ปรับสีได้)")
st.caption("ℹ️ คลิกที่แผนที่เพื่อเพิ่มจุด -> ตั้งค่า -> กดคำนวณ")

# --- 2. Sidebar ---
with st.sidebar:
    st.header("⚙️ ตั้งค่า API & ข้อมูล")
    # Key
    default_app_id = "9aef939d"
    default_api_key = "0f7019f3ef3242dbd3cc6bf776e2ebb6"
    app_id = st.text_input("App ID", value=default_app_id, type="password")
    api_key = st.text_input("API Key", value=default_api_key, type="password")
    
    st.markdown("---")
    
    # จัดการหมุด
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
    st.write(f"📍 จุดปัจจุบัน: **{len(st.session_state.markers)}** จุด")

    st.markdown("---")

    # ตั้งค่าแผนที่ & เวลา
    map_style_name = st.selectbox("สไตล์พื้นหลัง", ["Light", "Dark", "Street", "Satellite"])
    map_tiles_dict = {
        "Light": "CartoDB positron", "Dark": "CartoDB dark_matter",
        "Street": "OpenStreetMap", "Satellite": "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
    }
    selected_tiles = map_tiles_dict[map_style_name]
    tile_attr = "Esri" if "Satellite" in map_style_name else None

    travel_mode = st.selectbox("การเดินทาง", ["public_transport", "driving", "walking", "cycling"])
    
    time_intervals = st.multiselect("ช่วงเวลา (นาที)", options=[5, 10, 15, 30, 45, 60], default=[15, 30])
    
    # 🟢 🟢 ส่วนตั้งค่าสี (เพิ่มใหม่ตรงนี้) 🟢 🟢
    st.markdown("---")
    with st.expander("🎨 ตั้งค่าสีพื้นที่ (Color Settings)", expanded=True):
        st.write("เลือกสีตามช่วงเวลา:")
        # ใช้ st.color_picker และอัปเดตค่าลง Session State ทันที
        st.session_state.colors['step1'] = st.color_picker("≤ 10 นาที", st.session_state.colors['step1'])
        st.session_state.colors['step2'] = st.color_picker("11 - 20 นาที", st.session_state.colors['step2'])
        st.session_state.colors['step3'] = st.color_picker("21 - 30 นาที", st.session_state.colors['step3'])
        st.session_state.colors['step4'] = st.color_picker("> 30 นาที", st.session_state.colors['step4'])
        
        st.markdown("💡 *Tip: เลือกสีอ่อนๆ หรือปรับ Opacity ในแผนที่เพื่อให้เห็นการซ้อนทับชัดเจน*")

    st.markdown("---")
    submit_button = st.button("🚀 คำนวณทุกจุด", type="primary", use_container_width=True)

# --- 4. Logic เรียก API (Multi-Point) ---
if submit_button:
    if not api_key or not app_id:
        st.warning("⚠️ กรุณาใส่ API Key")
    elif not st.session_state.markers:
        st.warning("⚠️ กรุณาคลิกเพิ่มหมุดก่อน")
    elif not time_intervals:
        st.warning("⚠️ กรุณาเลือกเวลา")
    else:
        with st.spinner(f'กำลังคำนวณ...'):
            try:
                departure_searches = []
                sorted_times = sorted(time_intervals)
                for i, marker in enumerate(st.session_state.markers):
                    for time_min in sorted_times:
                        departure_searches.append({
                            "id": f"search_{i}_{time_min}",
                            "coords": {"lat": marker['lat'], "lng": marker['lng']},
                            "transportation": {"type": travel_mode},
                            "departure_time": datetime.now().isoformat(),
                            "travel_time": time_min * 60
                        })

                response = requests.post(
                    "https://api.traveltimeapp.com/v4/time-map",
                    json={"departure_searches": departure_searches},
                    headers={"Content-Type": "application/json", "X-Application-Id": app_id, "X-Api-Key": api_key}
                )
                
                if response.status_code == 200:
                    result = response.json()
                    all_features = []
                    for search in result.get("results", []):
                        time_val = int(search['search_id'].split('_')[-1]) 
                        for shape in search.get("shapes", []):
                            coords = [[pt["lng"], pt["lat"]] for pt in shape["shell"]]
                            holes = [[[pt["lng"], pt["lat"]] for pt in hole] for hole in shape.get("holes", [])]
                            all_features.append({
                                "type": "Feature",
                                "geometry": {"type": "Polygon", "coordinates": [coords] + holes},
                                "properties": {"travel_time_minutes": time_val}
                            })
                    st.session_state.isochrone_data = {"type": "FeatureCollection", "features": all_features}
                    st.success(f"✅ คำนวณสำเร็จ!")
                else:
                    st.error(f"❌ Error: {response.status_code} - {response.text}")
            except Exception as e:
                st.error(f"❌ Error: {e}")

# --- 5. ฟังก์ชันเลือกสี (อัปเดตให้ใช้สีจาก Session State) ---
def get_color(minutes):
    c = st.session_state.colors # ดึงสีปัจจุบันมาใช้
    if minutes <= 10: return c['step1']
    elif minutes <= 20: return c['step2']
    elif minutes <= 30: return c['step3']
    else: return c['step4']

# --- 6. แสดงแผนที่ ---
def display_map():
    if st.session_state.markers:
        last_m = st.session_state.markers[-1]
        center = [last_m['lat'], last_m['lng']]
    else:
        center = [DEFAULT_LAT, DEFAULT_LON]

    m = folium.Map(location=center, zoom_start=12, tiles=selected_tiles, attr=tile_attr)

    # วาด Isochrones
    if st.session_state.isochrone_data:
        folium.GeoJson(
            st.session_state.isochrone_data,
            name='TravelTime Area',
            style_function=lambda feature: {
                'fillColor': get_color(feature['properties']['travel_time_minutes']), # ใช้ฟังก์ชันใหม่
                'color': 'white',
                'weight': 1,
                'fillOpacity': 0.5 # ความโปร่งแสง (สำคัญมากสำหรับการซ้อนทับ)
            },
            tooltip=folium.GeoJsonTooltip(fields=['travel_time_minutes'], aliases=['นาที:'])
        ).add_to(m)

    # วาดหมุด
    for i, marker in enumerate(st.session_state.markers):
        folium.Marker(
            [marker['lat'], marker['lng']],
            popup=f"จุดที่ {i+1}",
            icon=folium.Icon(color="red", icon="map-marker", prefix='fa')
        ).add_to(m)

    # 🟢 แสดง Legend แบบ Dynamic ตามสีที่เลือก
    if st.session_state.isochrone_data:
        c = st.session_state.colors
        # สร้าง HTML เล็กๆ เพื่อโชว์กล่องสี
        legend_html = f"""
        <div style="
            position: fixed; 
            bottom: 50px; left: 50px; width: 200px; height: 130px; 
            background-color: white; z-index:9999; font-size:14px;
            padding: 10px; border: 2px solid grey; border-radius: 5px;
            opacity: 0.9;">
            <b>คำอธิบายสี (Legend)</b><br>
            <i style="background:{c['step1']};width:15px;height:15px;display:inline-block;margin-right:5px;"></i> ≤ 10 นาที<br>
            <i style="background:{c['step2']};width:15px;height:15px;display:inline-block;margin-right:5px;"></i> 11 - 20 นาที<br>
            <i style="background:{c['step3']};width:15px;height:15px;display:inline-block;margin-right:5px;"></i> 21 - 30 นาที<br>
            <i style="background:{c['step4']};width:15px;height:15px;display:inline-block;margin-right:5px;"></i> > 30 นาที
        </div>
        """
        m.get_root().html.add_child(folium.Element(legend_html))

    # แสดงแผนที่ & รับคลิก
    map_output = st_folium(m, width=1200, height=600, key="multi_color_map")
    if map_output and map_output.get('last_clicked'):
        clicked_lat = map_output['last_clicked']['lat']
        clicked_lng = map_output['last_clicked']['lng']
        is_new = True
        if st.session_state.markers:
            last_mk = st.session_state.markers[-1]
            if abs(clicked_lat - last_mk['lat']) < 0.00001 and abs(clicked_lng - last_mk['lng']) < 0.00001:
                is_new = False
        if is_new:
            st.session_state.markers.append({'lat': clicked_lat, 'lng': clicked_lng})
            st.rerun()

display_map()
