# Plan: Loop-optimize `pages/Rent_Gradient_flowchart.mmd` (audited v3)

## Context
The current `.mmd` (commit `a6e1571`) is a faithful but heavy map of `pages/Rent_Gradient.py`:
**347 lines, ~190 nodes, 16 subgraphs including nested ones**. v2 wrongly said "214 nodes, 12
subgraphs"; that figure was a count of lines containing brackets. The user wants the shortest
diagram that still leads straight to the app's top goal (find CBD → R(d)=R₀·e^(−λd) → undervalued
"golden land"), without changing the outcome. Every output, and every decision that changes an
output, must still be shown. The Python code is not touched.

## Audit v3: errors and gaps in v2, verified against the code
| # | v2 said | Code actually says | Ref |
|---|---|---|---|
| B1 | Closeness-100% anchor is display-only | It also feeds the evidence **roads_ok** check (nearest of composite or closeness ≤ agree_radius), which moves the confidence level | L2070-2071, L1934-1936 |
| B2 | Stability probe has no output effect | Composite stability "unstable" **blocks HIGH**. It never changes the anchor itself | L2228, L1956-1960, L1144 |
| B3 | ③ starts at "union" | Needs isochrone data (button disabled + guard). Unions **all** isochrone polygons, then requires nodes ≥2 | L4278, L5865, L5874, L3788 |
| B4 | Evidence: cluster "or zone centre" | Zone centre is used only when a red zone exists and its centre lies inside R. With the fallback disc and no cluster there is **no evidence anchor**. Cluster rank = mass/(1+(d/reach)²), not "densest" | L2198-2213, L1879-1888 |
| B5 | Confidence rule unstated | HIGH: coverage≥min ∧ roads ∧ zoning ∧ parcel ∧ ¬unstable ∧ ¬touches_boundary. MEDIUM: coverage≥medium ∧ ≥2 signals. Otherwise LOW | L1959-1965 |
| B6 | Anchor priority 4 (marker mean) / "else error" are normal paths | The Rent guard needs iso ∨ auto, and iso is stored only when non-empty. So these paths run only if no iso geometry parses (for example an imported empty FC). Keep them as **one tail node** | L5997, L5779-5785, L2623-2630 |
| B7 | Click clears "iso/CBD/rent" (A13 lost in v2) | Network and auto-anchor **survive**, so the next Rent still prefers the auto anchor | L536-552, L6043 |
| B8 | Rent has 3 auto triggers | A **4th**: the evidence toggle `on_change` → clear rent → Rent(quiet). Editing samples **only syncs**, so the model stays stale until a trigger | L4569, L5988-5990, L4400-4413 |
| B9 | Missing invalidation | Changing anchor context (centre, radius, travel mode) → clear all anchors **and rent** → rerun. Adding, removing or toggling markers → clear iso/CBD/rent | L4656-4666, L536-539, L4207-4262 |
| B10 | No loop back from the goal | "Add top node", "add Golden #1" and "add Golden #k" each add a marker → clear iso/CBD/rent → rerun. This is how the user acts on the goal | L4356, L4384, L5493 |
| B11 | Value Gap only needs fit mode | Needs **network ∧ fit mode**. Ring Report: mean closeness − R_mid/R₀. Golden table: closeness_norm − R(d)/R₀ (clamped 0..1) | L2933, L2954, L5361-5372 |
| B12 | Anchor input limits | UI radius is 4–20 km (function accepts 1–20). Graph must have 2–100k nodes, otherwise an error | L4634, L637, L797 |

## Audit v4: second pass over v3 (re-read L4671-4712, L5418-5517, L2905-2982, L5345-5374)
| # | v3 said | Code actually says | Ref |
|---|---|---|---|
| C1 | Outputs = Ring Report + Golden table | A third output: the **Markers tab** shows R(d) at every marker (distance from the anchor, predicted rent). Add it to the OUT node | L5499-5517 |
| C2 | Ring Value Gap = mean closeness − R_mid/R₀ | R_mid/R₀ is **clamped to 0..1** in both tables (the ring uses `rent_mid/r0`, the Golden table uses `est/r0`). Ring Value Gap is also only present inside the `has_net` block | L2938, L5366, L2933, L2954 |
| C3 | d_max "anchor-only = R" | Applies only when an auto anchor exists **and there is no isochrone**; with an isochrone present, the bbox rule is used even for an auto anchor | L3004-3006 |
| C4 | Anchor flow always ends in a rerun | On any exception: `st.error` + `return`. Nothing is published, rent is not cleared, **no rerun**. Route the failure into `ERR` | L5972-5974 |
| C5 | Closeness-100% "display only" for Rent | Confirmed by the UI text ("Rent Gradient ยังคงใช้ตัวที่ ①"), and it still feeds roads_ok in the evidence check [B1] | L4685 |
| C6 | Baseline "~190 nodes" | The counting script gives **198 nodes** (the earlier regex may over/under-count). Use the script's number as the baseline and re-run the same script every round | — |
| C7 | Evidence run when the checkbox is on | Pressing the button again re-runs everything on cached roads; a stored result without evidence while the checkbox is on is only a hint, so it does not matter for the flow | L4690 |

