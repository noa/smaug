"""
Tests for personnel name anonymization and privacy features.
"""

import os
from pathlib import Path

import pytest

from smaug.api import SmaugAPI
from smaug.cli._util import Anonymizer, resolve_personnel_name
from smaug.store import ProjectStore

EXAMPLES_DIR = Path(__file__).parent.parent / "examples"


@pytest.fixture(autouse=True)
def reset_anonymizer():
    """Ensure Anonymizer is reset before/after each test."""
    Anonymizer.enabled = False
    Anonymizer._real_to_anon = {}
    Anonymizer._anon_to_real = {}
    original_env = os.environ.get("SMAUG_ANONYMIZE")
    yield
    Anonymizer.enabled = False
    Anonymizer._real_to_anon = {}
    Anonymizer._anon_to_real = {}
    if original_env is not None:
        os.environ["SMAUG_ANONYMIZE"] = original_env
    elif "SMAUG_ANONYMIZE" in os.environ:
        del os.environ["SMAUG_ANONYMIZE"]


class TestAnonymizer:
    """Tests for core Anonymizer utility and mappings."""

    def test_disabled_by_default(self):
        """Verify Anonymizer starts disabled and returns inputs as-is."""
        assert not Anonymizer.enabled
        assert Anonymizer.anonymize("Smith, John") == "Smith, John"
        assert Anonymizer.resolve("PhD 1") == "PhD 1"

    def test_stable_anonymization(self):
        """Verify stable role-based mappings when initialized."""
        store = ProjectStore(EXAMPLES_DIR)
        store.load_all()

        class DummyArgs:
            anonymize = True

        Anonymizer.init(store, DummyArgs())
        assert Anonymizer.enabled

        # Since it is sorted alphabetically, "Smith, John" or others should map consistently
        # Let's inspect some of the generated mapping keys
        assert len(Anonymizer._real_to_anon) > 0
        for real_name, anon_name in Anonymizer._real_to_anon.items():
            assert anon_name in Anonymizer._anon_to_real
            assert Anonymizer._anon_to_real[anon_name] == real_name

    def test_hypotheticals_exempt(self):
        """Verify hypothetical descriptions are left unchanged."""
        Anonymizer.enabled = True
        hypo = "[Hypothetical PhD #1]"
        assert Anonymizer.anonymize(hypo) == hypo

    def test_dynamic_fallback(self):
        """Verify unseen or dynamic names get anonymized on the fly."""
        Anonymizer.enabled = True
        Anonymizer._anon_to_real = {}
        Anonymizer._real_to_anon = {}

        assert Anonymizer.anonymize("Staff Member") == "Staff 1"
        assert Anonymizer.anonymize("New Faculty Person") == "Faculty 1"
        assert Anonymizer.anonymize("Some Grad Student") == "PhD 1"
        assert Anonymizer.anonymize("Unknown Entity") == "Person 1"

    def test_bidirectional_resolve_personnel_name(self):
        """Verify resolve_personnel_name supports bidirectional lookup."""
        store = ProjectStore(EXAMPLES_DIR)
        store.load_all()

        class DummyArgs:
            anonymize = True

        Anonymizer.init(store, DummyArgs())

        real_names = list(Anonymizer._real_to_anon.keys())
        assert len(real_names) > 0

        # Test finding real name from anonymized name
        anon_name = Anonymizer._real_to_anon[real_names[0]]
        resolved, error = resolve_personnel_name(anon_name, real_names)
        assert error is None
        assert resolved == real_names[0]

        # Case-insensitive & space-insensitive resolve
        resolved_ci, error_ci = resolve_personnel_name(
            anon_name.lower().replace(" ", ""), real_names
        )
        assert error_ci is None
        assert resolved_ci == real_names[0]


class TestSmaugAPIAnonymization:
    """Tests for SmaugAPI anonymization integration."""

    def test_api_with_anonymization(self):
        """Verify API anonymizes personnel names in dict responses."""
        api = SmaugAPI(EXAMPLES_DIR, anonymize=True)
        assert Anonymizer.enabled

        # Test project status PI name
        status = api.project_status("QUASAR")
        assert "project" in status
        pi_name = status["project"]["pi"]
        assert (
            pi_name.startswith("Faculty")
            or pi_name.startswith("PhD")
            or pi_name.startswith("Postdoc")
            or pi_name.startswith("Staff")
            or pi_name.startswith("Person")
        )

        # Test spending report personnel totals keys
        report = api.spending_report("QUASAR")
        for key in report["personnel_totals"]:
            assert (
                key.startswith("Faculty")
                or key.startswith("PhD")
                or key.startswith("Postdoc")
                or key.startswith("Staff")
                or key.startswith("Person")
            )

        # Test spending projections personnel keys
        proj = api.spending_projection("QUASAR", months=1)
        for p in proj["projections"][0]["personnel"]:
            name = p["name"]
            assert (
                name.startswith("Faculty")
                or name.startswith("PhD")
                or name.startswith("Postdoc")
                or name.startswith("Staff")
                or name.startswith("Person")
            )

    def test_env_variable_activation(self):
        """Verify SMAUG_ANONYMIZE=1 activates anonymization by default."""
        os.environ["SMAUG_ANONYMIZE"] = "1"
        _api = SmaugAPI(EXAMPLES_DIR)
        assert Anonymizer.enabled

    def test_env_variable_disabled(self):
        """Verify SMAUG_ANONYMIZE=0 overrides anonymize settings to disable."""
        os.environ["SMAUG_ANONYMIZE"] = "0"
        _api = SmaugAPI(EXAMPLES_DIR, anonymize=True)
        assert not Anonymizer.enabled
