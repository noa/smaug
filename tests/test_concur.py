"""
Unit tests for Concur expense export parsing and ingestion.
"""

from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory

import openpyxl
import pytest

from smaug.api import SmaugAPI
from smaug.concur import is_concur_export, parse_concur_export
from smaug.models import ReimbursementCategory, ReimbursementStatus
from smaug.reimbursements import filter_reimbursements, import_concur_report
from smaug.store import ProjectStore


def create_synthetic_concur_xlsx(file_path: Path) -> Path:
    """Helper to generate a realistic Concur export spreadsheet."""
    wb = openpyxl.Workbook()
    ws = wb.active
    assert ws is not None
    ws.title = "Entries"

    headers = [
        "Date",
        "Receipt",
        "Expense Type",
        "Vendor Details",
        "Payment Type",
        "Approved",
    ]
    ws.append(headers)

    rows = [
        ("07/03/2026", "Yes", "Other ", "Anthropic", "Out of Pocket", "$200.00"),
        ("06/01/2026", "Yes", "Other ", "Google Cloud", "Out of Pocket", "$1,500.00"),
        ("06/20/2026", "Yes", "Airfare", "Delta Air", "Out of Pocket", "$550.00"),
        ("05/02/2026", "No", "Other ", "OpenAI", "Out of Pocket", "$100.00"),
    ]
    for r in rows:
        ws.append(r)

    wb.save(file_path)
    wb.close()
    return file_path


@pytest.fixture
def temp_concur_workspace():
    with TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        projects_dir = root / "projects"
        projects_dir.mkdir(parents=True)
        reports_dir = root / "reports"
        reports_dir.mkdir(parents=True)

        manifest = projects_dir / "manifest.yaml"
        manifest.write_text(
            "projects:\n"
            "  ATLAS:\n"
            "    name: ATLAS\n"
            "    total_budget: 1000000\n"
            "discretionary:\n"
            "  STIPEND:\n"
            "    name: STIPEND - SMITH\n"
            "    funded_program: '80000001'\n"
            "    total_budget: 50000\n"
        )
        yield root


def test_is_concur_export(temp_concur_workspace):
    xlsx_path = temp_concur_workspace / "concur_test.xlsx"
    create_synthetic_concur_xlsx(xlsx_path)

    assert is_concur_export(xlsx_path) is True

    # Test non-concur excel
    non_concur = temp_concur_workspace / "other.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    assert ws is not None
    ws.append(["Foo", "Bar", "Baz"])
    ws.append([1, 2, 3])
    wb.save(non_concur)
    wb.close()
    assert is_concur_export(non_concur) is False

    # Test non-excel
    txt_path = temp_concur_workspace / "file.txt"
    txt_path.write_text("Hello")
    assert is_concur_export(txt_path) is False


def test_parse_concur_export(temp_concur_workspace):
    xlsx_path = temp_concur_workspace / "concur_sample.xlsx"
    create_synthetic_concur_xlsx(xlsx_path)

    entries = parse_concur_export(xlsx_path)
    assert len(entries) == 4

    # Anthropic
    assert entries[0].vendor == "Anthropic"
    assert entries[0].amount == Decimal("200.00")
    assert entries[0].category == ReimbursementCategory.COMPUTE
    assert entries[0].receipt == "Yes"
    assert entries[0].payment_type == "Out of Pocket"

    # Google Cloud
    assert entries[1].vendor == "Google Cloud"
    assert entries[1].amount == Decimal("1500.00")
    assert entries[1].category == ReimbursementCategory.COMPUTE

    # Delta Air
    assert entries[2].vendor == "Delta Air"
    assert entries[2].amount == Decimal("550.00")
    assert entries[2].category == ReimbursementCategory.TRAVEL

    # OpenAI
    assert entries[3].vendor == "OpenAI"
    assert entries[3].amount == Decimal("100.00")
    assert entries[3].category == ReimbursementCategory.COMPUTE
    assert entries[3].receipt == "No"


def test_import_concur_report_default_submitted(temp_concur_workspace):
    store = ProjectStore(temp_concur_workspace)
    store.load_all()

    xlsx_path = temp_concur_workspace / "Compute_Charges.xlsx"
    create_synthetic_concur_xlsx(xlsx_path)

    # Calling without project must raise ValueError
    with pytest.raises(ValueError, match="An explicit target project must be specified"):
        import_concur_report(store, xlsx_path)

    res = import_concur_report(
        store,
        xlsx_path,
        project="ATLAS",
        claimant="Jane Smith",
    )

    assert res["total_entries"] == 4
    assert res["imported_count"] == 4
    assert res["status"] == "submitted"
    assert res["duplicates_skipped"] == 0

    items = filter_reimbursements(store, project="ATLAS")
    assert len(items) == 4
    for itm in items:
        assert itm.status == ReimbursementStatus.SUBMITTED
        assert itm.claimant == "Jane Smith"
        assert itm.external_ref == "Compute_Charges"

    # Test deduplication
    res2 = import_concur_report(
        store,
        xlsx_path,
        project="ATLAS",
    )
    assert res2["imported_count"] == 0
    assert res2["duplicates_skipped"] == 4
    assert len(filter_reimbursements(store, project="ATLAS")) == 4


