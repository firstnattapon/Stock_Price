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
  <p>Program Definition &rarr; AI Prompt &rarr; Adjacency Analysis &rarr; Site-Bound Packed Floor Plan</p>
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

with tab2:
    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.subheader("⚙️ Circulation Factor")
    cc1, cc2 = st.columns([1, 3])
    with cc1:
        circ_pct = st.number_input("Circulation (% Net Area)", min_value=0, max_value=100,
            value=0, step=5, help="แนะนำให้ปรับเป็น 0% หากกรอกพื้นที่รวมมาพอดีกรอบ Site แล้ว")
    with cc2:
        st.info("💡 เนื่องจากใช้วิธี Pack Area พอดี Site ระบบจะแปลง Circulation เป็นตัวคูณปรับสัดส่วนรวมให้พอดี")
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
        {"room1": "Living Area", "room2": "Dining",   "score":  2, "reason": "Open plan connection"}
    ],
    "Design_Concept": "Packed layout fitting exactly 8x4 meters site boundary."
}"""

    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.subheader("📋 วาง AI Result JSON")
    user_json = st.text_area("⬇️ JSON output", value=MOCK, height=220)
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

            st.dataframe(df.style.format("{:.2f}", subset=["net_area_sqm", clbl, "Gross_sqm"]), use_container_width=True)

            # ── 2. Network Graph (For Adjacency Weight) ────────
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

            # ════════════════════════════════════════════════════════
            # 3. Schematic Packed Block Plan
            # ════════════════════════════════════════════════════════
            st.markdown("---")
            st.markdown("### 🟩 2. Schematic Packed Floor Plan  (100% Site Fit)")

            # เตรียม Data สำหรับ Treemap Slice & Dice
            items_to_pack = [(r, df.loc[df["room"]==r, "Gross_sqm"].values[0] * scale_ratio) for r in sorted_rooms]
            
            # เรียกใช้ Algorithm ผ่าพื้นที่
            layout_rects = generate_treemap(items_to_pack, 0, 0, SITE_W, SITE_L)

            # ── Draw figure ──
            BG        = "#0F1624"
            ANNO_CLR  = "#FFD700"
            OUTER_PAD = max(SITE_W, SITE_L) * 0.15 

            FIG_W_IN = 14
            FIG_H_IN = FIG_W_IN * (SITE_L + 2*OUTER_PAD) / (SITE_W + 2*OUTER_PAD) + 0.5
            fig_bp, ax = plt.subplots(figsize=(FIG_W_IN, FIG_H_IN))
            fig_bp.patch.set_facecolor(BG)
            ax.set_facecolor(BG)

            # กรอบ Site
            ax.add_patch(Rectangle((0,0), SITE_W, SITE_L, linewidth=4.0, edgecolor=ANNO_CLR, facecolor="none", zorder=9))

            # Dimension arrows 
            ax.annotate("", xy=(SITE_W, -OUTER_PAD*0.3), xytext=(0, -OUTER_PAD*0.3), arrowprops=dict(arrowstyle="<->", color=ANNO_CLR, lw=2.0))
            ax.text(SITE_W/2, -OUTER_PAD*0.45, f"Width: {SITE_W:.1f} ม.", ha="center", va="top", fontsize=12, fontweight="bold", color=ANNO_CLR)

            ax.annotate("", xy=(-OUTER_PAD*0.3, SITE_L), xytext=(-OUTER_PAD*0.3, 0), arrowprops=dict(arrowstyle="<->", color=ANNO_CLR, lw=2.0))
            ax.text(-OUTER_PAD*0.45, SITE_L/2, f"Length: {SITE_L:.1f} ม.", ha="right", va="center", fontsize=12, fontweight="bold", color=ANNO_CLR, rotation=90)

            # เก็บตำแหน่งศูนย์กลางสำหรับวาดเส้นเชื่อม
            pos_packed = {}
            
            # วาดห้อง (Room Blocks)
            for r_data in layout_rects:
                room = r_data['room']
                rx, ry, rw, rh = r_data['x'], r_data['y'], r_data['w'], r_data['h']
                cx, cy = rx + rw/2.0, ry + rh/2.0
                pos_packed[room] = [cx, cy]
                
                color = pal[room]
                zone = ZONE_MAP.get(room, "Private")
                net_ = df.loc[df["room"]==room, "net_area_sqm"].values[0]
                scaled_area = rw * rh
                
                # กำแพงห้อง (เว้นขอบนิดๆ เพื่อให้เห็นเส้นแบ่ง)
                pad = 0.04
                ax.add_patch(Rectangle((rx+pad, ry+pad), rw-2*pad, rh-2*pad,
                    facecolor=color, edgecolor="#FFFFFF", lw=2.0, alpha=0.95, zorder=6))
                
                # Zone Stripe แถบสี
                stripe_h = min(rh * 0.15, 0.4)
                ax.add_patch(Rectangle((rx+pad, ry+rh-pad-stripe_h), rw-2*pad, stripe_h,
                    facecolor=ZONE_ACCENT.get(zone, "#555"), edgecolor="none", alpha=0.40, zorder=7))
                
                # Text
                fs = min(rw, rh) * 6 + 4
                fs = max(7, min(fs, 12))
                ax.text(cx, cy + rh*0.1, room, ha="center", va="center",
                    fontsize=fs, fontweight="bold", color="white",
                    path_effects=[pe.withStroke(linewidth=2.5, foreground="#00000099")], zorder=8)
                
                ax.text(cx, cy - rh*0.15, f"Plan Area: {scaled_area:.1f} ตร.ม.",
                    ha="center", va="center", fontsize=fs*0.75, color="#E8F0FF", zorder=8,
                    path_effects=[pe.withStroke(linewidth=1.5, foreground="#00000099")])

            # ── วาดเส้นความสัมพันธ์ (Adjacency overlay) ──
            ADJ_S = {
                 3: dict(c="#FF4D4D",lw=2.8,ls="-", a=0.9),
                 2: dict(c="#FFD700",lw=2.0,ls="-", a=0.8),
                 1: dict(c="#4CAF50",lw=1.2,ls=":", a=0.6),
                -1: dict(c="#000000",lw=1.5,ls="--",a=0.5),
            }
            
            for adj in data["Adjacency"]:
                r1, r2, sc = adj["room1"], adj["room2"], adj["score"]
                if r1 in pos_packed and r2 in pos_packed:
                    s = ADJ_S.get(sc, ADJ_S[1])
                    x1_, y1_ = pos_packed[r1]
                    x2_, y2_ = pos_packed[r2]
                    
                    # ลากเส้นเชื่อมศูนย์กลาง
                    ax.plot([x1_, x2_], [y1_, y2_], color=s["c"], lw=s["lw"],
                        ls=s["ls"], alpha=s["a"], zorder=9, solid_capstyle="round")
                    
                    # ตัวเลข Score
                    mx_, my_ = (x1_+x2_)/2, (y1_+y2_)/2
                    ax.text(mx_, my_, str(sc), ha="center", va="center", fontsize=7.5,
                        color=s["c"], fontweight="bold", zorder=10,
                        bbox=dict(boxstyle="circle,pad=0.2", fc=BG, ec=s["c"], lw=1.0, alpha=0.95))

            ax.set_xlim(-OUTER_PAD, SITE_W+OUTER_PAD)
            ax.set_ylim(-OUTER_PAD, SITE_L+OUTER_PAD)
            ax.set_aspect("equal")
            ax.axis("off")
            plt.tight_layout(pad=0.8)
            st.pyplot(fig_bp, use_container_width=True)

            st.markdown(f"""
