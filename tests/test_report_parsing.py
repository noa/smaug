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
#
# These fixtures reproduce the real JHU report layout with substituted names
# and amounts. Two properties of that layout drive the parser design:
#
#   1. Summary tables are right-aligned with genuinely empty cells. A category
#      with no charge this month prints three numbers, not five, so the columns
#      can only be recovered from word geometry.
#   2. Salary rows carry a text G/L label ("SAL-FACULTY FT/PT"), a single
#      end-of-pay-period date, and a wage type -- there is no numeric G/L
#      header, and no Doc column.


def _mock_positional_page(text: str, rows: list[tuple[float, list[tuple[str, float, float]]]]):
    """
    Mock page exposing both text and word geometry.

    ``rows`` is a list of (top, [(text, x0, x1), ...]).
    """
    page = MagicMock()
    page.extract_text.return_value = text
    words = [
        {"text": t, "x0": x0, "x1": x1, "top": top} for top, row in rows for (t, x0, x1) in row
    ]
    page.extract_words.return_value = words
    return page


# Right-edge positions of the seven summary columns, matching the real report.
_COL = {
    "budget": (203.0, 250.0),
    "month": (285.0, 320.0),
    "spent": (360.0, 400.0),
    "committed": (455.0, 495.0),
    "both": (560.0, 600.0),
    "balance": (640.0, 686.0),
    "pct": (742.0, 770.0),
}

_EXPENDITURE_HEADER = [
    ("Expenditures", 18.0, 68.7),
    ("Budget", 224.8, 252.3),
    ("July", 286.7, 302.7),
    ("2026", 304.9, 322.7),
    ("Total", 354.0, 375.0),
    ("Spent", 378.0, 403.0),
    ("Total", 433.9, 453.0),
    ("Committed", 455.2, 497.0),
    ("Total", 507.1, 526.2),
    ("Spent", 528.4, 550.6),
    ("&", 552.8, 558.6),
    ("Committed", 560.8, 602.6),
    ("Budget", 628.3, 655.9),
    ("Balance", 658.1, 688.8),
    ("Budget", 711.4, 738.9),
    ("Utilized", 741.1, 769.6),
]

_REVENUE_HEADER = [
    ("Revenue", 18.0, 51.4),
    ("Budget", 224.8, 252.3),
    ("July", 286.7, 302.7),
    ("2026", 304.9, 322.7),
    ("Total", 346.2, 365.4),
    ("Received", 367.6, 402.7),
    ("Total", 440.1, 459.2),
    ("Expected", 461.4, 497.0),
    ("Total", 513.7, 532.8),
    ("Rcvd.", 535.0, 556.8),
    ("&", 559.1, 564.8),
    ("Expected", 567.1, 602.6),
    ("Budget", 628.3, 655.9),
    ("Balance", 658.1, 688.8),
    ("Budget", 704.6, 732.2),
    ("Received", 734.4, 769.6),
]


def _cells(label_words, **values):
    """Build a data row: label words plus numeric cells in named columns."""
    row = list(label_words)
    for key, text in values.items():
        x0, x1 = _COL[key]
        row.append((text, x0, x1))
    return row


REAL_LAYOUT_SUMMARY_TEXT = """\
Sponsored PI Summary Report Direct Cost Balance: (68,611.59)
July 2026 Over Committed: (106,691.02)
Sponsored Program: 90109289 - B661547 Grant: 145891 - IARPA ARTS Project
PI For Sponsored Program: Doe, Jane (114605) Grantor Code: Example National Laboratory \
Budget Begin Date: 02/06/2024
Responsible Cost Center: 2110000000 - CTR Award ID: B661547 Budget End Date: 03/31/2027
Program FA Function: ORGANIZED RESEARCH Grant Project End Date: 03/31/2027
F&A Rate: 55.50 Payment Method: MONL Grant Status: Approved Award
Revenue Budget July 2026 Total Received Total Expected Total Rcvd. & Expected Budget Balance
Sponsored Revenue 1,768,083.01 107,213.11 1,619,296.12 1,619,296.12 148,786.89 91.6%
Expenditures Budget July 2026 Total Spent Total Committed Total Spent & Committed Budget Balance
Salaries & Wages 38,037.57 713,541.51 152,791.88 866,333.39 (866,333.39)
Supplies & Materials 4,848.99 4,848.99 (4,848.99)
Total Expenditures 1,768,083.01 72,571.08 1,619,296.12 255,477.91 1,874,774.03 (106,691.02) 106.0%
"""


