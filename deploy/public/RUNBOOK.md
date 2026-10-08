# Local P1 verification and later Lightsail handoff

Target: Lightsail Linux4GB, not a cloud deployment in this task. `deploy/public/Dockerfile`
uses frozen Python3.12.14/uv0.12.7/workspace lock, Java21+PDF dependencies. App runs
non-root and explicit hosted/disabled composition; container memory cap3GiB leaves1GiB
of a4GiB host for the OS/proxy. Selected-page subprocess cap512MiB/20CPU-seconds/30s. Cross-process upload admission
is1; concurrent uploads receive429 before their bodies are read.
All metrics below must be interpreted as offline control-plane/upload/prepare smoke,
not live OCR/JVM/LLM peak RSS or a completed end-to-end analysis capacity claim.

```sh
cd /Users/ss020/Dev/ESG_ProofOps/.local/r108-public
uv sync --frozen --all-packages
open -a Docker
# Wait for docker info to succeed, then build. No provider or AWS keys are supplied.
docker build -f deploy/public/Dockerfile -t proofops-r108-public:p1 .
.venv/bin/python scripts/hosted_docker_probe.py --output /tmp/r108-p1-evidence
```

Probe creates/removes its own container and volume only; keeps the image. It uses
`--network none --read-only --memory3g --memory-swap3g --cpus2 --pids-limit128`,
cap-dropALL/no-new-privileges,512MiB noexec tmpfs and a private `/data` volume. It
locally generates a session secret and test-only7-day consent version in a temporary
0600 env file (never printed/copied to evidence). Measures wall startup/restart,
image uncompressedSize, API VmHWM, sampled summed Python RSS, worker/child maxrss,
and cgroup memory.peak. Sampling includes the probe process; cgroup peak includes
page cache. No network is available except container loopback. Smoke uses actual
Uvicorn HTTP, invitation, cookie/CSRF, two tenants, validated3-page PDF,202/poll,
separate worker CLI preparation of2pages, explicit blocked result, physical purge,
logout and a surviving session+CSRF after Uvicorn restart. Test upload is blank3pages.

For a persistent local operator setup, provide exact HTTPS APP_ORIGIN, a generated
HOSTED_SESSION_SECRET and HOSTED_EVENT_ID in a private env file; bind a private data
volume. Defaults refuse uploads/runs and disable paid transport. Do not source research
.env files. HOSTED_CONSENT_VERSION and HOSTED_ACCEPT_UPLOADS=true allow the user-approved
7-day original retention policy. Set ANALYSIS_BACKEND=r108/R108_ACCEPT_NEW_RUNS=true only
for the explicit offline blocked flow until the approved live handler is implemented.

Invite via `python scripts/hosted_control.py invite --tenant <UUID> --user <subject> --role admin`
inside the API image; the one-time code is returned only to the operator. Browser has
no provider key. API+worker must use the same secret, event ID and data volume.
`python scripts/hosted_control.py worker` runs one persistent offline worker;
`... worker --once` processes at most one job. Worker and API each run expiry maintenance;
API does so every60seconds and on lifespan startup; `... maintain` runs explicitly.
Expired active PDFs become inaccessible/physically removed; do not shut down all
maintenance before their7-day deadline unless every active payload is first purged.

`... backup --path <new-private-dir>` uses SQLite online backup and copies only
receipt/graph/export artifacts, never original/prepared/display PDFs or auth secrets.
Stop API/worker before restore: `... restore --path <backup-dir>`. Restore checks its
matching independent ledger identity, never rewinds `deletions.sqlite3` (money+deletion
fences), replays tombstones before access and never restores raw PDFs. Missing source
means SOURCE_UNAVAILABLE/reupload. A lost independent ledger requires reconciliation,
not a new empty budget. Copy/encrypt that ledger separately under operator custody;
never restore an older version to free budget or resurrect files. Subject-free event
aggregate survives30-day per-run audit expiry; unknown money remains blocked until
reconciled. Backups expire from earliest source creation+14days, not snapshot time.

