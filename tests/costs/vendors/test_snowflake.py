from datetime import date

from metronome.costs.vendors import snowflake

# Trimmed from a real cumulative statement (2023-07), which packs many
# MONTHLY USAGE blocks into one PDF. Oct-2022 has no OVERAGE- rows (still
# inside prepaid capacity); the pre-summed "... TOTAL" row is 28.53 but
# that's capacity drawdown, not new cost -- correct answer is $0.00.
CUMULATIVE_STATEMENT_TEXT = """
USAGE STATEMENT
CUSTOMER: Acme STATEMENT DATE: 07/31/2023
SUMMARY
Capacity Purchased USD 25,000.00
MONTHLY USAGE
USAGE MONTH USAGE CATEGORY UNITS CONSUMED TOTAL USAGE (USD)
Oct-2022 ADJ FOR INCL CLOUD SERVICES (0.068) (0.13)
Oct-2022 CLOUD SERVICES 0.068 0.13
Oct-2022 COMPUTE 14.995 28.49
Oct-2022 STORAGE 0.002 0.04
Oct-2022 AZ72662-GCP-US-EAST4 TOTAL N/A 28.53
MONTHLY USAGE
USAGE MONTH USAGE CATEGORY UNITS CONSUMED TOTAL USAGE (USD)
Oct-2023 ADJ FOR INCL CLOUD SERVICES (1.579) (3.00)
Oct-2023 CLOUD SERVICES 6.373 12.11
Oct-2023 COMPUTE 15.794 30.01
Oct-2023 OVERAGE-ADJ FOR INCL CLOUD SERVICES (7.387) (14.77)
Oct-2023 OVERAGE-AUTOMATIC CLUSTERING 0.001 0.00
Oct-2023 OVERAGE-CLOUD SERVICES 23.907 47.81
Oct-2023 OVERAGE-COMPUTE 74.129 148.26
Oct-2023 OVERAGE-SNOWPIPE 28.408 56.82
Oct-2023 OVERAGE-STORAGE 0.138 5.50
Oct-2023 SNOWPIPE 2.117 4.02
Oct-2023 STORAGE 0.015 0.35
Oct-2023 AZ72662-GCP-US-EAST4 TOTAL N/A 43.49
""".strip()

# Real text from Usage_Statement_171822_2026_2.pdf (a modern single-month
# statement, verified via pdfplumber). Every category has an OVERAGE-
# counterpart, and the "... TOTAL" row is stuck at 0.00.
MODERN_STATEMENT_TEXT = """
USAGE STATEMENT
CUSTOMER: Acme STATEMENT DATE: 02/28/2026
SUMMARY
Capacity Purchased USD 25,000.00
MONTHLY USAGE
USAGE MONTH USAGE CATEGORY UNITS CONSUMED TOTAL USAGE (USD)
Feb-2026 ADJ FOR INCL CLOUD SERVICES (0.452) (0.90)
Feb-2026 CLOUD SERVICES 0.452 0.90
Feb-2026 OVERAGE-ADJ FOR INCL CLOUD SERVICES (20.026) (40.06)
Feb-2026 OVERAGE-CLOUD SERVICES 20.026 40.06
Feb-2026 OVERAGE-COMPUTE 359.065 718.13
Feb-2026 OVERAGE-SERVERLESS TASKS 1.411 2.81
Feb-2026 OVERAGE-STORAGE 0.094 2.16
Feb-2026 OVERAGE-TRUST CENTER 101.955 203.91
Feb-2026 AZ72662-GCP-US-EAST4 TOTAL N/A 0.00
""".strip()


def test_detect_true_for_snowflake_statement():
    assert snowflake.detect(MODERN_STATEMENT_TEXT) is True


def test_detect_false_for_unrelated_text():
    assert snowflake.detect("some other invoice entirely") is False


def test_parse_cumulative_statement_returns_one_row_per_month_seen():
    rows = snowflake.parse(CUMULATIVE_STATEMENT_TEXT, "stmt_2023_07.pdf")
    by_month = {r.metric_date: r for r in rows}

    assert by_month[date(2022, 10, 1)].metric_value == 0.0
    assert round(by_month[date(2023, 10, 1)].metric_value, 2) == 243.62
    assert all(r.statement_date == date(2023, 7, 31) for r in rows)
    assert all(r.metric_name == "Snowflake" for r in rows)
    assert all(r.source_file == "stmt_2023_07.pdf" for r in rows)


def test_parse_modern_statement_sums_only_overage_rows():
    rows = snowflake.parse(MODERN_STATEMENT_TEXT, "stmt_2026_02.pdf")
    assert len(rows) == 1
    row = rows[0]
    assert row.metric_date == date(2026, 2, 1)
    assert round(row.metric_value, 2) == 927.01
    assert row.statement_date == date(2026, 2, 28)
