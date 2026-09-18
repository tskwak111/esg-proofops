# Context-loop review (AGENT development review)

Development-only non-blind agent review of 80 frozen target paragraphs for the coordinator context experiment. No human approval, no precision figures, no verified-quality claims, no production grading.

## Provenance

- Reviewer: OpenCode Muse Spark 1.3 Free
- Scope: development_only=true, production_grading=false
- Frozen targets: 20 oldest-baseline outcomes x 4 reports (doosan, kia, kb, kakao)
- Baseline summaries (oldest by mtime):
  - doosan: .local/cross-report-wave/doosan/extract-8d2a075d-d4cf-43cb-a788-8cf377e9c673/summary.json
  - kia: .local/cross-report-wave/kia/extract-c0bdd0e2-a8fc-4b08-81d4-026356520766/summary.json
  - kb: .local/cross-report-wave/kb/extract-caddac76-86a7-439c-aa76-0041745242a4/summary.json
  - kakao: .local/cross-report-wave/kakao/extract-a0507b70-949b-4222-ab11-467f3dfc6e64/summary.json
- Original manifests: per-report .local/cross-report-wave/<report>/selection.json; paragraph graphs: paragraphs.json (same-page neighbors used as surrounding context).
- Method: non-blind agent review. Coordinator observed baseline quotes in the reviewer input before annotation. The worker’s claimed read-first/compare-after sequence is not established. These labels are diagnostic suggestions, not independent gold.

## Decision counts (development labels, not grades)

- doosan: assertion=6 ambiguous=2 nonassertion=12
- kia: assertion=10 ambiguous=2 nonassertion=8
- kb: assertion=6 ambiguous=4 nonassertion=10
- kakao: assertion=2 ambiguous=0 nonassertion=18

## Baseline comparison notes (for coordinator integration; agent view only)

- Clear miss (baseline empty/error, agent assertion): kia f857f020-953e-5094-a1d5-c127e6b5a3c2 (MODEL_SPAN_OR_SCHEMA_INVALID).
- Clear false-positive spans (baseline claim quotes, agent nonassertion/ambiguous): doosan e3df7c39 2nd quote (truncated fragment), doosan f2b13d60 (2 fragment quotes), kia 6ef96ce5 (glossary definition), kia 39d0c6a6, kia 7fec9593 (procedure labels), kb ca0ddb30, kb bb9020ca (generic fragments), kakao 34891203 (3 legend labels).
- Partial coverage: kia 4ae4cd94 baseline omits final commitment sentence included in agent quotes.
- All other targets: agent agrees with baseline span presence/absence (span-count agreement is not a correctness claim).

## Validation

Actual command run: python3 .local/context-loop/review-temp/validate_review.py
Result: PASS — 80 unique baseline source_ids; every target_sha256 matches paragraph hash; every quote exact in target; every reason present; assertion items carry quotes, others carry none.

## Items

