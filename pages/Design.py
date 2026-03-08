"""
PYTRON – Architecture Design Framework
Simple · Stable · Fast

8-stage pipeline from site intelligence to construction documentation.
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
</style>
""", unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────
# 1. SESSION STATE DEFAULTS
# ─────────────────────────────────────────────────────────────────────
_DEFAULTS: Dict = {
    "project_name": "Untitled Project",
    # Stage 1 – Site Intelligence
    "site_area":   400.0,
    "far":         2.5,
    "bcr":         60.0,
    "setback_f":   6.0,
    "setback_s":   3.0,
    "setback_r":   3.0,
    "wind_dir":    "South-West",
    "sun_orient":  "East-West",
    "noise_src":   "North",
    # Stage 2 – Program
    "rooms": [
        {"name": "Living Room",   "area": 35.0, "zone": "Social",   "priority": "High"},
        {"name": "Kitchen",       "area": 16.0, "zone": "Service",  "priority": "High"},
        {"name": "Master Bedroom","area": 25.0, "zone": "Private",  "priority": "High"},
        {"name": "Bedroom 2",     "area": 16.0, "zone": "Private",  "priority": "Medium"},
        {"name": "Bathroom 1",    "area": 6.0,  "zone": "Service",  "priority": "High"},
        {"name": "Bathroom 2",    "area": 5.0,  "zone": "Service",  "priority": "Medium"},
        {"name": "Garage",        "area": 36.0, "zone": "Service",  "priority": "Low"},
    ],
    # Stage 3 – Circulation %
    "circ_pct": 30.0,
    # Stage 4 – Adjacency
    "adj_matrix": None,
    # Stage 7 – Materials
    "structure_sys": "Reinforced Concrete Frame",
    "facade_mat":    "Exposed Concrete + Timber Cladding",
    "roof_type":     "Flat / Green Roof",
}

for k, v in _DEFAULTS.items():
    if k not in st.session_state:
        st.session_state[k] = v


# ─────────────────────────────────────────────────────────────────────
# HELPER: colours for zones
# ─────────────────────────────────────────────────────────────────────
ZONE_COLORS = {
    "Social":  "#6c63ff",
    "Private": "#f472b6",
    "Service": "#06b6d4",
    "Outdoor": "#34d399",
}

def _zc(z: str) -> str:
    return ZONE_COLORS.get(z, "#94a3b8")


