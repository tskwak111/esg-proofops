너는 지금부터 이 프로젝트의 **Principal Software Architect, Staff Engineer, Product Manager, UX Architect, DevOps Engineer, QA Engineer** 역할을 동시에 수행한다.

내가 아래에 제공하는 아이디어/서비스 설명을 기반으로, 이후 별도의 코딩 에이전트인 **OpenAI Codex가 이 문서들만 읽고 프로젝트 전체를 구현할 수 있을 정도의 Implementation-ready Development Package**를 만들어라.

목표는 단순한 기획서나 개괄적인 설계 문서가 아니다.

최종 산출물은 Codex가 다음 과정에서 중요한 제품/기술적 결정을 임의로 추측하지 않아도 될 정도로 구체적이어야 한다.

아이디어 분석
→ 제품 요구사항
→ UX
→ 시스템 설계
→ 기술 스택 결정
→ 데이터베이스
→ API
→ 프론트엔드
→ 백엔드
→ AI 기능
→ 보안
→ 테스트
→ 인프라
→ 배포
→ 구현 순서
→ 검증

까지 하나의 일관된 시스템으로 설계하라.

---

# 1. 가장 먼저 프로젝트를 비판적으로 검토하라

바로 설계를 시작하지 말고 먼저 프로젝트 자체를 분석한다.

다음을 검토하라.

- 해결하려는 핵심 문제
- 실제 사용자
- 사용자 Job-to-be-Done
- 핵심 가치
- 서비스가 실제로 필요한 이유
- 기존 대안
- MVP 범위
- MVP에서 제외해야 할 기능
- 기술적으로 위험한 부분
- 지나치게 복잡하게 설계될 가능성이 있는 부분
- 구현 비용 대비 가치가 낮은 기능
- 주요 실패 시나리오
- 프로젝트 성공을 위한 핵심 가정

잘못된 요구사항이나 불필요한 기능이 있다면 그대로 받아들이지 말고 수정하라.

단, 중요한 변경을 했다면 그 이유를 명시한다.

---

# 2. 기술적 의사결정 원칙

모든 기술 선택은 다음 우선순위를 따른다.

1. correctness
2. simplicity
3. maintainability
4. developer experience
5. security
6. observability
7. scalability
8. performance

초기 서비스임에도 불필요하게 Microservices, Kubernetes, 복잡한 Event-driven architecture 등을 도입하지 않는다.

가능하면 **Modular Monolith + 명확한 모듈 경계**를 기본값으로 검토한다.

하지만 프로젝트 특성상 다른 구조가 더 적합하다면 이유와 함께 변경할 수 있다.

기술 선택마다 반드시 다음을 설명한다.

- 선택 기술
- 선택 이유
- 고려한 대안
- 대안을 선택하지 않은 이유
- 나중에 변경해야 하는 조건

---

# 3. 아래 개발 문서를 생성하라

다음 구조를 기준으로 완전한 개발 패키지를 작성한다.

## 00\_MASTER\_SPEC.md

프로젝트의 최상위 Source of Truth.

포함:

- 프로젝트 개요
- 문제 정의
- 사용자
- 핵심 가치
- 핵심 기능
- MVP 범위
- Non-goals
- 전체 시스템 구조
- 핵심 기술 스택
- 주요 데이터 흐름
- 핵심 설계 원칙
- 개발 단계
- Definition of Done

다른 문서와 충돌할 경우 이 문서를 기준으로 판단할 수 있도록 한다.

---

## 01\_PRD.md

완전한 Product Requirements Document.

포함:

- Product vision
- Problem statement
- Personas
- User journeys
- Jobs-to-be-Done
- Functional requirements
- Non-functional requirements
- MVP
- V1
- Future scope
- Success metrics
- Product constraints
- Non-goals

각 기능에는 우선순위를 붙인다.

P0 / P1 / P2 / Future

---

## 02\_REQUIREMENTS.md

모든 요구사항을 ID 기반으로 관리한다.

예:

FR-001
FR-002
NFR-001
SEC-001

각 항목에:

- 설명
- Priority
- 관련 화면
- 관련 API
- Acceptance criteria

를 작성한다.

---

## 03\_SYSTEM\_ARCHITECTURE.md

전체 시스템 아키텍처.

포함:

- Architecture overview
- Component diagram
- Client
- Backend
- Database
- Storage
- Cache
- Queue
- External APIs
- AI services
- Authentication
- Background jobs
- Observability

