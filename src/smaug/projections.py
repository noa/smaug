"""
Spending projections based on personnel configuration.

Calculates monthly burn rate and projects spending through specified dates.
"""

import copy
import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path

import yaml

from .models import ExpenseItem, TravelItem
from .store import ProjectStore


@dataclass
class Rates:
    """Current institutional rates."""

    idc: Decimal
    fringe: dict[str, Decimal]  # type -> rate
    # Grad student costs (per semester for tuition, annual for insurance)
    tuition_per_semester: Decimal = Decimal("0")
    insurance_annual: Decimal = Decimal("0")
    tuition_months: list[int] | None = None  # Months when tuition is billed (e.g., [1, 9])
    masters_tuition_per_semester: Decimal = Decimal("0")
    masters_hourly_default: Decimal = Decimal("20")
    masters_hours_per_week_default: Decimal = Decimal("20")
    masters_max_hours_per_week: Decimal = Decimal("19.9")


@dataclass
class Assignment:
    """A personnel assignment to a project."""

    project: str
    effort: Decimal
    start: date | None = None
    end: date | None = None


@dataclass
class SalaryRecord:
    """A salary record with optional start and end dates."""

    amount: Decimal
    start: date | None = None
    end: date | None = None


@dataclass
class PersonnelEntry:
    """A person with their salary and project assignments."""

    name: str
    person_type: str
    annual_salary: Decimal
    assignments: list[Assignment]
    departure: date | None = None  # Overall end date (leaves university)
    salaries: list[SalaryRecord] = field(default_factory=list)
    hourly_rate: Decimal | None = None
    hours_per_week: Decimal | None = None
    include_tuition: bool = True
    include_insurance: bool = True


@dataclass
class MonthlyProjection:
    """Projected costs for a single month."""

    year: int
    month: int
    direct_salary: Decimal
    fringe: Decimal
    indirect: Decimal
    total: Decimal
    personnel: list[tuple[str, Decimal]]  # (name, amount)
    tuition: Decimal = Decimal("0")  # Grad student tuition (billed in Jan/Sep)
    insurance: Decimal = Decimal("0")  # Grad student health insurance (monthly)
    travel: Decimal = Decimal("0")
    compute: Decimal = Decimal("0")
    equipment: Decimal = Decimal("0")
    other_direct: Decimal = Decimal("0")
    travel_detail: list[TravelItem] | None = None
    expense_detail: list[ExpenseItem] | None = None


@dataclass
class Hypothetical:
    """A hypothetical scenario override for what-if analysis.

    Types:
    - Override existing person: name_pattern set, is_addition=False
    - Add generic role: person_type set, is_addition=True
    """

    is_addition: bool = False  # True = add new person, False = override existing
    name_pattern: str = ""  # For overrides: fuzzy match against person name
    person_type: str = ""  # For additions: phd, postdoc, staff, faculty
    effort: Decimal = Decimal("0")  # Effort percentage (0-1)
    salary: Decimal | None = None  # For non-PhD additions: annual salary
    start: date | None = None
    end: date | None = None


def parse_hypothetical(spec: str) -> Hypothetical:
    """Parse a hypothetical specification string.

    Formats:
    - "Name=50%" - Override existing person's effort
    - "+phd@100%" - Add hypothetical PhD student
    - "+postdoc@100%:85000" - Add hypothetical postdoc with salary
    - "Name=50%@2026-06" - Date-bounded override
    - "+phd@100%@2026-06:2026-09" - Date-bounded addition

    Returns:
        Hypothetical object

    Raises:
        ValueError: If spec format is invalid
    """
    spec = spec.strip()

    # Addition pattern: +type@effort%[:salary][@start[:end]]
    add_match = re.match(
        r"^\+(\w+)@(\d+(?:\.\d+)?)%(?::(\d+))?(?:@([0-9-]+)?(?::([0-9-]+))?)?$", spec
    )
    if add_match:
        person_type = add_match.group(1).lower()
        effort = Decimal(add_match.group(2)) / 100
        salary_str = add_match.group(3)
        salary = Decimal(salary_str) if salary_str else None

        start_str = add_match.group(4)
        end_str = add_match.group(5)
        start = parse_date(start_str) if start_str else None
        end = parse_date(end_str) if end_str else None

        # Normalize type names
        type_map = {
            "phd": "grad_student",
            "grad": "grad_student",
            "grad_student": "grad_student",
            "masters": "masters_student",
            "ms": "masters_student",
            "masters_student": "masters_student",
            "postdoc": "postdoc",
            "staff": "staff",
            "faculty": "faculty",
        }
        if person_type not in type_map:
            raise ValueError(
                f"Unknown person type: {person_type}. Use phd, masters, postdoc, staff, or faculty."
            )

        return Hypothetical(
            is_addition=True,
            person_type=type_map[person_type],
            effort=effort,
            salary=salary,
            start=start,
            end=end,
        )

    # Override pattern: Name=effort%[@start[:end]]
    override_match = re.match(r"^([^=]+)=(\d+(?:\.\d+)?)%(?:@([0-9-]+)?(?::([0-9-]+))?)?$", spec)
    if override_match:
        name = override_match.group(1).strip()
        effort = Decimal(override_match.group(2)) / 100
        start_str = override_match.group(3)
        end_str = override_match.group(4)
        start = parse_date(start_str) if start_str else None
        end = parse_date(end_str) if end_str else None
        return Hypothetical(
            is_addition=False,
            name_pattern=name,
            effort=effort,
            start=start,
            end=end,
        )

    raise ValueError(f"Invalid hypothetical format: '{spec}'. Use 'Name=50%' or '+phd@100%'")


