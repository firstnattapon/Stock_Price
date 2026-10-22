# Rent_Gradient_new_v2 — ชั้นแผนที่ (Layers)

`pages/Rent_Gradient_new_v2.py` คือหน้าเดียวที่รวม **ทุกฟังก์ชันของ `pages/Rent_Gradient.py`**
(Isochrone / CBD zone / Rent Gradient · Network Analysis · Automated CBD Anchor + Evidence ·
WMS / KML / traffic / config / cache) เข้ากับ **Space Syntax ของ `pages/Rent_Gradient_new.py`**
โดยทุกอย่างที่อยู่บนแผนที่เป็น "ชั้น" (layer) ของแผนที่เดียว

- ไฟล์เดิมทั้งสอง (`Rent_Gradient.py`, `Rent_Gradient_new.py`) **ไม่ถูกแก้** — v2 คัดลอกฟังก์ชันเข้าไฟล์เดียว ไม่ import ข้ามหน้า
- เป้าหมายของการจัดโครงสร้างใหม่: **เรียบง่าย · เสถียร · เร็ว** โดย **ตัวเลขผลคำนวณต้องเท่าเดิมทุกตัว**
- ผู้ใช้เห็นอะไรเปลี่ยนไป → ดู §6 · วัดผลได้เท่าไร → §7 · อะไรที่ยังไม่ได้ตรวจ → §9

## 1) โครงสร้าง: เปลี่ยนเฉพาะ "เปลือก" ไม่แตะ "แกนคำนวณ"

```
 ENGINE  (ฟังก์ชันล้วน ไม่เรียก st.*  ·  คัดลอกตรงตัว  ·  ล็อกด้วยเทสต์)
         Reach/Rent · Anchor/Evidence · OSM cache+fetch · Network · Space Syntax
            ▲  เรียกผ่าน StateManager + stage เท่านั้น (layer ไม่แตะ session_state)
 STAGES  calc · network · rent · anchor · space_syntax
         ปุ่ม Run → ตรวจ input → คำนวณ (cached) → เก็บผลใน session → แจ้ง error ที่จุดเดียว
            ▼  build_ctx()  =  snapshot อ่านอย่างเดียวของ session (ครั้งเดียวต่อรอบ)
 LAYERS  19 แถว  Layer(id, title, group, draw, available, show_key, legend, options, …)
            ▼  render_layers(ctx)  วาดทีละชั้น (ล่าง → บน) · error แยกชั้น · แล้ว add_to(map)
         แผนที่เดียว (canvas) + legend กล่องเดียว + จำมุมมองฝั่งเบราว์เซอร์
 VIEWS   6 มุมมองใต้แผนที่ (radio) — รันเฉพาะมุมมองที่เลือก
```

| โซน | ใน `Rent_Gradient_new_v2.py` | กติกา |
|---|---|---|
| **ENGINE** | SECTION 3 (คำนวณหลัก) · 3b (Space Syntax) · ฟังก์ชัน OSM/anchor/rent ที่ไม่เรียก `st.*` | คัดลอกตรงตัว — **ไม่ต้องอ่าน/แก้** ถ้าไม่ได้เปลี่ยนวิธีคำนวณ (ledger test กันไม่ให้ซอร์สเพี้ยน) |
| **SHELL** | SECTION 1–2 ค่าคงที่ + `StateManager` · 4 cached wrappers · 5 UI (`LAYERS` → แผงควบคุม → `VIEWS`) · 6 stages · 7 `main()` | ส่วนเดียวที่ต้องอ่านเมื่อแก้หน้าจอ — `main()` ยาว 30 บรรทัด |
| **TESTS** | `tests/test_rent_gradient_new_v2.py` | ledger + เทสต์ layer/stage/state + AppTest ทุก flow |

`main()` ทั้งหมด:

```python
intents = render_sidebar(); run_stages(intents)           # sidebar → ปุ่มที่กด → คำนวณ
with intents["ss_status"]: _ss_status(intents["ss_params"])
ctx = build_ctx()                                          # snapshot อ่านอย่างเดียว
with st.sidebar: _render_sidebar_layers_panel(ctx, intents["locked"])
render_header(); render_metrics_row(); render_map(ctx); render_views(ctx)   # แผนที่แสดงอย่างเดียว ไม่ส่งอะไรกลับ
```

## 2) ชั้นแผนที่ (ล่าง → บน — ลำดับ vector เท่ากับ `render_map` เดิม)

