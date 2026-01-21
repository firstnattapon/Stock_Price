# import streamlit as st
# import folium
# from streamlit_folium import st_folium
# import requests
# from shapely.geometry import shape, mapping
# import json
# from typing import List, Dict, Any, Optional, Tuple

# # ============================================================================
# # 1. CONSTANTS & CONFIGURATION
# # ============================================================================

# PAGE_CONFIG = {
#     "page_title": "Dormitory Site Selection (Chiang Khong)",
#     "page_icon": "🏢",
#     "layout": "wide"
# }

# DEFAULT_JSON_URL = "https://raw.githubusercontent.com/firstnattapon/Stock_Price/refs/heads/main/Geoapify_Map/geoapify_cbd_project.json"

# DEFAULT_LAT = 20.219443
# DEFAULT_LON = 100.403630
# DEFAULT_API_KEY = "4eefdfb0b0d349e595595b9c03a69e3d"

# MARKER_COLORS = ['red', 'blue', 'green', 'purple', 'orange', 'black', 'pink', 'cadetblue']
# HEX_COLORS = ['#D63E2A', '#38AADD', '#72B026', '#D252B9', '#F69730', '#333333', '#FF91EA', '#436978']

# MAP_STYLES = {
#     "OpenStreetMap (มาตรฐาน)": {"tiles": "OpenStreetMap", "attr": None},
#     "CartoDB Positron (สีอ่อน/สะอาด)": {"tiles": "CartoDB positron", "attr": None},
#     "CartoDB Dark Matter (สีเข้ม)": {"tiles": "CartoDB dark_matter", "attr": None},
# }

# TRAVEL_MODE_NAMES = {
#     "drive": "🚗 ขับรถ",
#     "walk": "🚶 เดินเท้า",
#     "bicycle": "🚲 ปั่นจักรยาน",
#     "transit": "🚌 ขนส่งสาธารณะ"
# }

# TIME_OPTIONS = [5, 10, 15, 20, 30]

# # --- NEW: POI Categories for Dormitory Business ---
# POI_CATEGORIES = {
#     "🎓 แหล่งคนเช่า: สถานศึกษา (Education)": "education",
#     "🏭 แหล่งคนเช่า: แหล่งงาน/อุตสาหกรรม (Industrial)": "commercial.industrial,office",
#     "🏪 สิ่งอำนวยความสะดวก: ร้านสะดวกซื้อ/ตลาด (Commercial)": "commercial.supermarket,commercial.convenience,commercial.marketplace",
#     "🏥 สิ่งอำนวยความสะดวก: โรงพยาบาล (Healthcare)": "healthcare",
#     "🏢 คู่แข่ง: หอพัก/อพาร์ทเม้นท์ (Residential)": "accommodation.hut,building.residential"
# }

# POI_COLORS = {
#     "education": "blue",
#     "commercial": "green",
#     "healthcare": "red",
#     "accommodation": "purple",
#     "other": "gray"
# }

# # ============================================================================
# # 2. PURE HELPER FUNCTIONS
# # ============================================================================

# def get_fill_color(minutes: float, colors_config: Dict[str, str]) -> str:
#     if minutes <= 10: return colors_config['step1']
#     elif minutes <= 20: return colors_config['step2']
#     elif minutes <= 30: return colors_config['step3']
#     else: return colors_config['step4']

# def get_border_color(original_marker_idx: Optional[int]) -> str:
#     if original_marker_idx is None: return '#3388ff'
#     return HEX_COLORS[original_marker_idx % len(HEX_COLORS)]

# def calculate_intersection(features: List[Dict], num_active_markers: int) -> Optional[Dict]:
#     if num_active_markers < 2: return None
#     polys_per_active_idx = {}
#     for feat in features:
#         active_idx = feat['properties']['active_index']
#         geom = shape(feat['geometry'])
#         if active_idx not in polys_per_active_idx:
#             polys_per_active_idx[active_idx] = geom
#         else:
#             polys_per_active_idx[active_idx] = polys_per_active_idx[active_idx].union(geom)
    
