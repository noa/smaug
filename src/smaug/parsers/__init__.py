"""
Parser plugin system for institution-specific report formats.

Smaug discovers parsers via Python entry points registered under the
``smaug.parsers`` group.  Each parser implements one of the abstract
base classes below and advertises its ability to handle specific file
formats via the ``can_parse`` method.

To add support for a new institution:

1. Create a module (e.g., ``my_parsers/mit_reports.py``) containing a
   class that inherits from :class:`ReportParser` or
   :class:`InvoiceParser`.
2. Register it in your package's ``pyproject.toml``::

       [project.entry-points."smaug.parsers"]
       mit_sponsored = "my_parsers.mit_reports:MITSponsoredParser"

3. Install your package (``pip install .``) and smaug will
   automatically discover the parser.
"""

from abc import ABC, abstractmethod
from importlib.metadata import entry_points
from pathlib import Path

from ..models import EffortAllocation, Invoice, SpendingReport

# ---------------------------------------------------------------------------
# Abstract base classes
# ---------------------------------------------------------------------------


class ReportParser(ABC):
    """Parse institutional spending reports into :class:`SpendingReport` objects."""

    @abstractmethod
    def name(self) -> str:
        """Human-readable name (e.g., ``'JHU Sponsored Report'``)."""

    @abstractmethod
    def can_parse(self, file_path: Path) -> bool:
        """Return *True* if this parser can handle *file_path*."""

    @abstractmethod
    def parse(self, file_path: Path) -> tuple[SpendingReport | None, list[EffortAllocation]]:
        """Parse a report file.

        Returns:
            ``(spending_report_or_None, list_of_personnel_allocations)``
        """


class InvoiceParser(ABC):
    """Parse sponsor invoices into :class:`Invoice` objects."""

    @abstractmethod
    def name(self) -> str:
        """Human-readable name (e.g., ``'JHU Lockbox Invoice'``)."""

    @abstractmethod
    def can_parse(self, file_path: Path) -> bool:
        """Return *True* if this parser can handle *file_path*."""

    @abstractmethod
    def parse(self, file_path: Path) -> Invoice | None:
        """Parse an invoice PDF and return an :class:`Invoice` or *None*."""


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


def discover_parsers() -> tuple[list[ReportParser], list[InvoiceParser]]:
    """Discover and instantiate all registered parsers via entry points.

    Returns:
        ``(report_parsers, invoice_parsers)``
    """
    report_parsers: list[ReportParser] = []
    invoice_parsers: list[InvoiceParser] = []

    eps = entry_points()
    # Python 3.12+ returns a SelectableGroups; 3.9-3.11 returns a dict
    parser_eps = (
        eps.select(group="smaug.parsers")
        if hasattr(eps, "select")
        else eps.get("smaug.parsers", [])  # type: ignore[arg-type]
    )

    for ep in parser_eps:
        try:
            cls = ep.load()
            instance = cls()
            if isinstance(instance, ReportParser):
                report_parsers.append(instance)
            elif isinstance(instance, InvoiceParser):
                invoice_parsers.append(instance)
        except Exception as e:
            # Don't crash on broken third-party parsers
            import warnings

            warnings.warn(f"Failed to load parser '{ep.name}': {e}", stacklevel=2)

    return report_parsers, invoice_parsers


def parse_report(
    file_path: Path,
    parsers: list[ReportParser],
) -> tuple[SpendingReport | None, list[EffortAllocation]]:
    """Try each parser in order until one succeeds.

    Returns:
        ``(spending_report_or_None, list_of_allocations)``
    """
    for parser in parsers:
        if parser.can_parse(file_path):
            return parser.parse(file_path)
    return None, []


def parse_invoice(
    file_path: Path,
    parsers: list[InvoiceParser],
) -> Invoice | None:
    """Try each invoice parser until one succeeds."""
    for parser in parsers:
        if parser.can_parse(file_path):
            return parser.parse(file_path)
    return None
