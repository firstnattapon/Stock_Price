import streamlit as st
import mpy_cross
import subprocess
import os
import tempfile
import shutil

st.set_page_config(page_title="MPY Converter", page_icon="⚡")

st.title("⚡ Python (.py) to MicroPython (.mpy)")
st.caption("Simple converter using mpy-cross")

# --- Sidebar: คำแนะนำ ---
with st.sidebar:
    st.header("📌 คำแนะนำ")
    st.markdown("""
    1. **เช็คเวอร์ชัน:** ตรวจสอบว่าบอร์ด MicroPython ของคุณรองรับ `.mpy` เวอร์ชันไหน
       (แอพนี้ใช้ `mpy-cross` เวอร์ชันล่าสุดที่ติดตั้งใน requirements.txt)
    2. **การใช้งาน:** อัปโหลดไฟล์ `.py` แล้วกดแปลง ระบบจะให้ดาวน์โหลดไฟล์ `.mpy` ทันที
    3. **ความปลอดภัย:** ไฟล์จะถูกลบทันทีหลังการประมวลผล
    """)
    
    # แสดงเวอร์ชัน mpy-cross ที่กำลังรันอยู่
    try:
        version_check = subprocess.run([mpy_cross.mpy_cross, "--version"], capture_output=True, text=True)
        st.info(f"Current mpy-cross version:\n{version_check.stdout}")
    except Exception as e:
        st.error(f"Error checking version: {e}")

# --- Main App ---

uploaded_file = st.file_uploader("อัปโหลดไฟล์ Python (.py)", type=["py"])

if uploaded_file is not None:
    # สร้างปุ่มกดเพื่อเริ่มแปลง
    if st.button("แปลงเป็น .mpy", type="primary"):
        
        # สร้าง Temporary Directory เพื่อความสะอาดและปลอดภัย
        with tempfile.TemporaryDirectory() as tmpdirname:
            
            # 1. บันทึกไฟล์ที่อัปโหลดลง Temp
            input_path = os.path.join(tmpdirname, uploaded_file.name)
            with open(input_path, "wb") as f:
                f.write(uploaded_file.getbuffer())
            
            # 2. เตรียมคำสั่ง mpy-cross
            # โดยปกติ output จะชื่อเดียวกับ input แต่เปลี่ยนนามสกุล
            output_filename = os.path.splitext(uploaded_file.name)[0] + ".mpy"
            output_path = os.path.join(tmpdirname, output_filename)
            
            # 3. รันคำสั่งแปลงไฟล์
            # เรียกใช้ binary ของ mpy-cross ผ่าน package mpy_cross โดยตรง
            cmd = [mpy_cross.mpy_cross, input_path]
            
            try:
                result = subprocess.run(cmd, capture_output=True, text=True)
                
                if result.returncode == 0:
                    st.success(f"✅ แปลงไฟล์สำเร็จ: {output_filename}")
                    
                    # 4. อ่านไฟล์ผลลัพธ์เพื่อเตรียมให้ดาวน์โหลด
                    with open(output_path, "rb") as f:
                        mpy_data = f.read()
                        
                    st.download_button(
                        label="⬇️ ดาวน์โหลดไฟล์ .mpy",
                        data=mpy_data,
                        file_name=output_filename,
                        mime="application/octet-stream"
                    )
                    
                else:
                    st.error("❌ เกิดข้อผิดพลาดในการแปลงไฟล์")
                    st.code(result.stderr) # แสดง Error จาก mpy-cross
                    
            except Exception as e:
                st.error(f"An error occurred: {e}")

    st.warning("⚠️ หมายเหตุ: ไฟล์ .mpy ต้องใช้กับ MicroPython เวอร์ชันที่ตรงกัน (Major/Minor version) มิฉะนั้นจะเกิด Error 'incompatible .mpy file' บนบอร์ด")

else:
    st.info("กรุณาอัปโหลดไฟล์ .py เพื่อเริ่มต้น")
