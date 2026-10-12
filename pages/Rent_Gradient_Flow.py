"""
Rent Gradient Flow — แอปขับเคลื่อนด้วยแผน (flowchart) ต่อยอดจาก Rent Gradient v2
==============================================================================
แผน  : pages/Rent_Gradient_flowchart.mmd (ตรวจเทียบโค้ดแล้วใน docs/rent-gradient-flowchart-facts.md)
ฐาน  : pages/Rent_Gradient_V2.py — import เป็น engine ทั้งไฟล์ ไม่ copy โค้ดคำนวณหรือ UI
       (ผลคำนวณเหมือน V2 ทุกประการ; แก้ V2 ที่เดียว หน้านี้ได้ตามทันที)

แท็บ
  💹 Rent Gradient v2   V2 ทั้งหน้า: sidebar เดิม + แผนที่ + แท็บวิเคราะห์ (ไม่เปลี่ยน)
  🧭 Flow               แผนที่ทำงานจริง: สถานะแต่ละ node จาก guard ของแผน, ปุ่มรันต่อ node,
                        flowchart ลงสีตามสถานะ, ตารางกติกาล้างผล (INV)

Plan node -> engine function -> สิ่งที่เห็นในแท็บ Flow
  ISO  ① Isochrone   perform_calculation            การ์ด ① + ปุ่มรัน
  NET  ③ Network     perform_network_analysis       การ์ด ③ + ปุ่มรัน
  ANC  Anchor        perform_automated_anchor       การ์ด Anchor + ปุ่มรัน
  EVN  Evidence      (รันใน ANC เมื่อเปิด toggle)    การ์ด Evidence (อ่านอย่างเดียว)
  R1   ④ Rent        perform_rent_gradient          การ์ด ④ + ปุ่มรัน (+ ป้าย stale)
  INV  invalidation  StateManager.invalidate_*      ตารางกติกา (a)–(d)
  ERR  stop          guard ก่อนรัน -> st.warning    เหตุผลที่ ⛔ ในการ์ด
  GOAL outputs       render_analytics_panel         การ์ด GOAL (ได้อะไร / ขาดอะไร)

Sections
- Section 1: Engine (V2) & Constants
- Section 2: Plan logic (No st.* — testable): facts -> node status -> next step -> live flowchart
- Section 3: UI Components (st.* allowed)
- Section 4: Main Execution
"""

import importlib.util
import math
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import streamlit as st


# ============================================================================
# SECTION 1: ENGINE (Rent_Gradient_V2) & CONSTANTS
# ============================================================================

ENGINE_MODULE_NAME = "rent_gradient_v2_engine"
ENGINE_PATH = Path(__file__).with_name("Rent_Gradient_V2.py")


def load_engine():
    """โหลด Rent_Gradient_V2.py เป็น module (ไม่รัน main) ครั้งเดียวต่อ process แล้วใช้ซ้ำทุก rerun."""
    module = sys.modules.get(ENGINE_MODULE_NAME)
    if module is None:
        spec = importlib.util.spec_from_file_location(ENGINE_MODULE_NAME, ENGINE_PATH)
        module = importlib.util.module_from_spec(spec)
        sys.modules[ENGINE_MODULE_NAME] = module
        try:
            spec.loader.exec_module(module)
        except BaseException:
            sys.modules.pop(ENGINE_MODULE_NAME, None)
            raise
    return module


engine = load_engine()

PAGE_CONFIG: Dict[str, Any] = {
    "page_title": "Rent Gradient Flow — แอปขับเคลื่อนด้วยแผน",
    "page_icon": "🧭",
    "layout": "wide",
}

TAB_V2_LABEL = "💹 Rent Gradient v2"
TAB_FLOW_LABEL = "🧭 Flow"

# ปุ่มรันในแท็บ Flow ตั้งค่านี้ผ่าน on_click แล้ว main() รัน node หลังวาด sidebar
# (ลำดับเดียวกับ V2.main) จึงวาดการ์ด/ปุ่มด้วยสถานะ "หลังรัน" ได้โดยไม่ต้อง st.rerun()
PENDING_KEY = "_flow_pending_node"

# session key ที่ V2 ใช้เป็น string ตรงๆ (ไม่มีค่าคงที่ใน StateManager)
KEY_USE_EVIDENCE = "anchor_use_evidence"
KEY_RENT_EVIDENCE_ANCHOR = "rent_use_evidence_anchor"
KEY_ANCHOR_CENTER_TEXT = "anchor_center_input"

