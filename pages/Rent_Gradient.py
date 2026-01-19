import streamlit as st
import folium
from streamlit_folium import st_folium
import requests

# --- 1. การตั้งค่าหน้าเว็บ ---
st.set_page_config(
    page_title="Geoapify Multi-Color Map",
    page_icon="🌍",
    layout="wide"
)

# --- เตรียม Session State ---
if 'markers' not in st.session_state:
    st.session_state.markers = [] 

if 'isochrone_data' not in st.session_state:
    st.session_state.isochrone_data = None

# 🟢 เตรียมสีสำหรับ Gradient (พื้นที่ Fill)
if 'colors' not in st.session_state:
    st.session_state.colors = {
        'step1': '#2A9D8F', # เขียว
        'step2': '#E9C46A', # เหลือง
        'step3': '#F4A261', # ส้ม
        'step4': '#D62828'  # แดง
    }

# 🟢 เตรียมชุดสีสำหรับหมุด (Markers) และเส้นขอบ (Border)
MARKER_COLORS = ['red', 'blue', 'green', 'purple', 'orange', 'black', 'pink', 'cadetblue']
HEX_COLORS = ['#D63E2A', '#38AADD', '#72B026', '#D252B9', '#F69730', '#333333', '#FF91EA', '#436978']

# พิกัดเริ่มต้น (เชียงของ)
DEFAULT_LAT = 20.219443
DEFAULT_LON = 100.403630

st.title("🌍 Geoapify: แผนที่หลายจุด หลายสี (Multi-Point)")
st.caption("ℹ️ คลิกบนแผนที่เพื่อเพิ่มจุด -> หมุดและขอบพื้นที่เปลี่ยนสีตามลำดับ")

# --- 2. Sidebar ---
with st.sidebar:
    st.header("⚙️ การตั้งค่า Geoapify")
    
    # Key
    default_key = "4eefdfb0b0d349e595595b9c03a69e3d"
    api_key = st.text_input("API Key", value=default_key, type="password")
    
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
            
    # แสดงรายการจุด
    st.write(f"📍 จำนวนจุด: **{len(st.session_state.markers)}**")
    if st.session_state.markers:
        st.markdown("---")
        for i, m in enumerate(st.session_state.markers):
            color_name = MARKER_COLORS[i % len(MARKER_COLORS)]
            st.markdown(f"<span style='color:{color_name};'>●</span> จุดที่ {i+1} ({color_name})", unsafe_allow_html=True)

    st.markdown("---")
    
    # ตั้งค่าแผนที่
    map_style = st.selectbox("สไตล์แผนที่", ["OpenStreetMap", "CartoDB positron", "CartoDB dark_matter"])
    
    travel_mode = st.selectbox(
        "รูปแบบการเดินทาง",
        options=["drive", "walk", "bicycle", "transit"], 
        format_func=lambda x: {
            "drive": "🚗 ขับรถ", "walk": "🚶 เดินเท้า",
            "bicycle": "🚲 ปั่นจักรยาน", "transit": "🚌 ขนส่งสาธารณะ"
        }[x]
    )
    
    # เลือกเวลา (Multi-select)
    time_intervals = st.multiselect("ช่วงเวลา (นาที)", options=[5, 10, 15, 30, 45, 60], default=[5])

    # ตั้งค่าสีพื้นที่
    with st.expander("🎨 ตั้งค่าสีพื้นที่ (Fill Colors)"):
        st.session_state.colors['step1'] = st.color_picker("≤ 10 นาที", st.session_state.colors['step1'])
        st.session_state.colors['step2'] = st.color_picker("11 - 20 นาที", st.session_state.colors['step2'])
        st.session_state.colors['step3'] = st.color_picker("21 - 30 นาที", st.session_state.colors['step3'])
        st.session_state.colors['step4'] = st.color_picker("> 30 นาที", st.session_state.colors['step4'])

    st.markdown("---")
    submit_button = st.button("🚀 คำนวณทุกจุด", type="primary", use_container_width=True)

