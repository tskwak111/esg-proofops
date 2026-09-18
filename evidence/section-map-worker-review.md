# Section-map worker review — E narrative / ESG DATA / APPENDIX boundaries

Date: 2026-09-09. Worker-only read inspection; no grades, no labels, no product inference calls (coding-agent review used Muse Spark 1.3 Free).
Scope per dispatch: claim targets = E narrative; evidence = E narrative + ALL ESG DATA
+ ALL APPENDIX (incl. S/G/glossary/assurance). Coordinator owns implementation/integration and fixes.

Method (read-only): `.venv` `pypdf` text extraction + `hashlib` sha256, running-header
banner classification (`ENVIRONMENT`/`ESG DATA`/`APPENDIX`, SEC `Planet`/`Facts & Figures`,
KB header tabs), divider-page self-maps cross-checked against observed neighbor pages.
Physical pages are 1-based PDF order. Printed labels matched physical numbers on all
sampled pages (LG `p16→/16/`, SEC `p3→03`, `p62→경제성과`, KB `p89→89`); full-document
offset-0 is a CANDIDATE generalization, not verified per page. Image/scan content
(cover p1 KB, SEC assurance scans) is reported as unreadable-by-text-extraction, never
inferred. Boundary tags: [TEXT-OBSERVED] = both sides' banners/headings directly observed;
[CANDIDATE] = inference needing visual or coordinator confirmation.

Specs read: `AGENTS.md`, `docs/00_MASTER_SPEC.md`, `sources/PROJECT_DOMAIN_V2_ORIGINAL.md`
(partial, through §13.2), `docs/20_TASK_BREAKDOWN.md`, `docs/27_PARSING_AND_PROVENANCE.md`
(§1–4), `docs/31_DOMAIN_IMPLEMENTATION_GAPS.md` (§GAP-001–009), `evidence/e-scope-case-review.md`,
`evidence/e-scope-verification.md`. No domain values invented; unresolved items stay unknown
per GAP-004/GAP-008 behavior (no clause numbers, no grades).

## PDF-1 — LG Chem (reference)

- Exact path: `기업보고서/배터리 에너지/LGChem_Sustainability_Report_2025_KOR.pdf`
- SHA256: `c6395dd2be7948d85fa2b52c6edb61367fa6610c6f389c2478b44cb4cfcb5bde` (matches
  `evidence/e-scope-case-review.md`; `sha256sum` re-verified this run)
- Physical pages: 119. Structure: OVERVIEW + E/S/G narrative + ESG DATA + APPENDIX.