| # | id | ชื่อใน LayerControl | กลุ่มในแผงชั้น | ต้องมีข้อมูล | checkbox (`show_*`) · ค่าเริ่มต้น |
|---|---|---|---|---|---|
| 1 | `traffic` | Google Traffic | บริบท & overlay | – | `show_traffic` · ปิด |
| 2 | `wms_population` | ความหนาแน่นประชากร | บริบท & overlay | – | `show_population` · ปิด |
| 3 | `wms_cityplan` | ผังเมืองรวม | บริบท & overlay | – | `show_cityplan` · ปิด (+ ตัวเลือกความโปร่งใส) |
| 4 | `wms_dol` | รูปแปลงที่ดิน | บริบท & overlay | – | `show_dol` · ปิด (+ ตัวเลือกความโปร่งใส `dol_opacity` ค่าเริ่มต้น 0.2) |
| 5 | `anchor_boundary` | Automated Anchor study boundary | Automated Anchor | anchor | `show_anchor_boundary` · ปิด (ใหม่) |
| 6 | `evidence_zone` | Peak colour zone (ผังสีสูงสุด) | Automated Anchor | evidence | `show_evidence_zone` · ปิด (ใหม่) |
| 7 | `evidence_clusters` | Parcel clusters (แปลงถี่) | Automated Anchor | evidence | `show_evidence_clusters` · ปิด (ใหม่) |
| 8 | `rent_rings` | Rent Gradient Rings | Rent Gradient | rent | `show_rent_rings` · เปิด |
| 9 | `rent_heat` | Rent Heat (Nodes) | Rent Gradient | rent + network | `show_rent_nodes` · ปิด |
| 10 | `betweenness` | Road Betweenness | โครงข่ายถนน | network | `show_betweenness` · ปิด |
| 11 | `closeness` | Node Integration | โครงข่ายถนน | network | `show_closeness` · ปิด (วาดสีเทา `NODE_FILL` / `NODE_STROKE` และครึ่งขนาดของเอนจิน `NODE_RADIUS_SCALE` = 0.5 → 1–4 px) |
| 12 | `golden` | Golden Land Spots | โครงข่ายถนน | network | `show_golden_spots` · เปิด |
| 13 | `travel_areas` | Travel Areas | โครงข่ายถนน | isochrone | แสดงเสมอเมื่อมีข้อมูล (ขอบสีขาว) |
| 14 | `cbd_zone` | CBD Zone | โครงข่ายถนน | CBD (∩) | แสดงเสมอเมื่อมีข้อมูล |
| 15 | **`space_syntax`** | 🧭 Space Syntax (ไล่สีตามคะแนน) | โครงข่ายถนน | ผล Space Syntax | `show_space_syntax` · เปิด (ใหม่) |
| 16 | `railway` | แนวรถไฟเชียงของ | บริบท & overlay | KML | `show_railway` · ปิด (+ ตัวเลือกความโปร่งใส `railway_opacity` ค่าเริ่มต้น 0.2) |
| 17 | `top_node` | Integration Center | โครงข่ายถนน | network | แสดงเสมอเมื่อมีข้อมูล |
| 18 | `cbd_anchor` | CBD Anchor (Composite / Closeness / Evidence / Rent) | Automated Anchor | anchor / rent | แสดงเสมอเมื่อมีข้อมูล |
| 19 | `markers` | หมุดของฉัน | บริบท & overlay | หมุด | แสดงเสมอเมื่อมีหมุด |

- ชั้น 5–7 (รายละเอียดของ anchor) เดิมวาดด้วย `show=False` โดยไม่มี checkbox → ตอนนี้มี checkbox (ค่าเริ่มต้น = ปิด เหมือนเดิม) และยังอยู่ใน LayerControl ของแผนที่ (`start_hidden`)
- ชั้นที่ปิดอยู่หรือไม่มีข้อมูลจะ **ไม่ถูกสร้าง** เลย
- ชั้น Space Syntax: ไล่สีทุกช่วงถนนแดง (เข้าถึงง่าย) → น้ำเงิน (เข้าถึงยาก) · วงขอบเขตพื้นที่ศึกษา · จุดคะแนนสูงสุด top-N · ตัวเลือกการแสดงผล (ตัวชี้วัด Integration/Choice, รัศมี, ชุดสี, สเกล, เส้นหนา, top-N) อยู่ใต้ checkbox และ **เปลี่ยนแล้วไม่คำนวณใหม่**

## 3) มุมมองใต้แผนที่ (`VIEWS`, radio แทน `st.tabs`)

📈 Bid-Rent Curve · 🧾 Ring Report · 💎 Golden Spots · 📍 หมุด & ราคาประเมิน · **🧭 Space Syntax** (Segment map PNG / สถิติ & อันดับ / หลักการ) · 📐 หลักการ

เนื้อหา 5 มุมมองเดิมถูกย้ายมาตรง ๆ (เทสต์เทียบ AST กับ tab เดิม) — `st.tabs` รันเนื้อหา **ทุกแท็บทุก rerun** แต่ radio รันเฉพาะที่เลือก PNG/histogram ของ Space Syntax สร้างเมื่อกดขอเท่านั้นและ cache ไว้

## 4) เพิ่มชั้น / มุมมองใหม่

**ชั้นแผนที่ = 1 ฟังก์ชัน + 1 แถว (+ 1 ค่าเริ่มต้นถ้ามี checkbox)** — เทสต์ `test_a_new_layer_is_one_function_and_one_row` พิสูจน์ไว้

```python
def draw_station(ctx: Ctx):                       # 1) สร้างให้เสร็จแล้วคืนค่า (อย่า add_to(map) เอง)
    group = folium.FeatureGroup(name="สถานีรถ", show=True)
    for lat, lon, name in STATIONS:
        folium.CircleMarker([lat, lon], radius=6, tooltip=escape(name)).add_to(group)   # ข้อความจากภายนอกผ่าน escape
    return group

LAYERS = (...,
    Layer("station", "สถานีรถ", "บริบท & overlay", draw_station, _always,
          show_key="show_station", label="🚌 สถานีรถ"),                                 # 2) แถวใน LAYERS (ตำแหน่ง = ลำดับซ้อน)
    ...)
# 3) "show_station": False ใน StateManager._DEFAULTS และใน SESSION_KEYS_TO_SAVE (ถ้าอยากให้บันทึกใน config)
```

ถ้ามี legend ให้ใส่ `legend=fn(ctx) -> html` (+ `legend_rank`) · ถ้ามีตัวเลือกเพิ่มให้ใส่ `options=fn(ctx, locked)` ·
ชั้นที่พังจะแสดงเป็น warning ใต้แผนที่ ชั้นอื่นยังขึ้นตามปกติ (`render_layers` จับ error ทีละชั้น)

**มุมมองใหม่ = 1 ฟังก์ชัน `view_x(ctx)` + 1 แถวใน `VIEWS`**

