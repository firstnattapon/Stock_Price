# Automated CBD Anchor: road-only, deterministic, one pass

`pages/Rent_Gradient.py` discovers an anchor without a manually guessed CBD pin,
Geoapify key, or precomputed isochrone. In the sidebar, open **Automated CBD
Anchor**, set the study centre and radius, then press **🎯 ค้นหา CBD Anchor
อัตโนมัติ**. One press downloads the roads once and returns **two anchors**:

1. **Composite** (dark-blue marker, used by Rent Gradient ahead of the existing
   centroid fallbacks): closeness, degree and junction density.
2. **Closeness 100%** (green marker, comparison only): the pure network 1-median.

There is no random seed and no number of starts: the same graph always gives the
same answer. Changing the centre, radius or travel mode clears the previous
anchors and the rent result. JSON/config/bundle exports preserve the results and
settings; configs saved by the earlier seeded search still load (their
`random_seed`, `restarts` and `trace` fields are ignored).

The two anchors above use road data only: no POI, population or commerce
queries. An **opt-in evidence stage** (below) can confirm the road candidates with
the official city plan and the parcel layer and adds a third, purple-marker
anchor with a confidence level; it is off by default and never changes the two
road anchors. Optional rent observations already supported by the page are used
only to fit and compare the rent model (R² at the study centre against R² at the
anchor); they never affect the anchor score.

## Overpass reliability and configuration

The road download first checks the graph disk cache (exact match, then a cached
graph that fully covers the footprint — see *Reusing downloads*). On a miss it
tries each server once by default, then fails over in this order:

1. endpoints supplied through `OVERPASS_ENDPOINTS` (comma-separated base URLs),
2. the current `osmnx.settings.overpass_url`,
3. `overpass-api.de`, the VK Maps instance, and `overpass.private.coffee`.

Use base API URLs such as `https://example.org/api`; a trailing `/interpreter`
is accepted and removed because OSMnx appends the request path. Downloads are
serialized while changing OSMnx's process-global endpoint, then the original
setting is restored; cache hits never wait for a download. This prevents
concurrent Streamlit sessions from sending requests to one another's selected
server. A successful graph records the serving endpoint and is persisted to the
disk cache.

If all servers fail, the UI lists every attempted endpoint and its shortened
error. Connection refusal, timeout, invalid HTTP response, and server-status
errors trigger failover. A valid empty OSM response or invalid graph request
does not waste calls on the remaining servers. Public Overpass servers are
shared services: keep caching enabled and configure a self-hosted/paid endpoint
first for sustained or commercial traffic.

## Algorithm (`find_cbd_anchors`)

1. Download one fixed OSM road graph around the study circle with a **20% radial
   buffer** (default radius 10 km, footprint radius 12 km). The selected travel
   mode determines which roads are downloaded.
2. **Vectorised preparation.** Collapse parallel/opposite-direction roads to their
   shortest positive length in metres and drop self loops, build a symmetric CSR
   matrix with NumPy, and keep the largest connected component (SciPy). Node order
   is fixed by `(type, str(id))`, so ties never depend on graph insertion order.
   This measures street accessibility, not driving time or one-way routing.
3. Every inside road node is a shortest-path destination (paths may leave the
   circle through buffered roads). Project coordinates to a local azimuthal
   equidistant CRS. Junctions have at least **three distinct neighbours**;
   density is the count of junctions within **500 m** (inclusive, with a 1e-6 m
   tolerance so lattice points on the circle do not depend on CRS rounding).
4. **Candidates.** Composite: inside junctions (all inside nodes only if there are
   none, disclosed as a warning). Closeness 100%: every inside node, including
   degree-2 nodes.
5. **Reference sample.** Up to 256 destinations chosen with a constant seed (all
   of them when there are fewer). Their exact Dijkstra rows give (a) the exact
   closeness of each pivot, which calibrates the composite normaliser, and (b) a
   pivot closeness `k / sum_p d(v,p)` for *every* node. The sample size depends
   only on the graph (it shrinks as `1/sqrt(V)` above 25,000 nodes, to at least
   96, because pivot rows are the dominant cost there) — never on the run's row
   budget, otherwise a certified and a screened run would use different objectives.
6. **Exact rows, once.** Each exact row serves both objectives. If a candidate
   pool fits the row budget — `rows_budget = clamp(3e7 // V, 64, 4096)`, so about
   4,096 rows at 7k nodes and 750 at 40k — **every candidate is scored** and the
   global maximum of the fixed objective is certified
   (`certification = exhaustive-fixed-objective`). Otherwise the pool is ranked by
   pivot closeness, the top 256 are scored exactly, and a local exhaustive climb
   (150 m neighbourhoods, bounded by the same budget) polishes the best
   (`certification = pivot-screened-exact-top-k`). The screen is independent of
   any seed, never raises a budget error, and is not a global certificate.