Migration is additive hosted-schema1 in an isolated directory. Never point hosted mode
at research state.sqlite3 or import existing Apple receipts as Linux-verified. Rollback
must understand schema1 and retain the independent ledger: stop acceptance, preserve
pending jobs/money, serve static web; no local-env bypass. Base-image digests/system
packages are not yet release-pinned, amd64 behavior is not inferred from an arm64 probe.
Cloud credentials, TLS/reverse proxy, domains, approved OCR binding, provider retention,
pricing and complete R108 review/export integration remain separate release gates.

## P2 private live worker
Use current image tag `proofops-r108-public:p2`; the packaged evaluation allowlist
contains only the private worker entry point and reused pilot preparation module.
Default key-free smoke remains off and cannot call providers. Set live flags only
with the operator JSON/key-file paths described in CONTRACT's P2 amendment. Keep
private key/config mounts read-only and outside HOSTED_DATA_DIR; never source the
key files or provide them to the browser. Run the existing `hosted_control.py worker`.

macOS worker uses an isolated subprocess with its own document-scoped receipts,
SQLite state and selected PDF. It never points at the research state/cache/budget
DB. Hosted money/fences remain authoritative and are checked before each transport.
One active run is capped at840seconds of pipeline execution; unknown dispatch on
crash/timeout retains the reservation and needs reconciliation. The analysis lock
is inherited by its child: a parent crash cannot make purge unlink active source
files. A tombstoned worker cannot dispatch or publish; maintenance retries purge
once the child exits. A failed result integrity read must be investigated, not
relabelled as empty evidence. Linux source-reader release remains blocked as above.

For the explicitly authorized local Mac canary only:
`python scripts/hosted_live_probe.py --pdf <existing-original.pdf> --pages 22,41
--output <new-private-dir> --research-root /Users/ss020/Dev/ESG_ProofOps`.
This opens loopback Uvicorn, authenticates through the hosted API, uploads the
original, accepts exactly2pages, and runs one worker. Before transport it reserves
USD.30 in the existing lab/sprint3/E2E/r108-spend.json under its shared decision lock;
settled unused reservation is returned, unknown money stays reserved. Output/data
existence prevents accidental repeat. No cloud/push or default paid allowance.
Operator config discloses 2025 report /2024 reporting period for this fixed canary.
The local canary isn't a same-site TLS browser or Linux OCR capacity certification.

## P3 — 2026-10-10 Lightsail 실행 준비 (이번 작업은 클라우드 호출 0)

DEC-19: 서울 `ap-northeast-2`, Linux VM 2vCPU/4GB, Vercel 정적 웹, 분석 동시성1,
USD0.50/run·5/day·5/event, 원본 PDF 7일. 이 절은 **내일 사용자가 실행할 절차**다.
P3에서 AWS/Vercel/SSH/유료 모델 호출·push는 하지 않았다. `deploy/lightsail/*`는
기본 dry-run이며 `--apply`를 명시해야 원격 호출을 한다. `pack.sh`, `local-smoke.sh`는
로컬 Docker 전용이다. 운영 env나 provider 키 파일을 `source`하지 않는다.

**출시 게이트:** P2 Linux reader는 여전히 미승인이다. 새 kit의 `deploy.sh`는
`LIVE_DISABLED=true`만 허용한다. 실제 분석 공개는 승인된 Linux reader 이미지 통합,
4GB live RSS, TLS/Vercel 쿠키·업로드 실측 이후의 별도 작업이다. 현재 배포 가능한 것은
닫힌 control plane / 명시적 offline blocked flow이다. 키를 배치해도 live는 켜지지 않는다.

### 1. 사용자가 AWS 계정·권한을 준비 (약 10–20분)

