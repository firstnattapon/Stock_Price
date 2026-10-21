"""UI — the sidebar: config, isochrone, network, anchor and rent panels.

Definitions are cut verbatim from pages/Rent_Gradient.py (see tests/test_rg_v2_equivalence.py).
"""


import json
import pandas as pd
import streamlit as st
from math import floor
from typing import Any, Dict, List, Optional, Tuple

from .compat import HAS_SCIPY, np
from .config import EVIDENCE_CONFIG, EVIDENCE_SCHEMA, MAP_STYLES, MARKER_COLORS, TIME_OPTIONS, TRAVEL_MODE_NAMES, _WEB_MERCATOR
from .geo import calculate_distance_meters
from .rent import _fit_dof, fit_interval_text, fit_quality_label, fit_quality_warning
from .vision import _tile_bbox, estimate_evidence_requests
from .osm import clear_disk_cache, export_cache_as_zip, get_cache_stats
from .evidence import load_cached_wms_image
from .state import StateManager
from .bundle import download_github_bundle, export_bundle_zip, import_bundle_zip
from .controllers import _anchor_context_matches, _anchor_search_context, _on_rent_anchor_toggle, _parse_anchor_center_input, _sync_rent_samples_from_editor
from .ui_map import _legend_swatch_row


def _apply_bundle(content: bytes, source: str, icon: str) -> None:
    """Import a bundle, report the outcome, rerun on success."""
    result = import_bundle_zip(content)
    if not result["success"]:
        for err in result["errors"]:
            st.error(err)
        return
    mode = "config + cache" if result["cache_loaded"] else "config เท่านั้น"
    st.toast(f"✅ โหลด Bundle{source} สำเร็จ ({mode})", icon=icon)
    for warn in result["warnings"]:
        st.warning(warn)
    st.rerun()


def _render_sidebar_config_section(locked: bool) -> None:
    """Config Import / Export expander."""
    with st.expander("💾 จัดการ Config (Export/Import)", expanded=False):
        # สร้าง bundle เฉพาะเมื่อผู้ใช้กดปุ่ม — ไม่ zip cache ก้อนใหญ่ทุก rerun
        if st.button("📦 เตรียม Bundle (.zip)", use_container_width=True, disabled=locked):
            st.session_state["_bundle_bytes"] = export_bundle_zip()
        if st.session_state.get("_bundle_bytes"):
            st.download_button(
                "⬇ Download Bundle (.zip)",
                st.session_state["_bundle_bytes"],
                "rent_gradient_bundle.zip",
                "application/zip",
                use_container_width=True,
                disabled=locked,
            )

        uploaded_bundle = st.file_uploader("Upload Bundle (.zip)", type=["zip"], key="bundle_uploader")
        if uploaded_bundle and st.button("ยืนยันการโหลด Bundle", use_container_width=True, disabled=locked):
            _apply_bundle(uploaded_bundle.read(), "", "📦")

        st.markdown("---")
        st.markdown("##### Import Bundle from GitHub")
        st.caption("แหล่งข้อมูลคงที่: เชียงของ.zip")
        if st.button("นำเข้า Bundle จาก GitHub", use_container_width=True, disabled=locked):
            bundle_bytes, err = download_github_bundle()
            if err:
                st.error(err)
            elif not bundle_bytes:
                st.error("ไม่พบข้อมูล Bundle จาก GitHub")
            else:
                _apply_bundle(bundle_bytes, " จาก GitHub", "📥")


def _render_sidebar_marker_input(locked: bool) -> None:
    """Manual coordinate input row."""
    c1, c2 = st.columns([0.7, 0.3])
    coords_input = c1.text_input(
        "Coords",
        placeholder="20.21, 100.40",
        label_visibility="collapsed",
        key="manual_coords",
        disabled=locked,
    )
    if c2.button("เพิ่ม", use_container_width=True, disabled=locked):
        try:
            lat_str, lng_str = coords_input.strip().split(",")
            StateManager.add_marker(float(lat_str), float(lng_str))
            StateManager.invalidate_inputs()
            st.rerun()
        except Exception:
            st.error("Format: Lat, Lng")


