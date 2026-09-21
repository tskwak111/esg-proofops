# 10 · AI·RAG·태깅 계약

> ESG ProofOps · 개발 명세 1.0 · 2026-09-08
> 도메인 정본: `sources/PROJECT_DOMAIN_V2_ORIGINAL.md` (원문 2.0, 2026-09-07).

## 1. LLM 이 하는 일과 하지 않는 일
LLM 은 atomic claim 후보, track/topic, 표 구조화 후보, G/P/M 요소 존재와 SourceRef, 보증 scope 요소, 수정 문안의 표현을 제안한다. E-grade/label, 산술 검산, 파일 hash, 인용 실재 검증, 법적 효력/면책 여부는 생성하지 않는다. JSON schema 에 grade 나 label 을 넣지 않고 extra field 는 reject 한다. JSON 이 유효하다고 사실이 맞는 것은 아니다.[S09–S10]

## 2. 프롬프트 구성
System prompt 는 역할·출력 스키마·금지 동작만 포함한다. User packet 은 구조화된 claim, source refs, permitted evidence snippets, allowed element catalog, document context 다. PDF 본문은 `untrusted_document_data` 경계로 묶고 system/도구 지시로 승격하지 않는다. 모델에 holdout gold, 인간의 정답 해설, 이전 모델의 최종 grade 를 주지 않는다. `prompts/` 네 파일을 기본 템플릿으로 사용하며 실제 rendered system/user/schema 를 각각 해시한다.

## 3. 처리 순서
(1) source quality 확인 → (2) atomic claim 후보 → (3) preliminary track/요소 요청 → (4) 로컬 근거와 전역 허용 항목 검색 → (5) citation/binding 후보 검증 → (6) EvidencePacket 동결 → (7) 3회 독립 호출 → (8) 각 응답 스키마/출처/귀속/기간 검증 → (9) consensus → (10) RuleEngine.

preliminary extraction 은 검색 query 를 만들기 위한 후보이지 최종 투표가 아니다. RAG 가 새로운 근거를 찾으면 packet hash 가 바뀌고 태깅3회를 새로 수행한다. 일부 replicate 만 다른 packet 을 보는 상태는 허용하지 않는다. 3회 실행의 모델/프롬프트는 같을 수 있으므로 서로 통계적으로 독립이라고 주장하지 않는다. `agreement=3/3`은 관측된 출력 일치이지 정확도/확률이 아니다.

## 4. EvidencePacket
필수 필드: tenant_id, run_id, document_version_id, parse_manifest_id, claim_id, atomic_quote, claim_source_refs, document_context(기업/기간/산업/경계), allowed_elements, evidence_candidates, candidate_bindings, search_coverage, packet_sha256, schema_version. context 크기 초과 시 paragraph/table/footnote 단위로 우선순위 truncate 하고 omitted_source_ids 를 기록한다. 직접 근거가 잘리면 blocked_evidence 이다.

기본 chunk 는 문단·제목경로 기준 목표800tokens/최대1600tokens, 인접 문장 overlap100tokens 다. 표는 row+상위 header+unit+footnote 단위이며 동일 표 id 유지; 행을 토큰 한도로 자를 때 숫자와 연도 header 를 분리하지 않는다. 단위 없는 독립 셀을 retrievable 정량 evidence 로 만들지 않는다. page 경계 문장 결합은 복수 SourceRef 를 유지한다.

## 5. RAG 세부
회수 순서: GRI index candidate pages → 같은 section/table lineage → 문서 전체 lexical top20 + vector top20 → source-id canonical dedupe → RRF(k=60) → 최대12 snippets/총12,000tokens. 한 claim 은 전역 탐색 최대2라운드다. 기본 reranker 는 별도 모델이 아니라 typed binding/기간/경계 검사를 우선 적용한다. reranker 모델 추가는 평가 후 ADR 로 한다.

