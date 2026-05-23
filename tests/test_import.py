"""Tests for the report import CLI command."""

import shutil
import tempfile
from pathlib import Path

import pytest

from smaug.cli._import import _collect_report_files, _import_single_file
from smaug.parsers import discover_parsers
from smaug.store import ProjectStore

EXAMPLES_DIR = Path(__file__).parent.parent / "examples"
FIXTURES_CSV = EXAMPLES_DIR / "reports" / "sponsored" / "quasar_2025_2026.csv"


@pytest.fixture
def tmp_data_dir(tmp_path):
    """Create a minimal data directory with manifest and rates."""
    # Copy the example data directory structure
    shutil.copytree(EXAMPLES_DIR, tmp_path / "data", dirs_exist_ok=True)
    return tmp_path / "data"


@pytest.fixture
def report_parsers():
    """Discover available report parsers."""
    parsers, _ = discover_parsers()
    return parsers


class TestCollectReportFiles:
    """Test file collection from paths."""

    def test_single_csv_file(self):
        files = _collect_report_files(FIXTURES_CSV)
        assert len(files) == 1
        assert files[0] == FIXTURES_CSV

    def test_directory_finds_csvs(self):
        files = _collect_report_files(EXAMPLES_DIR / "reports" / "sponsored")
        assert len(files) == 2
        names = {f.name for f in files}
        assert "quasar_2025_2026.csv" in names
        assert "nexus_2025_2026.csv" in names

    def test_empty_directory(self, tmp_path):
        empty = tmp_path / "empty"
        empty.mkdir()
        files = _collect_report_files(empty)
        assert files == []

    def test_nonexistent_path(self, tmp_path):
        files = _collect_report_files(tmp_path / "does_not_exist.csv")
        assert files == []


class TestImportSingleFile:
    """Test importing individual report files."""

    def test_import_valid_csv(self, tmp_path, report_parsers):
        target = tmp_path / "reports" / "sponsored"
        result = _import_single_file(FIXTURES_CSV, target, report_parsers)

        assert result["status"] == "imported"
        assert result["project_id"] == "QUASAR"
        assert result["period"] == "March 2026"
        assert (target / "quasar_2025_2026.csv").exists()

    def test_dry_run_does_not_copy(self, tmp_path, report_parsers):
        target = tmp_path / "reports" / "sponsored"
        result = _import_single_file(FIXTURES_CSV, target, report_parsers, dry_run=True)

        assert result["status"] == "would_import"
        assert result["project_id"] == "QUASAR"
        assert not (target / "quasar_2025_2026.csv").exists()

    def test_duplicate_skipped(self, tmp_path, report_parsers):
        target = tmp_path / "reports" / "sponsored"
        # Import once
        _import_single_file(FIXTURES_CSV, target, report_parsers)
        # Import again
        result = _import_single_file(FIXTURES_CSV, target, report_parsers)

        assert result["status"] == "skipped"
        assert "Already exists" in result["message"]

    def test_duplicate_with_force(self, tmp_path, report_parsers):
        target = tmp_path / "reports" / "sponsored"
        # Import once
        _import_single_file(FIXTURES_CSV, target, report_parsers)
        # Import again with force
        result = _import_single_file(FIXTURES_CSV, target, report_parsers, force=True)

        assert result["status"] == "imported"

    def test_same_file_in_place_skipped(self, report_parsers):
        """Importing a file from the target dir itself should be skipped."""
        target = FIXTURES_CSV.parent
        result = _import_single_file(FIXTURES_CSV, target, report_parsers)

        assert result["status"] == "skipped"
        assert "already in the data directory" in result["message"]

    def test_unparseable_file_rejected(self, tmp_path, report_parsers):
        # Create a junk file
        junk = tmp_path / "garbage.csv"
        junk.write_text("this,is,not,a,report\n1,2,3,4\n")
        target = tmp_path / "reports" / "sponsored"

        result = _import_single_file(junk, target, report_parsers)
        assert result["status"] == "error"
        assert "No parser" in result["message"]

    def test_validation_warnings_collected(self, tmp_path, report_parsers):
        """The QUASAR CSV has a category sum mismatch warning."""
        target = tmp_path / "reports" / "sponsored"
        result = _import_single_file(FIXTURES_CSV, target, report_parsers)

        # Should still import (warnings don't block), but warnings should be present
        assert result["status"] == "imported"
        assert "warnings" in result
        assert any("Category sum" in w for w in result["warnings"])


