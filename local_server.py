"""Local development server.

Run this for local testing:
    pip install .
    cp .env.example .env   # then fill in your keys
    python local_server.py

The server listens on http://localhost:8787/webhook
Use a tool like ngrok to expose it for Telegram webhook:
    ngrok http 8787
Then set the webhook:
    curl https://api.telegram.org/bot<YOUR_TOKEN>/setWebhook?url=https://<NGROK_URL>/webhook
"""

import asyncio
import json
import os
import threading

import requests as req_lib
from dotenv import load_dotenv
from flask import Flask, request

from src.bot import handle_message
from src.telegram import parse_incoming_message

load_dotenv()

app = Flask(__name__)


class LocalEnv:
    """Local development environment — uses requests library and in-memory KV."""

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


@app.route("/webhook", methods=["POST"])
def webhook_handler():
    """Receive incoming Telegram updates."""
    body = request.get_json()
    chat_id, text = parse_incoming_message(body)

    if chat_id and text:
        thread = threading.Thread(target=_process_in_background, args=(chat_id, text))
        thread.start()

    return "OK", 200


if __name__ == "__main__":
    print("Starting local development server on http://localhost:8787")
    print("Webhook URL: http://localhost:8787/webhook")
    print()
    print("Use ngrok to expose: ngrok http 8787")
    print("Then set Telegram webhook:")
    print(f"  curl https://api.telegram.org/bot<TOKEN>/setWebhook?url=https://<NGROK_URL>/webhook")
    app.run(host="0.0.0.0", port=8787, debug=True)
