"""
Sponsored PDF report parsing.

Extracts spending data and personnel costs from JHU sponsored project reports.

The summary page holds two right-aligned numeric tables (Revenue and
Expenditures) whose blank cells are simply absent from the extracted text.
Counting tokens therefore mis-assigns columns on any row with a blank cell --
for example a category with no charge in the current month -- so the tables are
read positionally instead: every numeric token is matched to the header column
whose right edge it aligns with. Pages without word geometry (synthetic
fixtures, damaged PDFs) fall back to regex extraction.
"""

import re
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path

import pdfplumber

from .models import (
    CommitmentDetail,
    EffortAllocation,
    EmployeeType,
    SpendingReport,
)

MONTH_NAMES = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)

# A numeric table cell: 1,234.56 / (1,234.56) / 12.3% / 100%
_NUMERIC_CELL = re.compile(r"^\(?-?[\d,]+\.\d{1,2}\)?%?$|^\(?-?[\d,]+\)?%$")

# Summary-page category rows -> SpendingReport field prefixes
CATEGORY_LABELS = {
    "salaries & wages": "salary",
    "salaries and wages": "salary",
    "fringe benefits": "fringe",
    "tuition & fees": "tuition",
    "tuition and fees": "tuition",
    "student health insurance": "insurance",
    "total student health insurance": "insurance",
    "service center": "service_center",
    "total service center": "service_center",
    "travel domestic": "travel",
    "travel foreign": "travel_foreign",
    "supplies & materials": "supplies",
    "materials & supplies": "supplies",
    "supplies": "supplies",
    "capital equipment": "equipment",
    "equipment": "equipment",
    "subcontracts": "subcontracts",
    "subawards": "subcontracts",
    "consultant services": "consultant",
    "consultants": "consultant",
    "other expenses": "other",
}

# Summary-page total rows
TOTAL_LABELS = {
    "total direct costs": "direct",
    "total indirect costs": "indirect",
    "total expenditures": "total",
    "undistributed budget": "undistributed",
}


def clean_text_to_decimal(text: str | None) -> Decimal | None:
    """
    Converts a currency string (e.g., "1,325.88" or "(9,034.52)") to a Decimal.
    Returns None if text is empty or invalid.
    """
    if not text or not str(text).strip():
        return None

    # Remove commas, percent signs, and map parentheses to a leading minus
    cleaned_text = (
        str(text).strip().replace(",", "").replace("(", "-").replace(")", "").replace("%", "")
    )

    if not cleaned_text:
        return None

    try:
        return Decimal(cleaned_text)
    except InvalidOperation:
        return None


def _parse_date_flexible(val: str | None) -> date | None:
    """Parse MM/DD/YYYY, MM/DD/YY, MM/YYYY, YYYY-MM-DD, YYYY-MM, or Month-YYYY."""
    if not val or not str(val).strip():
        return None
    val_str = str(val).strip()
    for fmt in ("%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d", "%m/%Y", "%Y-%m", "%B-%Y", "%b-%Y"):
        try:
            return datetime.strptime(val_str, fmt).date()
        except ValueError:
            pass
    return None


def month_end(d: date) -> date:
    """Last calendar day of the month containing ``d``."""
    if d.month == 12:
        return date(d.year, 12, 31)
    return date(d.year, d.month + 1, 1) - timedelta(days=1)


