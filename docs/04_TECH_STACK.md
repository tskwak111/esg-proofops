# 04 · 기술 스택과 선택 근거

> ESG ProofOps · 개발 명세 1.0 · 2026-09-08
> 도메인 정본: `sources/PROJECT_DOMAIN_V2_ORIGINAL.md` (원문 2.0, 2026-09-07).

## 1. 결정표
| 영역 | 선택 | 대안·선택하지 않은 이유 | 재검토 조건 |
|---|---|---|---|
| Python | 3.12.x, uv lock | 3.13+는 기존 연구 adapter 검증 범위를 벗어남 | 파서/SDK 모두 호환 시험 후 |
| Java | Temurin JRE 21 LTS | 11도 OD 요건 충족, 신규 런타임은 21로 통일 | base image 보안/호환 이슈 |
| 기본 파서 | opendataloader-pdf==2.5.7 JSON | 전면 비전은 비용·재현성과 위치 관리 부담 | 한국어 표 gold 에서 개선 검증 |
| 표 교차확인 | pdfplumber, Bedrock vision | Textract 를 한국어 주력으로 쓰지 않음 | 공식 언어 지원/실측 변경 |
| PDF geometry/render | pypdf, pypdfium2 | PyMuPDF 는 기존 코드 편하지만 라이선스 gate 필요 | 라이선스 승인된 legacy benchmark |
| API | FastAPI, Pydantic v2, Uvicorn | Spring Boot 로 나누면 Python extraction 과 계약 이중화 | 운영 팀 분리 근거 발생 |
| AWS SDK | boto3/botocore | SDK 없는 수동 HTTP 인증 구현 금지 | 공식 SDK 특수 기능 미지원 |
| Rules | Python pure functions + PyYAML safe_load | LLM/복잡한 rule SaaS 는 불필요 | 규칙 작성자 UX 의 독립 제품화 |
| Agents | strands-agents, bedrock-agentcore SDK | LangGraph 추가하면 orchestration 중복 | 객관적 기능 격차 발생 |
| LLM | Bedrock approved role binding | 외부 OpenAI/DeepSeek direct API 는 초기 미허용 | 대회/고객 전송 정책 변경 |
| Embedding | Titan Text Embeddings V2, 1024d baseline | 다른 임베딩 모델은 평가 없이 혼용 금지 | 한국어 회수율 비교 승격 |
| Search | OpenSearch Serverless | pgvector 는 원문 DynamoDB 선택과 별도 RDB 운영 필요 | 고정비/검색 품질 실측 근거 |
| State/storage | DynamoDB + S3 | SQLite 는 AWS 다중 worker 정본에 부적합 | 명백한 관계형 transaction 요구 확장 |
| Queue | SQS standard + DLQ | Redis/Celery 이중 상태 운영 불필요 | queue 기능 격차가 입증될 때 |
| Web | React 19 family, TypeScript, Vite, TanStack Query, React Router | Next SSR 은 내부 검토 도구에 필수 아님 | 공개 SEO/서버 rendering 필요 |
| Forms/UI | react-hook-form, Zod, accessible headless controls, pdfjs-dist | 무거운 시각화 framework 도입 안 함 | 성능/접근성 요구 발생 |
| Test | pytest, hypothesis, httpx, Vitest, Testing Library, Playwright | 실 API 만 확인하면 비용·비결정성 큼 | 기존 체계로 못 잡는 장애 확인 |
| Infra | AWS CDK TypeScript, ECS Fargate, CloudFront, ALB, Cognito | Kubernetes/Terraform 혼용 금지 | 운영 표준 변경 |
| Observability | CloudWatch + OpenTelemetry | 별도 SaaS 자동 도입/본문 유출 방지 | 고객 요구/비용 근거 |

[S01–S12]의 공식 자료를 근거로 API 특성을 검토했다. 정확한 transitive 버전은 TASK-001의 lock 생성에서 실제 resolve·테스트 후 고정한다. 존재 여부를 확인하지 않은 최신 patch 번호를 문서에서 꾸며내지 않는다. `uv.lock`, `pnpm-lock.yaml`, Docker digest, SDK/모델 binding hash 가 실제 실행 정본이다. 이 패키지의 `.env.example`은 동작하는 AWS 계정 설정이 아니다.

## 2. 모델 역할과 선택 계약
`extractor`, `tagger`, `vision`, `writer` 네 역할을 둔다. P0는 구조화 출력·한국어·이미지 입력을 지원하는 승인된 Bedrock 모델 한 종을 extractor/tagger/vision 에 공용 binding 하고 writer 는 템플릿을 기본으로 둔다. 상위/경량 모델 cascade 는 독립 validation 이후 P1이다. account 별 access 및 inference profile 이 다르므로 실재하지 않는 model ARN 을 본문에 고정하지 않는다.

`model_bindings.json`은 role 마다 실제 model_id/inference_profile_arn, endpoint_region, allowed_processing_regions, max_context_tokens, max_output_tokens, accepts_images, structured_output_strategy, pricing_snapshot_id, checked_at 을 요구한다. preflight 는 해당 계정의 실제 허용 정보와 최소 구조화 호출로 기능을 확인하고, 가용하지 않으면 오류를 반환한다. global cross-region profile 을 자동 대체값으로 선택하지 않는다. 한국 내 저장과 한국 내 추론은 별개의 조건이다.

## 3. 버전 변경 규칙
파서/normalizer 변경은 parse profile version 을 올리고 같은 원본에 새 parse manifest 를 만든다. 모델·prompt·packet 변경은 tag signature 를 바꾼다. 임베딩 모델 또는 dimensions 변경은 새 OpenSearch index generation 을 만든 뒤 재색인하고 alias 를 전환한다. Rulepack 변경은 rules-only rescore 가능성 검사를 거친다. major contract 변경은 API/schema version migration 을 먼저 정의한다.
