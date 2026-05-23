"""Tests for sponsored report regex extraction using synthetic page text.

These tests exercise the parsing logic without requiring real PDFs by
mocking pdfplumber page objects with known text content.
"""

from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from smaug.sponsored_report_parsing import (
    clean_text_to_decimal,
    parse_employee_type,
    parse_personnel_page,
    parse_sponsored_summary,
)

# --- Unit tests for helper functions ---


class TestCleanTextToDecimal:
    def test_simple_number(self):
        assert clean_text_to_decimal("1234.56") == Decimal("1234.56")

    def test_with_commas(self):
        assert clean_text_to_decimal("1,234,567.89") == Decimal("1234567.89")

    def test_negative_parentheses(self):
        assert clean_text_to_decimal("(500.00)") == Decimal("-500.00")

    def test_empty_string(self):
        assert clean_text_to_decimal("") is None

    def test_none(self):
        assert clean_text_to_decimal(None) is None

    def test_whitespace(self):
        assert clean_text_to_decimal("  ") is None

    def test_garbage(self):
        assert clean_text_to_decimal("abc") is None


class TestParseEmployeeType:
    def test_faculty(self):
        from smaug.models import EmployeeType

        assert parse_employee_type("Faculty Salaries") == EmployeeType.FACULTY

    def test_postdoc(self):
        from smaug.models import EmployeeType

        assert parse_employee_type("Postdoc Salaries") == EmployeeType.POSTDOC

    def test_grad_student(self):
        from smaug.models import EmployeeType

        assert parse_employee_type("Student Grad Wages") == EmployeeType.GRAD_STUDENT

    def test_staff(self):
        from smaug.models import EmployeeType

        assert parse_employee_type("Staff Professional") == EmployeeType.STAFF

    def test_unknown(self):
        from smaug.models import EmployeeType

        assert parse_employee_type("Something Else") == EmployeeType.UNKNOWN


# --- Regex extraction tests with synthetic page text ---


def _mock_page(text: str) -> MagicMock:
    """Create a mock pdfplumber page that returns the given text."""
    page = MagicMock()
    page.extract_text.return_value = text
    return page


# A synthetic page that matches the JHU sponsored report format.
# Category lines: "Category Name  <monthly>  <cum_spent>  <committed>"
# The regex captures 3 groups: (monthly, cum_spent, committed).
SYNTHETIC_SUMMARY_TEXT = """\
Statement of Expenditures
Grant: 145891 - IARPA ARTS PI For Andrews, Nicholas
Sponsored Program: 90109289 - B661547

Expenditures Budget March 2026

Salaries & Wages 35000.00 650000.00 12000.00
Fringe Benefits 8500.00 158000.00 3200.00
Tuition & Fees 0.00 42000.00 0.00
Student Health Insurance 0.00 8500.00 0.00
Service Center 500.00 3200.00 0.00
Travel Domestic 1200.00 15000.00 0.00
Other Expenses 800.00 12000.00 0.00

Total Indirect Costs 300000.00 12000.00 245000.00 0.00 245000.00

Total Expenditures 1400000.00 58000.00 1133700.00 15200.00 1148900.00

Sponsored Revenue 2473206.00

Budget Utilized: 46.4%
"""


class TestParseSponsoredSummary:
    """Test regex extraction from synthetic summary page text."""

    @pytest.fixture
    def summary(self):
        page = _mock_page(SYNTHETIC_SUMMARY_TEXT)
        return parse_sponsored_summary(page)

    def test_grant_number(self, summary):
        assert summary["grant_number"] == "145891"

    def test_grant_name(self, summary):
        assert "IARPA ARTS" in summary["grant_name"]

    def test_sponsored_program(self, summary):
        assert summary["sponsored_program"] == "90109289"

    def test_award_id(self, summary):
        assert summary["award_id"] == "B661547"

    def test_period(self, summary):
        assert summary["period"] == "March 2026"
        assert summary["year"] == 2026
        assert summary["month"] == 3

    def test_total_spent(self, summary):
        assert summary["total_spent"] == Decimal("1133700.00")

    def test_total_committed(self, summary):
        assert summary["total_committed"] == Decimal("15200.00")

    def test_total_spent_and_committed(self, summary):
        assert summary["total_spent_and_committed"] == Decimal("1148900.00")

    def test_indirect_spent(self, summary):
        assert summary["indirect_spent"] == Decimal("245000.00")

    def test_salary_spent(self, summary):
        assert summary["salary_spent"] == Decimal("650000.00")

    def test_fringe_spent(self, summary):
        assert summary["fringe_spent"] == Decimal("158000.00")

    def test_tuition_spent(self, summary):
        assert summary["tuition_spent"] == Decimal("42000.00")

    def test_budget_utilized(self, summary):
        assert summary["budget_utilized_pct"] == Decimal("46.4")

    def test_funded_ceiling(self, summary):
        assert summary["funded_ceiling"] == Decimal("2473206.00")


class TestParseSponsoredSummaryMissingFields:
    """Test graceful handling when fields are absent."""

    def test_empty_page(self):
        page = _mock_page("Nothing useful here.")
        summary = parse_sponsored_summary(page)
        assert "grant_number" not in summary
        assert "total_spent" not in summary

    def test_partial_header(self):
        page = _mock_page("Grant: 999999 - Some Project PI For Smith\nNo other data.")
        summary = parse_sponsored_summary(page)
        assert summary["grant_number"] == "999999"
        assert "total_spent" not in summary


# Synthetic personnel / salary report page
SYNTHETIC_PERSONNEL_TEXT = """\
Salary Report
Grant: 145891 - IARPA ARTS

March 2026

FACULTY Salaries
Andrews, Nicholas Doc 1234567 01/2026 02/2026 3,500.00
Total for Andrews, Nicholas 3,500.00

STUDENT GRAD Wages
Li, Henry Doc 2345678 01/2026 02/2026 4,166.67
Total for Li, Henry 4,166.67

POSTDOC Salaries
Zhang, Lin Doc 3456789 01/2026 02/2026 6,666.66
Total for Zhang, Lin 6,666.66
"""


class TestParsePersonnelPage:
    """Test personnel extraction from synthetic salary report text."""

    @pytest.fixture
    def personnel(self):
        page = _mock_page(SYNTHETIC_PERSONNEL_TEXT)
        return parse_personnel_page(page)

    def test_finds_all_people(self, personnel):
        names = {p.person_name for p in personnel}
        assert "Andrews, Nicholas" in names
        assert "Li, Henry" in names
        assert "Zhang, Lin" in names

    def test_salary_amounts(self, personnel):
        by_name = {p.person_name: p for p in personnel}
        assert by_name["Andrews, Nicholas"].salary_amount == Decimal("3500.00")
        assert by_name["Li, Henry"].salary_amount == Decimal("4166.67")
        assert by_name["Zhang, Lin"].salary_amount == Decimal("6666.66")

    def test_period(self, personnel):
        for p in personnel:
            assert "2026" in p.period

    def test_project_id(self, personnel):
        for p in personnel:
            assert p.project_id == "145891"

    def test_non_salary_page_returns_empty(self):
        page = _mock_page("This is a regular page with no salary data.")
        result = parse_personnel_page(page)
        assert result == []
