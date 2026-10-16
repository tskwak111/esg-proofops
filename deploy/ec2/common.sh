#!/usr/bin/env bash
# EC2 entry points retain the private SSH/runtime contract; no provider env sourcing.
set -euo pipefail
set +x
umask 077
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export APPLY=false
FORCE_RESTART=false
DRAIN_TIMEOUT=600
while [[ $# -gt 0 ]]; do
  case "$1" in
    --apply) APPLY=true; shift ;;
    --force-restart)
      [[ ${0##*/} == deploy.sh ]] || { echo 'Restart options are for deploy.sh only.' >&2; exit 2; }
      FORCE_RESTART=true; shift ;;
    --drain-timeout)
      [[ ${0##*/} == deploy.sh && ${2:-} =~ ^[0-9]{1,5}$ ]] || { echo 'Invalid drain timeout.' >&2; exit 2; }
      DRAIN_TIMEOUT=$2; shift 2 ;;
    --worker-cpus|--worker-memory)
      [[ ${0##*/} == deploy.sh && -n ${2:-} ]] || { echo 'Worker options are for deploy.sh only and require a value.' >&2; exit 2; }
      case "$1" in --worker-cpus) WORKER_CPUS=$2;; --worker-memory) WORKER_MEMORY=$2;; esac
      shift 2 ;;
    *) echo 'Usage: script [--apply]; deploy.sh also accepts [--force-restart] [--drain-timeout SECONDS] [--worker-cpus CPUS] [--worker-memory MEMORY]' >&2; exit 2 ;;
  esac
done
export REGION=${REGION:-ap-southeast-2} PROFILE=${PROFILE:-proofops-deploy}
export ACCOUNT_ID=${ACCOUNT_ID:-000000000000} NAME=${NAME:-proofops-r108}
export ARCH=${ARCH:-arm64} IMAGE=${IMAGE:-proofops-r108-public:ec1-arm64}
export STATE_DIR=${STATE_DIR:-"$HERE/.state"}
[[ $REGION == ap-southeast-2 && $ACCOUNT_ID == 000000000000 && $ARCH == arm64 ]] || { echo 'EC1 requires its approved account, Sydney (project region) and arm64.' >&2; exit 2; }
[[ $NAME =~ ^proofops-r108[-a-zA-Z0-9]*$ ]] || exit 2
export AWS_PAGER='' AWS_EC2_METADATA_DISABLED=true
AWS=(aws --profile "$PROFILE" --region "$REGION" --no-cli-pager)
preview() { printf 'DRY RUN:'; printf ' %q' "$@"; printf '\n'; }
aws_run() { if "$APPLY"; then "${AWS[@]}" "$@"; else preview "${AWS[@]}" "$@"; fi; }
need() { [[ -n ${!1:-} ]] || { echo "Set $1 (see RUNBOOK)." >&2; exit 2; }; }
write_compose_env() {
  printf 'IMAGE=%s\nCADDY_IMAGE=caddy:2.10.2-alpine\nAPI_HOST=%s.sslip.io\nACME_EMAIL=%s\nLOCAL_PORT=8000\nWORKER_CPUS=%s\nWORKER_MEMORY=%s\n' \
    "$IMAGE" "$STATIC_IP" "$ACME_EMAIL" "$WORKER_CPUS" "$WORKER_MEMORY" > "$1"
}
