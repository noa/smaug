"""
Audit functionality for comparing spending reports against expected effort.

Compares actual spending from PDF reports against expected costs based on
personnel_config.yaml effort allocations.
"""

from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from pathlib import Path

from .models import EffortAllocation
from .projections import PersonnelEntry, is_active, load_personnel_config


class FindingType(Enum):
    """Types of audit findings."""

    EFFORT_VARIANCE = "effort_variance"  # Expected vs actual differs significantly
    MISSING_FROM_REPORT = "missing_from_report"  # In config but not in report
    UNEXPECTED_IN_REPORT = "unexpected_in_report"  # In report but not in config
    OUTSIDE_ASSIGNMENT = "outside_assignment"  # Billing outside assignment window


@dataclass
class AuditFinding:
    """A single audit finding."""

    finding_type: FindingType
    person_name: str
    project_id: str
    period: str
    message: str
    expected_amount: Decimal | None = None
    actual_amount: Decimal | None = None
    variance_pct: Decimal | None = None

    @property
    def severity(self) -> str:
        """Return severity level: info, warning, error."""
        if self.finding_type == FindingType.UNEXPECTED_IN_REPORT:
            return "warning"
        if self.finding_type == FindingType.MISSING_FROM_REPORT:
            return "info"
        if self.finding_type == FindingType.OUTSIDE_ASSIGNMENT:
            return "warning"
        if self.variance_pct is not None:
            if abs(self.variance_pct) > Decimal("25"):
                return "error"
            return "warning"
        return "info"


@dataclass
class AuditReport:
    """Complete audit report with findings."""

    project_id: str | None  # None if cross-project
    periods: list[str]
    findings: list[AuditFinding] = field(default_factory=list)
    personnel_compared: int = 0

    @property
    def error_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == "error")

    @property
    def warning_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == "warning")

    @property
    def info_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == "info")


def _normalize_name(name: str) -> str:
    """Normalize person name for comparison (handle 'Last, First' variations)."""
    # Remove extra whitespace and standardize
    return " ".join(name.strip().split())


def _get_expected_monthly_salary(
    person: PersonnelEntry, project_id: str, year: int, month: int
) -> Decimal | None:
    """
    Get expected monthly salary for a person on a project.

    Returns None if person has no active assignment for that project/month.
    """
    for assignment in person.assignments:
        if assignment.project != project_id:
            continue
        if not is_active(assignment, year, month, person.departure):
            continue
        if assignment.effort <= 0:
            continue

        # Monthly salary = annual / 12 * effort
        return (person.annual_salary / 12) * assignment.effort

    return None


def _has_active_assignment(person: PersonnelEntry, project_id: str, year: int, month: int) -> bool:
    """Check if person has any active assignment (even 0%) on project for month."""
    for assignment in person.assignments:
        if assignment.project != project_id:
            continue
        if is_active(assignment, year, month, person.departure):
            return True
    return False


