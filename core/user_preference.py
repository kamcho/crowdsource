from django.conf import settings
from django.db import models


class UserCategoryPreference(models.Model):
    class Source(models.TextChoices):
        MANUAL = 'manual', 'Manual'
        VIEWED = 'viewed', 'From browsing'
        ACTIVITY = 'activity', 'From activity'

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='category_preferences',
    )
    category = models.ForeignKey(
        'Category',
        on_delete=models.CASCADE,
        related_name='user_preferences',
    )
    source = models.CharField(
        max_length=20,
        choices=Source.choices,
        default=Source.MANUAL,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['user', 'category'],
                name='unique_user_category_preference',
            ),
        ]

    def __str__(self):
        return f'{self.user} prefers {self.category.name}'


class UserProductView(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='product_views',
    )
    product = models.ForeignKey(
        'Product',
        on_delete=models.CASCADE,
        related_name='user_views',
    )
    viewed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-viewed_at']
        indexes = [
            models.Index(fields=['user', 'product', '-viewed_at']),
        ]

    def __str__(self):
        return f'{self.user} viewed {self.product.name}'


class UserCategoryViewStat(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='category_view_stats',
    )
    category = models.ForeignKey(
        'Category',
        on_delete=models.CASCADE,
        related_name='user_view_stats',
    )
    view_count = models.PositiveIntegerField(default=0)
    last_viewed_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['user', 'category'],
                name='unique_user_category_view_stat',
            ),
        ]

    def __str__(self):
        return f'{self.user} · {self.category.name} ({self.view_count} views)'
