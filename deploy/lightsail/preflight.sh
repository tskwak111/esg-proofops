#!/usr/bin/env bash
# shellcheck source=common.sh
source "$(dirname "$0")/common.sh"
if ! "$APPLY"; then
  for action in 'sts get-caller-identity' 'lightsail get-regions --include-availability-zones' 'lightsail get-blueprints' 'lightsail get-bundles' 'lightsail get-instances' 'lightsail get-static-ips' 'lightsail get-key-pairs'; do
    # These fixed words are CLI arguments, not operator input.
    read -r -a parts <<< "$action"
    aws_run "${parts[@]}"
  done
  echo 'Apply requires ACCOUNT_ID, confirmed VCPU_QUOTA and STATIC_IP_QUOTA; no cloud call was made.'
  exit
fi
need ACCOUNT_ID; need VCPU_QUOTA; need STATIC_IP_QUOTA
[[ $ACCOUNT_ID =~ ^[0-9]{12}$ && $VCPU_QUOTA =~ ^[0-9]+$ && $STATIC_IP_QUOTA =~ ^[0-9]+$ ]] || exit 2
"${AWS[@]}" sts get-caller-identity > "$STATE_DIR/identity.json"
[[ $(jq -r .Account "$STATE_DIR/identity.json") == "$ACCOUNT_ID" ]] || { echo 'Wrong AWS account.' >&2; exit 2; }
for pair in 'regions get-regions' 'blueprints get-blueprints' 'bundles get-bundles' 'instances get-instances' 'ips get-static-ips'; do
  read -r label action <<< "$pair"
  if [[ $label == regions ]]; then
    "${AWS[@]}" lightsail "$action" --include-availability-zones > "$STATE_DIR/$label.json"
  else
    "${AWS[@]}" lightsail "$action" > "$STATE_DIR/$label.json"
  fi
done
python3 "$HERE/select-catalog.py" "$STATE_DIR" "$ARCH" "${BLUEPRINT_ID:-ubuntu_24_04}" "$VCPU_QUOTA" "$STATIC_IP_QUOTA" "${MAX_MONTHLY_USD:-24}"
echo 'Preflight saved verified account, Seoul AZ, active Ubuntu LTS and queried 4GB IPv4 bundle.'
