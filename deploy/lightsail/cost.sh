#!/usr/bin/env bash
# shellcheck source=common.sh
source "$(dirname "$0")/common.sh"
aws_run budgets describe-budget --account-id "${ACCOUNT_ID:-<verified-account-id>}" --budget-name proofops-r108-monthly-20
aws_run lightsail get-instance --instance-name "$NAME"
echo 'Budget updates are delayed. Provider costs/unknown reservations must also be checked in the hosted independent ledger.'
