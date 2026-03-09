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

# ── Bezier Curve Generator for Premium UI ────────────────────
def get_bezier_curve(p0, p2, offset_ratio=0.15, num_points=30):
    p0 = np.array(p0)
    p2 = np.array(p2)
    dist = np.linalg.norm(p2 - p0)
    if dist == 0: return [p0[0]], [p0[1]]
    
    mid = (p0 + p2) / 2.0
    d = p2 - p0
    normal = np.array([-d[1], d[0]])
    normal = normal / np.linalg.norm(normal)
    
    # สลับทิศทางความโค้งตามผลรวมของพิกัด เพื่อให้เส้นไขว้กันดูมีมิติ
    direction = 1 if (p0[0] + p0[1]) % 2 > 1 else -1
    p1 = mid + normal * (dist * offset_ratio * direction)
    
    t = np.linspace(0, 1, num_points)
    curve = np.outer((1-t)**2, p0) + np.outer(2*(1-t)*t, p1) + np.outer(t**2, p2)
    return curve[:, 0], curve[:, 1]


# ══════════════════════════════════════════
# 🗂️  Tabs
# ══════════════════════════════════════════
tab1, tab2, tab3 = st.tabs([
    "📤  1. USER INPUT & PROMPT A",
    "📥  2. IMPORT JSON & PACKED PLAN",
    "🪑  3. PROMPT B & FINAL PRODUCT"
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
            st.success("✅ **Prompt A — Packed Plan**: คัดลอกข้อความด้านล่างนี้ไปวางใน Claude / ChatGPT เพื่อรับข้อมูลการจัดโซนห้อง (สำหรับใช้งานใน Tab 2)")
            st.code(json.dumps(prompt, ensure_ascii=False, indent=4), language="json")


# ════════════════════════════════════════════════════════════════
# รับ Input พื้นฐานสำหรับ Tab 2
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
    st.subheader("📋 วาง AI Result JSON (Prompt A)")
    user_json = st.text_area("⬇️ JSON output from Claude / ChatGPT", value=MOCK, height=220)
    st.markdown('</div>', unsafe_allow_html=True)

    if st.button("✨ Generate Schematic Packed Plan", type="primary"):
        st.session_state.plan_generated = True

# ════════════════════════════════════════════════════════════════
# ระบบประมวลผลข้อมูลร่วมสำหรับ Tab 2 และ Tab 3
# ════════════════════════════════════════════════════════════════
if st.session_state.get("plan_generated", False):
    try:
        data      = json.loads(user_json)
        if "Space_Requirement" not in data:
            st.error("❌ ข้อผิดพลาด: ไม่พบคีย์ 'Space_Requirement' ใน JSON ที่คุณวาง\n\n💡 ดูเหมือนว่าคุณกำลังนำ JSON ผลลัพธ์ของ Openings + Furniture มาวางผิดที่ กรุณาไปที่ Tab 3 แทนครับ")
            st.stop()
            
        df        = pd.DataFrame(data["Space_Requirement"])
        clbl      = f"Circulation_{circ_pct}%"
        df[clbl]          = df["net_area_sqm"] * circ_factor
        df["Gross_sqm"]   = df["net_area_sqm"] + df[clbl]
        rooms_list        = df["room"].tolist()

        pal = {}; fi = 0
        for r in rooms_list:
            pal[r] = ROOM_PALETTE.get(r, FALLBACK[fi % len(FALLBACK)])
            if r not in ROOM_PALETTE: fi += 1

        t_net   = df["net_area_sqm"].sum()
        t_gross = df["Gross_sqm"].sum()
        
        SITE_W = st.session_state.get("site_width",  8.0)
        SITE_L = st.session_state.get("site_length", 4.0)
        SITE_AREA = SITE_W * SITE_L
        scale_ratio = SITE_AREA / t_gross if t_gross > 0 else 1

        # Calculate Layout Rectangles
        G = nx.Graph()
        for r in rooms_list: G.add_node(r)
        WM = {3:4.0, 2:2.5, 1:1.0, -1:0.02}
        for adj in data["Adjacency"]:
            r1,r2,sc = adj["room1"],adj["room2"],adj["score"]
            if r1 in rooms_list and r2 in rooms_list:
                G.add_edge(r1, r2, weight=WM.get(sc, 1.0))
        sp = nx.spring_layout(G, weight="weight", seed=42)
        sorted_rooms = sorted(rooms_list, key=lambda r: sp[r][1], reverse=True)
        items_to_pack = [(r, df.loc[df["room"]==r, "Gross_sqm"].values[0] * scale_ratio) for r in sorted_rooms]
        layout_rects = generate_treemap(items_to_pack, 0, 0, SITE_W, SITE_L)

        # Build room lookup
        room_lookup = {}
        for rd in layout_rects:
            room_lookup[rd["room"]] = rd

        # ── Render TAB 2 ──
        with tab2:
            st.markdown("---")
            st.markdown("### 📊 1. Space Requirement")
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("📐 Net Area", f"{t_net:.2f} ตร.ม.")
            m2.metric("🏗️ Gross Area", f"{t_gross:.2f} ตร.ม.")
            m3.metric("🟩 Site Box", f"{SITE_AREA:.2f} ตร.ม.")
            m4.metric("⚖️ Scaling Factor", f"x {scale_ratio:.2f}", help="สัดส่วนที่นำไปคูณเพื่อให้เต็มกรอบ Site พอดีเป๊ะ")

            st.dataframe(df.style.format("{:.2f}", subset=["net_area_sqm", clbl, "Gross_sqm"]), width="stretch")

            # 2. Adjacency Matrix
            st.markdown("---")
            st.markdown("### 🧮 2. Adjacency Matrix")
            mat = pd.DataFrame(0, index=rooms_list, columns=rooms_list)
            for adj in data["Adjacency"]:
                r1, r2, sc = adj["room1"], adj["room2"], adj["score"]
                if r1 in rooms_list and r2 in rooms_list:
                    mat.at[r1, r2] = sc; mat.at[r2, r1] = sc
            mat_values = mat.values.astype(float)
            
            hover_text = []
            for i, r_row in enumerate(rooms_list):
                row_hover = []
                for j, r_col in enumerate(rooms_list):
                    score = int(mat_values[i][j])
                    label = {3:"ต้องติดกัน", 2:"ควรใกล้กัน", 1:"เฉยๆ", -1:"ควรแยก"}.get(score, "ไม่มีความสัมพันธ์")
                    reason = ""
                    for a in data["Adjacency"]:
                        if (a["room1"] == r_row and a["room2"] == r_col) or (a["room1"] == r_col and a["room2"] == r_row):
                            reason = a.get("reason", "")
                            break
                    row_hover.append(f"<b>{r_row} ↔ {r_col}</b><br>Score: {score}<br>{label}<br>Reason: {reason}")
                hover_text.append(row_hover)

            annotations = []
            for i, r_row in enumerate(rooms_list):
                for j, r_col in enumerate(rooms_list):
                    val = int(mat_values[i][j])
                    annotations.append(dict(x=r_col, y=r_row, text=str(val), font=dict(color="white" if abs(val) >= 2 else "#C8DCFF", size=13, family=THAI_FONT), showarrow=False))

            fig_h = go.Figure(data=go.Heatmap(
                z=mat_values, x=rooms_list, y=rooms_list, colorscale="RdYlGn", zmin=-1, zmax=3, zmid=0,
                hovertext=hover_text, hoverinfo="text", colorbar=dict(thickness=15, len=0.8), xgap=2, ygap=2
            ))
            fig_h.update_layout(title=dict(text="Adjacency Matrix", font=dict(size=14, color="#C8DCFF", family=THAI_FONT), x=0.5), annotations=annotations, height=500, plot_bgcolor="#0F1624", paper_bgcolor="#0F1624")
            st.plotly_chart(fig_h, width="stretch")

            # 3. Relationship Network Graph
            st.markdown("---")
            st.markdown("### 🕸️ 3. Relationship Network Graph")
            n = len(rooms_list); angles = [2*math.pi*i/n for i in range(n)]
            pn = {r:(math.cos(a),math.sin(a)) for r,a in zip(rooms_list,angles)}
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
                fig_n.add_trace(go.Scatter(x=[x0,x1,None],y=[y0,y1,None],mode="lines",
                    line=dict(color=s["c"],width=s["w"],dash=s["d"]), name=s["l"],legendgroup=s["l"],showlegend=show,hoverinfo="skip"))
            
            na=[df.loc[df["room"]==r,"net_area_sqm"].values[0] for r in rooms_list]
            fig_n.add_trace(go.Scatter(x=[pn[r][0] for r in rooms_list], y=[pn[r][1] for r in rooms_list],
                mode="markers+text", marker=dict(size=[max(44,a*7) for a in na],color=[pal[r] for r in rooms_list],line=dict(color="white",width=2.5)),
                text=rooms_list,textfont=dict(size=10,color="white",family="Arial Black"), hoverinfo="text",showlegend=False))
            fig_n.update_layout(height=520, plot_bgcolor="#0F1624", paper_bgcolor="#0F1624", xaxis=dict(visible=False), yaxis=dict(visible=False))
            st.plotly_chart(fig_n, width="stretch")

            # 4. Schematic Packed Block Plan (Commercial Grade)
            st.markdown("---")
            st.markdown("### 🟩 4. Schematic Packed Floor Plan (Commercial Grade)")
            
            show_adj_overlay = st.toggle("✨ Premium Adjacency Overlay", value=True, help="แสดงความสัมพันธ์ด้วยเส้นโค้ง Bezier และเอฟเฟกต์ Neon Glow")

            BG = "#0F1624"; ANNO_CLR = "#FFD700"; OUTER_PAD = max(SITE_W, SITE_L) * 0.15
            fig_bp = go.Figure()
            pos_packed = {}
            
            pad = 0.04
            room_opacity = 0.35 if show_adj_overlay else 0.92 
            
            # --- LAYER 1: ฐานของห้อง (Rectangles) ---
            for r_data in layout_rects:
                room, rx, ry, rw, rh = r_data['room'], r_data['x'], r_data['y'], r_data['w'], r_data['h']
                cx, cy = rx + rw/2.0, ry + rh/2.0
                pos_packed[room] = [cx, cy]
                color = pal[room]
                
                # วาดพื้นหลังห้อง
                fig_bp.add_shape(type="rect", x0=rx+pad, y0=ry+pad, x1=rx+rw-pad, y1=ry+rh-pad, 
                                 fillcolor=color, opacity=room_opacity, line=dict(color="#FFFFFF", width=1.5), layer="below")

            # --- LAYER 2: เส้นความสัมพันธ์ (Bezier Curves) ---
            met_rules = []
            broken_rules = []

            def check_adjacency(r1_name, r2_name, tol=0.1):
                r1 = room_lookup.get(r1_name); r2 = room_lookup.get(r2_name)
                if not r1 or not r2: return False
                return not (r1['x'] > r2['x'] + r2['w'] + tol or r1['x'] + r1['w'] < r2['x'] - tol or
                            r1['y'] > r2['y'] + r2['h'] + tol or r1['y'] + r1['h'] < r2['y'] - tol)

            if show_adj_overlay:
                for adj in data.get("Adjacency", []):
                    r1, r2, sc = adj.get("room1"), adj.get("room2"), adj.get("score", 0)
                    reason = adj.get("reason", "")
                    
                    if r1 in pos_packed and r2 in pos_packed and sc >= 2:
                        is_adj = check_adjacency(r1, r2)
                        status_text = "✅ (ติดกันตามแผน)" if is_adj else "⚠️ (ถูกแยกด้วย Treemap)"
                        
                        if is_adj: met_rules.append(f"**{r1} ↔ {r2}** (Score {sc}): {reason}")
                        else: broken_rules.append(f"**{r1} ↔ {r2}** (Score {sc}): {reason}")
                        
                        x0, y0 = pos_packed[r1]
                        x1, y1 = pos_packed[r2]
                        
                        line_color = "#FF4D4D" if sc == 3 else "#FFD700"
                        hover_text = f"<b>{r1} ↔ {r2}</b><br>Score: {sc}<br>Reason: {reason}<br>Status: {status_text}"
                        
                        # สร้างเส้นโค้ง Bezier
                        bx, by = get_bezier_curve([x0, y0], [x1, y1], offset_ratio=0.12)
                        
                        # กวาดเส้นเงาสีดำหนาๆ (Outer Glow / Shadow) ลงในเลเยอร์ล่าง
                        fig_bp.add_trace(go.Scatter(
                            x=bx, y=by, mode="lines",
                            line=dict(color="#0F1624", width=8), 
                            hoverinfo="skip", showlegend=False
                        ))
                        # วาดเส้นเรืองแสงตรงกลาง (Core Line)
                        fig_bp.add_trace(go.Scatter(
                            x=bx, y=by, mode="lines",
                            line=dict(color=line_color, width=3.5 if sc==3 else 2.5, dash="solid" if sc==3 else "dot"),
                            hoverinfo="text", hovertext=hover_text, showlegend=False
                        ))

            # --- LAYER 3: จุดเชื่อมต่อ (Nodes) ---
            if show_adj_overlay:
                node_x = [pos_packed[r][0] for r in pos_packed]
                node_y = [pos_packed[r][1] for r in pos_packed]
                # วาด Node วงกลมสมบูรณ์แบบ ทับเส้นทั้งหมด
                fig_bp.add_trace(go.Scatter(
                    x=node_x, y=node_y, mode="markers",
                    marker=dict(size=14, color="#0F1624", line=dict(color="#FFFFFF", width=2.5)),
                    hoverinfo="skip", showlegend=False
                ))

            # --- LAYER 4: ข้อความ (Text Labels) ---
            for r_data in layout_rects:
                room, cx, cy, rh = r_data['room'], r_data['x']+r_data['w']/2.0, r_data['y']+r_data['h']/2.0, r_data['h']
                fig_bp.add_trace(go.Scatter(
                    x=[cx], y=[cy+rh*0.14], mode="text", text=[room], 
                    textfont=dict(size=13, color="white", family="Arial Black"), 
                    showlegend=False, hoverinfo="skip"
                ))

            # ตีกรอบเหลืองรอบ Site
            fig_bp.add_shape(type="rect", x0=0, y0=0, x1=SITE_W, y1=SITE_L, line=dict(color=ANNO_CLR, width=3), fillcolor="rgba(0,0,0,0)", layer="above")
            
            fig_bp.update_layout(height=max(500, int(500*(SITE_L+2*OUTER_PAD)/(SITE_W+2*OUTER_PAD))), plot_bgcolor=BG, paper_bgcolor=BG, xaxis=dict(visible=False, scaleanchor="y", scaleratio=1), yaxis=dict(visible=False), margin=dict(l=20, r=20, t=40, b=20))
            st.plotly_chart(fig_bp, width="stretch", config={"scrollZoom": True})

            if met_rules or broken_rules:
                c1, c2 = st.columns(2)
                with c1: st.success("**✅ ความสัมพันธ์ที่จัดได้สำเร็จ:**\n" + ("\n".join([f"- {m}" for m in met_rules]) if met_rules else "\n- ไม่มี"))
                with c2: st.warning("**⚠️ ความสัมพันธ์ที่ถูกบีบให้แยกกัน:**\n" + ("\n".join([f"- {b}" for b in broken_rules]) if broken_rules else "\n- ไม่มี"))

            # 5. Design Concept
            st.markdown("---")
            st.markdown("### 🧠 5. AI Design Concept")
            st.info(f"💡 {data.get('Design_Concept', '')}")

            st.success("✅ **สร้าง Packed Plan สำเร็จ!** ไปที่แท็บ **'🪑 3. PROMPT B & FINAL PRODUCT'** เพื่อใส่ประตู หน้าต่าง และเฟอร์นิเจอร์ต่อได้เลยครับ")


        # ── Render TAB 3 ──
        with tab3:
            st.markdown("### 🚪 6. AI Prompt — Openings + Furniture")
            st.markdown('<div class="note"><b>💡 Two-Stage AI Flow:</b> คัดลอก Prompt ด้านล่างไปส่งให้ AI อีกรอบ เพื่อได้ช่องเปิด + เฟอร์นิเจอร์ที่ลงตัวตามพิกัดห้อง</div>', unsafe_allow_html=True)

            packed_plan_for_prompt = []
            for rd in layout_rects:
                packed_plan_for_prompt.append({
                    "room": rd["room"], "x": round(rd["x"], 3), "y": round(rd["y"], 3),
                    "w": round(rd["w"], 3), "h": round(rd["h"], 3), "orientation_deg": 0.0,
                })
            auto_prompt_b = {
                "system_prompt": "คุณคือสถาปนิกระดับ Senior และผู้เชี่ยวชาญด้าน Space Planning ที่แม่นยำทางคณิตศาสตร์ — ตอบกลับเป็น JSON เท่านั้น ห้ามมีข้อความอื่นนอกกรอบ JSON",
                "user_prompt": "รับข้อมูล 'Packed_Plan' (สี่เหลี่ยมจัดสรรพื้นที่) — คืนค่า Openings (ประตู/หน้าต่าง) และ Furniture placement โดยต้องทำตามกฎพิกัด Local Coordinates และ Mathematical Bounding อย่างเคร่งครัด",
                "strict_mathematical_rules": {
                    "1_coordinate_system": {"type": "Local / Relative Coordinates", "rule": "พิกัด x_m และ y_m ของเฟอร์นิเจอร์ทุกชิ้น จะต้องเริ่มต้นที่ (0,0) ซึ่งหมายถึง 'มุมซ้ายล่างของห้องนั้นๆ' เสมอ (ห้ามใช้พิกัด Absolute ของทั้งไซต์งาน)"},
                    "2_furniture_bounding_box": {"rule": "เฟอร์นิเจอร์ต้องไม่ล้นออกนอกขอบเขตห้อง (Slice and Dice Bounding) โดยต้องเป็นไปตามสมการนี้:", "x_axis_clamp": "0 <= x_m <= (Room_w - Furniture_w)", "y_axis_clamp": "0 <= y_m <= (Room_h - Furniture_d)"},
                    "3_openings_bounding": {"rule": "ตำแหน่ง offset_m ของประตูและหน้าต่างต้องไม่เกินความกว้างหรือยาวของกำแพงห้อง", "north_south_walls": "0 <= offset_m <= (Room_w - Opening_width)", "east_west_walls": "0 <= offset_m <= (Room_h - Opening_width)"},
                    "4_clearance_overlap": {"rule": "ตรวจสอบ clearance_m ของเฟอร์นิเจอร์แต่ละชิ้น ไม่ให้ทับซ้อน (Overlap) กับระยะเดินหรือสวิงประตู (Door Swing) ภายใน Local Room นั้นๆ"}
                },
                "constraints_data": {"walkway_clearance_m": 0.6, "seating_clearance_m": 0.8, "bed_clearance_m": 0.5, "door_min_width_m": 0.8, "window_min_width_m": 0.6},
                "Packed_Plan": packed_plan_for_prompt,
                "metadata": {"site_width_m": SITE_W, "site_length_m": SITE_L, "scale_factor": round(scale_ratio, 4)},
                "required_output_schema": {
                    "Openings": [{"id": "string", "room": "string", "wall": "string (north|south|east|west)", "offset_m": "float (relative to wall start)", "width_m": "float", "height_m": "float", "sill_height_m": "float", "type": "string (window|door|sliding|fixed)"}],
                    "Furniture": [{"id": "string", "room": "string", "type": "string", "w_m": "float", "d_m": "float", "h_m": "float", "x_m": "float (Local coordinate X)", "y_m": "float (Local coordinate Y)", "orientation_deg": "float (0, 90, 180, 270)", "clearance_m": "float", "placement_mode": "string (wall-mounted|free|corner|island)"}],
                    "Checks": {"overlaps": ["array of structural violations"], "clearance_violations": ["array of clearance issues"], "door_swing_conflicts": ["array of swing issues"]}
                }
            }
            st.code(json.dumps(auto_prompt_b, ensure_ascii=False, indent=4), language="json")

            # 7. Import Openings + Furniture JSON
            st.markdown("---")
            st.markdown("### 🪑 7. Import Openings + Furniture (AI Result)")

            MOCK_OF = json.dumps({
                "Openings": [
                    {"id":"D1","room":layout_rects[0]["room"],"wall":"south","offset_m":0.5,"width_m":0.9,"height_m":2.1,"sill_height_m":0.0,"type":"door"},
                    {"id":"W1","room":layout_rects[-1]["room"],"wall":"north","offset_m":1.0,"width_m":1.2,"height_m":1.2,"sill_height_m":0.9,"type":"window"},
                ],
                "Furniture": [
                    {"id":"F1","room":layout_rects[0]["room"],"type":"table","w_m":1.0,"d_m":0.6,"h_m":0.75,"x_m":0.3,"y_m":0.3,"orientation_deg":0,"clearance_m":0.6,"placement_mode":"free"},
                ],
                "Checks": {"overlaps":[],"clearance_violations":[],"door_swing_conflicts":[]},
            }, ensure_ascii=False, indent=2)

            of_json = st.text_area("⬇️ วาง Openings + Furniture JSON จาก AI (Prompt B)", value=MOCK_OF, height=200, key="of_json")

            if st.button("🪑 Visualize Openings + Furniture", type="primary"):
                try:
                    of_data = json.loads(of_json)
                    if "Openings" not in of_data and "Furniture" not in of_data:
                        st.error("❌ ข้อผิดพลาด: ไม่พบคีย์ 'Openings' หรือ 'Furniture' กรุณาตรวจสอบว่าไม่ได้นำ JSON ของ Space Requirement มาวางผิดช่อง")
                        st.stop()
                        
                    openings  = of_data.get("Openings", [])
                    furniture = of_data.get("Furniture", [])
                    checks    = of_data.get("Checks", {})

                    fig_of = go.Figure()
                    pad_of = 0.04
                    for rd in layout_rects:
                        rm, rx, ry, rw, rh = rd["room"], rd["x"], rd["y"], rd["w"], rd["h"]
                        fig_of.add_shape(type="rect", x0=rx+pad_of, y0=ry+pad_of, x1=rx+rw-pad_of, y1=ry+rh-pad_of, fillcolor=pal.get(rm, "#4E79A7"), opacity=0.35, line=dict(color="#FFFFFF", width=1.5), layer="below")
                        fig_of.add_annotation(x=rx+rw/2, y=ry+rh/2, text=rm, showarrow=False, font=dict(size=10, color="#C8DCFF", family="Arial Black"))

                    # Draw Openings
                    OPEN_CLR = {"door":"#FF6B6B","window":"#4ECDC4","sliding":"#FFE66D","fixed":"#95E1D3"}
                    for op in openings:
                        rm = op.get("room","")
                        if rm not in room_lookup: continue
                        rd = room_lookup[rm]; wall = op.get("wall","south"); off = op.get("offset_m", 0); ow  = op.get("width_m", 0.9)
                        ot  = op.get("type","door"); clr = OPEN_CLR.get(ot, "#FFFFFF")

                        if wall == "south": x0 = rd["x"] + off; y0 = rd["y"]; x1 = x0 + ow; y1 = y0
                        elif wall == "north": x0 = rd["x"] + off; y0 = rd["y"] + rd["h"]; x1 = x0 + ow; y1 = y0
                        elif wall == "west": x0 = rd["x"]; y0 = rd["y"] + off; x1 = x0; y1 = y0 + ow
                        else: x0 = rd["x"] + rd["w"]; y0 = rd["y"] + off; x1 = x0; y1 = y0 + ow

                        fig_of.add_trace(go.Scatter(x=[x0, x1], y=[y0, y1], mode="lines", line=dict(color=clr, width=6), showlegend=False))
                        fig_of.add_annotation(x=(x0+x1)/2, y=(y0+y1)/2, text=op.get("id",""), showarrow=False, font=dict(size=8, color=clr))

                    # Draw Furniture
                    FURN_CLR = "#A78BFA"
                    for fi in furniture:
                        rm = fi.get("room","")
                        if rm not in room_lookup: continue
                        rd = room_lookup[rm]
                        fx, fy, fw, fd = rd["x"] + fi.get("x_m", 0), rd["y"] + fi.get("y_m", 0), fi.get("w_m", 0.5), fi.get("d_m", 0.5)

                        fig_of.add_shape(type="rect", x0=fx, y0=fy, x1=fx+fw, y1=fy+fd, fillcolor=FURN_CLR, opacity=0.55, line=dict(color="#FFFFFF", width=1))
                        cl = fi.get("clearance_m", 0)
                        if cl > 0: fig_of.add_shape(type="rect", x0=fx-cl, y0=fy-cl, x1=fx+fw+cl, y1=fy+fd+cl, fillcolor="rgba(0,0,0,0)", opacity=0.4, line=dict(color=FURN_CLR, width=1, dash="dot"))
                        fig_of.add_annotation(x=fx+fw/2, y=fy+fd/2, text=f"{fi.get('id','')}<br>{fi.get('type','')}", showarrow=False, font=dict(size=7, color="#E8F0FF"))

                    fig_of.add_shape(type="rect", x0=0, y0=0, x1=SITE_W, y1=SITE_L, line=dict(color="#FFD700", width=3), fillcolor="rgba(0,0,0,0)")
                    fig_of.update_layout(height=max(520, int(520*(SITE_L+1.5)/(SITE_W+1.5))), plot_bgcolor=BG, paper_bgcolor=BG, xaxis=dict(visible=False, scaleanchor="y", scaleratio=1), yaxis=dict(visible=False), margin=dict(l=20,r=20,t=50,b=20))
                    st.plotly_chart(fig_of, width="stretch", config={"scrollZoom":True})

                    # 8. Validation Checks
                    st.markdown("---")
                    st.markdown("### ✅ 8. Validation Checks")
                    overlaps      = checks.get("overlaps", [])
                    cl_violations = checks.get("clearance_violations", [])
                    swing_conf    = checks.get("door_swing_conflicts", [])

                    vc1, vc2, vc3 = st.columns(3)
                    vc1.metric("🔴 Overlaps", len(overlaps), delta="⚠️ Found!" if overlaps else "✅ None", delta_color="inverse" if overlaps else "normal")
                    vc2.metric("🟡 Clearance", len(cl_violations), delta="⚠️ Found!" if cl_violations else "✅ None", delta_color="inverse" if cl_violations else "normal")
                    vc3.metric("🟠 Door Swing", len(swing_conf), delta="⚠️ Found!" if swing_conf else "✅ None", delta_color="inverse" if swing_conf else "normal")

                    auto_warnings = []
                    for fi in furniture:
                        rm = fi.get("room","")
                        if rm not in room_lookup: continue
                        rd = room_lookup[rm]
                        fx, fy, fw, fd = fi.get("x_m",0), fi.get("y_m",0), fi.get("w_m",0), fi.get("d_m",0)
                        if fx < 0 or fy < 0 or fx+fw > rd["w"]+0.01 or fy+fd > rd["h"]+0.01:
                            auto_warnings.append(f"⚠️ {fi.get('id','')} ({fi.get('type','')}) ใน {rm} ล้นออกนอกขอบห้อง!")

                    for op in openings:
                        ow = op.get("width_m", 0)
                        if op.get("type") == "door" and ow < 0.8: auto_warnings.append(f"⚠️ {op.get('id','')} door width {ow}m < 0.8m")
                        if op.get("type") == "window" and ow < 0.6: auto_warnings.append(f"⚠️ {op.get('id','')} window width {ow}m < 0.6m")

                    if overlaps: st.warning("**Overlap Details:**"); st.json(overlaps)
                    if cl_violations: st.warning("**Clearance Violation Details:**"); st.json(cl_violations)
                    if swing_conf: st.warning("**Door Swing Conflict Details:**"); st.json(swing_conf)
                    if auto_warnings: 
                        st.warning("**Auto-detected Warnings:**")
                        for w in auto_warnings: st.markdown(f"- {w}")

                    if not overlaps and not cl_violations and not swing_conf and not auto_warnings:
                        st.success("✅ All checks passed — สมบูรณ์แบบ! ไม่พบ overlap หรือจุดบกพร่อง")

                    st.markdown("---")
                    st.markdown("### 📦 Final AI Result JSON (Complete)")
                    final_json = {
                        "Packed_Plan": packed_plan_for_prompt, "Openings": openings, "Furniture": furniture, "Checks": checks,
                        "metadata": {"site_width_m": SITE_W, "site_length_m": SITE_L, "scale_factor": round(scale_ratio, 4), "total_net_sqm": round(t_net, 2), "total_gross_sqm": round(t_gross, 2)},
                    }
                    st.code(json.dumps(final_json, ensure_ascii=False, indent=2), language="json")

                except Exception as e2:
                    st.error(f"❌ Openings/Furniture JSON ไม่ถูกต้อง: {e2}")

    except Exception as e:
        with tab2:
            st.error(f"❌ JSON ไม่ถูกต้อง หรือเกิดข้อผิดพลาด: {e}")
