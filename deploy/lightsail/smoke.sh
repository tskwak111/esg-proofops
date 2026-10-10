#!/usr/bin/env bash
# No AWS calls. Explicit --apply permits HTTP against the specified base.
# shellcheck source=common.sh
source "$(dirname "$0")/common.sh"
if ! "$APPLY"; then echo 'DRY RUN: smoke.py --base https://production-domain/hosted-api --origin https://production-domain --invite-file PRIVATE_0600_FILE --foreign-invite-file PRIVATE_FOREIGN_0600_FILE --expect blocked (upload -> scope-plan POST/GET + If-Match guard -> run with unchanged scope -> held result -> tenant 404 -> purge; requires LIVE_DISABLED)'; exit; fi
need SMOKE_BASE; need APP_ORIGIN; need INVITE_FILE; need FOREIGN_INVITE_FILE
python3 "$HERE/smoke.py" --base "$SMOKE_BASE" --origin "$APP_ORIGIN" --invite-file "$INVITE_FILE" --foreign-invite-file "$FOREIGN_INVITE_FILE" --expect blocked
