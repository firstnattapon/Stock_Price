"""
Rent Gradient x Space Syntax (Laora) — Bid-Rent บนระยะของโครงข่ายถนน
===================================================================
หน้านี้แยกจาก ``Rent_Gradient.py`` (ไม่แก้ไฟล์เดิม): ใช้สมการ Bid-Rent เดิม
``R(d) = R₀·e^(−λ·d)`` แต่ลองนิยาม "ระยะ d" 4 แบบ แล้วเทียบว่าแบบไหนอธิบายราคาได้ดีที่สุด

    euclid       เส้นตรง (baseline เหมือนหน้าเดิม)          km
    metric       ระยะตามถนนจริง (Dijkstra)                  km
    topological  จำนวนก้าวต่อ segment (นับเฉพาะการเลี้ยว)     steps
    angular      ผลรวมมุมเลี้ยว (90° = 1.0)                  ×90°

จุดอ้างอิงเป็น *ชุด* ของถนน (Main Street) ไม่ใช่จุดเดียว ตามงานของ Laora
การคำนวณทั้งหมดอยู่ใน ``rent_gradient_laora/core.py`` (ทดสอบ offline ได้)
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rent_gradient_laora import core  # noqa: E402

PAGE_CONFIG: Dict[str, Any] = {
    "page_title": "Rent Gradient x Space Syntax (Laora)",
    "page_icon": "🧭",
    "layout": "wide",
}

# ค่าเริ่มต้นเดียวกับ Rent_Gradient.py (เชียงของ)
DEFAULT_LAT = 20.219443
DEFAULT_LON = 100.403630
NETWORK_TYPES: Dict[str, str] = {"drive": "🚗 ถนนรถ", "walk": "🚶 เดินเท้า", "bike": "🚲 จักรยาน"}

KIND_LABELS: Dict[str, str] = {
    "euclid": "Euclid (เส้นตรง)",
    "metric": "Metric (ตามถนน)",
    "topological": "Topological (จำนวนก้าว)",
    "angular": "Angular (มุมเลี้ยว)",
}
KIND_COLORS: Dict[str, str] = {
    "euclid": "#898781", "metric": "#2a78d6", "topological": "#eb6834", "angular": "#2a9d8f",
}
DEFAULT_BIN: Dict[str, float] = {"euclid": 0.5, "metric": 0.5, "topological": 1.0, "angular": 0.25}

K_GRAPH, K_NET, K_META = "laora_graph", "laora_net", "laora_meta"
K_RESULT, K_SAMPLES = "laora_result", "laora_samples"
BASE_PAGE_MODULE = "rent_gradient_base_for_laora"


# ============================================================================
# DATA ACCESS
# ============================================================================

def _base_page() -> Optional[Any]:
    """Load ``pages/Rent_Gradient.py`` read-only to reuse its Overpass failover + disk cache.

    Returns ``None`` when it cannot be imported; the page then falls back to plain osmnx.
    """
    if BASE_PAGE_MODULE in sys.modules:
        return sys.modules[BASE_PAGE_MODULE]
    path = ROOT / "pages" / "Rent_Gradient.py"
    try:
        spec = importlib.util.spec_from_file_location(BASE_PAGE_MODULE, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[BASE_PAGE_MODULE] = module
        spec.loader.exec_module(module)
        return module
    except Exception:
        sys.modules.pop(BASE_PAGE_MODULE, None)
        return None


def fetch_graph(lat: float, lon: float, radius_m: float, network_type: str
                ) -> Tuple[Optional[Any], str, Optional[str]]:
    """``(graph, source_label, error)`` for a circle around the study centre.

    Prefers the Rent_Gradient.py loader (disk cache + Overpass mirror failover). Only if
    that page cannot be loaded or raises does it fall back to a plain osmnx download.
    """
    base = _base_page()
    reason = "import Rent_Gradient.py ไม่สำเร็จ"
    if base is not None:
        try:
            polygon = base.anchor_study_polygon(lat, lon, radius_m)
            graph, cached, error = base._fetch_osm_graph(polygon.wkt, network_type)
        except Exception as exc:
            reason = f"{type(exc).__name__}: {exc}"
        else:
            if graph is None:
                return None, "", error
            label = graph.graph.get("osm_source") or ("cache" if cached else "download")
            return graph, f"Rent_Gradient cache/failover ({label})", None
    try:
        import osmnx as ox

        graph = ox.graph_from_point((lat, lon), dist=radius_m, network_type=network_type,
                                    truncate_by_edge=True)
        return graph, f"osmnx โดยตรง ({reason})", None
    except Exception as exc:
        return None, "", f"โหลดโครงข่ายถนนไม่สำเร็จ: {type(exc).__name__}: {exc}"


def parse_points(text: str) -> List[Tuple[float, float]]:
    """Lines of ``lat, lon`` -> list of (lat, lon). Raises ValueError on a bad line."""
    points: List[Tuple[float, float]] = []
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        parts = line.replace(";", ",").replace("\t", ",").split(",")
        if len(parts) != 2:
            raise ValueError(f"บรรทัด {number}: ต้องเป็น 'lat, lon'")
        try:
            lat, lon = float(parts[0]), float(parts[1])
        except ValueError as exc:
            raise ValueError(f"บรรทัด {number}: ตัวเลขไม่ถูกต้อง") from exc
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            raise ValueError(f"บรรทัด {number}: พิกัดอยู่นอกช่วง")
        points.append((lat, lon))
    return points


def samples_from_csv(uploaded: Any) -> pd.DataFrame:
    """CSV with columns lat, lon, rent (any case) -> DataFrame; raises ValueError."""
    frame = pd.read_csv(uploaded)
    frame.columns = [str(c).strip().lower() for c in frame.columns]
    missing = {"lat", "lon", "rent"} - set(frame.columns)
    if missing:
        raise ValueError("CSV ต้องมีคอลัมน์ lat, lon, rent (ขาด: " + ", ".join(sorted(missing)) + ")")
    return frame[["lat", "lon", "rent"]].astype("float64")


def _initial_samples() -> pd.DataFrame:
    """Reuse the calibration samples already typed on the Rent_Gradient page, if any."""
    existing = st.session_state.get("rent_samples") or []
    return pd.DataFrame(existing, columns=["lat", "lon", "rent"], dtype="float64")


# ============================================================================
# SIDEBAR
# ============================================================================

def _sidebar_study_area() -> None:
    with st.expander("🗺️ ขอบเขตศึกษา & โครงข่ายถนน", expanded=st.session_state.get(K_NET) is None):
        lat = st.number_input("Lat ศูนย์กลาง", value=DEFAULT_LAT, format="%.6f", key="laora_lat")
        lon = st.number_input("Lon ศูนย์กลาง", value=DEFAULT_LON, format="%.6f", key="laora_lon")
        radius = st.slider("รัศมี (m)", 1000, 6000, 2000, 250, key="laora_radius")
        network_type = st.selectbox("ชนิดโครงข่าย", list(NETWORK_TYPES), key="laora_network",
                                    format_func=lambda k: NETWORK_TYPES[k])
        if st.button("📥 โหลดโครงข่ายถนน", width="stretch"):
            with st.spinner("กำลังโหลดโครงข่ายถนน…"):
                graph, source, error = fetch_graph(lat, lon, float(radius), network_type)
                if graph is None:
                    st.error(error or "โหลดไม่สำเร็จ")
                    return
                try:
                    net = core.build_network(graph)
                except ValueError as exc:
                    st.error(str(exc))
                    return
            st.session_state[K_GRAPH] = graph
            st.session_state[K_NET] = net
            st.session_state[K_META] = {"source": source, "lat": lat, "lon": lon,
                                        "radius": radius, "network": network_type}
            st.session_state.pop(K_RESULT, None)
            st.rerun()


def _sidebar_anchor() -> Optional[Any]:
    """Anchor chooser; returns a ``core.Anchor`` or ``None``."""
    net = st.session_state.get(K_NET)
    with st.expander("📍 จุดยึด (Main Street / CBD)", expanded=net is not None):
        if net is None:
            st.caption("โหลดโครงข่ายถนนก่อน")
            return None
        modes = ["ชื่อถนน (Main Street)", "พิกัด lat, lon"]
        base_data = st.session_state.get("rent_gradient_data") or {}
        base_anchor = base_data.get("anchor") if isinstance(base_data, dict) else None
        if base_anchor and base_anchor.get("lat") is not None:
            modes.append("จุดยึดจากหน้า Rent_Gradient")
        mode = st.radio("กำหนดจุดยึดด้วย", modes, key="laora_anchor_mode")
        try:
            if mode == modes[0]:
                streets = core.list_street_names(net, limit=60)
                if not streets:
                    st.warning("ไม่พบชื่อถนนในข้อมูล OSM — ใช้โหมดพิกัดแทน")
                    return None
                chosen = st.multiselect(
                    "ถนนสายหลัก", [name for name, _ in streets],
                    format_func=lambda n: f"{n} ({dict(streets)[n]:,.0f} m)", key="laora_streets")
                return core.anchor_from_street_names(net, chosen) if chosen else None
            if mode == modes[1]:
                text = st.text_area(
                    "จุดตามถนนสายหลัก (บรรทัดละ lat, lon)", height=110, key="laora_anchor_text",
                    placeholder="20.21944, 100.40363\n20.22010, 100.40420",
                    help="จุดเดียว = CBD เป็นจุด · หลายจุดตามแนวถนน = ถนนสายนั้น")
                pts = parse_points(text)
                return core.anchor_from_points(net, pts) if pts else None
            point = (float(base_anchor["lat"]), float(base_anchor["lon"]))
            st.caption(f"ใช้ {base_anchor.get('source', 'anchor')} ({point[0]:.5f}, {point[1]:.5f})")
            return core.anchor_from_points(net, [point])
        except ValueError as exc:
            st.error(str(exc))
            return None


def _sidebar_samples() -> pd.DataFrame:
    with st.expander("🧾 ตัวอย่างราคาจริง", expanded=True):
        st.caption("แนะนำ ≥ 10 จุดกระจายหลายระยะ — น้อยกว่า 3 จุดเทียบโมเดลไม่ได้")
        if K_SAMPLES not in st.session_state:
            st.session_state[K_SAMPLES] = _initial_samples()
        upload = st.file_uploader("นำเข้า CSV (lat, lon, rent)", type="csv", key="laora_csv")
        if upload is not None and st.session_state.get("laora_csv_done") != upload.file_id:
            try:
                st.session_state[K_SAMPLES] = samples_from_csv(upload)
                st.session_state["laora_csv_done"] = upload.file_id
            except Exception as exc:
                st.error(f"อ่าน CSV ไม่ได้: {exc}")
        edited = st.data_editor(
            st.session_state[K_SAMPLES], num_rows="dynamic", hide_index=True, width="stretch",
            key="laora_editor",
            column_config={
                "lat": st.column_config.NumberColumn("Lat", format="%.5f"),
                "lon": st.column_config.NumberColumn("Lon", format="%.5f"),
                "rent": st.column_config.NumberColumn("ราคา", min_value=0.0),
            })
        st.text_input("หน่วยราคา", value="บาท/ตร.ว./เดือน", key="laora_unit")
        return edited


def _sidebar_options() -> Dict[str, Any]:
    with st.expander("⚙️ ตัวเลือกระยะ", expanded=False):
        turn = st.slider(
            "Topological: นับเป็น 1 ก้าวเมื่อเลี้ยวเกิน (°)", 0, 60, 0, 5, key="laora_turn",
            help="0 = ทุกการเปลี่ยน segment นับ 1 ก้าว · 20–30° = ถนนที่แทบตรงนับเป็นเส้นเดียว")
        offset = st.checkbox("รวมระยะจากจุดถึงถนน (off-network) ใน Metric", value=True,
                             key="laora_offset")
    return {"turn": float(turn), "offset": bool(offset)}


# ============================================================================
# RESULTS
# ============================================================================

def models_table(result: Dict[str, Any]) -> pd.DataFrame:
    """One row per fitted kind in ranking order (rank 1 = best by the criterion)."""
    rows = []
    for rank, kind in enumerate(result["ranking"], start=1):
        m = result["models"][kind]
        rows.append({
            "อันดับ": rank, "ระยะ": KIND_LABELS[kind], "หน่วย": m["unit"], "n": m["n"],
            "λ (ต่อหน่วย)": m["lam"], "R₀": m["r0"], "R²": m["r2"], "Adj R²": m["adj_r2"],
            "LOO-RMSE (ln)": m["loo_rmse"], "AICc": m["aicc"],
        })
    return pd.DataFrame(rows)


def _scatter_figure(result: Dict[str, Any], kind: str, unit_label: str, log_y: bool) -> go.Figure:
    pts = result["points"]
    x = np.array([p[kind] for p in pts])
    y = np.array([p["rent"] for p in pts])
    color = KIND_COLORS[kind]
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=x, y=y, mode="markers", name="ตัวอย่างจริง",
                             marker={"color": color, "size": 9}))
    model = result["models"].get(kind)
    if model is not None and len(x):
        grid = np.linspace(float(x.min()), float(x.max()), 80)
        fig.add_trace(go.Scatter(x=grid, y=model["r0"] * np.exp(-model["lam"] * grid),
                                 mode="lines", name=f"fit (R² = {model['r2']:.2f})",
                                 line={"color": color, "width": 2}))
    fig.update_layout(margin={"l": 10, "r": 10, "t": 30, "b": 10}, height=340,
                      xaxis_title=f"ระยะ ({result['units'].get(kind, '')})",
                      yaxis_title=unit_label, legend={"orientation": "h"})
    if log_y:
        fig.update_yaxes(type="log")
    return fig


def _render_results(result: Dict[str, Any], unit_label: str) -> None:
    st.subheader("📊 เทียบระยะ 4 แบบ")
    for warning in result["warnings"]:
        st.warning(warning)
    if not result["ranking"]:
        st.info("ยังไม่มีโมเดลที่ fit ได้ — เพิ่มตัวอย่างราคาที่อยู่คนละระยะกัน")
        return

    best = result["ranking"][0]
    crit = "LOO-RMSE ต่ำสุด" if result["criterion"] == "loo_rmse" else "R² สูงสุด"
    st.success(f"ระยะที่อธิบายราคาได้ดีที่สุดบนตัวอย่างชุดนี้: **{KIND_LABELS[best]}** ({crit}) · "
               f"n = {result['n_used']}/{result['n_input']}")
    table = models_table(result)
    st.dataframe(table, hide_index=True, width="stretch", column_config={
        "λ (ต่อหน่วย)": st.column_config.NumberColumn(format="%.4f"),
        "R₀": st.column_config.NumberColumn(format="%.1f"),
        "R²": st.column_config.NumberColumn(format="%.3f"),
        "Adj R²": st.column_config.NumberColumn(format="%.3f"),
        "LOO-RMSE (ln)": st.column_config.NumberColumn(format="%.3f"),
        "AICc": st.column_config.NumberColumn(format="%.1f"),
    })
    st.caption("λ อยู่คนละหน่วยตามชนิดระยะ จึง **เทียบกันตรงๆ ไม่ได้** — ให้เทียบด้วย LOO-RMSE / R² / AICc "
               "(ตัวแปรตาม ln ราคา ชุดตัวอย่างเดียวกัน)")

    log_y = st.checkbox("แกนราคาแบบ log", value=False, key="laora_logy")
    kinds = [k for k in core.DISTANCE_KINDS if k in result["units"]]
    for tab, kind in zip(st.tabs([KIND_LABELS[k] for k in kinds]), kinds):
        with tab:
            st.plotly_chart(_scatter_figure(result, kind, unit_label, log_y), width="stretch")

    with st.expander("📏 โปรไฟล์ราคาเฉลี่ยรายช่วงระยะ (เหมือนวัดทุก 500 ม. ของ Laora)"):
        kind = st.selectbox("ชนิดระยะ", kinds, format_func=lambda k: KIND_LABELS[k],
                            index=kinds.index("metric") if "metric" in kinds else 0,
                            key="laora_bin_kind")
        size = st.number_input(f"ความกว้างช่วง ({result['units'][kind]})", min_value=0.05,
                               value=float(DEFAULT_BIN[kind]), step=0.05, key=f"laora_bin_{kind}")
        profile = core.binned_profile([p[kind] for p in result["points"]],
                                      [p["rent"] for p in result["points"]], float(size))
        st.dataframe(pd.DataFrame(profile).rename(columns={
            "from": "จาก", "to": "ถึง", "n": "จำนวนจุด", "mean_rent": "ราคาเฉลี่ย"}),
            hide_index=True, width="stretch")

    with st.expander("ข้อมูลรายจุด"):
        st.dataframe(pd.DataFrame(result["points"]), hide_index=True, width="stretch")


# ============================================================================
# MAIN
# ============================================================================

def main() -> None:
    st.set_page_config(**PAGE_CONFIG)
    st.title("🧭 Rent Gradient × Space Syntax")
    st.caption("Bid-Rent R(d) = R₀·e^(−λ·d) โดยให้ d เป็นระยะตามโครงข่ายถนน "
               "(Metric / Topological / Angular) เทียบกับเส้นตรง — ตามแนวคิดงานของ Laora · "
               "หน้านี้แยกจาก Rent_Gradient.py")

    with st.sidebar:
        _sidebar_study_area()
        anchor = _sidebar_anchor()
        edited = _sidebar_samples()
        options = _sidebar_options()
        net = st.session_state.get(K_NET)
        run = st.button("🧮 เทียบโมเดล", type="primary", width="stretch",
                        disabled=net is None or anchor is None)

    net = st.session_state.get(K_NET)
    meta = st.session_state.get(K_META)
    if net is None:
        st.info("เริ่มจากแถบด้านข้าง: โหลดโครงข่ายถนน → เลือกจุดยึด → ใส่ตัวอย่างราคา")
        return

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("โหนด", f"{net.n_nodes:,}")
    c2.metric("segment", f"{net.n_segments:,}")
    c3.metric("รัศมี (m)", f"{meta['radius']:,}")
    c4.metric("แหล่งข้อมูล", meta["source"].split(" (")[0])
    st.caption(f"โครงข่าย: {meta['source']} · {NETWORK_TYPES[meta['network']]}")

    if anchor is not None:
        st.caption(f"จุดยึด: {len(anchor.node_idx)} โหนด · {len(anchor.seg_idx)} segment "
                   f"({'แนวถนน' if anchor.is_line else 'จุด'})")
    if run and anchor is not None:
        samples = [{"lat": r["lat"], "lon": r["lon"], "rent": r["rent"]}
                   for _, r in edited.iterrows()]
        st.session_state[K_RESULT] = core.compare_distance_models(
            samples, net, anchor, topological_turn_deg=options["turn"],
            include_offset=options["offset"])

    result = st.session_state.get(K_RESULT)
    if result is not None:
        _render_results(result, st.session_state.get("laora_unit", "ราคา"))


if __name__ == "__main__":
    main()
