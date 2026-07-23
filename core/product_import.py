from django.conf import settings
from django.db import models


class ProductImportDraft(models.Model):
    class Step(models.TextChoices):
        SUPPLIER = 'supplier', 'Supplier'
        CATEGORIES = 'categories', 'Categories'
        BASICS = 'basics', 'Product details'
        ATTRIBUTES = 'attributes', 'Specifications'
        VARIATIONS = 'variations', 'Variations & pricing'
        PRODUCT_MEDIA = 'product_media', 'Product images'
        VARIATION_MEDIA = 'variation_media', 'Variation images'
        REVIEW = 'review', 'Review & publish'

    class Status(models.TextChoices):
        PARSING = 'parsing', 'Parsing'
        IN_PROGRESS = 'in_progress', 'In progress'
        COMPLETED = 'completed', 'Completed'
        FAILED = 'failed', 'Failed'
        DISCARDED = 'discarded', 'Discarded'

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='product_import_drafts',
    )
    source_url = models.URLField(blank=True)
    raw_paste = models.TextField(blank=True)
    draft_data = models.JSONField(default=dict, blank=True)
    current_step = models.CharField(
        max_length=30,
        choices=Step.choices,
        default=Step.BASICS,
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PARSING,
    )
    parse_error = models.TextField(blank=True)
    product = models.ForeignKey(
        'Product',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='import_drafts',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at']

    def __str__(self):
        name = self.draft_data.get('name') or 'Untitled import'
        return f'Import draft: {name}'

    @property
    def display_name(self):
        return self.draft_data.get('name') or 'Untitled product'

    @property
    def step_index(self):
        order = list(self.Step.values)
        try:
            return order.index(self.current_step)
        except ValueError:
            return 0

    @property
    def step_count(self):
        return len(self.Step.choices)

    def step_number(self):
        return self.step_index + 1


class ProductImportMedia(models.Model):
    draft = models.ForeignKey(
        ProductImportDraft,
        on_delete=models.CASCADE,
        related_name='media_files',
    )
    variation_sku = models.CharField(
        max_length=80,
        blank=True,
        help_text='Blank for product-level media.',
    )
    file = models.FileField(upload_to='import_drafts/%Y/%m/')
    is_primary = models.BooleanField(default=False)
    sort_order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['variation_sku', 'sort_order', 'id']

    @property
    def is_variation_media(self):
        return bool(self.variation_sku)
