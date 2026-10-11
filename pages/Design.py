"""AI Architecture — Neuro-Symbolic Design Pipeline (Streamlit page).

    Prompt A (LLM writes C/W rules) -> MatrixController (random graph search scored by sum C*W)
    -> spring layout + slice-and-dice treemap (packed plan) -> Prompt B (openings + furniture)

simple : one linear flow per tab, one source of truth for the active plan, callbacks instead of reruns
stable : seeded RNG, process-independent layout, every pasted AI JSON validated, nothing vanishes on rerun
fast   : vectorised graph search, few Plotly traces/shapes per figure, no Styler, no redundant st.rerun()

Everything except `main()` is a pure function, so tests can import this file without a Streamlit server.
"""
import html
import json
import math
import re
import secrets
import zlib

import networkx as nx
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# ══════════════════════════════════════════
# 🎨  Design tokens
# ══════════════════════════════════════════
ROOM_OPTIONS  = ["Bedroom", "Living Area", "Kitchen", "Dining", "Bathroom", "Balcony", "Laundry", "Closet"]
DEFAULT_ROOMS = ["Bedroom", "Living Area", "Kitchen", "Dining", "Bathroom", "Closet"]
DEFAULT_AREAS = {
    "Bedroom": 7.0, "Living Area": 7.0, "Kitchen": 6.0, "Dining": 6.0,
    "Bathroom": 3.0, "Balcony": 2.5, "Laundry": 2.0, "Closet": 3.0,
}
AUTO_MODE, MANUAL_MODE = "Auto (Neufert / Thai Building Code)", "Manual (ผู้ใช้กำหนดเอง)"
MIN_AREA = 0.01          # m² floor: a zero / negative / non-numeric AI area can never break the treemap

ROOM_PALETTE = {
    "Living Area": "#4E79A7", "Bedroom": "#E15759", "Dining": "#F28E2B",
    "Kitchen": "#59A14F", "Bathroom": "#76B7B2", "Closet": "#B07AA1",
    "Balcony": "#EDC948", "Laundry": "#FF9DA7",
}
FALLBACK = ["#4E79A7", "#E15759", "#F28E2B", "#59A14F",
            "#76B7B2", "#B07AA1", "#EDC948", "#FF9DA7", "#BAB0AC", "#D37295"]

BG, INK, GOLD = "#0F1624", "#C8DCFF", "#FFD700"
PAD = 0.04               # inset of a room rectangle inside its slot (m)

# adjacency score -> line style in the network graph / pull strength in the spring layout
EDGE_STYLE = {
     3: dict(color="#FF4D4D", width=5,   dash="solid", label="Score 3 — must adjacent"),
     2: dict(color="#FFD700", width=3,   dash="solid", label="Score 2 — should be near"),
     1: dict(color="#4CAF50", width=1.5, dash="dot",   label="Score 1 — neutral"),
    -1: dict(color="#888888", width=1.5, dash="dash",  label="Score -1 — keep apart"),
}
PULL = {3: 4.0, 2: 2.5, 1: 1.0, -1: 0.02}
OPENING_COLOR = {"door": "#FF6B6B", "window": "#4ECDC4", "sliding": "#FFE66D", "fixed": "#95E1D3"}
FURNITURE_COLOR = "#A78BFA"

CSS = """
<style>
  [data-testid="stAppViewContainer"] { background:#0F1624; }
  [data-testid="stHeader"]           { background:transparent; }

  .hero {
    background:linear-gradient(135deg,#0D1B35 0%,#1A2E55 55%,#0F3460 100%);
    border:1px solid #1E3A6E; border-radius:18px;
    padding:30px 40px 26px 40px; margin-bottom:28px;
  }
  .hero h1 { color:#E8F0FF !important; margin:0 0 8px 0; font-size:2rem; }
  .hero p  { color:#7090C0; margin:0; font-size:0.93rem; }

  /* cards = st.container(border=True, key="card_*") */
  [class*="st-key-card_"] { background:#141C2E; border:1px solid #1E2E4A; border-radius:14px; padding:22px 26px; }

  /* stMetric is the current test id; metric-container is kept for older Streamlit */
  [data-testid="stMetric"], [data-testid="metric-container"] {
    background:#1A2540; border:1px solid #243358; border-left:4px solid #3B82F6;
    border-radius:12px; padding:14px 18px;
  }
  [data-testid="stMetricLabel"], [data-testid="metric-container"] label { color:#7090C0 !important; }
  [data-testid="stMetricValue"]                                           { color:#E8F0FF !important; }

  [data-baseweb="tab-list"] { gap:6px; background:transparent !important; }
  [data-baseweb="tab"] {
    background:#141C2E !important; border:1px solid #1E2E4A !important;
    border-radius:10px 10px 0 0 !important; padding:10px 24px !important;
    color:#7090C0 !important; font-weight:600 !important;
  }
  [aria-selected="true"] { background:#1A2540 !important; border-bottom-color:#3B82F6 !important; color:#60A5FA !important; }

  [data-testid="stTextInput"] input, [data-testid="stNumberInput"] input {
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
    background:#0D1E3A; border-left:4px solid #3B82F6; border-radius:8px;
    padding:14px 18px; font-size:0.87rem; color:#90B4D8; margin:14px 0; line-height:1.7;
  }
  .rank-bar { background:#1A2540; border-radius:8px; padding:4px 8px; margin:4px 0 22px 0; }
  .rank-bar div { height:10px; border-radius:5px; }
</style>
"""

HERO = """
<div class="hero">
  <h1>🏛️ AI Architecture: Neuro-Symbolic Design Pipeline</h1>
  <p>Program Definition &rarr; AI Rule Generation (LLM) &rarr; Deterministic Graph Engine &rarr; Packed Floor Plan</p>
</div>
"""

ENGINE_NOTE = (
    '<div class="note">'
    '<b>📖 การทำงานแบบ Hybrid:</b><br>'
    '1. วาง JSON จาก AI ที่ได้ในกล่องด้านล่าง เพื่อให้ระบบ <b>Extract กฎคณิตศาสตร์ (C & W)</b> อัตโนมัติ<br>'
    '2. กด <b>Generate</b> เพื่อให้ระบบคณิตศาสตร์ในแอปสุ่มหา Graph ที่สอดคล้องกับกฎของ AI ได้แม่นยำที่สุด 100% ไร้ข้อผิดพลาดทางตรรกะ'
    '</div>'
)


# ══════════════════════════════════════════
# 🧰  Small helpers (all AI/user JSON goes through these)
# ══════════════════════════════════════════
def _num(value, default=None):
    """float(value) or `default` for None / text / NaN / inf."""
    try:
        x = float(value)
    except (TypeError, ValueError):
        return default
    return x if math.isfinite(x) else default


def _clamp_int(value, lo, hi):
    """Nearest int in [lo, hi]; anything non-numeric -> 0 (= 'no rule')."""
    x = _num(value, 0.0)
    return int(min(hi, max(lo, round(x))))


def _dicts(value):
    """The dict items of a JSON list (anything else -> [])."""
    return [v for v in value if isinstance(v, dict)] if isinstance(value, list) else []


def _as_list(value):
    """A JSON value as a list: list as is, null / "" -> [], a lone item -> [item]."""
    return value if isinstance(value, list) else ([] if value in (None, "") else [value])


_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.S | re.I)


def parse_json_text(text):
    """json.loads that also accepts what chat UIs wrap around JSON: ```json fences or a sentence before/after."""
    raw = (text or "").strip().lstrip("\ufeff")
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        match = _FENCE.search(raw)
        body = match.group(1) if match else raw[raw.find("{"): raw.rfind("}") + 1]
        if not body.strip() or body.strip() == raw:
            raise                      # nothing to unwrap -> the original error is the useful one
        return json.loads(body)


