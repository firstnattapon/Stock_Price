import streamlit as st
import json
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import matplotlib.pyplot as plt
import seaborn as sns
import numpy as np
import math

# ==========================================
# ⚙️ Page Setup
# ==========================================
st.set_page_config(page_title="AI Architecture Pipeline", layout="wide", page_icon="🏛️")
st.title("🏛️ AI Architecture: Schematic Design Pipeline")
st.markdown("ระบบแปลงข้อมูล (Program) → AI Prompt → Visualized Schematic Design")

# ==========================================
# 🗂️ Tabs Layout
# ==========================================
tab1, tab2 = st.tabs(["📤 1. USER INPUT & EXPORT PROMPT", "📥 2. IMPORT JSON & FINAL PRODUCT"])

# ==========================================
# 📤 TAB 1: User Input & Export JSON
# ==========================================
with tab1:
    st.header("1. Program Definition & Site")

    col1, col2 = st.columns(2)
    with col1:
        project_type = st.text_input("ประเภทโครงการ (Project Type)", value="บ้านเช่า (Rental House)")
        width = st.number_input("ความกว้าง Site (ม.)", value=8.0, step=0.5)
        length = st.number_input("ความยาว Site (ม.)", value=4.0, step=0.5)

    with col2:
        rooms = st.multiselect(
            "พื้นที่ใช้สอยที่ต้องการ (Required Rooms)",
            ["Bedroom", "Living Area", "Kitchen", "Dining", "Bathroom", "Balcony", "Laundry" , "Closet"],
            default=["Bedroom", "Living Area", "Kitchen", "Dining", "Bathroom"  , "Closet"]
        )
        mode = st.radio(
            "รูปแบบการคำนวณพื้นที่ (Sizing Mode)",
            ["Auto (คำนวณตามมาตรฐานขั้นต่ำกฎหมาย/Neufert)", "Manual (ผู้ใช้กำหนดเอง)"]
        )

    # ==========================================
    # ✏️ MANUAL MODE — inputs per room
    # ==========================================
    manual_areas = {}
    DEFAULT_AREAS = {
        "Bedroom": 9.0,
        "Living Area": 8.0,
        "Kitchen": 4.5,
        "Dining": 4.0,
        "Bathroom": 3.0,
        "Balcony": 2.5,
        "Laundry": 2.0,
        "Closet": 3.0,
    }

    if mode == "Manual (ผู้ใช้กำหนดเอง)":
        if rooms:
            st.divider()
            st.subheader("📐 กำหนดพื้นที่แต่ละห้องด้วยตนเอง")
            cols = st.columns(min(len(rooms), 4))
            for i, room in enumerate(rooms):
                with cols[i % 4]:
                    manual_areas[room] = st.number_input(
                        f"**{room}** (ตร.ม.)",
                        value=DEFAULT_AREAS.get(room, 4.0),
                        min_value=1.0,
                        max_value=100.0,
                        step=0.5,
                        key=f"manual_{room}",
                    )
            total_manual = sum(manual_areas.values())
            site_area = width * length
            pct = (total_manual / site_area * 100) if site_area > 0 else 0
            col_a, col_b, col_c = st.columns(3)
            col_a.metric("📐 Total Net Area", f"{total_manual:.1f} ตร.ม.")
            col_b.metric("🏗️ Site Area", f"{site_area:.1f} ตร.ม.")
            col_c.metric(
                "📊 Coverage",
                f"{pct:.0f}%",
                delta="⚠️ เกิน Site!" if pct > 100 else "✅ OK",
                delta_color="inverse" if pct > 100 else "normal",
            )
        else:
            st.warning("กรุณาเลือกห้องก่อน")

    # ==========================================
    # 🚀 Generate Prompt
    # ==========================================
    if st.button("Generate Prompt for AI", type="primary"):
        if not rooms:
            st.error("กรุณาเลือกห้องอย่างน้อย 1 ห้อง")
        else:
            if mode == "Manual (ผู้ใช้กำหนดเอง)":
                space_areas_payload = [
                    {"room": r, "net_area_sqm": manual_areas.get(r, DEFAULT_AREAS.get(r, 4.0))}
                    for r in rooms
                ]
            else:
                space_areas_payload = "Auto-calculate based on Neufert standards and Thai Building Code"

            ai_prompt = {
                "system_prompt": (
                    "คุณคือสถาปนิกระดับ Senior หน้าที่ของคุณคือวิเคราะห์ Program Definition "
                    "และส่งข้อมูลกลับมาเป็น JSON ตามโครงสร้างที่กำหนดเท่านั้น "
                    "ห้ามมีข้อความเกริ่นนำหรือสรุปท้ายใดๆ"
                ),
                "user_input": {
                    "project": project_type,
                    "site_dimension": f"{width} x {length} m (Total {width * length} sqm)",
                    "required_spaces": rooms,
                    "sizing_mode": mode,
                    "space_areas": space_areas_payload,
                },
                "required_output_schema": {
                    "Space_Requirement": [
                        {"room": "string (ชื่อห้อง)", "net_area_sqm": "float (พื้นที่สุทธิ ตร.ม.)"}
                    ],
                    "Adjacency": [
                        {
                            "room1": "string",
                            "room2": "string",
                            "score": "int (3=ติดกัน/สำคัญมาก, 2=ใกล้กัน, 1=เฉยๆ, -1=ควรอยู่ห่างกัน)",
                            "reason": "string (เหตุผลสั้นๆ)",
                        }
                    ],
                    "Design_Concept": "string (อธิบายแนวความคิดการจัดวางแบบมืออาชีพ)",
                },
            }

            st.success("✅ คัดลอกข้อความด้านล่างนี้ไปวางใน Claude หรือ ChatGPT ได้เลย")
            st.code(json.dumps(ai_prompt, ensure_ascii=False, indent=4), language="json")


