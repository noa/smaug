"""Tests for MCP write command edge cases.

Covers the bugs where write tools returned {"success": true} but
didn't actually modify the config, or hung indefinitely.
"""

import shutil
from pathlib import Path

import pytest
import yaml

from smaug.api import SmaugAPI

EXAMPLES_DIR = Path(__file__).parent.parent / "examples"


@pytest.fixture
def temp_api(tmp_path):
    """SmaugAPI pointed at a mutable copy of the examples directory."""
    shutil.copytree(EXAMPLES_DIR, tmp_path / "data", dirs_exist_ok=True)
    return SmaugAPI(tmp_path / "data")


def _read_personnel_config(api: SmaugAPI) -> dict:
    """Read the raw YAML config for verification."""
    config_path = Path(api.data_dir) / "projects" / "personnel_config.yaml"
    with open(config_path) as f:
        return yaml.safe_load(f)  # type: ignore[no-any-return]


class TestSetEffortZero:
    """Bug: setting effort to 0% returned success but didn't write."""

    def test_set_effort_zero_pct_succeeds(self, temp_api):
        """Setting effort to 0% should actually write 0.0 to the config."""
        res = temp_api.set_personnel_effort("Smith, Jane", "QUASAR", 0.0)
        assert res.get("success") is True

        # Verify the YAML was actually modified
        config = _read_personnel_config(temp_api)
        person = next(p for p in config["personnel"] if p["name"] == "Smith, Jane")
        quasar_assignment = next(a for a in person["assignments"] if a["project"] == "QUASAR")
        assert quasar_assignment["effort"] == 0.0

    def test_set_effort_zero_from_percentage(self, temp_api):
        """Setting effort to 0 (as percentage) should write 0.0."""
        res = temp_api.set_personnel_effort("Smith, Jane", "QUASAR", 0)
        assert res.get("success") is True

        config = _read_personnel_config(temp_api)
        person = next(p for p in config["personnel"] if p["name"] == "Smith, Jane")
        quasar_assignment = next(a for a in person["assignments"] if a["project"] == "QUASAR")
        assert quasar_assignment["effort"] == 0.0


class TestSetEffortErrorReporting:
    """Bug: errors were silently swallowed, returning success."""

    def test_invalid_name_returns_error(self, temp_api):
        """Setting effort for nonexistent person should return error, not success."""
        res = temp_api.set_personnel_effort("Nonexistent, Person", "QUASAR", 50.0)
        assert "error" in res
        assert res.get("success") is not True

    def test_invalid_project_still_adds(self, temp_api):
        """Setting effort on a new project creates a new assignment."""
        res = temp_api.set_personnel_effort("Smith, Jane", "NEWPROJ", 50.0)
        # This should create a new assignment (the CLI allows adding assignments
        # to projects not in the manifest — it's a config-level operation)
        assert res.get("success") is True

    def test_error_includes_message(self, temp_api):
        """Error responses should include a descriptive message."""
        res = temp_api.set_personnel_effort("ZZZZZ", "QUASAR", 50.0)
        assert "error" in res
        assert isinstance(res["error"], str)
        assert len(res["error"]) > 0


class TestSetAssignmentEnd:
    """Bug: set_assignment_end would hang or return success without change."""

    def test_set_end_date(self, temp_api):
        """Setting an end date should actually modify the config."""
        res = temp_api.set_assignment_end("Smith, Jane", "QUASAR", "2026-06")
        assert res.get("success") is True

        config = _read_personnel_config(temp_api)
        person = next(p for p in config["personnel"] if p["name"] == "Smith, Jane")
        quasar_assignment = next(a for a in person["assignments"] if a["project"] == "QUASAR")
        assert quasar_assignment["end"] == "2026-06"

    def test_clear_end_date(self, temp_api):
        """Clearing an end date with 'none' should remove the field."""
        # First set an end date
        temp_api.set_assignment_end("Smith, Jane", "QUASAR", "2026-06")
        # Then clear it
        res = temp_api.set_assignment_end("Smith, Jane", "QUASAR", "none")
        assert res.get("success") is True

        config = _read_personnel_config(temp_api)
        person = next(p for p in config["personnel"] if p["name"] == "Smith, Jane")
        quasar_assignment = next(a for a in person["assignments"] if a["project"] == "QUASAR")
        assert "end" not in quasar_assignment

    def test_invalid_name_returns_error(self, temp_api):
        """Setting end date for nonexistent person should return error."""
        res = temp_api.set_assignment_end("Nobody", "QUASAR", "2026-06")
        assert "error" in res


