import json
import logging
import os

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.db import transaction

from core.models import Category, Product
from core.group_buy_services import ensure_default_group_buy_for_product
from core.product_attribute import ProductAttribute
from core.product_file import ProductFile
from core.product_import import ProductImportDraft, ProductImportMedia
from core.product_variation import ProductOption, ProductOptionValue, ProductVariation
from core.supplier import Supplier

logger = logging.getLogger(__name__)


def get_category_choices():
    return list(
        Category.objects.filter(is_active=True)
        .order_by('name')
        .values('id', 'name', 'slug')
    )


def get_supplier_choices():
    return list(
        Supplier.objects.filter(is_active=True)
        .order_by('name')
        .values('id', 'name', 'alibaba_url')
    )


def draft_has_supplier_step(draft):
    return bool((draft.draft_data or {}).get('show_supplier_step'))


def draft_has_category_step(draft):
    return bool((draft.draft_data or {}).get('show_category_step'))


def resolve_existing_category_chain(names):
    parent = None
    node = None
    for raw_name in names:
        name = str(raw_name).strip()
        if not name:
            return None
        queryset = Category.objects.filter(is_active=True, name__iexact=name)
        if parent is None:
            queryset = queryset.filter(parent__isnull=True)
        else:
            queryset = queryset.filter(parent=parent)
        node = queryset.first()
        if not node:
            return None
        parent = node
    return node


def build_category_proposal(names):
    parent = None
    segments = []
    for raw_name in names:
        name = str(raw_name).strip()
        if not name:
            continue
        queryset = Category.objects.filter(is_active=True, name__iexact=name)
        if parent is None:
            queryset = queryset.filter(parent__isnull=True)
        else:
            queryset = queryset.filter(parent=parent)
        existing = queryset.first()
        segments.append({
            'name': name,
            'existing_id': existing.pk if existing else None,
        })
        parent = existing
    return segments


def ensure_category_chain(names):
    parent = None
    node = None
    for raw_name in names:
        name = str(raw_name).strip()
        if not name:
            continue
        queryset = Category.objects.filter(is_active=True, name__iexact=name)
        if parent is None:
            queryset = queryset.filter(parent__isnull=True)
        else:
            queryset = queryset.filter(parent=parent)
        node = queryset.first()
        if not node:
            node = Category.objects.create(parent=parent, name=name, is_active=True)
        parent = node
    if node is None:
        raise ValidationError('Enter at least one category name.')
    return node


def get_import_step_order(draft):
    order = [
        ProductImportDraft.Step.BASICS,
        ProductImportDraft.Step.ATTRIBUTES,
        ProductImportDraft.Step.VARIATIONS,
        ProductImportDraft.Step.PRODUCT_MEDIA,
        ProductImportDraft.Step.VARIATION_MEDIA,
        ProductImportDraft.Step.REVIEW,
    ]
    prefix = []
    if draft_has_supplier_step(draft):
        prefix.append(ProductImportDraft.Step.SUPPLIER)
    if draft_has_category_step(draft):
        prefix.append(ProductImportDraft.Step.CATEGORIES)
    return [*prefix, *order]


def update_draft_supplier_data(draft, supplier_data):
    data = dict(draft.draft_data or {})
    data['supplier'] = supplier_data
    draft.draft_data = data
    draft.save(update_fields=['draft_data', 'updated_at'])
    return draft


def skip_supplier_step(draft):
    data = dict(draft.draft_data or {})
    data['show_supplier_step'] = False
    draft.draft_data = data
    draft.save(update_fields=['draft_data', 'updated_at'])
    return draft


def skip_category_step(draft):
    data = dict(draft.draft_data or {})
    data['show_category_step'] = False
    data.pop('category_proposal', None)
    draft.draft_data = data
    draft.save(update_fields=['draft_data', 'updated_at'])
    return draft


