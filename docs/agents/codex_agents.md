# Codex & Custom API-Driven Agents

This guide covers integrating Smaug with custom OpenAI Codex, GPT, and API-driven agents. Rather than dumping the entire project state into the prompt upfront or writing custom shell-execution loops, custom agents should interact with Smaug using dynamic tool calling.

> [!NOTE]
> **Choosing Your Development Approach:**
> * **Developing / Customizing Smaug:** If you are building tools or custom wrappers that modify Smaug's internals or require running test suites, you should run your scripting and LLM agent sessions directly within the root of the cloned Smaug repository.
> * **Standard Tool API Usage:** If you are building a pure budget forecasting dashboard or assistant that only queries existing data, you do not need to clone the repository. You can simply install the package directly from GitHub (`pip install "git+https://github.com/noa/smaug.git#egg=smaug[mcp]"`) and run `smaug-mcp` or import the Python API (`smaug.api.SmaugAPI`) inside your own separate application workspace.

---

## 1. Designing Tool-Calling Agents

Language models perform best when they select and call tools dynamically. Exposing Smaug as a toolset avoids token waste, maintains clean developer loops, and allows the agent to execute specific queries on demand.

### Option A — MCP Tool Integration (Recommended)
Register the Smaug MCP server with your custom agent framework. This exposes all Smaug capabilities as structured tools with predefined schemas (parameters, descriptions, types).

Configure your agent framework to run the server:
```bash
smaug-mcp
```

The agent discovers and executes the appropriate tools (e.g. `list_projects`, `stopwork_forecast`) dynamically as it resolves user queries.

### Option B — Function Calling (Schema Definition)
If you are calling LLM APIs directly, define tool schemas for Smaug commands.

Below is an example of defining a tool schema for the stop-work forecast:

```json
{
  "type": "function",
  "function": {
    "name": "get_stopwork_forecast",
    "description": "Calculate the monthly burn rate and stop-work date forecast for a project.",
    "parameters": {
      "type": "object",
      "properties": {
        "project": {
          "type": "string",
          "description": "The uppercase short name of the project (e.g., QUASAR)."
        }
      },
      "required": ["project"]
    }
  }
}
```

When the agent decides to call `get_stopwork_forecast`, your application executes the corresponding Smaug command or Python API call and returns the structured result.

---

## 2. Dynamic Python API Toolset

For custom Python scripts or orchestrators, use the `SmaugAPI` to wrap specific methods as tools. This avoids loading and parsing the entire workspace context in a single large dictionary.

```python
from smaug.api import SmaugAPI

# Initialize the API
api = SmaugAPI()

# Define targeted tool functions for your LLM agent:

def tool_list_projects() -> list:
    """List all active academic projects with basic status and budget."""
    return api.list_projects(status="active")

def tool_project_forecast(project: str) -> dict:
    """Get the current stop-work forecast, including burn rate and projected end date."""
    return api.stopwork_forecast(project)

def tool_travel_expenses(project: str) -> list:
    """Get list of travels and expenses for a project."""
    return api.get_travel_expenses(project)
```

By providing these targeted functions as tools, the LLM agent only queries the specific data it needs, resulting in faster execution, lower token usage, and less noise in the context window.
