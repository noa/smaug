"""Setup CLI commands: MCP server registration and environment status."""

import json
import shutil
import subprocess
import sys
from pathlib import Path

from ..store import ProjectStore


def _get_repo_root() -> Path:
    """Return the smaug repository root (directory containing pyproject.toml)."""
    return Path(__file__).resolve().parent.parent.parent.parent


def _find_mcp_json(repo_root: Path) -> dict | None:
    """Load .mcp.json from the repo root if it exists and contains smaug."""
    mcp_json_path = repo_root / ".mcp.json"
    if not mcp_json_path.exists():
        return None
    try:
        with open(mcp_json_path, encoding="utf-8") as f:
            data: dict = json.load(f)
            return data
    except (json.JSONDecodeError, OSError):
        return None


def _mcp_json_has_smaug(mcp_data: dict | None) -> bool:
    """Check whether .mcp.json already has a smaug MCP server entry."""
    if mcp_data is None:
        return False
    servers = mcp_data.get("mcpServers", {})
    return "smaug" in servers


def _get_desktop_config_path() -> Path:
    """Return the Claude Desktop config file path (macOS)."""
    return Path.home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"


def _build_mcp_command(repo_root: Path) -> list[str] | None:
    """Build the MCP server command args, preferring uv, falling back to direct executable."""
    uv_path = shutil.which("uv")
    if uv_path:
        return ["uv", "run", "--directory", str(repo_root), "smaug-mcp"]

    print("  Note: 'uv' not found on PATH, falling back to direct executable.")
    smaug_mcp_path = shutil.which("smaug-mcp")
    if not smaug_mcp_path:
        venv_bin = Path(sys.executable).parent
        candidate = venv_bin / "smaug-mcp"
        if candidate.exists():
            smaug_mcp_path = str(candidate)
        else:
            print("  Error: Could not locate 'smaug-mcp' executable.")
            print("  Make sure smaug is installed with MCP extras:")
            print(f'    pip install -e "{repo_root}[mcp]"')
            return None

    return [smaug_mcp_path]


def _setup_mcp_code(repo_root: Path, scope: str) -> None:
    """Register the smaug MCP server with Claude Code."""
    claude_path = shutil.which("claude")
    if not claude_path:
        print("  ✗ Claude Code: 'claude' CLI not found on PATH — skipped.")
        print("    Install: https://docs.anthropic.com/en/docs/claude-code/overview")
        return

    mcp_cmd = _build_mcp_command(repo_root)
    if mcp_cmd is None:
        return

    cmd = ["claude", "mcp", "add", "--scope", scope, "smaug", "--", *mcp_cmd]

    # Check for existing .mcp.json configuration
    mcp_data = _find_mcp_json(repo_root)
    if _mcp_json_has_smaug(mcp_data):
        print("  Note: .mcp.json already contains a 'smaug' entry — it will be updated.")

    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            print(f"  ✓ Claude Code: registered (scope: {scope})")
        else:
            print(f"  ✗ Claude Code: claude mcp add failed (exit {result.returncode})")
            if result.stderr.strip():
                print(f"    {result.stderr.strip()}")
    except OSError as e:
        print(f"  ✗ Claude Code: {e}")


def _setup_mcp_desktop(repo_root: Path) -> None:
    """Register the smaug MCP server with Claude Desktop."""
    config_path = _get_desktop_config_path()

    if not config_path.parent.exists():
        print("  ✗ Claude Desktop: config directory not found — is Claude Desktop installed?")
        print(f"    Expected: {config_path.parent}")
        return

    mcp_cmd = _build_mcp_command(repo_root)
    if mcp_cmd is None:
        return

    server_entry = {
        "command": mcp_cmd[0],
        "args": mcp_cmd[1:],
    }

    try:
        if config_path.exists():
            with open(config_path, encoding="utf-8") as f:
                config = json.load(f)
        else:
            config = {}

        config.setdefault("mcpServers", {})
        already_exists = "smaug" in config["mcpServers"]
        config["mcpServers"]["smaug"] = server_entry

        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)

        if already_exists:
            print("  ✓ Claude Desktop: updated existing smaug entry")
        else:
            print("  ✓ Claude Desktop: registered")
        print("    Restart Claude Desktop to activate.")
    except (json.JSONDecodeError, OSError) as e:
        print(f"  ✗ Claude Desktop: failed to update config — {e}")
        print(f"    Config path: {config_path}")