```text
C(v)      = (M - 1) / sum_u d(v,u)                    # M inside destination nodes
C_rank(v) = Phi((C(v) - mean_ref) / std_ref)          # Phi = normal CDF
D_rank(v) = mid-rank percentile of distinct-neighbour degree among candidates
J_rank(v) = mid-rank percentile of junction_count_500m among candidates
Composite = 0.50*C_rank + 0.30*D_rank + 0.20*J_rank
Closeness100 = C(v) / (C(v) + 1 / study_radius_m)     # strictly monotone in C
```

`mean_ref`/`std_ref` come from the exact closeness of the reference sample, and
mid-rank percentiles use exact counts over the candidate pool; all three
composite components therefore span a comparable 0..1 range and the nominal
50/30/20 weights are close to the weights that actually order the candidates.
Normalisers and destinations depend only on the graph. Scores are compared after
rounding to 12 decimals, so mathematically tied nodes (e.g. the two middle nodes
of a path) stay tied whatever the summation order and the lowest node index wins. Every result reports
`nominal_weights`, `effective_weights` (`w_i * std_i`, normalised over the pool)
and `winner_contribution`; the sidebar shows them. On the two real road graphs in
`Geoapify_Map/osmnx_cache.zip` the earlier bounded transform `C/(C+1/R)` gave
closeness an effective weight of about 27% against a nominal 50% (density 45-49%
against 20%); the rank-based composite gives about 56/21/23 on the larger graph.
`scoring` records `rank-v2` or `closeness-bounded` so older exports stay
interpretable.

**Removed in this version:** the random-restart pattern search (ARPS: 8 bearings,
radius halving, seeds, traces and its map layers). It never changed the answer
when the exhaustive pass ran, wasted about half of the Dijkstra rows, and was
*less* stable than the pivot screen over budget (on a real graph, 20 single-start
seeds gave 10 different anchors up to 15.7 km apart while the screen gave one).
For graphs the exhaustive pass covers, results are identical to the previous
implementation: node and score match on both real graphs and the synthetic grids.

## Stability probe (indicative)

The anchor is the centre of the road network *inside the circle you choose*, so
it can move with that circle. The search therefore measures it at almost no cost:
while the pivot rows stream through, they are also summed per perturbed circle —
radius ×0.8 and ×1.2, and the centre shifted by 20% of the radius north, east,
south and west. A ×1.2 or shifted circle pulls in roads *outside* the study circle,
so destinations are sampled in two strata — the study circle (the usual pivots) and
the ring up to 1.2 R outside it (96 extra pivot rows, probe only; the anchors never
depend on them) — and combined with a stratified estimate. For each circle the best
16 junctions *anywhere inside that circle* (by that estimate) are scored exactly on
the circle's destinations (reusing rows already computed; degree/density re-ranked
inside the circle; normaliser from the pivots inside it) and the best one's drift
from the anchor is reported:

| Level | Max drift |
| --- | --- |
| 🟢 stable | ≤ 5% of the study radius |
| 🟡 check | ≤ 15% |
| 🔴 unstable | > 15% |

The result carries `stability = {cases, max_drift_m, median_drift_m,
max_drift_ratio, level}`, the sidebar shows a badge and a warning when the level is
not *stable*, and the map popups repeat it. It is **indicative**: it uses pivot
sums and the top 16 candidates. Against exact re-runs of the full search on the
real graphs (6 graph/radius settings × 2 objectives) the level agreed in 12 of 12
cases and 70 of 72 per-circle drifts were identical; on a synthetic "dumbbell"
(a second cluster wholly outside the circle) the probe reports the true 6.7 km
move where a base-circle-only sample reported 0. `scripts/anchor_sensitivity.py`
remains the exact check and prints the in-app probe next to its own numbers. On
the larger real graph (8 km radius) the composite anchor moved at most 379 m
(stable) while the Closeness-100% anchor moved up to 2.3 km (unstable) — one
graph, so treat it as a prompt to check your own area, not as a general result.

## Reusing downloads and where the time goes

Compute is no longer the bottleneck; the OSM download is (142 s cold in the
recorded run). Two things are done with resources that are already there:

