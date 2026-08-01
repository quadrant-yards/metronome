from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class MetricRow:
    metric_name: str
    metric_date: date
    metric_value: float
