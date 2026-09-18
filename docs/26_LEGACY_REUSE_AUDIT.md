# 26 · 기존 저장소 재사용 검토

> ESG ProofOps · 개발 명세 1.0 · 2026-09-08
> 도메인 정본: `sources/PROJECT_DOMAIN_V2_ORIGINAL.md` (원문 2.0, 2026-09-07).

## 1. 조사 기준과 한계

대상은 `tskwak111/esg-evidence-audit`, main 스냅샷 `70da628a401b89b5ea2c08ee4243523ce99acb50`이다. GitHub 연결을 통해 README·아키텍처와 아래 핵심 소스의 지정 범위를 읽었다. 모든 파일 전수 감사나 기존 테스트 실행을 수행한 것은 아니다. 런타임 환경의 DNS 제한으로 clone/설치 실행은 이루어지지 않았다. 따라서 “재사용 가능”은 **이식 후보와 필요한 수정 조건**이지, 새 시스템에서 테스트를 통과했다는 뜻이 아니다.

## 2. 파일별 결론

모든 경로의 접두사는 `esg_pipeline/research_v4/`다. 상세 열람 범위·blob ID 는 `evidence/legacy_inspection.json`에 기록한다.

| 기존 파일 | 확인한 자산 | 결정 | 새 위치 / 필수 보완 |
|---|---|---|---|
| `document_graph.py` | GraphBlock, TableStructure, BlockRelation, ParserRunMetadata | 모델 개념 재사용, 계약 확장 | `packages/proofops/domain/documents.py`; 테넌트·문서버전·좌표계·원시/정규 텍스트·원문 해시·다중 출처·edge 무결성 추가 |
| `parser_adapters.py` | PyMuPDFParserAdapter, PdfPlumberParserAdapter; 표 재구성 derived_from | 인터페이스·테스트 방식 이식 | `adapters/parsing/`; 기본 파서는 OpenDataLoader. 기존 PyMuPDF 는 라이선스 승인 후 비교용. pdfplumber 는 표 교차확인 |
| `graph_ensemble.py` | merge_document_graphs, 위치 정렬, ID 충돌 처리 | 그대로 복사 금지, 병합 정책 재작성 | `application/ingest/graph_fusion.py`; 동일 원문 영역 정렬·수치 충돌·중복 ID alias·출처 보존 |
| `evidence_bundle.py` | gold 필드 제외 allowlist, claim/local/table 문맥 포맷 | allowlist 원칙 재사용 | `application/evidence/packet_builder.py`; 문자열이 아닌 typed SourceRef 로 전달, 비교연도·경계·직접근거 정책 추가 |
| `llm_extraction_adapter.py` | 구조화 추출, no-grade 지시, source/temporal guards | 검증 아이디어만 이식 | `application/tagging/validate.py`; strict 옵션을 운영에서 항상 활성화, 새 G/P/M 요소 계약 사용 |
| `run_signature.py` | canonical_json_bytes, SourceSignature, LLMRequestSignature, PostprocessSignature | 순수 해시 유틸·분리 설계 우선 이식 | `domain/provenance.py`; tenant, permission/consent, replicate_id, inference profile, extraction epoch 추가 |
| `content_cache.py` | 원시 응답/후처리 분리, 성공 상태·해시 확인, 원자 파일 쓰기 | 로컬 adapter 참고 + AWS 저장소 재구현 | `adapters/cache/`; 파일 flock 은 다중 Fargate 컨테이너 잠금이 아님. DynamoDB lease/fencing 과 S3 immutable artifact 사용 |
| `evidence_grader.py` | 외부 문맥 제외, 특칙, 순수 함수형 scorer | **새 규칙엔진으로 대체** | `domain/rules/`; 원문 v2.0의 사다리로 재작성. 기존 기준과 label 은 이식하지 않음 |
| README / ARCHITECTURE | 재현성·silver/holdout 분리·현재 구현 한계 | 운영·평가 설계의 참고 자산 | 기존 성능 수치나 구현됨 문구를 새 시스템의 성과로 주장하지 않음 |

`table_reconstruction.py`, `claim_decomposer.py`, `parser_table_eval.py`, `gold_backtest.py`, `canonical_run_service.py`, `run_manifest.py` 등은 아키텍처 문서에서 존재와 역할을 확인했지만 이번 응답에서 본문을 직접 검토하지 않았다. **2차 검토 후보**다. 해당 이름만으로 안정성·재사용성을 확정하지 않는다.

## 3. 직접 확인한 이식 위험

### R-01. 그래프 중복 제거 후 dangling edge 가능성

