"""
Reimbursement CLI commands: import statements, triage candidates, track status, and reconcile.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from ..concur import is_concur_export
from ..credit_card import classify_transaction, parse_statement
from ..models import (
    ReimbursementCategory,
    ReimbursementItem,
    ReimbursementStatus,
)
from ..reimbursements import (
    add_reimbursement,
    auto_reconcile,
    filter_reimbursements,
    generate_reimbursement_id,
    import_concur_report,
    import_credit_card_statement,
    reconcile_reimbursements,
    update_reimbursement,
)
from ..store import ProjectStore
from ..yaml_utils import git_commit_change, yaml_transaction


def _status_color(status: ReimbursementStatus | str) -> str:
    s = status.value if isinstance(status, ReimbursementStatus) else str(status).lower()
    colors = {
        "reimbursed": "green",
        "submitted": "cyan",
        "pending": "yellow",
        "rejected": "red",
    }
    return colors.get(s, "dim")


def cmd_reimbursement(store: ProjectStore, args) -> None:
    """Manage out-of-pocket reimbursements and credit card statements."""
    console = Console()
    action = args.action

    if action == "list":
        items = filter_reimbursements(
            store,
            project=getattr(args, "project", None),
            status=getattr(args, "status", None),
            category=getattr(args, "category", None),
        )

        title = "Reimbursements"
        if getattr(args, "project", None):
            title += f" (Project: {args.project.upper()})"
        if getattr(args, "status", None):
            title += f" [Status: {args.status}]"

        tbl = Table(title=title, box=box.ROUNDED, header_style="bold", title_style="bold")
        tbl.add_column("ID", style="dim", min_width=18)
        tbl.add_column("Date", min_width=10)
        tbl.add_column("Project", style="cyan", min_width=8)
        tbl.add_column("Category", min_width=10)
        tbl.add_column("Amount", justify="right", min_width=10)
        tbl.add_column("Status", min_width=10)
        tbl.add_column("Claimant", min_width=14)
        tbl.add_column("Description", min_width=25)
        tbl.add_column("Reconciled / Ref", style="dim", min_width=20)

        total_pending = Decimal("0")
        total_reimbursed = Decimal("0")

        for item in items:
            stat_str = (
                item.status.value
                if isinstance(item.status, ReimbursementStatus)
                else str(item.status)
            )
            color = _status_color(stat_str)
            stat_formatted = f"[{color}]{stat_str.upper()}[/{color}]"

            cat_str = (
                item.category.value
                if isinstance(item.category, ReimbursementCategory)
                else str(item.category)
            )
            date_str = item.date.isoformat() if item.date else "-"

            ref_info = item.reconciled_report or item.external_ref or "-"

            tbl.add_row(
                item.id,
                date_str,
                item.project_id,
                cat_str,
                f"${item.amount:,.2f}",
                stat_formatted,
                item.claimant or "-",
                item.description[:35] + ("..." if len(item.description) > 35 else ""),
                ref_info,
            )

            if stat_str in ("pending", "submitted"):
                total_pending += item.amount
            elif stat_str == "reimbursed":
                total_reimbursed += item.amount

        console.print()
        console.print(tbl)
        console.print(
            f"Outstanding Liabilities (Pending/Submitted): [yellow]${total_pending:,.2f}[/yellow]  |  "
            f"Total Reimbursed: [green]${total_reimbursed:,.2f}[/green]"
        )
        console.print()

    elif action == "import":
        source_path = Path(args.path)
        if not source_path.exists():
            console.print(f"[red]Error: Path not found: {source_path}[/red]")
            return

        is_interactive = getattr(args, "interactive", False)
        is_dry_run = getattr(args, "dry_run", False)
        auto_high = getattr(args, "auto_high", False)
        default_proj = getattr(args, "project", None)
        claimant = getattr(args, "claimant", None)

        # Resolve requested status flag if specified
        target_status: ReimbursementStatus | None = None
        if getattr(args, "reimbursed", False):
            target_status = ReimbursementStatus.REIMBURSED
        elif getattr(args, "submitted", False):
            target_status = ReimbursementStatus.SUBMITTED
        elif getattr(args, "status", None):
            s = args.status.lower()
            if s in ("reimbursed", "accepted", "paid"):
                target_status = ReimbursementStatus.REIMBURSED
            elif s in ("submitted",):
                target_status = ReimbursementStatus.SUBMITTED
            elif s in ("pending",):
                target_status = ReimbursementStatus.PENDING

        # Check if source is a Concur export file or directory containing Concur exports
        concur_files: list[Path] = []
        if source_path.is_dir():
            xlsx_files = sorted(source_path.glob("*.xlsx")) + sorted(source_path.glob("*.xls"))
            concur_files = [
                f for f in xlsx_files if not f.name.startswith("~$") and is_concur_export(f)
            ]
        elif source_path.is_file() and is_concur_export(source_path):
            concur_files = [source_path]

        if concur_files:
            if not default_proj:
                console.print(
                    "[red]Error: Concur expense import requires an explicit target project.\n"
                    "Please specify with --project / -p (e.g. --project STIPEND).[/red]"
                )
                return

            target_proj = default_proj.strip().upper()
            concur_status = target_status or ReimbursementStatus.SUBMITTED
            total_imported = 0
            total_dupes = 0
            total_entries = 0

            for c_file in concur_files:
                res = import_concur_report(
                    store,
                    c_file,
                    project=target_proj,
                    status=concur_status,
                    claimant=claimant,
                    dry_run=is_dry_run,
                )
                total_imported += res["imported_count"]
                total_dupes += res["duplicates_skipped"]
                total_entries += res["total_entries"]

                title_prefix = (
                    "[yellow]Dry Run: [/yellow]" if is_dry_run else "[green]Imported: [/green]"
                )
                tbl = Table(
                    title=f"{title_prefix}Concur Report '{c_file.stem}' [bold]({concur_status.value.upper()})[/bold]",
                    box=box.ROUNDED,
                )
                tbl.add_column("Date", min_width=10)
                tbl.add_column("Vendor / Description", min_width=25)
                tbl.add_column("Category", min_width=10)
                tbl.add_column("Amount", justify="right", min_width=10)
                tbl.add_column("Payment", min_width=14)
                tbl.add_column("Receipt", min_width=8)
                tbl.add_column("Status", min_width=10)

                for itm in res["items"]:
                    tbl.add_row(
                        itm["date"],
                        itm["description"],
                        itm["category"],
                        f"${itm['amount']:,.2f}",
                        itm.get("notes", "").split(".")[0].replace("Payment: ", ""),
                        "Yes" if "Yes" in itm.get("notes", "") else "No",
                        f"[{_status_color(itm['status'])}]{itm['status'].upper()}[/{_status_color(itm['status'])}]",
                    )

                console.print()
                console.print(tbl)

            action_desc = "Would import" if is_dry_run else "Successfully imported"
            color = "yellow" if is_dry_run else "green"
            console.print(
                f"[{color}]{action_desc} {total_imported} items across {len(concur_files)} report(s) as {concur_status.value.upper()} "
                f"({total_dupes} duplicates skipped, {total_entries} total line items)[/{color}]\n"
            )
            if is_dry_run:
                console.print(
                    "Run without [bold]--dry-run[/bold] to write entries to reimbursements config.\n"
                )
            return

        # Otherwise, process as credit card / bank statement CSV
        file_path = source_path
        if file_path.is_dir():
            console.print(
                f"[red]Error: {file_path} is a directory and contains no Concur Excel exports.[/red]"
            )
            return

        card_status = target_status or ReimbursementStatus.PENDING

        if not is_interactive and not is_dry_run and auto_high:
            # Batch import of high-confidence items
            res = import_credit_card_statement(
                store,
                file_path,
                default_project=default_proj,
                auto_accept_high=True,
                claimant=claimant,
                status=card_status,
            )
            console.print(
                f"[green]Successfully imported {res['auto_accepted_count']} high-confidence items from {file_path.name} as {card_status.value.upper()}![/green]"
            )
            console.print(
                f"Skipped {res['personal_count']} personal transactions, {res['duplicates_skipped']} duplicates."
            )
            return

        # Parse transactions for preview or interactive triage
        try:
            transactions = parse_statement(file_path)
        except Exception as e:
            console.print(f"[red]Error parsing statement {file_path}: {e}[/red]")
            return

        store.load_reimbursements_config()
        existing_hashes = {i.hash_id for i in store.get_all_reimbursements() if i.hash_id}

        active_projects = store.list_projects()
        default_project = default_proj or (
            active_projects[0] if active_projects else "DISCRETIONARY"
        )

        candidates: list[tuple] = []
        personal_txs = 0
        duplicates = 0

        for tx in transactions:
            if tx.hash_id and tx.hash_id in existing_hashes:
                duplicates += 1
                continue
            classification = classify_transaction(tx)
            if not classification.is_reimbursable:
                personal_txs += 1
                continue
            candidates.append((tx, classification))

        console.print(f"\n[bold]Statement:[/bold] {file_path.name}")
        console.print(
            f"Total Transactions: {len(transactions)} | Research Candidates: {len(candidates)} | Personal/Excluded: {personal_txs} | Duplicates: {duplicates}\n"
        )

        if not candidates:
            console.print("[yellow]No new reimbursable candidate transactions found.[/yellow]")
            return

        if is_dry_run:
            cand_table = Table(title="Detected Candidates (Dry Run)", box=box.ROUNDED)
            cand_table.add_column("Date", min_width=10)
            cand_table.add_column("Description", min_width=30)
            cand_table.add_column("Amount", justify="right", min_width=10)
            cand_table.add_column("Suggested Cat", min_width=12)
            cand_table.add_column("Confidence", min_width=10)
            cand_table.add_column("Reason", style="dim")

            for tx, cl in candidates:
                cand_table.add_row(
                    tx.transaction_date.isoformat(),
                    tx.description,
                    f"${tx.amount:,.2f}",
                    cl.category.value,
                    cl.confidence,
                    cl.reason,
                )
            console.print(cand_table)
            console.print(
                "\nRun without [bold]--dry-run[/bold] (or with [bold]--interactive[/bold] / [bold]--auto-high[/bold]) to save."
            )
            return

        if is_interactive:
            console.print("[bold cyan]Starting Interactive Triage Review[/bold cyan]")
            console.print(
                "Commands at prompt: [bold]y[/bold]=accept, [bold]t[/bold]=travel, [bold]c[/bold]=compute, [bold]s[/bold]=supplies, [bold]p[/bold] <proj>=assign project, [bold]i[/bold]=ignore, [bold]q[/bold]=quit\n"
            )

            accepted_items: list[ReimbursementItem] = []

            for idx, (tx, cl) in enumerate(candidates, 1):
                panel_content = (
                    f"[bold]Date:[/bold] {tx.transaction_date}  |  "
                    f"[bold]Amount:[/bold] [bold green]${tx.amount:,.2f}[/bold green]\n"
                    f"[bold]Description:[/bold] {tx.description}\n"
                    f"[bold]Suggested Category:[/bold] {cl.category.value.upper()} (Confidence: {cl.confidence})\n"
                    f"[bold]Rationale:[/bold] {cl.reason}\n"
                    f"[bold]Target Project:[/bold] {default_project}"
                )
                console.print(
                    Panel(panel_content, title=f"Candidate {idx}/{len(candidates)}", expand=False)
                )

                current_cat = cl.category
                current_proj = default_project

                while True:
                    try:
                        choice = input("Decision [y/t/c/s/p <proj>/i/q]? ").strip()
                    except (EOFError, KeyboardInterrupt):
                        choice = "q"

                    if not choice or choice.lower() == "y":
                        # Accept with suggested values
                        accepted_items.append(
                            ReimbursementItem(
                                id=generate_reimbursement_id(tx.transaction_date),
                                project_id=current_proj,
                                date=tx.transaction_date,
                                amount=tx.amount,
                                description=tx.description,
                                category=current_cat,
                                claimant=claimant,
                                status=card_status,
                                source=tx.card_source,
                                hash_id=tx.hash_id,
                                notes=cl.reason,
                            )
                        )
                        console.print(
                            f"[green]✔ Accepted as {current_cat.value.upper()} on {current_proj}[/green]\n"
                        )
                        break
                    elif choice.lower() == "t":
                        current_cat = ReimbursementCategory.TRAVEL
                        console.print("Set category to TRAVEL. Confirm with 'y' or press enter.")
                    elif choice.lower() == "c":
                        current_cat = ReimbursementCategory.COMPUTE
                        console.print("Set category to COMPUTE. Confirm with 'y' or press enter.")
                    elif choice.lower() == "s":
                        current_cat = ReimbursementCategory.SUPPLIES
                        console.print("Set category to SUPPLIES. Confirm with 'y' or press enter.")
                    elif choice.lower().startswith("p "):
                        parts = choice.split(None, 1)
                        if len(parts) > 1:
                            current_proj = parts[1].strip().upper()
                            console.print(
                                f"Set project to {current_proj}. Confirm with 'y' or press enter."
                            )
                    elif choice.lower() == "i":
                        console.print("[dim]Ignored transaction.[/dim]\n")
                        break
                    elif choice.lower() == "q":
                        console.print("[yellow]Review terminated early.[/yellow]\n")
                        break
                    else:
                        console.print("Invalid command. Options: y, t, c, s, p <project>, i, q")

                if choice.lower() == "q":
                    break

            if accepted_items:
                config_path = store.projects_dir / "reimbursements_config.yaml"
                with yaml_transaction(config_path) as data:
                    reimb_list = data.setdefault("reimbursements", [])
                    for itm in accepted_items:
                        reimb_list.append(itm.to_dict())

                git_commit_change(
                    store.data_dir,
                    f"reimbursement-import: {len(accepted_items)} items from {file_path.name}",
                )
                store.load_reimbursements_config()
                console.print(
                    f"[green]Saved {len(accepted_items)} reimbursements to config![/green]"
                )

        else:
            # Non-interactive, non-auto-high without dry run
            console.print(
                f"Found {len(candidates)} candidates. Use [bold]--interactive[/bold] / [bold]-i[/bold] to triage, or [bold]--auto-high[/bold] to import high-confidence items."
            )

    elif action == "add":
        project = args.project.upper()
        amount = Decimal(str(args.amount))
        desc = args.description
        date_str = getattr(args, "date", None) or date.today().isoformat()
        category = getattr(args, "category", None) or "other"
        claimant = getattr(args, "claimant", None)
        notes = getattr(args, "notes", None)
        ext_ref = getattr(args, "external_ref", None)

        item = add_reimbursement(
            store,
            project=project,
            amount=amount,
            description=desc,
            date_incurred=date_str,
            category=category,
            claimant=claimant,
            notes=notes,
            external_ref=ext_ref,
        )
        console.print(
            f"[green]Added reimbursement {item.id} to {project}: {desc} (${amount:,.2f})[/green]"
        )

    elif action == "set-status":
        item_id = args.id
        status_str = args.status.lower()
        ext_ref = getattr(args, "external_ref", None)

        updated = update_reimbursement(
            store,
            item_id,
            status=status_str,
            external_ref=ext_ref,
        )
        if updated:
            console.print(
                f"[green]Updated {item_id} status to {updated.status.value.upper()}[/green]"
            )
        else:
            console.print(f"[red]Error: Reimbursement item '{item_id}' not found.[/red]")

    elif action == "reconcile":
        project = getattr(args, "project", None)
        auto_accept = getattr(args, "auto_accept", False)

        matches = reconcile_reimbursements(store, project=project)

        if not matches:
            console.print("[yellow]No outstanding reimbursements to reconcile.[/yellow]")
            return

        tbl = Table(title="Reimbursement Reconciliation vs PI Reports", box=box.ROUNDED)
        tbl.add_column("Reimbursement ID", style="dim", min_width=18)
        tbl.add_column("Project", style="cyan", min_width=8)
        tbl.add_column("Date", min_width=10)
        tbl.add_column("Amount", justify="right", min_width=10)
        tbl.add_column("Match Type", min_width=16)
        tbl.add_column("Confidence", min_width=10)
        tbl.add_column("Reconciliation Details", min_width=35)

        exact_count = 0
        overdue_count = 0

        for m in matches:
            if m.confidence == "exact":
                conf_formatted = "[bold green]EXACT[/bold green]"
                exact_count += 1
            elif m.confidence == "high":
                conf_formatted = "[green]HIGH[/green]"
                exact_count += 1
            elif m.confidence == "overdue":
                conf_formatted = "[bold red]OVERDUE[/bold red]"
                overdue_count += 1
            else:
                conf_formatted = "[yellow]PENDING[/yellow]"

            tbl.add_row(
                m.reimbursement_id,
                m.project_id,
                m.reimbursement_date.isoformat() if m.reimbursement_date else "-",
                f"${m.reimbursement_amount:,.2f}",
                m.match_type,
                conf_formatted,
                m.details,
            )

        console.print()
        console.print(tbl)
        console.print(
            f"Matched Reports: [green]{exact_count}[/green]  |  "
            f"Overdue (>45d): [red]{overdue_count}[/red]  |  "
            f"Pending: [yellow]{len(matches) - exact_count - overdue_count}[/yellow]"
        )
        console.print()

        if auto_accept and exact_count > 0:
            reconciled = auto_reconcile(store, project=project)
            console.print(
                f"[green]Successfully reconciled and marked {len(reconciled)} items as REIMBURSED![/green]\n"
            )
        elif exact_count > 0:
            console.print(
                "Tip: Run [bold]smaug reimbursement reconcile --auto-accept[/bold] (or [bold]-y[/bold]) to mark confirmed matches as REIMBURSED."
            )
