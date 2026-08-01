from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Callable
from datetime import date
from pathlib import Path
from types import ModuleType

import duckdb

from metronome.costs import vendors
from metronome.costs.models import CostRow
from metronome.costs.pdf_text import extract_text
from metronome.costs.rollup import resolve_monthly
from metronome.metrics import store

logger = logging.getLogger(__name__)

TextExtractor = Callable[[Path], str]

_RAW_COLUMNS = [
    ("metric_name", "VARCHAR"),
    ("metric_date", "DATE"),
    ("metric_value", "DOUBLE"),
    ("source_file", "VARCHAR"),
]
_MONTHLY_COLUMNS = [("metric_name", "VARCHAR"), ("metric_date", "DATE"), ("metric_value", "DOUBLE")]


def parse_all(
    downloads_dir: Path,
    text_extractor: TextExtractor = extract_text,
    vendor_modules: list[ModuleType] | None = None,
) -> list[CostRow]:
    vendor_modules = vendor_modules if vendor_modules is not None else vendors.ALL
    rows: list[CostRow] = []
    for pdf_path in sorted(downloads_dir.glob("*.pdf")):
        try:
            text = text_extractor(pdf_path)
            matched = [module for module in vendor_modules if module.detect(text)]
            if not matched:
                logger.warning("no vendor matched %s; skipping", pdf_path.name)
                continue
            if len(matched) > 1:
                logger.warning(
                    "multiple vendors matched %s (%s); using %s",
                    pdf_path.name, [m.__name__ for m in matched], matched[0].__name__,
                )
            rows.extend(matched[0].parse(text, pdf_path.name))
        except Exception as exc:
            logger.error("failed to parse %s: %s", pdf_path.name, exc, exc_info=True)
            continue
    return rows


def _read_previous_source_files(db_path: Path) -> dict[str, set[str]]:
    if not db_path.exists():
        return {}
    previous: dict[str, set[str]] = defaultdict(set)
    con = duckdb.connect(str(db_path), read_only=True)
    try:
        rows = con.execute("SELECT DISTINCT metric_name, source_file FROM raw_costs").fetchall()
        for metric_name, source_file in rows:
            previous[metric_name].add(source_file)
    except duckdb.CatalogException:
        pass
    finally:
        con.close()
    return dict(previous)


def count_new_rows(raw_rows: list[CostRow], previous: dict[str, set[str]]) -> dict[str, int]:
    counts: dict[str, int] = {vendor: 0 for vendor in sorted({r.metric_name for r in raw_rows})}
    for row in raw_rows:
        if row.source_file not in previous.get(row.metric_name, set()):
            counts[row.metric_name] += 1
    return counts


def write_outputs(
    raw_rows: list[CostRow],
    monthly_rows: list[CostRow],
    db_path: Path,
    csv_path: Path,
    csv_export_months: int = 12,
    csv_export_floor: date | None = None,
) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(db_path))
    try:
        con.execute("BEGIN TRANSACTION")
        try:
            store.write_replace(
                con, "raw_costs", _RAW_COLUMNS,
                [(r.metric_name, r.metric_date, r.metric_value, r.source_file) for r in raw_rows],
            )
            store.write_replace(
                con, "monthly_costs", _MONTHLY_COLUMNS,
                [(r.metric_name, r.metric_date, r.metric_value) for r in monthly_rows],
            )

            if monthly_rows:
                anchor = max(r.metric_date for r in monthly_rows)
                csv_start = store.trailing_window_start(
                    anchor, csv_export_months, "months", floor=csv_export_floor
                )
            else:
                csv_start = csv_export_floor or date.min

            store.export_csv(
                con,
                "SELECT metric_name, metric_date, metric_value FROM monthly_costs "
                "WHERE metric_date >= ? ORDER BY metric_date, metric_name",
                [csv_start],
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
    downloads_dir: Path,
    db_path: Path,
    csv_path: Path,
    text_extractor: TextExtractor = extract_text,
    vendor_modules: list[ModuleType] | None = None,
    sum_on_collision: frozenset[str] = frozenset(),
    csv_export_months: int = 12,
    csv_export_floor: date | None = None,
) -> None:
    raw_rows = parse_all(downloads_dir, text_extractor, vendor_modules)
    monthly_rows = resolve_monthly(raw_rows, sum_on_collision)
    previous_source_files = _read_previous_source_files(db_path)
    new_row_counts = count_new_rows(raw_rows, previous_source_files)
    write_outputs(raw_rows, monthly_rows, db_path, csv_path, csv_export_months, csv_export_floor)
    logger.info(
        "wrote %d raw rows and %d monthly rows to %s and %s",
        len(raw_rows), len(monthly_rows), db_path, csv_path,
    )
    logger.info("new raw rows this run by vendor: %s", new_row_counts)
