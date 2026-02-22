"""Flask server for local development and Google Cloud Run production.

Local development:
    pip install .
    cp .env.example .env   # then fill in your keys
    python local_server.py

Cloud Run:
    Deployed via Dockerfile with gunicorn.
    Environment variables set via --set-env-vars on deploy.
"""

import asyncio
import json
import os
import threading

import requests as req_lib
from dotenv import load_dotenv
from flask import Flask, request, Response

from src.bot import handle_message, get_logs, log_error
from src.telegram import parse_incoming_message, send_message

load_dotenv()

app = Flask(__name__)


class LocalEnv:
    """Environment adapter — uses requests library and in-memory KV."""

    def __init__(self):
        self.telegram_bot_token = os.environ["TELEGRAM_BOT_TOKEN"]
        self.claude_api_key = os.environ["CLAUDE_API_KEY"]
        self.github_token = os.environ["GITHUB_TOKEN"]
        self.github_repo_owner = os.environ["GITHUB_REPO_OWNER"]
        self.github_repo_name = os.environ["GITHUB_REPO_NAME"]
        self.github_file_path = os.environ.get("GITHUB_FILE_PATH", "index.html")
        self.github_branch = os.environ.get("GITHUB_BRANCH", "main")
        self._kv = {}

    async def http_request(self, method, url, headers=None, body=None):
        """Make HTTP requests using the requests library."""
        kwargs = {"headers": headers}
        if body:
            if isinstance(body, dict):
                kwargs["json"] = body
            else:
                kwargs["data"] = body

        resp = req_lib.request(method, url, **kwargs)
        return {"status": resp.status_code, "text": resp.text}

    async def kv_get(self, key):
        return self._kv.get(key)

    async def kv_put(self, key, value, ttl=None):
        self._kv[key] = value

    async def kv_delete(self, key):
        self._kv.pop(key, None)


env = LocalEnv()


def _process_in_background(chat_id, text):
    """Run handle_message in a new event loop, with error logging."""
    try:
        asyncio.run(handle_message(env, chat_id, text))
    except Exception as e:
        print(f"[ERROR] {chat_id}: {e}")
        import traceback
        traceback.print_exc()
        try:
            asyncio.run(log_error(env, chat_id, "unhandled_exception", str(e)))
        except Exception:
            pass
        try:
            asyncio.run(send_message(
                env, chat_id,
                "Sorry, something went wrong while processing your message. Please try again."
            ))
        except Exception:
            print(f"Failed to send error message to {chat_id}")


@app.route("/webhook", methods=["GET", "POST"])
def webhook_handler():
    """Handle incoming Telegram updates (POST) and log/usage queries (GET)."""

    if request.method == "GET":
        # /webhook?logs — return error logs
        if request.args.get("logs") is not None:
            logs = asyncio.run(get_logs(env))
            return Response(json.dumps(logs, indent=2), mimetype="application/json")

        # /webhook?usage — return usage logs
        if request.args.get("usage") is not None:
            raw = asyncio.run(env.kv_get("usage_log"))
            usage_logs = json.loads(raw) if raw else []
            return Response(json.dumps(usage_logs, indent=2), mimetype="application/json")

        return "OK", 200

    # POST: incoming Telegram update
    body = request.get_json()
    chat_id, text = parse_incoming_message(body)

    if chat_id and text:
        thread = threading.Thread(target=_process_in_background, args=(chat_id, text))
        thread.start()

    return "OK", 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8787))
    print(f"Starting server on http://localhost:{port}")
    print(f"Webhook URL: http://localhost:{port}/webhook")
    print()
    print(f"Use ngrok to expose: ngrok http {port}")
    print("Then set Telegram webhook:")
    print(f"  curl https://api.telegram.org/bot<TOKEN>/setWebhook?url=https://<NGROK_URL>/webhook")
    app.run(host="0.0.0.0", port=port, debug=True)