`merge_document_graphs`는 같은 `(page_num, block_type, normalized_text)`를 발견하면 뒤 블록을 버리고 `id_map[(graph_index, block.block_id)] = block.block_id`로 저장한다. 먼저 남긴 블록의 ID 와 버린 블록의 ID 가 다를 때, 뒤 블록을 가리키던 relation 이 최종 graph 에 없는 ID 를 계속 참조할 수 있다. `DocumentGraph`에 edge 존재 검증이 보이지 않는 열람 범위에서는 이 상태가 차단되지 않는다.

예: parser A 의 `A1`과 parser B 의 `B1`이 같은 내용, B 의 행 `B2 -> B1`. B1은 제거되지만 `B2 -> B1`이 남으면 근거 추적이 끊긴다. 이는 소스에서 도출한 결함 시나리오이며 기존 저장소를 실행한 재현 결과는 아니다.

**수정 계약:** `dedupe_key -> retained_canonical_id`와 `(parser_run_id, source_id) -> canonical_id`를 별도 유지한다. 버린 후보의 provenance 도 retained 블록에 추가한다. 모든 edge endpoint 가 존재하는지 검증하고 실패 시 해당 graph 를 확정하지 않는다. `FX-GRAPH-001` 테스트 벡터를 사용한다.

### R-02. 같은 페이지의 같은 문자열만으로는 동일 블록이 아니다

현재 text_key 는 bbox 를 포함하지 않는다. 서로 다른 표의 “합계”, 같은 페이지의 다른 사업장 수치처럼 실제 별개 영역을 병합할 수 있다. 새 병합은 문서버전·페이지·영역·타입·표 컨텍스트를 함께 사용한다. 동일 텍스트라도 겹치지 않는 영역은 유지한다. 수치 불일치 후보를 삭제해 다수결로 만들지 않는다.

### R-03. 좌표 부재를 `[0,0,0,0]`으로 대체하는 경로

pdfplumber adapter 의 table record 변환은 bbox 가 없으면 영점 상자를 넣는다. 새로운 계약에서는 `bbox=null`, `source_quality=unlocated`와 이유를 기록한다. 위치 없는 근거는 자동 확정 입력으로 허용하지 않는다. UI 에서 페이지 맨 위를 실제 근거처럼 하이라이트하지 않는다.

### R-04. 기존 scorer 와 새 도메인의 차이

읽은 `evidence_grader.py`의 성과형은 `method_or_verification_any_of`, 목표형 E2는 `e2_support_any_of`를 사용한다. 새 원문 §4.4는 성과형 E3에 산정방법 **및 보증 연결**을, 목표형 E2에 기준연도·기준값 **및 적용범위**를 요구한다. 기존 YAML/JSON 정책이나 골드 라벨을 그대로 가져오면 원문과 다른 판정이 발생할 수 있다.

### R-05. strict guard 기본값과 캐시 역할

`LLMEvidenceExtractionAdapter` 생성자의 strict provenance/temporal 플래그는 열람 코드에서 기본 false 다. 운영 경로가 이를 어떻게 주입하는지는 별도 확인해야 한다. 새 구현은 guarded path 를 기본값이 아니라 **필수 경계**로 만든다. `run_signature.py`의 좋은 설계를 가져오되, 세 태깅 회차를 동일 cache key 로 합치지 않도록 replicate_id 를 추가한다.

## 4. 데이터 재사용

기존 README 는 5개사 180행 Gold 를 개발용 silver 로 취급하고, policy replay consistency 를 PDF-to-grade 정확도로 주장하지 말라고 명시한다. 이를 유지한다. 기존 데이터를 v2.0의 G/P/M 태깅으로 재라벨링한 뒤 개발풀로 사용한다. 이미 본 회사/문서는 독립 평가 holdout 으로 재사용하지 않는다. 원본 PDF 권리와 실제 파일 존재는 별도로 확인한다.

## 5. 이식 순서

먼저 새 contracts 와 원문 사다리 테스트를 만들고, signature → graph schema → pdfplumber/table adapter → evidence packet allowlist → provenance guard 순서로 이식한다. 기존 grader, `standards/v4/`, 연구 sampling quota, legacy dashboard 를 통째로 import 하지 않는다. 기존 저장소에는 쓰기·삭제·브랜치 생성·PR 을 수행하지 않았다.

새 runtime 은 `proofops.*` namespace 다. 실제 코드 이식은 최소 함수 단위이며 출처 commit 과 원래 파일을 각 파일 헤더 및 `evidence/reuse_ledger.json`에 남긴다. 기존 실험 경로를 지우지 않는다. 새 개발 브랜치/새 디렉터리 사용은 Codex 실행 단계에서 한다.
