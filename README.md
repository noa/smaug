# 🐉 Smaug

**Budget tracking and spending projections for academic research grants.**

Smaug helps PIs and lab managers track grant spending, project burn rates, manage personnel effort allocations, and forecast stop-work dates — all from the command line.


<details open>
<summary><b>💬 Example: Claude + Smaug MCP</b></summary>

> **You:** We got our April spending report for ARIA. When does the money run out, and what happens if Priya goes on internship this summer?

> **Claude:** I'll import the report, check the forecast, and model the internship scenario.
>
> *Called `import_report` — imported April 2026 spending report for ARIA*
>
> *Called `stopwork_forecast` for ARIA*
>
> Based on April actuals ($287,431 cumulative against a $1.2M ceiling), ARIA hits stop-work in **March 2028** at the current burn rate of ~$38k/month:
>
> | Month | Projected | Cumulative | Remaining | Status |
> |-------|-----------|-----------|-----------|--------|
> | 2026-05 | $38,219 | $325,650 | $874,350 | OK |
> | … | | | | |
> | 2028-02 | $39,106 | $1,178,304 | $21,696 | OK |
> | 2028-03 | $39,106 | $1,217,410 | −$17,410 | ⛔ Stop-work |
>
> *Called `spend_plan` with `override_effort: [{name: "Priya", effort_pct: 0, start: "2026-06", end: "2026-09"}]`*
>
> If Priya is at 0% for June–September (internship), you save ~$28,800 over those four months (stipend + fringe + tuition). That pushes stop-work out to **April 2028** — one extra month. Want me to set up that date-bounded effort change now, or model other scenarios first?