def test_import_concur_report_reimbursed_flag(temp_concur_workspace):
    store = ProjectStore(temp_concur_workspace)
    store.load_all()

    xlsx_path = temp_concur_workspace / "Reimbursed_Report.xlsx"
    create_synthetic_concur_xlsx(xlsx_path)

    res = import_concur_report(
        store,
        xlsx_path,
        project="ATLAS",
        status="reimbursed",
    )

    assert res["imported_count"] == 4
    assert res["status"] == "reimbursed"

    items = filter_reimbursements(store, project="ATLAS")
    assert len(items) == 4
    for itm in items:
        assert itm.status == ReimbursementStatus.REIMBURSED


def test_import_concur_report_dry_run(temp_concur_workspace):
    store = ProjectStore(temp_concur_workspace)
    store.load_all()

    xlsx_path = temp_concur_workspace / "Dry_Run_Report.xlsx"
    create_synthetic_concur_xlsx(xlsx_path)

    res = import_concur_report(
        store,
        xlsx_path,
        project="ATLAS",
        dry_run=True,
    )

    assert res["dry_run"] is True
    assert res["imported_count"] == 4
    # Store should not have any items saved
    items = filter_reimbursements(store, project="ATLAS")
    assert len(items) == 0


def test_api_import_concur(temp_concur_workspace):
    api = SmaugAPI(temp_concur_workspace)

    xlsx_path = temp_concur_workspace / "API_Concur.xlsx"
    create_synthetic_concur_xlsx(xlsx_path)

    # Calling without project returns error
    err_res = api.import_concur_reimbursements(str(xlsx_path), project="")
    assert "error" in err_res

    res = api.import_concur_reimbursements(
        str(xlsx_path),
        project="ATLAS",
        status="accepted",
        claimant="Jane Smith",
    )

    assert res["imported_count"] == 4
    assert res["status"] == "reimbursed"

    reimbs = api.list_reimbursements(project="ATLAS")
    assert len(reimbs) == 4
    assert all(r["status"] == "reimbursed" for r in reimbs)


class DummyArgs:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


def test_cli_import_concur_missing_project_errors(temp_concur_workspace):
    from smaug.cli._reimbursement import cmd_reimbursement

    store = ProjectStore(temp_concur_workspace)
    store.load_all()

    xlsx_path = temp_concur_workspace / "Single_Concur.xlsx"
    create_synthetic_concur_xlsx(xlsx_path)

    args = DummyArgs(
        action="import",
        path=str(xlsx_path),
        reimbursed=True,
        submitted=False,
        status=None,
        project=None,  # Missing project
        claimant="Jane Smith",
        dry_run=False,
        interactive=False,
        auto_high=False,
    )

    cmd_reimbursement(store, args)

    # Should not import anything since project was missing
    items = filter_reimbursements(store)
    assert len(items) == 0


def test_cli_import_concur_single_file_reimbursed(temp_concur_workspace):
    from smaug.cli._reimbursement import cmd_reimbursement

    store = ProjectStore(temp_concur_workspace)
    store.load_all()

    xlsx_path = temp_concur_workspace / "Single_Concur.xlsx"
    create_synthetic_concur_xlsx(xlsx_path)

    args = DummyArgs(
        action="import",
        path=str(xlsx_path),
        reimbursed=True,
        submitted=False,
        status=None,
        project="ATLAS",
        claimant="Jane Smith",
        dry_run=False,
        interactive=False,
        auto_high=False,
    )

    cmd_reimbursement(store, args)

    items = filter_reimbursements(store, project="ATLAS")
    assert len(items) == 4
    assert all(i.status == ReimbursementStatus.REIMBURSED for i in items)


def test_cli_import_concur_directory_submitted(temp_concur_workspace):
    from smaug.cli._reimbursement import cmd_reimbursement

    store = ProjectStore(temp_concur_workspace)
    store.load_all()

    concur_dir = temp_concur_workspace / "concur_batch"
    concur_dir.mkdir()
    create_synthetic_concur_xlsx(concur_dir / "report1.xlsx")
    create_synthetic_concur_xlsx(concur_dir / "report2.xlsx")

    args = DummyArgs(
        action="import",
        path=str(concur_dir),
        reimbursed=False,
        submitted=True,
        status=None,
        project="ATLAS",
        claimant="Jane Smith",
        dry_run=False,
        interactive=False,
        auto_high=False,
    )

    cmd_reimbursement(store, args)

    items = filter_reimbursements(store, project="ATLAS")
    # report1 has 4 items, report2 has 4 items = 8 items total
    assert len(items) == 8
    assert all(i.status == ReimbursementStatus.SUBMITTED for i in items)

    # Re-running on the same directory should detect all 8 as duplicates
    cmd_reimbursement(store, args)
    assert len(filter_reimbursements(store, project="ATLAS")) == 8


def test_cli_import_concur_dry_run(temp_concur_workspace):
    from smaug.cli._reimbursement import cmd_reimbursement

    store = ProjectStore(temp_concur_workspace)
    store.load_all()

    xlsx_path = temp_concur_workspace / "Preview_Only.xlsx"
    create_synthetic_concur_xlsx(xlsx_path)

    args = DummyArgs(
        action="import",
        path=str(xlsx_path),
        reimbursed=False,
        submitted=False,
        status=None,
        project="ATLAS",
        claimant="Jane Smith",
        dry_run=True,
        interactive=False,
        auto_high=False,
    )

    cmd_reimbursement(store, args)

    items = filter_reimbursements(store, project="ATLAS")
    assert len(items) == 0
