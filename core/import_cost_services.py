"""Landed cost and suggested selling price for import batches."""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

from django.conf import settings

from core.import_batch import ImportBatch


def _quantize_money(value: Decimal) -> Decimal:
    return value.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def default_margin_percent() -> Decimal:
    return Decimal(str(getattr(settings, 'DEFAULT_IMPORT_MARGIN_PERCENT', '16')))


def effective_units(batch: ImportBatch) -> int:
    if batch.units_imported:
        return batch.units_imported
    return batch.group_buy.pledged_units or 0


def sum_batch_additional_costs(batch: ImportBatch) -> Decimal:
    return sum(
        (line.amount for line in batch.additional_costs.all()),
        Decimal('0'),
    )


def build_batch_cost_summary(batch: ImportBatch | None) -> dict | None:
    if not batch:
        return None

    units = effective_units(batch)
    supplier_unit = batch.supplier_unit_cost or Decimal('0')
    goods_total = _quantize_money(supplier_unit * units)
    additional_costs = _quantize_money(sum_batch_additional_costs(batch))
    landed_total = _quantize_money(goods_total + additional_costs)
    landed_per_unit = (
        _quantize_money(landed_total / Decimal(units))
        if units
        else Decimal('0')
    )

    margin = batch.target_margin_percent if batch.target_margin_percent is not None else default_margin_percent()
    suggested_unit_price = (
        _quantize_money(landed_per_unit * (Decimal('1') + margin / Decimal('100')))
        if landed_per_unit
        else Decimal('0')
    )
    current_sell = Decimal(batch.group_buy.unit_price)
    margin_if_sold_at_current = Decimal('0')
    if landed_per_unit and current_sell:
        margin_if_sold_at_current = _quantize_money(
            ((current_sell - landed_per_unit) / landed_per_unit) * Decimal('100'),
        )

    return {
        'units': units,
        'supplier_unit_cost': supplier_unit,
        'goods_total': goods_total,
        'additional_costs': additional_costs,
        'landed_total': landed_total,
        'landed_per_unit': landed_per_unit,
        'margin_percent': margin,
        'suggested_unit_price': suggested_unit_price,
        'current_unit_price': current_sell,
        'margin_at_current_price': margin_if_sold_at_current,
    }


def build_shipment_analytics(batch_summaries: list) -> dict:
    """Roll up per-product import batches on one physical shipment."""
    zero = Decimal('0')
    analytics = {
        'product_count': len(batch_summaries),
        'total_units': 0,
        'goods_total': zero,
        'additional_total': zero,
        'landed_total': zero,
        'suggested_revenue': zero,
        'current_revenue': zero,
        'missing_supplier_count': 0,
        'goods_share_percent': 0,
        'additional_share_percent': 0,
        'profit_at_suggested': zero,
        'profit_at_current': zero,
        'margin_on_suggested_revenue': zero,
        'margin_on_current_revenue': zero,
    }
    for row in batch_summaries:
        summary = row.get('summary')
        if not summary:
            continue
        units = int(summary.get('units') or 0)
        analytics['total_units'] += units
        analytics['goods_total'] += summary['goods_total']
        analytics['additional_total'] += summary['additional_costs']
        analytics['landed_total'] += summary['landed_total']
        analytics['suggested_revenue'] += summary['suggested_unit_price'] * units
        analytics['current_revenue'] += summary['current_unit_price'] * units
        if not summary.get('supplier_unit_cost'):
            analytics['missing_supplier_count'] += 1

    landed = analytics['landed_total']
    if landed > 0:
        analytics['goods_share_percent'] = int(
            (analytics['goods_total'] / landed * Decimal('100')).quantize(Decimal('1')),
        )
        analytics['additional_share_percent'] = max(
            0,
            100 - analytics['goods_share_percent'],
        )
        analytics['profit_at_suggested'] = _quantize_money(
            analytics['suggested_revenue'] - landed,
        )
        analytics['profit_at_current'] = _quantize_money(
            analytics['current_revenue'] - landed,
        )
        if analytics['suggested_revenue'] > 0:
            analytics['margin_on_suggested_revenue'] = _quantize_money(
                (analytics['profit_at_suggested'] / analytics['suggested_revenue']) * Decimal('100'),
            )
        if analytics['current_revenue'] > 0:
            analytics['margin_on_current_revenue'] = _quantize_money(
                (analytics['profit_at_current'] / analytics['current_revenue']) * Decimal('100'),
            )
    return analytics
