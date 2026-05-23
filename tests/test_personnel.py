"""
Tests for personnel tracking and effort validation.
"""

from decimal import Decimal

import pytest

from smaug.models import EffortAllocation, EmployeeType
from smaug.personnel import PersonnelTracker


class TestPersonnelTracker:
    """Tests for PersonnelTracker."""

    @pytest.fixture
    def tracker(self):
        tracker = PersonnelTracker()

        # Add sample allocations
        tracker.add_allocations(
            [
                EffortAllocation(
                    person_name="Smith, John",
                    project_id="PROJ_A",
                    period="September 2025",
                    salary_amount=Decimal("5000.00"),
                    employee_type=EmployeeType.FACULTY,
                ),
                EffortAllocation(
                    person_name="Smith, John",
                    project_id="PROJ_B",
                    period="September 2025",
                    salary_amount=Decimal("3000.00"),
                    employee_type=EmployeeType.FACULTY,
                ),
                EffortAllocation(
                    person_name="Doe, Jane",
                    project_id="PROJ_A",
                    period="September 2025",
                    salary_amount=Decimal("7500.00"),
                    employee_type=EmployeeType.POSTDOC,
                ),
            ]
        )
        return tracker

    def test_get_all_personnel(self, tracker):
        """Test listing all personnel."""
        personnel = tracker.get_all_personnel()
        assert len(personnel) == 2
        assert "Smith, John" in personnel
        assert "Doe, Jane" in personnel

    def test_get_person_effort(self, tracker):
        """Test getting effort for specific person."""
        effort = tracker.get_person_effort("Smith, John")
        assert len(effort) == 2

        total = sum(e.salary_amount for e in effort)
        assert total == Decimal("8000.00")

    def test_get_project_personnel(self, tracker):
        """Test getting personnel for a project."""
        personnel = tracker.get_project_personnel("PROJ_A")
        assert len(personnel) == 2

        names = {p.person_name for p in personnel}
        assert names == {"Smith, John", "Doe, Jane"}

    def test_get_person_by_project(self, tracker):
        """Test aggregating person's salary by project."""
        by_project = tracker.get_person_by_project("Smith, John")

        assert by_project["PROJ_A"] == Decimal("5000.00")
        assert by_project["PROJ_B"] == Decimal("3000.00")

    def test_validate_effort_type_mismatch(self):
        """Test that type mismatches are detected."""
        tracker = PersonnelTracker()

        # Person with different types across projects
        tracker.add_allocations(
            [
                EffortAllocation(
                    person_name="Confused, Chris",
                    project_id="PROJ_A",
                    period="September 2025",
                    salary_amount=Decimal("5000.00"),
                    employee_type=EmployeeType.FACULTY,
                ),
                EffortAllocation(
                    person_name="Confused, Chris",
                    project_id="PROJ_B",
                    period="September 2025",
                    salary_amount=Decimal("3000.00"),
                    employee_type=EmployeeType.POSTDOC,  # Different type!
                ),
            ]
        )

        warnings = tracker.validate_effort()

        assert len(warnings) == 1
        assert warnings[0].warning_type == "employee_type_mismatch"
        assert warnings[0].person_name == "Confused, Chris"
