import json

from src import claude_client, github_client, telegram
from src.html_validator import ValidatedHTML

MAX_HISTORY_MESSAGES = 20
HISTORY_TTL = 86400  # 24 hours


async def handle_message(env, phone_number, message_text):
    """Main entry point — route an incoming message through the bot logic."""
    normalized = message_text.strip().lower()

    # Handle rollback command
    if normalized in {"undo", "rollback", "revert", "go back", "undo last change"}:
        await _handle_rollback(env, phone_number)
        return

    # Check if there is a pending change awaiting confirmation
    pending = await env.kv_get(f"pending:{phone_number}")

    if pending:
        await _handle_confirmation(env, phone_number, message_text, pending)
    else:
        await _handle_new_request(env, phone_number, message_text)


async def _handle_rollback(env, phone_number):
    """Restore the previous version of the website HTML."""
    rollback_json = await env.kv_get(f"rollback:{phone_number}")

    if not rollback_json:
        await telegram.send_message(
            env,
            phone_number,
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
        await env.kv_delete(f"rollback:{phone_number}")
        await telegram.send_message(
            env,
            phone_number,
            "Sorry, the previous version could not be restored. "
            "Please describe what you would like changed instead.",
        )
        return

    success, _ = await github_client.update_html(
        env, validated.content, f"Rollback: undo '{original_summary}'"
    )

    await env.kv_delete(f"rollback:{phone_number}")

    if success:
        # Record this rollback in conversation history
        await _append_history(env, phone_number, "user", "Undo last change")
        await _append_history(
            env, phone_number, "bot",
            f"Rolled back the last change: \"{original_summary}\""
        )
        await telegram.send_message(
            env,
            phone_number,
            f"Done! The last change has been undone.\n\n"
            f"*Reverted:* {original_summary}\n\n"
            f"The website will refresh in a minute or two.",
        )
    else:
        await telegram.send_message(
            env,
            phone_number,
            "Sorry, there was an error restoring the previous version. "
            "Please try again later.",
        )


async def _handle_confirmation(env, phone_number, message_text, pending_json):
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
            await env.kv_delete(f"pending:{phone_number}")
            await telegram.send_message(
                env,
                phone_number,
                "Sorry, the update could not be applied because the generated HTML "
                "did not pass validation checks. Please try your request again.",
            )
            return

        # Save current HTML for rollback before pushing the new one
        current_html, _ = await github_client.get_current_html(env)
        if current_html:
            rollback_data = json.dumps({"html": current_html, "summary": summary})
            await env.kv_put(f"rollback:{phone_number}", rollback_data, ttl=86400)

        # Push to GitHub (Cloudflare Pages auto-deploys from this repo)
        success, msg = await github_client.update_html(
            env, validated.content, f"Website update: {summary}"
        )

        await env.kv_delete(f"pending:{phone_number}")

        if success:
            # Record in conversation history
            await _append_history(env, phone_number, "bot", f"Applied update: {summary}")

            await telegram.send_message(
                env,
                phone_number,
                f"Done! The website has been updated.\n\n"
                f"*Changes made:* {summary}\n\n"
                f"The website will refresh automatically in a minute or two.\n\n"
                f"If you don't like this change, send *UNDO* to revert it.",
            )
        else:
            await telegram.send_message(
                env,
                phone_number,
                "Sorry, there was an error updating the website. Please try again later.",
            )

    elif normalized in no_words:
        await env.kv_delete(f"pending:{phone_number}")
        await _append_history(env, phone_number, "bot", "User cancelled the pending change.")
        await telegram.send_message(
            env,
            phone_number,
            "No problem! The changes have been cancelled. "
            "Send me another request whenever you are ready.",
        )

    else:
        # User sent something else while a confirmation is pending
        await telegram.send_message(
            env,
            phone_number,
            "I have a pending update waiting for your confirmation.\n\n"
            "Reply *YES* to apply the changes or *NO* to cancel.",
        )


async def _handle_new_request(env, phone_number, message_text):
    """Process a brand-new update request from the user."""
    # Record user message in conversation history
    await _append_history(env, phone_number, "user", message_text)

    # Fetch the current website HTML from GitHub
    current_html, _ = await github_client.get_current_html(env)

    if current_html is None:
        await telegram.send_message(
            env,
            phone_number,
            "Sorry, I could not fetch the current website right now. Please try again later.",
        )
        return

    # Load conversation history for context
    history = await _get_history(env, phone_number)

    # Ask Claude to process the request
    result = await claude_client.process_request(
        env, current_html, message_text, history
    )

    action = result.get("action")

    if action == "update":
        # Store the pending change in KV for confirmation
        pending = json.dumps({
            "html": result["updated_html"],
            "summary": result["summary"],
        })
        await env.kv_put(f"pending:{phone_number}", pending, ttl=3600)

        # Record bot response in history
        await _append_history(
            env, phone_number, "bot",
            f"Proposed update: {result['summary']} (waiting for confirmation)"
        )

        await telegram.send_message(
            env,
            phone_number,
            f"I will make these changes:\n\n"
            f"{result['summary']}\n\n"
            f"Reply *YES* to confirm or *NO* to cancel.",
        )

    elif action in ("clarify", "out_of_scope", "off_topic"):
        await _append_history(env, phone_number, "bot", result["message"])
        await telegram.send_message(env, phone_number, result["message"])

    else:
        msg = result.get("message", "Sorry, something went wrong. Please try again.")
        await _append_history(env, phone_number, "bot", msg)
        await telegram.send_message(env, phone_number, msg)


# ── Conversation history helpers ──────────────────────────────────────


async def _get_history(env, phone_number):
    """Load conversation history for this phone number from KV.

    Returns a list of {"role": "user"|"bot", "text": "..."} dicts.
    """
    raw = await env.kv_get(f"history:{phone_number}")
    if raw:
        return json.loads(raw)
    return []


async def _append_history(env, phone_number, role, text):
    """Append a message to the conversation history in KV.

    Keeps only the last MAX_HISTORY_MESSAGES entries.
    """
    history = await _get_history(env, phone_number)
    history.append({"role": role, "text": text})

    # Trim to the most recent messages
    if len(history) > MAX_HISTORY_MESSAGES:
        history = history[-MAX_HISTORY_MESSAGES:]

    await env.kv_put(
        f"history:{phone_number}", json.dumps(history), ttl=HISTORY_TTL
    )
