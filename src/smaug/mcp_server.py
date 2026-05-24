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
    # Write Tools
    # ------------------------------------------------------------------

    @mcp.tool()
    def set_personnel_effort(name: str, project: str, effort_pct: float) -> str:
        """Set or update effort allocation for a person on a project.

        Args:
            name: Personnel name (supports fuzzy/nickname resolution).
            project: Project short name (e.g. 'QUASAR').
            effort_pct: Effort level as a percentage (e.g. 25 for 25%).
        """
        api = SmaugAPI(data_dir, anonymize=anonymize)
        return json.dumps(api.set_personnel_effort(name, project, effort_pct), indent=2)

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
