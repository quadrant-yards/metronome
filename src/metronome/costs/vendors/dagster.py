from __future__ import annotations

import re

from metronome.dateparse import FULL_MONTHS, month_year_to_date
from metronome.costs.models import CostRow

_DATE_OF_ISSUE_RE = re.compile(r"Date of issue\s+([A-Za-z]+) (\d{1,2}), (\d{4})")
_AMOUNT_DUE_RE = re.compile(r"Amount due\s+\$([\d,]+\.\d{2})\s+USD")


def detect(text: str) -> bool:
    return "dagsterlabs.com" in text.lower()


def parse(text: str, source_file: str) -> list[CostRow]:
    issue_match = _DATE_OF_ISSUE_RE.search(text)
    amount_match = _AMOUNT_DUE_RE.search(text)
    if not issue_match or not amount_match:
        raise ValueError(f"could not parse Dagster invoice: {source_file}")

    month_name, _day, year = issue_match.groups()
    metric_date = month_year_to_date(month_name, int(year), FULL_MONTHS)
    metric_value = float(amount_match.group(1).replace(",", ""))

    return [
        CostRow(
            metric_name="Dagster",
            metric_date=metric_date,
            metric_value=metric_value,
            source_file=source_file,
        )
    ]
