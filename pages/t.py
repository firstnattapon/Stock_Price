import streamlit as st
import folium
from streamlit_folium import st_folium
import requests
from shapely.geometry import shape, mapping
import json
from typing import List, Dict, Any, Optional, Tuple

# ============================================================================
# 1. CONSTANTS & CONFIGURATION
# ============================================================================

PAGE_CONFIG = {
    "page_title": "Geoapify Map (Chiang Khong CBD)",
    "page_icon": "🌍",
    "layout": "wide"
}

DEFAULT_LAT = 20.219443
DEFAULT_LON = 100.403630
DEFAULT_API_KEY = "4eefdfb0b0d349e595595b9c03a69e3d"

MARKER_COLORS = ['red', 'blue', 'green', 'purple', 'orange', 'black', 'pink', 'cadetblue']
HEX_COLORS = ['#D63E2A', '#38AADD', '#72B026', '#D252B9', '#F69730', '#333333', '#FF91EA', '#436978']

MAP_STYLES = {
    "OpenStreetMap (มาตรฐาน)": {"tiles": "OpenStreetMap", "attr": None},
    "CartoDB Positron (สีอ่อน/สะอาด)": {"tiles": "CartoDB positron", "attr": None},
    "CartoDB Dark Matter (สีเข้ม)": {"tiles": "CartoDB dark_matter", "attr": None},
    "Esri Satellite (ดาวเทียม)": {
        "tiles": "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        "attr": "Tiles &copy; Esri &mdash; Source: Esri"
    },
    "Esri Street Map (ถนนละเอียด)": {
        "tiles": "https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}",
        "attr": "Tiles &copy; Esri &mdash; Source: Esri"
    }
}

TRAVEL_MODE_NAMES = {
    "drive": "🚗 ขับรถ",
    "walk": "🚶 เดินเท้า",
    "bicycle": "🚲 ปั่นจักรยาน",
    "transit": "🚌 ขนส่งสาธารณะ"
}

TIME_OPTIONS = [5, 10, 15, 20, 30, 45, 60]

# ============================================================================
# 2. PURE HELPER FUNCTIONS (Logic & Calculation)
# ============================================================================

def get_fill_color(minutes: float, colors_config: Dict[str, str]) -> str:
    """Determine fill color based on travel time."""
    if minutes <= 10:
        return colors_config['step1']
    elif minutes <= 20:
        return colors_config['step2']
    elif minutes <= 30:
        return colors_config['step3']
    else:
        return colors_config['step4']

def get_border_color(original_marker_idx: Optional[int]) -> str:
    """Get border color for isochrone based on marker index."""
    if original_marker_idx is None:
        return '#3388ff'
    return HEX_COLORS[original_marker_idx % len(HEX_COLORS)]

def calculate_intersection(features: List[Dict], num_active_markers: int) -> Optional[Dict]:
    """
    Calculate geometric intersection of all active marker isochrones.
    
    Returns:
        GeoJSON geometry dict or None if no intersection exists
    """
    if num_active_markers < 2:
        return None
    
    # Group polygons by active_index
    polys_per_active_idx = {}
    
    for feat in features:
        active_idx = feat['properties']['active_index']
        geom = shape(feat['geometry'])
        
        if active_idx not in polys_per_active_idx:
            polys_per_active_idx[active_idx] = geom
        else:
            # Union multiple shapes from same marker
            polys_per_active_idx[active_idx] = polys_per_active_idx[active_idx].union(geom)
    
    # Verify completeness
    if len(polys_per_active_idx) < num_active_markers:
        return None
    
    # Calculate intersection across all markers
    active_indices = sorted(polys_per_active_idx.keys())
    
    try:
        intersection_poly = polys_per_active_idx[active_indices[0]]
        
        for idx in active_indices[1:]:
            intersection_poly = intersection_poly.intersection(polys_per_active_idx[idx])
            if intersection_poly.is_empty:
                return None
        
        return mapping(intersection_poly) if not intersection_poly.is_empty else None
    
    except Exception as e:
        st.error(f"Intersection calculation error: {e}")
        return None