# --- 4. Logic เรียก API (Geoapify Multi-Point Logic) ---
if submit_button:
    if not api_key:
        st.warning("⚠️ กรุณาใส่ API Key")
    elif not st.session_state.markers:
        st.warning("⚠️ กรุณาเพิ่มหมุดอย่างน้อย 1 จุด")
    elif not time_intervals:
        st.warning("⚠️ กรุณาเลือกเวลา")
    else:
        with st.spinner(f'กำลังเชื่อมต่อ Geoapify ({len(st.session_state.markers)} จุด)...'):
            try:
                base_url = "https://api.geoapify.com/v1/isoline"
                all_features = []
                
                # Geoapify รองรับการส่งหลาย range ใน 1 request (คั่นด้วยลูกน้ำ)
                ranges_seconds = ",".join([str(t * 60) for t in sorted(time_intervals)])
                
                # Loop ยิง API ทีละจุด (Geoapify คิดทีละจุดศูนย์กลาง)
                for i, marker in enumerate(st.session_state.markers):
                    params = {
                        "lat": marker['lat'],
                        "lon": marker['lng'],
                        "type": "time",
                        "mode": travel_mode,
                        "range": ranges_seconds, # ส่งไปหลายเวลาพร้อมกันเลย
                        "apiKey": api_key
                    }
                    
                    response = requests.get(base_url, params=params)
                    
                    if response.status_code == 200:
                        data = response.json()
                        
                        # 🟢 สำคัญ: แทรก properties ลงไปในผลลัพธ์ เพื่อให้ Folium รู้ว่าเป็นของจุดไหน
                        for feature in data.get('features', []):
                            # Geoapify คืนค่า 'value' มาเป็นวินาที
                            seconds = feature['properties'].get('value', 0)
                            feature['properties']['travel_time_minutes'] = seconds / 60
                            feature['properties']['marker_index'] = i # แทรก index เพื่อระบุสีขอบ
                            
                            all_features.append(feature)
                    else:
                        st.error(f"❌ API Error จุดที่ {i+1}: {response.status_code}")
                
                if all_features:
                    st.session_state.isochrone_data = {"type": "FeatureCollection", "features": all_features}
                    st.success(f"✅ คำนวณสำเร็จ!")
                
            except Exception as e:
                st.error(f"❌ เกิดข้อผิดพลาด: {e}")

# --- 5. ฟังก์ชันเลือกสี ---
def get_fill_color(minutes):
    c = st.session_state.colors
    if minutes <= 10: return c['step1']
    elif minutes <= 20: return c['step2']
    elif minutes <= 30: return c['step3']
    else: return c['step4']

def get_border_color(marker_idx):
    # เลือกสีขอบตามลำดับหมุด (วนลูปสีถ้าหมุดเยอะกว่าสีที่มี)
    if marker_idx is not None:
        return HEX_COLORS[marker_idx % len(HEX_COLORS)]
    return '#3388ff' # สี default

# --- 6. แสดงแผนที่ ---
def display_map():
    # หาจุดกึ่งกลาง (เอาจุดล่าสุด หรือจุด Default)
    if st.session_state.markers:
        last_m = st.session_state.markers[-1]
        center = [last_m['lat'], last_m['lng']]
    else:
        center = [DEFAULT_LAT, DEFAULT_LON]

    m = folium.Map(location=center, zoom_start=11, tiles=map_style)

    # 1. วาด Isochrones (พื้นที่)
    if st.session_state.isochrone_data:
        folium.GeoJson(
            st.session_state.isochrone_data,
            name='Geoapify Area',
            style_function=lambda feature: {
                'fillColor': get_fill_color(feature['properties']['travel_time_minutes']),
                'color': get_border_color(feature['properties']['marker_index']), # 🟢 สีขอบตามหมุด
                'weight': 2,
                'fillOpacity': 0.4
            },
            tooltip=folium.GeoJsonTooltip(fields=['travel_time_minutes'], aliases=['นาที:'])
        ).add_to(m)

    # 2. วาดหมุด (Markers) พร้อมสีที่เปลี่ยนไปเรื่อยๆ
    for i, marker in enumerate(st.session_state.markers):
        color_name = MARKER_COLORS[i % len(MARKER_COLORS)]
        
        folium.Marker(
            [marker['lat'], marker['lng']],
            popup=f"จุดที่ {i+1} ({color_name})",
            icon=folium.Icon(color=color_name, icon="map-marker", prefix='fa') # ใช้ fa icon
        ).add_to(m)

    # แสดงแผนที่ & รับคลิก
    map_output = st_folium(m, width=1200, height=600, key="geoapify_multi_map")
    
    if map_output and map_output.get('last_clicked'):
        clicked_lat = map_output['last_clicked']['lat']
        clicked_lng = map_output['last_clicked']['lng']
        
        # ป้องกันการคลิกซ้ำที่เดิม (Anti-double click)
        is_new = True
        if st.session_state.markers:
            last_mk = st.session_state.markers[-1]
            if abs(clicked_lat - last_mk['lat']) < 0.00001 and abs(clicked_lng - last_mk['lng']) < 0.00001:
                is_new = False
        
        if is_new:
            st.session_state.markers.append({'lat': clicked_lat, 'lng': clicked_lng})
            st.rerun()

display_map()
