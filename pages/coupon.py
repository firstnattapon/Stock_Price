import streamlit as st
import pandas as pd
import requests

st.set_page_config(page_title="ระบบจัดการคูปอง", page_icon="🎫", layout="wide")

BASE_URL = "https://smart-washer-a830b-default-rtdb.asia-southeast1.firebasedatabase.app/coupons"

# --- ฟังก์ชันจัดการฐานข้อมูล Firebase ---

# 1. ฟังก์ชันสร้างเฉพาะเลขตอง 11111 - 99999 (9 ใบ)
def create_repdigits_only(value, status):
    data_payload = {}
    current_time = pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S")
    
    generated_list = []
    for i in range(1, 10):
        code = str(i) * 5
        data_payload[code] = {
            "status": status,
            "value": value,
            "timestamp": current_time,
            "type": "vip_repdigit"
        }
        generated_list.append(code)

    try:
        response = requests.patch(f"{BASE_URL}.json", json=data_payload)
        response.raise_for_status()
        return True, generated_list
    except Exception as e:
        return False, str(e)

# 2. ฟังก์ชันเพิ่มคูปองแบบ Manual (เพิ่มระบบเช็คซ้ำ)
def add_manual_coupon(code, value, status):
    # เช็คก่อนว่ามีรหัสนี้ในระบบหรือยัง
    try:
        check_response = requests.get(f"{BASE_URL}/{code}.json")
        check_response.raise_for_status()
        
        # ถ้า Firebase ส่งข้อมูลกลับมา (ไม่ใช่ None) แปลว่ามีรหัสนี้อยู่แล้ว
        if check_response.json() is not None:
            return False, "❌ มีรหัสคูปองนี้ในระบบแล้ว (ไม่สามารถบันทึกทับได้)"
    except Exception as e:
        return False, f"เกิดข้อผิดพลาดในการตรวจสอบข้อมูล: {str(e)}"

    # ถ้าไม่มีข้อมูลซ้ำ ให้ดำเนินการบันทึก
    current_time = pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S")
    data_payload = {
        "status": status,
        "value": value,
        "timestamp": current_time,
        "type": "manual"
    }
    try:
        response = requests.put(f"{BASE_URL}/{code}.json", json=data_payload)
        response.raise_for_status()
        return True, "บันทึกข้อมูลสำเร็จ"
    except Exception as e:
        return False, str(e)

# 3. ฟังก์ชันลบคูปอง (ทีละรายการ)
def delete_coupon(code):
    try:
        response = requests.delete(f"{BASE_URL}/{code}.json")
        response.raise_for_status()
        return True, "ลบข้อมูลสำเร็จ"
    except Exception as e:
        return False, str(e)

# 4. ฟังก์ชันลบข้อมูลคูปองทั้งหมด
def delete_all_coupons():
    try:
        # ลบข้อมูลที่ Node /coupons ทั้งหมด
        response = requests.delete(f"{BASE_URL}.json")
        response.raise_for_status()
        return True, "ล้างข้อมูลคูปองทั้งหมดเรียบร้อยแล้ว"
    except Exception as e:
        return False, str(e)


# --- ส่วนหน้าจอใช้งานหลัก (UI) ---
st.title("🎫 ระบบจัดการคูปอง (Firebase)")
st.markdown("---")

tab1, tab2, tab3 = st.tabs(["🎰 สร้างเลขตอง (Auto)", "➕ เพิ่มคูปองเอง (Manual Add)", "🗑️ ลบคูปอง (Delete)"])

# ----- TAB 1: สร้างเลขตอง -----
with tab1:
    st.info("ระบบจะสร้างเลข: 11111, 22222, 33333, 44444, 55555, 66666, 77777, 88888, 99999 (รวม 9 ใบ)")
    with st.form("repdigit_form"):
        col1, col2 = st.columns(2)
        with col1:
            val_rep = st.number_input("มูลค่าคูปอง (บาท)", value=500, key="val_rep")
        with col2:
            stat_rep = st.selectbox("สถานะ", ["active", "vip", "used"], key="stat_rep")
            
        submit_rep = st.form_submit_button("🚀 กดปุ่มนี้เพื่อสร้าง 9 ใบ ทีเดียว")
        
        if submit_rep:
            with st.spinner("กำลังส่งข้อมูลเข้า Firebase..."):
                success, result = create_repdigits_only(val_rep, stat_rep)
                if success:
                    st.success("✅ บันทึกสำเร็จ! สร้างคูปองดังนี้:")
                    st.write(result)
                    st.balloons()
                else:
                    st.error(f"เกิดข้อผิดพลาด: {result}")

