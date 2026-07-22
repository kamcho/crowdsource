import logging
from abc import ABC, abstractmethod

from django.conf import settings
from django.core.mail import send_mail

from core.notification import NotificationLog

logger = logging.getLogger('crowdsource.notifications')


class NotificationBackend(ABC):
    @abstractmethod
    def send_sms(self, recipient, body):
        pass

    @abstractmethod
    def send_email(self, recipient, subject, body):
        pass


class ConsoleNotificationBackend(NotificationBackend):
    def send_sms(self, recipient, body):
        logger.info('[NOTIFY SMS] to=%s | %s', recipient, body)
        return True

    def send_email(self, recipient, subject, body):
        logger.info('[NOTIFY EMAIL] to=%s subject=%s | %s', recipient, subject, body)
        return True


class TextSmsNotificationBackend(NotificationBackend):
    """SMS via TextSMS (textsms.co.ke); email via Django mail backend."""

    def __init__(self):
        self._email_backend = DjangoEmailNotificationBackend()

    def send_sms(self, recipient, body):
        if not getattr(settings, 'TEXTSMS_ENABLED', False):
            logger.info('[NOTIFY SMS disabled] to=%s | %s', recipient, body)
            return True

        from core.textsms import TextSmsAPIError, TextSmsConfigError, send_sms

        try:
            result = send_sms(mobile=recipient, message=body)
            logger.info(
                'TextSMS sent message_id=%s to=%s',
                result.get('message_id'),
                recipient,
            )
            return True
        except TextSmsConfigError:
            logger.warning('TextSMS not configured; logging SMS instead of sending')
            return ConsoleNotificationBackend().send_sms(recipient, body)
        except TextSmsAPIError:
            raise

    def send_email(self, recipient, subject, body):
        return self._email_backend.send_email(recipient, subject, body)


class AfricasTalkingNotificationBackend(NotificationBackend):
    def send_sms(self, recipient, body):
        username = getattr(settings, 'AFRICASTALKING_USERNAME', '')
        api_key = getattr(settings, 'AFRICASTALKING_API_KEY', '')
        if not username or not api_key:
            raise RuntimeError(
                'AFRICASTALKING_USERNAME and AFRICASTALKING_API_KEY are required '
                'when NOTIFICATION_BACKEND=africas_talking.',
            )
        raise NotImplementedError(
            'Africa\'s Talking SMS integration is not wired yet. '
            'Set NOTIFICATION_BACKEND=console for local development.',
        )

    def send_email(self, recipient, subject, body):
        raise NotImplementedError('Africa\'s Talking email is not configured; use SendGrid or SMTP.')


class TwilioNotificationBackend(NotificationBackend):
    def send_sms(self, recipient, body):
        if not getattr(settings, 'TWILIO_ACCOUNT_SID', ''):
            raise RuntimeError('TWILIO_ACCOUNT_SID is required when NOTIFICATION_BACKEND=twilio.')
        raise NotImplementedError(
            'Twilio SMS integration is not wired yet. '
            'Set NOTIFICATION_BACKEND=console for local development.',
        )

    def send_email(self, recipient, subject, body):
        raise NotImplementedError('Twilio email is not configured; use SendGrid or SMTP.')


class SendGridNotificationBackend(NotificationBackend):
    def send_sms(self, recipient, body):
        raise NotImplementedError('SendGrid does not send SMS; configure a SMS backend separately.')

    def send_email(self, recipient, subject, body):
        if not getattr(settings, 'SENDGRID_API_KEY', ''):
            raise RuntimeError('SENDGRID_API_KEY is required when NOTIFICATION_BACKEND=sendgrid.')
        raise NotImplementedError(
            'SendGrid email integration is not wired yet. '
            'Set NOTIFICATION_BACKEND=console for local development.',
        )


class DjangoEmailNotificationBackend(NotificationBackend):
    """Console SMS + Django email backend (SMTP or console)."""

    def __init__(self):
        self._console = ConsoleNotificationBackend()

    def send_sms(self, recipient, body):
        return self._console.send_sms(recipient, body)

    def send_email(self, recipient, subject, body):
        send_mail(
            subject=subject,
            message=body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[recipient],
            fail_silently=False,
        )
        return True


def _get_backend():
    backend_name = getattr(settings, 'NOTIFICATION_BACKEND', 'console')
    if backend_name == 'console':
        return ConsoleNotificationBackend()
    if backend_name == 'textsms':
        return TextSmsNotificationBackend()
    if backend_name == 'africas_talking':
        return AfricasTalkingNotificationBackend()
    if backend_name == 'twilio':
        return TwilioNotificationBackend()
    if backend_name == 'sendgrid':
        return SendGridNotificationBackend()
    if backend_name == 'django_email':
        return DjangoEmailNotificationBackend()
    raise ValueError(f'Unknown NOTIFICATION_BACKEND: {backend_name}')


