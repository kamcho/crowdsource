from datetime import timedelta

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.db import transaction
from django.db.models import Count, Prefetch, Q, Sum, Value
from django.db.models.functions import Coalesce
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils import timezone

from .admin_dashboard import get_admin_dashboard_context
from .category_link_services import (
    build_go_together_overview,
    get_go_together_category_ids,
    set_go_together_categories,
)
from .category_utils import build_category_tree
from .decorators import admin_required, staff_required
from .forms import (
    CategoryForm,
    CategoryGoTogetherForm,
    FulfillmentForm,
    GroupBuyForm,
    ImportBatchCreateForm,
    ImportBatchForm,
    ImportBatchAdditionalCostFormSet,
    ImportShipmentForm,
    ImportShipmentAddProductForm,
    ShipmentSharedCostSplitForm,
    ProductAttributeForm,
    RefundCreateForm,
    SupplierForm,
    ComplaintStaffReplyForm,
    get_pledge_formset,
    save_variation_pledges_from_post,
    get_variation_file_formset,
    ProductFileFormSet,
    ProductForm,
    ProductOptionForm,
    ProductOptionValueForm,
    ProductVariationForm,
)
from .group_buy import GroupBuy, GroupBuyEntry
from .group_buy_services import ensure_default_group_buy_for_product
from .fulfillment import Fulfillment
from .fulfillment_services import create_fulfillment_for_order
from .import_batch import ImportBatch
from .import_cost import ImportShipment
from .import_cost_services import (
    apply_shipment_shared_cost_split,
    build_batch_cost_summary,
    build_shipment_analytics,
)
from .import_services import (
    create_import_batch,
    group_buys_available_for_shipment,
    link_group_buy_to_shipment,
    unlink_import_batch_from_shipment,
)
from .import_shipment_picker import (
    filter_group_buys_for_search,
    group_buy_picker_items,
)
from .import_shipment_parse import (
    apply_parsed_costing_to_batches,
    match_parsed_lines_to_batches,
    parse_supplier_order_paste,
    serialize_supplier_paste_rows,
)
from .openai_product_import import is_openai_configured
from .models import Category, Product
from .supplier import Supplier
from .order import Order
from .pricing import build_price_tiers, product_variation_price_range
from .wishlist_services import is_wishlisted
from .shipping_services import build_shipping_calculator_context
from .refund import MPESA_REVERSAL_REQUIRED_IN_PRODUCTION, Refund
from .refund_services import cancel_refund, complete_refund, create_refund
from .complaint import Complaint
from .complaint_services import add_complaint_message, update_complaint_status
from .product_attribute import ProductAttribute
from .product_file import ProductFile
from .product_variation import ProductOption, ProductOptionValue, ProductVariation


def get_related_products(product, limit=6):
    active_group_buys = GroupBuy.objects.filter(
        status__in=[GroupBuy.Status.OPEN, GroupBuy.Status.MOQ_REACHED],
    ).prefetch_related('entries')

    base_qs = Product.objects.filter(
        is_active=True,
        category__is_active=True,
    ).exclude(pk=product.pk).select_related(
        'category', 'category__parent',
    ).prefetch_related(
        'files', 'variations',
        Prefetch('group_buys', queryset=active_group_buys, to_attr='active_group_buys_list'),
    )

    related = list(base_qs.filter(category=product.category)[:limit])
    if len(related) >= limit:
        return related

    seen_ids = {product.pk, *(item.pk for item in related)}
    remaining = limit - len(related)

    go_together_ids = get_go_together_category_ids(product.category)
    if go_together_ids and remaining:
        go_together_products = list(
            base_qs.filter(category_id__in=go_together_ids)
            .exclude(pk__in=seen_ids)[:remaining]
        )
        related.extend(go_together_products)
        seen_ids.update(item.pk for item in go_together_products)
        remaining = limit - len(related)

    if product.category.parent_id:
        siblings = list(
            base_qs.filter(category__parent=product.category.parent)
            .exclude(pk__in=seen_ids)[:remaining]
        )
        related.extend(siblings)
        seen_ids.update(item.pk for item in siblings)
        remaining = limit - len(related)

    if remaining:
        related.extend(list(base_qs.exclude(pk__in=seen_ids)[:remaining]))

    return related


@staff_required
def admin_dashboard(request):
    full_admin_access = request.user.is_admin_user
    context = get_admin_dashboard_context(full_admin_access=full_admin_access)
    context['full_admin_access'] = full_admin_access
    context['dashboard_title'] = 'Admin dashboard' if full_admin_access else 'Ops dashboard'
    context['dashboard_subtitle'] = (
        'Platform overview, analytics, and management shortcuts.'
        if full_admin_access
        else 'Group buys, imports, and delivery operations.'
    )
    return render(request, 'core/dashboard/index.html', context)


def _serialize_media_file(product_file):
    return {
        'url': product_file.file.url,
        'type': product_file.media_type,
        'caption': product_file.caption,
    }


def _build_product_detail_context(product):
    product_media = [
        _serialize_media_file(product_file)
        for product_file in product.product_files.all()
    ]
    variation_media = {}
    variation_attributes = {}
    for variation in product.variations.filter(is_active=True).prefetch_related('files', 'attributes'):
        if variation.files.exists():
            variation_media[str(variation.pk)] = [
                _serialize_media_file(product_file)
                for product_file in variation.files.all()
            ]
        attrs = list(variation.variation_attributes)
        if attrs:
            variation_attributes[str(variation.pk)] = [
                {'title': attribute.title, 'description': attribute.description}
                for attribute in attrs
            ]

    product_attributes = [
        {'title': attribute.title, 'description': attribute.description}
        for attribute in product.product_attributes
    ]
    option_value_images = {}
    for variation in product.variations.filter(is_active=True).prefetch_related(
        'option_values',
        'files',
    ):
        image = variation.primary_image
        if not image:
            continue
        image_url = image.file.url
        for option_value in variation.option_values.all():
            option_value_images.setdefault(str(option_value.pk), image_url)

    return {
        'product_media': product_media,
        'variation_media': variation_media,
        'product_attributes': product_attributes,
        'variation_attributes': variation_attributes,
        'option_value_images': option_value_images,
    }


def _attribute_table_rows(attributes):
    """Pair attributes into Alibaba-style table rows (label/value × 2 per row)."""
    items = list(attributes)
    if not items:
        return []
    rows = []
    for index in range(0, len(items), 2):
        pair = items[index:index + 2]
        while len(pair) < 2:
            pair.append(None)
        rows.append(pair)
    return rows


