"""CLI commands for importing and listing spending reports."""

import shutil
from pathlib import Path

from ..parsers import ReportParser, discover_parsers
from ..parsers import parse_report as _plugin_parse_report
from ..store import ProjectStore
from ..validation import validate_report
from ._util import Anonymizer, Colors, color


def _import_single_file(
    file_path: Path,
    target_dir: Path,
    report_parsers: list[ReportParser],
    *,
    dry_run: bool = False,
    force: bool = False,
) -> dict:
    """Import a single report file into the data directory.

    Returns a result dict with keys: file, status, message, and optionally
    project_id, period, total_spent.
    """
    result: dict = {"file": str(file_path.name)}

    # Check destination
    dest = target_dir / file_path.name
    if dest.exists() and not force:
        # Check if it's the same file (e.g., importing from the data dir itself)
        if dest.resolve() == file_path.resolve():
            result["status"] = "skipped"
            result["message"] = "File is already in the data directory"
            return result
        result["status"] = "skipped"
        result["message"] = "Already exists (use --force to overwrite)"
        return result

    # Try to parse the file
    report, _personnel = _plugin_parse_report(file_path, report_parsers)

    if report is None:
        result["status"] = "error"
        result["message"] = "No parser could handle this file"
        return result

    # Validate the parsed report
    validation = validate_report(report, file_path)
    if not validation.is_valid:
        errors = "; ".join(e.message for e in validation.errors)
        result["status"] = "error"
        result["message"] = f"Validation failed: {errors}"
        return result

    # Collect parsed metadata
    result["project_id"] = report.project_id
    result["period"] = report.period
    result["total_spent"] = report.total_spent

    # Collect any validation warnings
    warnings = [w for w in validation.warnings if w.severity == "warning"]
    if warnings:
        result["warnings"] = [w.message for w in warnings]

    if dry_run:
        result["status"] = "would_import"
        result["message"] = "Dry run — file not copied"
        return result

    # Copy file to target directory
    target_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(file_path, dest)

    result["status"] = "imported"
    result["message"] = f"Copied to {dest}"
    return result


def _collect_report_files(source: Path) -> list[Path]:
    """Collect importable files from a path (file or directory)."""
    if source.is_file():
        return [source]

    if source.is_dir():
        files: list[Path] = []
        for pattern in ("*.pdf", "*.csv", "*.PDF", "*.CSV"):
            files.extend(source.glob(pattern))
        return sorted(files)

    return []


def cmd_report(store: ProjectStore, args) -> None:
    """Dispatch report subcommands: list, import."""
    action = getattr(args, "action", None)

    if action == "list":
        _cmd_report_list(store, args)
    elif action == "import":
        _cmd_report_import(store, args)
    else:
        print("Usage: smaug report {list,import} ...")


def _cmd_report_list(store: ProjectStore, args) -> None:
    """Show detailed spending report for a project (moved from cmd_report)."""
    from ..api import SmaugAPI

    api = SmaugAPI(args.data_dir)
    result = api.spending_report(args.project)

    if "error" in result:
        print(result["error"])
        return

    # Get project name for header
    data = store.get_project(args.project)
    name = data.project.name if data else args.project
    print(f"\n=== Spending History: {name} ===\n")

    if not result["periods"]:
        print("No spending reports found.")
        return

    print(f"{'Period':<18} {'Spent':>14} {'Committed':>14} {'Total':>14}")
    print("-" * 62)

    for period in result["periods"]:
        print(
            f"{period['period']:<18} ${period['total_spent']:>12,.2f} ${period['total_committed']:>12,.2f} ${period['total_spent_and_committed']:>12,.2f}"
        )

    # Personnel on this project
    if result["personnel_totals"]:
        print("\n--- Personnel ---")
        for pname, total in sorted(result["personnel_totals"].items(), key=lambda x: -x[1]):
            print(f"  {Anonymizer.anonymize(pname):<30} ${total:>12,.2f}")


def _cmd_report_import(store: ProjectStore, args) -> None:
    """Import spending report(s) into the data directory."""
    source = Path(args.path)
    report_type = getattr(args, "type", "sponsored")
    dry_run = getattr(args, "dry_run", False)
    force = getattr(args, "force", False)

    if not source.exists():
        print(f"Error: Path not found: {source}")
        return

    # Determine target directory
    data_dir = Path(args.data_dir)
    target_dir = data_dir / "reports" / report_type

    # Discover parsers
    report_parsers, _ = discover_parsers()

    if not report_parsers:
        print("Error: No report parsers available. Install a parser plugin.")
        return

    # Collect files to import
    files = _collect_report_files(source)

    if not files:
        if source.is_dir():
            print(f"No report files (PDF, CSV) found in: {source}")
        else:
            print(f"Error: Not a recognized file type: {source}")
        return

    # Print header
    mode = "DRY RUN — " if dry_run else ""
    type_label = report_type.replace("-", " ").title()
    print(f"\n{mode}Importing {len(files)} file(s) as {type_label} reports\n")

    # Process each file
    imported = 0
    skipped = 0
    errors = 0

    for file_path in files:
        result = _import_single_file(
            file_path,
            target_dir,
            report_parsers,
            dry_run=dry_run,
            force=force,
        )

        status = result["status"]
        icon = {
            "imported": color("✓", Colors.GREEN),
            "would_import": color("○", Colors.CYAN),
            "skipped": color("-", Colors.YELLOW),
            "error": color("✗", Colors.RED),
        }.get(status, "?")

        # Build detail string
        detail_parts = []
        if result.get("project_id"):
            detail_parts.append(f"project={result['project_id']}")
        if result.get("period"):
            detail_parts.append(f"period={result['period']}")
        if result.get("total_spent") is not None:
            detail_parts.append(f"spent=${result['total_spent']:,.2f}")

        detail = f" ({', '.join(detail_parts)})" if detail_parts else ""
        print(f"  {icon} {result['file']}{detail}")

        if result.get("message") and status in ("skipped", "error"):
            print(f"    {result['message']}")

        # Print warnings if any
        for warning in result.get("warnings", []):
            print(f"    {color('⚠', Colors.YELLOW)} {warning}")

        if status == "imported":
            imported += 1
        elif status == "would_import":
            imported += 1  # Count for summary
        elif status == "skipped":
            skipped += 1
        else:
            errors += 1

    # Summary
    print()
    if dry_run:
        print(f"Would import: {imported}, Skip: {skipped}, Errors: {errors}")
    else:
        print(f"Imported: {imported}, Skipped: {skipped}, Errors: {errors}")

    if imported > 0 and not dry_run:
        print(f"\nReports saved to: {target_dir}")
        print("Run 'smaug list' or 'smaug report list <PROJECT>' to verify.")


