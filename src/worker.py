"""Cloudflare Workers Python entry point.

This module handles incoming HTTP requests in the Cloudflare Workers runtime.
It bridges the JS-based Workers environment to the Python bot logic.
"""

import json
from js import Response, Object, Headers, URL, fetch
from pyodide.ffi import to_js, create_proxy

try:
    from src.bot import handle_message, get_logs, log_error
    from src.telegram import parse_incoming_message, send_message
except ModuleNotFoundError:
    from bot import handle_message, get_logs, log_error
    from telegram import parse_incoming_message, send_message


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

    # --- GET /webhook?logs or /webhook?usage: view logs ---
    if method == "GET":
        parsed_url = URL.new(url_str)
        resp_headers = Headers.new(to_js({"Content-Type": "application/json"}, dict_converter=Object.fromEntries))
        if str(parsed_url.searchParams.get("logs")) != "None":
            logs = await get_logs(env)
            return Response.new(json.dumps(logs, indent=2), status=200, headers=resp_headers)
        if str(parsed_url.searchParams.get("usage")) != "None":
            raw = await env.kv_get("usage_log")
            usage_logs = json.loads(raw) if raw else []
            return Response.new(json.dumps(usage_logs, indent=2), status=200, headers=resp_headers)
        return Response.new("OK", status=200)

    # --- POST: incoming Telegram update ---
    if method == "POST":
        body_text = await request.text()
        body = json.loads(str(body_text))

        chat_id, text = parse_incoming_message(body)

        if chat_id and text:
            # Process synchronously — the main handler has no duration limit,
            # unlike waitUntil() which is killed after 30s.
            await _process_message(env, chat_id, text)

        # Return 200 to acknowledge the webhook
        return Response.new("OK", status=200)

    return Response.new("Method Not Allowed", status=405)


async def _process_message(env, chat_id, text):
    """Background task to process the message without blocking the webhook response."""
    try:
        await handle_message(env, chat_id, text)
    except Exception as e:
        print(f"Error processing message from {chat_id}: {e}")
        try:
            await log_error(env, chat_id, "unhandled_exception", str(e))
        except Exception:
            pass
        try:
            await send_message(
                env, chat_id,
                "Sorry, something went wrong while processing your message. Please try again."
            )
        except Exception:
            print(f"Failed to send error message to {chat_id}")
