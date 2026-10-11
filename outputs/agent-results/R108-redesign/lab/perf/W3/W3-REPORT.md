W3 부분 완료: 처리 시간 개선·재생 검증·로컬 구현 완료; 필수 단계 겹치기는 checkpoint 불변 범위 확인 대기이며 미구현이다.
기준 a16e118, .local/w3-speed / w3-speed. deploy/public/Dockerfile Linux/arm64, CPU 상한8·메모리 cgroup16GiB·실제 Docker VM7.75GiB; 망 차단·응답150ms·프로파일러 OFF.
LG PA4 13쪽, PB5와 같은 NAVER/기아 주장4+4쪽 및 자동 근거23/24쪽의 PA9 저장 상태 사용; 실제 v6/v9 재생이며 v10 새 응답 실증은 아니다.
LG 전후136.186→88.299초(-35.2%): parse25.326→23.764 / extract80.979→36.566 / tag29.853→27.942.
기아 전후329.409→308.427초(-6.4%): parse126.972→112.358 / extract105.560→97.987 / tag96.840→98.055. NAVER 후74.239초.
모든 단독·동시 재생의 실제 wire 및 최종 전체 checkpoint가 각 원본과 동일. 단독 HTTP 재생LG356/기아272/NAVER119; 주장·요소·등급·unknown/conflict·replica·원문 provenance 보존.
HOSTED_MAX_ACTIVE_RUNS=2 실제 슬롯·문서 잠금·lease 경로 동시335.134초, active peak2, 합산 RSS 표본 최고1000.86MiB, 부모 제어 작업partial_blocked·예약 잔액0(공개 분석으로 발행하지 않음).
동시 LG parse/extract/tag26.027/38.966/32.659, 기아129.373/102.386/96.584초; 단독과 workers가16→8로 달라 순수 경합 효과로 단정하지 않는다. 기아 parse가 주 병목이다.
c8g 단독 조건부 추정LG175.98초≤6분·기아398.62초≤12분: 재생 stage wall에 저장 provider 지연과150ms의 차이를 정적 thread별 합산·최장 thread로 추가; summary.json. AWS 실측·보장은 아니다.
v5 전체 fresh v10 영수증 재사용: tenant/run·원문·graph·refs·reader/runtime·전체 canonical bytes 동일 조건만; 실패 셀candidate와 source guard 유지. v6/v9/v10 원시 OCR8MiB 캐시·padding0/6 두 process.
CPU: 사용량 조회1001 IDs를1002 SELECT→3 SELECT로 줄임. fresh scoped accounting·미정산·외부ID 제외·중복 제거·원장 금액 유지; 정산 캐시·DB migration·dependency 추가0.
파싱: 기존 단일 async 쪽 배치 POST 유지, GET 최대4 병렬·provider 순서/coverage 검증 유지. 쪽별 유료 POST를 분할하거나 원문 verifier/기존 연구 코드를 변경하지 않음.
권장 출발값: 1건 workers16, 2건 workers8씩(총16)·CPU OCR2씩·parse GET4. 계정 RPM/TPM 실측 전에는 안전 처리량 보장이 아니며 실제429·새 모델 canary는 not_run.
429: 전체 역할별 공동 gate, 향후 admission 절반·Retry-After 최소 준수·30초 초과 defer·동일 실패 dispatch 재시도0. quota/spend 별도 코드·broker accounting_pending/fence·비용 예약 보존. [공식 문서](https://developers.openai.com/api/docs/guides/rate-limits).
겹치기 gate: 첫 LG쪽8/8 원문 verified이나 page graph ad56285b…≠원본 wire d9b7d4cb…; inspection-corrected.json. 미래 전체 graph hash로 태깅하거나 wire 비교를 약화하지 않았고 stage_overlap=False 유지.
W3 정책 SHA f348b07e73e35c3d353666cc382ee7b8a756b7c3aa6838520ae6101dcad9bee4; private analysis_policy_sha256/CLI로만 opt-in. 기본v2·과거 정책 불변, 새 발행은 현재/W3만; rollback은 새 실행 pin 제거·기존 W3 readers 보존(CONTRACT.md).
검증: Linux 관련230통과, 최종 rate/기존 cache/provider guard76통과(일부 중복). ruff·mypy19 Python·architecture·git diff-check·production Docker build 통과; 명령/로그·self-review는 summary.json.
한계: 공유 호스트 단일 실험·초기 LG baseline에 source probe 병행; Java/Upstage 원시 파싱은 저장 결과, render/OCR/근거 검증은 실제 재실행. retained OCR 캐시에는 신규 망 지연을 덧붙이지 않음.
실제 모델/AWS/EC2/현재 quota/새 v10 전수 품질은 not_run. a16e118 새 모델 요소 DomainValidationError는 조정자 공지의 HX1 회귀로 분리; 재생 테스트를 모델 정확도나 production 완료로 표현하지 않음.
신규 유료 호출0·USD0.00≤0.5·키 출력0·push/배포/EC2 변경0. 로컬 commit은 W3.DONE, 원자료·비교·입력/소스 SHA·미충족 요건은 summary.json. W3.DONE status=partial(전체 완료 아님).
