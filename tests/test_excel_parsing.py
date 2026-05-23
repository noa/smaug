"""
Tests for Excel budget parsing.
"""

from decimal import Decimal
from pathlib import Path

import pytest

from smaug.excel_budget_parsing import parse_budget_file


class TestExcelBudgetParsing:
    """Tests for Excel budget file parsing."""

    @pytest.fixture
    def arts_budget_path(self):
        return Path("jhu/projects/ARTS/ARTS_Updated_budget_July_2025.xlsx")

    def test_parse_combined_sheet(self, arts_budget_path):
        """Test parsing the Combined sheet from budget file."""
        if not arts_budget_path.exists():
            pytest.skip("Budget file not available")

        budget = parse_budget_file(arts_budget_path)

        assert budget is not None
        assert budget.project_id == "ARTS"

        # Check totals are reasonable
        assert budget.total_budget > Decimal("1000000")  # > $1M
        assert budget.total_direct_costs > Decimal("500000")  # > $500k
        assert budget.total_indirect_costs > Decimal("100000")  # > $100k

        # Check we have budget lines
        assert len(budget.lines) > 0

        # Check categories exist
        categories = {line.category for line in budget.lines}
        assert "Personnel" in categories
        assert "Equipment" in categories
        assert "Travel" in categories

    def test_budget_year_breakdown(self, arts_budget_path):
        """Test that we have multiple years in budget."""
        if not arts_budget_path.exists():
            pytest.skip("Budget file not available")

        budget = parse_budget_file(arts_budget_path)
        assert budget is not None

        years = {line.year for line in budget.lines}
        assert len(years) >= 2, "Expected at least 2 years of budget"
