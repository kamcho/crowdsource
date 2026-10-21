from datetime import timedelta
from functools import wraps

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Count, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .context import reset_current_tenant, set_current_tenant
from .forms import TenantForm, TenantMemberCreateForm, TenantMembershipForm
from .models import Tenant, TenantMembership, TenantPageView
from .permissions import user_can_manage_tenant, user_can_manage_tenants


def tenant_management_required(view_func):
    @login_required(login_url='users:signin')
    @wraps(view_func)
    def wrapped(request, *args, **kwargs):
        if not user_can_manage_tenants(request.user):
            messages.error(request, 'You do not have permission to manage tenants.')
            return redirect('home:landing')
        return view_func(request, *args, **kwargs)

    return wrapped


def tenant_admin_required(view_func):
    @login_required(login_url='users:signin')
    @wraps(view_func)
    def wrapped(request, *args, **kwargs):
        tenant_id = kwargs.get('tenant_id')
        tenant = Tenant.objects.filter(pk=tenant_id).first()
        if not user_can_manage_tenant(request.user, tenant):
            messages.error(request, 'You do not have permission to manage this tenant.')
            return redirect('home:landing')
        return view_func(request, *args, **kwargs)

    return wrapped


@tenant_management_required
def tenant_list(request):
    tenants = Tenant.objects.annotate(
        membership_count=Count('memberships'),
    ).order_by('-is_default', 'name')
    return render(request, 'tenants/dashboard/list.html', {
        'tenants': tenants,
        'tenant_domain': settings.TENANT_BASE_DOMAIN,
    })


@tenant_management_required
def tenant_create(request):
    form = TenantForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        tenant = form.save()
        messages.success(request, f'Tenant "{tenant.name}" was created.')
        return redirect('core:tenant_edit', tenant_id=tenant.pk)

    return render(request, 'tenants/dashboard/form.html', {
        'form': form,
        'page_title': 'Create tenant',
        'tenant': None,
        'tenant_domain': settings.TENANT_BASE_DOMAIN,
    })


@tenant_admin_required
def tenant_edit(request, tenant_id):
    tenant = get_object_or_404(Tenant, pk=tenant_id)
    tenant_token = set_current_tenant(tenant)
    try:
        from core.models import Order, Product

        now = timezone.now()
        month_ago = now - timedelta(days=30)
        recent_views = TenantPageView.objects.filter(
            tenant=tenant,
            viewed_at__gte=month_ago,
        )
        analytics = {
            'products_total': Product.objects.filter(tenant=tenant).count(),
            'products_active': Product.objects.filter(
                tenant=tenant,
                is_active=True,
            ).count(),
            'orders_total': Order.objects.filter(tenant=tenant).count(),
            'orders_paid': Order.objects.filter(
                tenant=tenant,
                status=Order.Status.PAID,
            ).count(),
            'paid_revenue': Order.objects.filter(
                tenant=tenant,
                status=Order.Status.PAID,
            ).aggregate(total=Sum('total_amount'))['total'] or 0,
            'views_30_days': recent_views.count(),
            'views_7_days': recent_views.filter(
                viewed_at__gte=now - timedelta(days=7),
            ).count(),
            'unique_ips_30_days': recent_views.exclude(
                ip_address__isnull=True,
            ).values('ip_address').distinct().count(),
            'top_pages': recent_views.values('path').annotate(
                views=Count('id'),
            ).order_by('-views', 'path')[:10],
            'recent_views': TenantPageView.objects.filter(
                tenant=tenant,
            ).select_related('user')[:100],
        }
    finally:
        reset_current_tenant(tenant_token)

    form = TenantForm(
        request.POST or None,
        instance=tenant,
        allow_deactivation=request.user.is_superuser,
        allow_slug_change=request.user.is_superuser,
    )
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, f'Tenant "{tenant.name}" was updated.')
        return redirect('core:tenant_edit', tenant_id=tenant.pk)

    membership_form = TenantMembershipForm()
    create_member_form = TenantMemberCreateForm()
    memberships = tenant.memberships.select_related('user').order_by(
        'role',
        'user__phone',
    )
    return render(request, 'tenants/dashboard/form.html', {
        'form': form,
        'page_title': f'Manage {tenant.name}',
        'tenant': tenant,
        'analytics': analytics,
        'membership_form': membership_form,
        'create_member_form': create_member_form,
        'memberships': memberships,
        'tenant_domain': settings.TENANT_BASE_DOMAIN,
    })


@tenant_admin_required
@require_POST
def tenant_add_membership(request, tenant_id):
    tenant = get_object_or_404(Tenant, pk=tenant_id)
    form = TenantMembershipForm(request.POST)
    if form.is_valid():
        membership, created = TenantMembership.objects.get_or_create(
            tenant=tenant,
            user=form.cleaned_data['user'],
            defaults={'role': form.cleaned_data['role']},
        )
        if not created and membership.role != form.cleaned_data['role']:
            membership.role = form.cleaned_data['role']
            membership.save(update_fields=['role'])
        messages.success(
            request,
            f'{membership.user.get_full_name()} is now a '
            f'{membership.get_role_display().lower()} for {tenant.name}.',
        )
    else:
        for errors in form.errors.values():
            for error in errors:
                messages.error(request, error)
    return redirect('core:tenant_edit', tenant_id=tenant.pk)


@tenant_admin_required
@require_POST
def tenant_create_member(request, tenant_id):
    tenant = get_object_or_404(Tenant, pk=tenant_id)
    form = TenantMemberCreateForm(request.POST)
    if form.is_valid():
        user_model = get_user_model()
        tenant_token = set_current_tenant(tenant)
        try:
            with transaction.atomic():
                user = user_model.objects.create_user(
                    phone=form.cleaned_data['phone'],
                    password=form.cleaned_data['password'],
                    first_name=form.cleaned_data['first_name'],
                    last_name=form.cleaned_data['last_name'],
                    email=form.cleaned_data['email'],
                    role=user_model.Role.CUSTOMER,
                )
                membership, _ = TenantMembership.objects.update_or_create(
                    tenant=tenant,
                    user=user,
                    defaults={'role': form.cleaned_data['role']},
                )
        finally:
            reset_current_tenant(tenant_token)
        messages.success(
            request,
            f'Account created for {membership.user.get_full_name()} and added as '
            f'{membership.get_role_display().lower()} for {tenant.name}.',
        )
    else:
        for errors in form.errors.values():
            for error in errors:
                messages.error(request, error)
    return redirect('core:tenant_edit', tenant_id=tenant.pk)


@tenant_admin_required
@require_POST
def tenant_remove_membership(request, tenant_id, membership_id):
    tenant = get_object_or_404(Tenant, pk=tenant_id)
    membership = get_object_or_404(
        TenantMembership,
        pk=membership_id,
        tenant=tenant,
    )
    membership.delete()
    messages.success(request, 'Tenant access was removed for that user.')
    return redirect('core:tenant_edit', tenant_id=tenant.pk)
