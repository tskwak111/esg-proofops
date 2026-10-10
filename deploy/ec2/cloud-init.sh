#!/usr/bin/env bash
# Secret-free EC2 user-data, reused from Lightsail. Application image is transferred later with scp.
set -euo pipefail
umask 077
# EC2: Ubuntu24.04 arm64, no instance profile or credentials in user-data.
[[ $(uname -m) == aarch64 ]] || { echo 'EC2 requires aarch64' >&2; exit 2; }
# shellcheck source=/dev/null
. /etc/os-release
[[ $ID == ubuntu && $VERSION_ID == 24.04 ]] || exit 2
# Keep IPv6 off at the host as well as the EC2 interface/security group.
printf '%s\n' 'net.ipv6.conf.all.disable_ipv6 = 1' 'net.ipv6.conf.default.disable_ipv6 = 1' > /etc/sysctl.d/90-proofops-ipv4.conf
sysctl --system >/dev/null
SSH_CIDR=__SSH_CIDR__
export DEBIAN_FRONTEND=noninteractive
# The EIP is attached just after instance-running; wait for that IPv4 network path.
updated=false
for ((attempt=0; attempt<60; attempt++)); do
  if apt-get update; then updated=true; break; fi
  sleep 5
done
"$updated" || { echo 'Package index unavailable after EIP wait' >&2; exit 1; }
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
