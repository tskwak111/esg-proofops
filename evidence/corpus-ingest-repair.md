# CORPUS-INGEST repair — evidence report

범위: `packages/proofops/application/uploads_security.py`와
`tests/acceptance/test_upload_security.py`만 수정했다. parser/profile/graph,
manifests/deps, corpus harness, Git 작업은 Root 소유로 손대지 않았다. 원본 PDF
50개는 읽기만 했고 어떤 바이트도 변경하지 않았다(아래 sha256 before/after 로 확인).
제품/클라우드 모델 호출은 하지 않았다.

## 1. Root가 발견한 두 실패의 진단

### 1-1. Samsung: `/AA`에 `/D → /Named`가 있다는 이유만으로 거부 (구 line 281)

`_inspect`의 기존 `forbidden` 집합에 `/AA` 자체가 들어 있었다. 어떤 딕셔너리든
`/AA` 키(추가 액션 표)를 갖고 있으면 그 표의 실제 내용(어떤 트리거에 어떤
action이 연결됐는지)을 보지 않고 즉시 `PDF_INVALID`로 거부했다. `/AA`는
합법적으로 `/D → {/S /Named, /N /NextPage}` 같은 순수 뷰어 내 탐색 액션을
담을 수 있는 컨테이너이며, 컨테이너의 존재와 위험한 내용은 별개다.

실제 파일을 직접 열어 확인한 결과(읽기 전용 진단, 앱 코드는 그대로 사용):

```
subtype_counts {'/Named': 345}
named_dests {'/GoBack', '/PrevPage', '/NextPage'}
```

345개의 `/AA` 항목 전부가 `/Named` + `{GoBack, PrevPage, NextPage}` 뿐이었다.
JavaScript, Launch, 원격/embedded 참조는 없었다.

### 1-2. KT: 100,001번째 객체에서 거부 (구 line 272)

기존 순회는 `pending.pop()`마다 `visited += 1`을 먼저 하고, `seen`(고유 노드)
중복 체크는 그 다음이었다. 즉 이미 방문한 공유 노드를 참조하는 또 다른 진입
경로가 있으면 그 노드를 다시 큐에 넣고 다시 `visited`를 올린 뒤에야 skip
했다. **pop 횟수**가 아니라 **고유 노드 수**가 예산이어야 하는데, 실제로는
pop 횟수를 예산으로 쓰고 있었다.

같은 파일을 고유 노드 기준으로 다시 순회해 실측했다:

```
unique dict nodes: 94887
unique array nodes: 33945
total unique nodes: 128832
raw indexed refs (xref+objStm): 67643
```

즉 KT 문서는 **고유 노드 수 자체가 128,832개**로, 중복 계산 버그를 고쳐도
현재 기본값 `max_objects=100,000`을 실제로 초과한다. 이는 카운팅 버그가
아니라 문서 규모의 문제다. 이 사실은 아래 "남은 게이트"에 있는 그대로
보고하며, 임의로 상한을 올려 통과시키지 않았다.

## 2. 최소 안전 수정

### 2-1. 중복 제거된 유계 객체 순회 (KT 클래스 버그 수정)

- `seen`(고유 `id(value)`) 체크를 **먼저** 하고, 이미 본 노드는 그 자리에서
  건너뛴다(재enqueue도 하지 않음).
- 예산 비교를 `len(seen) > limits.max_objects`로 바꿔 **고유 노드 수**를
  예산으로 쓴다. pop 횟수가 아니다.
- CPU/자원 상한(`cpu_seconds`, `timeout_seconds`, `memory_bytes`,
  `max_decoded_bytes`)은 그대로 유지했다. 디코딩 바이트 예산은 스트림 필터
  화이트리스트·순서 그대로다.

### 2-2. `/AA`/`/OpenAction`을 컨테이너가 아니라 내용으로 판정 (Samsung 클래스 버그 수정)