def clean_space(rows):
    """Space_Requirement rows -> ([{room, net_area_sqm > 0}] with unique rooms, warnings)."""
    out, seen, warnings = [], set(), []
    for row in _dicts(rows):
        room = row.get("room")
        if not isinstance(room, str) or not room.strip() or room in seen:
            warnings.append(f"ข้ามแถวที่ไม่มีชื่อห้อง หรือชื่อห้องซ้ำ: {room!r}")
            continue
        area = _num(row.get("net_area_sqm"))
        if area is None or area <= 0:
            warnings.append(f"ห้อง {room}: พื้นที่ไม่ถูกต้อง ({row.get('net_area_sqm')!r}) → ใช้ {MIN_AREA} ตร.ม. แทน")
            area = MIN_AREA
        seen.add(room)
        out.append({"room": room, "net_area_sqm": area})
    return out, warnings


def quality_pct(score, s_max):
    return max(0.0, min(100.0, score / s_max * 100)) if s_max > 0 else 0.0


# ══════════════════════════════════════════════════════════════
# 🧬  MatrixController — Chaillou Dual-Matrix Quality Engine
# ══════════════════════════════════════════════════════════════
def _mirror_upper(M):
    """Symmetric copy of M built from its upper triangle (the half the engine reads), blanks -> 0, zero diagonal."""
    upper = np.triu(np.nan_to_num(np.asarray(M, dtype=float), nan=0.0, posinf=0.0, neginf=0.0), 1)
    return upper + upper.T


class MatrixController:
    """
    Chaillou (2020) Dual-Matrix Quality Framework:
      Q(e_ij) = C[i][j] x W[i][j]
      S*(G)   = sum Q(e_ij) - sum penalty(missing critical edges)      (critical = C=+1 and W=3)

    A graph is a boolean mask over the n(n-1)/2 room pairs, so sampling, scoring and the
    connectivity pre-check are numpy one-liners. Edge lists (room-name pairs) stay the public format.
    """

    def __init__(self, rooms, C, W):
        self.rooms = list(rooms)
        n = len(self.rooms)
        self.idx = {r: i for i, r in enumerate(self.rooms)}
        self.C = _mirror_upper(np.reshape(np.asarray(C, dtype=float), (n, n)))
        self.W = _mirror_upper(np.reshape(np.asarray(W, dtype=float), (n, n)))
        i, j = np.triu_indices(n, 1)
        self._pairs = list(zip(i.tolist(), j.tolist()))                  # pair k = (rooms[i], rooms[j])
        c, w = self.C[i, j], self.W[i, j]
        self._q = c * w                                                  # Q per pair
        self._penalty = np.where((c == 1) & (w == 3), w, 0.0)            # price of a missing critical edge
        self._chain = (j - i) == 1                                       # fallback graph: rooms in a row

    # ── edge list <-> mask ────────────────────────────────────
    def _mask(self, edges):
        wanted = {frozenset(e) for e in edges}
        return np.array([frozenset((self.rooms[a], self.rooms[b])) in wanted for a, b in self._pairs], dtype=bool)

    def _edges(self, mask):
        return [(self.rooms[a], self.rooms[b]) for (a, b), on in zip(self._pairs, mask) if on]

    # ── scoring ───────────────────────────────────────────────
    def edge_score(self, r1, r2):
        i, j = self.idx.get(r1, -1), self.idx.get(r2, -1)
        return 0.0 if i < 0 or j < 0 else float(self.C[i, j] * self.W[i, j])

    def _score(self, mask):
        return float(self._q[mask].sum() - self._penalty[~mask].sum())

    def graph_score(self, edges):
        return self._score(self._mask(edges))

    def max_theoretical_score(self):
        best = float(self._q[self._q > 0].sum())
        return best if best > 0 else 1.0

    # ── sampling ──────────────────────────────────────────────
    def _connected(self, mask):
        n = len(self.rooms)
        if n < 2:
            return True
        adj = [[] for _ in range(n)]
        for k in np.flatnonzero(mask).tolist():
            a, b = self._pairs[k]
            adj[a].append(b)
            adj[b].append(a)
        seen, stack = {0}, [0]
        while stack:
            for nb in adj[stack.pop()]:
                if nb not in seen:
                    seen.add(nb)
                    stack.append(nb)
        return len(seen) == n

    def _probabilities(self, T):
        """sigmoid(Q/T): a wish (Q>0) is drawn almost always, neutral pairs (Q=0) half the time, a veto (Q<0) rarely."""
        return 1.0 / (1.0 + np.exp(np.clip(-self._q / max(float(T), 1e-9), -50, 50)))

    def _sample(self, rng, p, max_attempts=500, batch=64):
        """First connected Bernoulli sample of the edge set (rejection sampling), or None.

        Draws come `batch` rows at a time and rows with fewer than n-1 edges are discarded without a
        graph search, so even a matrix that almost never connects costs milliseconds, not seconds."""
        need = len(self.rooms) - 1
        for start in range(0, max_attempts, batch):
            draws = rng.random((min(batch, max_attempts - start), len(p))) < p
            for row in np.flatnonzero(draws.sum(axis=1) >= need):
                if self._connected(draws[row]):
                    return draws[row]
        return None

    def generate_graph(self, T=0.7, max_attempts=500, rng=None):
        rng = np.random.default_rng() if rng is None else rng
        mask = self._sample(rng, self._probabilities(T), max_attempts)
        return self._edges(self._chain if mask is None else mask)

    def filter_best_graphs(self, N=100, top_k=5, T=0.7, seed=None):
        """Top-k *distinct* connected graphs out of N samples as [(edges, S*)]; the same seed gives the same answer."""
        rng = np.random.default_rng(seed)
        p = self._probabilities(T)
        found = {}                                       # mask bytes -> (score, mask), in discovery order
        for _ in range(N):
            mask = self._sample(rng, p)
            mask = self._chain if mask is None else mask.copy()
            found.setdefault(mask.tobytes(), (self._score(mask), mask))
        ranked = sorted(found.values(), key=lambda t: -t[0])             # stable: ties keep discovery order
        return [(self._edges(mask), score) for score, mask in ranked[:top_k]]

    # ── reporting ─────────────────────────────────────────────
    def get_violated_rules(self, edges):
        on, violations = self._mask(edges), []
        for k, (a, b) in enumerate(self._pairs):
            c, w = int(self.C[a, b]), int(self.W[a, b])
            if w != 3:
                continue
            r1, r2 = self.rooms[a], self.rooms[b]
            if c == 1 and not on[k]:
                violations.append(f"❌ Critical Direct Missing: **{r1} ↔ {r2}**")
            elif c == -1 and on[k]:
                violations.append(f"⚠️ Critical Separation Violated: **{r1} ↔ {r2}**")
        return violations

    def to_adjacency_json(self, edges, space_requirements, design_concept=""):
        """Engine -> renderer contract. Score 3/2/1 = Q>=3/2/1; anything weaker (Q<=0) is -1 = 'no pull' in the layout."""
        on, adjacency = self._mask(edges), []
        for k, (a, b) in enumerate(self._pairs):
            if not on[k]:
                continue
            q, c, w = float(self._q[k]) + 0.0, int(self.C[a, b]), int(self.W[a, b])
            adjacency.append({
                "room1": self.rooms[a], "room2": self.rooms[b],
                "score": 3 if q >= 3 else (2 if q >= 2 else (1 if q >= 1 else -1)),
                "reason": f"Q={q:.0f} (C={'Direct' if c == 1 else 'Indirect'}, "
                          f"W={'High' if w == 3 else ('Medium' if w == 2 else 'Low')})",
            })
        return {"Space_Requirement": space_requirements, "Adjacency": adjacency, "Design_Concept": design_concept}


# ══════════════════════════════════════════════════════════════
# 🗂️  Typology presets, AI rules, matrix edits
# ══════════════════════════════════════════════════════════════
_RULE_TABLE = {
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
}


def build_default_matrices(rooms):
    """Chaillou-inspired typology defaults -> (C, W) as list-of-lists in `rooms` order."""
    n = len(rooms)
    C = [[0] * n for _ in range(n)]
    W = [[0] * n for _ in range(n)]
    for i, r1 in enumerate(rooms):
        for j, r2 in enumerate(rooms):
            if i != j and frozenset({r1, r2}) in _RULE_TABLE:
                C[i][j], W[i][j] = _RULE_TABLE[frozenset({r1, r2})]
    return C, W


