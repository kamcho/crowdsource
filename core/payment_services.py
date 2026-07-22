from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction

from core.fulfillment_services import create_fulfillment_for_order
from core.group_buy import GroupBuyEntry
from core.mpesa import (
    MpesaAPIError,
    MpesaConfigError,
    initiate_stk_push,
    normalize_mpesa_phone,
    parse_stk_callback,
    query_stk_status,
)
from core.order import Order, OrderItem
from core.payment import Payment


def usd_to_kes(amount_usd):
    from core.currency import convert_usd_to_kes
    return convert_usd_to_kes(amount_usd)


def is_mpesa_enabled():
    return getattr(settings, 'PAYMENT_PROVIDER', 'demo') == 'mpesa'


def _validate_checkout(user, group_buy, address):
    from core.commerce_services import (
        can_confirm_pledge_order,
        get_user_pledge_entries,
        user_has_pending_mpesa_checkout,
    )

    if not can_confirm_pledge_order(user, group_buy):
        if user_has_pending_mpesa_checkout(user, group_buy):
            raise ValidationError('Complete your pending M-Pesa payment first.')
        if group_buy.status == GroupBuy.Status.CANCELLED:
            raise ValidationError('This group buy was cancelled.')
        raise ValidationError('No pledges found for this group buy.')

    if not address or address.user_id != user.id:
        raise ValidationError('Select a valid delivery address.')

    entries = get_user_pledge_entries(user, group_buy)
    if not entries:
        raise ValidationError('No pledges found for this group buy.')
    return entries


def _build_order_lines(order, entries, group_buy):
    from core.pricing import resolve_unit_price
    order.items.all().delete()
    total = Decimal('0.00')
    for entry in entries:
        order_item = OrderItem.objects.create(
            order=order,
            variation=entry.variation,
            quantity=entry.quantity,
            unit_price=resolve_unit_price(group_buy, entry.variation),
        )
        total += order_item.line_total
    order.total_amount = total
    order.save(update_fields=['total_amount', 'updated_at'])
    return total


def _release_terminal_payments_for_order(order):
    """Free the one-to-one order slot so a new checkout payment can be created."""
    Payment.objects.filter(order=order).exclude(
        status=Payment.Status.PENDING,
    ).update(order=None)


def _get_or_create_checkout_payment(user, group_buy, order, total, amount_kes):
    pending_payment = Payment.objects.filter(
        user=user,
        group_buy=group_buy,
        status=Payment.Status.PENDING,
    ).first()
    if pending_payment:
        pending_payment.amount = total
        pending_payment.amount_kes = amount_kes
        pending_payment.order = order
        pending_payment.provider = 'mpesa'
        pending_payment.save(update_fields=[
            'amount', 'amount_kes', 'order', 'provider',
        ])
        return pending_payment

    _release_terminal_payments_for_order(order)
    return Payment.objects.create(
        group_buy=group_buy,
        user=user,
        order=order,
        amount=total,
        amount_kes=amount_kes,
        status=Payment.Status.PENDING,
        provider='mpesa',
    )


def prepare_checkout_order(user, group_buy, address):
    """Create or refresh a pending order + payment ready for M-Pesa STK push."""
    entries = _validate_checkout(user, group_buy, address)
    from core.pricing import pledge_checkout_total
    amount_usd = pledge_checkout_total(entries, group_buy)
    amount_kes = usd_to_kes(amount_usd)

    with transaction.atomic():
        from core.commerce_services import get_or_create_pending_checkout_order

        order = get_or_create_pending_checkout_order(user, group_buy, address)
        order.status = Order.Status.PENDING_PAYMENT
        order.save(update_fields=['status', 'updated_at'])
        total = _build_order_lines(order, entries, group_buy)
        payment = _get_or_create_checkout_payment(
            user, group_buy, order, total, amount_kes,
        )

    return order, payment


def initiate_mpesa_stk_push(payment, phone):
    if payment.status != Payment.Status.PENDING:
        raise ValidationError('This payment is no longer pending.')

    normalized_phone = normalize_mpesa_phone(phone)
    amount_kes = payment.amount_kes or usd_to_kes(payment.amount)

    data = initiate_stk_push(
        phone_number=normalized_phone,
        amount=amount_kes,
        account_reference=payment.reference,
        description='CrowdSource',
    )

    payment.phone_number = normalized_phone
    payment.amount_kes = amount_kes
    payment.merchant_request_id = data.get('MerchantRequestID', '')
    payment.checkout_request_id = data.get('CheckoutRequestID', '')
    payment.result_description = data.get('CustomerMessage', '')[:255]
    payment.provider = 'mpesa'
    payment.save(update_fields=[
        'phone_number', 'amount_kes', 'merchant_request_id',
        'checkout_request_id', 'result_description', 'provider',
    ])
    return payment


def get_pending_mpesa_payment(user, group_buy):
    return Payment.objects.filter(
        user=user,
        group_buy=group_buy,
        status=Payment.Status.PENDING,
        provider='mpesa',
    ).first()


def default_mpesa_phone_for_user(user):
    if not user.phone:
        return ''
    phone_str = str(user.phone)
    if phone_str.startswith('+254'):
        return '0' + phone_str[4:]
    if phone_str.startswith('254') and len(phone_str) >= 12:
        return '0' + phone_str[3:]
    return phone_str


