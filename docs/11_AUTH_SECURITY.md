# 11 · 인증·권한·보안

> ESG ProofOps · 개발 명세 1.0 · 2026-09-08
> 도메인 정본: `sources/PROJECT_DOMAIN_V2_ORIGINAL.md` (원문 2.0, 2026-09-07).

## 1. 인증
Cognito Hosted UI 의 OIDC Authorization Code+PKCE 를 BFF 에서 수행한다. state/nonce 는 서버 저장 일회성10분, redirect_uri 는 설정 exact match, code replay 거부. 신규 사용자 초대와 password/MFA 정책은 Cognito user pool 이 관리하며 자체 비밀번호 테이블을 만들지 않는다. 관리자·검토자 MFA 를 운영 기본으로 요구한다. P0는 하나의 Cognito user pool, tenant membership 은 application 정본이다.

session cookie `__Host-proofops_session`: Secure, HttpOnly, Path=/, SameSite=Lax, Domain 미설정. SID 는32bytes 이상 CSPRNG, 저장 key 는 hash. 절대8시간/idle30분, rotation 은 로그인·권한승격·tenant 전환시, logout 시 즉시 revoke 한다. refresh token 은 KMS 암호문으로 저장하고 로그/URL/브라우저 storage 로 보내지 않는다. 서버는 토큰 signature/iss/aud/exp/nonce 를 검증하고 JWKS rotation 을 캐시 만료로 처리한다.

## 2. 역할·격리
viewer=읽기/export, editor=upload/run/cancel, reviewer=review/rescore, admin=구성/활성화/삭제/모든 업무 권한. editor 는 reviewer 권한을 자동 얻지 않는다. 각 operation 에서 tenant membership strong read 또는 짧은30초 캐시 후 revoke event 로 invalidate 한다. 보안 테스트는 즉시 revoked user 를 strong 검증 경로로 확인한다. 민감 변경은 캐시 없이 읽는다.

tenant_id 는 세션에서 주입한다. 모든 DDB/S3/OpenSearch 접근은 tenant scope 를 요구하는 Repository API 로 제한한다. 클라이언트가 S3 key, bucket, arbitrary index, inference ARN 을 전달할 수 없다. source_id 가 존재하더라도 run/docversion/tenant 가 맞지 않으면404다. 검색 필터를 생성모델에게 위임하지 않는다.

## 3. 브라우저·API
CORS 는 배포 origin 한정, credentials true, wildcard 금지. 변경 요청은 CSRF token+Origin 을 검사한다. CSP 는 self 중심, PDF blob/image 필요만 허용하며 untrusted HTML 삽입을 금지한다. input 은 Pydantic extra forbid/길이·enum validation, log/error output escape, CSV export 는 =,+,-,@로 시작하는 사용자 string cell 앞에 안전한 prefix 를 붙여 formula injection 을 방어한다(숫자로 타입 확인된 값은 별도 numeric 출력).

DynamoDB 라도 injection 이 사라지는 것은 아니다. 사용자 입력을 expression 문자열·OpenSearch DSL 로 직접 넣지 않고 parameter binding/typed query builder 로 구성한다. tenant/model/action allowlist 는 regex 입력 validation 과 별개로 enforce 한다. POST idem/limits 가 resource abuse 를 제한한다.

## 4. PDF 공격면
presigned POST 는 exact key prefix/content-length-range 를 제한한다. 업로드 후 서버 magic/hash/크기/페이지/암호 여부를 검증한다. 파서 container 는 non-root, read-only rootfs, bounded scratch, CPU/memory/PID 제한, 임의 인터넷 egress deny(필요한 AWS endpoint 만 allowlist)다. PDF embedded JS/Launch/URI 액션을 실행하지 않고 remote resource 를 fetch 하지 않는다. converter command 는 shell=False argument list 로 실행한다. 파일명은 display metadata 이고 filesystem path 로 쓰지 않는다.

2026-09-13 로컬 호환성 수정: 직접 `/A` 및 `/Type /Annot`, `/Subtype /Widget`의
`/AA /D`·`/AA /U` 클릭 이벤트에서만 URI와 Named Print를 허용한다.
Widget의 마우스 down/up 의미는 PDF 32000-1 Table 194에 근거한다.
자동 OpenAction, 포커스·페이지 열기, 문서 수준 AA, 위험한 Next 연결은 계속 거부한다.
공유 액션은 각 트리거 문맥에서 재검사한다. 원본은 변경하지 않고 서버는 액션을 실행하지 않는다.
API/DB migration은 없다. 롤백하면 새로 허용한 원본의 재검사가 다시 거부될 수 있으므로
기존 원본·manifest를 보존하고 이전 검사기로 해당 실행을 재배정하지 않는다.

원문 다운로드는 read-only viewer 로 표시하고 active content 를 실행하지 않는다. scan detection 을 이유로 외부 OCR SaaS 에 자동 전송하지 않는다. decompression bomb/무한 파싱은 stage timeout·memorylimit 으로 종료하고 partial/failed 사유를 남긴다.

## 5. 데이터 이동·모델 정책
미공개 공시의 storage region, inference processing regions, provider retention/training terms, cross-region routing, log content, 계약상 동의는 별도 ConsentProfile 로 승인한다. S3가 서울이라고 추론도 서울이라고 간주하지 않는다. AWS 기능별 region/Memory cross-region 문서를 확인하고 기본 Memory OFF 를 유지한다.[S07–S08] 허용 지역을 넘는 inference profile 은 preflight 에서 차단한다.

‘학습 미사용 보장’ 문구는 실제 계정·모델·계약 설정 확인 후에만 판매 문구로 사용한다. 애플리케이션 자체는 고객 원문을 fewshot/training 으로 자동 재사용하지 않으며 review 확정도 해당 tenant 의 동의된 개발 풀에만 들어갈 수 있다. 다른 tenant 의 공개보고서 cache 라도 무단 공유하지 않는다.

## 6. 저장·로그·삭제
S3 versioning+KMS, DynamoDB KMS/PITR, Secrets Manager 와 IAM task role, TLS end-to-end 를 사용한다. CI 는 GitHub OIDC 로 배포 role 을 얻고 장기 AWS key 를 저장하지 않는다. application log 는 id/hash/code/token 수만, 문서 원문·payload·인증 token 은 제외한다. 원시 모델응답은 필요 동의하에 S3 암호화 artifact 로 제한 보존하고 CloudWatch 에 남기지 않는다.

기본 개발 설정(도입 제안): quarantine24시간, orphan48시간, raw model responses7일, accepted artifacts90일, 본문 없는 audit365일. 이는 계약상 확정 보존기간이 아니며 고객 정책은 배포 시 승인한다. 사용자가 삭제 요청하면 삭제 manifest 실행 상태를 보여 주고 백업 잔존/법정보존 조건을 설명한다. 보존 의무가 없는 fixture 는 테스트 종료시 즉시 삭제한다.

## 7. 라이선스·공급망
OD tagged version license, pdfplumber/PDFium 및 모델/표준 텍스트 권리를 SBOM/NOTICE 와 함께 점검한다. PyMuPDF 공식 문서는 AGPL 또는 상용 라이선스 선택을 안내한다.[S06] 따라서 라이선스 확인 없이 기존 parser 를 비공개 서비스 기본 image 에 복사하지 않는다. 자체 작성 clause summary/ID 만 배포하고 IFRS/GRI/SASB 전문을 원문 허가 없이 vectorDB 에 적재하지 않는다. KSSB 공개본도 공개 접근 가능성과 재배포 권리를 동일시하지 않는다.
