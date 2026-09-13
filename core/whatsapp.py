"""Meta WhatsApp Cloud API client."""

from __future__ import annotations

import logging
import re

import requests
from django.conf import settings

logger = logging.getLogger('crowdsource.whatsapp')

GRAPH_API_VERSION = 'v19.0'


class WhatsAppConfigError(Exception):
    """Raised when WhatsApp Cloud API settings are missing."""


class WhatsAppAPIError(Exception):
    """Raised when the WhatsApp API returns an error."""

    def __init__(self, message, response_data=None, status_code=None):
        super().__init__(message)
        self.response_data = response_data or {}
        self.status_code = status_code

    @property
    def error_code(self):
        return (self.response_data.get('error') or {}).get('code')

    @property
    def is_auth_error(self):
        return self.status_code == 401 or self.error_code in {190, 102}


def check_access_token():
    """Return None if token works, else a human-readable error string."""
    if not is_whatsapp_configured():
        return 'WhatsApp is not configured (missing phone number id or access token).'

    phone_number_id = settings.WHATSAPP_PHONE_NUMBER_ID.strip()
    headers = {
        'Authorization': f'Bearer {settings.WHATSAPP_ACCESS_TOKEN.strip()}',
    }
    try:
        response = requests.get(
            f'https://graph.facebook.com/{GRAPH_API_VERSION}/{phone_number_id}',
            headers=headers,
            timeout=15,
        )
        if response.ok:
            return None
        data = response.json()
        message = data.get('error', {}).get('message', response.text)
        return message
    except requests.RequestException as exc:
        return f'Could not reach Meta API: {exc}'


def normalize_whatsapp_recipient(phone: str) -> str:
    clean_phone = re.sub(r'\D', '', str(phone or '').strip())
    if clean_phone.startswith('0') and len(clean_phone) == 10:
        return '254' + clean_phone[1:]
    return clean_phone


def is_whatsapp_configured():
    return bool(
        getattr(settings, 'WHATSAPP_ENABLED', False)
        and getattr(settings, 'WHATSAPP_PHONE_NUMBER_ID', '').strip()
        and getattr(settings, 'WHATSAPP_ACCESS_TOKEN', '').strip()
    )


def whatsapp_backend():
    return getattr(settings, 'WHATSAPP_BACKEND', 'cloud').strip().lower()


def _require_cloud_config():
    if not is_whatsapp_configured():
        raise WhatsAppConfigError(
            'WhatsApp Cloud API is not configured. Set WHATSAPP_ENABLED=true and '
            'WHATSAPP_PHONE_NUMBER_ID / WHATSAPP_ACCESS_TOKEN in your environment.',
        )


def _messages_url():
    phone_number_id = settings.WHATSAPP_PHONE_NUMBER_ID.strip()
    return (
        f'https://graph.facebook.com/{GRAPH_API_VERSION}/{phone_number_id}/messages'
    )


def _post_message(payload):
    backend = whatsapp_backend()
    if backend == 'console':
        logger.info('WhatsApp console send to %s: %s', payload.get('to'), payload)
        return {'mode': 'console', 'payload': payload}

    _require_cloud_config()
    headers = {
        'Authorization': f'Bearer {settings.WHATSAPP_ACCESS_TOKEN.strip()}',
        'Content-Type': 'application/json',
    }
    response = requests.post(_messages_url(), json=payload, headers=headers, timeout=30)
    try:
        data = response.json()
    except ValueError:
        data = {'raw': response.text}

    if not response.ok:
        error = data.get('error', {})
        message = error.get('message', 'WhatsApp API request failed')
        api_error = WhatsAppAPIError(message, response_data=data, status_code=response.status_code)
        if api_error.is_auth_error:
            logger.error('WhatsApp authentication failed: %s', message)
        raise api_error
    logger.info('WhatsApp message sent to %s', payload.get('to'))
    return data


def send_text(*, to: str, body: str):
    payload = {
        'messaging_product': 'whatsapp',
        'recipient_type': 'individual',
        'to': normalize_whatsapp_recipient(to),
        'type': 'text',
        'text': {'preview_url': True, 'body': body[:4096]},
    }
    return _post_message(payload)


def _media_upload_url():
    phone_number_id = settings.WHATSAPP_PHONE_NUMBER_ID.strip()
    return f'https://graph.facebook.com/{GRAPH_API_VERSION}/{phone_number_id}/media'


def upload_media(*, file_bytes: bytes, mime_type: str = 'image/jpeg', filename: str = 'product.jpg'):
    backend = whatsapp_backend()
    if backend == 'console':
        logger.info('WhatsApp console media upload (%s bytes)', len(file_bytes))
        return 'console-media-id'

    _require_cloud_config()
    headers = {'Authorization': f'Bearer {settings.WHATSAPP_ACCESS_TOKEN.strip()}'}
    response = requests.post(
        _media_upload_url(),
        headers=headers,
        data={'messaging_product': 'whatsapp', 'type': mime_type},
        files={'file': (filename, file_bytes, mime_type)},
        timeout=60,
    )
    try:
        data = response.json()
    except ValueError:
        data = {'raw': response.text}

    if not response.ok:
        message = data.get('error', {}).get('message', 'WhatsApp media upload failed')
        raise WhatsAppAPIError(message, response_data=data, status_code=response.status_code)
    media_id = data.get('id')
    if not media_id:
        raise WhatsAppAPIError('WhatsApp media upload did not return an id', response_data=data)
    return media_id


def send_image(*, to: str, image_url: str, caption: str = ''):
    image_payload = {'link': image_url}
    if caption:
        image_payload['caption'] = caption[:1024]
    payload = {
        'messaging_product': 'whatsapp',
        'recipient_type': 'individual',
        'to': normalize_whatsapp_recipient(to),
        'type': 'image',
        'image': image_payload,
    }
    return _post_message(payload)


def send_image_id(*, to: str, media_id: str, caption: str = ''):
    image_payload = {'id': media_id}
    if caption:
        image_payload['caption'] = caption[:1024]
    payload = {
        'messaging_product': 'whatsapp',
        'recipient_type': 'individual',
        'to': normalize_whatsapp_recipient(to),
        'type': 'image',
        'image': image_payload,
    }
    return _post_message(payload)


def mark_message_read(message_id: str):
    backend = whatsapp_backend()
    if backend == 'console':
        logger.debug('WhatsApp console mark read: %s', message_id)
        return {'mode': 'console'}

    _require_cloud_config()
    payload = {
        'messaging_product': 'whatsapp',
        'status': 'read',
        'message_id': message_id,
    }
    headers = {
        'Authorization': f'Bearer {settings.WHATSAPP_ACCESS_TOKEN.strip()}',
        'Content-Type': 'application/json',
    }
    response = requests.post(_messages_url(), json=payload, headers=headers, timeout=15)
    if not response.ok:
        logger.warning('Failed to mark WhatsApp message read: %s', response.text)
    return response.json() if response.content else {}
