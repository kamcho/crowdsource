"""WhatsApp inbound message orchestration."""

from __future__ import annotations

import hashlib
import hmac
import logging
import threading

from django.conf import settings
from django.core.cache import cache
from django.db import close_old_connections
from django.db.models import Q

from core.models import Product
from core.order import Order
from core.pricing import format_price_range, product_variation_price_range
from core.textsms import normalize_kenyan_mobile
from home.catalog import get_public_products_queryset

from . import whatsapp
from .whatsapp import WhatsAppAPIError, WhatsAppConfigError
from .whatsapp_agent import AgentResult, WhatsAppAgentError, run_whatsapp_agent
from .whatsapp_media import (
    absolute_whatsapp_media_url,
    get_whatsapp_public_base_url,
    is_whatsapp_reachable_url,
    render_product_image_jpeg,
)

logger = logging.getLogger('crowdsource.whatsapp')

SESSION_TTL = 3600
MAX_HISTORY = 8
MAX_SEARCH_RESULTS = 3
PROCESSED_MESSAGE_TTL = 86400


def verify_webhook_signature(body: bytes, signature_header: str) -> bool:
    secret = getattr(settings, 'WHATSAPP_APP_SECRET', '').strip()
    if not secret:
        return True
    if not signature_header or not signature_header.startswith('sha256='):
        return False
    expected = hmac.new(secret.encode('utf-8'), body, hashlib.sha256).hexdigest()
    received = signature_header.removeprefix('sha256=')
    return hmac.compare_digest(expected, received)


def absolute_site_url(path: str) -> str:
    base = get_whatsapp_public_base_url()
    if not path:
        return base
    return f"{base}/{path.lstrip('/')}"


def _processed_message_key(message_id: str) -> str:
    return f'whatsapp:processed:{message_id}'


def absolute_media_url(relative_url: str) -> str:
    return absolute_whatsapp_media_url(relative_url)


def refresh_products_for_whatsapp(products):
    if not products:
        return []
    ids = [product.pk for product in products]
    return list(get_public_products_queryset().filter(pk__in=ids)[:MAX_SEARCH_RESULTS])


def build_product_caption(product: Product) -> str:
    price_min, price_max = product_variation_price_range(product)
    price_text = format_price_range(price_min, price_max)
    group_buy = product.active_group_buy
    lines = [product.name]
    if price_text:
        lines.append(f'Price: {price_text}')
    if group_buy:
        lines.append(f'MOQ: {group_buy.moq} units · {group_buy.progress_percent}% pledged')
    lines.append(f'View: {absolute_site_url(product.get_absolute_url())}')
    return '\n'.join(lines)[:1024]


def build_products_intro(products) -> str:
    count = len(products)
    noun = 'product' if count == 1 else 'products'
    return f'Found {count} {noun} — sending photos now:'


def _history_key(phone: str) -> str:
    return f'whatsapp:history:{phone}'


def get_conversation_history(phone: str):
    return cache.get(_history_key(phone), [])


def append_conversation(phone: str, role: str, content: str):
    history = get_conversation_history(phone)
    history.append({'role': role, 'content': content})
    cache.set(_history_key(phone), history[-MAX_HISTORY:], SESSION_TTL)


def find_user_by_whatsapp_phone(phone: str):
    from users.models import User

    candidates = []
    raw = phone.strip()
    if raw:
        candidates.append(raw)
        if not raw.startswith('+'):
            candidates.append(f'+{raw}')
    normalized = None
    for candidate in candidates:
        try:
            normalized = normalize_kenyan_mobile(candidate)
            break
        except ValueError:
            continue
    if not normalized:
        return None

    e164 = f'+{normalized}'
    return User.objects.filter(Q(phone=e164) | Q(phone=normalized)).first()


def resolve_products_from_intent(intent_data, *, user=None, limit=MAX_SEARCH_RESULTS):
    intent = intent_data.get('intent')
    product_id = intent_data.get('product_id')
    product_slug = intent_data.get('product_slug')
    query = intent_data.get('query')

    base_qs = get_public_products_queryset()

    if product_id:
        product = base_qs.filter(pk=product_id).first()
        return list(base_qs.filter(pk=product.pk)[:1]) if product else []

    if product_slug:
        product = base_qs.filter(slug=product_slug).first()
        return list(base_qs.filter(pk=product.pk)[:1]) if product else []

    if intent == 'product_search' and query:
        return list(base_qs.filter(
            Q(name__icontains=query) | Q(description__icontains=query),
        )[:limit])

    if user and user.is_authenticated and intent in ('product_search', 'unknown', 'greeting'):
        from core.preference_services import get_suggested_products_for_user

        suggestions = get_suggested_products_for_user(user, limit=limit)
        if suggestions:
            return suggestions

    if query:
        return list(base_qs.filter(
            Q(name__icontains=query) | Q(description__icontains=query),
        )[:limit])

    return []


