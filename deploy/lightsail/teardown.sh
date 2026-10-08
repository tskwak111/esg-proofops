#!/usr/bin/env bash
# shellcheck source=common.sh
source "$(dirname "$0")/common.sh"
if ! "$APPLY"; then
  aws_run lightsail get-instance-snapshots
  aws_run lightsail delete-instance --instance-name "$NAME" --force-delete-add-ons
  aws_run lightsail get-instance --instance-name "$NAME"
  aws_run lightsail delete-instance-snapshot --instance-snapshot-name '<exact-source-instance-matching-snapshot>'
  aws_run lightsail detach-static-ip --static-ip-name "$NAME"
  aws_run lightsail release-static-ip --static-ip-name "$NAME"
  echo 'Apply requires CONFIRM_DELETE=NAME, LEDGER_ARCHIVED=true and matching local ownership/account. No resources deleted.'
  exit
fi
need ACCOUNT_ID; need CONFIRM_DELETE; need LEDGER_ARCHIVED
[[ $CONFIRM_DELETE == "$NAME" && $LEDGER_ARCHIVED == true ]] || { echo 'Archive current independent ledger under operator custody before deletion.' >&2; exit 2; }
[[ -f $STATE_DIR/owned.txt && $(cat "$STATE_DIR/owned.txt") == "$ACCOUNT_ID $REGION $NAME" ]] || { echo 'Missing/mismatched ownership state; inspect resources manually.' >&2; exit 2; }
[[ $("${AWS[@]}" sts get-caller-identity --query Account --output text) == "$ACCOUNT_ID" ]] || exit 2
"${AWS[@]}" lightsail get-instances > "$STATE_DIR/delete-instances.json"
"${AWS[@]}" lightsail get-static-ips > "$STATE_DIR/delete-ips.json"
"${AWS[@]}" lightsail get-instance-snapshots > "$STATE_DIR/delete-snapshots.json"
attached=$(jq -r --arg n "$NAME" '.staticIps[]|select(.name==$n)|.attachedTo // ""' "$STATE_DIR/delete-ips.json")
[[ -z $attached || $attached == "$NAME" ]] || { echo 'IP attached to another instance; stop.' >&2; exit 2; }
# Re-runnable: list APIs distinguish absence from access/network errors; failures stop.
if [[ $(jq --arg n "$NAME" '[.instances[]|select(.name==$n)]|length' "$STATE_DIR/delete-instances.json") != 0 ]]; then
  [[ $(jq -r --arg n "$NAME" '.instances[]|select(.name==$n)|.tags[]|select(.key=="Project")|.value' "$STATE_DIR/delete-instances.json") == proofops-r108 ]] || { echo 'Ownership tag mismatch.' >&2; exit 2; }
  if [[ $(jq --arg n "$NAME" '[.instances[]|select(.name==$n)|.addOns[]?|select(.name=="AutoSnapshot" and .status=="Enabled")]|length' "$STATE_DIR/delete-instances.json") != 0 ]]; then
    "${AWS[@]}" lightsail get-auto-snapshots --resource-name "$NAME" > "$STATE_DIR/auto-snapshots.json"
    while IFS= read -r date; do
      mutate lightsail delete-auto-snapshot --resource-name "$NAME" --date "$date"
    done < <(jq -r '.autoSnapshots[]?.date' "$STATE_DIR/auto-snapshots.json")
  fi
  mutate lightsail delete-instance --instance-name "$NAME" --force-delete-add-ons
fi
while IFS= read -r snapshot; do
  [[ -n $snapshot ]] || continue
  mutate lightsail delete-instance-snapshot --instance-snapshot-name "$snapshot"
done < <(jq -r --arg n "$NAME" '.instanceSnapshots[]|select(.fromInstanceName==$n)|.name' "$STATE_DIR/delete-snapshots.json")
if [[ $(jq --arg n "$NAME" '[.staticIps[]|select(.name==$n)]|length' "$STATE_DIR/delete-ips.json") != 0 ]]; then
  attached=$(jq -r --arg n "$NAME" '.staticIps[]|select(.name==$n)|.attachedTo // ""' "$STATE_DIR/delete-ips.json")
  [[ -z $attached || $attached == "$NAME" ]] || { echo 'IP attached to another instance; stop.' >&2; exit 2; }
  # Instance deletion detaches its IP. Re-read before conditional detach.
  "${AWS[@]}" lightsail get-static-ip --static-ip-name "$NAME" > "$STATE_DIR/ip-after-delete.json"
  if [[ $(jq -r '.staticIp.isAttached' "$STATE_DIR/ip-after-delete.json") == true ]]; then mutate lightsail detach-static-ip --static-ip-name "$NAME"; fi
  mutate lightsail release-static-ip --static-ip-name "$NAME"
fi
if [[ -f $STATE_DIR/key-imported ]]; then
  "${AWS[@]}" lightsail get-key-pairs > "$STATE_DIR/delete-keys.json"
  if [[ $(jq --arg n "$NAME" '[.keyPairs[]|select(.name==$n)]|length' "$STATE_DIR/delete-keys.json") != 0 ]]; then
    mutate lightsail delete-key-pair --key-pair-name "$NAME"
  fi
fi
"${AWS[@]}" lightsail get-instances > "$STATE_DIR/final-instances.json"
"${AWS[@]}" lightsail get-static-ips > "$STATE_DIR/final-ips.json"
"${AWS[@]}" lightsail get-instance-snapshots > "$STATE_DIR/final-snapshots.json"
jq -e --arg n "$NAME" '[.instances[]|select(.name==$n)]|length==0' "$STATE_DIR/final-instances.json" >/dev/null
jq -e --arg n "$NAME" '[.staticIps[]|select(.name==$n)]|length==0' "$STATE_DIR/final-ips.json" >/dev/null
jq -e --arg n "$NAME" '[.instanceSnapshots[]|select(.fromInstanceName==$n)]|length==0' "$STATE_DIR/final-snapshots.json" >/dev/null
echo 'Exact owned VM/IP/snapshots/key removed and absence verified; billing alert retained. Keep archived ledger and deletion evidence private.'
