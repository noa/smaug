"""Argument parser registration and main() entry point."""

import argparse
import sys

from ..store import ProjectStore
from ._budget_commands import cmd_budget
from ._financial import (
    cmd_budget_vs_actuals,
    cmd_optimize,
    cmd_proposal,
    cmd_spend_plan,
    cmd_stopwork,
    cmd_summary,
)
from ._import import cmd_report
from ._operational import (
    cmd_clear,
    cmd_expense,
    cmd_export,
    cmd_health,
    cmd_history,
    cmd_init,
    cmd_invoice,
    cmd_note,
    cmd_travel,
    cmd_undo,
)
from ._read_commands import (
    cmd_audit,
    cmd_dump,
    cmd_gaps,
    cmd_list,
    cmd_personnel,
    cmd_project,
    cmd_status,
)
from ._setup import cmd_setup
from ._write_commands import (
    cmd_add_person,
    cmd_add_project,
    cmd_alias,
    cmd_remove_effort,
    cmd_set_budget,
    cmd_set_departure,
    cmd_set_effort,
    cmd_set_end,
    cmd_set_fringe,
    cmd_set_healthcare,
    cmd_set_idc,
    cmd_set_project_end,
    cmd_set_salary,
    cmd_set_status,
    cmd_set_tuition,
    cmd_set_type,
)


