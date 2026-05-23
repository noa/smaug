"""
Invoice PDF parsing.

Extracts billing data from sponsor invoices (e.g., JHU invoices to LLNL).
These are external billing documents with cumulative expense totals.
"""

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

import pdfplumber

from .models import Invoice


def clean_currency(text: str | None) -> Decimal | None:
    """
    Convert a currency string (e.g., '132,522.33' or '$1,234.56') to Decimal.
    Returns None if text is empty or invalid.
    """
    if not text:
        return None
    # Remove $ signs, commas, and whitespace
    cleaned = re.sub(r"[$,\s]", "", text.strip())
    if not cleaned:
        return None
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None


def parse_date_mdy(text: str) -> date | None:
    """Parse a date in MM/DD/YYYY format."""
    try:
        return datetime.strptime(text.strip(), "%m/%d/%Y").date()
    except ValueError:
        return None


def parse_date_full(text: str) -> date | None:
    """Parse a date like 'January 12, 2026'."""
    try:
        return datetime.strptime(text.strip(), "%B %d, %Y").date()
    except ValueError:
        return None


def parse_invoice_summary(text: str) -> dict:
    """
    Parse the first page summary of an invoice.

    Returns dict with:
        - invoice_number: Invoice #
        - invoice_date: Date of invoice
        - period_start, period_end: Billing period
        - grant_number: JHU Grant No
        - subcontract_no: Subcontract No
        - budget_total: Total budget
        - previous_expense: Previous cumulative
        - current_expense: This period
        - cumulative_expense: New cumulative
        - categories: Dict of category -> cumulative amount
    """
    result: dict[str, str | date | Decimal | dict[str, Decimal] | None] = {
        "invoice_number": None,
        "invoice_date": None,
        "period_start": None,
        "period_end": None,
        "grant_number": None,
        "subcontract_no": None,
        "budget_total": Decimal("0"),
        "previous_expense": Decimal("0"),
        "current_expense": Decimal("0"),
        "cumulative_expense": Decimal("0"),
        "categories": {},
    }

    # Invoice number
    match = re.search(r"INVOICE\s*#\s*(\d+)", text)
    if match:
        result["invoice_number"] = match.group(1)

    # Invoice date
    match = re.search(r"Invoice\s+Date:\s*(\w+\s+\d+,\s*\d+)", text)
    if match:
        result["invoice_date"] = parse_date_full(match.group(1))

    # Period covered
    match = re.search(r"Period\s+Covered:\s*(\d+/\d+/\d+)\s*-\s*(\d+/\d+/\d+)", text)
    if match:
        result["period_start"] = parse_date_mdy(match.group(1))
        result["period_end"] = parse_date_mdy(match.group(2))

    # Grant number
    match = re.search(r"JHU\s+Grant\s+No:\s*(\d+)", text)
    if match:
        result["grant_number"] = match.group(1)

    # Subcontract number
    match = re.search(r"Subcontract\s+No:\s*(\S+)", text)
    if match:
        result["subcontract_no"] = match.group(1)

    # Parse expense categories
    # Pattern: Category name followed by numbers (Previous, Current, Cumulative)
    category_patterns = [
        (r"Salaries\s*&\s*Wages\s+([\d,.]+)\s+([\d,.]+)\s+([\d,.]+)", "Salaries & Wages"),
        (r"Fringe\s+Benefits\s+([\d,.]+)\s+([\d,.]+)\s+([\d,.]+)", "Fringe Benefits"),
        (
            r"Materials\s+and\s+Supplies\s+([\d,.]+)\s+([\d,.]+)\s+([\d,.]+)",
            "Materials and Supplies",
        ),
        (r"Tuition\s+and\s+Fees\s+([\d,.]+)\s+([\d,.]+)\s+([\d,.]+)", "Tuition and Fees"),
        (r"Travel\s+([\d,.]+)\s+([\d,.]+)\s+([\d,.]+)", "Travel"),
        (
            r"Student\s+Health\s+Insurance\s+([\d,.]+)\s+([\d,.]+)\s+([\d,.]+)",
            "Student Health Insurance",
        ),
        (r"Facilities\s*&\s*Admin\s+Costs\s+([\d,.]+)\s+([\d,.]+)\s+([\d,.]+)", "F&A Costs"),
        (r"Other\s+Expenses\s+([\d,.]+)\s+([\d,.]+)\s+([\d,.]+)", "Other Expenses"),
    ]

    for pattern, category in category_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            cumulative = clean_currency(match.group(3))
            if cumulative:
                result["categories"][category] = cumulative  # type: ignore[index]

    # Total line: Budget, Previous, Current, Cumulative
    # Pattern: Total  1,271,083.01  594,083.01  132,522.33  726,605.34
    match = re.search(r"Total\s+([\d,.]+)\s+([\d,.]+)\s+([\d,.]+)\s+([\d,.]+)", text)
    if match:
        result["budget_total"] = clean_currency(match.group(1)) or Decimal("0")
        result["previous_expense"] = clean_currency(match.group(2)) or Decimal("0")
        result["current_expense"] = clean_currency(match.group(3)) or Decimal("0")
        result["cumulative_expense"] = clean_currency(match.group(4)) or Decimal("0")

    return result


