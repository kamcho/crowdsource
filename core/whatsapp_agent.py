"""OpenAI tool-calling agent for WhatsApp customer support."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

from django.conf import settings

from core.openai_product_import import is_openai_configured

from .whatsapp_tools import (
    MAX_TOOL_PRODUCTS,
    execute_tool,
    get_active_category_names,
    TOOL_DEFINITIONS,
)

logger = logging.getLogger('crowdsource.whatsapp')

MAX_TOOL_ROUNDS = 4


class WhatsAppAgentError(Exception):
    """Raised when the WhatsApp agent cannot run."""


@dataclass
class AgentResult:
    reply_text: str
    products: list = field(default_factory=list)


def _build_system_prompt(*, user=None) -> str:
    categories = get_active_category_names()
    category_hint = ', '.join(categories[:40]) if categories else 'none loaded'
    user_hint = 'registered customer linked to this WhatsApp number' if user else 'guest (not signed in)'

    return f"""You are the WhatsApp support assistant for {settings.SITE_NAME}, a Kenya group-buy import marketplace (CrowdSource).

The customer is a {user_hint}.

You have tools to:
- search and browse products (by keyword, category, or product id)
- list catalog highlights
- list categories
- check the customer's orders (only when their account is linked)
- explain how the platform works

Active catalog categories include: {category_hint}

Rules:
- Always use tools for product, order, or platform-fact requests instead of guessing.
- "show me handbags/bags/products" → search_products or browse_category or list_catalog.
- "what do you sell" / "show products" → list_catalog.
- product id messages → get_product_by_id.
- order status → get_my_orders.
- how group buys / MOQ / signup work → get_platform_info.
- Keep WhatsApp replies concise (under 700 chars). Friendly and helpful.
- When tools return products, reply with ONE short intro sentence only (e.g. "Found 3 handbags — sending photos now."). Never list product names, prices, or URLs — photos are sent separately.
- If no account is linked and they ask about orders, tell them to sign in with the same phone number.
- Site URL: {settings.SITE_PROTOCOL}://{settings.SITE_DOMAIN}
"""


def _dedupe_products(products):
    seen = set()
    unique = []
    for product in products:
        if product.pk in seen:
            continue
        seen.add(product.pk)
        unique.append(product)
    return unique[:MAX_TOOL_PRODUCTS]


def run_whatsapp_agent(message: str, *, history=None, user=None) -> AgentResult:
    message = (message or '').strip()
    if not message:
        return AgentResult(reply_text='Send me a message and I can help you browse products or check orders.')

    if not is_openai_configured():
        raise WhatsAppAgentError(
            'OpenAI is not configured. Set OPENAI_API_KEY in your environment.',
        )

    from openai import OpenAI

    history = history or []
    messages = [{'role': 'system', 'content': _build_system_prompt(user=user)}]
    for item in history[-6:]:
        role = item.get('role')
        content = item.get('content')
        if role in ('user', 'assistant') and content:
            messages.append({'role': role, 'content': content})
    messages.append({'role': 'user', 'content': message})

    client = OpenAI(api_key=settings.OPENAI_API_KEY)
    collected_products = []

    for round_num in range(MAX_TOOL_ROUNDS):
        try:
            response = client.chat.completions.create(
                model=getattr(settings, 'OPENAI_MODEL', 'gpt-4o-mini'),
                messages=messages,
                tools=TOOL_DEFINITIONS,
                tool_choice='auto',
                temperature=0.3,
            )
        except Exception as exc:
            logger.exception('WhatsApp agent OpenAI failure on round %s', round_num + 1)
            raise WhatsAppAgentError('Could not process your message right now.') from exc

        choice = response.choices[0]
        assistant_message = choice.message

        if assistant_message.tool_calls:
            messages.append({
                'role': 'assistant',
                'content': assistant_message.content,
                'tool_calls': [
                    {
                        'id': call.id,
                        'type': call.type,
                        'function': {
                            'name': call.function.name,
                            'arguments': call.function.arguments,
                        },
                    }
                    for call in assistant_message.tool_calls
                ],
            })
            for tool_call in assistant_message.tool_calls:
                try:
                    arguments = json.loads(tool_call.function.arguments or '{}')
                except json.JSONDecodeError:
                    arguments = {}
                result = execute_tool(tool_call.function.name, arguments, user=user)
                collected_products.extend(result.products)
                messages.append({
                    'role': 'tool',
                    'tool_call_id': tool_call.id,
                    'content': json.dumps(result.data),
                })
            continue

        reply = (assistant_message.content or '').strip()
        if not reply:
            reply = 'How can I help you today? Ask about products, orders, or how group buys work.'
        return AgentResult(
            reply_text=reply,
            products=_dedupe_products(collected_products),
        )

    return AgentResult(
        reply_text='I found some information but need a simpler question — try "show me bags" or "product 12".',
        products=_dedupe_products(collected_products),
    )
