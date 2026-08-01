from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date

from metronome.costs.models import CostRow

logger = logging.getLogger(__name__)


def _next_month(current: date) -> date:
    if current.month == 12:
        return date(current.year + 1, 1, 1)
    return date(current.year, current.month + 1, 1)


def _month_range(start: date, end: date) -> list[date]:
    months = []
    current = start
    while current <= end:
        months.append(current)
        current = _next_month(current)
    return months


def _resolve_group(
    vendor: str, month: date, group: list[CostRow], sum_on_collision: frozenset[str]
) -> CostRow:
    if len(group) == 1:
        return group[0]

    distinct_values = {round(r.metric_value, 2) for r in group}

    if vendor in sum_on_collision:
        total = sum(r.metric_value for r in group)
        return CostRow(
            metric_name=vendor,
            metric_date=month,
            metric_value=round(total, 2),
            source_file="; ".join(r.source_file for r in group),
        )

    with_statement_date = [r for r in group if r.statement_date is not None]
    if with_statement_date:
        best = max(with_statement_date, key=lambda r: r.statement_date)
        if len(distinct_values) > 1:
            logger.warning(
                "%s %s has conflicting values across statements %s; using %s (latest statement_date)",
                vendor, month.isoformat(), [r.source_file for r in group], best.source_file,
            )
        return best

    if len(distinct_values) > 1:
        logger.warning(
            "%s %s has %d unexpected source files with differing values %s; keeping first encountered: %s",
            vendor, month.isoformat(), len(group), [r.source_file for r in group], group[0].source_file,
        )
    else:
        logger.warning(
            "%s %s has %d unexpected source files mapping to the same month with matching values %s; "
            "keeping first encountered: %s",
            vendor, month.isoformat(), len(group), [r.source_file for r in group], group[0].source_file,
        )
    return group[0]


def resolve_monthly(
    rows: list[CostRow],
    sum_on_collision: frozenset[str] = frozenset(),
) -> list[CostRow]:
    """Collapse raw per-file rows into one row per (vendor, month), then
    gap-fill every vendor's month range with NULL rows for missing months."""
    grouped: dict[tuple[str, date], list[CostRow]] = defaultdict(list)
    for row in rows:
        grouped[(row.metric_name, row.metric_date)].append(row)

    resolved: dict[tuple[str, date], CostRow] = {
        key: _resolve_group(key[0], key[1], group, sum_on_collision) for key, group in grouped.items()
    }

    output: list[CostRow] = []
    vendors = sorted({vendor for vendor, _ in resolved})
    for vendor in vendors:
        vendor_months = sorted(month for (v, month) in resolved if v == vendor)
        for month in _month_range(vendor_months[0], vendor_months[-1]):
            if (vendor, month) in resolved:
                output.append(resolved[(vendor, month)])
            else:
                output.append(CostRow(metric_name=vendor, metric_date=month, metric_value=None, source_file=None))
    return output
