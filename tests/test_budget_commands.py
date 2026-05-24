"""Tests for the budget list/add/set CLI commands."""

import shutil
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import yaml

from smaug.cli._budget_commands import (
    _expand_date,
    _load_idc_rate,
    _recompute_totals,
    _resolve_budget_config_path,
    _split_total,
    cmd_budget,
)
from smaug.contractual_budget import load_contractual_budget
from smaug.store import ProjectStore

EXAMPLES_DIR = Path(__file__).parent.parent / "examples"


@pytest.fixture
def data_dir(tmp_path):
    """Copy examples into a temp directory and return its path.

    Rewrites QUASAR's budget_dir to use an absolute path so tests don't
    depend on the working directory.
    """
    dest = tmp_path / "data"
    shutil.copytree(EXAMPLES_DIR, dest, dirs_exist_ok=True)

    # Patch manifest: make budget_dir absolute so tests work from any CWD
    manifest_path = dest / "projects" / "manifest.yaml"
    with open(manifest_path) as f:
        manifest = yaml.safe_load(f)

    quasar_budget_dir = dest / "projects" / "QUASAR"
    manifest["projects"]["QUASAR"]["budget_dir"] = str(quasar_budget_dir)
    with open(manifest_path, "w") as f:
        yaml.dump(manifest, f, default_flow_style=False)

    return dest


@pytest.fixture
def store(data_dir):
    """A ProjectStore loaded from the temp data directory."""
    s = ProjectStore(data_dir=data_dir)
    s.load_all()
    return s


def _make_args(**kwargs):
    """Build a namespace-like object for argparse arguments."""
    args = MagicMock()
    for k, v in kwargs.items():
        setattr(args, k, v)
    return args


def _budget_config_path(data_dir, project="QUASAR"):
    """Return the budget_config.yaml path for QUASAR (with patched absolute budget_dir)."""
    return Path(data_dir) / "projects" / project / "budget_config.yaml"


# ──────────────────────────────────────────────────────────────
# Unit tests for helpers
# ──────────────────────────────────────────────────────────────


class TestHelpers:
    def test_expand_date_start(self):
        assert _expand_date("2028-07", is_end=False) == "2028-07-01"

    def test_expand_date_end(self):
        assert _expand_date("2029-06", is_end=True) == "2029-06-30"

    def test_expand_date_end_february(self):
        assert _expand_date("2028-02", is_end=True) == "2028-02-29"  # leap year

    def test_expand_date_already_full(self):
        assert _expand_date("2028-07-15", is_end=False) == "2028-07-15"

    def test_split_total(self):
        direct, idc = _split_total(Decimal("600000"), Decimal("0.55"))
        assert direct == Decimal("387097")
        assert idc == Decimal("212903")
        assert direct + idc == Decimal("600000")

    def test_load_idc_rate(self, data_dir):
        rate = _load_idc_rate(str(data_dir))
        assert rate == Decimal("0.55")

    def test_recompute_totals(self):
        config = {
            "by_year": {
                "year1": {"total": 450000, "direct": 290323, "idc": 159677},
                "year2": {"total": 500000, "direct": 322581, "idc": 177419},
            },
            "totals": {},
        }
        _recompute_totals(config)
        assert config["totals"]["total_budget"] == 950000
        assert config["totals"]["total_direct_costs"] == 612904
        assert config["totals"]["total_indirect_costs"] == 337096

    def test_resolve_path_with_budget_dir(self, store, data_dir):
        """QUASAR has budget_dir set — should resolve to config within it."""
        path = _resolve_budget_config_path(store, "QUASAR", str(data_dir))
        assert path is not None
        assert path.name == "budget_config.yaml"
        assert path.exists()

    def test_resolve_path_without_budget_dir(self, store, data_dir):
        """NEXUS has no budget_dir — should use default convention."""
        path = _resolve_budget_config_path(store, "NEXUS", str(data_dir))
        assert path is not None
        assert str(path).endswith("projects/NEXUS/budget_config.yaml")

    def test_resolve_path_unknown_project(self, store, data_dir):
        path = _resolve_budget_config_path(store, "NONEXISTENT", str(data_dir))
        assert path is None


