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
queries. An **opt-in evidence stage** (below) scans the whole study circle for the
red city-plan zone (ผังสีสูงสุด, พาณิชยกรรม) and the densest cluster of small parcels
(รูปแปลงที่ดินถี่) inside it, and adds a third, purple-marker anchor with a confidence level;
it is off by default and never changes the two road anchors. Optional rent observations
already supported by the page are used only to fit and compare the rent model (R² at the
study centre against R² at the anchor); they never affect the anchor score.

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

## Evidence stage (opt-in): peak colour × dense parcel cluster, scanned over the study radius

Roads find the *network* centre; the official plan and the parcel layer say where the
*commercial* centre is. Tick **🗺️ Evidence: ผังสีสูงสุด + แปลงที่ดินถี่ cluster (ทดลอง)** before pressing
the search button. The road search is unchanged; afterwards `run_evidence_stage` scans the
**whole study circle** (the radius you set, in km) instead of confirming a few road candidates:

1. **One global grid.** Web-Mercator is cut into cells of 128 m (≈120 m on the ground at
   20°N). Plan tiles are 16 384 m (128×128 cells, ≈15 m/px) and parcel tiles 1 024 m (8×8 cells,
   ≈0.94 m/px, the scale at which ตึกแถว lots stay measurable). Tiles sit at fixed
   coordinates, so a tile is the **same request and the same cache file whatever the centre or
   radius**: a second run costs 0 requests and a wider circle fetches only the new plan tiles.
   Window sizes of the old design depended on the candidates and were never shared.
2. **Plan pass.** The `cityplan_dpt` tiles that touch the circle are fetched (≤ 16, ≤ 4 in
   parallel). Every pixel is classified with a 32³ look-up table built from the legend; class shares
   are counted per cell.
3. **Peak colour (ผังสีสูงสุด) = the red zone.** The peak zone is made of the legend classes flagged
   `commercial` (พาณิชยกรรม, red in the provisional legend): cells where ≥ 40 % of the pixels have that
   colour, grouped 8-connected, kept when a group has ≥ 4 cells (≈ 0.06 km²). Green farmland and every
   other colour are never the peak, **and when the radius holds no red zone the stage does not fall to a
   lower colour** (e.g. dense residential): it takes the fallback below. With several red zones in the
   radius, the densest cluster over all of them wins, so the answer does not depend on the centre you
   typed. A custom legend file that flags no class `commercial` keeps the single highest-weight class
   (weight > 0) as the peak; such a legend can never be "commercial", so it can never reach HIGH.
4. **Parcel pass.** `dol` tiles are fetched **only where the peak zone is**: ≤ 16 tiles, the ones
   with most zone cells first, nearest the study centre among equals. One label pass per tile
   (the same boundary-line / line-width logic as `parcel_features`) gives every lot's centroid, area
   and aspect.
5. **Frequency per cell.** `cover_small` and `cover_shop` are the share of a cell's ground area
   taken by lots < 200 m² and by ตึกแถว (40–160 m², aspect ≥ 2.5); score =
   0.4·clip(cover_shop/0.5) + 0.3·clip(cover_small/0.5) + 0.3·scaled ink. Coverage, not lot-count
   shares: ten shophouses beside farmland score 0.13, a shophouse quarter 0.88, town / suburb /
   rural 0.07 / 0.03 / 0.00 (synthetic scenes). A cell without drawn lines is **no data**, not low.
6. **Dense cluster (ถี่ cluster).** 3×3 box mean over cells with data; hot cells score ≥ 0.5 and lie
   inside the peak zone (dilated by one cell) and the circle; 8-connected groups of ≥ 3 cells are
   clusters, ranked by mass (Σ score; ties: raster order). The **evidence anchor is the
   score-weighted centroid of the best cluster**. It is not snapped to a road node (Rent Gradient only
   needs `lat`/`lon`). No cluster ⇒ the centre of the largest peak zone (`basis = "zone"`,
   LOW). No peak zone ⇒ see the fallback below.
7. **Fallback (no red zone / plan unreadable).** No red zone in the radius, a blank plan, an area outside the
   published plan, or a legend that explains < 50 % of the painted pixels make the stage look at the parcels within
   1.5 km of the composite road anchor instead: `status = "partial"`, the zoning signal is unknown (never
   HIGH) and the note says why. Without a composite anchor ⇒ `unavailable`.
8. **Confidence.** HIGH needs roads (a road anchor ≤ 300 m away), zoning (peak colour is พาณิชยกรรม
   and the anchor lies in / next to it) and parcels (cluster score ≥ 0.5, ≥ 3 cells) to agree, parcel
   coverage (tiles read ÷ tiles needed) ≥ 0.6, no *unstable* road or evidence probe, and a cluster that
   does not touch the circle edge. MEDIUM: two of three and coverage ≥ 0.4. Otherwise LOW. Thai
   reasons are listed in the sidebar and the marker popup.
9. **Stability probe (indicative, free).** On the rasters already loaded the pick is repeated for a
   radius ×0.8 and for the centre moved 0.2 R north / east / south / west; the peak class and parcel grid
   stay those of the base run. Drift ≤ 5 % of R ⇒ 🟢, ≤ 15 % ⇒ 🟡, else 🔴; a probe that loses the cluster
   counts as a full-radius move. A cluster cut by the circle is flagged and cannot be HIGH.
10. **Bounded and boring.** ≤ 40 requests, 15 s per request, 60 s per run (unfinished tiles are dropped
    and reported). No key, network error, service exception, blank layer or unreadable plan ⇒ the road
    anchors are untouched and the panel says why.

