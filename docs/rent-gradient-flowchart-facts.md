# Rent_Gradient_flowchart.mmd — facts table (diagram vs code)

Each row is a fact read from `pages/Rent_Gradient.py`. ✓ = every needle string appears in the diagram text (checked mechanically).
This is a **coverage check, not a proof of equivalence**: it shows the diagram does not omit these facts, not that the wording is the only valid reading.
Out of scope (implementation heuristics, not shown): evidence cell/tile sizes, peak-cell share 0.40, zone min cells 4, hot-cell score/quantile, smoothing, tile and request budgets, Dijkstra batching, cache/bundle I/O, UI widgets, colours.

| # | Fact | Code ref | In diagram |
|---|---|---|---|
| 1 | ① guards: API key, ≥1 active marker, เลือกเวลา | L5738-5748 | ✓ |
| 2 | ไม่ได้ feature เลย → หยุด (ไม่ set iso / ไม่ refresh) | L5779-5780 | ✓ |
| 3 | CBD = ∩ ของ union ต่อ marker; ≥2 marker, ทุกจุดได้ polygon, ไม่ว่าง ไม่งั้น None | L2306-2330 | ✓ |
| 4 | Rent quiet หลัง ① เสมอ แม้ไม่มี CBD | L5807-5808 | ✓ |
| 5 | ③ ต้องมี isochrone | L4278, L5865 | ✓ |
| 6 | union polygon ทั้งหมด; nodes ≥2 | L5874, L3788 | ✓ |
| 7 | closeness บน LCC: exact n ≤3000 ไม่งั้น pivot k=600 | L141-142, L3751-3759 | ✓ |
| 8 | betweenness: exact nodes ≤2000 ไม่งั้น sample k=400 | L139-140, L3797-3814 | ✓ |
| 9 | Golden = .5C+.3deg/max+.2(1−bet) | L145-149, L2411-2416 | ✓ |
| 10 | NMS 150 m, top 10 | L143-144, L2430-2445 | ✓ |
| 11 | Rent quiet หลัง ③ เฉพาะมี rent อยู่แล้ว | L5905 | ✓ |
| 12 | Anchor: R 4–20 กม., buffer +20%, graph 2–100k | L4634, L155, L797 | ✓ |
| 13 | composite pool: junction deg≥3 ไม่มี=ทุกโหนด | L817-821 | ✓ |
| 14 | composite score .5Φ(C)+.3 rank(deg)+.2 rank(density 500 m) | L835-843, L965-966 | ✓ |
| 15 | closeness-100% = 1-median ทุกโหนด | L1137-1139 | ✓ |
| 16 | Rent ใช้เฉพาะ composite | L5937-5939, L5980 | ✓ |
| 17 | exact ถ้า pool พอดีงบ ไม่งั้น pivot-screen + refine | L1050-1090 | ✓ |
| 18 | Evidence: โซนแดง / fallback disc 1.5 กม. รอบ composite | L2120-2140, L1424 | ✓ |
| 19 | cluster ≥3 เซลล์ | L1431, L1859 | ✓ |
| 20 | cluster rank = mass/(1+(d/2000 m)²) | L1430, L1887 | ✓ |
| 21 | ไม่เจอ cluster → กลางโซนแดงถ้าอยู่ในวง ไม่งั้นไม่มี evidence anchor | L2198-2213 | ✓ |
| 22 | roads_ok = anchor ถนนที่ใกล้สุด ≤300 m | L1934-1936, L1439 | ✓ |
| 23 | parcel_ok = score ≥0.50 | L2223-2224, L1440 | ✓ |
| 24 | HIGH = coverage≥0.60 ∧ 3 สัญญาณ ∧ ไม่ unstable ∧ ไม่ชนขอบ | L1960, L1440 | ✓ |
| 25 | unstable = drift >15% ของรัศมี (stable ≤5%) | L1039-1040, L184-185, L1441 | ✓ |
| 26 | MEDIUM = coverage≥0.40 ∧ ตรง ≥2; อื่นๆ LOW | L1962-1965 | ✓ |
| 27 | publish พร้อมกัน → ล้าง rent → Rent quiet → rerun | L5969-5975 | ✓ |
| 28 | exception: ไม่ publish ไม่ rerun | L5972-5974 | ✓ |
| 29 | ④ guard: isochrone ∨ auto anchor | L5997 | ✓ |
| 30 | anchor priority 0-4 | L2576-2630 | ✓ |
| 31 | evidence anchor แทน composite เมื่อ toggle ∧ มีผล | L5978-5985 | ✓ |
| 32 | d_max: bbox ≥0.3 กม., ไม่มี=5; auto ∧ ไม่มี iso = R | L2633-2651, L3004-3006 | ✓ |
| 33 | FIT เมื่อ valid ≥2 ∧ ระยะต่างกัน | L2519-2532 | ✓ |
| 34 | FIT: OLS ln R=ln R0−λd, R², CI95, d_max≥ไกลสุด×1.05 | L2498-2573, L3020 | ✓ |
| 35 | INDEX: R0=100, λ=ln4/d_max | L3022-3023, L204-206 | ✓ |
| 36 | แก้ตารางตัวอย่าง = sync อย่างเดียว | L4400-4413 | ✓ |
| 37 | curve 80 จุด, 6 วงแหวน, Rent Heat ถ้ามี network | L204-214, L2719 | ✓ |
| 38 | Value Gap = Closeness − clamp(R/R0) เฉพาะ network ∧ FIT | L2933, L2954, L5366-5372 | ✓ |
| 39 | ผลลัพธ์: Ring Report, Golden table, Markers (R(d) ต่อหมุด) | L2848, L5345, L5499-5517 | ✓ |
| 40 | (a) คลิก/แก้หมุด/เพิ่ม top node,Golden → ล้าง iso,CBD,rent; debounce 0.5 s ≥10 m; network+anchor คงไว้ | L6029-6044, L2275-2299, L137-138, L4207-4262, L4356, L4384, L5493 | ✓ |
| 41 | (b) เปลี่ยน center/radius/travel mode; ล้าง Anchor → ล้าง anchors+rent | L4656-4666, L4709-4711 | ✓ |
| 42 | (c) รีเซ็ต / import config → ล้างทุกอย่าง | L555-583 | ✓ |
| 43 | (d) toggle Evidence-anchor → ล้าง rent → Rent quiet | L4569, L5988-5990 | ✓ |
| 44 | loop: เพิ่ม Golden เป็นหมุด | L4384, L5493 | ✓ |
