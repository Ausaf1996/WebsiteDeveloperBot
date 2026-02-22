# Website Developer Bot

Telegram bot that updates the PAN Medical & Industrial Supplies website via Claude AI.
Non-technical users send plain-English messages on Telegram; the bot applies changes to the live site.

Live website: https://panmedicalsupplies.com
Production server: https://website-developer-bot-843979520931.us-central1.run.app/webhook

## Architecture

```
Telegram Message
      |
      v
Google Cloud Run   (local_server.py + gunicorn)
      |
      +---> Telegram API   (src/telegram.py)     -- parse incoming, send replies
      +---> Claude API     (src/claude_client.py) -- understand request, generate updated HTML
      +---> GitHub API     (src/github_client.py) -- fetch current HTML, push updates
      +---> HTML Validator (src/html_validator.py) -- validate HTML before deploying
      +---> In-memory KV   -- pending confirmations, rollback snapshots, conversation history
              |
              v
      Cloudflare Pages auto-deploys from the GitHub website repo
```

### Two-Repo Setup

| Repo | Purpose | Managed by |
|---|---|---|
| `WebsiteDeveloperBot` (this repo) | Bot application code | Developer |
| `PanMedicalSupplies` (GitHub: Ausaf1996) | Website `index.html` | The bot (via GitHub API) |

Cloudflare Pages watches the website repo and auto-deploys on every push.
The bot application runs on Google Cloud Run (deployed via `gcloud run deploy`).

## Project Structure

```
WebsiteDeveloperBot/
+-- .gitignore              # Excludes .env, __pycache__, .wrangler, node_modules, build/
+-- .env                    # Local environment variables (NOT committed)
+-- .dockerignore           # Excludes .git, .env, etc. from Docker image
+-- Dockerfile              # Container definition for Cloud Run
+-- pyproject.toml          # Python project config and dependencies
+-- wrangler.jsonc          # Cloudflare Workers config (legacy, kept for reference)
+-- local_server.py         # Flask server -- runs both locally and on Cloud Run
+-- Claude.md               # This file -- project context for AI assistants
+-- README.md               # Human-readable setup and deployment guide
+-- src/
    +-- __init__.py
    +-- worker.py           # Cloudflare Workers entry point (legacy, kept for reference)
    +-- bot.py              # Core logic: message routing, confirmation flow, rollback
    +-- claude_client.py    # Claude API integration with strict update-only prompt
    +-- telegram.py         # Telegram Bot API -- parse updates, send messages
    +-- github_client.py    # GitHub Contents API -- read/write index.html
    +-- html_validator.py   # Plain Python validation -- ensures HTML integrity
```

## Module Details

### local_server.py (Flask server -- production & local)
- Flask app serving as the main entry point for both Cloud Run (production) and local development.
- `LocalEnv` class implements the shared `env` interface using `requests` library for HTTP and in-memory dict for KV.
- Processes Telegram messages in background threads (each with its own asyncio event loop).
- **Endpoints**:
  - `POST /webhook` -- incoming Telegram updates.
  - `GET /webhook?logs` -- error log entries from KV.
  - `GET /webhook?usage` -- usage/token log entries from KV.
- In-memory KV does not enforce TTLs. KV data resets on container cold starts, but that's acceptable since pending confirmations, rollback, and history all have short effective lifetimes anyway.
- Uses `PORT` env var (Cloud Run sets this to 8080; defaults to 8787 locally).
- In production, gunicorn runs the app with 300s worker timeout.
- **Per-chat concurrency lock** -- if a message is already being processed for a chat, new messages from that chat get a "Please wait" reply instead of racing on shared KV state. Different chats process concurrently.

### src/worker.py (Cloudflare Workers entry point -- legacy)
- Kept for reference. Was the production entry point when deployed on Cloudflare Workers.
- Defines `on_fetch(request, cf_env, ctx)` -- the Workers fetch handler.
- `WorkersEnv` class adapts Cloudflare bindings (secrets, KV) into the shared `env` interface.
- **No longer used in production** -- Cloud Run uses `local_server.py` instead.

