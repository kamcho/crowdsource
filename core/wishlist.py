from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class WishlistItem(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='wishlist_items',
    )
    product = models.ForeignKey(
        'Product',
        on_delete=models.CASCADE,
        related_name='wishlist_items',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['user', 'product'],
                name='unique_wishlist_item_per_product',
            ),
        ]

    def __str__(self):
        return f'{self.user} — {self.product.name}'

    def clean(self):
        if self.product_id and not self.product.is_active:
            raise ValidationError({'product': 'Cannot save an inactive product.'})
        if self.product_id and not self.product.category.is_active:
            raise ValidationError({'product': 'Cannot save a product from an inactive category.'})

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)
