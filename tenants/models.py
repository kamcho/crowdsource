from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from .context import get_current_tenant


class Tenant(models.Model):
    name = models.CharField(max_length=150)
    slug = models.SlugField(max_length=80, unique=True)
    is_active = models.BooleanField(default=True)
    is_default = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']
        constraints = [
            models.UniqueConstraint(
                fields=['is_default'],
                condition=Q(is_default=True),
                name='tenants_single_default_tenant',
            ),
        ]

    def __str__(self):
        return self.name


class TenantMembership(models.Model):
    class Role(models.TextChoices):
        CUSTOMER = 'customer', 'Customer'
        STAFF = 'staff', 'Staff'
        ADMIN = 'admin', 'Admin'

    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        related_name='memberships',
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='tenant_memberships',
    )
    role = models.CharField(
        max_length=20,
        choices=Role.choices,
        default=Role.CUSTOMER,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['tenant__name', 'user__phone']
        constraints = [
            models.UniqueConstraint(
                fields=['tenant', 'user'],
                name='tenants_unique_user_membership',
            ),
        ]

    def __str__(self):
        return f'{self.user} — {self.tenant} ({self.get_role_display()})'


class TenantManager(models.Manager):
    def get_queryset(self):
        queryset = super().get_queryset()
        tenant = get_current_tenant()
        if tenant is not None:
            return queryset.filter(tenant_id=tenant.pk)
        return queryset.filter(
            tenant__is_default=True,
            tenant__is_active=True,
        )


class TenantOwnedModel(models.Model):
    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        related_name='%(app_label)s_%(class)s_records',
    )

    objects = TenantManager()

    class Meta:
        abstract = True

    def _ensure_tenant(self):
        current_tenant = get_current_tenant()
        if self.tenant_id is None:
            tenant = current_tenant or Tenant.objects.filter(is_default=True).first()
            if tenant is None:
                raise ValidationError('A tenant is required to save this record.')
            self.tenant = tenant
        elif current_tenant is not None and self.tenant_id != current_tenant.pk:
            raise ValidationError('Cannot save a record for a different tenant.')

    def full_clean(self, *args, **kwargs):
        self._ensure_tenant()
        super().full_clean(*args, **kwargs)

    def save(self, *args, **kwargs):
        self._ensure_tenant()

        for field in self._meta.concrete_fields:
            if not isinstance(field, models.ForeignKey) or field.name == 'tenant':
                continue
            related_model = field.remote_field.model
            if not any(item.name == 'tenant' for item in related_model._meta.fields):
                continue
            related_id = getattr(self, field.attname)
            if related_id is None:
                continue
            related_tenant_id = related_model._base_manager.filter(
                pk=related_id,
            ).values_list('tenant_id', flat=True).first()
            if related_tenant_id != self.tenant_id:
                raise ValidationError({
                    field.name: 'Related records must belong to the same tenant.',
                })

        super().save(*args, **kwargs)
