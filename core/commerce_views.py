from decimal import Decimal

from django.core.exceptions import ValidationError
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_GET, require_POST

from core.currency import set_display_currency, normalize_currency, SUPPORTED_CURRENCIES

from core.cart import CartItem
from core.address import Address
from core.commerce_services import (
    add_to_cart,
    checkout_cart,
    get_or_create_cart,
    can_confirm_pledge_order,
    complete_payment_and_create_order,
    get_user_latest_paid_order,
    get_user_order_for_group_buy,
    pledge_checkout_total,
)
from core.payment_services import (
    default_mpesa_phone_for_user,
    ensure_mpesa_stk_push,
    get_pending_mpesa_payment,
    is_mpesa_enabled,
    prepare_checkout_order,
    usd_to_kes,
)
from core.mpesa import MpesaAPIError, MpesaConfigError
from core.fulfillment_services import create_fulfillment_for_order, get_user_addresses, get_user_address, get_user_default_address
from core.group_buy import GroupBuy, GroupBuyEntry
from core.models import Product
from core.order import Order
from core.product_variation import ProductVariation
from core.wishlist_services import get_user_wishlist_items, remove_from_wishlist, toggle_wishlist
from core.forms import AddressForm, ComplaintForm, ComplaintMessageForm
from core.complaint import Complaint
from core.complaint_services import add_complaint_message, create_complaint

@login_required(login_url='users:signin')
def cart_detail(request):
    cart = get_or_create_cart(request.user)
    items = cart.items.select_related(
        'group_buy__product',
        'variation',
    ).prefetch_related('group_buy__product__files')

    if request.method == 'POST':
        if 'checkout' in request.POST:
            saved_entries, errors = checkout_cart(request.user)
            if errors:
                for error in errors:
                    messages.error(request, error)
            else:
                messages.success(
                    request,
                    f'Booking saved for {len(saved_entries)} line(s). Your cart is cleared.',
                )
                return redirect('pledge_list')
            return redirect('cart_detail')

        updated = False
        for key, value in request.POST.items():
            if not key.startswith('quantity_'):
                continue
            try:
                item_id = int(key.replace('quantity_', ''))
                quantity = int(value)
            except (TypeError, ValueError):
                continue
            item = items.filter(pk=item_id).first()
            if not item:
                continue
            if quantity < 1:
                item.delete()
            else:
                item.quantity = quantity
                item.save()
            updated = True
        if updated:
            messages.success(request, 'Cart updated.')
        return redirect('cart_detail')

    return render(request, 'core/cart/detail.html', {
        'cart': cart,
        'items': items,
    })


@login_required(login_url='users:signin')
@require_POST
def cart_add(request):
    group_buy = get_object_or_404(GroupBuy.objects.select_related('product'), pk=request.POST.get('group_buy'))
    quantity = max(int(request.POST.get('quantity') or 1), 1)

    variation = None
    variation_id = request.POST.get('variation')
    if variation_id:
        variation = get_object_or_404(
            ProductVariation,
            pk=variation_id,
            product=group_buy.product,
            is_active=True,
        )

    try:
        add_to_cart(request.user, group_buy, variation, quantity)
    except ValidationError as exc:
        messages.error(request, '; '.join(exc.messages))
        return redirect('product_detail', slug=group_buy.product.slug)

    messages.success(request, 'Added to cart.')
    next_url = request.POST.get('next')
    if next_url == 'cart':
        return redirect('cart_detail')
    return redirect('product_detail', slug=group_buy.product.slug)


@login_required(login_url='users:signin')
@require_POST
def cart_remove(request, item_id):
    item = get_object_or_404(
        CartItem.objects.select_related('group_buy__product'),
        pk=item_id,
        cart__user=request.user,
    )
    slug = item.group_buy.product.slug
    item.delete()
    messages.success(request, 'Item removed from cart.')
    return redirect('cart_detail')


