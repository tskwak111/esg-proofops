# EV1 · evidence-source-v1 (opt-in)

기존 기본값·native/claim source v1/v2/v3·저장 revision은 변경하지 않는다.
새 근거 검증 어댑터는 `proofops.adapters.local.evidence_source_verification_v1`이다.
통합 프로필·런처·worker 연결은 INT1 소유 파일이므로 EV1에서 변경하지 않았다.

새 실행에서 권한 확인된 원본 graph/PDF bytes와 근거 쪽 목록을 전달한다:

```python
receipt = reader.attest_evidence_sources(
    graph, original_bytes, tenant_id=tenant_id, physical_pages=tuple(evidence_pages)
)
# receipt를 새 불변 artifact로 저장하고, 실행 계약에 reader.policy()를 pin한다.
scoped = reader.replay_evidence_sources(receipt, graph, original_bytes, tenant_id=tenant_id)
```

`scoped`는 기존 `retrieve_evidence`·span citation·binding guard의 입력이다.
재생은 동일 정책·원본 SHA·tenant/document/manifest/graph·쪽 목록을 확인하고
네이티브 글리프와 원문 렌더를 다시 읽는다. 외부 verified flag를 승인하지 않는다.
새 정책에는 adapter/SV1/Q8/OCR 코드 해시와 reader 버전을 보존한다.
API/DB schema·migration·dependency 변경은 없다. 기존 receipt 바이트는 그대로다.

문단은 전체 raw span에 대해 PDFium의 같은 쪽·bbox 문자열/글리프와 216dpi
원문 crop의 Apple Vision CPU 읽기가 일치해야 한다. SV1의 알파벳 사이 공백
정렬만 허용하며 숫자·단위·부호·소수점·% 인접 공백 및 문자 차이는 거절한다.
파서 raw/offset/ref는 유지하고 정본 인용·변경 경계·글리프·crop hash는 proof에 남긴다.
verified는 정확한 span만 추가한다. 문단 quality와 ancestry를 소급 승인하지 않는다.

겹치는 Widget/AP 주석, OCG/XFA, 잘린/다른 글리프, 다른 쪽/행/열 혼입은 보류다.
AP 없는 Link 및 인용 글자를 덮지 않는 Widget는 일괄 보류 사유에서 제외한다.
두 ink 높이보다 큰 가로 간격/불연속 읽기, 인접 가로 선 사이 영역은 표 귀속을
요구한다. 보수적 기하 가드이므로 실제 문단도 보류될 수 있다.
text-column/ruled-row 방식으로 감지한 표 영역과 겹치는 문단도 보류한다.
이 탐지는 거절에만 사용하며 행·열을 추측해 승인하지 않는다. 알파벳/한글 등
문자 16개 미만인 단편은 관계 확인을 요구한다. 이 보수적 프로필에서는 짧은
진짜 문단이나 표 사이 각주도 보류될 수 있으며 기본 reader를 변경하지 않는다.

표는 Q8의 유일한 table/row/cell 관계·같은 쪽·비중첩 행열·명시 column index,
완전한 2×2 이상 unmerged grid와 원문 합성 일치가 필요하다(최대400셀).
머리글을 포함한 모든 셀의 전체 문자열·글리프·가시 crop를 확인한 표만 승인한다.
불명확한 각주/원문 issue는 유지한다. `table_vision_not_run`만 해당 로컬
전체 grid 검증으로 resolved로 남길 수 있다. semantic binding은 undetermined다.
표처럼 평탄화된 문단을 표 셀로 재구성하거나 숫자의 전역 귀속을 인정하지 않는다.

무료 재생의 `citation_ready_element_slots`는 packet의 allowed_elements 슬롯 수다.
해당 요소의 의미 충족·binding accepted·present·보증 covered·등급 회복을 뜻하지 않는다.
새 모델 태깅·합의·public/AWS 경로는 EV1에서 not_run이며 유료 호출은0이다.
rollback은 새 opt-in 배정 중단이다. 새 receipt는 당시 reader와 함께 보존하고
구 reader로 재해석하지 않는다. 기존 실행·원본·태깅·보고서는 덮어쓰지 않는다.