| source_id | report | decision | quotes | baseline_note | reason |
|---|---|---|---|---|---|
| 08a85f8b | kakao | assertion | 5 | agree | 서비스 제공·리스크 영향·시나리오 분석 수행·분석 결과·재무영향 추정이 다문장으로 진술됨. |
| 08c475e0 | kia | nonassertion | 0 | agree_no_span | 비전 슬로건으로 검증 가능한 진술이 없음. |
| 09e69b01 | kia | nonassertion | 0 | agree_no_span | 기간 구분 라벨로 명제가 없음. |
| 0c39804c | doosan | nonassertion | 0 | agree_no_span | 목차·머리말 성격의 보고서 탐색 문구로 회사 진술 명제가 없음. |
| 0c413b43 | kb | assertion | 1 | agree | 투자 확대·기술 도입의 구체적 실행 항목을 진술함. |
| 0ee16643 | kb | ambiguous | 0 | agree_no_span:효과 문구에 span 없음은 타당 | 효과 성격의 일반 문구로 독립 명제가 없어 주장 확정이 어려우므로 유보. |
| 0f68744e | doosan | nonassertion | 0 | agree_no_span | 키워드 나열 조각으로 주어·서술어 명제가 없어 회사 주장으로 볼 수 없음. |
| 12ca60b3 | kb | assertion | 2 | agree | ESG 채권 조달과 자금 전액 할당의 2개 완전 문장이 자금 운용을 진술함. |
| 13799942 | kb | nonassertion | 0 | agree_no_span | 단일 명사로 명제가 성립하지 않음. |
| 182124ff | kia | assertion | 1 | agree | 조달 수단이 명시된 재생에너지 조치 항목으로 실행 내용을 진술함. |
| 19b947ac | kakao | assertion | 5 | agree | 프리쿨링 도입·전략 회복탄력성·재해 대비·삼중화 설비의 5개 문장이 대응 조치를 진술함. |
| 1f42a0ef | kb | ambiguous | 0 | agree_no_span:단독 라벨에 span 없음은 타당 | 시스템 고도화 활동 라벨로 표 행 문맥 없이는 주장력이 불확실하므로 유보. |
| 20d12889 | kakao | nonassertion | 0 | agree_no_span | 수치 셀 조각으로 명제가 없음. |
| 217c9f99 | kakao | nonassertion | 0 | agree_no_span | 수치 셀 조각으로 명제가 없음. |
| 25796c77 | doosan | nonassertion | 0 | agree_no_span | 단일 약어 라벨로 명제 내용이 없어 주장으로 볼 수 없음. |
| 28edf712 | doosan | nonassertion | 0 | agree_no_span | 지표 라벨 조각으로 주장 명제가 없음. |
| 2936f9eb | kia | assertion | 1 | agree | 해외·국내 연도가 명시된 정량 목표 항목으로 목표 주장을 진술함. |
| 296c3615 | kakao | nonassertion | 0 | agree_no_span | 수치 셀 조각으로 명제가 없음. |
| 2bf43eed | doosan | nonassertion | 0 | agree_no_span | 가치 슬로건 나열로 검증 가능한 회사 진술이 없음. |
| 323912e1 | kb | nonassertion | 0 | agree_no_span | 단일 명사로 명제가 성립하지 않음. |
| 34891203 | kakao | nonassertion | 0 | baseline_fp:범례 라벨 3개를 주장으로 인용 | 리스크 유형 범례 라벨 나열로 진술 명제가 없어 주장으로 볼 수 없음. |
| 39d0c6a6 | kia | ambiguous | 0 | baseline_fp:절차 라벨을 주장으로 인용 | 절차적 안건 라벨로 구체적 명제가 없어 주장 여부를 확인할 수 없으므로 유보. |
| 3bd85fd0 | doosan | assertion | 1 | agree | 회사 주체의 거버넌스 체계 구축·운영 진술이 완전한 문장으로 서술됨. |
| 41ac6d25 | kakao | nonassertion | 0 | agree_no_span | 절 표제 조각으로 진술 명제가 없음. |
| 4356ffc8 | doosan | nonassertion | 0 | agree_no_span | 조직도 박스 라벨 나열로 서술어가 없어 독립 명제가 아님. |
| 49c63d25 | doosan | assertion | 4 | agree | 운영 주체·감축 목표 이행·모니터링·보고의 4개 완전 문장이 회사 활동을 진술함. |
| 4ae4cd94 | kia | assertion | 7 | baseline_partial:마지막 책임 이행 문장 미인용 | 로드맵 수립·재생에너지 확대·수소 도입·Scope3 감축·상쇄크레딧 확보 등 회사 계획이 다문장으로 진술됨. |
| 4dab68f1 | kb | nonassertion | 0 | agree_no_span | 표 행머리 조각으로 명제가 없음. |
| 4f5a10b8 | doosan | nonassertion | 0 | agree_no_span | 소제목 성격의 항목 라벨로 진술 명제가 없음. |
| 4f6b3e06 | kakao | nonassertion | 0 | agree_no_span | 수치 셀 조각으로 명제가 없음. |
| 6072ff76 | doosan | nonassertion | 0 | agree_no_span | 단일 단어로 명제가 성립하지 않음. |
| 641a18e3 | kia | assertion | 1 | agree | 소재 감축 실행 항목으로 조치 내용을 진술함. |
| 64b1a60b | kia | assertion | 1 | agree | 연도·범위·비율이 명시된 전동화 목표 항목임. |
| 6cfbe9e4 | kb | nonassertion | 0 | agree_no_span | 표 행머리 조각으로 명제가 없음. |
| 6d88f939 | doosan | assertion | 3 | agree | 위원회 분석·관리·보고의 3개 완전 문장이 대응 방향과 감축 추진을 진술함. |
| 6dd003ba | kb | nonassertion | 0 | agree_no_span | 표 행머리 조각으로 명제가 없음. |
| 6e778404 | kakao | nonassertion | 0 | agree_no_span | 단위 표기 조각으로 명제가 없음. |
| 6ef96ce5 | kia | nonassertion | 0 | baseline_fp:용어 정의문을 주장으로 인용 | 일반 용어 정의 각주로 회사 행위 진술이 없어 주장으로 볼 수 없음. |
| 707674c0 | kakao | nonassertion | 0 | agree_no_span | 수치 셀 조각으로 명제가 없음. |
| 71c6e13d | kakao | nonassertion | 0 | agree_no_span | 시나리오 범례 라벨로 명제가 없음. |
| 736ef9b5 | kb | nonassertion | 0 | agree_no_span | 단일 명사로 명제가 성립하지 않음. |
| 7d65506e | kakao | nonassertion | 0 | agree_no_span | 시나리오 범례 라벨로 명제가 없음. |
| 7efa10f8 | kia | nonassertion | 0 | agree_no_span | 기간 구분 라벨로 명제가 없음. |
| 7fec9593 | kia | ambiguous | 0 | baseline_fp:절차 라벨을 주장으로 인용 | 행정 절차 라벨로 명제 내용이 없어 주장 여부를 확인할 수 없으므로 유보. |
| 8595fb7d | kb | nonassertion | 0 | agree_no_span | 분야명 나열로 진술 명제가 없음. |
| 8fee9a80 | kb | nonassertion | 0 | agree_no_span | 목차·표제 성격의 탐색 문구로 회사 진술이 없음. |
| 932fc336 | doosan | assertion | 3 | agree | 모니터링·분석·보고의 3개 완전 문장이 ESG팀 활동을 구체적으로 진술함. |
| 9ae59cf8 | doosan | nonassertion | 0 | agree_no_span | 차트 항목 라벨로 회사 진술 명제가 없음. |
| 9b375cdd | kia | nonassertion | 0 | agree_no_span | 로드맵 단계명 라벨로 명제 진술이 없음. |
| 9fe918f2 | doosan | nonassertion | 0 | agree_no_span | 단일 단어로 명제가 성립하지 않음. |
| a40e00bf | kia | assertion | 1 | agree | 협력사 대응 역량 강화라는 구체적 실행 항목을 진술함. |
| a82626e6 | kakao | nonassertion | 0 | agree_no_span | 수치 셀 조각으로 명제가 없음. |
| a961cff8 | kakao | nonassertion | 0 | agree_no_span | 수치 셀 조각으로 명제가 없음. |
| aae23535 | doosan | nonassertion | 0 | agree_no_span | SDG 번호 라벨 나열로 명제 서술이 없음. |
| ab386c96 | kb | assertion | 1 | agree | 환경 부문 공급 확대 항목으로 실행 내용을 진술함. |
| af0b9e7a | kia | assertion | 1 | agree | 연도·지역·비율이 명시된 전동화 목표 항목임. |
| afbbd5fb | kakao | nonassertion | 0 | agree_no_span | 사업장 약어 풀이 각주로 진술 명제가 없음. |
| b90ec234 | kia | assertion | 1 | agree | 지역·비율이 명시된 전동화 목표 항목으로 목표 주장을 진술함. |
| bb9020ca | kb | ambiguous | 0 | baseline_fp:일반 문구를 주장으로 인용 | 효과 성격의 일반 문구로 주체·서술어 명제가 없어 주장 확정이 어려우므로 유보. |
| c1742a3d | kakao | nonassertion | 0 | agree_no_span | 수치 셀 조각으로 명제가 없음. |
| c263219a | kakao | nonassertion | 0 | agree_no_span | 그래프 주석 조각으로 명제가 없음. |
| c3e0ce1c | kb | assertion | 5 | agree | 시스템 투자·배출량 관리·익스포저 조정·기후금융 추진이 완전 문장으로 진술됨. |
| c3e1ca47 | kia | nonassertion | 0 | agree_no_span | 연도+명사 표제 조각으로 서술어가 없어 주장으로 볼 수 없음. |
| ca0ddb30 | kb | ambiguous | 0 | baseline_fp:일반 문구를 주장으로 인용 | 일반 사업 다각화 문구로 회사 주체 명제가 없어 기후 주장으로 확정할 수 없으므로 유보. |
| cc2c0056 | kakao | nonassertion | 0 | agree_no_span | 수치 셀 조각으로 명제가 없음. |
| ce1c601a | kb | assertion | 2 | agree | 금융상품 확대·포트폴리오 구축의 2개 실행 항목을 진술함. |
| d17b3e86 | kb | assertion | 1 | agree | 투자 행위 항목으로 동일 페이지 투자 문맥에서 실행 내용을 진술함. |
| d8f5bd1b | doosan | nonassertion | 0 | agree_no_span | 단일 조직명 조각으로 주장 명제가 아님. |
| e3df7c39 | doosan | assertion | 1 | baseline_fp:두번째 quote는 절단된 불완전 문장 인용 | 첫 문장은 총괄·방향 설정의 완전한 주장이나 뒷부분이 '지역별'에서 절단되어 불완전함. |
| e4e8114b | doosan | assertion | 1 | agree | 연도·산출물이 명시된 다이어그램 과제 항목으로 동일 페이지 전략 문맥에서 계획 주장으로 읽힘. |
| e738110e | kia | nonassertion | 0 | agree_no_span | 전략 단계 표제로 독립된 진술 명제가 없음. |
| eb990bb4 | kakao | nonassertion | 0 | agree_no_span | 시나리오 범례 라벨로 명제가 없음. |
| ed10a978 | kia | assertion | 1 | agree | 로드맵 문맥에서 자체발전 도입 조치 항목으로 구체적 실행 내용을 진술함. |
| f27112bb | kb | nonassertion | 0 | agree_no_span | 표 구분 라벨로 명제가 없음. |
| f2b13d60 | doosan | ambiguous | 0 | baseline_fp:명사구 2개를 독립 주장처럼 인용 | 앞 문단 절단문의 계속 절편으로 주어가 없어 단독 명제가 불완전하므로 판정 유보. |
| f4953441 | doosan | ambiguous | 0 | agree_no_span:미완성 조각에 span 없음은 타당 | '및'으로 끝나는 절단 항목명으로 완전한 명제를 확인할 수 없어 판정 유보. |
| f583ffaf | kb | nonassertion | 0 | agree_no_span | 단일 명사로 명제가 성립하지 않음. |
| f857f020 | kia | assertion | 3 | baseline_miss:오류 상태로 span 없음 | 선언 이후 추진 실적·2025년 전략 재정비·Scope별 감축 계획이 완전 문장으로 진술됨. |
| f902103e | kakao | nonassertion | 0 | agree_no_span | 수치 셀 조각으로 명제가 없음. |
| fc6f58b3 | kia | nonassertion | 0 | agree_no_span | 목차 성격의 보고서 탐색 문구로 회사 진술이 없음. |

Full quote texts: see evidence/context-loop-review.json expected_claim_quotes.
