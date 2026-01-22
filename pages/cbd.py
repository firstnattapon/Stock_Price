import streamlit as st
import streamlit.components.v1 as components
from urllib.parse import quote

st.set_page_config(page_title="Longdo + WMSDOL (MV_SPARCEL)", layout="wide")
st.title("Longdo Map API v3 + WMS แปลงที่ดิน (MV_SPARCEL)")

st.markdown(
    """
ใช้ Longdo Map API v3 เพื่อแสดงแผนที่ และซ้อนชั้นข้อมูลจาก WMS (GeoServer)

**WMS URL:** `http://110.164.49.68:8081/geoserver/WMSDOL/wms?`  
**Layer:** `MV_SPARCEL`
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
        help="แนะนำให้เก็บใน Streamlit secrets"
    )

    st.subheader("แผนที่")
    lat = st.number_input("Latitude", value=13.7563, format="%.6f")
    lon = st.number_input("Longitude", value=100.5018, format="%.6f")
    zoom = st.slider("Zoom", 1, 20, 12)
    height = st.slider("ความสูงแผนที่ (px)", 350, 950, 700)

    st.subheader("WMS")
    wms_url = st.text_input(
        "WMS Endpoint",
        value="http://110.164.49.68:8081/geoserver/WMSDOL/wms?",
    )
    layer_name = st.text_input("Layer name", value="MV_SPARCEL")
    opacity = st.slider("Opacity", 0.0, 1.0, 0.7, 0.05)

    # สำคัญ: Longdo base map มักเป็น EPSG:3857
    # ถ้า WMS ไม่รองรับ 3857 ให้ลอง 24047 แต่มีโอกาสซ้อนตำแหน่งไม่ตรง
    srs = st.selectbox("SRS/CRS ที่ร้องขอจาก WMS", ["EPSG:3857", "EPSG:24047", "EPSG:4326"], index=0)

    img_format = st.selectbox("Image format", ["image/png", "image/jpeg"], index=0)
    transparent = st.checkbox("Transparent (แนะนำเมื่อ PNG)", value=True)
    styles = st.text_input("styles (ปล่อยว่างได้)", value="")

    st.divider()
    st.subheader("ทดสอบ WMS")
    getcap = f"{wms_url}{'&' if '?' in wms_url else '?'}service=WMS&request=GetCapabilities"
    st.write("GetCapabilities:")
    st.code(getcap, language="text")

    # WMS version (GeoServer ส่วนมากรองรับทั้ง 1.1.1 และ 1.3.0)
    wms_version = st.selectbox("WMS Version", ["1.3.0", "1.1.1"], index=0)

if not longdo_key.strip():
    st.warning("กรุณาใส่ Longdo Map API Key ก่อน")
    st.stop()

# -----------------------
# Build WMS extra query
# -----------------------
# ใน Longdo LayerOptions มี extraQuery เพื่อแนบ query string เพิ่มเติม
# สำหรับ WMS ต้องมี layers=... และมักใช้ transparent=true เมื่อ PNG
extra_parts = [f"layers={quote(layer_name)}"]

if transparent:
    extra_parts.append("transparent=true")

if styles.strip():
    extra_parts.append(f"styles={quote(styles.strip())}")

extra_query = "&".join(extra_parts)

# -----------------------
# Render HTML (Longdo Map v3 + WMS layer)
# -----------------------
# อ้างอิง: LayerOptions รองรับ WMS/WMTS(KVP) options: format, srs, styles, extraQuery ฯลฯ
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
        margin: 6px 0 0 0;
      }}
    </style>
  </head>
  <body>
    <div id="map"></div>
    <div class="note">
      WMS: {wms_url} | Layer: {layer_name} | SRS: {srs} | format: {img_format}
    </div>

    <script>
      // Init map
      var map = new longdo.Map({{
        placeholder: document.getElementById('map'),
        location: {{ lat: {lat}, lon: {lon} }},
        zoom: {zoom}
      }});

      // Optional marker at center
      map.Overlays.add(new longdo.Marker({{ lat: {lat}, lon: {lon} }}, {{
        title: 'Center'
      }}));

      // WMS Layer
      try {{
        var parcelWms = new longdo.Layer('MV_SPARCEL (WMS)', {{
          type: longdo.LayerType.WMS,
          url: '{wms_url}',
          format: '{img_format}',
          srs: '{srs}',
          opacity: {opacity},
          // weight ต่ำจะแสดง "ทับ" เลเยอร์ที่ weight สูงกว่า (ตามเอกสาร)
          weight: 10,
          extraQuery: '{extra_query}'
        }});

        map.Layers.add(parcelWms);
      }} catch (e) {{
        console.error(e);
      }}
    </script>
  </body>
</html>
"""

components.html(html, height=height + 40, scrolling=False)

st.subheader("หมายเหตุ / ถ้าเลเยอร์ไม่ขึ้น")
st.markdown(
    """
ตรวจเช็คตามลำดับ:

1. เปิด `GetCapabilities` แล้วดูว่า layer `MV_SPARCEL` มีจริง และรองรับ SRS ที่เลือกหรือไม่  
2. แนะนำเริ่มจาก `SRS = EPSG:3857` (ถ้า WMS รองรับ จะซ้อนกับแผนที่ฐานได้ตรงสุด)  
3. ถ้า WMS รองรับแค่ `EPSG:24047` อาจซ้อน “ไม่ตรงตำแหน่ง” เพราะแผนที่ฐานมักเป็น Web Mercator  
   - วิธีแก้: ทำตัวกลางให้บริการเป็น tiles/WMTS ใน EPSG:3857 แล้วค่อยเอามาซ้อน
4. บางเครือข่าย/เซิร์ฟเวอร์อาจบล็อก CORS ทำให้เรียก tile ไม่ได้ (ต้องใช้ proxy)
    """
)
"""
Usage
-----
pip install streamlit

Run:
  streamlit run app.py

Streamlit secrets:
  .streamlit/secrets.toml
    LONGDO_MAP_KEY="YOUR_KEY"
"""