def parse_employee_type(gl_account: str) -> EmployeeType:
    """Determine employee type from a G/L account label (e.g. "SAL-FACULTY FT/PT")."""
    if not gl_account:
        return EmployeeType.UNKNOWN
    gl_lower = gl_account.lower()

    # Student accounts are matched before the faculty/staff keywords, so that
    # "SAL-STUDENT GRADUATE" is not swallowed by a broader rule. Note that
    # "SALARY-STU POSTDOCTORAL" is a postdoc account and falls through below.
    if re.search(r"stu(dent)?\s+(grad|graduate)", gl_lower) or "grad student" in gl_lower:
        return EmployeeType.GRAD_STUDENT
    if "masters" in gl_lower or re.search(r"stu(dent)?\s+mast", gl_lower):
        return EmployeeType.MASTERS_STUDENT
    if "postdoc" in gl_lower:
        return EmployeeType.POSTDOC
    # "SAL-FACULTY FT/PT", "SALARY-FACULTY FT/PT", and the abbreviated "SAL-FAC TLC"
    if "faculty" in gl_lower or re.search(r"\bfac\b", gl_lower):
        return EmployeeType.FACULTY
    if "staff" in gl_lower or "nadm" in gl_lower or "casual" in gl_lower:
        return EmployeeType.STAFF
    if "student" in gl_lower:
        return EmployeeType.GRAD_STUDENT
    return EmployeeType.UNKNOWN


# ----------------------------------------------------------------------
# Positional table extraction
# ----------------------------------------------------------------------


def _cluster_rows(words: list[dict], tol: float = 4.0) -> list[list[dict]]:
    """Group extracted words into visual rows by their vertical position."""
    rows: list[tuple[float, list[dict]]] = []
    for word in sorted(words, key=lambda w: (w["top"], w["x0"])):
        for top, bucket in rows:
            if abs(top - word["top"]) < tol:
                bucket.append(word)
                break
        else:
            rows.append((word["top"], [word]))
    return [sorted(bucket, key=lambda w: w["x0"]) for _, bucket in rows]


def _split_header_columns(row: list[dict], gap: float = 6.0) -> list[dict]:
    """
    Split a header row into columns.

    Words inside one header phrase sit ~2-3pt apart; separate columns are
    separated by 10pt or more, so a 6pt gap is an unambiguous divider.
    """
    columns: list[dict] = []
    for word in row:
        if columns and word["x0"] - columns[-1]["x1"] < gap:
            columns[-1]["text"] += " " + word["text"]
            columns[-1]["x1"] = word["x1"]
        else:
            columns.append({"text": word["text"], "x0": word["x0"], "x1": word["x1"]})
    return columns


def _canonical_column(label: str, period_month: str | None) -> str | None:
    """Map a header column label to a canonical key."""
    norm = re.sub(r"\s+", " ", label.strip().lower())
    if period_month and norm == period_month.lower():
        return "month"
    # Any "<Month> <Year>" header is the single-month column.
    if re.match(r"^(" + "|".join(m.lower() for m in MONTH_NAMES) + r")\s+\d{4}$", norm):
        return "month"
    return {
        "budget": "budget",
        "total spent": "spent",
        "total committed": "committed",
        "total spent & committed": "spent_and_committed",
        "total received": "received",
        "total expected": "expected",
        "total rcvd. & expected": "rcvd_and_expected",
        "total rcvd & expected": "rcvd_and_expected",
        "budget balance": "balance",
        "budget utilized": "utilized",
        "budget received": "pct_received",
    }.get(norm)


def _assign_cells(row: list[dict], columns: list[tuple[str, float]]) -> tuple[str, dict]:
    """
    Split a data row into its label and its numeric cells.

    Columns are right-aligned, so each numeric token is assigned to the column
    with the nearest right edge. Tokens further than ``max_dist`` from every
    column are dropped rather than guessed at.
    """
    max_dist = 30.0
    label_parts: list[str] = []
    cells: dict[str, Decimal] = {}

    for word in row:
        text = word["text"]
        if _NUMERIC_CELL.match(text):
            best_key = None
            best_dist = max_dist
            for key, right_edge in columns:
                dist = abs(word["x1"] - right_edge)
                if dist < best_dist:
                    best_dist = dist
                    best_key = key
            if best_key is not None and best_key not in cells:
                value = clean_text_to_decimal(text)
                if value is not None:
                    cells[best_key] = value
        else:
            label_parts.append(text)

    return re.sub(r"\s+", " ", " ".join(label_parts)).strip(), cells


