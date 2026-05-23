"""
JHU Invoice parser.

Parses the PDF invoices sent by JHU to external sponsors (e.g., LLNL
sub-award billing).  These contain cumulative expense totals broken
down by category.

Registered as an entry point for automatic discovery.
"""

from pathlib import Path

from ..invoice_parsing import parse_invoice as _parse_invoice
from ..models import Invoice
from . import InvoiceParser


class JHUInvoiceParser(InvoiceParser):
    """Parser for JHU sponsor invoices (PDF format)."""

    def name(self) -> str:
        return "JHU Lockbox Invoice"

    def can_parse(self, file_path: Path) -> bool:
        if file_path.suffix.lower() != ".pdf":
            return False

        try:
            import pdfplumber

            with pdfplumber.open(file_path) as pdf:
                if not pdf.pages:
                    return False
                text = pdf.pages[0].extract_text() or ""
                return "INVOICE" in text and ("JHU Grant No" in text or "Subcontract No" in text)
        except Exception:
            return False

    def parse(self, file_path: Path) -> Invoice | None:
        return _parse_invoice(file_path)