ATTRIBUTE_SECTION_HEADINGS = {
    ProductAttribute.Section.KEY: 'Key attributes',
    ProductAttribute.Section.PACKAGING: 'Packaging and delivery',
}

ATTRIBUTE_SECTION_ORDER = (
    ProductAttribute.Section.KEY,
    ProductAttribute.Section.PACKAGING,
)


def _append_catalog_summary_rows(rows, product, group_buy=None):
    """Add variation and option summaries when missing from stored attributes."""
    titles = {row['title'].lower() for row in rows}
    active_variations = product.active_variations
    variation_count = (
        active_variations.count()
        if hasattr(active_variations, 'count')
        else len(active_variations)
    )
    if variation_count and 'variations' not in titles:
        rows.append({
            'title': 'Variations',
            'description': f'{variation_count} SKU{"s" if variation_count != 1 else ""} available',
        })
    for option in product.options.all():
        if option.name.lower() in titles:
            continue
        values = ', '.join(value.value for value in option.values.all())
        if values:
            rows.append({
                'title': option.name,
                'description': values,
            })
    if group_buy and 'moq' not in titles:
        rows.append({
            'title': 'MOQ',
            'description': f'{group_buy.moq} units',
        })
    return rows


def _build_attribute_sections(product, group_buy=None):
    """Group product-level attributes into Alibaba-style sections."""
    stored = list(product.product_attributes)
    if stored:
        grouped = {}
        section_order = []
        for attribute in stored:
            section = attribute.section or ProductAttribute.Section.KEY
            if section not in grouped:
                grouped[section] = []
                section_order.append(section)
            grouped[section].append({
                'title': attribute.title,
                'description': attribute.description,
            })
        key_section = ProductAttribute.Section.KEY
        if key_section in grouped:
            grouped[key_section] = _append_catalog_summary_rows(
                grouped[key_section],
                product,
                group_buy,
            )
        return [
            {
                'heading': ATTRIBUTE_SECTION_HEADINGS.get(
                    section,
                    section.replace('_', ' ').title(),
                ),
                'rows': _attribute_table_rows(grouped[section]),
            }
            for section in sorted(
                section_order,
                key=lambda value: (
                    ATTRIBUTE_SECTION_ORDER.index(value)
                    if value in ATTRIBUTE_SECTION_ORDER
                    else len(ATTRIBUTE_SECTION_ORDER)
                ),
            )
        ]

    fallback = _build_display_attributes(product, group_buy)
    return [{
        'heading': 'Key attributes',
        'rows': _attribute_table_rows(fallback),
    }]


def _build_display_attributes(product, group_buy=None):
    """Product-level attributes for the middle-column specs grid."""
    stored = list(product.product_attributes)
    if stored:
        return [
            {'title': attribute.title, 'description': attribute.description}
            for attribute in stored
        ]

    rows = [
        {
            'title': 'Category',
            'description': product.category.get_breadcrumb(),
        },
    ]

    active_variations = product.active_variations
    variation_count = active_variations.count() if hasattr(active_variations, 'count') else len(active_variations)
    if variation_count:
        rows.append({
            'title': 'Variations',
            'description': f'{variation_count} SKU{"s" if variation_count != 1 else ""} available',
        })

    for option in product.options.all():
        values = ', '.join(value.value for value in option.values.all())
        if values:
            rows.append({
                'title': option.name,
                'description': values,
            })

    if group_buy:
        rows.append({
            'title': 'MOQ',
            'description': f'{group_buy.moq} units',
        })
        rows.append({
            'title': 'Group buy closes',
            'description': group_buy.closes_at.strftime('%b %d, %Y'),
        })

    if product.description:
        excerpt = product.description.strip().replace('\n', ' ')
        if len(excerpt) > 120:
            excerpt = f'{excerpt[:117]}…'
        rows.append({
            'title': 'Overview',
            'description': excerpt,
        })

    return rows


def product_detail(request, slug):
    product = get_object_or_404(
        Product.objects.select_related('category__parent')
        .prefetch_related(
            'files',
            'attributes',
            'options__values',
            'variations__option_values__option',
            'variations__files',
            'variations__attributes',
            'group_buys__entries__user',
        ),
        slug=slug,
        is_active=True,
        category__is_active=True,
    )
    group_buy = product.active_group_buy
    if not group_buy:
        group_buy = ensure_default_group_buy_for_product(product)

    user_entries = []
    pledge_formset = None

    if group_buy:
        if request.user.is_authenticated:
            user_entries = list(
                group_buy.entries.filter(user=request.user).select_related('variation')
            )

        if request.method == 'POST' and 'join_group_buy' in request.POST:
            if not request.user.is_authenticated:
                return redirect(f'{reverse("users:signin")}?next={request.path}')

            if product.active_variations.exists():
                try:
                    with transaction.atomic():
                        save_variation_pledges_from_post(group_buy, request.user, request.POST)
                    messages.success(request, 'Your booking has been saved.')
                    return redirect('pledge_list')
                except ValidationError as exc:
                    messages.error(request, exc.messages[0] if exc.messages else str(exc))
            else:
                pledge_formset = get_pledge_formset(group_buy, request.user, data=request.POST)
                if pledge_formset.is_valid():
                    with transaction.atomic():
                        pledge_formset.save()
                    messages.success(request, 'Your booking has been saved.')
                    return redirect('pledge_list')
                messages.error(request, 'Please correct the errors below.')
        elif group_buy.is_joinable and request.user.is_authenticated:
            pledge_formset = get_pledge_formset(group_buy, request.user)
        elif request.user.is_authenticated and user_entries:
            pledge_formset = get_pledge_formset(group_buy, request.user)

    pledged_by_variation = {
        str(entry.variation_id): entry.quantity
        for entry in user_entries if entry.variation_id
    }
    pledged_quantities = pledged_by_variation.copy()

    related_products = get_related_products(product)
    detail_context = _build_product_detail_context(product)
    price_min, price_max = product_variation_price_range(product)
    if price_min is None and group_buy:
        price_min = price_max = group_buy.unit_price

    price_tiers = build_price_tiers(product, group_buy)
    pledger_count = group_buy.entries.values('user').distinct().count() if group_buy else 0
    display_attributes = _build_display_attributes(product, group_buy)
    attribute_sections = _build_attribute_sections(product, group_buy)
    shipping_calculator = build_shipping_calculator_context(product)

    if request.user.is_authenticated:
        from core.preference_services import record_product_view

        record_product_view(request.user, product)

    return render(request, 'core/products/detail.html', {
        'product': product,
        'group_buy': group_buy,
        'user_entries': user_entries,
        'pledge_formset': pledge_formset,
        'user_pledged_total': group_buy.user_pledged_units(request.user) if group_buy and request.user.is_authenticated else 0,
        'pledged_by_variation': pledged_by_variation,
        'pledged_quantities': pledged_quantities,
        'related_products': related_products,
        'price_min': price_min,
        'price_max': price_max,
        'price_tiers': price_tiers,
        'pledger_count': pledger_count,
        'display_attributes': display_attributes,
        'attribute_sections': attribute_sections,
        'is_wishlisted': is_wishlisted(request.user, product) if request.user.is_authenticated else False,
        **shipping_calculator,
        **detail_context,
    })


