# Writing Custom Parsers

Smaug uses a plugin architecture for parsing institution-specific spending
reports and invoices. This guide explains how to write and register your
own parser.

## Architecture Overview

Smaug discovers parsers at runtime via Python
[entry points](https://packaging.python.org/en/latest/specifications/entry-points/).
When loading reports, smaug iterates through all registered parsers and uses
the first one whose `can_parse()` method returns `True` for a given file.

```
                    ┌──────────────┐
                    │  ProjectStore │
                    │  load_reports │
                    └──────┬───────┘
                           │
                  ┌────────▼────────┐
                  │ For each file:  │
                  │ try parsers     │
                  └────────┬────────┘
                           │
            ┌──────────────┼──────────────┐
            ▼              ▼              ▼
    ┌──────────────┐ ┌──────────┐ ┌──────────────┐
    │ JHU Parser   │ │ CSV      │ │ Your Parser  │
    │ (built-in)   │ │ (built-in)│ │ (entry point)│
    └──────────────┘ └──────────┘ └──────────────┘
```

## Parser Types

There are two abstract base classes in `smaug.parsers`:

### `ReportParser` — Spending Reports

Parses monthly spending reports into `SpendingReport` objects with optional
per-person `EffortAllocation` data.

```python
from smaug.parsers import ReportParser
from smaug.models import SpendingReport, EffortAllocation

class MyInstitutionParser(ReportParser):
    def name(self) -> str:
        return "My Institution Sponsored Report"

    def can_parse(self, file_path: Path) -> bool:
        """Return True if this parser can handle the file."""
        # Check file extension, header content, etc.
        ...

    def parse(self, file_path: Path) -> tuple[SpendingReport | None, list[EffortAllocation]]:
        """Parse the file and return structured data."""
        ...
```

### `InvoiceParser` — Sponsor Invoices

Parses invoice documents (typically PDFs) into `Invoice` objects.

```python
from smaug.parsers import InvoiceParser
from smaug.models import Invoice

class MyInvoiceParser(InvoiceParser):
    def name(self) -> str:
        return "My Institution Invoice"

    def can_parse(self, file_path: Path) -> bool:
        ...

    def parse(self, file_path: Path) -> Invoice | None:
        ...
```

## Step-by-Step Guide

### 1. Create your parser module

Create a Python package for your parser. This can live anywhere — it doesn't
need to be inside the smaug source tree.

```
my-institution-parsers/
├── pyproject.toml
└── src/
    └── my_parsers/
        ├── __init__.py
        └── sponsored_report.py
```

### 2. Implement the parser

Here's a complete example for a CSV-based parser with a custom column layout:

```python
# src/my_parsers/sponsored_report.py

import csv
from decimal import Decimal
from pathlib import Path

from smaug.models import EffortAllocation, SpendingReport
from smaug.parsers import ReportParser


class MITSponsoredParser(ReportParser):
    """Parse MIT-format sponsored spending reports."""

    def name(self) -> str:
        return "MIT Sponsored Report"

    def can_parse(self, file_path: Path) -> bool:
        """Detect MIT reports by checking for a header marker."""
        if file_path.suffix.lower() != ".csv":
            return False
        try:
            with open(file_path) as f:
                header = f.readline()
                return "MIT_COST_OBJECT" in header
        except Exception:
            return False

    def parse(
        self, file_path: Path
    ) -> tuple[SpendingReport | None, list[EffortAllocation]]:
        """Parse the report into smaug's data model."""
        with open(file_path, newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        if not rows:
            return None, []

        # Use the last row (most recent cumulative data)
        row = rows[-1]

        report = SpendingReport(
            project_id=row["MIT_COST_OBJECT"],
            period=row["REPORT_PERIOD"],
            year=int(row["FISCAL_YEAR"]),
            month=int(row["FISCAL_MONTH"]),
            total_spent=Decimal(row["TOTAL_EXPENDITURES"]),
            total_committed=Decimal(row.get("TOTAL_ENCUMBRANCES", "0")),
            salary_spent=Decimal(row.get("SALARIES", "0")),
            fringe_spent=Decimal(row.get("FRINGE", "0")),
            travel_spent=Decimal(row.get("TRAVEL", "0")),
            indirect_spent=Decimal(row.get("INDIRECT", "0")),
        )

        # Compute total_spent_and_committed
        report.total_spent_and_committed = (
            report.total_spent + report.total_committed
        )

        return report, []
```

### 3. Register via entry points

In your package's `pyproject.toml`, register the parser under the
`smaug.parsers` entry point group:

```toml
[project]
name = "my-institution-parsers"
version = "0.1.0"
dependencies = ["smaug"]

[project.entry-points."smaug.parsers"]
mit_sponsored = "my_parsers.sponsored_report:MITSponsoredParser"
```

You can register multiple parsers in the same package:

```toml
[project.entry-points."smaug.parsers"]
mit_sponsored = "my_parsers.sponsored_report:MITSponsoredParser"
mit_invoice = "my_parsers.invoice:MITInvoiceParser"
```

### 4. Install and verify

```bash
pip install -e ./my-institution-parsers

# Smaug automatically discovers the new parser:
smaug list
```

## The SpendingReport Model

Your parser should populate as many fields as possible:

```python
SpendingReport(
    project_id="QUASAR",          # Maps to manifest.yaml identifiers
    period="September 2025",       # Human-readable period string
    year=2025,                     # Numeric year
    month=9,                       # Numeric month (1-12)

    # Summary totals (cumulative — running totals through this month)
    total_spent=Decimal("142500"),
    total_committed=Decimal("5000"),
    total_spent_and_committed=Decimal("147500"),
    indirect_spent=Decimal("45000"),

    # Category breakdowns (cumulative)
    salary_spent=Decimal("85000"),
    fringe_spent=Decimal("18000"),
    tuition_spent=Decimal("13334"),
    insurance_spent=Decimal("0"),
    service_center_spent=Decimal("0"),
    travel_spent=Decimal("3200"),
    other_spent=Decimal("1500"),

    # Monthly amounts (optional — single-month values)
    salary_month=Decimal("8500"),
    fringe_month=Decimal("1800"),

    # Funded ceiling (optional — total revenue received)
    funded_ceiling=Decimal("450000"),
)
```

**Important:** All `_spent` fields are **cumulative** (total through the
reporting month). Smaug computes monthly deltas from consecutive reports.
If your institution provides single-month values, populate the `_month`
fields as well.

## The CSV Format (Built-In)

If you can export your data as CSV, you may not need a custom parser at all.
The built-in CSV parser expects this schema:

```csv
project_id,period,year,month,total_spent,total_committed,salary_spent,fringe_spent,tuition_spent,travel_spent,other_spent,indirect_spent
QUASAR,September 2025,2025,9,142500.00,5000.00,85000.00,18000.00,13334.00,3200.00,1500.00,45000.00
QUASAR,October 2025,2025,10,158000.00,4500.00,93500.00,19800.00,13334.00,5400.00,2000.00,50000.00
```

Required columns: `project_id`, `year`, `month`, `total_spent`.
All other columns are optional.

## Validation

Smaug validates all parsed reports before storing them. Your parser's output
is automatically checked for:

- **Invalid dates** — year/month must be valid (non-zero, month 1-12)
- **Unknown project** — project_id must not be empty
- **Cross-field consistency** — `spent + committed ≈ spent_and_committed`
- **Category sum consistency** — category breakdown should approximate `total_spent`
- **Monotonicity** — cumulative `total_spent` should never decrease between months
- **All-zeros detection** — warns if a file parsed but produced no spending data

Reports that fail hard validation checks (invalid dates, unknown project) are
rejected entirely. Warnings (non-monotonic totals, category mismatches) are
logged but the report is still stored.

## Error Handling

If your parser encounters an unrecoverable error, return `(None, [])` from
`parse()`. Smaug will skip the file and continue with other reports.

If your parser raises an exception during `can_parse()` or `parse()`, smaug
catches it and emits a warning without crashing. However, clean error handling
in your parser is preferred.

## Built-In Parsers

Smaug ships with these parsers registered via entry points:

| Entry Point | Class | Format |
|---|---|---|
| `jhu_sponsored` | `JHUSponsoredParser` | JHU sponsored PDF reports |
| `jhu_non_sponsored` | `JHUNonSponsoredParser` | JHU discretionary PDF reports |
| `jhu_invoice` | `JHUInvoiceParser` | JHU Lockbox invoice PDFs |
| `csv` | `CSVReportParser` | Standardized CSV format |
