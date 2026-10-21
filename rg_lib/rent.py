"""Pure engine — Bid-Rent gradient R(d) = R0*exp(-lambda*d): OLS fit, rings, nodes, ring report. No streamlit, no I/O.

Definitions are cut verbatim from pages/Rent_Gradient.py (see tests/test_rg_v2_equivalence.py).
"""


from math import exp, log, pi, sqrt
from shapely.geometry import shape
from shapely.ops import unary_union
from typing import Any, Dict, List, Optional, Tuple

from .config import RENT_CONFIG, RENT_RAMP, _T_CRIT_975
from .geo import _anchor_projection, _geodesic_circle_coords, haversine_km


def predict_rent(distance_km: float, r0: float, lam: float) -> float:
    """Bid-rent prediction: R(d) = R₀ · e^(−λ·d)."""
    return r0 * exp(-lam * distance_km)


def rent_color_for_norm(norm: float) -> str:
    """Map normalized rent 0..1 (ต่ำ→สูง) onto the sequential ramp (อ่อน→เข้ม)."""
    norm = max(0.0, min(1.0, norm))
    idx = int(round(norm * (len(RENT_RAMP) - 1)))
    return RENT_RAMP[idx]


def t_critical_95(dof: int) -> float:
    """Two-sided 95% t quantile; interpolates conservatively (next-lower df)."""
    if dof < 1:
        return float("inf")
    usable = [k for k in _T_CRIT_975 if k <= dof]
    return _T_CRIT_975[max(usable)] if dof <= 120 else 1.960


def fit_rent_gradient_from_samples(
    samples: List[Dict[str, Any]],
    anchor_lat: float,
    anchor_lon: float,
) -> Optional[Dict[str, Any]]:
    """
    Fit R(d) = R₀·e^(−λd) จากตัวอย่างราคาจริงด้วย log-linear OLS.

    ln(R) = ln(R₀) − λ·d  →  regression เส้นตรงบน (d, ln R)

    Returns ``{r0, lam, r2, n_samples, points}`` หรือ ``None``
    เมื่อข้อมูลไม่พอ (ต้องมี ≥ 2 จุดที่ระยะต่างกัน และราคา > 0).
    """
    pts: List[Tuple[float, float]] = []  # (distance_km, ln_rent)
    for s in samples:
        try:
            lat = float(s["lat"])
            lon = float(s["lon"])
            rent = float(s["rent"])
        except (KeyError, TypeError, ValueError):
            continue
        if rent <= 0:
            continue
        d = haversine_km(anchor_lat, anchor_lon, lat, lon)
        pts.append((d, log(rent)))

    if len(pts) < 2:
        return None

    n = len(pts)
    mean_x = sum(p[0] for p in pts) / n
    mean_y = sum(p[1] for p in pts) / n
    sxx = sum((p[0] - mean_x) ** 2 for p in pts)
    if sxx <= 1e-12:  # ทุกจุดระยะเท่ากัน — fit ไม่ได้
        return None
    sxy = sum((p[0] - mean_x) * (p[1] - mean_y) for p in pts)

    slope = sxy / sxx
    intercept = mean_y - slope * mean_x
    lam = -slope
    r0 = exp(intercept)

    ss_tot = sum((p[1] - mean_y) ** 2 for p in pts)
    ss_res = sum((p[1] - (intercept + slope * p[0])) ** 2 for p in pts)
    r2 = 1.0 - (ss_res / ss_tot) if ss_tot > 1e-12 else 1.0

    # Uncertainty of the slope. With n = 2 the line is exact (no residual degrees
    # of freedom), so R² = 1 carries no information and no interval exists.
    dof = n - 2
    adj_r2: Optional[float] = None
    lam_se: Optional[float] = None
    lam_ci95: Optional[Tuple[float, float]] = None
    half_dist_ci95: Optional[Tuple[float, float]] = None
    if dof > 0:
        if ss_tot > 1e-12:
            adj_r2 = 1.0 - (1.0 - r2) * (n - 1) / dof
        lam_se = sqrt(ss_res / dof / sxx)
        margin = t_critical_95(dof) * lam_se
        lam_ci95 = (lam - margin, lam + margin)
        # d½ = ln2/λ is only bounded when the whole interval stays positive.
        if lam_ci95[0] > RENT_CONFIG["min_lambda"]:
            half_dist_ci95 = (log(2.0) / lam_ci95[1], log(2.0) / lam_ci95[0])

    return {
        "r0": r0,
        "lam": lam,
        "r2": r2,
        "adj_r2": adj_r2,
        "lam_se": lam_se,
        "lam_ci95": lam_ci95,
        "half_dist_ci95": half_dist_ci95,
        "dof": dof,
        "low_confidence": n < RENT_CONFIG["min_reliable_samples"],
        "n_samples": n,
        "points": [{"d": p[0], "rent": exp(p[1])} for p in pts],
    }


