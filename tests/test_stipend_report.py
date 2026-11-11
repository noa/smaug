"""
Unit tests for non-sponsored stipend statement parsing.
"""

from decimal import Decimal
from unittest.mock import MagicMock, patch

from smaug.sponsored_report_parsing import (
    parse_non_sponsored_report,
    parse_non_sponsored_summary,
    parse_non_sponsored_transactions,
)

SYNTHETIC_NON_SPONSORED_MAY_PAGE_1 = """\
Non-Sponsored Summary Statement
Funded Program: 80000001 - STIPEND - SMITH Fund: 100000
Expenditures May 2026
Travel Foreign 1,500.00 1,500.00
Other Expenses 200.00 200.00
Year-to-Date Expenditures 0.00 0.00 1,700.00
Month-End Balance: 48,300.00
"""

SYNTHETIC_NON_SPONSORED_JUNE_PAGE_1 = """\
Non-Sponsored Summary Statement
Funded Program: 80000001 - STIPEND - SMITH Fund: 100000
Expenditures June 2026
Travel Foreign 1,500.00 1,500.00
Other Expenses 1,250.00 1,450.00
Year-to-Date Expenditures 0.00 1,250.00 2,950.00
Month-End Balance: 47,050.00
"""

SYNTHETIC_NON_SPONSORED_JUNE_PAGE_2 = """\
Non Sponsored PI Transaction Report
Funded Program: 80000001
Other Expenses MISC REIMB 00100001/OTHER JANE SMITH 1900000001 06/22/2026 1,250.00
Total Other Expenses 1,250.00
"""


def _mock_page(text: str) -> MagicMock:
    page = MagicMock()
    page.extract_text.return_value = text
    return page


def test_parse_non_sponsored_summary_may_synthetic():
    summary = parse_non_sponsored_summary(_mock_page(SYNTHETIC_NON_SPONSORED_MAY_PAGE_1))
    assert summary["funded_program"] == "80000001"
    assert summary["period"] == "May 2026"
    assert summary["year"] == 2026
    assert summary["month"] == 5
    assert summary["total_spent"] == Decimal("1700.00")
    assert summary["other_spent"] == Decimal("200.00")
    assert summary["travel_foreign_spent"] == Decimal("1500.00")


def test_parse_non_sponsored_summary_june_synthetic():
    summary = parse_non_sponsored_summary(_mock_page(SYNTHETIC_NON_SPONSORED_JUNE_PAGE_1))
    assert summary["funded_program"] == "80000001"
    assert summary["period"] == "June 2026"
    assert summary["year"] == 2026
    assert summary["month"] == 6
    assert summary["total_month"] == Decimal("1250.00")
    assert summary["total_spent"] == Decimal("2950.00")
    assert summary["other_month"] == Decimal("1250.00")
    assert summary["other_spent"] == Decimal("1450.00")
    assert summary["travel_foreign_spent"] == Decimal("1500.00")


def test_parse_non_sponsored_transactions_synthetic():
    txs = parse_non_sponsored_transactions(_mock_page(SYNTHETIC_NON_SPONSORED_JUNE_PAGE_2))
    assert len(txs) == 1
    exp = txs[0]
    assert exp.amount == Decimal("1250.00")
    assert exp.vendor == "JANE SMITH"
    assert exp.ref_doc == "1900000001"
    assert exp.date is not None
    assert (exp.date.year, exp.date.month, exp.date.day) == (2026, 6, 22)
    assert "MISC REIMB" in (exp.description or "")


def test_parse_non_sponsored_report_mocked(tmp_path):
    dummy_pdf = tmp_path / "report.pdf"
    dummy_pdf.write_bytes(b"%PDF-1.4")

    mock_pdf = MagicMock()
    mock_pdf.pages = [
        _mock_page(SYNTHETIC_NON_SPONSORED_JUNE_PAGE_1),
        _mock_page(SYNTHETIC_NON_SPONSORED_JUNE_PAGE_2),
    ]
    mock_pdf.__enter__.return_value = mock_pdf
    mock_pdf.__exit__.return_value = False

    with patch("smaug.sponsored_report_parsing.pdfplumber") as mock_plumber:
        mock_plumber.open.return_value = mock_pdf
        report = parse_non_sponsored_report(dummy_pdf)

    assert report is not None
    assert report.project_id == "80000001"
    assert report.period == "June 2026"
    assert report.total_spent == Decimal("2950.00")
    assert report.total_month == Decimal("1250.00")
    assert len(report.expenses) == 1
    assert report.expenses[0].ref_doc == "1900000001"
