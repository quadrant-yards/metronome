from datetime import date

from metronome.costs.vendors import hex

# Real text from Invoice-65D06C93-0031.pdf, verified via pdfplumber.
INVOICE_TEXT = """
Invoice
Invoice number 65D06C93 0031
Date of issue October 23, 2025
Date due October 23, 2025
Hex Bill to
2261 Market Street Sealed
#4233 sam.swift@sealed.com
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


def test_parse_extracts_month_and_amount_due():
    rows = hex.parse(INVOICE_TEXT, "Invoice-65D06C93-0031.pdf")
    assert len(rows) == 1
    row = rows[0]
    assert row.metric_name == "Hex"
    assert row.metric_date == date(2025, 10, 1)
    assert row.metric_value == 150.00
    assert row.source_file == "Invoice-65D06C93-0031.pdf"
    assert row.statement_date is None


def test_parse_raises_when_fields_missing():
    import pytest

    with pytest.raises(ValueError):
        hex.parse("nothing useful here", "bad.pdf")
