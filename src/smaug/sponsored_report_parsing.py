"""
Sponsored PDF report parsing.

Extracts spending data and personnel costs from JHU sponsored project reports.
"""

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

import pdfplumber

from .models import (
    CommitmentDetail,
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


def _parse_date_flexible(val: str | None) -> date | None:
    """Parse flexible date strings (MM/DD/YYYY, MM/DD/YY, MM/YYYY, YYYY-MM-DD, YYYY-MM)."""
    if not val or not str(val).strip():
        return None
    val_str = str(val).strip()
    for fmt in ("%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d", "%m/%Y", "%Y-%m"):
        try:
            dt = datetime.strptime(val_str, fmt)
            return dt.date()
        except ValueError:
            pass
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
    elif "masters" in gl_lower:
        return EmployeeType.MASTERS_STUDENT
    elif "staff" in gl_lower or "nadm" in gl_lower:
        return EmployeeType.STAFF
    return EmployeeType.UNKNOWN


def parse_sponsored_summary(page) -> dict:
    """
    Parse the first page of a sponsored report to extract summary costs and metadata.

    Returns dict with summary amounts, categories, dates, revenue, and ceiling.
    """
    text = page.extract_text() or ""
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
    # Format: Total Expenditures [<budget>] <monthly> <cum_spent> <committed> <spent+committed>
    exp_match = re.search(
        r"Total Expenditures\s+(?:[\d,.()-]+\s+)?([\d,.-]+)\s+([\d,.-]+)\s+([\d,.-]+)\s+([\d,.-]+)",
        text,
    )
    if exp_match:
        result["total_month"] = clean_text_to_decimal(exp_match.group(1))
        result["total_spent"] = clean_text_to_decimal(exp_match.group(2))
        result["total_committed"] = clean_text_to_decimal(exp_match.group(3))
        result["total_spent_and_committed"] = clean_text_to_decimal(exp_match.group(4))

    # Extract indirect costs
    indirect_match = re.search(
        r"Total Indirect Costs\s+(?:[\d,.()-]+\s+)?([\d,.-]+)\s+([\d,.-]+)(?:\s+[\d,.-]+)?\s+([\d,.-]+)",
        text,
    )
    if indirect_match:
        result["indirect_month"] = clean_text_to_decimal(indirect_match.group(1))
        result["indirect_spent"] = clean_text_to_decimal(indirect_match.group(2))

    # Extract budget utilization percentage
    util_match = re.search(r"Budget Utilized:\s+([\d.]+)%", text)
    if util_match:
        result["budget_utilized_pct"] = Decimal(util_match.group(1))

    # Extract funded ceiling and revenue info
    rev_match = re.search(r"Sponsored Revenue\s+([\d,]+\.\d{2})(?:\s+([\d,]+\.\d{2}))?", text)
    if rev_match:
        result["funded_ceiling"] = clean_text_to_decimal(rev_match.group(1))
        result["total_revenue_received"] = clean_text_to_decimal(rev_match.group(1))
        if rev_match.group(2):
            result["revenue_month"] = clean_text_to_decimal(rev_match.group(2))

    tot_rec_match = re.search(r"Total Received:?\s*([\d,]+\.\d{2})", text, re.IGNORECASE)
    if tot_rec_match:
        result["total_revenue_received"] = clean_text_to_decimal(tot_rec_match.group(1))
        if not result.get("funded_ceiling"):
            result["funded_ceiling"] = result["total_revenue_received"]

    rec_month_match = re.search(
        r"(?:Month|July|August|September|October|November|December|January|February|March|April|May|June)\s+Receipts:?\s*([\d,]+\.\d{2})",
        text,
        re.IGNORECASE,
    )
    if rec_month_match:
        result["revenue_month"] = clean_text_to_decimal(rec_month_match.group(1))

    # Extract award metadata (dates, grantor, IDC rate)
    begin_match = re.search(
        r"Budget Begin(?: Date)?:?\s*(\d{1,2}/\d{1,2}/\d{2,4}|\d{4}-\d{2}-\d{2})",
        text,
        re.IGNORECASE,
    )
    if begin_match:
        result["budget_start_date"] = _parse_date_flexible(begin_match.group(1))
    else:
        period_match = re.search(
            r"Budget Period:?\s*(\d{1,2}/\d{1,2}/\d{2,4})\s+to\s+(\d{1,2}/\d{1,2}/\d{2,4})",
            text,
            re.IGNORECASE,
        )
        if period_match:
            result["budget_start_date"] = _parse_date_flexible(period_match.group(1))
            result["budget_end_date"] = _parse_date_flexible(period_match.group(2))

    if "budget_end_date" not in result:
        end_match = re.search(
            r"Budget End(?: Date)?:?\s*(\d{1,2}/\d{1,2}/\d{2,4}|\d{4}-\d{2}-\d{2})",
            text,
            re.IGNORECASE,
        )
        if end_match:
            result["budget_end_date"] = _parse_date_flexible(end_match.group(1))

    proj_end_match = re.search(
        r"(?:Grant Project End Date|Project End Date):?\s*(\d{1,2}/\d{1,2}/\d{2,4}|\d{4}-\d{2}-\d{2})",
        text,
        re.IGNORECASE,
    )
    if proj_end_match:
        result["grant_end_date"] = _parse_date_flexible(proj_end_match.group(1))

    grantor_match = re.search(r"Grantor(?:\s+Code)?:?\s*([A-Za-z0-9_-]+)", text, re.IGNORECASE)
    if grantor_match:
        result["grantor_code"] = grantor_match.group(1).strip()

    fa_match = re.search(
        r"(?:F\s*&\s*A|IDC|Indirect Cost)\s+Rate:?\s*([\d.]+)%",
        text,
        re.IGNORECASE,
    )
    if fa_match:
        result["stated_idc_rate"] = clean_text_to_decimal(fa_match.group(1))

    # Extract category breakdowns
    # Each category line: "Category Name  <month_amt>  <cum_spent>  [<committed>]"
    category_patterns = {
        "salary": (r"Salaries \& Wages\s+([\d,.()-]+)\s+([\d,.()-]+)(?:\s+([\d,.()-]+))?", 1, 2, 3),
        "fringe": (r"Fringe Benefits\s+([\d,.()-]+)\s+([\d,.()-]+)(?:\s+([\d,.()-]+))?", 1, 2, 3),
        "tuition": (r"Tuition \& Fees\s+([\d,.()-]+)\s+([\d,.()-]+)(?:\s+([\d,.()-]+))?", 1, 2, 3),
        "insurance": (
            r"(?:Student Health Insurance|Total Student Health)\s+([\d,.()-]+)\s+([\d,.()-]+)(?:\s+([\d,.()-]+))?",
            1,
            2,
            3,
        ),
        "service_center": (
            r"(?:Service Center|Total Service Center)\s+([\d,.()-]+)\s+([\d,.()-]+)(?:\s+([\d,.()-]+))?",
            1,
            2,
            3,
        ),
        "travel": (r"Travel Domestic\s+([\d,.()-]+)\s+([\d,.()-]+)(?:\s+([\d,.()-]+))?", 1, 2, 3),
        "travel_foreign": (
            r"Travel Foreign\s+([\d,.()-]+)\s+([\d,.()-]+)(?:\s+([\d,.()-]+))?",
            1,
            2,
            3,
        ),
        "supplies": (
            r"(?:Supplies \& Materials|Materials \& Supplies|Supplies)\s+([\d,.()-]+)\s+([\d,.()-]+)(?:\s+([\d,.()-]+))?",
            1,
            2,
            3,
        ),
        "equipment": (
            r"(?:Capital Equipment|Equipment)\s+([\d,.()-]+)\s+([\d,.()-]+)(?:\s+([\d,.()-]+))?",
            1,
            2,
            3,
        ),
        "subcontracts": (
            r"(?:Subcontracts|Subawards)\s+([\d,.()-]+)\s+([\d,.()-]+)(?:\s+([\d,.()-]+))?",
            1,
            2,
            3,
        ),
        "consultant": (
            r"(?:Consultant Services|Consultants)\s+([\d,.()-]+)\s+([\d,.()-]+)(?:\s+([\d,.()-]+))?",
            1,
            2,
            3,
        ),
        "other": (r"Other Expenses\s+([\d,.()-]+)\s+([\d,.()-]+)(?:\s+([\d,.()-]+))?", 1, 2, 3),
    }

    for key, (pattern, month_group, spent_group, committed_group) in category_patterns.items():
        match = re.search(pattern, text)
        if match:
            result[f"{key}_month"] = clean_text_to_decimal(match.group(month_group))
            result[f"{key}_spent"] = clean_text_to_decimal(match.group(spent_group))
            if committed_group and match.group(committed_group):
                result[f"{key}_committed"] = clean_text_to_decimal(match.group(committed_group))

    return result


def parse_personnel_page(
    page, report_period: str = "Unknown", report_project_id: str = "unknown"
) -> list[EffortAllocation]:
    """
    Parse a salary report page to extract personnel effort allocations,
    including G/L accounts, wage types, and pay-period dates.

    Args:
        page: pdfplumber page object
        report_period: Period string from report summary (e.g., "November 2025")
        report_project_id: Grant number from report summary

    Returns list of EffortAllocation objects.
    """
    text = page.extract_text() or ""
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

    period = f"{date_match.group(1)} {date_match.group(2)}" if date_match else report_period

    lines = text.split("\n")
    current_gl_account = None
    current_wage_type = None
    current_emp_type = EmployeeType.UNKNOWN

    # Store transaction details preceding "Total for" lines
    pending_details: dict[str, list[dict]] = {}

    for line in lines:
        line_clean = line.strip()
        if not line_clean:
            continue

        # Check for G/L account header
        gl_match = re.search(r"(?:^|\b)G/L\s*(\d{6})\s*[-:]?\s*(.+)", line_clean, re.IGNORECASE)
        if not gl_match:
            gl_match = re.search(r"^(\d{6})\s*[-:]\s*(.+)", line_clean)
        if gl_match:
            current_gl_account = gl_match.group(1)
            current_wage_type = gl_match.group(2).strip()
            current_emp_type = parse_employee_type(current_wage_type)

        # Check for detail / transaction line with date range
        tx_match = re.search(
            r"^([A-Za-z\s,\.-]+?)\s+(?:Doc\s+\d+\s+)?(\d{1,2}/\d{1,2}/\d{2,4}|\d{1,2}/\d{4})\s+(?:to\s+|-)?\s*(\d{1,2}/\d{1,2}/\d{2,4}|\d{1,2}/\d{4})\s+([\d,]+\.\d{2})",
            line_clean,
        )
        if tx_match and not line_clean.startswith("Total for"):
            pname = tx_match.group(1).strip()
            if (
                not pname.startswith("Ref.")
                and not pname.startswith("Doc")
                and not pname.startswith("G/L")
            ):
                s_dt = _parse_date_flexible(tx_match.group(2))
                e_dt = _parse_date_flexible(tx_match.group(3))
                amt = clean_text_to_decimal(tx_match.group(4))
                pending_details.setdefault(pname, []).append(
                    {
                        "start": s_dt,
                        "end": e_dt,
                        "amount": amt,
                        "gl": current_gl_account,
                        "wage_type": current_wage_type,
                        "emp_type": current_emp_type,
                    }
                )

        # Look for person totals: "Total for Name AMOUNT"
        total_match = re.search(r"Total for (.*?)\s+([\d,]+\.\d{2})", line_clean)
        if total_match:
            name = total_match.group(1).strip()

            # Skip non-person entries
            if name.startswith("Ref.") or name.startswith("Doc") or re.match(r"^[\d#\s]+$", name):
                continue

            salary = clean_text_to_decimal(total_match.group(2))
            if salary:
                emp_type = current_emp_type
                gl_acc = current_gl_account
                wage_tp = current_wage_type
                pay_start = None
                pay_end = None

                # Find any transaction details for this person
                matching_txs = pending_details.get(name) or []
                if not matching_txs:
                    for k, v in pending_details.items():
                        if name.split(",")[0].lower() in k.lower():
                            matching_txs = v
                            break

                if matching_txs:
                    starts = [t["start"] for t in matching_txs if t["start"]]
                    ends = [t["end"] for t in matching_txs if t["end"]]
                    if starts:
                        pay_start = min(starts)
                    if ends:
                        pay_end = max(ends)
                    if matching_txs[-1].get("gl"):
                        gl_acc = matching_txs[-1]["gl"]
                    if matching_txs[-1].get("wage_type"):
                        wage_tp = matching_txs[-1]["wage_type"]
                    if matching_txs[-1].get("emp_type") != EmployeeType.UNKNOWN:
                        emp_type = matching_txs[-1]["emp_type"]

                # Fallback backward search if employee type is still unknown
                if emp_type == EmployeeType.UNKNOWN:
                    for prev_line in lines[: lines.index(line)][::-1]:
                        if name.split(",")[0] in prev_line:
                            if "FACULTY" in prev_line:
                                emp_type = EmployeeType.FACULTY
                            elif "POSTDOC" in prev_line:
                                emp_type = EmployeeType.POSTDOC
                            elif "STUDENT GRAD" in prev_line or "STU POSTDOC" in prev_line:
                                emp_type = EmployeeType.GRAD_STUDENT
                            elif "MASTERS" in prev_line:
                                emp_type = EmployeeType.MASTERS_STUDENT
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
                        gl_account=gl_acc,
                        wage_type=wage_tp,
                        pay_period_start=pay_start,
                        pay_period_end=pay_end,
                    )
                )

    return allocations


