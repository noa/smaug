# Anonymization & Context Privacy

This document describes Smaug's **Anonymization Mode**—a feature designed to protect confidential salary information when sharing budget reviews, projections, or audits with colleagues, or when exposing Smaug tools to AI agents.

---

## Overview

Academic budget tracking requires handling highly sensitive, individual-level salary data. When sharing budget sheets or integrating with AI models, leaking the exact compensation of faculty, postdocs, and graduate students is a major concern.

Smaug addresses this by decoupling the **storage layer** from the **presentation layer**:
1. **Raw Database**: The backend Project Store and reports database keep real names to ensure accurate matching, tracking, and financial reconciliation.
2. **Display Translation**: Real names are dynamically translated to stable, role-based anonymized identifiers *only* when rendering output in CLI commands, API JSON, or MCP contexts.

---

## How It Works

### 1. Stable, Role-Based Mapping
When anonymization is active, Smaug gathers all unique employee names from actual spending reports and institutional configurations, sorts them alphabetically, and maps them to a role-based display string:
* **Faculty** $\rightarrow$ `Faculty 1`, `Faculty 2`, ...
* **Postdoctoral Researchers** $\rightarrow$ `Postdoc 1`, `Postdoc 2`, ...
* **Graduate Students (PhDs)** $\rightarrow$ `PhD 1`, `PhD 2`, ...
* **Staff Members** $\rightarrow$ `Staff 1`, `Staff 2`, ...
* **Unknown / Fallback** $\rightarrow$ `Person 1`, `Person 2`, ...

Sorting names alphabetically guarantees that **the mapping remains stable and consistent** across different commands within a run.

### 2. Bidirectional Name Resolution
Even with anonymization active, administrative operations remain fully functional. If you are reviewing an anonymized output and need to query details about a specific person (e.g. `PhD 2`), Smaug's bidirectional resolver allows you to use the anonymized identifier in queries:
```bash
smaug personnel "PhD 2" --anonymize
```
The query processor transparently resolves `"PhD 2"` to their real name in the backend database, performs the requested audit or projection, and displays the final outputs under the anonymized label.

The resolver is case-insensitive and space-insensitive (e.g., `phd 2`, `PhD2`, or `phd2` will all resolve to the same person).

---

## Activating Anonymization

Anonymization can be configured globally or per-command across three distinct channels:

### 1. CLI Commands (Opt-In for Humans)
To use anonymization during manual CLI operations, append the `--anonymize` flag to any read or write command:
```bash
# View aggregate personnel summary anonymized
smaug personnel --anonymize

# Run spending projection anonymized
smaug project QUASAR --months 12 --anonymize

# Audit spending anonymized
smaug audit QUASAR --anonymize
```

### 2. Global Environment Variable
If you want anonymization active for all operations without typing the flag every time, set the `SMAUG_ANONYMIZE` environment variable:
```bash
export SMAUG_ANONYMIZE=1
```
To disable anonymization explicitly (e.g., to override a configured environment variable or script defaults), set it to `0`:
```bash
export SMAUG_ANONYMIZE=0
```

### 3. AI Agent Privacy via MCP Server (Active by Default)
AI agents integrating via the Model Context Protocol (MCP) will automatically trigger anonymized tools. This prevents private name and salary data from entering the AI model's context window.

If a human user explicitly needs the raw name data exposed through MCP, they can bypass the default safety by starting the server with the `--no-anonymize` or `--unmask-names` flag:
```bash
smaug-mcp --no-anonymize
```

---

## Resolving Identities (Authorized Admins Only)

If an authorized user (such as the PI) needs to identify the real person behind an anonymized handle (e.g., `PhD 2` or `Faculty 1`):

### Option A: Query in Raw Mode
Omitting the `--anonymize` flag (and ensuring `SMAUG_ANONYMIZE` is not set to `1`) runs Smaug in standard Raw Mode, immediately exposing all real names and compensations:
```bash
smaug personnel
```

### Option B: Index Parity
Because both raw and anonymized views sort names alphabetically, the list indices (`#`) align exactly:
1. Run `smaug personnel --anonymize` to locate the row number of interest (e.g., row `#3`).
2. Run `smaug personnel` (in raw mode).
3. The name under row `#3` is the real identity of that individual.