@login_required(login_url='users:signin')
def pledge_list(request):
    entries = GroupBuyEntry.objects.filter(user=request.user).select_related(
        'group_buy__product',
        'variation',
    ).prefetch_related('group_buy__product__files').order_by('-updated_at')

    pledge_groups = []
    grouped = {}
    group_order = []
    for entry in entries:
        group_buy = entry.group_buy
        if group_buy.pk not in grouped:
            grouped[group_buy.pk] = {
                'group_buy': group_buy,
                'product': group_buy.product,
                'entries': [],
                'total_units': 0,
                'estimated_total': group_buy.unit_price * 0,
                'latest_activity': entry.updated_at,
            }
            group_order.append(group_buy.pk)
        bucket = grouped[group_buy.pk]
        bucket['entries'].append(entry)
        bucket['total_units'] += entry.quantity
        bucket['estimated_total'] += entry.line_total
        if entry.updated_at > bucket['latest_activity']:
            bucket['latest_activity'] = entry.updated_at

    pledge_groups = [grouped[pk] for pk in group_order]
    pledge_groups.sort(key=lambda item: item['latest_activity'], reverse=True)

    for group in pledge_groups:
        group['entries'].sort(key=lambda entry: entry.updated_at, reverse=True)
        group_buy = group['group_buy']
        group['latest_paid_order'] = get_user_latest_paid_order(request.user, group_buy)
        group['pending_payment'] = get_pending_mpesa_payment(request.user, group_buy)
        group['can_confirm'] = can_confirm_pledge_order(request.user, group_buy)
        group['is_paid'] = group['latest_paid_order'] is not None

    summary = {
        'active_group_buys': len(pledge_groups),
        'total_pledges': sum(group['total_units'] for group in pledge_groups),
    }

    return render(request, 'core/pledges/list.html', {
        'pledge_groups': pledge_groups,
        'summary': summary,
    })


def _get_user_group_buy_pledge_context(user, group_buy_id):
    group_buy = get_object_or_404(
        GroupBuy.objects.select_related('product'),
        pk=group_buy_id,
    )
    entries = list(
        GroupBuyEntry.objects.filter(user=user, group_buy=group_buy).select_related('variation')
    )
    if not entries:
        return None
    return {
        'group_buy': group_buy,
        'product': group_buy.product,
        'entries': entries,
        'total_units': sum(entry.quantity for entry in entries),
        'total_amount': pledge_checkout_total(entries, group_buy),
        'order': get_user_order_for_group_buy(user, group_buy),
        'can_confirm': can_confirm_pledge_order(user, group_buy),
    }


@login_required(login_url='users:signin')
def confirm_order_checkout(request, group_buy_id):
    context = _get_user_group_buy_pledge_context(request.user, group_buy_id)
    if not context:
        messages.error(request, 'No bookings found for this group buy.')
        return redirect('pledge_list')

    if not context['can_confirm']:
        pending = get_pending_mpesa_payment(request.user, context['group_buy'])
        if pending:
            return redirect('payment_pending', payment_id=pending.pk)
        messages.error(request, 'Unable to pay for this group buy.')
        return redirect('pledge_list')

    if is_mpesa_enabled():
        pending = get_pending_mpesa_payment(request.user, context['group_buy'])
        if pending:
            return redirect('payment_pending', payment_id=pending.pk)

    addresses = list(get_user_addresses(request.user))
    default_address = get_user_default_address(request.user)
    context['addresses'] = addresses
    context['default_address'] = default_address
    context['selected_address_id'] = (
        default_address.pk if default_address else (addresses[0].pk if addresses else None)
    )
    context['mpesa_enabled'] = is_mpesa_enabled()
    context['amount_kes'] = usd_to_kes(context['total_amount'])
    context['default_mpesa_phone'] = default_mpesa_phone_for_user(request.user)
    return render(request, 'core/pledges/confirm.html', context)


@login_required(login_url='users:signin')
@require_POST
def confirm_order_pay(request, group_buy_id):
    group_buy = get_object_or_404(GroupBuy.objects.select_related('product'), pk=group_buy_id)
    address_id = request.POST.get('address_id')
    address = get_user_address(request.user, address_id) if address_id else None

    if not address:
        messages.error(request, 'Select a delivery address before paying.')
        return redirect('confirm_order_checkout', group_buy_id=group_buy.pk)

    if is_mpesa_enabled():
        mpesa_phone = request.POST.get('mpesa_phone', '').strip()
        if not mpesa_phone:
            messages.error(request, 'Enter your M-Pesa phone number.')
            return redirect('confirm_order_checkout', group_buy_id=group_buy.pk)

        try:
            order, payment = prepare_checkout_order(request.user, group_buy, address)
            payment = ensure_mpesa_stk_push(payment, mpesa_phone)
        except ValidationError as exc:
            messages.error(request, '; '.join(exc.messages))
            return redirect('confirm_order_checkout', group_buy_id=group_buy.pk)
        except (MpesaConfigError, MpesaAPIError) as exc:
            messages.error(request, f'M-Pesa error: {exc}')
            return redirect('confirm_order_checkout', group_buy_id=group_buy.pk)
        except ValueError as exc:
            messages.error(request, str(exc))
            return redirect('confirm_order_checkout', group_buy_id=group_buy.pk)

        messages.info(
            request,
            payment.result_description or 'Check your phone to complete M-Pesa payment.',
        )
        return redirect('payment_pending', payment_id=payment.pk)

    try:
        order, payment = complete_payment_and_create_order(request.user, group_buy, address)
    except ValidationError as exc:
        messages.error(request, '; '.join(exc.messages))
        return redirect('confirm_order_checkout', group_buy_id=group_buy.pk)

    messages.success(
        request,
        f'Demo payment — order #{order.pk} confirmed (no M-Pesa charge). Ref {payment.reference}.',
    )
    return redirect('order_detail', order_id=order.pk)


