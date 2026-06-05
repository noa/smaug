"""
MCP (Model Context Protocol) server for smaug.

Exposes smaug's budget tracking capabilities as read-only MCP tools
for AI agents. Install with: pip install -e ".[mcp]" (cloned repository)
or pip install "git+https://github.com/noa/smaug.git#egg=smaug[mcp]"

Usage:
    smaug-mcp                          # stdio transport (default)
    smaug-mcp --data-dir /path/to/data # custom data directory
"""

import json
import os
import sys


def _get_data_dir() -> str:
    """Resolve data directory from env or default."""
    return os.environ.get("SMAUG_DATA_DIR", "~/.smaug")


def main():
    """Entry point for the smaug-mcp command."""
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError:
        print(
            "MCP dependencies not installed. Install with:\n"
            '  pip install -e ".[mcp]" (from a cloned repository root)\n'
            "or:\n"
            '  pip install "git+https://github.com/noa/smaug.git#egg=smaug[mcp]"',
            file=sys.stderr,
        )
        sys.exit(1)

    from .api import SmaugAPI

    mcp = FastMCP(
        "smaug",
        instructions="Academic research budget tracking and spending projections",
    )

    # Allow --data-dir override via argv
    data_dir = _get_data_dir()
    for i, arg in enumerate(sys.argv[1:], 1):
        if arg == "--data-dir" and i < len(sys.argv) - 1:
            data_dir = sys.argv[i + 1]
            break

    # Support disabling anonymization explicitly in MCP server via CLI flag
    no_anonymize = False
    for arg in sys.argv[1:]:
        if arg in ("--no-anonymize", "--unmask-names"):
            no_anonymize = True
            break
    anonymize = not no_anonymize

    # ------------------------------------------------------------------
    # Tools (read-only)
    # ------------------------------------------------------------------

    @mcp.tool()
    def list_projects(status: str | None = None) -> str:
        """List all tracked research projects with budget summaries.

        Returns project names, budgets, spending, monthly burn rates,
        and projected remaining funds.

        Args:
            status: Filter by lifecycle status. Options: 'active' (default),
                    'proposed', 'accepted', 'completed'.
        """
        api = SmaugAPI(data_dir, anonymize=anonymize)
        return json.dumps(api.list_projects(status=status), indent=2)

    @mcp.tool()
    def project_status(project: str) -> str:
        """Get detailed budget vs. actuals for a single project.

        Shows budget summary, latest spending report, category breakdown,
        and remaining funds.

        Args:
            project: Project short name (e.g., 'QUASAR').
        """
        api = SmaugAPI(data_dir, anonymize=anonymize)
        return json.dumps(api.project_status(project), indent=2)

    @mcp.tool()
    def spending_report(project: str) -> str:
        """Get monthly spending history from parsed reports.

        Shows cumulative spending over time and per-person salary totals.

        Args:
            project: Project short name.
        """
        api = SmaugAPI(data_dir, anonymize=anonymize)
        return json.dumps(api.spending_report(project), indent=2)

    @mcp.tool()
    def spending_projection(project: str, months: int = 12, end_date: str | None = None) -> str:
        """Project monthly spending forward based on current personnel config.

        Calculates salary, fringe, tuition, travel, compute, IDC and total
        costs per month, based on current effort allocations.

        Args:
            project: Project short name.
            months: Number of months to project (default 12).
            end_date: End date as YYYY-MM (overrides months if provided).
        """
        api = SmaugAPI(data_dir, anonymize=anonymize)
        return json.dumps(
            api.spending_projection(project, months=months, end_date=end_date),
            indent=2,
        )

    @mcp.tool()
    def stopwork_forecast(project: str, ceiling: float | None = None) -> str:
        """Predict when a project will exhaust its funding.

        Projects forward spending based on current personnel assignments
        and institutional rates, returning the estimated stop-work month.

        Args:
            project: Project short name.
            ceiling: Override the funding ceiling amount. If not provided,
                     uses the ceiling from the latest report or budget.
        """
        api = SmaugAPI(data_dir, anonymize=anonymize)
        return json.dumps(api.stopwork_forecast(project, ceiling=ceiling), indent=2)

    @mcp.tool()
    def spend_plan(
        projects: list[str],
        months: int | None = None,
        fy: int | None = None,
        add_personnel: list[dict] | None = None,
        override_effort: list[dict] | None = None,
    ) -> str:
        """Generate a monthly spend plan with optional what-if scenarios.

        Use add_personnel to model hiring new people:
          [{"type": "phd", "effort_pct": 100},
           {"type": "postdoc", "effort_pct": 100, "salary": 85000}]

        Use override_effort to change existing allocations:
          [{"name": "Smith", "effort_pct": 50}]

        Args:
            projects: List of project short names.
            months: Number of months (default: until project end).
            fy: Fiscal year (e.g., 2026 for Jul 2025 - Jun 2026).
            add_personnel: List of personnel to add hypothetically.
            override_effort: List of effort overrides for existing personnel.
        """
        api = SmaugAPI(data_dir, anonymize=anonymize)
        result = api.spend_plan(
            projects=projects,
            months=months,
            fy=fy,
            add_personnel=add_personnel,
            override_effort=override_effort,
        )
        return json.dumps(result, indent=2)

    @mcp.tool()
    def audit_spending(project: str | None = None, months: int = 3, threshold: float = 10.0) -> str:
        """Audit spending vs expected effort allocations.

        Compares actual salary spending from reports against expected
        costs based on personnel configuration. Flags discrepancies.

        Args:
            project: Project short name (or omit to audit all projects).
            months: Months to look back (default 3).
            threshold: Variance threshold % to flag (default 10).
        """
        api = SmaugAPI(data_dir, anonymize=anonymize)
        return json.dumps(
            api.audit(project=project, months=months, threshold=threshold),
            indent=2,
        )

    @mcp.tool()
    def proposal_budget(
        phd: int = 0,
        years: int = 3,
        pi: list[dict] | None = None,
        masters: int = 0,
        travel: float = 0,
        compute: float = 0,
        equipment: float = 0,
        other: float = 0,
        escalation: float = 3.0,
    ) -> str:
        """Generate a multi-year research proposal budget.

        Creates a detailed budget with salary escalation, fringe benefits,
        tuition, IDC, and all cost categories.

        Args:
            phd: Number of PhD students at 100% effort.
            years: Number of budget years (default 3).
            pi: List of PI specs: [{"name": "Smith", "effort_pct": 10}].
            masters: Number of Masters students.
            travel: Annual travel budget.
            compute: Annual compute/cloud costs.
            equipment: Equipment (year 1 only, excluded from IDC).
            other: Other direct costs per year.
            escalation: Annual salary escalation % (default 3.0).
        """
        api = SmaugAPI(data_dir, anonymize=anonymize)
        return json.dumps(
            api.proposal_budget(
                pi=pi,
                phd=phd,
                masters=masters,
                years=years,
                travel=travel,
                compute=compute,
                equipment=equipment,
                other=other,
                escalation=escalation,
            ),
            indent=2,
        )

    @mcp.tool()
    def dump_project(project: str) -> str:
        """Get raw project data as JSON for detailed analysis.

        Returns complete project data including budget, spending history,
        and personnel allocations.

        Args:
            project: Project short name.
        """
        api = SmaugAPI(data_dir, anonymize=anonymize)
        return json.dumps(api.dump_project(project), indent=2)

    # ------------------------------------------------------------------
    # Resources (read-only context)
    # ------------------------------------------------------------------

    @mcp.resource("smaug://rates")
    def get_rates() -> str:
        """Current institutional rates (IDC, fringe, tuition, insurance)."""
        from pathlib import Path

        from .config import get_rates_path

        rates_path = get_rates_path(Path(data_dir).expanduser())
        if rates_path.exists():
            return rates_path.read_text()
        return "# No rates.yaml found"

    @mcp.resource("smaug://manifest")
    def get_manifest() -> str:
        """Project definitions from manifest.yaml."""
        from pathlib import Path

        manifest_path = Path(data_dir).expanduser() / "projects" / "manifest.yaml"
        if manifest_path.exists():
            return manifest_path.read_text()
        return "# No manifest.yaml found"

    @mcp.resource("smaug://calendar")
    def get_calendar() -> str:
        """Fiscal calendar details (JHU runs Jul-Jun)."""
        from datetime import date

        today = date.today()
        current_year = today.year
        current_month = today.month

        # JHU Fiscal Year: Jul 1 to Jun 30
        if current_month >= 7:
            current_fy = current_year + 1
            months_remaining = 6 - (current_month - 7)
        else:
            current_fy = current_year
            months_remaining = 6 - current_month

        calendar_data = {
            "fiscal_year": {"start_month": 7, "label": f"FY{current_fy}"},
            "tuition_billing_months": [1, 9],
            "current_fy": current_fy,
            "current_month": f"{current_year}-{current_month:02d}",
            "months_remaining_in_fy": months_remaining,
        }
        return json.dumps(calendar_data, indent=2)

    # ------------------------------------------------------------------
    # Import Tools
    # ------------------------------------------------------------------

    @mcp.tool()
    def import_report(
        path: str,
        report_type: str = "sponsored",
        force: bool = False,
    ) -> str:
        """Import spending report(s) from a file or directory into smaug.

        Parses PDF or CSV spending reports, validates them, and copies them
        into the smaug data directory for tracking.

        Args:
            path: Absolute path to a report file (PDF/CSV) or directory of reports.
            report_type: Type of report: 'sponsored' (grant-funded) or 'non-sponsored' (discretionary).
            force: If true, overwrite existing files with the same name.
        """
        from pathlib import Path as _Path

        from .cli._import import _collect_report_files, _import_single_file
        from .parsers import discover_parsers

        source = _Path(path).expanduser()
        if not source.exists():
            return json.dumps({"error": f"Path not found: {path}"})

        data_path = _Path(data_dir).expanduser()
        target_dir = data_path / "reports" / report_type

        report_parsers, _ = discover_parsers()
        if not report_parsers:
            return json.dumps({"error": "No report parsers available"})

        files = _collect_report_files(source)
        if not files:
            return json.dumps({"error": f"No report files (PDF, CSV) found at: {path}"})

        results = []
        for file_path in files:
            result = _import_single_file(
                file_path,
                target_dir,
                report_parsers,
                dry_run=False,
                force=force,
            )
            results.append(result)

        imported = sum(1 for r in results if r["status"] == "imported")
        skipped = sum(1 for r in results if r["status"] == "skipped")
        errors = sum(1 for r in results if r["status"] == "error")

        return json.dumps(
            {
                "summary": {
                    "imported": imported,
                    "skipped": skipped,
                    "errors": errors,
                    "target_directory": str(target_dir),
                },
                "results": results,
            },
            indent=2,
        )

    @mcp.tool()
    def import_invoice(
        path: str,
        project: str | None = None,
        force: bool = False,
    ) -> str:
        """Import sponsor invoice PDF(s) into smaug.

        Parses lockbox invoice PDFs, extracts billing data, and copies them
        into the smaug data directory for validation against spending reports.

        Args:
            path: Absolute path to an invoice PDF or directory of invoices.
            project: Explicitly assign to a project (overrides auto-detection).
            force: If true, overwrite existing files with the same name.
        """
        from pathlib import Path as _Path

        from .cli._import import _collect_report_files, _import_single_invoice
        from .parsers import discover_parsers
        from .store import ProjectStore as _Store

        source = _Path(path).expanduser()
        if not source.exists():
            return json.dumps({"error": f"Path not found: {path}"})

        data_path = _Path(data_dir).expanduser()
        target_dir = data_path / "reports" / "invoices"

        _, invoice_parsers = discover_parsers()
        if not invoice_parsers:
            return json.dumps({"error": "No invoice parsers available"})

        store = _Store(data_dir=data_dir)
        store.load_all()

        files = _collect_report_files(source)
        if not files:
            return json.dumps({"error": f"No invoice files found at: {path}"})

        results = []
        for file_path in files:
            result = _import_single_invoice(
                file_path,
                target_dir,
                invoice_parsers,
                store,
                override_project=project,
                dry_run=False,
                force=force,
            )
            results.append(result)

        imported = sum(1 for r in results if r["status"] == "imported")
        skipped = sum(1 for r in results if r["status"] == "skipped")
        errors = sum(1 for r in results if r["status"] == "error")

        return json.dumps(
            {
                "summary": {
                    "imported": imported,
                    "skipped": skipped,
                    "errors": errors,
                    "target_directory": str(target_dir),
                },
                "results": results,
            },
            indent=2,
        )

    # ------------------------------------------------------------------
    # Write Tools
    # ------------------------------------------------------------------

    @mcp.tool()
    def set_personnel_effort(
        name: str,
        project: str,
        effort_pct: float,
        start: str | None = None,
        end: str | None = None,
    ) -> str:
        """Set or update effort allocation for a person on a project.

        Without start/end, updates the existing effort in-place.
        With start and/or end (YYYY-MM format), creates a new date-bounded
        assignment — useful for temporary changes like internship leave,
        sabbaticals, or phased effort ramp-ups.

        Example: To mark someone as 0% from June to September for an
        internship, call with effort_pct=0, start="2026-06", end="2026-09".

        Args:
            name: Personnel name (supports fuzzy/nickname resolution).
            project: Project short name (e.g. 'QUASAR').
            effort_pct: Effort level as a percentage (e.g. 25 for 25%).
            start: Optional start date as YYYY-MM for date-bounded assignment.
            end: Optional end date as YYYY-MM for date-bounded assignment.
        """
        api = SmaugAPI(data_dir, anonymize=anonymize)
        return json.dumps(
            api.set_personnel_effort(name, project, effort_pct, start=start, end=end),
            indent=2,
        )

    @mcp.tool()
    def add_personnel(
        name: str, person_type: str, project: str, effort_pct: float, salary: int | None = None
    ) -> str:
        """Add new personnel and assign them to a project.

        Args:
            name: New personnel name (Last, First).
            person_type: Type of employee ('faculty', 'postdoc', 'grad_student', 'staff').
            project: Project short name.
            effort_pct: Initial effort percentage (e.g., 100 for 100%).
            salary: Optional annual salary override. Required for non-student roles.
        """
        api = SmaugAPI(data_dir, anonymize=anonymize)
        return json.dumps(
            api.add_personnel(name, person_type, project, effort_pct, salary), indent=2
        )

    @mcp.tool()
    def add_travel_item(
        project: str, description: str, date_str: str, amount: float, traveler: str | None = None
    ) -> str:
        """Add a planned travel item to a project.

        Args:
            project: Project short name.
            description: Travel destination and purpose (e.g., 'NeurIPS Conference').
            date_str: Planned date of travel (YYYY-MM-DD or YYYY-MM).
            amount: Estimated cost of travel.
            traveler: Optional traveler name.
        """
        api = SmaugAPI(data_dir, anonymize=anonymize)
        return json.dumps(
            api.add_travel_item(project, description, date_str, amount, traveler), indent=2
        )

    @mcp.tool()
    def add_expense_item(
        project: str,
        description: str,
        amount: float,
        category: str = "Other",
        date_str: str | None = None,
        start_str: str | None = None,
        end_str: str | None = None,
    ) -> str:
        """Add a recurring or one-time expense/purchase item to a project.

        Args:
            project: Project short name.
            description: Description of the purchase (e.g., 'GPU cluster access').
            amount: Cost of the expense (per month if recurring, total if one-time).
            category: Expense category ('Equipment', 'Materials and Supplies', 'Other').
            date_str: Specific date for one-time expense (YYYY-MM-DD).
            start_str: Start date for recurring expense (YYYY-MM).
            end_str: End date for recurring expense (YYYY-MM).
        """
        api = SmaugAPI(data_dir, anonymize=anonymize)
        return json.dumps(
            api.add_expense_item(
                project, description, amount, category, date_str, start_str, end_str
            ),
            indent=2,
        )

    # ------------------------------------------------------------------
    # Notes Tools
    # ------------------------------------------------------------------

    @mcp.tool()
    def list_project_notes(project: str) -> str:
        """List all markdown notes for a project.

        Args:
            project: Project short name.
        """
        api = SmaugAPI(data_dir, anonymize=anonymize)
        return json.dumps(api.list_project_notes(project), indent=2)

    @mcp.tool()
    def show_project_note(project: str, identifier: str) -> str:
        """Show contents of a specific project note by index or title.

        Args:
            project: Project short name.
            identifier: Note index (1-based) or title substring.
        """
        api = SmaugAPI(data_dir, anonymize=anonymize)
        return json.dumps(api.show_project_note(project, identifier), indent=2)

    @mcp.tool()
    def add_project_note(
        project: str, title: str, content: str, tags: list[str] | None = None
    ) -> str:
        """Add a new note to a project.

        Args:
            project: Project short name.
            title: Title of the note.
            content: Main text/markdown content.
            tags: Optional list of tags.
        """
        api = SmaugAPI(data_dir, anonymize=anonymize)
        return json.dumps(api.add_project_note(project, title, content, tags), indent=2)

    @mcp.tool()
    def remove_project_note(project: str, identifier: str) -> str:
        """Delete/remove a note from a project.

        Args:
            project: Project short name.
            identifier: Note index (1-based) or title substring.
        """
        api = SmaugAPI(data_dir, anonymize=anonymize)
        return json.dumps(api.remove_project_note(project, identifier), indent=2)

    mcp.run()


if __name__ == "__main__":
    main()