def apply_hypotheticals(
    personnel: list[PersonnelEntry],
    hypotheticals: list[Hypothetical],
    project_id: str,
    rates: "Rates",
    aliases: dict[str, str] | None = None,
) -> list[PersonnelEntry]:
    """Apply hypothetical overrides to create a modified personnel list.

    Args:
        personnel: Original personnel list
        hypotheticals: List of hypotheticals to apply
        project_id: Project to apply hypotheticals to
        rates: Institutional rates (for PhD default salary)
        aliases: Optional dict mapping aliases to real names

    Returns:
        New personnel list with hypotheticals applied (original unchanged)
    """
    # Deep copy to avoid modifying original
    modified = copy.deepcopy(personnel)

    hypo_counter = 1

    for hypo in hypotheticals:
        if hypo.is_addition:
            # Create a new hypothetical person
            if hypo.person_type == "grad_student":
                # Use configured stipend for PhD students
                salary = hypo.salary or rates.tuition_per_semester * 2 + rates.insurance_annual
                # Actually use a reasonable default
                salary = Decimal("47000")  # Standard stipend
            elif hypo.person_type == "masters_student":
                # Hourly masters: default salary = hourly * hours/week * 52
                salary = hypo.salary or (
                    rates.masters_hourly_default * rates.masters_hours_per_week_default * 52
                )
            else:
                if hypo.salary is None:
                    raise ValueError(f"Salary required for hypothetical {hypo.person_type}")
                salary = hypo.salary

            new_person = PersonnelEntry(
                name=f"[Hypothetical {hypo.person_type.title()} #{hypo_counter}]",
                person_type=hypo.person_type,
                annual_salary=salary,
                assignments=[
                    Assignment(
                        project=project_id,
                        effort=hypo.effort,
                        start=hypo.start,
                        end=hypo.end,
                    )
                ],
            )
            modified.append(new_person)
            hypo_counter += 1

        else:
            # Override existing person's effort
            matched = False
            pattern_lower = hypo.name_pattern.lower()

            # Check for alias match first if aliases provided
            resolved_name = None
            if aliases:
                for alias, real_name in aliases.items():
                    if alias.lower() == pattern_lower:
                        resolved_name = real_name
                        break

            for person in modified:
                name_lower = person.name.lower()
                # Match if: alias resolved to this person, or fuzzy match
                if (resolved_name and person.name == resolved_name) or (
                    not resolved_name and pattern_lower in name_lower
                ):
                    if hypo.start is None and hypo.end is None:
                        # Replace all assignments for this project with a single indefinite assignment
                        new_assignments = [a for a in person.assignments if a.project != project_id]
                        new_assignments.append(
                            Assignment(
                                project=project_id,
                                effort=hypo.effort,
                                start=None,
                                end=None,
                            )
                        )
                        person.assignments = new_assignments
                    else:
                        # Time-bounded override: split or adjust existing matching assignments
                        new_assignments = []
                        h_start = hypo.start
                        h_end = hypo.end

                        for a in person.assignments:
                            if a.project != project_id:
                                new_assignments.append(a)
                                continue

                            # Split/truncate matching assignments around [h_start, h_end)
                            # 1. Piece before h_start
                            if h_start and (a.start is None or a.start < h_start):
                                new_end = min(a.end, h_start) if a.end else h_start
                                new_assignments.append(
                                    Assignment(
                                        project=a.project,
                                        effort=a.effort,
                                        start=a.start,
                                        end=new_end,
                                    )
                                )
                            # 2. Piece after h_end
                            if h_end and (a.end is None or h_end < a.end):
                                new_start = max(a.start, h_end) if a.start else h_end
                                new_assignments.append(
                                    Assignment(
                                        project=a.project,
                                        effort=a.effort,
                                        start=new_start,
                                        end=a.end,
                                    )
                                )

                        # Append the override assignment
                        new_assignments.append(
                            Assignment(
                                project=project_id,
                                effort=hypo.effort,
                                start=h_start,
                                end=h_end,
                            )
                        )
                        person.assignments = new_assignments

                    matched = True
                    break

            if not matched:
                raise ValueError(f"No personnel match for '{hypo.name_pattern}'")

    return modified


