import streamlit as st
import pandas as pd
import numpy as np
import pydeck as pdk
from geopy.distance import great_circle

# --- ตั้งค่าหน้า Streamlit ---
st.set_page_config(layout="wide")
st.title("แอปจำลองแผนที่การไล่ระดับของค่าเช่า (Rent Gradient Map)")
st.write("""
แอปนี้จำลองทฤษฎี **Rent Gradient** ในทางเศรษฐศาสตร์เมือง 
ที่อธิบายว่าค่าเช่าที่ดินจะลดลงเมื่อระยะทางห่างจากจุดศูนย์กลาง (CBD) เพิ่มมากขึ้น
คุณสามารถปรับพารามิเตอร์ต่างๆ ได้ในแถบด้านข้าง
""")

# --- ส่วนรับข้อมูล (Sidebar) ---
st.sidebar.header("ตั้งค่าพารามิเตอร์")

# 1. กำหนดจุดศูนย์กลาง (CBD)
st.sidebar.subheader("1. กำหนดจุดศูนย์กลาง (CBD)")
# ใช้ค่าเริ่มต้นเป็นกรุงเทพฯ (อนุสาวรีย์ชัยสมรภูมิ)
cbd_lat = st.sidebar.number_input("ละติจูด (Latitude) ของ CBD", value=13.7649, format="%.4f")
cbd_lon = st.sidebar.number_input("ลองจิจูด (Longitude) ของ CBD", value=100.5383, format="%.4f")
cbd_coords = (cbd_lat, cbd_lon)

# 2. กำหนดพารามิเตอร์ของแบบจำลอง
st.sidebar.subheader("2. กำหนดแบบจำลองค่าเช่า")
max_rent = st.sidebar.slider("ค่าเช่าสูงสุด (ที่ CBD)", min_value=1000, max_value=20000, value=10000, step=100)
# อัตราการลดลง (Decay Rate)
decay_rate = st.sidebar.slider("อัตราการลดลงของค่าเช่า (Decay Rate)", min_value=0.01, max_value=1.0, value=0.1, step=0.01)
st.sidebar.caption("ค่ายิ่งมาก ค่าเช่ายิ่งลดลงเร็วเมื่อห่างจาก CBD")

# 3. กำหนดพื้นที่แสดงผล
st.sidebar.subheader("3. กำหนดพื้นที่แสดงผล")
radius_km = st.sidebar.slider("รัศมีที่จะคำนวณ (กม.)", min_value=10, max_value=100, value=50, step=5)
grid_density = st.sidebar.slider("ความละเอียดของกริด (N x N)", min_value=20, max_value=100, value=50, step=5)
st.sidebar.caption(f"จะคำนวณทั้งหมด {grid_density*grid_density} จุด")

# --- ฟังก์ชันสร้างข้อมูล (ใช้ Cache เพื่อความเร็ว) ---
@st.cache_data
def generate_rent_grid(center_lat, center_lon, max_r, decay, radius, grid_n):
    """
    สร้าง DataFrame ของจุดต่างๆ รอบ CBD พร้อมค่าเช่าที่คำนวณได้
    """
    center_point = (center_lat, center_lon)
    
    # สร้างขอบเขตของกริด (ประมาณ 1 องศา ~ 111 กม.)
    lat_offset = radius / 111.0
    lon_offset = radius / (111.0 * np.cos(np.radians(center_lat))) # ปรับตามละติจูด
    
    # สร้างชุดของละติจูดและลองจิจูด
    lats = np.linspace(center_lat - lat_offset, center_lat + lat_offset, grid_n)
    lons = np.linspace(center_lon - lon_offset, center_lon + lon_offset, grid_n)
    
    # สร้างกริด
    grid_lats, grid_lons = np.meshgrid(lats, lons)
    
    points_data = []
    
    # วนลูปคำนวณทุกจุดในกริด
    for lat, lon in zip(grid_lats.ravel(), grid_lons.ravel()):
        point_coords = (lat, lon)
        
        # คำนวณระยะทางจาก CBD
        distance = great_circle(center_point, point_coords).km
        
        # คำนวณค่าเช่าโดยใช้ Exponential Decay Model
        # rent = max_rent * e^(-decay * distance)
        if distance <= radius:
            rent = max_r * np.exp(-decay * distance)
            points_data.append([lat, lon, rent, distance])

    df = pd.DataFrame(points_data, columns=['lat', 'lon', 'rent', 'distance_km'])
    return df.query("rent > 0") # กรองเเฉพาะจุดที่มีค่าเช่า

