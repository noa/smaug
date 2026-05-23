"""
Sponsored PDF report parsing.

Extracts spending data and personnel costs from JHU sponsored project reports.
"""

import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

import pdfplumber

from .models import (
    EffortAllocation,
    EmployeeType,
    SpendingReport,
)


def clean_text_to_decimal(text: str | None) -> Decimal | None:
    """
    Converts a currency string (e.g., "1,325.88" or "(9,034.52)") to a Decimal.
    Returns None if text is empty or invalid.
    """
    if not text or not str(text).strip():
        return None

    # Remove commas, parentheses (for negative), and whitespace
    cleaned_text = str(text).strip().replace(",", "").replace("(", "-").replace(")", "")

    if not cleaned_text:
        return None

    try:
        return Decimal(cleaned_text)
    except InvalidOperation:
        return None


def parse_employee_type(gl_account: str) -> EmployeeType:
    """Determine employee type from G/L account description."""
    gl_lower = gl_account.lower()
    if "faculty" in gl_lower:
        return EmployeeType.FACULTY
    elif "postdoc" in gl_lower:
        return EmployeeType.POSTDOC
    elif "student grad" in gl_lower or "grad student" in gl_lower:
        return EmployeeType.GRAD_STUDENT
    elif "staff" in gl_lower or "nadm" in gl_lower:
        return EmployeeType.STAFF
    return EmployeeType.UNKNOWN


def parse_sponsored_summary(page) -> dict:
    """
    Parse the first page of a sponsored report to extract summary costs.

    Returns dict with:
        - project_id: Grant number
        - grant_name: Grant name
        - sponsored_program: SP number
        - award_id: Award ID
        - period: Month/Year string
        - year: Fiscal year
        - month: Month number
        - totals: Various spending totals
    """
    text = page.extract_text()
    result = {}

    # Extract grant info
    grant_match = re.search(r"Grant:\s+(\d+)\s+-\s+(.*?)\s+PI For", text)
    if grant_match:
        result["grant_number"] = grant_match.group(1)
        result["grant_name"] = grant_match.group(2).strip()

    # Extract sponsored program
    sp_match = re.search(r"Sponsored Program:\s+(\d+)\s+-\s+(\S+)", text)
    if sp_match:
        result["sponsored_program"] = sp_match.group(1)
        result["award_id"] = sp_match.group(2)

    # Extract report date from "Expenditures Budget Month Year"
    date_match = re.search(r"Expenditures Budget\s+([A-Za-z]+)\s+(\d{4})", text)
    if date_match:
        month_name = date_match.group(1)
        year = date_match.group(2)
        result["period"] = f"{month_name} {year}"
        result["year"] = int(year)
        try:
            result["month"] = datetime.strptime(month_name, "%B").month
        except ValueError:
            result["month"] = 1

    # Extract total expenditures
    # Format: Total Expenditures <budget> <monthly> <cum_spent> <committed> <spent+committed> ...
    exp_match = re.search(
        r"Total Expenditures\s+[\d,.()-]+\s+([\d,.-]+)\s+([\d,.-]+)\s+([\d,.-]+)\s+([\d,.-]+)", text
    )
    if exp_match:
        result["total_month"] = clean_text_to_decimal(exp_match.group(1))
        result["total_spent"] = clean_text_to_decimal(exp_match.group(2))
        result["total_committed"] = clean_text_to_decimal(exp_match.group(3))
        result["total_spent_and_committed"] = clean_text_to_decimal(exp_match.group(4))

    # Extract indirect costs
    # Format: Total Indirect Costs <budget(often 0)> <monthly> <cum_spent> <committed> <spent+committed>
    indirect_match = re.search(
        r"Total Indirect Costs\s+[\d,.()-]+\s+([\d,.-]+)\s+([\d,.-]+)\s+[\d,.-]+\s+([\d,.-]+)", text
    )
    if indirect_match:
        result["indirect_month"] = clean_text_to_decimal(indirect_match.group(1))
        result["indirect_spent"] = clean_text_to_decimal(indirect_match.group(2))

    # Extract budget utilization percentage
    util_match = re.search(r"Budget Utilized:\s+([\d.]+)%", text)
    if util_match:
        result["budget_utilized_pct"] = Decimal(util_match.group(1))

    # Extract funded ceiling from Sponsored Revenue line
    # Format: "Sponsored Revenue <amount> <amount> <amount> ..."
    rev_match = re.search(r"Sponsored Revenue\s+([\d,]+\.\d{2})", text)
    if rev_match:
        result["funded_ceiling"] = clean_text_to_decimal(rev_match.group(1))

    # Extract category breakdowns
    # Each category line: "Category Name  <month_amt>  <cum_spent>  <committed>  <spent+committed>"
    # We capture both the monthly amount and cumulative total spent.
    # Format: (regex, month_group, spent_group, committed_group_or_None)
    category_patterns = {
        "salary": (r"Salaries \& Wages\s+([\d,.()-]+)\s+([\d,.()-]+)\s+([\d,.()-]+)", 1, 2, 3),
        "fringe": (r"Fringe Benefits\s+([\d,.()-]+)\s+([\d,.()-]+)\s+([\d,.()-]+)", 1, 2, 3),
        "tuition": (r"Tuition \& Fees\s+([\d,.()-]+)\s+([\d,.()-]+)\s+([\d,.()-]+)", 1, 2, None),
        "insurance": (
            r"(?:Student Health Insurance|Total Student Health)\s+([\d,.()-]+)\s+([\d,.()-]+)\s+([\d,.()-]+)",
            1,
            2,
            None,
        ),
        "service_center": (
            r"(?:Service Center|Total Service Center)\s+([\d,.()-]+)\s+([\d,.()-]+)\s+([\d,.()-]+)",
            1,
            2,
            None,
        ),
        "travel": (r"Travel Domestic\s+([\d,.()-]+)\s+([\d,.()-]+)\s+([\d,.()-]+)", 1, 2, None),
        "other": (r"Other Expenses\s+([\d,.()-]+)\s+([\d,.()-]+)\s+([\d,.()-]+)", 1, 2, None),
    }

    for key, (pattern, month_group, spent_group, committed_group) in category_patterns.items():
        match = re.search(pattern, text)
        if match:
            result[f"{key}_month"] = clean_text_to_decimal(match.group(month_group))
            result[f"{key}_spent"] = clean_text_to_decimal(match.group(spent_group))
            if committed_group:
                result[f"{key}_committed"] = clean_text_to_decimal(match.group(committed_group))

    return result


