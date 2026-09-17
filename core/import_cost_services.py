"""Landed cost and suggested selling price for import batches."""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP, ROUND_DOWN

from django.conf import settings
from django.db import transaction

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


def split_amount_by_unit_weights(total_amount: Decimal, unit_counts: list[int]) -> list[Decimal]:
    """
    Split a USD total across lines in proportion to unit counts.
    Returned amounts sum exactly to total_amount (largest-remainder cents).
    """
    if total_amount <= 0:
        return []
    if not unit_counts:
        return []
    total_units = sum(unit_counts)
    if total_units <= 0:
        raise ValueError('Cannot split cost without positive unit counts on selected products.')

    total_amount = _quantize_money(total_amount)
    shares: list[Decimal] = []
    remainders: list[Decimal] = []
    running = Decimal('0')
    for units in unit_counts:
        exact = total_amount * Decimal(units) / Decimal(total_units)
        floored = exact.quantize(Decimal('0.01'), rounding=ROUND_DOWN)
        shares.append(floored)
        remainders.append(exact - floored)
        running += floored

    cents_left = int((total_amount - running) / Decimal('0.01'))
    if cents_left > 0:
        order = sorted(range(len(unit_counts)), key=lambda i: remainders[i], reverse=True)
        for i in range(cents_left):
            shares[order[i % len(order)]] += Decimal('0.01')

    return [_quantize_money(share) for share in shares]


@transaction.atomic
def apply_shipment_shared_cost_split(
    shipment,
    import_batch_ids: list[int],
    *,
    cost_type: str,
    total_amount: Decimal,
    description: str = '',
) -> dict:
    """
    Record one shared shipment charge and allocate it to import batches by unit share.
    Creates ImportShipmentSharedCost plus ImportBatchAdditionalCost on each batch.
    """
    from core.import_cost import ImportBatchAdditionalCost, ImportShipmentSharedCost

    batches = list(
        ImportBatch.objects.filter(pk__in=import_batch_ids, shipment=shipment)
        .select_related('group_buy')
        .order_by('pk'),
    )
    if not batches:
        raise ValueError('Select at least one product on this shipment.')

    unit_counts = [effective_units(batch) for batch in batches]
    if sum(unit_counts) <= 0:
        raise ValueError(
            'Selected products have no units — set units imported or ensure group buys have pledges.',
        )

    shares = split_amount_by_unit_weights(_quantize_money(total_amount), unit_counts)
    note = (description or '').strip()
    shared = ImportShipmentSharedCost.objects.create(
        shipment=shipment,
        cost_type=cost_type,
        description=note,
        amount=_quantize_money(total_amount),
    )

    allocations = []
    for batch, share in zip(batches, shares):
        line_description = note
        if not line_description:
            line_description = f'Split from shipment shared charge (${shared.amount})'
        ImportBatchAdditionalCost.objects.create(
            import_batch=batch,
            cost_type=cost_type,
            description=line_description[:255],
            amount=share,
        )
        allocations.append({
            'import_batch_id': batch.pk,
            'product_name': batch.group_buy.product.name,
            'units': effective_units(batch),
            'amount': share,
        })

    return {
        'shared_cost_id': shared.pk,
        'total_amount': shared.amount,
        'allocations': allocations,
    }