# สถานะของ node
DONE, READY, BLOCKED, STALE, PARTIAL, IDLE, OFF = (
    "done", "ready", "blocked", "stale", "partial", "idle", "off",
)
STATE_BADGE: Dict[str, str] = {
    DONE: "✅ เสร็จ",
    READY: "▶️ พร้อมรัน",
    BLOCKED: "⛔ ติดเงื่อนไข",
    STALE: "⚠️ ควรรันใหม่",
    PARTIAL: "🟡 บางส่วน",
    IDLE: "◻️ ทางเลือก",
    OFF: "💤 ปิดอยู่",
}
# สถานะ -> class ใน Mermaid (ลงสี node ของแผน)
STATE_CLASS: Dict[str, str] = {
    DONE: "st_done", READY: "st_ready", BLOCKED: "st_blocked",
    STALE: "st_stale", PARTIAL: "st_stale", IDLE: "st_idle", OFF: "st_idle",
}
CLASS_STYLE: Dict[str, str] = {
    "st_done": "fill:#d4edda,stroke:#2e7d32,stroke-width:2px,color:#000",
    "st_ready": "fill:#e3f2fd,stroke:#1565c0,stroke-width:3px,color:#000",
    "st_blocked": "fill:#fdecea,stroke:#c0392b,stroke-width:2px,stroke-dasharray: 4 3,color:#000",
    "st_stale": "fill:#fff3cd,stroke:#b8860b,stroke-width:2px,color:#000",
    "st_idle": "fill:#f1f1f1,stroke:#9e9e9e,color:#555",
}

# node ของแผนที่รันได้ -> ฟังก์ชัน orchestrator ของ V2 (เรียกเหมือน V2.main ทุกประการ)
RUNNERS = {
    "ISO": lambda: engine.perform_calculation(engine.StateManager.get_active_markers()),
    "NET": lambda: engine.perform_network_analysis(),
    "ANC": lambda: engine.perform_automated_anchor(),
    "R1": lambda: engine.perform_rent_gradient(),
}

CSS = (
    "<style>"
    ".block-container { padding-top: 2rem; padding-bottom: 0rem; } "
    "h1 { margin-bottom: 0px; } "
    "div[data-testid=\"stHorizontalBlock\"] button { padding: 0rem 0.5rem; }"
    "</style>"
)


# ============================================================================
# SECTION 2: PLAN LOGIC (No st.* — testable)
# ============================================================================

@dataclass(frozen=True)
class FlowFacts:
    """ข้อเท็จจริงจาก session state ที่ guard ของแผนต้องใช้ (ไม่มี object หนัก)."""

    locked: bool = False
    # ① inputs / outputs
    api_key: bool = False
    active_markers: int = 0
    time_intervals: int = 0
    iso_features: int = 0
    cbd_found: bool = False
    # ③
    network_found: bool = False
    network_nodes: int = 0
    golden_spots: int = 0
    # Anchor / Evidence
    has_scipy: bool = True
    anchor_center_valid: bool = True
    anchor_found: bool = False
    anchor_lat: float = 0.0
    anchor_lon: float = 0.0
    use_evidence: bool = False
    evidence_state: str = "none"          # none | outdated | unavailable | ok
    evidence_level: str = ""              # HIGH | MEDIUM | LOW
    rent_uses_evidence_anchor: bool = False
    # ④
    rent_found: bool = False
    rent_fit: bool = False                # False = โหมดดัชนี
    rent_lambda: float = 0.0
    rent_n: int = 0
    rent_r2: Optional[float] = None       # มีเฉพาะเมื่อ n ≥ 3 (n = 2 → R² ไม่มีความหมาย)
    rent_anchor_source: str = ""
    rent_stale: bool = False


@dataclass(frozen=True)
class NodeStatus:
    key: str        # id ของ node ใน Rent_Gradient_flowchart.mmd
    title: str
    state: str      # ผลของ node: DONE | READY | BLOCKED | STALE | PARTIAL | IDLE | OFF
    detail: str     # สิ่งที่ได้ หรือเหตุผลที่ติด — ภาษาไทย
    blocked: str = ""   # guard ของแผนไม่ผ่านตอนนี้ (node ERR) — ว่าง = รันได้; แยกจาก state เพราะ
                        # node ที่มีผลเก่าค้าง (เช่น Network หลังล้าง isochrone) ก็รันซ้ำไม่ได้

    @property
    def runnable(self) -> bool:
        return self.key in RUNNERS and not self.blocked