def resolve_user_phone(user, order=None):
    if user and user.phone:
        return str(user.phone)
    if order and order.delivery_phone:
        return str(order.delivery_phone)
    return ''


def _normalize_sms_recipient(phone):
    if not phone:
        return ''
    from core.textsms import normalize_kenyan_mobile
    try:
        return normalize_kenyan_mobile(phone)
    except ValueError:
        return phone


def resolve_user_email(user):
    if user and user.email:
        return user.email.strip()
    return ''


def _log_notification(*, user, event, channel, recipient, subject, body, status, error_message=''):
    NotificationLog.objects.create(
        user=user,
        event=event,
        channel=channel,
        recipient=recipient or '—',
        subject=subject,
        body=body,
        status=status,
        error_message=error_message,
    )


def notify_user(user, event, *, sms_body='', email_subject='', email_body='', order=None):
    backend = _get_backend()
    sms_enabled = getattr(settings, 'NOTIFICATION_SMS_ENABLED', True)
    email_enabled = getattr(settings, 'NOTIFICATION_EMAIL_ENABLED', True)

    phone = resolve_user_phone(user, order=order)
    email = resolve_user_email(user)

    if sms_enabled and sms_body:
        if phone:
            sms_recipient = _normalize_sms_recipient(phone)
            try:
                backend.send_sms(sms_recipient, sms_body)
                _log_notification(
                    user=user, event=event, channel=NotificationLog.Channel.SMS,
                    recipient=sms_recipient, subject='', body=sms_body,
                    status=NotificationLog.Status.SENT,
                )
            except Exception as exc:
                logger.exception('SMS notification failed for %s', event)
                _log_notification(
                    user=user, event=event, channel=NotificationLog.Channel.SMS,
                    recipient=sms_recipient, subject='', body=sms_body,
                    status=NotificationLog.Status.FAILED, error_message=str(exc),
                )
        else:
            _log_notification(
                user=user, event=event, channel=NotificationLog.Channel.SMS,
                recipient='', subject='', body=sms_body,
                status=NotificationLog.Status.SKIPPED, error_message='No phone number',
            )

    if email_enabled and email_body:
        subject = email_subject or f'CrowdSource — {event.replace(".", " ").title()}'
        if email:
            try:
                backend.send_email(email, subject, email_body)
                _log_notification(
                    user=user, event=event, channel=NotificationLog.Channel.EMAIL,
                    recipient=email, subject=subject, body=email_body,
                    status=NotificationLog.Status.SENT,
                )
            except Exception as exc:
                logger.exception('Email notification failed for %s', event)
                _log_notification(
                    user=user, event=event, channel=NotificationLog.Channel.EMAIL,
                    recipient=email, subject=subject, body=email_body,
                    status=NotificationLog.Status.FAILED, error_message=str(exc),
                )
        else:
            _log_notification(
                user=user, event=event, channel=NotificationLog.Channel.EMAIL,
                recipient='', subject=subject, body=email_body,
                status=NotificationLog.Status.SKIPPED, error_message='No email address',
            )


def notify_group_buy_pledgers(group_buy, event, *, sms_body='', email_subject='', email_body=''):
    from core.group_buy import GroupBuyEntry

    user_ids = set()
    entries = GroupBuyEntry.objects.filter(group_buy=group_buy).select_related('user')
    for entry in entries:
        if entry.user_id in user_ids:
            continue
        user_ids.add(entry.user_id)
        notify_user(
            entry.user, event,
            sms_body=sms_body.format(product=group_buy.product.name),
            email_subject=email_subject.format(product=group_buy.product.name) if email_subject else '',
            email_body=email_body.format(product=group_buy.product.name) if email_body else '',
        )


def notify_group_buy_paid_buyers(group_buy, event, *, sms_body='', email_subject='', email_body=''):
    from core.order import Order

    orders = Order.objects.filter(
        group_buy=group_buy,
        status__in=[Order.Status.PAID, Order.Status.REFUNDED],
    ).select_related('user')
    notified = set()
    for order in orders:
        if order.user_id in notified:
            continue
        notified.add(order.user_id)
        message = sms_body.format(
            product=group_buy.product.name,
            order_id=order.pk,
        ) if '{' in sms_body else sms_body
        email_msg = email_body.format(
            product=group_buy.product.name,
            order_id=order.pk,
        ) if email_body and '{' in email_body else email_body
        notify_user(
            order.user, event,
            sms_body=message,
            email_subject=email_subject.format(product=group_buy.product.name) if email_subject else '',
            email_body=email_msg,
            order=order,
        )


# --- Event helpers ---

def notify_payment_completed(order, payment):
    product = order.group_buy.product.name
    kes_part = f' (KES {payment.amount_kes})' if payment.amount_kes else ''
    sms = (
        f'CrowdSource: Payment received for order #{order.pk} ({product}). '
        f'Ref {payment.reference}{kes_part}.'
    )
    email = (
        f'Hi {order.user.get_full_name()},\n\n'
        f'Your payment for order #{order.pk} ({product}) was received.\n'
        f'Reference: {payment.reference}\n'
        f'Amount: ${payment.amount}\n\n'
        f'We will notify you when your import and delivery status changes.\n'
    )
    notify_user(
        order.user, 'payment.completed',
        sms_body=sms,
        email_subject=f'Payment confirmed — Order #{order.pk}',
        email_body=email,
        order=order,
    )


