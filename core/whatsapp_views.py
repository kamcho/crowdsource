import json
import logging

from django.conf import settings
from django.http import HttpResponse, HttpResponseForbidden
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from core.whatsapp_services import process_webhook_payload, verify_webhook_signature

logger = logging.getLogger('crowdsource.whatsapp')


@csrf_exempt
@require_http_methods(['GET', 'POST'])
def whatsapp_webhook(request):
    if request.method == 'GET':
        return _verify_subscription(request)

    body = request.body
    signature = request.headers.get('X-Hub-Signature-256', '')
    if not verify_webhook_signature(body, signature):
        logger.warning('Rejected WhatsApp webhook with invalid signature')
        return HttpResponseForbidden('Invalid signature')

    try:
        payload = json.loads(body.decode('utf-8'))
    except (json.JSONDecodeError, UnicodeDecodeError):
        logger.warning('Invalid WhatsApp webhook JSON')
        return HttpResponse(status=400)

    handled = process_webhook_payload(payload)
    logger.info('WhatsApp webhook processed %s message(s)', handled)
    return HttpResponse(status=200)


def _verify_subscription(request):
    mode = request.GET.get('hub.mode')
    token = request.GET.get('hub.verify_token')
    challenge = request.GET.get('hub.challenge', '')
    expected = getattr(settings, 'WHATSAPP_VERIFY_TOKEN', '').strip()

    if mode == 'subscribe' and token and expected and token == expected:
        return HttpResponse(challenge, content_type='text/plain')

    logger.warning('WhatsApp webhook verification failed')
    return HttpResponseForbidden('Verification failed')
