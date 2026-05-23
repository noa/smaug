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
"""

import csv
from decimal import Decimal, InvalidOperation
from pathlib import Path

from ..models import EffortAllocation, SpendingReport
from . import ReportParser


def _to_decimal(value: str) -> Decimal:
    """Convert a CSV cell to Decimal, defaulting to 0."""
    if not value or not value.strip():
        return Decimal("0")
    try:
        return Decimal(value.strip().replace(",", ""))
    except InvalidOperation:
        return Decimal("0")


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
        reports: list[SpendingReport] = []

        try:
            with open(file_path, newline="") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    report = SpendingReport(
                        project_id=row.get("project_id", "unknown"),
                        period=row.get("period", f"{row.get('year', '')}-{row.get('month', '')}"),
                        year=int(row.get("year", 0)),
                        month=int(row.get("month", 0)),
                        total_spent=_to_decimal(row.get("total_spent", "0")),
                        total_committed=_to_decimal(row.get("total_committed", "0")),
                        salary_spent=_to_decimal(row.get("salary_spent", "0")),
                        fringe_spent=_to_decimal(row.get("fringe_spent", "0")),
                        tuition_spent=_to_decimal(row.get("tuition_spent", "0")),
                        travel_spent=_to_decimal(row.get("travel_spent", "0")),
                        other_spent=_to_decimal(row.get("other_spent", "0")),
                        indirect_spent=_to_decimal(row.get("indirect_spent", "0")),
                    )
                    reports.append(report)
        except Exception as e:
            print(f"Warning: Error parsing CSV {file_path}: {e}")
            return None, []

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
                reader = csv.DictReader(f)
                for row in reader:
                    report = SpendingReport(
                        project_id=row.get("project_id", "unknown"),
                        period=row.get("period", f"{row.get('year', '')}-{row.get('month', '')}"),
                        year=int(row.get("year", 0)),
                        month=int(row.get("month", 0)),
                        total_spent=_to_decimal(row.get("total_spent", "0")),
                        total_committed=_to_decimal(row.get("total_committed", "0")),
                        salary_spent=_to_decimal(row.get("salary_spent", "0")),
                        fringe_spent=_to_decimal(row.get("fringe_spent", "0")),
                        tuition_spent=_to_decimal(row.get("tuition_spent", "0")),
                        travel_spent=_to_decimal(row.get("travel_spent", "0")),
                        other_spent=_to_decimal(row.get("other_spent", "0")),
                        indirect_spent=_to_decimal(row.get("indirect_spent", "0")),
                    )
                    reports.append(report)
        except Exception as e:
            print(f"Warning: Error parsing CSV {file_path}: {e}")

        return reports
