"""WhatsApp inbound message orchestration."""

from __future__ import annotations

import hashlib
import hmac
import logging
import threading
from datetime import datetime, timezone as datetime_timezone

from django.conf import settings
from django.core.cache import cache
from django.db import close_old_connections
from django.db.models import Q
from django.utils import timezone

from core.models import Product
from core.order import Order
from core.pricing import format_price_range, product_variation_price_range
from core.textsms import normalize_kenyan_mobile
from home.catalog import get_public_products_queryset
from tenants.context import get_current_tenant

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

MAX_HISTORY = 8
MAX_SEARCH_RESULTS = 3
ACTIVITY_FEED_MAX = 40
OUTBOUND_META_TTL = 7 * 86400
MAX_PRODUCT_REMARKS = 4
MAX_REMARK_LINE_LEN = 96

DELIVERY_STATUS_REMARKS = {
    'sent': 'Sent',
    'delivered': 'Delivered',
    'read': 'Read',
    'read_by_business': 'Read by business',
    'failed': 'Failed',
}


def _event_datetime(timestamp):
    try:
        return datetime.fromtimestamp(int(timestamp), tz=datetime_timezone.utc)
    except (TypeError, ValueError, OSError, OverflowError):
        return timezone.now()


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


def absolute_media_url(relative_url: str) -> str:
    return absolute_whatsapp_media_url(relative_url)


def refresh_products_for_whatsapp(products):
    if not products:
        return []
    ids = [product.pk for product in products]
    return list(
        get_public_products_queryset()
        .filter(pk__in=ids)
        .prefetch_related('attributes')[:MAX_SEARCH_RESULTS]
    )


def _outbound_meta_key(message_id: str) -> str:
    return f'whatsapp:outbound:{message_id}'


def _extract_sent_message_id(api_response) -> str:
    if not isinstance(api_response, dict):
        return ''
    messages = api_response.get('messages')
    if isinstance(messages, list) and messages:
        return (messages[0].get('id') or '').strip()
    return ''


def record_whatsapp_activity(
    *,
    phone: str,
    direction: str,
    summary: str,
    message_id: str = '',
    delivery_status: str = '',
):
    phone = (phone or '').strip()
    if not phone and not summary:
        return
    message_id = (message_id or '').strip()
    event_time = timezone.now()

    from core.whatsapp_message import WhatsAppMessage

    defaults = {
        'phone': phone,
        'direction': direction,
        'body': (summary or '').strip()[:4096],
        'message_type': 'text',
        'delivery_status': (delivery_status or '').strip(),
        'sent_at': event_time,
        'status_updated_at': event_time if delivery_status else None,
    }
    if message_id:
        message = WhatsAppMessage.objects.filter(message_id=message_id).first()
        if message:
            if delivery_status:
                message.delivery_status = delivery_status
                message.status_updated_at = event_time
                message.save(update_fields=['delivery_status', 'status_updated_at'])
        else:
            WhatsAppMessage.objects.create(message_id=message_id, **defaults)
    else:
        WhatsAppMessage.objects.create(**defaults)


def get_whatsapp_activity_feed():
    from core.whatsapp_message import WhatsAppMessage

    rows = list(WhatsAppMessage.objects.all()[:ACTIVITY_FEED_MAX])
    users_by_phone = _users_by_whatsapp_phone(item.phone for item in rows)
    return [
        {
            'id': item.pk,
            'phone': item.phone,
            'direction': item.direction,
            'summary': (item.body or '').strip()[:160],
            'read_remark': DELIVERY_STATUS_REMARKS.get(
                item.delivery_status,
                item.delivery_status.replace('_', ' ').title(),
            ),
            'message_id': item.message_id,
            'delivery_status': item.delivery_status,
            'status_detail': item.status_detail,
            'at': item.sent_at,
            'message_type': item.message_type,
            'sender_name': item.sender_name,
            'user': users_by_phone.get(_normalized_whatsapp_phone(item.phone)),
        }
        for item in rows
    ]


def _normalized_whatsapp_phone(phone):
    try:
        return normalize_kenyan_mobile(str(phone or ''))
    except ValueError:
        return ''


