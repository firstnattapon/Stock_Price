import streamlit as st
import streamlit.components.v1 as components
from urllib.parse import quote

st.set_page_config(page_title="Longdo + MapProxy WMS (Red WMS)", layout="wide")
st.title("Longdo Map API v3 + Longdo MapProxy WMS (ทำสีแดงเฉพาะ WMS)")

st.markdown(
    """
แอปนี้แสดง **Longdo Map API v3** และซ้อน **WMS (Longdo MapProxy)** โดยพยายามทำให้ *เฉพาะเลเยอร์ WMS* เป็นสีแดงได้ 2 วิธี:

1) ใช้ `styles=` (ถ้า WMS มี style สีแดงให้เลือกใน GetCapabilities)  
2) ใช้ `SLD_BODY=` (ถ้า WMS/MapProxy อนุญาตให้ส่ง SLD ผ่าน)

- **WMS Endpoint (MapProxy):** `https://ms.longdo.com/mapproxy/service`
    """
)

# -----------------------
# Sidebar controls
# -----------------------
with st.sidebar:
    st.header("ตั้งค่า")

    longdo_key = st.text_input(
        "Longdo Map API Key",
        value=st.secrets.get("LONGDO_MAP_KEY", ""),
        type="password",
        help="แนะนำให้เก็บใน .streamlit/secrets.toml"
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
    )

    # สำคัญ: ต้องเป็นชื่อ <Name> จาก GetCapabilities เท่านั้น
    layer_name = st.text_input(
        "Layer name (<Name> จาก GetCapabilities)",
        value="",
        help="เปิด GetCapabilities แล้วหา <Layer><Name>...</Name>"
    )

    opacity = st.slider("Opacity", 0.0, 1.0, 0.75, 0.05)
    srs = st.selectbox("SRS/CRS", ["EPSG:3857", "EPSG:4326"], index=0)
    img_format = st.selectbox("Image format", ["image/png", "image/jpeg"], index=0)
    transparent = st.checkbox("Transparent (แนะนำเมื่อ PNG)", value=True)

    st.divider()
    st.subheader("ตั้งค่าสีแดงเฉพาะ WMS")

    red_mode = st.radio(
        "โหมดทำสีแดง",
        ["ใช้ styles= (ต้องมีอยู่แล้ว)", "ใช้ SLD_BODY= (ถ้าเซิร์ฟเวอร์รองรับ)"],
        index=0
    )

    # โหมด 1: styles=
    styles = ""
    if red_mode.startswith("ใช้ styles"):
        styles = st.text_input(
            "WMS styles",
            value="",
            help="ใส่ชื่อ style ที่มีอยู่แล้ว เช่น red / parcel_red (ดูจาก GetCapabilities)"
        )
        st.caption("ถ้าไม่รู้ชื่อ style: เปิด GetCapabilities แล้วดูใน <Style><Name>...</Name></Style> ของ layer")

    # โหมด 2: SLD_BODY=
    sld_body = ""
    if red_mode.startswith("ใช้ SLD_BODY"):
        st.caption("ถ้า WMS/MapProxy ไม่ยอมรับ SLD_BODY เลเยอร์จะไม่เปลี่ยนสี (บางระบบบล็อก)")
        default_sld = """<?xml version="1.0" encoding="UTF-8"?>
<sld:StyledLayerDescriptor version="1.0.0"
  xmlns:sld="http://www.opengis.net/sld"
  xmlns:ogc="http://www.opengis.net/ogc"
  xmlns="http://www.opengis.net/sld">
  <sld:NamedLayer>
    <sld:Name>YOUR_LAYER_NAME</sld:Name>
    <sld:UserStyle>
      <sld:Title>Red parcels</sld:Title>
      <sld:FeatureTypeStyle>
        <sld:Rule>
          <sld:PolygonSymbolizer>
            <sld:Fill>
              <sld:CssParameter name="fill">#FF0000</sld:CssParameter>
              <sld:CssParameter name="fill-opacity">0.0</sld:CssParameter>
            </sld:Fill>
            <sld:Stroke>
              <sld:CssParameter name="stroke">#FF0000</sld:CssParameter>
              <sld:CssParameter name="stroke-width">2</sld:CssParameter>
              <sld:CssParameter name="stroke-opacity">0.9</sld:CssParameter>
            </sld:Stroke>
          </sld:PolygonSymbolizer>
        </sld:Rule>
      </sld:FeatureTypeStyle>
    </sld:UserStyle>
  </sld:NamedLayer>
</sld:StyledLayerDescriptor>
"""
        sld_body = st.text_area(
            "SLD XML (จะถูก URL-encode ให้อัตโนมัติ)",
            value=default_sld,
            height=260,
            help="แก้ YOUR_LAYER_NAME ให้ตรงกับ layer ที่ใช้จริง"
        )

    st.divider()
    st.subheader("ทดสอบ WMS")
    getcap = f"{wms_url}{'&' if '?' in wms_url else '?'}SERVICE=WMS&REQUEST=GetCapabilities"
    st.write("GetCapabilities:")
    st.code(getcap, language="text")

    st.caption("Tip: ถ้าไม่ขึ้น ให้ลองเปิด DevTools Console ดู error และตรวจชื่อ layer/CRS/การบล็อก CORS")

