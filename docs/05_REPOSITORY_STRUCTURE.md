# 05 · 구현 저장소 구조

> ESG ProofOps · 개발 명세 1.0 · 2026-09-08
> 도메인 정본: `sources/PROJECT_DOMAIN_V2_ORIGINAL.md` (원문 2.0, 2026-09-07).

## 1. 새 구현 디렉터리
이 패키지는 문서·계약·fixture 다. 아래 트리는 Codex 가 **구현할 목표 구조**이며 앱 코드가 이미 포함돼 있다는 뜻은 아니다.

```text
AGENTS.md
README.md
pyproject.toml / uv.lock / package.json / pnpm-lock.yaml
.env.example
apps/
  api/src/proofops_api/{main.py,composition.py,auth.py,middleware.py,routers/}
  worker/src/proofops_worker/{main.py,composition.py,relay.py,consumer.py,heartbeat.py}
  agent/src/proofops_agent/{entrypoint.py,tagger.py,extraction.py,vision.py}
  web/src/{app/,routes/,components/,features/,api/,design/}
packages/proofops/
  domain/{documents.py,claims.py,evidence.py,decisions.py,provenance.py,errors.py}
  domain/rules/{engine.py,goal.py,performance.py,management.py,exceptions.py,safe_harbor.py}
  application/ports/{storage.py,queue.py,search.py,models.py,clock.py}
  application/ingest/{parse.py,graph_fusion.py,normalize.py,geometry.py,quality.py}
  application/evidence/{packet_builder.py,retrieval.py,binding.py,citations.py}
  application/tagging/{consensus.py,validate.py,service.py}
  application/{runs.py,reviews.py,rescores.py,exports.py,retention.py}
  adapters/parsing/{opendataloader.py,pdfplumber.py,pdfium.py,legacy_pymupdf.py,hybrid.py}
  adapters/aws/{s3.py,dynamodb.py,sqs.py,opensearch.py,bedrock.py,cognito.py}
  adapters/cache/{local.py,aws.py}
  adapters/local/{filesystem.py,sqlite_state.py,queue.py,search.py,models.py}
contracts/{openapi.yaml,jsonschema/,requirement_catalog.json}
config/{rubric/,standards/,regulatory/,assurance/,sasb/,parsing.yaml,limits.yaml}
prompts/{claim_extraction.md,element_tagging.md,vision_table.md,suggestion.md}
tests/{unit/,integration/,contracts/,acceptance/,e2e/,security/,evaluation/}
fixtures/{rule_cases.json,edge_cases.json,synthetic/}
evaluation/{datasets/,splits/,metrics/,reports/}
infra/cdk/{bin/,lib/,tests/}
scripts/{validate_package.py,preflight.py,verify_architecture.py,verify_rulepack.py}
docs/00_MASTER_SPEC.md ... docs/33_FINAL_HANDOFF_AUDIT.md
sources/                         # 첨부 원문·외부 출처 목록; runtime import 금지
legacy_reference/                # 원본 snapshot 별도 checkout, 새 runtime import 금지
```

## 2. 기존 저장소와 통합 방식
권장: 기존 저장소에 새 `proofops/` 개발 영역 또는 새 브랜치를 만들고 위 구조를 추가한다. 원본 research_v4 디렉터리를 한 번에 이동/삭제하지 않는다. main 의 연구 CLI 와 테스트는 유지한다. legacy_reference 는 submodule 을 강제하지 않으며 특정 commit 의 read-only 작업 복사여도 된다. 이 응답은 브랜치 생성·커밋·push 를 수행하지 않았다.

이식 파일은 `evidence/legacy_inspection.json`의 snapshot 과 source/license 를 기록한다. 동일 동작을 유지하는 순수 유틸은 characterization test→복사→import 정리→새 테스트 통과 순서다. policy/grade 는 parity 목표가 아니라 v2.0 source compliance 목표다.

## 3. 규약
Python 파일/함수 snake_case, 클래스 PascalCase, TS component PascalCase, HTTP/json snake_case 를 사용한다. domain enum 은 계약에 나온 소문자 또는 고정 대문자를 그대로 쓴다. 시간은 UTC RFC3339, 화면만 Asia/Seoul 로 변환한다. SHA256은 소문자 64 hex, 모든 내부 id 는 서버 발급 UUID 문자열, public API 에서 경로 삽입을 막기 위해 UUID 형식을 검사한다. 시범 fixture id 는 별도 테스트용 namespace 이고 운영 id 검증과 섞지 않는다.
