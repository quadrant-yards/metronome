import logging
from datetime import date
from pathlib import Path

import duckdb

from metronome.costs.models import CostRow
from metronome.costs.pipeline import count_new_rows, parse_all, run, write_outputs

SNOWFLAKE_TEXT = """
USAGE STATEMENT
CUSTOMER: Acme STATEMENT DATE: 02/28/2026
MONTHLY USAGE
USAGE MONTH USAGE CATEGORY UNITS CONSUMED TOTAL USAGE (USD)
Feb-2026 OVERAGE-COMPUTE 359.065 718.13
Feb-2026 AZ72662-GCP-US-EAST4 TOTAL N/A 0.00
""".strip()

DAGSTER_TEXT = """
Invoice
Date of issue January 1, 2026
billing@dagsterlabs.com
Amount due $124.56 USD
""".strip()


def _fake_extractor(mapping: dict[str, str]):
    def _extract(path: Path) -> str:
        return mapping[path.name]

    return _extract


def test_parse_all_dispatches_each_file_to_the_matching_vendor(tmp_path):
    (tmp_path / "a.pdf").write_bytes(b"")
    (tmp_path / "b.pdf").write_bytes(b"")
    extractor = _fake_extractor({"a.pdf": SNOWFLAKE_TEXT, "b.pdf": DAGSTER_TEXT})

    rows = parse_all(tmp_path, extractor)

    names = {r.metric_name for r in rows}
    assert names == {"Snowflake", "Dagster"}


def test_parse_all_skips_files_matching_no_vendor(tmp_path, caplog):
    (tmp_path / "mystery.pdf").write_bytes(b"")
    extractor = _fake_extractor({"mystery.pdf": "totally unrelated content"})

    with caplog.at_level(logging.WARNING):
        rows = parse_all(tmp_path, extractor)

    assert rows == []
    assert any("mystery.pdf" in message for message in caplog.messages)


POISON_DAGSTER_TEXT = """
Invoice
Date of issue Blorptember 1, 2026
billing@dagsterlabs.com
Amount due $999.99 USD
""".strip()


def test_parse_all_skips_poisoned_file_but_still_parses_the_rest(tmp_path, caplog):
    (tmp_path / "good_sf.pdf").write_bytes(b"")
    (tmp_path / "poison.pdf").write_bytes(b"")
    (tmp_path / "good_dg.pdf").write_bytes(b"")
    extractor = _fake_extractor(
        {
            "good_sf.pdf": SNOWFLAKE_TEXT,
            "poison.pdf": POISON_DAGSTER_TEXT,
            "good_dg.pdf": DAGSTER_TEXT,
        }
    )

    with caplog.at_level(logging.ERROR):
        rows = parse_all(tmp_path, extractor)

    names = {r.metric_name for r in rows}
    assert names == {"Snowflake", "Dagster"}
    assert len(rows) == 2

    error_messages = [r.message for r in caplog.records if r.levelno == logging.ERROR]
    assert any("poison.pdf" in message for message in error_messages)


def test_run_writes_duckdb_tables_and_csv(tmp_path):
    (tmp_path / "downloads").mkdir()
    (tmp_path / "downloads" / "sf.pdf").write_bytes(b"")
    (tmp_path / "downloads" / "dg.pdf").write_bytes(b"")
    extractor = _fake_extractor({"sf.pdf": SNOWFLAKE_TEXT, "dg.pdf": DAGSTER_TEXT})

    db_path = tmp_path / "metrics.db"
    csv_path = tmp_path / "data-monthly.csv"

    run(tmp_path / "downloads", db_path, csv_path, extractor)

    con = duckdb.connect(str(db_path))
    raw_count = con.execute("SELECT COUNT(*) FROM raw_costs").fetchone()[0]
    monthly = con.execute(
        "SELECT metric_name, metric_date, metric_value FROM monthly_costs ORDER BY metric_name"
    ).fetchall()
    con.close()

    assert raw_count == 2
    assert monthly == [
        ("Dagster", date(2026, 1, 1), 124.56),
        ("Snowflake", date(2026, 2, 1), 718.13),
    ]

    csv_text = csv_path.read_text()
    assert "metric_name,metric_date,metric_value" in csv_text
    assert "Dagster,2026-01-01,124.56" in csv_text
    assert "Snowflake,2026-02-01,718.13" in csv_text


def test_run_against_empty_downloads_dir_succeeds_with_empty_outputs(tmp_path):
    (tmp_path / "downloads").mkdir()
    extractor = _fake_extractor({})

    db_path = tmp_path / "metrics.db"
    csv_path = tmp_path / "data-monthly.csv"

    run(tmp_path / "downloads", db_path, csv_path, extractor)

    con = duckdb.connect(str(db_path))
    raw_count = con.execute("SELECT COUNT(*) FROM raw_costs").fetchone()[0]
    monthly_count = con.execute("SELECT COUNT(*) FROM monthly_costs").fetchone()[0]
    con.close()

    assert raw_count == 0
    assert monthly_count == 0

    csv_text = csv_path.read_text()
    assert csv_text.strip() == "metric_name,metric_date,metric_value"


