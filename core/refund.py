import uuid
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Sum
from django.utils import timezone


# PRODUCTION: Replace manual completion with Safaricom Daraja Reversal API
# before marking refunds as completed. See refund_services.complete_refund().
MPESA_REVERSAL_REQUIRED_IN_PRODUCTION = True


class Refund(models.Model):
    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        COMPLETED = 'completed', 'Completed'
        FAILED = 'failed', 'Failed'
        CANCELLED = 'cancelled', 'Cancelled'

    class RefundType(models.TextChoices):
        FULL = 'full', 'Full refund'
        PARTIAL = 'partial', 'Partial refund'

    payment = models.ForeignKey(
        'Payment',
        on_delete=models.PROTECT,
        related_name='refunds',
    )
    order = models.ForeignKey(
        'Order',
        on_delete=models.PROTECT,
        related_name='refunds',
    )
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    refund_type = models.CharField(max_length=20, choices=RefundType.choices)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )
    reason = models.CharField(max_length=255)
    reference = models.CharField(max_length=40, unique=True, editable=False)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='refunds_created',
    )
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'Refund {self.reference} ({self.get_status_display()})'

    def save(self, *args, **kwargs):
        if not self.reference:
            self.reference = self._generate_reference()
        super().save(*args, **kwargs)

    @staticmethod
    def _generate_reference():
        return f'RF-{uuid.uuid4().hex[:12].upper()}'

    @property
    def is_completed(self):
        return self.status == self.Status.COMPLETED
