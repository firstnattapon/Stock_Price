import streamlit as st
import paho.mqtt.client as mqtt
import time
import random

# --- ตั้งค่าหน้าเว็บ ---
st.set_page_config(page_title="NETPIE Tester", page_icon="💸")
st.title("💸 NETPIE 2020 Tester: Money In")
st.markdown("เครื่องมือทดสอบยิง MQTT ไปยัง ESP32")

# --- ส่วนกรอกค่า Config (Sidebar) ---
st.sidebar.header("🔐 ตั้งค่า NETPIE")
# แนะนำให้ใช้ Key/Secret ชุดเดียวกับ ESP32 ก็ได้สำหรับการทดสอบ
# แต่ Client ID ควรเปลี่ยนนิดหน่อยเพื่อไม่ให้ชนกัน (ผมเลยสุ่มให้ในโค้ด)
CLIENT_ID_INPUT = st.sidebar.text_input("Client ID (Device ID)", value="")
TOKEN_INPUT     = st.sidebar.text_input("Token (User)", value="", type="password")
SECRET_INPUT    = st.sidebar.text_input("Secret (Password)", value="", type="password")

# --- ส่วนควบคุมการส่งข้อมูล ---
st.divider()
st.subheader("📡 ส่งคำสั่ง (Publish)")

# Topic ต้องตรงกับที่ ESP32 รอรับ
target_topic = "@msg/money_in" 
st.info(f"Target Topic: **{target_topic}**")

# จำลองจำนวนเงิน หรือข้อความที่จะส่ง
message_payload = st.text_input("ข้อความที่จะส่ง (เช่น จำนวนเงิน)", value="10")

if st.button("🚀 ยิงคำสั่ง (Publish)"):
    if not CLIENT_ID_INPUT or not TOKEN_INPUT or not SECRET_INPUT:
        st.error("กรุณากรอกข้อมูล NETPIE ในเมนูด้านซ้ายให้ครบก่อนครับ")
    else:
        # สร้าง Client ID แบบสุ่มต่อท้าย เพื่อป้องกันการชนกับ ESP32 ที่ออนไลน์อยู่
        session_client_id = f"{CLIENT_ID_INPUT}_streamlit_{random.randint(1,999)}"
        
        client = mqtt.Client(client_id=session_client_id)
        client.username_pw_set(TOKEN_INPUT, SECRET_INPUT)
        
        try:
            # เชื่อมต่อ NETPIE
            broker_address = "broker.netpie.io"
            port = 1883
            
            with st.spinner(f"กำลังเชื่อมต่อ NETPIE... ({broker_address})"):
                client.connect(broker_address, port, 60)
                client.loop_start() # เริ่มทำงาน Background thread
                time.sleep(1) # รอการเชื่อมต่อสักครู่
                
                # ทำการส่งข้อมูล (Publish)
                client.publish(target_topic, message_payload)
                
                st.success(f"✅ ส่งข้อมูล '{message_payload}' ไปที่ '{target_topic}' เรียบร้อย!")
                
                time.sleep(1)
                client.loop_stop()
                client.disconnect()
                
        except Exception as e:
            st.error(f"❌ เกิดข้อผิดพลาด: {e}")

st.markdown("---")
st.caption("หมายเหตุ: หาก ESP32 รับได้ ควรจะเห็น Log หรือการทำงานตามที่เขียนไว้")
