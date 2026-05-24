# Spend Plans and What-If Scenarios

The `spend-plan` command generates detailed monthly spending projections for
one or more projects, with support for hypothetical personnel changes,
contract year scoping, and side-by-side comparison mode.

## Basic Usage

```bash
# Generate a spend plan for a single project
smaug spend-plan QUASAR

# Multiple projects at once
smaug spend-plan QUASAR NEXUS
```

By default, the plan projects from today through the project's `end_date`
(from `manifest.yaml`). If no end date is set, it shows 12 months.

## Date Range Controls

### Fiscal year view

Scope the plan to a fiscal year (July 1 – June 30):

```bash
smaug spend-plan QUASAR --fy 2026
# Shows: Jul 2025 through Jun 2026
```

### Contract year view

If the project has a `budget_config.yaml` with defined contract periods,
you can scope to a specific contract year:

```bash
smaug spend-plan QUASAR --year 2
# Shows: the date range defined in budget_config.yaml for year2
```

### Custom end date

```bash
smaug spend-plan QUASAR --to 2027-06
```

## What-If Scenarios

The `--if` flag lets you model hypothetical personnel changes without
modifying any configuration files.

### Add a hypothetical person

```bash
# Add a PhD student at 100% effort
smaug spend-plan QUASAR --if "+phd@100%"

# Add a postdoc at 100% effort with $85k salary
smaug spend-plan QUASAR --if "+postdoc@100%:85000"

# Add a staff member
smaug spend-plan QUASAR --if "+staff@50%:65000"
```

The format is: `+type@effort%[:salary]`

| Type | Default salary | Notes |
|---|---|---|
| `phd` or `grad` | Uses stipend from `rates.yaml` | Includes tuition and insurance |
| `postdoc` | Must specify salary | Fringe from `rates.yaml` |
| `staff` | Must specify salary | Fringe from `rates.yaml` |
| `faculty` | Must specify salary | Fringe from `rates.yaml` |

### Override existing effort

Change an existing person's effort on the project:

```bash
# Set Smith's effort to 50%
smaug spend-plan QUASAR --if "Smith=50%"

# Works with aliases and fuzzy matching
smaug spend-plan QUASAR --if "jane=20%"
smaug spend-plan QUASAR --if "chen=50%"
```

### Combine multiple hypotheticals

```bash
smaug spend-plan QUASAR \
  --if "+phd@100%" \
  --if "Smith=25%" \
  --if "+postdoc@100%:80000"
```

## Comparison Mode

Use `--compare` with `--if` to see a side-by-side delta between the current
plan and the hypothetical scenario:

```bash
smaug spend-plan QUASAR --compare --if "+phd@100%"
```

This outputs the hypothetical spend plan **plus** a comparison panel:

```
┌─────────── Comparison ───────────┐
│ Current total:          $342,000 │
│ Hypothetical total:     $418,500 │
│ Delta:                  +$76,500 │
└──────────────────────────────────┘
```

## Output Columns

The spend plan table shows monthly breakdowns:

| Column | Description |
|---|---|
| Month | Year-month, with ◀ marking the current month |
| Salary | Direct salary costs |
| Fringe | Fringe benefits (salary × fringe rate) |
| Travel | Travel expenses scheduled for this month |
| Compute | Cloud/HPC compute costs |
| Equip | Equipment purchases (excluded from IDC) |
| Other | Other direct costs |
| IDC | Indirect costs on MTDC base |
| Total | All costs for the month |

Months in the past are dimmed. The current month is highlighted with a ◀ marker.
Grand totals are color-coded:
- 🟢 Green: under $200k
- 🟡 Yellow: $200k–$500k
- 🔴 Red: over $500k

## Personnel Assumptions

The header panel lists all personnel contributing to the project with their
effort percentages and end dates:

```
┌──── Spend Plan: QUASAR ────────────────────────────────────┐
│ Through June 2028                                          │
│ Personnel: Faculty Smith 10%, Postdoc Chen 100%,           │
│            PhD Martinez 50% (thru Sep 2027)                │
└────────────────────────────────────────────────────────────┘
```

Personnel with end dates earlier than the project end date are flagged
in yellow with their departure month.

## Travel and Expense Detail

When travel or one-time expenses fall in a projected month, they appear
as detail annotations below the table:

```
    ▸ Travel: ICML 2026 $3,500.00 (estimated)
    ▸ Equipment: GPU Server (A100) $15,000.00
```
