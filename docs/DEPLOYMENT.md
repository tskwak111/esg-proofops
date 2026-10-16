# 백엔드·프런트 배포 인수인계

대상은 백엔드 `tskwak111/esg-proofops`, EC2 `i-01fec46ef85815a17`(ap-southeast-2, arm64, Ubuntu 24.04)이다. CI1은 로컬 파일·검증 결과이며 운영에 적용되지 않았다. 관리자는 [콘솔 설정 절차](../deploy/ec2/admin-setup.md)를 완료한 뒤 활성화한다. 기존 애플리케이션 정책·기본 프로필·테스트 기준은 유지한다.

## 자동 백엔드 배포

`.github/workflows/deploy-backend.yml`은 main push 또는 main의 수동 Run workflow로 실행한다. Repository 변수 `BACKEND_DEPLOY_ENABLED=true`가 필요하며 production environment의 필수 승인자가 승인한 후 job이 시작한다. 승인자는 **실행 대상 SHA**, 기존 CI 결과, 데이터/설정 호환성, 동결 여부를 확인한다. YAML만으로 승인자를 만들 수 없으므로 콘솔 설정을 생략하지 않는다.

흐름은 ARM64 runner → `deploy/public/Dockerfile` 이미지 빌드 → `scripts/hosted_pipeline_smoke.py` → OIDC 단기 자격 증명 → ECR commit SHA 태그 push → SSM `AWS-RunShellScript` → 서버 health 결과 확인이다. 스모크 컨테이너는 모두 `--network none`이고 운영 키·운영 데이터를 마운트하지 않는다. runner에서만 worker 2 CPU/5 GiB를 사용하며 기존 로컬 기본값 6 CPU/12 GiB는 유지한다.

서버 `/srv/proofops/deploy-from-ecr.sh`는 인스턴스 역할로 ECR에 로그인하고 이미지를 pull한다. 수동 경로와 같은 `.deploy.lock`을 잡은 뒤 기존 `drain-restart.sh`의 `drain_and_wait false 600`을 사용한다. 현재 이미지를 `.previous-image`에 기록하고 `compose.env`의 **IMAGE 값만** 원자적으로 바꾼다. WORKER_CPUS/MEMORY, OCR 설정, Caddy, `runtime.env`는 보존한다. `proofops.service` 재시작 후 API와 worker의 실행 image ID·Docker health, `/v1/health/ready`를 확인하고 resume한다. 서버 스크립트나 compose 설정은 CI가 자동으로 갱신하지 않는다.

GitHub concurrency는 실행 중 배포를 취소하지 않는다. 서버 lock을 잡지 못하면 새 실행이 실패한다. 진행 중 job을 수동 취소해도 이미 보낸 SSM 명령은 계속될 수 있다. GitHub summary의 command ID로 AWS 콘솔 → Systems Manager → Run Command → 해당 invocation 상태를 확인한 후 다음 작업을 한다. 상태조회 오류·timeout은 배포 성공으로 처리하지 않는다. 서버 execution timeout은 2,400초, CI polling은 최대 2,580초다.

## 실패와 롤백

- pull·arm64 확인 실패는 배포 전에 종료한다. drain/wait-idle 실패는 restart 없이 종료하며 기존 helper 규약대로 maintenance를 남긴다. 작업을 확인한 관리자가 재시도 또는 resume를 결정한다. 강제 restart는 자동 경로에 없다.
- IMAGE 전환 뒤 설정·재시작·health 실패 시 원래 compose.env를 복구하고 직전 로컬 이미지로 재시작한다. 이전 API/worker와 readiness가 정상일 때만 resume한다. 성공적으로 롤백되어도 GitHub 배포는 **실패**이며 서버 출력에는 `ROLLED_BACK`이 남는다.
- resume 명령이 실패하면 일부 효과가 이미 적용됐을 수 있으므로 다시 drain/wait-idle을 통과한 뒤에만 롤백한다. 이 재드레인이 실패하면 현재 서비스와 복구 백업을 보존하고 관리자 판단을 기다린다.
- 롤백 health도 실패하면 자동 resume하지 않는다. `/srv/proofops/.deploy-ecr.*/compose.env` 백업과 maintenance를 보존한다. Docker 로그인 토큰 임시 디렉터리는 제거한다. SIGKILL·호스트 장애·SSM 강제 종료 시 trap 실행은 보장되지 않으므로 관리자 복구가 필요하다.

관리자가 특정 **이전 ECR SHA**로 되돌릴 때 서버에서 실행하는 예시:

```bash
# SHA는 관리자가 확인한 40자리 이전 commit으로 치환한다.
sudo /srv/proofops/deploy-from-ecr.sh --dry-run \
  000000000000.dkr.ecr.ap-southeast-2.amazonaws.com/proofops-r108:REPLACE_WITH_PREVIOUS_SHA ap-southeast-2
# 위와 동일한 입력을 검토한 후 --dry-run을 --apply로 바꿔 실행한다.
```

ECR 태그는 immutable이다. 같은 SHA workflow를 다시 push해 덮어쓰지 않는다. `.previous-image`가 기존 tar 기반 로컬 태그이면 위 ECR 전용 명령의 입력으로 쓸 수 없다. 그 경우 관리자는 기존 수동 pack/deploy 경로로 검증된 이전 tar를 배포하거나 서버에서 백업 compose.env를 복구한다. 직접 복구도 동일한 `.deploy.lock`, drain→wait-idle→restart→health→resume 순서를 지킨다. 장애 시 임의로 `docker compose down`, 데이터 삭제, 이미지 prune을 하지 않는다.