def _users_by_whatsapp_phone(phones):
    from users.models import User

    phone_values = {str(phone).strip() for phone in phones if phone}
    candidates = phone_values | {
        f'+{phone}' for phone in phone_values if not phone.startswith('+')
    }
    users = User.objects.filter(phone__in=candidates)
    return {
        _normalized_whatsapp_phone(user.phone): user
        for user in users
        if _normalized_whatsapp_phone(user.phone)
    }


def _track_outbound_send(
    to: str,
    preview: str,
    api_response,
    *,
    message_type='text',
    media_id='',
    message_record=None,
):
    wamid = _extract_sent_message_id(api_response)
    if not wamid and message_record is None:
        return
    recipient = whatsapp.normalize_whatsapp_recipient(to)
    from core.whatsapp_message import WhatsAppMessage

    sent_at = timezone.now()
    if message_record is None:
        message_record, _ = WhatsAppMessage.objects.update_or_create(
            message_id=wamid,
            defaults={
                'phone': recipient or to,
                'direction': WhatsAppMessage.Direction.OUTBOUND,
                'message_type': message_type,
                'body': (preview or '')[:4096],
                'media_id': media_id,
                'delivery_status': 'sent',
                'sent_at': sent_at,
                'status_updated_at': sent_at,
            },
        )
    else:
        message_record.message_id = wamid
        message_record.delivery_status = 'sent'
        message_record.status_detail = (
            '' if wamid else 'WhatsApp accepted the message without returning a message ID.'
        )
        message_record.status_updated_at = sent_at
        message_record.save(update_fields=[
            'message_id',
            'delivery_status',
            'status_detail',
            'status_updated_at',
        ])
        if not wamid:
            logger.warning('WhatsApp accepted an outbound message without returning a message ID')

    if wamid:
        cache.set(
            _outbound_meta_key(wamid),
            {'phone': recipient, 'preview': (preview or '')[:120]},
            OUTBOUND_META_TTL,
        )


def _create_outbound_message(*, to, body, message_type='text', media_id=''):
    from core.whatsapp_message import WhatsAppMessage

    recipient = whatsapp.normalize_whatsapp_recipient(to)
    return WhatsAppMessage.objects.create(
        phone=recipient or to,
        direction=WhatsAppMessage.Direction.OUTBOUND,
        message_type=message_type,
        body=(body or '')[:4096],
        media_id=media_id,
        delivery_status='sending',
        sent_at=timezone.now(),
    )


def _mark_outbound_message_failed(message_record, exc):
    message_record.delivery_status = 'failed'
    message_record.status_detail = str(exc)[:2000]
    message_record.status_updated_at = timezone.now()
    message_record.save(update_fields=[
        'delivery_status',
        'status_detail',
        'status_updated_at',
    ])


def product_remark_lines(product: Product, limit: int = MAX_PRODUCT_REMARKS) -> list[str]:
    lines = []
    for attr in product.product_attributes.order_by('sort_order', 'title')[:limit]:
        desc = (attr.description or '').strip().replace('\n', ' ')
        title = (attr.title or '').strip()
        if not desc and not title:
            continue
        text = f'{title}: {desc}' if title and desc else (title or desc)
        if len(text) > MAX_REMARK_LINE_LEN:
            text = text[: MAX_REMARK_LINE_LEN - 1] + '…'
        lines.append(text)
    return lines


def build_product_caption(product: Product) -> str:
    price_min, price_max = product_variation_price_range(product)
    price_text = format_price_range(price_min, price_max)
    group_buy = product.active_group_buy
    lines = [product.name]
    if price_text:
        lines.append(f'Price: {price_text}')
    if group_buy:
        lines.append(f'MOQ: {group_buy.moq} units · {group_buy.progress_percent}% pledged')
    remarks = product_remark_lines(product)
    if remarks:
        lines.append('Remarks:')
        lines.extend(f'• {line}' for line in remarks)
    lines.append(f'View: {absolute_site_url(product.get_absolute_url())}')
    return '\n'.join(lines)[:1024]


