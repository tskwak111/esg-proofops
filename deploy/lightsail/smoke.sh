#!/usr/bin/env bash
# No AWS calls. Explicit --apply permits HTTP against the specified base.
# shellcheck source=common.sh
source "$(dirname "$0")/common.sh"
if ! "$APPLY"; then echo 'DRY RUN: smoke.py --base https://production-domain/hosted-api --origin https://production-domain --invite-file PRIVATE_0600_FILE --expect blocked'; exit; fi
need SMOKE_BASE; need APP_ORIGIN; need INVITE_FILE
python3 "$HERE/smoke.py" --base "$SMOKE_BASE" --origin "$APP_ORIGIN" --invite-file "$INVITE_FILE" --expect blocked
