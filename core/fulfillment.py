from django.db import models
from django.utils import timezone


class Fulfillment(models.Model):
    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        PACKED = 'packed', 'Packed'
        OUT_FOR_DELIVERY = 'out_for_delivery', 'Out for delivery'
        DELIVERED = 'delivered', 'Delivered'
        FAILED = 'failed', 'Failed'

    STATUS_PROGRESS = {
        Status.PENDING: 10,
        Status.PACKED: 35,
        Status.OUT_FOR_DELIVERY: 70,
        Status.DELIVERED: 100,
        Status.FAILED: 0,
    }

    order = models.OneToOneField(
        'Order',
        on_delete=models.CASCADE,
        related_name='fulfillment',
    )
    import_batch = models.ForeignKey(
        'ImportBatch',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='fulfillments',
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )
    tracking_reference = models.CharField(max_length=100, blank=True)
    notes = models.TextField(blank=True)
    shipped_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'Fulfillment for order #{self.order_id} ({self.get_status_display()})'

    @property
    def progress_percent(self):
        return self.STATUS_PROGRESS.get(self.status, 0)

    @property
    def buyer_status_message(self):
        messages = {
            self.Status.PENDING: 'Your order is queued for packing after import.',
            self.Status.PACKED: 'Your order has been packed and is awaiting dispatch.',
            self.Status.OUT_FOR_DELIVERY: 'Your order is out for delivery.',
            self.Status.DELIVERED: 'Your order was delivered successfully.',
            self.Status.FAILED: 'Delivery attempt failed — our team will contact you.',
        }
        return messages.get(self.status, self.get_status_display())

    def save(self, *args, **kwargs):
        now = timezone.now()
        if self.status in (self.Status.OUT_FOR_DELIVERY, self.Status.DELIVERED) and not self.shipped_at:
            self.shipped_at = now
        if self.status == self.Status.DELIVERED and not self.delivered_at:
            self.delivered_at = now
        super().save(*args, **kwargs)