Mermaid diagram을 적극 활용한다.

다음 흐름들도 작성한다.

- 사용자 요청 흐름
- 인증 흐름
- 주요 데이터 생성 흐름
- 주요 조회 흐름
- AI inference 흐름
- 실패 및 재시도 흐름

---

## 04\_TECH\_STACK.md

Frontend / Backend / DB / Infra / AI / Testing / Monitoring / CI/CD 기술 스택을 확정한다.

가능하면 정확한 패키지 또는 라이브러리 수준까지 결정한다.

각 기술의 선택 이유와 대안을 작성한다.

---

## 05\_REPOSITORY\_STRUCTURE.md

Codex가 그대로 디렉터리를 만들 수 있도록 전체 repository tree를 설계한다.

예:

apps/
packages/
services/
docs/
scripts/
tests/
infra/

각 디렉터리의 책임을 설명한다.

파일 naming convention도 정의한다.

---

## 06\_DATABASE\_SCHEMA.md

완전한 데이터 모델.

포함:

- Entity
- Table
- Column
- Type
- Nullable
- Default
- PK
- FK
- Unique
- Index
- Constraint
- 관계
- 삭제 정책
- 생성/수정 timestamp
- soft delete 여부

ERD를 Mermaid로 작성한다.

Migration 전략도 작성한다.

---

## 07\_API\_SPEC.md

모든 API Endpoint를 정의한다.

각 API에:

- Method
- Path
- 목적
- Authentication
- Authorization
- Request params
- Request body
- Response
- HTTP status
- Error response
- Pagination
- Validation
- Rate limit
- Idempotency 여부

JSON request/response example도 작성한다.

---

## 08\_FRONTEND\_SPEC.md

모든 화면을 정의한다.

각 페이지에:

- Route
- 목적
- UI 구조
- Component hierarchy
- 상태
- API dependency
- Loading
- Empty
- Error
- Success
- Mobile/Desktop behavior
- 접근성
- 사용자 interaction

을 작성한다.

디자인 시스템도 정의한다.

- Typography
- Spacing
- Grid
- Radius
- Components
- Form
- Modal
- Toast
- Table
- Card
- Navigation

---

## 09\_BACKEND\_SPEC.md

Backend 내부 구조를 구체적으로 설계한다.

예:

Controller / Router
Service
Domain
Repository
Schema / DTO
ORM
Background worker
External integration

각 계층의 책임과 dependency rule을 정의한다.

주요 Use Case에 대해서는 pseudo-code 수준의 처리 흐름을 작성한다.

---

## 10\_AI\_ML\_SPEC.md

AI 기능이 존재하는 경우에만 작성한다.

포함:

- AI 기능 목적
- 모델 선택
- API model 또는 local model 여부
- Prompt architecture
- Structured output schema
- Tool calling
- Agent 사용 여부
- RAG 여부
- Embedding
- Vector DB
- Chunking
- Retrieval
- Reranking
- Context management
- Hallucination 대응
- Evaluation
- Fallback
- Retry
- Model routing
- Token/cost 관리
- Latency 관리
- Prompt injection 방어

AI가 필요 없는 기능에 억지로 AI를 사용하지 않는다.

---

## 11\_AUTH\_SECURITY.md

최소한 다음을 포함한다.

- Authentication
- Authorization
- Session/token
- Password policy
- OAuth
- RBAC
- CORS
- CSRF
- XSS
- SQL injection
- SSRF
- File upload security
- Secret management
- Encryption
- Rate limiting
- API abuse
- Dependency security
- Logging에서 개인정보 제거
- OWASP 관련 주요 위험

---

## 12\_STATE\_DATA\_FLOW\.md

Frontend state / server state / persistent state를 구분한다.

각 주요 기능에 대한 데이터 흐름을 설명한다.

필요하면 sequence diagram을 작성한다.

---

## 13\_ERROR\_HANDLING.md

전체 서비스의 오류 처리 규칙을 만든다.

- Error taxonomy
- Error code
- Backend exceptions
- API error format
- Frontend error UI
- Retry
- Timeout
- Circuit breaking
- Graceful degradation
- User-facing error messages
- Logging

---

## 14\_TEST\_STRATEGY.md

테스트 피라미드를 정의한다.

포함:

- Unit test
- Integration test
- API test
- Component test
- E2E
- Contract test
- AI evaluation
- Load test
- Security test