계정 관리자에서 전용 IAM 사용자 `proofops-deploy`를 만들고 콘솔 사용자는 MFA 설정.
프로그램 access key는 로컬 AWS profile에만 저장하며 서버·Docker·브라우저에는 주지 않는다.
`deploy/lightsail/iam-policy.json`의 `ACCOUNT_ID`를 실제 12자리 계정 ID로 바꾸어 사용자에
attach한다. 정책은 이번 CLI에서 사용하는 **Lightsail 작업 + Budgets View/Modify만** 열고
Lightsail은 서울 리전으로 제한한다. STS GetCallerIdentity는 별도 Allow가 필요 없다.
IAM 사용자/정책 생성 권한은 이 배포 사용자에 주지 않는다. Lightsail 목록/생성 API는
resource ARN을 생성 전에 알 수 없어 Resource `*`이며 계정 내 다른 서울 리소스에도
명시된 작업 권한이 있다. 관리자 계정·권한 경계/SCP가 필요하면 관리자가 추가로 제한한다.
Budgets는 정확한 `proofops-r108-monthly-20` ARN으로 제한하고 legacy `aws-portal:*`
또는 비용탐색기 권한은 추가하지 않는다. Billing IAM access/account activation이 막으면
관리자가 Billing 설정을 확인한다. 알림 이메일·계정 ID를 공개 repo에 저장하지 않는다.

```sh
cd /Users/ss020/Dev/ESG_ProofOps/.local/r108-public
aws configure --profile proofops-deploy
# prompt: local access key / secret key / ap-northeast-2 / json
export PROFILE=proofops-deploy REGION=ap-northeast-2 NAME=proofops-r108 ARCH=amd64
export ACCOUNT_ID=REPLACE_12_DIGIT_ID
# Lightsail 콘솔/Service Quotas에서 해당 계정 서울의 실제 적용 quota 확인 후 입력.
# published default는 vCPU20, static IP5이지만 신규 계정은 더 낮을 수 있다.
export VCPU_QUOTA=REPLACE_CONFIRMED_VCPU_QUOTA STATIC_IP_QUOTA=REPLACE_CONFIRMED_IP_QUOTA
export MAX_MONTHLY_USD=24
export SSH_CIDR=REPLACE_YOUR_CURRENT_PUBLIC_IPV4/32
ssh-keygen -t rsa -b 3072 -f "$HOME/.ssh/proofops-r108"
export SSH_KEY="$HOME/.ssh/proofops-r108" SSH_PUBLIC_KEY="$HOME/.ssh/proofops-r108.pub"
# passphrase 키는 ssh-add로 agent에 넣는다. BatchMode를 사용하며 암호를 인자로 넣지 않는다.
ssh-add "$SSH_KEY"
export ALERT_EMAIL=REPLACE_OPERATOR_EMAIL ACME_EMAIL="$ALERT_EMAIL"
deploy/lightsail/preflight.sh                 # 로컬 command preview
deploy/lightsail/preflight.sh --apply         # 내일: STS account/region/AZ/catalog/usage 확인
deploy/lightsail/budget.sh --apply            # 월 USD20 account-wide 80/100% actual +100% forecast 이메일
```

quota API 접근을 위해 ServiceQuotas 권한을 확대하지 않는다. preflight는 운영자가 확인한
quota와 `get-instances` vCPU 합계, `get-static-ips` 수량을 비교한다. 미확인 quota는
apply를 막는다. 과금 경보는 hard cap이 아니며 Upstage/OpenRouter 비용은 AWS 청구에
포함되지 않는다. 중복 budget 이름이면 기존 budget을 확인하고 갱신하며 오류를 무시하지 않는다.

### 2. 이미지와 서버 준비 (약 10–25분; 최초 x86 build는 더 걸릴 수 있음)

Lightsail catalog에는 문서화된 CPU architecture 필드가 없다. kit는 standard Ubuntu
24.04 LTS x86_64만 선택하고, `get-bundles` 결과에서 active Linux·IPv4·2vCPU·4GB,
blueprint minPower 이상, 월24달러 이하 중 최저가를 선택하여 ID/가격을 `.state`에 보관한다.
ID/가격을 하드코딩하지 않는다. ARM catalog를 추측하지 않으며 원격 `uname -m`까지 검사한다.
현재 P2 로컬 이미지는 linux/arm64라 **x86 재빌드가 필수**다.