To try this yourself: install [Claude Desktop](https://claude.ai/download), then register Smaug as an MCP tool:
```bash
smaug setup mcp
```
See [Set up the MCP server](#set-up-the-mcp-server-optional) below for details.

</details>


---

## Quick Start

### Install

Smaug is not published to PyPI. Clone and install it with [uv](https://docs.astral.sh/uv/):

```bash
git clone https://github.com/noa/smaug.git
cd smaug
uv pip install -e ".[mcp]"
```

This installs the `smaug` CLI, the `smaug-mcp` MCP server, and registers plugin entry points in editable mode.

<details>
<summary>Alternative install methods</summary>

**pip (editable):**
```bash
pip install -e ".[dev,mcp]"
```

**Directly from GitHub (no clone):**
```bash
pip install "git+https://github.com/noa/smaug.git#egg=smaug[mcp]"
# or as a global CLI tool:
uv tool install git+https://github.com/noa/smaug.git
```
</details>

### Initialize a workspace

```bash
smaug init
```

This creates a `~/.smaug/` directory with template configuration files.

### Set up the MCP server (optional)

To use Smaug as an MCP tool with [Claude Code](https://docs.anthropic.com/en/docs/claude-code) or other MCP-compatible agents, register it:

```bash
smaug setup mcp
```

This auto-detects the repository location and registers `smaug-mcp` as a project-scoped MCP server in `.mcp.json`. To register at user scope instead:

```bash
smaug setup mcp --scope user
```

<details>
<summary>Manual MCP registration</summary>

If you prefer to register manually with the Claude CLI:
```bash
claude mcp add --scope project smaug -- uv run --directory /path/to/smaug smaug-mcp
```
</details>

> [!TIP]
> Run `smaug setup show` to verify your installation — it checks whether the CLI, MCP dependencies, data directory, and MCP registration are all configured correctly.

### Or try with example data

```bash
git clone https://github.com/noa/smaug.git
cd smaug
smaug --data-dir examples list
```

### Core commands

```bash
# List all projects with budget overview
smaug list

# Detailed status for a project
smaug status QUASAR

# Project spending over time
smaug report QUASAR

# Personnel effort across all projects
smaug personnel

# Monthly spending projections
smaug project QUASAR --months 12

# Monthly spend plan with what-if scenarios
smaug spend-plan QUASAR --if "+phd@100%"

# Stop-work date forecast
smaug stopwork QUASAR --ceiling 450000

# Generate a proposal budget
smaug proposal --pi "Smith=10%" --phd 2 --travel 5000 --compute 8000
```

<details>
<summary>Starting a new project &amp; clearing demo data</summary>

When you initialize a new workspace, Smaug seeds it with demo projects (`QUASAR`, `NEXUS`, `ATLAS`, `STARTUP`) and sample personnel. To track your own grants, clear the demo data first:

```bash
smaug clear
```

This prompts for confirmation (`CLEAR`), then resets all config files and deletes demo project directories and reports.

Once clean, add your own project:

```bash
# Add a sponsored grant
smaug add-project MYGRANT --type sponsored --budget 750000 --grant "123456"

# Add personnel
smaug add-person "Smith, John" faculty MYGRANT 15% --salary 120000
smaug add-person "Doe, Jane" grad_student MYGRANT 50% --salary 48000

# Add travel and expenses
smaug travel add MYGRANT "IEEE Conference" 2026-10 3200
smaug expense add MYGRANT "Workstation" 8500 --category Equipment

# Import spending reports
smaug report import /path/to/monthly_report.pdf
```

Or use an AI agent one-liner:
```bash
claude "Create a new project ATLAS for $1M with two PhD students, then import report.pdf and summarize spending"
```
</details>

---

## Motivation: Why Smaug?

Managing academic research grant budgets is complex and time-consuming. PIs and lab managers must navigate multiple separate institutional systems, compile fragmented PDF/CSV reports, track fringe and indirect cost (F&A) rates, and model personnel effort across projects.

Smaug was created to address these high-level administration challenges:

*   **Unified Spending & Effort View:** Provides a single, centralized command-line interface to inspect spending, travel, equipment purchases, and personnel effort across **all** of your sponsored grants and internal discretionary accounts.
*   **Catching Spending Discrepancies:** Detects deviations and conflicts between expected monthly effort configurations (planned) and actual charges extracted from parsed expenditure reports (actual), letting you fix billing mistakes before they propagate.
*   **Preventing Common Finance Issues:** Flags common administrative problems such as incorrect or overlapping personnel effort allocations across multiple projects, delayed sponsor invoices, and approaching contractual spending ceilings.
*   **Cash Flow Estimates for Sponsors:** Generates and exports monthly spending projection models (spend plans) that can be shared with program managers and sponsors as cash flow estimates and stop-work forecasts.



---

## Sponsored Grant Lifecycle

For sponsored awards, Smaug maps to the natural lifecycle of a research grant:

1. **Proposal** — Generate multi-year budget tables with salary escalation, fringe, tuition, and F&A rates (`smaug proposal`). The proposal budget establishes the *expected* spending plan: how much will be spent, on whom, and when.

2. **Award & Setup** — Once a proposal is accepted, create the project in Smaug with the contractual budget ceiling, personnel effort allocations, and budget periods (`smaug add-project`, `smaug add-person`, `smaug budget add`).

3. **Active Tracking** — As the institution issues monthly expenditure reports, import them to track cumulative *actual* spending against the expected baseline (`smaug report import`). Generate spend plans and stop-work forecasts to project future cash flow (`smaug spend-plan`, `smaug stopwork`).

4. **Incremental Funding & Modifications** — Record contract modifications, new budget periods, or ceiling adjustments as they occur (`smaug budget add`, `smaug set-budget`).

5. **Audit & Reconciliation** — Compare actual charges against expected personnel effort to detect billing discrepancies, over-commitments, or under-allocations (`smaug audit`). Cross-check sponsor invoices against internal reports (`smaug invoice import`).

The proposal establishes what spending *should* look like; the imported spending reports measure what *actually* happened. Smaug's role is to make these two views easy to compare and reconcile throughout the life of an award.

> [!TIP]
> **You don't need to memorize these commands.** If you're using a coding agent (Claude Code, Gemini, etc.), you can describe what you need in plain English and the agent will select the right Smaug commands for you:
> ```bash
> claude "Generate a 3-year proposal budget for 1 PI at 10% and 2 PhD students"
> claude "Set up project ATLAS with a $500k ceiling ending June 2028, add two grad students"
> claude "Import this month's spending report and flag any discrepancies against expected effort"
> claude "We got a $200k supplement on ATLAS — update the budget and reforecast the stop-work date"
> ```

---

## Core Capabilities

Smaug helps answer common administrative questions about project budgets and projections:

### 1. Stop-Work Date Forecasting
Combines current cumulative spending reports, planned travel, equipment purchases, and personnel effort to project when funding will run out based on the contractual ceiling:
```bash
smaug stopwork QUASAR --ceiling 450000
```
*Outputs the projected stop-work month based on the remaining budget:*
```text
╭──────────────────────────── Stop-Work Forecast: Quantum-Assisted Sensing and Recognition ────────────────────────────╮
│ Latest Report: March 2026                                                                                            │
│ Budget Envelope: $  450,000.00  (remaining-budget envelope)                                                          │
│ Remaining for forward: $  450,000.00                                                                                 │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯
                       Forward Projection (Base)
╭────────────┬─────────────┬──────────────┬──────────────┬────────────╮
│ Month      │   Projected │   Cumulative │    Remaining │ Status     │
├────────────┼─────────────┼──────────────┼──────────────┼────────────┤
│ 2026-04    │ $    23,844 │  $    23,844 │  $   426,156 │ OK         │
│ 2026-05    │ $    23,844 │  $    47,688 │  $   402,312 │ OK         │
│ ...        │             │              │              │            │
│ 2027-08    │ $    23,069 │  $   419,275 │  $    30,725 │ OK         │
│ 2027-09    │ $    28,094 │  $   447,369 │  $     2,631 │ OK         │
╰────────────┴─────────────┴──────────────┴──────────────┴────────────╯
Funds sufficient through projected period.
```

### 2. Hypothetical Scenario Spending Plans
Model hypothetical hires or change effort allocations to see the monthly cash flow impact on a project budget:
```bash
# Model adding a PhD student at 100% effort and reducing Smith to 50% effort
smaug spend-plan QUASAR --if "+phd@100%" --if "Smith, Jane=50%" --compare
```
*Displays a side-by-side comparison of the baseline cash flow versus the hypothetical scenario:*
```text
╭─────────────────────────────────────────────────────────── Spend Plan: QUASAR ───────────────────────────────────────────────────────────╮
│  Hypothetical: +phd@100%, Smith, Jane=50%                                                                                                │
│  Through June 2028                                                                                                                       │
│  Personnel: Faculty Smith, Jane 50%, Postdoc Chen, Wei 100%, PhD Martinez, Sofia 50%, Staff Johnson, Alex 50%, PhD [Hypothetical           │
│  Grad_Student #1] 100%                                                                                                                   │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─────────────────────────────────────────────────────────────── Comparison ───────────────────────────────────────────────────────────────╮
│  Current total:      $     613,102                                                                                                       │
│  Hypothetical total: $   1,110,810                                                                                                       │
│  Delta:                  +$497,708                                                                                                       │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### 3. Proposal Budget Generation
Generates multi-year proposal budget tables incorporating salary escalation, fringe, graduate tuition, health insurance, and F&A (IDC) rates:
```bash
smaug proposal --pi "Smith=10%" --phd 2 --travel 5000 --compute 8000 --years 3
```
*Outputs yearly columns including MTDC calculations and indirect cost breakdowns:*
```text
                                     Budget Summary
╭────────────────────────┬──────────────┬──────────────┬──────────────┬────────────────╮
│ Category               │       Year 1 │       Year 2 │       Year 3 │          Total │
├────────────────────────┼──────────────┼──────────────┼──────────────┼────────────────┤
│ Salaries & Wages       │     $118,000 │     $121,540 │     $125,186 │       $364,726 │
│ Fringe Benefits        │       $5,670 │       $5,840 │       $6,015 │        $17,525 │
│ Tuition                │      $26,668 │      $26,668 │      $26,668 │        $80,004 │
│ Health & Dental Ins.   │       $8,730 │       $8,730 │       $8,730 │        $26,190 │
│ Travel                 │       $5,000 │       $5,000 │       $5,000 │        $15,000 │
│ Compute / Cloud        │       $8,000 │       $8,000 │       $8,000 │        $24,000 │
├────────────────────────┼──────────────┼──────────────┼──────────────┼────────────────┤
│ Total Direct Costs     │     $172,068 │     $175,778 │     $179,600 │       $527,446 │
│ F&A (55% MTDC)         │      $79,970 │      $82,011 │      $84,112 │       $246,093 │
├────────────────────────┼──────────────┼──────────────┼──────────────┼────────────────┤
│ GRAND TOTAL            │     $252,038 │     $257,789 │     $263,712 │       $773,538 │
╰────────────────────────┴──────────────┴──────────────┴──────────────┴────────────────╯
```

### 4. Spending & Effort Auditing
Audits parsed expenditure reports against expected monthly efforts in `personnel_config.yaml`, flagging billing deviations and discrepancies:
```bash
smaug audit QUASAR --threshold 10
```
*Flags deviations, such as over-commitment or under-allocation of personnel.*

### 5. Personnel Anonymization & Privacy
Prevents confidential salary information from leaking to unauthorized contexts. Anonymization maps real names to consistent anonymized identifiers (`Faculty 1`, `PhD 1`) while supporting bidirectional lookup:
```bash
smaug personnel --anonymize
```
*Note: anonymization is enabled by default for AI agents interacting with the data via the MCP server.*

---

## Features

- **Multi-project tracking** — Monitor sponsored grants and discretionary accounts side by side
- **Spending projections** — Monthly burn rate calculations based on personnel configurations
- **Stop-work forecasting** — Predict when funding will run out under current spend rates
- **Personnel management** — Track effort allocations, salary changes, and assignment dates
- **Personnel aliases** — Fuzzy name matching, nicknames, and index-based personnel lookup
- **Spend plans** — Generate detailed monthly projections with what-if scenarios
- **Audit** — Compare actual spending against expected personnel effort
- **Budget vs. actuals** — Reconcile projections against contractual budget ceilings
- **Proposal budgets** — Generate multi-year proposal budgets from personnel specs
- **Project notes** — Per-project documentation with Markdown and YAML frontmatter
- **Invoice validation** — Cross-check sponsor invoices against internal reports
- **Plugin parsers** — Extensible architecture for institution-specific report formats


## Configuration

Smaug reads data from a configurable directory (default: `~/.smaug/`):

```
~/.smaug/
├── rates.yaml              # Institutional rates (IDC, fringe, tuition)
├── projects/
│   ├── manifest.yaml       # Project definitions
│   ├── personnel_config.yaml   # Personnel and effort allocations
│   ├── travel_config.yaml      # Travel budget items
│   └── QUASAR/
│       └── budget_config.yaml  # Contractual budget periods
└── reports/
    ├── sponsored/          # Spending reports (PDF or CSV)
    └── invoices/           # Sponsor invoices
```

Set the data directory via:
1. `--data-dir` flag
2. `SMAUG_DATA_DIR` environment variable
3. `~/.smaug/` (auto-detected)

See the [Configuration Reference](docs/configuration.md) for detailed format documentation.

## Documentation

| Guide | Description |
|---|---|
| [Configuration Reference](docs/configuration.md) | All YAML config files, schemas, and directory layout |
| [Personnel Aliases & Identity](docs/aliases_and_identity.md) | Nicknames, fuzzy matching, and index-based personnel lookup |
| [Anonymization & Privacy](docs/anonymization.md) | Prevent confidential salary info from leaking to AI agents and unauthorized users |
| [Spend Plans & What-If Scenarios](docs/spend_plans.md) | Monthly projections, hypothetical hiring, and comparison mode |
| [Proposal Budget Generation](docs/proposal_budgets.md) | Multi-year proposal budgets with salary escalation |
| [Auditing & Reconciliation](docs/auditing.md) | Spending audits, stop-work forecasts, and report validation |
| [Project Notes](docs/project_notes.md) | Per-project Markdown notes with YAML frontmatter |
| [Writing Custom Parsers](docs/writing_parsers.md) | Plugin architecture for institution-specific report formats |
| [Agentic Workflows & Operations](docs/agentic_workflows.md) | Multi-step agent reasoning recipes, spending plans, rebalancing, and audits |

## Institutional Customization (JHU & Beyond)

Smaug uses **Johns Hopkins University (JHU)** as its default institutional template out of the box. The standard template configurations in `rates.yaml`, the parsed PDF sponsored report extractors, and the lockbox invoice formats are pre-configured for JHU administrative formats and graduate student benefit structures.

If you are using Smaug at a different institution, you can customize it for your school in two ways:

### 1. Adjusting Institutional Rates
You do not need to write code to change financial parameters. Simply edit the centralized institutional rates configuration file in `~/.smaug/rates.yaml` (or the folder passed via `--data-dir`):
- **F&A (Indirect Costs)**: Adjust the `idc` percentage rate (e.g., `0.55` for 55% MTDC).
- **Fringe Benefit Pools**: Update the decimal percentages for faculty, postdoc, staff, and graduate student fringe categories.
- **Tuition & Insurance**: Update the per-semester graduate student tuition costs and annual health & dental insurance premiums.

### 2. Adding Custom Report/Invoice Parsers
To parse non-JHU specific PDF reports or specialized sponsor invoices, you can implement a custom parser plugin using Smaug's extensible architecture:
1. Create a class inheriting from `smaug.parsers.ReportParser` or `smaug.parsers.InvoiceParser`.
2. Implement `can_parse(file_path)` (file detection) and `parse(file_path)` (data extraction logic).
3. Register your parser plugin under the `smaug.parsers` entry points group in your custom package's `pyproject.toml`.

See the [Writing Custom Parsers](docs/writing_parsers.md) and [Configuration Reference](docs/configuration.md) guides for a complete walkthrough.

## Agent Integration & Getting Started Guides

Smaug supports agentic workflows by providing three integration channels (CLI, Python API, and MCP) to query data, calculate burn rates, and run forecasts.

> [!TIP]
> **Choosing Your Runtime Setup (Cloned Repository vs. MCP Tool):**
> * **Cloned Repository Setup (Recommended for Developers/Technically Savvy Users):** If you plan to customize Smaug, fix bugs, or have coding agents (like Claude Code or Gemini/Antigravity) run tests and modify the codebase, you should run the agent from the root of a cloned git repository. This bypasses MCP server configuration and allows agents to operate directly on the local workspace in editable mode.
> * **MCP Tool Setup (Recommended for End-Users):** If you simply want to use Smaug to manage your budgets, run forecasts, or model what-if scenarios without modifying its codebase, you do not need to clone the repository. Instead, configure Smaug's Model Context Protocol (MCP) server externally, allowing any MCP-compliant agent to query and manage your data without being run from the Smaug repository itself.

To configure AI agents to work with Smaug, we provide getting started guides:

*   **[Agent Integration Overview](docs/agents/overview.md)**: A high-level introduction to the integration pathways (CLI, Python API, and MCP).
*   **[Claude Code Getting Started Guide](docs/agents/claude_code.md)**: Step-by-step setup instructions for Anthropic's Claude Code command-line agent, utilizing the [CLAUDE.md](CLAUDE.md) pointer rules.
*   **[Gemini & Antigravity Guide](docs/agents/gemini.md)**: Onboarding instructions for Google Gemini and Antigravity 2.0 workspace rules.
*   **[Codex & Custom API-Driven Agents](docs/agents/codex_agents.md)**: Designing custom python script agents and pipeline wrappers utilizing OpenAI Codex / GPT APIs and `smaug dump` JSON outputs.
*   **[Model Context Protocol (MCP) Guide](docs/agents/mcp_agents.md)**: Connecting Smaug's local `smaug-mcp` tool server directly to Claude Desktop and other MCP-compliant agents.

### Example Agentic Workflow: Project Plus-Up Spending Feasibility

In academic administration, managing unexpected grant changes requires careful calculation of institutional overhead and benefits. When an AI agent is asked:
> *"We received a $300k budget plus-up on QUASAR that must be spent by September 2026. What personnel hires are feasible under JHU rates?"*

The agent can programmatically search the option space using Smaug's programmatic API to evaluate combinations (e.g., postdocs, PhD students, and equipment purchases) by calculating salaries, JHU fringe rates, semester tuition billing schedules, and F&A (indirect cost) recovery:

```python
from smaug.api import SmaugAPI

api = SmaugAPI()

def evaluate_spend_scenario(add_personnel):
    # Retrieve hypothetical spend plan for the next 6 months
    plan = api.spend_plan(
        projects=["QUASAR"],
        months=6,
        add_personnel=add_personnel
    )
    # Sum up expenditures billed within the June–September 2026 window
    net_cost = sum(
        entry["total"] for entry in plan["projections"]
        if "2026-06" <= entry["month"] <= "2026-09"
    )
    # Compare with baseline spending to find net incremental cost
    baseline = api.spend_plan(projects=["QUASAR"], months=6)
    base_cost = sum(
        entry["total"] for entry in baseline["projections"]
        if "2026-06" <= entry["month"] <= "2026-09"
    )
    return net_cost - base_cost

# Evaluate adding 1 full-time postdoc vs. 2 PhD students (inc. JHU tuition & insurance schedules)
postdoc_cost = evaluate_spend_scenario([{"type": "postdoc", "effort_pct": 100, "salary": 85000}])
phd_cost = evaluate_spend_scenario([{"type": "grad_student", "effort_pct": 100, "salary": 50000}] * 2)

print(f"Postdoc option cost: ${postdoc_cost:,.2f}")  # Calculates salary + 21.1% fringe + 55% F&A
print(f"2x PhD option cost: ${phd_cost:,.2f}")        # Calculates stipends + Sept tuition/insurance + F&A
```

Once the agent identifies a suitable plan (e.g., adding a Postdoc and two PhD students at 50% effort, leaving the remainder to purchase an F&A-exempt GPU server), it can execute the CLI setup commands directly:

```bash
# Add postdoc and graduate students to the project configuration
smaug add-person "Postdoc, New" postdoc QUASAR 100% --salary 85000
smaug add-person "Student, Grad1" grad_student QUASAR 50% --salary 50000
smaug add-person "Student, Grad2" grad_student QUASAR 50% --salary 50000

# Obligate the remaining funds for a custom compute server (Equipment is F&A-exempt)
smaug expense add QUASAR "GPU Server Cluster" 150000 --category Equipment
```

See the [Agentic Workflows Guide](docs/agentic_workflows.md) for full descriptions of this and other automated operational recipes (such as discrepancy auditing, multi-project effort rebalancing, and proposal drafting).

## Development

```bash
git clone https://github.com/noa/smaug.git
cd smaug
uv venv && uv pip install -e ".[dev]"
uv run pytest tests/ -v
```

## License

GNU Affero General Public License v3. See [LICENSE](LICENSE).