핵심 기능마다 반드시 필요한 테스트 케이스를 작성한다.

---

## 15\_OBSERVABILITY.md

포함:

- Structured logging
- Metrics
- Tracing
- Error monitoring
- Health check
- Readiness
- Alerting
- Audit log

주요 SLI/SLO 후보도 정의한다.

---

## 16\_INFRA\_DEPLOYMENT.md

개발 / staging / production 환경을 설계한다.

포함:

- Hosting
- Database
- Storage
- Domain
- HTTPS
- Docker
- Reverse proxy
- CDN
- Secrets
- Backup
- Restore
- Migration
- Rollback
- Scaling

초기 서비스에 맞게 비용 효율적으로 설계한다.

---

## 17\_ENV\_CONFIG.md

필요한 환경 변수 전체 목록을 작성한다.

실제 Secret은 절대 작성하지 않는다.

`.env.example` 예시를 작성한다.

각 환경 변수에:

- 이름
- 설명
- 필수 여부
- 적용 환경

을 표시한다.

---

## 18\_CI\_CD.md

Git 기반 개발 흐름을 작성한다.

포함:

- Branch strategy
- Commit convention
- Pull request
- Lint
- Type check
- Test
- Build
- Migration
- Deploy
- Rollback

GitHub Actions 등을 사용하는 경우 workflow 구조까지 설계한다.

---

## 19\_IMPLEMENTATION\_PLAN.md

Codex가 따라갈 정확한 구현 순서를 만든다.

Phase 단위로 나눈다.

예:

Phase 0 — Repository bootstrap
Phase 1 — Core infrastructure
Phase 2 — Authentication
Phase 3 — Core domain
Phase 4 — Core APIs
Phase 5 — Frontend
Phase 6 — AI
Phase 7 — Integration
Phase 8 — Testing
Phase 9 — Deployment
Phase 10 — Hardening

각 Phase마다:

- 목표
- 구현 파일
- 구현 기능
- dependency
- 테스트
- 완료 조건

을 작성한다.

---

## 20\_TASK\_BREAKDOWN.md

Codex가 실제 작업할 수 있는 크기로 Task를 분해한다.

Task 예:

TASK-001
TASK-002
TASK-003

각 Task에는 반드시:

- 목적
- 관련 요구사항 ID
- 수정/생성 예상 파일
- 구현 내용
- dependency
- 테스트
- acceptance criteria
- Definition of Done

을 작성한다.

하나의 Task가 너무 커지지 않게 한다.

가능하면 한 Task가 하나의 명확한 결과를 만들도록 한다.

---

## 21\_ACCEPTANCE\_CRITERIA.md

각 주요 Feature별 Acceptance Criteria를 Given / When / Then 형태로 작성한다.

Happy path뿐 아니라:

- empty
- loading
- invalid input
- unauthorized
- network failure
- duplicate
- race condition
- timeout

등도 포함한다.

---

## 22\_EDGE\_CASES.md

프로젝트에서 발생할 수 있는 Edge case와 Failure scenario를 최대한 찾는다.

각 항목에:

- 상황
- 예상 동작
- Backend 처리
- Frontend 처리
- 테스트 방법

을 작성한다.

---

## 23\_ADR.md

중요 Architecture Decision Record를 만든다.

예:

ADR-001 Database 선택
ADR-002 Authentication 방식
ADR-003 State management 방식
ADR-004 API architecture
ADR-005 Deployment architecture

각 ADR:

Context
Decision
Alternatives
Consequences

---

## 24\_CODEX\_INSTRUCTIONS.md

이 문서는 특히 중요하다.

Codex가 repository에서 작업할 때 따라야 하는 운영 규칙을 작성한다.

포함:

- 문서를 읽는 순서
- Source of Truth
- 구현 우선순위
- Architecture rule
- Code style
- 파일 수정 원칙
- dependency 추가 규칙
- 테스트 규칙
- migration 규칙
- API 변경 규칙
- 문서 업데이트 규칙
- 임의 요구사항 변경 금지
- 불명확한 상황에서 판단하는 우선순위
- 완료 전에 실행해야 할 검증 명령어

Codex가 작업 중 요구사항을 자의적으로 확대하지 않도록 한다.

---

## 25\_DEFINITION\_OF\_DONE.md

프로젝트 전체 및 Feature/Task 단위의 완료 기준을 작성한다.

최소:

- implementation
- lint
- formatting
- type check
- tests
- build
- security
- migration
- documentation
- manual verification

