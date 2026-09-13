"""OpenAI intent parsing for inbound WhatsApp messages."""

from __future__ import annotations

import json
import logging

from django.conf import settings

from core.openai_product_import import is_openai_configured

logger = logging.getLogger('crowdsource.whatsapp')

INTENTS = frozenset({
    'greeting',
    'general_help',
    'product_detail',
    'product_search',
    'order_status',
    'unknown',
})

SYSTEM_PROMPT = """You classify WhatsApp messages for Kenya Imports, a group-buy import marketplace in Kenya.

Return ONLY valid JSON:
{
  "intent": "greeting | general_help | product_detail | product_search | order_status | unknown",
  "query": "search phrase or empty string",
  "product_id": null or integer,
  "product_slug": "slug or empty string",
  "reply_hint": "short note for the assistant about what the user wants"
}

Rules:
- If the user mentions a numeric product id (e.g. "product 12", "id 45", "#7"), set intent=product_detail and product_id.
- If they mention a product by name, set intent=product_detail or product_search with query.
- order_status: questions about their order, delivery, payment status.
- general_help: how the platform works, MOQ, group buys, sign up.
- greeting: hi/hello/hey without a concrete request.
- unknown: unclear message.
"""


class WhatsAppIntentError(Exception):
    """Raised when OpenAI intent parsing is unavailable or fails."""


def normalize_intent(data: dict):
    intent = str(data.get('intent', 'unknown')).strip().lower()
    if intent not in INTENTS:
        intent = 'unknown'

    product_id = data.get('product_id')
    if product_id in ('', None):
        product_id = None
    else:
        try:
            product_id = int(product_id)
        except (TypeError, ValueError):
            product_id = None

    return {
        'intent': intent,
        'query': str(data.get('query', '') or '').strip(),
        'product_id': product_id,
        'product_slug': str(data.get('product_slug', '') or '').strip(),
        'reply_hint': str(data.get('reply_hint', '') or '').strip(),
    }


def parse_whatsapp_intent(message: str, *, history=None):
    message = (message or '').strip()
    if not message:
        return normalize_intent({'intent': 'unknown'})

    if not is_openai_configured():
        raise WhatsAppIntentError(
            'OpenAI is not configured. Set OPENAI_API_KEY in your environment.'
        )

    from openai import OpenAI

    history = history or []
    messages = [{'role': 'system', 'content': SYSTEM_PROMPT}]
    for item in history[-6:]:
        role = item.get('role')
        content = item.get('content')
        if role in ('user', 'assistant') and content:
            messages.append({'role': role, 'content': content})
    messages.append({'role': 'user', 'content': message})

    client = OpenAI(api_key=settings.OPENAI_API_KEY)
    try:
        response = client.chat.completions.create(
            model=getattr(settings, 'OPENAI_MODEL', 'gpt-4o-mini'),
            messages=messages,
            response_format={'type': 'json_object'},
            temperature=0.2,
        )
        raw = response.choices[0].message.content or '{}'
        data = json.loads(raw)
    except Exception as exc:
        logger.exception('WhatsApp intent OpenAI failure')
        raise WhatsAppIntentError('Could not understand the message right now.') from exc

    return normalize_intent(data)
