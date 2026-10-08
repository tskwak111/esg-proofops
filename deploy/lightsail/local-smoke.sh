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
"${COMPOSE[@]}" up -d --wait --wait-timeout 60 --pull never api worker
"${COMPOSE[@]}" exec -T api python scripts/hosted_control.py invite --tenant 11111111-1111-4111-8111-111111111111 --user p3-smoke --role admin > "$work/invite.txt"
chmod 600 "$work/invite.txt"
python3 "$HERE/smoke.py" --base "http://127.0.0.1:$LOCAL_PORT" --origin https://p3-local.example --invite-file "$work/invite.txt" --expect blocked --output "$EVIDENCE_DIR/smoke.json"
"${COMPOSE[@]}" restart api worker
"${COMPOSE[@]}" up -d --wait --wait-timeout 60 --pull never api worker
"${COMPOSE[@]}" exec -T api python scripts/hosted_control.py invite --tenant 22222222-2222-4222-8222-222222222222 --user p3-restart --role admin > "$work/invite.txt"
python3 "$HERE/smoke.py" --base "http://127.0.0.1:$LOCAL_PORT" --origin https://p3-local.example --invite-file "$work/invite.txt" --expect blocked --output "$EVIDENCE_DIR/restart-smoke.json"
# Exercise P2's Linux result DTO with empty dummy key paths. The Linux source gate
# returns before reading keys or dispatch. Fail closed if that gate has changed.
"${COMPOSE[@]}" exec -T api python -c 'import json,urllib.request; r=json.load(urllib.request.urlopen("http://127.0.0.1:8000/v1/runtime")); assert r["source_verifier"]=="unresolved" and not r["live_analysis"]'
printf '%s\n' '{"enabled":true,"openrouter_key_file":"/run/private/openrouter.env","upstage_key_file":"/run/private/upstage.env","report_year":2025,"period_start":"2024-01-01","period_end":"2024-12-31"}' > "$work/private/live.json"
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
"${COMPOSE[@]}" exec -T api python scripts/hosted_control.py invite --tenant 33333333-3333-4333-8333-333333333333 --user p3-linux-result --role admin > "$work/invite.txt"
python3 "$HERE/smoke.py" --base "http://127.0.0.1:$LOCAL_PORT" --origin https://p3-local.example --invite-file "$work/invite.txt" --expect linux-blocked-result --output "$EVIDENCE_DIR/linux-result-smoke.json"
"${COMPOSE[@]}" ps --format json > "$EVIDENCE_DIR/compose-ps.json"
echo 'Local Compose API+worker smoke/restart/purge passed; TLS/Linux live capacity remain not_run.'
