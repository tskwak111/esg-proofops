#!/usr/bin/env bash
# Local image build/export, preview by default. No registry/AWS access.
set -euo pipefail
set +x
umask 077
HERE="$(cd "$(dirname "$0")" && pwd)"
APPLY=false
BUILD=false
ARCH=${ARCH:-arm64}
archive=''
while [[ $# -gt 0 ]]; do
  case $1 in
    --apply) APPLY=true; shift;;
    --build) BUILD=true; shift;;
    --arch) [[ $# -ge 2 ]] || exit 2; ARCH=$2; shift 2;;
    --*) echo 'Usage: pack.sh [--apply] [--build] [--arch arm64] NEW_ARCHIVE.tar' >&2; exit 2;;
    *) [[ -z $archive ]] || exit 2; archive=$1; shift;;
  esac
done
[[ $ARCH == arm64 ]] || { echo 'EC2 pack requires linux/arm64.' >&2; exit 2; }
export ARCH IMAGE=${IMAGE:-proofops-r108-public:ec1-arm64}
if ! "$APPLY"; then
  echo 'DRY RUN: local Docker build/export linux/arm64 with SHA256 manifest; use --apply [--build] NEW_ARCHIVE.tar. No Docker/registry/AWS calls.'
  exit
fi
[[ -n $archive && $archive != -* && ! -e $archive && ! -e $archive.json ]] || { echo 'Use a new archive and manifest path.' >&2; exit 2; }
if "$BUILD"; then exec "$HERE/../lightsail/pack.sh" --build "$archive"; fi
exec "$HERE/../lightsail/pack.sh" "$archive"
