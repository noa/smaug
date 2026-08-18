"""
Programmatic API for smaug budget data.

All methods return plain dicts/lists suitable for JSON serialization.
No terminal output, no Rich formatting, no ANSI codes.

This module is the single source of truth for business logic.
CLI commands delegate here for computation, then handle formatting.
"""

import contextlib
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

from .config import resolve_data_dir
from .models import ProjectStatus
from .store import ProjectStore


def _dec(val: Decimal | None) -> float | None:
    """Convert Decimal to float for JSON serialization."""
    if val is None:
        return None
    return float(val)


def _date_str(d: date | None) -> str | None:
    """Convert date to ISO string for JSON serialization."""
    if d is None:
        return None
    return d.strftime("%Y-%m")


class SmaugAPI:
    """Programmatic interface to smaug budget data.

    All methods return plain dicts/lists suitable for JSON serialization.
    No terminal output, no Rich formatting, no ANSI codes.
    """

    def __init__(self, data_dir: str | Path | None = None, anonymize: bool | None = None):
        if data_dir is None:
            self._data_dir = resolve_data_dir()
        else:
            self._data_dir = Path(data_dir).expanduser()
        self._store: ProjectStore | None = None

        # Check anonymize setting
        import os

        from .cli._util import Anonymizer

        anonymize_env = os.environ.get("SMAUG_ANONYMIZE", "").lower() in ("1", "true", "yes")
        anonymize_disabled = os.environ.get("SMAUG_ANONYMIZE", "").lower() in ("0", "false", "no")

        if anonymize_disabled:
            Anonymizer.enabled = False
        elif anonymize or (anonymize is None and anonymize_env):
            # Load store to initialize anonymizer
            store = self._get_store()

            class DummyArgs:
                anonymize = True

            Anonymizer.init(store, DummyArgs())

    @property
    def data_dir(self) -> str:
        return str(self._data_dir)

    def _get_store(self) -> ProjectStore:
        """Lazy-load and cache the ProjectStore."""
        if self._store is None:
            self._store = ProjectStore(self._data_dir)
            self._store.load_all()
        return self._store

    def _config_path(self) -> Path:
        return self._data_dir / "projects" / "personnel_config.yaml"

    def _sanitize_result(self, result: dict) -> dict:
        """Re-anonymize any real names that leaked into error messages or return values.

        When anonymization is enabled, CLI commands internally de-anonymize names
        (e.g. "PhD 1" → "Mahapatra, Aurosweta") to operate on the YAML config.
        If an error occurs, the real name can appear in the error message. This
        method scrubs those leaks before the result reaches the MCP layer.
        """
        from .cli._util import Anonymizer

        if not Anonymizer.enabled:
            return result

        def _scrub(value: object) -> object:
            if isinstance(value, str):
                # Replace any real names with their anonymized form.
                # Process longest names first to avoid partial replacements.
                for real_name in sorted(Anonymizer._real_to_anon, key=len, reverse=True):
                    if real_name in value:
                        value = value.replace(real_name, Anonymizer._real_to_anon[real_name])
                return value
            if isinstance(value, dict):
                return {k: _scrub(v) for k, v in value.items()}
            if isinstance(value, list):
                return [_scrub(v) for v in value]
            return value

        return _scrub(result)  # type: ignore[return-value]

    @staticmethod
    @contextlib.contextmanager
    def _suppress_stdout():
        """Suppress stdout during CLI command execution.

        CLI write commands use print() for informational messages (e.g.
        "Resolved 'PhD 1' to: Mahapatra, Aurosweta"). When running under
        the MCP server (stdio transport), these print() calls would both
        leak real names and corrupt the JSON-RPC protocol stream.
        """
        import io

        old_stdout = sys.stdout
        buf = io.StringIO()
        sys.stdout = buf
        try:
            yield buf
        finally:
            sys.stdout = old_stdout

    def _load_personnel_config(self):
        from .projections import load_personnel_config

        path = self._config_path()
        if path.exists():
            return load_personnel_config(path)
        return None, []

    def list_projects(self, status: str | None = None) -> list[dict]:
        """List all projects with budget summaries and burn rates.

        Args:
            status: Filter by lifecycle status ('proposed', 'accepted',
                    'active', 'completed'). Default: 'active' only.

        Returns:
            List of dicts with keys: id, name, status, end_date, budget,
            spent, pct_spent, monthly_burn, projected_total, projected_remaining.
        """
        from .projections import load_personnel_config, project_monthly_costs

        store = self._get_store()
        store.load_travel_config()
        store.load_purchases_config()

        if status:
            ps = ProjectStatus(status)
            project_ids = store.list_projects(status=ps)
        else:
            project_ids = store.list_projects(status=ProjectStatus.ACTIVE)

        config_path = self._config_path()
        from .projections import PersonnelEntry, Rates

        rates: Rates | None = None
        personnel: list[PersonnelEntry] = []
        if config_path.exists():
            rates, personnel = load_personnel_config(config_path)

        results = []
        for project_id in project_ids:
            data = store.get_project(project_id)
            if not data:
                continue

            budget = Decimal("0")
            if data.budget:
                budget = data.budget.total_budget
            elif data.project.total_budget:
                budget = data.project.total_budget

            spent = Decimal("0")
            if data.spending:
                latest = max(data.spending, key=lambda r: (r.year, r.month))
                spent = latest.total_spent

            monthly_burn = Decimal("0")
            proj_total = Decimal("0")
            project_end = data.project.end_date

            if rates and personnel and data.project.status == ProjectStatus.ACTIVE:
                with contextlib.suppress(Exception):
                    today = date.today()
                    current = today.replace(day=1)
                    travel_items = store.get_project_travel(project_id)
                    expense_items = store.get_project_expenses(project_id)

                    for _ in range(60):
                        if project_end and current >= project_end:
                            break
                        proj = project_monthly_costs(
                            project_id,
                            rates,
                            personnel,
                            current.year,
                            current.month,
                            travel_items,
                            expense_items,
                        )
                        if current.year == today.year and current.month == today.month:
                            monthly_burn = proj.total
                        if proj.total == 0:
                            break
                        proj_total += proj.total
                        if current.month == 12:
                            current = current.replace(year=current.year + 1, month=1)
                        else:
                            current = current.replace(month=current.month + 1)

            remaining = budget - spent - proj_total if budget else Decimal("0")
            pct_spent = float(spent / budget * 100) if budget and spent else 0.0

            results.append(
                {
                    "id": project_id,
                    "name": data.project.name,
                    "status": data.project.status.value,
                    "end_date": _date_str(project_end),
                    "budget": _dec(budget),
                    "spent": _dec(spent),
                    "pct_spent": round(pct_spent, 1),
                    "monthly_burn": _dec(monthly_burn),
                    "projected_total": _dec(proj_total),
                    "projected_remaining": _dec(remaining),
                }
            )

        return results

    def project_status(self, project: str) -> dict:
        """Detailed budget vs. actuals for a single project.

        Returns:
            Dict with keys: project, budget, latest_spending, categories,
            remaining, pct_remaining.
        """
        store = self._get_store()
        data = store.get_project(project)
        if not data:
            return {"error": f"Project not found: {project}"}

        from .cli._util import Anonymizer

        result: dict = {
            "project": {
                "id": data.project.short_name,
                "name": data.project.name,
                "pi": Anonymizer.anonymize(data.project.pi),
                "type": data.project.project_type.value,
                "status": data.project.status.value,
                "grant_number": data.project.grant_number,
                "award_id": data.project.award_id,
                "end_date": _date_str(data.project.end_date),
            },
            "budget": None,
            "latest_spending": None,
            "categories": None,
            "remaining": None,
            "pct_remaining": None,
        }

        if data.budget:
            result["budget"] = {
                "total_direct_costs": _dec(data.budget.total_direct_costs),
                "total_indirect_costs": _dec(data.budget.total_indirect_costs),
                "total_budget": _dec(data.budget.total_budget),
            }

        if data.spending:
            latest = data.spending[-1]
            result["latest_spending"] = {
                "period": latest.period,
                "total_spent": _dec(latest.total_spent),
                "total_committed": _dec(latest.total_committed),
                "total_spent_and_committed": _dec(latest.total_spent_and_committed),
                "budget_utilized_pct": _dec(latest.budget_utilized_pct),
                "funded_ceiling": _dec(latest.funded_ceiling),
            }
            result["categories"] = {
                "salary": _dec(latest.salary_spent),
                "fringe": _dec(latest.fringe_spent),
                "tuition": _dec(latest.tuition_spent),
                "insurance": _dec(latest.insurance_spent),
                "service_center": _dec(latest.service_center_spent),
                "travel": _dec(latest.travel_spent),
                "other": _dec(latest.other_spent),
                "indirect": _dec(latest.indirect_spent),
            }
            if data.budget and data.budget.total_budget > 0:
                remaining = data.budget.total_budget - latest.total_spent_and_committed
                result["remaining"] = _dec(remaining)
                result["pct_remaining"] = round(
                    float(remaining / data.budget.total_budget * 100), 1
                )

        return result

    def spending_report(self, project: str) -> dict:
        """Monthly spending breakdown from parsed reports.

        Returns:
            Dict with keys: project, periods (list of spending records),
            personnel_totals.
        """
        store = self._get_store()
        data = store.get_project(project)
        if not data:
            return {"error": f"Project not found: {project}"}

        periods = []
        for report in data.spending:
            periods.append(
                {
                    "period": report.period,
                    "year": report.year,
                    "month": report.month,
                    "total_spent": _dec(report.total_spent),
                    "total_committed": _dec(report.total_committed),
                    "total_spent_and_committed": _dec(report.total_spent_and_committed),
                }
            )

        from .cli._util import Anonymizer

        personnel_totals: dict[str, float] = {}
        for alloc in data.personnel:
            anon_name = Anonymizer.anonymize(alloc.person_name) or alloc.person_name
            personnel_totals[anon_name] = personnel_totals.get(anon_name, 0.0) + float(
                alloc.salary_amount
            )

        return {
            "project": project,
            "periods": periods,
            "personnel_totals": personnel_totals,
        }

    def dump_project(self, project: str) -> dict:
        """Raw project data as dict.

        Returns:
            Complete project data including budget, spending, and personnel.
        """
        import json

        store = self._get_store()
        json_str = store.dump_json(project)
        return dict(json.loads(json_str))

    def spending_projection(
        self, project: str, months: int = 12, end_date: str | None = None
    ) -> dict:
        """Monthly forward projections based on current config.

        Args:
            project: Project short name.
            months: Number of months to project (default 12).
            end_date: End date as YYYY-MM (overrides months).

        Returns:
            Dict with keys: project, projections (list), totals.
        """
        from .cli._util import Anonymizer
        from .projections import project_spending

        store = self._get_store()
        store.load_travel_config()
        store.load_purchases_config()

        travel_items = store.get_project_travel(project)
        expense_items = store.get_project_expenses(project)

        parsed_end = None
        if end_date:
            parts = end_date.split("-")
            parsed_end = date(int(parts[0]), int(parts[1]), 1)

        projections = project_spending(
            project_id=project,
            config_path=self._config_path(),
            end_date=parsed_end,
            months=months,
            travel_items=travel_items,
            expense_items=expense_items,
        )

        proj_list = []
        totals = {
            "salary": 0.0,
            "fringe": 0.0,
            "travel": 0.0,
            "compute": 0.0,
            "equipment": 0.0,
            "other": 0.0,
            "indirect": 0.0,
            "total": 0.0,
        }
        for p in projections:
            entry = {
                "month": f"{p.year}-{p.month:02d}",
                "salary": _dec(p.direct_salary),
                "fringe": _dec(p.fringe),
                "tuition": _dec(p.tuition),
                "insurance": _dec(p.insurance),
                "travel": _dec(p.travel),
                "compute": _dec(p.compute),
                "equipment": _dec(p.equipment),
                "other": _dec(p.other_direct),
                "indirect": _dec(p.indirect),
                "total": _dec(p.total),
                "personnel": [
                    {"name": Anonymizer.anonymize(name), "amount": _dec(amt)}
                    for name, amt in p.personnel
                ],
            }
            proj_list.append(entry)
            for key in totals:
                val = entry.get(key)
                if isinstance(val, int | float):
                    totals[key] += float(val)

        return {
            "project": project,
            "projections": proj_list,
            "totals": {k: round(v, 2) for k, v in totals.items()},
        }

    def stopwork_forecast(self, project: str, ceiling: float | None = None) -> dict:
        """Predict fund exhaustion date under current spend rate.

        Args:
            project: Project short name.
            ceiling: Override funding ceiling amount.

        Returns:
            Dict with keys: project, ceiling, ceiling_source,
            cumulative_spent, stop_month, stop_day, monthly_projections.
        """
        from .projections import project_spending

        store = self._get_store()
        data = store.get_project(project)
        if not data:
            return {"error": f"Project not found: {project}"}

        if not data.spending:
            return {"error": f"No spending reports found for {project}"}

        latest = data.spending[-1]

        if ceiling is not None:
            effective_ceiling = Decimal(str(ceiling))
            ceiling_source = "user-provided"
        elif latest.funded_ceiling:
            effective_ceiling = latest.funded_ceiling
            ceiling_source = "report"
        elif data.budget and data.budget.total_budget:
            effective_ceiling = data.budget.total_budget
            ceiling_source = "budget"
        else:
            return {"error": "No funded ceiling or budget found"}

        cumulative = latest.total_spent

        store.load_travel_config()
        store.load_purchases_config()
        travel_items = store.get_project_travel(project)
        expense_items = store.get_project_expenses(project)

        start = date(latest.year, latest.month, 1)
        if start.month == 12:
            start = start.replace(year=start.year + 1, month=1)
        else:
            start = start.replace(month=start.month + 1)

        projections = project_spending(
            project,
            self._config_path(),
            start_date=start,
            months=18,
            travel_items=travel_items,
            expense_items=expense_items,
        )

        stop_month = None
        stop_day = None
        monthly = []

        for proj in projections:
            burn = proj.total
            cumulative += burn
            remaining = effective_ceiling - cumulative
            month_str = f"{proj.year}-{proj.month:02d}"

            status = "ok"
            if remaining < 0:
                status = "stop-work"
                if stop_month is None:
                    stop_month = month_str
                    if burn > 0:
                        frac = (remaining + burn) / burn
                        frac = max(Decimal("0"), min(frac, Decimal("1")))
                        day = int(frac * 30)
                        stop_day = f"~day {day} of {month_str}"

            monthly.append(
                {
                    "month": month_str,
                    "projected": _dec(burn),
                    "cumulative": _dec(cumulative),
                    "remaining": _dec(remaining),
                    "status": status,
                }
            )

            if status == "stop-work":
                # Show 1 more month after stop-work
                count_after = sum(1 for m in monthly if m["status"] == "stop-work")
                if count_after >= 2:
                    break

        return {
            "project": project,
            "ceiling": _dec(effective_ceiling),
            "ceiling_source": ceiling_source,
            "cumulative_spent": _dec(latest.total_spent),
            "stop_month": stop_month,
            "stop_day": stop_day,
            "monthly_projections": monthly,
        }

    def audit(self, project: str | None = None, months: int = 3, threshold: float = 10.0) -> dict:
        """Flag discrepancies between expected and actual effort.

        Args:
            project: Project short name (or None for all projects).
            months: Months to look back (default 3).
            threshold: Variance threshold % to flag (default 10).

        Returns:
            Dict with keys: project, periods, findings, summary.
        """
        from .audit import audit_project

        store = self._get_store()
        config_path = self._config_path()

        if not config_path.exists():
            return {"error": "Personnel config not found"}

        tracker = store.get_personnel_tracker()
        all_allocations = []
        for person_name in tracker.get_all_personnel():
            all_allocations.extend(tracker.get_person_effort(person_name))

        projects_to_audit = [project] if project else store.list_projects()
        all_findings = []

        for pid in projects_to_audit:
            report = audit_project(
                project_id=pid,
                config_path=config_path,
                actual_allocations=all_allocations,
                months_back=months,
                threshold_pct=Decimal(str(threshold)),
            )
            from .cli._util import Anonymizer

            for f in report.findings:
                msg = f.message
                if Anonymizer.enabled:
                    for real_name, anon_name in Anonymizer._real_to_anon.items():
                        msg = msg.replace(real_name, anon_name)
                all_findings.append(
                    {
                        "type": f.finding_type.value,
                        "person": Anonymizer.anonymize(f.person_name),
                        "project": f.project_id,
                        "period": f.period,
                        "message": msg,
                        "severity": f.severity,
                        "expected": _dec(f.expected_amount),
                        "actual": _dec(f.actual_amount),
                        "variance_pct": _dec(f.variance_pct),
                    }
                )

        errors = sum(1 for f in all_findings if f["severity"] == "error")
        warnings = sum(1 for f in all_findings if f["severity"] == "warning")
        info = sum(1 for f in all_findings if f["severity"] == "info")

        return {
            "project": project,
            "findings": all_findings,
            "summary": {"errors": errors, "warnings": warnings, "info": info},
        }

    def proposal_budget(
        self,
        pi: list[dict] | None = None,
        phd: int = 0,
        masters: int = 0,
        years: int = 3,
        travel: float = 0,
        compute: float = 0,
        annotation: float = 0,
        equipment: float = 0,
        other: float = 0,
        escalation: float = 3.0,
    ) -> dict:
        """Generate a hypothetical proposal budget.

        Args:
            pi: List of PI specs, e.g. [{"name": "Smith", "effort_pct": 10}].
            phd: Number of PhD students at 100% effort.
            masters: Number of Masters students.
            years: Budget years (default 3).
            travel: Annual travel budget.
            compute: Annual compute costs.
            annotation: Annual annotation costs.
            equipment: Equipment (year 1 only).
            other: Other direct costs per year.
            escalation: Annual salary escalation % (default 3.0).

        Returns:
            Dict with keys: years (list), personnel_detail, grand_total,
            idc_rate, total_direct, total_idc.
        """
        from .proposal_budget import (
            ProposalPerson,
            generate_proposal_budget,
            load_proposal_rates,
            resolve_salary,
        )

        rates_config = load_proposal_rates(self._data_dir)
        personnel_config_path = self._config_path()

        people: list[ProposalPerson] = []

        from .cli._util import Anonymizer

        if pi:
            for spec in pi:
                name = spec["name"]
                effort = Decimal(str(spec["effort_pct"])) / 100
                salary, resolved = resolve_salary(
                    name, "faculty", personnel_config_path, rates_config
                )
                people.append(
                    ProposalPerson(
                        label=f"{Anonymizer.anonymize(resolved)} (PI)",
                        person_type="faculty",
                        effort=effort,
                        annual_salary=salary,
                    )
                )

        if phd:
            gs_costs = rates_config.get("grad_student_costs", {})
            stipend = Decimal(str(gs_costs.get("stipend", 50000)))
            for i in range(phd):
                people.append(
                    ProposalPerson(
                        label=f"PhD Student #{i + 1}",
                        person_type="grad_student",
                        effort=Decimal("1.0"),
                        annual_salary=stipend,
                    )
                )

        if masters:
            hourly = Decimal(str(rates_config.get("masters_hourly", 20)))
            hrs = Decimal(str(rates_config.get("masters_hours_per_week", 20)))
            annual = hourly * hrs * 52
            for i in range(masters):
                people.append(
                    ProposalPerson(
                        label=f"Masters Student #{i + 1}",
                        person_type="part_time",
                        effort=Decimal("1.0"),
                        annual_salary=annual,
                        student_type="masters",
                    )
                )

        if not people:
            return {"error": "No personnel specified"}

        budget = generate_proposal_budget(
            people=people,
            rates_config=rates_config,
            num_years=years,
            travel_per_year=Decimal(str(travel)),
            compute_per_year=Decimal(str(compute)),
            annotation_per_year=Decimal(str(annotation)),
            equipment_year1=Decimal(str(equipment)),
            other_per_year=Decimal(str(other)),
            salary_escalation=Decimal(str(escalation / 100)),
        )

        year_list = []
        for yb in budget.years:
            year_list.append(
                {
                    "year": yb.year_num,
                    "salary": _dec(yb.salary),
                    "fringe": _dec(yb.fringe),
                    "tuition": _dec(yb.tuition),
                    "insurance": _dec(yb.insurance),
                    "travel": _dec(yb.travel),
                    "compute": _dec(yb.compute),
                    "annotation": _dec(yb.annotation),
                    "equipment": _dec(yb.equipment),
                    "other": _dec(yb.other),
                    "total_direct": _dec(yb.total_direct),
                    "mtdc": _dec(yb.mtdc),
                    "idc": _dec(yb.idc(budget.idc_rate)),
                    "total": _dec(yb.total_with_idc(budget.idc_rate)),
                }
            )

        detail = {}
        for year_num, persons in budget.personnel_detail.items():
            detail[year_num] = [
                {
                    "label": p.label,
                    "type": p.person_type,
                    "effort": _dec(p.effort),
                    "salary": _dec(p.salary),
                    "fringe": _dec(p.fringe),
                    "tuition": _dec(p.tuition),
                    "insurance": _dec(p.insurance),
                    "total": _dec(p.total),
                }
                for p in persons
            ]

        return {
            "years": year_list,
            "personnel_detail": detail,
            "idc_rate": _dec(budget.idc_rate),
            "total_direct": _dec(budget.total_direct),
            "total_idc": _dec(budget.total_idc),
            "grand_total": _dec(budget.grand_total),
        }

    def list_project_notes(self, project: str) -> list[dict]:
        """List all notes for a project."""
        from .notes import list_notes

        notes = list_notes(self.data_dir, project)
        return [
            {
                "index": idx,
                "title": n.title,
                "filename": n.filename,
                "created": n.created.isoformat(),
                "tags": n.tags,
            }
            for idx, n in enumerate(notes, 1)
        ]

    def show_project_note(self, project: str, identifier: str) -> dict:
        """Show contents of a specific project note."""
        from .notes import show_note

        content, err = show_note(self.data_dir, project, identifier)
        if err:
            return {"error": err}
        return {"content": content}

    def add_project_note(
        self, project: str, title: str, content: str, tags: list[str] | None = None
    ) -> dict:
        """Add a new project note."""
        from .notes import add_note

        try:
            path = add_note(self.data_dir, project, title, content, tags)
            return {"success": True, "filename": path.name}
        except Exception as e:
            return {"error": str(e)}

    def remove_project_note(self, project: str, identifier: str) -> dict:
        """Remove a project note."""
        from .notes import remove_note

        title, err = remove_note(self.data_dir, project, identifier)
        if err:
            return {"error": err}
        return {"success": True, "title": title}

    def set_personnel_effort(
        self,
        name: str,
        project: str,
        effort_pct: float,
        start: str | None = None,
        end: str | None = None,
    ) -> dict:
        """Set effort for a person on a project.

        Args:
            name: Person name (fuzzy matching supported).
            project: Project short name.
            effort_pct: Effort as percentage (e.g. 25 for 25%).
            start: Optional start date as YYYY-MM. When provided with end,
                creates a new date-bounded assignment instead of modifying
                the existing one.
            end: Optional end date as YYYY-MM.
        """
        from .cli._write_commands import cmd_set_effort

        class DummyArgs:
            def __init__(self, **kwargs):
                for k, v in kwargs.items():
                    setattr(self, k, v)

        with self._suppress_stdout():
            try:
                cmd_set_effort(
                    self._get_store(),
                    DummyArgs(
                        data_dir=self.data_dir,
                        name=name,
                        project=project,
                        effort=str(effort_pct),
                        start=start,
                        end=end,
                    ),
                )
                self._store = None  # Invalidate cache so reads reflect the write
                return self._sanitize_result(
                    {
                        "success": True,
                        "name": name,
                        "project": project,
                        "effort_pct": effort_pct,
                    }
                )
            except Exception as e:
                return self._sanitize_result({"error": str(e)})

    def remove_personnel_effort(
        self,
        name: str,
        project: str,
        start: str | None = None,
        end: str | None = None,
    ) -> dict:
        """Remove an effort assignment for a person on a project.

        Args:
            name: Person name (fuzzy matching supported).
            project: Project short name.
            start: Optional start date as YYYY-MM.
            end: Optional end date as YYYY-MM.
        """
        from .cli._write_commands import cmd_remove_effort

        class DummyArgs:
            def __init__(self, **kwargs):
                for k, v in kwargs.items():
                    setattr(self, k, v)

        with self._suppress_stdout():
            try:
                cmd_remove_effort(
                    self._get_store(),
                    DummyArgs(
                        data_dir=self.data_dir,
                        name=name,
                        project=project,
                        start=start,
                        end=end,
                    ),
                )
                self._store = None  # Invalidate cache so reads reflect the write
                return self._sanitize_result({"success": True, "name": name, "project": project})
            except Exception as e:
                return self._sanitize_result({"error": str(e)})

    def set_personnel_type(self, name: str, person_type: str) -> dict:
        """Set or update personnel type for a person."""
        from .cli._write_commands import cmd_set_type

        class DummyArgs:
            def __init__(self, **kwargs):
                for k, v in kwargs.items():
                    setattr(self, k, v)

        with self._suppress_stdout():
            try:
                cmd_set_type(
                    self._get_store(),
                    DummyArgs(
                        data_dir=self.data_dir,
                        name=name,
                        type=person_type,
                    ),
                )
                self._store = None  # Invalidate cache so reads reflect the write
                return self._sanitize_result({"success": True, "name": name, "type": person_type})
            except Exception as e:
                return self._sanitize_result({"error": str(e)})

    def add_personnel(
        self,
        name: str,
        person_type: str,
        project: str,
        effort_pct: float,
        salary: int | None = None,
        hours: float | None = None,
        start: str | None = None,
        end: str | None = None,
    ) -> dict:
        """Add a new person."""
        from .cli._write_commands import cmd_add_person

        class DummyArgs:
            def __init__(self, **kwargs):
                for k, v in kwargs.items():
                    setattr(self, k, v)

        with self._suppress_stdout():
            try:
                cmd_add_person(
                    self._get_store(),
                    DummyArgs(
                        data_dir=self.data_dir,
                        name=name,
                        type=person_type,
                        project=project,
                        effort=str(effort_pct),
                        salary=str(salary) if salary is not None else None,
                        hours=hours,
                        start=start,
                        end=end,
                    ),
                )
                self._store = None  # Invalidate cache so reads reflect the write
                res = {
                    "success": True,
                    "name": name,
                    "type": person_type,
                    "project": project,
                    "effort_pct": effort_pct,
                }
                if hours is not None:
                    res["hours"] = hours
                return self._sanitize_result(res)
            except Exception as e:
                return self._sanitize_result({"error": str(e)})

    def add_travel_item(
        self,
        project: str,
        description: str,
        date_str: str,
        amount: float,
        traveler: str | None = None,
    ) -> dict:
        """Add a travel item."""
        from .cli._operational import cmd_travel

        class DummyArgs:
            def __init__(self, **kwargs):
                for k, v in kwargs.items():
                    setattr(self, k, v)

        with self._suppress_stdout():
            try:
                cmd_travel(
                    self._get_store(),
                    DummyArgs(
                        data_dir=self.data_dir,
                        action="add",
                        project=project,
                        description=description,
                        date=date_str,
                        amount=str(amount),
                        traveler=traveler,
                    ),
                )
                self._store = None  # Invalidate cache so reads reflect the write
                return self._sanitize_result(
                    {"success": True, "project": project, "description": description}
                )
            except Exception as e:
                return self._sanitize_result({"error": str(e)})

    def add_expense_item(
        self,
        project: str,
        description: str,
        amount: float,
        category: str = "Other",
        date_str: str | None = None,
        start_str: str | None = None,
        end_str: str | None = None,
    ) -> dict:
        """Add an expense item."""
        from .cli._operational import cmd_expense

        class DummyArgs:
            def __init__(self, **kwargs):
                for k, v in kwargs.items():
                    setattr(self, k, v)

        with self._suppress_stdout():
            try:
                cmd_expense(
                    self._get_store(),
                    DummyArgs(
                        data_dir=self.data_dir,
                        action="add",
                        project=project,
                        description=description,
                        amount=str(amount),
                        category=category,
                        date=date_str,
                        start=start_str,
                        end=end_str,
                    ),
                )
                self._store = None  # Invalidate cache so reads reflect the write
                return self._sanitize_result(
                    {"success": True, "project": project, "description": description}
                )
            except Exception as e:
                return self._sanitize_result({"error": str(e)})

    def remove_expense_item(self, project: str, description: str) -> dict:
        """Remove an expense item, identified by project and description."""
        from .cli._operational import cmd_expense

        class DummyArgs:
            def __init__(self, **kwargs):
                for k, v in kwargs.items():
                    setattr(self, k, v)

        with self._suppress_stdout() as captured:
            try:
                cmd_expense(
                    self._get_store(),
                    DummyArgs(
                        data_dir=self.data_dir,
                        action="remove",
                        project=project,
                        description=description,
                    ),
                )
                output = captured.getvalue()
                if "Error:" in output:
                    return self._sanitize_result({"error": output.strip()})
                self._store = None  # Invalidate cache so reads reflect the write
                return self._sanitize_result(
                    {"success": True, "project": project, "description": description}
                )
            except Exception as e:
                return self._sanitize_result({"error": str(e)})

    def edit_expense_item(
        self,
        project: str,
        description: str,
        amount: float | None = None,
        new_description: str | None = None,
        category: str | None = None,
        date_str: str | None = None,
        start_str: str | None = None,
        end_str: str | None = None,
    ) -> dict:
        """Edit an existing expense item, identified by project and description."""
        from .cli._operational import cmd_expense

        class DummyArgs:
            def __init__(self, **kwargs):
                for k, v in kwargs.items():
                    setattr(self, k, v)

        with self._suppress_stdout() as captured:
            try:
                cmd_expense(
                    self._get_store(),
                    DummyArgs(
                        data_dir=self.data_dir,
                        action="edit",
                        project=project,
                        description=description,
                        amount=amount,
                        new_description=new_description,
                        category=category,
                        date=date_str,
                        start=start_str,
                        end=end_str,
                    ),
                )
                output = captured.getvalue()
                if "Error:" in output:
                    return self._sanitize_result({"error": output.strip()})
                self._store = None  # Invalidate cache so reads reflect the write
                return self._sanitize_result(
                    {
                        "success": True,
                        "project": project,
                        "description": new_description or description,
                    }
                )
            except Exception as e:
                return self._sanitize_result({"error": str(e)})

    def spend_plan(
        self,
        projects: list[str],
        months: int | None = None,
        fy: int | None = None,
        add_personnel: list[dict] | None = None,
        override_effort: list[dict] | None = None,
    ) -> dict:
        """Generate monthly spend plan with optional hypotheticals."""
        from .cli._util import Anonymizer, load_aliases
        from .projections import (
            apply_hypotheticals,
            load_personnel_config,
            parse_hypothetical,
            project_spending,
        )

        project = projects[0]
        store = self._get_store()
        store.load_travel_config()
        store.load_purchases_config()

        travel_items = store.get_project_travel(project)
        expense_items = store.get_project_expenses(project)

        # 1. Parse and compile hypotheticals
        hypothetical_specs = []
        if add_personnel:
            for item in add_personnel:
                ptype = item.get("type", "phd")
                effort = item.get("effort_pct", 100)
                salary = item.get("salary")
                start = item.get("start")
                end = item.get("end")
                spec = f"+{ptype}@{effort}%"
                if salary:
                    spec += f":{salary}"
                if start or end:
                    spec += f"@{start or ''}"
                    if end:
                        spec += f":{end}"
                hypothetical_specs.append(spec)
        if override_effort:
            for item in override_effort:
                name = item.get("name")
                real_name = Anonymizer.resolve(name) if name else name
                effort = item.get("effort_pct", 100)
                start = item.get("start")
                end = item.get("end")
                if real_name:
                    spec = f"{real_name}={effort}%"
                    if start or end:
                        spec += f"@{start or ''}"
                        if end:
                            spec += f":{end}"
                    hypothetical_specs.append(spec)

        # 2. Apply hypotheticals
        rates_config, personnel = load_personnel_config(self._config_path())
        active_personnel = personnel
        if hypothetical_specs:
            try:
                hypotheticals = [parse_hypothetical(spec) for spec in hypothetical_specs]
                aliases = load_aliases(self.data_dir)
                active_personnel = apply_hypotheticals(
                    personnel, hypotheticals, project, rates_config, aliases=aliases
                )
            except Exception as e:
                return {"error": f"Failed to apply hypotheticals: {e}"}

        # 3. Determine start/end date
        from datetime import date

        start_date = date.today().replace(day=1)
        end_date = None

        if fy:
            start_date = date(fy - 1, 7, 1)
            end_date = date(fy, 7, 1)
            months_count = 12
        else:
            months_count = months or 12

        projections = project_spending(
            project_id=project,
            config_path=self._config_path(),
            start_date=start_date,
            end_date=end_date,
            months=months_count,
            travel_items=travel_items,
            expense_items=expense_items,
            personnel_overrides=active_personnel,
        )

        proj_list = []
        totals = {
            "salary": 0.0,
            "fringe": 0.0,
            "travel": 0.0,
            "compute": 0.0,
            "equipment": 0.0,
            "other": 0.0,
            "indirect": 0.0,
            "total": 0.0,
        }
        for p in projections:
            entry = {
                "month": f"{p.year}-{p.month:02d}",
                "salary": float(p.direct_salary),
                "fringe": float(p.fringe),
                "tuition": float(p.tuition),
                "insurance": float(p.insurance),
                "travel": float(p.travel),
                "compute": float(p.compute),
                "equipment": float(p.equipment),
                "other": float(p.other_direct),
                "indirect": float(p.indirect),
                "total": float(p.total),
                "personnel": [
                    {"name": Anonymizer.anonymize(name), "amount": float(amt)}
                    for name, amt in p.personnel
                ],
            }
            proj_list.append(entry)
            for key in totals:
                val = entry.get(key)
                if isinstance(val, int | float):
                    totals[key] += float(val)

        return {
            "project": project,
            "projections": proj_list,
            "totals": {k: round(v, 2) for k, v in totals.items()},
        }

    # ------------------------------------------------------------------
    # Personnel overview
    # ------------------------------------------------------------------

    def personnel_overview(self, project: str | None = None) -> dict:
        """Return personnel effort allocations and spending.

        Args:
            project: Optional project filter.
        """
        from .cli._util import Anonymizer
        from .projections import load_personnel_config

        store = self._get_store()
        tracker = store.get_personnel_tracker()
        config_path = self._config_path()

        personnel_list: list[dict] = []

        if not config_path.exists():
            return {"error": f"Personnel config not found: {config_path}"}

        _, config_personnel = load_personnel_config(config_path)

        for person in config_personnel:
            assignments = []
            has_matching_project = False
            for a in person.assignments:
                if project and a.project != project:
                    continue
                has_matching_project = True
                assignments.append(
                    {
                        "project": a.project,
                        "effort": float(a.effort),
                        "start": _date_str(a.start),
                        "end": _date_str(a.end),
                    }
                )

            if project and not has_matching_project:
                continue

            # Spending from reports
            by_project = tracker.get_person_by_project(person.name)
            if project:
                total_spent = float(by_project.get(project, Decimal("0")))
            else:
                total_spent = float(sum(by_project.values(), Decimal("0")))

            total_effort: float = sum(
                float(a.effort) for a in person.assignments if not project or a.project == project
            )

            personnel_list.append(
                {
                    "name": Anonymizer.anonymize(person.name),
                    "type": person.person_type,
                    "annual_salary": float(person.annual_salary),
                    "total_effort": round(total_effort, 4),
                    "departure": _date_str(person.departure),
                    "assignments": assignments,
                    "total_spent": round(total_spent, 2),
                    "salaries": [
                        {
                            "amount": float(s.amount),
                            "start": _date_str(s.start),
                            "end": _date_str(s.end),
                        }
                        for s in person.salaries
                    ]
                    if person.salaries
                    else [],
                }
            )

        return {
            "personnel": personnel_list,
            "count": len(personnel_list),
            "filter_project": project,
        }

    # ------------------------------------------------------------------
    # Funding summary
    # ------------------------------------------------------------------

    def funding_summary(self, fy: int | None = None) -> dict:
        """Aggregate spending across all sponsored projects.

        Args:
            fy: Fiscal year (e.g. 2026 = Jul 2025 - Jun 2026).
        """
        from .projections import load_personnel_config, project_monthly_costs

        store = self._get_store()
        config_path = self._config_path()

        if not config_path.exists():
            return {"error": f"Personnel config not found: {config_path}"}

        rates, personnel = load_personnel_config(config_path)
        store.load_travel_config()
        store.load_purchases_config()

        today = date.today()
        if fy:
            range_start = date(fy - 1, 7, 1)
            range_end = date(fy, 6, 1)
            range_label = f"FY {fy} (Jul {fy - 1} - Jun {fy})"
        else:
            range_start = date(today.year, 1, 1)
            range_end = date(today.year, 12, 1)
            range_label = f"{range_start.strftime('%b %Y')} - {range_end.strftime('%b %Y')}"

        # Collect sponsored projects
        sponsored = []
        for pid in store.list_projects():
            data = store.get_project(pid)
            if data and data.project.project_type.value == "sponsored":
                sponsored.append((pid, data))

        if not sponsored:
            return {
                "range_label": range_label,
                "projects": [],
                "grand_actual": 0,
                "grand_projected": 0,
                "grand_total": 0,
            }

        def _build_actuals(data, rs: date) -> dict[tuple[int, int], Decimal]:
            reports = sorted(data.spending, key=lambda r: (r.year, r.month))
            actuals: dict[tuple[int, int], Decimal] = {}
            baseline = Decimal("0")
            for r in reports:
                if date(r.year, r.month, 1) < rs:
                    baseline = r.total_spent
            prev = baseline
            for r in reports:
                if date(r.year, r.month, 1) < rs:
                    continue
                actuals[(r.year, r.month)] = r.total_spent - prev
                prev = r.total_spent
            return actuals

        rows = []
        grand_actual = Decimal("0")
        grand_projected = Decimal("0")

        current_month = today.replace(day=1)

        for pid, data in sponsored:
            actuals = _build_actuals(data, range_start)
            travel_items = store.get_project_travel(pid)
            expense_items = store.get_project_expenses(pid)

            proj_actual = Decimal("0")
            proj_projected = Decimal("0")

            cur = date(range_start.year, range_start.month, 1)
            while cur <= range_end:
                key = (cur.year, cur.month)
                if key in actuals:
                    proj_actual += actuals[key]
                elif cur >= current_month:
                    mp = project_monthly_costs(
                        pid,
                        rates,
                        personnel,
                        cur.year,
                        cur.month,
                        travel_items,
                        expense_items,
                    )
                    proj_projected += mp.total
                if cur.month == 12:
                    cur = cur.replace(year=cur.year + 1, month=1)
                else:
                    cur = cur.replace(month=cur.month + 1)

            total = proj_actual + proj_projected
            rows.append(
                {
                    "id": pid,
                    "actual": round(float(proj_actual), 2),
                    "projected": round(float(proj_projected), 2),
                    "total": round(float(total), 2),
                }
            )
            grand_actual += proj_actual
            grand_projected += proj_projected

        rows.sort(key=lambda r: float(str(r["total"])), reverse=True)

        return {
            "range_label": range_label,
            "projects": rows,
            "grand_actual": round(float(grand_actual), 2),
            "grand_projected": round(float(grand_projected), 2),
            "grand_total": round(float(grand_actual + grand_projected), 2),
        }

    # ------------------------------------------------------------------
    # Budget vs actuals
    # ------------------------------------------------------------------

    def budget_vs_actuals(self, project: str) -> dict:
        """Compare projected spending against contractual budget ceilings."""
        from .contractual_budget import load_contractual_budget
        from .projections import load_personnel_config, project_monthly_costs

        store = self._get_store()
        data = store.get_project(project)
        if not data:
            return {"error": f"Project not found: {project}"}

        budget_config_path = None
        if data.project.budget_dir:
            budget_config_path = Path(data.project.budget_dir) / "budget_config.yaml"

        if not budget_config_path or not budget_config_path.exists():
            return {"error": f"No contractual budget config found for {project}"}

        contract = load_contractual_budget(budget_config_path)
        if not contract:
            return {"error": f"Could not parse budget config: {budget_config_path}"}

        config_path = self._config_path()
        rates = None
        personnel: list = []
        if config_path.exists():
            rates, personnel = load_personnel_config(config_path)

        today = date.today()

        periods_out = []
        total_budget = Decimal("0")
        total_actual = Decimal("0")
        total_projected = Decimal("0")

        for period in sorted(contract.periods, key=lambda p: p.year_num):
            budget_amt = period.total
            total_budget += budget_amt

            is_past = period.end < today
            is_current = period.start <= today <= period.end
            is_future = period.start > today

            actual_amt = Decimal("0")
            projected_amt = Decimal("0")

            if is_past or is_current:
                period_reports = [
                    r
                    for r in data.spending
                    if period.start <= date(r.year, r.month, 1) <= period.end
                ]
                if period_reports:
                    latest = max(period_reports, key=lambda r: (r.year, r.month))
                    earliest = min(period_reports, key=lambda r: (r.year, r.month))

                    if period.year_num == 1:
                        actual_amt = latest.total_spent
                    else:
                        prior_period = contract.get_period_by_year(period.year_num - 1)
                        prior_ending = Decimal("0")
                        if prior_period:
                            prior_reports = [
                                r
                                for r in data.spending
                                if prior_period.start
                                <= date(r.year, r.month, 1)
                                <= prior_period.end
                            ]
                            if prior_reports:
                                prior_latest = max(prior_reports, key=lambda r: (r.year, r.month))
                                prior_ending = prior_latest.total_spent
                            else:
                                prior_ending = earliest.total_spent
                        actual_amt = latest.total_spent - prior_ending

            if (is_current or is_future) and rates and personnel:
                proj_start = today.replace(day=1) if is_current else period.start
                cur = proj_start
                while cur <= period.end:
                    proj = project_monthly_costs(project, rates, personnel, cur.year, cur.month)
                    projected_amt += proj.total
                    if cur.month == 12:
                        cur = cur.replace(year=cur.year + 1, month=1)
                    else:
                        cur = cur.replace(month=cur.month + 1)

            total_actual += actual_amt
            total_projected += projected_amt

            variance = budget_amt - actual_amt - projected_amt
            underspend_threshold = budget_amt * Decimal("0.25")

            if is_past:
                if variance > underspend_threshold:
                    status = "underspend"
                elif variance >= 0:
                    status = "under"
                else:
                    status = "overspend"
            elif is_current:
                if variance > underspend_threshold:
                    status = "underspend"
                elif variance >= budget_amt * Decimal("0.05"):
                    status = "on_track"
                elif variance >= 0:
                    status = "tight"
                else:
                    status = "overspend"
            else:
                if variance > underspend_threshold:
                    status = "underspend"
                elif variance >= 0:
                    status = "planned"
                else:
                    status = "overspend"

            periods_out.append(
                {
                    "year_num": period.year_num,
                    "dates": f"{period.start.strftime('%b %Y')} - {period.end.strftime('%b %Y')}",
                    "budget": round(float(budget_amt), 2),
                    "actual": round(float(actual_amt), 2),
                    "projected": round(float(projected_amt), 2),
                    "variance": round(float(variance), 2),
                    "status": status,
                }
            )

        return {
            "project": project,
            "award_id": contract.award_id,
            "total_budget": round(float(total_budget), 2),
            "periods": periods_out,
            "total_actual": round(float(total_actual), 2),
            "total_projected": round(float(total_projected), 2),
            "total_variance": round(float(total_budget - total_actual - total_projected), 2),
        }

    # ------------------------------------------------------------------
    # Write: set_salary
    # ------------------------------------------------------------------

    def set_salary(
        self,
        name: str,
        salary: int,
        start: str | None = None,
        end: str | None = None,
    ) -> dict:
        """Set annual salary for a person."""
        from .cli._write_commands import cmd_set_salary

        class DummyArgs:
            def __init__(self, **kwargs):
                for k, v in kwargs.items():
                    setattr(self, k, v)

        with self._suppress_stdout():
            try:
                cmd_set_salary(
                    self._get_store(),
                    DummyArgs(
                        data_dir=self.data_dir,
                        name=name,
                        salary=str(salary),
                        start=start,
                        end=end,
                    ),
                )
                self._store = None  # Invalidate cache so reads reflect the write
                return self._sanitize_result({"success": True, "name": name, "salary": salary})
            except Exception as e:
                return self._sanitize_result({"error": str(e)})

    # ------------------------------------------------------------------
    # Write: set_assignment_end
    # ------------------------------------------------------------------

    def set_assignment_end(self, name: str, project: str, end_date: str) -> dict:
        """Set or clear end date for a person's project assignment."""
        from .cli._write_commands import cmd_set_end

        class DummyArgs:
            def __init__(self, **kwargs):
                for k, v in kwargs.items():
                    setattr(self, k, v)

        with self._suppress_stdout():
            try:
                cmd_set_end(
                    self._get_store(),
                    DummyArgs(data_dir=self.data_dir, name=name, project=project, date=end_date),
                )
                self._store = None  # Invalidate cache so reads reflect the write
                return self._sanitize_result(
                    {"success": True, "name": name, "project": project, "end_date": end_date}
                )
            except Exception as e:
                return self._sanitize_result({"error": str(e)})

    # ------------------------------------------------------------------
    # Write: set_departure
    # ------------------------------------------------------------------

    def set_departure(self, name: str, departure_date: str) -> dict:
        """Set departure date for a person (leaves university/graduates)."""
        from .cli._write_commands import cmd_set_departure

        class DummyArgs:
            def __init__(self, **kwargs):
                for k, v in kwargs.items():
                    setattr(self, k, v)

        with self._suppress_stdout():
            try:
                cmd_set_departure(
                    self._get_store(),
                    DummyArgs(data_dir=self.data_dir, name=name, date=departure_date),
                )
                self._store = None  # Invalidate cache so reads reflect the write
                return self._sanitize_result(
                    {"success": True, "name": name, "departure_date": departure_date}
                )
            except Exception as e:
                return self._sanitize_result({"error": str(e)})

    # ------------------------------------------------------------------
    # Report Gaps
    # ------------------------------------------------------------------

    def report_gaps(self) -> dict:
        """Check for missing monthly spending reports across all projects.

        Returns:
            Dictionary with missing monthly report periods per project.
        """
        from datetime import datetime

        store = self._get_store()
        now = datetime.now()
        projects = store.list_projects()
        results: dict[str, list[str]] = {}

        for project_id in projects:
            data = store.get_project(project_id)
            if not data or not data.spending:
                results[project_id] = ["No reports found"]
                continue

            periods = {(r.year, r.month) for r in data.spending}
            min_period = min(periods)
            max_period = max(periods)

            end_year, end_month = now.year, now.month
            if max_period > (end_year, end_month):
                end_year, end_month = max_period

            expected = set()
            year, month = min_period
            while (year, month) <= (end_year, end_month):
                expected.add((year, month))
                month += 1
                if month > 12:
                    month = 1
                    year += 1

            missing = sorted(expected - periods)
            if missing:
                results[project_id] = [datetime(y, m, 1).strftime("%B %Y") for y, m in missing]

        return {
            "has_gaps": bool(results),
            "gaps": results,
        }

    # ------------------------------------------------------------------
    # Budget Health Check
    # ------------------------------------------------------------------

    def health_check(self) -> dict:
        """Run comprehensive data integrity checks across projects, reports, and personnel."""
        from datetime import datetime

        from .cli._util import Anonymizer
        from .projections import load_personnel_config

        store = self._get_store()
        now = datetime.now()
        projects = store.list_projects()
        warnings: list[str] = []
        project_health: dict[str, dict] = {}

        # 1. Report gaps
        for project_id in projects:
            data = store.get_project(project_id)
            if not data or not data.spending:
                warnings.append(f"Project '{project_id}': No spending reports found.")
                project_health[project_id] = {"has_reports": False, "report_count": 0}
                continue
            periods = {(r.year, r.month) for r in data.spending}
            min_period = min(periods)
            max_period = max(periods)
            end_year, end_month = now.year, now.month
            if max_period > (end_year, end_month):
                end_year, end_month = max_period
            year, month = min_period
            missing_months = []
            while (year, month) <= (end_year, end_month):
                if (year, month) not in periods:
                    missing_months.append(f"{datetime(year, month, 1).strftime('%B %Y')}")
                month += 1
                if month > 12:
                    month = 1
                    year += 1
            if missing_months:
                warnings.append(
                    f"Project '{project_id}' has missing report gaps: {', '.join(missing_months)}."
                )
            project_health[project_id] = {
                "has_reports": True,
                "report_count": len(data.spending),
                "missing_reports": missing_months,
            }

        # 2. Invoices
        for project_id in projects:
            invoices = store.get_project_invoices(project_id)
            data = store.get_project(project_id)
            if data and data.project.project_type.value == "sponsored":
                if not invoices:
                    warnings.append(f"Project '{project_id}': No invoices found.")
                else:
                    periods = {(inv.period_end.year, inv.period_end.month) for inv in invoices}
                    min_period = min(periods)
                    end_year, end_month = now.year, now.month
                    year, month = min_period
                    missing_invs = []
                    while (year, month) <= (end_year, end_month):
                        if (year, month) not in periods:
                            missing_invs.append(f"{datetime(year, month, 1).strftime('%B %Y')}")
                        month += 1
                        if month > 12:
                            month = 1
                            year += 1
                    if missing_invs:
                        warnings.append(
                            f"Project '{project_id}' has missing invoice gaps: {', '.join(missing_invs)}."
                        )

        # 3. Parse warnings
        for pw in store.get_parse_warnings():
            warnings.append(f"Parse warning in {pw.file}: {pw.message}")

        # 4. Personnel over-commitments
        config_path = self._config_path()
        if config_path.exists():
            try:
                _rates, config_personnel = load_personnel_config(config_path)
                for p in config_personnel:
                    total_effort = sum(a.effort for a in p.assignments)
                    if total_effort > Decimal("1.0"):
                        warnings.append(
                            f"Personnel '{Anonymizer.anonymize(p.name)}' is over-committed at {total_effort * 100:.0f}% total effort across projects."
                        )
            except Exception as e:
                warnings.append(f"Personnel config error: {e}")

        return {
            "status": "healthy" if not warnings else "warnings_found",
            "warning_count": len(warnings),
            "warnings": warnings,
            "project_health": project_health,
        }

    # ------------------------------------------------------------------
    # Budget Mitigation Optimizer
    # ------------------------------------------------------------------

    def optimize_budget(self, project: str, target_months: int = 12) -> dict:
        """Suggest budget mitigation strategies (travel freezes, expense pauses, effort cuts).

        Args:
            project: Project short name.
            target_months: Target extension in months (default 12).
        """
        from .projections import optimize_mitigations

        store = self._get_store()
        config_path = self._config_path()
        if not config_path.exists():
            return {"error": f"Personnel config not found: {config_path}"}

        data = store.get_project(project)
        if not data:
            return {"error": f"Project not found: {project}"}

        plans = optimize_mitigations(project, config_path, store, target_months=target_months)
        return {
            "project": project,
            "target_months": target_months,
            "plans": plans,
        }

    # ------------------------------------------------------------------
    # Contractual Budget Methods
    # ------------------------------------------------------------------

    def list_budget_periods(self, project: str) -> dict:
        """List contractual budget periods and funding increments for a project."""
        from .cli._budget_commands import _resolve_budget_config_path
        from .contractual_budget import load_contractual_budget

        store = self._get_store()
        config_path = _resolve_budget_config_path(store, project, self.data_dir)
        if config_path is None:
            return {"error": f"Project '{project}' not found"}
        if not config_path.exists():
            return {"project": project, "has_budget_config": False, "periods": []}

        contract = load_contractual_budget(config_path)
        if not contract:
            return {"error": f"Could not parse budget config at {config_path}"}

        periods = [
            {
                "year_num": p.year_num,
                "start": p.start.strftime("%Y-%m-%d"),
                "end": p.end.strftime("%Y-%m-%d"),
                "total": float(p.total),
                "direct": float(p.direct),
                "idc": float(p.idc),
            }
            for p in sorted(contract.periods, key=lambda x: x.year_num)
        ]

        return {
            "project": project,
            "award_id": contract.award_id,
            "pi": contract.pi,
            "start_date": contract.start_date.strftime("%Y-%m-%d") if contract.start_date else None,
            "total_budget": float(contract.total_budget),
            "total_direct_costs": float(contract.total_direct_costs),
            "total_indirect_costs": float(contract.total_indirect_costs),
            "periods": periods,
        }

    def add_budget_period(
        self,
        project: str,
        year: int,
        total: float,
        start: str,
        end: str,
        direct: float | None = None,
        idc: float | None = None,
    ) -> dict:
        """Add a contractual funding increment period."""
        from .cli._budget_commands import _cmd_budget_add

        class DummyArgs:
            def __init__(self, **kwargs):
                for k, v in kwargs.items():
                    setattr(self, k, v)

        with self._suppress_stdout():
            try:
                _cmd_budget_add(
                    self._get_store(),
                    DummyArgs(
                        data_dir=self.data_dir,
                        project=project,
                        year=year,
                        total=total,
                        start=start,
                        end=end,
                        direct=direct,
                        idc=idc,
                    ),
                )
                self._store = None
                return self._sanitize_result(
                    {"success": True, "project": project, "year": year, "total": total}
                )
            except Exception as e:
                return self._sanitize_result({"error": str(e)})

    def set_budget_period(
        self,
        project: str,
        year: int,
        total: float | None = None,
        direct: float | None = None,
        idc: float | None = None,
        start: str | None = None,
        end: str | None = None,
    ) -> dict:
        """Modify an existing contractual funding increment period."""
        from .cli._budget_commands import _cmd_budget_set

        class DummyArgs:
            def __init__(self, **kwargs):
                for k, v in kwargs.items():
                    setattr(self, k, v)

        with self._suppress_stdout():
            try:
                _cmd_budget_set(
                    self._get_store(),
                    DummyArgs(
                        data_dir=self.data_dir,
                        project=project,
                        year=year,
                        total=total,
                        direct=direct,
                        idc=idc,
                        start=start,
                        end=end,
                    ),
                )
                self._store = None
                return self._sanitize_result({"success": True, "project": project, "year": year})
            except Exception as e:
                return self._sanitize_result({"error": str(e)})

    # ------------------------------------------------------------------
    # Project Lifecycle Methods
    # ------------------------------------------------------------------

    def add_project(
        self,
        project: str,
        description: str | None = None,
        project_type: str = "sponsored",
        budget: float | None = None,
        grant: str | None = None,
        status: str = "active",
    ) -> dict:
        """Add a new project to the manifest."""
        from .cli._write_commands import cmd_add_project

        class DummyArgs:
            def __init__(self, **kwargs):
                for k, v in kwargs.items():
                    setattr(self, k, v)

        with self._suppress_stdout():
            try:
                cmd_add_project(
                    self._get_store(),
                    DummyArgs(
                        data_dir=self.data_dir,
                        name=project,
                        description=description,
                        type=project_type,
                        budget=str(int(budget)) if budget is not None else None,
                        grant=grant,
                        status=status,
                    ),
                )
                self._store = None
                return self._sanitize_result(
                    {"success": True, "project": project, "type": project_type}
                )
            except Exception as e:
                return self._sanitize_result({"error": str(e)})

    def set_project_status(self, project: str, status: str) -> dict:
        """Set project lifecycle status (proposed, accepted, active, completed)."""
        from .cli._write_commands import cmd_set_status

        class DummyArgs:
            def __init__(self, **kwargs):
                for k, v in kwargs.items():
                    setattr(self, k, v)

        with self._suppress_stdout():
            try:
                cmd_set_status(
                    self._get_store(),
                    DummyArgs(data_dir=self.data_dir, project=project, status=status),
                )
                self._store = None
                return self._sanitize_result(
                    {"success": True, "project": project, "status": status}
                )
            except Exception as e:
                return self._sanitize_result({"error": str(e)})

    def set_project_budget(self, project: str, budget: float) -> dict:
        """Set total budget for a project."""
        from .cli._write_commands import cmd_set_budget

        class DummyArgs:
            def __init__(self, **kwargs):
                for k, v in kwargs.items():
                    setattr(self, k, v)

        with self._suppress_stdout():
            try:
                cmd_set_budget(
                    self._get_store(),
                    DummyArgs(data_dir=self.data_dir, project=project, budget=str(int(budget))),
                )
                self._store = None
                return self._sanitize_result(
                    {"success": True, "project": project, "budget": budget}
                )
            except Exception as e:
                return self._sanitize_result({"error": str(e)})

    def set_project_end(self, project: str, end_date: str) -> dict:
        """Set project end date (YYYY-MM)."""
        from .cli._write_commands import cmd_set_project_end

        class DummyArgs:
            def __init__(self, **kwargs):
                for k, v in kwargs.items():
                    setattr(self, k, v)

        with self._suppress_stdout():
            try:
                cmd_set_project_end(
                    self._get_store(),
                    DummyArgs(data_dir=self.data_dir, project=project, date=end_date),
                )
                self._store = None
                return self._sanitize_result(
                    {"success": True, "project": project, "end_date": end_date}
                )
            except Exception as e:
                return self._sanitize_result({"error": str(e)})

    # ------------------------------------------------------------------
    # Rate Configuration Methods
    # ------------------------------------------------------------------

    def set_fringe(self, person_type: str, rate: float) -> dict:
        """Set fringe benefit rate for a personnel type."""
        from .cli._write_commands import cmd_set_fringe

        class DummyArgs:
            def __init__(self, **kwargs):
                for k, v in kwargs.items():
                    setattr(self, k, v)

        with self._suppress_stdout():
            try:
                cmd_set_fringe(
                    self._get_store(),
                    DummyArgs(data_dir=self.data_dir, type=person_type, rate=str(rate)),
                )
                self._store = None
                return self._sanitize_result(
                    {"success": True, "person_type": person_type, "rate": rate}
                )
            except Exception as e:
                return self._sanitize_result({"error": str(e)})

    def set_idc(self, rate: float) -> dict:
        """Set IDC (indirect cost) rate."""
        from .cli._write_commands import cmd_set_idc

        class DummyArgs:
            def __init__(self, **kwargs):
                for k, v in kwargs.items():
                    setattr(self, k, v)

        with self._suppress_stdout():
            try:
                cmd_set_idc(
                    self._get_store(),
                    DummyArgs(data_dir=self.data_dir, rate=str(rate)),
                )
                self._store = None
                return self._sanitize_result({"success": True, "idc_rate": rate})
            except Exception as e:
                return self._sanitize_result({"error": str(e)})

    def set_tuition(self, amount: float) -> dict:
        """Set per-semester graduate student tuition cost."""
        from .cli._write_commands import cmd_set_tuition

        class DummyArgs:
            def __init__(self, **kwargs):
                for k, v in kwargs.items():
                    setattr(self, k, v)

        with self._suppress_stdout():
            try:
                cmd_set_tuition(
                    self._get_store(),
                    DummyArgs(data_dir=self.data_dir, amount=str(amount)),
                )
                self._store = None
                return self._sanitize_result({"success": True, "tuition_per_semester": amount})
            except Exception as e:
                return self._sanitize_result({"error": str(e)})

    def set_healthcare(self, amount: float) -> dict:
        """Set annual health & dental insurance cost for graduate students."""
        from .cli._write_commands import cmd_set_healthcare

        class DummyArgs:
            def __init__(self, **kwargs):
                for k, v in kwargs.items():
                    setattr(self, k, v)

        with self._suppress_stdout():
            try:
                cmd_set_healthcare(
                    self._get_store(),
                    DummyArgs(data_dir=self.data_dir, amount=str(amount)),
                )
                self._store = None
                return self._sanitize_result({"success": True, "healthcare_annual": amount})
            except Exception as e:
                return self._sanitize_result({"error": str(e)})
