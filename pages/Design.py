import streamlit as st
import json
import pandas as pd
import plotly.graph_objects as go
import numpy as np
import math
import networkx as nx

# ══════════════════════════════════════════
# ⚙️  Page Config + Session State
# ══════════════════════════════════════════
st.set_page_config(page_title="AI Architecture Pipeline", layout="wide", page_icon="🏛️")

if "site_width"  not in st.session_state: st.session_state.site_width  = 8.0
if "site_length" not in st.session_state: st.session_state.site_length = 4.0
if "plan_generated" not in st.session_state: st.session_state.plan_generated = False

# ── Global CSS ────────────────────────────────────────────────
st.markdown("""
<style>
  [data-testid="stAppViewContainer"] { background: #0F1624; }
  [data-testid="stHeader"]           { background: transparent; }

  .hero {
    background: linear-gradient(135deg,#0D1B35 0%,#1A2E55 55%,#0F3460 100%);
    border: 1px solid #1E3A6E;
    border-radius: 18px;
    padding: 30px 40px 26px 40px;
    margin-bottom: 28px;
  }
  .hero h1 { color:#E8F0FF !important; margin:0 0 8px 0; font-size:2rem; }
  .hero p  { color:#7090C0; margin:0; font-size:0.93rem; }

  .card {
    background: #141C2E;
    border: 1px solid #1E2E4A;
    border-radius: 14px;
    padding: 22px 26px;
    margin-bottom: 18px;
  }

  [data-testid="metric-container"] {
    background: #1A2540;
    border: 1px solid #243358;
    border-left: 4px solid #3B82F6;
    border-radius: 12px;
    padding: 14px 18px;
  }
  [data-testid="metric-container"] label                          { color:#7090C0 !important; }
  [data-testid="metric-container"] [data-testid="stMetricValue"] { color:#E8F0FF !important; }

  [data-baseweb="tab-list"] { gap:6px; background:transparent !important; }
  [data-baseweb="tab"] {
    background:#141C2E !important; border:1px solid #1E2E4A !important;
    border-radius:10px 10px 0 0 !important; padding:10px 24px !important;
    color:#7090C0 !important; font-weight:600 !important;
  }
  [aria-selected="true"] {
    background:#1A2540 !important;
    border-bottom-color:#3B82F6 !important;
    color:#60A5FA !important;
  }

  [data-testid="stTextInput"] input,
  [data-testid="stNumberInput"] input {
    background:#1A2540 !important; border:1px solid #243358 !important;
    color:#E8F0FF !important; border-radius:8px !important;
  }
  [data-testid="stTextArea"] textarea {
    background:#1A2540 !important; border:1px solid #243358 !important;
    color:#E8F0FF !important; font-size:0.82rem !important;
  }

  label, .stMarkdown p { color:#A0B8D8 !important; }
  h1,h2,h3             { color:#C8DCFF !important; }
  hr                   { border-color:#1E2E4A !important; margin:24px 0 !important; }

  .note {
    background:#0D1E3A; border-left:4px solid #3B82F6;
    border-radius:8px; padding:14px 18px;
    font-size:0.87rem; color:#90B4D8; margin:14px 0; line-height:1.7;
  }
  [data-testid="stDataFrame"] { border-radius:10px; overflow:hidden; }
</style>
""", unsafe_allow_html=True)

st.markdown("""
<div class="hero">
  <h1>🏛️ AI Architecture: Schematic Design Pipeline</h1>
  <p>Program Definition &rarr; AI Prompt &rarr; Adjacency Analysis &rarr; Relationship Graph &rarr; Packed Floor Plan &rarr; Math-Bounded Furniture</p>
</div>
""", unsafe_allow_html=True)