def audit_project_period(
    project_id: str,
    period: str,
    year: int,
    month: int,
    personnel_config: list[PersonnelEntry],
    actual_allocations: list[EffortAllocation],
    threshold_pct: Decimal = Decimal("10"),
    aliases: dict[str, str] | None = None,
) -> list[AuditFinding]:
    """
    Audit a single project for a single period.

    Args:
        project_id: Project short name
        period: Period string (e.g., "January 2026")
        year: Year to check
        month: Month to check
        personnel_config: Expected personnel from config
        actual_allocations: Actual allocations from PDF reports
        threshold_pct: Variance threshold to flag (default 10%)
        aliases: Optional dict mapping payroll names to config names

    Returns:
        List of AuditFinding objects
    """
    findings = []

    def resolve_name(raw_name: str) -> str:
        if aliases:
            query = raw_name.lower().strip()
            for alias, real_name in aliases.items():
                if alias.lower().strip() == query:
                    return real_name
        return raw_name

    # Build lookup of actual amounts by normalized name
    actual_by_name: dict[str, Decimal] = {}
    for alloc in actual_allocations:
        if alloc.project_id != project_id:
            continue
        if alloc.period != period:
            continue
        canon_name = resolve_name(alloc.person_name)
        name_key = _normalize_name(canon_name)
        actual_by_name[name_key] = actual_by_name.get(name_key, Decimal("0")) + alloc.salary_amount

    # Build lookup of expected amounts
    expected_by_name: dict[str, Decimal] = {}
    config_by_name: dict[str, PersonnelEntry] = {}

    for person in personnel_config:
        expected = _get_expected_monthly_salary(person, project_id, year, month)
        if expected is not None and expected > 0:
            name_key = _normalize_name(person.name)
            expected_by_name[name_key] = expected
            config_by_name[name_key] = person

    # Compare expected vs actual
    all_names = set(expected_by_name.keys()) | set(actual_by_name.keys())

    for name in all_names:
        expected = expected_by_name.get(name)
        actual = actual_by_name.get(name)

        if expected is not None and actual is None:
            # Expected but not in report
            findings.append(
                AuditFinding(
                    finding_type=FindingType.MISSING_FROM_REPORT,
                    person_name=name,
                    project_id=project_id,
                    period=period,
                    message=f"Expected ${expected:,.2f} but not found in report",
                    expected_amount=expected,
                    actual_amount=Decimal("0"),
                )
            )

        elif actual is not None and expected is None:
            # In report but not expected
            # Check if they have ANY assignment (even 0%) listed
            person_entry = None
            for p in personnel_config:
                if _normalize_name(p.name) == name or _normalize_name(resolve_name(p.name)) == name:
                    person_entry = p
                    break

            if person_entry is None:
                findings.append(
                    AuditFinding(
                        finding_type=FindingType.UNEXPECTED_IN_REPORT,
                        person_name=name,
                        project_id=project_id,
                        period=period,
                        message=f"Found ${actual:,.2f} but person not in config",
                        actual_amount=actual,
                    )
                )
            elif not _has_active_assignment(person_entry, project_id, year, month):
                findings.append(
                    AuditFinding(
                        finding_type=FindingType.OUTSIDE_ASSIGNMENT,
                        person_name=name,
                        project_id=project_id,
                        period=period,
                        message=f"Found ${actual:,.2f} but assignment not active for this period",
                        actual_amount=actual,
                    )
                )

        elif expected is not None and actual is not None:
            # Both exist - check variance
            if expected > 0:
                variance_pct = ((actual - expected) / expected) * 100
            else:
                variance_pct = Decimal("100") if actual > 0 else Decimal("0")

            if abs(variance_pct) > threshold_pct:
                direction = "over" if variance_pct > 0 else "under"
                findings.append(
                    AuditFinding(
                        finding_type=FindingType.EFFORT_VARIANCE,
                        person_name=name,
                        project_id=project_id,
                        period=period,
                        message=f"${actual:,.2f} vs expected ${expected:,.2f} ({direction} by {abs(variance_pct):.1f}%)",
                        expected_amount=expected,
                        actual_amount=actual,
                        variance_pct=variance_pct,
                    )
                )

    return findings


