"""
Tests for ceiling resolution, period attribution, and mitigation planning.

These cover the distinction the reporting depends on: the *authorized* budget
(what the award may eventually be worth) versus the *funded ceiling* (what the
sponsor has actually obligated). Spending stops at the ceiling, so anything
forecasting exhaustion measures against it.
"""

import shutil
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import ClassVar

import pytest
import yaml

from smaug.api import SmaugAPI
from smaug.budget_resolution import (
    resolve_award_end_date,
    resolve_funded_ceiling,
    resolve_project_budget,
)
from smaug.cli._util import canonicalize_person_name

EXAMPLES_DIR = Path(__file__).parent.parent / "examples"

# QUASAR is authorized for 1,500,000 across three years, but the sponsor has
# only obligated 700,000 so far, and the award runs to 2028-06-30 rather than
# the 2028-06 recorded in the manifest.
CEILING_CSV = """\
project_id,period,year,month,total_spent,total_committed,total_month,salary_spent,indirect_spent,funded_ceiling,total_revenue_received,grant_end_date,budget_end_date,budget_start_date
QUASAR,September 2025,2025,9,300000.00,20000.00,300000.00,200000.00,100000.00,700000.00,300000.00,2028-06-30,2028-06-30,2025-01-01
QUASAR,October 2025,2025,10,350000.00,20000.00,50000.00,233000.00,117000.00,700000.00,350000.00,2028-06-30,2028-06-30,2025-01-01
QUASAR,November 2025,2025,11,400000.00,300000.00,50000.00,266000.00,134000.00,700000.00,400000.00,2028-06-30,2028-06-30,2025-01-01
"""


@pytest.fixture
def ceiling_api(tmp_path):
    """API over an isolated copy of examples whose QUASAR reports carry a ceiling."""
    dest = tmp_path / "data"
    shutil.copytree(EXAMPLES_DIR, dest, dirs_exist_ok=True)

    reports = dest / "reports" / "sponsored"
    # The shipped toy PDF also reports grant 200001, which the manifest maps to
    # QUASAR; clear every shipped report so these fixtures stand alone.
    for stale in reports.iterdir():
        if stale.is_file():
            stale.unlink()
    (reports / "quasar_ceiling.csv").write_text(CEILING_CSV)

    # budget_dir in the shipped manifest points at the repo's examples tree.
    manifest_path = dest / "projects" / "manifest.yaml"
    manifest = yaml.safe_load(manifest_path.read_text())
    manifest["projects"]["QUASAR"]["budget_dir"] = "projects/QUASAR"
    manifest_path.write_text(yaml.dump(manifest))

    return SmaugAPI(dest)


class TestCeilingResolution:
    def test_authorized_budget_is_the_contract_total(self, ceiling_api):
        store = ceiling_api._get_store()
        amount, source = resolve_project_budget(store, "QUASAR", ceiling_api.data_dir)
        assert amount == Decimal("1500000")
        assert source == "contractual_budget"

    def test_funded_ceiling_prefers_the_report_over_the_authorization(self, ceiling_api):
        store = ceiling_api._get_store()
        amount, source = resolve_funded_ceiling(store, "QUASAR", ceiling_api.data_dir)
        assert amount == Decimal("700000.00")
        assert "funded ceiling" in source

    def test_funded_ceiling_falls_back_to_the_authorization(self, ceiling_api):
        """A project with no reported ceiling still resolves to something usable."""
        store = ceiling_api._get_store()
        amount, source = resolve_funded_ceiling(store, "NEXUS", ceiling_api.data_dir)
        assert amount > Decimal("0")
        assert "authorized budget" in source

    def test_award_end_prefers_the_report_over_the_manifest(self, ceiling_api):
        store = ceiling_api._get_store()
        end_date, source = resolve_award_end_date(store, "QUASAR")
        assert end_date == date(2028, 6, 30)
        assert source.startswith("report")