## 5) Space Syntax ในหน้านี้

- ปุ่มเดียว **🧮 วิเคราะห์ Space Syntax** (โหลดโครงข่าย + คำนวณ) และ **🧪 ตัวอย่างเชียงของ (ออฟไลน์)** ที่อ่านกราฟจาก `Geoapify_Map/osmnx_cache.zip` (ไม่ต้องต่อ Overpass)
- **พื้นที่ศึกษา = วงเดียวกับการค้นหา CBD Anchor** (`anchor_study_polygon` + `_fetch_osm_graph` เดิม: disk cache + Overpass failover) ศูนย์กลางใช้ `anchor_lat/lon` ร่วมกัน แก้ที่แผง Automated CBD Anchor ที่เดียว; รัศมีแสดงผล 1,000–10,000 ม. เป็นของ Space Syntax เอง (คำนวณบนโครงข่ายกว้างกว่า 20 % แล้วแสดง/จัดอันดับเฉพาะในรัศมี เพื่อลด edge effect)
- เปลี่ยนแค่พารามิเตอร์ (ระยะ angular/topological/metric, มุมเลี้ยว, รัศมีวิเคราะห์, Choice) → ไม่โหลดโครงข่ายซ้ำ · เปลี่ยนศูนย์/รัศมี/ชนิดโครงข่าย → โหลดใหม่
- ตั้งค่าเปลี่ยนไปจากที่คำนวณไว้ → แสดงข้อความ "กดวิเคราะห์เพื่ออัปเดตผล" (ไม่ปล่อยให้ผลเก่าดูเหมือนเป็นผลปัจจุบัน)
- **ผลคำนวณอยู่ใน session ไม่ลง config JSON** (คำนวณใหม่เร็ว); **ค่าตั้ง** (`ss_*`, `show_space_syntax`) ลง config · `reset` / `import_config` / `clear_results("space_syntax")` ล้างผลเก่า
- คีย์ session ใช้ prefix `ss_` จึงไม่ชนกับ `rgn_*` ของหน้า `Rent_Gradient_new.py`
- ตัวเลขเท่ากับหน้า `Rent_Gradient_new.py` (เทสต์ `test_the_engine_gives_exactly_the_numbers_of_the_standalone_space_syntax_page`)

## 6) ต่างจาก `Rent_Gradient.py` อย่างไร

### ปัญหาที่พบในโครงสร้างเดิม → กลไกใน v2

| # | ปัญหา (ยืนยันจากโค้ด) | เสา | กลไกใน v2 |
|---|---|---|---|
| 1 | `render_map` 350 บรรทัดต่อกัน — layer เดียวพังทำให้แผนที่พังทั้งหน้า | เรียบง่าย · เสถียร | `LAYERS` 1 แถว/ชั้น · `render_layers` จับ error ทีละชั้น → warning ใต้แผนที่ |
| 2 | toggle กระจาย 3 แผง + 3 ชั้นซ่อนโดยไม่มี toggle | เรียบง่าย | แผง **🗺️ ชั้นแผนที่ (Layers)** แผงเดียวสร้างจาก `LAYERS` (คีย์ `show_*` เดิม) |
| 3 | `st_folium` ใช้แฮชสคริปต์ Leaflet เป็น key → เนื้อหาเปลี่ยนก็ re-mount แผนที่ ซูม/ตำแหน่งที่เลื่อนไว้เด้งกลับ · renderer SVG (ช้าเมื่อเส้นเป็นหมื่น) · GeoJSON เก็บพิกัด 7 ทศนิยม | เร็ว | `prefer_canvas=True` · เส้น/จุดเป็น JSON แบบกะทัดรัด (`CompactLines/CompactPoints`) พิกัด 5 ทศนิยม (~1 ม.) **เฉพาะตอนวาด** (ผลที่เก็บไม่เปลี่ยน) · cache ต่อ session (LRU, ใช้ซ้ำเฉพาะกับอ็อบเจ็กต์ผลตัวเดิม) · `ViewMemory` จำ center/zoom ใน `sessionStorage` |
| 4 | `st.tabs` รันทุกแท็บทุก rerun | เร็ว | view router (radio) รันเฉพาะที่เลือก |
| 5 | เปิดหน้าแรกของทุก session เรียก `requests.get(JSON_URL, timeout=3)` | เร็ว · เสถียร | `st.cache_data(ttl=600, max_entries=1)` — ครั้งเดียวต่อโปรเซส (ถ้า GitHub เข้าไม่ได้ก็ไม่ถูกเรียกซ้ำโดยทุก session) |
| 6 | `_OVERPASS_LOCK = RLock()` ระดับ module แต่ Streamlit รัน page script ใน module `__main__` ใหม่ทุก rerun → ล็อกไม่ได้กันดาวน์โหลดชนกันข้าม session | เสถียร | ถือล็อกใน `st.cache_resource` (หนึ่งอัน/โปรเซส) |
| 7 | `st.cache_data` 4 ตัวไม่มี `max_entries` (ผล Network 0.4–5 MB/รายการ) | เสถียร | ใส่ `max_entries` ทุกตัว (เทสต์บังคับ) |
| 8 | `import_config` ไม่ตรวจชนิด/ช่วงค่า — ค่าผิดชนิดทำ widget พังทั้งหน้า | เสถียร | ตรวจตาม `_DEFAULTS` ข้ามค่าที่ผิดและแจ้งชื่อคีย์ที่ถูกข้าม |
| 9 | legend 2 ชุดตำแหน่งชนกันเมื่อเปิดทั้งคู่ | เรียบง่าย | `legend_stack` — กล่องเดียว สแตกหัวข้อของชั้นที่เปิดอยู่ |