def _render_sidebar_marker_list(locked: bool) -> List[Tuple[int, Dict[str, Any]]]:
    """Render the marker list with toggle / delete controls. Returns active_list."""
    markers = StateManager.get_markers()

    # Delete last / Reset buttons
    c1, c2 = st.columns(2)
    if c1.button("❌ ลบจุดล่าสุด", use_container_width=True, disabled=locked) and markers:
        StateManager.pop_last_marker()
        StateManager.invalidate_inputs()
        st.rerun()
    if c2.button("🔄 รีเซ็ต", use_container_width=True, disabled=locked):
        StateManager.reset()
        st.rerun()

    active_list = StateManager.get_active_markers()
    st.write(f"📍 Active Markers: **{len(active_list)}**")

    if markers:
        st.markdown("---")
        for i, m in enumerate(markers):
            col1, col2, col3 = st.columns([0.15, 0.70, 0.15])

            prev_active = m.get("active", True)
            is_active = col1.checkbox(
                " ",
                value=prev_active,
                key=f"active_chk_{i}",
                label_visibility="collapsed",
                disabled=locked,
            )

            if is_active != prev_active:
                StateManager.set_marker_active(i, is_active)
                StateManager.invalidate_inputs()

            if is_active:
                style = (
                    f"color:{MARKER_COLORS[i % len(MARKER_COLORS)]}; font-weight:bold;"
                )
            else:
                style = "color:gray; text-decoration:line-through;"
            col2.markdown(
                f"<span style='{style}'>● จุดที่ {i+1}</span> "
                f"<span style='font-size:0.8em'>({m['lat']:.4f}, {m['lng']:.4f})</span>",
                unsafe_allow_html=True,
            )

            if col3.button("✕", key=f"del_btn_{i}", disabled=locked):
                StateManager.remove_marker(i)
                StateManager.invalidate_inputs()
                st.rerun()

    # Refresh active list after possible mutations
    return StateManager.get_active_markers()


def _render_sidebar_network_panel(locked: bool) -> bool:
    """
    Render the Network Analysis expander (cache management + run button).

    Returns ``True`` if the user clicked **Run Network Analysis**.
    """
    with st.expander("🕸️ วิเคราะห์โครงข่าย (Network Analysis)", expanded=True):
        st.caption("วิเคราะห์ความสำคัญของถนน (OSMnx)")

        can_analyze = StateManager.get_isochrone_data() is not None
        if can_analyze:
            st.info("✅ **Scope:** พื้นที่ Travel Areas ทั้งหมด", icon="🗺️")
        else:
            st.warning("⚠️ **Scope:** กรุณาคำนวณ Isochrone ก่อน", icon="🛑")

        # ---- Cache Management ----
        cache_stats = get_cache_stats()
        st.markdown("##### 💾 Cache Management")

        if cache_stats["count"] > 0:
            st.caption(
                f"📊 **{cache_stats['count']} ไฟล์** "
                f"({cache_stats['size_mb']:.1f} MB)"
            )

            if st.button(
                "📤 Export Cache (.zip)",
                use_container_width=True,
                key="export_cache_btn",
                disabled=locked,
            ):
                st.session_state["_cache_zip_bytes"] = export_cache_as_zip()
            if st.session_state.get("_cache_zip_bytes"):
                st.download_button(
                    "⬇ Download Ready",
                    data=st.session_state["_cache_zip_bytes"],
                    file_name="osmnx_cache.zip",
                    mime="application/zip",
                    use_container_width=True,
                )

            if st.button(
                "🗑️ ล้าง Cache",
                use_container_width=True,
                type="secondary",
                disabled=locked,
            ):
                clear_disk_cache()
                st.toast("ล้าง Cache สำเร็จ!", icon="✅")
                st.rerun()
        else:
            st.caption("📊 **Cache ว่างเปล่า**")


        st.markdown("---")
        do_network: bool = st.button(
            "🚀 Run Network Analysis",
            use_container_width=True,
            disabled=(not can_analyze) or locked,
        )

        # ---- Network results preview ----
        net_data = StateManager.get_network_data()
        if net_data and net_data.get("top_node"):
            top = net_data["top_node"]
            stats = net_data.get("stats", {})
            st.markdown("---")
            st.markdown("**🏆 จุดที่อยู่ตรงกลางที่สุด (Integration Center)**")
            st.caption(f"Score: {top['score']:.4f}")
            if stats.get("used_approximation"):
                st.caption("⚡ *ใช้ Approximation (กราฟขนาดใหญ่)*")
            closeness_method_labels = {
                "exact-scipy": "🧭 Closeness: exact (scipy, ถ่วงน้ำหนักเมตร)",
                "pivot-approx": "🧭 Closeness: pivot sampling (Eppstein–Wang)",
                "networkx-fallback": "🧭 Closeness: networkx fallback (ไม่มี scipy)",
            }
            method_label = closeness_method_labels.get(stats.get("closeness_method"))
            if method_label:
                st.caption(method_label)
            st.code(f"{top['lat']:.5f}, {top['lon']:.5f}")

            if st.button(
                "➕ เพิ่มจุดนี้ลงในรายการ",
                use_container_width=True,
                type="secondary",
                disabled=locked,
            ):
                StateManager.add_marker(top["lat"], top["lon"])
                StateManager.invalidate_inputs()
                st.toast("เพิ่มจุดใหม่เรียบร้อย! กรุณากดคำนวณใหม่", icon="✅")
                st.rerun()

        golden_spots = net_data.get("golden_spots") if net_data else None
        if golden_spots:
            st.markdown("---")
            st.markdown("**💎 ทำเลที่ดินทอง (ก่อนคนรู้)**")
            st.caption(
                "สมการคะแนน: 0.50×Closeness + 0.30×Degree + 0.20×(1-Betweenness)"
            )

            preview_lines = []
            for i, spot in enumerate(golden_spots[:5], start=1):
                preview_lines.append(
                    f"{i}. score={spot['score']:.4f} | "
                    f"{spot['lat']:.5f}, {spot['lon']:.5f}"
                )
            st.code("\n".join(preview_lines), language="text")

            best = golden_spots[0]
            if st.button(
                "➕ เพิ่มจุดทำเลที่ดินทองอันดับ 1",
                use_container_width=True,
                type="secondary",
                disabled=locked,
            ):
                StateManager.add_marker(best["lat"], best["lon"])
                StateManager.invalidate_inputs()
                st.toast("เพิ่มทำเลที่ดินทองแล้ว! กรุณากดคำนวณใหม่", icon="💎")
                st.rerun()

        st.markdown("##### Layer Controls")
        st.checkbox("Show Roads (Betweenness)", key="show_betweenness", disabled=locked)
        st.caption("🔴: ทางผ่านหลัก (High Traffic Flow)")
        st.checkbox("Show Nodes (Integration)", key="show_closeness", disabled=locked)
        st.caption("⚫: จุดเข้าถึงง่าย (Central Hub)")
        st.checkbox("Show Golden Spots", key="show_golden_spots", disabled=locked)
        st.caption("💎: จุดทำเลที่ดินทอง (คะแนนรวมสูง)")

    return do_network


