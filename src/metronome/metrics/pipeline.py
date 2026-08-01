from __future__ import annotations

import logging
from pathlib import Path

import duckdb

from metronome.metrics import store
from metronome.metrics.models import MetricRow
from metronome.metrics.sql_runner import QueryExecutor, run_all

logger = logging.getLogger(__name__)

_TABLES = {"weekly": "product_weekly", "monthly": "product_monthly"}
_WINDOW_UNITS = {"weekly": "weeks", "monthly": "months"}
_COLUMNS = [("metric_name", "VARCHAR"), ("metric_date", "DATE"), ("metric_value", "DOUBLE")]


def write_outputs(
    rows: list[MetricRow],
    period: str,
    db_path: Path,
    csv_path: Path,
    csv_export_weeks: int = 12,
    csv_export_months: int = 12,
) -> None:
    table = _TABLES[period]
    con = duckdb.connect(str(db_path))
    try:
        con.execute("BEGIN TRANSACTION")
        try:
            store.write_upsert(
                con, table, _COLUMNS,
                key_columns=["metric_name", "metric_date"],
                rows=[(r.metric_name, r.metric_date, r.metric_value) for r in rows],
            )

            anchor = con.execute(f"SELECT MAX(metric_date) FROM {table}").fetchone()[0]
            select = (
                f"SELECT metric_name, metric_date, metric_value FROM {table} "
                f"WHERE metric_date >= ? ORDER BY metric_date, metric_name"
            )
            if anchor is not None:
                window_count = csv_export_months if period == "monthly" else csv_export_weeks
                csv_start = store.trailing_window_start(anchor, window_count, _WINDOW_UNITS[period])
                store.export_csv(con, select, [csv_start], csv_path)
            else:
                store.export_csv(
                    con,
                    f"SELECT metric_name, metric_date, metric_value FROM {table} "
                    f"ORDER BY metric_date, metric_name",
                    [],
                    csv_path,
                )
        except Exception:
            con.execute("ROLLBACK")
            raise
        else:
            con.execute("COMMIT")
    finally:
        con.close()


def run(
    period: str,
    execute_query: QueryExecutor,
    db_path: Path,
    csv_path: Path,
    sources_dir: Path,
    csv_export_weeks: int = 12,
    csv_export_months: int = 12,
) -> None:
    rows = run_all(period, execute_query, sources_dir)
    write_outputs(rows, period, db_path, csv_path, csv_export_weeks, csv_export_months)
    logger.info("wrote %d rows to %s table for period=%s", len(rows), _TABLES[period], period)