| Range (physical) | Banner / heading (verbatim head) | Role |
|---|---|---|
| 1–15 | OVERVIEW (`CEO 메시지`, `회사 소개`, `중요성 평가`, `Metrics and Targets` p15) | Out of scope (note p15 E summary table — see ambiguity A1) |
| 16–49 [TEXT-OBSERVED] | ENVIRONMENT. p16 `LG화학은 기후변화가 사업 전반에 미치는 영향… 2050년 Net-Zero`; p24 `온실가스 감축 전략` (2030 carbon-neutral-growth, 2019 baseline 951만 tCO₂e); p27 `Risk Management / 온실가스·에너지 관리`; p29 `Metrics and Targets / 온실가스 배출량 / Scope 1·2 배출량 단위 2023 2024 2025`; p30 `Scope 3 배출량`; p32 순환경제 전환; p36 환경영향 저감; p45 자연자본 (TNFD); p49 잘피 차트 (ENVIRONMENT banner) | CLAIM TARGET E narrative |
| 50–77 [TEXT-OBSERVED; coordinator corrected] | SOCIAL from p50 (`사람의 안전이 모든 일의 최우선… EH&S`); p60 공급망; coordinator observed p77 SOCIAL and p78 GOVERNANCE | S narrative (evidence only via appendix; narrative itself out of claim scope) |
| 78–96 [TEXT-OBSERVED; coordinator corrected] | GOVERNANCE from p78 (책임경영); p80 `이사회 전문성`; p90 윤리규범; p96 `조세 전략` (GOVERNANCE banner); p97 banner flips to ESG DATA | G narrative |
| 97–102 [TEXT-OBSERVED] | ESG DATA / ENVIRONMENT: p97 `온실가스` (Scope 1·2 table, mirrors p29), p98 `Scope 3 배출량` (mirrors p30), p99 에너지, p100 대기오염물질, p101 수자원, p102 폐기물 | EVIDENCE (environmental data) |
| 103–106 [TEXT-OBSERVED] | ESG DATA / SOCIAL: p103 안전보건, p104 임직원, p105 이직 현황, p106 공급망 | EVIDENCE (ALL ESG DATA incl. S) |
| 107–108 [TEXT-OBSERVED] | ESG DATA / GOVERNANCE + 경제: p107 윤리·공정거래, p108 `경제적 성과 / 매출액` (financial, banner still ESG DATA) | EVIDENCE (ALL ESG DATA incl. G + financial) |
| 109–110 [TEXT-OBSERVED] | ESG DATA / `Glossary` (`ABS Acrylonitrile Butadiene Styrene …`) | EVIDENCE (glossary lives under ESG DATA banner, not APPENDIX) |
| 111–114 [TEXT-OBSERVED] | APPENDIX / `GRI 대조표` (`GRI 표준 부합 보고 방식(In accordance with)… 2025-01-01–12-31`; 2-1…305-1…) | EVIDENCE (GRI index) |
| 115–116 [TEXT-OBSERVED] | APPENDIX / `SASB 대조표` (`RT-CH-110a.1 … 5,142,284 tCO₂e, 97%`) | EVIDENCE (SASB) |
| 117–119 [TEXT-OBSERVED START / END = EOF] | APPENDIX / `로이드인증원 검증 의견서` (ISAE 3000 + ISAE 3410, 제한적 보증; p118–119 자격·독립성 ISO 14065/17021·ISQC1·IESBA; doc ends p119) | EVIDENCE (assurance) |

Claim target: **p16–49**. Evidence: **p16–49 + p97–119 (all of ESG DATA and APPENDIX)**.
Consistent with `evidence/e-scope-case-review.md` (E narrative 16–49, env data 97–102, SOCIAL data
103–, GOVERNANCE data 107–, GRI 111, SASB 115, ASSURANCE 117).

Ambiguity: (A1) p15 OVERVIEW `Metrics and Targets` E summary (탄소중립 성장, Scope 3 제3자 검증
언급) is E-relevant but outside the ENVIRONMENT banner — CANDIDATE exclusion from claim target,
flag for coordinator. (A2) Glossary under ESG DATA banner (not APPENDIX) — evidence either way,
but auto-detectors keyed on `APPENDIX` banner would miss p109–110. (A3) p108 financial table under
ESG DATA — include per ALL-ESG-DATA scope, do not treat as E evidence. (A4) Coordinator corrected SOCIAL/GOVERNANCE boundary to p77→78 by direct extraction and rendering; the worker initial p80 start was incorrect.

## PDF-2 — Samsung Electronics (differently structured: division-split E, Facts & Figures, TCFD, no glossary)

- Exact path: `기업보고서/반도체 전자/Samsung_Electronics_Sustainability_Report_2025_KOR.pdf`
- SHA256: `342a99a14d7c32b4e66cbbf977cc89dc79044ccc7c5e71367fb476c14538c8c5`
- Physical pages: 87 (p87 zero-length text extract — blank/unreadable-by-text, CANDIDATE back cover).
  Structure: Our Company / Planet(DX+DS) / People / Principle / Facts & Figures / Appendix.

