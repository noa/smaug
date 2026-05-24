# Getting Started with Claude Code

[Claude Code](https://docs.anthropic.com/en/docs/agents-and-tools/claude-code) is an agentic command-line tool designed by Anthropic that can edit code, run tests, and execute CLI commands. This guide explains how to configure and run Claude Code with the Smaug codebase and runtime tools.

---

## 1. Project-wide Instructions via `CLAUDE.md`

When Claude Code starts a session in the Smaug repository, it automatically reads the project-level `CLAUDE.md` file in the root.

This file teaches Claude:
- How to run tests (`uv run pytest`)
- How to run lint checks and formatters (`uv run ruff check` and `uv run ruff format`)
- Core coding guidelines, naming standards (uppercase projects, "Last, First" personnel), and local file structures.

You do not need to do anything to activate this; Claude Code loads it automatically.

---

## 2. Setting Up the Smaug MCP Server for Claude Code

Claude Code can use Model Context Protocol (MCP) servers to gain advanced, structured tool capabilities. Connecting Claude Code to the `smaug-mcp` server allows Claude to query, audit, and forecast budgets natively via schema-validated tools rather than parsing raw CLI printouts.

### step-by-step MCP Configuration

1. **Install Smaug with MCP support** in your environment:
   ```bash
   pip install "smaug[mcp]"
   # or using uv:
   uv pip install "smaug[mcp]"
   ```

2. **Locate Claude Code's configuration file**:
   Claude Code loads its global MCP configurations from `~/.claude/config.json`.

3. **Edit `~/.claude/config.json`**:
   Add the `smaug-mcp` server definition to the `mcpServers` object:

   ```json
   {
     "mcpServers": {
       "smaug": {
         "command": "smaug-mcp"
       }
     }
   }
   ```

   > [!TIP]
   > Smaug automatically reads configurations from the default location `~/.smaug`. To point to a custom directory, you can optionally set the `SMAUG_DATA_DIR` environment variable:
   > ```json
   > {
   >   "mcpServers": {
   >     "smaug": {
   >       "command": "smaug-mcp",
   >       "env": {
   >         "SMAUG_DATA_DIR": "/absolute/path/to/custom/data"
   >       }
   >     }
   >   }
   > }
   > ```

4. **Restart Claude Code**:
   When Claude Code boots up, it will connect to the MCP server. You can verify that the Smaug tools are loaded by running:
   ```bash
   # inside Claude Code chat
   /tools
   ```
   You should see tools like `smaug_list_projects`, `smaug_stopwork_forecast`, `smaug_spend_plan`, etc.

---

## 3. Recommended Workflow Patterns

You can prompt Claude Code directly from your terminal with one-off questions:

```bash
# Query budget information
claude "Check the remaining budget and stopwork date for QUASAR"

# Make configuration changes
claude "Add a new graduate student named John Doe to project QUASAR at 50% effort"

# Run codebase tasks
claude "Run the test suite and fix any failing tests in the parser logic"
```

When pair-programming inside the interactive Claude Code chat:

### Code Maintenance and Debugging
Claude Code can be used to debug issues and update Smaug's Python logic:
- Ask Claude Code: *"Run the test suite and fix any failing tests in the parser logic."*
- Claude will automatically execute `uv run pytest`, capture the error, inspect files like `src/smaug/parsers/jhu_sponsored.py`, perform the fix, and re-run tests until green.

### Scenario Projections and Analysis
You can ask Claude Code to solve complex, multi-step financial questions directly:
- Ask Claude Code: *"Check if we have enough budget in QUASAR to increase Martinez's effort to 100% through the end of the year."*
- Claude will use the MCP tools or CLI commands to:
  1. Retrieve Martinez's current allocation on all projects.
  2. Query `smaug spend-plan QUASAR --if "Martinez=100%"`.
  3. Compare the projected total with the project's contractual ceiling.
  4. Write a detailed summary of the findings.