def rent_fit_is_stale(
    rent_data: Mapping[str, Any], samples: Sequence[Mapping[str, Any]]
) -> bool:
    """ตารางตัวอย่างเปลี่ยนหลัง fit ล่าสุดหรือไม่ (แผน: แก้ตาราง = sync อย่างเดียว ไม่ fit ใหม่).

    ถาม V2 ตรงๆ ว่า "ถ้า fit ใหม่ตอนนี้ ผลจะต่างไหม" ด้วย ``fit_rent_gradient_from_samples`` ตัวเดียวกัน:
    โหมดดัชนี -> ต่างเมื่อตอนนี้ fit ได้แล้ว · โหมด FIT -> ต่างเมื่อ fit ไม่ได้แล้ว หรือจุด (d, ราคา) เปลี่ยน
    """
    model = rent_data.get("model") or {}
    anchor = rent_data.get("anchor") or {}
    try:
        refit = engine.fit_rent_gradient_from_samples(list(samples), anchor["lat"], anchor["lon"])
    except (KeyError, TypeError, ValueError):
        return False
    if model.get("is_index"):
        return refit is not None
    scatter = rent_data.get("samples_scatter")
    if scatter is None:  # ผลเก่าที่ไม่เก็บจุด fit — บอกไม่ได้ ไม่เตือนมั่ว
        return False
    if refit is None:
        return True
    used = sorted((p["d"], p["rent"]) for p in scatter)
    now = sorted((p["d"], p["rent"]) for p in refit["points"])
    return len(used) != len(now) or not all(
        math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-9)
        for pair_a, pair_b in zip(used, now) for a, b in zip(pair_a, pair_b)
    )


def _evidence_facts(evidence: Mapping[str, Any]) -> Tuple[str, str]:
    """(state, level) ตามเงื่อนไขเดียวกับ ``_evidence_summary`` ของ V2."""
    if not evidence:
        return "none", ""
    if evidence.get("schema") != engine.EVIDENCE_SCHEMA:
        return "outdated", ""
    if evidence.get("status") == "unavailable" or not evidence.get("evidence_anchor"):
        return "unavailable", ""
    return "ok", str((evidence.get("confidence") or {}).get("level") or "")


def collect_facts(state: Mapping[str, Any]) -> FlowFacts:
    """อ่าน session state -> FlowFacts (ผลที่ยังไม่มี / เป็น error / ว่าง = ถือว่ายังไม่มีผล ไม่ raise)."""
    sm = engine.StateManager
    markers = state.get(sm.K_MARKERS) or []
    iso = state.get(sm.K_ISOCHRONE) or {}
    inter = state.get(sm.K_INTERSECTION) or {}
    net = state.get(sm.K_NETWORK) or {}
    auto = state.get(sm.K_AUTO_ANCHOR) or {}
    rent = state.get(sm.K_RENT_DATA) or {}

    network_found = bool(net) and "error" not in net
    stats = (net.get("stats") or {}) if network_found else {}
    anchor = auto.get("anchor") or {}

    center_text = state.get(KEY_ANCHOR_CENTER_TEXT)
    center_valid = True
    if center_text is not None:
        try:
            engine._parse_anchor_center_input(center_text)
        except ValueError:
            center_valid = False

    evidence_state, evidence_level = _evidence_facts(state.get(sm.K_AUTO_ANCHOR_EVIDENCE) or {})

    rent_found = bool(rent) and "error" not in rent and "model" in rent
    model = rent.get("model") or {}
    # โหมดดัชนี = is_index หรือไม่มี R² (นิยามเดียวกับ fit_quality_label ของ V2)
    rent_fit = rent_found and not model.get("is_index") and model.get("r2") is not None
    r2 = model.get("r2") if rent_fit and engine._fit_dof(model) > 0 else None

    return FlowFacts(
        locked=bool(state.get(sm.K_UI_LOCKED)),
        api_key=bool(state.get(sm.K_API_KEY)),
        active_markers=sum(1 for m in markers if m.get("active", True)),
        time_intervals=len(state.get(sm.K_TIME_INTERVALS) or []),
        iso_features=len(iso.get("features") or []),
        cbd_found=bool(inter.get("features")),
        network_found=network_found,
        network_nodes=int(stats.get("nodes_count") or 0),
        golden_spots=len(net.get("golden_spots") or []) if network_found else 0,
        has_scipy=bool(engine.HAS_SCIPY),
        anchor_center_valid=center_valid,
        anchor_found=bool(anchor),
        anchor_lat=float(anchor.get("lat") or 0.0),
        anchor_lon=float(anchor.get("lon") or 0.0),
        use_evidence=bool(state.get(KEY_USE_EVIDENCE)),
        evidence_state=evidence_state,
        evidence_level=evidence_level,
        rent_uses_evidence_anchor=bool(state.get(KEY_RENT_EVIDENCE_ANCHOR)),
        rent_found=rent_found,
        rent_fit=rent_fit,
        rent_lambda=float(model.get("lam") or 0.0),
        rent_n=int(model.get("n_samples") or 0),
        rent_r2=float(r2) if r2 is not None else None,
        rent_anchor_source=str((rent.get("anchor") or {}).get("source") or ""),
        rent_stale=rent_found and rent_fit_is_stale(rent, state.get(sm.K_RENT_SAMPLES) or []),
    )