# ─────────────────────────────────────────────────────────────────────
# SIDEBAR
# ─────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## 🏛️ PYTRON")
    st.caption("Architecture Design Framework")
    st.divider()

    st.session_state["project_name"] = st.text_input(
        "Project Name", value=st.session_state["project_name"]
    )

    stage_labels = [
        "01 · Site Intelligence",
        "02 · Program Definition",
        "03 · Space Quantification",
        "04 · Relationship Logic",
        "05 · Spatial Network",
        "06 · Schematic Design",
        "07 · Design Development",
        "08 · Construction Docs",
    ]
    current = st.radio("Navigate Stage", stage_labels, index=0)
    stage_idx = stage_labels.index(current)
    st.progress((stage_idx + 1) / len(stage_labels))

    st.divider()
    # ── Export / Import ──────────────────────────────────────────────
    with st.expander("💾 Export / Import", expanded=False):
        export_data = {
            k: v for k, v in st.session_state.items()
            if k in _DEFAULTS
        }
        st.download_button(
            "⬇ Export JSON",
            data=json.dumps(export_data, indent=2, default=str),
            file_name=f"pytron_{st.session_state['project_name'].replace(' ','_')}.json",
            mime="application/json",
        )
        uploaded = st.file_uploader("⬆ Import JSON", type=["json"])
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
# STAGE 01 – SITE INTELLIGENCE
# ═════════════════════════════════════════════════════════════════════
if stage_idx == 0:
    st.markdown('<div class="stage-badge">Stage 01</div>', unsafe_allow_html=True)
    st.subheader("Site Intelligence")
    st.caption("Architecture begins with land, climate, and regulations.")

    c1, c2 = st.columns(2)
    with c1:
        st.session_state["site_area"] = st.number_input(
            "Site Area (sq m)", min_value=10.0, value=st.session_state["site_area"], step=10.0
        )
        st.session_state["far"] = st.number_input(
            "Floor Area Ratio (FAR)", min_value=0.1, value=st.session_state["far"], step=0.1
        )
        st.session_state["bcr"] = st.slider(
            "Building Coverage Ratio (%)", 10, 90, int(st.session_state["bcr"])
        )
    with c2:
        st.session_state["setback_f"] = st.number_input("Front Setback (m)", 0.0, 20.0, st.session_state["setback_f"], 0.5)
        st.session_state["setback_s"] = st.number_input("Side Setback (m)",  0.0, 20.0, st.session_state["setback_s"], 0.5)
        st.session_state["setback_r"] = st.number_input("Rear Setback (m)",  0.0, 20.0, st.session_state["setback_r"], 0.5)

    st.divider()
    c3, c4, c5 = st.columns(3)
    with c3:
        st.session_state["wind_dir"] = st.selectbox(
            "🌬️ Prevailing Wind", ["North","North-East","East","South-East","South","South-West","West","North-West"],
            index=["North","North-East","East","South-East","South","South-West","West","North-West"].index(st.session_state["wind_dir"]),
        )
    with c4:
        st.session_state["sun_orient"] = st.selectbox(
            "☀️ Sun Orientation", ["East-West","North-South"],
            index=["East-West","North-South"].index(st.session_state["sun_orient"]),
        )
    with c5:
        st.session_state["noise_src"] = st.selectbox(
            "🔊 Primary Noise Source", ["North","East","South","West","None"],
            index=["North","East","South","West","None"].index(st.session_state["noise_src"]),
        )

    # ── Computed metrics ─────────────────────────────────────────────
    max_bldg_footprint = st.session_state["site_area"] * st.session_state["bcr"] / 100
    max_total_floor    = st.session_state["site_area"] * st.session_state["far"]

    st.divider()
    m1, m2, m3 = st.columns(3)
    with m1:
        st.markdown(f"""
        <div class="metric-glow">
            <h3>Max Footprint</h3>
            <p>{max_bldg_footprint:,.0f} m²</p>
        </div>
        """, unsafe_allow_html=True)
    with m2:
        st.markdown(f"""
        <div class="metric-glow">
            <h3>Max Total Floor</h3>
            <p>{max_total_floor:,.0f} m²</p>
        </div>
        """, unsafe_allow_html=True)
    with m3:
        est_floors = max_total_floor / max_bldg_footprint if max_bldg_footprint > 0 else 0
        st.markdown(f"""
        <div class="metric-glow">
            <h3>Est. Floors</h3>
            <p>{est_floors:,.1f}</p>
        </div>
        """, unsafe_allow_html=True)

    # ── Site Constraints Diagram ─────────────────────────────────────
    st.divider()
    st.markdown("##### 🗺️ Site Constraints Map")

    _W = 20  # abstract width for diagram
    _H = _W * 0.75
    sb_f = st.session_state["setback_f"]
    sb_s = st.session_state["setback_s"]
    sb_r = st.session_state["setback_r"]

    fig_site = go.Figure()
    # site boundary
    fig_site.add_shape(type="rect", x0=0, y0=0, x1=_W, y1=_H,
                       line=dict(color="#94a3b8", width=2, dash="dot"),
                       fillcolor="rgba(30,30,46,0.6)")
    # buildable area
    fig_site.add_shape(type="rect",
                       x0=sb_s, y0=sb_f, x1=_W - sb_s, y1=_H - sb_r,
                       line=dict(color="#6c63ff", width=2),
                       fillcolor="rgba(108,99,255,0.12)")
    fig_site.add_annotation(x=_W/2, y=_H/2, text="Buildable<br>Area",
                            showarrow=False, font=dict(color="#a5b4fc", size=14, family="Inter"))
    # direction labels
    fig_site.add_annotation(x=_W/2, y=-0.8, text="FRONT (Road)", showarrow=False,
                            font=dict(color="#f59e0b", size=11))
    fig_site.add_annotation(x=_W/2, y=_H+0.8, text="REAR", showarrow=False,
                            font=dict(color="#94a3b8", size=11))
    # wind arrow (simplified)
    _DIR_ANGLES = {"North":90,"North-East":45,"East":0,"South-East":-45,
                   "South":-90,"South-West":-135,"West":180,"North-West":135}
    wa = math.radians(_DIR_ANGLES.get(st.session_state["wind_dir"], 0))
    cx, cy = _W/2, _H/2
    arrow_len = 3
    fig_site.add_annotation(
        x=cx + arrow_len*math.cos(wa), y=cy + arrow_len*math.sin(wa),
        ax=cx - arrow_len*math.cos(wa), ay=cy - arrow_len*math.sin(wa),
        xref="x", yref="y", axref="x", ayref="y",
        showarrow=True, arrowhead=3, arrowsize=1.5, arrowwidth=2,
        arrowcolor="#06b6d4",
    )
    fig_site.add_annotation(
        x=cx + (arrow_len+1.2)*math.cos(wa),
        y=cy + (arrow_len+1.2)*math.sin(wa),
        text="🌬️ Wind", showarrow=False,
        font=dict(color="#06b6d4", size=10),
    )
    fig_site.update_layout(
        xaxis=dict(visible=False, range=[-2, _W+2]),
        yaxis=dict(visible=False, range=[-2, _H+2], scaleanchor="x"),
        height=380,
        margin=dict(l=0,r=0,t=10,b=10),
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
    )
    st.plotly_chart(fig_site, use_container_width=True)


