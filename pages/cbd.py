import streamlit as st
import streamlit.components.v1 as components

# ตั้งค่าหน้าเว็บ
st.set_page_config(page_title="Longdo Map Streamlit", layout="wide")

st.title("🗺️ Longdo Map with Streamlit")
st.caption("ตัวอย่างการเชื่อมต่อ Longdo Map API เข้ากับ Streamlit")

# 1. การตั้งค่าและ Input จากผู้ใช้ (Sidebar)
with st.sidebar:
    st.header("📍 ตั้งค่าพิกัด")
    
    # API Key (ใช้ Key ที่คุณให้มาเป็นค่า Default)
    api_key = st.text_input("Longdo API Key", value="0a999afb0da60c5c45d010e9c171ffc8")
    
    # กำหนดพิกัดเริ่มต้น (ตัวอย่างคือ สยามพารากอน)
    lat = st.number_input("Latitude (ละติจูด)", value=13.7469, format="%.6f")
    lon = st.number_input("Longitude (ลองจิจูด)", value=100.5349, format="%.6f")
    zoom = st.slider("Zoom Level", 1, 20, 15)

    st.info("ลองเปลี่ยนค่าพิกัด แผนที่จะขยับตามอัตโนมัติ")

# 2. ส่วนแสดงผลแผนที่ (HTML & JavaScript)
# เราต้องสร้าง HTML string ที่ฝัง JavaScript ของ Longdo ลงไป
longdo_map_html = f"""
<!DOCTYPE html>
<html>
<head>
    <style>
        body {{ margin: 0; padding: 0; }}
        #map {{ height: 600px; width: 100%; }}
    </style>
    <script src="https://api.longdo.com/map/?key={api_key}"></script>
    <script>
        var map;
        function init() {{
            // สร้างแผนที่
            map = new longdo.Map({{
                placeholder: document.getElementById('map')
            }});
            
            // กำหนดจุดกึ่งกลางและการซูมตามค่าที่รับมาจาก Python
            map.location({{ lon: {lon}, lat: {lat} }}, true);
            map.zoom({zoom});

            // เพิ่มหมุด (Marker) ตรงจุดกึ่งกลาง
            var marker = new longdo.Marker({{ lon: {lon}, lat: {lat} }}, {{
                title: 'ตำแหน่งที่เลือก',
                detail: 'Lat: {lat}, Lon: {lon}'
            }});
            map.Overlays.add(marker);
            
            // เพิ่มเลเยอร์จราจร (Optional)
            map.Layers.add(longdo.Layers.TRAFFIC);
        }}
    </script>
</head>
<body onload="init();">
    <div id="map"></div>
</body>
</html>
"""

# 3. แสดงผลด้วย components.html
# height ต้องสัมพันธ์กับ css height ด้านบน
components.html(longdo_map_html, height=600)

# แสดงข้อมูลใต้แผนที่
st.markdown(f"**พิกัดปัจจุบัน:** `{lat}, {lon}`")
st.markdown("---")
st.success("โหลดแผนที่เรียบร้อยจาก Longdo API")