def rules_from_ai(data):
    """Validate Prompt-A output -> ({rooms, C, W, space, concept}, warnings). Raises ValueError (Thai) when unusable."""
    if not isinstance(data, dict) or not isinstance(data.get("Adjacency_Rules"), list):
        raise ValueError("JSON ไม่ถูกต้อง หรือไม่พบ Array 'Adjacency_Rules' ตาม Schema ใหม่")
    space, warnings = clean_space(data.get("Space_Requirement"))
    if not space:
        raise ValueError("ไม่พบ 'Space_Requirement' ที่ใช้ได้ (ต้องมี room และ net_area_sqm)")
    rooms = [s["room"] for s in space]
    pos, n = {r: i for i, r in enumerate(rooms)}, len(rooms)
    C, W, skipped = np.zeros((n, n), dtype=int), np.zeros((n, n), dtype=int), 0
    for rule in data["Adjacency_Rules"]:
        a, b = (rule.get("room1"), rule.get("room2")) if isinstance(rule, dict) else (None, None)
        if not (isinstance(a, str) and isinstance(b, str)) or a not in pos or b not in pos or a == b:
            skipped += 1
            continue
        i, j = pos[a], pos[b]
        C[i, j] = C[j, i] = _clamp_int(rule.get("Connectivity_C"), -1, 1)
        W[i, j] = W[j, i] = _clamp_int(rule.get("Importance_W"), 0, 3)
    if skipped:
        warnings.append(f"ข้าม {skipped} กฎที่อ้างถึงห้องซึ่งไม่อยู่ใน Space_Requirement")
    return {"rooms": rooms, "C": C.tolist(), "W": W.tolist(), "space": space,
            "concept": str(data.get("Design_Concept") or "")}, warnings


def matrices_for(rooms, ai_rules):
    """(C, W, 'ai' | 'default' | 'mismatch'): AI rules when they cover exactly the selected rooms, else typology defaults."""
    if ai_rules and set(ai_rules["rooms"]) == set(rooms):
        pos = {r: i for i, r in enumerate(ai_rules["rooms"])}
        order = np.ix_([pos[r] for r in rooms], [pos[r] for r in rooms])
        return np.asarray(ai_rules["C"])[order].tolist(), np.asarray(ai_rules["W"])[order].tolist(), "ai"
    C, W = build_default_matrices(rooms)
    return C, W, ("mismatch" if ai_rules else "default")


def merge_matrix_edits(base, edited, lo, hi):
    """Symmetric matrix from a user-edited copy of `base`.

    The editor shows the full n x n grid, so the user may change (i, j) or (j, i). A cell that differs
    from `base` wins over its mirror (upper triangle wins if both halves changed); blanks are 0; values are
    rounded into [lo, hi]."""
    b = np.nan_to_num(np.asarray(base, dtype=float), nan=0.0)
    e = np.nan_to_num(np.asarray(edited, dtype=float), nan=0.0, posinf=0.0, neginf=0.0)
    merged = _mirror_upper(np.where(e != b, e, e.T))
    return np.clip(np.rint(merged), lo, hi)


def run_engine(rooms, C, W, space_req, concept, n_gen, top_k, temp, seed):
    """One Execute click -> everything Tab 1 shows and 'send to Tab 2' needs (plain data, session-state friendly)."""
    mc = MatrixController(rooms, C, W)
    s_max = mc.max_theoretical_score()
    ranked = [{"edges": edges, "score": score, "pct": quality_pct(score, s_max), "violations": mc.get_violated_rules(edges)}
              for edges, score in mc.filter_best_graphs(N=n_gen, top_k=top_k, T=temp, seed=seed)]
    return {"ranked": ranked, "S_max": s_max, "rooms": list(rooms), "C": mc.C.tolist(), "W": mc.W.tolist(),
            "space_req": space_req, "concept": concept, "seed": seed}


def plans_from_results(res):
    """Ranked graphs -> one Adjacency JSON string per rank (what Tab 2 renders)."""
    mc = MatrixController(res["rooms"], res["C"], res["W"])
    return [json.dumps(mc.to_adjacency_json(
                r["edges"], res["space_req"],
                f"{res['concept']} | [MatrixController Rank #{rank} | S*={r['score']:.1f}/{res['S_max']:.1f} ({r['pct']:.1f}%)]"),
                ensure_ascii=False, indent=2)
            for rank, r in enumerate(res["ranked"], 1)]


# ══════════════════════════════════════════════════════════════
# 📐  Packed plan: spring layout + slice-and-dice treemap
# ══════════════════════════════════════════════════════════════
def generate_treemap(items, x, y, w, h):
    """Pack ordered (room, area) pairs into the w x h box: cut where the running area is nearest half, split the longer side."""
    if not items:
        return []
    if len(items) == 1:
        return [{"room": items[0][0], "x": x, "y": y, "w": w, "h": h}]
    total = sum(a for _, a in items)
    if total <= 0:                                           # all-zero areas: share the box equally
        items, total = [(r, 1.0) for r, _ in items], float(len(items))
    acc, split, gap = 0.0, 1, float("inf")
    for k in range(1, len(items)):
        acc += items[k - 1][1]
        if abs(acc - total / 2) < gap:
            split, gap = k, abs(acc - total / 2)
    first, rest = items[:split], items[split:]
    share = sum(a for _, a in first) / total
    if w >= h:
        return (generate_treemap(first, x, y, w * share, h)
                + generate_treemap(rest, x + w * share, y, w - w * share, h))
    return (generate_treemap(first, x, y, w, h * share)
            + generate_treemap(rest, x, y + h * share, w, h - h * share))


def layout_seed(rooms, edges):
    """Seed for nx.spring_layout. crc32, not hash(): str hashes are randomised per process, which re-shuffled the plan on every restart."""
    key = json.dumps([list(rooms), sorted([min(a, b), max(a, b), s] for a, b, s in edges)], ensure_ascii=False)
    return zlib.crc32(key.encode("utf-8"))


def room_colors(rooms):
    colors, spare = {}, 0
    for r in rooms:
        if r in ROOM_PALETTE:
            colors[r] = ROOM_PALETTE[r]
        else:
            colors[r], spare = FALLBACK[spare % len(FALLBACK)], spare + 1
    return colors


def build_plan(data, site_w, site_l, circ_pct=0):
    """Adjacency JSON (dict) -> everything the views need. Raises ValueError (Thai message) on unusable input."""
    if not isinstance(data, dict):
        raise ValueError("JSON ต้องเป็น Object { ... }")
    if "Adjacency_Rules" in data and "Adjacency" not in data:
        raise ValueError("ข้อมูลผิดประเภท! โครงสร้างนี้คือ 'กฎจาก AI' คุณต้องนำมันไปวางใน Tab 1 เพื่อให้ระบบวิเคราะห์เป็นกราฟก่อนครับ")
    if "Space_Requirement" not in data or "Adjacency" not in data:
        raise ValueError("ข้อผิดพลาด: ไม่พบข้อมูลที่จำเป็น (Space_Requirement / Adjacency) กรุณากลับไปส่งค่าจาก Tab 1 ใหม่อีกครั้ง")
    space, warnings = clean_space(data["Space_Requirement"])
    if not space:
        raise ValueError("Space_Requirement ว่างเปล่า — ต้องมีอย่างน้อย 1 ห้อง")

    circ_col = f"Circulation_{circ_pct}%"
    df = pd.DataFrame(space)
    df[circ_col] = df["net_area_sqm"] * (circ_pct / 100.0)
    df["Gross_sqm"] = df["net_area_sqm"] + df[circ_col]
    rooms = df["room"].tolist()
    t_net, t_gross = float(df["net_area_sqm"].sum()), float(df["Gross_sqm"].sum())
    site_area = site_w * site_l
    scale = site_area / t_gross if t_gross > 0 else 1.0

    known, edges = set(rooms), []
    for adj in _dicts(data["Adjacency"]):
        a, b = adj.get("room1"), adj.get("room2")
        if isinstance(a, str) and isinstance(b, str) and a != b and a in known and b in known:
            edges.append((a, b, int(round(_num(adj.get("score"), 1.0)))))

    graph = nx.Graph()
    graph.add_nodes_from(rooms)
    for a, b, s in edges:
        graph.add_edge(a, b, weight=PULL.get(s, 1.0))
    pos = nx.spring_layout(graph, weight="weight", seed=layout_seed(rooms, edges))
    order = sorted(rooms, key=lambda r: (-float(pos[r][1]), r))              # top -> bottom, ties by name
    area = dict(zip(df["room"], df["Gross_sqm"] * scale))
    return {
        "df": df, "circ_col": circ_col, "rooms": rooms, "palette": room_colors(rooms), "edges": edges,
        "rects": generate_treemap([(r, float(area[r])) for r in order], 0.0, 0.0, site_w, site_l),
        "site_w": site_w, "site_l": site_l, "site_area": site_area, "scale": scale,
        "t_net": t_net, "t_gross": t_gross, "concept": str(data.get("Design_Concept") or ""), "warnings": warnings,
    }


