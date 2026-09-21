# Automated CBD Anchor: road-only coarse-to-fine search

`pages/Rent_Gradient.py` now discovers an anchor without a manually guessed CBD
pin, Geoapify key, or precomputed isochrone. In the sidebar, open **Automated CBD
Anchor**, set the study centre and radius, choose a reproducible random seed and
number of starts, then press **🎯 ค้นหา CBD Anchor อัตโนมัติ**. The map shows a
dark-blue **Automated CBD Anchor** and an optional search-path layer. Rent
Gradient immediately uses this anchor ahead of the existing centroid fallbacks.
Changing the study settings clears the previous automatic anchor and rent
result. JSON/config/bundle exports preserve the result, settings, and trace.

Only road data are used. There are no POI, population, commerce, or zoning queries.
Optional rent observations already supported by the page are used only to fit
and compare the rent model; they never affect the anchor score.

## Overpass reliability and configuration

The road download first checks the graph disk cache. On a cache miss it tries
each server once by default, then fails over in this order:

1. endpoints supplied through `OVERPASS_ENDPOINTS` (comma-separated base URLs),
2. the current `osmnx.settings.overpass_url`,
3. `overpass-api.de`, the VK Maps instance, and `overpass.private.coffee`.

Use base API URLs such as `https://example.org/api`; a trailing `/interpreter`
is accepted and removed because OSMnx appends the request path. Downloads are
serialized while changing OSMnx's process-global endpoint, then the original
setting is restored. This prevents concurrent Streamlit sessions from sending
requests to one another's selected server. A successful graph records the
serving endpoint and is persisted to the existing disk cache.

If all servers fail, the UI lists every attempted endpoint and its shortened
error. Connection refusal, timeout, invalid HTTP response, and server-status
errors trigger failover. A valid empty OSM response or invalid graph request
does not waste calls on the remaining servers. Public Overpass servers are
shared services: keep caching enabled and configure a self-hosted/paid endpoint
first for sustained or commercial traffic.

## Search and scoring

1. Download one fixed OSM road graph around the study circle with a **20% radial
   buffer**. Default study radius is 10 km, so the graph footprint has radius
   12 km. This footprint does not move with the random seed or follow an
   isochrone. The selected travel mode determines which roads are downloaded.
2. Collapse parallel/opposite-direction roads to their shortest positive length
   in metres; ignore self loops. Use the largest undirected connected component.
   This measures street accessibility, not driving time or one-way routing.
3. Keep every inside road node as a shortest-path destination. Paths can leave
   the study circle through buffered roads and re-enter. Anchors and probes are
   inside junctions with at least **three distinct neighbouring nodes**. If none
   exist, use inside road nodes and disclose the fallback.
4. Project coordinates to a local azimuthal equidistant CRS. Density is the
   count of junction nodes within **500 m**, including the candidate itself when
   it is a junction. This is equivalent to density per fixed circle area for
   normalised scoring. It is not an intersection-consolidation or land-use model.
5. Sample distinct starting junctions using NumPy's seeded generator. Each
   start scans bearings 0, 45, …, 315 degrees at radius **4,000 m**. A probe snaps
   only to candidates within half its current radius, inside the study circle.
6. Move only to a strictly higher score. Otherwise halve the radius, bounded at
   **150 m**. At 150 m, evaluate every nearby candidate with exact Dijkstra,
   repeating until no strictly better candidate remains. Stable node ordering
   resolves ties reproducibly, including after graph insertion order changes.
7. Road trials showed that local convergence can still trap different starts
   in different centres. If all candidate junctions fit the evaluation budget,
   **audit every candidate** after ARPS and select the globally highest score.
   This certificate applies to the fixed objective and graph, not to the real
   economic CBD. Larger graphs return an explicit `local-only` certificate.

For `M` inside destination nodes and exact shortest road distance `d(v,u)`:

```text
C(v) = (M - 1) / sum_u d(v,u)
C_norm(v) = C(v) / (C(v) + 1 / study_radius_m)
D_norm(v) = distinct_neighbour_degree(v) / max_inside_degree
J_norm(v) = junction_count_500m(v) / max_inside_junction_count_500m
Score(v) = 0.50*C_norm(v) + 0.30*D_norm(v) + 0.20*J_norm(v)
```

