import shutil
from decimal import Decimal
from pathlib import Path

import pytest
import yaml

from smaug.api import SmaugAPI
from smaug.audit import FindingType
from smaug.cli._util import Anonymizer, resolve_personnel_name
from smaug.models import EffortAllocation, EmployeeType

EXAMPLES_DIR = Path(__file__).parent.parent / "examples"


@pytest.fixture
def temp_store_api(tmp_path):
    """SmaugAPI pointed at an isolated mutable copy of examples."""
    dest = tmp_path / "data"
    shutil.copytree(EXAMPLES_DIR, dest, dirs_exist_ok=True)
    return SmaugAPI(dest)


class TestAssignmentSegmentsDisambiguation:
    """Issue 1: set_assignment_end segment targeting and disambiguation."""

    def test_multi_segment_without_start_errors(self, temp_store_api, tmp_path):
        """When a person has multiple segments on a project, omitting start_date must error."""
        # Add multiple segments for Smith, Jane on QUASAR in config
        config_path = Path(temp_store_api.data_dir) / "projects" / "personnel_config.yaml"
        with open(config_path) as f:
            data = yaml.safe_load(f)

        for p in data["personnel"]:
            if p["name"] == "Smith, Jane":
                p["assignments"] = [
                    {"project": "QUASAR", "effort": 0.1, "start": "2024-09", "end": "2025-06"},
                    {"project": "QUASAR", "effort": 0.2, "start": "2025-07", "end": "2026-06"},
                ]
        with open(config_path, "w") as f:
            yaml.dump(data, f)

        res = temp_store_api.set_assignment_end("Smith, Jane", "QUASAR", "2026-12")
        assert "error" in res
        assert "Multiple assignment segments found" in res["error"]
        assert "specify 'start'" in res["error"]

    def test_multi_segment_with_start_updates_exact_segment(self, temp_store_api):
        """Providing start_date modifies only the targeted segment."""
        config_path = Path(temp_store_api.data_dir) / "projects" / "personnel_config.yaml"
        with open(config_path) as f:
            data = yaml.safe_load(f)

        for p in data["personnel"]:
            if p["name"] == "Smith, Jane":
                p["assignments"] = [
                    {"project": "QUASAR", "effort": 0.1, "start": "2024-09", "end": "2025-06"},
                    {"project": "QUASAR", "effort": 0.2, "start": "2025-07", "end": "2026-06"},
                ]
        with open(config_path, "w") as f:
            yaml.dump(data, f)

        res = temp_store_api.set_assignment_end(
            "Smith, Jane", "QUASAR", "2026-12", start_date="2024-09"
        )
        assert res.get("success") is True
        assert "assignments" in res
        assignments = res["assignments"]
        assert len(assignments) == 2

        seg1 = next(a for a in assignments if a.get("start") == "2024-09")
        seg2 = next(a for a in assignments if a.get("start") == "2025-07")
        assert seg1["end"] == "2026-12"
        assert seg2["end"] == "2026-06"  # Untouched

    def test_single_segment_updates_without_start(self, temp_store_api):
        """Single segment assignment can be updated without start_date."""
        res = temp_store_api.set_assignment_end("Chen, Wei", "QUASAR", "2027-01")
        assert res.get("success") is True
        assert "assignments" in res
        assert any(a.get("end") == "2027-01" for a in res["assignments"])


class TestPersonnelNameResolution:
    """Issue 2: Exact matching and candidate list constraint."""

    def test_exact_match_short_circuits_anonymizer(self):
        """Exact match in candidate list must not be mangled by anonymizer mappings."""
        Anonymizer.enabled = True
        Anonymizer._anon_to_real = {"PhD 1": "Someone Else"}
        Anonymizer._real_to_anon = {"Someone Else": "PhD 1"}

        candidates = ["PhD 1", "PhD 2", "Faculty 1"]
        resolved, err = resolve_personnel_name("PhD 1", candidates)
        assert err is None
        assert resolved == "PhD 1"

        Anonymizer.enabled = False

    def test_resolver_never_returns_name_outside_candidates(self):
        """Resolver must only return names that exist in the candidate list."""
        candidates = ["Smith, Jane", "Doe, John", "Robbie"]
        resolved, err = resolve_personnel_name("Nonexistent", candidates)
        assert resolved is None
        assert err is not None
        assert "No personnel found" in err

    def test_case_insensitive_exact_match(self):
        """Case variations of candidates match directly."""
        candidates = ["Smith, Jane", "Doe, John"]
        resolved, err = resolve_personnel_name("smith, jane", candidates)
        assert err is None
        assert resolved == "Smith, Jane"


