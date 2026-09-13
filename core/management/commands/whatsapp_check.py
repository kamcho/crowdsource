"""Verify WhatsApp Cloud API credentials."""

from django.core.management.base import BaseCommand

from core.whatsapp import check_access_token, is_whatsapp_configured, whatsapp_backend
from core.whatsapp_media import get_whatsapp_public_base_url, is_whatsapp_reachable_url


class Command(BaseCommand):
    help = 'Check WhatsApp Cloud API access token and configuration.'

    def handle(self, *args, **options):
        backend = whatsapp_backend()
        self.stdout.write(f'Backend: {backend}')

        public_base = get_whatsapp_public_base_url()
        self.stdout.write(f'Public media base: {public_base}')
        if not is_whatsapp_reachable_url(public_base):
            self.stdout.write(self.style.ERROR(
                'Product images will NOT show in WhatsApp — set WHATSAPP_PUBLIC_BASE_URL '
                'to a public HTTPS URL (ngrok in dev, https://kenyaimports.com in prod).',
            ))
        else:
            self.stdout.write(self.style.SUCCESS('Public media base URL looks reachable.'))

        if not is_whatsapp_configured():
            self.stdout.write(self.style.ERROR(
                'WhatsApp is not configured. Set WHATSAPP_ENABLED, '
                'WHATSAPP_PHONE_NUMBER_ID, and WHATSAPP_ACCESS_TOKEN.',
            ))
            return

        if backend == 'console':
            self.stdout.write(self.style.WARNING(
                'WHATSAPP_BACKEND=console — messages are logged, not sent via Meta.',
            ))
            return

        error = check_access_token()
        if error:
            self.stdout.write(self.style.ERROR(f'Token check failed: {error}'))
            self.stdout.write(
                'Generate a new token: Meta Developer Console → your app → '
                'WhatsApp → API setup → Generate access token. '
                'For production, create a permanent System User token.',
            )
            return

        self.stdout.write(self.style.SUCCESS('WhatsApp access token is valid.'))
