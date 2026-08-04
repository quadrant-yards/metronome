from datetime import date

from metronome.costs.vendors import sentry

# Real text from a Sentry invoice PDF, verified via pdfplumber
# (organization/account identifiers redacted).
INVOICE_TEXT = """
Sentry
45 Fremont Street, 8th Floor
San Francisco, CA 94105
Organization: Acme Invoice: d495e6dcd6ef454cad9e629152743520
Account: redacted@example.com Date: 09 Sep 2025
Acme Status: PAID
389 5th Ave
400
New York, NY 10016
United States of America
Description Amount
Subscription to Team
Sep 09 2025 to Oct 08 2025 $29.00 USD
50,000 reserved errors $0.00 USD
5 GB reserved logs $0.00 USD
50 reserved replays $0.00 USD
5,000,000 reserved spans $0.00 USD
1 reserved cron monitors $0.00 USD
1 reserved uptime monitors $0.00 USD
1 GB reserved attachments $0.00 USD
760 pay-as-you-go replays $2.85 USD
25.9 pay-as-you-go continuous profile hours $0.82 USD
Sales Tax $2.90 USD
Total $35.57 USD
Your subscription will automatically renew on or about the same day each month and your credit card
on file will be charged the recurring subscription fees set forth above. In addition to recurring
subscription fees, you may also be charged for monthly pay-as-you-go fees. You may cancel your
subscription at any time by visiting https://sentry.io/settings/billing/cancel/.
Questions? support@sentry.io
""".strip()


def test_detect_true_for_invoice():
    assert sentry.detect(INVOICE_TEXT) is True


def test_detect_false_for_unrelated_text():
    assert sentry.detect("some other invoice entirely") is False


def test_parse_invoice():
    rows = sentry.parse(INVOICE_TEXT, "sentry-2025-09-09.pdf")
    assert len(rows) == 1
    assert rows[0].metric_name == "Sentry"
    assert rows[0].metric_date == date(2025, 9, 1)
    assert rows[0].metric_value == 35.57
