# Plan: apply the 18-line flowchart to `pages/Rent_Gradient_V2.py`, then open a PR

## Context
The user asked: take the 18-line `pages/Rent_Gradient_flowchart.mmd` as a plan, apply it to
`Rent_Gradient_V2`, then open a PR, with the standing rule **no change in results**.

Finding from reading V2 (a copy of `Rent_Gradient.py` plus a Flowchart tab): the 8 flowchart nodes
already map 1:1 onto existing functions, so the code needs no re-architecture. The one place where the
code is more complex than the flowchart is node **INV** (invalidation): the same three layer lists are
repeated at 12 call sites, and "clear rent then recompute quietly" is written twice.

| Flowchart node | V2 code (line numbers in `Rent_Gradient_V2.py`) |
|---|---|
| ISO ① | `perform_calculation`, `calculate_intersection` |
| NET ③ | `perform_network_analysis`, `_compute_centrality_impl`, `compute_weighted_closeness`, `compute_golden_land_opportunities` |
| ANC | `perform_automated_anchor`, `find_cbd_anchors`, `anchor_study_polygon` |
| EVN | `run_evidence_stage`, `classify_anchor_confidence` |
| R1 ④ | `perform_rent_gradient`, `_rent_anchor_input`, `resolve_cbd_anchor`, `compute_rent_gradient_data`, `fit_rent_gradient_from_samples` |
| INV | `StateManager.clear_results` + 12 call sites: L4210, 4224, 4249, 4265, 4360, 4388, 5536, 6089 (markers); L4668, 4713 (anchors); L6016, 6035 (rent); reset/import call `clear_results()` (L562, L585) |
| ERR | early `return` + `st.error` in each `perform_*` |
| GOAL | `render_analytics_panel` tabs (Ring Report, Golden Spots, Markers) and the Flowchart tab |

## What "apply" will mean (recommended; changes V2 only, V1 untouched)
1. **Flow map in the V2 module docstring**: the node → function table above plus a pointer to the
   `.mmd`. Comments only.
2. **Centralize INV in `StateManager`**: add the layer tuples and three classmethods that call the
   existing `clear_results` with exactly the same lists:
   - `invalidate_markers()` → `["isochrone", "intersection", "rent"]` (8 call sites)
   - `invalidate_anchors()` → `["anchor", "anchor_closeness", "anchor_evidence"]` (2 call sites)
   - `invalidate_rent()` → `["rent"]` (2 call sites)
   `reset()` and `import_config()` keep calling `clear_results()` (clear everything).
3. **`_refresh_rent()`** helper = `invalidate_rent()` + `perform_rent_gradient(quiet=True)`, used in
   `perform_automated_anchor` (L6016-6017) and `_on_rent_anchor_toggle` (L6035-6036).
4. **Docs**: copy this plan to `docs/rent-gradient-v2-plan.md` (the plan under `/root/.claude/` is not
   reachable from the repo) and mark the code-application section as done.

Out of scope on purpose (could change behaviour): removing the rarely used "average of markers" tail
of `resolve_cbd_anchor`, the legacy `anchor_seed` / `anchor_restarts` config keys, UI text,
`Rent_Gradient.py`, any calculation function.

## Why this is safe, and how it is checked
- Each new method calls `clear_results` with the identical list, and each call site keeps its
  surrounding `st.rerun()` / toast / ordering. The marker-checkbox site (L4249) has no rerun and
  keeps none.
- **New test `tests/test_rent_gradient_v2.py`** (offline, same loader pattern as the other tests):
  1. for every calculation function (`fit_rent_gradient_from_samples`, `compute_rent_gradient_data`,
     `find_cbd_anchors`, `compute_golden_land_opportunities`, `run_evidence_stage`,
     `classify_anchor_confidence`, `resolve_cbd_anchor`, `calculate_intersection`,
     `build_ring_report`, `_compute_centrality_impl`), `inspect.getsource` is identical in V1 and V2;
  2. `invalidate_markers/anchors/rent` change exactly the same session keys as the old
     `clear_results([...])` lists (fake `st.session_state` dict);
  3. a source scan: no `clear_results([` call with a literal list remains outside `StateManager`.
- Run the 6 existing test files against V2 too (temporary copies under the scratchpad with the page
  path swapped; nothing committed) and compare pass/fail with the V1 run.
- `diff` V1 vs V2 must show only: docstring, title/header, flowchart helpers + tab, the new
  `StateManager` methods, `_refresh_rent`, and the replaced call sites.
- `AppTest` on both pages: no exception, V2 has 6 tabs. Facts check script: 44 facts, 0 missing.
- Not verifiable here: the calculation buttons end to end (needs a Geoapify key); say so in the PR.

## Pull request
`claude/confident-dijkstra-2wx52j` already has **open PR #30** (shorter flowchart). GitHub allows one
open PR per head/base pair, so a second PR from this branch is not possible. Recommended: merge #30
first (the user asked for the merge before, never revoked it), then merge `origin/main` into the
branch, commit this work, and open a **new PR** "Rent Gradient v2: apply flowchart (centralized
invalidation)". Do not merge that one until the user says so. The alternative is adding the commits to
#30 and retitling it.
PR body: summary, the node → function table, what is deliberately not changed, test results, and
what is not tested. Check for a PR template first (none was found earlier).

## Result (applied)
- `pages/Rent_Gradient_V2.py`: flow map in the module docstring, `StateManager.invalidate_markers /
  invalidate_anchors / invalidate_rent` replacing 12 literal-list call sites, `_refresh_rent()` replacing the
  two "clear rent then recompute quietly" pairs. `reset()` / `import_config()` unchanged.
- `tests/test_rent_gradient_v2.py` (24 tests): 17 calculation functions are source-identical in V1 and V2, the
  config constants are equal, each invalidation rule clears exactly the layers of the old call, no literal
  `clear_results([...])` is left at a call site.
- The 6 existing test files pointed at V2 (temporary copies, not committed): **168 passed / 3 skipped**, the same
  as against V1. Full suite on V1 including `test_design_page.py`: 223 passed / 3 skipped.
- `diff` V1 vs V2 shows only the docstring, title/header, flowchart helpers + tab, the new `StateManager` methods,
  `_refresh_rent` and the replaced call sites. `AppTest`: no exception on either page, V2 has 6 tabs.
- Not tested: the calculation buttons end to end (they need a Geoapify API key).
