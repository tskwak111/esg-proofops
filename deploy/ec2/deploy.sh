#!/usr/bin/env bash
# shellcheck source=common.sh
source "$(dirname "$0")/common.sh"
if ! "$APPLY"; then
  echo 'DRY RUN: verify archive SHA/architecture and private runtime config; SSH verifies uname; scp archive/config; docker load; pull Caddy; systemd restart. No SSH/cloud calls.'
  exit
fi
python3 "$HERE/ec2.py" target
need STATIC_IP; need SSH_KEY; need IMAGE_ARCHIVE; need RUNTIME_ENV; need ACME_EMAIL
[[ $STATIC_IP =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ && -f $SSH_KEY && -f $IMAGE_ARCHIVE && -f $IMAGE_ARCHIVE.json ]] || exit 2
[[ $IMAGE =~ ^[a-zA-Z0-9][a-zA-Z0-9._:/-]+$ && $ACME_EMAIL =~ ^[a-zA-Z0-9._+%-]+@[a-zA-Z0-9.-]+$ ]] || exit 2
python3 "$HERE/check-config.py" "$RUNTIME_ENV"
python3 - "$IMAGE_ARCHIVE" "$IMAGE" "$ARCH" <<'CHECK'
import hashlib,json,sys
from pathlib import Path
p=Path(sys.argv[1]); m=json.loads(Path(str(p)+'.json').read_text())
assert m['image']==sys.argv[2] and m['arch']==sys.argv[3], 'Wrong image/architecture'
assert hashlib.file_digest(p.open('rb'),'sha256').hexdigest()==m['archive_sha256'], 'Archive SHA mismatch'
CHECK
SSH=(ssh -i "$SSH_KEY" -o BatchMode=yes -o StrictHostKeyChecking=yes "ubuntu@$STATIC_IP")
SCP=(scp -q -i "$SSH_KEY" -o BatchMode=yes -o StrictHostKeyChecking=yes)
"${SSH[@]}" 'sudo cloud-init status --wait >/dev/null'
actual=$("${SSH[@]}" uname -m)
case "$ARCH:$actual" in amd64:x86_64|arm64:aarch64) ;; *) echo 'Server/image CPU mismatch.' >&2; exit 2;; esac
remote="/home/ubuntu/proofops-upload-$$"
"${SSH[@]}" "umask 077; mkdir '$remote'"
cleanup() { "${SSH[@]}" "rm -rf -- '$remote'" >/dev/null 2>&1 || true; }
trap cleanup EXIT
"${SCP[@]}" "$IMAGE_ARCHIVE" "ubuntu@$STATIC_IP:$remote/image.tar"
"${SCP[@]}" "$RUNTIME_ENV" "ubuntu@$STATIC_IP:$remote/runtime.env"
"${SCP[@]}" "$HERE/compose.yaml" "$HERE/Caddyfile" "ubuntu@$STATIC_IP:$remote/"
printf 'IMAGE=%s\nCADDY_IMAGE=caddy:2.10.2-alpine\nAPI_HOST=%s.sslip.io\nACME_EMAIL=%s\nLOCAL_PORT=8000\n' "$IMAGE" "$STATIC_IP" "$ACME_EMAIL" > "$STATE_DIR/compose.env"
"${SCP[@]}" "$STATE_DIR/compose.env" "ubuntu@$STATIC_IP:$remote/compose.env"
# No keys in command args, user-data, env output or logs. Existing data/ledger preserved.
"${SSH[@]}" "sudo bash -s -- '$remote'" <<'REMOTE'
set -euo pipefail
set +x
stage=$1
sudo docker load --input "$stage/image.tar" >/dev/null
sudo install -m 600 "$stage/runtime.env" "$stage/compose.env" /srv/proofops/
sudo install -m 644 "$stage/compose.yaml" "$stage/Caddyfile" /srv/proofops/
sudo docker pull caddy:2.10.2-alpine >/dev/null
cd /srv/proofops
sudo docker compose --env-file compose.env -f compose.yaml --profile tls config --quiet
sudo docker compose --env-file compose.env -f compose.yaml run --rm --no-deps caddy validate --config /etc/caddy/Caddyfile >/dev/null
sudo systemctl restart proofops.service
REMOTE
echo "Deployed private config/image; test https://$STATIC_IP.sslip.io/v1/health/ready and Vercel proxy before enabling admission."
