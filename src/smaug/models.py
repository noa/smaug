"""
Data models for the budget tracking framework.

All models are dataclasses that can be serialized to/from JSON for persistence
and manual inspection.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date as _date
from decimal import Decimal
from enum import Enum

# Type alias to avoid shadowing in ExpenseItem where field 'date' shadows the import
Date = _date


class EmployeeType(Enum):
    """Employee classification for effort tracking."""

    FACULTY = "faculty"
    POSTDOC = "postdoc"
    GRAD_STUDENT = "grad_student"
    MASTERS_STUDENT = "masters_student"
    STAFF = "staff"
    UNKNOWN = "unknown"


class TravelStatus(Enum):
    """Status of a travel budget item."""

    ESTIMATED = "estimated"
    ACTUALIZED = "actualized"


class ProjectType(Enum):
    """Distinguishes sponsored research from discretionary accounts."""

    SPONSORED = "sponsored"
    DISCRETIONARY = "discretionary"


class ProjectStatus(Enum):
    """Lifecycle status for a project.

    Sponsored projects follow: proposed → accepted → active → completed.
    Discretionary accounts are always active or completed.
    """

    PROPOSED = "proposed"
    ACCEPTED = "accepted"
    ACTIVE = "active"
    COMPLETED = "completed"


@dataclass
class Project:
    """A research project or discretionary account."""

    short_name: str
    name: str
    pi: str
    project_type: ProjectType
    status: ProjectStatus = ProjectStatus.ACTIVE

    # Identifiers (sponsored projects)
    grant_number: str | None = None
    sponsored_program: str | None = None
    award_id: str | None = None

    # Identifiers (discretionary accounts)
    funded_program: str | None = None
    fund_center: str | None = None

    # Dates
    start_date: Date | None = None
    end_date: Date | None = None

    # Budget (from manifest, used when no Excel file)
    total_budget: Decimal | None = None

    # File locations
    budget_dir: str | None = None
    reports_dir: str | None = None


@dataclass
class BudgetLine:
    """A single budget line item for a category and year."""

    category: str
    year: int
    amount: Decimal


@dataclass
class ProjectBudget:
    """Complete budget for a project across all years."""

    project_id: str
    lines: list[BudgetLine] = field(default_factory=list)
    total_direct_costs: Decimal = Decimal("0")
    total_indirect_costs: Decimal = Decimal("0")
    total_budget: Decimal = Decimal("0")

    def get_year_total(self, year: int) -> Decimal:
        """Get total budget for a specific year."""
        return sum((line.amount for line in self.lines if line.year == year), Decimal("0"))


@dataclass
class Expense:
    """A single expense transaction."""

    date: Date
    category: str
    amount: Decimal
    vendor: str | None = None
    description: str | None = None
    ref_doc: str | None = None


@dataclass
class CommitmentDetail:
    """Per-person commitment from the Salary Commitment Report."""

    person_name: str
    employee_type: EmployeeType = EmployeeType.UNKNOWN
    salary_committed: Decimal = Decimal("0")
    fringe_committed: Decimal = Decimal("0")
    idc_committed: Decimal = Decimal("0")
    encumbrance_start: Date | None = None
    encumbrance_end: Date | None = None


@dataclass
class SpendingReport:
    """Monthly spending report for a project."""

    project_id: str
    period: str  # e.g., "September 2025"
    year: int
    month: int

    # Summary totals
    total_spent: Decimal = Decimal("0")
    total_committed: Decimal = Decimal("0")
    total_spent_and_committed: Decimal = Decimal("0")
    indirect_spent: Decimal = Decimal("0")
    budget_utilized_pct: Decimal | None = None
    total_month: Decimal | None = None

    # Category breakdowns (cumulative "Total Spent" per category)
    salary_spent: Decimal = Decimal("0")
    fringe_spent: Decimal = Decimal("0")
    tuition_spent: Decimal = Decimal("0")
    insurance_spent: Decimal = Decimal("0")
    service_center_spent: Decimal = Decimal("0")  # Cloud compute / HPC
    travel_spent: Decimal = Decimal("0")  # Travel Domestic
    travel_foreign_spent: Decimal = Decimal("0")
    supplies_spent: Decimal = Decimal("0")  # Supplies & Materials
    equipment_spent: Decimal = Decimal("0")  # Capital Equipment
    subcontracts_spent: Decimal = Decimal("0")
    consultant_spent: Decimal = Decimal("0")
    other_spent: Decimal = Decimal("0")

    # Monthly (single-month) category amounts from report
    salary_month: Decimal | None = None
    fringe_month: Decimal | None = None
    tuition_month: Decimal | None = None
    insurance_month: Decimal | None = None
    service_center_month: Decimal | None = None
    travel_month: Decimal | None = None
    travel_foreign_month: Decimal | None = None
    supplies_month: Decimal | None = None
    equipment_month: Decimal | None = None
    subcontracts_month: Decimal | None = None
    consultant_month: Decimal | None = None
    other_month: Decimal | None = None
    indirect_month: Decimal | None = None

    # Category commitments
    salary_committed: Decimal = Decimal("0")
    fringe_committed: Decimal = Decimal("0")
    tuition_committed: Decimal = Decimal("0")
    insurance_committed: Decimal = Decimal("0")
    service_center_committed: Decimal = Decimal("0")
    travel_committed: Decimal = Decimal("0")
    travel_foreign_committed: Decimal = Decimal("0")
    supplies_committed: Decimal = Decimal("0")
    equipment_committed: Decimal = Decimal("0")
    subcontracts_committed: Decimal = Decimal("0")
    consultant_committed: Decimal = Decimal("0")
    other_committed: Decimal = Decimal("0")

    # Funded ceiling and revenue from report
    funded_ceiling: Decimal | None = None
    total_revenue_received: Decimal | None = None
    revenue_month: Decimal | None = None

    # Award metadata
    budget_start_date: Date | None = None
    budget_end_date: Date | None = None
    grant_end_date: Date | None = None
    grantor_code: str | None = None
    stated_idc_rate: Decimal | None = None

    # Detailed commitments & transactions
    commitment_details: list[CommitmentDetail] = field(default_factory=list)
    expenses: list[Expense] = field(default_factory=list)


@dataclass
class Person:
    """A lab member who may have effort on multiple projects."""

    name: str
    employee_type: EmployeeType = EmployeeType.UNKNOWN


@dataclass
class EffortAllocation:
    """Salary/effort allocation for a person on a project for a period."""

    person_name: str
    project_id: str
    period: str  # e.g., "September 2025"
    salary_amount: Decimal
    employee_type: EmployeeType = EmployeeType.UNKNOWN
    effort_pct: Decimal | None = None  # Derived from salary if base known

    # Detail fields from payroll ledger
    gl_account: str | None = None
    wage_type: str | None = None
    pay_period_start: Date | None = None
    pay_period_end: Date | None = None


@dataclass
class EffortWarning:
    """Warning about suspicious effort allocation."""

    person_name: str
    period: str
    warning_type: str  # e.g., "over_commitment", "under_allocation"
    message: str
    total_effort_pct: Decimal | None = None


@dataclass
class TravelItem:
    """A planned or actualized travel expense."""

    project_id: str
    description: str
    date: Date
    amount: Decimal
    traveler: str | None = None
    status: TravelStatus = TravelStatus.ESTIMATED

    def to_dict(self):
        return {
            "project": self.project_id,
            "description": self.description,
            "date": self.date.isoformat() if self.date else None,
            "amount": float(self.amount),
            "traveler": self.traveler,
            "status": self.status.value,
        }


@dataclass
class ExpenseItem:
    """A one-time or recurring expense (e.g., equipment, cloud compute)."""

    project_id: str
    description: str
    amount: Decimal
    category: str = "Other"
    date: Date | None = None  # For one-time
    start_date: Date | None = None  # For recurring
    end_date: Date | None = None  # For recurring

    @property
    def is_recurring(self) -> bool:
        return self.start_date is not None

    def to_dict(self):
        data = {
            "project": self.project_id,
            "description": self.description,
            "amount": float(self.amount),
            "category": self.category,
        }
        if self.date:
            data["date"] = self.date.isoformat()
        if self.start_date:
            data["start"] = self.start_date.isoformat()
        if self.end_date:
            data["end"] = self.end_date.isoformat()
        return data


@dataclass
class Invoice:
    """A sponsor invoice (billing request) for a project period."""

    project_id: str
    invoice_number: str
    invoice_date: Date
    period_start: Date
    period_end: Date

    # Subcontract reference
    subcontract_no: str | None = None
    grant_number: str | None = None

    # From summary table
    previous_expense: Decimal = Decimal("0")
    current_expense: Decimal = Decimal("0")
    cumulative_expense: Decimal = Decimal("0")

    # Budget reference
    budget_total: Decimal = Decimal("0")

    # Category breakdown (cumulative amounts)
    categories: dict[str, Decimal] = field(default_factory=dict)

    # Personnel detail (if available on backup pages)
    personnel: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "project": self.project_id,
            "invoice_number": self.invoice_number,
            "invoice_date": self.invoice_date.isoformat() if self.invoice_date else None,
            "period_start": self.period_start.isoformat() if self.period_start else None,
            "period_end": self.period_end.isoformat() if self.period_end else None,
            "subcontract_no": self.subcontract_no,
            "grant_number": self.grant_number,
            "previous_expense": float(self.previous_expense),
            "current_expense": float(self.current_expense),
            "cumulative_expense": float(self.cumulative_expense),
            "budget_total": float(self.budget_total),
            "categories": {k: float(v) for k, v in self.categories.items()},
            "personnel": self.personnel,
        }


@dataclass
class ProjectData:
    """Complete data for a project: budget, spending, and personnel."""

    project: Project
    budget: ProjectBudget | None = None
    spending: list[SpendingReport] = field(default_factory=list)
    personnel: list[EffortAllocation] = field(default_factory=list)


# JSON serialization helpers
class DecimalEncoder(json.JSONEncoder):
    """JSON encoder that handles Decimal and date types."""

    def default(self, obj):
        if isinstance(obj, Decimal):
            return str(obj)
        if isinstance(obj, _date):
            return obj.isoformat()
        if isinstance(obj, Enum):
            return obj.value
        return super().default(obj)


def decimal_decoder(dct: dict) -> dict:
    """JSON decoder hook to convert string amounts back to Decimal."""
    for key in [
        "amount",
        "salary_amount",
        "total_spent",
        "total_committed",
        "total_spent_and_committed",
        "indirect_spent",
        "budget_utilized_pct",
        "total_direct_costs",
        "total_indirect_costs",
        "total_budget",
        "effort_pct",
        "total_effort_pct",
        "total_month",
        "salary_spent",
        "fringe_spent",
        "tuition_spent",
        "insurance_spent",
        "service_center_spent",
        "travel_spent",
        "travel_foreign_spent",
        "supplies_spent",
        "equipment_spent",
        "subcontracts_spent",
        "consultant_spent",
        "other_spent",
        "salary_month",
        "fringe_month",
        "tuition_month",
        "insurance_month",
        "service_center_month",
        "travel_month",
        "travel_foreign_month",
        "supplies_month",
        "equipment_month",
        "subcontracts_month",
        "consultant_month",
        "other_month",
        "indirect_month",
        "salary_committed",
        "fringe_committed",
        "idc_committed",
        "tuition_committed",
        "insurance_committed",
        "service_center_committed",
        "travel_committed",
        "travel_foreign_committed",
        "supplies_committed",
        "equipment_committed",
        "subcontracts_committed",
        "consultant_committed",
        "other_committed",
        "funded_ceiling",
        "total_revenue_received",
        "revenue_month",
        "stated_idc_rate",
    ]:
        if key in dct and dct[key] is not None:
            dct[key] = Decimal(dct[key])
    return dct
