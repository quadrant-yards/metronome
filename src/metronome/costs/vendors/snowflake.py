from __future__ import annotations

import calendar
import re
from datetime import date

from metronome.dateparse import ABBREV_MONTHS, FULL_MONTHS, month_year_to_date
from metronome.costs.models import CostRow

_STATEMENT_DATE_RE = re.compile(r"STATEMENT DATE:\s*(\d{2})/(\d{2})/(\d{4})")
_USAGE_MONTH_RE = re.compile(r"^([A-Za-z]{3})-(\d{4})$")

# Snowflake redesigned its statement starting Sep-2026: one month per PDF,
# the month comes from a "STATEMENT PERIOD" header instead of a per-line
# "Aug-2026" prefix, and long category names wrap around the numbers line:
#   OVERAGE-COMPUTE 653.843 Credits Usage 1,307.69
#   OVERAGE-ADJ FOR INCL
#   -27.916 Credits Adjustment -55.84
#   CLOUD SERVICES
_PERIOD_RE = re.compile(
    r"STATEMENT PERIOD.*\n.*?\b(" + "|".join(FULL_MONTHS) + r") (\d{4})\b"
)
_CHARGE_LINE_RE = re.compile(
    r"^(?P<head>.*?)\s*-?[\d,]*\.?\d+ .+? (?:Usage|Adjustment) (?P<total>-?[\d,]+\.\d{2})$"
)


def _is_legacy(text: str) -> bool:
    return "USAGE STATEMENT" in text and "MONTHLY USAGE" in text


def _is_redesigned(text: str) -> bool:
    return "STATEMENT PERIOD" in text and "Monthly Usage Details" in text


def detect(text: str) -> bool:
    return _is_legacy(text) or _is_redesigned(text)


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


def _parse_redesigned(text: str, source_file: str) -> list[CostRow]:
    period_match = _PERIOD_RE.search(text)
    if not period_match:
        raise ValueError(f"could not find statement period in Snowflake statement: {source_file}")
    month_name, year = period_match.groups()
    usage_month = month_year_to_date(month_name, int(year), FULL_MONTHS)
    last_day = calendar.monthrange(usage_month.year, usage_month.month)[1]

    lines = text.splitlines()
    overage_total = 0.0
    charge_lines = 0
    for i, line in enumerate(lines):
        match = _CHARGE_LINE_RE.match(line)
        if not match:
            continue
        charge_lines += 1
        # A wrapped category starts on the line above the numbers line.
        head = match.group("head") or (lines[i - 1] if i > 0 else "")
        if head.startswith("OVERAGE-"):
            overage_total += _parse_amount(match.group("total"))
    # No charge lines at all means the layout drifted again -- fail loudly
    # rather than report a silent $0 month.
    if not charge_lines:
        raise ValueError(f"no charge lines found in Snowflake statement: {source_file}")

    return [
        CostRow(
            metric_name="Snowflake",
            metric_date=usage_month,
            metric_value=round(overage_total, 2),
            source_file=source_file,
            statement_date=usage_month.replace(day=last_day),
        )
    ]


def parse(text: str, source_file: str) -> list[CostRow]:
    if not _is_legacy(text):
        return _parse_redesigned(text, source_file)

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
