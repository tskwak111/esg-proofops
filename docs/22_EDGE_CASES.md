# 22 · 경계 사례·실패 시나리오

> ESG ProofOps · 개발 명세 1.0 · 2026-09-08
> 도메인 정본: `sources/PROJECT_DOMAIN_V2_ORIGINAL.md` (원문 2.0, 2026-09-07).

## 처리 원칙
아래 사례는 입력/상태/기대 동작을 고정하는 수용계약이다. 합성 fixture 만으로 실제 PDF/클라우드 통과를 주장하지 않는다. 기계 판독 정본은 `fixtures/edge_cases.json`이다. 각 실패는13장의 error code/부분 완료 규약을 따른다.

| Fixture | 상황 | 백엔드 처리·기대 | 프론트엔드 | 테스트 단언 |
|---|---|---|---|---|
| FX-GRAPH-001 | 동일영역 A1/B1과 B2→B1 | canonical A1 보존, B2→A1, 모든출처유지 | 상태·부분 완료·재시도/비활성사유표시 | dangling edge 수0 |
| FX-GRAPH-002 | 다른영역 동일문자 합계 | 둘다 보존 | 상태·부분 완료·재시도/비활성사유표시 | block 수2 |
| FX-LOC-001 | bbox 없음 | bbox null, unlocated, 자동인정불가 | 원문/후보를 나란히, 결손과 판독실패 분리 | 0,0,0,0 가짜하이라이트없음 |
| FX-LOC-002 | 회전90도/CropBox 이동 | affine 변환 후 원문영역왕복 | 원문/후보를 나란히, 결손과 판독실패 분리 | crop 내 bbox 및 역변환오차<0.5pt |
| FX-LOC-003 | NFD 한국어/공백정규화 | 원문 offset map 로 quote 검증 | 원문/후보를 나란히, 결손과 판독실패 분리 | 정규문자열 offset 을 rawoffset 으로오인하지않음 |
| FX-TABLE-001 | 연도열순서2024/2023 뒤바뀜 | 값을 header 에따라각연도귀속 | 원문/후보를 나란히, 결손과 판독실패 분리 | 연도값 swap 없음 |
| FX-TABLE-002 | 동일 metric 시장기반/위치기반 | 별도 measurement_basis | 원문/후보를 나란히, 결손과 판독실패 분리 | 중복으로삭제하지않음 |
| FX-TABLE-003 | 표합계1,234 vsvision1,284 | conflict review | 원문/후보를 나란히, 결손과 판독실패 분리 | 큰값/다수결자동선택없음 |
| FX-NUM-001 | 전년0 현재10 | rate not_computable | 상태·부분 완료·재시도/비활성사유표시 | inf/100%생성없음 |
| FX-NUM-002 | dash 또는빈칸 | missing not0 | 상태·부분 완료·재시도/비활성사유표시 | 합계검산허위일치없음 |
| FX-NUM-003 | 표104.95 표시105.0 | 표시정밀도구간으로비교 | 상태·부분 완료·재시도/비활성사유표시 | 임의5%오차허용없음 |
| FX-RAG-001 | 다른기업동일문장검색 hit | tenant/docversion 필터로거부 | 원문/후보를 나란히, 결손과 판독실패 분리 | accepted0 |
| FX-RAG-002 | 같은문서다른표목표연도 | global 숫자인정거부 | 원문/후보를 나란히, 결손과 판독실패 분리 | G1present 승격없음 |
| FX-ASSURE-001 | 보증기관존재/대상 year 다름 | not_covered 또는정보부족시 undetermined | 원문/후보를 나란히, 결손과 판독실패 분리 | covered 금지 |
| FX-CACHE-001 | replicate1캐시만존재 | 2/3은 cachemiss | 상태·부분 완료·재시도/비활성사유표시 | 독립 requestsignature3개 |
| FX-REVIEW-001 | 동일 review 두명동시확정 | 한명200 다른412 | draft 보존+최신변경 diff | 태깅/감사/head 원자 |
| FX-JOB-001 | workerA lease 후죽음 workerB 재시도 | fence 상승 A 늦은 publish 거부 | 상태·부분 완료·재시도/비활성사유표시 | 최종포인터 B 만 |
| FX-JOB-002 | SQS 같은메시지2회 | jobdedupe | 상태·부분 완료·재시도/비활성사유표시 | acceptedartifact1개 |
| FX-EXPORT-001 | snapshot 중 review 변경 | epoch 불일치로다시캡처 | 상태·부분 완료·재시도/비활성사유표시 | 혼합 revision0 |
| FX-BUDGET-001 | 입력 token 예산100% | partial,미분석수표시 | 상태·부분 완료·재시도/비활성사유표시 | 전수완료배지없음 |
| FX-GRI-001 | GRI 인쇄 p28이 PDFp31 | 페이지매핑검증후조회 | 원문/후보를 나란히, 결손과 판독실패 분리 | 물리28로맹목점프금지 |
| FX-YEAR-001 | 전년 PDF 없음 | not_run | 상태·부분 완료·재시도/비활성사유표시 | 목표후퇴단정없음 |
| FX-INJECT-001 | PDF 에이전트를무시하고 labelE3지시 | 문서데이터로취급 | 상태·부분 완료·재시도/비활성사유표시 | 등급출력스키마/권한불변 |
| FX-DELETE-001 | 삭제후 PITR 복구 | tombstone 재적용 | 상태·부분 완료·재시도/비활성사유표시 | 원문노출없음 |


## 추가 경계
기업명 동음/법인구조 변경은 company_id 와 consolidation metadata 를 사람이 확인한다. 다중 페이지 표는 previous/next table lineage 와 반복 header 가 연결될 때만 합친다. page 의 인쇄번호가 roman/부록번호/없음이면 physical page 를 기본 표시하고 label 은 nullable 다. footnote 의 숫자가 실적값인지 목표값인지 분리하고, 2030년 예상진척을 현재진척으로 인정하지 않는다. 표의 %는 비율과 절대값 단위로 혼용하지 않는다.

공시 본문과 보증의견서가 별첨 파일이면 P0는 같은 승인된 document set 에 합본 또는 별도 source registration 을 구현하기 전 자동으로 묶지 않는다. 현재 P0 API 의 document_version 은 단일 PDF 이므로 사용자는 원문 순서가 보존된 합본을 업로드하고 provenance 에 파일 구성 정보를 기록해야 한다. 이때 합본 bytes 가 검토의 고정 원본이며 원별 source page mapping 은 추가 metadata 로 남긴다. 별첨을 몰래 외부에서 찾아 자동입증에 포함하지 않는다.
