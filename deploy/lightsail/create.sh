#!/usr/bin/env bash
# shellcheck source=common.sh
source "$(dirname "$0")/common.sh"
if ! "$APPLY"; then
  "$HERE/preflight.sh"
  aws_run lightsail import-key-pair --key-pair-name "$NAME" --public-key-base64 'file://<base64-encoded-RSA-public-key>'
  aws_run lightsail create-instances --instance-names "$NAME" --availability-zone '<selected-Seoul-AZ>' --blueprint-id ubuntu_24_04 --bundle-id '<queried-4GB-IPv4-bundle>' --ip-address-type ipv4 --key-pair-name "$NAME" --user-data "file://$HERE/cloud-init.sh" --tags key=Project,value=proofops-r108
  aws_run lightsail put-instance-public-ports --instance-name "$NAME" --port-infos 'file://<22-my-IP-only+80+443.json>'
  aws_run lightsail allocate-static-ip --static-ip-name "$NAME"
  aws_run lightsail attach-static-ip --static-ip-name "$NAME" --instance-name "$NAME"
  exit
fi
need SSH_PUBLIC_KEY; need SSH_CIDR
python3 - "$SSH_CIDR" <<'CHECK'
import ipaddress, sys
n=ipaddress.ip_network(sys.argv[1], strict=True)
assert n.version == 4 and n.prefixlen == 32, 'SSH requires your IPv4 /32'
CHECK
[[ -f $SSH_PUBLIC_KEY ]] || exit 2
"$HERE/preflight.sh" --apply
[[ $(jq --arg n "$NAME" '[.instances[]|select(.name==$n)]|length' "$STATE_DIR/instances.json") == 0 ]] || { echo 'Instance already exists; use deploy.sh or teardown, never replace.' >&2; exit 2; }
[[ $(jq --arg n "$NAME" '[.staticIps[]|select(.name==$n)]|length' "$STATE_DIR/ips.json") == 0 ]] || { echo 'Static IP name already exists.' >&2; exit 2; }
# Refuse name collisions. Only a key imported by this kit may be deleted in teardown.
"${AWS[@]}" lightsail get-key-pairs > "$STATE_DIR/keys.json"
[[ $(jq --arg n "$NAME" '[.keyPairs[]|select(.name==$n)]|length' "$STATE_DIR/keys.json") == 0 ]] || { echo 'Key name already exists.' >&2; exit 2; }
printf '%s\n' "$ACCOUNT_ID $REGION $NAME" > "$STATE_DIR/owned.txt"
python3 - "$SSH_PUBLIC_KEY" "$STATE_DIR/public-key.b64" <<'CHECK'
import base64,sys
from pathlib import Path
key=Path(sys.argv[1]).read_bytes().strip()
assert key.startswith(b'ssh-rsa '), 'Lightsail import requires an ssh-rsa public key'
Path(sys.argv[2]).write_text(base64.b64encode(key).decode())
CHECK
touch "$STATE_DIR/key-imported"
mutate lightsail import-key-pair --key-pair-name "$NAME" --public-key-base64 "file://$STATE_DIR/public-key.b64"
jq -n --arg cidr "$SSH_CIDR" '[{fromPort:22,toPort:22,protocol:"tcp",cidrs:[$cidr],ipv6Cidrs:[]},{fromPort:80,toPort:80,protocol:"tcp",cidrs:["0.0.0.0/0"],ipv6Cidrs:[]},{fromPort:443,toPort:443,protocol:"tcp",cidrs:["0.0.0.0/0"],ipv6Cidrs:[]}]' > "$STATE_DIR/ports.json"
sed "s/__SSH_CIDR__/${SSH_CIDR//\//\\/}/" "$HERE/cloud-init.sh" > "$STATE_DIR/cloud-init.sh"
mutate lightsail create-instances --instance-names "$NAME" --availability-zone "$(jq -r .az "$STATE_DIR/selection.json")" --blueprint-id "$(jq -r .blueprint "$STATE_DIR/selection.json")" --bundle-id "$(jq -r .bundle "$STATE_DIR/selection.json")" --ip-address-type ipv4 --key-pair-name "$NAME" --user-data "file://$STATE_DIR/cloud-init.sh" --tags key=Project,value=proofops-r108
mutate lightsail put-instance-public-ports --instance-name "$NAME" --port-infos "file://$STATE_DIR/ports.json"
mutate lightsail allocate-static-ip --static-ip-name "$NAME"
mutate lightsail attach-static-ip --static-ip-name "$NAME" --instance-name "$NAME"
"${AWS[@]}" lightsail get-static-ip --static-ip-name "$NAME" > "$STATE_DIR/static-ip.json"
echo "STATIC_IP=$(jq -r .staticIp.ipAddress "$STATE_DIR/static-ip.json")"
echo 'Wait for cloud-init, then deploy.sh; services remain closed until runtime config is installed.'
