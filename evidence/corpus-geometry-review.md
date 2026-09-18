# GEOMETRY-DIAG — 8건 PARSER_GEOMETRY_INVALID 원인 조사 및 root 초안 검토

2026-09-09 KST. 읽기 전용 조사. 원본 PDF·product code는 수정하지 않았다.
소유 범위는 이 문서와 `.local/corpus-geometry-review/`뿐이다.

## 1. 재현과 원본 upstream JSON 보존

`.local/corpus-repair/final/results.json`의 8건 전부(SHA-256 기준)를 동일 표본
페이지로 다시 파싱해 같은 실패를 재현했다. `OpenDataLoaderParser`를 상속한
`CapturingParser`가 **기존 `_execute`를 그대로 호출**(`super()._execute(...)`,
실제 Java 21 / OpenDataLoader 2.5.7 서브프로세스, timeout·출력 크기·프로세스
트리 상한 모두 그대로 적용)한 뒤, `parse()`가 실패 시 임시 디렉터리를 삭제하기
*전에* `source.json`/`geometry.json`/`auxiliary.json`만 별도 scratch 경로로
복사했다. `source.pdf`는 복사·수정하지 않았다.

- 스크립트: `.local/corpus-geometry-review/diagnose_geometry.py`
- 실행: `uv run --no-sync python .local/corpus-geometry-review/diagnose_geometry.py`
- 결과: 8/8 `PARSER_GEOMETRY_INVALID` 재현, 8/8 upstream JSON 캡처 성공
  (`.local/corpus-geometry-review/captured/<sha256>/`).

| 문서 | SHA-256(8자) | 표본 physical_page |
|---|---|---|
| 2026_HDEC_Sustainability_Report_K.pdf | 76dcbaaa | 3, 92, 176 |
| HMM_SUSTAINABILITY_REPORT_2025.pdf | 918caaf1 | 3, 67, 127 |
| 2025 HD현대일렉트릭 지속가능경영보고서_KOR.pdf | a9f4800b | 3, 66, 125 |
| 2025poscofuturem.pdf | 65070d88 | 3, 70, 133 |
| LGChem_Sustainability_Report_2025_KOR.pdf | c6395dd2 | 3, 59, 111 |
| 에코프로비엠_지속가능경영보고서_2025.pdf | 1b78d3ba | 3, 61, 114 |
| Hyundai Mobis SR 2026_0624_FFF.pdf | 3e9dc8ab | 3, 97, 186 |
| Kakao_SustainabilityReport2025_KR.pdf | 43804a2d | 3, 69, 131 |

## 2. 원인 노드와 좌표 변환 재현

`.local/corpus-geometry-review/inspect_captures.py`가 실제 `_batch()`의
non-auxiliary/auxiliary 두 변환 경로를 동일하게 재현해 각 캡처의 `source.json`
(OpenDataLoader 1차 후보)과 `auxiliary.json`(pdfplumber 보조 후보)을 모두
순회하고, `canonical_bbox_from_native`가 실패하는 노드를 특정했다.
전체 결과: `.local/corpus-geometry-review/inspect_results.json`.

| 문서 | 오프너 수 | 배치 | 최대 초과폭(pt) |
|---|---:|---|---:|
| 2026_HDEC | 2(1차) + 32(보조) | primary image, aux table/cell | 1.2 / 8.5 |
| HMM | 30(보조만) | aux table/row/cell | 8.4–8.5 |
| HD현대일렉트릭 | 19(보조만) | aux table/row/cell | 8.5 |
| 2025poscofuturem | 1(1차) | primary text block | 18.1 |
| LGChem | 2(1차) | primary image | 0.3 / **95.3** |
| 에코프로비엠 | 7(보조만) | aux table/row/cell | 0.4 |
| Hyundai Mobis | 1(1차) | primary image | 1.1 |
| Kakao | 5(1차) | primary text/table/cell | 8.5–8.7 |

모든 실패 페이지에서 `crop_box == media_crop_box`, `rotation=0`이었다.
즉 CropBox와 MediaBox가 같은 단순 페이지이며, affine 변환의 회전/원점
분기(90/180/270도, crop 이동)는 이번 8건 어디에도 관여하지 않는다.

## 3. bleed/이미지 extent 대 transform 버그 판별

`canonical_bbox_from_native`가 재현한 실패는 두 그룹으로 나뉜다.

