# Gmail Email Labeling Agent

Autonomous agent that reads unread Gmail threads and applies triage labels using Claude's reasoning to classify emails by urgency and required action.

## Purpose

Inbox zero strategy: every unread email gets classified so you know exactly what to do next without re-reading each one.

## Label System

Uses existing Gmail labels:

| Label | Gmail ID | Meaning |
|---|---|---|
| `Act_Now` | Label_31 | Needs a reply or concrete action today — someone is waiting on you |
| `Next_Moves` | Label_32 | Needs action but not urgent — can wait a few days |
| `Track_It` | Label_34 | Receipt, confirmation, or awaiting a reply — monitor only |
| `Stay_Informed` | Label_28 | Informational, worth reading, no action required |
| `Skip_It` | Label_33 | Newsletter, promo, automated notification — safe to archive |

## Setup

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Google OAuth credentials

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a project → Enable Gmail API
3. Create OAuth 2.0 credentials (Desktop app)
4. Download `credentials.json` and place it in the project root

### 3. Anthropic API key

```bash
export ANTHROPIC_API_KEY=sk-ant-...
```

Or create a `.env` file:

```
ANTHROPIC_API_KEY=sk-ant-...
```

## Usage

```bash
python agent.py
```

On first run, a browser window opens for Google OAuth. The token is saved to `token.pickle` for subsequent runs.

### Options

```bash
python agent.py --max-threads 50   # Process up to 50 threads (default: 30)
python agent.py --dry-run          # Classify without applying labels
python agent.py --verbose          # Show Claude's reasoning for each email
```

## Architecture

```
agent.py
├── Gmail client (google-auth + googleapiclient)
│   ├── search_unread_threads()   – paginated fetch of unread threads
│   ├── get_thread()              – full thread content with decoded bodies
│   └── apply_label()            – adds triage label, marks thread read
└── Agentic loop (Anthropic SDK)
    ├── System prompt with label definitions
    ├── Tool definitions exposed to Claude
    └── Tool dispatch → Gmail client calls
```

The agent runs a standard tool-use loop: Claude decides which thread to fetch next, reads it, then applies a label. It iterates until all unread threads are processed.

## Deploying to AWS Lambda + EventBridge

Serverless deployment: no idle instance, runs on a schedule, costs ~$0/month at this scale.

### Architecture

```
EventBridge Scheduler (every 15 min)
    └─▶ Lambda (container image, 512 MB, 15 min timeout)
            ├─ Secrets Manager: gmail-agent/anthropic-api-key
            ├─ Secrets Manager: gmail-agent/token        ← auto-refreshed in place
            └─ Secrets Manager: gmail-agent/credentials
```

### Prerequisites

- AWS CLI configured (`aws configure`)
- AWS SAM CLI installed (`brew install aws-sam-cli`)
- Docker running

### One-time deploy

```bash
sam build
sam deploy --guided   # enter Anthropic API key when prompted
```

SAM creates the Lambda function (container image), IAM roles, and exports `FunctionArn` + `SchedulerRoleArn`.

### Adding a user (one command)

```bash
./add-user.sh alice <FunctionArn> <SchedulerRoleArn>
# custom schedule:
./add-user.sh bob   <FunctionArn> <SchedulerRoleArn> "rate(30 minutes)"
./add-user.sh carol <FunctionArn> <SchedulerRoleArn> "cron(0 8 * * ? *)"
```

Each user gets their own EventBridge schedule. The script authenticates Gmail locally, uploads the token to Secrets Manager (`gmail-agent/{user}/token`), then creates the schedule with `{"user_id": "alice"}` as event payload.

Each schedule is independent — different frequencies, different users, one shared Lambda.

### Useful commands

```bash
# View live logs
aws logs tail /aws/lambda/GmailAgentFunction --follow

# Trigger a specific user manually
aws lambda invoke \
  --function-name GmailAgentFunction \
  --payload '{"user_id":"alice"}' \
  /dev/stdout

# List all schedules
aws scheduler list-schedules --name-prefix gmail-agent-

# Remove a user
aws scheduler delete-schedule --name gmail-agent-alice

# Re-authenticate Gmail (token expired or revoked)
rm token.pickle
./add-user.sh alice <FunctionArn> <SchedulerRoleArn>
```

## Files

- `agent.py` — main entry point and agentic loop
- `gmail_auth.py` — Gmail OAuth, supports both local (pickle) and Lambda (Secrets Manager) modes
- `lambda_function.py` — AWS Lambda handler
- `Dockerfile` — container image for Lambda
- `template.yaml` — AWS SAM infrastructure definition
- `requirements.txt` — Python dependencies
- `credentials.json` — Google OAuth client secrets (not committed)
- `token.pickle` — saved OAuth token, local only (not committed)

## Security model

### What is isolated

- Each user's Gmail token is in a separate secret (`gmail-agent/{user}/token`)
- `user_id` is validated on entry — alphanumerics, hyphens, underscores only (no path traversal)
- The IAM policy uses two scoped resource ARNs:
  - `gmail-agent/anthropic-api-key*` — read-only, shared key
  - `gmail-agent/*/*` — read/write, only two-segment paths (per-user secrets); cannot reach flat secrets outside the namespace

### Remaining limitation — shared Lambda

With a single shared Lambda, cross-user access is enforced **by application code**, not by IAM. The Lambda role has `gmail-agent/*/*` access across all users. A bug in `set_user()` or the event parsing could in theory cause one user's invocation to load another's token.

**Acceptable for:** personal use, small trusted groups, internal tooling.

**Not acceptable for:** a commercial multi-tenant SaaS where users are strangers.

### Security roadmap (not yet implemented)

#### 20–5 000 users — STS AssumeRole per user

One Lambda, one IAM role per user scoped to `gmail-agent/{user_id}/*`. The Lambda's
base role has only `sts:AssumeRole`; it assumes the user-specific role at invocation
start and gets temporary credentials (15 min) that can only reach that user's secrets.
Adding a user = `add-user.sh` creates the IAM role, no redeploy needed.

```
Lambda (base role: sts:AssumeRole only)
  └─ AssumeRole → role-gmail-agent-alice  (access: gmail-agent/alice/* only)
  └─ AssumeRole → role-gmail-agent-bob   (access: gmail-agent/bob/*  only)
```

#### 5 000–500 000 users — ABAC + DynamoDB/KMS

At this scale Secrets Manager becomes expensive (~$0.40/secret/month) and
hits operational limits. Switch to:

- **DynamoDB** for token storage (encrypted at rest, ~$0.25/million reads)
- **KMS customer-managed key per user** for envelope encryption (IAM-enforced)
- **STS session tags** (`UserId=alice`) + IAM ABAC condition on KMS key tags:
  `StringEquals: {"aws:ResourceTag/Owner": "${aws:PrincipalTag/UserId}"}`
- **SQS** for job dispatch (one message per user) instead of one schedule per user
- **Cognito** for user authentication and OAuth callback (replaces the local `add-user.sh` flow)

At this scale other concerns dominate before IAM isolation: Anthropic API rate
limits (shared key across all users), GDPR data residency, per-user billing, and
a proper web onboarding flow.

#### 500 000+ users — multi-account

Separate AWS account per tenant group via AWS Organizations + Control Tower.
Account-level isolation is the strongest boundary AWS offers.

## Notes

- The agent reads but does not delete, archive, or send any emails
- Labels are additive — existing labels are preserved
- Threads already carrying a triage label are skipped to avoid re-processing
