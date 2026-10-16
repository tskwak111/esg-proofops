# J8 표 셀 후보 정책

`finals-unattended-j8-v1`은 J3에서 파생한 opt-in이다. 기존 J3/W9 분석·추출
해시, 기본 정책, frozen reader 및 저장된 receipt/revision/report는 유지한다.
새 실행은 `extraction_j8`, J3, W9, PB1, source-ID와 table-row 옵션을 함께
동결한다. 분석 정책은 셀 후보 정책 해시를, 추출 정책은 후보 계약과 새 프롬프트를
고정한다. 런타임 설정과 worker composition은 같은 옵션·해시를 검증한다.

일반 표에서는 실제 parser origin cell과 명시 `•` 경계만 후보로 사용한다.
행·열 span의 중복, 누락, 음수/잘못된 범위, 원문 grid 불일치를 거부한다.
같은 parser·문서·페이지의 table_parent 소속을 확인하고, 존재하는 좌표는
원문 표시 좌표계 및 부모 영역 안에 있어야 한다. 없는 좌표는 unlocated로
보존하며 native v10 검증 이전에 verified를 부여하지 않는다.

머리 셀·각주·일반 소개는 문맥이다. 시행연도가 적힌 설비 이름은 개선방안/효과
행이 명시된 적용 행렬에서만 실제 시행 후보가 된다. KPI의 첫 열에 있는 독립
행동은 후보이며, 구체 수단 항목이 있다는 이유로 제외하지 않는다. 글머리가
붙은 일반 소개는 문맥으로 두되 명명된 개발·적용 시스템은 별도 후보로 유지한다.
계획/달성 열의 같은 행에서 본문이 정확히 같고 종결 `완료`만 다른 경우에만
달성 후보를 남긴다. 사업장이 다른 열·수치·연도·조건의 차이는 합치지 않는다.
빈 셀의 무조건 forward-fill, 셀을 넘는 인용이나 주어·수치·연도 합성은 금지한다.

연도별 수치 표는 W9의 최신연도 성과 행과 과거연도 비교 metadata를 유지한다.
숫자·단위·연도 검증이 실패한 표에 일반 셀 fallback으로 값을 인정하지 않는다.
후보와 parent_context는 입증 근거 승인이 아니다. LLM은 선택·태깅만 수행하며,
새 인용마다 원문 검증/귀속/태깅을 거친다. 부모 verified/present/등급을 복사하지
않는다. unknown/conflict/unreadable, Python 판정 및 인간 If-Match 계약은 유지한다.

공개 DTO·DB column 변경 및 migration은 없다. 내부 profile allowlist만 확장한다.
Rollback은 새 정책의 생성·배정을 중단하고 이미 만든 J8 snapshot reader를
보존하는 방식이다. 구버전에서 미지원 정책을 기존 정책으로 바꿔 읽지 않는다.

`python -m evaluation.j8_cells_replay --lab <R108 lab> --output <새 디렉터리>
--fresh <J8 live-cells.json>`은 저장 선택과 제한적 새 선택을 원문 좌표로 다시
투영한다. 원래 요청·raw content·profile·receipt와 입력 해시를 검증하고 네트워크를
차단한다. 이전 모델이 새 wire를 읽었다고 표시하지 않으며 기존 선택을 보존한
추가 후보의 엄격 DL3 1:1 문자열 점수만 비교한다. AI draft 분모 156이며 독립
사람 R2 gold, 의미·요소·등급 정확도 및 새로운 전체 E2E 실행의 증거는 아니다.