```sh
export IMAGE=proofops-r108-public:p3-amd64
export IMAGE_ARCHIVE="$HOME/proofops-r108-amd64.tar"
deploy/lightsail/pack.sh --build "$IMAGE_ARCHIVE"    # docker build linux/amd64 + save + SHA manifest
deploy/lightsail/create.sh                         # 무과금 preview
deploy/lightsail/create.sh --apply                 # 내일: 기존 이름 충돌 시 중단, 자동 재생성 없음
export STATIC_IP=REPLACE_RETURNED_STATIC_IPV4
# Lightsail 브라우저 SSH 콘솔에서 아래 fingerprint를 읽어 대조한다.
# sudo ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub
ssh-keyscan -t ed25519 "$STATIC_IP" > /tmp/proofops-r108-hostkey
ssh-keygen -lf /tmp/proofops-r108-hostkey
# 위 두 fingerprint 일치 확인 후에만 known_hosts에 추가.
cat /tmp/proofops-r108-hostkey >> "$HOME/.ssh/known_hosts"
```

Lightsail import는 ssh-rsa public key만 지원하므로 RSA3072를 생성하고 base64 문자열로 전송한다.
create는 imported SSH 공개키, IPv4-only VM, Project tag, 22=현재 IPv4/32만·80/443=public,
고정IP를 만든다. secret 없는 cloud-init은 Docker/Compose·UFW를 설치하고 데이터/backup
디렉터리와 systemd unit을 만든다. Lightsail 기본22 규칙은 생성 직후 정확한 포트 목록으로
교체하고 cloud-init UFW도 같은 SSH /32만 허용한다. IP가 바뀌면 먼저 운영자 SSH /32와
UFW 규칙을 업데이트한다. 콘솔 browser SSH는 이 규칙으로 차단될 수 있으므로 fingerprint
확인은 제한 적용 전 콘솔/직접 신뢰 경로에서 완료한다. 광범위22를 다시 열어 두지 않는다.
실패하면 `.state` operation/ownership 기록과 실제 리소스를 확인하고 정리하며 create를
무작정 반복하지 않는다. 고정IP가 분리된 상태로 남지 않도록 teardown을 즉시 준비한다.

### 3. Vercel production origin 확인과 private env 배치

현재 제출 checkout `.local/esg-submission-hosted`에는 `.vercel/project.json`이 없다.
production 도메인을 추측하지 않았다. 내일 Vercel 로그인 후 해당 checkout에서
`vercel link`로 **기존 제출 프로젝트**를 선택한다(새 프로젝트 생성 금지).
`.vercel/project.json`의 `projectId`/`orgId`와 Vercel Dashboard의 동일 프로젝트 Settings →
Domains를 대조하고 **현재 Production deployment에 붙은 alias**를 확인한다.
`vercel alias ls`/`vercel project inspect <existing-project-name>`로 재확인 가능하다.
preview/build URL과 production alias를 혼동하지 않는다. HTTP는 자동 HTTPS로 최종 이동시킨다.

```sh
export APP_ORIGIN=https://REPLACE_VERIFIED_VERCEL_PRODUCTION_DOMAIN
export RUNTIME_ENV="$HOME/proofops-runtime.env"
python3 deploy/lightsail/init-runtime.py --origin "$APP_ORIGIN" --output "$RUNTIME_ENV"
# 생성된 secret은 출력/재생성하지 않고 다음 배포에도 보존한다. 원본7일 동의 버전 유지.
deploy/lightsail/deploy.sh --apply
```

Docker save/scp/load를 사용하므로 app registry/push가 필요 없다. 서버는 Caddy 고정 tag를
한 번 pull하고 설정 검증 후 systemd를 재시작한다. API+worker는 UID10001/read-only,
공유 `/srv/proofops/data` bind volume, restart unless-stopped, API512MiB/worker2560MiB
합계3GiB, Caddy128MiB다. `.state/compose.env`는 secret 없으며 runtime.env는 서버0600.
`/srv/proofops/private`는 UID10001/GID10001 mode700; container에는 read-only bind로 필요한 키파일을 제공한다.
API 포트8000은 localhost에만 bind하고 외부에는 Caddy80/443만 공개한다. `<static-ip>.sslip.io`
DNS와 Let's Encrypt ACME TCP80를 사용한다. Docker local logs는10MiB×3/service, request/access
logging은 꺼진다. userdata/systemd/config 검증 로그에 키/쿠키/원문을 넣지 않는다.
공유 sslip.io 발급 rate limit/DNS 장애는 실제 TLS gate이며 실패하면 웹은 static을 유지한다.

