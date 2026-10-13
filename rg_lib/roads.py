"""Pure engine — road-network anchors: ``find_cbd_anchors``, weighted closeness, CSR/Dijkstra. No streamlit, no I/O.

Definitions are cut verbatim from pages/Rent_Gradient.py (see tests/test_rg_v2_equivalence.py).
"""


import networkx as nx
import time
from pyproj import CRS
from typing import Any, Dict, List, Optional, Tuple

from .compat import HAS_SCIPY, csgraph_components, csgraph_dijkstra, csr_matrix, np
from .config import ANCHOR_CONFIG, NETWORK_CONFIG
from .geo import _anchor_projection, anchor_study_polygon, calculate_distance_meters


def _node_sort_key(node: Any) -> Tuple[str, str]:
    """Type-aware ordering so ties never depend on graph insertion order."""
    return (type(node).__name__, str(node))


def _collapsed_csr(
    graph: nx.Graph, nodes: List[Any], default_length: Optional[float] = None
) -> "csr_matrix":
    """Symmetric CSR of the shortest road length between each pair of ``nodes``.

    Parallel and opposite-direction edges collapse to their minimum length and
    self loops are dropped. Pure numpy after one pass over the edges; this is the
    one road-matrix builder shared by the anchor search and network analysis.
    """
    index = {node: i for i, node in enumerate(nodes)}
    us: List[int] = []
    vs: List[int] = []
    raw: List[Any] = []
    for u, v, length in graph.edges(data="length", default=default_length):
        if u == v or u not in index or v not in index:
            continue
        us.append(index[u])
        vs.append(index[v])
        raw.append(length)
    if any(length is None for length in raw):
        raise ValueError("Every road edge must have length in metres.")
    try:
        lengths = np.asarray(raw, dtype=float)
    except (TypeError, ValueError) as exc:
        raise ValueError("Every road edge must have length in metres.") from exc
    if len(lengths) and (not np.isfinite(lengths).all() or (lengths <= 0).any()):
        raise ValueError("Road lengths must be finite and positive.")
    n = len(nodes)
    if not len(lengths):
        return csr_matrix((n, n), dtype=float)
    a = np.asarray(us, dtype=np.int64)
    b = np.asarray(vs, dtype=np.int64)
    lo, hi = np.minimum(a, b), np.maximum(a, b)
    pair = lo * n + hi
    order = np.lexsort((lengths, pair))  # by pair, then shortest length first
    pair_sorted = pair[order]
    first = np.concatenate(([True], pair_sorted[1:] != pair_sorted[:-1]))
    keep = order[first]
    rows = np.concatenate((lo[keep], hi[keep]))
    cols = np.concatenate((hi[keep], lo[keep]))
    vals = np.concatenate((lengths[keep], lengths[keep]))
    return csr_matrix((vals, (rows, cols)), shape=(n, n))


def _dijkstra_batches(matrix: "csr_matrix", sources: Any):
    """Yield ``(sources_in_batch, rows)`` with at most ``batch_size`` exact rows at once.

    Never materialises an all-pairs matrix: memory stays O(batch_size * V).
    """
    size = ANCHOR_CONFIG["batch_size"]
    for start in range(0, len(sources), size):
        part = sources[start:start + size]
        yield part, csgraph_dijkstra(matrix, directed=False, indices=part)


def _road_network(graph: nx.Graph) -> Dict[str, Any]:
    """Largest undirected road component as a CSR matrix plus WGS84 coordinates."""
    all_nodes = sorted(graph.nodes, key=_node_sort_key)
    full = _collapsed_csr(graph, all_nodes)
    n_components, labels = csgraph_components(full, directed=False)
    sizes = np.bincount(labels, minlength=n_components)
    first_index = np.full(n_components, len(all_nodes))
    np.minimum.at(first_index, labels, np.arange(len(all_nodes)))
    biggest = np.flatnonzero(sizes == sizes.max())
    component = biggest[np.argmin(first_index[biggest])]  # ties: lowest sorted node
    keep = np.flatnonzero(labels == component)
    nodes = [all_nodes[i] for i in keep]
    if len(nodes) < 2:
        raise ValueError("No connected roads available in the study area.")
    try:
        lonlat = np.array([(float(graph.nodes[n]["x"]), float(graph.nodes[n]["y"]))
                           for n in nodes])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("Every road node requires WGS84 x/y coordinates.") from exc
    return {"nodes": nodes, "matrix": full[keep][:, keep].tocsr(), "lonlat": lonlat,
            "components": int(n_components), "total_nodes": len(all_nodes)}


