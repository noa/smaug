"""
Contractual budget loading and period-aware calculations.

Loads budget ceiling data from budget_config.yaml files, which represent
the fixed contractual allocations that don't change with salary adjustments.
"""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path

import yaml


@dataclass
class ContractPeriod:
    """A single contract period (e.g., Year 1, Year 2)."""

    year_num: int
    start: date
    end: date
    total: Decimal
    direct: Decimal
    idc: Decimal


@dataclass
class ContractualBudget:
    """Complete contractual budget with period allocations."""

    award_id: str
    pi: str
    start_date: date
    periods: list[ContractPeriod] = field(default_factory=list)
    total_budget: Decimal = Decimal("0")
    total_direct_costs: Decimal = Decimal("0")
    total_indirect_costs: Decimal = Decimal("0")

    def get_period_for_date(self, check_date: date) -> ContractPeriod | None:
        """Get the contract period containing the given date."""
        for period in self.periods:
            if period.start <= check_date <= period.end:
                return period
        return None

    def get_period_by_year(self, year_num: int) -> ContractPeriod | None:
        """Get a specific contract period by year number."""
        for period in self.periods:
            if period.year_num == year_num:
                return period
        return None

    def get_budget_through_date(self, through_date: date) -> Decimal:
        """
        Get cumulative budget ceiling through a given date.

        Includes full allocation for all completed periods plus
        pro-rated allocation for the current period.
        """
        total = Decimal("0")

        for period in sorted(self.periods, key=lambda p: p.year_num):
            if period.end <= through_date:
                # Period fully complete
                total += period.total
            elif period.start <= through_date:
                # Partially through this period - pro-rate
                days_in_period = (period.end - period.start).days + 1
                days_elapsed = (through_date - period.start).days + 1
                fraction = Decimal(str(days_elapsed)) / Decimal(str(days_in_period))
                total += period.total * fraction
                break
            else:
                # Future period
                break

        return total

    def get_completed_periods(self, as_of: date) -> list[ContractPeriod]:
        """Get all periods that ended before the given date."""
        return [p for p in self.periods if p.end < as_of]

    def get_current_period(self, as_of: date) -> ContractPeriod | None:
        """Get the period containing the given date."""
        return self.get_period_for_date(as_of)

    def get_future_periods(self, as_of: date) -> list[ContractPeriod]:
        """Get all periods starting after the given date."""
        return [p for p in self.periods if p.start > as_of]


def parse_date_str(date_str: str) -> date:
    """Parse YYYY-MM-DD date string."""
    parts = str(date_str).split("-")
    return date(int(parts[0]), int(parts[1]), int(parts[2]))


def load_contractual_budget(config_path: str | Path) -> ContractualBudget | None:
    """
    Load contractual budget from budget_config.yaml.

    Args:
        config_path: Path to budget_config.yaml file

    Returns:
        ContractualBudget or None if file doesn't exist or is invalid
    """
    config_path = Path(config_path)

    if not config_path.exists():
        return None

    try:
        with open(config_path) as f:
            config = yaml.safe_load(f)
    except Exception:
        return None

    if not config:
        return None

    contract = config.get("contract", {})
    totals = config.get("totals", {})
    by_year = config.get("by_year", {})
    periods_config = contract.get("periods", {})

    # Parse start date
    start_date_str = contract.get("start_date", "")
    if not start_date_str:
        return None
    start_date = parse_date_str(start_date_str)

    # Build period list
    periods = []
    for year_key, period_dates in periods_config.items():
        # year_key is like 'year1', 'year2', etc.
        year_num = int(year_key.replace("year", ""))

        period_start = parse_date_str(period_dates["start"])
        period_end = parse_date_str(period_dates["end"])

        # Get budget for this year
        year_budget = by_year.get(year_key, {})

        periods.append(
            ContractPeriod(
                year_num=year_num,
                start=period_start,
                end=period_end,
                total=Decimal(str(year_budget.get("total", 0))),
                direct=Decimal(str(year_budget.get("direct", 0))),
                idc=Decimal(str(year_budget.get("idc", 0))),
            )
        )

    # Sort periods by year number
    periods.sort(key=lambda p: p.year_num)

    return ContractualBudget(
        award_id=contract.get("award_id", ""),
        pi=contract.get("pi", ""),
        start_date=start_date,
        periods=periods,
        total_budget=Decimal(str(totals.get("total_budget", 0))),
        total_direct_costs=Decimal(str(totals.get("total_direct_costs", 0))),
        total_indirect_costs=Decimal(str(totals.get("total_indirect_costs", 0))),
    )
