# Atomic coverage worker review — 13 sentence targets (p24) vs discovery + original text + atomic_pilot.py

Scope: review only. No code edits, no Git, no model API calls, no secrets accessed.
Read: `AGENTS.md`, `docs/00_MASTER_SPEC.md`, `docs/26_LEGACY_REUSE_AUDIT.md`,
`docs/27_PARSING_AND_PROVENANCE.md`, `docs/28_RULE_ENGINE_CONTRACT.md`,
`docs/31_DOMAIN_IMPLEMENTATION_GAPS.md`,
`.local/section-pipeline/live-two-packets/result.json` (13 claims, 2 packets),
`.local/atomic-pilot/targeted/discovery.json` (12 claims) +
`.local/atomic-pilot/targeted/summary.json` + per-request folders
(`request.json` / `response.json` / `validation.json`),
`evaluation/atomic_pilot.py`, `evaluation/upstage_live_probe.py` (`locate_quotes`),
`packages/proofops/application/claims.py` (`discover_atomic_claims`,
`validate_extraction_response`), `apps/agent/src/proofops_agent/extraction.py`.
Per AGENTS.md: LLM does extraction/tagging only; grades/labels are pure-Python
rule-engine output (not inferred here); `unknown`/`conflict`/`unreadable` are not
recast as absence; `present` requires verified source grounding (not asserted here);
numbers/target-years get no automatic document-global grounding (GAP-004);
tenant/version/page/coords/replica/model/prompt/rule hashes are preserved;
no invented domain thresholds, article numbers, regulatory facts, model ARNs, or
performance figures.

## 1. Target inventory (what the "13" are)

`result.json` top-level `claims` (13) = sentence targets:

- `32ae97f9-e49d-5a02-9c57-45cbf4579e8b:0` [0,68]: "LG화학은 2050년 넷제로(Net-Zero) 달성을 목표로 2030년 온실가스 감축 로드맵을 수립하여 추진하고 있습니다."
- `32ae97f9…:1` [69,223]: "향후 생산능력 확대 및 글로벌 사업 확장에 따른 배출량 증가 요인에도 불구하고, Scope 1 및 Scope 2 배출량을 기준연도(2019년, 951만 tCO₂e) 수준으로 관리하는 탄소중립 성장(Carbon Neutral Growth)을 2030년 목표로 설정하고 있습니다."
- `32ae97f9…:3` [287,406]: "이러한 사업 환경을 고려하여 온실가스 감축 과제는 기후 리스크 및 기회 대응을 위한 전사 전략의 일환으로 추진되고 있으며, 녹색 금융 및 투자 기준에 부합하도록 K-택소노미 분류 체계와 연계하여 관리하고 있습니다."
- `32ae97f9…:4` [407,589]: "LG화학은 2030년까지 에너지 효율 개선, 저탄소 연료·원료 전환 및 재생에너지 확대를 중심으로 감축을 추진하고 있으며, 중장기적으로는 공정 전기화, 전기분해로, 탄소 포집·활용(Carbon Capture and Utilization, CCU) 등 저탄소 공정 기술 개발을 통해 배출 구조의 근본적 전환을 추진하고 있습니다."
- `f93c5d61-41cc-51bb-aa84-b84a2631f8fa:0` [0,52], `:1` [53,154] (2 targets)
- `1c115c9f-6314-5690-8ef2-52d47cf67441:0` [0,76], `:1` [77,164] (2 targets)
- 5 single-span targets: `74e46a77…:0` [0,30], `f2d74546…:0` [0,32], `657cd272…:0` [0,35], `578612a7…:0` [0,31], `2adb2e35…:0` [0,27]

`discovery.json` contains 12 claims — every target above **except `32ae97f9…:3`**.
All kept quotes/char offsets in `discovery.json` match `result.json` exactly
(byte-identical substrings, same `source_id`/offsets/`raw_text_sha256`/bbox).
`source_quality` remains `unverified`, `verification_state` `candidate`,
`atomicity`/`decision` unset (`summary.json`: `"atomicity":
"model_proposed_not_independently_reviewed"`, `"decision": null`) — correctly
not upgraded by this reviewer.

