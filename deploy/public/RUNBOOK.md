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
