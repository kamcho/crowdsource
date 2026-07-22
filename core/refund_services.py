from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from core.fulfillment import Fulfillment
from core.order import Order
from core.payment import Payment
from core.refund import Refund


def get_order_refunded_amount(order):
    total = order.refunds.filter(status=Refund.Status.COMPLETED).aggregate(
        total=Sum('amount'),
    )['total']
    return total or Decimal('0.00')


def get_order_refundable_amount(order):
    try:
        payment = order.payment
    except Payment.DoesNotExist:
        return Decimal('0.00')

    if payment.status != Payment.Status.COMPLETED:
        return Decimal('0.00')

    refunded = get_order_refunded_amount(order)
    return max(payment.amount - refunded, Decimal('0.00'))


def create_refund(*, order, amount, reason, created_by, refund_type=Refund.RefundType.PARTIAL, notes=''):
    if order.status not in (Order.Status.PAID, Order.Status.REFUNDED):
        raise ValidationError('Only paid orders can be refunded.')

    try:
        payment = order.payment
    except Payment.DoesNotExist:
        raise ValidationError('This order has no completed payment to refund.')

    if payment.status != Payment.Status.COMPLETED:
        raise ValidationError('Payment must be completed before issuing a refund.')

    amount = Decimal(amount)
    if amount <= 0:
        raise ValidationError('Refund amount must be greater than zero.')

    refundable = get_order_refundable_amount(order)
    if amount > refundable:
        raise ValidationError(f'Refund amount cannot exceed ${refundable} remaining.')

    if refund_type == Refund.RefundType.FULL and amount != refundable:
        raise ValidationError('Full refunds must match the remaining refundable balance.')

    if refund_type == Refund.RefundType.PARTIAL and amount >= refundable and refundable > 0:
        raise ValidationError('Use a full refund for the remaining balance.')

    refund = Refund.objects.create(
        payment=payment,
        order=order,
        amount=amount,
        refund_type=refund_type,
        reason=reason.strip(),
        notes=notes.strip(),
        created_by=created_by,
        status=Refund.Status.PENDING,
    )
    from core.notification_services import notify_refund_created
    notify_refund_created(refund)
    return refund


def complete_refund(refund):
    """
    Mark a refund completed after ops confirms the buyer was repaid.

    PRODUCTION TODO: Call M-Pesa Daraja Reversal API here when provider != 'demo'
    and only mark completed after the gateway confirms success.
    """
    if refund.status != Refund.Status.PENDING:
        raise ValidationError('Only pending refunds can be completed.')

    order = refund.order
    refundable = get_order_refundable_amount(order)
    if refund.amount > refundable:
        raise ValidationError('Refund amount exceeds the remaining refundable balance.')

    with transaction.atomic():
        refund.status = Refund.Status.COMPLETED
        refund.completed_at = timezone.now()
        refund.save(update_fields=['status', 'completed_at', 'updated_at'])

        remaining = get_order_refundable_amount(order)
        if remaining <= Decimal('0.00'):
            order.status = Order.Status.REFUNDED
            order.save(update_fields=['status', 'updated_at'])
            try:
                fulfillment = order.fulfillment
                if fulfillment.status != Fulfillment.Status.DELIVERED:
                    fulfillment.status = Fulfillment.Status.FAILED
                    fulfillment.notes = (
                        f'{fulfillment.notes}\nCancelled due to full refund.'
                        if fulfillment.notes
                        else 'Cancelled due to full refund.'
                    ).strip()
                    fulfillment.save(update_fields=['status', 'notes', 'updated_at'])
            except Fulfillment.DoesNotExist:
                pass

    from core.notification_services import notify_refund_completed
    notify_refund_completed(refund)

    return refund


def cancel_refund(refund):
    if refund.status != Refund.Status.PENDING:
        raise ValidationError('Only pending refunds can be cancelled.')
    refund.status = Refund.Status.CANCELLED
    refund.save(update_fields=['status', 'updated_at'])
    return refund