키 배치는 승인된 provider 계정의 로컬0600 파일만 입력한다. `openrouter.env`는
`OPENROUTER_API_KEY=...` 한 줄, `upstage.env`는 `UPSTAGE_API_KEY=...` 한 줄이고 shell로
평가하지 않는다. live.json은 `enabled`, 실제 `report_year`·`period_start`·`period_end`,
`openrouter_key_file=/run/private/openrouter.env`, `upstage_key_file=/run/private/upstage.env`.
현재는 LIVE_DISABLED=true이므로 config.enabled가 true여도 전송은 없다.

```sh
export OPENROUTER_KEY_FILE=REPLACE_LOCAL_0600_FILE UPSTAGE_KEY_FILE=REPLACE_LOCAL_0600_FILE
export LIVE_CONFIG_FILE=REPLACE_LOCAL_0600_JSON
deploy/lightsail/keys.sh --apply    # 선택적 준비; 서버 UID10001/GID10001 mode600; 출력 없음
```

### 4. 제출 사이트 rewrite와 빌드 (현재 checkout은 수정하지 않음)

```sh
export WEB_CHECKOUT=/Users/ss020/Dev/ESG_ProofOps/.local/esg-submission-hosted
python3 deploy/lightsail/configure-web.py --checkout "$WEB_CHECKOUT" --static-ip "$STATIC_IP"
python3 deploy/lightsail/configure-web.py --checkout "$WEB_CHECKOUT" --static-ip "$STATIC_IP" --apply
git -C "$WEB_CHECKOUT" diff -- vercel.json
```

기존 `/hosted-api/:path*` destination만 `https://<static-ip>.sslip.io/:path*`로 바꾸고
SPA/API 규칙은 보존한다. vercel.json의 destination에 env interpolation을 쓰지 않는다.
Vercel production build env에 `VITE_ANALYSIS_BACKEND=hosted`, `VITE_HOSTED_API_BASE=/hosted-api`
설정 후 재배포한다. 기존 `VITE_DEMO_STATIC=true pnpm build`는 static shell을 사용하는
현 구조의 build 명령이므로 유지한다. APP_ORIGIN은 API sslip.io가 아닌 브라우저의 정확한
production origin이다. 웹은 같은 origin `/hosted-api`로만 호출한다. 브라우저에서 sslip.io
직접 cross-site cookie 호출을 쓰지 않는다. VITE 변수에는 provider/session/AWS 키가 없다.

### 5. 내일 실측 gate — 이 작업에서는 모두 not_run

처음에는 웹 static·서버 admission=false를 유지한다. operator-only blocked smoke 동안만
private runtime.env에서 HOSTED_ACCEPT_UPLOADS=true, R108_ACCEPT_NEW_RUNS=true,
ANALYSIS_BACKEND=r108로 바꾸고 LIVE_DISABLED=true를 유지하여 deploy.sh로 재적용한다.
계약에 맞는 정상 PDF 최대2쪽 처리, 전체 원본300쪽/50MiB 제한을 유지한다.

- TLS: sslip.io DNS→static IP, 인증서 hostname/chain/만료 확인, HTTPS health200, HTTP→HTTPS.
- Set-Cookie: production 페이지에서 초대 로그인200, `__Host-proofops_session; Secure;
  HttpOnly; Path=/; SameSite=Lax; no Domain`; 새로고침 후 session200/CSRF write.
  Network에서 Cookie가 **production /hosted-api에 재전송**되는지 확인하고 cookie/code/body를
  공개 evidence에 붙이지 않는다. HTTP CLI 수동 Cookie 검사만으로 브라우저 통과를 주장하지 않는다.