Original p24 paragraph text (from
`.local/atomic-pilot/targeted/3143f684-…/request.json` `context`, len 589)
confirms a sentence missing from `result.json` numbering (`:2` gap between `:1`
end 223 and `:3` start 287):

- `:2` (untargeted, context-only), chars ~224–286: "석유화학 산업은 생산 공정 특성상 단기간 내 직접 배출(Scope 1) 감축에 기술적·경제적 제약이 존재합니다."

## 2. Omitted targets

- **O-1 — `:2` never became a target (sentence-candidate stage).**
  `result.json` sentence_ids run `:0,:1,:3,:4`, skipping `:2`.
  Verdict on correctness is the coordinator's, but factually: the sentence is a
  generic industry constraint statement with no company subject, no year/value
  commitment, no management action. Both SYSTEM prompts ("Exclude general
  industry descriptions and definitions" in `upstage_live_probe.py`; atomic pilot
  "Isolated headings, chart labels and generic background are not assertions")
  give a textual basis for exclusion. Required handling per
  `discover_atomic_claims`: it must stay `unknown` (uncovered text), never be
  treated as absence/non-claim, and must not be silently reworded. It currently
  survives only as `context` (interpretation aid, not a claim source) — that part
  is correct. Do NOT promote it to `present` without verified grounding.
- **O-2 — `32ae97f9…:3` targeted but dropped by the model (atomic stage).**
  Target ranges in `3143f684-…/request.json` explicitly include `(287,406)`,
  yet live `response.json` (`{"claims":[…]}`) returns only 3 claims
  (`:0`, `:1`, `:4`) and `summary.json` records `spans: 3` for source `32ae97f9`.
  `discovery.json` therefore has no claim with `char_start 287`.
  Worse, `discovery.json` buries the dropped target inside a single
  `unprocessed_span`/`unknown` exclusion spanning **[223,407]**, which concatenates
  the untargeted `:2` background AND the targeted-but-dropped `:3` K-taxonomy
  sentence into one gap. A re-reader cannot distinguish "background uncovered"
  from "model dropped an explicit target". This is the single most lossy point
  in the 13→12 comparison. Minimal fix is re-extraction of the exact stored
  target substring (see R-1), plus gap-span bookkeeping that separates
  never-targeted gaps from dropped-target gaps (coordinator-owned).

## 3. Compound assertions kept whole (per-target)

"Compound" here means two independently assertable goals/results/actions joined
in one quote. Whether to split is governed by the pilot SYSTEM: split separate
goals/results/actions into minimal exact clauses with year/value/unit/Scope/
entity/qualifier attached; do NOT split a measure list or Scope 1+2 into
invented assertions; if exact splitting loses essential qualifiers, keep the
compound quote for later review.

- **C-1 — `32ae…:0`**: two time-bound assertions in one quote: (a) 2050 Net-Zero
  goal + (b) 2030 roadmap established/pursued. Split point exists at the sentence
  level only (it IS one sentence); sub-sentence split would need exact-clause
  substrings each retaining entity+year. Currently kept whole in both artifacts —
  defensible under "keep compound if qualifiers lost"; any split must be
  source-exact substrings, not paraphrases (see R-2).
- **C-2 — `32ae…:1`**: concession ("에도 불구하고") + Scope 1+2 cap at
  2019/951만 tCO₂e + Carbon Neutral Growth as 2030 goal. Correctly kept whole:
  splitting Scope 1 vs 2 or detaching "2019년, 951만 tCO₂e" / "2030년" / "에도
  불구하고" would violate the keep-qualifier-attached and no-invented-Scope-split
  rules. No split recommended; flag only that downstream tagging must keep
  baseline-year, baseline-value, scope, and target-year bound to THIS assertion
  (GAP-004: no document-global year/number grounding).
- **C-3 — `32ae…:3` (the omitted one)**: two assertions sharing a subject:
  (a) GHG task pursued as part of company-wide climate risk/opportunity strategy;
  (b) managed in linkage with K-taxonomy to meet green-finance standards.
  If re-extracted, keep as ONE source-exact quote (the full [287,406] sentence)
  unless two exact non-overlapping substrings can each carry their qualifier
  ("전사 전략의 일환" vs "K-택소노미 … 연계"). Do not split off "K-택소노미" as a
  standalone label claim.
