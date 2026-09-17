"""Parse pasted Alibaba-style order lines and match to shipment import batches."""

from __future__ import annotations

import html
import json
import logging
import re
from decimal import Decimal, InvalidOperation
from difflib import SequenceMatcher

from django.conf import settings

logger = logging.getLogger(__name__)

_LINE_TOTAL_RE = re.compile(r'^USD\s+([\d.]+)\s*$', re.I)
_UNIT_PRICE_RE = re.compile(r'USD\s+([\d.]+)\s*/\s*Pieces', re.I)
_QTY_RE = re.compile(r'^[\d.]+$')


def _to_decimal(value) -> Decimal | None:
    if value is None or value == '':
        return None
    try:
        return Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        return None


def _normalize_title(text: str) -> str:
    text = html.unescape(text or '')
    text = re.sub(r'[^\w\s]', ' ', text.lower())
    return ' '.join(text.split())


def _merge_supplier_paste_blocks(text: str) -> list[str]:
    """Blank lines often sit between title and '-' — merge those fragments."""
    chunks = [chunk.strip() for chunk in re.split(r'\n\s*\n+', text) if chunk.strip()]
    merged: list[str] = []
    for chunk in chunks:
        if chunk.startswith('-') and merged:
            merged[-1] = f'{merged[-1]}\n\n{chunk}'
        else:
            merged.append(chunk)
    return merged


def _parse_supplier_block(block: str) -> dict | None:
    parts = [line.strip() for line in block.splitlines() if line.strip()]
    if len(parts) < 3:
        return None

    title_lines = []
    idx = 0
    while idx < len(parts) and parts[idx] != '-' and not _UNIT_PRICE_RE.search(parts[idx]):
        if not _LINE_TOTAL_RE.match(parts[idx]) and not (
            _QTY_RE.match(parts[idx]) and idx > 0 and _UNIT_PRICE_RE.search(parts[idx - 1])
        ):
            title_lines.append(parts[idx])
        idx += 1
    if not title_lines:
        return None
    title = ' '.join(title_lines)

    unit_price = None
    quantity = None
    line_total = None
    for part in parts[idx:]:
        if part == '-':
            continue
        unit_match = _UNIT_PRICE_RE.search(part)
        if unit_match:
            unit_price = _to_decimal(unit_match.group(1))
            continue
        total_match = _LINE_TOTAL_RE.match(part)
        if total_match:
            line_total = _to_decimal(total_match.group(1))
            continue
        if _QTY_RE.match(part) and quantity is None:
            quantity = _to_decimal(part)

    if unit_price is None and quantity and line_total and quantity > 0:
        unit_price = (line_total / quantity).quantize(Decimal('0.0001'))

    if title and unit_price is not None and quantity is not None:
        return {
            'title': title[:500],
            'supplier_unit_cost': unit_price,
            'units': int(quantity),
            'line_total': line_total,
        }
    return None


def parse_supplier_order_paste_regex(raw: str) -> list[dict]:
    """Parse blocks: title, -, USD x /Pieces, qty, USD total."""
    text = html.unescape(raw or '').strip()
    if not text:
        return []

    rows = []
    for block in _merge_supplier_paste_blocks(text):
        parsed = _parse_supplier_block(block)
        if parsed:
            rows.append(parsed)
    return rows


