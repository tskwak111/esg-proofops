# 25 · 완료 정의

> ESG ProofOps · 개발 명세 1.0 · 2026-09-08
> 도메인 정본: `sources/PROJECT_DOMAIN_V2_ORIGINAL.md` (원문 2.0, 2026-09-07).

## Task 완료
수용 기준을검증하는 positive/negative/race 테스트가있고실행 결과가통과해야한다. lint/format/typecheck/build 가통과하고 contract/문서가코드와일치해야한다. source·tenant·immutable metadata·logging 규칙을위반하지않아야한다. 새 dependency/마이그레이션은 license/rollback 을포함한다. 단순 mock 동작으로실제기능검증을대체하지않는다.

## Feature 완료
FR 에서화면/API/DTO/DB/worker/error/tests 로추적가능해야한다. loading/empty/invalid/unauthorized/timeout/duplicate/race 동작이설명과일치해야한다. UI 는키보드·원문접근·미판정상태표시를확인한다. API 변경과 DBmigration/rollback 이같은 release 에포함된다. 기존실험과새도메인기능을혼용하지않는다.

## P0 구현 완료
업로드→원문구조→claim→근거 packet→3회 tag→rule→review→export 의실제수직경로가작동한다. source 위치/citation/귀속/숫자/assurance/격리/lease/export 테스트가통과한다. 미정도메인 case 는명시된 gap 동작으로재현가능해야한다. 이조건을충족해도규칙조항·법제승인없이는법정기준검증서비스완료를주장하지않는다.

## 대회 실증 완료
승인된공개보고서로실행한 manifest, 실제 모델/파서 version, stage 별비용/시간, 골드정의, 요소/등급/회수지표, 실패/검토율, 원문링크, 사람태깅 수정, immutableexport 를제시한다. 실제시연과저장된 replay 를구분한다. 예시합성 데이터를실기업검토결과처럼소개하지않는다.

## 실서비스 공개 완료
대회실증외에계정/리전/모델동의·원문권리·기준 조항·규제표기·라이선스·테넌트격리·보존/삭제·백업복구·incident 대응·운영성능검증이필요하다. 특히 safeharbor 는법적효력보장이아니라문서기록지원임을표시한다. 미승인범위를숨긴채 productionready 로표시하지않는다.

## 이번 산출물의 완료 범위
이번 파일들은 개발 문서·API/schema/설정 초안·합성 테스트 벡터·Codex 지시서다. 실제 애플리케이션 구현, 기존 저장소 테스트 실행, 실제 PDF 파서 정확도 실험, Bedrock 호출, AWS 배포는 수행 범위가 아니다. 패키지 구조·참조·schema·traceability 검증 결과는 `evidence/package_validation.json`에 따로 제공한다.
