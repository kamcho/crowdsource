from django import template

from core.currency import format_kes, format_money, format_money_range, get_exchange_rate, to_decimal

register = template.Library()


@register.simple_tag(takes_context=True)
def money(context, amount):
    return format_money(
        amount,
        context.get('display_currency'),
        context.get('usd_to_kes_rate'),
    )


@register.simple_tag(takes_context=True)
def money_range(context, price_min, price_max=None):
    return format_money_range(
        price_min,
        price_max,
        context.get('display_currency'),
        context.get('usd_to_kes_rate'),
    )


@register.simple_tag(takes_context=True)
def money_kes(context, amount):
    rate = context.get('usd_to_kes_rate') or get_exchange_rate()
    return format_kes(amount, rate)


@register.simple_tag(takes_context=True)
def usd_hint(context, amount):
    value = to_decimal(amount)
    if value is None:
        return ''
    return f'≈ ${value:.2f}'


@register.simple_tag(takes_context=True)
def money_from(context, amount):
    formatted = format_money(
        amount,
        context.get('display_currency'),
        context.get('usd_to_kes_rate'),
    )
    return f'From {formatted}'


@register.filter
def lookup(mapping, key):
    if not mapping:
        return None
    return mapping.get(str(key))


@register.filter
def import_margin_display(margin):
    """Human-readable margin % for import costing (avoids noisy huge percentages)."""
    if margin is None:
        return ''
    try:
        value = float(margin)
    except (TypeError, ValueError):
        return ''
    if value > 500:
        return 'Unreliable — add supplier unit cost'
    if value < 0:
        return f'{value:.1f}% (below landed cost)'
    return f'{value:.1f}% margin at current price'


@register.filter
def decimal_percent(value, places=0):
    if value is None:
        return ''
    try:
        number = float(value)
    except (TypeError, ValueError):
        return ''
    fmt = f'{{:.{int(places)}f}}'
    return fmt.format(number)


@register.filter
def in_list(value, collection):
    if not collection:
        return False
    try:
        return value in collection
    except TypeError:
        return False