def resolve_cbd_anchor(
    intersection_data: Optional[Dict[str, Any]],
    network_data: Optional[Dict[str, Any]],
    isochrone_data: Optional[Dict[str, Any]],
    markers: List[Dict[str, Any]],
    automated_anchor: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """
    หาจุดยึด CBD สำหรับ Rent Gradient ตามลำดับความน่าเชื่อถือ:
    0) Automated CBD Anchor ที่ผู้ใช้สั่งค้นหา
    1) centroid ของ CBD Zone (จุดตัด isochrone)
    2) Integration Center จาก Network Analysis
    3) centroid ของ Travel Areas ทั้งหมด
    4) ค่าเฉลี่ยตำแหน่งหมุดที่ active
    """
    # An explicitly discovered road anchor takes precedence over polygon centroids.
    if automated_anchor:
        return dict(automated_anchor["anchor"])

    # 1) CBD intersection centroid
    try:
        feats = (intersection_data or {}).get("features") or []
        if feats:
            geom = shape(feats[0]["geometry"])
            c = geom.centroid
            return {"lat": c.y, "lon": c.x, "source": "CBD Zone (จุดตัด Isochrone)"}
    except Exception:
        pass

    # 2) Network Integration Center
    try:
        top = (network_data or {}).get("top_node")
        if top and top.get("score", -1) >= 0:
            return {"lat": top["lat"], "lon": top["lon"], "source": "Integration Center (Network)"}
    except Exception:
        pass

    # 3) Union centroid of all isochrones
    try:
        feats = (isochrone_data or {}).get("features") or []
        if feats:
            combined = unary_union([shape(f["geometry"]) for f in feats])
            c = combined.centroid
            return {"lat": c.y, "lon": c.x, "source": "จุดกึ่งกลาง Travel Areas"}
    except Exception:
        pass

    # 4) Mean of active markers
    active = [m for m in markers if m.get("active", True)]
    if active:
        lat = sum(m["lat"] for m in active) / len(active)
        lon = sum(m["lng"] for m in active) / len(active)
        return {"lat": lat, "lon": lon, "source": "ค่าเฉลี่ยตำแหน่งหมุด"}

    return None


def isochrone_max_distance_km(
    anchor_lat: float,
    anchor_lon: float,
    isochrone_data: Optional[Dict[str, Any]],
) -> float:
    """ระยะไกลสุดจากจุดยึดถึงขอบ Travel Areas (ใช้มุม bounding box ของแต่ละ feature)."""
    d_max = 0.0
    feats = (isochrone_data or {}).get("features") or []
    for f in feats:
        try:
            minx, miny, maxx, maxy = shape(f["geometry"]).bounds
        except Exception:
            continue
        for lon, lat in ((minx, miny), (minx, maxy), (maxx, miny), (maxx, maxy)):
            d = haversine_km(anchor_lat, anchor_lon, lat, lon)
            d_max = max(d_max, d)
    if d_max <= 0:
        d_max = RENT_CONFIG["default_d_max_km"]
    return max(d_max, RENT_CONFIG["min_d_max_km"])


def build_rent_rings_geojson(
    anchor_lat: float,
    anchor_lon: float,
    d_max_km: float,
    r0: float,
    lam: float,
    is_index: bool,
    unit_label: str,
) -> Dict[str, Any]:
    """สร้างวงแหวนราคา (annuli) รอบ CBD — สีตามค่าเช่าคาดการณ์ที่กึ่งกลางวง."""
    n_rings = RENT_CONFIG["num_rings"]
    step = d_max_km / n_rings

    # ช่วงค่าเช่าทั้งหมดสำหรับ normalize สี (รองรับกรณี λ < 0 ที่ curve กลับทิศ)
    r_at_0 = predict_rent(0.0, r0, lam)
    r_at_max = predict_rent(d_max_km, r0, lam)
    r_lo, r_hi = min(r_at_0, r_at_max), max(r_at_0, r_at_max)
    r_span = (r_hi - r_lo) or 1.0

    features: List[Dict[str, Any]] = []
    for i in range(1, n_rings + 1):
        r_in = step * (i - 1)
        r_out = step * i
        rent_mid = predict_rent((r_in + r_out) / 2.0, r0, lam)
        norm = (rent_mid - r_lo) / r_span

        outer = _geodesic_circle_coords(anchor_lat, anchor_lon, r_out)
        rings = [outer]
        if r_in > 0:
            rings.append(list(reversed(_geodesic_circle_coords(anchor_lat, anchor_lon, r_in))))

        if is_index:
            rent_label = f"ดัชนี ≈ {rent_mid:.1f} / 100"
        else:
            rent_label = f"≈ {rent_mid:,.0f} {unit_label}"

        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "Polygon", "coordinates": rings},
                "properties": {
                    "band": f"{r_in:.1f} – {r_out:.1f} km",
                    "rent_mid": round(rent_mid, 2),
                    "rent_label": rent_label,
                    "color": rent_color_for_norm(norm),
                },
            }
        )

    return {"type": "FeatureCollection", "features": features}