@admin_required
def category_list(request):
    categories = list(Category.objects.select_related('parent').all())
    category_rows = build_category_tree(categories)
    return render(request, 'core/categories/list.html', {
        'category_rows': category_rows,
        'total_categories': len(categories),
    })


@admin_required
def category_create(request):
    parent = None
    parent_id = request.GET.get('parent')
    if parent_id:
        parent = get_object_or_404(Category, pk=parent_id)

    if request.method == 'POST':
        form = CategoryForm(request.POST)
        if form.is_valid():
            category = form.save()
            messages.success(request, f'Category "{category.get_breadcrumb()}" created successfully.')
            return redirect('core:category_list')
        messages.error(request, 'Please correct the errors below.')
    else:
        form = CategoryForm(initial={'parent': parent} if parent else None)

    return render(request, 'core/categories/create.html', {
        'form': form,
        'parent': parent,
    })


@admin_required
def category_go_together_list(request):
    categories = list(Category.objects.select_related('parent').filter(is_active=True))
    category_rows = build_category_tree(categories)
    overview_rows = build_go_together_overview(category_rows)
    linked_pair_count = sum(row['link_count'] for row in overview_rows) // 2
    return render(request, 'core/categories/go_together_list.html', {
        'overview_rows': overview_rows,
        'linked_pair_count': linked_pair_count,
        'total_categories': len(categories),
    })


@admin_required
def category_go_together_manage(request, category_id):
    category = get_object_or_404(Category, pk=category_id)
    selected_ids = get_go_together_category_ids(category)

    if request.method == 'POST':
        form = CategoryGoTogetherForm(
            request.POST,
            source_category=category,
        )
        if form.is_valid():
            set_go_together_categories(
                category,
                form.cleaned_data['linked_categories'].values_list('pk', flat=True),
            )
            messages.success(
                request,
                f'Go-together links updated for "{category.get_breadcrumb()}".',
            )
            return redirect('core:category_go_together_manage', category_id=category.pk)
        messages.error(request, 'Please correct the errors below.')
    else:
        form = CategoryGoTogetherForm(
            initial={'linked_categories': selected_ids},
            source_category=category,
        )

    categories = list(Category.objects.filter(is_active=True).select_related('parent'))
    category_tree = build_category_tree(categories)

    return render(request, 'core/categories/go_together_manage.html', {
        'category': category,
        'form': form,
        'category_tree': category_tree,
        'selected_category_ids': set(selected_ids),
    })


@admin_required
def product_list(request):
    products = Product.objects.select_related('category', 'supplier').prefetch_related(
        'files', 'options', 'variations'
    ).all()
    return render(request, 'core/products/list.html', {
        'products': products,
    })


@admin_required
def product_create(request):
    if request.method == 'POST':
        form = ProductForm(request.POST)
        formset = ProductFileFormSet(request.POST, request.FILES)
        if form.is_valid() and formset.is_valid():
            with transaction.atomic():
                product = form.save()
                files = formset.save(commit=False)
                for product_file in files:
                    product_file.product = product
                    product_file.save()
                for deleted in formset.deleted_objects:
                    deleted.delete()
            messages.success(request, f'Product "{product.name}" created successfully.')
            return redirect('core:product_list')
        messages.error(request, 'Please correct the errors below.')
    else:
        form = ProductForm()
        formset = ProductFileFormSet()

    return render(request, 'core/products/create.html', {
        'form': form,
        'formset': formset,
    })


@admin_required
def product_option_list(request, product_id):
    product = get_object_or_404(Product.objects.prefetch_related('options__values'), pk=product_id)
    return render(request, 'core/product_options/list.html', {
        'product': product,
        'options': product.options.all(),
    })


@admin_required
def product_option_create(request, product_id):
    product = get_object_or_404(Product, pk=product_id)

    if request.method == 'POST':
        form = ProductOptionForm(request.POST, product=product)
        if form.is_valid():
            option = form.save()
            messages.success(request, f'Option "{option.name}" added to {product.name}.')
            return redirect('core:product_option_list', product_id=product.pk)
        messages.error(request, 'Please correct the errors below.')
    else:
        form = ProductOptionForm(product=product)

    return render(request, 'core/product_options/create.html', {
        'form': form,
        'product': product,
    })


@admin_required
def product_option_value_list(request, option_id):
    option = get_object_or_404(
        ProductOption.objects.select_related('product').prefetch_related('values'),
        pk=option_id,
    )
    return render(request, 'core/product_option_values/list.html', {
        'option': option,
        'product': option.product,
        'values': option.values.all(),
    })


@admin_required
def product_option_value_create(request, option_id):
    option = get_object_or_404(ProductOption.objects.select_related('product'), pk=option_id)

    if request.method == 'POST':
        form = ProductOptionValueForm(request.POST, option=option)
        if form.is_valid():
            option_value = form.save()
            messages.success(
                request,
                f'Value "{option_value.value}" added to {option.name}.',
            )
            return redirect('core:product_option_value_list', option_id=option.pk)
        messages.error(request, 'Please correct the errors below.')
    else:
        form = ProductOptionValueForm(option=option)

    return render(request, 'core/product_option_values/create.html', {
        'form': form,
        'option': option,
        'product': option.product,
    })


@admin_required
def product_variation_list(request, product_id):
    product = get_object_or_404(
        Product.objects.prefetch_related('options__values', 'variations__option_values__option', 'variations__files'),
        pk=product_id,
    )
    return render(request, 'core/product_variations/list.html', {
        'product': product,
        'variations': product.variations.all(),
    })


