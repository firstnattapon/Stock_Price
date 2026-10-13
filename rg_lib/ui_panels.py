"""UI — header, metrics row and the analytics tabs under the map.

Definitions are cut verbatim from pages/Rent_Gradient.py (see tests/test_rg_v2_equivalence.py).
"""


import pandas as pd
import streamlit as st
from typing import Any, Dict, List, Optional

from .config import CHART_COLOR_CURVE, CHART_COLOR_MUTED, CHART_COLOR_SAMPLES
from .geo import approx_geom_area_km2, haversine_km
from .rent import build_ring_report, fit_interval_text, fit_quality_label, fit_quality_warning, format_rent_value, predict_rent
from .state import StateManager


def render_header() -> None:
    """หัวเรื่อง + สรุปหลักการของหน้าแบบย่อ."""
    st.markdown("#### 💹 Rent Gradient — Bid-Rent CBD Analysis")
    st.caption(
        "① เริ่มใกล้ศูนย์กลางประชากร → ② Isochrone 20 นาทีหา C20 → "
        "③ Isochrone 5 นาทีหา C5 → ④ Golden Spots → ⑤ Rent Gradient"
    )


def render_metrics_row() -> None:
    """แถวตัวชี้วัดสรุปเหนือแผนที่."""
    active_n = len(StateManager.get_active_markers())
    inter_data = StateManager.get_intersection_data()
    net_data = StateManager.get_network_data()
    rent_data = StateManager.get_rent_data()

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("📍 หมุด Active", active_n)

    cbd_txt = "—"
    if inter_data:
        feats = inter_data.get("features") or []
        area = approx_geom_area_km2(feats[0]["geometry"]) if feats else None
        cbd_txt = f"{area:.2f} km²" if area is not None else "พบแล้ว"
    c2.metric("🎯 CBD Zone", cbd_txt)

    net_txt = "—"
    if net_data and "error" not in net_data:
        stats = net_data.get("stats", {})
        net_txt = f"{stats.get('nodes_count', 0):,} โหนด"
    c3.metric("🕸️ Network", net_txt)

    lam_txt, half_txt = "—", "—"
    if rent_data and "error" not in rent_data:
        model = rent_data["model"]
        lam_txt = f"{model['lam']:.4f}/km"
        half = model.get("half_dist_km")
        half_txt = f"{half:.2f} km" if half else "∞"
    c4.metric("📉 λ (Rent Gradient)", lam_txt)
    c5.metric("½ ราคา ที่ระยะ", half_txt)


def _build_bid_rent_figure(rent_data: Dict[str, Any]):
    """สร้างกราฟ Bid-Rent Curve (plotly) — โมเดล + จุดตัวอย่างจริง + เส้น d½."""
    import plotly.graph_objects as go  # lazy import — โหลดเมื่อใช้จริงเท่านั้น

    model = rent_data["model"]
    curve = rent_data["curve"]
    unit_text = "ดัชนีค่าเช่า (0–100)" if model["is_index"] else model["unit"]

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=curve["d"],
            y=curve["r"],
            mode="lines",
            name="Bid-Rent Curve (โมเดล)",
            line=dict(color=CHART_COLOR_CURVE, width=2.5),
            hovertemplate="ระยะ %{x:.2f} km<br>ค่าเช่า %{y:,.1f}<extra></extra>",
        )
    )

    scatter = rent_data.get("samples_scatter") or []
    if scatter:
        fig.add_trace(
            go.Scatter(
                x=[p["d"] for p in scatter],
                y=[p["rent"] for p in scatter],
                mode="markers",
                name="ตัวอย่างราคาจริง",
                marker=dict(
                    color=CHART_COLOR_SAMPLES,
                    size=10,
                    line=dict(color="#ffffff", width=1.5),
                ),
                hovertemplate="ระยะ %{x:.2f} km<br>ราคาจริง %{y:,.1f}<extra></extra>",
            )
        )

    half = model.get("half_dist_km")
    if half and half <= model["d_max_km"]:
        fig.add_vline(
            x=half,
            line_dash="dash",
            line_color=CHART_COLOR_MUTED,
            annotation_text=f"d½ = {half:.2f} km",
            annotation_font_color=CHART_COLOR_MUTED,
        )

    fig.update_layout(
        height=380,
        margin=dict(l=10, r=10, t=30, b=10),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
        xaxis=dict(
            title="ระยะทางจาก CBD (km)",
            gridcolor="rgba(137,135,129,0.25)",
            zeroline=False,
        ),
        yaxis=dict(
            title=unit_text,
            gridcolor="rgba(137,135,129,0.25)",
            zeroline=False,
            rangemode="tozero",
        ),
        font=dict(size=13),
    )
    return fig