# ---- guards ต่อ node (ข้อความในแผน: pages/Rent_Gradient_flowchart.mmd) -----------------------
# state = ผลของ node (มีผลแล้วไหม) · blocked = guard ของแผนผ่านไหมตอนนี้ (ถ้าไม่ผ่านปุ่มรันถูกปิด)

def _status_iso(f: FlowFacts) -> NodeStatus:
    title = "① Isochrone → CBD"
    missing = []
    if not f.api_key:
        missing.append("ไม่มี API key")
    if f.active_markers < 1:
        missing.append("ต้องมีหมุด active ≥ 1")
    if f.time_intervals < 1:
        missing.append("ยังไม่ได้เลือกเวลา")
    blocked = " · ".join(missing)
    if f.iso_features:
        cbd = ("พบ CBD Zone" if f.cbd_found
               else "ไม่พบ CBD (ต้อง ≥ 2 หมุดที่ทุกจุดได้พื้นที่และทับซ้อนกัน)")
        return NodeStatus("ISO", title, DONE, f"{f.iso_features} isochrone · {cbd}", blocked)
    if blocked:
        return NodeStatus("ISO", title, BLOCKED, blocked, blocked)
    return NodeStatus(
        "ISO", title, READY,
        f"{f.active_markers} หมุด active · {f.time_intervals} ช่วงเวลา — Geoapify isoline ต่อหมุด "
        "แล้วหา CBD (∩) และคำนวณ Rent ให้เอง",
    )


def _status_network(f: FlowFacts) -> NodeStatus:
    title = "③ Network (OSM)"
    blocked = "" if f.iso_features else "ต้องมี isochrone ก่อน — รัน ①"
    if f.network_found:
        detail = f"{f.network_nodes:,} โหนด · Golden Spots {f.golden_spots} จุด"
        if blocked:  # กติกา (a) ล้าง isochrone แต่คง Network ไว้
            detail += " · ผลจากรอบก่อน (isochrone ถูกล้างแล้ว แต่แผนคง Network ไว้) — รัน ① ก่อนจึงรันซ้ำได้"
        return NodeStatus("NET", title, DONE, detail, blocked)
    if blocked:
        return NodeStatus("NET", title, BLOCKED, blocked, blocked)
    return NodeStatus(
        "NET", title, READY,
        "union ทุก isochrone → ถนน OSM → closeness / betweenness / Golden Spots "
        "(ครั้งแรกอาจนาน 5–10 นาที)",
    )


def _status_anchor(f: FlowFacts) -> NodeStatus:
    title = "🎯 Automated Anchor"
    if not f.has_scipy:
        blocked = "ต้องติดตั้ง scipy + numpy"
    elif not f.anchor_center_valid:
        blocked = "พิกัดศูนย์พื้นที่ศึกษาไม่ถูกต้อง (Lat, Lon)"
    else:
        blocked = ""
    if f.anchor_found:
        return NodeStatus(
            "ANC", title, DONE,
            f"Composite {f.anchor_lat:.5f}, {f.anchor_lon:.5f} · Rent ใช้ตัวนี้ "
            "(Closeness 100% ไว้เทียบเท่านั้น)",
            blocked,
        )
    if blocked:
        return NodeStatus("ANC", title, BLOCKED, blocked, blocked)
    return NodeStatus(
        "ANC", title, IDLE,
        "ทางเลือก — หาศูนย์กลางจากโครงข่ายถนนโดยไม่ต้องมี isochrone (รัศมี 4–20 กม. + buffer 20%)",
    )