# ══════════════════════════════════════════
# 🎨  Design Tokens
# ══════════════════════════════════════════
ROOM_PALETTE = {
    "Living Area":"#4E79A7","Bedroom":"#E15759","Dining":"#F28E2B",
    "Kitchen":"#59A14F","Bathroom":"#76B7B2","Closet":"#B07AA1",
    "Balcony":"#EDC948","Laundry":"#FF9DA7",
}
FALLBACK = ["#4E79A7","#E15759","#F28E2B","#59A14F",
            "#76B7B2","#B07AA1","#EDC948","#FF9DA7","#BAB0AC","#D37295"]

ZONE_MAP = {
    "Living Area":"Public","Dining":"Public",
    "Kitchen":"Service","Laundry":"Service","Balcony":"Semi-Public",
    "Bedroom":"Private","Bathroom":"Private","Closet":"Private",
}
ZONE_ACCENT = {"Public":"#4A9EE0","Service":"#3CC470","Private":"#E05C5C","Semi-Public":"#E0C040"}

THAI_FONT = "Tahoma, Segoe UI, sans-serif"

# ── Slice and Dice Algorithm (Treemap Packing) ────────────────
def generate_treemap(items, x, y, w, h):
    """แบ่งพื้นที่แบบ Slice and Dice ผ่าครึ่งตามสัดส่วนพื้นที่ (รับประกันเติมเต็ม 100%)"""
    if not items: return []
    if len(items) == 1: return [{'room': items[0][0], 'x': x, 'y': y, 'w': w, 'h': h}]
    
    tot_area = sum(i[1] for i in items)
    best_split, min_diff, acc = 1, float('inf'), 0
    
    for i in range(1, len(items)):
        acc += items[i-1][1]
        diff = abs(acc - tot_area/2)
        if diff < min_diff:
            min_diff = diff
            best_split = i
            
    items1 = items[:best_split]
    items2 = items[best_split:]
    area1 = sum(i[1] for i in items1)
    
    if w >= h:
        w1 = w * (area1 / tot_area)
        r1 = generate_treemap(items1, x, y, w1, h)
        r2 = generate_treemap(items2, x + w1, y, w - w1, h)
    else:
        h1 = h * (area1 / tot_area)
        r1 = generate_treemap(items1, x, y, w, h1)
        r2 = generate_treemap(items2, x, y + h1, w, h - h1)
    return r1 + r2

# ══════════════════════════════════════════
# 🗂️  Tabs
# ══════════════════════════════════════════
tab1, tab2 = st.tabs([
    "📤  USER INPUT  &  EXPORT PROMPT",
    "📥  IMPORT JSON  &  FINAL PRODUCT",
])