| Range (physical) | Banner / heading (verbatim head) | Role |
|---|---|---|
| 1–9 | Our Company (p1 cover; p2 INDEX; p3–9 CEO·회사소개·지배구조·중대성·이해관계자) | Out of scope |
| 10 [TEXT-OBSERVED divider] | `Planet / 더 나은 세상… / 추진체계와 주요성과 / 기후변화 / 자원순환 / 수자원 / 오염물질 / DS부문… 11/12/16/18/20/21/22/27/29/32` — section ToC, no claims | EVIDENCE-EXCLUDED divider (CANDIDATE exclusion from claim target) |
| 11–20 [TEXT-OBSERVED] | Planet DX부문: p11 `추진체계와 주요성과 / Governance` (新환경경영전략); p12–13 리스크·시나리오; p14 `온실가스 직접 배출 감축` (2030 탄소중립); p15 RE100/PPA; p16 자원순환; p17 폐기물 매립제로; p18–19 수자원; p20 `오염물질 / Pollution` DX | CLAIM TARGET (E, DX) |
| 21–33 [TEXT-OBSERVED] | Planet DS부문: p21 `추진체계와 주요성과` DS (board/ESG경영협의회); p22 `기후변화` (2050 탄소중립 Scope 1,2); p23 재무영향·회복력; p24–26 온실가스/Scope 3; p27 자원순환 (99.9% 재활용률); p28 재이용; p29–30 수자원; p31 생물다양성 (LEAP); p32–33 오염물질 (2040 자연상태 수준) | CLAIM TARGET (E, DS) |
| 34–57 [TEXT-OBSERVED via dividers p34/p61] | People (p34 divider lists 임직원35/공급망45/사회공헌51/개인정보53/제품품질55; sampled p35,41–50,53–57 match) | S narrative (evidence only via appendix) |
| 58–60 [TEXT-OBSERVED] | Principle (p58 divider `준법과 윤리경영 59`; p59–60 준법·제보) | G narrative |
| 61 [TEXT-OBSERVED divider] | `Facts & Figures / 경제성과 / 사회성과 / 환경성과 / 사업부문별 환경성과 / 62/63/68/72` | Divider |
| 62 [TEXT-OBSERVED] | 경제성과 (매출액·영업이익 2022–2024, K-IFRS 연결) | EVIDENCE (ALL data incl. financial) |
| 63–67 [TEXT-OBSERVED] | 사회성과 (준법·임직원·DEI·교육·책임광물) | EVIDENCE (S data) |
| 68–71 [TEXT-OBSERVED] | 환경성과: p68 `온실가스 관리(Scope 1, 2)` 시장기반/지역기반 이중보고; p69 제품에너지·재생플라스틱; p70–71 수자원 | EVIDENCE (environmental data) |
| 72–74 [TEXT-OBSERVED] | 사업부문별 환경성과 DX/DS split (p72 온실가스, p73 에너지/자원, p74 수자원; p74 last data page) | EVIDENCE (divisional E data) |
| 75 [TEXT-OBSERVED divider] | `독립된 인증인의 인증보고서 / Scope 1, 2 … / Scope 3 … / GRI Index / TCFD 대조표 / SASB 대조표 / About This Report / 76/77/78/80/82/84/86 / Appendix` | Divider (self-map matches observed pages) |
| 76 [HEADING TEXT-OBSERVED / BODY CANDIDATE] | `독립된 인증인의 인증보고서` — heading only via text extract (likely scan/image) | EVIDENCE (assurance; needs vision confirm) |
| 77 [HEADING TEXT-OBSERVED / BODY CANDIDATE] | `Scope 1, 2 온실가스 배출량 검증 의견서` — heading only | EVIDENCE (assurance) |
| 78–79 [TEXT-OBSERVED headings] | `Scope 3 온실가스 배출량 검증 의견서` (2 pages) | EVIDENCE (assurance) |
| 80–81 [TEXT-OBSERVED] | `GRI Index` (GRI 200 경제 201-1/201-2…, GRI 300 환경 304-1…) | EVIDENCE (GRI) |
| 82–83 [TEXT-OBSERVED] | `TCFD 권고안 상세 답변` (거버넌스/전략/시나리오) — LG has no TCFD section | EVIDENCE (TCFD) |
| 84–85 [TEXT-OBSERVED] | SASB (`TC-HW-230a.1`, `TC-SC-110a.1 … P.68, P.72`) — hardware+semiconductor codes | EVIDENCE (SASB) |
| 86 [TEXT-OBSERVED] | `About This Report` (GRI 2021, UN SDGs, TCFD, SASB 반영; 보고범위 33개 생산거점; K-IFRS 연결) | EVIDENCE (methodology/boundary) |

