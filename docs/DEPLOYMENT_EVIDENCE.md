# TASK-044 배포·복구 증거

현재 상태: **AWS staging acceptance blocked / 실제 배포·복구 not_run**.
로컬 검증 결과는 [task-044 실행 기록](../evidence/task-044.md)에 기록한다.
공개 PDF 권리·계정·모델·동의·배포 승인을 이 작업에서 만들지 않았다.

## 로컬에서 구현한 게이트

```sh
uv run python infra/cdk/staging_gate.py \
  --manifest evidence/staging/manifest.json \
  --approval evidence/staging/approval.json
```

이 명령은 로컬 파일을 읽고 JSON 결과를 stdout에 출력한다. 기존 파일과
태깅/판정 revision을 변경하지 않으며 AWS·모델·네트워크를 호출하지 않는다.
기본 입력이 없으면 exit 1, `evidence_complete=false`, 누락된 실증은 `not_run`이다.
exit 0은 **제공받은 증거 묶음의 검사 통과**만 뜻한다. 배포 수행, 승인 부여,
보고서 내용의 진실성, production readiness를 뜻하지 않는다.

승인과 로그는 보호된 CI/리뷰 경로에서 받아야 한다. 해시는 무결성 검사지
승인자의 신원 인증이나 전자서명이 아니다. 사용자가 올린 임의 JSON을
신뢰할 승인으로 취급하거나 이 CLI의 exit 0만으로 배포 권한을 부여하면 안 된다.
서명/CI identity 검증·실제 AWS 실행 연결은 아직 구현하지 않았다.

## 증거 묶음 v1 (내부 운영 파일, 제품 API/DB 변경 없음)

`manifest.json`은 `schema_version: 1`, `release`, `previous_release`, `reports`를 갖는다.
두 release 객체는 아래 필드를 모두 갖는다.

| 필드 | 입력 |
|---|---|
| `release_id` | 서로 다른 현재/이전 릴리스 식별자 |
| `environment` | `staging` |
| `account_id`, `region`, `tenant_id` | 실제 승인 범위, 현재/이전 동일 |
| `images` | `api`, `worker`, `agent` 각각의 `repository@sha256:<64 hex>` |
| `runtime_binding_sha256`, `runtime_version` | 검증한 binding 해시와 고정 runtime version |
| `rulepack_sha256`, `index_alias` | 불변 rulepack과 index 복귀 지점 |

`reports`는 아래 이름별 `{path, sha256}`를 갖는다. path는 manifest 디렉터리
내 상대경로이며 경로 탈출·외부 symlink·파일 해시 불일치는 거부한다.
manifest/approval/report JSON은 1MiB, 참조 로그·원문·복원 파일은 100MiB까지
읽는다. 사전 파일 크기만 믿지 않고 최대 `limit + 1` 바이트를 읽어 초과를 거부한다.
`approval.json`은 `status: approved`, 비어 있지 않은 `approved_by`, timezone이
있는 `approved_at`, **manifest 파일 원본 바이트**의 `manifest_sha256`를 갖는다.
manifest 변경 후 이전 승인을 재사용할 수 없다.

각 report는 `kind`, `release_sha256`, `status`, `environment: staging`,
`synthetic: false`, `checked_at`, `command`, 정수 `exit_code: 0`, `assertions`,
`log: {path, sha256}`를 갖는다. `release_sha256`는 release 객체를 Python
`json.dumps(release, sort_keys=True, separators=(",", ":"), allow_nan=False)`로
직렬화한 UTF-8 바이트의 SHA-256이다. 미래 시각, 문자열 boolean,
다른 릴리스, 실패 exit, 누락/변조 로그, 합성 보고서를 성공으로 인정하지 않는다.
제공된 `blocked`, `not_run`, `fail` 상태는 완료로 승격하지 않는다.
아래 assertions는 각각 정확히 boolean `true`여야 한다.

| report | 필수 assertions / 추가 데이터 |
|---|---|
| `cdk_synth` | `template_synthesized` |
| `supply_chain` | `locks`, `sbom`, `vulnerabilities`, `secrets`, `licenses` |
| `preflight` | `runtime_binding`, `consent`, `account_permissions`, `live_model_probe` |
| `public_pdf` | `rights_approved`, `source_verified`, `three_distinct_replicas`, `python_grades` |
| `tenant_isolation` | `foreign_read_denied`, `foreign_write_denied` |
| `review_conflict` | `stale_if_match_rejected`, `old_revision_unchanged` |
| `export_integrity` | `snapshot_hash_verified`, `old_export_unchanged` |
| `rollback` | `previous_images`, `previous_binding`, `rule_pointer`, `index_alias`, `schema_compatible`; `restored_release`가 `previous_release`와 동일 |
| `restore` | `separate_environment`, `source_hash`, `rulepack_hash`, `export_hash`, `tenant_isolation`, `tombstones_reapplied`, `pending_leases_reset` |
| `slo` | `query_p95_measured`, `acceptance_p95_measured`, `rpo_measured`, `rto_measured` |

`restore.artifacts`에는 `source`, `rulepack`, `export`별
`{original: {path, sha256}, restored: {path, sha256}}`를 제공한다.
게이트는 실제 파일을 읽어 두 바이트열이 일치하는지 검사한다.
이는 S3/PITR 복원을 실행하거나 schema/tenant/tombstone 검사를 대신하지 않는다.
그 검사는 실제 복구 환경에서 수행하고 로그에 남겨야 한다.

`slo.measurements`에는 수치 `query_p95_ms`, `acceptance_p95_ms`, `rpo_seconds`,
`rto_seconds`를 제공한다. 각 초기 목표 상한은 1000ms, 2000ms, 86400초, 14400초이며
NaN/무한대/boolean/음수/상한 초과는 거부한다. 목표는 실측 성능 보장이 아니다.

## 실제 staging에서 남은 순서

1. TASK-044의 모든 P0 의존 작업과 실행 권한을 확인한다. 잠금·SBOM·취약점·secret·라이선스 검사,
   실행 가능한 IaC synth, private runtime wiring, 검증된 이미지 digest를 확보한다.
2. 실제 계정/리전/binding/동의/공개 PDF 권리와 배포 승인을 받는다.
   기존 `uv run python scripts/preflight.py`를 실제 승인 입력으로 실행하고 원본 출력을 보존한다.
   그 CLI의 `live_model_probe=not_run`을 실제 모델 실증으로 바꾸어 기록하지 않는다.
3. 승인 범위에서 staging 배포 후 공개 PDF 전과정, 테넌트 차단, review If-Match 경합,
   과거 revision 불변, export hash 및 이전 다운로드 무결성을 실제 검증한다.
4. 이전 image digest/runtime binding/rule pointer/index alias로 복귀해 호환성을 검증한다.
   별도 recovery 환경에 S3 version/DDB PITR를 복원하고 원문·rulepack·export hash,
   schema·tenant, 삭제 tombstone 재적용과 pending lease 초기화를 검증한다.
   복구 시 기존 판정·태깅·리포트를 덮어쓰지 않는다.
5. 실제 부하·RPO/RTO 측정값, 명령, exit code, 로그, 현재/이전 릴리스 참조를 묶고
   검토자가 그 manifest 해시를 승인한다. 누락/실패 항목을 공개한다.

현재 CDK CLI/배포 엔트리포인트와 Playwright runner가 없고 AWS 검증·승인도 없어
이 순서를 완료하지 못했다. 기존 `infra/cdk/lib`의 템플릿 함수나 로컬 synthetic
테스트는 실제 staging artifact가 아니다. production 배포는 별도 사용자 승인 대상이다.
