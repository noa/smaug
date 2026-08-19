"""Heavy financial analysis CLI commands: stopwork, spend-plan, proposal, budget-vs-actuals, summary."""

from decimal import Decimal
from pathlib import Path

from ..store import ProjectStore
from ._util import Anonymizer, Colors, color, load_aliases, parse_date_input


def cmd_stopwork(store: ProjectStore, args) -> None:
    """Forecast stop-work date based on funded ceiling and projected spending."""
    from datetime import date as date_type

    from rich import box
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table

    from ..projections import project_spending

    console = Console(width=max(120, Console().width) if Console().width else 120)

    data = store.get_project(args.project)
    if not data:
        console.print(f"[red]Project not found:[/red] {args.project}")
        return

    if not data.spending:
        console.print(f"[yellow]No spending reports found for {args.project}[/yellow]")
        return

    latest = data.spending[-1]

    # Determine mode: --ceiling = remaining-budget envelope, else = lifetime cumulative
    is_envelope = hasattr(args, "ceiling") and args.ceiling

    if is_envelope:
        ceiling = Decimal(str(args.ceiling))
        ceiling_source = "remaining-budget envelope"
    elif latest.funded_ceiling:
        ceiling = latest.funded_ceiling
        ceiling_source = "report"
    elif data.budget and data.budget.total_budget:
        ceiling = data.budget.total_budget
        ceiling_source = "budget"
    else:
        console.print("[red]No funded ceiling or budget found.[/red] Use --ceiling to specify.")
        return

    # Apply deductions
    deductions = Decimal("0")
    deduction_items = []
    if hasattr(args, "deduct") and args.deduct:
        for d in args.deduct:
            amt = Decimal(str(d))
            deductions += amt
            deduction_items.append(amt)

    effective_ceiling = ceiling - deductions

    # In envelope mode, auto-deduct actual spend from reports within the envelope period
    actuals_consumed = Decimal("0")
    actuals_detail = []  # (period_label, amount)
    if is_envelope:
        from_month = getattr(args, "envelope_from", None)
        if from_month:
            parsed = parse_date_input(from_month)
            parts = parsed.split("-")
            from_date = date_type(int(parts[0]), int(parts[1]), 1)

            # Compute monthly deltas from reports within the envelope period
            all_sorted = sorted(data.spending, key=lambda r: (r.year, r.month))
            for i, r in enumerate(all_sorted):
                r_date = date_type(r.year, r.month, 1)
                if r_date >= from_date:
                    if i > 0:
                        delta = r.total_spent - all_sorted[i - 1].total_spent
                    else:
                        delta = r.total_spent  # first report, use cumulative as delta
                    actuals_consumed += delta
                    actuals_detail.append((r.period, delta))

        cumulative_start = deductions + actuals_consumed
    else:
        cumulative_start = latest.total_spent

    # Header panel
    header_lines = []
    header_lines.append(f"[bold]Latest Report:[/bold] {latest.period}")

    if is_envelope:
        header_lines.append(
            f"[bold]Budget Envelope:[/bold] ${ceiling:>12,.2f}  [dim]({ceiling_source})[/dim]"
        )
        if deductions > 0:
            for i, d in enumerate(deduction_items):
                header_lines.append(f"  [dim]Deduction {i + 1}:[/dim] -${d:>10,.2f}")
        if actuals_detail:
            for period_label, amt in actuals_detail:
                header_lines.append(f"  [dim]{period_label} actual:[/dim] -${amt:>10,.2f}")
        remaining_envelope = effective_ceiling - actuals_consumed
        gap_color = "green" if remaining_envelope > 0 else "red"
        header_lines.append(
            f"[bold]Remaining for forward:[/bold] [{gap_color}]${remaining_envelope:>12,.2f}[/{gap_color}]"
        )
    else:
        header_lines.append(
            f"[bold]Funded Ceiling:[/bold] ${ceiling:>12,.2f}  [dim]({ceiling_source})[/dim]"
        )
        if deductions > 0:
            for i, d in enumerate(deduction_items):
                header_lines.append(f"  [dim]Deduction {i + 1}:[/dim] -${d:>10,.2f}")
            header_lines.append(f"[bold]Effective Ceiling:[/bold] ${effective_ceiling:>12,.2f}")
        header_lines.append(f"[bold]Cumulative Spent:[/bold] ${latest.total_spent:>12,.2f}")
        header_lines.append(f"[bold]Committed:[/bold]        ${latest.total_committed:>12,.2f}")
        gap = effective_ceiling - latest.total_spent
        gap_color = "green" if gap > 0 else "red"
        header_lines.append(
            f"[bold]Remaining:[/bold]        [{gap_color}]${gap:>12,.2f}[/{gap_color}]"
        )

    console.print()
    console.print(
        Panel(
            "\n".join(header_lines),
            title=f"[bold]Stop-Work Forecast: {data.project.name}[/bold]",
            border_style="cyan",
        )
    )

    # Monthly category breakdown from recent reports
    recent = data.spending[-3:] if len(data.spending) >= 3 else data.spending
    recent = sorted(recent, key=lambda r: (r.year, r.month))

    cat_table = Table(
        title="Monthly Category Breakdown (from reports)",
        box=box.ROUNDED,
        show_header=True,
        header_style="bold",
        title_style="bold",
    )
    cat_table.add_column("Category", style="cyan", min_width=16)
    for r in recent:
        cat_table.add_column(r.period, justify="right", min_width=12)

    # Build monthly values: prefer direct _month fields, fall back to computing deltas
    def _month_val(report, field_month, field_cum, prev_report=None):
        """Get monthly value: prefer _month field, fallback to delta from cumulative."""
        val = getattr(report, field_month, None)
        if val is not None:
            return val
        if prev_report is not None:
            return getattr(report, field_cum) - getattr(prev_report, field_cum)
        return None

    categories = [
        ("Salary", "salary_month", "salary_spent"),
        ("Fringe", "fringe_month", "fringe_spent"),
        ("Tuition", "tuition_month", "tuition_spent"),
        ("Insurance", "insurance_month", "insurance_spent"),
        ("Service Center", "service_center_month", "service_center_spent"),
        ("Travel", "travel_month", "travel_spent"),
        ("Other", "other_month", "other_spent"),
    ]

    # Find prev reports for delta computation
    all_sorted = sorted(data.spending, key=lambda r: (r.year, r.month))
    prev_map = {}  # report -> previous report
    for i, r in enumerate(all_sorted):
        if i > 0:
            prev_map[id(r)] = all_sorted[i - 1]

    for label, month_field, cum_field in categories:
        row = []
        for r in recent:
            prev = prev_map.get(id(r))
            val = _month_val(r, month_field, cum_field, prev)
            if val is not None and val != Decimal("0"):
                row.append(f"${val:>10,.0f}")
            else:
                row.append("[dim]$0[/dim]")
        cat_table.add_row(label, *row)

    # Direct subtotals
    cat_table.add_section()
    direct_row = []
    for r in recent:
        prev = prev_map.get(id(r))
        total = Decimal("0")
        for _, mf, cf in categories:
            val = _month_val(r, mf, cf, prev)
            if val is not None:
                total += val
        direct_row.append(f"${total:>10,.0f}")
    cat_table.add_row("[bold]Direct Subtotal[/bold]", *direct_row)

    # IDC row
    idc_row = []
    for r in recent:
        val = getattr(r, "indirect_month", None)
        if val is not None:
            idc_row.append(f"${val:>10,.0f}")
        else:
            prev = prev_map.get(id(r))
            if prev:
                delta = r.indirect_spent - prev.indirect_spent
                idc_row.append(f"${delta:>10,.0f}")
            else:
                idc_row.append("[dim]-[/dim]")
    cat_table.add_row("IDC", *idc_row)

    # Month total row
    cat_table.add_section()
    month_total_row = []
    for i, r in enumerate(recent):
        if i > 0:
            prev_r = recent[i - 1]
            delta = r.total_spent - prev_r.total_spent
            month_total_row.append(f"[bold]${delta:>10,.0f}[/bold]")
        else:
            # First report in window: try prev from all_sorted
            prev = prev_map.get(id(r))
            if prev:
                delta = r.total_spent - prev.total_spent
                month_total_row.append(f"[bold]${delta:>10,.0f}[/bold]")
            else:
                month_total_row.append("[dim]-[/dim]")
    cat_table.add_row("[bold]Month Total[/bold]", *month_total_row)

    console.print(cat_table)

    # Forward projections
    config_path = Path(args.data_dir) / "projects" / "personnel_config.yaml"
    if not config_path.exists():
        console.print("[yellow]No personnel config found; cannot project forward.[/yellow]")
        return

    store.load_travel_config()
    store.load_purchases_config()
    travel_items = store.get_project_travel(args.project)
    expense_items = store.get_project_expenses(args.project)

    start = date_type(latest.year, latest.month, 1)
    # Advance to next month after latest report
    if start.month == 12:
        start = start.replace(year=start.year + 1, month=1)
    else:
        start = start.replace(month=start.month + 1)

    projections = project_spending(
        args.project,
        config_path,
        start_date=start,
        months=18,
        travel_items=travel_items,
        expense_items=expense_items,
    )

    # Determine scenario
    scenario = getattr(args, "scenario", None)
    throttle_pct = Decimal(str(getattr(args, "throttle_pct", 0) or 0)) / 100

    def _run_scenario(projs, label, ceiling_val, cumulative_start, modifier=None):
        """Run a stop-work projection scenario and return (table, stop_month, stop_day_str)."""
        tbl = Table(
            title=label,
            box=box.ROUNDED,
            show_header=True,
            header_style="bold",
            title_style="bold",
        )
        tbl.add_column("Month", style="cyan", min_width=10)
        tbl.add_column("Projected", justify="right", min_width=10)
        tbl.add_column("Cumulative", justify="right", min_width=12)
        tbl.add_column("Remaining", justify="right", min_width=12)
        tbl.add_column("Status", min_width=10)

        cumulative = cumulative_start
        stop_month = None
        stop_day_str = None
        months_past_stop = 0

        for proj in projs:
            burn = proj.total
            if modifier:
                burn = modifier(proj, burn)

            cumulative += burn
            remaining = ceiling_val - cumulative
            month_str = f"{proj.year}-{proj.month:02d}"

            if remaining >= 0:
                status = "[green]OK[/green]"
            else:
                if stop_month is None:
                    stop_month = month_str
                    # Day-level precision
                    if burn > 0:
                        frac = (remaining + burn) / burn
                        frac = max(Decimal("0"), min(frac, Decimal("1")))
                        day = int(frac * 30)
                        stop_day_str = f"~day {day} of {month_str}"
                status = "[red bold]STOP-WORK[/red bold]"
                months_past_stop += 1

            remaining_style = "green" if remaining >= 0 else "red"
            tbl.add_row(
                month_str,
                f"${burn:>10,.0f}",
                f"${cumulative:>10,.0f}",
                f"[{remaining_style}]${remaining:>10,.0f}[/{remaining_style}]",
                status,
            )

            # Stop after 2 months past stop-work
            if months_past_stop >= 2:
                break

        return tbl, stop_month, stop_day_str

    # Base scenario
    base_table, base_stop, base_day = _run_scenario(
        projections, "Forward Projection (Base)", effective_ceiling, cumulative_start
    )
    console.print(base_table)

    if base_stop:
        msg = f"Projected stop-work: [bold red]{base_stop}[/bold red]"
        if base_day:
            msg += f"  (funds exhausted {base_day})"
        console.print(msg)
    else:
        console.print("[green]Funds sufficient through projected period.[/green]")

    # Scenario: no-tuition (always show if there's tuition in projections)
    has_tuition = any(p.tuition > 0 for p in projections)
    run_no_tuition = (scenario == "no-tuition") or (has_tuition and scenario is None)

    if run_no_tuition:
        console.print()

        def no_tuition_modifier(proj, burn):
            return burn - proj.tuition - proj.insurance

        nt_table, nt_stop, nt_day = _run_scenario(
            projections,
            "Scenario: No Tuition/Insurance Until Fall",
            effective_ceiling,
            cumulative_start,
            modifier=no_tuition_modifier,
        )
        console.print(nt_table)
        if nt_stop:
            msg = f"Scenario stop-work: [bold red]{nt_stop}[/bold red]"
            if nt_day:
                msg += f"  (funds exhausted {nt_day})"
            console.print(msg)
        else:
            console.print("[green]Scenario: Funds sufficient through projected period.[/green]")

    # Scenario: throttle
    if scenario == "throttle" and throttle_pct > 0:
        console.print()
        reduction = Decimal("1") - throttle_pct

        def throttle_modifier(proj, burn):
            return burn * reduction

        th_table, th_stop, th_day = _run_scenario(
            projections,
            f"Scenario: Throttle ({int(throttle_pct * 100)}% Reduction)",
            effective_ceiling,
            cumulative_start,
            modifier=throttle_modifier,
        )
        console.print(th_table)
        if th_stop:
            msg = f"Scenario stop-work: [bold red]{th_stop}[/bold red]"
            if th_day:
                msg += f"  (funds exhausted {th_day})"
            console.print(msg)
        else:
            console.print("[green]Scenario: Funds sufficient through projected period.[/green]")

    console.print()


