"""Safaricom Daraja M-Pesa STK Push client (Paybill).

Docs: https://developer.safaricom.co.ke/
Same integration pattern as Excel / Soma Smart projects.
"""

from __future__ import annotations

import base64
import logging
from datetime import datetime

import requests
from django.conf import settings

logger = logging.getLogger('crowdsource.mpesa')


class MpesaConfigError(Exception):
    """Raised when required M-Pesa settings are missing."""


class MpesaAPIError(Exception):
    """Raised when the Daraja API returns an error response."""

    def __init__(self, message, response_data=None):
        super().__init__(message)
        self.response_data = response_data or {}


def _mpesa_settings():
    required = {
        'MPESA_CONSUMER_KEY': getattr(settings, 'MPESA_CONSUMER_KEY', ''),
        'MPESA_CONSUMER_SECRET': getattr(settings, 'MPESA_CONSUMER_SECRET', ''),
        'MPESA_SHORTCODE': getattr(settings, 'MPESA_SHORTCODE', ''),
        'MPESA_PASSKEY': getattr(settings, 'MPESA_PASSKEY', ''),
    }
    missing = [key for key, value in required.items() if not value]
    if missing:
        raise MpesaConfigError(
            f'Missing M-Pesa configuration: {", ".join(missing)}. '
            'Set them in your .env file.',
        )
    return required


def mpesa_base_url():
    if getattr(settings, 'MPESA_ENVIRONMENT', 'sandbox') == 'production':
        return 'https://api.safaricom.co.ke'
    return 'https://sandbox.safaricom.co.ke'


def normalize_mpesa_phone(phone: str) -> str:
    """Normalize Kenyan numbers to 2547XXXXXXXX."""
    digits = ''.join(ch for ch in (phone or '') if ch.isdigit())
    if digits.startswith('254') and len(digits) == 12:
        return digits
    if digits.startswith('0') and len(digits) == 10:
        return f'254{digits[1:]}'
    if len(digits) == 9 and digits[0] in '17':
        return f'254{digits}'
    raise ValueError('Enter a valid Kenyan mobile number (e.g. 0712345678).')


def get_access_token() -> str:
    cfg = _mpesa_settings()
    url = f'{mpesa_base_url()}/oauth/v1/generate?grant_type=client_credentials'
    credentials = base64.b64encode(
        f'{cfg["MPESA_CONSUMER_KEY"]}:{cfg["MPESA_CONSUMER_SECRET"]}'.encode(),
    ).decode()
    response = requests.get(
        url,
        headers={'Authorization': f'Basic {credentials}'},
        timeout=30,
    )
    data = response.json()
    if response.status_code != 200 or 'access_token' not in data:
        logger.error('M-Pesa OAuth failed: %s', data)
        raise MpesaAPIError('Could not authenticate with M-Pesa.', data)
    return data['access_token']


def _build_password(shortcode: str, passkey: str, timestamp: str) -> str:
    raw = f'{shortcode}{passkey}{timestamp}'
    return base64.b64encode(raw.encode()).decode()


def mpesa_callback_url():
    base = getattr(settings, 'MPESA_CALLBACK_BASE_URL', '').strip().rstrip('/')
    if not base:
        raise MpesaConfigError(
            'MPESA_CALLBACK_BASE_URL is required for M-Pesa payments '
            '(public HTTPS URL, e.g. ngrok tunnel in dev).',
        )
    return f'{base}/payments/mpesa/callback/'


def initiate_stk_push(*, phone_number: str, amount: int, account_reference: str, description: str):
    """Trigger Lipa na M-Pesa Paybill STK push."""
    cfg = _mpesa_settings()
    token = get_access_token()
    timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
    shortcode = cfg['MPESA_SHORTCODE']

    payload = {
        'BusinessShortCode': shortcode,
        'Password': _build_password(shortcode, cfg['MPESA_PASSKEY'], timestamp),
        'Timestamp': timestamp,
        'TransactionType': 'CustomerPayBillOnline',
        'Amount': int(amount),
        'PartyA': phone_number,
        'PartyB': shortcode,
        'PhoneNumber': phone_number,
        'CallBackURL': mpesa_callback_url(),
        'AccountReference': account_reference[:12],
        'TransactionDesc': description[:13],
    }

    url = f'{mpesa_base_url()}/mpesa/stkpush/v1/processrequest'
    response = requests.post(
        url,
        json=payload,
        headers={'Authorization': f'Bearer {token}'},
        timeout=30,
    )
    data = response.json()
    if response.status_code != 200 or data.get('ResponseCode') != '0':
        logger.error('STK push failed: %s', data)
        raise MpesaAPIError(
            data.get('ResponseDescription', 'STK push request failed.'),
            data,
        )
    return data


def query_stk_status(checkout_request_id: str):
    """Query STK transaction status (for polling when callback is delayed)."""
    cfg = _mpesa_settings()
    token = get_access_token()
    timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
    shortcode = cfg['MPESA_SHORTCODE']
    payload = {
        'BusinessShortCode': shortcode,
        'Password': _build_password(shortcode, cfg['MPESA_PASSKEY'], timestamp),
        'Timestamp': timestamp,
        'CheckoutRequestID': checkout_request_id,
    }
    url = f'{mpesa_base_url()}/mpesa/stkpushquery/v1/query'
    response = requests.post(
        url,
        json=payload,
        headers={'Authorization': f'Bearer {token}'},
        timeout=30,
    )
    return response.json()


def parse_stk_callback(payload: dict):
    """Extract STK callback fields from Safaricom JSON body."""
    callback = payload.get('Body', {}).get('stkCallback', {})
    metadata_items = callback.get('CallbackMetadata', {}).get('Item', [])
    metadata = {}
    for item in metadata_items:
        name = item.get('Name')
        if name and 'Value' in item:
            metadata[name] = item['Value']

    return {
        'merchant_request_id': callback.get('MerchantRequestID', ''),
        'checkout_request_id': callback.get('CheckoutRequestID', ''),
        'result_code': callback.get('ResultCode'),
        'result_description': callback.get('ResultDesc', ''),
        'amount': metadata.get('Amount'),
        'mpesa_receipt_number': metadata.get('MpesaReceiptNumber', ''),
        'phone_number': metadata.get('PhoneNumber'),
        'transaction_date': metadata.get('TransactionDate'),
    }