**(A) 표 경계 소폭 초과 — 6개 문서(2026_HDEC, HMM, HD현대일렉트릭, 2025poscofuturem,
에코프로비엠, Kakao)의 다수 오프너.** 초과폭은 대부분 5.6~8.7pt, 항상 표/셀/행의
왼쪽·아래 경계에서 음수(`x0<0` 또는 `y0<0`)로 나타난다. pdfplumber 보조 배치는
`page origin`을 빼는 shift 후 media crop의 역행렬을 적용하는데, media와 crop이
동일한 이번 경우 그 자체는 버그가 아니다. 초과폭이 항상 셀 격자 전체에서 동일하게
반복되는 고정값(예: -8.504)인 것은 해당 표가 페이지 여백보다 살짝 넓게 그려진
실제 원본 표/음영 배경(전형적 "표 배경이 본문 여백을 살짝 침범" 패턴)이거나,
pdfplumber 자신의 셀 경계 추정이 살짝 과대추정된 것을 그대로 반영한 값으로
보인다. 자체 affine 합성 로직의 회전/이동 버그로는 설명되지 않는다 — crop=media,
rotation=0이므로 to_native/to_canonical은 순수 y-flip 하나뿐이고, 그 결과가
독립적으로도 동일 방향·동일 크기로 어긋난다.

**(B) 이미지 extent가 페이지를 크게 벗어남 — LGChem(95.3pt), 2025poscofuturem의
본문 텍스트 블록(18.1pt), Hyundai Mobis 이미지(1.1pt), 2026_HDEC 이미지(1.2pt).**
LGChem의 두 이미지는 각각 페이지 높이 1191.12pt에 대해 y1=1131.12/1286.371로,
후자는 페이지보다 위로 95pt 더 크게 나온다. 이는 원본 PDF에 실제로 존재하는
전면/블리드 이미지(표지·섹션 도입부 등에서 흔한, 인쇄 여백을 넘는 배치)를
OpenDataLoader가 그대로 보고한 값일 가능성이 raw JSON 수준에서는 가장 크다.
**다만 이번 조사는 OpenDataLoader가 보고한 bounding box 자체가 실제 렌더링
위치와 일치하는지 공식 뷰어로 왕복 검증하지 않았다** — docs/27 좌표 스키마
각주가 명시하듯 그 왕복 검증은 별도 구현 단계 시험이며, 이번 조사 범위 밖이다.
따라서 "실제 원본의 블리드 이미지"와 "OpenDataLoader 자체의 extent 계산 버그"를
이번 근거만으로 확정 구분할 수 없다. classify_offense 휴리스틱은 media/crop이
항상 동일해 두 그룹을 분리하지 못했다(모두 `beyond_media`로만 표시됨) — 이
휴리스틱의 한계로 기록한다.

**결론:** 8건 모두 우리 쪽 affine 합성(`to_canonical_affine`/`_compose_affine`/
`invert_affine`)의 회전·이동 처리 버그로 재현되지 않는다. rotation=0·crop=media인
가장 단순한 케이스에서만 실패했고, 회전/이동 분기가 관여하는 케이스는 이번
8건에 없었다. 원인은 (A) upstream 파서(주로 pdfplumber 보조 배치)의 표/셀
경계 소폭 초과, (B) 원본 문서의 실제 큰 이미지 extent(OpenDataLoader가 그대로
보고) 둘 중 하나로 보이며, 최종 확정에는 공식 렌더러 왕복 검증이 필요하다.

## 4. 페이지별 물리 페이지·타입 카운트

전체 상세: `inspect_results.json`의 `per_page_type_counts`(원문 전체 텍스트는
포함하지 않음, `aux:`는 pdfplumber 보조 배치 카운트). 요약:

| 문서 | 3p 타입 수 | 중간p 타입 수 | 후단p 타입 수 |
|---|---|---|---|
| 2026_HDEC | text/heading 다수 | image 2, table류 다수 | — |
| HMM | table류(1차+보조) | table류(1차+보조) | table류(1차+보조) |
| HD현대일렉트릭 | table류(보조 다수) | table류(보조) | table류(보조) |
| 2025poscofuturem | text block 1(초과) | — | — |
| LGChem | image 1(초과) | image 1(초과) | — |
| 에코프로비엠 | — | table류(보조) | — |
| Hyundai Mobis | image 1(초과) | — | — |
| Kakao | text/table(초과) | table/cell(초과) | — |

## 5. 후보-단위 invalid geometry 보존 방식 검토 (root 초안)