@admin_required
def product_variation_create(request, product_id):
    product = get_object_or_404(
        Product.objects.prefetch_related('options__values'),
        pk=product_id,
    )

    if not product.options.exists():
        messages.warning(
            request,
            f'Add at least one option to "{product.name}" before creating variations.',
        )
        return redirect('core:product_option_list', product_id=product.pk)

    for option in product.options.all():
        if not option.values.exists():
            messages.warning(
                request,
                f'Add values for "{option.name}" before creating variations.',
            )
            return redirect('core:product_option_value_list', option_id=option.pk)

    if request.method == 'POST':
        form = ProductVariationForm(request.POST, product=product)
        if form.is_valid():
            try:
                with transaction.atomic():
                    form.save()
            except ValidationError as exc:
                if hasattr(exc, 'message_dict'):
                    for field, errors in exc.message_dict.items():
                        for error in errors:
                            form.add_error(None, error)
                else:
                    form.add_error(None, exc.messages[0] if exc.messages else str(exc))
                messages.error(request, 'Please correct the errors below.')
            else:
                messages.success(request, f'Variation "{form.instance.sku}" created successfully.')
                return redirect('core:product_variation_list', product_id=product.pk)
        else:
            messages.error(request, 'Please correct the errors below.')
    else:
        form = ProductVariationForm(product=product)

    option_fields = [
        (option, form[f'option_{option.pk}'])
        for option in product.options.all()
    ]

    return render(request, 'core/product_variations/create.html', {
        'form': form,
        'product': product,
        'option_fields': option_fields,
    })


@admin_required
def product_attribute_list(request, product_id):
    product = get_object_or_404(
        Product.objects.prefetch_related('attributes__variation'),
        pk=product_id,
    )
    return render(request, 'core/product_attributes/list.html', {
        'product': product,
        'attributes': product.attributes.all(),
    })


@admin_required
def product_attribute_create(request, product_id):
    product = get_object_or_404(Product, pk=product_id)
    next_url = request.GET.get('next') or request.POST.get('next')

    if request.method == 'POST':
        form = ProductAttributeForm(request.POST, product=product)
        if form.is_valid():
            attribute = form.save()
            messages.success(request, f'Attribute "{attribute.title}" added.')
            if next_url and url_has_allowed_host_and_scheme(
                next_url,
                allowed_hosts={request.get_host()},
                require_https=request.is_secure(),
            ):
                return redirect(next_url)
            return redirect('core:product_attribute_list', product_id=product.pk)
        messages.error(request, 'Please correct the errors below.')
    else:
        initial = {}
        title = (request.GET.get('title') or '').strip()
        description = (request.GET.get('description') or '').strip()
        section = (request.GET.get('section') or '').strip()
        if title:
            initial['title'] = title
        if description:
            initial['description'] = description
        if section in ProductAttribute.Section.values:
            initial['section'] = section
        form = ProductAttributeForm(product=product, initial=initial)

    return render(request, 'core/product_attributes/create.html', {
        'form': form,
        'product': product,
        'next': next_url,
    })


@admin_required
def product_variation_files(request, product_id, variation_id):
    product = get_object_or_404(Product, pk=product_id)
    variation = get_object_or_404(
        ProductVariation.objects.select_related('product').prefetch_related('option_values__option'),
        pk=variation_id,
        product=product,
    )

    if request.method == 'POST':
        formset = get_variation_file_formset(variation, data=request.POST, files=request.FILES)
        if formset.is_valid():
            with transaction.atomic():
                for product_file in formset.save(commit=False):
                    product_file.product = product
                    product_file.variation = variation
                    product_file.save()
                for deleted in formset.deleted_objects:
                    deleted.delete()
            messages.success(request, f'Media updated for {variation.sku}.')
            return redirect('core:product_variation_files', product_id=product.pk, variation_id=variation.pk)
        messages.error(request, 'Please correct the errors below.')
    else:
        formset = get_variation_file_formset(variation)

    return render(request, 'core/product_variations/files.html', {
        'product': product,
        'variation': variation,
        'formset': formset,
    })


GROUP_BUY_STATUS_FILTERS = [
    ('', 'All'),
    (GroupBuy.Status.OPEN, 'Open'),
    (GroupBuy.Status.MOQ_REACHED, 'MOQ reached'),
    (GroupBuy.Status.IMPORTING, 'Importing'),
    (GroupBuy.Status.COMPLETED, 'Completed'),
    (GroupBuy.Status.CANCELLED, 'Cancelled'),
]


@staff_required
def group_buy_list(request):
    status_filter = request.GET.get('status', '')
    valid_statuses = {choice[0] for choice in GroupBuy.Status.choices}

    group_buys = GroupBuy.objects.select_related(
        'product',
        'product__category',
        'import_batch',
    ).prefetch_related(
        'product__files',
    ).annotate(
        pledged_total=Coalesce(Sum('entries__quantity'), Value(0)),
        backer_count=Count('entries', distinct=True),
        paid_order_count=Count(
            'orders',
            filter=Q(orders__status=Order.Status.PAID),
            distinct=True,
        ),
    ).order_by('-created_at')

    if status_filter in valid_statuses:
        group_buys = group_buys.filter(status=status_filter)

    summary = {
        'total': GroupBuy.objects.count(),
        'open': GroupBuy.objects.filter(status=GroupBuy.Status.OPEN).count(),
        'moq_reached': GroupBuy.objects.filter(status=GroupBuy.Status.MOQ_REACHED).count(),
        'importing': GroupBuy.objects.filter(status=GroupBuy.Status.IMPORTING).count(),
        'completed': GroupBuy.objects.filter(status=GroupBuy.Status.COMPLETED).count(),
        'cancelled': GroupBuy.objects.filter(status=GroupBuy.Status.CANCELLED).count(),
    }

    return render(request, 'core/group_buys/list.html', {
        'group_buys': group_buys,
        'summary': summary,
        'status_filter': status_filter,
        'status_filters': GROUP_BUY_STATUS_FILTERS,
    })


