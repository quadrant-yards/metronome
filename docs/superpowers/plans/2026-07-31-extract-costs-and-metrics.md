# Extract metronome.costs and metronome.metrics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract the generic engine behind `data-pipelines2`'s `eng_costs` and `product_analytics` pipelines into `metronome.costs` and `metronome.metrics`, then rewire `data-pipelines2` to consume them instead of keeping local copies.

**Architecture:** Two new subpackages under `src/metronome/`: `costs/` (vendor-invoice-PDF parsing → monthly cost rollup) and `metrics/` (SQL-source-driven timeseries metrics), plus two shared top-level modules (`dateparse.py`, `snowflake_conn.py`). A new `metronome.metrics.store` module factors out the DuckDB write + CSV export logic that both pipelines currently duplicate. `data-pipelines2`'s `eng_costs/` and `product_analytics/` packages shrink to thin `cli.py` wrappers that supply client-specific config (paths, env vars, collision policy, CSV floor date) to the generic `run()` functions.

**Tech Stack:** Python 3.11+, DuckDB, pdfplumber, snowflake-connector-python, cryptography, pytest, hatchling, pyenv (this machine uses pyenv + pip, not uv — `uv` is not installed here even though `data-pipelines2` has a `uv.lock`).

## Global Constraints

- Python `>=3.11` (per `metronome`'s existing `pyproject.toml`).
- Dependency versions: `duckdb>=1.4.5`, `pdfplumber>=0.11.8`, `snowflake-connector-python>=3.18.0`, `cryptography>=44.0.0`, `pytest>=8.0.0` (dev only) — copied from `data-pipelines2/scripts/metrics/requirements.txt`.
- No mocking of DuckDB in tests — use real `duckdb.connect()` against `tmp_path` files, matching the existing `data-pipelines2` test style.
- Tests are behavior-driven pytest with `tmp_path` fixtures; no test classes.
- `metronome`'s own dev/test environment is the pyenv virtualenv named `metronome` (already active via this repo's `.python-version`) — never `pyme` or `sealed`.
- `data-pipelines2` lives at `~/ghq/github.com/sealedinc/data-pipelines2` and uses the pyenv virtualenv `sealed` (Python 3.9, at `~/.pyenv/versions/3.13/envs/sealed`); its own `pip` is old (21.2.4) but supports `pip install -e`.
- Every module that's a straight port must keep the original's log messages and error text verbatim (existing tests assert on log message substrings).

---

### Task 1: Repo scaffold and dependencies

**Files:**
- Modify: `pyproject.toml`
- Create: `src/metronome/costs/__init__.py`
- Create: `src/metronome/metrics/__init__.py`

**Interfaces:**
- Produces: an installable `metronome` package (editable in its own `metronome` pyenv env) with `costs` and `metrics` as empty subpackages, ready for later tasks to populate. `pytest` runs from repo root and can import `metronome.*`.

- [ ] **Step 1: Update `pyproject.toml` with runtime deps, a dev extra, and pytest config**

Replace the full file contents with:

```toml
[project]
name = "metronome"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "duckdb>=1.4.5",
    "pdfplumber>=0.11.8",
    "snowflake-connector-python>=3.18.0",
    "cryptography>=44.0.0",
]

[project.optional-dependencies]
dev = ["pytest>=8.0.0"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/metronome"]

[tool.pytest.ini_options]
pythonpath = ["src"]
```

- [ ] **Step 2: Create the two new subpackage directories with empty `__init__.py` files**

```bash
mkdir -p src/metronome/costs/vendors src/metronome/metrics
touch src/metronome/costs/__init__.py src/metronome/metrics/__init__.py
```