class TestCacheInvalidation:
    """Bug: stale cached store returned old data after writes."""

    def test_effort_change_reflected_in_subsequent_read(self, temp_api):
        """After set_personnel_effort, personnel_overview should show new value."""
        # Set effort to 50%
        res = temp_api.set_personnel_effort("Smith, Jane", "QUASAR", 50.0)
        assert res.get("success") is True

        # Read back via a different API method on the SAME instance
        overview = temp_api.personnel_overview()
        person = next(p for p in overview["personnel"] if "Smith" in p["name"])
        quasar = next(a for a in person["assignments"] if a["project"] == "QUASAR")
        assert quasar["effort"] == 0.5

    def test_salary_change_reflected_in_subsequent_read(self, temp_api):
        """After set_salary, personnel_overview should show the new salary."""
        res = temp_api.set_salary("Smith, Jane", 200000)
        assert res.get("success") is True

        overview = temp_api.personnel_overview()
        person = next(p for p in overview["personnel"] if "Smith" in p["name"])
        # Should reflect the new salary
        assert person["annual_salary"] == 200000


class TestSetDeparture:
    """Test set_departure error handling."""

    def test_set_departure_succeeds(self, temp_api):
        res = temp_api.set_departure("Smith, Jane", "2028-06")
        assert res.get("success") is True

        config = _read_personnel_config(temp_api)
        person = next(p for p in config["personnel"] if p["name"] == "Smith, Jane")
        assert person["departure"] == "2028-06"

    def test_invalid_name_returns_error(self, temp_api):
        res = temp_api.set_departure("Nobody", "2028-06")
        assert "error" in res


class TestAddPersonnel:
    """Test add_personnel error handling."""

    def test_duplicate_name_returns_error(self, temp_api):
        """Adding a person who already exists should return error, not success."""
        res = temp_api.add_personnel("Smith, Jane", "postdoc", "QUASAR", 100.0, salary=80000)
        assert "error" in res, "Should have returned error for duplicate name"

    def test_invalid_type_returns_error(self, temp_api):
        """Adding with an invalid person type should return error."""
        res = temp_api.add_personnel("New, Person", "invalid_type", "QUASAR", 100.0, salary=80000)
        assert "error" in res

    def test_add_new_person_succeeds(self, temp_api):
        """Adding a genuinely new person should succeed and write to config."""
        res = temp_api.add_personnel("Brand, New", "postdoc", "QUASAR", 100.0, salary=80000)
        assert res.get("success") is True

        config = _read_personnel_config(temp_api)
        person = next((p for p in config["personnel"] if p["name"] == "Brand, New"), None)
        assert person is not None
        assert person["type"] == "postdoc"
        assert person["annual_salary"] == 80000