def _build_golden_spots_df(
    golden_spots: List[Dict[str, Any]],
    rent_data: Optional[Dict[str, Any]],
) -> pd.DataFrame:
    """ตาราง Golden Spots — เสริมระยะจาก CBD, ราคาประเมิน และ Value Gap."""
    has_rent = bool(rent_data and "error" not in rent_data)
    rows = []
    for i, s in enumerate(golden_spots, start=1):
        row: Dict[str, Any] = {
            "อันดับ": i,
            "Score": round(s["score"], 4),
            "Lat": round(s["lat"], 5),
            "Lon": round(s["lon"], 5),
            "Closeness": round(s.get("closeness_norm", 0.0), 3),
            "Degree": round(s.get("degree_norm", 0.0), 3),
        }
        if has_rent:
            model = rent_data["model"]
            anchor = rent_data["anchor"]
            d_km = haversine_km(anchor["lat"], anchor["lon"], s["lat"], s["lon"])
            est = predict_rent(d_km, model["r0"], model["lam"])
            rent_norm = max(0.0, min(1.0, est / model["r0"])) if model["r0"] else 0.0
            row["ระยะจาก CBD (km)"] = round(d_km, 2)
            row["ค่าเช่าคาดการณ์"] = round(est, 1)
            # Value Gap: เข้าถึงง่าย (closeness สูง) แต่ราคายังต่ำ = โอกาส
            # ซ่อนในโหมดดัชนี: R(d)/R0 เป็นค่าสมมติ gap จึงสะท้อนสมมติฐานเอง
            if not model.get("is_index"):
                row["Value Gap"] = round(s.get("closeness_norm", 0.0) - rent_norm, 3)
        rows.append(row)
    return pd.DataFrame(rows)


