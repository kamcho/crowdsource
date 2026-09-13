"""Serialize group buys for the shipment product picker UI."""


def group_buy_picker_item(group_buy, *, request=None):
    product = group_buy.product
    image = product.primary_image
    image_url = ''
    if image and image.file:
        image_url = image.file.url
        if request:
            image_url = request.build_absolute_uri(image_url)

    return {
        'id': group_buy.pk,
        'name': product.name,
        'category': product.category.name,
        'pledged_units': group_buy.pledged_units,
        'moq': group_buy.moq,
        'status': group_buy.get_status_display(),
        'image_url': image_url,
    }


def group_buy_picker_items(group_buys, *, request=None):
    return [group_buy_picker_item(gb, request=request) for gb in group_buys]


def filter_group_buys_for_search(group_buys, query: str):
    query = (query or '').strip().lower()
    if not query:
        return group_buys
    filtered = []
    for group_buy in group_buys:
        product = group_buy.product
        haystack = ' '.join([
            product.name,
            product.category.name,
            str(group_buy.pk),
        ]).lower()
        if query in haystack:
            filtered.append(group_buy)
    return filtered