### สิ่งที่ผู้ใช้เห็นต่างไป

1. **ชั้นแผนที่ทั้งหมดอยู่แผงเดียว** "🗺️ ชั้นแผนที่ (Layers)" จัดเป็น 4 กลุ่ม · sidebar เรียงตาม pipeline: จุดเริ่ม + Isochrone → Network → Automated CBD Anchor → Space Syntax → Rent Gradient → ชั้นแผนที่
2. **สลับชั้นแล้วซูม/ตำแหน่งที่เลื่อนไว้ไม่เด้งกลับ** (แผนที่ยังถูกสร้างใหม่ แต่กู้มุมมองให้) · เพิ่มหมุด/พบ anchor ใหม่ → ยัง re-center เหมือนเดิม · ถ้าเบราว์เซอร์บล็อก `sessionStorage` → กลับไปพฤติกรรมเดิมโดยไม่พัง (ปิดฟีเจอร์ทั้งหมดได้ด้วย `REMEMBER_VIEW = False`)
3. legend เป็นกล่องเดียวมุมล่างซ้าย
4. ใต้แผนที่เป็นตัวเลือก (radio) แทนแท็บ + เพิ่มมุมมอง 🧭 Space Syntax
5. พื้นหลังแผนที่เพิ่ม "พื้นดำ (เหมือน depthmap)" และ "Dark (Esri Dark Gray)" (พื้นมืด + ป้ายชื่อ) — แนะนำสำหรับไล่สีแดง→น้ำเงิน · เดิมเป็น "Dark (CARTO)" แต่ CARTO บังคับ API key แล้ว (ไทล์ที่ไม่มี key มีลายน้ำ "API KEY REQUIRED") — session/config เก่าที่เลือกไว้จะเปิดเป็น Dark ใหม่เอง (`LEGACY_MAP_STYLES`) · สไตล์อื่นที่เพิ่ม (ไม่ต้องใช้ key ทั้งหมด): Google Maps ถนน / ภูมิประเทศ / ดาวเทียมล้วน, Esri Street Map, Esri Topographic · Esri Canvas (Light/Dark Gray) มีไทล์ถึงซูม 16 จึงตั้ง `max_native_zoom` ให้ Leaflet ขยายไทล์แทนภาพ "Map data not yet available"
6. config JSON รูปแบบเดิม (ไฟล์เก่าโหลดได้) + คีย์ใหม่ของ Space Syntax / ชั้น anchor
7. **Active Markers เพิ่มได้จากการกรอกพิกัดที่ ⚙️ การตั้งค่า เท่านั้น — คลิกแผนที่ไม่เพิ่มหมุดอีกแล้ว**
   - แผนที่เรียก `st_folium(..., returned_objects=[])` → ไม่ส่งอะไรกลับ: คลิก/เลื่อน/ซูมไม่ทำให้หน้า rerun และไม่ล้างผล Isochrone / CBD / Rent ที่คำนวณไว้ (เดิมคลิกพลาดครั้งเดียวก็เพิ่มหมุดและล้างผลทั้งสามอย่าง) · โค้ด `handle_map_click` / `should_add_marker` / debounce ถูกลบ (ledger: แทน 2 ตัว)
   - ช่องกรอกที่ sidebar ตรวจรูปแบบและช่วงพิกัดด้วยตัวเดียวกับช่องศูนย์พื้นที่ศึกษา (Lat ±85 · Lon ±180) แล้วบอกเหตุผลเป็นภาษาไทย — ค่าที่ผิดไม่เพิ่มหมุดและไม่ล้างผลที่มีอยู่ · คำแนะนำเหนือช่อง: อ่านพิกัดเมาส์ได้ที่มุมขวาล่างของแผนที่
   - ปุ่ม ➕ ที่เพิ่ม "จุดที่ได้จากการวิเคราะห์" ยังอยู่ตามเดิม (Integration Center และ Golden Spot อันดับ 1 ใน sidebar · ปุ่มยืนยันเพิ่มหมุดใน view 💎 Golden Spots) — เป็นคำสั่งที่กดเอง ไม่ใช่การคลิกแผนที่ (เทสต์ `test_the_map_cannot_add_a_pin…` ล็อกรายการฟังก์ชันที่เพิ่มหมุดได้)
   - แก้บั๊กเดิมของรายการหมุดที่เจอระหว่างตรวจ (มีใน `Rent_Gradient.py` ด้วย): ลบหมุดกลางรายการทำให้ติ๊ก เปิด/ปิด ของหมุดที่เหลือสลับกัน (checkbox ผูก key ตามลำดับ) และตัวเลข "Active Markers: N" ใน sidebar ช้ากว่าความจริงหนึ่งรอบหลังติ๊ก
8. **สี UI อ่านสบายตาทั้งพื้นขาวและพื้นดำ** (ตามโหมดของ Streamlit / ระบบ — ดูรายละเอียดใน §6b)

### 6b) สี UI: เรียบง่าย สบายตา ทั้งพื้นขาวและพื้นดำ

หลักคิด: หน้าเว็บของ Streamlit ตามธีมที่ผู้ใช้เลือกอยู่แล้ว — สีที่เขียนฝังเองถูกเปลี่ยนให้ "ไม่ต้องรู้ว่าธีมไหน" (ผสมจาก `currentColor`) หรือพกสองชุดให้เบราว์เซอร์เลือก · **สีของข้อมูลบนแผนที่ไม่ถูกแตะ** (Rent ramp, Betweenness, Space Syntax, Travel Areas, สีจาก WMS) เพราะเป็นสีที่สื่อความหมาย

