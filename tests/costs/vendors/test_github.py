from datetime import date

from metronome.costs.vendors import github

# Real text from INV135524778.pdf (regular monthly INVOICE), verified via pdfplumber.
INVOICE_TEXT = """
INVOICE
GitHub, Inc. Invoice # INV135524778
Support Contact BILL TO
Invoice Date May 15, 2026
88 Colin P. Kelly Jr. St.
Sealed Inc
San Francisco, CA 94107 Terms Due Upon Receipt
389 5th Ave
Suite 400 Due Date May 15, 2026
New York, New York 10016-3320 Currency USD
United States
QUANTITY DESCRIPTION RATE AMOUNT
GitHub Copilot Usage
95.00 $1.00 $95.00
Apr 01, 2026 - Apr 30, 2026
GitHub Business Cloud - Month
15 $21.00 $315.00
May 15, 2026 - Jun 14, 2026
SUBTOTAL: $410.00
TAX: $36.39
INVOICE TOTAL: $446.39
APPLIED TRANSACTIONS:
P-90276625 May 15, 2026 -$446.39
BALANCE DUE: $0.00
""".strip()

# Real text from INV121852355.pdf (mid-cycle proration RECEIPT), verified via pdfplumber.
RECEIPT_TEXT = """
RECEIPT
GitHub, Inc. Invoice # INV121852355
Support Contact BILL TO
Invoice Date Feb 25, 2026
88 Colin P. Kelly Jr. St.
Sealed Inc
San Francisco, CA 94107 Terms Due Upon Receipt
108 W 39th Street
Ste 1006 PMB2341 Due Date Feb 25, 2026
New York, New York 10018-3614 Currency USD
United States
QUANTITY DESCRIPTION RATE AMOUNT
GitHub Business Cloud - Month -- Proration
15 $21.00 $202.50
Feb 25, 2026 - Mar 14, 2026
GitHub Business Cloud - Month -- Proration Credit
13 $21.00 $-175.50
Feb 25, 2026 - Mar 14, 2026
SUBTOTAL: $27.00
TAX: $2.39
INVOICE TOTAL: $29.39
APPLIED TRANSACTIONS:
P-84908715 Feb 25, 2026 -$29.39
BALANCE DUE: $0.00
""".strip()


def test_detect_true_for_invoice_and_receipt():
    assert github.detect(INVOICE_TEXT) is True
    assert github.detect(RECEIPT_TEXT) is True


def test_detect_false_for_unrelated_text():
    assert github.detect("some other invoice entirely") is False


def test_parse_regular_invoice():
    rows = github.parse(INVOICE_TEXT, "INV135524778.pdf")
    assert len(rows) == 1
    assert rows[0].metric_name == "GitHub"
    assert rows[0].metric_date == date(2026, 5, 1)
    assert rows[0].metric_value == 446.39


def test_parse_proration_receipt():
    rows = github.parse(RECEIPT_TEXT, "INV121852355.pdf")
    assert len(rows) == 1
    assert rows[0].metric_date == date(2026, 2, 1)
    assert rows[0].metric_value == 29.39


# Hypothetical credit-dominant receipt: line items already show GitHub renders
# negative amounts as "$-X.XX" (see RECEIPT_TEXT above), so a negative
# INVOICE TOTAL is a plausible real-world case, not just a fuzz artifact.
NEGATIVE_TOTAL_TEXT = """
RECEIPT
GitHub, Inc. Invoice # INV999999999
Support Contact BILL TO
Invoice Date Mar 1, 2026
88 Colin P. Kelly Jr. St.
Sealed Inc
San Francisco, CA 94107 Terms Due Upon Receipt
United States
QUANTITY DESCRIPTION RATE AMOUNT
GitHub Business Cloud - Month -- Proration Credit
25 $21.00 $-525.00
Feb 01, 2026 - Feb 28, 2026
SUBTOTAL: $-50.00
TAX: $0.00
INVOICE TOTAL: $-50.00
APPLIED TRANSACTIONS:
P-00000000 Mar 1, 2026 $50.00
BALANCE DUE: $0.00
""".strip()


def test_parse_negative_invoice_total_does_not_raise():
    rows = github.parse(NEGATIVE_TOTAL_TEXT, "INV999999999.pdf")
    assert len(rows) == 1
    assert rows[0].metric_value == -50.0