(`src/metronome/costs/vendors/__init__.py` is created with real content in Task 4 — don't `touch` it here.)

- [ ] **Step 3: Install metronome (editable, with dev extras) into its own `metronome` pyenv env**

```bash
cd ~/ghq/github.com/quadrant-yards/metronome
pip install -e ".[dev]"
```

This repo's `.python-version` already pins the shell to the `metronome` pyenv env, so this `pip` is that env's `pip`.

- [ ] **Step 4: Verify the scaffold**

```bash
python -c "import metronome; print(metronome.__file__)"
pytest --collect-only
```

Expected: the `import` line prints a path ending in `.../metronome/src/metronome/__init__.py`; `pytest --collect-only` reports 0 tests collected, no errors.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml src/metronome/costs/__init__.py src/metronome/metrics/__init__.py
git commit -m "Scaffold metronome.costs and metronome.metrics packages"
```

---

### Task 2: `dateparse.py`

**Files:**
- Create: `src/metronome/dateparse.py`
- Test: `tests/test_dateparse.py`

**Interfaces:**
- Produces: `FULL_MONTHS: dict[str, int]`, `ABBREV_MONTHS: dict[str, int]`, `month_year_to_date(month_name: str, year: int, month_names: dict[str, int]) -> date`. Consumed by every vendor parser in Task 4.

- [ ] **Step 1: Write the failing test**

Create `tests/test_dateparse.py`:

```python
from datetime import date

import pytest

from metronome.dateparse import ABBREV_MONTHS, FULL_MONTHS, month_year_to_date


def test_month_year_to_date_full_month_name():
    assert month_year_to_date("January", 2026, FULL_MONTHS) == date(2026, 1, 1)


def test_month_year_to_date_abbreviated_month_name():
    assert month_year_to_date("Feb", 2026, ABBREV_MONTHS) == date(2026, 2, 1)


def test_month_year_to_date_unrecognized_month_name_raises_value_error_with_context():
    with pytest.raises(ValueError, match="Blorptember"):
        month_year_to_date("Blorptember", 2026, FULL_MONTHS)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_dateparse.py -v`
Expected: FAIL / ERROR — `ModuleNotFoundError: No module named 'metronome.dateparse'`

- [ ] **Step 3: Write the implementation**

Create `src/metronome/dateparse.py`:

```python
from __future__ import annotations

from datetime import date

FULL_MONTHS: dict[str, int] = {
    "January": 1, "February": 2, "March": 3, "April": 4,
    "May": 5, "June": 6, "July": 7, "August": 8,
    "September": 9, "October": 10, "November": 11, "December": 12,
}

ABBREV_MONTHS: dict[str, int] = {
    "Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
    "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12,
}


def month_year_to_date(month_name: str, year: int, month_names: dict[str, int]) -> date:
    """Convert a month name + year into the first-of-month date."""
    try:
        month_number = month_names[month_name]
    except KeyError:
        raise ValueError(f"unrecognized month name: {month_name!r}") from None
    return date(year, month_number, 1)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_dateparse.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add src/metronome/dateparse.py tests/test_dateparse.py
git commit -m "Add metronome.dateparse"
```

---

### Task 3: `costs/models.py` and `costs/pdf_text.py`

**Files:**
- Create: `src/metronome/costs/models.py`
- Create: `src/metronome/costs/pdf_text.py`
- Test: `tests/costs/test_pdf_text.py`

**Interfaces:**
- Produces: `CostRow` frozen dataclass (`metric_name: str`, `metric_date: date`, `metric_value: float | None`, `source_file: str | None`, `statement_date: date | None = None`); `extract_text(path: Path) -> str`. Consumed by every vendor parser (Task 4), `costs/rollup.py` (Task 5), and `costs/pipeline.py` (Task 7).
- `CostRow` has no dedicated unit test file — it's a plain dataclass exercised through `rollup`/`pipeline` tests, matching the source repo's convention (it wasn't tested directly there either).

- [ ] **Step 1: Write the failing test for `pdf_text`**

Create `tests/costs/test_pdf_text.py`:

```python
from unittest.mock import MagicMock, patch

from metronome.costs.pdf_text import extract_text


def test_extract_text_joins_pages_with_newlines(tmp_path):
    pdf_path = tmp_path / "invoice.pdf"
    pdf_path.write_bytes(b"")

    page1 = MagicMock()
    page1.extract_text.return_value = "Page one text"
    page2 = MagicMock()
    page2.extract_text.return_value = "Page two text"

    fake_pdf = MagicMock()
    fake_pdf.pages = [page1, page2]
    fake_pdf.__enter__.return_value = fake_pdf
    fake_pdf.__exit__.return_value = False

    with patch("pdfplumber.open", return_value=fake_pdf) as mock_open:
        result = extract_text(pdf_path)

    mock_open.assert_called_once_with(pdf_path)
    assert result == "Page one text\nPage two text"


def test_extract_text_treats_a_page_with_no_extractable_text_as_empty_string(tmp_path):
    pdf_path = tmp_path / "blank.pdf"
    pdf_path.write_bytes(b"")

    blank_page = MagicMock()
    blank_page.extract_text.return_value = None
    text_page = MagicMock()
    text_page.extract_text.return_value = "Some text"

    fake_pdf = MagicMock()
    fake_pdf.pages = [blank_page, text_page]
    fake_pdf.__enter__.return_value = fake_pdf
    fake_pdf.__exit__.return_value = False

    with patch("pdfplumber.open", return_value=fake_pdf):
        result = extract_text(pdf_path)

    assert result == "\nSome text"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/costs/test_pdf_text.py -v`
Expected: FAIL / ERROR — `ModuleNotFoundError: No module named 'metronome.costs.pdf_text'`

- [ ] **Step 3: Write the implementation**

Create `src/metronome/costs/models.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class CostRow:
    """One (vendor, month) cost observation.

    `metric_value` and `source_file` are None only for gap-filled rows
    produced by rollup.resolve_monthly() — a month with no source data.
    `statement_date` is set only by the Snowflake parser, where it's used
    to break ties between overlapping cumulative statements (see rollup.py).
    """

    metric_name: str
    metric_date: date
    metric_value: float | None
    source_file: str | None
    statement_date: date | None = None
```

Create `src/metronome/costs/pdf_text.py`:

```python
from __future__ import annotations

from pathlib import Path

import pdfplumber


def extract_text(path: Path) -> str:
    """Extract all text from a PDF, pages joined with newlines."""
    with pdfplumber.open(path) as pdf:
        return "\n".join(page.extract_text() or "" for page in pdf.pages)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/costs/test_pdf_text.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add src/metronome/costs/models.py src/metronome/costs/pdf_text.py tests/costs/test_pdf_text.py
git commit -m "Add metronome.costs.models and metronome.costs.pdf_text"
```

---

### Task 4: Vendor invoice parsers

**Files:**
- Create: `src/metronome/costs/vendors/dagster.py`
- Create: `src/metronome/costs/vendors/gcp.py`
- Create: `src/metronome/costs/vendors/github.py`
- Create: `src/metronome/costs/vendors/hex.py`
- Create: `src/metronome/costs/vendors/snowflake.py`
- Create: `src/metronome/costs/vendors/__init__.py`
- Test: `tests/costs/vendors/test_dagster.py`
- Test: `tests/costs/vendors/test_gcp.py`
- Test: `tests/costs/vendors/test_github.py`
- Test: `tests/costs/vendors/test_hex.py`
- Test: `tests/costs/vendors/test_snowflake.py`
- Test: `tests/costs/vendors/test_registry.py`

**Interfaces:**
- Consumes: `CostRow` from `metronome.costs.models` (Task 3), `FULL_MONTHS`/`ABBREV_MONTHS`/`month_year_to_date` from `metronome.dateparse` (Task 2).
- Produces: each vendor module exposes `detect(text: str) -> bool` and `parse(text: str, source_file: str) -> list[CostRow]`. `metronome.costs.vendors.ALL: list[ModuleType]` — the default registry `[dagster, gcp, github, hex, snowflake]`. Consumed by `costs/pipeline.py` (Task 7).

These are straight ports — every module and test body below is copied verbatim from `data-pipelines2/scripts/metrics/eng_costs/vendors/*.py` and `data-pipelines2/tests/metrics/eng_costs/test_*.py`, with only the import paths changed (`scripts.metrics.eng_costs.*` → `metronome.*`).

- [ ] **Step 1: Write the failing tests for all 5 vendors**

Create `tests/costs/vendors/test_dagster.py`:

```python
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
```

Create `tests/costs/vendors/test_gcp.py`:

```python
from datetime import date

from metronome.costs.vendors import gcp

# Real text from INV-US-26007303.pdf (current template), verified via pdfplumber.
CURRENT_TEMPLATE_TEXT = """
DOIT INTERNATIONAL USA INC
5201 Great America Parkway, Suite 320
Attn: Eric Born Details: Covering April 2026
Tel: +9727149325223 Tax ID: 453478769
TAX INVOICE No: INV-US-26007303
Google Cloud Project 'sealed-prod' 1 USD1,787.90 1,787.90
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
Google Cloud Project 'sealed-dev' 1 USD 1,280.10 1,280.10
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
Google Cloud Project 'sealed-dev' 1 1,282.05 1,282.05
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
```

Create `tests/costs/vendors/test_github.py`:

```python
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
```

Create `tests/costs/vendors/test_hex.py`:

```python
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
```

Create `tests/costs/vendors/test_snowflake.py`:

```python
from datetime import date

from metronome.costs.vendors import snowflake

# Trimmed from a real cumulative statement (2023-07), which packs many
# MONTHLY USAGE blocks into one PDF. Oct-2022 has no OVERAGE- rows (still
# inside prepaid capacity); the pre-summed "... TOTAL" row is 28.53 but
# that's capacity drawdown, not new cost -- correct answer is $0.00.
CUMULATIVE_STATEMENT_TEXT = """
USAGE STATEMENT
CUSTOMER: Sealed STATEMENT DATE: 07/31/2023
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
CUSTOMER: Sealed STATEMENT DATE: 02/28/2026
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
```

Create `tests/costs/vendors/test_registry.py`:

```python
from metronome.costs.vendors import ALL, dagster, gcp, github, hex, snowflake


def test_all_contains_every_vendor_module_exactly_once():
    assert set(ALL) == {dagster, gcp, github, hex, snowflake}
    assert len(ALL) == len(set(ALL))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/costs/vendors/ -v`
Expected: FAIL / ERROR on every test — `ModuleNotFoundError: No module named 'metronome.costs.vendors'`

- [ ] **Step 3: Write the implementations**

Create `src/metronome/costs/vendors/dagster.py`:

```python
from __future__ import annotations

import re

from metronome.dateparse import FULL_MONTHS, month_year_to_date
from metronome.costs.models import CostRow

_DATE_OF_ISSUE_RE = re.compile(r"Date of issue\s+([A-Za-z]+) (\d{1,2}), (\d{4})")
_AMOUNT_DUE_RE = re.compile(r"Amount due\s+\$([\d,]+\.\d{2})\s+USD")


def detect(text: str) -> bool:
    return "dagsterlabs.com" in text.lower()


def parse(text: str, source_file: str) -> list[CostRow]:
    issue_match = _DATE_OF_ISSUE_RE.search(text)
    amount_match = _AMOUNT_DUE_RE.search(text)
    if not issue_match or not amount_match:
        raise ValueError(f"could not parse Dagster invoice: {source_file}")

    month_name, _day, year = issue_match.groups()
    metric_date = month_year_to_date(month_name, int(year), FULL_MONTHS)
    metric_value = float(amount_match.group(1).replace(",", ""))

    return [
        CostRow(
            metric_name="Dagster",
            metric_date=metric_date,
            metric_value=metric_value,
            source_file=source_file,
        )
    ]
```

Create `src/metronome/costs/vendors/gcp.py`:

```python
from __future__ import annotations

import re

from metronome.dateparse import FULL_MONTHS, month_year_to_date
from metronome.costs.models import CostRow

_COVERING_RE = re.compile(r"Covering ([A-Za-z]+) (\d{4})")
# Anchor-free on purpose -- see Background note above. Matches "total"
# only when immediately followed (whitespace only) by a currency marker,
# which naturally excludes "Total Before ..." / "Total Price ...".
_TOTAL_RE = re.compile(r"(?i)\btotal\s+(?:usd\s*|\$)\s*([\d,]+\.\d{2})")


def detect(text: str) -> bool:
    return "DOIT INTERNATION" in text.upper()


def parse(text: str, source_file: str) -> list[CostRow]:
    covering_match = _COVERING_RE.search(text)
    total_matches = _TOTAL_RE.findall(text)
    if not covering_match or not total_matches:
        raise ValueError(f"could not parse GCP/DoiT invoice: {source_file}")

    month_name, year = covering_match.groups()
    metric_date = month_year_to_date(month_name, int(year), FULL_MONTHS)
    metric_value = float(total_matches[-1].replace(",", ""))

    return [
        CostRow(
            metric_name="GCP",
            metric_date=metric_date,
            metric_value=metric_value,
            source_file=source_file,
        )
    ]
```

Create `src/metronome/costs/vendors/github.py`:

```python
from __future__ import annotations

import re

from metronome.dateparse import ABBREV_MONTHS, month_year_to_date
from metronome.costs.models import CostRow

_INVOICE_DATE_RE = re.compile(r"Invoice Date\s+([A-Za-z]{3}) (\d{1,2}), (\d{4})")
_INVOICE_TOTAL_RE = re.compile(r"INVOICE TOTAL:\s*\$(-?[\d,]+\.\d{2})")


def detect(text: str) -> bool:
    return "GitHub, Inc." in text


def parse(text: str, source_file: str) -> list[CostRow]:
    date_match = _INVOICE_DATE_RE.search(text)
    total_match = _INVOICE_TOTAL_RE.search(text)
    if not date_match or not total_match:
        raise ValueError(f"could not parse GitHub invoice: {source_file}")

    month_name, _day, year = date_match.groups()
    metric_date = month_year_to_date(month_name, int(year), ABBREV_MONTHS)
    metric_value = float(total_match.group(1).replace(",", ""))

    return [
        CostRow(
            metric_name="GitHub",
            metric_date=metric_date,
            metric_value=metric_value,
            source_file=source_file,
        )
    ]
```

Create `src/metronome/costs/vendors/hex.py`:

```python
from __future__ import annotations

import re

from metronome.dateparse import FULL_MONTHS, month_year_to_date
from metronome.costs.models import CostRow

_DATE_OF_ISSUE_RE = re.compile(r"Date of issue\s+([A-Za-z]+) (\d{1,2}), (\d{4})")
_AMOUNT_DUE_RE = re.compile(r"Amount due\s+\$([\d,]+\.\d{2})\s+USD")


def detect(text: str) -> bool:
    return "hex.tech" in text.lower()


def parse(text: str, source_file: str) -> list[CostRow]:
    issue_match = _DATE_OF_ISSUE_RE.search(text)
    amount_match = _AMOUNT_DUE_RE.search(text)
    if not issue_match or not amount_match:
        raise ValueError(f"could not parse Hex invoice: {source_file}")

    month_name, _day, year = issue_match.groups()
    metric_date = month_year_to_date(month_name, int(year), FULL_MONTHS)
    metric_value = float(amount_match.group(1).replace(",", ""))

    return [
        CostRow(
            metric_name="Hex",
            metric_date=metric_date,
            metric_value=metric_value,
            source_file=source_file,
        )
    ]
```

Create `src/metronome/costs/vendors/snowflake.py`:

```python
from __future__ import annotations

import re
from datetime import date

from metronome.dateparse import ABBREV_MONTHS, month_year_to_date
from metronome.costs.models import CostRow

_STATEMENT_DATE_RE = re.compile(r"STATEMENT DATE:\s*(\d{2})/(\d{2})/(\d{4})")
_USAGE_MONTH_RE = re.compile(r"^([A-Za-z]{3})-(\d{4})$")


def detect(text: str) -> bool:
    return "USAGE STATEMENT" in text and "MONTHLY USAGE" in text


def _parse_amount(token: str) -> float:
    token = token.replace(",", "")
    if token.startswith("(") and token.endswith(")"):
        return -float(token[1:-1])
    return float(token)


def _parse_usage_month(token: str) -> date | None:
    match = _USAGE_MONTH_RE.match(token)
    if not match:
        return None
    month_name, year = match.groups()
    return month_year_to_date(month_name, int(year), ABBREV_MONTHS)


def _statement_date(text: str) -> date | None:
    match = _STATEMENT_DATE_RE.search(text)
    if not match:
        return None
    month, day, year = match.groups()
    return date(int(year), int(month), int(day))


def parse(text: str, source_file: str) -> list[CostRow]:
    stmt_date = _statement_date(text)
    overage_totals: dict[date, float] = {}
    months_seen: set[date] = set()

    for line in text.splitlines():
        tokens = line.split()
        if len(tokens) < 4:
            continue
        usage_month = _parse_usage_month(tokens[0])
        if usage_month is None:
            continue
        category = " ".join(tokens[1:-2])
        units_token, total_token = tokens[-2], tokens[-1]
        if not category:
            continue
        try:
            total = _parse_amount(total_token)
        except ValueError:
            continue

        months_seen.add(usage_month)
        if category.endswith("TOTAL") and units_token == "N/A":
            # Pre-summed capacity-drawdown row, not a grand total -- ignored.
            continue
        if category.startswith("OVERAGE-"):
            overage_totals[usage_month] = overage_totals.get(usage_month, 0.0) + total

    return [
        CostRow(
            metric_name="Snowflake",
            metric_date=month,
            metric_value=round(overage_totals.get(month, 0.0), 2),
            source_file=source_file,
            statement_date=stmt_date,
        )
        for month in sorted(months_seen)
    ]
```

Create `src/metronome/costs/vendors/__init__.py`:

```python
from __future__ import annotations

from metronome.costs.vendors import dagster, gcp, github, hex, snowflake

ALL = [dagster, gcp, github, hex, snowflake]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/costs/vendors/ -v`
Expected: PASS (all tests pass — 5 dagster/hex + 6 gcp + 5 github + 1 registry + 3 snowflake, exact count doesn't matter, just zero failures)

- [ ] **Step 5: Commit**

```bash
git add src/metronome/costs/vendors/ tests/costs/vendors/
git commit -m "Add metronome.costs.vendors (Dagster, GCP, GitHub, Hex, Snowflake invoice parsers)"
```

---

### Task 5: `costs/rollup.py`

**Files:**
- Create: `src/metronome/costs/rollup.py`
- Test: `tests/costs/test_rollup.py`

**Interfaces:**
- Consumes: `CostRow` from `metronome.costs.models` (Task 3).
- Produces: `resolve_monthly(rows: list[CostRow], sum_on_collision: frozenset[str] = frozenset()) -> list[CostRow]`. Consumed by `costs/pipeline.py` (Task 7). `sum_on_collision` replaces the original's hardcoded `_SUM_ON_COLLISION = {"GitHub"}` module constant — callers now opt in per-vendor.

- [ ] **Step 1: Write the failing test**

Create `tests/costs/test_rollup.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/costs/test_rollup.py -v`
Expected: FAIL / ERROR — `ModuleNotFoundError: No module named 'metronome.costs.rollup'`

- [ ] **Step 3: Write the implementation**

Create `src/metronome/costs/rollup.py`:

```python
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date

from metronome.costs.models import CostRow

logger = logging.getLogger(__name__)


def _next_month(current: date) -> date:
    if current.month == 12:
        return date(current.year + 1, 1, 1)
    return date(current.year, current.month + 1, 1)


def _month_range(start: date, end: date) -> list[date]:
    months = []
    current = start
    while current <= end:
        months.append(current)
        current = _next_month(current)
    return months


def _resolve_group(
    vendor: str, month: date, group: list[CostRow], sum_on_collision: frozenset[str]
) -> CostRow:
    if len(group) == 1:
        return group[0]

    distinct_values = {round(r.metric_value, 2) for r in group}

    if vendor in sum_on_collision:
        total = sum(r.metric_value for r in group)
        return CostRow(
            metric_name=vendor,
            metric_date=month,
            metric_value=round(total, 2),
            source_file="; ".join(r.source_file for r in group),
        )

    with_statement_date = [r for r in group if r.statement_date is not None]
    if with_statement_date:
        best = max(with_statement_date, key=lambda r: r.statement_date)
        if len(distinct_values) > 1:
            logger.warning(
                "%s %s has conflicting values across statements %s; using %s (latest statement_date)",
                vendor, month.isoformat(), [r.source_file for r in group], best.source_file,
            )
        return best

    if len(distinct_values) > 1:
        logger.warning(
            "%s %s has %d unexpected source files with differing values %s; keeping first encountered: %s",
            vendor, month.isoformat(), len(group), [r.source_file for r in group], group[0].source_file,
        )
    else:
        logger.warning(
            "%s %s has %d unexpected source files mapping to the same month with matching values %s; "
            "keeping first encountered: %s",
            vendor, month.isoformat(), len(group), [r.source_file for r in group], group[0].source_file,
        )
    return group[0]


def resolve_monthly(
    rows: list[CostRow],
    sum_on_collision: frozenset[str] = frozenset(),
) -> list[CostRow]:
    """Collapse raw per-file rows into one row per (vendor, month), then
    gap-fill every vendor's month range with NULL rows for missing months."""
    grouped: dict[tuple[str, date], list[CostRow]] = defaultdict(list)
    for row in rows:
        grouped[(row.metric_name, row.metric_date)].append(row)

    resolved: dict[tuple[str, date], CostRow] = {
        key: _resolve_group(key[0], key[1], group, sum_on_collision) for key, group in grouped.items()
    }

    output: list[CostRow] = []
    vendors = sorted({vendor for vendor, _ in resolved})
    for vendor in vendors:
        vendor_months = sorted(month for (v, month) in resolved if v == vendor)
        for month in _month_range(vendor_months[0], vendor_months[-1]):
            if (vendor, month) in resolved:
                output.append(resolved[(vendor, month)])
            else:
                output.append(CostRow(metric_name=vendor, metric_date=month, metric_value=None, source_file=None))
    return output
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/costs/test_rollup.py -v`
Expected: PASS (9 passed)

- [ ] **Step 5: Commit**

```bash
git add src/metronome/costs/rollup.py tests/costs/test_rollup.py
git commit -m "Add metronome.costs.rollup with a parameterized sum_on_collision policy"
```

---

### Task 6: `metrics/models.py` and `metrics/store.py`

**Files:**
- Create: `src/metronome/metrics/models.py`
- Create: `src/metronome/metrics/store.py`
- Test: `tests/metrics/test_store.py`

**Interfaces:**
- Produces: `MetricRow` frozen dataclass (`metric_name: str`, `metric_date: date`, `metric_value: float`). `write_replace(con, table, columns, rows)`, `write_upsert(con, table, columns, key_columns, rows)`, `export_csv(con, query, params, csv_path)`, `trailing_window_start(anchor, count, unit, floor=None)`. Consumed by `costs/pipeline.py` (Task 7) and `metrics/pipeline.py` (Task 10).
- `MetricRow` has no dedicated unit test file, matching the source repo's convention — it's exercised through `metrics/pipeline.py` and `metrics/sql_runner.py` tests.
- This module is new, not a port — `write_replace`/`write_upsert`/`export_csv`/`trailing_window_start` don't exist in `data-pipelines2` as standalone functions, so their tests are new too.

- [ ] **Step 1: Write the failing test**

Create `tests/metrics/test_store.py`:

```python
from datetime import date, timedelta

import duckdb

from metronome.metrics.store import export_csv, trailing_window_start, write_replace, write_upsert


def test_write_replace_creates_table_and_inserts_rows(tmp_path):
    db_path = tmp_path / "test.db"
    con = duckdb.connect(str(db_path))
    try:
        write_replace(
            con, "widgets",
            [("name", "VARCHAR"), ("count", "INTEGER")],
            [("a", 1), ("b", 2)],
        )
        result = con.execute("SELECT name, count FROM widgets ORDER BY name").fetchall()
    finally:
        con.close()
    assert result == [("a", 1), ("b", 2)]


def test_write_replace_drops_previous_contents_on_rerun(tmp_path):
    db_path = tmp_path / "test.db"
    con = duckdb.connect(str(db_path))
    try:
        write_replace(con, "widgets", [("name", "VARCHAR")], [("a",), ("b",)])
        write_replace(con, "widgets", [("name", "VARCHAR")], [("c",)])
        result = con.execute("SELECT name FROM widgets").fetchall()
    finally:
        con.close()
    assert result == [("c",)]


def test_write_replace_with_no_rows_creates_an_empty_table(tmp_path):
    db_path = tmp_path / "test.db"
    con = duckdb.connect(str(db_path))
    try:
        write_replace(con, "widgets", [("name", "VARCHAR")], [])
        count = con.execute("SELECT COUNT(*) FROM widgets").fetchone()[0]
    finally:
        con.close()
    assert count == 0


def test_write_upsert_creates_table_on_first_call(tmp_path):
    db_path = tmp_path / "test.db"
    con = duckdb.connect(str(db_path))
    try:
        write_upsert(
            con, "widgets",
            [("name", "VARCHAR"), ("count", "INTEGER")],
            key_columns=["name"],
            rows=[("a", 1)],
        )
        result = con.execute("SELECT name, count FROM widgets").fetchall()
    finally:
        con.close()
    assert result == [("a", 1)]


def test_write_upsert_replaces_rows_matching_the_same_key(tmp_path):
    db_path = tmp_path / "test.db"
    con = duckdb.connect(str(db_path))
    try:
        write_upsert(con, "widgets", [("name", "VARCHAR"), ("count", "INTEGER")], ["name"], [("a", 1)])
        write_upsert(con, "widgets", [("name", "VARCHAR"), ("count", "INTEGER")], ["name"], [("a", 2)])
        result = con.execute("SELECT name, count FROM widgets").fetchall()
    finally:
        con.close()
    assert result == [("a", 2)]


def test_write_upsert_leaves_rows_with_a_different_key_untouched(tmp_path):
    db_path = tmp_path / "test.db"
    con = duckdb.connect(str(db_path))
    try:
        write_upsert(con, "widgets", [("name", "VARCHAR"), ("count", "INTEGER")], ["name"], [("a", 1)])
        write_upsert(con, "widgets", [("name", "VARCHAR"), ("count", "INTEGER")], ["name"], [("b", 2)])
        result = con.execute("SELECT name, count FROM widgets ORDER BY name").fetchall()
    finally:
        con.close()
    assert result == [("a", 1), ("b", 2)]


def test_write_upsert_supports_composite_keys(tmp_path):
    db_path = tmp_path / "test.db"
    con = duckdb.connect(str(db_path))
    try:
        columns = [("name", "VARCHAR"), ("period", "DATE"), ("count", "INTEGER")]
        write_upsert(con, "widgets", columns, ["name", "period"], [("a", date(2026, 1, 1), 1)])
        write_upsert(con, "widgets", columns, ["name", "period"], [("a", date(2026, 1, 1), 9)])
        result = con.execute("SELECT name, period, count FROM widgets").fetchall()
    finally:
        con.close()
    assert result == [("a", date(2026, 1, 1), 9)]


def test_export_csv_writes_headered_csv(tmp_path):
    db_path = tmp_path / "test.db"
    csv_path = tmp_path / "out.csv"
    con = duckdb.connect(str(db_path))
    try:
        write_replace(con, "widgets", [("name", "VARCHAR"), ("count", "INTEGER")], [("a", 1)])
        export_csv(con, "SELECT name, count FROM widgets", [], csv_path)
    finally:
        con.close()
    assert csv_path.read_text().strip().splitlines() == ["name,count", "a,1"]


def test_export_csv_applies_query_params(tmp_path):
    db_path = tmp_path / "test.db"
    csv_path = tmp_path / "out.csv"
    con = duckdb.connect(str(db_path))
    try:
        write_replace(con, "widgets", [("name", "VARCHAR"), ("count", "INTEGER")], [("a", 1), ("b", 2)])
        export_csv(con, "SELECT name, count FROM widgets WHERE count >= ?", [2], csv_path)
    finally:
        con.close()
    assert csv_path.read_text().strip().splitlines() == ["name,count", "b,2"]


def test_trailing_window_start_months_shifts_back_count_minus_one_months():
    assert trailing_window_start(date(2026, 6, 1), 12, "months") == date(2025, 7, 1)


def test_trailing_window_start_months_handles_year_rollover():
    assert trailing_window_start(date(2026, 1, 1), 3, "months") == date(2025, 11, 1)


def test_trailing_window_start_weeks_shifts_back_count_minus_one_weeks():
    anchor = date(2026, 7, 27)
    assert trailing_window_start(anchor, 12, "weeks") == anchor - timedelta(weeks=11)


def test_trailing_window_start_clamps_to_floor_when_window_would_go_earlier():
    result = trailing_window_start(date(2026, 6, 1), 12, "months", floor=date(2025, 11, 1))
    assert result == date(2025, 11, 1)


def test_trailing_window_start_does_not_clamp_when_window_is_already_past_floor():
    result = trailing_window_start(date(2027, 3, 1), 12, "months", floor=date(2025, 11, 1))
    assert result == date(2026, 4, 1)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/metrics/test_store.py -v`
Expected: FAIL / ERROR — `ModuleNotFoundError: No module named 'metronome.metrics.store'`

- [ ] **Step 3: Write the implementation**

Create `src/metronome/metrics/models.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class MetricRow:
    metric_name: str
    metric_date: date
    metric_value: float
```

Create `src/metronome/metrics/store.py`:

```python
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from typing import Literal

import duckdb


def write_replace(
    con: duckdb.DuckDBPyConnection,
    table: str,
    columns: list[tuple[str, str]],
    rows: list[tuple],
) -> None:
    """Drop and recreate `table`, then insert `rows`.

    `columns` is a list of (name, sql_type) pairs defining the table's schema.
    """
    col_defs = ", ".join(f"{name} {sql_type}" for name, sql_type in columns)
    con.execute(f"DROP TABLE IF EXISTS {table}")
    con.execute(f"CREATE TABLE {table} ({col_defs})")
    if rows:
        placeholders = ", ".join("?" for _ in columns)
        con.executemany(f"INSERT INTO {table} VALUES ({placeholders})", rows)


def write_upsert(
    con: duckdb.DuckDBPyConnection,
    table: str,
    columns: list[tuple[str, str]],
    key_columns: list[str],
    rows: list[tuple],
) -> None:
    """Create `table` if missing, delete rows matching each row's key columns, then insert `rows`."""
    col_defs = ", ".join(f"{name} {sql_type}" for name, sql_type in columns)
    con.execute(f"CREATE TABLE IF NOT EXISTS {table} ({col_defs})")

    column_names = [name for name, _ in columns]
    key_indexes = [column_names.index(key) for key in key_columns]
    keys = {tuple(row[i] for i in key_indexes) for row in rows}
    where_clause = " AND ".join(f"{key} = ?" for key in key_columns)
    for key_values in keys:
        con.execute(f"DELETE FROM {table} WHERE {where_clause}", list(key_values))

    if rows:
        placeholders = ", ".join("?" for _ in columns)
        con.executemany(f"INSERT INTO {table} VALUES ({placeholders})", rows)


def export_csv(
    con: duckdb.DuckDBPyConnection,
    query: str,
    params: list,
    csv_path: Path,
) -> None:
    """Run `query` and COPY its results to `csv_path` as a headered CSV."""
    csv_path_str = str(csv_path).replace("'", "''")
    con.execute(f"COPY ({query}) TO '{csv_path_str}' (HEADER, DELIMITER ',')", params)


def trailing_window_start(
    anchor: date,
    count: int,
    unit: Literal["months", "weeks"],
    floor: date | None = None,
) -> date:
    """Return the start of a trailing `count`-`unit` window ending at `anchor`
    (inclusive), clamped to `floor` if given."""
    if unit == "months":
        total = anchor.year * 12 + (anchor.month - 1) - (count - 1)
        year, month = divmod(total, 12)
        window_start = date(year, month + 1, 1)
    else:
        window_start = anchor - timedelta(weeks=count - 1)

    if floor is not None:
        return max(window_start, floor)
    return window_start
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/metrics/test_store.py -v`
Expected: PASS (15 passed)

- [ ] **Step 5: Commit**

```bash
git add src/metronome/metrics/models.py src/metronome/metrics/store.py tests/metrics/test_store.py
git commit -m "Add metronome.metrics.models and metronome.metrics.store"
```

---

### Task 7: `costs/pipeline.py`

**Files:**
- Create: `src/metronome/costs/pipeline.py`
- Test: `tests/costs/test_pipeline.py`

**Interfaces:**
- Consumes: `CostRow` (Task 3), `extract_text` (Task 3), `vendors.ALL` (Task 4), `resolve_monthly` (Task 5), `write_replace`/`export_csv`/`trailing_window_start` from `metronome.metrics.store` (Task 6).
- Produces: `parse_all(downloads_dir, text_extractor=extract_text, vendor_modules=None) -> list[CostRow]`, `count_new_rows(raw_rows, previous) -> dict[str, int]`, `write_outputs(raw_rows, monthly_rows, db_path, csv_path, csv_export_months=12, csv_export_floor=None) -> None`, `run(downloads_dir, db_path, csv_path, text_extractor=extract_text, vendor_modules=None, sum_on_collision=frozenset(), csv_export_months=12, csv_export_floor=None) -> None`. Consumed by `data-pipelines2`'s `eng_costs/cli.py` (Task 12).

- [ ] **Step 1: Write the failing test**

Create `tests/costs/test_pipeline.py`:

```python
import logging
from datetime import date
from pathlib import Path

import duckdb

from metronome.costs.models import CostRow
from metronome.costs.pipeline import count_new_rows, parse_all, run, write_outputs

SNOWFLAKE_TEXT = """
USAGE STATEMENT
CUSTOMER: Sealed STATEMENT DATE: 02/28/2026
MONTHLY USAGE
USAGE MONTH USAGE CATEGORY UNITS CONSUMED TOTAL USAGE (USD)
Feb-2026 OVERAGE-COMPUTE 359.065 718.13
Feb-2026 AZ72662-GCP-US-EAST4 TOTAL N/A 0.00
""".strip()

DAGSTER_TEXT = """
Invoice
Date of issue January 1, 2026
billing@dagsterlabs.com
Amount due $124.56 USD
""".strip()


def _fake_extractor(mapping: dict[str, str]):
    def _extract(path: Path) -> str:
        return mapping[path.name]

    return _extract


def test_parse_all_dispatches_each_file_to_the_matching_vendor(tmp_path):
    (tmp_path / "a.pdf").write_bytes(b"")
    (tmp_path / "b.pdf").write_bytes(b"")
    extractor = _fake_extractor({"a.pdf": SNOWFLAKE_TEXT, "b.pdf": DAGSTER_TEXT})

    rows = parse_all(tmp_path, extractor)

    names = {r.metric_name for r in rows}
    assert names == {"Snowflake", "Dagster"}


def test_parse_all_skips_files_matching_no_vendor(tmp_path, caplog):
    (tmp_path / "mystery.pdf").write_bytes(b"")
    extractor = _fake_extractor({"mystery.pdf": "totally unrelated content"})

    with caplog.at_level(logging.WARNING):
        rows = parse_all(tmp_path, extractor)

    assert rows == []
    assert any("mystery.pdf" in message for message in caplog.messages)


POISON_DAGSTER_TEXT = """
Invoice
Date of issue Blorptember 1, 2026
billing@dagsterlabs.com
Amount due $999.99 USD
""".strip()


def test_parse_all_skips_poisoned_file_but_still_parses_the_rest(tmp_path, caplog):
    (tmp_path / "good_sf.pdf").write_bytes(b"")
    (tmp_path / "poison.pdf").write_bytes(b"")
    (tmp_path / "good_dg.pdf").write_bytes(b"")
    extractor = _fake_extractor(
        {
            "good_sf.pdf": SNOWFLAKE_TEXT,
            "poison.pdf": POISON_DAGSTER_TEXT,
            "good_dg.pdf": DAGSTER_TEXT,
        }
    )

    with caplog.at_level(logging.ERROR):
        rows = parse_all(tmp_path, extractor)

    names = {r.metric_name for r in rows}
    assert names == {"Snowflake", "Dagster"}
    assert len(rows) == 2

    error_messages = [r.message for r in caplog.records if r.levelno == logging.ERROR]
    assert any("poison.pdf" in message for message in error_messages)


def test_run_writes_duckdb_tables_and_csv(tmp_path):
    (tmp_path / "downloads").mkdir()
    (tmp_path / "downloads" / "sf.pdf").write_bytes(b"")
    (tmp_path / "downloads" / "dg.pdf").write_bytes(b"")
    extractor = _fake_extractor({"sf.pdf": SNOWFLAKE_TEXT, "dg.pdf": DAGSTER_TEXT})

    db_path = tmp_path / "metrics.db"
    csv_path = tmp_path / "data-monthly.csv"

    run(tmp_path / "downloads", db_path, csv_path, extractor)

    con = duckdb.connect(str(db_path))
    raw_count = con.execute("SELECT COUNT(*) FROM raw_costs").fetchone()[0]
    monthly = con.execute(
        "SELECT metric_name, metric_date, metric_value FROM monthly_costs ORDER BY metric_name"
    ).fetchall()
    con.close()

    assert raw_count == 2
    assert monthly == [
        ("Dagster", date(2026, 1, 1), 124.56),
        ("Snowflake", date(2026, 2, 1), 718.13),
    ]

    csv_text = csv_path.read_text()
    assert "metric_name,metric_date,metric_value" in csv_text
    assert "Dagster,2026-01-01,124.56" in csv_text
    assert "Snowflake,2026-02-01,718.13" in csv_text


def test_run_against_empty_downloads_dir_succeeds_with_empty_outputs(tmp_path):
    (tmp_path / "downloads").mkdir()
    extractor = _fake_extractor({})

    db_path = tmp_path / "metrics.db"
    csv_path = tmp_path / "data-monthly.csv"

    run(tmp_path / "downloads", db_path, csv_path, extractor)

    con = duckdb.connect(str(db_path))
    raw_count = con.execute("SELECT COUNT(*) FROM raw_costs").fetchone()[0]
    monthly_count = con.execute("SELECT COUNT(*) FROM monthly_costs").fetchone()[0]
    con.close()

    assert raw_count == 0
    assert monthly_count == 0

    csv_text = csv_path.read_text()
    assert csv_text.strip() == "metric_name,metric_date,metric_value"


def test_run_is_idempotent_across_repeated_calls(tmp_path):
    (tmp_path / "downloads").mkdir()
    (tmp_path / "downloads" / "sf.pdf").write_bytes(b"")
    extractor = _fake_extractor({"sf.pdf": SNOWFLAKE_TEXT})
    db_path = tmp_path / "metrics.db"
    csv_path = tmp_path / "data-monthly.csv"

    run(tmp_path / "downloads", db_path, csv_path, extractor)
    run(tmp_path / "downloads", db_path, csv_path, extractor)

    con = duckdb.connect(str(db_path))
    count = con.execute("SELECT COUNT(*) FROM monthly_costs").fetchone()[0]
    con.close()
    assert count == 1


def test_write_outputs_clamps_csv_export_to_a_floor(tmp_path):
    raw_rows = [CostRow("X", date(2024, 1, 1), 1.0, "f1.pdf")]
    monthly_rows = [
        CostRow("X", date(2024, 1, 1), 1.0, "f1.pdf"),
        CostRow("X", date(2025, 10, 1), 2.0, "f1.pdf"),
        CostRow("X", date(2025, 11, 1), 3.0, "f1.pdf"),
        CostRow("X", date(2026, 6, 1), 4.0, "f1.pdf"),
    ]
    db_path = tmp_path / "metrics.db"
    csv_path = tmp_path / "out.csv"

    write_outputs(raw_rows, monthly_rows, db_path, csv_path, csv_export_floor=date(2025, 11, 1))

    con = duckdb.connect(str(db_path))
    monthly_count = con.execute("SELECT COUNT(*) FROM monthly_costs").fetchone()[0]
    con.close()
    # DuckDB table keeps full history regardless of the CSV window
    assert monthly_count == 4

    csv_text = csv_path.read_text()
    # anchor = 2026-06-01; window_start = 2025-07-01; floor 2025-11-01 wins
    assert "2024-01-01" not in csv_text
    assert "2025-10-01" not in csv_text
    assert "2025-11-01" in csv_text
    assert "2026-06-01" in csv_text


def test_write_outputs_windows_csv_to_trailing_12_months_when_floor_doesnt_bind(tmp_path):
    raw_rows = [CostRow("X", date(2026, 3, 1), 1.0, "f1.pdf")]
    monthly_rows = [
        CostRow("X", date(2026, 3, 1), 1.0, "f1.pdf"),
        CostRow("X", date(2026, 4, 1), 2.0, "f1.pdf"),
        CostRow("X", date(2027, 3, 1), 3.0, "f1.pdf"),
    ]
    db_path = tmp_path / "metrics.db"
    csv_path = tmp_path / "out.csv"

    write_outputs(raw_rows, monthly_rows, db_path, csv_path, csv_export_floor=date(2025, 11, 1))

    csv_text = csv_path.read_text()
    # anchor = 2027-03-01; window_start = 2026-04-01 (past the 2025-11 floor, so
    # the trailing-12-months window wins, not the floor)
    assert "2026-03-01" not in csv_text
    assert "2026-04-01" in csv_text
    assert "2027-03-01" in csv_text


def test_write_outputs_with_no_floor_uses_the_plain_trailing_window(tmp_path):
    raw_rows = [CostRow("X", date(2024, 1, 1), 1.0, "f1.pdf")]
    monthly_rows = [
        CostRow("X", date(2024, 1, 1), 1.0, "f1.pdf"),
        CostRow("X", date(2026, 6, 1), 4.0, "f1.pdf"),
    ]
    db_path = tmp_path / "metrics.db"
    csv_path = tmp_path / "out.csv"

    write_outputs(raw_rows, monthly_rows, db_path, csv_path)

    csv_text = csv_path.read_text()
    # anchor = 2026-06-01; window_start = 2025-07-01; no floor supplied, so
    # nothing clamps it -- 2024-01-01 falls outside the trailing 12 months.
    assert "2024-01-01" not in csv_text
    assert "2026-06-01" in csv_text


def test_write_outputs_sorts_csv_by_metric_date_ascending_across_vendors(tmp_path):
    raw_rows = [CostRow("Zeta", date(2026, 1, 1), 1.0, "f1.pdf")]
    monthly_rows = [
        CostRow("Alpha", date(2026, 2, 1), 20.0, "f1.pdf"),
        CostRow("Zeta", date(2026, 1, 1), 10.0, "f2.pdf"),
    ]
    db_path = tmp_path / "metrics.db"
    csv_path = tmp_path / "out.csv"

    write_outputs(raw_rows, monthly_rows, db_path, csv_path)

    lines = csv_path.read_text().strip().splitlines()
    assert lines[0] == "metric_name,metric_date,metric_value"
    assert lines[1] == "Zeta,2026-01-01,10.0"
    assert lines[2] == "Alpha,2026-02-01,20.0"


def test_count_new_rows_all_new_when_no_previous_files():
    rows = [
        CostRow("Snowflake", date(2026, 1, 1), 10.0, "a.pdf"),
        CostRow("Snowflake", date(2026, 2, 1), 20.0, "b.pdf"),
        CostRow("Dagster", date(2026, 1, 1), 5.0, "c.pdf"),
    ]
    assert count_new_rows(rows, {}) == {"Snowflake": 2, "Dagster": 1}


def test_count_new_rows_excludes_previously_seen_files():
    rows = [
        CostRow("Snowflake", date(2026, 1, 1), 10.0, "a.pdf"),
        CostRow("Snowflake", date(2026, 2, 1), 20.0, "b.pdf"),
    ]
    previous = {"Snowflake": {"a.pdf"}}
    assert count_new_rows(rows, previous) == {"Snowflake": 1}


def test_count_new_rows_reports_zero_for_vendor_with_no_new_files():
    rows = [CostRow("Dagster", date(2026, 1, 1), 5.0, "c.pdf")]
    previous = {"Dagster": {"c.pdf"}}
    assert count_new_rows(rows, previous) == {"Dagster": 0}


def test_read_previous_source_files_returns_empty_and_creates_no_file_when_db_missing(tmp_path):
    from metronome.costs.pipeline import _read_previous_source_files

    db_path = tmp_path / "does-not-exist.db"
    assert _read_previous_source_files(db_path) == {}
    assert not db_path.exists()


def test_run_logs_all_rows_as_new_on_first_run(tmp_path, caplog):
    (tmp_path / "downloads").mkdir()
    (tmp_path / "downloads" / "sf.pdf").write_bytes(b"")
    extractor = _fake_extractor({"sf.pdf": SNOWFLAKE_TEXT})
    db_path = tmp_path / "metrics.db"
    csv_path = tmp_path / "data-monthly.csv"

    with caplog.at_level(logging.INFO):
        run(tmp_path / "downloads", db_path, csv_path, extractor)

    message = next(m for m in caplog.messages if "new raw rows this run by vendor" in m)
    assert "'Snowflake': 1" in message


def test_run_logs_zero_new_rows_on_unchanged_second_run(tmp_path, caplog):
    (tmp_path / "downloads").mkdir()
    (tmp_path / "downloads" / "sf.pdf").write_bytes(b"")
    extractor = _fake_extractor({"sf.pdf": SNOWFLAKE_TEXT})
    db_path = tmp_path / "metrics.db"
    csv_path = tmp_path / "data-monthly.csv"

    run(tmp_path / "downloads", db_path, csv_path, extractor)
    caplog.clear()
    with caplog.at_level(logging.INFO):
        run(tmp_path / "downloads", db_path, csv_path, extractor)

    message = next(m for m in caplog.messages if "new raw rows this run by vendor" in m)
    assert "'Snowflake': 0" in message


def test_run_logs_only_the_newly_added_file_as_new(tmp_path, caplog):
    (tmp_path / "downloads").mkdir()
    (tmp_path / "downloads" / "sf.pdf").write_bytes(b"")
    db_path = tmp_path / "metrics.db"
    csv_path = tmp_path / "data-monthly.csv"
    run(tmp_path / "downloads", db_path, csv_path, _fake_extractor({"sf.pdf": SNOWFLAKE_TEXT}))

    (tmp_path / "downloads" / "dg.pdf").write_bytes(b"")
    extractor2 = _fake_extractor({"sf.pdf": SNOWFLAKE_TEXT, "dg.pdf": DAGSTER_TEXT})
    caplog.clear()
    with caplog.at_level(logging.INFO):
        run(tmp_path / "downloads", db_path, csv_path, extractor2)

    message = next(m for m in caplog.messages if "new raw rows this run by vendor" in m)
    assert "'Snowflake': 0" in message
    assert "'Dagster': 1" in message


def test_run_with_custom_vendor_list_only_matches_supplied_vendors(tmp_path):
    from metronome.costs.vendors import dagster

    (tmp_path / "downloads").mkdir()
    (tmp_path / "downloads" / "sf.pdf").write_bytes(b"")
    (tmp_path / "downloads" / "dg.pdf").write_bytes(b"")
    extractor = _fake_extractor({"sf.pdf": SNOWFLAKE_TEXT, "dg.pdf": DAGSTER_TEXT})
    db_path = tmp_path / "metrics.db"
    csv_path = tmp_path / "data-monthly.csv"

    run(tmp_path / "downloads", db_path, csv_path, extractor, vendor_modules=[dagster])

    con = duckdb.connect(str(db_path))
    raw_count = con.execute("SELECT COUNT(*) FROM raw_costs").fetchone()[0]
    con.close()
    assert raw_count == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/costs/test_pipeline.py -v`
Expected: FAIL / ERROR — `ModuleNotFoundError: No module named 'metronome.costs.pipeline'`

- [ ] **Step 3: Write the implementation**

Create `src/metronome/costs/pipeline.py`:

```python
from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Callable
from datetime import date
from pathlib import Path
from types import ModuleType

import duckdb

from metronome.costs import vendors
from metronome.costs.models import CostRow
from metronome.costs.pdf_text import extract_text
from metronome.costs.rollup import resolve_monthly
from metronome.metrics import store

logger = logging.getLogger(__name__)

TextExtractor = Callable[[Path], str]

_RAW_COLUMNS = [
    ("metric_name", "VARCHAR"),
    ("metric_date", "DATE"),
    ("metric_value", "DOUBLE"),
    ("source_file", "VARCHAR"),
]
_MONTHLY_COLUMNS = [("metric_name", "VARCHAR"), ("metric_date", "DATE"), ("metric_value", "DOUBLE")]


def parse_all(
    downloads_dir: Path,
    text_extractor: TextExtractor = extract_text,
    vendor_modules: list[ModuleType] | None = None,
) -> list[CostRow]:
    vendor_modules = vendor_modules if vendor_modules is not None else vendors.ALL
    rows: list[CostRow] = []
    for pdf_path in sorted(downloads_dir.glob("*.pdf")):
        try:
            text = text_extractor(pdf_path)
            matched = [module for module in vendor_modules if module.detect(text)]
            if not matched:
                logger.warning("no vendor matched %s; skipping", pdf_path.name)
                continue
            if len(matched) > 1:
                logger.warning(
                    "multiple vendors matched %s (%s); using %s",
                    pdf_path.name, [m.__name__ for m in matched], matched[0].__name__,
                )
            rows.extend(matched[0].parse(text, pdf_path.name))
        except Exception as exc:
            logger.error("failed to parse %s: %s", pdf_path.name, exc, exc_info=True)
            continue
    return rows


def _read_previous_source_files(db_path: Path) -> dict[str, set[str]]:
    if not db_path.exists():
        return {}
    previous: dict[str, set[str]] = defaultdict(set)
    con = duckdb.connect(str(db_path), read_only=True)
    try:
        rows = con.execute("SELECT DISTINCT metric_name, source_file FROM raw_costs").fetchall()
        for metric_name, source_file in rows:
            previous[metric_name].add(source_file)
    except duckdb.CatalogException:
        pass
    finally:
        con.close()
    return dict(previous)


def count_new_rows(raw_rows: list[CostRow], previous: dict[str, set[str]]) -> dict[str, int]:
    counts: dict[str, int] = {vendor: 0 for vendor in sorted({r.metric_name for r in raw_rows})}
    for row in raw_rows:
        if row.source_file not in previous.get(row.metric_name, set()):
            counts[row.metric_name] += 1
    return counts


def write_outputs(
    raw_rows: list[CostRow],
    monthly_rows: list[CostRow],
    db_path: Path,
    csv_path: Path,
    csv_export_months: int = 12,
    csv_export_floor: date | None = None,
) -> None:
    con = duckdb.connect(str(db_path))
    try:
        con.execute("BEGIN TRANSACTION")
        try:
            store.write_replace(
                con, "raw_costs", _RAW_COLUMNS,
                [(r.metric_name, r.metric_date, r.metric_value, r.source_file) for r in raw_rows],
            )
            store.write_replace(
                con, "monthly_costs", _MONTHLY_COLUMNS,
                [(r.metric_name, r.metric_date, r.metric_value) for r in monthly_rows],
            )

            if monthly_rows:
                anchor = max(r.metric_date for r in monthly_rows)
                csv_start = store.trailing_window_start(
                    anchor, csv_export_months, "months", floor=csv_export_floor
                )
            else:
                csv_start = csv_export_floor or date.min

            store.export_csv(
                con,
                "SELECT metric_name, metric_date, metric_value FROM monthly_costs "
                "WHERE metric_date >= ? ORDER BY metric_date, metric_name",
                [csv_start],
                csv_path,
            )
        except Exception:
            con.execute("ROLLBACK")
            raise
        else:
            con.execute("COMMIT")
    finally:
        con.close()


def run(
    downloads_dir: Path,
    db_path: Path,
    csv_path: Path,
    text_extractor: TextExtractor = extract_text,
    vendor_modules: list[ModuleType] | None = None,
    sum_on_collision: frozenset[str] = frozenset(),
    csv_export_months: int = 12,
    csv_export_floor: date | None = None,
) -> None:
    raw_rows = parse_all(downloads_dir, text_extractor, vendor_modules)
    monthly_rows = resolve_monthly(raw_rows, sum_on_collision)
    previous_source_files = _read_previous_source_files(db_path)
    new_row_counts = count_new_rows(raw_rows, previous_source_files)
    write_outputs(raw_rows, monthly_rows, db_path, csv_path, csv_export_months, csv_export_floor)
    logger.info(
        "wrote %d raw rows and %d monthly rows to %s and %s",
        len(raw_rows), len(monthly_rows), db_path, csv_path,
    )
    logger.info("new raw rows this run by vendor: %s", new_row_counts)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/costs/test_pipeline.py -v`
Expected: PASS (all tests pass)

- [ ] **Step 5: Commit**

```bash
git add src/metronome/costs/pipeline.py tests/costs/test_pipeline.py
git commit -m "Add metronome.costs.pipeline, rebuilt on metronome.metrics.store"
```

---

### Task 8: `snowflake_conn.py`

**Files:**
- Create: `src/metronome/snowflake_conn.py`
- Test: `tests/test_snowflake_conn.py`

**Interfaces:**
- Produces: `SnowflakeConfig` frozen dataclass (`account`, `user`, `private_key_pem`, `role`, `database`, `warehouse`, all `str`), `connect(config: SnowflakeConfig) -> ContextManager[SnowflakeConnection]`, `execute_query(conn, sql: str) -> list[tuple]`. Consumed by `metrics/pipeline.py` is NOT a consumer (it takes an already-built `QueryExecutor`) — this module is consumed directly by `data-pipelines2`'s `product_analytics/cli.py` (Task 13).

- [ ] **Step 1: Write the failing test**

Create `tests/test_snowflake_conn.py`:

```python
from unittest.mock import MagicMock, patch

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from metronome.snowflake_conn import SnowflakeConfig, _load_private_key_der, connect, execute_query


def _generate_test_pem() -> str:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem_bytes = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    return pem_bytes.decode()


def test_load_private_key_der_round_trips_a_pem_key():
    pem_text = _generate_test_pem()

    der_bytes = _load_private_key_der(pem_text)

    assert isinstance(der_bytes, bytes)
    reloaded = serialization.load_der_private_key(der_bytes, password=None)
    original = serialization.load_pem_private_key(pem_text.encode(), password=None)
    assert reloaded.private_numbers() == original.private_numbers()


def test_connect_passes_config_and_der_key_to_snowflake_connector():
    pem_text = _generate_test_pem()
    config = SnowflakeConfig(
        account="acct1", user="user1", private_key_pem=pem_text,
        role="role1", database="db1", warehouse="wh1",
    )

    fake_conn = MagicMock()
    with patch("snowflake.connector.connect", return_value=fake_conn) as mock_connect:
        with connect(config) as conn:
            assert conn is fake_conn

    _, kwargs = mock_connect.call_args
    assert kwargs["account"] == "acct1"
    assert kwargs["user"] == "user1"
    assert kwargs["role"] == "role1"
    assert kwargs["database"] == "db1"
    assert kwargs["warehouse"] == "wh1"
    assert isinstance(kwargs["private_key"], bytes)
    fake_conn.close.assert_called_once()


def test_execute_query_returns_fetchall_result_and_closes_cursor():
    fake_cursor = MagicMock()
    fake_cursor.fetchall.return_value = [("Stage A", "2026-07-01", 3)]
    fake_cursor.nextset.return_value = None
    fake_conn = MagicMock()
    fake_conn.cursor.return_value = fake_cursor

    rows = execute_query(fake_conn, "select 1")

    assert rows == [("Stage A", "2026-07-01", 3)]
    fake_cursor.execute.assert_called_once_with("select 1", num_statements=0)
    fake_cursor.close.assert_called_once()


def test_execute_query_drains_multi_statement_scripts_and_returns_the_last_result():
    fake_cursor = MagicMock()
    fake_cursor.fetchall.side_effect = [
        [("Statement executed successfully.",)],
        [("Stage A", "2026-07-01", 3)],
    ]
    fake_cursor.nextset.side_effect = [True, None]
    fake_conn = MagicMock()
    fake_conn.cursor.return_value = fake_cursor

    rows = execute_query(fake_conn, "SET period = 'week'; select 1")

    assert rows == [("Stage A", "2026-07-01", 3)]
    fake_cursor.execute.assert_called_once_with("SET period = 'week'; select 1", num_statements=0)
    fake_cursor.close.assert_called_once()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_snowflake_conn.py -v`
Expected: FAIL / ERROR — `ModuleNotFoundError: No module named 'metronome.snowflake_conn'`

- [ ] **Step 3: Write the implementation**

Create `src/metronome/snowflake_conn.py`:

```python
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

import snowflake.connector
from cryptography.hazmat.primitives import serialization


@dataclass(frozen=True)
class SnowflakeConfig:
    account: str
    user: str
    private_key_pem: str
    role: str
    database: str
    warehouse: str


def _load_private_key_der(pem_text: str) -> bytes:
    private_key = serialization.load_pem_private_key(pem_text.encode(), password=None)
    return private_key.private_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )


@contextmanager
def connect(config: SnowflakeConfig) -> Iterator[snowflake.connector.SnowflakeConnection]:
    conn = snowflake.connector.connect(
        account=config.account,
        user=config.user,
        private_key=_load_private_key_der(config.private_key_pem),
        role=config.role,
        database=config.database,
        warehouse=config.warehouse,
    )
    try:
        yield conn
    finally:
        conn.close()


def execute_query(conn: snowflake.connector.SnowflakeConnection, sql: str) -> list[tuple]:
    cursor = conn.cursor()
    try:
        cursor.execute(sql, num_statements=0)
        rows = cursor.fetchall()
        while cursor.nextset() is not None:
            rows = cursor.fetchall()
        return rows
    finally:
        cursor.close()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_snowflake_conn.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add src/metronome/snowflake_conn.py tests/test_snowflake_conn.py
git commit -m "Add metronome.snowflake_conn with an explicit SnowflakeConfig"
```

---

### Task 9: `metrics/sql_runner.py`

**Files:**
- Create: `src/metronome/metrics/sql_runner.py`
- Test: `tests/metrics/test_sql_runner.py`

**Interfaces:**
- Consumes: `MetricRow` from `metronome.metrics.models` (Task 6).
- Produces: `QueryExecutor = Callable[[str], list[tuple]]`, `run_all(period: str, execute_query: QueryExecutor, sources_dir: Path) -> list[MetricRow]`. Consumed by `metrics/pipeline.py` (Task 10).

- [ ] **Step 1: Write the failing test**

Create `tests/metrics/test_sql_runner.py`:

```python
import logging
from datetime import date

from metronome.metrics.sql_runner import run_all


def test_run_all_discovers_and_executes_every_sql_file_in_sources_dir(tmp_path):
    (tmp_path / "alpha.sql").write_text("select 'Alpha', date '2026-07-27', 1")
    (tmp_path / "beta.sql").write_text("select 'Beta', date '2026-07-27', 2")

    def _execute(sql: str) -> list[tuple]:
        if "Alpha" in sql:
            return [("Alpha", date(2026, 7, 27), 1)]
        if "Beta" in sql:
            return [("Beta", date(2026, 7, 27), 2)]
        return []  # the SET statement

    rows = run_all("weekly", _execute, sources_dir=tmp_path)

    names = {r.metric_name for r in rows}
    assert names == {"Alpha", "Beta"}
    assert len(rows) == 2


def test_run_all_sets_period_session_variable_before_running_sources(tmp_path):
    (tmp_path / "metric.sql").write_text("select 'X', date '2026-07-27', 1")

    def _make_executor():
        calls: list[str] = []

        def _execute(sql: str) -> list[tuple]:
            calls.append(sql)
            return []

        _execute.calls = calls
        return _execute

    weekly_executor = _make_executor()
    run_all("weekly", weekly_executor, sources_dir=tmp_path)
    assert weekly_executor.calls[0] == "SET period = 'week';"

    monthly_executor = _make_executor()
    run_all("monthly", monthly_executor, sources_dir=tmp_path)
    assert monthly_executor.calls[0] == "SET period = 'month';"


def test_run_all_skips_failing_source_but_returns_the_rest(tmp_path, caplog):
    (tmp_path / "broken.sql").write_text("select 1/0")
    (tmp_path / "ok.sql").write_text("select 'OK', date '2026-07-27', 2")

    def _execute(sql: str) -> list[tuple]:
        if "1/0" in sql:
            raise RuntimeError("boom")
        if "OK" in sql:
            return [("OK", date(2026, 7, 27), 2)]
        return []  # the SET statement

    with caplog.at_level(logging.ERROR):
        rows = run_all("weekly", _execute, sources_dir=tmp_path)

    assert len(rows) == 1
    assert rows[0].metric_name == "OK"
    assert any("broken" in message for message in caplog.messages)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/metrics/test_sql_runner.py -v`
Expected: FAIL / ERROR — `ModuleNotFoundError: No module named 'metronome.metrics.sql_runner'`

- [ ] **Step 3: Write the implementation**

Create `src/metronome/metrics/sql_runner.py`:

```python
from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

from metronome.metrics.models import MetricRow

logger = logging.getLogger(__name__)

QueryExecutor = Callable[[str], list[tuple]]

_PERIOD_VARS = {"weekly": "week", "monthly": "month"}


def _rows_to_metrics(rows: list[tuple]) -> list[MetricRow]:
    return [
        MetricRow(metric_name=name, metric_date=metric_date, metric_value=float(value))
        for name, metric_date, value in rows
    ]


def run_all(period: str, execute_query: QueryExecutor, sources_dir: Path) -> list[MetricRow]:
    execute_query(f"SET period = '{_PERIOD_VARS[period]}';")

    rows: list[MetricRow] = []
    for sql_file in sorted(sources_dir.glob("*.sql")):
        try:
            rows.extend(_rows_to_metrics(execute_query(sql_file.read_text())))
        except Exception as exc:
            logger.error(
                "failed to run %s for period=%s: %s", sql_file.stem, period, exc, exc_info=True
            )
            continue
    return rows
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/metrics/test_sql_runner.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add src/metronome/metrics/sql_runner.py tests/metrics/test_sql_runner.py
git commit -m "Add metronome.metrics.sql_runner"
```

---

### Task 10: `metrics/pipeline.py`

**Files:**
- Create: `src/metronome/metrics/pipeline.py`
- Test: `tests/metrics/test_pipeline.py`

**Interfaces:**
- Consumes: `MetricRow` (Task 6), `write_upsert`/`export_csv`/`trailing_window_start` from `metronome.metrics.store` (Task 6), `QueryExecutor`/`run_all` from `metronome.metrics.sql_runner` (Task 9).
- Produces: `write_outputs(rows, period, db_path, csv_path, csv_export_weeks=12, csv_export_months=12) -> None`, `run(period, execute_query, db_path, csv_path, sources_dir, csv_export_weeks=12, csv_export_months=12) -> None`. Consumed by `data-pipelines2`'s `product_analytics/cli.py` (Task 13).

- [ ] **Step 1: Write the failing test**

Create `tests/metrics/test_pipeline.py`:

```python
from datetime import date, timedelta

import duckdb

from metronome.metrics.models import MetricRow
from metronome.metrics.pipeline import run, write_outputs


def test_write_outputs_creates_table_and_inserts_rows(tmp_path):
    rows = [
        MetricRow("Intake [PACO]", date(2026, 7, 27), 3.0),
        MetricRow("Furnace Jobs", date(2026, 7, 27), 2.0),
    ]
    db_path = tmp_path / "metrics.db"
    csv_path = tmp_path / "out.csv"

    write_outputs(rows, "weekly", db_path, csv_path)

    con = duckdb.connect(str(db_path))
    result = con.execute(
        "SELECT metric_name, metric_date, metric_value FROM product_weekly ORDER BY metric_name"
    ).fetchall()
    con.close()

    assert result == [
        ("Furnace Jobs", date(2026, 7, 27), 2.0),
        ("Intake [PACO]", date(2026, 7, 27), 3.0),
    ]


def test_write_outputs_replaces_existing_rows_for_the_same_period_on_rerun(tmp_path):
    db_path = tmp_path / "metrics.db"
    csv_path = tmp_path / "out.csv"

    write_outputs([MetricRow("Intake [PACO]", date(2026, 7, 27), 3.0)], "weekly", db_path, csv_path)
    write_outputs([MetricRow("Intake [PACO]", date(2026, 7, 27), 9.0)], "weekly", db_path, csv_path)

    con = duckdb.connect(str(db_path))
    result = con.execute("SELECT metric_name, metric_date, metric_value FROM product_weekly").fetchall()
    con.close()

    assert result == [("Intake [PACO]", date(2026, 7, 27), 9.0)]


def test_write_outputs_does_not_touch_other_periods_rows(tmp_path):
    db_path = tmp_path / "metrics.db"
    csv_path = tmp_path / "out.csv"

    write_outputs([MetricRow("Intake [PACO]", date(2026, 7, 20), 1.0)], "weekly", db_path, csv_path)
    write_outputs([MetricRow("Intake [PACO]", date(2026, 7, 27), 2.0)], "weekly", db_path, csv_path)

    con = duckdb.connect(str(db_path))
    count = con.execute("SELECT COUNT(*) FROM product_weekly").fetchone()[0]
    con.close()

    assert count == 2


def test_write_outputs_monthly_and_weekly_use_separate_tables(tmp_path):
    db_path = tmp_path / "metrics.db"
    csv_path = tmp_path / "out.csv"

    write_outputs([MetricRow("Intake [PACO]", date(2026, 7, 27), 1.0)], "weekly", db_path, csv_path)
    write_outputs([MetricRow("Intake [PACO]", date(2026, 7, 1), 2.0)], "monthly", db_path, csv_path)

    con = duckdb.connect(str(db_path))
    weekly_count = con.execute("SELECT COUNT(*) FROM product_weekly").fetchone()[0]
    monthly_count = con.execute("SELECT COUNT(*) FROM product_monthly").fetchone()[0]
    con.close()

    assert weekly_count == 1
    assert monthly_count == 1


def test_write_outputs_windows_csv_to_trailing_12_months(tmp_path):
    rows = [
        MetricRow("X", date(2026, 3, 1), 1.0),
        MetricRow("X", date(2026, 4, 1), 2.0),
        MetricRow("X", date(2027, 3, 1), 3.0),
    ]
    db_path = tmp_path / "metrics.db"
    csv_path = tmp_path / "out.csv"

    write_outputs(rows, "monthly", db_path, csv_path)

    csv_text = csv_path.read_text()
    assert "2026-03-01" not in csv_text
    assert "2026-04-01" in csv_text
    assert "2027-03-01" in csv_text


def test_write_outputs_windows_csv_to_trailing_12_weeks(tmp_path):
    anchor = date(2026, 7, 27)
    just_inside = anchor - timedelta(weeks=11)
    just_outside = anchor - timedelta(weeks=12)

    rows = [
        MetricRow("X", just_outside, 1.0),
        MetricRow("X", just_inside, 2.0),
        MetricRow("X", anchor, 3.0),
    ]
    db_path = tmp_path / "metrics.db"
    csv_path = tmp_path / "out.csv"

    write_outputs(rows, "weekly", db_path, csv_path)

    csv_text = csv_path.read_text()
    assert just_outside.isoformat() not in csv_text
    assert just_inside.isoformat() in csv_text
    assert anchor.isoformat() in csv_text


def test_write_outputs_sorts_csv_by_metric_date_then_metric_name(tmp_path):
    rows = [
        MetricRow("Zeta", date(2026, 7, 20), 1.0),
        MetricRow("Alpha", date(2026, 7, 27), 2.0),
    ]
    db_path = tmp_path / "metrics.db"
    csv_path = tmp_path / "out.csv"

    write_outputs(rows, "weekly", db_path, csv_path)

    lines = csv_path.read_text().strip().splitlines()
    assert lines[0] == "metric_name,metric_date,metric_value"
    assert lines[1] == "Zeta,2026-07-20,1.0"
    assert lines[2] == "Alpha,2026-07-27,2.0"


def test_write_outputs_with_no_rows_writes_header_only_csv(tmp_path):
    db_path = tmp_path / "metrics.db"
    csv_path = tmp_path / "out.csv"

    write_outputs([], "weekly", db_path, csv_path)

    csv_text = csv_path.read_text().strip()
    assert csv_text == "metric_name,metric_date,metric_value"


def test_run_end_to_end_writes_db_and_csv(tmp_path):
    sources_dir = tmp_path / "sources"
    sources_dir.mkdir()
    (sources_dir / "paco.sql").write_text("select 'Intake [PACO]', date '2026-07-27', 3")
    (sources_dir / "xcel_addl.sql").write_text("select 'Furnace Jobs', date '2026-07-27', 2")

    def _execute(sql: str) -> list[tuple]:
        if "Intake" in sql:
            return [("Intake [PACO]", date(2026, 7, 27), 3)]
        if "Furnace" in sql:
            return [("Furnace Jobs", date(2026, 7, 27), 2)]
        return []  # the SET statement

    db_path = tmp_path / "metrics.db"
    csv_path = tmp_path / "out.csv"

    run("weekly", _execute, db_path, csv_path, sources_dir=sources_dir)

    con = duckdb.connect(str(db_path))
    count = con.execute("SELECT COUNT(*) FROM product_weekly").fetchone()[0]
    con.close()
    assert count == 2

    csv_text = csv_path.read_text()
    assert "Intake [PACO]" in csv_text
    assert "Furnace Jobs" in csv_text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/metrics/test_pipeline.py -v`
Expected: FAIL / ERROR — `ModuleNotFoundError: No module named 'metronome.metrics.pipeline'`

- [ ] **Step 3: Write the implementation**

Create `src/metronome/metrics/pipeline.py`:

```python
from __future__ import annotations

import logging
from pathlib import Path

import duckdb

from metronome.metrics import store
from metronome.metrics.models import MetricRow
from metronome.metrics.sql_runner import QueryExecutor, run_all

logger = logging.getLogger(__name__)

_TABLES = {"weekly": "product_weekly", "monthly": "product_monthly"}
_WINDOW_UNITS = {"weekly": "weeks", "monthly": "months"}
_COLUMNS = [("metric_name", "VARCHAR"), ("metric_date", "DATE"), ("metric_value", "DOUBLE")]


def write_outputs(
    rows: list[MetricRow],
    period: str,
    db_path: Path,
    csv_path: Path,
    csv_export_weeks: int = 12,
    csv_export_months: int = 12,
) -> None:
    table = _TABLES[period]
    con = duckdb.connect(str(db_path))
    try:
        con.execute("BEGIN TRANSACTION")
        try:
            store.write_upsert(
                con, table, _COLUMNS,
                key_columns=["metric_name", "metric_date"],
                rows=[(r.metric_name, r.metric_date, r.metric_value) for r in rows],
            )

            anchor = con.execute(f"SELECT MAX(metric_date) FROM {table}").fetchone()[0]
            select = (
                f"SELECT metric_name, metric_date, metric_value FROM {table} "
                f"WHERE metric_date >= ? ORDER BY metric_date, metric_name"
            )
            if anchor is not None:
                window_count = csv_export_months if period == "monthly" else csv_export_weeks
                csv_start = store.trailing_window_start(anchor, window_count, _WINDOW_UNITS[period])
                store.export_csv(con, select, [csv_start], csv_path)
            else:
                store.export_csv(
                    con,
                    f"SELECT metric_name, metric_date, metric_value FROM {table} "
                    f"ORDER BY metric_date, metric_name",
                    [],
                    csv_path,
                )
        except Exception:
            con.execute("ROLLBACK")
            raise
        else:
            con.execute("COMMIT")
    finally:
        con.close()


def run(
    period: str,
    execute_query: QueryExecutor,
    db_path: Path,
    csv_path: Path,
    sources_dir: Path,
    csv_export_weeks: int = 12,
    csv_export_months: int = 12,
) -> None:
    rows = run_all(period, execute_query, sources_dir)
    write_outputs(rows, period, db_path, csv_path, csv_export_weeks, csv_export_months)
    logger.info("wrote %d rows to %s table for period=%s", len(rows), _TABLES[period], period)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/metrics/test_pipeline.py -v`
Expected: PASS (all tests pass)

- [ ] **Step 5: Run the full metronome test suite**

Run: `pytest -v`
Expected: PASS — every test from Tasks 2–10 passes together (checks for cross-task import issues).

- [ ] **Step 6: Commit**

```bash
git add src/metronome/metrics/pipeline.py tests/metrics/test_pipeline.py
git commit -m "Add metronome.metrics.pipeline, rebuilt on metronome.metrics.store"
```

---

### Task 11: Wire `metronome` into `data-pipelines2`'s `sealed` environment

**Files:**
- Modify: `~/ghq/github.com/sealedinc/data-pipelines2/pyproject.toml`

**Interfaces:**
- Produces: `import metronome` resolves inside the `sealed` pyenv env, pointing at `~/ghq/github.com/quadrant-yards/metronome/src/metronome`. Required before Tasks 12–13 can run or test against real imports.

This repo is `sealedinc`-owned, outside the `quadrant-yards` org this workspace is normally scoped to — the user has explicitly authorized both reading from and modifying it as part of this extraction (see conversation history). `uv` is not installed on this machine even though `data-pipelines2` ships a `uv.lock`, so this step uses the `sealed` pyenv env's `pip` directly, matching the same "activate the venv, `pip install -e`" mechanism metronome's own setup brief uses for `pyme`.

- [ ] **Step 1: Editable-install metronome into the `sealed` env**

```bash
~/.pyenv/versions/3.13/envs/sealed/bin/pip install -e ~/ghq/github.com/quadrant-yards/metronome
```

- [ ] **Step 2: Verify the import resolves**

```bash
~/.pyenv/versions/3.13/envs/sealed/bin/python -c "import metronome; print(metronome.__file__)"
```

Expected: prints a path ending in `.../quadrant-yards/metronome/src/metronome/__init__.py`.

- [ ] **Step 3: Record the dependency in `data-pipelines2`'s `pyproject.toml` for future `uv sync` runs**

Open `~/ghq/github.com/sealedinc/data-pipelines2/pyproject.toml` and add `"metronome"` to the `dependencies` list, plus a `[tool.uv.sources]` table pointing at the local editable path:

```toml
dependencies = [
    "dagster>=1.11.15",
    "dagster-webserver>=1.11.15",
    "dbt-core>=1.10.13,<2",
    "dbt-snowflake>=1.10.2",
    "pytest-playwright>=0.7.1",
    "tqdm>=4.67.1",
    "metronome",
]

[tool.pytest.ini_options]
pythonpath = ["."]

[tool.uv.sources]
metronome = { path = "/Users/sam/ghq/github.com/quadrant-yards/metronome", editable = true }
```

This makes the dependency explicit and keeps a future `uv sync` (once `uv` is available in this shell) consistent with the `pip install -e` done in Step 1 — `uv.lock` itself is not regenerated here since `uv` isn't runnable in this environment; flag this to the user so they can run `uv lock` themselves when convenient.

- [ ] **Step 4: Commit the `data-pipelines2` pyproject.toml change**

```bash
cd ~/ghq/github.com/sealedinc/data-pipelines2
git add pyproject.toml
git commit -m "Add metronome as a local editable dependency"
```

---

### Task 12: Migrate `data-pipelines2`'s `eng_costs` to consume `metronome.costs`

**Files (all in `~/ghq/github.com/sealedinc/data-pipelines2`):**
- Modify: `scripts/metrics/eng_costs/cli.py`
- Delete: `scripts/metrics/eng_costs/models.py`
- Delete: `scripts/metrics/eng_costs/pdf_text.py`
- Delete: `scripts/metrics/eng_costs/rollup.py`
- Delete: `scripts/metrics/eng_costs/pipeline.py`
- Delete: `scripts/metrics/eng_costs/dateparse.py`
- Delete: `scripts/metrics/eng_costs/vendors/` (whole directory)
- Delete: `tests/metrics/eng_costs/test_dateparse.py`
- Delete: `tests/metrics/eng_costs/test_rollup.py`
- Delete: `tests/metrics/eng_costs/test_pipeline.py`
- Delete: `tests/metrics/eng_costs/test_dagster.py`
- Delete: `tests/metrics/eng_costs/test_gcp.py`
- Delete: `tests/metrics/eng_costs/test_github.py`
- Delete: `tests/metrics/eng_costs/test_hex.py`
- Delete: `tests/metrics/eng_costs/test_snowflake.py`
- Modify: `tests/metrics/eng_costs/test_cli.py`

**Interfaces:**
- Consumes: `metronome.costs.pipeline.run(...)` (Task 7), with `sum_on_collision=frozenset({"GitHub"})` and `csv_export_floor=date(2025, 11, 1)` supplied to preserve current behavior.

- [ ] **Step 1: Rewrite `cli.py`**

Replace `scripts/metrics/eng_costs/cli.py` with:

```python
from __future__ import annotations

import argparse
import logging
from datetime import date
from pathlib import Path

from metronome.costs.pipeline import run

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_DOWNLOADS_DIR = _REPO_ROOT / "data.local" / "Downloads.Sealed"
_DEFAULT_DB_PATH = _REPO_ROOT / "data.local" / "metrics.db"
_DEFAULT_CSV_PATH = _REPO_ROOT / "data.local" / "eng-costs-monthly.csv"

_SUM_ON_COLLISION = frozenset({"GitHub"})
_CSV_EXPORT_FLOOR = date(2025, 11, 1)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Parse vendor cost PDFs into metrics.db and eng-costs-monthly.csv"
    )
    parser.add_argument("--downloads-dir", type=Path, default=_DEFAULT_DOWNLOADS_DIR)
    parser.add_argument("--db-path", type=Path, default=_DEFAULT_DB_PATH)
    parser.add_argument("--csv-path", type=Path, default=_DEFAULT_CSV_PATH)
    return parser


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    args = build_parser().parse_args()
    run(
        args.downloads_dir,
        args.db_path,
        args.csv_path,
        sum_on_collision=_SUM_ON_COLLISION,
        csv_export_floor=_CSV_EXPORT_FLOOR,
    )


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Delete the files that moved to metronome**

```bash
cd ~/ghq/github.com/sealedinc/data-pipelines2
git rm scripts/metrics/eng_costs/models.py
git rm scripts/metrics/eng_costs/pdf_text.py
git rm scripts/metrics/eng_costs/rollup.py
git rm scripts/metrics/eng_costs/pipeline.py
git rm scripts/metrics/eng_costs/dateparse.py
git rm -r scripts/metrics/eng_costs/vendors
git rm tests/metrics/eng_costs/test_dateparse.py
git rm tests/metrics/eng_costs/test_rollup.py
git rm tests/metrics/eng_costs/test_pipeline.py
git rm tests/metrics/eng_costs/test_dagster.py
git rm tests/metrics/eng_costs/test_gcp.py
git rm tests/metrics/eng_costs/test_github.py
git rm tests/metrics/eng_costs/test_hex.py
git rm tests/metrics/eng_costs/test_snowflake.py
```

- [ ] **Step 3: Add a wiring regression test to `test_cli.py`**

Append to `tests/metrics/eng_costs/test_cli.py` (the existing `build_parser` tests stay unchanged — `build_parser()`'s signature didn't change):

```python
def test_main_wires_sum_on_collision_and_csv_export_floor(monkeypatch):
    from datetime import date

    from scripts.metrics.eng_costs import cli

    captured = {}

    def fake_run(downloads_dir, db_path, csv_path, **kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(cli, "run", fake_run)
    monkeypatch.setattr("sys.argv", ["prog"])

    cli.main()

    assert captured["sum_on_collision"] == frozenset({"GitHub"})
    assert captured["csv_export_floor"] == date(2025, 11, 1)
```

- [ ] **Step 4: Run the eng_costs test suite**

```bash
cd ~/ghq/github.com/sealedinc/data-pipelines2
~/.pyenv/versions/3.13/envs/sealed/bin/pytest tests/metrics/eng_costs/ -v
```

Expected: PASS — only `test_cli.py` remains in this directory (now with the new wiring test) and all its tests pass, proving `cli.py` correctly imports and calls into `metronome.costs.pipeline.run`.

- [ ] **Step 5: Commit**

```bash
git add scripts/metrics/eng_costs/cli.py tests/metrics/eng_costs/test_cli.py
git commit -m "Migrate eng_costs to consume metronome.costs.pipeline"
```

---

### Task 13: Migrate `data-pipelines2`'s `product_analytics` to consume `metronome.metrics`

**Files (all in `~/ghq/github.com/sealedinc/data-pipelines2`):**
- Modify: `scripts/metrics/product_analytics/cli.py`
- Delete: `scripts/metrics/product_analytics/models.py`
- Delete: `scripts/metrics/product_analytics/snowflake_conn.py`
- Delete: `scripts/metrics/product_analytics/pipeline.py`
- Delete: `tests/metrics/product_analytics/test_pipeline.py`
- Delete: `tests/metrics/product_analytics/test_snowflake_conn.py`
- Modify: `tests/metrics/product_analytics/test_cli.py`

**Interfaces:**
- Consumes: `metronome.snowflake_conn.SnowflakeConfig`/`connect`/`execute_query` (Task 8), `metronome.metrics.pipeline.run(...)` (Task 10), passing this repo's own `sources/` directory.

- [ ] **Step 1: Rewrite `cli.py`**

Replace `scripts/metrics/product_analytics/cli.py` with:

```python
from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path

from metronome import snowflake_conn
from metronome.metrics.pipeline import run

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_DB_PATH = _REPO_ROOT / "data.local" / "metrics.db"
_DEFAULT_WEEKLY_CSV_PATH = _REPO_ROOT / "data.local" / "product-analytics-weekly.csv"
_DEFAULT_MONTHLY_CSV_PATH = _REPO_ROOT / "data.local" / "product-analytics-monthly.csv"
_SOURCES_DIR = Path(__file__).parent / "sources"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run product-analytics Snowflake sources into metrics.db + CSV"
    )
    parser.add_argument("--period", required=True, choices=["weekly", "monthly"])
    parser.add_argument("--db-path", type=Path, default=_DEFAULT_DB_PATH)
    parser.add_argument("--csv-path", type=Path, default=None)
    return parser


def _config_from_env() -> snowflake_conn.SnowflakeConfig:
    return snowflake_conn.SnowflakeConfig(
        account=os.environ["SNOWFLAKE_ACCOUNT"],
        user=os.environ["TRANSFORM_SNOWFLAKE_USER"],
        private_key_pem=os.environ["TRANSFORM_SNOWFLAKE_PRIVATE_KEY"],
        role=os.environ["TRANSFORM_SNOWFLAKE_ROLE"],
        database=os.environ["TRANSFORM_SNOWFLAKE_DATABASE"],
        warehouse=os.environ["TRANSFORM_SNOWFLAKE_WAREHOUSE"],
    )


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    args = build_parser().parse_args()
    csv_path = args.csv_path or (
        _DEFAULT_WEEKLY_CSV_PATH if args.period == "weekly" else _DEFAULT_MONTHLY_CSV_PATH
    )

    with snowflake_conn.connect(_config_from_env()) as conn:
        def execute_query(sql: str) -> list[tuple]:
            return snowflake_conn.execute_query(conn, sql)

        run(args.period, execute_query, args.db_path, csv_path, sources_dir=_SOURCES_DIR)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Delete the files that moved to metronome**

```bash
cd ~/ghq/github.com/sealedinc/data-pipelines2
git rm scripts/metrics/product_analytics/models.py
git rm scripts/metrics/product_analytics/snowflake_conn.py
git rm scripts/metrics/product_analytics/pipeline.py
git rm tests/metrics/product_analytics/test_pipeline.py
git rm tests/metrics/product_analytics/test_snowflake_conn.py
```

- [ ] **Step 3: Add an env-var-mapping regression test to `test_cli.py`**

Replace `tests/metrics/product_analytics/test_cli.py` with:

```python
from pathlib import Path

import pytest

from scripts.metrics.product_analytics.cli import _config_from_env, build_parser

_REPO_ROOT = Path(__file__).resolve().parents[3]


def test_default_db_path_is_anchored_at_repo_root():
    assert (_REPO_ROOT / "pyproject.toml").exists()
    args = build_parser().parse_args(["--period", "weekly"])
    assert args.db_path.parent == _REPO_ROOT / "data.local"


def test_default_db_path_points_inside_data_local():
    args = build_parser().parse_args(["--period", "weekly"])
    assert args.db_path.name == "metrics.db"
    assert args.db_path.parent.name == "data.local"
    assert args.csv_path is None


def test_period_is_required():
    with pytest.raises(SystemExit):
        build_parser().parse_args([])


def test_period_must_be_weekly_or_monthly():
    with pytest.raises(SystemExit):
        build_parser().parse_args(["--period", "yearly"])


def test_paths_can_be_overridden():
    args = build_parser().parse_args(
        ["--period", "monthly", "--db-path", "/tmp/y.db", "--csv-path", "/tmp/z.csv"]
    )
    assert str(args.db_path) == "/tmp/y.db"
    assert str(args.csv_path) == "/tmp/z.csv"


def test_config_from_env_reads_expected_env_vars(monkeypatch):
    monkeypatch.setenv("SNOWFLAKE_ACCOUNT", "acct1")
    monkeypatch.setenv("TRANSFORM_SNOWFLAKE_USER", "user1")
    monkeypatch.setenv("TRANSFORM_SNOWFLAKE_PRIVATE_KEY", "pem-text")
    monkeypatch.setenv("TRANSFORM_SNOWFLAKE_ROLE", "role1")
    monkeypatch.setenv("TRANSFORM_SNOWFLAKE_DATABASE", "db1")
    monkeypatch.setenv("TRANSFORM_SNOWFLAKE_WAREHOUSE", "wh1")

    config = _config_from_env()

    assert config.account == "acct1"
    assert config.user == "user1"
    assert config.private_key_pem == "pem-text"
    assert config.role == "role1"
    assert config.database == "db1"
    assert config.warehouse == "wh1"
```

- [ ] **Step 4: Run the product_analytics test suite**

```bash
cd ~/ghq/github.com/sealedinc/data-pipelines2
~/.pyenv/versions/3.13/envs/sealed/bin/pytest tests/metrics/product_analytics/ -v
```

Expected: PASS — `test_cli.py` (6 tests, including the new env-var one) and `test_source_files.py` (unchanged, still covers the SQL files directly) all pass.

- [ ] **Step 5: Commit**

```bash
git add scripts/metrics/product_analytics/cli.py tests/metrics/product_analytics/test_cli.py
git commit -m "Migrate product_analytics to consume metronome.snowflake_conn and metronome.metrics.pipeline"
```

---

### Task 14: Final verification

**Files:** none (verification only)

**Interfaces:** none — this task only runs existing test suites and CLI entry points to confirm the whole extraction holds together end to end.

- [ ] **Step 1: Run the full metronome test suite**

```bash
cd ~/ghq/github.com/quadrant-yards/metronome
pytest -v
```

Expected: PASS, 0 failures.

- [ ] **Step 2: Run the full data-pipelines2 test suite for the metrics scripts**

```bash
cd ~/ghq/github.com/sealedinc/data-pipelines2
~/.pyenv/versions/3.13/envs/sealed/bin/pytest tests/metrics/ -v
```

Expected: PASS, 0 failures. This should now be a much smaller suite (`test_cli.py` for both `eng_costs` and `product_analytics`, plus `test_source_files.py`) than before the migration.

- [ ] **Step 3: Smoke-test both CLIs resolve their imports**

```bash
cd ~/ghq/github.com/sealedinc/data-pipelines2
~/.pyenv/versions/3.13/envs/sealed/bin/python -m scripts.metrics.eng_costs.cli --help
~/.pyenv/versions/3.13/envs/sealed/bin/python -m scripts.metrics.product_analytics.cli --help
```

Expected: both print their argparse `--help` text with no `ImportError`/`ModuleNotFoundError` — this is the check that catches an import-path typo that unit tests (which run inside `pytest`'s already-configured `pythonpath`) might not.

- [ ] **Step 4: Confirm no stray generic code was left behind in data-pipelines2**

```bash
cd ~/ghq/github.com/sealedinc/data-pipelines2
find scripts/metrics -type f
```

Expected output — only:
```
scripts/metrics/__init__.py
scripts/metrics/requirements.txt
scripts/metrics/eng_costs/__init__.py
scripts/metrics/eng_costs/cli.py
scripts/metrics/product_analytics/__init__.py
scripts/metrics/product_analytics/cli.py
scripts/metrics/product_analytics/sources/__init__.py
scripts/metrics/product_analytics/sources/paco.sql
scripts/metrics/product_analytics/sources/xcel_addl.sql
```

If `scripts/metrics/requirements.txt` still lists `duckdb`, `pdfplumber`, `snowflake-connector-python`, `cryptography` — those are now transitive through the `metronome` dependency and this file is stale; leave it for the user to decide whether to trim (it's not imported by any code, just documentation of what used to be direct requirements).

- [ ] **Step 5: Report status to the user**

No commit in this task — it's verification only. Summarize for the user: test counts in both repos, confirmation the two CLIs still resolve, and the note from Task 11 Step 3 that `uv lock` should be run by the user once `uv` is available in their shell.