#     if len(polys_per_active_idx) < num_active_markers: return None
#     active_indices = sorted(polys_per_active_idx.keys())
#     try:
#         intersection_poly = polys_per_active_idx[active_indices[0]]
#         for idx in active_indices[1:]:
#             intersection_poly = intersection_poly.intersection(polys_per_active_idx[idx])
#             if intersection_poly.is_empty: return None
#         return mapping(intersection_poly) if not intersection_poly.is_empty else None
#     except Exception: return None

# @st.cache_data(show_spinner=False, ttl=3600)
# def fetch_api_data_cached(api_key: str, travel_mode: str, ranges_str: str, marker_lat: float, marker_lon: float) -> Optional[List[Dict]]:
#     url = "https://api.geoapify.com/v1/isoline"
#     params = {"lat": marker_lat, "lon": marker_lon, "type": "time", "mode": travel_mode, "range": ranges_str, "apiKey": api_key}
#     try:
#         response = requests.get(url, params=params, timeout=10)
#         return response.json().get('features', []) if response.status_code == 200 else None
#     except Exception: return None

# # --- NEW: Function to fetch POIs ---
# @st.cache_data(show_spinner=False, ttl=3600)
# def fetch_places_cached(api_key: str, categories: str, lat: float, lon: float, radius: int = 2000) -> List[Dict]:
#     """Fetch Places of Interest (POI) from Geoapify."""
#     url = "https://api.geoapify.com/v2/places"
#     params = {
#         "categories": categories,
#         "filter": f"circle:{lon},{lat},{radius}",
#         "bias": f"proximity:{lon},{lat}",
#         "limit": 50,
#         "apiKey": api_key
#     }
#     try:
#         response = requests.get(url, params=params, timeout=10)
#         if response.status_code == 200:
#             return response.json().get('features', [])
#         return []
#     except Exception:
#         return []

# # ============================================================================
# # 3. STATE MANAGEMENT
# # ============================================================================

# def initialize_session_state():
#     defaults = {
#         'markers': [{'lat': DEFAULT_LAT, 'lng': DEFAULT_LON, 'active': True}],
#         'isochrone_data': None,
#         'intersection_data': None,
#         'poi_data': [], # NEW: Store found POIs
#         'colors': {'step1': '#2A9D8F', 'step2': '#E9C46A', 'step3': '#F4A261', 'step4': '#D62828'},
#         'api_key': DEFAULT_API_KEY,
#         'map_style_name': list(MAP_STYLES.keys())[0],
#         'travel_mode': "drive",
#         'time_intervals': [10]
#     }
#     # Load defaults from URL if clean start
#     if 'markers' not in st.session_state:
#         try:
#             r = requests.get(DEFAULT_JSON_URL, timeout=3)
#             if r.status_code == 200:
#                 data = r.json()
#                 defaults.update({k: data.get(k, v) for k, v in defaults.items()})
#         except: pass

#     for key, default_val in defaults.items():
#         if key not in st.session_state: st.session_state[key] = default_val
    
#     for m in st.session_state.markers:
#         if 'active' not in m: m['active'] = True

# def get_active_markers():
#     return [(i, m) for i, m in enumerate(st.session_state.markers) if m.get('active', True)]

# # ============================================================================
# # 4. MAIN APP
# # ============================================================================

# st.set_page_config(**PAGE_CONFIG)
# st.markdown("""<style>.block-container { padding-top: 2rem; } h1 { margin-bottom: 0px; }</style>""", unsafe_allow_html=True)

# initialize_session_state()

# with st.sidebar:
#     st.header("🏢 ค้นหาทำเลหอพัก")
    
#     # 1. API Key
#     st.text_input("API Key (Geoapify)", key="api_key", type="password")
    
