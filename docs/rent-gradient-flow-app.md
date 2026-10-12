# Rent Gradient Flow — the plan as an app (`pages/Rent_Gradient_Flow.py`)

A new Streamlit page that takes the 18-line plan `pages/Rent_Gradient_flowchart.mmd` and makes it
executable **on top of** Rent Gradient v2. It is a thin shell: V2 is imported as the engine, so every
calculation, every sidebar widget and the whole map/analytics UI are V2's own.

> Reading of the request: "new app, built from this plan, extending Rent Gradient v2, with a tab
> *Rent Gradient v2*" → a new page whose first tab, **💹 Rent Gradient v2**, is V2 itself, plus a second
> tab, **🧭 Flow**, that turns the plan into a live board. If a different shape was meant (for example a
> copy of V2 instead of an import, or only a renamed tab), the shell is ~650 lines and cheap to rework.

## Layout

```
sidebar  = V2's sidebar, unchanged (markers, API key, ①, ③, Rent, Anchor, map layers)
─────────────────────────────────────────────────────────────────────────────────────
🧭 Rent Gradient Flow                        title
[ spinner / toast / error of any run ]       container above the tabs, visible from both tabs
[💹 Rent Gradient v2] [🧭 Flow]
   V2 header, metrics,                         GOAL · progress k/4 · next step
   map, analytics tabs                         one card per plan node + ▶ run button
   (unchanged)                                 live-coloured plan (Mermaid) · invalidation table (INV)
```

## Why import instead of copy

`pages/Rent_Gradient_V2.py` is loaded as a module (`rent_gradient_v2_engine` in `sys.modules`, loaded once
per process) and its pieces are called exactly as `V2.main()` calls them. Nothing is copied, so a fix in V2
reaches this page at once and the results cannot drift. `tests/test_rent_gradient_flow.py` enforces it: the
page may define no function or class with the same name as V2 (only `main`), and the run buttons must call the
same four orchestrators as `V2.main()`.

## Plan node → code → what you see

| Plan node | Engine function (V2) | Flow tab |
|---|---|---|
| ISO ① Isochrone | `perform_calculation` | card ① + ▶ |
| NET ③ Network | `perform_network_analysis` | card ③ + ▶ |
| ANC Anchor | `perform_automated_anchor` | card Anchor + ▶ |
| EVN Evidence | runs inside ANC when the toggle is on | card Evidence (read only) |
| R1 ④ Rent | `perform_rent_gradient` | card ④ + ▶ (+ ⚠️ when the table changed) |
| INV invalidation | `StateManager.invalidate_*`, `clear_results` | table (a)–(d), read from `StateManager` |
| ERR stop | guards inside each `perform_*` | reason on a ⛔ card, `st.warning` instead of a run |
| GOAL outputs | `render_analytics_panel` | card GOAL: what is produced, what is missing and why |

## How a node gets its status

`collect_facts(st.session_state)` → `FlowFacts` → `evaluate_flow()` → one `NodeStatus` per node
(`state` = does it have a result, `blocked` = does the plan's guard fail right now). All of it is pure
Python (no `st.*`), so it is tested offline. Guards are the plan's own words (facts table #):

| Node | Button disabled when (`blocked`) | `state` |
|---|---|---|
| ISO | no API key · no active marker · no time selected (#1) | ✅ isochrone present (CBD found or why not) |
| NET | no isochrone (#5) | ✅ network present; a network kept after rule (a) says so |
| ANC | no scipy/numpy · centre text not `Lat, Lon` (#12) | ✅ composite anchor present, otherwise ◻️ optional |
| EVN | — | 💤 off · ◻️ waits for ANC · ▶️ on but no result · ✅ HIGH/MEDIUM/LOW · 🟡 unavailable · ⚠️ old schema (#18–26) |
| R1 | neither isochrone nor composite anchor (#29) | ✅ FIT or INDEX; ⚠️ **stale** when re-fitting would change the model (#36) |
| GOAL | — | ✅ network ∧ FIT ∧ not stale · 🟡 partial · ◻️ nothing yet (#37–39) |

"Stale" asks V2 itself: `fit_rent_gradient_from_samples` on the current table, compared with the points the
stored model was fitted on. Editing the table only *syncs* (plan fact #36); the card now says a re-run is due.

## How a click runs

1. `on_click` stores the node in `st.session_state["_flow_pending_node"]`.
2. The rerun draws V2's sidebar, pops the node, and `run_flow_node` checks the plan's guard before calling the
   V2 orchestrator inside the container above the tabs.
3. The tabs are drawn **after** the run, so the cards, the buttons and the V2 tab already show the new
   state: no `st.rerun()`, and an error message is not wiped by one.

The Flow board is isolated (`_isolated`): if it ever fails to draw, the error is shown and V2 keeps working.

## Found while testing, fixed in V2: Mermaid in a hidden tab

In Chromium on Streamlit 1.65 the diagram in V2's own **Flowchart** tab showed *"Syntax error in text"*:
Mermaid measures text while drawing, and an iframe in a tab that is not open is 0 px wide. The shared
builder `Rent_Gradient_V2._flowchart_html` now draws once, when the frame gets a size (`ResizeObserver` /
`resize`), instead of `startOnLoad`. Both V2's Flowchart tab and the live plan in this page use it. It is not
one of the calculation functions that must match V1.

## Verification

- `tests/test_rent_gradient_flow.py`, 49 tests, all offline: reuse (shell, not copy), every guard against real
  V2 results (`compute_rent_gradient_data`, `find_cbd_anchors`), stale detection, live flowchart keeps every line
  of the plan, the INV table equals what `StateManager` clears, and the whole app end to end with `AppTest`
  (Geoapify and OSM replaced by synthetic data): ① → ③ → table edit → ⚠️ → ④ → FIT → GOAL, the anchor path,
  rule (a), the UI lock, the sidebar buttons, a failing board.
- 14 deliberate breakages (a guard, the runner map, run order, tab name, lock, INV list, a copied V2 function, …)
  were each caught by a test.
- Real browser (Chromium via Playwright, Streamlit 1.65): both tabs and the nav entry render; a map click adds a
  marker through the shell; ▶ ① calls V2 and its error appears above the tabs with the card unchanged; the live
  plan is coloured by status; V2's own Flowchart tab now renders.
- Real browser again, with Geoapify / OSM replaced by synthetic data (a scratch launcher, not committed): ▶ ① then ③
  turn the cards and the plan colours green in the same pass, ③ unlocks without a second click, ④ appears by
  itself after ①, and GOAL stays 🟡 until there is a FIT (Value Gap is hidden in index mode).
- **Not verified:** a real Geoapify / OSM run and map tiles (blocked from the sandbox; the offline `AppTest`
  covers the same code paths with stand-ins). Mermaid, Leaflet, jQuery, Bootstrap and awesome-markers were served
  from the same npm versions the CDNs would serve; the folium fullscreen / measure / mouse-position plugins were
  stubbed. After deploy, open **Rent Gradient Flow**, switch to **🧭 Flow** and check the plan renders.