def audit_project(
    project_id: str,
    config_path: Path,
    actual_allocations: list[EffortAllocation],
    periods: list[str] | None = None,
    months_back: int = 3,
    threshold_pct: Decimal = Decimal("10"),
    aliases: dict[str, str] | None = None,
) -> AuditReport:
    """
    Run audit for a project across multiple periods.

    Args:
        project_id: Project short name
        config_path: Path to personnel_config.yaml
        actual_allocations: All allocations from PDF reports
        periods: Specific periods to audit (or None for auto-detect)
        months_back: Number of months to look back (default 3)
        threshold_pct: Variance threshold to flag
        aliases: Optional dict mapping payroll names to config names

    Returns:
        AuditReport with findings
    """
    _rates, personnel = load_personnel_config(config_path)

    # Get periods from actual allocations if not specified
    if periods is None:
        project_allocs = [a for a in actual_allocations if a.project_id == project_id]
        period_set = set(a.period for a in project_allocs)

        # Parse and sort periods, take most recent N
        period_dates = []
        for p in period_set:
            try:
                # Parse "Month Year" format
                parts = p.split()
                if len(parts) == 2:
                    from datetime import datetime

                    dt = datetime.strptime(p, "%B %Y")
                    period_dates.append((dt, p))
            except ValueError:
                continue

        period_dates.sort(key=lambda x: x[0], reverse=True)
        periods = [p[1] for p in period_dates[:months_back]]

    all_findings = []

    for period in periods:
        # Parse period to year/month
        try:
            from datetime import datetime

            dt = datetime.strptime(period, "%B %Y")
            year, month = dt.year, dt.month
        except ValueError:
            continue

        findings = audit_project_period(
            project_id=project_id,
            period=period,
            year=year,
            month=month,
            personnel_config=personnel,
            actual_allocations=actual_allocations,
            threshold_pct=threshold_pct,
            aliases=aliases,
        )
        all_findings.extend(findings)

    return AuditReport(
        project_id=project_id,
        periods=periods,
        findings=all_findings,
        personnel_compared=len(set(f.person_name for f in all_findings)),
    )


def format_audit_report(report: AuditReport, use_color: bool = True) -> str:
    """
    Format audit report for terminal output.

    Args:
        report: AuditReport to format
        use_color: Whether to use ANSI color codes

    Returns:
        Formatted string
    """
    # ANSI color codes
    reset = "\033[0m" if use_color else ""
    bold = "\033[1m" if use_color else ""
    red = "\033[91m" if use_color else ""
    yellow = "\033[93m" if use_color else ""
    green = "\033[92m" if use_color else ""
    dim = "\033[2m" if use_color else ""

    lines = []

    # Header
    project_str = report.project_id or "All Projects"
    lines.append(f"\n{bold}=== Audit Report: {project_str} ==={reset}")
    lines.append(f"{dim}Periods: {', '.join(report.periods)}{reset}")
    lines.append("")

    if not report.findings:
        lines.append(f"{green}✓ No issues found{reset}")
        return "\n".join(lines)

    # Summary
    summary_parts = []
    if report.error_count > 0:
        summary_parts.append(f"{red}{report.error_count} errors{reset}")
    if report.warning_count > 0:
        summary_parts.append(f"{yellow}{report.warning_count} warnings{reset}")
    if report.info_count > 0:
        summary_parts.append(f"{dim}{report.info_count} info{reset}")

    lines.append(f"Summary: {', '.join(summary_parts)}")
    lines.append("")

    # Group findings by period
    by_period: dict[str, list[AuditFinding]] = {}
    for finding in report.findings:
        if finding.period not in by_period:
            by_period[finding.period] = []
        by_period[finding.period].append(finding)

    for period in sorted(by_period.keys(), reverse=True):
        lines.append(f"{bold}{period}{reset}")

        for finding in by_period[period]:
            # Color based on severity
            if finding.severity == "error":
                icon = f"{red}✗{reset}"
                clr = red
            elif finding.severity == "warning":
                icon = f"{yellow}!{reset}"
                clr = yellow
            else:
                icon = f"{dim}○{reset}"
                clr = dim

            from .cli._util import Anonymizer

            msg = finding.message
            if Anonymizer.enabled:
                for real_name, anon_name in Anonymizer._real_to_anon.items():
                    msg = msg.replace(real_name, anon_name)
            lines.append(f"  {icon} {clr}{Anonymizer.anonymize(finding.person_name)}{reset}: {msg}")

        lines.append("")

    return "\n".join(lines)
