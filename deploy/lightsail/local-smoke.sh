#!/usr/bin/env bash
# Local-only Compose rehearsal: no Caddy, provider keys, cloud or registry pull.
set -euo pipefail
set +x
umask 077
HERE="$(cd "$(dirname "$0")" && pwd)"
IMAGE=${IMAGE:-proofops-r108-public:p2}
LOCAL_PORT=${LOCAL_PORT:-18083}
EVIDENCE_DIR=${EVIDENCE_DIR:-"$HERE/.state/local-smoke"}
mkdir -p "$EVIDENCE_DIR"
work=$(mktemp -d)
project="p3-smoke-$$"
cleanup() {
  docker compose --project-name "$project" --project-directory "$work" --env-file "$work/compose.env" -f "$HERE/compose.yaml" down --volumes --remove-orphans >/dev/null 2>&1 || true
  # Docker creates UID10001 directories; remove only this temporary probe volume.
  docker run --rm --pull never --user 0 --entrypoint python -v "$work:/probe" "$IMAGE" -c 'import shutil; shutil.rmtree("/probe/data",ignore_errors=True)' >/dev/null 2>&1 || true
  rm -rf "$work"
}
trap cleanup EXIT
mkdir "$work/data" "$work/private"
cp "$HERE/runtime.env.example" "$work/runtime.env"
python3 - "$work/runtime.env" <<'CHECK'
import secrets,sys
from pathlib import Path
p=Path(sys.argv[1]); s=p.read_text().replace('https://REPLACE_WITH_PRODUCTION_DOMAIN','https://p3-local.example').replace('REPLACE_WITH_AT_LEAST_32_RANDOM_BYTES',secrets.token_urlsafe(48)).replace('HOSTED_ACCEPT_UPLOADS=false','HOSTED_ACCEPT_UPLOADS=true').replace('R108_ACCEPT_NEW_RUNS=false','R108_ACCEPT_NEW_RUNS=true').replace('ANALYSIS_BACKEND=static','ANALYSIS_BACKEND=r108')
p.write_text(s); p.chmod(0o600)
CHECK
printf 'IMAGE=%s\nLOCAL_PORT=%s\nAPI_HOST=p3-local.example\nACME_EMAIL=p3@example.invalid\n' "$IMAGE" "$LOCAL_PORT" > "$work/compose.env"
docker run --rm --pull never --user 0 --entrypoint python -v "$work/data:/data" "$IMAGE" -c 'import os; os.chown("/data",10001,10001); os.chmod("/data",0o700)' >/dev/null
COMPOSE=(docker compose --project-name "$project" --project-directory "$work" --env-file "$work/compose.env" -f "$HERE/compose.yaml")
"${COMPOSE[@]}" config --quiet
startup_started=$(python3 -c 'import time; print(time.monotonic())')
"${COMPOSE[@]}" up -d --wait --wait-timeout 60 --pull never api worker
python3 - "$startup_started" "$EVIDENCE_DIR/startup.json" <<'CHECK'
import json,sys,time
from pathlib import Path
Path(sys.argv[2]).write_text(json.dumps(dict(api_worker_healthy_seconds=round(time.monotonic()-float(sys.argv[1]),3))))
CHECK
issue_invites() {
  local tenant=$1 user=$2 foreign_tenant=$3 foreign_user=$4
  "${COMPOSE[@]}" exec -T api python scripts/hosted_control.py invite --tenant "$tenant" --user "$user" --role admin > "$work/invite.txt"
  "${COMPOSE[@]}" exec -T api python scripts/hosted_control.py invite --tenant "$foreign_tenant" --user "$foreign_user" --role admin > "$work/foreign-invite.txt"
  chmod 600 "$work/invite.txt" "$work/foreign-invite.txt"
}
issue_invites 11111111-1111-4111-8111-111111111111 p3-smoke 22222222-2222-4222-8222-222222222222 p3-smoke-foreign
python3 "$HERE/smoke.py" --base "http://127.0.0.1:$LOCAL_PORT" --origin https://p3-local.example --invite-file "$work/invite.txt" --foreign-invite-file "$work/foreign-invite.txt" --expect blocked --output "$EVIDENCE_DIR/smoke.json"
"${COMPOSE[@]}" restart api worker
"${COMPOSE[@]}" up -d --wait --wait-timeout 60 --pull never api worker
issue_invites 22222222-2222-4222-8222-222222222222 p3-restart 33333333-3333-4333-8333-333333333333 p3-restart-foreign
python3 "$HERE/smoke.py" --base "http://127.0.0.1:$LOCAL_PORT" --origin https://p3-local.example --invite-file "$work/invite.txt" --foreign-invite-file "$work/foreign-invite.txt" --expect blocked --output "$EVIDENCE_DIR/restart-smoke.json"
# Exercise P2's Linux result DTO with empty dummy key paths. The Linux source gate
# returns before reading keys or dispatch. Fail closed if that gate has changed.
"${COMPOSE[@]}" exec -T api python -c 'import json,urllib.request; r=json.load(urllib.request.urlopen("http://127.0.0.1:8000/v1/runtime")); assert r["source_verifier"]=="upstage-ocr-page-v3" and not r["live_analysis"]; assert r["rendered_reader_gate_report_sha256"]=="69f0797dbae5420ba1b5deb4ef2f12df3e7a820c0a9a37c5f5d16c37deea741e"'
printf '%s\n' '{"enabled":true,"llm_provider":"openai","openai_key_file":"/run/private/openai.env","openrouter_key_file":"/run/private/openrouter.env","upstage_key_file":"/run/private/upstage.env","report_year":2025,"period_start":"2024-01-01","period_end":"2024-12-31","analysis_profile":"r108-finals-candidate","rendered_reader_profile":"upstage-ocr-page-v2"}' > "$work/private/live.json"
: > "$work/private/openai.env"
: > "$work/private/openrouter.env"
: > "$work/private/upstage.env"
chmod 600 "$work/private/"*
docker run --rm --pull never --user 0 --entrypoint python -v "$work/private:/private" "$IMAGE" -c 'import os; [os.chown("/private/"+n,10001,10001) for n in os.listdir("/private")]' >/dev/null
python3 - "$work/runtime.env" <<'CHECK'
from pathlib import Path
import sys
p=Path(sys.argv[1]); p.write_text(p.read_text().replace('LIVE_DISABLED=true','LIVE_DISABLED=false'))
CHECK
"${COMPOSE[@]}" up -d --wait --wait-timeout 60 --pull never api worker
issue_invites 33333333-3333-4333-8333-333333333333 p3-linux-result 44444444-4444-4444-8444-444444444444 p3-linux-foreign
python3 "$HERE/smoke.py" --base "http://127.0.0.1:$LOCAL_PORT" --origin https://p3-local.example --invite-file "$work/invite.txt" --foreign-invite-file "$work/foreign-invite.txt" --expect linux-blocked-result --output "$EVIDENCE_DIR/linux-result-smoke.json"
python3 - "$EVIDENCE_DIR/linux-result-smoke.json" <<'CHECK'
import json,sys
from pathlib import Path
p=json.loads(Path(sys.argv[1]).read_text())["pipeline_profiles"]
assert p["analysis_profile"]=="r108-finals-candidate" and p["rendered_reader_requested"]=="upstage-ocr-page-v2" and p["source_reader"]=="unresolved"
CHECK
"${COMPOSE[@]}" ps --format json > "$EVIDENCE_DIR/compose-ps.json"
echo 'Local Compose API+worker smoke/restart/purge passed; TLS/Linux live capacity remain not_run.'
