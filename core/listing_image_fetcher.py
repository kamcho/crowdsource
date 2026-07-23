import json
import logging
import re
import time
from urllib.parse import urlparse

import requests
from django.core.files.base import ContentFile
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)

USER_AGENT = (
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
    '(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'
)
REQUEST_HEADERS = {
    'User-Agent': USER_AGENT,
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.9',
}
IMAGE_REQUEST_HEADERS = {
    **REQUEST_HEADERS,
    'Accept': 'image/avif,image/webp,image/apng,image/*,*/*;q=0.8',
    'Referer': 'https://www.alibaba.com/',
}
MAX_LISTING_IMAGES = 15
CONNECT_TIMEOUT_SECONDS = 15
PAGE_READ_TIMEOUT_SECONDS = 45
IMAGE_READ_TIMEOUT_SECONDS = 90
MAX_IMAGE_BYTES = 15 * 1024 * 1024
MAX_DOWNLOAD_ATTEMPTS = 3
RETRY_BACKOFF_SECONDS = 2


class ListingImageFetchError(Exception):
    pass


def build_listing_session():
    session = requests.Session()
    session.headers.update(REQUEST_HEADERS)
    retry = Retry(
        total=2,
        connect=2,
        read=2,
        backoff_factor=1,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=('GET',),
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount('https://', adapter)
    session.mount('http://', adapter)
    return session


def is_alibaba_listing_url(url):
    if not url:
        return False
    host = (urlparse(url).netloc or '').lower()
    return host.endswith('alibaba.com')


def extract_alibaba_product_id(url):
    match = re.search(r'_(\d+)\.html', url or '')
    return match.group(1) if match else None


def fetch_listing_page_html(url, session=None):
    if not is_alibaba_listing_url(url):
        raise ListingImageFetchError(
            'Only alibaba.com product detail URLs are supported for auto-download.'
        )
    session = session or build_listing_session()
    try:
        response = session.get(
            url,
            timeout=(CONNECT_TIMEOUT_SECONDS, PAGE_READ_TIMEOUT_SECONDS),
            allow_redirects=True,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        raise ListingImageFetchError(f'Could not load listing page: {exc}') from exc

    if len(response.text) < 500:
        raise ListingImageFetchError(
            'Listing page returned very little content — Alibaba may have blocked the request.'
        )
    return response.text


def extract_listing_image_urls(html, max_images=MAX_LISTING_IMAGES):
    candidates = []
    seen = set()

    def add_url(raw_url):
        normalized = normalize_listing_image_url(raw_url)
        if not normalized or normalized in seen:
            return
        if not is_product_gallery_image(normalized):
            return
        seen.add(normalized)
        candidates.append(normalized)

    # Direct alicdn URLs in HTML/JSON.
    for match in re.finditer(
        r'https?://[^"\s<>\\]+?\.alicdn\.com[^"\s<>\\]*?\.(?:jpg|jpeg|png|webp)(?:\?\S*)?',
        html,
        re.IGNORECASE,
    ):
        add_url(match.group(0))

    for match in re.finditer(
        r'//s\.alicdn\.com[^"\s<>\\]*?\.(?:jpg|jpeg|png|webp)(?:\?\S*)?',
        html,
        re.IGNORECASE,
    ):
        add_url('https:' + match.group(0))

    # Common JSON fields on Alibaba product pages.
    json_key_patterns = [
        r'"imageUrlList"\s*:\s*(\[[^\]]+\])',
        r'"images"\s*:\s*(\[[^\]]+\])',
        r'"fullPathImageURI"\s*:\s*"([^"]+)"',
        r'"originalImage"\s*:\s*\{\s*"imageUrl"\s*:\s*"([^"]+)"',
        r'"imageUrl"\s*:\s*"(https?://[^"]+?\.alicdn\.com[^"]+)"',
    ]
    for pattern in json_key_patterns:
        for match in re.finditer(pattern, html, re.IGNORECASE):
            value = match.group(1)
            if value.startswith('['):
                try:
                    items = json.loads(value.replace('\\/', '/'))
                except json.JSONDecodeError:
                    continue
                if isinstance(items, list):
                    for item in items:
                        if isinstance(item, str):
                            add_url(item)
                        elif isinstance(item, dict):
                            for key in ('imageUrl', 'url', 'original', 'src'):
                                if item.get(key):
                                    add_url(item[key])
            else:
                add_url(value)

    return candidates[:max_images]


def normalize_listing_image_url(url):
    if not url:
        return ''
    cleaned = url.strip().strip('"').strip("'").replace('\\/', '/')
    if cleaned.startswith('//'):
        cleaned = 'https:' + cleaned
    cleaned = cleaned.split(' ')[0]
    # Alibaba often serves thumbnails as filename.jpg_350x350.jpg
    cleaned = re.sub(
        r'(\.(?:jpg|jpeg|png|webp))_\d+x\d+\.(?:jpg|jpeg|png|webp)',
        r'\1',
        cleaned,
        flags=re.IGNORECASE,
    )
    # Other size suffixes before the extension.
    cleaned = re.sub(
        r'_\d+x\d+(?=\.(?:jpg|jpeg|png|webp))',
        '',
        cleaned,
        flags=re.IGNORECASE,
    )
    return cleaned


def image_download_candidates(url):
    normalized = normalize_listing_image_url(url)
    if not normalized:
        return []

    candidates = [normalized]
    parsed = urlparse(normalized)
    host = (parsed.netloc or '').lower()
    if host.startswith('img.'):
        alt_host = 's.alicdn.com'
        candidates.append(normalized.replace(f'://{host}', f'://{alt_host}', 1))
    elif host.startswith('s.'):
        alt_host = 'img.alicdn.com'
        candidates.append(normalized.replace(f'://{host}', f'://{alt_host}', 1))

    deduped = []
    seen = set()
    for candidate in candidates:
        if candidate not in seen:
            seen.add(candidate)
            deduped.append(candidate)
    return deduped


def is_product_gallery_image(url):
    lower = url.lower()
    blocked = ('avatar', 'icon', 'logo', 'sprite', 'flag', 'badge', 'emoji')
    if any(token in lower for token in blocked):
        return False
    if re.search(r'_\d+x\d+\.', lower):
        # Skip obvious thumbnails after normalization failed.
        if any(size in lower for size in ('_50x50', '_60x60', '_80x80', '_100x100', '_120x120')):
            return False
    return '.alicdn.com' in lower and re.search(r'\.(?:jpg|jpeg|png|webp)', lower)


def _read_response_content(response):
    chunks = []
    total = 0
    for chunk in response.iter_content(chunk_size=65536):
        if not chunk:
            continue
        total += len(chunk)
        if total > MAX_IMAGE_BYTES:
            raise ListingImageFetchError('Downloaded image is too large.')
        chunks.append(chunk)
    return b''.join(chunks)


def _download_listing_image_once(url, session):
    response = session.get(
        url,
        headers=IMAGE_REQUEST_HEADERS,
        timeout=(CONNECT_TIMEOUT_SECONDS, IMAGE_READ_TIMEOUT_SECONDS),
        stream=True,
    )
    response.raise_for_status()

    content_type = (response.headers.get('content-type') or '').lower()
    if content_type and not content_type.startswith('image/'):
        raise ListingImageFetchError('Downloaded file is not an image.')

    content = _read_response_content(response)
    if len(content) < 1024:
        raise ListingImageFetchError('Downloaded image is too small.')

    extension = guess_extension(url, content_type)
    filename = f'listing-{abs(hash(url)) % 10_000_000}{extension}'
    return ContentFile(content, name=filename)


def _is_retryable_request_error(exc):
    if isinstance(exc, (requests.Timeout, requests.ConnectionError)):
        return True
    message = str(exc).lower()
    return any(token in message for token in ('timed out', 'timeout', 'connection', 'temporarily unavailable'))


def download_listing_image(url, session=None):
    session = session or build_listing_session()
    candidates = image_download_candidates(url)
    if not candidates:
        raise ListingImageFetchError('Invalid image URL.')

    last_error = None
    for candidate in candidates:
        for attempt in range(MAX_DOWNLOAD_ATTEMPTS):
            try:
                return _download_listing_image_once(candidate, session)
            except requests.RequestException as exc:
                last_error = ListingImageFetchError(f'Failed to download image: {exc}')
                if attempt + 1 < MAX_DOWNLOAD_ATTEMPTS and _is_retryable_request_error(exc):
                    logger.warning(
                        'Retrying image download (%s/%s): %s',
                        attempt + 2,
                        MAX_DOWNLOAD_ATTEMPTS,
                        candidate,
                    )
                    time.sleep(RETRY_BACKOFF_SECONDS * (attempt + 1))
                    continue
                break
            except ListingImageFetchError as exc:
                last_error = exc
                break

    raise last_error or ListingImageFetchError('Failed to download image.')


def guess_extension(url, content_type):
    if 'png' in content_type or url.lower().endswith('.png'):
        return '.png'
    if 'webp' in content_type or url.lower().endswith('.webp'):
        return '.webp'
    if 'jpeg' in content_type or url.lower().endswith('.jpeg'):
        return '.jpeg'
    return '.jpg'