if not longdo_key.strip():
    st.warning("กรุณาใส่ Longdo Map API Key ก่อน")
    st.stop()

if not layer_name.strip():
    st.warning("กรุณาใส่ Layer name (<Name> จาก GetCapabilities) ก่อน")
    st.stop()

# -----------------------
# Build WMS extraQuery (KVP)
# -----------------------
extra_parts = []

# layers=...
extra_parts.append(f"layers={quote(layer_name.strip())}")

# styles=... (โหมด styles)
if red_mode.startswith("ใช้ styles"):
    if styles.strip():
        extra_parts.append(f"styles={quote(styles.strip())}")
    else:
        # ปล่อยว่างได้ แต่จะไม่เปลี่ยนสีให้แดง
        extra_parts.append("styles=")

# transparent=...
if transparent and img_format == "image/png":
    extra_parts.append("transparent=true")

# SLD_BODY=... (โหมด SLD)
if red_mode.startswith("ใช้ SLD_BODY"):
    # แนะนำให้แทน YOUR_LAYER_NAME อัตโนมัติ
    if sld_body:
        sld_fixed = sld_body.replace("YOUR_LAYER_NAME", layer_name.strip())
        extra_parts.append("SLD_BODY=" + quote(sld_fixed))

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
      <div><b>Layer:</b> <span class="mono">{layer_name}</span></div>
      <div><b>SRS:</b> <span class="mono">{srs}</span> | <b>Format:</b> <span class="mono">{img_format}</span> | <b>Opacity:</b> {opacity}</div>
      <div><b>Mode:</b> {red_mode}</div>
      <div><b>extraQuery:</b> <span class="mono">{extra_query}</span></div>
    </div>

    <script>
      var map = new longdo.Map({{
        placeholder: document.getElementById('map'),
        location: {{ lat: {lat}, lon: {lon} }},
        zoom: {zoom}
      }});

      map.Overlays.add(new longdo.Marker({{ lat: {lat}, lon: {lon} }}, {{ title: 'Center' }}));

      try {{
        var wmsLayer = new longdo.Layer('WMS (Red)', {{
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

components.html(html, height=height + 110, scrolling=False)

st.subheader("เช็คว่า ‘ทำแดง’ ได้จริงไหม")
st.markdown(
    """
### ถ้าเลือก `styles=` แล้วไม่แดง
- แปลว่า WMS **ไม่มี style สีแดง** หรือชื่อ style ไม่ตรง  
- ให้เปิด GetCapabilities แล้วคัดลอกชื่อ style จาก `<Style><Name>...</Name></Style>`

### ถ้าเลือก `SLD_BODY=` แล้วไม่แดง
- มีโอกาสสูงว่า **MapProxy/เซิร์ฟเวอร์ไม่อนุญาต SLD** หรือไม่ส่งต่อพารามิเตอร์ไปยัง upstream  
- หรือ layer ไม่ใช่ polygon/ชื่อ layer ไม่ตรง

ถ้าคุณส่ง “ชื่อ layer” และส่วน `<Style>...</Style>` จาก GetCapabilities มา ผมจะบอกให้ได้ว่าควรใส่ `styles=` อะไรถึงจะเป็นสีแดงครับ
    """
)

st.subheader("การตั้งค่า secrets (แนะนำ)")