def save_categories_from_import(draft, segment_names):
    names = [str(name).strip() for name in segment_names if str(name).strip()]
    if not names:
        raise ValidationError('Enter at least one category name.')

    leaf = ensure_category_chain(names)
    data = dict(draft.draft_data or {})
    data['category_id'] = leaf.pk
    data['show_category_step'] = False
    data.pop('category_proposal', None)
    draft.draft_data = data
    draft.save(update_fields=['draft_data', 'updated_at'])
    return leaf


def get_next_import_step(draft):
    data = draft.draft_data or {}
    if data.get('show_supplier_step'):
        return ProductImportDraft.Step.SUPPLIER
    if data.get('show_category_step'):
        return ProductImportDraft.Step.CATEGORIES
    return ProductImportDraft.Step.BASICS


def save_supplier_from_import(draft, *, name, contact_name='', email='', phone='',
                              wechat_id='', alibaba_url='', country='China', notes=''):
    name = name.strip()
    if not name:
        raise ValidationError('Supplier name is required.')

    existing = Supplier.objects.filter(name__iexact=name).first()
    if not existing and alibaba_url:
        from core.openai_product_import import _normalize_url

        normalized_url = _normalize_url(alibaba_url)
        for supplier in Supplier.objects.filter(is_active=True):
            if _normalize_url(supplier.alibaba_url) == normalized_url:
                existing = supplier
                break

    if existing:
        supplier = existing
        created = False
    else:
        supplier = Supplier.objects.create(
            name=name,
            contact_name=contact_name.strip(),
            email=email.strip(),
            phone=phone.strip(),
            wechat_id=wechat_id.strip(),
            alibaba_url=alibaba_url.strip(),
            country=(country or 'China').strip() or 'China',
            notes=notes.strip(),
            is_active=True,
        )
        created = True

    data = dict(draft.draft_data or {})
    data['supplier_id'] = supplier.pk
    data['show_supplier_step'] = False
    data['supplier'] = {
        'name': supplier.name,
        'contact_name': supplier.contact_name,
        'email': supplier.email,
        'phone': supplier.phone,
        'wechat_id': supplier.wechat_id,
        'alibaba_url': supplier.alibaba_url,
        'country': supplier.country,
        'notes': supplier.notes,
    }
    draft.draft_data = data
    draft.save(update_fields=['draft_data', 'updated_at'])
    return supplier, created


def update_draft_from_basics(draft, *, name, description, category_id, supplier_id,
                             is_special_class, is_active):
    data = dict(draft.draft_data or {})
    data.update({
        'name': name.strip(),
        'description': description.strip(),
        'category_id': category_id,
        'supplier_id': supplier_id or None,
        'is_special_class': bool(is_special_class),
        'is_active': bool(is_active),
    })
    draft.draft_data = data
    draft.save(update_fields=['draft_data', 'updated_at'])
    return draft


def update_draft_attributes(draft, attributes):
    data = dict(draft.draft_data or {})
    data['attributes'] = attributes
    draft.draft_data = data
    draft.save(update_fields=['draft_data', 'updated_at'])
    return draft


def update_draft_variations(draft, *, options, variations):
    data = dict(draft.draft_data or {})
    data['options'] = options
    data['variations'] = variations
    draft.draft_data = data
    draft.save(update_fields=['draft_data', 'updated_at'])
    return draft


def parse_attributes_post(post_data):
    raw = post_data.get('attributes_json', '[]')
    try:
        items = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValidationError('Invalid attributes data.') from exc
    if not isinstance(items, list):
        raise ValidationError('Attributes must be a list.')
    normalized = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        title = str(item.get('title', '')).strip()
        if not title:
            continue
        section = item.get('section') or 'key'
        if section not in {'key', 'packaging'}:
            section = 'key'
        normalized.append({
            'title': title[:100],
            'description': str(item.get('description', '')).strip(),
            'section': section,
            'sort_order': index,
        })
    return normalized