Feasibility check of the node budget: ISO ≈7, NET ≈8, ANCHOR ≈12, RENT ≈12, invalidation 2,
OUT 3, GOAL/MAIN 2 → ≈46. That is tight. **Fidelity beats the count**: if contract 1-8 does not
fit in 45 nodes, keep the extra nodes and report the real number.

The v2 rows A1-A4 and A6-A11 still hold. Detail kept only as a footnote: the Golden degree and
mean betweenness are taken on the directed MultiDiGraph G (L3885, L2376, L2390). Rent Heat covers
only nodes with closeness>0, i.e. the LCC (L3867).

## Fidelity contract (final, v3)
1. `main`: init → sidebar intents → ① → ③ → ④ → Anchor (in this order) → render → click.
2. ① guards (key, ≥1 marker, times) → Geoapify per marker → no feature ⇒ stop. Otherwise
   CBD = ∩ of the per-marker unions (≥2 markers, all returned, non-empty) → Rent(quiet).
3. ③ [needs iso] union all → OSM graph (cache → covering cache → Overpass), nodes≥2 →
   closeness on the LCC (exact ≤3000 / pivots) + edge betweenness (exact ≤2000 / k=400) → top
   node, Golden = .5C+.3deg+.2(1−bet̄), NMS 150 m, top 10 → Rent(quiet) only if rent exists.
4. Anchor [R 4–20 km]: circle+20% → OSM graph → composite (junctions, else all) & closeness-100%,
   exact if the pool fits the budget, otherwise screen + refine. Optional evidence: red zone
   (else disc) → cluster (else zone centre if red, else none) → HIGH/MED/LOW using roads(both
   anchors), zoning, parcel, coverage and stability [B1, B2, B4, B5]. Then clear rent →
   Rent(quiet) → rerun.
5. Rent anchor: composite auto (→ evidence if toggle ∧ schema ∧ anchor) > CBD centroid > top node >
   iso centroid > [tail: marker mean / error] [B6].
6. d_max (iso bbox ≥0.3 km, 5 km if none; auto anchor ∧ no iso = R [C3]; fit ⇒ ≥ farthest sample ×1.05) →
   fit (valid ≥2 ∧ Sxx>0) gives OLS R₀, λ, R², CI. Otherwise index R₀=100, λ=ln4/d_max. Then
   curve, 6 rings and Rent Heat (if network).
7. Invalidation: click / marker edit / add top node or Golden spot → clear iso, CBD, rent (keep
   network and anchor) → rerun. Anchor context change → clear anchors and rent → rerun.
   Evidence toggle → Rent(quiet) [B7-B10].
8. Output: Ring Report + Golden table + Markers tab (R(d) per marker) [C1], with Value Gap
   (clamped R/R₀ [C2]) only if network ∧ fit [B11] → GOAL → (add Golden as marker) loops back
   to ① [B10]. An anchor-search exception → `ERR`, no publish, no rerun [C4].

## Target shape (aim ≤ ~45 nodes, ≤ ~90 lines)
- `flowchart TD` first, then a 3-line `%%` goal header. A header placed before it failed to parse.
- Subgraphs: ①ISO, ③NET, ANCHOR, ④RENT. Contract 7 collapses into 2 "invalidate" nodes with
  several incoming edges.
- Chain sequential steps in one node with `<br/>`. Diamonds only for the branches in contract 1-8.
  Merge all error terminals into one `ERR`. Only 3 classDefs: goal, call, err.

## Loop (repeat until no node can be removed without breaking contract 1-8)
1. Rewrite or shrink `pages/Rent_Gradient_flowchart.mmd`.
2. Render in the session scratchpad directory (not `/tmp`):
   `npx -y @mermaid-js/mermaid-cli -p pp.json -i <file> -o out.png`, with `pp.json` set to
   `{"executablePath":"/opt/pw-browsers/chromium","args":["--no-sandbox"]}`. It must parse
   cleanly; view the PNG.
3. Tick contract 1-8, and **every** audit row (A1-A11 + B1-B12 + C1-C7), against the code refs.
4. Log line, node and subgraph counts with the same counting script each round. Try one more merge
   or removal, then go back to step 2.

