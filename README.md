# Gmail Email Labeling Agent

![CI](https://github.com/fbrillon/test-repo/actions/workflows/ci.yml/badge.svg)
![Security](https://github.com/fbrillon/test-repo/actions/workflows/security.yml/badge.svg)

Autonomous agent that reads unread Gmail threads and applies triage labels using Claude — so every email is classified before you even open your inbox.

## Labels applied

| Label | Meaning |
|---|---|
| `Act_Now` | Needs a reply or action today |
| `Next_Moves` | Needs action, not urgent |
| `Track_It` | Receipt or awaiting reply — monitor only |
| `Stay_Informed` | Informational, no action required |
| `Skip_It` | Newsletter, promo — safe to ignore |

## Quick start

```bash
git clone https://github.com/fbrillon/test-repo
pip install -r requirements.txt
# Place credentials.json from Google Cloud Console in the project root
export ANTHROPIC_API_KEY=sk-ant-...
python agent.py --dry-run   # preview without applying labels
python agent.py             # run for real
```

## Deploy (serverless, runs every 15 min, ~$0/month)

```bash
sam build && sam deploy --guided          # first time
./add-user.sh <user> <FunctionArn> <SchedulerRoleArn>
```

## Full documentation

See [CLAUDE.md](CLAUDE.md) for complete setup, architecture, multi-user deployment, and security model.
