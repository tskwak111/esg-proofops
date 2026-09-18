# Atomic-evidence worker review — LG Chem p24 claims vs p97–99 data vs p117–119 assurance

Scope: source-text observation only. No grades, labels, clauses, or human approvals are asserted.
All `binding_status=undetermined`, `source_quality=unverified`, `atomicity=not_reviewed`
per `.local/section-pipeline/live-two-packets/candidate-links.json`, `result.json`, `summary.json`.
No approved verification exists; nothing below is an approved verification.
Original PDF (from artifact `source.json`): 「LG화학 지속가능경영보고서 2025」, 119 pages.
Parsed 57-page artifact set (`parse_manifest_id 1aaf9890-eaef-4898-812c-0718a63036a7`):
physical pages 16–49 + 97–119. p24, p97–99, p117–119 are all inside the set.
p4 (reporting-boundary Overview) is NOT in the parsed set; p4 text below is seen only via
`.local/section-pipeline/final/lg-map.json` named-destination preview, not via parsed artifact.

## 1. p24 claim atoms (parsed text, `source.json` p24, id 3042 / candidates `:0,:1,:3,:4`)

- A1 (result.json `:0`, chars 0–68): 2050 Net-Zero goal + 2030 GHG reduction roadmap. Goal-type.
  Target years 2050 / 2030 present; no numeric target, no base year, no Scope in this sentence.
- A2 (result.json `:1`, chars 69–223): Carbon Neutral Growth — keep Scope 1 + Scope 2 at the
  2019 baseline level (2019년, 951만 tCO₂e) as the 2030 target. Goal-type.
  Metric = Scope 1&2 total; base year = 2019; base value = 9.51 MtCO₂e; target year = 2030.
  No Market-based vs Location-based qualifier on the Scope 2 portion in this sentence.
- A3 (result.json `:3`, chars 287–406): GHG reduction as part of company-wide climate strategy,
  managed in linkage with K-taxonomy. Management-type, no numeric content.
- A4 (result.json `:4`, chars 407–589): 2030 levers (efficiency, low-carbon fuel/feedstock,
  renewables) + mid/long-term tech (electrification, electrolysis furnaces, CCU). Transition-plan text.
- A5 (p24 id 3108): 2025 performance claim — 8 efficiency tasks, ≈30,000 tons GHG reduced in 2025
  (약 3만 톤). Performance-type. No Scope split, no global/domestic boundary, no method,
  gas written as 온실가스 (CO₂e implied, not stated). Typo in source: "생산공정정".
- A6 (p24 chart + 이행계획 table): roadmap chart, unit 만 톤; 이행계획 shares 3% / 25% / 72% = 100%,
  footnote id 3105: subject to change with business structure / renewable sourcing.

## 2. p24 chart/table inspection (text parse only — visual render not performed here)

- Chart fragments (ids 3043–3075): unit (단위: 만 톤); values 951 / 951 / 890;
  year labels 2019 Baseline / 2025 / 2030 탄소중립 성장 / 2050 Net-Zero.
  Parse order does NOT reliably attach 890 to a year label — 890 may be the 2025 bar,
  but this is UNCONFIRMED from text order alone. Coordinator should visually check original PDF p24.
- Numerical observation (not a verification): p97 2025 global Scope 1+2 = 8,889,779 tCO₂e
  ≈ 889만 톤 ≈ chart 890 (rounding-consistent). Year/boundary linkage of the 890 bar is
  unverified, so this is NOT claimed as a match.
- Chart 2030 bar = 951, direction-consistent with A2 ("hold at baseline level"), same unit family
  (만 톤 vs 951만 tCO₂e). Consistency of the TARGET definition is textual, not data-verified.
- 이행계획 table (ids 3093–3104): 3/25/72 shares sum to 100% as printed; the absolute-ton basis
  of the percentages (gap vs BAU? vs baseline?) is not stated in parsed text — underspecified,
  not false. Footnote makes the plan explicitly provisional.

## 3. p97–99 data tables — headers, footnotes, boundaries

p97 Scope 1·2 table (ids 5132–5136 + lists 5133, 5137):
- Header: Scope 1·2 배출량, unit tCO₂e, years 2023 / 2024 / 2025; rows 글로벌 / 국내 / 해외;
  intensity row tCO₂e/백만원.
- Split detail (list 5133): Scope 1 global/domestic/overseas + intensity; Scope 2 with
  Market-based AND Location-based for domestic and overseas + intensity. Dual reporting PRESENT.
- Footnotes (list 5137): (1) 2024 domestic S1+S2 partly revised per ministry inventory verification;
  (2) 2025 domestic S1+S2 per ministry submission basis, subject to change after verification —
  2025 is PROVISIONAL; (3) intensity denominator = revenue EXCLUDING LG Energy Solution,
  common & other segments — intensity boundary differs from absolute-total boundary;
  (4–6) Scope 2 dual-reporting method; global Scope 2 total uses Market-based; Market-based =
  Location-based minus REC/녹색프리미엄.
- Biogenic note (id 5136): biomass CO₂ reported separately (10.5 tCO₂), excluded from Scope 1.
- NO 2019 column anywhere in p97–99 parsed pages: the A2 baseline (2019, 951만) cannot be
  confirmed within p97–99. (Absence elsewhere in the 119-page report is NOT asserted.)

