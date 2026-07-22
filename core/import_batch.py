from django.db import models
from django.utils import timezone


class ImportBatch(models.Model):
    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        ORDERED = 'ordered', 'Ordered from supplier'
        IN_TRANSIT = 'in_transit', 'In transit'
        CUSTOMS = 'customs', 'In customs'
        RECEIVED = 'received', 'Received locally'
        CANCELLED = 'cancelled', 'Cancelled'

    ACTIVE_STATUSES = {
        Status.PENDING,
        Status.ORDERED,
        Status.IN_TRANSIT,
        Status.CUSTOMS,
    }

    STATUS_PROGRESS = {
        Status.PENDING: 10,
        Status.ORDERED: 30,
        Status.IN_TRANSIT: 55,
        Status.CUSTOMS: 75,
        Status.RECEIVED: 100,
        Status.CANCELLED: 0,
    }

    group_buy = models.OneToOneField(
        'GroupBuy',
        on_delete=models.CASCADE,
        related_name='import_batch',
    )
    supplier = models.ForeignKey(
        'Supplier',
        on_delete=models.PROTECT,
        related_name='import_batches',
        null=True,
        blank=True,
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )
    supplier_reference = models.CharField(
        max_length=100,
        blank=True,
        help_text='Factory or supplier order reference.',
    )
    estimated_arrival = models.DateField(null=True, blank=True)
    arrived_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name_plural = 'import batches'

    def __str__(self):
        return f'Import batch #{self.pk} — {self.group_buy.product.name} ({self.get_status_display()})'

    @property
    def progress_percent(self):
        return self.STATUS_PROGRESS.get(self.status, 0)

    @property
    def buyer_status_message(self):
        messages = {
            self.Status.PENDING: 'Bulk import scheduled — supplier order being prepared.',
            self.Status.ORDERED: 'Bulk order placed with supplier.',
            self.Status.IN_TRANSIT: 'Shipment in transit from China.',
            self.Status.CUSTOMS: 'Shipment clearing customs.',
            self.Status.RECEIVED: 'Import arrived locally — preparing your delivery.',
            self.Status.CANCELLED: 'Import batch cancelled — please contact support.',
        }
        return messages.get(self.status, self.get_status_display())

    def save(self, *args, **kwargs):
        is_new = self.pk is None
        old_status = None
        if not is_new:
            old_status = type(self).objects.filter(pk=self.pk).values_list('status', flat=True).first()

        if self.status == self.Status.RECEIVED and not self.arrived_at:
            self.arrived_at = timezone.now()
        super().save(*args, **kwargs)
        self._sync_group_buy_status()

        from core.notification_services import (
            notify_import_batch_created,
            notify_import_batch_status_changed,
        )
        if is_new:
            notify_import_batch_created(self)
        elif old_status and old_status != self.status:
            notify_import_batch_status_changed(self, old_status, self.status)

    def _sync_group_buy_status(self):
        from core.group_buy import GroupBuy

        group_buy = self.group_buy
        if self.status == self.Status.CANCELLED:
            return

        if self.status == self.Status.RECEIVED:
            if group_buy.status != GroupBuy.Status.COMPLETED:
                group_buy.status = GroupBuy.Status.COMPLETED
                group_buy.save(update_fields=['status', 'updated_at'])
            from core.fulfillment_services import link_fulfillments_to_import_batch
            link_fulfillments_to_import_batch(self)
            return

        if self.status in self.ACTIVE_STATUSES:
            if group_buy.status in (GroupBuy.Status.MOQ_REACHED, GroupBuy.Status.IMPORTING):
                group_buy.status = GroupBuy.Status.IMPORTING
                group_buy.save(update_fields=['status', 'updated_at'])