def _group_buy_manage_context(group_buy):
    import_batch = (
        ImportBatch.objects.select_related('supplier', 'shipment')
        .prefetch_related('additional_costs')
        .filter(group_buy=group_buy)
        .first()
    )
    entries = list(
        group_buy.entries.select_related('user', 'variation').order_by('-created_at')
    )
    paid_order_qs = group_buy.orders.filter(status=Order.Status.PAID).select_related(
        'user', 'payment', 'fulfillment',
    ).order_by('-created_at')
    for order in paid_order_qs:
        create_fulfillment_for_order(order)
    paid_orders = list(
        group_buy.orders.filter(status=Order.Status.PAID)
        .select_related('user', 'payment', 'fulfillment')
        .order_by('-created_at')
    )
    refund_orders = list(
        group_buy.orders.filter(status__in=[Order.Status.PAID, Order.Status.REFUNDED])
        .select_related('user', 'payment', 'fulfillment')
        .prefetch_related('refunds', 'refunds__created_by')
        .order_by('-created_at')
    )
    pledged_total = sum(entry.quantity for entry in entries)
    import_cost_summary = build_batch_cost_summary(import_batch) if import_batch else None
    additional_cost_formset = (
        ImportBatchAdditionalCostFormSet(instance=import_batch) if import_batch else None
    )
    product = group_buy.product
    price_min, price_max = product_variation_price_range(product)
    price_tiers = build_price_tiers(product, group_buy)
    return {
        'group_buy': group_buy,
        'product': product,
        'price_min': price_min,
        'price_max': price_max,
        'price_tiers': price_tiers,
        'pledger_count': len(entries),
        'import_batch': import_batch,
        'import_cost_summary': import_cost_summary,
        'additional_cost_formset': additional_cost_formset,
        'entries': entries,
        'paid_orders': paid_orders,
        'refund_orders': refund_orders,
        'pledged_total': pledged_total,
        'progress_percent': min(int((pledged_total / group_buy.moq) * 100), 100) if group_buy.moq else 100,
        'fulfillment_status_choices': Fulfillment.Status.choices,
        'mpesa_reversal_required': MPESA_REVERSAL_REQUIRED_IN_PRODUCTION,
    }


@staff_required
def group_buy_create(request):
    product = None
    product_id = request.GET.get('product')
    if product_id:
        product = Product.objects.filter(pk=product_id, is_active=True).first()

    if request.method == 'POST':
        form = GroupBuyForm(request.POST)
        if form.is_valid():
            group_buy = form.save()
            group_buy.refresh_status()
            messages.success(
                request,
                f'Group buy for "{group_buy.product.name}" created successfully.',
            )
            return redirect('core:group_buy_manage', group_buy_id=group_buy.pk)
        messages.error(request, 'Please correct the errors below.')
    else:
        initial = {
            'closes_at': timezone.now() + timedelta(days=30),
            'status': GroupBuy.Status.OPEN,
        }
        if product:
            initial['product'] = product.pk
        form = GroupBuyForm(initial=initial)

    return render(request, 'core/group_buys/create.html', {
        'form': form,
        'product': product,
    })


@staff_required
def group_buy_manage(request, group_buy_id):
    group_buy = get_object_or_404(
        GroupBuy.objects.select_related('product', 'product__category', 'product__supplier')
        .prefetch_related(
            Prefetch(
                'product__files',
                queryset=ProductFile.objects.filter(variation__isnull=True),
            ),
        ),
        pk=group_buy_id,
    )
    context = _group_buy_manage_context(group_buy)
    import_batch = context['import_batch']

    if request.method == 'POST':
        action = request.POST.get('action', 'save_group_buy')

        if action == 'save_group_buy':
            form = GroupBuyForm(request.POST, instance=group_buy)
            if form.is_valid():
                form.save()
                group_buy.refresh_status()
                messages.success(request, 'Group buy updated successfully.')
                return redirect('core:group_buy_manage', group_buy_id=group_buy.pk)
            messages.error(request, 'Please correct the errors below.')
            context['form'] = form
            context['import_batch_form'] = ImportBatchForm(instance=import_batch) if import_batch else None
            context['import_batch_create_form'] = ImportBatchCreateForm(product_supplier=group_buy.product.supplier)
            return render(request, 'core/group_buys/manage.html', context)

        if action == 'refresh_status':
            group_buy.refresh_status()
            messages.success(request, 'MOQ status refreshed from current bookings.')
            return redirect('core:group_buy_manage', group_buy_id=group_buy.pk)

        if action == 'create_import_batch':
            create_form = ImportBatchCreateForm(
                request.POST,
                product_supplier=group_buy.product.supplier,
            )
            if create_form.is_valid():
                try:
                    create_import_batch(
                        group_buy,
                        supplier=create_form.cleaned_data.get('supplier'),
                        supplier_reference=create_form.cleaned_data['supplier_reference'],
                        estimated_arrival=create_form.cleaned_data.get('estimated_arrival'),
                        notes=create_form.cleaned_data.get('notes', ''),
                    )
                    messages.success(request, 'Import batch created.')
                    return redirect('core:group_buy_manage', group_buy_id=group_buy.pk)
                except ValidationError as exc:
                    messages.error(request, '; '.join(getattr(exc, 'messages', [str(exc)])))
            else:
                messages.error(request, 'Please correct the import batch errors below.')
            context['form'] = GroupBuyForm(instance=group_buy)
            context['import_batch_create_form'] = create_form
            context['import_batch_form'] = None
            return render(request, 'core/group_buys/manage.html', context)

        if action == 'save_import_batch' and import_batch:
            batch_form = ImportBatchForm(request.POST, instance=import_batch)
            cost_formset = ImportBatchAdditionalCostFormSet(request.POST, instance=import_batch)
            if batch_form.is_valid() and cost_formset.is_valid():
                with transaction.atomic():
                    batch_form.save()
                    cost_formset.save()
                messages.success(request, 'Import batch and costing updated.')
                return redirect('core:group_buy_manage', group_buy_id=group_buy.pk)
            messages.error(request, 'Please correct the import batch errors below.')
            context['form'] = GroupBuyForm(instance=group_buy)
            context['import_batch_form'] = batch_form
            context['additional_cost_formset'] = cost_formset
            context['import_cost_summary'] = build_batch_cost_summary(import_batch)
            context['import_batch_create_form'] = ImportBatchCreateForm(product_supplier=group_buy.product.supplier)
            return render(request, 'core/group_buys/manage.html', context)

        if action == 'apply_suggested_price' and import_batch:
            summary = build_batch_cost_summary(import_batch)
            suggested = summary and summary.get('suggested_unit_price')
            if suggested and suggested > 0:
                group_buy.unit_price = suggested
                group_buy.save(update_fields=['unit_price', 'updated_at'])
                messages.success(
                    request,
                    f'Group buy unit price set to ${suggested} (landed cost + {summary["margin_percent"]}% margin).',
                )
            else:
                messages.error(request, 'Enter supplier cost and units first to get a price suggestion.')
            return redirect('core:group_buy_manage', group_buy_id=group_buy.pk)

        if action == 'update_fulfillment':
            fulfillment = get_object_or_404(
                Fulfillment.objects.select_related('order__group_buy'),
                pk=request.POST.get('fulfillment_id'),
                order__group_buy=group_buy,
            )
            batch_form = FulfillmentForm(request.POST, instance=fulfillment)
            if batch_form.is_valid():
                batch_form.save()
                messages.success(request, f'Fulfillment updated for order #{fulfillment.order_id}.')
                return redirect('core:group_buy_manage', group_buy_id=group_buy.pk)
            messages.error(request, 'Please correct the fulfillment errors below.')

        if action == 'create_refund':
            order = get_object_or_404(
                Order.objects.select_related('payment', 'group_buy'),
                pk=request.POST.get('order_id'),
                group_buy=group_buy,
            )
            refund_form = RefundCreateForm(
                request.POST,
                refundable_amount=order.refundable_amount,
            )
            if refund_form.is_valid():
                try:
                    create_refund(
                        order=order,
                        amount=refund_form.cleaned_data['amount'],
                        reason=refund_form.cleaned_data['reason'],
                        notes=refund_form.cleaned_data.get('notes', ''),
                        refund_type=refund_form.cleaned_data['refund_type'],
                        created_by=request.user,
                    )
                    messages.success(
                        request,
                        f'Refund recorded for order #{order.pk}. '
                        'Mark it complete after the buyer is repaid.',
                    )
                    return redirect('core:group_buy_manage', group_buy_id=group_buy.pk)
                except ValidationError as exc:
                    messages.error(request, '; '.join(getattr(exc, 'messages', [str(exc)])))
            else:
                messages.error(request, 'Please correct the refund errors below.')

        if action == 'complete_refund':
            refund = get_object_or_404(
                Refund.objects.select_related('order__group_buy'),
                pk=request.POST.get('refund_id'),
                order__group_buy=group_buy,
            )
            try:
                complete_refund(refund)
                if MPESA_REVERSAL_REQUIRED_IN_PRODUCTION:
                    messages.warning(
                        request,
                        f'Refund {refund.reference} marked complete. '
                        'PRODUCTION REMINDER: trigger M-Pesa Daraja reversal for this payment.',
                    )
                else:
                    messages.success(request, f'Refund {refund.reference} marked complete.')
                return redirect('core:group_buy_manage', group_buy_id=group_buy.pk)
            except ValidationError as exc:
                messages.error(request, '; '.join(getattr(exc, 'messages', [str(exc)])))

        if action == 'cancel_refund':
            refund = get_object_or_404(
                Refund.objects.select_related('order__group_buy'),
                pk=request.POST.get('refund_id'),
                order__group_buy=group_buy,
            )
            try:
                cancel_refund(refund)
                messages.success(request, f'Refund {refund.reference} cancelled.')
                return redirect('core:group_buy_manage', group_buy_id=group_buy.pk)
            except ValidationError as exc:
                messages.error(request, '; '.join(getattr(exc, 'messages', [str(exc)])))

    context = _group_buy_manage_context(group_buy)
    import_batch = context['import_batch']
    context['form'] = GroupBuyForm(instance=group_buy)
    context['import_batch_form'] = ImportBatchForm(instance=import_batch) if import_batch else None
    if import_batch and context.get('additional_cost_formset') is None:
        context['additional_cost_formset'] = ImportBatchAdditionalCostFormSet(instance=import_batch)
    context['import_batch_create_form'] = ImportBatchCreateForm(product_supplier=group_buy.product.supplier)
    return render(request, 'core/group_buys/manage.html', context)


