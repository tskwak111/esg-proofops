#!/usr/bin/env bash
# Source only from this directory; never source provider files or runtime.env.
set -euo pipefail
set +x
umask 077
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APPLY=false
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
    *) echo 'Usage: script [--apply]; deploy.sh also accepts [--force-restart] [--drain-timeout SECONDS]' >&2; exit 2 ;;
  esac
done
REGION=${REGION:-ap-northeast-2}
PROFILE=${PROFILE:-proofops-deploy}
NAME=${NAME:-proofops-r108}
STATE_DIR=${STATE_DIR:-"$HERE/.state"}
IMAGE=${IMAGE:-proofops-r108-public:p2}
ARCH=${ARCH:-amd64}
[[ $REGION == ap-northeast-2 ]] || { echo 'DEC-19 requires Seoul.' >&2; exit 2; }
[[ $NAME =~ ^proofops-r108[-a-zA-Z0-9]*$ ]] || { echo 'Invalid resource name.' >&2; exit 2; }
[[ $ARCH == amd64 || $ARCH == arm64 ]] || exit 2
mkdir -p "$STATE_DIR"
export AWS_PAGER='' AWS_EC2_METADATA_DISABLED=true
AWS=(aws --profile "$PROFILE" --region "$REGION" --no-cli-pager)
preview() { printf 'DRY RUN:'; printf ' %q' "$@"; printf '\n'; }
aws_run() { if "$APPLY"; then "${AWS[@]}" "$@"; else preview "${AWS[@]}" "$@"; fi; }
need() { [[ -n ${!1:-} ]] || { echo "Set $1 (see RUNBOOK)." >&2; exit 2; }; }
wait_operations() {
  local id status attempt
  for id in $(jq -r '(.operations // [.operation])[]? | select(. != null) | .id' "$1"); do
    for ((attempt=0; attempt<90; attempt++)); do
      status=$("${AWS[@]}" lightsail get-operation --operation-id "$id" --query operation.status --output text)
      case "$status" in Succeeded|Completed) break;; Failed) echo "Lightsail operation failed: $id" >&2; return 1;; esac
      sleep 2
    done
    [[ $status == Succeeded || $status == Completed ]] || { echo 'Operation timeout; inspect state, do not recreate.' >&2; return 1; }
  done
}
mutate() { "${AWS[@]}" "$@" > "$STATE_DIR/operation.json"; wait_operations "$STATE_DIR/operation.json"; }