# ──────────────────────────────────────────────────────────────
# budget list
# ──────────────────────────────────────────────────────────────


class TestBudgetList:
    def test_list_existing_project_runs(self, store, data_dir):
        """QUASAR has a budget_config.yaml — listing should not raise."""
        args = _make_args(action="list", project="QUASAR", data_dir=str(data_dir))
        cmd_budget(store, args)


# ──────────────────────────────────────────────────────────────
# budget add
# ──────────────────────────────────────────────────────────────


class TestBudgetAdd:
    def test_add_new_year(self, store, data_dir):
        """Adding year 4 to QUASAR should update budget_config.yaml."""
        args = _make_args(
            action="add",
            project="QUASAR",
            year=4,
            start="2028-07",
            end="2029-06",
            total=600000.0,
            direct=387097.0,
            idc=212903.0,
            data_dir=str(data_dir),
        )
        cmd_budget(store, args)

        config_path = _budget_config_path(data_dir)
        contract = load_contractual_budget(config_path)
        assert contract is not None

        year4 = contract.get_period_by_year(4)
        assert year4 is not None
        assert year4.total == Decimal("600000")
        assert year4.direct == Decimal("387097")
        assert year4.idc == Decimal("212903")

        # Cumulative totals should be updated: 450k + 500k + 550k + 600k
        assert contract.total_budget == Decimal("2100000")

    def test_add_duplicate_year_no_change(self, store, data_dir):
        """Adding an already-existing year should not modify the file."""
        config_path = _budget_config_path(data_dir)

        with open(config_path) as f:
            original = f.read()

        args = _make_args(
            action="add",
            project="QUASAR",
            year=1,
            start="2025-01",
            end="2025-12",
            total=450000.0,
            direct=None,
            idc=None,
            data_dir=str(data_dir),
        )
        cmd_budget(store, args)

        with open(config_path) as f:
            after = f.read()
        assert original == after

    def test_add_auto_split(self, store, data_dir):
        """Adding with only --total should derive direct/IDC from rates.yaml."""
        args = _make_args(
            action="add",
            project="QUASAR",
            year=4,
            start="2028-07",
            end="2029-06",
            total=600000.0,
            direct=None,
            idc=None,
            data_dir=str(data_dir),
        )
        cmd_budget(store, args)

        config_path = _budget_config_path(data_dir)
        contract = load_contractual_budget(config_path)
        assert contract is not None
        year4 = contract.get_period_by_year(4)
        assert year4 is not None

        # With IDC rate 0.55: direct = 600000 / 1.55 ≈ 387097
        assert year4.direct == Decimal("387097")
        assert year4.idc == Decimal("212903")
        assert year4.total == Decimal("600000")

    def test_add_creates_config_for_new_project(self, store, data_dir):
        """Adding to NEXUS (no budget_config.yaml) should bootstrap the file."""
        args = _make_args(
            action="add",
            project="NEXUS",
            year=1,
            start="2025-04",
            end="2026-03",
            total=375000.0,
            direct=None,
            idc=None,
            data_dir=str(data_dir),
        )
        cmd_budget(store, args)

        config_path = Path(data_dir) / "projects" / "NEXUS" / "budget_config.yaml"
        assert config_path.exists()

        contract = load_contractual_budget(config_path)
        assert contract is not None
        assert len(contract.periods) == 1
        assert contract.periods[0].year_num == 1

    def test_add_expands_dates(self, store, data_dir):
        """YYYY-MM start should expand to -01 and end to last day of month."""
        args = _make_args(
            action="add",
            project="QUASAR",
            year=4,
            start="2028-07",
            end="2029-06",
            total=600000.0,
            direct=387097.0,
            idc=212903.0,
            data_dir=str(data_dir),
        )
        cmd_budget(store, args)

        config_path = _budget_config_path(data_dir)
        with open(config_path) as f:
            raw = yaml.safe_load(f)

        period = raw["contract"]["periods"]["year4"]
        # ruamel.yaml may store as date objects; yaml.safe_load converts them
        start = str(period["start"])
        end = str(period["end"])
        assert start == "2028-07-01"
        assert end == "2029-06-30"

    def test_add_sets_budget_dir_in_manifest(self, store, data_dir):
        """Adding to NEXUS should set budget_dir in manifest.yaml."""
        args = _make_args(
            action="add",
            project="NEXUS",
            year=1,
            start="2025-04",
            end="2026-03",
            total=375000.0,
            direct=None,
            idc=None,
            data_dir=str(data_dir),
        )
        cmd_budget(store, args)

        manifest_path = Path(data_dir) / "projects" / "manifest.yaml"
        with open(manifest_path) as f:
            manifest = yaml.safe_load(f)

        assert manifest["projects"]["NEXUS"].get("budget_dir") is not None