def parse_variations_post(post_data):
    raw = post_data.get('variations_json', '{}')
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValidationError('Invalid variations data.') from exc

    options = payload.get('options') or []
    variations = payload.get('variations') or []
    if not isinstance(options, list) or not isinstance(variations, list):
        raise ValidationError('Invalid options or variations format.')

    clean_options = []
    for opt_index, option in enumerate(options):
        name = str(option.get('name', '')).strip()
        if not name:
            continue
        values = []
        for val_index, value in enumerate(option.get('values') or []):
            label = str(value.get('value') if isinstance(value, dict) else value).strip()
            if label:
                values.append({'value': label[:100], 'sort_order': val_index})
        if values:
            clean_options.append({
                'name': name[:100],
                'sort_order': opt_index,
                'values': values,
            })

    clean_variations = []
    seen_skus = set()
    for index, variation in enumerate(variations):
        sku = str(variation.get('sku', '')).strip() or f'IMPORT-{index + 1}'
        if sku in seen_skus:
            raise ValidationError(f'Duplicate SKU: {sku}')
        seen_skus.add(sku)
        try:
            price = Decimal(str(variation.get('price', '0'))).quantize(Decimal('0.01'))
        except Exception as exc:
            raise ValidationError(f'Invalid price for SKU {sku}.') from exc
        selections = variation.get('option_selections') or {}
        if not isinstance(selections, dict):
            selections = {}
        clean_variations.append({
            'sku': sku[:80],
            'price': str(price),
            'is_active': bool(variation.get('is_active', True)),
            'option_selections': {
                str(k).strip(): str(v).strip()
                for k, v in selections.items()
                if str(k).strip() and str(v).strip()
            },
        })

    return clean_options, clean_variations


def add_product_import_media(draft, upload, *, is_primary=False, sort_order=0):
    if is_primary:
        draft.media_files.filter(variation_sku='').update(is_primary=False)
    return ProductImportMedia.objects.create(
        draft=draft,
        file=upload,
        is_primary=is_primary,
        sort_order=sort_order,
    )


def set_product_import_media_primary(draft, media_id):
    media = draft.media_files.filter(pk=media_id, variation_sku='').first()
    if not media:
        raise ValidationError('Image not found.')
    draft.media_files.filter(variation_sku='').update(is_primary=False)
    media.is_primary = True
    media.save(update_fields=['is_primary'])
    return media


def add_variation_import_media(draft, *, sku, upload, is_primary=False, sort_order=0):
    if is_primary:
        draft.media_files.filter(variation_sku=sku).update(is_primary=False)
    return ProductImportMedia.objects.create(
        draft=draft,
        variation_sku=sku,
        file=upload,
        is_primary=is_primary,
        sort_order=sort_order,
    )


def _product_file_from_import_media(media, *, product, variation=None):
    filename = os.path.basename(media.file.name)
    media.file.open('rb')
    try:
        content = media.file.read()
    finally:
        media.file.close()

    product_file = ProductFile(
        product=product,
        variation=variation,
        is_primary=media.is_primary,
        sort_order=media.sort_order,
    )
    product_file.file.save(filename, ContentFile(content), save=False)
    product_file.save()
    return product_file


def validate_draft_for_publish(draft):
    data = draft.draft_data or {}
    errors = []
    if not str(data.get('name', '')).strip():
        errors.append('Product name is required.')
    if not data.get('category_id'):
        errors.append('Category is required.')
    if not Category.objects.filter(pk=data.get('category_id'), is_active=True).exists():
        errors.append('Selected category is invalid.')

    variations = data.get('variations') or []
    options = data.get('options') or []
    if variations and not options:
        errors.append('Options are required when variations exist.')

    if errors:
        raise ValidationError(errors)
    return data


