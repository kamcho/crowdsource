import os

from django.db import models
from django.utils.text import slugify

IMAGE_EXTENSIONS = {'jpg', 'jpeg', 'png', 'gif', 'webp', 'bmp', 'svg'}
VIDEO_EXTENSIONS = {'mp4', 'webm', 'mov', 'avi', 'mkv', 'm4v'}


def detect_media_type(filename):
    extension = os.path.splitext(filename)[1].lstrip('.').lower()
    if extension in VIDEO_EXTENSIONS:
        return ProductFile.MediaType.VIDEO
    return ProductFile.MediaType.IMAGE


def product_file_upload_path(instance, filename):
    product_id = instance.product_id or 'unsorted'
    if instance.variation_id:
        return f'products/{product_id}/variations/{instance.variation_id}/{filename}'
    return f'products/{product_id}/{filename}'


class ProductFile(models.Model):
    class MediaType(models.TextChoices):
        IMAGE = 'image', 'Image'
        VIDEO = 'video', 'Video'

    product = models.ForeignKey(
        'Product',
        on_delete=models.CASCADE,
        related_name='files',
    )
    variation = models.ForeignKey(
        'ProductVariation',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='files',
    )
    file = models.FileField(upload_to=product_file_upload_path)
    media_type = models.CharField(
        max_length=10,
        choices=MediaType.choices,
        blank=True,
    )
    caption = models.CharField(max_length=255, blank=True)
    sort_order = models.PositiveIntegerField(default=0)
    is_primary = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['sort_order', 'created_at']

    def __str__(self):
        if self.variation_id:
            return f'{self.get_media_type_display()} for {self.variation.sku}'
        return f'{self.get_media_type_display()} for {self.product.name}'

    def clean(self):
        from django.core.exceptions import ValidationError

        if self.variation_id and self.product_id and self.variation.product_id != self.product_id:
            raise ValidationError('Variation must belong to the same product.')

    @property
    def is_image(self):
        return self.media_type == self.MediaType.IMAGE

    @property
    def is_video(self):
        return self.media_type == self.MediaType.VIDEO

    def save(self, *args, **kwargs):
        if self.variation_id:
            self.product_id = self.variation.product_id
        if self.file and not self.media_type:
            self.media_type = detect_media_type(self.file.name)
        super().save(*args, **kwargs)
        if self.is_primary:
            primary_scope = ProductFile.objects.filter(product=self.product, is_primary=True)
            if self.variation_id:
                primary_scope = primary_scope.filter(variation=self.variation)
            else:
                primary_scope = primary_scope.filter(variation__isnull=True)
            primary_scope.exclude(pk=self.pk).update(is_primary=False)
