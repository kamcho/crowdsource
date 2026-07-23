from core.models import Product
from core.wishlist import WishlistItem


def get_user_wishlist_items(user):
    return WishlistItem.objects.filter(user=user).select_related(
        'product__category',
    ).prefetch_related(
        'product__files',
        'product__group_buys',
        'product__variations',
    )


def get_wishlisted_product_ids(user):
    if not user.is_authenticated:
        return []
    return list(
        WishlistItem.objects.filter(user=user).values_list('product_id', flat=True)
    )


def is_wishlisted(user, product):
    if not user.is_authenticated:
        return False
    return WishlistItem.objects.filter(user=user, product_id=product.pk).exists()


def toggle_wishlist(user, product):
    item = WishlistItem.objects.filter(user=user, product=product).first()
    if item:
        item.delete()
        return False
    WishlistItem.objects.create(user=user, product=product)
    return True


def remove_from_wishlist(user, product_id):
    WishlistItem.objects.filter(user=user, product_id=product_id).delete()