def _extract_summary_tables(page, period_month: str | None) -> dict:
    """
    Read the Revenue and Expenditures tables from the summary page positionally.

    Returns a dict of parsed fields, or an empty dict when the page exposes no
    usable word geometry.
    """
    try:
        words = page.extract_words()
    except Exception:
        return {}
    if not words or not isinstance(words, list):
        return {}
    try:
        rows = _cluster_rows([w for w in words if "x0" in w and "top" in w])
    except (TypeError, KeyError):
        return {}

    result: dict = {}
    table: str | None = None
    columns: list[tuple[str, float]] = []

    for row in rows:
        row_text = re.sub(r"\s+", " ", " ".join(w["text"] for w in row)).strip()
        lowered = row_text.lower()

        if lowered.startswith("report for grant"):
            table = None
            continue

        # Header rows start a new table and define its column geometry.
        if re.match(r"^revenue\s+budget\b", lowered) or re.match(
            r"^expenditures\s+budget\b", lowered
        ):
            table = "revenue" if lowered.startswith("revenue") else "expenditures"
            columns = []
            for col in _split_header_columns(row)[1:]:  # skip the row-label header
                key = _canonical_column(col["text"], period_month)
                if key:
                    columns.append((key, col["x1"]))
            continue

        if table is None or not columns:
            continue

        label, cells = _assign_cells(row, columns)
        if not label or not cells:
            continue
        norm_label = label.lower()

        if table == "revenue":
            if norm_label in ("sponsored revenue", "total revenue"):
                # The Revenue "Budget" column is the funded ceiling: the amount
                # the sponsor has actually obligated, which is what a stop-work
                # forecast must be measured against.
                if "budget" in cells:
                    result["funded_ceiling"] = cells["budget"]
                if "received" in cells:
                    result["total_revenue_received"] = cells["received"]
                if "month" in cells:
                    result["revenue_month"] = cells["month"]
            continue

        # Expenditures table
        if norm_label in TOTAL_LABELS:
            kind = TOTAL_LABELS[norm_label]
            if kind == "total":
                result["total_month"] = cells.get("month")
                result["total_spent"] = cells.get("spent")
                result["total_committed"] = cells.get("committed")
                result["total_spent_and_committed"] = cells.get("spent_and_committed")
                if "budget" in cells:
                    result["expenditure_budget"] = cells["budget"]
                if "utilized" in cells:
                    result["budget_utilized_pct"] = cells["utilized"]
            elif kind == "indirect":
                result["indirect_month"] = cells.get("month")
                result["indirect_spent"] = cells.get("spent")
                result["indirect_committed"] = cells.get("committed")
            elif kind == "direct":
                result["direct_month"] = cells.get("month")
                result["direct_spent"] = cells.get("spent")
                result["direct_committed"] = cells.get("committed")
            continue

        prefix = CATEGORY_LABELS.get(norm_label)
        if prefix:
            for cell_key, suffix in (
                ("month", "month"),
                ("spent", "spent"),
                ("committed", "committed"),
            ):
                if cell_key in cells:
                    result[f"{prefix}_{suffix}"] = cells[cell_key]

    return result


# ----------------------------------------------------------------------
# Summary page
# ----------------------------------------------------------------------