def parse_commitment_page(
    page, report_period: str = "Unknown", report_project_id: str = "unknown"
) -> list[CommitmentDetail]:
    """
    Parse a Salary Commitment / Encumbrance page to extract individual commitment details.

    Args:
        page: pdfplumber page object
        report_period: Fallback period
        report_project_id: Fallback project ID

    Returns list of CommitmentDetail objects.
    """
    text = page.extract_text() or ""
    commitments = []

    # Check if this is a commitment page
    is_commitment_page = (
        "Salary Commitment" in text
        or "Commitment Report" in text
        or "Salary Encumbrance" in text
        or ("Encumbrance" in text and "Salary" in text)
    )
    if not is_commitment_page:
        return []

    lines = text.split("\n")
    current_emp_type = EmployeeType.UNKNOWN

    for line in lines:
        line_clean = line.strip()
        if not line_clean:
            continue

        # Check for G/L account header to determine employee type
        gl_match = re.search(r"(?:^|\b)G/L\s*(\d{6})\s*[-:]?\s*(.+)", line_clean, re.IGNORECASE)
        if not gl_match:
            gl_match = re.search(r"^(\d{6})\s*[-:]\s*(.+)", line_clean)
        if gl_match:
            current_emp_type = parse_employee_type(gl_match.group(2))

        # Format 1: "Name [Doc] Start End Salary [Fringe] [IDC]"
        row_match = re.search(
            r"^([A-Za-z\s,\.-]+?)\s+(?:Doc\s+\d+\s+)?(\d{1,2}/\d{1,2}/\d{2,4})\s+(?:to\s+|-)?\s*(\d{1,2}/\d{1,2}/\d{2,4})\s+([\d,]+\.\d{2})(?:\s+([\d,]+\.\d{2}))?(?:\s+([\d,]+\.\d{2}))?",
            line_clean,
        )
        if row_match and not line_clean.startswith("Total") and not line_clean.startswith("Grand"):
            pname = row_match.group(1).strip()
            if (
                not pname.startswith("Ref.")
                and not pname.startswith("Doc")
                and not pname.startswith("G/L")
            ):
                s_dt = _parse_date_flexible(row_match.group(2))
                e_dt = _parse_date_flexible(row_match.group(3))
                sal_comm = clean_text_to_decimal(row_match.group(4)) or Decimal("0")
                fr_comm = clean_text_to_decimal(row_match.group(5)) or Decimal("0")
                idc_comm = clean_text_to_decimal(row_match.group(6)) or Decimal("0")

                commitments.append(
                    CommitmentDetail(
                        person_name=pname,
                        employee_type=current_emp_type,
                        salary_committed=sal_comm,
                        fringe_committed=fr_comm,
                        idc_committed=idc_comm,
                        encumbrance_start=s_dt,
                        encumbrance_end=e_dt,
                    )
                )
            continue

        # Format 2: "Total for Name Salary Fringe IDC" or "Total for Name Salary"
        total_match = re.search(
            r"Total for\s+([A-Za-z\s,\.-]+?)\s+([\d,]+\.\d{2})(?:\s+([\d,]+\.\d{2}))?(?:\s+([\d,]+\.\d{2}))?",
            line_clean,
        )
        if total_match:
            pname = total_match.group(1).strip()
            sal_comm = clean_text_to_decimal(total_match.group(2)) or Decimal("0")
            fr_comm = clean_text_to_decimal(total_match.group(3)) or Decimal("0")
            idc_comm = clean_text_to_decimal(total_match.group(4)) or Decimal("0")

            # If not already recorded in commitments for this person
            if not any(c.person_name == pname for c in commitments):
                commitments.append(
                    CommitmentDetail(
                        person_name=pname,
                        employee_type=current_emp_type,
                        salary_committed=sal_comm,
                        fringe_committed=fr_comm,
                        idc_committed=idc_comm,
                    )
                )

    return commitments


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
    all_commitments = []

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
                    total_month=summary.get("total_month"),
                    # Category breakdowns (cumulative)
                    salary_spent=summary.get("salary_spent", Decimal("0")) or Decimal("0"),
                    fringe_spent=summary.get("fringe_spent", Decimal("0")) or Decimal("0"),
                    tuition_spent=summary.get("tuition_spent", Decimal("0")) or Decimal("0"),
                    insurance_spent=summary.get("insurance_spent", Decimal("0")) or Decimal("0"),
                    service_center_spent=summary.get("service_center_spent", Decimal("0"))
                    or Decimal("0"),
                    travel_spent=summary.get("travel_spent", Decimal("0")) or Decimal("0"),
                    travel_foreign_spent=summary.get("travel_foreign_spent", Decimal("0"))
                    or Decimal("0"),
                    supplies_spent=summary.get("supplies_spent", Decimal("0")) or Decimal("0"),
                    equipment_spent=summary.get("equipment_spent", Decimal("0")) or Decimal("0"),
                    subcontracts_spent=summary.get("subcontracts_spent", Decimal("0"))
                    or Decimal("0"),
                    consultant_spent=summary.get("consultant_spent", Decimal("0")) or Decimal("0"),
                    other_spent=summary.get("other_spent", Decimal("0")) or Decimal("0"),
                    # Monthly (single-month) category amounts
                    salary_month=summary.get("salary_month"),
                    fringe_month=summary.get("fringe_month"),
                    tuition_month=summary.get("tuition_month"),
                    insurance_month=summary.get("insurance_month"),
                    service_center_month=summary.get("service_center_month"),
                    travel_month=summary.get("travel_month"),
                    travel_foreign_month=summary.get("travel_foreign_month"),
                    supplies_month=summary.get("supplies_month"),
                    equipment_month=summary.get("equipment_month"),
                    subcontracts_month=summary.get("subcontracts_month"),
                    consultant_month=summary.get("consultant_month"),
                    other_month=summary.get("other_month"),
                    indirect_month=summary.get("indirect_month"),
                    # Category commitments
                    salary_committed=summary.get("salary_committed", Decimal("0")) or Decimal("0"),
                    fringe_committed=summary.get("fringe_committed", Decimal("0")) or Decimal("0"),
                    tuition_committed=summary.get("tuition_committed", Decimal("0"))
                    or Decimal("0"),
                    insurance_committed=summary.get("insurance_committed", Decimal("0"))
                    or Decimal("0"),
                    service_center_committed=summary.get("service_center_committed", Decimal("0"))
                    or Decimal("0"),
                    travel_committed=summary.get("travel_committed", Decimal("0")) or Decimal("0"),
                    travel_foreign_committed=summary.get("travel_foreign_committed", Decimal("0"))
                    or Decimal("0"),
                    supplies_committed=summary.get("supplies_committed", Decimal("0"))
                    or Decimal("0"),
                    equipment_committed=summary.get("equipment_committed", Decimal("0"))
                    or Decimal("0"),
                    subcontracts_committed=summary.get("subcontracts_committed", Decimal("0"))
                    or Decimal("0"),
                    consultant_committed=summary.get("consultant_committed", Decimal("0"))
                    or Decimal("0"),
                    other_committed=summary.get("other_committed", Decimal("0")) or Decimal("0"),
                    # Funded ceiling and revenue
                    funded_ceiling=summary.get("funded_ceiling"),
                    total_revenue_received=summary.get("total_revenue_received"),
                    revenue_month=summary.get("revenue_month"),
                    # Award metadata
                    budget_start_date=summary.get("budget_start_date"),
                    budget_end_date=summary.get("budget_end_date"),
                    grant_end_date=summary.get("grant_end_date"),
                    grantor_code=summary.get("grantor_code"),
                    stated_idc_rate=summary.get("stated_idc_rate"),
                )

            # All pages: Personnel & Commitments
            report_period = summary.get("period", "Unknown")
            report_project_id = summary.get("grant_number", "unknown")
            for page in pdf.pages:
                personnel = parse_personnel_page(page, report_period, report_project_id)
                all_personnel.extend(personnel)

                commitments = parse_commitment_page(page, report_period, report_project_id)
                all_commitments.extend(commitments)

            if spending_report and all_commitments:
                spending_report.commitment_details = all_commitments

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