Root가 구현한 실제 diff를 코드로 확인했다(수정하지 않음, 읽기만 함):

- `geometry.py`: `project_native_bbox`(순수 affine 투영, 경계 검사 없음)를
  분리하고 `canonical_bbox_from_native`가 이를 감싸 경계 검사를 유지한다.
- `graph_fusion.py`: `CandidateBlock.bbox`는 `canonical_bbox_from_native`가
  `DomainValidationError`를 던지면 `None`을 반환(예외를 삼키지 않고 명시적으로
  잡아 `None`으로 전환)한다. `has_invalid_geometry`는
  `source.native_bbox is not None and bbox is None`으로, "원래 bbox가 있었는데
  경계 검사에서 떨어진" 경우만 True다. `fuse_candidates(..., fusion_version=3)`은
  invalid-geometry 후보를 다른 어떤 후보와도 매칭하지 않는다(`_matches`가
  `left.bbox is None or right.bbox is None`에서 즉시 `False`) — 항상 단독
  singleton 그룹이 되어 `quality="unlocated"`로 떨어지고, 이후
  `source_geometry_invalid`/`state="unreadable"` 이슈로 재분류된다. **원문
  요구(raw/native bbox·affine 보존, canonical location·SourceRef 미부여, open/
  unreadable 유지)를 정확히 만족한다.** `fusion_version` 1/2는 여전히 invalid
  geometry 후보가 있으면 즉시 `ValueError`로 거부해 레거시 산출물 재생 경로를
  오염시키지 않는다.
- `normalize.py`(`_observation`): 바인딩된 블록 중 하나라도
  `has_invalid_geometry`면 `state="unreadable"`, `parsed=None`으로 강제하고,
  `refs`에서 `candidate.has_invalid_geometry`인 후보를 제외한다. 숫자·SourceRef
  둘 다 무효 후보를 근거로 만들 수 없다.
- 유효한 블록(다른 표/문단)은 영향받지 않고 계속 진행된다 — `_matches`가
  kind/page/context/IoU 기준으로 별도 그룹을 유지하므로 8건 문서의 나머지
  블록은 이번 변경으로 손실되지 않는다.

**보존 방식 자체는 원문 요구와 일치한다.** raw_bbox/native_bbox/affine은
`CandidateBlock`/`NativeSource`에 그대로 남아 있고(`parser_bbox`,
`parser_to_canonical` 필드가 `__post_init__`에서 canonical 기대값과의 일치까지
검증), canonical location과 SourceRef는 명시적으로 차단된다.

## 6. 하류 caller 우회 위험 (root가 독립적으로 재추적할 부분)

캡처된 데이터에는 없고 코드 검토로만 확인한 사항이다. 아래 각 caller가
`has_invalid_geometry`/`quality`를 직접 다시 확인하는지 표로 정리한다.

| Caller | invalid geometry 재확인 방식 | 우회 위험 |
|---|---|---|
| `normalize.py::_observation` | `has_invalid_geometry` 명시 확인 + `quality != verified` | 없음 |
| `domain/numeric.py` | `block.quality != "verified"`로 우선 차단 | 없음 |
| `evidence/citations.py::verify_source_ref` | `ref.bbox is None` **and** `block.quality != "verified"` 이중 확인 | 없음 |
| `application/assurance.py` | `block.quality == "verified"` 확인 후에만 `candidates[winner]` 접근 | 없음 |
| `evidence/binding.py` | `block.quality != "verified" or block.winner is None`로 사전 차단 | 없음 |
| `evidence/packet_guard.py` | 텍스트를 신뢰하기 전에 항상 `verify_source_ref` 재호출 | 없음 |
| `application/claims.py` | `block.quality not in ("verified","unverified")`로 제외(→ exclusion, state 대부분 "unknown") | 없음 (단, 아래 §6.1 참고) |
| **`application/ingest/gri.py::build_gri_index`** | **`block.winner is None`만 확인. `winner=0`이라 통과 후 `block.source_ref()`를 예외 처리 없이 호출한다.** | **가용성 결함 있음 — 근거 위조 아님, §6.2 정정 참고** |
| `evidence/retrieval.py`(GRI 소비부) | `verify_source_ref(...).verification_state == "verified"` 재확인 후에만 `gri_pages`에 반영 | 없음 (retrieval 경로 자체는 안전) |