class TestStructuredResponses:
    """Write tools should return structured details, not just success: true."""

    def test_set_effort_returns_details(self, temp_api):
        res = temp_api.set_personnel_effort("Smith, Jane", "QUASAR", 25.0)
        assert res["success"] is True
        assert res["name"] == "Smith, Jane"
        assert res["project"] == "QUASAR"
        assert res["effort_pct"] == 25.0

    def test_set_salary_returns_details(self, temp_api):
        res = temp_api.set_salary("Smith, Jane", 200000)
        assert res["success"] is True
        assert res["name"] == "Smith, Jane"
        assert res["salary"] == 200000

    def test_set_assignment_end_returns_details(self, temp_api):
        res = temp_api.set_assignment_end("Smith, Jane", "QUASAR", "2027-06")
        assert res["success"] is True
        assert res["name"] == "Smith, Jane"
        assert res["end_date"] == "2027-06"

    def test_set_departure_returns_details(self, temp_api):
        res = temp_api.set_departure("Smith, Jane", "2028-06")
        assert res["success"] is True
        assert res["departure_date"] == "2028-06"

    def test_set_personnel_type_returns_details(self, temp_api):
        res = temp_api.set_personnel_type("Smith, Jane", "faculty")
        assert res["success"] is True
        assert res["name"] == "Smith, Jane"
        assert res["type"] == "faculty"


@pytest.fixture
def anon_api(tmp_path):
    """SmaugAPI with anonymization enabled, pointed at a mutable copy of examples."""
    shutil.copytree(EXAMPLES_DIR, tmp_path / "data", dirs_exist_ok=True)
    return SmaugAPI(tmp_path / "data", anonymize=True)


class TestAnonymizationPrivacy:
    """Bug: error messages leaked real names when anonymization was enabled.

    When an MCP agent called set_assignment_end("PhD 1", "ARTS", "2026-06"),
    the error message returned "Person 'Mahapatra, Aurosweta' not found in config"
    — exposing the real identity behind the anonymized label.
    """

    def _get_real_names(self, api: SmaugAPI) -> list[str]:
        """Get all real personnel names from the config."""
        from smaug.cli._util import Anonymizer

        return list(Anonymizer._real_to_anon.keys())

    def test_error_messages_never_contain_real_names(self, anon_api):
        """Error responses must use anonymized names, not real ones."""
        from smaug.cli._util import Anonymizer

        real_names = self._get_real_names(anon_api)
        assert len(real_names) > 0, "Anonymizer should have mapped some names"

        # Pick a real name and its anonymized label
        real_name = real_names[0]
        anon_name = Anonymizer.anonymize(real_name)
        assert anon_name != real_name, "Anonymization should change the name"

        # Try an operation that will fail — the error message must NOT
        # contain the real name, only the anonymized one
        res = anon_api.set_assignment_end(anon_name, "NONEXISTENT_PROJECT", "2026-06")
        error_msg = res.get("error", "")
        assert real_name not in error_msg, f"Real name '{real_name}' leaked in error: {error_msg}"

    def test_set_effort_error_scrubs_real_names(self, anon_api):
        """set_personnel_effort errors must not leak real names."""

        real_names = self._get_real_names(anon_api)

        # Use a totally invalid name — error should not contain any real names
        res = anon_api.set_personnel_effort("ZZZZZ_INVALID", "QUASAR", 50.0)
        assert "error" in res
        for real_name in real_names:
            assert real_name not in res["error"], (
                f"Real name '{real_name}' leaked in error: {res['error']}"
            )

    def test_successful_write_scrubs_real_names(self, anon_api):
        """Even success responses must not contain real names."""
        from smaug.cli._util import Anonymizer

        real_names = self._get_real_names(anon_api)
        first_anon = Anonymizer.anonymize(real_names[0])

        res = anon_api.set_personnel_effort(first_anon, "QUASAR", 25.0)
        # Check all string values in the result
        result_str = str(res)
        for real_name in real_names:
            assert real_name not in result_str, (
                f"Real name '{real_name}' leaked in result: {result_str}"
            )

    def test_multi_match_error_scrubs_names(self, anon_api):
        """Fuzzy match errors listing multiple candidates must use anonymized names."""

        real_names = self._get_real_names(anon_api)

        # Use a very short query that might match multiple people
        res = anon_api.set_departure(",", "2028-06")
        if "error" in res:
            for real_name in real_names:
                assert real_name not in res["error"], (
                    f"Real name '{real_name}' leaked in multi-match error: {res['error']}"
                )