def _status_evidence(f: FlowFacts) -> NodeStatus:
    title = "🗺️ Evidence (ทดลอง)"
    if not f.use_evidence:
        return NodeStatus("EVN", title, OFF, "ปิดอยู่ — เปิดที่ sidebar › Automated CBD Anchor")
    if f.evidence_state == "ok":
        used = "Rent ใช้ Evidence anchor" if f.rent_uses_evidence_anchor else "Rent ยังใช้ Composite"
        return NodeStatus("EVN", title, DONE, f"ความเชื่อมั่น {f.evidence_level or '—'} · {used}")
    if f.evidence_state == "unavailable":
        return NodeStatus("EVN", title, PARTIAL, "ไม่ได้หลักฐานเสริม — ใช้ผลจากถนนอย่างเดียว")
    if f.evidence_state == "outdated":
        return NodeStatus("EVN", title, STALE, "ผลหลักฐานจากเวอร์ชันเก่า — รัน Anchor ใหม่")
    if not f.anchor_found:
        return NodeStatus("EVN", title, IDLE, "เปิดแล้ว — Evidence รันต่อจาก Anchor ในครั้งเดียว")
    return NodeStatus("EVN", title, READY, "เปิดแล้วแต่ยังไม่มีผล — รัน Anchor อีกครั้ง (ใช้ถนนจากแคช)")


def _status_rent(f: FlowFacts) -> NodeStatus:
    title = "④ Rent Gradient"
    blocked = "" if (f.iso_features or f.anchor_found) else "ต้องมี isochrone หรือ Automated Anchor ก่อน"
    if f.rent_found:
        if f.rent_fit:
            mode = f"FIT n={f.rent_n}" + (f" R²={f.rent_r2:.2f}" if f.rent_r2 is not None else "")
        else:
            mode = "INDEX (ดัชนี 0–100)"
        detail = f"{mode} · λ = {f.rent_lambda:.4f}/km · จุดยึด: {f.rent_anchor_source or '—'}"
        if f.rent_stale:
            detail += " — ตารางตัวอย่างเปลี่ยนหลัง fit ล่าสุด (แก้ตาราง = sync อย่างเดียว) กดรันเพื่อ fit ใหม่"
            return NodeStatus("R1", title, STALE, detail, blocked)
        return NodeStatus("R1", title, DONE, detail, blocked)
    if blocked:
        return NodeStatus("R1", title, BLOCKED, blocked, blocked)
    return NodeStatus(
        "R1", title, READY,
        "fit จากตัวอย่างราคาในตาราง (≥ 2 จุดระยะต่างกัน) ไม่งั้นโหมดดัชนี — ปกติรันเองหลัง ① / Anchor",
    )


def _status_goal(f: FlowFacts) -> NodeStatus:
    """ผลลัพธ์ของแผน (node GOAL): ได้อะไรแล้ว ขาดอะไร และขาดเพราะ node ไหน."""
    title = "🎯 GOAL — ที่ดินทอง"
    have: List[str] = []
    missing: List[str] = []
    if f.rent_found:
        have.append("Bid-Rent curve · วงแหวนราคา · R(d) ต่อหมุด")
    else:
        missing.append("Bid-Rent curve (ต้อง ④)")
    if f.network_found:
        have.append("Golden table")
    else:
        missing.append("Golden table (ต้อง ③)")
    if f.rent_found:
        if f.network_found:
            have.append("Rent Heat บนโหนด")
        else:
            missing.append("Rent Heat (ต้อง ③)")
        if f.network_found and f.rent_fit:
            have.append("Value Gap")
        elif f.network_found:
            missing.append("Value Gap (ต้อง FIT — โหมดดัชนีซ่อน)")
        else:
            missing.append("Value Gap (ต้อง ③ ∧ FIT)")
    detail = "ได้: " + (" · ".join(have) or "—")
    if missing:
        detail += " | ขาด: " + " · ".join(missing)
    if not (f.rent_found or f.network_found):
        return NodeStatus("GOAL", title, IDLE, detail)
    if f.rent_found and f.network_found and f.rent_fit and not f.rent_stale:
        return NodeStatus("GOAL", title, DONE, detail)
    return NodeStatus("GOAL", title, PARTIAL, detail)


