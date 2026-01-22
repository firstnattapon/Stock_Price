import streamlit as st
import streamlit.components.v1 as components 

# ตั้งค่าหน้าเว็บ
st.set_page_config(page_title="Longdo Map Streamlit", layout="wide")

st.title("🗺️ Longdo Map with Streamlit")
st.caption("ตัวอย่างการเชื่อมต่อ Longdo Map API เข้ากับ Streamlit พร้อมชั้นข้อมูลกรมที่ดิน")

# 1. การตั้งค่าและ Input จากผู้ใช้ (Sidebar)
with st.sidebar:
    st.header("📍 ตั้งค่าพิกัด")
    
    # API Key
    api_key = st.text_input("Longdo API Key", value="0a999afb0da60c5c45d010e9c171ffc8")
    
    # กำหนดพิกัดเริ่มต้น
    lat = st.number_input("Latitude (ละติจูด)", value=13.7469, format="%.6f")
    lon = st.number_input("Longitude (ลองจิจูด)", value=100.5349, format="%.6f")
    zoom = st.slider("Zoom Level", 1, 20, 16)
    
    st.markdown("---")
    st.header("🗂️ ชั้นข้อมูล (Layers)")
    
    # เลือกชั้นข้อมูลที่ต้องการแสดง
    show_traffic = st.checkbox("แสดงข้อมูลจราจร", value=False)
    show_dol = st.checkbox("แสดงชั้นข้อมูลกรมที่ดิน (DOL)", value=True)
    
    st.info("💡 ซูมเข้าไปที่ระดับ 16-20 เพื่อดูรายละเอียดกรมที่ดิน")

# 2. ส่วนแสดงผลแผนที่
longdo_map_html = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <style>
        body {{ margin: 0; padding: 0; }}
        #map {{ height: 600px; width: 100%; }}
    </style>
    <script src="https://api.longdo.com/map/?key={api_key}"></script>
</head>
<body>
    <div id="map"></div>
    
    <script>
        var map;
        
        function init() {{
            try {{
                // สร้างแผนที่
                map = new longdo.Map({{
                    placeholder: document.getElementById('map'),
                    language: 'th'
                }});
                
                // กำหนดจุดกึ่งกลางและการซูม
                map.location({{ lon: {lon}, lat: {lat} }}, true);
                map.zoom({zoom}, true);

                // เพิ่มหมุด (Marker)
                var marker = new longdo.Marker({{ lon: {lon}, lat: {lat} }}, {{
                    title: 'ตำแหน่งที่เลือก',
                    detail: 'Lat: {lat}<br>Lon: {lon}'
                }});
                map.Overlays.add(marker);
                
                // เพิ่มเลเยอร์จราจร
                {f"map.Layers.add(longdo.Layers.TRAFFIC);" if show_traffic else "// Traffic layer disabled"}
                
                // เพิ่มชั้นข้อมูลกรมที่ดิน (DOL)
                {f"map.Layers.add(longdo.Layers.DOL);" if show_dol else "// DOL layer disabled"}
                
                console.log('Map initialized successfully');
                console.log('Available layers:', longdo.Layers);
                
            }} catch(e) {{
                console.error('Error initializing map:', e);
            }}
        }}
        
        // รอให้ DOM โหลดเสร็จก่อน
        if (document.readyState === 'loading') {{
            document.addEventListener('DOMContentLoaded', init);
        }} else {{
            init();
        }}
    </script>
</body>
</html>
"""

# 3. แสดงผลด้วย components.html
components.html(longdo_map_html, height=620)

# แสดงข้อมูลใต้แผนที่
col1, col2, col3 = st.columns(3)

with col1:
    st.metric("Latitude", f"{lat:.6f}")
with col2:
    st.metric("Longitude", f"{lon:.6f}")
with col3:
    st.metric("Zoom Level", zoom)

st.markdown("---")

# ข้อมูลเกี่ยวกับ Layers
with st.expander("ℹ️ ข้อมูลเกี่ยวกับชั้นข้อมูลกรมที่ดิน"):
    st.markdown("""
    ### ชั้นข้อมูลกรมที่ดิน (Department of Lands - DOL)
    
    **ข้อมูลที่แสดง:**
    - 🏘️ ขอบเขตแปลงที่ดิน
    - 📋 เลขที่โฉนด
    - 📍 หมายเลขแปลง
    - 🗺️ ข้อมูลทางราชการ
    
    **วิธีใช้งาน:**
    1. ซูมเข้าไปที่ระดับ **16 ขึ้นไป** เพื่อเห็นรายละเอียด
    2. คลิกที่แปลงที่ดินเพื่อดูข้อมูลเพิ่มเติม
    3. ข้อมูลจะแสดงชัดเจนที่ zoom level 18-20
    
    **หมายเหตุ:**
    - ข้อมูลอาจไม่ครอบคลุมทุกพื้นที่
    - ต้องมี API Key ที่มีสิทธิ์เข้าถึงข้อมูล DOL
    - ข้อมูลอ้างอิงจากกรมที่ดิน กระทรวงมหาดไทย
    """)

# ตารางแสดง Layers ที่เปิดใช้งาน
st.subheader("📊 สถานะ Layers")
layer_status = {
    "Layer": ["จราจร (Traffic)", "กรมที่ดิน (DOL)"],
    "สถานะ": ["🟢 เปิด" if show_traffic else "🔴 ปิด", 
               "🟢 เปิด" if show_dol else "🔴 ปิด"]
}
st.table(layer_status)

st.success("✅ โหลดแผนที่เรียบร้อยจาก Longdo API")

# คำเตือน
if show_dol and zoom < 16:
    st.warning("⚠️ ชั้นข้อมูลกรมที่ดินจะแสดงชัดเจนเมื่อซูมเข้าไปที่ระดับ 16 ขึ้นไป")
