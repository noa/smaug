# Gemini & Antigravity Setup

This guide covers running Smaug with Google Gemini CLI and Antigravity.

---

## 1. Gemini CLI

### Prerequisites

Gemini CLI can interact with Smaug in two ways. Choose whichever fits your setup:

**Option A — MCP Server (recommended):**
Install Smaug with MCP support and register the server with Gemini:

```bash
pip install "smaug[mcp]"
gemini mcp add smaug -- smaug-mcp
```

This registers `smaug-mcp` as a tool provider. Gemini discovers all Smaug tools (list projects, forecast stop-work dates, run spend plans, etc.) automatically via their schema definitions. No further context is needed.

**Option B — Shell execution with AGENTS.md context:**
Install `smaug` so it is available on your PATH, then run `gemini` from the Smaug repository root. Gemini reads `AGENTS.md` at startup and learns how to invoke `smaug` CLI commands via its built-in shell execution tool.

> [!TIP]
> Both options require that `smaug` is installed (`pip install smaug` or `uv tool install smaug`). Option A works from any directory. Option B requires running from the repository root so Gemini can read `AGENTS.md`.

### CLI Examples

Once either option is configured, you can ask questions directly:

```bash
# Check on project spending
gemini -p "Check on spending for QUASAR"

# Forecast a stop-work date
gemini -p "When will NEXUS run out of money?"

# Scenario planning
gemini -p "What happens if we add a PhD student to QUASAR at 100% effort?"
```

### MCP Server Configuration (manual)

If you prefer to configure the MCP server manually instead of using `gemini mcp add`, add it to `.gemini/settings.json`:

```json
{
  "mcpServers": {
    "smaug": {
      "command": "smaug-mcp"
    }
  }
}
```

Verify the connection with the `/mcp` command inside the Gemini CLI.

---

## 2. Google Antigravity (2.0 Release)

Google **Antigravity 2.0** uses Workspace rules and customizations to guide coding style, workflows, and context adherence.

### Workspace Rules Setup

You can define rules that Antigravity automatically detects in this repository:

1. **Rule File Location**: Save project-level rules in the `.agents/rules/` directory at the root of the repository.
2. **Rule Selection**: In the Antigravity agent panel inside your editor:
   - Open the **Customizations panel** (via the `...` menu at the top of the agent panel).
   - Go to the **Rules** tab.
   - Click **+ Workspace** to create or view workspace-level rules.
3. **Activation**: Rules can be configured to be **Always On**, **Model Decision** (the agent decides if it applies based on natural language description), or **Glob** (applied to specific file types, e.g., `*.py` or `*.yaml`).

### Recommended Workspace Rule File

We provide a pre-configured workspace rule at `.agents/rules/smaug-rules.md`. This tells Antigravity about the codebase layout, formatting standards, and Smaug domain conventions automatically.
