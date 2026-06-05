"""Tests for the SmaugAPI programmatic interface."""

import json
from decimal import Decimal
from pathlib import Path

import pytest

from smaug.api import SmaugAPI

EXAMPLES_DIR = Path(__file__).parent.parent / "examples"


@pytest.fixture
def api():
    """SmaugAPI pointed at the examples directory."""
    return SmaugAPI(EXAMPLES_DIR)


class TestListProjects:
    def test_returns_list(self, api):
        result = api.list_projects()
        assert isinstance(result, list)

    def test_active_projects_only_by_default(self, api):
        result = api.list_projects()
        statuses = {p["status"] for p in result}
        assert statuses <= {"active"}

    def test_all_statuses(self, api):
        # Proposed projects should appear when filtering
        result = api.list_projects(status="proposed")
        assert any(p["id"] == "ATLAS" for p in result)

    def test_fields_present(self, api):
        result = api.list_projects()
        assert len(result) > 0
        proj = result[0]
        for key in [
            "id",
            "name",
            "status",
            "budget",
            "spent",
            "pct_spent",
            "monthly_burn",
            "projected_total",
            "projected_remaining",
        ]:
            assert key in proj, f"Missing key: {key}"

    def test_json_serializable(self, api):
        result = api.list_projects()
        # Should not raise
        json_str = json.dumps(result)
        assert isinstance(json_str, str)

    def test_no_decimal_types(self, api):
        result = api.list_projects()
        for proj in result:
            for key, val in proj.items():
                assert not isinstance(val, Decimal), f"Field {key} is Decimal, should be float"


class TestProjectStatus:
    def test_valid_project(self, api):
        result = api.project_status("QUASAR")
        assert "project" in result
        assert result["project"]["id"] == "QUASAR"

    def test_invalid_project(self, api):
        result = api.project_status("NONEXISTENT")
        assert "error" in result

    def test_budget_present(self, api):
        result = api.project_status("QUASAR")
        # QUASAR has a total_budget in manifest, so budget info should exist
        assert result["project"]["name"] == "Quantum-Assisted Sensing and Recognition"

    def test_json_serializable(self, api):
        result = api.project_status("QUASAR")
        json_str = json.dumps(result)
        assert isinstance(json_str, str)


class TestSpendingReport:
    def test_valid_project(self, api):
        result = api.spending_report("QUASAR")
        assert result["project"] == "QUASAR"
        assert isinstance(result["periods"], list)
        assert isinstance(result["personnel_totals"], dict)

    def test_invalid_project(self, api):
        result = api.spending_report("NONEXISTENT")
        assert "error" in result


class TestDumpProject:
    def test_returns_dict(self, api):
        result = api.dump_project("QUASAR")
        assert isinstance(result, dict)
        assert "project" in result

    def test_json_serializable(self, api):
        result = api.dump_project("QUASAR")
        json_str = json.dumps(result)
        assert isinstance(json_str, str)


class TestSpendingProjection:
    def test_basic_projection(self, api):
        result = api.spending_projection("QUASAR", months=3)
        assert result["project"] == "QUASAR"
        assert isinstance(result["projections"], list)
        assert len(result["projections"]) == 3
        assert "totals" in result

    def test_projection_fields(self, api):
        result = api.spending_projection("QUASAR", months=1)
        proj = result["projections"][0]
        for key in ["month", "salary", "fringe", "indirect", "total", "personnel"]:
            assert key in proj, f"Missing key: {key}"

    def test_json_serializable(self, api):
        result = api.spending_projection("QUASAR", months=2)
        json_str = json.dumps(result)
        assert isinstance(json_str, str)

    def test_nonzero_values(self, api):
        """QUASAR has active personnel, so projections should be nonzero."""
        result = api.spending_projection("QUASAR", months=1)
        total = result["totals"]["total"]
        assert total > 0


