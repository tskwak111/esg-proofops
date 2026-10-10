#!/usr/bin/env bash
# shellcheck source=common.sh
source "$(dirname "$0")/common.sh"
if "$APPLY"; then exec python3 "$HERE/ec2.py" teardown --apply; fi
exec python3 "$HERE/ec2.py" teardown
