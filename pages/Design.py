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

if "site_width"               not in st.session_state: st.session_state.site_width               = 8.0
if "site_length"              not in st.session_state: st.session_state.site_length              = 4.0
if "plan_generated"           not in st.session_state: st.session_state.plan_generated           = False
if "generated_adjacency_json" not in st.session_state: st.session_state.generated_adjacency_json = None

# Session State สำหรับ Neuro-Symbolic AI Data Hand-off
if "ai_parsed_c"       not in st.session_state: st.session_state.ai_parsed_c       = None
if "ai_parsed_w"       not in st.session_state: st.session_state.ai_parsed_w       = None
if "ai_parsed_rooms"   not in st.session_state: st.session_state.ai_parsed_rooms   = None
if "ai_parsed_space"   not in st.session_state: st.session_state.ai_parsed_space   = None
if "ai_parsed_concept" not in st.session_state: st.session_state.ai_parsed_concept = None

# State สำหรับเก็บผลลัพธ์ Graph Generation
if "graph_results"       not in st.session_state: st.session_state.graph_results       = None

# ── [NEW] Multi-Rank Navigation State ────────────────────────
if "all_graphs_json"     not in st.session_state: st.session_state.all_graphs_json     = []
if "selected_rank_index" not in st.session_state: st.session_state.selected_rank_index = 0

# ── [NEW] Navigation Callbacks ────────────────────────────────
def go_prev():
    st.session_state.selected_rank_index = max(
        0, st.session_state.selected_rank_index - 1
    )