def packed_plan(plan):
    """Rectangles as sent to the AI in Prompt B / echoed in the final JSON."""
    return [{"room": r["room"], "x": round(r["x"], 3), "y": round(r["y"], 3),
             "w": round(r["w"], 3), "h": round(r["h"], 3), "orientation_deg": 0.0} for r in plan["rects"]]


# ══════════════════════════════════════════════════════════════
# 📝  Prompts (Thai copy is product text — keep verbatim)
# ══════════════════════════════════════════════════════════════
def build_prompt_a(project, site_w, site_l, rooms, mode, areas):
    total_site_area = site_w * site_l
    max_net_area = total_site_area * 0.85
    return {
        "system_prompt": "คุณคือสถาปนิกระดับ Senior หน้าที่ของคุณคือวิเคราะห์ข้อมูลและส่งกลับเป็นรูปแบบ JSON ที่ Valid เท่านั้น ห้ามมีข้อความทักทาย, Markdown (` ```json `), หรือคำอธิบายใดๆ นอกกรอบ JSON ปีกกา {} เด็ดขาด",
        "user_input": {
            "project": project,
            "site_dimension": f"{site_w} x {site_l} m (Total {total_site_area} sqm)",
            "required_spaces": rooms,
            "sizing_mode": mode,
            "space_areas": [{"room": r, "net_area_sqm": areas[r]} for r in rooms] if mode == MANUAL_MODE else "Auto-calculate",
        },
        "strict_architectural_constraints": {
            "1_area_limit": f"ผลรวมของ 'net_area_sqm' ทุกห้องรวมกัน จะต้องไม่เกินพื้นที่ Site ({total_site_area} sqm) ลบด้วยพื้นที่ทางเดิน 15% หมายความว่า Total Net Area ต้องไม่เกิน {max_net_area:.1f} sqm เด็ดขาด",
            "2_code_compliance": "ห้องน้ำ (Bathroom) ต้องมีขนาดไม่ต่ำกว่ามาตรฐานกฎหมาย (1.5 sqm ขึ้นไป) และห้องอื่นๆ ต้องมีสัดส่วนสมจริงตามมาตรฐาน Neufert",
            "3_comprehensive_adjacency": "ใน 'Adjacency_Rules' ให้สร้างกฎสำหรับทุกคู่ห้องที่มีความสัมพันธ์ชัดเจน ต้องมีทั้งห้องที่บังคับติดกัน (C=1) และห้องที่บังคับแยกกัน (C=-1) ให้ครบถ้วน",
        },
        "required_output_schema": {
            "Space_Requirement": [{"room": "string", "net_area_sqm": "float"}],
            "Adjacency_Rules": [{
                "room1": "string",
                "room2": "string",
                "Connectivity_C": "int (-1=ควรแยก, 0=ไม่มีผล, 1=ควรติดกัน)",
                "Importance_W": "int (0=ไม่สำคัญ, 1=น้อย, 2=ปานกลาง, 3=สำคัญมาก)",
                "reason": "string (อธิบายเหตุผลสั้นๆ)",
            }],
            "Design_Concept": "string (สรุปแนวคิด Space Planning 1-2 ประโยค)",
        },
    }


def build_prompt_b(plan):
    return {
        "system_prompt": "คุณคือสถาปนิกระดับ Senior และผู้เชี่ยวชาญด้าน Space Planning ที่แม่นยำทางคณิตศาสตร์ — ตอบกลับเป็น JSON เท่านั้น ห้ามมีข้อความอื่นนอกกรอบ JSON",
        "user_prompt": "รับข้อมูล 'Packed_Plan' (สี่เหลี่ยมจัดสรรพื้นที่) — คืนค่า Openings (ประตู/หน้าต่าง) และ Furniture placement โดยต้องทำตามกฎพิกัด Local Coordinates และ Mathematical Bounding อย่างเคร่งครัด",
        "strict_mathematical_rules": {
            "1_coordinate_system": {"type": "Local / Relative Coordinates", "rule": "พิกัด x_m และ y_m ของเฟอร์นิเจอร์ทุกชิ้น จะต้องเริ่มต้นที่ (0,0) ซึ่งหมายถึง 'มุมซ้ายล่างของห้องนั้นๆ' เสมอ (ห้ามใช้พิกัด Absolute ของทั้งไซต์งาน)"},
            "2_furniture_bounding_box": {"rule": "เฟอร์นิเจอร์ต้องไม่ล้นออกนอกขอบเขตห้อง (Slice and Dice Bounding) โดยต้องเป็นไปตามสมการนี้:", "x_axis_clamp": "0 <= x_m <= (Room_w - Furniture_w)", "y_axis_clamp": "0 <= y_m <= (Room_h - Furniture_d)"},
            "3_openings_bounding": {"rule": "ตำแหน่ง offset_m ของประตูและหน้าต่างต้องไม่เกินความกว้างหรือยาวของกำแพงห้อง", "north_south_walls": "0 <= offset_m <= (Room_w - Opening_width)", "east_west_walls": "0 <= offset_m <= (Room_h - Opening_width)"},
            "4_clearance_overlap": {"rule": "ตรวจสอบ clearance_m ของเฟอร์นิเจอร์แต่ละชิ้น ไม่ให้ทับซ้อนกับระยะเดินหรือสวิงประตูภายใน Local Room นั้นๆ"},
        },
        "constraints_data": {"walkway_clearance_m": 0.6, "seating_clearance_m": 0.8, "bed_clearance_m": 0.5, "door_min_width_m": 0.8, "window_min_width_m": 0.6},
        "Packed_Plan": packed_plan(plan),
        "metadata": {"site_width_m": plan["site_w"], "site_length_m": plan["site_l"], "scale_factor": round(plan["scale"], 4)},
        "required_output_schema": {
            "Openings": [{"id": "string", "room": "string", "wall": "string (north|south|east|west)", "offset_m": "float (relative to wall start)", "width_m": "float", "height_m": "float", "sill_height_m": "float", "type": "string (window|door|sliding|fixed)"}],
            "Furniture": [{"id": "string", "room": "string", "type": "string", "w_m": "float", "d_m": "float", "h_m": "float", "x_m": "float (Local coordinate X)", "y_m": "float (Local coordinate Y)", "orientation_deg": "float (0, 90, 180, 270)", "clearance_m": "float", "placement_mode": "string (wall-mounted|free|corner|island)"}],
            "Checks": {"overlaps": ["array of structural violations"], "clearance_violations": ["array of clearance issues"], "door_swing_conflicts": ["array of swing issues"]},
        },
    }


def example_openings(rects):
    """Starter Prompt-B answer so 'Visualize' can be tried before pasting a real one."""
    first = rects[0]["room"] if rects else ""
    last = rects[-1]["room"] if rects else ""
    return json.dumps({
        "Openings": [
            {"id": "D1", "room": first, "wall": "south", "offset_m": 0.5, "width_m": 0.9, "height_m": 2.1, "sill_height_m": 0.0, "type": "door"},
            {"id": "W1", "room": last, "wall": "north", "offset_m": 1.0, "width_m": 1.2, "height_m": 1.2, "sill_height_m": 0.9, "type": "window"},
        ],
        "Furniture": [
            {"id": "F1", "room": first, "type": "table", "w_m": 1.0, "d_m": 0.6, "h_m": 0.75, "x_m": 0.3, "y_m": 0.3, "orientation_deg": 0, "clearance_m": 0.6, "placement_mode": "free"},
        ],
        "Checks": {"overlaps": [], "clearance_violations": [], "door_swing_conflicts": []},
    }, ensure_ascii=False, indent=2)


