"""WhatsApp support bot tools — catalog and customer account queries."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from django.conf import settings
from django.db.models import Q

from core.category_utils import get_category_descendant_ids
from core.complaint import Complaint
from core.group_buy import GroupBuyEntry
from core.models import Category, Product
from core.order import Order
from core.payment import Payment
from core.refund import Refund
from home.catalog import get_public_products_queryset

MAX_TOOL_PRODUCTS = 5

PLATFORM_TOPICS = {
    'overview': (
        f'{settings.SITE_NAME} helps buyers in Kenya import products from China through group buys. '
        'Multiple buyers pledge units together until MOQ is reached, then the batch is imported and delivered.'
    ),
    'group_buys': (
        'A group buy opens for a product with a minimum order quantity (MOQ). '
        'Buyers pledge how many units they want. When pledged units reach MOQ, the buy closes and import begins. '
        'You pay only after pledging; payment confirms your spot.'
    ),
    'moq': (
        'MOQ (minimum order quantity) is the number of units needed before the supplier will produce or ship the batch. '
        'Each product page shows pledged units vs MOQ and progress percentage.'
    ),
    'signup': (
        'Create an account with your Kenyan phone number on the website, browse products, and pledge on open group buys. '
        'Use the same phone on WhatsApp to check order status here.'
    ),
    'payments': (
        'Orders are paid via M-Pesa after you pledge. Payment status appears on your order page once confirmed.'
    ),
    'shipping': (
        'After MOQ is reached, goods are imported from China and delivered to your saved Kenya address. '
        'Delivery details are collected at checkout.'
    ),
    'catalog': (
        'Browse all active products on the website catalog. Ask me to search by name, category, or product id.'
    ),
}


@dataclass
class ToolResult:
    data: dict
    products: list = field(default_factory=list)


def _unlinked_account_result(record_key: str) -> ToolResult:
    signup_url = (
        f'{settings.SITE_PROTOCOL}://{settings.SITE_DOMAIN}/users/signup/'
    )
    return ToolResult(data={
        'ok': False,
        'account_linked': False,
        'message': (
            'No account was found for this WhatsApp number. '
            f'Sign up at {signup_url} using this same phone number, then ask again.'
        ),
        'signup_url': signup_url,
        record_key: [],
    })


def _product_summary(product: Product) -> dict:
    from core.pricing import format_price_range, product_variation_price_range

    price_min, price_max = product_variation_price_range(product)
    group_buy = product.active_group_buy
    summary = {
        'id': product.pk,
        'name': product.name,
        'category': product.category.get_breadcrumb(),
        'url_path': product.get_absolute_url(),
    }
    price_text = format_price_range(price_min, price_max)
    if price_text:
        summary['price'] = price_text
    if group_buy:
        summary['group_buy'] = {
            'pledged_units': group_buy.pledged_units,
            'moq': group_buy.moq,
            'progress_percent': group_buy.progress_percent,
        }
    return summary


def _products_payload(products) -> list[dict]:
    return [_product_summary(product) for product in products]


def find_matching_categories(query: str):
    query = (query or '').strip().lower()
    if not query:
        return []

    categories = list(Category.objects.filter(is_active=True).select_related('parent', 'parent__parent'))
    matches = []
    seen = set()

    def add(category):
        if category.pk not in seen:
            seen.add(category.pk)
            matches.append(category)

    for category in categories:
        name = category.name.lower()
        breadcrumb = category.get_breadcrumb().lower()
        if query in name or query in breadcrumb or name in query:
            add(category)
            continue
        for token in re.findall(r'[a-z]{3,}', name):
            if token in query or query in token:
                add(category)
                break

    query_words = [word for word in re.findall(r'[a-z]{3,}', query)]
    for category in categories:
        name_tokens = re.findall(r'[a-z]{3,}', category.name.lower())
        if any(
            word in name_token or name_token in word
            for word in query_words
            for name_token in name_tokens
        ):
            add(category)

    return matches


def search_products(*, query: str = '', category_name: str = '', limit: int = MAX_TOOL_PRODUCTS) -> ToolResult:
    limit = max(1, min(int(limit or MAX_TOOL_PRODUCTS), MAX_TOOL_PRODUCTS))
    base_qs = get_public_products_queryset()
    products = []
    matched_categories = []

    if category_name:
        matched_categories = find_matching_categories(category_name)

    if query:
        text_filter = Q(name__icontains=query) | Q(description__icontains=query)
        text_filter |= Q(category__name__icontains=query)
        products = list(base_qs.filter(text_filter).distinct()[:limit])

        if not products:
            for category in find_matching_categories(query):
                if category not in matched_categories:
                    matched_categories.append(category)

    if matched_categories and len(products) < limit:
        category_ids = set()
        for category in matched_categories:
            category_ids.update(get_category_descendant_ids(category))
        remaining = limit - len(products)
        category_products = list(
            base_qs.filter(category_id__in=category_ids).exclude(
                pk__in=[product.pk for product in products],
            )[:remaining],
        )
        products.extend(category_products)

    category_labels = [category.get_breadcrumb() for category in matched_categories]
    if products:
        message = f'Found {len(products)} product(s)'
        if category_labels:
            message += f' in {", ".join(category_labels[:2])}'
        elif query:
            message += f' matching "{query}"'
    elif query or category_name:
        message = f'No products found for "{query or category_name}"'
    else:
        message = 'No products found'

    return ToolResult(
        data={
            'ok': bool(products),
            'message': message,
            'query': query,
            'categories': category_labels,
            'products': _products_payload(products),
        },
        products=products,
    )


def browse_category(*, category_name: str, limit: int = MAX_TOOL_PRODUCTS) -> ToolResult:
    return search_products(query='', category_name=category_name, limit=limit)


def get_product_by_id(*, product_id: int) -> ToolResult:
    product = get_public_products_queryset().filter(pk=product_id).first()
    if not product:
        return ToolResult(data={
            'ok': False,
            'message': f'Product #{product_id} was not found or is not active.',
            'products': [],
        })
    return ToolResult(
        data={
            'ok': True,
            'message': f'Found product #{product_id}',
            'products': _products_payload([product]),
        },
        products=[product],
    )


def list_catalog(*, limit: int = MAX_TOOL_PRODUCTS, user=None) -> ToolResult:
    limit = max(1, min(int(limit or MAX_TOOL_PRODUCTS), MAX_TOOL_PRODUCTS))
    products = []

    if user and user.is_authenticated:
        from core.preference_services import get_suggested_products_for_user

        products = get_suggested_products_for_user(user, limit=limit)

    if not products:
        products = list(get_public_products_queryset()[:limit])

    return ToolResult(
        data={
            'ok': bool(products),
            'message': f'Showing {len(products)} product(s) from the catalog',
            'products': _products_payload(products),
        },
        products=products,
    )


def list_categories() -> ToolResult:
    categories = Category.objects.filter(is_active=True).select_related('parent', 'parent__parent')
    rows = [
        {
            'name': category.name,
            'breadcrumb': category.get_breadcrumb(),
            'slug': category.slug,
        }
        for category in categories.order_by('name')
    ]
    return ToolResult(data={
        'ok': bool(rows),
        'message': f'{len(rows)} active categories',
        'categories': rows,
    })


def get_my_orders(*, user, order_id: int | None = None) -> ToolResult:
    if not user or not user.is_authenticated:
        return _unlinked_account_result('orders')

    orders_qs = (
        Order.objects.filter(user=user)
        .select_related('group_buy__product')
        .order_by('-created_at')
    )
    if order_id:
        orders_qs = orders_qs.filter(pk=order_id)

    orders = list(orders_qs[:5 if not order_id else 1])
    rows = [
        {
            'id': order.pk,
            'status': order.get_status_display(),
            'product': order.group_buy.product.name,
            'total_amount': str(order.total_amount),
        }
        for order in orders
    ]
    if order_id and not rows:
        message = f'Order #{order_id} was not found on your account.'
    elif not rows:
        message = 'No orders found for your account.'
    else:
        message = f'Found {len(rows)} order(s)'

    return ToolResult(data={
        'ok': bool(rows),
        'message': message,
        'orders': rows,
    })


def get_my_group_buys(*, user, group_buy_id: int | None = None) -> ToolResult:
    if not user or not user.is_authenticated:
        return _unlinked_account_result('group_buys')

    entries_qs = (
        GroupBuyEntry.objects.filter(user=user)
        .select_related('group_buy__product', 'variation')
        .order_by('-created_at')
    )
    if group_buy_id:
        entries_qs = entries_qs.filter(group_buy_id=group_buy_id)

    entries = list(entries_qs[:5 if not group_buy_id else 20])
    rows = [
        {
            'group_buy_id': entry.group_buy_id,
            'product': entry.group_buy.product.name,
            'status': entry.group_buy.get_status_display(),
            'quantity': entry.quantity,
            'variation': entry.variation.display_name if entry.variation_id else None,
            'moq': entry.group_buy.moq,
            'pledged_units': entry.group_buy.pledged_units,
            'units_remaining': entry.group_buy.units_remaining,
            'closes_at': entry.group_buy.closes_at.isoformat(),
        }
        for entry in entries
    ]
    if group_buy_id and not rows:
        message = f'No group-buy pledge #{group_buy_id} was found on your account.'
    elif not rows:
        message = 'No group-buy pledges found for your account.'
    else:
        message = f'Found {len(rows)} group-buy pledge(s)'

    return ToolResult(data={
        'ok': bool(rows),
        'message': message,
        'group_buys': rows,
    })


def get_my_complaints(*, user, reference: str = '', order_id: int | None = None) -> ToolResult:
    if not user or not user.is_authenticated:
        return _unlinked_account_result('complaints')

    complaints_qs = Complaint.objects.filter(user=user).select_related('order').order_by('-created_at')
    if reference:
        complaints_qs = complaints_qs.filter(reference__iexact=reference.strip())
    if order_id:
        complaints_qs = complaints_qs.filter(order_id=order_id)

    complaints = list(complaints_qs[:5 if not reference else 1])
    rows = [
        {
            'reference': complaint.reference,
            'subject': complaint.subject,
            'category': complaint.get_category_display(),
            'status': complaint.get_status_display(),
            'order_id': complaint.order_id,
            'description': complaint.description[:300],
            'created_at': complaint.created_at.isoformat(),
        }
        for complaint in complaints
    ]
    if reference and not rows:
        message = f'Complaint {reference} was not found on your account.'
    elif not rows:
        message = 'No complaints found for your account.'
    else:
        message = f'Found {len(rows)} complaint(s)'

    return ToolResult(data={
        'ok': bool(rows),
        'message': message,
        'complaints': rows,
    })


def get_my_payments(
    *,
    user,
    reference: str = '',
    order_id: int | None = None,
) -> ToolResult:
    if not user or not user.is_authenticated:
        return _unlinked_account_result('payments')

    payments_qs = (
        Payment.objects.filter(user=user)
        .select_related('order', 'group_buy__product')
        .order_by('-created_at')
    )
    if reference:
        payments_qs = payments_qs.filter(reference__iexact=reference.strip())
    if order_id:
        payments_qs = payments_qs.filter(order_id=order_id)

    payments = list(payments_qs[:5 if not reference else 1])
    rows = [
        {
            'reference': payment.reference,
            'status': payment.get_status_display(),
            'amount': str(payment.amount),
            'product': payment.group_buy.product.name,
            'order_id': payment.order_id,
            'receipt_number': payment.mpesa_receipt_number or None,
            'created_at': payment.created_at.isoformat(),
            'completed_at': payment.completed_at.isoformat() if payment.completed_at else None,
        }
        for payment in payments
    ]
    if reference and not rows:
        message = f'Payment {reference} was not found on your account.'
    elif not rows:
        message = 'No payments found for your account.'
    else:
        message = f'Found {len(rows)} payment(s)'

    return ToolResult(data={
        'ok': bool(rows),
        'message': message,
        'payments': rows,
    })


def get_my_refunds(
    *,
    user,
    reference: str = '',
    order_id: int | None = None,
) -> ToolResult:
    if not user or not user.is_authenticated:
        return _unlinked_account_result('refunds')

    refunds_qs = (
        Refund.objects.filter(order__user=user)
        .select_related('order__group_buy__product')
        .order_by('-created_at')
    )
    if reference:
        refunds_qs = refunds_qs.filter(reference__iexact=reference.strip())
    if order_id:
        refunds_qs = refunds_qs.filter(order_id=order_id)

    refunds = list(refunds_qs[:5 if not reference else 1])
    rows = [
        {
            'reference': refund.reference,
            'status': refund.get_status_display(),
            'type': refund.get_refund_type_display(),
            'amount': str(refund.amount),
            'reason': refund.reason,
            'order_id': refund.order_id,
            'product': refund.order.group_buy.product.name,
            'created_at': refund.created_at.isoformat(),
            'completed_at': refund.completed_at.isoformat() if refund.completed_at else None,
        }
        for refund in refunds
    ]
    if reference and not rows:
        message = f'Refund {reference} was not found on your account.'
    elif not rows:
        message = 'No refunds found for your account.'
    else:
        message = f'Found {len(rows)} refund(s)'

    return ToolResult(data={
        'ok': bool(rows),
        'message': message,
        'refunds': rows,
    })


def get_platform_info(*, topic: str = 'overview') -> ToolResult:
    topic = (topic or 'overview').strip().lower().replace('-', '_').replace(' ', '_')
    if topic not in PLATFORM_TOPICS:
        topic = 'overview'
    return ToolResult(data={
        'ok': True,
        'topic': topic,
        'message': PLATFORM_TOPICS[topic],
    })


def get_active_category_names() -> list[str]:
    return list(
        Category.objects.filter(is_active=True)
        .order_by('name')
        .values_list('name', flat=True),
    )


TOOL_DEFINITIONS = [
    {
        'type': 'function',
        'function': {
            'name': 'search_products',
            'description': (
                'Search the product catalog by keyword and/or category. '
                'Use for requests like "handbags", "earbuds", "show me makeup". '
                'Matches product names, descriptions, and category names.'
            ),
            'parameters': {
                'type': 'object',
                'properties': {
                    'query': {
                        'type': 'string',
                        'description': 'Search phrase, e.g. handbag, watch, product type.',
                    },
                    'category_name': {
                        'type': 'string',
                        'description': 'Optional category filter, e.g. Bags, Electronics.',
                    },
                    'limit': {
                        'type': 'integer',
                        'description': 'Max products to return (1-5).',
                    },
                },
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'browse_category',
            'description': 'List products in a category such as Bags, Electronics, or Tote Bags.',
            'parameters': {
                'type': 'object',
                'properties': {
                    'category_name': {
                        'type': 'string',
                        'description': 'Category name or keyword, e.g. bags, electronics.',
                    },
                    'limit': {
                        'type': 'integer',
                        'description': 'Max products to return (1-5).',
                    },
                },
                'required': ['category_name'],
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'get_product_by_id',
            'description': 'Fetch one product when the user gives a numeric product id.',
            'parameters': {
                'type': 'object',
                'properties': {
                    'product_id': {
                        'type': 'integer',
                        'description': 'Numeric product id from the catalog.',
                    },
                },
                'required': ['product_id'],
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'list_catalog',
            'description': (
                'Show available products when the user asks what you sell, '
                'what is available, or to browse the catalog.'
            ),
            'parameters': {
                'type': 'object',
                'properties': {
                    'limit': {
                        'type': 'integer',
                        'description': 'Max products to return (1-5).',
                    },
                },
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'list_categories',
            'description': 'List product categories when the user asks what categories or types you carry.',
            'parameters': {
                'type': 'object',
                'properties': {},
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'get_my_orders',
            'description': (
                'Look up the customer orders linked to their WhatsApp phone number. '
                'Use for order status, delivery, or payment questions.'
            ),
            'parameters': {
                'type': 'object',
                'properties': {
                    'order_id': {
                        'type': 'integer',
                        'description': 'Optional specific order id, e.g. "order 42".',
                    },
                },
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'get_my_group_buys',
            'description': (
                'Look up the group buys and quantities the customer has pledged. '
                'Use for questions about their own group-buy participation, MOQ progress, or pledge status.'
            ),
            'parameters': {
                'type': 'object',
                'properties': {
                    'group_buy_id': {
                        'type': 'integer',
                        'description': 'Optional specific group-buy id.',
                    },
                },
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'get_my_complaints',
            'description': (
                'Look up the customer complaints and their status. Use for complaint or support-case updates.'
            ),
            'parameters': {
                'type': 'object',
                'properties': {
                    'reference': {
                        'type': 'string',
                        'description': 'Optional complaint reference, e.g. CP-ABC123.',
                    },
                    'order_id': {
                        'type': 'integer',
                        'description': 'Optional order id to find related complaints.',
                    },
                },
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'get_my_payments',
            'description': (
                'Look up the customer payment status, amount, and M-Pesa receipt. '
                'Use for questions about a payment or payment reference.'
            ),
            'parameters': {
                'type': 'object',
                'properties': {
                    'reference': {
                        'type': 'string',
                        'description': 'Optional payment reference, e.g. CS-ABC123.',
                    },
                    'order_id': {
                        'type': 'integer',
                        'description': 'Optional order id.',
                    },
                },
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'get_my_refunds',
            'description': (
                'Look up the customer refund status, amount, and reason. '
                'Use for questions about a refund or refund reference.'
            ),
            'parameters': {
                'type': 'object',
                'properties': {
                    'reference': {
                        'type': 'string',
                        'description': 'Optional refund reference, e.g. RF-ABC123.',
                    },
                    'order_id': {
                        'type': 'integer',
                        'description': 'Optional order id.',
                    },
                },
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'get_platform_info',
            'description': (
                'Answer general questions about how Kenya Imports / CrowdSource works: '
                'group buys, MOQ, signup, payments, shipping.'
            ),
            'parameters': {
                'type': 'object',
                'properties': {
                    'topic': {
                        'type': 'string',
                        'enum': list(PLATFORM_TOPICS.keys()),
                        'description': 'Which platform topic to explain.',
                    },
                },
            },
        },
    },
]


def execute_tool(name: str, arguments: dict, *, user=None) -> ToolResult:
    if name == 'search_products':
        return search_products(
            query=str(arguments.get('query') or ''),
            category_name=str(arguments.get('category_name') or ''),
            limit=arguments.get('limit') or MAX_TOOL_PRODUCTS,
        )
    if name == 'browse_category':
        return browse_category(
            category_name=str(arguments.get('category_name') or ''),
            limit=arguments.get('limit') or MAX_TOOL_PRODUCTS,
        )
    if name == 'get_product_by_id':
        return get_product_by_id(product_id=int(arguments['product_id']))
    if name == 'list_catalog':
        return list_catalog(limit=arguments.get('limit') or MAX_TOOL_PRODUCTS, user=user)
    if name == 'list_categories':
        return list_categories()
    if name == 'get_my_orders':
        order_id = arguments.get('order_id')
        return get_my_orders(user=user, order_id=int(order_id) if order_id else None)
    if name == 'get_my_group_buys':
        group_buy_id = arguments.get('group_buy_id')
        return get_my_group_buys(
            user=user,
            group_buy_id=int(group_buy_id) if group_buy_id else None,
        )
    if name == 'get_my_complaints':
        order_id = arguments.get('order_id')
        return get_my_complaints(
            user=user,
            reference=str(arguments.get('reference') or ''),
            order_id=int(order_id) if order_id else None,
        )
    if name == 'get_my_payments':
        order_id = arguments.get('order_id')
        return get_my_payments(
            user=user,
            reference=str(arguments.get('reference') or ''),
            order_id=int(order_id) if order_id else None,
        )
    if name == 'get_my_refunds':
        order_id = arguments.get('order_id')
        return get_my_refunds(
            user=user,
            reference=str(arguments.get('reference') or ''),
            order_id=int(order_id) if order_id else None,
        )
    if name == 'get_platform_info':
        return get_platform_info(topic=str(arguments.get('topic') or 'overview'))
    return ToolResult(data={'ok': False, 'message': f'Unknown tool: {name}'})