def _import_single_invoice(
    file_path: Path,
    target_dir: Path,
    invoice_parsers: list,
    store: ProjectStore,
    *,
    override_project: str | None = None,
    dry_run: bool = False,
    force: bool = False,
) -> dict:
    """Import a single invoice PDF into the central reports/invoices directory."""
    result: dict = {"file": str(file_path.name)}

    # Check destination
    dest = target_dir / file_path.name
    if dest.exists() and not force:
        if dest.resolve() == file_path.resolve():
            result["status"] = "skipped"
            result["message"] = "File is already in the central invoices directory"
            return result
        result["status"] = "skipped"
        result["message"] = "Already exists (use --force to overwrite)"
        return result

    # Try to parse the invoice
    from ..parsers import parse_invoice as _plugin_parse_invoice

    invoice = _plugin_parse_invoice(file_path, invoice_parsers)

    if invoice is None:
        result["status"] = "error"
        result["message"] = "No invoice parser could handle this file"
        return result

    # Resolve project ID
    project_id = override_project
    if not project_id:
        project_id = store._resolve_project_id(invoice.project_id)

    if not project_id:
        result["status"] = "error"
        result["project_unresolved"] = True
        result["message"] = (
            f"Could not automatically resolve project for this invoice (Grant No: {invoice.grant_number or 'None'}). Please specify --project explicitly."
        )
        return result

    # Store project ID in invoice and result
    invoice.project_id = project_id
    result["project_id"] = project_id
    result["invoice_number"] = invoice.invoice_number
    result["amount"] = invoice.current_expense

    if dry_run:
        result["status"] = "would_import"
        result["message"] = "Dry run — file not copied"
        return result

    # Copy file to target directory
    target_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(file_path, dest)

    result["status"] = "imported"
    result["message"] = f"Copied to {dest}"
    return result


def cmd_invoice_import(store: ProjectStore, args) -> None:
    """Import JHU lockbox invoices into central data directory."""
    source = Path(args.path)
    dry_run = getattr(args, "dry_run", False)
    force = getattr(args, "force", False)
    override_project = getattr(args, "project", None)

    if not source.exists():
        print(f"Error: Path not found: {source}")
        return

    # Determine target directory
    data_dir = Path(args.data_dir)
    target_dir = data_dir / "reports" / "invoices"

    # Discover parsers
    _, invoice_parsers = discover_parsers()

    if not invoice_parsers:
        print("Error: No invoice parsers available. Install a parser plugin.")
        return

    # Collect files to import
    files = _collect_report_files(source)

    if not files:
        if source.is_dir():
            print(f"No invoice PDF files found in: {source}")
        else:
            print(f"Error: Not a recognized file type: {source}")
        return

    # Print header
    mode = "DRY RUN — " if dry_run else ""
    print(f"\n{mode}Importing {len(files)} invoice file(s)\n")

    # Process each file
    imported = 0
    skipped = 0
    errors = 0

    for file_path in files:
        result = _import_single_invoice(
            file_path,
            target_dir,
            invoice_parsers,
            store,
            override_project=override_project,
            dry_run=dry_run,
            force=force,
        )

        status = result["status"]
        icon = {
            "imported": color("✓", Colors.GREEN),
            "would_import": color("○", Colors.CYAN),
            "skipped": color("-", Colors.YELLOW),
            "error": color("✗", Colors.RED),
        }.get(status, "?")

        # Build detail string
        detail_parts = []
        if result.get("project_id"):
            detail_parts.append(f"project={result['project_id']}")
        if result.get("invoice_number"):
            detail_parts.append(f"invoice={result['invoice_number']}")
        if result.get("amount") is not None:
            detail_parts.append(f"amount=${result['amount']:,.2f}")

        detail = f" ({', '.join(detail_parts)})" if detail_parts else ""
        print(f"  {icon} {result['file']}{detail}")

        if result.get("message") and status in ("skipped", "error"):
            print(f"    {result['message']}")

        if status == "imported" or status == "would_import":
            imported += 1
        elif status == "skipped":
            skipped += 1
        else:
            errors += 1

    # Summary
    print()
    if dry_run:
        print(f"Would import: {imported}, Skip: {skipped}, Errors: {errors}")
    else:
        print(f"Imported: {imported}, Skipped: {skipped}, Errors: {errors}")

    if imported > 0 and not dry_run:
        print(f"\nInvoices saved to: {target_dir}")
        print("Run 'smaug invoice list' to verify.")
