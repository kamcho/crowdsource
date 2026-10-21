from django.conf import settings
from django.http import Http404

from .context import reset_current_tenant, set_current_tenant
from .models import Tenant


class TenantMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
        base_domain = self._host_without_port(
            getattr(settings, 'TENANT_BASE_DOMAIN', ''),
        ).lower()
        self.base_domain = (
            base_domain[4:] if base_domain.startswith('www.') else base_domain
        )

    def __call__(self, request):
        host = self._host_without_port(request.get_host()).lower().rstrip('.')
        tenant = self._resolve_tenant(host)
        if tenant is None or not tenant.is_active:
            raise Http404('Tenant not found')

        request.tenant = tenant
        token = set_current_tenant(tenant)
        try:
            return self.get_response(request)
        finally:
            reset_current_tenant(token)

    def _resolve_tenant(self, host):
        if host in self._default_hosts():
            return Tenant.objects.filter(is_default=True, is_active=True).first()

        suffix = f'.{self.base_domain}' if self.base_domain else ''
        if suffix and host.endswith(suffix):
            slug = host[:-len(suffix)]
            if slug and '.' not in slug:
                return Tenant.objects.filter(slug=slug, is_active=True).first()
            return None

        if settings.DEBUG and host in {'testserver', 'localhost', '127.0.0.1'}:
            return Tenant.objects.filter(is_default=True, is_active=True).first()
        return None

    def _default_hosts(self):
        hosts = {self.base_domain, f'www.{self.base_domain}'}
        hosts.add('testserver')
        if settings.DEBUG:
            hosts.update({'localhost', '127.0.0.1'})
        return hosts

    @staticmethod
    def _host_without_port(host):
        if host.startswith('['):
            return host.split(']')[0] + ']'
        return host.rsplit(':', 1)[0] if host.count(':') == 1 else host