def build_products_intro(products) -> str:
    count = len(products)
    noun = 'product' if count == 1 else 'products'
    return f'Found {count} {noun} — sending photos now:'


def get_conversation_history(phone: str, *, exclude_message_id=''):
    from core.whatsapp_message import WhatsAppMessage

    messages = WhatsAppMessage.objects.filter(phone=phone)
    if exclude_message_id:
        messages = messages.exclude(message_id=exclude_message_id)
    recent_messages = list(messages.order_by('-sent_at', '-pk')[:MAX_HISTORY])
    return [
        {
            'role': 'user' if item.direction == WhatsAppMessage.Direction.INBOUND else 'assistant',
            'content': item.body or f'[{item.message_type.title()} message]',
        }
        for item in reversed(recent_messages)
    ]


def find_user_by_whatsapp_phone(phone: str):
    from users.models import User

    raw = str(phone or '').strip()
    try:
        normalized = normalize_kenyan_mobile(raw)
    except ValueError:
        return None

    national = f'0{normalized[3:]}'
    candidates = {raw, normalized, f'+{normalized}', national}
    user = User.objects.filter(phone__in=candidates).first()
    if user:
        return user

    for user in User.objects.filter(phone__endswith=normalized[-9:]).iterator():
        try:
            if normalize_kenyan_mobile(str(user.phone)) == normalized:
                return user
        except ValueError:
            continue
    return None


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
    remarks = product_remark_lines(product)
    if remarks:
        lines.append('Remarks:')
        lines.extend(f'• {line}' for line in remarks)
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
    message_record = _create_outbound_message(to=to, body=body)
    try:
        data = whatsapp.send_text(to=to, body=body)
        _track_outbound_send(
            to,
            body,
            data,
            message_record=message_record,
        )
        return True
    except (WhatsAppAPIError, WhatsAppConfigError) as exc:
        _mark_outbound_message_failed(message_record, exc)
        _log_whatsapp_send_failure(exc)
        return False


def _safe_send_image(*, to: str, image_url: str, caption: str = '') -> bool:
    preview = caption or 'Image'
    message_record = _create_outbound_message(
        to=to,
        body=preview,
        message_type='image',
    )
    try:
        data = whatsapp.send_image(to=to, image_url=image_url, caption=caption)
        _track_outbound_send(
            to,
            preview,
            data,
            message_type='image',
            message_record=message_record,
        )
        return True
    except (WhatsAppAPIError, WhatsAppConfigError) as exc:
        _mark_outbound_message_failed(message_record, exc)
        _log_whatsapp_send_failure(exc)
        return False


def _safe_send_product_image(*, to: str, product: Product, caption: str = '') -> bool:
    image_bytes = render_product_image_jpeg(product)
    if not image_bytes:
        logger.warning('No usable image for product #%s (%s)', product.pk, product.name)
        return False

    message_record = _create_outbound_message(
        to=to,
        body=caption or product.name,
        message_type='image',
    )
    try:
        media_id = whatsapp.upload_media(
            file_bytes=image_bytes,
            mime_type='image/jpeg',
            filename=f'product-{product.pk}.jpg',
        )
        data = whatsapp.send_image_id(to=to, media_id=media_id, caption=caption)
        _track_outbound_send(
            to,
            caption or product.name,
            data,
            message_type='image',
            media_id=media_id,
            message_record=message_record,
        )
        return True
    except (WhatsAppAPIError, WhatsAppConfigError) as exc:
        _mark_outbound_message_failed(message_record, exc)
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
        tenant_token = None
        try:
            tenant_id = message.get('tenant_id')
            if tenant_id:
                from tenants.context import set_current_tenant
                from tenants.models import Tenant

                tenant = Tenant.objects.get(pk=tenant_id)
                tenant_token = set_current_tenant(tenant)
            handle_inbound_text_message(
                from_phone=message.get('from_phone', ''),
                message_text=message.get('message_text', ''),
                message_id=message.get('message_id', ''),
                message_persisted=True,
            )
        except Exception:
            logger.exception(
                'Failed to handle WhatsApp message from %s',
                message.get('from_phone'),
            )
        finally:
            if tenant_token is not None:
                from tenants.context import reset_current_tenant

                reset_current_tenant(tenant_token)
            close_old_connections()

    threading.Thread(target=runner, daemon=True).start()