def check_openings(rects, openings, furniture):
    """Geometry the AI's own 'Checks' cannot be trusted with: furniture stays in its room, door/window minimum widths."""
    by_room = {r["room"]: r for r in rects}
    warnings = []
    for item in furniture:
        rd = by_room.get(item.get("room")) if isinstance(item.get("room"), str) else None
        if rd is None:
            continue
        x, y = _num(item.get("x_m"), 0.0), _num(item.get("y_m"), 0.0)
        w, d = _num(item.get("w_m"), 0.0), _num(item.get("d_m"), 0.0)
        if x < 0 or y < 0 or x + w > rd["w"] + 0.01 or y + d > rd["h"] + 0.01:
            warnings.append(f"⚠️ {item.get('id', '')} ({item.get('type', '')}) ใน {rd['room']} ล้นออกนอกขอบห้อง!")
    for op in openings:
        width = _num(op.get("width_m"), 0.0)
        if op.get("type") == "door" and width < 0.8:
            warnings.append(f"⚠️ {op.get('id', '')} door width {width}m < 0.8m")
        if op.get("type") == "window" and width < 0.6:
            warnings.append(f"⚠️ {op.get('id', '')} window width {width}m < 0.6m")
    return warnings


# ══════════════════════════════════════════════════════════════
# 📊  Figures — one trace per style, shapes/annotations passed in one go (Plotly validates per call)
# ══════════════════════════════════════════════════════════════
def _layout(**extra):
    return dict(plot_bgcolor=BG, paper_bgcolor=BG, font=dict(color=INK), **extra)


def show_figure(fig, **config):
    """Every figure paints its own dark palette; theme=None stops Streamlit re-colouring fonts/legends (unreadable in light mode)."""
    st.plotly_chart(fig, width="stretch", theme=None, config=config or None)


def _room_shapes(plan, opacity):
    """Room rectangles (inset by PAD) under the traces, plus the gold site outline on top."""
    shapes = [dict(type="rect", x0=r["x"] + PAD, y0=r["y"] + PAD, x1=r["x"] + r["w"] - PAD, y1=r["y"] + r["h"] - PAD,
                   fillcolor=plan["palette"][r["room"]], opacity=opacity, line=dict(color="#FFFFFF", width=1.5), layer="below")
              for r in plan["rects"]]
    shapes.append(dict(type="rect", x0=0, y0=0, x1=plan["site_w"], y1=plan["site_l"], line=dict(color=GOLD, width=3),
                       fillcolor="rgba(0,0,0,0)", layer="above"))
    return shapes


def get_bezier_curve(p0, p2, offset_ratio=0.15, num_points=30):
    """Quadratic Bézier p0 -> p2 bowed sideways by offset_ratio x length; the bow alternates with the start position."""
    p0, p2 = np.asarray(p0, dtype=float), np.asarray(p2, dtype=float)
    d = p2 - p0
    dist = float(np.hypot(d[0], d[1]))
    if dist == 0:
        return [p0[0]], [p0[1]]
    normal = np.array([-d[1], d[0]]) / dist
    direction = 1 if (p0[0] + p0[1]) % 2 > 1 else -1
    p1 = (p0 + p2) / 2.0 + normal * (dist * offset_ratio * direction)
    t = np.linspace(0, 1, num_points)[:, None]
    curve = (1 - t) ** 2 * p0 + 2 * (1 - t) * t * p1 + t ** 2 * p2
    return curve[:, 0], curve[:, 1]


def heatmap_fig(plan):
    rooms = plan["rooms"]
    pos = {r: i for i, r in enumerate(rooms)}
    z = np.zeros((len(rooms), len(rooms)))
    for a, b, s in plan["edges"]:
        z[pos[a], pos[b]] = z[pos[b], pos[a]] = s
    heat = go.Heatmap(z=z, x=rooms, y=rooms, colorscale="RdYlGn", zmin=-1, zmax=3,
                      colorbar=dict(thickness=15, len=0.8), xgap=2, ygap=2)
    return go.Figure(data=[heat], layout=_layout(height=500))


def network_fig(plan):
    rooms, n = plan["rooms"], len(plan["rooms"])
    xy = {r: (math.cos(2 * math.pi * i / n), math.sin(2 * math.pi * i / n)) for i, r in enumerate(rooms)}
    lines = {}                                                   # style key -> (xs, ys), None-separated
    for a, b, s in plan["edges"]:
        xs, ys = lines.setdefault(s if s in EDGE_STYLE else 1, ([], []))
        xs.extend([xy[a][0], xy[b][0], None])
        ys.extend([xy[a][1], xy[b][1], None])
    data = [go.Scatter(x=xs, y=ys, mode="lines", name=EDGE_STYLE[s]["label"], hoverinfo="skip",
                       line={k: EDGE_STYLE[s][k] for k in ("color", "width", "dash")})
            for s, (xs, ys) in sorted(lines.items(), reverse=True)]
    area = dict(zip(plan["df"]["room"], plan["df"]["net_area_sqm"]))
    data.append(go.Scatter(
        x=[xy[r][0] for r in rooms], y=[xy[r][1] for r in rooms], mode="markers+text",
        marker=dict(size=[max(44, area[r] * 7) for r in rooms], color=[plan["palette"][r] for r in rooms],
                    line=dict(color="white", width=2.5)),
        text=rooms, textfont=dict(size=10, color="white", family="Arial Black"),
        hovertext=[f"{r}<br>{area[r]:.1f} ตร.ม." for r in rooms], hoverinfo="text", showlegend=False))
    return go.Figure(data=data, layout=_layout(height=520, xaxis=dict(visible=False), yaxis=dict(visible=False)))


def floorplan_fig(plan, overlay=True):
    rects, W, L = plan["rects"], plan["site_w"], plan["site_l"]
    data = []
    if overlay:                                                  # weaker links first so the red ones sit on top
        centre = {r["room"]: (r["x"] + r["w"] / 2.0, r["y"] + r["h"] / 2.0) for r in rects}
        links = {2: ([], []), 3: ([], [])}
        for a, b, s in plan["edges"]:
            if s >= 2:
                bx, by = get_bezier_curve(centre[a], centre[b], offset_ratio=0.12)
                xs, ys = links[3 if s == 3 else 2]
                xs.extend([*bx, None])
                ys.extend([*by, None])
        for s, style in ((2, dict(color="#FFD700", width=2.5, dash="dot")), (3, dict(color="#FF4D4D", width=3.5, dash="solid"))):
            xs, ys = links[s]
            if xs:
                data.append(go.Scatter(x=xs, y=ys, mode="lines", line=dict(color=BG, width=8), hoverinfo="skip", showlegend=False))
                data.append(go.Scatter(x=xs, y=ys, mode="lines", line=style, hoverinfo="skip", showlegend=False))
    data.append(go.Scatter(
        x=[r["x"] + r["w"] / 2.0 for r in rects], y=[r["y"] + r["h"] / 2.0 + r["h"] * 0.14 for r in rects],
        mode="text", text=[r["room"] for r in rects], showlegend=False, hoverinfo="skip",
        textfont=dict(size=13, color="white", family="Arial Black")))
    outer = max(W, L) * 0.15
    return go.Figure(data=data, layout=_layout(
        height=max(500, int(500 * (L + 2 * outer) / (W + 2 * outer))), shapes=_room_shapes(plan, 0.35 if overlay else 0.92),
        xaxis=dict(visible=False, scaleanchor="y", scaleratio=1), yaxis=dict(visible=False),
        margin=dict(l=20, r=20, t=40, b=20)))


