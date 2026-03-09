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
  <p>Program Definition &rarr; AI Prompt &rarr; Adjacency Analysis &rarr; Relationship Graph &rarr; Packed Floor Plan</p>
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
ZONE_DARK   = {"Public":"#1B3A5C","Service":"#1B4030","Private":"#4A1B1B","Semi-Public":"#3A3000"}
ZONE_ACCENT = {"Public":"#4A9EE0","Service":"#3CC470","Private":"#E05C5C","Semi-Public":"#E0C040"}

# ── Thai font family for Plotly (browser-safe + Thai support) ──
THAI_FONT = "Tahoma, Segoe UI, sans-serif"

# ── Slice and Dice Algorithm (Treemap Packing) ────────────────
def generate_treemap(items, x, y, w, h):
    """แบ่งพื้นที่แบบ Slice and Dice ผ่าครึ่งตามสัดส่วนพื้นที่ (รับประกันเติมเต็ม 100%)"""
    if not items: return []
    if len(items) == 1: return [{'room': items[0][0], 'x': x, 'y': y, 'w': w, 'h': h}]
    
    tot_area = sum(i[1] for i in items)
    best_split, min_diff, acc = 1, float('inf'), 0
    
    # หาจุดตัดแบ่งกลุ่ม (Split point) ที่พื้นที่ใกล้เคียง 50:50 ที่สุด
    for i in range(1, len(items)):
        acc += items[i-1][1]
        diff = abs(acc - tot_area/2)
        if diff < min_diff:
            min_diff = diff
            best_split = i
            
    items1 = items[:best_split]
    items2 = items[best_split:]
    area1 = sum(i[1] for i in items1)
    
    # หั่นพื้นที่ฝั่งที่ยาวกว่า (Longest axis split)
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
                manual_areas[room] = st.number_input(
                    f"{room} (ตร.ม.)", value=DEFAULT_AREAS.get(room, 4.0),
                    min_value=1.0, max_value=100.0, step=0.5, key=f"m_{room}",
                )
        total_m = sum(manual_areas.values())
        site_a  = width * length
        pct     = (total_m / site_a * 100) if site_a > 0 else 0
        ca, cb, cc = st.columns(3)
        ca.metric("📐 Total Net",  f"{total_m:.1f} ตร.ม.")
        cb.metric("🏗️ Site Area",  f"{site_a:.1f} ตร.ม.")
        cc.metric("📊 Coverage",   f"{pct:.0f}%",
            delta="⚠️ เกิน Site!" if pct > 100 else "✅ OK",
            delta_color="inverse" if pct > 100 else "normal")
        st.markdown('</div>', unsafe_allow_html=True)

    if st.button("🚀 Generate AI Prompt", type="primary"):
        if not rooms:
            st.error("กรุณาเลือกห้องอย่างน้อย 1 ห้อง")
        else:
            payload = (
                [{"room":r,"net_area_sqm":manual_areas.get(r,DEFAULT_AREAS.get(r,4.0))} for r in rooms]
                if mode == "Manual (ผู้ใช้กำหนดเอง)" else "Auto-calculate"
            )
            prompt = {
                "system_prompt": "คุณคือสถาปนิกระดับ Senior หน้าที่ของคุณคือวิเคราะห์ข้อมูลและส่งกลับเป็น JSON เท่านั้น",
                "user_input": {
                    "project": project_type,
                    "site_dimension": f"{width} x {length} m (Total {width*length} sqm)",
                    "required_spaces": rooms, "sizing_mode": mode, "space_areas": payload,
                },
                "required_output_schema": {
                    "Space_Requirement": [{"room":"string","net_area_sqm":"float"}],
                    "Adjacency": [{"room1":"string","room2":"string",
                        "score":"int (3=ติดกัน,2=ใกล้,1=เฉยๆ,-1=แยก)","reason":"string"}],
                    "Design_Concept": "string",
                },
            }
            st.success("✅ คัดลอกข้อความด้านล่างนี้ไปวางใน Claude / ChatGPT")
            st.code(json.dumps(prompt, ensure_ascii=False, indent=4), language="json")

