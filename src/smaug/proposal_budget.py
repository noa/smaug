"""
Proposal budget generation using JHU institutional rates.

Generates multi-year budget tables for research proposals based on
personnel specifications (effort percentages) and current institutional
rates from rates.yaml.
"""

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import yaml


@dataclass
class ProposalPerson:
    """A person or role in a proposal budget."""

    label: str  # Display name (e.g., "Smith (PI)" or "PhD Student #1")
    person_type: str  # faculty, postdoc, staff, grad_student
    effort: Decimal  # 0-1
    annual_salary: Decimal
    months_per_year: int = 12  # Can be less for summer-only etc.
    student_type: str = "phd"  # 'phd' or 'masters' (affects tuition rate)
    include_tuition: bool = True  # Set False to exclude tuition (e.g., self-funded masters)


@dataclass
class YearBudget:
    """Budget for a single year."""

    year_num: int
    salary: Decimal = Decimal("0")
    fringe: Decimal = Decimal("0")
    tuition: Decimal = Decimal("0")
    insurance: Decimal = Decimal("0")
    travel: Decimal = Decimal("0")
    compute: Decimal = Decimal("0")
    annotation: Decimal = Decimal("0")
    equipment: Decimal = Decimal("0")
    other: Decimal = Decimal("0")

    @property
    def total_direct(self) -> Decimal:
        return (
            self.salary
            + self.fringe
            + self.tuition
            + self.insurance
            + self.travel
            + self.compute
            + self.annotation
            + self.equipment
            + self.other
        )

    @property
    def mtdc(self) -> Decimal:
        """Modified Total Direct Costs (base for IDC). Excludes tuition and equipment > $5k."""
        return (
            self.salary
            + self.fringe
            + self.insurance
            + self.travel
            + self.compute
            + self.annotation
            + self.other
        )

    def idc(self, rate: Decimal) -> Decimal:
        return self.mtdc * rate

    def total_with_idc(self, rate: Decimal) -> Decimal:
        return self.total_direct + self.idc(rate)


@dataclass
class PersonYearDetail:
    """Per-person, per-year cost breakdown."""

    label: str
    person_type: str
    effort: Decimal
    salary: Decimal
    fringe: Decimal
    tuition: Decimal = Decimal("0")
    insurance: Decimal = Decimal("0")

    @property
    def total(self) -> Decimal:
        return self.salary + self.fringe + self.tuition + self.insurance


@dataclass
class ProposalBudget:
    """Complete proposal budget across all years."""

    years: list[YearBudget] = field(default_factory=list)
    personnel_detail: dict[int, list[PersonYearDetail]] = field(default_factory=dict)
    idc_rate: Decimal = Decimal("0")
    salary_escalation: Decimal = Decimal("0.03")  # 3% annual raise default

    @property
    def total_direct(self) -> Decimal:
        return sum((y.total_direct for y in self.years), Decimal("0"))

    @property
    def total_idc(self) -> Decimal:
        return sum((y.idc(self.idc_rate) for y in self.years), Decimal("0"))

    @property
    def grand_total(self) -> Decimal:
        return self.total_direct + self.total_idc


def load_proposal_rates(data_dir: str | Path) -> dict:
    """Load institutional rates from rates.yaml (or legacy jhu_rates.yaml)."""
    from .config import get_rates_path

    rates_path = get_rates_path(Path(data_dir))
    if not rates_path.exists():
        raise FileNotFoundError(f"Rates file not found: {rates_path}")

    with open(rates_path) as f:
        return yaml.safe_load(f)  # type: ignore[no-any-return]


def resolve_salary(
    name_pattern: str,
    person_type: str,
    personnel_config_path: Path,
    rates_config: dict,
) -> tuple[Decimal, str]:
    """
    Resolve salary for a person specification.

    If name_pattern matches someone in personnel_config.yaml, use their salary.
    Otherwise use defaults based on type.

    Returns:
        (salary, resolved_label)
    """
    if personnel_config_path.exists():
        with open(personnel_config_path) as f:
            config = yaml.safe_load(f)

        for p in config.get("personnel", []):
            if name_pattern.lower() in p["name"].lower():
                return Decimal(str(p["annual_salary"])), p["name"]

    # Default salaries by type
    gs_costs = rates_config.get("grad_student_costs", {})
    defaults = {
        "grad_student": Decimal(str(gs_costs.get("stipend", 50000))),
        "postdoc": Decimal("70000"),
        "staff": Decimal("60000"),
        "faculty": Decimal("150000"),
    }

    salary = defaults.get(person_type, Decimal("50000"))
    return salary, name_pattern


