"""
Concur expense report export ingestion.

Parses exported Concur expense report spreadsheets (.xlsx) containing submitted
or reimbursed expense line items with dates, categories, vendors, receipts, and amounts.
"""

from __future__ import annotations

import hashlib
import warnings
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

import openpyxl

from .credit_card import ClassificationResult, classify_transaction
from .models import CreditCardTransaction, Date, ReimbursementCategory


@dataclass
class ConcurExpenseEntry:
    """A single expense line item extracted from a Concur Excel export."""

    date: Date
    vendor: str
    expense_type: str
    payment_type: str
    amount: Decimal
    receipt: str
    report_name: str
    hash_id: str
    category: ReimbursementCategory = ReimbursementCategory.OTHER


def is_concur_export(file_path: str | Path) -> bool:
    """Check if file is a Concur Excel export spreadsheet."""
    path = Path(file_path)
    if path.name.startswith("~$") or path.suffix.lower() not in (".xlsx", ".xls"):
        return False

    try:
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", category=UserWarning, module="openpyxl")
            wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
            sheet = wb.active
            if sheet is None:
                wb.close()
                return False
            for row in sheet.iter_rows(values_only=True):
                if not row or not any(row):
                    continue
                headers = [str(c).strip().lower() for c in row if c is not None]
                # Concur exports contain 'date' and ('vendor details' or 'vendor') and ('approved' or 'amount')
                has_date = "date" in headers
                has_vendor = any("vendor" in h for h in headers)
                has_amount = any(h in ("approved", "amount", "claimed", "total") for h in headers)
                wb.close()
                return has_date and (has_vendor or has_amount)
            wb.close()
    except Exception:
        return False
    return False


def parse_concur_export(file_path: str | Path) -> list[ConcurExpenseEntry]:
    """
    Parse a Concur expense export spreadsheet (.xlsx).

    Args:
        file_path: Path to the .xlsx file

    Returns:
        List of ConcurExpenseEntry items
    """
    path = Path(file_path)
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=UserWarning, module="openpyxl")
        wb = openpyxl.load_workbook(path, data_only=True)
    sheet = wb.active
    if sheet is None:
        wb.close()
        return []
    report_name = path.stem

    entries: list[ConcurExpenseEntry] = []
    header_map: dict[str, int] = {}

    for row_idx, row in enumerate(sheet.iter_rows(values_only=True)):
        if not row or not any(row):
            continue

        if not header_map:
            # Find header row
            cleaned = [str(c).strip().lower() if c is not None else "" for c in row]
            if "date" in cleaned:
                for idx, col in enumerate(cleaned):
                    if col:
                        header_map[col] = idx
                continue

        # Data row
        date_raw = (
            row[header_map["date"]]
            if "date" in header_map and header_map["date"] < len(row)
            else None
        )
        if not date_raw:
            continue

        # Parse date
        if isinstance(date_raw, datetime):
            parsed_date = date_raw.date()
        elif isinstance(date_raw, date):
            parsed_date = date_raw
        else:
            try:
                parsed_date = datetime.strptime(str(date_raw).strip(), "%m/%d/%Y").date()
            except ValueError:
                try:
                    parsed_date = datetime.strptime(str(date_raw).strip(), "%Y-%m-%d").date()
                except ValueError:
                    continue

        # Vendor
        vendor_col = header_map.get("vendor details", header_map.get("vendor", -1))
        vendor = (
            str(row[vendor_col]).strip()
            if vendor_col >= 0 and vendor_col < len(row) and row[vendor_col] is not None
            else "Unknown"
        )

        # Expense type
        exp_type_col = header_map.get("expense type", -1)
        exp_type = (
            str(row[exp_type_col]).strip()
            if exp_type_col >= 0 and exp_type_col < len(row) and row[exp_type_col] is not None
            else "Other"
        )

        # Payment type
        pay_type_col = header_map.get("payment type", -1)
        payment_type = (
            str(row[pay_type_col]).strip()
            if pay_type_col >= 0 and pay_type_col < len(row) and row[pay_type_col] is not None
            else "Out of Pocket"
        )

        # Receipt
        receipt_col = header_map.get("receipt", -1)
        receipt = (
            str(row[receipt_col]).strip()
            if receipt_col >= 0 and receipt_col < len(row) and row[receipt_col] is not None
            else "No"
        )

        # Amount (from 'approved', 'amount', or 'total')
        amt_col = header_map.get(
            "approved",
            header_map.get("amount", header_map.get("claimed", header_map.get("total", -1))),
        )
        amt_raw = (
            str(row[amt_col]).replace("$", "").replace(",", "").strip()
            if amt_col >= 0 and amt_col < len(row) and row[amt_col] is not None
            else "0"
        )
        try:
            amount = Decimal(amt_raw)
        except InvalidOperation:
            amount = Decimal("0")

        # Classify category using report name, vendor, and expense type
        clean_report_name = report_name.replace("_", " ").replace("-", " ")
        combined_desc = f"{clean_report_name} {vendor} {exp_type}"
        dummy_tx = CreditCardTransaction(
            transaction_date=parsed_date,
            post_date=None,
            description=combined_desc,
            category=exp_type,
            amount=amount,
        )
        cl: ClassificationResult = classify_transaction(dummy_tx)
        cat = cl.category if cl.is_reimbursable else ReimbursementCategory.OTHER

        # Generate deduplication hash
        hash_input = f"{report_name}|{row_idx}|{parsed_date.isoformat()}|{vendor}|{amt_raw}"
        hash_id = hashlib.sha256(hash_input.encode("utf-8")).hexdigest()[:16]

        entries.append(
            ConcurExpenseEntry(
                date=parsed_date,
                vendor=vendor,
                expense_type=exp_type,
                payment_type=payment_type,
                amount=amount,
                receipt=receipt,
                report_name=report_name,
                hash_id=hash_id,
                category=cat,
            )
        )

    wb.close()
    return entries