OpenSearch query 에는 tenant_id, document_version_id, parse_manifest_id, index_generation 필터를 server 가 강제한다. 결과를 받은 후 SourceStore 에서 같은 권한·hash 를 다시 검사한다. 부록 근거라도 적용되는 법인·범위·기간을 연결하지 못하면 `candidate/undetermined`이지 accepted 가 아니다. 숫자·목표연도는 해당 atomic claim 또는 동일 table lineage 에 직접 존재해야 한다. 같은 페이지, 가까운 paragraph 라는 이유만으로 local scope 를 넓히지 않는다.

검색에서 발견 못 한 것과 문서에 없는 것은 다르다. `search_coverage`에 조회한 경로·페이지·제외/미처리 영역·budget/truncation 을 기록한다. 허용된 근거 범위를 충분히 처리하지 못하면 absent 가 아니라 unknown 으로 반환한다. 완전한 부재 증명을 주장하지 않고 “이번 공시 내 검색 범위에서 발견되지 않음”으로 표시한다.

## 6. 3회 합의 규칙
각 replicate 는 호출 전에 request signature 를 만들고 raw/guarded 결과를 각각 보존한다. present 라면서 실재 source 가 없으면 그 요소는 invalid 이며 unknown 으로 canonicalize 한다. 기본 candidate majority 는 세 결과 중 동일 state·동일 normalized value·동일 귀속이2회 이상인 경우다. 서로 다른 인용이라도 같은 사실을 같은 대상/기간/경계에 대해 입증하면 source union 을 저장한다.

**자동 확정은 더 보수적이다.** 세 번 모두 critical track/값/연도/경계/보증 coverage 가 같고, 모든 accepted refs 가 검증되고, parse conflict·규칙 gap 이 없을 때 auto_confirmed 한다. 2:1 결과는 majority 후보를 저장하되 grade-critical 차이면 needs_review 이다. 세 번 모두 다른 state, 모델실패1회, citation failure 는 needs_review 이다. grade 에 무관한 문안 표현 차이는 투표 불일치로 세지 않는다. 이 규칙은 다수결 자체를 버리는 것이 아니라 다수결 결과의 자동 확정 권한을 제한한다.

## 7. 표·이미지와 OCR
표가 있는 모든 대상 페이지의 table crop 또는 페이지를 vision 으로 교차확인한다(원문 §6 1-2 유지). 메인 OD/local extraction, pdfplumber 와 비전이 각자의 raw output/provenance 를 보존한다. 숫자·header·단위가 충돌하면 이미지 직접 재검토 또는 human review 다. 차트 설명 모델의 설명에서 정확한 배출량 수치를 추정하지 않는다. 독립적으로 읽을 수 없는 chart 수치는 UNREADABLE 이다.

scan 이거나 텍스트층이 손상된 영역에서만 승인된 OCR profile 을 사용한다. 한국어 인식 품질을 공개보고서 표본으로 검증하고 언어/모델/license/version 을 기록한다. OD hybrid 의 docling-fast 와 별도 Docling 을 독립 두 파서 표처럼 투표하지 않는다. 상세는27장이다.

## 8. 모델·예산·fallback
role 별 binding 은4장 계약을 따른다. 콘텍스트 token 은 해당 모델 tokenizer 또는 provider count API 로 계산하고 전체 한도에서 출력·system reserve 를 뺀다. output truncation 을 valid JSON repair 로 숨기지 않는다. 독립3회는 회당 max_output_tokens 를 명시하고 원문 요소 태깅은 기본4096tokens, table 구조화는8192tokens 로 시작하되 모델 한도를 초과하지 않는다. 표 전체가 초과하면 stable row-window 로 나누고 header/provenance 를 반복한다.