def build_rent_nodes_geojson(
    nodes_geojson: Optional[Dict[str, Any]],
    anchor_lat: float,
    anchor_lon: float,
    r0: float,
    lam: float,
    d_max_km: float,
) -> Optional[Dict[str, Any]]:
    """ทาสีโหนดถนน (จาก Network Analysis) ตามค่าเช่าคาดการณ์ → Rent Heat."""
    feats = (nodes_geojson or {}).get("features") or []
    if not feats:
        return None

    r_at_0 = predict_rent(0.0, r0, lam)
    r_at_max = predict_rent(d_max_km, r0, lam)
    r_lo, r_hi = min(r_at_0, r_at_max), max(r_at_0, r_at_max)
    r_span = (r_hi - r_lo) or 1.0

    out_features: List[Dict[str, Any]] = []
    for f in feats:
        try:
            lon, lat = f["geometry"]["coordinates"]
        except (KeyError, ValueError, TypeError):
            continue
        rent = predict_rent(haversine_km(anchor_lat, anchor_lon, lat, lon), r0, lam)
        norm = (rent - r_lo) / r_span
        out_features.append(
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [lon, lat]},
                "properties": {
                    "type": "rent_node",
                    "rent": round(rent, 2),
                    "color": rent_color_for_norm(norm),
                },
            }
        )
    return {"type": "FeatureCollection", "features": out_features}


def _ring_index_for_distance(
    d_km: float, step_km: float, n_rings: int
) -> Optional[int]:
    """คืน index วงแหวน (0-based) ของระยะ d_km — ``None`` เมื่ออยู่นอกวงนอกสุด."""
    if step_km <= 0 or d_km < 0:
        return None
    idx = int(d_km / step_km)
    if idx >= n_rings:
        # จุดที่อยู่บนขอบนอกสุดพอดีนับเป็นวงสุดท้าย
        return n_rings - 1 if d_km <= step_km * n_rings + 1e-9 else None
    return idx


