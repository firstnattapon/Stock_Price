import streamlit as st
import pandas as pd
import requests
import json

# 1. ตั้งค่าหน้าเว็บ
st.set_page_config(
    page_title="Dashboard คูปองคงเหลือ",
    page_icon="🎫",
    layout="wide"
)

# URL ของ Firebase (ตัด .json ออกเพื่อนำไปต่อท้ายในฟังก์ชัน)
BASE_URL = "https://smart-washer-a830b-default-rtdb.asia-southeast1.firebasedatabase.app/coupons"

# 2. ฟังก์ชันสำหรับดึงข้อมูล (Read)
def load_data():
    try:
        response = requests.get(f"{BASE_URL}.json")
        response.raise_for_status()
        data = response.json()
        return data
    except Exception as e:
        st.error(f"เกิดข้อผิดพลาดในการดึงข้อมูล: {e}")
        return None

# 3. ฟังก์ชันสำหรับเพิ่มข้อมูล (Create/Update)
def add_coupon(coupon_id, status, value=None):
    # สร้าง URL สำหรับ node นั้นๆ โดยเฉพาะ เช่น /coupons/11111.json
    url = f"{BASE_URL}/{coupon_id}.json"
    
    # ข้อมูลที่จะส่งขึ้นไป
    payload = {
        "status": status,
        "value": value,
        "timestamp": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    
    try:
        # ใช้ PUT เพื่อระบุ ID เอง (ถ้าใช้ POST Firebase จะสุ่ม ID ยาวๆ ให้)
        response = requests.put(url, json=payload)
        response.raise_for_status()
        return True
    except Exception as e:
        st.error(f"บันทึกไม่สำเร็จ: {e}")
        return False

# --- ส่วนแสดงผลหลัก (Main Interface) ---
st.title("🎫 ระบบตรวจสอบและจัดการคูปอง (Smart Washer)")
st.markdown("---")

# ==========================================
# ส่วนที่เพิ่ม: Sidebar สำหรับเพิ่มข้อมูล (Add Data)
# ==========================================
with st.sidebar:
    st.header("➕ เพิ่ม/แก้ไข คูปอง")
    
    with st.form("add_coupon_form"):
        # กำหนดช่วงเลขคูปอง 11111 - 99999 ตามที่ต้องการ
        new_id = st.number_input(
            "ระบุเลขคูปอง (5 หลัก)", 
            min_value=11111, 
            max_value=99999, 
            step=1,
            help="ใส่เลขระหว่าง 11111 ถึง 99999"
        )
        
        new_status = st.selectbox("สถานะ", ["active", "used", "expired"])
        new_value = st.number_input("มูลค่า (บาท)", min_value=0, value=100)
        
        submitted = st.form_submit_button("บันทึกข้อมูล")
        
        if submitted:
            if 11111 <= new_id <= 99999:
                success = add_coupon(new_id, new_status, new_value)
                if success:
                    st.success(f"บันทึกคูปอง {new_id} เรียบร้อย!")
                    st.cache_data.clear() # เคลียร์ cache
                    # ใช้ rerun เพื่อรีเฟรชตารางข้อมูลทันที
                    st.rerun()
            else:
                st.error("กรุณาระบุเลขคูปองให้ถูกต้อง (11111-99999)")

# ==========================================
# ส่วนแสดงผลข้อมูลเดิม (View Data)
# ==========================================

# ปุ่ม Refresh
if st.button("🔄 อัปเดตตารางข้อมูล"):
    st.cache_data.clear()
    st.rerun()

# โหลดข้อมูล
data = load_data()

if data:
    # การแปลงข้อมูล (เหมือนโค้ดเดิมของคุณ)
    if isinstance(data, dict):
        items = []
        for key, value in data.items():
            if isinstance(value, dict):
                value['coupon_code'] = key # เปลี่ยนชื่อ key ให้อ่านง่าย
                items.append(value)
            else:
                items.append({'coupon_code': key, 'value': value})
        df = pd.DataFrame(items)
        
    elif isinstance(data, list):
        # กรณี List ต้องจัดการ index ให้ตรงกับเลขคูปองถ้าเป็นไปได้
        # หรือถ้า Firebase เก็บเป็น array ที่มีค่า null เยอะๆ อาจจะต้อง clean
        items = []
        for i, val in enumerate(data):
            if val is not None:
                if isinstance(val, dict):
                    val['coupon_code'] = i
                    items.append(val)
                else:
                    items.append({'coupon_code': i, 'value': val})
        df = pd.DataFrame(items)
    else:
        df = pd.DataFrame()

    if not df.empty:
        # ย้าย coupon_code มาคอลัมน์แรก
        if 'coupon_code' in df.columns:
            cols = df.columns.tolist()
            cols.insert(0, cols.pop(cols.index('coupon_code')))
            df = df[cols]
            
            # ทำให้เป็น string เพื่อไม่ให้แสดง comma (เช่น 11,111)
            df['coupon_code'] = df['coupon_code'].astype(str) 

        # Metric
        c1, c2, c3 = st.columns(3)
        with c1:
            st.metric("จำนวนคูปองทั้งหมด", f"{len(df)} ใบ")
        with c2:
            # นับเฉพาะ Active
            if 'status' in df.columns:
                active_count = len(df[df['status'] == 'active'])
                st.metric("สถานะ Active", f"{active_count} ใบ")
            else:
                st.metric("สถานะ Active", "-")

        st.subheader("📋 รายการคูปอง")
        st.dataframe(
            df, 
            use_container_width=True,
            hide_index=True
        )
    else:
        st.info("ไม่พบข้อมูลคูปอง")
else:
    st.info("ยังไม่มีข้อมูลในฐานข้อมูล")
