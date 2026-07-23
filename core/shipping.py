from decimal import Decimal

from django.db import models


class ShippingRate(models.Model):
    class Mode(models.TextChoices):
        AIR = 'air', 'Air freight'
        SEA = 'sea', 'Sea freight'

    class GoodsClass(models.TextChoices):
        NORMAL = 'normal', 'Normal goods'
        SPECIAL = 'special', 'Special goods'

    class ChargeBasis(models.TextChoices):
        PER_KG = 'per_kg', 'Per kilogram'
        PER_CBM = 'per_cbm', 'Per CBM'

    mode = models.CharField(max_length=10, choices=Mode.choices)
    goods_class = models.CharField(max_length=10, choices=GoodsClass.choices)
    charge_basis = models.CharField(max_length=10, choices=ChargeBasis.choices)
    rate = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=3, default='USD')
    is_active = models.BooleanField(default=True)
    notes = models.CharField(max_length=255, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['mode', 'goods_class']
        constraints = [
            models.UniqueConstraint(
                fields=['mode', 'goods_class'],
                name='unique_shipping_rate_mode_class',
            ),
        ]

    def __str__(self):
        return (
            f'{self.get_mode_display()} · {self.get_goods_class_display()} · '
            f'{self.currency} {self.rate}/{self.get_charge_basis_display()}'
        )

    @property
    def unit_label(self):
        if self.charge_basis == self.ChargeBasis.PER_KG:
            return 'kg'
        return 'CBM'
