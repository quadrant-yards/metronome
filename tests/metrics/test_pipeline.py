from datetime import date, timedelta

import duckdb

from metronome.metrics.models import MetricRow
from metronome.metrics.pipeline import run, write_outputs


def test_write_outputs_creates_table_and_inserts_rows(tmp_path):
    rows = [
        MetricRow("Intake [PACO]", date(2026, 7, 27), 3.0),
        MetricRow("Furnace Jobs", date(2026, 7, 27), 2.0),
    ]
    db_path = tmp_path / "metrics.db"
    csv_path = tmp_path / "out.csv"

    write_outputs(rows, "weekly", db_path, csv_path)

    con = duckdb.connect(str(db_path))
    result = con.execute(
        "SELECT metric_name, metric_date, metric_value FROM product_weekly ORDER BY metric_name"
    ).fetchall()
    con.close()

    assert result == [
        ("Furnace Jobs", date(2026, 7, 27), 2.0),
        ("Intake [PACO]", date(2026, 7, 27), 3.0),
    ]


def test_write_outputs_replaces_existing_rows_for_the_same_period_on_rerun(tmp_path):
    db_path = tmp_path / "metrics.db"
    csv_path = tmp_path / "out.csv"

    write_outputs([MetricRow("Intake [PACO]", date(2026, 7, 27), 3.0)], "weekly", db_path, csv_path)
    write_outputs([MetricRow("Intake [PACO]", date(2026, 7, 27), 9.0)], "weekly", db_path, csv_path)

    con = duckdb.connect(str(db_path))
    result = con.execute("SELECT metric_name, metric_date, metric_value FROM product_weekly").fetchall()
    con.close()

    assert result == [("Intake [PACO]", date(2026, 7, 27), 9.0)]


def test_write_outputs_does_not_touch_other_periods_rows(tmp_path):
    db_path = tmp_path / "metrics.db"
    csv_path = tmp_path / "out.csv"

    write_outputs([MetricRow("Intake [PACO]", date(2026, 7, 20), 1.0)], "weekly", db_path, csv_path)
    write_outputs([MetricRow("Intake [PACO]", date(2026, 7, 27), 2.0)], "weekly", db_path, csv_path)

    con = duckdb.connect(str(db_path))
    count = con.execute("SELECT COUNT(*) FROM product_weekly").fetchone()[0]
    con.close()

    assert count == 2


def test_write_outputs_monthly_and_weekly_use_separate_tables(tmp_path):
    db_path = tmp_path / "metrics.db"
    csv_path = tmp_path / "out.csv"

    write_outputs([MetricRow("Intake [PACO]", date(2026, 7, 27), 1.0)], "weekly", db_path, csv_path)
    write_outputs([MetricRow("Intake [PACO]", date(2026, 7, 1), 2.0)], "monthly", db_path, csv_path)

    con = duckdb.connect(str(db_path))
    weekly_count = con.execute("SELECT COUNT(*) FROM product_weekly").fetchone()[0]
    monthly_count = con.execute("SELECT COUNT(*) FROM product_monthly").fetchone()[0]
    con.close()

    assert weekly_count == 1
    assert monthly_count == 1


def test_write_outputs_windows_csv_to_trailing_12_months(tmp_path):
    rows = [
        MetricRow("X", date(2026, 3, 1), 1.0),
        MetricRow("X", date(2026, 4, 1), 2.0),
        MetricRow("X", date(2027, 3, 1), 3.0),
    ]
    db_path = tmp_path / "metrics.db"
    csv_path = tmp_path / "out.csv"

    write_outputs(rows, "monthly", db_path, csv_path)

    csv_text = csv_path.read_text()
    assert "2026-03-01" not in csv_text
    assert "2026-04-01" in csv_text
    assert "2027-03-01" in csv_text


def test_write_outputs_windows_csv_to_trailing_12_weeks(tmp_path):
    anchor = date(2026, 7, 27)
    just_inside = anchor - timedelta(weeks=11)
    just_outside = anchor - timedelta(weeks=12)

    rows = [
        MetricRow("X", just_outside, 1.0),
        MetricRow("X", just_inside, 2.0),
        MetricRow("X", anchor, 3.0),
    ]
    db_path = tmp_path / "metrics.db"
    csv_path = tmp_path / "out.csv"

    write_outputs(rows, "weekly", db_path, csv_path)

    csv_text = csv_path.read_text()
    assert just_outside.isoformat() not in csv_text
    assert just_inside.isoformat() in csv_text
    assert anchor.isoformat() in csv_text


def test_write_outputs_sorts_csv_by_metric_date_then_metric_name(tmp_path):
    rows = [
        MetricRow("Zeta", date(2026, 7, 20), 1.0),
        MetricRow("Alpha", date(2026, 7, 27), 2.0),
    ]
    db_path = tmp_path / "metrics.db"
    csv_path = tmp_path / "out.csv"

    write_outputs(rows, "weekly", db_path, csv_path)

    lines = csv_path.read_text().strip().splitlines()
    assert lines[0] == "metric_name,metric_date,metric_value"
    assert lines[1] == "Zeta,2026-07-20,1.0"
    assert lines[2] == "Alpha,2026-07-27,2.0"


def test_write_outputs_with_no_rows_writes_header_only_csv(tmp_path):
    db_path = tmp_path / "metrics.db"
    csv_path = tmp_path / "out.csv"

    write_outputs([], "weekly", db_path, csv_path)

    csv_text = csv_path.read_text().strip()
    assert csv_text == "metric_name,metric_date,metric_value"


def test_run_end_to_end_writes_db_and_csv(tmp_path):
    sources_dir = tmp_path / "sources"
    sources_dir.mkdir()
    (sources_dir / "paco.sql").write_text("select 'Intake [PACO]', date '2026-07-27', 3")
    (sources_dir / "xcel_addl.sql").write_text("select 'Furnace Jobs', date '2026-07-27', 2")

    def _execute(sql: str) -> list[tuple]:
        if "Intake" in sql:
            return [("Intake [PACO]", date(2026, 7, 27), 3)]
        if "Furnace" in sql:
            return [("Furnace Jobs", date(2026, 7, 27), 2)]
        return []  # the SET statement

    db_path = tmp_path / "metrics.db"
    csv_path = tmp_path / "out.csv"

    run("weekly", _execute, db_path, csv_path, sources_dir=sources_dir)

    con = duckdb.connect(str(db_path))
    count = con.execute("SELECT COUNT(*) FROM product_weekly").fetchone()[0]
    con.close()
    assert count == 2

    csv_text = csv_path.read_text()
    assert "Intake [PACO]" in csv_text
    assert "Furnace Jobs" in csv_text
