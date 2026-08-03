from __future__ import annotations

import logging
import re
from datetime import date

from metronome.costs.models import CostRow
from metronome.dateparse import ABBREV_MONTHS, FULL_MONTHS, month_year_to_date

logger = logging.getLogger(__name__)

_DATE_OF_ISSUE_RE = re.compile(r"Date of issue\s+([A-Za-z]+) (\d{1,2}), (\d{4})")
_AMOUNT_DUE_RE = re.compile(r"Amount due\s+\$(-?[\d,]+\.\d{2})\s+USD")
_LINE_AMOUNT_RE = re.compile(r"\$(-?[\d,]+\.\d{2})\s*$")
_PERIOD_RE = re.compile(
    r"^([A-Za-z]{3,9}) (\d{1,2})(?:, (\d{4}))? ([A-Za-z]{3,9}) (\d{1,2}), (\d{4})\s*$"
)


def _parse_amount(token: str) -> float:
    return float(token.replace(",", ""))


def _period_start(line: str) -> date | None:
    """Parse a Stripe line-item period range like "Dec 1, 2025 Jan 1, 2026"
    or "Sep 23 Oct 23, 2025" (first date's year is implied) into its start
    month. Returns None if the line isn't a period range."""
    match = _PERIOD_RE.match(line.strip())
    if not match:
        return None
    start_month, _start_day, start_year, end_month, _end_day, end_year = match.groups()
    if start_month not in ABBREV_MONTHS or end_month not in ABBREV_MONTHS:
        return None
    if start_year is not None:
        start_year_int = int(start_year)
    else:
        # No year on the first date means it's implied to match the second
        # date's year, unless the range wraps into a new year (e.g. a
        # "Dec 23 Jan 23, 2026" period, where Dec is actually the prior year).
        start_year_int = int(end_year)
        if ABBREV_MONTHS[start_month] > ABBREV_MONTHS[end_month]:
            start_year_int -= 1
    return month_year_to_date(start_month, start_year_int, ABBREV_MONTHS)


def _line_item_totals(text: str) -> dict[date, float]:
    totals: dict[date, float] = {}
    lines = text.splitlines()
    for current_line, next_line in zip(lines, lines[1:]):
        amount_match = _LINE_AMOUNT_RE.search(current_line.strip())
        if not amount_match:
            continue
        period_start = _period_start(next_line)
        if period_start is None:
            continue
        totals[period_start] = totals.get(period_start, 0.0) + _parse_amount(amount_match.group(1))
    return totals


def parse(text: str, source_file: str, metric_name: str) -> list[CostRow]:
    issue_match = _DATE_OF_ISSUE_RE.search(text)
    amount_match = _AMOUNT_DUE_RE.search(text)
    if not issue_match or not amount_match:
        raise ValueError(f"could not parse {metric_name} invoice: {source_file}")

    amount_due = _parse_amount(amount_match.group(1))
    totals = _line_item_totals(text)

    if not totals:
        month_name, _day, year = issue_match.groups()
        issue_month = month_year_to_date(month_name, int(year), FULL_MONTHS)
        return [
            CostRow(
                metric_name=metric_name,
                metric_date=issue_month,
                metric_value=amount_due,
                source_file=source_file,
            )
        ]

    line_item_total = round(sum(totals.values()), 2)
    if abs(line_item_total - round(amount_due, 2)) > 0.01:
        logger.warning(
            "%s %s: line items sum to %.2f but Amount due is %.2f",
            metric_name, source_file, line_item_total, amount_due,
        )

    return [
        CostRow(
            metric_name=metric_name,
            metric_date=month,
            metric_value=round(value, 2),
            source_file=source_file,
        )
        for month, value in sorted(totals.items())
    ]