def parse_personnel_page(
    page, report_period: str = "Unknown", report_project_id: str = "unknown"
) -> list[EffortAllocation]:
    """
    Parse a salary report page to extract personnel effort allocations.

    Args:
        page: pdfplumber page object
        report_period: Period string from report summary (e.g., "November 2025")
                      used as fallback when page doesn't have its own date header
        report_project_id: Grant number from report summary, used as fallback
                          when page doesn't have its own Grant header

    Returns list of EffortAllocation objects.
    """
    text = page.extract_text()
    allocations = []

    # Check if this is a salary page
    if "Salary Report" not in text and "Total for" not in text:
        return []

    # Extract project identifier from page, fall back to report-level project_id
    grant_match = re.search(r"Grant:\s+(\d+)", text)
    project_id = grant_match.group(1) if grant_match else report_project_id

    # Extract period from page header if available
    date_match = re.search(
        r"([A-Za-z]+)\s+(\d{4})\s*$", text.split("\n")[1] if len(text.split("\n")) > 1 else ""
    )
    if not date_match:
        date_match = re.search(r"([A-Za-z]+)\s+(\d{4})", text[:500])

    # Use page-specific date if found, otherwise fall back to report period
    period = f"{date_match.group(1)} {date_match.group(2)}" if date_match else report_period

    # Parse individual salary lines
    lines = text.split("\n")
    for line in lines:
        # Look for person totals: "Total for Name AMOUNT"
        total_match = re.search(r"Total for (.*?)\s+([\d,]+\.\d{2})", line)
        if total_match:
            name = total_match.group(1).strip()

            # Skip non-person entries (transaction references, document IDs, etc.)
            if name.startswith("Ref.") or name.startswith("Doc") or re.match(r"^[\d#\s]+$", name):
                continue

            salary = clean_text_to_decimal(total_match.group(2))
            if salary:
                # Try to get employee type from previous lines
                emp_type = EmployeeType.UNKNOWN
                # Search backwards for GL account
                for prev_line in lines[: lines.index(line)][::-1]:
                    if name.split(",")[0] in prev_line:
                        if "FACULTY" in prev_line:
                            emp_type = EmployeeType.FACULTY
                        elif "POSTDOC" in prev_line:
                            emp_type = EmployeeType.POSTDOC
                        elif "STUDENT GRAD" in prev_line or "STU POSTDOC" in prev_line:
                            emp_type = EmployeeType.GRAD_STUDENT
                        elif "STAFF" in prev_line or "NADM" in prev_line:
                            emp_type = EmployeeType.STAFF
                        break

                allocations.append(
                    EffortAllocation(
                        person_name=name,
                        project_id=project_id,
                        period=period,
                        salary_amount=salary,
                        employee_type=emp_type,
                    )
                )

    return allocations


