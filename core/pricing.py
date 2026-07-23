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


def build_price_tiers(product, group_buy=None):
    """Build Alibaba-style price columns from variation prices."""
    tiers = []
    variations = list(product.variations.filter(is_active=True).order_by('price', 'sku'))
    if variations:
        current_price = None
        bucket = []
        for variation in variations:
            if current_price is not None and variation.price != current_price:
                tiers.append(_price_tier_from_bucket(bucket))
                bucket = []
            current_price = variation.price
            bucket.append(variation)
        if bucket:
            tiers.append(_price_tier_from_bucket(bucket))
    elif group_buy is not None:
        tiers.append({
            'price': group_buy.unit_price,
            'label': f'≥{group_buy.moq} units',
        })
    return tiers[:4]


def _price_tier_from_bucket(variations):
    if len(variations) == 1:
        label = variations[0].display_name
        if len(label) > 36:
            label = f'{label[:33]}…'
    else:
        label = f'{len(variations)} options'
    return {
        'price': variations[0].price,
        'label': label,
    }
