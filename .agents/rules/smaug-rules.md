# Smaug Codebase Conventions

This rule provides structural context and constraints for modifying the Smaug codebase.

## Application Scope
- **Activation Mode**: Model Decision or Glob-based
- **Glob Pattern**: `src/**/*.py`, `tests/**/*.py`, `**/*.yaml`

## Code Style & Formatting
- **Python Version**: Target Python 3.11+. Use modern type hints and syntax where possible.
- **Formatter**: Code must adhere to Ruff rules (100-character line limit, double quotes for strings, 4-space indentation).
- **Type Checking**: Enforced by mypy (`check_untyped_defs = true`). Write explicit types for all public interfaces.

## Smaug Conventions & Safety
- **Naming Standards**:
  - Project identifiers are short uppercase names (e.g., `QUASAR`, `NEXUS`, `ATLAS`).
  - Personnel names use `"Last, First"` format (e.g., `"Smith, Jane"`). Always use fuzzy identity resolution helpers when matching personnel.
- **Write Operations**: All database writes modify local YAML configuration files. Do not invoke `smaug clear` unless explicitly requested.