def _anchor_summary(label: str, result: Dict[str, Any], diagnostics: bool = False) -> None:
    """Compact, identical presentation for the composite and the Closeness-100% anchor."""
    anchor = result["anchor"]
    st.write(f"**{anchor['source']}** ({anchor['lat']:.6f}, {anchor['lon']:.6f})")
    st.caption(f"Score {anchor['score']:.4f} · {result['evaluated_nodes']} โหนดที่ประเมินแม่นยำ "
               f"จาก {result['candidate_nodes']} candidates")
    if diagnostics:
        st.caption(f"Closeness {anchor['closeness']:.8f} 1/m · Degree {anchor['degree']} · "
                   f"Junctions/500m {anchor['junction_count']} (diagnostics only)")
    st.caption("ตรวจคะแนนครบทุก candidate: ยืนยันคะแนนสูงสุดของ objective นี้แล้ว"
               if result.get("globally_certified")
               else "คัดด้วย pivot closeness แล้วประเมินแม่นยำ — ไม่รับรอง global optimum")
    effective = result.get("effective_weights")
    if effective and result.get("scoring") == "rank-v2":
        contribution = result["winner_contribution"]
        st.caption(
            "น้ำหนักที่มีผลจริงต่อการจัดอันดับ — "
            f"Closeness {effective['closeness']:.0%} · Degree {effective['degree']:.0%} · "
            f"Density {effective['density']:.0%} (ประกาศ 50/30/20); "
            f"สัดส่วนคะแนนที่ผู้ชนะ — {contribution['closeness']:.0%} / "
            f"{contribution['degree']:.0%} / {contribution['density']:.0%}"
        )
    stability = result.get("stability")
    if stability:
        badge = {"stable": "🟢 นิ่ง", "check": "🟡 ควรตรวจ", "unstable": "🔴 ไม่นิ่ง"}[stability["level"]]
        st.caption(
            f"ความนิ่งเมื่อวงศึกษาเปลี่ยน ±20% (ประมาณการ): {badge} — ขยับสูงสุด "
            f"{stability['max_drift_m']:.0f} ม. ({stability['max_drift_ratio']:.0%} ของรัศมี)"
        )
    for warning in result.get("warnings", []):
        st.warning(warning)


def _evidence_thumbnail(rgba: np.ndarray, size: int = 340) -> Any:
    """Cached window on a white card (transparent layers are invisible on a dark theme)."""
    from PIL import Image

    card = Image.new("RGBA", (rgba.shape[1], rgba.shape[0]), (255, 255, 255, 255))
    card.alpha_composite(Image.fromarray(rgba, "RGBA"))
    return card.convert("RGB").resize((size, size))


