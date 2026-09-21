# R00 · 정본 대조 결과와 구현 vs 판단 지도

> 2026-09-20. `32_PIPELINE_COMPLETION_PLAN.md` R00 산출물. 범위: 현재 v2.0 구현/계약과
> 사용자가 반영을 요청한 v2.2(`ROOT handoff/team-v3/reference/PROJECT_V2_2.md`,
> `RECONCILIATION_SPEC.md`) 사이의 명시 요구/충돌/진짜 미정을 분리한다. 도메인을 새로
> 기획하지 않으며, `00_MASTER_SPEC.md` §9와 `31_DOMAIN_IMPLEMENTATION_GAPS.md`의
> AI 검토 해석 절을 보충한다. Python/런타임 파일은 수정하지 않았다.

## 1. 이미 명시 요구인 것 (재승인 질문 아님)

`ROOT handoff/team-v3/REQUIREMENT_TRACE.csv`의 G1~G8/P1~P6/M1~M6은 v2.0에서 이미
`config/rubric`+`domain/rules`로 구현 대상이었고 v2.2가 이를 변경하지 않았다. C1~C5는
v2.2 §3.7/4.5/4.10 신설 요구로, `REQUIREMENT_TRACE.csv` C1~C5 행 기준 **B 소유**이며,
A가 접근 가능한 공유 저장소 기준(마지막 확인 commit ff61f41)으로는 계약·예제만 보인다
— 이는 A 쪽에서 본 마지막 공유 상태이고 B의 미공유 진행을 "없음"으로 단정하는 것은
아니다. 이는 GAP이 아니라 소유·최신 상태 확인이 B 쪽에 있는 명시 구현 항목이다.

## 2. 진짜 도메인 미정 (GAP-001~010, 해석 제안은 31장)

31장에 AI 검토 해석(`review_origin=ai_project_interpretation`)을 추가했다. GAP-004/008/009/010은
사실관계·외부확인형이라 이번 해석 대상에서 제외했다. 런타임 `decision_status` enum에
새 값을 넣지 않았다 — 28장 계약은 그대로 `blocked_rule_gap`을 반환한다.

## 3. R02 — 소스 정책 변경의 계약/버전/마이그레이션/롤백

**변경 없음.** 이번 작업은 소스 검증 정책을 바꾸지 않았다. 향후 R02가 정책을 바꿀 때
지켜야 할 경계만 기록한다.

| 항목 | 내용 |
|---|---|
| 대상 계약 | `packages/proofops/adapters/local/claim_source_verification.py`, `source_verification.py`, `table_source_verification.py`; 검증 결과가 28장 `ElementState.present = citation_verified AND binding_accepted`의 입력 |
| 현재 검증기 | `tests/integration/test_frozen_native_replay.py`가 과거 실행을 과거 검증기로 재생하는 계약을 보증 |
| 새 정책 적용 범위 | 새 정책은 새 실행에만 고정. 과거 `claims.py` 전체 파일 hash로 고정된 과거 실행은 과거 검증기로 재생 — 새 정책을 구버전에 강제 통과시키는 방식은 R02 완료 기준 위반(`32_PIPELINE_COMPLETION_PLAN.md` R00 항목 3) |
| Migration | 정책 버전 필드를 검증 결과에 추가하는 것은 additive. 기존 reader가 새 필드를 못 읽으면 명시적 unsupported로 거절(§7.2 원칙), 조용히 무시하지 않음 |
| Rollback | 새 producer(새 검증 로직) 비활성화 + 이전 reader 유지. 기존 검증 결과·revision을 삭제하거나 재작성하지 않음 |
| 확인 명령(정책 변경 시에만) | `tests/integration/test_frozen_native_replay.py` + 변경한 검증 모듈의 기존 unit/integration |

## 4. R04 — candidate-stage 의미와 계약 영향 (정정: 2026-09-20 두 번째 검토)

**정정 사항:** 앞선 초안은 `validate_preliminary`가 이미 미검증 후보를 검색까지 진행시킨다고
잘못 기술했다. 실제 코드를 재확인한 결과는 다음과 같다.