def ensure_mpesa_stk_push(payment, phone, *, retry=False):
    """Send STK push only when this pending payment has not received one yet."""
    if payment.status != Payment.Status.PENDING:
        raise ValidationError('This payment is no longer pending.')
    if payment.stk_push_initiated and not retry:
        return payment
    if not phone:
        raise ValidationError('Enter your M-Pesa phone number.')
    return initiate_mpesa_stk_push(payment, phone)


def retry_mpesa_stk_push(payment, phone):
    """Send a fresh STK push after a previous prompt expired or was ignored."""
    if payment.status != Payment.Status.PENDING:
        raise ValidationError('This payment is no longer pending.')
    if not phone:
        raise ValidationError('Enter your M-Pesa phone number.')
    payment.merchant_request_id = ''
    payment.checkout_request_id = ''
    payment.result_code = None
    payment.result_description = ''
    payment.save(update_fields=[
        'merchant_request_id', 'checkout_request_id',
        'result_code', 'result_description',
    ])
    return initiate_mpesa_stk_push(payment, phone)


@transaction.atomic
def finalize_paid_order(payment, *, mpesa_receipt=''):
    if payment.status == Payment.Status.COMPLETED:
        return payment.order

    order = payment.order
    if not order:
        raise ValidationError('Payment is not linked to an order.')

    if mpesa_receipt:
        payment.mpesa_receipt_number = mpesa_receipt

    order.status = Order.Status.PAID
    order.save(update_fields=['status', 'updated_at'])
    payment.mark_completed(order)
    create_fulfillment_for_order(order)

    from core.commerce_services import clear_user_pledges_for_group_buy
    clear_user_pledges_for_group_buy(order.user, order.group_buy)

    from core.notification_services import notify_payment_completed
    notify_payment_completed(order, payment)
    return order


def fail_payment(payment, *, result_code=None, result_description=''):
    if payment.status != Payment.Status.PENDING:
        return payment
    payment.status = Payment.Status.FAILED
    if result_code is not None:
        payment.result_code = result_code
    if result_description:
        payment.result_description = result_description[:255]
    payment.order = None
    payment.save(update_fields=['status', 'result_code', 'result_description', 'order'])
    return payment


def cancel_payment(payment, *, result_code=None, result_description=''):
    if payment.status != Payment.Status.PENDING:
        return payment
    payment.status = Payment.Status.CANCELLED
    if result_code is not None:
        payment.result_code = result_code
    if result_description:
        payment.result_description = result_description[:255]
    payment.order = None
    payment.save(update_fields=['status', 'result_code', 'result_description', 'order'])
    return payment


def process_stk_callback_payload(payload):
    parsed = parse_stk_callback(payload)
    checkout_id = parsed.get('checkout_request_id', '')
    merchant_id = parsed.get('merchant_request_id', '')

    payment = Payment.objects.select_related('order').filter(
        checkout_request_id=checkout_id,
    ).first()
    if not payment and merchant_id:
        payment = Payment.objects.select_related('order').filter(
            merchant_request_id=merchant_id,
        ).first()

    if not payment:
        return None

    payment.callback_payload = payload
    payment.result_code = parsed.get('result_code')
    payment.result_description = (parsed.get('result_description') or '')[:255]
    if parsed.get('mpesa_receipt_number'):
        payment.mpesa_receipt_number = parsed['mpesa_receipt_number']
    if parsed.get('phone_number'):
        payment.phone_number = str(parsed['phone_number'])
    payment.save(update_fields=[
        'callback_payload', 'result_code', 'result_description',
        'mpesa_receipt_number', 'phone_number',
    ])

    result_code = parsed.get('result_code')
    if result_code == 0:
        finalize_paid_order(payment, mpesa_receipt=parsed.get('mpesa_receipt_number', ''))
    elif result_code == 1032:
        cancel_payment(
            payment,
            result_code=1032,
            result_description=parsed.get('result_description', 'Payment cancelled.'),
        )
    else:
        fail_payment(
            payment,
            result_code=result_code,
            result_description=parsed.get('result_description', 'Payment failed.'),
        )
    return payment


def poll_mpesa_payment_status(payment):
    """Poll Daraja STK query API when callback has not arrived yet."""
    if payment.status != Payment.Status.PENDING or not payment.checkout_request_id:
        return payment

    try:
        query_data = query_stk_status(payment.checkout_request_id)
    except (MpesaConfigError, MpesaAPIError):
        return payment

    result_code = query_data.get('ResultCode')
    if result_code == 0:
        receipt = ''
        metadata = query_data.get('CallbackMetadata', {}).get('Item', [])
        for item in metadata:
            if item.get('Name') == 'MpesaReceiptNumber':
                receipt = str(item.get('Value', ''))
        finalize_paid_order(payment, mpesa_receipt=receipt)
    elif str(result_code) == '1032':
        cancel_payment(
            payment,
            result_code=1032,
            result_description=query_data.get('ResultDesc', 'Payment cancelled.'),
        )
    elif result_code not in (None,) and str(result_code) != '4999':
        fail_payment(
            payment,
            result_code=int(result_code) if str(result_code).isdigit() else None,
            result_description=query_data.get('ResultDesc', 'Payment failed.'),
        )

    payment.refresh_from_db()
    return payment
