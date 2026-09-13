from decimal import Decimal

from django.db import models


class ImportCostType(models.TextChoices):
    CHINA_WAREHOUSE = 'china_warehouse', 'China → warehouse'
    INTERNATIONAL_FREIGHT = 'international_freight', 'Freight to Kenya'
    CUSTOMS = 'customs', 'Customs & clearance'
    INLAND = 'inland', 'Inland transport (e.g. Nakuru)'
    OTHER = 'other', 'Other'


class ImportShipment(models.Model):
    """Physical run (container / air) grouping many product import batches — costing is per product."""

    name = models.CharField(max_length=120)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.name

    @property
    def total_units(self):
        total = 0
        for batch in self.import_batches.select_related('group_buy'):
            total += batch.effective_units
        return total


class ImportBatchAdditionalCost(models.Model):
    """Extra charges for this product only (warehouse, freight, customs, Nakuru, etc.)."""

    import_batch = models.ForeignKey(
        'ImportBatch',
        on_delete=models.CASCADE,
        related_name='additional_costs',
    )
    cost_type = models.CharField(max_length=32, choices=ImportCostType.choices)
    description = models.CharField(max_length=255, blank=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f'{self.get_cost_type_display()} ${self.amount}'


class ImportShipmentSharedCost(models.Model):
    shipment = models.ForeignKey(
        ImportShipment,
        on_delete=models.CASCADE,
        related_name='shared_costs',
    )
    cost_type = models.CharField(max_length=32, choices=ImportCostType.choices)
    description = models.CharField(max_length=255, blank=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f'{self.get_cost_type_display()} ${self.amount}'