# ════════════════════════════════════════════════════════════════
# 📥  TAB 2
# ════════════════════════════════════════════════════════════════
with tab2:
    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.subheader("⚙️ Circulation Factor")
    cc1, cc2 = st.columns([1, 3])
    with cc1:
        circ_pct = st.number_input("Circulation (% Net Area)", min_value=0, max_value=100,
            value=0, step=5, help="แนะนำให้ปรับเป็น 0% หากต้องการให้ Site คุมสัดส่วนพื้นที่เอง")
    with cc2:
        st.info("💡 เนื่องจากใช้วิธี Pack Area พอดี Site ระบบจะแปลง Circulation เป็นตัวคูณ (Scaling Factor) เพื่อปรับสัดส่วนรวมให้พอดี")
    circ_factor = circ_pct / 100.0
    st.markdown('</div>', unsafe_allow_html=True)

    # JSON Input
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
    "Design_Concept": "Packed layout fitting exactly 8x4 meters site boundary. Front zone for Public/Service and Rear for Private rooms."
}"""

    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.subheader("📋 วาง AI Result JSON")
    user_json = st.text_area("⬇️ JSON output from Claude / ChatGPT", value=MOCK, height=220)
    st.markdown('</div>', unsafe_allow_html=True)

    if st.button("✨ Generate Schematic Packed Plan", type="primary"):
        try:
            data      = json.loads(user_json)
            df        = pd.DataFrame(data["Space_Requirement"])
            clbl      = f"Circulation_{circ_pct}%"
            df[clbl]          = df["net_area_sqm"] * circ_factor
            df["Gross_sqm"]   = df["net_area_sqm"] + df[clbl]
            rooms_list        = df["room"].tolist()

            pal = {}; fi = 0
            for r in rooms_list:
                pal[r] = ROOM_PALETTE.get(r, FALLBACK[fi % len(FALLBACK)])
                if r not in ROOM_PALETTE: fi += 1

            # ── 1. Space Table ─────────────────────────────────
            st.markdown("---")
            st.markdown("### 📊 1. Space Requirement")
            t_net   = df["net_area_sqm"].sum()
            t_gross = df["Gross_sqm"].sum()
            
            SITE_W = st.session_state.get("site_width",  8.0)
            SITE_L = st.session_state.get("site_length", 4.0)
            SITE_AREA = SITE_W * SITE_L

            m1, m2, m3, m4 = st.columns(4)
            m1.metric("📐 Net Area", f"{t_net:.2f} ตร.ม.")
            m2.metric("🏗️ Gross Area", f"{t_gross:.2f} ตร.ม.")
            m3.metric("🟩 Site Box", f"{SITE_AREA:.2f} ตร.ม.")
            
            # การคำนวณตัวคูณเพื่อเติมเต็ม Site พอดี
            scale_ratio = SITE_AREA / t_gross if t_gross > 0 else 1
            m4.metric("⚖️ Scaling Factor", f"x {scale_ratio:.2f}", 
                      help="สัดส่วนที่นำไปคูณเพื่อให้เต็มกรอบ Site พอดีเป๊ะ")

            st.dataframe(df.style.format("{:.2f}", subset=["net_area_sqm", clbl, "Gross_sqm"]),
                         use_container_width=True)

            # ── 2. Adjacency Matrix (Plotly Interactive Heatmap) ──
            st.markdown("---")
            st.markdown("### 🧮 2. Adjacency Matrix")
            mat = pd.DataFrame(0, index=rooms_list, columns=rooms_list)
            for adj in data["Adjacency"]:
                r1, r2, sc = adj["room1"], adj["room2"], adj["score"]
                if r1 in rooms_list and r2 in rooms_list:
                    mat.at[r1, r2] = sc; mat.at[r2, r1] = sc

            mat_values = mat.values.astype(float)
            
            # สร้าง hover text แสดงรายละเอียดคู่ห้อง
            hover_text = []
            for i, r_row in enumerate(rooms_list):
                row_hover = []
                for j, r_col in enumerate(rooms_list):
                    score = int(mat_values[i][j])
                    if score == 3:
                        label = "ต้องติดกัน (Must Adjacent)"
                    elif score == 2:
                        label = "ควรใกล้กัน (Should Near)"
                    elif score == 1:
                        label = "เฉยๆ (Neutral)"
                    elif score == -1:
                        label = "ควรแยก (Keep Apart)"
                    else:
                        label = "ไม่มีความสัมพันธ์"
                    # หา reason ถ้ามี
                    reason = ""
                    for a in data["Adjacency"]:
                        if (a["room1"] == r_row and a["room2"] == r_col) or \
                           (a["room1"] == r_col and a["room2"] == r_row):
                            reason = a.get("reason", "")
                            break
                    hover_str = (
                        f"<b>{r_row} ↔ {r_col}</b><br>"
                        f"Score: {score}<br>"
                        f"{label}"
                    )
                    if reason:
                        hover_str += f"<br>Reason: {reason}"
                    row_hover.append(hover_str)
                hover_text.append(row_hover)

            # สร้าง annotation text (ตัวเลข score)
            annotations = []
            for i, r_row in enumerate(rooms_list):
                for j, r_col in enumerate(rooms_list):
                    val = int(mat_values[i][j])
                    annotations.append(dict(
                        x=r_col, y=r_row,
                        text=str(val),
                        font=dict(color="white" if abs(val) >= 2 else "#C8DCFF", size=13, family=THAI_FONT),
                        showarrow=False,
                    ))

            # Plotly Heatmap — RdYlGn colorscale, center=0
            fig_h = go.Figure(data=go.Heatmap(
                z=mat_values,
                x=rooms_list,
                y=rooms_list,
                colorscale="RdYlGn",
                zmin=-1, zmax=3, zmid=0,
                hovertext=hover_text,
                hoverinfo="text",
                colorbar=dict(
                    title=dict(text="Adj. Score", font=dict(color="#A0B8D8", family=THAI_FONT)),
                    tickfont=dict(color="#A0B8D8"),
                    thickness=15,
                    len=0.8,
                ),
                xgap=2, ygap=2,
            ))
            fig_h.update_layout(
                title=dict(
                    text="Adjacency Matrix   (3 = ต้องติดกัน  ·  -1 = ควรแยก)",
                    font=dict(size=14, color="#C8DCFF", family=THAI_FONT),
                    x=0.5,
                ),
                annotations=annotations,
                height=500,
                plot_bgcolor="#0F1624",
                paper_bgcolor="#0F1624",
                xaxis=dict(
                    tickfont=dict(color="#A0B8D8", size=11, family=THAI_FONT),
                    side="bottom",
                    tickangle=-30,
                ),
                yaxis=dict(
                    tickfont=dict(color="#A0B8D8", size=11, family=THAI_FONT),
                    autorange="reversed",
                ),
                margin=dict(l=100, r=40, t=60, b=80),
            )
            st.plotly_chart(fig_h, use_container_width=True)

            # ── 3. Relationship Network Graph ──────────────────
            st.markdown("---")
            st.markdown("### 🕸️ 3. Relationship Network Graph")
            n       = len(rooms_list)
            angles  = [2*math.pi*i/n for i in range(n)]
            pn      = {r:(math.cos(a),math.sin(a)) for r,a in zip(rooms_list,angles)}
            ES = {
                 3: dict(c="#FF4D4D",w=5,  d="solid",l="Score 3 — must adjacent"),
                 2: dict(c="#FFD700",w=3,  d="solid",l="Score 2 — should be near"),
                 1: dict(c="#4CAF50",w=1.5,d="dot",  l="Score 1 — neutral"),
                -1: dict(c="#888888",w=1.5,d="dash", l="Score -1 — keep apart"),
            }
            fig_n = go.Figure(); dl = set()
            for adj in data["Adjacency"]:
                r1,r2,sc = adj["room1"],adj["room2"],adj["score"]
                if r1 not in pn or r2 not in pn: continue
                s=ES.get(sc,ES[1]); x0,y0=pn[r1]; x1,y1=pn[r2]; mx,my=(x0+x1)/2,(y0+y1)/2
                show=s["l"] not in dl; dl.add(s["l"])
                fig_n.add_trace(go.Scatter(x=[mx],y=[my],mode="markers",
                    marker=dict(size=10,color=s["c"],opacity=0),
                    hovertext=f"<b>{r1} ↔ {r2}</b><br>Score: {sc}<br>{adj.get('reason','')}",
                    hoverinfo="text",showlegend=False))
                fig_n.add_trace(go.Scatter(x=[x0,x1,None],y=[y0,y1,None],mode="lines",
                    line=dict(color=s["c"],width=s["w"],dash=s["d"]),
                    name=s["l"],legendgroup=s["l"],showlegend=show,hoverinfo="skip"))
            
            na=[df.loc[df["room"]==r,"net_area_sqm"].values[0] for r in rooms_list]
            fig_n.add_trace(go.Scatter(
                x=[pn[r][0] for r in rooms_list], y=[pn[r][1] for r in rooms_list],
                mode="markers+text",
                marker=dict(size=[max(44,a*7) for a in na],color=[pal[r] for r in rooms_list],
                    line=dict(color="white",width=2.5),opacity=0.92),
                text=rooms_list,textposition="middle center",
                textfont=dict(size=10,color="white",family="Arial Black"),
                hovertext=[f"<b>{r}</b><br>Net: {a:.1f} ตร.ม." for r,a in zip(rooms_list,na)],
                hoverinfo="text",showlegend=False,
            ))
            for r,a,(px_,py_) in zip(rooms_list,na,[pn[r] for r in rooms_list]):
                fig_n.add_annotation(x=px_,y=py_-0.19,text=f"{a:.0f} sqm",
                    showarrow=False,font=dict(size=8.5,color="#90B4D8"))
            fig_n.update_layout(
                height=520, plot_bgcolor="#0F1624", paper_bgcolor="#0F1624",
                margin=dict(l=20,r=20,t=50,b=20),
                xaxis=dict(visible=False,range=[-1.7,1.7]),
                yaxis=dict(visible=False,range=[-1.7,1.7],scaleanchor="x"),
                title=dict(text="Room Relationship Network  ·  hover edges for details",
                    font=dict(size=14,color="#C8DCFF"),x=0.5),
                legend=dict(title="Edge Type",orientation="h",yanchor="bottom",y=-0.07,
                    xanchor="center",x=0.5,font=dict(size=11,color="#A0B8D8"),
                    bgcolor="#141C2E",bordercolor="#1E2E4A"),
            )
            st.plotly_chart(fig_n, use_container_width=True)

            # ════════════════════════════════════════════════════════
            # 4. Schematic Packed Block Plan (Plotly Interactive)
            # ════════════════════════════════════════════════════════
            st.markdown("---")
            st.markdown("### 🟩 4. Schematic Packed Floor Plan  (100% Site Fit)")

            # Network Graph for 1D Ordering (Backend Process for Treemap)
            G = nx.Graph()
            for r in rooms_list: G.add_node(r)
            WM = {3:4.0, 2:2.5, 1:1.0, -1:0.02}
            for adj in data["Adjacency"]:
                r1,r2,sc = adj["room1"],adj["room2"],adj["score"]
                if r1 in rooms_list and r2 in rooms_list:
                    G.add_edge(r1, r2, weight=WM.get(sc, 1.0))
            
            # หาตำแหน่งด้วย Spring Layout เพื่อหาความสัมพันธ์ 1D
            sp = nx.spring_layout(G, weight="weight", seed=42)
            
            # เรียงลำดับห้องตามแกน Y (สมมติว่าเป็นแนวลึกของบ้าน)
            sorted_rooms = sorted(rooms_list, key=lambda r: sp[r][1], reverse=True)

            # เตรียม Data สำหรับ Treemap Slice & Dice
            items_to_pack = [(r, df.loc[df["room"]==r, "Gross_sqm"].values[0] * scale_ratio) for r in sorted_rooms]
            
            # เรียกใช้ Algorithm ผ่าพื้นที่
            layout_rects = generate_treemap(items_to_pack, 0, 0, SITE_W, SITE_L)

            # ── Draw with Plotly ──
            BG        = "#0F1624"
            ANNO_CLR  = "#FFD700"
            OUTER_PAD = max(SITE_W, SITE_L) * 0.15

            fig_bp = go.Figure()

            # เก็บตำแหน่งศูนย์กลางสำหรับวาดเส้นเชื่อม
            pos_packed = {}
            
            # วาดห้อง (Room Blocks) as shapes + invisible scatter for hover
            room_hover_x = []
            room_hover_y = []
            room_hover_text = []
            room_hover_colors = []
            room_labels_x = []
            room_labels_y = []
            room_labels_text = []
            room_area_x = []
            room_area_y = []
            room_area_text = []

            pad = 0.04
            for r_data in layout_rects:
                room = r_data['room']
                rx, ry, rw, rh = r_data['x'], r_data['y'], r_data['w'], r_data['h']
                cx, cy = rx + rw/2.0, ry + rh/2.0
                pos_packed[room] = [cx, cy]
                
                color = pal[room]
                zone = ZONE_MAP.get(room, "Private")
                scaled_area = rw * rh
                net_area = df.loc[df["room"]==room, "net_area_sqm"].values[0]
                gross_area = df.loc[df["room"]==room, "Gross_sqm"].values[0]
                
                # Room block shape (with padding)
                fig_bp.add_shape(
                    type="rect",
                    x0=rx + pad, y0=ry + pad,
                    x1=rx + rw - pad, y1=ry + rh - pad,
                    fillcolor=color,
                    opacity=0.92,
                    line=dict(color="#FFFFFF", width=2),
                    layer="below",
                )
                
                # Zone stripe
                stripe_h = min(rh * 0.15, 0.4)
                fig_bp.add_shape(
                    type="rect",
                    x0=rx + pad, y0=ry + rh - pad - stripe_h,
                    x1=rx + rw - pad, y1=ry + rh - pad,
                    fillcolor=ZONE_ACCENT.get(zone, "#555"),
                    opacity=0.40,
                    line=dict(width=0),
                    layer="below",
                )
                
                # Collect hover data
                room_hover_x.append(cx)
                room_hover_y.append(cy)
                room_hover_text.append(
                    f"<b>{room}</b><br>"
                    f"Zone: {zone}<br>"
                    f"Plan Area: {scaled_area:.1f} ตร.ม.<br>"
                    f"Net Area: {net_area:.1f} ตร.ม.<br>"
                    f"Gross Area: {gross_area:.1f} ตร.ม.<br>"
                    f"Dimensions: {rw:.2f} × {rh:.2f} ม."
                )
                room_hover_colors.append(color)
                
                # Labels
                room_labels_x.append(cx)
                room_labels_y.append(cy + rh * 0.08)
                room_labels_text.append(room)
                room_area_x.append(cx)
                room_area_y.append(cy - rh * 0.12)
                room_area_text.append(f"Plan Area: {scaled_area:.1f} ตร.ม.")

            # Invisible scatter for hover interaction on rooms
            fig_bp.add_trace(go.Scatter(
                x=room_hover_x, y=room_hover_y,
                mode="markers",
                marker=dict(size=35, color=room_hover_colors, opacity=0),
                hovertext=room_hover_text,
                hoverinfo="text",
                showlegend=False,
                name="Rooms",
            ))

            # Room name labels
            fig_bp.add_trace(go.Scatter(
                x=room_labels_x, y=room_labels_y,
                mode="text",
                text=room_labels_text,
                textfont=dict(size=12, color="white", family="Arial Black"),
                hoverinfo="skip",
                showlegend=False,
            ))

            # Area labels
            fig_bp.add_trace(go.Scatter(
                x=room_area_x, y=room_area_y,
                mode="text",
                text=room_area_text,
                textfont=dict(size=9, color="#E8F0FF", family=THAI_FONT),
                hoverinfo="skip",
                showlegend=False,
            ))

            # ── วาดเส้นความสัมพันธ์ (Adjacency overlay) ──
            ADJ_S = {
                 3: dict(c="#FF4D4D", w=3.0, d="solid", a=0.9),
                 2: dict(c="#FFD700", w=2.0, d="solid", a=0.8),
                 1: dict(c="#4CAF50", w=1.5, d="dot",   a=0.6),
                -1: dict(c="#000000", w=2.0, d="dash",  a=0.5),
            }
            
            legend_added = set()
            for adj in data["Adjacency"]:
                r1, r2, sc = adj["room1"], adj["room2"], adj["score"]
                if r1 in pos_packed and r2 in pos_packed:
                    s = ADJ_S.get(sc, ADJ_S[1])
                    x1_, y1_ = pos_packed[r1]
                    x2_, y2_ = pos_packed[r2]
                    mx_, my_ = (x1_ + x2_) / 2, (y1_ + y2_) / 2
                    
                    score_label = f"Score {sc}"
                    show_legend = score_label not in legend_added
                    legend_added.add(score_label)
                    
                    # Edge line
                    fig_bp.add_trace(go.Scatter(
                        x=[x1_, x2_], y=[y1_, y2_],
                        mode="lines",
                        line=dict(color=s["c"], width=s["w"], dash=s["d"]),
                        opacity=s["a"],
                        name=score_label,
                        legendgroup=score_label,
                        showlegend=show_legend,
                        hoverinfo="skip",
                    ))
                    
                    # Score label at midpoint
                    fig_bp.add_trace(go.Scatter(
                        x=[mx_], y=[my_],
                        mode="markers+text",
                        marker=dict(size=18, color=BG, line=dict(color=s["c"], width=1.5)),
                        text=[str(sc)],
                        textfont=dict(size=9, color=s["c"], family="Arial Black"),
                        textposition="middle center",
                        hovertext=f"<b>{r1} ↔ {r2}</b><br>Score: {sc}<br>{adj.get('reason', '')}",
                        hoverinfo="text",
                        showlegend=False,
                    ))

            # Site boundary rectangle
            fig_bp.add_shape(
                type="rect",
                x0=0, y0=0, x1=SITE_W, y1=SITE_L,
                line=dict(color=ANNO_CLR, width=4),
                fillcolor="rgba(0,0,0,0)",
            )

            # Dimension annotations
            # Width arrow (bottom)
            fig_bp.add_annotation(
                x=SITE_W / 2, y=-OUTER_PAD * 0.35,
                text=f"Width: {SITE_W:.1f} ม.",
                showarrow=False,
                font=dict(size=13, color=ANNO_CLR, family=THAI_FONT),
            )
            fig_bp.add_shape(
                type="line", x0=0, y0=-OUTER_PAD*0.28, x1=SITE_W, y1=-OUTER_PAD*0.28,
                line=dict(color=ANNO_CLR, width=2),
            )
            # Width arrow heads
            fig_bp.add_annotation(
                x=0, y=-OUTER_PAD*0.28, ax=0.15, ay=-OUTER_PAD*0.28,
                xref="x", yref="y", axref="x", ayref="y",
                showarrow=True, arrowhead=2, arrowsize=1.5, arrowcolor=ANNO_CLR, arrowwidth=2,
                text="",
            )
            fig_bp.add_annotation(
                x=SITE_W, y=-OUTER_PAD*0.28, ax=SITE_W-0.15, ay=-OUTER_PAD*0.28,
                xref="x", yref="y", axref="x", ayref="y",
                showarrow=True, arrowhead=2, arrowsize=1.5, arrowcolor=ANNO_CLR, arrowwidth=2,
                text="",
            )

            # Length arrow (left)
            fig_bp.add_annotation(
                x=-OUTER_PAD * 0.45, y=SITE_L / 2,
                text=f"Length: {SITE_L:.1f} ม.",
                showarrow=False,
                font=dict(size=13, color=ANNO_CLR, family=THAI_FONT),
                textangle=-90,
            )
            fig_bp.add_shape(
                type="line", x0=-OUTER_PAD*0.28, y0=0, x1=-OUTER_PAD*0.28, y1=SITE_L,
                line=dict(color=ANNO_CLR, width=2),
            )
            # Length arrow heads
            fig_bp.add_annotation(
                x=-OUTER_PAD*0.28, y=0, ax=-OUTER_PAD*0.28, ay=0.1,
                xref="x", yref="y", axref="x", ayref="y",
                showarrow=True, arrowhead=2, arrowsize=1.5, arrowcolor=ANNO_CLR, arrowwidth=2,
                text="",
            )
            fig_bp.add_annotation(
                x=-OUTER_PAD*0.28, y=SITE_L, ax=-OUTER_PAD*0.28, ay=SITE_L-0.1,
                xref="x", yref="y", axref="x", ayref="y",
                showarrow=True, arrowhead=2, arrowsize=1.5, arrowcolor=ANNO_CLR, arrowwidth=2,
                text="",
            )

            # Layout
            fig_bp.update_layout(
                height=max(500, int(500 * (SITE_L + 2*OUTER_PAD) / (SITE_W + 2*OUTER_PAD))),
                plot_bgcolor=BG,
                paper_bgcolor=BG,
                xaxis=dict(
                    visible=False,
                    range=[-OUTER_PAD, SITE_W + OUTER_PAD],
                    scaleanchor="y",
                    scaleratio=1,
                ),
                yaxis=dict(
                    visible=False,
                    range=[-OUTER_PAD, SITE_L + OUTER_PAD],
                ),
                margin=dict(l=20, r=20, t=40, b=20),
                title=dict(
                    text="Schematic Block Plan  ·  drag to pan / scroll to zoom / hover for details",
                    font=dict(size=13, color="#C8DCFF", family=THAI_FONT),
                    x=0.5,
                ),
                legend=dict(
                    title="Adjacency",
                    orientation="h", yanchor="bottom", y=-0.08,
                    xanchor="center", x=0.5,
                    font=dict(size=11, color="#A0B8D8"),
                    bgcolor="#141C2E", bordercolor="#1E2E4A",
                ),
                dragmode="pan",
            )
            # Default to pan mode with scroll zoom enabled
            st.plotly_chart(fig_bp, use_container_width=True, config={
                "scrollZoom": True,
                "displayModeBar": True,
                "modeBarButtonsToAdd": ["zoom2d", "pan2d", "resetScale2d"],
            })

            st.markdown(f"""
