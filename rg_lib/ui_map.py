"""UI — the Folium map: base layers, WMS overlays, rent rings/nodes, markers, legend.

Definitions are cut verbatim from pages/Rent_Gradient.py (see tests/test_rg_v2_equivalence.py).
"""


import folium
import streamlit as st
from branca.element import MacroElement, Template
from folium.plugins import Fullscreen, MeasureControl, MousePosition
from streamlit_folium import st_folium
from typing import Any, Dict, List, Optional

from .config import DEFAULT_CONFIG, EVIDENCE_SCHEMA, LONGDO_WMS_URL, MAP_STYLES, MARKER_COLORS, RENT_CONFIG, RENT_RAMP
from .geo import get_border_color, get_fill_color, haversine_km
from .rent import format_rent_value, predict_rent
from .state import StateManager
from .controllers import _parse_kml_to_geojson


def _add_wms_layer(
    m: folium.Map,
    layers: str,
    name: str,
    show: bool,
    opacity: float = 1.0,
) -> None:
    """Helper — add a Longdo WMS overlay to a Folium map."""
    folium.WmsTileLayer(
        url=LONGDO_WMS_URL,
        layers=layers,
        name=name,
        fmt="image/png",
        transparent=True,
        version="1.1.1",
        attr=f"{name} / Longdo Map",
        show=show,
        opacity=opacity,
    ).add_to(m)


def _legend_swatch_row(color_css: str, label: str, extra_style: str = "") -> str:
    """HTML แถวเดียวของ legend: สี่เหลี่ยมสี + ป้ายข้อความ."""
    return (
        '<div style="display:flex; align-items:center; gap:6px; margin:1px 0;">'
        f'<span style="display:inline-block; width:14px; height:14px; border-radius:3px; '
        f'background:{color_css}; {extra_style}"></span>'
        f'<span>{label}</span></div>'
    )


def _add_map_legend(m: folium.Map) -> None:
    """เพิ่มกล่อง Legend มุมล่างซ้าย อธิบายทุกเลเยอร์ที่กำลังแสดงอยู่."""
    clrs = StateManager.get_colors()
    rows: List[str] = []

    if StateManager.get_isochrone_data():
        rows.append('<div style="font-weight:600; margin-bottom:2px;">เวลาเดินทาง</div>')
        rows.append(_legend_swatch_row(clrs["step1"], "≤ 10 นาที"))
        rows.append(_legend_swatch_row(clrs["step2"], "≤ 20 นาที"))
        rows.append(_legend_swatch_row(clrs["step3"], "≤ 30 นาที"))
        rows.append(_legend_swatch_row(clrs["step4"], "> 30 นาที"))

    if StateManager.get_intersection_data():
        rows.append(_legend_swatch_row(
            "#FFD700", "CBD Zone", "border:2px dashed #FF8C00;"
        ))

    net_data = StateManager.get_network_data()
    if net_data and st.session_state.show_golden_spots and net_data.get("golden_spots"):
        rows.append(_legend_swatch_row(
            "#FFD60A", "💎 Golden Spot", "border:2px solid #8C6A00; border-radius:50%;"
        ))

    rent_data = StateManager.get_rent_data()
    if rent_data and "error" not in rent_data and st.session_state.show_rent_rings:
        model = rent_data["model"]
        unit = "ดัชนี" if model["is_index"] else model["unit"]
        rows.append(
            '<div style="font-weight:600; margin:4px 0 2px;">Rent Gradient</div>'
            '<div style="display:flex; align-items:center; gap:6px;">'
            f'<span style="display:inline-block; width:56px; height:10px; border-radius:3px; '
            f'background:linear-gradient(90deg, {RENT_RAMP[-1]}, {RENT_RAMP[0]});"></span>'
            f'<span>CBD → ขอบ ({unit})</span></div>'
        )

    if not rows:
        return

    html = (
        '<div style="position:fixed; bottom:18px; left:12px; z-index:9999; '
        'background:rgba(255,255,255,0.93); border:1px solid rgba(11,11,11,0.10); '
        'border-radius:8px; padding:8px 10px; font-size:12px; color:#0b0b0b; '
        'box-shadow:0 1px 4px rgba(0,0,0,0.18); line-height:1.45; '
        'font-family:system-ui, -apple-system, sans-serif;">'
        + "".join(rows)
        + "</div>"
    )
    legend = MacroElement()
    legend._template = Template(
        "{% macro html(this, kwargs) %}" + html + "{% endmacro %}"
    )
    m.get_root().add_child(legend)


def _stability_popup(result: Dict[str, Any]) -> str:
    stability = result.get("stability")
    if not stability:
        return ""
    return (f"<br>Stability: {stability['level']} "
            f"(max drift {stability['max_drift_m']:.0f} m, indicative)")


