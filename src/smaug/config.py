"""
Configuration and data directory resolution.

Resolves the data directory through a priority chain:
    1. CLI ``--data-dir`` argument
    2. ``SMAUG_DATA_DIR`` environment variable
    3. ``~/.smaug/`` in the user's home directory
    4. Error with a helpful message
"""

import os
from pathlib import Path

# Default names for configuration files
RATES_FILE = "rates.yaml"
MANIFEST_FILE = "manifest.yaml"
PERSONNEL_CONFIG_FILE = "personnel_config.yaml"
TRAVEL_CONFIG_FILE = "travel_config.yaml"
PURCHASES_CONFIG_FILE = "purchases_config.yaml"
ALIASES_FILE = "aliases.yaml"

ENV_VAR = "SMAUG_DATA_DIR"


def resolve_data_dir(cli_value: str | None = None) -> Path:
    """
    Resolve the data directory from the priority chain.

    Args:
        cli_value: Value passed via ``--data-dir`` CLI argument. Takes
            highest priority when not *None*.

    Returns:
        Resolved absolute path to the data directory.

    Raises:
        FileNotFoundError: If no valid data directory can be found.
    """
    import sys

    is_init = "init" in sys.argv

    # 1. CLI argument
    if cli_value:
        path = Path(cli_value)
        if path.exists() or is_init:
            return path.resolve()
        # If it looks like an old default but doesn't exist,
        # give a helpful migration hint
        if cli_value in ("jhu", "data"):
            raise FileNotFoundError(
                f"Data directory '{cli_value}' not found.\n"
                "  Hint: smaug now defaults to '~/.smaug/'.\n"
                "  Run 'smaug init' to create a new data directory, or\n"
                "  set --data-dir to your existing data location."
            )
        raise FileNotFoundError(f"Data directory not found: {cli_value}")

    # 2. Environment variable
    env_dir = os.environ.get(ENV_VAR)
    if env_dir:
        path = Path(env_dir)
        if path.exists() or is_init:
            return path.resolve()
        raise FileNotFoundError(f"${ENV_VAR} is set to '{env_dir}' but directory does not exist.")

    # 3. ~/.smaug/ in user's home directory
    home_data = Path.home() / ".smaug"
    if home_data.exists() or is_init:
        return home_data.resolve()

    raise FileNotFoundError(
        "No data directory found. Searched:\n"
        "  1. --data-dir argument\n"
        f"  2. ${ENV_VAR} environment variable\n"
        "  3. ~/.smaug/ in home directory\n\n"
        "Run 'smaug init' to create a new data directory."
    )


def get_rates_path(data_dir: Path) -> Path:
    """Return the path to the institutional rates file."""
    # Support both new and legacy naming
    new_path = data_dir / RATES_FILE
    legacy_path = data_dir / "jhu_rates.yaml"

    if new_path.exists():
        return new_path
    if legacy_path.exists():
        return legacy_path
    return new_path  # Default to new name even if missing


def get_projects_dir(data_dir: Path) -> Path:
    """Return the path to the projects directory."""
    return data_dir / "projects"


def get_reports_dir(data_dir: Path) -> Path:
    """Return the path to the reports directory."""
    return data_dir / "reports"