def openings_fig(plan, openings, furniture):
    """Rooms + openings + furniture -> (figure, ids skipped because their room is not in this plan)."""
    by_room = {r["room"]: r for r in plan["rects"]}
    shapes = _room_shapes(plan, 0.35)
    notes = [dict(x=r["x"] + r["w"] / 2, y=r["y"] + r["h"] / 2, text=r["room"], showarrow=False,
                  font=dict(size=10, color=INK, family="Arial Black")) for r in plan["rects"]]
    lines, skipped = {}, []
    for op in openings:
        rd = by_room.get(op.get("room")) if isinstance(op.get("room"), str) else None
        if rd is None:
            skipped.append(str(op.get("id", "?")))
            continue
        wall, off, width = op.get("wall", "south"), _num(op.get("offset_m"), 0.0), _num(op.get("width_m"), 0.9)
        kind = op["type"] if isinstance(op.get("type"), str) else "door"
        if wall in ("south", "north"):                           # horizontal wall: the opening slides along x
            x0, x1 = rd["x"] + off, rd["x"] + off + width
            y0 = y1 = rd["y"] if wall == "south" else rd["y"] + rd["h"]
        else:                                                    # west / east (any other value is drawn east, as before)
            y0, y1 = rd["y"] + off, rd["y"] + off + width
            x0 = x1 = rd["x"] if wall == "west" else rd["x"] + rd["w"]
        xs, ys = lines.setdefault(kind, ([], []))
        xs.extend([x0, x1, None])
        ys.extend([y0, y1, None])
        notes.append(dict(x=(x0 + x1) / 2, y=(y0 + y1) / 2, text=str(op.get("id", "")), showarrow=False,
                          font=dict(size=8, color=OPENING_COLOR.get(kind, "#FFFFFF"))))
    for item in furniture:
        rd = by_room.get(item.get("room")) if isinstance(item.get("room"), str) else None
        if rd is None:
            skipped.append(str(item.get("id", "?")))
            continue
        fx, fy = rd["x"] + _num(item.get("x_m"), 0.0), rd["y"] + _num(item.get("y_m"), 0.0)
        fw, fd, cl = _num(item.get("w_m"), 0.5), _num(item.get("d_m"), 0.5), _num(item.get("clearance_m"), 0.0)
        shapes.append(dict(type="rect", x0=fx, y0=fy, x1=fx + fw, y1=fy + fd, fillcolor=FURNITURE_COLOR, opacity=0.55,
                           line=dict(color="#FFFFFF", width=1)))
        if cl > 0:
            shapes.append(dict(type="rect", x0=fx - cl, y0=fy - cl, x1=fx + fw + cl, y1=fy + fd + cl, fillcolor="rgba(0,0,0,0)",
                               opacity=0.4, line=dict(color=FURNITURE_COLOR, width=1, dash="dot")))
        notes.append(dict(x=fx + fw / 2, y=fy + fd / 2, text=f"{item.get('id', '')}<br>{item.get('type', '')}",
                          showarrow=False, font=dict(size=7, color="#E8F0FF")))
    data = [go.Scatter(x=xs, y=ys, mode="lines", line=dict(color=OPENING_COLOR.get(kind, "#FFFFFF"), width=6),
                       hoverinfo="skip", showlegend=False) for kind, (xs, ys) in lines.items()]
    W, L = plan["site_w"], plan["site_l"]
    return go.Figure(data=data, layout=_layout(
        height=max(520, int(520 * (L + 1.5) / (W + 1.5))), shapes=shapes, annotations=notes,
        xaxis=dict(visible=False, scaleanchor="y", scaleratio=1), yaxis=dict(visible=False),
        margin=dict(l=20, r=20, t=50, b=20))), skipped


# ══════════════════════════════════════════════════════════════
# 🧭  State + callbacks (callbacks run before the script, so no st.rerun() is needed)
# ══════════════════════════════════════════════════════════════
def init_state():
    for key, default in (("ai_rules", None), ("graph_results", None), ("show_prompt_a", False),
                         ("plans", []), ("rank", 0), ("manual_plan", None), ("manual_json", "{}"), ("manual_src", None),
                         ("of_shown", False)):
        st.session_state.setdefault(key, default)


def active_plan_json():
    """The one plan being shown: the selected engine rank, else the manually pasted JSON."""
    ss = st.session_state
    return ss.plans[min(ss.rank, len(ss.plans) - 1)] if ss.plans else ss.manual_plan


def send_all_to_plan():
    ss = st.session_state
    ss.update(plans=plans_from_results(ss.graph_results), rank=0, manual_plan=None)
    st.toast(f"🚀 ส่ง {len(ss.plans)} Graphs สำเร็จ! กรุณากดที่ Tab 2 เพื่อ Navigate ด้วยปุ่ม ◀ / ▶", icon="✅")


def use_manual_json():
    ss = st.session_state
    if ss.manual_json != active_plan_json():                     # box still shows the active plan: nothing to switch to
        ss.update(plans=[], rank=0, manual_plan=ss.manual_json)


def shift_rank(delta):
    ss = st.session_state
    ss.rank = max(0, min(len(ss.plans) - 1, ss.rank + delta))


def reset_plan():
    st.session_state.update(plans=[], rank=0, manual_plan=None, graph_results=None, of_shown=False)


def show_openings():
    st.session_state.of_shown = True


# ══════════════════════════════════════════════════════════════
# 📤  TAB 1 — program, Prompt A, rules, graph search
# ══════════════════════════════════════════════════════════════
def render_manual_areas(rooms, site_area):
    areas = {}
    with st.container(border=True, key="card_areas"):
        st.subheader("📐 กำหนดพื้นที่แต่ละห้อง")
        cols = st.columns(min(len(rooms), 4))
        for i, room in enumerate(rooms):
            areas[room] = cols[i % 4].number_input(
                f"{room} (ตร.ม.)", value=DEFAULT_AREAS.get(room, 4.0), min_value=1.0, max_value=100.0, step=0.5, key=f"m_{room}")
        total = sum(areas.values())
        pct = total / site_area * 100 if site_area > 0 else 0
        a, b, c = st.columns(3)
        a.metric("📐 Total Net", f"{total:.1f} ตร.ม.")
        b.metric("🏗️ Site Area", f"{site_area:.1f} ตร.ม.")
        c.metric("📊 Coverage", f"{pct:.0f}%", delta="⚠️ เกิน Site!" if pct > 100 else "✅ OK",
                 delta_color="inverse" if pct > 100 else "normal")
    return areas


def load_ai_rules(text):
    if not text.strip():
        st.warning("⚠️ กรุณาวาง JSON จาก AI ก่อน")
        return
    try:
        data = parse_json_text(text)
    except json.JSONDecodeError as exc:
        st.error(f"❌ โครงสร้าง JSON มีข้อผิดพลาด: {exc}")
        return
    try:
        rules, warnings = rules_from_ai(data)
    except ValueError as exc:
        st.warning(f"⚠️ {exc}")
        return
    st.session_state.ai_rules = rules
    st.success("✅ ดึงกฎ C & W จาก AI สำเร็จ! ตาราง Matrix ด้านล่างถูกอัปเดตแล้ว")
    for w in warnings:
        st.warning(f"⚠️ {w}")


def _int_columns(rooms, lo, hi):
    return {r: st.column_config.NumberColumn(r, min_value=lo, max_value=hi, step=1, format="%d") for r in rooms}


def render_matrix_editors(rooms):
    """C / W editors -> (C, W, source): symmetric arrays and where the defaults came from ('ai' | 'default' | 'mismatch')."""
    if not rooms:
        st.warning("⚠️ กรุณาเลือกห้องด้านบนก่อน")
        return None, None, "default"
    C0, W0, source = matrices_for(rooms, st.session_state.ai_rules)
    st.caption({"ai": "✨ กำลังใช้กฎจากข้อมูล AI ที่ดึงมาล่าสุด",
                "default": "ℹ️ กำลังใช้กฎตั้งต้น (Default Typology) เนื่องจากยังไม่ได้โหลดกฎจาก AI",
                "mismatch": "ℹ️ ห้องที่เลือกไม่ตรงกับห้องในกฎ AI ที่โหลดไว้ → กำลังใช้กฎตั้งต้น (Default Typology)"}[source])
    sig = zlib.crc32(json.dumps([rooms, C0, W0]).encode("utf-8"))        # new defaults -> fresh editors, same defaults -> keep edits
    left, right = st.columns(2)
    with left:
        st.markdown("**C — Connectivity Matrix** (+1=ติด, -1=แยก)")
        edited_c = st.data_editor(pd.DataFrame(C0, index=rooms, columns=rooms), key=f"mc_C_{sig}",
                                  width="stretch", column_config=_int_columns(rooms, -1, 1))
    with right:
        st.markdown("**W — Importance Matrix** (3=มาก, 2=กลาง, 1=น้อย)")
        edited_w = st.data_editor(pd.DataFrame(W0, index=rooms, columns=rooms), key=f"mc_W_{sig}",
                                  width="stretch", column_config=_int_columns(rooms, 0, 3))
    st.caption("✏️ แก้ช่องไหนก็ได้ — ระบบสะท้อนค่าไปยังช่องคู่ให้เอง (ถ้าแก้ทั้งสองช่อง ใช้ช่องครึ่งบน)")
    return merge_matrix_edits(C0, edited_c.to_numpy(), -1, 1), merge_matrix_edits(W0, edited_w.to_numpy(), 0, 3), source