- 업로드: 권리가 있는 실제50MiB 이하/300쪽 이하 정상 PDF를 production proxy로 전송하여201,
  서버 length/SHA 일치 확인. exact52428800 bytes와52428801 bytes fixture는 별도로 확인하여
  cap 이하가 proxy에서 잘리지 않고 cap 초과는413(허용429/422 사유도 구분); 동시 업로드429.
  Vercel Functions의4.5MB 한도를 외부 rewrite 경로에 그대로 적용하지 않으며50MiB가 된다고
  가정하지도 않는다. Network Timing, 전송 bytes, 응답 status만 기록하고 fixture는 삭제한다.
- 120초: Vercel 외부 origin 응답-header 제한은 공지상120s. 실제 정상 최대 업로드 요청의
  total/TTFB가120s 이내인지 기록하고 run acceptance202는 짧게 끝나는지 측정한다.
  worker 분석 전체 시간은 polling으로 분리되어120초 HTTP 한 요청에 묶이지 않는다.
  제한 자체의 slow-origin 경계 검사는 private staging에서만119/121초 지연 응답으로 확인한다
  (production auth API에 sleep/debug endpoint를 추가하지 않는다). timeout이면 idempotency로
  상태 확인 후 재시도하며 유료 job을 중복 만들지 않는다.
- default offline smoke는 partial_blocked/LIVE_BINDING_UNAVAILABLE, result409가 정답이다.
  Linux live opt-in의 P2 artifact는200/null grade/LINUX_SOURCE_READER_UNRESOLVED이며
  완성 분석이 아니다. 승인 reader 통합 후에만 authorized `smoke.py --expect result --allow-live`
  한 번으로 결과200·hold/source mapping·실제 비용·4GB RSS를 검증한다. 행사 장부 새로 만들기 금지.

```sh
umask 077
ssh -i "$SSH_KEY" "ubuntu@$STATIC_IP" \
  "sudo docker compose --project-directory /srv/proofops --env-file /srv/proofops/compose.env -f /srv/proofops/compose.yaml exec -T api python scripts/hosted_control.py invite --tenant 11111111-1111-4111-8111-111111111111 --user operator-smoke --role admin" > "$HOME/proofops-smoke-invite.txt"
chmod 600 "$HOME/proofops-smoke-invite.txt"
export INVITE_FILE="$HOME/proofops-smoke-invite.txt" SMOKE_BASE="$APP_ORIGIN/hosted-api"
deploy/lightsail/smoke.sh --apply
# Browser gate를 따로 통과시키고 operator fixture/invite 파일을 삭제한다.
```

smoke는 health→login→session→PDF201→run202→worker poll→결과→purge completed→logout을
실행하고 secret/UUID/원문 없이 상태·길이·시간만 출력한다. 공개 admission은 Linux release
gate를 통과할 때까지 다시 닫고 static 웹을 유지한다. API/worker 원장/도메인 guard는 바꾸지 않는다.

### 6. 본선 운영·백업·롤백·중지

초대 발급은 위 SSH CLI의 tenant/user/role만 바꿔 실행하여 one-time code를 개인 경로로
전달한다. invite24h, session8h/idle30m. viewer/editor/reviewer/admin을 구분한다.
일일 운영: health/ready/runtime, queue8/active1, 폐기 실패, 디스크/RSS, Docker logs 로테이션,
`cost.sh --apply`의 AWS budget incurred/forecast를 확인한다. 비용 미정산/unknown은 유지하고
새 event ID/빈 ledger로 cap을 초기화하지 않는다. 아래 원장 SQL은 aggregate만 출력한다.

```sh
# 서버 /srv/proofops에서 (sudo -i 이후)
docker compose --env-file compose.env exec -T api python -c 'import sqlite3,json; db=sqlite3.connect("file:/data/deletions.sqlite3?mode=ro",uri=True); print(json.dumps({"spend_status_micro_usd":db.execute("select status,sum(amount) from spend group by status").fetchall(),"aged_event_micro_usd":db.execute("select sum(amount) from event_totals").fetchone()[0]}))'
# payload-free application backup; original/prepared/display PDF/auth 제외
# admission 닫고 worker drain/unknown 기록 후 API/worker를 중지
docker compose --env-file compose.env stop api worker
docker compose --env-file compose.env run --rm --no-deps api python scripts/hosted_control.py backup --path /data/backups/UNIQUE_DATE
docker compose --env-file compose.env up -d api worker
```

