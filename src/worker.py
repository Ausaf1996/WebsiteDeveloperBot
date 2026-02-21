"""Cloudflare Workers Python entry point.

This module handles incoming HTTP requests in the Cloudflare Workers runtime.
It bridges the JS-based Workers environment to the Python bot logic.
"""

import json
from js import Response, Object, Headers, URL, fetch
from pyodide.ffi import to_js

from src.bot import handle_message
from src.telegram import parse_incoming_message


class WorkersEnv:
    """Adapts Cloudflare Workers env bindings into the interface expected by bot modules."""

    def __init__(self, cf_env):
        self._cf = cf_env
        self.telegram_bot_token = str(cf_env.TELEGRAM_BOT_TOKEN)
        self.claude_api_key = str(cf_env.CLAUDE_API_KEY)
        self.github_token = str(cf_env.GITHUB_TOKEN)
        self.github_repo_owner = str(cf_env.GITHUB_REPO_OWNER)
        self.github_repo_name = str(cf_env.GITHUB_REPO_NAME)
        self.github_file_path = str(getattr(cf_env, "GITHUB_FILE_PATH", "index.html"))
        self.github_branch = str(getattr(cf_env, "GITHUB_BRANCH", "main"))

    async def http_request(self, method, url, headers=None, body=None):
        """Make an HTTP request using the Workers global fetch API."""
        options = {"method": method}

        if headers:
            options["headers"] = headers
        if body:
            if isinstance(body, dict):
                options["body"] = json.dumps(body)
            else:
                options["body"] = body

        js_options = to_js(options, dict_converter=Object.fromEntries)
        response = await fetch(url, js_options)
        text = await response.text()
        return {"status": response.status, "text": str(text)}

    async def kv_get(self, key):
        result = await self._cf.PENDING_CHANGES.get(key)
        if result:
            return str(result)
        return None

    async def kv_put(self, key, value, ttl=None):
        opts = Object.fromEntries(to_js({"expirationTtl": ttl})) if ttl else None
        if opts:
            await self._cf.PENDING_CHANGES.put(key, value, opts)
        else:
            await self._cf.PENDING_CHANGES.put(key, value)

    async def kv_delete(self, key):
        await self._cf.PENDING_CHANGES.delete(key)


async def on_fetch(request, cf_env, ctx):
    """Cloudflare Workers fetch handler — main entry point."""
    url_str = str(request.url)
    method = str(request.method)

    env = WorkersEnv(cf_env)

    if "/webhook" not in url_str:
        return Response.new("Not Found", status=404)

    # --- POST: incoming Telegram update ---
    if method == "POST":
        body_text = await request.text()
        body = json.loads(str(body_text))

        chat_id, text = parse_incoming_message(body)

        if chat_id and text:
            # Process in background so we return 200 quickly
            ctx.waitUntil(_process_message(env, chat_id, text))

        # Always return 200 to acknowledge the webhook
        return Response.new("OK", status=200)

    return Response.new("Method Not Allowed", status=405)


async def _process_message(env, chat_id, text):
    """Background task to process the message without blocking the webhook response."""
    try:
        await handle_message(env, chat_id, text)
    except Exception as e:
        # Log the error (visible in Cloudflare Workers logs)
        print(f"Error processing message from {chat_id}: {e}")