### src/bot.py (Core orchestration)
Orchestrates the full conversation flow:
1. **Authorization check** -- only chat IDs in `ALLOWED_CHAT_IDS` list can use the bot.
2. **Rollback commands** (undo/rollback/revert) -- restores previous HTML from KV.
3. **Pending confirmation** -- if a change is waiting, handles YES/NO responses.
4. **New request** -- fetches HTML from GitHub, loads conversation history, sends to Claude, stores pending change in KV, asks user to confirm.

**KV key patterns** (three per chat ID):
- `pending:{chat_id}` -- pending HTML + summary awaiting YES/NO (TTL: 3600s = 1 hour).
- `rollback:{chat_id}` -- snapshot of HTML before last applied change (TTL: 86400s = 24 hours).
- `history:{chat_id}` -- last 20 conversation messages for Claude context (TTL: 86400s = 24 hours).

**Constants** at top of file:
- `MAX_HISTORY_MESSAGES = 20`
- `HISTORY_TTL = 86400` (24 hours)
- `ALLOWED_CHAT_IDS` -- list of string chat IDs allowed to use the bot. If empty list, all users are allowed.

**Logging**: Prints `[USER {chat_id}]` and `[BOT {chat_id}]` for messages, plus token usage per Claude API call.

### src/claude_client.py (Claude API)
- Model: `claude-opus-4-6`
- Max tokens: 16000
- System prompt enforces strict rules: only modify what's explicitly requested, never remove/add unless asked.
- `_build_messages()` constructs the messages array:
  - **With history**: HTML as first user message, then conversation history replayed as user/assistant turns, then latest user message.
  - **Without history**: Single user message with HTML + request combined.
  - Only ONE copy of the HTML is ever included per API call (fetched fresh each time, not stored in history).
- Response format is structured JSON with `action` field: `update`, `clarify`, `out_of_scope`, `off_topic`.
- Returns `_usage` key with token counts for logging.
- Falls back to regex JSON extraction if Claude wraps response in text.

### src/telegram.py (Telegram Bot API)
- `parse_incoming_message(body)` -- extracts `(chat_id, text)` from Telegram update. Handles both `message` and `edited_message`.
- `send_message(env, chat_id, text)` -- sends reply with Markdown parse mode.

### src/github_client.py (GitHub Contents API)
- `get_current_html(env)` -- fetches `index.html` + SHA from the website repo. Returns `(content, sha)` or `(None, None)`.
- `update_html(env, new_html, commit_message)` -- commits updated HTML. Fetches current SHA first (required by GitHub API).
- **Critical**: All requests must include `User-Agent: WebsiteDeveloperBot` header. GitHub rejects requests without it.
- Logs non-200 responses for debugging.

### src/html_validator.py (HTML validation)
- Plain Python class -- **NOT pydantic** (kept plain for compatibility).
- `ValidatedHTML(content=html_string)` -- validates on construction, raises `ValueError` if invalid.
- Three checks:
  1. `_must_be_complete_html` -- DOCTYPE, html, head, body tags.
  2. `_must_have_required_sections` -- all 9 section IDs: home, about, api, formulations, contrast, devices, chemicals, animal, contact.
  3. `_must_have_sidebar_and_footer` -- sidebar-wrapper and footer-contact elements.

## Environment Interface

`LocalEnv` (used in both production and local dev) implements this interface. All business logic uses only these methods:

```python
env.telegram_bot_token: str
env.claude_api_key: str
env.github_token: str
env.github_repo_owner: str
env.github_repo_name: str
env.github_file_path: str     # default: "index.html"
env.github_branch: str        # default: "main"

await env.http_request(method, url, headers=None, body=None) -> {"status": int, "text": str}
await env.kv_get(key) -> str | None
await env.kv_put(key, value, ttl=None)
await env.kv_delete(key)
```

## Environment Variables

