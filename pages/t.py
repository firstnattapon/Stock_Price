import streamlit as st
import json
import pandas as pd

# ==========================================
# 1. CORE LOGIC & CALCULATION (รักษาหลักการคำนวณ - Goal 2)
# ==========================================
def calculate_results(params):
    """
    ฟังก์ชันคำนวณหลัก แยกออกมาเพื่อความชัดเจนและ Test ง่าย
    """
    try:
        initial_inv = params.get('initial_investment', 10000)
        growth_rate = params.get('growth_rate', 5.0)
        years = params.get('years', 10)
        
        # Logic การคำนวณ (Compound Interest Example)
        data = []
        current_val = initial_inv
        for i in range(1, years + 1):
            current_val = current_val * (1 + (growth_rate / 100))
            data.append({"Year": i, "Balance": round(current_val, 2)})
            
        return pd.DataFrame(data)
    except Exception as e:
        st.error(f"Calculation Error: {e}")
        return pd.DataFrame()

# ==========================================
# 2. IMPORT / EXPORT HANDLERS (Goal 1)
# ==========================================
def get_current_config():
    """รวบรวมค่าปัจจุบันจาก Session State เพื่อเตรียม Export"""
    config = {
        "initial_investment": st.session_state.get('initial_investment', 10000),
        "growth_rate": st.session_state.get('growth_rate', 5.0),
        "years": st.session_state.get('years', 10),
        "note": st.session_state.get('note', "")
    }
    return config

def load_config(uploaded_file):
    """โหลดค่าจากไฟล์ JSON กลับเข้าสู่ Session State"""
    if uploaded_file is not None:
        try:
            data = json.load(uploaded_file)
            # Update session state ด้วยค่าใหม่
            for key, value in data.items():
                st.session_state[key] = value
            st.success("✅ Configuration Loaded Successfully!")
            st.rerun() # Rerun เพื่อให้ UI อัปเดตค่าทันที
        except Exception as e:
            st.error(f"Error loading file: {e}")

# ==========================================
# 3. UI SETUP (รักษา UI ให้เหมือนเดิม - Goal 2)
# ==========================================
def main():
    st.set_page_config(page_title="Pro Calculation System", layout="wide")
    
    st.title("📊 System Calculation Dashboard")

    # --- Initialize Session State (ถ้ายังไม่มีค่า ให้ตั้งค่า Default) ---
    if 'initial_investment' not in st.session_state: st.session_state['initial_investment'] = 10000
    if 'growth_rate' not in st.session_state: st.session_state['growth_rate'] = 5.0
    if 'years' not in st.session_state: st.session_state['years'] = 10
    if 'note' not in st.session_state: st.session_state['note'] = ""

    # --- System Menu (ส่วนที่เพิ่มมาเพื่อ Import/Export โดยไม่กวน UI หลัก) ---
    with st.expander("📂 System Management (Import / Export)", expanded=False):
        col_ex_1, col_ex_2 = st.columns(2)
        
        # Export Section
        with col_ex_1:
            st.markdown("### Export Configuration")
            config_data = get_current_config()
            json_string = json.dumps(config_data, indent=4)
            st.download_button(
                label="⬇️ Download Config (JSON)",
                data=json_string,
                file_name="system_config.json",
                mime="application/json"
            )
            
        # Import Section
        with col_ex_2:
            st.markdown("### Import Configuration")
            uploaded_file = st.file_uploader("Upload Config File", type=['json'])
            if uploaded_file is not None:
                # ปุ่ม Confirm เพื่อป้องกันการโหลดซ้ำโดยไม่ตั้งใจ
                if st.button("🔄 Load & Apply Config"):
                    load_config(uploaded_file)

    st.markdown("---")

    # --- MAIN INPUT UI (รักษา Layout เดิม) ---
    col1, col2 = st.columns([1, 2])

    with col1:
        st.subheader("⚙️ Parameters")
        # ใช้ key=... เพื่อผูกกับ session_state โดยตรง
        st.number_input("Initial Investment ($)", min_value=0, step=100, key='initial_investment')
        st.slider("Growth Rate (%)", 0.0, 20.0, step=0.1, key='growth_rate')
        st.number_input("Duration (Years)", min_value=1, max_value=50, step=1, key='years')
        st.text_area("Notes / Remarks", key='note')

    # --- OUTPUT DISPLAY (รักษา Output เดิม) ---
    with col2:
        st.subheader("📈 Results Analysis")
        
        # ดึงค่าจาก State มาคำนวณ
        current_params = get_current_config()
        df_result = calculate_results(current_params)

        if not df_result.empty:
            final_val = df_result.iloc[-1]['Balance']
            profit = final_val - current_params['initial_investment']
            
            # Metrics Display
            m1, m2, m3 = st.columns(3)
            m1.metric("Final Balance", f"${final_val:,.2f}")
            m2.metric("Total Profit", f"${profit:,.2f}", delta_color="normal")
            m3.metric("ROI", f"{(profit/current_params['initial_investment'])*100:.2f}%")
            
            # Chart & Table
            st.line_chart(df_result.set_index("Year"))
            with st.expander("View Detailed Data"):
                st.dataframe(df_result, use_container_width=True)

if __name__ == "__main__":
    main()