<div class="note">
<b>📐 หลักการ Packed Block Plan:</b><br>
<b>① Scaling</b> — ปรับขนาดพื้นที่ทุกห้องตามสัดส่วน (Ratio) เพื่อให้ผลรวมพอดีกับกรอบ <b>{SITE_W:.1f} × {SITE_L:.1f} ม.</b> (100% Fit).<br>
<b>② Adjacency Ordering</b> — วิเคราะห์ Network Graph เพื่อดึงห้องที่เชื่อมต่อกันมาเรียงลำดับแนวแกน.<br>
<b>③ Slice and Dice Algorithm</b> — ผ่าแบ่งกรอบสี่เหลี่ยมสลับแนวตั้ง/แนวนอนตามสัดส่วนพื้นที่ห้อง (Treemap) ทำให้ไม่เกิดพื้นที่เสียเปล่า (Zero Gaps).<br>
<b>④ Network Overlay</b> — เส้นประและตัวเลขแสดง Adjacency Score จริงที่วางทาบลงบนแปลน.
</div>
""", unsafe_allow_html=True)

            # ── 3. Design Concept ──────────────────────────────
            st.markdown("---")
            st.markdown("### 🧠 3. AI Design Concept")
            st.markdown(f"""
<div style="background:linear-gradient(135deg,#0D1B35,#1A2E55); border:1px solid #1E3A6E;border-radius:14px; padding:22px 28px;color:#C0D8F0;font-size:0.97rem;line-height:1.75;">
  💡 {data["Design_Concept"]}
</div>
""", unsafe_allow_html=True)

        except Exception as e:
            st.error(f"❌ JSON ไม่ถูกต้อง หรือเกิดข้อผิดพลาด: {e}")