def cmd_spend_plan(store: ProjectStore, args) -> None:
    """Generate a monthly spend plan for specified project(s)."""
    from datetime import date
    from decimal import Decimal

    from rich import box
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table

    from ..contractual_budget import load_contractual_budget
    from ..projections import (
        apply_hypotheticals,
        load_personnel_config,
        parse_hypothetical,
        project_monthly_costs,
    )

    # Use a wide console to ensure table columns don't truncate
    console = Console(width=max(140, Console().width) if Console().width else 140)

    config_path = Path(args.data_dir) / "projects" / "personnel_config.yaml"

    if not config_path.exists():
        console.print(f"[red]Error:[/red] Personnel config not found: {config_path}")
        return

    rates, personnel = load_personnel_config(config_path)

    # Parse date range overrides
    start_override = None
    end_override = None
    contract_year_label = None  # For display purposes

    # Handle fiscal year if provided (FY runs July 1 - June 30)
    if args.fy:
        fy_year = int(args.fy)
        # FY 2026 = July 1, 2025 through June 30, 2026
        start_override = date(fy_year - 1, 7, 1)
        end_override = date(fy_year, 6, 30)
    elif args.year:
        # Contract year - we'll look this up per-project below
        contract_year_label = args.year
    elif args.to:
        to_date = parse_date_input(args.to)
        parts = to_date.split("-")
        end_override = date(int(parts[0]), int(parts[1]), 1)

    # Parse hypotheticals if provided
    hypotheticals = []
    if args.hypotheticals:
        for spec in args.hypotheticals:
            try:
                hypo = parse_hypothetical(spec)
                hypotheticals.append(hypo)
            except ValueError as e:
                console.print(f"[red]Error:[/red] {e}")
                return

    # Load items
    store.load_travel_config()
    store.load_purchases_config()

    for project_id in args.projects:
        data = store.get_project(project_id)
        if not data:
            console.print(f"[red]Project not found:[/red] {project_id}")
            continue

        travel_items = store.get_project_travel(project_id)
        expense_items = store.get_project_expenses(project_id)

        # Handle contract year lookup for this specific project
        period_start_override = start_override
        period_end_override = end_override

        if contract_year_label:
            # Look up contract period from budget_config.yaml
            budget_config_path = None
            if data.project.budget_dir:
                budget_config_path = Path(data.project.budget_dir) / "budget_config.yaml"

            if budget_config_path and budget_config_path.exists():
                contract = load_contractual_budget(budget_config_path)
                if contract:
                    period = contract.get_period_by_year(contract_year_label)
                    if period:
                        period_start_override = period.start
                        period_end_override = period.end
                    else:
                        console.print(
                            f"[yellow]Warning:[/yellow] Contract year {contract_year_label} not found for {project_id}"
                        )
                        console.print(
                            f"  Available years: {[p.year_num for p in contract.periods]}"
                        )
            else:
                console.print(
                    f"[yellow]Warning:[/yellow] No budget_config.yaml found for {project_id}, cannot use --year"
                )

        # Determine end date: CLI override > project end_date > 12 months default
        project_end = period_end_override or data.project.end_date

        # Apply hypotheticals if provided
        if hypotheticals:
            try:
                aliases = load_aliases(args.data_dir)
                active_personnel = apply_hypotheticals(
                    personnel, hypotheticals, project_id, rates, aliases=aliases
                )
            except ValueError as e:
                console.print(f"[red]Error:[/red] {e}")
                return

            # Build subtitle with hypotheticals
            hypo_desc = ", ".join(args.hypotheticals)
            subtitle = f"[magenta]Hypothetical:[/magenta] [bold]{hypo_desc}[/bold]"
        else:
            active_personnel = personnel
            subtitle = None

        # Build period info text
        period_parts = []
        if args.fy:
            period_parts.append(
                f"[bold]FY {args.fy}[/bold] [dim](Jul {args.fy - 1} - Jun {args.fy})[/dim]"
            )
        elif contract_year_label and period_start_override:
            period_parts.append(
                f"[bold]Year {contract_year_label}[/bold] [dim]({period_start_override.strftime('%b %Y')} - {period_end_override.strftime('%b %Y')})[/dim]"  # type: ignore[union-attr]
            )

        if project_end:
            period_parts.append(f"Through [cyan]{project_end.strftime('%B %Y')}[/cyan]")
        else:
            period_parts.append("[dim](No end date - showing 12 months)[/dim]")

        period_info = " • ".join(period_parts)
        if subtitle:
            period_info = f"{subtitle}\n{period_info}"

        # Build personnel assumptions list
        # Get personnel with effort on this project (for current or near-future months)
        personnel_lines = []
        check_date = (period_start_override or date.today()).replace(day=1)
        for person in active_personnel:
            for assignment in person.assignments:
                if assignment.project != project_id:
                    continue
                # Check if assignment will be active during the projection period
                if assignment.start and check_date < assignment.start:
                    continue
                if assignment.end and check_date >= assignment.end:
                    continue
                if person.departure and check_date >= person.departure:
                    continue
                if assignment.effort <= 0:
                    continue

                effort_pct = int(assignment.effort * 100)
                # Use shorter type names for display
                type_display = {
                    "grad_student": "PhD",
                    "masters_student": "Masters",
                    "postdoc": "Postdoc",
                    "faculty": "Faculty",
                    "staff": "Staff",
                }.get(person.person_type, person.person_type)

                # Determine effective end date (earliest of assignment end and departure)
                effective_end = None
                if assignment.end and person.departure:
                    effective_end = min(assignment.end, person.departure)
                elif assignment.end:
                    effective_end = assignment.end
                elif person.departure:
                    effective_end = person.departure

                # Show end date if it's within the projection period
                end_suffix = ""
                if effective_end and project_end and effective_end < project_end:
                    end_suffix = f" [yellow](thru {effective_end.strftime('%b %Y')})[/yellow]"
                elif effective_end and not project_end:
                    # No project end, but person has an end date - show it
                    end_suffix = f" [yellow](thru {effective_end.strftime('%b %Y')})[/yellow]"

                personnel_lines.append(
                    f"[dim]{type_display}[/dim] {Anonymizer.anonymize(person.name)} [cyan]{effort_pct}%[/cyan]{end_suffix}"
                )

        if personnel_lines:
            personnel_info = "[bold]Personnel:[/bold] " + ", ".join(personnel_lines)
            period_info = f"{period_info}\n{personnel_info}"

        # Print header panel
        console.print()
        console.print(
            Panel(
                period_info,
                title=f"[bold cyan]Spend Plan: {project_id}[/bold cyan]",
                border_style="cyan",
                padding=(0, 2),
            )
        )
        console.print()

        # If compare mode, compute baseline first
        baseline_total = Decimal("0")
        if args.compare and hypotheticals:
            current = date.today().replace(day=1)
            months_computed = 0
            max_months = 60 if project_end else 12

            while months_computed < max_months:
                if project_end and current >= project_end:
                    break
                proj = project_monthly_costs(
                    project_id,
                    rates,
                    personnel,
                    current.year,
                    current.month,
                    travel_items,
                    expense_items,
                )
                if proj.total == 0 and months_computed > 0:
                    break
                baseline_total += proj.total
                if current.month == 12:
                    current = current.replace(year=current.year + 1, month=1)
                else:
                    current = current.replace(month=current.month + 1)
                months_computed += 1

        # Create the table
        table = Table(
            box=box.ROUNDED,
            show_header=True,
            header_style="bold",
            row_styles=["", "dim"],  # Alternating row styles
            border_style="dim",
            expand=False,  # Don't collapse columns
        )

        # Add columns with proper alignment and no_wrap to prevent truncation
        table.add_column("Month", style="cyan", no_wrap=True, min_width=10)
        table.add_column("Salary", justify="right", no_wrap=True, min_width=12)
        table.add_column("Fringe", justify="right", no_wrap=True, min_width=10)
        table.add_column("Travel", justify="right", no_wrap=True, min_width=10)
        table.add_column("Compute", justify="right", no_wrap=True, min_width=10)
        table.add_column("Equip", justify="right", no_wrap=True, min_width=10)
        table.add_column("Other", justify="right", no_wrap=True, min_width=10)
        table.add_column("IDC", justify="right", no_wrap=True, min_width=10)
        table.add_column("Total", justify="right", style="bold", no_wrap=True, min_width=12)

        total_salary = Decimal("0")
        total_fringe = Decimal("0")
        total_idc = Decimal("0")
        total_tuition = Decimal("0")
        total_insurance = Decimal("0")
        total_travel = Decimal("0")
        total_compute = Decimal("0")
        total_equip = Decimal("0")
        total_other = Decimal("0")
        total_all = Decimal("0")

        # Track detail rows to add after main table rows
        detail_rows = []

        # For fiscal year or contract year, start from the period start; otherwise start from today
        current = period_start_override or date.today().replace(day=1)
        months_shown = 0
        max_months = 60 if project_end else 12  # Cap at 5 years or 12 months

        while months_shown < max_months:
            if project_end and current >= project_end:
                break

            proj = project_monthly_costs(
                project_id,
                rates,
                active_personnel,
                current.year,
                current.month,
                travel_items,
                expense_items,
            )

            # Skip months with no spending
            if proj.total == 0:
                if months_shown > 0:  # Only stop if we've shown something
                    break
                # Otherwise advance to next month
                if current.month == 12:
                    current = current.replace(year=current.year + 1, month=1)
                else:
                    current = current.replace(month=current.month + 1)
                continue

            month_str = f"{current.year}-{current.month:02d}"
            today = date.today()

            # Style the month based on past/current/future
            if current.year == today.year and current.month == today.month:
                month_display = f"[bold cyan]{month_str}[/bold cyan] ◀"
            elif date(current.year, current.month, 1) < today.replace(day=1):
                month_display = f"[dim]{month_str}[/dim]"
            else:
                month_display = month_str

            # Style the total based on amount
            if proj.total >= 100000:
                total_style = "[bold red]"
            elif proj.total >= 50000:
                total_style = "[yellow]"
            else:
                total_style = "[green]"

            table.add_row(
                month_display,
                f"${proj.direct_salary:,.2f}",
                f"${proj.fringe:,.2f}",
                f"${proj.travel:,.2f}",
                f"${proj.compute:,.2f}",
                f"${proj.equipment:,.2f}",
                f"${proj.other_direct:,.2f}",
                f"${proj.indirect:,.2f}",
                f"{total_style}${proj.total:,.2f}[/]",
            )

            # Build detail rows if any
            details = []
            if proj.travel_detail:
                for item in proj.travel_detail:
                    desc = (
                        item.description
                        if len(item.description) < 35
                        else item.description[:32] + "..."
                    )
                    status_style = "green" if item.status.value == "actualized" else "yellow"
                    details.append(
                        f"    [cyan]▸[/cyan] [bold]Travel:[/bold] {desc} [green]${item.amount:,.2f}[/green] [{status_style}]({item.status.value})[/{status_style}]"
                    )
            if proj.expense_detail:
                for expense_item in proj.expense_detail:
                    if expense_item.is_recurring:
                        continue
                    desc = (
                        expense_item.description
                        if len(expense_item.description) < 35
                        else expense_item.description[:32] + "..."
                    )
                    details.append(
                        f"    [cyan]▸[/cyan] [bold]{expense_item.category}:[/bold] {desc} [green]${expense_item.amount:,.2f}[/green]"
                    )

            if details:
                detail_rows.append((months_shown, details))

            total_salary += proj.direct_salary
            total_fringe += proj.fringe
            total_idc += proj.indirect
            total_tuition += proj.tuition
            total_insurance += proj.insurance
            total_travel += proj.travel
            total_compute += proj.compute
            total_equip += proj.equipment
            total_other += proj.other_direct
            total_all += proj.total

            # Next month
            if current.month == 12:
                current = current.replace(year=current.year + 1, month=1)
            else:
                current = current.replace(month=current.month + 1)
            months_shown += 1

        # Add totals row with section divider
        table.add_section()

        # Color-code the grand total based on amount
        if total_all >= 500000:
            total_color = "bold red"
        elif total_all >= 200000:
            total_color = "bold yellow"
        else:
            total_color = "bold green"

        table.add_row(
            "[bold]TOTAL[/bold]",
            f"[bold]${total_salary:,.2f}[/bold]",
            f"[bold]${total_fringe:,.2f}[/bold]",
            f"[bold]${total_travel:,.2f}[/bold]",
            f"[bold]${total_compute:,.2f}[/bold]",
            f"[bold]${total_equip:,.2f}[/bold]",
            f"[bold]${total_other:,.2f}[/bold]",
            f"[bold]${total_idc:,.2f}[/bold]",
            f"[{total_color}]${total_all:,.2f}[/{total_color}]",
            style="bold",
        )

        console.print(table)

        # Print detail rows
        if detail_rows:
            console.print()
            for _, details in detail_rows:
                for detail in details:
                    console.print(detail)

        # Show comparison if requested
        if args.compare and hypotheticals:
            delta = total_all - baseline_total
            delta_str = f"+${delta:,.0f}" if delta >= 0 else f"-${abs(delta):,.0f}"
            delta_color = "red" if delta > 0 else "green"

            console.print()
            console.print(
                Panel(
                    f"[bold]Current total:[/bold]      ${baseline_total:>12,.0f}\n"
                    f"[bold]Hypothetical total:[/bold] ${total_all:>12,.0f}\n"
                    f"[bold]Delta:[/bold]              [{delta_color}]{delta_str:>13}[/{delta_color}]",
                    title="[bold]Comparison[/bold]",
                    border_style="magenta",
                    padding=(0, 2),
                )
            )


