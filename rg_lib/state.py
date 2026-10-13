"""Session — ``StateManager``: every read/write of ``st.session_state`` goes through this class.

Definitions are cut verbatim from pages/Rent_Gradient.py (see tests/test_rg_v2_equivalence.py).
"""


import json
import requests
import streamlit as st
import time
from typing import Any, Dict, List, Optional, Tuple

from .config import DEFAULT_CONFIG, RESULT_KEYS_TO_SAVE, SESSION_KEYS_TO_SAVE, TIMEOUT_INIT


class StateManager:
    """
    Centralized session-state management.

    All reads / writes to ``st.session_state`` go through this class
    so that key names are defined once and typos are caught at the
    class level instead of buried in UI code.
    """

    # ---- Key constants (single source of truth) ----
    K_MARKERS: str = "markers"
    K_ISOCHRONE: str = "isochrone_data"
    K_INTERSECTION: str = "intersection_data"
    K_NETWORK: str = "network_data"
    K_LAST_CLICK: str = "last_processed_click"
    K_COLORS: str = "colors"
    K_API_KEY: str = "api_key"
    K_MAP_STYLE: str = "map_style_name"
    K_TRAVEL_MODE: str = "travel_mode"
    K_TIME_INTERVALS: str = "time_intervals"
    K_SHOW_DOL: str = "show_dol"
    K_SHOW_CITYPLAN: str = "show_cityplan"
    K_CITYPLAN_OPACITY: str = "cityplan_opacity"
    K_SHOW_POPULATION: str = "show_population"
    K_SHOW_TRAFFIC: str = "show_traffic"
    K_SHOW_BETWEENNESS: str = "show_betweenness"
    K_SHOW_CLOSENESS: str = "show_closeness"
    K_SHOW_RAILWAY: str = "show_railway"
    K_SHOW_GOLDEN: str = "show_golden_spots"
    K_UI_LOCKED: str = "ui_locked"
    K_RENT_SAMPLES: str = "rent_samples"
    K_RENT_DATA: str = "rent_gradient_data"
    K_SHOW_RENT_RINGS: str = "show_rent_rings"
    K_SHOW_RENT_NODES: str = "show_rent_nodes"
    K_RENT_UNIT: str = "rent_unit_label"
    K_AUTO_ANCHOR: str = "automated_anchor_data"
    K_AUTO_ANCHOR_CLOSENESS: str = "automated_anchor_closeness_data"
    K_AUTO_ANCHOR_EVIDENCE: str = "automated_anchor_evidence_data"

    # ---- Default values ----
    _DEFAULTS: Dict[str, Any] = {
        K_MARKERS: None,  # Will be set from remote JSON or fallback
        K_ISOCHRONE: None,
        K_INTERSECTION: None,
        K_NETWORK: None,
        K_LAST_CLICK: None,
        K_COLORS: {
            "step1": "#2A9D8F",
            "step2": "#E9C46A",
            "step3": "#F4A261",
            "step4": "#D62828",
        },
        K_API_KEY: DEFAULT_CONFIG["GEOAPIFY_KEY"],
        K_MAP_STYLE: "Esri Light Gray (แนะนำสำหรับดูผังเมือง)",
        K_TRAVEL_MODE: "drive",
        K_TIME_INTERVALS: [5],
        K_SHOW_DOL: False,
        K_SHOW_CITYPLAN: False,
        K_CITYPLAN_OPACITY: 0.7,
        K_SHOW_POPULATION: False,
        K_SHOW_TRAFFIC: False,
        K_SHOW_BETWEENNESS: False,
        K_SHOW_CLOSENESS: False,
        K_SHOW_RAILWAY: False,
        K_SHOW_GOLDEN: True,
        K_UI_LOCKED: False,
        K_RENT_SAMPLES: [],
        K_RENT_DATA: None,
        K_SHOW_RENT_RINGS: True,
        K_SHOW_RENT_NODES: False,
        K_RENT_UNIT: "บาท/ตร.ว./เดือน",
        K_AUTO_ANCHOR: None,
        K_AUTO_ANCHOR_CLOSENESS: None,
        K_AUTO_ANCHOR_EVIDENCE: None,
        "anchor_use_evidence": False,         # opt-in until real WMS fixtures calibrate the thresholds
        "rent_use_evidence_anchor": False,    # Rent keeps the composite anchor unless ticked
        "anchor_lat": DEFAULT_CONFIG["LAT"],
        "anchor_lon": DEFAULT_CONFIG["LON"],
        "anchor_radius_km": 10.0,
    }

    _DEFAULT_MARKER: Dict[str, Any] = {
        "lat": DEFAULT_CONFIG["LAT"],
        "lng": DEFAULT_CONFIG["LON"],
        "active": True,
    }

    # ------------------------------------------------------------------ init
    @classmethod
    def initialize(cls) -> None:
        """Initialize all session-state variables with defaults.

        On first load, attempts to pull saved state from a remote JSON.
        Subsequent reruns are no-ops for keys that already exist.
        """
        first_run = cls.K_MARKERS not in st.session_state

        # Resolve starting defaults (possibly from remote)
        defaults = dict(cls._DEFAULTS)
        if first_run:
            defaults[cls.K_MARKERS] = cls._load_remote_defaults(defaults)

        # Fallback marker list
        if defaults[cls.K_MARKERS] is None:
            defaults[cls.K_MARKERS] = [dict(cls._DEFAULT_MARKER)]

        # Apply defaults using setdefault (idempotent)
        for key, value in defaults.items():
            st.session_state.setdefault(key, value)

        # Ensure every marker dict has an 'active' key
        for m in st.session_state[cls.K_MARKERS]:
            m.setdefault("active", True)

    @staticmethod
    def _load_remote_defaults(defaults: Dict[str, Any]) -> Optional[List[Dict]]:
        """Attempt to load initial state from the remote JSON URL."""
        try:
            resp = requests.get(
                DEFAULT_CONFIG["JSON_URL"], timeout=TIMEOUT_INIT
            )
            if resp.status_code == 200:
                data: Dict[str, Any] = resp.json()
                # Merge remote settings into defaults
                for k in defaults:
                    if k in data:
                        defaults[k] = data[k]
                return data.get("markers")
        except Exception:
            pass
        return None

    # ------------------------------------------------------------- accessors
    @classmethod
    def get_markers(cls) -> List[Dict[str, Any]]:
        return st.session_state[cls.K_MARKERS]

    @classmethod
    def get_active_markers(cls) -> List[Tuple[int, Dict[str, Any]]]:
        """Return list of (original_index, marker_dict) for active markers."""
        return [
            (i, m)
            for i, m in enumerate(st.session_state[cls.K_MARKERS])
            if m.get("active", True)
        ]

    @classmethod
    def get_isochrone_data(cls) -> Optional[Dict[str, Any]]:
        return st.session_state[cls.K_ISOCHRONE]

    @classmethod
    def get_intersection_data(cls) -> Optional[Dict[str, Any]]:
        return st.session_state[cls.K_INTERSECTION]

    @classmethod
    def get_network_data(cls) -> Optional[Dict[str, Any]]:
        return st.session_state[cls.K_NETWORK]

    @classmethod
    def get_colors(cls) -> Dict[str, str]:
        return st.session_state[cls.K_COLORS]

    @classmethod
    def get_api_key(cls) -> str:
        return st.session_state[cls.K_API_KEY]

    @classmethod
    def get_travel_mode(cls) -> str:
        return st.session_state[cls.K_TRAVEL_MODE]

    @classmethod
    def get_time_intervals(cls) -> List[int]:
        return st.session_state[cls.K_TIME_INTERVALS]

    @classmethod
    def get_map_style_name(cls) -> str:
        return st.session_state[cls.K_MAP_STYLE]

    @classmethod
    def get_rent_samples(cls) -> List[Dict[str, Any]]:
        return st.session_state[cls.K_RENT_SAMPLES]

    @classmethod
    def set_rent_samples(cls, samples: List[Dict[str, Any]]) -> None:
        st.session_state[cls.K_RENT_SAMPLES] = samples

    @classmethod
    def get_rent_data(cls) -> Optional[Dict[str, Any]]:
        return st.session_state[cls.K_RENT_DATA]

    @classmethod
    def set_rent_data(cls, data: Optional[Dict[str, Any]]) -> None:
        st.session_state[cls.K_RENT_DATA] = data

    @classmethod
    def get_rent_unit(cls) -> str:
        return st.session_state[cls.K_RENT_UNIT]

    # -------------------------------------------------------------- mutators
    @classmethod
    def set_isochrone_data(cls, data: Optional[Dict[str, Any]]) -> None:
        st.session_state[cls.K_ISOCHRONE] = data

    @classmethod
    def set_intersection_data(cls, data: Optional[Dict[str, Any]]) -> None:
        st.session_state[cls.K_INTERSECTION] = data

    @classmethod
    def set_network_data(cls, data: Optional[Dict[str, Any]]) -> None:
        st.session_state[cls.K_NETWORK] = data

    @classmethod
    def add_marker(cls, lat: float, lng: float) -> None:
        st.session_state[cls.K_MARKERS].append(
            {"lat": lat, "lng": lng, "active": True}
        )

    @classmethod
    def remove_marker(cls, index: int) -> None:
        markers = st.session_state[cls.K_MARKERS]
        if 0 <= index < len(markers):
            markers.pop(index)

    @classmethod
    def pop_last_marker(cls) -> None:
        markers = st.session_state[cls.K_MARKERS]
        if markers:
            markers.pop()

    @classmethod
    def set_marker_active(cls, index: int, active: bool) -> None:
        st.session_state[cls.K_MARKERS][index]["active"] = active

    @classmethod
    def record_click(cls, lat: float, lon: float) -> None:
        st.session_state[cls.K_LAST_CLICK] = {
            "timestamp": time.time(),
            "lat": lat,
            "lon": lon,
        }

    @classmethod
    def get_last_click(cls) -> Optional[Dict[str, Any]]:
        return st.session_state.get(cls.K_LAST_CLICK)

    # ------------------------------------------------------- cache clearing
    @classmethod
    def clear_results(cls, layers: Optional[List[str]] = None) -> None:
        """
        Smart cache invalidation — clear only specified layers.

        Args:
            layers: ``['isochrone', 'intersection', 'network', 'rent']``.
                    ``None`` clears all.
        """
        if layers is None:
            layers = ["isochrone", "intersection", "network", "rent", "anchor", "anchor_closeness",
                      "anchor_evidence"]

        if "anchor" in layers:
            st.session_state[cls.K_AUTO_ANCHOR] = None
            st.session_state[cls.K_AUTO_ANCHOR_EVIDENCE] = None  # it confirms this road result
            st.session_state[cls.K_RENT_DATA] = None
        if "anchor_evidence" in layers:
            st.session_state[cls.K_AUTO_ANCHOR_EVIDENCE] = None
        if "anchor_closeness" in layers:
            st.session_state[cls.K_AUTO_ANCHOR_CLOSENESS] = None

        if "isochrone" in layers:
            st.session_state[cls.K_ISOCHRONE] = None
        if "intersection" in layers:
            st.session_state[cls.K_INTERSECTION] = None
        if "network" in layers:
            st.session_state[cls.K_NETWORK] = None
        if "rent" in layers:
            st.session_state[cls.K_RENT_DATA] = None

    @classmethod
    def reset(cls) -> None:
        """Reset to factory defaults."""
        st.session_state[cls.K_MARKERS] = [dict(cls._DEFAULT_MARKER)]
        st.session_state[cls.K_LAST_CLICK] = None
        cls.clear_results()

    @classmethod
    def import_config(cls, data: Dict[str, Any]) -> None:
        """Import settings + optional precomputed outputs from config."""
        if "markers" in data:
            st.session_state[cls.K_MARKERS] = data["markers"]

        settings = data.get("settings", {})
        for k, v in settings.items():
            if k in SESSION_KEYS_TO_SAVE:
                st.session_state[k] = v

        # The combined coordinate widget is UI-only. Keep it synchronized with
        # the legacy anchor_lat / anchor_lon keys used by saved configurations.
        if "anchor_lat" in settings or "anchor_lon" in settings:
            st.session_state["anchor_center_input"] = (
                f"{float(st.session_state['anchor_lat'])!r}, "
                f"{float(st.session_state['anchor_lon'])!r}"
            )

        # Start from a clean slate so keys absent from the payload
        # don't keep stale results anchored to the previous CBD.
        cls.clear_results()

        precomputed_results = data.get("precomputed_results", {})
        for result_key in RESULT_KEYS_TO_SAVE:
            if result_key in precomputed_results:
                st.session_state[result_key] = precomputed_results[result_key]

        # Backward compatibility: allow old flat structure.
        for result_key in RESULT_KEYS_TO_SAVE:
            if result_key in data:
                st.session_state[result_key] = data[result_key]

    @classmethod
    def export_config(cls) -> str:
        """Export config and currently computed outputs as a JSON string."""
        return json.dumps(
            {
                "format_version": 2,
                "markers": st.session_state[cls.K_MARKERS],
                "settings": {
                    k: st.session_state[k]
                    for k in SESSION_KEYS_TO_SAVE
                    if k in st.session_state
                },
                "precomputed_results": {
                    k: st.session_state.get(k)
                    for k in RESULT_KEYS_TO_SAVE
                },
            },
            indent=2,
            ensure_ascii=False,
        )
