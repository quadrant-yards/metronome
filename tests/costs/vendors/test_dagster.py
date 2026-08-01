from datetime import date

from metronome.costs.vendors import dagster

# Real text from Invoice-A74E1E93-0042.pdf, verified via pdfplumber.
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
Subtotal $124.56
Total $124.56
Amount due $124.56 USD
Page 1 of 1
""".strip()


def test_detect_true_for_dagster_invoice():
    assert dagster.detect(INVOICE_TEXT) is True


def test_detect_false_for_unrelated_text():
    assert dagster.detect("some other invoice entirely") is False


def test_parse_extracts_month_and_amount_due():
    rows = dagster.parse(INVOICE_TEXT, "Invoice-A74E1E93-0042.pdf")
    assert len(rows) == 1
    row = rows[0]
    assert row.metric_name == "Dagster"
    assert row.metric_date == date(2026, 1, 1)
    assert row.metric_value == 124.56
    assert row.source_file == "Invoice-A74E1E93-0042.pdf"
    assert row.statement_date is None


def test_parse_raises_when_fields_missing():
    import pytest

    with pytest.raises(ValueError):
        dagster.parse("nothing useful here", "bad.pdf")
