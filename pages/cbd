import streamlit as st
import streamlit.components.v1 as components

st.set_page_config(page_title="Longdo Map Streamlit", layout="wide")
st.title("🗺️ Longdo Map with Streamlit")

with st.sidebar:
    st.header("📍 ตั้งค่าพิกัด")
    api_key = st.text_input("Longdo API Key", value="0a999afb0da60c5c45d010e9c171ffc8")
    lat = st.number_input("Latitude", value=13.7469, format="%.6f")
    lon = st.number_input("Longitude", value=100.5349, format="%.6f")
    zoom = st.slider("Zoom Level", 1, 20, 15)

    st.header("🧩 Layers")
    show_traffic = st.checkbox("Traffic", value=True)
    show_wms = st.checkbox("Longdo WMS (MapProxy)", value=True)

    # ใส่ชื่อชั้น WMS ที่ได้จาก GetCapabilities
    wms_layer_name = st.text_input("WMS Layer Name (จาก GetCapabilities)", value="WMS_LAYER_NAME_HERE")

WMS_URL = "http://ms.longdo.com/mapproxy/service"

longdo_map_html = f"""
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8" />
  <style>
    body {{ margin: 0; padding: 0; }}
    #map {{ height: 600px; width: 100%; }}
  </style>

  <script src="https://api.longdo.com/map/?key={api_key}"></script>
  <script>
    var map;

    function init() {{
      map = new longdo.Map({{
        placeholder: document.getElementById('map')
      }});

      map.location({{ lon: {lon}, lat: {lat} }}, true);
      map.zoom({zoom});

      // marker
      var marker = new longdo.Marker({{ lon: {lon}, lat: {lat} }}, {{
        title: 'ตำแหน่งที่เลือก',
        detail: 'Lat: {lat}, Lon: {lon}'
      }});
      map.Overlays.add(marker);

      // Traffic layer
      if ({str(show_traffic).lower()}) {{
        map.Layers.add(longdo.Layers.TRAFFIC);
      }}

      // WMS layer (overlay)
      if ({str(show_wms).lower()}) {{
        // สร้าง WMS layer (ต้องให้ name/layers ถูกต้อง)
        var wms = new longdo.Layer('{wms_layer_name}', {{
          type: longdo.LayerType.WMS,
          url: '{WMS_URL}',
          // ค่าด้านล่างเป็น WMS params ทั่วไป
          layers: '{wms_layer_name}',
          format: 'image/png',
          transparent: true
        }});

        map.Layers.add(wms);
      }}
    }}
  </script>
</head>

<body onload="init();">
  <div id="map"></div>
</body>
</html>
"""

components.html(longdo_map_html, height=600)
st.markdown(f"**พิกัดปัจจุบัน:** `{lat}, {lon}`")