def generate_proposal_budget(
    people: list[ProposalPerson],
    rates_config: dict,
    num_years: int = 3,
    travel_per_year: Decimal = Decimal("0"),
    compute_per_year: Decimal = Decimal("0"),
    annotation_per_year: Decimal = Decimal("0"),
    equipment_year1: Decimal = Decimal("0"),
    other_per_year: Decimal = Decimal("0"),
    salary_escalation: Decimal = Decimal("0.03"),
) -> ProposalBudget:
    """
    Generate a multi-year proposal budget.

    Args:
        people: List of ProposalPerson specs
        rates_config: Parsed rates.yaml
        num_years: Number of budget years
        travel_per_year: Annual travel budget
        compute_per_year: Annual compute/cloud costs
        equipment_year1: Equipment (year 1 only, excluded from IDC)
        other_per_year: Other direct costs per year
        salary_escalation: Annual salary increase rate (default 3%)

    Returns:
        ProposalBudget with complete breakdown
    """
    idc_rate = Decimal(str(rates_config.get("idc_rate", 0.55)))
    fringe_rates = {k: Decimal(str(v)) for k, v in rates_config.get("fringe_rates", {}).items()}
    gs_costs = rates_config.get("grad_student_costs", {})
    tuition_billing = rates_config.get("tuition_billing", {})

    # PhD tuition: 20% departmental supplement (80% covered by institutional remission)
    # Masters tuition: full tuition charged to grant
    phd_tuition_annual = Decimal(
        str(
            gs_costs.get(
                "phd_tuition",
                tuition_billing.get("per_semester", gs_costs.get("tuition", 0) / 2) * 2,
            )
        )
    )
    masters_tuition_annual = Decimal(
        str(gs_costs.get("masters_tuition", gs_costs.get("full_tuition", 66670)))
    )
    insurance_annual = Decimal(str(gs_costs.get("health_dental", 0)))

    budget = ProposalBudget(idc_rate=idc_rate, salary_escalation=salary_escalation)

    for year_num in range(1, num_years + 1):
        year_budget = YearBudget(year_num=year_num)
        year_details = []
        escalation = (1 + salary_escalation) ** (year_num - 1)

        for person in people:
            # Escalate salary for out years
            escalated_salary = person.annual_salary * Decimal(str(escalation))

            # Pro-rate for effort and months
            months_fraction = Decimal(str(person.months_per_year)) / 12
            salary = escalated_salary * person.effort * months_fraction
            salary = salary.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

            # Fringe
            fringe_rate = fringe_rates.get(person.person_type, Decimal("0.315"))
            if person.student_type == "masters":
                # Only subject to fringe during 3 summer months (June, July, August)
                fringe_rate = fringe_rate * Decimal("3") / Decimal("12")
            fringe = salary * fringe_rate
            fringe = fringe.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

            # Tuition and insurance for students (pro-rated by effort)
            # PhD: 20% supplement only; Masters: full tuition
            tuition = Decimal("0")
            insurance = Decimal("0")
            if person.student_type == "masters" and person.include_tuition:
                tuition = (masters_tuition_annual * person.effort).quantize(
                    Decimal("0.01"), rounding=ROUND_HALF_UP
                )
                insurance = (insurance_annual * person.effort).quantize(
                    Decimal("0.01"), rounding=ROUND_HALF_UP
                )
            elif person.person_type == "grad_student":
                tuition = (phd_tuition_annual * person.effort).quantize(
                    Decimal("0.01"), rounding=ROUND_HALF_UP
                )
                insurance = (insurance_annual * person.effort).quantize(
                    Decimal("0.01"), rounding=ROUND_HALF_UP
                )

            year_budget.salary += salary
            year_budget.fringe += fringe
            year_budget.tuition += tuition
            year_budget.insurance += insurance

            year_details.append(
                PersonYearDetail(
                    label=person.label,
                    person_type=person.person_type,
                    effort=person.effort,
                    salary=salary,
                    fringe=fringe,
                    tuition=tuition,
                    insurance=insurance,
                )
            )

        year_budget.travel = travel_per_year
        year_budget.compute = compute_per_year
        year_budget.annotation = annotation_per_year
        year_budget.equipment = equipment_year1 if year_num == 1 else Decimal("0")
        year_budget.other = other_per_year

        budget.years.append(year_budget)
        budget.personnel_detail[year_num] = year_details

    return budget
