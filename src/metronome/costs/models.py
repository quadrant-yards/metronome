from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class CostRow:
    """One (vendor, month) cost observation.

    `metric_value` and `source_file` are None only for gap-filled rows
    produced by rollup.resolve_monthly() — a month with no source data.
    `statement_date` is set only by the Snowflake parser, where it's used
    to break ties between overlapping cumulative statements (see rollup.py).
    """

    metric_name: str
    metric_date: date
    metric_value: float | None
    source_file: str | None
    statement_date: date | None = None
