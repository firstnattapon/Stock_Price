import streamlit as st
import folium
from streamlit_folium import st_folium

# =========================================================
# ตั้งค่า Key ของคุณ (ตรวจสอบแล้วว่าเป็น Key นี้)
# =========================================================
API_KEY = "d319a3926ede7cab2d778899e3d9661a"

st.set_page_config(layout="wide")
st.title("🛠️ ทดสอบหาช่องทางที่ถูกต้อง (Longdo Map)")

# พิกัดเชียงของ
center_lat, center_lon = 20.2604, 100.4100

m = folium.Map(location=[center_lat, center_lon], zoom_start=15)

# ---------------------------------------------------------
# วิธีที่ 1: แบบ WMTS (มาตรฐานปกติ)
# ---------------------------------------------------------
wmts_url = f"https://ms.longdo.com/mapproxy/service/render/wmts/dol_parcels/GoogleMapsCompatible/{{z}}/{{x}}/{{y}}.png?apikey={API_KEY}"
folium.TileLayer(
    tiles=wmts_url,
    attr="Longdo Map (WMTS)",
    name="1. แบบ WMTS (โหลดเร็ว)",
    overlay=True,
    show=True # ลองเปิดอันนี้เป็นค่าเริ่มต้น
).add_to(m)

# ---------------------------------------------------------
# วิธีที่ 2: แบบ WMS (แบบดั้งเดิม - บังคับส่ง Parameter ครบ)
# ---------------------------------------------------------
# เราจะส่ง Parameter แบบเจาะจงสุดๆ เพื่อไม่ให้ Server งง
wms_url = f"https://ms.longdo.com/mapproxy/service/wms?apikey={API_KEY}"
folium.raster_layers.WmsTileLayer(
    url=wms_url,
    layers="dol_parcels",
    fmt="image/png",
    transparent=True,
    version="1.1.1",
    attr="Longdo Map (WMS)",
    name="2. แบบ WMS (มาตรฐานกรมที่ดิน)",
    overlay=True,
    show=False
).add_to(m)

# ---------------------------------------------------------
# วิธีที่ 3: เช็คสิทธิ์ด้วย Traffic (ถ้าอันนี้ขึ้น แสดงว่า Key ปกติ 100%)
# ---------------------------------------------------------
traffic_url = f"https://ms.longdo.com/mapproxy/service/render/wmts/layert/GoogleMapsCompatible/{{z}}/{{x}}/{{y}}.png?apikey={API_KEY}"
folium.TileLayer(
    tiles=traffic_url,
    attr="Longdo Traffic",
    name="3. ทดสอบ: เส้นจราจร (Traffic)",
    overlay=True,
    show=False
).add_to(m)

# เพิ่มปุ่มควบคุม Layer
folium.LayerControl(collapsed=False).add_to(m)

# แสดงผล
st.info("👇 **กรุณากดเลือก Layer ที่มุมขวาบนของแผนที่ทีละอัน**")
st_folium(m, height=600, use_container_width=True)
