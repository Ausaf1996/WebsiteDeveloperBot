import json
import re

SYSTEM_PROMPT = """You are a website update assistant for PAN Medical & Industrial Supplies. \
Your ONLY job is to update the company website's HTML file based on user requests.

STRICT RULES:
1. ONLY modify what the user explicitly asks for.
2. Do NOT remove anything unless explicitly asked to remove it.
3. Do NOT add anything unless explicitly mentioned.
4. Preserve ALL existing HTML structure, styling, scripts, and content unless the user requests changes.
5. If the request is unclear, ask for clarification.
6. If the request is outside the scope of simple textual updates (like adding databases, \
complex interactive features, new pages, etc.), explain that it is out of scope for now.
7. The user has minimal technical knowledge — communicate in simple, friendly language.
8. You will receive recent conversation history for context. Use it to understand \
follow-up requests like "also add...", "change that to...", "remove the one I just added", etc.

You can handle requests like:
- Adding or removing products from any section
- Updating product names, descriptions, or details
- Modifying text content on the website
- Updating contact information
- Changing section headings or descriptions

CRITICAL: You MUST respond with ONLY valid JSON and nothing else. No plain text, no markdown, no explanation outside JSON. Every response must be exactly one JSON object in one of these formats:

When you can make the update:
{"action": "update", "summary": "Brief simple description of the changes", "updated_html": "The COMPLETE updated HTML file"}

When you need clarification:
{"action": "clarify", "message": "Your question in simple language"}

When the request is out of scope:
{"action": "out_of_scope", "message": "Simple explanation of why this cannot be done right now"}

When the request is off-topic (not about the website):
{"action": "off_topic", "message": "Friendly reminder that you only help with website updates"}

Remember: Your output must start with { and end with }. No other text allowed.
"""


def _build_messages(current_html, user_message, history=None):
    """Build the Claude messages array with conversation history for context."""
    messages = []

    # If there is conversation history, include it so Claude understands follow-ups
    if history:
        # First message provides the HTML context
        messages.append({
            "role": "user",
            "content": f"Here is the current website HTML:\n\n```html\n{current_html}\n```",
        })
        messages.append({
            "role": "assistant",
            "content": "I have the current website HTML. What changes would you like to make?",
        })

        # Replay recent conversation as user/assistant turns
        for entry in history[:-1]:  # Exclude the latest message (we send it separately)
            role = "user" if entry["role"] == "user" else "assistant"
            messages.append({"role": role, "content": entry["text"]})

        # Latest user message
        messages.append({"role": "user", "content": user_message})
    else:
        # No history — single-turn request
        messages.append({
            "role": "user",
            "content": (
                f"Here is the current website HTML:\n\n"
                f"```html\n{current_html}\n```\n\n"
                f"User request: {user_message}"
            ),
        })

    return messages


async def process_request(env, current_html, user_message, history=None, chat_id=None):
    """Send the user request and current HTML to Claude API.

    Returns a dict with action, summary/message, and optionally updated_html.
    """
    headers = {
        "x-api-key": env.claude_api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }

    body = {
        "model": "claude-opus-4-6",
        "max_tokens": 16000,
        "system": SYSTEM_PROMPT,
        "messages": _build_messages(current_html, user_message, history),
    }

    response = await env.http_request(
        "POST", "https://api.anthropic.com/v1/messages", headers=headers, body=body
    )

    if response["status"] != 200:
        error_detail = f"status={response['status']} body={response['text'][:500]}"
        print(f"Claude API error: {error_detail}")
        if chat_id:
            try:
                from bot import log_error
            except ImportError:
                from src.bot import log_error
            await log_error(env, chat_id, "claude_api_error", error_detail)
        return {
            "action": "error",
            "message": "Sorry, I'm having trouble processing your request right now. Please try again later.",
            "_usage": None,
        }

    result = json.loads(response["text"])
    content_text = result["content"][0]["text"]
    usage = result.get("usage")

    try:
        parsed = json.loads(content_text)
    except json.JSONDecodeError:
        error_detail = f"stop_reason={result.get('stop_reason')} content_text={content_text[:500]}"
        print(f"Claude response not valid JSON. {error_detail}")
        if chat_id:
            try:
                from bot import log_error
            except ImportError:
                from src.bot import log_error
            await log_error(env, chat_id, "claude_bad_json", error_detail)
        # Try to extract JSON from the response if Claude wrapped it in text
        json_match = re.search(r"\{.*\}", content_text, re.DOTALL)
        if json_match:
            try:
                parsed = json.loads(json_match.group())
            except json.JSONDecodeError:
                parsed = None
        else:
            parsed = None

    if parsed is None:
        # Claude returned plain text instead of JSON — treat it as a clarify response
        parsed = {
            "action": "clarify",
            "message": content_text.strip(),
        }

    parsed["_usage"] = usage
    return parsed