def main():
    parser = argparse.ArgumentParser(
        prog="smaug",
        description="Budget tracking and spending projections for academic research grants",
    )
    parser.add_argument(
        "--data-dir", default=None, help="Data directory (default: $SMAUG_DATA_DIR or ~/.smaug/)"
    )
    parser.add_argument(
        "--anonymize",
        action="store_true",
        help="Anonymize personnel names to protect confidential salary information",
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__import__('smaug').__version__}"
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # list command
    list_parser = subparsers.add_parser("list", help="List all projects")
    list_parser.add_argument(
        "--all", "-a", action="store_true", help="Show all projects (including proposed, completed)"
    )
    list_parser.add_argument(
        "--status", choices=["proposed", "accepted", "active", "completed"], help="Filter by status"
    )
    list_parser.set_defaults(func=cmd_list)

    # status command
    status_parser = subparsers.add_parser("status", help="Show project status")
    status_parser.add_argument("project", help="Project short name (e.g., ARTS)")
    status_parser.set_defaults(func=cmd_status)

    # report command (subcommand group)
    report_parser = subparsers.add_parser("report", help="Manage spending reports")
    report_subparsers = report_parser.add_subparsers(dest="action", required=True)

    # report list
    report_list = report_subparsers.add_parser("list", help="Show spending report for a project")
    report_list.add_argument("project", help="Project short name")

    # report import
    report_import = report_subparsers.add_parser(
        "import", help="Import spending report(s) into the data directory"
    )
    report_import.add_argument("path", help="Path to a report file or directory of reports")
    report_import.add_argument(
        "--type",
        default="sponsored",
        choices=["sponsored", "non-sponsored"],
        help="Report type (default: sponsored)",
    )
    report_import.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and show what would be imported without copying",
    )
    report_import.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing files",
    )

    report_parser.set_defaults(func=cmd_report)

    # personnel command
    personnel_parser = subparsers.add_parser("personnel", help="Show personnel effort")
    personnel_parser.add_argument("name", nargs="?", help="Person name (optional)")
    personnel_parser.add_argument("--project", "-p", help="Filter by project (e.g., ARTS)")
    personnel_parser.set_defaults(func=cmd_personnel)

    # project command (projections)
    project_parser = subparsers.add_parser("project", help="Show spending projections")
    project_parser.add_argument("project", help="Project short name")
    project_parser.add_argument(
        "--months", type=int, default=12, help="Number of months to project (default: 12)"
    )
    project_parser.add_argument("--to", help="End date as YYYY-MM")
    project_parser.set_defaults(func=cmd_project)

    # gaps command
    gaps_parser = subparsers.add_parser("gaps", help="Check for missing spending reports")
    gaps_parser.set_defaults(func=cmd_gaps)

    # set-end command
    setend_parser = subparsers.add_parser("set-end", help="Set end date for personnel assignment")
    setend_parser.add_argument("name", help="Person name or index number")
    setend_parser.add_argument("project", help="Project short name")
    setend_parser.add_argument("date", help="End date as YYYY-MM")
    setend_parser.set_defaults(func=cmd_set_end)

    # set-departure command
    depart_parser = subparsers.add_parser(
        "set-departure", help="Set departure date (leaves university)"
    )
    depart_parser.add_argument("name", help="Person name or index number")
    depart_parser.add_argument("date", help="Departure date as YYYY-MM")
    depart_parser.set_defaults(func=cmd_set_departure)

    # set-type command
    type_parser = subparsers.add_parser("set-type", help="Set personnel type")
    type_parser.add_argument("name", help="Person name or index number")
    type_parser.add_argument(
        "type",
        help="Person type: faculty, postdoc, grad_student/phd, masters_student/masters/ms, staff",
    )
    type_parser.set_defaults(func=cmd_set_type)

    # set-salary command
    salary_parser = subparsers.add_parser("set-salary", help="Set annual salary")
    salary_parser.add_argument("name", help="Person name or index number")
    salary_parser.add_argument("salary", help="Annual salary amount")
    salary_parser.add_argument("--start", help="Start date as YYYY-MM")
    salary_parser.add_argument("--end", help="End date as YYYY-MM")
    salary_parser.set_defaults(func=cmd_set_salary)

    # set-idc command
    idc_parser = subparsers.add_parser("set-idc", help="Set IDC (F&A) rate")
    idc_parser.add_argument("rate", help="IDC rate as decimal (0.55) or percent (55)")
    idc_parser.set_defaults(func=cmd_set_idc)

    # set-healthcare command
    hc_parser = subparsers.add_parser(
        "set-healthcare", help="Set annual grad student health & dental cost"
    )
    hc_parser.add_argument("amount", help="Annual health & dental cost")
    hc_parser.set_defaults(func=cmd_set_healthcare)

    # set-tuition command
    tuition_parser = subparsers.add_parser(
        "set-tuition", help="Set per-semester tuition for grad students"
    )
    tuition_parser.add_argument("amount", help="Tuition amount per semester")
    tuition_parser.set_defaults(func=cmd_set_tuition)

    # set-fringe command
    fringe_parser = subparsers.add_parser("set-fringe", help="Set fringe rate for a personnel type")
    fringe_parser.add_argument(
        "type", help="Personnel type: faculty, postdoc, staff, grad_student/phd"
    )
    fringe_parser.add_argument("rate", help="Fringe rate as decimal (0.315) or percent (31.5)")
    fringe_parser.set_defaults(func=cmd_set_fringe)

    # add-person command
    addperson_parser = subparsers.add_parser("add-person", help="Add new personnel")
    addperson_parser.add_argument("name", help="Full name (Last, First)")
    addperson_parser.add_argument(
        "type",
        help="Person type: faculty, postdoc, grad_student/phd, masters_student/masters/ms, staff",
    )
    addperson_parser.add_argument("project", help="Initial project assignment")
    addperson_parser.add_argument("effort", help="Effort as decimal (0.25) or percent (25)")
    addperson_parser.add_argument(
        "--salary",
        help="Annual salary (default: stipend for grad students, hourly rate for masters)",
    )
    addperson_parser.add_argument(
        "--hours",
        type=float,
        help="Hours per week for hourly personnel (default from rates.yaml, max 19.9 for masters)",
    )
    addperson_parser.add_argument("--start", help="Start date as YYYY-MM")
    addperson_parser.add_argument("--end", help="End date as YYYY-MM")
    addperson_parser.set_defaults(func=cmd_add_person)

    # set-effort command
    effort_parser = subparsers.add_parser("set-effort", help="Set effort allocation on a project")
    effort_parser.add_argument("name", help="Person name or index number")
    effort_parser.add_argument("project", help="Project short name")
    effort_parser.add_argument("effort", help="Effort as decimal (0.25) or percent (25)")
    effort_parser.add_argument("--start", help="Start date as YYYY-MM")
    effort_parser.add_argument("--end", help="End date as YYYY-MM")
    effort_parser.set_defaults(func=cmd_set_effort)

    # remove-effort command
    remove_parser = subparsers.add_parser(
        "remove-effort", aliases=["rm"], help="Remove person from a project"
    )
    remove_parser.add_argument("name", help="Person name or index number")
    remove_parser.add_argument("project", help="Project short name")
    remove_parser.add_argument("--start", help="Start date as YYYY-MM")
    remove_parser.add_argument("--end", help="End date as YYYY-MM")
    remove_parser.set_defaults(func=cmd_remove_effort)

    # alias command
    alias_parser = subparsers.add_parser("alias", help="Manage personnel nicknames/aliases")
    alias_subparsers = alias_parser.add_subparsers(dest="action", required=True)

    alias_list = alias_subparsers.add_parser("list", help="List all aliases")
    alias_list.set_defaults(func=cmd_alias)

    alias_add = alias_subparsers.add_parser("add", help="Add an alias")
    alias_add.add_argument("alias", help="Nickname to use")
    alias_add.add_argument("person", help="Person name or index to alias")
    alias_add.set_defaults(func=cmd_alias)

    alias_rm = alias_subparsers.add_parser("remove", help="Remove an alias")
    alias_rm.add_argument("alias", help="Alias to remove")
    alias_rm.set_defaults(func=cmd_alias)

    # add-project command
    addproj_parser = subparsers.add_parser("add-project", help="Add a new project")
    addproj_parser.add_argument("name", help="Short project name (e.g., DSAI)")
    addproj_parser.add_argument(
        "--type", default="sponsored", choices=["sponsored", "discretionary"], help="Project type"
    )
    addproj_parser.add_argument(
        "--status",
        choices=["proposed", "accepted", "active", "completed"],
        help="Initial status (default: active)",
    )
    addproj_parser.add_argument("--budget", help="Total budget amount")
    addproj_parser.add_argument("--description", help="Project description/full name")
    addproj_parser.add_argument("--grant", help="Grant number for sponsored projects")
    addproj_parser.set_defaults(func=cmd_add_project)

    # set-project-end command
    projend_parser = subparsers.add_parser("set-project-end", help="Set project end date")
    projend_parser.add_argument("project", help="Project short name")
    projend_parser.add_argument("date", help="End date as YYYY-MM")
    projend_parser.set_defaults(func=cmd_set_project_end)

    # set-budget command
    setbudget_parser = subparsers.add_parser("set-budget", help="Set project budget")
    setbudget_parser.add_argument("project", help="Project short name")
    setbudget_parser.add_argument("budget", help="Total budget amount")
    setbudget_parser.set_defaults(func=cmd_set_budget)

    # budget command (subcommand group for contractual budget periods)
    budget_parser = subparsers.add_parser(
        "budget", help="Manage contractual budget periods (budget_config.yaml)"
    )
    budget_subparsers = budget_parser.add_subparsers(dest="action", required=True)

    # budget list
    budget_list = budget_subparsers.add_parser(
        "list", help="List contractual budget periods for a project"
    )
    budget_list.add_argument("project", help="Project short name")

    # budget add
    budget_add = budget_subparsers.add_parser(
        "add", help="Add a new funding increment (contract period)"
    )
    budget_add.add_argument("project", help="Project short name")
    budget_add.add_argument("--year", type=int, required=True, help="Period number (e.g., 1, 2, 3)")
    budget_add.add_argument(
        "--start", required=True, help="Period start date (YYYY-MM or YYYY-MM-DD)"
    )
    budget_add.add_argument("--end", required=True, help="Period end date (YYYY-MM or YYYY-MM-DD)")
    budget_add.add_argument(
        "--total", type=float, required=True, help="Total amount (direct + IDC)"
    )
    budget_add.add_argument(
        "--direct",
        type=float,
        default=None,
        help="Direct costs (if omitted, derived from --total using IDC rate)",
    )
    budget_add.add_argument(
        "--idc",
        type=float,
        default=None,
        help="Indirect costs (if omitted, derived from --total using IDC rate)",
    )

    # budget set
    budget_set = budget_subparsers.add_parser("set", help="Modify an existing contract period")
    budget_set.add_argument("project", help="Project short name")
    budget_set.add_argument("--year", type=int, required=True, help="Period number to modify")
    budget_set.add_argument("--total", type=float, default=None, help="New total amount")
    budget_set.add_argument("--direct", type=float, default=None, help="New direct costs")
    budget_set.add_argument("--idc", type=float, default=None, help="New indirect costs")
    budget_set.add_argument(
        "--start", default=None, help="New period start date (YYYY-MM or YYYY-MM-DD)"
    )
    budget_set.add_argument(
        "--end", default=None, help="New period end date (YYYY-MM or YYYY-MM-DD)"
    )

    budget_parser.set_defaults(func=cmd_budget)

    # set-status command
    setstatus_parser = subparsers.add_parser("set-status", help="Set project lifecycle status")
    setstatus_parser.add_argument("project", help="Project short name")
    setstatus_parser.add_argument(
        "status", choices=["proposed", "accepted", "active", "completed"], help="New status"
    )
    setstatus_parser.set_defaults(func=cmd_set_status)

    # spend-plan command
    spendplan_parser = subparsers.add_parser("spend-plan", help="Generate monthly spend plan")
    spendplan_parser.add_argument("projects", nargs="+", help="Project short name(s)")
    spendplan_parser.add_argument("--to", help="End date as YYYY-MM (default: project end date)")
    spendplan_parser.add_argument(
        "--fy",
        type=int,
        metavar="YEAR",
        help="Fiscal year (e.g., 2026 for FY2026: Jul 2025 - Jun 2026)",
    )
    spendplan_parser.add_argument(
        "--year",
        type=int,
        metavar="N",
        help="Contract year (e.g., 1, 2, 3 - uses project budget_config.yaml)",
    )
    spendplan_parser.add_argument(
        "--if",
        dest="hypotheticals",
        action="append",
        metavar="SPEC",
        help='Hypothetical override: "Name=50%%" or "+phd@100%%" (repeatable)',
    )
    spendplan_parser.add_argument(
        "--compare", action="store_true", help="Show comparison between current and hypothetical"
    )
    spendplan_parser.set_defaults(func=cmd_spend_plan)

    # summary command
    summary_parser = subparsers.add_parser(
        "summary", help="Aggregate sponsored funding across all projects"
    )
    summary_parser.add_argument(
        "--from",
        dest="range_from",
        metavar="YYYY-MM",
        help="Start of date range (default: Jan of current year)",
    )
    summary_parser.add_argument(
        "--to",
        dest="range_to",
        metavar="YYYY-MM",
        help="End of date range (default: Dec of current year)",
    )
    summary_parser.add_argument(
        "--fy",
        type=int,
        metavar="YEAR",
        help="Fiscal year shortcut (e.g., 2026 for Jul 2025 - Jun 2026)",
    )
    summary_parser.set_defaults(func=cmd_summary)

    # dump command
    dump_parser = subparsers.add_parser("dump", help="Dump project as JSON")
    dump_parser.add_argument("project", help="Project short name")
    dump_parser.set_defaults(func=cmd_dump)

    # audit command
    audit_parser = subparsers.add_parser("audit", help="Audit spending vs expected effort")
    audit_parser.add_argument(
        "project", nargs="?", help="Project short name or index (optional, audits all if omitted)"
    )
    audit_parser.add_argument(
        "--months", type=int, default=3, help="Months to look back (default: 3)"
    )
    audit_parser.add_argument(
        "--threshold", type=float, default=10.0, help="Variance threshold %% to flag (default: 10)"
    )
    audit_parser.add_argument(
        "--verbose", "-v", action="store_true", help="Show all comparisons, not just discrepancies"
    )
    audit_parser.set_defaults(func=cmd_audit)

    # stopwork command
    stopwork_parser = subparsers.add_parser(
        "stopwork", help="Forecast stop-work date based on funded ceiling"
    )
    stopwork_parser.add_argument("project", help="Project short name (e.g., ARTS)")
    stopwork_parser.add_argument(
        "--ceiling", type=float, help="Budget envelope amount (e.g., 241000 for new increment)"
    )
    stopwork_parser.add_argument(
        "--deduct",
        type=float,
        action="append",
        help="Deduct amount from envelope (repeatable, e.g., --deduct 22800)",
    )
    stopwork_parser.add_argument(
        "--from",
        dest="envelope_from",
        help="Envelope start month (auto-deducts actuals from reports, e.g., 2026-01)",
    )
    stopwork_parser.add_argument(
        "--scenario", choices=["no-tuition", "throttle"], help="Run scenario analysis"
    )
    stopwork_parser.add_argument(
        "--throttle-pct", type=float, default=0, help="Burn reduction %% for throttle scenario"
    )
    stopwork_parser.set_defaults(func=cmd_stopwork)

    # budget-vs-actuals command
    bva_parser = subparsers.add_parser(
        "budget-vs-actuals", help="Compare projected vs contractual budget"
    )
    bva_parser.add_argument("project", help="Project short name (e.g., ARTS)")
    bva_parser.set_defaults(func=cmd_budget_vs_actuals)

    # travel command
    travel_parser = subparsers.add_parser("travel", help="Manage travel budget")
    travel_subparsers = travel_parser.add_subparsers(dest="action", required=True)

    # travel list
    travel_list = travel_subparsers.add_parser("list", help="List travel items")
    travel_list.add_argument("--project", "-p", help="Filter by project")

    # travel add
    travel_add = travel_subparsers.add_parser("add", help="Add travel item")
    travel_add.add_argument("project", help="Project short name")
    travel_add.add_argument("description", help="Description")
    travel_add.add_argument("date", help="Date (YYYY-MM-DD)")
    travel_add.add_argument("amount", type=float, help="Estimated amount")
    travel_add.add_argument("--traveler", help="Traveler name")

    # travel actualize
    travel_act = travel_subparsers.add_parser("actualize", help="Mark travel as actualized")
    travel_act.add_argument("project", help="Project short name")
    travel_act.add_argument("description", help="Description (partial match)")
    travel_act.add_argument("--amount", type=float, help="Actual amount (optional)")

    travel_parser.set_defaults(func=cmd_travel)

    # expense command
    expense_parser = subparsers.add_parser("expense", help="Manage expenses (equipment, recurring)")
    expense_subparsers = expense_parser.add_subparsers(dest="action", required=True)

    # expense list
    expense_list = expense_subparsers.add_parser("list", help="List expenses")
    expense_list.add_argument("--project", "-p", help="Filter by project")

    # expense add
    expense_add = expense_subparsers.add_parser("add", help="Add new expense")
    expense_add.add_argument("project", help="Project short name")
    expense_add.add_argument("description", help="Description")
    expense_add.add_argument("amount", type=float, help="Amount")
    expense_add.add_argument("--category", default="Other", help="Category (Equipment, Other, etc)")
    expense_add.add_argument("--date", help="Date for one-time expense (YYYY-MM-DD)")
    expense_add.add_argument("--start", help="Start date for recurring (YYYY-MM-DD)")
    expense_add.add_argument("--end", help="End date for recurring (YYYY-MM-DD)")

    # expense remove
    expense_remove = expense_subparsers.add_parser("remove", help="Remove an expense")
    expense_remove.add_argument("project", help="Project short name")
    expense_remove.add_argument("description", help="Description of the expense to remove")

    # expense edit
    expense_edit = expense_subparsers.add_parser("edit", help="Edit an existing expense")
    expense_edit.add_argument("project", help="Project short name")
    expense_edit.add_argument("description", help="Description of the expense to edit")
    expense_edit.add_argument("--amount", type=float, help="New amount")
    expense_edit.add_argument("--new-description", dest="new_description", help="New description")
    expense_edit.add_argument("--category", help="New category (Equipment, Other, etc)")
    expense_edit.add_argument(
        "--date", help="Convert to one-time expense on this date (YYYY-MM-DD)"
    )
    expense_edit.add_argument("--start", help="New start date for recurring (YYYY-MM-DD)")
    expense_edit.add_argument("--end", help="New end date for recurring (YYYY-MM-DD)")

    expense_parser.set_defaults(func=cmd_expense)

    # invoice command
    invoice_parser = subparsers.add_parser("invoice", help="Manage and validate invoices")
    invoice_subparsers = invoice_parser.add_subparsers(dest="action", required=True)

    # invoice list
    invoice_list = invoice_subparsers.add_parser("list", help="List all invoices")
    invoice_list.add_argument("--project", "-p", help="Filter by project")

    # invoice validate
    invoice_validate = invoice_subparsers.add_parser(
        "validate", help="Validate invoices against spending reports"
    )
    invoice_validate.add_argument("--project", "-p", help="Filter by project")
    invoice_validate.add_argument(
        "--verbose", "-v", action="store_true", help="Show category breakdown"
    )

    # invoice import
    invoice_import = invoice_subparsers.add_parser("import", help="Import invoice PDF(s)")
    invoice_import.add_argument("path", help="Path to invoice PDF file or directory")
    invoice_import.add_argument("--project", "-p", help="Explicitly assign to a project")
    invoice_import.add_argument("--dry-run", action="store_true", help="Validate without copying")
    invoice_import.add_argument("--force", action="store_true", help="Overwrite existing files")

    invoice_parser.set_defaults(func=cmd_invoice)

    # note command
    note_parser = subparsers.add_parser("note", help="Manage per-project notes")
    note_subparsers = note_parser.add_subparsers(dest="action", required=True)

    # note list
    note_list = note_subparsers.add_parser("list", help="List notes for a project")
    note_list.add_argument("project", help="Project short name")

    # note show
    note_show = note_subparsers.add_parser("show", help="Show a note")
    note_show.add_argument("project", help="Project short name")
    note_show.add_argument("identifier", help="Note index (1-based) or title substring")

    # note add
    note_add = note_subparsers.add_parser("add", help="Add a new note")
    note_add.add_argument("project", help="Project short name")
    note_add.add_argument("title", help="Note title")
    note_add.add_argument("--message", "-m", help="Note content (opens $EDITOR if omitted)")
    note_add.add_argument("--tags", "-t", help="Comma-separated tags")

    # note remove
    note_rm = note_subparsers.add_parser("remove", aliases=["rm"], help="Remove a note")
    note_rm.add_argument("project", help="Project short name")
    note_rm.add_argument("identifier", help="Note index (1-based) or title substring")

    # note import
    note_import = note_subparsers.add_parser("import", help="Import a file as a note")
    note_import.add_argument("project", help="Project short name")
    note_import.add_argument("file", help="Path to file to import")
    note_import.add_argument("--title", help="Override note title")
    note_import.add_argument("--tags", "-t", help="Comma-separated tags")

    note_parser.set_defaults(func=cmd_note)

    # proposal command
    proposal_parser = subparsers.add_parser("proposal", help="Generate research proposal budget")
    proposal_parser.add_argument(
        "project", nargs="?", default=None, help="Project name (reads personnel from config)"
    )
    proposal_parser.add_argument(
        "--pi",
        action="append",
        metavar="NAME=EFFORT%",
        help='PI effort (e.g., "Smith=10%%"). Repeatable.',
    )
    proposal_parser.add_argument(
        "--person",
        nargs=2,
        action="append",
        metavar=("TYPE", "NAME=EFFORT%"),
        help='Named person: TYPE NAME=EFFORT%% (e.g., staff "Alex=50%%"). Repeatable.',
    )
    proposal_parser.add_argument(
        "--phd", type=int, default=0, metavar="N", help="Number of PhD students at 100%% effort"
    )
    proposal_parser.add_argument(
        "--masters",
        type=int,
        default=0,
        metavar="N",
        help="Number of Masters students (hourly RA rate from rates.yaml)",
    )
    proposal_parser.add_argument(
        "--no-masters-tuition", action="store_true", help="Exclude tuition for Masters students"
    )
    proposal_parser.add_argument(
        "--years", type=int, default=3, help="Number of budget years (default: 3)"
    )
    proposal_parser.add_argument("--travel", type=float, default=0, help="Annual travel budget")
    proposal_parser.add_argument(
        "--compute", type=float, default=0, help="Annual compute/cloud costs"
    )
    proposal_parser.add_argument(
        "--annotation", type=float, default=0, help="Annual annotation/data costs"
    )
    proposal_parser.add_argument(
        "--equipment", type=float, default=0, help="Equipment cost (year 1 only, excluded from IDC)"
    )
    proposal_parser.add_argument(
        "--other", type=float, default=0, help="Other direct costs per year"
    )
    proposal_parser.add_argument(
        "--escalation", type=float, default=3.0, help="Annual salary escalation %% (default: 3.0)"
    )
    proposal_parser.set_defaults(func=cmd_proposal)

    # optimize command
    optimize_parser = subparsers.add_parser(
        "optimize", help="Suggest budget mitigations to extend stop-work date"
    )
    optimize_parser.add_argument("project", help="Project short name")
    optimize_parser.add_argument(
        "--target-months",
        type=int,
        default=12,
        help="Target funding extension in months (default 12)",
    )
    optimize_parser.set_defaults(func=cmd_optimize)

    # export command
    export_parser = subparsers.add_parser(
        "export", help="Export spend plan to styled Excel workbook"
    )
    export_parser.add_argument("project", help="Project short name")
    export_parser.add_argument("filename", help="Target Excel filename (.xlsx)")
    export_parser.set_defaults(func=cmd_export)

    # init command
    init_parser = subparsers.add_parser("init", help="Initialize Smaug data directory")
    init_parser.set_defaults(func=cmd_init)

    # health command
    health_parser = subparsers.add_parser(
        "health", help="Run data integrity and budget health dashboard"
    )
    health_parser.set_defaults(func=cmd_health)

    # history command
    history_parser = subparsers.add_parser("history", help="Show git commit log history of changes")
    history_parser.set_defaults(func=cmd_history)

    # undo command
    undo_parser = subparsers.add_parser("undo", help="Undo the last configuration change")
    undo_parser.set_defaults(func=cmd_undo)

    # clear command
    clear_parser = subparsers.add_parser("clear", help="Clear all projects, personnel, and reports")
    clear_parser.set_defaults(func=cmd_clear)

    # setup command (subcommand group)
    setup_parser = subparsers.add_parser(
        "setup", help="Manage smaug environment setup and integrations"
    )
    setup_subparsers = setup_parser.add_subparsers(dest="action", required=True)

    # setup mcp
    setup_mcp = setup_subparsers.add_parser(
        "mcp", help="Register smaug MCP server with Claude Code and/or Claude Desktop"
    )
    setup_mcp.add_argument(
        "--scope",
        default="project",
        choices=["project", "user"],
        help="Registration scope for Claude Code (default: project)",
    )
    setup_mcp.add_argument(
        "--target",
        default="all",
        choices=["all", "code", "desktop"],
        help="Target client: 'code' (Claude Code), 'desktop' (Claude Desktop), or 'all' (default)",
    )

    # setup show
    setup_subparsers.add_parser("show", help="Show current smaug setup status")

    setup_parser.set_defaults(func=cmd_setup)

    args = parser.parse_args()

    # Resolve data directory through priority chain
    from ..config import resolve_data_dir

    try:
        data_dir = resolve_data_dir(args.data_dir)
        args.data_dir = str(data_dir)
    except FileNotFoundError as e:
        print(f"Error: {e}")
        sys.exit(1)

    # Load data
    store = ProjectStore(data_dir=args.data_dir)
    if args.command not in ("init", "clear", "setup"):
        try:
            store.load_all()
        except FileNotFoundError as e:
            print(f"Error: {e}")
            sys.exit(1)

        # Initialize Anonymizer
        from ._util import Anonymizer

        Anonymizer.init(store, args)

    # Run command
    args.func(store, args)


if __name__ == "__main__":
    main()