def evaluate_flow(facts: FlowFacts) -> List[NodeStatus]:
    """สถานะของ node ตามลำดับในแผน: ISO, NET, ANC, EVN, R1, GOAL."""
    return [
        _status_iso(facts), _status_network(facts), _status_anchor(facts),
        _status_evidence(facts), _status_rent(facts), _status_goal(facts),
    ]


def next_step(statuses: Sequence[NodeStatus], facts: FlowFacts) -> str:
    """ขั้นต่อไปที่แนะนำ — เรียงตามแผน ① → ③ → ④ → GOAL."""
    by = {s.key: s for s in statuses}
    iso, net, anc, r1, goal = by["ISO"], by["NET"], by["ANC"], by["R1"], by["GOAL"]
    if r1.state == STALE:
        return "กดรัน ④ เพื่อ fit Rent Gradient ใหม่ — ตารางตัวอย่างเปลี่ยนหลัง fit ล่าสุด"
    if iso.state != DONE and anc.state != DONE:
        if iso.state == BLOCKED:
            return f"แก้เงื่อนไขของ ① ก่อน: {iso.detail} (หรือใช้ Automated Anchor แทน)"
        return "กดรัน ① เพื่อหา Isochrone และ CBD"
    if net.state == READY:
        return "กดรัน ③ เพื่อวิเคราะห์โครงข่ายถนน → Golden Spots"
    if net.state == BLOCKED:
        return "รัน ① ก่อนจึงจะทำ ③ Network (Golden Spots) ได้ — Anchor อย่างเดียวพอสำหรับ Rent"
    if r1.state == READY:
        return "กดรัน ④ เพื่อคำนวณ Rent Gradient"
    if facts.rent_found and not facts.rent_fit:
        return ("ใส่ตัวอย่างราคา ≥ 2 จุดที่ระยะต่างกันจาก CBD (sidebar › Rent Gradient › Calibration) "
                "แล้วกดรัน ④ → โหมด FIT + Value Gap")
    if goal.state == DONE:
        return ("ครบตามแผน — ดู 💎 Golden Spots ในแท็บ Rent Gradient v2 "
                "หรือเพิ่ม Golden #1 เป็นหมุดแล้ววนรอบใหม่")
    return "—"


# ---- แผน (.mmd) แบบมีชีวิต -----------------------------------------------------------------

_NODE_DEF = re.compile(r"^\s+([A-Za-z_][A-Za-z0-9_]*)\s*(?:\(\[|\[\[|\[|\(\(|\{|\()")


def plan_node_ids(mmd: str) -> List[str]:
    """id ของ node ที่นิยามไว้ใน .mmd (ตามลำดับที่พบ)."""
    ids: List[str] = []
    for line in mmd.splitlines():
        match = _NODE_DEF.match(line)
        if match and match.group(1) not in ids:
            ids.append(match.group(1))
    return ids


def live_flowchart(mmd: str, statuses: Sequence[NodeStatus]) -> str:
    """.mmd เดิมทุกบรรทัด + classDef/class ที่ลงสี node ตามสถานะ (GOAL/ERR คงสีเดิมของแผน)."""
    known = set(plan_node_ids(mmd))
    groups: Dict[str, List[str]] = {}
    for status in statuses:
        if status.key in known and status.key not in ("GOAL", "ERR"):
            groups.setdefault(STATE_CLASS[status.state], []).append(status.key)
    lines = [mmd.rstrip("\n")]
    lines += [f"    classDef {name} {style}" for name, style in CLASS_STYLE.items()]
    lines += [f"    class {','.join(keys)} {name}" for name, keys in groups.items()]
    return "\n".join(lines) + "\n"


# ---- INV: กติกาล้างผล (ข้อมูลจาก StateManager ไม่ hard-code ซ้ำ) -----------------------------

@dataclass(frozen=True)
class InvalidationRule:
    code: str
    trigger: str
    clears: Tuple[str, ...]  # session keys ที่ถูกล้าง (ค่าคงที่ K_* ของ StateManager)


