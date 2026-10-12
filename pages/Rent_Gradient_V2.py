"""
Rent Gradient v2 — Flowchart ของ pages/Rent_Gradient.py
=======================================================
หน้านี้แสดง flowchart แบบย่อ (pages/Rent_Gradient_flowchart.mmd) พร้อม goal ของ app
ไม่คำนวณหรือเรียก API ใด ๆ — อ่านไฟล์ .mmd แล้ว render ด้วย Mermaid ในเบราว์เซอร์
"""
import html
from pathlib import Path

import streamlit as st

MMD_PATH = Path(__file__).with_name("Rent_Gradient_flowchart.mmd")
MERMAID_JS = "https://cdn.jsdelivr.net/npm/mermaid@10.9.3/dist/mermaid.min.js"
DIAGRAM_HEIGHT_PX = 2300


def _diagram_html(mmd: str) -> str:
    """Self-contained HTML: light panel so Mermaid's default theme stays readable in dark mode."""
    return f"""
<div style="background:#ffffff;border-radius:8px;padding:16px;overflow-x:auto">
  <pre class="mermaid" style="margin:0;display:flex;justify-content:center">{html.escape(mmd, quote=False)}</pre>
</div>
<script src="{MERMAID_JS}"></script>
<script>mermaid.initialize({{startOnLoad: true, securityLevel: "strict", flowchart: {{useMaxWidth: true}}}});</script>
"""


def _show_html(markup: str) -> None:
    """st.iframe on newer Streamlit; components.html (deprecated) on older versions."""
    if hasattr(st, "iframe"):
        st.iframe(markup, height=DIAGRAM_HEIGHT_PX)
    else:
        import streamlit.components.v1 as components

        components.html(markup, height=DIAGRAM_HEIGHT_PX, scrolling=True)


def main() -> None:
    st.set_page_config(page_title="Rent Gradient v2", page_icon="🗺️", layout="wide")
    st.title("🗺️ Rent Gradient v2 — Flowchart")

    st.markdown(
        "**Goal สูงสุดของ app:** หา CBD (anchor) → ประมาณราคาที่ดินตามระยะ "
        "`R(d) = R₀·e^(−λd)` → ชี้ **ที่ดินทอง** คือที่เข้าถึงง่าย "
        "(closeness/degree สูง ทราฟฟิกต่ำ) แต่ราคาคาดการณ์ยังต่ำ (Value Gap สูง)"
    )

    if not MMD_PATH.is_file():
        st.error(f"ไม่พบไฟล์ flowchart: {MMD_PATH.name}")
        return
    mmd = MMD_PATH.read_text(encoding="utf-8")

    c1, c2, c3 = st.columns(3)
    c1.metric("บรรทัด", f"{len(mmd.splitlines())}", "จาก 346")
    c2.metric("ผลลัพธ์ของ app", "ไม่เปลี่ยน")
    c3.download_button("⬇ ดาวน์โหลด .mmd", mmd, MMD_PATH.name, "text/plain")

    _show_html(_diagram_html(mmd))

    with st.expander("ดูโค้ด Mermaid (.mmd)"):
        st.code(mmd, language="text")


main()