@login_required(login_url='users:signin')
def order_list(request):
    orders = list(
        Order.objects.filter(user=request.user).select_related(
            'group_buy__product',
            'group_buy__import_batch',
            'payment',
            'fulfillment',
        ).prefetch_related(
            'items__variation',
            'group_buy__product__files',
            'refunds',
        )
    )
    for order in orders:
        if order.status == Order.Status.PAID:
            order.fulfillment = create_fulfillment_for_order(order)

    summary = {
        'order_count': len(orders),
        'paid_count': sum(1 for order in orders if order.status == Order.Status.PAID),
        'pending_count': sum(1 for order in orders if order.status == Order.Status.PENDING_PAYMENT),
        'refunded_count': sum(1 for order in orders if order.status == Order.Status.REFUNDED),
        'total_spent': sum(
            (order.total_amount for order in orders if order.status == Order.Status.PAID),
            Decimal('0.00'),
        ),
        'total_units': sum(
            sum(item.quantity for item in order.items.all())
            for order in orders
        ),
    }

    return render(request, 'core/orders/list.html', {
        'orders': orders,
        'summary': summary,
    })


@login_required(login_url='users:signin')
def order_detail(request, order_id):
    order = get_object_or_404(
        Order.objects.select_related(
            'group_buy__product',
            'group_buy__import_batch',
            'user',
            'payment',
            'fulfillment',
            'delivery_address',
        ).prefetch_related(
            'items__variation',
            'group_buy__product__files',
            'refunds',
            'complaints',
        ),
        pk=order_id,
        user=request.user,
    )
    if order.status == Order.Status.PAID:
        create_fulfillment_for_order(order)
        order = Order.objects.select_related(
            'group_buy__product',
            'group_buy__import_batch',
            'user',
            'payment',
            'fulfillment',
            'delivery_address',
        ).prefetch_related(
            'items__variation',
            'group_buy__product__files',
            'refunds',
            'complaints',
        ).get(pk=order_id, user=request.user)
    return render(request, 'core/orders/detail.html', {
        'order': order,
    })


def _address_next_url(request, fallback='address_list'):
    next_url = request.GET.get('next') or request.POST.get('next')
    if next_url and next_url.startswith('/'):
        return next_url
    return fallback


@login_required(login_url='users:signin')
def address_list(request):
    addresses = get_user_addresses(request.user)
    return render(request, 'core/addresses/list.html', {
        'addresses': addresses,
    })


@login_required(login_url='users:signin')
def address_create(request):
    next_url = request.GET.get('next', '')

    if request.method == 'POST':
        form = AddressForm(request.POST, user=request.user)
        if form.is_valid():
            address = form.save()
            messages.success(request, 'Address saved.')
            redirect_to = _address_next_url(request)
            if redirect_to != 'address_list':
                return redirect(redirect_to)
            return redirect('address_list')
        messages.error(request, 'Please correct the errors below.')
    else:
        initial = {}
        user = request.user
        if user.first_name:
            initial['recipient_name'] = user.get_full_name()
        if user.phone:
            initial['phone'] = user.phone
        if not Address.objects.filter(user=user).exists():
            initial['is_default'] = True
        form = AddressForm(initial=initial, user=request.user)

    return render(request, 'core/addresses/form.html', {
        'form': form,
        'title': 'Add delivery address',
        'next_url': next_url,
    })


@login_required(login_url='users:signin')
def address_edit(request, address_id):
    address = get_object_or_404(Address.objects.filter(user=request.user), pk=address_id)
    next_url = request.GET.get('next', '')

    if request.method == 'POST':
        form = AddressForm(request.POST, instance=address, user=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, 'Address updated.')
            redirect_to = _address_next_url(request)
            if redirect_to != 'address_list':
                return redirect(redirect_to)
            return redirect('address_list')
        messages.error(request, 'Please correct the errors below.')
    else:
        form = AddressForm(instance=address, user=request.user)

    return render(request, 'core/addresses/form.html', {
        'form': form,
        'title': 'Edit delivery address',
        'address': address,
        'next_url': next_url,
    })


@login_required(login_url='users:signin')
@require_POST
def address_delete(request, address_id):
    address = get_object_or_404(Address.objects.filter(user=request.user), pk=address_id)
    was_default = address.is_default
    address.delete()
    if was_default:
        replacement = get_user_addresses(request.user).first()
        if replacement:
            replacement.is_default = True
            replacement.save(update_fields=['is_default', 'updated_at'])
    messages.success(request, 'Address removed.')
    return redirect('address_list')


