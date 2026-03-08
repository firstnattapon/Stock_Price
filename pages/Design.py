import streamlit as st
import json
import pandas as pd
import networkx as nx
import matplotlib.pyplot as plt

st.set_page_config(page_title="AI Architecture Planner", layout="wide")

st.title("AI Architectural Layout Generator")

st.markdown("Program → AI → Layout Visualization")

# -----------------------------
# USER INPUT
# -----------------------------

st.sidebar.header("Project Input")

width = st.sidebar.number_input("Site Width (m)", value=8)
depth = st.sidebar.number_input("Site Depth (m)", value=4)

mode = st.sidebar.selectbox(
    "Size Mode",
    ["auto_minimum_required", "manual"]
)

spaces = st.sidebar.multiselect(
    "Program Spaces",
    ["Bedroom","Living Area","Kitchen","Dining","Bathroom"],
    default=["Bedroom","Living Area","Kitchen","Dining","Bathroom"]
)

circulation = st.sidebar.slider(
    "Circulation Ratio",
    0.1,0.5,0.30
)

# -----------------------------
# PROGRAM JSON GENERATOR
# -----------------------------

program_json = {
    "framework":"AI Architectural Design Engine",
    "site":{
        "width":width,
        "depth":depth,
        "area":width*depth
    },
    "mode":{
        "size_mode":mode,
        "circulation_ratio":circulation
    },
    "program_definition":spaces,
    "goal":[
        "space_requirement",
        "adjacency_matrix",
        "relationship_diagram",
        "bubble_diagram",
        "schematic_block_plan"
    ]
}

st.header("Program JSON")

st.json(program_json)

# -----------------------------
# EXPORT PROMPT
# -----------------------------

st.header("Prompt JSON (Copy to AI)")

prompt = f"""
You are a professional architect.

Use the following program definition and generate architectural planning outputs.

Return JSON only.

Required outputs:

1 space_requirement
2 adjacency_matrix
3 spatial_network
4 bubble_diagram_coordinates
5 schematic_layout

Program Definition:

{json.dumps(program_json,indent=2)}
"""

st.code(prompt,language="json")

# -----------------------------
# IMPORT AI RESULT
# -----------------------------

st.header("Paste AI JSON Result")

user_json = st.text_area("Paste JSON here")

if user_json:

    try:

        data = json.loads(user_json)

        st.success("JSON loaded")

        # --------------------------------
        # SPACE REQUIREMENT
        # --------------------------------

        st.subheader("Space Requirement")

        space_df = pd.DataFrame(
            data["space_requirement"].items(),
            columns=["Space","Area sqm"]
        )

        st.dataframe(space_df)

        # --------------------------------
        # ADJACENCY MATRIX
        # --------------------------------

        st.subheader("Adjacency Matrix")

        adj = data["adjacency_matrix"]

        # แก้ไขบรรทัดนี้เพื่อรองรับจำนวน Array ที่ไม่เท่ากัน
        matrix = pd.DataFrame.from_dict(adj, orient='index').fillna("")

        st.dataframe(matrix)

        # --------------------------------
        # RELATIONSHIP GRAPH
        # --------------------------------

        st.subheader("Relationship Diagram")

        G = nx.Graph()

        for k,v in adj.items():
            for i in v:
                G.add_edge(k,i)

        fig,ax = plt.subplots()

        pos = nx.spring_layout(G)

        nx.draw(G,pos,with_labels=True,node_size=3000,font_size=10)

        st.pyplot(fig)

        # --------------------------------
        # BUBBLE DIAGRAM
        # --------------------------------

        st.subheader("Bubble Diagram")

        bubbles = data["bubble_diagram_coordinates"]

        fig,ax = plt.subplots()

        for b in bubbles:

            circle = plt.Circle(
                (b["x"],b["y"]),
                b["r"],
                fill=False
            )

            ax.add_patch(circle)

            ax.text(
                b["x"],
                b["y"],
                b["space"],
                ha="center"
            )

        ax.set_aspect("equal")
        st.pyplot(fig)

        # --------------------------------
        # SCHEMATIC BLOCK PLAN
        # --------------------------------

        st.subheader("Schematic Block Plan")

        blocks = data["schematic_layout"]

        fig,ax = plt.subplots()

        for b in blocks:

            rect = plt.Rectangle(
                (b["x"],b["y"]),
                b["w"],
                b["h"],
                fill=False
            )

            ax.add_patch(rect)

            ax.text(
                b["x"]+b["w"]/2,
                b["y"]+b["h"]/2,
                b["space"],
                ha="center",
                va="center"
            )

        ax.set_xlim(0,width)
        ax.set_ylim(0,depth)

        ax.set_aspect("equal")

        st.pyplot(fig)

    except json.JSONDecodeError:
        st.error("Invalid JSON Format: โปรดตรวจสอบ Syntax ของ JSON อีกครั้ง")
    except Exception as e:
        st.error(f"Processing Error: เกิดข้อผิดพลาดในการสร้างกราฟิก - {e}")