#     # 2. Add Marker
#     with st.container():
#         st.caption("📍 ปักหมุดที่ดิน/ตำแหน่งสนใจ")
#         c1, c2 = st.columns([0.7, 0.3])
#         new_coords = c1.text_input("Lat, Lon", placeholder="20.21, 100.40", label_visibility="collapsed")
#         if c2.button("เพิ่ม", use_container_width=True):
#             if new_coords:
#                 try:
#                     parts = new_coords.split(',')
#                     lat, lng = float(parts[0]), float(parts[1])
#                     st.session_state.markers.append({'lat': lat, 'lng': lng, 'active': True})
#                     st.session_state.isochrone_data = None
#                     st.rerun()
#                 except: st.error("พิกัดผิดพลาด")

#     # 3. List Markers
#     if st.session_state.markers:
#         st.markdown("---")
#         for i, m in enumerate(st.session_state.markers):
#             col_chk, col_txt, col_del = st.columns([0.15, 0.7, 0.15])
#             active = col_chk.checkbox("", m.get('active', True), key=f"act_{i}")
#             st.session_state.markers[i]['active'] = active
#             col_txt.markdown(f"**จุดที่ {i+1}** <span style='font-size:0.8em'>({m['lat']:.3f}, {m['lng']:.3f})</span>", unsafe_allow_html=True)
#             if col_del.button("✕", key=f"del_{i}"):
#                 st.session_state.markers.pop(i)
#                 st.rerun()
        
#         if st.button("ลบจุดล่าสุด"):
#             st.session_state.markers.pop()
#             st.rerun()

#     st.markdown("---")
    
#     # 4. Isochrone Settings
#     st.subheader("1. วิเคราะห์ระยะเดินทาง")
#     st.selectbox("พาหนะ", list(TRAVEL_MODE_NAMES.keys()), format_func=lambda x: TRAVEL_MODE_NAMES[x], key="travel_mode")
#     st.multiselect("นาที", TIME_OPTIONS, key="time_intervals")
    
#     if st.button("🚀 คำนวณพื้นที่ (Isochrone)", type="primary", use_container_width=True):
#         active_list = get_active_markers()
#         if not active_list or not st.session_state.api_key:
#             st.error("ใส่ API Key และเลือกจุด")
#         else:
#             with st.spinner("Calculating..."):
#                 all_feats = []
#                 ranges = ",".join([str(t*60) for t in sorted(st.session_state.time_intervals)])
#                 for idx, (orig_idx, m) in enumerate(active_list):
#                     feats = fetch_api_data_cached(st.session_state.api_key, st.session_state.travel_mode, ranges, m['lat'], m['lng'])
#                     if feats:
#                         for f in feats:
#                             f['properties'].update({'active_index': idx, 'original_index': orig_idx, 'travel_time_minutes': f['properties'].get('value',0)/60})
#                             all_feats.append(f)
                
#                 st.session_state.isochrone_data = {"type": "FeatureCollection", "features": all_feats} if all_feats else None
#                 cbd = calculate_intersection(all_feats, len(active_list))
#                 st.session_state.intersection_data = {"type": "FeatureCollection", "features": [{"type": "Feature", "geometry": cbd, "properties": {"type": "cbd"}}]} if cbd else None

#     # --- NEW: POI Finder Section ---
#     st.markdown("---")
#     st.subheader("2. สำรวจสิ่งรอบข้าง (POI)")
#     st.caption("ค้นหา 'Demand' หรือ 'คู่แข่ง' ในรัศมี 2 กม. จากจุดที่เลือก")
    
#     selected_poi_type = st.selectbox("เลือกประเภทสถานที่", list(POI_CATEGORIES.keys()))
    
#     if st.button("🔍 ค้นหาสถานที่ (Find POI)", use_container_width=True):
#         active_list = get_active_markers()
#         if not active_list:
#             st.warning("เลือกจุดก่อนครับ")
#         else:
#             cat_code = POI_CATEGORIES[selected_poi_type]
#             found_pois = []
#             with st.spinner(f"กำลังค้นหา {selected_poi_type}..."):
#                 for _, m in active_list:
#                     # Search around each active marker
#                     data = fetch_places_cached(st.session_state.api_key, cat_code, m['lat'], m['lng'])
#                     found_pois.extend(data)
            