## Audit v5 — "ผลลัพธ์ไม่เปลี่ยนแปลง จริงมั้ย?" (answer: partly; the claim was overstated)
"Unchanged" can mean three things. Checked each one against the code:

1. **App v1 vs v2 (code): true.** `diff` of `Rent_Gradient.py` vs `Rent_Gradient_V2.py` shows 7 hunks:
   docstring, `page_title`, header text, the flowchart helpers, the tab list, `with tab_flow`.
   None is in the calculation code. Not run end to end (needs a Geoapify key).
2. **Flowchart vs code (the merged 29-node version): mostly true, but 5 defects found**
   | # | In the diagram | Code says | Ref |
   |---|---|---|---|
   | D1 | "ถนน(ทั้ง 2 anchor)" | `roads_ok` = the **nearest** of the composite/closeness anchors is within `agree_radius_m` = **300 m** | L1934-1936, L1439 |
   | D2 | "composite นิ่ง" | Only **"unstable"** blocks HIGH (levels stable/check/unstable); two sources: road probe + evidence probe | L1956, L2228, L1039 |
   | D3 | composite ".3deg+.2dens" and Golden ".3deg" look the same | Composite uses **mid-rank percentiles** (and Φ for C); Golden uses degree/max_degree | L835-843, L2403 |
   | D4 | Invalidation rules list 3 groups | **Missing:** รีเซ็ต (clears everything + default marker), import config (clears all, then loads saved results), ล้าง Anchor (clears anchors + rent) | L555-583, L4709 |
   | D5 | Confidence rule is symbolic | **Numbers dropped:** parcel_ok 0.50, coverage_min 0.60, coverage_medium 0.40, cluster_min_cells 3, fallback disc 1.5 km | L1440, L1431, L1424 |
3. **The plan's own contract is self-written**, so "contract ticked" is not an independent proof.
   The round-2 keep-list inherits D1-D5. Fix: build a **facts table** (every constant, branch and
   rule read from the code, with a line ref) and check each fact appears in the diagram text
   or on an edge. Anything missing is a defect.

What I can honestly claim after the fix: *no outcome-changing branch or number from the facts
table is missing from the diagram*. I cannot claim a proof of equivalence, and the node counts
come from a regex script, so they are approximate.

