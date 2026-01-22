import streamlit as st
import streamlit.components.v1 as components

st.set_page_config(page_title="Longdo Map - Check DOL", layout="wide")

st.title("🗺️ ตรวจสอบชั้นข้อมูลกรมที่ดิน")

# --- Sidebar ---
with st.sidebar:
    st.header("⚙️ ตั้งค่า")
    # ใช้ Key เดิม (หรือ Key ของคุณเอง)
    api_key = st.text_input("API Key", value="0a999afb0da60c5c45d010e9c171ffc8")
    
    # พิกัด (ตัวอย่าง: พื้นที่ที่มีโฉนดชัดเจน แถวลาดยาว)
    lat = st.number_input("Lat", value=13.8479, format="%.6f")
    lon = st.number_input("Lon", value=100.5630, format="%.6f")
    
    # *** สำคัญ: ตั้งค่า Zoom เริ่มต้นให้สูงเข้าไว้ ***
    zoom = st.slider("Zoom Level (ต้อง 15+ ถึงจะเห็น)", 1, 20, 17)
    
    st.markdown("---")
    show_dol = st.checkbox("✅ แสดงเส้นกรมที่ดิน (DOL)", value=True)
    gray_base = st.checkbox("🌑 ใช้พื้นหลังสีเทา (ช่วยให้เห็นเส้นชัด)", value=True)

# --- Logic JS ---
# แปลงค่า Python -> JS
val_dol = "true" if show_dol else "false"
val_gray = "longdo.Layers.GRAY" if gray_base else "longdo.Layers.NORMAL"

html_code = f"""
<!DOCTYPE html>
<html>
<head>
    <style>
        body {{ margin: 0; }}
        #map {{ height: 600px; width: 100%; }}
    </style>
    <script src="https://api.longdo.com/map/?key={api_key}"></script>
    <script>
        var map;
        function init() {{
            map = new longdo.Map({{
                placeholder: document.getElementById('map'),
                layer: {val_gray} // ตั้งค่าพื้นหลังตั้งแต่เริ่ม
            }});
            
            // ไปยังพิกัดและซูม
            map.location({{ lon: {lon}, lat: {lat} }}, true);
            map.zoom({zoom});

            // เพิ่ม Layer กรมที่ดิน
            if ({val_dol}) {{
                try {{
                    // วิธีเรียก Layer กรมที่ดินแบบมาตรฐาน
                    var dolLayer = longdo.Layers.DOL;
                    map.Layers.add(dolLayer);
                    
                    console.log("Added DOL Layer");
                }} catch (e) {{
                    console.error("Error adding DOL:", e);
                }}
            }}
            
            // เพิ่มหมุดเพื่อบอกตำแหน่ง
            map.Overlays.add(new longdo.Marker({{ lon: {lon}, lat: {lat} }}));
        }}
    </script>
</head>
<body onload="init();">
    <div id="map"></div>
</body>
</html>
"""

components.html(html_code, height=600)

# --- คำแนะนำการแก้ปัญหา ---
st.info(f"Current Zoom: {zoom}")
if show_dol and zoom < 15:
    st.error("⚠️ **คำเตือน:** Zoom Level ต่ำกว่า 15 เส้นโฉนดจะไม่แสดงผล กรุณาเลื่อน Zoom ไปทางขวา")
else:
    st.success("✅ ระดับ Zoom เหมาะสมสำหรับการดูโฉนด")

st.markdown("""
### 📌 ถ้ายังไม่ขึ้น ให้เช็คตามนี้:
1. **พื้นที่นั้นไม่มีข้อมูล:** ลองเลื่อนแผนที่ไปในเขตเมือง (เช่น กรุงเทพฯ)
2. **Server กรมที่ดินล่ม:** ลองเข้าเว็บ [LandsMaps](https://landsmaps.dol.go.th/) โดยตรง ถ้าเว็บนั้นหมุนติ้วๆ หรือไม่โหลด แสดงว่าระบบกรมที่ดินล่ม (Longdo ดึงข้อมูลสดจากที่นั่น)
3. **Browser Block:** บางครั้ง Browser บล็อกเนื้อหา (Mixed Content) แต่กรณีนี้พบน้อยกับ Longdo รุ่นใหม่
""")
