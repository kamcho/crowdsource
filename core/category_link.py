from django.db import models

from .models import Category


class CategoryGoTogetherLink(models.Model):
    """Merchandising link: products in linked categories pair well together."""

    source_category = models.ForeignKey(
        Category,
        on_delete=models.CASCADE,
        related_name='go_together_outgoing',
    )
    linked_category = models.ForeignKey(
        Category,
        on_delete=models.CASCADE,
        related_name='go_together_incoming',
    )
    sort_order = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['sort_order', 'linked_category__name']
        constraints = [
            models.UniqueConstraint(
                fields=['source_category', 'linked_category'],
                name='unique_category_go_together_link',
            ),
            models.CheckConstraint(
                condition=~models.Q(source_category=models.F('linked_category')),
                name='no_self_go_together_link',
            ),
        ]

    def __str__(self):
        return f'{self.source_category.name} → {self.linked_category.name}'