def ring_coverage_areas_km2(
    coverage_geojson: Optional[Dict[str, Any]],
    anchor_lat: float,
    anchor_lon: float,
    step_km: float,
    n_rings: int,
) -> Optional[List[float]]:
    """พื้นที่ของ (วงแหวน ∩ พื้นที่ที่ดาวน์โหลดถนนจริง) ต่อวง หน่วย km² (pure).

    โหนด Network มีเฉพาะในพื้นที่ที่ดึงข้อมูลถนน (union ของ isochrone) จึงต้องหาร
    ความหนาแน่นด้วยพื้นที่ที่ครอบจริง ไม่ใช่พื้นที่วงแหวนเต็ม คำนวณในพิกัดเมตร
    (azimuthal equidistant รอบ anchor). คืน ``None`` เมื่อไม่มี/อ่านพื้นที่ไม่ได้.
    """
    if not coverage_geojson or step_km <= 0 or n_rings <= 0:
        return None
    try:
        from shapely.geometry import Point
        from shapely.ops import transform

        projection = _anchor_projection(anchor_lat, anchor_lon)
        geom = transform(
            lambda x, y, z=None: projection.transform(x, y), shape(coverage_geojson)
        )
        if geom.is_empty:
            return None
        if not geom.is_valid:
            geom = geom.buffer(0)
        origin = Point(0.0, 0.0)
        areas: List[float] = []
        for i in range(n_rings):
            outer = origin.buffer(step_km * (i + 1) * 1000.0, quad_segs=64)
            inner = origin.buffer(step_km * i * 1000.0, quad_segs=64) if i else None
            band = outer.difference(inner) if inner is not None else outer
            areas.append(float(band.intersection(geom).area) / 1e6)
        return areas
    except Exception:
        return None


def count_nodes_per_ring(
    nodes_geojson: Optional[Dict[str, Any]],
    anchor_lat: float,
    anchor_lon: float,
    step_km: float,
    n_rings: int,
) -> Tuple[List[int], List[List[float]], int]:
    """นับโหนดถนน (จาก Network Analysis) ต่อวงแหวน Rent Gradient.

    Returns:
        ``(counts, closeness_per_ring, outside_count)`` —
        โหนดที่ไกลกว่าวงนอกสุด (เช่น anchor เลื่อนหลังคำนวณ network)
        นับรวมใน ``outside_count`` เพื่อให้ยอดรวมครบทุกโหนด
    """
    counts: List[int] = [0] * n_rings
    closeness_per_ring: List[List[float]] = [[] for _ in range(n_rings)]
    outside = 0
    for f in ((nodes_geojson or {}).get("features") or []):
        try:
            lon, lat = f["geometry"]["coordinates"]
        except (KeyError, ValueError, TypeError):
            continue
        idx = _ring_index_for_distance(
            haversine_km(anchor_lat, anchor_lon, lat, lon), step_km, n_rings
        )
        if idx is None:
            outside += 1
            continue
        counts[idx] += 1
        closeness_per_ring[idx].append(
            float((f.get("properties") or {}).get("closeness", 0.0))
        )
    return counts, closeness_per_ring, outside


