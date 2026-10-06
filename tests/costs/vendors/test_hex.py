from datetime import date

from metronome.costs.vendors import hex

# Real text from Invoice-65D06C93-0031.pdf, verified via pdfplumber.
INVOICE_TEXT = """
Invoice
Invoice number 65D06C93 0031
Date of issue October 23, 2025
Date due October 23, 2025
Hex Bill to
2261 Market Street Acme
#4233 billing@example.com
San Francisco, California 94114
United States
ar@hex.tech
$150.00 USD due October 23, 2025
Pay online
Description Qty Unit price Amount
Compute - Extra Large 0 $0.0108 $0.00
Sep 23 Oct 23, 2025
Compute - Large 0 $0.0053 $0.00
Sep 23 Oct 23, 2025
Compute - V100 GPU 0 $0.1117 $0.00
Sep 23 Oct 23, 2025
Compute - 4XL 0 $0.043 $0.00
Sep 23 Oct 23, 2025
Compute - 2XL 0 $0.0215 $0.00
Sep 23 Oct 23, 2025
Premium Support 2 $0.00 $0.00
Oct 23 Nov 23, 2025
Team Edition - Author Seats 2 $75.00 $150.00
Oct 23 Nov 23, 2025
Subtotal $150.00
Total $150.00
Amount due $150.00 USD
Page 1 of 2
Hex Technologies Inc's W 9 is available here if required:
https://docs.hex.tech/hex-technologies-w9.pdf
Page 2 of 2
""".strip()


def test_detect_true_for_hex_invoice():
    assert hex.detect(INVOICE_TEXT) is True


def test_detect_false_for_unrelated_text():
    assert hex.detect("some other invoice entirely") is False


def test_parse_splits_arrears_usage_and_forward_subscription_by_period():
    # The compute lines cover the just-ended Sep 23-Oct 23 cycle (all $0 here);
    # Premium Support and the seats are prepaid for the upcoming Oct 23-Nov 23
    # cycle. Each dollar amount should land in the month its own period starts,
    # not all lumped into the invoice's issue-date month.
    rows = hex.parse(INVOICE_TEXT, "Invoice-65D06C93-0031.pdf")
    by_month = {r.metric_date: r.metric_value for r in rows}
    assert by_month == {date(2025, 9, 1): 0.0, date(2025, 10, 1): 150.00}
    assert all(r.metric_name == "Hex" for r in rows)
    assert all(r.source_file == "Invoice-65D06C93-0031.pdf" for r in rows)
    assert all(r.statement_date is None for r in rows)


def test_parse_falls_back_to_issue_date_when_no_line_item_periods_found():
    text = """
Invoice
Date of issue October 23, 2025
ar@hex.tech
Amount due $150.00 USD
""".strip()
    rows = hex.parse(text, "minimal.pdf")
    assert len(rows) == 1
    assert rows[0].metric_date == date(2025, 10, 1)
    assert rows[0].metric_value == 150.00


def test_parse_raises_when_fields_missing():
    import pytest

    with pytest.raises(ValueError):
        hex.parse("nothing useful here", "bad.pdf")


# Real text from Invoice-65D06C93-0038.pdf (abridged to the non-zero lines),
# the first invoice shape with NY sales tax: line items are pre-tax.
TAXED_INVOICE_TEXT = """
Invoice
Date of issue May 23, 2026
ar@hex.tech
Description Qty Unit price Tax Amount
Compute - 2XL 0 $0.0215 $0.00
Apr 23 May 23, 2026
1 × Team Edition - Author Seats added on 24 Apr 2026 1 $73.30 8.875% $73.30
Apr 23 May 23, 2026
Basic Support 4 $0.00 $0.00
May 23 Jun 23, 2026
Team Edition - Author Seats 4 $75.00 8.875% $300.00
May 23 Jun 23, 2026
Subtotal $373.30
Total excluding tax $373.30
Sales Tax - New York  8.875% on $373.30  $33.13
Total $406.43
Amount due $406.43 USD
""".strip()


def test_parse_allocates_sales_tax_to_taxed_line_item_months(caplog):
    # $33.13 tax split pro rata on $73.30 (April) vs $300.00 (May) taxed
    # line items; rows must sum to the tax-inclusive Total without warning.
    rows = hex.parse(TAXED_INVOICE_TEXT, "Invoice-65D06C93-0038.pdf")
    by_month = {r.metric_date: r.metric_value for r in rows}
    assert by_month == {date(2026, 4, 1): 79.81, date(2026, 5, 1): 326.62}
    assert round(sum(by_month.values()), 2) == 406.43
    assert "line items sum to" not in caplog.text
