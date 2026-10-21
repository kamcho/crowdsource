from .models import TenantMembership
from .models import Tenant


def get_tenant_membership(user, tenant):
    if not user or not user.is_authenticated:
        return None
    tenant = tenant or Tenant.objects.filter(is_default=True).first()
    if tenant is None:
        return None
    return TenantMembership.objects.filter(user=user, tenant=tenant).first()


def user_has_tenant_role(user, tenant, *roles):
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    membership = get_tenant_membership(user, tenant)
    return bool(membership and membership.role in roles)


def user_is_tenant_admin(user, tenant):
    return user_has_tenant_role(user, tenant, TenantMembership.Role.ADMIN)


def user_can_manage_tenants(user):
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    default_tenant = Tenant.objects.filter(is_default=True).first()
    return user_is_tenant_admin(user, default_tenant)


def user_is_tenant_ops(user, tenant):
    return user_has_tenant_role(
        user,
        tenant,
        TenantMembership.Role.ADMIN,
        TenantMembership.Role.STAFF,
    )