### 6.1 claims.py의 잔여 관찰 (경미, 문서화 목적)
`block.quality not in ("verified","unverified")` 분기는 invalid-geometry
singleton(`quality="unlocated"`)을 올바르게 배제한다. 다만 exclusion의 `state`
매핑(`{"conflicted":"conflict","unreadable":"unreadable"}.get(block.quality,"unknown")`)에는
`"unlocated"`가 없어 `state="unknown"`으로 떨어진다. 클레임 생성 자체는 막히므로
증거 신뢰도 우회는 아니지만, 감사자가 "unlocated 때문에 제외"와 "다른 이유로
unknown" 상태를 구분하려면 `ClaimExclusion`의 `quality` 필드(있음, `block.quality`
그대로 저장)를 봐야 한다는 점을 남긴다.

### 6.2 정정 — CanonicalBlock.source_ref()는 원본 native_bbox에 대해 엄격 검사를 다시 수행한다
이전 초안에서 "invalid-geometry singleton은 `winner=0`이므로 `source_ref()`가
`bbox=None`인 unlocated SourceRef를 조용히 반환한다"고 적었는데, 이는 실제
구현을 잘못 읽은 것이다. `CanonicalBlock.source_ref()`(`graph_fusion.py`)는
`canonicalize_source_ref(block.source, block.geometry, ...)`를 호출하고, 이
함수는 내부에서 `.bbox` 프로퍼티와 동일한 엄격 함수
`canonical_bbox_from_native(source.native_bbox, geometry)`를 다시 실행한다.
`.bbox` 프로퍼티만 예외를 잡아 `None`으로 바꾸고(`graph_fusion.py`의
`CandidateBlock.bbox`), `source_ref()`/`canonicalize_source_ref`는 그
`DomainValidationError`를 잡지 않고 그대로 전파한다. 이는
`tests/acceptance/test_geometry_issues.py::test_outside_page_candidates_survive_without_a_usable_location`로
직접 확인했다(`with pytest.raises(DomainValidationError): bad.source_ref()`,
실행: `uv run --no-sync pytest tests/acceptance/test_geometry_issues.py -q` →
2 passed). 같은 파일의
`test_bad_value_geometry_remains_unreadable_even_with_forged_quality`는
canonical `quality`를 `"verified"`로 강제 위조해도 `normalize_tables`가 해당
관측치를 `value_state="unreadable"`/`value_decimal=None`으로 유지하고
`source_refs`에서 invalid-geometry 블록을 제외함을 함께 확인한다.

**정정된 결론: `build_gri_index`(`gri.py:142`)가 `block.source_ref()`를
try/except 없이 호출하므로, invalid-geometry `table_row`가 GRI 코드/페이지
참조 정규식에 매칭되면 `build_gri_index` 자체가 `DomainValidationError`를
전파하며 실패한다.** 이는 조용한 근거 위조/우회가 아니라 **가용성/예외처리
결함**이다 — 유효하지 않은 지오메트리를 가진 GRI 행이 있으면 문서 전체의 GRI
인덱스 구성이 예외로 중단될 수 있다(다른 유효한 GRI 행을 포함해서). 이번
8건 샘플 지오메트리 오프너 중 `kind="table_row"`이며 GRI 코드 패턴에 매칭되는
사례는 캡처된 데이터에서 직접 확인하지 않았으므로, 이 결함이 오늘 시점에
실제로 트리거되는지는 **미확인**이다 — 코드 경로상 가능성만 확인했다.
`evidence/retrieval.py`가 GRI 엔트리를 소비하기 전에 이미
`build_gri_index`가 예외 없이 완료되어야 하므로, 잘못된 근거가 새는 방향이
아니라 인덱스 구성이 막히는 방향의 위험이다. root가 독립적으로 판단할 수정
방향(코드는 건드리지 않음, 제안만): `gri.py`에서 `block.source_ref()` 호출을
`block.quality in ("verified", "unverified")` 확인 또는
`try/except DomainValidationError`로 감싸 해당 행만 건너뛰고 나머지 GRI
인덱스는 계속 구성되게 한다(다른 안전 경로들과 동일한 "읽기 시점 재검증"
패턴).

### 6.3 API 레이어 확인 — source preview의 강등 처리 (root 수정, 코드 읽기로 확인)
`apps/api/src/proofops_api/routers/sources.py`를 실제로 읽어 확인했다.

