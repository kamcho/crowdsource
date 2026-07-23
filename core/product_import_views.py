import json

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from core.decorators import admin_required
from core.forms import (
    ProductImportBasicsForm,
    ProductImportCategoriesForm,
    ProductImportPasteForm,
    ProductImportSupplierForm,
)
from core.models import Category, Product
from core.openai_product_import import is_openai_configured, parse_pasted_product_content
from core.product_import import ProductImportDraft, ProductImportMedia
from core.product_import_services import (
    add_product_import_media,
    add_variation_import_media,
    advance_draft_step,
    draft_has_category_step,
    draft_has_supplier_step,
    get_category_choices,
    get_import_step_order,
    get_next_import_step,
    get_supplier_choices,
    parse_attributes_post,
    parse_variations_post,
    publish_product_import_draft,
    save_categories_from_import,
    save_supplier_from_import,
    set_product_import_media_primary,
    skip_category_step,
    skip_supplier_step,
    update_draft_attributes,
    update_draft_from_basics,
    update_draft_supplier_data,
    update_draft_variations,
)

STEP_ROUTES = {
    ProductImportDraft.Step.SUPPLIER: 'core:product_import_supplier',
    ProductImportDraft.Step.CATEGORIES: 'core:product_import_categories',
    ProductImportDraft.Step.BASICS: 'core:product_import_basics',
    ProductImportDraft.Step.ATTRIBUTES: 'core:product_import_attributes',
    ProductImportDraft.Step.VARIATIONS: 'core:product_import_variations',
    ProductImportDraft.Step.PRODUCT_MEDIA: 'core:product_import_product_media',
    ProductImportDraft.Step.VARIATION_MEDIA: 'core:product_import_variation_media',
    ProductImportDraft.Step.REVIEW: 'core:product_import_review',
}


def _draft_queryset(user):
    return ProductImportDraft.objects.filter(created_by=user).exclude(
        status=ProductImportDraft.Status.DISCARDED,
    )


def _step_context(draft):
    step_order = get_import_step_order(draft)
    current_index = step_order.index(draft.current_step) if draft.current_step in step_order else 0
    steps = []
    for step in step_order:
        step_index = step_order.index(step)
        steps.append({
            'key': step,
            'label': ProductImportDraft.Step(step).label,
            'url': reverse(STEP_ROUTES[step], kwargs={'draft_id': draft.pk}),
            'is_current': draft.current_step == step,
            'is_complete': step_index < current_index,
        })
    return {
        'draft': draft,
        'wizard_steps': steps,
        'step_number': current_index + 1,
        'step_total': len(step_order),
    }


def _redirect_step(draft):
    return redirect(STEP_ROUTES.get(draft.current_step, 'core:product_import_basics'), draft_id=draft.pk)


@admin_required
def product_import_list(request):
    drafts = _draft_queryset(request.user).select_related('product', 'created_by')
    return render(request, 'core/product_import/list.html', {
        'drafts': drafts,
        'openai_configured': is_openai_configured(),
    })


@admin_required
def product_import_start(request):
    if not is_openai_configured():
        messages.error(
            request,
            'OpenAI is not configured. Add OPENAI_API_KEY to your .env file.',
        )
        return redirect('core:product_import_list')

    if request.method == 'POST':
        form = ProductImportPasteForm(request.POST)
        if form.is_valid():
            draft = ProductImportDraft.objects.create(
                created_by=request.user,
                source_url=form.cleaned_data.get('source_url') or '',
                raw_paste=form.cleaned_data['raw_paste'],
                status=ProductImportDraft.Status.PARSING,
                current_step=ProductImportDraft.Step.BASICS,
            )
            try:
                parsed = parse_pasted_product_content(
                    raw_paste=draft.raw_paste,
                    source_url=draft.source_url,
                    categories=get_category_choices(),
                    suppliers=get_supplier_choices(),
                )
                draft.draft_data = parsed
                draft.status = ProductImportDraft.Status.IN_PROGRESS
                draft.parse_error = ''
                draft.current_step = get_next_import_step(draft)
                draft.save(update_fields=[
                    'draft_data', 'status', 'parse_error', 'current_step', 'updated_at',
                ])
                messages.success(request, 'Content parsed successfully. Review each step before publishing.')
                return _redirect_step(draft)
            except Exception as exc:
                draft.status = ProductImportDraft.Status.FAILED
                draft.parse_error = str(exc)
                draft.save(update_fields=['status', 'parse_error', 'updated_at'])
                messages.error(request, f'Could not parse content: {exc}')
                return redirect('core:product_import_list')
        messages.error(request, 'Paste supplier content before continuing.')
    else:
        form = ProductImportPasteForm()

    return render(request, 'core/product_import/start.html', {
        'form': form,
        'openai_configured': is_openai_configured(),
    })


