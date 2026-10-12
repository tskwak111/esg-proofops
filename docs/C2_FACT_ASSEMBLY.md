# C2 / DEC-43 내부 사실 조립 계약

`management-direct-certification-c2-v1`은 명시적으로 선택하는 로컬 파일럿이다.
`analysis_profile.policy_for`로 읽을 수 있지만 `publication_policy_for`는 항상
`C2_PUBLICATION_DISABLED_COORDINATOR_ACTIVATION_REQUIRED`로 거절한다.
기본 profile, 기존 snapshot, 규칙팩과 등급 엔진은 변경하지 않는다.

`FactAssemblyReceiptV1`은 기존 불변 review input 안의 opaque artifact로 저장한다.
공개 API 필드/enum과 DB column은 추가하지 않아 migration은 없다. 미지원 schema,
policy/hash, tenant/document/packet, raw receipt 변조는 reader에서 거절한다.
롤백은 새 profile 생성 중단이며 이미 저장한 reader와 artifact는 보존한다.

원시 추출 3회 각각의 request/provider/cache identity와 model/prompt hash를 보존한다.
각 원시표의 원문 SourceRef를 독립 검증한 후 동일 Python matcher를 실행한다.
원시표와 계산 결과/결과 hash는 분리하며, 검증된 활동·기간·범위 tuple과 요소 상태가
3/3 같은 경우에만 후보를 만든다. 다른 인용 길이는 허용하지만 다른 차원을 합치지 않는다.
범위는 **각 회차가 직접 인용한 M2 근거**에서만 계산한다. 보조 dimension 인용은
그 M2 근거 안에 있어야 한다. 다른 회차나 packet 전체에서 미기재 값을 보충하지 않는다.

M3는 동일 원자 활동의 직접 ISO 14001 인증 문구만 지원한다. 보고서 전체 보증,
GRI 같은 쪽, 다른 시설/기간이나 여러 의견서 합산을 적용하지 않는다. 일반 보증서나
GHG P4 조립의 생산 권한은 이 파일럿에 포함하지 않는다.
보고연도 문맥은 명시 연도가 없는 현재 인증 주장에만 같은 쪽 원문으로 연결한다.
인증 유효기간을 추정하지 않고 카카오의 2026 확대를 2025로 바꾸지 않는다.
조건부 trigger의 false는 완전히 검증된 원자 주장의 해당 주장 여부에 한정한다.
근거 요소의 unknown/conflict/unreadable을 absent로 변환하지 않는다.

R7의 두 원본 SHA에 고정한 의견서 문자 구간은 발견용이다. LG p118의 두 의견서를
서로 겹치지 않는 문자 구간으로 나누고 카카오는 5개 의견서와 검토된 뒤표지를 분리한다.
알 수 없는 빈 페이지는 뒤표지로 간주하지 않는다. 기존 EV1은 새 선택 페이지 receipt에
그대로 재사용하고 표 헤더/불일치 문구는 보류한다.
ISO 파일럿의 선택 스팬 reader는 원본 글리프 구간·지역 주석·레이아웃·렌더 OCR을
확인하며 부모 문단을 승격하지 않는다. 원문↔발췌는 기존 H1의 불변 page-map을 사용한다.

`evaluation/c2_pilot.py`는 prepare → requests → SIM1 codex-sim → assess를 실행한다.
실제 API는 명시적인 `api` 단계에서만 실행하고 C2 USD 0.40 및 R108 누적 fence를 적용한다.
모델 JSON은 grade/label을 받지 않는다. provider 원장과 원시 응답 sidecar hash를 확인하고
각 실제 회차의 원문·귀속 검증 결과를 순수 Python 엔진에 넣는다.
기존 I9에서 같은 내용·해시의 승인된 규칙팩을 **원래 승인 테넌트에서** 재사용한다.
새 승인자를 만들어 넣거나 테넌트 간 승인 정보를 복제하지 않는다.

저장/재개/reload/If-Match/export 테스트는 합성 checkpoint 경계와 실제 SQLite/reader를
사용한다. 새 profile의 공개 판정과 검토를 통한 활성화는 차단한다. 기존 profile의
사람 태깅 수정 및 새 revision 생성은 그대로 유지된다. 운영 E2E/배포 활성화는 별도다.
