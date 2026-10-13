"""
Geoapify CBD x Longdo GIS + Network Analysis + Rent Gradient (Bid-Rent) — v2
============================================================================
v2 = pages/Rent_Gradient.py with the same behaviour (calculations, widgets, texts, state keys), restructured into
the layered package ``rg_lib`` (see rg_lib/__init__.py). This file is only the page: ``main()`` is the original,
unchanged, and the imports below re-export the names that tests and scripts read from a page module (``page.<name>``),
so the same test-suite runs against either page:

    RENT_GRADIENT_PAGE=pages/Rent_Gradient_v2.py python -m pytest tests

pages/Rent_Gradient.py is left as it was and remains the reference implementation. Both pages use the same
``st.session_state`` keys, so results computed in one tab are visible in the other.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent  # repo root: ``rg_lib`` lives next to ``pages/``
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st
import folium  # noqa: F401  (tests patch page.folium / page.requests / page.ox / page.st_folium)
import requests  # noqa: F401
import osmnx as ox  # noqa: F401
from streamlit_folium import st_folium  # noqa: F401

from rg_lib.compat import (  # noqa: F401
    HAS_SCIPY, csgraph_dijkstra, ndi,
)
from rg_lib.config import (  # noqa: F401
    ANCHOR_CONFIG, CELL_M, CITYPLAN_PROVISIONAL_LEGEND, DEFAULT_CONFIG, EVIDENCE_CONFIG, EVIDENCE_SCHEMA,
    LONGDO_WMS_URL, MAX_CACHE_ENTRY_BYTES, NETWORK_CONFIG, OVERPASS_CONFIG, PAGE_CONFIG, ZONING_COLOR_TOLERANCE,
    _OVERPASS_LOCK, _WEB_MERCATOR,
)
from rg_lib.geo import (  # noqa: F401
    _anchor_projection, _geodesic_circle_coords, anchor_study_polygon, approx_geom_area_km2,
    calculate_distance_meters, calculate_intersection, get_border_color, get_fill_color, haversine_km,
    should_add_marker,
)
from rg_lib.rent import (  # noqa: F401
    _fit_dof, _ring_index_for_distance, build_rent_nodes_geojson, build_rent_rings_geojson, build_ring_report,
    compute_rent_gradient_data, count_nodes_per_ring, fit_interval_text, fit_quality_label, fit_quality_warning,
    fit_rent_gradient_from_samples, format_rent_value, isochrone_max_distance_km, rent_color_for_norm,
    resolve_cbd_anchor, ring_coverage_areas_km2, t_critical_95,
)
from rg_lib.vision import (  # noqa: F401
    _cells_per_tile, _circle_mask, _classify_colors, _clusters_of, _component_aspect, _evidence_geometry,
    _hot_threshold, _is_red_family, _lattice_tiles, _legend_lut, _parcel_tile_scores, _paste, _peak_zone,
    _pick_cluster, _plan_tile_shares, _smooth_nan, _tile_bbox, _wms_params, _wms_window, _zones_in_scope,
    classify_anchor_confidence, estimate_evidence_requests, load_cityplan_legend, parcel_features,
    wms_meters_per_pixel,
)
from rg_lib.osm import (  # noqa: F401
    CACHE_DIR, _fetch_osm_graph, _load_graph_bytes, _read_cache_sidecar, cached_graph_available,
    export_cache_as_zip, find_covering_cache_key, get_cache_key, get_cache_stats, import_cache_from_zip,
    load_graph_from_cache, safe_fetch_isochrone, safe_pickle_loads, save_graph_to_cache,
)
from rg_lib.roads import (  # noqa: F401
    _collapsed_csr, compute_weighted_closeness, find_cbd_anchors,
)
from rg_lib.network import (  # noqa: F401
    _compute_centrality_impl, compute_golden_land_opportunities, edge_scores_by_pair,
)
from rg_lib.evidence import (  # noqa: F401
    fetch_wms_image, load_cached_wms_image, run_evidence_stage,
)
from rg_lib.state import (  # noqa: F401
    StateManager,
)
from rg_lib.bundle import (  # noqa: F401
    export_bundle_zip, import_bundle_zip,
)
from rg_lib.controllers import (  # noqa: F401
    _anchor_context_matches, _parse_anchor_center_input, _parse_kml_to_geojson, _rent_anchor_input,
    fetch_api_data_cached, handle_map_click, perform_automated_anchor, perform_calculation,
    perform_network_analysis, perform_rent_gradient,
)
from rg_lib.ui_map import (  # noqa: F401
    render_map,
)
from rg_lib.ui_sidebar import (  # noqa: F401
    render_sidebar,
)
from rg_lib.ui_panels import (  # noqa: F401
    _build_golden_spots_df, render_analytics_panel, render_header, render_metrics_row,
)


# The disk cache folder must exist before any handler runs (as in the single-file page, on every rerun).
CACHE_DIR.mkdir(exist_ok=True)


# ============================================================================
# MAIN EXECUTION  (identical to pages/Rent_Gradient.py)
# ============================================================================

def main() -> None:
    st.set_page_config(**PAGE_CONFIG)

    # Inject minimal CSS to fix spacing
    st.markdown(
        "<style>"
        ".block-container { padding-top: 2rem; padding-bottom: 0rem; } "
        "h1 { margin-bottom: 0px; } "
        "div[data-testid=\"stHorizontalBlock\"] button "
        "{ padding: 0rem 0.5rem; }"
        "</style>",
        unsafe_allow_html=True,
    )

    # 1. Initialize State
    StateManager.initialize()

    # 2. Render Sidebar → capture user intents
    do_calc, do_net, do_rent, do_anchor, active_list = render_sidebar()

    # 3. Execute Business Logic (based on user intents)
    if do_calc:
        perform_calculation(active_list)

    if do_net:
        perform_network_analysis()

    if do_rent:
        perform_rent_gradient()

    if do_anchor:
        perform_automated_anchor()

    # 4. Render Header + Metrics + Map + Analytics
    render_header()
    render_metrics_row()
    map_output = render_map()
    render_analytics_panel()

    # 5. Handle Map Click → mutate state & rerun
    handle_map_click(map_output, st.session_state[StateManager.K_UI_LOCKED])


if __name__ == "__main__":
    main()
