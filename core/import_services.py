from django.core.exceptions import ValidationError

from core.import_batch import ImportBatch

def create_import_batch(group_buy, *, supplier=None, supplier_reference='', estimated_arrival=None, notes=''):
    if ImportBatch.objects.filter(group_buy=group_buy).exists():
        raise ValidationError('This group buy already has an import batch.')

    if supplier is None and group_buy.product.supplier_id:
        supplier = group_buy.product.supplier

    return ImportBatch.objects.create(
        group_buy=group_buy,
        supplier=supplier,
        supplier_reference=supplier_reference,
        estimated_arrival=estimated_arrival,
        notes=notes,
    )


def advance_import_batch(batch, new_status):
    valid = {choice[0] for choice in ImportBatch.Status.choices}
    if new_status not in valid:
        raise ValidationError('Invalid import batch status.')

    batch.status = new_status
    batch.save()
    return batch
