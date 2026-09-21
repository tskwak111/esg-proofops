# Service readiness implementation plan

> **현재 개발 계획:** [전체 파이프라인 완성 개발 계획](32_PIPELINE_COMPLETION_PLAN.md).
> 아래 내용은 진단·실행 이력이다. 다음 개발의 순서와 완료 기준은 새 계획을 따른다.
> 과거의 "next/remaining/active priorities" 문구를 현재 우선순위로 사용하지 않는다.

Goal: make the existing E-claim evidence-review workflow usable with real PDFs
and measured model output, without treating unverified extraction as substantiation.
User authorized autonomous implementation, evaluation and external API comparison
on 2026-09-12, then extended the cumulative Upstage test budget to USD 20.
Existing unsettled reservations remain charged; domain gaps stay gated.
Spec: 00_MASTER_SPEC.md, 27_PARSING_AND_PROVENANCE.md,
28_RULE_ENGINE_CONTRACT.md, 31_DOMAIN_IMPLEMENTATION_GAPS.md and original v2.

## 파이프라인 재평가 — 2026-09-20

사용자 요청에 따라 실제 실행 기록·현재 호출 경로·관련 연구를 검토했다.
아래는 **진단과 수정 방향**이며 대체 파서 비교나 런타임 변경을 완료했다는 뜻이 아니다.
이 절의 개발 우선순위가 아래의 과거 "다음 수정" 순서보다 우선한다.

### 판단과 관찰 근거

문서 → 주장 → 근거 → 태깅 → Python 규칙이라는 큰 구조는 유지한다.
현재의 조기 차단, 입력 문맥, 검증 단위와 개발 우선순위는 수정해야 한다.
최신 롯데 3쪽 부분 실행은 후보12개 중 원문 검증 보류11개, 선행 분류 미합의1개,
태깅 게시0개다. 이는 downstream 모델 정확도0%가 아니라 대부분 분석 전에
중단됐다는 관찰이다. ROOT `outputs/scope-flow-20260920/RESULTS.md` 참조.

| 확인한 병목 | 코드/관찰 | 수정 방향 |
|---|---|---|
| 주장 인용보다 큰 문단 박스로 원문 승인 | `adapters/local/claim_source_verification.py::_read_paragraph`; 이전 롯데 보류10건은 이웃 제목이 문단 박스에 걸리는 `clipped_or_rotated_words` | 주장에 해당하는 원문 span/행 좌표 복구를 비교. epsilon 확대 금지 |
| 원문 미승인 또는 선행 분류 미합의면 검색도 중단 | `apps/worker/.../tag_runner.py`의 두 조기 `continue` | 위치가 추적되는 후보의 탐색/검토와 최종 근거 채택 분리. 미검증을 present로 승격하지 않음 |
| 선행 분류 객체 전체의 3회 일치 요구 | `live_tagging.py::_source_replicas`; goal 일치, safe-harbor만 null/null/forward_looking | 합의된 필드는 후보 탐색에 사용하고 충돌 필드는 보류. 판정에 영향을 주면 최종 등급 보류 유지 |
| 필요한 주변 문맥이 모델 입력에서 빠짐 | `upstage_extraction.py`의 블록 입력, `application/tagging/preliminary.py`의 인용문만 전달 | 원문 인용과 별도로 절 제목·인접 문단·표 제목을 출처와 함께 공급 |
| 제한된 시연을 전수 분석으로 확장하지 못함 | `scripts/analyze_report.py` 추출 기본8회; 문단 우선순위 후 제한 선택 | 기존 체크포인트로 범위별 처리·미처리 내역 관리. 비용 한도를 유지하며 재개 가능한 전수 처리 |
| 근거 검색 성능을 따로 확인하지 못함 | 로컬 BM25 연결됨; 현재 보류 대부분은 검색 이전 | 정답 근거가 top-K에 들어오는지 먼저 측정. 표 행/열 제목·단위·주석 보존. 필요할 때만 검색기 교체 |

후보 탐색 허용은 검증된 근거 인정과 다르다. 출처를 전혀 특정할 수 없는 후보는
계속 보류한다. 변경 시 원문 무결성·테넌트·비용 가드, 동일 evidence packet에 대한
최종 태깅 3회, 규칙엔진 판정 원칙은 유지한다. 미정 도메인 기준은 새로 발명하지 않는다.

### 다음 개발의 작은 의사결정 실험

1. 기존 보고서에서 서로 다른 레이아웃의 5개 기업, 약20쪽, 주장/근거30~50쌍을
   먼저 고정한다. 이는 제안 규모이며 아직 평가 결과가 아니다. 3개 기업 개발,
   2개 기업은 이번 수정에서 제외하고 평가한다. 과거 사용한 기업을 완전 미관측으로 부르지 않는다.
2. 같은 입력으로 현행 파서와 대체 파서 **하나**를 비교한다. 기존 Upstage Parse
   어댑터 또는 설치 버전에서 가능한 OpenDataLoader hybrid를 우선 재사용한다.
   일부 페이지의 사람이 확인한 전사/좌표도 별도 진단 입력으로 사용해 파서 문제와
   검증기 문제를 구분한다. 기존 production verified 기록을 조작하지 않는다.
3. 동일 모델·문맥·범위를 유지해 파서 차이를 먼저 비교한다. 확인된 원문으로도
   추출이 실패하면 문맥 묶음을 수정한다. 확인된 주장/근거를 줘도 태깅이 실패하면
   그 단계의 프롬프트·합의 처리·모델을 비교한다. 한 번에 모든 변수를 바꾸지 않는다.
