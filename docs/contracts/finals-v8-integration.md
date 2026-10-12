# I8 · v8 기본 정책 통합

사용자 `int-I8.md`에 따라 v7 `874f05f`에 K9 `a2a452e`를 통합한다.
새 실행 기본값은 `finals-20261012-v8`이며 SHA256은
`55675a8ada572b8012eae78d51d479df67112a7aa4fb0eb03baa22cdc6817d1a`다.
최종 K9 v5 정책에서 integration_profile만 변경한다. source/parser/추출 정책,
세 replica, Python 규칙 사다리, unknown/conflict/unreadable 보류는 유지한다.

K9의 구체적 이행·거버넌스 귀속과 같은 문단 Scope 정의 연결은
[K9 계약](finals-k9-attribution.md)을 따른다. LLM present 투표, verified 원문,
주장·기업·문서·위치 검증 없이는 present가 되지 않는다. 숫자·목표연도로 보충
Scope 인용을 전용하지 않는다. SBTi 방법 채택은 G8 검증 완료가 아니며 일반
개선 문장은 M4 구체적 실적을 만들지 않는다.

v7 SHA `0d10ccb21b953f5c29846438fb72538baf50ebd280c45d89b5adbf727c6c9efb`,
K9 v5 SHA `7c9b238a4b3d10d54f5400f5fda2cd395a52ed476b34865c3309c1f71810e6d5`와
v5/v6/K7/K8/F1/K9 v1–v4 pin·reader를 보존한다. 재개는 저장된 pin을 사용하며
새 기본값으로 소급 변경하지 않는다. 기존 tag/decision revision과 보고서는 불변이다.
v8 게시에서도 F1의 요청별 provider hold와 projection hash를 기록한다.

공개 API/DB schema·migration·dependency 변경은 없다. 로컬 검증 결과와 채택
판정은 `outputs/agent-results/R108-redesign/lab/perf/I8/I8-REPORT.md`와 해당
측정 JSON에 남긴다. 비용 USD0.80과 공유 USD25 원장을 동시에 제한하며,
accounting_pending 노출은 0으로 풀지 않는다.

배포 준비 입력은 `analysis_profile=finals-unattended-v2`, 위 v8 policy SHA,
workers8·batch100·4RPS·active_run1이다. 서버 Dockerfile Linux2CPU/4GiB 로컬
이미지에서 기존 LG13쪽·카카오30쪽/주장9쪽 입력을 검증한다. 재사용 파싱/OCR,
새 모델 호출, 원문 재검증을 구분하며 독립 의미 골드나 전체 보고서 정확도로
표현하지 않는다. push·배포·EC2/runtime.env/live.json 쓰기는 이 작업 범위 밖이다.

롤백은 새 v8 배정을 중단하고 v7 pin으로 새 실행을 만드는 방식이다. 이미
생성된 v8/K9 실행을 재개·게시할 때는 이 reader를 유지해야 한다. v7 전용
구버전은 v8 hash를 거부한다. 기존 결과를 덮어써 롤백하지 않는다.
