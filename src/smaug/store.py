"""
Project data store.

Loads project configuration from manifest, parses budgets and reports,
and provides unified access to project data.
"""

import json
import logging
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml

from .excel_budget_parsing import parse_budget_file
from .invoice_parsing import find_invoices
from .models import (
    ExpenseItem,
    Invoice,
    Project,
    ProjectBudget,
    ProjectData,
    ProjectStatus,
    ProjectType,
    SpendingReport,
    TravelItem,
    TravelStatus,
)
from .parsers import (
    InvoiceParser,
    ReportParser,
    discover_parsers,
)
from .parsers import parse_invoice as _plugin_parse_invoice
from .parsers import parse_report as _plugin_parse_report
from .personnel import PersonnelTracker
from .validation import ParseWarning, validate_report

logger = logging.getLogger(__name__)


_REPORT_PARSE_CACHE: dict[tuple[str, float, int], tuple[SpendingReport | None, list]] = {}


class ProjectStore:
    """
    Central store for all project data.

    Loads project configuration from manifest.yaml and parses
    associated budget and report files.
    """

    def __init__(self, data_dir: str | Path = "jhu"):
        self.data_dir = Path(data_dir)
        self.projects_dir = self.data_dir / "projects"
        self.reports_dir = self.data_dir / "reports"
        self.cache_dir = self.projects_dir / ".cache"

        self._projects: dict[str, Project] = {}
        self._budgets: dict[str, ProjectBudget] = {}
        self._spending: dict[str, list[SpendingReport]] = {}
        self._travel: list[TravelItem] = []
        self._expenses: list[ExpenseItem] = []
        self._invoices: dict[str, list[Invoice]] = {}
        self._personnel = PersonnelTracker()
        self._parse_warnings: list[ParseWarning] = []

        # Discover parsers via the plugin registry
        self._report_parsers: list[ReportParser] = []
        self._invoice_parsers: list[InvoiceParser] = []
        self._report_parsers, self._invoice_parsers = discover_parsers()

    def load_manifest(self) -> None:
        """Load project definitions from manifest.yaml."""
        manifest_path = self.projects_dir / "manifest.yaml"

        if not manifest_path.exists():
            raise FileNotFoundError(f"Manifest not found: {manifest_path}")

        with open(manifest_path) as f:
            manifest = yaml.safe_load(f)

        def parse_date_str(date_str):
            """Parse YYYY-MM date string."""
            if not date_str:
                return None
            parts = str(date_str).split("-")
            return date(int(parts[0]), int(parts[1]), 1)

        # Load sponsored projects
        for short_name, config in manifest.get("projects", {}).items():
            status_str = config.get("status", "active")
            status = ProjectStatus(status_str) if status_str else ProjectStatus.ACTIVE
            budget_val = config.get("total_budget") or config.get("budget")
            self._projects[short_name] = Project(
                short_name=short_name,
                name=config.get("name", short_name),
                pi=config.get("pi", ""),
                project_type=ProjectType.SPONSORED,
                status=status,
                grant_number=config.get("grant_number"),
                sponsored_program=config.get("sponsored_program"),
                award_id=config.get("award_id"),
                budget_dir=config.get("budget_dir"),
                reports_dir=config.get("reports_dir"),
                end_date=parse_date_str(config.get("end_date")),
                total_budget=Decimal(str(budget_val)) if budget_val else None,
            )

        # Load non-sponsored / discretionary accounts
        for short_name, config in manifest.get("discretionary", {}).items():
            status_str = config.get("status", "active")
            status = ProjectStatus(status_str) if status_str else ProjectStatus.ACTIVE
            budget_val = config.get("total_budget") or config.get("budget")
            self._projects[short_name] = Project(
                short_name=short_name,
                name=config.get("name", short_name),
                pi=config.get("pi", ""),
                project_type=ProjectType.DISCRETIONARY,
                status=status,
                funded_program=config.get("funded_program"),
                fund_center=config.get("fund_center"),
                reports_dir=config.get("reports_dir"),
                end_date=parse_date_str(config.get("end_date")),
                total_budget=Decimal(str(budget_val)) if budget_val else None,
            )

    def load_budgets(self) -> None:
        """Load budget data from Excel files for all projects."""
        for short_name, project in self._projects.items():
            if project.budget_dir:
                budget_dir = Path(project.budget_dir)
                if not budget_dir.is_absolute():
                    budget_dir = self.data_dir / budget_dir
                if budget_dir.exists():
                    # Find budget Excel files
                    for xlsx_file in budget_dir.glob("*[Bb]udget*.xlsx"):
                        budget = parse_budget_file(xlsx_file)
                        if budget:
                            budget.project_id = short_name
                            self._budgets[short_name] = budget
                            break  # Use first matching budget file

    def load_reports(self) -> None:
        """Load spending reports via the parser plugin registry."""
        self._parse_warnings = []  # Reset on each load

        for report_dir in (self.reports_dir / "sponsored", self.reports_dir / "non-sponsored"):
            if not report_dir.exists():
                continue
            for report_file in sorted(report_dir.glob("*")):
                if report_file.is_dir():
                    continue

                try:
                    stat = report_file.stat()
                    cache_key = (str(report_file.resolve()), stat.st_mtime, stat.st_size)
                except OSError:
                    cache_key = None

                if cache_key and cache_key in _REPORT_PARSE_CACHE:
                    report, personnel = _REPORT_PARSE_CACHE[cache_key]
                else:
                    report, personnel = _plugin_parse_report(report_file, self._report_parsers)
                    if cache_key:
                        _REPORT_PARSE_CACHE[cache_key] = (report, personnel)

                if report:
                    # Validate before storing
                    prior = self._spending.get(
                        self._resolve_project_id(report.project_id) or "",
                        [],
                    )
                    result = validate_report(report, report_file, prior_reports=prior)
                    self._parse_warnings.extend(result.warnings)

                    if not result.is_valid:
                        logger.warning(
                            "Rejecting report %s: %s",
                            report_file.name,
                            "; ".join(e.message for e in result.errors),
                        )
                        continue

                    # Map identifiers to project short names
                    project_id = self._resolve_project_id(report.project_id)
                    if project_id:
                        report.project_id = project_id
                        if project_id not in self._spending:
                            self._spending[project_id] = []
                        # Avoid duplicates (same project + period)
                        existing = [
                            r for r in self._spending[project_id] if r.period == report.period
                        ]
                        if not existing:
                            self._spending[project_id].append(report)

                # Add personnel allocations
                for alloc in personnel:
                    mapped = self._resolve_project_id(alloc.project_id)
                    if mapped:
                        alloc.project_id = mapped
                        self._personnel.add_allocation(alloc)

    def load_travel_config(self) -> None:
        """Load travel configuration from travel_config.yaml."""
        self._travel = []  # Clear existing items to avoid duplicates
        config_path = self.projects_dir / "travel_config.yaml"
        if not config_path.exists():
            return

        with open(config_path) as f:
            config = yaml.safe_load(f)

        for item in config.get("travel", []):
            try:
                # Parse date
                date_str = item.get("date")
                travel_date = None
                if date_str:
                    parts = str(date_str).split("-")
                    if len(parts) >= 3:
                        travel_date = date(int(parts[0]), int(parts[1]), int(parts[2]))
                    elif len(parts) == 2:
                        travel_date = date(int(parts[0]), int(parts[1]), 1)
                    else:
                        print(f"Warning: Invalid date format: {date_str}")
                        travel_date = date.today()  # Fallback to today

                if travel_date is None:
                    travel_date = date.today()  # Ensure travel_date is never None

                self._travel.append(
                    TravelItem(
                        project_id=item["project"],
                        description=item["description"],
                        date=travel_date,
                        amount=Decimal(str(item.get("amount", 0))),
                        traveler=item.get("traveler"),
                        status=TravelStatus(item.get("status", "estimated")),
                    )
                )
            except Exception as e:
                print(f"Warning: Failed to parse travel item: {item}. Error: {e}")

    def load_purchases_config(self) -> None:
        """Load purchases/expenses configuration from purchases_config.yaml."""
        self._expenses = []  # Clear existing
        config_path = self.projects_dir / "purchases_config.yaml"
        if not config_path.exists():
            return

        with open(config_path) as f:
            config = yaml.safe_load(f)

        for item in config.get("items", []):
            try:
                # Parse dates
                date_val = None
                start_val = None
                end_val = None

                if item.get("date"):
                    parts = str(item["date"]).split("-")
                    if len(parts) >= 3:
                        date_val = date(int(parts[0]), int(parts[1]), int(parts[2]))
                    elif len(parts) == 2:
                        date_val = date(int(parts[0]), int(parts[1]), 1)

                if item.get("start"):
                    parts = str(item["start"]).split("-")
                    if len(parts) >= 2:
                        start_val = date(int(parts[0]), int(parts[1]), 1)

                if item.get("end"):
                    parts = str(item["end"]).split("-")
                    if len(parts) >= 2:
                        end_val = date(int(parts[0]), int(parts[1]), 1)

                self._expenses.append(
                    ExpenseItem(
                        project_id=item["project"],
                        description=item["description"],
                        amount=Decimal(str(item.get("amount", 0))),
                        category=item.get("category", "Other"),
                        date=date_val,
                        start_date=start_val,
                        end_date=end_val,
                    )
                )
            except Exception as e:
                print(f"Warning: Failed to parse expense item: {item}. Error: {e}")

    def _find_project_by_short_name(self, name: str) -> str | None:
        """Find project by short name (direct match)."""
        if name in self._projects:
            return name
        return None

    def _find_project_by_grant(self, grant_number: str) -> str | None:
        """Find project short name by grant number."""
        for short_name, project in self._projects.items():
            if project.grant_number == grant_number:
                return short_name
        return None

    def _find_project_by_funded_program(self, funded_program: str) -> str | None:
        """Find project short name by funded program ID."""
        for short_name, project in self._projects.items():
            if project.funded_program == funded_program:
                return short_name
        return None

    def _resolve_project_id(self, identifier: str) -> str | None:
        """Resolve an identifier to a project short name.

        Tries, in order: direct short name, grant number, funded program.
        """
        return (
            self._find_project_by_short_name(identifier)
            or self._find_project_by_grant(identifier)
            or self._find_project_by_funded_program(identifier)
        )

    def load_invoices(self) -> None:
        """Load invoices from project invoice directories and the central invoice directory."""
        self._invoices = {}  # Clear existing

        # 1. Load from project-specific invoice directories
        for short_name, project in self._projects.items():
            if project.budget_dir:
                # budget_dir is normally relative to the data directory
                budget_dir = Path(project.budget_dir)
                if not budget_dir.is_absolute():
                    budget_dir = self.data_dir / budget_dir
                invoice_dir = budget_dir / "invoices"
                if invoice_dir.exists():
                    invoice_files = find_invoices(invoice_dir)
                    for pdf_path in invoice_files:
                        invoice = _plugin_parse_invoice(pdf_path, self._invoice_parsers)
                        if invoice:
                            invoice.project_id = short_name
                            self._invoices.setdefault(short_name, []).append(invoice)

        # 2. Load from the central reports/invoices directory
        central_invoice_dir = self.reports_dir / "invoices"
        if central_invoice_dir.exists():
            central_files = find_invoices(central_invoice_dir)
            for pdf_path in central_files:
                invoice = _plugin_parse_invoice(pdf_path, self._invoice_parsers)
                if invoice:
                    resolved_id = self._resolve_project_id(invoice.project_id)
                    if resolved_id:
                        invoice.project_id = resolved_id
                        self._invoices.setdefault(resolved_id, []).append(invoice)
                    else:
                        self._parse_warnings.append(
                            ParseWarning(
                                file=str(pdf_path.name),
                                severity="warning",
                                code="INVOICE_NO_PROJECT",
                                message=f"Could not resolve project for invoice '{pdf_path.name}' (grant number: {invoice.grant_number or 'None'})",
                            )
                        )

        # 3. Sort all project invoices by period start
        for short_name in self._invoices:
            self._invoices[short_name].sort(key=lambda inv: inv.period_start)

    def load_all(self) -> None:
        """Load all data from manifest, budgets, reports, and invoices."""
        self.load_manifest()
        self.load_travel_config()
        self.load_purchases_config()
        self.load_budgets()
        self.load_reports()
        self.load_invoices()

    def get_project_travel(self, project_id: str) -> list[TravelItem]:
        """Get travel items for a specific project."""
        return sorted(
            [t for t in self._travel if t.project_id == project_id],
            key=lambda t: t.date if t.date else date.max,
        )

    def get_project_expenses(self, project_id: str) -> list[ExpenseItem]:
        """Get expense items for a specific project."""
        return [e for e in self._expenses if e.project_id == project_id]

    def get_project_invoices(self, project_id: str) -> list[Invoice]:
        """Get invoices for a specific project, sorted by period."""
        return self._invoices.get(project_id, [])

    def get_project(self, project_id: str) -> ProjectData | None:
        """
        Get complete data for a project.

        Args:
            project_id: Project short name (e.g., "ARTS")

        Returns:
            ProjectData with budget, spending, and personnel info
        """
        if project_id not in self._projects:
            return None

        project = self._projects[project_id]
        budget = self._budgets.get(project_id)
        spending = sorted(self._spending.get(project_id, []), key=lambda r: (r.year, r.month))
        personnel = self._personnel.get_project_personnel(project_id)

        return ProjectData(project=project, budget=budget, spending=spending, personnel=personnel)

    def list_projects(self, status: ProjectStatus | None = None) -> list[str]:
        """Get list of project short names, optionally filtered by status."""
        if status is not None:
            return sorted(name for name, proj in self._projects.items() if proj.status == status)
        return sorted(self._projects.keys())

    def get_personnel_tracker(self) -> PersonnelTracker:
        """Get the personnel tracker for cross-project queries."""
        return self._personnel

    def get_parse_warnings(self) -> list[ParseWarning]:
        """Return any warnings generated during report parsing."""
        return list(self._parse_warnings)

    def save_cache(self) -> None:
        """Save parsed data to JSON cache files."""
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        # Save budgets
        budgets_data = {}
        for project_id, budget in self._budgets.items():
            budgets_data[project_id] = {
                "project_id": budget.project_id,
                "total_direct_costs": str(budget.total_direct_costs),
                "total_indirect_costs": str(budget.total_indirect_costs),
                "total_budget": str(budget.total_budget),
                "lines": [
                    {"category": line.category, "year": line.year, "amount": str(line.amount)}
                    for line in budget.lines
                ],
            }
        with open(self.cache_dir / "budgets.json", "w") as f:
            json.dump(budgets_data, f, indent=2)

        # Save spending
        spending_data = {}
        for project_id, reports in self._spending.items():
            spending_data[project_id] = [
                {
                    "project_id": r.project_id,
                    "period": r.period,
                    "year": r.year,
                    "month": r.month,
                    "total_spent": str(r.total_spent),
                    "total_committed": str(r.total_committed),
                    "total_spent_and_committed": str(r.total_spent_and_committed),
                    "indirect_spent": str(r.indirect_spent),
                    "budget_utilized_pct": str(r.budget_utilized_pct)
                    if r.budget_utilized_pct
                    else None,
                    "total_month": str(r.total_month) if r.total_month is not None else None,
                    "salary_spent": str(r.salary_spent),
                    "fringe_spent": str(r.fringe_spent),
                    "tuition_spent": str(r.tuition_spent),
                    "insurance_spent": str(r.insurance_spent),
                    "service_center_spent": str(r.service_center_spent),
                    "travel_spent": str(r.travel_spent),
                    "travel_foreign_spent": str(r.travel_foreign_spent),
                    "supplies_spent": str(r.supplies_spent),
                    "equipment_spent": str(r.equipment_spent),
                    "subcontracts_spent": str(r.subcontracts_spent),
                    "consultant_spent": str(r.consultant_spent),
                    "other_spent": str(r.other_spent),
                    "salary_month": str(r.salary_month) if r.salary_month is not None else None,
                    "fringe_month": str(r.fringe_month) if r.fringe_month is not None else None,
                    "tuition_month": str(r.tuition_month) if r.tuition_month is not None else None,
                    "insurance_month": str(r.insurance_month)
                    if r.insurance_month is not None
                    else None,
                    "service_center_month": str(r.service_center_month)
                    if r.service_center_month is not None
                    else None,
                    "travel_month": str(r.travel_month) if r.travel_month is not None else None,
                    "travel_foreign_month": str(r.travel_foreign_month)
                    if r.travel_foreign_month is not None
                    else None,
                    "supplies_month": str(r.supplies_month)
                    if r.supplies_month is not None
                    else None,
                    "equipment_month": str(r.equipment_month)
                    if r.equipment_month is not None
                    else None,
                    "subcontracts_month": str(r.subcontracts_month)
                    if r.subcontracts_month is not None
                    else None,
                    "consultant_month": str(r.consultant_month)
                    if r.consultant_month is not None
                    else None,
                    "other_month": str(r.other_month) if r.other_month is not None else None,
                    "indirect_month": str(r.indirect_month)
                    if r.indirect_month is not None
                    else None,
                    "salary_committed": str(r.salary_committed),
                    "fringe_committed": str(r.fringe_committed),
                    "tuition_committed": str(r.tuition_committed),
                    "insurance_committed": str(r.insurance_committed),
                    "service_center_committed": str(r.service_center_committed),
                    "travel_committed": str(r.travel_committed),
                    "travel_foreign_committed": str(r.travel_foreign_committed),
                    "supplies_committed": str(r.supplies_committed),
                    "equipment_committed": str(r.equipment_committed),
                    "subcontracts_committed": str(r.subcontracts_committed),
                    "consultant_committed": str(r.consultant_committed),
                    "other_committed": str(r.other_committed),
                    "funded_ceiling": str(r.funded_ceiling) if r.funded_ceiling else None,
                    "total_revenue_received": str(r.total_revenue_received)
                    if r.total_revenue_received
                    else None,
                    "revenue_month": str(r.revenue_month) if r.revenue_month else None,
                    "budget_start_date": r.budget_start_date.isoformat()
                    if r.budget_start_date
                    else None,
                    "budget_end_date": r.budget_end_date.isoformat() if r.budget_end_date else None,
                    "grant_end_date": r.grant_end_date.isoformat() if r.grant_end_date else None,
                    "grantor_code": r.grantor_code,
                    "stated_idc_rate": str(r.stated_idc_rate) if r.stated_idc_rate else None,
                    "commitment_details": [
                        {
                            "person_name": c.person_name,
                            "type": c.employee_type.value,
                            "salary_committed": str(c.salary_committed),
                            "fringe_committed": str(c.fringe_committed),
                            "idc_committed": str(c.idc_committed),
                            "encumbrance_start": c.encumbrance_start.isoformat()
                            if c.encumbrance_start
                            else None,
                            "encumbrance_end": c.encumbrance_end.isoformat()
                            if c.encumbrance_end
                            else None,
                        }
                        for c in r.commitment_details
                    ],
                }
                for r in reports
            ]
        with open(self.cache_dir / "spending.json", "w") as f:
            json.dump(spending_data, f, indent=2)

        # Save personnel
        with open(self.cache_dir / "personnel.json", "w") as f:
            json.dump(self._personnel.to_dict(), f, indent=2)

    def dump_json(self, project_id: str) -> str:
        """
        Dump project data as pretty-printed JSON for manual verification.

        Args:
            project_id: Project short name

        Returns:
            JSON string
        """
        data = self.get_project(project_id)
        if not data:
            return json.dumps({"error": f"Project not found: {project_id}"})

        # One authoritative budget figure, so the project record and the budget
        # object cannot disagree (the manifest carries a rounded copy).
        from .budget_resolution import resolve_project_budget

        authoritative_budget, budget_source = resolve_project_budget(
            self, project_id, self.data_dir
        )

        # Convert to serializable dict
        result: dict[str, Any] = {
            "project": {
                "short_name": data.project.short_name,
                "name": data.project.name,
                "pi": data.project.pi,
                "type": data.project.project_type.value,
                "grant_number": data.project.grant_number,
                "award_id": data.project.award_id,
                "total_budget": str(authoritative_budget)
                if authoritative_budget > Decimal("0")
                else None,
                "total_budget_source": budget_source,
            },
            "budget": None,
            "spending": [],
            "personnel": [],
        }

        if data.budget:
            result["budget"] = {
                "total_direct_costs": str(data.budget.total_direct_costs),
                "total_indirect_costs": str(data.budget.total_indirect_costs),
                "total_budget": str(
                    authoritative_budget
                    if authoritative_budget > Decimal("0")
                    else data.budget.total_budget
                ),
                "lines": [
                    {"category": line.category, "year": line.year, "amount": str(line.amount)}
                    for line in data.budget.lines
                ],
            }
        elif authoritative_budget > Decimal("0"):
            result["budget"] = {
                "total_direct_costs": None,
                "total_indirect_costs": None,
                "total_budget": str(authoritative_budget),
                "lines": [],
            }
        else:
            # Check contractual budget YAML
            from .contractual_budget import load_contractual_budget

            b_path = self.data_dir / "projects" / project_id / "budget_config.yaml"
            if not b_path.exists() and data.project.budget_dir:
                cand = Path(data.project.budget_dir)
                b_path = (
                    cand / "budget_config.yaml"
                    if cand.is_absolute()
                    else self.data_dir / cand / "budget_config.yaml"
                )
            if b_path.exists():
                contract = load_contractual_budget(b_path)
                if contract:
                    result["budget"] = {
                        "total_direct_costs": str(contract.total_direct_costs),
                        "total_indirect_costs": str(contract.total_indirect_costs),
                        "total_budget": str(contract.total_budget),
                        "lines": [
                            {
                                "category": f"Year {p.year_num}",
                                "year": p.year_num,
                                "amount": str(p.total),
                            }
                            for p in contract.periods
                        ],
                    }

        for r in data.spending:
            result["spending"].append(
                {
                    "period": r.period,
                    "total_spent": str(r.total_spent),
                    "total_committed": str(r.total_committed),
                    "total_spent_and_committed": str(r.total_spent_and_committed),
                    "total_month": str(r.total_month) if r.total_month is not None else None,
                    "salary_spent": str(r.salary_spent),
                    "fringe_spent": str(r.fringe_spent),
                    "tuition_spent": str(r.tuition_spent),
                    "insurance_spent": str(r.insurance_spent),
                    "service_center_spent": str(r.service_center_spent),
                    "travel_spent": str(r.travel_spent),
                    "travel_foreign_spent": str(r.travel_foreign_spent),
                    "supplies_spent": str(r.supplies_spent),
                    "equipment_spent": str(r.equipment_spent),
                    "subcontracts_spent": str(r.subcontracts_spent),
                    "consultant_spent": str(r.consultant_spent),
                    "other_spent": str(r.other_spent),
                    "indirect_spent": str(r.indirect_spent),
                    "funded_ceiling": str(r.funded_ceiling) if r.funded_ceiling else None,
                    "total_revenue_received": str(r.total_revenue_received)
                    if r.total_revenue_received
                    else None,
                    "revenue_month": str(r.revenue_month) if r.revenue_month else None,
                    "budget_start_date": r.budget_start_date.isoformat()
                    if r.budget_start_date
                    else None,
                    "budget_end_date": r.budget_end_date.isoformat() if r.budget_end_date else None,
                    "grant_end_date": r.grant_end_date.isoformat() if r.grant_end_date else None,
                    "grantor_code": r.grantor_code,
                    "stated_idc_rate": str(r.stated_idc_rate) if r.stated_idc_rate else None,
                    "commitment_details": [
                        {
                            "person_name": c.person_name,
                            "type": c.employee_type.value,
                            "salary_committed": str(c.salary_committed),
                            "fringe_committed": str(c.fringe_committed),
                            "idc_committed": str(c.idc_committed),
                            "encumbrance_start": c.encumbrance_start.isoformat()
                            if c.encumbrance_start
                            else None,
                            "encumbrance_end": c.encumbrance_end.isoformat()
                            if c.encumbrance_end
                            else None,
                        }
                        for c in r.commitment_details
                    ],
                }
            )

        for a in data.personnel:
            result["personnel"].append(
                {
                    "person": a.person_name,
                    "period": a.period,
                    "salary": str(a.salary_amount),
                    "type": a.employee_type.value,
                    "gl_account": a.gl_account,
                    "wage_type": a.wage_type,
                    "pay_period_start": a.pay_period_start.isoformat()
                    if a.pay_period_start
                    else None,
                    "pay_period_end": a.pay_period_end.isoformat() if a.pay_period_end else None,
                }
            )

        return json.dumps(result, indent=2)