Zero maxima use a denominator of one. Normalisers and destinations stay fixed
across probes, scales, and starts. The bounded closeness transform avoids
sample-dependent min/max normalisation, which would otherwise change the
objective while climbing. The final audit certifies the highest **composite
score**, not closeness alone.

SciPy CSR Dijkstra uses a symmetric matrix and at most 16 source rows per batch.
It never allocates an all-pairs distance matrix. A search evaluates at most
2,048 distinct candidates by default and admits at most 100,000 graph nodes.
Each restart has an 80-iteration limit. Exhausting the evaluation budget raises
a visible error; an iteration limit returns `converged=false` with a warning.
The pure function accepts explicit budgets for offline analysis. Road downloads
reuse the existing disk/OSMnx caches. No network calls occur in the search core.

## Reproduce the checks

Install the project requirements and `pytest`, then run:

```shell
python -m pytest tests/test_automated_anchor.py -q
python scripts/benchmark_cbd_anchor.py --restarts 50 --independent-seeds 50 --save-graphml cache/chiang-khong-buffered.graphml --output cache/cbd-audit.json
python scripts/benchmark_cbd_anchor.py --graphml cache/chiang-khong-buffered.graphml --restarts 50 --independent-seeds 50 --output cache/cbd-warm-audit.json
```

The audit writes coordinates, score components, all sampled starts, trace,
convergence, certificate, exact evaluation count, boundary warnings, timings,
and distances between results. `--independent-seeds 50` executes the full search
50 additional times with different seeds and one random start each; these are
separate from the local outcomes of a single multi-start run. A warm GraphML
audit does not measure a fresh Overpass download.

For independent validation, supply `--ground-truth LAT LON` and/or
`--samples rent_samples.json` (a list of `lat`, `lon`, `rent` observations).
Without supplied evidence those fields remain null. R² compares log-rent fits
against the first sampled start; a positive difference is not a statistical
significance test. Independent survey/held-out observations are needed to make
that claim.

Tests cover exact agreement with NetworkX, minimum parallel-edge lengths,
deterministic ordering, 50 synthetic starts, monotone movement, 150 m stopping,
global certification, larger-graph disclosure, disconnected components,
shortest paths through the buffer, invalid input, resource limits, missing
SciPy, anchor precedence, rent without isochrones, config round trips, actual
Streamlit button execution/invalidation/failure, and the dark-blue map marker.
They also simulate connection refusal, retry/failover, cache reuse, custom
endpoint precedence, bounded all-server diagnostics, and global setting restore.

## Accuracy and limitations

- **150 m is a search radius**, not a demonstrated error bound against the
  economic CBD. Road connectivity and junction density are structural proxies.
- A buffer reduces truncation bias; it cannot eliminate it. Coverage, boundary
  position, graph size, disconnected roads, and OSM mapping practices still
  matter. Expand/shift the study region and compare anchors near the boundary.
- OSM roundabouts and divided carriageways can represent one physical junction
  with several nodes. Three distinct neighbours prevent parallel-edge degree
  inflation, but do not merge such physical intersections.
- A 50 m spread target is evaluated as maximum pairwise distance in metres,
  rather than calling a distance a variance. It is guaranteed by exhaustive
  certification only for an unchanged graph, candidate set, and objective.
- The 10-second target must distinguish cached compute from network download.
  Overpass latency is outside this algorithm's control. Large local-only
  searches have no global-optimum or cross-seed stability guarantee.
- Ground-truth CBD error and improved rent-fit significance have **not** been
  established from roads alone. These draft targets require independent data.

Implementation references: [OSMnx API](https://osmnx.readthedocs.io/en/stable/user-reference.html)
and [SciPy sparse graph algorithms](https://docs.scipy.org/doc/scipy/reference/sparse.csgraph.html).
OpenStreetMap road data are © [OpenStreetMap contributors](https://www.openstreetmap.org/copyright).

## Recorded real-road run (2026-09-20)

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
