from django.core.paginator import Paginator
from django.db.models import Case, IntegerField, Prefetch, Q, Sum, Value, When
from django.db.models.functions import Coalesce

from core.category_utils import get_category_descendant_ids
from core.group_buy import GroupBuy
from core.models import Category, Product
from core.product_file import ProductFile
from core.product_variation import ProductVariation

PRODUCTS_PAGE_SIZE = 12
LANDING_PRODUCT_MAX = 100
HERO_CAROUSEL_MAX = 6
_SEARCH_STOPWORDS = frozenset({'a', 'an', 'and', 'for', 'of', 'the', 'to', 'with'})
_MAX_SEARCH_TOKENS = 8


def get_active_group_buys_queryset():
    return GroupBuy.objects.filter(
        status__in=[GroupBuy.Status.OPEN, GroupBuy.Status.MOQ_REACHED],
    ).annotate(
        pledged_total=Coalesce(Sum('entries__quantity'), 0),
    )


def public_search_tokens(search):
    """Words that must each match. Filler words are ignored so 'bag for laptop' still hits."""
    raw = [token.strip('.,;:!?\'"()[]{}') for token in (search or '').split()]
    tokens = [
        token for token in raw
        if len(token) >= 2 and token.lower() not in _SEARCH_STOPWORDS
    ]
    if tokens:
        return tokens[:_MAX_SEARCH_TOKENS]
    stripped = (search or '').strip()
    return [stripped] if stripped else []


def _token_match(token):
    return (
        Q(name__icontains=token)
        | Q(description__icontains=token)
        | Q(slug__icontains=token)
        | Q(category__name__icontains=token)
        | Q(category__parent__name__icontains=token)
        | Q(category__parent__parent__name__icontains=token)
    )


def _public_search_filter(search):
    combined = Q()
    for token in public_search_tokens(search):
        combined &= _token_match(token)
    return combined


def _public_search_rank(search):
    """Prefer the full phrase in the name, then products whose name contains each word."""
    rank = (
        Case(When(name__iexact=search, then=Value(100)), default=Value(0), output_field=IntegerField())
        + Case(When(name__istartswith=search, then=Value(50)), default=Value(0), output_field=IntegerField())
        + Case(When(name__icontains=search, then=Value(40)), default=Value(0), output_field=IntegerField())
    )
    for token in public_search_tokens(search):
        rank += Case(
            When(name__icontains=token, then=Value(20)),
            default=Value(0),
            output_field=IntegerField(),
        )
        rank += Case(
            When(category__name__icontains=token, then=Value(8)),
            default=Value(0),
            output_field=IntegerField(),
        )
        rank += Case(
            When(description__icontains=token, then=Value(2)),
            default=Value(0),
            output_field=IntegerField(),
        )
    return rank


def get_public_products_queryset(*, category=None, search=''):
    queryset = Product.objects.filter(
        is_active=True,
        category__is_active=True,
    )
    if category:
        queryset = queryset.filter(category_id__in=get_category_descendant_ids(category))
    search = (search or '').strip()
    if search:
        queryset = queryset.annotate(search_rank=_public_search_rank(search)).filter(
            _public_search_filter(search),
        ).order_by('-search_rank', '-created_at')
    else:
        queryset = queryset.order_by('-created_at')
    return queryset.select_related(
        'category',
        'category__parent',
        'category__parent__parent',
    ).prefetch_related(
        Prefetch(
            'files',
            queryset=ProductFile.objects.filter(variation__isnull=True),
        ),
        Prefetch(
            'variations',
            queryset=ProductVariation.objects.filter(is_active=True).only(
                'id', 'product_id', 'price', 'is_active',
            ),
        ),
        Prefetch(
            'group_buys',
            queryset=get_active_group_buys_queryset(),
            to_attr='active_group_buys_list',
        ),
    )


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
