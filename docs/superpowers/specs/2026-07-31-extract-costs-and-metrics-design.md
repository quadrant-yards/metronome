# Extract `metronome.costs` and `metronome.metrics` from data-pipelines2

## Context

`data-pipelines2` (the `sealedinc` client repo, at
`~/ghq/github.com/sealedinc/data-pipelines2/scripts/metrics/`) contains two pipelines that feed
the weekly Metrics meeting:

- **`eng_costs`** — parses vendor invoice PDFs (Dagster, GCP/DoiT, GitHub, Hex, Snowflake usage)
  into a monthly cost rollup, written to DuckDB + exported as CSV.
- **`product_analytics`** — runs a directory of Snowflake SQL source files on a weekly/monthly
  cadence, written to DuckDB + exported as CSV.

Both pipelines share a lot of generic machinery underneath client-specific "recipe" code. This
spec extracts the generic parts into `metronome` (this repo) as two new subpackages,
`metronome.costs` and `metronome.metrics`, and updates `data-pipelines2` to consume them.

## Scope

**In scope — moves to `metronome`:**
- `CostRow` / `MetricRow` models
- PDF text extraction
- The 5 vendor invoice parsers (Dagster, GCP, GitHub, Hex, Snowflake) — these parse standard
  vendor invoice formats, not anything Sealed-specific, so they're reusable across clients that
  use the same vendors
- Monthly rollup / gap-fill logic
- Month-name date parsing
- The DuckDB write + CSV export logic (both the eng_costs "replace" pattern and the
  product_analytics "upsert" pattern)
- The SQL-sources-directory runner
- The Snowflake key-pair connector

**Out of scope — stays in `data-pipelines2`:**
- `sources/*.sql` (`paco.sql`, `xcel_addl.sql`) — genuinely Sealed business logic
- CLI entry points (argparse, hardcoded paths like `data.local/Downloads.Sealed`, env var names)
- Anything reading `TRANSFORM_SNOWFLAKE_*` / `SNOWFLAKE_ACCOUNT` env vars directly

**Also in scope:** updating `data-pipelines2` itself to import from `metronome` instead of
keeping local copies, and porting the existing test suites.

## Package layout

```
src/metronome/
├── dateparse.py            # FULL_MONTHS, ABBREV_MONTHS, month_year_to_date — unchanged
├── snowflake_conn.py        # SnowflakeConfig dataclass, connect(config), execute_query(conn, sql)
├── costs/
│   ├── __init__.py
│   ├── models.py            # CostRow
│   ├── pdf_text.py          # extract_text
│   ├── rollup.py            # resolve_monthly(rows, sum_on_collision=frozenset())
│   ├── pipeline.py          # parse_all, run(...)
│   └── vendors/
│       ├── __init__.py       # ALL = [dagster, gcp, github, hex, snowflake]
│       ├── dagster.py
│       ├── gcp.py
│       ├── github.py
│       ├── hex.py
│       └── snowflake.py
└── metrics/
    ├── __init__.py
    ├── models.py             # MetricRow
    ├── store.py              # write_replace, write_upsert, export_csv, trailing_window_start
    └── sql_runner.py         # run_all(period, execute_query, sources_dir)
```

## Components

### `dateparse.py`

Ported verbatim: `FULL_MONTHS`, `ABBREV_MONTHS`, `month_year_to_date(month_name, year,
month_names)`. No client-specific content.

### `snowflake_conn.py`

Currently reads six env vars directly (`SNOWFLAKE_ACCOUNT`, `TRANSFORM_SNOWFLAKE_USER`,
`TRANSFORM_SNOWFLAKE_PRIVATE_KEY`, `TRANSFORM_SNOWFLAKE_ROLE`, `TRANSFORM_SNOWFLAKE_DATABASE`,
`TRANSFORM_SNOWFLAKE_WAREHOUSE`). The generic version takes an explicit config object instead:

```python
@dataclass(frozen=True)
class SnowflakeConfig:
    account: str
    user: str
    private_key_pem: str
    role: str
    database: str
    warehouse: str

@contextmanager
def connect(config: SnowflakeConfig) -> Iterator[SnowflakeConnection]: ...

def execute_query(conn: SnowflakeConnection, sql: str) -> list[tuple]: ...
```

