#!/usr/bin/env bash
# EC2 entry points retain the private SSH/runtime contract; no provider env sourcing.
set -euo pipefail
set +x
umask 077
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export APPLY=false
if [[ ${1:-} == --apply ]]; then APPLY=true; shift; fi
[[ $# == 0 ]] || { echo 'Usage: script [--apply]' >&2; exit 2; }
export REGION=${REGION:-ap-southeast-2} PROFILE=${PROFILE:-proofops-deploy}
export ACCOUNT_ID=${ACCOUNT_ID:-753036488189} NAME=${NAME:-proofops-r108}
export ARCH=${ARCH:-arm64} IMAGE=${IMAGE:-proofops-r108-public:ec1-arm64}
export STATE_DIR=${STATE_DIR:-"$HERE/.state"}
[[ $REGION == ap-southeast-2 && $ACCOUNT_ID == 753036488189 && $ARCH == arm64 ]] || { echo 'EC1 requires its approved account, Sydney (project region) and arm64.' >&2; exit 2; }
[[ $NAME =~ ^proofops-r108[-a-zA-Z0-9]*$ ]] || exit 2
export AWS_PAGER='' AWS_EC2_METADATA_DISABLED=true
AWS=(aws --profile "$PROFILE" --region "$REGION" --no-cli-pager)
preview() { printf 'DRY RUN:'; printf ' %q' "$@"; printf '\n'; }
aws_run() { if "$APPLY"; then "${AWS[@]}" "$@"; else preview "${AWS[@]}" "$@"; fi; }
need() { [[ -n ${!1:-} ]] || { echo "Set $1 (see RUNBOOK)." >&2; exit 2; }; }
