import streamlit as st
import folium
from streamlit_folium import st_folium
import time

st.set_page_config(layout="wide")

st.header("🔧 ทดสอบการเชื่อมต่อ Longdo Map")

# ใส่ Key ของคุณตรงนี้
API_KEY = "d319a3926ede7cab2d778899e3d9661a" 
# เพิ่มตัวเลขสุ่มเพื่อป้องกัน Cache
cache_buster = str(time.time())

if not API_KEY:
    st.error("กรุณาใส่ API Key")
else:
    # เริ่มที่เชียงของ (ตำแหน่งเดิม)
    m = folium.Map(location=[20.2604, 100.41], zoom_start=16)

    # 1. ชั้นข้อมูลทดสอบ: แผนที่สีเทา (Check Key)
    folium.TileLayer(
        tiles=f"https://ms.longdo.com/mapproxy/service/render/wmts/gray/GoogleMapsCompatible/{{z}}/{{x}}/{{y}}.png?apikey={API_KEY}&t={cache_buster}",
        attr="Longdo Gray",
        name="1. แผนที่สีเทา (เช็ค Key)",
        overlay=True,
        show=True
    ).add_to(m)

    # 2. ชั้นข้อมูลจริง: แปลงที่ดิน (Check Data)
    folium.TileLayer(
        tiles=f"https://ms.longdo.com/mapproxy/service/render/wmts/dol_parcels/GoogleMapsCompatible/{{z}}/{{x}}/{{y}}.png?apikey={API_KEY}&t={cache_buster}",
        attr="กรมที่ดิน",
        name="2. แปลงที่ดิน (DOL)",
        overlay=True,
        show=True,
        opacity=0.8
    ).add_to(m)

    folium.LayerControl().add_to(m)
    
    st.info("👇 **ลองสลับ Layer ที่มุมขวาบน**")
    st.markdown("""
    * ถ้า **แผนที่สีเทา** ขึ้น = Key ใช้ได้แล้ว ✅
    * ถ้า **แปลงที่ดิน** ไม่ขึ้น (แต่สีเทาขึ้น) = พื้นที่นี้อาจไม่มีข้อมูล หรือต้องซูมเข้าไปอีก
    * ถ้า **ไม่ขึ้นทั้งคู่** = Key ผิด หรือ การตั้งค่า Domain ยังไม่อัปเดต ❌
    """)

    st_folium(m, height=600, use_container_width=True)
