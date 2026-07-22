from django.conf import settings
from django.db import models
from phonenumber_field.modelfields import PhoneNumberField


class Address(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='addresses',
    )
    label = models.CharField(max_length=50, blank=True, default='Home')
    recipient_name = models.CharField(max_length=150)
    phone = PhoneNumberField(region='KE')
    county = models.CharField(max_length=100)
    area = models.CharField(max_length=100, help_text='Town, estate, or area.')
    street_address = models.CharField(max_length=255)
    delivery_notes = models.CharField(max_length=255, blank=True)
    is_default = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-is_default', '-updated_at']
        verbose_name_plural = 'addresses'

    def __str__(self):
        return f'{self.recipient_name} — {self.area}, {self.county}'

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if self.is_default:
            Address.objects.filter(user=self.user).exclude(pk=self.pk).update(is_default=False)

    @property
    def formatted_single_line(self):
        parts = [self.street_address, self.area, self.county]
        return ', '.join(part for part in parts if part)

    def snapshot_fields(self):
        return {
            'delivery_recipient_name': self.recipient_name,
            'delivery_phone': str(self.phone),
            'delivery_county': self.county,
            'delivery_area': self.area,
            'delivery_street': self.street_address,
            'delivery_notes': self.delivery_notes,
        }