def build_ring_report(
    rent_data: Optional[Dict[str, Any]],
    network_data: Optional[Dict[str, Any]],
    samples: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """สรุปรายวงแหวน Rent Gradient สำหรับ scan หาโซนซื้อที่ดิน (pure).

    1 แถว = 1 วง: ช่วงระยะ, พื้นที่, ค่าเช่าคาดการณ์ และเมื่อมีผล Network
    Analysis จะเติมจำนวนโหนด, ความหนาแน่น, Closeness, Golden Spots และ
    Value Gap (= Closeness เฉลี่ย − ราคา normalize) ตามนิยามเดียวกับ
    ตาราง Golden Spots — ค่าบวกมาก = เข้าถึงง่ายแต่ราคาคาดการณ์ยังต่ำ
    """
    if not rent_data or "error" in rent_data:
        return []
    ring_feats = (rent_data.get("rings_geojson") or {}).get("features") or []
    if not ring_feats:
        return []

    model = rent_data["model"]
    anchor = rent_data["anchor"]
    # Value Gap compares network closeness with R(d)/R0. In index mode R(d)/R0
    # is an assumed decay (1/4 at the edge), so the gap would only echo that
    # assumption; it is reported only when the rent model is fitted to data.
    show_gap = not model.get("is_index")
    n_rings = len(ring_feats)
    d_max = model["d_max_km"]
    step = d_max / n_rings
    r0 = float(model.get("r0") or 0.0)

    nodes_fc = None
    if network_data and "error" not in network_data:
        nodes_fc = network_data.get("nodes")
    has_net = bool((nodes_fc or {}).get("features"))

    counts, closeness_per_ring, outside_nodes = count_nodes_per_ring(
        nodes_fc, anchor["lat"], anchor["lon"], step, n_rings
    )
    total_nodes = sum(counts) + outside_nodes
    coverage_areas = (
        ring_coverage_areas_km2(
            (network_data or {}).get("coverage_geojson"),
            anchor["lat"], anchor["lon"], step, n_rings,
        )
        if has_net else None
    )

    golden_per_ring: List[List[int]] = [[] for _ in range(n_rings)]
    golden_spots = (network_data or {}).get("golden_spots") or []
    for rank, spot in enumerate(golden_spots, start=1):
        idx = _ring_index_for_distance(
            haversine_km(anchor["lat"], anchor["lon"], spot["lat"], spot["lon"]),
            step,
            n_rings,
        )
        if idx is not None:
            golden_per_ring[idx].append(rank)

    samples_per_ring: List[int] = [0] * n_rings
    for s in samples or []:
        try:
            d = haversine_km(
                anchor["lat"], anchor["lon"], float(s["lat"]), float(s["lon"])
            )
        except (KeyError, TypeError, ValueError):
            continue
        idx = _ring_index_for_distance(d, step, n_rings)
        if idx is not None:
            samples_per_ring[idx] += 1

    rows: List[Dict[str, Any]] = []
    for i, feat in enumerate(ring_feats):
        props = feat.get("properties") or {}
        r_in, r_out = step * i, step * (i + 1)
        area_km2 = pi * (r_out ** 2 - r_in ** 2)
        row: Dict[str, Any] = {
            "วง": i + 1,
            "ช่วงระยะจาก CBD": props.get("band", f"{r_in:.1f} – {r_out:.1f} km"),
            "พื้นที่ (km²)": round(area_km2, 2),
            "ค่าเช่าคาดการณ์": props.get(
                "rent_label",
                format_rent_value(
                    predict_rent((r_in + r_out) / 2.0, r0, model["lam"]), model
                ),
            ),
        }
        if has_net:
            n_in = counts[i]
            cl = closeness_per_ring[i]
            cl_mean = (sum(cl) / len(cl)) if cl else 0.0
            rent_mid = float(props.get("rent_mid", 0.0))
            rent_norm = max(0.0, min(1.0, rent_mid / r0)) if r0 > 0 else 0.0
            row["โหนด Network"] = n_in
            row["% โหนด"] = (
                round(100.0 * n_in / total_nodes, 1) if total_nodes else 0.0
            )
            if coverage_areas is not None:
                covered = coverage_areas[i]
                row["พื้นที่ครอบคลุม (km²)"] = round(covered, 2)
                # หารด้วยพื้นที่ที่มีข้อมูลถนนจริง (ไม่ใช่วงแหวนเต็ม) กันค่าต่ำเกินจริงในวงนอก
                density_area = covered if covered > 1e-6 else area_km2
            else:
                density_area = area_km2
            row["โหนด/km²"] = round(n_in / density_area, 1) if density_area > 0 else 0.0
            row["Closeness เฉลี่ย"] = round(cl_mean, 3)
            row["Closeness สูงสุด"] = round(max(cl), 3) if cl else 0.0
            row["Golden Spots"] = ", ".join(map(str, golden_per_ring[i])) or "—"
            if show_gap:
                row["Value Gap"] = round(cl_mean - rent_norm, 3)
        row["ตัวอย่างราคา"] = samples_per_ring[i]
        rows.append(row)

    # โหนดนอกวงนอกสุด — แสดงเป็นแถวสุดท้ายให้ยอดรวมโหนดครบ
    if has_net and outside_nodes > 0:
        rows.append(
            {
                "วง": "—",
                "ช่วงระยะจาก CBD": f"> {d_max:.1f} km (นอกวงนอกสุด)",
                "พื้นที่ (km²)": None,
                **({"พื้นที่ครอบคลุม (km²)": None} if coverage_areas is not None else {}),
                "ค่าเช่าคาดการณ์": "นอกขอบเขตโมเดล",
                "โหนด Network": outside_nodes,
                "% โหนด": (
                    round(100.0 * outside_nodes / total_nodes, 1)
                    if total_nodes
                    else 0.0
                ),
                "โหนด/km²": None,
                "Closeness เฉลี่ย": None,
                "Closeness สูงสุด": None,
                "Golden Spots": "—",
                **({"Value Gap": None} if show_gap else {}),
                "ตัวอย่างราคา": 0,
            }
        )
    return rows


def compute_rent_gradient_data(
    intersection_data: Optional[Dict[str, Any]],
    network_data: Optional[Dict[str, Any]],
    isochrone_data: Optional[Dict[str, Any]],
    markers: List[Dict[str, Any]],
    samples: List[Dict[str, Any]],
    unit_label: str,
    automated_anchor: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    คำนวณ Rent Gradient ทั้งชุด (pure, JSON-serializable):
    anchor → fit/default model → rings + curve + rent heat.
    """
    anchor = resolve_cbd_anchor(
        intersection_data, network_data, isochrone_data, markers, automated_anchor
    )
    if anchor is None:
        return {"error": "ไม่พบจุดยึด CBD — กรุณาปักหมุดและคำนวณ Isochrone ก่อน"}

    d_max = isochrone_max_distance_km(anchor["lat"], anchor["lon"], isochrone_data)
    if automated_anchor and not isochrone_data:
        d_max = automated_anchor["study_radius_m"] / 1000.0

    fit = fit_rent_gradient_from_samples(samples, anchor["lat"], anchor["lon"])
    if fit is not None:
        r0, lam, r2 = fit["r0"], fit["lam"], fit["r2"]
        n_samples = fit["n_samples"]
        fit_stats = {
            key: fit[key]
            for key in ("adj_r2", "lam_se", "lam_ci95", "half_dist_ci95",
                        "dof", "low_confidence")
        }
        is_index = False
        samples_scatter = fit["points"]
        # ขยายขอบเขตกราฟ/วงแหวนให้คลุมตัวอย่างที่อยู่ไกลกว่า Travel Areas
        d_max = max(d_max, max((p["d"] for p in samples_scatter), default=0.0) * 1.05)
    else:
        r0 = RENT_CONFIG["base_index"]
        lam = log(RENT_CONFIG["edge_decay_ratio"]) / d_max
        r2 = None
        n_samples = 0
        fit_stats = {
            "adj_r2": None, "lam_se": None, "lam_ci95": None,
            "half_dist_ci95": None, "dof": 0, "low_confidence": False,
        }
        is_index = True
        samples_scatter = []

    inverted = lam < 0
    abs_lam = abs(lam)
    half_dist = (log(2.0) / abs_lam) if abs_lam > RENT_CONFIG["min_lambda"] else None

    # เส้นโค้ง Bid-Rent สำหรับกราฟ
    n_pts = RENT_CONFIG["curve_points"]
    curve_d = [d_max * i / (n_pts - 1) for i in range(n_pts)]
    curve_r = [predict_rent(d, r0, lam) for d in curve_d]

    rings = build_rent_rings_geojson(
        anchor["lat"], anchor["lon"], d_max, r0, lam, is_index, unit_label
    )
    rent_nodes = build_rent_nodes_geojson(
        (network_data or {}).get("nodes"), anchor["lat"], anchor["lon"], r0, lam, d_max
    )

    # เติมจำนวนโหนด Network ต่อวงลง tooltip ของ Rent Gradient Rings บนแผนที่
    nodes_fc = (network_data or {}).get("nodes") if network_data and "error" not in network_data else None
    ring_feats = rings["features"]
    n_rings = len(ring_feats)
    if nodes_fc and nodes_fc.get("features") and n_rings > 0:
        ring_step = d_max / n_rings
        node_counts, _closeness, _outside = count_nodes_per_ring(
            nodes_fc, anchor["lat"], anchor["lon"], ring_step, n_rings
        )
        for feat, count in zip(ring_feats, node_counts):
            feat["properties"]["nodes_label"] = f"{count:,} โหนด"
    else:
        for feat in ring_feats:
            feat["properties"]["nodes_label"] = "—"

    return {
        "anchor": anchor,
        "model": {
            "r0": r0,
            "lam": lam,
            "r2": r2,
            **fit_stats,
            "n_samples": n_samples,
            "is_index": is_index,
            "inverted": inverted,
            "unit": unit_label,
            "d_max_km": d_max,
            "half_dist_km": half_dist,
        },
        "curve": {"d": curve_d, "r": curve_r},
        "samples_scatter": samples_scatter,
        "rings_geojson": rings,
        "rent_nodes_geojson": rent_nodes,
    }


def format_rent_value(value: float, model: Dict[str, Any]) -> str:
    """แสดงผลราคา: โหมดดัชนี → 'ดัชนี xx/100', โหมดราคาจริง → 'x,xxx หน่วย'."""
    if model.get("is_index"):
        return f"ดัชนี {value:.1f}/100"
    return f"{value:,.0f} {model.get('unit', '')}".strip()


def _fit_dof(model: Dict[str, Any]) -> int:
    """Residual degrees of freedom; derived for results saved before ``dof`` existed."""
    return int(model.get("dof", model.get("n_samples", 0) - 2))


def fit_quality_label(model: Dict[str, Any]) -> str:
    """ป้ายคุณภาพการ fit ที่ระบุจำนวนตัวอย่างเสมอ (ไม่ใช้คำว่า calibrated เปล่า ๆ)."""
    if model.get("is_index") or model.get("r2") is None:
        return "โหมดดัชนี — ยังไม่ calibrate จากราคาจริง"
    n = model.get("n_samples", 0)
    parts = [f"n={n}"]
    if _fit_dof(model) > 0:
        parts.append(f"R²={model['r2']:.3f}")
        if model.get("adj_r2") is not None:
            parts.append(f"adj-R²={model['adj_r2']:.3f}")
    else:
        parts.append("R² ไม่มีความหมาย (2 จุดผ่านเส้นตรงได้พอดี)")
    return "calibrated (" + ", ".join(parts) + ")"


def fit_quality_warning(model: Dict[str, Any]) -> Optional[str]:
    """ข้อความเตือนเมื่อการ fit ยังไม่น่าเชื่อถือ — ``None`` เมื่อไม่มีประเด็น."""
    if model.get("is_index") or model.get("r2") is None:
        return None
    need = RENT_CONFIG["min_reliable_samples"]
    low = model.get("low_confidence")
    if low is None:  # results saved before the flag existed
        low = model.get("n_samples", 0) < need
    if low:
        return (
            f"ตัวอย่าง {model.get('n_samples', 0)} จุด น้อยกว่า {need} จุด — "
            "λ และ d½ ยังไม่น่าเชื่อถือ (2 จุดจะได้ R² = 1 เสมอ) ควรเพิ่มตัวอย่างก่อนใช้ตัดสินใจ"
        )
    ci = model.get("lam_ci95")
    if ci and ci[0] <= 0 <= ci[1]:
        return "ช่วงเชื่อมั่น 95% ของ λ คร่อมศูนย์ — ข้อมูลยังแยกไม่ออกว่าราคาลดลงตามระยะจริงหรือไม่"
    return None


def fit_interval_text(model: Dict[str, Any]) -> Optional[str]:
    """ช่วงเชื่อมั่น 95% ของ λ และ d½ เป็นข้อความ (``None`` เมื่อไม่มีองศาอิสระ)."""
    ci = model.get("lam_ci95")
    if not ci:
        return None
    text = f"λ 95% CI [{ci[0]:.4f}, {ci[1]:.4f}]"
    half_ci = model.get("half_dist_ci95")
    if half_ci:
        text += f" · d½ 95% CI [{half_ci[0]:.2f}, {half_ci[1]:.2f}] km"
    else:
        text += " · d½ ไม่มีขอบเขต (CI ของ λ รวมศูนย์)"
    return text
