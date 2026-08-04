from datetime import date

from metronome.costs.vendors import gcp

# Real text from INV-US-26007303.pdf (current template), verified via pdfplumber.
CURRENT_TEMPLATE_TEXT = """
DOIT INTERNATIONAL USA INC
5201 Great America Parkway, Suite 320
Attn: Eric Born Details: Covering April 2026
Tel: +9727149325223 Tax ID: 453478769
TAX INVOICE No: INV-US-26007303
Google Cloud Project 'acme-prod' 1 USD1,787.90 1,787.90
Total Before Sales Tax USD4,860.40
0.00% Sales Tax USD 0.00
Total USD4,860.40
""".strip()

# Real text from IN254024450.pdf (older "Priority" template). Note the
# column interleaving pdfplumber produces here: the total line is merged
# onto the same line as unrelated left-column text.
OLDER_TEMPLATE_TEXT = """
DOIT INTERNATIONAL USA INC
5201 Great America Pkwy, Ste. 320
Attn: Born Eric Details: Covering December 2025
Sales Invoice IN254024450 Original. - Digitally Signed
Google Cloud Project 'acme-dev' 1 USD 1,280.10 1,280.10
Total Price 3,784.82
Pay by: 01/30/26
Tax 0.00
Customer Number: US101141 TOTAL USD 3,784.82
Cust. Company Number: 453478769
""".strip()

# Real text from INV-US-26001452.pdf: a third total-line shape, "$" not "USD".
DOLLAR_SIGN_TOTAL_TEXT = """
DoiT Internationel USA INC
Attn: Eric Born Details: Covering January 2026
Google Cloud Project 'acme-dev' 1 1,282.05 1,282.05
Total Before Tax $3,721.76
Tax (0.00%) $0.00
Total $3,721.76
""".strip()


def test_detect_true_for_both_template_spellings():
    assert gcp.detect(CURRENT_TEMPLATE_TEXT) is True
    assert gcp.detect("DoiT Internationel USA INC") is True


def test_detect_false_for_unrelated_text():
    assert gcp.detect("some other invoice entirely") is False


def test_parse_current_template():
    rows = gcp.parse(CURRENT_TEMPLATE_TEXT, "INV-US-26007303.pdf")
    assert len(rows) == 1
    assert rows[0].metric_name == "GCP"
    assert rows[0].metric_date == date(2026, 4, 1)
    assert rows[0].metric_value == 4860.40


def test_parse_older_template_with_interleaved_columns():
    rows = gcp.parse(OLDER_TEMPLATE_TEXT, "IN254024450.pdf")
    assert len(rows) == 1
    assert rows[0].metric_date == date(2025, 12, 1)
    assert rows[0].metric_value == 3784.82


def test_parse_dollar_sign_total_shape():
    rows = gcp.parse(DOLLAR_SIGN_TOTAL_TEXT, "INV-US-26001452.pdf")
    assert len(rows) == 1
    assert rows[0].metric_date == date(2026, 1, 1)
    assert rows[0].metric_value == 3721.76


def test_parse_raises_when_no_final_total_line_found():
    import pytest

    text = "Details: Covering January 2026\nTotal Before Sales Tax USD4,860.40\n"
    with pytest.raises(ValueError):
        gcp.parse(text, "bad.pdf")