def cmd_budget_vs_actuals(store: ProjectStore, args) -> None:
    """Compare projected spending against contractual budget ceilings.

    Rendering only: the figures come from SmaugAPI.budget_vs_actuals so the CLI
    and the MCP tools cannot drift apart on how a period's actual is derived.
    """
    from decimal import Decimal

    from ..api import SmaugAPI

    project_id = args.project
    result = SmaugAPI(args.data_dir).budget_vs_actuals(project_id)
    if "error" in result:
        print(f"Error: {result['error']}")
        return

    status_styles = {
        "underspend": ("⚠ Underspend", Colors.YELLOW),
        "under": ("✓ Under", Colors.GREEN),
        "overspend": ("⚠ Overspend", Colors.RED),
        "on_track": ("→ On Track", Colors.GREEN),
        "tight": ("→ Tight", Colors.YELLOW),
        "planned": ("○ Planned", Colors.BLUE),
    }

    print(f"\n{color('=== Budget vs Actuals: ' + project_id + ' ===', Colors.BOLD + Colors.CYAN)}")
    print(f"Award: {result['award_id']} | Total Budget: ${result['total_budget']:,.0f}\n")

    header = f"{'Period':<10} {'Dates':<25} {'Budget':>14} {'Actual':>14} {'Projected':>14} {'Variance':>12} {'Status':<12}"
    print(color(header, Colors.BOLD))
    print(color("─" * 105, Colors.DIM))

    def money(value: float) -> str:
        return f"${value:>12,.0f}" if value > 0 else f"{'-':>14}"

    def variance_cell(value: float) -> str:
        text = f"${value:>10,.0f}" if value >= 0 else f"-${abs(value):>9,.0f}"
        return color(text, Colors.RED if value < 0 else Colors.GREEN)

    for period in result["periods"]:
        label, style = status_styles.get(period["status"], (period["status"], Colors.DIM))
        print(
            f"{'Year ' + str(period['year_num']):<10} {period['dates']:<25} "
            f"${period['budget']:>12,.0f} {money(period['actual'])} "
            f"{money(period['projected'])} {variance_cell(period['variance']):>21} "
            f"{color(label, style)}"
        )

    print(color("─" * 105, Colors.DIM))
    print(
        f"{color('TOTAL', Colors.BOLD):<10} {'':<25} ${result['total_budget']:>12,.0f} "
        f"{money(result['total_actual'])} {money(result['total_projected'])} "
        f"{variance_cell(result['total_variance']):>21}"
    )

    opening = result.get("opening_balance")
    if opening:
        print()
        print(
            color(
                f"Note: ${opening['amount']:,.0f} was spent before the earliest available "
                f"report ({opening['covers']}).",
                Colors.DIM,
            )
        )
        print(color("      It is spread evenly across those months; no monthly", Colors.DIM))
        print(color("      detail exists to split it exactly.", Colors.DIM))

    if not result.get("reconciles", True):
        shortfall = Decimal(str(result["cumulative_spent"])) - Decimal(str(result["total_actual"]))
        print()
        print(
            color(
                f"Warning: period actuals fall ${shortfall:,.2f} short of the "
                f"${result['cumulative_spent']:,.2f} cumulative spend on record.",
                Colors.RED,
            )
        )


