"""
Report validation and sanity checking.

Validates parsed spending reports for structural integrity and
cross-field consistency before they are stored.  Catches common
parsing failures (missed regexes, malformed dates, non-monotonic
cumulative totals) that would otherwise silently corrupt data.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

from .models import SpendingReport

logger = logging.getLogger(__name__)


@dataclass
class ParseWarning:
    """A validation finding from report parsing."""

    file: str
    severity: str  # "error" | "warning"
    code: str  # machine-readable code, e.g. "ZERO_YEAR"
    message: str


@dataclass
class ValidationResult:
    """Outcome of validating a parsed report."""

    report: SpendingReport
    source_file: Path
    warnings: list[ParseWarning] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        """True if no errors (warnings are tolerated)."""
        return not any(w.severity == "error" for w in self.warnings)

    @property
    def errors(self) -> list[ParseWarning]:
        return [w for w in self.warnings if w.severity == "error"]


def validate_report(
    report: SpendingReport,
    source_file: Path,
    prior_reports: list[SpendingReport] | None = None,
) -> ValidationResult:
    """Validate a parsed spending report.

    Args:
        report: The parsed report to validate.
        source_file: Path to the source file (for diagnostics).
        prior_reports: Earlier reports for the same project, sorted
            chronologically.  Used for monotonicity checks.

    Returns:
        ValidationResult with any warnings/errors.
    """
    result = ValidationResult(report=report, source_file=source_file)
    fname = source_file.name

    # --- Hard errors (report should be rejected) ---

    if report.year == 0 or report.month == 0:
        result.warnings.append(
            ParseWarning(
                file=fname,
                severity="error",
                code="INVALID_DATE",
                message=f"Invalid date: year={report.year}, month={report.month}",
            )
        )

    if report.month < 0 or report.month > 12:
        result.warnings.append(
            ParseWarning(
                file=fname,
                severity="error",
                code="MONTH_OUT_OF_RANGE",
                message=f"Month out of range: {report.month}",
            )
        )

    if report.project_id in ("unknown", "", None):
        result.warnings.append(
            ParseWarning(
                file=fname,
                severity="error",
                code="UNKNOWN_PROJECT",
                message="Could not determine project ID from report",
            )
        )

    if report.period in ("Unknown", "", None):
        result.warnings.append(
            ParseWarning(
                file=fname,
                severity="error",
                code="UNKNOWN_PERIOD",
                message="Could not parse report period string",
            )
        )

    # --- Warnings (report is stored but flagged) ---

    if report.total_spent < 0:
        result.warnings.append(
            ParseWarning(
                file=fname,
                severity="warning",
                code="NEGATIVE_SPENT",
                message=f"Negative total_spent: ${report.total_spent:,.2f}",
            )
        )

    # Cross-field consistency: spent + committed ≈ spent_and_committed
    if report.total_spent_and_committed != Decimal("0"):
        expected = report.total_spent + report.total_committed
        diff = abs(report.total_spent_and_committed - expected)
        if diff > Decimal("1"):
            result.warnings.append(
                ParseWarning(
                    file=fname,
                    severity="warning",
                    code="TOTAL_MISMATCH",
                    message=(
                        f"spent+committed mismatch: "
                        f"${report.total_spent:,.2f} + ${report.total_committed:,.2f} "
                        f"= ${expected:,.2f}, but report says ${report.total_spent_and_committed:,.2f} "
                        f"(diff: ${diff:,.2f})"
                    ),
                )
            )

    # Category sum vs total_spent (approximate check)
    category_sum = (
        report.salary_spent
        + report.fringe_spent
        + report.tuition_spent
        + report.insurance_spent
        + report.service_center_spent
        + report.travel_spent
        + report.other_spent
        + report.indirect_spent
    )
    if report.total_spent != Decimal("0") and category_sum != Decimal("0"):
        cat_diff = abs(report.total_spent - category_sum)
        # Allow a tolerance — some reports have rounding or categories we don't track
        threshold = max(Decimal("100"), report.total_spent * Decimal("0.02"))
        if cat_diff > threshold:
            result.warnings.append(
                ParseWarning(
                    file=fname,
                    severity="warning",
                    code="CATEGORY_SUM_MISMATCH",
                    message=(
                        f"Category sum ${category_sum:,.2f} differs from "
                        f"total_spent ${report.total_spent:,.2f} by ${cat_diff:,.2f}"
                    ),
                )
            )

    # All-zeros check: if total_spent is 0 but the file parsed successfully,
    # something is likely wrong with the extraction
    all_zeros = (
        report.total_spent == Decimal("0")
        and report.total_committed == Decimal("0")
        and report.total_spent_and_committed == Decimal("0")
    )
    if all_zeros and report.year != 0:
        result.warnings.append(
            ParseWarning(
                file=fname,
                severity="warning",
                code="ALL_ZEROS",
                message="All spending totals are zero — possible extraction failure",
            )
        )

    # Monotonicity check: cumulative total_spent should never decrease
    if prior_reports:
        latest_prior = max(prior_reports, key=lambda r: (r.year, r.month))
        if (report.year, report.month) > (
            latest_prior.year,
            latest_prior.month,
        ) and report.total_spent < latest_prior.total_spent:
            decrease = latest_prior.total_spent - report.total_spent
            result.warnings.append(
                ParseWarning(
                    file=fname,
                    severity="warning",
                    code="NON_MONOTONIC",
                    message=(
                        f"Cumulative total_spent decreased: "
                        f"${latest_prior.total_spent:,.2f} ({latest_prior.period}) → "
                        f"${report.total_spent:,.2f} ({report.period}), "
                        f"drop of ${decrease:,.2f}"
                    ),
                )
            )

    # Log warnings
    for w in result.warnings:
        if w.severity == "error":
            logger.warning("PARSE ERROR [%s]: %s", fname, w.message)
        else:
            logger.info("PARSE WARNING [%s]: %s", fname, w.message)

    return result