- **C-4 — `32ae…:4`**: two horizon assertions: (a) "2030년까지 … 중심으로" near-term
  lever list (efficiency, low-carbon fuel/material switch, renewables expansion);
  (b) "중장기적으로는 …" technology list (electrification, electrolysis furnace,
  CCU) toward fundamental structural shift. A source-exact split at the
  "중장기적으로는" boundary is textually possible with years/horizons retained on
  each side, but the lever lists themselves must NOT be exploded into one-claim-
  per-item (SYSTEM forbids splitting a measure list into invented assertions).
  Recommend at most a two-clause split, or keep whole (see R-2).
- **C-5 — `f93c…:1`**: means list (operating-condition optimization,
  high-efficiency equipment, waste-heat recovery) + outcomes (steam/power
  reduction + "이를 통해 온실가스 배출 저감"). The "이를 통해" causal link is the
  qualifier binding means to outcome — splitting means from outcome loses it.
  Keep whole.
- **C-6 — `1c11…:1`**: quantitative result clause ("2025년에는 총 8건의 에너지
  효율화 과제를 통해 약 3만 톤의 온실가스를 저감하였으며") + tail ("주요
  생산공정정에서 추진한 에너지 효율화 사례는 다음과 같습니다"). The tail is an
  introductory pointer ("다음과 같습니다"), explicitly excludable per pilot
  SYSTEM ("excluding introductory phrases such as 'examples are as follows'").
  Currently the whole [77,164] sentence is one claim including the pointer tail
  AND the source typo "생산공정정" (must be preserved byte-exact, never
  corrected). See R-3.
- **C-7 — short fragments (5 singles)**: each is a heading/chart-label-like noun
  phrase without sentence predicate or explicit subject (see §5). They are atomic
  by length but compound-ambiguous (e.g. `f2d74546…:0` concatenates category
  "설비 효율 개선" + instance "원심분리기 성능 개선 및 운전 조건 최적화" without
  particle). Do not further split; resolve assertion-status first.

## 4. Lost or at-risk qualifiers (if split or reworded carelessly)

- **Q-1 — concession qualifier**: "배출량 증가 요인에도 불구하고" (`:1`) binds the
  cap commitment to adverse growth context. Any clause split must carry it with
  the cap assertion or keep the compound.
- **Q-2 — scope+baseline bundle** (`:1`): "Scope 1 및 Scope 2", "기준연도(2019년,
  951만 tCO₂e)", "수준으로 관리", "2030년 목표". Detaching any one element
  (e.g. quoting only "951만 tCO₂e" or only "2030년 목표") breaks G3/G4 element
  binding under `28_RULE_ENGINE_CONTRACT.md`.
- **Q-3 — horizon markers** (`:4`): "2030년까지" vs "중장기적으로는". A split must
  not leave one clause horizon-less.
- **Q-4 — approximation + unit** (`1c11…:1`): "약" (approximately) + "3만 톤".
  "약" must be preserved in any sub-quote; "톤" without "온실가스" loses the
  metric; "8건" without "에너지 효율화 과제" loses the subject of counting.
  Note "톤" here abbreviates tCO₂e context from the same sentence's "온실가스를" —
  do not import unit expansions from elsewhere in the document (GAP-004).
- **Q-5 — linkage qualifiers** (`:3` when re-extracted): "전사 전략의 일환",
  "녹색 금융 및 투자 기준에 부합하도록", "K-택소노미 분류 체계와 연계". Each
  belongs to its respective clause; a naive split on "며," could strand them.
- **Q-6 — causal link** (`f93c…:1`): "이를 통해" ties steam/power savings to GHG
  reduction. Do not quote the GHG tail as an independent measured result.
- **Q-7 — source typo**: "생산공정정" (`1c11…:1`) must be reproduced exactly;
  "fixing" it breaks quote/offset validation (`validate_extraction_response`
  requires `quote == text[start:end]`).

## 5. Subject-less fragments — no unsupported subject inheritance

The five singles lack an explicit company subject in-quote:

