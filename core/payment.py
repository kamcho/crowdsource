import uuid
from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils import timezone


class Payment(models.Model):
    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        COMPLETED = 'completed', 'Completed'
        FAILED = 'failed', 'Failed'
        CANCELLED = 'cancelled', 'Cancelled'

    group_buy = models.ForeignKey(
        'GroupBuy',
        on_delete=models.PROTECT,
        related_name='payments',
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='payments',
    )
    order = models.OneToOneField(
        'Order',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='payment',
    )
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )
    reference = models.CharField(max_length=40, unique=True, editable=False)
    provider = models.CharField(max_length=50, blank=True, default='demo')
    amount_kes = models.PositiveIntegerField(null=True, blank=True)
    phone_number = models.CharField(max_length=20, blank=True)
    merchant_request_id = models.CharField(max_length=64, blank=True, db_index=True)
    checkout_request_id = models.CharField(max_length=64, blank=True, db_index=True)
    mpesa_receipt_number = models.CharField(max_length=32, blank=True)
    result_code = models.IntegerField(null=True, blank=True)
    result_description = models.CharField(max_length=255, blank=True)
    callback_payload = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'Payment {self.reference} ({self.get_status_display()})'

    def save(self, *args, **kwargs):
        if not self.reference:
            self.reference = self._generate_reference()
        super().save(*args, **kwargs)

    @staticmethod
    def _generate_reference():
        return f'CS-{uuid.uuid4().hex[:12].upper()}'

    def mark_completed(self, order):
        self.order = order
        self.status = self.Status.COMPLETED
        self.completed_at = timezone.now()
        self.save(update_fields=['order', 'status', 'completed_at'])

    @property
    def stk_push_initiated(self):
        return bool(self.checkout_request_id)