`data-pipelines2`'s `cli.py` keeps reading its own env vars and builds `SnowflakeConfig` from
them before calling `connect()`.

### `costs/models.py`

`CostRow` ported verbatim (frozen dataclass: `metric_name`, `metric_date`, `metric_value`,
`source_file`, `statement_date`).

### `costs/pdf_text.py`

`extract_text(path: Path) -> str` ported verbatim.

### `costs/vendors/`

Each vendor module ports verbatim: `detect(text: str) -> bool`, `parse(text: str, source_file:
str) -> list[CostRow]`. `vendors/__init__.py` exposes `ALL = [dagster, gcp, github, hex,
snowflake]` as the default registry, so `data-pipelines2` (or any future client) can pass a
custom list to add vendors without forking.

### `costs/rollup.py`

`resolve_monthly` ported with one change — the vendor-summing policy becomes a parameter instead
of a module constant:

```python
def resolve_monthly(
    rows: list[CostRow],
    sum_on_collision: frozenset[str] = frozenset(),
) -> list[CostRow]: ...
```

`data-pipelines2` passes `frozenset({"GitHub"})` at the call site to preserve current behavior.

### `costs/pipeline.py`

`parse_all` ported near-verbatim, taking a vendor list instead of a hardcoded module list:

```python
def parse_all(
    downloads_dir: Path,
    text_extractor: TextExtractor = extract_text,
    vendors: list[VendorModule] = vendors.ALL,
) -> list[CostRow]: ...
```

`run(...)` ported with the CSV floor date de-hardcoded:

```python
def run(
    downloads_dir: Path,
    db_path: Path,
    csv_path: Path,
    text_extractor: TextExtractor = extract_text,
    vendors: list[VendorModule] = vendors.ALL,
    csv_export_months: int = 12,
    csv_export_floor: date | None = None,
) -> None: ...
```

Internally, `write_outputs` is rebuilt on top of `metrics.store`: `write_replace` for
`raw_costs` and `monthly_costs`, `export_csv` for the trailing-window CSV, `trailing_window_start`
for the window math (replacing `_shift_months`/`_csv_export_start_date`). Transaction lifecycle
(`BEGIN`/`COMMIT`/`ROLLBACK`, connection open/close) stays owned by this function, same as today
— `store.py` functions operate on an already-open connection and don't manage transactions
themselves.

`count_new_rows` and `_read_previous_source_files` port verbatim (they're already generic).

`data-pipelines2`'s `cli.py` supplies `csv_export_floor=date(2025, 11, 1)` at the call site to
preserve current behavior.

### `metrics/models.py`

`MetricRow` ported verbatim.

### `metrics/store.py`

New module factoring out what's currently duplicated between the two pipelines'
`write_outputs`:

```python
def write_replace(
    con: DuckDBPyConnection, table: str, columns: list[str], rows: list[tuple],
) -> None:
    """DROP + CREATE + INSERT — full replace of a table's contents."""

def write_upsert(
    con: DuckDBPyConnection, table: str, columns: list[str],
    key_columns: list[str], rows: list[tuple],
) -> None:
    """CREATE IF NOT EXISTS, DELETE matching key_columns, then INSERT."""

def export_csv(
    con: DuckDBPyConnection, query: str, params: list, csv_path: Path,
) -> None:
    """COPY (query) TO csv_path (HEADER, DELIMITER ',')."""

def trailing_window_start(
    anchor: date, count: int, unit: Literal["months", "weeks"], floor: date | None = None,
) -> date:
    """Shift `anchor` back `count - 1` units; clamp to `floor` if given."""
```

`write_replace` covers eng_costs' `raw_costs`/`monthly_costs` pattern. `write_upsert` covers
product_analytics' `product_weekly`/`product_monthly` pattern. `trailing_window_start`
generalizes eng_costs' `_shift_months`/`_csv_export_start_date` and product_analytics' `_shift`
over the `"months"`/`"weeks"` distinction.

### `metrics/sql_runner.py`

`run_all(period, execute_query, sources_dir)` ported verbatim from product_analytics'
`pipeline.py` — sets the `period` SQL variable, globs `*.sql` in `sources_dir`, runs each,
converts rows to `MetricRow`, logs and skips on per-file failure.

### `metrics/pipeline.py`

Product_analytics' `write_outputs`/`run` move into metronome too, symmetric with
`costs/pipeline.py` — nothing in them is Sealed-specific. Rebuilt on
`metrics.store.write_upsert` + `metrics.store.export_csv` + `metrics.store.trailing_window_start`
the same way costs' `run` is rebuilt on `write_replace`:

```python
def run(
    period: str,
    execute_query: QueryExecutor,
    db_path: Path,
    csv_path: Path,
    sources_dir: Path,
    csv_export_weeks: int = 12,
    csv_export_months: int = 12,
) -> None: ...
```

`data-pipelines2`'s `cli.py` supplies its own `sources_dir` (pointing at its local `sources/`
directory of `.sql` files) and calls this directly.

