from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.template.loader import render_to_string
from django.views.decorators.http import require_GET

from django.urls import reverse

from .catalog import (
    LANDING_PRODUCT_MAX,
    get_filter_category,
    get_hero_carousel_products,
    get_public_products_queryset,
    paginate_products,
)


def _products_page_context(request, *, max_products=None):
    category_slug = (request.GET.get('category') or '').strip()
    search = (request.GET.get('q') or '').strip()
    category = get_filter_category(category_slug)
    queryset = get_public_products_queryset(category=category, search=search)
    full_count = queryset.count()
    paginate_queryset = queryset[:max_products] if max_products is not None else queryset
    page_obj = paginate_products(paginate_queryset, request.GET.get('page', 1))

    return {
        'products': page_obj.object_list,
        'page_obj': page_obj,
        'category': category,
        'category_slug': category_slug,
        'search': search,
        'total_count': full_count,
        'paginated_count': page_obj.paginator.count,
        'browse_base_url': reverse('home:product_browse'),
        'active_category': category,
    }


def landing(request):
    search = (request.GET.get('q') or '').strip()
    category_slug = (request.GET.get('category') or '').strip()
    category = get_filter_category(category_slug)
    has_filters = bool(search or category)
    max_products = None if has_filters else LANDING_PRODUCT_MAX
    context = _products_page_context(request, max_products=max_products)
    page_obj = context['page_obj']

    return render(request, 'home/landing.html', {
        'products': context['products'],
        'page_obj': page_obj,
        'total_product_count': context['total_count'],
        'landing_max_products': max_products,
        'search': search,
        'category': category,
        'category_slug': category_slug,
        'browse_base_url': reverse('home:landing'),
        'active_category': category,
        'hero_carousel_products': get_hero_carousel_products(),
    })


def product_browse(request):
    context = _products_page_context(request)
    return render(request, 'home/products.html', context)


def privacy_policy(request):
    return render(request, 'home/privacy.html')


@require_GET
def product_browse_load(request):
    is_landing = request.GET.get('landing') == '1'
    max_products = LANDING_PRODUCT_MAX if is_landing else None
    context = _products_page_context(request, max_products=max_products)
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


@require_GET
def robots_txt(request):
    sitemap_url = request.build_absolute_uri(reverse('sitemap'))
    lines = [
        'User-agent: *',
        'Allow: /',
        'Disallow: /admin/',
        'Disallow: /core/',
        'Disallow: /users/',
        'Disallow: /cart/',
        'Disallow: /orders/',
        'Disallow: /pledges/',
        'Disallow: /payments/',
        'Disallow: /addresses/',
        'Disallow: /wishlist/',
        'Disallow: /complaints/',
        'Disallow: /currency/',
        'Disallow: /products/load/',
        f'Sitemap: {sitemap_url}',
    ]
    return HttpResponse('\n'.join(lines) + '\n', content_type='text/plain; charset=utf-8')
