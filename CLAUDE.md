# Claude Code Development Guide

This file defines the development commands and style rules for working on the Smaug codebase.

## Build and Test Commands
- **Run Tests**: `uv run pytest` or `pytest`
- **Run Specific Test**: `uv run pytest tests/test_filename.py -k test_name`
- **Linting & Formatting Check**: `uv run ruff check` and `uv run ruff format --check`
- **Auto-formatting**: `uv run ruff format` and `uv run ruff check --fix`
- **Type Checking**: `uv run mypy src`

## Style and Code Standards
- **Python Version**: Target Python 3.11+.
- **Formatting**: Handled by Ruff (100 char line limit, double quotes, 4-space indent).
- **Type Annotations**: Enforced by mypy (`check_untyped_defs = true`).

## Smaug CLI & Runtime Instructions
For instructions on how to use and execute the Smaug CLI tools, budget forecasting scenarios, and project configurations, please refer directly to the runtime manual:
- See [AGENTS.md](file:///Users/nandrews/smaug-public/AGENTS.md)
