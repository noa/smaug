"""
Unit tests for reimbursement management, credit card import, and reconciliation.
"""

from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from smaug.api import SmaugAPI
from smaug.models import (
    Date,
    Expense,
    ReimbursementCategory,
    ReimbursementStatus,
    SpendingReport,
)
from smaug.reimbursements import (
    add_reimbursement,
    auto_reconcile,
    filter_reimbursements,
    import_credit_card_statement,
    reconcile_reimbursements,
    update_reimbursement,
)
from smaug.store import ProjectStore

CHASE_CSV_CONTENT = """Transaction Date,Post Date,Description,Category,Type,Amount,Memo
06/01/2026,06/02/2026,GOOGLE *CLOUD ABC123,Shopping,Sale,-1500.00,
06/23/2026,06/24/2026,DELTA AIR   0060000000000,Travel,Sale,-850.00,
06/15/2026,06/16/2026,GIANT FOOD INC #100,Groceries,Sale,-80.00,
"""


@pytest.fixture
def temp_workspace():
    with TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        projects_dir = root / "projects"
        projects_dir.mkdir(parents=True)
        reports_dir = root / "reports"
        reports_dir.mkdir(parents=True)

        # Manifest
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


def test_add_and_filter_reimbursements(temp_workspace):
    store = ProjectStore(temp_workspace)
    store.load_all()

    item = add_reimbursement(
        store,
        project="ATLAS",
        amount=850.00,
        description="Flight to conference",
        date_incurred="2026-06-23",
        category="travel",
        claimant="Jane Smith",
        notes="Delta Flight",
    )

    assert item.project_id == "ATLAS"
    assert item.amount == Decimal("850.00")
    assert item.date == Date(2026, 6, 23)
    assert item.category == ReimbursementCategory.TRAVEL
    assert item.status == ReimbursementStatus.PENDING

    # Filter
    all_items = filter_reimbursements(store)
    assert len(all_items) == 1
    assert all_items[0].id == item.id

    by_proj = filter_reimbursements(store, project="ATLAS")
    assert len(by_proj) == 1

    by_other = filter_reimbursements(store, project="NONEXISTENT")
    assert len(by_other) == 0


def test_import_credit_card_statement(temp_workspace):
    store = ProjectStore(temp_workspace)
    store.load_all()

    csv_path = temp_workspace / "chase.csv"
    csv_path.write_text(CHASE_CSV_CONTENT)

    res = import_credit_card_statement(
        store,
        csv_path,
        default_project="ATLAS",
        auto_accept_high=True,
        claimant="Jane Smith",
    )

    assert res["total_transactions"] == 3
    assert res["personal_count"] == 1  # Giant Food
    assert res["auto_accepted_count"] == 2  # Google Cloud & Delta Air

    items = filter_reimbursements(store)
    assert len(items) == 2

    # Verify deduplication on re-import
    res2 = import_credit_card_statement(
        store,
        csv_path,
        default_project="ATLAS",
        auto_accept_high=True,
    )
    assert res2["duplicates_skipped"] == 2
    assert len(filter_reimbursements(store)) == 2


def test_update_status(temp_workspace):
    store = ProjectStore(temp_workspace)
    store.load_all()

    item = add_reimbursement(
        store,
        project="ATLAS",
        amount=150.00,
        description="Lab Supplies",
        date_incurred="2026-06-10",
        category="supplies",
    )

    updated = update_reimbursement(
        store,
        item.id,
        status="submitted",
        external_ref="CONCUR-999",
    )
    assert updated is not None
    assert updated.status == ReimbursementStatus.SUBMITTED
    assert updated.external_ref == "CONCUR-999"


def test_reconciliation_exact_transaction_match(temp_workspace):
    store = ProjectStore(temp_workspace)
    store.load_all()

    # Add reimbursement item of 1,250.00
    item = add_reimbursement(
        store,
        project="STIPEND",
        amount=1250.00,
        description="Conference expenses",
        date_incurred="2026-06-01",
        claimant="Jane Smith",
        category="other",
    )

    # Synthetic June report with matching transaction
    report = SpendingReport(
        project_id="80000001",
        period="June 2026",
        year=2026,
        month=6,
        total_spent=Decimal("3250.00"),
        total_month=Decimal("1250.00"),
        other_month=Decimal("1250.00"),
        other_spent=Decimal("1450.00"),
        expenses=[
            Expense(
                date=Date(2026, 6, 22),
                category="Other Expenses",
                amount=Decimal("1250.00"),
                vendor="JANE SMITH",
                description="MISC REIMB 00100001/OTHER",
                ref_doc="1900000001",
            )
        ],
    )
    store._spending["STIPEND"] = [report]

    matches = reconcile_reimbursements(store, project="STIPEND")
    assert len(matches) == 1
    m = matches[0]
    assert m.reimbursement_id == item.id
    assert m.confidence == "exact"
    assert m.match_type == "exact_transaction"
    assert m.matched_ref_doc == "1900000001"

    # Test auto_reconcile
    reconciled = auto_reconcile(store, project="STIPEND")
    assert len(reconciled) == 1

    # Status should now be REIMBURSED
    refreshed = filter_reimbursements(store, project="STIPEND")[0]
    assert refreshed.status == ReimbursementStatus.REIMBURSED
    assert "1900000001" in (refreshed.reconciled_report or "")


def test_reconciliation_category_spike_match(temp_workspace):
    store = ProjectStore(temp_workspace)
    store.load_all()

    # Sponsored report without detailed lines but with travel_month spike
    add_reimbursement(
        store,
        project="ATLAS",
        amount=850.00,
        description="Flight",
        date_incurred="2026-06-20",
        category="travel",
    )

    report = SpendingReport(
        project_id="ATLAS",
        period="July 2026",
        year=2026,
        month=7,
        total_spent=Decimal("50000.00"),
        travel_month=Decimal("850.00"),
    )
    store._spending["ATLAS"] = [report]

    matches = reconcile_reimbursements(store, project="ATLAS")
    assert len(matches) == 1
    assert matches[0].match_type == "category_spike"
    assert matches[0].confidence == "high"


def test_api_reimbursement_endpoints(temp_workspace):
    api = SmaugAPI(temp_workspace)

    add_res = api.add_reimbursement(
        project="ATLAS",
        amount=500.0,
        description="Compute credits",
        date_incurred="2026-07-01",
        category="compute",
    )
    assert "id" in add_res
    reimb_id = add_res["id"]

    listed = api.list_reimbursements(project="ATLAS")
    assert len(listed) == 1
    assert listed[0]["amount"] == 500.0

    stat_res = api.set_reimbursement_status(reimb_id, "submitted", external_ref="REF123")
    assert stat_res.get("success") is True

    reconcile_res = api.reconcile_reimbursements(project="ATLAS")
    assert len(reconcile_res) == 1
    assert reconcile_res[0]["reimbursement_id"] == reimb_id


def test_cli_add_reimbursement_default_date(temp_workspace):
    from types import SimpleNamespace

    from smaug.cli._reimbursement import cmd_reimbursement

    store = ProjectStore(temp_workspace)
    store.load_all()

    args = SimpleNamespace(
        action="add",
        project="ATLAS",
        amount=120.50,
        description="Adapters and cables",
        date=None,
        category="supplies",
        claimant="Jane Smith",
        notes=None,
        external_ref=None,
    )
    cmd_reimbursement(store, args)

    items = filter_reimbursements(store, project="ATLAS")
    assert len(items) == 1
    assert items[0].amount == Decimal("120.50")
    assert items[0].date == Date.today()
