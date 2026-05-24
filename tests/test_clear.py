"""Tests for the clear CLI command."""

import shutil
from pathlib import Path
from unittest.mock import patch

import pytest

from smaug.cli._operational import cmd_clear
from smaug.store import ProjectStore


@pytest.fixture
def tmp_data_dir(tmp_path):
    """Create a temporary data directory populated with example data."""
    examples_dir = Path(__file__).parent.parent / "examples"
    shutil.copytree(examples_dir, tmp_path / "data", dirs_exist_ok=True)
    return tmp_path / "data"


class DummyArgs:
    def __init__(self, data_dir):
        self.data_dir = str(data_dir)


class TestClearCommand:
    def test_clear_with_clear_confirmation(self, tmp_data_dir):
        """Verify that typing 'CLEAR' successfully purges data files/folders."""
        # Confirm setup has files
        manifest_file = tmp_data_dir / "projects" / "manifest.yaml"
        personnel_file = tmp_data_dir / "projects" / "personnel_config.yaml"
        travel_file = tmp_data_dir / "projects" / "travel_config.yaml"
        purchases_file = tmp_data_dir / "projects" / "purchases_config.yaml"

        assert manifest_file.exists()
        assert personnel_file.exists()

        # Let's create a fake project-specific directory and a report
        proj_subdir = tmp_data_dir / "projects" / "QUASAR"
        proj_subdir.mkdir(parents=True, exist_ok=True)
        (proj_subdir / "budget_config.yaml").write_text("dummy")

        report_file = tmp_data_dir / "reports" / "sponsored" / "quasar_2025_2026.csv"
        assert report_file.exists()

        store = ProjectStore(tmp_data_dir)
        args = DummyArgs(tmp_data_dir)

        # Mock standard input to return 'CLEAR'
        with patch("builtins.input", return_value="CLEAR"):
            cmd_clear(store, args)

        # Verify configuration files have been reset/cleared
        import yaml

        with open(manifest_file) as f:
            manifest_data = yaml.safe_load(f)
        assert manifest_data["projects"] == {}
        assert manifest_data["discretionary"] == {}

        with open(personnel_file) as f:
            personnel_data = yaml.safe_load(f)
        assert personnel_data["personnel"] == []

        with open(travel_file) as f:
            travel_data = yaml.safe_load(f)
        assert travel_data["travel"] == []

        with open(purchases_file) as f:
            purchases_data = yaml.safe_load(f)
        assert purchases_data["items"] == []

        # Project directories and report files should be deleted
        assert not proj_subdir.exists()
        assert not report_file.exists()

    def test_clear_cancelled_with_other_input(self, tmp_data_dir):
        """Verify that entering anything other than 'CLEAR' does not perform deletion."""
        manifest_file = tmp_data_dir / "projects" / "manifest.yaml"
        manifest_content_before = manifest_file.read_text()

        report_file = tmp_data_dir / "reports" / "sponsored" / "quasar_2025_2026.csv"
        assert report_file.exists()

        store = ProjectStore(tmp_data_dir)
        args = DummyArgs(tmp_data_dir)

        # Mock standard input to return 'CANCEL'
        with patch("builtins.input", return_value="CANCEL"):
            cmd_clear(store, args)

        # Verify nothing was deleted
        assert manifest_file.read_text() == manifest_content_before
        assert report_file.exists()
