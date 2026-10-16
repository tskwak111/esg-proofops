#!/usr/bin/env bash
# shellcheck source-path=SCRIPTDIR
# Server-only ECR deployment. Preview by default; no runtime secrets leave the host.
set -euo pipefail
set +x
umask 077
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

validate_target() {
  [[ $2 == ap-southeast-2 && $1 =~ ^[0-9]{12}\.dkr\.ecr\.ap-southeast-2\.amazonaws\.com/[a-z0-9]+([._/-][a-z0-9]+)*:[0-9a-f]{40}$ ]] || {
    echo 'Expected a Sydney private ECR image with a full commit SHA tag.' >&2
    return 2
  }
}

# Both API and worker must run the exact pulled image and pass Docker healthchecks.
wait_healthy() {
  local expected=$1 attempt service container state good
  for ((attempt=0; attempt<120; attempt++)); do
    good=true
    for service in api worker; do
      container=$("${compose[@]}" ps -q "$service") || return 1
      state=''
      if [[ -n $container ]]; then
        state=$(docker inspect --format '{{.Image}} {{if .State.Health}}{{.State.Health.Status}}{{end}}' "$container") || return 1
      fi
      [[ $state == "$expected healthy" ]] || good=false
    done
    if "$good" && "${compose[@]}" exec -T api python -c 'import json,urllib.request; assert json.load(urllib.request.urlopen("http://127.0.0.1:8000/v1/health/ready",timeout=2))["status"] == "ok"'; then
      return 0
    fi
    sleep 1
  done
  return 1
}

finish_deployment() {
  local rc=$?
  trap - EXIT INT TERM
  if "$switched"; then
    echo 'Deployment failed; restoring the previous image.' >&2
    # Resume can commit before its client fails; re-drain before touching that release.
    if "$resume_attempted" && ! drain_and_wait false 600; then
      echo "Cannot re-drain after uncertain resume; leave services intact. Backup: $stage/compose.env" >&2
      rm -rf -- "$stage/docker"
      exit 1
    fi
    if cp -p "$stage/compose.env" "$stage/restore.env" &&
       mv -f "$stage/restore.env" compose.env &&
       systemctl restart proofops.service && wait_healthy "$previous_id" &&
       hosted_control resume; then
      echo "ROLLED_BACK image=$previous"
    else
      echo "Rollback failed; do not resume unhealthy services. Backup retained at $stage/compose.env" >&2
      rm -rf -- "$stage/docker"
      exit 1
    fi
    [[ $rc != 0 ]] || rc=1
  fi
  rm -rf -- "$stage"
  exit "$rc"
}

deploy_from_ecr() {
  local image=$1 region=$2 directory=$3 helper registry target_id
  validate_target "$image" "$region"
  cd "$directory"
  # Same inode/FD as the existing manual drain-restart path.
  exec 9>.deploy.lock
  flock -n 9 || { echo 'Another deployment owns the restart gate.' >&2; return 1; }
  for file in compose.env compose.yaml runtime.env; do
    [[ -f $file && ! -L $file ]] || { echo "Missing/unsafe $file" >&2; return 2; }
  done
  helper="$HERE/drain-restart.sh"
  [[ -f $helper ]] || helper="$HERE/../public/drain-restart.sh"
  # shellcheck source=../public/drain-restart.sh
  source "$helper"
  # Compose must use its server IMAGE, not an inherited shell override.
  unset IMAGE
  compose=(docker compose --env-file compose.env -f compose.yaml)
  stage=$(mktemp -d "$directory/.deploy-ecr.XXXXXX")
  switched=false
  resume_attempted=false
  trap finish_deployment EXIT
  trap 'exit 130' INT
  trap 'exit 143' TERM
  cp -p compose.env "$stage/compose.env"
  previous=$(python3 - "$image" "$stage/new.env" <<'PY'
import pathlib, re, sys
raw = pathlib.Path('compose.env').read_bytes()
pattern = rb'(?m)^IMAGE=([^\r\n]+)\r?$'
matches = list(re.finditer(pattern, raw))
if len(matches) != 1:
    raise SystemExit('compose.env must contain exactly one unquoted IMAGE= entry')
old = matches[0].group(1).decode('ascii')
if not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9._:/@-]+', old):
    raise SystemExit('Unsupported previous image reference')
# Replace only the value bytes; retain comments, CRLF, resource limits and every other key.
m = matches[0]
pathlib.Path(sys.argv[2]).write_bytes(raw[:m.start(1)] + sys.argv[1].encode() + raw[m.end(1):])
print(old)
PY
  )
  previous_id=$(docker image inspect --format '{{.Id}}' "$previous")
  [[ -n $previous_id ]] || return 1
  registry=${image%%/*}
  mkdir "$stage/docker"
  export DOCKER_CONFIG="$stage/docker"
  # Empty credential/config files and clean environment force the EC2 instance role.
  env -i PATH="$PATH" HOME=/root AWS_CONFIG_FILE=/dev/null AWS_SHARED_CREDENTIALS_FILE=/dev/null \
    AWS_PAGER='' AWS_EC2_METADATA_DISABLED=false \
    aws --region "$region" ecr get-login-password |
    docker login --username AWS --password-stdin "$registry" >/dev/null
  timeout 180 docker pull "$image" >/dev/null
  [[ $(docker image inspect --format '{{.Architecture}}' "$image") == arm64 ]] || {
    echo 'Expected arm64 image.' >&2; return 1;
  }
  target_id=$(docker image inspect --format '{{.Id}}' "$image")
  [[ -n $target_id ]] || return 1
  # Fail closed on active work; never force a restart or auto-resume a failed drain.
  drain_and_wait false 600
  printf '%s\n' "$previous" > "$stage/previous-image"
  mv -f "$stage/previous-image" .previous-image
  # Preserve original mode/ownership, atomically switch only IMAGE.
  cp -p compose.env "$stage/install.env"
  cat "$stage/new.env" > "$stage/install.env"
  switched=true
  mv -f "$stage/install.env" compose.env
  "${compose[@]}" --profile tls config --quiet
  systemctl restart proofops.service
  wait_healthy "$target_id"
  resume_attempted=true
  hosted_control resume
  switched=false
  echo "DEPLOYED image=$image api=healthy worker=healthy ready=ok resumed=true"
}

if [[ ${BASH_SOURCE[0]} == "$0" ]]; then
  apply=false
  case ${1:-} in
    --apply) apply=true; shift;;
    --dry-run) shift;;
  esac
  [[ $# == 2 ]] || { echo 'Usage: deploy-from-ecr.sh [--apply|--dry-run] ECR_IMAGE REGION' >&2; exit 2; }
  validate_target "$1" "$2"
  if ! "$apply"; then
    echo "DRY RUN: $1; lock -> instance-role login/pull -> drain/wait-idle -> IMAGE-only switch -> restart -> API/worker health/ready -> resume; rollback on failure. No AWS/Docker calls."
    exit 0
  fi
  [[ $EUID == 0 ]] || { echo 'Run --apply as root on the EC2 host.' >&2; exit 2; }
  deploy_from_ecr "$1" "$2" /srv/proofops
fi
