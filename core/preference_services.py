from datetime import timedelta

from django.db.models import F
from django.utils import timezone

from core.category_utils import get_category_descendant_ids
from core.models import Category
from core.user_preference import UserCategoryPreference, UserCategoryViewStat, UserProductView

from home.catalog import get_public_products_queryset

SUGGESTED_PRODUCTS_LIMIT = 12
VIEW_DEBOUNCE_MINUTES = 30
VIEWS_FOR_PARENT_PREFERENCE = 3


def get_explicit_preferred_category_ids(user):
    if not user or not user.is_authenticated:
        return []
    return list(
        UserCategoryPreference.objects.filter(user=user).values_list('category_id', flat=True)
    )


def infer_category_ids_from_activity(user):
    if not user or not user.is_authenticated:
        return []

    from core.group_buy import GroupBuyEntry
    from core.order import Order
    from core.wishlist import WishlistItem

    category_ids = set()

    category_ids.update(
        WishlistItem.objects.filter(user=user).values_list('product__category_id', flat=True)
    )
    category_ids.update(
        Order.objects.filter(user=user, status=Order.Status.PAID).values_list(
            'group_buy__product__category_id',
            flat=True,
        )
    )
    category_ids.update(
        GroupBuyEntry.objects.filter(user=user).values_list(
            'group_buy__product__category_id',
            flat=True,
        )
    )

    return [
        category_id
        for category_id in category_ids
        if category_id
        and Category.objects.filter(pk=category_id, is_active=True).exists()
    ]


def get_effective_preferred_category_ids(user):
    explicit = get_explicit_preferred_category_ids(user)
    if explicit:
        return explicit
    return infer_category_ids_from_activity(user)


def expand_preferred_category_ids(category_ids):
    expanded = set()
    for category in Category.objects.filter(id__in=category_ids, is_active=True):
        expanded.update(get_category_descendant_ids(category))
    return list(expanded)


def add_category_preference(user, category, *, source=UserCategoryPreference.Source.VIEWED):
    if not category or not category.is_active:
        return None

    preference, created = UserCategoryPreference.objects.get_or_create(
        user=user,
        category=category,
        defaults={'source': source},
    )
    if not created and preference.source != source and source == UserCategoryPreference.Source.MANUAL:
        preference.source = source
        preference.save(update_fields=['source'])
    return preference


def set_user_category_preferences(user, category_ids):
    valid_ids = set(
        Category.objects.filter(id__in=category_ids, is_active=True).values_list('id', flat=True)
    )
    UserCategoryPreference.objects.filter(user=user).exclude(category_id__in=valid_ids).delete()

    for category_id in valid_ids:
        add_category_preference(
            user,
            Category.objects.get(pk=category_id),
            source=UserCategoryPreference.Source.MANUAL,
        )


def record_product_view(user, product):
    """Track a product view and auto-add parent category prefs after repeated browsing."""
    if not user or not user.is_authenticated or not product.is_active:
        return None

    category = product.category
    if not category or not category.is_active:
        return None

    cutoff = timezone.now() - timedelta(minutes=VIEW_DEBOUNCE_MINUTES)
    if UserProductView.objects.filter(
        user=user,
        product=product,
        viewed_at__gte=cutoff,
    ).exists():
        return None

    UserProductView.objects.create(user=user, product=product)

    stat, _ = UserCategoryViewStat.objects.get_or_create(user=user, category=category)
    UserCategoryViewStat.objects.filter(pk=stat.pk).update(
        view_count=F('view_count') + 1,
        last_viewed_at=timezone.now(),
    )
    stat.refresh_from_db()

    if stat.view_count < VIEWS_FOR_PARENT_PREFERENCE:
        return None

    target_category = category.parent if category.parent_id else category
    if not target_category.is_active:
        return None

    return add_category_preference(
        user,
        target_category,
        source=UserCategoryPreference.Source.VIEWED,
    )


def get_viewed_category_stats(user):
    if not user or not user.is_authenticated:
        return UserCategoryViewStat.objects.none()
    return (
        UserCategoryViewStat.objects.filter(user=user, view_count__gt=0)
        .select_related('category')
        .order_by('-view_count', '-last_viewed_at')
    )


def get_preferred_categories(user):
    category_ids = get_explicit_preferred_category_ids(user)
    if not category_ids:
        return Category.objects.none()
    return Category.objects.filter(id__in=category_ids, is_active=True).order_by('name')


def get_suggested_products_for_user(user, *, limit=SUGGESTED_PRODUCTS_LIMIT):
    if not user or not user.is_authenticated:
        return []

    category_ids = get_effective_preferred_category_ids(user)
    if not category_ids:
        return []

    match_ids = expand_preferred_category_ids(category_ids)
    if not match_ids:
        return []

    queryset = get_public_products_queryset().filter(category_id__in=match_ids)
    return list(queryset[:limit])


def user_has_category_preferences(user):
    return bool(get_effective_preferred_category_ids(user))
