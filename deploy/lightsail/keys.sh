#!/usr/bin/env bash
# shellcheck source=common.sh
source "$(dirname "$0")/common.sh"
if ! "$APPLY"; then echo 'DRY RUN: scp local provider files into private staging; install UID10001/GID10001 mode0600 /srv/proofops/private/{openrouter.env,upstage.env,live.json}; no key values printed, no live enable.'; exit; fi
need STATIC_IP; need SSH_KEY; need OPENROUTER_KEY_FILE; need UPSTAGE_KEY_FILE; need LIVE_CONFIG_FILE
[[ $STATIC_IP =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]] || exit 2
python3 - "$OPENROUTER_KEY_FILE" "$UPSTAGE_KEY_FILE" "$LIVE_CONFIG_FILE" <<'CHECK'
import json,stat,sys
from pathlib import Path
from datetime import date
for name in sys.argv[1:]:
    p=Path(name)
    assert p.is_file() and not p.is_symlink() and stat.S_IMODE(p.stat().st_mode)==0o600, 'Private regular 0600 files required'
for name,var in zip(sys.argv[1:3],('OPENROUTER_API_KEY','UPSTAGE_API_KEY')):
    lines=Path(name).read_text().splitlines()
    assert len(lines)==1 and lines[0].startswith(var+'=') and lines[0].split('=',1)[1].strip(), 'Use one KEY=value line per file'
c=json.loads(Path(sys.argv[3]).read_text())
assert c['openrouter_key_file']=='/run/private/openrouter.env' and c['upstage_key_file']=='/run/private/upstage.env'
assert type(c['enabled']) is bool and type(c['report_year']) is int and 1900<=c['report_year']<=2100
assert date.fromisoformat(c['period_start'])<=date.fromisoformat(c['period_end'])
CHECK
SSH=(ssh -i "$SSH_KEY" -o BatchMode=yes -o StrictHostKeyChecking=yes "ubuntu@$STATIC_IP")
SCP=(scp -q -i "$SSH_KEY" -o BatchMode=yes -o StrictHostKeyChecking=yes)
remote="/home/ubuntu/proofops-keys-$$"
"${SSH[@]}" "umask 077; mkdir '$remote'"
cleanup() { "${SSH[@]}" "rm -rf -- '$remote'" >/dev/null 2>&1 || true; }
trap cleanup EXIT
"${SCP[@]}" "$OPENROUTER_KEY_FILE" "ubuntu@$STATIC_IP:$remote/openrouter.env"
"${SCP[@]}" "$UPSTAGE_KEY_FILE" "ubuntu@$STATIC_IP:$remote/upstage.env"
"${SCP[@]}" "$LIVE_CONFIG_FILE" "ubuntu@$STATIC_IP:$remote/live.json"
"${SSH[@]}" "sudo install -d -o 10001 -g 10001 -m 700 /srv/proofops/private && sudo install -o 10001 -g 10001 -m 600 '$remote/openrouter.env' '$remote/upstage.env' '$remote/live.json' /srv/proofops/private/"
echo 'Key files installed privately; LIVE_DISABLED remains true. No provider request was made by this script.'