Claim target: **p11–33** (p10 divider CANDIDATE-excluded). Evidence: **p11–33 + p61/62–86
(all Facts & Figures and Appendix)**.
Structural differences vs LG: (1) E narrative split by division DX/DS with duplicated
topic order; (2) data section named Facts & Figures with economy-first order and DX/DS-split
E tables; (3) TCFD appendix instead of glossary — **no glossary heading found in the worker scan (absence unverified)**; (4) three
assurance artifacts (인증보고서 + Scope 1,2 + Scope 3) vs LG single LRQA opinion;
(5) methodology lives at end (About This Report p86) not front (LG ABOUT THIS REPORT p4).

Ambiguity: (B1) p76–77 bodies unreadable via text extraction — assurance coverage/level/period
unknown, needs vision path per ch.27. (B2) p87 blank — CANDIDATE empty back cover; doc-end
assurance completeness depends on p78–79 + p86, not p87. (B3) GRI/SASB page refs (e.g. `P.68`)
are printed-label refs — resolution to physical pages needs printed↔physical map (offset-0
CANDIDATE).

## PDF-3 — KB Financial Group KSSB report (differently structured: standard-based, no ESG DATA section)

- Exact path: `기업보고서/은행 보험 증권/2025 KB금융그룹 지속가능경영보고서-KSSB 지속가능성 공시기준 적용.pdf`
- SHA256: `498e5db603e72bd488d0fbaf0cedaa122ef29e16e63da903f6d88a2086b35a8a`
- Physical pages: 112 (p1 image-only garbled extract = cover CANDIDATE; p112 zero-length =
  blank CANDIDATE). Structure: 개요 / 지속가능성 이슈 5 topics (KSSB 4-pillar order) / Appendix.
  No separate ESG DATA, GRI Index or glossary heading found in the scan (absence unverified); observed data tables are inline in narrative.

| Range (physical) | Banner / heading (verbatim head) | Role |
|---|---|---|
| 1–2 [PART CANDIDATE] | p1 cover (image); p2 `보고서 개요` (3-report system: KSSB 공시 / 데이터 이용자 / 이해관계자) | Out of scope (p2 framing only) |
| 3–16 | 개요: p3 KSSB 1·2호 + 5 topics 선정; p4 추정·판단; p5 `목차`; p6 데이터 거버넌스; p7–9 지속가능성 거버넌스; p10 재무중대성; p11–16 리스크 관리 | Out of scope (note p6 methodology — A5) |
| 17–64 [START CANDIDATE p17 / TEXT-OBSERVED p18–64] | 기후위기 대응 (E): p17 Investor-headlines 전환금융 intro (has 기후 tab); p18 거버넌스; p20–21 전략/기회; p22–27 사업모형·가치사슬; p28 전환계획 (SBTi Near-term 승인 2021-10); p29–41 재무영향·시나리오(NGFS/RCP)·회복력; p42–43 위험관리/ESRM; p44–46 측정접근법·Scope 1&2 (연결실체, KSSB 2호); p47–59 Scope 3 + PCAF 금융배출량 (은행/보험/GICS/국채, 2024/2025); p60–61 회복력·내부탄소가격 (NGFS GCAM); p62–64 목표 (`KB Net Zero S.T.A.R.`, SBTi 제3자 검증 p64) | CLAIM TARGET (E) |
| 65–73 [TEXT-OBSERVED] | 금융소비자보호 (S): p65 Investor-headlines divider; p66–68 거버넌스/CCO; p69–70 위험·전략; p71–73 프로세스·SASB활용·모니터링 | S narrative |
| 74–82 [TEXT-OBSERVED] | 정보보호: p74 관리체계 (CISO/CPO, 레드팀/블루팀); p75–80 위원회·대응 프로세스; p81–82 SASB활용·모니터링 | S narrative |
| 83–88 [TEXT-OBSERVED] | 디지털 혁신 및 기술: p83 미래전략부문/AX; p84–88 협의체·리스크·AI윤리·모니터링 | S/G narrative |
| 89–91 [TEXT-OBSERVED] | Appendix `KSSB 지속가능성 공시기준 제2호 Index` (문단번호→페이지, e.g. Scope 1→46) — replaces GRI Index | EVIDENCE (standard index) |
| 92–106 [TEXT-OBSERVED] | Appendix `SASB Index` finance codes (FN-CB/CF/IB/AC/IN: 데이터보안, 금융배출량, 대출관행, 다양성, 직무윤리…; 15 pages) | EVIDENCE (SASB, E+S+G mixed) |
| 107–108 [TEXT-OBSERVED] | Appendix `제3자 검증의견서` (KMR, 2025-12-31 year, 2026-06-24; 검증방법 p108) | EVIDENCE (assurance) |
| 109–111 [TEXT-OBSERVED] | Appendix `온실가스 배출량 검증의견서` (Scope 3 검증 수행; 리스크분석·현장검증; 종합의견 “적정”; 책임한계 명시) | EVIDENCE (GHG assurance) |

