# 30 · 출처·조사 범위·검증 상태

> ESG ProofOps · 개발 명세 1.0 · 2026-09-08
> 도메인 정본: `sources/PROJECT_DOMAIN_V2_ORIGINAL.md` (원문 2.0, 2026-09-07).

## 출처를 읽는 규칙
원문으로부터 유지한 도메인과 새로 제안한 구현 설계를 구분한다. `sources/PROJECT_DOMAIN_V2_ORIGINAL.md`는 그대로 복사한 v2.0이고 SHA-256은 source_manifest 에 기록했다. 일반 개발패키지 요청문도 별도 보존했다. 이 패키지는 공식 규제/법률/보증기준 원문 전체를 재검증한 법률 검토서가 아니다.

## 공식 기술 자료
| ID | 자료 | 확인 범위 |
|---|---|---|
| S01 | [OpenDataLoader release API v2.5.7](https://api.github.com/repos/opendataloader-project/opendataloader-pdf/releases/latest) | GitHub GET 확인: v2.5.7, published2026-09-01. 설치/benchmark 미실행. |
| S02 | [OpenDataLoader tagged README](https://github.com/opendataloader-project/opendataloader-pdf/blob/v2.5.7/README.md) | Java11+/Python3.10+, JSON bbox/Markdown, Apache2.0. 이번검토는 taggedREADME1–150행. |
| S03 | [OpenDataLoader hybrid mode](https://opendataloader.org/docs/hybrid-mode) | docling-fast 와선택적 hybrid/OCR, 기본 hybrid off. 그림설명은정확수치판독보장아님. |
| S04 | [OpenDataLoader JSON output schema](https://opendataloader.org/docs/reference/json-schema) | hierarchical kids/page number/table rows/cells. 실제 version native bbox 는 adapterfixture 에서검증. |
| S05 | [Amazon Textract limits/languages](https://docs.aws.amazon.com/textract/latest/dg/limits-document.html) | 공식지원언어목록에한국어없음. 한국어주력 fallback 으로선정하지않음. |
| S06 | [PyMuPDF license/features](https://pymupdf.readthedocs.io/en/latest/about.html) | AGPL 또는 commercial license 선택. 사용조건검토후 optionaladapter. |
| S07 | [AgentCore regions](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/agentcore-regions.html) | 기능별 regionavailability 가다르므로계정 preflight 필수. |
| S08 | [AgentCore cross-region processing](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/cross-region-inference.html) | Memory/evaluation 의처리리전검토. 저장리전과추론리전동일가정금지. |
| S09 | [Bedrock structured output](https://docs.aws.amazon.com/bedrock/latest/userguide/structured-output.html) | 구조화응답지원과내용정확성은별개. 모델별기능확인. |
| S10 | [Strands structured output](https://strandsagents.com/docs/user-guide/concepts/agents/structured-output/) | 구조화모델출력계약사용. SDK 실제 lock/version smoke 필수. |
| S11 | [AWS DynamoDB overview/constraints](https://docs.aws.amazon.com/prescriptive-guidance/latest/modernization-rdbms-dynamodb/overview.html) | item400KB,transaction 제약. 큰 artifact 는 S3에분리. |
| S12 | [Titan embeddings parameters](https://docs.aws.amazon.com/bedrock/latest/userguide/model-parameters-titan-embed-text.html) | Titan Text EmbeddingsV2의 modelID 와1024/512/256dimension. 본설계1024baseline. |
| S13 | [대회 공개 페이지](https://ku-aws-challenge.framer.ai/) | 고려대×AWS 공모전과 AWS LLM 활용 안내. 표시월일의연도/허용서비스전체는미확정이므로2026마감확정근거로사용안함. |
| S14 | [AgentCore VPC connectivity](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/agentcore-vpc.html) | private connectivity 는해당 region/feature 설정검증필요. |
| S15 | [AgentCore long-running operations](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-long-run.html) | runtime 장기실행기능과별개로 DDB/SQS 를 durable workflow 정본으로설계. |

## 기존 저장소 스냅샷

`70da628a401b89b5ea2c08ee4243523ce99acb50`를기준으로아래파일을열람했다. 일부행만열람한파일의전체안정성/테스트통과를주장하지않는다.

- [README.md](https://github.com/tskwak111/esg-evidence-audit/blob/70da628a401b89b5ea2c08ee4243523ce99acb50/README.md) — all; project status, silver and policy replay caveats.
- [docs/research_v4/ARCHITECTURE.md](https://github.com/tskwak111/esg-evidence-audit/blob/70da628a401b89b5ea2c08ee4243523ce99acb50/docs/research_v4/ARCHITECTURE.md) — tool-visible content; tail may be truncated; architecture overview and module inventory; not proof all consumers enabled guards.
- [esg_pipeline/research_v4/parser_adapters.py](https://github.com/tskwak111/esg-evidence-audit/blob/70da628a401b89b5ea2c08ee4243523ce99acb50/esg_pipeline/research_v4/parser_adapters.py) — all; parser adapters and missing bbox fallback.
- [esg_pipeline/research_v4/graph_ensemble.py](https://github.com/tskwak111/esg-evidence-audit/blob/70da628a401b89b5ea2c08ee4243523ce99acb50/esg_pipeline/research_v4/graph_ensemble.py) — 1-300 (whole file in returned range); dedupe alias and bbox-free text key.
- [esg_pipeline/research_v4/document_graph.py](https://github.com/tskwak111/esg-evidence-audit/blob/70da628a401b89b5ea2c08ee4243523ce99acb50/esg_pipeline/research_v4/document_graph.py) — 1-290 (whole file in returned range); graph models and source schema.
- [esg_pipeline/research_v4/evidence_bundle.py](https://github.com/tskwak111/esg-evidence-audit/blob/70da628a401b89b5ea2c08ee4243523ce99acb50/esg_pipeline/research_v4/evidence_bundle.py) — 1-270 (whole file in returned range); source allowlists and gold exclusion.
- [esg_pipeline/research_v4/run_signature.py](https://github.com/tskwak111/esg-evidence-audit/blob/70da628a401b89b5ea2c08ee4243523ce99acb50/esg_pipeline/research_v4/run_signature.py) — 1-230; canonical hashing and source/request/postprocess identity.
- [esg_pipeline/research_v4/content_cache.py](https://github.com/tskwak111/esg-evidence-audit/blob/70da628a401b89b5ea2c08ee4243523ce99acb50/esg_pipeline/research_v4/content_cache.py) — 1-240; cache schema/status and local locking.
- [esg_pipeline/research_v4/evidence_grader.py](https://github.com/tskwak111/esg-evidence-audit/blob/70da628a401b89b5ea2c08ee4243523ce99acb50/esg_pipeline/research_v4/evidence_grader.py) — 1-220; method OR verification; target e2 ANY shortcut.
- [esg_pipeline/research_v4/llm_extraction_adapter.py](https://github.com/tskwak111/esg-evidence-audit/blob/70da628a401b89b5ea2c08ee4243523ce99acb50/esg_pipeline/research_v4/llm_extraction_adapter.py) — 1-200; strict optional guards, extraction without grade.

## 실제로 수행하지 않은 검증
기존 repo clone/의존성설치/전체 pytest, 실제 ESG PDF 의파서출력/좌표/screenshot 검사, 한국어 tablebenchmark, 실제 Bedrock 태깅3회, AWSdeploy/cost 측정, 공식조항번호/현행규제확정은수행하지않았다. 원문 파일/선택코드/공식기술문서정독과문서패키지기계검증을수행한것이다. 라이선스는기술선택의검토 gate 이지본응답의법률자문결론이아니다.

## 명세에서 새로 결정한 값
100MiB/300pages, token budgets, lease120초/heartbeat30초, retry 총3회, chunk/token 한도, UX 토큰, API 응답/DBkeys/작업 DAG/초기 SLI 목표는이번개발설계의제안값이다. 외부자료가그수치를실증했다고주장하지않는다. 실제 계정가격/성능을측정해 version 변경과회귀검증을거쳐조정한다.


## 추가 확인 S16
[OpenDataLoader v2.5.7 schema.json](https://github.com/opendataloader-project/opendataloader-pdf/blob/v2.5.7/schema.json)의 1–180행을 직접 확인했다. bbox 순서는 left/bottom/right/top, 페이지는 1-based로 명시돼 있다. blob은 `c797f3386bd6f633b9009bea675f82348ea442c9`다. 실제 파서를 실행한 것은 아니다.