def _evidence_diagnostics(evidence: Dict[str, Any]) -> None:
    """What the stage actually read: the plan's dominant colours (and which count as red) and how many
    lots / how dense the parcels were — the numbers to look at when the answer looks wrong."""
    plan, parcel = evidence.get("plan") or {}, evidence.get("parcel") or {}
    with st.expander("วินิจฉัยการอ่านภาพ (สีผังเมือง + แปลงที่ดิน)"):
        explained = plan.get("explained")
        st.caption(f"ผังเมือง: {plan.get('state', '—')} · อ่านได้ {plan.get('tiles_ok', 0)}/{plan.get('tiles', 0)} ไทล์"
                   + (f" · legend อธิบายสีได้ {explained:.0%}" if explained is not None else ""))
        if plan.get("colours"):
            st.dataframe([{"สี": c["hex"], "สัดส่วน %": round(100 * c["share"], 1), "ตรง legend": c["legend"] or "—",
                           "นับเป็นแดง": c["red"]} for c in plan["colours"]], hide_index=True)
        if parcel.get("best_score") is not None:
            st.caption(f"แปลงที่ดิน: อ่านได้ {parcel.get('lots', 0):,} แปลงใน {parcel.get('tiles_ok', 0)}/"
                       f"{parcel.get('tiles_needed', 0)} ไทล์ · คะแนนความถี่สูงสุดในโซน {parcel['best_score']:.2f} · "
                       f"เกณฑ์ cluster {parcel['hot_threshold']:.2f}")
        elif parcel.get("tiles_needed"):
            st.caption(f"แปลงที่ดิน: อ่านได้ {parcel.get('lots', 0):,} แปลงใน {parcel.get('tiles_ok', 0)}/"
                       f"{parcel.get('tiles_needed', 0)} ไทล์ แต่ไม่มีเซลล์ที่วัดความถี่ได้")


