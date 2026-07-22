"""TextSMS (textsms.co.ke) API client.

Docs: https://textsms.co.ke/bulk-sms-api/
Endpoint: POST https://sms.textsms.co.ke/api/services/sendsms/
"""

from __future__ import annotations

import logging
import re

import requests
from django.conf import settings

logger = logging.getLogger('crowdsource.notifications')

SEND_SMS_URL = 'https://sms.textsms.co.ke/api/services/sendsms/'


class TextSmsConfigError(Exception):
    """Raised when required TextSMS settings are missing."""


class TextSmsAPIError(Exception):
    """Raised when the TextSMS API returns an error response."""

    def __init__(self, message, response_data=None):
        super().__init__(message)
        self.response_data = response_data or {}


def _textsms_settings():
    required = {
        'TEXTSMS_API_KEY': getattr(settings, 'TEXTSMS_API_KEY', ''),
        'TEXTSMS_PARTNER_ID': getattr(settings, 'TEXTSMS_PARTNER_ID', ''),
        'TEXTSMS_SHORTCODE': getattr(settings, 'TEXTSMS_SHORTCODE', ''),
    }
    missing = [key for key, value in required.items() if not value]
    if missing:
        raise TextSmsConfigError(
            f'Missing TextSMS configuration: {", ".join(missing)}. '
            'Set them in your .env file.',
        )
    return required


def normalize_kenyan_mobile(phone: str) -> str:
    """
    Normalize a Kenyan phone number to 254XXXXXXXXX for TextSMS.
    Accepts 07..., +254..., or 254... formats.
    """
    digits = re.sub(r'\D', '', phone or '')
    if digits.startswith('254') and len(digits) == 12:
        return digits
    if digits.startswith('0') and len(digits) == 10:
        return f'254{digits[1:]}'
    if len(digits) == 9:
        return f'254{digits}'
    raise ValueError(f'Invalid Kenyan mobile number: {phone}')


def send_sms(*, mobile: str, message: str) -> dict:
    """
    Send a single SMS via TextSMS POST API.
    Returns parsed response metadata including message_id.
    """
    config = _textsms_settings()
    normalized_mobile = normalize_kenyan_mobile(mobile)

    payload = {
        'apikey': config['TEXTSMS_API_KEY'],
        'partnerID': config['TEXTSMS_PARTNER_ID'],
        'message': message,
        'shortcode': config['TEXTSMS_SHORTCODE'],
        'mobile': normalized_mobile,
        'pass_type': 'plain',
    }

    try:
        response = requests.post(
            SEND_SMS_URL,
            json=payload,
            headers={'Content-Type': 'application/json'},
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()
    except requests.RequestException as exc:
        logger.exception('TextSMS request failed for %s', normalized_mobile)
        raise TextSmsAPIError(str(exc)) from exc
    except ValueError as exc:
        raise TextSmsAPIError('Invalid JSON response from TextSMS') from exc

    responses = data.get('responses') or []
    if not responses:
        raise TextSmsAPIError('Empty response from TextSMS', data)

    first = responses[0]
    code = first.get('respose-code') or first.get('response-code')
    if str(code) != '200':
        description = first.get('response-description', 'SMS send failed')
        raise TextSmsAPIError(description, data)

    return {
        'mobile': first.get('mobile', normalized_mobile),
        'message_id': str(first.get('messageid', '')),
        'description': first.get('response-description', 'Success'),
        'raw': data,
    }
