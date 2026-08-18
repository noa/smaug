# Smaug — Agent Skill File

Smaug is a CLI tool for tracking academic research grant budgets. It helps PIs
monitor spending, project burn rates, forecast stop-work dates, and manage
personnel effort allocations.

## When to use smaug

Use smaug when the user asks about:
- Grant budgets, spending, or remaining funds
- Monthly burn rates or spending projections
- Stop-work date forecasts (when will funding run out?)
- Personnel effort allocations across projects
- What-if scenarios (hiring, effort changes)
- Proposal budget generation
- Spending audits or discrepancies

## Data directory

Smaug reads from a data directory. Pass it with `--data-dir`:

```bash
smaug --data-dir /path/to/data list
```

Or set the `SMAUG_DATA_DIR` environment variable. Default: `~/.smaug/`.

The data directory contains:
```
~/.smaug/
├── rates.yaml                  # Institutional rates (IDC, fringe, tuition)
├── projects/
│   ├── manifest.yaml           # Project definitions and identifiers
│   ├── personnel_config.yaml   # Personnel and effort allocations
│   ├── travel_config.yaml      # Travel budget items
│   ├── purchases_config.yaml   # Equipment and recurring expenses
│   └── <PROJECT>/notes/        # Per-project notes (markdown w/ YAML frontmatter)
└── reports/
    ├── sponsored/              # Monthly spending PDFs (grant-funded)
    ├── non-sponsored/          # Monthly spending PDFs (discretionary)
    └── invoices/               # Sponsor invoices
```

## Command reference

### Read commands (safe, no side effects)

```bash
# List all active projects with budget overview
smaug list
smaug list --all                    # Include proposed, completed
smaug list --status proposed        # Filter by lifecycle status

# Detailed status for one project
smaug status QUASAR

# Comprehensive "state of play" summary (warnings, financials, personnel, forecast)
smaug state-of-play QUASAR
smaug state-of-play QUASAR --json

# Spending history from parsed reports
smaug report list QUASAR

# Personnel effort across all projects
smaug personnel
smaug personnel "Smith"             # Single person detail
smaug personnel --project QUASAR    # Filter by project

# Monthly spending projections
smaug project QUASAR --months 12
smaug project QUASAR --to 2028-06

# Stop-work date forecast
smaug stopwork QUASAR
smaug stopwork QUASAR --ceiling 450000

# Monthly spend plan with what-if scenarios
smaug spend-plan QUASAR
smaug spend-plan QUASAR --if "+phd@100%"           # Add a PhD student
smaug spend-plan QUASAR --if "+postdoc@100%:85000"  # Add postdoc at $85k
smaug spend-plan QUASAR --if "+masters@100%"        # Add hourly masters student
smaug spend-plan QUASAR --if "Smith=50%"            # Change Smith's effort
smaug spend-plan QUASAR --fy 2026                   # Fiscal year view
smaug spend-plan QUASAR --compare --if "+phd@100%"  # Side-by-side comparison

# Aggregate funding across all sponsored projects
smaug summary --fy 2026

# Audit spending vs expected effort
smaug audit QUASAR
smaug audit --months 6 --threshold 15

# Budget vs contractual ceiling
smaug budget-vs-actuals QUASAR

# Contractual budget periods (funding increments)
smaug budget list QUASAR              # Show all contract periods and amounts

# Check for missing report months
smaug gaps

# Dump project data as machine-readable JSON
smaug dump QUASAR

# Generate proposal budget
smaug proposal --pi "Smith=10%" --phd 2 --travel 5000 --compute 8000
smaug proposal QUASAR                  # Use existing project personnel

# Project notes
smaug note list QUASAR                  # List all notes for a project
smaug note show QUASAR 1                # Show note by index
smaug note show QUASAR "stop-work"      # Show note by title substring

# Budget health and integrity dashboard
smaug health

# Revision history of git-backed configuration changes
smaug history

# Suggest budget mitigation strategies to extend stop-work date
smaug optimize QUASAR
smaug optimize QUASAR --target-months 18
```

### Write commands (modify configuration)

These commands modify YAML configuration files. Use with caution.

