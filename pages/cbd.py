import streamlit as st
import folium
from streamlit_folium import st_folium

# --- 1. การตั้งค่าหน้าเว็บ ---
st.set_page_config(page_title="Longdo Map - DOL Layer", layout="wide")

st.title("🗺️ ระบบดูข้อมูลรูปแปลงที่ดิน (กรมที่ดิน)")
st.caption("ข้อมูลจาก Longdo Map WMS Special Layers")

# --- 2. ตั้งค่า Parameters สำหรับ WMS ---
API_KEY = "0a999afb0da60c5c45d010e9c171ffc8"
BASE_URL = "https://ms.longdo.com/mapproxy/service"

# สร้าง URL เต็มที่รวม Key
wms_full_url = f"{BASE_URL}?key={API_KEY}"

# --- 3. สร้างแผนที่หลัก (Base Map) ---
# กำหนดพิกัดเริ่มต้น (อนุสาวรีย์ชัยฯ) และ Zoom Level
m = folium.Map(location=[13.7649, 100.5383], zoom_start=16)

# --- 4. เพิ่มชั้นข้อมูลพื้นฐาน (Base Layer) ---
folium.WmsTileLayer(
    url=wms_full_url,
    layers='longdo_icons',
    name='Longdo Road Map',
    format='image/png',       # แก้ไข: fmt -> format
    transparent=False,
    attr='© NuMAP, Longdo'    # แก้ไข: attribution -> attr
).add_to(m)

# --- 5. เพิ่มชั้นข้อมูลกรมที่ดิน (DOL Layer) ---
folium.WmsTileLayer(
    url=wms_full_url,
    layers='dol',
    name='Department of Lands (รูปแปลงที่ดิน)',
    format='image/png',       # แก้ไข: fmt -> format
    transparent=True,         # พื้นหลังใสเพื่อให้เห็นถนน
    version='1.1.1',
    attr='Department of Lands / Longdo Map' # แก้ไข: attribution -> attr
).add_to(m)

# เพิ่มปุ่มควบคุมเปิด-ปิด Layer
folium.LayerControl().add_to(m)

# --- 6. แสดงผลใน Streamlit ---
# ใช้ st_folium เพื่อ render แผนที่และรับค่าการโต้ตอบ
st_data = st_folium(m, width="100%", height=600)

# --- 7. ส่วนแสดงข้อมูลเสริม ---
st.info("""
**คำแนะนำการใช้งาน:**
1. **Zoom In:** ข้อมูลเส้นแบ่งแปลงที่ดินจะแสดงชัดเจนเมื่อซูมเข้าไปใกล้ๆ พื้นที่ (Zoom Level 15-18)
2. **Layer Control:** กดที่ไอคอน Layer มุมขวาบนของแผนที่ เพื่อเปิด/ปิด ชั้นข้อมูลกรมที่ดินได้
""")

# (Optional) แสดงค่าพิกัดที่คลิก
if st_data and st_data.get('last_clicked'):
    lat = st_data['last_clicked']['lat']
    lng = st_data['last_clicked']['lng']
    st.success(f"📍 พิกัดที่คลิก: {lat}, {lng}")
