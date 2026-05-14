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

## Files

- `agent.py` — main entry point and agentic loop
- `requirements.txt` — Python dependencies
- `credentials.json` — Google OAuth client secrets (not committed)
- `token.pickle` — saved OAuth token (not committed)

## Notes

- The agent reads but does not delete, archive, or send any emails
- Labels are additive — existing labels are preserved
- Threads already carrying a triage label are skipped to avoid re-processing
