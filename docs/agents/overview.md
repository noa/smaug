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