def render_ranked(res):
    ranked, s_max = res["ranked"], res["S_max"]
    st.success(f"✅ เสร็จสิ้น! แสดง Top-{len(ranked)} กราฟที่แม่นยำตามกฎมากที่สุด  ·  🎲 seed `{res['seed']}` (ใส่ในช่อง Seed เพื่อได้ผลเดิมซ้ำ)")
    for rank, r in enumerate(ranked, 1):
        pct, violations = r["pct"], r["violations"]
        color = "#3CC470" if pct >= 70 else ("#FFB74D" if pct >= 40 else "#E05C5C")
        st.markdown(
            f"**Rank #{rank}** — S\\*(G) = `{r['score']:.1f}` / `{s_max:.1f}` &nbsp;|&nbsp; "
            f"Quality = **{pct:.1f}%** &nbsp;|&nbsp; Edges = {len(r['edges'])} &nbsp;|&nbsp; "
            f"Violations = {'🟢 None' if not violations else f'🔴 {len(violations)}'}"
            f'<div class="rank-bar"><div style="width:{pct:.1f}%;background:{color}"></div></div>',
            unsafe_allow_html=True)
        if violations:
            with st.expander(f"🔍 ดู Rule Violations ({len(violations)} items) — Rank #{rank}", expanded=False):
                st.markdown("\n".join(f"- {v}" for v in violations))
    st.button("✅ ส่ง Top-K ทั้งหมดไป Tab 2 (Navigate ด้วย ◀ / ▶)", key="send_all", type="primary", on_click=send_all_to_plan)


def render_engine(rooms, areas):
    ss = st.session_state
    st.divider()
    st.markdown("### 🧬 2. Neuro-Symbolic Graph Engine (Matrix Controller)")
    st.markdown(ENGINE_NOTE, unsafe_allow_html=True)
    ai_text = st.text_area("⬇️ วางผลลัพธ์ JSON (Prompt A) จาก AI ที่นี่ เพื่อโหลดกฎ C & W อัตโนมัติ", height=150, key="ai_json")
    if st.button("📥 อัปเดตกฎ (Load AI Rules)"):
        load_ai_rules(ai_text)

    with st.expander("🛠️ ตรวจสอบ/แก้ไข กฎ Matrix ก่อนประมวลผล (Optional)", expanded=True):
        C, W, source = render_matrix_editors(rooms)

    c1, c2, c3, c4 = st.columns([2, 2, 2, 3])
    n_gen = c1.number_input("จำนวน Candidate Graphs (N)", min_value=20, max_value=500, value=100, step=20)
    top_k = c2.number_input("Top-K ที่เลือก", min_value=1, max_value=10, value=5, step=1)
    seed_in = c3.number_input("🎲 Seed (0 = สุ่มใหม่)", min_value=0, max_value=2**31 - 1, value=0, step=1)
    temp = c4.slider("🌡️ Temperature (T)", min_value=0.3, max_value=1.5, value=0.7, step=0.05)

    if st.button("🎲 3. สานกฎให้เป็นกราฟ (Execute Graph Generation)", type="primary"):
        if len(rooms) < 2:
            st.error("ต้องมีห้องอย่างน้อย 2 ห้อง")
        else:
            ai = source == "ai"
            space_req = ss.ai_rules["space"] if ai else [{"room": r, "net_area_sqm": areas[r]} for r in rooms]
            concept = (ss.ai_rules["concept"] if ai else "") or "Neuro-Symbolic Automated Pipeline"
            seed = int(seed_in) or secrets.randbelow(2**31 - 1) + 1
            ss.graph_results = run_engine(rooms, C, W, space_req, concept, int(n_gen), int(top_k), float(temp), seed)
    if ss.graph_results is not None:
        render_ranked(ss.graph_results)


def render_tab1():
    """Returns the site (width, length) the other tabs need."""
    ss = st.session_state
    with st.container(border=True, key="card_site"):
        st.subheader("🏗️ Program Definition & Site")
        left, right = st.columns(2)
        with left:
            project = st.text_input("Project Type", value="บ้านเช่า (Rental House)")
            site_w = st.number_input("ความกว้าง Site (ม.)", value=8.0, step=0.5, min_value=1.0, key="site_width")
            site_l = st.number_input("ความยาว Site (ม.)", value=4.0, step=0.5, min_value=1.0, key="site_length")
            st.info(f"📐 พื้นที่ Site รวม: **{site_w * site_l:.1f} ตร.ม.** ({site_w:.1f} × {site_l:.1f} ม.)")
        with right:
            rooms = st.multiselect("พื้นที่ใช้สอยที่ต้องการ", ROOM_OPTIONS, default=DEFAULT_ROOMS)
            mode = st.radio("Sizing Mode", [AUTO_MODE, MANUAL_MODE])

    areas = {r: DEFAULT_AREAS.get(r, 4.0) for r in rooms}
    if mode == MANUAL_MODE and rooms:
        areas = render_manual_areas(rooms, site_w * site_l)

    if st.button("🚀 1. Generate AI Prompt (Rule Maker)", type="primary"):
        ss.show_prompt_a = True
    if ss.show_prompt_a:                                         # stays on screen until the page is reset
        if not rooms:
            st.error("กรุณาเลือกห้องอย่างน้อย 1 ห้อง")
        else:
            st.success("✅ **Prompt A — Rules Definition**: คัดลอกข้อความด้านล่างนี้ไปวางใน Claude / ChatGPT เพื่อรับกฎความสัมพันธ์ (C & W Matrix)")
            st.code(json.dumps(build_prompt_a(project, site_w, site_l, rooms, mode, areas), ensure_ascii=False, indent=4), language="json")

    render_engine(rooms, areas)
    return site_w, site_l


# ══════════════════════════════════════════════════════════════
# 📥  TAB 2 — pick the plan, show it, flip through ranks
# ══════════════════════════════════════════════════════════════
def render_nav(total, concept):
    ss = st.session_state
    st.divider()
    left, mid, right = st.columns([1, 4, 1])
    left.button("◀ Previous", on_click=shift_rank, args=(-1,), disabled=ss.rank == 0, width="stretch", key="btn_prev")
    mid.markdown(
        f"<div style='text-align:center;padding:8px 0'>"
        f"<span style='color:#60A5FA;font-size:1.1rem;font-weight:700'>📊 Graph Rank #{ss.rank + 1} / {total}</span><br>"
        f"<span style='color:#7090C0;font-size:0.82rem'>{html.escape(concept[:120])}{'…' if len(concept) > 120 else ''}</span>"
        f"</div>", unsafe_allow_html=True)
    right.button("Next ▶", on_click=shift_rank, args=(1,), disabled=ss.rank >= total - 1, width="stretch", key="btn_next")
    st.divider()