- **Covering cache.** Every cached graph now has a small JSON sidecar
  (`osm_graph_<key>.json`: network type, footprint polygon, bounds, size). When a
  request is not in the cache — or the exact-key entry's recorded footprint does
  not contain it (the key is the md5 of bounds rounded to 3 decimals, so a
  different shape with the same bounds shares it; a circle's graph used to be
  served for a same-bbox square, silently missing a quarter of the area) — the
  smallest cached graph of the same network type
  whose footprint **fully contains** the requested polygon is loaded and cropped
  with the same rules as `osmnx.graph_from_polygon` (`truncate_by_edge`, largest
  weakly connected component), then stored under its own key. Partial coverage is
  never used (it would bias the result near the boundary); entries cached before
  this version have no sidecar and are simply not indexed; a missing or corrupt
  sidecar is ignored. Exact-key entries that have no sidecar (imported bundles,
  older caches) cannot be checked: they are still used but labelled
  `cache (footprint unverified)`. It applies to both the anchor search and Network Analysis,
  so running the anchor first lets a later, smaller isochrone union reuse it.
  Disable with `ANCHOR_CONFIG["reuse_covering_cache"] = False`. A cropped graph is
  not byte-identical to a fresh download at the boundary (edge simplification).
- **Timings.** Every result records `load_seconds`, the graph source
  (`download`, `cache` or `cache-crop`) and the compute split
  (`prep_s`, `pivots_s`, `exact_s`); the sidebar prints them.

Measured on synthetic road-like graphs (both anchors and the stability probe):

| Nodes | Previous (ARPS, two searches) | Now |
| --- | --- | --- |
| 10,000 | 2.4 s (one objective) | ≈0.8 s (both), ≈0.9 s with the stability probe |
| 40,000 | 9.1 s (one objective) | ≈4.2 s (both), ≈5.6 s with the stability probe |
| 100,000 (the limit) | — | ≈16 s before the pivot shrink, ≈640 MB peak process memory with the graph |

For 40,000 nodes the split is roughly 0.2 s preparation (previously ≈4 s of Python
graph rebuilding), 1.8 s pivot rows and 1.8 s exact rows; the probe's extra ring
pivots add ≈1.4 s there. These are observations on one machine, not latency
promises, and exclude the Overpass download.

## Evidence stage (opt-in): city plan + parcels confirm the road candidates

Roads find *candidates*; official zoning and the parcel structure *confirm* them.
Tick **🗺️ ใช้ผังเมืองรวม + รูปแปลงที่ดิน ยืนยันผู้สมัคร (ทดลอง)** before pressing
the search button. The road search is unchanged; afterwards `run_evidence_stage`:

1. **Candidates** — `find_cbd_anchors` exports the top 150 exactly-scored nodes per
   objective (`candidate_export`); both road anchors plus the best remaining ones that
   are ≥ 300 m apart (greedy NMS) are kept, up to 12.
2. **Windows** — per candidate one `dol` (รูปแปลงที่ดิน, 1 km) and one `cityplan_dpt`
   (ผังเมืองรวม, 1.5 km) GetMap at 1024 px, plus one city-plan overview of the whole
   study circle. Same Longdo WMS endpoint, `EPSG:3857`, `version 1.1.1`, transparent
   PNG as the map layers. ≤ 4 in parallel, ≤ 40 requests, 15 s timeout, never raises.
   Images are cached on disk (`wms_<sha256 of the parameters>.png` + JSON sidecar; the
   key is not part of the name), so a repeat run costs **0 requests** and the cache
   exports with the rest of the cache bundle.
3. **Parcel features** (`parcel_features`, Pillow + `scipy.ndimage` only) — the ink
   ratio (thick boundary lines ⇒ dense, small parcels), the cells between boundary
   lines (area corrected for line width, principal-axis aspect), `small_share`
   (< 200 m² = 50 ตร.ว.), `shophouse_share` (ตึกแถว: 40–160 m² and aspect ≥ 2.5), and
   `parcel_score` = 0.4·shophouse + 0.3·small + 0.3·scaled ink. A blank or too coarse
   window is **no data**, not "low".
4. **Zoning features** (`zoning_features`) — nearest legend colour per pixel (3×3
   majority vote removes labels/outlines), class shares inside a 300 m disc,
   `zoning_intensity` (weighted by `Geoapify_Map/cityplan_legend.json` class weights),
   `in_commercial` / distance to the nearest พาณิชยกรรม patch. Outside the published
   plan ⇒ **no data**.