@transaction.atomic
def publish_product_import_draft(draft):
    if draft.status == ProductImportDraft.Status.COMPLETED:
        raise ValidationError('This import has already been published.')

    data = validate_draft_for_publish(draft)

    product = Product.objects.create(
        category_id=data['category_id'],
        supplier_id=data.get('supplier_id'),
        name=data['name'][:200],
        description=data.get('description', ''),
        is_special_class=bool(data.get('is_special_class')),
        is_active=bool(data.get('is_active', True)),
    )

    for index, attr in enumerate(data.get('attributes') or []):
        ProductAttribute.objects.create(
            product=product,
            title=attr['title'],
            description=attr.get('description', ''),
            section=attr.get('section', 'key'),
            sort_order=attr.get('sort_order', index),
        )

    option_value_map = {}
    for option_data in data.get('options') or []:
        option = ProductOption.objects.create(
            product=product,
            name=option_data['name'],
            sort_order=option_data.get('sort_order', 0),
        )
        for value_data in option_data.get('values') or []:
            option_value = ProductOptionValue.objects.create(
                option=option,
                value=value_data['value'],
                sort_order=value_data.get('sort_order', 0),
            )
            option_value_map[(option.name, option_value.value)] = option_value

    for variation_data in data.get('variations') or []:
        variation = ProductVariation.objects.create(
            product=product,
            sku=variation_data['sku'],
            price=Decimal(variation_data.get('price', '0')),
            is_active=bool(variation_data.get('is_active', True)),
        )
        selected_values = []
        for option_name, value_label in (variation_data.get('option_selections') or {}).items():
            key = (option_name, value_label)
            if key not in option_value_map:
                raise ValidationError(
                    f'Variation {variation_data["sku"]} references unknown option '
                    f'{option_name}: {value_label}.'
                )
            selected_values.append(option_value_map[key])
        if selected_values:
            variation.option_values.set(selected_values)
            variation.validate()

    for media in draft.media_files.filter(variation_sku='').order_by('sort_order', 'id'):
        _product_file_from_import_media(media, product=product)

    for media in draft.media_files.exclude(variation_sku='').order_by('sort_order', 'id'):
        variation = product.variations.filter(sku=media.variation_sku).first()
        if not variation:
            continue
        _product_file_from_import_media(media, product=product, variation=variation)

    draft.product = product
    draft.status = ProductImportDraft.Status.COMPLETED
    draft.current_step = ProductImportDraft.Step.REVIEW
    draft.save(update_fields=['product', 'status', 'current_step', 'updated_at'])

    ensure_default_group_buy_for_product(product)
    return product


def advance_draft_step(draft, step):
    draft.current_step = step
    draft.status = ProductImportDraft.Status.IN_PROGRESS
    draft.save(update_fields=['current_step', 'status', 'updated_at'])


def fetch_listing_images_for_draft(draft, url=None, max_images=15):
    from core.listing_image_fetcher import (
        ListingImageFetchError,
        download_listing_image,
        extract_listing_image_urls,
        fetch_listing_page_html,
    )

    fetch_url = (url or draft.source_url or '').strip()
    if not fetch_url:
        raise ValidationError('Enter an Alibaba product detail URL to fetch images.')

    html = fetch_listing_page_html(fetch_url)
    image_urls = extract_listing_image_urls(html, max_images=max_images)
    if not image_urls:
        raise ValidationError(
            'No product images were found on that listing page. '
            'Try uploading images manually.'
        )

    from core.listing_image_fetcher import build_listing_session

    session = build_listing_session()
    existing_count = draft.media_files.filter(variation_sku='').count()
    has_primary = draft.media_files.filter(variation_sku='', is_primary=True).exists()

    downloaded = 0
    errors = []
    for index, image_url in enumerate(image_urls):
        try:
            content_file = download_listing_image(image_url, session=session)
        except ListingImageFetchError as exc:
            errors.append(str(exc))
            logger.warning('Import image download failed for %s: %s', image_url, exc)
            continue

        ProductImportMedia.objects.create(
            draft=draft,
            file=content_file,
            is_primary=not has_primary and downloaded == 0,
            sort_order=existing_count + downloaded,
        )
        downloaded += 1

    if downloaded == 0:
        detail = errors[0] if errors else 'Unknown error.'
        raise ValidationError(
            'Could not download any images. '
            f'{detail} '
            'Alibaba CDN can be slow from some networks — try again in a moment or upload images manually.'
        )

    if fetch_url != (draft.source_url or ''):
        draft.source_url = fetch_url
        draft.save(update_fields=['source_url', 'updated_at'])

    return {
        'downloaded': downloaded,
        'found': len(image_urls),
        'errors': errors,
    }
