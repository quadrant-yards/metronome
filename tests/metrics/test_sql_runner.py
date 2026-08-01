import logging
from datetime import date

from metronome.metrics.sql_runner import run_all


def test_run_all_discovers_and_executes_every_sql_file_in_sources_dir(tmp_path):
    (tmp_path / "alpha.sql").write_text("select 'Alpha', date '2026-07-27', 1")
    (tmp_path / "beta.sql").write_text("select 'Beta', date '2026-07-27', 2")

    def _execute(sql: str) -> list[tuple]:
        if "Alpha" in sql:
            return [("Alpha", date(2026, 7, 27), 1)]
        if "Beta" in sql:
            return [("Beta", date(2026, 7, 27), 2)]
        return []  # the SET statement

    rows = run_all("weekly", _execute, sources_dir=tmp_path)

    names = {r.metric_name for r in rows}
    assert names == {"Alpha", "Beta"}
    assert len(rows) == 2


def test_run_all_sets_period_session_variable_before_running_sources(tmp_path):
    (tmp_path / "metric.sql").write_text("select 'X', date '2026-07-27', 1")

    def _make_executor():
        calls: list[str] = []

        def _execute(sql: str) -> list[tuple]:
            calls.append(sql)
            return []

        _execute.calls = calls
        return _execute

    weekly_executor = _make_executor()
    run_all("weekly", weekly_executor, sources_dir=tmp_path)
    assert weekly_executor.calls[0] == "SET period = 'week';"

    monthly_executor = _make_executor()
    run_all("monthly", monthly_executor, sources_dir=tmp_path)
    assert monthly_executor.calls[0] == "SET period = 'month';"


def test_run_all_skips_failing_source_but_returns_the_rest(tmp_path, caplog):
    (tmp_path / "broken.sql").write_text("select 1/0")
    (tmp_path / "ok.sql").write_text("select 'OK', date '2026-07-27', 2")

    def _execute(sql: str) -> list[tuple]:
        if "1/0" in sql:
            raise RuntimeError("boom")
        if "OK" in sql:
            return [("OK", date(2026, 7, 27), 2)]
        return []  # the SET statement

    with caplog.at_level(logging.ERROR):
        rows = run_all("weekly", _execute, sources_dir=tmp_path)

    assert len(rows) == 1
    assert rows[0].metric_name == "OK"
    assert any("broken" in message for message in caplog.messages)
