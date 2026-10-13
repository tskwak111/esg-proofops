# HX2 hosted 핫픽스 계약

기준은 `17e42a1`의 v13이다. 배포·push·EC2 변경과 실제 모델 호출은 하지 않는다.

- `claim_source_policies.PAGE_OCR_PROFILES`가 shipped OCR reader의 단일
  레지스트리다. source replay/publication, worker reader 선택, durable native
  policy binding, checkpoint digest/run-ID 검증은 이 레지스트리를 사용한다.
  새 reader를 등록하면 별도 native 허용목록 수정은 필요 없다. 전체 native
  policy 일치, lease 소유권, 최초 binding 불변성, source/tenant/receipt 검증을 유지한다.
- 현재 v13 정책 hash는 `488cb0b9339e4144ae9221845b21bfdd193d38a18cff60c24fb1c4cd6256090d`
  로 유지한다. v12 hash와 frozen verifier/reader bytes도 변경하지 않는다.
  향후 버전 등록의 wiring은 가상 v15 registry entry로 검사하며, 미출시 v14
  분석 정책의 의미·품질을 승인하거나 실증한 것은 아니다.
- hosted 업로드는 새 `hosted-null-navigation-hx2-v1` 보안 프로필로 Orion의 `0 0 R` null reference와 internal GoTo의 null page
  destination만 inert no-op으로 읽는다. 다른 missing reference, action/Next chain,
  암호·원본 hash·object/stream/resource 한도는 계속 검사한다. 기존 `strict-v1`의
  null destination 거부 동작과 해당 회귀 테스트는 유지한다. PDFium 개방 성공만으로
  원본 보안 검사를 우회하지 않는다. 원본을 다시 저장하거나 교체하지 않으며
  `upload-security.json.null_object_references`에 null reference 수를 기록한다.
- 브라우저에서 사용자가 선택 범위를 편집하면 기존 `manual_selection=true`를
  보낸다. 자동 선택의 unknown/conflict/unreadable guard, If-Match revision,
  source identity, 주장⊆근거, 쪽 상한은 유지한다. unknown 쪽의 분류를 바꾸지 않는다.
- hosted result GET과 run의 result에는 optional
  `hold_reason_details: [{code, message}]`를 제공한다. 공개 코드의 안전한 한국어
  설명만 넣으며 raw exception/원문/키는 전달하지 않는다. UI는 해당 상세를 표시한다.
  기존 결과 snapshot bytes/hash와 tag/decision/report revision은 다시 쓰지 않는다.
  기존 소비자는 이 optional field를 무시할 수 있고 DB/DTO migration은 필요 없다.
- E8의 production frontend는 H4 오류 매핑이 누락된 별도 bundle이었다. 조정자는
  이 변경의 `hostedClient.ts`/`HostedResult.tsx`도 실제 frontend branch에 통합해야 한다.
  서버 변경만으로 이미 배포된 JavaScript bundle을 수정할 수는 없다.

배포 전 조정자가 실행할 무료 스모크:

```sh
uv run python scripts/hosted_pipeline_smoke.py --output /tmp/hx2-release-smoke
```

`deploy/public/Dockerfile`로 이미지를 빌드한 후 별도 API/worker 컨테이너를 띄운다.
각 runtime은 network none이며 host key/data를 mount하지 않는다. 가짜 provider
POST/status/download/OCR/LLM 응답만 주입하고 실제 upload→job binding→parse→extract→
tag→publication→GET→API restart 경로를 검사한다. 검증되지 않은 요소는 unknown,
확정 등급은 null로 유지한다. fixture는 production entrypoint/config로 활성화할 수 없다.

Rollback은 새 runtime/frontend 배정을 중단하고 저장된 정책 reader를 유지하는 것이다.
수정 전 runtime은 v13 native binding 결함이 있으므로 새 v13 job에 다시 배정하지 않는다.
기존 원문과 결과는 보존한다.