# ==========================================
# 📥 TAB 2: Import JSON & Visualize
# ==========================================
with tab2:
    st.header("2. Import AI Result & Generate Final Product")
    st.markdown("นำ JSON ที่ AI ประมวลผลเสร็จแล้วมาวางที่นี่ ระบบจะวาดแปลนและตารางให้อัตโนมัติ")

    # ──────────────────────────────────────────
    # 🔧 Circulation % — user-adjustable
    # ──────────────────────────────────────────
    st.markdown("### ⚙️ ตั้งค่า Circulation Factor")
    circ_col1, circ_col2 = st.columns([1, 3])
    with circ_col1:
        circulation_pct = st.number_input(
            "Circulation (% ของ Net Area)",
            min_value=0,
            max_value=100,
            value=30,
            step=5,
            help="มาตรฐานทั่วไป: 20–30% สำหรับที่พักอาศัย, 30–40% สำหรับอาคารสาธารณะ",
        )
    with circ_col2:
        if circulation_pct < 20:
            st.info(f"ℹ️ {circulation_pct}% — น้อยกว่ามาตรฐาน (อาจแออัด)")
        elif circulation_pct <= 35:
            st.success(f"✅ {circulation_pct}% — อยู่ในช่วงมาตรฐานที่พักอาศัย (20–35%)")
        elif circulation_pct <= 50:
            st.warning(f"⚠️ {circulation_pct}% — สูงกว่าปกติ เหมาะอาคารสาธารณะ/เชิงพาณิชย์")
        else:
            st.error(f"🔴 {circulation_pct}% — สูงมาก ควรตรวจสอบอีกครั้ง")

    circ_factor = circulation_pct / 100.0

    st.divider()

    mock_json = """{
    "Space_Requirement": [
        {"room": "Living Area", "net_area_sqm": 8.0},
        {"room": "Bedroom", "net_area_sqm": 9.0},
        {"room": "Dining", "net_area_sqm": 4.0},
        {"room": "Kitchen", "net_area_sqm": 4.5},
        {"room": "Bathroom", "net_area_sqm": 3.0}
    ],
    "Adjacency": [
        {"room1": "Living Area", "room2": "Dining", "score": 3, "reason": "ใช้งานต่อเนื่องกัน เปิดโล่งได้"},
        {"room1": "Dining", "room2": "Kitchen", "score": 3, "reason": "เสิร์ฟอาหารสะดวก"},
        {"room1": "Living Area", "room2": "Bedroom", "score": 1, "reason": "ต้องการความเป็นส่วนตัว"},
        {"room1": "Bedroom", "room2": "Bathroom", "score": 2, "reason": "ใช้งานสะดวกตอนกลางคืน"},
        {"room1": "Kitchen", "room2": "Bedroom", "score": -1, "reason": "ป้องกันกลิ่นและเสียงรบกวน"}
    ],
    "Design_Concept": "แบ่งพื้นที่ตามลำดับความเป็นส่วนตัว (Public to Private) โดยวาง Living และ Dining ไว้ด้านหน้าเชื่อมต่อกันเพื่อความโปร่ง และแยก Bedroom ไว้ด้านหลังสุดโดยมี Bathroom คั่นกลาง"
}"""

    user_json_input = st.text_area("⬇️ วาง JSON ตรงนี้", value=mock_json, height=250)

    if st.button("Generate Final Product", type="primary"):
        try:
            data = json.loads(user_json_input)

            # --- 1. Space Requirement (+ user-defined Circulation %) ---
            st.subheader("📊 1. Space Requirement (รายการพื้นที่ใช้สอย)")
            df_space = pd.DataFrame(data["Space_Requirement"])
            circ_col_label = f"Circulation_{circulation_pct}%"
            df_space[circ_col_label] = df_space["net_area_sqm"] * circ_factor
            df_space["Gross_Area_sqm"] = df_space["net_area_sqm"] + df_space[circ_col_label]

            st.dataframe(
                df_space.style.format(
                    "{:.2f}", subset=["net_area_sqm", circ_col_label, "Gross_Area_sqm"]
                ),
                use_container_width=True,
            )

            total_net = df_space["net_area_sqm"].sum()
            total_gross = df_space["Gross_Area_sqm"].sum()
            m1, m2, m3 = st.columns(3)
            m1.metric("📐 Total Net Area", f"{total_net:.2f} ตร.ม.")
            m2.metric(f"🚶 Circulation ({circulation_pct}%)", f"{(total_gross - total_net):.2f} ตร.ม.")
            m3.metric("🏗️ Total Gross Area", f"{total_gross:.2f} ตร.ม.")

            st.divider()

            # --- 2. Adjacency Matrix ---
            st.subheader("🧮 2. Adjacency Matrix (ตารางความสัมพันธ์)")
            rooms_list = df_space["room"].tolist()
            matrix = pd.DataFrame(0, index=rooms_list, columns=rooms_list)

            for adj in data["Adjacency"]:
                r1, r2, score = adj["room1"], adj["room2"], adj["score"]
                if r1 in rooms_list and r2 in rooms_list:
                    matrix.at[r1, r2] = score
                    matrix.at[r2, r1] = score

            fig_heat, ax = plt.subplots(figsize=(8, 6))
            sns.heatmap(
                matrix.astype(float),
                annot=True,
                fmt=".0f",
                cmap="RdYlGn",
                center=0,
                vmin=-1,
                vmax=3,
                linewidths=0.5,
                linecolor="#e0e0e0",
                cbar_kws={"label": "Relationship Score"},
                ax=ax,
            )
            ax.set_title("Adjacency Matrix  (3 = ต้องติดกัน  |  -1 = ควรแยกออก)", fontsize=13, pad=12)
            plt.tight_layout()
            st.pyplot(fig_heat)

            st.divider()

            # --- 3. Relationship Diagram (Plotly Network) ---
            st.subheader("🕸️ 3. Relationship Diagram (Network Graph)")

            n = len(rooms_list)
            angles = [2 * math.pi * i / n for i in range(n)]
            pos = {room: (math.cos(a), math.sin(a)) for room, a in zip(rooms_list, angles)}

            EDGE_STYLES = {
                3:  {"color": "#E03434", "width": 5,   "dash": "solid", "label": "Strong (3)"},
                2:  {"color": "#F5A623", "width": 3,   "dash": "solid", "label": "Medium (2)"},
                1:  {"color": "#4A90D9", "width": 1.5, "dash": "dot",   "label": "Weak (1)"},
                -1: {"color": "#888888", "width": 1.5, "dash": "dash",  "label": "Avoid (−1)"},
            }

            fig_net = go.Figure()
            drawn_labels = set()

            for adj in data["Adjacency"]:
                r1, r2, score = adj["room1"], adj["room2"], adj["score"]
                if r1 not in pos or r2 not in pos:
                    continue
                style = EDGE_STYLES.get(score, EDGE_STYLES[1])
                x0, y0 = pos[r1]
                x1, y1 = pos[r2]
                mx, my = (x0 + x1) / 2, (y0 + y1) / 2

                show_legend = style["label"] not in drawn_labels
                drawn_labels.add(style["label"])

                fig_net.add_trace(
                    go.Scatter(
                        x=[mx], y=[my],
                        mode="markers",
                        marker=dict(size=10, color=style["color"], opacity=0),
                        hovertext=f"<b>{r1} ↔ {r2}</b><br>Score: {score}<br>{adj.get('reason', '')}",
                        hoverinfo="text",
                        showlegend=False,
                    )
                )

                fig_net.add_trace(
                    go.Scatter(
                        x=[x0, x1, None],
                        y=[y0, y1, None],
                        mode="lines",
                        line=dict(color=style["color"], width=style["width"], dash=style["dash"]),
                        name=style["label"],
                        legendgroup=style["label"],
                        showlegend=show_legend,
                        hoverinfo="skip",
                    )
                )

            node_x = [pos[r][0] for r in rooms_list]
            node_y = [pos[r][1] for r in rooms_list]
            node_areas = [df_space.loc[df_space["room"] == r, "net_area_sqm"].values[0] for r in rooms_list]
            node_sizes = [max(40, a * 6) for a in node_areas]

            PALETTE = [
                "#4E79A7", "#F28E2B", "#59A14F", "#E15759",
                "#76B7B2", "#EDC948", "#B07AA1", "#FF9DA7",
            ]

            fig_net.add_trace(
                go.Scatter(
                    x=node_x,
                    y=node_y,
                    mode="markers+text",
                    marker=dict(
                        size=node_sizes,
                        color=PALETTE[: len(rooms_list)],
                        line=dict(color="white", width=2),
                        opacity=0.92,
                    ),
                    text=rooms_list,
                    textposition="middle center",
                    textfont=dict(size=11, color="white", family="Arial Black"),
                    hovertext=[
                        f"<b>{r}</b><br>Net Area: {a:.1f} ตร.ม."
                        for r, a in zip(rooms_list, node_areas)
                    ],
                    hoverinfo="text",
                    showlegend=False,
                )
            )

            for r, a, x, y in zip(rooms_list, node_areas, node_x, node_y):
                fig_net.add_annotation(
                    x=x,
                    y=y - 0.18,
                    text=f"{a:.0f} ตร.ม.",
                    showarrow=False,
                    font=dict(size=9, color="#555"),
                )

            fig_net.update_layout(
                height=520,
                margin=dict(l=20, r=20, t=40, b=20),
                plot_bgcolor="#F8F9FA",
                paper_bgcolor="#F8F9FA",
                xaxis=dict(visible=False, range=[-1.6, 1.6]),
                yaxis=dict(visible=False, range=[-1.6, 1.6], scaleanchor="x"),
                title=dict(
                    text="Room Relationship Network  •  hover เส้นเพื่อดูเหตุผล",
                    font=dict(size=14),
                    x=0.5,
                ),
                legend=dict(
                    title="Edge Type",
                    orientation="h",
                    yanchor="bottom",
                    y=-0.05,
                    xanchor="center",
                    x=0.5,
                    font=dict(size=11),
                ),
            )

            st.plotly_chart(fig_net, use_container_width=True)

            leg_col1, leg_col2, leg_col3, leg_col4 = st.columns(4)
            leg_col1.markdown("🔴 **เส้นแดงหนา** = ต้องติดกัน (3)")
            leg_col2.markdown("🟠 **เส้นส้ม** = ควรอยู่ใกล้ (2)")
            leg_col3.markdown("🔵 **เส้นน้ำเงินจุด** = เฉยๆ (1)")
            leg_col4.markdown("⚫ **เส้นเทาขีด** = ควรแยก (−1)")

            st.divider()

            # --- 4. Schematic Block Plan ---
            st.subheader("🟩 4. Schematic Block Plan (Proportional Treemap)")
            st.markdown(
                f"จำลองการจัดก้อน Mass เบื้องต้นตามสัดส่วนพื้นที่จริง (Gross Area รวม Circulation {circulation_pct}%)"
            )

            fig_tree = px.treemap(
                df_space,
                path=[px.Constant("Site Area"), "room"],
                values="Gross_Area_sqm",
                color="room",
                hover_data={"net_area_sqm": True, "Gross_Area_sqm": True},
                color_discrete_sequence=px.colors.qualitative.Pastel,
            )
            fig_tree.update_traces(textinfo="label+value", textfont_size=14)
            fig_tree.update_layout(margin=dict(t=10, l=10, r=10, b=10))
            st.plotly_chart(fig_tree, use_container_width=True)

            st.divider()

            # --- 5. Design Logic ---
            st.subheader("🧠 5. AI Design Logic (แนวคิดการออกแบบ)")
            st.success(data["Design_Concept"])

        except Exception as e:
            st.error(f"❌ รูปแบบ JSON ไม่ถูกต้อง หรือมีบางอย่างผิดพลาด: {e}")