| ส่วน | เดิม | ตอนนี้ |
|---|---|---|
| view 📐 หลักการ | การ์ดน้ำเงินเข้ม `#101c27` + ตัวหนังสือขาว/เขียวมิ้นต์ `#53d6a2` ตายตัว — หัวข้อ "Flow …" และกล่อง "หมายเหตุเรื่องราคา" เป็นตัวสีอ่อนบนพื้นขาว **อ่านไม่ออกในโหมดสว่าง** | การ์ดเทาโปร่ง (`color-mix` จาก `currentColor`) ตัวหนังสือใช้สีของหน้า มีสีเน้นเดียว (teal `#1f7a70`) ที่ขอบและป้ายเลขขั้น · ข้อความเท่าเดิมทุกตัวอักษร (เทสต์เทียบ AST หลังตัดบล็อก `<style>`) |
| รายการหมุดใน sidebar | ใช้ชื่อสี CSS (`black`, `pink`, `gray` …) — `black` หายบนพื้นดำ, `pink` จางบนพื้นขาว | ตัวหนังสือใช้สีธีม · มีเฉพาะ "จุดสี" ของหมุด (hex เดียวกับหมุดบนแผนที่) ล้อมวงเทากลาง ๆ ทุกสีจึงเห็นได้ทั้งสองพื้น · หมุดที่ปิดอยู่: จาง + ขีดฆ่า + จุดโปร่ง |
| legend · ปุ่ม zoom / เต็มจอ / วัดระยะ · layer control · scale · attribution · พิกัดเมาส์ · popup · tooltip | ขาวตายตัว | `MAP_CHROME_CSS`: ชุดสีขาวและชุดสีดำ เลือกด้วย `prefers-color-scheme` (แผนที่อยู่ใน iframe จึงมองไม่เห็นธีมของ Streamlit) · เทา-ขาวนุ่ม ไม่ใช้ขาว/ดำสนิท · ไอคอนกลับสีในโหมดมืด · ตัวหนังสือ/ข้อความรอง/ลิงก์ผ่าน contrast ≥ 4.5:1 ทั้งสองชุด (เทสต์คำนวณให้) |

selector ของ `MAP_CHROME_CSS` ขึ้นต้นด้วย `html .leaflet-container` เพื่อชนะ CSS ของ Leaflet/ปลั๊กอินที่ folium วางไว้หลังบล็อกนี้ · เพิ่มสีใหม่ = เพิ่มตัวแปร `--rg-*` ในทั้งสองชุด (เทสต์เช็คว่าทุก `var()` มีนิยามและชุดมืดไม่นิยามชื่อที่ชุดขาวไม่มี)

### ledger: ครบทุกฟังก์ชัน ไม่ตกหล่น

| ไฟล์ต้นทาง | ชื่อระดับบนสุด | คงเดิมตรงตัว | แก้ (มีเหตุผลรายตัว) | แทนด้วยโค้ด SHELL | ตกหล่น |
|---|---|---|---|---|---|
| `Rent_Gradient.py` | 189 | **168** (4,016 บรรทัด) | 15 | 6 | **0** |
| `Rent_Gradient_new.py` | 84 | **60** (808 บรรทัด) | 2 | 22 | **0** |

เทสต์เทียบซอร์สรายฟังก์ชัน: ชื่อที่ไม่อยู่ในรายการ "แก้/แทน" แล้วซอร์สต่างจากต้นฉบับ = เทสต์ล้ม; ชื่อที่อยู่ในรายการแต่จริง ๆ ไม่ต่าง = เทสต์ล้ม (รายการจึงไม่เน่า)
แก้ 15: `PAGE_CONFIG`, `DEFAULT_CONFIG`, `MAP_STYLES`, `_OVERPASS_LOCK`, `StateManager`, `NETWORK_CONFIG`, `SESSION_KEYS_TO_SAVE`, `_render_sidebar_marker_input`, `_render_sidebar_marker_list`, `_render_sidebar_network_panel`, `_render_sidebar_rent_panel`, `render_sidebar`, `render_header`, `render_map`, `main`
แทน 6: `should_add_marker`, `handle_map_click`, `_add_wms_layer`, `_add_map_legend`, `_render_sidebar_map_settings`, `render_analytics_panel`
ทั้งไฟล์ 7,949 บรรทัด: ส่วนที่คัดลอกตรงตัวราว 4,820 บรรทัด (≈ 61 %) · ส่วนที่เขียนใหม่/แก้ (SHELL) 105 รายการ รวม 2,350 บรรทัด (≈ 30 %) · ที่เหลือคือ import, หัวข้อ section และบรรทัดว่าง

## 7) ผลการวัด

วิธีวัด (sandbox นี้): `AppTest` โหลดผลสำเร็จรูปจาก `Geoapify_Map/เชียงของ-cbd.json` + เครือข่ายถนนจริง 1,648 โหนด / 4,090 เส้น แล้ว **รัน rerun สลับ base ↔ v2 ในโปรเซสเดียว** (ตัดความเพี้ยนของเครื่อง), มัธยฐานของ 8–20 รอบ, ปิดการเรียก GitHub JSON · "คอมไพล์แคช" = ใช้ `ScriptCache` ร่วมกันทุกรอบเหมือน `Runtime` ของเซิร์ฟเวอร์จริง (AppTest สร้าง `ScriptCache` ใหม่ทุก `run()` จึงคอมไพล์สคริปต์ซ้ำทุกรอบ ซึ่งแปรตามขนาดซอร์ส — ไฟล์ v2 ใหญ่กว่า AST ราว ×1.27)

