import streamlit as st
import streamlit.components.v1 as components
from urllib.parse import quote

st.set_page_config(page_title="Longdo + MapProxy WMS (กรมที่ดิน)", layout="wide")
st.title("Longdo Map API v3 + Longdo MapProxy WMS (Department of Land WMS)")

st.markdown(
    """
ตัวอย่าง Streamlit สำหรับแสดง **Longdo Map API v3** และซ้อนชั้นข้อมูลจาก **WMS (Longdo MapProxy)**

- **WMS Endpoint (MapProxy):** `https://ms.longdo.com/mapproxy/service`
- หมายเหตุจากภาพ: ควรซูมให้ **Scale ใหญ่กว่า 1:10000** เพื่อให้แสดงรายละเอียดได้ (โดยทั่วไปลองเริ่มที่ **Zoom ≥ 14**)
    """
)

# -----------------------
# Sidebar controls
# -----------------------
with st.sidebar:
    st.header("ตั้งค่า")

    # แนะนำให้ใส่ key ผ่าน .streamlit/secrets.toml:
    # LONGDO_MAP_KEY = "xxx"
    longdo_key = st.text_input(
        "Longdo Map API Key",
        value=st.secrets.get("LONGDO_MAP_KEY", ""),
        type="password",
        help="แนะนำให้เก็บใน Streamlit secrets เช่น .streamlit/secrets.toml"
    )

    st.subheader("ตำแหน่ง/การซูม")
    lat = st.number_input("Latitude", value=13.7563, format="%.6f")
    lon = st.number_input("Longitude", value=100.5018, format="%.6f")
    zoom = st.slider("Zoom", 1, 20, 15)
    height = st.slider("ความสูงแผนที่ (px)", 350, 950, 720)

    st.subheader("WMS (Longdo MapProxy)")
    wms_url = st.text_input(
        "WMS Endpoint",
        value="https://ms.longdo.com/mapproxy/service",
        help="ค่าจากภาพ: https://ms.longdo.com/mapproxy/service"
    )

    # บางระบบต้องใช้ชื่อ layer เฉพาะ (ดูจาก GetCapabilities)
    layer_name = st.text_input(
        "Layer name (ต้องตรงกับ GetCapabilities)",
        value="",
        help="ถ้าไม่ทราบ ให้เปิด GetCapabilities แล้วค้นหา <Name> ของ layer"
    )

    # บางบริการ MapProxy ต้องระบุ map=... หรือ service=... เพิ่มเติม
    extra_query_user = st.text_input(
        "Extra query (ใส่เพิ่มเองถ้าจำเป็น)",
        value="",
        help="ตัวอย่าง: map=/path/to/mapfile.map (แล้วแต่บริการรองรับ)"
    )

    opacity = st.slider("Opacity", 0.0, 1.0, 0.7, 0.05)

    # Longdo base map มักอยู่บน Web Mercator
    srs = st.selectbox("SRS/CRS", ["EPSG:3857", "EPSG:4326"], index=0)

    img_format = st.selectbox("Image format", ["image/png", "image/jpeg"], index=0)
    transparent = st.checkbox("Transparent (แนะนำเมื่อ PNG)", value=True)
    styles = st.text_input("styles (ปล่อยว่างได้)", value="")

    st.divider()
    st.subheader("ลิงก์ทดสอบ (เปิดในเบราว์เซอร์)")
    getcap = f"{wms_url}{'&' if '?' in wms_url else '?'}SERVICE=WMS&REQUEST=GetCapabilities"
    st.write("GetCapabilities:")
    st.code(getcap, language="text")

    st.caption("ถ้าเลเยอร์ไม่ขึ้น ให้เปิด GetCapabilities แล้วตรวจชื่อ layer และ CRS ที่รองรับ")

if not longdo_key.strip():
    st.warning("กรุณาใส่ Longdo Map API Key ก่อน")
    st.stop()

# -----------------------
# Zoom hint (อิงจากคำแนะนำ scale > 1:10000)
# -----------------------
if zoom < 14:
    st.info("คำแนะนำ: ลองปรับ Zoom เป็น 14 ขึ้นไป (เพื่อให้เข้าใกล้เงื่อนไข Scale > 1:10000)")

