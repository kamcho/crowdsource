def get_user_dashboard_context(user):
    from core.group_buy import GroupBuyEntry
    from core.order import Order
    from core.wishlist_services import get_wishlisted_product_ids

    orders = Order.objects.filter(user=user)
    pledges = GroupBuyEntry.objects.filter(user=user)
    cart = getattr(user, 'cart', None)

    recent_orders = list(
        orders.filter(status=Order.Status.PAID)
        .select_related('group_buy__product')
        .order_by('-created_at')[:4]
    )
    recent_pledges = list(
        pledges.select_related('group_buy__product', 'variation')
        .order_by('-created_at')[:4]
    )

    return {
        'user_stats': {
            'pledges': pledges.count(),
            'orders': orders.filter(status=Order.Status.PAID).count(),
            'pending_orders': orders.filter(status=Order.Status.PENDING_PAYMENT).count(),
            'cart_items': cart.item_count if cart else 0,
            'wishlist_items': len(get_wishlisted_product_ids(user)),
        },
        'recent_orders': recent_orders,
        'recent_pledges': recent_pledges,
    }