| กรณี | `Rent_Gradient.py` | v2 | หมายเหตุ |
|---|---|---|---|
| ชั้นหนักปิด · AppTest ปกติ | 0.41 s | 0.52 s | ×1.26 — **ช้ากว่า** เพราะคอมไพล์ซ้ำทุกรอบ (ดูแถวถัดไป) |
| ชั้นหนักปิด · คอมไพล์แคช | 0.099 s | 0.115 s | **+16 ms (×1.16)** — องค์ประกอบใน sidebar เพิ่มจาก 90 เป็น 117 (แผง Space Syntax + แผงชั้นแผนที่) |
| เปิด Betweenness + Nodes · AppTest ปกติ | 1.15 s | 0.60 s | เร็วขึ้น ×1.9 |
| เปิด Betweenness + Nodes · คอมไพล์แคช | 0.89 s | 0.24 s | เร็วขึ้น ×3.7 |
| เวลา `st_folium` (เปิดชั้นหนัก) | 0.84 s | 0.16–0.18 s | |
| ขนาดสคริปต์แผนที่ (เปิดชั้นหนัก) | 2,311 KB | 643 KB | −72 % |
| 16,000 เส้น · เปิดชั้นหนัก (ปกติ / แคช) | 3.45 s / 3.29 s | 0.96 s / 0.64 s | สคริปต์ 8,503 → 2,380 KB |
| 65,440 เส้น · เปิดชั้นหนัก (ปกติ / แคช) | 15.5 s / 13.9 s | 2.6 s / 2.2 s | สคริปต์ 32,996 → 9,266 KB |
| คอมไพล์หน้า **ครั้งเดียวต่อโปรเซส** | 247 ms | 363 ms | จ่ายตอนเปิดเซิร์ฟเวอร์/แก้ไฟล์เท่านั้น |

Chromium จริง (Playwright + Chromium 141, ชั้นหนักเปิด, ข้อมูลเดียวกัน):

| รายการ | `Rent_Gradient.py` | v2 |
|---|---|---|
| renderer | SVG — 5,749 path | **canvas** — 1 canvas, 0 path |
| สลับ checkbox ชั้นแล้วมุมมอง (ผู้ใช้ซูมไว้ที่ 17) | **เด้งกลับ zoom 14 + ศูนย์เดิม** | **คงที่ zoom 17 และศูนย์เดิม** |
| คลิก checkbox → เห็นชั้นใหม่ | 4.8 s | 4.6 s (ไม่ต่างอย่างมีนัย — แผนที่ยังถูกสร้างใหม่ทุกครั้ง เวลาส่วนใหญ่อยู่ฝั่งเบราว์เซอร์ใน sandbox) |
| แผนที่พร้อมครั้งแรก | 5.1–7.0 s (สองรอบวัด) | 5.6 s (ความแปรผันระหว่างรอบมากกว่าความต่าง) |
| เปิดชั้น Space Syntax จากปุ่มตัวอย่างเชียงของ | – | 13 s จากกดปุ่มถึงเห็นชั้นบนแผนที่ (2,172 segment · คำนวณเอง 4.7 s) · LayerControl มีแถว 🧭 · legend กล่องเดียว (Travel Areas + Integration NAIN + Golden Spot) |
| คลิกแผนที่เพื่อเพิ่มหมุด | ✓ | ✓ ในรอบวัดนี้ (12 → 13 หมุด) — **ถอดออกภายหลังตามคำสั่งผู้ใช้**: ตอนนี้คลิกแผนที่ไม่เพิ่มหมุด (§6 ข้อ 7) |
| `sessionStorage` ถูกบล็อก | – | ✓ แผนที่/ชั้น/legend/คลิกใช้ได้ ไม่มี error ใหม่ (มุมมองกลับไปเด้งเหมือนเดิม) |
| console error | ไทล์ภายนอกโหลดไม่ได้ | เหมือนกัน (`ERR_TUNNEL_CONNECTION_FAILED` ของ `tile.openstreetmap.org`, `mt1.google.com`, `ms.longdo.com` — sandbox บล็อกอินเทอร์เน็ต) |

**ที่ไม่ได้ดีขึ้น (รายงานตรง ๆ):** (ก) rerun เปล่าตอนปิดชั้นหนักช้ากว่าเดิมเล็กน้อย (+16 ms ในโหมดคอมไพล์แคช ซึ่งใกล้เคียงเซิร์ฟเวอร์จริง) เพราะมีองค์ประกอบใน sidebar มากขึ้น · (ข) เวลาที่เห็นชั้นใหม่หลังคลิกในเบราว์เซอร์ใกล้เคียงเดิม — ที่ดีขึ้นคือไม่เสียมุมมอง, canvas ลื่นกว่า และงานฝั่งเซิร์ฟเวอร์/ขนาดข้อมูลลดลงมาก · (ค) ความเร็วของ **การคำนวณ** betweenness ของ Network ไม่เปลี่ยน (1,648 โหนดแบบ exact ใช้ราว 23 s) — เป็นอัลกอริทึมเดิมที่ล็อกไว้เพื่อให้ตัวเลขเท่าเดิม

## 8) เทสต์และการตรวจ

| ชุด | ผล |
|---|---|
| `tests/test_rent_gradient_new_v2.py` (ledger · state/เสถียรภาพ · registry · Space Syntax · views · AppTest ทุก flow · การเพิ่มหมุด · สีขาว/ดำ) | **87 ผ่าน** (เดิม 64) |
| `tests/test_rent_gradient_new.py` (หน้า Space Syntax เดิม — ไม่แก้) | **88 ผ่าน** |
| เทสต์ 6 ไฟล์ของ `Rent_Gradient.py` (automated_anchor, anchor_evidence, anchor_stability_and_cache, rent_gradient_principles, osm_failover, wms_fixtures) กับ `Rent_Gradient.py` เอง | 168 ผ่าน · 3 ข้าม |
| เทสต์ 6 ไฟล์เดียวกันกับ v2 (สำเนา scratch ที่สลับ path เป็น v2 และปรับ 2 จุดเพราะ marker anchor อยู่ใน FeatureGroup) | 168 ผ่าน · 3 ข้าม |