def parse_date(date_str: str | None) -> date | None:
    """Parse YYYY-MM format to date (first of month)."""
    if not date_str:
        return None
    parts = str(date_str).split("-")
    return date(int(parts[0]), int(parts[1]), 1)


def resolve_assignment_overlaps(assignments: list[Assignment]) -> list[Assignment]:
    """Resolve overlapping assignments for the same project.

    Later assignments in the list (newer overrides) split/truncate earlier ones.
    Adjacent segments with identical effort are collapsed back together.
    """
    resolved: list[Assignment] = []
    for cur in assignments:
        new_resolved = []
        h_start, h_end, project_id = cur.start, cur.end, cur.project
        for a in resolved:
            if a.project != project_id:
                new_resolved.append(a)
                continue

            # If the current assignment is completely indefinite (start and end are None),
            # it replaces everything before it on this project entirely.
            if h_start is None and h_end is None:
                continue

            # 1. Piece before h_start
            if h_start and (a.start is None or a.start < h_start):
                new_end = min(a.end, h_start) if a.end else h_start
                if a.start is None or a.start < new_end:
                    new_resolved.append(Assignment(a.project, a.effort, a.start, new_end))

            # 2. Piece after h_end
            if h_end and (a.end is None or h_end < a.end):
                new_start = max(a.start, h_end) if a.start else h_end
                if a.end is None or new_start < a.end:
                    new_resolved.append(Assignment(a.project, a.effort, new_start, a.end))

        new_resolved.append(cur)
        resolved = new_resolved

    # Collapse adjacent contiguous segments with identical effort on the same project
    collapsed: list[Assignment] = []
    for a in resolved:
        if not collapsed:
            collapsed.append(a)
            continue
        prev = collapsed[-1]
        if prev.project == a.project and prev.effort == a.effort and prev.end == a.start:
            collapsed[-1] = Assignment(prev.project, prev.effort, prev.start, a.end)
        else:
            collapsed.append(a)

    return collapsed


