# Agentic Integration Overview

Smaug provides three communication channels for AI agents to interact with grant data:

1. **Model Context Protocol (MCP)**: A `smaug-mcp` server allowing LLM clients that support MCP to call Smaug capabilities as tools.
2. **Command Line Interface (CLI)**: A CLI with detailed flags and machine-readable `smaug dump <PROJECT>` outputs for shell-based agents.
3. **Python API (`smaug.api.SmaugAPI`)**: Returns structured dictionary outputs for custom script-based pipelines.

---

## The Smaug Core Architecture & Data Layout

AI agents must understand where Smaug stores state to run effectively. Smaug is a **local-first** application that backs its configuration in a data directory (by default `~/.smaug` or set via the `SMAUG_DATA_DIR` environment variable).

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

### Core Conventions for Agents

- **Project Identifiers**: Always uppercase (e.g. `QUASAR`, `ATLAS`).
- **Personnel Names**: formatted as `"Last, First"` (e.g. `"Smith, Jane"`). Smaug includes a fuzzy identity resolution utility (`resolve_personnel_name`) which supports common nicknames and aliases.
- **Spending Reports**: Reports imported into Smaug are treated as cumulative; the latest report contains the total expenditures to date.
- **Write Safety & Undo**: All write operations (e.g., changing effort, adding personnel) modify the YAML configuration files in `~/.smaug/`. When configured in a Git-backed workspace, changes can be audited via `smaug history` and reversed using `smaug undo`.

---

## Recommended Execution Contexts: Repository vs. MCP Tool

Depending on your role and objectives, you should choose one of two distinct execution contexts:

### 1. Cloned Repository Setup (For Developers & Coding Agents)
If you are a developer, plan to customize the Smaug Python package, make bug fixes, or intend to use coding agents (such as Claude Code or Gemini/Antigravity) to perform active code edits and run pytest suites, you should **run the agent from the root of a cloned git repository**.
* **Why:** This avoids MCP configuration, runs automatically in editable mode (`pip install -e .`), and makes it easy to submit pull requests or test code changes instantly.
* **Best Fit For:** Technically savvy users, developers, and code-modifying agent sessions.

### 2. Standalone MCP Server Setup (For End-Users & Pure Query Agents)
If you simply want to utilize Smaug to track budgets, audit spending, project stop-work dates, and run what-if scenarios without any intention of altering the source code, you should **use the MCP server externally**.
* **Why:** You do not need to clone the codebase. Simply install Smaug directly from GitHub (`pip install "git+https://github.com/noa/smaug.git#egg=smaug[mcp]"`) and configure the `smaug-mcp` executable inside your agent's config (e.g., Claude Desktop or Gemini). The agent queries and operates on your local `~/.smaug` data seamlessly.
* **Best Fit For:** Lab managers, PIs, and end-user workflow agents.

---

## Choosing the Best Integration Channel

Depending on the agent's architecture, choose the corresponding channel:

| Agent Architecture | Recommended Interface | Getting Started Guide |
|:---|:---|:---|
| **Claude Code** | Native MCP or CLI rules | [Claude Code Guide](./claude_code.md) |
| **Gemini & Antigravity** | Workspace Rules / CLI | [Gemini & Antigravity Guide](./gemini.md) |
| **Codex / API-Driven Shell Agents** | CLI & `smaug dump` | [Codex / Shell Agents Guide](./codex_agents.md) |
| **Any MCP-Compliant Agent** | `smaug-mcp` server | [MCP Onboarding Guide](./mcp_agents.md) |

---

## Quick Diagnostics

For agents troubleshooting their setup, run the following diagnostic commands:

```bash
# Check if CLI is in path and works
smaug --help

# Verify the current active data directory
smaug health

# Test tool-level data loading
smaug list --all
```
