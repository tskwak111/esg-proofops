# W7 — 문장 앞절 복구 완료
기준 a16e118 · worktree `.local/w7-sentence` / branch `w7-sentence` · 로컬 커밋만, push·배포·EC2 변경 0.
원인: 원문 블록에는 앞절이 있으나 sentence-ID 후보가 PDF 줄바꿈에서 잘리고 모델이 뒷줄만 선택; 기존 join은 선택된 줄만 합침. 원문 영역 보정이 자른 것이 아님.
수정: `--extraction-sentence-prefix` opt-in(검증된 context graph·source-ID·linewrap 필수); 동일 원문 문단의 연속 앞절만 복구하고 기존 글자·좌표 검증 재실행.
마침표·글머리·제목 경계에서 멈춤; 독립 앞 주장·다른 선택·표 행/열·derived 문단은 붙이지 않음. 불명확한 경계는 유지하며 일반 문법 완전성을 보장하지 않음.
새 정책 SHA256 `c6e603453be254c083f845051f6e3f4a47196373abb2f01aebf513c26cf2757e`; 최종 정책의 저장 raw 응답 재생 인용·오프셋은 Linux fresh 검증 결과와 전부 동일.
LG QM1 고정 표본: 앞절 누락 문단 7/15(46.7%)→0/15, 전체 인용 표본 7/30→0/30; 지적된 7건 모두 복구.
LG 전체 재생: 규칙상 복구 가능한 앞절 누락 14/47(29.8%)→0/48; 종전 fragment guard 제외 1건 복구, 주장 79→80.
동일 fresh v10 검증기 LG 원문 검증 79→80(기존 QM1 저장 verified 74와 다른 비교 기준; PA9 효과를 W7 효과로 세지 않음).
NAVER: 누락 0/4→0/4, 주장 17→17, 원문 검증 8→8; 기아: 누락 0/15→0/15, 주장 40→40, 원문 검증 40→40.
DL3 동일 초안 정답·문자 매칭: NAVER 재현율 17/76=22.37%·정밀도 17/17=100%, 기아 38/80=47.5%·38/40=95%; 전후 동일. LG 정답 없음→not_run/null.
확장된 15개를 원본 PDF 해당 bbox의 native 글자/배치와 독립 대조: 글자·위치 오검증 0/15; 전부 fresh verified. 전체 문서 오류 0이나 모델 정확도를 뜻하지 않음.
검증: 개발 회귀 111·통합 87·최종 관련 66 통과; ruff/format·mypy·architecture(계약 fixture 포함)·diff-check 통과. `verification.json`에 명령·결과·자체 검토 수록.
무료 Linux 재생 총 LG 305.5초/NAVER 90.8초/기아 375.0초(원문 재검증 포함); 인용 선택 단계 0.09/0.14/0.32초. 실서비스 전체 속도 비교 아님.
모델/API 유료 호출 0·USD0≤0.3; LG 서버 자료는 읽기 전용 수집 전후 해시 동일. 원본·기존 결과·정책·등급 및 unknown/conflict/unreadable 상태 불변.
활성화는 새 state에 옵션 추가; rollback은 미래 실행에서 옵션 제거·이전 profile 사용. API/DB 변경·migration 없음; 기존 state에는 옵션 추가 금지.
한계: 초안 정답 문자 대조이며 사람 R2/의미 정확도 아님. 새 태깅·등급/실제 모델·AWS 시험 not_run; HX1의 신규 호출 DomainValidationError 회귀와 분리.
근거: `scores.json`, `source-audit.json`, 회사별 `measurement.json`·`changes.json`·fresh attestation, `source-collection.json`, `verification.json`; 재현 코드 `evaluation/w7_sentence_replay.py`, `evaluation/w7_score.py`.
