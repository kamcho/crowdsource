from django import template

from core.currency import format_money, format_money_range

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
def money_from(context, amount):
    formatted = format_money(
        amount,
        context.get('display_currency'),
        context.get('usd_to_kes_rate'),
    )
    return f'From {formatted}'