# ════════════════════════════════════════════════════════════════
# 📤  TAB 1
# ════════════════════════════════════════════════════════════════
with tab1:
    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.subheader("🏗️ Program Definition & Site")

    c1, c2 = st.columns(2)
    with c1:
        project_type = st.text_input("Project Type", value="บ้านเช่า (Rental House)")
        width  = st.number_input("ความกว้าง Site (ม.)",  value=st.session_state.site_width,
                                  step=0.5, min_value=1.0, key="site_width")
        length = st.number_input("ความยาว Site (ม.)",   value=st.session_state.site_length,
                                  step=0.5, min_value=1.0, key="site_length")
    with c2:
        rooms = st.multiselect(
            "พื้นที่ใช้สอยที่ต้องการ",
            ["Bedroom","Living Area","Kitchen","Dining","Bathroom","Balcony","Laundry","Closet"],
            default=["Bedroom","Living Area","Kitchen","Dining","Bathroom","Closet"],
        )
        mode = st.radio("Sizing Mode", ["Auto (Neufert / Thai Building Code)", "Manual (ผู้ใช้กำหนดเอง)"])
    st.markdown('</div>', unsafe_allow_html=True)

    DEFAULT_AREAS = {
        "Bedroom":7.0,"Living Area":7.0,"Kitchen":6.0,"Dining":6.0,
        "Bathroom":3.0,"Balcony":2.5,"Laundry":2.0,"Closet":3.0,
    }
    manual_areas = {}

    if mode == "Manual (ผู้ใช้กำหนดเอง)" and rooms:
        st.markdown('<div class="card">', unsafe_allow_html=True)
        cols = st.columns(min(len(rooms), 4))
        for i, room in enumerate(rooms):
            with cols[i % 4]:
                manual_areas[room] = st.number_input(
                    f"{room} (ตร.ม.)", value=DEFAULT_AREAS.get(room, 4.0),
                    min_value=1.0, max_value=100.0, step=0.5, key=f"m_{room}",
                )

    if st.button("🚀 Generate AI Prompt", type="primary"):
        if rooms:
            payload = [{"room":r,"net_area_sqm":manual_areas.get(r,DEFAULT_AREAS.get(r,4.0))} for r in rooms] if mode == "Manual (ผู้ใช้กำหนดเอง)" else "Auto-calculate"
            prompt = {
                "system_prompt": "คุณคือสถาปนิกระดับ Senior ส่งกลับเป็น JSON เท่านั้น",
                "user_input": {
                    "project": project_type, "site_dimension": f"{width} x {length} m",
                    "required_spaces": rooms, "sizing_mode": mode, "space_areas": payload,
                },
                "required_output_schema": {
                    "Space_Requirement": [{"room":"string","net_area_sqm":"float"}],
                    "Adjacency": [{"room1":"string","room2":"string", "score":"int (3,2,1,-1)","reason":"string"}],
                    "Design_Concept": "string",
                },
            }
            st.success("✅ **Prompt A — Packed Plan**")
            st.code(json.dumps(prompt, ensure_ascii=False, indent=4), language="json")

