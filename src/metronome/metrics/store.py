from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from typing import Literal

import duckdb


def write_replace(
    con: duckdb.DuckDBPyConnection,
    table: str,
    columns: list[tuple[str, str]],
    rows: list[tuple],
) -> None:
    """Drop and recreate `table`, then insert `rows`.

    `columns` is a list of (name, sql_type) pairs defining the table's schema.
    """
    col_defs = ", ".join(f"{name} {sql_type}" for name, sql_type in columns)
    con.execute(f"DROP TABLE IF EXISTS {table}")
    con.execute(f"CREATE TABLE {table} ({col_defs})")
    if rows:
        placeholders = ", ".join("?" for _ in columns)
        con.executemany(f"INSERT INTO {table} VALUES ({placeholders})", rows)


def write_upsert(
    con: duckdb.DuckDBPyConnection,
    table: str,
    columns: list[tuple[str, str]],
    key_columns: list[str],
    rows: list[tuple],
) -> None:
    """Create `table` if missing, delete rows matching each row's key columns, then insert `rows`."""
    col_defs = ", ".join(f"{name} {sql_type}" for name, sql_type in columns)
    con.execute(f"CREATE TABLE IF NOT EXISTS {table} ({col_defs})")

    column_names = [name for name, _ in columns]
    key_indexes = [column_names.index(key) for key in key_columns]
    keys = {tuple(row[i] for i in key_indexes) for row in rows}
    where_clause = " AND ".join(f"{key} = ?" for key in key_columns)
    for key_values in keys:
        con.execute(f"DELETE FROM {table} WHERE {where_clause}", list(key_values))

    if rows:
        placeholders = ", ".join("?" for _ in columns)
        con.executemany(f"INSERT INTO {table} VALUES ({placeholders})", rows)


def export_csv(
    con: duckdb.DuckDBPyConnection,
    query: str,
    params: list,
    csv_path: Path,
) -> None:
    """Run `query` and COPY its results to `csv_path` as a headered CSV."""
    csv_path_str = str(csv_path).replace("'", "''")
    con.execute(f"COPY ({query}) TO '{csv_path_str}' (HEADER, DELIMITER ',')", params)


def trailing_window_start(
    anchor: date,
    count: int,
    unit: Literal["months", "weeks"],
    floor: date | None = None,
) -> date:
    """Return the start of a trailing `count`-`unit` window ending at `anchor`
    (inclusive), clamped to `floor` if given."""
    if unit == "months":
        total = anchor.year * 12 + (anchor.month - 1) - (count - 1)
        year, month = divmod(total, 12)
        window_start = date(year, month + 1, 1)
    else:
        window_start = anchor - timedelta(weeks=count - 1)

    if floor is not None:
        return max(window_start, floor)
    return window_start