def load_personnel_config(config_path: str | Path) -> tuple[Rates, list[PersonnelEntry]]:
    """
    Load personnel configuration from YAML.

    Rates are loaded from rates.yaml (sibling to personnel_config.yaml)
    if available, otherwise falls back to rates in personnel_config.yaml.

    Returns:
        Tuple of (Rates, list of PersonnelEntry)
    """
    config_path = Path(config_path)

    with open(config_path) as f:
        config = yaml.safe_load(f)

    # Try to load rates from rates.yaml (or legacy jhu_rates.yaml)
    from .config import get_rates_path

    rates_path = get_rates_path(config_path.parent.parent)
    if rates_path.exists():
        with open(rates_path) as f:
            rates_config = yaml.safe_load(f)
        # Load grad student costs if available
        gs_costs = rates_config.get("grad_student_costs", {})
        tuition_billing = rates_config.get("tuition_billing", {})
        rates = Rates(
            idc=Decimal(str(rates_config["idc_rate"])),
            fringe={k: Decimal(str(v)) for k, v in rates_config["fringe_rates"].items()},
            tuition_per_semester=Decimal(
                str(tuition_billing.get("per_semester", gs_costs.get("tuition", 0) / 2))
            ),
            insurance_annual=Decimal(
                str(gs_costs.get("health_dental", gs_costs.get("insurance", 0)))
            ),
            tuition_months=tuition_billing.get("months", [1, 9]),
            masters_tuition_per_semester=Decimal(
                str(
                    tuition_billing.get(
                        "masters_per_semester", gs_costs.get("masters_tuition", 0) / 2
                    )
                )
            ),
            masters_hourly_default=Decimal(str(rates_config.get("masters_hourly", 20))),
            masters_hours_per_week_default=Decimal(
                str(rates_config.get("masters_hours_per_week", 20))
            ),
            masters_max_hours_per_week=Decimal(
                str(rates_config.get("masters_max_hours_per_week", "19.9"))
            ),
        )
    elif "rates" in config:
        # Fallback to rates in personnel_config.yaml
        gs_costs = config.get("grad_student_costs", {})
        rates = Rates(
            idc=Decimal(str(config["rates"]["idc"])),
            fringe={k: Decimal(str(v)) for k, v in config["rates"]["fringe"].items()},
            tuition_per_semester=Decimal(str(gs_costs.get("tuition", 0))) / 2,
            insurance_annual=Decimal(
                str(gs_costs.get("insurance", gs_costs.get("health_dental", 0)))
            ),
            tuition_months=[1, 9],
        )
    else:
        # Default rates if none found
        rates = Rates(
            idc=Decimal("0.55"),
            fringe={
                "faculty": Decimal("0.34"),
                "postdoc": Decimal("0.227"),
                "grad_student": Decimal("0.0"),
                "masters_student": Decimal("0.0825"),
                "staff": Decimal("0.34"),
            },
            tuition_per_semester=Decimal("6667"),
            insurance_annual=Decimal("2785"),
            tuition_months=[1, 9],
            masters_tuition_per_semester=Decimal("33335"),
            masters_hourly_default=Decimal("20"),
            masters_hours_per_week_default=Decimal("20"),
            masters_max_hours_per_week=Decimal("19.9"),
        )

    # Parse personnel
    personnel = []
    for p in config.get("personnel", []):
        assignments = []
        for a in p.get("assignments", []):
            assignments.append(
                Assignment(
                    project=a["project"],
                    effort=Decimal(str(a.get("effort", 0))),
                    start=parse_date(a.get("start")),
                    end=parse_date(a.get("end")),
                )
            )

        raw_salary = p.get("annual_salary", 0)
        salaries = []
        hourly_rate = None
        hours_per_week = None
        include_tuition = p.get("include_tuition", True)
        include_insurance = p.get("include_insurance", True)

        if p["type"] == "masters_student":
            # Hourly masters: compute annual salary from rate * hours * 52
            hourly_rate = Decimal(str(p.get("hourly_rate", 0))) if p.get("hourly_rate") else None
            hours_per_week = (
                Decimal(str(p.get("hours_per_week", 0))) if p.get("hours_per_week") else None
            )
            effective_hourly = hourly_rate or rates.masters_hourly_default
            effective_hours = hours_per_week or rates.masters_hours_per_week_default
            if effective_hours > rates.masters_max_hours_per_week:
                import logging

                logging.getLogger(__name__).warning(
                    "%s: hours_per_week %.1f exceeds JHU cap of %.1f",
                    p["name"],
                    effective_hours,
                    rates.masters_max_hours_per_week,
                )
            if raw_salary and Decimal(str(raw_salary)) > 0:
                annual_salary = Decimal(str(raw_salary))
            else:
                annual_salary = effective_hourly * effective_hours * 52
            salaries = [SalaryRecord(amount=annual_salary, start=None, end=None)]
        elif isinstance(raw_salary, list):
            for s in raw_salary:
                salaries.append(
                    SalaryRecord(
                        amount=Decimal(str(s["amount"])),
                        start=parse_date(s.get("start")),
                        end=parse_date(s.get("end")),
                    )
                )
            annual_salary = salaries[-1].amount if salaries else Decimal("0")
        else:
            annual_salary = Decimal(str(raw_salary))
            salaries = [SalaryRecord(amount=annual_salary, start=None, end=None)]

        personnel.append(
            PersonnelEntry(
                name=p["name"],
                person_type=p["type"],
                annual_salary=annual_salary,
                assignments=resolve_assignment_overlaps(assignments),
                departure=parse_date(p.get("departure")),
                salaries=salaries,
                hourly_rate=hourly_rate,
                hours_per_week=hours_per_week,
                include_tuition=include_tuition,
                include_insurance=include_insurance,
            )
        )

    return rates, personnel


