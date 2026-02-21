"""Cloudflare Workers Python entry point.

This module handles incoming HTTP requests in the Cloudflare Workers runtime.
It bridges the JS-based Workers environment to the Python bot logic.
"""

import json
from js import Response, Object, Headers, URL, fetch
from pyodide.ffi import to_js

from src.bot import handle_message
from src.whatsapp import parse_incoming_message, verify_webhook


class WorkersEnv:
    """Adapts Cloudflare Workers env bindings into the interface expected by bot modules."""

    def __init__(self, cf_env):
        self._cf = cf_env
        self.whatsapp_token = str(cf_env.WHATSAPP_TOKEN)
        self.whatsapp_verify_token = str(cf_env.WHATSAPP_VERIFY_TOKEN)
        self.whatsapp_phone_number_id = str(cf_env.WHATSAPP_PHONE_NUMBER_ID)
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

    # --- GET: WhatsApp webhook verification ---
    if method == "GET":
        url_obj = URL.new(url_str)
        params = {
            "hub.mode": str(url_obj.searchParams.get("hub.mode") or ""),
            "hub.verify_token": str(url_obj.searchParams.get("hub.verify_token") or ""),
            "hub.challenge": str(url_obj.searchParams.get("hub.challenge") or ""),
        }
        challenge = verify_webhook(params, env.whatsapp_verify_token)
        if challenge:
            return Response.new(challenge, status=200)
        return Response.new("Forbidden", status=403)

    # --- POST: incoming WhatsApp message ---
    if method == "POST":
        body_text = await request.text()
        body = json.loads(str(body_text))

        phone, text = parse_incoming_message(body)

        if phone and text:
            # Process in background so we return 200 quickly
            ctx.waitUntil(_process_message(env, phone, text))

        # Always return 200 to acknowledge the webhook
        return Response.new("OK", status=200)

    return Response.new("Method Not Allowed", status=405)


async def _process_message(env, phone, text):
    """Background task to process the message without blocking the webhook response."""
    try:
        await handle_message(env, phone, text)
    except Exception as e:
        # Log the error (visible in Cloudflare Workers logs)
        print(f"Error processing message from {phone}: {e}")
