from datetime import date

from metronome.costs.vendors import github

# Real text from INV135524778.pdf (regular monthly INVOICE), verified via pdfplumber.
INVOICE_TEXT = """
INVOICE
GitHub, Inc. Invoice # INV135524778
Support Contact BILL TO
Invoice Date May 15, 2026
88 Colin P. Kelly Jr. St.
Acme Inc
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
Acme Inc
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


def _rows_named(rows, metric_name):
    return [r for r in rows if r.metric_name == metric_name]


def test_detect_true_for_invoice_and_receipt():
    assert github.detect(INVOICE_TEXT) is True
    assert github.detect(RECEIPT_TEXT) is True


def test_detect_false_for_unrelated_text():
    assert github.detect("some other invoice entirely") is False


def test_parse_regular_invoice():
    # Copilot usage is billed in arrears for April; Business Cloud is billed
    # forward for the May 15 - Jun 14 cycle. Each should land in its own
    # month, with the invoice's tax split proportionally across the two.
    rows = github.parse(INVOICE_TEXT, "INV135524778.pdf")
    total_rows = _rows_named(rows, "GitHub")
    by_month = {r.metric_date: r.metric_value for r in total_rows}
    assert by_month == {date(2026, 4, 1): 103.43, date(2026, 5, 1): 342.96}
    assert all(r.source_file == "INV135524778.pdf" for r in rows)


def test_parse_regular_invoice_splits_by_product():
    rows = github.parse(INVOICE_TEXT, "INV135524778.pdf")
    by_metric = {(r.metric_name, r.metric_date): r.metric_value for r in rows if r.metric_name != "GitHub"}
    assert by_metric == {
        ("GitHub Copilot", date(2026, 4, 1)): 103.43,
        ("GitHub Seats", date(2026, 5, 1)): 342.96,
    }


def test_parse_proration_receipt():
    # Proration and Proration Credit are both seat-count adjustments, so they
    # net into GitHub Seats rather than a separate product.
    rows = github.parse(RECEIPT_TEXT, "INV121852355.pdf")
    by_metric = {(r.metric_name, r.metric_date): r.metric_value for r in rows}
    assert by_metric == {
        ("GitHub", date(2026, 2, 1)): 29.39,
        ("GitHub Seats", date(2026, 2, 1)): 29.39,
    }


# Hypothetical credit-dominant receipt: line items already show GitHub renders
# negative amounts as "$-X.XX" (see RECEIPT_TEXT above), so a negative
# INVOICE TOTAL is a plausible real-world case, not just a fuzz artifact.
NEGATIVE_TOTAL_TEXT = """
RECEIPT
GitHub, Inc. Invoice # INV999999999
Support Contact BILL TO
Invoice Date Mar 1, 2026
88 Colin P. Kelly Jr. St.
Acme Inc
San Francisco, CA 94107 Terms Due Upon Receipt
United States
QUANTITY DESCRIPTION RATE AMOUNT
GitHub Business Cloud - Month -- Proration Credit
25 $21.00 $-50.00
Feb 01, 2026 - Feb 28, 2026
SUBTOTAL: $-50.00
TAX: $0.00
INVOICE TOTAL: $-50.00
APPLIED TRANSACTIONS:
P-00000000 Mar 1, 2026 $50.00
BALANCE DUE: $0.00
""".strip()


def test_parse_negative_invoice_total_does_not_raise():
    rows = _rows_named(github.parse(NEGATIVE_TOTAL_TEXT, "INV999999999.pdf"), "GitHub")
    assert len(rows) == 1
    assert rows[0].metric_date == date(2026, 2, 1)
    assert rows[0].metric_value == -50.0


# Line items sum to a different figure than SUBTOTAL/TOTAL -- e.g. a
# transcription error on the PDF, or a fee this parser doesn't recognize as
# a line item. Should log a warning (not asserted here) but still return the
# line-item-derived rows rather than raising.
MISMATCHED_SUBTOTAL_TEXT = """
INVOICE
GitHub, Inc. Invoice # INV888888888
Support Contact BILL TO
Invoice Date Mar 1, 2026
88 Colin P. Kelly Jr. St.
Acme Inc
San Francisco, CA 94107 Terms Due Upon Receipt
United States
QUANTITY DESCRIPTION RATE AMOUNT
GitHub Copilot Usage
$95.00
Feb 01, 2026 - Feb 28, 2026
SUBTOTAL: $200.00
TAX: $0.00
INVOICE TOTAL: $200.00
APPLIED TRANSACTIONS:
P-00000001 Mar 1, 2026 -$200.00
BALANCE DUE: $0.00
""".strip()


def test_parse_mismatched_subtotal_does_not_raise():
    rows = _rows_named(github.parse(MISMATCHED_SUBTOTAL_TEXT, "INV888888888.pdf"), "GitHub")
    assert len(rows) == 1
    assert rows[0].metric_value == 95.00


# A period starting on the last calendar day of its month (e.g. after a seat
# count change shifts the subscription anchor) bills for the END month, not
# the start -- same anchoring rule as _stripe_invoice.
MONTH_END_ANCHOR_TEXT = """
INVOICE
GitHub, Inc. Invoice # INV777777777
Support Contact BILL TO
Invoice Date Aug 31, 2026
88 Colin P. Kelly Jr. St.
Acme Inc
San Francisco, CA 94107 Terms Due Upon Receipt
United States
QUANTITY DESCRIPTION RATE AMOUNT
GitHub Business Cloud - Month
10 $21.00 $210.00
Aug 31, 2026 - Sep 30, 2026
SUBTOTAL: $210.00
TAX: $0.00
INVOICE TOTAL: $210.00
APPLIED TRANSACTIONS:
P-00000002 Aug 31, 2026 -$210.00
BALANCE DUE: $0.00
""".strip()


def test_parse_attributes_month_end_anchored_period_to_the_end_month():
    rows = _rows_named(github.parse(MONTH_END_ANCHOR_TEXT, "INV777777777.pdf"), "GitHub")
    assert len(rows) == 1
    assert rows[0].metric_date == date(2026, 9, 1)
    assert rows[0].metric_value == 210.00


UNKNOWN_PRODUCT_TEXT = """
INVOICE
GitHub, Inc. Invoice # INV666666666
Support Contact BILL TO
Invoice Date Mar 1, 2026
88 Colin P. Kelly Jr. St.
Acme Inc
San Francisco, CA 94107 Terms Due Upon Receipt
United States
QUANTITY DESCRIPTION RATE AMOUNT
GitHub Advanced Security
2 $49.00 $98.00
Mar 01, 2026 - Mar 31, 2026
SUBTOTAL: $98.00
TAX: $0.00
INVOICE TOTAL: $98.00
APPLIED TRANSACTIONS:
P-00000003 Mar 1, 2026 -$98.00
BALANCE DUE: $0.00
""".strip()


def test_parse_unrecognized_product_falls_back_to_other(caplog):
    # A product this parser doesn't know yet still lands in a per-product
    # metric, so the breakdown always sums to the GitHub total.
    rows = github.parse(UNKNOWN_PRODUCT_TEXT, "INV666666666.pdf")
    by_metric = {(r.metric_name, r.metric_date): r.metric_value for r in rows}
    assert by_metric == {
        ("GitHub", date(2026, 3, 1)): 98.00,
        ("GitHub Other", date(2026, 3, 1)): 98.00,
    }
    assert any("GitHub Advanced Security" in message for message in caplog.messages)