def is_active(assignment: Assignment, year: int, month: int, departure: date | None = None) -> bool:
    """Check if an assignment is active for a given month."""
    check_date = date(year, month, 1)

    if assignment.start and check_date < assignment.start:
        return False
    if assignment.end and check_date >= assignment.end:
        return False
    # Person-level departure overrides assignment
    return not (departure and check_date >= departure)


def project_monthly_costs(
    project_id: str,
    rates: Rates,
    personnel: list[PersonnelEntry],
    year: int,
    month: int,
    travel_items: list[TravelItem] | None = None,
    expenses: list[ExpenseItem] | None = None,
) -> MonthlyProjection:
    """
    Calculate projected costs for a project for a specific month.

    Args:
        project_id: Project short name
        rates: Current institutional rates
        personnel: List of personnel entries
        year: Year to project
        month: Month to project
        travel_items: List of travel items for this project
        expenses: List of expense items for this project

    Returns:
        MonthlyProjection with costs breakdown
    """
    direct_salary = Decimal("0")
    fringe = Decimal("0")
    tuition = Decimal("0")
    insurance = Decimal("0")
    travel_cost = Decimal("0")
    compute_cost = Decimal("0")
    equipment_cost = Decimal("0")
    other_cost = Decimal("0")
    current_travel: list[TravelItem] = []
    current_expenses: list[ExpenseItem] = []

    personnel_detail = []

    date_val = date(year, month, 1)

    # Calculate travel for this month
    if travel_items:
        for travel_item in travel_items:
            if (
                travel_item.date
                and travel_item.date.year == year
                and travel_item.date.month == month
            ):
                travel_cost += travel_item.amount
                current_travel.append(travel_item)

    # Calculate expenses for this month
    if expenses:
        for expense_item in expenses:
            cost_to_add = Decimal("0")
            if expense_item.is_recurring:
                # Recurring: check if current month is within range (inclusive)
                # Normalize start/end to month granularity if possible, or just date range
                start = (
                    expense_item.start_date.replace(day=1) if expense_item.start_date else date.min
                )
                end = expense_item.end_date.replace(day=1) if expense_item.end_date else date.max
                if start <= date_val <= end:
                    cost_to_add = expense_item.amount
            else:
                # One-time: check if same month
                if (
                    expense_item.date
                    and expense_item.date.year == year
                    and expense_item.date.month == month
                ):
                    cost_to_add = expense_item.amount

            if cost_to_add > 0:
                cat_lower = expense_item.category.lower()
                if "equip" in cat_lower:
                    equipment_cost += cost_to_add
                elif "compute" in cat_lower:
                    compute_cost += cost_to_add
                else:
                    other_cost += cost_to_add
                current_expenses.append(expense_item)

    # Determine if this is a tuition billing month
    tuition_months = rates.tuition_months or [1, 9]
    is_tuition_month = month in tuition_months

    for person in personnel:
        for assignment in person.assignments:
            if assignment.project != project_id:
                continue
            if not is_active(assignment, year, month, person.departure):
                continue
            if assignment.effort <= 0:
                continue

            # Monthly salary = annual / 12 * effort
            salary = person.annual_salary
            if person.salaries:
                for sr in person.salaries:
                    if sr.start and date_val < sr.start:
                        continue
                    if sr.end and date_val >= sr.end:
                        continue
                    salary = sr.amount
                    break
            monthly_salary = (salary / 12) * assignment.effort
            direct_salary += monthly_salary

            # Fringe based on type
            fringe_rate = rates.fringe.get(person.person_type, Decimal("0.34"))
            if person.person_type == "masters_student":
                # FICA exempt (0% fringe) during Academic Year (Sept - May)
                # Subject to Casual/Limited rate during Summer (June - Aug)
                if month in (6, 7, 8):
                    fringe_rate = rates.fringe.get("masters_student", Decimal("0.0825"))
                else:
                    fringe_rate = Decimal("0.0")

            person_fringe = monthly_salary * fringe_rate
            fringe += person_fringe

            # Add tuition and insurance for grad/masters students
            person_tuition = Decimal("0")
            person_insurance = Decimal("0")
            if person.person_type == "grad_student" and is_tuition_month:
                # Tuition and insurance billed semi-annually in Jan/Sep
                person_tuition = rates.tuition_per_semester * assignment.effort
                tuition += person_tuition
                person_insurance = (rates.insurance_annual / 2) * assignment.effort
                insurance += person_insurance
            elif person.person_type == "masters_student" and is_tuition_month:
                # Masters students: full tuition rate, respect per-person flags
                if person.include_tuition:
                    person_tuition = rates.masters_tuition_per_semester * assignment.effort
                    tuition += person_tuition
                if person.include_insurance:
                    person_insurance = (rates.insurance_annual / 2) * assignment.effort
                    insurance += person_insurance

            personnel_detail.append(
                (person.name, monthly_salary + person_fringe + person_tuition + person_insurance)
            )

    # Indirect costs on salary + fringe (tuition typically excluded from IDC)
    # Travel usually incurs IDC.
    # Equipment typically EXCLUDED from IDC (check rates if over $5k, but simplified here)
    # Compute and Other costs usually incur IDC
    base_for_idc = direct_salary + fringe + travel_cost + compute_cost + other_cost + insurance
    indirect = base_for_idc * rates.idc

    total = (
        direct_salary
        + fringe
        + indirect
        + tuition
        + insurance
        + travel_cost
        + compute_cost
        + equipment_cost
        + other_cost
    )

    return MonthlyProjection(
        year=year,
        month=month,
        direct_salary=direct_salary,
        fringe=fringe,
        indirect=indirect,
        total=total,
        personnel=personnel_detail,
        tuition=tuition,
        insurance=insurance,
        travel=travel_cost,
        compute=compute_cost,
        equipment=equipment_cost,
        other_direct=other_cost,
        travel_detail=current_travel,
        expense_detail=current_expenses,
    )


