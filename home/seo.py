"""SEO helpers for public marketing pages."""

import json
from urllib.parse import urlencode

from django.conf import settings
from django.urls import reverse
from django.utils.html import strip_tags
from django.utils.safestring import mark_safe


def public_site_url(path=''):
    """Canonical public origin (production domain), not the request host."""
    protocol = (getattr(settings, 'SITE_PROTOCOL', 'https') or 'https').strip().rstrip(':')
    domain = (getattr(settings, 'SITE_DOMAIN', '') or '').strip().rstrip('/')
    if not domain:
        return path or '/'
    if not path:
        return f'{protocol}://{domain}/'
    if not path.startswith('/'):
        path = f'/{path}'
    return f'{protocol}://{domain}{path}'


def _clean_description(text, *, max_length=155, fallback=''):
    raw = strip_tags(text or '').strip()
    if not raw:
        return fallback
    if len(raw) <= max_length:
        return raw
    return f'{raw[: max_length - 1].rstrip()}…'


def json_ld_script(data):
    return mark_safe(
        f'<script type="application/ld+json">{json.dumps(data, ensure_ascii=False)}</script>'
    )


def organization_and_website_json_ld():
    site_url = public_site_url('/')
    browse_url = public_site_url(reverse('home:product_browse'))
    site_name = getattr(settings, 'SITE_NAME', 'Kenya Imports')
    contact_phone = getattr(settings, 'SITE_CONTACT_PHONE', '').strip()
    organization = {
        '@type': 'Organization',
        '@id': f'{site_url}#organization',
        'name': site_name,
        'url': site_url,
        'description': (
            'Group-buying platform for factory-direct imports from China to Kenya.'
        ),
    }
    if contact_phone:
        organization['telephone'] = contact_phone
    return {
        '@context': 'https://schema.org',
        '@graph': [
            organization,
            {
                '@type': 'WebSite',
                '@id': f'{site_url}#website',
                'url': site_url,
                'name': site_name,
                'publisher': {'@id': f'{site_url}#organization'},
                'potentialAction': {
                    '@type': 'SearchAction',
                    'target': {
                        '@type': 'EntryPoint',
                        'urlTemplate': f'{browse_url}?q={{search_term_string}}',
                    },
                    'query-input': 'required name=search_term_string',
                },
            },
        ],
    }


def landing_seo(has_filters, category, search):
    browse = browse_page_seo(category, search, page_number=1)
    if has_filters:
        return {
            'seo_robots': 'noindex, follow',
            'seo_canonical_url': browse['seo_canonical_url'],
            'seo_title': browse['seo_title'],
            'seo_description': browse['seo_description'],
            'seo_og_title': browse['seo_og_title'],
            'seo_og_description': browse['seo_og_description'],
        }
    site_name = getattr(settings, 'SITE_NAME', 'Kenya Imports')
    description = (
        'Join group buys to meet factory MOQ and import products from China at wholesale prices. '
        'Save on shipping with Kenya Imports.'
    )
    return {
        'seo_robots': 'index, follow, max-image-preview:large',
        'seo_canonical_url': public_site_url('/'),
        'seo_title': f'{site_name} — Buy Together, Save More on China Imports',
        'seo_description': description,
        'seo_og_title': f'{site_name} — Buy Together, Save More',
        'seo_og_description': description,
    }


def browse_page_seo(category, search, page_number=1):
    site_name = getattr(settings, 'SITE_NAME', 'Kenya Imports')
    params = {}
    if category:
        params['category'] = category.slug
    if search:
        params['q'] = search
    if page_number and page_number > 1:
        params['page'] = str(page_number)

    query = f'?{urlencode(params)}' if params else ''
    canonical = public_site_url(f"{reverse('home:product_browse')}{query}")

    if search:
        title = f'Search: {search} — {site_name}'
        description = (
            f'Factory-direct group buy products matching “{search}”. '
            'Join others in Kenya to hit MOQ and unlock wholesale import pricing.'
        )
    elif category:
        cat_desc = _clean_description(
            getattr(category, 'description', ''),
            fallback=f'Shop {category.name} products available for group buy import to Kenya.',
        )
        title = f'{category.name} Group Buys — Import from China | {site_name}'
        description = cat_desc
    else:
        title = f'Browse Group Buy Products — Factory Direct Imports | {site_name}'
        description = (
            'Browse factory-direct products available for group buy import to Kenya. '
            'Filter by category and join others to hit MOQ and save on shipping.'
        )

    robots = 'index, follow, max-image-preview:large'
    if page_number and page_number > 1:
        robots = 'noindex, follow'

    return {
        'seo_robots': robots,
        'seo_canonical_url': canonical,
        'seo_title': title,
        'seo_description': description,
        'seo_og_title': title,
        'seo_og_description': description,
    }