fallback 은 schema repair1회와 승인된 같은 role 대체 binding 까지만이며, 대체 모델을 썼으면 새로운 ensemble packet run 으로 기록한다. 지정된 대체 binding 이 없으면 review/partial 이지 임의 외부 API 호출이 아니다. prompt prefix caching 은 허용하되 whole-response 캐시를3회 자기일관성으로 세지 않는다. batch inference 는 3회 replicate 구분·동일 출력 계약이 검증된 후 활성화한다.

## 9. 수정 제안
기본은 결손 요소→검증된 요구사항 요약→삽입 위치의 템플릿이다. 예: “p.28 목표 문장에 기준연도와 기준값을 추가하세요.” 원문에 없는 기준연도/목표율을 실데이터처럼 제시하지 않는다. LLM rewrite 는 의미를 바꾸지 않는 문체 정리에만 사용하고 새로운 숫자·법적 보장·인증 표현을 code guard 로 차단한다. 미검증 조항은 번호를 출력하지 않고 검증 대기 표시를 한다.

### 같은 packet 안의 표 문맥 중복 제거 (2026-09-19)

1,600-token 후보 한도/총 12,000-token 한도를 넘는 묶음은, 해당 원문 검증·품질·
부모 관계 검사를 먼저 통과한 뒤 같은 packet의 앞선 후보에 **완전히 동일한 SourceRef**가
이미 있으면 중복 문맥만 생략할 수 있다. 해당 후보 자신의 SourceRef는 유지한다.
문자열을 자르거나 다른 좌표의 같은 문자열을 합치지 않으며, 표·행·헤더 인용 전체는
동결 packet 어딘가에 그대로 남는다. 소비자는 후보 하나만 분리하지 않고 전체 packet을
읽어야 한다. 허용 범위 안의 기존 묶음은 그대로 유지한다.

`search_coverage.deduplicated_source_refs`는 실제 채택된 후보별 생략한 문맥 source_id를
기록한다. 토큰은 실제 저장 표현으로 계산하고, 여전히 넘치면 후보 전체를 제외한다.
앞선 문맥 없이 너무 큰 첫 주장 셀은 계속 blocked_evidence가 될 수 있다. 품질 미확정·
각주·인용·귀속 가드, numeric global 금지, unknown 유지에는 변경이 없다.
공개 API/DB schema 변경은 없으며 기존 packet/revision을 다시 쓰지 않는다.


### 검증된 단일 행의 큰 표 문맥 (2026-09-20)

단일 검증 행이고 표·행·셀 모두 verified이며 행 번호/셀 span/부모 관계가 명확한
12개 초과 구조 블록의 표에만 행 범위 선택을 적용한다. 의미상 헤더 역할은 아직 없으므로
주장 행과 **모든 앞선 행**을 보존한다. 뒤 행과 그 하위 블록, 보존된 셀과 원문이 정확히
같은 하위 paragraph/heading은 별도 후보에서 제외한다. 다른 문장은 유지한다.
GRI/lexical/vector가 같은 제외 블록을 다시 반환해도 이 선택을 적용하고, 다른 표나
문서 내 전역 검색 결과는 기존 경로로 처리한다. 제외한 ID는
`row_context_excluded_source_ids`와 `unprocessed_source_ids`에 남기며 absent로 바꾸지 않는다.

표 전체 SourceRef는 부모 문맥으로 보존하고 `context_only_source_ids`에 기록한다.
그 ID는 독립 present 인용 후보가 아니다. 이 범위 선택에서는 동일 SourceRef 문맥을
한도에 닿기 전부터 중복 제거하며 후보 자신의 참조는 유지한다. 12개/1,600/12,000
한도와 인용·각주·품질·binding 검사는 동일하다. 구조가 불명확하면 기존 전체 표 확장으로
되돌아가고, 뒤쪽 행이나 복잡한 표는 여전히 blocked_evidence일 수 있다.

공개 API/DB migration은 없고 coverage 진단 필드만 추가된다. 이전 동결 packet/revision은
수정하지 않는다. 롤백은 이 범위 선택을 제거하여 기존 검색 경로를 복구한다.
