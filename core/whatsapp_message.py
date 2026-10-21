from django.db import models

from tenants.models import TenantOwnedModel


class WhatsAppMessage(TenantOwnedModel):
    class Direction(models.TextChoices):
        INBOUND = 'inbound', 'Inbound'
        OUTBOUND = 'outbound', 'Outbound'

    phone = models.CharField(max_length=32, db_index=True)
    sender_name = models.CharField(max_length=150, blank=True)
    direction = models.CharField(max_length=10, choices=Direction.choices)
    message_id = models.CharField(max_length=255, blank=True)
    message_type = models.CharField(max_length=32, default='text')
    body = models.TextField(blank=True)
    media_id = models.CharField(max_length=255, blank=True)
    media_mime_type = models.CharField(max_length=120, blank=True)
    delivery_status = models.CharField(max_length=32, blank=True)
    status_detail = models.TextField(blank=True)
    sent_at = models.DateTimeField(db_index=True)
    status_updated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-sent_at', '-pk']
        constraints = [
            models.UniqueConstraint(
                fields=['tenant', 'message_id'],
                condition=~models.Q(message_id=''),
                name='unique_whatsapp_message_id_per_tenant',
            ),
        ]
        indexes = [
            models.Index(
                fields=['tenant', 'phone', '-sent_at'],
                name='wa_msg_tenant_phone_time_idx',
            ),
        ]

    def __str__(self):
        return f'{self.get_direction_display()} WhatsApp message to/from {self.phone}'