class TestStopworkForecast:
    def test_measures_against_the_funded_ceiling(self, ceiling_api):
        result = ceiling_api.stopwork_forecast("QUASAR")
        assert result["ceiling"] == 700000.00
        assert "funded ceiling" in result["ceiling_source"]

    def test_reports_outstanding_commitments(self, ceiling_api):
        result = ceiling_api.stopwork_forecast("QUASAR")
        assert result["outstanding_commitments"] == 300000.00
        assert result["spent_and_committed"] == 700000.00

    def test_does_not_forecast_past_the_award_end(self, ceiling_api):
        result = ceiling_api.stopwork_forecast("QUASAR")
        assert result["award_end_date"] == "2028-06-30"
        for month in result["monthly_projections"]:
            assert month["month"] <= "2028-06"

    def test_user_supplied_ceiling_wins(self, ceiling_api):
        result = ceiling_api.stopwork_forecast("QUASAR", ceiling=123456.0)
        assert result["ceiling"] == 123456.0
        assert result["ceiling_source"] == "user-provided"


class TestListProjects:
    def test_remaining_is_measured_against_the_ceiling(self, ceiling_api):
        quasar = next(p for p in ceiling_api.list_projects() if p["id"] == "QUASAR")
        assert quasar["budget"] == 1500000.0
        assert quasar["funded_ceiling"] == 700000.0
        # Remaining runway comes off the ceiling, not the authorization.
        assert quasar["projected_remaining"] < 700000.0 - quasar["spent"] + 1

    def test_end_date_comes_from_the_report(self, ceiling_api):
        quasar = next(p for p in ceiling_api.list_projects() if p["id"] == "QUASAR")
        assert quasar["end_date"] == "2028-06-30"


class TestBudgetVsActualsAttribution:
    """The earliest report's cumulative total includes spending that predates it."""

    def test_period_actuals_reconcile_to_cumulative_spend(self, ceiling_api):
        result = ceiling_api.budget_vs_actuals("QUASAR")
        assert result["reconciles"] is True
        assert result["total_actual"] == pytest.approx(result["cumulative_spent"])

    def test_opening_balance_is_attributed_not_dropped(self, ceiling_api):
        """
        The first report (September 2025) shows 300,000 cumulative of which
        300,000 is that month, so there is nothing unreported to spread here;
        year 1 must still receive the spend rather than showing zero.
        """
        result = ceiling_api.budget_vs_actuals("QUASAR")
        year1 = next(p for p in result["periods"] if p["year_num"] == 1)
        assert year1["actual"] > 0

    def test_opening_balance_is_spread_and_reported(self, tmp_path):
        """A first report whose cumulative exceeds its own month carries an opening balance."""
        dest = tmp_path / "data"
        shutil.copytree(EXAMPLES_DIR, dest, dirs_exist_ok=True)
        reports = dest / "reports" / "sponsored"
        for stale in reports.iterdir():
            if stale.is_file():
                stale.unlink()
        # 500,000 cumulative in June 2026 of which only 50,000 is June: the
        # other 450,000 was spent across the award's first 17 months.
        (reports / "quasar_opening.csv").write_text(
            "project_id,period,year,month,total_spent,total_committed,total_month,"
            "funded_ceiling,budget_start_date,grant_end_date\n"
            "QUASAR,June 2026,2026,6,500000.00,0.00,50000.00,700000.00,2025-01-01,2028-06-30\n"
        )
        manifest_path = dest / "projects" / "manifest.yaml"
        manifest = yaml.safe_load(manifest_path.read_text())
        manifest["projects"]["QUASAR"]["budget_dir"] = "projects/QUASAR"
        manifest_path.write_text(yaml.dump(manifest))

        result = SmaugAPI(dest).budget_vs_actuals("QUASAR")

        assert result["opening_balance"]["amount"] == 450000.00
        assert result["opening_balance"]["covers"] == "Jan 2025 - May 2026"
        # Year 1 (calendar 2025) takes the 12/17 of the opening balance that
        # falls inside it rather than showing nothing.
        year1 = next(p for p in result["periods"] if p["year_num"] == 1)
        assert year1["actual"] == pytest.approx(450000.00 * 12 / 17, abs=0.01)
        assert result["reconciles"] is True


