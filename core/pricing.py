from decimal import Decimal


def resolve_unit_price(group_buy, variation=None):
    """Return the unit price for a pledge, cart line, or order item."""
    if variation is not None:
        return Decimal(variation.price)
    return Decimal(group_buy.unit_price)


def entry_line_total(entry):
    return resolve_unit_price(entry.group_buy, entry.variation) * entry.quantity


def pledge_checkout_total(entries, group_buy):
    return sum(entry_line_total(entry) for entry in entries)


def product_variation_price_range(product):
    prices = [
        variation.price
        for variation in product.active_variations
    ]
    if not prices:
        return None, None
    return min(prices), max(prices)


def format_price_range(price_min, price_max):
    if price_min is None:
        return ''
    if price_max is not None and price_min != price_max:
        return f'${price_min} – ${price_max}'
    return f'${price_min}'