def invalidation_rules() -> Tuple[InvalidationRule, ...]:
    sm = engine.StateManager
    return (
        InvalidationRule(
            "(a)", "คลิกแผนที่ · เพิ่ม/ลบ/toggle หมุด · เพิ่ม top node หรือ Golden เป็นหมุด",
            (sm.K_ISOCHRONE, sm.K_INTERSECTION, sm.K_RENT_DATA)),
        InvalidationRule(
            "(b)", "เปลี่ยน center / radius / travel mode · ล้าง Anchor",
            (sm.K_AUTO_ANCHOR, sm.K_AUTO_ANCHOR_CLOSENESS, sm.K_AUTO_ANCHOR_EVIDENCE, sm.K_RENT_DATA)),
        InvalidationRule(
            "(c)", "รีเซ็ต · import config (import แล้วโหลดผลที่บันทึกกลับมา)",
            (sm.K_ISOCHRONE, sm.K_INTERSECTION, sm.K_NETWORK, sm.K_RENT_DATA,
             sm.K_AUTO_ANCHOR, sm.K_AUTO_ANCHOR_CLOSENESS, sm.K_AUTO_ANCHOR_EVIDENCE)),
        InvalidationRule(
            "(d)", "toggle Evidence-anchor (แล้ว Rent คำนวณใหม่แบบเงียบ)",
            (sm.K_RENT_DATA,)),
    )


def _layer_labels() -> Dict[str, str]:
    sm = engine.StateManager
    return {
        sm.K_ISOCHRONE: "Isochrone", sm.K_INTERSECTION: "CBD", sm.K_NETWORK: "Network",
        sm.K_RENT_DATA: "Rent", sm.K_AUTO_ANCHOR: "Anchor", sm.K_AUTO_ANCHOR_CLOSENESS: "Closeness-anchor",
        sm.K_AUTO_ANCHOR_EVIDENCE: "Evidence",
    }


def invalidation_table_markdown() -> str:
    labels = _layer_labels()
    everything = list(labels)
    rows = ["| กติกา | เมื่อ | ล้าง | คงไว้ |", "|---|---|---|---|"]
    for rule in invalidation_rules():
        cleared = " · ".join(labels[k] for k in everything if k in rule.clears)
        kept = " · ".join(labels[k] for k in everything if k not in rule.clears) or "—"
        rows.append(f"| {rule.code} | {rule.trigger} | {cleared} | {kept} |")
    return "\n".join(rows)


# ============================================================================
# SECTION 3: UI COMPONENTS (st.* allowed)
# ============================================================================

def _queue_run(node_key: str) -> None:
    """on_click: จำ node ที่ผู้ใช้กด — main() จะรันหลังวาด sidebar ในรอบเดียวกัน."""
    st.session_state[PENDING_KEY] = node_key


def run_flow_node(node_key: str) -> None:
    """รัน node ด้วย orchestrator ของ V2 ถ้า guard ของแผนผ่าน; ไม่ผ่าน = แจ้งเหตุผล (node ERR) ไม่รัน."""
    statuses = evaluate_flow(collect_facts(st.session_state))
    status = next(s for s in statuses if s.key == node_key)
    if not status.runnable:
        st.warning(f"⚠️ {status.title}: {status.blocked or status.detail}")
        return
    RUNNERS[node_key]()


def _isolated(label: str, action) -> None:
    """แท็บ Flow เป็นส่วนเสริม: ถ้าวาดไม่สำเร็จ ให้แจ้งแล้วปล่อยให้ V2 ทำงานต่อ (คลิกแผนที่, ปุ่มใน sidebar).

    ``st.rerun()`` / หยุดสคริปต์เป็น BaseException จึงไม่ถูกจับตรงนี้."""
    try:
        action()
    except Exception as exc:
        st.error(f"{label} แสดงผลไม่สำเร็จ: {exc}", icon="⚠️")


def _render_plan_diagram(mmd: str) -> None:
    markup = engine._flowchart_html(mmd)
    height = engine._FLOWCHART_HEIGHT_PX
    if hasattr(st, "iframe"):
        st.iframe(markup, height=height)
    else:  # Streamlit เก่า: components.html (deprecated ในรุ่นใหม่)
        import streamlit.components.v1 as components

        components.html(markup, height=height, scrolling=True)


def _render_node_card(status: NodeStatus, locked: bool) -> None:
    with st.container(border=True):
        text, action = st.columns([5, 1], vertical_alignment="center")
        text.markdown(f"**{status.title}** · {STATE_BADGE[status.state]}")
        text.caption(status.detail)
        if status.key in RUNNERS:
            action.button(
                "↻ รันใหม่" if status.state == DONE else "▶ รัน",
                key=f"flow_run_{status.key}",
                on_click=_queue_run,
                args=(status.key,),
                disabled=locked or not status.runnable,
                help=status.blocked or "รันขั้นนี้ (ตัวคำนวณเดียวกับปุ่มใน sidebar)",
                width="stretch",
            )