def _evidence_summary(evidence: Dict[str, Any], composite: Optional[Dict[str, Any]]) -> None:
    """Peak colour, dense parcel cluster, confidence and stability of the evidence stage."""
    fetch = evidence.get("fetch", {})
    if evidence.get("schema") != EVIDENCE_SCHEMA:
        st.warning("ผลหลักฐานนี้มาจากเวอร์ชันเก่า (ยึดผู้สมัครจากถนน) — กดค้นหาอีกครั้งเพื่อคำนวณใหม่",
                   icon="⚠️")
        return
    if evidence.get("legend_source") == "provisional":
        st.warning("โซนแดงอ่านตามเฉดสี (ไม่ผูกกับ legend) แต่สีผังเมืองอื่นยังเป็นค่าชั่วคราว "
                   "(ยังไม่ calibrate กับภาพจริงของ Longdo) — ใช้เป็นหลักฐานประกอบ ไม่ใช่คำตอบสุดท้าย",
                   icon="⚠️")
    if evidence.get("status") == "unavailable" or not evidence.get("evidence_anchor"):
        st.warning(f"ไม่ได้หลักฐานเสริม: {evidence.get('reason') or 'ไม่ทราบสาเหตุ'} — ใช้ผลจากถนนอย่างเดียว")
        if fetch.get("errors"):
            st.caption("; ".join(fetch["errors"][:3]))
        _evidence_diagnostics(evidence)
        return
    anchor, confidence = evidence["evidence_anchor"], evidence["confidence"]
    study, plan, parcel = evidence["study"], evidence["plan"], evidence["parcel"]
    badge = {"HIGH": "🟢 สูง", "MEDIUM": "🟡 กลาง", "LOW": "🔴 ต่ำ"}[confidence["level"]]
    st.write(f"**{anchor['source']}** ({anchor['lat']:.6f}, {anchor['lon']:.6f})")
    st.caption(
        f"ความเชื่อมั่น: {badge} · คะแนน cluster {anchor['score']:.3f} · "
        f"ข้อมูลแปลงครบ {anchor['coverage']:.0%}"
        + (" · ข้อมูลบางส่วน" if evidence.get("status") == "partial" else ""))
    for reason in confidence["reasons"]:
        st.caption(f"• {reason}")
    for note in evidence.get("notes", []):
        st.caption(f"ℹ️ {note}")
    peak = plan.get("peak")
    st.caption(f"สแกนรัศมี {study['radius_m'] / 1000:g} กม. (≈ {study['area_km2']:,.0f} ตร.กม.)"
               + (f" · ผังสีสูงสุด: {peak['name']} {peak['area_km2']:.2f} ตร.กม. ({len(plan['zones'])} โซนใหญ่)"
                  if peak else " · ไม่พบโซนแดง (พาณิชยกรรม) ในวงศึกษา"))
    if peak:
        st.markdown(_legend_swatch_row(f"rgb({peak['rgb'][0]},{peak['rgb'][1]},{peak['rgb'][2]})",
                                       f"{peak['name']} (พาณิชยกรรม) — สีที่อ่านได้จริง "
                                       f"rgb({peak['rgb'][0]},{peak['rgb'][1]},{peak['rgb'][2]})"),
                    unsafe_allow_html=True)
    stability = evidence.get("stability")
    if stability:
        level = {"stable": "🟢 นิ่ง", "check": "🟡 ควรตรวจ", "unstable": "🔴 ไม่นิ่ง"}[stability["level"]]
        st.caption(f"ความนิ่งเมื่อวงศึกษาเปลี่ยน (ประมาณการ): {level} — ขยับสูงสุด "
                   f"{stability['max_drift_m']:.0f} ม. ({stability['max_drift_ratio']:.0%} ของรัศมี)")
    if composite:
        moved = calculate_distance_meters(
            composite["anchor"]["lat"], composite["anchor"]["lon"], anchor["lat"], anchor["lon"])
        st.caption(f"ห่างจาก anchor ① {moved:,.0f} ม.")
    st.caption(f"ดึงภาพ {fetch.get('requests', 0)} คำขอ · จากแคช {fetch.get('cache_hits', 0)} · "
               f"ผังเมือง {plan.get('tiles_ok', 0)}/{plan.get('tiles', 0)} ไทล์ · "
               f"แปลงที่ดิน {parcel.get('tiles_ok', 0)}/{parcel.get('tiles_needed', 0)} ไทล์ · "
               f"{fetch.get('seconds', 0.0):.1f} วินาที"
               + (f" · ข้าม {fetch['skipped_over_budget']} ไทล์ (เกินโควตา/หมดเวลา)"
                  if fetch.get("skipped_over_budget") else ""))
    st.checkbox("ใช้ Evidence Anchor คำนวณ Rent Gradient", key="rent_use_evidence_anchor",
                on_change=_on_rent_anchor_toggle,
                help="ค่าเริ่มต้น: Rent ใช้ anchor ① Composite — ติ๊กเมื่อยอมรับหลักฐานผังเมือง/แปลงที่ดินแล้ว")
    _evidence_diagnostics(evidence)
    with st.expander("รายละเอียดหลักฐาน (cluster + ภาพ)"):
        st.dataframe([
            {
                "อันดับ": c["rank"], "Lat": round(c["lat"], 5), "Lon": round(c["lon"], 5),
                "เซลล์": c["cells"], "เฮกตาร์": round(c["area_ha"]), "คะแนน": round(c["score"], 3),
                "ห่างศูนย์ (กม.)": round(c["distance_m"] / 1000, 1), "คะแนนถ่วงระยะ": round(c["weighted_mass"], 1),
                "แปลงเล็ก%": round(100 * c["cover_small"]), "ตึกแถว%": round(100 * c["cover_shop"]),
                "ในโซนสีสูงสุด": c["in_zone"], "สแกนไม่ครบ": c["touches_boundary"],
            }
            for c in evidence["clusters"]
        ], hide_index=True)
        windows, px = evidence["windows"], evidence["windows"]["px"]
        x, y = _WEB_MERCATOR.transform(anchor["lon"], anchor["lat"])
        left, right = st.columns(2)
        for column, layer, tile_m, title in (
                (left, EVIDENCE_CONFIG["parcel_layer"], windows["parcel_tile_m"], "รูปแปลงที่ดิน (dol)"),
                (right, EVIDENCE_CONFIG["plan_layer"], windows["plan_tile_m"], "ผังเมืองรวม (cityplan_dpt)")):
            image = load_cached_wms_image(
                layer, _tile_bbox(int(floor(x / tile_m)), int(floor(y / tile_m)), tile_m), px)
            if image is not None:
                column.image(_evidence_thumbnail(image), caption=f"{title} · ไทล์ {tile_m / 1000:g} กม.")
        st.download_button("ดาวน์โหลด Evidence JSON", json.dumps(evidence, ensure_ascii=False, indent=2),
                           "automated_cbd_evidence.json", "application/json")


