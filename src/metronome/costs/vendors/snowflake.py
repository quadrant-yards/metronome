from __future__ import annotations

import re
from datetime import date

from metronome.dateparse import ABBREV_MONTHS, month_year_to_date
from metronome.costs.models import CostRow

_STATEMENT_DATE_RE = re.compile(r"STATEMENT DATE:\s*(\d{2})/(\d{2})/(\d{4})")
_USAGE_MONTH_RE = re.compile(r"^([A-Za-z]{3})-(\d{4})$")


def detect(text: str) -> bool:
    return "USAGE STATEMENT" in text and "MONTHLY USAGE" in text


def _parse_amount(token: str) -> float:
    token = token.replace(",", "")
    if token.startswith("(") and token.endswith(")"):
        return -float(token[1:-1])
    return float(token)


def _parse_usage_month(token: str) -> date | None:
    match = _USAGE_MONTH_RE.match(token)
    if not match:
        return None
    month_name, year = match.groups()
    return month_year_to_date(month_name, int(year), ABBREV_MONTHS)


def _statement_date(text: str) -> date | None:
    match = _STATEMENT_DATE_RE.search(text)
    if not match:
        return None
    month, day, year = match.groups()
    return date(int(year), int(month), int(day))


def parse(text: str, source_file: str) -> list[CostRow]:
    stmt_date = _statement_date(text)
    overage_totals: dict[date, float] = {}
    months_seen: set[date] = set()

    for line in text.splitlines():
        tokens = line.split()
        if len(tokens) < 4:
            continue
        usage_month = _parse_usage_month(tokens[0])
        if usage_month is None:
            continue
        category = " ".join(tokens[1:-2])
        units_token, total_token = tokens[-2], tokens[-1]
        if not category:
            continue
        try:
            total = _parse_amount(total_token)
        except ValueError:
            continue

        months_seen.add(usage_month)
        if category.endswith("TOTAL") and units_token == "N/A":
            # Pre-summed capacity-drawdown row, not a grand total -- ignored.
            continue
        if category.startswith("OVERAGE-"):
            overage_totals[usage_month] = overage_totals.get(usage_month, 0.0) + total

    return [
        CostRow(
            metric_name="Snowflake",
            metric_date=month,
            metric_value=round(overage_totals.get(month, 0.0), 2),
            source_file=source_file,
            statement_date=stmt_date,
        )
        for month in sorted(months_seen)
    ]