- `/AA` 자체를 `forbidden`에서 제거했다. `/OpenAction`도 마찬가지로
  "존재=거부"가 아니라 "내용을 검사"로 바꿨다.
- 새 `reject_dangerous_action_chain()`이 각 액션 딕셔너리를 명시적으로
  분류한다: **`/S`가 명시적 허용 목록(`/Named`, `/GoTo`)에 없으면 무조건
  거부**한다(missing `/S`, 알 수 없는 `/S`, 위험한 `/S` 모두 거부).
  - `/Named`는 `/N`이 순수 탐색 목적지 집합
    `{NextPage, PrevPage, FirstPage, LastPage, GoBack, GoForward}`에 있을
    때만 허용한다. `SaveAs`, `Print`, `GoToPage`, `Find` 등은 여전히 거부다.
  - `/GoTo`는 내부 목적지(`/D` 필수)만 허용한다. `/GoToR`(원격 파일),
    `/GoToE`(embedded 파일)는 원래의 전역 `forbidden` 집합에 그대로 남아
    이 분기에 도달하기 전에 차단된다.
  - `/Next` 체인(단일 또는 배열)을 재귀적으로 전부 검증한다. 체인 어디든
    위험한 링크가 있으면 문서 전체를 거부한다(깊이 32로 유계).
  - 이 검사는 페이지 트리에서 실제 도달 가능한지와 무관하게, xref/objStm에
    인덱싱된 모든 객체에 대해 수행된다(기존과 동일하게 전체 스캔 유지).
- 최상위 `forbidden` 키 집합(JS, Launch, SubmitForm, ImportData, GoToR,
  GoToE, Rendition, RichMedia, EmbeddedFiles/File, XFA)은 그대로 무조건
  차단이다. `/AA`/`/OpenAction` 검사와 별개로 어떤 딕셔너리에 있어도 걸린다.
- "포괄적 `/AA`/`/OpenAction` 검사 제거"는 하지 않았다. 오히려 검사를
  세분화해 hidden/unreachable 위치의 위험 action도 계속 fail-closed로
  차단한다(`test_indirect_action_subtype_in_unreachable_object_is_rejected`,
  `test_aa_next_chain_with_hidden_dangerous_action_is_rejected`).

### 2-3. 임계값 인플레이션을 하지 않은 부분

- `max_objects` 기본값(100,000)을 올리지 않았다. KT는 여전히
  `UPLOAD_LIMIT_EXCEEDED`로 거부되며, 아래 게이트에 명시했다.
- 암호화 빈 비밀번호 특례를 구현하지 않았다. `docs/09_BACKEND_SPEC.md:28`이
  "암호 PDF는 PDF_PASSWORD_REQUIRED... 비밀번호 수집/복구 기능은 P0에 없다"를
  이미 명시하며 빈 비밀번호 예외를 언급하지 않는다. 원문 계약에 없는 특례를
  임의로 추가하지 않고 기존 무조건 거부 동작을 그대로 두었다(§4 게이트 참고).

## 3. RED → GREEN

### RED (수정 전, 새 테스트 3개가 실패함을 확인)

```
uv run --no-sync python -m pytest tests/acceptance/test_upload_security.py \
  -k "aa_with_inert or aa_with_internal_goto or shared_object_fan_in" -v
```
결과: `test_aa_with_inert_named_navigation_is_accepted` FAILED
(UPLOAD_LIMIT_EXCEEDED — 당시는 `/AA` 자체가 거부됐던 것과 별개로 초기 실행이
자원 한도에도 걸렸음을 보여줌), `test_aa_with_internal_goto_destination_is_accepted`
FAILED, `test_shared_object_fan_in_does_not_inflate_object_budget` FAILED.
같은 실행에서 위험 액션 거부 테스트 12개는 이미 통과(보존해야 하는 동작).

### GREEN (수정 후)