def cmd_summary(store: ProjectStore, args) -> None:
    """Show aggregated sponsored funding across all projects for a date range."""
    from datetime import date
    from decimal import Decimal

    from rich import box
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table

    from ..projections import load_personnel_config, project_monthly_costs

    console = Console(width=max(120, Console().width) if Console().width else 120)

    config_path = Path(args.data_dir) / "projects" / "personnel_config.yaml"
    if not config_path.exists():
        console.print(f"[red]Error:[/red] Personnel config not found: {config_path}")
        return

    rates, personnel = load_personnel_config(config_path)
    store.load_travel_config()
    store.load_purchases_config()

    # Determine date range
    today = date.today()
    if args.fy:
        fy_year = int(args.fy)
        range_start = date(fy_year - 1, 7, 1)
        range_end = date(fy_year, 6, 1)  # inclusive last month
        range_label = f"FY {fy_year} (Jul {fy_year - 1} \u2013 Jun {fy_year})"
    else:
        if args.range_from:
            parsed = parse_date_input(args.range_from)
            parts = parsed.split("-")
            range_start = date(int(parts[0]), int(parts[1]), 1)
        else:
            range_start = date(today.year, 1, 1)
        if args.range_to:
            parsed = parse_date_input(args.range_to)
            parts = parsed.split("-")
            range_end = date(int(parts[0]), int(parts[1]), 1)
        else:
            range_end = date(today.year, 12, 1)
        range_label = f"{range_start.strftime('%b %Y')} \u2013 {range_end.strftime('%b %Y')}"

    # Collect all sponsored projects
    sponsored = []
    for pid in store.list_projects():
        data = store.get_project(pid)
        if data and data.project.project_type.value == "sponsored":
            sponsored.append((pid, data))

    if not sponsored:
        console.print("[yellow]No sponsored projects found.[/yellow]")
        return

    # For each project, build a dict of month -> actual spend (delta)
    # Spending reports are cumulative; the delta gives the monthly actual.
    # We anchor deltas against the cumulative value at the end of the month
    # before range_start so the first month only captures in-range spending.
    def build_actuals(data, range_start):
        """Return {(year, month): monthly_spend} from cumulative reports."""
        reports = sorted(data.spending, key=lambda r: (r.year, r.month))
        actuals = {}
        # Find the baseline: cumulative at end of month before range_start
        baseline = Decimal("0")
        for r in reports:
            if date(r.year, r.month, 1) < range_start:
                baseline = r.total_spent
        prev_spent = baseline
        for r in reports:
            if date(r.year, r.month, 1) < range_start:
                continue
            delta = r.total_spent - prev_spent
            actuals[(r.year, r.month)] = delta
            prev_spent = r.total_spent
        return actuals

    # Walk the date range
    grand_actual = Decimal("0")
    grand_projected = Decimal("0")
    rows = []  # (project_id, actual, projected, total)

    for pid, data in sponsored:
        actuals = build_actuals(data, range_start)
        travel_items = store.get_project_travel(pid)
        expense_items = store.get_project_expenses(pid)

        proj_actual = Decimal("0")
        proj_projected = Decimal("0")

        cur = date(range_start.year, range_start.month, 1)
        current_month = today.replace(day=1)
        while cur <= range_end:
            key = (cur.year, cur.month)
            if key in actuals:
                proj_actual += actuals[key]
            elif cur >= current_month:
                # Only project future months; past months without
                # a report are simply $0 actual.
                mp = project_monthly_costs(
                    pid, rates, personnel, cur.year, cur.month, travel_items, expense_items
                )
                proj_projected += mp.total
            # advance
            if cur.month == 12:
                cur = cur.replace(year=cur.year + 1, month=1)
            else:
                cur = cur.replace(month=cur.month + 1)

        proj_total = proj_actual + proj_projected
        rows.append((pid, proj_actual, proj_projected, proj_total))
        grand_actual += proj_actual
        grand_projected += proj_projected

    grand_total = grand_actual + grand_projected

    # Render
    console.print()
    console.print(
        Panel(
            f"[bold]{range_label}[/bold]",
            title="[bold cyan]Sponsored Funding Summary[/bold cyan]",
            border_style="cyan",
            padding=(0, 2),
        )
    )
    console.print()

    table = Table(
        box=box.ROUNDED, show_header=True, header_style="bold", border_style="dim", expand=False
    )
    table.add_column("Project", style="cyan", no_wrap=True, min_width=10)
    table.add_column("Actual", justify="right", no_wrap=True, min_width=14)
    table.add_column("Projected", justify="right", no_wrap=True, min_width=14)
    table.add_column("Total", justify="right", style="bold", no_wrap=True, min_width=14)

    for pid, actual, projected, total in sorted(rows, key=lambda r: -r[3]):
        act_str = f"${actual:,.0f}" if actual else "\u2014"
        proj_str = f"${projected:,.0f}" if projected else "\u2014"
        if total >= 500_000:
            tot_style = "[bold red]"
        elif total >= 200_000:
            tot_style = "[bold yellow]"
        else:
            tot_style = "[green]"
        table.add_row(pid, act_str, proj_str, f"{tot_style}${total:,.0f}[/]")

    table.add_section()
    if grand_total >= 500_000:
        gt_style = "bold red"
    elif grand_total >= 200_000:
        gt_style = "bold yellow"
    else:
        gt_style = "bold green"
    table.add_row(
        "[bold]TOTAL[/bold]",
        f"[bold]${grand_actual:,.0f}[/bold]",
        f"[bold]${grand_projected:,.0f}[/bold]",
        f"[{gt_style}]${grand_total:,.0f}[/{gt_style}]",
        style="bold",
    )

    console.print(table)


