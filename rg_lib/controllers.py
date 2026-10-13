"""Controllers — ``perform_*`` handlers, ``@st.cache_data`` wrappers, KML parsing and map-click handling.

Definitions are cut verbatim from pages/Rent_Gradient.py (see tests/test_rg_v2_equivalence.py).
"""


import json
import pandas as pd
import streamlit as st
import time
import xml.etree.ElementTree as ET
from shapely.geometry import shape
from shapely.ops import unary_union
from typing import Any, Dict, List, Optional, Tuple

from .config import EVIDENCE_SCHEMA, NETWORK_CONFIG, TRAVEL_MODE_TO_NETWORK_TYPE, _ANCHOR_CONTEXT_KEYS, _KML_FILE_PATH, _KML_NS
from .geo import anchor_study_polygon, calculate_intersection, should_add_marker
from .rent import compute_rent_gradient_data, fit_quality_label, fit_quality_warning, fit_rent_gradient_from_samples
from .vision import load_cityplan_legend
from .osm import _fetch_osm_graph, cached_graph_available, safe_fetch_isochrone
from .roads import find_cbd_anchors
from .network import _compute_centrality_impl
from .evidence import run_evidence_stage
from .state import StateManager


@st.cache_data(show_spinner=False, ttl=NETWORK_CONFIG["cache_ttl_seconds"])
def fetch_api_data_cached(
    api_key: str,
    travel_mode: str,
    ranges_str: str,
    marker_lat: float,
    marker_lon: float,
) -> Tuple[Optional[List[Dict[str, Any]]], Optional[str]]:
    """Streamlit-cached wrapper around the isochrone API call."""
    return safe_fetch_isochrone(api_key, travel_mode, ranges_str, marker_lat, marker_lon)


@st.cache_data(show_spinner=False, ttl=NETWORK_CONFIG["cache_ttl_seconds"])
def union_all_polygons_cached(features_json_str: str) -> str:
    """
    Union all polygon features → WKT string.

    Takes a JSON **string** so that the argument is hashable for caching.
    """
    features: List[Dict[str, Any]] = json.loads(features_json_str)
    polys = [shape(f["geometry"]) for f in features]
    if not polys:
        return ""
    combined = unary_union(polys)
    return combined.wkt


@st.cache_data(show_spinner=False, ttl=NETWORK_CONFIG["cache_ttl_seconds"])
def compute_centrality_cached(
    polygon_wkt_str: str, network_type: str = "drive"
) -> Dict[str, Any]:
    """Streamlit-cached wrapper for the pure centrality computation."""
    return _compute_centrality_impl(polygon_wkt_str, network_type)


def _parse_coordinates(coord_text: str) -> List[List[float]]:
    """Parse a KML <coordinates> text block into [[lon, lat], ...]."""
    coords: List[List[float]] = []
    for token in coord_text.strip().split():
        parts = token.split(",")
        if len(parts) >= 2:
            try:
                coords.append([float(parts[0]), float(parts[1])])
            except ValueError:
                continue
    return coords


@st.cache_data(show_spinner=False)
def _parse_kml_to_geojson() -> Optional[Dict[str, Any]]:
    """Parse the bundled railway KML into a GeoJSON FeatureCollection.

    Uses stdlib ``xml.etree.ElementTree`` — no extra dependencies.
    Result is cached by ``@st.cache_data`` so the 10 MB file is parsed
    only once per Streamlit server lifetime.
    """
    if not _KML_FILE_PATH.exists():
        return None

    try:
        tree = ET.parse(str(_KML_FILE_PATH))
        root = tree.getroot()
    except ET.ParseError:
        return None

    features: List[Dict[str, Any]] = []

    # -- LineStrings --
    for ls_el in root.iter(f"{{{_KML_NS['kml']}}}LineString"):
        coord_el = ls_el.find(f"{{{_KML_NS['kml']}}}coordinates")
        if coord_el is None or not coord_el.text:
            continue
        coords = _parse_coordinates(coord_el.text)
        if len(coords) >= 2:
            features.append({
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": coords},
                "properties": {},
            })

    # -- Polygons --
    for poly_el in root.iter(f"{{{_KML_NS['kml']}}}Polygon"):
        outer = poly_el.find(
            f"{{{_KML_NS['kml']}}}outerBoundaryIs/"
            f"{{{_KML_NS['kml']}}}LinearRing/"
            f"{{{_KML_NS['kml']}}}coordinates"
        )
        if outer is None or not outer.text:
            continue
        coords = _parse_coordinates(outer.text)
        if len(coords) >= 4:
            features.append({
                "type": "Feature",
                "geometry": {"type": "Polygon", "coordinates": [coords]},
                "properties": {},
            })

    if not features:
        return None

    return {"type": "FeatureCollection", "features": features}