## Round 2 — "อีกได้มั้ย" (can it go shorter?): YES, 29 → ~11 nodes, 82 → ~40 lines
Order of work: (1) fix D1-D5 in the current diagram and build the facts table, (2) only then
shorten. The shorter diagram may end slightly above 11 nodes or have longer boxes because of D4/D5.
Baseline (merged in #28/#29): **82 lines, 29 nodes, 4 subgraphs, 5,323 chars**.
Rule: a node or edge may go only if its outcome-changing content survives as text or an edge
label. Contract 1-8 and rows A/B/C stay the checklist.

| Cut | Why the outcome is unchanged |
|---|---|
| Drop `UI` node and the `-.-> UI` loop edges | Each rerun comes from one button, so the ①→③→④→Anchor order never changes a result. Keep the four triggers as the subgraph/node prefixes ①③④ |
| Fold guards into node text + dashed edge to `ERR` (I1, I3, N1, R0 diamonds) | Same stop conditions, shown as `[ต้อง …]` plus an `ERR` edge |
| Merge I1-I4 → 1 node, N1-N5 → 1 node | Steps are sequential with no output-changing branch between them |
| `N5` "มี rent อยู่แล้ว?" → label on the edge NET → Rent | Same condition, no node |
| Merge A1+A2, A4+A5; drop `A6` (publish → clear rent → rerun becomes an edge label) | Same sequence |
| Keep diamond `EV` (Evidence on/off) and `FIT` (valid samples ≥2) | The only two branches that change which outputs exist (evidence anchor; FIT vs INDEX and Value Gap visibility) |
| Merge R1+R2; R4/R5 become the two edge labels out of `FIT` | Same formulas, fewer boxes |
| Merge INV1+INV2+TOG → 1 `INV` node (a/b/c lines) | Same three invalidation rules and their triggers |
| Merge `OUT` into `GOAL` | The outputs stay listed in the goal node |
| Drop cache → covering cache → Overpass detail, the `act` classDef and the duplicated `%%` header | Same graph/data; styling only |
| **Keep** (outcome-changing numbers; D1-D5 added) | roads agree ≤300 m (nearest anchor), only "unstable" blocks HIGH, parcel_ok 0.50 / coverage 0.60 / 0.40 / min cells 3 / fallback disc 1.5 km, composite = percentile ranks, INV also lists รีเซ็ต / import / ล้าง Anchor, exact ≤3000 / pivot 600, betweenness exact ≤2000 / k=400, Golden weights + NMS 150 m + top 10, R 4–20 km +20%, graph 2–100k, composite vs closeness-100%, exact vs pivot-screen, evidence rank + HIGH/MED/LOW rule, anchor priority, d_max rule, OLS vs INDEX, clamp(R/R₀), debounce 0.5 s / ≥10 m, "แก้ตาราง ≠ fit ใหม่" |

Target skeleton (0 subgraphs, ~11 nodes): `GOAL`, `ERR`, `ISO`, `NET`, `ANC`, `EV`, `EVN`,
`R1`, `FIT`, `R6`, `INV`. Edges: ISO → R1; NET -.->|ถ้ามี rent| R1; ANC → EV; EV -->|ใช่| EVN → R1;
EV -->|ไม่| R1; R1 → FIT; FIT → R6 (two labelled edges); R6 → GOAL; NET → GOAL; GOAL -.-> INV;
INV -.->|toggle Evidence| R1; dashed guard/exception edges ISO/NET/ANC/R1 → ERR.

Stop rule: if a further merge would hide an outcome-changing branch from the text and the edges,
keep the node. If ~11 nodes would make a box unreadable, split that box and report the real count.
Trade-off to state in the PR: fewer diamonds means more reading inside each box.

Related edit: `pages/Rent_Gradient_V2.py` has `_FLOWCHART_HEIGHT_PX = 2300`, sized for the old
tall diagram. After the new render, measure the SVG height and lower that constant (V2 only reads
the `.mmd`; no other code changes). `Rent_Gradient.py` stays untouched.

## Pull request ("Rent Gradient v2") — requested by the user
Interpretation (the user's message: plan file + "pr ไปที่ tap ใหม่ Rent Gradient v2"): open a
**new PR** titled **Rent Gradient v2** from the designated branch `claude/confident-dijkstra-2wx52j`
into `main`. It contains the optimized `pages/Rent_Gradient_flowchart.mmd` and this plan saved as
`docs/rent-gradient-flowchart-plan.md` (the plan file under `/root/.claude/` is not reachable from
the repo). No changes to `Rent_Gradient.py`.
- Check for a PR template first (`.github/pull_request_template.md` etc.) and mirror it.
- PR body: goal, before → after counts, the audit checklist result (A/B/C rows), and the
  attribution line the session requires.
- After creating it, ask whether to subscribe to PR activity.

## Round 2 delivery
- #28 and #29 are merged, so this is a **new PR**: merge `origin/main` into
  `claude/confident-dijkstra-2wx52j` (non-destructive; a branch reset was denied earlier), commit
  the changes, push, open a PR titled "Rent Gradient v2: shorter flowchart". Do not merge it
  until the user says so.
- Changes: `pages/Rent_Gradient_flowchart.mmd`, the `_FLOWCHART_HEIGHT_PX` constant in
  `pages/Rent_Gradient_V2.py`, and the "Result" section of `docs/rent-gradient-flowchart-plan.md`
  (Round 2: counts before → after).
- Verify: mermaid-cli render with the scratchpad `pp.json`, view the PNG, run the same node-count
  script as before (baseline 82 / 29 / 4), re-tick A/B/C, `AppTest` on `Rent_Gradient_V2.py`
  (no exception, 6 tabs), and one browser screenshot of the Flowchart tab (local Mermaid via
  route, since the sandbox cannot reach the CDN).

## Deliverable and verification
- Replace `pages/Rent_Gradient_flowchart.mmd` in place.
- Commit and push to `claude/confident-dijkstra-2wx52j`.
- Report the counts before (346 lines per `wc -l` / 198 nodes per the counting script / 16
  subgraphs) and after, using the same script. Confirm a clean
  render and that the full checklist passes.

## Result
| | Lines | Nodes | Subgraphs | Chars |
|---|---|---|---|---|
| Original (a6e1571) | 346 | 198 | 16 | – |
| Round 1 (#28) | 82 | 29 | 4 | 5,323 |
| Round 2 | **45** | **11** | **0** | ~5,100 |

- Round 2 also fixes audit defects D1-D5 (the nearest road anchor ≤300 m, only "unstable" blocks HIGH,
  percentile ranks for the composite score, the missing reset / import / clear-anchor invalidation, and the
  dropped evidence numbers). The text per box is longer, so the saving is in nodes and edges, not characters.
- `docs/rent-gradient-flowchart-facts.md`: 44 facts read from the code, each checked mechanically against
  the diagram text (87 strings, none missing). This is a coverage check, not a proof of equivalence.
- Node counts come from a regex script and are approximate. `Rent_Gradient.py` is unchanged.