이 kit는 backup을 data bind 내부 `/data/backups/UNIQUE_DATE`에 두어 maintenance에서 접근한다. `/srv/proofops/backups`는
암호화 export staging 용도이며 자동 raw-copy/VM snapshot에 쓰지 않는다. 온라인 앱 백업은
가장 오래된 source creation+14d 만료이며 purge 시 해당 backup artifact도 삭제한다.
복구: acceptance 닫기→API/worker stop→동일 ledger identity/current deletions.sqlite3를
보존→`docker compose run --rm --no-deps api python scripts/hosted_control.py restore --path
/data/backups/UNIQUE_DATE`→API/worker 시작. 원본 PDF는 복구되지 않으므로 reupload,
SOURCE_UNAVAILABLE가 정상이다. 독립 ledger를 이전 버전으로 rewind하지 않는다.

롤백 순서: HOSTED_ACCEPT_UPLOADS=false/R108_ACCEPT_NEW_RUNS=false/ANALYSIS_BACKEND=static/
LIVE_DISABLED=true를 로컬 private env에 설정하여 deploy.sh 재적용→Vercel production
`VITE_ANALYSIS_BACKEND=static` 재빌드/재배포→필요하면 `vercel.json.p3-backup` rewrite 복원.
직전 hosted schema1 호환 이미지로만 바꾸고 data/돈/삭제 ledger를 유지한다. APP_ENV=local
우회는 없다. worker active/unknown 요청을 유료 재전송하지 않는다.

중지는 `systemctl stop proofops`로 API+worker+Caddy를 멈출 수 있지만 **일반 Lightsail
VM은 stopped 상태에도 삭제할 때까지 과금**된다. 원본7일 deadline이 남았으면 유지보수
프로세스를 유지하거나 모든 활성 문서를 authorized deletion으로 purge completed 확인 후
완전히 중지한다. 과금 종료는 아래 teardown이다.

```sh
# 접수 닫고 drain/unknown 상태 확인한 뒤 서버에서 API+worker stop (새 dispatch 방지)
# current 독립 ledger의 SQLite online copy만 export (PDF/키/세션 DB 제외)
sudo systemctl stop proofops
cd /srv/proofops
sudo docker compose --env-file compose.env run --rm --no-deps api python -c 'import sqlite3; src=sqlite3.connect("file:/data/deletions.sqlite3?mode=ro",uri=True); dst=sqlite3.connect("/data/operator-ledger.sqlite3"); src.backup(dst); dst.close(); src.close()'
# sudo install -o ubuntu -g ubuntu -m600 /srv/proofops/data/operator-ledger.sqlite3 /home/ubuntu/operator-ledger.sqlite3
# 로컬로 scp 후 operator custody에서 암호화 보관; 임시 서버 copy 제거. 원장에는 hashed fences/IDs가 있어 공개 금지.
# 아래는 로컬 shell에서, 보관 성공 확인 후에만:
export CONFIRM_DELETE="$NAME" LEDGER_ARCHIVED=true
deploy/lightsail/teardown.sh          # 정확한 리소스 목록 preview
deploy/lightsail/teardown.sh --apply  # 내일/본선 후: owned VM + IP + 해당 source snapshots + imported key 삭제
```

teardown은 account/서울/name/owned.txt/Project tag를 대조하고 타 인스턴스에 IP가 붙어 있으면
삭제 전에 중단한다. 자동 snapshot addon이 외부에서 켜졌다면 해당 VM automatic snapshots도
먼저 제거한다. 마지막 list로 VM/IP/manual snapshots absence를 확인한다. budget 경보는 남긴다.
VM 삭제는 서버 raw PDFs/키/Caddy volumes도 없애므로 독립 ledger export를 먼저 완료한다.