class TestBudgetPreservation:
    """Issue 3: Budget preservation in project_status and dump_project."""

    def test_project_status_with_manifest_total_budget(self, temp_store_api):
        """project_status returns non-null budget, remaining, pct_remaining when manifest has total_budget."""
        # Ensure project has total_budget in manifest
        status = temp_store_api.project_status("QUASAR")
        assert status.get("budget") is not None
        assert status["budget"]["total_budget"] is not None
        assert float(status["budget"]["total_budget"]) > 0
        assert status.get("remaining") is not None
        assert status.get("pct_remaining") is not None

    def test_dump_project_includes_total_budget(self, temp_store_api):
        """dump_project serializes total_budget in project metadata and budget block."""
        dumped = temp_store_api.dump_project("QUASAR")
        assert dumped.get("project", {}).get("total_budget") is not None
        assert dumped.get("budget") is not None
        assert dumped["budget"]["total_budget"] is not None


class TestStateOfPlayAllocationsAndHeadcount:
    """Issue 4, 5, 6, 7: Allocations, active status, headcount, and runway formatting."""

    def test_multi_segment_in_current_allocations(self, temp_store_api):
        """All segments for a person must appear in current_allocations."""
        config_path = Path(temp_store_api.data_dir) / "projects" / "personnel_config.yaml"
        with open(config_path) as f:
            data = yaml.safe_load(f)

        for p in data["personnel"]:
            if p["name"] == "Smith, Jane":
                p["assignments"] = [
                    {"project": "QUASAR", "effort": 0.1, "start": "2024-09", "end": "2025-06"},
                    {"project": "QUASAR", "effort": 0.5, "start": "2026-01", "end": "2028-06"},
                ]
            if p["name"] == "Doe, John":
                p["assignments"] = [
                    {"project": "QUASAR", "effort": 0.0, "start": "2024-01", "end": "2028-01"},
                ]
        with open(config_path, "w") as f:
            yaml.dump(data, f)

        sop = temp_store_api.project_state_of_play("QUASAR")
        allocs = sop["personnel"]["current_allocations"]

        smith_allocs = [a for a in allocs if "Smith" in a["name"] or "Faculty" in a["name"]]
        assert len(smith_allocs) == 2

        # Expired segment must have is_active_now: False
        past_seg = next(a for a in smith_allocs if a["assignment_start"] == "2024-09")
        assert past_seg["is_active_now"] is False

        # Zero effort must have is_active_now: False
        doe_allocs = [a for a in allocs if "Doe" in a["name"] or "Postdoc" in a["name"]]
        if doe_allocs:
            assert doe_allocs[0]["is_active_now"] is False

        # active_headcount must count unique persons with effort > 0
        assert sop["personnel"]["active_headcount"] >= 1

    def test_runway_warning_negative_months(self, temp_store_api, monkeypatch):
        """When stop work month is in the past, warning text must say 'ran out X months ago'."""

        # Mock stopwork forecast to return past date
        def mock_stopwork(project):
            return {"stop_month": "2025-01", "stop_day": "2025-01-15"}

        monkeypatch.setattr(temp_store_api, "stopwork_forecast", mock_stopwork)
        sop = temp_store_api.project_state_of_play("QUASAR")
        warnings = sop["warnings"]
        assert any("Funding ran out" in w for w in warnings)
        assert not any("Funding is projected to run out in 0 months" in w for w in warnings)


class TestProjectEndValidation:
    """Issue 8: Validation when project end date precedes commitments."""

    def test_set_project_end_emits_warnings(self, temp_store_api):
        """Setting project end before assignments/commitments returns warnings."""
        res = temp_store_api.set_project_end("QUASAR", "2025-01")
        assert res.get("success") is True
        assert "warnings" in res
        assert len(res["warnings"]) > 0
        assert any("assignment on QUASAR ends" in w or "precedes" in w for w in res["warnings"])