@staff_required
def import_shipment_list(request):
    shipments = (
        ImportShipment.objects.annotate(batch_count=Count('import_batches'))
        .order_by('-created_at')
    )
    return render(request, 'core/import_shipments/list.html', {
        'shipments': shipments,
    })


@staff_required
def import_shipment_create(request):
    if request.method == 'POST':
        form = ImportShipmentForm(request.POST)
        if form.is_valid():
            shipment = form.save()
            messages.success(request, f'Shipment "{shipment.name}" created.')
            return redirect('core:import_shipment_manage', shipment_id=shipment.pk)
        messages.error(request, 'Please correct the errors below.')
    else:
        form = ImportShipmentForm()
    return render(request, 'core/import_shipments/form.html', {
        'form': form,
        'title': 'New shipment batch',
    })


@staff_required
def import_shipment_manage(request, shipment_id):
    shipment = get_object_or_404(
        ImportShipment.objects.prefetch_related(
            'import_batches__group_buy__product',
            'import_batches__additional_costs',
        ),
        pk=shipment_id,
    )

    if request.method == 'POST':
        action = request.POST.get('action', 'save_shipment')
        if action == 'delete_shipment':
            name = shipment.name
            shipment.delete()
            messages.success(request, f'Shipment "{name}" deleted.')
            return redirect('core:import_shipment_list')

        if action == 'add_product':
            add_form = ImportShipmentAddProductForm(request.POST, shipment=shipment)
            if add_form.is_valid():
                try:
                    link_group_buy_to_shipment(add_form.cleaned_data['group_buy'], shipment)
                    messages.success(request, 'Product added to this shipment.')
                except ValidationError as exc:
                    messages.error(request, '; '.join(getattr(exc, 'messages', [str(exc)])))
            else:
                messages.error(request, 'Could not add product — pick one from the list.')
            return redirect('core:import_shipment_manage', shipment_id=shipment.pk)

        if action == 'remove_product':
            batch = get_object_or_404(ImportBatch, pk=request.POST.get('import_batch_id'), shipment=shipment)
            unlink_import_batch_from_shipment(batch)
            messages.success(request, f'Removed "{batch.group_buy.product.name}" from this shipment.')
            return redirect('core:import_shipment_manage', shipment_id=shipment.pk)

        if action == 'parse_supplier_paste':
            raw = request.POST.get('supplier_paste', '')
            use_ai = request.POST.get('use_ai') == '1'
            session_key = f'import_shipment_supplier_paste_{shipment.pk}'
            parsed = None
            try:
                parsed = parse_supplier_order_paste(raw, use_ai=use_ai)
            except RuntimeError as exc:
                messages.error(request, str(exc))
            if parsed is not None:
                if not parsed:
                    messages.warning(
                        request,
                        'No order lines found. Paste blocks with title, USD/piece, quantity, and line total.',
                    )
                    request.session[session_key] = {'rows': [], 'raw': raw}
                else:
                    batches = list(shipment.import_batches.select_related('group_buy__product'))
                    matched = match_parsed_lines_to_batches(parsed, batches)
                    request.session[session_key] = {
                        'rows': serialize_supplier_paste_rows(matched),
                        'raw': raw,
                    }
                    matched_count = sum(1 for row in matched if row.get('import_batch_id'))
                    messages.success(
                        request,
                        f'Parsed {len(matched)} line(s); {matched_count} matched to products on this shipment.',
                    )
            return redirect('core:import_shipment_manage', shipment_id=shipment.pk)

        if action == 'apply_supplier_paste':
            from decimal import Decimal

            session_key = f'import_shipment_supplier_paste_{shipment.pk}'
            data = request.session.get(session_key)
            if not data or not data.get('rows'):
                messages.error(request, 'Parse supplier order text first.')
                return redirect('core:import_shipment_manage', shipment_id=shipment.pk)
            valid_batch_ids = set(
                shipment.import_batches.values_list('pk', flat=True)
            )
            selected = {str(i) for i in request.POST.getlist('paste_row')}
            rows_to_apply = []
            for index, row in enumerate(data['rows']):
                if str(index) not in selected:
                    continue
                batch_id = request.POST.get(f'paste_batch_{index}', '').strip()
                if batch_id:
                    try:
                        batch_id = int(batch_id)
                    except ValueError:
                        batch_id = None
                else:
                    batch_id = row.get('import_batch_id')
                if not batch_id or batch_id not in valid_batch_ids:
                    continue
                rows_to_apply.append({
                    'import_batch_id': batch_id,
                    'supplier_unit_cost': Decimal(row['supplier_unit_cost']),
                    'units': int(row['units']),
                })
            updated = apply_parsed_costing_to_batches(rows_to_apply, shipment)
            if updated:
                messages.success(
                    request,
                    f'Updated supplier cost and units on {updated} product(s). '
                    'Add freight and customs on each product’s group buy page.',
                )
                request.session.pop(session_key, None)
            else:
                messages.warning(request, 'No matched rows were applied — check selections and product names.')
            return redirect('core:import_shipment_manage', shipment_id=shipment.pk)

        if action == 'clear_supplier_paste':
            request.session.pop(f'import_shipment_supplier_paste_{shipment.pk}', None)
            return redirect('core:import_shipment_manage', shipment_id=shipment.pk)

        if action == 'apply_shared_cost_split':
            split_form = ShipmentSharedCostSplitForm(request.POST)
            batch_ids = request.POST.getlist('shared_cost_batch')
            if not batch_ids:
                messages.error(request, 'Select at least one product in the table (checkboxes).')
                return redirect('core:import_shipment_manage', shipment_id=shipment.pk)
            if split_form.is_valid():
                try:
                    result = apply_shipment_shared_cost_split(
                        shipment,
                        [int(pk) for pk in batch_ids],
                        cost_type=split_form.cleaned_data['cost_type'],
                        total_amount=split_form.cleaned_data['amount'],
                        description=split_form.cleaned_data.get('description') or '',
                    )
                except (ValueError, TypeError) as exc:
                    messages.error(request, str(exc))
                else:
                    parts = ', '.join(
                        f'{a["product_name"]} ${a["amount"]} ({a["units"]} u)'
                        for a in result['allocations']
                    )
                    messages.success(
                        request,
                        f'Split ${result["total_amount"]} across {len(result["allocations"])} product(s): {parts}',
                    )
            else:
                messages.error(request, 'Fix the shared charge form and try again.')
            return redirect('core:import_shipment_manage', shipment_id=shipment.pk)

        form = ImportShipmentForm(request.POST, instance=shipment)
        if form.is_valid():
            form.save()
            messages.success(request, 'Shipment batch updated.')
            return redirect('core:import_shipment_manage', shipment_id=shipment.pk)
        messages.error(request, 'Please correct the errors below.')
    else:
        form = ImportShipmentForm(instance=shipment)

    batch_summaries = []
    for batch in shipment.import_batches.select_related('group_buy__product', 'group_buy__product__category').prefetch_related('group_buy__product__files'):
        summary = build_batch_cost_summary(batch)
        line_profit = None
        if summary and summary['units']:
            line_profit = (
                summary['current_unit_price'] * summary['units'] - summary['landed_total']
            )
        batch_summaries.append({
            'batch': batch,
            'summary': summary,
            'line_profit': line_profit,
            'picker': group_buy_picker_items([batch.group_buy], request=request)[0],
        })

    available_group_buys = group_buys_available_for_shipment(shipment)
    add_product_picker_items = group_buy_picker_items(available_group_buys, request=request)

    shipment_analytics = build_shipment_analytics(batch_summaries)

    paste_session = request.session.get(f'import_shipment_supplier_paste_{shipment.pk}', {})
    supplier_paste_preview = paste_session.get('rows') or []
    supplier_paste_raw = paste_session.get('raw', '')

    shipment_paste_batch_choices = [
        {
            'id': item['batch'].pk,
            'name': item['batch'].group_buy.product.name,
        }
        for item in batch_summaries
    ]

    return render(request, 'core/import_shipments/manage.html', {
        'shipment': shipment,
        'form': form,
        'add_product_form': ImportShipmentAddProductForm(shipment=shipment),
        'add_product_picker_items': add_product_picker_items,
        'add_product_search_url': reverse(
            'core:import_shipment_group_buy_search',
            kwargs={'shipment_id': shipment.pk},
        ),
        'batch_summaries': batch_summaries,
        'total_units': shipment.total_units,
        'shipment_analytics': shipment_analytics,
        'openai_configured': is_openai_configured(),
        'supplier_paste_preview': supplier_paste_preview,
        'supplier_paste_raw': supplier_paste_raw,
        'shipment_paste_batch_choices': shipment_paste_batch_choices,
        'shared_cost_split_form': ShipmentSharedCostSplitForm(),
    })