def project_spending(
    project_id: str,
    config_path: str | Path,
    start_date: date | None = None,
    end_date: date | None = None,
    months: int = 12,
    travel_items: list[TravelItem] | None = None,
    expense_items: list[ExpenseItem] | None = None,
    personnel_overrides: list[PersonnelEntry] | None = None,
) -> list[MonthlyProjection]:
    """
    Generate spending projections for a project.

    Args:
        project_id: Project short name
        config_path: Path to personnel_config.yaml
        start_date: Start date (default: today)
        end_date: End date (overrides months if provided)
        months: Number of months to project (default: 12)
        travel_items: Optional list of travel items
        expense_items: Optional list of expense items
        personnel_overrides: Optional list of PersonnelEntry overrides

    Returns:
        List of MonthlyProjection
    """
    rates, personnel_from_config = load_personnel_config(config_path)
    personnel = personnel_overrides if personnel_overrides is not None else personnel_from_config

    if start_date is None:
        start_date = date.today().replace(day=1)

    projections = []
    current = start_date

    count = 0
    while True:
        if end_date and current >= end_date:
            break
        if not end_date and count >= months:
            break

        proj = project_monthly_costs(
            project_id, rates, personnel, current.year, current.month, travel_items, expense_items
        )
        projections.append(proj)

        # Next month
        if current.month == 12:
            current = current.replace(year=current.year + 1, month=1)
        else:
            current = current.replace(month=current.month + 1)
        count += 1

    return projections


