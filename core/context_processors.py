from django.urls import reverse

from core.refund import Refund
from core.complaint import Complaint

from .category_utils import build_category_image_map, build_category_nav_tree, build_category_tree
from .currency import get_display_currency, get_exchange_rate
from .models import Category


def cart_summary(request):
    if not getattr(request, 'user', None) or not request.user.is_authenticated:
        return {'cart_item_count': 0}
    cart = request.user.cart.first()
    if cart is None:
        return {'cart_item_count': 0}
    return {'cart_item_count': cart.item_count}


def wishlist_summary(request):
    if not getattr(request, 'user', None) or not request.user.is_authenticated:
        return {
            'wishlist_count': 0,
            'wishlisted_product_ids': [],
        }
    from core.wishlist_services import get_wishlisted_product_ids

    product_ids = get_wishlisted_product_ids(request.user)
    return {
        'wishlist_count': len(product_ids),
        'wishlisted_product_ids': product_ids,
    }


def admin_sidebar(request):
    user = getattr(request, 'user', None)
    from tenants.permissions import user_is_tenant_ops

    if not user_is_tenant_ops(user, getattr(request, 'tenant', None)):
        return {}
    if not request.path.startswith('/core/'):
        return {}
    return {
        'stats': {
            'refunds_pending': Refund.objects.filter(status=Refund.Status.PENDING).count(),
            'complaints_open': Complaint.objects.filter(
                status__in=[Complaint.Status.OPEN, Complaint.Status.IN_PROGRESS],
            ).count(),
        },
    }


def tenant_context(request):
    from tenants.permissions import (
        get_tenant_membership,
        user_can_manage_tenants,
        user_is_tenant_admin,
        user_is_tenant_ops,
    )

    tenant = getattr(request, 'tenant', None)
    user = getattr(request, 'user', None)
    membership = get_tenant_membership(user, tenant)
    return {
        'current_tenant': tenant,
        'tenant_membership': membership,
        'tenant_is_admin': user_is_tenant_admin(user, tenant),
        'tenant_is_ops': user_is_tenant_ops(user, tenant),
        'can_manage_tenants': user_can_manage_tenants(user),
    }


def currency(request):
    return {
        'display_currency': get_display_currency(request),
        'usd_to_kes_rate': get_exchange_rate(),
    }


def category_nav(request):
    categories = list(Category.objects.filter(is_active=True).select_related('parent'))
    browse_url = reverse('home:product_browse')
    tree = build_category_nav_tree(categories)
    image_map = build_category_image_map(categories)

    def attach_meta(nodes):
        enriched = []
        for node in nodes:
            enriched.append({
                **node,
                'url': f'{browse_url}?category={node["slug"]}',
                'image_url': image_map.get(node['id']),
                'children': attach_meta(node['children']),
            })
        return enriched

    return {
        'category_nav_tree': attach_meta(tree),
        'category_filter_rows': build_category_tree(categories),
    }


def site_contact(request):
    from django.conf import settings

    raw = getattr(settings, 'SITE_CONTACT_PHONE', '').strip()
    display = getattr(settings, 'SITE_CONTACT_PHONE_DISPLAY', '').strip() or raw
    digits = ''.join(character for character in raw if character.isdigit())
    tel_href = f'tel:+{digits}' if digits else ''
    whatsapp_href = f'https://wa.me/{digits}' if digits else ''
    return {
        'site_contact_phone': display,
        'site_contact_phone_tel': tel_href,
        'site_contact_whatsapp_url': whatsapp_href,
    }
