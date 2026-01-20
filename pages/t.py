import streamlit as st
import folium
from streamlit_folium import st_folium
import requests
import time

# --- 1. การตั้งค่าหน้าเว็บ ---
st.set_page_config(
    page_title="Geoapify: Smart Site Search",
    page_icon="🔎",
    layout="wide"
)

# --- Constants & Config ---
DEFAULT_LAT = 20.219443
DEFAULT_LON = 100.403630
DEFAULT_API_KEY = "4eefdfb0b0d349e595595b9c03a69e3d"

MARKER_COLORS = ['red', 'blue', 'green', 'purple', 'orange', 'black', 'pink', 'cadetblue']
HEX_COLORS = ['#D63E2A', '#38AADD', '#72B026', '#D252B9', '#F69730', '#333333', '#FF91EA', '#436978']

# --- 2. Session State Initialization ---
if 'markers' not in st.session_state:
    st.session_state.markers = [{'lat': DEFAULT_LAT, 'lng': DEFAULT_LON, 'address': 'จุดเริ่มต้น (เชียงของ)'}]

if 'isochrone_data' not in st.session_state:
    st.session_state.isochrone_data = None

if 'map_center' not in st.session_state:
    st.session_state.map_center = [DEFAULT_LAT, DEFAULT_LON]

if 'colors' not in st.session_state:
    st.session_state.colors = {
        'step1': '#2A9D8F', 'step2': '#E9C46A', 
        'step3': '#F4A261', 'step4': '#D62828'
    }

# --- 3. Helper Functions (Logic) ---

def fetch_isochrones(api_key, markers, travel_mode, time_intervals):
    """ดึงข้อมูลพื้นที่การเดินทาง (Isochrone)"""
    base_url = "https://api.geoapify.com/v1/isoline"
    all_features = []
    ranges_seconds = ",".join([str(t * 60) for t in sorted(time_intervals)])
    
    for i, marker in enumerate(markers):
        params = {
            "lat": marker['lat'], "lon": marker['lng'],
            "type": "time", "mode": travel_mode,
            "range": ranges_seconds, "apiKey": api_key
        }
        try:
            response = requests.get(base_url, params=params)
            if response.status_code == 200:
                data = response.json()
                for feature in data.get('features', []):
                    seconds = feature['properties'].get('value', 0)
                    feature['properties']['travel_time_minutes'] = seconds / 60
                    feature['properties']['marker_index'] = i
                    all_features.append(feature)
            else:
                st.error(f"❌ Isochrone API Error จุดที่ {i+1}: {response.status_code}")
        except Exception as e:
            st.error(f"❌ Error fetching isochrone: {e}")
            
    return {"type": "FeatureCollection", "features": all_features} if all_features else None

def geocode_search(api_key, query_text):
    """ค้นหาสถานที่จากชื่อ (Forward Geocoding)"""
    url = "https://api.geoapify.com/v1/geocode/search"
    params = {"text": query_text, "apiKey": api_key, "limit": 1}
    try:
        response = requests.get(url, params=params)
        if response.status_code == 200:
            features = response.json().get('features', [])
            if features:
                props = features[0]['properties']
                return {
                    'lat': props['lat'],
                    'lng': props['lon'],
                    'address': props.get('formatted', query_text)
                }
    except Exception as e:
        st.error(f"Search Error: {e}")
    return None

def reverse_geocode(api_key, lat, lng):
    """หาชื่อที่อยู่จากพิกัด (Reverse Geocoding)"""
    url = "https://api.geoapify.com/v1/geocode/reverse"
    params = {"lat": lat, "lon": lng, "apiKey": api_key}
    try:
        response = requests.get(url, params=params)
        if response.status_code == 200:
            features = response.json().get('features', [])
            if features:
                return features[0]['properties'].get('formatted', 'Unknown Address')
    except:
        pass
    return "Custom Location"

def get_fill_color(minutes):
    c = st.session_state.colors
    if minutes <= 10: return c['step1']
    elif minutes <= 20: return c['step2']
    elif minutes <= 30: return c['step3']
    else: return c['step4']

def get_border_color(marker_idx):
    if marker_idx is not None:
        return HEX_COLORS[marker_idx % len(HEX_COLORS)]
    return '#3388ff'

# --- 4. Main UI & App Logic ---

st.title("🌍 Geoapify: ค้นหาทำเล & วิเคราะห์พื้นที่")
st.caption(f"📍 ระบุพิกัดแม่นยำด้วยการค้นหา + วิเคราะห์ระยะเวลาเดินทาง")

