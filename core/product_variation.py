from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models


class ProductOption(models.Model):
    product = models.ForeignKey(
        'Product',
        on_delete=models.CASCADE,
        related_name='options',
    )
    name = models.CharField(max_length=100)
    sort_order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['sort_order', 'name']
        constraints = [
            models.UniqueConstraint(
                fields=['product', 'name'],
                name='unique_product_option_name',
            ),
        ]

    def __str__(self):
        return f'{self.product.name} — {self.name}'


class ProductOptionValue(models.Model):
    option = models.ForeignKey(
        ProductOption,
        on_delete=models.CASCADE,
        related_name='values',
    )
    value = models.CharField(max_length=100)
    sort_order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['sort_order', 'value']
        constraints = [
            models.UniqueConstraint(
                fields=['option', 'value'],
                name='unique_product_option_value',
            ),
        ]

    def __str__(self):
        return f'{self.option.name}: {self.value}'

    @property
    def product(self):
        return self.option.product


class ProductVariation(models.Model):
    product = models.ForeignKey(
        'Product',
        on_delete=models.CASCADE,
        related_name='variations',
    )
    option_values = models.ManyToManyField(
        ProductOptionValue,
        related_name='variations',
    )
    sku = models.CharField(max_length=80, unique=True)
    price = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['sku']

    def __str__(self):
        return self.display_name

    @property
    def display_name(self):
        values = self.option_values.select_related('option').order_by(
            'option__sort_order',
            'option__name',
        )
        if not values.exists():
            return self.sku
        return ' / '.join(f'{item.option.name}: {item.value}' for item in values)

    def clean_option_values(self):
        if not self.product_id:
            return

        values = list(self.option_values.select_related('option'))
        if not values:
            raise ValidationError('Select at least one option value.')

        options_seen = set()
        for option_value in values:
            if option_value.option.product_id != self.product_id:
                raise ValidationError('All option values must belong to this product.')
            if option_value.option_id in options_seen:
                raise ValidationError('Only one value per option is allowed.')
            options_seen.add(option_value.option_id)

        product_option_ids = set(
            self.product.options.values_list('id', flat=True)
        )
        if product_option_ids and options_seen != product_option_ids:
            missing = product_option_ids - options_seen
            missing_names = ProductOption.objects.filter(
                id__in=missing
            ).values_list('name', flat=True)
            raise ValidationError(
                f'Missing a value for: {", ".join(missing_names)}.'
            )

    def validate_unique_combination(self):
        current_ids = set(self.option_values.values_list('id', flat=True))
        for variation in self.product.variations.prefetch_related('option_values'):
            if self.pk and variation.pk == self.pk:
                continue
            other_ids = set(variation.option_values.values_list('id', flat=True))
            if other_ids == current_ids:
                raise ValidationError('A variation with this option combination already exists.')

    def validate(self):
        self.clean_option_values()
        self.validate_unique_combination()

    @property
    def primary_file(self):
        primary = self.files.filter(is_primary=True).first()
        if primary:
            return primary
        return self.files.first()

    @property
    def primary_image(self):
        from core.product_file import ProductFile

        primary = self.primary_file
        if primary and primary.is_image:
            return primary
        return self.files.filter(media_type=ProductFile.MediaType.IMAGE).first()

    @property
    def product_level_attributes(self):
        return self.product.attributes.filter(variation__isnull=True)

    @property
    def variation_attributes(self):
        return self.attributes.all()
