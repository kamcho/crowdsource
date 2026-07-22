from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class Cart(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='cart',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at']

    def __str__(self):
        return f'Cart for {self.user}'

    @property
    def item_count(self):
        return self.items.aggregate(total=models.Sum('quantity'))['total'] or 0

    @property
    def subtotal(self):
        return sum(item.line_total for item in self.items.select_related('group_buy'))


class CartItem(models.Model):
    cart = models.ForeignKey(
        Cart,
        on_delete=models.CASCADE,
        related_name='items',
    )
    group_buy = models.ForeignKey(
        'GroupBuy',
        on_delete=models.CASCADE,
        related_name='cart_items',
    )
    variation = models.ForeignKey(
        'ProductVariation',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='cart_items',
    )
    quantity = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['cart', 'group_buy', 'variation'],
                name='unique_cart_item_per_variation',
            ),
        ]

    def __str__(self):
        label = self.variation.display_name if self.variation_id else 'Standard'
        return f'{self.quantity}× {label}'

    @property
    def unit_price(self):
        from core.pricing import resolve_unit_price
        return resolve_unit_price(self.group_buy, self.variation)

    @property
    def line_total(self):
        return Decimal(self.unit_price) * self.quantity

    @property
    def product(self):
        return self.group_buy.product

    def clean(self):
        if self.quantity < 1:
            raise ValidationError({'quantity': 'Quantity must be at least 1.'})

        if not self.group_buy_id:
            return

        if not self.group_buy.is_joinable:
            raise ValidationError('This group buy is no longer accepting new items.')

        if self.variation_id and self.variation.product_id != self.group_buy.product_id:
            raise ValidationError({'variation': 'Variation must belong to this product.'})

        product_has_variations = self.group_buy.product.variations.filter(is_active=True).exists()
        if product_has_variations and not self.variation_id:
            raise ValidationError({'variation': 'Select a product variation.'})
        if not product_has_variations and self.variation_id:
            raise ValidationError({'variation': 'This product has no variations.'})

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)
