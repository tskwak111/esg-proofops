#!/usr/bin/env bash
# shellcheck source=common.sh
source "$(dirname "$0")/common.sh"
if "$APPLY"; then python3 "$HERE/ec2.py" target; fi
if "$APPLY"; then exec "$HERE/../lightsail/deploy.sh" --apply; fi
exec "$HERE/../lightsail/deploy.sh"
