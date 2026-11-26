"""High-performance compiled & vectorized kernels for ``pages/Rent_Gradient.py``.

Design goals
------------
1. **100% identical principles and numerical outputs** — every kernel reproduces
   the exact mathematical definitions, tie-breaking rules, normalization constants
   and edge cases of the pure-Python/NetworkX/SciPy reference implementations
   (including NumPy's exact pairwise float64 summation for bit-identical totals).
2. **Thread-safe stability in Streamlit** — uses ``@njit(cache=True, nogil=True)``
   (never OpenMP/TBB ``parallel=True``, which can crash Streamlit script-runner
   threads) dispatched across a small bounded ``ThreadPoolExecutor`` with
   disjoint per-worker scratch buffers and deterministic ordered reductions.
3. **Exact topological 1-core (tree) peeling** — peels degree-1 dead-end trees
   in O(N) before running exact Closeness or exact Brandes Edge Betweenness on
   the smaller 2-core, yielding an exact ~2–3× extra algorithmic speedup on top
   of compiled machine code.
4. **Process-wide caching** — because this is a regular importable module
   (cached in ``sys.modules``), Streamlit reruns never re-execute or re-JIT any
   kernel, never recreate ``pyproj.Transformer`` contexts, and reuse HTTP
   keep-alive connection pools.
5. **Graceful fallback** — if ``numba`` is unavailable or fails to compile,
   ``HAS_NUMBA`` is ``False`` and callers transparently fall back to the
   existing SciPy/NetworkX paths.
"""

from __future__ import annotations

import atexit
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np
import requests
from pyproj import Transformer
from requests.adapters import HTTPAdapter

# ----------------------------------------------------------------------------
# Process-wide singletons (created once per server process, not per rerun)
# ----------------------------------------------------------------------------
WEB_MERCATOR: Transformer = Transformer.from_crs("EPSG:4326", "EPSG:3857", always_xy=True)
WEB_MERCATOR_INV: Transformer = Transformer.from_crs("EPSG:3857", "EPSG:4326", always_xy=True)

_ORIG_REQUESTS_GET = requests.get
_SESSION_LOCAL = threading.local()

_HEX_BYTE: Tuple[str, ...] = tuple(f"{i:02x}" for i in range(256))
_LEGEND_LUT_CACHE: Dict[Tuple[Any, ...], np.ndarray] = {}
_LEGEND_LUT_LOCK = threading.Lock()
_PLASMA_HEX_LUT: Optional[Tuple[str, ...]] = None

_N_WORKERS: int = max(1, min(os.cpu_count() or 1, 8))
_POOL_LOCK = threading.Lock()
_EXECUTOR: Optional[ThreadPoolExecutor] = None
_JIT_LOCK = threading.Lock()
_WARMED_KERNELS: set[str] = set()


def _get_executor() -> ThreadPoolExecutor:
    global _EXECUTOR
    if _EXECUTOR is None:
        with _POOL_LOCK:
            if _EXECUTOR is None:
                _EXECUTOR = ThreadPoolExecutor(max_workers=_N_WORKERS, thread_name_prefix="rg_fast")
                atexit.register(_shutdown_executor)
    return _EXECUTOR


def _shutdown_executor() -> None:
    global _EXECUTOR
    ex = _EXECUTOR
    _EXECUTOR = None
    if ex is not None:
        ex.shutdown(wait=False, cancel_futures=True)


def get_http_session() -> requests.Session:
    """Thread-local HTTP keep-alive session (avoids repeated TLS handshakes)."""
    sess = getattr(_SESSION_LOCAL, "session", None)
    if sess is None:
        sess = requests.Session()
        adapter = HTTPAdapter(pool_connections=16, pool_maxsize=16)
        sess.mount("https://", adapter)
        sess.mount("http://", adapter)
        _SESSION_LOCAL.session = sess
    return sess


def http_get(requests_module: Any, url: str, **kwargs: Any) -> Any:
    """Use the keep-alive session unless ``requests.get`` was monkeypatched."""
    if getattr(requests_module, "get", None) is _ORIG_REQUESTS_GET:
        return get_http_session().get(url, **kwargs)
    return requests_module.get(url, **kwargs)


def plasma_hex_lut() -> Tuple[str, ...]:
    """256-entry precomputed hex lookup table matching ``matplotlib.colormaps['plasma'](x)``."""
    global _PLASMA_HEX_LUT
    if _PLASMA_HEX_LUT is None:
        import matplotlib
        import matplotlib.colors as mcolors

        cmap = matplotlib.colormaps["plasma"]
        if hasattr(cmap, "colors") and len(cmap.colors) == 256:
            _PLASMA_HEX_LUT = tuple(mcolors.to_hex(c) for c in cmap.colors)
        else:
            _PLASMA_HEX_LUT = tuple(mcolors.to_hex(cmap(i / 255.0)) for i in range(256))
    return _PLASMA_HEX_LUT


def rgb_float_to_hex_list(rgb: np.ndarray) -> List[str]:
    """Fast vectorized conversion of ``(N, 3)`` float RGB in [0, 1] → ``['#rrggbb', ...]``."""
    n = len(rgb)
    if n == 0:
        return []
    u8 = np.rint(rgb * 255.0).astype(np.int32)
    np.clip(u8, 0, 255, out=u8)
    r = u8[:, 0].tolist()
    g = u8[:, 1].tolist()
    b = u8[:, 2].tolist()
    hb = _HEX_BYTE
    return [f"#{hb[rv]}{hb[gv]}{hb[bv]}" for rv, gv, bv in zip(r, g, b)]


def haversine_km_batch(lat0: float, lon0: float, lats: np.ndarray, lons: np.ndarray) -> np.ndarray:
    """Vectorized Haversine distance in km from ``(lat0, lon0)`` to ``(lats, lons)``."""
    lat1 = np.radians(lat0)
    lon1 = np.radians(lon0)
    lat2 = np.radians(lats)
    lon2 = np.radians(lons)
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = np.sin(dlat * 0.5) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon * 0.5) ** 2
    return 6371.0 * (2.0 * np.arctan2(np.sqrt(a), np.sqrt(np.maximum(1.0 - a, 0.0))))


def cached_legend_lut(legend: List[Dict[str, Any]], tolerance: float) -> np.ndarray:
    """Memoised 5-bit-per-channel RGB → legend-class lookup table."""
    key = (tuple(tuple(int(v) for v in entry["rgb"][:3]) for entry in legend), float(tolerance))
    cached = _LEGEND_LUT_CACHE.get(key)
    if cached is not None:
        return cached
    idx = np.arange(32768)
    rgb = np.stack(
        [((idx >> 10) & 31) * 8 + 4, ((idx >> 5) & 31) * 8 + 4, (idx & 31) * 8 + 4],
        axis=1,
    ).astype(np.float32)
    best = np.full(idx.shape, np.inf, dtype=np.float32)
    lut = np.full(idx.shape, -1, dtype=np.int8)
    for k, entry in enumerate(legend):
        dist = np.sqrt(((rgb - np.asarray(entry["rgb"], dtype=np.float32)) ** 2).sum(axis=1))
        closer = (dist < best) & (dist <= tolerance)
        best[closer] = dist[closer]
        lut[closer] = k
    with _LEGEND_LUT_LOCK:
        if len(_LEGEND_LUT_CACHE) >= 32:
            _LEGEND_LUT_CACHE.clear()
        _LEGEND_LUT_CACHE[key] = lut
    return lut


# ----------------------------------------------------------------------------
# Numba compiled kernels (cache=True, nogil=True — NO OpenMP/parallel=True)
# ----------------------------------------------------------------------------
try:
    from numba import njit

    HAS_NUMBA: bool = True
except Exception:  # pragma: no cover
    HAS_NUMBA = False

    def njit(*_args: Any, **_kwargs: Any):  # type: ignore[misc]
        def _wrap(fn: Callable[..., Any]) -> Callable[..., Any]:
            return fn

        return _wrap


