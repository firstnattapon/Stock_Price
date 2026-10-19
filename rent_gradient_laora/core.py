"""Bid-rent fitted on four distance definitions, measured over a street network.

Idea (Space Syntax x Alonso-Muth-Mills): keep the bid-rent equation

    R(d) = R0 * exp(-lam * d)        <=>        ln R = ln R0 - lam * d

but let ``d`` be defined four ways and see which one explains observed rents best:

=============  ==========================================================  =========
kind           meaning                                                     unit
=============  ==========================================================  =========
euclid         straight line to the anchor (baseline, as Rent_Gradient.py)  km
metric         shortest path along the roads (Dijkstra on lengths)          km
topological    number of segment-to-segment steps (turn cost 1 each,        steps
               optionally only turns sharper than a threshold)
angular        sum of direction changes, 90 deg = 1.0 (straight = 0)        x90 deg
=============  ==========================================================  =========

Topological and angular distance live on the *segment* (line) graph, as in segment
analysis (directed, so doubling back costs a U-turn); metric lives on the intersection graph. The anchor is a *set* of nodes /
segments (e.g. a Main Street), not a single point, and the distance of a rent sample
is measured from the nearest of them.

Simplifications, on purpose: segment direction uses the endpoint chord unless the edge
carries a ``geometry`` with ``coords``; points are projected to a local equirectangular
plane (fine for a city-sized area); parallel / opposite edges collapse to the shortest.

Lambda is per unit of the chosen distance, so it is NOT comparable across kinds. Compare
kinds with leave-one-out RMSE / R^2 / AICc, which share the same dependent variable.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import cos, degrees, acos, log, radians, sqrt
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import networkx as nx
import numpy as np
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import dijkstra as _dijkstra
from scipy.stats import t as _student_t

DISTANCE_KINDS: Tuple[str, ...] = ("euclid", "metric", "topological", "angular")
DISTANCE_UNITS: Dict[str, str] = {
    "euclid": "km",
    "metric": "km",
    "topological": "steps",
    "angular": "x90°",
}

M_PER_DEG_LAT = 110_574.0
M_PER_DEG_LON_EQ = 111_320.0
EPS_COST = 1e-9          # zero-cost transitions must stay explicit in a sparse matrix
MIN_RELIABLE_SAMPLES = 10


# --------------------------------------------------------------------- network
@dataclass(frozen=True)
class RoadNetwork:
    """Collapsed, undirected road network in local metres plus its line graph."""

    node_ids: List[Any]
    node_xy: np.ndarray        # (N, 2) metres in the local plane
    node_lonlat: np.ndarray    # (N, 2) lon, lat
    seg_a: np.ndarray          # (S,) node index, a < b
    seg_b: np.ndarray          # (S,)
    seg_len: np.ndarray        # (S,) metres
    seg_dir_a: np.ndarray      # (S, 2) unit vector leaving node a along the segment
    seg_dir_b: np.ndarray      # (S, 2) unit vector leaving node b along the segment
    lg_from: np.ndarray        # directed line graph: state 2s = segment s a->b, 2s+1 = b->a
    lg_to: np.ndarray          # transition from_state -> to_state at their shared node
    lg_deflection_deg: np.ndarray  # deflection of that transition, 0 (straight) .. 180 (U-turn)
    seg_names: List[Optional[str]]
    origin: Tuple[float, float]    # (lat0, lon0) of the local plane

    @property
    def n_nodes(self) -> int:
        return len(self.node_ids)

    @property
    def n_segments(self) -> int:
        return len(self.seg_a)

    def to_xy(self, lon: Any, lat: Any) -> np.ndarray:
        return _to_xy(lon, lat, self.origin[1], self.origin[0])


@dataclass(frozen=True)
class Anchor:
    """The reference set distances are measured from."""

    node_idx: np.ndarray   # node indices
    seg_idx: np.ndarray    # segment indices (never empty)
    is_line: bool = True   # True: a street (euclid measured to its chords); False: point(s)


def _to_xy(lon: Any, lat: Any, lon0: float, lat0: float) -> np.ndarray:
    lon = np.asarray(lon, dtype=float)
    lat = np.asarray(lat, dtype=float)
    x = (lon - lon0) * cos(radians(lat0)) * M_PER_DEG_LON_EQ
    y = (lat - lat0) * M_PER_DEG_LAT
    return np.stack([x, y], axis=-1)


def _node_sort_key(node: Any) -> Tuple[str, str]:
    return (type(node).__name__, str(node))


def _unit(vec: np.ndarray) -> np.ndarray:
    norm = float(np.hypot(vec[0], vec[1]))
    return vec / norm if norm > 1e-9 else np.zeros(2)


def _first_name(value: Any) -> Optional[str]:
    if isinstance(value, (list, tuple)):
        value = value[0] if value else None
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _edge_directions(
    data: Dict[str, Any], xy_a: np.ndarray, xy_b: np.ndarray, lon0: float, lat0: float
) -> Tuple[np.ndarray, np.ndarray]:
    """Unit vectors leaving a and b along the segment (edge geometry if present)."""
    chord = xy_b - xy_a
    dir_a, dir_b = _unit(chord), _unit(-chord)
    geom = data.get("geometry")
    coords = getattr(geom, "coords", None)
    if coords is None:
        return dir_a, dir_b
    try:
        pts = _to_xy([c[0] for c in coords], [c[1] for c in coords], lon0, lat0)
    except Exception:
        return dir_a, dir_b
    if len(pts) < 2:
        return dir_a, dir_b
    if np.hypot(*(pts[0] - xy_a)) > np.hypot(*(pts[0] - xy_b)):
        pts = pts[::-1]                      # geometry runs b -> a; flip to a -> b
    nxt = next((p for p in pts[1:] if np.hypot(*(p - pts[0])) > 1e-6), None)
    prv = next((p for p in pts[-2::-1] if np.hypot(*(p - pts[-1])) > 1e-6), None)
    if nxt is not None:
        dir_a = _unit(nxt - xy_a)
    if prv is not None:
        dir_b = _unit(prv - xy_b)
    return dir_a, dir_b


def build_network(graph: nx.Graph) -> RoadNetwork:
    """Collapse an OSMnx-style graph (node ``x``/``y`` = lon/lat, edge ``length`` m).

    Edges without ``length`` fall back to the straight-line length of their endpoints.
    """
    nodes = sorted(graph.nodes, key=_node_sort_key)
    if len(nodes) < 2:
        raise ValueError("The road graph needs at least two nodes.")
    index = {node: i for i, node in enumerate(nodes)}
    try:
        lonlat = np.array(
            [(float(graph.nodes[n]["x"]), float(graph.nodes[n]["y"])) for n in nodes]
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("Every road node requires WGS84 x (lon) and y (lat).") from exc
    lat0, lon0 = float(lonlat[:, 1].mean()), float(lonlat[:, 0].mean())
    xy = _to_xy(lonlat[:, 0], lonlat[:, 1], lon0, lat0)

    best: Dict[Tuple[int, int], Tuple[float, Dict[str, Any]]] = {}
    for u, v, data in graph.edges(data=True):
        if u == v:
            continue
        iu, iv = index[u], index[v]
        a, b = (iu, iv) if iu < iv else (iv, iu)
        length = data.get("length")
        try:
            length = float(length)
        except (TypeError, ValueError):
            length = float("nan")
        if not np.isfinite(length) or length <= 0:
            length = float(np.hypot(*(xy[b] - xy[a])))
        if length <= 0:
            continue
        if (a, b) not in best or length < best[(a, b)][0]:
            best[(a, b)] = (length, data)
    if not best:
        raise ValueError("The road graph has no usable edges.")

    pairs = sorted(best)
    seg_a = np.array([p[0] for p in pairs], dtype=np.int64)
    seg_b = np.array([p[1] for p in pairs], dtype=np.int64)
    seg_len = np.array([best[p][0] for p in pairs], dtype=float)
    dirs = [_edge_directions(best[p][1], xy[p[0]], xy[p[1]], lon0, lat0) for p in pairs]
    seg_dir_a = np.array([d[0] for d in dirs])
    seg_dir_b = np.array([d[1] for d in dirs])
    seg_names = [_first_name(best[p][1].get("name")) for p in pairs]

    incident: List[List[int]] = [[] for _ in nodes]
    for s in range(len(pairs)):
        incident[seg_a[s]].append(s)
        incident[seg_b[s]].append(s)
    # Directed line graph: a state is a segment travelled one way. Arriving at node n on
    # segment s and leaving on t costs the deflection between the two headings. Doubling
    # back is only allowed at a dead end (degree 1), so a traveller cannot "turn" for free
    # by detouring down a spur.
    t_from: List[int] = []
    t_to: List[int] = []
    t_def: List[float] = []
    for n, segs in enumerate(incident):
        def arrive(s: int) -> int:
            return 2 * s if seg_b[s] == n else 2 * s + 1

        def depart(s: int) -> int:
            return 2 * s if seg_a[s] == n else 2 * s + 1

        def leaving(s: int) -> np.ndarray:
            return seg_dir_a[s] if seg_a[s] == n else seg_dir_b[s]

        for s in segs:
            for t in segs:
                if s == t:
                    continue
                between = degrees(acos(float(np.clip(np.dot(leaving(s), leaving(t)), -1.0, 1.0))))
                t_from.append(arrive(s))
                t_to.append(depart(t))
                t_def.append(180.0 - between)
        if len(segs) == 1:
            s = segs[0]
            t_from.append(arrive(s))
            t_to.append(depart(s))
            t_def.append(180.0)
    return RoadNetwork(
        node_ids=nodes,
        node_xy=xy,
        node_lonlat=lonlat,
        seg_a=seg_a,
        seg_b=seg_b,
        seg_len=seg_len,
        seg_dir_a=seg_dir_a,
        seg_dir_b=seg_dir_b,
        lg_from=np.array(t_from, dtype=np.int64),
        lg_to=np.array(t_to, dtype=np.int64),
        lg_deflection_deg=np.array(t_def, dtype=float),
        seg_names=seg_names,
        origin=(lat0, lon0),
    )


def _sym_csr(n: int, rows: np.ndarray, cols: np.ndarray, vals: np.ndarray) -> csr_matrix:
    if len(rows) == 0:
        return csr_matrix((n, n), dtype=float)
    return csr_matrix(
        (np.concatenate([vals, vals]), (np.concatenate([rows, cols]), np.concatenate([cols, rows]))),
        shape=(n, n),
    )


def _node_matrix(net: RoadNetwork) -> csr_matrix:
    return _sym_csr(net.n_nodes, net.seg_a, net.seg_b, net.seg_len)


def _segment_matrix(net: RoadNetwork, kind: str, turn_deg: float) -> csr_matrix:
    """Directed state graph (2 states per segment) weighted by the transition cost."""
    if kind == "topological":
        counted = np.ones(len(net.lg_deflection_deg), dtype=bool) if turn_deg <= 0 \
            else net.lg_deflection_deg > turn_deg      # 0 = every step counts
        cost = np.where(counted, 1.0, 0.0)
    elif kind == "angular":
        cost = net.lg_deflection_deg / 90.0
    else:
        raise ValueError(f"No segment graph for distance kind {kind!r}.")
    n = 2 * net.n_segments
    return csr_matrix((np.maximum(cost, EPS_COST), (net.lg_from, net.lg_to)), shape=(n, n))


# ---------------------------------------------------------------------- anchor
def list_street_names(net: RoadNetwork, limit: int = 40) -> List[Tuple[str, float]]:
    """Named streets of ``net`` as ``(name, total_length_m)``, longest first.

    Lengths come from the collapsed network, so a two-way street is not counted twice.
    """
    totals: Dict[str, float] = {}
    for name, length in zip(net.seg_names, net.seg_len):
        if name is not None:
            totals[name] = totals.get(name, 0.0) + float(length)
    return sorted(totals.items(), key=lambda kv: (-kv[1], kv[0]))[:limit]


def _anchor_from_nodes(net: RoadNetwork, node_idx: Iterable[int]) -> Anchor:
    nodes = np.unique(np.asarray(list(node_idx), dtype=np.int64))
    if len(nodes) == 0:
        raise ValueError("The anchor is empty.")
    inside = np.zeros(net.n_nodes, dtype=bool)
    inside[nodes] = True
    segs = np.flatnonzero(inside[net.seg_a] & inside[net.seg_b])   # along the street itself
    is_line = len(segs) > 0
    if not is_line:                                                 # point(s): their streets
        segs = np.flatnonzero(inside[net.seg_a] | inside[net.seg_b])
    if len(segs) == 0:
        raise ValueError("The anchor nodes have no road segments.")
    return Anchor(node_idx=nodes, seg_idx=segs, is_line=is_line)


def anchor_from_points(net: RoadNetwork, points: Sequence[Tuple[float, float]]) -> Anchor:
    """Anchor from ``(lat, lon)`` points, each snapped to its nearest road node.

    One point = a single reference (CBD centre). Several points along a street =
    that street. Only the endpoints of the street need to be listed densely enough
    for the snapped nodes to follow it.
    """
    pts = [(float(lat), float(lon)) for lat, lon in points]
    if not pts:
        raise ValueError("The anchor needs at least one point.")
    xy = net.to_xy([p[1] for p in pts], [p[0] for p in pts])
    d2 = ((xy[:, None, :] - net.node_xy[None, :, :]) ** 2).sum(axis=2)
    return _anchor_from_nodes(net, np.argmin(d2, axis=1))


def anchor_from_street_names(net: RoadNetwork, names: Sequence[str]) -> Anchor:
    """Anchor made of every segment carrying one of the OSM street ``names``."""
    wanted = {str(n) for n in names}
    segs = [s for s, name in enumerate(net.seg_names) if name in wanted]
    if not segs:
        raise ValueError("No road segment matches those street names.")
    nodes = np.unique(np.concatenate([net.seg_a[segs], net.seg_b[segs]]))
    return Anchor(node_idx=nodes, seg_idx=np.asarray(segs, dtype=np.int64))


# -------------------------------------------------------------------- snapping
def snap_points(net: RoadNetwork, points: Sequence[Tuple[float, float]]) -> Dict[str, np.ndarray]:
    """Project ``(lat, lon)`` points onto their nearest segment (chord geometry).

    Returns ``seg`` (index), ``t`` (0 at node a .. 1 at node b) and ``offset_m``
    (distance from the point to the road).
    """
    pts = np.asarray([(float(lat), float(lon)) for lat, lon in points], dtype=float).reshape(-1, 2)
    p = net.to_xy(pts[:, 1], pts[:, 0])                       # (P, 2)
    a = net.node_xy[net.seg_a]                                # (S, 2)
    ab = net.node_xy[net.seg_b] - a
    denom = np.maximum((ab ** 2).sum(axis=1), 1e-12)
    segs = np.empty(len(p), dtype=np.int64)
    ts = np.empty(len(p))
    offs = np.empty(len(p))
    for i, q in enumerate(p):
        t = np.clip(((q - a) * ab).sum(axis=1) / denom, 0.0, 1.0)
        foot = a + t[:, None] * ab
        dist = np.hypot(*(foot - q).T)
        k = int(np.argmin(dist))
        segs[i], ts[i], offs[i] = k, float(t[k]), float(dist[k])
    return {"seg": segs, "t": ts, "offset_m": offs}


def _euclid_to_anchor(net: RoadNetwork, anchor: Anchor, xy: np.ndarray) -> np.ndarray:
    """Straight-line metres to the anchor: its chords for a street, its nodes for points."""
    best = np.full(len(xy), np.inf)
    if not anchor.is_line:
        for n in anchor.node_idx:
            best = np.minimum(best, np.hypot(*(net.node_xy[n] - xy).T))
        return best
    for s in anchor.seg_idx:
        a, b = net.node_xy[net.seg_a[s]], net.node_xy[net.seg_b[s]]
        ab = b - a
        t = np.clip(((xy - a) @ ab) / max(float(ab @ ab), 1e-12), 0.0, 1.0)
        dist = np.hypot(*(a + t[:, None] * ab - xy).T)
        best = np.minimum(best, dist)
    return best


# ------------------------------------------------------------------- distances
def distances_to_anchor(
    net: RoadNetwork,
    anchor: Anchor,
    points: Sequence[Tuple[float, float]],
    kinds: Sequence[str] = DISTANCE_KINDS,
    topological_turn_deg: float = 0.0,
    include_offset: bool = True,
) -> Dict[str, Any]:
    """Distance of each ``(lat, lon)`` point to the anchor, per kind (NaN if unreachable).

    ``topological_turn_deg``: a segment-to-segment step costs 1 only when its deflection
    exceeds this angle (0 = every step counts; ~20-30 treats a near-straight street as
    one line, closer to axial depth).
    ``include_offset``: add the distance from the point to its nearest road to the
    ``metric`` distance (the point is rarely exactly on a road).
    Units are in ``DISTANCE_UNITS``.
    """
    unknown = [k for k in kinds if k not in DISTANCE_KINDS]
    if unknown:
        raise ValueError(f"Unknown distance kinds: {unknown}")
    pts = list(points)
    snap = snap_points(net, pts)
    seg, t, off = snap["seg"], snap["t"], snap["offset_m"]
    out: Dict[str, np.ndarray] = {}

    if "euclid" in kinds:
        arr = np.asarray([(float(lat), float(lon)) for lat, lon in pts], dtype=float).reshape(-1, 2)
        xy = net.to_xy(arr[:, 1], arr[:, 0])
        out["euclid"] = _euclid_to_anchor(net, anchor, xy) / 1000.0

    if "metric" in kinds:
        d_node = _dijkstra(_node_matrix(net), directed=False, indices=anchor.node_idx, min_only=True)
        length = net.seg_len[seg]
        along = np.minimum(d_node[net.seg_a[seg]] + t * length,
                           d_node[net.seg_b[seg]] + (1.0 - t) * length)
        on_anchor = np.isin(seg, anchor.seg_idx)
        along = np.where(on_anchor, 0.0, along)
        total = along + (off if include_offset else 0.0)
        out["metric"] = np.where(np.isfinite(total), total, np.nan) / 1000.0

    for kind in ("topological", "angular"):
        if kind not in kinds:
            continue
        sources = np.concatenate([2 * anchor.seg_idx, 2 * anchor.seg_idx + 1])
        states = _dijkstra(_segment_matrix(net, kind, topological_turn_deg), directed=True,
                           indices=sources, min_only=True)
        value = np.round(np.minimum(states[0::2], states[1::2])[seg], 6)
        out[kind] = np.where(np.isfinite(value), value, np.nan)

    return {"distances": out, "units": {k: DISTANCE_UNITS[k] for k in out},
            "snap_offset_m": off, "snap_segment": seg}


# --------------------------------------------------------------------- fitting
def fit_log_linear(d: Sequence[float], rent: Sequence[float]) -> Optional[Dict[str, Any]]:
    """OLS of ``ln(rent)`` on ``d``  ->  R(d) = r0 * exp(-lam * d).

    Returns ``None`` when ``d`` has no variation or fewer than 2 points. Statistics that
    need residual degrees of freedom (adj. R^2, AIC/AICc, LOO, CI) are ``None`` when the
    sample is too small for them.
    """
    x = np.asarray(d, dtype=float)
    y = np.log(np.asarray(rent, dtype=float))
    n = len(x)
    if n < 2 or not np.isfinite(x).all() or not np.isfinite(y).all():
        return None
    mean_x, mean_y = x.mean(), y.mean()
    sxx = float(((x - mean_x) ** 2).sum())
    if sxx <= 1e-12:
        return None
    slope = float(((x - mean_x) * (y - mean_y)).sum() / sxx)
    intercept = float(mean_y - slope * mean_x)
    resid = y - (intercept + slope * x)
    ss_res = float((resid ** 2).sum())
    ss_tot = float(((y - mean_y) ** 2).sum())
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 1e-12 else 1.0
    dof = n - 2

    result: Dict[str, Any] = {
        "r0": float(np.exp(intercept)), "lam": -slope, "r2": r2, "n": n, "dof": dof,
        "rmse_log": sqrt(ss_res / n), "adj_r2": None, "aic": None, "aicc": None,
        "loo_rmse": None, "lam_se": None, "lam_ci95": None,
    }
    if dof > 0:
        if ss_tot > 1e-12:
            result["adj_r2"] = 1.0 - (1.0 - r2) * (n - 1) / dof
        lam_se = sqrt(ss_res / dof / sxx)
        margin = float(_student_t.ppf(0.975, dof)) * lam_se
        result["lam_se"] = lam_se
        result["lam_ci95"] = (-slope - margin, -slope + margin)
    k = 3  # intercept, slope, error variance
    rss = max(ss_res, 1e-12)
    aic = n * log(rss / n) + 2 * k
    result["aic"] = aic
    if n - k - 1 > 0:
        result["aicc"] = aic + 2 * k * (k + 1) / (n - k - 1)
    if n >= 3:
        h = 1.0 / n + (x - mean_x) ** 2 / sxx                 # leverage of the simple OLS
        press = resid / np.maximum(1.0 - h, 1e-9)
        result["loo_rmse"] = float(np.sqrt((press ** 2).mean()))
    return result


def _clean_samples(samples: Iterable[Dict[str, Any]]) -> List[Tuple[float, float, float]]:
    rows: List[Tuple[float, float, float]] = []
    for s in samples:
        try:
            lat, lon, rent = float(s["lat"]), float(s["lon"]), float(s["rent"])
        except (KeyError, TypeError, ValueError):
            continue
        if np.isfinite([lat, lon, rent]).all() and rent > 0:
            rows.append((lat, lon, rent))
    return rows


def compare_distance_models(
    samples: Iterable[Dict[str, Any]],
    net: RoadNetwork,
    anchor: Anchor,
    kinds: Sequence[str] = DISTANCE_KINDS,
    topological_turn_deg: float = 0.0,
    include_offset: bool = True,
) -> Dict[str, Any]:
    """Fit bid-rent once per distance kind on the same samples and rank the kinds.

    ``samples``: dicts with ``lat``, ``lon``, ``rent`` (same schema as ``rent_samples`` in
    Rent_Gradient.py). Samples unreachable under any kind are dropped from all kinds so
    the fits stay comparable. Ranking: lowest leave-one-out RMSE (log rent) when every
    fit has one, otherwise highest R^2.
    """
    rows = _clean_samples(samples)
    warnings: List[str] = []
    n_input = len(rows)
    if n_input == 0:
        return {"n_input": 0, "n_used": 0, "models": {}, "ranking": [], "criterion": None,
                "points": [], "units": {}, "warnings": ["ไม่มีตัวอย่างราคาที่ใช้ได้ (ต้องมี lat, lon, rent > 0)"]}

    info = distances_to_anchor(net, anchor, [(r[0], r[1]) for r in rows], kinds,
                               topological_turn_deg, include_offset)
    dist = info["distances"]
    keep = np.ones(n_input, dtype=bool)
    for arr in dist.values():
        keep &= np.isfinite(arr)
    n_used = int(keep.sum())
    if n_used < n_input:
        warnings.append(f"ตัดตัวอย่างออก {n_input - n_used} จุด เพราะเชื่อมกับจุดยึดผ่านถนนไม่ได้")

    rent = np.array([r[2] for r in rows])[keep]
    models: Dict[str, Optional[Dict[str, Any]]] = {}
    for kind in dist:
        fit = fit_log_linear(dist[kind][keep], rent) if n_used >= 2 else None
        if fit is not None:
            fit["unit"] = DISTANCE_UNITS[kind]
        else:
            warnings.append(f"{kind}: fit ไม่ได้ (ระยะไม่มีความแปรผันระหว่างตัวอย่าง)")
        models[kind] = fit

    fitted = {k: m for k, m in models.items() if m is not None}
    criterion: Optional[str] = None
    ranking: List[str] = []
    if fitted:
        if all(m["loo_rmse"] is not None for m in fitted.values()):
            criterion = "loo_rmse"
            ranking = sorted(fitted, key=lambda k: (fitted[k]["loo_rmse"], -fitted[k]["r2"]))
        else:
            criterion = "r2"
            ranking = sorted(fitted, key=lambda k: -fitted[k]["r2"])
    if n_used < 3:
        warnings.append("ตัวอย่างน้อยกว่า 3 จุด: การเทียบโมเดลไม่มีความหมายทางสถิติ")
    elif n_used < MIN_RELIABLE_SAMPLES:
        warnings.append(f"ตัวอย่าง {n_used} จุด (< {MIN_RELIABLE_SAMPLES}): ผลจัดอันดับเป็นแนวโน้มเท่านั้น")

    points = []
    lat_lon_rent = [r for r, k in zip(rows, keep) if k]
    for i, (lat, lon, r) in enumerate(lat_lon_rent):
        rec: Dict[str, Any] = {"lat": lat, "lon": lon, "rent": r}
        for kind in dist:
            rec[kind] = float(dist[kind][keep][i])
        points.append(rec)

    return {"n_input": n_input, "n_used": n_used, "models": models, "ranking": ranking,
            "criterion": criterion, "points": points, "units": info["units"], "warnings": warnings}


def binned_profile(
    d: Sequence[float], rent: Sequence[float], bin_size: float
) -> List[Dict[str, float]]:
    """Mean rent per distance bin (e.g. ``bin_size=0.5`` km), like Laora's 500 m steps."""
    if bin_size <= 0:
        raise ValueError("bin_size must be positive.")
    x = np.asarray(d, dtype=float)
    y = np.asarray(rent, dtype=float)
    ok = np.isfinite(x) & np.isfinite(y)
    x, y = x[ok], y[ok]
    if len(x) == 0:
        return []
    idx = np.floor(x / bin_size + 1e-9).astype(int)
    out = []
    for b in np.unique(idx):
        sel = idx == b
        out.append({"from": float(b * bin_size), "to": float((b + 1) * bin_size),
                    "n": int(sel.sum()), "mean_rent": float(y[sel].mean())})
    return out
