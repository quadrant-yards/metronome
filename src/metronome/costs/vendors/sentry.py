from __future__ import annotations

import re

from metronome.dateparse import ABBREV_MONTHS, month_year_to_date
from metronome.costs.models import CostRow

_INVOICE_DATE_RE = re.compile(r"Date:\s*(\d{1,2}) ([A-Za-z]{3}) (\d{4})")
_TOTAL_RE = re.compile(r"Total \$([\d,]+\.\d{2}) USD")


def detect(text: str) -> bool:
    return "support@sentry.io" in text


def parse(text: str, source_file: str) -> list[CostRow]:
    date_match = _INVOICE_DATE_RE.search(text)
    total_match = _TOTAL_RE.search(text)
    if not date_match or not total_match:
        raise ValueError(f"could not parse Sentry invoice: {source_file}")

    _day, month_name, year = date_match.groups()
    metric_date = month_year_to_date(month_name, int(year), ABBREV_MONTHS)
    metric_value = float(total_match.group(1).replace(",", ""))

    return [
        CostRow(
            metric_name="Sentry",
            metric_date=metric_date,
            metric_value=metric_value,
            source_file=source_file,
        )
    ]
