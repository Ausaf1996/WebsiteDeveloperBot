import json


def parse_incoming_message(body):
    """Parse an incoming Telegram webhook update.

    Returns (chat_id, message_text) or (None, None) if not a valid text message.
    """
    try:
        message = body.get("message") or body.get("edited_message")
        if not message:
            return None, None

        chat_id = str(message["chat"]["id"])
        text = message.get("text")

        if text:
            return chat_id, text

        return chat_id, None
    except (KeyError, TypeError):
        return None, None


async def send_message(env, chat_id, text):
    """Send a text message back to the user via Telegram Bot API."""
    url = f"https://api.telegram.org/bot{env.telegram_bot_token}/sendMessage"
    headers = {"Content-Type": "application/json"}
    body = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown",
    }
    await env.http_request("POST", url, headers=headers, body=body)