def test_run_is_idempotent_across_repeated_calls(tmp_path):
    (tmp_path / "downloads").mkdir()
    (tmp_path / "downloads" / "sf.pdf").write_bytes(b"")
    extractor = _fake_extractor({"sf.pdf": SNOWFLAKE_TEXT})
    db_path = tmp_path / "metrics.db"
    csv_path = tmp_path / "data-monthly.csv"

    run(tmp_path / "downloads", db_path, csv_path, extractor)
    run(tmp_path / "downloads", db_path, csv_path, extractor)

    con = duckdb.connect(str(db_path))
    count = con.execute("SELECT COUNT(*) FROM monthly_costs").fetchone()[0]
    con.close()
    assert count == 1


def test_write_outputs_clamps_csv_export_to_a_floor(tmp_path):
    raw_rows = [CostRow("X", date(2024, 1, 1), 1.0, "f1.pdf")]
    monthly_rows = [
        CostRow("X", date(2024, 1, 1), 1.0, "f1.pdf"),
        CostRow("X", date(2025, 10, 1), 2.0, "f1.pdf"),
        CostRow("X", date(2025, 11, 1), 3.0, "f1.pdf"),
        CostRow("X", date(2026, 6, 1), 4.0, "f1.pdf"),
    ]
    db_path = tmp_path / "metrics.db"
    csv_path = tmp_path / "out.csv"

    write_outputs(raw_rows, monthly_rows, db_path, csv_path, csv_export_floor=date(2025, 11, 1))

    con = duckdb.connect(str(db_path))
    monthly_count = con.execute("SELECT COUNT(*) FROM monthly_costs").fetchone()[0]
    con.close()
    # DuckDB table keeps full history regardless of the CSV window
    assert monthly_count == 4

    csv_text = csv_path.read_text()
    # anchor = 2026-06-01; window_start = 2025-07-01; floor 2025-11-01 wins
    assert "2024-01-01" not in csv_text
    assert "2025-10-01" not in csv_text
    assert "2025-11-01" in csv_text
    assert "2026-06-01" in csv_text


def test_write_outputs_windows_csv_to_trailing_12_months_when_floor_doesnt_bind(tmp_path):
    raw_rows = [CostRow("X", date(2026, 3, 1), 1.0, "f1.pdf")]
    monthly_rows = [
        CostRow("X", date(2026, 3, 1), 1.0, "f1.pdf"),
        CostRow("X", date(2026, 4, 1), 2.0, "f1.pdf"),
        CostRow("X", date(2027, 3, 1), 3.0, "f1.pdf"),
    ]
    db_path = tmp_path / "metrics.db"
    csv_path = tmp_path / "out.csv"

    write_outputs(raw_rows, monthly_rows, db_path, csv_path, csv_export_floor=date(2025, 11, 1))

    csv_text = csv_path.read_text()
    # anchor = 2027-03-01; window_start = 2026-04-01 (past the 2025-11 floor, so
    # the trailing-12-months window wins, not the floor)
    assert "2026-03-01" not in csv_text
    assert "2026-04-01" in csv_text
    assert "2027-03-01" in csv_text


def test_write_outputs_with_no_floor_uses_the_plain_trailing_window(tmp_path):
    raw_rows = [CostRow("X", date(2024, 1, 1), 1.0, "f1.pdf")]
    monthly_rows = [
        CostRow("X", date(2024, 1, 1), 1.0, "f1.pdf"),
        CostRow("X", date(2026, 6, 1), 4.0, "f1.pdf"),
    ]
    db_path = tmp_path / "metrics.db"
    csv_path = tmp_path / "out.csv"

    write_outputs(raw_rows, monthly_rows, db_path, csv_path)

    csv_text = csv_path.read_text()
    # anchor = 2026-06-01; window_start = 2025-07-01; no floor supplied, so
    # nothing clamps it -- 2024-01-01 falls outside the trailing 12 months.
    assert "2024-01-01" not in csv_text
    assert "2026-06-01" in csv_text


def test_write_outputs_sorts_csv_by_metric_date_ascending_across_vendors(tmp_path):
    raw_rows = [CostRow("Zeta", date(2026, 1, 1), 1.0, "f1.pdf")]
    monthly_rows = [
        CostRow("Alpha", date(2026, 2, 1), 20.0, "f1.pdf"),
        CostRow("Zeta", date(2026, 1, 1), 10.0, "f2.pdf"),
    ]
    db_path = tmp_path / "metrics.db"
    csv_path = tmp_path / "out.csv"

    write_outputs(raw_rows, monthly_rows, db_path, csv_path)

    lines = csv_path.read_text().strip().splitlines()
    assert lines[0] == "metric_name,metric_date,metric_value"
    assert lines[1] == "Zeta,2026-01-01,10.0"
    assert lines[2] == "Alpha,2026-02-01,20.0"


