import json
import logging
import re
from decimal import Decimal, InvalidOperation

from django.conf import settings

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a product catalog assistant for a group-buy import marketplace.
Extract structured product data from pasted supplier listing text (Alibaba, 1688, WhatsApp specs, etc.).

Return ONLY valid JSON matching this schema:
{
  "name": "string max 200 chars",
  "description": "string, buyer-friendly product description",
  "category_slug": "exact slug from provided list if product fits an existing category, else empty string",
  "category_path": ["Top-level category", "Optional subcategory", "Leaf category for this product"],
  "supplier": {
    "name": "factory/company name or empty string",
    "contact_name": "sales contact person or empty string",
    "email": "email or empty string",
    "phone": "phone/WhatsApp or empty string",
    "wechat_id": "WeChat ID or empty string",
    "alibaba_url": "Alibaba company/storefront URL or empty string",
    "country": "country or empty string",
    "notes": "extra supplier notes or empty string"
  },
  "is_special_class": false,
  "is_active": true,
  "attributes": [
    {"title": "string", "description": "string", "section": "key|packaging", "sort_order": 0}
  ],
  "options": [
    {
      "name": "Color",
      "sort_order": 0,
      "values": [{"value": "Black", "sort_order": 0}]
    }
  ],
  "variations": [
    {
      "sku": "unique sku string",
      "price": "12.50",
      "is_active": true,
      "option_selections": {"Color": "Black", "Size": "M"}
    }
  ]
}

Rules:
- Prices are USD decimal strings without currency symbols.
- Use section "key" for product specs; "packaging" for weight, dimensions, carton info, MOQ, lead time.
- Infer options (Color, Size, Capacity, etc.) from variation rows when present.
- Generate sensible unique SKUs if missing (e.g. PRODUCT-COLOR-SIZE).
- Include ALL variations found; each must have option_selections covering every option.
- If no variations, return empty options and variations arrays.
- Do not invent image URLs; omit media fields.
- Extract supplier details when present in the paste (company name, contact, email, phone, WeChat, Alibaba store link).
- Put the Alibaba company/store URL in supplier.alibaba_url; product listing URLs belong in source context only.
- category_path must contain 1-4 human-readable category names from most general to most specific; the last name is the product's direct category.
- Use category names from the pasted listing when they are not in the provided slug list.
- Leave category_slug empty when the product category is not represented in the provided slug list.
- Be concise but complete."""

EMPTY_DRAFT = {
    'name': '',
    'description': '',
    'category_id': None,
    'show_category_step': False,
    'category_proposal': None,
    'supplier_id': None,
    'supplier': {},
    'show_supplier_step': False,
    'is_special_class': False,
    'is_active': True,
    'attributes': [],
    'options': [],
    'variations': [],
}


def is_openai_configured():
    return bool(getattr(settings, 'OPENAI_API_KEY', '').strip())


def parse_pasted_product_content(*, raw_paste, categories, suppliers=None, source_url=''):
    if not is_openai_configured():
        raise RuntimeError(
            'OpenAI is not configured. Set OPENAI_API_KEY in your environment.'
        )

    from openai import OpenAI

    category_lines = '\n'.join(
        f'- {item["slug"]}: {item["name"]}' for item in categories[:80]
    ) or '- (no categories yet)'

    user_content = f"""Source URL (optional): {source_url or 'none'}

Available category slugs:
{category_lines}

