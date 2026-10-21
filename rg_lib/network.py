"""I/O — network analysis: centrality and golden-land scoring on the (cached) OSM graph. No streamlit.

Definitions are cut verbatim from pages/Rent_Gradient.py (see tests/test_rg_v2_equivalence.py).
"""


import matplotlib
import matplotlib.colors as colors
import networkx as nx
from shapely import wkt
from shapely.geometry import mapping
from typing import Any, Dict, List, Optional, Tuple

from .config import NETWORK_CONFIG
from .geo import calculate_distance_meters
from .osm import _fetch_osm_graph
from .roads import compute_weighted_closeness


def edge_scores_by_pair(
    scores: Dict[Tuple[Any, ...], float]
) -> Dict[Tuple[Any, Any], float]:
    """Collapse edge scores keyed ``(u, v)`` or ``(u, v, key)`` onto ``sorted((u, v))``.

    NetworkX returns 3-tuple keys for MultiGraph edge betweenness and credits
    only one of several parallel edges, so the pair value is the maximum over
    its keys. Looking such a dict up with a 2-tuple silently yields nothing.
    """
    pairs: Dict[Tuple[Any, Any], float] = {}
    for key, value in scores.items():
        pair = tuple(sorted(key[:2]))
        if value > pairs.get(pair, float("-inf")):
            pairs[pair] = value
    return pairs


def compute_golden_land_opportunities(
    graph: nx.MultiDiGraph,
    closeness_cent: Dict[Any, float],
    edge_betweenness_cent: Dict[Tuple[Any, Any], float],
    top_n: int = 10,
    min_spacing_m: Optional[float] = None,
) -> List[Dict[str, Any]]:
    """
    Rank candidate nodes for "golden land" discovery.

    Principle / Equation:
    score = 0.50*closeness_norm + 0.30*degree_norm + 0.20*(1-edge_betweenness_norm)

    Selection is greedy non-maximum suppression: a node is skipped when a
    higher-ranked pick lies within ``min_spacing_m`` (default from
    ``NETWORK_CONFIG``; ``0`` disables), so adjacent nodes of one junction
    cluster cannot fill the whole top-N.
    """
    if not closeness_cent:
        return []

    weights = NETWORK_CONFIG["golden_land_weights"]
    max_close = max(closeness_cent.values()) or 1.0

    degree_dict = dict(graph.degree())
    max_degree = max(degree_dict.values()) if degree_dict else 1
    if max_degree <= 0:
        max_degree = 1

    edge_betweenness_cent = edge_scores_by_pair(edge_betweenness_cent)
    max_bet = max(edge_betweenness_cent.values()) if edge_betweenness_cent else 1.0
    if max_bet <= 0:
        max_bet = 1.0

    # Precompute mean adjacent edge-betweenness per node once.
    # This avoids repeated ``graph.edges(node)`` scans for every node.
    node_edge_score_sum: Dict[Any, float] = {}
    node_edge_count: Dict[Any, int] = {}
    for u, v in graph.edges():
        bet_norm = edge_betweenness_cent.get(tuple(sorted((u, v))), 0.0) / max_bet

        node_edge_score_sum[u] = node_edge_score_sum.get(u, 0.0) + bet_norm
        node_edge_count[u] = node_edge_count.get(u, 0) + 1

        if u != v:
            node_edge_score_sum[v] = node_edge_score_sum.get(v, 0.0) + bet_norm
            node_edge_count[v] = node_edge_count.get(v, 0) + 1

    ranked: List[Dict[str, Any]] = []
    for node, data in graph.nodes(data=True):
        close_norm = closeness_cent.get(node, 0.0) / max_close
        degree_norm = degree_dict.get(node, 0) / max_degree

        edge_count = node_edge_count.get(node, 0)
        if edge_count > 0:
            edge_bet_norm = node_edge_score_sum[node] / edge_count
        else:
            edge_bet_norm = 0.0

        low_traffic_bonus = 1.0 - edge_bet_norm
        score = (
            weights["closeness"] * close_norm
            + weights["degree"] * degree_norm
            + weights["low_traffic_bonus"] * low_traffic_bonus
        )
        ranked.append(
            {
                "node_id": int(node) if isinstance(node, int) else str(node),
                "lat": data["y"],
                "lon": data["x"],
                "score": score,
                "closeness_norm": close_norm,
                "degree_norm": degree_norm,
                "low_traffic_bonus": low_traffic_bonus,
            }
        )

    ranked.sort(key=lambda x: x["score"], reverse=True)
    spacing = (
        NETWORK_CONFIG["golden_land_min_spacing_m"]
        if min_spacing_m is None else float(min_spacing_m)
    )
    if spacing <= 0:
        return ranked[:top_n]
    picked: List[Dict[str, Any]] = []
    for cand in ranked:
        if len(picked) >= top_n:
            break
        if all(
            calculate_distance_meters(cand["lat"], cand["lon"], p["lat"], p["lon"]) >= spacing
            for p in picked
        ):
            picked.append(cand)
    return picked