3 ข้าม = เทสต์ภาพ WMS ที่ต้องรัน `scripts/capture_wms_fixtures.py` (ต้องต่อเน็ต) — ข้ามเหมือนกันทั้งสองหน้า

ที่เพิ่มในรอบ "หมุดกรอกเอง + สีขาว/ดำ": แผนที่เรียก `st_folium` โดยไม่ขออะไรกลับ · ไม่มี `handle_map_click`/debounce · รายชื่อฟังก์ชันที่เพิ่มหมุดได้ถูกล็อก (ไม่มีทางเพิ่มหมุดจากแผนที่) · กรอกพิกัดถูกต้อง → หมุด active เพิ่ม + ผล Isochrone/CBD/Rent ถูกล้าง แต่ผล Network อยู่ · พิกัดผิด 7 แบบ → แจ้งเหตุผล ไม่เพิ่ม ไม่ล้างผล · เมนูล็อกแล้วช่องกรอกถูกล็อกด้วย · ลบหมุดกลางรายการแล้วสถานะ เปิด/ปิด ของหมุดที่เหลือไม่สลับ (ล้มถ้าเอาการล้างสถานะ checkbox ออก) · ตัวเลข Active Markers ตามการติ๊กในรอบเดียวกัน · ชุดสีขาว/ดำของแผงบนแผนที่ครบชื่อและ contrast ≥ 4.5:1 · legend ไม่มีสีของตัวเอง · ป้ายหมุดไม่ใช้ชื่อสี CSS · การ์ดหลักการไม่มีสีตายตัวนอกจากสีเน้นหนึ่งสี

ครอบคลุมโดยเทสต์ v2 (ตัวอย่าง): ซอร์สเท่ากันทุกฟังก์ชัน · ไม่ import ข้ามหน้า · remote defaults เรียก ≤ 1 ครั้งต่อ TTL · ล็อก Overpass เป็นอ็อบเจ็กต์เดียวแม้โมดูลถูกรันซ้ำ · cache_data ทุกตัวมี `max_entries` · config ผิดชนิดถูกข้ามและแจ้ง · layer พัง 1 ชั้นแผนที่ยังขึ้น + มี warning · ข้อความจาก OSM/ผู้ใช้ถูก escape · แผนที่ฐาน deterministic · Space Syntax คำนวณ/แสดงผลเท่าหน้าเดิม · PNG/histogram ไม่ถูกสร้างถ้าไม่ได้เลือก view · เปลี่ยนตัวเลือกแสดงผลแล้วไม่คำนวณใหม่ · widget ที่ถูกซ่อนจำค่าไว้ · เมนูล็อกแล้ว Space Syntax ถูกล็อกด้วย

**ตรวจจริงในเบราว์เซอร์ (ขาว/ดำ)**: รัน Streamlit จริง + Playwright 1.56 / Chromium จำลอง `prefers-color-scheme` ทั้ง light และ dark (Leaflet/ปลั๊กอินจาก npm แทน CDN · ไทล์พื้นหลังเป็นภาพเทาเรียบเพราะ sandbox ต่อเน็ตไม่ได้) — โหลด bundle เชียงของ → **คลิกกลางแผนที่ → จำนวน Active Markers ไม่เปลี่ยน (1 → 1)** · กรอกพิกัดทีละจุด 7 ครั้ง → 8 หมุด · `95, 100` และ `abc` ถูกปฏิเสธพร้อมคำอธิบาย (ยัง 8 หมุด) · จับภาพหน้าหลัก, แผนที่ + layer control + legend, popup, tooltip, แผงวัดระยะ, แถบ attribution/พิกัด/scale, หน้า 📐 หลักการ, รายการหมุด (รวมหมุดสีดำ/ชมพู/ที่ปิดอยู่) และมุมมอง 🧭 Space Syntax ทั้งสองโหมด — ข้อความทุกส่วนอ่านออก ไม่มีสีที่หายบนพื้นใดพื้นหนึ่ง

เวอร์ชันที่ใช้ตรวจ: Python 3.13 · streamlit 1.66.0 · streamlit-folium 0.27.4 · folium 0.20.0 · osmnx 2.1.1 · networkx 3.7 · scipy 1.18.1 · shapely 2.2.0 · Chromium 141

## 9) ยังไม่ได้ตรวจสอบ / ข้อจำกัด