p98 Scope 3 table (id 5266 + lists 5267, method ids 5272–5299):
- Header: Scope 3 배출량, explicitly 국내 합계 (domestic-only total), unit tCO₂e, 2023–2025.
  Cats 1,2,3,4,5,6,7,9,11,12,15 shown (11 categories); Cat 8/10/13/14 not listed.
- Footnotes (list 5267): 2023 Cats 5,6,7,9,11,12,15 were EXCLUDED (no criteria), added from 2024;
  2025 criteria changes: Cat 1 SWAP-volume exclusion; Cat 4/9 EcoTransIT new-version distances;
  Cat 15 divestiture exclusion. 2023→2025 totals are NOT like-for-like — trend comparison
  across these years without noting this is a genuine mismatch risk.
- Method block: GHG Protocol Scope 3 Standard (2011) cited; per-category activity data stated;
  forward plan to expand from domestic to overseas (id 5278) — overseas Scope 3 currently out of scope.

p99 energy table (ids 5451–5459 + list 5460): global/domestic/overseas TJ + MWh splits;
footnotes redefine total-consumption scope (REC-based external procurement in; green premium and
self-generation out) with 2023/2024 restatement. Relevant only as context for A4/A5 levers.

## 4. Genuine mismatches / boundary gaps (p24 vs p97–99)

1. Baseline unverifiable in-range: A2's 2019/9.51M has no 2019 column in p97–99. Not "wrong" —
   evidence not present on these pages.
2. Scope 2 basis unspecified in A2: p97 shows Market vs Location differ materially
   (2025 overseas: Market 976,657 vs Location 1,108,646). The 2030 "951만" target does not state
   which basis applies — genuine boundary gap.
3. Entity boundary unconfirmed: p24 states no exclusions; the LG Energy Solution / 팜한농
   exclusion text is reported to live on p4 Overview (outside the 57-page parsed set, seen only
   via lg-map preview). Whether p97 totals and the A2 target share the same entity boundary
   is UNCONFIRMED within inspected artifacts. Do not assume.
4. A5 (≈30 kt via 8 tasks) has no linkable counterpart: p97 shows annual totals, not
   project-level reductions; no Scope/boundary/method stated. P6-style same-table confirmation
   is not present. Standalone provisional performance sentence.
5. 이행계획 % shares lack a stated absolute basis; chart 890 bar lacks a confirmed year label
   in text parse. Both need original-PDF visual check, not text assertion.
6. 2025 data provisional (footnote 2) + 2024 restated (footnote 1): any "on track vs 2030"
   reading that treats printed 2025 as final is unsound.

## 5. p117–119 assurance — observed coverage (not a verification of any claim)

Report assurance (p117, LRQA, ids 7845–7878):
- Standards: GRI 2021, ISAE 3000 + ISAE 3410; level: 제한적 보증 (limited); materiality by
  expert judgement. Explicit note (id 7866): limited < reasonable, focused on aggregated data.
- Scope: 2025-01-01–12-31, domestic + overseas operations; covers ESG DATA (ENV/SOC/GOV)
  accuracy/reliability + GRI-2021-basis check.
- Carve-outs (id 7858): suppliers, contractors, other third parties EXCLUDED.
- Method notes: Scope 1+2 + energy data cross-checked against another third party's verified
  result (id 7872); Scope 3 checked as appropriately reflected from a separate LRQA contract
  (id 7874). Opinion: no matters found (negative-form limited conclusion, id 7861–7865).

GHG inventory assurance (p118–119, LRQA, ids 7898–7925 + p119 Table 1):
- Standard: ISO 14064-3:2019; level: limited; materiality 5%.
- Scope: 국내 only (domestic operations) — overseas NOT covered here.
  Covers Scope 3 data/information accuracy + GHG Protocol Scope 3 compliance.
- p119 Table 1 Scope 3 total 18,335,055 tCO₂e DIGIT-MATCHES p98 2025 domestic total
  (observation, not approval). Category values listed (Cat 12: 2,445,823; Cat 15: 184,378, etc.).

Coverage consequences for the p24 atoms:
- A1/A2/A4 (goals/plans): assurance statements give no goal-attainment coverage; goals are
  inherently outside a historical-data limited assurance. No `covered` status may be inferred —
  candidate-links already records `binding_status: undetermined`.
- A5-type performance numbers: report assurance (limited, global ops) nominally in scope, but
  (a) project-level 30 kt items are not line items in either assurance table observed;
  (b) the inventory assurance backing is domestic-only while A5's boundary is unstated.
  At most `undetermined`; never `covered` on current evidence.
- No reasonable-assurance statement observed on any inspected page. Assurance provider LRQA;
  contract nos. SEO00000269 (2026-06-25) and SEO00001951 (2026-06-20) as printed.

## 6. What is left for the coordinator (no fix applied here)

- Visually render original PDF p24: attach the 890 bar to its year label; confirm chart title,
  axis, and whether 2030 bar = 951 target or a modeled value.
- Confirm entity boundary from original PDF p4 (battery/farm exclusions) and restate which
  p97–99 totals share A2's boundary; confirm Market- vs Location-based basis of the 2030 target.
- Locate any 2019 baseline disclosure outside pp.16–49/97–119 if needed; do not treat p97–99
  silence as report-wide absence.
- All tagging/grading decisions belong to the pipeline + coordinator; this review changes no code,
  grades, or links.
