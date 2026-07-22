import json
from calendar import month_abbr
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db.models import Count, Exists, OuterRef, Sum
from django.db.models.functions import TruncMonth
from django.utils import timezone

from core.fulfillment import Fulfillment
from core.group_buy import GroupBuy, GroupBuyEntry
from core.import_batch import ImportBatch
from core.models import Category, Product
from core.refund import Refund
from core.supplier import Supplier
from core.order import Order
from core.payment import Payment


def get_admin_dashboard_context(*, full_admin_access=True):
    User = get_user_model()

    pledged_units = GroupBuyEntry.objects.aggregate(total=Sum('quantity'))['total'] or 0

    stats = {
        'group_buys': GroupBuy.objects.count(),
        'orders_paid': Order.objects.filter(status=Order.Status.PAID).count(),
        'orders_pending': Order.objects.filter(status=Order.Status.PENDING_PAYMENT).count(),
        'pledges': GroupBuyEntry.objects.count(),
        'pledged_units': pledged_units,
        'import_batches': ImportBatch.objects.count(),
        'fulfillments': Fulfillment.objects.count(),
        'fulfillments_delivered': Fulfillment.objects.filter(
            status=Fulfillment.Status.DELIVERED,
        ).count(),
        'fulfillments_in_progress': Fulfillment.objects.filter(
            status__in=[
                Fulfillment.Status.PENDING,
                Fulfillment.Status.PACKED,
                Fulfillment.Status.OUT_FOR_DELIVERY,
            ],
        ).count(),
        'refunds_pending': Refund.objects.filter(status=Refund.Status.PENDING).count(),
        'refunds_completed': Refund.objects.filter(status=Refund.Status.COMPLETED).count(),
    }

    if full_admin_access:
        revenue = Order.objects.filter(status=Order.Status.PAID).aggregate(
            total=Sum('total_amount'),
        )['total'] or Decimal('0.00')
        stats.update({
            'users': User.objects.count(),
            'products': Product.objects.count(),
            'products_active': Product.objects.filter(is_active=True).count(),
            'categories': Category.objects.filter(is_active=True).count(),
            'suppliers': Supplier.objects.filter(is_active=True).count(),
            'revenue': revenue,
            'payments': Payment.objects.filter(status=Payment.Status.COMPLETED).count(),
        })

    group_buy_status = {
        row['status']: row['count']
        for row in GroupBuy.objects.values('status').annotate(count=Count('id'))
    }
    group_buy_pipeline = [
        {
            'status': status,
            'label': label,
            'count': group_buy_status.get(status, 0),
        }
        for status, label in GroupBuy.Status.choices
    ]

    fulfillment_status = {
        row['status']: row['count']
        for row in Fulfillment.objects.values('status').annotate(count=Count('id'))
    }
    fulfillment_pipeline = [
        {
            'status': status,
            'label': label,
            'count': fulfillment_status.get(status, 0),
        }
        for status, label in Fulfillment.Status.choices
    ]

    has_import_batch = ImportBatch.objects.filter(group_buy_id=OuterRef('pk'))
    moq_without_batch = GroupBuy.objects.filter(
        status=GroupBuy.Status.MOQ_REACHED,
    ).annotate(
        has_batch=Exists(has_import_batch),
    ).filter(
        has_batch=False,
    ).select_related('product').order_by('-updated_at')[:6]

    recent_orders = list(
        Order.objects.filter(status=Order.Status.PAID)
        .select_related('user', 'group_buy__product', 'fulfillment')
        .order_by('-updated_at')[:8]
    )

    pending_deliveries = list(
        Fulfillment.objects.filter(
            status__in=[
                Fulfillment.Status.PENDING,
                Fulfillment.Status.PACKED,
                Fulfillment.Status.OUT_FOR_DELIVERY,
            ],
        )
        .select_related('order__user', 'order__group_buy__product')
        .order_by('status', '-updated_at')[:8]
    )

    pending_refunds = list(
        Refund.objects.filter(status=Refund.Status.PENDING)
        .select_related('order__user', 'order__group_buy__product', 'created_by')
        .order_by('-created_at')[:8]
    )

    active_group_buys = list(
        GroupBuy.objects.filter(
            status__in=[
                GroupBuy.Status.OPEN,
                GroupBuy.Status.MOQ_REACHED,
                GroupBuy.Status.IMPORTING,
            ],
        )
        .select_related('product')
        .annotate(pledged_total=Sum('entries__quantity'))
        .order_by('-updated_at')[:6]
    )

    chart_months = []
    chart_orders = []
    chart_revenue = []
    today = timezone.localdate()
    month_cursor = today.replace(day=1)
    month_keys = []
    for _ in range(6):
        month_keys.append(month_cursor)
        if month_cursor.month == 1:
            month_cursor = month_cursor.replace(year=month_cursor.year - 1, month=12)
        else:
            month_cursor = month_cursor.replace(month=month_cursor.month - 1)
    month_keys.reverse()

    paid_orders = Order.objects.filter(status=Order.Status.PAID)
    monthly_orders = {
        row['month'].date(): row['count']
        for row in paid_orders.annotate(month=TruncMonth('created_at')).values('month').annotate(count=Count('id'))
    }
    monthly_revenue = {}
    if full_admin_access:
        monthly_revenue = {
            row['month'].date(): float(row['total'] or 0)
            for row in paid_orders.annotate(month=TruncMonth('created_at')).values('month').annotate(total=Sum('total_amount'))
        }

    for month_start in month_keys:
        chart_months.append(month_abbr[month_start.month])
        chart_orders.append(monthly_orders.get(month_start, 0))
        chart_revenue.append(monthly_revenue.get(month_start, 0))

    group_buy_status_chart = [
        {
            'label': label,
            'count': group_buy_status.get(status, 0),
        }
        for status, label in GroupBuy.Status.choices
        if group_buy_status.get(status, 0) > 0
    ] or [
        {'label': label, 'count': 0}
        for status, label in GroupBuy.Status.choices[:3]
    ]

    campaign_progress = []
    for group_buy in active_group_buys[:4]:
        pledged = group_buy.pledged_total or 0
        moq = group_buy.moq or 1
        campaign_progress.append({
            'name': group_buy.product.name,
            'status': group_buy.get_status_display(),
            'pledged': pledged,
            'moq': moq,
            'percent': min(int((pledged / moq) * 100), 100),
        })

    return {
        'stats': stats,
        'group_buy_pipeline': group_buy_pipeline,
        'fulfillment_pipeline': fulfillment_pipeline,
        'moq_without_batch': list(moq_without_batch),
        'recent_orders': recent_orders,
        'pending_deliveries': pending_deliveries,
        'pending_refunds': pending_refunds,
        'active_group_buys': active_group_buys,
        'chart_months_json': json.dumps(chart_months),
        'chart_orders_json': json.dumps(chart_orders),
        'chart_revenue_json': json.dumps(chart_revenue),
        'group_buy_status_chart': group_buy_status_chart,
        'group_buy_status_chart_json': json.dumps(group_buy_status_chart),
        'campaign_progress': campaign_progress,
    }
