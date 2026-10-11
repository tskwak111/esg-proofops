#!/usr/bin/env bash
# Shared remote EC2/Lightsail gate. No provider calls or credential output.
set -euo pipefail
set +x

hosted_control() {
  "${compose[@]}" exec -T api python scripts/hosted_control.py "$@"
}

drain_and_wait() {
  local force=$1 timeout=$2 rc
  hosted_control drain || return $?
  if hosted_control wait-idle --timeout "$timeout"; then
    return 0
  else
    rc=$?
    if [[ $force == true && $rc == 3 ]]; then
      echo 'WARNING: forced restart with running work; lease/accounting fences remain reserved.' >&2
      return 0
    fi
    echo 'Restart aborted; maintenance remains enabled. Inspect work, then explicitly resume or retry deployment.' >&2
    return "$rc"
  fi
}

deploy_release() {
  local stage=$1 force=$2 timeout=$3 api health attempt
  [[ -d $stage && $force =~ ^(true|false)$ && $timeout =~ ^[0-9]{1,5}$ ]] || return 2
  cd /srv/proofops
  exec 9>.deploy.lock
  flock -n 9 || { echo 'Another deployment owns the restart gate.' >&2; return 1; }
  compose=(sudo docker compose --env-file compose.env -f compose.yaml)
  sudo docker load --input "$stage/image.tar" >/dev/null
  sudo docker pull caddy:2.10.2-alpine >/dev/null
  if [[ -f compose.yaml || -f compose.env ]]; then
    # Use the CURRENT container/config; unsupported drain commands fail closed.
    drain_and_wait "$force" "$timeout" || return $?
  fi
  sudo install -m 600 "$stage/runtime.env" "$stage/compose.env" /srv/proofops/
  sudo install -m 644 "$stage/compose.yaml" "$stage/Caddyfile" /srv/proofops/
  "${compose[@]}" --profile tls config --quiet
  "${compose[@]}" run --rm --no-deps caddy caddy validate --config /etc/caddy/Caddyfile </dev/null >/dev/null
  # Also covers first install: flag is committed before workers can start.
  "${compose[@]}" run --rm --no-deps api python scripts/hosted_control.py drain
  sudo systemctl restart proofops.service
  for ((attempt=0; attempt<60; attempt++)); do
    api=$("${compose[@]}" ps -q api)
    health=''
    if [[ -n $api ]]; then
      health=$(sudo docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{end}}' "$api")
    fi
    if [[ $health == healthy ]]; then
      "${compose[@]}" exec -T api python -c 'import json,urllib.request; assert json.load(urllib.request.urlopen("http://127.0.0.1:8000/v1/health/ready",timeout=2))["status"] == "ok"'
      hosted_control resume
      return 0
    fi
    sleep 1
  done
  echo 'Replacement API is not healthy; maintenance remains enabled.' >&2
  return 1
}

if [[ ${BASH_SOURCE[0]} == "$0" ]]; then
  [[ $# == 3 ]] || { echo 'Usage: drain-restart.sh STAGE FORCE TIMEOUT' >&2; exit 2; }
  deploy_release "$@"
fi