# ──────────────────────────────────────────────────────────────
# budget set
# ──────────────────────────────────────────────────────────────


class TestBudgetSet:
    def test_set_update_total(self, store, data_dir):
        """Modifying year 2 total should update amounts and recompute totals."""
        args = _make_args(
            action="set",
            project="QUASAR",
            year=2,
            total=520000.0,
            direct=None,
            idc=None,
            start=None,
            end=None,
            data_dir=str(data_dir),
        )
        cmd_budget(store, args)

        config_path = _budget_config_path(data_dir)
        contract = load_contractual_budget(config_path)
        assert contract is not None
        year2 = contract.get_period_by_year(2)
        assert year2 is not None
        assert year2.total == Decimal("520000")

        # Cumulative total: 450k + 520k + 550k = 1520k
        assert contract.total_budget == Decimal("1520000")

    def test_set_nonexistent_year_no_change(self, store, data_dir):
        """Setting a nonexistent year should not modify the file."""
        config_path = _budget_config_path(data_dir)
        with open(config_path) as f:
            original = f.read()

        args = _make_args(
            action="set",
            project="QUASAR",
            year=99,
            total=100000.0,
            direct=None,
            idc=None,
            start=None,
            end=None,
            data_dir=str(data_dir),
        )
        cmd_budget(store, args)

        with open(config_path) as f:
            after = f.read()
        assert original == after

    def test_set_explicit_direct_idc(self, store, data_dir):
        """Setting with explicit direct and IDC should use those values."""
        args = _make_args(
            action="set",
            project="QUASAR",
            year=1,
            total=460000.0,
            direct=300000.0,
            idc=160000.0,
            start=None,
            end=None,
            data_dir=str(data_dir),
        )
        cmd_budget(store, args)

        config_path = _budget_config_path(data_dir)
        contract = load_contractual_budget(config_path)
        assert contract is not None
        year1 = contract.get_period_by_year(1)
        assert year1 is not None
        assert year1.total == Decimal("460000")
        assert year1.direct == Decimal("300000")
        assert year1.idc == Decimal("160000")

    def test_set_no_amount_no_change(self, store, data_dir):
        """Setting without any amount flags should not modify the file."""
        config_path = _budget_config_path(data_dir)
        with open(config_path) as f:
            original = f.read()

        args = _make_args(
            action="set",
            project="QUASAR",
            year=1,
            total=None,
            direct=None,
            idc=None,
            start=None,
            end=None,
            data_dir=str(data_dir),
        )
        cmd_budget(store, args)

        with open(config_path) as f:
            after = f.read()
        assert original == after

    def test_set_no_config_does_not_create(self, store, data_dir):
        """Setting on a project with no budget_config.yaml should not create one."""
        config_path = Path(data_dir) / "projects" / "NEXUS" / "budget_config.yaml"
        assert not config_path.exists()

        args = _make_args(
            action="set",
            project="NEXUS",
            year=1,
            total=100000.0,
            direct=None,
            idc=None,
            start=None,
            end=None,
            data_dir=str(data_dir),
        )
        cmd_budget(store, args)

        assert not config_path.exists()
