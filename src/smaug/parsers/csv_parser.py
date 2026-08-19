"""
CSV Report parser — the default built-in parser.

Reads spending reports in a standardized CSV format that any institution
can produce from their financial system.  This allows users to get
started without writing a custom PDF parser.

Expected CSV schema::

    project_id,period,year,month,total_spent,total_committed,salary_spent,fringe_spent,tuition_spent,travel_spent,other_spent,indirect_spent

Example row::

    QUASAR,September 2025,2025,9,142500.00,5000.00,85000.00,18000.00,13334.00,3200.00,1500.00,45000.00

All monetary fields are cumulative (running totals through the
reporting month).  Fields beyond ``total_committed`` are optional.

Optional award columns, when present, let a CSV-fed project use the same
forecasting as a PDF-fed one::

    funded_ceiling      amount the sponsor has actually obligated (drives
                        stop-work forecasts, and is not the same as the
                        authorized total budget)
    total_revenue_received, revenue_month
    budget_start_date, budget_end_date, grant_end_date   (YYYY-MM-DD)
    stated_idc_rate, grantor_code
"""

import csv
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from ..models import EffortAllocation, SpendingReport
from . import ReportParser

# Cumulative category columns, all optional and defaulting to zero
_CATEGORY_COLUMNS = (
    "salary",
    "fringe",
    "tuition",
    "insurance",
    "service_center",
    "travel",
    "travel_foreign",
    "supplies",
    "equipment",
    "subcontracts",
    "consultant",
    "other",
)


def _to_decimal(value: str) -> Decimal:
    """Convert a CSV cell to Decimal, defaulting to 0."""
    if not value or not value.strip():
        return Decimal("0")
    try:
        return Decimal(value.strip().replace(",", ""))
    except InvalidOperation:
        return Decimal("0")


def _optional_decimal(row: dict, key: str) -> Decimal | None:
    """Decimal for a column that may be absent or blank."""
    raw = row.get(key)
    if raw is None or not str(raw).strip():
        return None
    try:
        return Decimal(str(raw).strip().replace(",", ""))
    except InvalidOperation:
        return None


def _optional_date(row: dict, key: str) -> date | None:
    """Date for a column that may be absent or blank (YYYY-MM-DD or YYYY-MM)."""
    raw = row.get(key)
    if raw is None or not str(raw).strip():
        return None
    text = str(raw).strip()
    for fmt in ("%Y-%m-%d", "%Y-%m", "%m/%d/%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _row_to_report(row: dict) -> SpendingReport:
    """Build a SpendingReport from one CSV row."""
    report = SpendingReport(
        project_id=row.get("project_id", "unknown"),
        period=row.get("period", f"{row.get('year', '')}-{row.get('month', '')}"),
        year=int(row.get("year", 0)),
        month=int(row.get("month", 0)),
        total_spent=_to_decimal(row.get("total_spent", "0")),
        total_committed=_to_decimal(row.get("total_committed", "0")),
        total_month=_optional_decimal(row, "total_month"),
        indirect_spent=_to_decimal(row.get("indirect_spent", "0")),
        indirect_month=_optional_decimal(row, "indirect_month"),
        funded_ceiling=_optional_decimal(row, "funded_ceiling"),
        total_revenue_received=_optional_decimal(row, "total_revenue_received"),
        revenue_month=_optional_decimal(row, "revenue_month"),
        stated_idc_rate=_optional_decimal(row, "stated_idc_rate"),
        grantor_code=(row.get("grantor_code") or "").strip() or None,
        budget_start_date=_optional_date(row, "budget_start_date"),
        budget_end_date=_optional_date(row, "budget_end_date"),
        grant_end_date=_optional_date(row, "grant_end_date"),
    )

    for prefix in _CATEGORY_COLUMNS:
        setattr(report, f"{prefix}_spent", _to_decimal(row.get(f"{prefix}_spent", "0")))
        month_value = _optional_decimal(row, f"{prefix}_month")
        if month_value is not None:
            setattr(report, f"{prefix}_month", month_value)

    explicit_total = _optional_decimal(row, "total_spent_and_committed")
    report.total_spent_and_committed = (
        explicit_total
        if explicit_total is not None
        else report.total_spent + report.total_committed
    )
    return report


class CSVReportParser(ReportParser):
    """Parse spending reports from a standardized CSV file."""

    def name(self) -> str:
        return "CSV Report"

    def can_parse(self, file_path: Path) -> bool:
        if file_path.suffix.lower() != ".csv":
            return False
        try:
            with open(file_path, newline="") as f:
                reader = csv.DictReader(f)
                fields = reader.fieldnames or []
                # Require at minimum: project_id, year, month, total_spent
                return all(col in fields for col in ("project_id", "year", "month", "total_spent"))
        except Exception:
            return False

    def parse(self, file_path: Path) -> tuple[SpendingReport | None, list[EffortAllocation]]:
        """Parse all rows from a CSV file.

        Note: unlike PDF parsers that return a single report, a CSV file
        may contain multiple rows (one per month).  We return the *last*
        row as the SpendingReport (most recent) and an empty personnel
        list (CSV format doesn't include per-person salary data).
        """
        reports = self.parse_all(file_path)
        if not reports:
            return None, []

        # Return the most recent report
        reports.sort(key=lambda r: (r.year, r.month))
        return reports[-1], []

    def parse_all(self, file_path: Path) -> list[SpendingReport]:
        """Parse all rows from a CSV, returning every report.

        This is used by the store to load multi-month CSV files.
        """
        reports: list[SpendingReport] = []

        try:
            with open(file_path, newline="") as f:
                for row in csv.DictReader(f):
                    reports.append(_row_to_report(row))
        except Exception as e:
            print(f"Warning: Error parsing CSV {file_path}: {e}")

        return reports
