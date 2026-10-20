"""
Rent Gradient (new v2) — กองเลเยอร์บนแผนที่เดียว: Simple · Stable · Fast
=======================================================================
ต่อยอดจาก ``Rent_Gradient_new.py`` (ไม่แก้ไฟล์เดิมทั้งสอง) โดยเปลี่ยนวิธีวาดแผนที่จากการเรียงบล็อก ``if`` ต่อกัน
เป็น "เลเยอร์ = ฟังก์ชันธรรมดา 1 ตัว" ใน list เดียว

    LAYERS = (("rent_rings", "…", layer_rent_rings),      # ล่าง
              ("space_syntax", "…", layer_space_syntax))  # บน

เพิ่มเลเยอร์ใหม่ = เขียน 1 ฟังก์ชัน + เพิ่ม 1 บรรทัดใน ``LAYERS`` (ปุ่มเปิด/ปิด, legend, การจับ error ได้เอง)

Simple   เลเยอร์ ``fn(ctx) -> (folium element, legend html | None) | None``; ไม่มี framework
Stable   เลเยอร์ที่ error ถูกจับทีละเลเยอร์ (แผนที่ไม่ล้ม) · เลเยอร์ที่ไม่มีข้อมูลคืน ``None`` แล้วถูกซ่อน
         ถ้าโหลด ``Rent_Gradient_new.py`` ไม่ได้/ขาดฟังก์ชันที่ใช้ → แจ้ง error ชัดเจนแล้วหยุด ไม่ crash
Fast     วิเคราะห์ครั้งเดียว; ข้อมูลที่ใช้สร้างเลเยอร์ (GeoJSON, สี, อันดับ) ถูก cache แบบ LRU 8 รายการ
         เปิด/ปิดเลเยอร์หรือเลื่อนแผนที่จึงไม่คำนวณซ้ำ; วาดแบบ canvas และไม่ rerun ตอนเลื่อนแผนที่

โครงข่ายถนน/ผลวิเคราะห์ใช้ session key ชุดเดียวกับ ``Rent_Gradient_new`` (``rgn_*``) จึงโหลดครั้งเดียวใช้ได้ทั้งสองหน้า
เลเยอร์ราคา (rent_rings) อ่านผลจากหน้า ``Rent_Gradient`` ใน session เดียวกันแบบ read-only
"""

from __future__ import annotations

import hashlib
import importlib.util
import sys
from collections import OrderedDict
from dataclasses import dataclass
from html import escape
from pathlib import Path
from typing import Any, Callable, Dict, List, MutableMapping, Optional, Sequence, Tuple

import numpy as np
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
CORE_PAGE = ROOT / "pages" / "Rent_Gradient_new.py"
CORE_MODULE = "rent_gradient_new_for_v2"

# สิ่งที่หน้านี้ต้องใช้จาก Rent_Gradient_new.py — ขาดข้อใดข้อหนึ่งจะแจ้งชื่อที่หาย ไม่ปล่อยให้ crash กลางทาง
REQUIRED_CORE: Tuple[str, ...] = (
    "scale_scores", "segments_geojson", "base_anchor", "radius_key", "radius_label",
    "gradient_css", "MEASURES", "SCALE_MODES", "MAP_STYLES", "K_NET", "K_META", "K_RESULT", "K_AUTORUN",
    "_sidebar_study_area", "_sidebar_analysis", "_sidebar_style", "_run_analysis", "_display_mask",
    "_summary_row", "_display_columns", "_top_rows",
)

PAGE_CONFIG: Dict[str, Any] = {"page_title": "Rent Gradient — Layers (v2)", "page_icon": "🧱", "layout": "wide"}
CACHE_LIMIT = 8
K_RUN, K_CACHE = "rgv2_run", "rgv2_cache"
RENT_STATE_KEY = "rent_gradient_data"          # ผลของหน้า Rent_Gradient (อ่านอย่างเดียว)


# ============================================================================
# SECTION 1: CORE LOADER + CACHE (ไม่เรียก st.* ยกเว้นตอนอ่าน session ใน main)
# ============================================================================

