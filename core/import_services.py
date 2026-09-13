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


def link_group_buy_to_shipment(group_buy, shipment):
    batch = ImportBatch.objects.filter(group_buy=group_buy).first()
    if not batch:
        batch = create_import_batch(group_buy)
    if batch.shipment_id and batch.shipment_id != shipment.pk:
        raise ValidationError(
            f'"{group_buy.product.name}" is already on shipment "{batch.shipment.name}". '
            'Remove it there first or unlink from the group buy page.',
        )
    batch.shipment = shipment
    batch.save(update_fields=['shipment', 'updated_at'])
    return batch


def unlink_import_batch_from_shipment(batch):
    batch.shipment = None
    batch.save(update_fields=['shipment', 'updated_at'])
    return batch


def group_buys_available_for_shipment(shipment):
    """Group buys not yet on this shipment and not on another shipment."""
    from core.group_buy import GroupBuy

    linked_here = set(shipment.import_batches.values_list('group_buy_id', flat=True))
    candidates = (
        GroupBuy.objects.select_related('product')
        .exclude(pk__in=linked_here)
        .order_by('-created_at')
    )
    available = []
    for group_buy in candidates:
        try:
            batch = group_buy.import_batch
        except ImportBatch.DoesNotExist:
            batch = None
        if batch and batch.shipment_id and batch.shipment_id != shipment.pk:
            continue
        available.append(group_buy)
    return available
