# Website Developer Bot

Telegram bot that updates the PAN Medical & Industrial Supplies website via Claude API.
Non-technical users send plain-English messages on Telegram; the bot applies changes to the live site.

## Architecture

```
Telegram Message
      │
      ▼
Cloudflare Worker  (src/worker.py)
      │
      ├─► Telegram API  (src/telegram.py)    — parse incoming, send replies
      ├─► Claude API    (src/claude_client.py) — understand request, generate updated HTML
      ├─► GitHub API    (src/github_client.py) — fetch current HTML, push updates
      ├─► Pydantic      (src/html_validator.py) — validate HTML before deploying
      └─► KV Store      — pending confirmations, rollback snapshots, conversation history
              │
              ▼
      Cloudflare Pages auto-deploys from the GitHub website repo
```

## Project Structure

```
├── .gitignore              # Excludes .env, __pycache__, .wrangler, node_modules
├── .env.example            # Template — copy to .env for local development
├── pyproject.toml          # Python project config and dependencies
├── wrangler.jsonc          # Cloudflare Workers deployment config
├── local_server.py         # Flask dev server for local testing
├── index.html              # Reference copy of the website (not deployed from here)
├── CLAUDE.md               # This file — project context for Claude Code
├── README.md               # Setup and deployment instructions
└── src/
    ├── __init__.py
    ├── worker.py           # Cloudflare Workers entry point (JS interop via Pyodide)
    ├── bot.py              # Core logic: confirmation flow, rollback, conversation history
    ├── claude_client.py    # Claude API integration with strict update-only prompt
    ├── telegram.py         # Telegram Bot API — parse updates, send messages
    ├── github_client.py    # GitHub Contents API — read/write index.html
    └── html_validator.py   # Pydantic model ensuring HTML integrity
```

## Key Modules

### src/worker.py
Cloudflare Workers Python entry point. Defines `on_fetch(request, cf_env, ctx)`.
Uses `WorkersEnv` class to adapt CF bindings (secrets, KV) into the interface the bot modules expect.
Background-processes messages via `ctx.waitUntil()` so the webhook returns 200 immediately.
Only handles POST `/webhook` — Telegram does not require GET verification.

### src/bot.py
Orchestrates the conversation flow:
1. Checks if the message is a rollback command (undo/rollback/revert) → restores previous HTML.
2. Checks KV for a pending confirmation for this chat ID → handles YES/NO.
3. If new request: fetches current HTML from GitHub → loads conversation history → sends to Claude → stores pending change in KV → asks user to confirm.

Manages three KV key patterns per chat ID:
- `pending:{chat_id}` — pending HTML + summary awaiting YES/NO (1-hour TTL).
- `rollback:{chat_id}` — snapshot of the HTML before the last applied change (24-hour TTL).
- `history:{chat_id}` — last 20 conversation messages for Claude context (24-hour TTL).

### src/claude_client.py
Sends the current HTML + user message to Claude API (claude-sonnet-4-20250514).
When conversation history exists, builds a multi-turn message array so Claude understands follow-ups like "also add..." or "change that to...".
System prompt enforces strict rules:
- Only modify what is explicitly requested.
- Never remove content unless asked.
- Never add content unless asked.
- Use conversation history for context on follow-up requests.
- Respond with structured JSON: `{action, summary, updated_html}` or `{action, message}`.

### src/telegram.py
- `parse_incoming_message()` — extracts chat_id and text from Telegram update payload.
- `send_message()` — sends a text reply via the Telegram Bot API with Markdown formatting.

### src/github_client.py
Uses the GitHub Contents API to:
- `get_current_html()` — fetch index.html + its SHA from the website repo.
- `update_html()` — commit updated index.html to the repo (Cloudflare Pages auto-deploys).

### src/html_validator.py
Pydantic `ValidatedHTML` model with three validators:
- `must_be_complete_html` — checks DOCTYPE, html, head, body tags.
- `must_have_required_sections` — ensures all 9 section IDs survive (home, about, api, formulations, contrast, devices, chemicals, animal, contact).
- `must_have_sidebar_and_footer` — ensures sidebar-wrapper and footer-contact exist.

## Environment Variables

All secrets are loaded from `.env` locally or from Cloudflare secrets in production.

| Variable | Description |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Telegram bot token from BotFather |
| `CLAUDE_API_KEY` | Anthropic API key |
| `GITHUB_TOKEN` | GitHub personal access token (repo write access) |
| `GITHUB_REPO_OWNER` | GitHub username/org owning the website repo |
| `GITHUB_REPO_NAME` | Name of the website HTML repo |
| `GITHUB_FILE_PATH` | Path to the HTML file in the repo (default: `index.html`) |
| `GITHUB_BRANCH` | Branch to update (default: `main`) |

## Design Decisions

- **No database** — Cloudflare KV stores three lightweight things: pending confirmations (1hr TTL), rollback snapshots (24hr TTL), and conversation history (24hr TTL, last 20 messages). All expire automatically.
- **One-level rollback** — before applying any change, the current HTML is saved to KV. User can send "undo" to restore it. Only the most recent change can be undone.
- **Conversation history** — last 20 messages per chat ID are stored in KV and sent to Claude as multi-turn context, enabling natural follow-up requests.
- **Environment abstraction** — `WorkersEnv` (production) and `LocalEnv` (dev) both implement the same `http_request`, `kv_get/put/delete` interface so all business logic is runtime-agnostic.
- **Two repos** — this repo holds the bot application; a separate repo holds the website HTML. Cloudflare Pages watches the website repo for auto-deploy.
- **Confirmation required** — every change must be confirmed with YES/NO before it is applied, preventing accidental updates.
- **Pydantic validation** — HTML is validated before every push to prevent broken deploys.
- **Simple scope** — the bot only handles textual updates (products, descriptions, contact info). Anything requiring a database, new pages, or complex features is explicitly out of scope.