@admin_required
def product_import_supplier(request, draft_id):
    draft = get_object_or_404(_draft_queryset(request.user), pk=draft_id)
    if draft.status == ProductImportDraft.Status.FAILED:
        messages.error(request, draft.parse_error or 'Parsing failed.')
        return redirect('core:product_import_list')

    if not draft_has_supplier_step(draft):
        return redirect('core:product_import_basics', draft_id=draft.pk)

    supplier_data = (draft.draft_data or {}).get('supplier') or {}

    if request.method == 'POST':
        if request.POST.get('action') == 'skip':
            skip_supplier_step(draft)
            draft.current_step = get_next_import_step(draft)
            draft.save(update_fields=['current_step', 'updated_at'])
            messages.info(request, 'Supplier step skipped. You can link a supplier later on product details.')
            return _redirect_step(draft)

        form = ProductImportSupplierForm(request.POST)
        if form.is_valid():
            update_draft_supplier_data(draft, form.cleaned_data)
            supplier, created = save_supplier_from_import(draft, **form.cleaned_data)
            draft.current_step = get_next_import_step(draft)
            draft.save(update_fields=['current_step', 'updated_at'])
            if created:
                messages.success(request, f'Supplier "{supplier.name}" created.')
            else:
                messages.success(
                    request,
                    f'Linked existing supplier "{supplier.name}".',
                )
            return _redirect_step(draft)
        messages.error(request, 'Please correct the errors below.')
    else:
        form = ProductImportSupplierForm(initial=supplier_data)

    context = _step_context(draft)
    context.update({'form': form})
    return render(request, 'core/product_import/supplier.html', context)


@admin_required
def product_import_categories(request, draft_id):
    draft = get_object_or_404(_draft_queryset(request.user), pk=draft_id)
    if draft.status == ProductImportDraft.Status.FAILED:
        messages.error(request, draft.parse_error or 'Parsing failed.')
        return redirect('core:product_import_list')

    if not draft_has_category_step(draft):
        return redirect('core:product_import_basics', draft_id=draft.pk)

    proposal = (draft.draft_data or {}).get('category_proposal') or {'segments': []}

    if request.method == 'POST':
        if request.POST.get('action') == 'skip':
            skip_category_step(draft)
            draft.current_step = ProductImportDraft.Step.BASICS
            draft.save(update_fields=['current_step', 'updated_at'])
            messages.info(request, 'Category step skipped. Choose a category on the next step.')
            return redirect('core:product_import_basics', draft_id=draft.pk)

        form = ProductImportCategoriesForm(request.POST, proposal=proposal)
        if form.is_valid():
            try:
                leaf = save_categories_from_import(draft, form.cleaned_data['segment_names'])
            except ValidationError as exc:
                messages.error(request, '; '.join(getattr(exc, 'messages', [str(exc)])))
            else:
                draft.current_step = ProductImportDraft.Step.BASICS
                draft.save(update_fields=['current_step', 'updated_at'])
                messages.success(request, f'Categories saved. Product will use "{leaf.name}".')
                return redirect('core:product_import_basics', draft_id=draft.pk)
        messages.error(request, 'Please correct the errors below.')
    else:
        form = ProductImportCategoriesForm(proposal=proposal)

    context = _step_context(draft)
    context.update({
        'form': form,
        'category_proposal': proposal,
    })
    return render(request, 'core/product_import/categories.html', context)


@admin_required
def product_import_basics(request, draft_id):
    draft = get_object_or_404(_draft_queryset(request.user), pk=draft_id)
    if draft.status == ProductImportDraft.Status.FAILED:
        messages.error(request, draft.parse_error or 'Parsing failed.')
        return redirect('core:product_import_list')

    if draft_has_supplier_step(draft):
        return redirect('core:product_import_supplier', draft_id=draft.pk)

    if draft_has_category_step(draft):
        return redirect('core:product_import_categories', draft_id=draft.pk)

    data = draft.draft_data or {}
    initial = {
        'name': data.get('name', ''),
        'description': data.get('description', ''),
        'category': data.get('category_id'),
        'supplier': data.get('supplier_id'),
        'is_special_class': data.get('is_special_class', False),
        'is_active': data.get('is_active', True),
    }

    if request.method == 'POST':
        form = ProductImportBasicsForm(request.POST)
        if form.is_valid():
            update_draft_from_basics(
                draft,
                name=form.cleaned_data['name'],
                description=form.cleaned_data['description'],
                category_id=form.cleaned_data['category'].pk,
                supplier_id=form.cleaned_data['supplier'].pk if form.cleaned_data['supplier'] else None,
                is_special_class=form.cleaned_data['is_special_class'],
                is_active=form.cleaned_data['is_active'],
            )
            advance_draft_step(draft, ProductImportDraft.Step.ATTRIBUTES)
            messages.success(request, 'Product details saved.')
            return redirect('core:product_import_attributes', draft_id=draft.pk)
        messages.error(request, 'Please correct the errors below.')
    else:
        form = ProductImportBasicsForm(initial=initial)

    context = _step_context(draft)
    context.update({'form': form})
    return render(request, 'core/product_import/basics.html', context)


