"""Tests for sponsored report regex extraction using synthetic page text.

These tests exercise the parsing logic without requiring real PDFs by
mocking pdfplumber page objects with known text content.
"""

from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from smaug.sponsored_report_parsing import (
    clean_text_to_decimal,
    parse_commitment_page,
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


# --- Tests for expanded report parsing capabilities ---

SYNTHETIC_JULY_REPORT_PAGE1 = """\
Johns Hopkins University Sponsored Financial Report
Grant: 145891 - IARPA ARTS PI For Andrews, Nicholas
Sponsored Program: 90109289 - B661547
Budget Begin Date: 02/06/2024
Budget End Date: 03/31/2027
Grant Project End Date: 03/31/2027
Grantor Code: LLNL
F&A Rate: 55.50% MTDC

Expenditures Budget July 2026

Salaries & Wages 25000.00 450000.00 12000.00
Fringe Benefits 5500.00 99000.00 2640.00
Tuition & Fees 0.00 26668.00 0.00
Total Student Health 0.00 8730.00 0.00
Total Service Center 271.69 1500.00 0.00
Travel Domestic 1200.00 12500.00 0.00
Travel Foreign 4286.60 4286.60 0.00
Supplies & Materials 4848.99 4848.99 0.00
Capital Equipment 0.00 15000.00 0.00
Subcontracts 10000.00 80000.00 0.00
Consultant Services 1000.00 5000.00 0.00
Other Expenses 800.00 9500.00 200.00

Total Expenditures 2473206.00 72571.08 850000.00 14840.00 864840.00
Total Indirect Costs 0.00 19663.80 142500.00 0.00 142500.00

Budget Utilized: 35.0%
Sponsored Revenue 1619296.12 107213.11
"""


class TestParseExpandedSummary:
    @pytest.fixture
    def summary(self):
        page = _mock_page(SYNTHETIC_JULY_REPORT_PAGE1)
        return parse_sponsored_summary(page)

    def test_total_month(self, summary):
        assert summary["total_month"] == Decimal("72571.08")

    def test_travel_foreign(self, summary):
        assert summary["travel_foreign_spent"] == Decimal("4286.60")
        assert summary["travel_foreign_month"] == Decimal("4286.60")

    def test_supplies(self, summary):
        assert summary["supplies_spent"] == Decimal("4848.99")
        assert summary["supplies_month"] == Decimal("4848.99")

    def test_equipment(self, summary):
        assert summary["equipment_spent"] == Decimal("15000.00")
        assert summary["equipment_month"] == Decimal("0.00")

    def test_subcontracts(self, summary):
        assert summary["subcontracts_spent"] == Decimal("80000.00")
        assert summary["subcontracts_month"] == Decimal("10000.00")

    def test_consultant(self, summary):
        assert summary["consultant_spent"] == Decimal("5000.00")
        assert summary["consultant_month"] == Decimal("1000.00")

    def test_award_metadata(self, summary):
        from datetime import date

        assert summary["budget_start_date"] == date(2024, 2, 6)
        assert summary["budget_end_date"] == date(2027, 3, 31)
        assert summary["grant_end_date"] == date(2027, 3, 31)
        assert summary["grantor_code"] == "LLNL"
        assert summary["stated_idc_rate"] == Decimal("55.50")

    def test_revenue(self, summary):
        assert summary["total_revenue_received"] == Decimal("1619296.12")
        assert summary["revenue_month"] == Decimal("107213.11")
        assert summary["funded_ceiling"] == Decimal("1619296.12")


SYNTHETIC_JULY_PERSONNEL_PAGE = """\
Salary Report July 2026
Grant: 145891 - IARPA ARTS

G/L 600120 - SAL-FAC TLC / PtInstSl
Andrews, Nicholas Doc 1000001 03/15/2026 to 07/31/2026 17,673.00
Total for Andrews, Nicholas 17,673.00

G/L 600010 - FACULTY SALARIES
Wiesner, Matthew Doc 1000002 01/15/2026 to 06/30/2026 4,382.52
Total for Wiesner, Matthew 4,382.52

G/L 600030 - STUDENT GRAD STIPEND
Sisman, Berrak Doc 1000003 04/15/2026 to 06/30/2026 2,275.02
Total for Sisman, Berrak 2,275.02
"""


class TestParseDetailedPersonnelPage:
    @pytest.fixture
    def personnel(self):
        page = _mock_page(SYNTHETIC_JULY_PERSONNEL_PAGE)
        return parse_personnel_page(page, report_period="July 2026", report_project_id="145891")

    def test_pay_periods_and_gl(self, personnel):
        from datetime import date

        from smaug.models import EmployeeType

        by_name = {p.person_name: p for p in personnel}

        andrews = by_name["Andrews, Nicholas"]
        assert andrews.salary_amount == Decimal("17673.00")
        assert andrews.gl_account == "600120"
        assert andrews.wage_type == "SAL-FAC TLC / PtInstSl"
        assert andrews.pay_period_start == date(2026, 3, 15)
        assert andrews.pay_period_end == date(2026, 7, 31)

        wiesner = by_name["Wiesner, Matthew"]
        assert wiesner.salary_amount == Decimal("4382.52")
        assert wiesner.gl_account == "600010"
        assert wiesner.pay_period_start == date(2026, 1, 15)
        assert wiesner.pay_period_end == date(2026, 6, 30)

        sisman = by_name["Sisman, Berrak"]
        assert sisman.salary_amount == Decimal("2275.02")
        assert sisman.employee_type == EmployeeType.GRAD_STUDENT
        assert sisman.pay_period_start == date(2026, 4, 15)
        assert sisman.pay_period_end == date(2026, 6, 30)


SYNTHETIC_COMMITMENT_PAGE = """\
Salary Commitment Report July 2026
Grant: 145891 - IARPA ARTS

G/L 600030 - STUDENT GRAD STIPEND
Ulgen, Ege Doc 2000001 08/01/2026 03/31/2027 33333.36 0.00 18500.02
Zhao, Kevin Doc 2000002 08/01/2026 03/31/2027 33333.36 0.00 18500.02
Student, Three Doc 2000003 08/01/2026 03/31/2027 33333.36 0.00 18500.02
Student, Four Doc 2000004 08/01/2026 03/31/2027 33333.36 0.00 18500.02

G/L 600010 - FACULTY SALARIES
Andrews, Nicholas Doc 2000005 08/01/2026 03/31/2027 15000.00 4725.00 10947.38
Wiesner, Matthew Doc 2000006 08/01/2026 03/31/2027 5000.00 1575.00 3649.13
"""


class TestParseCommitmentPage:
    @pytest.fixture
    def commitments(self):
        page = _mock_page(SYNTHETIC_COMMITMENT_PAGE)
        return parse_commitment_page(page, report_period="July 2026", report_project_id="145891")

    def test_grad_students_encumbered(self, commitments):
        from datetime import date

        from smaug.models import EmployeeType

        names = {c.person_name for c in commitments}
        assert "Ulgen, Ege" in names
        assert "Zhao, Kevin" in names
        assert "Student, Three" in names
        assert "Student, Four" in names
        assert len(commitments) == 6

        by_name = {c.person_name: c for c in commitments}
        ulgen = by_name["Ulgen, Ege"]
        assert ulgen.employee_type == EmployeeType.GRAD_STUDENT
        assert ulgen.salary_committed == Decimal("33333.36")
        assert ulgen.fringe_committed == Decimal("0.00")
        assert ulgen.idc_committed == Decimal("18500.02")
        assert ulgen.encumbrance_start == date(2026, 8, 1)
        assert ulgen.encumbrance_end == date(2027, 3, 31)