def format_projection_report(projections: list[MonthlyProjection], project_id: str) -> str:
    """Format projections as a readable report."""
    lines = [
        f"\n=== Spending Projection: {project_id} ===\n",
        f"{'Month':<12} {'Salary':>12} {'Fringe':>10} {'Travel':>10} {'Compute':>10} {'Equip':>10} {'Other':>10} {'IDC':>10} {'Total':>12}",
        "-" * 102,
    ]

    total_salary = Decimal("0")
    total_fringe = Decimal("0")
    total_travel = Decimal("0")
    total_compute = Decimal("0")
    total_equip = Decimal("0")
    total_other = Decimal("0")
    total_idc = Decimal("0")
    total_all = Decimal("0")

    for p in projections:
        month_str = f"{p.year}-{p.month:02d}"
        lines.append(
            f"{month_str:<12} ${p.direct_salary:>10,.2f} ${p.fringe:>8,.2f} ${p.travel:>8,.2f} ${p.compute:>8,.2f} ${p.equipment:>8,.2f} ${p.other_direct:>8,.2f} ${p.indirect:>8,.2f} ${p.total:>10,.2f}"
        )
        # Add detail for travel if present
        if p.travel_detail:
            for item in p.travel_detail:
                desc = (
                    item.description
                    if len(item.description) < 30
                    else item.description[:27] + "..."
                )
                lines.append(f"  > Travel: {desc:<30} ${item.amount:,.2f} ({item.status.value})")

        # Add detail for expenses if present
        if p.expense_detail:
            for expense_item in p.expense_detail:
                # Skip recurring items to reduce noise
                if expense_item.is_recurring:
                    continue
                desc = (
                    expense_item.description
                    if len(expense_item.description) < 30
                    else expense_item.description[:27] + "..."
                )
                lines.append(f"  > {expense_item.category}: {desc:<29} ${expense_item.amount:,.2f}")

        total_salary += p.direct_salary
        total_fringe += p.fringe
        total_travel += p.travel
        total_compute += p.compute
        total_equip += p.equipment
        total_other += p.other_direct
        total_idc += p.indirect
        total_all += p.total

    lines.append("-" * 102)
    lines.append(
        f"{'TOTAL':<12} ${total_salary:>10,.2f} ${total_fringe:>8,.2f} ${total_travel:>8,.2f} ${total_compute:>8,.2f} ${total_equip:>8,.2f} ${total_other:>8,.2f} ${total_idc:>8,.2f} ${total_all:>10,.2f}"
    )
    return "\n".join(lines)