def _setup_mcp(args) -> None:
    """Register the smaug MCP server with Claude Code and/or Claude Desktop."""
    scope = getattr(args, "scope", "project")
    target = getattr(args, "target", "all")

    # Determine repo root
    repo_root = _get_repo_root()
    pyproject = repo_root / "pyproject.toml"
    if not pyproject.exists():
        print(f"Error: Could not find pyproject.toml at expected location: {pyproject}")
        print("Is smaug installed from the repository?")
        return

    print(f"Registering smaug MCP server (repo: {repo_root})...\n")

    if target in ("all", "code"):
        _setup_mcp_code(repo_root, scope)
    if target in ("all", "desktop"):
        _setup_mcp_desktop(repo_root)

    print()


def _setup_show(args) -> None:
    """Show current smaug setup and environment status."""

    print("\n=== Smaug Setup Status ===\n")

    # 1. Check editable install
    try:
        import smaug

        smaug_location = Path(smaug.__file__).resolve().parent
        repo_root = _get_repo_root()
        # If the installed smaug package lives inside the repo tree, it's editable
        try:
            smaug_location.relative_to(repo_root)
            is_editable = True
        except ValueError:
            is_editable = False

        if is_editable:
            print(f"  ✓ smaug is installed in editable mode ({repo_root})")
        else:
            print(f"  • smaug is installed (location: {smaug_location})")
    except ImportError:
        print("  ✗ smaug is not installed")

    # 2. Check MCP dependencies
    try:
        import mcp  # noqa: F401

        print("  ✓ MCP dependencies are installed")
    except ImportError:
        print("  ✗ MCP dependencies not installed")
        print("    Install with: pip install -e '.[mcp]'")

    # 3. Check data directory
    data_dir = Path(getattr(args, "data_dir", "~/.smaug")).expanduser()
    if data_dir.exists():
        print(f"  ✓ Data directory exists: {data_dir}")
    else:
        print(f"  ✗ Data directory not found: {data_dir}")
        print("    Run 'smaug init' to create it.")

    # 4. Check Claude Code (.mcp.json in repo root)
    repo_root = _get_repo_root()
    mcp_data = _find_mcp_json(repo_root)
    mcp_json_path = repo_root / ".mcp.json"

    if mcp_data is not None:
        if _mcp_json_has_smaug(mcp_data):
            print(f"  ✓ Claude Code: smaug registered ({mcp_json_path})")
        else:
            print("  • Claude Code: .mcp.json exists but has no smaug entry")
            print("    Run 'smaug setup mcp --target code' to register.")
    else:
        print(f"  ✗ Claude Code: .mcp.json not found at {mcp_json_path}")
        print("    Run 'smaug setup mcp --target code' to register.")

    # 5. Check Claude Desktop config
    desktop_config_path = _get_desktop_config_path()
    if desktop_config_path.exists():
        try:
            with open(desktop_config_path, encoding="utf-8") as f:
                desktop_config = json.load(f)
            if "smaug" in desktop_config.get("mcpServers", {}):
                print("  ✓ Claude Desktop: smaug registered")
            else:
                print("  ✗ Claude Desktop: no smaug entry in config")
                print("    Run 'smaug setup mcp --target desktop' to register.")
        except (json.JSONDecodeError, OSError):
            print("  • Claude Desktop: config file exists but could not be read")
    else:
        print("  • Claude Desktop: not installed (config not found)")

    # 6. Check CLI tools
    claude_path = shutil.which("claude")
    if claude_path:
        print(f"  ✓ claude CLI found: {claude_path}")
    else:
        print("  ✗ claude CLI not found on PATH")

    uv_path = shutil.which("uv")
    if uv_path:
        print(f"  ✓ uv found: {uv_path}")
    else:
        print("  • uv not found on PATH (optional, used for MCP registration)")

    print()


def cmd_setup(store: ProjectStore, args) -> None:
    """Manage smaug environment setup and integrations."""

    action = getattr(args, "action", None)

    if action == "mcp":
        _setup_mcp(args)
    elif action == "show":
        _setup_show(args)
    else:
        print("Usage: smaug setup {mcp,show}")
        print("  mcp   Register the smaug MCP server with Claude Code")
        print("  show  Show current setup status")
