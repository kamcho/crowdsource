from django.contrib.auth import get_user_model
from django.contrib.auth.signals import user_logged_in
from django.core.exceptions import ValidationError
from django.db.models.signals import m2m_changed, post_save
from django.dispatch import receiver

from core.product_variation import ProductVariation
from .context import get_current_tenant
from .models import Tenant, TenantMembership


@receiver(post_save, sender=get_user_model())
def add_user_to_current_tenant(sender, instance, created, **kwargs):
    if not created:
        return
    tenant = get_current_tenant() or Tenant.objects.filter(is_default=True).first()
    if tenant is None:
        return
    role = {
        'admin': TenantMembership.Role.ADMIN,
        'staff': TenantMembership.Role.STAFF,
    }.get(instance.role, TenantMembership.Role.CUSTOMER)
    TenantMembership.objects.get_or_create(
        tenant=tenant,
        user=instance,
        defaults={'role': role},
    )


@receiver(user_logged_in)
def add_logged_in_user_to_current_tenant(sender, request, user, **kwargs):
    tenant = getattr(request, 'tenant', None) or get_current_tenant()
    if tenant is None:
        return
    TenantMembership.objects.get_or_create(
        tenant=tenant,
        user=user,
        defaults={'role': TenantMembership.Role.CUSTOMER},
    )


@receiver(m2m_changed, sender=ProductVariation.option_values.through)
def validate_variation_option_value_tenant(sender, instance, action, pk_set, **kwargs):
    if action != 'pre_add' or not pk_set:
        return

    foreign_tenant_value = instance.option_values.model._base_manager.filter(
        pk__in=pk_set,
    ).exclude(tenant_id=instance.tenant_id).exists()
    if foreign_tenant_value:
        raise ValidationError('Option values must belong to the same tenant.')