def parse_personnel_page(text: str) -> list[dict]:
    """
    Parse personnel details from backup pages.

    Format:
    Employee ID  Last, First  End of Pay  Posting Date  Salary  Fringe
    100001 Smith , Jane 12/15/2025 12/10/2025 $ 590.48 $ 159.75
    """
    personnel = []

    # Pattern for personnel lines with salary
    pattern = re.compile(
        r"(\d{6})\s+"  # Employee ID (6 digits)
        r"(\w+)\s*,\s*(\w+)\s+"  # Last, First
        r"(\d+/\d+/\d+)\s+"  # End of Pay Period
        r"(\d+/\d+/\d+)\s+"  # Posting Date
        r"\$?\s*([\d,.]+)\s+"  # Salary
        r"\$?\s*([\d,.]+)"  # Fringe
    )

    for match in pattern.finditer(text):
        person = {
            "employee_id": match.group(1),
            "name": f"{match.group(3)} {match.group(2)}".strip(),  # First Last
            "pay_period_end": match.group(4),
            "posting_date": match.group(5),
            "salary": float(clean_currency(match.group(6)) or 0),
            "fringe": float(clean_currency(match.group(7)) or 0),
        }
        personnel.append(person)

    return personnel


def parse_invoice(file_path: str | Path) -> Invoice | None:
    """
    Parse a complete invoice PDF.

    Args:
        file_path: Path to the invoice PDF

    Returns:
        Invoice object or None if parsing fails
    """
    path = Path(file_path)
    if not path.exists():
        return None

    try:
        with pdfplumber.open(path) as pdf:
            if not pdf.pages:
                return None

            # Parse first page for summary
            first_page_text = pdf.pages[0].extract_text() or ""
            summary = parse_invoice_summary(first_page_text)

            # Parse any personnel detail pages
            all_personnel = []
            for page in pdf.pages[1:]:
                page_text = page.extract_text() or ""
                # Check if this looks like a personnel page
                if "Employee" in page_text or "Salary" in page_text:
                    personnel = parse_personnel_page(page_text)
                    all_personnel.extend(personnel)

            # Determine project ID from grant number or filename
            project_id = "unknown"
            if summary["grant_number"]:
                project_id = summary["grant_number"]
            else:
                # Try to extract from filename (e.g., 148591_ARTS_April_2025.pdf)
                name_parts = path.stem.split("_")
                if len(name_parts) >= 2:
                    project_id = name_parts[1]

            # Build Invoice object
            invoice = Invoice(
                project_id=project_id,
                invoice_number=summary["invoice_number"] or path.stem,
                invoice_date=summary["invoice_date"] or date.today(),
                period_start=summary["period_start"] or date.today(),
                period_end=summary["period_end"] or date.today(),
                subcontract_no=summary["subcontract_no"],
                grant_number=summary["grant_number"],
                previous_expense=summary["previous_expense"],
                current_expense=summary["current_expense"],
                cumulative_expense=summary["cumulative_expense"],
                budget_total=summary["budget_total"],
                categories=summary["categories"],
                personnel=all_personnel,
            )

            return invoice

    except Exception as e:
        print(f"Error parsing invoice {path}: {e}")
        return None


def find_invoices(invoice_dir: str | Path) -> list[Path]:
    """Find all invoice PDFs in a directory."""
    path = Path(invoice_dir)
    if not path.exists():
        return []
    return sorted(path.glob("*.pdf"))
