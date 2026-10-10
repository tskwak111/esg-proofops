#!/usr/bin/env bash
# EC2 wrappers share the existing private SSH/runtime path; no provider env sourcing.
set -euo pipefail
set +x
umask 077
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export APPLY=false
if [[ ${1:-} == --apply ]]; then APPLY=true; shift; fi
[[ $# == 0 ]] || { echo 'Usage: script [--apply]' >&2; exit 2; }
export REGION=${REGION:-ap-northeast-2} PROFILE=${PROFILE:-proofops-deploy}
export ACCOUNT_ID=${ACCOUNT_ID:-753036488189} NAME=${NAME:-proofops-r108}
export ARCH=${ARCH:-arm64} IMAGE=${IMAGE:-proofops-r108-public:ec1-arm64}
export STATE_DIR=${STATE_DIR:-"$HERE/.state"}
[[ $REGION == ap-northeast-2 && $ACCOUNT_ID == 753036488189 && $ARCH == arm64 ]] || { echo 'EC1 requires its approved account, Seoul and arm64.' >&2; exit 2; }
[[ $NAME =~ ^proofops-r108[-a-zA-Z0-9]*$ ]] || exit 2
export AWS_PAGER='' AWS_EC2_METADATA_DISABLED=true
