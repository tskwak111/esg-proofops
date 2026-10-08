#!/usr/bin/env bash
# Secret-free Lightsail user-data. Application image is transferred later with scp.
set -euo pipefail
umask 077
SSH_CIDR=__SSH_CIDR__
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y docker.io docker-compose-v2 ca-certificates curl ufw
ufw default deny incoming
ufw allow from "$SSH_CIDR" to any port 22 proto tcp
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable
systemctl enable --now docker
install -d -m 700 /srv/proofops
install -d -o 10001 -g 10001 -m 700 /srv/proofops/private
install -d -o 10001 -g 10001 -m 700 /srv/proofops/data /srv/proofops/backups
cat > /etc/docker/daemon.json <<'JSON'
{"log-driver":"local","log-opts":{"max-size":"10m","max-file":"3"},"live-restore":true}
JSON
systemctl restart docker
cat > /etc/systemd/system/proofops.service <<'UNIT'
[Unit]
Description=ProofOps hosted API worker and TLS proxy
Requires=docker.service
After=docker.service network-online.target
Wants=network-online.target
ConditionPathExists=/srv/proofops/runtime.env
ConditionPathExists=/srv/proofops/compose.yaml
[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=/srv/proofops
ExecStart=/usr/bin/docker compose --env-file compose.env -f compose.yaml --profile tls up -d --pull never
ExecStop=/usr/bin/docker compose --env-file compose.env -f compose.yaml --profile tls stop
TimeoutStartSec=180
[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable proofops.service
# No auto-snapshots: they would contain raw PDFs and auth/key material.
