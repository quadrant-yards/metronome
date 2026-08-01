from __future__ import annotations

import re

from metronome.dateparse import FULL_MONTHS, month_year_to_date
from metronome.costs.models import CostRow

_COVERING_RE = re.compile(r"Covering ([A-Za-z]+) (\d{4})")
# Anchor-free on purpose -- see Background note above. Matches "total"
# only when immediately followed (whitespace only) by a currency marker,
# which naturally excludes "Total Before ..." / "Total Price ...".
_TOTAL_RE = re.compile(r"(?i)\btotal\s+(?:usd\s*|\$)\s*([\d,]+\.\d{2})")


def detect(text: str) -> bool:
    return "DOIT INTERNATION" in text.upper()


def parse(text: str, source_file: str) -> list[CostRow]:
    covering_match = _COVERING_RE.search(text)
    total_matches = _TOTAL_RE.findall(text)
    if not covering_match or not total_matches:
        raise ValueError(f"could not parse GCP/DoiT invoice: {source_file}")

    month_name, year = covering_match.groups()
    metric_date = month_year_to_date(month_name, int(year), FULL_MONTHS)
    metric_value = float(total_matches[-1].replace(",", ""))

    return [
        CostRow(
            metric_name="GCP",
            metric_date=metric_date,
            metric_value=metric_value,
            source_file=source_file,
        )
    ]
