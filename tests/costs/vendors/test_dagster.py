from datetime import date

from metronome.costs.vendors import dagster

# Real text from Invoice-A74E1E93-0042.pdf, verified via pdfplumber. A second
# line item (Storage) was added so the shown lines sum to the invoice's real
# Subtotal/Total/Amount due -- the original excerpt only kept one line item
# for brevity and didn't sum to $124.56 on its own.
INVOICE_TEXT = """
Invoice
Invoice number A74E1E93 0042
Date of issue January 1, 2026
Date due January 1, 2026
Dagster Labs Bill to
548 Market St sealed
#50093 sam.swift@sealed.com
San Francisco, California 94104
United States
billing@dagsterlabs.com
$124.56 USD due January 1, 2026
Pay online
Description Qty Unit price Amount
Serverless Compute Minutes  Starter Plan) 3,136 $0.005 $15.68
Dec 1, 2025 Jan 1, 2026
Serverless Storage GB-Hours  Starter Plan) 21,776 $0.005 $108.88
Dec 1, 2025 Jan 1, 2026
Subtotal $124.56
Total $124.56
Amount due $124.56 USD
Page 1 of 1
""".strip()


def test_detect_true_for_dagster_invoice():
    assert dagster.detect(INVOICE_TEXT) is True


def test_detect_false_for_unrelated_text():
    assert dagster.detect("some other invoice entirely") is False


def test_parse_uses_line_item_period_start_not_issue_date():
    # The invoice is issued Jan 1, 2026 but the line items cover
    # Dec 1, 2025 - Jan 1, 2026 -- the money was spent in December, so the
    # metric date should land there, not on the (later) issue date.
    rows = dagster.parse(INVOICE_TEXT, "Invoice-A74E1E93-0042.pdf")
    assert len(rows) == 1
    row = rows[0]
    assert row.metric_name == "Dagster"
    assert row.metric_date == date(2025, 12, 1)
    assert row.metric_value == 124.56
    assert row.source_file == "Invoice-A74E1E93-0042.pdf"
    assert row.statement_date is None


def test_parse_falls_back_to_issue_date_when_no_line_item_periods_found():
    text = """
Invoice
Date of issue January 1, 2026
billing@dagsterlabs.com
Amount due $124.56 USD
""".strip()
    rows = dagster.parse(text, "minimal.pdf")
    assert len(rows) == 1
    assert rows[0].metric_date == date(2026, 1, 1)
    assert rows[0].metric_value == 124.56


def test_parse_splits_line_items_with_different_periods_into_separate_rows():
    # A usage line trued up in arrears (Jan) alongside a base fee paid for the
    # upcoming period (Feb) -- each dollar amount should land in its own month.
    text = """
Invoice
Date of issue February 1, 2026
billing@dagsterlabs.com
Description Qty Unit price Amount
Serverless Compute Minutes  Starter Plan) 1,000 $0.005 $5.00
Jan 1, 2026 Feb 1, 2026
Serverless Base Fee  Starter Plan) 1 $100.00 $100.00
Feb 1, 2026 Mar 1, 2026
Amount due $105.00 USD
""".strip()
    rows = dagster.parse(text, "multi.pdf")
    by_month = {r.metric_date: r.metric_value for r in rows}
    assert by_month == {date(2026, 1, 1): 5.00, date(2026, 2, 1): 100.00}


def test_parse_raises_when_fields_missing():
    import pytest

    with pytest.raises(ValueError):
        dagster.parse("nothing useful here", "bad.pdf")