@pytest.fixture
def real_layout_summary():
    rows = [
        (159.1, _REVENUE_HEADER),
        (
            173.8,
            _cells(
                [("Sponsored", 18.0, 56.7), ("Revenue", 58.9, 90.9)],
                budget="1,768,083.01",
                month="107,213.11",
                spent="1,619,296.12",
                both="1,619,296.12",
                balance="148,786.89",
                pct="91.6%",
            ),
        ),
        (215.8, _EXPENDITURE_HEADER),
        (
            247.3,
            _cells(
                [("Salaries", 18.0, 46.9), ("&", 49.1, 54.5), ("Wages", 56.7, 81.6)],
                month="38,037.57",
                spent="713,541.51",
                committed="152,791.88",
                both="866,333.39",
                balance="(866,333.39)",
            ),
        ),
        # No charge this month: the month cell is absent, not zero-filled.
        (
            275.2,
            _cells(
                [("Supplies", 18.0, 48.7), ("&", 50.9, 56.2), ("Materials", 58.5, 90.9)],
                spent="4,848.99",
                both="4,848.99",
                balance="(4,848.99)",
            ),
        ),
        (
            412.4,
            _cells(
                [("Total", 18.0, 37.1), ("Expenditures", 39.3, 90.0)],
                budget="1,768,083.01",
                month="72,571.08",
                spent="1,619,296.12",
                committed="255,477.91",
                both="1,874,774.03",
                balance="(106,691.02)",
                pct="106.0%",
            ),
        ),
    ]
    page = _mock_positional_page(REAL_LAYOUT_SUMMARY_TEXT, rows)
    return parse_sponsored_summary(page)


class TestPositionalSummaryParsing:
    def test_period(self, real_layout_summary):
        assert real_layout_summary["period"] == "July 2026"

    def test_totals(self, real_layout_summary):
        assert real_layout_summary["total_month"] == Decimal("72571.08")
        assert real_layout_summary["total_spent"] == Decimal("1619296.12")
        assert real_layout_summary["total_committed"] == Decimal("255477.91")
        assert real_layout_summary["total_spent_and_committed"] == Decimal("1874774.03")

    def test_populated_category_row(self, real_layout_summary):
        assert real_layout_summary["salary_month"] == Decimal("38037.57")
        assert real_layout_summary["salary_spent"] == Decimal("713541.51")
        assert real_layout_summary["salary_committed"] == Decimal("152791.88")

    def test_blank_month_cell_is_zero_not_shifted(self, real_layout_summary):
        """A category with no charge this month must not borrow the next column."""
        assert real_layout_summary["supplies_month"] == Decimal("0")
        assert real_layout_summary["supplies_spent"] == Decimal("4848.99")
        assert real_layout_summary["supplies_committed"] == Decimal("0")

    def test_revenue_columns(self, real_layout_summary):
        # The Revenue "Budget" column is the funded ceiling; "Total Received"
        # is a separate, smaller figure.
        assert real_layout_summary["funded_ceiling"] == Decimal("1768083.01")
        assert real_layout_summary["total_revenue_received"] == Decimal("1619296.12")
        assert real_layout_summary["revenue_month"] == Decimal("107213.11")

    def test_award_metadata(self, real_layout_summary):
        from datetime import date

        assert real_layout_summary["budget_start_date"] == date(2024, 2, 6)
        assert real_layout_summary["budget_end_date"] == date(2027, 3, 31)
        assert real_layout_summary["grant_end_date"] == date(2027, 3, 31)
        assert real_layout_summary["stated_idc_rate"] == Decimal("55.50")

    def test_grantor_code_keeps_full_name(self, real_layout_summary):
        """The grantor name shares a line with the next label and must not be cut short."""
        assert real_layout_summary["grantor_code"] == "Example National Laboratory"