def _stability_cases(study_radius_m: float) -> List[Dict[str, Any]]:
    """Perturbed study circles: rescaled radius, and centre shifted N/E/S/W."""
    shift = ANCHOR_CONFIG["stability_shift"] * study_radius_m
    cases: List[Dict[str, Any]] = [
        {"case": f"radius x{scale:g}", "dx": 0.0, "dy": 0.0, "radius": study_radius_m * scale}
        for scale in ANCHOR_CONFIG["stability_scales"]
    ]
    for name, (ux, uy) in (("N", (0, 1)), ("E", (1, 0)), ("S", (0, -1)), ("W", (-1, 0))):
        cases.append({"case": f"centre {ANCHOR_CONFIG['stability_shift']:.0%} {name}",
                      "dx": ux * shift, "dy": uy * shift, "radius": study_radius_m})
    return cases


def find_cbd_anchors(
    graph: nx.MultiDiGraph,
    study_center: Tuple[float, float],
    study_radius_m: float = 10000.0,
    final_radius_m: float = 150.0,
    max_rows: Optional[int] = None,
    stability: bool = True,
) -> Dict[str, Any]:
    """Composite and Closeness-100% anchors from one road graph, without I/O.

    Deterministic: no seed, no restarts. Exact length-weighted SciPy Dijkstra on
    the largest undirected component (street accessibility, not one-way routing);
    parallel and reverse edges use the minimum length. Destinations and anchors
    lie inside the study circle; paths may use buffer nodes. Junctions have >=3
    distinct neighbours; density counts them within 500 metric metres.

    Both objectives share one distance pass, so each exact row (closeness) is
    computed once:

    * composite - junction candidates (all inside nodes only if none exist),
      Score = .5*C_rank + .3*degree_rank + .2*density_rank with degree/density
      as mid-rank percentiles over the candidate pool and C_rank = Phi((C -
      mean)/std) from the exact closeness of a fixed reference sample.
    * closeness - every inside node is a candidate, Score = C/(C + 1/R), strictly
      monotone in C, hence the raw length-weighted 1-median.

    Each objective is exhaustive when its candidate pool fits ``rows_budget``
    (``max_rows`` or ``max_row_nodes // V`` clamped): the global maximum of the
    fixed objective is then certified. Otherwise every candidate is ranked with
    the reference sample's distances (Eppstein-Wang pivots), the top-K are scored
    exactly and a local exhaustive climb (``final_radius_m``) polishes the best:
    seed-independent and stable, but not a global certificate. Neither proves an
    economic CBD.

    ``stability`` adds an *indicative* probe at almost no cost: the pivot rows are
    also summed per perturbed circle (radius x0.8/x1.2, centre shifted 20% of the
    radius N/E/S/W), the best few candidates of each case are scored exactly on
    that case's destinations, and the drift of the best one from the anchor is
    reported with a stable / check / unstable level. The exact oracle is
    ``scripts/anchor_sensitivity.py``.
    """
    if not HAS_SCIPY:
        raise RuntimeError("Automated CBD search requires SciPy and NumPy.")
    from scipy.spatial import cKDTree
    from scipy.special import ndtr

    started = time.perf_counter()
    anchor_study_polygon(*study_center, study_radius_m)
    if not 0 < final_radius_m <= study_radius_m:
        raise ValueError("Require 0 < final radius <= study radius.")
    if max_rows is not None and not 1 <= max_rows <= 10000:
        raise ValueError("Invalid row budget.")
    if not 2 <= len(graph) <= ANCHOR_CONFIG["max_nodes"]:
        raise ValueError("Road graph must contain 2–100,000 nodes; reduce the study area.")
    if CRS.from_user_input(graph.graph.get("crs", "EPSG:4326")) != CRS.from_epsg(4326):
        raise ValueError("Road graph must use WGS84 longitude/latitude (EPSG:4326).")

    net = _road_network(graph)
    nodes, matrix, lonlat = net["nodes"], net["matrix"], net["lonlat"]
    n = len(nodes)
    if (not np.isfinite(lonlat).all() or (np.abs(lonlat[:, 0]) > 180).any()
            or (np.abs(lonlat[:, 1]) > 90).any()):
        raise ValueError("Invalid road node coordinates.")
    projection = _anchor_projection(*study_center)
    xy = np.column_stack(projection.transform(lonlat[:, 0], lonlat[:, 1]))
    radial_distance = np.linalg.norm(xy, axis=1)
    eligible = np.flatnonzero(radial_distance <= study_radius_m)
    if len(eligible) < 2:
        raise ValueError("Fewer than two connected road nodes inside the study circle.")
    prep_done = time.perf_counter()

    degrees = np.diff(matrix.indptr).astype(float)  # distinct neighbours (no parallels)
    junctions = np.flatnonzero(degrees >= 3)
    composite_pool = eligible[degrees[eligible] >= 3]
    junction_fallback = len(composite_pool) == 0
    if junction_fallback:
        composite_pool = eligible
    pools = {"composite": composite_pool, "closeness": eligible}
    density = np.zeros(n)
    density_nodes = np.arange(n) if stability else eligible  # perturbed circles reach outside
    if len(junctions):
        # Inclusive radius with a sub-micrometre tolerance: lattice points that sit
        # exactly on the circle land at 500 ± 1e-9 m after the CRS round trip, so a
        # bare "<= 500" would depend on pyproj/libm rounding rather than geometry.
        density[density_nodes] = cKDTree(xy[junctions]).query_ball_point(
            xy[density_nodes], ANCHOR_CONFIG["density_radius_m"] + 1e-6, return_length=True)
    # Diagnostics (and the Closeness-100% record): share of the inside maximum.
    degree_norm = degrees / max(float(degrees[eligible].max()), 1.0)
    density_norm = density / max(float(density[eligible].max()), 1.0)

    def midrank(values, pool_nodes):
        """Mid-rank percentile of each value within ``pool_nodes``, in (0, 1)."""
        pool = np.sort(values[pool_nodes])
        return (np.searchsorted(pool, values, side="left")
                + np.searchsorted(pool, values, side="right")) / (2.0 * len(pool))

    degree_rank = midrank(degrees, composite_pool)
    density_rank = midrank(density, composite_pool)
    weights = {"closeness": 0.50, "degree": 0.30, "density": 0.20}
    n_destinations = len(eligible)
    rows_budget = int(max_rows) if max_rows else int(np.clip(
        ANCHOR_CONFIG["max_row_nodes"] // n, ANCHOR_CONFIG["min_rows"], ANCHOR_CONFIG["max_rows"]))

    # Fixed reference sample of destinations (constant seed): exact closeness
    # calibrates the composite normaliser and the summed distance rows rank every
    # candidate by pivot closeness. Its rows are shared, never recomputed.
    # The sample size is a property of the graph, not of the run: it fixes the composite
    # normaliser, so it must not move with ``max_rows`` or the objective would change
    # between a certified run and a screened one. Huge graphs use fewer pivots (their
    # rows cost the most) — at 100k nodes that is ~half of the previous pivot time.
    ref_target = float(ANCHOR_CONFIG["reference_nodes"])
    if n > ANCHOR_CONFIG["reference_shrink_above_nodes"]:
        ref_target = max(float(ANCHOR_CONFIG["reference_min_nodes"]),
                         ref_target * (ANCHOR_CONFIG["reference_shrink_above_nodes"] / n) ** 0.5)
    n_ref = min(n_destinations, int(round(ref_target)))
    ref_nodes = np.sort(np.random.default_rng(ANCHOR_CONFIG["reference_seed"]).choice(
        eligible, size=n_ref, replace=False))
    ref_c = np.empty(n_ref)
    pivot_sum = np.zeros(n)
    cases = _stability_cases(study_radius_m) if stability else []
    case_inside = np.zeros((n, len(cases)), dtype=bool)
    for k, case in enumerate(cases):
        case_inside[:, k] = np.hypot(xy[:, 0] - case["dx"], xy[:, 1] - case["dy"]) <= case["radius"]
    case_float = case_inside.astype(float)
    # Two strata of destinations for the perturbed circles: the base circle (the pivots
    # above) and the ring just outside it, which a x1.2 or shifted circle pulls in. Sampling
    # only the base circle would leave mass outside it invisible to the probe.
    outer_pool = (np.flatnonzero((radial_distance > study_radius_m) & case_inside.any(axis=1))
                  if cases else np.empty(0, dtype=int))
    n_out = min(len(outer_pool), int(ANCHOR_CONFIG["stability_outer_nodes"]))
    out_nodes = (np.sort(np.random.default_rng(ANCHOR_CONFIG["reference_seed"] + 1).choice(
        outer_pool, size=n_out, replace=False)) if n_out else np.empty(0, dtype=int))
    sources = np.concatenate((ref_nodes, out_nodes)).astype(int)
    case_pivot_sum = np.zeros((n, len(cases)))   # S1: sum over base pivots inside each circle
    case_outer_sum = np.zeros((n, len(cases)))   # S2: same over ring pivots
    case_ref_sum = np.zeros((len(sources), len(cases)))
    # Distances from each exact row to every case's destinations: a by-product of
    # the base pass, so the probe re-runs Dijkstra only for rows it has not seen.
    case_sums: Dict[int, np.ndarray] = {}
    filled = 0
    for part, rows_d in _dijkstra_batches(matrix, sources):
        position = np.arange(filled, filled + len(part))
        is_base = position < n_ref
        if is_base.any():
            ref_c[position[is_base]] = (n_destinations - 1) / rows_d[is_base][:, eligible].sum(axis=1)
            pivot_sum += rows_d[is_base].sum(axis=0)
        if cases:  # per-case sums over the pivots that fall inside each perturbed circle
            if is_base.any():
                case_pivot_sum += rows_d[is_base].T @ case_float[part[is_base]]
            if (~is_base).any():
                case_outer_sum += rows_d[~is_base].T @ case_float[part[~is_base]]
            chunk = rows_d @ case_float
            case_ref_sum[position] = chunk
            case_sums.update((int(i), row) for i, row in zip(part, chunk))
        filled += len(part)
    ref_mean, ref_std = float(ref_c.mean()), float(ref_c.std())

    # Stratified (Horvitz-Thompson) estimate of the summed distance to each case's
    # destinations: sum_u d(v,u) ~ (n1/k1) S1 + (n2/k2) S2, with n_j the nodes of stratum
    # j inside the circle and k_j the pivots of that stratum inside it.
    case_sum_hat = np.zeros((n, len(cases)))
    case_norm = []
    for k in range(len(cases)):
        n1c = int(case_inside[eligible, k].sum())
        n2c = int(case_inside[outer_pool, k].sum()) if len(outer_pool) else 0
        k1c = int(case_inside[ref_nodes, k].sum())
        k2c = int(case_inside[out_nodes, k].sum()) if n_out else 0
        w1 = n1c / k1c if k1c else 0.0
        w2 = n2c / k2c if k2c else 0.0
        if n2c and not k2c and k1c:       # no ring pivot inside: borrow the base mean distance
            w2 = n2c / k1c
            case_sum_hat[:, k] = w1 * case_pivot_sum[:, k] + w2 * case_pivot_sum[:, k]
        elif n1c and not k1c and k2c:
            w1 = n1c / k2c
            case_sum_hat[:, k] = w1 * case_outer_sum[:, k] + w2 * case_outer_sum[:, k]
        else:
            case_sum_hat[:, k] = w1 * case_pivot_sum[:, k] + w2 * case_outer_sum[:, k]
        # Per-case normaliser: exact closeness of the pivots inside the circle, weighted by
        # how many destinations each one represents.
        members = np.concatenate((ref_nodes[case_inside[ref_nodes, k]], out_nodes[case_inside[out_nodes, k]]))
        weights_k = np.concatenate((np.full(k1c, w1), np.full(k2c, w2)))
        pos_k = np.concatenate((np.flatnonzero(case_inside[ref_nodes, k]),
                                n_ref + np.flatnonzero(case_inside[out_nodes, k]))) if len(members) else np.empty(0, int)
        if len(members) > 1 and weights_k.sum() > 0:
            c_k = (n1c + n2c - 1) / np.maximum(case_ref_sum[pos_k, k], 1e-9)
            mu = float(np.average(c_k, weights=weights_k))
            var = float(np.average((c_k - mu) ** 2, weights=weights_k))
            case_norm.append((mu, var ** 0.5))
        else:
            case_norm.append((ref_mean, ref_std))
    exact_c: Dict[int, float] = {int(p): float(c) for p, c in zip(ref_nodes, ref_c)}
    pivots_done = time.perf_counter()

    def ensure_exact(candidates):
        """Exact closeness for every candidate lacking it (one shared row each)."""
        missing = [int(i) for i in candidates if int(i) not in exact_c]
        for part, rows_d in _dijkstra_batches(matrix, missing):
            for i, c in zip(part, (n_destinations - 1) / rows_d[:, eligible].sum(axis=1)):
                exact_c[int(i)] = float(c)
            if cases:
                case_sums.update((int(i), row) for i, row in zip(part, rows_d @ case_float))
        return len(missing)

    def closeness_component(c, objective, norm=None):
        """Closeness mapped onto 0..1 (scalar or array), fixed for the whole search."""
        if objective == "closeness":
            return c / (c + 1.0 / study_radius_m)
        mean, std = norm if norm is not None else (ref_mean, ref_std)
        if std <= 0:
            return np.full_like(np.asarray(c, dtype=float), 0.5)
        return ndtr((c - mean) / std)

    def components(i, objective):
        c = exact_c[i]
        cn = float(closeness_component(c, objective))
        if objective == "closeness":
            dn, jn = float(degree_norm[i]), float(density_norm[i])
            score = cn
        else:
            dn, jn = float(degree_rank[i]), float(density_rank[i])
            score = (weights["closeness"] * cn
                     + weights["degree"] * dn + weights["density"] * jn)
        return {"score": float(score), "closeness": float(c), "closeness_norm": cn,
                "degree_norm": dn, "density_norm": jn,
                "degree": int(degrees[i]), "junction_count": int(density[i])}

    def best_of(candidates, objective):
        # Scores are quantised so mathematically tied nodes stay tied whatever the
        # summation order or library version; the lowest node index then wins.
        return max((int(i) for i in candidates),
                   key=lambda i: (round(components(i, objective)["score"], 12), -i))

    def probe(objective, base_winner):
        """Indicative drift of the anchor under rescaled / shifted study circles."""
        # Candidates are every junction (all nodes for Closeness 100%) inside each
        # perturbed circle, not just those of the base circle: a x1.2 or shifted circle
        # can have its best node outside the base one.
        pool = (np.flatnonzero(degrees >= 3)
                if objective == "composite" and not junction_fallback else np.arange(n))
        picks: List[np.ndarray] = []
        case_ranks: List[Tuple[np.ndarray, np.ndarray]] = []
        for k in range(len(cases)):
            inside = case_inside[pool, k]
            cand = pool[inside]
            if objective == "composite" and len(cand):
                # degree/density percentiles are re-taken inside each perturbed circle
                case_ranks.append((midrank(degrees, cand), midrank(density, cand)))
            else:
                case_ranks.append((degree_rank, density_rank))
            if not len(cand):
                picks.append(cand)
                continue
            n_case = int(case_inside[:, k].sum())
            approx_c = (n_case - 1) / np.maximum(case_sum_hat[cand, k], 1e-9)
            if objective == "closeness":
                approx = approx_c
            else:
                approx = (weights["closeness"] * closeness_component(approx_c, objective, case_norm[k])
                          + weights["degree"] * case_ranks[k][0][cand]
                          + weights["density"] * case_ranks[k][1][cand])
            order = np.lexsort((cand, -approx))
            picks.append(cand[order[:int(ANCHOR_CONFIG["stability_top_m"])]])
        needed = sorted({int(i) for pick in picks for i in pick} - case_sums.keys())
        for part, rows_d in _dijkstra_batches(matrix, needed):
            case_sums.update((int(i), row) for i, row in zip(part, rows_d @ case_float))
        reach_limit = float(radial_distance.max())
        out = []
        for k, case in enumerate(cases):
            n_dest = int(case_inside[:, k].sum())
            best, best_key = None, None
            for i in picks[k]:
                i = int(i)
                c = (n_dest - 1) / case_sums[i][k] if case_sums[i][k] > 0 else 0.0
                if objective == "closeness":
                    score = c
                else:
                    score = (weights["closeness"] * float(closeness_component(c, objective, case_norm[k]))
                             + weights["degree"] * float(case_ranks[k][0][i])
                             + weights["density"] * float(case_ranks[k][1][i]))
                if best_key is None or (round(score, 12), -i) > best_key:
                    best, best_key = i, (round(score, 12), -i)
            if best is None:
                out.append({"case": case["case"], "drift_m": None, "node_id": None})
                continue
            drift = calculate_distance_meters(
                lonlat[base_winner, 1], lonlat[base_winner, 0], lonlat[best, 1], lonlat[best, 0])
            out.append({"case": case["case"], "drift_m": float(drift), "node_id": str(nodes[best]),
                        "lat": float(lonlat[best, 1]), "lon": float(lonlat[best, 0]),
                        "covered": bool(np.hypot(case["dx"], case["dy"]) + case["radius"] <= reach_limit)})
        drifts = [c["drift_m"] for c in out if c["drift_m"] is not None]
        if not drifts:
            return None
        worst = max(drifts)
        ratio = worst / study_radius_m
        level = ("stable" if ratio <= ANCHOR_CONFIG["stability_ok_ratio"]
                 else "check" if ratio <= ANCHOR_CONFIG["stability_warn_ratio"] else "unstable")
        return {"method": "pivot-screen + exact top-M per case (per-case pivot normaliser)",
                "indicative": True, "cases": out, "max_drift_m": float(worst),
                "median_drift_m": float(np.median(drifts)), "max_drift_ratio": float(ratio),
                "level": level}

    def solve(objective):
        """Exhaustive when the pool fits the row budget, else screen + refine."""
        pool = pools[objective]
        screening = None
        if len(pool) <= rows_budget:
            ensure_exact(pool)
            winner = best_of(pool, objective)
            certified, refined = True, True
        else:
            k_eff = n_ref - np.isin(pool, ref_nodes).astype(float)  # a pivot skips d(p,p)=0
            approx_c = k_eff / np.maximum(pivot_sum[pool], 1e-9)
            if objective == "closeness":
                approx_score = approx_c
            else:
                approx_score = (weights["closeness"] * closeness_component(approx_c, objective)
                                + weights["degree"] * degree_rank[pool]
                                + weights["density"] * density_rank[pool])
            top_k = min(int(ANCHOR_CONFIG["screen_top_k"]), rows_budget)
            order = np.lexsort((pool, -approx_score))  # score desc, node index asc
            chosen = [int(pool[j]) for j in order[:top_k]]
            extra = ensure_exact(chosen)
            tree = cKDTree(xy[pool])
            pool_set = set(pool.tolist())
            # every pool node that already has an exact row competes (pivots, and the
            # other objective's exhaustive pass), not only this objective's own picks
            scored = [i for i in exact_c if i in pool_set]
            current = best_of(scored, objective)
            refined = False
            for _ in range(int(ANCHOR_CONFIG["refine_iterations"])):
                around = [current] + [int(pool[j]) for j in
                                      tree.query_ball_point(xy[current], final_radius_m)]
                fresh = len([i for i in around if i not in exact_c])
                if extra + fresh > rows_budget:
                    break
                extra += ensure_exact(around)
                best = best_of(around, objective)
                if components(best, objective)["score"] > components(current, objective)["score"] + 1e-12:
                    current = best
                else:
                    refined = True
                    break
            winner, certified = current, False
            screening = {"pivots": n_ref, "screened_top_k": len(chosen),
                         "extra_rows": extra, "refine_converged": refined}

        anchor = dict(
            {"node_id": str(nodes[winner]), "lat": float(lonlat[winner, 1]),
             "lon": float(lonlat[winner, 0]), **components(winner, objective)},
            source=("Automated CBD Anchor — Closeness 100%"
                    if objective == "closeness" else "Automated CBD Anchor"),
        )
        warnings = []
        if not certified:
            warnings.append(
                f"กราฟเกินงบตรวจครบทุกโหนด: คัดผู้สมัครด้วย pivot closeness ({screening['pivots']} จุด) "
                f"แล้วประเมินแม่นยำ {screening['screened_top_k']} อันดับแรกและไต่ต่อเฉพาะที่ — "
                "เสถียร (ไม่ขึ้นกับ seed) แต่ไม่รับรอง global optimum")
        if net["components"] > 1:
            warnings.append(f"ใช้ component ใหญ่ที่สุด; ตัด {net['total_nodes'] - n} โหนดที่ไม่เชื่อมต่อ")
        boundary_margin = float(study_radius_m - radial_distance[winner])
        if boundary_margin < ANCHOR_CONFIG["boundary_warn_ratio"] * study_radius_m:
            warnings.append("Anchor ใกล้ขอบพื้นที่ศึกษา: ควรขยายพื้นที่แล้วเปรียบเทียบผล")
        if objective == "composite" and junction_fallback:
            warnings.append("ไม่พบทางแยกในพื้นที่ศึกษา: ใช้โหนดถนนทั่วไปเป็นผู้สมัคร Anchor แทน")

        # Report the weights that actually move the ranking, not only the nominal ones.
        if objective == "composite":
            spread_c = (float(ndtr((ref_c - ref_mean) / ref_std).std()) if ref_std > 0 else 0.0)
            influence = {
                "closeness": weights["closeness"] * spread_c,
                "degree": weights["degree"] * float(degree_rank[composite_pool].std()),
                "density": weights["density"] * float(density_rank[composite_pool].std()),
            }
            total_influence = sum(influence.values())
            effective = {k: (v / total_influence if total_influence > 0 else weights[k])
                         for k, v in influence.items()}
            win = components(winner, objective)
            contribution = {
                "closeness": weights["closeness"] * win["closeness_norm"] / win["score"],
                "degree": weights["degree"] * win["degree_norm"] / win["score"],
                "density": weights["density"] * win["density_norm"] / win["score"],
            } if win["score"] > 0 else dict(weights)
            scoring = "rank-v2"
            nominal = dict(weights)
            normalisation = {
                "closeness": {"type": "normal-cdf-z", "mean": ref_mean, "std": ref_std,
                              "reference_nodes": n_ref},
                "degree": {"type": "mid-rank-percentile", "pool": len(composite_pool)},
                "density": {"type": "mid-rank-percentile", "pool": len(composite_pool)},
            }
        else:
            effective = nominal = contribution = {"closeness": 1.0, "degree": 0.0, "density": 0.0}
            scoring = "closeness-bounded"
            normalisation = {"closeness": {"type": "C/(C+1/study_radius)"}}

        method = "exact-scipy" if certified else "pivot-screened-exact-scipy"
        if objective == "closeness":
            method += "-closeness-100"
        stability_result = probe(objective, winner) if cases else None
        if stability_result and stability_result["level"] != "stable":
            warnings.append(
                f"Anchor ขยับได้ถึง {stability_result['max_drift_m']:.0f} ม. "
                f"({stability_result['max_drift_ratio']:.0%} ของรัศมี) เมื่อวงศึกษาเปลี่ยน ±20% — "
                "ผลขึ้นกับวงที่เลือก (ประมาณการ)")
        return {
            "anchor": anchor, "converged": bool(refined), "method": method,
            "objective": objective, "density_source": "road-junctions-only",
            "globally_certified": certified,
            "certification": ("exhaustive-fixed-objective" if certified
                              else "pivot-screened-exact-top-k"),
            "screening": screening, "scoring": scoring, "nominal_weights": dict(nominal),
            "effective_weights": dict(effective), "winner_contribution": dict(contribution),
            "normalisation": normalisation,
            "study_center": list(study_center), "study_radius_m": study_radius_m,
            "evaluated_nodes": int(sum(1 for i in pool if int(i) in exact_c)),
            "graph_nodes": n, "candidate_nodes": int(len(pool)),
            "junction_fallback": bool(objective == "composite" and junction_fallback),
            "destination_nodes": int(n_destinations), "boundary_margin_m": boundary_margin,
            "warnings": warnings, "stability": stability_result,
        }

    results = {objective: solve(objective) for objective in ("composite", "closeness")}

    def top_nodes(objective: str, limit: int) -> List[int]:
        in_pool = set(pools[objective].tolist())
        ranked = sorted((i for i in exact_c if i in in_pool),
                        key=lambda i: (round(components(i, objective)["score"], 12), -i), reverse=True)
        return ranked[:limit]

    candidate_nodes: List[int] = []
    for i in top_nodes("composite", ANCHOR_CONFIG["candidate_export"]) + top_nodes(
            "closeness", ANCHOR_CONFIG["candidate_export"]):
        if i not in candidate_nodes:
            candidate_nodes.append(i)
    composite_pool_set = set(composite_pool.tolist())
    evidence_candidates = []
    for i in candidate_nodes:
        comp = components(i, "composite")
        evidence_candidates.append({
            "node_id": str(nodes[i]), "lat": float(lonlat[i, 1]), "lon": float(lonlat[i, 0]),
            "composite_score": comp["score"], "closeness_norm": comp["closeness_norm"],
            "degree": int(degrees[i]), "junction_count": int(density[i]),
            "in_composite_pool": bool(i in composite_pool_set),
        })
    finished = time.perf_counter()
    timings = {"prep_s": prep_done - started, "pivots_s": pivots_done - prep_done,
               "exact_s": finished - pivots_done, "compute_s": finished - started}
    for result in results.values():
        result["compute_seconds"] = timings["compute_s"]
        result["timings"] = timings
    return {**results, "timings": timings, "rows_budget": rows_budget,
            "evidence_candidates": evidence_candidates,
            "graph": {"nodes": n, "edges": int(matrix.nnz // 2),
                      "dropped_nodes": net["total_nodes"] - n},
            "study_center": list(study_center), "study_radius_m": study_radius_m}


def compute_weighted_closeness(
    G_undir: nx.MultiGraph,
) -> Tuple[Dict[Any, float], str]:
    """
    Weighted closeness centrality สำหรับหา CBD node (Network 1-Median).

    หลักการ / สมการ:
        v* = argmin_v Σ_u d_len(v,u)  ⟺  argmax C(v) = (N−1) / Σ_u d_len(v,u)
        d_len = shortest path ถ่วงน้ำหนักด้วยความยาวถนนจริง (เมตร)

    ความเสถียร: คำนวณเฉพาะ Largest Connected Component (LCC) —
    โหนดนอก LCC ได้ค่า 0 จึงไม่มีสิทธิ์เป็น top node — และใช้ seed คงที่
    ทำให้ผลซ้ำได้ทุกครั้ง

    ความเร็ว:
      - N ≤ closeness_exact_threshold → exact ด้วย scipy.sparse.csgraph.dijkstra
      - N มากกว่า → Eppstein–Wang pivot sampling (k pivots, seed=42):
            Ĉ(v) = k / Σ_{p∈pivots} d_len(v,p)   (error ~ O(1/√k))
      - ไม่มี scipy → fallback nx.closeness_centrality(distance="length")

    Returns:
        ``(closeness_dict, method)`` โดย method ∈
        {"exact-scipy", "pivot-approx", "networkx-fallback", "trivial"}
    """
    closeness: Dict[Any, float] = {node: 0.0 for node in G_undir.nodes}
    if len(G_undir) < 2:
        return closeness, "trivial"

    lcc_nodes = max(nx.connected_components(G_undir), key=len)
    n = len(lcc_nodes)
    if n < 2:
        return closeness, "trivial"
    G_lcc = G_undir.subgraph(lcc_nodes)

    if not HAS_SCIPY:
        closeness.update(nx.closeness_centrality(G_lcc, distance="length"))
        return closeness, "networkx-fallback"

    # sparse adjacency (min length เมื่อมี parallel/reverse edges) — ตัวสร้างเดียวกับ anchor search
    nodelist = list(G_lcc.nodes)
    csr = _collapsed_csr(G_lcc, nodelist, default_length=1.0)

    if n <= NETWORK_CONFIG["closeness_exact_threshold"]:
        # all-pairs ที่ n <= 3000 (<= ~72 MB); แถวต่อแถวผ่านตัวช่วยเดียวกับ anchor search
        sums = np.empty(n)
        for part, rows_d in _dijkstra_batches(csr, np.arange(n)):
            sums[part] = rows_d.sum(axis=1)
        k_eff = n - 1
        method = "exact-scipy"
    else:
        k = min(NETWORK_CONFIG["closeness_k_pivots"], n)
        rng = np.random.default_rng(42)
        pivots = rng.choice(n, size=k, replace=False)
        sums = np.zeros(n)
        for _part, rows_d in _dijkstra_batches(csr, pivots):
            sums += rows_d.sum(axis=0)
        k_eff = k
        method = "pivot-approx"

    with np.errstate(divide="ignore", invalid="ignore"):
        scores = np.where(np.isfinite(sums) & (sums > 0), k_eff / sums, 0.0)
    for i, node in enumerate(nodelist):
        closeness[node] = float(scores[i])
    return closeness, method