## `data-pipelines2` changes

- `scripts/metrics/eng_costs/` shrinks to just `cli.py`: argparse, the `data.local/...` default
  paths, and the call into `metronome.costs.pipeline.run(...)` with `sum_on_collision` and
  `csv_export_floor` supplied. `models.py`, `pdf_text.py`, `rollup.py`, `pipeline.py`, and
  `vendors/` are deleted.
- `scripts/metrics/product_analytics/` shrinks to `cli.py` + `sources/*.sql`: `cli.py` reads
  `TRANSFORM_SNOWFLAKE_*` env vars, builds `SnowflakeConfig`, and calls
  `metronome.snowflake_conn.connect()` + `metronome.metrics.pipeline.run(...)`, passing its own
  `sources_dir`. `models.py`, `snowflake_conn.py`, and `pipeline.py` are deleted.
- `dateparse.py` (top-level, if it's shared) is deleted; nothing needs to import it directly
  since vendor parsers now live in metronome and import `metronome.dateparse` internally.
- Corresponding test files (`test_dateparse.py`, `test_rollup.py`, `test_pipeline.py` (both),
  each vendor's test) are deleted from `data-pipelines2/tests/metrics/` — that coverage moves to
  metronome. `test_source_files.py` (covers the SQL files themselves) and any CLI-level
  integration tests that exercise Sealed-specific paths stay.
- `metronome` is added as an editable dependency: `data-pipelines2` uses `uv` + a `sealed` pyenv
  env (not the `pyme` env metronome's setup brief describes), so wiring is
  `uv add --editable ~/ghq/github.com/quadrant-yards/metronome` run from `data-pipelines2` — same
  mechanism, different env than the brief's worked example.

## Testing

Port and adapt the existing pytest suites into `metronome`:
- `test_dateparse.py`
- `test_rollup.py` (add cases for the new `sum_on_collision` parameter)
- `test_pipeline.py` for costs (update for `vendors`/`csv_export_floor` params)
- one test file per vendor parser
- `test_snowflake_conn.py` (update for `SnowflakeConfig`)
- new tests for `metrics/store.py` (`write_replace`, `write_upsert`, `export_csv`,
  `trailing_window_start`) since this module is new, not a straight port
- `test_pipeline.py` for `metrics/` covering `sql_runner.run_all` and `pipeline.run`
  (adapted from product_analytics' existing `test_pipeline.py`/`test_cli.py`)

Style matches the source repo: behavior-driven pytest, `tmp_path` fixtures, real DuckDB
connections (no mocking).

## Dependencies

`pyproject.toml` gains:

```toml
dependencies = [
    "duckdb>=1.4.5",
    "pdfplumber>=0.11.8",
    "snowflake-connector-python>=3.18.0",
    "cryptography>=44.0.0",
]

[dependency-groups]
dev = ["pytest>=8.0.0"]
```

(Versions match what `data-pipelines2/scripts/metrics/requirements.txt` currently pins.)

## Non-goals

- No changes to the meeting format, the Sheets template, or any Claude skills in this pass.
- No CLI scaffold/framework in metronome (each client repo keeps its own `cli.py`).
- No changes to `engagements` (metronome's currently-documented consumer) — `data-pipelines2` is
  a separate, new consumer wired up as part of this work.