# ═════════════════════════════════════════════════════════════════════
# STAGE 02 – PROGRAM DEFINITION
# ═════════════════════════════════════════════════════════════════════
elif stage_idx == 1:
    st.markdown('<div class="stage-badge">Stage 02</div>', unsafe_allow_html=True)
    st.subheader("Program Definition")
    st.caption("Translate human needs into spatial requirements.")

    rooms = st.session_state["rooms"]
    zones = ["Social", "Private", "Service", "Outdoor"]
    priorities = ["High", "Medium", "Low"]

    st.markdown("##### ✏️ Room List Editor")
    edited = st.data_editor(
        pd.DataFrame(rooms),
        num_rows="dynamic",
        column_config={
            "name":     st.column_config.TextColumn("Room Name", width="medium"),
            "area":     st.column_config.NumberColumn("Area (m²)", min_value=1, max_value=500, step=1),
            "zone":     st.column_config.SelectboxColumn("Zone", options=zones),
            "priority": st.column_config.SelectboxColumn("Priority", options=priorities),
        },
        use_container_width=True,
        key="room_editor",
    )
    st.session_state["rooms"] = edited.to_dict("records")

    st.divider()
    c1, c2 = st.columns(2)

    with c1:
        st.markdown("##### 📊 Area by Zone")
        df = pd.DataFrame(st.session_state["rooms"])
        if not df.empty and "zone" in df.columns:
            zone_sum = df.groupby("zone")["area"].sum().reset_index()
            fig_z = px.bar(
                zone_sum, x="zone", y="area", color="zone",
                color_discrete_map=ZONE_COLORS,
                text_auto=".0f",
            )
            fig_z.update_layout(
                showlegend=False,
                xaxis_title="", yaxis_title="Area (m²)",
                height=300,
                margin=dict(l=0,r=0,t=10,b=0),
                plot_bgcolor="rgba(0,0,0,0)",
                paper_bgcolor="rgba(0,0,0,0)",
                font=dict(family="Inter", color="#cbd5e1"),
            )
            fig_z.update_traces(
                marker_line_width=0,
                textfont_size=12,
                textposition="outside",
            )
            st.plotly_chart(fig_z, use_container_width=True)

    with c2:
        st.markdown("##### 🥧 Zone Proportion")
        if not df.empty and "zone" in df.columns:
            fig_p = px.pie(
                zone_sum, names="zone", values="area",
                color="zone", color_discrete_map=ZONE_COLORS,
                hole=0.45,
            )
            fig_p.update_layout(
                height=300,
                margin=dict(l=0,r=0,t=10,b=0),
                paper_bgcolor="rgba(0,0,0,0)",
                font=dict(family="Inter", color="#cbd5e1"),
                legend=dict(orientation="h", y=-0.1),
            )
            fig_p.update_traces(textinfo="label+percent", textfont_size=11)
            st.plotly_chart(fig_p, use_container_width=True)


