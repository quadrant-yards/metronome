import logging
from datetime import date

from metronome.costs.models import CostRow
from metronome.costs.rollup import resolve_monthly


def test_single_row_per_month_passes_through_unchanged():
    rows = [
        CostRow("Dagster", date(2026, 1, 1), 100.0, "a.pdf"),
        CostRow("Dagster", date(2026, 2, 1), 110.0, "b.pdf"),
    ]
    result = resolve_monthly(rows)
    assert result == rows


def test_gap_fill_inserts_null_row_for_missing_month():
    rows = [
        CostRow("Dagster", date(2026, 1, 1), 100.0, "jan.pdf"),
        CostRow("Dagster", date(2026, 3, 1), 120.0, "mar.pdf"),
    ]
    result = resolve_monthly(rows)
    by_month = {r.metric_date: r for r in result}

    assert len(result) == 3
    assert by_month[date(2026, 1, 1)].metric_value == 100.0
    assert by_month[date(2026, 2, 1)].metric_value is None
    assert by_month[date(2026, 2, 1)].source_file is None
    assert by_month[date(2026, 3, 1)].metric_value == 120.0


def test_gap_fill_is_independent_per_vendor():
    rows = [
        CostRow("Dagster", date(2026, 1, 1), 100.0, "a.pdf"),
        CostRow("Dagster", date(2026, 3, 1), 120.0, "b.pdf"),
        CostRow("GCP", date(2026, 1, 1), 500.0, "c.pdf"),
        CostRow("GCP", date(2026, 2, 1), 510.0, "d.pdf"),
    ]
    result = resolve_monthly(rows)
    gcp_months = {r.metric_date for r in result if r.metric_name == "GCP"}
    # GCP has no gap of its own -- shouldn't get a fabricated March row just
    # because Dagster's range extends further.
    assert gcp_months == {date(2026, 1, 1), date(2026, 2, 1)}


def test_github_style_collision_sums_values_when_opted_in():
    rows = [
        CostRow("GitHub", date(2026, 2, 1), 400.66, "regular.pdf"),
        CostRow("GitHub", date(2026, 2, 1), 29.39, "proration.pdf"),
    ]
    result = resolve_monthly(rows, sum_on_collision=frozenset({"GitHub"}))
    assert len(result) == 1
    assert round(result[0].metric_value, 2) == 430.05


def test_github_collision_without_sum_on_collision_keeps_first_and_warns(caplog):
    rows = [
        CostRow("GitHub", date(2026, 2, 1), 400.66, "regular.pdf"),
        CostRow("GitHub", date(2026, 2, 1), 29.39, "proration.pdf"),
    ]
    with caplog.at_level(logging.WARNING):
        result = resolve_monthly(rows)

    assert len(result) == 1
    assert result[0].metric_value == 400.66
    assert result[0].source_file == "regular.pdf"
    assert any("GitHub" in message for message in caplog.messages)


def test_snowflake_style_collision_prefers_latest_statement_date():
    rows = [
        CostRow("Snowflake", date(2023, 10, 1), 999.0, "old_stmt.pdf", statement_date=date(2023, 11, 30)),
        CostRow("Snowflake", date(2023, 10, 1), 243.62, "new_stmt.pdf", statement_date=date(2024, 2, 29)),
    ]
    result = resolve_monthly(rows)
    assert len(result) == 1
    assert result[0].metric_value == 243.62
    assert result[0].source_file == "new_stmt.pdf"


def test_unexpected_duplicate_for_non_special_vendor_logs_warning_and_keeps_first(caplog):
    rows = [
        CostRow("Dagster", date(2026, 1, 1), 100.0, "first.pdf"),
        CostRow("Dagster", date(2026, 1, 1), 999.0, "second.pdf"),
    ]
    with caplog.at_level(logging.WARNING):
        result = resolve_monthly(rows)

    assert len(result) == 1
    assert result[0].metric_value == 100.0
    assert result[0].source_file == "first.pdf"
    assert any("Dagster" in message and "2026-01-01" in message for message in caplog.messages)


def test_duplicate_files_with_matching_values_still_logs_warning(caplog):
    rows = [
        CostRow("Dagster", date(2026, 1, 1), 100.0, "first.pdf"),
        CostRow("Dagster", date(2026, 1, 1), 100.0, "second.pdf"),
    ]
    with caplog.at_level(logging.WARNING):
        result = resolve_monthly(rows)

    assert len(result) == 1
    assert result[0].metric_value == 100.0
    assert result[0].source_file == "first.pdf"
    assert any("Dagster" in message and "2026-01-01" in message for message in caplog.messages)