if HAS_NUMBA:

    # ------------------------------------------------------------------
    # Exact NumPy DOUBLE_pairwise_sum replica (8-way unrolled + pairwise split).
    # Implemented 100% iteratively (zero recursion) so Numba cache=True reloads
    # cleanly across process restarts without recursive-relocation bugs.
    # Guarantees bit-for-bit np.array_equal agreement with depth[reached].sum().
    # ------------------------------------------------------------------
    @njit(cache=True, nogil=True)
    def _np_pairwise_sum(a: np.ndarray, start: int, n: int) -> float:
        if n <= 0:
            return 0.0
        if n < 8:
            res = 0.0
            for i in range(start, start + n):
                res += a[i]
            return res
        if n <= 128:
            r0 = a[start]
            r1 = a[start + 1]
            r2 = a[start + 2]
            r3 = a[start + 3]
            r4 = a[start + 4]
            r5 = a[start + 5]
            r6 = a[start + 6]
            r7 = a[start + 7]
            i = start + 8
            end8 = start + n - 8
            while i <= end8:
                r0 += a[i]
                r1 += a[i + 1]
                r2 += a[i + 2]
                r3 += a[i + 3]
                r4 += a[i + 4]
                r5 += a[i + 5]
                r6 += a[i + 6]
                r7 += a[i + 7]
                i += 8
            res = ((r0 + r1) + (r2 + r3)) + ((r4 + r5) + (r6 + r7))
            end = start + n
            while i < end:
                res += a[i]
                i += 1
            return res

        # Iterative post-order evaluation of exact binary split tree (depth <= 60)
        st_start = np.empty(64, dtype=np.int64)
        st_n = np.empty(64, dtype=np.int64)
        st_state = np.empty(64, dtype=np.int8)
        val_stack = np.empty(64, dtype=np.float64)

        st_start[0] = start
        st_n[0] = n
        st_state[0] = 0
        sp = 1
        vsp = 0

        while sp > 0:
            sp -= 1
            if st_state[sp] == 1:
                right = val_stack[vsp - 1]
                left = val_stack[vsp - 2]
                val_stack[vsp - 2] = left + right
                vsp -= 1
                continue

            cur_s = int(st_start[sp])
            cur_n = int(st_n[sp])
            if cur_n <= 128:
                if cur_n < 8:
                    res = 0.0
                    for i in range(cur_s, cur_s + cur_n):
                        res += a[i]
                else:
                    r0 = a[cur_s]
                    r1 = a[cur_s + 1]
                    r2 = a[cur_s + 2]
                    r3 = a[cur_s + 3]
                    r4 = a[cur_s + 4]
                    r5 = a[cur_s + 5]
                    r6 = a[cur_s + 6]
                    r7 = a[cur_s + 7]
                    i = cur_s + 8
                    end8 = cur_s + cur_n - 8
                    while i <= end8:
                        r0 += a[i]
                        r1 += a[i + 1]
                        r2 += a[i + 2]
                        r3 += a[i + 3]
                        r4 += a[i + 4]
                        r5 += a[i + 5]
                        r6 += a[i + 6]
                        r7 += a[i + 7]
                        i += 8
                    res = ((r0 + r1) + (r2 + r3)) + ((r4 + r5) + (r6 + r7))
                    end = cur_s + cur_n
                    while i < end:
                        res += a[i]
                        i += 1
                val_stack[vsp] = res
                vsp += 1
            else:
                n2 = cur_n >> 1
                n2 -= n2 & 7
                # Push combine marker, then right child, then left child (LIFO -> left first)
                st_state[sp] = 1
                sp += 1
                st_start[sp] = cur_s + n2
                st_n[sp] = cur_n - n2
                st_state[sp] = 0
                sp += 1
                st_start[sp] = cur_s
                st_n[sp] = n2
                st_state[sp] = 0
                sp += 1

        return val_stack[0]

    # ------------------------------------------------------------------
    # Lazy 4-ary min-heap helpers (inlined by LLVM)
    # No heap_pos random-write array: ~2x faster on sparse planar road graphs.
    # Safe capacity: caller allocates len(indices) + n + 16 (provably >= max pushes
    # for positive-weight Dijkstra since each vertex is popped at most once).
    # ------------------------------------------------------------------
    @njit(cache=True, nogil=True)
    def _lheap_push(hv: np.ndarray, hd: np.ndarray, hsize: int, v: int, d: float) -> int:
        p = hsize
        hsize += 1
        while p > 0:
            par = (p - 1) >> 2
            pd = hd[par]
            if d < pd:
                hd[p] = pd
                hv[p] = hv[par]
                p = par
            else:
                break
        hd[p] = d
        hv[p] = v
        return hsize

    @njit(cache=True, nogil=True)
    def _lheap_pop(hv: np.ndarray, hd: np.ndarray, hsize: int) -> Tuple[int, float, int]:
        top_v = hv[0]
        top_d = hd[0]
        hsize -= 1
        if hsize > 0:
            lv = hv[hsize]
            ld = hd[hsize]
            p = 0
            while True:
                c0 = (p << 2) + 1
                if c0 >= hsize:
                    break
                best = c0
                bd = hd[c0]
                c_end = c0 + 4
                if c_end > hsize:
                    c_end = hsize
                for c in range(c0 + 1, c_end):
                    cd = hd[c]
                    if cd < bd:
                        best = c
                        bd = cd
                if bd < ld:
                    hd[p] = bd
                    hv[p] = hv[best]
                    p = best
                else:
                    break
            hd[p] = ld
            hv[p] = lv
        return top_v, top_d, hsize

    # ------------------------------------------------------------------
    # Exact 1-core (dead-end tree) peeling for undirected weighted CSR graphs
    # ------------------------------------------------------------------
    @njit(cache=True, nogil=True)
    def _peel_one_core(
        indptr: np.ndarray,
        indices: np.ndarray,
        weights: np.ndarray,
        edge_ids: np.ndarray,
        n_nodes: int,
    ) -> Tuple[
        np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray,
        np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray,
        int,
    ]:
        """Peel degree-1 trees onto their attachment 2-core nodes in O(N + M).

        Returns core CSR ``(c_indptr, c_indices, c_weights, c_eids, core_orig,
        core_weight, core_tree_dist)`` plus peel stack ``(peel_u, peel_p, peel_w,
        peel_eid, peel_sub, n_peel)`` for exact O(N) unpeeling.
        """
        deg = np.empty(n_nodes, dtype=np.int32)
        queue = np.empty(n_nodes, dtype=np.int32)
        q_tail = 0
        for u in range(n_nodes):
            d = int(indptr[u + 1] - indptr[u])
            deg[u] = d
            if d == 1:
                queue[q_tail] = u
                q_tail += 1

        removed = np.zeros(n_nodes, dtype=np.uint8)
        sub_size = np.ones(n_nodes, dtype=np.int64)
        tree_dist = np.zeros(n_nodes, dtype=np.float64)

        peel_u = np.empty(n_nodes, dtype=np.int32)
        peel_p = np.empty(n_nodes, dtype=np.int32)
        peel_w = np.empty(n_nodes, dtype=np.float64)
        peel_eid = np.empty(n_nodes, dtype=np.int32)
        peel_sub = np.empty(n_nodes, dtype=np.int64)
        n_peel = 0

        q_head = 0
        while q_head < q_tail:
            u = int(queue[q_head])
            q_head += 1
            if removed[u] or deg[u] != 1:
                continue
            # Find the unique unremoved neighbour p
            p = -1
            w_up = 0.0
            eid_up = -1
            for k in range(indptr[u], indptr[u + 1]):
                nb = int(indices[k])
                if not removed[nb]:
                    p = nb
                    w_up = weights[k]
                    eid_up = int(edge_ids[k])
                    break
            if p < 0:
                continue
            removed[u] = 1
            deg[u] = 0
            deg[p] -= 1
            su = sub_size[u]
            sub_size[p] += su
            tree_dist[p] += tree_dist[u] + float(su) * w_up

            peel_u[n_peel] = u
            peel_p[n_peel] = p
            peel_w[n_peel] = w_up
            peel_eid[n_peel] = eid_up
            peel_sub[n_peel] = su
            n_peel += 1

            if deg[p] == 1:
                queue[q_tail] = p
                q_tail += 1

        # Build compact 2-core CSR
        orig_to_core = np.full(n_nodes, -1, dtype=np.int32)
        n_core = 0
        for u in range(n_nodes):
            if not removed[u]:
                orig_to_core[u] = n_core
                n_core += 1

        core_orig = np.empty(n_core, dtype=np.int32)
        core_weight = np.empty(n_core, dtype=np.int64)
        core_tree_dist = np.empty(n_core, dtype=np.float64)
        c_indptr = np.empty(n_core + 1, dtype=np.int32)
        c_indptr[0] = 0

        m_core = 0
        for u in range(n_nodes):
            cu = int(orig_to_core[u])
            if cu >= 0:
                core_orig[cu] = u
                core_weight[cu] = sub_size[u]
                core_tree_dist[cu] = tree_dist[u]
                for k in range(indptr[u], indptr[u + 1]):
                    if orig_to_core[indices[k]] >= 0:
                        m_core += 1
                c_indptr[cu + 1] = m_core

        c_indices = np.empty(m_core, dtype=np.int32)
        c_weights = np.empty(m_core, dtype=np.float64)
        c_eids = np.empty(m_core, dtype=np.int32)
        pos = 0
        for cu in range(n_core):
            u = int(core_orig[cu])
            for k in range(indptr[u], indptr[u + 1]):
                cv = int(orig_to_core[indices[k]])
                if cv >= 0:
                    c_indices[pos] = cv
                    c_weights[pos] = weights[k]
                    c_eids[pos] = edge_ids[k]
                    pos += 1

        return (
            c_indptr, c_indices, c_weights, c_eids,
            core_orig, core_weight, core_tree_dist,
            peel_u, peel_p, peel_w, peel_eid, peel_sub, n_peel,
        )

    # ------------------------------------------------------------------
    # KERNEL 1: Weighted Brandes Edge Betweenness (works on full graph OR
    # weighted 2-core where each node carries ``node_weight[v] >= 1``)
    # ------------------------------------------------------------------
    @njit(cache=True, nogil=True)
    def _brandes_edge_bc_chunk(
        indptr: np.ndarray,
        indices: np.ndarray,
        weights: np.ndarray,
        edge_ids: np.ndarray,
        node_weights: np.ndarray,
        sources: np.ndarray,
        n_nodes: int,
        n_edges: int,
        want_closeness: bool,
    ) -> Tuple[np.ndarray, np.ndarray]:
        m_dir = len(indices)
        bc = np.zeros(n_edges, dtype=np.float64)
        close_sums = np.zeros(len(sources), dtype=np.float64) if want_closeness else np.empty(0, dtype=np.float64)

        dist = np.empty(n_nodes, dtype=np.float64)
        settled = np.zeros(n_nodes, dtype=np.int32)
        sigma = np.empty(n_nodes, dtype=np.float64)
        delta = np.empty(n_nodes, dtype=np.float64)
        stack = np.empty(n_nodes, dtype=np.int32)

        # Linked-list predecessor arena (provably <= m_dir entries per source)
        pred_head = np.empty(n_nodes, dtype=np.int32)
        arena_cap = m_dir + 4
        pred_node = np.empty(arena_cap, dtype=np.int32)
        pred_edge = np.empty(arena_cap, dtype=np.int32)
        pred_next = np.empty(arena_cap, dtype=np.int32)

        hcap = m_dir + n_nodes + 16
        hv = np.empty(hcap, dtype=np.int32)
        hd = np.empty(hcap, dtype=np.float64)

        stamp = np.int32(0)
        inf = np.inf
        for si in range(len(sources)):
            s = int(sources[si])
            ws = float(node_weights[s])
            stamp += np.int32(1)
            dist.fill(inf)
            arena_len = 0
            stack_len = 0

            dist[s] = 0.0
            sigma[s] = 1.0
            pred_head[s] = -1
            hv[0] = s
            hd[0] = 0.0
            hsize = 1

            d_sum = 0.0
            while hsize > 0:
                v, d, hsize = _lheap_pop(hv, hd, hsize)
                if settled[v] == stamp:
                    continue
                settled[v] = stamp
                stack[stack_len] = v
                stack_len += 1
                delta[v] = 0.0
                if want_closeness:
                    d_sum += float(node_weights[v]) * d
                sv = sigma[v]
                start = indptr[v]
                end = indptr[v + 1]
                for k in range(start, end):
                    w = int(indices[k])
                    if settled[w] == stamp:
                        continue
                    vw_dist = d + weights[k]
                    dw = dist[w]
                    if vw_dist < dw:
                        dist[w] = vw_dist
                        sigma[w] = sv
                        pred_node[arena_len] = v
                        pred_edge[arena_len] = edge_ids[k]
                        pred_next[arena_len] = -1
                        pred_head[w] = arena_len
                        arena_len += 1
                        hsize = _lheap_push(hv, hd, hsize, w, vw_dist)
                    elif vw_dist == dw:
                        sigma[w] += sv
                        pred_node[arena_len] = v
                        pred_edge[arena_len] = edge_ids[k]
                        pred_next[arena_len] = pred_head[w]
                        pred_head[w] = arena_len
                        arena_len += 1

            if want_closeness:
                close_sums[si] = d_sum

            # Brandes edge accumulation in reverse settling order
            for k in range(stack_len - 1, -1, -1):
                w = int(stack[k])
                coeff = (float(node_weights[w]) + delta[w]) / sigma[w]
                p_idx = pred_head[w]
                while p_idx >= 0:
                    v = int(pred_node[p_idx])
                    e = int(pred_edge[p_idx])
                    c = sigma[v] * coeff
                    bc[e] += ws * c
                    delta[v] += c
                    p_idx = int(pred_next[p_idx])

        return bc, close_sums

    # ------------------------------------------------------------------
    # KERNEL 2: Weighted Closeness Centrality (exact 2-core & pivot)
    # ------------------------------------------------------------------
    @njit(cache=True, nogil=True)
    def _dijkstra_closeness_core_chunk(
        indptr: np.ndarray,
        indices: np.ndarray,
        weights: np.ndarray,
        core_weight: np.ndarray,
        sources: np.ndarray,
        n_core: int,
    ) -> np.ndarray:
        out = np.empty(len(sources), dtype=np.float64)
        dist = np.empty(n_core, dtype=np.float64)
        hcap = len(indices) + n_core + 16
        hv = np.empty(hcap, dtype=np.int32)
        hd = np.empty(hcap, dtype=np.float64)
        inf = np.inf

        for si in range(len(sources)):
            s = int(sources[si])
            dist.fill(inf)
            dist[s] = 0.0
            hv[0] = s
            hd[0] = 0.0
            hsize = 1
            total = 0.0
            reached = 0
            while hsize > 0:
                v, d, hsize = _lheap_pop(hv, hd, hsize)
                if d > dist[v]:
                    continue
                total += float(core_weight[v]) * d
                reached += 1
                start = indptr[v]
                end = indptr[v + 1]
                for k in range(start, end):
                    w = int(indices[k])
                    nd = d + weights[k]
                    if nd < dist[w]:
                        dist[w] = nd
                        hsize = _lheap_push(hv, hd, hsize, w, nd)
            out[si] = total if reached == n_core else inf
        return out

    @njit(cache=True, nogil=True)
    def _dijkstra_closeness_pivot_chunk(
        indptr: np.ndarray,
        indices: np.ndarray,
        weights: np.ndarray,
        pivots: np.ndarray,
        n_nodes: int,
    ) -> np.ndarray:
        col_sums = np.zeros(n_nodes, dtype=np.float64)
        dist = np.empty(n_nodes, dtype=np.float64)
        hcap = len(indices) + n_nodes + 16
        hv = np.empty(hcap, dtype=np.int32)
        hd = np.empty(hcap, dtype=np.float64)
        inf = np.inf

        for si in range(len(pivots)):
            s = int(pivots[si])
            dist.fill(inf)
            dist[s] = 0.0
            hv[0] = s
            hd[0] = 0.0
            hsize = 1
            reached = 0
            while hsize > 0:
                v, d, hsize = _lheap_pop(hv, hd, hsize)
                if d > dist[v]:
                    continue
                col_sums[v] += d
                reached += 1
                start = indptr[v]
                end = indptr[v + 1]
                for k in range(start, end):
                    w = int(indices[k])
                    nd = d + weights[k]
                    if nd < dist[w]:
                        dist[w] = nd
                        hsize = _lheap_push(hv, hd, hsize, w, nd)
            if reached < n_nodes:
                for v in range(n_nodes):
                    if dist[v] == inf:
                        col_sums[v] = inf
        return col_sums

    # ------------------------------------------------------------------
    # KERNEL 3: Automated CBD Anchor Dijkstra Pass (pivots + exact + stability)
    # ------------------------------------------------------------------
    @njit(cache=True, nogil=True)
    def _anchor_dijkstra_chunk(
        indptr: np.ndarray,
        indices: np.ndarray,
        weights: np.ndarray,
        sources: np.ndarray,
        source_is_base: np.ndarray,
        eligible_mask: np.ndarray,
        case_inside: np.ndarray,
        n_nodes: int,
        want_pivot_accum: bool,
    ) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        n_src = len(sources)
        n_cases = case_inside.shape[1]
        elig_sums = np.empty(n_src, dtype=np.float64)
        case_rows = np.zeros((n_src, n_cases), dtype=np.float64)
        pivot_sum = np.zeros(n_nodes, dtype=np.float64) if want_pivot_accum else np.empty(0, dtype=np.float64)
        case_pivot_sum = (
            np.zeros((n_nodes, n_cases), dtype=np.float64)
            if (want_pivot_accum and n_cases > 0)
            else np.empty((0, 0), dtype=np.float64)
        )
        case_outer_sum = (
            np.zeros((n_nodes, n_cases), dtype=np.float64)
            if (want_pivot_accum and n_cases > 0)
            else np.empty((0, 0), dtype=np.float64)
        )

        dist = np.empty(n_nodes, dtype=np.float64)
        hcap = len(indices) + n_nodes + 16
        hv = np.empty(hcap, dtype=np.int32)
        hd = np.empty(hcap, dtype=np.float64)
        inf = np.inf

        for si in range(n_src):
            s = int(sources[si])
            is_base = bool(source_is_base[si])
            dist.fill(inf)
            dist[s] = 0.0
            hv[0] = s
            hd[0] = 0.0
            hsize = 1

            esum = 0.0
            while hsize > 0:
                v, d, hsize = _lheap_pop(hv, hd, hsize)
                if d > dist[v]:
                    continue
                if eligible_mask[v]:
                    esum += d
                if n_cases > 0:
                    for c in range(n_cases):
                        if case_inside[v, c]:
                            case_rows[si, c] += d
                if want_pivot_accum:
                    if is_base:
                        pivot_sum[v] += d
                        if n_cases > 0:
                            for c in range(n_cases):
                                if case_inside[s, c]:
                                    case_pivot_sum[v, c] += d
                    elif n_cases > 0:
                        for c in range(n_cases):
                            if case_inside[s, c]:
                                case_outer_sum[v, c] += d
                start = indptr[v]
                end = indptr[v + 1]
                for k in range(start, end):
                    w = int(indices[k])
                    nd = d + weights[k]
                    if nd < dist[w]:
                        dist[w] = nd
                        hsize = _lheap_push(hv, hd, hsize, w, nd)
            elig_sums[si] = esum
        return elig_sums, case_rows, pivot_sum, case_pivot_sum, case_outer_sum

    # ------------------------------------------------------------------
    # KERNEL 4: Space Syntax Local Pass — O(|B(r)|) lazy 4-ary heap +
    # O(|B(r)|) reverse-pop Choice + bit-exact NumPy pairwise sum!
    # ------------------------------------------------------------------
    @njit(cache=True, nogil=True)
    def _ss_local_chunk(
        m_indptr: np.ndarray,
        m_indices: np.ndarray,
        m_data: np.ndarray,
        d_indptr: np.ndarray,
        d_indices: np.ndarray,
        d_data: np.ndarray,
        n_seg: int,
        radii: np.ndarray,
        origins: np.ndarray,
        with_choice: bool,
    ) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        n_r = len(radii)
        n_orig = len(origins)
        n_states = 2 * n_seg
        r_max = radii[n_r - 1]

        nc_out = np.zeros((n_r, n_orig), dtype=np.float64)
        td_out = np.zeros((n_r, n_orig), dtype=np.float64)
        ch_out = np.zeros((n_r, n_seg), dtype=np.int64) if with_choice else np.empty((0, 0), dtype=np.int64)

        m_dist = np.empty(n_states, dtype=np.float64)
        m_seen = np.zeros(n_states, dtype=np.int32)
        m_hcap = len(m_indices) + n_states + 16
        m_hv = np.empty(m_hcap, dtype=np.int32)
        m_hd = np.empty(m_hcap, dtype=np.float64)

        seg_seen = np.zeros(n_seg, dtype=np.int32)
        seg_mdist = np.empty(n_seg, dtype=np.float64)
        ball_segs = np.empty(n_seg, dtype=np.int32)
        inside_segs = np.empty(n_seg, dtype=np.int32)
        allowed = np.zeros(n_seg, dtype=np.int32)

        d_dist = np.empty(n_states, dtype=np.float64)
        d_seen = np.zeros(n_states, dtype=np.int32)
        d_pred = np.empty(n_states, dtype=np.int32)
        d_hcap = len(d_indices) + n_states + 16
        d_hv = np.empty(d_hcap, dtype=np.int32)
        d_hd = np.empty(d_hcap, dtype=np.float64)
        d_order = np.empty(n_states, dtype=np.int32)
        sub_w = np.zeros(n_states, dtype=np.int64)
        reached_depths = np.empty(n_seg, dtype=np.float64)

        m_stamp = np.int32(0)
        allow_stamp = np.int32(0)
        d_stamp = np.int32(0)

        for oi in range(n_orig):
            origin = int(origins[oi])
            r0 = origin << 1
            r1 = r0 + 1

            # 1) Metric neighbourhood up to r_max
            m_stamp += np.int32(1)
            m_seen[r0] = m_stamp
            m_seen[r1] = m_stamp
            m_dist[r0] = 0.0
            m_dist[r1] = 0.0
            m_hv[0] = r0
            m_hd[0] = 0.0
            m_hv[1] = r1
            m_hd[1] = 0.0
            hsize = 2

            n_ball = 0
            while hsize > 0:
                u, d, hsize = _lheap_pop(m_hv, m_hd, hsize)
                if d > m_dist[u]:
                    continue
                s = u >> 1
                if seg_seen[s] != m_stamp:
                    seg_seen[s] = m_stamp
                    seg_mdist[s] = d
                    ball_segs[n_ball] = s
                    n_ball += 1
                start = m_indptr[u]
                end = m_indptr[u + 1]
                for k in range(start, end):
                    v = int(m_indices[k])
                    nd = d + m_data[k]
                    if nd <= r_max and (m_seen[v] != m_stamp or nd < m_dist[v]):
                        m_seen[v] = m_stamp
                        m_dist[v] = nd
                        if m_indptr[v] < m_indptr[v + 1]:
                            hsize = _lheap_push(m_hv, m_hd, hsize, v, nd)
                        else:
                            # Dead-end arrival state: record directly without heap overhead
                            vs = v >> 1
                            if seg_seen[vs] != m_stamp:
                                seg_seen[vs] = m_stamp
                                seg_mdist[vs] = nd
                                ball_segs[n_ball] = vs
                                n_ball += 1
                            elif nd < seg_mdist[vs]:
                                seg_mdist[vs] = nd

            # 2) For each requested radius r (ascending)
            for ri in range(n_r):
                r = radii[ri]
                n_in = 0
                allow_stamp += np.int32(1)
                for bi in range(n_ball):
                    s = int(ball_segs[bi])
                    if seg_mdist[s] <= r:
                        inside_segs[n_in] = s
                        allowed[s] = allow_stamp
                        n_in += 1
                nc_out[ri, oi] = float(n_in)
                if n_in < 2:
                    continue

                inside_segs[:n_in].sort()

                d_stamp += np.int32(1)
                d_seen[r0] = d_stamp
                d_seen[r1] = d_stamp
                d_dist[r0] = 0.0
                d_dist[r1] = 0.0
                d_pred[r0] = -1
                d_pred[r1] = -1
                d_hv[0] = r0
                d_hd[0] = 0.0
                d_hv[1] = r1
                d_hd[1] = 0.0
                dhsize = 2

                n_pop = 0
                while dhsize > 0:
                    u, d, dhsize = _lheap_pop(d_hv, d_hd, dhsize)
                    if d > d_dist[u]:
                        continue
                    d_order[n_pop] = u
                    n_pop += 1
                    start = d_indptr[u]
                    end = d_indptr[u + 1]
                    for k in range(start, end):
                        v = int(d_indices[k])
                        if allowed[v >> 1] != allow_stamp:
                            continue
                        nd = d + d_data[k]
                        if d_seen[v] != d_stamp or nd < d_dist[v]:
                            d_seen[v] = d_stamp
                            d_dist[v] = nd
                            d_pred[v] = u
                            if d_indptr[v] < d_indptr[v + 1]:
                                dhsize = _lheap_push(d_hv, d_hd, dhsize, v, nd)

                if with_choice:
                    for j in range(n_pop):
                        sub_w[d_order[j]] = 0

                n_reached = 0
                for ii in range(n_in):
                    s = int(inside_segs[ii])
                    s0 = s << 1
                    s1 = s0 + 1
                    has0 = d_seen[s0] == d_stamp
                    has1 = d_seen[s1] == d_stamp
                    if has0 and has1:
                        d0 = d_dist[s0]
                        d1 = d_dist[s1]
                        if d0 <= d1:
                            reached_depths[n_reached] = d0
                            rep_state = s0
                        else:
                            reached_depths[n_reached] = d1
                            rep_state = s1
                        n_reached += 1
                        if with_choice and s != origin:
                            if d_indptr[rep_state] < d_indptr[rep_state + 1]:
                                sub_w[rep_state] += 1
                            else:
                                # Dead-end state wasn't pushed to d_order: fold weight directly to its parent
                                p = int(d_pred[rep_state])
                                if p >= 0:
                                    sub_w[p] += 1
                                    ps = p >> 1
                                    if ps != origin:
                                        ch_out[ri, ps] += 1
                    elif has0:
                        reached_depths[n_reached] = d_dist[s0]
                        n_reached += 1
                        if with_choice and s != origin:
                            if d_indptr[s0] < d_indptr[s0 + 1]:
                                sub_w[s0] += 1
                            else:
                                p = int(d_pred[s0])
                                if p >= 0:
                                    sub_w[p] += 1
                                    ps = p >> 1
                                    if ps != origin:
                                        ch_out[ri, ps] += 1
                    elif has1:
                        reached_depths[n_reached] = d_dist[s1]
                        n_reached += 1
                        if with_choice and s != origin:
                            if d_indptr[s1] < d_indptr[s1 + 1]:
                                sub_w[s1] += 1
                            else:
                                p = int(d_pred[s1])
                                if p >= 0:
                                    sub_w[p] += 1
                                    ps = p >> 1
                                    if ps != origin:
                                        ch_out[ri, ps] += 1

                td_out[ri, oi] = _np_pairwise_sum(reached_depths, 0, n_reached)

                if with_choice:
                    for j in range(n_pop - 1, -1, -1):
                        v = int(d_order[j])
                        w = sub_w[v]
                        p = int(d_pred[v])
                        if p >= 0:
                            sub_w[p] += w
                            ps = p >> 1
                            if ps != origin:
                                ch_out[ri, ps] += w

        return nc_out, td_out, ch_out

    # ------------------------------------------------------------------
    # KERNEL 5: Space Syntax Global Pass — lazy 4-ary heap + skip deg0 states +
    # pre-sorted component members (ZERO per-origin sort!) + bit-exact pairwise sum
    # ------------------------------------------------------------------
    @njit(cache=True, nogil=True)
    def _ss_global_chunk(
        d_indptr: np.ndarray,
        d_indices: np.ndarray,
        d_data: np.ndarray,
        n_seg: int,
        members: np.ndarray,
        origins: np.ndarray,
        exact_mode: bool,
        scale: float,
        with_choice: bool,
    ) -> Tuple[np.ndarray, np.ndarray]:
        n_orig = len(origins)
        n_mem = len(members)
        n_states = 2 * n_seg

        td_exact = np.zeros(n_orig, dtype=np.float64) if exact_mode else np.empty(0, dtype=np.float64)
        td_pivot = np.zeros(n_seg, dtype=np.float64) if not exact_mode else np.empty(0, dtype=np.float64)
        ch_int = np.zeros(n_seg, dtype=np.int64) if (with_choice and exact_mode) else np.empty(0, dtype=np.int64)
        ch_flt = np.zeros(n_seg, dtype=np.float64) if (with_choice and not exact_mode) else np.empty(0, dtype=np.float64)

        d_dist = np.empty(n_states, dtype=np.float64)
        d_pred = np.empty(n_states, dtype=np.int32)
        d_hcap = len(d_indices) + n_states + 16
        d_hv = np.empty(d_hcap, dtype=np.int32)
        d_hd = np.empty(d_hcap, dtype=np.float64)
        d_order = np.empty(n_states, dtype=np.int32)
        sub_w = np.zeros(n_states, dtype=np.int64)
        reached_depths = np.empty(n_mem, dtype=np.float64)
        inf = np.inf

        # Track touched states for small components so reset is O(|visited|) and safe
        small_comp = n_mem * 4 < n_seg
        touched = np.empty(n_states, dtype=np.int32) if small_comp else np.empty(0, dtype=np.int32)
        n_touched = 0
        if small_comp:
            d_dist.fill(inf)

        for oi in range(n_orig):
            origin = int(origins[oi])
            r0 = origin << 1
            r1 = r0 + 1

            if small_comp:
                for ti in range(n_touched):
                    d_dist[touched[ti]] = inf
                n_touched = 0
                touched[0] = r0
                touched[1] = r1
                n_touched = 2
            else:
                d_dist.fill(inf)

            d_dist[r0] = 0.0
            d_dist[r1] = 0.0
            d_pred[r0] = -1
            d_pred[r1] = -1
            d_hv[0] = r0
            d_hd[0] = 0.0
            d_hv[1] = r1
            d_hd[1] = 0.0
            dhsize = 2

            n_pop = 0
            if with_choice:
                while dhsize > 0:
                    u, d, dhsize = _lheap_pop(d_hv, d_hd, dhsize)
                    if d > d_dist[u]:
                        continue
                    d_order[n_pop] = u
                    n_pop += 1
                    start = d_indptr[u]
                    end = d_indptr[u + 1]
                    for k in range(start, end):
                        v = int(d_indices[k])
                        nd = d + d_data[k]
                        old_dv = d_dist[v]
                        if nd < old_dv:
                            if small_comp and old_dv == inf:
                                touched[n_touched] = v
                                n_touched += 1
                            d_dist[v] = nd
                            d_pred[v] = u
                            if d_indptr[v] < d_indptr[v + 1]:
                                dhsize = _lheap_push(d_hv, d_hd, dhsize, v, nd)
            else:
                while dhsize > 0:
                    u, d, dhsize = _lheap_pop(d_hv, d_hd, dhsize)
                    if d > d_dist[u]:
                        continue
                    start = d_indptr[u]
                    end = d_indptr[u + 1]
                    for k in range(start, end):
                        v = int(d_indices[k])
                        nd = d + d_data[k]
                        old_dv = d_dist[v]
                        if nd < old_dv:
                            if small_comp and old_dv == inf:
                                touched[n_touched] = v
                                n_touched += 1
                            d_dist[v] = nd
                            if d_indptr[v] < d_indptr[v + 1]:
                                dhsize = _lheap_push(d_hv, d_hd, dhsize, v, nd)

            if with_choice:
                for j in range(n_pop):
                    sub_w[d_order[j]] = 0

            if exact_mode:
                n_r = 0
                for mi in range(n_mem):
                    s = int(members[mi])
                    s0 = s << 1
                    s1 = s0 + 1
                    d0 = d_dist[s0]
                    d1 = d_dist[s1]
                    if d0 <= d1:
                        best_d = d0
                        rep_state = s0
                    else:
                        best_d = d1
                        rep_state = s1
                    if best_d < inf:
                        reached_depths[n_r] = best_d
                        n_r += 1
                        if with_choice and s != origin:
                            if d_indptr[rep_state] < d_indptr[rep_state + 1]:
                                sub_w[rep_state] += 1
                            else:
                                p = int(d_pred[rep_state])
                                if p >= 0:
                                    sub_w[p] += 1
                                    ps = p >> 1
                                    if ps != origin:
                                        ch_int[ps] += 1
                td_exact[oi] = _np_pairwise_sum(reached_depths, 0, n_r)
                if with_choice:
                    for j in range(n_pop - 1, -1, -1):
                        v = int(d_order[j])
                        w = sub_w[v]
                        p = int(d_pred[v])
                        if p >= 0:
                            sub_w[p] += w
                            ps = p >> 1
                            if ps != origin:
                                ch_int[ps] += w
            else:
                for mi in range(n_mem):
                    s = int(members[mi])
                    s0 = s << 1
                    s1 = s0 + 1
                    d0 = d_dist[s0]
                    d1 = d_dist[s1]
                    if d0 <= d1:
                        best_d = d0
                        rep_state = s0
                    else:
                        best_d = d1
                        rep_state = s1
                    if best_d < inf:
                        td_pivot[s] += scale * best_d
                        if with_choice and s != origin:
                            if d_indptr[rep_state] < d_indptr[rep_state + 1]:
                                sub_w[rep_state] += 1
                            else:
                                p = int(d_pred[rep_state])
                                if p >= 0:
                                    sub_w[p] += 1
                                    ps = p >> 1
                                    if ps != origin:
                                        ch_flt[ps] += scale
                if with_choice:
                    for j in range(n_pop - 1, -1, -1):
                        v = int(d_order[j])
                        w = sub_w[v]
                        p = int(d_pred[v])
                        if p >= 0:
                            sub_w[p] += w
                            ps = p >> 1
                            if ps != origin:
                                ch_flt[ps] += scale * float(w)

        if exact_mode:
            return td_exact, ch_int.astype(np.float64)
        return td_pivot, ch_flt

    # ------------------------------------------------------------------
    # KERNEL 6: O(N) Subtree Sums (for direct callers of _subtree_sums)
    # ------------------------------------------------------------------
    @njit(cache=True, nogil=True)
    def subtree_sums_numba(pred: np.ndarray, weights: np.ndarray) -> np.ndarray:
        n = len(pred)
        total = weights.astype(np.float64).copy()
        indeg = np.zeros(n, dtype=np.int32)
        for v in range(n):
            p = int(pred[v])
            if 0 <= p < n:
                indeg[p] += 1
        queue = np.empty(n, dtype=np.int32)
        head = 0
        tail = 0
        for v in range(n):
            if indeg[v] == 0:
                queue[tail] = v
                tail += 1
        while head < tail:
            v = int(queue[head])
            head += 1
            p = int(pred[v])
            if 0 <= p < n:
                total[p] += total[v]
                indeg[p] -= 1
                if indeg[p] == 0:
                    queue[tail] = p
                    tail += 1
        return total

    # ------------------------------------------------------------------
    # KERNEL 7: Space Syntax Geometry Assembly & Polyline Stats
    # ------------------------------------------------------------------
    @njit(cache=True, nogil=True)
    def _dp_simplify_indices(
        xy: np.ndarray,
        start: int,
        end: int,
        tol2: float,
        keep: np.ndarray,
        stack_lo: np.ndarray,
        stack_hi: np.ndarray,
    ) -> None:
        keep[start] = 1
        keep[end] = 1
        if end - start <= 1:
            return
        sp = 0
        stack_lo[sp] = start
        stack_hi[sp] = end
        sp += 1
        while sp > 0:
            sp -= 1
            lo = int(stack_lo[sp])
            hi = int(stack_hi[sp])
            ax = xy[lo, 0]
            ay = xy[lo, 1]
            dx = xy[hi, 0] - ax
            dy = xy[hi, 1] - ay
            len2 = dx * dx + dy * dy
            best_d2 = -1.0
            best_i = -1
            if len2 == 0.0:
                for i in range(lo + 1, hi):
                    px = xy[i, 0] - ax
                    py = xy[i, 1] - ay
                    d2 = px * px + py * py
                    if d2 > best_d2:
                        best_d2 = d2
                        best_i = i
            else:
                inv_len2 = 1.0 / len2
                for i in range(lo + 1, hi):
                    px = xy[i, 0] - ax
                    py = xy[i, 1] - ay
                    t = (px * dx + py * dy) * inv_len2
                    if t <= 0.0:
                        d2 = px * px + py * py
                    elif t >= 1.0:
                        qx = xy[i, 0] - xy[hi, 0]
                        qy = xy[i, 1] - xy[hi, 1]
                        d2 = qx * qx + qy * qy
                    else:
                        cx = px - t * dx
                        cy = py - t * dy
                        d2 = cx * cx + cy * cy
                    if d2 > best_d2:
                        best_d2 = d2
                        best_i = i
            if best_d2 > tol2 and best_i > lo:
                keep[best_i] = 1
                if best_i - lo > 1:
                    stack_lo[sp] = lo
                    stack_hi[sp] = best_i
                    sp += 1
                if hi - best_i > 1:
                    stack_lo[sp] = best_i
                    stack_hi[sp] = hi
                    sp += 1

    @njit(cache=True, nogil=True)
    def polyline_batch_stats_numba(
        all_xy: np.ndarray,
        all_ll: np.ndarray,
        offsets: np.ndarray,
        node_xy: np.ndarray,
        seg_a: np.ndarray,
        seg_b: np.ndarray,
        raw_len: np.ndarray,
        tol: float,
    ) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        n_seg = len(seg_a)
        seg_len = np.empty(n_seg, dtype=np.float64)
        seg_bend = np.empty(n_seg, dtype=np.float64)
        dir_a = np.empty((n_seg, 2), dtype=np.float64)
        dir_b = np.empty((n_seg, 2), dtype=np.float64)
        mid_xy = np.empty((n_seg, 2), dtype=np.float64)
        mid_ll = np.empty((n_seg, 2), dtype=np.float64)

        max_pts = 2
        for s in range(n_seg):
            cnt = int(offsets[s + 1] - offsets[s])
            if cnt > max_pts:
                max_pts = cnt

        keep = np.empty(max_pts, dtype=np.uint8)
        stack_lo = np.empty(max_pts + 4, dtype=np.int32)
        stack_hi = np.empty(max_pts + 4, dtype=np.int32)
        simp_x = np.empty(max_pts, dtype=np.float64)
        simp_y = np.empty(max_pts, dtype=np.float64)
        bends = np.empty(max_pts, dtype=np.float64)
        cum = np.empty(max_pts, dtype=np.float64)
        tol2 = tol * tol

        for s in range(n_seg):
            o0 = int(offsets[s])
            o1 = int(offsets[s + 1])
            m = o1 - o0
            if m <= 0:
                seg_len[s] = 0.1
                seg_bend[s] = 0.0
                dir_a[s, 0] = 0.0
                dir_a[s, 1] = 0.0
                dir_b[s, 0] = 0.0
                dir_b[s, 1] = 0.0
                mid_xy[s, 0] = node_xy[seg_a[s], 0]
                mid_xy[s, 1] = node_xy[seg_a[s], 1]
                mid_ll[s, 0] = 0.0
                mid_ll[s, 1] = 0.0
                continue

            cum[0] = 0.0
            total_l = 0.0
            for i in range(1, m):
                dx = all_xy[o0 + i, 0] - all_xy[o0 + i - 1, 0]
                dy = all_xy[o0 + i, 1] - all_xy[o0 + i - 1, 1]
                total_l += np.hypot(dx, dy)
                cum[i] = total_l

            rl = raw_len[s]
            if not np.isfinite(rl) or rl <= 0.0:
                rl = total_l
            seg_len[s] = rl if rl >= 0.1 else 0.1

            if total_l <= 0.0:
                mid_xy[s, 0] = all_xy[o0, 0]
                mid_xy[s, 1] = all_xy[o0, 1]
                mid_ll[s, 0] = all_ll[o0, 0]
                mid_ll[s, 1] = all_ll[o0, 1]
            else:
                half = total_l * 0.5
                lo_i = 0
                hi_i = m - 1
                while lo_i + 1 < hi_i:
                    mi = (lo_i + hi_i) >> 1
                    if cum[mi] <= half:
                        lo_i = mi
                    else:
                        hi_i = mi
                c0 = cum[lo_i]
                c1 = cum[lo_i + 1]
                dc = c1 - c0
                if dc > 0.0:
                    dt = half - c0
                    mid_xy[s, 0] = all_xy[o0 + lo_i, 0] + dt * ((all_xy[o0 + lo_i + 1, 0] - all_xy[o0 + lo_i, 0]) / dc)
                    mid_xy[s, 1] = all_xy[o0 + lo_i, 1] + dt * ((all_xy[o0 + lo_i + 1, 1] - all_xy[o0 + lo_i, 1]) / dc)
                    mid_ll[s, 0] = all_ll[o0 + lo_i, 0] + dt * ((all_ll[o0 + lo_i + 1, 0] - all_ll[o0 + lo_i, 0]) / dc)
                    mid_ll[s, 1] = all_ll[o0 + lo_i, 1] + dt * ((all_ll[o0 + lo_i + 1, 1] - all_ll[o0 + lo_i, 1]) / dc)
                else:
                    mid_xy[s, 0] = all_xy[o0 + lo_i, 0]
                    mid_xy[s, 1] = all_xy[o0 + lo_i, 1]
                    mid_ll[s, 0] = all_ll[o0 + lo_i, 0]
                    mid_ll[s, 1] = all_ll[o0 + lo_i, 1]

            if m > 2 and tol > 0.0:
                for i in range(m):
                    keep[i] = 0
                _dp_simplify_indices(all_xy[o0:o1], 0, m - 1, tol2, keep, stack_lo, stack_hi)
                n_simp = 0
                for i in range(m):
                    if keep[i]:
                        simp_x[n_simp] = all_xy[o0 + i, 0]
                        simp_y[n_simp] = all_xy[o0 + i, 1]
                        n_simp += 1
            else:
                n_simp = m
                for i in range(m):
                    simp_x[i] = all_xy[o0 + i, 0]
                    simp_y[i] = all_xy[o0 + i, 1]

            has_step = False
            first_ux = 0.0
            first_uy = 0.0
            prev_ux = 0.0
            prev_uy = 0.0
            n_bends = 0
            for i in range(1, n_simp):
                sx = simp_x[i] - simp_x[i - 1]
                sy = simp_y[i] - simp_y[i - 1]
                sl = np.hypot(sx, sy)
                if sl > 1e-6:
                    ux = sx / sl
                    uy = sy / sl
                    if not has_step:
                        first_ux = ux
                        first_uy = uy
                        has_step = True
                    else:
                        dot = prev_ux * ux + prev_uy * uy
                        if dot < -1.0:
                            dot = -1.0
                        elif dot > 1.0:
                            dot = 1.0
                        bends[n_bends] = np.degrees(np.arccos(dot))
                        n_bends += 1
                    prev_ux = ux
                    prev_uy = uy

            if not has_step:
                cx = node_xy[seg_b[s], 0] - node_xy[seg_a[s], 0]
                cy = node_xy[seg_b[s], 1] - node_xy[seg_a[s], 1]
                cn = np.hypot(cx, cy)
                if cn > 1e-9:
                    dir_a[s, 0] = cx / cn
                    dir_a[s, 1] = cy / cn
                    dir_b[s, 0] = -cx / cn
                    dir_b[s, 1] = -cy / cn
                else:
                    dir_a[s, 0] = 0.0
                    dir_a[s, 1] = 0.0
                    dir_b[s, 0] = 0.0
                    dir_b[s, 1] = 0.0
                seg_bend[s] = 0.0
            else:
                dir_a[s, 0] = first_ux
                dir_a[s, 1] = first_uy
                dir_b[s, 0] = -prev_ux
                dir_b[s, 1] = -prev_uy
                seg_bend[s] = _np_pairwise_sum(bends, 0, n_bends) if n_bends > 0 else 0.0

        return seg_len, seg_bend, dir_a, dir_b, mid_xy, mid_ll

    @njit(cache=True, nogil=True)
    def assemble_transitions_numba(
        n_nodes: int,
        seg_a: np.ndarray,
        seg_b: np.ndarray,
        seg_dir_a: np.ndarray,
        seg_dir_b: np.ndarray,
    ) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        n_seg = len(seg_a)
        deg = np.zeros(n_nodes, dtype=np.int64)
        for s in range(n_seg):
            deg[seg_a[s]] += 1
            deg[seg_b[s]] += 1

        ptr = np.empty(n_nodes + 1, dtype=np.int64)
        ptr[0] = 0
        max_k = 0
        for u in range(n_nodes):
            d = deg[u]
            if d > max_k:
                max_k = d
            ptr[u + 1] = ptr[u] + d

        inc_seg = np.empty(2 * n_seg, dtype=np.int64)
        inc_side = np.empty(2 * n_seg, dtype=np.int8)
        cur = ptr[:-1].copy()
        for s in range(n_seg):
            ua = seg_a[s]
            pos_a = cur[ua]
            inc_seg[pos_a] = s
            inc_side[pos_a] = 0
            cur[ua] = pos_a + 1

            ub = seg_b[s]
            pos_b = cur[ub]
            inc_seg[pos_b] = s
            inc_side[pos_b] = 1
            cur[ub] = pos_b + 1

        total_moves = 0
        for u in range(n_nodes):
            p0 = ptr[u]
            p1 = ptr[u + 1]
            if p1 - p0 < 2:
                continue
            for i in range(p0, p1):
                si = inc_seg[i]
                for j in range(p0, p1):
                    if inc_seg[j] != si:
                        total_moves += 1

        tr_from = np.empty(total_moves, dtype=np.int64)
        tr_to = np.empty(total_moves, dtype=np.int64)
        tr_dots = np.empty(total_moves, dtype=np.float64)
        out_buf = np.empty((max_k, 2), dtype=np.float64)
        out_i = 0

        for u in range(n_nodes):
            p0 = ptr[u]
            p1 = ptr[u + 1]
            k = p1 - p0
            if k < 2:
                continue
            out = out_buf[:k]
            for idx in range(k):
                si = inc_seg[p0 + idx]
                if inc_side[p0 + idx] == 0:
                    out[idx, 0] = seg_dir_a[si, 0]
                    out[idx, 1] = seg_dir_a[si, 1]
                else:
                    out[idx, 0] = seg_dir_b[si, 0]
                    out[idx, 1] = seg_dir_b[si, 1]
            # Call BLAS dgemm (identical rounding to NumPy out @ out.T)
            dm = np.ascontiguousarray(out) @ np.ascontiguousarray(out.T)
            for i in range(k):
                si = inc_seg[p0 + i]
                arrive = (2 * si) if inc_side[p0 + i] == 1 else (2 * si + 1)
                for j in range(k):
                    sj = inc_seg[p0 + j]
                    if sj == si:
                        continue
                    depart = (2 * sj) if inc_side[p0 + j] == 0 else (2 * sj + 1)
                    tr_from[out_i] = arrive
                    tr_to[out_i] = depart
                    tr_dots[out_i] = dm[i, j]
                    out_i += 1

        return tr_from, tr_to, tr_dots

    # ------------------------------------------------------------------
    # KERNEL 8: suggest_shortcut with early exit once all near targets settle
    # ------------------------------------------------------------------
    @njit(cache=True, nogil=True)
    def suggest_shortcut_numba(
        m_indptr: np.ndarray,
        m_indices: np.ndarray,
        m_data: np.ndarray,
        seg_mid_xy: np.ndarray,
        shown: np.ndarray,
        origins: np.ndarray,
        lo: float,
        hi: float,
        min_detour: float,
    ) -> Tuple[int, float, int, int, float, float]:
        n_seg = len(seg_mid_xy)
        n_states = 2 * n_seg
        n_shown = len(shown)

        dist = np.empty(n_states, dtype=np.float64)
        seen = np.zeros(n_states, dtype=np.int32)
        hcap = len(m_indices) + n_states + 16
        hv = np.empty(hcap, dtype=np.int32)
        hd = np.empty(hcap, dtype=np.float64)

        target_stamp = np.zeros(n_seg, dtype=np.int32)
        target_done = np.zeros(n_seg, dtype=np.int32)
        near_list = np.empty(n_shown, dtype=np.int32)
        near_straight = np.empty(n_shown, dtype=np.float64)
        near_road = np.empty(n_seg, dtype=np.float64)

        stamp = np.int32(0)
        found_any = 0
        best_ratio = -1.0
        best_a = -1
        best_b = -1
        best_straight = 0.0
        best_road = 0.0

        for oi in range(len(origins)):
            o = int(origins[oi])
            ox = seg_mid_xy[o, 0]
            oy = seg_mid_xy[o, 1]
            stamp += np.int32(1)

            n_near = 0
            for si in range(n_shown):
                s = int(shown[si])
                st_d = np.hypot(seg_mid_xy[s, 0] - ox, seg_mid_xy[s, 1] - oy)
                if lo <= st_d <= hi:
                    target_stamp[s] = stamp
                    near_list[n_near] = s
                    near_straight[n_near] = st_d
                    n_near += 1
            if n_near == 0:
                continue

            r0 = o << 1
            r1 = r0 + 1
            seen[r0] = stamp
            seen[r1] = stamp
            dist[r0] = 0.0
            dist[r1] = 0.0
            hv[0] = r0
            hd[0] = 0.0
            hv[1] = r1
            hd[1] = 0.0
            hsize = 2

            remaining = n_near
            while hsize > 0 and remaining > 0:
                u, d, hsize = _lheap_pop(hv, hd, hsize)
                if d > dist[u]:
                    continue
                s = u >> 1
                if target_stamp[s] == stamp and target_done[s] != stamp:
                    target_done[s] = stamp
                    near_road[s] = d
                    remaining -= 1
                start = m_indptr[u]
                end = m_indptr[u + 1]
                for k in range(start, end):
                    v = int(m_indices[k])
                    nd = d + m_data[k]
                    if seen[v] != stamp or nd < dist[v]:
                        seen[v] = stamp
                        dist[v] = nd
                        hsize = _lheap_push(hv, hd, hsize, v, nd)

            o_best_ratio = -1.0
            o_best_b = -1
            o_best_straight = 0.0
            o_best_road = 0.0
            for ni in range(n_near):
                s = int(near_list[ni])
                if target_done[s] == stamp:
                    rd = near_road[s]
                    st_d = near_straight[ni]
                    denom = st_d if st_d > 1e-9 else 1e-9
                    ratio = rd / denom
                    if ratio > o_best_ratio:
                        o_best_ratio = ratio
                        o_best_b = s
                        o_best_straight = st_d
                        o_best_road = rd

            if o_best_ratio >= min_detour and (found_any == 0 or o_best_ratio > best_ratio):
                found_any = 1
                best_ratio = o_best_ratio
                best_a = o
                best_b = o_best_b
                best_straight = o_best_straight
                best_road = o_best_road

        return found_any, best_ratio, best_a, best_b, best_straight, best_road

    # ------------------------------------------------------------------
    # KERNEL 9: Evidence Image Processing — Single-Pass Parcel Cell Stats
    # ------------------------------------------------------------------
    @njit(cache=True, nogil=True)
    def parcel_label_stats_numba(
        labels: np.ndarray,
        n: int,
    ) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        h, w = labels.shape
        area = np.zeros(n, dtype=np.int64)
        perim = np.zeros(n, dtype=np.float64)
        touches = np.zeros(n, dtype=np.uint8)
        sx = np.zeros(n, dtype=np.float64)
        sy = np.zeros(n, dtype=np.float64)
        sxx = np.zeros(n, dtype=np.float64)
        syy = np.zeros(n, dtype=np.float64)
        sxy = np.zeros(n, dtype=np.float64)

        for r in range(h):
            r0 = r - 1 if r > 0 else 0
            r1 = r + 1 if r + 1 < h else h - 1
            rf = float(r)
            rf2 = rf * rf
            is_r_edge = (r == 0) or (r == h - 1)
            for c in range(w):
                lab = int(labels[r, c])
                if lab <= 0 or lab > n:
                    continue
                idx = lab - 1
                area[idx] += 1
                cf = float(c)
                sx[idx] += cf
                sy[idx] += rf
                sxx[idx] += cf * cf
                syy[idx] += rf2
                sxy[idx] += cf * rf
                if is_r_edge or c == 0 or c == w - 1:
                    touches[idx] = 1
                c0 = c - 1 if c > 0 else 0
                c1 = c + 1 if c + 1 < w else w - 1
                if (
                    labels[r0, c0] != lab
                    or labels[r0, c] != lab
                    or labels[r0, c1] != lab
                    or labels[r, c0] != lab
                    or labels[r, c1] != lab
                    or labels[r1, c0] != lab
                    or labels[r1, c] != lab
                    or labels[r1, c1] != lab
                ):
                    perim[idx] += 1.0

        return area, perim, touches, sx, sy, sxx, syy, sxy

    # ------------------------------------------------------------------
    # KERNEL 10: Evidence Image Processing — Single-Pass Plan Tile Shares
    # ------------------------------------------------------------------
    @njit(cache=True, nogil=True)
    def plan_tile_shares_numba(
        rgba: np.ndarray,
        lut: np.ndarray,
        n_classes: int,
        cells: int,
        alpha_threshold: int,
    ) -> Tuple[np.ndarray, int, int, int, np.ndarray, np.ndarray]:
        h = rgba.shape[0]
        w = rgba.shape[1]
        px = h // cells if cells > 0 else 0
        shares = np.zeros((n_classes + 1, cells, cells), dtype=np.uint32)
        hist4 = np.zeros(4096, dtype=np.int64)
        red_sum = np.zeros(3, dtype=np.int64)
        painted = 0
        explained = 0
        red_pixels = 0
        if px <= 0:
            return shares, painted, explained, red_pixels, red_sum, hist4
        h_lim = cells * px
        w_lim = h_lim if h_lim <= w else w

        for r in range(h_lim):
            cy = (cells - 1) - (r // px)
            sample_r = (r & 3) == 0
            for c in range(w_lim):
                if np.int32(rgba[r, c, 3]) <= alpha_threshold:
                    continue
                painted += 1
                rv = np.int32(rgba[r, c, 0])
                gv = np.int32(rgba[r, c, 1])
                bv = np.int32(rgba[r, c, 2])
                cx = c // px

                k = np.int32(lut[((rv >> 3) << 10) | ((gv >> 3) << 5) | (bv >> 3)])
                if k >= 0:
                    explained += 1
                    shares[k, cy, cx] += np.uint32(1)

                mx = rv if rv >= gv else gv
                if bv > mx:
                    mx = bv
                mn = rv if rv <= gv else gv
                if bv < mn:
                    mn = bv
                d = mx - mn
                gb = gv - bv
                if rv == mx and mx >= 128 and 5 * d >= mx and 2 * gb >= -d and 4 * gb <= d:
                    red_pixels += 1
                    red_sum[0] += rv
                    red_sum[1] += gv
                    red_sum[2] += bv
                    shares[n_classes, cy, cx] += np.uint32(1)

                if sample_r and (c & 3) == 0:
                    hist4[((rv >> 4) << 8) | ((gv >> 4) << 4) | (bv >> 4)] += 1

        return shares, painted, explained, red_pixels, red_sum, hist4

    # ------------------------------------------------------------------
    # KERNEL 11: Evidence Image Processing — Classify Colors + 3x3 Majority
    # ------------------------------------------------------------------
    @njit(cache=True, nogil=True)
    def classify_colors_numba(
        rgba: np.ndarray,
        legend_rgb: np.ndarray,
        tolerance: float,
        alpha_threshold: int,
    ) -> np.ndarray:
        h, w = rgba.shape[0], rgba.shape[1]
        n_cls = legend_rgb.shape[0]
        tol2 = float(tolerance * tolerance)
        cls = np.full((h, w), -1, dtype=np.int16)

        for r in range(h):
            for c in range(w):
                if np.int32(rgba[r, c, 3]) <= alpha_threshold:
                    continue
                rv = float(rgba[r, c, 0])
                gv = float(rgba[r, c, 1])
                bv = float(rgba[r, c, 2])
                best_d2 = tol2 + 1.0
                best_k = -1
                for k in range(n_cls):
                    dr = rv - legend_rgb[k, 0]
                    dg = gv - legend_rgb[k, 1]
                    db = bv - legend_rgb[k, 2]
                    d2 = dr * dr + dg * dg + db * db
                    if d2 <= tol2 and d2 < best_d2:
                        best_d2 = d2
                        best_k = k
                cls[r, c] = best_k

        out = np.full((h, w), -1, dtype=np.int16)
        counts = np.zeros(n_cls, dtype=np.int32)
        for r in range(h):
            r0 = r - 1 if r > 0 else 0
            r1 = r + 1 if r + 1 < h else h - 1
            for c in range(w):
                c0 = c - 1 if c > 0 else 0
                c1 = c + 1 if c + 1 < w else w - 1
                for k in range(n_cls):
                    counts[k] = 0
                for rr in (r0, r, r1):
                    for cc in (c0, c, c1):
                        v = int(cls[rr, cc])
                        if v >= 0:
                            counts[v] += 1
                best_k = -1
                best_cnt = 4
                for k in range(n_cls):
                    if counts[k] > best_cnt:
                        best_cnt = counts[k]
                        best_k = k
                out[r, c] = best_k
        return out


# ----------------------------------------------------------------------------
# Thread-safe JIT warmup & host wrappers (deterministic across CPU cores)
# ----------------------------------------------------------------------------
def _ensure_jit_compiled(key: str, fn: Any, *warmup_args: Any) -> None:
    """Ensure a Numba dispatcher compiles/loads its cache strictly single-threaded.

    Numba's C dispatcher compilation & disk-cache deserialization is NOT
    thread-safe on first call; warming up once under ``_JIT_LOCK`` before any
    ``ThreadPoolExecutor`` dispatch (or concurrent Streamlit rerun) eliminates
    all concurrent-compile races permanently.
    """
    if key in _WARMED_KERNELS:
        return
    with _JIT_LOCK:
        if key in _WARMED_KERNELS:
            return
        fn(*warmup_args)
        _WARMED_KERNELS.add(key)


def _call_jit_safe(key: str, fn: Any, *args: Any) -> Any:
    """Invoke a single-threaded Numba kernel with compile-once locking."""
    if key in _WARMED_KERNELS:
        return fn(*args)
    with _JIT_LOCK:
        res = fn(*args)
        _WARMED_KERNELS.add(key)
        return res


def _split_chunks(arr: np.ndarray, min_chunk: int = 16) -> List[np.ndarray]:
    n = len(arr)
    if n == 0:
        return []
    workers = _N_WORKERS
    if workers <= 1 or n < min_chunk * 2:
        return [np.ascontiguousarray(arr)]
    n_chunks = min(workers, max(1, n // min_chunk))
    return [np.ascontiguousarray(c) for c in np.array_split(arr, n_chunks) if len(c)]


def brandes_edge_betweenness_fast(
    indptr: np.ndarray,
    indices: np.ndarray,
    weights: np.ndarray,
    edge_ids: np.ndarray,
    sources: np.ndarray,
    n_nodes: int,
    n_edges: int,
    exact_all_sources: bool = False,
    comp_sizes: Optional[np.ndarray] = None,
) -> np.ndarray:
    """Run compiled Brandes edge betweenness across CPU cores.

    When ``exact_all_sources=True`` (all nodes are sources), applies exact
    1-core dead-end tree peeling first so only the smaller 2-core runs Dijkstra.
    """
    if n_nodes <= 1 or n_edges <= 0:
        return np.zeros(max(0, int(n_edges)), dtype=np.float64)

    indptr_i = np.ascontiguousarray(indptr, dtype=np.int32)
    indices_i = np.ascontiguousarray(indices, dtype=np.int32)
    weights_f = np.ascontiguousarray(weights, dtype=np.float64)
    edge_ids_i = np.ascontiguousarray(edge_ids, dtype=np.int32)
    n_nodes_i = int(n_nodes)
    n_edges_i = int(n_edges)

    if exact_all_sources and comp_sizes is not None:
        (
            c_indptr, c_indices, c_weights, c_eids,
            _core_orig, core_weight, _core_tree_dist,
            peel_u, _peel_p, _peel_w, peel_eid, peel_sub, n_peel,
        ) = _call_jit_safe("_peel_one_core", _peel_one_core, indptr_i, indices_i, weights_f, edge_ids_i, n_nodes_i)
        bc = np.zeros(n_edges_i, dtype=np.float64)
        # Exact tree-edge contributions in O(N)
        for k in range(n_peel):
            u = int(peel_u[k])
            su = float(peel_sub[k])
            nc = float(comp_sizes[u])
            bc[peel_eid[k]] += 2.0 * su * (nc - su)

        n_core = len(core_weight)
        core_sources = np.ascontiguousarray(np.flatnonzero(np.diff(c_indptr) > 0), dtype=np.int32)
        if len(core_sources) > 0:
            _ensure_jit_compiled(
                "_brandes_edge_bc_chunk",
                _brandes_edge_bc_chunk,
                c_indptr, c_indices, c_weights, c_eids, core_weight,
                np.empty(0, dtype=np.int32), n_core, n_edges_i, False,
            )
            chunks = _split_chunks(core_sources, min_chunk=16)
            if len(chunks) <= 1:
                part_bc, _ = _brandes_edge_bc_chunk(
                    c_indptr, c_indices, c_weights, c_eids, core_weight, core_sources, n_core, n_edges_i, False
                )
                bc += part_bc
            else:
                ex = _get_executor()
                futs = [
                    ex.submit(
                        _brandes_edge_bc_chunk,
                        c_indptr, c_indices, c_weights, c_eids, core_weight, ch, n_core, n_edges_i, False,
                    )
                    for ch in chunks
                ]
                for fut in futs:
                    bc += fut.result()[0]
        bc *= 1.0 / (float(n_nodes_i) * float(n_nodes_i - 1))
        return bc

    sources_i = np.ascontiguousarray(sources, dtype=np.int32)
    if len(sources_i) == 0:
        return np.zeros(n_edges_i, dtype=np.float64)
    unit_w = np.ones(n_nodes_i, dtype=np.int64)
    _ensure_jit_compiled(
        "_brandes_edge_bc_chunk",
        _brandes_edge_bc_chunk,
        indptr_i, indices_i, weights_f, edge_ids_i, unit_w,
        np.empty(0, dtype=np.int32), n_nodes_i, n_edges_i, False,
    )
    chunks = _split_chunks(sources_i, min_chunk=16)
    if len(chunks) <= 1:
        bc, _ = _brandes_edge_bc_chunk(
            indptr_i, indices_i, weights_f, edge_ids_i, unit_w, sources_i, n_nodes_i, n_edges_i, False
        )
    else:
        ex = _get_executor()
        futs = [
            ex.submit(
                _brandes_edge_bc_chunk,
                indptr_i, indices_i, weights_f, edge_ids_i, unit_w, ch, n_nodes_i, n_edges_i, False,
            )
            for ch in chunks
        ]
        bc = np.zeros(n_edges_i, dtype=np.float64)
        for fut in futs:
            bc += fut.result()[0]

    bc *= 1.0 / (float(len(sources_i)) * float(n_nodes_i - 1))
    return bc


def closeness_exact_fast(
    indptr: np.ndarray,
    indices: np.ndarray,
    weights: np.ndarray,
    n_nodes: int,
) -> np.ndarray:
    """Exact all-pairs row sums on a connected CSR graph using exact 1-core peeling."""
    n_nodes_i = int(n_nodes)
    if n_nodes_i <= 0:
        return np.empty(0, dtype=np.float64)
    indptr_i = np.ascontiguousarray(indptr, dtype=np.int32)
    indices_i = np.ascontiguousarray(indices, dtype=np.int32)
    weights_f = np.ascontiguousarray(weights, dtype=np.float64)
    dummy_eids = np.zeros(len(indices_i), dtype=np.int32)

    (
        c_indptr, c_indices, c_weights, _c_eids,
        core_orig, core_weight, core_tree_dist,
        peel_u, peel_p, peel_w, _peel_eid, peel_sub, n_peel,
    ) = _call_jit_safe("_peel_one_core", _peel_one_core, indptr_i, indices_i, weights_f, dummy_eids, n_nodes_i)

    n_core = len(core_orig)
    total_tree_dist = float(core_tree_dist.sum())
    sums = np.empty(n_nodes_i, dtype=np.float64)

    if n_core <= 1:
        if n_core == 1:
            sums[core_orig[0]] = total_tree_dist
    else:
        _ensure_jit_compiled(
            "_dijkstra_closeness_core_chunk",
            _dijkstra_closeness_core_chunk,
            c_indptr, c_indices, c_weights, core_weight, np.empty(0, dtype=np.int32), n_core,
        )
        sources = np.arange(n_core, dtype=np.int32)
        chunks = _split_chunks(sources, min_chunk=32)
        if len(chunks) <= 1:
            core_sums = _dijkstra_closeness_core_chunk(c_indptr, c_indices, c_weights, core_weight, sources, n_core)
        else:
            ex = _get_executor()
            futs = [
                ex.submit(_dijkstra_closeness_core_chunk, c_indptr, c_indices, c_weights, core_weight, ch, n_core)
                for ch in chunks
            ]
            core_sums = np.concatenate([fut.result() for fut in futs])
        sums[core_orig] = core_sums + total_tree_dist

    # Unpeel in reverse order: sum_d[u] = sum_d[p] + (N - 2 * sub[u]) * w_up
    n_f = float(n_nodes_i)
    for k in range(n_peel - 1, -1, -1):
        u = int(peel_u[k])
        p = int(peel_p[k])
        sums[u] = sums[p] + (n_f - 2.0 * float(peel_sub[k])) * peel_w[k]
    return sums


def closeness_pivot_fast(
    indptr: np.ndarray,
    indices: np.ndarray,
    weights: np.ndarray,
    pivots: np.ndarray,
    n_nodes: int,
) -> np.ndarray:
    """Eppstein-Wang pivot column sums across CPU cores."""
    n_nodes_i = int(n_nodes)
    if n_nodes_i <= 0:
        return np.empty(0, dtype=np.float64)
    indptr_i = np.ascontiguousarray(indptr, dtype=np.int32)
    indices_i = np.ascontiguousarray(indices, dtype=np.int32)
    weights_f = np.ascontiguousarray(weights, dtype=np.float64)
    pivots_i = np.ascontiguousarray(pivots, dtype=np.int32)
    if len(pivots_i) == 0:
        return np.zeros(n_nodes_i, dtype=np.float64)
    _ensure_jit_compiled(
        "_dijkstra_closeness_pivot_chunk",
        _dijkstra_closeness_pivot_chunk,
        indptr_i, indices_i, weights_f, np.empty(0, dtype=np.int32), n_nodes_i,
    )
    chunks = _split_chunks(pivots_i, min_chunk=16)
    if len(chunks) <= 1:
        return _dijkstra_closeness_pivot_chunk(indptr_i, indices_i, weights_f, pivots_i, n_nodes_i)
    ex = _get_executor()
    futs = [ex.submit(_dijkstra_closeness_pivot_chunk, indptr_i, indices_i, weights_f, ch, n_nodes_i) for ch in chunks]
    total = np.zeros(n_nodes_i, dtype=np.float64)
    for fut in futs:
        total += fut.result()
    return total


def anchor_dijkstra_fast(
    indptr: np.ndarray,
    indices: np.ndarray,
    weights: np.ndarray,
    sources: np.ndarray,
    source_is_base: np.ndarray,
    eligible_mask: np.ndarray,
    case_inside: np.ndarray,
    n_nodes: int,
    want_pivot_accum: bool,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Multi-threaded anchor Dijkstra pass returning exact sums without 2D distance allocation."""
    n_nodes_i = int(n_nodes)
    indptr_i = np.ascontiguousarray(indptr, dtype=np.int32)
    indices_i = np.ascontiguousarray(indices, dtype=np.int32)
    weights_f = np.ascontiguousarray(weights, dtype=np.float64)
    sources_i = np.ascontiguousarray(sources, dtype=np.int32)
    base_u8 = np.ascontiguousarray(source_is_base, dtype=np.uint8)
    elig_u8 = np.ascontiguousarray(eligible_mask, dtype=np.uint8)
    case_u8 = np.ascontiguousarray(case_inside, dtype=np.uint8)
    n_cases = case_u8.shape[1]
    want_piv = bool(want_pivot_accum)

    if len(sources_i) == 0 or n_nodes_i <= 0:
        return (
            np.empty(0, dtype=np.float64),
            np.zeros((0, n_cases), dtype=np.float64),
            np.zeros(n_nodes_i, dtype=np.float64) if want_piv else np.empty(0, dtype=np.float64),
            np.zeros((n_nodes_i, n_cases), dtype=np.float64) if (want_piv and n_cases > 0) else np.empty((0, 0), dtype=np.float64),
            np.zeros((n_nodes_i, n_cases), dtype=np.float64) if (want_piv and n_cases > 0) else np.empty((0, 0), dtype=np.float64),
        )

    _ensure_jit_compiled(
        "_anchor_dijkstra_chunk",
        _anchor_dijkstra_chunk,
        indptr_i, indices_i, weights_f,
        np.empty(0, dtype=np.int32), np.empty(0, dtype=np.uint8),
        elig_u8, case_u8, n_nodes_i, want_piv,
    )
    idx_chunks = _split_chunks(np.arange(len(sources_i), dtype=np.int32), min_chunk=16)
    if len(idx_chunks) <= 1:
        return _anchor_dijkstra_chunk(
            indptr_i, indices_i, weights_f, sources_i, base_u8, elig_u8, case_u8, n_nodes_i, want_piv
        )
    ex = _get_executor()
    futs = [
        ex.submit(
            _anchor_dijkstra_chunk,
            indptr_i, indices_i, weights_f,
            np.ascontiguousarray(sources_i[ch], dtype=np.int32),
            np.ascontiguousarray(base_u8[ch], dtype=np.uint8),
            elig_u8, case_u8, n_nodes_i, want_piv,
        )
        for ch in idx_chunks
    ]
    es_parts: List[np.ndarray] = []
    cr_parts: List[np.ndarray] = []
    pivot_sum = np.zeros(n_nodes_i, dtype=np.float64) if want_piv else np.empty(0, dtype=np.float64)
    case_pivot = np.zeros((n_nodes_i, n_cases), dtype=np.float64) if (want_piv and n_cases > 0) else np.empty((0, 0), dtype=np.float64)
    case_outer = np.zeros((n_nodes_i, n_cases), dtype=np.float64) if (want_piv and n_cases > 0) else np.empty((0, 0), dtype=np.float64)
    for fut in futs:
        es, cr, ps, cp, co = fut.result()
        es_parts.append(es)
        cr_parts.append(cr)
        if want_piv:
            pivot_sum += ps
            if n_cases > 0:
                case_pivot += cp
                case_outer += co
    return np.concatenate(es_parts), np.vstack(cr_parts), pivot_sum, case_pivot, case_outer


def ss_local_pass_fast(
    depth_matrix: Any,
    metric_matrix: Any,
    n_seg: int,
    radii: Sequence[float],
    with_choice: bool,
    tick_batch: Optional[Callable[[int], None]] = None,
) -> Dict[float, Tuple[np.ndarray, np.ndarray, Optional[np.ndarray]]]:
    """Multi-threaded compiled Space Syntax local pass."""
    r_sorted = np.ascontiguousarray(sorted(float(r) for r in radii), dtype=np.float64)
    n_seg_i = int(n_seg)
    with_ch = bool(with_choice)
    if len(r_sorted) == 0:
        return {}
    if n_seg_i <= 0:
        return {
            r: (np.zeros(0, dtype=np.float64), np.zeros(0, dtype=np.float64), np.zeros(0, dtype=np.float64) if with_ch else None)
            for r in r_sorted.tolist()
        }

    m_indptr = np.ascontiguousarray(metric_matrix.indptr, dtype=np.int32)
    m_indices = np.ascontiguousarray(metric_matrix.indices, dtype=np.int32)
    m_data = np.ascontiguousarray(metric_matrix.data, dtype=np.float64)
    d_indptr = np.ascontiguousarray(depth_matrix.indptr, dtype=np.int32)
    d_indices = np.ascontiguousarray(depth_matrix.indices, dtype=np.int32)
    d_data = np.ascontiguousarray(depth_matrix.data, dtype=np.float64)

    _ensure_jit_compiled(
        "_ss_local_chunk",
        _ss_local_chunk,
        m_indptr, m_indices, m_data, d_indptr, d_indices, d_data,
        n_seg_i, r_sorted, np.empty(0, dtype=np.int32), with_ch,
    )

    origins = np.arange(n_seg_i, dtype=np.int32)
    workers = _N_WORKERS
    if n_seg_i < 64 or workers <= 1:
        nc_all, td_all, ch_int = _ss_local_chunk(
            m_indptr, m_indices, m_data, d_indptr, d_indices, d_data, n_seg_i, r_sorted, origins, with_ch
        )
        if tick_batch is not None:
            tick_batch(n_seg_i)
        ch_all = ch_int.astype(np.float64) if with_ch else None
    else:
        n_batches = max(workers, min(workers * 4, max(1, n_seg_i // 64)))
        chunks = [np.ascontiguousarray(c, dtype=np.int32) for c in np.array_split(origins, n_batches) if len(c)]
        ex = _get_executor()
        futs = [
            (
                ch,
                ex.submit(
                    _ss_local_chunk,
                    m_indptr, m_indices, m_data, d_indptr, d_indices, d_data, n_seg_i, r_sorted, ch, with_ch,
                ),
            )
            for ch in chunks
        ]
        n_r = len(r_sorted)
        nc_all = np.zeros((n_r, n_seg_i), dtype=np.float64)
        td_all = np.zeros((n_r, n_seg_i), dtype=np.float64)
        ch_acc = np.zeros((n_r, n_seg_i), dtype=np.int64) if with_ch else None
        for ch, fut in futs:
            p_nc, p_td, p_ch = fut.result()
            nc_all[:, ch] = p_nc
            td_all[:, ch] = p_td
            if with_ch and ch_acc is not None:
                ch_acc += p_ch
            if tick_batch is not None:
                tick_batch(len(ch))
        ch_all = ch_acc.astype(np.float64) if (with_ch and ch_acc is not None) else None

    out: Dict[float, Tuple[np.ndarray, np.ndarray, Optional[np.ndarray]]] = {}
    for ri, r in enumerate(r_sorted.tolist()):
        out[r] = (nc_all[ri], td_all[ri], ch_all[ri] if ch_all is not None else None)
    return out


def ss_global_component_fast(
    depth_matrix: Any,
    n_seg: int,
    members: np.ndarray,
    origins: np.ndarray,
    exact_mode: bool,
    scale: float,
    with_choice: bool,
    tick_batch: Optional[Callable[[int], None]] = None,
) -> Tuple[np.ndarray, Optional[np.ndarray]]:
    """Multi-threaded compiled Space Syntax global pass for one connected component."""
    n_seg_i = int(n_seg)
    exact_b = bool(exact_mode)
    with_ch = bool(with_choice)
    scale_f = float(scale)
    orig_i = np.ascontiguousarray(origins, dtype=np.int32)
    n_orig = len(orig_i)
    if n_seg_i <= 0 or n_orig == 0:
        td_empty = np.zeros(0 if exact_b else max(0, n_seg_i), dtype=np.float64)
        ch_empty = np.zeros(max(0, n_seg_i), dtype=np.float64) if with_ch else None
        return td_empty, ch_empty

    d_indptr = np.ascontiguousarray(depth_matrix.indptr, dtype=np.int32)
    d_indices = np.ascontiguousarray(depth_matrix.indices, dtype=np.int32)
    d_data = np.ascontiguousarray(depth_matrix.data, dtype=np.float64)
    mem_i = np.ascontiguousarray(members, dtype=np.int32)

    _ensure_jit_compiled(
        "_ss_global_chunk",
        _ss_global_chunk,
        d_indptr, d_indices, d_data, n_seg_i, mem_i,
        np.empty(0, dtype=np.int32), exact_b, scale_f, with_ch,
    )

    workers = _N_WORKERS
    if n_orig < 32 or workers <= 1:
        td_part, ch_part = _ss_global_chunk(
            d_indptr, d_indices, d_data, n_seg_i, mem_i, orig_i, exact_b, scale_f, with_ch
        )
        if tick_batch is not None:
            tick_batch(n_orig)
        return td_part, (ch_part if with_ch else None)

    n_batches = max(workers, min(workers * 4, max(1, n_orig // 32)))
    chunks = [np.ascontiguousarray(c, dtype=np.int32) for c in np.array_split(orig_i, n_batches) if len(c)]
    ex = _get_executor()
    futs = [
        (
            ch,
            ex.submit(
                _ss_global_chunk,
                d_indptr, d_indices, d_data, n_seg_i, mem_i, ch, exact_b, scale_f, with_ch,
            ),
        )
        for ch in chunks
    ]
    if exact_b:
        td_parts: List[np.ndarray] = []
    else:
        td_acc = np.zeros(n_seg_i, dtype=np.float64)
    ch_acc = np.zeros(n_seg_i, dtype=np.float64) if with_ch else None
    for ch, fut in futs:
        p_td, p_ch = fut.result()
        if exact_b:
            td_parts.append(p_td)
        else:
            td_acc += p_td
        if with_ch and ch_acc is not None:
            ch_acc += p_ch
        if tick_batch is not None:
            tick_batch(len(ch))

    return (np.concatenate(td_parts) if exact_b else td_acc), ch_acc


# ----------------------------------------------------------------------------
# Thread-safe host wrappers for single-threaded compiled kernels
# ----------------------------------------------------------------------------
def subtree_sums_fast(pred: np.ndarray, weights: np.ndarray) -> np.ndarray:
    return _call_jit_safe(
        "subtree_sums_numba",
        subtree_sums_numba,
        np.ascontiguousarray(pred, dtype=np.int32),
        np.ascontiguousarray(weights, dtype=np.float64),
    )


def polyline_batch_stats_fast(
    all_xy: np.ndarray,
    all_ll: np.ndarray,
    offsets: np.ndarray,
    node_xy: np.ndarray,
    seg_a: np.ndarray,
    seg_b: np.ndarray,
    raw_len: np.ndarray,
    tol: float,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    return _call_jit_safe(
        "polyline_batch_stats_numba",
        polyline_batch_stats_numba,
        np.ascontiguousarray(all_xy, dtype=np.float64),
        np.ascontiguousarray(all_ll, dtype=np.float64),
        np.ascontiguousarray(offsets, dtype=np.int64),
        np.ascontiguousarray(node_xy, dtype=np.float64),
        np.ascontiguousarray(seg_a, dtype=np.int64),
        np.ascontiguousarray(seg_b, dtype=np.int64),
        np.ascontiguousarray(raw_len, dtype=np.float64),
        float(tol),
    )


def assemble_transitions_fast(
    n_nodes: int,
    seg_a: np.ndarray,
    seg_b: np.ndarray,
    seg_dir_a: np.ndarray,
    seg_dir_b: np.ndarray,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    tr_from, tr_to, tr_dots = _call_jit_safe(
        "assemble_transitions_numba",
        assemble_transitions_numba,
        int(n_nodes),
        np.ascontiguousarray(seg_a, dtype=np.int64),
        np.ascontiguousarray(seg_b, dtype=np.int64),
        np.ascontiguousarray(seg_dir_a, dtype=np.float64),
        np.ascontiguousarray(seg_dir_b, dtype=np.float64),
    )
    if len(tr_dots) == 0:
        return tr_from, tr_to, np.empty(0, dtype=np.float64)
    tr_defl = 180.0 - np.degrees(np.arccos(np.clip(tr_dots, -1.0, 1.0)))
    return tr_from, tr_to, tr_defl


def edge_betweenness_for_multigraph(
    G_undir: Any,
    k_samples: Optional[int] = None,
    seed: int = 42,
) -> Optional[Dict[Tuple[Any, Any], float]]:
    """Compiled weighted Brandes edge betweenness matching NetworkX on an undirected (Multi)Graph.

    Returns ``{tuple(sorted((u, v))): score}`` or ``None`` if any edge weight is
    missing/non-positive or SciPy/Numba is unavailable (caller falls back to NetworkX).
    """
    if not HAS_NUMBA:
        return None
    import networkx as nx
    from scipy.sparse import csr_matrix
    from scipy.sparse.csgraph import connected_components

    nodes = list(G_undir)
    n = len(nodes)
    if n < 2:
        return {}
    node_idx = {node: i for i, node in enumerate(nodes)}

    # Collapse parallel edges to min weight (matches NetworkX _single_source_dijkstra_path_basic)
    # while recording every non-loop pair so even 0-score edges exist in the output dict.
    edge_min: Dict[Tuple[int, int], float] = {}
    self_loops: List[Tuple[Any, Any]] = []
    is_multi = G_undir.is_multigraph()
    if is_multi:
        for u, v, data in G_undir.edges(data=True):
            iu, iv = node_idx[u], node_idx[v]
            w_raw = data.get("length", 1.0)
            try:
                w = float(w_raw)
            except (TypeError, ValueError):
                return None
            if not np.isfinite(w) or w <= 0.0:
                return None
            if iu == iv:
                self_loops.append((u, v))
                continue
            key = (iu, iv) if iu < iv else (iv, iu)
            prev = edge_min.get(key)
            if prev is None or w < prev:
                edge_min[key] = w
    else:
        for u, v, data in G_undir.edges(data=True):
            iu, iv = node_idx[u], node_idx[v]
            w_raw = data.get("length", 1.0)
            try:
                w = float(w_raw)
            except (TypeError, ValueError):
                return None
            if not np.isfinite(w) or w <= 0.0:
                return None
            if iu == iv:
                self_loops.append((u, v))
                continue
            key = (iu, iv) if iu < iv else (iv, iu)
            edge_min[key] = w

    m = len(edge_min)
    if m == 0:
        return {tuple(sorted(pair)): 0.0 for pair in self_loops}

    pair_list = list(edge_min.keys())
    w_list = list(edge_min.values())
    lo = np.fromiter((p[0] for p in pair_list), dtype=np.int32, count=m)
    hi = np.fromiter((p[1] for p in pair_list), dtype=np.int32, count=m)
    eids_u = np.arange(m, dtype=np.int32)
    ws_u = np.asarray(w_list, dtype=np.float64)

    rows = np.concatenate((lo, hi))
    cols = np.concatenate((hi, lo))
    vals = np.concatenate((ws_u, ws_u))
    # Build CSR and track edge_id per directed slot identically via a parallel integer CSR
    csr_w = csr_matrix((vals, (rows, cols)), shape=(n, n))
    csr_e = csr_matrix((np.concatenate((eids_u, eids_u)) + 1, (rows, cols)), shape=(n, n))
    edge_ids = (csr_e.data - 1).astype(np.int32)

    exact_all = k_samples is None or k_samples >= n
    if exact_all:
        n_comp, labels = connected_components(csr_w, directed=False)
        sizes = np.bincount(labels, minlength=n_comp)
        comp_sizes = sizes[labels].astype(np.int64)
        sources = np.arange(n, dtype=np.int32)
    else:
        comp_sizes = None
        sampled_nodes = nx.utils.create_py_random_state(seed).sample(nodes, int(k_samples))
        sources = np.fromiter((node_idx[nd] for nd in sampled_nodes), dtype=np.int32, count=len(sampled_nodes))

    bc = brandes_edge_betweenness_fast(
        csr_w.indptr, csr_w.indices, csr_w.data, edge_ids,
        sources, n, m, exact_all_sources=exact_all, comp_sizes=comp_sizes,
    )

    out: Dict[Tuple[Any, Any], float] = {}
    for eid, (iu, iv) in enumerate(pair_list):
        nu, nv = nodes[iu], nodes[iv]
        out[(nu, nv) if nu <= nv else (nv, nu)] = float(bc[eid])
    for u, v in self_loops:
        out.setdefault((u, v) if u <= v else (v, u), 0.0)
    return out


def suggest_shortcut_fast(
    metric_matrix: Any,
    seg_mid_xy: np.ndarray,
    shown: np.ndarray,
    origins: np.ndarray,
    lo: float,
    hi: float,
    min_detour: float,
) -> Tuple[int, float, int, int, float, float]:
    return _call_jit_safe(
        "suggest_shortcut_numba",
        suggest_shortcut_numba,
        np.ascontiguousarray(metric_matrix.indptr, dtype=np.int32),
        np.ascontiguousarray(metric_matrix.indices, dtype=np.int32),
        np.ascontiguousarray(metric_matrix.data, dtype=np.float64),
        np.ascontiguousarray(seg_mid_xy, dtype=np.float64),
        np.ascontiguousarray(shown, dtype=np.int32),
        np.ascontiguousarray(origins, dtype=np.int32),
        float(lo),
        float(hi),
        float(min_detour),
    )


def parcel_label_stats_fast(
    labels: np.ndarray,
    n: int,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    return _call_jit_safe(
        "parcel_label_stats_numba",
        parcel_label_stats_numba,
        np.ascontiguousarray(labels, dtype=np.int32),
        int(n),
    )


def plan_tile_shares_fast(
    rgba: np.ndarray,
    lut: np.ndarray,
    n_classes: int,
    cells: int,
    alpha_threshold: int,
) -> Tuple[np.ndarray, int, int, int, np.ndarray, np.ndarray]:
    return _call_jit_safe(
        "plan_tile_shares_numba",
        plan_tile_shares_numba,
        np.ascontiguousarray(rgba, dtype=np.uint8),
        np.ascontiguousarray(lut, dtype=np.int8),
        int(n_classes),
        int(cells),
        int(alpha_threshold),
    )


def classify_colors_fast(
    rgba: np.ndarray,
    legend_rgb: np.ndarray,
    tolerance: float,
    alpha_threshold: int,
) -> np.ndarray:
    return _call_jit_safe(
        "classify_colors_numba",
        classify_colors_numba,
        np.ascontiguousarray(rgba, dtype=np.uint8),
        np.ascontiguousarray(legend_rgb, dtype=np.float64),
        float(tolerance),
        int(alpha_threshold),
    )


