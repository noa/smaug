# Personnel Aliases and Identity Resolution

Smaug provides a flexible identity resolution system so you don't need to
remember or type full `"Last, First"` names. Every command that accepts a
person name supports **numeric indices**, **aliases**, and **fuzzy matching**.

## Resolution Order

When you provide a name argument, smaug resolves it in this order:

1. **Numeric index** — If the input is a number, it's treated as a 1-based
   index into the personnel list (as shown by `smaug personnel`).
2. **Alias lookup** — Case-insensitive match against entries in `aliases.yaml`.
3. **Exact match** — Direct string comparison against known personnel names.
4. **Fuzzy match** — Case-insensitive substring search. If exactly one person
   matches, it's used. If multiple match, smaug lists the ambiguous matches.

## Examples

```bash
# All of these resolve to "Chen, Wei" if configured correctly:
smaug personnel "Chen, Wei"     # Exact match
smaug personnel chen            # Fuzzy match (substring)
smaug personnel wei             # Alias (if configured)
smaug personnel 2               # Index (if Chen is #2 in the list)
```

## Managing Aliases

Aliases are stored in `projects/aliases.yaml` and map short nicknames to
the canonical `"Last, First"` name from `personnel_config.yaml`.

### List aliases

```bash
smaug alias list
```

```
=== Personnel Aliases ===

Alias                Resolves To
------------------------------------------------------------
jane                 Smith, Jane
wei                  Chen, Wei
sofia                Martinez, Sofia
```

### Add an alias

```bash
smaug alias add wei "Chen, Wei"

# The target name supports fuzzy matching too:
smaug alias add sofia martinez     # Resolves "martinez" → "Martinez, Sofia"
```

If the alias already exists, it is updated:

```
Updating alias 'wei': Chen, Wei -> Chen, Wei
```

### Remove an alias

```bash
smaug alias remove wei
# Output: Removed alias: 'wei' (was -> 'Chen, Wei')
```

## Where Aliases Work

Aliases are supported universally across **all** personnel-related commands:

| Command | Example |
|---|---|
| `smaug personnel` | `smaug personnel wei` |
| `smaug set-effort` | `smaug set-effort wei QUASAR 50%` |
| `smaug set-salary` | `smaug set-salary wei 75000` |
| `smaug set-end` | `smaug set-end wei QUASAR 2027-06` |
| `smaug set-departure` | `smaug set-departure wei 2028-01` |
| `smaug spend-plan --if` | `smaug spend-plan QUASAR --if "wei=50%"` |
| `smaug audit` | Fuzzy matching in audit output |

## The `aliases.yaml` File

```yaml
aliases:
  jane: "Smith, Jane"
  wei: "Chen, Wei"
  raj: "Patel, Raj"
  alex: "Johnson, Alex"
```

- Keys are case-insensitive during lookup (but stored as-is).
- Values must match a name in `personnel_config.yaml` exactly.
- The file is created automatically when you run `smaug alias add`.

## Index-Based Access

The `smaug personnel` command numbers each person. You can use these numbers
in any command:

```bash
$ smaug personnel
=== All Personnel ===

  # Name                   Salary  Current Effort     Spent       Ends ...
  1 Smith, Jane              $180k            30%    $12,000   ongoing ...
  2 Chen, Wei                 $72k           100%    $45,000   ongoing ...
  3 Martinez, Sofia             $50k           100%    $18,000   ongoing ...

# Use the index directly:
$ smaug set-effort 2 QUASAR 50%
# Resolves to: Chen, Wei
```

> **Note:** Indices are based on the current personnel list ordering and may
> change if people are added or removed. Aliases are more stable for scripts.

## Fuzzy Matching Details

Fuzzy matching is a **case-insensitive substring search**:

- `smith` matches `"Smith, Jane"` ✓
- `jan` matches `"Smith, Jane"` ✓
- `martinez` matches `"Martinez, Sofia"` ✓
- `a` matches multiple people → smaug reports the ambiguity:

```
Multiple personnel matching 'a':
  - Martinez, Sofia
  - Patel, Raj
  - Johnson, Alex
```

When using `--if` hypotheticals in `spend-plan`, the same fuzzy matching applies:

```bash
smaug spend-plan QUASAR --if "chen=50%"
# Resolves "chen" → "Chen, Wei", sets effort to 50%
```