Claim target: **p17–64** (p17 CANDIDATE-included: has 기후위기 대응 tab + 전환금융 intro but
Investor-headlines divider character; coordinator to confirm include/exclude).
Evidence: **p17–64 + p89–111 (ALL Appendix)** — there is no separate ESG DATA section; E data
tables (Scope 1&2 p46, Scope 3/PCAF p47–59) sit inside the claim-target range itself.
Structural differences vs LG/SEC: (1) KSSB 4-pillar order (거버넌스→전략→위험관리→지표및목표)
inside the E topic instead of activity narratives; (2) financed-emissions (Scope 3 Cat.15/PCAF)
as the dominant E tables; (3) KSSB Index replaces GRI; (4) two KMR opinions incl. standalone
Scope 3 GHG opinion; (5) page header carries full tab path on every page (useful banner signal,
noisy for extraction).

Ambiguity: (C1) p17 include/exclude (above). (C2) E/S boundary p64→p65 TEXT-OBSERVED by divider;
S/S boundaries p73→p74, p82→p83 TEXT-OBSERVED by topic heads. (C3) Glossary not found in the worker scan; keep unknown, not established absence. (C4) p1/p112 image/blank —
no content claims depend on them. (C5) SASB p92–106 mixes E+S+G codes; include ALL per scope,
do not pre-sort. (C6) KSSB Index page refs are printed labels (offset-0 CANDIDATE).

## Cross-report notes for coordinator

1. Banner vocabularies differ (`ESG DATA` vs `Facts & Figures` vs none) — banner-keyed
   auto-detection needs per-report maps; LG glossary-under-ESG-DATA and SEC p10/p61/p75
   dividers are the known traps.
2. Data granularity differs (LG global/국내/해외; SEC market/location dual + DX/DS split;
   KB 연결실체 + PCAF asset-class/GICS/country) — boundary map only; no binding inferred.
3. Assurance topology differs (LG 1 opinion p117–119; SEC 3 artifacts p76–79 with p76–77
   vision-needed; KB KMR pair p107–111 with explicit Scope 3 opinion) — period/metric/boundary
   matching is coordinator work, not done here.
4. Printed↔physical offset-0 held on all samples but is CANDIDATE document-wide; GRI/SASB/KSSB
   index page refs must not be treated as physical pages without the map (ch.27 §3).
5. Nothing in this file is a grade, label, verification, or gold annotation (ch.31 gaps preserved).

## Reproduce (read-only, no new dependencies)

```sh
.venv/bin/python -c "import pypdf; print(len(pypdf.PdfReader('기업보고서/배터리 에너지/LGChem_Sustainability_Report_2025_KOR.pdf').pages))"
sha256sum '기업보고서/배터리 에너지/LGChem_Sustainability_Report_2025_KOR.pdf' '기업보고서/반도체 전자/Samsung_Electronics_Sustainability_Report_2025_KOR.pdf' '기업보고서/은행 보험 증권/2025 KB금융그룹 지속가능경영보고서-KSSB 지속가능성 공시기준 적용.pdf'
```

No git changes made; only this file written. No paid product-model calls or secrets access. Coding-agent inference used the authorized OpenCode provider.

Coordinator integration note: TEXT-OBSERVED tags are navigation/text observations only, never canonical source_quality=verified or human gold. Divider pages remain included in broad candidate scopes; claim extraction determines whether their text asserts anything. Blank-text pages remain unknown/unreadable, not excluded by assumption.
