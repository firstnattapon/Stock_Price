"""
PYTRON – Architecture Design Framework v2.1
Simple · Stable · Fast

8-stage pipeline from site intelligence to construction documentation.
Space Group logic with AI Prompt export/import.
"""

import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import plotly.express as px
import networkx as nx
import json, math, io
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Tuple, Optional

# ─────────────────────────────────────────────────────────────────────
# 0. PAGE CONFIG & THEME
# ─────────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="PYTRON · Architecture Design Framework",
    page_icon="🏛️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Inject custom CSS ────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800;900&display=swap');

/* ── Global ─────────────────────────────────────────────────────── */
html, body, [class*="css"] {
    font-family: 'Inter', sans-serif;
}
.block-container { padding-top: 1.5rem; }

/* ── Card style ─────────────────────────────────────────────────── */
.pytron-card {
    background: linear-gradient(135deg, #1e1e2e 0%, #2a2a3e 100%);
    border: 1px solid rgba(255,255,255,0.08);
    border-radius: 16px;
    padding: 1.5rem 1.8rem;
    margin-bottom: 1rem;
    box-shadow: 0 4px 24px rgba(0,0,0,0.25);
    transition: transform 0.2s, box-shadow 0.2s;
}
.pytron-card:hover {
    transform: translateY(-2px);
    box-shadow: 0 8px 32px rgba(0,0,0,0.35);
}

/* ── Stage badge ────────────────────────────────────────────────── */
.stage-badge {
    display: inline-block;
    background: linear-gradient(135deg, #6c63ff, #3b82f6);
    color: #fff;
    font-weight: 700;
    font-size: 0.7rem;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    padding: 0.25rem 0.75rem;
    border-radius: 20px;
    margin-bottom: 0.6rem;
}

/* ── Metric highlight ───────────────────────────────────────────── */
.metric-glow {
    background: linear-gradient(135deg, #0f172a, #1e293b);
    border: 1px solid rgba(99,102,241,0.3);
    border-radius: 12px;
    padding: 1rem 1.2rem;
    text-align: center;
}
.metric-glow h3 {
    color: #818cf8;
    font-size: 0.75rem;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    margin: 0 0 0.3rem 0;
}
.metric-glow p {
    color: #e2e8f0;
    font-size: 1.6rem;
    font-weight: 700;
    margin: 0;
}

/* ── Law card ───────────────────────────────────────────────────── */
.law-card {
    background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
    border-left: 3px solid #f59e0b;
    border-radius: 0 12px 12px 0;
    padding: 0.8rem 1.2rem;
    margin-bottom: 0.6rem;
    font-style: italic;
    color: #e2e8f0;
    font-size: 0.95rem;
}

/* ── Sidebar style ──────────────────────────────────────────────── */
section[data-testid="stSidebar"] {
    background: linear-gradient(180deg, #0f172a 0%, #1e1b4b 100%);
}
section[data-testid="stSidebar"] .stMarkdown h1,
section[data-testid="stSidebar"] .stMarkdown h2,
section[data-testid="stSidebar"] .stMarkdown h3 {
    color: #c7d2fe;
}

/* ── Progress bar colour ────────────────────────────────────────── */
.stProgress > div > div > div > div {
    background: linear-gradient(90deg, #6c63ff, #3b82f6, #06b6d4);
}

/* ── Tabs underline ─────────────────────────────────────────────── */
.stTabs [data-baseweb="tab-highlight"] {
    background-color: #6c63ff;
}

/* ── Expander headers ───────────────────────────────────────────── */
details summary {
    font-weight: 600 !important;
}

/* ── Auto badge ─────────────────────────────────────────────────── */
.auto-badge {
    display: inline-block;
    background: rgba(6,182,212,0.15);
    color: #06b6d4;
    font-size: 0.65rem;
    font-weight: 700;
    letter-spacing: 0.08em;
    padding: 0.15rem 0.5rem;
    border-radius: 10px;
    margin-left: 0.4rem;
}
.manual-badge {
    display: inline-block;
    background: rgba(148,163,184,0.15);
    color: #94a3b8;
    font-size: 0.65rem;
    font-weight: 700;
    letter-spacing: 0.08em;
    padding: 0.15rem 0.5rem;
    border-radius: 10px;
    margin-left: 0.4rem;
}
.zone-dot {
    display: inline-block;
    width: 10px; height: 10px;
    border-radius: 50%;
    margin-right: 0.4rem;
    vertical-align: middle;
}
</style>
""", unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────
# 1. CONSTANTS – Neufert Standards & Adjacency Rules
# ─────────────────────────────────────────────────────────────────────
ROOM_STANDARDS = {
    "Kitchen":           {"min": 10, "recommended": 14},
    "Dining Room":       {"min": 12, "recommended": 16},
    "Master Bedroom":    {"min": 18, "recommended": 25},
    "Bedroom":           {"min": 12, "recommended": 16},
    "Living Room":       {"min": 20, "recommended": 35},
    "Bathroom":          {"min": 4,  "recommended": 6},
    "Closet":            {"min": 3,  "recommended": 5},
    "Garage":            {"min": 18, "recommended": 30},
    "Study / Office":    {"min": 9,  "recommended": 12},
    "Laundry Room":      {"min": 4,  "recommended": 6},
    "Storage":           {"min": 3,  "recommended": 5},
    "Foyer / Entry":     {"min": 4,  "recommended": 7},
}

ADJACENCY_RULES = {
    ("Kitchen", "Dining Room"): 2, ("Dining Room", "Living Room"): 2,
    ("Kitchen", "Living Room"): 1, ("Master Bedroom", "Bathroom"): 2,
    ("Master Bedroom", "Closet"): 2, ("Bedroom", "Bathroom"): 2,
    ("Bedroom", "Closet"): 1, ("Foyer / Entry", "Living Room"): 2,
    ("Foyer / Entry", "Kitchen"): 1, ("Garage", "Kitchen"): 1,
    ("Laundry Room", "Kitchen"): 1, ("Study / Office", "Living Room"): 1,
    ("Storage", "Kitchen"): 1,
}

DEFAULT_SPACE_GROUPS = [
    {"group_name": "Kitchen + Dining", "rooms": ["Kitchen", "Dining Room"], "zone": "Service", "size_mode": "auto"},
    {"group_name": "Living Area", "rooms": ["Living Room", "Foyer / Entry"], "zone": "Social", "size_mode": "auto"},
    {"group_name": "Master Suite", "rooms": ["Master Bedroom", "Bathroom", "Closet"], "zone": "Private", "size_mode": "auto"},
    {"group_name": "Secondary Bedroom", "rooms": ["Bedroom"], "zone": "Private", "size_mode": "auto"},
    {"group_name": "Utility", "rooms": ["Garage", "Laundry Room"], "zone": "Service", "size_mode": "auto"},
]

ZONE_COLORS = {"Social": "#6c63ff", "Private": "#f472b6", "Service": "#06b6d4", "Outdoor": "#34d399"}

# ── Rental Presets (Thai) ─────────────────────────────────────────────
RENTAL_ROOM_STANDARDS = {
    "Bedroom":      {"min": 8.0,  "recommended": 10.0},
    "Living Room":  {"min": 4.0,  "recommended": 6.0},
    "Kitchen":      {"min": 6.0,  "recommended": 8.0},
    "Dining Room":  {"min": 6.0,  "recommended": 8.0},
    "Bathroom":     {"min": 4.0,  "recommended": 5.0},
    "Closet":       {"min": 2.0,  "recommended": 3.0},
}

RENTAL_PRESETS = {
    "ห้องเช่า Standard (30 m²)": {
        "project_name": "ห้องเช่า Standard 30 m²",
        "site_area": 200.0, "far": 2.0, "bcr": 60.0,
        "setback_f": 3.0, "setback_s": 1.5, "setback_r": 1.5,
        "circ_pct": 15.0,
        "groups": [
            {
                "group_name": "ห้องนอน + นั่งเล่น",
                "rooms": ["Bedroom", "Living Room"],
                "zone": "Private", "size_mode": "manual",
                "manual_areas": {"Bedroom": 8.0, "Living Room": 4.0},
                "target_m2": 12,
                "design_note_th": "แบ่งเขตด้วยเฟอร์นิเจอร์ ประหยัดพื้นที่",
                "design_note_en": "Zone divided by furniture arrangement",
            },
            {
                "group_name": "ครัว + กินข้าว",
                "rooms": ["Kitchen", "Dining Room"],
                "zone": "Service", "size_mode": "manual",
                "manual_areas": {"Kitchen": 6.0, "Dining Room": 6.0},
                "target_m2": 12,
                "design_note_th": "ครัวกึ่งเปิด ต่อเนื่องพื้นที่กินข้าว",
                "design_note_en": "Semi-open kitchen integrated with dining",
            },
            {
                "group_name": "ห้องน้ำ + เสื้อผ้า",
                "rooms": ["Bathroom", "Closet"],
                "zone": "Service", "size_mode": "manual",
                "manual_areas": {"Bathroom": 4.0, "Closet": 2.0},
                "target_m2": 6,
                "design_note_th": "Wet zone รวม Built-in closet ประหยัดพื้นที่",
                "design_note_en": "Wet zone with integrated built-in wardrobe",
            },
        ],
    },
}

def _zc(z: str) -> str:
    return ZONE_COLORS.get(z, "#94a3b8")

def _get_room_area(name: str, mode: str = "auto") -> float:
    if mode == "auto" and name in ROOM_STANDARDS:
        return float(ROOM_STANDARDS[name]["min"])
    return ROOM_STANDARDS.get(name, {}).get("min", 10.0)

def _expand_groups_to_rooms(groups):
    rooms = []
    for g in groups:
        for rname in g.get("rooms", []):
            sm = g.get("size_mode", "auto")
            manual_areas = g.get("manual_areas", {})
            if sm == "manual" and rname in manual_areas:
                area = float(manual_areas[rname])
            else:
                area = _get_room_area(rname, sm)
            rooms.append({"name": rname, "area": area, "zone": g.get("zone", "Service"),
                          "priority": "High", "size_mode": sm, "group": g.get("group_name", "")})
    return rooms

def _lookup_adjacency(a: str, b: str) -> int:
    return ADJACENCY_RULES.get((a, b), ADJACENCY_RULES.get((b, a), -1))

def _rooms_in_same_group(a: str, b: str, groups) -> bool:
    for g in groups:
        if a in g.get("rooms", []) and b in g.get("rooms", []):
            return True
    return False


# ─────────────────────────────────────────────────────────────────────
# 2. SESSION STATE DEFAULTS
# ─────────────────────────────────────────────────────────────────────
_DEFAULTS: Dict = {
    "project_name": "Untitled Project",
    "project_type": "Custom",
    "site_area": 400.0, "far": 2.5, "bcr": 60.0,
    "setback_f": 6.0, "setback_s": 3.0, "setback_r": 3.0,
    "wind_dir": "South-West", "sun_orient": "East-West", "noise_src": "North",
    "space_groups": None,
    "rooms": None,
    "circ_pct": 30.0,
    "adj_matrix": None,
    "structure_sys": "Reinforced Concrete Frame",
    "facade_mat": "Exposed Concrete + Timber Cladding",
    "roof_type": "Flat / Green Roof",
    "ai_prompt_exported": False,
    "ai_response_imported": False,
    "ai_stage_data": {},
    "ai_verdict": {},
    "ai_warnings": [],
    "ai_principles": [],
}

for k, v in _DEFAULTS.items():
    if k not in st.session_state:
        st.session_state[k] = v

if st.session_state["space_groups"] is None:
    st.session_state["space_groups"] = [dict(g) for g in DEFAULT_SPACE_GROUPS]
    st.session_state["rooms"] = _expand_groups_to_rooms(st.session_state["space_groups"])

if st.session_state["rooms"] is None:
    st.session_state["rooms"] = _expand_groups_to_rooms(st.session_state["space_groups"])


# ─────────────────────────────────────────────────────────────────────
# SIDEBAR
# ─────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## 🏛️ PYTRON")
    st.caption("Architecture Design Framework v2.1")
    st.divider()

    st.session_state["project_name"] = st.text_input(
        "Project Name", value=st.session_state["project_name"]
    )

    stage_labels = [
        "01 · Site Intelligence", "02 · Program Definition",
        "03 · Space Quantification", "04 · Relationship Logic",
        "05 · Spatial Network", "06 · Schematic Design",
        "07 · Design Development", "08 · Construction Docs",
    ]
    current = st.radio("Navigate Stage", stage_labels, index=0)
    stage_idx = stage_labels.index(current)
    st.progress((stage_idx + 1) / len(stage_labels))

    # Status badges
    ptype = st.session_state.get("project_type", "Custom")
    if ptype != "Custom":
        st.markdown(f'<span style="color:#06b6d4;">🏠 {ptype}</span>', unsafe_allow_html=True)
    if st.session_state.get("ai_response_imported"):
        verdict = st.session_state.get("ai_verdict", {})
        score = verdict.get("score", "")
        label_th = verdict.get("label_th", "")
        score_str = f" · {score}/10 {label_th}" if score else ""
        st.markdown(f'<span style="color:#34d399;">● AI Imported{score_str}</span>', unsafe_allow_html=True)

    st.divider()
    with st.expander("💾 Export / Import", expanded=False):
        # Existing state export
        export_data = {k: v for k, v in st.session_state.items() if k in _DEFAULTS}
        st.download_button(
            "⬇ Export State JSON",
            data=json.dumps(export_data, indent=2, default=str),
            file_name=f"pytron_{st.session_state['project_name'].replace(' ','_')}.json",
            mime="application/json",
        )
        st.markdown("---")

        # AI Prompt Export — Full Stage 02–06 Schema (Bilingual)
        if st.button("🤖 Export AI Prompt JSON", use_container_width=True):
            sa  = st.session_state["site_area"]
            far_v = st.session_state["far"]
            rooms_flat = st.session_state.get("rooms", [])
            names_list = [r["name"] for r in rooms_flat]
            prompt_obj = {
                "task": "pytron_full_design_optimization_stage02_to_06",
                "version": "pytron-v2.1-bilingual",
                "language": "bilingual_th_en",
                "system_instruction": (
                    "You are a Gold-Standard Professional Architect (สถาปนิกมืออาชีพระดับมืออาชีพ). "
                    "Analyze the provided architectural program and return a COMPLETE spatial design optimization "
                    "covering Stage 02 through Stage 06. "
                    "All rationale fields must be provided in BOTH Thai (th) and English (en). "
                    "Follow Neufert standards strictly. Output ONLY pure JSON — no markdown, no explanation, "
                    "no code fences. The JSON must exactly match the requested_output_schema."
                ),
                "project_context": {
                    "project_name": st.session_state["project_name"],
                    "project_type": st.session_state.get("project_type", "Custom"),
                    "site_area_m2": sa,
                    "floor_area_ratio": far_v,
                    "building_coverage_ratio_pct": st.session_state["bcr"],
                    "max_allowable_floor_area_m2": round(sa * far_v, 2),
                    "setbacks_m": {
                        "front": st.session_state["setback_f"],
                        "side": st.session_state["setback_s"],
                        "rear": st.session_state["setback_r"],
                    },
                    "climate": {
                        "wind_direction": st.session_state["wind_dir"],
                        "sun_orientation": st.session_state["sun_orient"],
                        "noise_source": st.session_state["noise_src"],
                    },
                },
                "current_program": {
                    "space_groups": st.session_state.get("space_groups", []),
                    "rooms_flat": rooms_flat,
                    "circulation_factor_pct": st.session_state["circ_pct"],
                    "current_adjacency_matrix": st.session_state.get("adj_matrix"),
                    "room_names_ordered": names_list,
                },
                "hard_constraints": {
                    "total_must_not_exceed_m2": round(sa * far_v, 2),
                    "respect_neufert_minimums": True,
                    "output_must_be_pure_json": True,
                    "adjacency_matrix_size": f"{len(names_list)}x{len(names_list)} matching room_names_ordered",
                },
                "requested_output_schema": {
                    "_note": "Return ALL fields below. th = ภาษาไทย, en = English.",

                    "stage_02_output": {
                        "optimized_rooms": [
                            {
                                "name": "string — room name",
                                "area": "float — optimized area m²",
                                "zone": "Social | Private | Service | Outdoor",
                                "priority": "High | Medium | Low",
                                "size_mode": "auto | manual",
                                "group": "string — group name",
                                "design_rationale_th": "string — เหตุผลการออกแบบ",
                                "design_rationale_en": "string — design rationale",
                            }
                        ],
                        "space_groups_optimized": [
                            {
                                "group_name": "string",
                                "group_name_th": "string — ชื่อกลุ่มห้องภาษาไทย",
                                "rooms": ["list of room names"],
                                "zone": "string",
                                "total_area_m2": "float",
                                "notes_th": "string — หมายเหตุภาษาไทย",
                                "notes_en": "string — notes in English",
                            }
                        ],
                    },

                    "stage_03_output": {
                        "circulation_factor_recommended": "float 0.10–0.40",
                        "circulation_rationale_th": "string — เหตุผลค่า circulation",
                        "circulation_rationale_en": "string — rationale for circulation factor",
                        "room_quantification": [
                            {
                                "name": "string",
                                "functional_m2": "float",
                                "circulation_m2": "float",
                                "total_m2": "float",
                                "efficiency_note_th": "string",
                                "efficiency_note_en": "string",
                            }
                        ],
                        "total_functional_m2": "float",
                        "total_with_circulation_m2": "float",
                        "utilisation_pct_of_max": "float",
                    },

                    "stage_04_output": {
                        "adjacency_matrix": f"2D array {len(names_list)}x{len(names_list)} — values 0/1/2 matching room_names_ordered",
                        "adjacency_rationale": {
                            "essential_pairs_th": ["string — คู่ที่ต้องชิดกัน"],
                            "essential_pairs_en": ["string — pairs that must be adjacent"],
                            "avoid_pairs_th": ["string — คู่ที่ควรแยก"],
                            "avoid_pairs_en": ["string — pairs to separate"],
                        },
                        "relationship_strategy_th": "string — กลยุทธ์ความสัมพันธ์เชิงพื้นที่",
                        "relationship_strategy_en": "string — spatial relationship strategy",
                    },

                    "stage_05_output": {
                        "connectivity_score": "float 0.0–1.0",
                        "hub_rooms": ["list — ห้องที่เป็น hub หลัก"],
                        "zone_clusters": [
                            {
                                "cluster_name_th": "string — ชื่อ cluster ภาษาไทย",
                                "cluster_name": "string — cluster name",
                                "zone_type": "string",
                                "rooms": ["list"],
                                "internal_cohesion": "High | Medium | Low",
                                "notes_th": "string",
                                "notes_en": "string",
                            }
                        ],
                        "critical_paths": [
                            {
                                "path_name_th": "string — ชื่อเส้นทาง",
                                "path": ["room_A", "room_B", "room_C"],
                                "importance": "Critical | High | Medium",
                                "reason_th": "string",
                                "reason_en": "string",
                            }
                        ],
                        "spatial_network_quality_verdict": {
                            "score_label": "Excellent | Good | Fair | Poor",
                            "summary_th": "string — สรุปคุณภาพ spatial network",
                            "summary_en": "string",
                            "improvement_suggestions_th": ["string — ข้อเสนอแนะ"],
                            "improvement_suggestions_en": ["string"],
                        },
                    },

                    "stage_06_output": {
                        "recommended_structural_grid": "4×4 m | 4×6 m | 5×6 m | 6×6 m | 8×8 m | 6×9 m | 8×12 m",
                        "grid_rationale_th": "string — เหตุผลการเลือก grid",
                        "grid_rationale_en": "string",
                        "estimated_floors": "int",
                        "area_per_floor_m2": "float",
                        "zone_layout_strategy_th": "string — กลยุทธ์การจัดวาง zone",
                        "zone_layout_strategy_en": "string",
                        "block_plan_notes_th": "string — หมายเหตุ schematic block plan",
                        "block_plan_notes_en": "string",
                        "orientation_strategy_th": "string — กลยุทธ์การวางทิศทาง",
                        "orientation_strategy_en": "string",
                    },

                    "design_principles_applied": [
                        "string — หลักการออกแบบที่ใช้ (bilingual หรือ English)",
                    ],
                    "professional_warnings": [
                        "string — คำเตือนจากสถาปนิก (bilingual)",
                    ],
                    "overall_design_verdict": {
                        "score": "int 1–10",
                        "label_th": "string — ระดับคุณภาพ",
                        "label_en": "string",
                        "summary_th": "string — สรุปภาพรวมโครงการ",
                        "summary_en": "string",
                    },
                    "total_area_check": "float — grand total including circulation",
                },
            }
            prompt_json = json.dumps(prompt_obj, indent=2, default=str, ensure_ascii=False)
            st.session_state["ai_prompt_exported"] = True
            st.download_button(
                "⬇ Download Full AI Prompt (Stage 02–06)",
                data=prompt_json,
                file_name=f"pytron_ai_prompt_{st.session_state['project_name'].replace(' ','_')}.json",
                mime="application/json",
                key="ai_prompt_dl",
            )
            st.info("📋 วางทั้ง JSON นี้เป็น prompt ใน Claude / ChatGPT แล้ว Import กลับมา")

        st.markdown("---")

        # AI Response Import (supports v2.0 flat + v2.1 nested stage_XX_output)
        ai_upload = st.file_uploader("⬆ Import AI Response JSON", type=["json"], key="ai_resp_upload")
        if ai_upload:
            try:
                ai_data = json.load(ai_upload)
                # --- Detect v2.1 nested format ---
                is_v21 = "stage_02_output" in ai_data
                if is_v21:
                    s02 = ai_data.get("stage_02_output", {})
                    s03 = ai_data.get("stage_03_output", {})
                    s04 = ai_data.get("stage_04_output", {})
                    new_rooms = s02.get("optimized_rooms", [])
                    new_adj = s04.get("adjacency_matrix", [])
                    new_groups = s02.get("space_groups_optimized", [])
                    circ_val = s03.get("circulation_factor_recommended")
                else:
                    new_rooms = ai_data.get("optimized_rooms", [])
                    new_adj = ai_data.get("adjacency_matrix", [])
                    new_groups = ai_data.get("space_groups_optimized", [])
                    circ_val = ai_data.get("circulation_factor_recommended")

                errors = []
                if not new_rooms:
                    errors.append("Missing 'optimized_rooms'")
                if not new_adj:
                    errors.append("Missing 'adjacency_matrix'")
                if errors:
                    st.error("Validation failed: " + ", ".join(errors))
                else:
                    if len(new_adj) != len(new_rooms):
                        st.error(f"Room count ({len(new_rooms)}) != adjacency matrix size ({len(new_adj)})")
                    else:
                        st.session_state["rooms"] = new_rooms
                        st.session_state["adj_matrix"] = new_adj
                        if circ_val is not None:
                            cv = float(circ_val)
                            st.session_state["circ_pct"] = cv * 100 if cv < 1 else cv
                        if new_groups:
                            st.session_state["space_groups"] = new_groups
                        # v2.1 extra stage data
                        if is_v21:
                            st.session_state["ai_stage_data"] = {
                                "stage_03": s03,
                                "stage_04": s04,
                                "network": ai_data.get("stage_05_output", {}),
                                "schematic": ai_data.get("stage_06_output", {}),
                            }
                            st.session_state["ai_verdict"] = ai_data.get("overall_design_verdict", {})
                            st.session_state["ai_warnings"] = ai_data.get("professional_warnings", [])
                            st.session_state["ai_principles"] = ai_data.get("design_principles_applied", [])
                        st.session_state["ai_response_imported"] = True
                        ver = "v2.1" if is_v21 else "v2.0"
                        st.success(f"✅ [{ver}] Imported {len(new_rooms)} rooms, circ={st.session_state['circ_pct']:.0f}%")
                        st.rerun()
            except Exception as e:
                st.error(f"Import failed: {e}")

        st.markdown("---")
        # Standard import
        uploaded = st.file_uploader("⬆ Import State JSON", type=["json"], key="state_upload")
        if uploaded:
            try:
                data = json.load(uploaded)
                for k, v in data.items():
                    st.session_state[k] = v
                st.success("Imported successfully!")
                st.rerun()
            except Exception as e:
                st.error(f"Import failed: {e}")


# ─────────────────────────────────────────────────────────────────────
# HEADER
# ─────────────────────────────────────────────────────────────────────
st.markdown(f"""
<div style="text-align:center;padding:0.5rem 0 1rem 0;">
    <h1 style="margin:0;font-weight:900;
        background:linear-gradient(90deg,#6c63ff,#3b82f6,#06b6d4);
        -webkit-background-clip:text;-webkit-text-fill-color:transparent;">
        PYTRON
    </h1>
    <p style="color:#94a3b8;margin:0;font-size:0.95rem;letter-spacing:0.05em;">
        {st.session_state['project_name']} &nbsp;·&nbsp; Stage {stage_idx+1}/8
    </p>
</div>
""", unsafe_allow_html=True)


# ═════════════════════════════════════════════════════════════════════
# STAGE 01 – SITE INTELLIGENCE (UNCHANGED)
# ═════════════════════════════════════════════════════════════════════
if stage_idx == 0:
    st.markdown('<div class="stage-badge">Stage 01</div>', unsafe_allow_html=True)
    st.subheader("Site Intelligence")
    st.caption("Architecture begins with land, climate, and regulations.")

    c1, c2 = st.columns(2)
    with c1:
        st.session_state["site_area"] = st.number_input("Site Area (sq m)", min_value=10.0, value=st.session_state["site_area"], step=10.0)
        st.session_state["far"] = st.number_input("Floor Area Ratio (FAR)", min_value=0.1, value=st.session_state["far"], step=0.1)
        st.session_state["bcr"] = st.slider("Building Coverage Ratio (%)", 10, 90, int(st.session_state["bcr"]))
    with c2:
        st.session_state["setback_f"] = st.number_input("Front Setback (m)", 0.0, 20.0, st.session_state["setback_f"], 0.5)
        st.session_state["setback_s"] = st.number_input("Side Setback (m)", 0.0, 20.0, st.session_state["setback_s"], 0.5)
        st.session_state["setback_r"] = st.number_input("Rear Setback (m)", 0.0, 20.0, st.session_state["setback_r"], 0.5)

    st.divider()
    c3, c4, c5 = st.columns(3)
    with c3:
        opts_w = ["North","North-East","East","South-East","South","South-West","West","North-West"]
        st.session_state["wind_dir"] = st.selectbox("🌬️ Prevailing Wind", opts_w, index=opts_w.index(st.session_state["wind_dir"]))
    with c4:
        opts_s = ["East-West","North-South"]
        st.session_state["sun_orient"] = st.selectbox("☀️ Sun Orientation", opts_s, index=opts_s.index(st.session_state["sun_orient"]))
    with c5:
        opts_n = ["North","East","South","West","None"]
        st.session_state["noise_src"] = st.selectbox("🔊 Primary Noise Source", opts_n, index=opts_n.index(st.session_state["noise_src"]))

    max_bldg_footprint = st.session_state["site_area"] * st.session_state["bcr"] / 100
    max_total_floor = st.session_state["site_area"] * st.session_state["far"]

    st.divider()
    m1, m2, m3 = st.columns(3)
    with m1:
        st.markdown(f'<div class="metric-glow"><h3>Max Footprint</h3><p>{max_bldg_footprint:,.0f} m²</p></div>', unsafe_allow_html=True)
    with m2:
        st.markdown(f'<div class="metric-glow"><h3>Max Total Floor</h3><p>{max_total_floor:,.0f} m²</p></div>', unsafe_allow_html=True)
    with m3:
        est_floors = max_total_floor / max_bldg_footprint if max_bldg_footprint > 0 else 0
        st.markdown(f'<div class="metric-glow"><h3>Est. Floors</h3><p>{est_floors:,.1f}</p></div>', unsafe_allow_html=True)

    st.divider()
    st.markdown("##### 🗺️ Site Constraints Map")
    _W, _H = 20, 15
    sb_f, sb_s, sb_r = st.session_state["setback_f"], st.session_state["setback_s"], st.session_state["setback_r"]
    fig_site = go.Figure()
    fig_site.add_shape(type="rect", x0=0, y0=0, x1=_W, y1=_H, line=dict(color="#94a3b8", width=2, dash="dot"), fillcolor="rgba(30,30,46,0.6)")
    fig_site.add_shape(type="rect", x0=sb_s, y0=sb_f, x1=_W-sb_s, y1=_H-sb_r, line=dict(color="#6c63ff", width=2), fillcolor="rgba(108,99,255,0.12)")
    fig_site.add_annotation(x=_W/2, y=_H/2, text="Buildable<br>Area", showarrow=False, font=dict(color="#a5b4fc", size=14, family="Inter"))
    fig_site.add_annotation(x=_W/2, y=-0.8, text="FRONT (Road)", showarrow=False, font=dict(color="#f59e0b", size=11))
    fig_site.add_annotation(x=_W/2, y=_H+0.8, text="REAR", showarrow=False, font=dict(color="#94a3b8", size=11))
    _DIR_ANGLES = {"North":90,"North-East":45,"East":0,"South-East":-45,"South":-90,"South-West":-135,"West":180,"North-West":135}
    wa = math.radians(_DIR_ANGLES.get(st.session_state["wind_dir"], 0))
    cx, cy = _W/2, _H/2
    arrow_len = 3
    fig_site.add_annotation(x=cx+arrow_len*math.cos(wa), y=cy+arrow_len*math.sin(wa), ax=cx-arrow_len*math.cos(wa), ay=cy-arrow_len*math.sin(wa), xref="x", yref="y", axref="x", ayref="y", showarrow=True, arrowhead=3, arrowsize=1.5, arrowwidth=2, arrowcolor="#06b6d4")
    fig_site.add_annotation(x=cx+(arrow_len+1.2)*math.cos(wa), y=cy+(arrow_len+1.2)*math.sin(wa), text="🌬️ Wind", showarrow=False, font=dict(color="#06b6d4", size=10))
    fig_site.update_layout(xaxis=dict(visible=False, range=[-2, _W+2]), yaxis=dict(visible=False, range=[-2, _H+2], scaleanchor="x"), height=380, margin=dict(l=0,r=0,t=10,b=10), plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)")
    st.plotly_chart(fig_site, use_container_width=True)


# ═════════════════════════════════════════════════════════════════════
# STAGE 02 – PROGRAM DEFINITION (v2: Space Groups)
# ═════════════════════════════════════════════════════════════════════
elif stage_idx == 1:
    st.markdown('<div class="stage-badge">Stage 02</div>', unsafe_allow_html=True)
    st.subheader("Program Definition")
    st.caption("Define spatial groups — rooms auto-sized from Neufert standards.")

    groups = st.session_state["space_groups"]
    zones = ["Social", "Private", "Service", "Outdoor"]
    all_room_names = list(ROOM_STANDARDS.keys())
    preset_group_names = [g["group_name"] for g in DEFAULT_SPACE_GROUPS] + ["Custom"]

    # ── Project Type Selector ──────────────────────────────────────────
    st.markdown("##### 🏠 Project Type")
    ptype_options = ["Custom"] + list(RENTAL_PRESETS.keys())
    ptype_idx = ptype_options.index(st.session_state.get("project_type", "Custom")) if st.session_state.get("project_type", "Custom") in ptype_options else 0
    selected_ptype = st.selectbox("เลือกประเภทโปรเจค / Project Type", ptype_options, index=ptype_idx, label_visibility="collapsed")
    st.session_state["project_type"] = selected_ptype

    if selected_ptype != "Custom":
        preset = RENTAL_PRESETS[selected_ptype]
        total_target = sum(g["target_m2"] for g in preset["groups"])
        # Info summary card
        pc1, pc2, pc3 = st.columns(3)
        with pc1:
            st.markdown(f'<div class="metric-glow"><h3>เป้าหมาย / Target</h3><p>{total_target} m²</p></div>', unsafe_allow_html=True)
        with pc2:
            st.markdown(f'<div class="metric-glow"><h3>กลุ่มห้อง / Groups</h3><p>{len(preset["groups"])}</p></div>', unsafe_allow_html=True)
        with pc3:
            st.markdown(f'<div class="metric-glow"><h3>Circulation</h3><p>{preset["circ_pct"]:.0f}%</p></div>', unsafe_allow_html=True)

        # Group breakdown
        for g in preset["groups"]:
            rooms_str = " + ".join([f"{r} ({g['manual_areas'].get(r,0):.0f} m²)" for r in g["rooms"]])
            st.markdown(f"""
            <div class="pytron-card" style="padding:0.8rem 1.2rem;margin-bottom:0.5rem;">
                <span class="zone-dot" style="background:{_zc(g['zone'])};"></span>
                <b>{g['group_name']}</b> — {g['target_m2']} m²<br>
                <span style="color:#94a3b8;font-size:0.85rem;">{rooms_str}</span><br>
                <span style="color:#06b6d4;font-size:0.8rem;">🇹🇭 {g['design_note_th']}</span><br>
                <span style="color:#94a3b8;font-size:0.8rem;">🇬🇧 {g['design_note_en']}</span>
            </div>""", unsafe_allow_html=True)

        col_load, col_skip = st.columns(2)
        with col_load:
            if st.button(f"⚡ โหลด Preset นี้ทันที", use_container_width=True, type="primary"):
                p = RENTAL_PRESETS[selected_ptype]
                st.session_state["project_name"]   = p["project_name"]
                st.session_state["site_area"]      = p["site_area"]
                st.session_state["far"]            = p["far"]
                st.session_state["bcr"]            = p["bcr"]
                st.session_state["setback_f"]      = p["setback_f"]
                st.session_state["setback_s"]      = p["setback_s"]
                st.session_state["setback_r"]      = p["setback_r"]
                st.session_state["circ_pct"]       = p["circ_pct"]
                st.session_state["space_groups"]   = [dict(g) for g in p["groups"]]
                st.session_state["rooms"]          = _expand_groups_to_rooms(p["groups"])
                # Auto-gen adjacency
                _names = [r["name"] for r in st.session_state["rooms"]]
                _n = len(_names)
                _grps = st.session_state["space_groups"]
                new_adj = [[0]*_n for _ in range(_n)]
                for i in range(_n):
                    for j in range(i+1, _n):
                        a, b = _names[i], _names[j]
                        val = _lookup_adjacency(a, b)
                        if val >= 0:
                            new_adj[i][j] = val; new_adj[j][i] = val
                        elif _rooms_in_same_group(a, b, _grps):
                            new_adj[i][j] = 1; new_adj[j][i] = 1
                st.session_state["adj_matrix"] = new_adj
                st.session_state["ai_response_imported"] = False
                st.success(f"✅ Preset '{selected_ptype}' โหลดแล้ว — Stage 02–04 อัพเดทอัตโนมัติ")
                st.rerun()
        with col_skip:
            if st.button("✏️ แก้ไข Groups เอง", use_container_width=True):
                st.session_state["project_type"] = "Custom"
                st.rerun()

        st.divider()

    # Action buttons
    bc1, bc2 = st.columns(2)
    with bc1:
        if st.button("➕ Add Group", use_container_width=True):
            groups.append({"group_name": f"Group {len(groups)+1}", "rooms": [], "zone": "Service", "size_mode": "auto"})
            st.session_state["space_groups"] = groups
            st.rerun()
    with bc2:
        if st.button("🔄 Reset to Defaults", use_container_width=True):
            st.session_state["space_groups"] = [dict(g) for g in DEFAULT_SPACE_GROUPS]
            st.session_state["rooms"] = _expand_groups_to_rooms(st.session_state["space_groups"])
            st.session_state["adj_matrix"] = None
            st.rerun()

    st.divider()

    # Render group cards
    groups_to_remove = []
    manual_overrides = {}

    for gi, g in enumerate(groups):
        with st.container(border=True):
            hc1, hc2, hc3 = st.columns([4, 2, 1])
            with hc1:
                new_name = st.text_input("Group Name", value=g["group_name"], key=f"gn_{gi}", label_visibility="collapsed")
                groups[gi]["group_name"] = new_name
            with hc2:
                zc = _zc(g["zone"])
                st.markdown(f'<span class="zone-dot" style="background:{zc};"></span> **{g["zone"]}**', unsafe_allow_html=True)
                new_zone = st.selectbox("Zone", zones, index=zones.index(g["zone"]), key=f"gz_{gi}", label_visibility="collapsed")
                groups[gi]["zone"] = new_zone
            with hc3:
                if st.button("✕", key=f"rm_{gi}", help="Remove this group"):
                    groups_to_remove.append(gi)

            # Room selection
            current_rooms = g.get("rooms", [])
            new_rooms = st.multiselect("Rooms in group", all_room_names, default=current_rooms, key=f"gr_{gi}")
            groups[gi]["rooms"] = new_rooms

            # Size mode per room
            sm = g.get("size_mode", "auto")
            for rname in new_rooms:
                rc1, rc2 = st.columns([3, 2])
                with rc1:
                    std = ROOM_STANDARDS.get(rname, {"min": 10, "recommended": 14})
                    if sm == "auto":
                        st.markdown(f"&nbsp;&nbsp;&nbsp;• **{rname}**: *{std['min']} m² (auto min)* <span class='auto-badge'>AUTO</span>", unsafe_allow_html=True)
                    else:
                        manual_val = st.number_input(f"{rname} area (m²)", min_value=1.0, value=float(std["min"]), step=1.0, key=f"mv_{gi}_{rname}")
                        manual_overrides[f"{gi}_{rname}"] = manual_val
                with rc2:
                    pass

            # Group total
            total_min = sum(ROOM_STANDARDS.get(r, {"min": 10})["min"] for r in new_rooms)
            st.caption(f"Auto minimum total: **{total_min} m²**")

            # Toggle size mode
            auto_on = st.toggle("Auto Minimum sizes", value=(sm == "auto"), key=f"sm_{gi}")
            groups[gi]["size_mode"] = "auto" if auto_on else "manual"

    # Process removals
    if groups_to_remove:
        for idx in sorted(groups_to_remove, reverse=True):
            groups.pop(idx)
        st.session_state["space_groups"] = groups
        st.rerun()

    # Sync flat rooms list from groups
    flat_rooms = []
    for gi, g in enumerate(groups):
        for rname in g.get("rooms", []):
            sm = g.get("size_mode", "auto")
            if sm == "auto":
                area = _get_room_area(rname, "auto")
            else:
                area = manual_overrides.get(f"{gi}_{rname}", _get_room_area(rname, "auto"))
            flat_rooms.append({"name": rname, "area": area, "zone": g["zone"], "priority": "High", "size_mode": sm, "group": g["group_name"]})
    st.session_state["rooms"] = flat_rooms
    st.session_state["space_groups"] = groups

    # Summary table
    st.divider()
    st.markdown("##### 📋 Expanded Room Summary")
    if flat_rooms:
        sum_df = pd.DataFrame(flat_rooms)
        st.dataframe(sum_df[["name","zone","size_mode","area","group"]].rename(columns={"name":"Room","zone":"Zone","size_mode":"Mode","area":"Area (m²)","group":"Group"}), use_container_width=True, hide_index=True)

        # Bar chart by zone
        st.divider()
        st.markdown("##### 📊 Area by Zone")
        zone_sum = sum_df.groupby("zone")["area"].sum().reset_index()
        fig_z = px.bar(zone_sum, x="zone", y="area", color="zone", color_discrete_map=ZONE_COLORS, text_auto=".0f")
        fig_z.update_layout(showlegend=False, xaxis_title="", yaxis_title="Area (m²)", height=300, margin=dict(l=0,r=0,t=10,b=0), plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)", font=dict(family="Inter", color="#cbd5e1"))
        fig_z.update_traces(marker_line_width=0, textfont_size=12, textposition="outside")
        st.plotly_chart(fig_z, use_container_width=True)


# ═════════════════════════════════════════════════════════════════════
# STAGE 03 – SPACE QUANTIFICATION
# ═════════════════════════════════════════════════════════════════════
elif stage_idx == 2:
    st.markdown('<div class="stage-badge">Stage 03</div>', unsafe_allow_html=True)
    st.subheader("Space Quantification")
    st.caption("Space requirement = usable area + circulation.")

    st.session_state["circ_pct"] = st.slider("Circulation Factor (%)", 10, 50, int(st.session_state["circ_pct"]), 5)

    rooms = st.session_state["rooms"]
    df = pd.DataFrame(rooms)
    if df.empty or "area" not in df.columns:
        st.info("Please define rooms in Stage 02 first.")
    else:
        circ = st.session_state["circ_pct"] / 100
        df["circulation"] = (df["area"] * circ).round(1)
        df["total"] = (df["area"] + df["circulation"]).round(1)
        df["mode_badge"] = df.get("size_mode", pd.Series(["auto"]*len(df))).apply(lambda x: "AUTO" if x == "auto" else "MANUAL")

        st.dataframe(
            df[["name","zone","area","circulation","total","mode_badge"]].rename(columns={
                "name":"Room", "zone":"Zone", "area":"Functional (m²)",
                "circulation":"Circulation (m²)", "total":"Total (m²)", "mode_badge":"Mode",
            }),
            use_container_width=True, hide_index=True,
        )

        func_total = df["area"].sum()
        circ_total = df["circulation"].sum()
        grand = df["total"].sum()

        st.divider()
        m1, m2, m3 = st.columns(3)
        with m1:
            st.markdown(f'<div class="metric-glow"><h3>Functional Area</h3><p>{func_total:,.0f} m²</p></div>', unsafe_allow_html=True)
        with m2:
            st.markdown(f'<div class="metric-glow"><h3>Circulation</h3><p>{circ_total:,.0f} m²</p></div>', unsafe_allow_html=True)
        with m3:
            st.markdown(f'<div class="metric-glow"><h3>Grand Total</h3><p>{grand:,.0f} m²</p></div>', unsafe_allow_html=True)

        max_floor = st.session_state["site_area"] * st.session_state["far"]
        if grand > max_floor:
            st.warning(f"⚠️ Total area ({grand:,.0f} m²) exceeds max allowable floor area ({max_floor:,.0f} m²).")
        else:
            utilisation = grand / max_floor * 100 if max_floor > 0 else 0
            st.success(f"✅ Within limits — utilisation {utilisation:.0f}% of {max_floor:,.0f} m² max.")

        # Group Summary accordion
        if "group" in df.columns:
            with st.expander("📁 Group Summary", expanded=False):
                grp_sum = df.groupby("group").agg({"area": "sum", "circulation": "sum", "total": "sum"}).reset_index()
                grp_sum.columns = ["Group", "Functional (m²)", "Circulation (m²)", "Total (m²)"]
                st.dataframe(grp_sum, use_container_width=True, hide_index=True)

        # Stacked bar chart
        st.divider()
        st.markdown("##### 📐 Area Breakdown per Room")
        fig_q = go.Figure()
        fig_q.add_trace(go.Bar(x=df["name"], y=df["area"], name="Functional", marker_color="#6c63ff"))
        fig_q.add_trace(go.Bar(x=df["name"], y=df["circulation"], name="Circulation", marker_color="#3b82f6"))
        fig_q.update_layout(barmode="stack", height=350, margin=dict(l=0,r=0,t=10,b=0), plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)", font=dict(family="Inter", color="#cbd5e1"), legend=dict(orientation="h", y=1.05), yaxis_title="Area (m²)")
        st.plotly_chart(fig_q, use_container_width=True)


# ═════════════════════════════════════════════════════════════════════
# STAGE 04 – RELATIONSHIP LOGIC (v2: Auto-Generate)
# ═════════════════════════════════════════════════════════════════════
elif stage_idx == 3:
    st.markdown('<div class="stage-badge">Stage 04</div>', unsafe_allow_html=True)
    st.subheader("Relationship Logic")
    st.caption("Spaces must relate according to function proximity.")

    rooms = st.session_state["rooms"]
    names = [r["name"] for r in rooms]
    n = len(names)

    if n < 2:
        st.info("Add at least 2 rooms in Stage 02.")
    else:
        if st.session_state["adj_matrix"] is None or len(st.session_state["adj_matrix"]) != n:
            st.session_state["adj_matrix"] = [[0]*n for _ in range(n)]

        # Auto-generate button
        if st.button("⚡ Auto-Generate from Rules", use_container_width=True, type="primary"):
            groups = st.session_state.get("space_groups", [])
            new_adj = [[0]*n for _ in range(n)]
            applied_rules = []
            for i in range(n):
                for j in range(i+1, n):
                    a, b = names[i], names[j]
                    val = _lookup_adjacency(a, b)
                    if val >= 0:
                        new_adj[i][j] = val
                        new_adj[j][i] = val
                        label = {0: "None", 1: "Convenient", 2: "Essential"}.get(val, str(val))
                        applied_rules.append(f"{a} ↔ {b}: {label} ({val})")
                    elif _rooms_in_same_group(a, b, groups):
                        new_adj[i][j] = 1
                        new_adj[j][i] = 1
                        applied_rules.append(f"{a} ↔ {b}: Same-group default (1)")
            st.session_state["adj_matrix"] = new_adj
            st.rerun()

        st.markdown("##### 🔗 Adjacency Matrix")
        st.caption("Rate proximity need: **0** = none, **1** = convenient, **2** = essential")

        adj = st.session_state["adj_matrix"]
        adj_df = pd.DataFrame(adj, index=names, columns=names)
        edited_adj = st.data_editor(adj_df, use_container_width=True, key="adj_editor")
        st.session_state["adj_matrix"] = edited_adj.values.tolist()

        # Info box: applied rules
        with st.expander("📋 Adjacency Rules Reference", expanded=False):
            for (a, b), v in ADJACENCY_RULES.items():
                label = {0: "None", 1: "Convenient", 2: "Essential"}.get(v, str(v))
                st.caption(f"• {a} ↔ {b}: **{label}** ({v})")

        # Heatmap
        st.divider()
        st.markdown("##### 🌡️ Proximity Heatmap")
        fig_h = px.imshow(
            edited_adj.values, x=names, y=names,
            color_continuous_scale=["#1e1e2e","#3b82f6","#f59e0b"],
            zmin=0, zmax=2, text_auto=True,
        )
        fig_h.update_layout(height=max(350, 50*n), margin=dict(l=0,r=0,t=10,b=0), paper_bgcolor="rgba(0,0,0,0)", font=dict(family="Inter", color="#cbd5e1"), coloraxis_colorbar=dict(title="Need", tickvals=[0,1,2], ticktext=["None","Conv.","Ess."]))
        st.plotly_chart(fig_h, use_container_width=True)


# ═════════════════════════════════════════════════════════════════════
# STAGE 05 – SPATIAL NETWORK (v2: Group coloring + Connectivity Score)
# ═════════════════════════════════════════════════════════════════════
elif stage_idx == 4:
    st.markdown('<div class="stage-badge">Stage 05</div>', unsafe_allow_html=True)
    st.subheader("Spatial Network")
    st.caption("Architecture is a network of spaces connected by movement.")

    rooms = st.session_state["rooms"]
    names = [r["name"] for r in rooms]
    n = len(names)
    adj = st.session_state.get("adj_matrix")

    if adj is None or len(adj) != n or n < 2:
        st.info("Please fill the adjacency matrix in Stage 04 first.")
    else:
        G = nx.Graph()
        for i, r in enumerate(rooms):
            G.add_node(names[i], zone=r.get("zone",""), area=r.get("area",10))
        essential_edges = 0
        convenient_edges = 0
        for i in range(n):
            for j in range(i+1, n):
                w = adj[i][j]
                if w > 0:
                    G.add_edge(names[i], names[j], weight=w)
                    if w == 2:
                        essential_edges += 1
                    else:
                        convenient_edges += 1

        pos = nx.spring_layout(G, seed=42, k=2.5)

        fig_net = go.Figure()

        # Group label annotations
        groups = st.session_state.get("space_groups", [])
        for g in groups:
            grp_nodes = [rn for rn in g.get("rooms", []) if rn in pos]
            if len(grp_nodes) >= 2:
                xs = [pos[rn][0] for rn in grp_nodes]
                ys = [pos[rn][1] for rn in grp_nodes]
                cx_g, cy_g = np.mean(xs), np.mean(ys)
                fig_net.add_annotation(
                    x=cx_g, y=cy_g - 0.12, text=f"〔{g['group_name']}〕",
                    showarrow=False,
                    font=dict(color="rgba(255,255,255,0.2)", size=10, family="Inter"),
                )

        # Edges by weight
        for w_val, color, width, dash in [(1,"#475569",1.5,"dot"),(2,"#f59e0b",2.5,"solid")]:
            ex, ey = [], []
            for u, v, d in G.edges(data=True):
                if d["weight"] == w_val:
                    x0, y0 = pos[u]; x1, y1 = pos[v]
                    ex += [x0, x1, None]; ey += [y0, y1, None]
            label = "Convenient" if w_val == 1 else "Essential"
            fig_net.add_trace(go.Scatter(x=ex, y=ey, mode="lines", name=label, line=dict(color=color, width=width, dash=dash), hoverinfo="none"))

        # Nodes
        node_x = [pos[nm][0] for nm in names]
        node_y = [pos[nm][1] for nm in names]
        node_sizes = [max(20, r.get("area",10)*1.1) for r in rooms]
        node_colors = [_zc(r.get("zone","")) for r in rooms]

        fig_net.add_trace(go.Scatter(
            x=node_x, y=node_y, mode="markers+text",
            marker=dict(size=node_sizes, color=node_colors, line=dict(width=2, color="rgba(255,255,255,0.3)")),
            text=names, textposition="top center",
            textfont=dict(size=11, color="#e2e8f0", family="Inter"),
            name="Rooms", hovertemplate="%{text}<extra></extra>",
        ))

        fig_net.update_layout(height=500, margin=dict(l=0,r=0,t=10,b=0), plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)", xaxis=dict(visible=False), yaxis=dict(visible=False), font=dict(family="Inter", color="#cbd5e1"), legend=dict(orientation="h", y=-0.05), showlegend=True)
        st.plotly_chart(fig_net, use_container_width=True)

        # Stats
        max_possible = n * (n - 1) / 2 if n > 1 else 1
        connectivity_score = (essential_edges * 2 + convenient_edges * 1) / (max_possible * 2) if max_possible > 0 else 0

        st.divider()
        mc1, mc2, mc3, mc4 = st.columns(4)
        with mc1:
            st.markdown(f'<div class="metric-glow"><h3>Nodes</h3><p>{G.number_of_nodes()}</p></div>', unsafe_allow_html=True)
        with mc2:
            st.markdown(f'<div class="metric-glow"><h3>Edges</h3><p>{G.number_of_edges()}</p></div>', unsafe_allow_html=True)
        with mc3:
            density = nx.density(G)
            st.markdown(f'<div class="metric-glow"><h3>Density</h3><p>{density:.2f}</p></div>', unsafe_allow_html=True)
        with mc4:
            st.markdown(f'<div class="metric-glow"><h3>Connectivity</h3><p>{connectivity_score:.2f}</p></div>', unsafe_allow_html=True)

        # AI Network Analysis (v2.1)
        ai_net = st.session_state.get("ai_stage_data", {}).get("network", {})
        if ai_net:
            st.divider()
            st.markdown("##### 🤖 AI Network Analysis")
            hub_rooms = ai_net.get("hub_rooms", [])
            if hub_rooms:
                st.info(f"**Hub rooms:** {', '.join(hub_rooms)}")
            clusters = ai_net.get("zone_clusters", [])
            if clusters:
                for cl in clusters:
                    cname = cl.get("cluster_name_th", cl.get("cluster_name", ""))
                    rooms_list = ", ".join(cl.get("rooms", []))
                    cohesion = cl.get("internal_cohesion", "")
                    st.markdown(f'<div class="pytron-card"><b>{cname}</b> ({cl.get("zone_type","")})<br>Rooms: {rooms_list}<br>Cohesion: {cohesion}</div>', unsafe_allow_html=True)
            cpaths = ai_net.get("critical_paths", [])
            if cpaths:
                with st.expander("🛤️ Critical Paths", expanded=False):
                    for cp in cpaths:
                        arrow = " → ".join(cp.get("path", []))
                        st.markdown(f"**{cp.get('importance','')}**: {arrow}")
                        st.caption(cp.get("path_name_th", ""))
            verdict = ai_net.get("spatial_network_quality_verdict", {})
            if verdict:
                st.success(f"Network Quality: **{verdict.get('score_label', '')}**")
                for sug in verdict.get("improvement_suggestions_th", []):
                    st.caption(f"💡 {sug}")


# ═════════════════════════════════════════════════════════════════════
# STAGE 06 – SCHEMATIC DESIGN (v2.1: AI Schematic Data)
# ═════════════════════════════════════════════════════════════════════
elif stage_idx == 5:
    st.markdown('<div class="stage-badge">Stage 06</div>', unsafe_allow_html=True)
    st.subheader("Schematic Design")
    st.caption("Convert conceptual relationships into real geometry.")

    rooms = st.session_state["rooms"]
    df = pd.DataFrame(rooms)
    if df.empty:
        st.info("Define rooms in Stage 02 first.")
    else:
        circ = st.session_state["circ_pct"] / 100
        df["total"] = df["area"] * (1 + circ)

        st.markdown("##### 🏗️ Schematic Block Plan")
        fig_tree = px.treemap(df, path=["zone", "name"], values="total", color="zone", color_discrete_map=ZONE_COLORS)
        fig_tree.update_layout(height=450, margin=dict(l=0,r=0,t=30,b=0), paper_bgcolor="rgba(0,0,0,0)", font=dict(family="Inter", color="#fff"))
        fig_tree.update_traces(textinfo="label+value", texttemplate="%{label}<br>%{value:.0f} m²", textfont_size=13, marker_line_width=2, marker_line_color="rgba(0,0,0,0.3)")
        st.plotly_chart(fig_tree, use_container_width=True)

        st.divider()
        st.markdown("##### 📏 Structure Grid Estimation")
        max_footprint = st.session_state["site_area"] * st.session_state["bcr"] / 100
        grand_total = df["total"].sum()
        est_floors = math.ceil(grand_total / max_footprint) if max_footprint > 0 else 1
        per_floor = grand_total / est_floors

        # Use AI grid if available
        ai_sch = st.session_state.get("ai_stage_data", {}).get("schematic", {})
        grid_opts = ["4×4 m","5×6 m","4×6 m","6×6 m","8×8 m","6×9 m","8×12 m"]
        ai_grid = ai_sch.get("recommended_structural_grid", "")
        default_gi = grid_opts.index(ai_grid) if ai_grid in grid_opts else 0

        gc1, gc2, gc3 = st.columns(3)
        with gc1:
            st.markdown(f'<div class="metric-glow"><h3>Est. Floors</h3><p>{ai_sch.get("estimated_floor_count", est_floors)}</p></div>', unsafe_allow_html=True)
        with gc2:
            st.markdown(f'<div class="metric-glow"><h3>Per Floor</h3><p>{per_floor:,.0f} m²</p></div>', unsafe_allow_html=True)
        with gc3:
            grid = st.selectbox("Grid Module", grid_opts, index=default_gi)
            st.markdown(f'<div class="metric-glow"><h3>Grid</h3><p>{grid}</p></div>', unsafe_allow_html=True)

        # AI Schematic panels (v2.1)
        if ai_sch:
            st.divider()
            st.markdown("##### 🤖 AI Schematic Design")

            # Grid rationale
            if ai_sch.get("recommended_grid_rationale_th"):
                st.info(f"**Grid Rationale:** {ai_sch['recommended_grid_rationale_th']}")

            # Zone layout strategy
            zls = ai_sch.get("zone_layout_strategy", {})
            if zls:
                with st.expander("🗺️ Zone Layout Strategy", expanded=True):
                    st.markdown(f"**Strategy:** {zls.get('description_th', '')}")
                    zc1, zc2, zc3 = st.columns(3)
                    with zc1:
                        st.markdown(f"**🚿 Wet Zone**\n\n{zls.get('wet_zone_placement', '')}")
                    with zc2:
                        st.markdown(f"**🛏️ Private Zone**\n\n{zls.get('private_zone_placement', '')}")
                    with zc3:
                        st.markdown(f"**🛋️ Social Zone**\n\n{zls.get('social_zone_placement', '')}")

            # Block plan sequence
            bps = ai_sch.get("block_plan_sequence", [])
            if bps:
                with st.expander("📐 Block Plan Sequence", expanded=True):
                    for bp in bps:
                        rooms_str = ", ".join(bp.get("rooms", []))
                        st.markdown(f'<div class="pytron-card"><b>{bp.get("position","")}</b>: {rooms_str}<br><small>{bp.get("rationale_th","")}</small></div>', unsafe_allow_html=True)

            # Facade strategy
            fs = ai_sch.get("facade_strategy", {})
            if fs:
                with st.expander("🏢 Facade & Ventilation Strategy", expanded=False):
                    st.markdown(f"**Primary Facade:** {fs.get('primary_facade_direction', '')}")
                    st.markdown(f"**Windows:** {fs.get('window_placement_th', '')}")
                    st.markdown(f"**Ventilation:** {fs.get('natural_ventilation_strategy_th', '')}")
                    st.markdown(f"**Shading:** {fs.get('shading_recommendation_th', '')}")

            # MEP
            mep = ai_sch.get("mep_recommendations", {})
            if mep:
                with st.expander("⚙️ MEP Recommendations", expanded=False):
                    st.markdown(f"**HVAC:** {mep.get('hvac_th', '')}")
                    st.markdown(f"**Plumbing Stack:** {mep.get('plumbing_stack_location', '')}")
                    st.markdown(f"**Electrical Panel:** {mep.get('electrical_panel_location', '')}")

            # Structure
            if ai_sch.get("structural_system_recommendation"):
                st.caption(f"🏗️ Structure: {ai_sch['structural_system_recommendation']}")

            # Summary
            if ai_sch.get("schematic_design_summary_th"):
                st.divider()
                st.markdown(f'<div class="law-card">{ai_sch["schematic_design_summary_th"]}</div>', unsafe_allow_html=True)

        # AI Overall Verdict (v2.1)
        ai_verdict = st.session_state.get("ai_verdict", {})
        ai_warnings = st.session_state.get("ai_warnings", [])
        ai_principles = st.session_state.get("ai_principles", [])
        if ai_verdict or ai_warnings:
            st.divider()
            st.markdown("##### 📊 AI Design Verdict")
            if ai_verdict:
                score = ai_verdict.get("score_out_of_10", "")
                st.markdown(f'<div class="metric-glow"><h3>Design Score</h3><p>{score} / 10</p></div>', unsafe_allow_html=True)
                st.markdown(f"**{ai_verdict.get('verdict_th', '')}**")
                vc1, vc2 = st.columns(2)
                with vc1:
                    st.markdown("**✅ Strengths**")
                    for s in ai_verdict.get("top_3_strengths_th", []):
                        st.caption(f"• {s}")
                with vc2:
                    st.markdown("**🔧 Improvements**")
                    for s in ai_verdict.get("top_3_improvements_th", []):
                        st.caption(f"• {s}")
            if ai_warnings:
                with st.expander("⚠️ Professional Warnings", expanded=False):
                    for w in ai_warnings:
                        st.warning(w)
            if ai_principles:
                with st.expander("📜 Design Principles Applied", expanded=False):
                    for p in ai_principles:
                        st.caption(f"✓ {p}")


# ═════════════════════════════════════════════════════════════════════
# STAGE 07 – DESIGN DEVELOPMENT (UNCHANGED)
# ═════════════════════════════════════════════════════════════════════
elif stage_idx == 6:
    st.markdown('<div class="stage-badge">Stage 07</div>', unsafe_allow_html=True)
    st.subheader("Design Development")
    st.caption("Refine structure, systems, materials, and façade.")

    t1, t2, t3 = st.tabs(["🏗️ Structure", "⚡ MEP Systems", "🎨 Materials & Character"])

    with t1:
        struct_opts = ["Reinforced Concrete Frame","Steel Frame","Load-bearing Wall","Timber Frame","Hybrid (RC + Steel)"]
        st.session_state["structure_sys"] = st.selectbox("Structural System", struct_opts, index=struct_opts.index(st.session_state["structure_sys"]))
        sys_data = {
            "Reinforced Concrete Frame": [8,6,7,5,9], "Steel Frame": [9,8,6,7,7],
            "Load-bearing Wall": [5,4,9,8,6], "Timber Frame": [6,7,5,9,4], "Hybrid (RC + Steel)": [9,8,7,6,8],
        }
        cats = ["Span","Speed","Cost","Sustainability","Fire Resistance"]
        vals = sys_data.get(st.session_state["structure_sys"], [5]*5)
        fig_r = go.Figure()
        fig_r.add_trace(go.Scatterpolar(r=vals+[vals[0]], theta=cats+[cats[0]], fill="toself", fillcolor="rgba(108,99,255,0.2)", line_color="#6c63ff", name=st.session_state["structure_sys"]))
        fig_r.update_layout(polar=dict(radialaxis=dict(visible=True, range=[0,10], showline=False, gridcolor="rgba(255,255,255,0.08)"), angularaxis=dict(gridcolor="rgba(255,255,255,0.08)"), bgcolor="rgba(0,0,0,0)"), height=350, margin=dict(l=40,r=40,t=30,b=30), paper_bgcolor="rgba(0,0,0,0)", font=dict(family="Inter", color="#cbd5e1"), showlegend=False)
        st.plotly_chart(fig_r, use_container_width=True)

    with t2:
        st.markdown("##### Mechanical · Electrical · Plumbing")
        mep_items = {
            "HVAC System": ["Central Chiller","Split Type","VRV/VRF","Natural Ventilation"],
            "Electrical": ["Single Phase","Three Phase"],
            "Water Supply": ["Municipal + Pump","Gravity Tank","Pressure Booster"],
            "Fire Protection": ["Sprinkler","Fire Extinguisher Only","Hydrant System"],
            "Solar / Renewable": ["None","Rooftop PV","BIPV Facade","Solar Water Heater"],
        }
        for label, options in mep_items.items():
            st.selectbox(label, options, key=f"mep_{label}")

    with t3:
        c1, c2 = st.columns(2)
        with c1:
            st.session_state["facade_mat"] = st.text_input("Façade Material", value=st.session_state["facade_mat"])
            roof_opts = ["Flat / Green Roof","Pitched Roof","Butterfly Roof","Barrel Vault","Folded Plate"]
            st.session_state["roof_type"] = st.selectbox("Roof Type", roof_opts, index=roof_opts.index(st.session_state["roof_type"]))
        with c2:
            st.multiselect("Interior Finishes", ["Polished Concrete","Hardwood","Ceramic Tile","Terrazzo","Epoxy","Carpet"], default=["Polished Concrete","Hardwood"], key="int_finishes")
            st.selectbox("Color Palette Mood", ["Warm Neutral","Cool Minimal","Earth Tone","Monochrome","Bold Contrast"], key="color_mood")


# ═════════════════════════════════════════════════════════════════════
# STAGE 08 – CONSTRUCTION DOCUMENTATION (UNCHANGED)
# ═════════════════════════════════════════════════════════════════════
elif stage_idx == 7:
    st.markdown('<div class="stage-badge">Stage 08</div>', unsafe_allow_html=True)
    st.subheader("Construction Documentation")
    st.caption("Translate design into precise instructions for construction.")

    drawing_sets = [
        {"set": "Architectural Drawings", "icon": "🏛️", "items": ["Floor Plans","Elevations","Sections","Roof Plan","Reflected Ceiling Plan","Door & Window Schedule"]},
        {"set": "Structural Drawings", "icon": "🔩", "items": ["Foundation Plan","Column Layout","Beam Layout","Slab Reinforcement","Structural Details"]},
        {"set": "Electrical Plans", "icon": "⚡", "items": ["Power Layout","Lighting Layout","Panel Schedule","Grounding Plan"]},
        {"set": "Plumbing Plans", "icon": "🚿", "items": ["Water Supply Isometric","Drainage Layout","Fixture Schedule"]},
        {"set": "Detail Drawings", "icon": "🔍", "items": ["Wall Section","Stair Detail","Window Detail","Wet Area Waterproofing","Expansion Joint"]},
    ]

    st.markdown("##### 📋 Drawing Set Checklist")
    progress_counts = []
    for ds in drawing_sets:
        with st.expander(f"{ds['icon']}  {ds['set']}", expanded=False):
            done = 0
            for item in ds["items"]:
                if st.checkbox(item, key=f"doc_{ds['set']}_{item}"):
                    done += 1
            progress_counts.append((ds["set"], done, len(ds["items"])))

    st.divider()
    st.markdown("##### 📈 Documentation Progress")
    total_items = sum(t for _, _, t in progress_counts)
    total_done = sum(d for _, d, _ in progress_counts)
    overall = total_done / total_items if total_items > 0 else 0
    st.progress(overall)
    st.caption(f"{total_done} / {total_items} items completed ({overall*100:.0f}%)")

    for name, done, total in progress_counts:
        pct = done / total if total > 0 else 0
        st.markdown(f"**{name}** — {done}/{total}")
        st.progress(pct)

    st.divider()
    st.markdown("##### 📄 Generate Summary Report")
    if st.button("📥 Generate Project Summary", type="primary"):
        rooms = st.session_state["rooms"]
        df = pd.DataFrame(rooms)
        circ = st.session_state["circ_pct"] / 100
        if not df.empty:
            df["total"] = (df["area"] * (1 + circ)).round(1)

        report_lines = [
            f"# PYTRON — Project Summary",
            f"**Project:** {st.session_state['project_name']}", "",
            "## Site Data",
            f"- Site Area: {st.session_state['site_area']:,.0f} m²",
            f"- FAR: {st.session_state['far']}",
            f"- BCR: {st.session_state['bcr']}%",
            f"- Setbacks: F={st.session_state['setback_f']}m, S={st.session_state['setback_s']}m, R={st.session_state['setback_r']}m",
            f"- Wind: {st.session_state['wind_dir']} | Sun: {st.session_state['sun_orient']} | Noise: {st.session_state['noise_src']}",
            "", "## Program",
        ]
        if not df.empty:
            for _, row in df.iterrows():
                report_lines.append(f"- {row['name']}: {row['area']} m² ({row['zone']})")
            report_lines.append(f"\n**Total (incl. {st.session_state['circ_pct']:.0f}% circulation): {df['total'].sum():,.0f} m²**")

        report_lines += [
            "", "## Systems",
            f"- Structure: {st.session_state['structure_sys']}",
            f"- Façade: {st.session_state['facade_mat']}",
            f"- Roof: {st.session_state['roof_type']}",
            "", "## Documentation Progress",
            f"- {total_done}/{total_items} drawings completed ({overall*100:.0f}%)",
        ]
        report_text = "\n".join(report_lines)
        st.download_button("⬇ Download Report (.md)", data=report_text, file_name=f"pytron_{st.session_state['project_name'].replace(' ','_')}_report.md", mime="text/markdown")
        st.markdown(report_text)


# ─────────────────────────────────────────────────────────────────────
# FOOTER
# ─────────────────────────────────────────────────────────────────────
st.divider()
with st.expander("📜 Professional Design Laws", expanded=False):
    laws = [
        "Bad spatial relationships cannot be fixed by decoration.",
        "Circulation efficiency defines building intelligence.",
        "The site dictates architecture more than aesthetics.",
        "Good architecture minimizes wasted movement.",
        "The earlier the design decision, the greater the impact.",
    ]
    for law in laws:
        st.markdown(f'<div class="law-card">"{law}"</div>', unsafe_allow_html=True)

st.markdown("""
<div style="text-align:center;padding:1rem 0 0.5rem 0;opacity:0.4;font-size:0.75rem;">
    PYTRON v2.1 · Architecture Design Framework · Simple · Stable · Fast
</div>
""", unsafe_allow_html=True)