def handle_inbound_text_message(
    *,
    from_phone: str,
    message_text: str,
    message_id: str = '',
    message_persisted: bool = False,
):
    from_phone = (from_phone or '').strip()
    message_text = (message_text or '').strip()
    if not from_phone or not message_text:
        return

    if not message_persisted:
        _save_inbound_message({
            'from_phone': from_phone,
            'message_text': message_text,
            'message_id': message_id,
            'message_type': 'text',
        })
    _acknowledge_inbound_message(
        message_id,
        from_phone,
        message_text,
        show_typing=True,
    )

    history = get_conversation_history(
        from_phone,
        exclude_message_id=message_id,
    )
    user = find_user_by_whatsapp_phone(from_phone)

    try:
        result = run_whatsapp_agent(
            message_text,
            history=history,
            user=user,
            phone=from_phone,
        )
    except WhatsAppAgentError as exc:
        _safe_send_text(to=from_phone, body=str(exc))
        return

    if result.products:
        products = refresh_products_for_whatsapp(result.products)
        _safe_send_text(to=from_phone, body=build_products_intro(products))
        send_product_replies(to=from_phone, products=products)
    else:
        _safe_send_text(to=from_phone, body=result.reply_text)


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
                    'message_type': 'text',
                    'sent_at': item.get('timestamp'),
                    'sender_name': _contact_name(value, item.get('from', '')),
                })
    return messages


def _contact_name(value, phone):
    for contact in value.get('contacts', []):
        if contact.get('wa_id') == phone:
            return ((contact.get('profile') or {}).get('name') or '')[:150]
    return ''


def extract_inbound_messages(payload: dict):
    messages = []
    if payload.get('object') != 'whatsapp_business_account':
        return messages

    for entry in payload.get('entry', []):
        for change in entry.get('changes', []):
            value = change.get('value', {})
            for item in value.get('messages', []):
                message_type = (item.get('type') or 'unknown').strip().lower()
                content = item.get(message_type) or {}
                body = ''
                if message_type == 'text':
                    body = (content.get('body') or '').strip()
                elif message_type == 'button':
                    body = (content.get('text') or content.get('payload') or '').strip()
                elif message_type == 'interactive':
                    interactive = content.get('button_reply') or content.get('list_reply') or {}
                    body = (interactive.get('title') or interactive.get('description') or '').strip()
                elif message_type == 'location':
                    latitude = content.get('latitude')
                    longitude = content.get('longitude')
                    if latitude is not None and longitude is not None:
                        body = f'Location: {latitude}, {longitude}'
                elif message_type in {'image', 'video', 'audio', 'document', 'sticker'}:
                    body = (content.get('caption') or content.get('filename') or '').strip()

                messages.append({
                    'from_phone': item.get('from', ''),
                    'message_id': item.get('id', ''),
                    'message_text': body,
                    'message_type': message_type,
                    'sent_at': item.get('timestamp'),
                    'sender_name': _contact_name(value, item.get('from', '')),
                    'media_id': (content.get('id') or '').strip(),
                    'media_mime_type': (content.get('mime_type') or '').strip(),
                })
    return messages


def _save_inbound_message(message):
    from core.whatsapp_message import WhatsAppMessage

    phone = (message.get('from_phone') or '').strip()
    message_id = (message.get('message_id') or '').strip()
    if not phone:
        return
    message_type = (message.get('message_type') or 'text').strip().lower()
    body = (message.get('message_text') or '').strip()
    sent_at = _event_datetime(message.get('sent_at'))
    values = {
        'phone': phone,
        'sender_name': (message.get('sender_name') or '')[:150],
        'direction': WhatsAppMessage.Direction.INBOUND,
        'message_type': message_type[:32],
        'body': body[:4096],
        'media_id': (message.get('media_id') or '')[:255],
        'media_mime_type': (message.get('media_mime_type') or '')[:120],
        'sent_at': sent_at,
    }
    if message_id:
        _, created = WhatsAppMessage.objects.get_or_create(
            message_id=message_id,
            defaults=values,
        )
        return created
    else:
        WhatsAppMessage.objects.create(**values)
        return True