def _sync_rent_samples_from_editor(edited_df: "pd.DataFrame") -> None:
    """แปลงตาราง data_editor → list ตัวอย่างราคา แล้ว sync เข้า session state."""
    new_samples: List[Dict[str, float]] = []
    for _, row in edited_df.iterrows():
        try:
            lat, lon, rent = float(row["lat"]), float(row["lon"]), float(row["rent"])
        except (TypeError, ValueError):
            continue
        if pd.isna(lat) or pd.isna(lon) or pd.isna(rent) or rent <= 0:
            continue
        new_samples.append({"lat": lat, "lon": lon, "rent": rent})

    if new_samples != StateManager.get_rent_samples():
        StateManager.set_rent_samples(new_samples)


def _anchor_search_context() -> Dict[str, Any]:
    return {
        "study_center": [st.session_state.anchor_lat, st.session_state.anchor_lon],
        "study_radius_m": st.session_state.anchor_radius_km * 1000,
        "network_type": TRAVEL_MODE_TO_NETWORK_TYPE.get(StateManager.get_travel_mode(), "drive"),
    }


def _anchor_context_matches(saved: Optional[Dict[str, Any]], current: Dict[str, Any]) -> bool:
    """Compare only the inputs that change the answer.

    Results saved by the earlier seeded search also carry ``random_seed`` and
    ``restarts``; those no longer matter and must not invalidate a saved result.
    """
    return bool(saved) and all(saved.get(k) == current.get(k) for k in _ANCHOR_CONTEXT_KEYS)


def _parse_anchor_center_input(value: str) -> Tuple[float, float]:
    """Parse a single "Lat, Lon" text field while preserving legacy state keys."""
    parts = [part.strip() for part in str(value).split(",")]
    example = "20.075226819421776, 100.5083729446834"
    if len(parts) != 2 or not all(parts):
        raise ValueError(f"กรุณากรอกพิกัดเป็น Lat, Lon เช่น {example}")
    try:
        lat, lon = (float(parts[0]), float(parts[1]))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"พิกัดไม่ถูกต้อง กรุณาใช้รูปแบบ Lat, Lon เช่น {example}") from exc
    if not (-85.0 <= lat <= 85.0):
        raise ValueError("Lat ต้องอยู่ระหว่าง -85 ถึง 85")
    if not (-180.0 <= lon <= 180.0):
        raise ValueError("Lon ต้องอยู่ระหว่าง -180 ถึง 180")
    return lat, lon


def perform_calculation(
    active_list: List[Tuple[int, Dict[str, Any]]]
) -> None:
    """Fetch isochrones for all active markers, compute CBD intersection."""
    # ---- Validation ----
    api_key = StateManager.get_api_key()
    if not api_key:
        st.warning("⚠️ กรุณาใส่ API Key")
        return
    if not active_list:
        st.warning("⚠️ กรุณาเลือกจุดอย่างน้อย 1 จุด")
        return
    time_intervals = StateManager.get_time_intervals()
    if not time_intervals:
        st.warning("⚠️ กรุณาเลือกช่วงเวลา")
        return

    travel_mode = StateManager.get_travel_mode()

    with st.spinner("กำลังคำนวณ Isochrone..."):
        all_features: List[Dict[str, Any]] = []
        ranges_str = ",".join(str(t * 60) for t in sorted(time_intervals))
        errors: List[str] = []

        for act_idx, (orig_idx, marker) in enumerate(active_list):
            features, error_msg = fetch_api_data_cached(
                api_key, travel_mode, ranges_str, marker["lat"], marker["lng"]
            )

            if features is None:
                errors.append(f"จุดที่ {orig_idx + 1}: {error_msg}")
                continue

            for f in features:
                f["properties"].update(
                    {
                        "travel_time_minutes": f["properties"].get("value", 0) / 60,
                        "original_index": orig_idx,
                        "active_index": act_idx,
                    }
                )
                all_features.append(f)

        # Display collected errors
        for error in errors:
            st.error(error)
        if not all_features:
            return  # All requests failed

        # Store isochrone results
        StateManager.set_isochrone_data(
            {"type": "FeatureCollection", "features": all_features}
        )

        # Calculate CBD intersection
        cbd_geom = calculate_intersection(all_features, len(active_list))
        if cbd_geom:
            StateManager.set_intersection_data(
                {
                    "type": "FeatureCollection",
                    "features": [
                        {
                            "type": "Feature",
                            "geometry": cbd_geom,
                            "properties": {"type": "cbd"},
                        }
                    ],
                }
            )
            st.toast("✅ พบพื้นที่ CBD!", icon="🎯")
        else:
            StateManager.set_intersection_data(None)
            st.toast("⚠️ ไม่พบพื้นที่ทับซ้อน", icon="⚠️")

        # Rent Gradient ผูกกับ CBD ใหม่ — รีเฟรชอัตโนมัติ (pure math, เร็วมาก)
        perform_rent_gradient(quiet=True)