def parse_sponsored_summary(page) -> dict:
    """
    Parse the first page of a sponsored report to extract summary costs and metadata.

    Returns dict with summary amounts, categories, dates, revenue, and ceiling.
    """
    text = page.extract_text() or ""
    result: dict = {}

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

    # Report period: the bare "<Month> <Year>" line in the page header
    period_match = re.search(
        r"^\s*(" + "|".join(MONTH_NAMES) + r")\s+(\d{4})\b", text, re.MULTILINE
    )
    if not period_match:
        period_match = re.search(
            r"Expenditures Budget\s+(" + "|".join(MONTH_NAMES) + r")\s+(\d{4})", text
        )
    if period_match:
        month_name, year = period_match.group(1), period_match.group(2)
        result["period"] = f"{month_name} {year}"
        result["year"] = int(year)
        result["month"] = MONTH_NAMES.index(month_name) + 1

    # Award metadata
    begin_match = re.search(
        r"Budget Begin(?: Date)?:?\s*(\d{1,2}/\d{1,2}/\d{2,4}|\d{4}-\d{2}-\d{2})",
        text,
        re.IGNORECASE,
    )
    if begin_match:
        result["budget_start_date"] = _parse_date_flexible(begin_match.group(1))
    else:
        span_match = re.search(
            r"Budget Period:?\s*(\d{1,2}/\d{1,2}/\d{2,4})\s+to\s+(\d{1,2}/\d{1,2}/\d{2,4})",
            text,
            re.IGNORECASE,
        )
        if span_match:
            result["budget_start_date"] = _parse_date_flexible(span_match.group(1))
            result["budget_end_date"] = _parse_date_flexible(span_match.group(2))

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

    proj_start_match = re.search(
        r"Grant Project Start Date:?\s*(\d{1,2}/\d{1,2}/\d{2,4}|\d{4}-\d{2}-\d{2})",
        text,
        re.IGNORECASE,
    )
    if proj_start_match and "budget_start_date" not in result:
        result["budget_start_date"] = _parse_date_flexible(proj_start_match.group(1))

    # The grantor name shares its line with the next labelled field, and is a
    # multi-word name -- so take the rest of the line and then trim the trailing
    # label rather than stopping at the first token.
    grantor_match = re.search(r"Grantor(?:\s+Code)?:\s*(.+)$", text, re.MULTILINE)
    if grantor_match:
        grantor = re.split(
            r"\s*(?:Budget Begin|Budget End|Grant Project|Award ID|Payment Method|Grant Status"
            r"|Responsible Cost|Program FA|PI on Grant|Sp\. Program)\b",
            grantor_match.group(1),
        )[0].strip()
        # Some layouts run the next label straight onto the value with no space
        grantor = re.sub(r"(?:Budget|Grant|Award|Payment|Program)\s*$", "", grantor).strip(" :")
        if grantor:
            result["grantor_code"] = grantor

    # F&A rate is printed without a percent sign ("F&A Rate: 55.50")
    fa_match = re.search(
        r"(?:F\s*&\s*A|IDC|Indirect Cost)\s*Rate:?\s*([\d.]+)\s*%?",
        text,
        re.IGNORECASE,
    )
    if fa_match:
        result["stated_idc_rate"] = clean_text_to_decimal(fa_match.group(1))

    # Budget utilization percentage
    util_match = re.search(r"Budget Utilized:\s+([\d.]+)%", text)
    if util_match:
        result["budget_utilized_pct"] = Decimal(util_match.group(1))

    # ---- Positional extraction of the two numeric tables ---------------
    positional = _extract_summary_tables(page, result.get("period"))
    if positional:
        result.update({k: v for k, v in positional.items() if v is not None})
        # A blank cell means zero, not "same as the neighbouring column".
        for prefix in set(CATEGORY_LABELS.values()):
            for suffix in ("month", "spent", "committed"):
                result.setdefault(f"{prefix}_{suffix}", Decimal("0"))
        return result

    # ---- Regex fallback ------------------------------------------------
    # Reached only for pages without word geometry. Column blanks are
    # indistinguishable here, so values may be shifted on sparse rows.
    exp_match = re.search(
        r"Total Expenditures\s+(?:[\d,.()-]+\s+)?([\d,.-]+)\s+([\d,.-]+)\s+([\d,.-]+)\s+([\d,.-]+)",
        text,
    )
    if exp_match:
        result["total_month"] = clean_text_to_decimal(exp_match.group(1))
        result["total_spent"] = clean_text_to_decimal(exp_match.group(2))
        result["total_committed"] = clean_text_to_decimal(exp_match.group(3))
        result["total_spent_and_committed"] = clean_text_to_decimal(exp_match.group(4))

    indirect_match = re.search(
        r"Total Indirect Costs\s+(?:[\d,.()-]+\s+)?([\d,.-]+)\s+([\d,.-]+)(?:\s+[\d,.-]+)?\s+([\d,.-]+)",
        text,
    )
    if indirect_match:
        result["indirect_month"] = clean_text_to_decimal(indirect_match.group(1))
        result["indirect_spent"] = clean_text_to_decimal(indirect_match.group(2))

    rev_match = re.search(r"Sponsored Revenue\s+([\d,]+\.\d{2})(?:\s+([\d,]+\.\d{2}))?", text)
    if rev_match:
        result["funded_ceiling"] = clean_text_to_decimal(rev_match.group(1))
        if rev_match.group(2):
            result["revenue_month"] = clean_text_to_decimal(rev_match.group(2))

    for key, pattern in (
        ("salary", r"Salaries \& Wages\s+([\d,.()-]+)\s+([\d,.()-]+)(?:\s+([\d,.()-]+))?"),
        ("fringe", r"Fringe Benefits\s+([\d,.()-]+)\s+([\d,.()-]+)(?:\s+([\d,.()-]+))?"),
        ("tuition", r"Tuition \& Fees\s+([\d,.()-]+)\s+([\d,.()-]+)(?:\s+([\d,.()-]+))?"),
        (
            "insurance",
            r"Student Health Insurance\s+([\d,.()-]+)\s+([\d,.()-]+)(?:\s+([\d,.()-]+))?",
        ),
        ("service_center", r"Service Center\s+([\d,.()-]+)\s+([\d,.()-]+)(?:\s+([\d,.()-]+))?"),
        ("travel", r"Travel Domestic\s+([\d,.()-]+)\s+([\d,.()-]+)(?:\s+([\d,.()-]+))?"),
        ("travel_foreign", r"Travel Foreign\s+([\d,.()-]+)\s+([\d,.()-]+)(?:\s+([\d,.()-]+))?"),
        ("supplies", r"Supplies \& Materials\s+([\d,.()-]+)\s+([\d,.()-]+)(?:\s+([\d,.()-]+))?"),
        ("equipment", r"Capital Equipment\s+([\d,.()-]+)\s+([\d,.()-]+)(?:\s+([\d,.()-]+))?"),
        ("subcontracts", r"Subcontracts\s+([\d,.()-]+)\s+([\d,.()-]+)(?:\s+([\d,.()-]+))?"),
        ("consultant", r"Consultant Services\s+([\d,.()-]+)\s+([\d,.()-]+)(?:\s+([\d,.()-]+))?"),
        ("other", r"Other Expenses\s+([\d,.()-]+)\s+([\d,.()-]+)(?:\s+([\d,.()-]+))?"),
    ):
        match = re.search(pattern, text)
        if match:
            result[f"{key}_month"] = clean_text_to_decimal(match.group(1))
            result[f"{key}_spent"] = clean_text_to_decimal(match.group(2))
            if match.group(3):
                result[f"{key}_committed"] = clean_text_to_decimal(match.group(3))

    tot_rec_match = re.search(r"Total Received:?\s*([\d,]+\.\d{2})", text, re.IGNORECASE)
    if tot_rec_match:
        result["total_revenue_received"] = clean_text_to_decimal(tot_rec_match.group(1))

    return result