| Variable | Description | Where set |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | Telegram bot token from BotFather | `.env` (local) / Cloud Run env vars (prod) |
| `CLAUDE_API_KEY` | Anthropic API key | `.env` (local) / Cloud Run env vars (prod) |
| `GITHUB_TOKEN` | GitHub PAT with repo write access | `.env` (local) / Cloud Run env vars (prod) |
| `GITHUB_REPO_OWNER` | GitHub username owning the website repo | `.env` (local) / Cloud Run env vars (prod) |
| `GITHUB_REPO_NAME` | Name of the website HTML repo | `.env` (local) / Cloud Run env vars (prod) |
| `GITHUB_FILE_PATH` | Path to HTML file in repo (default: `index.html`) | `.env` (local) / Cloud Run env vars (prod) |
| `GITHUB_BRANCH` | Branch to update (default: `main`) | `.env` (local) / Cloud Run env vars (prod) |
| `PORT` | Server port (default: 8787 local, 8080 Cloud Run) | Set automatically by Cloud Run |

## Deployment

### Production (Google Cloud Run)

```bash
export CLOUDSDK_PYTHON=/opt/homebrew/bin/python3.13
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

Then set the Telegram webhook (one-time, or after changing service URL):
```bash
curl "https://api.telegram.org/bot<TOKEN>/setWebhook?url=https://website-developer-bot-843979520931.us-central1.run.app/webhook"
```

### Local development
```bash
pip install .
cp .env.example .env   # fill in keys
python local_server.py  # runs on http://localhost:8787
ngrok http 8787         # expose for Telegram webhook
curl "https://api.telegram.org/bot<TOKEN>/setWebhook?url=https://<NGROK_URL>/webhook"
```

Note: ngrok free tier uses `.ngrok-free.dev` domain (not `.ngrok-free.app`).
Remember to reset the webhook to the Cloud Run URL when done testing locally.

### Viewing production logs
```bash
export CLOUDSDK_PYTHON=/opt/homebrew/bin/python3.13
gcloud run services logs read website-developer-bot --region us-central1 --limit 50
```

Or stream live:
```bash
gcloud run services logs tail website-developer-bot --region us-central1
```

### Checking webhook status
```bash
curl "https://api.telegram.org/bot<TOKEN>/getWebhookInfo"
```

### Checking error/usage logs via HTTP
```bash
curl "https://website-developer-bot-843979520931.us-central1.run.app/webhook?logs"
curl "https://website-developer-bot-843979520931.us-central1.run.app/webhook?usage"
```

## Key Design Decisions

- **Google Cloud Run** -- Migrated from Cloudflare Workers because Workers' free plan has a 30-second `waitUntil()` limit and 10ms CPU cap. Claude Opus responses with full HTML take 30-60+ seconds. Cloud Run has a generous free tier, 300s request timeout, and no CPU limits.
- **In-memory KV** -- Uses a simple Python dict for KV storage. Data resets on container cold starts, but all stored data (pending confirmations, rollback snapshots, conversation history) has short effective lifetimes anyway. No external database needed.
- **One-level rollback** -- only the most recent change can be undone. After rollback, no further undo until a new change is applied.
- **Confirmation required** -- every change must be confirmed with YES/NO before it is applied, preventing accidental updates.
- **HTML fetched fresh each request** -- current HTML is fetched from GitHub on every new request, never stored in conversation history. Only one copy of the HTML per API call.
- **Conversation history is text only** -- the last 20 messages (plain text, no HTML) are stored and replayed to Claude for follow-up context.
- **Environment abstraction** -- `LocalEnv` implements a clean interface so all business logic is runtime-agnostic.
- **Two repos** -- this repo holds the bot application; a separate repo (`PanMedicalSupplies`) holds the website HTML. Cloudflare Pages watches the website repo for auto-deploy.
- **Simple scope** -- only textual updates (products, descriptions, contact info). Complex features (databases, new pages, interactive elements) are explicitly out of scope.
