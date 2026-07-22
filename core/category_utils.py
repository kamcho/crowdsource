def build_category_tree(categories):
    """Return categories as (category, depth) rows in Alibaba-style tree order."""
    by_parent = {}
    for category in categories:
        by_parent.setdefault(category.parent_id, []).append(category)

    for siblings in by_parent.values():
        siblings.sort(key=lambda item: item.name.lower())

    def walk(parent_id=None, depth=0):
        for category in by_parent.get(parent_id, []):
            yield category, depth
            yield from walk(category.id, depth + 1)

    return list(walk())


def build_category_groups(categories):
    """Return root categories with mid-level columns and leaf children."""
    by_parent = {}
    for category in categories:
        by_parent.setdefault(category.parent_id, []).append(category)

    for siblings in by_parent.values():
        siblings.sort(key=lambda item: item.name.lower())

    groups = []
    for root in by_parent.get(None, []):
        columns = []
        for mid in by_parent.get(root.id, []):
            columns.append({
                'category': mid,
                'children': by_parent.get(mid.id, []),
            })
        groups.append({'root': root, 'columns': columns})

    return groups


def build_category_nav_tree(categories):
    """Return nested category tree for the browse drawer."""
    by_parent = {}
    for category in categories:
        by_parent.setdefault(category.parent_id, []).append(category)

    for siblings in by_parent.values():
        siblings.sort(key=lambda item: item.name.lower())

    def build_node(category):
        children = by_parent.get(category.id, [])
        return {
            'id': category.id,
            'name': category.name,
            'slug': category.slug,
            'children': [build_node(child) for child in children],
        }

    return [build_node(root) for root in by_parent.get(None, [])]


def build_category_image_map(categories):
    """Map category ids to a representative product image URL."""
    from core.models import Product

    by_id = {category.id: category for category in categories}
    image_map = {}

    products = Product.objects.filter(
        is_active=True,
        category_id__in=by_id.keys(),
    ).prefetch_related('files').order_by('category_id', 'id')

    for product in products:
        category_id = product.category_id
        if category_id in image_map:
            continue
        primary = product.primary_image
        if primary:
            image_map[category_id] = primary.file.url

    def image_for(category_id):
        if category_id in image_map:
            return image_map[category_id]
        category = by_id.get(category_id)
        if not category or not category.parent_id:
            return None
        return image_for(category.parent_id)

    return {category_id: image_for(category_id) for category_id in by_id}


def category_depth_map(categories):
    by_id = {category.id: category for category in categories}
    depths = {}

    def depth_for(category):
        if category.id in depths:
            return depths[category.id]
        if category.parent_id is None:
            depths[category.id] = 0
        else:
            depths[category.id] = depth_for(by_id[category.parent_id]) + 1
        return depths[category.id]

    for category in categories:
        depth_for(category)
    return depths