class TestAuditAliases:
    """Issue 9: Audit alias resolution."""

    def test_audit_resolves_aliases(self, temp_store_api):
        """Payroll names mapped in aliases.yaml are recognized in audit."""
        # Create an alias mapping
        aliases_path = Path(temp_store_api.data_dir) / "projects" / "aliases.yaml"
        with open(aliases_path, "w") as f:
            yaml.dump({"aliases": {"Payroll Alias Name": "Smith, Jane"}}, f)

        # Add allocation with alias name to tracker
        store = temp_store_api._get_store()
        tracker = store.get_personnel_tracker()
        tracker.add_allocation(
            EffortAllocation(
                person_name="Payroll Alias Name",
                project_id="QUASAR",
                period="January 2026",
                salary_amount=Decimal("1000.00"),
                employee_type=EmployeeType.FACULTY,
            )
        )

        res = temp_store_api.audit(project="QUASAR", months=1)
        # Should not flag "Payroll Alias Name" as "person not in config"
        not_in_config = [
            f
            for f in res.get("findings", [])
            if f.get("type") == FindingType.UNEXPECTED_IN_REPORT.value
            and ("Payroll Alias" in f.get("message", "") or "Payroll Alias" in f.get("person", ""))
        ]
        assert len(not_in_config) == 0


class TestUnifiedBudgetResolution:
    """Tests for unified budget resolution across tools."""

    def test_budget_resolution_sources(self, temp_store_api):
        from smaug.budget_resolution import resolve_project_budget

        store = temp_store_api._get_store()
        # Set up a contractual budget for a test project
        project_dir = Path(temp_store_api.data_dir) / "projects" / "TEST_PROJ"
        project_dir.mkdir(parents=True, exist_ok=True)
        budget_cfg = project_dir / "budget_config.yaml"
        with open(budget_cfg, "w") as f:
            yaml.dump(
                {
                    "award_id": "AWD-12345",
                    "periods": [
                        {
                            "year": 1,
                            "start": "2026-01",
                            "end": "2026-12",
                            "direct": 100000,
                            "idc": 55000,
                            "total": 155000,
                        },
                        {
                            "year": 2,
                            "start": "2027-01",
                            "end": "2027-12",
                            "direct": 100000,
                            "idc": 55000,
                            "total": 155000,
                        },
                    ],
                },
                f,
            )

        # Add project to store manifest
        manifest_path = Path(temp_store_api.data_dir) / "projects" / "manifest.yaml"
        with open(manifest_path) as f:
            manifest = yaml.safe_load(f)
        manifest.setdefault("projects", {})["TEST_PROJ"] = {
            "name": "Test Project",
            "pi": "Smith, Jane",
            "status": "active",
        }
        with open(manifest_path, "w") as f:
            yaml.dump(manifest, f)

        store = temp_store_api._get_store()
        store.load_manifest()

        budget_amt, source = resolve_project_budget(store, "TEST_PROJ", temp_store_api.data_dir)
        assert budget_amt == Decimal("310000")
        assert source == "contractual_budget"

    def test_budget_vs_actuals_with_contractual_yaml(self, temp_store_api):
        # Create project with budget_config.yaml
        project_dir = Path(temp_store_api.data_dir) / "projects" / "ARTS"
        project_dir.mkdir(parents=True, exist_ok=True)
        budget_cfg = project_dir / "budget_config.yaml"
        with open(budget_cfg, "w") as f:
            yaml.dump(
                {
                    "award_id": "X100001",
                    "periods": [
                        {
                            "year": 1,
                            "start": "2024-02",
                            "end": "2025-01",
                            "direct": 500000,
                            "idc": 275000,
                            "total": 775000,
                        },
                        {
                            "year": 2,
                            "start": "2025-02",
                            "end": "2026-01",
                            "direct": 500000,
                            "idc": 275000,
                            "total": 775000,
                        },
                    ],
                },
                f,
            )

        manifest_path = Path(temp_store_api.data_dir) / "projects" / "manifest.yaml"
        with open(manifest_path) as f:
            manifest = yaml.safe_load(f)
        manifest.setdefault("projects", {})["ARTS"] = {
            "name": "ARTS Project",
            "pi": "Smith, Jane",
            "status": "active",
        }
        with open(manifest_path, "w") as f:
            yaml.dump(manifest, f)

        # Re-create API to reload store
        api = SmaugAPI(temp_store_api.data_dir)
        res = api.budget_vs_actuals("ARTS")
        assert "error" not in res
        assert res["award_id"] == "X100001"
        assert res["total_budget"] == 1550000.0

        # dump_project should also return populated budget
        dump = api.dump_project("ARTS")
        assert dump["budget"] is not None
        assert float(dump["budget"]["total_budget"]) == 1550000.0
