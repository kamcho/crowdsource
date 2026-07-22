import json
import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from core.mpesa import MpesaAPIError, MpesaConfigError
from core.payment import Payment
from core.payment_services import (
    default_mpesa_phone_for_user,
    ensure_mpesa_stk_push,
    poll_mpesa_payment_status,
    process_stk_callback_payload,
    retry_mpesa_stk_push,
)

logger = logging.getLogger('crowdsource.mpesa')


@csrf_exempt
@require_POST
def mpesa_callback(request):
    """Safaricom STK callback — must be publicly reachable (HTTPS)."""
    try:
        payload = json.loads(request.body.decode('utf-8'))
    except (json.JSONDecodeError, UnicodeDecodeError):
        logger.warning('Invalid M-Pesa callback payload')
        return JsonResponse({'ResultCode': 1, 'ResultDesc': 'Invalid payload'})

    payment = process_stk_callback_payload(payload)
    if not payment:
        logger.warning('M-Pesa callback for unknown payment')
    return JsonResponse({'ResultCode': 0, 'ResultDesc': 'Accepted'})


@login_required(login_url='users:signin')
def payment_pending(request, payment_id):
    payment = get_object_or_404(
        Payment.objects.select_related('order__group_buy__product'),
        pk=payment_id,
        user=request.user,
    )

    if request.method == 'POST' and payment.status == Payment.Status.PENDING:
        phone = request.POST.get('mpesa_phone', '').strip()
        retry = request.POST.get('retry') == '1'
        try:
            if retry:
                payment = retry_mpesa_stk_push(payment, phone)
            else:
                payment = ensure_mpesa_stk_push(payment, phone)
            messages.info(
                request,
                payment.result_description or 'STK push sent. Check your phone.',
            )
        except (MpesaConfigError, MpesaAPIError) as exc:
            messages.error(request, f'M-Pesa error: {exc}')
        except ValueError as exc:
            messages.error(request, str(exc))
        except ValidationError as exc:
            messages.error(request, '; '.join(getattr(exc, 'messages', [str(exc)])))
        return redirect('payment_pending', payment_id=payment.pk)

    stk_needs_phone = False
    if payment.status == Payment.Status.PENDING and not payment.stk_push_initiated:
        phone = payment.phone_number or default_mpesa_phone_for_user(request.user)
        if phone:
            try:
                payment = ensure_mpesa_stk_push(payment, phone)
            except (MpesaConfigError, MpesaAPIError, ValueError) as exc:
                messages.warning(request, f'Could not send M-Pesa prompt: {exc}')
                stk_needs_phone = True
            except ValidationError as exc:
                messages.warning(request, '; '.join(getattr(exc, 'messages', [str(exc)])))
                stk_needs_phone = True
        else:
            stk_needs_phone = True

    return render(request, 'core/payments/pending.html', {
        'payment': payment,
        'order': payment.order,
        'product': payment.order.group_buy.product if payment.order_id else None,
        'stk_needs_phone': stk_needs_phone,
        'stk_can_retry': payment.status == Payment.Status.PENDING and payment.stk_push_initiated,
        'default_mpesa_phone': default_mpesa_phone_for_user(request.user),
    })


@login_required(login_url='users:signin')
@require_GET
def payment_status(request, payment_id):
    payment = get_object_or_404(Payment, pk=payment_id, user=request.user)

    if payment.status == Payment.Status.PENDING:
        poll_mpesa_payment_status(payment)

    payment.refresh_from_db()

    redirect_url = None
    if payment.status == Payment.Status.COMPLETED and payment.order_id:
        redirect_url = reverse('order_detail', kwargs={'order_id': payment.order_id})

    return JsonResponse({
        'status': payment.status,
        'stk_initiated': payment.stk_push_initiated,
        'result_description': payment.result_description,
        'mpesa_receipt_number': payment.mpesa_receipt_number,
        'redirect_url': redirect_url,
    })
