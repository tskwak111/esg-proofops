#!/usr/bin/env bash
# Local image export only. --build performs a local Docker build, never AWS.
set -euo pipefail
umask 077
HERE="$(cd "$(dirname "$0")" && pwd)"
BUILD=false
if [[ ${1:-} == --build ]]; then BUILD=true; shift; fi
[[ $# == 1 && ! -e $1 ]] || { echo 'Usage: pack.sh [--build] NEW_ARCHIVE.tar' >&2; exit 2; }
IMAGE=${IMAGE:-proofops-r108-public:p2}
ARCH=${ARCH:-amd64}
[[ $ARCH == arm64 || $ARCH == amd64 ]] || exit 2
if "$BUILD"; then docker build --platform "linux/$ARCH" -f "$HERE/../public/Dockerfile" -t "$IMAGE" "$HERE/../.."; fi
[[ $(docker image inspect --format '{{.Os}}/{{.Architecture}}' "$IMAGE") == "linux/$ARCH" ]] || { echo "Image architecture mismatch: rebuild with ARCH=$ARCH pack.sh --build." >&2; exit 2; }
docker save --output "$1" "$IMAGE"
chmod 600 "$1"
python3 - "$1" "$IMAGE" "$ARCH" <<'CHECK'
import hashlib, json, subprocess, sys
from pathlib import Path
archive=Path(sys.argv[1])
h=hashlib.file_digest(archive.open('rb'), 'sha256').hexdigest()
image_id=subprocess.check_output(['docker','image','inspect','--format','{{.Id}}',sys.argv[2]],text=True).strip()
archive.with_suffix(archive.suffix+'.json').write_text(json.dumps(dict(image=sys.argv[2], arch=sys.argv[3], image_id=image_id, archive_sha256=h),indent=2)+'\n')
print('Exported image archive and SHA256 manifest; no registry push.')
CHECK
