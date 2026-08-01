from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

from metronome.metrics.models import MetricRow

logger = logging.getLogger(__name__)

QueryExecutor = Callable[[str], list[tuple]]

_PERIOD_VARS = {"weekly": "week", "monthly": "month"}


def _rows_to_metrics(rows: list[tuple]) -> list[MetricRow]:
    return [
        MetricRow(metric_name=name, metric_date=metric_date, metric_value=float(value))
        for name, metric_date, value in rows
    ]


def run_all(period: str, execute_query: QueryExecutor, sources_dir: Path) -> list[MetricRow]:
    execute_query(f"SET period = '{_PERIOD_VARS[period]}';")

    rows: list[MetricRow] = []
    for sql_file in sorted(sources_dir.glob("*.sql")):
        try:
            rows.extend(_rows_to_metrics(execute_query(sql_file.read_text())))
        except Exception as exc:
            logger.error(
                "failed to run %s for period=%s: %s", sql_file.stem, period, exc, exc_info=True
            )
            continue
    return rows