REAL_LAYOUT_PERSONNEL_PAGE = """\
Sponsored PI Salary Report
July 2026
Sponsored Program: 90109289 - B661547 Grant: 145891 - IARPA ARTS Project
Employee G/L Account End of Pay Period Wage Type Pay Period Salary
Doe, Jane SAL-FACULTY FT/PT 03/15/2026 Salary 1,974.75
Doe, Jane SAL-FACULTY FT/PT 07/31/2026 Salary 937.50
Total for Doe, Jane 2,912.25
Roe, Richard Quentin SAL-FAC TLC 01/15/2026 PtInstSl 365.21
Roe, Richard Quentin SAL-FAC TLC 06/30/2026 PtInstSl 365.21
Total for Roe, Richard Quentin 730.42
Poe, Edgar SAL-STUDENT GRAD 07/15/2026 Salary 2,166.67
Total for Poe, Edgar 2,166.67
Total Salaries 5,809.34
"""


class TestRealLayoutPersonnelPage:
    @pytest.fixture
    def personnel(self):
        page = _mock_page(REAL_LAYOUT_PERSONNEL_PAGE)
        return parse_personnel_page(page, report_period="July 2026", report_project_id="145891")

    def test_all_people_found(self, personnel):
        assert {p.person_name for p in personnel} == {
            "Doe, Jane",
            "Roe, Richard Quentin",
            "Poe, Edgar",
        }

    def test_totals_are_authoritative(self, personnel):
        by_name = {p.person_name: p for p in personnel}
        assert by_name["Doe, Jane"].salary_amount == Decimal("2912.25")
        assert by_name["Roe, Richard Quentin"].salary_amount == Decimal("730.42")

    def test_gl_wage_type_and_pay_periods(self, personnel):
        from datetime import date

        jane = {p.person_name: p for p in personnel}["Doe, Jane"]
        assert jane.gl_account == "SAL-FACULTY FT/PT"
        assert jane.wage_type == "Salary"
        # Charges reach back to March: retroactive, not current-period.
        assert jane.pay_period_start == date(2026, 3, 15)
        assert jane.pay_period_end == date(2026, 7, 31)

    def test_multiword_surname_is_not_split_into_the_gl_label(self, personnel):
        richard = {p.person_name: p for p in personnel}["Roe, Richard Quentin"]
        assert richard.gl_account == "SAL-FAC TLC"
        assert richard.wage_type == "PtInstSl"

    def test_employee_types(self, personnel):
        from smaug.models import EmployeeType

        by_name = {p.person_name: p for p in personnel}
        assert by_name["Doe, Jane"].employee_type == EmployeeType.FACULTY
        # "SAL-FAC TLC" is the abbreviated faculty account, not an unknown one.
        assert by_name["Roe, Richard Quentin"].employee_type == EmployeeType.FACULTY
        assert by_name["Poe, Edgar"].employee_type == EmployeeType.GRAD_STUDENT


REAL_LAYOUT_COMMITMENT_PAGE = """\
Sponsored PI Salary Commitment Report
July 2026
Sponsored Program: 90109289 - B661547 Grant: 145891 - IARPA ARTS Project
Employee Commitment Start Commitment End Commitment
G/L Account
Doe, Jane SALARY-FACULTY FT/PT August-2026 December-2026 9,375.00
Poe, Edgar SALARY-STUDENT GRADUATE August-2026 March-2027 31,416.72
Moe, Larry SALARY-STUDENT GRADUATE August-2026 March-2027 34,666.72
Total Commitments
75,458.44
"""


class TestRealLayoutCommitmentPage:
    @pytest.fixture
    def commitments(self):
        page = _mock_page(REAL_LAYOUT_COMMITMENT_PAGE)
        return parse_commitment_page(page, report_period="July 2026", report_project_id="145891")

    def test_all_commitments_found(self, commitments):
        assert {c.person_name for c in commitments} == {"Doe, Jane", "Poe, Edgar", "Moe, Larry"}

    def test_total_line_is_not_a_person(self, commitments):
        assert len(commitments) == 3

    def test_month_granularity_window_runs_to_month_end(self, commitments):
        from datetime import date

        edgar = {c.person_name: c for c in commitments}["Poe, Edgar"]
        assert edgar.salary_committed == Decimal("31416.72")
        assert edgar.encumbrance_start == date(2026, 8, 1)
        assert edgar.encumbrance_end == date(2027, 3, 31)

    def test_employee_type_from_gl_label(self, commitments):
        from smaug.models import EmployeeType

        by_name = {c.person_name: c for c in commitments}
        assert by_name["Doe, Jane"].employee_type == EmployeeType.FACULTY
        assert by_name["Poe, Edgar"].employee_type == EmployeeType.GRAD_STUDENT