- `74e46a77…:0` "설비 운영 효율 향상을 통한 전력 및 스팀 사용량 절감"
- `f2d74546…:0` "설비 효율 개선 원심분리기 성능 개선 및 운전 조건 최적화"
  (note missing particle — likely chart-label concatenation)
- `657cd272…:0` "공정 열효율 향상 및 폐에너지 재활용을 통한 온실가스 배출 저감"
- `578612a7…:0` "열에너지 회수 열교환기 설치 및 폐증기 회수 시스템 구축"
- `2adb2e35…:0` "고효율 설비 적용을 통한 냉각수 펌프 운영 최적화"

Pilot SYSTEM says "never insert a missing subject" and "Isolated headings, chart
labels … are not assertions", yet all five are stored as `kind: claim` in both
artifacts. This reviewer does NOT resolve whether they are assertions, does NOT
inherit "LG화학" as their subject, and does NOT approve them as sources. Minimal
path for the coordinator: either return them as `excluded`/`unknown` with a
stated reason, or keep them as verbatim quotes whose missing-subject status is
explicitly recorded so the rule engine cannot treat them as company-asserted
performance/management facts. No grade, approval, or subject insertion is
recommended or implied here.

## 6. Minimal source-exact extraction recommendations (coordinator-owned)

- **R-1 (the one true omission — re-extract verbatim):** re-request source
  `32ae97f9` target `(287,406)` and store the exact substring
  "이러한 사업 환경을 고려하여 온실가스 감축 과제는 기후 리스크 및 기회 대응을 위한 전사 전략의 일환으로 추진되고 있으며, 녹색 금융 및 투자 기준에 부합하도록 K-택소노미 분류 체계와 연계하여 관리하고 있습니다."
  with identical `source_ref` (document_version `8b505a31-…`, parse_manifest
  `1aaf9890-…`, page 24, `raw_text_sha256 402c08ed…`, same bbox). Do not
  paraphrase, do not split Scope/entities, do not attach `:2` context into the
  quote.
- **R-2 (optional, only if the coordinator wants finer atoms):** the only splits
  with clean source-exact boundaries are `32ae…:4` at "중장기적으로는" (two
  horizon clauses, each keeping its year/horizon + lever list intact) and
  possibly `32ae…:0` into its 2050-goal vs 2030-roadmap clauses — each new quote
  must be an exact substring with entity+year retained, and the lever lists in
  `:4` must NOT be exploded per-item. Default if in doubt: keep compounds whole
  ("keep the compound quote for later review" per SYSTEM).
- **R-3 (`1c11…:1`):** trim the introductory tail at a source-exact boundary so
  the stored claim is "2025년에는 총 8건의 에너지 효율화 과제를 통해 약 3만
  톤의 온실가스를 저감하였으며" plus an explicit decision on the tail
  ("주요 생산공정정에서 추진한 에너지 효율화 사례는 다음과 같습니다" —
  introductory pointer, excludable per SYSTEM), preserving "약", "8건", "3만 톤",
  year 2025, and the "생산공정정" typo byte-exact in whichever span retains it.
  Do not normalize "약 3만 톤" to a bare number or import tCO₂e from `:1`.
- **R-4 (fragments):** do not reword or add subjects. Either re-label the five
  singles `excluded`/`unknown` with reasons (heading/chart-label/unclear subject)
  or retain verbatim with missing-subject flagged. No subject inheritance.
- **R-5 (gap bookkeeping):** separate the [223,407] `unprocessed_span` into
  never-targeted (`:2` background) vs targeted-but-dropped (`:3`) ranges so a
  future diff catches model drops mechanically.

No recommendation here infers grades, source approval, or subject inheritance.

## 7. `evaluation/atomic_pilot.py` — target provenance and replay safety

What is preserved well:

