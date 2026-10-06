from __future__ import annotations

import calendar
import logging
import re
from collections import defaultdict
from datetime import date

from metronome.dateparse import ABBREV_MONTHS, month_year_to_date
from metronome.costs.models import CostRow

logger = logging.getLogger(__name__)

_INVOICE_DATE_RE = re.compile(r"Invoice Date\s+([A-Za-z]{3}) (\d{1,2}), (\d{4})")
_SUBTOTAL_RE = re.compile(r"SUBTOTAL:\s*\$(-?[\d,]+\.\d{2})")
_TAX_RE = re.compile(r"TAX:\s*\$(-?[\d,]+\.\d{2})")
_INVOICE_TOTAL_RE = re.compile(r"INVOICE TOTAL:\s*\$(-?[\d,]+\.\d{2})")
# A line item is a "DESCRIPTION" line, an "AMOUNT" line (either a bare
# "$X.XX" or a "QTY RATE AMOUNT" line -- the item's own amount is always the
# last dollar figure on it), and a "Mon D, YYYY - Mon D, YYYY" service-period
# line, e.g.:
#   GitHub Copilot Usage
#   95.00 $1.00 $95.00
#   Apr 01, 2026 - Apr 30, 2026
# A GitHub invoice bundles an arrears usage charge for the prior period with
# a forward-billed subscription charge for the next, so -- like the
# Stripe-based Dagster/Hex parser (_stripe_invoice) -- each line item is
# bucketed to its own service-period month instead of lumping the whole
# invoice onto its issue-date month.
_LINE_ITEM_RE = re.compile(
    r"^(GitHub .+)\n"
    r".*\$(-?[\d,]+\.\d{2})\s*\n"
    r"([A-Za-z]{3}) (\d{1,2}), (\d{4}) - ([A-Za-z]{3}) (\d{1,2}), (\d{4})\s*$",
    re.MULTILINE,
)


def detect(text: str) -> bool:
    return "GitHub, Inc." in text


def _parse_amount(token: str) -> float:
    return float(token.replace(",", ""))


def _bucket_month(start_month: str, start_day: str, start_year: str, end_month: str, end_year: str) -> date:
    """Unlike Stripe's shared-year shorthand, GitHub always prints an explicit
    year on both ends of a period -- but the same month-end anchoring rule
    from _stripe_invoice applies: a period like "Aug 31, 2026 - Sep 30, 2026"
    that starts on the last calendar day of its month is really the charge
    for the END month, not the start."""
    start_month_num = ABBREV_MONTHS[start_month]
    end_month_num = ABBREV_MONTHS[end_month]
    start_year_int = int(start_year)
    days_in_start_month = calendar.monthrange(start_year_int, start_month_num)[1]
    if start_month_num != end_month_num and int(start_day) == days_in_start_month:
        return month_year_to_date(end_month, int(end_year), ABBREV_MONTHS)
    return month_year_to_date(start_month, start_year_int, ABBREV_MONTHS)


# Each line item also rolls up into a per-product metric alongside the
# combined "GitHub" total, so seat spend and Copilot spend can be tracked
# separately. Proration / Proration Credit lines are seat-count changes and
# belong with the seat subscription they adjust.
_PRODUCT_PREFIXES = (
    ("GitHub Business Cloud", "GitHub Seats"),
    ("GitHub Copilot", "GitHub Copilot"),
)
_OTHER_PRODUCT = "GitHub Other"


def _product_metric(description: str) -> str:
    for prefix, metric_name in _PRODUCT_PREFIXES:
        if description.startswith(prefix):
            return metric_name
    logger.warning("unrecognized GitHub line item %r; reporting it as %s", description, _OTHER_PRODUCT)
    return _OTHER_PRODUCT


def _line_item_totals(text: str) -> dict[tuple[str, date], float]:
    """Pre-tax amounts keyed by (product metric name, service-period month)."""
    totals: dict[tuple[str, date], float] = defaultdict(float)
    for match in _LINE_ITEM_RE.finditer(text):
        description, amount, start_month, start_day, start_year, end_month, end_day, end_year = match.groups()
        month = _bucket_month(start_month, start_day, start_year, end_month, end_year)
        product = _product_metric(description)
        value = _parse_amount(amount)
        totals[(product, month)] += value
        logger.debug(
            "line item %r amount=%.2f period=%s %s, %s - %s %s, %s -> bucketed to %s as %s",
            description, value, start_month, start_day, start_year, end_month, end_day, end_year, month, product,
        )
    return dict(totals)


def parse(text: str, source_file: str) -> list[CostRow]:
    date_match = _INVOICE_DATE_RE.search(text)
    total_match = _INVOICE_TOTAL_RE.search(text)
    if not date_match or not total_match:
        raise ValueError(f"could not parse GitHub invoice: {source_file}")

    total = _parse_amount(total_match.group(1))
    line_item_totals = _line_item_totals(text)

    if not line_item_totals:
        month_name, _day, year = date_match.groups()
        metric_date = month_year_to_date(month_name, int(year), ABBREV_MONTHS)
        logger.debug(
            "%s: no line items found; using invoice date %s %s -> metric_date=%s",
            source_file, month_name, year, metric_date,
        )
        return [CostRow(metric_name="GitHub", metric_date=metric_date, metric_value=total, source_file=source_file)]

    month_totals: dict[date, float] = defaultdict(float)
    for (_product, month), amount in line_item_totals.items():
        month_totals[month] += amount

    line_item_subtotal = round(sum(month_totals.values()), 2)
    subtotal_match = _SUBTOTAL_RE.search(text)
    subtotal = _parse_amount(subtotal_match.group(1)) if subtotal_match else line_item_subtotal
    if subtotal_match and abs(line_item_subtotal - round(subtotal, 2)) > 0.01:
        logger.warning(
            "GitHub %s: line items sum to %.2f but SUBTOTAL is %.2f",
            source_file, line_item_subtotal, subtotal,
        )

    tax_match = _TAX_RE.search(text)
    tax = _parse_amount(tax_match.group(1)) if tax_match else 0.0

    # Tax is billed once per invoice, not per line item, so split it across
    # each bucket in proportion to that bucket's share of the pre-tax subtotal.
    def with_tax(amount: float) -> float:
        return round(amount + (tax * (amount / subtotal) if subtotal else 0.0), 2)

    rows = [
        CostRow(metric_name="GitHub", metric_date=month, metric_value=with_tax(amount), source_file=source_file)
        for month, amount in sorted(month_totals.items())
    ]
    product_rows = [
        CostRow(metric_name=product, metric_date=month, metric_value=with_tax(amount), source_file=source_file)
        for (product, month), amount in sorted(line_item_totals.items())
    ]

    rows_total = round(sum(r.metric_value for r in rows), 2)
    if abs(rows_total - round(total, 2)) > 0.01:
        logger.warning(
            "GitHub %s: split rows sum to %.2f but INVOICE TOTAL is %.2f",
            source_file, rows_total, total,
        )

    return rows + product_rows