# ----------------------------------------------------------------------
# Salary pages
# ----------------------------------------------------------------------

# Rows look like:
#   "Smith, Jane SAL-FACULTY FT/PT 03/15/2026 Salary 1,974.75"
#   "Roe, Richard SAL-FAC TLC 01/15/2026 PtInstSl 365.21"
_SALARY_ROW = re.compile(
    r"^(?P<left>.+?)\s+(?P<date>\d{1,2}/\d{1,2}/\d{2,4})\s+(?P<rest>.+?)\s+"
    r"(?P<amount>\(?[\d,]+\.\d{2}\)?)$"
)

# G/L labels are printed in upper case; employee names are not.
_GL_TOKEN = re.compile(r"^(?:SAL|SALARY|WAGE|WAGES|GL)[-A-Z0-9]*$")


def _split_name_and_gl(left: str) -> tuple[str, str | None]:
    """
    Split "Doe, Mary Elizabeth SAL-FACULTY FT/PT" into name and G/L label.

    Prefers an explicit SAL-/SALARY- token; otherwise peels off the trailing run
    of tokens that contain no lower-case letters.
    """
    tokens = left.split()
    if not tokens:
        return left.strip(), None

    for idx, token in enumerate(tokens):
        if _GL_TOKEN.match(token) and idx > 0:
            return " ".join(tokens[:idx]).strip(), " ".join(tokens[idx:]).strip()

    split_at = len(tokens)
    while split_at > 1 and not re.search(r"[a-z]", tokens[split_at - 1]):
        split_at -= 1
    if split_at < len(tokens):
        return " ".join(tokens[:split_at]).strip(), " ".join(tokens[split_at:]).strip()
    return left.strip(), None


