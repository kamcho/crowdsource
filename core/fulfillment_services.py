from django.core.exceptions import ValidationError

from core.address import Address
from core.fulfillment import Fulfillment
from core.import_batch import ImportBatch
from core.order import Order


def get_user_addresses(user):
    return Address.objects.filter(user=user).order_by('-is_default', '-updated_at')


def get_user_default_address(user):
    return Address.objects.filter(user=user, is_default=True).first()


def get_user_address(user, address_id):
    return Address.objects.filter(user=user, pk=address_id).first()


def create_fulfillment_for_order(order):
    fulfillment, created = Fulfillment.objects.get_or_create(
        order=order,
        defaults={'status': Fulfillment.Status.PENDING},
    )
    import_batch = ImportBatch.objects.filter(group_buy=order.group_buy).first()
    if import_batch and not fulfillment.import_batch_id:
        fulfillment.import_batch = import_batch
        fulfillment.save(update_fields=['import_batch', 'updated_at'])
    return fulfillment


def link_fulfillments_to_import_batch(import_batch):
    Fulfillment.objects.filter(
        order__group_buy=import_batch.group_buy,
        order__status=Order.Status.PAID,
    ).update(import_batch=import_batch)


def update_fulfillment(fulfillment, *, status=None, tracking_reference=None, notes=None):
    old_status = fulfillment.status
    if status is not None:
        valid = {choice[0] for choice in Fulfillment.Status.choices}
        if status not in valid:
            raise ValidationError('Invalid fulfillment status.')
        fulfillment.status = status
    if tracking_reference is not None:
        fulfillment.tracking_reference = tracking_reference
    if notes is not None:
        fulfillment.notes = notes
    fulfillment.save()
    if fulfillment.status != old_status:
        from core.notification_services import notify_fulfillment_status_changed
        notify_fulfillment_status_changed(fulfillment, old_status, fulfillment.status)
    return fulfillment