# ═════════════════════════════════════════════════════════════════════
# STAGE 03 – SPACE QUANTIFICATION
# ═════════════════════════════════════════════════════════════════════
elif stage_idx == 2:
    st.markdown('<div class="stage-badge">Stage 03</div>', unsafe_allow_html=True)
    st.subheader("Space Quantification")
    st.caption("Space requirement = usable area + circulation (≈30%).")

    st.session_state["circ_pct"] = st.slider(
        "Circulation Factor (%)", 10, 50, int(st.session_state["circ_pct"]), 5
    )

    rooms = st.session_state["rooms"]
    df = pd.DataFrame(rooms)
    if df.empty or "area" not in df.columns:
        st.info("Please define rooms in Stage 02 first.")
    else:
        circ = st.session_state["circ_pct"] / 100
        df["circulation"] = (df["area"] * circ).round(1)
        df["total"] = (df["area"] + df["circulation"]).round(1)

        st.dataframe(
            df[["name","zone","area","circulation","total"]].rename(columns={
                "name": "Room", "zone": "Zone",
                "area": "Functional (m²)",
                "circulation": "Circulation (m²)",
                "total": "Total (m²)",
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

        # Check against site limits
        max_floor = st.session_state["site_area"] * st.session_state["far"]
        if grand > max_floor:
            st.warning(f"⚠️ Total area ({grand:,.0f} m²) exceeds max allowable floor area ({max_floor:,.0f} m²).")
        else:
            utilisation = grand / max_floor * 100 if max_floor > 0 else 0
            st.success(f"✅ Within limits — utilisation {utilisation:.0f}% of {max_floor:,.0f} m² max.")

        # Stacked bar chart
        st.divider()
        st.markdown("##### 📐 Area Breakdown per Room")
        fig_q = go.Figure()
        fig_q.add_trace(go.Bar(
            x=df["name"], y=df["area"],
            name="Functional", marker_color="#6c63ff",
        ))
        fig_q.add_trace(go.Bar(
            x=df["name"], y=df["circulation"],
            name="Circulation", marker_color="#3b82f6",
        ))
        fig_q.update_layout(
            barmode="stack", height=350,
            margin=dict(l=0,r=0,t=10,b=0),
            plot_bgcolor="rgba(0,0,0,0)",
            paper_bgcolor="rgba(0,0,0,0)",
            font=dict(family="Inter", color="#cbd5e1"),
            legend=dict(orientation="h", y=1.05),
            yaxis_title="Area (m²)",
        )
        st.plotly_chart(fig_q, use_container_width=True)


# ═════════════════════════════════════════════════════════════════════
# STAGE 04 – RELATIONSHIP LOGIC
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
        # Build / load adjacency matrix
        if st.session_state["adj_matrix"] is None or len(st.session_state["adj_matrix"]) != n:
            st.session_state["adj_matrix"] = [[0]*n for _ in range(n)]

        st.markdown("##### 🔗 Adjacency Matrix")
        st.caption("Rate proximity need: **0** = none, **1** = convenient, **2** = essential")

        adj = st.session_state["adj_matrix"]
        adj_df = pd.DataFrame(adj, index=names, columns=names)
        edited_adj = st.data_editor(
            adj_df,
            use_container_width=True,
            key="adj_editor",
        )
        st.session_state["adj_matrix"] = edited_adj.values.tolist()

        # Visualise as heatmap
        st.divider()
        st.markdown("##### 🌡️ Proximity Heatmap")
        fig_h = px.imshow(
            edited_adj.values,
            x=names, y=names,
            color_continuous_scale=["#1e1e2e","#3b82f6","#f59e0b"],
            zmin=0, zmax=2,
            text_auto=True,
        )
        fig_h.update_layout(
            height=max(350, 50*n),
            margin=dict(l=0,r=0,t=10,b=0),
            paper_bgcolor="rgba(0,0,0,0)",
            font=dict(family="Inter", color="#cbd5e1"),
            coloraxis_colorbar=dict(title="Need", tickvals=[0,1,2], ticktext=["None","Conv.","Ess."]),
        )
        st.plotly_chart(fig_h, use_container_width=True)


# ═════════════════════════════════════════════════════════════════════
# STAGE 05 – SPATIAL NETWORK
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
        for i in range(n):
            for j in range(i+1, n):
                w = adj[i][j]
                if w > 0:
                    G.add_edge(names[i], names[j], weight=w)

        pos = nx.spring_layout(G, seed=42, k=2.5)

        # Build Plotly figure
        edge_x, edge_y = [], []
        edge_colors = []
        for u, v, d in G.edges(data=True):
            x0, y0 = pos[u]
            x1, y1 = pos[v]
            edge_x += [x0, x1, None]
            edge_y += [y0, y1, None]

        fig_net = go.Figure()

        # edges – split by weight for colouring
        for w_val, color, width, dash in [(1,"#475569",1.5,"dot"),(2,"#f59e0b",2.5,"solid")]:
            ex, ey = [], []
            for u, v, d in G.edges(data=True):
                if d["weight"] == w_val:
                    x0, y0 = pos[u]
                    x1, y1 = pos[v]
                    ex += [x0, x1, None]
                    ey += [y0, y1, None]
            label = "Convenient" if w_val == 1 else "Essential"
            fig_net.add_trace(go.Scatter(
                x=ex, y=ey, mode="lines", name=label,
                line=dict(color=color, width=width, dash=dash),
                hoverinfo="none",
            ))

        # nodes
        node_x = [pos[nm][0] for nm in names]
        node_y = [pos[nm][1] for nm in names]
        node_sizes = [max(20, r.get("area",10)*1.1) for r in rooms]
        node_colors = [_zc(r.get("zone","")) for r in rooms]

        fig_net.add_trace(go.Scatter(
            x=node_x, y=node_y, mode="markers+text",
            marker=dict(size=node_sizes, color=node_colors,
                        line=dict(width=2, color="rgba(255,255,255,0.3)")),
            text=names,
            textposition="top center",
            textfont=dict(size=11, color="#e2e8f0", family="Inter"),
            name="Rooms",
            hovertemplate="%{text}<extra></extra>",
        ))

        fig_net.update_layout(
            height=500,
            margin=dict(l=0,r=0,t=10,b=0),
            plot_bgcolor="rgba(0,0,0,0)",
            paper_bgcolor="rgba(0,0,0,0)",
            xaxis=dict(visible=False), yaxis=dict(visible=False),
            font=dict(family="Inter", color="#cbd5e1"),
            legend=dict(orientation="h", y=-0.05),
            showlegend=True,
        )
        st.plotly_chart(fig_net, use_container_width=True)

        # Network stats
        st.divider()
        mc1, mc2, mc3 = st.columns(3)
        with mc1:
            st.markdown(f'<div class="metric-glow"><h3>Nodes</h3><p>{G.number_of_nodes()}</p></div>', unsafe_allow_html=True)
        with mc2:
            st.markdown(f'<div class="metric-glow"><h3>Edges</h3><p>{G.number_of_edges()}</p></div>', unsafe_allow_html=True)
        with mc3:
            density = nx.density(G)
            st.markdown(f'<div class="metric-glow"><h3>Density</h3><p>{density:.2f}</p></div>', unsafe_allow_html=True)


# ═════════════════════════════════════════════════════════════════════
# STAGE 06 – SCHEMATIC DESIGN
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

        # Simple packing algorithm — treemap-style
        st.markdown("##### 🏗️ Schematic Block Plan")
        fig_tree = px.treemap(
            df, path=["zone", "name"], values="total",
            color="zone", color_discrete_map=ZONE_COLORS,
        )
        fig_tree.update_layout(
            height=450,
            margin=dict(l=0,r=0,t=30,b=0),
            paper_bgcolor="rgba(0,0,0,0)",
            font=dict(family="Inter", color="#fff"),
        )
        fig_tree.update_traces(
            textinfo="label+value",
            texttemplate="%{label}<br>%{value:.0f} m²",
            textfont_size=13,
            marker_line_width=2,
            marker_line_color="rgba(0,0,0,0.3)",
        )
        st.plotly_chart(fig_tree, use_container_width=True)

        # Structure grid estimation
        st.divider()
        st.markdown("##### 📏 Structure Grid Estimation")
        max_footprint = st.session_state["site_area"] * st.session_state["bcr"] / 100
        grand_total = df["total"].sum()
        est_floors = math.ceil(grand_total / max_footprint) if max_footprint > 0 else 1
        per_floor = grand_total / est_floors

        gc1, gc2, gc3 = st.columns(3)
        with gc1:
            st.markdown(f'<div class="metric-glow"><h3>Est. Floors</h3><p>{est_floors}</p></div>', unsafe_allow_html=True)
        with gc2:
            st.markdown(f'<div class="metric-glow"><h3>Per Floor</h3><p>{per_floor:,.0f} m²</p></div>', unsafe_allow_html=True)
        with gc3:
            grid = st.selectbox("Grid Module", ["4×4 m","6×6 m","8×8 m","6×9 m","8×12 m"])
            st.markdown(f'<div class="metric-glow"><h3>Grid</h3><p>{grid}</p></div>', unsafe_allow_html=True)


# ═════════════════════════════════════════════════════════════════════
# STAGE 07 – DESIGN DEVELOPMENT
# ═════════════════════════════════════════════════════════════════════
elif stage_idx == 6:
    st.markdown('<div class="stage-badge">Stage 07</div>', unsafe_allow_html=True)
    st.subheader("Design Development")
    st.caption("Refine structure, systems, materials, and façade.")

    t1, t2, t3 = st.tabs(["🏗️ Structure", "⚡ MEP Systems", "🎨 Materials & Character"])

    with t1:
        st.session_state["structure_sys"] = st.selectbox(
            "Structural System",
            ["Reinforced Concrete Frame","Steel Frame","Load-bearing Wall","Timber Frame","Hybrid (RC + Steel)"],
            index=["Reinforced Concrete Frame","Steel Frame","Load-bearing Wall","Timber Frame","Hybrid (RC + Steel)"]
            .index(st.session_state["structure_sys"]),
        )
        # Simple comparison radar
        sys_data = {
            "Reinforced Concrete Frame": [8,6,7,5,9],
            "Steel Frame":              [9,8,6,7,7],
            "Load-bearing Wall":        [5,4,9,8,6],
            "Timber Frame":             [6,7,5,9,4],
            "Hybrid (RC + Steel)":      [9,8,7,6,8],
        }
        cats = ["Span","Speed","Cost","Sustainability","Fire Resistance"]
        vals = sys_data.get(st.session_state["structure_sys"], [5]*5)
        fig_r = go.Figure()
        fig_r.add_trace(go.Scatterpolar(
            r=vals + [vals[0]], theta=cats + [cats[0]],
            fill="toself",
            fillcolor="rgba(108,99,255,0.2)",
            line_color="#6c63ff",
            name=st.session_state["structure_sys"],
        ))
        fig_r.update_layout(
            polar=dict(
                radialaxis=dict(visible=True, range=[0,10], showline=False, gridcolor="rgba(255,255,255,0.08)"),
                angularaxis=dict(gridcolor="rgba(255,255,255,0.08)"),
                bgcolor="rgba(0,0,0,0)",
            ),
            height=350,
            margin=dict(l=40,r=40,t=30,b=30),
            paper_bgcolor="rgba(0,0,0,0)",
            font=dict(family="Inter", color="#cbd5e1"),
            showlegend=False,
        )
        st.plotly_chart(fig_r, use_container_width=True)

    with t2:
        st.markdown("##### Mechanical · Electrical · Plumbing")
        mep_items = {
            "HVAC System": ["Central Chiller","Split Type","VRV/VRF","Natural Ventilation"],
            "Electrical":  ["Single Phase","Three Phase"],
            "Water Supply": ["Municipal + Pump","Gravity Tank","Pressure Booster"],
            "Fire Protection": ["Sprinkler","Fire Extinguisher Only","Hydrant System"],
            "Solar / Renewable": ["None","Rooftop PV","BIPV Facade","Solar Water Heater"],
        }
        selections = {}
        for label, options in mep_items.items():
            selections[label] = st.selectbox(label, options)

    with t3:
        c1, c2 = st.columns(2)
        with c1:
            st.session_state["facade_mat"] = st.text_input(
                "Façade Material", value=st.session_state["facade_mat"]
            )
            st.session_state["roof_type"] = st.selectbox(
                "Roof Type",
                ["Flat / Green Roof","Pitched Roof","Butterfly Roof","Barrel Vault","Folded Plate"],
                index=["Flat / Green Roof","Pitched Roof","Butterfly Roof","Barrel Vault","Folded Plate"]
                .index(st.session_state["roof_type"]),
            )
        with c2:
            int_finishes = st.multiselect(
                "Interior Finishes",
                ["Polished Concrete","Hardwood","Ceramic Tile","Terrazzo","Epoxy","Carpet"],
                default=["Polished Concrete","Hardwood"],
            )
            color_palette = st.selectbox(
                "Color Palette Mood",
                ["Warm Neutral","Cool Minimal","Earth Tone","Monochrome","Bold Contrast"],
            )


# ═════════════════════════════════════════════════════════════════════
# STAGE 08 – CONSTRUCTION DOCUMENTATION
# ═════════════════════════════════════════════════════════════════════
elif stage_idx == 7:
    st.markdown('<div class="stage-badge">Stage 08</div>', unsafe_allow_html=True)
    st.subheader("Construction Documentation")
    st.caption("Translate design into precise instructions for construction.")

    drawing_sets = [
        {"set": "Architectural Drawings", "icon": "🏛️",
         "items": ["Floor Plans","Elevations","Sections","Roof Plan","Reflected Ceiling Plan","Door & Window Schedule"]},
        {"set": "Structural Drawings", "icon": "🔩",
         "items": ["Foundation Plan","Column Layout","Beam Layout","Slab Reinforcement","Structural Details"]},
        {"set": "Electrical Plans",  "icon": "⚡",
         "items": ["Power Layout","Lighting Layout","Panel Schedule","Grounding Plan"]},
        {"set": "Plumbing Plans",    "icon": "🚿",
         "items": ["Water Supply Isometric","Drainage Layout","Fixture Schedule"]},
        {"set": "Detail Drawings",   "icon": "🔍",
         "items": ["Wall Section","Stair Detail","Window Detail","Wet Area Waterproofing","Expansion Joint"]},
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
    total_done  = sum(d for _, d, _ in progress_counts)
    overall = total_done / total_items if total_items > 0 else 0
    st.progress(overall)
    st.caption(f"{total_done} / {total_items} items completed ({overall*100:.0f}%)")

    # Per-set progress bar
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
            f"**Project:** {st.session_state['project_name']}",
            "",
            "## Site Data",
            f"- Site Area: {st.session_state['site_area']:,.0f} m²",
            f"- FAR: {st.session_state['far']}",
            f"- BCR: {st.session_state['bcr']}%",
            f"- Setbacks: F={st.session_state['setback_f']}m, S={st.session_state['setback_s']}m, R={st.session_state['setback_r']}m",
            f"- Wind: {st.session_state['wind_dir']} | Sun: {st.session_state['sun_orient']} | Noise: {st.session_state['noise_src']}",
            "",
            "## Program",
        ]
        if not df.empty:
            for _, row in df.iterrows():
                report_lines.append(f"- {row['name']}: {row['area']} m² ({row['zone']})")
            report_lines.append(f"\n**Total (incl. {st.session_state['circ_pct']:.0f}% circulation): {df['total'].sum():,.0f} m²**")

        report_lines += [
            "",
            "## Systems",
            f"- Structure: {st.session_state['structure_sys']}",
            f"- Façade: {st.session_state['facade_mat']}",
            f"- Roof: {st.session_state['roof_type']}",
            "",
            "## Documentation Progress",
            f"- {total_done}/{total_items} drawings completed ({overall*100:.0f}%)",
        ]
        report_text = "\n".join(report_lines)
        st.download_button(
            "⬇ Download Report (.md)",
            data=report_text,
            file_name=f"pytron_{st.session_state['project_name'].replace(' ','_')}_report.md",
            mime="text/markdown",
        )
        st.markdown(report_text)


# ─────────────────────────────────────────────────────────────────────
# FOOTER — Professional Design Laws
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
    PYTRON · Architecture Design Framework · Simple · Stable · Fast
</div>
""", unsafe_allow_html=True)
