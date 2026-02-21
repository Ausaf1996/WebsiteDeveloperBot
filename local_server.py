"""Local development server.

Run this for local testing:
    pip install -r requirements.txt
    cp .env.example .env   # then fill in your keys
    python local_server.py

The server listens on http://localhost:8787/webhook
Use a tool like ngrok to expose it for WhatsApp webhook testing:
    ngrok http 8787
"""

import asyncio
import json
import os
import threading

import requests as req_lib
from dotenv import load_dotenv
from flask import Flask, request

from src.bot import handle_message
from src.whatsapp import parse_incoming_message, verify_webhook

load_dotenv()

app = Flask(__name__)


class LocalEnv:
    """Local development environment — uses requests library and in-memory KV."""

    def __init__(self):
        self.whatsapp_token = os.environ["WHATSAPP_TOKEN"]
        self.whatsapp_verify_token = os.environ["WHATSAPP_VERIFY_TOKEN"]
        self.whatsapp_phone_number_id = os.environ["WHATSAPP_PHONE_NUMBER_ID"]
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


@app.route("/webhook", methods=["GET"])
def webhook_verify():
    """WhatsApp webhook verification endpoint."""
    challenge = verify_webhook(request.args.to_dict(), env.whatsapp_verify_token)
    if challenge:
        return challenge, 200
    return "Forbidden", 403


@app.route("/webhook", methods=["POST"])
def webhook_handler():
    """Receive incoming WhatsApp messages."""
    body = request.get_json()
    phone, text = parse_incoming_message(body)

    if phone and text:
        # Process in a background thread so we return 200 immediately
        thread = threading.Thread(
            target=lambda: asyncio.run(handle_message(env, phone, text))
        )
        thread.start()

    return "OK", 200


if __name__ == "__main__":
    print("Starting local development server on http://localhost:8787")
    print("Webhook URL: http://localhost:8787/webhook")
    print("Use ngrok to expose: ngrok http 8787")
    app.run(host="0.0.0.0", port=8787, debug=True)