class TestImportedReportsLoadCorrectly:
    """Verify that imported reports are picked up by ProjectStore."""

    def test_imported_csv_appears_in_store(self, tmp_data_dir, report_parsers):
        """Import a CSV into the data dir, then verify the store loads it."""
        target = tmp_data_dir / "reports" / "sponsored"

        # The example already has the CSV, but let's import from a temp copy
        with tempfile.TemporaryDirectory() as staging:
            staging_csv = Path(staging) / "quasar_copy.csv"
            shutil.copy2(FIXTURES_CSV, staging_csv)

            result = _import_single_file(staging_csv, target, report_parsers)
            assert result["status"] == "imported"

        # Now load the store and check
        store = ProjectStore(data_dir=str(tmp_data_dir))
        store.load_all()

        data = store.get_project("QUASAR")
        assert data is not None
        assert len(data.spending) > 0

        # The imported copy should contribute reports
        periods = {r.period for r in data.spending}
        assert "March 2026" in periods


class TestBatchImport:
    """Test importing from a directory."""

    def test_batch_import_directory(self, tmp_path, report_parsers):
        target = tmp_path / "reports" / "sponsored"

        # Import the whole sponsored directory
        source_dir = EXAMPLES_DIR / "reports" / "sponsored"
        files = _collect_report_files(source_dir)
        results = []
        for f in files:
            results.append(_import_single_file(f, target, report_parsers))

        assert len(results) == 2
        assert all(r["status"] == "imported" for r in results)
        assert (target / "quasar_2025_2026.csv").exists()
        assert (target / "nexus_2025_2026.csv").exists()


class TestInvoiceImport:
    """Test importing of JHU lockbox invoices."""

    @pytest.fixture
    def invoice_parsers(self):
        from datetime import date
        from decimal import Decimal

        from smaug.models import Invoice
        from smaug.parsers import InvoiceParser

        class DummyInvoiceParser(InvoiceParser):
            def name(self) -> str:
                return "Dummy Invoice Parser"

            def can_parse(self, file_path: Path) -> bool:
                return file_path.suffix.lower() == ".pdf" and "dummy" in file_path.name.lower()

            def parse(self, file_path: Path) -> Invoice | None:
                return Invoice(
                    invoice_number="INV-12345",
                    project_id="QUASAR",
                    invoice_date=date(2026, 4, 1),
                    grant_number="JHU-12345",
                    period_start=date(2026, 3, 1),
                    period_end=date(2026, 3, 31),
                    current_expense=Decimal("5000.00"),
                    cumulative_expense=Decimal("25000.00"),
                    categories={"Salary": Decimal("5000.00")},
                )

        return [DummyInvoiceParser()]

    def test_import_valid_invoice(self, tmp_path, invoice_parsers):
        from smaug.cli._import import _import_single_invoice
        from smaug.store import ProjectStore

        store = ProjectStore(EXAMPLES_DIR)
        store.load_all()

        source_file = tmp_path / "dummy_invoice.pdf"
        source_file.write_text("dummy PDF content")

        target_dir = tmp_path / "reports" / "invoices"

        result = _import_single_invoice(
            source_file, target_dir, invoice_parsers, store, override_project="QUASAR"
        )

        assert result["status"] == "imported"
        assert result["project_id"] == "QUASAR"
        assert result["invoice_number"] == "INV-12345"
        assert (target_dir / "dummy_invoice.pdf").exists()

    def test_import_invoice_dry_run(self, tmp_path, invoice_parsers):
        from smaug.cli._import import _import_single_invoice
        from smaug.store import ProjectStore

        store = ProjectStore(EXAMPLES_DIR)
        store.load_all()

        source_file = tmp_path / "dummy_invoice.pdf"
        source_file.write_text("dummy PDF content")

        target_dir = tmp_path / "reports" / "invoices"

        result = _import_single_invoice(
            source_file, target_dir, invoice_parsers, store, override_project="QUASAR", dry_run=True
        )

        assert result["status"] == "would_import"
        assert not (target_dir / "dummy_invoice.pdf").exists()