def load_core(path: Path = CORE_PAGE) -> Tuple[Optional[Any], Optional[str]]:
    """``(module, error)`` of ``Rent_Gradient_new.py``; exactly one of them is ``None``."""
    name = CORE_MODULE if path == CORE_PAGE else f"{CORE_MODULE}_{abs(hash(str(path)))}"
    module = sys.modules.get(name)
    if module is None:
        if not path.exists():
            return None, f"ไม่พบไฟล์ {path.name} (ถูกลบหรือเปลี่ยนชื่อ?) — หน้านี้ต้องใช้ไฟล์นั้น"
        try:
            spec = importlib.util.spec_from_file_location(name, path)
            module = importlib.util.module_from_spec(spec)
            sys.modules[name] = module
            spec.loader.exec_module(module)
        except Exception as exc:
            sys.modules.pop(name, None)
            return None, f"โหลด {path.name} ไม่สำเร็จ: {type(exc).__name__}: {exc}"
    missing = [n for n in REQUIRED_CORE if not hasattr(module, n)]
    if missing:
        return None, f"{path.name} ไม่มีสิ่งที่หน้านี้ใช้: {', '.join(missing)}"
    return module, None


def cache_get_or_build(store: MutableMapping, key: Any, builder: Callable[[], Any], limit: int = CACHE_LIMIT) -> Any:
    """Tiny LRU: a hit never calls ``builder``; the oldest entry goes first once ``limit`` is exceeded."""
    if key in store:
        store.move_to_end(key)
        return store[key]
    value = store[key] = builder()
    while len(store) > limit:
        store.popitem(last=False)
    return value


# ============================================================================
# SECTION 2: LAYER CONTEXT + LAYERS (ไม่เรียก st.*)
# ============================================================================

@dataclass(frozen=True)
class LayerContext:
    """Everything a layer may read. Layers never write to it."""

    core: Any                          # module Rent_Gradient_new
    net: Any
    result: Any
    mask: np.ndarray
    mask_key: str
    run_id: int
    measure: str                       # "integration" | "choice"
    rkey: str                          # radius key, e.g. "800" or "n"
    style: Dict[str, Any]              # palette, scale, thick, basemap, top_n
    meta: Dict[str, Any]
    rent_data: Optional[Dict[str, Any]]
    cache: MutableMapping

    def cached(self, name: str, *parts: Any, builder: Callable[[], Any]) -> Any:
        return cache_get_or_build(self.cache, (name, self.run_id, self.mask_key, *parts), builder)


def mask_digest(mask: np.ndarray) -> str:
    return hashlib.md5(np.packbits(np.asarray(mask, dtype=bool)).tobytes()).hexdigest()[:12]


def _legend_block(title: str, body_html: str) -> str:
    return (f'<div style="margin-top:6px;"><div style="font-weight:600; margin-bottom:3px;">{escape(title)}</div>'
            f"{body_html}</div>")


def _gradient_block(core: Any, title: str, palette: str, low: str, high: str, note: str) -> str:
    bar = (f'<div style="height:12px; border-radius:3px; background:{core.gradient_css(palette)};"></div>'
           '<div style="display:flex; justify-content:space-between; margin-top:2px;">'
           f"<span>🔵 {escape(low)}</span><span>{escape(high)} 🔴</span></div>"
           f'<div style="margin-top:3px; color:#555;">{escape(note)}</div>')
    return _legend_block(title, bar)


def _space_syntax_data(ctx: LayerContext) -> Dict[str, Any]:
    """The expensive part of the Space Syntax layer (scale, colours, GeoJSON, ranking): cached."""
    core, res, style = ctx.core, ctx.result, ctx.style
    values = res.integration[ctx.rkey] if ctx.measure == "integration" else res.choice_norm[ctx.rkey]
    nc = res.nc[ctx.rkey]
    scaled = core.scale_scores(values, style["scale"], ctx.mask)
    columns = core._display_columns(ctx.net, scaled, values, nc, style["palette"], style["thick"])
    columns["label"] = [escape(text) for text in columns["label"]]      # OSM names reach tooltips as HTML
    top = core._top_rows(ctx.net, scaled, values, nc, ctx.mask, style["top_n"]) if style["top_n"] else []
    for row in top:
        row["label"] = escape(str(row["label"]))
    return {
        "geojson": core.segments_geojson(ctx.net, columns, ctx.mask, precision=5),
        "top": top, "low": scaled["ticks"][0][1], "high": scaled["ticks"][-1][1],
    }