```
uv run --no-sync python -m pytest tests/acceptance/test_upload_security.py -v
```
결과: `41 passed in 3.62s`. 전체 목록:
- 기존 무해 업로드/버전/동시성/VERSION_CONFLICT 테스트 유지 통과.
- 기존 URI/JavaScript/Launch active-action 미실행 테스트 유지 통과
  (`test_active_actions_do_not_fetch_or_execute`, 실제 소켓 리스너로 외부 접속
  시도가 없음을 확인).
- 기존 리소스 한도(bytes/pages/objects/decoded/timeout/memory) 거부 테스트
  유지 통과.
- 기존 Fargate 격리 템플릿 테스트 유지 통과.
- 기존 unreachable object 안의 `/Launch` subtype indirect 참조 거부 유지 통과.
- 신규 `test_aa_with_inert_named_navigation_is_accepted`: `/AA`+`/D→/Named`
  (`NextPage`) 수용.
- 신규 `test_aa_with_internal_goto_destination_is_accepted`: `/OpenAction`의
  내부 `/GoTo` 목적지 수용.
- 신규 `test_aa_with_dangerous_or_unknown_action_is_rejected`
  (parametrize 11종): JavaScript, Launch, GoToR, GoToE, SubmitForm,
  ImportData, Rendition, Movie, SetOCGState, `/Named`+`SaveAs`(허용목록 밖),
  `/S` 누락 — 전부 `PDF_INVALID`로 거부.
- 신규 `test_aa_next_chain_with_hidden_dangerous_action_is_rejected`:
  `/Named`(무해) → `/Next` → `/JavaScript`(위험) 체인 전체 거부.
- 신규 `test_shared_object_fan_in_does_not_inflate_object_budget`: 40개
  페이지가 공유하는 단일 리소스 딕셔너리가 고유 노드 1개로만 계산됨을
  `max_objects=400`으로 확인.

### 실제 코퍼스 before/after (원본 불변 확인 포함)

읽기 전용 임시 스크립트(`.local/_corpus_ingest_repair_verify.py`, 검증 후
삭제됨, 트래킹 fixture에 원본 바이트 없음)로 `verify_quarantined_pdf`를 실제
바이트에 직접 호출했다. 실행 전/후 sha256을 비교해 원본이 바뀌지 않았음을
같은 실행에서 확인했다.

| 파일 | 수정 전 결과 | 수정 후 결과 | 원본 sha256 불변 |
|---|---|---|---|
| Samsung_Electronics_Sustainability_Report_2025_KOR.pdf | `PDF_INVALID` (line 281, `/AA`) | `verified`, pages=87 | 확인(`342a99a1...8c5`, 호출 전/후 동일) |
| KT 2025 지속가능경영보고서.pdf | `UPLOAD_LIMIT_EXCEEDED` (line 272, visited=100001) | `UPLOAD_LIMIT_EXCEEDED` (여전히, 아래 §4 게이트) | 확인(`9c6394eb...7dc`, 호출 전/후 동일) |

Samsung은 1차 시도에서 `/Named`에 `GoBack`을 허용 목록에 없어 여전히 거부됐다.
실제 파일을 추적해 345개 `/AA` 항목이 전부 `/Named`+`{GoBack,PrevPage,NextPage}`
뿐임을 확인한 뒤 `GoBack`/`GoForward`(뷰어 히스토리 탐색, 코드 실행이나
외부 자원 접근이 없는 것은 `PrevPage`/`NextPage`와 동일한 성격)를 허용 목록에
추가해 두 번째 시도에서 `verified`로 통과했다. 이 반복 자체가 진단
과정이었음을 투명하게 남긴다.

## 4. 남은 게이트 (임의로 채우지 않음)

- **KT류 대형 문서의 `max_objects` 상한**: 128,832개 고유 노드는 현재
  기본값(100,000)을 실제로 초과하는 정당한 문서 규모다. 이 기본값을 올릴지,
  올린다면 얼마로 할지는 리소스/DoS 방어 정책 결정이며 이번 작업 범위인
  "보안 로직 최소 수정"을 벗어난다. Root/코디네이터가 결정할 입력이다.
  결정 전까지 KT는 `UPLOAD_LIMIT_EXCEEDED`로 남는다(가짜 통과로 만들지 않음).
