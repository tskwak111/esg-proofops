#!/usr/bin/env bash
# shellcheck source=common.sh
source "$(dirname "$0")/common.sh"
if "$APPLY"; then
  python3 "$HERE/ec2.py" target
  [[ -f ${SSH_KEY:-} ]] || { echo 'Set SSH_KEY to a local private key.' >&2; exit 2; }
  actual=$(ssh -i "$SSH_KEY" -o BatchMode=yes -o StrictHostKeyChecking=yes "ubuntu@$STATIC_IP" uname -m)
  [[ $actual == aarch64 ]] || { echo 'EC2 key target must be aarch64.' >&2; exit 2; }
fi
if "$APPLY"; then exec "$HERE/../lightsail/keys.sh" --apply; fi
exec "$HERE/../lightsail/keys.sh"
