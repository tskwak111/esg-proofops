# 16 · 인프라·배포·복구

> ESG ProofOps · 개발 명세 1.0 · 2026-09-08
> 도메인 정본: `sources/PROJECT_DOMAIN_V2_ORIGINAL.md` (원문 2.0, 2026-09-07).

## 1. 환경
local 은 파일/SQlite/메모리 검색+명시적 synthetic model adapter 로 계약 테스트한다. local fake 결과에는 `synthetic=true` 배지/manifest 를 의무화한다. staging 과 production 은 별도 AWS 계정 권장, 최소한 다른 bucket/table/queue/collection/userpool/KMS key 를 사용한다. preview 환경에 고객 원고를 복사하지 않는다.

기본 저장 리전은 ap-northeast-2로 제안하되 대회 허용 서비스/계정/기능별 가용성을 preflight 로 확인한다. 모델 처리 리전은 저장 리전과 별개로 동의 profile 에 기록한다.[S07] 계정 값이 없으면 local synthetic 에서 개발하고 cloud done 을 주장하지 않는다.

## 2. CDK stacks
`NetworkStack`(VPC, endpoints, SG), `DataStack`(S3/DDB/SQS/KMS), `AuthStack`(Cognito), `SearchStack`(OpenSearch Serverless), `ComputeStack`(ECS/API/worker/ALB), `AgentStack`(AgentCore runtime IAM/binding), `WebStack`(S3 web+CloudFront), `ObservabilityStack`(alarms/loggroups)로 코드상 모듈만 나눈다. 여러 stack 은 배포 책임 분리이며 애플리케이션 microservice 분할이 아니다.

API 와 worker 는 private subnet, ALB 는 public TLS, static web 은 private S3 origin+CloudFront OAC, `/v1/*`와 `/auth/*`는 ALB origin 으로 routing 한다. certificate/실도메인은 계정 입력이다. session cookie/csrf 를 같은 origin 으로 유지한다. HTTPS 강제, HSTS, S3 Block Public Access 를 켠다.

## 3. 초기 task 크기와 scale
API 시작값0.5vCPU/1GiB 1–2tasks, worker2vCPU/8GiB 1task/max2, parser JVM heap2GiB, ephemeral storage40GiB 를 실측 시작값으로 둔다. Hybrid backend 를 활성화하면 같은 worker 의 bounded sidecar 또는 별도 승인 task profile 로8GiB 이상 예산을 재평가한다. 크기는 권장 시작 설정이지 한국어300페이지 처리 보장이 아니다. 대형 보고서가 메모리 제한을 넘으면 task 를 키우기 전 row-window/페이지 batch 를 검증한다.

scale target 은 queue age 와 bounded concurrency, 모델 TPS 를 동시에 적용한다. worker 증가로 Bedrock quota 를 넘기지 않도록 tenant/global semaphore 를 DDB lease 로 둔다. 실행 제어는 SQS/DDB 이고 AgentCore 장기 세션을 durable workflow 정본으로 삼지 않는다.

## 4. 네트워크와 권한
ECS IAM task role 은 S3 tenant prefix·DDB tables·SQS·해당 Bedrock/AgentCore action 만 허용한다. parser subprocess 에는 credentials/environment 를 전달하지 않고 임의 인터넷 egress 를 차단한다. 필요한 AWS API endpoint/VPC 경로는 allowlist 다. Private networking feature 의 해당 리전 지원을 확인하고 부족하면 임의 공용경로로 우회하지 않는다. 모델 파일 다운로드는 build/prefetch 단계에 고정 digest 로 진행한다. 런타임 auto-download 를 재현성/egress 정책에서 허용하지 않는다.

## 5. Agent 배포
agent entrypoint 는 공식 SDK 가 요구하는 HTTP/호출 계약을 사용하며 설치된 SDK 버전의 샘플로 smoke test 한다. service-to-service IAM 호출이 기본이고 browser 에 runtime ARN invoke 권한을 주지 않는다. 요청은 server 가 서명/작성한 EvidencePacket artifact id+hash 또는 bounded packet 만 받는다. agent 가 tenant 를 바꾸거나 임의 도구를 선택할 수 없다. Gateway/Identity/Memory 를 P0에서 모두 켜야 하는 것으로 간주하지 않는다.

## 6. 배포 순서
1. lock/SBOM/취약점·라이선스 검사 및 IaC synth.
2. data/auth/search 생성, secret/binding/consent bootstrap.
3. schema/rulepack dry-run, 새 index generation 준비.
4. API/worker/agent staging 배포, synthetic smoke→승인된 공개 PDF smoke.
5. model/preflight+tenant isolation+review/export 확인.
6. 사용자 승인 후 production 에 동일 image digest 배포. worker 는 새 run 부터 새 config snapshot 사용.

## 7. 롤백과 복구
API·worker 는 이전 image digest 로 rolling rollback, AgentCore 는 이전 runtime version/endpoint binding 으로 되돌린다. rules 는 active pointer 만 이전 version 으로 변경하고 이미 산출한 decision 을 덮지 않는다. 새 DB 필드를 읽을 수 있는 이전 app 인지 확인하고 파괴적 schema migration 은 배포와 동시에 하지 않는다. OpenSearch 는 이전 index alias 로 rollback 한다.

S3 versioning 및 DDB PITR 로 별도 recovery 환경에 복원→hash/schema/tenant 검증→deletion tombstone 재적용→pendingjob lease 초기화→사용자 연결 전환한다. RPO≤24시간/RTO≤4시간은 초기 복구 훈련 목표이며 실측 전 보장으로 쓰지 않는다. 문서 원본/active rulepack/export 의 복구 fixture 를 staging 에서 한 번 검증해야 배포완료로 인정한다.

## 8. 비용
고정비는 OpenSearch collection, ALB/NAT/endpoints, ECS, 관측성에서 생기고 모델 token 만 계산하면 누락된다. 정확한 가격은 리전·계정·시점 가격표를 등록한 pricing snapshot 으로 계산한다. stage 별 직접 비용+일별 고정비 배분+검토시간을 별도로 보고한다. 대회 credit/마감일은 검증 없이 가정하지 않는다.
