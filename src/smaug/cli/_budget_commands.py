"""CLI commands for managing contractual budget periods (budget_config.yaml)."""

from decimal import Decimal
from pathlib import Path

import yaml

from ..config import get_rates_path
from ..contractual_budget import load_contractual_budget
from ..store import ProjectStore
from ..yaml_utils import git_commit_change, yaml_transaction


def _resolve_budget_config_path(store: ProjectStore, project_id: str, data_dir: str) -> Path | None:
    """Resolve the path to a project's budget_config.yaml.

    Returns the path (which may or may not exist yet), or None if the
    project itself is not found.
    """
    data = store.get_project(project_id)
    if not data:
        return None

    if data.project.budget_dir:
        b_path = Path(data.project.budget_dir)
        if b_path.is_absolute():
            return b_path / "budget_config.yaml"
        # Check relative to data_dir first
        if (Path(data_dir) / b_path / "budget_config.yaml").exists():
            return Path(data_dir) / b_path / "budget_config.yaml"
        candidate = Path(data_dir) / "projects" / project_id / "budget_config.yaml"
        if candidate.exists():
            return candidate
        return b_path / "budget_config.yaml"

    # Default convention: projects/<PROJECT>/budget_config.yaml under data_dir
    return Path(data_dir) / "projects" / project_id / "budget_config.yaml"


def _load_idc_rate(data_dir: str) -> Decimal:
    """Load the IDC rate from rates.yaml, defaulting to 0.55."""
    rates_path = get_rates_path(Path(data_dir))
    if rates_path.exists():
        with open(rates_path) as f:
            rates = yaml.safe_load(f)
        return Decimal(str(rates.get("idc_rate", 0.55)))
    return Decimal("0.55")


def _split_total(total: Decimal, idc_rate: Decimal) -> tuple[Decimal, Decimal]:
    """Split a total amount into (direct, idc) using the IDC rate.

    total = direct + direct * idc_rate = direct * (1 + idc_rate)
    """
    direct = (total / (1 + idc_rate)).quantize(Decimal("1"))
    idc = total - direct
    return direct, idc


def _recompute_totals(config: dict) -> None:
    """Recompute the cumulative totals section from all by_year entries."""
    by_year = config.get("by_year", {})
    total_budget = Decimal("0")
    total_direct = Decimal("0")
    total_idc = Decimal("0")

    for year_data in by_year.values():
        total_budget += Decimal(str(year_data.get("total", 0)))
        total_direct += Decimal(str(year_data.get("direct", 0)))
        total_idc += Decimal(str(year_data.get("idc", 0)))

    totals = config.setdefault("totals", {})
    totals["total_budget"] = int(total_budget)
    totals["total_direct_costs"] = int(total_direct)
    totals["total_indirect_costs"] = int(total_idc)


def _ensure_budget_dir_in_manifest(data_dir: str, project_id: str, budget_dir_rel: str) -> None:
    """Set budget_dir in manifest.yaml if not already set."""
    manifest_path = Path(data_dir) / "projects" / "manifest.yaml"
    if not manifest_path.exists():
        return

    with yaml_transaction(manifest_path) as manifest:
        for section in ["projects", "discretionary"]:
            if (
                section in manifest
                and project_id in manifest[section]
                and not manifest[section][project_id].get("budget_dir")
            ):
                manifest[section][project_id]["budget_dir"] = budget_dir_rel


def cmd_budget(store: ProjectStore, args) -> None:
    """Manage contractual budget periods."""
    action = args.action
    if action == "list":
        _cmd_budget_list(store, args)
    elif action == "add":
        _cmd_budget_add(store, args)
    elif action == "set":
        _cmd_budget_set(store, args)


