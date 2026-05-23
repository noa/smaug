"""Tests for the report validation module."""

from decimal import Decimal
from pathlib import Path

from smaug.models import SpendingReport
from smaug.validation import validate_report


def _make_report(**kwargs) -> SpendingReport:
    """Helper to build a SpendingReport with sensible defaults."""
    return SpendingReport(
        project_id=str(kwargs.get("project_id", "TEST")),
        period=str(kwargs.get("period", "March 2026")),
        year=int(kwargs.get("year", 2026)),
        month=int(kwargs.get("month", 3)),
        total_spent=Decimal(str(kwargs.get("total_spent", "100000"))),
        total_committed=Decimal(str(kwargs.get("total_committed", "5000"))),
        total_spent_and_committed=Decimal(str(kwargs.get("total_spent_and_committed", "105000"))),
        salary_spent=Decimal(str(kwargs.get("salary_spent", "50000"))),
        fringe_spent=Decimal(str(kwargs.get("fringe_spent", "12000"))),
        tuition_spent=Decimal(str(kwargs.get("tuition_spent", "8000"))),
        insurance_spent=Decimal(str(kwargs.get("insurance_spent", "2000"))),
        service_center_spent=Decimal(str(kwargs.get("service_center_spent", "0"))),
        travel_spent=Decimal(str(kwargs.get("travel_spent", "3000"))),
        other_spent=Decimal(str(kwargs.get("other_spent", "1000"))),
        indirect_spent=Decimal(str(kwargs.get("indirect_spent", "24000"))),
    )


FAKE_PATH = Path("test_report.pdf")


class TestHardErrors:
    """Tests for conditions that should reject the report."""

    def test_zero_year_rejected(self):
        report = _make_report(year=0)
        result = validate_report(report, FAKE_PATH)
        assert not result.is_valid
        assert any(w.code == "INVALID_DATE" for w in result.errors)

    def test_zero_month_rejected(self):
        report = _make_report(month=0)
        result = validate_report(report, FAKE_PATH)
        assert not result.is_valid

    def test_month_out_of_range(self):
        report = _make_report(month=13)
        result = validate_report(report, FAKE_PATH)
        assert not result.is_valid
        assert any(w.code == "MONTH_OUT_OF_RANGE" for w in result.errors)

    def test_unknown_project_rejected(self):
        report = _make_report(project_id="unknown")
        result = validate_report(report, FAKE_PATH)
        assert not result.is_valid
        assert any(w.code == "UNKNOWN_PROJECT" for w in result.errors)

    def test_empty_project_rejected(self):
        report = _make_report(project_id="")
        result = validate_report(report, FAKE_PATH)
        assert not result.is_valid

    def test_unknown_period_rejected(self):
        report = _make_report(period="Unknown")
        result = validate_report(report, FAKE_PATH)
        assert not result.is_valid
        assert any(w.code == "UNKNOWN_PERIOD" for w in result.errors)


class TestWarnings:
    """Tests for conditions that warn but don't reject."""

    def test_valid_report_passes(self):
        report = _make_report()
        result = validate_report(report, FAKE_PATH)
        assert result.is_valid

    def test_negative_spent_warns(self):
        report = _make_report(total_spent=Decimal("-500"))
        result = validate_report(report, FAKE_PATH)
        assert result.is_valid  # Warning, not error
        assert any(w.code == "NEGATIVE_SPENT" for w in result.warnings)

    def test_total_mismatch_warns(self):
        report = _make_report(
            total_spent=Decimal("100000"),
            total_committed=Decimal("5000"),
            total_spent_and_committed=Decimal("110000"),  # Wrong: should be 105000
        )
        result = validate_report(report, FAKE_PATH)
        assert result.is_valid
        assert any(w.code == "TOTAL_MISMATCH" for w in result.warnings)

    def test_total_mismatch_within_tolerance(self):
        """$1 or less difference should not trigger a warning."""
        report = _make_report(
            total_spent=Decimal("100000"),
            total_committed=Decimal("5000"),
            total_spent_and_committed=Decimal("105000.50"),
        )
        result = validate_report(report, FAKE_PATH)
        assert not any(w.code == "TOTAL_MISMATCH" for w in result.warnings)

    def test_category_sum_mismatch_warns(self):
        report = _make_report(
            total_spent=Decimal("100000"),
            salary_spent=Decimal("10000"),
            fringe_spent=Decimal("0"),
            tuition_spent=Decimal("0"),
            insurance_spent=Decimal("0"),
            service_center_spent=Decimal("0"),
            travel_spent=Decimal("0"),
            other_spent=Decimal("0"),
            indirect_spent=Decimal("0"),
        )
        result = validate_report(report, FAKE_PATH)
        assert any(w.code == "CATEGORY_SUM_MISMATCH" for w in result.warnings)

    def test_all_zeros_warns(self):
        report = _make_report(
            total_spent=Decimal("0"),
            total_committed=Decimal("0"),
            total_spent_and_committed=Decimal("0"),
        )
        result = validate_report(report, FAKE_PATH)
        assert any(w.code == "ALL_ZEROS" for w in result.warnings)


class TestMonotonicity:
    """Tests for cumulative total_spent monotonicity checks."""

    def test_increasing_ok(self):
        prior = _make_report(year=2026, month=2, total_spent=Decimal("90000"))
        current = _make_report(year=2026, month=3, total_spent=Decimal("100000"))
        result = validate_report(current, FAKE_PATH, prior_reports=[prior])
        assert not any(w.code == "NON_MONOTONIC" for w in result.warnings)

    def test_decrease_warns(self):
        prior = _make_report(year=2026, month=2, total_spent=Decimal("110000"))
        current = _make_report(year=2026, month=3, total_spent=Decimal("100000"))
        result = validate_report(current, FAKE_PATH, prior_reports=[prior])
        assert any(w.code == "NON_MONOTONIC" for w in result.warnings)

    def test_no_prior_reports(self):
        """No priors should not crash or warn about monotonicity."""
        report = _make_report()
        result = validate_report(report, FAKE_PATH, prior_reports=[])
        assert not any(w.code == "NON_MONOTONIC" for w in result.warnings)


class TestValidationResult:
    """Tests for ValidationResult properties."""

    def test_is_valid_with_only_warnings(self):
        report = _make_report(total_spent=Decimal("-1"))
        result = validate_report(report, FAKE_PATH)
        # Negative spent is a warning, not an error
        assert result.is_valid
        assert len(result.warnings) > 0

    def test_errors_property(self):
        report = _make_report(year=0, project_id="unknown")
        result = validate_report(report, FAKE_PATH)
        assert len(result.errors) >= 2