- `GET /v1/runs/{run_id}/sources/{source_id}`(`source_get`)는 `block.source_ref()`를
  무조건 호출한다. invalid-geometry 블록에서 이는 `DomainValidationError`
  (`ValueError` 서브클래스)를 던지고, 라우터의 `except (ValueError, ...)`가
  이를 잡아 `failure(exc)` → **409 `ARTIFACT_UNAVAILABLE`**로 응답한다. 즉
  "SourceRef API는 invalid geometry에 대해 409를 유지한다"가 실제 코드로
  확인된다.
- `GET /local/sources/{run_id}/{source_id}?preview=page`(실제 PNG 렌더)는
  `render_page_preview(original, candidate.source.physical_page,
  candidate.geometry)`를 사용해 렌더링한다 — `.bbox`나 `.source_ref()`에
  의존하지 않는다. 하이라이트 오버레이 여부만 `_highlight_allowed(block,
  graph.issues)`가 결정하는데, 그 함수는
  `if block.bbox is None or block.winner is None or ...: return False`로
  **`block.bbox is None`을 가장 먼저, 단락 평가로 확인**하므로
  invalid-geometry 블록에서는 `block.source_ref()`(그 함수 안에서 호출됨)에
  도달하지 않고 곧바로 `"X-Source-Highlight": "unavailable"`을 반환한다. 렌더
  자체는 계속 성공한다 — PNG/원본 PDF 응답 경로(`preview=None`, 전체 PDF
  반환)는 이 로직과 무관하게 항상 동작한다.
- 정리: invalid-geometry 소스에 대해 구조화된 SourceRef를 요청하면 409로
  명확히 막히고(근거 위조 없음), 페이지 미리보기(PNG/원본 PDF)는 계속
  열람 가능하되 하이라이트 오버레이만 비활성화된다. 이는 §00 "검증된 원문
  근거 없이 present를 인정하지 않는다"와 일치하며, 사람 검토자가 원본을 계속
  볼 수 있어야 한다는 요구도 함께 만족한다.
- 실행 확인: `uv run --no-sync pytest tests/acceptance/test_geometry_issues.py -q`
  → `2 passed`(§6.2 인용 근거). `uv run --no-sync pytest
  tests/integration/test_source_api.py -q` → `5 passed, 2 warnings`(이 파일이
  `X-Source-Highlight`/preview 경로를 다룬다; 개별 assertion 문구까지는 다시
  읽지 않았고 pass/fail 결과만 인용한다). 두 명령 모두 이번 조사에서 실제로
  실행했다.

## 7. 하지 않은 것 / 범위 제한

- 원본 PDF를 수정하거나 좌표를 잘라내거나 만들어내지 않았다. 실패한 8건은
  여전히 실패로 남는다(코드 수정은 root 소유).
- OpenDataLoader가 보고한 이미지 extent가 실제 페이지 렌더링과 일치하는지
  공식 뷰어 왕복 검증은 수행하지 않았다(§3(B) 한계로 명시).
- root의 실제 fusion_version=3 diff에 대한 unit/contract 테스트 실행은 이번
  작업 범위(read-only 리뷰)가 아니므로 별도로 확인하지 않았다 — root가
  독립적으로 실행·기록해야 한다.
- `.local/corpus-geometry-review/parser-artifacts/`에 생성된 실제 파싱 산출물은
  scratch이며 `.local/corpus-repair/`의 기존 매니페스트와 분리되어 있어 기존
  산출물을 덮어쓰지 않았다.

## 8. 재현 파일

- `.local/corpus-geometry-review/diagnose_geometry.py` — 8건 재파싱 + upstream
  JSON 캡처(읽기 전용, `_execute` 상속 호출 후 복사만 추가).
- `.local/corpus-geometry-review/diagnose_results.json` — 재현 결과.
- `.local/corpus-geometry-review/inspect_captures.py` — 실제 변환 로직 재현 +
  오프너 노드 특정.
- `.local/corpus-geometry-review/inspect_results.json` — 오프너 상세 + 페이지별
  타입 카운트.
- `.local/corpus-geometry-review/captured/<sha256>/` — 8건의 실제
  source.json/geometry.json/auxiliary.json (원본 upstream 그대로, 가공 없음).

## Coordinator resolution — 2026-09-09

The GRI availability finding in §6.2 is resolved: `build_gri_index` skips rows
with invalid native geometry while preserving those rows and their quality issues
in the graph. A failing regression reproduced the exception before the guard;
the final 32-test scope passes after the correction. The earlier review results
above describe the reviewed draft, not unresolved final defects. Final evidence:
[corpus-geometry-verification.md](corpus-geometry-verification.md).