<div class="note">
<b>📐 หลักการ Packed Block Plan:</b><br>
<b>① Scaling</b> — ปรับขนาดพื้นที่ทุกห้องตามสัดส่วน (Ratio) เพื่อให้ผลรวมพอดีกับกรอบ <b>{SITE_W:.1f} × {SITE_L:.1f} ม.</b> (100% Fit).<br>
<b>② Adjacency Ordering</b> — วิเคราะห์ Network Graph เพื่อดึงห้องที่เชื่อมต่อกันมาเรียงลำดับแนวแกน.<br>
<b>③ Slice and Dice Algorithm</b> — ผ่าแบ่งกรอบสี่เหลี่ยมสลับแนวตั้ง/แนวนอนตามสัดส่วนพื้นที่ห้อง (Treemap) ทำให้ไม่เกิดพื้นที่เสียเปล่า (Zero Gaps).<br>
<b>④ Network Overlay</b> — เส้นและตัวเลขแสดง Adjacency Score จริงที่วางทาบลงบนแปลน.
</div>
""", unsafe_allow_html=True)

            # ── 5. Design Concept ──────────────────────────────
            st.markdown("---")
            st.markdown("### 🧠 5. AI Design Concept")
            st.markdown(f"""
<div style="background:linear-gradient(135deg,#0D1B35,#1A2E55); border:1px solid #1E3A6E;border-radius:14px; padding:22px 28px;color:#C0D8F0;font-size:0.97rem;line-height:1.75;">
  💡 {data["Design_Concept"]}
</div>
""", unsafe_allow_html=True)

        except Exception as e:
            st.error(f"❌ JSON ไม่ถูกต้อง หรือเกิดข้อผิดพลาด: {e}")