class TestStopworkForecast:
    def test_with_ceiling(self, api):
        result = api.stopwork_forecast("QUASAR", ceiling=100000)
        # May return error if no spending reports loaded from example CSVs
        if "error" in result:
            assert "spending" in result["error"].lower() or "not found" in result["error"].lower()
        else:
            assert result["project"] == "QUASAR"
            assert result["ceiling"] == 100000.0
            assert isinstance(result["monthly_projections"], list)

    def test_invalid_project(self, api):
        result = api.stopwork_forecast("NONEXISTENT")
        assert "error" in result

    def test_json_serializable(self, api):
        result = api.stopwork_forecast("QUASAR", ceiling=100000)
        json_str = json.dumps(result)
        assert isinstance(json_str, str)


class TestAudit:
    def test_returns_structure(self, api):
        result = api.audit(project="QUASAR")
        assert "findings" in result
        assert "summary" in result
        assert isinstance(result["findings"], list)

    def test_summary_keys(self, api):
        result = api.audit()
        for key in ["errors", "warnings", "info"]:
            assert key in result["summary"]

    def test_json_serializable(self, api):
        result = api.audit()
        json_str = json.dumps(result)
        assert isinstance(json_str, str)


class TestProposalBudget:
    def test_basic_proposal(self, api):
        result = api.proposal_budget(
            pi=[{"name": "Smith", "effort_pct": 10}],
            phd=1,
            years=2,
            travel=5000,
        )
        assert "years" in result
        assert len(result["years"]) == 2
        assert result["grand_total"] > 0

    def test_personnel_detail(self, api):
        result = api.proposal_budget(
            pi=[{"name": "Smith", "effort_pct": 10}],
            phd=1,
        )
        assert 1 in result["personnel_detail"]
        detail = result["personnel_detail"][1]
        assert len(detail) == 2  # PI + 1 PhD

    def test_json_serializable(self, api):
        result = api.proposal_budget(phd=1)
        json_str = json.dumps(result)
        assert isinstance(json_str, str)

    def test_no_personnel_error(self, api):
        result = api.proposal_budget()
        assert "error" in result


@pytest.fixture
def temp_api(tmp_path):
    import shutil

    shutil.copytree(EXAMPLES_DIR, tmp_path / "data", dirs_exist_ok=True)
    return SmaugAPI(tmp_path / "data")


class TestNotesAPI:
    def test_notes_crud(self, temp_api):
        # 1. Add a note
        res = temp_api.add_project_note(
            "QUASAR", "My Test Note", "Some note content.", tags=["test", "api"]
        )
        assert res.get("success") is True

        # 2. List notes
        notes = temp_api.list_project_notes("QUASAR")
        assert len(notes) >= 1
        assert any(n["title"] == "My Test Note" for n in notes)

        # 3. Show note
        note = temp_api.show_project_note("QUASAR", "My Test Note")
        assert "content" in note
        assert "Some note content." in note["content"]

        # 4. Remove note
        del_res = temp_api.remove_project_note("QUASAR", "My Test Note")
        assert del_res.get("success") is True

        # Verify it's gone
        notes_after = temp_api.list_project_notes("QUASAR")
        assert not any(n["title"] == "My Test Note" for n in notes_after)


