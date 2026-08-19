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
    """Parse YYYY-MM-DD or YYYY-MM date string."""
    parts = str(date_str).split("-")
    if len(parts) >= 3:
        return date(int(parts[0]), int(parts[1]), int(parts[2]))
    if len(parts) == 2:
        return date(int(parts[0]), int(parts[1]), 1)
    return date.today()


def load_contractual_budget(config_path: str | Path) -> ContractualBudget | None:
    """
    Load contractual budget from budget_config.yaml.

    Supports both standard nested schema and flat list-of-periods schema.

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

    if not config or not isinstance(config, dict):
        return None

    # Check for flat list format
    if "periods" in config and isinstance(config["periods"], list):
        periods = []
        total_budget = Decimal("0")
        total_direct = Decimal("0")
        total_idc = Decimal("0")
        start_date = None

        for p_data in config["periods"]:
            year_num = int(p_data.get("year", p_data.get("year_num", 1)))
            p_start = parse_date_str(str(p_data.get("start", "2020-01-01")))
            p_end = parse_date_str(str(p_data.get("end", "2020-12-31")))
            if start_date is None or p_start < start_date:
                start_date = p_start

            p_total = Decimal(str(p_data.get("total", 0)))
            p_direct = Decimal(str(p_data.get("direct", 0)))
            p_idc = Decimal(str(p_data.get("idc", 0)))

            total_budget += p_total
            total_direct += p_direct
            total_idc += p_idc

            periods.append(
                ContractPeriod(
                    year_num=year_num,
                    start=p_start,
                    end=p_end,
                    total=p_total,
                    direct=p_direct,
                    idc=p_idc,
                )
            )

        periods.sort(key=lambda p: p.year_num)
        return ContractualBudget(
            award_id=str(config.get("award_id", "")),
            pi=str(config.get("pi", "")),
            start_date=start_date or date.today(),
            periods=periods,
            total_budget=total_budget,
            total_direct_costs=total_direct,
            total_indirect_costs=total_idc,
        )

    contract = config.get("contract", {})
    totals = config.get("totals", {})
    by_year = config.get("by_year", {})
    periods_config = contract.get("periods", {})

    # Parse start date
    start_date_str = contract.get("start_date", "")
    if not start_date_str and periods_config:
        # Infer start date from first period
        first_p = next(iter(periods_config.values()))
        start_date_str = first_p.get("start", "")

    if not start_date_str:
        return None
    start_date = parse_date_str(start_date_str)

    # Build period list
    periods = []
    for year_key, period_dates in periods_config.items():
        # year_key is like 'year1', 'year2', etc.
        try:
            year_num = int(str(year_key).replace("year", "").replace("Year", ""))
        except ValueError:
            year_num = 1

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
