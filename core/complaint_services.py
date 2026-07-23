from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from core.complaint import Complaint, ComplaintMessage


def create_complaint(*, user, category, subject, description, order=None):
    complaint = Complaint(
        user=user,
        order=order,
        category=category,
        subject=subject.strip(),
        description=description.strip(),
    )
    complaint.full_clean()
    complaint.save()
    return complaint


def add_complaint_message(*, complaint, author, body, is_staff_reply=False):
    body = body.strip()
    if not body:
        raise ValidationError('Message cannot be empty.')

    if not is_staff_reply and complaint.user_id != author.pk:
        raise ValidationError('You can only reply to your own complaint.')
    if is_staff_reply and not author.is_ops_user:
        raise ValidationError('Only staff can send internal replies.')

    if not complaint.is_open and not is_staff_reply:
        raise ValidationError('This complaint is closed. Open a new issue if you need more help.')

    message = ComplaintMessage.objects.create(
        complaint=complaint,
        author=author,
        body=body,
        is_staff_reply=is_staff_reply,
    )
    if is_staff_reply and complaint.status == Complaint.Status.OPEN:
        complaint.status = Complaint.Status.IN_PROGRESS
        complaint.save(update_fields=['status', 'updated_at'])
    return message


@transaction.atomic
def update_complaint_status(*, complaint, status, staff_notes=''):
    if status not in Complaint.Status.values:
        raise ValidationError('Invalid status.')

    complaint.status = status
    update_fields = ['status', 'updated_at']
    if staff_notes is not None:
        complaint.staff_notes = staff_notes.strip()
        update_fields.append('staff_notes')

    if status in {Complaint.Status.RESOLVED, Complaint.Status.CLOSED}:
        complaint.resolved_at = timezone.now()
        update_fields.append('resolved_at')
    elif complaint.resolved_at:
        complaint.resolved_at = None
        update_fields.append('resolved_at')

    complaint.save(update_fields=update_fields)
    return complaint