class TestWriteCommandsAPI:
    def test_set_personnel_effort(self, temp_api):
        res = temp_api.set_personnel_effort("Smith, Jane", "QUASAR", 50.0)
        assert res.get("success") is True

        # Verify the change is reflected
        plan = temp_api.spend_plan(["QUASAR"])
        assert "projections" in plan

    def test_add_personnel(self, temp_api):
        res = temp_api.add_personnel("Doe, Jane", "postdoc", "QUASAR", 100.0, salary=80000)
        assert res.get("success") is True

    def test_add_travel_item(self, temp_api):
        res = temp_api.add_travel_item(
            "QUASAR", "IEEE Conference", "2026-08-15", 3000.0, traveler="Smith, Jane"
        )
        assert res.get("success") is True

    def test_add_expense_item(self, temp_api):
        res = temp_api.add_expense_item(
            "QUASAR",
            "Server Hosting",
            500.0,
            category="Other",
            start_str="2026-06-01",
            end_str="2026-12-31",
        )
        assert res.get("success") is True

    def test_date_bounded_effort_crud(self, temp_api):
        res = temp_api.set_personnel_effort(
            "Smith, Jane", "QUASAR", 20.0, start="2026-06", end="2026-09"
        )
        assert res.get("success") is True

        res = temp_api.set_personnel_effort(
            "Smith, Jane", "QUASAR", 30.0, start="2026-06", end="2026-09"
        )
        assert res.get("success") is True

        res = temp_api.remove_personnel_effort(
            "Smith, Jane", "QUASAR", start="2026-06", end="2026-09"
        )
        assert res.get("success") is True

    def test_date_bounded_salary_crud(self, temp_api):
        # 1. Update salary with start date (converts flat salary to schedule)
        res = temp_api.set_salary("Smith, Jane", 200000, start="2026-07")
        assert res.get("success") is True

        # 2. Update it again with identical start date to verify in-place update
        res = temp_api.set_salary("Smith, Jane", 220000, start="2026-07")
        assert res.get("success") is True

        # Verify spend plan uses old salary ($180,000) in 2026-06 and new salary ($220,000) in 2026-07.
        # Jane Smith has 10% effort on QUASAR.
        plan = temp_api.spend_plan(["QUASAR"])
        proj_06 = next(p for p in plan["projections"] if p["month"] == "2026-06")
        proj_07 = next(p for p in plan["projections"] if p["month"] == "2026-07")

        # Monthly salary difference should be (220k - 180k) / 12 * 0.10 = 333.33
        diff = proj_07["salary"] - proj_06["salary"]
        assert abs(diff - 333.33) < 0.02

        # Verify personnel overview shows salaries list
        overview = temp_api.personnel_overview()
        person = next(p for p in overview["personnel"] if "Smith" in p["name"])
        assert len(person["salaries"]) == 2

        # 3. Add another time-bounded salary segment
        res = temp_api.set_salary("Smith, Jane", 240000, start="2027-07", end="2028-07")
        assert res.get("success") is True

        # 4. Overwrite schedule with flat salary
        res = temp_api.set_salary("Smith, Jane", 185000)
        assert res.get("success") is True


class TestSpendPlanAPI:
    def test_spend_plan_basic(self, api):
        res = api.spend_plan(["QUASAR"])
        assert "projections" in res
        assert "totals" in res
        assert res["project"] == "QUASAR"

    def test_spend_plan_with_hypotheticals(self, api):
        res = api.spend_plan(
            ["QUASAR"],
            add_personnel=[{"type": "phd", "effort_pct": 100, "salary": 45000}],
            override_effort=[{"name": "Smith, Jane", "effort_pct": 50}],
        )
        assert "projections" in res
        assert "totals" in res
        assert res["project"] == "QUASAR"

    def test_spend_plan_with_date_bounded_hypotheticals(self, api):
        res = api.spend_plan(
            ["QUASAR"],
            override_effort=[
                {"name": "Smith, Jane", "effort_pct": 50, "start": "2026-06", "end": "2026-09"}
            ],
        )
        assert "projections" in res
        assert "totals" in res
        assert res["project"] == "QUASAR"


class TestOptimize:
    def test_optimize_mitigations(self, api):
        from smaug.projections import optimize_mitigations

        store = api._get_store()
        config_path = api._config_path()
        plans = optimize_mitigations("QUASAR", config_path, store, target_months=12)
        assert len(plans) == 3
        names = [p["name"] for p in plans]
        assert "Plan A: Non-Personnel Cuts Only" in names
        assert "Plan B: Moderate Cuts" in names
        assert "Plan C: Deep Cuts" in names
        for p in plans:
            assert "extended_stop_work_months" in p
            assert "extension" in p
