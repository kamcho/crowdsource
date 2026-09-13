from django.db import transaction

from .category_link import CategoryGoTogetherLink
from .models import Category


def get_go_together_category_ids(category):
    """Return active linked category IDs for a category."""
    if not category or not category.pk:
        return []
    return list(
        CategoryGoTogetherLink.objects.filter(
            source_category=category,
            linked_category__is_active=True,
        ).values_list('linked_category_id', flat=True)
    )


def get_go_together_categories(category):
    """Return active Category instances linked to the given category."""
    ids = get_go_together_category_ids(category)
    if not ids:
        return []
    categories = Category.objects.filter(pk__in=ids, is_active=True)
    by_id = {item.pk: item for item in categories}
    return [by_id[pk] for pk in ids if pk in by_id]


@transaction.atomic
def set_go_together_categories(source_category, linked_category_ids):
    """
    Replace go-together links for source_category.
    Links are symmetric: linking A with B creates A→B and B→A.
    """
    linked_ids = {
        int(category_id)
        for category_id in linked_category_ids
        if int(category_id) != source_category.pk
    }
    current_ids = set(get_go_together_category_ids(source_category))

    to_add = linked_ids - current_ids
    to_remove = current_ids - linked_ids

    for linked_id in to_add:
        linked_category = Category.objects.get(pk=linked_id)
        CategoryGoTogetherLink.objects.get_or_create(
            source_category=source_category,
            linked_category=linked_category,
        )
        CategoryGoTogetherLink.objects.get_or_create(
            source_category=linked_category,
            linked_category=source_category,
        )

    for linked_id in to_remove:
        CategoryGoTogetherLink.objects.filter(
            source_category=source_category,
            linked_category_id=linked_id,
        ).delete()
        CategoryGoTogetherLink.objects.filter(
            source_category_id=linked_id,
            linked_category=source_category,
        ).delete()


def build_go_together_overview(category_rows):
    """
    Given (category, depth) rows from build_category_tree, return rows with
    linked category names for the admin overview table.
    """
    if not category_rows:
        return []

    category_ids = [category.pk for category, _ in category_rows]
    links = CategoryGoTogetherLink.objects.filter(
        source_category_id__in=category_ids,
        linked_category__is_active=True,
    ).select_related('linked_category').order_by('sort_order', 'linked_category__name')

    links_by_source = {}
    for link in links:
        links_by_source.setdefault(link.source_category_id, []).append(link.linked_category)

    overview = []
    for category, depth in category_rows:
        linked = links_by_source.get(category.pk, [])
        overview.append({
            'category': category,
            'depth': depth,
            'linked_categories': linked,
            'link_count': len(linked),
        })
    return overview