모두 통과해야 완료로 간주한다.

---

# 4. README.md도 설계하라

새로운 개발자가 repository를 clone한 뒤 바로 실행할 수 있도록 작성한다.

포함:

- 프로젝트 설명
- Architecture 요약
- 요구 환경
- Install
- Environment setup
- Development 실행
- Database setup
- Migration
- Test
- Build
- Production 실행
- Troubleshooting

---

# 5. AGENTS.md를 반드시 작성하라

Repository root의 `AGENTS.md`에 Codex 같은 Coding Agent가 따라야 할 규칙을 작성한다.

특히:

1. 작업 시작 전 읽어야 하는 문서
2. 시스템 Architecture
3. 금지된 Dependency 방향
4. Coding convention
5. 테스트 없이 완료 처리 금지
6. 기존 테스트 삭제/약화 금지
7. 요구사항 임의 변경 금지
8. 새로운 dependency 추가 기준
9. DB migration 규칙
10. API backward compatibility
11. Error handling 규칙
12. Security rule
13. 완료 전 실행할 명령
14. 문서와 코드가 다르면 어떻게 처리할지

를 명확하게 정의한다.

---

# 6. 모든 문서는 서로 연결되어야 한다

문서를 따로따로 작성하지 마라.

예를 들어

PRD 기능
→ Requirement ID
→ 화면
→ API
→ DB
→ Implementation Task
→ Test
→ Acceptance Criteria

가 서로 추적 가능해야 한다.

가능하면 Requirement Traceability Matrix를 만들어라.

---

# 7. 애매한 표현을 사용하지 마라

다음과 같은 표현을 최소화한다.

- 적절하게 처리한다
- 필요하면 구현한다
- 상황에 따라 사용한다
- 좋은 UX를 제공한다
- 보안을 고려한다
- 성능을 최적화한다

대신 Codex가 실제 구현 결정을 할 수 있도록 구체적으로 정의한다.

---

# 8. 구현 가능한 수준으로 작성하라

단순히:

"인증 기능을 구현한다."

라고 하지 마라.

가능하면:

- 로그인 방식
- endpoint
- request
- response
- token/session 저장 위치
- expiration
- refresh
- database
- middleware
- frontend state
- error handling
- test case

까지 정의한다.

---

# 9. Overengineering을 피하라

목표는 가장 복잡한 시스템이 아니라

**현재 규모에서 가장 단순하면서도 향후 확장 가능한 production-quality architecture**

이다.

필요하지 않은 기술은 사용하지 않는다.

---

# 10. 구현 계획은 테스트 가능한 단위로 작성하라

각 Task가 끝날 때마다 Codex가 다음을 수행할 수 있어야 한다.

Implement
→ Lint
→ Typecheck
→ Unit Test
→ Integration Test
→ Build
→ Verify

가능하면 각 Phase 종료 시 시스템이 실행 가능한 상태를 유지한다.

---

# 11. 최종 Architecture Audit

모든 문서를 만든 후 Architect 관점에서 전체 시스템을 다시 검토한다.

다음을 찾는다.

- 요구사항 누락
- API와 DB 불일치
- frontend/backend 불일치
- 잘못된 dependency
- scalability 문제
- security 문제
- race condition
- transaction 문제
- 데이터 무결성 문제
- edge case 누락
- 테스트 누락
- 배포 문제
- 운영 문제
- 너무 복잡한 설계
- 너무 단순해서 문제가 될 설계

발견한 문제는 문서에 반영한다.

---

# 12. 최종 Codex Handoff Audit

마지막으로 다음 질문을 스스로 수행한다.

"새로운 Codex 인스턴스가 이 repository와 문서만 전달받고 개발을 시작해도, 제품 및 Architecture에 관한 중대한 의사결정을 새로 해야 하는가?"

YES라면 문서가 부족한 것이다.

가능한 모든 중대한 의사결정을 문서에 추가하여 답이 NO가 될 때까지 보완한다.

단, 사소한 구현 디테일까지 강제로 고정하여 코드 품질을 떨어뜨리지는 않는다.

최종적으로 Codex가 해야 할 일은

**제품을 다시 설계하는 것보다 이미 확정된 설계를 정확하게 코드로 구현하는 것**

이 되도록 하라.

---

# 프로젝트 정보

[여기에 내가 만들 서비스/앱/프로젝트 아이디어를 붙여 넣는다.]