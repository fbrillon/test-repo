#!/usr/bin/env bash
# add-user.sh — Onboard a new user to the Gmail triage agent.
#
# Usage:
#   ./add-user.sh <user-id> <lambda-arn> <scheduler-role-arn> [schedule-expression]
#
# Examples:
#   ./add-user.sh alice  arn:aws:lambda:...  arn:aws:iam:...
#   ./add-user.sh bob    arn:aws:lambda:...  arn:aws:iam:...  "rate(30 minutes)"
#   ./add-user.sh carol  arn:aws:lambda:...  arn:aws:iam:...  "cron(0 8 * * ? *)"
#
# The lambda-arn and scheduler-role-arn are printed by: sam deploy

set -euo pipefail

USER_ID="${1:?Usage: $0 <user-id> <lambda-arn> <scheduler-role-arn> [schedule]}"
LAMBDA_ARN="${2:?Missing lambda-arn}"
SCHEDULER_ROLE_ARN="${3:?Missing scheduler-role-arn}"
SCHEDULE="${4:-rate(15 minutes)}"

# Step 1 — authenticate Gmail locally and upload token to Secrets Manager
echo "==> Authenticating Gmail for user: $USER_ID"
python agent.py --user "$USER_ID" --upload-token

# Step 2 — create an EventBridge Scheduler schedule for this user
echo "==> Creating EventBridge schedule: gmail-agent-$USER_ID ($SCHEDULE)"
aws scheduler create-schedule \
  --name "gmail-agent-$USER_ID" \
  --schedule-expression "$SCHEDULE" \
  --flexible-time-window '{"Mode":"FLEXIBLE","MaximumWindowInMinutes":5}' \
  --target "{
    \"Arn\": \"$LAMBDA_ARN\",
    \"RoleArn\": \"$SCHEDULER_ROLE_ARN\",
    \"Input\": \"{\\\"user_id\\\": \\\"$USER_ID\\\"}\"
  }"

echo ""
echo "Done. User '$USER_ID' will be triaged on schedule: $SCHEDULE"
echo "To remove: aws scheduler delete-schedule --name gmail-agent-$USER_ID"
