from django.urls import reverse

from core.refund import Refund

from .category_utils import build_category_image_map, build_category_nav_tree
from .currency import get_display_currency, get_exchange_rate
from .models import Category


def cart_summary(request):
    if not getattr(request, 'user', None) or not request.user.is_authenticated:
        return {'cart_item_count': 0}
    cart = getattr(request.user, 'cart', None)
    if cart is None:
        return {'cart_item_count': 0}
    return {'cart_item_count': cart.item_count}


def admin_sidebar(request):
    user = getattr(request, 'user', None)
    if not user or not user.is_authenticated or not user.is_ops_user:
        return {}
    if not request.path.startswith('/core/'):
        return {}
    return {
        'stats': {
            'refunds_pending': Refund.objects.filter(status=Refund.Status.PENDING).count(),
        },
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

    return {'category_nav_tree': attach_meta(tree)}
