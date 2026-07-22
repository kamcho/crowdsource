from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class Order(models.Model):
    class Status(models.TextChoices):
        PENDING_PAYMENT = 'pending_payment', 'Pending Payment'
        PAID = 'paid', 'Paid'
        REFUNDED = 'refunded', 'Refunded'
        CANCELLED = 'cancelled', 'Cancelled'

    group_buy = models.ForeignKey(
        'GroupBuy',
        on_delete=models.PROTECT,
        related_name='orders',
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='orders',
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING_PAYMENT,
    )
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    delivery_address = models.ForeignKey(
        'Address',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='orders',
    )
    delivery_recipient_name = models.CharField(max_length=150, blank=True)
    delivery_phone = models.CharField(max_length=32, blank=True)
    delivery_county = models.CharField(max_length=100, blank=True)
    delivery_area = models.CharField(max_length=100, blank=True)
    delivery_street = models.CharField(max_length=255, blank=True)
    delivery_notes = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'Order #{self.pk} — {self.user} ({self.get_status_display()})'

    @property
    def product(self):
        return self.group_buy.product

    def recalculate_total(self):
        total = sum(item.line_total for item in self.items.all())
        self.total_amount = total
        self.save(update_fields=['total_amount', 'updated_at'])

    def apply_delivery_address(self, address):
        self.delivery_address = address
        for field, value in address.snapshot_fields().items():
            setattr(self, field, value)

    @property
    def has_delivery_address(self):
        return bool(self.delivery_street or self.delivery_area)

    @property
    def delivery_formatted(self):
        parts = [
            self.delivery_street,
            self.delivery_area,
            self.delivery_county,
        ]
        return ', '.join(part for part in parts if part)

    @property
    def refunded_amount(self):
        from core.refund_services import get_order_refunded_amount
        return get_order_refunded_amount(self)

    @property
    def refundable_amount(self):
        from core.refund_services import get_order_refundable_amount
        return get_order_refundable_amount(self)


class OrderItem(models.Model):
    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name='items',
    )
    variation = models.ForeignKey(
        'ProductVariation',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='order_items',
    )
    quantity = models.PositiveIntegerField()
    unit_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text='Locked unit price at order creation.',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['id']
        constraints = [
            models.UniqueConstraint(
                fields=['order', 'variation'],
                name='unique_order_item_per_variation',
            ),
        ]

    def __str__(self):
        label = self.variation.display_name if self.variation_id else 'Standard'
        return f'{self.quantity}× {label}'

    @property
    def line_total(self):
        return Decimal(self.unit_price) * self.quantity

    def clean(self):
        if self.quantity < 1:
            raise ValidationError({'quantity': 'Quantity must be at least 1.'})

        if self.variation_id and self.order_id:
            if self.variation.product_id != self.order.group_buy.product_id:
                raise ValidationError({'variation': 'Variation must belong to this product.'})