#             st.session_state.poi_data = found_pois
#             if found_pois:
#                 st.success(f"เจอทั้งหมด {len(found_pois)} แห่ง")
#             else:
#                 st.warning("ไม่พบสถานที่ในหมวดหมู่นี้")


# # ============================================================================
# # MAP
# # ============================================================================

# style = MAP_STYLES[st.session_state.map_style_name]
# center = [DEFAULT_LAT, DEFAULT_LON]
# if st.session_state.markers: center = [st.session_state.markers[-1]['lat'], st.session_state.markers[-1]['lng']]

# m = folium.Map(location=center, zoom_start=13, tiles=style["tiles"], attr=style["attr"])

# # 1. Isochrones
# if st.session_state.isochrone_data:
#     folium.GeoJson(
#         st.session_state.isochrone_data,
#         style_function=lambda x: {
#             'fillColor': get_fill_color(x['properties']['travel_time_minutes'], st.session_state.colors),
#             'color': get_border_color(x['properties']['original_index']),
#             'weight': 1, 'fillOpacity': 0.2
#         },
#         tooltip=folium.GeoJsonTooltip(['travel_time_minutes'], aliases=['นาที:'])
#     ).add_to(m)

# # 2. CBD Intersection
# if st.session_state.intersection_data:
#     folium.GeoJson(
#         st.session_state.intersection_data,
#         style_function=lambda x: {'fillColor': '#FFD700', 'color': '#FF8C00', 'weight': 3, 'fillOpacity': 0.5, 'dashArray': '5, 5'},
#         tooltip="🏆 Prime Area (CBD)"
#     ).add_to(m)

# # 3. User Markers
# for i, marker in enumerate(st.session_state.markers):
#     if marker.get('active', True):
#         folium.Marker(
#             [marker['lat'], marker['lng']],
#             popup=f"Site {i+1}",
#             icon=folium.Icon(color=MARKER_COLORS[i % len(MARKER_COLORS)], icon="home", prefix='fa')
#         ).add_to(m)

# # --- NEW: POI Markers ---
# if st.session_state.poi_data:
#     poi_group = folium.FeatureGroup(name="POI Results")
#     for feat in st.session_state.poi_data:
#         props = feat.get('properties', {})
#         lat = props.get('lat')
#         lon = props.get('lon')
#         name = props.get('name', 'Unknown')
#         address = props.get('formatted', '')
        
#         # Determine icon based on category
#         cats = props.get('categories', [])
#         icon_name = "info-sign"
#         icon_color = "gray"
        
#         if "education" in str(cats): 
#             icon_name = "book"; icon_color = "blue"
#         elif "healthcare" in str(cats): 
#             icon_name = "plus"; icon_color = "red"
#         elif "commercial" in str(cats): 
#             icon_name = "shopping-cart"; icon_color = "green"
#         elif "accommodation" in str(cats): 
#             icon_name = "bed"; icon_color = "purple"
            
#         folium.Marker(
#             location=[lat, lon],
#             tooltip=f"<b>{name}</b>",
#             popup=f"{name}<br><span style='font-size:0.8em'>{address}</span>",
#             icon=folium.Icon(color=icon_color, icon=icon_name, prefix='glyphicon')
#         ).add_to(poi_group)
#     poi_group.add_to(m)

# folium.LayerControl().add_to(m)

# # Output
# map_out = st_folium(m, height=700, use_container_width=True)

# # Click to add marker
# if map_out and map_out.get('last_clicked'):
#     clat, clng = map_out['last_clicked']['lat'], map_out['last_clicked']['lng']
#     # Prevent duplicate clicks logic simplified
#     st.session_state.markers.append({'lat': clat, 'lng': clng, 'active': True})
#     st.session_state.isochrone_data = None 
#     st.rerun()
