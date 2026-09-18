# 15 · 관측성·운영 지표

> ESG ProofOps · 개발 명세 1.0 · 2026-09-08
> 도메인 정본: `sources/PROJECT_DOMAIN_V2_ORIGINAL.md` (원문 2.0, 2026-09-07).

## 1. 로그 구조
모든 application log 는 JSON 으로 `timestamp, level, service, env, trace_id, request_id, tenant_hash, run_id, stage, job_id, attempt, fencing_token, code, latency_ms`를 포함한다. 개별 모델 호출은 `model_binding_hash, provider_request_id, input_tokens, output_tokens, cached_tokens, request_signature`를 추가한다. PDF quote, 문서제목/기업 비밀명, raw prompts/responses, API keys 는 일반 로그에서 제외한다. 원문 디버깅은 권한 있는 artifact viewer 를 통해서만 한다.

## 2. 지표
api_requests_total/status, api_latency_ms, queue_oldest_age, job_retry_count, lease_lost_total, dlq_messages, parser_page_count/unreadable_count, table_conflicts, citation_rejected, binding_undetermined, three_run_disagreement, grade_counts, decision_blocked_rule_gap, review_pending/age, export_snapshot_retry, model_tokens/cost_unknown 를 수집한다. low-cardinality label(env,stage,error_code)만 metric dimension 에 쓰고 claim_id 는 trace 에 둔다.

## 3. tracing
upload→run→job→parser/AgentCore call→rule→review→export 를 trace link 로 잇는다. 비동기 큐 전달에는 traceparent 와 run_id 만 전달하고 원문을 메시지 body 에 넣지 않는다. LLM span 에는 role·signature·토큰·지연만 넣고 자동 prompt capture 는 비활성화한다. AgentCore observability 의 기본 로그 설정도 본문을 캡처하지 않는지 preflight 한다.

## 4. 초기 SLI/SLO 와 알림
| 지표 | 초기 목표/알림 | 조치 |
|---|---|---|
| 조회 API p95 |20동시 사용자 시험에서1초 이내 목표 | query/인덱스·artifact fetch 프로파일 |
| 생성 요청 수락 p95 |2초 이내 목표 | 동기 heavywork 제거 |
| API error rate |5분간5xx>5% | 의존성·최근 배포 확인 |
| Outbox/queue lag |age>120초 5분 지속 | relay lease/DLQ/worker 확인 |
| DLQ |1건 이상 | 해당 run 상태·수동 재처리 승인 |
| Citation invalid |직전200요소 대비>10% | model/prompt/parse change 조사, auto-confirm 중지 |
| Review pending age |업무일1일 초과 표시 | 담당자 처리; 법적 SLA 로 주장 금지 |
| 모델 budget |80% 경고/100% 신규 호출 중단 | partial 표시 |
| snapshot integrity |불일치1건 | export 다운로드 차단 및 재생성 |

운영 SLO 는 측정 전 목표다. 문서 전체 처리시간은 페이지/표/claim/model 에 좌우되므로 고정 초단위 약속 대신 stage 실측 p50/p95를 파일럿 보고서에 기록한다. availability 목표를 원가·실증 없이 계약상 SLA 로 만들지 않는다.

## 5. 감사 로그는 application log 와 별개
Audit event 는 사용자와 규칙 변경의 증빙이며 core transaction 과 원자적으로 append 한다. hash chain 은 변경 탐지와 순서 확인에 도움을 주지만 외부 공증·법적 증거능력을 자동 보장하지 않는다. S3 export manifest 에 원본/parse/model/prompt/rule/decision hash 와 리뷰 시퀀스를 넣는다. retention 과 접근 권한은11장 정책을 따른다.