```bash
# Import spending reports
smaug report import /path/to/report.pdf                  # Single sponsored report
smaug report import /path/to/reports/                    # Batch import directory
smaug report import /path/to/report.csv --type non-sponsored  # Discretionary report
smaug report import /path/to/reports/ --dry-run           # Validate without copying
smaug report import /path/to/report.pdf --force           # Overwrite existing

smaug set-effort "Smith" QUASAR 25%
smaug set-salary "Smith" 180000
smaug set-end "Smith" QUASAR 2027-06
smaug set-departure "Smith" 2028-01
smaug add-person "New, Person" grad_student QUASAR 100% --salary 50000
smaug add-person "Kim, Minjae" masters QUASAR 100%                      # Hourly masters (rate from rates.yaml)
smaug add-person "Kim, Minjae" masters QUASAR 100% --salary 25 --hours 15  # Custom hourly rate and hours
smaug add-project ATLAS --type sponsored --budget 500000
smaug set-status ATLAS active
smaug set-project-end QUASAR 2028-06
smaug set-budget QUASAR 1500000
smaug travel add QUASAR "Conference" 2026-07-20 3500
smaug expense add QUASAR "GPU cluster" 12000 --category Equipment
smaug note add QUASAR "Budget Review" --message "Notes here..."
smaug note add QUASAR "Analysis"        # Opens $EDITOR
smaug note import QUASAR /path/to/file.md --title "Imported Doc"
smaug note remove QUASAR 1              # Remove by index

# Contractual budget periods (funding increments)
smaug budget add QUASAR --year 3 --start 2027-01 --end 2027-12 --total 550000
smaug budget add QUASAR --year 3 --start 2027-01 --end 2027-12 --total 550000 --direct 354839 --idc 195161
smaug budget set QUASAR --year 2 --total 520000

# Initialize a new Smaug workspace with git change-tracking
smaug init

# Revert/undo the last configuration change
smaug undo

# Clear all projects, personnel, and reports (requires confirmation: "CLEAR")
smaug clear

# Export a styled Excel spreadsheet spend plan
smaug export QUASAR spend_plan.xlsx

# Scan & import lockbox invoices
smaug invoice import /path/to/invoice.pdf
smaug invoice import /path/to/invoices/ --project QUASAR --force

# Setup and environment configuration
smaug setup mcp                # Register MCP server with Claude Code (project scope)
smaug setup mcp --scope user   # Register at user scope
smaug setup show               # Show installation and setup status
```

## Important conventions

- **Project names** are short uppercase identifiers (e.g., QUASAR, NEXUS, ATLAS)
- **Personnel names** use "Last, First" format but accept fuzzy matching
- **Personnel types**: `faculty`, `postdoc`, `grad_student`/`phd`, `masters_student`/`masters`/`ms`, `staff`
- **Masters students** are hourly (rate and hours from `rates.yaml`); JHU caps at 19.9 hrs/wk
- **Spending reports are cumulative** — the latest report contains the total
- **Effort** is expressed as a decimal (0.25) or percentage (25%) depending on context
- Use `smaug list` first to see available projects and their short names
- Use `smaug dump <PROJECT>` for machine-readable JSON output

## Python API

For programmatic access without shell commands:

```python
from smaug.api import SmaugAPI

api = SmaugAPI("/path/to/data")
projects = api.list_projects(status="active")
forecast = api.stopwork_forecast("QUASAR")
plan = api.spend_plan(["QUASAR"], add_personnel=[{"type": "phd", "effort_pct": 100}])
state = api.project_state_of_play("QUASAR")
health = api.health_check()
gaps = api.report_gaps()
mitigations = api.optimize_budget("QUASAR", target_months=12)
```

## MCP Server

Smaug ships a full-featured MCP server exposing both read and write tools for AI agents:

- **Analysis & Forecasting**: `list_projects`, `project_state_of_play`, `project_status`, `spending_report`, `spending_projection`, `stopwork_forecast`, `spend_plan` (with what-if modeling), `audit_spending`, `proposal_budget`, `dump_project`
- **Operations & Integrity**: `health_check`, `report_gaps`, `optimize_budget`, `list_budget_periods`, `budget_vs_actuals`, `funding_summary`, `personnel_overview`
- **Personnel & Effort Management**: `set_personnel_effort`, `remove_personnel_effort`, `set_salary`, `set_personnel_type`, `set_assignment_end`, `set_departure`, `add_personnel` (supports faculty, postdoc, PhD, and hourly masters students with `--hours` cap)
- **Project & Budget Lifecycle**: `add_project`, `set_project_status`, `set_project_budget`, `set_project_end`, `add_budget_period`, `set_budget_period`
- **Rates Configuration**: `set_fringe`, `set_idc`, `set_tuition`, `set_healthcare`
- **Items & Notes**: `add_travel_item`, `add_expense_item`, `edit_expense_item`, `remove_expense_item`, `list_project_notes`, `show_project_note`, `add_project_note`, `remove_project_note`
- **Importing**: `import_report`, `import_invoice`

The easiest way to register it with Claude Code:

```bash
smaug setup mcp              # Register with Claude Code (project scope)
smaug setup mcp --scope user  # Register at user scope
smaug setup show              # Verify installation status
```

Or manually:
```bash
claude mcp add --scope project smaug -- uv run --directory /path/to/smaug smaug-mcp
```