def layer_space_syntax(ctx: LayerContext) -> Optional[Tuple[Any, Optional[str]]]:
    """Road segments coloured blue → red by accessibility (Integration) or through-movement (Choice)."""
    import folium

    style, core = ctx.style, ctx.core
    data = ctx.cached("space_syntax", ctx.measure, ctx.rkey, style["scale"], style["palette"], style["thick"],
                      style["top_n"], builder=lambda: _space_syntax_data(ctx))
    if not data["geojson"]["features"]:
        return None
    group = folium.FeatureGroup(name="Space Syntax (ไล่สีตามคะแนน)")
    folium.GeoJson(
        data["geojson"],
        style_function=lambda f: {"color": f["properties"]["color"], "weight": f["properties"]["weight"],
                                  "opacity": 0.95},
        highlight_function=lambda f: {"weight": f["properties"]["weight"] + 3, "opacity": 1.0},
        tooltip=folium.GeoJsonTooltip(
            fields=["label", "score", "value", "nc"],
            aliases=["ถนน:", "คะแนน (0–100):", "ค่าดัชนี:", "segment ในรัศมี:"], localize=True, sticky=True),
    ).add_to(group)
    for row in data["top"]:
        folium.Marker(
            [row["lat"], row["lon"]], tooltip=f"#{row['rank']} · คะแนน {row['score']:.1f} · {row['label']}",
            icon=folium.DivIcon(html=(
                '<div style="width:22px;height:22px;line-height:20px;border-radius:50%;text-align:center;'
                'background:#fff;color:#b00020;border:2px solid #b00020;font:700 11px system-ui;">'
                f"{row['rank']}</div>"), icon_size=(22, 22), icon_anchor=(11, 11)),
        ).add_to(group)
    title = f"{core.MEASURES[ctx.measure]['title']} (คะแนน 0–100)"
    note = f"{core.SCALE_MODES[style['scale']]} · {core.radius_label(_radius_value(ctx))}"
    return group, _gradient_block(core, title, style["palette"], f"ต่ำ {data['low']:.2f}",
                                  f"{data['high']:.2f} สูง", note)


def _radius_value(ctx: LayerContext) -> Optional[float]:
    return next((r for r in ctx.result.radii if ctx.core.radius_key(r) == ctx.rkey), None)


def layer_rent_rings(ctx: LayerContext) -> Optional[Tuple[Any, Optional[str]]]:
    """Rent Gradient rings computed on the Rent_Gradient page (same session). Hidden when absent."""
    import folium

    data = ctx.rent_data
    rings = data.get("rings_geojson") if isinstance(data, dict) and "error" not in data else None
    features = rings.get("features") if isinstance(rings, dict) else None
    if not features:
        return None
    safe = {"type": "FeatureCollection", "features": [
        {**f, "properties": {k: escape(v) if isinstance(v, str) else v for k, v in (f.get("properties") or {}).items()}}
        for f in features]}
    present = (safe["features"][0]["properties"])
    fields = [(k, a) for k, a in (("band", "ระยะจาก CBD:"), ("rent_label", "ค่าเช่าคาดการณ์:")) if k in present]
    group = folium.FeatureGroup(name="Rent Gradient Rings")
    folium.GeoJson(
        safe,
        style_function=lambda f: {"fillColor": f["properties"].get("color", "#3987e5"),
                                  "color": f["properties"].get("color", "#3987e5"), "weight": 1,
                                  "fillOpacity": 0.16},
        tooltip=folium.GeoJsonTooltip(fields=[k for k, _ in fields], aliases=[a for _, a in fields],
                                      localize=True) if fields else None,
    ).add_to(group)
    model = data.get("model") if isinstance(data.get("model"), dict) else {}
    unit = "ดัชนี" if model.get("is_index") else str(model.get("unit", ""))
    return group, _legend_block("Rent Gradient (วงแหวนราคา)", f"<div>CBD → ขอบ ({escape(unit)})</div>")


