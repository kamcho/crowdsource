from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Sum
from django.utils import timezone


class GroupBuy(models.Model):
    class Status(models.TextChoices):
        OPEN = 'open', 'Open'
        MOQ_REACHED = 'moq_reached', 'MOQ Reached'
        IMPORTING = 'importing', 'Importing'
        COMPLETED = 'completed', 'Completed'
        CANCELLED = 'cancelled', 'Cancelled'

    product = models.ForeignKey(
        'Product',
        on_delete=models.CASCADE,
        related_name='group_buys',
    )
    moq = models.PositiveIntegerField(help_text='Minimum total units required to unlock bulk import.')
    unit_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text='Bulk unit price once MOQ is met.',
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.OPEN,
    )
    closes_at = models.DateTimeField(help_text='Last date buyers can join this group buy.')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name_plural = 'group buys'

    def __str__(self):
        return f'{self.product.name} group buy ({self.get_status_display()})'

    @property
    def pledged_units(self):
        total = self.entries.aggregate(total=Sum('quantity'))['total']
        return total or 0

    @property
    def progress_percent(self):
        if self.moq == 0:
            return 100
        return min(int((self.pledged_units / self.moq) * 100), 100)

    @property
    def units_remaining(self):
        return max(self.moq - self.pledged_units, 0)

    @property
    def moq_reached(self):
        return self.pledged_units >= self.moq

    @property
    def is_joinable(self):
        return (
            self.status == self.Status.OPEN
            and timezone.now() < self.closes_at
            and not self.moq_reached
        )

    def user_pledged_units(self, user):
        if not user.is_authenticated:
            return 0
        total = self.entries.filter(user=user).aggregate(total=Sum('quantity'))['total']
        return total or 0

    def refresh_status(self):
        if self.status == self.Status.OPEN and self.moq_reached:
            self.status = self.Status.MOQ_REACHED
            self.save(update_fields=['status', 'updated_at'])

    def save(self, *args, **kwargs):
        old_status = None
        if self.pk:
            old_status = type(self).objects.filter(pk=self.pk).values_list('status', flat=True).first()
        super().save(*args, **kwargs)
        if old_status != self.status:
            from core.notification_services import notify_group_buy_cancelled, notify_moq_reached
            if self.status == self.Status.MOQ_REACHED and old_status == self.Status.OPEN:
                notify_moq_reached(self)
            elif self.status == self.Status.CANCELLED:
                notify_group_buy_cancelled(self)

    @property
    def import_status_message(self):
        try:
            batch = self.import_batch
        except Exception:
            batch = None
        if batch is not None:
            return batch.buyer_status_message
        if self.status == self.Status.MOQ_REACHED:
            return 'MOQ reached — awaiting import batch.'
        if self.status == self.Status.IMPORTING:
            return 'Import in progress.'
        if self.status == self.Status.COMPLETED:
            return 'Import complete — preparing deliveries.'
        if self.status == self.Status.OPEN:
            return f'{self.pledged_units} / {self.moq} units pledged overall'
        return ''


class GroupBuyEntry(models.Model):
    group_buy = models.ForeignKey(
        GroupBuy,
        on_delete=models.CASCADE,
        related_name='entries',
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='group_buy_entries',
    )
    variation = models.ForeignKey(
        'ProductVariation',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='group_buy_entries',
    )
    quantity = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['group_buy', 'user', 'variation'],
                name='unique_group_buy_entry_per_user_variation',
            ),
        ]

    def __str__(self):
        label = self.variation.display_name if self.variation_id else 'Standard'
        return f'{self.user} — {self.quantity}× {label}'

    @property
    def unit_price(self):
        from core.pricing import resolve_unit_price
        return resolve_unit_price(self.group_buy, self.variation)

    @property
    def line_total(self):
        from core.pricing import entry_line_total
        return entry_line_total(self)

    def clean(self):
        if self.quantity < 1:
            raise ValidationError({'quantity': 'Quantity must be at least 1.'})

        if not self.group_buy_id:
            return

        if not self.group_buy.is_joinable and not self.pk:
            raise ValidationError('This group buy is no longer accepting pledges.')

        if self.variation_id and self.variation.product_id != self.group_buy.product_id:
            raise ValidationError({'variation': 'Variation must belong to this product.'})

        product_has_variations = self.group_buy.product.variations.filter(is_active=True).exists()
        if product_has_variations and not self.variation_id:
            raise ValidationError({'variation': 'Select a product variation.'})
        if not product_has_variations and self.variation_id:
            raise ValidationError({'variation': 'This product has no variations.'})

        if not product_has_variations:
            duplicate = GroupBuyEntry.objects.filter(
                group_buy=self.group_buy,
                user=self.user,
                variation__isnull=True,
            ).exclude(pk=self.pk)
            if duplicate.exists():
                raise ValidationError('You already have a pledge for this product. Update the quantity instead.')

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)
        self.group_buy.refresh_status()

    def delete(self, *args, **kwargs):
        group_buy = self.group_buy
        super().delete(*args, **kwargs)
        if group_buy.status == GroupBuy.Status.MOQ_REACHED and not group_buy.moq_reached:
            group_buy.status = GroupBuy.Status.OPEN
            group_buy.save(update_fields=['status', 'updated_at'])