### 7. 예상 비용·검증 범위

현재 공식4GB IPv4 Linux plan은 USD24/month, fixed hourly cap이며 서울 catalog 조회가
정본이다. 단순730h 환산으로264h는약USD8.68,11일+행사 모델 최대5는약USD13.68; VAT/
전송 초과/유료 Vercel/도메인/backup 비용 별도, 청구 확정 견적은 아니다. 예상 전체10–20달러
범위를 유지하고 선택 bundle 월24달러 초과 시 kit는 중단한다. 연결된 static IP는 free,
분리된 IP는 과금될 수 있다. 앱 backup은 같은 disk이며 AWS snapshots는 기본off(원본/키
유출·TTL 무효화를 피함). 준비40–70분+사용자 계정·TLS/browser gate 시간, DNS/ACME 실패는 별도.

P3 로컬 검증: ShellCheck/각 Bash syntax, dry-run remote-call trap, catalog/권한/teardown
mock contract, Compose API+worker(no Caddy), health/login/upload202/poll/purge/restart.
로컬 arm64 증거를 amd64·TLS·50MiB Vercel·120s staging·live4GB 결과로 바꾸지 않는다.

공식 참조(2026-10-09 문서 확인, API 호출 아님):
[Lightsail get-bundles](https://docs.aws.amazon.com/cli/latest/reference/lightsail/get-bundles.html),
[Lightsail quotas](https://docs.aws.amazon.com/general/latest/gr/lightsail.html),
[Lightsail bundle pricing](https://docs.aws.amazon.com/lightsail/latest/userguide/amazon-lightsail-bundles.html),
[stopped billing](https://docs.aws.amazon.com/lightsail/latest/userguide/amazon-lightsail-frequently-asked-questions-faq-billing-and-account-management.html),
[Budgets IAM](https://docs.aws.amazon.com/service-authorization/latest/reference/list_budgets.html),
[Vercel external rewrites](https://vercel.com/docs/routing/rewrites),
[Vercel120s origin limit](https://vercel.com/changelog/cdn-origin-timeout-increased-to-two-minutes),
[Caddy body limit](https://caddyserver.com/docs/caddyfile/directives/request_body).

## P4 local amd64 image and operator selection

Build without pushing: `docker buildx build --platform linux/amd64 --load
-f deploy/public/Dockerfile -t proofops-r108-public:p4-amd64 .`.
Run key-free Compose rehearsal with `IMAGE=proofops-r108-public:p4-amd64
EVIDENCE_DIR=/path/to/private/evidence deploy/lightsail/local-smoke.sh`.
The script supplies dummy empty key files only for the Linux blocked-result check;
no provider credentials or cloud calls are needed.

In private live.json, omit `analysis_profile` for the existing P2 profile or set
`"analysis_profile":"r108-finals-candidate"` for the frozen integration bundle.
Linux defaults to approved v3; macOS retains Apple. To request it explicitly,
set the single entry `"rendered_reader_profile":"upstage-ocr-page-v3"`.
V1/v2 selections remain `LINUX_SOURCE_READER_UNRESOLVED`; operator JSON cannot
approve a reader. The release allowlist in `config/hosted_rendered_readers.json`
records O1d SHA256 `69f0797dbae5420ba1b5deb4ef2f12df3e7a820c0a9a37c5f5d16c37deea741e`.
Default live flags remain off. The key-free Compose probe verifies approved v3
runtime provenance and failed-v2 non-dispatch. Actual PNG-only OCR uses the same
hosted budget/lease broker as parse/Luna, and result reads use cached receipt
bytes only. Linux live capacity and public TLS remain separate release checks.
Close live admission or select a held reader to roll back new work; preserve
saved readers/receipts and the independent budget/deletion ledger.

The image includes the pilot's runtime PyYAML dependency, delegated review helper,
both lockfiles and their matching SBOM. These are required for its existing
supply-chain admission gate; changing a lockfile requires regenerating the SBOM
with `uv run python scripts/check_licenses.py --generate-sbom
--env ENABLE_LEGACY_PYMUPDF=false` before rebuilding.