# เรียงล่าง → บน: วงแหวนราคาอยู่ใต้เส้นถนน
LAYERS: Tuple[Tuple[str, str, Callable[[LayerContext], Optional[Tuple[Any, Optional[str]]]]], ...] = (
    ("rent_rings", "Rent rings (ราคา)", layer_rent_rings),
    ("space_syntax", "Space Syntax", layer_space_syntax),
)


def _bounds(ctx: LayerContext) -> Tuple[float, float, float, float]:
    idx = np.flatnonzero(ctx.mask)
    pts = np.concatenate([ctx.net.seg_lonlat[i] for i in idx]) if len(idx) else np.array([ctx.net.origin[::-1]])
    return float(pts[:, 1].min()), float(pts[:, 1].max()), float(pts[:, 0].min()), float(pts[:, 0].max())


def render_layers(
    ctx: LayerContext, enabled: Sequence[str], layers: Optional[Sequence[Tuple[str, str, Callable]]] = None,
) -> Tuple[Any, List[str], List[str]]:
    """Build the map: ``(folium map, drawn layer ids, warnings)``. A failing layer only adds a warning."""
    import folium
    from branca.element import MacroElement, Template
    from folium.plugins import Fullscreen

    style = ctx.core.MAP_STYLES[ctx.style["basemap"]]
    south, north, west, east = _bounds(ctx)
    fmap = folium.Map(location=[(south + north) / 2, (west + east) / 2], zoom_start=14, tiles=style["tiles"],
                      attr=style["attr"], prefer_canvas=True, control_scale=True)
    if style["tiles"] is None:
        fmap.get_root().header.add_child(folium.Element(
            "<style>.leaflet-container{background:#000 !important;}</style>"))
    fmap.fit_bounds([[south, west], [north, east]])

    drawn: List[str] = []
    warnings: List[str] = []
    legends: List[str] = []
    for layer_id, label, build in (LAYERS if layers is None else layers):
        if layer_id not in enabled:
            continue
        try:
            out = build(ctx)
        except Exception as exc:                          # one broken layer must not take the map down
            warnings.append(f"{label}: {type(exc).__name__}: {exc}")
            continue
        if out is None:
            continue
        element, legend = out
        element.add_to(fmap)
        drawn.append(layer_id)
        if legend:
            legends.append(legend)

    anchor = ctx.core.base_anchor()
    if anchor is not None:
        folium.Marker([anchor["lat"], anchor["lon"]], tooltip=f"จุดยึด CBD — {escape(str(anchor['source']))}",
                      icon=folium.Icon(color="darkblue", icon="building", prefix="fa")).add_to(fmap)
    Fullscreen(position="topleft").add_to(fmap)
    folium.LayerControl().add_to(fmap)
    if legends:
        html = ('<div style="position:fixed; bottom:42px; left:12px; z-index:9999; width:230px; '
                'background:rgba(255,255,255,0.93); border:1px solid rgba(11,11,11,0.10); border-radius:8px; '
                'padding:2px 10px 8px; font-size:12px; color:#0b0b0b; box-shadow:0 1px 4px rgba(0,0,0,0.18); '
                'line-height:1.45; font-family:system-ui, -apple-system, sans-serif;">' + "".join(legends) + "</div>")
        macro = MacroElement()
        macro._template = Template("{% macro html(this, kwargs) %}" + html + "{% endmacro %}")
        fmap.get_root().add_child(macro)
    return fmap, drawn, warnings


# ============================================================================
# SECTION 3: UI (st.* allowed)
# ============================================================================

