# schema1.1에서 v2.2 제품으로 연결할 때 남은 계약

기존 input/policy/output.schema.json은 내부 모듈 계약1.1입니다. 이번 문서 패키지3과 버전 숫자가 다릅니다.
기존 예제는 합성이고 hash는 원본 실재 검증이 아닙니다. 기존 스키마를 변경하지 않았습니다.

## 1. 수집 provenance — 신규 companion 계약
collection_manifest.schema.json과 example-collection-manifest.json을 제공합니다. 이는 B가 구현할 수집 이력 형식이며 현재 앱이 읽는 DTO가 아닙니다.
manifest_id/package_id/synthetic/fetched_at/artifacts[]를 기록합니다.
각 artifact: source_id(입력 sources[].source_id), document_version_id, artifact_sha256, corp_code, fy, rcept_no, consolidation, source_system, fetched_at, locator, status, error_code.
같은 원본의 여러 인용은 서로 다른 source_id와 같은 artifact hash를 가질 수 있습니다.
입력 identity.package_id와 회사/FY/문서버전/해시가 일치하는지 application에서 대조합니다.
각 artifact의 fetched_at은 실제 조회 UTC ISO8601(Z), 최상위 fetched_at은 수집 묶음 완료시각입니다. source_system은 DART 또는 integrated_report. 예제 시각은 합성입니다. 날짜의 실제 유효성은 application에서 표준 datetime으로 검사합니다.
미공시와 timeout/권한실패/항목미제공을 같은 상태로 처리하지 않습니다. 실패 artifact는 hash/locator null, error_code 필수라는 의미 검사를 추가합니다.
지정 source가 원본으로 검증되지 않으면 엔진 확정 입력으로 전달하지 않습니다.

## 2. 원문 출력과 내부 output의 대응
| 원문 요구 | 내부1.1/추가 위치 | 담당 |
|---|---|---|
| claim_id/item/status | 현재 output | B |
| 양쪽 값 | sustainability_value/financial_value | B |
| explanation_location/present | explanation_source_id를 원문 sources에 resolve; 없으면 location null | B 검증/A표시 |
| difference_note/allowed_difference_type | 승인 유형+검증된 설명 기반 presentation 데이터 추가 필요 | B초안/A계약확정 |
| source_ref.system/corp_code/fy/fetched_at | collection manifest를 source_id로 연결 | B |
| basis.standard/clause/text | accounting config의 supplied/unverified/verified 상태와 함께 전달 | B/A |
| confidence | 원문 예시에는 있으나 정의 없음. 측정된 정의 없으면 null/미제공; 가짜0.9 금지 | A+B |
| 기존 label/evidence_grade | 기존 Decision에서 유지. 내부 C output에는 넣지 않음 | A |

출력 필드를 임의로 strict schema1.1에 끼워넣지 않습니다. A/B가 필드와 양·음성 예제를 확정한 다음 versioned projection/새 계약을 만듭니다.
일치 결과에 설명문구가 없을 수 있습니다. explanation_source_id=null을 무조건 설명부족으로 해석하지 않습니다.

## 3. 상태/화면
status는 matched/needs_explanation/not_applicable 세 값. blocked/not_run은 execution_state이며 status=null.
검증된 비적용/미공시와 수집오류·읽기실패·미승인정책을 구분합니다.
needs_explanation 표시: 설명 보완 권장. blocked: 검토 대기. not_run: 미실행.
고정문구: 본 기능은 회계 처리의 적정성을 판단하지 않으며, 공시 간 차이에 대한 설명의 존재 여부만 점검합니다.
원문 quote는 금지어가 있어도 변조하지 않습니다. 생성된 해설만 금지 결론 가드 대상으로 검사합니다.

## 4. 통합 검증
C기능 on/off로 기존 grade/label 동일; 회사/FY/tenant/hash 다른 입력 거부; 검색실패는 설명부재로 변환 금지;
원본 tag/decision revision이 바뀌면 새 packet/result revision; 옛 보고서 불변; 원문 양쪽 링크; C5 차단.
