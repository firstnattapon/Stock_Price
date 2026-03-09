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
    st.subheader("📋 วาง AI Result JSON (Prompt A)")
    user_json = st.text_area("⬇️ JSON output from Claude / ChatGPT", value=MOCK, height=220)
    st.markdown('</div>', unsafe_allow_html=True)

    if st.button("✨ Generate Schematic Packed Plan", type="primary"):
        st.session_state.plan_generated = True

if st.session_state.get("plan_generated", False):
    try:
        data = json.loads(user_json)
        if "Space_Requirement" not in data:
            st.error("❌ ข้อผิดพลาด: ไม่พบคีย์ 'Space_Requirement' ใน JSON")
            st.stop()
            
        df = pd.DataFrame(data["Space_Requirement"])
        clbl = f"Circulation_{circ_pct}%"
        df[clbl] = df["net_area_sqm"] * circ_factor
        df["Gross_sqm"] = df["net_area_sqm"] + df[clbl]
        rooms_list = df["room"].tolist()

        pal = {}; fi = 0
        for r in rooms_list:
            pal[r] = ROOM_PALETTE.get(r, FALLBACK[fi % len(FALLBACK)])
            if r not in ROOM_PALETTE: fi += 1

        t_net = df["net_area_sqm"].sum()
        t_gross = df["Gross_sqm"].sum()
        
        SITE_W = st.session_state.get("site_width", 8.0)
        SITE_L = st.session_state.get("site_length", 4.0)
        SITE_AREA = SITE_W * SITE_L
        scale_ratio = SITE_AREA / t_gross if t_gross > 0 else 1

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

        room_lookup = {rd["room"]: rd for rd in layout_rects}

        with tab2:
            # 1, 2, 3 ... (Skipping rendering code for brevity of focus, but kept in full code)
            st.markdown("---")
            st.markdown("### 📊 1. Space Requirement")
            st.dataframe(df.style.format("{:.2f}", subset=["net_area_sqm", clbl, "Gross_sqm"]), width="stretch")

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

        # ── Render TAB 3 ──
        with tab3:
            st.markdown("### 🚪 6. AI Prompt — Openings + Furniture")
            st.markdown('<div class="note"><b>💡 Two-Stage AI Flow:</b> คัดลอก Prompt ด้านล่างไปส่งให้ AI อีกรอบ เพื่อได้ช่องเปิด + เฟอร์นิเจอร์ที่ลงตัวตามพิกัดห้อง</div>', unsafe_allow_html=True)
            # ... (รหัส Tab 3 เดิม นำมาวางต่อได้เลย ไม่ได้แก้ไขในส่วนนี้)
    except Exception as e:
        st.error(f"❌ JSON ไม่ถูกต้อง หรือเกิดข้อผิดพลาด: {e}")
