import streamlit as st
import json
import pandas as pd
import plotly.graph_objects as go
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyBboxPatch, Rectangle
import matplotlib.patheffects as pe
import seaborn as sns
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
  <p>Program Definition &rarr; AI Prompt &rarr; Adjacency Analysis &rarr; Site-Bound Schematic Block Plan</p>
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
        mode = st.radio("Sizing Mode", [
            "Auto (Neufert / Thai Building Code)",
            "Manual (ผู้ใช้กำหนดเอง)",
        ])
    st.markdown('</div>', unsafe_allow_html=True)

    DEFAULT_AREAS = {
        "Bedroom":9.0,"Living Area":8.0,"Kitchen":4.5,"Dining":4.0,
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
                if mode == "Manual (ผู้ใช้กำหนดเอง)"
                else "Auto-calculate based on Neufert standards and Thai Building Code"
            )
            prompt = {
                "system_prompt": (
                    "คุณคือสถาปนิกระดับ Senior หน้าที่ของคุณคือวิเคราะห์ Program Definition "
                    "และส่งข้อมูลกลับมาเป็น JSON ตามโครงสร้างที่กำหนดเท่านั้น "
                    "ห้ามมีข้อความเกริ่นนำหรือสรุปท้ายใดๆ"
                ),
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

    # Circulation
    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.subheader("⚙️ Circulation Factor")
    cc1, cc2 = st.columns([1, 3])
    with cc1:
        circ_pct = st.number_input("Circulation (% Net Area)", min_value=0, max_value=100,
            value=30, step=5, help="20–30% ที่พักอาศัย | 30–40% อาคารสาธารณะ")
    with cc2:
        if   circ_pct < 20:  st.info(   f"ℹ️ {circ_pct}% — น้อยกว่ามาตรฐาน")
        elif circ_pct <= 35: st.success( f"✅ {circ_pct}% — มาตรฐานที่พักอาศัย (20–35%)")
        elif circ_pct <= 50: st.warning( f"⚠️ {circ_pct}% — สูงกว่าปกติ")
        else:                st.error(   f"🔴 {circ_pct}% — สูงมาก")
    circ_factor = circ_pct / 100.0
    st.markdown('</div>', unsafe_allow_html=True)

    # JSON Input
    MOCK = """{
    "Space_Requirement": [
        {"room": "Bedroom",      "net_area_sqm": 7.0},
        {"room": "Living Area",  "net_area_sqm": 7.0},
        {"room": "Kitchen",      "net_area_sqm": 6.0},
        {"room": "Dining",       "net_area_sqm": 6.0},
        {"room": "Bathroom",     "net_area_sqm": 3.0},
        {"room": "Closet",       "net_area_sqm": 3.0}
    ],
    "Adjacency": [
        {"room1": "Living Area", "room2": "Dining",   "score":  3, "reason": "Open plan connection"},
        {"room1": "Dining",      "room2": "Kitchen",  "score":  3, "reason": "Serve food efficiently"},
        {"room1": "Bedroom",     "room2": "Closet",   "score":  3, "reason": "Direct wardrobe access"},
        {"room1": "Bedroom",     "room2": "Bathroom", "score":  2, "reason": "Night-time convenience"},
        {"room1": "Bathroom",    "room2": "Closet",   "score":  2, "reason": "Private zone cluster"},
        {"room1": "Living Area", "room2": "Bedroom",  "score":  1, "reason": "Privacy transition"},
        {"room1": "Kitchen",     "room2": "Bedroom",  "score": -1, "reason": "Prevent odor & noise"}
    ],
    "Design_Concept": "Zone layout: Public (Living+Dining) at front open-plan, Service (Kitchen) adjacent to Dining, Private cluster (Bedroom+Closet+Bathroom) at rear — maximum separation from Kitchen."
}"""

    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.subheader("📋 วาง AI Result JSON")
    user_json = st.text_area("⬇️ JSON output from Claude / ChatGPT", value=MOCK, height=220)
    st.markdown('</div>', unsafe_allow_html=True)

    if st.button("✨ Generate Schematic Design", type="primary"):
        try:
            data      = json.loads(user_json)
            df        = pd.DataFrame(data["Space_Requirement"])
            clbl      = f"Circulation_{circ_pct}%"
            df[clbl]          = df["net_area_sqm"] * circ_factor
            df["Gross_sqm"]   = df["net_area_sqm"] + df[clbl]
            rooms_list        = df["room"].tolist()

            # Palette
            pal = {}; fi = 0
            for r in rooms_list:
                pal[r] = ROOM_PALETTE.get(r, FALLBACK[fi % len(FALLBACK)])
                if r not in ROOM_PALETTE: fi += 1

            # ── 1. Space Table ─────────────────────────────────
            st.markdown("---")
            st.markdown("### 📊 1. Space Requirement")
            t_net   = df["net_area_sqm"].sum()
            t_gross = df["Gross_sqm"].sum()
            m1,m2,m3 = st.columns(3)
            m1.metric("📐 Net Area",                    f"{t_net:.2f} ตร.ม.")
            m2.metric(f"🚶 Circulation ({circ_pct}%)", f"{(t_gross-t_net):.2f} ตร.ม.")
            m3.metric("🏗️ Gross Area",                  f"{t_gross:.2f} ตร.ม.")
            st.dataframe(
                df.style
                    .format("{:.2f}", subset=["net_area_sqm", clbl, "Gross_sqm"])
                    .background_gradient(subset=["Gross_sqm"], cmap="Blues"),
                use_container_width=True,
            )

            # ── 2. Adjacency Matrix ────────────────────────────
            st.markdown("---")
            st.markdown("### 🧮 2. Adjacency Matrix")
            mat = pd.DataFrame(0, index=rooms_list, columns=rooms_list)
            for adj in data["Adjacency"]:
                r1,r2,sc = adj["room1"],adj["room2"],adj["score"]
                if r1 in rooms_list and r2 in rooms_list:
                    mat.at[r1,r2] = sc; mat.at[r2,r1] = sc

            fig_h, ax_h = plt.subplots(figsize=(8, 5.5))
            fig_h.patch.set_facecolor("#0F1624")
            ax_h.set_facecolor("#0F1624")
            sns.heatmap(mat.astype(float), annot=True, fmt=".0f",
                cmap="RdYlGn", center=0, vmin=-1, vmax=3,
                linewidths=0.6, linecolor="#1E2E4A",
                cbar_kws={"label":"Adj. Score","shrink":0.8}, ax=ax_h)
            ax_h.set_title("Adjacency Matrix   (3 = ต้องติดกัน  ·  -1 = ควรแยก)",
                fontsize=12, pad=14, color="#C8DCFF", fontweight="bold")
            ax_h.tick_params(colors="#A0B8D8", labelsize=9)
            plt.setp(ax_h.get_xticklabels(), rotation=30)
            plt.setp(ax_h.get_yticklabels(), rotation=0)
            plt.tight_layout()
            st.pyplot(fig_h, use_container_width=True)

            # ── 3. Network Graph ───────────────────────────────
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
            # 4. Schematic Block Plan — Site-Bounded (TRUE SCALE)
            # ════════════════════════════════════════════════════════
            st.markdown("---")
            st.markdown("### 🟩 4. Schematic Block Plan  (Adjacency-Informed · True Scale)")

            # Read site from session state
            SITE_W = st.session_state.get("site_width",  8.0)
            SITE_L = st.session_state.get("site_length", 4.0)

            st.markdown(
                f"บล็อกถูกจัดวางกึ่งกลางภายใน **กรอบ Site {SITE_W:.1f} × {SITE_L:.1f} ม.** "
                f"ด้วยสัดส่วนตามแกนเมตรจริง (True Scale) "
            )

            gross_map = {r: df.loc[df["room"]==r,"Gross_sqm"].values[0] for r in rooms_list}

            # 4.1 Build NetworkX graph
            G = nx.Graph()
            for r in rooms_list: G.add_node(r)
            WM = {3:4.0, 2:2.5, 1:1.0, -1:0.02}
            for adj in data["Adjacency"]:
                r1,r2,sc = adj["room1"],adj["room2"],adj["score"]
                if r1 in rooms_list and r2 in rooms_list:
                    G.add_edge(r1, r2, weight=WM.get(sc, 1.0))
            conn = {n for e in G.edges() for n in e}
            for r in rooms_list:
                if r not in conn and r != rooms_list[0]:
                    G.add_edge(rooms_list[0], r, weight=0.15)

            # 4.2 Spring layout
            sp = nx.spring_layout(G, weight="weight",
                k=5.0/math.sqrt(max(len(rooms_list),1)),
                iterations=800, seed=7)

            # 4.3 Initial block sizes (TRUE SCALE)
            # Area = W x L -> ถือว่าเป็นสี่เหลี่ยมจัตุรัส -> Area = (2*half)^2
            # ดังนั้น half = sqrt(Area) / 2
            half = {r: math.sqrt(gross_map[r]) / 2.0 for r in rooms_list}
            pos  = {r: [sp[r][0]*SITE_W*0.3, sp[r][1]*SITE_L*0.3] for r in rooms_list}

            # 4.4 Non-overlapping push-apart
            GAP = 0.25
            for _it in range(2000):
                moved = False
                for i,r1 in enumerate(rooms_list):
                    for j,r2 in enumerate(rooms_list):
                        if j <= i: continue
                        x1,y1=pos[r1]; x2,y2=pos[r2]; h1,h2=half[r1],half[r2]
                        mind=h1+h2+GAP; dx=x2-x1; dy=y2-y1
                        ox=mind-abs(dx); oy=mind-abs(dy)
                        if ox>0 and oy>0:
                            if ox<=oy:
                                push=ox/2+0.01; s=1 if dx>=0 else -1
                                pos[r1][0]-=s*push; pos[r2][0]+=s*push
                            else:
                                push=oy/2+0.01; s=1 if dy>=0 else -1
                                pos[r1][1]-=s*push; pos[r2][1]+=s*push
                            moved=True
                if not moved: break

            # 4.5 Center cluster within the site (No scaling of block sizes)
            bb_xmin = min(pos[r][0]-half[r] for r in rooms_list)
            bb_xmax = max(pos[r][0]+half[r] for r in rooms_list)
            bb_ymin = min(pos[r][1]-half[r] for r in rooms_list)
            bb_ymax = max(pos[r][1]+half[r] for r in rooms_list)
            
            cx0 = (bb_xmin+bb_xmax)/2
            cy0 = (bb_ymin+bb_ymax)/2
            
            for r in rooms_list:
                pos[r][0]  = (pos[r][0]-cx0) + SITE_W/2
                pos[r][1]  = (pos[r][1]-cy0) + SITE_L/2

            # 4.6 Draw figure
            BG        = "#0F1624"
            ANNO_CLR  = "#FFD700"
            OUTER_PAD = max(SITE_W, SITE_L) * 0.18  # axis padding outside site

            # Figure proportional to site + outer pad
            FIG_W_IN = 14
            FIG_H_IN = FIG_W_IN * (SITE_L + 2*OUTER_PAD) / (SITE_W + 2*OUTER_PAD) + 0.5
            fig_bp, ax = plt.subplots(figsize=(FIG_W_IN, FIG_H_IN))
            fig_bp.patch.set_facecolor(BG)
            ax.set_facecolor(BG)

            # ── Meter grid (inside site only) ──
            for gx in np.arange(0, SITE_W+0.01, 1.0):
                ax.axvline(gx, color="#1E2E44", lw=0.7, zorder=0)
            for gy in np.arange(0, SITE_L+0.01, 1.0):
                ax.axhline(gy, color="#1E2E44", lw=0.7, zorder=0)

            # ── Site fill + boundary ──
            ax.add_patch(Rectangle((0,0), SITE_W, SITE_L,
                linewidth=0, facecolor="#151F34", zorder=1))
            ax.add_patch(Rectangle((0,0), SITE_W, SITE_L,
                linewidth=3.5, edgecolor=ANNO_CLR, facecolor="none", zorder=9))

            # ── Dimension arrows ──
            ax.annotate("", xy=(SITE_W, -OUTER_PAD*0.38), xytext=(0, -OUTER_PAD*0.38),
                arrowprops=dict(arrowstyle="<->", color=ANNO_CLR, lw=2.0))
            ax.text(SITE_W/2, -OUTER_PAD*0.55,
                f"{SITE_W:.1f} ม.",
                ha="center", va="top", fontsize=12, fontweight="bold", color=ANNO_CLR)

            ax.annotate("", xy=(-OUTER_PAD*0.38, SITE_L), xytext=(-OUTER_PAD*0.38, 0),
                arrowprops=dict(arrowstyle="<->", color=ANNO_CLR, lw=2.0))
            ax.text(-OUTER_PAD*0.58, SITE_L/2,
                f"{SITE_L:.1f} ม.",
                ha="right", va="center", fontsize=12, fontweight="bold",
                color=ANNO_CLR, rotation=90)

            # ── Meter tick labels ──
            for gx in range(0, int(SITE_W)+1):
                ax.text(gx, SITE_L+OUTER_PAD*0.12, f"{gx}",
                    ha="center", va="bottom", fontsize=7, color="#556688")
            for gy in range(0, int(SITE_L)+1):
                ax.text(SITE_W+OUTER_PAD*0.10, gy, f"{gy}",
                    ha="left", va="center", fontsize=7, color="#556688")
            ax.text(SITE_W/2, SITE_L+OUTER_PAD*0.32, "เมตร",
                ha="center", va="bottom", fontsize=7.5, color="#445577", style="italic")

            # ── Zone halos ──
            for room in rooms_list:
                cx,cy=pos[room]; h=half[room]; zone=ZONE_MAP.get(room,"Private"); pad=0.04
                ax.add_patch(FancyBboxPatch(
                    (cx-h-pad,cy-h-pad),(h+pad)*2,(h+pad)*2,
                    boxstyle="round,pad=0.04",
                    facecolor=ZONE_DARK.get(zone,"#222"),
                    edgecolor=ZONE_ACCENT.get(zone,"#555"),
                    lw=0.8,ls="--",alpha=0.50,zorder=2))

            # ── Zone labels ──
            zone_groups = {}
            for r in rooms_list:
                zone_groups.setdefault(ZONE_MAP.get(r,"Private"),[]).append(r)
            for zone, zr in zone_groups.items():
                zxs=[pos[r][0] for r in zr]; zys=[pos[r][1] for r in zr]; zh=[half[r] for r in zr]
                top=max(y+h for y,h in zip(zys,zh))+0.10
                cx_z=sum(zxs)/len(zxs)
                # clamp label inside site
                top  = min(top, SITE_L - 0.08)
                cx_z = max(0.1, min(cx_z, SITE_W - 0.1))
                ax.text(cx_z, top, f"[ {zone} ]",
                    ha="center", va="bottom", fontsize=7.5,
                    color=ZONE_ACCENT.get(zone,"#888"), alpha=0.80,
                    style="italic", fontweight="bold", zorder=3,
                    path_effects=[pe.withStroke(linewidth=2, foreground=BG)])

            # ── Adjacency edges ──
            ADJ_S = {
                 3: dict(c="#FF4D4D",lw=2.5,ls="-", a=0.88,lbl="Score 3  must-adjacent"),
                 2: dict(c="#FFD700",lw=1.8,ls="-", a=0.75,lbl="Score 2  should-be-near"),
                 1: dict(c="#4CAF50",lw=1.0,ls=":", a=0.55,lbl="Score 1  neutral"),
                -1: dict(c="#666666",lw=1.0,ls="--",a=0.40,lbl="Score -1  keep-apart"),
            }
            drawn_e = set()
            for adj in data["Adjacency"]:
                r1,r2,sc = adj["room1"],adj["room2"],adj["score"]
                if r1 not in pos or r2 not in pos: continue
                s=ADJ_S.get(sc,ADJ_S[1])
                x1_,y1_=pos[r1]; x2_,y2_=pos[r2]
                lbl=s["lbl"] if s["lbl"] not in drawn_e else "_"; drawn_e.add(s["lbl"])
                ax.plot([x1_,x2_],[y1_,y2_], color=s["c"], lw=s["lw"],
                    ls=s["ls"], alpha=s["a"], zorder=4, label=lbl,
                    solid_capstyle="round")
                mx_,my_=(x1_+x2_)/2,(y1_+y2_)/2
                ax.text(mx_,my_,str(sc),ha="center",va="center",fontsize=7,
                    color=s["c"],fontweight="bold",zorder=5,
                    bbox=dict(boxstyle="circle,pad=0.22",fc=BG,ec=s["c"],lw=0.7,alpha=0.88))

            # ── Room blocks ──
            for room in rooms_list:
                cx,cy=pos[room]; h=half[room]
                color=pal[room]
                net_=df.loc[df["room"]==room,"net_area_sqm"].values[0]
                gross_=gross_map[room]; zone=ZONE_MAP.get(room,"Private")
                # Glow
                for sh,av in [(0.06,0.08),(0.03,0.13)]:
                    ax.add_patch(FancyBboxPatch((cx-h-sh,cy-h-sh),(h+sh)*2,(h+sh)*2,
                        boxstyle="round,pad=0.06",facecolor=color,edgecolor="none",alpha=av,zorder=5))
                # Body
                ax.add_patch(FancyBboxPatch((cx-h,cy-h),h*2,h*2,
                    boxstyle="round,pad=0.06",facecolor=color,edgecolor="white",
                    lw=1.8,alpha=0.94,zorder=6))
                # Top stripe
                stripe_h=h*0.28
                ax.add_patch(Rectangle((cx-h,cy+h-stripe_h),h*2,stripe_h,
                    facecolor=ZONE_ACCENT.get(zone,"#555"),edgecolor="none",alpha=0.30,zorder=7))
                # Room name
                fs = 8 if h<0.25 else (9 if h<0.35 else (10 if h<0.50 else 11))
                ax.text(cx,cy+h*0.10,room,ha="center",va="center",
                    fontsize=fs,fontweight="bold",color="white",
                    path_effects=[pe.withStroke(linewidth=2.5,foreground="#00000099")],zorder=8)
                # Area
                ax.text(cx,cy-h*0.30,f"Net {net_:.1f} | Gross {gross_:.1f}",
                    ha="center",va="center",fontsize=6.5,color="white",alpha=0.78,zorder=8)
                # Zone tag
                ax.text(cx,cy+h*0.70,zone,ha="center",va="center",
                    fontsize=5.5,color="white",alpha=0.55,style="italic",zorder=8)

            # ── Site label (top-right inside) ──
            ax.text(SITE_W-0.10, SITE_L-0.10,
                f"Site:  {SITE_W:.1f} × {SITE_L:.1f} ม.  =  {SITE_W*SITE_L:.0f} ตร.ม.",
                ha="right",va="top",fontsize=9,color=ANNO_CLR,fontweight="bold",zorder=10,
                bbox=dict(boxstyle="round,pad=0.3",fc="#0A1020",ec=ANNO_CLR,lw=1.0,alpha=0.88))

            # ── Legends ──
            lp=[mpatches.Patch(color=v["c"],label=v["lbl"]) for v in ADJ_S.values()]
            al=ax.legend(handles=lp,loc="lower right",fontsize=8,framealpha=0.90,
                facecolor="#0A1020",edgecolor="#243358",labelcolor="white",
                title="Adjacency Score",title_fontsize=9)
            plt.setp(al.get_title(),color="#90B4E0")
            zp=[mpatches.Patch(facecolor=ZONE_ACCENT[z],label=z,alpha=0.85) for z in ZONE_ACCENT]
            zl=ax.legend(handles=zp,loc="upper right",fontsize=8,framealpha=0.90,
                facecolor="#0A1020",edgecolor="#243358",labelcolor="white",
                title="Spatial Zone",title_fontsize=9)
            plt.setp(zl.get_title(),color="#90B4E0")
            ax.add_artist(al)

            ax.set_xlim(-OUTER_PAD, SITE_W+OUTER_PAD)
            ax.set_ylim(-OUTER_PAD, SITE_L+OUTER_PAD)
            ax.set_aspect("equal"); ax.axis("off")
            ax.set_title(
                f"Schematic Block Plan  —  Site {SITE_W:.1f} × {SITE_L:.1f} ม."
                f"  ·  Adjacency-Informed · True Scale",
                fontsize=13, color="#C8DCFF", fontweight="bold", pad=16)
            plt.tight_layout(pad=0.8)
            st.pyplot(fig_bp, use_container_width=True)

            st.markdown(f"""
<div class="note">
<b>📐 หลักการ Block Plan:</b><br>
<b>① ตำแหน่ง</b> — Spring Layout (NetworkX) ใช้ Adjacency Score เป็น spring weight
(Score 3 = ดึงชิด · Score -1 = ผลักออก)<br>
<b>② Non-Overlap</b> — Iterative push-apart algorithm ดันบล็อกที่ทับกันออก<br>
<b>③ True Scale & Centering</b> — ขนาดบล็อกสเกลจริง 1:1 จัดกึ่งกลางลงในขอบเขต {SITE_W:.1f} × {SITE_L:.1f} ม.<br>
<b>④ ขนาดบล็อก</b> — สัดส่วนสเกลจริงตาม Gross Area (ตร.ม.) ซึ่ง = Net + Circulation {circ_pct}%<br>
<b>⑤ Zone</b> — Public · Service · Private แสดงด้วยสีพื้นหลัง halo
</div>
""", unsafe_allow_html=True)

            # ── 5. Design Concept ──────────────────────────────
            st.markdown("---")
            st.markdown("### 🧠 5. AI Design Concept")
            st.markdown(f"""
<div style="background:linear-gradient(135deg,#0D1B35,#1A2E55);
            border:1px solid #1E3A6E;border-radius:14px;
            padding:22px 28px;color:#C0D8F0;font-size:0.97rem;line-height:1.75;">
  💡 {data["Design_Concept"]}
</div>
""", unsafe_allow_html=True)

        except Exception as e:
            st.error(f"❌ JSON ไม่ถูกต้อง หรือเกิดข้อผิดพลาด: {e}")
