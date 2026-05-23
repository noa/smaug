# Configuration Reference

Smaug reads all configuration from a data directory (default: `~/.smaug/`).
This guide covers every configuration file and its schema.

## Directory Layout

```
~/.smaug/
├── rates.yaml                     # Institutional rates (IDC, fringe, tuition)
├── projects/
│   ├── manifest.yaml              # Project definitions and identifiers
│   ├── personnel_config.yaml      # Personnel and effort allocations
│   ├── aliases.yaml               # Personnel nickname mappings (optional)
│   ├── travel_config.yaml         # Travel budget items
│   ├── purchases_config.yaml      # Equipment and recurring expenses
│   └── <PROJECT>/
│       ├── budget_config.yaml     # Contractual budget periods
│       └── notes/                 # Per-project notes (Markdown with YAML frontmatter)
└── reports/
    ├── sponsored/                 # Spending reports (PDF or CSV) — grant-funded
    ├── non-sponsored/             # Spending reports — discretionary accounts
    └── invoices/                  # Sponsor invoices (PDF)
```

## Setting the Data Directory

Smaug resolves the data directory in the following order:

1. `--data-dir /path/to/data` (CLI flag — highest priority)
2. `SMAUG_DATA_DIR` environment variable
3. `~/.smaug/` (auto-detected default)

---

## `rates.yaml` — Institutional Rates

Defines institution-specific financial parameters. Every cost projection
and proposal budget depends on these values.

```yaml
# Indirect Cost (F&A) rate applied to Modified Total Direct Costs (MTDC).
# MTDC excludes tuition and equipment over $5k.
idc_rate: 0.55

# Fringe benefit rates by employee classification.
# These are multiplied by salary to compute fringe costs.
fringe_rates:
  faculty: 0.315
  staff: 0.315
  postdoc: 0.211
  grad_student: 0.0       # Typically 0 — grad students don't receive fringe
  part_time: 0.0825

# Graduate student cost parameters
grad_student_costs:
  stipend: 50000           # Annual PhD stipend
  phd_tuition: 13334       # Annual tuition charged to grant (after remission)
  masters_tuition: 66670   # Full tuition for Masters students
  full_tuition: 66670      # Reference: full annual tuition rate
  health_dental: 4365      # Annual health & dental insurance per student

# Tuition billing schedule
tuition_billing:
  schedule: semester
  months: [1, 9]           # Months when tuition is billed (January, September)
  per_semester: 6667       # PhD tuition per semester
  masters_per_semester: 33335

# Hourly rates (for proposal budgets with Masters RAs)
undergrad_hourly: 15.0
masters_hourly: 20.0
masters_hours_per_week: 20
```

**Key points:**
- IDC is applied to the Modified Total Direct Costs base (salary + fringe + travel + compute + insurance + other), but **not** tuition or equipment.
- Tuition is billed in the months specified by `tuition_billing.months` (typically January and September for semester-based institutions).
- Fringe rates vary by employee type and should match your institution's negotiated rates.

---

## `manifest.yaml` — Project Definitions

Defines all projects tracked by smaug. There are two sections: `projects`
(sponsored/grant-funded) and `discretionary` (internal accounts).

```yaml
# Sponsored projects (grant-funded)
projects:
  QUASAR:                          # Short name — used everywhere in CLI
    name: Quantum-Assisted Sensing and Recognition
    status: active                 # proposed | accepted | active | completed
    grant_number: '200001'         # Internal grant identifier
    sponsored_program: '90200001'  # Sponsored program ID (used to match reports)
    award_id: X100001              # External award ID
    budget_dir: projects/QUASAR    # Relative path to project-specific config
    pi: Jane Smith
    end_date: 2028-06              # YYYY-MM format
    total_budget: 1500000          # Total award amount

  ATLAS:
    name: Adaptive Transfer Learning for Autonomous Systems
    status: proposed               # Not yet funded — excluded from default views
    pi: Jane Smith
    total_budget: 500000

# Discretionary accounts (startup funds, internal allocations)
discretionary:
  STARTUP:
    name: PI Startup Funds
    funded_program: '80010001'     # Used to match non-sponsored reports
    fund_center: '2110000200'
    reports_dir: reports/non-sponsored
    pi: Jane Smith
    type: discretionary
```

**Project identifiers** — smaug maps spending reports to projects using:
- `grant_number` or `sponsored_program` for sponsored projects
- `funded_program` for discretionary accounts

**Lifecycle statuses:**

| Status | Description | Shown in `smaug list`? |
|---|---|---|
| `proposed` | Under review, not yet funded | Only with `--all` or `--status proposed` |
| `accepted` | Funded but not yet spending | Only with `--all` or `--status accepted` |
| `active` | Currently spending (default) | Yes |
| `completed` | Grant period ended | Only with `--all` or `--status completed` |

---

## `personnel_config.yaml` — Personnel and Effort