def build_product_text(product: Product) -> str:
    price_min, price_max = product_variation_price_range(product)
    price_text = format_price_range(price_min, price_max)
    group_buy = product.active_group_buy
    lines = [
        f'*{product.name}*',
        f'Category: {product.category.name}',
    ]
    if price_text:
        lines.append(f'Price: {price_text}')
    if group_buy:
        lines.append(
            f'Group buy: {group_buy.pledged_units}/{group_buy.moq} units pledged '
            f'({group_buy.progress_percent}% to MOQ)',
        )
    if product.description:
        snippet = product.description.strip().replace('\n', ' ')
        lines.append(snippet[:220] + ('…' if len(snippet) > 220 else ''))
    lines.append(f'View: {absolute_site_url(product.get_absolute_url())}')
    return '\n'.join(lines)


def build_order_status_text(user) -> str:
    orders = (
        Order.objects.filter(user=user)
        .select_related('group_buy__product')
        .order_by('-created_at')[:5]
    )
    if not orders:
        return (
            'I could not find any orders linked to your account. '
            f'Sign in at {absolute_site_url("/users/signin/")} with the same phone number.'
        )

    lines = ['Here are your recent orders:']
    for order in orders:
        product_name = order.group_buy.product.name
        lines.append(
            f'• Order #{order.pk} — {product_name} — {order.get_status_display()} — ${order.total_amount}',
        )
    lines.append(f'Manage orders: {absolute_site_url("/orders/")}')
    return '\n'.join(lines)


def build_help_text() -> str:
    return (
        f'Welcome to {settings.SITE_NAME}! We help buyers in Kenya import from China through group buys.\n\n'
        'You can ask me about:\n'
        '• A product by name or id (e.g. "product 12" or "handbags")\n'
        '• How group buys and MOQ work\n'
        '• Your order status (use the phone number on your account)\n\n'
        f'Browse the catalog: {absolute_site_url("/products/")}'
    )


def build_greeting_text(user=None) -> str:
    if user:
        name = user.get_full_name().strip() or 'there'
        return (
            f'Hi {name}! I can help you find products, check order status, or explain how group buys work.\n\n'
            'Try: "product 5" or "show me handbags".'
        )
    return (
        'Hi! I can help you find products and answer questions about Kenya Imports.\n\n'
        'Try: "product 12" or search by name, e.g. "makeup".'
    )


def send_product_replies(*, to: str, products):
    products = refresh_products_for_whatsapp(products)
    if not products:
        _safe_send_text(
            to=to,
            body=(
                'I could not find a matching product. '
                f'Try browsing {absolute_site_url("/products/")} or send a product id like "product 12".'
            ),
        )
        return

    for product in products[:MAX_SEARCH_RESULTS]:
        caption = build_product_caption(product)
        if _safe_send_product_image(to=to, product=product, caption=caption):
            continue
        _safe_send_text(to=to, body=build_product_text(product))


def _log_whatsapp_send_failure(exc: Exception):
    if isinstance(exc, WhatsAppAPIError) and exc.is_auth_error:
        logger.error(
            'WhatsApp outbound message failed — access token is invalid or expired. '
            'Generate a new token in Meta Developer Console → WhatsApp → API setup, '
            'update WHATSAPP_ACCESS_TOKEN in .env, and restart the server. Meta says: %s',
            exc,
        )
        return
    if isinstance(exc, WhatsAppConfigError):
        logger.error('WhatsApp outbound message failed — not configured: %s', exc)
        return
    logger.exception('WhatsApp outbound message failed')


def _safe_send_text(*, to: str, body: str) -> bool:
    try:
        whatsapp.send_text(to=to, body=body)
        return True
    except (WhatsAppAPIError, WhatsAppConfigError) as exc:
        _log_whatsapp_send_failure(exc)
        return False


def _safe_send_image(*, to: str, image_url: str, caption: str = '') -> bool:
    try:
        whatsapp.send_image(to=to, image_url=image_url, caption=caption)
        return True
    except (WhatsAppAPIError, WhatsAppConfigError) as exc:
        _log_whatsapp_send_failure(exc)
        return False


