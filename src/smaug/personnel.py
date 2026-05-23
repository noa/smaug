"""
Personnel tracking and effort validation.

Tracks lab personnel effort across split-funded projects and validates
that allocations are reasonable.
"""

from collections import defaultdict
from decimal import Decimal

from .models import EffortAllocation, EffortWarning, EmployeeType


class PersonnelTracker:
    """
    Tracks and validates personnel effort across projects.
    """

    def __init__(self):
        # Map: person_name -> list of EffortAllocation
        self._allocations: dict[str, list[EffortAllocation]] = defaultdict(list)

    def add_allocation(self, allocation: EffortAllocation) -> None:
        """Add an effort allocation."""
        self._allocations[allocation.person_name].append(allocation)

    def add_allocations(self, allocations: list[EffortAllocation]) -> None:
        """Add multiple effort allocations."""
        for alloc in allocations:
            self.add_allocation(alloc)

    def get_all_personnel(self) -> list[str]:
        """Get list of all tracked personnel names."""
        return sorted(self._allocations.keys())

    def get_person_effort(self, name: str, period: str | None = None) -> list[EffortAllocation]:
        """
        Get effort allocations for a person.

        Args:
            name: Person's name
            period: Optional period filter (e.g., "September 2025")

        Returns:
            List of EffortAllocation for this person
        """
        allocations = self._allocations.get(name, [])
        if period:
            allocations = [a for a in allocations if a.period == period]
        return allocations

    def get_project_personnel(
        self, project_id: str, period: str | None = None
    ) -> list[EffortAllocation]:
        """
        Get all personnel allocations for a project.

        Args:
            project_id: Grant number or funded program ID
            period: Optional period filter

        Returns:
            List of EffortAllocation for this project
        """
        result = []
        for allocations in self._allocations.values():
            for alloc in allocations:
                if alloc.project_id == project_id and (period is None or alloc.period == period):
                    result.append(alloc)
        return result

    def get_periods(self) -> list[str]:
        """Get all unique periods with allocations."""
        periods = set()
        for allocations in self._allocations.values():
            for alloc in allocations:
                periods.add(alloc.period)
        return sorted(periods)

    def get_person_total_by_period(self, name: str) -> dict[str, Decimal]:
        """
        Get total salary by period for a person across all projects.

        Returns:
            Dict mapping period -> total salary
        """
        totals: defaultdict[str, Decimal] = defaultdict(Decimal)
        for alloc in self._allocations.get(name, []):
            totals[alloc.period] += alloc.salary_amount
        return dict(totals)

    def get_person_by_project(self, name: str) -> dict[str, Decimal]:
        """
        Get total salary by project for a person.

        Returns:
            Dict mapping project_id -> total salary
        """
        totals: defaultdict[str, Decimal] = defaultdict(Decimal)
        for alloc in self._allocations.get(name, []):
            totals[alloc.project_id] += alloc.salary_amount
        return dict(totals)

    def validate_effort(self, period: str | None = None) -> list[EffortWarning]:
        """
        Validate effort allocations for potential issues.

        Checks for:
        - Employee type mismatches across projects
        - Suspiciously high total salaries (potential over-commitment)

        Args:
            period: Optional period to validate (validates all if None)

        Returns:
            List of EffortWarning objects
        """
        warnings = []

        for name, allocations in self._allocations.items():
            if period:
                allocations = [a for a in allocations if a.period == period]

            if not allocations:
                continue

            # Check employee type consistency
            types = set(
                a.employee_type for a in allocations if a.employee_type != EmployeeType.UNKNOWN
            )
            if len(types) > 1:
                warnings.append(
                    EffortWarning(
                        person_name=name,
                        period=period or "all",
                        warning_type="employee_type_mismatch",
                        message=f"Multiple employee types found: {', '.join(t.value for t in types)}",
                    )
                )

            # Group by period and check totals
            period_totals: defaultdict[str, Decimal] = defaultdict(Decimal)
            for alloc in allocations:
                period_totals[alloc.period] += alloc.salary_amount

            # Flag if same person appears on many projects in same period
            for p, _total in period_totals.items():
                period_allocs = [a for a in allocations if a.period == p]
                if len(set(a.project_id for a in period_allocs)) > 3:
                    warnings.append(
                        EffortWarning(
                            person_name=name,
                            period=p,
                            warning_type="many_projects",
                            message=f"Allocated to {len(set(a.project_id for a in period_allocs))} projects",
                        )
                    )

        return warnings

    def to_dict(self) -> dict:
        """Serialize all allocations to a dict for JSON export."""
        result = {}
        for name, allocations in self._allocations.items():
            result[name] = [
                {
                    "person_name": a.person_name,
                    "project_id": a.project_id,
                    "period": a.period,
                    "salary_amount": str(a.salary_amount),
                    "employee_type": a.employee_type.value,
                    "effort_pct": str(a.effort_pct) if a.effort_pct else None,
                }
                for a in allocations
            ]
        return result