def render_analytics_panel() -> None:
    """แท็บวิเคราะห์ใต้แผนที่: Bid-Rent Curve / Golden Spots / หมุด / หลักการ."""
    rent_data = StateManager.get_rent_data()
    net_data = StateManager.get_network_data()
    has_rent = bool(rent_data and "error" not in rent_data)
    golden_spots = (net_data or {}).get("golden_spots") if net_data else None
    locked = st.session_state.get(StateManager.K_UI_LOCKED, False)

    tab_curve, tab_rings, tab_gold, tab_marks, tab_theory = st.tabs(
        [
            "📈 Bid-Rent Curve",
            "🧾 Ring Report",
            "💎 Golden Spots",
            "📍 หมุด & ราคาประเมิน",
            "📐 หลักการ",
        ]
    )

    with tab_curve:
        if has_rent:
            model = rent_data["model"]
            st.plotly_chart(
                _build_bid_rent_figure(rent_data),
                use_container_width=True,
                config={"displayModeBar": False},
            )
            eq_r0 = f"{model['r0']:,.1f}" if not model["is_index"] else f"{model['r0']:.0f}"
            fit_txt = f" — {fit_quality_label(model)}"
            interval = fit_interval_text(model)
            if interval:
                fit_txt += f" · {interval}"
            st.caption(
                f"R(d) = {eq_r0} × e^(−{model['lam']:.4f}·d)"
                + fit_txt
            )
            quality_warning = fit_quality_warning(model)
            if quality_warning:
                st.warning(quality_warning, icon="📉")
        else:
            st.info("กด **🧮 คำนวณ Rent Gradient** ใน sidebar เพื่อสร้างเส้นโค้ง Bid-Rent", icon="💡")

    with tab_rings:
        if has_rent:
            ring_rows = build_ring_report(
                rent_data, net_data, StateManager.get_rent_samples()
            )
            has_net_cols = bool(net_data and "error" not in net_data and net_data.get("nodes", {}).get("features"))
            df_rings = pd.DataFrame(ring_rows)
            st.dataframe(df_rings, use_container_width=True, hide_index=True)

            csv_bytes = df_rings.to_csv(index=False).encode("utf-8-sig")
            st.download_button(
                "⬇ ดาวน์โหลด CSV",
                csv_bytes,
                "ring_report.csv",
                "text/csv",
            )

            if not has_net_cols:
                st.info(
                    "รัน **🚀 Network Analysis** เพื่อเติมจำนวนโหนด, Closeness "
                    "และ Value Gap รายวง",
                    icon="💡",
                )
            if rent_data["model"].get("is_index"):
                st.caption(
                    "**โหนด/km²** = ความหนาแน่นของโครงข่ายถนน หารด้วยพื้นที่ของวงที่มีข้อมูลถนนจริง · "
                    "**Closeness เฉลี่ย** = ความเข้าถึงง่ายเฉลี่ยของโหนดในวง · "
                    "**Value Gap ถูกซ่อน** ในโหมดดัชนี เพราะ R(d)/R₀ เป็นค่าสมมติ "
                    "(ลดเหลือ ¼ ที่ขอบ) — ใส่ตัวอย่างราคาจริงเพื่อ calibrate ก่อน"
                )
            else:
                st.caption(
                    "**โหนด/km²** = ความหนาแน่นของโครงข่ายถนน หารด้วยพื้นที่ของวงที่มีข้อมูลถนนจริง · "
                    "**Closeness เฉลี่ย** = ความเข้าถึงง่ายเฉลี่ยของโหนดในวง · "
                    "**Value Gap** = Closeness เฉลี่ย − (ค่าเช่าคาดการณ์/R₀) — "
                    "วงที่ Value Gap สูงคือวงที่โครงข่ายเข้าถึงดีแต่ราคาคาดการณ์ยังต่ำ "
                    "(ตัวชี้นำเชิงเปรียบเทียบ ไม่ใช่ราคาผิดปกติที่พิสูจน์แล้ว)"
                )
        else:
            st.info("กด **🧮 คำนวณ Rent Gradient** ใน sidebar เพื่อสร้างรายงานรายวง", icon="💡")

    with tab_gold:
        if golden_spots:
            df_gold = _build_golden_spots_df(golden_spots, rent_data)
            st.dataframe(df_gold, use_container_width=True, hide_index=True)
            if has_rent:
                if rent_data["model"].get("is_index"):
                    st.caption(
                        "Value Gap ถูกซ่อนในโหมดดัชนี (R(d)/R₀ เป็นค่าสมมติ) — "
                        "ใส่ตัวอย่างราคาจริงเพื่อ calibrate"
                    )
                else:
                    st.caption(
                        "**Value Gap** = Closeness − (ค่าเช่าคาดการณ์/R₀) — "
                        "ค่าบวกมาก = เข้าถึงง่ายแต่ราคายังต่ำ (ตัวชี้นำเชิงเปรียบเทียบ)"
                    )

            c1, c2, _sp = st.columns([0.3, 0.3, 0.4])
            csv_bytes = df_gold.to_csv(index=False).encode("utf-8-sig")
            c1.download_button(
                "⬇ ดาวน์โหลด CSV",
                csv_bytes,
                "golden_spots.csv",
                "text/csv",
                use_container_width=True,
            )
            rank = c2.selectbox(
                "เพิ่มอันดับลงแผนที่",
                list(range(1, len(golden_spots) + 1)),
                label_visibility="collapsed",
                format_func=lambda r: f"➕ เพิ่มอันดับ {r} ลงแผนที่",
            )
            if c2.button("ยืนยันเพิ่มหมุด", use_container_width=True, disabled=locked):
                spot = golden_spots[rank - 1]
                StateManager.add_marker(spot["lat"], spot["lon"])
                StateManager.clear_results(["isochrone", "intersection", "rent"])
                st.toast(f"เพิ่ม Golden Spot อันดับ {rank} แล้ว! กรุณากดคำนวณใหม่", icon="💎")
                st.rerun()
        else:
            st.info("รัน **🚀 Network Analysis** เพื่อค้นหาทำเลที่ดินทอง", icon="💡")

    with tab_marks:
        markers = StateManager.get_markers()
        if markers:
            rows = []
            for i, mk in enumerate(markers, start=1):
                row: Dict[str, Any] = {
                    "จุดที่": i,
                    "สถานะ": "✅ Active" if mk.get("active", True) else "⏸ ปิด",
                    "Lat": round(mk["lat"], 5),
                    "Lon": round(mk["lng"], 5),
                }
                if has_rent:
                    model = rent_data["model"]
                    anchor = rent_data["anchor"]
                    d_km = haversine_km(anchor["lat"], anchor["lon"], mk["lat"], mk["lng"])
                    row["ระยะจาก CBD (km)"] = round(d_km, 2)
                    row["ค่าเช่าคาดการณ์"] = format_rent_value(
                        predict_rent(d_km, model["r0"], model["lam"]), model
                    )
                rows.append(row)
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
            if not has_rent:
                st.caption("คำนวณ Rent Gradient เพื่อดูราคาประเมินของแต่ละหมุด")
        else:
            st.info("ยังไม่มีหมุด — คลิกบนแผนที่หรือกรอกพิกัดใน sidebar", icon="📍")

    with tab_theory:
        st.html(
            """
<style>
.rg-guide {
    max-width: 920px;
    margin: 0 auto;
    color: #edf7f4;
    font-family: inherit;
}
.rg-guide * { box-sizing: border-box; }
.rg-guide .principle {
    padding: 20px 22px;
    border: 1px solid rgba(83, 214, 162, .38);
    border-radius: 16px;
    background: linear-gradient(135deg, rgba(83, 214, 162, .13), #101c27);
}
.rg-guide .label {
    margin-bottom: 5px;
    color: #53d6a2;
    font-size: .76rem;
    font-weight: 900;
    letter-spacing: .08em;
}
.rg-guide h3 {
    margin: 0 0 7px;
    color: #ffffff;
    font-size: clamp(1.15rem, 2.6vw, 1.55rem);
}
.rg-guide p { margin: 0; color: #b6c9cd; line-height: 1.65; }
.rg-guide code {
    padding: 2px 6px;
    border-radius: 6px;
    color: #dffff3;
    background: rgba(83, 214, 162, .12);
}
.rg-guide .flow-title {
    margin: 22px 0 11px;
    color: #ffffff;
    font-size: 1.05rem;
    font-weight: 850;
}
.rg-guide .flow {
    display: grid;
    gap: 9px;
}
.rg-guide .step {
    display: grid;
    grid-template-columns: 38px 1fr;
    gap: 12px;
    align-items: start;
    padding: 13px 15px;
    border: 1px solid #29404e;
    border-radius: 13px;
    background: #101c27;
}
.rg-guide .number {
    display: grid;
    width: 34px;
    height: 34px;
    place-items: center;
    border-radius: 10px;
    color: #05251b;
    background: #53d6a2;
    font-weight: 950;
}
.rg-guide .step b {
    display: block;
    margin-bottom: 2px;
    color: #ffffff;
}
.rg-guide .step span {
    color: #9fb4ba;
    font-size: .88rem;
    line-height: 1.55;
}
.rg-guide .notes {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 9px;
    margin-top: 12px;
}
.rg-guide .note {
    padding: 13px 14px;
    border: 1px solid #29404e;
    border-radius: 12px;
    color: #adbec2;
    background: rgba(16, 28, 39, .72);
    font-size: .84rem;
}
.rg-guide .note b {
    display: block;
    margin-bottom: 3px;
    color: #ffcb6b;
}
.rg-guide .formula {
    margin-top: 12px;
    padding: 14px 16px;
    border-left: 4px solid #67b8ff;
    border-radius: 0 12px 12px 0;
    color: #c7d9dc;
    background: rgba(103, 184, 255, .08);
    font-size: .88rem;
}
.rg-guide .formula b { color: #8dccff; }
@media (max-width: 680px) {
    .rg-guide .notes { grid-template-columns: 1fr; }
}
</style>

<div class="rg-guide">
    <div class="principle">
        <div class="label">หลักการเลือกหมุดเริ่มต้น</div>
        <h3>หมุดเริ่มต้น = โหนดถนนที่ใกล้ “จุดกึ่งกลางประชากร” มากที่สุด</h3>
        <p>
            หมุดนี้มีหน้าที่สร้างขอบเขตค้นหา 20 นาทีเท่านั้น
            <strong>ไม่ใช่ CBD และไม่ใช่แปลงที่ต้องการลงทุน</strong>
        </p>
    </div>

    <div class="flow-title">🧭 Flow การหา CBD และ Rent Gradient</div>
    <div class="flow">
        <div class="step">
            <div class="number">1</div>
            <div>
                <b>ปักหมุดเริ่มต้น</b>
                <span>เลือกโหนดถนนที่ใกล้จุดกึ่งกลางประชากรมากที่สุด</span>
            </div>
        </div>

        <div class="step">
            <div class="number">2</div>
            <div>
                <b>คำนวณพื้นที่เดินทาง 20 นาที</b>
                <span>เลือกเวลา <code>[20]</code> ค่าเดียว เพื่อสร้างขอบเขตค้นหารอบกว้าง</span>
            </div>
        </div>

        <div class="step">
            <div class="number">3</div>
            <div>
                <b>รัน Network Analysis</b>
                <span>วิเคราะห์พื้นที่ 20 นาที แล้วหา <code>C20</code> = โหนดที่มี Closeness สูงสุด</span>
            </div>
        </div>

        <div class="step">
            <div class="number">4</div>
            <div>
                <b>ใช้ C20 เป็นหมุดใหม่</b>
                <span>ปิดหรือลบหมุดเดิม เลือกเวลา <code>[5]</code> แล้วคำนวณ Isochrone ใหม่จาก C20</span>
            </div>
        </div>

        <div class="step">
            <div class="number">5</div>
            <div>
                <b>รัน Network Analysis อีกครั้ง</b>
                <span>วิเคราะห์พื้นที่ 5 นาที แล้วหา <code>C5</code> = CBD Anchor ขั้นสุดท้าย</span>
            </div>
        </div>

        <div class="step">
            <div class="number">6</div>
            <div>
                <b>หา Golden Spots</b>
                <span>จัดอันดับจุดที่น่าสนใจรอบ C5 และตรวจประกอบด้วยผังเมือง รูปแปลง และประชากร</span>
            </div>
        </div>

        <div class="step">
            <div class="number">7</div>
            <div>
                <b>คำนวณ Rent Gradient</b>
                <span>ใช้ C5 เป็นจุดอ้างอิงของ <code>R(d) = R₀·e<sup>−λd</sup></code> เพื่อสร้าง Curve, Rings และ Rent Heat</span>
            </div>
        </div>
    </div>

    <div class="notes">
        <div class="note">
            <b>G20 ไม่ใช่ขั้นตอนหลัก</b>
            จุดกึ่งกลาง Travel Areas ใช้ชั่วคราวเฉพาะตอนที่ยังไม่มีผล Network
        </div>
        <div class="note">
            <b>สร้างพื้นที่ 5 นาทีใหม่</b>
            ต้องคำนวณจาก C20 ใหม่ ไม่ใช่ย่อรูปพื้นที่ 20 นาที
        </div>
        <div class="note">
            <b>รัน Network ใหม่เสมอ</b>
            หลังเปลี่ยนหมุดหรือเวลา เพื่อไม่ให้ C5 และ Golden Spots ใช้ผลเก่า
        </div>
    </div>

    <div class="formula">
        <b>หมายเหตุเรื่องราคา:</b>
        หากไม่มีตัวอย่างราคาจริงอย่างน้อย 2 จุดที่มีระยะต่างกัน
        ระบบจะแสดงดัชนีสัมพัทธ์ 0–100 ไม่ใช่ราคาตลาดจริง
    </div>
</div>
            """
        )