def cmd_proposal(store: ProjectStore, args) -> None:
    """Generate a research proposal budget using institutional rates."""
    from rich import box
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table

    from ..models import ProjectStatus
    from ..proposal_budget import (
        ProposalPerson,
        YearBudget,
        generate_proposal_budget,
        load_proposal_rates,
        resolve_salary,
    )

    console = Console(width=max(120, Console().width) if Console().width else 120)

    # Load rates
    try:
        rates_config = load_proposal_rates(args.data_dir)
    except FileNotFoundError as e:
        console.print(f"[red]Error:[/red] {e}")
        return

    personnel_config_path = Path(args.data_dir) / "projects" / "personnel_config.yaml"

    # Build people list — either from a named project or from CLI flags
    people = []
    project_name = getattr(args, "project", None)

    if project_name:
        # Project-based mode: read personnel from config for this project
        data = store.get_project(project_name)
        if not data:
            console.print(f"[red]Error:[/red] Project '{project_name}' not found in manifest")
            return

        if not personnel_config_path.exists():
            console.print(f"[red]Error:[/red] No personnel config found: {personnel_config_path}")
            return

        import yaml

        with open(personnel_config_path) as f:
            config = yaml.safe_load(f) or {}

        gs_costs = rates_config.get("grad_student_costs", {})

        for person in config.get("personnel", []):
            # Check if this person has an assignment to the target project
            assignments = person.get("assignments", [])
            project_effort = Decimal("0")
            for assignment in assignments:
                if assignment.get("project") == project_name:
                    project_effort += Decimal(str(assignment.get("effort", 0)))

            if project_effort == 0:
                continue  # Not assigned to this project

            person_type = person.get("type", "staff")
            salary = Decimal(str(person.get("annual_salary", gs_costs.get("stipend", 50000))))
            label = Anonymizer.anonymize(person["name"]) or person["name"]

            # Mark PI if faculty
            if person_type == "faculty":
                label += " (PI)"

            people.append(
                ProposalPerson(
                    label=label,
                    person_type=person_type,
                    effort=project_effort,
                    annual_salary=salary,
                )
            )

        if not people:
            console.print(
                f"[yellow]No personnel assigned to {project_name} in personnel_config.yaml[/yellow]"
            )
            return

        console.print(f"[bold]Generating proposal budget for project: {project_name}[/bold]")
        if data.project.status == ProjectStatus.PROPOSED:
            console.print("[dim]Status: proposed[/dim]")
    else:
        # CLI flag mode (original behavior)
        # Parse --pi and --person specs: "Name=effort%"
        type_map = {
            "pi": "faculty",
            "faculty": "faculty",
            "postdoc": "postdoc",
            "staff": "staff",
        }

        named_specs = []
        if args.pi:
            for spec in args.pi:
                named_specs.append(("faculty", spec, True))
        if args.person:
            for ptype, spec in args.person:
                named_specs.append((type_map.get(ptype, ptype), spec, False))

        for person_type, spec, is_pi in named_specs:
            # Parse "Name=effort%"
            if "=" not in spec:
                console.print(
                    f"[red]Error:[/red] Invalid format '{spec}'. Use 'Name=effort%' (e.g., 'Smith=10%')"
                )
                return
            name_part, effort_part = spec.rsplit("=", 1)
            effort_str = effort_part.rstrip("%")
            try:
                effort = Decimal(effort_str) / 100
            except Exception:
                console.print(f"[red]Error:[/red] Invalid effort '{effort_part}' in '{spec}'")
                return

            salary, resolved_name = resolve_salary(
                name_part.strip(), person_type, personnel_config_path, rates_config
            )

            label = Anonymizer.anonymize(resolved_name) or resolved_name or name_part.strip()
            if is_pi:
                label += " (PI)"

            people.append(
                ProposalPerson(
                    label=label,
                    person_type=person_type,
                    effort=effort,
                    annual_salary=salary,
                )
            )

        # Parse --phd N (generic PhD students at stipend rate)
        if args.phd:
            gs_costs = rates_config.get("grad_student_costs", {})
            stipend = Decimal(str(gs_costs.get("stipend", 50000)))
            for i in range(args.phd):
                people.append(
                    ProposalPerson(
                        label=f"PhD Student #{i + 1}",
                        person_type="grad_student",
                        effort=Decimal("1.0"),
                        annual_salary=stipend,
                    )
                )

        # Parse --masters N (full tuition, hourly RA rate from rates.yaml)
        if args.masters:
            hourly = Decimal(str(rates_config.get("masters_hourly", 20)))
            hrs_per_week = Decimal(str(rates_config.get("masters_hours_per_week", 20)))
            # Annual salary = hourly x hours/week x 52 weeks
            annual_salary = hourly * hrs_per_week * 52
            for i in range(args.masters):
                people.append(
                    ProposalPerson(
                        label=f"Masters Student #{i + 1}",
                        person_type="part_time",
                        effort=Decimal("1.0"),
                        annual_salary=annual_salary,
                        student_type="masters",
                        include_tuition=not args.no_masters_tuition,
                    )
                )

        if not people:
            console.print(
                "[red]Error:[/red] No personnel specified. Use a project name, or --pi, --person, --phd, --masters."
            )
            return

    # Generate budget
    budget = generate_proposal_budget(
        people=people,
        rates_config=rates_config,
        num_years=args.years,
        travel_per_year=Decimal(str(args.travel)) if args.travel else Decimal("0"),
        compute_per_year=Decimal(str(args.compute)) if args.compute else Decimal("0"),
        annotation_per_year=Decimal(str(args.annotation)) if args.annotation else Decimal("0"),
        equipment_year1=Decimal(str(args.equipment)) if args.equipment else Decimal("0"),
        other_per_year=Decimal(str(args.other)) if args.other else Decimal("0"),
        salary_escalation=Decimal(str(args.escalation / 100)),
    )

    # Display header
    idc_rate = budget.idc_rate
    fringe_rates = rates_config.get("fringe_rates", {})
    gs_costs = rates_config.get("grad_student_costs", {})

    header_lines = []
    header_lines.append(f"[bold]Duration:[/bold] {args.years} year{'s' if args.years > 1 else ''}")
    header_lines.append(f"[bold]IDC Rate:[/bold] {float(idc_rate) * 100:.1f}% (MTDC)")
    header_lines.append(f"[bold]Salary Escalation:[/bold] {args.escalation}% per year")
    header_lines.append("")
    header_lines.append("[bold]Personnel:[/bold]")
    for p in people:
        fringe_rate = fringe_rates.get(p.person_type, 0.315)
        effort_pct = int(p.effort * 100)
        type_display = {
            "grad_student": "PhD",
            "masters_student": "Masters",
            "part_time": "Masters",
            "postdoc": "Postdoc",
            "faculty": "Faculty",
            "staff": "Staff",
        }.get(p.person_type, p.person_type)
        # For masters students, show hours/week instead of effort % since
        # their part-time hours are baked into the salary
        if p.student_type == "masters":
            hrs_per_week = rates_config.get("masters_hours_per_week", 20)
            effort_display = f"{hrs_per_week} hrs/wk"
        else:
            effort_display = f"{effort_pct}% effort"
        header_lines.append(
            f"  [cyan]{p.label}[/cyan] — {type_display}, "
            f"{effort_display}, ${p.annual_salary:,.0f}/yr, "
            f"fringe {float(fringe_rate) * 100:.1f}%"
        )

    console.print()
    console.print(
        Panel(
            "\n".join(header_lines),
            title="[bold cyan]Proposal Budget[/bold cyan]",
            border_style="cyan",
            padding=(0, 2),
        )
    )

    # Personnel detail table
    detail_table = Table(
        title="Personnel Cost Detail",
        box=box.ROUNDED,
        show_header=True,
        header_style="bold",
        title_style="bold",
    )
    detail_table.add_column("Person", style="cyan", min_width=25)
    detail_table.add_column("Type", min_width=8)
    detail_table.add_column("Effort", justify="right", min_width=7)
    for y in range(1, args.years + 1):
        detail_table.add_column(f"Year {y}", justify="right", min_width=12)
    if args.years > 1:
        detail_table.add_column("Total", justify="right", min_width=12, style="bold")

    for idx, person in enumerate(people):
        # Show hours/week for masters instead of misleading 100%
        if person.student_type == "masters":
            hrs_per_week = rates_config.get("masters_hours_per_week", 20)
            effort_str = f"{hrs_per_week} hrs/wk"
        else:
            effort_str = f"{int(person.effort * 100)}%"
        row = [
            person.label,
            {
                "grad_student": "PhD",
                "masters_student": "Masters",
                "part_time": "Masters",
                "postdoc": "Postdoc",
                "faculty": "Faculty",
                "staff": "Staff",
            }.get(person.person_type, person.person_type),
            effort_str,
        ]
        person_total = Decimal("0")
        for year_num in range(1, args.years + 1):
            details = budget.personnel_detail[year_num]
            d = details[idx]
            year_cost = d.total
            person_total += year_cost
            row.append(f"${year_cost:,.0f}")
        if args.years > 1:
            row.append(f"${person_total:,.0f}")
        detail_table.add_row(*row)

    # Add per-year salary subtotals
    detail_table.add_section()
    salary_row = ["[bold]Salary Subtotal[/bold]", "", ""]
    for year_num in range(1, args.years + 1):
        yb: YearBudget = budget.years[year_num - 1]
        salary_row.append(f"[bold]${yb.salary:,.0f}[/bold]")
    if args.years > 1:
        salary_row.append(f"[bold]${sum(y.salary for y in budget.years):,.0f}[/bold]")
    detail_table.add_row(*salary_row)

    fringe_row = ["[bold]Fringe Subtotal[/bold]", "", ""]
    for year_num in range(1, args.years + 1):
        yb = budget.years[year_num - 1]
        fringe_row.append(f"[bold]${yb.fringe:,.0f}[/bold]")
    if args.years > 1:
        fringe_row.append(f"[bold]${sum(y.fringe for y in budget.years):,.0f}[/bold]")
    detail_table.add_row(*fringe_row)

    console.print()
    console.print(detail_table)

    # Summary budget table
    summary_table = Table(
        title="Budget Summary",
        box=box.ROUNDED,
        show_header=True,
        header_style="bold",
        title_style="bold",
    )
    summary_table.add_column("Category", style="cyan", min_width=22)
    for y in range(1, args.years + 1):
        summary_table.add_column(f"Year {y}", justify="right", min_width=12)
    if args.years > 1:
        summary_table.add_column("Total", justify="right", min_width=14, style="bold")

    def _sum_field(field_name):
        return sum(getattr(y, field_name) for y in budget.years)

    # Direct costs
    categories = [
        ("Salaries & Wages", "salary"),
        ("Fringe Benefits", "fringe"),
        ("Tuition", "tuition"),
        ("Health & Dental Ins.", "insurance"),
        ("Travel", "travel"),
        ("Compute / Cloud", "compute"),
        ("Annotation", "annotation"),
        ("Equipment", "equipment"),
        ("Other Direct Costs", "other"),
    ]

    for label, field_name in categories:
        total = _sum_field(field_name)
        if total == 0:
            continue
        row = [label]
        for yb in budget.years:
            val = getattr(yb, field_name)
            row.append(f"${val:,.0f}" if val > 0 else "[dim]—[/dim]")
        if args.years > 1:
            row.append(f"${total:,.0f}")
        summary_table.add_row(*row)

    # Total Direct Costs
    summary_table.add_section()
    tdc_row = ["[bold]Total Direct Costs[/bold]"]
    for yb in budget.years:
        tdc_row.append(f"[bold]${yb.total_direct:,.0f}[/bold]")
    if args.years > 1:
        tdc_row.append(f"[bold]${budget.total_direct:,.0f}[/bold]")
    summary_table.add_row(*tdc_row)

    # IDC
    idc_row = [f"[bold]F&A ({float(idc_rate) * 100:.0f}% MTDC)[/bold]"]
    for yb in budget.years:
        idc_row.append(f"${yb.idc(idc_rate):,.0f}")
    if args.years > 1:
        idc_row.append(f"${budget.total_idc:,.0f}")
    summary_table.add_row(*idc_row)

    # Grand Total
    summary_table.add_section()
    grand_row = ["[bold green]GRAND TOTAL[/bold green]"]
    for yb in budget.years:
        grand_row.append(f"[bold green]${yb.total_with_idc(idc_rate):,.0f}[/bold green]")
    if args.years > 1:
        grand_row.append(f"[bold green]${budget.grand_total:,.0f}[/bold green]")
    summary_table.add_row(*grand_row)

    # Total without overhead
    summary_table.add_section()
    no_oh_row = ["[dim]Without F&A[/dim]"]
    for yb in budget.years:
        no_oh_row.append(f"[dim]${yb.total_direct:,.0f}[/dim]")
    if args.years > 1:
        no_oh_row.append(f"[dim]${budget.total_direct:,.0f}[/dim]")
    summary_table.add_row(*no_oh_row)

    console.print()
    console.print(summary_table)
    console.print()


