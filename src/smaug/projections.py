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
            "postdoc": "postdoc",
            "staff": "staff",
            "faculty": "faculty",
        }
        if person_type not in type_map:
            raise ValueError(
                f"Unknown person type: {person_type}. Use phd, postdoc, staff, or faculty."
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
    return resolved


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
                "staff": Decimal("0.34"),
            },
            tuition_per_semester=Decimal("6667"),
            insurance_annual=Decimal("2785"),
            tuition_months=[1, 9],
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
        if isinstance(raw_salary, list):
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
            person_fringe = monthly_salary * fringe_rate
            fringe += person_fringe

            # Add tuition and insurance for grad students
            person_tuition = Decimal("0")
            person_insurance = Decimal("0")
            if person.person_type == "grad_student" and is_tuition_month:
                # Tuition and insurance billed semi-annually in Jan/Sep
                person_tuition = rates.tuition_per_semester * assignment.effort
                tuition += person_tuition
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
    config_path: str | Path,
    store: ProjectStore,
    target_months: int = 12,
) -> list[dict]:
    """
    Greedy budget mitigation optimizer.
    Suggests travel freezes, expense pauses, and personnel effort cuts to extend the project's stop-work date.

    Returns:
        List of 3 styled mitigation plans (easy, moderate, deep).
    """
    from datetime import date

    from .cli._util import Anonymizer

    # 1. Compute baseline stop-work date
    travel_items = store.get_project_travel(project_id)
    expense_items = store.get_project_expenses(project_id)

    _rates, original_personnel = load_personnel_config(config_path)

    def get_stop_work_months(personnel_list, travel_list, expense_list) -> float:
        # Generate projections up to 36 months
        projections = project_spending(
            project_id=project_id,
            config_path=config_path,
            start_date=date.today().replace(day=1),
            months=36,
            travel_items=travel_list,
            expense_items=expense_list,
            personnel_overrides=personnel_list,
        )
        # Calculate when remaining budget is exhausted
        project_data = store.get_project(project_id)
        if not project_data or not project_data.project.total_budget:
            return 12.0

        remaining_budget = project_data.project.total_budget
        spent_so_far = Decimal("0")
        if project_data.spending:
            spent_so_far = project_data.spending[-1].total_spent

        available_funds = max(Decimal("0"), remaining_budget - spent_so_far)

        cumulative_spent = Decimal("0")
        for idx, p in enumerate(projections, 1):
            cumulative_spent += p.total
            if cumulative_spent >= available_funds:
                prev_spent = cumulative_spent - p.total
                needed = available_funds - prev_spent
                fraction = float(needed / p.total) if p.total > 0 else 0.0
                return float(idx - 1) + fraction
        return 36.0

    baseline_months = get_stop_work_months(original_personnel, travel_items, expense_items)

    plans = []

    # Plan A: Non-Personnel Cuts Only
    plan_easy_travel = [t for t in travel_items if t.status.value != "actualized"]
    frozen_travel = []
    for t in plan_easy_travel:
        frozen_travel.append(f"Freeze travel: {t.description} (${t.amount:,.2f})")

    frozen_expenses = []
    for e in expense_items:
        frozen_expenses.append(f"Pause expense: {e.description} (${e.amount:,.2f}/mo)")

    easy_months = get_stop_work_months(original_personnel, [], [])
    plans.append(
        {
            "name": "Plan A: Non-Personnel Cuts Only",
            "description": "Freeze all planned travel and pause all recurring expenses.",
            "levers": frozen_travel + frozen_expenses,
            "extended_stop_work_months": easy_months,
            "extension": max(0.0, easy_months - baseline_months),
        }
    )

    # Plan B: Moderate Cuts
    import copy

    mod_personnel = copy.deepcopy(original_personnel)
    levers_mod = list(frozen_travel + frozen_expenses)
    for p in mod_personnel:
        for a in p.assignments:
            if a.project == project_id:
                old_effort = a.effort
                a.effort = old_effort * Decimal("0.75")
                levers_mod.append(
                    f"Reduce {Anonymizer.anonymize(p.name)} effort: {old_effort * 100:.0f}% -> {a.effort * 100:.0f}%"
                )

    mod_months = get_stop_work_months(mod_personnel, [], [])
    plans.append(
        {
            "name": "Plan B: Moderate Cuts",
            "description": "Freeze travel/expenses and reduce personnel effort by 25%.",
            "levers": levers_mod,
            "extended_stop_work_months": mod_months,
            "extension": max(0.0, mod_months - baseline_months),
        }
    )

    # Plan C: Deep Cuts
    deep_personnel = copy.deepcopy(original_personnel)
    levers_deep = list(frozen_travel + frozen_expenses)
    for p in deep_personnel:
        for a in p.assignments:
            if a.project == project_id:
                old_effort = a.effort
                a.effort = old_effort * Decimal("0.50")
                levers_deep.append(
                    f"Reduce {Anonymizer.anonymize(p.name)} effort: {old_effort * 100:.0f}% -> {a.effort * 100:.0f}%"
                )

    deep_months = get_stop_work_months(deep_personnel, [], [])
    plans.append(
        {
            "name": "Plan C: Deep Cuts",
            "description": "Freeze travel/expenses and reduce personnel effort by 50%.",
            "levers": levers_deep,
            "extended_stop_work_months": deep_months,
            "extension": max(0.0, deep_months - baseline_months),
        }
    )

    return plans