def render_flow_tab() -> None:
    """แท็บ Flow — อ่านสถานะจาก session state หลังรัน node แล้ว (main() เรียกหลังขั้นรัน)."""
    facts = collect_facts(st.session_state)
    statuses = evaluate_flow(facts)

    st.markdown(
        "**🎯 GOAL:** ที่ดินทอง = เข้าถึงง่าย แต่ราคา `R(d) = R₀·e^(−λd)` ยังต่ำ · "
        "Value Gap = Closeness − clamp(R/R₀, 0..1) เฉพาะเมื่อมี network ∧ FIT"
    )
    core = [s for s in statuses if s.key in ("ISO", "NET", "R1", "GOAL")]
    finished = sum(1 for s in core if s.state == DONE)
    st.progress(finished / len(core), text=f"ความคืบหน้าตามแผน {finished}/{len(core)} (① → ③ → ④ → GOAL)")
    st.info(f"👉 ขั้นต่อไป: {next_step(statuses, facts)}")
    if facts.locked:
        st.caption("🔒 sidebar ล็อกอยู่ — ปุ่มรันถูกปิด")

    for status in statuses:
        _render_node_card(status, facts.locked)

    st.markdown("##### 🗺️ แผนที่มีชีวิต")
    st.caption("🟩 เสร็จ · 🟦 พร้อมรัน · 🟥 ติดเงื่อนไข · 🟨 ควรรันใหม่/บางส่วน · ⬜ ทางเลือก/ปิด")
    plan_path = engine._FLOWCHART_PATH
    if plan_path.is_file():
        _render_plan_diagram(live_flowchart(plan_path.read_text(encoding="utf-8"), statuses))
    else:
        st.warning(f"ไม่พบไฟล์แผน: {plan_path.name}", icon="⚠️")

    with st.expander("♻️ กติกาล้างผล (INV) — การกระทำไหนล้างอะไร"):
        st.markdown(invalidation_table_markdown())
        st.caption(
            "ค่าในตารางอ่านจาก StateManager ของ V2 โดยตรง · แก้ตารางตัวอย่างราคาแล้ว Rent "
            "ไม่คำนวณใหม่เอง (การ์ด ④ จะขึ้น ⚠️)"
        )


# ============================================================================
# SECTION 4: MAIN EXECUTION
# ============================================================================

def main() -> None:
    st.set_page_config(**PAGE_CONFIG)
    st.markdown(CSS, unsafe_allow_html=True)

    # 1. Initialize State (V2)
    engine.StateManager.initialize()

    st.markdown("#### 🧭 Rent Gradient Flow")
    st.caption(
        "แอปขับเคลื่อนด้วยแผน `Rent_Gradient_flowchart.mmd` · ต่อยอดจาก Rent Gradient v2 "
        "(ใช้ engine เดียวกัน ผลคำนวณเหมือนกัน)"
    )
    run_area = st.container()  # spinner / toast / error ของทุกการรัน อยู่เหนือแท็บ เห็นได้ทุกแท็บ

    # 2. Sidebar ของ V2 (ไม่เปลี่ยน) → intents
    do_calc, do_net, do_rent, do_anchor, active_list = engine.render_sidebar()

    # 3. รัน node: ปุ่มในแท็บ Flow ก่อน แล้วปุ่มใน sidebar (ลำดับของปุ่ม sidebar เหมือน V2.main)
    pending = st.session_state.pop(PENDING_KEY, None)
    with run_area:
        if pending in RUNNERS:
            run_flow_node(pending)
        if do_calc:
            engine.perform_calculation(active_list)
        if do_net:
            engine.perform_network_analysis()
        if do_rent:
            engine.perform_rent_gradient()
        if do_anchor:
            engine.perform_automated_anchor()

    # 4. แท็บ: V2 ทั้งหน้า + Flow (วาดหลังรัน จึงเห็นผลล่าสุดทั้งสองแท็บ)
    tab_v2, tab_flow = st.tabs([TAB_V2_LABEL, TAB_FLOW_LABEL])
    with tab_v2:
        engine.render_header()
        engine.render_metrics_row()
        map_output = engine.render_map()
        engine.render_analytics_panel()
    with tab_flow:
        _isolated("แท็บ Flow", render_flow_tab)

    # 5. Handle Map Click → mutate state & rerun
    engine.handle_map_click(map_output, st.session_state[engine.StateManager.K_UI_LOCKED])


if __name__ == "__main__":
    main()