# ════════════════════════════════════════════════════════════════
# 📥  TAB 2
# ════════════════════════════════════════════════════════════════
with tab2:
    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.subheader("⚙️ Circulation Factor")
    circ_pct = st.number_input("Circulation (% Net Area)", min_value=0, max_value=100, value=0, step=5)
    circ_factor = circ_pct / 100.0
    st.markdown('</div>', unsafe_allow_html=True)

    # JSON Input for Space & Adjacency
    MOCK = """{
    "Space_Requirement": [
        {"room": "Kitchen",      "net_area_sqm": 6.0},
        {"room": "Dining",       "net_area_sqm": 6.0},
        {"room": "Bathroom",     "net_area_sqm": 3.0},
        {"room": "Closet",       "net_area_sqm": 3.0},
        {"room": "Bedroom",      "net_area_sqm": 7.0},
        {"room": "Living Area",  "net_area_sqm": 7.0}
    ],
    "Adjacency": [
        {"room1": "Kitchen",     "room2": "Dining",   "score":  3, "reason": "Serve food"},
        {"room1": "Bathroom",    "room2": "Closet",   "score":  3, "reason": "Dressing area"},
        {"room1": "Bedroom",     "room2": "Living Area","score": 2, "reason": "Private connection"},
        {"room1": "Living Area", "room2": "Dining",   "score":  2, "reason": "Open plan connection"},
        {"room1": "Bedroom",     "room2": "Bathroom", "score":  2, "reason": "Convenience"},
        {"room1": "Kitchen",     "room2": "Bedroom",  "score": -1, "reason": "Odor & Noise"}
    ],
    "Design_Concept": "Packed layout fitting exactly 8x4 meters site boundary."
}"""

    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.subheader("📋 วาง AI Result JSON (Space Requirement)")
    user_json = st.text_area("⬇️ JSON output from Prompt A", value=MOCK, height=220)
    st.markdown('</div>', unsafe_allow_html=True)

    if st.button("✨ Generate Schematic Packed Plan", type="primary"):
        st.session_state.plan_generated = True

    if st.session_state.get("plan_generated", False):
        try:
            data = json.loads(user_json)
            df   = pd.DataFrame(data["Space_Requirement"])
            clbl = f"Circulation_{circ_pct}%"
            df[clbl]        = df["net_area_sqm"] * circ_factor
            df["Gross_sqm"] = df["net_area_sqm"] + df[clbl]
            rooms_list      = df["room"].tolist()

            pal = {}; fi = 0
            for r in rooms_list:
                pal[r] = ROOM_PALETTE.get(r, FALLBACK[fi % len(FALLBACK)])
                if r not in ROOM_PALETTE: fi += 1

            SITE_W = st.session_state.get("site_width", 8.0)
            SITE_L = st.session_state.get("site_length", 4.0)
            SITE_AREA = SITE_W * SITE_L
            
            t_net = df["net_area_sqm"].sum()
            t_gross = df["Gross_sqm"].sum()
            scale_ratio = SITE_AREA / t_gross if t_gross > 0 else 1

            # ── Schematic Packed Block Plan (Treemap) ──
            G = nx.Graph()
            for r in rooms_list: G.add_node(r)
            WM = {3:4.0, 2:2.5, 1:1.0, -1:0.02}
            for adj in data["Adjacency"]:
                r1, r2, sc = adj["room1"], adj["room2"], adj["score"]
                if r1 in rooms_list and r2 in rooms_list:
                    G.add_edge(r1, r2, weight=WM.get(sc, 1.0))
            
            sp = nx.spring_layout(G, weight="weight", seed=42)
            sorted_rooms = sorted(rooms_list, key=lambda r: sp[r][1], reverse=True)

            items_to_pack = [(r, df.loc[df["room"]==r, "Gross_sqm"].values[0] * scale_ratio) for r in sorted_rooms]
            layout_rects = generate_treemap(items_to_pack, 0, 0, SITE_W, SITE_L)

            st.markdown("---")
            st.markdown("### 🟩 Schematic Packed Floor Plan  (100% Site Fit)")

            fig_bp = go.Figure()
            BG = "#0F1624"
            pad = 0.04
            
            for rd in layout_rects:
                room, rx, ry, rw, rh = rd['room'], rd['x'], rd['y'], rd['w'], rd['h']
                color = pal[room]
                fig_bp.add_shape(type="rect", x0=rx+pad, y0=ry+pad, x1=rx+rw-pad, y1=ry+rh-pad, fillcolor=color, opacity=0.92, line=dict(color="#FFFFFF", width=2))
                fig_bp.add_annotation(x=rx+rw/2, y=ry+rh/2, text=room, showarrow=False, font=dict(size=12, color="white", family="Arial Black"))
                fig_bp.add_annotation(x=rx+rw/2, y=ry+rh/2 - rh*0.12, text=f"{rw*rh:.1f} ตร.ม.", showarrow=False, font=dict(size=9, color="#E8F0FF", family=THAI_FONT))

            fig_bp.add_shape(type="rect", x0=0, y0=0, x1=SITE_W, y1=SITE_L, line=dict(color="#FFD700", width=4), fillcolor="rgba(0,0,0,0)")

            fig_bp.update_layout(
                height=500, plot_bgcolor=BG, paper_bgcolor=BG,
                xaxis=dict(visible=False, scaleanchor="y", scaleratio=1),
                yaxis=dict(visible=False), margin=dict(l=20, r=20, t=20, b=20),
            )
            st.plotly_chart(fig_bp, width="stretch")

            # ══════════════════════════════════════════════════════
            # 7. Import Openings + Furniture JSON (User's JSON)
            # ══════════════════════════════════════════════════════
            st.markdown("---")
            st.markdown("### 🪑 7. Import Openings + Furniture (AI Result)")
            
            # ใส่ JSON ที่ผู้ใช้ให้มาเป็น Default
            USER_MOCK_OF = """{
  "Openings": [
    {"id": "W-KIT-01", "room": "Kitchen", "wall": "south", "offset_m": 0.9, "width_m": 1.2, "height_m": 1.0, "sill_height_m": 0.9, "type": "window"},
    {"id": "W-KIT-02", "room": "Kitchen", "wall": "west", "offset_m": 0.7, "width_m": 0.8, "height_m": 1.0, "sill_height_m": 0.9, "type": "window"},
    {"id": "D-KIT-01", "room": "Kitchen", "wall": "east", "offset_m": 0.55, "width_m": 0.9, "height_m": 2.1, "sill_height_m": 0.0, "type": "door"},
    {"id": "W-DIN-01", "room": "Dining", "wall": "north", "offset_m": 1.0, "width_m": 1.0, "height_m": 1.0, "sill_height_m": 0.9, "type": "window"},
    {"id": "W-DIN-02", "room": "Dining", "wall": "west", "offset_m": 0.5, "width_m": 0.8, "height_m": 1.0, "sill_height_m": 0.9, "type": "window"},
    {"id": "D-DIN-01", "room": "Dining", "wall": "east", "offset_m": 0.55, "width_m": 0.9, "height_m": 2.1, "sill_height_m": 0.0, "type": "door"},
    {"id": "D-LIV-01", "room": "Living Area", "wall": "south", "offset_m": 0.425, "width_m": 0.9, "height_m": 2.1, "sill_height_m": 0.0, "type": "door"},
    {"id": "W-LIV-01", "room": "Living Area", "wall": "north", "offset_m": 0.375, "width_m": 1.0, "height_m": 1.0, "sill_height_m": 0.9, "type": "window"},
    {"id": "D-BED-01", "room": "Bedroom", "wall": "west", "offset_m": 0.5, "width_m": 0.9, "height_m": 2.1, "sill_height_m": 0.0, "type": "door"},
    {"id": "W-BED-01", "room": "Bedroom", "wall": "south", "offset_m": 0.8, "width_m": 1.5, "height_m": 1.0, "sill_height_m": 0.9, "type": "window"},
    {"id": "W-BED-02", "room": "Bedroom", "wall": "east", "offset_m": 0.58, "width_m": 0.8, "height_m": 1.0, "sill_height_m": 0.9, "type": "window"},
    {"id": "D-BATH-01", "room": "Bathroom", "wall": "south", "offset_m": 0.3, "width_m": 0.8, "height_m": 2.1, "sill_height_m": 0.0, "type": "door"},
    {"id": "W-BATH-01", "room": "Bathroom", "wall": "north", "offset_m": 0.5, "width_m": 0.6, "height_m": 0.6, "sill_height_m": 1.5, "type": "fixed"},
    {"id": "D-CLO-01", "room": "Closet", "wall": "south", "offset_m": 0.2, "width_m": 1.2, "height_m": 2.1, "sill_height_m": 0.0, "type": "sliding"},
    {"id": "W-CLO-01", "room": "Closet", "wall": "east", "offset_m": 0.6, "width_m": 0.6, "height_m": 0.6, "sill_height_m": 1.5, "type": "fixed"}
  ],
  "Furniture": [
    {"id": "F-KIT-01", "room": "Kitchen", "type": "base_cabinet_countertop", "w_m": 2.4, "d_m": 0.6, "h_m": 0.9, "x_m": 0.0, "y_m": 0.0, "orientation_deg": 0.0, "clearance_m": 1.4, "placement_mode": "wall-mounted"},
    {"id": "F-KIT-02", "room": "Kitchen", "type": "refrigerator", "w_m": 0.6, "d_m": 0.6, "h_m": 1.8, "x_m": 2.4, "y_m": 0.0, "orientation_deg": 0.0, "clearance_m": 0.6, "placement_mode": "corner"},
    {"id": "F-KIT-03", "room": "Kitchen", "type": "base_cabinet_west", "w_m": 0.6, "d_m": 1.1, "h_m": 0.9, "x_m": 0.0, "y_m": 0.6, "orientation_deg": 0.0, "clearance_m": 0.9, "placement_mode": "wall-mounted"},
    {"id": "F-DIN-01", "room": "Dining", "type": "dining_table", "w_m": 1.2, "d_m": 0.8, "h_m": 0.75, "x_m": 0.9, "y_m": 2.65, "orientation_deg": 0.0, "clearance_m": 0.65, "placement_mode": "island"},
    {"id": "F-DIN-02", "room": "Dining", "type": "chair", "w_m": 0.45, "d_m": 0.45, "h_m": 0.9, "x_m": 0.35, "y_m": 2.775, "orientation_deg": 270.0, "clearance_m": 0.35, "placement_mode": "free"},
    {"id": "F-DIN-03", "room": "Dining", "type": "chair", "w_m": 0.45, "d_m": 0.45, "h_m": 0.9, "x_m": 2.2, "y_m": 2.775, "orientation_deg": 90.0, "clearance_m": 0.35, "placement_mode": "free"},
    {"id": "F-DIN-04", "room": "Dining", "type": "chair", "w_m": 0.45, "d_m": 0.45, "h_m": 0.9, "x_m": 1.075, "y_m": 3.5, "orientation_deg": 180.0, "clearance_m": 0.5, "placement_mode": "free"},
    {"id": "F-DIN-05", "room": "Dining", "type": "chair", "w_m": 0.45, "d_m": 0.45, "h_m": 0.9, "x_m": 1.075, "y_m": 2.1, "orientation_deg": 0.0, "clearance_m": 0.1, "placement_mode": "free"},
    {"id": "F-LIV-01", "room": "Living Area", "type": "sofa_2seat", "w_m": 0.75, "d_m": 1.5, "h_m": 0.85, "x_m": 3.0, "y_m": 1.3, "orientation_deg": 90.0, "clearance_m": 0.7, "placement_mode": "wall-mounted"},
    {"id": "F-LIV-02", "room": "Living Area", "type": "tv_unit", "w_m": 0.3, "d_m": 0.9, "h_m": 0.5, "x_m": 4.45, "y_m": 1.55, "orientation_deg": 0.0, "clearance_m": 0.7, "placement_mode": "wall-mounted"},
    {"id": "F-LIV-03", "room": "Living Area", "type": "side_table", "w_m": 0.4, "d_m": 0.4, "h_m": 0.55, "x_m": 3.0, "y_m": 0.8, "orientation_deg": 0.0, "clearance_m": 0.6, "placement_mode": "corner"},
    {"id": "F-BED-01", "room": "Bedroom", "type": "double_bed", "w_m": 2.0, "d_m": 1.6, "h_m": 0.5, "x_m": 6.0, "y_m": 0.277, "orientation_deg": 0.0, "clearance_m": 0.5, "placement_mode": "wall-mounted"},
    {"id": "F-BED-02", "room": "Bedroom", "type": "nightstand", "w_m": 0.5, "d_m": 0.27, "h_m": 0.55, "x_m": 7.5, "y_m": 0.0, "orientation_deg": 0.0, "clearance_m": 0.5, "placement_mode": "corner"},
    {"id": "F-BED-03", "room": "Bedroom", "type": "nightstand", "w_m": 0.5, "d_m": 0.27, "h_m": 0.55, "x_m": 7.5, "y_m": 1.877, "orientation_deg": 0.0, "clearance_m": 0.5, "placement_mode": "corner"},
    {"id": "F-BATH-01", "room": "Bathroom", "type": "shower_enclosure", "w_m": 0.9, "d_m": 0.9, "h_m": 2.1, "x_m": 4.75, "y_m": 2.154, "orientation_deg": 0.0, "clearance_m": 0.6, "placement_mode": "corner"},
    {"id": "F-BATH-02", "room": "Bathroom", "type": "toilet", "w_m": 0.4, "d_m": 0.65, "h_m": 0.8, "x_