4. 주장 precision/recall, 실제 인용 위치 정확성, 정답 근거 Recall@K,
   연도·단위·대상 귀속 오류, 검토 가능한 결과 비율, 보류 원인, 비용·시간을 기록한다.
   전수 처리 여부도 별도로 표시한다. 통과 테스트 수나 단순 승인율은 정확도가 아니다.
5. 같은 레이아웃에서 무관한 숫자/이웃 문구를 잘못 승인하지 않으면서 평가 기업의
   올바른 연결이 늘어나는 방법만 채택한다. 임시 AI 라벨은 silver이며 독립 gold나
   서비스 정확도 근거로 쓰지 않는다. 필요한 도메인 승인과 B 통합은 계속 별도 관리한다.

개발 완료 단위는 "함수 수정+검사 통과"가 아니라 고정 입력에서 사용자가 확인할
주장·근거·보류 이유·판정 가능 결과의 변화다. 관련 검사는 한 번 수행하고, 전체 검사는
통합 시점에 한다. 에이전트에도 이 결과와 수정 경계를 지정한다. 실제 커버리지가
늘지 않는 미세 수정·재검증을 반복한 것은 조정자의 우선순위 설정 문제이기도 하다.

### 참고한 1차 자료와 적용 범위

- [Claimify / ACL 2025](https://aclanthology.org/2025.acl-long.348/):
  주장 추출의 문맥·모호성·독립적 이해 가능성을 참고한다. 한국어 ESG PDF 실증은
  아니며, 재서술한 문장을 원문 인용으로 바꾸지 않는다.
- [FEVEROUS](https://aclanthology.org/2021.fever-1.1/) 및
  [Structured Evidence Extraction](https://aclanthology.org/2023.emnlp-main.409/):
  문장과 표를 결합한 근거 탐색, 표→행/열→셀 선택을 참고한다. 해당 데이터셋의
  판정 라벨·성능을 우리 도메인에 그대로 이식하지 않는다.
- [Docling](https://arxiv.org/abs/2408.09869),
  [OpenDataLoader](https://github.com/opendataloader-project/opendataloader-pdf):
  레이아웃·표 구조와 선택적 hybrid 파싱을 비교 후보로 삼는다. upstream 기능이
  설치 버전에 모두 있다고 가정하지 않으며 한국어 ESG 우위는 아직 미측정이다.
- [ALCE](https://arxiv.org/abs/2305.14627): 인용을 출력했다는 사실과 그 인용이
  내용을 뒷받침하는지를 구분해 평가하는 접근을 참고한다.
- [기존 ESG 연구 코드](https://github.com/tskwak111/esg-evidence-audit):
  주장별 허용 문맥과 EvidenceBundle을 재사용 검토한다. README의 과거 gold는
  개발 silver로 재분류되어 있어 독립 검증이 끝난 완제품으로 취급하지 않는다.

## 전체 연결 상태 — 2026-09-20

아래는 실제 실행과 현재 코드 기준이며, 과거 일지의 "아직 연결 전" 설명보다
우선한다. 코드 구현 여부와 실보고서 품질/승인은 구분한다.

| 구간 | 현재 확인된 상태 | 남은 일 |
|---|---|---|
| 새 PDF 업로드 → 파싱 | KB·롯데의 실제 로컬 실행, 원본/좌표/불변 산출물 보존 | 다양한 레이아웃의 표·문단 경계 복구 |
| E 주장 추출 | 실제 Upstage 호출·원문 인용 저장·명시적 본문/근거 범위 분리 | 자동 섹션 선택 연결, 짧은 도표 문구와 복합 주장 품질 |
| 본문·데이터·부록 검색 | 실제 태깅 워커에 BM25·GRI 탐색 연결 | 후보를 해당 주장·지표·연도·범위의 검증된 근거로 채택하는 커버리지 |
| 태깅 → 규칙엔진 | 실제 선행 분류·요소 태깅 게시, Python 규칙엔진 존재 | 원문 검증 실패 해소와 승인 규칙집 적용; 미승인 등급은 보류 |
| 검토·출력 | 실제 HTTP/브라우저 목록·상세·부분 ZIP 확인 | 미게시 태그의 보류 사유 표시, 승인 후 수정·재판정 실증 |
| 보증·수치 분석 | 구조화·매칭·저장·재생 및 수치 분석 코드 연결 | 자동 필드/수치 귀속 생산, 원문 검증된 입력과 출력 연계 |
| 개발자 B 연계·정답 | 반환 파일 구조 검사 존재 | B의 실제 C1–C4 결과, 전문가 기준·크로스워크·루브릭·독립 gold 수령/통합 |

최근 롯데 부분 실행(물리25·117·138쪽)은 주장11개, 태깅 게시1개였다.
저장된 태깅 checkpoint에서 나머지10개는 모두 `SOURCE_VALIDATION_REQUIRED`다.
이를 "근거 없음"이나 모델 정확도10/11로 해석하지 않는다. 전체 보고서 자동
완주·일반화된 정확도·공개 서비스 운영은 아직 입증되지 않았다.

### 본문/근거 범위 분리 결과

`analyze_report.command --pages 25,117,138 --claim-pages 25 ...`로 주장 추출만
본문에 한정할 수 있다. 같은 세 페이지의 새 롯데 실행에서 데이터·부록 주장은
3→0개, 본문 후보는8→12개였으며 그래프에는 세 페이지가 모두 남았다.
새 태깅 게시는0개(원문 검증 보류11, 선행 태깅 미합의1)라 전체 품질 개선을
주장하지 않는다. 미합의1개는 goal 트랙은 일치하지만 세이프하버 분류가 달랐다.

기존 실행 재생은 실제 HTTP 목록·상세200으로 확인했다. 새 실행 역시 부분
ZIP 출력까지 완료했다. 승인 규칙집/등급과 원문 검증 조건은 바꾸지 않았다.
기존 p25 보류 사례의 글자 좌표를 대조해 문단 경계에 이웃 제목이 걸리는
4~7pt 수준의 차이를 확인했다. 다음은 허용오차 확대가 아닌 문단·주장 좌표
복구를 우선한다. 근거: ROOT `outputs/scope-flow-20260920/RESULTS.md`.

## Header-role safety — 2026-09-20

Fixed dropped subheader semantics in automatic normalization: unsupported shared
period columns / explicit spanned header tiers now remain unresolved. Explicit
bindings also reject omitted text tiers while permitting preceding numeric data
rows. Scope2 basis support retained; no new role/grade/API/DB fields. This is a
safety correction, not complete target/actual extraction. Coordinator corrected
an overbroad draft rejection and removed expanded occupancy allocation.
Final related acceptance/numeric/source-review API: 224 passed, Ruff/mypy passed.
Patch-heldout KEPCO/Samsung Life (16 tables, frozen saved parse graphs): obs 0→0,
layout unresolved 16→16. No target/actual pattern present; no measured real-report
accuracy improvement. KEPCO header-role recognition and Samsung parser alignment
remain bigger extraction blockers. Next prioritize structural table recovery;
keep disclosed evaluation companies separate from the next evaluation split.
ROOT outputs/header-role-20260920/RESULTS.md. No model/AWS/new PDF parse calls.

## Generalization check — 2026-09-20

Production `normalize_tables` now supports explicit headers below full-width title
cells, including multi-row titles and shifted coordinate origins. Title text is
retained as provenance, never inferred into metric/unit/scope. No company/page
exceptions or evidence-admission relaxations. Existing no-title observation IDs
remain unchanged. Focused normalization/numeric tests: 213 passed; API/numeric
integration: 19 passed; changed-code Ruff/mypy passed.

Development used synthetic structures. Independent patch-level evaluation froze
Kia/KB/NAVER selected-page saved parser receipts (5 tables); these reports have
been used historically, so this is not globally unseen gold. Baseline extraction
is zero on all five tables, with unrelated unresolved headers. A title-only fix
cannot establish generalized extraction accuracy here. Keep this limitation
visible and prioritize structural header/role extraction, retaining original
cells and source verification, over company-specific header aliases.
Evidence: ROOT outputs/generalization-20260920/ (offline, no new model calls).

## Active priorities — 2026-09-20 integration follow-up

Implemented: source-revalidated immutable assurance publication/replay now reaches
API detail/list through real composition; executable numeric analysis consumes
frozen runs and explicit typed bindings; exact pinned historical verifier replay
restores KB; developer-B return files have a structural CLI gate in ROOT handoff/v3.
KB actual replay: 6 claims, 28 verified blocks, 2 verified claim bindings,
10 external candidates, 4 claims unresolved. No product model calls.
Numeric HMM/LG: 89/0 observations respectively; no bindings supplied, no findings.

Correction: table verification is ALREADY wired inside OpenDataLoaderParser
parse/load_verified via ParserProfile.table_source_policy_sha256. The earlier
metadata-fixed comparison had it disabled. A duplicate checkpoint overlay was
removed. Existing header-after-full-width-title candidate preparation improved;
actual report-level table/binding coverage still needs measurement with matching
new-run configuration. Do not append new overlays to old immutable snapshots.

Remaining order: (1) source-verified table normalization + actual claim binding,
(2) automatic assurance field producer and trusted claim scope, multiple opinion
revisions/export, (3) numeric binding producer + review/output integration,
(4) B C1–C4 actual returns and source-verified bridge, (5) reviewed domain
registry/crosswalk/rubric/gold. Approval and semantic roles are not invented.

Validation: coordinator core48, API/contracts/security63, staging gate29, root
return validator9 passed; Ruff/mypy10files/architecture passed; all Python
packages built with frozen verifier assets. Browser/new model/AWS/gold accuracy
not_run. Evidence: ROOT outputs/pipeline-integration-20260920/RESULTS.md.

## Historical priorities — 2026-09-20 first review


Whole-flow review found source-verified claim spans blocked by whole-paragraph
quality gates in retrieval/binding. Three Kiro tasks fixed exact external-span
admission, span-aware binding, and explicit per-claim needs_review reasons.
Frozen HMM/LG replay: 6 verified literal claim references now accepted (previously
0); 5 unverified claims remain undetermined. External evidence candidates remain
0. This measures source attribution, not substantiation or grade accuracy.
No new model calls. Existing receipts and source quality remain unchanged.

Next implementation order:
1. Increase usable source-verified table/row coverage in the actual automatic
   claim path; measure appendix evidence retrieval, preserving scope/units/notes.
2. Wire existing assurance extraction into storage and per-claim review/export;
   claims router and analysis_store still call match_assurance(None, ...).
3. Wire numeric consistency checks after typed entity/period/boundary binding;
   exposing normalized observations alone is not a numeric check.
4. Restore explicit versioned checkpoint replay: KB is currently rejected by
   changed native paragraph verifier hashes. Never bypass hash verification.
5. Integrate B C1–C4 outputs and reviewed domain registry/crosswalk/rubric/gold.
   Domain approval stays required; synthetic labels are development aids only.

Validation: 275 of 276 targeted tests passed initially; the added coordinator
assert read the wrong envelope level and was corrected to per-claim record,
then its full file passed (4 tests). Contracts/security/Python E2E gate 74 passed;
unit 183 passed/7 skipped; Ruff/basic mypy passed; proofops wheel/sdist built.
Additional check-untyped-defs exposes existing Optional errors at tag_runner
152/188, unresolved. Browser E2E/web build/new model/AWS/grade accuracy not_run.
No API/DB/schema/dependency changes. Rollback restores prior runtime logic for
new work; published receipts/revisions remain immutable.
Coordinator evidence: root outputs/system-priority-20260920/RESULTS.md and
comparison.json. Overall service readiness is not established.

## Historical priorities — 2026-09-19


Jev is deferred until after the existing-model service workflow is complete and
account access is available. No Jev dependency, key, paid experiment or SDK is
required for the work below. Preserve full v2.2 + reconciliation scope; do not
invent clauses, thresholds or legal applicability while waiting for domain data.
The user-authorized cumulative external-model ceiling is USD20 (not the older
USD10 references below); reconcile committed and unsettled ledger entries before
any further calls. This checkpoint made no external model calls.

| Order | Work / owner | Done when | Dependency |
|---|---|---|---|
| 1 | A: GRI candidate routing | Index rows direct retrieval to source-checked page candidates; unresolved labels retain lexical search | Existing parser/source graph |
| 2 | A: assurance extraction and wiring | Opinion fields with exact source spans flow into per-claim coverage and review/export instead of `match_assurance(None, ...)` | Extraction can proceed; approved grade effects require domain rules |
| 3 | A + data: criteria and crosswalk | Reviewed official versions/clauses/mappings load into existing rulepacks; missing criteria remain blocked | Data person supplies v3.1 registry, crosswalk and boundary examples |
| 4 | A: end-to-end claim workflow | E body + environmental data + appendix produce evidence, tags, deterministic grade or explicit hold, source preview and immutable review/export | 1–3; existing source/numeric gates retained |
| 5 | B + A: C1–C4 integration | B outputs with entity/period/boundary/provenance persist and display separately from G/P/M | B v3 package implementation; A can use contract fixtures first |
| 6 | A + data: acceptance | Independent company labels measure omissions, false support and grade errors; browser/export/recovery/security checks pass | Reviewed gold + integrated workflow |

User coordination: send B the v3 package, send data person v3.1 ZIP + work guide,
and collect early deliveries (criteria availability, 5–10 mappings, 5 claims,
open questions). No need to wait for a complete gold corpus to implement 1–2.
Reconcile v2.2 requirements with legacy v2.0 contracts per the handoff source
reconciliation record; changing the version name alone does not approve rules.

### First implemented slice: GRI runtime wiring

`LocalTagRunner` now builds a same-document GRI index and selects candidate
indicator codes by existing local BM25 against index rows. It passes entries and
codes to `retrieve_evidence`; it does not infer standards applicability. Selected
pages constrain both index rows and page targets. Retrieval still verifies the
index SourceRef and each target source; GRI cannot authorize present or global
numeric evidence. Ordinary lexical search continues when mappings are missing.

Page-label candidates come from the hash-checked original PDF: explicit
`/PageLabels`, supplemented by a unique 1–3 digit number in the outer 15% of the
upper/lower 10% page margin. Zero padding is normalized. Conflicting metadata or
multiple margin numbers leave the page unresolved. This is a navigation heuristic,
not visual verification of printed labels. Scans, central page numbers and complex
margins remain unsupported. Legacy NativeSource page labels are not trusted here:
pypdf may synthesize physical numbers when `/PageLabels` is absent. Five original
reports were inspected and all lacked that metadata; metadata-only routing is
therefore insufficient. No report-level retrieval improvement is claimed yet.

Compatibility: no public API/DB/schema migration. Newly assembled live packets
record `local-lexical-gri-v1:<input_hash>` in existing index_generation and preserve
existing GRI coverage fields. Historical frozen packets, revisions and reports are
not rewritten. Rollback restores the prior worker search composition for new work;
already published packets/receipts remain retained. No new library was installed.

Validation: 58 tests passed across local GRI, live tagging pipeline (fake HTTP),
local tagging, GRI parsing and retrieval; Ruff and mypy passed for changed code.
Real Jev/Upstage, full report evaluation, AWS, browser and release build: not_run
for this slice. This is runtime wiring, not overall service completion.

## Working approach

Keep source provenance, numeric checks and pure Python rules. Compare existing
local parsing against an external parser on identical selected pages before
changing parser defaults. Integrate real extraction with the existing review UI;
unknown source quality and unresolved semantics must be visible, never synthetic
success. Reuse existing storage and budget ledger, avoid new services/dependencies.
Public deployment and approval-dependent domain decisions remain separate gates.

## Execution waves

- [ ] Parser comparison: add bounded Upstage Document Parse transport beside the
  existing text probe. Reserve each call in the same SQLite ledger, no retries,
  fail closed on incomplete usage/receipt, preserve raw responses and page maps.
  Verify duplicate IDs, budget exhaustion, bad page count and malformed receipts
  with failing-first tests. Use at most ten pages per request and an initial
  3-report / 3-page-per-report sample; compare standard and enhanced modes within
  the remaining budget. Record time, price, table value-year-unit and source
  location findings. Development review is not human-approved benchmark gold.
- [x] Real extraction integration: trace synthetic composition gates, reuse the
  structured extractor and real transport, add explicit opt-in configuration,
  immutable receipts and source-bound candidate review. Verify upload-to-review
  with a real report, plus model errors, budget stops and source-quality blocks.
- [ ] Evidence connection: evaluate candidate retrieval and structured table/claim
  dimensions across multiple reports; choose local/API stages using observed
  omissions and attribution errors. Preserve source-quality gates and null grades
  until their inputs are accepted. No arbitrary domain thresholds or unit repairs.
- [ ] Product acceptance: run lint/type/unit/integration/contract/build/security
  and browser workflows, including failure/retry/review conflicts and exported
  source links. Keep a release checklist separating observed results, unmeasured
  metrics and approval/deployment blockers. Do not claim production readiness
  from passing code tests or a small development sample.

Coordinator owns shared integration, Git and evidence. Orca workers have explicit
file ownership. No push, deployment or budget increase is implied by this plan.

## Current official parser inputs

Checked 2026-09-12: https://www.upstage.ai/pricing/api lists Document Parse
standard USD 0.01/page, enhanced USD 0.03/page, excluding 10% VAT. Nine pages in
both modes would reserve an estimated USD 0.396 in settled usage. Ambiguous or
failed calls retain the existing USD 1 per-call reservation.
https://console.upstage.ai/api/parse/document-parsing specifies multipart POST
to /v1/document-digitization, usage.pages and per-mode page lists, normalized
element coordinates and mode selection. Enhanced is supported from
document-parse-260128. Store actual returned model version; never infer quality
approval from provider branding or agreement with another extraction engine.

Compatibility: evaluation adapter additions do not alter API/DB schema or prior
receipts. Rollback disables the new opt-in transport and preserves its artifacts.
Any later runtime contract/migration change must be recorded before implementation.

## Checkpoint 2026-09-12

Parser comparison wave implemented and exercised (five successful calls and one
429 retained reservation); findings are in `evidence/parser-extraction-comparison.md`.
Real extractor adapter is implemented with source-exact validation and shared
budget. Fixed Unicode-escaped model input; same-source development probes moved
from 0/3 valid responses to 3/3. This completes the adapter slice, not the full
API/worker/UI integration wave. Model-output errors preserve unknown; budget and
rate-limit conditions stop instead of iterating through remaining blocks.

Next executable slice: define explicit local real-extraction runtime/usage contract
and bounded block scheduling, then wire candidate review without synthetic tags.
Do not mount an Upstage transport under a synthetic consent/runtime binding.
Remaining API/DB compatibility, processing bindings and browser gates must be
resolved before claiming upload-to-real-review service readiness. Public release
is blocked, not approved by these development measurements.

## Local integration checkpoint (2026-09-12)

See `evidence/local-upstage-service-pilot.md`: actual upload/extraction/browser path
and USD10 accounting verified with 24 calls. Matched-packet prompt improvement is
development evidence only. Next: stable bounded paragraph selection, independent
extraction validation, then E + ESG DATA + APPENDIX evidence integration. Existing
UUID-based discovery order must not be mistaken for a repeatable sampling strategy.

## Cross-report checkpoint (2026-09-12)

Stable bounded paragraph selection and section navigation repairs are implemented.
Five additional companies were exercised: four original parses succeeded; one
original with automatic Print was rejected. Same-source prompt and standard/enhanced
API comparisons are archived in `evidence/cross-report-service-evaluation.md`.
The experimental prompt was not promoted because results were mixed. Next execute
existing parent-context/sentence pilots against frozen multi-company inputs, then
source-reviewed evidence attribution. Independent gold, numeric table validation
and release acceptance remain open; do not treat page coverage as accuracy.

## Model comparison contract — 2026-09-13 KST

The context/selection experiments on five frozen company samples did not justify
changing runtime defaults. Compare Solar Pro 4 using the same Upstage endpoint,
key and **existing** cumulative USD10 ledger. Official API example specifies
`solar-pro4` at `https://api.upstage.ai/v1`, with `reasoning_effort=medium`.
The provider's read-only `/v1/models` response additionally confirms exact version
`solar-pro4-260806` (archived `.local/context-loop/provider-models.json`).
Sources checked 2026-09-12 UTC: https://www.upstage.ai/blog/en/solar-pro-4 and
https://www.upstage.ai/pricing/api. Reserve undiscounted USD0.30 input / USD1.20
output per million tokens plus10%VAT; do not assume promotional eligibility.

Compatibility: default Pro3 behavior/price and stored budget policy remain unchanged;
explicit alternative calls record their own model/price snapshot in existing receipts.
No database migration, ledger reset, API/DTO change, runtime consent substitution or
source-quality promotion. The Pro3 frozen extractor rejects an explicitly Pro4
transport until a separately pinned runtime profile is implemented and tested.
Rollback disables alternative probes and preserves every paid receipt/reservation.

Pro4 canary correction: medium reasoning exhausted a 4096-token output budget with
no final answer and another request timed out. Both reservations remain unknown.
The official chat guide (https://console.upstage.ai/docs/capabilities/generate/chat)
states Pro4 reasoning is off by default. The bounded extraction probe now omits
reasoning_effort; compare at the same 1024-token cap as the Pro3 baseline. This is a
new explicit configuration experiment, never an automatic retry of the failed calls.

Source-fidelity correction (2026-09-13 KST): exact substrings can still remove part
of a word (observed `지분투자` → `투자`). New claim validation rejects boundaries
inside contiguous alphanumeric tokens; it never auto-expands or rewrites the quote.
The Upstage rule descriptor changes for new extraction profiles. Existing revisions,
receipts and recorded experiment results remain immutable. No API/DB shape change;
rollback restores the prior validator/profile code without rewriting prior results.

## Context/model loop checkpoint (2026-09-13 KST)

Five-company context and model experiments plus15 new E pages completed. Pro4
can now run only under an explicit matching local profile; defaults stayPro3.
Real Kia/NAVER upload/extract/API trials passed, but still produced untagged
candidates and one unstable numeric-table selection. See
`evidence/context-loop-verification.md`; automatic service readiness is not met.
Next address table reconstruction/evidence separation before broader live tagging.

## External table candidate contract (2026-09-13 KST)

Three original-page standard/enhanced comparisons recovered table structure that
local parsing split into headers and paragraphs. Implemented evaluation-only HTML
cell parsing and a converter into existing CandidateBatch/NativeSource types.
All table elements are eligible; never use company/metric-name whitelists. Preserve
merged row/column spans and exact decoded cell text; no semantic header approval.
Rebuild the requested PDF subset from original bytes and physical-page mapping,
then verify its request hash and the archived raw-response hash before conversion.
Only unrotated, full-origin MediaBox=CropBox geometry is supported initially; reject
other geometry instead of approximating. Table rectangles use actual provider
normalized coordinates. Cells have no bbox because the provider supplies none.
Use a fresh parse manifest; do not mutate stored local graphs or fuse mismatched
manifests. Standard/enhanced share one parser family, not independent votes.
No network, new dependency, API/DB shape change, runtime promotion, source-quality
approval or numeric acceptance is granted by conversion. Rollback removes this
opt-in evaluator and preserves every source/response artifact.

Six final-code offline replays retained five unique tables/81 cells, with no cell
locations or numeric observations. See `evidence/table-recovery-verification.md`.

## Sentence/table context loop — 2026-09-13 KST

New Upstage profiles opt into paired-quotation truncation checks; legacy snapshot
replay retains its old validator behavior. This is a source-fragment guard, not
assertion/grammar approval. Table evaluator versions5–8 preserve merged spans,
own-row identity, stable header aliases, source row order and target-only prompts.
No API/DB schema change or source-quality promotion. Rollback disables the new
extractor profile/evaluator and preserves old snapshots and paid receipts.
Four real five-table configurations passed3/5,5/5,3/5,5/5 structural checks;
semantic quality is still unmeasured. See `evidence/service-loop-verification.md`.
Actual Upstage element-tagging service composition remains engineering work; do
not describe its absence as solely a human/domain-approval blocker.

## Semantic evaluation checkpoint — 2026-09-13 KST

Thirty real paragraph calls across five development companies and a Kiro
source-only review reproduced whole-response loss from one rewritten quote.
New profiles retain exact siblings; rejected and uncovered text stay unknown.
Offline replay changed only one paragraph; this is not independent accuracy
evidence. Table-role vocabulary lacks numeric/header roles and remains a
model-proposed diagnostic, with source coordinates unverified. Prioritize held-out
company/source review, quantitative/header binding, mixed-cell context and the
actual tagger composition before service claims. See
`evidence/semantic-review-verification.md`.

## 근거 연결의 누락된 경계 태그 차단 — 2026-09-19

Jev 개발 실험의 연결/별도 기준 혼동을 계기로 `accept_binding`을 확인했다.
명시된 역할의 값 불일치는 기존에도 차단했지만, 주장과 후보에서 `boundary` 또는
`scope` 역할을 모두 생략하면 교차 출처 근거를 accepted로 반환하는 경로를 재현했다.
`Scope 1 & 2`를 `Scope 1`로만 태깅해도 같은 문제가 있었다.

공통 함수에서 주장 원문과 후보가 포함된 canonical 블록의 명시적 연결/별도·Scope
표현이 출처를 가진 역할 태그에 포함됐는지 확인한다. 누락/축약은 undetermined이며
새로운 역할, present, absent 또는 등급을 만들지 않는다. 올바른 역할이 제공되면
기존 출처/기간/기업/지표/표 좌표 검사를 거치고, 명시적 불일치는 rejected다.
태깅 서비스와 사람 검토가 같은 함수를 사용하므로 별도 허용 경로를 만들지 않았다.

범위: 제한된 한국어/영어 명시 표현의 누락 방지다. 전체 의미 추출이나 조직경계
동의어 판별의 완성은 아니다. 후보 블록에 여러 문맥이 섞여 있으면 보수적으로
검토가 늘 수 있다. 원자 주장 내부의 직접 인용과 기존 허용 전역 근거 경로는 유지한다.

검증 기록:
- 수정 전 새 회귀 사례: 5 failed, 1 passed. 5개 실패 모두 accepted가 잘못 반환됨.
- `.venv/bin/python -m pytest tests/acceptance/test_binding.py tests/acceptance/test_tagging.py -q`: 133 passed.
- `.venv/bin/python -m pytest tests/acceptance/test_reviews.py tests/acceptance/test_relations.py tests/acceptance/test_table_bindings.py tests/integration/test_live_relation_worker.py tests/integration/test_live_tagging_worker.py -q`: 91 passed, 기존 의존성 deprecation 경고 2개.
- 변경 Python 3개 파일 `ruff check`: passed. `binding.py` mypy: passed.
- 명시 경계 정상 연결, 허용 전역 범위/방법/검증, 누락된 Scope에 대한 모델 3회 present의
  guarded unknown 전환과 원시 응답 보존을 확인했다. 테스트의 모델과 출처는 합성 fixture다.
- 이번 수정 후 새로운 실제 모델 호출·다기업 PDF E2E·AWS 시험: not_run. 기존 Jev
  109문항 일치율을 이번 수정의 성능 개선 수치로 재사용하지 않는다.

API/DB/규칙팩 및 등급 사다리 변경 없음. 기존 저장 revision과 원시 응답은 수정하지
않는다. 새 실행/검토의 귀속 검사에 적용된다. 롤백은 binding.py의 추가 누락 가드를
되돌리는 코드 변경이며 과거 결과를 덮어쓰지 않는다. 모델 비교와 독립 보고서
품질 평가는 이 기술 누락 경로 수정과 별도 잔여 작업이다.

## 세 보고서 동일 입력 모델 비교 및 Scope 표기 보완 — 2026-09-19

삼성SDI·HMM·LG생활건강에서 실제 조합 16 + 통제 변조 8쌍을 원문 페이지와
대조하고 호출 전 가라벨을 고정했다. 미정 3쌍은 점수에서 제외했다. Solar Pro 3와
OpenRouter Jev 각각 24회 실제 호출: 가라벨 일치 8/21 vs 13/21, 잘못된 완전 지지
6/14 vs 0/14, 정상 근거의 낮은 분류 0/7 vs 3/7. 전문가 gold 및 실제 전체
pipeline 성능은 아니다. 입력은 수동 구조화된 표/본문이며 3회 태깅을 대체하지 않는다.

합산 사용/추정 비용 $0.003038859(추가 한도 $0.10). 이전 다섯 Jev 평가 회사와
겹치지 않지만 프로젝트 전체의 독립 holdout은 아니다. 정답에 맞춘 사후 라벨 변경
및 추가 프롬프트 재호출 없음. Jev 운영 승격은 보류하고 관계 분류 보조 실험만 유지한다.
근거 삭제/자동 승인/등급 계산을 Jev에 위임하지 않는다. 미정 수치/범위 및 관계
정책은 도메인 검토 파일에 정리했다.

원문에 등장하는 Scope 1+2 / Scope 1·2의 축약 태깅이 기존 누락 가드를 통과하는
문제도 재현하여 공통 정규식에 +, · 구분자를 추가했다. 수정 전 2 failed/2 passed;
binding/tagging/reviews 171 passed; ruff와 binding mypy 및 diff check passed.
완전한 역할의 허용 경로 유지, API/DB/규칙 계약 변경 없음. 회귀 graph는 합성 fixture;
새 PDF 전체 파이프라인 E2E, 전체 build/보안/클라우드 시험은 not_run.

실험 기록: 작업 루트 `outputs/jev-three-report-comparison-20260919/RESULTS.md`,
`DOMAIN_REVIEW.md`, 동결 cases/manifest, 제공자별 요청/응답 및 comparison.csv.
로컬 실행 코드: `.local/jev-three-report-comparison/`; `run.py --check`는 무료 오프라인
예산·payload·라벨 비노출 검사다. 기존 리뷰 revision/원시 응답/보고서는 변경하지 않았다.

## 실제 앱 경로의 근거 packet 평가 — 2026-09-19

`outputs/pipeline-packet-eval-20260919/REPORT.md`에 실제 업로드→파싱→Solar 추출→
불변 claim/graph 재생→서비스 검색/packet 함수를 실행한 결과를 보존했다. HMM
p36/112/124: 7개 주장 중 원문 확인 4개, LG생활건강 p32/122/142: 4개 중 2개.
6개 candidate packet 모두 자기 주장 인용만 포함하며 교차 출처 채택은 0개다.
나머지 5개는 blocked_evidence. 이는 전체 정확도나 전체 보고서 근거 부재가 아니다.

삼성SDI는 원본 /GoToR 외부 PDF 이동 동작 때문에 업로드 PDF_INVALID로 차단됐다.
원본/보안 정책을 변경하거나 우회하지 않았다. 실제 graph에는 HMM 14개 및
LG생활건강 8개 table 블록이 있지만 원문 품질/귀속 미확정으로 채택되지 않았다.
Jev 비교를 진행할 독립 근거 packet이 없어 추가 관계 모델 호출은 하지 않았다.
표 원문·셀 좌표·헤더·각주를 검증하여 packet으로 연결하는 작업이 우선이다.

평가 스크립트의 초기 발간연도 추정을 PDF 제목 2025로 수정하고 새 run으로
재실행했다. 초기 기록은 보존했고 그 비용까지 포함해 이번 추출 총 8회,
$0.001781835(토큰 단가+VAT 여유분). 앞선 비교 포함 $0.004820694 < $0.10.
프로덕션 코드/규칙 변경 없음. 3회 태깅/등급/전체 E2E와 새 Jev 비교는 not_run;
모델 성능 개선 또는 서비스 완료를 주장하지 않는다. 도메인 미정 라벨은 그대로다.

## 작은 직사각형 표 원문 검증 연결 — 2026-09-19

로컬 parser profile의 opt-in table_source_policy_sha256 / pilot --verify-tables로
native 문자+렌더링 Apple Vision 셀 검증 receipt를 발행하고 load_verified에서도
원본과 재생한다. 표 밖 단위/각주/의미 귀속과 등급은 승인하지 않는다. 기존
manifest hash는 옵션 미설정 시 유지하며 새 정책 hash 불일치는 차단한다.

실제 최종 HMM p36/112/124는 14 table 중 1개(내부탄소가격 6셀) 원문 검증 통과,
LG생활건강 p32/122/142는 8개 모두 미확정이다. 최종 자연어 주장 4+4개 중
원문 확인 4+2개이나 자동 packet의 별도 출처 후보는 여전히 0개다. 별도의 실제
표 행 선택 시험에서는 행/표/연도 헤더 3개 후보가 전달됐지만 6개 셀 묶음이 기존
크기 제한에 걸려 blocked_evidence다. 해당 시험은 모델 추출/정확도 집계에서 제외했다.

새 회귀 11, 관련 parsing/retrieval/numeric 192, unit/contract/security/staging gate
100 tests passed. 변경 파일 lint/typecheck/diff 및 web build passed. 실제 전체
브라우저 E2E·3회 태깅·최종 등급·AWS not_run. 합성 테스트는 실제 정확도가 아니다.
추가 Solar 6회 비용 $0.001276605, 비교 실험 누적 $0.006097299 / $0.10.
초기 LG 파싱 오류 및 HMM 중간 실행을 포함하며 기존 기록은 보존했다.

원문/기계 지표/한계: 작업 루트 `outputs/table-admission-20260919/RESULTS.md`.
다음 병목은 병합/다단 헤더 복구와 셀 인용의 중복으로 인한 packet 크기 초과다.
서비스 완료나 자동 근거 연결 개선을 주장하지 않는다.

## 표 근거 packet 중복 제거 — 2026-09-19

이미 포함된 동일 SourceRef 문맥을 packet 안에서 재사용하여 HMM의 고정 표 행
선택 시험은 후보 3→9, 크기 제외 6→0, blocked_evidence→candidate가 됐다.
자동 추출 주장의 별도 출처 후보는 HMM/LG 모두 여전히 0개다. 등급 규칙과
크기 제한은 변경하지 않았다. 원문 이미지 기반 silver 10개는 전문가 gold가 아니다.

pdfplumber 표 복구 에이전트 초안은 실제 입력에서 개선이 없고 좌표 처리도
부적절해 제외했다. LG 헤더 오류는 OpenDataLoader 후보에서 발생하며 별도로
해결해야 한다. 초안 제거 후 관련 회귀 14 passed, lint/typecheck/diff 통과.
추가 유료 모델 호출 0회; 전체 E2E/최종 판정/AWS not_run.
상세 기록: 작업 루트 outputs/table-packet-improvement-20260919/RESULTS.md.

## ODL 헤더·첫 데이터 행 분리 — 2026-09-19

실제 오류가 발생한 ODL 후보에 opt-in `odl_header_v1`을 연결했다. 원시 JSON은
불변 보존하고, native 단어와 일치하며 행 사이 간격이 명확할 때만 새 구조를
발행한다. 모호한 표는 변경하지 않는다. 새 manifest의 load_verified 재생을 확인했다.

LG p32 1개 표, HMM p124 2개 표에서 총 40개 분리 셀을 PDF 좌표 crop과 비교해
문자가 일치했다. HMM p36은 그대로다. 이는 개발용 관찰이며 독립 gold 평가가 아니다.
LG p122 복합 구조와 병합 단위 셀 검증/자동 근거 연결은 아직 남아 있다.
추가 유료 파이프라인 API 호출 0회. 관련 파싱/표/재생 테스트 89 passed,
계약·보안·staging gate 74 passed, lint/typecheck/web build 통과.
브라우저 전체 E2E·최종 태깅/등급·AWS는 not_run.
상세: 작업 루트 outputs/odl-header-repair-20260919/RESULTS.md.

## 병합 표 원문 검증 연결 — 2026-09-19

Kiro 비대화형 worker가 실제 코딩/검사/Orca 완료 보고까지 수행했다. 새로운
병합 표 검증 정책과 행 좌표 보완, 부모 표가 다른 셀의 잘못된 fusion을 수정했다.
LG p32 에너지 표는 26셀 모두 native+렌더링 OCR 검증을 통과해 표/행 포함 33블록이
verified가 됐다(이전 LG 표 0개). HMM은 기존 1표/9블록 통과를 유지했다.

LG 표 행 선택 probe는 근거 후보 12개가 담겼지만 21개가 제외되어 blocked_evidence다.
자동 모델 추출 주장에 대한 교차 근거 연결/최종 등급 개선은 측정하지 않았다.
다음 병목은 전체 표 후보 확장 대신 관련 행·연도 헤더·병합 단위의 필요한 문맥을
명시적으로 묶어 기존 packet 한도 안에서 완전하게 전달하는 것이다.

관련 파싱·검증·재생 73 passed, 계약/보안/staging gate 74 passed, 변경 lint/typecheck
및 web build 통과. 실제 전체 브라우저 E2E/새 모델 태깅·등급/AWS는 not_run.
추가 유료 파이프라인 모델 호출 0회(코딩 에이전트 구독 사용량과 구분).
상세 기록: 작업 루트 outputs/merged-table-20260919/RESULTS.md.
