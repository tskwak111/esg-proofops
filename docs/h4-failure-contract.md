# H4 파이프라인 실패·부분 결과 계약

기준: `hold-H4.md`, H3 `4fed2ea`, v12 `372c19c`. 이 변경은 로컬 검증용이며
배포·EC2·운영 설정 변경을 포함하지 않는다.

- 새 실행은 불변 job의 허용된 오류 코드를 `outcome.reason`에 보존한다.
  원문·예외 메시지를 공개 코드로 사용하지 않는다. 새 산출물은
  `pipeline_failure_projection=specific-pipeline-reasons-h4-v1`을 기록한다.
- extraction job이 있어도 checkpoint가 발행되지 않았으면 빈 성공으로
  표시하지 않는다. 실패 사유와 `confirmed_grade=null`을 반환한다.
  tag checkpoint가 없으면 기존에 발행된 추출 주장은 계속 표시한다.
- 검증된 extraction checkpoint의 `extraction_outcome`을 optional
  `result.pipeline`에 투영한다. 실패 쪽과 코드, 처리 범위를 표시하며
  unreadable·unknown을 absent 또는 근거 부재로 바꾸지 않는다.
- `PdfReadError`는 원문 내용 없이 `PARSER_PDF_INVALID`로 보존한다.
  파서 메모리 한도·원문 대조 실패·입력 오류·모델 요청 크기 초과를
  구분한다. 암호화·파일 손상은 기존 보안 업로드 게이트를 유지한다.
- 별도 hosted 업로드 상한은 기본 150MiB이며 런타임 설정을 UI에서 읽는다.
  기존 `/v1` 업로드 DTO의 100MiB 계약은 유지한다. H3 scope 연구의
  100MiB 제한은 hosted 서버 한도가 아니다.
- v12의 scheduler가 필요한 모델 transport는 바인딩이 없으면 provider
  예약 이전에 거부한다. 실제·불확실 전송 비용은 계속 보존한다.
- `FINALS_H4_POLICY`는 v12 위에 H3의 `partial-v2`/잘못된 표 unknown
  처리를 얹은 명시적 opt-in이다. 기본 v12 및 모든 과거 정책 hash,
  원문 판독기와 이전 revision/replay는 유지한다. H4 실측은 정확한 v12로 한다.

공개 hosted `pipeline`의 선택 필드와 허용 오류 코드를 추가한다. DB column,
기존 DTO 또는 도메인 등급 계약 변경은 없으며 migration은 필요 없다.
이전 소비자는 선택 필드를 무시할 수 있다. Rollback은 H4 hash의 새 실행
배정을 중단하고 해당 hash의 reader를 유지한다. 기존 보고서 bytes를 다시
작성하지 않는다. 모델 호출·원문 대조의 실패는 품질 성공으로 계산하지 않는다.