def _run_network_analysis_with_progress(
    polygon_wkt_str: str, network_type: str
) -> Dict[str, Any]:
    """
    Thin UI wrapper that shows progress while the **cached** pure function runs.
    """
    progress_bar = st.progress(0)
    status_container = st.empty()

    try:
        # Stage 1: Prepare
        status_container.info("🔍 **Stage 1/3:** กำลังเตรียมข้อมูลพื้นที่...")
        progress_bar.progress(0.05)

        # Stage 2: Check cache
        is_cached = cached_graph_available(polygon_wkt_str, network_type)

        if is_cached:
            status_container.success("✅ **พบข้อมูลใน Cache!** กำลังโหลด...")
        else:
            status_container.warning(
                "⏳ **กำลังดาวน์โหลดข้อมูลครั้งแรก...** (อาจใช้เวลา 5-10 นาที)"
            )
        progress_bar.progress(0.10)

        # Stage 3: Compute
        status_container.info("🛣️ **Stage 2/3:** กำลังวิเคราะห์โครงข่ายถนน...")
        progress_bar.progress(0.30)

        result = compute_centrality_cached(polygon_wkt_str, network_type)

        progress_bar.progress(0.90)

        # Stage 4: Report
        if "error" in result:
            status_container.error(f"❌ {result['error']}")
        else:
            stats = result.get("stats", {})
            status_container.success(
                f"✅ **สำเร็จ!** วิเคราะห์ {stats.get('nodes_count', 0):,} โหนด "
                f"และ {stats.get('edges_count', 0):,} ถนน"
            )
        progress_bar.progress(1.0)

    finally:
        progress_bar.empty()
        status_container.empty()

    return result


def perform_network_analysis() -> None:
    """Orchestrate the full network analysis pipeline."""
    iso_data = StateManager.get_isochrone_data()
    if not iso_data:
        st.error("❌ No Isochrone data found. Please calculate isochrones first.")
        return

    with st.spinner(
        "กำลังรวมพื้นที่และวิเคราะห์โครงข่ายถนน (OSMnx)... อาจใช้เวลาสักครู่"
    ):
        try:
            # 1. Union all travel polygons
            feats_json = json.dumps(iso_data.get("features", []))
            combined_wkt = union_all_polygons_cached(feats_json)

            if not combined_wkt:
                st.error("❌ No polygons to analyze.")
                return

            # 2. Run analysis with progress UI
            net_type = TRAVEL_MODE_TO_NETWORK_TYPE.get(
                StateManager.get_travel_mode(), "drive"
            )
            result = _run_network_analysis_with_progress(combined_wkt, net_type)

            if "error" in result:
                st.error(f"❌ Network Analysis Failed: {result['error']}")
                st.info(
                    "💡 **Tips:**\n"
                    "- Try a larger area\n"
                    "- Check if the location has road data in OpenStreetMap\n"
                    "- Verify internet connection"
                )
            else:
                StateManager.set_network_data(result)
                score_info = (
                    f"Score: {result['top_node']['score']:.4f}"
                    if result.get("top_node")
                    else ""
                )
                st.toast(f"✅ Analysis Completed! {score_info}", icon="🏆")

                # มีโหนดถนนแล้ว — รีเฟรช Rent Gradient เพื่อสร้าง Rent Heat
                if StateManager.get_rent_data() is not None:
                    perform_rent_gradient(quiet=True)

        except Exception as e:
            st.error(f"❌ Processing Error: {e}")
            st.info(
                "💡 If the error persists, try a different location "
                "or smaller time intervals."
            )


