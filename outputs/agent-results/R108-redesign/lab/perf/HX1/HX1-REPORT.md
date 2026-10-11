# HX1 — hotfix-elements / a16e118 기반 로컬 수정 완료(검증 제한 포함)
원인: LiveTaggingRuntime이 PB6 정책을 넣지만 tag_replicates 허용 목록에 없어 모델 호출 전 CITATION_RESTORE_POLICY_UNKNOWN 발생.
실제 RS6 상태·응답을 읽기 전용 SSH로 수집; DB/manifest 서버·로컬 SHA 동일. Linux 재생으로 70/78 요소 예외·요소 호출0 재현, 요청 본문298개 원본 동일(actual-stack.txt).
실제 실패 graph/packet으로 fresh-model 경계 이분 탐색: 통합 첫 실패6add70b, 원본 변경cb9ceb6; 4b7c4de/5a2d392는 정상(bisect.log, pb6-origin.log).
최소 수정: service.py의 정확한 정책 allowlist에 PB6 추가(2줄 추가/1줄 변경); DTO/DB/규칙·원문/과거 revision·정책 hash 변경 없음.
회귀: 실제 실패 checkpoint fixture + 새 OpenAI transport/cache miss/독립3회 스모크 + 변조 정책3종의 지출 전 거부; 수정 전 실패 → 수정 후4통과(smoke-final.log).
누락 이유: 기존 저장 응답 재생은 과거 PB2 정책을 유지했고 PB6 테스트는 복원 함수만 직접 호출. 새 기본 정책을 service→transport로 연결하는 스모크를 CI integration 범위에 추가.
LG13쪽 로컬 fresh 모델 실행1회(파서/OCR 원문 검증 산출물 재사용): 주장72, 요소 DomainValidationError0, 잠정23(E1 20/E2 3), 보류49; 추출 원천1실패 보존.
검증 제한: OpenAI HTTP403 1회 뒤 기존 immutable stop이 후속 호출을 막음(94 model_failed). 기준 잠정49 수준 회복은 미확인; 재실행·중단 가드 해제0.
시간479.74초(parse41.36/extract304.73/tag133.55); USD0.5 상한, 확정0.08403113950+불확실 예약0.02=노출0.10403113950(live/measurement.json, HX1-evidence.json).
전체 pytest: 6424통과/10실패/68스킵; 설치 전 시작한 웹8건은 설치 완료 후8통과. 잔여 HS2 REPORTING_SCOPE_REQUIRED·PT1 fixture combined_budget TypeError는 a16e118에서도2실패 재현.
W2 Linux 게시2실패는 별개: fake_analysis가 ocr_post 미주입→OCR_COLLECTION_FAILED_RESERVATION_RETAINED→PARSER_FAILED→broker 경합 토큰 무효화→LEASE_LOST; HX1 후에도2실패(w2-after.log).
ruff/format·mypy399파일·웹typecheck/build·CDKtypecheck·architecture·license·pip/pnpm audit 통과; reconciliation CI15검사(913통과/12스킵) 통과. 전체/보완 명령·결과는 commands.json.
리뷰: 원문 검증·binding·unknown·replica·예산·권한 가드 유지; 미승인 정책은 계속 거부. API/DB migration 불필요; 적용/rollback은 코드 단위이며 배포 승인 별도.
로컬 커밋만 수행. push·배포·EC2/클라우드 변경0, AWS 실증/전체 OS CI matrix not_run. 서버 원본과 실패 예약 보존; 완료 표식 HX1.DONE.
