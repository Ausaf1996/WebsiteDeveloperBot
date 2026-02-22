import json

try:
    from src import claude_client, github_client, telegram
    from src.html_validator import ValidatedHTML
except ModuleNotFoundError:
    import claude_client, github_client, telegram
    from html_validator import ValidatedHTML

MAX_HISTORY_MESSAGES = 20
HISTORY_TTL = 86400  # 24 hours
LOG_TTL = 86400  # 24 hours
MAX_LOG_ENTRIES = 50


async def log_error(env, chat_id, error_type, detail):
    """Append an error entry to the KV-based error log (24h TTL)."""
    try:
        raw = await env.kv_get("error_log")
        logs = json.loads(raw) if raw else []
    except Exception:
        logs = []

    # Use a simple incrementing approach for timestamp
    import time
    logs.append({
        "ts": int(time.time()),
        "chat_id": str(chat_id),
        "type": error_type,
        "detail": str(detail)[:500],
    })

    # Keep only the most recent entries
    if len(logs) > MAX_LOG_ENTRIES:
        logs = logs[-MAX_LOG_ENTRIES:]

    await env.kv_put("error_log", json.dumps(logs), ttl=LOG_TTL)


async def get_logs(env):
    """Retrieve all error log entries from KV."""
    raw = await env.kv_get("error_log")
    if raw:
        return json.loads(raw)
    return []

# Chat IDs allowed to use the bot. Add more IDs to this list.
ALLOWED_CHAT_IDS = [
    "8490004746",
    "1897441414"
]


async def handle_message(env, chat_id, message_text):
    """Main entry point — route an incoming message through the bot logic."""
    if ALLOWED_CHAT_IDS and chat_id not in ALLOWED_CHAT_IDS:
        await telegram.send_message(
            env, chat_id, "Sorry, you are not authorized to use this bot."
        )
        return

    normalized = message_text.strip().lower()

    # Handle rollback command
    if normalized in {"undo", "rollback", "revert", "go back", "undo last change"}:
        await _handle_rollback(env, chat_id)
        return

    # Check if there is a pending change awaiting confirmation
    pending = await env.kv_get(f"pending:{chat_id}")

    if pending:
        await _handle_confirmation(env, chat_id, message_text, pending)
    else:
        await _handle_new_request(env, chat_id, message_text)


async def _handle_rollback(env, chat_id):
    """Restore the previous version of the website HTML."""
    rollback_json = await env.kv_get(f"rollback:{chat_id}")

    if not rollback_json:
        await telegram.send_message(
            env,
            chat_id,
            "There is nothing to undo. I can only undo the most recent change, "
            "and only if it was made recently.",
        )
        return

    rollback_data = json.loads(rollback_json)
    previous_html = rollback_data["html"]
    original_summary = rollback_data["summary"]

    # Validate before pushing
    try:
        validated = ValidatedHTML(content=previous_html)
    except Exception:
        await env.kv_delete(f"rollback:{chat_id}")
        await telegram.send_message(
            env,
            chat_id,
            "Sorry, the previous version could not be restored. "
            "Please describe what you would like changed instead.",
        )
        return

    success, _ = await github_client.update_html(
        env, validated.content, f"Rollback: undo '{original_summary}'"
    )

    await env.kv_delete(f"rollback:{chat_id}")

    if success:
        # Record this rollback in conversation history
        await _append_history(env, chat_id, "user", "Undo last change")
        await _append_history(
            env, chat_id, "bot",
            f"Rolled back the last change: \"{original_summary}\""
        )
        await telegram.send_message(
            env,
            chat_id,
            f"Done! The last change has been undone.\n\n"
            f"*Reverted:* {original_summary}\n\n"
            f"The website will refresh in a minute or two.",
        )
    else:
        await telegram.send_message(
            env,
            chat_id,
            "Sorry, there was an error restoring the previous version. "
            "Please try again later.",
        )


async def _handle_confirmation(env, chat_id, message_text, pending_json):
    """User is replying to a pending confirmation prompt."""
    normalized = message_text.strip().lower()

    yes_words = {"yes", "y", "ok", "confirm", "go ahead", "do it", "haan", "ha", "sure"}
    no_words = {"no", "n", "cancel", "nahi", "nah", "stop"}

    if normalized in yes_words:
        pending = json.loads(pending_json)
        new_html = pending["html"]
        summary = pending["summary"]

        # Validate HTML with Pydantic before pushing
        try:
            validated = ValidatedHTML(content=new_html)
        except Exception:
            await env.kv_delete(f"pending:{chat_id}")
            await telegram.send_message(
                env,
                chat_id,
                "Sorry, the update could not be applied because the generated HTML "
                "did not pass validation checks. Please try your request again.",
            )
            return

        # Save current HTML for rollback before pushing the new one
        current_html, _ = await github_client.get_current_html(env)
        if current_html:
            rollback_data = json.dumps({"html": current_html, "summary": summary})
            await env.kv_put(f"rollback:{chat_id}", rollback_data, ttl=86400)

        # Push to GitHub (Cloudflare Pages auto-deploys from this repo)
        success, msg = await github_client.update_html(
            env, validated.content, f"Website update: {summary}"
        )

        await env.kv_delete(f"pending:{chat_id}")

        if success:
            # Record in conversation history
            await _append_history(env, chat_id, "bot", f"Applied update: {summary}")

            await telegram.send_message(
                env,
                chat_id,
                f"Done! The website has been updated.\n\n"
                f"*Changes made:* {summary}\n\n"
                f"The website will refresh automatically in a minute or two.\n\n"
                f"If you don't like this change, send *UNDO* to revert it.",
            )
        else:
            await telegram.send_message(
                env,
                chat_id,
                "Sorry, there was an error updating the website. Please try again later.",
            )

    elif normalized in no_words:
        await env.kv_delete(f"pending:{chat_id}")
        await _append_history(env, chat_id, "bot", "User cancelled the pending change.")
        await telegram.send_message(
            env,
            chat_id,
            "No problem! The changes have been cancelled. "
            "Send me another request whenever you are ready.",
        )

    else:
        # User sent something else while a confirmation is pending
        await telegram.send_message(
            env,
            chat_id,
            "I have a pending update waiting for your confirmation.\n\n"
            "Reply *YES* to apply the changes or *NO* to cancel.",
        )