def _render_sidebar_anchor_panel(locked: bool) -> bool:
    """One button, one road download, both anchors (Composite + Closeness 100%)."""
    with st.expander("🎯 Automated CBD Anchor", expanded=True):
        st.caption("กำหนดพื้นที่ศึกษา แล้วค้นหาจุดศูนย์กลางเชิงโครงข่ายถนน (ไม่ใช้ seed — ผลซ้ำได้เสมอ)")
        st.info(
            "ผลลัพธ์คือ **ศูนย์กลางเชิงโครงข่ายถนน** ของพื้นที่ที่เลือก (ขึ้นกับจุดศูนย์กลาง/รัศมี) "
            "ยังไม่ได้พิสูจน์ว่าตรงกับ CBD เชิงเศรษฐกิจ — ดูป้ายความนิ่งด้านล่าง "
            "และเทียบกับจุดที่ทราบก่อนใช้ตัดสินใจ",
            icon="ℹ️",
        )
        if "anchor_center_input" not in st.session_state:
            st.session_state["anchor_center_input"] = (
                f"{st.session_state.anchor_lat!r}, {st.session_state.anchor_lon!r}"
            )
        center_text = st.text_input(
            "ศูนย์พื้นที่ศึกษา Lat, Lon",
            key="anchor_center_input",
            placeholder="20.075226819421776, 100.5083729446834",
            disabled=locked,
            help=(
                "กรอกพิกัดเป็น Lat, Lon ในช่องเดียว เช่น "
                "20.075226819421776, 100.5083729446834"
            ),
        )
        center_valid = True
        try:
            center_lat, center_lon = _parse_anchor_center_input(center_text)
        except ValueError as exc:
            center_valid = False
            st.error(str(exc))
        else:
            if (
                center_lat != st.session_state.anchor_lat
                or center_lon != st.session_state.anchor_lon
            ):
                st.session_state.anchor_lat = center_lat
                st.session_state.anchor_lon = center_lon
        st.number_input("รัศมีพื้นที่ศึกษา (กม.)", 4.0, 20.0,
                        key="anchor_radius_km", step=0.5, disabled=locked)
        st.checkbox(
            "🗺️ Evidence: ผังสีสูงสุด + แปลงที่ดินถี่ cluster (ทดลอง)",
            key="anchor_use_evidence", disabled=locked,
            help=(
                "หลังหา anchor จากถนน จะอ่านผังเมืองรวม (cityplan_dpt) ทั้งวงศึกษา หาโซนสีสูงสุด "
                "(เช่น พาณิชยกรรม) แล้วดึงรูปแปลงที่ดิน (dol) เฉพาะในโซนนั้น เพื่อหา cluster ของแปลงเล็ก"
                "ถี่แบบตึกแถว — จุดกึ่งกลาง cluster คือ Evidence anchor พร้อมความเชื่อมั่น. "
                "ภาพถูกแคชบนดิสก์ (ไทล์เดิมไม่ถูกดึงซ้ำแม้เปลี่ยนจุดศูนย์กลาง/รัศมี) "
                "ถ้าดึงไม่ได้จะใช้ผลจากถนนอย่างเดียว"
            ),
        )
        if st.session_state.get("anchor_use_evidence") and center_valid:
            estimate = estimate_evidence_requests(
                (st.session_state.anchor_lat, st.session_state.anchor_lon),
                st.session_state.anchor_radius_km * 1000)
            st.caption(
                f"Evidence จะสแกนรัศมี {st.session_state.anchor_radius_km:g} กม. "
                f"(≈ {estimate['area_km2']:,.0f} ตร.กม.): ผังเมือง {estimate['plan_tiles']} ไทล์ + "
                f"แปลงที่ดินสูงสุด {estimate['parcel_tiles_max']} ไทล์ (ไม่เกิน {estimate['requests_max']} คำขอ)")

        context = _anchor_search_context()
        result = st.session_state.get(StateManager.K_AUTO_ANCHOR)
        closeness_result = st.session_state.get(StateManager.K_AUTO_ANCHOR_CLOSENESS)
        evidence_result = st.session_state.get(StateManager.K_AUTO_ANCHOR_EVIDENCE)
        if ((result and not _anchor_context_matches(result.get("context"), context))
                or (closeness_result
                    and not _anchor_context_matches(closeness_result.get("context"), context))
                or (evidence_result
                    and not _anchor_context_matches(evidence_result.get("context"), context))):
            StateManager.clear_results(["anchor", "anchor_closeness", "anchor_evidence"])
            st.rerun()

        if not HAS_SCIPY:
            st.error("กรุณาติดตั้ง scipy และ numpy เพื่อค้นหา Anchor")

        run_anchor = st.button(
            "🎯 ค้นหา CBD Anchor อัตโนมัติ",
            disabled=locked or not HAS_SCIPY or not center_valid,
            use_container_width=True,
        )

        if result:
            st.markdown("##### ① Composite (ใช้กับ Rent Gradient)")
            st.caption("Closeness 50% + Degree 30% + ความหนาแน่นทางแยกใน 500 ม. 20% "
                       "(แต่ละตัวแปลงเป็นอันดับ 0–1 ก่อนถ่วงน้ำหนัก) — junction เป็น candidate หลัก")
            _anchor_summary("composite", result)
        if closeness_result:
            st.markdown("##### ② Closeness 100% (เปรียบเทียบเท่านั้น)")
            st.caption("Score = Closeness อย่างเดียว (ระยะถนนเป็นเมตร) ทุก road node เป็น candidate; "
                       "Rent Gradient ยังคงใช้ตัวที่ ①")
            _anchor_summary("closeness", closeness_result, diagnostics=True)
        if evidence_result:
            st.markdown("##### ③ Evidence (ผังสีสูงสุด + แปลงที่ดินถี่)")
            _evidence_summary(evidence_result, result)
        elif result and st.session_state.get("anchor_use_evidence"):
            st.caption("เปิดตัวเลือกหลักฐานแล้ว — กดค้นหาอีกครั้ง (ใช้ถนนจากแคช) เพื่อตรวจผังเมือง/แปลงที่ดิน")
        shown = result or closeness_result
        if shown:
            timings = shown.get("timings", {})
            graph_info = shown.get("graph", {})
            st.caption(
                f"โหลดข้อมูลถนน {shown.get('load_seconds', 0.0):.2f} วินาที"
                f" ({graph_info.get('source', 'unknown')}) · คำนวณ {shown['compute_seconds']:.2f} วินาที"
                + (f" (เตรียม {timings['prep_s']:.2f} · pivot {timings['pivots_s']:.2f} · "
                   f"exact {timings['exact_s']:.2f})" if timings else "")
            )
            st.download_button(
                "ดาวน์โหลด Anchor JSON",
                json.dumps({"composite": result, "closeness": closeness_result,
                            "evidence": evidence_result}, ensure_ascii=False, indent=2),
                "automated_cbd_anchors.json",
                "application/json",
            )
            if st.button("ล้าง Anchor ที่ค้นหาไว้", disabled=locked):
                StateManager.clear_results(["anchor", "anchor_closeness", "anchor_evidence"])
                st.rerun()
        return run_anchor


