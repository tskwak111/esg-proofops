#!/usr/bin/env bash
# shellcheck source=common.sh
source "$(dirname "$0")/common.sh"
if ! "$APPLY"; then
  aws_run budgets create-budget --account-id '<verified-account-id>' --cli-input-json 'file://<monthly-USD20-email-alert.json>'
  echo 'Budget is an alert, not a spending cutoff; provider caps remain separate.'
  exit
fi
need ACCOUNT_ID; need ALERT_EMAIL
[[ $ACCOUNT_ID =~ ^[0-9]{12}$ ]] || exit 2
[[ $("${AWS[@]}" sts get-caller-identity --query Account --output text) == "$ACCOUNT_ID" ]] || exit 2
python3 - "$ACCOUNT_ID" "$ALERT_EMAIL" "$STATE_DIR/budget.json" <<'CHECK'
import json,re,sys
from pathlib import Path
account,email,out=sys.argv[1:]
assert re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',email), 'Valid email required'
alerts=[dict(Notification=dict(NotificationType=kind,ComparisonOperator='GREATER_THAN',Threshold=threshold,ThresholdType='PERCENTAGE'),Subscribers=[dict(SubscriptionType='EMAIL',Address=email)]) for kind,threshold in [('ACTUAL',80),('ACTUAL',100),('FORECASTED',100)]]
Path(out).write_text(json.dumps(dict(AccountId=account,Budget=dict(BudgetName='proofops-r108-monthly-20',BudgetLimit=dict(Amount='20',Unit='USD'),TimeUnit='MONTHLY',BudgetType='COST'),NotificationsWithSubscribers=alerts),indent=2)+'\n')
CHECK
"${AWS[@]}" budgets create-budget --cli-input-json "file://$STATE_DIR/budget.json"
echo 'Monthly account-wide USD20 email alerts created. Existing-name errors are not ignored; inspect/update existing budget.'