class TestOptimizeBudget:
    def test_plans_are_measured_against_the_ceiling(self, ceiling_api):
        plans = ceiling_api.optimize_budget("QUASAR")["plans"]
        assert plans
        assert plans[0]["ceiling"] == 700000.0
        assert plans[0]["available_funds"] == pytest.approx(300000.0)

    def test_levers_list_each_person_once(self, ceiling_api):
        """
        Date-bounded effort is stored as several segments per person; listing
        one lever per segment reads as duplicate people.
        """
        config_path = Path(ceiling_api.data_dir) / "projects" / "personnel_config.yaml"
        config = yaml.safe_load(config_path.read_text())
        for person in config["personnel"]:
            if person["name"] == "Smith, Jane":
                person["assignments"] = [
                    {"project": "QUASAR", "effort": 0.1, "start": "2025-01", "end": "2026-06"},
                    {"project": "QUASAR", "effort": 0.3, "start": "2026-06", "end": "2027-06"},
                    {"project": "QUASAR", "effort": 0.5, "start": "2027-06", "end": "2028-06"},
                ]
        config_path.write_text(yaml.dump(config))

        plans = SmaugAPI(ceiling_api.data_dir).optimize_budget("QUASAR")["plans"]
        levers = [lever for lever in plans[1]["levers"] if "Smith, Jane" in lever]
        assert len(levers) == 1

    def test_zero_effort_assignments_are_not_offered_as_levers(self, ceiling_api):
        config_path = Path(ceiling_api.data_dir) / "projects" / "personnel_config.yaml"
        config = yaml.safe_load(config_path.read_text())
        config["personnel"].append(
            {
                "name": "Idle, Eric",
                "type": "staff",
                "annual_salary": 90000,
                "assignments": [{"project": "QUASAR", "effort": 0.0}],
            }
        )
        config_path.write_text(yaml.dump(config))

        plans = SmaugAPI(ceiling_api.data_dir).optimize_budget("QUASAR")["plans"]
        for plan in plans:
            assert not any("Idle, Eric" in lever for lever in plan["levers"])
            assert not any("0% -> 0%" in lever for lever in plan["levers"])

    def test_deeper_cuts_leave_more_money(self, ceiling_api):
        plans = ceiling_api.optimize_budget("QUASAR")["plans"]
        left = [plan["funds_left_at_award_end"] for plan in plans]
        assert left[2] >= left[1] >= left[0]


class TestNameCanonicalization:
    """One person must not become several identities through spelling variants."""

    ALIASES: ClassVar[dict[str, str]] = {
        "Molly": "Doe, Mary",
        "Doe, Mary Elizabeth": "Doe, Mary",
    }
    KNOWN: ClassVar[set[str]] = {"Doe, Mary", "Smith, Jane"}

    def test_alias_resolves_to_config_spelling(self):
        assert (
            canonicalize_person_name("Doe, Mary Elizabeth", self.ALIASES, self.KNOWN) == "Doe, Mary"
        )

    def test_short_alias_resolves(self):
        assert canonicalize_person_name("Molly", self.ALIASES, self.KNOWN) == "Doe, Mary"

    def test_reversed_name_order_resolves(self):
        assert canonicalize_person_name("Jane Smith", {}, self.KNOWN) == "Smith, Jane"

    def test_longer_payroll_spelling_resolves_without_an_alias(self):
        assert canonicalize_person_name("Doe, Mary Elizabeth", {}, self.KNOWN) == "Doe, Mary"

    def test_unknown_name_is_left_alone(self):
        assert canonicalize_person_name("Stranger, Perfect", {}, self.KNOWN) == "Stranger, Perfect"
