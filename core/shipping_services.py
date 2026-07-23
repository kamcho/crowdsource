import re
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP

from core.currency import convert_usd_to_kes, get_exchange_rate, to_decimal
from core.shipping import ShippingRate


DIMENSION_PATTERN = re.compile(
    r'(\d+(?:\.\d+)?)\s*[xX×]\s*(\d+(?:\.\d+)?)\s*[xX×]\s*(\d+(?:\.\d+)?)\s*(cm|mm|m)?',
    re.IGNORECASE,
)
WEIGHT_PATTERN = re.compile(
    r'(\d+(?:\.\d+)?)\s*(kg|g|lb|lbs)?',
    re.IGNORECASE,
)

WEIGHT_TITLE_HINTS = ('gross weight', 'net weight', 'weight', 'unit weight')
DIMENSION_TITLE_HINTS = (
    'single package size',
    'package size',
    'carton size',
    'dimensions',
    'dimension',
    'size',
)


@dataclass
class PackageSpecs:
    weight_kg: Decimal | None = None
    length_cm: Decimal | None = None
    width_cm: Decimal | None = None
    height_cm: Decimal | None = None

    @property
    def cbm(self):
        if self.length_cm is None or self.width_cm is None or self.height_cm is None:
            return None
        length_m = self.length_cm / Decimal('100')
        width_m = self.width_cm / Decimal('100')
        height_m = self.height_cm / Decimal('100')
        return (length_m * width_m * height_m).quantize(Decimal('0.000001'))

    @property
    def dimensions_display(self):
        if self.length_cm is None or self.width_cm is None or self.height_cm is None:
            return ''
        return (
            f'{self.length_cm.normalize()} × {self.width_cm.normalize()} × '
            f'{self.height_cm.normalize()} cm'
        )

    def as_dict(self):
        return {
            'weight_kg': _decimal_to_str(self.weight_kg),
            'length_cm': _decimal_to_str(self.length_cm),
            'width_cm': _decimal_to_str(self.width_cm),
            'height_cm': _decimal_to_str(self.height_cm),
            'cbm': _decimal_to_str(self.cbm),
            'dimensions_display': self.dimensions_display,
        }


def _decimal_to_str(value):
    if value is None:
        return None
    normalized = value.normalize()
    text = format(normalized, 'f')
    if '.' in text:
        text = text.rstrip('0').rstrip('.')
    return text


def _title_matches(title, hints):
    lowered = (title or '').strip().lower()
    return any(hint in lowered for hint in hints)


def _parse_weight_kg(raw_value):
    if not raw_value:
        return None
    match = WEIGHT_PATTERN.search(str(raw_value).replace(',', ''))
    if not match:
        return None
    amount = Decimal(match.group(1))
    unit = (match.group(2) or 'kg').lower()
    if unit == 'g':
        return (amount / Decimal('1000')).quantize(Decimal('0.000001'))
    if unit in ('lb', 'lbs'):
        return (amount * Decimal('0.453592')).quantize(Decimal('0.000001'))
    return amount.quantize(Decimal('0.000001'))


def _parse_dimensions_cm(raw_value):
    if not raw_value:
        return None, None, None
    match = DIMENSION_PATTERN.search(str(raw_value).replace(',', ''))
    if not match:
        return None, None, None
    length = Decimal(match.group(1))
    width = Decimal(match.group(2))
    height = Decimal(match.group(3))
    unit = (match.group(4) or 'cm').lower()
    if unit == 'mm':
        length /= Decimal('10')
        width /= Decimal('10')
        height /= Decimal('10')
    elif unit == 'm':
        length *= Decimal('100')
        width *= Decimal('100')
        height *= Decimal('100')
    return length, width, height


def _attribute_field(attribute, field):
    if isinstance(attribute, dict):
        return attribute.get(field, '')
    return getattr(attribute, field, '')


def extract_package_specs(attributes):
    specs = PackageSpecs()
    for attribute in attributes:
        title = _attribute_field(attribute, 'title')
        description = _attribute_field(attribute, 'description')
        if _title_matches(title, WEIGHT_TITLE_HINTS) and specs.weight_kg is None:
            specs.weight_kg = _parse_weight_kg(description)
        if _title_matches(title, DIMENSION_TITLE_HINTS) and specs.length_cm is None:
            length, width, height = _parse_dimensions_cm(description)
            specs.length_cm = length
            specs.width_cm = width
            specs.height_cm = height
    return specs


def get_product_package_specs(product, variation=None):
    attributes = list(product.product_attributes)
    if variation is not None:
        attributes = list(variation.attributes.all()) + attributes
    return extract_package_specs(attributes)


def get_goods_class(product):
    return ShippingRate.GoodsClass.SPECIAL if product.is_special_class else ShippingRate.GoodsClass.NORMAL