5. **Fusion** — `0.35·road + 0.35·parcel + 0.30·zoning` over the signals that have
   data (weights renormalised: a missing signal lowers `coverage`, never the score);
   the winner must have at least one non-road signal, so a failed download cannot
   promote a road-only candidate. Ties break on node id.
6. **Confidence** — HIGH needs coverage ≥ 0.6 and roads (an anchor ≤ 300 m away),
   zoning (inside / ≤ 150 m from the commercial zone) and parcels (score ≥ 0.5) all
   agreeing, and a road stability level other than *unstable*; MEDIUM needs two of
   three and coverage ≥ 0.4; otherwise LOW. Thai reasons are listed in the sidebar and
   in the marker popup.
7. **Failure is boring** — no key, network error, service exception, blank layer or an
   unreadable plan ⇒ `status = "unavailable"` with a one-line reason; the road anchors
   are untouched. A missing layer for some candidates ⇒ `partial`.

The result is published under `automated_anchor_evidence_data` (saved with the config,
cleared with the road anchors and by any study-area change). Thumbnails are not stored;
the expander re-reads them from the disk cache. **Rent Gradient keeps using the
composite anchor** unless the user ticks *ใช้ Evidence Anchor คำนวณ Rent Gradient*.

### Calibration is still pending (read before trusting a label)

The thresholds were set on **synthetic** rasters (the four scenes in
`tests/test_anchor_evidence.py`, 1.5 m/px, 1-px lines and label specks):

| Scene | Ink | Median cell | Cells < 200 m² | ตึกแถว share | Time |
| --- | --- | --- | --- | --- | --- |
| ตึกแถว 4.5 × 16 m | 39.6% | 80 m² | 100% | 91% | 0.3 s |
| town 12 × 25 m | 17.8% | 307 m² | 0% | 0% | 0.13 s |
| suburb 20 × 40 m | 11.1% | 793 m² | 0% | 0% | 0.11 s |
| rural 80 × 120 m | 3.2% | 9,434 m² | 0% | 0% | 0.11 s |

Real Longdo rendering (line colour/width, parcel-number labels, whether the server
stops drawing parcels at some zoom, the exact DPT legend colours) is **unknown** here:
the sandbox cannot reach Longdo. Until it is calibrated the page shows a warning, the
legend file `Geoapify_Map/cityplan_legend.json` is absent so a **provisional**
8-class legend (DPT convention) is used and labelled as such, and the checkbox is off
by default.

To calibrate, on a machine that can reach Longdo:

```shell
python scripts/capture_wms_fixtures.py --study-center 20.219443 100.403630 --radius-km 10 \
    --point core 20.2194 100.4036 --point mid 20.2300 100.4200 --point outskirts 20.2600 100.4700
```

It saves the raw windows (several sizes), `GetCapabilities` and the city-plan legend
into `Geoapify_Map/fixtures/wms/` with a `manifest.json` (no key), and prints the
dominant colours of each plan window and the parcel features of each `dol` window.
Write `Geoapify_Map/cityplan_legend.json`
(`{"classes": [{"name", "rgb", "weight", "commercial"}]}`) from that table and commit
the folder; `tests/test_wms_fixtures.py` then checks the legend explains ≥ 85% of the
painted plan pixels and that the core scores above the outskirts (those tests are
skipped while the folder is absent).

Limits: small parcels also occur in suburban subdivisions and informal housing, so the
parcel signal alone is not a CBD (hence fusion with zoning and roads); DPT plans exist
only for planned areas and can be outdated; Longdo's terms for server-side tile use
should be checked (requests are few and cached); the evidence anchor is chosen among
road candidates, so it cannot lie where the roads give no candidate.

## Reproduce the checks

Install the project requirements and `pytest`, then run:

```shell
python -m pytest tests -q
python scripts/benchmark_cbd_anchor.py --repeat 3 --save-graphml cache/chiang-khong-buffered.graphml --output cache/cbd-audit.json
python scripts/benchmark_cbd_anchor.py --graphml cache/chiang-khong-buffered.graphml --repeat 3 --output cache/cbd-warm-audit.json
python scripts/anchor_sensitivity.py --graph cache/chiang-khong-buffered.graphml --radius-km 10 --output cache/sensitivity.json
```

The audit writes both anchors with score components, certification, exact
evaluation counts, boundary warnings, the timing split, whether repeated runs
returned identical anchors, and the in-app stability level. A warm GraphML audit
does not measure a fresh Overpass download.

For independent validation, supply `--ground-truth LAT LON` and/or
`--samples rent_samples.json` (a list of `lat`, `lon`, `rent` observations).
Without supplied evidence those fields remain null. R² compares log-rent fits at
the study centre and at the anchor; a positive difference is not a statistical
significance test. Independent survey/held-out observations are needed to make
that claim.

