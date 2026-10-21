from urllib.parse import urlsplit

from django.conf import settings

from .context import get_current_tenant


def get_tenant_domain(tenant=None):
    tenant = tenant or get_current_tenant()
    site_domain = getattr(settings, 'SITE_DOMAIN', '').strip().strip('/')
    if tenant is None or tenant.is_default:
        return site_domain

    base_domain = getattr(settings, 'TENANT_BASE_DOMAIN', '').strip().strip('.')
    if not base_domain:
        return site_domain

    domain = f'{tenant.slug}.{base_domain}'
    if settings.DEBUG:
        port = urlsplit(f'//{site_domain}').port
        if port:
            domain = f'{domain}:{port}'
    return domain


def get_tenant_site_name(tenant=None):
    tenant = tenant or get_current_tenant()
    return tenant.name if tenant else getattr(settings, 'SITE_NAME', 'Kenya Imports')