- **บริการภายนอกจริง**: Overpass (ดาวน์โหลดถนน + failover), Geoapify isochrone API, WMS (ผังเมือง/ประชากร/แปลงที่ดิน), ไทล์พื้นหลังและ Google Traffic — sandbox ต่อเน็ตไม่ได้ จึงตรวจด้วย config + กราฟที่บันทึกไว้เท่านั้น (โค้ดชั้น WMS ตรวจได้ว่าสร้างถูก ไม่ใช่ภาพจริง) · เทสต์ภาพ WMS 3 ข้อถูกข้าม
- **Streamlit Community Cloud**: ยังไม่เคยรันบนของจริง (หน่วยความจำ/ทรัพยากรจำกัด, `requirements.txt` จริง) — ควรเปิดหน้าครั้งแรกหลัง deploy แล้วลอง: Run Space Syntax ตัวอย่าง, สลับชั้น, เพิ่มหมุด
- **พื้นหลังแผนที่ไม่เปลี่ยนตามธีม**: โหมดมืดของ Streamlit ไม่ได้เปลี่ยนไทล์ — ค่าเริ่มต้น Esri Light Gray ยังสว่าง ให้เลือก "Dark (Esri Dark Gray)" / "พื้นดำ" เอง · สีข้อมูล (Betweenness แบบ plasma เริ่มจากน้ำเงินเข้ม, จุด Node `#000000` ที่มาจากเอนจิน) ออกแบบสำหรับพื้นอ่อน จึงจางบนพื้นดำ — ไม่ได้ปรับเพราะสื่อความหมายและอยู่ในโค้ดที่คัดลอกตรงตัว
- **แผงบนแผนที่ตามระบบปฏิบัติการ ไม่ใช่ตามปุ่มธีมของ Streamlit**: ใช้ `prefers-color-scheme` เพราะเอกสาร `st.context.theme` ระบุว่าค่าอาจผิดตอนโหลดครั้งแรกและตอนเปลี่ยนธีม · ถ้าเลือกธีม Streamlit ต่างจากระบบ แผงบนแผนที่จะใช้สีของระบบ (ยังอ่านออกทั้งคู่ เพียงไม่กลมกลืน)
- **สีหลักของ Streamlit** (ปุ่ม/checkbox/radio สีแดง) เป็นธีมทั้งแอป ไม่ได้แก้ในหน้านี้ — ต้องตั้ง `.streamlit/config.toml` ซึ่งกระทบทุกหน้า
- **ปุ่มเพิ่มหมุดที่ไม่ใช่การคลิกแผนที่ยังอยู่** (§6 ข้อ 7) — ปุ่มยืนยันใน view 💎 Golden Spots อยู่นอก ⚙️ การตั้งค่า ถ้าต้องการให้เพิ่มได้ที่ sidebar เท่านั้นเต็มรูปแบบ ย้ายเข้าแผง Network ได้ (ต้องให้ sidebar แสดงผลหลังรัน Network ทันที — ตอนนี้แผงนั้นตามหลังหนึ่ง rerun)
- **Chromium ใน sandbox** ใช้สำเนา Leaflet/Bootstrap/Font Awesome จาก npm แทน CDN และ stub ของปลั๊กอิน measure/mouse-position — ไม่มีผลต่อชั้นแผนที่/มุมมอง แต่ไม่ได้ตรวจปลั๊กอินสองตัวนั้นของจริง
- **ความเร็วการคำนวณ Network** (betweenness/closeness) ไม่ได้ปรับ — คงอัลกอริทึมเดิมเพื่อให้ตัวเลขเท่าเดิม
- **`use_container_width`** ที่ Streamlit ประกาศเลิกใช้: โค้ดที่คัดลอกตรงตัวยังใช้อยู่ 24 จุดเหมือน `Rent_Gradient.py` (โค้ด SHELL ใหม่ใช้ `width="stretch"`) — ยังทำงานบน streamlit 1.66.0 พร้อมคำเตือนใน log; การย้ายทั้งหมดเป็นงานกลไกที่ควรทำกับทั้งสองหน้าใน PR แยก
- **API key** ที่ฝังอยู่ใน `DEFAULT_CONFIG` ถูกคัดลอกตามต้นฉบับ (ไม่ได้ย้ายไป `st.secrets`) — แนะนำทำใน PR แยกพร้อมหมุนเวียน key
- เทสต์เก่า `tests/test_rent_gradient_v2.py` และ `test_rent_gradient_flow.py` error ตั้งแต่ตอน collect (หน้า `Rent_Gradient_V2.py` / `Rent_Gradient_Flow.py` ถูกลบไปแล้ว) และ `test_rent_gradient_laora_page.py` ล้ม (หน้า Laora ถูกเปลี่ยนชื่อเป็นไฟล์ไม่มีนามสกุล) — เป็นอยู่แล้วก่อนงานนี้ ไม่เกี่ยวกับ v2 ไม่ได้แตะ (`test_rent_gradient_laora.py` 16 ข้อและ `test_design_page.py` 55 ข้อผ่าน)

## 10) ทางเลือกในอนาคต (ยังไม่ได้ทำ)

- **อัปเดตชั้นโดยไม่ re-mount แผนที่** ด้วย `feature_group_to_add` ของ `streamlit-folium`: อ่านซอร์ส frontend (0.27.4) แล้วพบว่า `window.feature_group` ถูก push เพิ่มทุกครั้งที่อัปเดตและไม่เคยล้างอาร์เรย์ → ชั้นเก่า (หมื่นเส้น) ค้างในหน่วยความจำเบราว์เซอร์ตามจำนวนครั้งที่สลับ และ legend/HTML ของแผนที่ถูกฉีดครั้งเดียวตอน mount ไม่อัปเดต จึงเลือกแผนที่ static + จำมุมมองแทน — ถ้าจะทำต้องแก้ที่ตัว component
- **สไตล์แผนที่ตามธีมอัตโนมัติ** (ไทล์มืดเมื่อโหมดมืด) ต้องทำคู่กับชุดสีข้อมูลสำหรับพื้นมืด · **ธีมทั้งแอป** ใน `.streamlit/config.toml` (สีหลักที่นุ่มกว่าแดง) — สองข้อนี้กระทบนอกหน้านี้หรือเปลี่ยนข้อมูลที่เห็น จึงยังไม่ทำ
- ย้าย API key ไป `st.secrets` · `st.fragment` สำหรับ view ที่หนัก · ให้ Space Syntax เลือกศูนย์จากหมุด/anchor อัตโนมัติ · ใช้ Space Syntax เป็นตัวแปรในโมเดล Rent