이미지 롤백은 데이터 형식/migration 롤백이 아니다. 새 이미지와 기존 데이터가 이전 이미지에도 호환돼야 한다. 호환되지 않는 데이터·compose·systemd 변경은 별도 승인된 유지보수 절차로 수행한다.

## 비상 수동 배포 — 기존 스크립트 유지

운영자 Mac의 기존 승인된 AWS/SSM·SSH 설정과 개인 경로를 그대로 사용한다. `deploy/ec2/pack.sh`와 `deploy/ec2/deploy.sh`는 변경하지 않았다. 실제 작업 전 드라이런을 먼저 확인한다.

```bash
export IMAGE=proofops-r108-public:REPLACE_WITH_APPROVED_RELEASE
bash deploy/ec2/pack.sh /absolute/private/release.tar
bash deploy/ec2/pack.sh --apply --build /absolute/private/release.tar
# 기존 운영자의 STATIC_IP, SSH_KEY, RUNTIME_ENV, ACME_EMAIL,
# IMAGE_ARCHIVE 및 AWS PROFILE 설정을 현재 승인된 개인 환경에서 제공한다.
bash deploy/ec2/deploy.sh --worker-cpus 6.0 --worker-memory 12g
# 검토 후에만 같은 명령에 --apply를 추가한다.
```

리소스 예시는 현재 기본 6 CPU/12 GiB다. 수동 deploy.sh는 compose.env를 재생성하므로 실제 서버에 별도 자원값/추가 설정이 있으면 기존 운영자 절차로 먼저 확인·보존한다. 자동 경로의 IMAGE-only 보존을 수동 경로에도 있다고 가정하지 않는다. 수동 경로는 SHA/아키텍처를 확인한 tar와 운영자의 private runtime 파일을 기존 SSH/scp 경로(현재 운영 환경에서는 SSM 경유)로 보낸다. GitHub runner에 이 파일들을 올리거나 장기 키를 등록하지 않는다. 자동/수동 배포를 동시에 시작하지 않는다.

## 10월 19일 본선 동결

2026-10-19 본선용 동결의 시작·해제 시각은 조정자가 확정·기록한다. 동결 선언 시 repository 변수 `BACKEND_DEPLOY_ENABLED=false`로 신규 자동 배포를 막고, 대기 중 production 승인 요청은 승인하지 않는다. 이미 실행 중인 SSM 명령은 상태를 확인하고 안정된 릴리스까지 마무리한다. 이미 승인 대기 중인 job은 변수 변경만으로 취소된다고 가정하지 않는다.

동결 기간에는 일반 기능 배포, 기본 프로필/모델/프롬프트 변경, 의존성 갱신, DB migration, 비밀값 재배포, 이미지 정리를 하지 않는다. 긴급 장애 수정·보안 수정·직전 정상 릴리스 롤백만 조정자 승인을 받아 대상 SHA, 이유, 검증, 복구 SHA, 실행자·시간을 기록한다. main에 병합했다는 이유만으로 production 승인을 내리지 않는다. 동결 해제 후 대기 중 오래된 SHA 대신 선택한 검증 SHA를 확인한다.

## 비밀값과 프런트 연결

서버의 비밀값은 `/srv/proofops/runtime.env`, `/srv/proofops/private/`에 있다. 원문/상태는 `/srv/proofops/data/`에 있다. 경로만 문서화하며 내용은 커밋·Actions 변수·아티팩트·SSM command 인자로 전송하지 않는다. ECR 로그인은 임시 Docker config를 사용하고 정상 종료/처리 가능한 실패 시 제거한다. GitHub OIDC 자격 증명은 서버로 전달하지 않는다.

Vercel의 프런트 저장소는 **`tskwak111/esg-proofops-submission`**이다. 관리자가 Vercel 프로젝트 Settings → Git에서 GitHub App을 해당 저장소에 연결하고 Production Branch를 **main**으로 지정한다. main은 운영 배포, PR은 Preview 배포다. 프런트의 Vercel 환경변수는 해당 프로젝트 콘솔에서 관리하고 백엔드 서버 비밀값을 복사하지 않는다. 백엔드 저장소와 프런트 저장소는 별도 배포이며, 본선 동결 중 프런트 main 병합/production 승격도 같은 승인 규칙을 따른다. 연결·preview·운영 프록시 실제 health는 관리자가 확인할 미실행 항목이다. [Vercel GitHub 연결](https://vercel.com/docs/git/vercel-for-github)

## 로컬 확인

`actionlint .github/workflows/deploy-backend.yml`, `shellcheck -x deploy/ec2/deploy-from-ecr.sh`, `pytest tests/test_ci1_deploy.py tests/test_pa5_deploy.py`로 workflow·shell·실패 복구 경로를 확인한다. 실제 이미지 검증은 `python3 scripts/hosted_pipeline_smoke.py --image proofops-public:ci1-local --output .local/ci1-checks/smoke --worker-cpus 2 --worker-memory 5g`를 사용한다. 로컬 모의 성공은 AWS 권한·GitHub 승인 게이트·운영 배포 성공의 증거가 아니다.