def test_count_new_rows_all_new_when_no_previous_files():
    rows = [
        CostRow("Snowflake", date(2026, 1, 1), 10.0, "a.pdf"),
        CostRow("Snowflake", date(2026, 2, 1), 20.0, "b.pdf"),
        CostRow("Dagster", date(2026, 1, 1), 5.0, "c.pdf"),
    ]
    assert count_new_rows(rows, {}) == {"Snowflake": 2, "Dagster": 1}


def test_count_new_rows_excludes_previously_seen_files():
    rows = [
        CostRow("Snowflake", date(2026, 1, 1), 10.0, "a.pdf"),
        CostRow("Snowflake", date(2026, 2, 1), 20.0, "b.pdf"),
    ]
    previous = {"Snowflake": {"a.pdf"}}
    assert count_new_rows(rows, previous) == {"Snowflake": 1}


def test_count_new_rows_reports_zero_for_vendor_with_no_new_files():
    rows = [CostRow("Dagster", date(2026, 1, 1), 5.0, "c.pdf")]
    previous = {"Dagster": {"c.pdf"}}
    assert count_new_rows(rows, previous) == {"Dagster": 0}


def test_read_previous_source_files_returns_empty_and_creates_no_file_when_db_missing(tmp_path):
    from metronome.costs.pipeline import _read_previous_source_files

    db_path = tmp_path / "does-not-exist.db"
    assert _read_previous_source_files(db_path) == {}
    assert not db_path.exists()


def test_run_logs_all_rows_as_new_on_first_run(tmp_path, caplog):
    (tmp_path / "downloads").mkdir()
    (tmp_path / "downloads" / "sf.pdf").write_bytes(b"")
    extractor = _fake_extractor({"sf.pdf": SNOWFLAKE_TEXT})
    db_path = tmp_path / "metrics.db"
    csv_path = tmp_path / "data-monthly.csv"

    with caplog.at_level(logging.INFO):
        run(tmp_path / "downloads", db_path, csv_path, extractor)

    message = next(m for m in caplog.messages if "new raw rows this run by vendor" in m)
    assert "'Snowflake': 1" in message


def test_run_logs_zero_new_rows_on_unchanged_second_run(tmp_path, caplog):
    (tmp_path / "downloads").mkdir()
    (tmp_path / "downloads" / "sf.pdf").write_bytes(b"")
    extractor = _fake_extractor({"sf.pdf": SNOWFLAKE_TEXT})
    db_path = tmp_path / "metrics.db"
    csv_path = tmp_path / "data-monthly.csv"

    run(tmp_path / "downloads", db_path, csv_path, extractor)
    caplog.clear()
    with caplog.at_level(logging.INFO):
        run(tmp_path / "downloads", db_path, csv_path, extractor)

    message = next(m for m in caplog.messages if "new raw rows this run by vendor" in m)
    assert "'Snowflake': 0" in message


def test_run_logs_only_the_newly_added_file_as_new(tmp_path, caplog):
    (tmp_path / "downloads").mkdir()
    (tmp_path / "downloads" / "sf.pdf").write_bytes(b"")
    db_path = tmp_path / "metrics.db"
    csv_path = tmp_path / "data-monthly.csv"
    run(tmp_path / "downloads", db_path, csv_path, _fake_extractor({"sf.pdf": SNOWFLAKE_TEXT}))

    (tmp_path / "downloads" / "dg.pdf").write_bytes(b"")
    extractor2 = _fake_extractor({"sf.pdf": SNOWFLAKE_TEXT, "dg.pdf": DAGSTER_TEXT})
    caplog.clear()
    with caplog.at_level(logging.INFO):
        run(tmp_path / "downloads", db_path, csv_path, extractor2)

    message = next(m for m in caplog.messages if "new raw rows this run by vendor" in m)
    assert "'Snowflake': 0" in message
    assert "'Dagster': 1" in message


def test_run_with_custom_vendor_list_only_matches_supplied_vendors(tmp_path):
    from metronome.costs.vendors import dagster

    (tmp_path / "downloads").mkdir()
    (tmp_path / "downloads" / "sf.pdf").write_bytes(b"")
    (tmp_path / "downloads" / "dg.pdf").write_bytes(b"")
    extractor = _fake_extractor({"sf.pdf": SNOWFLAKE_TEXT, "dg.pdf": DAGSTER_TEXT})
    db_path = tmp_path / "metrics.db"
    csv_path = tmp_path / "data-monthly.csv"

    run(tmp_path / "downloads", db_path, csv_path, extractor, vendor_modules=[dagster])

    con = duckdb.connect(str(db_path))
    raw_count = con.execute("SELECT COUNT(*) FROM raw_costs").fetchone()[0]
    con.close()
    assert raw_count == 1