Pasted supplier content:
---
{raw_paste[:50000]}
---"""

    client = OpenAI(api_key=settings.OPENAI_API_KEY)
    response = client.chat.completions.create(
        model=getattr(settings, 'OPENAI_MODEL', 'gpt-4o-mini'),
        temperature=0.2,
        response_format={'type': 'json_object'},
        messages=[
            {'role': 'system', 'content': SYSTEM_PROMPT},
            {'role': 'user', 'content': user_content},
        ],
    )

    content = response.choices[0].message.content or '{}'
    parsed = json.loads(content)
    return normalize_parsed_draft(parsed, categories=categories, suppliers=suppliers or [])


def normalize_parsed_draft(parsed, *, categories, suppliers):
    draft = {**EMPTY_DRAFT}

    draft['name'] = _clean_str(parsed.get('name'), 200)
    draft['description'] = _clean_str(parsed.get('description'), 5000)
    draft['is_special_class'] = bool(parsed.get('is_special_class', False))
    draft['is_active'] = bool(parsed.get('is_active', True))

    slug = _clean_str(parsed.get('category_slug'), 160).lower()
    category_match = next((c for c in categories if c['slug'] == slug), None)
    if category_match:
        draft['category_id'] = category_match['id']
        draft['show_category_step'] = False
    else:
        _apply_category_path_resolution(draft, parsed)

    supplier_name = _clean_str(parsed.get('supplier_name'), 200)
    supplier_data = _normalize_supplier(parsed.get('supplier') or {})
    if not supplier_data.get('name') and supplier_name:
        supplier_data['name'] = supplier_name
    draft['supplier'] = supplier_data

    supplier_match = _match_existing_supplier(supplier_data, suppliers)
    if supplier_match:
        draft['supplier_id'] = supplier_match['id']
        draft['show_supplier_step'] = False
    elif supplier_data.get('name'):
        draft['show_supplier_step'] = True
    else:
        draft['show_supplier_step'] = False

    draft['attributes'] = _normalize_attributes(parsed.get('attributes') or [])
    draft['options'] = _normalize_options(parsed.get('options') or [])
    draft['variations'] = _normalize_variations(
        parsed.get('variations') or [],
        draft['options'],
    )
    return draft


def _normalize_category_names(parsed):
    path = parsed.get('category_path') or []
    if isinstance(path, list):
        names = []
        seen = set()
        for item in path:
            name = _clean_str(item, 100)
            key = name.lower()
            if name and key not in seen:
                names.append(name)
                seen.add(key)
        if names:
            return names

    slug = _clean_str(parsed.get('category_slug'), 160)
    if slug:
        return [slug.replace('-', ' ').title()]
    return []


def _apply_category_path_resolution(draft, parsed):
    from core.product_import_services import (
        build_category_proposal,
        resolve_existing_category_chain,
    )

    names = _normalize_category_names(parsed)
    if not names:
        draft['show_category_step'] = False
        return

    existing_leaf = resolve_existing_category_chain(names)
    if existing_leaf:
        draft['category_id'] = existing_leaf.pk
        draft['show_category_step'] = False
        return

    draft['show_category_step'] = True
    draft['category_proposal'] = {
        'segments': build_category_proposal(names),
    }


def _normalize_supplier(item):
    if not isinstance(item, dict):
        item = {}
    return {
        'name': _clean_str(item.get('name'), 200),
        'contact_name': _clean_str(item.get('contact_name'), 150),
        'email': _clean_str(item.get('email'), 254),
        'phone': _clean_str(item.get('phone'), 50),
        'wechat_id': _clean_str(item.get('wechat_id'), 100),
        'alibaba_url': _clean_str(item.get('alibaba_url'), 200),
        'country': _clean_str(item.get('country'), 100) or 'China',
        'notes': _clean_str(item.get('notes'), 5000),
    }


def _match_existing_supplier(supplier_data, suppliers):
    if not supplier_data.get('name') or not suppliers:
        return None

    name = supplier_data['name'].lower()
    alibaba_url = _normalize_url(supplier_data.get('alibaba_url'))

    for supplier in suppliers:
        if supplier['name'].lower() == name:
            return supplier
        existing_url = _normalize_url(supplier.get('alibaba_url'))
        if alibaba_url and existing_url and alibaba_url == existing_url:
            return supplier
    return None


def _normalize_url(url):
    if not url:
        return ''
    cleaned = str(url).strip().lower().rstrip('/')
    if cleaned.startswith('http://'):
        cleaned = 'https://' + cleaned[7:]
    return cleaned


def _normalize_attributes(items):
    attributes = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        title = _clean_str(item.get('title'), 100)
        if not title:
            continue
        section = item.get('section') or 'key'
        if section not in {'key', 'packaging'}:
            section = 'key'
        attributes.append({
            'title': title,
            'description': _clean_str(item.get('description'), 2000),
            'section': section,
            'sort_order': _safe_int(item.get('sort_order'), index),
        })
    return attributes


def _normalize_options(items):
    options = []
    for opt_index, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        name = _clean_str(item.get('name'), 100)
        if not name:
            continue
        values = []
        for val_index, value_item in enumerate(item.get('values') or []):
            if isinstance(value_item, dict):
                value = _clean_str(value_item.get('value'), 100)
                sort_order = _safe_int(value_item.get('sort_order'), val_index)
            else:
                value = _clean_str(value_item, 100)
                sort_order = val_index
            if value:
                values.append({'value': value, 'sort_order': sort_order})
        if values:
            options.append({
                'name': name,
                'sort_order': _safe_int(item.get('sort_order'), opt_index),
                'values': values,
            })
    return options


def _normalize_variations(items, options):
    variations = []
    seen_skus = set()
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        sku = _clean_str(item.get('sku'), 80) or f'IMPORT-{index + 1}'
        base_sku = sku
        counter = 1
        while sku in seen_skus:
            sku = f'{base_sku}-{counter}'
            counter += 1
        seen_skus.add(sku)

        price = _normalize_price(item.get('price'))
        selections = item.get('option_selections') or {}
        if not isinstance(selections, dict):
            selections = {}

        variations.append({
            'sku': sku,
            'price': str(price),
            'is_active': bool(item.get('is_active', True)),
            'option_selections': {
                _clean_str(k, 100): _clean_str(v, 100)
                for k, v in selections.items()
                if _clean_str(k, 100) and _clean_str(v, 100)
            },
        })

    if variations and not options:
        options = _infer_options_from_variations(variations)
    return variations


def _infer_options_from_variations(variations):
    option_map = {}
    for variation in variations:
        for option_name, value in variation.get('option_selections', {}).items():
            option_map.setdefault(option_name, set()).add(value)

    options = []
    for index, (name, values) in enumerate(option_map.items()):
        options.append({
            'name': name,
            'sort_order': index,
            'values': [
                {'value': value, 'sort_order': val_index}
                for val_index, value in enumerate(sorted(values))
            ],
        })
    return options


def _normalize_price(value):
    if value is None or value == '':
        return Decimal('0.00')
    if isinstance(value, (int, float, Decimal)):
        return Decimal(str(value)).quantize(Decimal('0.01'))
    cleaned = re.sub(r'[^\d.]', '', str(value))
    try:
        return Decimal(cleaned or '0').quantize(Decimal('0.01'))
    except InvalidOperation:
        return Decimal('0.00')


def _clean_str(value, max_length):
    if value is None:
        return ''
    return str(value).strip()[:max_length]


def _safe_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
