"""
Reimbursement tracking and reconciliation engine.

Manages out-of-pocket reimbursable expenses, imports credit card statements,
performs heuristic classification, tracks reimbursement lifecycles, and
reconciles submitted expenses against institutional PI spending reports.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING

from .concur import parse_concur_export
from .credit_card import ClassificationResult, classify_transaction, parse_statement
from .models import (
    Date,
    ReconciliationMatch,
    ReimbursementCategory,
    ReimbursementItem,
    ReimbursementStatus,
)
from .yaml_utils import git_commit_change, yaml_transaction

if TYPE_CHECKING:
    from .store import ProjectStore


def generate_reimbursement_id(tx_date: Date) -> str:
    """Generate a clean unique identifier for a reimbursement item."""
    prefix = tx_date.strftime("%Y%m%d") if tx_date else "reimb"
    short_uuid = uuid.uuid4().hex[:6]
    return f"reimb-{prefix}-{short_uuid}"


def import_credit_card_statement(
    store: ProjectStore,
    file_path: str | Path,
    default_project: str | None = None,
    auto_accept_high: bool = False,
    claimant: str | None = None,
    status: ReimbursementStatus | str = ReimbursementStatus.PENDING,
) -> dict:
    """
    Import and process transactions from a credit card statement.

    Args:
        store: ProjectStore instance
        file_path: Path to the statement file (e.g. Chase CSV)
        default_project: Default project short name for reimbursable items
        auto_accept_high: If True, automatically record high-confidence research items
        claimant: Optional claimant name for the reimbursements
        status: Status to assign to imported items (default: pending)

    Returns:
        Summary dict of import results
    """
    path = Path(file_path)
    transactions = parse_statement(path)
    store.load_reimbursements_config()

    existing_hashes = {item.hash_id for item in store.get_all_reimbursements() if item.hash_id}

    if not default_project:
        active_projects = store.list_projects()
        default_project = active_projects[0] if active_projects else "DISCRETIONARY"

    # Normalize status
    if isinstance(status, str):
        s_lower = status.strip().lower()
        if s_lower in ("accepted", "reimbursed", "paid"):
            assigned_status = ReimbursementStatus.REIMBURSED
        elif s_lower in ("submitted",):
            assigned_status = ReimbursementStatus.SUBMITTED
        elif s_lower in ("pending",):
            assigned_status = ReimbursementStatus.PENDING
        else:
            try:
                assigned_status = ReimbursementStatus(s_lower)
            except ValueError:
                assigned_status = ReimbursementStatus.PENDING
    else:
        assigned_status = status

    candidates: list[dict] = []
    imported_items: list[ReimbursementItem] = []
    duplicates_count = 0
    personal_count = 0

    for tx in transactions:
        if tx.hash_id and tx.hash_id in existing_hashes:
            duplicates_count += 1
            continue

        res: ClassificationResult = classify_transaction(tx)

        if not res.is_reimbursable:
            personal_count += 1
            continue

        item_id = generate_reimbursement_id(tx.transaction_date)
        project_to_assign = res.suggested_project or default_project

        reimb_item = ReimbursementItem(
            id=item_id,
            project_id=project_to_assign,
            date=tx.transaction_date,
            amount=tx.amount,
            description=tx.description,
            category=res.category,
            claimant=claimant,
            status=assigned_status,
            source=tx.card_source,
            hash_id=tx.hash_id,
            notes=res.reason,
        )

        candidates.append(
            {
                "transaction": tx.to_dict(),
                "classification": {
                    "category": res.category.value,
                    "confidence": res.confidence,
                    "reason": res.reason,
                },
                "item": reimb_item.to_dict(),
            }
        )

        if auto_accept_high and res.confidence == "high":
            imported_items.append(reimb_item)
            existing_hashes.add(tx.hash_id)

    if imported_items:
        config_path = store.projects_dir / "reimbursements_config.yaml"
        with yaml_transaction(config_path) as data:
            reimb_list = data.setdefault("reimbursements", [])
            for item in imported_items:
                reimb_list.append(item.to_dict())

        git_commit_change(
            store.data_dir,
            f"reimbursement-import: {len(imported_items)} items from {path.name}",
        )
        store.load_reimbursements_config()

    return {
        "source_file": str(path),
        "total_transactions": len(transactions),
        "reimbursable_candidates": candidates,
        "auto_accepted_count": len(imported_items),
        "personal_count": personal_count,
        "duplicates_skipped": duplicates_count,
    }


def import_concur_report(
    store: ProjectStore,
    file_path: str | Path,
    project: str | None = None,
    status: ReimbursementStatus | str = ReimbursementStatus.SUBMITTED,
    claimant: str | None = None,
    dry_run: bool = False,
) -> dict:
    """
    Import expense entries from a Concur expense report spreadsheet (.xlsx).

    Args:
        store: ProjectStore instance
        file_path: Path to the .xlsx file
        project: Target project short name (e.g. 'QUASAR', 'DISCRETIONARY') - required
        status: Status to assign ('submitted' or 'reimbursed'/'accepted')
        claimant: Optional claimant name (e.g. 'Jane Smith')
        dry_run: If True, preview entries without writing to config

    Returns:
        Summary dict of import results
    """
    if not project or not str(project).strip():
        raise ValueError(
            "An explicit target project must be specified for Concur expense import (e.g. --project STIPEND)."
        )
    target_project = str(project).strip().upper()

    path = Path(file_path)
    entries = parse_concur_export(path)
    store.load_reimbursements_config()

    existing_hashes = {item.hash_id for item in store.get_all_reimbursements() if item.hash_id}

    # Normalize status
    if isinstance(status, str):
        s_lower = status.strip().lower()
        if s_lower in ("accepted", "reimbursed", "paid"):
            assigned_status = ReimbursementStatus.REIMBURSED
        elif s_lower in ("submitted",):
            assigned_status = ReimbursementStatus.SUBMITTED
        elif s_lower in ("pending",):
            assigned_status = ReimbursementStatus.PENDING
        else:
            try:
                assigned_status = ReimbursementStatus(s_lower)
            except ValueError:
                assigned_status = ReimbursementStatus.SUBMITTED
    else:
        assigned_status = status

    imported_items: list[ReimbursementItem] = []
    duplicates_count = 0

    for entry in entries:
        if entry.hash_id in existing_hashes:
            duplicates_count += 1
            continue

        item_id = generate_reimbursement_id(entry.date)
        reimb_item = ReimbursementItem(
            id=item_id,
            project_id=target_project,
            date=entry.date,
            amount=entry.amount,
            description=f"{entry.vendor} ({entry.expense_type.strip()})",
            category=entry.category,
            claimant=claimant,
            status=assigned_status,
            external_ref=entry.report_name,
            source=f"Concur: {entry.report_name}",
            notes=f"Payment: {entry.payment_type}. Receipt: {entry.receipt}.",
            hash_id=entry.hash_id,
        )

        imported_items.append(reimb_item)
        existing_hashes.add(entry.hash_id)

    if not dry_run and imported_items:
        config_path = store.projects_dir / "reimbursements_config.yaml"
        with yaml_transaction(config_path) as data:
            reimb_list = data.setdefault("reimbursements", [])
            for item in imported_items:
                reimb_list.append(item.to_dict())

        git_commit_change(
            store.data_dir,
            f"reimbursement-concur: {len(imported_items)} items from {path.name} ({assigned_status.value})",
        )
        store.load_reimbursements_config()

    return {
        "source_file": str(path),
        "report_name": path.stem,
        "total_entries": len(entries),
        "imported_count": len(imported_items),
        "status": assigned_status.value,
        "duplicates_skipped": duplicates_count,
        "dry_run": dry_run,
        "items": [item.to_dict() for item in imported_items],
    }


def add_reimbursement(
    store: ProjectStore,
    project: str,
    amount: Decimal | float,
    description: str,
    date_incurred: date | str,
    category: ReimbursementCategory | str = ReimbursementCategory.OTHER,
    claimant: str | None = None,
    status: ReimbursementStatus | str = ReimbursementStatus.PENDING,
    notes: str | None = None,
    external_ref: str | None = None,
    source: str | None = None,
    hash_id: str | None = None,
) -> ReimbursementItem:
    """Add a new reimbursement item to configuration."""
    if isinstance(date_incurred, str):
        raw = date_incurred.strip()
        try:
            parsed_date = date.fromisoformat(raw)
        except ValueError:
            from .cli._util import parse_date_input

            d_str = parse_date_input(raw)
            parts = d_str.split("-")
            parsed_date = date(
                int(parts[0]), int(parts[1]), int(parts[2]) if len(parts) >= 3 else 1
            )
    else:
        parsed_date = date_incurred

    if isinstance(category, str):
        category = ReimbursementCategory(category.lower())
    if isinstance(status, str):
        status = ReimbursementStatus(status.lower())

    item_id = generate_reimbursement_id(parsed_date)
    item = ReimbursementItem(
        id=item_id,
        project_id=project,
        date=parsed_date,
        amount=Decimal(str(amount)),
        description=description,
        category=category,
        claimant=claimant,
        status=status,
        external_ref=external_ref,
        notes=notes,
        source=source,
        hash_id=hash_id,
    )

    config_path = store.projects_dir / "reimbursements_config.yaml"
    with yaml_transaction(config_path) as data:
        data.setdefault("reimbursements", []).append(item.to_dict())

    git_commit_change(
        store.data_dir,
        f"reimbursement-add: {project} - {description} (${amount})",
    )
    store.load_reimbursements_config()
    return item


def filter_reimbursements(
    store: ProjectStore,
    project: str | None = None,
    status: ReimbursementStatus | str | None = None,
    category: ReimbursementCategory | str | None = None,
) -> list[ReimbursementItem]:
    """Filter reimbursement items by project, status, and/or category."""
    store.load_reimbursements_config()
    items = store.get_all_reimbursements()

    if project:
        items = [i for i in items if i.project_id.upper() == project.upper()]

    if status:
        stat_val = status.value if isinstance(status, ReimbursementStatus) else str(status).lower()
        items = [
            i
            for i in items
            if (
                i.status.value if isinstance(i.status, ReimbursementStatus) else str(i.status)
            ).lower()
            == stat_val
        ]

    if category:
        cat_val = (
            category.value if isinstance(category, ReimbursementCategory) else str(category).lower()
        )
        items = [
            i
            for i in items
            if (
                i.category.value
                if isinstance(i.category, ReimbursementCategory)
                else str(i.category)
            ).lower()
            == cat_val
        ]

    return sorted(items, key=lambda x: x.date if x.date else date.min)


def update_reimbursement(
    store: ProjectStore,
    item_id: str,
    status: ReimbursementStatus | str | None = None,
    project: str | None = None,
    notes: str | None = None,
    external_ref: str | None = None,
    reconciled_report: str | None = None,
) -> ReimbursementItem | None:
    """Update fields on an existing reimbursement item."""
    config_path = store.projects_dir / "reimbursements_config.yaml"
    if not config_path.exists():
        return None

    updated_item: ReimbursementItem | None = None

    with yaml_transaction(config_path) as data:
        items_list = data.get("reimbursements", [])
        for entry in items_list:
            if entry.get("id") == item_id or entry.get("id", "").startswith(item_id):
                if status is not None:
                    entry["status"] = (
                        status.value
                        if isinstance(status, ReimbursementStatus)
                        else str(status).lower()
                    )
                if project is not None:
                    entry["project"] = project
                if notes is not None:
                    entry["notes"] = notes
                if external_ref is not None:
                    entry["external_ref"] = external_ref
                if reconciled_report is not None:
                    entry["reconciled_report"] = reconciled_report

                cat_str = entry.get("category", "other")
                try:
                    cat_enum = ReimbursementCategory(cat_str)
                except ValueError:
                    cat_enum = ReimbursementCategory.OTHER

                stat_str = entry.get("status", "pending")
                try:
                    stat_enum = ReimbursementStatus(stat_str)
                except ValueError:
                    stat_enum = ReimbursementStatus.PENDING

                d_val = entry.get("date")
                parsed_d = date.fromisoformat(d_val) if d_val else date.today()

                updated_item = ReimbursementItem(
                    id=entry["id"],
                    project_id=entry["project"],
                    date=parsed_d,
                    amount=Decimal(str(entry.get("amount", 0))),
                    description=entry.get("description", ""),
                    category=cat_enum,
                    claimant=entry.get("claimant"),
                    status=stat_enum,
                    external_ref=entry.get("external_ref"),
                    reconciled_report=entry.get("reconciled_report"),
                    source=entry.get("source"),
                    notes=entry.get("notes"),
                    hash_id=entry.get("hash_id"),
                )
                break

    if updated_item:
        git_commit_change(
            store.data_dir,
            f"reimbursement-update: {item_id} -> {updated_item.status.value}",
        )
        store.load_reimbursements_config()

    return updated_item


def reconcile_reimbursements(
    store: ProjectStore,
    project: str | None = None,
) -> list[ReconciliationMatch]:
    """
    Match outstanding (pending / submitted) reimbursements against institutional PI spending reports.

    Checks:
    1. Line-item transactions from report pages (Page 2 of discretionary reports)
       matching by amount and date window, especially where Vendor matches claimant.
    2. Monthly category spending amounts (e.g. Travel, Other Expenses) for exact amount matches.
    3. Flags stale / overdue items (> 45 days old without appearing in reports).
    """
    store.load_all()
    items = filter_reimbursements(store, project=project)
    matches: list[ReconciliationMatch] = []

    today = date.today()

    for item in items:
        # Check against reports for the project
        proj_id = item.project_id
        # Also resolve project short name or funded program identifier
        reports = store._spending.get(proj_id, [])
        if not reports:
            # Try finding by grant or funded program
            resolved = store._resolve_project_id(proj_id)
            if resolved:
                reports = store._spending.get(resolved, [])

        matched = False

        # 1. Check detailed transactions across all reports for this project
        for r in reports:
            if not r.expenses:
                continue

            for exp in r.expenses:
                # Compare amount and date proximity: transaction posting date on or after expense date (-10 days for posting delays)
                amt_diff = abs(exp.amount - item.amount)
                if (
                    amt_diff <= Decimal("0.01")
                    and exp.date
                    and item.date
                    and exp.date >= (item.date - timedelta(days=10))
                ):
                    vendor_name = (exp.vendor or "").strip().lower()
                    claimant_name = (item.claimant or "").strip().lower()

                    # Check vendor match or description match
                    is_exact_vendor = False
                    if claimant_name and vendor_name:
                        # e.g., "JANE SMITH" vs "Smith, Jane"
                        parts = claimant_name.replace(",", " ").split()
                        if all(p in vendor_name for p in parts if len(p) > 2):
                            is_exact_vendor = True

                    confidence = "exact" if (is_exact_vendor or exp.ref_doc) else "high"
                    ref_info = f"Ref Doc #{exp.ref_doc}" if exp.ref_doc else "Transaction"
                    vendor_info = f"Vendor: {exp.vendor}" if exp.vendor else ""
                    details = f"Matched posted transaction on {exp.date} in {r.period}: {ref_info} {vendor_info} (${exp.amount:,.2f})".strip()

                    matches.append(
                        ReconciliationMatch(
                            reimbursement_id=item.id,
                            project_id=item.project_id,
                            reimbursement_amount=item.amount,
                            reimbursement_date=item.date,
                            match_type="exact_transaction",
                            report_period=r.period,
                            confidence=confidence,
                            details=details,
                            matched_ref_doc=exp.ref_doc,
                            matched_date=exp.date,
                            matched_amount=exp.amount,
                        )
                    )
                    matched = True
                    break
            if matched:
                break

        # 2. If not matched on line transactions, check monthly category spikes
        if not matched and reports:
            for r in reports:
                # Check report period date on or after item date
                report_date = date(r.year, r.month, 1) if r.year and r.month else None
                if report_date and item.date and report_date >= item.date.replace(day=1):
                    # Check travel
                    cat = (
                        item.category
                        if isinstance(item.category, ReimbursementCategory)
                        else ReimbursementCategory.OTHER
                    )
                    cand_amounts = []
                    if cat == ReimbursementCategory.TRAVEL:
                        if r.travel_month is not None:
                            cand_amounts.append(("Travel Domestic", r.travel_month))
                        if r.travel_foreign_month is not None:
                            cand_amounts.append(("Travel Foreign", r.travel_foreign_month))
                    elif cat in (
                        ReimbursementCategory.COMPUTE,
                        ReimbursementCategory.EQUIPMENT,
                        ReimbursementCategory.SUPPLIES,
                        ReimbursementCategory.OTHER,
                    ):
                        if r.other_month is not None:
                            cand_amounts.append(("Other Expenses", r.other_month))
                        if r.service_center_month is not None:
                            cand_amounts.append(("Service Center", r.service_center_month))
                        if r.supplies_month is not None:
                            cand_amounts.append(("Supplies", r.supplies_month))

                    for cat_name, amt in cand_amounts:
                        if amt and abs(amt - item.amount) <= Decimal("0.01"):
                            matches.append(
                                ReconciliationMatch(
                                    reimbursement_id=item.id,
                                    project_id=item.project_id,
                                    reimbursement_amount=item.amount,
                                    reimbursement_date=item.date,
                                    match_type="category_spike",
                                    report_period=r.period,
                                    confidence="high",
                                    details=f"Matched exact monthly {cat_name} in {r.period} report (${amt:,.2f})",
                                    matched_date=report_date,
                                    matched_amount=amt,
                                )
                            )
                            matched = True
                            break
                if matched:
                    break

        # 3. Unmatched
        if not matched:
            days_old = (today - item.date).days if item.date else 0
            if days_old > 45:
                confidence = "overdue"
                details = f"Incurred {days_old} days ago without matching payment in PI reports (>45d overdue)."
            else:
                confidence = "pending"
                details = f"Pending institutional processing (incurred {days_old} days ago)."

            matches.append(
                ReconciliationMatch(
                    reimbursement_id=item.id,
                    project_id=item.project_id,
                    reimbursement_amount=item.amount,
                    reimbursement_date=item.date,
                    match_type="unmatched",
                    report_period="N/A",
                    confidence=confidence,
                    details=details,
                )
            )

    return matches


def auto_reconcile(
    store: ProjectStore,
    project: str | None = None,
) -> list[ReconciliationMatch]:
    """
    Find exact matches and automatically update their status to REIMBURSED.
    """
    matches = reconcile_reimbursements(store, project=project)
    reconciled_matches: list[ReconciliationMatch] = []

    for m in matches:
        if m.confidence in ("exact", "high") and m.match_type in (
            "exact_transaction",
            "category_spike",
        ):
            ref_str = f"Report: {m.report_period}"
            if m.matched_ref_doc:
                ref_str += f" (Ref Doc: {m.matched_ref_doc})"

            update_reimbursement(
                store,
                m.reimbursement_id,
                status=ReimbursementStatus.REIMBURSED,
                reconciled_report=ref_str,
            )
            reconciled_matches.append(m)

    return reconciled_matches