@staff_required
def import_shipment_group_buy_search(request, shipment_id):
    shipment = get_object_or_404(ImportShipment, pk=shipment_id)
    query = request.GET.get('q', '').strip()
    available = group_buys_available_for_shipment(shipment)
    filtered = filter_group_buys_for_search(available, query)[:30]
    return JsonResponse({
        'results': group_buy_picker_items(filtered, request=request),
    })


@staff_required
def refund_list(request):
    status_filter = request.GET.get('status', 'pending')
    refunds = Refund.objects.select_related(
        'order__user',
        'order__group_buy__product',
        'payment',
        'created_by',
    ).order_by('-created_at')

    if status_filter and status_filter != 'all':
        refunds = refunds.filter(status=status_filter)

    summary = {
        'pending': Refund.objects.filter(status=Refund.Status.PENDING).count(),
        'completed': Refund.objects.filter(status=Refund.Status.COMPLETED).count(),
        'cancelled': Refund.objects.filter(status=Refund.Status.CANCELLED).count(),
        'failed': Refund.objects.filter(status=Refund.Status.FAILED).count(),
    }

    if request.method == 'POST':
        action = request.POST.get('action')
        refund = get_object_or_404(Refund, pk=request.POST.get('refund_id'))

        if action == 'complete_refund':
            try:
                complete_refund(refund)
                if MPESA_REVERSAL_REQUIRED_IN_PRODUCTION:
                    messages.warning(
                        request,
                        f'Refund {refund.reference} marked complete. '
                        'PRODUCTION REMINDER: trigger M-Pesa Daraja reversal for this payment.',
                    )
                else:
                    messages.success(request, f'Refund {refund.reference} marked complete.')
            except ValidationError as exc:
                messages.error(request, '; '.join(getattr(exc, 'messages', [str(exc)])))
        elif action == 'cancel_refund':
            try:
                cancel_refund(refund)
                messages.success(request, f'Refund {refund.reference} cancelled.')
            except ValidationError as exc:
                messages.error(request, '; '.join(getattr(exc, 'messages', [str(exc)])))

        redirect_status = request.GET.get('status', status_filter)
        url = reverse('core:refund_list')
        if redirect_status:
            return redirect(f'{url}?status={redirect_status}')
        return redirect('core:refund_list')

    return render(request, 'core/refunds/list.html', {
        'refunds': refunds,
        'status_filter': status_filter,
        'summary': summary,
        'mpesa_reversal_required': MPESA_REVERSAL_REQUIRED_IN_PRODUCTION,
    })