# --- ประมวลผลและแสดงผล ---

# สร้างข้อมูล
rent_data_df = generate_rent_grid(cbd_lat, cbd_lon, max_rent, decay_rate, radius_km, grid_density)

if rent_data_df.empty:
    st.warning("ไม่สามารถสร้างข้อมูลได้ กรุณาลองปรับพารามิเตอร์")
else:
    # --- สร้างแผนที่ด้วย PyDeck ---

    # 1. Layer สำหรับ Heatmap แสดงการไล่ระดับค่าเช่า
    heatmap_layer = pdk.Layer(
        'HeatmapLayer',
        data=rent_data_df,
        get_position='[lon, lat]',
        get_weight='rent', # ใช้น้ำหนักตามค่าเช่า
        opacity=0.7,
        radius_pixels=70,
        intensity=1,
        threshold=0.05,
        color_range=[
            # สีเหลือง (ค่าเช่าต่ำ) ไป แดง (ค่าเช่าสูง)
            [255, 255, 204, 20],
            [255, 237, 160, 50],
            [254, 217, 118, 100],
            [254, 178, 76, 150],
            [253, 141, 60, 200],
            [240, 59, 32, 230],
            [189, 0, 38, 255]
        ]
    )

    # 2. Layer สำหรับปักหมุด CBD
    cbd_df = pd.DataFrame([{'name': 'CBD', 'lat': cbd_lat, 'lon': cbd_lon}])
    cbd_layer = pdk.Layer(
        'ScatterplotLayer',
        data=cbd_df,
        get_position='[lon, lat]',
        get_color='[0, 0, 0, 255]', # สีดำ
        get_radius=500, # รัศมี 500 เมตร
        pickable=True,
    )
    
    # 3. Layer สำหรับแสดงข้อความ "CBD"
    text_layer = pdk.Layer(
        "TextLayer",
        data=cbd_df,
        get_position="[lon, lat]",
        get_text="'CBD'",
        get_color="[0, 0, 0, 200]",
        get_size=20,
        get_alignment_baseline="'bottom'",
    )

    # กำหนดมุมมองเริ่มต้นของแผนที่
    view_state = pdk.ViewState(
        latitude=cbd_lat,
        longitude=cbd_lon,
        zoom=9, # ซูมออกมาเล็กน้อยเพื่อให้เห็นภาพรวม
        pitch=45, # มุมมองเอียง
        bearing=0
    )

    # รวม Layer ทั้งหมด
    deck = pdk.Deck(
        layers=[heatmap_layer, cbd_layer, text_layer],
        initial_view_state=view_state,
        map_style='mapbox://styles/mapbox/light-v9', # ใช้แผนที่สไตล์สว่าง
        tooltip={
            "html": """
                <b>ค่าเช่า (โดยประมาณ):</b> {rent} <br/>
                <b>ระยะทางจาก CBD:</b> {distance_km} กม.
            """,
            "style": {
                "backgroundColor": "steelblue",
                "color": "white"
            }
        }
    )

    # แสดงแผนที่
    st.pydeck_chart(deck)

    # --- แสดงข้อมูลเพิ่มเติม ---
    st.subheader(f"สรุปข้อมูล (คำนวณ {len(rent_data_df)} จุด)")
    col1, col2 = st.columns(2)
    with col1:
        st.metric("ค่าเช่าสูงสุด (ที่ CBD)", f"{max_rent:,.0f}")
    with col2:
        st.metric("ค่าเช่าเฉลี่ย (ในรัศมี)", f"{rent_data_df['rent'].mean():,.0f}")

    with st.expander("ดูตารางข้อมูลดิบ (Raw Data)"):
        st.dataframe(rent_data_df.sort_values('rent', ascending=False).style.format({
            'lat': '{:.4f}',
            'lon': '{:.4f}',
            'rent': '{:,.0f}',
            'distance_km': '{:.2f}'
        }))