def privacy_page_seo():
    site_name = getattr(settings, 'SITE_NAME', 'Kenya Imports')
    description = (
        'How Kenya Imports collects and uses your personal information. '
        'We do not sell or share your data with third parties.'
    )
    return {
        'seo_robots': 'index, follow',
        'seo_canonical_url': public_site_url(reverse('home:privacy_policy')),
        'seo_title': f'Privacy Policy — {site_name}',
        'seo_description': description,
        'seo_og_title': f'Privacy Policy — {site_name}',
        'seo_og_description': description,
    }


def privacy_webpage_json_ld():
    url = public_site_url(reverse('home:privacy_policy'))
    site_name = getattr(settings, 'SITE_NAME', 'Kenya Imports')
    return {
        '@context': 'https://schema.org',
        '@type': 'WebPage',
        'name': f'Privacy Policy — {site_name}',
        'url': url,
        'isPartOf': {'@id': public_site_url('/#website')},
        'about': {'@id': public_site_url('/#organization')},
    }


def product_page_seo(product, price_min=None):
    site_name = getattr(settings, 'SITE_NAME', 'Kenya Imports')
    description = _clean_description(
        product.description,
        fallback=(
            f'Join a group buy for {product.name}. '
            'Meet MOQ with other buyers in Kenya and import at wholesale pricing.'
        ),
    )
    title = f'{product.name} — Group Buy Import | {site_name}'
    canonical = public_site_url(product.get_absolute_url())
    return {
        'seo_robots': 'index, follow, max-image-preview:large',
        'seo_canonical_url': canonical,
        'seo_title': title,
        'seo_description': description,
        'seo_og_title': title,
        'seo_og_description': description,
        'seo_og_image': _product_og_image(product),
    }


def _product_og_image(product):
    hero = product.primary_image
    if not hero or not hero.is_image:
        return ''
    return public_site_url(hero.file.url)


def browse_item_list_json_ld(products):
    elements = []
    for index, product in enumerate(products[:24], start=1):
        elements.append({
            '@type': 'ListItem',
            'position': index,
            'url': public_site_url(product.get_absolute_url()),
            'name': product.name,
        })
    if not elements:
        return {}
    return {
        '@context': 'https://schema.org',
        '@type': 'ItemList',
        'itemListElement': elements,
    }


def product_structured_data(product, group_buy=None, price_min=None):
    site_name = getattr(settings, 'SITE_NAME', 'Kenya Imports')
    url = public_site_url(product.get_absolute_url())
    data = {
        '@context': 'https://schema.org',
        '@type': 'Product',
        'name': product.name,
        'description': _clean_description(product.description, fallback=product.name, max_length=500),
        'sku': product.slug,
        'url': url,
        'brand': {
            '@type': 'Brand',
            'name': site_name,
        },
    }
    image = _product_og_image(product)
    if image:
        data['image'] = [image]

    if price_min is not None:
        availability = 'https://schema.org/InStock'
        if group_buy and not group_buy.is_joinable:
            availability = 'https://schema.org/PreOrder'
        data['offers'] = {
            '@type': 'Offer',
            'url': url,
            'priceCurrency': 'USD',
            'price': str(price_min),
            'availability': availability,
            'seller': {
                '@type': 'Organization',
                'name': site_name,
            },
        }

    return data


def product_breadcrumb_json_ld(product):
    items = [
        ('Home', public_site_url('/')),
        ('Products', public_site_url(reverse('home:product_browse'))),
        (
            product.category.name,
            public_site_url(
                f"{reverse('home:product_browse')}?category={product.category.slug}",
            ),
        ),
        (product.name, public_site_url(product.get_absolute_url())),
    ]
    return {
        '@context': 'https://schema.org',
        '@type': 'BreadcrumbList',
        'itemListElement': [
            {
                '@type': 'ListItem',
                'position': index + 1,
                'name': name,
                'item': item_url,
            }
            for index, (name, item_url) in enumerate(items)
        ],
    }
