#!/usr/bin/env bash
# shellcheck source=common.sh
source "$(dirname "$0")/common.sh"
if "$APPLY"; then exec "$HERE/../lightsail/smoke.sh" --apply; fi
exec "$HERE/../lightsail/smoke.sh"