| 개념 | 실제 코드 근거 | 실제 현재 동작 |
|---|---|---|
| 소스 검증 게이트 | `apps/worker/src/proofops_worker/tag_runner.py` `LocalTagRunner._execute` (per-claim loop) | `claim.source_quality != "verified"`이면 `reason="SOURCE_VALIDATION_REQUIRED"`로 즉시 `status="blocked"` 기록 후 **continue** — preliminary 호출, evidence retrieval, tagging 전부 미실행 |
| `validate_preliminary` | `packages/proofops/application/tagging/preliminary.py:177-219` | source_quality 검증 이후에만 호출됨. 호출자 게이트에 더해 내부 `_sources`도 source_quality=verified, tenant/document/manifest/source hash와 인용 검증을 요구한다. 필드 스키마 검증만 하는 함수가 아니다 |
| 확정 귀속 | `packages/proofops/application/evidence/binding.py` (`accept_binding`) | verified span 요구 유지 (변경 없음) |
| 등급 입력 게이트 | `28_RULE_ENGINE_CONTRACT.md` §1: `present = citation_verified AND binding_accepted` | 유지 (변경 없음) |

**결론:** 현재 런타임은 R04가 목표로 하는 "미검증이어도 원문 위치 추적되는 후보는 저비용
검색·검토로 진행"을 아직 구현하지 않았다. 지금은 `source_quality`가 `verified`가 아니면
해당 claim 전체가 preliminary/검색 단계 진입 전에 차단된다. R04는 **확정 검증을 유지한 채 후보 검색을 앞 단계에서 허용하는 것**이 실제 작업이며, "이미 분리돼 있다"는 이전 서술은 오류였다.
아래 계약 영향은 이 변경이 실제로 이뤄질 때 지킬 경계다.

**계약/버전 영향(향후 R04가 이 차단을 검색 이후로 옮길 때)**

- 새 필드는 confirmed 스키마와 별도 버전으로 정의한다. 기존 `ConfirmedTags`/`accept_binding` 입력 스키마에 후보 필드를 끼워 넣지 않는다.
- 후보 packet hash가 바뀌면 새 태깅 revision을 만든다(기존 등급에 재사용 금지, `00_MASTER_SPEC.md` §5.6과 합치).
- 구버전 reader는 새 후보 필드를 모르면 무시가 아니라 명시적으로 "후보 미확정"으로 표시해야 한다 — 확정으로 오인되면 §5.4의 검증 계약(문자열 존재≠근거) 위반.
- Rollback: 후보 필드 producer만 비활성화. 이미 확정된 `accept_binding` 결과는 영향받지 않는다(후보 계층과 확정 계층이 분리돼 있으므로 rollback 범위가 작다).
- 확인 대상(변경 시): `tests/integration/test_local_tag_runner.py`, `tests/acceptance/test_preliminary.py` — 핵심 단언은 "미검증 source가 있으면 확정 grade/present가 생기지 않는다"(계약 불변, 이번에 재확인만 함).

## 5. 이 문서가 하지 않은 것

법령·기준 원문의 조항 번호를 만들지 않았다. 세이프하버의 법적 면책 효과를 판정하지
않았다. C군 상태를 label/evidence_grade에 연결하지 않았다. 어떤 rulepack도 활성화하지
않았다. `decision_status` 런타임 enum을 변경하지 않았다.

## 6. 활성화 게이트 (정정: D 승인 필수 아님)

사용자가 조정자(코디네이터)의 도메인 판단을 원문·사례 근거 기반으로 명시 위임했다.
따라서 31장의 AI 검토 해석은 "D(도메인 담당자) 승인 없이는 전부 보류"가 아니라,
**조정자 채택 + rulepack 버전 기록**이 기술적 활성화 게이트다. 이는 가짜 인간 승인을
만드는 것이 아니라 실제 결정 경로를 문서화하는 것이다 — 채택 시 31장 승인 이력 표에
`담당자=coordinator(AI-delegated)`, `rulepack hash`, `timestamp`, `boundary test vector`를
그대로 기록하고 `review_origin=ai_project_interpretation`을 유지한다(법·회계 전문가
승인으로 위장하지 않음). D의 원문·사례 제공은 여전히 유효하지만, 없다는 이유로 조정자의
채택 자체가 막히지는 않는다.