def get_active_shipping_rate(mode, goods_class):
    return ShippingRate.objects.filter(
        mode=mode,
        goods_class=goods_class,
        is_active=True,
    ).first()


def get_shipping_rates_payload():
    payload = {'air': {}, 'sea': {}}
    for rate in ShippingRate.objects.filter(is_active=True):
        payload[rate.mode][rate.goods_class] = {
            'rate': _decimal_to_str(rate.rate),
            'currency': rate.currency,
            'charge_basis': rate.charge_basis,
            'unit_label': rate.unit_label,
            'label': str(rate),
        }
    return payload


def format_shipping_amount(amount, currency, rate=None):
    amount = to_decimal(amount) or Decimal('0')
    currency = (currency or 'USD').upper()
    if currency == 'KES':
        kes = int(amount.quantize(Decimal('1'), rounding=ROUND_HALF_UP))
        return f'KES {kes:,}'
    return f'${amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)}'


def get_estimated_arrival(mode, is_special_class=False):
    """Typical in-transit window after dispatch from origin."""
    if mode == ShippingRate.Mode.SEA or mode == 'sea':
        return '30–35 days'
    if is_special_class:
        return '10–14 days'
    return '3–5 days'


def calculate_shipping_estimate(product, *, mode, quantity=1, variation=None):
    quantity = max(int(quantity or 1), 1)
    goods_class = get_goods_class(product)
    shipping_rate = get_active_shipping_rate(mode, goods_class)
    if not shipping_rate:
        return {
            'ok': False,
            'error': 'Shipping rate is not configured for this product class.',
        }

    specs = get_product_package_specs(product, variation)
    exchange_rate = get_exchange_rate()

    if shipping_rate.mode == ShippingRate.Mode.AIR:
        if specs.weight_kg is None:
            return {
                'ok': False,
                'error': 'Add a weight attribute (e.g. Single gross weight) to calculate air freight.',
                'specs': specs.as_dict(),
            }
        billable_units = specs.weight_kg * Decimal(quantity)
        total = (billable_units * shipping_rate.rate).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        basis_label = f'{_decimal_to_str(billable_units)} kg total'
    else:
        if specs.cbm is None:
            return {
                'ok': False,
                'error': 'Add a package size attribute (e.g. 40X35X2 cm) to calculate sea freight.',
                'specs': specs.as_dict(),
            }
        billable_units = specs.cbm * Decimal(quantity)
        total = (billable_units * shipping_rate.rate).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        basis_label = f'{_decimal_to_str(billable_units)} CBM total'

    total_usd = total
    total_kes = None
    if shipping_rate.currency == 'KES':
        total_kes = int(total.quantize(Decimal('1'), rounding=ROUND_HALF_UP))
        total_usd = (total / exchange_rate).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    else:
        total_kes = convert_usd_to_kes(total, exchange_rate)

    return {
        'ok': True,
        'mode': mode,
        'goods_class': goods_class,
        'quantity': quantity,
        'specs': specs.as_dict(),
        'rate': {
            'amount': _decimal_to_str(shipping_rate.rate),
            'currency': shipping_rate.currency,
            'charge_basis': shipping_rate.charge_basis,
            'unit_label': shipping_rate.unit_label,
        },
        'billable_units': _decimal_to_str(billable_units),
        'basis_label': basis_label,
        'total_usd': _decimal_to_str(total_usd),
        'total_kes': total_kes,
        'total_display': format_shipping_amount(total, shipping_rate.currency, exchange_rate),
        'total_usd_display': format_shipping_amount(total_usd, 'USD', exchange_rate),
        'total_kes_display': format_shipping_amount(total_kes, 'KES', exchange_rate),
        'is_special_class': product.is_special_class,
        'estimated_arrival': get_estimated_arrival(mode, product.is_special_class),
    }


def build_shipping_calculator_context(product, variation=None, quantity=1, mode='air'):
    estimate = calculate_shipping_estimate(
        product,
        mode=mode,
        quantity=quantity,
        variation=variation,
    )
    variation_package_specs = {}
    for product_variation in product.variations.filter(is_active=True).prefetch_related('attributes'):
        variation_package_specs[str(product_variation.pk)] = get_product_package_specs(
            product,
            product_variation,
        ).as_dict()

    specs = get_product_package_specs(product, variation)

    return {
        'shipping_rates': get_shipping_rates_payload(),
        'shipping_estimate': estimate,
        'package_specs': specs.as_dict(),
        'shipping_needs_weight': specs.weight_kg is None,
        'shipping_needs_size': specs.cbm is None,
        'variation_package_specs': variation_package_specs,
        'goods_class': get_goods_class(product),
        'is_special_class': product.is_special_class,
    }