def perform_automated_anchor() -> None:
    """Download one buffered graph, find both anchors in one pass, publish atomically."""
    context = _anchor_search_context()
    started = time.perf_counter()
    try:
        with st.spinner(
            "กำลังโหลดถนนพร้อม buffer 20% และค้นหา CBD… การโหลด OSM อาจใช้เวลานาน"
        ):
            polygon = anchor_study_polygon(*context["study_center"], context["study_radius_m"])
            fetch_started = time.perf_counter()
            graph, cached, error = _fetch_osm_graph(polygon.wkt, context["network_type"])
            load_seconds = time.perf_counter() - fetch_started
            if error or graph is None:
                raise ValueError(error or "No road graph returned.")
            found = find_cbd_anchors(
                graph, tuple(context["study_center"]), context["study_radius_m"])
            source = graph.graph.get("osm_source", "cache" if cached else "download")
            endpoint = graph.graph.get("overpass_endpoint", "disk-cache" if cached else "unknown")
            samples = StateManager.get_rent_samples()
            published = {}
            for objective, state_key in (
                ("composite", StateManager.K_AUTO_ANCHOR),
                ("closeness", StateManager.K_AUTO_ANCHOR_CLOSENESS),
            ):
                result = found[objective]
                result.update(
                    context=context,
                    graph_cached=cached,
                    graph_source_endpoint=endpoint,
                    graph={**found["graph"], "source": source, "endpoint": endpoint},
                    load_seconds=load_seconds,
                    total_seconds=time.perf_counter() - started,
                )
                anchor = result["anchor"]
                baseline = fit_rent_gradient_from_samples(samples, *context["study_center"])
                fitted = fit_rent_gradient_from_samples(samples, anchor["lat"], anchor["lon"])
                if baseline and fitted:
                    result["rent_fit_comparison"] = {
                        "center_r2": baseline["r2"],
                        "anchor_r2": fitted["r2"],
                        "delta_r2": fitted["r2"] - baseline["r2"],
                        "n_samples": fitted["n_samples"],
                    }
                published[state_key] = result
            published[StateManager.K_AUTO_ANCHOR_EVIDENCE] = None
            if st.session_state.get("anchor_use_evidence"):
                with st.spinner("กำลังตรวจผังเมืองรวมและรูปแปลงที่ดินของผู้สมัคร…"):
                    legend, legend_source = load_cityplan_legend()
                    evidence = run_evidence_stage(
                        found, tuple(context["study_center"]), context["study_radius_m"],
                        legend=legend, legend_source=legend_source)
                    evidence["context"] = context
                    published[StateManager.K_AUTO_ANCHOR_EVIDENCE] = evidence
            st.session_state.update(published)  # all anchors become visible together
            StateManager.clear_results(["rent"])
            perform_rent_gradient(quiet=True)
    except Exception as exc:
        st.error(f"ค้นหา Automated Anchor ไม่สำเร็จ: {exc}")
        return
    st.rerun()


def _rent_anchor_input() -> Optional[Dict[str, Any]]:
    """Anchor handed to the Rent Gradient: the composite one, or the evidence anchor on opt-in."""
    automated = st.session_state.get(StateManager.K_AUTO_ANCHOR)
    evidence = st.session_state.get(StateManager.K_AUTO_ANCHOR_EVIDENCE)
    if (automated and evidence and evidence.get("schema") == EVIDENCE_SCHEMA
            and evidence.get("evidence_anchor") and st.session_state.get("rent_use_evidence_anchor")):
        return {**automated, "anchor": dict(evidence["evidence_anchor"])}
    return automated


def _on_rent_anchor_toggle() -> None:
    StateManager.clear_results(["rent"])
    perform_rent_gradient(quiet=True)


def perform_rent_gradient(quiet: bool = False) -> None:
    """Orchestrate Rent Gradient computation (pure math — ไม่มี API call)."""
    iso_data = StateManager.get_isochrone_data()
    automated = _rent_anchor_input()
    if not iso_data and not automated:
        if not quiet:
            st.error("❌ กรุณาคำนวณ Isochrone หรือค้นหา Automated Anchor ก่อน")
        return

    data = compute_rent_gradient_data(
        StateManager.get_intersection_data(),
        StateManager.get_network_data(),
        iso_data,
        StateManager.get_markers(),
        StateManager.get_rent_samples(),
        StateManager.get_rent_unit(),
        automated_anchor=automated,
    )
    if "error" in data:
        StateManager.set_rent_data(None)
        if not quiet:
            st.error(f"❌ {data['error']}")
        return

    StateManager.set_rent_data(data)
    if not quiet:
        model = data["model"]
        mode = "โหมดดัชนี" if model["is_index"] else fit_quality_label(model)
        warn = fit_quality_warning(model)
        st.toast(
            f"💰 Rent Gradient พร้อม ({mode}) λ={model['lam']:.4f}"
            + (" — ⚠️ ตัวอย่างน้อย" if warn and "น้อยกว่า" in warn else ""),
            icon="⚠️" if warn else "✅",
        )


def handle_map_click(map_output: Optional[Dict[str, Any]], locked: bool) -> None:
    """Process a map click event — add marker if debounce passes."""
    if locked:
        return
    if not map_output:
        return
    clicked = map_output.get("last_clicked")
    if not clicked:
        return

    last = StateManager.get_last_click()
    if should_add_marker(clicked["lat"], clicked["lng"], last):
        StateManager.add_marker(clicked["lat"], clicked["lng"])
        StateManager.record_click(clicked["lat"], clicked["lng"])
        StateManager.clear_results(["isochrone", "intersection", "rent"])
        st.rerun()
