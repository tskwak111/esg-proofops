# OpenAI Luna 차트 검증

2026-10-10: `gpt-6-luna` 직접 API 호출로 이전했다. 본문 파서는 Docling+A100이며, 기존 OpenRouter 설정이나 저장된 실행을 자동 변경하지 않는다.

로컬 분석 서버는 기존 `OPENAI_API_KEY` 환경변수를 우선 사용한다. 키 파일을 사용할 때는 저장소 루트의 Git 제외 파일 `.env.openai.local`에 `OPENAI_API_KEY=...`로 입력한다. 실제 키를 문서나 명령행 인수에 넣지 않는다.

## 제한된 실제 검증

```powershell
.venv/Scripts/python.exe -X utf8 -m evaluation.openai_vision_pilot --pdf 지속가능경영보고서/NAVER_2024_KOR.pdf --pages 101,105 --output .local/openai-vision-pilot/new-review
```

출력 폴더는 새 경로를 지정한다. 동일한 이미지·모델·프롬프트 요청은 공용 원장의 완료 응답을 재사용한다. 실패하거나 응답 여부가 불확실한 생성 요청은 자동 재전송하지 않는다. 한 번에 최대 10쪽을 명시적으로 선택한다.

Docling 통합 파일럿에서는 `--vision --vision-model gpt-6-luna --vision-key-file .env.openai.local` 옵션을 사용한다. 옵션 이름은 실행 전 `python -m evaluation.docling_pilot --help`로 확인한다. 일반 `local_upstage_pilot`의 기존 OpenRouter 경로는 아직 그대로다.

## 비용과 증거

- 공용 원장: `.local/openai/vision-budget.sqlite3`, 누적 한도 USD 4.00. 원장을 삭제하거나 새 원장으로 우회하지 않는다.
- 토큰 수 사전 확인 후 최대 출력 8,192토큰 비용을 예약한다. 입력은 캐시 쓰기 단가로 보수적으로 계산하고 10% 여유를 포함한다. 따라서 기록 금액은 청구서의 실제 금액과 다를 수 있다.
- 가격 근거: https://developers.openai.com/api/docs/models/gpt-6-luna. 2026-10-17 이후 신규 호출은 가격 재확인 전 차단한다.
- `store=false`, 자동 생성 재시도 없음, 응답·사용량·모델·무결성 해시를 저장한다.
- 원문 좌표에 연결되지 않은 출력은 `vision_only` 검토 후보다. 차트의 의미·연도·단위·범례가 올바른지 자동 승인하지 않는다.

## 첫 실제 호출

NAVER 2024 보고서 물리 페이지 101·105 두 쪽의 호출이 성공했다. 보수적 누적 비용 기록은 USD 0.05726600이며 미정산 요청은 없었다. 결과는 `.local/openai-vision-pilot/sol-initial/`에 있다. 이는 연결과 비용 통제 확인이며, 정확도 평가나 다른 모델보다 우수하다는 증거는 아니다.
