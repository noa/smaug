# Auditing and Reconciliation

Smaug provides tools to compare actual spending against expected costs,
validate spending report integrity, and reconcile projections against
contractual budget ceilings.

## Spending Audit (`smaug audit`)

The audit command compares **actual** salary spending from parsed reports
against **expected** costs based on `personnel_config.yaml` effort allocations.

### Basic usage

```bash
# Audit a specific project (last 3 months by default)
smaug audit QUASAR

# Audit all projects
smaug audit

# Look back further
smaug audit QUASAR --months 6

# Adjust the variance threshold (default: 10%)
smaug audit QUASAR --threshold 15
```

### Finding types

The audit produces four types of findings:

| Finding | Severity | Meaning |
|---|---|---|
| `effort_variance` | warning/error | Expected vs. actual salary differs significantly |
| `missing_from_report` | info | Person is in config but not found in spending report |
| `unexpected_in_report` | warning | Person appears in report but not in config |
| `outside_assignment` | warning | Spending outside the configured assignment window |

Variance thresholds:
- **Warning:** variance exceeds the `--threshold` (default 10%)
- **Error:** variance exceeds 25%

### Example output

```
=== Audit Report: QUASAR ===
Periods: January 2026, December 2025, November 2025

Summary: 1 errors, 2 warnings, 1 info

January 2026
  ✗ Chen, Wei: $7,200.00 vs expected $6,000.00 (over by 20.0%)
  ! Martinez, Sofia: $4,500.00 vs expected $4,166.67 (over by 8.0%)

December 2025
  ○ Johnson, Alex: Expected $2,708.33 but not found in report

November 2025
  ! Unknown, Person: Found $1,500.00 but person not in config
```

### How it works

For each reporting period, the audit:

1. Computes **expected** monthly salary for each person: `annual_salary / 12 × effort`
2. Extracts **actual** salary from the spending report's per-person breakdown
3. Compares the two and flags discrepancies above the threshold

The audit uses normalized name matching to handle minor formatting differences
between config names and report names.

---

## Budget vs. Actuals (`smaug budget-vs-actuals`)

Compares cumulative spending against the contractual budget ceiling defined
in `budget_config.yaml`.

```bash
smaug budget-vs-actuals QUASAR
```

This requires a `budget_config.yaml` file in the project's `budget_dir` with
per-year budget allocations. The command shows:

- Cumulative spending through each contract period
- Budget ceiling for each period
- Variance (over/under budget)
- Projected spending through the end of the current period

---

## Report Validation

Smaug automatically validates all parsed spending reports before storing them.
This catches common parsing failures that would otherwise corrupt data silently.

### Validation checks

| Check | Severity | Description |
|---|---|---|
| Invalid date | error | Year or month is zero or out of range |
| Unknown project | error | Project ID could not be determined |
| Unknown period | error | Period string could not be parsed |
| Negative spending | warning | Total spent is negative |
| Total mismatch | warning | `spent + committed ≠ spent_and_committed` |
| Category sum mismatch | warning | Category totals don't approximate `total_spent` |
| All zeros | warning | File parsed but all spending totals are zero |
| Non-monotonic | warning | Cumulative `total_spent` decreased from prior report |

**Error** findings cause the report to be **rejected** (not stored).
**Warning** findings are logged but the report is still stored.

### Viewing validation results

```bash
# Check for missing report months across all projects
smaug gaps
```

### Monotonicity checking

Since spending reports contain cumulative totals, the `total_spent` value
should never decrease between consecutive months. If it does, smaug flags
a `NON_MONOTONIC` warning, which may indicate:

- A report was parsed incorrectly
- A refund or adjustment was posted
- Reports were loaded out of order

---

## Stop-Work Forecasting (`smaug stopwork`)

Projects forward spending based on current personnel assignments to predict
when funding will be exhausted.

```bash
# Basic forecast using budget or report ceiling
smaug stopwork QUASAR

# Override the funding ceiling
smaug stopwork QUASAR --ceiling 450000
```

### Scenarios

The stop-work command automatically runs scenario analysis:

**Base scenario** — current personnel at current effort levels.

**No-tuition scenario** — if any grad students have tuition charges,
this scenario shows the forecast without tuition/insurance (useful for
summer months when tuition is not billed).

**Throttle scenario** — reduce all spending by a percentage:

```bash
smaug stopwork QUASAR --scenario throttle --throttle-pct 20
# Shows: what if we reduced all spending by 20%?
```

### Output

The forecast shows month-by-month projections with cumulative spending
and remaining funds. When spending exceeds the ceiling, it marks the
transition month with day-level precision:

```
Projected stop-work: 2027-09  (funds exhausted ~day 15 of 2027-09)
```

---

## Invoice Validation

Smaug can cross-check sponsor invoices against internal spending reports:

```bash
smaug invoice QUASAR
```

This loads invoices from the project's `invoices/` directory and compares
them against internal report data, flagging discrepancies between what
the sponsor was billed and what internal reports show.

---

## Report Gap Detection (`smaug gaps`)

Checks for missing monthly reports across all projects:

```bash
smaug gaps
```

This compares the expected set of monthly reports (from the first report
month through today) against the actual set, listing any gaps.

```
=== Missing Spending Reports ===

QUASAR:
  - August 2025
  - November 2025
NEXUS:
  - October 2025
```
