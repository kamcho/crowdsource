from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from core.cart import Cart, CartItem
from core.fulfillment_services import create_fulfillment_for_order, get_user_address
from core.group_buy import GroupBuy, GroupBuyEntry
from core.order import Order, OrderItem
from core.payment import Payment


def get_or_create_cart(user):
    cart, _ = Cart.objects.get_or_create(user=user)
    return cart


def add_to_cart(user, group_buy, variation, quantity):
    cart = get_or_create_cart(user)
    item, created = CartItem.objects.get_or_create(
        cart=cart,
        group_buy=group_buy,
        variation=variation,
        defaults={'quantity': quantity},
    )
    if not created:
        item.quantity = quantity
        item.save()
    return item


def checkout_cart(user):
    cart = get_or_create_cart(user)
    items = list(
        cart.items.select_related('group_buy__product', 'variation')
    )
    if not items:
        return [], ['Your cart is empty.']

    errors = []
    saved_entries = []

    with transaction.atomic():
        for item in items:
            try:
                item.full_clean()
            except ValidationError as exc:
                errors.append(f'{item.product.name}: {"; ".join(exc.messages)}')
                continue

            entry, created = GroupBuyEntry.objects.get_or_create(
                group_buy=item.group_buy,
                user=user,
                variation=item.variation,
                defaults={'quantity': item.quantity},
            )
            if not created:
                entry.quantity = item.quantity
                entry.save()
            saved_entries.append(entry)

        if errors:
            transaction.set_rollback(True)
            return [], errors

        cart.items.all().delete()

    return saved_entries, []


def get_user_pledge_entries(user, group_buy):
    return list(
        group_buy.entries.filter(user=user).select_related('variation')
    )


def clear_user_pledges_for_group_buy(user, group_buy):
    """Remove pledges after they are converted to a paid order so the buyer can pledge again."""
    deleted_count, _ = GroupBuyEntry.objects.filter(
        user=user,
        group_buy=group_buy,
    ).delete()
    if deleted_count:
        group_buy.refresh_status()
    return deleted_count


def pledge_checkout_total(entries, group_buy):
    from core.pricing import pledge_checkout_total as _pledge_checkout_total
    return _pledge_checkout_total(entries, group_buy)


def user_has_paid_order(user, group_buy):
    return Order.objects.filter(
        group_buy=group_buy,
        user=user,
        status=Order.Status.PAID,
    ).exists()


def get_user_latest_paid_order(user, group_buy):
    return (
        Order.objects.filter(
            group_buy=group_buy,
            user=user,
            status=Order.Status.PAID,
        )
        .order_by('-created_at')
        .first()
    )


def user_has_pending_mpesa_checkout(user, group_buy):
    return Payment.objects.filter(
        user=user,
        group_buy=group_buy,
        status=Payment.Status.PENDING,
        provider='mpesa',
    ).exists()


def can_confirm_pledge_order(user, group_buy):
    if group_buy.status == GroupBuy.Status.CANCELLED:
        return False
    entries = get_user_pledge_entries(user, group_buy)
    if not entries:
        return False
    if user_has_pending_mpesa_checkout(user, group_buy):
        return False
    return True


def get_user_order_for_group_buy(user, group_buy):
    return Order.objects.filter(group_buy=group_buy, user=user).order_by('-created_at').first()


def get_or_create_pending_checkout_order(user, group_buy, address=None):
    order = (
        Order.objects.filter(
            group_buy=group_buy,
            user=user,
            status=Order.Status.PENDING_PAYMENT,
        )
        .order_by('-created_at')
        .first()
    )
    if not order:
        order = Order.objects.create(
            group_buy=group_buy,
            user=user,
            status=Order.Status.PENDING_PAYMENT,
            total_amount=Decimal('0.00'),
        )
    if address:
        order.apply_delivery_address(address)
        order.save()
    return order


def complete_payment_and_create_order(user, group_buy, address):
    if not can_confirm_pledge_order(user, group_buy):
        if user_has_pending_mpesa_checkout(user, group_buy):
            raise ValidationError('Complete your pending M-Pesa payment first.')
        if group_buy.status == GroupBuy.Status.CANCELLED:
            raise ValidationError('This group buy was cancelled.')
        raise ValidationError('No pledges found for this group buy.')

    if not address or address.user_id != user.id:
        raise ValidationError('Select a valid delivery address.')

    entries = get_user_pledge_entries(user, group_buy)
    amount = pledge_checkout_total(entries, group_buy)

    with transaction.atomic():
        payment = Payment.objects.create(
            group_buy=group_buy,
            user=user,
            amount=amount,
            status=Payment.Status.PENDING,
            provider='demo',
        )

        order = get_or_create_pending_checkout_order(user, group_buy, address)
        order.items.all().delete()
        total = Decimal('0.00')
        for entry in entries:
            from core.pricing import resolve_unit_price
            order_item = OrderItem.objects.create(
                order=order,
                variation=entry.variation,
                quantity=entry.quantity,
                unit_price=resolve_unit_price(group_buy, entry.variation),
            )
            total += order_item.line_total

        order.total_amount = total
        order.status = Order.Status.PAID
        order.save()

        payment.mark_completed(order)
        create_fulfillment_for_order(order)
        clear_user_pledges_for_group_buy(user, group_buy)

    from core.notification_services import notify_payment_completed
    notify_payment_completed(order, payment)

    return order, payment