def parse_supplier_order_paste_ai(raw: str) -> list[dict]:
    from core.openai_product_import import is_openai_configured

    if not is_openai_configured():
        raise RuntimeError('OpenAI is not configured. Set OPENAI_API_KEY in your environment.')

    from openai import OpenAI

    prompt = """Extract order lines from pasted wholesale supplier text (Alibaba cart, invoice, etc.).
Return JSON: {"lines": [{"title": "product title", "supplier_unit_cost": "1.38", "units": 4, "line_total": "5.52"}]}
- supplier_unit_cost and line_total are USD decimal strings without $.
- units is integer piece count.
- Skip headers and non-product lines.
- Decode HTML entities in titles (e.g. &#39; -> ')."""

    client = OpenAI(api_key=settings.OPENAI_API_KEY)
    response = client.chat.completions.create(
        model=getattr(settings, 'OPENAI_MODEL', 'gpt-4o-mini'),
        temperature=0.1,
        response_format={'type': 'json_object'},
        messages=[
            {'role': 'system', 'content': prompt},
            {'role': 'user', 'content': raw[:50000]},
        ],
    )
    payload = json.loads(response.choices[0].message.content or '{}')
    rows = []
    for item in payload.get('lines', []):
        unit = _to_decimal(item.get('supplier_unit_cost'))
        units = item.get('units')
        try:
            units = int(units)
        except (TypeError, ValueError):
            units = None
        if not item.get('title') or unit is None or not units:
            continue
        rows.append({
            'title': html.unescape(str(item['title']))[:500],
            'supplier_unit_cost': unit,
            'units': units,
            'line_total': _to_decimal(item.get('line_total')),
        })
    return rows


def parse_supplier_order_paste(raw: str, *, use_ai: bool = True) -> list[dict]:
    rows = parse_supplier_order_paste_regex(raw)
    if rows:
        return rows
    if use_ai:
        return parse_supplier_order_paste_ai(raw)
    return []


def match_parsed_lines_to_batches(parsed_rows: list[dict], batches) -> list[dict]:
    """Attach import_batch_id when product name fuzzy-matches parsed title."""
    batch_list = list(batches)
    enriched = []
    for row in parsed_rows:
        best_batch = None
        best_score = 0.0
        norm_title = _normalize_title(row['title'])
        for batch in batch_list:
            product_name = batch.group_buy.product.name
            norm_product = _normalize_title(product_name)
            score = SequenceMatcher(None, norm_title, norm_product).ratio()
            if norm_product and norm_product in norm_title:
                score = max(score, 0.72)
            if norm_title and norm_title in norm_product:
                score = max(score, 0.68)
            title_tokens = set(norm_title.split())
            product_tokens = set(norm_product.split())
            if product_tokens:
                overlap = len(title_tokens & product_tokens) / len(product_tokens)
                score = max(score, overlap * 0.85)
            if score > best_score:
                best_score = score
                best_batch = batch

        enriched.append({
            **row,
            'import_batch_id': best_batch.pk if best_batch and best_score >= 0.45 else None,
            'matched_product_name': (
                best_batch.group_buy.product.name if best_batch and best_score >= 0.45 else ''
            ),
            'match_score': round(best_score, 2),
        })
    return enriched


def serialize_supplier_paste_rows(rows: list[dict]) -> list[dict]:
    """JSON/session-safe dicts for preview and apply step."""
    out = []
    for row in rows:
        line_total = row.get('line_total')
        out.append({
            'title': row['title'],
            'supplier_unit_cost': str(row['supplier_unit_cost']),
            'units': row['units'],
            'line_total': str(line_total) if line_total is not None else None,
            'import_batch_id': row.get('import_batch_id'),
            'matched_product_name': row.get('matched_product_name') or '',
            'match_score': row.get('match_score', 0),
        })
    return out


def apply_parsed_costing_to_batches(matched_rows: list[dict], shipment) -> int:
    """Update supplier_unit_cost and units_imported on selected batches. Returns count updated."""
    updated = 0
    for row in matched_rows:
        batch_id = row.get('import_batch_id')
        if not batch_id:
            continue
        from core.import_batch import ImportBatch

        batch = ImportBatch.objects.filter(pk=batch_id, shipment=shipment).first()
        if not batch:
            continue
        unit = row['supplier_unit_cost']
        if unit is not None:
            unit = unit.quantize(Decimal('0.01'))
        batch.supplier_unit_cost = unit
        batch.units_imported = row['units']
        batch.save(update_fields=['supplier_unit_cost', 'units_imported', 'updated_at'])
        updated += 1
    return updated