def _cmd_budget_list(store: ProjectStore, args) -> None:
    """List contractual budget periods for a project."""
    from rich import box
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table

    console = Console()

    config_path = _resolve_budget_config_path(store, args.project, args.data_dir)
    if config_path is None:
        console.print(f"[red]Project not found:[/red] {args.project}")
        return

    if not config_path.exists():
        console.print(f"[yellow]No contractual budget configured for {args.project}.[/yellow]")
        console.print(
            f"  Use [cyan]smaug budget add {args.project} --year 1 --start YYYY-MM "
            f"--end YYYY-MM --total AMOUNT[/cyan] to create one."
        )
        return

    contract = load_contractual_budget(config_path)
    if not contract:
        console.print(f"[red]Error:[/red] Could not parse {config_path}")
        return

    # Header
    header_lines = []
    if contract.award_id:
        header_lines.append(f"[bold]Award:[/bold] {contract.award_id}")
    if contract.pi:
        header_lines.append(f"[bold]PI:[/bold] {contract.pi}")
    header_lines.append(f"[bold]Start:[/bold] {contract.start_date}")
    header_lines.append(
        f"[bold]Total Budget:[/bold] ${contract.total_budget:,.0f}  "
        f"[dim](Direct: ${contract.total_direct_costs:,.0f} + IDC: ${contract.total_indirect_costs:,.0f})[/dim]"
    )

    console.print()
    console.print(
        Panel(
            "\n".join(header_lines),
            title=f"[bold cyan]Contractual Budget: {args.project}[/bold cyan]",
            border_style="cyan",
        )
    )

    # Periods table
    table = Table(box=box.ROUNDED, show_header=True, header_style="bold")
    table.add_column("Period", style="cyan", min_width=8)
    table.add_column("Start", min_width=12)
    table.add_column("End", min_width=12)
    table.add_column("Total", justify="right", min_width=12)
    table.add_column("Direct", justify="right", min_width=12)
    table.add_column("IDC", justify="right", min_width=12)

    for period in sorted(contract.periods, key=lambda p: p.year_num):
        table.add_row(
            f"Year {period.year_num}",
            period.start.strftime("%Y-%m-%d"),
            period.end.strftime("%Y-%m-%d"),
            f"${period.total:,.0f}",
            f"${period.direct:,.0f}",
            f"${period.idc:,.0f}",
        )

    # Totals row
    table.add_section()
    table.add_row(
        "[bold]TOTAL[/bold]",
        "",
        "",
        f"[bold]${contract.total_budget:,.0f}[/bold]",
        f"[bold]${contract.total_direct_costs:,.0f}[/bold]",
        f"[bold]${contract.total_indirect_costs:,.0f}[/bold]",
    )

    console.print(table)
    console.print()


def _cmd_budget_add(store: ProjectStore, args) -> None:
    """Add a new contractual budget period."""
    from rich.console import Console

    console = Console()

    data = store.get_project(args.project)
    if not data:
        console.print(f"[red]Project not found:[/red] {args.project}")
        return

    year_num = args.year
    total = Decimal(str(args.total))

    # Determine direct / IDC split
    if args.direct is not None and args.idc is not None:
        direct = Decimal(str(args.direct))
        idc = Decimal(str(args.idc))
    elif args.direct is not None:
        direct = Decimal(str(args.direct))
        idc = total - direct
    elif args.idc is not None:
        idc = Decimal(str(args.idc))
        direct = total - idc
    else:
        # Auto-split using IDC rate
        idc_rate = _load_idc_rate(args.data_dir)
        direct, idc = _split_total(total, idc_rate)
        console.print(
            f"[dim]Auto-split using IDC rate {float(idc_rate) * 100:.1f}%: "
            f"direct=${direct:,.0f}, IDC=${idc:,.0f}[/dim]"
        )

    # Resolve config path
    config_path = _resolve_budget_config_path(store, args.project, args.data_dir)
    if config_path is None:
        console.print(f"[red]Project not found:[/red] {args.project}")
        return

    # Ensure parent directory exists
    config_path.parent.mkdir(parents=True, exist_ok=True)

    # Set budget_dir in manifest if this project doesn't have one yet
    if not data.project.budget_dir:
        rel_dir = str(config_path.parent.relative_to(Path(args.data_dir)))
        _ensure_budget_dir_in_manifest(args.data_dir, args.project, rel_dir)

    year_key = f"year{year_num}"

    try:
        with yaml_transaction(config_path) as config:
            # Bootstrap contract section if creating new file
            if "contract" not in config or not config["contract"]:
                config["contract"] = {
                    "award_id": data.project.award_id or "",
                    "pi": data.project.pi or "",
                    "start_date": _expand_date(args.start, is_end=False),
                }
            if "periods" not in config.get("contract", {}):
                config["contract"]["periods"] = {}
            if "by_year" not in config:
                config["by_year"] = {}
            if "totals" not in config:
                config["totals"] = {}

            # Check for duplicate
            if year_key in config["contract"]["periods"]:
                raise ValueError(
                    f"Year {year_num} already exists. Use 'smaug budget set' to modify it."
                )

            # Parse start/end dates — accept YYYY-MM (expand to YYYY-MM-01 / YYYY-MM-last)
            start_str = _expand_date(args.start, is_end=False)
            end_str = _expand_date(args.end, is_end=True)

            # Add period
            config["contract"]["periods"][year_key] = {
                "start": start_str,
                "end": end_str,
            }

            config["by_year"][year_key] = {
                "total": int(total),
                "direct": int(direct),
                "idc": int(idc),
            }

            # Recompute totals
            _recompute_totals(config)
    except ValueError as e:
        console.print(f"[red]Error:[/red] {e}")
        return

    console.print(f"Added Year {year_num}: ${total:,.0f} (direct=${direct:,.0f}, IDC=${idc:,.0f})")
    console.print(f"  Period: {args.start} to {args.end}")
    console.print(f"Config saved to {config_path}")
    git_commit_change(args.data_dir, f"budget-add: {args.project} year {year_num} (${total:,.0f})")