def optimize_mitigations(
    project_id: str,
    config_path: Path | str,
    store: ProjectStore,
    target_months: int = 12,
    budget_override: Decimal | None = None,
) -> list[dict]:
    """
    Computes 3 specific mitigation packages to extend project runway:
    - Plan A: Freeze planned travel + pause recurring expenses
    - Plan B: Freeze travel/expenses + 25% reduction on all personnel on this project
    - Plan C: Freeze travel/expenses + 50% reduction on all personnel on this project

    Runway is measured against the funded ceiling -- the money the sponsor has
    actually obligated -- and bounded by the award end date, so a plan that
    carries the project to the end of the award is reported as such rather than
    as an arbitrarily long extension.

    Returns:
        List of 3 styled mitigation plans (easy, moderate, deep).
    """
    from datetime import date

    from .budget_resolution import resolve_award_end_date, resolve_funded_ceiling
    from .cli._util import Anonymizer

    travel_items = store.get_project_travel(project_id)
    expense_items = store.get_project_expenses(project_id)

    _rates, original_personnel = load_personnel_config(config_path)

    start = date.today().replace(day=1)
    award_end, _ = resolve_award_end_date(store, project_id)
    horizon = 36
    if award_end and award_end > start:
        horizon = min(
            36,
            max(1, (award_end.year - start.year) * 12 + (award_end.month - start.month) + 1),
        )

    ceiling = budget_override
    ceiling_source = "override"
    if ceiling is None:
        ceiling, ceiling_source = resolve_funded_ceiling(store, project_id, store.data_dir)

    project_data = store.get_project(project_id)
    spent_so_far = Decimal("0")
    outstanding_commitments = Decimal("0")
    if project_data and project_data.spending:
        latest = max(project_data.spending, key=lambda r: (r.year, r.month))
        spent_so_far = latest.total_spent
        outstanding_commitments = latest.total_committed or Decimal("0")

    available_funds = max(Decimal("0"), (ceiling or Decimal("0")) - spent_so_far)

    def get_stop_work_months(
        personnel_list, travel_list, expense_list
    ) -> tuple[float, bool, float]:
        """
        Months of runway, whether the award ends before the funds do, and the
        funds left over at the end of the award.

        Once several plans all carry the project to the award end, the runway
        figure alone stops separating them; the leftover is what still does.
        """
        if not ceiling or ceiling <= Decimal("0"):
            return float(horizon), True, 0.0

        projections = project_spending(
            project_id=project_id,
            config_path=config_path,
            start_date=start,
            months=horizon,
            travel_items=travel_list,
            expense_items=expense_list,
            personnel_overrides=personnel_list,
        )

        cumulative_spent = Decimal("0")
        stop_at: float | None = None
        for idx, p in enumerate(projections, 1):
            cumulative_spent += p.total
            if stop_at is None and cumulative_spent >= available_funds:
                prev_spent = cumulative_spent - p.total
                needed = available_funds - prev_spent
                fraction = float(needed / p.total) if p.total > 0 else 0.0
                stop_at = float(idx - 1) + fraction

        leftover = float(available_funds - cumulative_spent)
        if stop_at is not None:
            return stop_at, False, leftover
        # Funds outlast the award: runway is capped by the award, not the money.
        return float(len(projections)), True, leftover

    baseline_months, baseline_capped, baseline_leftover = get_stop_work_months(
        original_personnel, travel_items, expense_items
    )

    def effort_levers(personnel_list, factor: Decimal) -> list[str]:
        """
        One lever per person, describing their effort over the forecast window.

        Assignments are stored as date-bounded segments, so a person whose
        effort steps up over time has several rows for one project; listing each
        row reads as duplicate people. Zero-effort assignments are omitted --
        cutting 0% to 0% is not a lever.
        """
        levers = []
        window_end = date(
            start.year + (start.month - 1 + horizon) // 12,
            (start.month - 1 + horizon) % 12 + 1,
            1,
        )
        for person in personnel_list:
            efforts = []
            for a in person.assignments:
                if a.project != project_id:
                    continue
                if a.end and a.end <= start:
                    continue
                if a.start and a.start >= window_end:
                    continue
                if person.departure and person.departure <= start:
                    continue
                efforts.append(a.effort)

            active = [e for e in efforts if e > 0]
            if not active:
                continue

            low, high = min(active), max(active)
            before = f"{high * 100:.0f}%" if low == high else f"{low * 100:.0f}-{high * 100:.0f}%"
            after_low, after_high = low * factor, high * factor
            after = (
                f"{after_high * 100:.0f}%"
                if low == high
                else f"{after_low * 100:.0f}-{after_high * 100:.0f}%"
            )
            levers.append(f"Reduce {Anonymizer.anonymize(person.name)} effort: {before} -> {after}")
        return levers

    def scale_effort(personnel_list, factor: Decimal):
        scaled = copy.deepcopy(personnel_list)
        for person in scaled:
            for a in person.assignments:
                if a.project == project_id:
                    a.effort = a.effort * factor
        return scaled

    plans = []

    # Plan A: Non-Personnel Cuts Only
    frozen_travel = [
        f"Freeze travel: {t.description} (${t.amount:,.2f})"
        for t in travel_items
        if t.status.value != "actualized"
    ]
    frozen_expenses = [
        (
            f"Pause expense: {e.description} (${e.amount:,.2f}/mo)"
            if e.is_recurring
            else f"Cancel expense: {e.description} (${e.amount:,.2f})"
        )
        for e in expense_items
    ]

    def add_plan(name: str, description: str, levers: list[str], factor: Decimal | None):
        personnel = (
            original_personnel if factor is None else scale_effort(original_personnel, factor)
        )
        months, capped, leftover = get_stop_work_months(personnel, [], [])
        plans.append(
            {
                "name": name,
                "description": description,
                "levers": levers,
                "extended_stop_work_months": months,
                "extension": max(0.0, months - baseline_months),
                "funded_through_award_end": capped,
                "funds_left_at_award_end": round(leftover, 2),
                "shortfall_at_award_end": round(-leftover, 2) if leftover < 0 else 0.0,
            }
        )

    add_plan(
        "Plan A: Non-Personnel Cuts Only",
        "Freeze all planned travel and pause all recurring expenses.",
        frozen_travel + frozen_expenses,
        None,
    )
    add_plan(
        "Plan B: Moderate Cuts",
        "Freeze travel/expenses and reduce personnel effort by 25%.",
        frozen_travel + frozen_expenses + effort_levers(original_personnel, Decimal("0.75")),
        Decimal("0.75"),
    )
    add_plan(
        "Plan C: Deep Cuts",
        "Freeze travel/expenses and reduce personnel effort by 50%.",
        frozen_travel + frozen_expenses + effort_levers(original_personnel, Decimal("0.50")),
        Decimal("0.50"),
    )

    for plan in plans:
        plan["baseline_stop_work_months"] = baseline_months
        plan["baseline_capped_by_award_end"] = baseline_capped
        plan["baseline_shortfall_at_award_end"] = (
            round(-baseline_leftover, 2) if baseline_leftover < 0 else 0.0
        )
        plan["outstanding_commitments"] = float(outstanding_commitments)
        plan["ceiling"] = float(ceiling) if ceiling else None
        plan["ceiling_source"] = ceiling_source
        plan["available_funds"] = float(available_funds)
        plan["horizon_months"] = horizon

    return plans
