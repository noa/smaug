# 🐉 Smaug

**Budget tracking and spending projections for academic research grants.**

Smaug helps PIs and lab managers track grant spending, project burn rates, manage personnel effort allocations, and forecast stop-work dates — all from the command line.

> [!IMPORTANT]
> **Privacy & Separation of Concerns:**
> Smaug is designed with a strict separation between code and sensitive data. All grant budgets, personnel salaries, and financial transaction histories reside strictly on your local machine and are **never** stored or tracked inside the package codebase.
>
> * **Default Data Location:** By default, your workspace state is stored in `~/.smaug/` in your user home directory.
> * **Customizing the Location:** You can override this default by setting the `SMAUG_DATA_DIR` environment variable, or by passing the `--data-dir /path/to/dir` option to any CLI command.

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

## Quick Start

### Install

Since Smaug is a local git repository and not published to PyPI, you can install it using one of the following methods depending on your workflow:

#### Option A: From a cloned local repository (Recommended for Developers/Savvy Users)
Clone the repository and install it (optionally in editable mode for development and plugin registration):

```bash
git clone https://github.com/noa/smaug.git
cd smaug

# Standard install
pip install .
# or
uv pip install .

# Editable install (Recommended for development, testing, or running local agents)
pip install -e ".[dev,mcp]"
# or
uv pip install -e ".[dev,mcp]"
```

> [!TIP]
> **Developer & Agentic Editable Installs:**
> Installing in editable mode (`-e`) ensures that changes to the Python code are immediately live. Crucially, it also registers the custom plugin entry points (e.g. `smaug.parsers`), which are required for custom report parsers to work correctly.

#### Option B: Directly from GitHub (Recommended for general non-dev use)
If you do not want to clone the codebase and just want to install Smaug as a CLI/MCP tool inside your environment, you can install it directly from GitHub:

```bash
# Install CLI only
pip install git+https://github.com/noa/smaug.git

# Install CLI with MCP server support
pip install "git+https://github.com/noa/smaug.git#egg=smaug[mcp]"

# Or using uv tool as a global CLI tool
uv tool install git+https://github.com/noa/smaug.git
# With MCP server support:
uv tool install --with mcp git+https://github.com/noa/smaug.git
```

### Initialize a new workspace

```bash
smaug init
```

This creates a `~/.smaug/` directory with template configuration files.

### Starting a New Project & Clearing Demo Data

When you initialize a new workspace, Smaug seeds it with a set of template files containing demo projects (`QUASAR`, `NEXUS`, `ATLAS`, `STARTUP`) and sample personnel. To track your own grants, you should first clear the demo data to start with a clean slate:

#### 1. Clearing Demo Projects

To remove all demo data and start with a completely fresh workspace, run the following CLI command:

```bash
smaug clear
```

This command will prompt you with a warning and require you to type **`CLEAR`** to confirm the action. Once confirmed, it automatically:
- Resets all configuration files (`manifest.yaml`, `personnel_config.yaml`, `travel_config.yaml`, `purchases_config.yaml`) to clean, empty states.
- Deletes any project-specific directories (such as `QUASAR/` and `NEXUS/`).
- Deletes all imported reports and invoices under the `reports/` folder.
- Commits the purging to Git (if change-tracking is active).

*(Alternatively, you can manually clear out these configurations by resetting the YAML files under `~/.smaug/projects/` to empty lists/objects and deleting the project subdirectories/reports manually.)*

#### 2. Starting a New Project

Once your workspace is clean, you can start a new project in two ways:

##### Option A: Via the CLI (Recommended)

1. **Add a sponsored or discretionary project** (this automatically appends it to `manifest.yaml`):
   ```bash
   # Add a sponsored grant
   smaug add-project MYGRANT --type sponsored --budget 750000 --grant "123456"

   # Add an internal discretionary account
   smaug add-project STARTUP --type discretionary
   ```
2. **Add personnel to the project**:
   ```bash
   smaug add-person "Smith, John" faculty MYGRANT 15% --salary 120000
   smaug add-person "Doe, Jane" grad_student MYGRANT 50% --salary 48000
   ```
3. **Add planned expenses or travel**:
   ```bash
   # Add travel
   smaug travel add MYGRANT "IEEE Conference" 2026-10 3200

   # Add recurring or one-time purchases
   smaug expense add MYGRANT "High-Performance Workstation" 8500 --category Equipment
   ```
4. **Import spending reports**:
   When monthly financial reports are issued by your institution, import them to track actual spending:
   ```bash
   smaug report import /path/to/monthly_report.pdf
   ```

##### Option B: By Editing YAML Directly

You can also define your project, personnel, and expenses by editing the YAML configuration files in `~/.smaug/projects/` directly. Ensure you follow the schemas detailed in the [Configuration Reference](docs/configuration.md).

For sponsored projects, you may want to create a project-specific subdirectory (e.g. `~/.smaug/projects/MYGRANT/`) containing a `budget_config.yaml` to define your contractual budget periods.


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
> * **Cloned Repository Setup (Recommended for Developers/Technically Savvy Users):** If you plan to customize Smaug, fix bugs, or have coding agents (like Claude Code or Gemini/Antigravity) run tests and modify the codebase, you should run the agent from the root of a cloned git repository. This bypasses MCP server configuration and allows agents to seamlessly operate on the local workspace in editable mode.
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

Once the agent selects the optimal plan (e.g., adding a Postdoc and two PhD students at 50% effort, leaving the remainder to purchase an F&A-exempt GPU server), it can execute the CLI setup commands directly:

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
