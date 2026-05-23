"""
Excel budget file parsing.

Extracts budget data from Excel spreadsheets following the JHU grant format.
"""

import contextlib
from decimal import Decimal, InvalidOperation
from pathlib import Path

import pandas as pd

from .models import BudgetLine, ProjectBudget


def parse_combined_sheet(file_path: str | Path) -> ProjectBudget:
    """
    Parse the 'Combined' sheet from a budget Excel file.

    Extracts yearly budget totals by category.

    Args:
        file_path: Path to the Excel budget file

    Returns:
        ProjectBudget with line items for each category/year
    """
    file_path = Path(file_path)
    xl = pd.ExcelFile(file_path)

    # Read Combined sheet without headers (complex layout)
    df = pd.read_excel(xl, "Combined", header=None)

    budget = ProjectBudget(project_id=file_path.parent.name)
    lines = []

    # Find the header row with year labels (row 3, 0-indexed)
    # Format: NaN, NaN, Year 01, Year 02, Year 03, Year 04, Year 05, SUBTOTALS
    year_row = df.iloc[3]
    year_columns = {}
    for col_idx, val in enumerate(year_row):
        if isinstance(val, str) and val.startswith("Year"):
            year_num = int(val.split()[1])
            year_columns[col_idx] = year_num

    # Category rows to extract (row index, category name)
    category_rows = {
        5: "Personnel",
        9: "Equipment",
        10: "Consultants",
        11: "Supplies",
        12: "Travel",
        13: "Patient Care - Inpatient",
        14: "Patient Care - Outpatient",
        15: "Alterations & Renovations",
        17: "Other Expenses",
        21: "Consortium Direct",
        23: "Consortium Indirect",
    }

    for row_idx, category in category_rows.items():
        if row_idx >= len(df):
            continue
        row = df.iloc[row_idx]
        for col_idx, year_num in year_columns.items():
            if col_idx < len(row):
                val = row.iloc[col_idx]
                if pd.notna(val) and val != 0:
                    with contextlib.suppress(InvalidOperation, ValueError):
                        amount = Decimal(str(val))
                        lines.append(BudgetLine(category=category, year=year_num, amount=amount))

    # Extract totals from specific rows
    total_direct_row = 25  # "TOTAL DIRECT COSTS FOR INITIAL BUDGET PERIOD"
    total_row = 29  # "TOTAL"
    idc_row = 27  # "IDC"

    if total_direct_row < len(df):
        row = df.iloc[total_direct_row]
        # Sum across year columns
        total = Decimal("0")
        for col_idx in year_columns:
            if col_idx < len(row) and pd.notna(row.iloc[col_idx]):
                with contextlib.suppress(InvalidOperation, ValueError):
                    total += Decimal(str(row.iloc[col_idx]))
        budget.total_direct_costs = total

    if idc_row < len(df):
        row = df.iloc[idc_row]
        total = Decimal("0")
        for col_idx in year_columns:
            if col_idx < len(row) and pd.notna(row.iloc[col_idx]):
                with contextlib.suppress(InvalidOperation, ValueError):
                    total += Decimal(str(row.iloc[col_idx]))
        budget.total_indirect_costs = total

    if total_row < len(df):
        row = df.iloc[total_row]
        total = Decimal("0")
        for col_idx in year_columns:
            if col_idx < len(row) and pd.notna(row.iloc[col_idx]):
                with contextlib.suppress(InvalidOperation, ValueError):
                    total += Decimal(str(row.iloc[col_idx]))
        budget.total_budget = total

    budget.lines = lines
    return budget


def parse_budget_file(file_path: str | Path) -> ProjectBudget | None:
    """
    Parse a budget Excel file and extract budget data.

    Looks for files matching *budget*.xlsx pattern.

    Args:
        file_path: Path to Excel file

    Returns:
        ProjectBudget or None if parsing fails
    """
    file_path = Path(file_path)

    if not file_path.exists():
        return None

    try:
        xl = pd.ExcelFile(file_path)
        if "Combined" in xl.sheet_names:
            return parse_combined_sheet(file_path)
    except Exception as e:
        print(f"Warning: Could not parse budget file {file_path}: {e}")

    return None