def parse_sponsored_report(
    file_path: str | Path,
) -> tuple[SpendingReport | None, list[EffortAllocation]]:
    """
    Parse a complete sponsored project PDF report.

    Args:
        file_path: Path to the PDF file

    Returns:
        Tuple of (SpendingReport, list of EffortAllocation)
    """
    file_path = Path(file_path)

    spending_report = None
    all_personnel = []

    try:
        with pdfplumber.open(file_path) as pdf:
            # Page 1: Summary
            if pdf.pages:
                summary = parse_sponsored_summary(pdf.pages[0])

                spending_report = SpendingReport(
                    project_id=summary.get("grant_number", "unknown"),
                    period=summary.get("period", "Unknown"),
                    year=summary.get("year", 0),
                    month=summary.get("month", 0),
                    total_spent=summary.get("total_spent", Decimal("0")) or Decimal("0"),
                    total_committed=summary.get("total_committed", Decimal("0")) or Decimal("0"),
                    total_spent_and_committed=summary.get("total_spent_and_committed", Decimal("0"))
                    or Decimal("0"),
                    indirect_spent=summary.get("indirect_spent", Decimal("0")) or Decimal("0"),
                    budget_utilized_pct=summary.get("budget_utilized_pct"),
                    # Category breakdowns (cumulative)
                    salary_spent=summary.get("salary_spent", Decimal("0")) or Decimal("0"),
                    fringe_spent=summary.get("fringe_spent", Decimal("0")) or Decimal("0"),
                    tuition_spent=summary.get("tuition_spent", Decimal("0")) or Decimal("0"),
                    insurance_spent=summary.get("insurance_spent", Decimal("0")) or Decimal("0"),
                    service_center_spent=summary.get("service_center_spent", Decimal("0"))
                    or Decimal("0"),
                    travel_spent=summary.get("travel_spent", Decimal("0")) or Decimal("0"),
                    other_spent=summary.get("other_spent", Decimal("0")) or Decimal("0"),
                    # Monthly (single-month) category amounts
                    salary_month=summary.get("salary_month"),
                    fringe_month=summary.get("fringe_month"),
                    tuition_month=summary.get("tuition_month"),
                    insurance_month=summary.get("insurance_month"),
                    service_center_month=summary.get("service_center_month"),
                    travel_month=summary.get("travel_month"),
                    other_month=summary.get("other_month"),
                    indirect_month=summary.get("indirect_month"),
                    # Commitments and ceiling
                    salary_committed=summary.get("salary_committed", Decimal("0")) or Decimal("0"),
                    fringe_committed=summary.get("fringe_committed", Decimal("0")) or Decimal("0"),
                    funded_ceiling=summary.get("funded_ceiling"),
                )

            # All pages: Personnel
            # Pass the report period and project_id from summary to handle continuation pages
            report_period = summary.get("period", "Unknown")
            report_project_id = summary.get("grant_number", "unknown")
            for page in pdf.pages:
                personnel = parse_personnel_page(page, report_period, report_project_id)
                all_personnel.extend(personnel)

    except Exception as e:
        print(f"Warning: Error parsing {file_path}: {e}")

    return spending_report, all_personnel


def parse_non_sponsored_summary(page) -> dict:
    """
    Parse the first page of a non-sponsored (discretionary) report.
    """
    text = page.extract_text()
    result = {}

    # Extract funded program
    fp_match = re.search(r"Funded Program:\s+(\d+)\s+-\s+(.*?)\s+Fund:", text)
    if fp_match:
        result["funded_program"] = fp_match.group(1)
        result["fund_name"] = fp_match.group(2).strip()

    # Extract period from header
    lines = text.split("\n")
    for line in lines[:5]:
        date_match = re.search(r"([A-Za-z]+)\s+(\d{4})", line)
        if date_match:
            result["period"] = f"{date_match.group(1)} {date_match.group(2)}"
            result["year"] = int(date_match.group(2))
            try:
                result["month"] = datetime.strptime(date_match.group(1), "%B").month
            except ValueError:
                result["month"] = 1
            break

    # Extract YTD expenditures
    ytd_match = re.search(r"YTD Expenditures:\s+([\d,.-]+)", text)
    if ytd_match:
        result["total_spent"] = clean_text_to_decimal(ytd_match.group(1))

    # Extract month-end balance
    bal_match = re.search(r"Month-End Balance:\s+\(?([\d,.-]+)\)?", text)
    if bal_match:
        result["balance"] = clean_text_to_decimal(bal_match.group(1))

    return result


def parse_non_sponsored_report(file_path: str | Path) -> SpendingReport | None:
    """
    Parse a non-sponsored (discretionary) PDF report.

    Args:
        file_path: Path to the PDF file

    Returns:
        SpendingReport or None
    """
    file_path = Path(file_path)

    try:
        with pdfplumber.open(file_path) as pdf:
            if pdf.pages:
                summary = parse_non_sponsored_summary(pdf.pages[0])

                return SpendingReport(
                    project_id=summary.get("funded_program", "unknown"),
                    period=summary.get("period", "Unknown"),
                    year=summary.get("year", 0),
                    month=summary.get("month", 0),
                    total_spent=summary.get("total_spent", Decimal("0")) or Decimal("0"),
                )
    except Exception as e:
        print(f"Warning: Error parsing {file_path}: {e}")

    return None
