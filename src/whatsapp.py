import json


def parse_incoming_message(body):
    """Parse an incoming WhatsApp webhook payload.

    Returns (phone_number, message_text) or (None, None) if not a valid text message.
    """
    try:
        entry = body.get("entry", [{}])[0]
        changes = entry.get("changes", [{}])[0]
        value = changes.get("value", {})
        messages = value.get("messages", [])

        if not messages:
            return None, None

        message = messages[0]
        phone = message.get("from")

        if message.get("type") == "text":
            text = message["text"]["body"]
            return phone, text

        return phone, None
    except (IndexError, KeyError):
        return None, None


async def send_message(env, to, text):
    """Send a text message back to the user via WhatsApp Business API."""
    url = f"https://graph.facebook.com/v21.0/{env.whatsapp_phone_number_id}/messages"
    headers = {
        "Authorization": f"Bearer {env.whatsapp_token}",
        "Content-Type": "application/json",
    }
    body = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": text},
    }
    await env.http_request("POST", url, headers=headers, body=body)


def verify_webhook(params, verify_token):
    """Verify the WhatsApp webhook subscription challenge.

    Returns the challenge string if valid, None otherwise.
    """
    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")

    if mode == "subscribe" and token == verify_token:
        return challenge
    return None
