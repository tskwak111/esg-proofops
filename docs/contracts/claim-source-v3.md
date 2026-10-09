# claim-source-v3 (SV1, opt-in)

새 실행에서 `--verify-claim-spans --claim-source-profile claim-source-v3`로 선택한다.
기본 reader, v1/v2, 기존 wrapper의 코드·정책·receipt는 변경하지 않는다.
새 reader는 기존 glyph-alignment-v1 결과를 보존하고 인용별 가시성 가드를 적용한다.
공개 API/DB schema 변경이나 migration, 새 dependency는 없다.

`claim_source_attestation_v3`는 원본 SHA-256, tenant/document/parse/graph,
기존 receipt, reader 코드·dependency 버전, 인용별 판정과 정본 문자열을 기록한다.
기존 정책 envelope에 `profile=claim-source-v3`와 전체 코드 해시를 고정하며,
정확히 일치하지 않는 정책·receipt의 재생은 거절한다.

새로 복구한 record의 `canonical_quote`는 같은 원문 PDF·물리 쪽·bbox에서
PDFium이 읽은 문자열이다. 파서와 공백 외 문자가 하나라도 다르면 복구하지 않는다.
숫자·단위·소수점·퍼센트·부호 인접 공백 차이와 물리 행 사이 공백 변경은 거절한다.
동일 bbox의 로컬 Apple Vision 렌더 읽기에서 정본 인용이 유일하게 일치해야 한다.
OCR의 문장부호·문자 오독은 교정하지 않는다. 216dpi와 고정 6px 패딩만 사용한다.

원래 파서 인용·SourceRef·offset은 불변으로 유지한다. 정본 채택은 이 source
attestation의 검증 문자열이며, 기존 추출 문자열이나 raw_text를 덮어쓰지 않는다.
`normalization`은 parser_quote, native_text, 변경 경계, 정본/파서/native 문자
offset, PDFium 글리프 index·bbox, 렌더 crop hash·문자열을 보존한다.
재생은 확인된 span만 승인하며 문단 전체·태깅·등급을 승인하지 않는다.

주석은 인용 글리프 bbox와 실제 겹침을 검사한다. AP 없는 Link는 가림으로
취급하지 않으며, 겹치는 Widget(외관 없음 포함)/AP는 보류한다. OCG와 XFA는
계속 보류한다. 잘린 글리프·다른 행/쪽 혼입·중복 인용은 복구하지 않는다.

Rollback은 새 실행의 opt-in 선택을 중단하는 것이다. 이미 저장된 v3 receipt는
당시 reader와 함께 보존하며 구 reader로 재해석하지 않는다. 무료 재생은 저장
모델 응답/후보와 원본 PDF를 읽을 뿐 기존 state·revision·보고서를 수정하지 않는다.
모델 합의·태깅 공개까지의 추가 진행은 별도 유료 평가이며 SV1에서는 not_run이다.
