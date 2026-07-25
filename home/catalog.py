from django.core.paginator import Paginator
from django.db.models import Prefetch, Q

from core.group_buy import GroupBuy
from core.models import Category, Product

PRODUCTS_PAGE_SIZE = 12
LANDING_PRODUCT_MAX = 100
HERO_CAROUSEL_MAX = 6


def _category_descendant_ids(category):
    ids = [category.pk]
    for child in Category.objects.filter(parent=category, is_active=True):
        ids.extend(_category_descendant_ids(child))
    return ids


def get_active_group_buys_queryset():
    return GroupBuy.objects.filter(
        status__in=[GroupBuy.Status.OPEN, GroupBuy.Status.MOQ_REACHED],
    ).prefetch_related('entries')


def get_public_products_queryset(*, category=None, search=''):
    queryset = Product.objects.filter(
        is_active=True,
        category__is_active=True,
    )
    if category:
        queryset = queryset.filter(category_id__in=_category_descendant_ids(category))
    if search:
        queryset = queryset.filter(
            Q(name__icontains=search) | Q(description__icontains=search),
        )
    active_group_buys = get_active_group_buys_queryset()
    return queryset.select_related(
        'category',
        'category__parent',
        'category__parent__parent',
    ).prefetch_related(
        'files',
        'options__values',
        'variations',
        Prefetch('group_buys', queryset=active_group_buys, to_attr='active_group_buys_list'),
    ).order_by('-created_at')


def paginate_products(queryset, page):
    paginator = Paginator(queryset, PRODUCTS_PAGE_SIZE)
    return paginator.get_page(page)


def get_filter_category(slug):
    if not slug:
        return None
    return Category.objects.filter(slug=slug, is_active=True).first()


def get_hero_carousel_products(*, limit=HERO_CAROUSEL_MAX):
    products = []
    for product in get_public_products_queryset()[:40]:
        if product.active_group_buy:
            products.append(product)
        if len(products) >= limit:
            break
    return products
