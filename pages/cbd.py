import streamlit as st
import streamlit.components.v1 as components

# ตั้งค่าหน้าเว็บ
st.set_page_config(page_title="Longdo Map - กรมที่ดิน", layout="wide")

st.title("🗺️ Longdo Map: ชั้นข้อมูลกรมที่ดิน")
st.caption("ตัวอย่างการแสดงเส้นแบ่งโฉนดที่ดิน (Cadastral Map)")

# --- 1. การตั้งค่าและ Input (Sidebar) ---
with st.sidebar:
    st.header("📍 ตั้งค่าแผนที่")
    
    # API Key
    api_key = st.text_input("Longdo API Key", value="0a999afb0da60c5c45d010e9c171ffc8")
    
    st.subheader("พิกัดและการซูม")
    # พิกัดตัวอย่าง (สยามพารากอน)
    lat = st.number_input("Latitude", value=13.7469, format="%.6f")
    lon = st.number_input("Longitude", value=100.5349, format="%.6f")
    
    # *สำคัญ* กรมที่ดินต้องซูมลึกๆ ถึงจะเห็นเส้น
    zoom = st.slider("Zoom Level (แนะนำ 16+ เพื่อดูโฉนด)", 1, 20, 17) 

    st.markdown("---")
    st.subheader("🛠️ ตัวเลือก Layer")
    
    # Checkbox สำหรับเปิด/ปิด Layer กรมที่ดิน
    show_dol_layer = st.checkbox("แสดงชั้นข้อมูลกรมที่ดิน (DOL)", value=True)
    show_traffic = st.checkbox("แสดงจราจร (Traffic)", value=False)

# --- 2. Logic การสร้าง JavaScript ---

# แปลงค่า Python boolean เป็น JavaScript boolean string ('true'/'false')
js_dol_layer = "true" if show_dol_layer else "false"
js_traffic = "true" if show_traffic else "false"

# HTML/JS Code
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
            // 1. สร้างแผนที่
            map = new longdo.Map({{
                placeholder: document.getElementById('map')
            }});
            
            // 2. กำหนดพิกัดและซูม
            map.location({{ lon: {lon}, lat: {lat} }}, true);
            map.zoom({zoom});

            // 3. จัดการ Layer กรมที่ดิน (DOL)
            if ({js_dol_layer}) {{
                // เพิ่ม Layer กรมที่ดิน
                map.Layers.add(longdo.Layers.DOL);
                
                // (Optional) เปลี่ยนพื้นหลังเป็นสีเทาเพื่อให้เห็นเส้นชัดขึ้น
                // map.Layers.setBase(longdo.Layers.GRAY); 
            }}

            // 4. จัดการ Layer จราจร
            if ({js_traffic}) {{
                map.Layers.add(longdo.Layers.TRAFFIC);
            }}

            // 5. เพิ่มหมุด (Marker)
            var marker = new longdo.Marker({{ lon: {lon}, lat: {lat} }}, {{
                title: 'จุดที่เลือก',
                detail: 'Lat: {lat} <br> Lon: {lon}'
            }});
            map.Overlays.add(marker);
        }}
    </script>
</head>
<body onload="init();">
    <div id="map"></div>
</body>
</html>
"""

# --- 3. แสดงผล ---
components.html(longdo_map_html, height=600)

# ส่วนแสดงข้อมูลสรุป
col1, col2 = st.columns(2)
with col1:
    st.info(f"📍 **พิกัด:** `{lat}, {lon}`")
with col2:
    status_text = "✅ เปิดใช้งาน" if show_dol_layer else "❌ ปิดใช้งาน"
    st.info(f"📜 **สถานะ Layer กรมที่ดิน:** {status_text}")

if show_dol_layer and zoom < 15:
    st.warning("⚠️ **คำแนะนำ:** หากมองไม่เห็นเส้นแบ่งโฉนด กรุณาเพิ่มค่า **Zoom Level** ให้มากกว่า 15")