def _cmd_budget_set(store: ProjectStore, args) -> None:
    """Modify an existing contractual budget period."""
    from rich.console import Console

    console = Console()

    config_path = _resolve_budget_config_path(store, args.project, args.data_dir)
    if config_path is None:
        console.print(f"[red]Project not found:[/red] {args.project}")
        return

    if not config_path.exists():
        console.print(f"[red]Error:[/red] No budget config found for {args.project}.")
        console.print("  Use 'smaug budget add' to create one first.")
        return

    year_num = args.year
    year_key = f"year{year_num}"

    try:
        with yaml_transaction(config_path) as config:
            by_year = config.get("by_year", {})
            if year_key not in by_year:
                raise ValueError(
                    f"Year {year_num} not found. "
                    f"Available: {[k.replace('year', '') for k in by_year]}"
                )

            old = by_year[year_key]
            old_total = old.get("total", 0)

            # Determine new amounts
            if args.total is not None:
                total = Decimal(str(args.total))
                if args.direct is not None and args.idc is not None:
                    direct = Decimal(str(args.direct))
                    idc = Decimal(str(args.idc))
                elif args.direct is not None:
                    direct = Decimal(str(args.direct))
                    idc = total - direct
                elif args.idc is not None:
                    idc = Decimal(str(args.idc))
                    direct = total - idc
                else:
                    idc_rate = _load_idc_rate(args.data_dir)
                    direct, idc = _split_total(total, idc_rate)
                    console.print(
                        f"[dim]Auto-split using IDC rate {float(idc_rate) * 100:.1f}%: "
                        f"direct=${direct:,.0f}, IDC=${idc:,.0f}[/dim]"
                    )
            elif args.direct is not None or args.idc is not None:
                direct = (
                    Decimal(str(args.direct))
                    if args.direct is not None
                    else Decimal(str(old.get("direct", 0)))
                )
                idc = (
                    Decimal(str(args.idc))
                    if args.idc is not None
                    else Decimal(str(old.get("idc", 0)))
                )
                total = direct + idc
            else:
                raise ValueError("Must specify at least one of --total, --direct, or --idc.")

            by_year[year_key] = {
                "total": int(total),
                "direct": int(direct),
                "idc": int(idc),
            }

            # Update period dates if provided
            periods = config.get("contract", {}).get("periods", {})
            if year_key in periods:
                start_val = getattr(args, "start", None)
                end_val = getattr(args, "end", None)
                if start_val:
                    periods[year_key]["start"] = _expand_date(start_val, is_end=False)
                if end_val:
                    periods[year_key]["end"] = _expand_date(end_val, is_end=True)

            _recompute_totals(config)
    except ValueError as e:
        console.print(f"[red]Error:[/red] {e}")
        return

    console.print(f"Updated Year {year_num}: ${old_total:,} → ${total:,.0f}")
    console.print(f"  Direct: ${direct:,.0f}  IDC: ${idc:,.0f}")
    console.print(f"Config saved to {config_path}")
    git_commit_change(args.data_dir, f"budget-set: {args.project} year {year_num} (${total:,.0f})")


def _expand_date(date_str: str, is_end: bool = False) -> str:
    """Expand YYYY-MM to YYYY-MM-DD.

    For start dates: YYYY-MM → YYYY-MM-01
    For end dates: YYYY-MM → YYYY-MM-last_day
    If already YYYY-MM-DD, return as-is.
    """
    import calendar

    parts = str(date_str).split("-")
    if len(parts) == 3:
        return date_str
    if len(parts) == 2:
        year, month = int(parts[0]), int(parts[1])
        if is_end:
            last_day = calendar.monthrange(year, month)[1]
            return f"{year}-{month:02d}-{last_day:02d}"
        return f"{year}-{month:02d}-01"
    return date_str
