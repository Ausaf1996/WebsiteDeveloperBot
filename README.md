# Website Developer Bot

A WhatsApp bot that lets non-technical users update the [PAN Medical & Industrial Supplies](https://panmedical.pages.dev) website by sending plain-English messages. The bot uses Claude AI to understand requests, modifies the HTML, validates it, and deploys the changes automatically.

## How It Works

```
User sends WhatsApp message
        │  "Add Paracetamol to the Pharmaceuticals section"
        ▼
┌─────────────────────┐
│  Cloudflare Worker   │──► Fetches current website HTML from GitHub
│  (this application)  │──► Sends HTML + request to Claude API
│                      │──► Claude generates updated HTML + summary
│                      │──► Stores pending change, asks user to confirm
└─────────────────────┘
        │  User replies "YES"
        ▼
┌─────────────────────┐
│  Validates HTML      │──► Pydantic checks structure is intact
│  Pushes to GitHub    │──► Commits updated index.html
│  Cloudflare Pages    │──► Auto-deploys from GitHub (already configured)
└─────────────────────┘
        │
        ▼
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

Bot:   I will make these changes:

       Add a new row "Aspirin" with status "Commercial" and regulatory
       documents "IP/USP" to the Pharmaceuticals & API's table.

       Reply YES to confirm or NO to cancel.

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

1. **A Cloudflare account** — free tier works
2. **A WhatsApp Business API account** — via [Meta for Developers](https://developers.facebook.com/)
3. **An Anthropic API key** — from [console.anthropic.com](https://console.anthropic.com/)
4. **A GitHub account** with a **separate repository** that holds your website's `index.html`
5. **Node.js** (v18+) — for the `wrangler` CLI
6. **Python** (3.11+) — for local development

---

## Setup

### 1. Clone and install dependencies

```bash
git clone https://github.com/your-username/WebsiteDeveloperBot.git
cd WebsiteDeveloperBot

# Install Python dependencies for local development
pip install pydantic requests flask python-dotenv

# Install wrangler CLI for Cloudflare deployment
npm install -g wrangler
```

### 2. Create the website repository

This bot updates a **separate** GitHub repository that holds the website HTML. Cloudflare Pages watches that repo and auto-deploys on every push.

1. Create a new GitHub repo (e.g., `pan-medical-website`)
2. Add your `index.html` to it and push
3. In Cloudflare Dashboard → Pages → Create a project → Connect to Git → select that repo
4. Set build output directory to `/` (the repo root), no build command needed
5. Deploy — your site is now live at `your-project.pages.dev`

### 3. Set up WhatsApp Business API

1. Go to [Meta for Developers](https://developers.facebook.com/) and create an app
2. Add the **WhatsApp** product to your app
3. In WhatsApp → Getting Started, note down:
   - **Phone Number ID** — this is `WHATSAPP_PHONE_NUMBER_ID`
   - **Temporary Access Token** — this is `WHATSAPP_TOKEN` (for production, generate a permanent token)
4. Choose a **verify token** — any string you pick, e.g., `my-secret-verify-token`. This is `WHATSAPP_VERIFY_TOKEN`
5. You'll configure the webhook URL after deploying (Step 6)

### 4. Get API keys

| Key | Where to get it |
|---|---|
| `CLAUDE_API_KEY` | [console.anthropic.com](https://console.anthropic.com/) → API Keys |
| `GITHUB_TOKEN` | [github.com/settings/tokens](https://github.com/settings/tokens) → Generate new token (classic) → select `repo` scope |

### 5. Configure environment

#### For local development

```bash
cp .env.example .env
```

Edit `.env` and fill in all the values:

```
WHATSAPP_TOKEN=EAAxxxxxxx...
WHATSAPP_VERIFY_TOKEN=my-secret-verify-token
WHATSAPP_PHONE_NUMBER_ID=123456789012345
CLAUDE_API_KEY=sk-ant-xxxxxxx...
GITHUB_TOKEN=ghp_xxxxxxx...
GITHUB_REPO_OWNER=your-github-username
GITHUB_REPO_NAME=pan-medical-website
GITHUB_FILE_PATH=index.html
GITHUB_BRANCH=main
```

#### For Cloudflare (production)

```bash
# Create the KV namespace for pending confirmations
npx wrangler kv namespace create PENDING_CHANGES
```

This outputs an ID — paste it into `wrangler.jsonc` replacing `your_kv_namespace_id`.

Then add each secret:

```bash
npx wrangler secret put WHATSAPP_TOKEN
npx wrangler secret put WHATSAPP_VERIFY_TOKEN
npx wrangler secret put WHATSAPP_PHONE_NUMBER_ID
npx wrangler secret put CLAUDE_API_KEY
npx wrangler secret put GITHUB_TOKEN
npx wrangler secret put GITHUB_REPO_OWNER
npx wrangler secret put GITHUB_REPO_NAME
```

Each command will prompt you to paste the value.

### 6. Deploy to Cloudflare Workers

```bash
# Login to Cloudflare (first time only)
npx wrangler login

# Deploy
npx wrangler deploy
```

After deploying, wrangler will print the Worker URL, e.g.:
```
https://website-developer-bot.your-subdomain.workers.dev
```

### 7. Configure the WhatsApp webhook

1. Go to Meta for Developers → Your App → WhatsApp → Configuration
2. Set **Callback URL** to: `https://website-developer-bot.your-subdomain.workers.dev/webhook`
3. Set **Verify Token** to the same value as your `WHATSAPP_VERIFY_TOKEN`
4. Subscribe to the **messages** webhook field
5. Click **Verify and Save**

The bot is now live. Send a WhatsApp message to your business number to test.

---

## Local Development

For testing locally before deploying:

```bash
# Start the local server
python local_server.py
```

The server runs at `http://localhost:8787`. To receive WhatsApp webhooks locally, expose it with [ngrok](https://ngrok.com/):

```bash
ngrok http 8787
```

Use the ngrok HTTPS URL as your webhook URL in the Meta dashboard (temporarily, for testing).

---

## Project Structure

```
WebsiteDeveloperBot/
├── .gitignore              # Excludes .env, __pycache__, .wrangler
├── .env.example            # Template for local environment variables
├── pyproject.toml          # Python project config and dependencies
├── wrangler.jsonc          # Cloudflare Workers deployment config
├── local_server.py         # Flask server for local testing
├── index.html              # Reference copy of the website (not deployed from here)
├── CLAUDE.md               # Project context for Claude Code
├── README.md               # This file
└── src/
    ├── __init__.py
    ├── worker.py           # Cloudflare Workers entry point
    ├── bot.py              # Core logic: message routing, confirmation flow
    ├── claude_client.py    # Claude API — understands requests, generates HTML
    ├── github_client.py    # GitHub API — fetches and pushes index.html
    ├── html_validator.py   # Pydantic validation — ensures HTML integrity
    └── whatsapp.py         # WhatsApp API — webhook handling, message sending
```

### Module Responsibilities

| Module | What it does |
|---|---|
| `src/worker.py` | Cloudflare Workers entry point. Routes `/webhook` GET (verification) and POST (messages). Uses `ctx.waitUntil()` to process messages in the background. |
| `src/bot.py` | Orchestrates the full flow: rollback commands, pending confirmations, new requests, conversation history. Manages three KV keys per phone: `pending:`, `rollback:`, `history:`. |
| `src/claude_client.py` | Sends current HTML + conversation history + user message to Claude. Builds multi-turn messages so Claude understands follow-ups. |
| `src/github_client.py` | Reads and writes `index.html` in the website GitHub repo using the Contents API. |
| `src/html_validator.py` | Pydantic model that validates every generated HTML before deployment — checks for DOCTYPE, all 9 page sections, sidebar, and footer. |
| `src/whatsapp.py` | Parses incoming webhook payloads, sends text replies, handles the webhook verification handshake. |
| `local_server.py` | Flask app that mimics the Worker locally. Uses `requests` library for HTTP and in-memory dict for KV. |

---

## What the Bot Can Do

- Add or remove products from any section (Pharmaceuticals, Veterinary, Chemicals, etc.)
- Update product names, descriptions, statuses, or regulatory documents
- Modify text content (headings, descriptions, about us, etc.)
- Update contact information
- **Undo the last change** — send "undo", "rollback", or "revert" to restore the previous version
- **Follow-up requests** — the bot remembers your recent conversation (last 20 messages, 24 hours) so you can say things like "also add...", "change that to...", or "remove the one I just added"

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

Before every confirmed update, the bot saves the current HTML to KV as a rollback snapshot (24-hour TTL). If the user sends **UNDO**, **ROLLBACK**, or **REVERT**, the bot restores the previous version and pushes it to GitHub.

- Only the **most recent** change can be undone (one level deep).
- The rollback snapshot expires after 24 hours.
- After a rollback, there is no further undo available until a new change is applied.

### Conversation History

The bot stores the last 20 messages (user + bot) per phone number in KV (24-hour TTL). This history is sent to Claude as multi-turn context, enabling:

- **Follow-up requests**: "Also add Ibuprofen to that same section"
- **Corrections**: "Actually change the status to Lab Scale instead"
- **References**: "Remove the product I just added"

History resets automatically after 24 hours of inactivity.

---

## Troubleshooting

### Webhook verification fails
- Make sure `WHATSAPP_VERIFY_TOKEN` matches exactly between your `.env`/Cloudflare secrets and the Meta dashboard.

### Bot doesn't respond
- Check Cloudflare Workers logs: `npx wrangler tail`
- Verify all secrets are set: `npx wrangler secret list`
- Ensure the WhatsApp webhook is subscribed to the `messages` field.

### HTML validation fails after an update
- This means Claude's output was missing a required section. The bot will ask the user to try again. If it keeps failing, the Claude prompt in `src/claude_client.py` may need adjustment for edge cases.

### Changes don't appear on the website
- Confirm Cloudflare Pages is connected to the correct GitHub repo and branch.
- Check the GitHub repo to see if the commit was pushed successfully.
- Cloudflare Pages typically deploys within 1-2 minutes of a push.

---

## Two-Repo Setup Explained

This project uses **two separate GitHub repositories**:

| Repo | Purpose | Managed by |
|---|---|---|
| `WebsiteDeveloperBot` (this repo) | The bot application code | You (the developer) |
| `pan-medical-website` (or your chosen name) | The website `index.html` | The bot (via GitHub API) |

Cloudflare Pages watches the **website repo** and auto-deploys whenever the bot pushes an updated `index.html`. The bot application itself runs on **Cloudflare Workers** (deployed separately via `wrangler deploy`).