def render_map() -> Optional[Dict[str, Any]]:
    """Build and display the Folium map. Returns the ``st_folium`` output dict."""
    style_conf = MAP_STYLES[StateManager.get_map_style_name()]
    markers = StateManager.get_markers()
    center = (
        [markers[-1]["lat"], markers[-1]["lng"]]
        if markers
        else [DEFAULT_CONFIG["LAT"], DEFAULT_CONFIG["LON"]]
    )
    automated = st.session_state.get(StateManager.K_AUTO_ANCHOR)
    automated_closeness = st.session_state.get(StateManager.K_AUTO_ANCHOR_CLOSENESS)
    if automated:
        center = [automated["anchor"]["lat"], automated["anchor"]["lon"]]
    elif automated_closeness:
        center = [automated_closeness["anchor"]["lat"], automated_closeness["anchor"]["lon"]]

    m = folium.Map(
        location=center,
        zoom_start=14,
        tiles=style_conf["tiles"],
        attr=style_conf["attr"],
    )
    if automated:
        anchor = automated["anchor"]
        folium.Marker(
            [anchor["lat"], anchor["lon"]], tooltip="Automated CBD Anchor",
            popup=folium.Popup(f"<b>Automated CBD Anchor</b><br>Score: {anchor['score']:.4f}"
                               f"<br>Junctions / 500 m: {anchor['junction_count']}"
                               + _stability_popup(automated), max_width=280),
            icon=folium.Icon(color="darkblue", icon="building", prefix="fa"),
        ).add_to(m)
        boundary_layer = folium.FeatureGroup(name="Automated Anchor study boundary", show=False)
        folium.Circle(automated["study_center"], radius=automated["study_radius_m"],
                      color="#184f95", fill=False, tooltip="Study boundary").add_to(boundary_layer)
        boundary_layer.add_to(m)

    if automated_closeness:
        anchor = automated_closeness["anchor"]
        folium.Marker(
            [anchor["lat"], anchor["lon"]],
            tooltip="Automated CBD Anchor — Closeness 100%",
            popup=folium.Popup(
                f"<b>Automated CBD Anchor — Closeness 100%</b>"
                f"<br>Closeness norm: {anchor['closeness_norm']:.6f}"
                f"<br>Closeness: {anchor['closeness']:.8f} 1/m"
                f"<br>Degree: {anchor['degree']} (diagnostic)"
                f"<br>Junctions / 500 m: {anchor['junction_count']} (diagnostic)"
                + _stability_popup(automated_closeness),
                max_width=320,
            ),
            icon=folium.Icon(color="green", icon="bullseye", prefix="fa"),
        ).add_to(m)

    evidence = st.session_state.get(StateManager.K_AUTO_ANCHOR_EVIDENCE)
    if evidence and evidence.get("schema") == EVIDENCE_SCHEMA and evidence.get("evidence_anchor"):
        anchor, confidence = evidence["evidence_anchor"], evidence["confidence"]
        folium.Marker(
            [anchor["lat"], anchor["lon"]], tooltip="Automated CBD Anchor — Evidence",
            popup=folium.Popup(
                f"<b>Automated CBD Anchor — Evidence</b><br>Confidence: {confidence['level']}"
                f"<br>Cluster score: {anchor['score']:.3f}"
                f"<br>Parcel coverage: {anchor['coverage']:.0%}"
                + "".join(f"<br>• {reason}" for reason in confidence["reasons"]), max_width=360),
            icon=folium.Icon(color="purple", icon="star", prefix="fa"),
        ).add_to(m)
        peak = evidence["plan"].get("peak")
        zone_layer = folium.FeatureGroup(name="Peak colour zone (ผังสีสูงสุด)", show=False)
        zone_color = "#d62828" if not peak else "#%02x%02x%02x" % tuple(peak["rgb"])
        for zone in evidence["plan"].get("zones", []):
            if zone.get("polygon"):
                folium.GeoJson(
                    {"type": "Feature", "properties": {}, "geometry": zone["polygon"]},
                    style_function=lambda _f, c=zone_color: {"color": c, "weight": 2, "fillColor": c,
                                                             "fillOpacity": 0.25, "dashArray": "6"},
                    tooltip=f"ผังสีสูงสุด{(' ' + peak['name']) if peak else ''} ≈ {zone['area_km2']:.2f} ตร.กม.",
                ).add_to(zone_layer)
        zone_layer.add_to(m)
        cluster_layer = folium.FeatureGroup(name="Parcel clusters (แปลงถี่)", show=False)
        for cluster in evidence.get("clusters", []):
            if cluster.get("polygon"):
                folium.GeoJson(
                    {"type": "Feature", "properties": {}, "geometry": cluster["polygon"]},
                    style_function=lambda _f, top=(cluster["rank"] == 1): {
                        "color": "#7b2cbf", "weight": 3 if top else 1, "fillColor": "#7b2cbf",
                        "fillOpacity": 0.45 if top else 0.2},
                    tooltip=(f"#{cluster['rank']} cluster แปลงเล็กถี่ · คะแนน {cluster['score']:.2f} · "
                             f"{cluster['area_ha']:,.0f} เฮกตาร์"),
                ).add_to(cluster_layer)
        cluster_layer.add_to(m)

    # ---- เครื่องมือสำรวจทำเล ----
    Fullscreen(position="topleft").add_to(m)
    MeasureControl(
        position="topleft",
        primary_length_unit="kilometers",
        secondary_length_unit="meters",
        primary_area_unit="sqmeters",
    ).add_to(m)
    MousePosition(
        position="bottomright",
        separator=" , ",
        num_digits=5,
        prefix="พิกัด:",
    ).add_to(m)

    # ---- Traffic overlay ----
    if st.session_state.show_traffic:
        folium.TileLayer(
            tiles="https://mt1.google.com/vt?lyrs=h,traffic&x={x}&y={y}&z={z}",
            attr="Google Traffic",
            name="Google Traffic",
            overlay=True,
        ).add_to(m)

    # ---- Rent Gradient Layers (วาดก่อนเพื่อให้อยู่ใต้เลเยอร์วิเคราะห์อื่น) ----
    rent_data = StateManager.get_rent_data()
    rent_model = None
    rent_anchor = None
    if rent_data and "error" not in rent_data:
        rent_model = rent_data["model"]
        rent_anchor = rent_data["anchor"]

        if st.session_state.show_rent_rings and rent_data.get("rings_geojson"):
            ring_feats = rent_data["rings_geojson"].get("features") or []
            has_nodes_label = bool(
                ring_feats and "nodes_label" in ring_feats[0].get("properties", {})
            )
            tooltip_fields = ["band", "rent_label"]
            tooltip_aliases = ["ระยะจาก CBD:", "ค่าเช่าคาดการณ์:"]
            if has_nodes_label:
                tooltip_fields.append("nodes_label")
                tooltip_aliases.append("โหนด Network:")
            folium.GeoJson(
                rent_data["rings_geojson"],
                name="Rent Gradient Rings",
                style_function=lambda x: {
                    "fillColor": x["properties"]["color"],
                    "color": x["properties"]["color"],
                    "weight": 1,
                    "fillOpacity": RENT_CONFIG["ring_fill_opacity"],
                },
                tooltip=folium.GeoJsonTooltip(
                    fields=tooltip_fields,
                    aliases=tooltip_aliases,
                    localize=True,
                ),
            ).add_to(m)

        if st.session_state.show_rent_nodes and rent_data.get("rent_nodes_geojson"):
            folium.GeoJson(
                rent_data["rent_nodes_geojson"],
                name="Rent Heat (Nodes)",
                marker=folium.CircleMarker(),
                style_function=lambda x: {
                    "fillColor": x["properties"]["color"],
                    "color": x["properties"]["color"],
                    "weight": 1,
                    "radius": 3,
                    "fillOpacity": 0.85,
                },
                tooltip=folium.GeoJsonTooltip(
                    fields=["rent"],
                    aliases=["ค่าเช่าคาดการณ์:"],
                    localize=True,
                ),
            ).add_to(m)

        # Automated marker is already present, even when Rent layers are hidden.
        if not automated:
            folium.Marker(
                [rent_anchor["lat"], rent_anchor["lon"]],
                tooltip=f"จุดยึด CBD — {rent_anchor['source']}",
                popup=folium.Popup(
                    f"<b>CBD Anchor</b><br>{rent_anchor['source']}<br>"
                    f"R₀ = {format_rent_value(rent_model['r0'], rent_model)}",
                    max_width=260,
                ),
                icon=folium.Icon(color="darkblue", icon="building", prefix="fa"),
            ).add_to(m)

    # ---- Network Analysis Layers ----
    net_data = StateManager.get_network_data()
    if net_data and "error" not in net_data:
        # Edges (Betweenness)
        if st.session_state.show_betweenness and net_data.get("edges"):
            folium.GeoJson(
                net_data["edges"],
                name="Road Betweenness",
                style_function=lambda x: {
                    "color": x["properties"]["color"],
                    "weight": x["properties"]["stroke_weight"],
                    "opacity": 0.8,
                },
                tooltip=folium.GeoJsonTooltip(
                    fields=["betweenness"],
                    aliases=["Betweenness Score:"],
                    localize=True,
                ),
            ).add_to(m)

        # Nodes (Closeness)
        if st.session_state.show_closeness and net_data.get("nodes"):
            folium.GeoJson(
                net_data["nodes"],
                name="Node Integration",
                marker=folium.CircleMarker(),
                style_function=lambda x: {
                    "fillColor": x["properties"]["color"],
                    "color": "#000000",
                    "weight": 1,
                    "radius": x["properties"]["radius"],
                    "fillOpacity": 0.9,
                },
                tooltip=folium.GeoJsonTooltip(
                    fields=["closeness"],
                    aliases=["Integration Score:"],
                    localize=True,
                ),
            ).add_to(m)

        # Golden Spots layer
        if st.session_state.show_golden_spots and net_data.get("golden_spots_geojson"):
            folium.GeoJson(
                net_data["golden_spots_geojson"],
                name="Golden Land Spots",
                marker=folium.CircleMarker(),
                style_function=lambda x: {
                    "fillColor": "#FFD60A",
                    "color": "#8C6A00",
                    "weight": 2,
                    "radius": max(5, 12 - x["properties"]["rank"]),
                    "fillOpacity": 0.85,
                },
                tooltip=folium.GeoJsonTooltip(
                    fields=["rank", "score"],
                    aliases=["Rank:", "Opportunity Score:"],
                    localize=True,
                ),
            ).add_to(m)

        # Top Node marker
        if net_data.get("top_node"):
            top = net_data["top_node"]
            folium.Marker(
                [top["lat"], top["lon"]],
                popup=f"🏆 Center (Score: {top['score']:.4f})",
                icon=folium.Icon(color="orange", icon="star", prefix="fa"),
                tooltip="จุดที่อยู่ตรงกลางที่สุด",
            ).add_to(m)

    # ---- Isochrone polygons ----
    iso_data = StateManager.get_isochrone_data()
    if iso_data:
        clrs = StateManager.get_colors()
        folium.GeoJson(
            iso_data,
            name="Travel Areas",
            style_function=lambda x: {
                "fillColor": get_fill_color(
                    x["properties"]["travel_time_minutes"], clrs
                ),
                "color": get_border_color(x["properties"]["original_index"]),
                "weight": 1,
                "fillOpacity": 0.2,
            },
        ).add_to(m)

    # ---- CBD intersection ----
    inter_data = StateManager.get_intersection_data()
    if inter_data:
        folium.GeoJson(
            inter_data,
            name="CBD Zone",
            style_function=lambda _x: {
                "fillColor": "#FFD700",
                "color": "#FF8C00",
                "weight": 3,
                "fillOpacity": 0.6,
                "dashArray": "5, 5",
            },
        ).add_to(m)

    # ---- WMS Layers ----
    _add_wms_layer(
        m, "thailand_population", "ความหนาแน่นประชากร",
        st.session_state.show_population,
    )
    _add_wms_layer(
        m, "cityplan_dpt", "ผังเมืองรวม",
        st.session_state.show_cityplan,
        opacity=st.session_state.cityplan_opacity,
    )
    _add_wms_layer(
        m, "dol", "รูปแปลงที่ดิน", st.session_state.show_dol
    )

    # ---- Railway KML Layer ----
    if st.session_state.show_railway:
        railway_geojson = _parse_kml_to_geojson()
        if railway_geojson and railway_geojson.get("features"):
            folium.GeoJson(
                railway_geojson,
                name="แนวรถไฟเชียงของ",
                style_function=lambda _x: {
                    "color": "#E63946",
                    "weight": 4,
                    "opacity": 0.85,
                    "dashArray": "8, 4",
                    "fillOpacity": 0,
                },
                tooltip="แนวเวนคืนรถไฟเด่นชัย-เชียงราย-เชียงของ",
            ).add_to(m)

    # ---- Markers ----
    for i, marker in enumerate(markers):
        active = marker.get("active", True)
        popup_html = f"<b>จุดที่ {i+1}</b>"
        if rent_model and rent_anchor:
            d_km = haversine_km(
                rent_anchor["lat"], rent_anchor["lon"], marker["lat"], marker["lng"]
            )
            est = predict_rent(d_km, rent_model["r0"], rent_model["lam"])
            popup_html += (
                f"<br>ระยะจาก CBD: {d_km:.2f} km"
                f"<br>ประเมิน: {format_rent_value(est, rent_model)}"
            )
        folium.Marker(
            [marker["lat"], marker["lng"]],
            popup=folium.Popup(popup_html, max_width=260),
            icon=folium.Icon(
                color=MARKER_COLORS[i % len(MARKER_COLORS)] if active else "gray",
                icon="map-marker" if active else "ban",
                prefix="fa",
            ),
        ).add_to(m)

    folium.LayerControl().add_to(m)
    _add_map_legend(m)

    # returned_objects จำกัดเฉพาะ last_clicked → เลื่อน/ซูมแผนที่ไม่ trigger
    # Streamlit rerun ทั้งหน้า (เร็วขึ้นมากบน Streamlit Cloud)
    return st_folium(
        m,
        height=900,
        use_container_width=True,
        key="main_map",
        returned_objects=["last_clicked"],
    )
