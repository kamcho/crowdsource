from decimal import Decimal

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db.models import Count, DecimalField, OuterRef, Q, Subquery, Sum
from django.db.models.functions import Coalesce
from django.shortcuts import get_object_or_404, redirect, render

from users.models import User

from .address import Address
from .complaint import Complaint
from .decorators import staff_required
from .forms import FulfillmentForm, RefundCreateForm
from .fulfillment_services import create_fulfillment_for_order
from .group_buy import GroupBuyEntry
from .order import Order
from .payment import Payment
from .refund import MPESA_REVERSAL_REQUIRED_IN_PRODUCTION, Refund
from .refund_services import cancel_refund, complete_refund, create_refund
from .wishlist import WishlistItem


def orders_queryset():
    return Order.objects.select_related(
        'user',
        'group_buy__product',
        'payment',
        'fulfillment',
    ).annotate(
        unit_count=Coalesce(Sum('items__quantity'), 0),
    )


def _order_search(query):
    combined = Q()
    for token in query.split():
        lookup = token[1:] if token.startswith('#') else token
        token_filter = (
            Q(user__first_name__icontains=token)
            | Q(user__last_name__icontains=token)
            | Q(user__email__icontains=token)
            | Q(user__phone__icontains=token)
            | Q(delivery_recipient_name__icontains=token)
            | Q(group_buy__product__name__icontains=token)
        )
        if lookup.isdigit():
            token_filter |= Q(pk=int(lookup))
        combined &= token_filter
    return combined


def customers_queryset(*, customers_only=True):
    paid_total = (
        Order.objects.filter(
            user_id=OuterRef('pk'),
            status=Order.Status.PAID,
        )
        .order_by()
        .values('user_id')
        .annotate(total=Sum('total_amount'))
        .values('total')
    )
    users = User.objects.all()
    if customers_only:
        users = users.filter(role=User.Role.CUSTOMER)
    return users.annotate(
        order_count=Count('orders', distinct=True),
        paid_order_count=Count(
            'orders',
            filter=Q(orders__status=Order.Status.PAID),
            distinct=True,
        ),
        refund_count=Count('orders__refunds', distinct=True),
        complaint_count=Count('complaints', distinct=True),
        open_complaint_count=Count(
            'complaints',
            filter=Q(complaints__status__in=[
                Complaint.Status.OPEN,
                Complaint.Status.IN_PROGRESS,
            ]),
            distinct=True,
        ),
        paid_total=Coalesce(
            Subquery(paid_total, output_field=DecimalField(max_digits=12, decimal_places=2)),
            Decimal('0.00'),
        ),
    )


def _customer_search(query):
    combined = Q()
    for token in query.split():
        combined &= (
            Q(first_name__icontains=token)
            | Q(last_name__icontains=token)
            | Q(email__icontains=token)
            | Q(phone__icontains=token)
        )
    return combined


@staff_required
def admin_order_list(request):
    status_filter = request.GET.get('status', 'all')
    query = request.GET.get('q', '').strip()
    orders = orders_queryset()
    if status_filter and status_filter != 'all':
        orders = orders.filter(status=status_filter)
    if query:
        orders = orders.filter(_order_search(query))

    summary = {
        'all': Order.objects.count(),
        'pending_payment': Order.objects.filter(status=Order.Status.PENDING_PAYMENT).count(),
        'paid': Order.objects.filter(status=Order.Status.PAID).count(),
        'refunded': Order.objects.filter(status=Order.Status.REFUNDED).count(),
        'cancelled': Order.objects.filter(status=Order.Status.CANCELLED).count(),
    }
    return render(request, 'core/orders/admin_list.html', {
        'orders': orders,
        'status_filter': status_filter,
        'query': query,
        'summary': summary,
    })


def _load_order(order_id):
    order = get_object_or_404(
        orders_queryset().prefetch_related(
            'items__variation',
            'refunds',
            'complaints',
        ),
        pk=order_id,
    )
    fulfillment = None
    if order.status == Order.Status.PAID:
        fulfillment = create_fulfillment_for_order(order)
    elif hasattr(order, 'fulfillment'):
        fulfillment = order.fulfillment
    return order, fulfillment