def _compute_centrality_impl(
    polygon_wkt_str: str, network_type: str = "drive"
) -> Dict[str, Any]:
    """
    **Pure** centrality computation — no Streamlit calls.

    Returns a result dict with keys:
    ``edges``, ``nodes``, ``top_node``, ``stats``  — or  ``error``.
    """
    G, was_cached, error = _fetch_osm_graph(polygon_wkt_str, network_type)
    if error:
        return {"error": error}

    if G is None or len(G.nodes) < 2:
        return {
            "error": (
                "Not enough nodes found in the area. "
                "Try a larger region or check if OSM data is available."
            )
        }

    node_count = len(G.nodes)
    is_large_graph = node_count > NETWORK_CONFIG["large_graph_threshold"]

    G_undir = G.to_undirected()

    # Closeness centrality — weighted 1-median บน LCC (แม่น/เสถียร/เร็ว)
    closeness_cent, closeness_method = compute_weighted_closeness(G_undir)
    max_close = max(closeness_cent.values()) if closeness_cent else 1.0

    # Betweenness centrality (on undirected projection)
    # กราฟใหญ่: ประมาณค่าด้วย k-source sampling (เร็วขึ้นหลายสิบเท่า,
    # อันดับความสำคัญของถนนแทบไม่เปลี่ยน) — seed คงที่เพื่อผลซ้ำได้
    if is_large_graph:
        k_samples = min(NETWORK_CONFIG["betweenness_k_samples"], node_count)
        betweenness_cent: Dict[Any, float] = nx.edge_betweenness_centrality(
            G_undir, k=k_samples, weight="length", seed=42
        )
    else:
        betweenness_cent = nx.edge_betweenness_centrality(G_undir, weight="length")
    # MultiGraph results are keyed (u, v, key); the lookups below use (u, v).
    betweenness_cent = edge_scores_by_pair(betweenness_cent)
    max_bet = max(betweenness_cent.values()) if betweenness_cent else 1.0

    # Public colormap registry (Matplotlib >= 3.5).
    # matplotlib.cm.get_cmap was removed in newer Matplotlib releases.
    cmap_bet = matplotlib.colormaps["plasma"]

    # ---- Build edge GeoJSON features ----
    edges_geojson: List[Dict[str, Any]] = []
    for u, v, _k, data in G.edges(keys=True, data=True):
        score = betweenness_cent.get(tuple(sorted((u, v))), 0.0)
        norm_score = score / max_bet if max_bet > 0 else 0.0

        if "geometry" in data:
            geom = mapping(data["geometry"])
        else:
            geom = {
                "type": "LineString",
                "coordinates": [
                    [G.nodes[u]["x"], G.nodes[u]["y"]],
                    [G.nodes[v]["x"], G.nodes[v]["y"]],
                ],
            }

        edges_geojson.append(
            {
                "type": "Feature",
                "geometry": geom,
                "properties": {
                    "type": "road",
                    "betweenness": norm_score,
                    "color": colors.to_hex(cmap_bet(norm_score)),
                    "stroke_weight": (
                        NETWORK_CONFIG["edge_weight_base"]
                        + norm_score * NETWORK_CONFIG["edge_weight_multiplier"]
                    ),
                },
            }
        )

    # ---- Build node GeoJSON features ----
    nodes_geojson: List[Dict[str, Any]] = []
    top_node_data: Dict[str, Any] = {"score": -1.0, "lat": 0.0, "lon": 0.0}

    for node, data in G.nodes(data=True):
        score = closeness_cent.get(node, 0.0)
        norm_score = score / max_close if max_close > 0 else 0.0

        if score > top_node_data["score"]:
            top_node_data = {"lat": data["y"], "lon": data["x"], "score": score}

        if norm_score > NETWORK_CONFIG["min_closeness_threshold"]:
            nodes_geojson.append(
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "Point",
                        "coordinates": [data["x"], data["y"]],
                    },
                    "properties": {
                        "type": "intersection",
                        "closeness": norm_score,
                        "color": "#000000",
                        "radius": 2 + norm_score * 6,
                    },
                }
            )

    # ---- Golden land opportunity ranking ----
    golden_spots = compute_golden_land_opportunities(
        G,
        closeness_cent,
        betweenness_cent,
        top_n=NETWORK_CONFIG["golden_land_top_n"],
    )
    golden_geojson_features: List[Dict[str, Any]] = []
    for idx, spot in enumerate(golden_spots, start=1):
        golden_geojson_features.append(
            {
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [spot["lon"], spot["lat"]],
                },
                "properties": {
                    "type": "golden_spot",
                    "rank": idx,
                    "score": round(spot["score"], 4),
                },
            }
        )

    return {
        "edges": {"type": "FeatureCollection", "features": edges_geojson},
        "nodes": {"type": "FeatureCollection", "features": nodes_geojson},
        "golden_spots": golden_spots,
        "golden_spots_geojson": {
            "type": "FeatureCollection",
            "features": golden_geojson_features,
        },
        "top_node": top_node_data if top_node_data["score"] != -1.0 else None,
        # ~11 m simplification keeps exports small; area error is negligible.
        "coverage_geojson": mapping(
            wkt.loads(polygon_wkt_str).simplify(1e-4, preserve_topology=True)
        ),
        "stats": {
            "nodes_count": len(G.nodes),
            "edges_count": len(G.edges),
            "used_approximation": is_large_graph,
            "closeness_method": closeness_method,
            "was_cached": was_cached,
        },
    }