def main() -> None:
    st.set_page_config(**PAGE_CONFIG)
    st.title("🧱 Rent Gradient — กองเลเยอร์บนแผนที่เดียว (v2)")
    core, error = load_core()
    if core is None:
        st.error(error)
        return
    layer_ids = [layer_id for layer_id, _, _ in LAYERS]
    labels = {layer_id: label for layer_id, label, _ in LAYERS}
    with st.sidebar:
        core._sidebar_study_area()
        params = core._sidebar_analysis()
        style = core._sidebar_style()
        enabled = st.multiselect("เลเยอร์บนแผนที่", layer_ids, default=layer_ids, key="rgv2_layers",
                                 format_func=labels.get, help="เปิด/ปิดได้ทันที โดยไม่คำนวณใหม่")
        net = st.session_state.get(core.K_NET)
        run = st.button("🧮 วิเคราะห์ Space Syntax", type="primary", width="stretch", disabled=net is None,
                        key="rgv2_run_btn")

    net, meta = st.session_state.get(core.K_NET), st.session_state.get(core.K_META)
    if net is None:
        st.info("เริ่มจากแถบด้านข้าง: ① โหลดโครงข่ายถนน (หรือกด 🧪 ตัวอย่างเชียงของ) → ② 🧮 วิเคราะห์ Space Syntax")
        return
    before = st.session_state.get(core.K_RESULT)
    if run or st.session_state.pop(core.K_AUTORUN, False):
        core._run_analysis(net, params)
    result = st.session_state.get(core.K_RESULT)
    if result is not before:                                   # a new analysis invalidates cached layer data
        st.session_state[K_RUN] = st.session_state.get(K_RUN, 0) + 1
    mask = core._display_mask(net, meta)
    core._summary_row(net, meta, mask, result)
    if result is None:
        st.info("กด 🧮 วิเคราะห์ Space Syntax ที่แถบด้านข้างเพื่อคำนวณและไล่สี")
        return
    if result.meta.get("params") != params:
        st.warning("ตั้งค่า Space Syntax เปลี่ยนไปจากที่คำนวณไว้ — กด 🧮 วิเคราะห์ เพื่ออัปเดตผล")

    measures = ["integration"] + (["choice"] if result.with_choice else [])
    keys = [core.radius_key(r) for r in result.radii]
    for widget_key, valid in (("rgv2_measure", measures), ("rgv2_radius", keys)):
        if st.session_state.get(widget_key, valid[0]) not in valid:        # options changed with a new analysis
            st.session_state.pop(widget_key, None)
    c1, c2 = st.columns([1.4, 1])
    measure = c1.radio("ตัวชี้วัด", measures, horizontal=True, key="rgv2_measure",
                       format_func=lambda m: f"{core.MEASURES[m]['title']} — {core.MEASURES[m]['thai']}")
    rkey = c2.selectbox("รัศมีที่แสดง", keys, index=keys.index("n") if "n" in keys else len(keys) - 1,
                        key="rgv2_radius", format_func=lambda k: core.radius_label(
                            next(r for r in result.radii if core.radius_key(r) == k)))
    cache = st.session_state.setdefault(K_CACHE, OrderedDict())
    ctx = LayerContext(core=core, net=net, result=result, mask=mask, mask_key=mask_digest(mask),
                       run_id=st.session_state.get(K_RUN, 0), measure=measure, rkey=rkey, style=style,
                       meta=meta, rent_data=st.session_state.get(RENT_STATE_KEY), cache=cache)
    fmap, drawn, warnings = render_layers(ctx, enabled)
    for text in warnings:
        st.warning(f"เลเยอร์ทำงานผิดพลาด (ข้ามไป): {text}")
    if "rent_rings" in enabled and "rent_rings" not in drawn:
        st.caption("ℹ️ ยังไม่มีผล Rent Gradient — คำนวณในหน้า Rent_Gradient ก่อน (session เดียวกัน) วงแหวนราคาจึงจะขึ้น")
    if not drawn:
        st.info("ยังไม่ได้เปิดเลเยอร์ที่มีข้อมูล — เลือกเลเยอร์ที่แถบด้านข้าง")
        return
    from streamlit_folium import st_folium

    st_folium(fmap, height=720, use_container_width=True, key="rgv2_map", returned_objects=[])
    st.caption("เลเยอร์ที่แสดง: " + " · ".join(labels[i] for i in drawn))


if __name__ == "__main__":
    main()