The result (`automated_anchor_evidence_data`, `schema: 2`) is saved with the config and cleared with
the road anchors and by any study-area change. A result saved by the earlier candidate-first version
has no `schema` and is shown as stale (and ignored by Rent) until the search is run again. Map layers
(hidden by default): **Peak colour zone (ผังสีสูงสุด)** and **Parcel clusters (แปลงถี่)**; thumbnails
re-read the plan and parcel tile under the anchor from the disk cache. **Rent Gradient keeps using
the composite anchor** unless the user ticks *ใช้ Evidence Anchor คำนวณ Rent Gradient*.

### What it costs (synthetic world — no network, no Longdo)

| Study radius | Plan tiles (upper bound) | Requests, small town | Requests, 1.5 km zone | Seconds of compute |
| --- | --- | --- | --- | --- |
| 4 km | 2 (≤ 4) | 6 | 16 | 0.5–0.6 |
| 10 km | 4 (≤ 9) | 8 | 18 | 0.2–0.6 |
| 20 km | 11 (≤ 16) | 15 | 25 | 0.4–0.8 |

The previous candidate-first stage sent 25 requests at **every** radius, none of them reusable, and
spent ≈ 8.9 s on analysis (measured with the same kind of fake fetcher: 12 candidates × 2 windows
+ overview). A zone larger than 16 parcel tiles is truncated and reported (`coverage` drops, HIGH is
impossible). The numbers exclude real network latency; a cold run is bounded by the 60 s deadline.
The sidebar shows the request estimate before you press the button (`estimate_evidence_requests`).

### Calibration is still pending (read before trusting a label)

The thresholds were set on **synthetic** rasters (the four scenes in
`tests/test_anchor_evidence.py`, 1-px lines and label specks; the table is from the earlier whole-window
score, the per-cell coverage score of the current stage is quoted above):

| Scene | Ink | Median cell | Cells < 200 m² | ตึกแถว share | Time |
| --- | --- | --- | --- | --- | --- |
| ตึกแถว 4.5 × 16 m | 39.6% | 80 m² | 100% | 91% | 0.3 s |
| town 12 × 25 m | 17.8% | 307 m² | 0% | 0% | 0.13 s |
| suburb 20 × 40 m | 11.1% | 793 m² | 0% | 0% | 0.11 s |
| rural 80 × 120 m | 3.2% | 9,434 m² | 0% | 0% | 0.11 s |

Real Longdo rendering (line colour/width, parcel-number labels, whether the server
stops drawing parcels at some zoom, the exact DPT legend colours) is **unknown** here:
the sandbox cannot reach Longdo (HTTP 000 from here; `Geoapify_Map/fixtures/wms/` does not exist).
Until it is calibrated the page shows a warning, the legend file
`Geoapify_Map/cityplan_legend.json` is absent so a **provisional** 8-class legend (DPT
convention) is used and labelled as such, and the checkbox is off by default.

Three things in the current design are specifically unverified against the real service:

- **Plan tiles are 16 384 Web-Mercator m at 1 024 px (≈ 15 m/px).** If `cityplan_dpt` is not drawn
  at that scale (check `capabilities.xml` for scale limits) every plan tile reads blank and the stage
  falls back to the parcels around the composite road anchor (`partial`, never HIGH). `plan_tile_m` is
  a config key; use `--radius-km 7.7` in the capture command below so its overview window equals one
  plan tile.
- **`peak_cell_share` (0.4)** and the 50 % "legend explains the painted pixels" gate depend on how
  outlines, labels and antialiasing look. A wrong legend shows up as `plan.state = "mismatch"` in the
  JSON and in the notes, not as a silently wrong peak colour.
- **The cell-score references** (`cover_ref` 0.5, hot ≥ 0.5) were set on the four synthetic scenes.

To calibrate, on a machine that can reach Longdo:

```shell
python scripts/capture_wms_fixtures.py --study-center 20.219443 100.403630 --radius-km 7.7 \
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
parcel signal alone is not a CBD (hence the peak-colour gate and the road agreement in the
confidence); DPT plans exist only for planned areas and can be outdated; Longdo's terms for
server-side tile use should be checked (requests are few and cached); the evidence anchor is the
centre of a cluster of 120 m cells, so it is accurate to about a cell and is not snapped to a road node;
parcel analysis covers only the peak-colour zone (≤ 16 tiles) and drops lots cut by a tile edge, which
slightly under-counts border cells; the stability probe keeps the base run's peak class and parcel grid.

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
parcel features and the per-cell frequency score on synthetic rasters (scene separation, label clutter,
rotation, too-coarse windows, blank layers, a few shophouses beside farmland), the global lattice
(shared tiles across centres and radii, tile budget per radius), the colour look-up table, the peak
colour (highest weight with a real zone, specks, weight-0 classes), cluster ranking and tie-breaks,
confidence, the cached WMS fetch and `run_evidence_stage` against a fake Longdo that places pixels by
Web-Mercator position (anchor on the planted quarter, independence of radius and centre, 0 requests on
a repeat, budget and deadline, unreadable plan fallback, parcels failing, stability flip, circle-edge
flag, JSON safety); `tests/test_wms_fixtures.py` runs the capture script against a fake server and
validates real fixtures when present; the Streamlit tests cover the opt-in checkbox and request
estimate, the third marker and map layers, Rent opt-in, invalidation and stale-schema results.
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