- Per-request folders store `request.json` (wire packet with `targets` +
  `context`, `SYSTEM`, `prompt_sha256`, `section_map_sha256`, `model_sha256`,
  `packet_sha256`, `application_packet_sha256`), `response.json` (raw provider
  payload incl. `provider_model`, `response_sha256`, cost snapshot), and
  `validation.json` (normalized spans + record). Tenant/document/manifest/page/
  model/prompt/rule hashes and `replicate_id`/`extraction_epoch` are in the
  `ExtractionProfile`. Claim IDs are `uuid5(parse_manifest_id, claim_hash)` over
  tenant+source_sha+source_ref+receipt, so identical re-responses reproduce IDs
  and prior revisions stay immutable. Offline (`--live` absent) path performs no
  model call. Range validation rejects empty/overlapping/out-of-bounds targets;
  `locate_quotes` enforces claims-only schema, exact unique (`text.count == 1`)
  verbatim matches, and containment of every returned span inside the declared
  target intervals. `discovery.json` keeps `raw_response_json`, both packet hashes,
  and full `profile` per receipt.

Gaps / replay hazards for the coordinator (no fix applied here):

- **P-1 — coverage is one-sided.** `respond()` raises if a returned claim lies
  OUTSIDE targets, but nothing fails when a target yields NO claim (the `:3`
  drop passed as `status: passed, spans: 3`). The loss is only visible as a
  merged `unprocessed_span` gap (§2, O-2). Consider a target-coverage check
  (each target interval covered by ≥1 span, or an explicit per-target
  `unknown`/`excluded` span with reason) before marking `passed`.
- **P-2 — receipt packet hash does not bind targets.** `discovery.json`
  `receipt.packet_sha256` equals the *application* packet hash (full text, no
  target split); the target list lives only in `profile.rule_sha256`
  (`dict(version=2, targets=ranges, map=…)`) and the per-request
  `request.json` wire packet. Replaying from `discovery.json` alone cannot
  reconstruct exact targets — keep `request.json` folders + `rule_sha256` as the
  replay unit, not the discovery file by itself.
- **P-3 — two extraction contracts coexist.** `discovery.json` receipts carry
  `raw_response_json` in `{"spans":[…]}` form while live-two-packets
  `response.json` files carry `{"claims":[…]}` form (parsed by `locate_quotes`
  into spans). A replay must pair each artifact with its matching prompt parser
  (`validate_extraction_response` vs `locate_quotes`) and prompt hash; the two
  `response_sha256` values for source `32ae97f9` legitimately differ across runs
  (targeted `4a4583b5…` vs live `7821a375…`) — do not dedupe across contracts.
- **P-4 — single replicate.** Profile uses `replicate_id: 1`,
  `extraction_epoch: 1`; this is NOT the three-substantially-separate taggings
  required by `00_MASTER_SPEC.md` §5/§8 for production. `summary.json`
  correctly labels output `model_proposed_not_independently_reviewed` with
  `decision: null` — keep that label until independent review + rule-engine
  scoring happen.
- **P-5 — configured-vs-returned model hashes.** `profile.model_sha256`
  (`19a9c578…`, configured `MODEL`) differs from per-request
  `provider_model_sha256` (`62b1bac008…`, returned `solar-pro3-260323`); both are
  stored, which is correct — do not collapse them. Live run also records
  `price_snapshot` with `region: provider-managed-unverified`; treat cost figures
  as provisional, not audited spend.
- **P-6 — secret/budget handling.** `--live` reads `UPSTAGE_API_KEY` from
  `.env.upstage.local` and spends via `.local/upstage/budget.sqlite3` ledger.
  This review made no live calls and read no secret; any re-run needs coordinator
  approval per AGENTS.md (model/cloud spend approval scope) and must preserve
  the ledger + `budget.json`.

## 8. Explicit non-inferences (AGENTS.md compliance)

No grade, label, track, approval, or verification state is assigned or changed
here. `unknown` (including `:2` background and the `:3` gap) is not recast as
absence or non-claim. `present` is not granted to any numeric/year assertion on
the basis of document-global context. No subject ("LG화학" or otherwise) is
inherited into the five subject-less fragments. No domain threshold, article
number, regulatory fact, model ARN, or performance figure is invented.

## 9. What's left (coordinator-owned)

1. Re-extract `32ae97f9` [287,406] verbatim (R-1) and split the [223,407] gap
   (R-5); 2. decide on R-2/R-3/R-4; 3. add a target-coverage gate (P-1) and
   document the discovery-vs-live contract pairing (P-2/P-3); 4. route all atoms
   through independent review + pure-Python rule engine before any grade/label.