@admin_required
def product_import_attributes(request, draft_id):
    draft = get_object_or_404(_draft_queryset(request.user), pk=draft_id)
    attributes = (draft.draft_data or {}).get('attributes', [])

    if request.method == 'POST':
        if request.POST.get('action') == 'back':
            advance_draft_step(draft, ProductImportDraft.Step.BASICS)
            return redirect('core:product_import_basics', draft_id=draft.pk)
        try:
            parsed = parse_attributes_post(request.POST)
            update_draft_attributes(draft, parsed)
            advance_draft_step(draft, ProductImportDraft.Step.VARIATIONS)
            messages.success(request, 'Specifications saved.')
            return redirect('core:product_import_variations', draft_id=draft.pk)
        except ValidationError as exc:
            messages.error(request, '; '.join(getattr(exc, 'messages', [str(exc)])))

    context = _step_context(draft)
    context.update({
        'attributes': attributes,
    })
    return render(request, 'core/product_import/attributes.html', context)


@admin_required
def product_import_variations(request, draft_id):
    draft = get_object_or_404(_draft_queryset(request.user), pk=draft_id)
    data = draft.draft_data or {}

    if request.method == 'POST':
        if request.POST.get('action') == 'back':
            advance_draft_step(draft, ProductImportDraft.Step.ATTRIBUTES)
            return redirect('core:product_import_attributes', draft_id=draft.pk)
        try:
            options, variations = parse_variations_post(request.POST)
            update_draft_variations(draft, options=options, variations=variations)
            advance_draft_step(draft, ProductImportDraft.Step.PRODUCT_MEDIA)
            messages.success(request, 'Variations saved.')
            return redirect('core:product_import_product_media', draft_id=draft.pk)
        except ValidationError as exc:
            messages.error(request, '; '.join(getattr(exc, 'messages', [str(exc)])))

    context = _step_context(draft)
    context.update({
        'import_variations_data': {
            'options': data.get('options', []),
            'variations': data.get('variations', []),
        },
    })
    return render(request, 'core/product_import/variations.html', context)


@admin_required
def product_import_product_media(request, draft_id):
    draft = get_object_or_404(_draft_queryset(request.user), pk=draft_id)
    product_media = draft.media_files.filter(variation_sku='')

    if request.method == 'POST':
        if request.POST.get('action') == 'back':
            advance_draft_step(draft, ProductImportDraft.Step.VARIATIONS)
            return redirect('core:product_import_variations', draft_id=draft.pk)

        if request.POST.get('action') == 'fetch_from_url':
            from core.product_import_services import fetch_listing_images_for_draft

            fetch_url = request.POST.get('fetch_url', '').strip()
            try:
                result = fetch_listing_images_for_draft(draft, url=fetch_url or None)
            except ValidationError as exc:
                messages.error(request, '; '.join(getattr(exc, 'messages', [str(exc)])))
            else:
                message = (
                    f'Downloaded {result["downloaded"]} of {result["found"]} '
                    f'image(s) from the listing.'
                )
                if result['errors']:
                    message += f' {len(result["errors"])} download(s) failed.'
                messages.success(request, message)
            return redirect('core:product_import_product_media', draft_id=draft.pk)

        if request.POST.get('action') == 'set_primary':
            media_id = request.POST.get('media_id')
            try:
                set_product_import_media_primary(draft, media_id)
            except ValidationError as exc:
                messages.error(request, '; '.join(getattr(exc, 'messages', [str(exc)])))
            else:
                messages.success(request, 'Primary image updated.')
            return redirect('core:product_import_product_media', draft_id=draft.pk)

        uploads = request.FILES.getlist('images')
        existing_count = draft.media_files.filter(variation_sku='').count()
        has_primary = draft.media_files.filter(variation_sku='', is_primary=True).exists()
        for index, upload in enumerate(uploads):
            make_primary = not has_primary and index == 0
            add_product_import_media(
                draft,
                upload,
                is_primary=make_primary,
                sort_order=existing_count + index,
            )
            if make_primary:
                has_primary = True

        if request.POST.get('remove_id'):
            removed = draft.media_files.filter(
                pk=request.POST.get('remove_id'),
                variation_sku='',
            ).first()
            was_primary = bool(removed and removed.is_primary)
            if removed:
                removed.delete()
            if was_primary:
                next_media = draft.media_files.filter(variation_sku='').order_by('sort_order', 'id').first()
                if next_media:
                    set_product_import_media_primary(draft, next_media.pk)

        if request.POST.get('action') == 'continue':
            advance_draft_step(draft, ProductImportDraft.Step.VARIATION_MEDIA)
            messages.success(request, 'Product images saved.')
            return redirect('core:product_import_variation_media', draft_id=draft.pk)
        messages.success(request, 'Images uploaded.')

    context = _step_context(draft)
    context.update({'product_media': draft.media_files.filter(variation_sku='')})
    return render(request, 'core/product_import/product_media.html', context)