def _render_sidebar_rent_panel(locked: bool) -> bool:
    """
    Render the Rent Gradient (Bid-Rent) expander.

    Returns ``True`` if the user clicked **คำนวณ Rent Gradient**.
    """
    with st.expander("💰 Rent Gradient (Bid-Rent)", expanded=True):
        st.caption("หลัก Alonso-Muth-Mills: **R(d) = R₀ · e^(−λ·d)** — ค่าเช่าลดลงตามระยะจาก CBD")

        can_run = (StateManager.get_isochrone_data() is not None
                   or st.session_state.get(StateManager.K_AUTO_ANCHOR) is not None)
        if not can_run:
            st.warning("⚠️ **Scope:** กรุณาคำนวณ Isochrone หรือค้นหา Automated Anchor ก่อน", icon="🛑")

        # ---- Calibration samples ----
        st.markdown("##### 🧾 ตัวอย่างราคาจริง (Calibration)")
        st.caption(
            "แนะนำ ≥ 5 จุดที่ระยะต่างกันเพื่อ fit λ จากตลาดจริง (2 จุดคำนวณได้ "
            "แต่ R² = 1 เสมอ จึงไม่บอกคุณภาพ) — เว้นว่างไว้ระบบจะใช้ดัชนี 0–100"
        )
        samples = StateManager.get_rent_samples()
        df = pd.DataFrame(samples, columns=["lat", "lon", "rent"], dtype="float64")
        edited_df = st.data_editor(
            df,
            num_rows="dynamic",
            hide_index=True,
            use_container_width=True,
            disabled=locked,
            column_config={
                "lat": st.column_config.NumberColumn("Lat", format="%.5f"),
                "lon": st.column_config.NumberColumn("Lon", format="%.5f"),
                "rent": st.column_config.NumberColumn("ราคา", min_value=0.0),
            },
        )
        if not locked:
            _sync_rent_samples_from_editor(edited_df)

        st.text_input("หน่วยราคา", key="rent_unit_label", disabled=locked)

        # ---- Layer toggles ----
        st.checkbox("🌈 Rent Rings (วงแหวนราคา)", key="show_rent_rings", disabled=locked)
        st.checkbox("🔥 Rent Heat (โหนดถนน)", key="show_rent_nodes", disabled=locked)
        st.caption("Rent Heat ต้องรัน Network Analysis ก่อน")

        do_rent: bool = st.button(
            "🧮 คำนวณ Rent Gradient",
            use_container_width=True,
            disabled=(not can_run) or locked,
        )

        # ---- Model summary ----
        rent_data = StateManager.get_rent_data()
        if rent_data and "error" not in rent_data:
            model = rent_data["model"]
            st.markdown("---")
            c1, c2 = st.columns(2)
            c1.metric("λ (ต่อ km)", f"{model['lam']:.4f}")
            half = model.get("half_dist_km")
            c2.metric("d½ (km)", f"{half:.2f}" if half else "∞")

            c3, c4 = st.columns(2)
            r0_txt = f"{model['r0']:,.0f}" if not model["is_index"] else f"{model['r0']:.0f} (ดัชนี)"
            c3.metric("R₀ ที่ CBD", r0_txt)
            if model.get("r2") is not None:
                if _fit_dof(model) > 0:
                    c4.metric("R² (fit)", f"{model['r2']:.3f}", help=fit_quality_label(model))
                else:
                    c4.metric("R² (fit)", "—", help=fit_quality_label(model))
            else:
                c4.metric("Calibration", "ดัชนี (ไม่มีตัวอย่าง)")
            interval = fit_interval_text(model)
            if interval:
                st.caption(f"n = {model['n_samples']} · {interval}")
            quality_warning = fit_quality_warning(model)
            if quality_warning:
                st.warning(quality_warning, icon="📉")

            anchor = rent_data["anchor"]
            st.caption(
                f"จุดยึด CBD: **{anchor['source']}** "
                f"({anchor['lat']:.5f}, {anchor['lon']:.5f})"
            )
            if model.get("inverted"):
                st.warning(
                    "λ ติดลบ — ราคาตัวอย่างสูงขึ้นตามระยะจาก CBD "
                    "(gradient กลับทิศ) ตรวจสอบตำแหน่งตัวอย่างหรือจุดยึด CBD",
                    icon="↔️",
                )

    return do_rent