- **암호화 빈 비밀번호 처리**: 원문 보안 계약(`docs/09_BACKEND_SPEC.md:28`)이
  이미 "암호 PDF → PDF_PASSWORD_REQUIRED, 비밀번호 수집/복구는 P0에 없음"을
  명시하고 빈 비밀번호 특례를 언급하지 않으므로 구현하지 않았다. 특례가
  필요하면 별도 사용자 승인이 있어야 한다.
- **다른 46개 코퍼스 파일의 개별 거부 원인**(`evidence/corpus-first-pass.md`
  §"실행 조건과 결과" 표의 `PDF_INVALID` 32건, `UPLOAD_LIMIT_EXCEEDED` 11건)은
  이번에 재분류하지 않았다. Root가 진단 지시에서 지정한 것은 Samsung/KT
  두 사례이며, 나머지는 각각 다른 원인(구조 오류/자원 한도)일 수 있어
  이번 최소 수정 범위를 넘는다.
- parser/profile/graph, corpus harness(`.local/corpus-first-pass/run_baseline.py`
  등), manifests/deps, Git 작업은 손대지 않았다(Root 소유).

## 6. 코디네이터 리뷰 반영 (2차)

Root 검토에서 4가지 추가 지적을 받아 반영했다.

1. **`/OpenAction` 직접 목적지 배열 vs `/Next` 액션 배열 혼동**: `/OpenAction`은
   액션 딕셔너리뿐 아니라 `[page /Fit]` 형태의 순수 목적지 배열일 수도 있다
   (PDF 32000-1 §12.3.2). `reject_dangerous_open_action()`이 배열이면
   `is_internal_destination()`으로 목적지로만 검사하고, 액션 체인 재귀에는
   들어가지 않게 분리했다.
2. **`/GoTo` `/D` 타입 검증**: `/D` 존재 여부만 보던 것을 `is_internal_destination()`
   으로 강화했다. name/string(Dests 트리 참조) 또는 `[page, fit-mode, ...]`
   형태이고 첫 원소가 실제 `/Page`|`/Pages` 딕셔너리를 가리킬 때만 허용한다.
3. **`/AA` 밖의 `/A`, `/Type /Action` 처리**: 주석(`/Annots`)·아웃라인의 직접
   `/A`, 그리고 컨테이너 없이 인덱싱만 된 `/Type /Action` 딕셔너리도 각각
   검증 경로에 추가했다. 단 `/A`는 **태그드 PDF의 구조요소(`/StructElem`)
   속성 객체/배열과 이름이 겹치므로**,가리키는 값이 `/S`를 가진 딕셔너리일
   때만 액션으로 취급하고 아니면 건너뛴다(`test_tagged_pdf_structure_element_
   attributes_are_not_treated_as_actions`).
4. **모든 `/S`를 전역 액션으로 취급하지 않기 vs 기존 위험-`/S` 가드 보존**:
   1차 시도에서 `/S`-in-forbidden 검사를 액션모양 딕셔너리로만 축소했다가,
   `/Type`이 없는 미도달 `/Launch` 딕셔너리(`test_indirect_action_subtype_
   in_unreachable_object_is_rejected`, 기존 테스트) 회귀를 유발함을 발견하고
   되돌렸다. 최종적으로 baseline 그대로 **`/S`가 위험 목록에 있으면 `/Type`
   유무·컨테이너와 무관하게 무조건 거부**를 유지했다(`/Type`은 스펙상
   optional). 대신 "전역 `/S` 취급"의 실제 문제였던 부분(무해한 `/Named`·
   `/GoTo`·`/URI` 값에 대해서만 상황별 additional context로 정밀 판단)은
   별도의 명시적 허용목록 경로(`reject_dangerous_action_chain`)로 처리해
   위험-서브타입 조기 거부와 무해-서브타입 정밀 검증을 분리했다.
