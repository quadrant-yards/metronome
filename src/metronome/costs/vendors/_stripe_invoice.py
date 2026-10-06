from __future__ import annotations

import calendar
import logging
import re
from datetime import date

from metronome.costs.models import CostRow
from metronome.dateparse import ABBREV_MONTHS, FULL_MONTHS, month_year_to_date

logger = logging.getLogger(__name__)

_DATE_OF_ISSUE_RE = re.compile(r"Date of issue\s+([A-Za-z]+) (\d{1,2}), (\d{4})")
# Prefer the pre-credit "Total" line over "Amount due", which nets out any
# "Applied balance" credit from a prior invoice and would otherwise
# understate what was actually billed for the period. Fall back to
# "Amount due" for invoices that don't print a separate Total line.
_TOTAL_RE = re.compile(r"^Total\s+\$(-?[\d,]+\.\d{2})\s*$", re.MULTILINE)
_AMOUNT_DUE_RE = re.compile(r"Amount due\s+\$(-?[\d,]+\.\d{2})\s+USD")
# Taxed invoices (e.g. Hex after NY sales tax kicked in) print pre-tax line
# items, a "Total excluding tax" line, then the tax and a tax-inclusive Total.
_TOTAL_EXCL_TAX_RE = re.compile(
    r"^Total excluding tax\s+\$(-?[\d,]+\.\d{2})\s*$", re.MULTILINE
)
# A line item's Tax column holds a rate like "8.875%" when the line is taxed.
_TAX_RATE_RE = re.compile(r"\s\d+(?:\.\d+)?%\s")
_LINE_AMOUNT_RE = re.compile(r"\$(-?[\d,]+\.\d{2})\s*$")
_PERIOD_RE = re.compile(
    r"^([A-Za-z]{3,9}) (\d{1,2})(?:, (\d{4}))? ([A-Za-z]{3,9}) (\d{1,2}), (\d{4})\s*$"
)


def _parse_amount(token: str) -> float:
    return float(token.replace(",", ""))


def _period_start(line: str) -> date | None:
    """Parse a Stripe line-item period range like "Dec 1, 2025 Jan 1, 2026"
    or "Sep 23 Oct 23, 2025" (first date's year is implied) into the month
    it bills for. Returns None if the line isn't a period range."""
    match = _PERIOD_RE.match(line.strip())
    if not match:
        return None
    start_month, start_day, start_year, end_month, end_day, end_year = match.groups()
    if start_month not in ABBREV_MONTHS or end_month not in ABBREV_MONTHS:
        return None
    start_month_num = ABBREV_MONTHS[start_month]
    end_month_num = ABBREV_MONTHS[end_month]
    if start_year is not None:
        start_year_int = int(start_year)
    else:
        # No year on the first date means it's implied to match the second
        # date's year, unless the range wraps into a new year (e.g. a
        # "Dec 23 Jan 23, 2026" period, where Dec is actually the prior year).
        start_year_int = int(end_year)
        if start_month_num > end_month_num:
            start_year_int -= 1

    # A subscription anchored on month-end (e.g. after a plan change) labels
    # its period's start as the last calendar day of the PRIOR month --
    # "Feb 28 Mar 31, 2026" is Stripe's way of writing the March cycle, not a
    # charge for February. When the start date is the last day of its month
    # and the range crosses into a new month, it bills for the end month.
    days_in_start_month = calendar.monthrange(start_year_int, start_month_num)[1]
    if start_month_num != end_month_num and int(start_day) == days_in_start_month:
        return month_year_to_date(end_month, int(end_year), ABBREV_MONTHS)

    return month_year_to_date(start_month, start_year_int, ABBREV_MONTHS)


def _line_item_totals(text: str) -> tuple[dict[date, float], dict[date, float]]:
    """Sum pre-tax line-item amounts by billed month. Also returns the taxed
    subset of those amounts by month, so invoice-level tax can be allocated
    to the months whose line items it was charged on."""
    totals: dict[date, float] = {}
    taxable: dict[date, float] = {}
    lines = text.splitlines()
    for current_line, next_line in zip(lines, lines[1:]):
        amount_match = _LINE_AMOUNT_RE.search(current_line.strip())
        if not amount_match:
            continue
        period_start = _period_start(next_line)
        if period_start is None:
            continue
        amount = _parse_amount(amount_match.group(1))
        totals[period_start] = totals.get(period_start, 0.0) + amount
        if _TAX_RATE_RE.search(current_line):
            taxable[period_start] = taxable.get(period_start, 0.0) + amount
    return totals, taxable


def _allocate_tax(
    totals: dict[date, float], taxable: dict[date, float], tax: float
) -> dict[date, float]:
    """Spread invoice-level tax across months pro rata to each month's taxed
    line items (all line items, if none are marked taxed). Rounding residue
    goes to the largest month so the rounded rows still sum to the Total."""
    basis = taxable if sum(taxable.values()) else totals
    basis_total = sum(basis.values())
    if not tax or not basis_total:
        return {month: round(value, 2) for month, value in totals.items()}
    with_tax = {
        month: round(value + tax * basis.get(month, 0.0) / basis_total, 2)
        for month, value in totals.items()
    }
    residue = round(sum(totals.values()) + tax - sum(with_tax.values()), 2)
    if residue:
        largest = max(basis, key=lambda month: basis[month])
        with_tax[largest] = round(with_tax[largest] + residue, 2)
    return with_tax


def parse(text: str, source_file: str, metric_name: str) -> list[CostRow]:
    issue_match = _DATE_OF_ISSUE_RE.search(text)
    total_match = _TOTAL_RE.search(text) or _AMOUNT_DUE_RE.search(text)
    if not issue_match or not total_match:
        raise ValueError(f"could not parse {metric_name} invoice: {source_file}")

    total = _parse_amount(total_match.group(1))
    totals, taxable = _line_item_totals(text)

    if not totals:
        month_name, _day, year = issue_match.groups()
        issue_month = month_year_to_date(month_name, int(year), FULL_MONTHS)
        return [
            CostRow(
                metric_name=metric_name,
                metric_date=issue_month,
                metric_value=total,
                source_file=source_file,
            )
        ]

    line_item_total = round(sum(totals.values()), 2)
    excl_tax_match = _TOTAL_EXCL_TAX_RE.search(text)
    if excl_tax_match and abs(line_item_total - _parse_amount(excl_tax_match.group(1))) <= 0.01:
        totals = _allocate_tax(totals, taxable, round(total - line_item_total, 2))
        line_item_total = round(sum(totals.values()), 2)
    if abs(line_item_total - round(total, 2)) > 0.01:
        logger.warning(
            "%s %s: line items sum to %.2f but Total is %.2f",
            metric_name, source_file, line_item_total, total,
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
