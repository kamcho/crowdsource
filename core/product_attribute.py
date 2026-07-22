from django.db import models
from django.db.models import Q


class ProductAttribute(models.Model):
    product = models.ForeignKey(
        'Product',
        on_delete=models.CASCADE,
        related_name='attributes',
    )
    variation = models.ForeignKey(
        'ProductVariation',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='attributes',
    )
    title = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    sort_order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['sort_order', 'title']
        constraints = [
            models.UniqueConstraint(
                fields=['product', 'title'],
                condition=Q(variation__isnull=True),
                name='unique_product_level_attribute_title',
            ),
            models.UniqueConstraint(
                fields=['variation', 'title'],
                condition=Q(variation__isnull=False),
                name='unique_variation_attribute_title',
            ),
        ]

    def __str__(self):
        scope = self.variation.sku if self.variation_id else self.product.name
        return f'{scope} — {self.title}'

    def clean(self):
        from django.core.exceptions import ValidationError

        if self.variation_id and self.product_id and self.variation.product_id != self.product_id:
            raise ValidationError('Variation must belong to the selected product.')