# --- Sidebar ---
with st.sidebar:
    st.header("⚙️ การตั้งค่า")
    
    api_key = st.text_input("API Key", value=DEFAULT_API_KEY, type="password")
    
    st.markdown("---")
    st.subheader("🔎 ค้นหาสถานที่")
    # New Feature: Search Box
    search_query = st.text_input("พิมพ์ชื่อสถานที่ (เช่น มหาวิทยาลัย...)", placeholder="ระบุชื่อสถานที่แล้วกด Enter")
    if search_query:
        # Check if we just searched this to avoid loop
        if 'last_search' not in st.session_state or st.session_state.last_search != search_query:
            with st.spinner(f"กำลังค้นหา '{search_query}'..."):
                result = geocode_search(api_key, search_query)
                if result:
                    st.session_state.markers.append(result)
                    st.session_state.map_center = [result['lat'], result['lng']] # Move map
                    st.session_state.last_search = search_query # Remember query
                    st.success(f"เจอแล้ว: {result['address']}")
                    time.sleep(1) # Give time to read
                    st.rerun()
                else:
                    st.warning("❌ ไม่พบสถานที่นี้")

    st.markdown("---")
    
    # ปุ่มจัดการหมุด
    col_btn1, col_btn2 = st.columns(2)
    with col_btn1:
        if st.button("❌ ลบจุดล่าสุด", use_container_width=True):
            if st.session_state.markers:
                st.session_state.markers.pop()
                st.rerun()
    with col_btn2:
        if st.button("🔄 รีเซ็ต", use_container_width=True):
            st.session_state.markers = [{'lat': DEFAULT_LAT, 'lng': DEFAULT_LON, 'address': 'จุดเริ่มต้น'}]
            st.session_state.isochrone_data = None
            st.session_state.map_center = [DEFAULT_LAT, DEFAULT_LON]
            st.rerun()
            
    st.write(f"📍 จุดวิเคราะห์: **{len(st.session_state.markers)}**")
    
    # แสดงรายการจุดพร้อมที่อยู่
    if st.session_state.markers:
        st.markdown("---")
        for i, m in enumerate(st.session_state.markers):
            color_name = MARKER_COLORS[i % len(MARKER_COLORS)]
            addr_short = m.get('address', 'Unknown')[:30] + "..." if len(m.get('address', '')) > 30 else m.get('address', 'Unknown')
            st.markdown(f"<span style='color:{color_name};'>●</span> <b>จุดที่ {i+1}</b><br><span style='font-size:0.8em; color:gray'>{addr_short}</span>", unsafe_allow_html=True)

    st.markdown("---")
    
    map_style = st.selectbox("สไตล์แผนที่", ["OpenStreetMap", "CartoDB positron", "CartoDB dark_matter"])
    travel_mode = st.selectbox(
        "รูปแบบการเดินทาง",
        options=["drive", "walk", "bicycle", "transit"], 
        format_func=lambda x: {"drive": "🚗 ขับรถ", "walk": "🚶 เดินเท้า", "bicycle": "🚲 ปั่นจักรยาน", "transit": "🚌 ขนส่งสาธารณะ"}[x]
    )
    time_intervals = st.multiselect("ช่วงเวลา (นาที)", options=[5, 10, 15, 30, 45, 60], default=[15])

    with st.expander("🎨 ตั้งค่าสีพื้นที่"):
        st.session_state.colors['step1'] = st.color_picker("≤ 10 นาที", st.session_state.colors['step1'])
        st.session_state.colors['step2'] = st.color_picker("11 - 20 นาที", st.session_state.colors['step2'])
        st.session_state.colors['step3'] = st.color_picker("21 - 30 นาที", st.session_state.colors['step3'])
        st.session_state.colors['step4'] = st.color_picker("> 30 นาที", st.session_state.colors['step4'])

    st.markdown("---")
    submit_button = st.button("🚀 คำนวณพื้นที่ให้บริการ", type="primary", use_container_width=True)

# --- 5. Logic Execution ---
if submit_button:
    if not api_key:
        st.warning("⚠️ กรุณาใส่ API Key")
    elif not st.session_state.markers:
        st.warning("⚠️ กรุณาเพิ่มหมุด")
    elif not time_intervals:
        st.warning("⚠️ กรุณาเลือกเวลา")
    else:
        with st.spinner('กำลังวิเคราะห์พื้นที่เดินทาง...'):
            st.session_state.isochrone_data = fetch_isochrones(
                api_key, st.session_state.markers, travel_mode, time_intervals
            )
            st.success("✅ คำนวณสำเร็จ!")

# --- 6. Display Map ---
def display_map():
    # ใช้ Center จาก State (เผื่อกรณี Search แล้วแผนที่ย้ายจุด)
    m = folium.Map(location=st.session_state.map_center, zoom_start=12, tiles=map_style)

    if st.session_state.isochrone_data:
        folium.GeoJson(
            st.session_state.isochrone_data,
            name='Isochrone',
            style_function=lambda feature: {
                'fillColor': get_fill_color(feature['properties']['travel_time_minutes']),
                'color': get_border_color(feature['properties']['marker_index']),
                'weight': 2, 'fillOpacity': 0.4
            },
            tooltip=folium.GeoJsonTooltip(fields=['travel_time_minutes'], aliases=['นาที:'])
        ).add_to(m)

    for i, marker in enumerate(st.session_state.markers):
        color_name = MARKER_COLORS[i % len(MARKER_COLORS)]
        addr = marker.get('address', 'Unknown')
        folium.Marker(
            [marker['lat'], marker['lng']],
            popup=f"<b>จุดที่ {i+1}</b><br>{addr}",
            icon=folium.Icon(color=color_name, icon="map-marker", prefix='fa')
        ).add_to(m)

    map_output = st_folium(m, width=1200, height=600, key="geoapify_ck_map")
    
    # Handle Map Click -> Add Marker + Reverse Geocode
    if map_output and map_output.get('last_clicked'):
        clicked_lat = map_output['last_clicked']['lat']
        clicked_lng = map_output['last_clicked']['lng']
        
        is_new = True
        if st.session_state.markers:
            last_mk = st.session_state.markers[-1]
            if abs(clicked_lat - last_mk['lat']) < 0.0001 and abs(clicked_lng - last_mk['lng']) < 0.0001:
                is_new = False
        
        if is_new:
            # ดึงชื่อสถานที่จริงมาใส่ (Reverse Geocode)
            new_addr = reverse_geocode(api_key, clicked_lat, clicked_lng)
            st.session_state.markers.append({'lat': clicked_lat, 'lng': clicked_lng, 'address': new_addr})
            st.rerun()

display_map()
