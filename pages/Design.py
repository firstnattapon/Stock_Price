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
  <p>Program Definition &rarr; AI Prompt &rarr; Adjacency Analysis &rarr; Relationship Graph &rarr; Packed Floor Plan &rarr; Furnishing</p>
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

with tab1:
    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.subheader("🏗️ Program Definition & Site")
    c1, c2 = st.columns(2)
    with c1:
        project_type = st.text_input("Project Type", value="บ้านเช่า (Rental House)")
        width  = st.number_input("ความกว้าง Site (ม.)",  value=st.session_state.site_width, step=0.5, min_value=1.0, key="site_width")
        length = st.number_input("ความยาว Site (ม.)",   value=st.session_state.site_length, step=0.5, min_value=1.0, key="site_length")
        st.info(f"📐 พื้นที่ Site รวม: **{width * length:.1f} ตร.ม.** ({width:.1f} × {length:.1f} ม.)")
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
        st.subheader("📐 กำหนดพื้นที่แต่ละห้อง")
        cols = st.columns(min(len(rooms), 4))
        for i, room in enumerate(rooms):
            with cols[i % 4]:
                manual_areas[room] = st.number_input(f"{room} (ตร.ม.)", value=DEFAULT_AREAS.get(room, 4.0), min_value=1.0, step=0.5, key=f"m_{room}")
        total_m = sum(manual_areas.values())
        site_a  = width * length
        pct     = (total_m / site_a * 100) if site_a > 0 else 0
        ca, cb, cc = st.columns(3)
        ca.metric("📐 Total Net",  f"{total_m:.1f} ตร.ม.")
        cb.metric("🏗️ Site Area",  f"{site_a:.1f} ตร.ม.")
        cc.metric("📊 Coverage",   f"{pct:.0f}%", delta="⚠️ เกิน Site!" if pct > 100 else "✅ OK", delta_color="inverse" if pct > 100 else "normal")
        st.markdown('</div>', unsafe_allow_html=True)

    if st.button("🚀 Generate AI Prompt", type="primary"):
        if not rooms:
            st.error("กรุณาเลือกห้องอย่างน้อย 1 ห้อง")
        else:
            payload = [{"room":r,"net_area_sqm":manual_areas.get(r,DEFAULT_AREAS.get(r,4.0))} for r in rooms] if mode == "Manual (ผู้ใช้กำหนดเอง)" else "Auto-calculate"
            prompt = {
                "system_prompt": "คุณคือสถาปนิกระดับ Senior หน้าที่ของคุณคือวิเคราะห์ข้อมูลและส่งกลับเป็น JSON เท่านั้น",
                "user_input": {
                    "project": project_type, "site_dimension": f"{width} x {length} m",
                    "required_spaces": rooms, "sizing_mode": mode, "space_areas": payload,
                },
                "required_output_schema": {
                    "Space_Requirement": [{"room":"string","net_area_sqm":"float"}],
                    "Adjacency": [{"room1":"string","room2":"string", "score":"int (3=ติดกัน,2=ใกล้,1=เฉยๆ,-1=แยก)","reason":"string"}],
                    "Design_Concept": "string",
                },
            }
            st.success("✅ **Prompt A — Packed Plan**: คัดลอกข้อความด้านล่างนี้ไปวางใน Claude / ChatGPT")
            st.code(json.dumps(prompt, ensure_ascii=False, indent=4), language="json")

            st.markdown("---")
            st.info("💡 **Prompt B — Openings + Furniture**: หลังจากได้ Packed Plan แล้ว ให้คัดลอก Prompt B ด้านล่างไปใช้ต่อ")
            prompt_b = {
                "system_prompt": "ตอบกลับเป็น JSON เท่านั้น คืนค่าพิกัดแบบ Relative (x_m, y_m เริ่มจากมุมซ้ายล่างของแต่ละห้อง = 0,0)",
                "user_prompt": "รับ Packed_Plan เป็น input คืนค่า Openings และ Furniture โดย x_m, y_m ให้อ้างอิงจากมุมซ้ายล่างของห้องนั้นๆ",
                "required_output_schema": {
                    "Openings": [{"id":"str","room":"str","wall":"north|south|east|west","offset_m":"float","width_m":"float","type":"window|door"}],
                    "Furniture": [{"id":"str","room":"str","type":"str","w_m":"float","d_m":"float","x_m":"float","y_m":"float"}],
                    "Checks": {"overlaps":"[]", "clearance_violations":"[]", "door_swing_conflicts":"[]"},
                },
            }
            st.code(json.dumps(prompt_b, ensure_ascii=False, indent=4), language="json")

