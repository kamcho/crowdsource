from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from django.conf import settings

CURRENCY_USD = 'USD'
CURRENCY_KES = 'KES'
SUPPORTED_CURRENCIES = (CURRENCY_USD, CURRENCY_KES)


def get_exchange_rate():
    return Decimal(str(getattr(settings, 'USD_TO_KES_RATE', '135')))


def normalize_currency(code):
    code = (code or '').upper()
    return code if code in SUPPORTED_CURRENCIES else CURRENCY_USD


def get_display_currency(request):
    if request is None:
        return CURRENCY_USD
    return normalize_currency(request.session.get('currency'))


def set_display_currency(request, currency):
    request.session['currency'] = normalize_currency(currency)
    request.session.modified = True


def to_decimal(value):
    if value is None or value == '':
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def convert_usd_to_kes(amount_usd, rate=None):
    rate = rate or get_exchange_rate()
    amount = to_decimal(amount_usd) or Decimal('0')
    return int((amount * rate).quantize(Decimal('1'), rounding=ROUND_HALF_UP))


def format_kes(amount_usd, rate=None):
    kes = convert_usd_to_kes(amount_usd, rate)
    return f'KES {kes:,}'


def format_money(amount_usd, currency=CURRENCY_USD, rate=None):
    amount = to_decimal(amount_usd)
    if amount is None:
        return '—'
    currency = normalize_currency(currency)
    if currency == CURRENCY_KES:
        return format_kes(amount, rate)
    return f'${amount:.2f} ≈ {format_kes(amount, rate)}'


def format_money_range(price_min, price_max, currency=CURRENCY_USD, rate=None):
    minimum = to_decimal(price_min)
    if minimum is None:
        return '—'
    maximum = to_decimal(price_max)
    currency = normalize_currency(currency)
    if maximum is not None and minimum != maximum:
        return (
            f'{format_money(minimum, currency, rate)} – '
            f'{format_money(maximum, currency, rate)}'
        )
    return format_money(minimum, currency, rate)
