"""
Tests for PDF report parsing.

Uses golden file comparison to verify extraction accuracy.
"""

import json
from decimal import Decimal
from pathlib import Path

import pytest

from smaug.sponsored_report_parsing import parse_sponsored_report

FIXTURES_DIR = Path(__file__).parent / "fixtures"


class TestSponsoredReportParsing:
    """Tests for sponsored PDF report parsing."""

    @pytest.fixture
    def sample_pdf_path(self):
        return FIXTURES_DIR / "sample_sponsored.pdf"

    @pytest.fixture
    def expected_data(self):
        with open(FIXTURES_DIR / "sample_sponsored.json") as f:
            return json.load(f)

    def test_parse_summary(self, sample_pdf_path, expected_data):
        """Test that summary data is correctly extracted."""
        if not sample_pdf_path.exists():
            pytest.skip("Sample PDF not available")

        report, _ = parse_sponsored_report(sample_pdf_path)

        assert report is not None
        assert report.project_id == expected_data["grant_number"]
        assert report.period == expected_data["period"]
        assert report.total_spent == Decimal(expected_data["total_spent"])
        assert report.total_committed == Decimal(expected_data["total_committed"])
        assert report.total_spent_and_committed == Decimal(
            expected_data["total_spent_and_committed"]
        )

    def test_parse_personnel(self, sample_pdf_path, expected_data):
        """Test that personnel data is correctly extracted."""
        if not sample_pdf_path.exists():
            pytest.skip("Sample PDF not available")

        _, personnel = parse_sponsored_report(sample_pdf_path)

        # Check we found expected number of people
        expected_names = {p["name"] for p in expected_data["personnel"]}
        actual_names = {p.person_name for p in personnel}

        assert expected_names == actual_names, f"Missing: {expected_names - actual_names}"

        # Check salary amounts
        expected_salaries = {p["name"]: Decimal(p["salary"]) for p in expected_data["personnel"]}
        for alloc in personnel:
            expected = expected_salaries.get(alloc.person_name)
            if expected:
                assert alloc.salary_amount == expected, (
                    f"{alloc.person_name}: expected {expected}, got {alloc.salary_amount}"
                )


class TestNonSponsoredReportParsing:
    """Tests for non-sponsored (discretionary) PDF parsing."""

    def test_parse_non_sponsored(self):
        """Test basic non-sponsored report parsing."""
        from smaug.sponsored_report_parsing import parse_non_sponsored_report

        # This test requires a real non-sponsored PDF in the data directory.
        # Skip in CI / public builds where no institutional data is available.
        sample_dir = Path(__file__).parent.parent / "data" / "reports" / "non-sponsored"
        if not sample_dir.exists():
            pytest.skip("No non-sponsored report data available")

        pdfs = list(sample_dir.glob("*.pdf"))
        if not pdfs:
            pytest.skip("No non-sponsored PDF files found")

        report = parse_non_sponsored_report(pdfs[0])

        assert report is not None
        assert report.project_id is not None
        assert report.total_spent is not None