Defines lab members, their salaries, and effort allocations across projects.
This is the primary input for all spending projections.

```yaml
personnel:
  - name: "Smith, Jane"           # "Last, First" format (convention, not required)
    type: faculty                 # faculty | postdoc | grad_student | staff
    annual_salary: 180000
    # departure: 2028-01          # Optional: date person leaves the lab
    assignments:
      - project: QUASAR
        effort: 0.10              # 10% effort (decimal, not percentage)
        start: 2025-01            # YYYY-MM — when effort begins
        # end: 2027-06            # Optional: when effort ends on this project
      - project: NEXUS
        effort: 0.10
        start: 2025-01

  - name: "Garcia, Maria"
    type: grad_student
    annual_salary: 50000
    assignments:
      - project: QUASAR
        effort: 0.50
        start: 2025-09
      - project: NEXUS
        effort: 0.50
        start: 2025-09
```

**Effort conventions:**
- Effort is always a **decimal** between 0 and 1 (e.g., `0.25` = 25%)
- A person can have assignments across multiple projects
- Monthly salary = `annual_salary / 12 * effort`
- Assignments are date-bounded: only active between `start` and `end`
- The `departure` field overrides all assignment end dates (person leaves entirely)

**Date handling:**
- `start` and `end` use `YYYY-MM` format (always interpreted as the 1st of the month)
- Assignments without an `end` date run indefinitely
- End dates can be cleared via `smaug set-end "Smith" QUASAR none`

---

## `travel_config.yaml` — Travel Budget

Tracks planned and completed travel expenses.

```yaml
travel:
  - project: QUASAR
    description: NeurIPS 2025
    date: 2025-12-10              # YYYY-MM-DD or YYYY-MM
    amount: 3200.00
    traveler: "Chen, Wei"         # Optional — who is traveling
    status: actualized            # estimated | actualized
  - project: QUASAR
    description: ICML 2026
    date: 2026-07-20
    amount: 3500.00
    traveler: "Garcia, Maria"
    status: estimated
```

**Status values:**
- `estimated` — planned but not yet incurred (shown in yellow in `spend-plan`)
- `actualized` — travel completed, costs confirmed (shown in green)

Travel costs are included in IDC calculations (they are part of MTDC).

---

## `purchases_config.yaml` — Equipment and Expenses

Tracks one-time purchases and recurring expenses.

```yaml
items:
  # One-time purchase (charged in a single month)
  - project: QUASAR
    description: GPU Server (A100)
    amount: 15000.00
    category: Equipment           # Equipment | Compute | Other
    date: 2025-06-15

  # Recurring expense (charged monthly within a date range)
  - project: QUASAR
    description: AWS Cloud Compute
    amount: 500.00                # Per-month amount
    category: Compute
    start: 2025-06-01
    end: 2027-06-01
```

**Categories:**
- `Equipment` — excluded from IDC (not part of MTDC)
- `Compute` — included in IDC
- `Other` — included in IDC
- Any other value — included in IDC (falls through to "Other")

---

## `budget_config.yaml` — Contractual Budget Periods

Located in each project's subdirectory (e.g., `projects/QUASAR/budget_config.yaml`).
Defines the contractual budget ceiling by year, used for `budget-vs-actuals`.

```yaml
contract:
  award_id: X100001
  pi: Jane Smith
  start_date: 2025-01-01
  periods:
    year1:
      start: 2025-01-01
      end: 2025-12-31
    year2:
      start: 2026-01-01
      end: 2026-12-31
    year3:
      start: 2027-01-01
      end: 2028-06-30

totals:
  total_budget: 1500000
  total_direct_costs: 967742
  total_indirect_costs: 532258

by_year:
  year1:
    total: 450000
    direct: 290323
    idc: 159677
  year2:
    total: 500000
    direct: 322581
    idc: 177419
  year3:
    total: 550000
    direct: 354839
    idc: 195161
```

This file is used by:
- `smaug budget-vs-actuals` — compares spending against contractual ceilings
- `smaug spend-plan --year 2` — scopes the spend plan to a specific contract year

---

## `aliases.yaml` — Personnel Nicknames

See [Personnel Aliases](aliases_and_identity.md) for full documentation.

```yaml
aliases:
  jane: "Smith, Jane"
  wei: "Chen, Wei"
  maria: "Garcia, Maria"
```

---

## Spending Reports

Place spending reports in `reports/sponsored/` or `reports/non-sponsored/`.
Smaug auto-detects the format using its parser plugin system.

**Supported formats:**
- **CSV** (built-in) — see [Writing Parsers](writing_parsers.md) for the expected schema
- **JHU PDF** (built-in) — institution-specific parser for JHU financial reports
- **Custom parsers** — register via Python entry points

Reports must contain **cumulative** spending totals. Smaug computes monthly
deltas from the difference between consecutive reports.