async def _log_usage(env, chat_id, usage, user_message):
    """Log Claude API token usage to KV and console."""
    if not usage:
        return
    input_tokens = usage.get("input_tokens", 0)
    output_tokens = usage.get("output_tokens", 0)
    print(f"  Tokens: {input_tokens} in / {output_tokens} out / {input_tokens + output_tokens} total")

    import time
    try:
        raw = await env.kv_get("usage_log")
        logs = json.loads(raw) if raw else []
    except Exception:
        logs = []

    logs.append({
        "ts": int(time.time()),
        "chat_id": str(chat_id),
        "message": user_message[:100],
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
    })

    if len(logs) > MAX_LOG_ENTRIES:
        logs = logs[-MAX_LOG_ENTRIES:]

    await env.kv_put("usage_log", json.dumps(logs), ttl=LOG_TTL)


async def _handle_new_request(env, chat_id, message_text):
    """Process a brand-new update request from the user."""
    print(f"[USER {chat_id}] {message_text}")

    # Acknowledge immediately so the user knows the bot is working
    await telegram.send_message(env, chat_id, "working on it...")

    # Record user message in conversation history
    await _append_history(env, chat_id, "user", message_text)

    # Fetch the current website HTML from GitHub
    current_html, _ = await github_client.get_current_html(env)

    if current_html is None:
        await log_error(env, chat_id, "github_fetch_failed", "Could not fetch current HTML from GitHub")
        await telegram.send_message(
            env,
            chat_id,
            "Sorry, I could not fetch the current website right now. Please try again later.",
        )
        return

    # Load conversation history for context
    history = await _get_history(env, chat_id)

    # Ask Claude to process the request
    result = await claude_client.process_request(
        env, current_html, message_text, history, chat_id=chat_id
    )

    usage = result.pop("_usage", None)
    action = result.get("action")

    if action == "update":
        # Store the pending change in KV for confirmation
        pending = json.dumps({
            "html": result["updated_html"],
            "summary": result["summary"],
        })
        await env.kv_put(f"pending:{chat_id}", pending, ttl=3600)

        # Record bot response in history
        await _append_history(
            env, chat_id, "bot",
            f"Proposed update: {result['summary']} (waiting for confirmation)"
        )

        reply = (
            f"I will make these changes:\n\n"
            f"{result['summary']}\n\n"
            f"Reply *YES* to confirm or *NO* to cancel."
        )
        await telegram.send_message(env, chat_id, reply)
        print(f"[BOT  {chat_id}] {result['summary']}")
        await _log_usage(env, chat_id, usage, message_text)

    elif action in ("clarify", "out_of_scope", "off_topic"):
        await _append_history(env, chat_id, "bot", result["message"])
        await telegram.send_message(env, chat_id, result["message"])
        print(f"[BOT  {chat_id}] {result['message']}")
        await _log_usage(env, chat_id, usage, message_text)

    else:
        msg = result.get("message", "Sorry, something went wrong. Please try again.")
        await _append_history(env, chat_id, "bot", msg)
        await telegram.send_message(env, chat_id, msg)
        print(f"[BOT  {chat_id}] {msg}")
        await _log_usage(env, chat_id, usage, message_text)


# ── Conversation history helpers ──────────────────────────────────────


async def _get_history(env, chat_id):
    """Load conversation history for this phone number from KV.

    Returns a list of {"role": "user"|"bot", "text": "..."} dicts.
    """
    raw = await env.kv_get(f"history:{chat_id}")
    if raw:
        return json.loads(raw)
    return []


async def _append_history(env, chat_id, role, text):
    """Append a message to the conversation history in KV.

    Keeps only the last MAX_HISTORY_MESSAGES entries.
    """
    history = await _get_history(env, chat_id)
    history.append({"role": role, "text": text})

    # Trim to the most recent messages
    if len(history) > MAX_HISTORY_MESSAGES:
        history = history[-MAX_HISTORY_MESSAGES:]

    await env.kv_put(
        f"history:{chat_id}", json.dumps(history), ttl=HISTORY_TTL
    )