# ----- TAB 2: เพิ่มคูปองแบบ Manual -----
with tab2:
    st.subheader("เพิ่มคูปองแบบกำหนดรหัสเอง")
    with st.form("manual_add_form"):
        code_input = st.text_input("รหัสคูปอง (เช่น PROMO999, NEWYEAR2024)", max_chars=20)
        
        col1, col2 = st.columns(2)
        with col1:
            val_manual = st.number_input("มูลค่าคูปอง (บาท)", value=100, min_value=0, key="val_manual")
        with col2:
            stat_manual = st.selectbox("สถานะ", ["active", "vip", "used"], key="stat_manual")
            
        submit_manual = st.form_submit_button("➕ บันทึกคูปอง")
        
        if submit_manual:
            if not code_input.strip():
                st.warning("⚠️ กรุณากรอกรหัสคูปอง")
            else:
                with st.spinner("กำลังตรวจสอบและบันทึกข้อมูล..."):
                    success, msg = add_manual_coupon(code_input.strip(), val_manual, stat_manual)
                    if success:
                        st.success(f"✅ เพิ่มคูปองรหัส **{code_input}** เรียบร้อยแล้ว!")
                    else:
                        st.error(msg) # แสดง Error ที่ได้จากฟังก์ชัน (เช่น ข้อมูลซ้ำ)

# ----- TAB 3: ลบคูปอง -----
with tab3:
    col_del1, col_del2 = st.columns(2)
    
    # ส่วนที่ 1: ลบทีละรหัส
    with col_del1:
        st.subheader("ลบคูปองทีละรายการ")
        with st.form("delete_form"):
            del_code_input = st.text_input("กรอกรหัสคูปองที่ต้องการลบ")
            submit_delete = st.form_submit_button("🗑️ ยืนยันการลบ") 
            
            if submit_delete:
                if not del_code_input.strip():
                    st.warning("⚠️ กรุณากรอกรหัสคูปองที่ต้องการลบ")
                else:
                    with st.spinner(f"กำลังลบ {del_code_input}..."):
                        success, msg = delete_coupon(del_code_input.strip())
                        if success:
                            st.success(f"✅ ลบคูปองรหัส **{del_code_input}** ออกจากระบบแล้ว!")
                        else:
                            st.error(f"เกิดข้อผิดพลาด: {msg}")

    # ส่วนที่ 2: ลบทั้งหมด (Danger Zone)
    with col_del2:
        st.subheader("🚨 ล้างข้อมูลทั้งหมด")
        with st.form("delete_all_form"):
            st.warning("ระวัง! การกดปุ่มนี้จะลบข้อมูลคูปอง 'ทั้งหมด' ไม่สามารถกู้คืนได้")
            confirm_delete_all = st.checkbox("ฉันเข้าใจและยืนยันที่จะลบข้อมูลทั้งหมด")
            submit_delete_all = st.form_submit_button("💥 ลบข้อมูลทั้งหมด", type="primary")
            
            if submit_delete_all:
                if confirm_delete_all:
                    with st.spinner("กำลังล้างข้อมูลทั้งหมด..."):
                        success, msg = delete_all_coupons()
                        if success:
                            st.success(f"✅ {msg}")
                        else:
                            st.error(f"เกิดข้อผิดพลาด: {msg}")
                else:
                    st.error("⚠️ กรุณาติ๊กถูกที่ช่อง 'ฉันเข้าใจและยืนยัน' ก่อนทำการลบทั้งหมด")

# --- ส่วนแสดงผลข้อมูลในระบบ ---
st.markdown("---")
col_header1, col_header2 = st.columns([4, 1])
with col_header1:
    st.subheader("📦 ข้อมูลคูปองล่าสุดในระบบ")
with col_header2:
    if st.button("🔄 รีเฟรชข้อมูล", use_container_width=True):
        st.rerun()

# ดึงข้อมูลมาแสดง
try:
    r = requests.get(f"{BASE_URL}.json")
    data = r.json()
    
    if data:
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
    st.error("เชื่อมต่อฐานข้อมูลไม่ได้ โปรดตรวจสอบอินเทอร์เน็ตหรือ URL ของ Firebase")