def _is_person_name(name: str) -> bool:
    """Reject table furniture that the row patterns can otherwise match."""
    if not name or len(name) < 2:
        return False
    lowered = name.lower()
    if lowered.startswith(("ref.", "doc", "g/l", "total", "grand", "employee", "report for")):
        return False
    return not re.match(r"^[\d#\s.,-]+$", name)


def _collect_salary_rows(text: str) -> tuple[dict[str, list[dict]], list[str], dict[str, Decimal]]:
    """
    Read the detail and "Total for" rows out of one salary page.

    Returns (details_by_name, names_in_page_order, totals_by_name). Callers
    assemble across pages, because a single person's rows can straddle a page
    break with the "Total for" line landing on the following page.
    """
    details: dict[str, list[dict]] = {}
    ordered: list[str] = []
    totals: dict[str, Decimal] = {}

    for raw_line in text.split("\n"):
        line = raw_line.strip()
        if not line or line.startswith("Report for"):
            continue

        total_match = re.match(r"^Total for\s+(.+?)\s+(\(?[\d,]+\.\d{2}\)?)$", line)
        if total_match:
            name = total_match.group(1).strip()
            amount = clean_text_to_decimal(total_match.group(2))
            if _is_person_name(name) and amount is not None:
                totals[name] = amount
                if name not in ordered:
                    ordered.append(name)
            continue

        row_match = _SALARY_ROW.match(line)
        if not row_match:
            continue
        name, gl_account = _split_name_and_gl(row_match.group("left"))
        if not _is_person_name(name):
            continue

        if name not in details:
            details[name] = []
            if name not in ordered:
                ordered.append(name)
        details[name].append(
            {
                "date": _parse_date_flexible(row_match.group("date")),
                "gl": gl_account,
                "wage": row_match.group("rest").strip() or None,
                "amount": clean_text_to_decimal(row_match.group("amount")),
            }
        )

    return details, ordered, totals


def _assemble_allocations(
    details: dict[str, list[dict]],
    ordered: list[str],
    totals: dict[str, Decimal],
    project_id: str,
    period: str,
) -> list[EffortAllocation]:
    """Turn collected salary rows into one EffortAllocation per person."""
    allocations: list[EffortAllocation] = []

    for name in ordered:
        rows = details.get(name, [])
        if not rows:
            # A "Total for" line whose detail rows were abbreviated on the page
            for known, known_rows in details.items():
                if known != name and (known.startswith(name) or name.startswith(known)):
                    rows = known_rows
                    break

        if name in totals:
            salary = totals[name]
        else:
            amounts = [r["amount"] for r in rows if r["amount"] is not None]
            if not amounts:
                continue
            salary = sum(amounts, Decimal("0"))

        dates = [r["date"] for r in rows if r["date"]]
        gl_account = next((r["gl"] for r in reversed(rows) if r["gl"]), None)
        wage_type = next((r["wage"] for r in reversed(rows) if r["wage"]), None)

        allocations.append(
            EffortAllocation(
                person_name=name,
                project_id=project_id,
                period=period,
                salary_amount=salary,
                employee_type=parse_employee_type(gl_account or ""),
                gl_account=gl_account,
                wage_type=wage_type,
                pay_period_start=min(dates) if dates else None,
                pay_period_end=max(dates) if dates else None,
            )
        )

    return allocations


