# Website Developer Bot

Telegram bot that updates the PAN Medical & Industrial Supplies website via Claude AI.
Non-technical users send plain-English messages on Telegram; the bot applies changes to the live site.

Live website: https://panmedical.pages.dev
Production worker: https://website-developer-bot.ausaf1996.workers.dev/webhook

## Architecture

```
Telegram Message
      |
      v
Cloudflare Worker  (src/worker.py)  -- or --  Flask server (local_server.py)
      |
      +---> Telegram API   (src/telegram.py)     -- parse incoming, send replies
      +---> Claude API     (src/claude_client.py) -- understand request, generate updated HTML
      +---> GitHub API     (src/github_client.py) -- fetch current HTML, push updates
      +---> HTML Validator (src/html_validator.py) -- validate HTML before deploying
      +---> KV Store       -- pending confirmations, rollback snapshots, conversation history
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
The bot application runs on Cloudflare Workers (deployed via `wrangler deploy`).

## Project Structure

```
WebsiteDeveloperBot/
+-- .gitignore              # Excludes .env, __pycache__, .wrangler, node_modules, build/
+-- .env                    # Local environment variables (NOT committed)
+-- pyproject.toml          # Python project config and local dev dependencies
+-- wrangler.jsonc          # Cloudflare Workers deployment config
+-- local_server.py         # Flask server for local testing
+-- Claude.md               # This file -- project context for AI assistants
+-- README.md               # Human-readable setup and deployment guide
+-- src/
    +-- __init__.py
    +-- worker.py           # Cloudflare Workers entry point (Pyodide runtime)
    +-- bot.py              # Core logic: message routing, confirmation flow, rollback
    +-- claude_client.py    # Claude API integration with strict update-only prompt
    +-- telegram.py         # Telegram Bot API -- parse updates, send messages
    +-- github_client.py    # GitHub Contents API -- read/write index.html
    +-- html_validator.py   # Plain Python validation -- ensures HTML integrity
```

## Module Details

### src/worker.py (Cloudflare Workers entry point)
- Defines `on_fetch(request, cf_env, ctx)` -- the Workers fetch handler.
- `WorkersEnv` class adapts Cloudflare bindings (secrets, KV) into the shared `env` interface.
- Uses `ctx.waitUntil(promise)` to process messages in the background (returns 200 immediately).
- **Critical**: Python coroutines must be wrapped with `to_js()` before passing to `ctx.waitUntil()` because it expects a JS Promise, not a Python coroutine.
- Only handles POST `/webhook`.
- Imports use `try/except` fallback: `from src.X` (local) -> `from X` (Cloudflare Workers).

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
- **Critical**: All requests must include `User-Agent: WebsiteDeveloperBot` header. The Workers `fetch` API does not add one automatically (unlike the `requests` library used locally), and GitHub rejects requests without it.
- Logs non-200 responses for debugging.

### src/html_validator.py (HTML validation)
- Plain Python class -- **NOT pydantic** (pydantic is not available in Cloudflare Workers Pyodide runtime).
- `ValidatedHTML(content=html_string)` -- validates on construction, raises `ValueError` if invalid.
- Three checks:
  1. `_must_be_complete_html` -- DOCTYPE, html, head, body tags.
  2. `_must_have_required_sections` -- all 9 section IDs: home, about, api, formulations, contrast, devices, chemicals, animal, contact.
  3. `_must_have_sidebar_and_footer` -- sidebar-wrapper and footer-contact elements.

### local_server.py (Local development)
- Flask app on port 8787 mimicking the Cloudflare Worker.
- `LocalEnv` class implements the same `env` interface using `requests` library for HTTP and in-memory dict for KV.
- Processes messages in background threads (each with its own asyncio event loop).
- Local KV does not enforce TTLs.

## Environment Interface

Both `WorkersEnv` (production) and `LocalEnv` (local) implement this interface. All business logic uses only these methods, making it runtime-agnostic:

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
| `TELEGRAM_BOT_TOKEN` | Telegram bot token from BotFather | `.env` (local) / `wrangler secret` (prod) |
| `CLAUDE_API_KEY` | Anthropic API key | `.env` (local) / `wrangler secret` (prod) |
| `GITHUB_TOKEN` | GitHub PAT with repo write access | `.env` (local) / `wrangler secret` (prod) |
| `GITHUB_REPO_OWNER` | GitHub username owning the website repo | `.env` (local) / `wrangler secret` (prod) |
| `GITHUB_REPO_NAME` | Name of the website HTML repo | `.env` (local) / `wrangler secret` (prod) |
| `GITHUB_FILE_PATH` | Path to HTML file in repo (default: `index.html`) | `.env` (local) / `wrangler.jsonc` vars (prod) |
| `GITHUB_BRANCH` | Branch to update (default: `main`) | `.env` (local) / `wrangler.jsonc` vars (prod) |

## Cloudflare Workers Python (Pyodide) Constraints

These are critical to know when modifying the codebase:

1. **No pydantic** -- Pyodide does not include pydantic. Use plain Python classes for validation.
2. **No `requests` library** -- use the global `fetch` API via `from js import fetch`.
3. **Flat module structure** -- Wrangler flattens `src/` files. Imports like `from src.bot import X` fail at runtime. Use `try/except` fallback pattern:
   ```python
   try:
       from src.bot import handle_message      # works locally
   except ModuleNotFoundError:
       from bot import handle_message           # works in Cloudflare Workers
   ```
4. **JS interop** -- Python coroutines must be converted to JS Promises with `to_js()` before passing to JS APIs like `ctx.waitUntil()`.
5. **GitHub API needs User-Agent** -- Workers `fetch` does not add a User-Agent header automatically. Must include `"User-Agent": "WebsiteDeveloperBot"` explicitly in all GitHub API requests.
6. **Available built-in modules**: `json`, `re`, `base64`, `asyncio` all work fine. Third-party packages generally do NOT work unless they are bundled in Pyodide.

## Deployment

### Production (Cloudflare Workers)
```bash
npx wrangler deploy
```
Then set the Telegram webhook (one-time, or after changing worker URL):
```bash
curl "https://api.telegram.org/bot<TOKEN>/setWebhook?url=https://website-developer-bot.ausaf1996.workers.dev/webhook"
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
Remember to reset the webhook to the Cloudflare URL when done testing locally.

### Viewing production logs
```bash
npx wrangler tail --format pretty
```

### Checking webhook status
```bash
curl "https://api.telegram.org/bot<TOKEN>/getWebhookInfo"
```

## Key Design Decisions

- **No database** -- Cloudflare KV stores three lightweight things per chat: pending (1hr TTL), rollback (24hr TTL), history (24hr TTL). All expire automatically.
- **One-level rollback** -- only the most recent change can be undone. After rollback, no further undo until a new change is applied.
- **Confirmation required** -- every change must be confirmed with YES/NO before it is applied, preventing accidental updates.
- **HTML fetched fresh each request** -- current HTML is fetched from GitHub on every new request, never stored in conversation history. Only one copy of the HTML per API call.
- **Conversation history is text only** -- the last 20 messages (plain text, no HTML) are stored and replayed to Claude for follow-up context.
- **Environment abstraction** -- `WorkersEnv` (production) and `LocalEnv` (dev) both implement the same interface so all business logic is runtime-agnostic.
- **Two repos** -- this repo holds the bot application; a separate repo (`PanMedicalSupplies`) holds the website HTML. Cloudflare Pages watches the website repo for auto-deploy.
- **Simple scope** -- only textual updates (products, descriptions, contact info). Complex features (databases, new pages, interactive elements) are explicitly out of scope.
