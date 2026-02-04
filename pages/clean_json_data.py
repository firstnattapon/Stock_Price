import streamlit as st
import json
import io

# ตั้งค่าหน้าเว็บ
st.set_page_config(page_title="Make Blueprint Minifier", page_icon="✂️")

st.title("✂️ Make (Integromat) Blueprint Minifier")
st.markdown("""
เครื่องมือลดขนาดไฟล์ Blueprint JSON โดยการตัด Metadata ที่ไม่จำเป็นออก (interface, designer, restore) 
เพื่อให้ไฟล์เล็กลงและแชร์ให้ AI หรือเพื่อนร่วมงานได้ง่ายขึ้น
""")

# ฟังก์ชันสำหรับลบ key ที่ไม่จำเป็น (Recursive)
def clean_json_data(obj):
    if isinstance(obj, dict):
        # รายชื่อ key ที่ต้องการลบ
        keys_to_remove = ['interface', 'expect', 'designer', 'restore']
        
        # ลบ key ออกจาก dict ปัจจุบัน
        for key in keys_to_remove:
            if key in obj:
                del obj[key]
        
        # วนลูปเข้าไปจัดการชั้นถัดไป
        for key, value in list(obj.items()):
            clean_json_data(value)
            
    elif isinstance(obj, list):
        # ถ้าเป็น List ให้วนลูปจัดการทุก item
        for item in obj:
            clean_json_data(item)

# ส่วนอัปโหลดไฟล์
uploaded_file = st.file_uploader("อัปโหลดไฟล์ Blueprint (.json)", type=["json"])

if uploaded_file is not None:
    try:
        # 1. อ่านไฟล์ต้นฉบับ
        # อ่าน bytes แล้ว decode เป็น string
        original_content = uploaded_file.getvalue().decode('utf-8')
        original_size = len(original_content)
        
        # แปลงเป็น Python Object
        data = json.loads(original_content)

        # 2. ทำความสะอาดข้อมูล (Clean)
        clean_json_data(data)

        # 3. แปลงกลับเป็น JSON แบบ Minified (ลบช่องว่าง)
        minified_content = json.dumps(data, separators=(',', ':'), ensure_ascii=False)
        minified_size = len(minified_content)

        # คำนวณเปอร์เซ็นต์ที่ลดลง
        reduction = ((original_size - minified_size) / original_size) * 100

        # แสดงผลลัพธ์
        st.success("✅ ลดขนาดไฟล์สำเร็จ!")
        
        col1, col2, col3 = st.columns(3)
        col1.metric("ขนาดเดิม", f"{original_size/1024:.2f} KB")
        col2.metric("ขนาดใหม่", f"{minified_size/1024:.2f} KB")
        col3.metric("ลดลง", f"{reduction:.2f}%")

        # ตั้งชื่อไฟล์ใหม่ (เติม _minified ต่อท้าย)
        original_filename = uploaded_file.name
        new_filename = original_filename.replace(".json", "_minified.json")

        # ปุ่มดาวน์โหลด
        st.download_button(
            label="⬇️ ดาวน์โหลดไฟล์ Minified",
            data=minified_content,
            file_name=new_filename,
            mime="application/json"
        )
        
        # (Optional) แสดงตัวอย่าง JSON บางส่วน
        with st.expander("ดูตัวอย่างเนื้อหาไฟล์ (500 ตัวอักษรแรก)"):
            st.code(minified_content[:500] + "...", language="json")

    except json.JSONDecodeError:
        st.error("❌ ไฟล์ที่อัปโหลดไม่ใช่ JSON ที่ถูกต้อง กรุณาตรวจสอบไฟล์อีกครั้ง")
    except Exception as e:
        st.error(f"❌ เกิดข้อผิดพลาด: {e}")