# -----------------------
# Build WMS extra query for Longdo Layer (KVP)
# -----------------------
extra_parts = []

# layers=... (ใส่เมื่อผู้ใช้กรอก)
if layer_name.strip():
    extra_parts.append(f"layers={quote(layer_name.strip())}")

# styles=...
if styles.strip():
    extra_parts.append(f"styles={quote(styles.strip())}")

# transparent=...
if transparent and img_format == "image/png":
    extra_parts.append("transparent=true")

# extra query from user (ต่อท้ายแบบดิบ แต่กันช่องว่างหัวท้าย)
if extra_query_user.strip():
    # ผู้ใช้อาจใส่รูปแบบ "a=b&c=d"
    extra_parts.append(extra_query_user.strip().lstrip("&").lstrip("?"))

extra_query = "&".join([p for p in extra_parts if p])

# -----------------------
# Render HTML (Longdo Map v3 + WMS layer)
# -----------------------
html = f"""
<!doctype html>
<html>
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <script src="https://api.longdo.com/map3/?key={longdo_key}"></script>
    <style>
      html, body {{ height: 100%; margin: 0; }}
      #map {{ width: 100%; height: {height}px; }}
      .note {{
        font-family: sans-serif;
        font-size: 12px;
        color: #444;
        margin: 8px 0 0 0;
        line-height: 1.4;
        word-break: break-word;
      }}
      .mono {{
        font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
      }}
    </style>
  </head>
  <body>
    <div id="map"></div>
    <div class="note">
      <div><b>WMS:</b> <span class="mono">{wms_url}</span></div>
      <div><b>Layer:</b> <span class="mono">{layer_name if layer_name.strip() else "(not set)"}</span></div>
      <div><b>SRS:</b> <span class="mono">{srs}</span> | <b>Format:</b> <span class="mono">{img_format}</span> | <b>Opacity:</b> {opacity}</div>
      <div><b>extraQuery:</b> <span class="mono">{extra_query if extra_query else "(none)"}</span></div>
    </div>

    <script>
      var map = new longdo.Map({{
        placeholder: document.getElementById('map'),
        location: {{ lat: {lat}, lon: {lon} }},
        zoom: {zoom}
      }});

      map.Overlays.add(new longdo.Marker({{ lat: {lat}, lon: {lon} }}, {{ title: 'Center' }}));

      try {{
        var wmsLayer = new longdo.Layer('Department of Land WMS (MapProxy)', {{
          type: longdo.LayerType.WMS,
          url: '{wms_url}',
          format: '{img_format}',
          srs: '{srs}',
          opacity: {opacity},
          weight: 10,
          extraQuery: '{extra_query}'
        }});

        map.Layers.add(wmsLayer);
      }} catch (e) {{
        console.error("Failed to add WMS layer:", e);
      }}
    </script>
  </body>
</html>
"""

components.html(html, height=height + 90, scrolling=False)

st.subheader("ถ้าเลเยอร์ไม่ขึ้น (เช็คตามลำดับ)")
st.markdown(
    """
1) เปิด **GetCapabilities** แล้วดูว่า **ชื่อ layer** ที่จะใช้คืออะไร (ค่าจาก `<Name>...</Name>`)  
2) ตรวจว่า layer รองรับ **CRS/SRS** ที่เลือก (แนะนำ **EPSG:3857**)  
3) ลองปรับ **Zoom ≥ 14** (สอดคล้องกับคำแนะนำ Scale > 1:10000)  
4) ถ้าใน GetCapabilities ต้องใส่พารามิเตอร์เพิ่ม (เช่น `map=...`) ให้ใส่ในช่อง **Extra query**  
5) ถ้าเครือข่าย/เซิร์ฟเวอร์บล็อก CORS อาจต้องใช้ proxy (อาการ: ใน DevTools มี error CORS/blocked)
    """
)

st.subheader("การตั้งค่า secrets (แนะนำ)")
st.markdown(
    """
สร้างไฟล์ `.streamlit/secrets.toml`:
