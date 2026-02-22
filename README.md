# Website Developer Bot

A Telegram bot that lets non-technical users update the [PAN Medical & Industrial Supplies](https://panmedical.pages.dev) website by sending plain-English messages. The bot uses Claude AI to understand requests, modifies the HTML, validates it, and deploys the changes automatically.

## How It Works

```
User sends Telegram message
        |  "Add Paracetamol to the Pharmaceuticals section"
        v
+---------------------+
|  Google Cloud Run    |--- Fetches current website HTML from GitHub
|  (this application)  |--- Sends HTML + request to Claude API
|                      |--- Claude generates updated HTML + summary
|                      |--- Stores pending change, asks user to confirm
+---------------------+
        |  User replies "YES"
        v
+---------------------+
|  Validates HTML      |--- Checks structure is intact
|  Pushes to GitHub    |--- Commits updated index.html
|  Cloudflare Pages    |--- Auto-deploys from GitHub (already configured)
+---------------------+
        |
        v
  Website is live with the changes
```

### Conversation Example

```
User:  Add "Metformin HCL" to the Pharmaceuticals table with status Commercial
       and regulatory documents USP/EP

Bot:   I will make these changes:

       Add a new row "Metformin HCL" with status "Commercial" and regulatory
       documents "USP/EP" to the Pharmaceuticals & API's table.

       Reply YES to confirm or NO to cancel.

User:  YES

Bot:   Done! The website has been updated.
       Changes made: Added Metformin HCL to Pharmaceuticals & API's table.
       The website will refresh automatically in a minute or two.
       If you don't like this change, send UNDO to revert it.

User:  Also add "Aspirin" with status Commercial and documents IP/USP

Bot:   I will make these changes: ...

User:  YES

Bot:   Done! ...

User:  UNDO

Bot:   Done! The last change has been undone.
       Reverted: Added Aspirin to Pharmaceuticals & API's table.
       The website will refresh in a minute or two.
```

> The bot remembers your recent conversation (last 20 messages, 24 hours) so you can
> send follow-up requests like "also add...", "change that to...", or "remove the one
> I just added" without repeating yourself.

---

## Prerequisites

Before setting up, you need:

1. **A Google Cloud account** -- free tier works (Cloud Run free tier: 2M requests/month)
2. **A Telegram bot** -- create one via [BotFather](https://t.me/BotFather) on Telegram
3. **An Anthropic API key** -- from [console.anthropic.com](https://console.anthropic.com/)
4. **A GitHub account** with a **separate repository** that holds your website's `index.html`
5. **gcloud CLI** -- install via `brew install google-cloud-sdk` (macOS) or [cloud.google.com/sdk/docs/install](https://cloud.google.com/sdk/docs/install)
6. **Python** (3.11+) -- for local development

---

## Setup

### 1. Clone and install dependencies

```bash
git clone https://github.com/your-username/WebsiteDeveloperBot.git
cd WebsiteDeveloperBot

# Install Python dependencies for local development
pip install .
```

### 2. Create the website repository

This bot updates a **separate** GitHub repository that holds the website HTML. Cloudflare Pages watches that repo and auto-deploys on every push.

1. Create a new GitHub repo (e.g., `PanMedicalSupplies`)
2. Add your `index.html` to it and push
3. In Cloudflare Dashboard -> Pages -> Create a project -> Connect to Git -> select that repo
4. Set build output directory to `/` (the repo root), no build command needed
5. Deploy -- your site is now live at `your-project.pages.dev`

### 3. Create a Telegram bot

1. Open Telegram and message [@BotFather](https://t.me/BotFather)
2. Send `/newbot` and follow the prompts to name your bot
3. BotFather will give you a **bot token** -- this is your `TELEGRAM_BOT_TOKEN`
4. Optionally send `/setdescription` to describe what the bot does

### 4. Get API keys

| Key | Where to get it |
|---|---|
| `CLAUDE_API_KEY` | [console.anthropic.com](https://console.anthropic.com/) -> API Keys |
| `GITHUB_TOKEN` | [github.com/settings/tokens](https://github.com/settings/tokens) -> Generate new token (classic) -> select `repo` scope |

### 5. Configure environment

#### For local development

```bash
cp .env.example .env
```

Edit `.env` and fill in all the values:

```
TELEGRAM_BOT_TOKEN=123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11
CLAUDE_API_KEY=sk-ant-xxxxxxx...
GITHUB_TOKEN=ghp_xxxxxxx...
GITHUB_REPO_OWNER=your-github-username
GITHUB_REPO_NAME=PanMedicalSupplies
GITHUB_FILE_PATH=index.html
GITHUB_BRANCH=main
```

### 6. Deploy to Google Cloud Run

```bash
# Authenticate (first time only)
gcloud init

# Deploy
gcloud run deploy website-developer-bot \
  --source . \
  --region us-central1 \
  --allow-unauthenticated \
  --set-env-vars "TELEGRAM_BOT_TOKEN=...,CLAUDE_API_KEY=...,GITHUB_TOKEN=...,GITHUB_REPO_OWNER=...,GITHUB_REPO_NAME=...,GITHUB_FILE_PATH=index.html,GITHUB_BRANCH=main" \
  --timeout=300 \
  --memory=512Mi \
  --cpu=1 \
  --min-instances=0 \
  --max-instances=1
```

After deploying, gcloud will print the Service URL, e.g.:
```
https://website-developer-bot-843979520931.us-central1.run.app
```

### 7. Set the Telegram webhook

Tell Telegram where to send updates by calling the `setWebhook` API:

```bash
curl "https://api.telegram.org/bot<YOUR_BOT_TOKEN>/setWebhook?url=https://<CLOUD_RUN_URL>/webhook"
```

You should get back:
```json
{"ok": true, "result": true, "description": "Webhook was set"}
```

The bot is now live. Send a message to your bot on Telegram to test.

---

## Local Development

For testing locally before deploying:

```bash
# Start the local server
python local_server.py
```

The server runs at `http://localhost:8787`. To receive Telegram webhooks locally, expose it with [ngrok](https://ngrok.com/):

```bash
ngrok http 8787
```

> **Note**: ngrok free tier uses `.ngrok-free.dev` domain (not `.ngrok-free.app`).

Then set the webhook to your ngrok URL (temporarily, for testing):

```bash
curl "https://api.telegram.org/bot<YOUR_BOT_TOKEN>/setWebhook?url=https://<NGROK_URL>/webhook"
```

Remember to reset the webhook to your Cloud Run URL when done testing locally.

---

## Project Structure

```
WebsiteDeveloperBot/
+-- .gitignore              # Excludes .env, __pycache__, .wrangler, node_modules, build/
+-- .env                    # Local environment variables (NOT committed)
+-- .dockerignore           # Excludes .git, .env, etc. from Docker image
+-- Dockerfile              # Container definition for Cloud Run
+-- pyproject.toml          # Python project config and dependencies
+-- local_server.py         # Flask server (production on Cloud Run + local dev)
+-- Claude.md               # Project context for AI assistants (Claude Code, etc.)
+-- README.md               # This file
+-- src/
    +-- __init__.py
    +-- worker.py           # Cloudflare Workers entry point (legacy)
    +-- bot.py              # Core logic: message routing, confirmation flow, rollback
    +-- claude_client.py    # Claude API -- understands requests, generates HTML
    +-- telegram.py         # Telegram Bot API -- parse updates, send messages
    +-- github_client.py    # GitHub API -- fetches and pushes index.html
    +-- html_validator.py   # HTML validation -- ensures structural integrity
```

### Module Responsibilities

| Module | What it does |
|---|---|
| `local_server.py` | Flask app serving as the main entry point. Handles POST `/webhook` for Telegram updates, GET `/webhook?logs` for error logs, GET `/webhook?usage` for token usage logs. Runs with gunicorn on Cloud Run, or standalone locally. |
| `src/bot.py` | Orchestrates the full flow: authorization check, rollback commands, pending confirmations, new requests, conversation history. Manages three KV keys per chat: `pending:`, `rollback:`, `history:`. |
| `src/claude_client.py` | Sends current HTML + conversation history + user message to Claude (claude-opus-4-6). Builds multi-turn messages so Claude understands follow-ups. |
| `src/telegram.py` | Parses incoming Telegram update payloads and sends text replies via the Bot API. |
| `src/github_client.py` | Reads and writes `index.html` in the website GitHub repo using the Contents API. |
| `src/html_validator.py` | Validates every generated HTML before deployment -- checks for DOCTYPE, all 9 page sections, sidebar, and footer. |
| `src/worker.py` | Legacy Cloudflare Workers entry point. Kept for reference. |

---

## Access Control

The bot restricts access to specific Telegram chat IDs. Edit the `ALLOWED_CHAT_IDS` list in `src/bot.py`:

```python
ALLOWED_CHAT_IDS = [
    "8490004746",
    # Add more chat IDs here
]
```

To find your chat ID, send a message to the bot and check the logs (`gcloud run logs read website-developer-bot --region us-central1` or the Flask console).

If `ALLOWED_CHAT_IDS` is empty, all users are allowed.

---

## What the Bot Can Do

- Add or remove products from any section (Pharmaceuticals, Veterinary, Chemicals, etc.)
- Update product names, descriptions, statuses, or regulatory documents
- Modify text content (headings, descriptions, about us, etc.)
- Update contact information
- **Undo the last change** -- send "undo", "rollback", or "revert" to restore the previous version
- **Follow-up requests** -- the bot remembers your recent conversation (last 20 messages, 24 hours) so you can say things like "also add...", "change that to...", or "remove the one I just added"

## What the Bot Will Not Do

- Add complex features (databases, forms, login systems, etc.)
- Create new pages or sections
- Change the visual design or layout significantly
- Anything unrelated to updating the website content
- Undo more than one change back (only the most recent change can be reverted)

The bot will politely inform the user when a request is out of scope.

---

## Rollback & Conversation History

### Rollback (Undo)

Before every confirmed update, the bot saves the current HTML as a rollback snapshot. If the user sends **UNDO**, **ROLLBACK**, or **REVERT**, the bot restores the previous version and pushes it to GitHub.

- Only the **most recent** change can be undone (one level deep).
- The rollback snapshot resets on container cold starts.
- After a rollback, there is no further undo available until a new change is applied.

### Conversation History

The bot stores the last 20 messages (user + bot) per chat ID in memory. This history is sent to Claude as multi-turn context, enabling:

- **Follow-up requests**: "Also add Ibuprofen to that same section"
- **Corrections**: "Actually change the status to Lab Scale instead"
- **References**: "Remove the product I just added"

History resets on container cold starts or after 24 hours of inactivity (locally).

---

## Monitoring & Logs

### View production logs
```bash
gcloud run logs read website-developer-bot --region us-central1 --limit 50
```

### Stream live logs
```bash
gcloud run logs tail website-developer-bot --region us-central1
```

### Check error logs via HTTP
```bash
curl "https://website-developer-bot-843979520931.us-central1.run.app/webhook?logs"
```

### Check usage/token logs via HTTP
```bash
curl "https://website-developer-bot-843979520931.us-central1.run.app/webhook?usage"
```

### Check webhook status
```bash
curl "https://api.telegram.org/bot<TOKEN>/getWebhookInfo"
```

---

## Troubleshooting

### Bot doesn't respond
- Check Cloud Run logs: `gcloud run logs read website-developer-bot --region us-central1 --limit 50`
- Check the webhook is set: `curl "https://api.telegram.org/bot<TOKEN>/getWebhookInfo"`
- Look for `last_error_message` in the webhook info -- common issues:
  - 404 errors: webhook URL is wrong
  - Connection errors: service is not deployed or is sleeping

### HTML validation fails after an update
- This means Claude's output was missing a required section. The bot will ask the user to try again. If it keeps failing, the system prompt in `src/claude_client.py` may need adjustment.

### Changes don't appear on the website
- Confirm Cloudflare Pages is connected to the correct GitHub repo and branch.
- Check the GitHub repo to see if the commit was pushed successfully.
- Cloudflare Pages typically deploys within 1-2 minutes of a push.

### Webhook issues
- Verify webhook status: `curl "https://api.telegram.org/bot<TOKEN>/getWebhookInfo"`
- If switching between local/production, remember to update the webhook URL.
- Telegram only supports HTTPS webhook URLs.
- ngrok free tier uses `.ngrok-free.dev` (not `.ngrok-free.app`).

### Cold starts
- Cloud Run may take a few seconds to start up after being idle. The first request after a cold start may be slower.
- In-memory KV data (pending confirmations, rollback, history) is lost on cold starts. This is by design -- all data has short lifetimes.

---

## Two-Repo Setup Explained

This project uses **two separate GitHub repositories**:

| Repo | Purpose | Managed by |
|---|---|---|
| `WebsiteDeveloperBot` (this repo) | The bot application code | You (the developer) |
| `PanMedicalSupplies` (or your chosen name) | The website `index.html` | The bot (via GitHub API) |

Cloudflare Pages watches the **website repo** and auto-deploys whenever the bot pushes an updated `index.html`. The bot application itself runs on **Google Cloud Run** (deployed via `gcloud run deploy`).

---

## Redeploying

After making code changes, redeploy with:

```bash
gcloud run deploy website-developer-bot \
  --source . \
  --region us-central1
```

Environment variables persist between deploys -- you only need `--set-env-vars` when changing them.