def _salary_page_context(text: str, report_period: str, report_project_id: str) -> tuple[str, str]:
    """Grant number and period for a salary page, falling back to report-level values."""
    grant_match = re.search(r"Grant:\s+(\d+)", text)
    project_id = grant_match.group(1) if grant_match else report_project_id

    period = report_period
    header_match = re.search(
        r"^\s*(" + "|".join(MONTH_NAMES) + r")\s+(\d{4})\s*$", text, re.MULTILINE
    )
    if header_match:
        period = f"{header_match.group(1)} {header_match.group(2)}"
    return project_id, period


def _is_salary_page(text: str) -> bool:
    """A Sponsored PI Salary Report page (or a continuation of one)."""
    if "Salary Commitment" in text:
        return False
    return "Salary Report" in text or "Total for" in text


def parse_personnel_page(
    page, report_period: str = "Unknown", report_project_id: str = "unknown"
) -> list[EffortAllocation]:
    """
    Parse a Sponsored PI Salary Report page into per-person effort allocations.

    Detail rows carry the G/L account, wage type, and end-of-pay-period date;
    those are aggregated per person so that retroactive postings (pay periods
    that closed before the report month) stay distinguishable from current
    charges. "Total for <name>" supplies the authoritative amount.

    Note that a person whose rows straddle a page break is only complete once
    the pages are combined; parse_sponsored_report assembles report-wide.

    Args:
        page: pdfplumber page object
        report_period: Period string from report summary (e.g., "November 2025")
        report_project_id: Grant number from report summary

    Returns list of EffortAllocation objects.
    """
    text = page.extract_text() or ""
    if not _is_salary_page(text):
        return []

    project_id, period = _salary_page_context(text, report_period, report_project_id)
    details, ordered, totals = _collect_salary_rows(text)
    return _assemble_allocations(details, ordered, totals, project_id, period)


# ----------------------------------------------------------------------
# Salary commitment page
# ----------------------------------------------------------------------

# "Li, Henry SALARY-STUDENT GRADUATE August-2026 March-2027 31,416.72"
_COMMITMENT_ROW = re.compile(
    r"^(?P<left>.+?)\s+(?P<start>[A-Za-z]+-\d{4})\s+(?P<end>[A-Za-z]+-\d{4})\s+"
    r"(?P<amounts>(?:\(?[\d,]+\.\d{2}\)?\s*)+)$"
)

# Older layouts use calendar dates for the encumbrance window.
_COMMITMENT_ROW_DATED = re.compile(
    r"^(?P<left>.+?)\s+(?P<start>\d{1,2}/\d{1,2}/\d{2,4})\s+(?:to\s+|-\s*)?"
    r"(?P<end>\d{1,2}/\d{1,2}/\d{2,4})\s+(?P<amounts>(?:\(?[\d,]+\.\d{2}\)?\s*)+)$"
)


def parse_commitment_page(
    page, report_period: str = "Unknown", report_project_id: str = "unknown"
) -> list[CommitmentDetail]:
    """
    Parse a Sponsored PI Salary Commitment Report page.

    Each row names one person, their encumbrance window, and the committed
    amount -- the future salary the sponsor's funds are already obligated to.

    Args:
        page: pdfplumber page object
        report_period: Fallback period
        report_project_id: Fallback project ID

    Returns list of CommitmentDetail objects.
    """
    text = page.extract_text() or ""

    is_commitment_page = (
        "Salary Commitment" in text
        or "Commitment Report" in text
        or "Salary Encumbrance" in text
        or ("Encumbrance" in text and "Salary" in text)
    )
    if not is_commitment_page:
        return []

    commitments: list[CommitmentDetail] = []

    for raw_line in text.split("\n"):
        line = raw_line.strip()
        if not line or line.startswith(("Total", "Grand", "Report for", "Employee")):
            continue

        match = _COMMITMENT_ROW.match(line) or _COMMITMENT_ROW_DATED.match(line)
        if not match:
            continue

        name, gl_account = _split_name_and_gl(match.group("left"))
        if not _is_person_name(name):
            continue

        amounts = [clean_text_to_decimal(a) or Decimal("0") for a in match.group("amounts").split()]
        start = _parse_date_flexible(match.group("start"))
        end = _parse_date_flexible(match.group("end"))
        # Month-granularity windows run to the end of the closing month.
        if end and re.match(r"^[A-Za-z]+-\d{4}$", match.group("end")):
            end = month_end(end)

        commitments.append(
            CommitmentDetail(
                person_name=name,
                employee_type=parse_employee_type(gl_account or ""),
                salary_committed=amounts[0] if amounts else Decimal("0"),
                fringe_committed=amounts[1] if len(amounts) > 1 else Decimal("0"),
                idc_committed=amounts[2] if len(amounts) > 2 else Decimal("0"),
                encumbrance_start=start,
                encumbrance_end=end,
            )
        )

    return commitments