with tab2:
    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.subheader("⚙️ Circulation Factor")
    cc1, cc2 = st.columns([1, 3])
    with cc1:
        circ_pct = st.number_input("Circulation (% Net Area)", min_value=0, max_value=100, value=0, step=5)
    with cc2:
        st.info("💡 เนื่องจากใช้วิธี Pack Area พอดี Site ระบบจะแปลง Circulation เป็นตัวคูณ (Scaling Factor)")
    circ_factor = circ_pct / 100.0
    st.markdown('</div>', unsafe_allow_html=True)

    MOCK = """{
    "Space_Requirement": [
        {"room": "Kitchen",      "net_area_sqm": 6.0}, {"room": "Dining",       "net_area_sqm": 6.0},
        {"room": "Bathroom",     "net_area_sqm": 3.0}, {"room": "Closet",       "net_area_sqm": 3.0},
        {"room": "Bedroom",      "net_area_sqm": 7.0}, {"room": "Living Area",  "net_area_sqm": 7.0}
    ],
    "Adjacency": [
        {"room1": "Kitchen", "room2": "Dining", "score": 3, "reason": "Serve food"},
        {"room1": "Bathroom","room2": "Closet", "score": 3, "reason": "Dressing area"}
    ],
    "Design_Concept": "Packed layout fitting exactly."
}"""

    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.subheader("📋 1. วาง AI Result JSON (Space & Adjacency)")
    user_json = st.text_area("⬇️ JSON output from Prompt A", value=MOCK, height=220)
    st.markdown('</div>', unsafe_allow_html=True)

    if st.button("✨ Generate Schematic Packed Plan", type="primary"):
        st.session_state.plan_generated = True

    if st.session_state.get("plan_generated", False):
        try:
            data = json.loads(user_json)
            df = pd.DataFrame(data["Space_Requirement"])
            clbl = f"Circulation_{circ_pct}%"
            df[clbl] = df["net_area_sqm"] * circ_factor
            df["Gross_sqm"] = df["net_area_sqm"] + df[clbl]
            rooms_list = df["room"].tolist()

            pal = {}; fi = 0
            for r in rooms_list:
                pal[r] = ROOM_PALETTE.get(r, FALLBACK[fi % len(FALLBACK)])
                if r not in ROOM_PALETTE: fi += 1

            SITE_W = st.session_state.get("site_width", 8.0)
            SITE_L = st.session_state.get("site_length", 4.0)
            SITE_AREA = SITE_W * SITE_L
            t_gross = df["Gross_sqm"].sum()
            scale_ratio = SITE_AREA / t_gross if t_gross > 0 else 1

            # ── 4. Schematic Packed Block Plan (Plotly Interactive) ──
            st.markdown("---")
            st.markdown("### 🟩 2. Schematic Packed Floor Plan  (100% Site Fit)")

            G = nx.Graph()
            for r in rooms_list: G.add_node(r)
            WM = {3:4.0, 2:2.5, 1:1.0, -1:0.02}
            if "Adjacency" in data:
                for adj in data["Adjacency"]:
                    r1,r2,sc = adj.get("room1"), adj.get("room2"), adj.get("score", 1)
                    if r1 in rooms_list and r2 in rooms_list:
                        G.add_edge(r1, r2, weight=WM.get(sc, 1.0))
            
            sp = nx.spring_layout(G, weight="weight", seed=42)
            sorted_rooms = sorted(rooms_list, key=lambda r: sp[r][1], reverse=True)
            items_to_pack = [(r, df.loc[df["room"]==r, "Gross_sqm"].values[0] * scale_ratio) for r in sorted_rooms]
            
            layout_rects = generate_treemap(items_to_pack, 0, 0, SITE_W, SITE_L)

            # ══════════════════════════════════════════════════════
            # 7. Import Openings + Furniture JSON
            # ══════════════════════════════════════════════════════
            st.markdown("---")
            st.markdown("### 🪑 3. Import Openings + Furniture JSON (Prompt B)")
            
            MOCK_OF = json.dumps({
                "Openings": [{"id":"D1","room":layout_rects[0]["room"],"wall":"south","offset_m":0.5,"width_m":0.9,"type":"door"}],
                "Furniture": [{"id":"F1","room":layout_rects[0]["room"],"type":"table","w_m":1.0,"d_m":0.6,"x_m":0.5,"y_m":0.5}],
                "Checks": {"overlaps":[],"clearance_violations":[],"door_swing_conflicts":[]}
            }, ensure_ascii=False, indent=2)

            of_json = st.text_area("⬇️ วาง Openings + Furniture JSON จาก AI", value=MOCK_OF, height=200, key="of_json")

            if st.button("🪑 Visualize Floor Plan with Clamping Math", type="primary"):
                try:
                    of_data = json.loads(of_json)
                    openings  = of_data.get("Openings", [])
                    furniture = of_data.get("Furniture", [])
                    checks    = of_data.get("Checks", {})

                    room_lookup = {rd["room"]: rd for rd in layout_rects}
                    fig_of = go.Figure()
                    pad_of = 0.04
                    
                    # วาดห้องจากพิกัด Slice and Dice
                    for rd in layout_rects:
                        rm, rx, ry, rw, rh = rd["room"], rd["x"], rd["y"], rd["w"], rd["h"]
                        fig_of.add_shape(
                            type="rect", x0=rx+pad_of, y0=ry+pad_of, x1=rx+rw-pad_of, y1=ry+rh-pad_of,
                            fillcolor=pal.get(rm, "#4E79A7"), opacity=0.35,
                            line=dict(color="#FFFFFF", width=1.5), layer="below",
                        )
                        fig_of.add_annotation(
                            x=rx+rw/2, y=ry+rh/2, text=rm, showarrow=False,
                            font=dict(size=10, color="#C8DCFF", family="Arial Black"),
                        )

                    # ── Draw Openings (ด้วยสมการคณิตศาสตร์จำกัดกรอบกำแพง) ──
                    OPEN_CLR = {"door":"#FF6B6B","window":"#4ECDC4","sliding":"#FFE66D","fixed":"#95E1D3"}
                    for op in openings:
                        rm = op.get("room","")
                        if rm not in room_lookup: continue
                        rd = room_lookup[rm]
                        wall = op.get("wall","south")
                        raw_off = op.get("offset_m", 0)
                        ow  = op.get("width_m", 0.9)
                        
                        # Mathematical Boundary Clamping สำหรับ Offset ของประตู/หน้าต่าง
                        wall_len = rd["w"] if wall in ["north", "south"] else rd["h"]
                        off = max(0, min(raw_off, wall_len - ow))

                        if wall == "south":   x0 = rd["x"] + off; y0 = rd["y"]; x1 = x0 + ow; y1 = y0
                        elif wall == "north": x0 = rd["x"] + off; y0 = rd["y"] + rd["h"]; x1 = x0 + ow; y1 = y0
                        elif wall == "west":  x0 = rd["x"]; y0 = rd["y"] + off; x1 = x0; y1 = y0 + ow
                        else:                 x0 = rd["x"] + rd["w"]; y0 = rd["y"] + off; x1 = x0; y1 = y0 + ow

                        fig_of.add_trace(go.Scatter(
                            x=[x0, x1], y=[y0, y1], mode="lines",
                            line=dict(color=OPEN_CLR.get(op.get("type","door"), "#FFFFFF"), width=6),
                            hovertext=f"<b>{op.get('id','')}</b><br>{rm} ({wall})",
                            hoverinfo="text", showlegend=False,
                        ))

                    # ── Draw Furniture (ด้วยสมการตรวจสอบ Coordinate + Bounding Box Clamping) ──
                    FURN_CLR = "#A78BFA"
                    auto_warnings = []
                    
                    for fi_item in furniture:
                        rm = fi_item.get("room","")
                        if rm not in room_lookup: continue
                        rd = room_lookup[rm]  # ดึงกรอบห้องจากผลลัพธ์ Slice and Dice
                        
                        raw_x = fi_item.get("x_m", 0)
                        raw_y = fi_item.get("y_m", 0)
                        fw = fi_item.get("w_m", 0.5)
                        fd = fi_item.get("d_m", 0.5)

                        # 1. Coordinate Detection System
                        # ตรวจสอบว่าพิกัดที่ AI ให้มาเป็น Absolute (เทียบขอบนอก) หรือ Relative (เทียบมุมห้อง)
                        is_absolute = (raw_x >= rd["w"] or raw_y >= rd["h"] or (raw_x >= rd["x"] and raw_x > 0))
                        
                        fx_init = raw_x if is_absolute else rd["x"] + raw_x
                        fy_init = raw_y if is_absolute else rd["y"] + raw_y

                        # ตรวจจับว่าถ้าใช้พิกัดเริ่มต้นแล้วล้นห้อง จะบันทึก Warning แจ้งผู้ใช้
                        if fx_init < rd["x"] or fy_init < rd["y"] or fx_init+fw > rd["x"]+rd["w"] or fy_init+fd > rd["y"]+rd["h"]:
                            auto_warnings.append(f"⚠️ {fi_item.get('id','')} ใน {rm} ให้พิกัดล้นขอบ ระบบใช้สมการ Clamping ดึงกลับเข้าห้องแล้ว")

                        # 2. Mathematical Bounding Box Clamping
                        # บังคับเฟอร์นิเจอร์ให้อยู่ใน Boundary ของ Slice & Dice 100%
                        fx = max(rd["x"], min(fx_init, rd["x"] + rd["w"] - fw))
                        fy = max(rd["y"], min(fy_init, rd["y"] + rd["h"] - fd))

                        fig_of.add_shape(
                            type="rect", x0=fx, y0=fy, x1=fx+fw, y1=fy+fd,
                            fillcolor=FURN_CLR, opacity=0.55,
                            line=dict(color="#FFFFFF", width=1),
                        )
                        fig_of.add_annotation(
                            x=fx+fw/2, y=fy+fd/2, text=f"{fi_item.get('id','')}<br>{fi_item.get('type','')}",
                            showarrow=False, font=dict(size=7, color="#E8F0FF"),
                        )

                    # กรอบ Site
                    fig_of.add_shape(
                        type="rect", x0=0, y0=0, x1=SITE_W, y1=SITE_L,
                        line=dict(color="#FFD700", width=3), fillcolor="rgba(0,0,0,0)",
                    )

                    fig_of.update_layout(
                        height=max(520, int(520*(SITE_L+1.5)/(SITE_W+1.5))),
                        plot_bgcolor="#0F1624", paper_bgcolor="#0F1624",
                        xaxis=dict(visible=False, range=[-0.5, SITE_W+0.5], scaleanchor="y", scaleratio=1),
                        yaxis=dict(visible=False, range=[-0.5, SITE_L+0.5]),
                        margin=dict(l=20,r=20,t=50,b=20),
                        title=dict(text="Furnished Plan with Math Clamping Constraints",
                            font=dict(size=13, color="#C8DCFF", family=THAI_FONT), x=0.5),
                        dragmode="pan",
                    )
                    st.plotly_chart(fig_of, width="stretch", config={"scrollZoom":True})

                    st.markdown("""
                    <div class="note">
                    <b>🧮 การทำงานของสมการแก้ปัญหาเฟอร์นิเจอร์ลอยออกนอกกรอบ:</b><br>
                    1. <b>Coordinate System Detection</b>: อัลกอริทึมจะตรวจสอบก่อนว่า AI คืนพิกัดเฟอร์นิเจอร์และหน้าต่างมาเป็นแบบ Absolute หรือ Relative.<br>
                    2. <b>Bounding Box Clamping</b>: ระบบจะใช้กรอบกว้างยาวของห้องที่ได้จากขั้นตอน <i>Slice and Dice</i> มาเป็น Constraint แม่ข่าย เพื่อเข้าสมการดึงพิกัดทั้งหมดให้อยู่ภายในห้องอย่างสมบูรณ์แบบโดยไม่ล้นออกไปนอกกำแพง.
                    </div>
                    """, unsafe_allow_html=True)

                    if auto_warnings:
                        st.warning("**🔧 Auto-Correction Triggered:**")
                        for w in auto_warnings: st.markdown(f"- {w}")

                except Exception as e2:
                    st.error(f"❌ Openings/Furniture JSON ไม่ถูกต้อง: {e2}")

        except Exception as e:
            st.error(f"❌ JSON ไม่ถูกต้อง หรือเกิดข้อผิดพลาด: {e}")
