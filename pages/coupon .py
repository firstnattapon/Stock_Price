import streamlit as st
import pandas as pd
import requests

st.set_page_config(page_title="Generator เลขตอง", page_icon="🎫", layout="wide")

BASE_URL = "https://smart-washer-a830b-default-rtdb.asia-southeast1.firebasedatabase.app/coupons"

# ฟังก์ชันสร้างเฉพาะเลขตอง 11111 - 99999 (9 ใบ)
def create_repdigits_only(value, status):
    data_payload = {}
    current_time = pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # วนลูปเลข 1 ถึง 9 แล้วทำซ้ำ 5 ครั้ง
    generated_list = []
    for i in range(1, 10):
        code = str(i) * 5  # เช่น "1" * 5 = "11111"
        
        data_payload[code] = {
            "status": status,
            "value": value,
            "timestamp": current_time,
            "type": "vip_repdigit" # ระบุประเภทไว้หน่อยว่าเป็นเลขตอง
        }
        generated_list.append(code)

    try:
        # ใช้ PATCH เพื่อส่งข้อมูลทั้ง 9 ตัวขึ้นไปทีเดียว
        response = requests.patch(f"{BASE_URL}.json", json=data_payload)
        response.raise_for_status()
        return True, generated_list
    except Exception as e:
        return False, str(e)

# --- ส่วนหน้าจอใช้งาน ---
st.title("🎫 สร้างคูปองเลขสวย (เลขตอง 5 หลัก)")
st.markdown("---")

st.info("ระบบจะสร้างเลข: 11111, 22222, 33333, 44444, 55555, 66666, 77777, 88888, 99999 (รวม 9 ใบ)")

with st.form("repdigit_form"):
    col1, col2 = st.columns(2)
    with col1:
        val = st.number_input("มูลค่าคูปอง (บาท)", value=500)
    with col2:
        stat = st.selectbox("สถานะ", ["active", "vip", "used"])
        
    submit = st.form_submit_button("🚀 กดปุ่มนี้เพื่อสร้าง 9 ใบ ทีเดียว")
    
    if submit:
        with st.spinner("กำลังส่งข้อมูลเข้า Firebase..."):
            success, result = create_repdigits_only(val, stat)
            
            if success:
                st.success("✅ บันทึกสำเร็จ! สร้างคูปองดังนี้:")
                st.write(result) # แสดงรายการเลขที่สร้าง
                st.balloons() # เอฟเฟกต์ลูกโป่งฉลอง
            else:
                st.error(f"เกิดข้อผิดพลาด: {result}")

# --- ส่วนแสดงผลข้อมูลในระบบ ---
st.markdown("---")
st.subheader("📦 ข้อมูลคูปองล่าสุด")

if st.button("🔄 รีเฟรชดูข้อมูล"):
    st.rerun()

# ดึงข้อมูลมาแสดง (โค้ดแสดงผลมาตรฐาน)
try:
    r = requests.get(f"{BASE_URL}.json")
    data = r.json()
    
    if data:
        # แปลงเป็น DataFrame แบบง่าย
        items = []
        if isinstance(data, dict):
            for k, v in data.items():
                if isinstance(v, dict):
                    v['code'] = k
                    items.append(v)
        
        if items:
            df = pd.DataFrame(items)
            # ย้าย code มาคอลัมน์แรก
            cols = df.columns.tolist()
            if 'code' in cols:
                cols.insert(0, cols.pop(cols.index('code')))
                df = df[cols]
                
            st.dataframe(df, use_container_width=True, hide_index=True)
        else:
            st.warning("รูปแบบข้อมูลไม่ถูกต้อง")
    else:
        st.info("ยังไม่มีข้อมูลในระบบ")
except:
    st.error("เชื่อมต่อฐานข้อมูลไม่ได้")
