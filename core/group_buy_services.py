from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from core.group_buy import GroupBuy
from core.models import Product
from core.pricing import product_variation_price_range


DEFAULT_GROUP_BUY_MOQ = 100
DEFAULT_GROUP_BUY_DAYS = 30


def default_group_buy_unit_price(product):
    price_min, _ = product_variation_price_range(product)
    if price_min is not None:
        return price_min
    return Decimal('0.01')


def _active_group_buy_for_product(product):
    return product.group_buys.filter(
        status__in=[GroupBuy.Status.OPEN, GroupBuy.Status.MOQ_REACHED],
    ).order_by('-created_at').first()


@transaction.atomic
def ensure_default_group_buy_for_product(product, *, moq=None, closes_at=None):
    """Create an open group buy when a product has none yet."""
    product = Product.objects.select_for_update().get(pk=product.pk)
    active = _active_group_buy_for_product(product)
    if active:
        return active

    return GroupBuy.objects.create(
        product=product,
        moq=moq or DEFAULT_GROUP_BUY_MOQ,
        unit_price=default_group_buy_unit_price(product),
        status=GroupBuy.Status.OPEN,
        closes_at=closes_at or (timezone.now() + timedelta(days=DEFAULT_GROUP_BUY_DAYS)),
    )
