"""
Command-line interface for the budget tracking framework.

Usage:
    python -m smaug.cli list
    python -m smaug.cli status <project>
    python -m smaug.cli report <project>
    python -m smaug.cli personnel [<name>]
    python -m smaug.cli project <project> [--months N] [--to YYYY-MM]
    python -m smaug.cli dump <project>
"""

from ._parser import main

__all__ = ["main"]