@staff_required
def admin_order_manage(request, order_id):
    order, fulfillment = _load_order(order_id)
    refundable = order.refundable_amount
    fulfillment_form = FulfillmentForm(instance=fulfillment) if fulfillment else None
    refund_form = RefundCreateForm(refundable_amount=refundable) if refundable > 0 else None

    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'update_fulfillment' and fulfillment:
            fulfillment_form = FulfillmentForm(request.POST, instance=fulfillment)
            if fulfillment_form.is_valid():
                fulfillment_form.save()
                messages.success(request, f'Delivery updated for order #{order.pk}.')
                return redirect('core:admin_order_manage', order_id=order.pk)
            messages.error(request, 'Please correct the delivery errors below.')
        elif action == 'create_refund':
            refund_form = RefundCreateForm(request.POST, refundable_amount=refundable)
            if refund_form.is_valid():
                try:
                    create_refund(
                        order=order,
                        amount=refund_form.cleaned_data['amount'],
                        reason=refund_form.cleaned_data['reason'],
                        notes=refund_form.cleaned_data.get('notes', ''),
                        refund_type=refund_form.cleaned_data['refund_type'],
                        created_by=request.user,
                    )
                    messages.success(
                        request,
                        f'Refund recorded for order #{order.pk}. Mark it complete after the buyer is repaid.',
                    )
                    return redirect('core:admin_order_manage', order_id=order.pk)
                except ValidationError as exc:
                    messages.error(request, '; '.join(getattr(exc, 'messages', [str(exc)])))
            else:
                messages.error(request, 'Please correct the refund errors below.')
        elif action in ('complete_refund', 'cancel_refund'):
            refund = get_object_or_404(Refund, pk=request.POST.get('refund_id'), order=order)
            try:
                if action == 'complete_refund':
                    complete_refund(refund)
                    if MPESA_REVERSAL_REQUIRED_IN_PRODUCTION:
                        messages.warning(
                            request,
                            f'Refund {refund.reference} marked complete. '
                            'PRODUCTION REMINDER: trigger M-Pesa Daraja reversal for this payment.',
                        )
                    else:
                        messages.success(request, f'Refund {refund.reference} marked complete.')
                else:
                    cancel_refund(refund)
                    messages.success(request, f'Refund {refund.reference} cancelled.')
            except ValidationError as exc:
                messages.error(request, '; '.join(getattr(exc, 'messages', [str(exc)])))
            return redirect('core:admin_order_manage', order_id=order.pk)

    return render(request, 'core/orders/admin_manage.html', {
        'order': order,
        'fulfillment': fulfillment,
        'fulfillment_form': fulfillment_form,
        'refund_form': refund_form,
        'refundable': refundable,
        'mpesa_reversal_required': MPESA_REVERSAL_REQUIRED_IN_PRODUCTION,
    })


@staff_required
def customer_list(request):
    view = request.GET.get('view', 'all')
    query = request.GET.get('q', '').strip()
    customers = customers_queryset()
    summary = {
        'all': customers.count(),
        'with_orders': customers.filter(order_count__gt=0).count(),
        'inactive': customers.filter(is_active=False).count(),
        'complaints': customers.filter(open_complaint_count__gt=0).count(),
    }
    if view == 'with_orders':
        customers = customers.filter(order_count__gt=0)
    elif view == 'inactive':
        customers = customers.filter(is_active=False)
    elif view == 'complaints':
        customers = customers.filter(open_complaint_count__gt=0)
    if query:
        customers = customers.filter(_customer_search(query))
    customers = customers.order_by('-date_joined')

    return render(request, 'core/customers/list.html', {
        'customers': customers,
        'view': view,
        'query': query,
        'summary': summary,
    })


@staff_required
def customer_manage(request, user_id):
    customer = get_object_or_404(customers_queryset(customers_only=False), pk=user_id)
    if request.method == 'POST' and request.POST.get('action') == 'set_active':
        if customer.role != User.Role.CUSTOMER:
            messages.error(request, 'Only customer accounts can be activated from this page.')
        else:
            customer.is_active = request.POST.get('is_active') == '1'
            customer.save(update_fields=['is_active', 'updated_at'])
            state = 'activated' if customer.is_active else 'deactivated'
            messages.success(request, f'{customer.get_full_name()} {state}.')
        return redirect('core:customer_manage', user_id=customer.pk)

    orders = orders_queryset().filter(user=customer)
    refunds = Refund.objects.filter(order__user=customer).select_related(
        'order__group_buy__product',
        'payment',
    )
    complaints = customer.complaints.select_related('order__group_buy__product')
    bookings = GroupBuyEntry.objects.filter(user=customer).select_related(
        'group_buy__product',
        'variation',
    )
    payments = Payment.objects.filter(user=customer).select_related(
        'group_buy__product',
        'order',
    )
    addresses = Address.objects.filter(user=customer)
    wishlist = WishlistItem.objects.filter(user=customer).select_related('product')

    return render(request, 'core/customers/manage.html', {
        'customer': customer,
        'orders': orders,
        'refunds': refunds,
        'complaints': complaints,
        'bookings': bookings,
        'payments': payments,
        'addresses': addresses,
        'wishlist': wishlist,
    })
