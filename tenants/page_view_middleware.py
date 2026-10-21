import ipaddress

from .models import TenantPageView


class TenantPageViewMiddleware:
    excluded_prefixes = ('/api/', '/media/', '/static/', '/webhooks/')

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        tenant = getattr(request, 'tenant', None)
        content_type = response.get('Content-Type', '').split(';', 1)[0].strip()

        if (
            tenant is not None
            and request.method == 'GET'
            and response.status_code == 200
            and content_type == 'text/html'
            and not request.path.startswith(self.excluded_prefixes)
        ):
            raw_ip = (
                request.META.get('HTTP_X_REAL_IP')
                or request.META.get('REMOTE_ADDR')
                or ''
            ).strip()
            try:
                ip_address = str(ipaddress.ip_address(raw_ip)) if raw_ip else None
            except ValueError:
                ip_address = None

            TenantPageView.objects.create(
                tenant=tenant,
                user=request.user if request.user.is_authenticated else None,
                path=request.path[:2048],
                ip_address=ip_address,
            )

        return response