def _render_sidebar_map_settings(locked: bool) -> None:
    """Map & Layer settings expander."""
    with st.expander("⚙️ ตั้งค่าแผนที่ & Layers", expanded=True):
        st.selectbox("สไตล์แผนที่", list(MAP_STYLES.keys()), key="map_style_name", disabled=locked)
        st.checkbox("🚦 การจราจร (Google Traffic)", key="show_traffic", disabled=locked)
        st.checkbox("👥 ความหนาแน่นประชากร", key="show_population", disabled=locked)

        c1, c2 = st.columns([0.65, 0.35])
        c1.checkbox("🏙️ ผังเมืองรวม", key="show_cityplan", disabled=locked)
        if st.session_state.show_cityplan:
            c2.slider(
                "Op.", 0.2, 1.0, key="cityplan_opacity", label_visibility="collapsed", disabled=locked
            )

        st.checkbox("📜 รูปแปลงที่ดิน", key="show_dol", disabled=locked)
        st.checkbox("🚂 แนวรถไฟเชียงของ", key="show_railway", disabled=locked)

        st.markdown("##### 🚗 การเดินทาง (Isochrone)")
        st.selectbox(
            "โหมด",
            list(TRAVEL_MODE_NAMES.keys()),
            format_func=TRAVEL_MODE_NAMES.get,
            key="travel_mode",
            disabled=locked,
        )
        st.multiselect("เวลา (นาที)", TIME_OPTIONS, key="time_intervals", disabled=locked)


def render_sidebar() -> Tuple[bool, bool, bool, bool, List[Tuple[int, Dict[str, Any]]]]:
    """
    Orchestrate the full sidebar — เรียงตามลำดับ pipeline:
    ① ปักหมุด → ② Isochrone CBD → ③ Network → ④ Rent Gradient → ตั้งค่าแผนที่

    Returns:
        ``(do_calculate, do_network, do_rent, do_anchor, active_markers_list)``
    """
    with st.sidebar:
        st.header("⚙️ การตั้งค่า")

        ui_locked = st.toggle("🔒 Lock Active Markers + เมนูทั้งหมด", key=StateManager.K_UI_LOCKED)
        _render_sidebar_config_section(ui_locked)
        st.markdown("---")
        _render_sidebar_marker_input(ui_locked)

        st.text_input("Geoapify API Key", key="api_key", type="password", disabled=ui_locked)

        active_list = _render_sidebar_marker_list(ui_locked)

        do_calc: bool = st.button(
            "🧩 ① คำนวณหา Isochrone CBD",
            type="primary",
            use_container_width=True,
            disabled=ui_locked,
        )
        st.markdown("---")

        do_network = _render_sidebar_network_panel(ui_locked)
        st.markdown("---")

        do_rent = _render_sidebar_rent_panel(ui_locked)
        st.markdown("---")

        _render_sidebar_map_settings(ui_locked)
        do_anchor = _render_sidebar_anchor_panel(ui_locked)

    return do_calc, do_network, do_rent, do_anchor, active_list
