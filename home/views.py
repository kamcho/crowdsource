from django.http import JsonResponse
from django.shortcuts import render
from django.template.loader import render_to_string
from django.views.decorators.http import require_GET

from core.category_utils import build_category_groups
from core.models import Category

from .catalog import (
    LANDING_PRODUCT_LIMIT,
    get_filter_category,
    get_public_products_queryset,
    paginate_products,
)


def landing(request):
    products = get_public_products_queryset()[:LANDING_PRODUCT_LIMIT]

    return render(request, 'home/landing.html', {
        'products': products,
        'total_product_count': get_public_products_queryset().count(),
    })


def _products_page_context(request):
    category_slug = (request.GET.get('category') or '').strip()
    search = (request.GET.get('q') or '').strip()
    category = get_filter_category(category_slug)
    queryset = get_public_products_queryset(category=category, search=search)
    page_obj = paginate_products(queryset, request.GET.get('page', 1))

    categories = Category.objects.filter(is_active=True).select_related('parent')
    return {
        'products': page_obj.object_list,
        'page_obj': page_obj,
        'category': category,
        'category_slug': category_slug,
        'search': search,
        'total_count': page_obj.paginator.count,
        'category_groups': build_category_groups(categories),
    }


def product_browse(request):
    context = _products_page_context(request)
    return render(request, 'home/products.html', context)


@require_GET
def product_browse_load(request):
    context = _products_page_context(request)
    html = render_to_string(
        'home/partials/product_cards.html',
        {'products': context['products']},
        request=request,
    )
    page_obj = context['page_obj']
    return JsonResponse({
        'html': html,
        'has_next': page_obj.has_next(),
        'next_page': page_obj.next_page_number() if page_obj.has_next() else None,
    })
