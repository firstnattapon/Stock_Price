import streamlit as st
import json
import pandas as pd
import graphviz
import plotly.express as px
import matplotlib.pyplot as plt
import seaborn as sns
import numpy as np

# ==========================================
# ⚙️ Page Setup
# ==========================================
st.set_page_config(page_title="AI Architecture Pipeline", layout="wide", page_icon="🏛️")
st.title("🏛️ AI Architecture: Schematic Design Pipeline")
st.markdown("ระบบแปลงข้อมูล (Program) -> AI Prompt -> Visualized Schematic Design")

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
            ["Bedroom", "Living Area", "Kitchen", "Dining", "Bathroom", "Balcony", "Laundry"],
            default=["Bedroom", "Living Area", "Kitchen", "Dining", "Bathroom"]
        )
        mode = st.radio("รูปแบบการคำนวณพื้นที่ (Sizing Mode)", 
                        ["Auto (คำนวณตามมาตรฐานขั้นต่ำกฎหมาย/Neufert)", "Manual (ผู้ใช้กำหนดเอง)"])

    if st.button("Generate Prompt for AI", type="primary"):
        # สร้าง Prompt โครงสร้างแข็ง (Strict Schema) เพื่อบังคับ AI
        ai_prompt = {
            "system_prompt": "คุณคือสถาปนิกระดับ Senior หน้าที่ของคุณคือวิเคราะห์ Program Definition และส่งข้อมูลกลับมาเป็น JSON ตามโครงสร้างที่กำหนดเท่านั้น ห้ามมีข้อความเกริ่นนำหรือสรุปท้ายใดๆ",
            "user_input": {
                "project": project_type,
                "site_dimension": f"{width} x {length} m (Total {width*length} sqm)",
                "required_spaces": rooms,
                "sizing_mode": mode
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
                        "reason": "string (เหตุผลสั้นๆ)"
                    }
                ],
                "Design_Concept": "string (อธิบายแนวความคิดการจัดวางแบบมืออาชีพ)"
            }
        }
        
        st.success("✅ คัดลอกข้อความด้านล่างนี้ไปวางใน Claude หรือ ChatGPT ได้เลย")
        st.code(json.dumps(ai_prompt, ensure_ascii=False, indent=4), language='json')


# ==========================================
# 📥 TAB 2: Import JSON & Visualize 
# ==========================================
with tab2:
    st.header("2. Import AI Result & Generate Final Product")
    st.markdown("นำ JSON ที่ AI ประมวลผลเสร็จแล้วมาวางที่นี่ ระบบจะวาดแปลนและตารางให้อัตโนมัติ")
    
    # Mockup JSON สำหรับให้ผู้ใช้เทสต์ระบบได้ทันทีโดยไม่ต้องไปหา AI
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
            
            # --- 1. Space Requirement (+30% Circulation) ---
            st.subheader("📊 1. Space Requirement (รายการพื้นที่ใช้สอย)")
            df_space = pd.DataFrame(data["Space_Requirement"])
            df_space["Circulation_30%"] = df_space["net_area_sqm"] * 0.3
            df_space["Gross_Area_sqm"] = df_space["net_area_sqm"] + df_space["Circulation_30%"]
            
            st.dataframe(df_space.style.format("{:.2f}", subset=["net_area_sqm", "Circulation_30%", "Gross_Area_sqm"]), use_container_width=True)
            
            total_net = df_space["net_area_sqm"].sum()
            total_gross = df_space["Gross_Area_sqm"].sum()
            st.info(f"**Total Net Area:** {total_net:.2f} ตร.ม. | **Total Gross Area (รวมสัญจร 30%):** {total_gross:.2f} ตร.ม.")
            
            st.divider()

            # --- 2. Adjacency Matrix ---
            st.subheader("🧮 2. Adjacency Matrix (ตารางความสัมพันธ์)")
            rooms_list = df_space["room"].tolist()
            # สร้าง Matrix เปล่า
            matrix = pd.DataFrame(index=rooms_list, columns=rooms_list)
            matrix.fillna(0, inplace=True)
            
            # เติมค่าจาก JSON
            for adj in data["Adjacency"]:
                r1, r2, score = adj["room1"], adj["room2"], adj["score"]
                if r1 in rooms_list and r2 in rooms_list:
                    matrix.at[r1, r2] = score
                    matrix.at[r2, r1] = score # สะท้อนค่ากลับ (Symmetric)
            
            # วาด Heatmap ด้วย Seaborn
            fig, ax = plt.subplots(figsize=(8, 6))
            sns.heatmap(matrix.astype(float), annot=True, cmap="coolwarm", center=0, cbar_kws={'label': 'Relationship Score'}, ax=ax)
            plt.title("Adjacency Matrix (3=High, -1=Avoid)")
            st.pyplot(fig)

            st.divider()

            # --- 3. Relationship Diagram (Bubble/Graph) ---
            st.subheader("🕸️ 3. Relationship Diagram (Bubble Network)")
            graph = graphviz.Graph(engine="neato") # ใช้ neato เพื่อกระจาย Node อัตโนมัติ
            graph.attr(dpi='150')
            
            for room in rooms_list:
                area = df_space[df_space['room'] == room]['net_area_sqm'].values[0]
                # ยิ่งพื้นที่ใหญ่ วงกลมยิ่งใหญ่ (จำลองคร่าวๆ)
                graph.node(room, f"{room}\n({area} sqm)", shape="circle", style="filled", fillcolor="lightblue", width=str(area/10))
                
            for adj in data["Adjacency"]:
                if adj["score"] == 3:
                    graph.edge(adj["room1"], adj["room2"], color="red", penwidth="3", label="Strong")
                elif adj["score"] == 2:
                    graph.edge(adj["room1"], adj["room2"], color="green", penwidth="2")
                elif adj["score"] == -1:
                    graph.edge(adj["room1"], adj["room2"], color="black", style="dashed", label="Avoid")

            st.graphviz_chart(graph)
            
            st.divider()

            # --- 4. Schematic Block Plan ---
            st.subheader("🟩 4. Schematic Block Plan (Proportional Treemap)")
            st.markdown("จำลองการจัดก้อน Mass เบื้องต้นตามสัดส่วนพื้นที่จริง (ใช้ Treemap แทน Block แปลน)")
            
            # ใช้ Plotly สร้าง Treemap แสดงสัดส่วนพื้นที่
            fig_tree = px.treemap(
                df_space, 
                path=[px.Constant("Site Area"), 'room'], 
                values='Gross_Area_sqm',
                color='room',
                hover_data=['net_area_sqm', 'Gross_Area_sqm']
            )
            fig_tree.update_traces(textinfo="label+value")
            fig_tree.update_layout(margin=dict(t=10, l=10, r=10, b=10))
            st.plotly_chart(fig_tree, use_container_width=True)

            st.divider()
            
            # --- 5. Design Logic ---
            st.subheader("🧠 5. AI Design Logic (แนวคิดการออกแบบ)")
            st.success(data["Design_Concept"])

        except Exception as e:
            st.error(f"❌ รูปแบบ JSON ไม่ถูกต้อง หรือมีบางอย่างผิดพลาด: {e}")
