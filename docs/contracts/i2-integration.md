# I2 통합 정책 계약

I2는 I1 `e5f3a0b`에 J6 fixture, J1 HTTP 오류 sidecar, J3 reader와
선택 인용 분리 기능을 순서대로 통합한다. 공개 API·DB column·판정 규칙의
변경이나 migration은 없다. 오류 sidecar는 J1의 별도 진단 정책 해시로
기록하며 W3의 quota 구분·Retry-After·미정산 비용 보존을 유지한다.

기본 `finals-unattended-v2`는 통합 프로필 `finals-20261011-v2`를 선택한다.
최종 정책 SHA256은
`1a02f8e5e4ecb468e3cabb718de2c572f6f781cb9625f5d4e3d3f6b3cc62c7cf`다.
I1 v1 hash `df58e8330bb2dbb46cc6b3f3690ca6a44d0c31f2cdc20a4c387569ebd131f37c`
및 이전 정책·receipt·revision·reader는 기존 해시로 읽는다.

J3 통합 후보 hash
`f5696b7b4850a190ebe9791e2174d28c7f5a1197c7a0092508ad3ca8c5cd41ae`는
무료 동결 입력 재생에서 재현 70/156, 정밀 70/75(93.33%), false_verified 0을
기록했다. I2의 95% gate에 미달하여 **기본값에서 제외**했다. 이 후보는
재생만 허용하고 신규 publication pin으로 거부한다. J3의 원래 opt-in
`finals-unattended-j3-v1` 정책 hash와 선택·부모/자식 인용 이력은 유지한다.
Hosted 선택 목록에도 J3를 추가하지 않는다. 기존의 명시적인 J3 pin은 계속 읽는다.
최종 v2의 추출·태깅 옵션은 I1 v1과 같으므로 최종 무료 재생 근거는 I1을
그대로 재사용한다. 수치는 DL3 draft 문자 1:1 proxy이며 의미·등급 정확도가 아니다.

`python -m evaluation.i2_replay`는 I1과 같은 정답 8쪽·LG 13쪽에서
후보를 검토하고 새 인용의 원문 검증을 수행한다. 네트워크와 운영 revision
쓰기는 금지한다. `python -m evaluation.i2_live`는 NAVER p88·기아 p26만
실호출하며 단독 workers16, 두 실행 합계 USD0.30 원장을 사용한다. 파싱/OCR
응답은 저장본이며 원문 가드는 다시 실행한다. 기존 원장·캐시는 덮어쓰지 않는다.

Rollback은 향후 기본 정책 배정을 I1로 되돌리는 코드 변경으로 수행하고,
새 정책 reader·실행·sidecar를 보존한다. 구버전이 새 pin을 모르면 거부해야 한다.
J4/W1/W2, stage overlap, push·배포·EC2/runtime.env·클라우드 변경은 포함하지 않는다.
