"""Public media URLs for WhatsApp Cloud API image messages."""

from __future__ import annotations

import io
import logging
import os
from urllib.parse import urlparse

from django.conf import settings

from core.product_file import ProductFile

logger = logging.getLogger('crowdsource.whatsapp')

WHATSAPP_IMAGE_EXTENSIONS = frozenset({'jpg', 'jpeg', 'png'})


def get_whatsapp_public_base_url() -> str:
    explicit = getattr(settings, 'WHATSAPP_PUBLIC_BASE_URL', '').strip().rstrip('/')
    if explicit:
        return explicit
    return f"{settings.SITE_PROTOCOL}://{settings.SITE_DOMAIN}".rstrip('/')


def absolute_whatsapp_media_url(relative_url: str) -> str:
    return f"{get_whatsapp_public_base_url()}/{relative_url.lstrip('/')}"


def is_whatsapp_reachable_url(url: str) -> bool:
    parsed = urlparse(url)
    host = (parsed.hostname or '').lower()
    if parsed.scheme != 'https':
        return False
    if host in {'localhost', '127.0.0.1', '0.0.0.0'}:
        return False
    if host.endswith('.local'):
        return False
    return bool(host)


def whatsapp_image_extension(filename: str) -> str:
    return os.path.splitext(filename or '')[1].lstrip('.').lower()


def is_whatsapp_compatible_image_file(product_file: ProductFile) -> bool:
    if not product_file or not product_file.is_image or not product_file.file:
        return False
    return whatsapp_image_extension(product_file.file.name) in WHATSAPP_IMAGE_EXTENSIONS


def get_whatsapp_product_image(product):
    """Return the best JPG/PNG image for WhatsApp (Meta rejects AVIF/WebP/GIF)."""
    if not product:
        return None

    product_files = list(
        product.product_files.filter(media_type=ProductFile.MediaType.IMAGE).order_by(
            '-is_primary',
            'sort_order',
            'created_at',
        ),
    )
    for product_file in product_files:
        if is_whatsapp_compatible_image_file(product_file):
            return product_file

    primary = product.primary_image
    if is_whatsapp_compatible_image_file(primary):
        return primary
    return None


def get_whatsapp_product_image_source(product):
    """Return any product image file suitable for conversion/upload."""
    if not product:
        return None
    image = product.primary_image
    if image and image.file:
        return image
    return product.product_files.filter(media_type=ProductFile.MediaType.IMAGE).first()


def render_product_image_jpeg(product) -> bytes | None:
    """Return JPEG bytes for WhatsApp upload (converts AVIF/WebP/etc. when needed)."""
    image = get_whatsapp_product_image_source(product)
    if not image or not image.file:
        return None

    extension = whatsapp_image_extension(image.file.name)
    if extension in WHATSAPP_IMAGE_EXTENSIONS:
        with image.file.open('rb') as handle:
            return handle.read()

    try:
        from PIL import Image
    except ImportError:
        logger.warning('Pillow is required to convert product images for WhatsApp')
        return None

    try:
        with image.file.open('rb') as handle:
            img = Image.open(handle)
            img = img.convert('RGB')
            buffer = io.BytesIO()
            img.save(buffer, format='JPEG', quality=85)
            return buffer.getvalue()
    except Exception:
        logger.exception('Failed to convert product #%s image for WhatsApp', product.pk)
        return None