@staff_required
def complaint_list(request):
    status_filter = request.GET.get('status', 'open')
    complaints = Complaint.objects.select_related(
        'user',
        'order__group_buy__product',
    ).prefetch_related('messages').order_by('-created_at')

    if status_filter and status_filter != 'all':
        if status_filter == 'open':
            complaints = complaints.filter(
                status__in=[Complaint.Status.OPEN, Complaint.Status.IN_PROGRESS],
            )
        else:
            complaints = complaints.filter(status=status_filter)

    summary = {
        'open': Complaint.objects.filter(
            status__in=[Complaint.Status.OPEN, Complaint.Status.IN_PROGRESS],
        ).count(),
        'resolved': Complaint.objects.filter(status=Complaint.Status.RESOLVED).count(),
        'closed': Complaint.objects.filter(status=Complaint.Status.CLOSED).count(),
        'total': Complaint.objects.count(),
    }

    if request.method == 'POST':
        complaint = get_object_or_404(Complaint, pk=request.POST.get('complaint_id'))
        form = ComplaintStaffReplyForm(request.POST, complaint=complaint)
        if form.is_valid():
            try:
                if form.cleaned_data['body'].strip():
                    add_complaint_message(
                        complaint=complaint,
                        author=request.user,
                        body=form.cleaned_data['body'],
                        is_staff_reply=True,
                    )
                update_complaint_status(
                    complaint=complaint,
                    status=form.cleaned_data['status'],
                    staff_notes=form.cleaned_data['staff_notes'],
                )
                messages.success(request, f'Complaint {complaint.reference} updated.')
            except ValidationError as exc:
                messages.error(request, '; '.join(getattr(exc, 'messages', [str(exc)])))
        else:
            messages.error(request, 'Please correct the errors below.')

        redirect_status = request.GET.get('status', status_filter)
        url = reverse('core:complaint_list')
        if redirect_status:
            return redirect(f'{url}?status={redirect_status}')
        return redirect('core:complaint_list')

    return render(request, 'core/complaints/manage.html', {
        'complaints': complaints,
        'status_filter': status_filter,
        'summary': summary,
    })


@admin_required
def supplier_list(request):
    query = request.GET.get('q', '').strip()
    status_filter = request.GET.get('status', 'active')

    suppliers = Supplier.objects.annotate(
        product_count=Count('products', distinct=True),
        batch_count=Count('import_batches', distinct=True),
    )

    if query:
        suppliers = suppliers.filter(
            Q(name__icontains=query)
            | Q(contact_name__icontains=query)
            | Q(email__icontains=query)
            | Q(phone__icontains=query)
            | Q(wechat_id__icontains=query)
            | Q(country__icontains=query)
        )

    if status_filter == 'active':
        suppliers = suppliers.filter(is_active=True)
    elif status_filter == 'inactive':
        suppliers = suppliers.filter(is_active=False)

    suppliers = suppliers.order_by('name')

    summary = {
        'total': Supplier.objects.count(),
        'active': Supplier.objects.filter(is_active=True).count(),
        'inactive': Supplier.objects.filter(is_active=False).count(),
        'with_products': Supplier.objects.filter(products__isnull=False).distinct().count(),
    }

    return render(request, 'core/suppliers/list.html', {
        'suppliers': suppliers,
        'query': query,
        'status_filter': status_filter,
        'summary': summary,
    })


@admin_required
def supplier_manage(request, supplier_id):
    supplier = get_object_or_404(
        Supplier.objects.annotate(
            product_count=Count('products', distinct=True),
            batch_count=Count('import_batches', distinct=True),
        ),
        pk=supplier_id,
    )
    products = (
        supplier.products.select_related('category')
        .prefetch_related('variations')
        .order_by('-created_at')
    )
    import_batches = (
        supplier.import_batches.select_related('group_buy__product')
        .order_by('-created_at')
    )

    return render(request, 'core/suppliers/manage.html', {
        'supplier': supplier,
        'products': products,
        'import_batches': import_batches,
    })


@admin_required
def supplier_create(request):
    if request.method == 'POST':
        form = SupplierForm(request.POST)
        if form.is_valid():
            supplier = form.save()
            messages.success(request, f'Supplier "{supplier.name}" created.')
            return redirect('core:supplier_manage', supplier_id=supplier.pk)
        messages.error(request, 'Please correct the errors below.')
    else:
        form = SupplierForm()
    return render(request, 'core/suppliers/form.html', {
        'form': form,
        'title': 'Add supplier',
    })


@admin_required
def supplier_edit(request, supplier_id):
    supplier = get_object_or_404(Supplier, pk=supplier_id)
    if request.method == 'POST':
        form = SupplierForm(request.POST, instance=supplier)
        if form.is_valid():
            supplier = form.save()
            messages.success(request, f'Supplier "{supplier.name}" updated.')
            return redirect('core:supplier_manage', supplier_id=supplier.pk)
        messages.error(request, 'Please correct the errors below.')
    else:
        form = SupplierForm(instance=supplier)
    return render(request, 'core/suppliers/form.html', {
        'form': form,
        'title': 'Edit supplier',
        'supplier': supplier,
    })