def notify_moq_reached(group_buy):
    sms = (
        'CrowdSource: MOQ reached for {product}! '
        'The bulk import will be arranged soon. We will keep you updated.'
    )
    email = (
        'Good news — the minimum order quantity was reached for {product}.\n\n'
        'The bulk import from China will be arranged soon. '
        'You will receive updates as the shipment progresses.\n'
    )
    notify_group_buy_pledgers(
        group_buy, 'group_buy.moq_reached',
        sms_body=sms,
        email_subject='MOQ reached — {product}',
        email_body=email,
    )


def notify_group_buy_cancelled(group_buy):
    sms = (
        'CrowdSource: The group buy for {product} was cancelled. '
        'Contact support if you already paid.'
    )
    email = (
        'The group buy for {product} has been cancelled.\n\n'
        'If you already paid, our team will arrange a refund. '
        'Contact support if you have questions.\n'
    )
    notify_group_buy_pledgers(
        group_buy, 'group_buy.cancelled',
        sms_body=sms,
        email_subject='Group buy cancelled — {product}',
        email_body=email,
    )


def notify_import_batch_created(batch):
    product = batch.group_buy.product.name
    sms = f'CrowdSource: Bulk import scheduled for {product}. We will update you as it moves.'
    email = (
        f'Bulk import has been scheduled for {product}.\n\n'
        f'{batch.buyer_status_message}\n'
    )
    notify_group_buy_paid_buyers(
        batch.group_buy, 'import_batch.created',
        sms_body=sms,
        email_subject=f'Import scheduled — {product}',
        email_body=email,
    )


def notify_import_batch_status_changed(batch, old_status, new_status):
    if old_status == new_status:
        return
    product = batch.group_buy.product.name
    message = batch.buyer_status_message
    sms = f'CrowdSource: {product} import update — {message}'
    email = (
        f'Import update for {product}:\n\n'
        f'Status: {batch.get_status_display()}\n'
        f'{message}\n'
    )
    notify_group_buy_paid_buyers(
        batch.group_buy, 'import_batch.status_changed',
        sms_body=sms,
        email_subject=f'Import update — {product}',
        email_body=email,
    )


def notify_fulfillment_status_changed(fulfillment, old_status, new_status):
    if old_status == new_status:
        return

    notify_events = {
        fulfillment.Status.OUT_FOR_DELIVERY,
        fulfillment.Status.DELIVERED,
        fulfillment.Status.FAILED,
    }
    if new_status not in notify_events:
        return

    order = fulfillment.order
    product = order.group_buy.product.name
    message = fulfillment.buyer_status_message
    tracking = fulfillment.tracking_reference
    sms = f'CrowdSource: Order #{order.pk} ({product}) — {message}'
    if tracking and new_status == fulfillment.Status.OUT_FOR_DELIVERY:
        sms = f'{sms} Tracking: {tracking}.'

    email = (
        f'Delivery update for order #{order.pk} ({product}):\n\n'
        f'{message}\n'
    )
    if tracking:
        email += f'\nTracking reference: {tracking}\n'

    notify_user(
        order.user, 'fulfillment.status_changed',
        sms_body=sms,
        email_subject=f'Delivery update — Order #{order.pk}',
        email_body=email,
        order=order,
    )


def notify_refund_created(refund):
    order = refund.order
    product = order.group_buy.product.name
    sms = (
        f'CrowdSource: Refund of ${refund.amount} initiated for order #{order.pk} ({product}). '
        f'Ref {refund.reference}. We will confirm once processed.'
    )
    email = (
        f'A refund of ${refund.amount} was initiated for order #{order.pk} ({product}).\n\n'
        f'Reference: {refund.reference}\n'
        f'Reason: {refund.reason}\n\n'
        f'You will receive another message once the refund is completed.\n'
    )
    notify_user(
        order.user, 'refund.created',
        sms_body=sms,
        email_subject=f'Refund initiated — Order #{order.pk}',
        email_body=email,
        order=order,
    )


def notify_refund_completed(refund):
    order = refund.order
    product = order.group_buy.product.name
    sms = (
        f'CrowdSource: Refund of ${refund.amount} completed for order #{order.pk} ({product}). '
        f'Ref {refund.reference}.'
    )
    email = (
        f'Your refund of ${refund.amount} for order #{order.pk} ({product}) is complete.\n\n'
        f'Reference: {refund.reference}\n'
    )
    notify_user(
        order.user, 'refund.completed',
        sms_body=sms,
        email_subject=f'Refund completed — Order #{order.pk}',
        email_body=email,
        order=order,
    )