def _safe_send_product_image(*, to: str, product: Product, caption: str = '') -> bool:
    image_bytes = render_product_image_jpeg(product)
    if not image_bytes:
        logger.warning('No usable image for product #%s (%s)', product.pk, product.name)
        return False

    try:
        media_id = whatsapp.upload_media(
            file_bytes=image_bytes,
            mime_type='image/jpeg',
            filename=f'product-{product.pk}.jpg',
        )
        whatsapp.send_image_id(to=to, media_id=media_id, caption=caption)
        return True
    except (WhatsAppAPIError, WhatsAppConfigError) as exc:
        _log_whatsapp_send_failure(exc)
        return False


def generate_reply_text(*, intent_data, user=None, products=None) -> str:
    intent = intent_data.get('intent')
    if intent == 'greeting':
        return build_greeting_text(user)
    if intent == 'general_help':
        return build_help_text()
    if intent == 'order_status':
        if user:
            return build_order_status_text(user)
        return (
            'To check orders I need your Kenya Imports account linked to this WhatsApp number. '
            f'Sign in at {absolute_site_url("/users/signin/")} using the same phone.'
        )
    if intent in ('product_detail', 'product_search'):
        if products:
            if len(products) == 1:
                return f'Here is what I found for product #{products[0].pk}:'
            return f'I found {len(products)} matching products:'
        return (
            'I could not find a matching product. '
            'Send a product id like "product 12" or describe what you want.'
        )
    return (
        'I am not sure I understood that. '
        'Try "product 12", search by name, or ask "how do group buys work?".'
    )


def _dispatch_inbound_message(message: dict):
    def runner():
        close_old_connections()
        try:
            handle_inbound_text_message(**message)
        except Exception:
            logger.exception(
                'Failed to handle WhatsApp message from %s',
                message.get('from_phone'),
            )
        finally:
            close_old_connections()

    threading.Thread(target=runner, daemon=True).start()


def handle_inbound_text_message(*, from_phone: str, message_text: str, message_id: str = ''):
    from_phone = (from_phone or '').strip()
    message_text = (message_text or '').strip()
    if not from_phone or not message_text:
        return

    if message_id:
        try:
            whatsapp.mark_message_read(message_id)
        except Exception:
            logger.debug('Could not mark WhatsApp message read', exc_info=True)

    history = get_conversation_history(from_phone)
    user = find_user_by_whatsapp_phone(from_phone)

    try:
        result = run_whatsapp_agent(message_text, history=history, user=user)
    except WhatsAppAgentError as exc:
        _safe_send_text(to=from_phone, body=str(exc))
        return

    append_conversation(from_phone, 'user', message_text)

    if result.products:
        products = refresh_products_for_whatsapp(result.products)
        _safe_send_text(to=from_phone, body=build_products_intro(products))
        send_product_replies(to=from_phone, products=products)
        append_conversation(from_phone, 'assistant', build_products_intro(products))
    else:
        _safe_send_text(to=from_phone, body=result.reply_text)
        append_conversation(from_phone, 'assistant', result.reply_text)


def extract_inbound_text_messages(payload: dict):
    messages = []
    if payload.get('object') != 'whatsapp_business_account':
        return messages

    for entry in payload.get('entry', []):
        for change in entry.get('changes', []):
            value = change.get('value', {})
            for item in value.get('messages', []):
                if item.get('type') != 'text':
                    continue
                text_body = (item.get('text') or {}).get('body', '').strip()
                if not text_body:
                    continue
                messages.append({
                    'from_phone': item.get('from', ''),
                    'message_id': item.get('id', ''),
                    'message_text': text_body,
                })
    return messages


def process_webhook_payload(payload: dict):
    if whatsapp.whatsapp_backend() == 'cloud':
        token_error = whatsapp.check_access_token()
        if token_error:
            logger.error(
                'WhatsApp webhook received messages but outbound API auth is broken: %s',
                token_error,
            )

    handled = 0
    for message in extract_inbound_text_messages(payload):
        message_id = (message.get('message_id') or '').strip()
        if message_id and not cache.add(_processed_message_key(message_id), 1, PROCESSED_MESSAGE_TTL):
            logger.info('Skipping duplicate WhatsApp message %s', message_id)
            continue
        _dispatch_inbound_message(message)
        handled += 1
    return handled