# ----------------------------------------------------------------------
# Whole-report entry point
# ----------------------------------------------------------------------


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
    all_personnel: list[EffortAllocation] = []
    all_commitments: list[CommitmentDetail] = []

    def amount(summary: dict, key: str) -> Decimal:
        return summary.get(key) or Decimal("0")

    try:
        with pdfplumber.open(file_path) as pdf:
            if not pdf.pages:
                return None, []

            summary = parse_sponsored_summary(pdf.pages[0])

            spending_report = SpendingReport(
                project_id=summary.get("grant_number", "unknown"),
                period=summary.get("period", "Unknown"),
                year=summary.get("year", 0),
                month=summary.get("month", 0),
                total_spent=amount(summary, "total_spent"),
                total_committed=amount(summary, "total_committed"),
                total_spent_and_committed=amount(summary, "total_spent_and_committed"),
                indirect_spent=amount(summary, "indirect_spent"),
                budget_utilized_pct=summary.get("budget_utilized_pct"),
                total_month=summary.get("total_month"),
                indirect_month=summary.get("indirect_month"),
                funded_ceiling=summary.get("funded_ceiling"),
                total_revenue_received=summary.get("total_revenue_received"),
                revenue_month=summary.get("revenue_month"),
                budget_start_date=summary.get("budget_start_date"),
                budget_end_date=summary.get("budget_end_date"),
                grant_end_date=summary.get("grant_end_date"),
                grantor_code=summary.get("grantor_code"),
                stated_idc_rate=summary.get("stated_idc_rate"),
            )

            for prefix in set(CATEGORY_LABELS.values()):
                setattr(spending_report, f"{prefix}_spent", amount(summary, f"{prefix}_spent"))
                setattr(spending_report, f"{prefix}_month", summary.get(f"{prefix}_month"))
                setattr(
                    spending_report,
                    f"{prefix}_committed",
                    amount(summary, f"{prefix}_committed"),
                )

            report_period = summary.get("period", "Unknown")
            report_project_id = summary.get("grant_number", "unknown")

            # Salary rows are assembled across every salary page at once: a
            # person's detail rows and their "Total for" line can land on
            # different pages, and assembling per page would both double-count
            # that person and lose their earlier pay periods.
            details: dict[str, list[dict]] = {}
            ordered: list[str] = []
            totals: dict[str, Decimal] = {}
            salary_project_id, salary_period = report_project_id, report_period

            for page in pdf.pages:
                page_text = page.extract_text() or ""
                if _is_salary_page(page_text):
                    salary_project_id, salary_period = _salary_page_context(
                        page_text, report_period, report_project_id
                    )
                    page_details, page_ordered, page_totals = _collect_salary_rows(page_text)
                    for name, rows in page_details.items():
                        details.setdefault(name, []).extend(rows)
                    for name in page_ordered:
                        if name not in ordered:
                            ordered.append(name)
                    totals.update(page_totals)

                all_commitments.extend(
                    parse_commitment_page(page, report_period, report_project_id)
                )

            all_personnel = _assemble_allocations(
                details, ordered, totals, salary_project_id, salary_period
            )

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
