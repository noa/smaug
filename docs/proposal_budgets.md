# Proposal Budget Generation

The `smaug proposal` command generates multi-year research proposal budgets
with proper institutional rate calculations, salary escalation, and cost
categorization.

## Basic Usage

### From CLI specifications

Build a proposal budget by specifying personnel and costs directly:

```bash
smaug proposal \
  --pi "Smith=10%" \
  --phd 2 \
  --travel 5000 \
  --compute 8000 \
  --years 3
```

### From an existing project

If you have a project in `manifest.yaml` with personnel already configured,
generate a proposal budget from those assignments:

```bash
smaug proposal QUASAR
```

This reads personnel effort from `personnel_config.yaml` and salaries from
the configuration, producing a budget based on current assignments.

## Personnel Specifications

### PI and named personnel

Use `--pi` and `--person` to specify named individuals with effort:

```bash
# PI at 10% effort (salary resolved from personnel_config.yaml)
--pi "Smith=10%"

# Additional faculty, postdoc, or staff
--person faculty "Jones=5%"
--person postdoc "NewPostdoc=100%"
--person staff "TechWriter=25%"
```

If the name matches someone in `personnel_config.yaml`, their salary is used
automatically. Otherwise, smaug falls back to default salaries by type.

### Generic PhD students

```bash
# Add N PhD students at 100% effort, using stipend from rates.yaml
--phd 2
```

PhD students automatically include:
- Stipend (from `grad_student_costs.stipend` in `rates.yaml`)
- Tuition (from `grad_student_costs.phd_tuition` — typically the 20% departmental supplement)
- Health insurance (from `grad_student_costs.health_dental`)
- Fringe at the `grad_student` rate (typically 0%)

### Masters students

```bash
--masters 1
```

Masters students use:
- Hourly rate × hours/week × 52 weeks (from `masters_hourly` and `masters_hours_per_week`)
- Full tuition (from `grad_student_costs.masters_tuition`)
- Part-time fringe rate

Exclude Masters tuition with `--no-masters-tuition`.

## Non-Personnel Costs

```bash
--travel 5000       # Annual travel budget
--compute 8000      # Annual compute/cloud costs (included in MTDC)
--annotation 3000   # Annual annotation/data costs (included in MTDC)
--equipment 15000   # Equipment — year 1 only, excluded from IDC
--other 2000        # Other direct costs per year
```

## Salary Escalation

By default, salaries increase 3% annually. Override with:

```bash
--escalation 4      # 4% annual salary escalation
--escalation 0      # No escalation
```

## Budget Duration

```bash
--years 3           # Default: 3-year budget
--years 5           # 5-year budget
```

## Output Format

The proposal command generates a detailed table showing:

### Personnel detail (per year)

```
Year 1 Personnel Detail:
  Smith, Jane (PI)     Faculty  10%   $18,000   Fringe: $5,670
  PhD Student #1       PhD     100%   $50,000   Fringe: $0     Tuition: $13,334  Insurance: $4,365
  PhD Student #2       PhD     100%   $50,000   Fringe: $0     Tuition: $13,334  Insurance: $4,365
```

### Annual summary

```
                   Year 1      Year 2      Year 3       Total
  Salary          $118,000    $121,540    $125,186    $364,726
  Fringe            $5,670      $5,840      $6,015     $17,525
  Tuition          $26,668     $26,668     $26,668     $80,004
  Insurance         $8,730      $8,730      $8,730     $26,190
  Travel            $5,000      $5,000      $5,000     $15,000
  Compute           $8,000      $8,000      $8,000     $24,000
  Equipment        $15,000          $0          $0     $15,000
  ─────────────────────────────────────────────────────────────
  Direct Costs    $187,068    $175,778    $179,599    $542,445
  IDC (55%)        $80,185     $82,261     $84,530    $246,976
  ─────────────────────────────────────────────────────────────
  TOTAL           $267,253    $258,039    $264,129    $789,421
```

## IDC Calculation

Indirect costs are calculated on the **Modified Total Direct Cost** (MTDC) base:

**Included in MTDC:** salary, fringe, insurance, travel, compute, annotation, other

**Excluded from MTDC:** tuition, equipment

This follows the standard federal F&A cost methodology.

## Rate Resolution

All rates are loaded from `rates.yaml` in the data directory:

| Rate | Source | Used for |
|---|---|---|
| IDC rate | `idc_rate` | Indirect cost calculation |
| Fringe rates | `fringe_rates.<type>` | Per-person fringe benefits |
| PhD stipend | `grad_student_costs.stipend` | Default PhD salary |
| PhD tuition | `grad_student_costs.phd_tuition` | Annual tuition per PhD |
| Masters tuition | `grad_student_costs.masters_tuition` | Annual tuition per Masters |
| Health insurance | `grad_student_costs.health_dental` | Annual insurance per student |
| Masters hourly | `masters_hourly` | Masters student salary basis |

## Tips

- Run `smaug proposal QUASAR` to verify that your existing project personnel
  produce a sensible budget before submitting a renewal proposal.
- Use `--escalation 0` for fixed-price contracts where salary escalation
  is not allowed.
- The equipment budget is placed entirely in Year 1. For multi-year equipment
  purchases, use `--other` and note the allocation in your budget justification.