def go_next():
    st.session_state.selected_rank_index = min(
        len(st.session_state.all_graphs_json) - 1,
        st.session_state.selected_rank_index + 1,
    )

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

  .score-bar-wrap { background:#1A2540; border-radius:8px; padding:2px 6px; }
  .score-bar      { height:10px; border-radius:5px; }

  /* [NEW] Navigation bar styling */
  .nav-bar {
    background: #0D1E3A;
    border: 1px solid #1E3A6E;
    border-radius: 12px;
    padding: 14px 20px;
    margin: 16px 0 24px 0;
    display: flex;
    align-items: center;
    justify-content: space-between;
  }
</style>
""", unsafe_allow_html=True)

st.markdown("""
<div class="hero">
  <h1>🏛️ AI Architecture: Neuro-Symbolic Design Pipeline</h1>
  <p>Program Definition &rarr; AI Rule Generation (LLM) &rarr; Deterministic Graph Engine &rarr; Packed Floor Plan</p>
</div>
""", unsafe_allow_html=True)

# ══════════════════════════════════════════
# 🎨  Design Tokens
# ══════════════════════════════════════════
ROOM_PALETTE = {
    "Living Area": "#4E79A7", "Bedroom": "#E15759", "Dining": "#F28E2B",
    "Kitchen": "#59A14F", "Bathroom": "#76B7B2", "Closet": "#B07AA1",
    "Balcony": "#EDC948", "Laundry": "#FF9DA7",
}
FALLBACK = ["#4E79A7", "#E15759", "#F28E2B", "#59A14F",
            "#76B7B2", "#B07AA1", "#EDC948", "#FF9DA7", "#BAB0AC", "#D37295"]

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

    direction = 1 if (p0[0] + p0[1]) % 2 > 1 else -1
    p1 = mid + normal * (dist * offset_ratio * direction)

    t = np.linspace(0, 1, num_points)
    curve = np.outer((1-t)**2, p0) + np.outer(2*(1-t)*t, p1) + np.outer(t**2, p2)
    return curve[:, 0], curve[:, 1]


# ══════════════════════════════════════════════════════════════
# 🧬  MatrixController — Chaillou Dual-Matrix Quality Engine
# ══════════════════════════════════════════════════════════════

class MatrixController:
    """
    Implements Chaillou (2020) Dual-Matrix Quality Framework:
      Q(e_ij) = C[i][j] × W[i][j]
      S*(G)   = Σ Q(e_ij) − Σ penalty(missing critical edges)
    """

    def __init__(self, rooms: list, C: list, W: list):
        self.rooms = rooms
        self.C     = np.array(C, dtype=float)
        self.W     = np.array(W, dtype=float)
        self.idx   = {r: i for i, r in enumerate(rooms)}

    def edge_score(self, r1: str, r2: str) -> float:
        i, j = self.idx.get(r1, -1), self.idx.get(r2, -1)
        if i < 0 or j < 0: return 0.0
        return float(self.C[i][j] * self.W[i][j])

    def graph_score(self, edges: list) -> float:
        edge_set = {(r1, r2) for r1, r2 in edges} | {(r2, r1) for r1, r2 in edges}
        score = sum(self.edge_score(r1, r2) for r1, r2 in edges)
        n = len(self.rooms)
        for i in range(n):
            for j in range(i + 1, n):
                if self.C[i][j] == 1 and self.W[i][j] == 3:
                    r1, r2 = self.rooms[i], self.rooms[j]
                    if (r1, r2) not in edge_set:
                        score -= float(self.W[i][j])
        return score

    def max_theoretical_score(self) -> float:
        n = len(self.rooms)
        s = sum(self.C[i][j] * self.W[i][j] for i in range(n) for j in range(i + 1, n) if (self.C[i][j] * self.W[i][j]) > 0)
        return s if s > 0 else 1.0

    def _is_connected(self, edges: list) -> bool:
        if not self.rooms: return True
        adj = {r: set() for r in self.rooms}
        for r1, r2 in edges:
            adj.setdefault(r1, set()).add(r2)
            adj.setdefault(r2, set()).add(r1)
        visited = set(); queue = [self.rooms[0]]
        while queue:
            node = queue.pop()
            if node in visited: continue
            visited.add(node); queue.extend(adj.get(node, set()) - visited)
        return len(visited) == len(self.rooms)

    def generate_graph(self, T: float = 0.7, max_attempts: int = 500) -> list:
        n = len(self.rooms)
        for _ in range(max_attempts):
            edges = []
            for i in range(n):
                for j in range(i + 1, n):
                    q = float(self.C[i][j] * self.W[i][j])
                    p = 1.0 / (1.0 + math.exp(max(-50, min(50, -q / T))))
                    if np.random.random() < p: edges.append((self.rooms[i], self.rooms[j]))
            if self._is_connected(edges): return edges
        return [(self.rooms[i], self.rooms[i+1]) for i in range(n - 1)]

    def filter_best_graphs(self, N: int = 100, top_k: int = 5, T: float = 0.7) -> list:
        candidates = [(g, self.graph_score(g)) for g in (self.generate_graph(T) for _ in range(N))]
        candidates.sort(key=lambda x: x[1], reverse=True)
        return candidates[:top_k]

    def get_violated_rules(self, edges: list) -> list:
        edge_set = {(r1, r2) for r1, r2 in edges} | {(r2, r1) for r1, r2 in edges}
        violations = []
        n = len(self.rooms)
        for i in range(n):
            for j in range(i + 1, n):
                r1, r2 = self.rooms[i], self.rooms[j]
                c, w = int(self.C[i][j]), int(self.W[i][j])
                connected = (r1, r2) in edge_set
                if c == 1 and w == 3 and not connected:
                    violations.append(f"❌ Critical Direct Missing: **{r1} ↔ {r2}**")
                elif c == -1 and w == 3 and connected:
                    violations.append(f"⚠️ Critical Separation Violated: **{r1} ↔ {r2}**")
        return violations

    def to_adjacency_json(self, edges: list, space_requirements: list, design_concept: str = "") -> dict:
        edge_set = {(r1, r2) for r1, r2 in edges} | {(r2, r1) for r1, r2 in edges}
        adjacency = []
        n = len(self.rooms)
        for i in range(n):
            for j in range(i + 1, n):
                r1, r2 = self.rooms[i], self.rooms[j]
                if (r1, r2) not in edge_set: continue
                q   = self.edge_score(r1, r2)
                c_v = int(self.C[i][j]); w_v = int(self.W[i][j])
                dp_score = 3 if q >= 3 else (2 if q >= 2 else (1 if q >= 1 else -1))
                conn_lbl = "Direct" if c_v == 1 else "Indirect"
                imp_lbl  = "High" if w_v == 3 else ("Medium" if w_v == 2 else "Low")
                reason   = f"Q={q:.0f} (C={conn_lbl}, W={imp_lbl})"
                adjacency.append({"room1": r1, "room2": r2, "score": dp_score, "reason": reason})
        return {
            "Space_Requirement": space_requirements,
            "Adjacency":         adjacency,
            "Design_Concept":    design_concept,
        }

# ══════════════════════════════════════════════════════════════
# 🗂️  Typology Matrix Presets  (Chaillou-inspired defaults)
# ══════════════════════════════════════════════════════════════
_RULE_TABLE: dict = {
    frozenset({"Kitchen",    "Dining"}):      (+1, 3),
    frozenset({"Kitchen",    "Living Area"}): (+1, 2),
    frozenset({"Dining",     "Living Area"}): (+1, 3),
    frozenset({"Bedroom",    "Bathroom"}):    (+1, 3),
    frozenset({"Bedroom",    "Closet"}):      (+1, 3),
    frozenset({"Bedroom",    "Living Area"}): (+1, 2),
    frozenset({"Bedroom",    "Balcony"}):     (+1, 1),
    frozenset({"Bedroom",    "Kitchen"}):     (-1, 3),
    frozenset({"Bathroom",   "Kitchen"}):     (-1, 2),
    frozenset({"Bathroom",   "Closet"}):      (+1, 2),
    frozenset({"Laundry",    "Kitchen"}):     (+1, 2),
    frozenset({"Laundry",    "Bathroom"}):    (+1, 1),
    frozenset({"Balcony",    "Living Area"}): (+1, 2),
    frozenset({"Balcony",    "Dining"}):      (+1, 1),
    frozenset({"Living Area","Dining"}):      (+1, 3),
}

def build_default_matrices(rooms: list) -> tuple[list, list]:
    n = len(rooms)
    C = [[0] * n for _ in range(n)]
    W = [[0] * n for _ in range(n)]
    for i, r1 in enumerate(rooms):
        for j, r2 in enumerate(rooms):
            if i == j: continue
            key = frozenset({r1, r2})
            if key in _RULE_TABLE:
                c_val, w_val = _RULE_TABLE[key]
                C[i][j] = c_val; W[i][j] = w_val
    return C, W

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
            ["Bedroom", "Living Area", "Kitchen", "Dining", "Bathroom", "Balcony", "Laundry", "Closet"],
            default=["Bedroom", "Living Area", "Kitchen", "Dining", "Bathroom", "Closet"],
        )
        mode = st.radio("Sizing Mode", ["Auto (Neufert / Thai Building Code)", "Manual (ผู้ใช้กำหนดเอง)"])
    st.markdown('</div>', unsafe_allow_html=True)

    DEFAULT_AREAS = {
        "Bedroom": 7.0, "Living Area": 7.0, "Kitchen": 6.0, "Dining": 6.0,
        "Bathroom": 3.0, "Balcony": 2.5, "Laundry": 2.0, "Closet": 3.0,
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

    if st.button("🚀 1. Generate AI Prompt (Rule Maker)", type="primary"):
        if not rooms:
            st.error("กรุณาเลือกห้องอย่างน้อย 1 ห้อง")
        else:
            payload = (
                [{"room": r, "net_area_sqm": manual_areas.get(r, DEFAULT_AREAS.get(r, 4.0))} for r in rooms]
                if mode == "Manual (ผู้ใช้กำหนดเอง)" else "Auto-calculate"
            )

            total_site_area = width * length
            max_net_area = total_site_area * 0.85

            prompt = {
                "system_prompt": "คุณคือสถาปนิกระดับ Senior หน้าที่ของคุณคือวิเคราะห์ข้อมูลและส่งกลับเป็นรูปแบบ JSON ที่ Valid เท่านั้น ห้ามมีข้อความทักทาย, Markdown (` ```json `), หรือคำอธิบายใดๆ นอกกรอบ JSON ปีกกา {} เด็ดขาด",
                "user_input": {
                    "project": project_type,
                    "site_dimension": f"{width} x {length} m (Total {total_site_area} sqm)",
                    "required_spaces": rooms,
                    "sizing_mode": mode,
                    "space_areas": payload,
                },
                "strict_architectural_constraints": {
                    "1_area_limit": f"ผลรวมของ 'net_area_sqm' ทุกห้องรวมกัน จะต้องไม่เกินพื้นที่ Site ({total_site_area} sqm) ลบด้วยพื้นที่ทางเดิน 15% หมายความว่า Total Net Area ต้องไม่เกิน {max_net_area:.1f} sqm เด็ดขาด",
                    "2_code_compliance": "ห้องน้ำ (Bathroom) ต้องมีขนาดไม่ต่ำกว่ามาตรฐานกฎหมาย (1.5 sqm ขึ้นไป) และห้องอื่นๆ ต้องมีสัดส่วนสมจริงตามมาตรฐาน Neufert",
                    "3_comprehensive_adjacency": "ใน 'Adjacency_Rules' ให้สร้างกฎสำหรับทุกคู่ห้องที่มีความสัมพันธ์ชัดเจน ต้องมีทั้งห้องที่บังคับติดกัน (C=1) และห้องที่บังคับแยกกัน (C=-1) ให้ครบถ้วน"
                },
                "required_output_schema": {
                    "Space_Requirement": [{"room": "string", "net_area_sqm": "float"}],
                    "Adjacency_Rules": [
                        {
                            "room1": "string",
                            "room2": "string",
                            "Connectivity_C": "int (-1=ควรแยก, 0=ไม่มีผล, 1=ควรติดกัน)",
                            "Importance_W": "int (0=ไม่สำคัญ, 1=น้อย, 2=ปานกลาง, 3=สำคัญมาก)",
                            "reason": "string (อธิบายเหตุผลสั้นๆ)"
                        }
                    ],
                    "Design_Concept": "string (สรุปแนวคิด Space Planning 1-2 ประโยค)",
                },
            }

            st.success("✅ **Prompt A — Rules Definition**: คัดลอกข้อความด้านล่างนี้ไปวางใน Claude / ChatGPT เพื่อรับกฎความสัมพันธ์ (C & W Matrix)")
            st.code(json.dumps(prompt, ensure_ascii=False, indent=4), language="json")

    # ════════════════════════════════════════════════════════════
    # 🧬  ADJACENCY GRAPH GENERATOR — MatrixController Section
    # ════════════════════════════════════════════════════════════
    st.markdown("---")

    st.markdown('### 🧬 2. Neuro-Symbolic Graph Engine (Matrix Controller)')
    st.markdown('<div class="note">'
        '<b>📖 การทำงานแบบ Hybrid:</b><br>'
        '1. วาง JSON จาก AI ที่ได้ในกล่องด้านล่าง เพื่อให้ระบบ <b>Extract กฎคณิตศาสตร์ (C & W)</b> อัตโนมัติ<br>'
        '2. กด <b>Generate</b> เพื่อให้ระบบคณิตศาสตร์ในแอปสุ่มหา Graph ที่สอดคล้องกับกฎของ AI ได้แม่นยำที่สุด 100% ไร้ข้อผิดพลาดทางตรรกะ'
        '</div>', unsafe_allow_html=True)

    ai_json_input = st.text_area("⬇️ วางผลลัพธ์ JSON (Prompt A) จาก AI ที่นี่ เพื่อโหลดกฎ C & W อัตโนมัติ", height=150)

    if st.button("📥 อัปเดตกฎ (Load AI Rules)"):
        if ai_json_input:
            try:
                parsed_data = json.loads(ai_json_input)
                if "Adjacency_Rules" in parsed_data:
                    p_rooms = [r["room"] for r in parsed_data.get("Space_Requirement", [])]
                    n = len(p_rooms)
                    p_C = [[0]*n for _ in range(n)]
                    p_W = [[0]*n for _ in range(n)]
                    room_idx = {r:i for i,r in enumerate(p_rooms)}

                    for rule in parsed_data["Adjacency_Rules"]:
                        r1, r2 = rule.get("room1"), rule.get("room2")
                        if r1 in room_idx and r2 in room_idx:
                            i, j = room_idx[r1], room_idx[r2]
                            p_C[i][j] = p_C[j][i] = rule.get("Connectivity_C", 0)
                            p_W[i][j] = p_W[j][i] = rule.get("Importance_W", 0)

                    st.session_state.ai_parsed_rooms   = p_rooms
                    st.session_state.ai_parsed_c       = p_C
                    st.session_state.ai_parsed_w       = p_W
                    st.session_state.ai_parsed_space   = parsed_data.get("Space_Requirement")
                    st.session_state.ai_parsed_concept = parsed_data.get("Design_Concept")
                    st.success("✅ ดึงกฎ C & W จาก AI สำเร็จ! ตาราง Matrix ด้านล่างถูกอัปเดตแล้ว")
                else:
                    st.warning("⚠️ JSON ไม่ถูกต้อง หรือไม่พบ Array 'Adjacency_Rules' ตาม Schema ใหม่")
            except Exception as e:
                st.error(f"❌ โครงสร้าง JSON มีข้อผิดพลาด: {e}")

    with st.expander("🛠️ ตรวจสอบ/แก้ไข กฎ Matrix ก่อนประมวลผล (Optional)", expanded=True):
        if not rooms:
            st.warning("⚠️ กรุณาเลือกห้องด้านบนก่อน")
        else:
            if st.session_state.ai_parsed_rooms and set(st.session_state.ai_parsed_rooms) == set(rooms):
                C_mapped = [[0]*len(rooms) for _ in range(len(rooms))]
                W_mapped = [[0]*len(rooms) for _ in range(len(rooms))]
                parsed_idx = {r:i for i,r in enumerate(st.session_state.ai_parsed_rooms)}
                for i, r1 in enumerate(rooms):
                    for j, r2 in enumerate(rooms):
                        if r1 in parsed_idx and r2 in parsed_idx:
                            pi, pj = parsed_idx[r1], parsed_idx[r2]
                            C_mapped[i][j] = st.session_state.ai_parsed_c[pi][pj]
                            W_mapped[i][j] = st.session_state.ai_parsed_w[pi][pj]
                C_default, W_default = C_mapped, W_mapped
                st.caption("✨ กำลังใช้กฎจากข้อมูล AI ที่ดึงมาล่าสุด")
            else:
                C_default, W_default = build_default_matrices(rooms)
                st.caption("ℹ️ กำลังใช้กฎตั้งต้น (Default Typology) เนื่องจากยังไม่ได้โหลดกฎจาก AI")

            mc1, mc2 = st.columns(2)
            with mc1:
                st.markdown("**C — Connectivity Matrix** (+1=ติด, -1=แยก)")
                df_C = pd.DataFrame(C_default, index=rooms, columns=rooms)
                edited_C = st.data_editor(df_C, key="mc_C_editor", use_container_width=True,
                                          column_config={c: st.column_config.NumberColumn(c, min_value=-1, max_value=1) for c in rooms})
            with mc2:
                st.markdown("**W — Importance Matrix** (3=มาก, 2=กลาง, 1=น้อย)")
                df_W = pd.DataFrame(W_default, index=rooms, columns=rooms)
                edited_W = st.data_editor(df_W, key="mc_W_editor", use_container_width=True,
                                          column_config={c: st.column_config.NumberColumn(c, min_value=0, max_value=3) for c in rooms})

    ctrl1, ctrl2, ctrl3 = st.columns([2, 2, 3])
    with ctrl1:
        n_gen  = st.number_input("จำนวน Candidate Graphs (N)", min_value=20, max_value=500, value=100, step=20)
    with ctrl2:
        top_k  = st.number_input("Top-K ที่เลือก", min_value=1, max_value=10, value=5, step=1)
    with ctrl3:
        temp   = st.slider("🌡️ Temperature (T)", min_value=0.3, max_value=1.5, value=0.7, step=0.05)

    if st.button("🎲 3. สานกฎให้เป็นกราฟ (Execute Graph Generation)", type="primary"):
        if len(rooms) < 2:
            st.error("ต้องมีห้องอย่างน้อย 2 ห้อง")
        else:
            C_vals = edited_C.values.tolist()
            W_vals = edited_W.values.tolist()
            mc     = MatrixController(rooms, C_vals, W_vals)
            S_max  = mc.max_theoretical_score()

            with st.spinner(f"⚙️ กำลัง Generate {n_gen} graphs ด้วย Algorithm ทางคณิตศาสตร์..."):
                best = mc.filter_best_graphs(N=int(n_gen), top_k=int(top_k), T=float(temp))

            space_req    = st.session_state.ai_parsed_space if st.session_state.ai_parsed_space else [{"room": r, "net_area_sqm": manual_areas.get(r, DEFAULT_AREAS.get(r, 4.0))} for r in rooms]
            base_concept = st.session_state.ai_parsed_concept if st.session_state.ai_parsed_concept else "Neuro-Symbolic Automated Pipeline"

            st.session_state.graph_results = {
                "best":         best,
                "S_max":        S_max,
                "space_req":    space_req,
                "base_concept": base_concept,
                "rooms":        rooms,
                "C":            C_vals,
                "W":            W_vals,
            }

    # ── Display Top-K results + [NEW] single send-all button ──
    if st.session_state.graph_results is not None:
        res  = st.session_state.graph_results
        mc   = MatrixController(res["rooms"], res["C"], res["W"])
        best = res["best"]
        S_max = res["S_max"]

        st.success(f"✅ เสร็จสิ้น! แสดง Top-{len(best)} กราฟที่แม่นยำตามกฎมากที่สุด")

        for rank, (edges, score) in enumerate(best):
            pct        = max(0, min(100, score / S_max * 100)) if S_max > 0 else 0
            violations = mc.get_violated_rules(edges)
            bar_color  = "#3CC470" if pct >= 70 else ("#FFB74D" if pct >= 40 else "#E05C5C")
            n_edges    = len(edges)

            with st.container():
                st.markdown(
                    f"**Rank #{rank+1}** — S\\*(G) = `{score:.1f}` / `{S_max:.1f}` &nbsp;|&nbsp; "
                    f"Quality = **{pct:.1f}%** &nbsp;|&nbsp; Edges = {n_edges} &nbsp;|&nbsp; "
                    f"Violations = {'🟢 None' if not violations else f'🔴 {len(violations)}'}"
                )
                st.markdown(
                    f'<div style="background:#1A2540;border-radius:8px;padding:4px 8px;margin-bottom:4px">'
                    f'<div style="width:{pct:.1f}%;height:10px;background:{bar_color};border-radius:5px"></div></div>',
                    unsafe_allow_html=True
                )
                if violations:
                    with st.expander(f"🔍 ดู Rule Violations ({len(violations)} items)", expanded=False):
                        for v in violations: st.markdown(f"- {v}")
                st.markdown("---")

        # ── [NEW] Single "Send All to Tab 2" button ────────────
        if st.button("✅ ส่ง Top-K ทั้งหมดไป Tab 2 (Navigate ด้วย ◀ / ▶)", key="send_all", type="primary"):
            all_json = []
            for rank, (edges, score) in enumerate(best):
                concept = f"{res['base_concept']} | [MatrixController Rank #{rank+1} | S*={score:.1f}/{S_max:.1f}]"
                gj = mc.to_adjacency_json(edges, res["space_req"], concept)
                all_json.append(json.dumps(gj, ensure_ascii=False, indent=2))
            st.session_state.all_graphs_json     = all_json
            st.session_state.selected_rank_index = 0
            st.session_state.generated_adjacency_json = all_json[0]
            st.session_state.plan_generated       = True
            st.toast(f"🚀 ส่ง {len(all_json)} Graphs สำเร็จ! กรุณากดที่ Tab 2 เพื่อ Navigate ด้วยปุ่ม ◀ / ▶", icon="✅")
            st.rerun()

# ════════════════════════════════════════════════════════════════
# 📥  TAB 2  — รับ Input + Navigation
# ════════════════════════════════════════════════════════════════
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

    # ── [NEW] Multi-Rank Navigation Bar ──────────────────────────
    if st.session_state.all_graphs_json:
        idx   = st.session_state.selected_rank_index
        total = len(st.session_state.all_graphs_json)

        # sync generated_adjacency_json with current selection
        st.session_state.generated_adjacency_json = st.session_state.all_graphs_json[idx]

        # Navigation UI
        st.markdown("---")
        nav_l, nav_c, nav_r = st.columns([1, 4, 1])
        with nav_l:
            st.button("◀ Previous", on_click=go_prev, disabled=(idx == 0),
                      use_container_width=True, key="btn_prev")
        with nav_c:
            # Parse score info for display from Design_Concept string
            try:
                _dc = json.loads(st.session_state.all_graphs_json[idx]).get("Design_Concept", "")
            except Exception:
                _dc = ""
            st.markdown(
                f"<div style='text-align:center;padding:8px 0'>"
                f"<span style='color:#60A5FA;font-size:1.1rem;font-weight:700'>📊 Graph Rank #{idx+1} / {total}</span><br>"
                f"<span style='color:#7090C0;font-size:0.82rem'>{_dc[:120]}{'…' if len(_dc)>120 else ''}</span>"
                f"</div>",
                unsafe_allow_html=True,
            )
        with nav_r:
            st.button("Next ▶", on_click=go_next, disabled=(idx == total - 1),
                      use_container_width=True, key="btn_next")
        st.markdown("---")

        st.success(f"🧬 **แสดง Graph Rank #{idx+1}/{total}** — ใช้ปุ่ม ◀ / ▶ เพื่อสลับ Rank โดยไม่ต้องกลับ Tab 1")
        if st.button("🗑️ รีเซ็ตข้อมูลทั้งหมด", key="mc_clear"):
            st.session_state.generated_adjacency_json = None
            st.session_state.all_graphs_json          = []
            st.session_state.selected_rank_index      = 0
            st.session_state.plan_generated           = False
            st.session_state.graph_results            = None
            st.rerun()

    elif st.session_state.generated_adjacency_json:
        # Legacy: data sent via old single-button path
        st.success("🧬 **ข้อมูลกราฟถูกซิงค์เรียบร้อยแล้ว**")
        if st.button("🗑️ รีเซ็ตข้อมูล", key="mc_clear_legacy"):
            st.session_state.generated_adjacency_json = None
            st.session_state.plan_generated           = False
            st.session_state.graph_results            = None
            st.rerun()

    with st.expander("🛠️ Debug / Manual JSON Input", expanded=False):
        _default_json = st.session_state.generated_adjacency_json or "{}"
        user_json = st.text_area("JSON from Generator", value=_default_json, height=200)
    
    # Determine active JSON for rendering
    if st.session_state.all_graphs_json:
        active_json = st.session_state.all_graphs_json[st.session_state.selected_rank_index]
    elif st.session_state.generated_adjacency_json:
        active_json = st.session_state.generated_adjacency_json
    else:
        active_json = user_json

    if st.button("✨ Generate Schematic Packed Plan (Manual Trigger)", type="primary"):
        try:
            test_data = json.loads(active_json)
            if "Adjacency_Rules" in test_data and "Adjacency" not in test_data:
                st.error("❌ ข้อมูลผิดประเภท! โครงสร้างนี้คือ 'กฎจาก AI' คุณต้องนำมันไปวางใน Tab 1 เพื่อให้ระบบวิเคราะห์เป็นกราฟก่อนครับ")
                st.stop()
            st.session_state.plan_generated = True
        except Exception:
            pass

# ════════════════════════════════════════════════════════════════
# ระบบประมวลผลข้อมูลร่วมสำหรับ Tab 2 และ Tab 3
# ════════════════════════════════════════════════════════════════
if st.session_state.get("plan_generated", False):
    try:
        # Use active_json as the source of truth
        if st.session_state.all_graphs_json:
            _render_json = st.session_state.all_graphs_json[st.session_state.selected_rank_index]
        elif st.session_state.generated_adjacency_json:
            _render_json = st.session_state.generated_adjacency_json
        else:
            _render_json = user_json

        data = json.loads(_render_json)
        if "Space_Requirement" not in data or "Adjacency" not in data:
            st.error("❌ ข้อผิดพลาด: ไม่พบข้อมูลที่จำเป็น กรุณากลับไปส่งค่าจาก Tab 1 ใหม่อีกครั้ง")
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

        SITE_W    = st.session_state.get("site_width",  8.0)
        SITE_L    = st.session_state.get("site_length", 4.0)
        SITE_AREA = SITE_W * SITE_L
        scale_ratio = SITE_AREA / t_gross if t_gross > 0 else 1

        G = nx.Graph()
        for r in rooms_list: G.add_node(r)
        WM = {3: 4.0, 2: 2.5, 1: 1.0, -1: 0.02}
        for adj in data["Adjacency"]:
            r1, r2, sc = adj["room1"], adj["room2"], adj["score"]
            if r1 in rooms_list and r2 in rooms_list:
                G.add_edge(r1, r2, weight=WM.get(sc, 1.0))
        sp = nx.spring_layout(G, weight="weight", seed=42)
        sorted_rooms  = sorted(rooms_list, key=lambda r: sp[r][1], reverse=True)
        items_to_pack = [(r, df.loc[df["room"]==r, "Gross_sqm"].values[0] * scale_ratio) for r in sorted_rooms]
        layout_rects  = generate_treemap(items_to_pack, 0, 0, SITE_W, SITE_L)
        room_lookup   = {rd["room"]: rd for rd in layout_rects}

        with tab2:
            st.markdown("---")
            st.markdown("### 📊 1. Space Requirement")
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("📐 Net Area",       f"{t_net:.2f} ตร.ม.")
            m2.metric("🏗️ Gross Area",    f"{t_gross:.2f} ตร.ม.")
            m3.metric("🟩 Site Box",       f"{SITE_AREA:.2f} ตร.ม.")
            m4.metric("⚖️ Scaling Factor", f"x {scale_ratio:.2f}")

            st.dataframe(df.style.format("{:.2f}", subset=["net_area_sqm", clbl, "Gross_sqm"]), width="stretch")

            st.markdown("---")
            st.markdown("### 🧮 2. Adjacency Matrix (Generated from Engine)")
            mat = pd.DataFrame(0, index=rooms_list, columns=rooms_list)
            for adj in data["Adjacency"]:
                r1, r2, sc = adj["room1"], adj["room2"], adj["score"]
                if r1 in rooms_list and r2 in rooms_list:
                    mat.at[r1, r2] = sc; mat.at[r2, r1] = sc

            fig_h = go.Figure(data=go.Heatmap(
                z=mat.values, x=rooms_list, y=rooms_list, colorscale="RdYlGn", zmin=-1, zmax=3, zmid=0,
                colorbar=dict(thickness=15, len=0.8), xgap=2, ygap=2
            ))
            fig_h.update_layout(height=500, plot_bgcolor="#0F1624", paper_bgcolor="#0F1624")
            st.plotly_chart(fig_h, width="stretch")

            st.markdown("---")
            st.markdown("### 🕸️ 3. Relationship Network Graph")
            n = len(rooms_list); angles = [2*math.pi*i/n for i in range(n)]
            pn = {r: (math.cos(a), math.sin(a)) for r, a in zip(rooms_list, angles)}
            ES = {
                 3: dict(c="#FF4D4D", w=5,   d="solid", l="Score 3 — must adjacent"),
                 2: dict(c="#FFD700", w=3,   d="solid", l="Score 2 — should be near"),
                 1: dict(c="#4CAF50", w=1.5, d="dot",   l="Score 1 — neutral"),
                -1: dict(c="#888888", w=1.5, d="dash",  l="Score -1 — keep apart"),
            }
            fig_n = go.Figure(); dl = set()
            for adj in data["Adjacency"]:
                r1, r2, sc = adj["room1"], adj["room2"], adj["score"]
                if r1 not in pn or r2 not in pn: continue
                s = ES.get(sc, ES[1]); x0, y0 = pn[r1]; x1, y1 = pn[r2]
                show = s["l"] not in dl; dl.add(s["l"])
                fig_n.add_trace(go.Scatter(x=[x0, x1, None], y=[y0, y1, None], mode="lines",
                    line=dict(color=s["c"], width=s["w"], dash=s["d"]), name=s["l"],
                    legendgroup=s["l"], showlegend=show, hoverinfo="skip"))

            na = [df.loc[df["room"]==r, "net_area_sqm"].values[0] for r in rooms_list]
            fig_n.add_trace(go.Scatter(
                x=[pn[r][0] for r in rooms_list], y=[pn[r][1] for r in rooms_list],
                mode="markers+text",
                marker=dict(size=[max(44, a*7) for a in na], color=[pal[r] for r in rooms_list],
                            line=dict(color="white", width=2.5)),
                text=rooms_list, textfont=dict(size=10, color="white", family="Arial Black"),
                hoverinfo="text", showlegend=False))
            fig_n.update_layout(height=520, plot_bgcolor="#0F1624", paper_bgcolor="#0F1624",
                                xaxis=dict(visible=False), yaxis=dict(visible=False))
            st.plotly_chart(fig_n, width="stretch")

            st.markdown("---")
            st.markdown("### 🟩 4. Schematic Packed Floor Plan")

            show_adj_overlay = st.toggle("✨ Premium Adjacency Overlay", value=True)
            BG = "#0F1624"; ANNO_CLR = "#FFD700"; OUTER_PAD = max(SITE_W, SITE_L) * 0.15
            fig_bp = go.Figure()
            pos_packed = {}
            pad = 0.04
            room_opacity = 0.35 if show_adj_overlay else 0.92

            for r_data in layout_rects:
                room, rx, ry, rw, rh = r_data['room'], r_data['x'], r_data['y'], r_data['w'], r_data['h']
                cx, cy = rx + rw/2.0, ry + rh/2.0
                pos_packed[room] = [cx, cy]
                fig_bp.add_shape(type="rect", x0=rx+pad, y0=ry+pad, x1=rx+rw-pad, y1=ry+rh-pad,
                                 fillcolor=pal[room], opacity=room_opacity,
                                 line=dict(color="#FFFFFF", width=1.5), layer="below")

            def check_adjacency(r1_name, r2_name, tol=0.1):
                r1 = room_lookup.get(r1_name); r2 = room_lookup.get(r2_name)
                if not r1 or not r2: return False
                return not (r1['x'] > r2['x'] + r2['w'] + tol or r1['x'] + r1['w'] < r2['x'] - tol or
                            r1['y'] > r2['y'] + r2['h'] + tol or r1['y'] + r1['h'] < r2['y'] - tol)

            if show_adj_overlay:
                for adj in data.get("Adjacency", []):
                    r1, r2, sc = adj.get("room1"), adj.get("room2"), adj.get("score", 0)
                    if r1 in pos_packed and r2 in pos_packed and sc >= 2:
                        x0, y0 = pos_packed[r1]; x1, y1 = pos_packed[r2]
                        line_color = "#FF4D4D" if sc == 3 else "#FFD700"
                        bx, by = get_bezier_curve([x0, y0], [x1, y1], offset_ratio=0.12)
                        fig_bp.add_trace(go.Scatter(x=bx, y=by, mode="lines",
                            line=dict(color="#0F1624", width=8), hoverinfo="skip", showlegend=False))
                        fig_bp.add_trace(go.Scatter(x=bx, y=by, mode="lines",
                            line=dict(color=line_color, width=3.5 if sc==3 else 2.5,
                                      dash="solid" if sc==3 else "dot"), showlegend=False))

            for r_data in layout_rects:
                room = r_data['room']
                cx   = r_data['x'] + r_data['w'] / 2.0
                cy   = r_data['y'] + r_data['h'] / 2.0
                rh   = r_data['h']
                fig_bp.add_trace(go.Scatter(x=[cx], y=[cy + rh*0.14], mode="text", text=[room],
                    textfont=dict(size=13, color="white", family="Arial Black"),
                    showlegend=False, hoverinfo="skip"))

            fig_bp.add_shape(type="rect", x0=0, y0=0, x1=SITE_W, y1=SITE_L,
                             line=dict(color=ANNO_CLR, width=3),
                             fillcolor="rgba(0,0,0,0)", layer="above")
            fig_bp.update_layout(
                height=max(500, int(500*(SITE_L+2*OUTER_PAD)/(SITE_W+2*OUTER_PAD))),
                plot_bgcolor=BG, paper_bgcolor=BG,
                xaxis=dict(visible=False, scaleanchor="y", scaleratio=1),
                yaxis=dict(visible=False),
                margin=dict(l=20, r=20, t=40, b=20)
            )
            st.plotly_chart(fig_bp, width="stretch", config={"scrollZoom": True})

            st.markdown("### 🧠 5. AI Design Concept")
            st.info(f"💡 {data.get('Design_Concept', '')}")

        # ════════════════════════════════════════════════════════
        # 🪑  TAB 3
        # ════════════════════════════════════════════════════════
        with tab3:
            st.markdown("### 🚪 6. AI Prompt — Openings + Furniture")
            st.markdown('<div class="note"><b>💡 Two-Stage AI Flow:</b> คัดลอก Prompt ด้านล่างไปส่งให้ AI อีกรอบ เพื่อได้ช่องเปิด + เฟอร์นิเจอร์ที่ลงตัวตามพิกัดห้อง</div>', unsafe_allow_html=True)

            packed_plan_for_prompt = [
                {"room": rd["room"], "x": round(rd["x"], 3), "y": round(rd["y"], 3),
                 "w": round(rd["w"], 3), "h": round(rd["h"], 3), "orientation_deg": 0.0}
                for rd in layout_rects
            ]
            auto_prompt_b = {
                "system_prompt": "คุณคือสถาปนิกระดับ Senior และผู้เชี่ยวชาญด้าน Space Planning ที่แม่นยำทางคณิตศาสตร์ — ตอบกลับเป็น JSON เท่านั้น ห้ามมีข้อความอื่นนอกกรอบ JSON",
                "user_prompt": "รับข้อมูล 'Packed_Plan' (สี่เหลี่ยมจัดสรรพื้นที่) — คืนค่า Openings (ประตู/หน้าต่าง) และ Furniture placement โดยต้องทำตามกฎพิกัด Local Coordinates และ Mathematical Bounding อย่างเคร่งครัด",
                "strict_mathematical_rules": {
                    "1_coordinate_system": {"type": "Local / Relative Coordinates", "rule": "พิกัด x_m และ y_m ของเฟอร์นิเจอร์ทุกชิ้น จะต้องเริ่มต้นที่ (0,0) ซึ่งหมายถึง 'มุมซ้ายล่างของห้องนั้นๆ' เสมอ"},
                    "2_furniture_bounding_box": {"rule": "เฟอร์นิเจอร์ต้องไม่ล้นออกนอกขอบเขตห้อง", "x_axis_clamp": "0 <= x_m <= (Room_w - Furniture_w)", "y_axis_clamp": "0 <= y_m <= (Room_h - Furniture_d)"},
                    "3_openings_bounding": {"rule": "ตำแหน่ง offset_m ของประตูและหน้าต่างต้องไม่เกินความกว้างหรือยาวของกำแพงห้อง", "north_south_walls": "0 <= offset_m <= (Room_w - Opening_width)", "east_west_walls": "0 <= offset_m <= (Room_h - Opening_width)"},
                    "4_clearance_overlap": {"rule": "ตรวจสอบ clearance_m ของเฟอร์นิเจอร์แต่ละชิ้น ไม่ให้ทับซ้อนกับระยะเดินหรือสวิงประตูภายใน Local Room นั้นๆ"}
                },
                "constraints_data": {"walkway_clearance_m": 0.6, "seating_clearance_m": 0.8, "bed_clearance_m": 0.5, "door_min_width_m": 0.8, "window_min_width_m": 0.6},
                "Packed_Plan": packed_plan_for_prompt,
                "metadata": {"site_width_m": SITE_W, "site_length_m": SITE_L, "scale_factor": round(scale_ratio, 4)},
                "required_output_schema": {
                    "Openings": [{"id": "string", "room": "string", "wall": "string (north|south|east|west)", "offset_m": "float", "width_m": "float", "height_m": "float", "sill_height_m": "float", "type": "string (window|door|sliding|fixed)"}],
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
                    {"id":"D1","room":layout_rects[0]["room"] if layout_rects else "","wall":"south","offset_m":0.5,"width_m":0.9,"height_m":2.1,"sill_height_m":0.0,"type":"door"},
                    {"id":"W1","room":layout_rects[-1]["room"] if layout_rects else "","wall":"north","offset_m":1.0,"width_m":1.2,"height_m":1.2,"sill_height_m":0.9,"type":"window"},
                ],
                "Furniture": [
                    {"id":"F1","room":layout_rects[0]["room"] if layout_rects else "","type":"table","w_m":1.0,"d_m":0.6,"h_m":0.75,"x_m":0.3,"y_m":0.3,"orientation_deg":0,"clearance_m":0.6,"placement_mode":"free"},
                ],
                "Checks": {"overlaps":[],"clearance_violations":[],"door_swing_conflicts":[]},
            }, ensure_ascii=False, indent=2)

            of_json = st.text_area("⬇️ วาง Openings + Furniture JSON จาก AI (Prompt B)", value=MOCK_OF, height=200, key="of_json")

            if st.button("🪑 Visualize Openings + Furniture", type="primary"):
                try:
                    of_data = json.loads(of_json)
                    if "Openings" not in of_data and "Furniture" not in of_data:
                        st.error("❌ ข้อผิดพลาด: ไม่พบคีย์ 'Openings' หรือ 'Furniture'")
                        st.stop()

                    openings  = of_data.get("Openings", [])
                    furniture = of_data.get("Furniture", [])
                    checks    = of_data.get("Checks", {})

                    fig_of = go.Figure()
                    pad_of = 0.04
                    for rd in layout_rects:
                        rm, rx, ry, rw, rh = rd["room"], rd["x"], rd["y"], rd["w"], rd["h"]
                        fig_of.add_shape(type="rect", x0=rx+pad_of, y0=ry+pad_of, x1=rx+rw-pad_of, y1=ry+rh-pad_of,
                                         fillcolor=pal.get(rm, "#4E79A7"), opacity=0.35,
                                         line=dict(color="#FFFFFF", width=1.5), layer="below")
                        fig_of.add_annotation(x=rx+rw/2, y=ry+rh/2, text=rm, showarrow=False,
                                              font=dict(size=10, color="#C8DCFF", family="Arial Black"))

                    OPEN_CLR = {"door":"#FF6B6B","window":"#4ECDC4","sliding":"#FFE66D","fixed":"#95E1D3"}
                    for op in openings:
                        rm = op.get("room","")
                        if rm not in room_lookup: continue
                        rd = room_lookup[rm]; wall = op.get("wall","south"); off = op.get("offset_m", 0); ow = op.get("width_m", 0.9)
                        ot = op.get("type","door"); clr = OPEN_CLR.get(ot, "#FFFFFF")

                        if wall == "south":  x0 = rd["x"] + off; y0 = rd["y"];          x1 = x0 + ow; y1 = y0
                        elif wall == "north": x0 = rd["x"] + off; y0 = rd["y"] + rd["h"]; x1 = x0 + ow; y1 = y0
                        elif wall == "west":  x0 = rd["x"];        y0 = rd["y"] + off;    x1 = x0;       y1 = y0 + ow
                        else:                x0 = rd["x"] + rd["w"]; y0 = rd["y"] + off; x1 = x0;       y1 = y0 + ow

                        fig_of.add_trace(go.Scatter(x=[x0, x1], y=[y0, y1], mode="lines",
                                                    line=dict(color=clr, width=6), showlegend=False))
                        fig_of.add_annotation(x=(x0+x1)/2, y=(y0+y1)/2, text=op.get("id",""),
                                              showarrow=False, font=dict(size=8, color=clr))

                    FURN_CLR = "#A78BFA"
                    for fi_item in furniture:
                        rm = fi_item.get("room","")
                        if rm not in room_lookup: continue
                        rd = room_lookup[rm]
                        fx = rd["x"] + fi_item.get("x_m", 0)
                        fy = rd["y"] + fi_item.get("y_m", 0)
                        fw = fi_item.get("w_m", 0.5)
                        fd = fi_item.get("d_m", 0.5)

                        fig_of.add_shape(type="rect", x0=fx, y0=fy, x1=fx+fw, y1=fy+fd,
                                         fillcolor=FURN_CLR, opacity=0.55, line=dict(color="#FFFFFF", width=1))
                        cl = fi_item.get("clearance_m", 0)
                        if cl > 0:
                            fig_of.add_shape(type="rect", x0=fx-cl, y0=fy-cl, x1=fx+fw+cl, y1=fy+fd+cl,
                                             fillcolor="rgba(0,0,0,0)", opacity=0.4,
                                             line=dict(color=FURN_CLR, width=1, dash="dot"))
                        fig_of.add_annotation(x=fx+fw/2, y=fy+fd/2,
                                              text=f"{fi_item.get('id','')}<br>{fi_item.get('type','')}",
                                              showarrow=False, font=dict(size=7, color="#E8F0FF"))

                    fig_of.add_shape(type="rect", x0=0, y0=0, x1=SITE_W, y1=SITE_L,
                                     line=dict(color="#FFD700", width=3), fillcolor="rgba(0,0,0,0)")
                    fig_of.update_layout(
                        height=max(520, int(520*(SITE_L+1.5)/(SITE_W+1.5))),
                        plot_bgcolor=BG, paper_bgcolor=BG,
                        xaxis=dict(visible=False, scaleanchor="y", scaleratio=1),
                        yaxis=dict(visible=False),
                        margin=dict(l=20, r=20, t=50, b=20)
                    )
                    st.plotly_chart(fig_of, width="stretch", config={"scrollZoom": True})

                    # 8. Validation Checks
                    st.markdown("---")
                    st.markdown("### ✅ 8. Validation Checks")
                    overlaps      = checks.get("overlaps", [])
                    cl_violations = checks.get("clearance_violations", [])
                    swing_conf    = checks.get("door_swing_conflicts", [])

                    vc1, vc2, vc3 = st.columns(3)
                    vc1.metric("🔴 Overlaps",   len(overlaps),      delta="⚠️ Found!" if overlaps      else "✅ None", delta_color="inverse" if overlaps      else "normal")
                    vc2.metric("🟡 Clearance",  len(cl_violations), delta="⚠️ Found!" if cl_violations else "✅ None", delta_color="inverse" if cl_violations else "normal")
                    vc3.metric("🟠 Door Swing", len(swing_conf),    delta="⚠️ Found!" if swing_conf    else "✅ None", delta_color="inverse" if swing_conf    else "normal")

                    auto_warnings = []
                    for fi_item in furniture:
                        rm = fi_item.get("room","")
                        if rm not in room_lookup: continue
                        rd = room_lookup[rm]
                        fx, fy, fw, fd = fi_item.get("x_m",0), fi_item.get("y_m",0), fi_item.get("w_m",0), fi_item.get("d_m",0)
                        if fx < 0 or fy < 0 or fx+fw > rd["w"]+0.01 or fy+fd > rd["h"]+0.01:
                            auto_warnings.append(f"⚠️ {fi_item.get('id','')} ({fi_item.get('type','')}) ใน {rm} ล้นออกนอกขอบห้อง!")

                    for op in openings:
                        ow = op.get("width_m", 0)
                        if op.get("type") == "door"   and ow < 0.8: auto_warnings.append(f"⚠️ {op.get('id','')} door width {ow}m < 0.8m")
                        if op.get("type") == "window" and ow < 0.6: auto_warnings.append(f"⚠️ {op.get('id','')} window width {ow}m < 0.6m")

                    if overlaps:      st.warning("**Overlap Details:**");            st.json(overlaps)
                    if cl_violations: st.warning("**Clearance Violation Details:**"); st.json(cl_violations)
                    if swing_conf:    st.warning("**Door Swing Conflict Details:**"); st.json(swing_conf)
                    if auto_warnings:
                        st.warning("**Auto-detected Warnings:**")
                        for w in auto_warnings: st.markdown(f"- {w}")

                    if not overlaps and not cl_violations and not swing_conf and not auto_warnings:
                        st.success("✅ All checks passed — สมบูรณ์แบบ! ไม่พบ overlap หรือจุดบกพร่อง")

                    st.markdown("---")
                    st.markdown("### 📦 Final AI Result JSON (Complete)")
                    final_json = {
                        "Packed_Plan": packed_plan_for_prompt, "Openings": openings,
                        "Furniture": furniture, "Checks": checks,
                        "metadata": {
                            "site_width_m":    SITE_W, "site_length_m": SITE_L,
                            "scale_factor":    round(scale_ratio, 4),
                            "total_net_sqm":   round(t_net, 2),
                            "total_gross_sqm": round(t_gross, 2),
                        },
                    }
                    st.code(json.dumps(final_json, ensure_ascii=False, indent=2), language="json")

                except Exception as e2:
                    st.error(f"❌ Openings/Furniture JSON ไม่ถูกต้อง: {e2}")

    except Exception as e:
        st.error(f"❌ เกิดข้อผิดพลาดในระบบแสดงผล: {e}")