def extract_message_status_updates(payload: dict):
    updates = []
    if payload.get('object') != 'whatsapp_business_account':
        return updates

    for entry in payload.get('entry', []):
        for change in entry.get('changes', []):
            value = change.get('value', {})
            for item in value.get('statuses', []):
                status = (item.get('status') or '').strip()
                message_id = (item.get('id') or '').strip()
                if not status or not message_id:
                    continue
                updates.append({
                    'message_id': message_id,
                    'status': status,
                    'status_detail': _status_detail(item.get('errors', [])),
                    'recipient_id': (item.get('recipient_id') or '').strip(),
                    'timestamp': item.get('timestamp'),
                })
    return updates


def _status_detail(errors):
    details = []
    for error in errors:
        if not isinstance(error, dict):
            continue
        code = error.get('code')
        title = (error.get('title') or error.get('message') or '').strip()
        detail = f'{code}: {title}' if code and title else (title or str(code or ''))
        if detail:
            details.append(detail)
    return '; '.join(details)[:2000]


def handle_message_status_update(update: dict):
    status = (update.get('status') or '').strip()
    message_id = (update.get('message_id') or '').strip()
    if not status or not message_id:
        return

    from core.whatsapp_message import WhatsAppMessage

    persisted = WhatsAppMessage.objects.filter(message_id=message_id).first()
    meta = cache.get(_outbound_meta_key(message_id)) or {}
    phone = (
        (persisted.phone if persisted else '')
        or meta.get('phone')
        or update.get('recipient_id')
        or ''
    )
    preview = (persisted.body if persisted else '') or meta.get('preview') or ''
    if persisted:
        persisted.delivery_status = status
        persisted.status_detail = (update.get('status_detail') or '')[:2000]
        persisted.status_updated_at = _event_datetime(update.get('timestamp'))
        persisted.save(update_fields=[
            'delivery_status',
            'status_detail',
            'status_updated_at',
        ])
    record_whatsapp_activity(
        phone=phone,
        direction='outbound',
        summary=preview or 'Outbound message',
        message_id=message_id,
        delivery_status=status,
    )
    if not persisted:
        WhatsAppMessage.objects.filter(message_id=message_id).update(
            status_detail=(update.get('status_detail') or '')[:2000],
        )
    logger.info(
        'WhatsApp message %s status=%s recipient=%s',
        message_id,
        status,
        phone,
    )


def _acknowledge_inbound_message(
    message_id: str,
    from_phone: str,
    preview: str,
    *,
    show_typing: bool = False,
):
    if not message_id:
        return
    try:
        whatsapp.mark_message_read(message_id, show_typing=show_typing)
        record_whatsapp_activity(
            phone=from_phone,
            direction='inbound',
            summary=preview,
            message_id=message_id,
            delivery_status='read_by_business',
        )
    except Exception:
        logger.debug('Could not acknowledge WhatsApp message', exc_info=True)


def process_webhook_payload(payload: dict):
    if whatsapp.whatsapp_backend() == 'cloud':
        token_error = whatsapp.check_access_token()
        if token_error:
            logger.error(
                'WhatsApp webhook received messages but outbound API auth is broken: %s',
                token_error,
            )

    handled = 0
    for update in extract_message_status_updates(payload):
        handle_message_status_update(update)
        handled += 1

    for message in extract_inbound_messages(payload):
        message_id = (message.get('message_id') or '').strip()
        created = _save_inbound_message(message)
        if not created:
            logger.info('Skipping duplicate WhatsApp message %s', message_id)
            continue
        if message.get('message_type') == 'text' and message.get('message_text'):
            _dispatch_inbound_message({
                'from_phone': message.get('from_phone', ''),
                'message_text': message.get('message_text', ''),
                'message_id': message_id,
                'tenant_id': getattr(get_current_tenant(), 'pk', None),
            })
        handled += 1
    return handled