def render_plan(plan):
    st.markdown("### 📊 1. Space Requirement")
    a, b, c, d = st.columns(4)
    a.metric("📐 Net Area", f"{plan['t_net']:.2f} ตร.ม.")
    b.metric("🏗️ Gross Area", f"{plan['t_gross']:.2f} ตร.ม.")
    c.metric("🟩 Site Box", f"{plan['site_area']:.2f} ตร.ม.")
    d.metric("⚖️ Scaling Factor", f"x {plan['scale']:.2f}")
    st.dataframe(plan["df"], hide_index=True, width="stretch",
                 column_config={k: st.column_config.NumberColumn(format="%.2f") for k in ("net_area_sqm", plan["circ_col"], "Gross_sqm")})

    st.markdown("### 🧮 2. Adjacency Matrix (Generated from Engine)")
    show_figure(heatmap_fig(plan))
    st.markdown("### 🕸️ 3. Relationship Network Graph")
    show_figure(network_fig(plan))
    st.markdown("### 🟩 4. Schematic Packed Floor Plan")
    overlay = st.toggle("✨ Premium Adjacency Overlay", value=True)
    show_figure(floorplan_fig(plan, overlay), scrollZoom=True)
    if st.session_state.plans:
        render_nav(len(st.session_state.plans), plan["concept"])
    st.markdown("### 🧠 5. AI Design Concept")
    st.info(f"💡 {plan['concept']}")


def render_tab2(site_w, site_l):
    """Returns the plan Tab 3 builds on (None until there is one)."""
    ss = st.session_state
    with st.container(border=True, key="card_circ"):
        st.subheader("⚙️ Circulation Factor")
        left, right = st.columns([1, 3])
        circ_pct = left.number_input("Circulation (% Net Area)", min_value=0, max_value=100, value=0, step=5)
        right.info("💡 เนื่องจากใช้วิธี Pack Area พอดี Site ระบบจะแปลง Circulation เป็นตัวคูณ (Scaling Factor)")

    if ss.plans:
        st.success(f"🧬 **ข้อมูลกราฟพร้อมแสดงผล** — ส่ง {len(ss.plans)} Graphs มาแล้ว | ใช้ปุ่ม ◀ / ▶ ใต้กราฟ Floor Plan เพื่อสลับ Rank")
    elif ss.manual_plan:
        st.success("🧬 **กำลังแสดงผลจาก JSON ที่วางเอง (Manual)** — ส่ง Top-K จาก Tab 1 เพื่อกลับไปใช้กราฟจาก Engine")
    if ss.plans or ss.manual_plan:
        st.button("🗑️ รีเซ็ตข้อมูลทั้งหมด", key="mc_clear", on_click=reset_plan)

    raw = active_plan_json()
    with st.expander("🛠️ Debug / Manual JSON Input", expanded=False):
        if ss.manual_src != raw:                                  # the box follows the active plan
            ss.manual_json, ss.manual_src = raw or "{}", raw
        st.text_area("JSON from Generator", height=200, key="manual_json")
    st.button("✨ Generate Schematic Packed Plan (Manual Trigger)", type="primary", on_click=use_manual_json)

    if raw is None:
        st.info("ℹ️ ยังไม่มีแผน — กด ‘ส่ง Top-K’ ใน Tab 1 หรือวาง Adjacency JSON ในกล่อง Debug แล้วกดปุ่มด้านบน")
        return None
    try:
        plan = build_plan(parse_json_text(raw), site_w, site_l, circ_pct)
    except ValueError as exc:
        st.error(f"❌ {exc}")
        return None
    st.divider()
    for w in plan["warnings"]:
        st.warning(f"⚠️ {w}")
    render_plan(plan)
    return plan


# ══════════════════════════════════════════════════════════════
# 🪑  TAB 3 — Prompt B, import openings + furniture
# ══════════════════════════════════════════════════════════════
def render_openings(plan):
    try:
        data = parse_json_text(st.session_state.of_json)
    except json.JSONDecodeError as exc:
        st.error(f"❌ Openings/Furniture JSON ไม่ถูกต้อง: {exc}")
        return
    if not isinstance(data, dict) or ("Openings" not in data and "Furniture" not in data):
        st.error("❌ ข้อผิดพลาด: ไม่พบคีย์ 'Openings' หรือ 'Furniture' กรุณาตรวจสอบว่าไม่ได้นำ JSON ของ Space Requirement มาวางผิดช่อง")
        return
    openings, furniture = _dicts(data.get("Openings")), _dicts(data.get("Furniture"))
    checks = data.get("Checks") if isinstance(data.get("Checks"), dict) else {}
    listed = {k: _as_list(checks.get(k)) for k in ("overlaps", "clearance_violations", "door_swing_conflicts")}

    fig, skipped = openings_fig(plan, openings, furniture)
    show_figure(fig, scrollZoom=True)
    if skipped:
        st.warning(f"⚠️ ข้ามรายการที่อ้างถึงห้องซึ่งไม่อยู่ใน Packed Plan นี้: {', '.join(skipped)}")

    st.divider()
    st.markdown("### ✅ 8. Validation Checks")
    for col, (key, label) in zip(st.columns(3), (("overlaps", "🔴 Overlaps"), ("clearance_violations", "🟡 Clearance"),
                                                  ("door_swing_conflicts", "🟠 Door Swing"))):
        found = listed[key]
        col.metric(label, len(found), delta="⚠️ Found!" if found else "✅ None", delta_color="inverse" if found else "normal")
    for key, title in (("overlaps", "Overlap Details:"), ("clearance_violations", "Clearance Violation Details:"),
                       ("door_swing_conflicts", "Door Swing Conflict Details:")):
        if listed[key]:
            st.warning(f"**{title}**")
            st.json(listed[key])
    auto = check_openings(plan["rects"], openings, furniture)
    if auto:
        st.warning("**Auto-detected Warnings:**")
        st.markdown("\n".join(f"- {w}" for w in auto))
    if not any(listed.values()) and not auto:
        st.success("✅ All checks passed — สมบูรณ์แบบ! ไม่พบ overlap หรือจุดบกพร่อง")

    st.divider()
    st.markdown("### 📦 Final AI Result JSON (Complete)")
    final = {"Packed_Plan": packed_plan(plan), "Openings": openings, "Furniture": furniture, "Checks": checks,
             "metadata": {"site_width_m": plan["site_w"], "site_length_m": plan["site_l"],
                          "scale_factor": round(plan["scale"], 4),
                          "total_net_sqm": round(plan["t_net"], 2), "total_gross_sqm": round(plan["t_gross"], 2)}}
    st.code(json.dumps(final, ensure_ascii=False, indent=2), language="json")


def render_tab3(plan):
    ss = st.session_state
    if plan is None:
        st.info("ℹ️ ยังไม่มี Packed Plan — สร้างแผนใน Tab 1 → Tab 2 ก่อน แล้วจึงมาต่อที่ขั้นตอนประตู/หน้าต่าง/เฟอร์นิเจอร์")
        return
    st.markdown("### 🚪 6. AI Prompt — Openings + Furniture")
    st.markdown('<div class="note"><b>💡 Two-Stage AI Flow:</b> คัดลอก Prompt ด้านล่างไปส่งให้ AI อีกรอบ เพื่อได้ช่องเปิด + เฟอร์นิเจอร์ที่ลงตัวตามพิกัดห้อง</div>', unsafe_allow_html=True)
    st.code(json.dumps(build_prompt_b(plan), ensure_ascii=False, indent=4), language="json")

    st.divider()
    st.markdown("### 🪑 7. Import Openings + Furniture (AI Result)")
    if "of_json" not in ss:
        ss.of_json = example_openings(plan["rects"])
    st.text_area("⬇️ วาง Openings + Furniture JSON จาก AI (Prompt B)", height=200, key="of_json")
    st.button("🪑 Visualize Openings + Furniture", type="primary", on_click=show_openings)
    if ss.of_shown:                                              # stays up (and follows the selected rank) until reset
        render_openings(plan)


# ══════════════════════════════════════════════════════════════
# 🗂️  Page
# ══════════════════════════════════════════════════════════════
def main():
    st.set_page_config(page_title="AI Architecture Pipeline", layout="wide", page_icon="🏛️")
    init_state()
    st.markdown(CSS + HERO, unsafe_allow_html=True)
    tab1, tab2, tab3 = st.tabs(["📤  1. USER INPUT & PROMPT A", "📥  2. IMPORT JSON & PACKED PLAN", "🪑  3. PROMPT B & FINAL PRODUCT"])
    with tab1:
        site_w, site_l = render_tab1()
    with tab2:
        plan = render_tab2(site_w, site_l)
    with tab3:
        render_tab3(plan)


if __name__ == "__main__":
    main()