Tests cover: exact agreement with NetworkX and an independent brute-force of the
composite; the previous implementation's certified winners on the real road
graphs; minimum parallel-edge lengths; deterministic ordering and repeated calls;
global certification; over-budget screening matching the exhaustive anchor for
both objectives at several budgets; no budget errors; disconnected components;
shortest paths through the buffer; invalid input; missing SciPy; anchor
precedence; rent without isochrones; config round trips and old saved contexts;
one Dijkstra row per node shared by both anchors and the probe; probe levels
against the exact perturbation oracle; covering-cache reuse, crop rules and
corrupt-sidecar handling; actual Streamlit button execution, invalidation and
failure; and the map markers. They also simulate connection refusal,
retry/failover, cache reuse, custom endpoint precedence, bounded all-server
diagnostics, and global setting restore. `tests/test_anchor_evidence.py` covers the
parcel/zoning features on synthetic rasters (scene separation, label clutter, rotation,
too-coarse windows, blank layers), fusion, confidence, the cached WMS fetch and
`run_evidence_stage` with a fake fetcher (core vs suburb, partial/unavailable, request
budget, cache counters, JSON safety); `tests/test_wms_fixtures.py` runs the capture
script against a fake server and validates real fixtures when present; the Streamlit
tests cover the opt-in checkbox, third marker, Rent opt-in and invalidation.
`tests/test_rent_gradient_principles.py`
adds regressions for the review fixes (betweenness keys on multigraphs, fit
standard errors, index-mode Value Gap, restricted unpickling and bundle-import
hardening, the narrow Overpass lock, coverage-aware ring density, Golden Spot
spacing).

## Accuracy and limitations

- **150 m is a search radius**, not a demonstrated error bound against the
  economic CBD. Road connectivity and junction density are structural proxies.
- A buffer reduces truncation bias; it cannot eliminate it. Coverage, boundary
  position, graph size, disconnected roads, and OSM mapping practices still
  matter. Expand/shift the study region and compare anchors near the boundary.
- OSM roundabouts and divided carriageways can represent one physical junction
  with several nodes. Three distinct neighbours prevent parallel-edge degree
  inflation, but do not merge such physical intersections.
- The certificate applies only to an unchanged graph, candidate set, and
  objective. Over the row budget the result is screened, not certified.
- Overpass latency is outside this algorithm's control; the covering cache only
  helps when a previously downloaded footprint contains the new one.
- The stability level is an estimate; a *stable* label does not validate the
  anchor against the real CBD.
- Ground-truth CBD error and improved rent-fit significance have **not** been
  established from roads alone. These draft targets require independent data.

Implementation references: [OSMnx API](https://osmnx.readthedocs.io/en/stable/user-reference.html)
and [SciPy sparse graph algorithms](https://docs.scipy.org/doc/scipy/reference/sparse.csgraph.html).
OpenStreetMap road data are © [OpenStreetMap contributors](https://www.openstreetmap.org/copyright).

## Recorded real-road run (2026-09-20)

> Recorded with the original seeded search and scoring (`C/(C+1/R)`, divided-by-
> maximum degree and density). The composite objective now uses rank-normalised
> components, so the winning node and score below will differ when the run is
> repeated; the Closeness-100% anchor, the graph sizes and the 142 s download are
> unaffected, and the "50 seeds" rows no longer have an equivalent (there are no
> seeds). The OSM graph itself is not stored in the repository — re-run the
> commands above to refresh these numbers.

See [the machine-readable benchmark](cbd-anchor-benchmark.json). Chiang Khong,
Thailand, centre `(20.219443, 100.403630)`, 10 km study radius, drive roads:

| Check | Observed result |
| --- | --- |
| Largest-component nodes / inside destinations / candidate junctions | 2,058 / 1,808 / 1,332 |
| Certified final anchor | OSM node 2227037179, `(20.253818, 100.4110003)` |
| 50-start search plus global audit | 0.759 s compute; 0.989 s including GraphML load |
| 50 independent single-start searches | Same certified node in all 50; 0 m final spread |
| Slowest independent search | 0.395 s compute |
| Local endpoints before certification | Up to 18.0 km apart; local search alone fails stability |
| Initial OSM download | 142.44 s; cold-download 10 s target not met |
| Ground-truth CBD error / rent-fit significance | Unverified; independent observations not supplied |

These timings are observations on the recorded machine and graph, not universal
latency promises. OSM edits can change future results.