def cmd_optimize(store: ProjectStore, args) -> None:
    """CLI handler for budget mitigation optimizer."""
    from rich import box
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table

    from ..projections import optimize_mitigations

    console = Console()
    project_id = args.project

    config_path = Path(args.data_dir) / "projects" / "personnel_config.yaml"
    if not config_path.exists():
        console.print(f"[red]Error:[/red] Personnel config not found: {config_path}")
        return

    plans = optimize_mitigations(project_id, config_path, store, target_months=args.target_months)

    console.print()
    console.print(
        Panel(
            f"Analyzing available budget mitigations for project: [bold cyan]{project_id}[/bold cyan] "
            f"to extend funding stop-work date (Target: {args.target_months} months).",
            title="[bold green]Budget Mitigation Optimizer[/bold green]",
            border_style="green",
        )
    )
    console.print()

    for plan in plans:
        table = Table(
            title=f"[bold yellow]{plan['name']}[/bold yellow]",
            box=box.ROUNDED,
            border_style="yellow",
            show_header=True,
        )
        table.add_column("Applied Mitigation Lever", style="cyan")

        for lever in plan["levers"]:
            table.add_row(lever)

        console.print(table)
        console.print(f"[bold green]Extension:[/bold green] +{plan['extension']:.1f} months")
        console.print(
            f"[bold green]New Stop-Work Forecast:[/bold green] {plan['extended_stop_work_months']:.1f} months from now"
        )
        console.print(f"[dim]{plan['description']}[/dim]")
        console.print()