@login_required(login_url='users:signin')
@require_POST
def address_set_default(request, address_id):
    address = get_object_or_404(Address.objects.filter(user=request.user), pk=address_id)
    address.is_default = True
    address.save()
    messages.success(request, 'Default address updated.')
    return redirect('address_list')


@login_required(login_url='users:signin')
def wishlist_list(request):
    items = get_user_wishlist_items(request.user)
    return render(request, 'core/wishlist/list.html', {
        'items': items,
    })


@login_required(login_url='users:signin')
@require_POST
def wishlist_toggle(request):
    product = get_object_or_404(
        Product.objects.select_related('category'),
        pk=request.POST.get('product_id'),
        is_active=True,
        category__is_active=True,
    )
    added = toggle_wishlist(request.user, product)
    if added:
        messages.success(request, f'"{product.name}" saved to your wishlist.')
    else:
        messages.info(request, f'"{product.name}" removed from your wishlist.')

    next_url = request.POST.get('next', '')
    if next_url and url_has_allowed_host_and_scheme(
        next_url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return redirect(next_url)
    return redirect('product_detail', slug=product.slug)


@login_required(login_url='users:signin')
@require_POST
def wishlist_remove(request, product_id):
    product = get_object_or_404(
        Product,
        pk=product_id,
        is_active=True,
    )
    remove_from_wishlist(request.user, product_id)
    messages.success(request, f'"{product.name}" removed from your wishlist.')
    return redirect('wishlist_list')


@require_GET
def set_currency(request):
    currency = normalize_currency(request.GET.get('currency'))
    if currency in SUPPORTED_CURRENCIES:
        set_display_currency(request, currency)

    next_url = request.GET.get('next', '')
    if next_url and url_has_allowed_host_and_scheme(
        next_url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return redirect(next_url)

    referer = request.META.get('HTTP_REFERER', '')
    if referer and url_has_allowed_host_and_scheme(
        referer,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return redirect(referer)
    return redirect('home:landing')


@login_required(login_url='users:signin')
def complaint_list(request):
    complaints = Complaint.objects.filter(
        user=request.user,
    ).select_related(
        'order__group_buy__product',
    ).order_by('-created_at')

    summary = {
        'total': complaints.count(),
        'open_count': complaints.filter(
            status__in=[Complaint.Status.OPEN, Complaint.Status.IN_PROGRESS],
        ).count(),
        'resolved_count': complaints.filter(status=Complaint.Status.RESOLVED).count(),
    }

    return render(request, 'core/complaints/list.html', {
        'complaints': complaints,
        'summary': summary,
    })


@login_required(login_url='users:signin')
def complaint_create(request):
    order = None
    order_id = request.GET.get('order') or request.POST.get('order')
    if order_id:
        order = get_object_or_404(
            Order.objects.select_related('group_buy__product'),
            pk=order_id,
            user=request.user,
        )

    if request.method == 'POST':
        form = ComplaintForm(request.POST, user=request.user, initial_order=order)
        if form.is_valid():
            complaint = create_complaint(
                user=request.user,
                order=form.cleaned_data['order'],
                category=form.cleaned_data['category'],
                subject=form.cleaned_data['subject'],
                description=form.cleaned_data['description'],
            )
            messages.success(
                request,
                f'Issue submitted. Reference {complaint.reference} — we will respond soon.',
            )
            return redirect('complaint_detail', complaint_id=complaint.pk)
        messages.error(request, 'Please correct the errors below.')
    else:
        form = ComplaintForm(user=request.user, initial_order=order)

    return render(request, 'core/complaints/create.html', {
        'form': form,
        'linked_order': order,
    })


@login_required(login_url='users:signin')
def complaint_detail(request, complaint_id):
    complaint = get_object_or_404(
        Complaint.objects.select_related(
            'order__group_buy__product',
            'user',
        ).prefetch_related('messages__author'),
        pk=complaint_id,
        user=request.user,
    )

    if request.method == 'POST' and complaint.is_open:
        message_form = ComplaintMessageForm(request.POST)
        if message_form.is_valid():
            try:
                add_complaint_message(
                    complaint=complaint,
                    author=request.user,
                    body=message_form.cleaned_data['body'],
                )
                messages.success(request, 'Message sent.')
                return redirect('complaint_detail', complaint_id=complaint.pk)
            except ValidationError as exc:
                messages.error(request, '; '.join(getattr(exc, 'messages', [str(exc)])))
        else:
            messages.error(request, 'Please enter a message.')
    else:
        message_form = ComplaintMessageForm()

    return render(request, 'core/complaints/detail.html', {
        'complaint': complaint,
        'message_form': message_form,
    })