5. **재귀 `/Next` 공유/순환 fan-out 유계화**: `chain_seen`(고유 액션 id 집합)을
   `reject_dangerous_action_chain` 안에서 유지해 같은 액션 노드를 가리키는
   여러 `/Next` 경로가 있어도 한 번만 검증한다. `depth<=32` cap과 별개로
   순환·다이아몬드 공유 구조에서도 유계 CPU를 보장한다.
6. **`/A`의 `/URI` 하위호환**: 기존 계약(`test_active_actions_do_not_fetch_or_
   execute[/URI-/URI]`)은 주석의 직접 `/A`에 있는 `/URI`(사용자 클릭 시에만
   발동, 절대 자동 실행되지 않음)를 무해한 저장 데이터로 승인하고 소켓
   접속이 전혀 없음을 검증한다. 이를 지우거나 약화하지 않고, `/URI`를
   "이 검사기는 절대 fetch하지 않는 저장 데이터"로 취급해 xref 스캔 순서와
   무관하게 일관되게 처리했다. 동시에 **`/AA`/`/OpenAction`을 통한 동일
   공유 `/URI` 액션은 여전히 무조건 거부**한다(자동 발동 트리거는 사용자
   제스처가 없으므로). xref 스캔이 모든 인덱스 객체를 부모와 무관하게
   독립적으로 방문하므로, "이미 검증됨" 플래그로 순서에 의존하는 방식은
   피하고, `/AA`/`/OpenAction` 호출부는 항상 엄격한(무-`/URI`) 허용목록을
   쓰도록 해 방문 순서와 무관하게 결정론적으로 거부되게 했다
   (`test_shared_uri_action_via_a_and_openaction_still_rejects_on_openaction`,
   `test_indirect_uri_action_accepted_regardless_of_xref_scan_order`).

### 반영 후 재검증

```
uv run --no-sync python -m pytest tests/acceptance/test_upload_security.py -q
  → 44 passed
uv run --no-sync ruff check packages/proofops/application/uploads_security.py tests/acceptance/test_upload_security.py
  → All checks passed!
uv run --no-sync mypy packages/proofops/application/uploads_security.py
  → Success: no issues found in 1 source file
```

실제 코퍼스 재확인(원본 불변, 읽기 전용 임시 스크립트 실행 후 삭제):

| 파일 | 결과 | 원본 sha256 불변 |
|---|---|---|
| Samsung_Electronics_Sustainability_Report_2025_KOR.pdf | `verified`, pages=87 | 확인 |
| KT 2025 지속가능경영보고서.pdf | `UPLOAD_LIMIT_EXCEEDED`(§4 게이트, 변경 없음) | 확인 |

## 7. 실행 명령 요약 (RED/GREEN, 최종)

```bash
# RED (1차 수정 전 커밋 기준으로 재현하려면 아래 3개만 별도 체크아웃해 실행)
uv run --no-sync python -m pytest tests/acceptance/test_upload_security.py \
  -k "aa_with_inert or aa_with_internal_goto or shared_object_fan_in" -v

# GREEN (현재 상태, 코디네이터 2차 리뷰 반영 포함)
uv run --no-sync python -m pytest tests/acceptance/test_upload_security.py -v
uv run --no-sync ruff check packages/proofops/application/uploads_security.py \
  tests/acceptance/test_upload_security.py
uv run --no-sync mypy packages/proofops/application/uploads_security.py
```

결과: 44 passed, ruff `All checks passed!`, mypy `Success: no issues found in
1 source file`. lint/type/unit 실제 실행이며 not_run 항목 없음(이 파일 범위
내에서). E2E/전체 pytest suite/전체 mypy(다른 패키지 포함)는 이번 작업
범위(파일 2개 소유)를 넘어 Root 통합 시 재확인이 필요하다.