@admin_required
def product_import_variation_media(request, draft_id):
    draft = get_object_or_404(_draft_queryset(request.user), pk=draft_id)
    variations = (draft.draft_data or {}).get('variations', [])

    if request.method == 'POST':
        if request.POST.get('action') == 'back':
            advance_draft_step(draft, ProductImportDraft.Step.PRODUCT_MEDIA)
            return redirect('core:product_import_product_media', draft_id=draft.pk)

        sku = request.POST.get('variation_sku', '').strip()
        uploads = request.FILES.getlist('images')
        if sku and uploads:
            existing = draft.media_files.filter(variation_sku=sku).count()
            for index, upload in enumerate(uploads):
                add_variation_import_media(
                    draft,
                    sku=sku,
                    upload=upload,
                    is_primary=existing == 0 and index == 0,
                    sort_order=existing + index,
                )
            messages.success(request, f'Images added for {sku}.')

        if request.POST.get('remove_id'):
            draft.media_files.filter(pk=request.POST.get('remove_id')).delete()

        if request.POST.get('action') == 'continue':
            advance_draft_step(draft, ProductImportDraft.Step.REVIEW)
            messages.success(request, 'Variation images saved.')
            return redirect('core:product_import_review', draft_id=draft.pk)

    media_by_sku = {}
    for media in draft.media_files.exclude(variation_sku=''):
        media_by_sku.setdefault(media.variation_sku, []).append(media)

    variation_rows = []
    for variation in variations:
        row = dict(variation)
        row['media'] = media_by_sku.get(variation.get('sku', ''), [])
        variation_rows.append(row)

    context = _step_context(draft)
    context.update({
        'variations': variation_rows,
    })
    return render(request, 'core/product_import/variation_media.html', context)


@admin_required
def product_import_review(request, draft_id):
    draft = get_object_or_404(_draft_queryset(request.user), pk=draft_id)
    data = draft.draft_data or {}

    category = Category.objects.filter(pk=data.get('category_id')).first()
    from core.supplier import Supplier
    supplier = Supplier.objects.filter(pk=data.get('supplier_id')).first()

    if request.method == 'POST':
        if request.POST.get('action') == 'back':
            advance_draft_step(draft, ProductImportDraft.Step.VARIATION_MEDIA)
            return redirect('core:product_import_variation_media', draft_id=draft.pk)
        try:
            product = publish_product_import_draft(draft)
            messages.success(request, f'Product "{product.name}" published to the catalog.')
            return redirect('core:product_list')
        except ValidationError as exc:
            messages.error(request, '; '.join(getattr(exc, 'messages', [str(exc)])))

    context = _step_context(draft)
    context.update({
        'data': data,
        'category': category,
        'supplier': supplier,
        'product_media': draft.media_files.filter(variation_sku=''),
        'variation_media': draft.media_files.exclude(variation_sku=''),
    })
    return render(request, 'core/product_import/review.html', context)


@admin_required
@require_POST
def product_import_discard(request, draft_id):
    draft = get_object_or_404(_draft_queryset(request.user), pk=draft_id)
    draft.status = ProductImportDraft.Status.DISCARDED
    draft.save(update_fields=['status', 'updated_at'])
    messages.info(request, 'Import draft discarded.')
    return redirect('core:product_import_list')
