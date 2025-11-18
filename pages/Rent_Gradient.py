import streamlit as st
import numpy as np
import pandas as pd
import pydeck as pdk

st.set_page_config(page_title="Rent Gradient Map", layout="wide")

st.title("📍 Rent Gradient Map (Urban Economics Theory)")
st.markdown(
    """
    แผนที่นี้จำลอง **rent gradient** (ค่าเช่าลดลงตามระยะห่างจากศูนย์กลางเมือง - CBD)  
    ใช้โมเดลเชิงทฤษฎีแบบง่าย ๆ เพื่อเล่นกับไอเดียเชิง Urban Economics
    """
)

# ---------------- Sidebar Controls ----------------
st.sidebar.header("🔧 Parameters")

city = st.sidebar.selectbox(
    "City Center (for visualization)",
    options=["Bangkok (CBD)", "Custom"],
    index=0,
)

if city == "Bangkok (CBD)":
    center_lat = 13.7563
    center_lon = 100.5018
else:
    center_lat = st.sidebar.number_input("Center Latitude", value=13.7563, format="%.6f")
    center_lon = st.sidebar.number_input("Center Longitude", value=100.5018, format="%.6f")

max_radius_km = st.sidebar.slider("Max radius from center (km)", 5.0, 50.0, 25.0, 1.0)

model_type = st.sidebar.radio("Rent gradient model", ["Linear", "Exponential"])

base_rent = st.sidebar.number_input("Base rent at CBD (R₀)", value=1000.0, min_value=0.0, step=10.0)
min_rent = st.sidebar.number_input("Minimum rent floor", value=0.0, min_value=0.0, step=10.0)

if model_type == "Linear":
    slope = st.sidebar.number_input("Slope per km (β)", value=20.0, min_value=0.0, step=1.0)
else:
    decay = st.sidebar.number_input("Decay rate per km (λ)", value=0.10, min_value=0.0, step=0.01, format="%.2f")

n_radial = st.sidebar.slider("Radial steps", 10, 60, 30)
n_angular = st.sidebar.slider("Angular steps", 16, 72, 36)

# ---------------- Rent Gradient Model ----------------
def rent_function(distance_km: np.ndarray) -> np.ndarray:
    if model_type == "Linear":
        rent = base_rent - slope * distance_km
    else:
        rent = base_rent * np.exp(-decay * distance_km)
    return np.maximum(rent, min_rent)

# ---------------- Generate Grid ----------------
# Create polar grid (distance, angle) then project to lat/lon (equirectangular approximation)
r = np.linspace(0, max_radius_km, n_radial)
theta = np.linspace(0, 2 * np.pi, n_angular, endpoint=False)

R, T = np.meshgrid(r, theta)  # shape (n_angular, n_radial)

# Convert to local x/y in km
x_km = R * np.cos(T)  # east-west
y_km = R * np.sin(T)  # north-south

# Convert km offsets to lat/lon (rough approximation, good enough for city scale)
lat0_rad = np.radians(center_lat)
lat = center_lat + (y_km / 110.574)  # 1 degree latitude ~ 110.574 km
lon = center_lon + (x_km / (111.320 * np.cos(lat0_rad)))  # adjust for latitude

distance_km = np.sqrt(x_km**2 + y_km**2)
rent = rent_function(distance_km)

df = pd.DataFrame(
    {
        "lat": lat.ravel(),
        "lon": lon.ravel(),
        "distance_km": distance_km.ravel(),
        "rent": rent.ravel(),
    }
)

# Normalize rent for color mapping / weight
if df["rent"].max() > 0:
    df["rent_norm"] = df["rent"] / df["rent"].max()
else:
    df["rent_norm"] = 0.0

# ---------------- Map (PyDeck) ----------------
st.subheader("🗺️ Rent Gradient Heatmap")

view_state = pdk.ViewState(
    latitude=center_lat,
    longitude=center_lon,
    zoom=10,
    pitch=45,
)

heatmap_layer = pdk.Layer(
    "HeatmapLayer",
    data=df,
    get_position="[lon, lat]",
    get_weight="rent",
    radius_pixels=60,
)

scatter_layer = pdk.Layer(
    "ScatterplotLayer",
    data=df,
    get_position="[lon, lat]",
    get_fill_color="[255 * rent_norm, 50, 255 * (1-rent_norm)]",
    get_radius=150,
    pickable=True,
)

cbd_layer = pdk.Layer(
    "ScatterplotLayer",
    data=pd.DataFrame({"lat": [center_lat], "lon": [center_lon]}),
    get_position="[lon, lat]",
    get_fill_color="[0, 0, 0]",
    get_radius=300,
)

deck = pdk.Deck(
    layers=[heatmap_layer, scatter_layer, cbd_layer],
    initial_view_state=view_state,
    tooltip={
        "html": "<b>Rent</b>: {rent} <br/> <b>Distance</b>: {distance_km} km",
        "style": {"color": "white"},
    },
)

st.pydeck_chart(deck)

# ---------------- Rent vs Distance Chart ----------------
st.subheader("📉 Rent vs Distance (theoretical gradient)")

max_r_for_chart = max_radius_km
r_line = np.linspace(0, max_r_for_chart, 200)
rent_line = rent_function(r_line)
chart_df = pd.DataFrame({"distance_km": r_line, "rent": rent_line})

st.line_chart(chart_df.set_index("distance_km"))

# ---------------- Text Explanation ----------------
with st.expander("อธิบายทฤษฎีแบบสั้น ๆ"):
    st.markdown(
        """
        **Rent Gradient Theory (Bid-Rent Function)**  
        - ในโมเดลเมืองศูนย์กลางเดียว (monocentric city model) สมมติว่าทุกคนต้องเดินทางเข้า CBD  
        - ค่าใช้จ่ายในการเดินทางยิ่งไกลยิ่งแพง → คนยอมจ่ายค่าเช่าน้อยลงเมื่ออยู่ไกล CBD  
        - เลยได้ฟังก์ชันค่าเช่าแบบลดลงตามระยะทาง เช่น  
            - Linear: `R(d) = R₀ − β d`  
            - Exponential: `R(d) = R₀ · exp(−λ d)`  
        
        App นี้ไม่ได้ใช้ข้อมูลจริง แต่เป็น **sandbox** ให้ลองเล่นกับไอเดียว่า
        ถ้าเราเปลี่ยน `R₀`, `β` หรือ `λ` แล้วรูปของ rent gradient และ pattern บนแผนที่จะเปลี่ยนไปยังไง
        """
    )
