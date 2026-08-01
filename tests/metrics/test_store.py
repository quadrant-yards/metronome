from datetime import date, timedelta

import duckdb

from metronome.metrics.store import export_csv, trailing_window_start, write_replace, write_upsert


def test_write_replace_creates_table_and_inserts_rows(tmp_path):
    db_path = tmp_path / "test.db"
    con = duckdb.connect(str(db_path))
    try:
        write_replace(
            con, "widgets",
            [("name", "VARCHAR"), ("count", "INTEGER")],
            [("a", 1), ("b", 2)],
        )
        result = con.execute("SELECT name, count FROM widgets ORDER BY name").fetchall()
    finally:
        con.close()
    assert result == [("a", 1), ("b", 2)]


def test_write_replace_drops_previous_contents_on_rerun(tmp_path):
    db_path = tmp_path / "test.db"
    con = duckdb.connect(str(db_path))
    try:
        write_replace(con, "widgets", [("name", "VARCHAR")], [("a",), ("b",)])
        write_replace(con, "widgets", [("name", "VARCHAR")], [("c",)])
        result = con.execute("SELECT name FROM widgets").fetchall()
    finally:
        con.close()
    assert result == [("c",)]


def test_write_replace_with_no_rows_creates_an_empty_table(tmp_path):
    db_path = tmp_path / "test.db"
    con = duckdb.connect(str(db_path))
    try:
        write_replace(con, "widgets", [("name", "VARCHAR")], [])
        count = con.execute("SELECT COUNT(*) FROM widgets").fetchone()[0]
    finally:
        con.close()
    assert count == 0


def test_write_upsert_creates_table_on_first_call(tmp_path):
    db_path = tmp_path / "test.db"
    con = duckdb.connect(str(db_path))
    try:
        write_upsert(
            con, "widgets",
            [("name", "VARCHAR"), ("count", "INTEGER")],
            key_columns=["name"],
            rows=[("a", 1)],
        )
        result = con.execute("SELECT name, count FROM widgets").fetchall()
    finally:
        con.close()
    assert result == [("a", 1)]


def test_write_upsert_replaces_rows_matching_the_same_key(tmp_path):
    db_path = tmp_path / "test.db"
    con = duckdb.connect(str(db_path))
    try:
        write_upsert(con, "widgets", [("name", "VARCHAR"), ("count", "INTEGER")], ["name"], [("a", 1)])
        write_upsert(con, "widgets", [("name", "VARCHAR"), ("count", "INTEGER")], ["name"], [("a", 2)])
        result = con.execute("SELECT name, count FROM widgets").fetchall()
    finally:
        con.close()
    assert result == [("a", 2)]


def test_write_upsert_leaves_rows_with_a_different_key_untouched(tmp_path):
    db_path = tmp_path / "test.db"
    con = duckdb.connect(str(db_path))
    try:
        write_upsert(con, "widgets", [("name", "VARCHAR"), ("count", "INTEGER")], ["name"], [("a", 1)])
        write_upsert(con, "widgets", [("name", "VARCHAR"), ("count", "INTEGER")], ["name"], [("b", 2)])
        result = con.execute("SELECT name, count FROM widgets ORDER BY name").fetchall()
    finally:
        con.close()
    assert result == [("a", 1), ("b", 2)]


def test_write_upsert_supports_composite_keys(tmp_path):
    db_path = tmp_path / "test.db"
    con = duckdb.connect(str(db_path))
    try:
        columns = [("name", "VARCHAR"), ("period", "DATE"), ("count", "INTEGER")]
        write_upsert(con, "widgets", columns, ["name", "period"], [("a", date(2026, 1, 1), 1)])
        write_upsert(con, "widgets", columns, ["name", "period"], [("a", date(2026, 1, 1), 9)])
        result = con.execute("SELECT name, period, count FROM widgets").fetchall()
    finally:
        con.close()
    assert result == [("a", date(2026, 1, 1), 9)]


def test_export_csv_writes_headered_csv(tmp_path):
    db_path = tmp_path / "test.db"
    csv_path = tmp_path / "out.csv"
    con = duckdb.connect(str(db_path))
    try:
        write_replace(con, "widgets", [("name", "VARCHAR"), ("count", "INTEGER")], [("a", 1)])
        export_csv(con, "SELECT name, count FROM widgets", [], csv_path)
    finally:
        con.close()
    assert csv_path.read_text().strip().splitlines() == ["name,count", "a,1"]


def test_export_csv_applies_query_params(tmp_path):
    db_path = tmp_path / "test.db"
    csv_path = tmp_path / "out.csv"
    con = duckdb.connect(str(db_path))
    try:
        write_replace(con, "widgets", [("name", "VARCHAR"), ("count", "INTEGER")], [("a", 1), ("b", 2)])
        export_csv(con, "SELECT name, count FROM widgets WHERE count >= ?", [2], csv_path)
    finally:
        con.close()
    assert csv_path.read_text().strip().splitlines() == ["name,count", "b,2"]


def test_trailing_window_start_months_shifts_back_count_minus_one_months():
    assert trailing_window_start(date(2026, 6, 1), 12, "months") == date(2025, 7, 1)


def test_trailing_window_start_months_handles_year_rollover():
    assert trailing_window_start(date(2026, 1, 1), 3, "months") == date(2025, 11, 1)


def test_trailing_window_start_weeks_shifts_back_count_minus_one_weeks():
    anchor = date(2026, 7, 27)
    assert trailing_window_start(anchor, 12, "weeks") == anchor - timedelta(weeks=11)


def test_trailing_window_start_clamps_to_floor_when_window_would_go_earlier():
    result = trailing_window_start(date(2026, 6, 1), 12, "months", floor=date(2025, 11, 1))
    assert result == date(2025, 11, 1)


def test_trailing_window_start_does_not_clamp_when_window_is_already_past_floor():
    result = trailing_window_start(date(2027, 3, 1), 12, "months", floor=date(2025, 11, 1))
    assert result == date(2026, 4, 1)
