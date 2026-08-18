# Getting Started with MCP Agents

Smaug includes native support for the **Model Context Protocol (MCP)**, an open standard that enables developers to build secure, bidirectional connections between AI models and local or remote data sources.

By starting the `smaug-mcp` server, any MCP-compliant agent (such as Claude Desktop or Claude Code) can natively interact with your academic grant budgets as schema-validated tools.

> [!NOTE]
> **Who is the MCP setup for?**
> * **Recommended for Non-Dev Usage:** Using the Model Context Protocol is the recommended pathway for users who simply want to query budgets, audit spending, run projections, and manage personnel allocations without modifying Smaug's code. **You do not need to clone the code repository or run the agent from it.**
> * **For Developer & Code-Modifying Agents:** If you plan to customize the tool, write custom parser plugins, or use coding agents to develop features inside the Smaug codebase, you should clone the repo and run your agent from the repository root instead of (or in addition to) using an external MCP server setup.

---

## 1. Installation

Since Smaug is a local git repository and not published to PyPI, you can install the package with `mcp` support using one of the following methods depending on your setup:

### Method A: From a cloned local repository:
```bash
pip install -e ".[mcp]"
# or using uv:
uv pip install -e ".[mcp]"
```

### Method B: Directly from GitHub (no repository clone required):
```bash
pip install "git+https://github.com/noa/smaug.git#egg=smaug[mcp]"
# or using uv:
uv pip install "git+https://github.com/noa/smaug.git#egg=smaug[mcp]"
```

Verify that the MCP server executable is in your path by running:

```bash
smaug-mcp --help
```

---

## 2. Configuration for MCP Clients

### Claude Desktop (macOS)
To connect Claude Desktop to your local Smaug data:

1. Open Claude Desktop's configuration file. On macOS, this is located at:
   `~/Library/Application Support/Claude/claude_desktop_config.json`
2. Add the `smaug` server to the `mcpServers` list:

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

3. Restart Claude Desktop. You will see a small plug icon in the chat box, indicating that the Smaug tools are successfully loaded and available.

---

## 3. Tool Reference Guide

The MCP server exposes the core functionality of the Smaug engine as JSON-schema validated tools. Here is a summary of the key tools available to MCP agents:

| Tool Name | CLI Equivalent | Description |
|:---|:---|:---|
| `smaug_list_projects` | `smaug list` | Lists all projects in the workspace. |
| `smaug_project_state_of_play` | `smaug state-of-play` | Returns comprehensive 360-degree project overview including warnings, spending, personnel, and runway. |
| `smaug_project_status` | `smaug status` | Returns detailed status, metadata, and actuals for a specific project. |
| `smaug_stopwork_forecast` | `smaug stopwork` | Forecasts the date when funding is projected to run out. |
| `smaug_spend_plan` | `smaug spend-plan` | Calculates a monthly spend plan, including hypothetical what-if scenarios (e.g. adding personnel). |
| `smaug_audit` | `smaug audit` | Audits spending report items against contractual effort allocations. |

---

## 4. Best Practices for MCP Agents

If you are developing a custom MCP-based agent or prompting Claude Desktop:
- **Let the Agent Query First**: Start by asking the agent to list the projects to retrieve the correct uppercase project identifiers (e.g. `QUASAR`, `NEXUS`).
- **Encourage Multi-Step Reasoning**: MCP tools allow the agent to run a scenario, inspect the forecast, make a change, and run the forecast again to optimize a spend plan iteratively.
- **Context Injection**: By using MCP tools, the agent only requests specific information as needed, preserving your model's context window and increasing response accuracy.