@st.cache_data(show_spinner=False, ttl=3600)
def fetch_api_data_cached(
    api_key: str,
    travel_mode: str,
    ranges_str: str,
    marker_lat: float,
    marker_lon: float
) -> Optional[List[Dict]]:
    """
    Fetch isochrone data from Geoapify API with caching.
    Cache TTL = 1 hour to balance freshness and performance.
    """
    url = "https://api.geoapify.com/v1/isoline"
    params = {
        "lat": marker_lat,
        "lon": marker_lon,
        "type": "time",
        "mode": travel_mode,
        "range": ranges_str,
        "apiKey": api_key
    }
    
    try:
        response = requests.get(url, params=params, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            return data.get('features', [])
        else:
            return None
            
    except requests.exceptions.Timeout:
        return None
    except Exception:
        return None

# ============================================================================
# 3. STATE MANAGEMENT
# ============================================================================

def initialize_session_state():
    """Initialize all session state variables with defaults."""
    defaults = {
        'markers': [{'lat': DEFAULT_LAT, 'lng': DEFAULT_LON, 'active': True}],
        'isochrone_data': None,
        'intersection_data': None,
        'colors': {
            'step1': '#2A9D8F',
            'step2': '#E9C46A',
            'step3': '#F4A261',
            'step4': '#D62828'
        },
        'api_key': DEFAULT_API_KEY,
        'map_style_name': list(MAP_STYLES.keys())[0],
        'travel_mode': "drive",
        'time_intervals': [5]
    }
    
    for key, default_val in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = default_val
    
    # Migration: ensure 'active' key exists in all markers
    for m in st.session_state.markers:
        if 'active' not in m:
            m['active'] = True

def get_active_markers() -> List[Tuple[int, Dict]]:
    """
    Get list of active markers with their original indices.
    
    Returns:
        List of (original_index, marker_dict) tuples
    """
    return [
        (i, m) for i, m in enumerate(st.session_state.markers)
        if m.get('active', True)
    ]

# ============================================================================
# 4. MAIN APP
# ============================================================================

st.set_page_config(**PAGE_CONFIG)

# Custom CSS
st.markdown("""
    <style>
        .block-container {
            padding-top: 2rem;
            padding-bottom: 0rem;
            padding-left: 2rem;
            padding-right: 2rem;
        }
        h1 { margin-bottom: 0px; }
        div[data-testid="stHorizontalBlock"] button {
            padding: 0rem 0.5rem;
            line-height: 1.5;
        }
        div[data-testid="stMarkdownContainer"] p {
            margin-bottom: 0px;
        }
    </style>
""", unsafe_allow_html=True)

initialize_session_state()

# ============================================================================
# SIDEBAR
# ============================================================================

with st.sidebar:
    st.header("⚙️ การตั้งค่า")
    
    # --- File Import/Export ---
    with st.expander("📂 จัดการไฟล์ (Import / Export)", expanded=False):
        # Export
        export_data = {
            "markers": st.session_state.markers,
            "isochrone_data": st.session_state.isochrone_data,
            "intersection_data": st.session_state.intersection_data,
            "colors": st.session_state.colors,
            "api_key": st.session_state.api_key,
            "map_style_name": st.session_state.map_style_name,
            "travel_mode": st.session_state.travel_mode,
            "time_intervals": st.session_state.time_intervals
        }
        
        st.download_button(
            label="💾 บันทึกไฟล์ (Export JSON)",
            data=json.dumps(export_data, indent=2),
            file_name="geoapify_cbd_project.json",
            mime="application/json",
            use_container_width=True
        )
        
        # Import
        uploaded_file = st.file_uploader("📂 เปิดไฟล์เดิม (Import JSON)", type=["json"])
        if uploaded_file is not None:
            try:
                data = json.load(uploaded_file)
                
                # Update state with imported data
                st.session_state.markers = data.get("markers", st.session_state.markers)
                
                # Migration: ensure 'active' key
                for m in st.session_state.markers:
                    if 'active' not in m:
                        m['active'] = True
                
                st.session_state.isochrone_data = data.get("isochrone_data", None)
                st.session_state.intersection_data = data.get("intersection_data", None)
                st.session_state.colors = data.get("colors", st.session_state.colors)
                st.session_state.api_key = data.get("api_key", DEFAULT_API_KEY)
                st.session_state.map_style_name = data.get("map_style_name", st.session_state.map_style_name)
                st.session_state.travel_mode = data.get("travel_mode", st.session_state.travel_mode)
                st.session_state.time_intervals = data.get("time_intervals", st.session_state.time_intervals)
                
                st.success("✅ โหลดข้อมูลสำเร็จ!")
                if st.button("🔄 รีเฟรชหน้าจอ"):
                    st.rerun()
                    
            except Exception as e:
                st.error(f"❌ ไฟล์ไม่ถูกต้อง: {e}")
    
    st.markdown("---")
    
    # API Key (use key parameter for automatic binding)
    st.text_input("API Key", key="api_key", type="password")
    
    st.markdown("---")
    
    # --- Control Buttons ---
    col_btn1, col_btn2 = st.columns(2)
    
    with col_btn1:
        if st.button("❌ ลบจุดล่าสุด", use_container_width=True):
            if st.session_state.markers:
                st.session_state.markers.pop()
                st.session_state.isochrone_data = None
                st.session_state.intersection_data = None
                st.rerun()
    
    with col_btn2:
        if st.button("🔄 รีเซ็ตทั้งหมด", use_container_width=True):
            st.session_state.markers = [{'lat': DEFAULT_LAT, 'lng': DEFAULT_LON, 'active': True}]
            st.session_state.isochrone_data = None
            st.session_state.intersection_data = None
            st.rerun()
    
    # Display marker statistics
    active_list = get_active_markers()
    st.write(f"📍 จุดที่เลือกคำนวณ: **{len(active_list)}** / {len(st.session_state.markers)}")
    
    # --- Marker List with Isolation Controls ---
    if st.session_state.markers:
        st.markdown("---")
        st.caption("✅ = นำมาคำนวณ | ❌ = ลบทิ้ง")
        
        for i, m in enumerate(st.session_state.markers):
            color_name = MARKER_COLORS[i % len(MARKER_COLORS)]
            
            col_chk, col_txt, col_del = st.columns([0.15, 0.70, 0.15])
            
            with col_chk:
                # Use checkbox with unique key - update happens on next rerun
                is_active = st.checkbox(
                    " ",
                    value=m.get('active', True),
                    key=f"active_chk_{i}",
                    label_visibility="collapsed"
                )
                # Update state (will take effect on next interaction)
                st.session_state.markers[i]['active'] = is_active
            
            with col_txt:
                if is_active:
                    text_style = f"color:{color_name}; font-weight:bold;"
                else:
                    text_style = "color:gray; text-decoration:line-through;"
                
                st.markdown(
                    f"<span style='{text_style}'>● จุดที่ {i+1}</span><br>"
                    f"<span style='font-size:0.8em; color:gray;'>"
                    f"({m['lat']:.4f}, {m['lng']:.4f})</span>",
                    unsafe_allow_html=True
                )
            
            with col_del:
                if st.button("✕", key=f"del_btn_{i}", help=f"ลบจุดที่ {i+1}"):
                    st.session_state.markers.pop(i)
                    st.session_state.isochrone_data = None
                    st.session_state.intersection_data = None
                    st.rerun()
    
    st.markdown("---")
    
    # --- Map Configuration ---
    st.selectbox(
        "สไตล์แผนที่",
        list(MAP_STYLES.keys()),
        key="map_style_name"
    )
    
    st.selectbox(
        "รูปแบบการเดินทาง",
        options=list(TRAVEL_MODE_NAMES.keys()),
        format_func=lambda x: TRAVEL_MODE_NAMES[x],
        key="travel_mode"
    )
    
    st.multiselect(
        "ช่วงเวลา (นาที)",
        options=TIME_OPTIONS,
        key="time_intervals"
    )
    
    # --- Color Configuration ---
    with st.expander("🎨 ตั้งค่าสีพื้นที่"):
        st.session_state.colors['step1'] = st.color_picker(
            "≤ 10 นาที",
            st.session_state.colors['step1']
        )
        st.session_state.colors['step2'] = st.color_picker(
            "11 - 20 นาที",
            st.session_state.colors['step2']
        )
        st.session_state.colors['step3'] = st.color_picker(
            "21 - 30 นาที",
            st.session_state.colors['step3']
        )
        st.session_state.colors['step4'] = st.color_picker(
            "> 30 นาที",
            st.session_state.colors['step4']
        )
    
    st.markdown("---")
    
    # Calculate button
    do_calculate = st.button(
        "🚀 คำนวณหา CBD (เฉพาะจุดที่เลือก)",
        type="primary",
        use_container_width=True
    )

# ============================================================================
# CALCULATION LOGIC
# ============================================================================

if do_calculate:
    active_markers_list = get_active_markers()
    
    # Validation
    if not st.session_state.api_key:
        st.warning("⚠️ กรุณาใส่ API Key")
    elif not active_markers_list:
        st.warning("⚠️ กรุณาเลือกจุดอย่างน้อย 1 จุด (ติ๊กถูก)")
    elif not st.session_state.time_intervals:
        st.warning("⚠️ กรุณาเลือกช่วงเวลา")
    else:
        with st.spinner(f'กำลังวิเคราะห์ข้อมูล {len(active_markers_list)} จุด...'):
            try:
                all_features = []
                ranges_str = ",".join([
                    str(t * 60) for t in sorted(st.session_state.time_intervals)
                ])
                
                # Fetch data for each active marker
                for active_idx, (orig_idx, marker) in enumerate(active_markers_list):
                    features = fetch_api_data_cached(
                        st.session_state.api_key,
                        st.session_state.travel_mode,
                        ranges_str,
                        marker['lat'],
                        marker['lng']
                    )
                    
                    if features:
                        for feat in features:
                            # Calculate travel time in minutes
                            seconds = feat['properties'].get('value', 0)
                            feat['properties']['travel_time_minutes'] = seconds / 60
                            
                            # Store both indices
                            feat['properties']['original_index'] = orig_idx
                            feat['properties']['active_index'] = active_idx
                            
                            all_features.append(feat)
                    else:
                        st.error(f"❌ API Error at Marker {orig_idx + 1}")
                
                # Process results
                if all_features:
                    st.session_state.isochrone_data = {
                        "type": "FeatureCollection",
                        "features": all_features
                    }
                    
                    # Calculate CBD intersection
                    cbd_geom = calculate_intersection(all_features, len(active_markers_list))
                    
                    if cbd_geom:
                        st.session_state.intersection_data = {
                            "type": "FeatureCollection",
                            "features": [{
                                "type": "Feature",
                                "geometry": cbd_geom,
                                "properties": {"type": "cbd"}
                            }]
                        }
                        st.success(f"✅ พบพื้นที่ CBD ร่วมกันของ {len(active_markers_list)} จุด!")
                    else:
                        st.session_state.intersection_data = None
                        if len(active_markers_list) > 1:
                            st.warning("⚠️ ไม่พบพื้นที่ทับซ้อนสำหรับจุดที่เลือก")
                        else:
                            st.success("✅ คำนวณพื้นที่ (จุดเดียว) สำเร็จ")
                else:
                    st.error("❌ ไม่ได้รับข้อมูลจาก API")
                    
            except Exception as e:
                st.error(f"❌ Error: {e}")

# ============================================================================
# MAP RENDERING
# ============================================================================

# Get map configuration
style_config = MAP_STYLES[st.session_state.map_style_name]
active_markers_list = get_active_markers()

# Determine map center
if active_markers_list:
    _, last_marker = active_markers_list[-1]
    center_point = [last_marker['lat'], last_marker['lng']]
elif st.session_state.markers:
    last_marker = st.session_state.markers[-1]
    center_point = [last_marker['lat'], last_marker['lng']]
else:
    center_point = [DEFAULT_LAT, DEFAULT_LON]

# Create base map
m = folium.Map(
    location=center_point,
    zoom_start=11,
    tiles=style_config["tiles"],
    attr=style_config["attr"]
)

# Layer 1: Isochrone Areas
if st.session_state.isochrone_data:
    folium.GeoJson(
        st.session_state.isochrone_data,
        name='Travel Areas',
        style_function=lambda feature: {
            'fillColor': get_fill_color(
                feature['properties']['travel_time_minutes'],
                st.session_state.colors
            ),
            'color': get_border_color(feature['properties']['original_index']),
            'weight': 1,
            'fillOpacity': 0.2
        },
        tooltip=folium.GeoJsonTooltip(
            fields=['travel_time_minutes'],
            aliases=['นาที:']
        )
    ).add_to(m)

# Layer 2: CBD Intersection
if st.session_state.intersection_data:
    folium.GeoJson(
        st.session_state.intersection_data,
        name='🏆 Common CBD Area',
        style_function=lambda feature: {
            'fillColor': '#FFD700',
            'color': '#FF8C00',
            'weight': 3,
            'fillOpacity': 0.6,
            'dashArray': '5, 5'
        },
        tooltip="🏆 พื้นที่จุดศูนย์กลาง (CBD)"
    ).add_to(m)

# Layer 3: Markers
for i, marker in enumerate(st.session_state.markers):
    is_active = marker.get('active', True)
    
    if is_active:
        color_name = MARKER_COLORS[i % len(MARKER_COLORS)]
        icon_type = "map-marker"
        opacity = 1.0
        popup_msg = f"<b>จุดที่ {i+1}</b> (Active)<br>ใช้คำนวณ"
    else:
        color_name = "gray"
        icon_type = "ban"
        opacity = 0.5
        popup_msg = f"<b>จุดที่ {i+1}</b> (Inactive)<br>ไม่ถูกนำมาคำนวณ"
    
    folium.Marker(
        [marker['lat'], marker['lng']],
        popup=popup_msg,
        icon=folium.Icon(color=color_name, icon=icon_type, prefix='fa'),
        opacity=opacity
    ).add_to(m)

# Add layer control
folium.LayerControl().add_to(m)

# Render map
map_output = st_folium(
    m,
    height=850,
    use_container_width=True,
    key="geoapify_main_map"
)

# Handle map clicks to add new markers
if map_output and map_output.get('last_clicked'):
    clicked_lat = map_output['last_clicked']['lat']
    clicked_lng = map_output['last_clicked']['lng']
    
    # Debounce: prevent duplicate clicks
    is_duplicate = False
    if st.session_state.markers:
        last_mk = st.session_state.markers[-1]
        if (abs(clicked_lat - last_mk['lat']) < 1e-5 and
            abs(clicked_lng - last_mk['lng']) < 1e-5):
            is_duplicate = True
    
    if not is_duplicate:
        # Add new marker (active by default)
        st.session_state.markers.append({
            'lat': clicked_lat,
            'lng': clicked_lng,
            'active': True
        })
        
        # Reset calculation results
        st.session_state.isochrone_data = None
        st.session_state.intersection_data = None
        st.rerun()
