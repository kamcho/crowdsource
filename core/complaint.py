import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class Complaint(models.Model):
    class Category(models.TextChoices):
        DELIVERY = 'delivery', 'Delivery issue'
        PRODUCT_QUALITY = 'product_quality', 'Product quality'
        PAYMENT = 'payment', 'Payment issue'
        WRONG_ITEM = 'wrong_item', 'Wrong item received'
        MISSING_ITEM = 'missing_item', 'Missing item'
        OTHER = 'other', 'Other'

    class Status(models.TextChoices):
        OPEN = 'open', 'Open'
        IN_PROGRESS = 'in_progress', 'In progress'
        RESOLVED = 'resolved', 'Resolved'
        CLOSED = 'closed', 'Closed'

    reference = models.CharField(max_length=40, unique=True, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='complaints',
    )
    order = models.ForeignKey(
        'Order',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='complaints',
    )
    category = models.CharField(max_length=30, choices=Category.choices)
    subject = models.CharField(max_length=200)
    description = models.TextField()
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.OPEN,
    )
    staff_notes = models.TextField(
        blank=True,
        help_text='Internal notes for ops — not shown to the customer.',
    )
    resolved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'Complaint {self.reference} ({self.get_status_display()})'

    def save(self, *args, **kwargs):
        if not self.reference:
            self.reference = self._generate_reference()
        super().save(*args, **kwargs)

    @staticmethod
    def _generate_reference():
        return f'CP-{uuid.uuid4().hex[:12].upper()}'

    @property
    def is_open(self):
        return self.status in {self.Status.OPEN, self.Status.IN_PROGRESS}

    def clean(self):
        if self.order_id and self.user_id and self.order.user_id != self.user_id:
            raise ValidationError({'order': 'Order must belong to this customer.'})


class ComplaintMessage(models.Model):
    complaint = models.ForeignKey(
        Complaint,
        on_delete=models.CASCADE,
        related_name='messages',
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='complaint_messages',
    )
    body = models.TextField()
    is_staff_reply = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        role = 'Staff' if self.is_staff_reply else 'Customer'
        return f'{role} message on {self.complaint.reference}'
