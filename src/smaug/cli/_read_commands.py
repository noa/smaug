"""Read-only CLI commands that query data without side effects."""

from datetime import date
from decimal import Decimal
from pathlib import Path

from ..projections import format_projection_report, project_spending
from ..store import ProjectStore
from ._util import (
    Anonymizer,
    Colors,
    color,
    color_pct,
    color_remaining,
    load_aliases,
    resolve_personnel_name,
)


def cmd_list(store: ProjectStore, args) -> None:
    """List all tracked projects with budget summary."""
    from ..api import SmaugAPI

    # Determine status filter
    show_all = getattr(args, "all", False)
    status_filter = getattr(args, "status", None)

    if status_filter:
        from ..models import ProjectStatus

        try:
            ProjectStatus(status_filter)
        except ValueError:
            print(
                f"Invalid status: {status_filter}. Options: proposed, accepted, active, completed"
            )
            return

    api = SmaugAPI(args.data_dir)

    if show_all:
        # Get all statuses
        results = []
        for s in ["active", "proposed", "accepted", "completed"]:
            results.extend(api.list_projects(status=s))
        # Deduplicate by id
        seen = set()
        deduped = []
        for r in results:
            if r["id"] not in seen:
                seen.add(r["id"])
                deduped.append(r)
        results = deduped
    else:
        results = api.list_projects(status=status_filter)

    if not results:
        print("No projects found. Check manifest.yaml")
        return

    # Print header with color
    header = f"{'Project':<10} {'Status':<10} {'Ends':<10} {'Budget':>14} {'Spent':>14} {'% Spent':>8} {'Mo.Burn':>12} {'Proj.Total':>14} {'Proj.Rem':>14}"
    print(color(header, Colors.BOLD + Colors.CYAN))
    print(color("-" * 118, Colors.DIM))

    for proj in results:
        status_str = proj["status"]
        status_display = (
            color(status_str, Colors.DIM)
            if status_str == "active"
            else color(status_str, Colors.YELLOW)
        )

        project_str = color(proj["id"], Colors.BOLD)
        budget = proj["budget"] or 0
        spent = proj["spent"] or 0
        monthly_burn = proj["monthly_burn"] or 0
        proj_total = proj["projected_total"] or 0
        remaining = proj["projected_remaining"] or 0
        pct_spent = proj["pct_spent"]

        # For proposed/accepted projects, show a simpler row
        if status_str in ("proposed", "accepted"):
            budget_str = f"${budget:,.0f}" if budget else "-"
            end_str = proj["end_date"] or "-"
            print(
                f"{project_str:<19} {status_display:<19} {end_str:<10} {budget_str:>14} {'-':>14} {'-':>17} {'-':>12} {'-':>14} {'-':>23}"
            )
            continue

        # Format values with colors
        budget_str = f"${budget:,.0f}" if budget else "-"
        spent_str = f"${spent:,.0f}" if spent else "-"
        pct_str = color_pct(pct_spent) if budget else "-"
        burn_str = f"${monthly_burn:,.0f}" if monthly_burn else "-"
        proj_str = f"${proj_total:,.0f}" if proj_total else "-"
        end_str = proj["end_date"] or "-"
        remain_str = (
            color_remaining(Decimal(str(remaining)), Decimal(str(budget))) if budget else "-"
        )

        print(
            f"{project_str:<19} {status_display:<19} {end_str:<10} {budget_str:>14} {spent_str:>14} {pct_str:>17} {burn_str:>12} {proj_str:>14} {remain_str:>23}"
        )


def cmd_status(store: ProjectStore, args) -> None:
    """Show budget vs actual status for a project."""
    from ..api import SmaugAPI

    api = SmaugAPI(args.data_dir)
    result = api.project_status(args.project)

    if "error" in result:
        print(result["error"])
        return

    proj = result["project"]
    print(f"\n=== {proj['name']} ===")
    print(f"PI: {Anonymizer.anonymize(proj['pi'])}")
    print(f"Type: {proj['type']}")

    if proj.get("grant_number"):
        print(f"Grant #: {proj['grant_number']}")
    if proj.get("award_id"):
        print(f"Award ID: {proj['award_id']}")

    # Budget summary
    if result["budget"]:
        b = result["budget"]
        print("\n--- Budget ---")
        print(f"Total Direct Costs:   ${b['total_direct_costs']:>12,.2f}")
        print(f"Total Indirect Costs: ${b['total_indirect_costs']:>12,.2f}")
        print(f"Total Budget:         ${b['total_budget']:>12,.2f}")

    # Latest spending
    sp = result["latest_spending"]
    if sp:
        print(f"\n--- Spending ({sp['period']}) ---")
        print(f"Total Spent:           ${sp['total_spent']:>12,.2f}")
        print(f"Total Committed:       ${sp['total_committed']:>12,.2f}")
        print(f"Total Spent+Committed: ${sp['total_spent_and_committed']:>12,.2f}")
        if sp.get("budget_utilized_pct"):
            print(f"Budget Utilized:       {sp['budget_utilized_pct']:>12.1f}%")
        if sp.get("funded_ceiling"):
            print(f"Funded Ceiling:        ${sp['funded_ceiling']:>12,.2f}")

        # Category breakdown if available
        cats = result.get("categories", {})
        has_categories = cats and any(
            cats.get(k)
            for k in [
                "salary",
                "fringe",
                "tuition",
                "insurance",
                "service_center",
                "travel",
                "other",
            ]
        )
        if has_categories:
            print("\n--- Category Breakdown (Cumulative) ---")
            print(f"  Salaries & Wages:    ${cats['salary']:>12,.2f}")
            print(f"  Fringe Benefits:     ${cats['fringe']:>12,.2f}")
            if cats.get("tuition"):
                print(f"  Tuition & Fees:      ${cats['tuition']:>12,.2f}")
            if cats.get("insurance"):
                print(f"  Health Insurance:    ${cats['insurance']:>12,.2f}")
            if cats.get("service_center"):
                print(f"  Service Center:      ${cats['service_center']:>12,.2f}")
            if cats.get("travel"):
                print(f"  Travel:              ${cats['travel']:>12,.2f}")
            if cats.get("other"):
                print(f"  Other Expenses:      ${cats['other']:>12,.2f}")
            print(f"  Indirect Costs:      ${cats['indirect']:>12,.2f}")

        # Compare to budget
        if result.get("remaining") is not None and result.get("pct_remaining") is not None:
            print(
                f"\nRemaining Budget:      ${result['remaining']:>12,.2f} ({result['pct_remaining']:.1f}%)"
            )


def cmd_state_of_play(store: ProjectStore, args) -> None:
    """Show comprehensive state of play summary for a project."""
    import json

    from ..api import SmaugAPI

    api = SmaugAPI(args.data_dir)
    result = api.project_state_of_play(args.project)

    if "error" in result:
        print(result["error"])
        return

    if getattr(args, "json", False):
        print(json.dumps(result, indent=2))
        return

    proj = result["project"]
    status_label = result["health_status"].upper()
    if result["health_status"] == "healthy":
        status_colored = color(f"[{status_label}]", Colors.GREEN + Colors.BOLD)
    elif result["health_status"] == "critical":
        status_colored = color(f"[{status_label}]", Colors.RED + Colors.BOLD)
    else:
        status_colored = color(f"[{status_label}]", Colors.YELLOW + Colors.BOLD)

    print(f"\n=== State of Play: {proj['name']} ({proj['id']}) {status_colored} ===")
    print(
        f"PI: {proj['pi']}  |  Type: {proj['type'].capitalize()}  |  Status: {proj['status'].capitalize()}"
    )
    if proj.get("grant_number"):
        print(f"Grant #: {proj['grant_number']}  |  Award ID: {proj.get('award_id') or 'N/A'}")
    if proj.get("end_date"):
        print(f"End Date: {proj['end_date']}")

    # Warnings
    warnings = result.get("warnings", [])
    if warnings:
        print(f"\n{color('--- Actionable Warnings & Alerts ---', Colors.YELLOW + Colors.BOLD)}")
        for w in warnings:
            if "Critical" in w or "exceeded" in w.lower() or "precedes" in w.lower():
                print(f"  {color('🚨', Colors.RED)} {color(w, Colors.RED)}")
            else:
                print(f"  {color('⚠️', Colors.YELLOW)} {color(w, Colors.YELLOW)}")
    else:
        print(f"\n{color('✓ All checks clear (no active warnings)', Colors.GREEN)}")

    # Spending overview
    so = result.get("spending_overview", {})
    b = so.get("budget", {})
    act = so.get("actuals", {})
    br = so.get("burn_rate", {})

    print(f"\n{color('--- Financial Overview ---', Colors.BOLD)}")
    if b.get("total_budget"):
        print(f"Total Budget:          ${b['total_budget']:>12,.2f}")
    if b.get("funded_ceiling"):
        print(f"Funded Ceiling:        ${b['funded_ceiling']:>12,.2f}")
    if act.get("total_spent") is not None:
        rep_str = f" ({act.get('latest_report_period')})" if act.get("latest_report_period") else ""
        print(f"Total Spent{rep_str:<12}: ${act['total_spent']:>12,.2f}")
        print(f"Total Committed:       ${act['total_committed']:>12,.2f}")
        print(f"Total Spent+Committed: ${act['total_spent_and_committed']:>12,.2f}")
    if act.get("remaining_balance") is not None:
        rem_str = color_remaining(act["remaining_balance"], b.get("total_budget") or 0)
        pct_str = f"({act['pct_remaining']:.1f}%)" if act.get("pct_remaining") is not None else ""
        print(f"Remaining Balance:     {rem_str:>12} {pct_str}")
    if br.get("current_monthly_burn"):
        print(f"Current Monthly Burn:  ${br['current_monthly_burn']:>12,.2f}")
    if br.get("projected_average_monthly_burn"):
        print(f"Projected Avg Burn:    ${br['projected_average_monthly_burn']:>12,.2f}/mo")

    # Categories
    cats = act.get("category_breakdown", {})
    if cats and any(cats.values()):
        print(f"\n{color('--- Spending Categories (Cumulative) ---', Colors.BOLD)}")
        for cat_name, cat_val in cats.items():
            if cat_val > 0:
                pct = act.get("category_percentages", {}).get(cat_name, 0.0)
                print(
                    f"  {cat_name.replace('_', ' ').capitalize():<22} ${cat_val:>12,.2f}  ({pct:>4.1f}%)"
                )

    # Forecast & Runway
    fc = result.get("forecast", {})
    if fc.get("stop_work_month") or fc.get("months_to_stopwork") is not None:
        print(f"\n{color('--- Runway & Forecast ---', Colors.BOLD)}")
        if fc.get("stop_work_month"):
            print(
                f"Stop-Work Date:        {fc['stop_work_month']} ({fc.get('stop_work_day') or 'end of month'})"
            )
        if fc.get("months_to_stopwork") is not None:
            print(f"Runway Remaining:      {fc['months_to_stopwork']} months")

    # Personnel
    pers = result.get("personnel", {})
    allocs = pers.get("current_allocations", [])
    if allocs:
        print(f"\n{color('--- Current Personnel on Project ---', Colors.BOLD)}")
        print(
            f"Active Team: {pers.get('active_headcount', 0)} people  |  Total Effort: {pers.get('total_effort_fte', 0.0):.2f} FTE"
        )
        print(f"{'Name':<24} {'Role':<14} {'Effort':>8} {'Monthly Cost':>14} {'End Date':>10}")
        print("-" * 74)
        for a in allocs:
            end_str = a.get("assignment_end") or "None"
            print(
                f"{a['name']:<24} {a['type']:<14} {a['effort_pct']:>7.1f}% ${a['monthly_total_cost']:>12,.2f} {end_str:>10}"
            )

    # Commitments & Plans
    cp = result.get("commitments_and_plans", {})
    travels = cp.get("travel_items", [])
    expenses = cp.get("expense_items", [])
    if travels or expenses:
        print(f"\n{color('--- Commitments & Planned Items ---', Colors.BOLD)}")
        if travels:
            print("Planned Travel:")
            for t in travels:
                print(
                    f"  • {t.get('description', '')} ({t.get('date', 'N/A')}): ${t.get('amount', 0.0):,.2f}"
                )
        if expenses:
            print("Planned Expenses:")
            for e in expenses:
                print(
                    f"  • {e.get('description', '')} [{e.get('category', 'Other')}]: ${e.get('amount', 0.0):,.2f}"
                )
    print()


def cmd_report(store: ProjectStore, args) -> None:
    """Show detailed spending report for a project."""
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
        for name, total in sorted(result["personnel_totals"].items(), key=lambda x: -x[1]):
            print(f"  {Anonymizer.anonymize(name):<30} ${total:>12,.2f}")


def cmd_personnel(store: ProjectStore, args) -> None:
    """Show personnel effort across projects."""
    tracker = store.get_personnel_tracker()

    # Load personnel config for annual salaries
    config_path = Path(args.data_dir) / "projects" / "personnel_config.yaml"
    salary_lookup = {}
    if config_path.exists():
        from ..projections import load_personnel_config

        _, config_personnel = load_personnel_config(config_path)
        for p in config_personnel:
            salary_lookup[p.name] = p.annual_salary

    if args.name:
        # Resolve name - could be an index number, alias, or actual name
        all_personnel = tracker.get_all_personnel()
        aliases = load_aliases(args.data_dir)
        target_name, error = resolve_personnel_name(args.name, all_personnel, aliases=aliases)

        if error:
            print(f"Error: {error}")
            return

        if target_name != args.name:
            print(f"Resolved '{args.name}' to: {Anonymizer.anonymize(target_name)}\n")

        # Show specific person's effort
        allocations = tracker.get_person_effort(target_name)  # type: ignore[arg-type]
        if not allocations:
            print(f"No allocations found for: {Anonymizer.anonymize(target_name)}")
            return

        annual_salary = salary_lookup.get(target_name, Decimal("0"))  # type: ignore[arg-type]
        print(f"\n=== Effort: {Anonymizer.anonymize(target_name)} ===")
        if annual_salary:
            print(f"Annual Salary: ${annual_salary:,.2f}\n")

        # Load config for effort assignments
        config_effort = {}  # project -> effort
        if config_path.exists():
            from ..projections import load_personnel_config

            _, config_personnel = load_personnel_config(config_path)
            for p in config_personnel:
                if p.name == target_name:
                    for a in p.assignments:
                        config_effort[a.project] = a.effort
                    break

        # Group by project and year
        by_project = tracker.get_person_by_project(target_name)  # type: ignore[arg-type]
        by_year: dict[str, Decimal] = {}
        for alloc in allocations:
            # Period is "Month YYYY" format, extract year from end
            year = "Unknown"
            if alloc.period and len(alloc.period) >= 4:
                year_part = alloc.period[-4:]
                if year_part.isdigit():
                    year = year_part
            by_year.setdefault(year, Decimal("0"))
            by_year[year] += alloc.salary_amount

        # Merge all projects (from config and spending)
        all_projects = set(by_project.keys()) | set(config_effort.keys())

        print(f"{'Project':<12} {'Effort':>7} {'Spent':>14}")
        print("-" * 35)
        grand_total = Decimal("0")
        for project_id in sorted(all_projects):
            effort = config_effort.get(project_id, 0)
            spent = by_project.get(project_id, Decimal("0"))
            effort_str = f"{effort * 100:.0f}%" if effort else "-"
            print(f"{project_id:<12} {effort_str:>7} ${spent:>12,.2f}")
            grand_total += spent

        print(f"\n{'Year':<12} {'Amount':>14}")
        print("-" * 28)
        for year, total in sorted(by_year.items()):
            print(f"{year:<12} ${total:>12,.2f}")

        print("-" * 28)
        print(f"{'ALL-TIME':<12} ${grand_total:>12,.2f}")

    else:
        # Show all personnel summary
        personnel = tracker.get_all_personnel()
        if not personnel:
            print("No personnel data found.")
            return

        # Calculate yearly and all-time totals
        yearly_totals: dict[str, Decimal] = {}
        all_time_total = Decimal("0")

        # Current date for calculating months since last invoice
        from datetime import datetime

        # Build config lookup for official dates and effort totals
        config_dates = {}  # name -> (start, end) from assignments
        effort_lookup = {}  # name -> total effort
        config_projects = {}  # name -> list of project names
        if config_path.exists():
            from ..projections import load_personnel_config

            _, config_personnel = load_personnel_config(config_path)
            for p in config_personnel:
                # Get earliest start and latest end across all assignments
                starts = [a.start for a in p.assignments if a.start]
                ends = [a.end for a in p.assignments if a.end]
                # Use departure date if no assignment ends, or earlier of the two
                if p.departure:
                    effective_end: date | None = (
                        min(max(ends), p.departure) if ends else p.departure
                    )
                else:
                    effective_end = max(ends) if ends else None
                config_dates[p.name] = (min(starts) if starts else None, effective_end)
                # Sum effort across all assignments
                effort_lookup[p.name] = sum(a.effort for a in p.assignments)
                # Collect project names
                config_projects[p.name] = sorted(set(a.project for a in p.assignments))

        # Apply project filter if specified
        project_filter = getattr(args, "project", None)
        if project_filter:
            # Filter personnel to only those assigned to this project OR who have spent on it
            filtered_personnel = []
            for name in personnel:
                # Check config assignments
                has_assignment = project_filter in config_projects.get(name, [])

                # Check actual spending
                by_project = tracker.get_person_by_project(name)
                has_spending = by_project.get(project_filter, Decimal("0")) > 0

                if has_assignment or has_spending:
                    filtered_personnel.append(name)

            personnel = filtered_personnel

            if not personnel:
                print(f"No personnel found for project: {project_filter}")
                return
            header_suffix = f" (Project: {project_filter})"
        else:
            header_suffix = ""

        print(f"\n=== All Personnel{header_suffix} ===\n")
        print(
            f"{'#':>3} {'Name':<22} {'Salary':>8} {'Current Effort':>14} {'Spent':>10} {'Ends':>10} {'(Invoices)':<18} {'Projects':<20}"
        )
        print("-" * 115)

        for idx, name in enumerate(personnel, 1):
            by_project = tracker.get_person_by_project(name)
            spent = sum(by_project.values(), Decimal("0"))
            annual = salary_lookup.get(name, Decimal("0"))
            effort = effort_lookup.get(name, 0)
            projects_str = ",".join(config_projects.get(name, [])) or "-"

            # If project filter is on, adjust values to show ONLY that project's data
            if project_filter:
                spent = by_project.get(project_filter, Decimal("0"))
                # Get effort specifically for this project
                effort = 0
                if config_path.exists():
                    from ..projections import load_personnel_config

                    _, config_personnel = load_personnel_config(config_path)
                    for p in config_personnel:
                        if p.name == name:
                            for a in p.assignments:
                                if a.project == project_filter:
                                    effort = a.effort
                                    break
                            break

                # Filter out 0% effort if project filter is on, UNLESS they have spending
                if effort == 0 and spent == 0:
                    continue

            all_time_total += spent

            # Find earliest and latest invoice periods
            earliest_date = None
            latest_date = None
            for alloc in tracker.get_person_effort(name):
                # Filter allocations if project filter is on
                if project_filter and alloc.project_id != project_filter:
                    continue

                year = "Unknown"
                if alloc.period and len(alloc.period) >= 4:
                    year_part = alloc.period[-4:]
                    if year_part.isdigit():
                        year = year_part
                        try:
                            period_date = datetime.strptime(alloc.period, "%B %Y")
                            if earliest_date is None or period_date < earliest_date:
                                earliest_date = period_date
                            if latest_date is None or period_date > latest_date:
                                latest_date = period_date
                        except ValueError:
                            pass
                yearly_totals.setdefault(year, Decimal("0"))
                yearly_totals[year] += alloc.salary_amount

            # Official end date from config (this is what projections use)
            if project_filter:
                # Get end date specific to this project assignment
                cfg_end = None
                if config_path.exists():
                    from ..projections import load_personnel_config

                    _, config_personnel = load_personnel_config(config_path)
                    for p in config_personnel:
                        if p.name == name:
                            for a in p.assignments:
                                if a.project == project_filter:
                                    cfg_end = a.end
                                    break
                            break
            else:
                _cfg_start, cfg_end = config_dates.get(name, (None, None))

            end_str = cfg_end.strftime("%b %y") if cfg_end else "ongoing"

            # Invoice range for verification
            if earliest_date and latest_date:
                inv_str = f"{earliest_date.strftime('%b')}-{latest_date.strftime('%b %y')}"
            else:
                inv_str = "-"

            salary_str = f"${annual / 1000:.0f}k" if annual else "-"
            effort_str = f"{effort * 100:.0f}%" if effort else "-"
            print(
                f"{idx:>3} {Anonymizer.anonymize(name):<22} {salary_str:>8} {effort_str:>14} ${spent:>8,.0f} {end_str:>10} {inv_str:<18} {projects_str:<20}"
            )

        # Yearly totals
        print("\n--- Yearly Totals ---")
        for year, total in sorted(yearly_totals.items()):
            print(f"  {year}: ${total:>12,.2f}")
        print(f"  {'ALL-TIME'}: ${all_time_total:>12,.2f}")

    # Show validation warnings
    warnings = tracker.validate_effort()
    if warnings:
        print("\n--- Warnings ---")
        for w in warnings:
            msg = w.message
            if Anonymizer.enabled:
                for real_name, anon_name in Anonymizer._real_to_anon.items():
                    msg = msg.replace(real_name, anon_name)
            print(f"  [{w.warning_type}] {Anonymizer.anonymize(w.person_name)}: {msg}")


def cmd_project(store: ProjectStore, args) -> None:
    """Show spending projections for a project."""
    from ..api import SmaugAPI

    api = SmaugAPI(args.data_dir)
    result = api.spending_projection(
        args.project,
        months=args.months,
        end_date=args.to,
    )

    if not result["projections"]:
        print(f"No projections generated for {args.project}")
        return

    # Format using the existing text formatter — requires re-calling
    # project_spending() since format_projection_report needs MonthlyProjection objects.
    # This is temporary until format_projection_report is refactored to accept dicts.
    config_path = Path(args.data_dir) / "projects" / "personnel_config.yaml"
    if not config_path.exists():
        print(f"Error: Personnel config not found: {config_path}")
        return

    store.load_travel_config()
    store.load_purchases_config()

    end_date = None
    if args.to:
        parts = args.to.split("-")
        end_date = date(int(parts[0]), int(parts[1]), 1)

    projections = project_spending(
        project_id=args.project,
        config_path=config_path,
        end_date=end_date,
        months=args.months,
        travel_items=store.get_project_travel(args.project),
        expense_items=store.get_project_expenses(args.project),
    )
    print(format_projection_report(projections, args.project))


def cmd_gaps(store: ProjectStore, args) -> None:
    """Check for missing spending reports."""
    from datetime import datetime

    now = datetime.now()
    projects = store.list_projects()
    any_gaps = False

    print("\n=== Missing Spending Reports ===\n")

    for project_id in projects:
        data = store.get_project(project_id)
        if not data or not data.spending:
            print(f"{project_id}: No reports found")
            any_gaps = True
            continue

        # Get all report periods as (year, month) tuples
        periods = set()
        for report in data.spending:
            periods.add((report.year, report.month))

        # Find min/max
        min_period = min(periods)
        max_period = max(periods)

        # Generate expected months from min to now (or max if in future)
        end_year, end_month = now.year, now.month
        if max_period > (end_year, end_month):
            end_year, end_month = max_period

        # Build expected set
        expected = set()
        year, month = min_period
        while (year, month) <= (end_year, end_month):
            expected.add((year, month))
            month += 1
            if month > 12:
                month = 1
                year += 1

        # Find missing
        missing = sorted(expected - periods)

        if missing:
            any_gaps = True
            print(f"{project_id}:")
            for year, month in missing:
                month_name = datetime(year, month, 1).strftime("%B %Y")
                print(f"  - {month_name}")

    if not any_gaps:
        print("All projects have complete report coverage.")


def cmd_dump(store: ProjectStore, args) -> None:
    """Dump project data as JSON for manual verification."""
    import json

    from ..api import SmaugAPI

    api = SmaugAPI(args.data_dir)
    result = api.dump_project(args.project)
    print(json.dumps(result, indent=2))


def cmd_audit(store: ProjectStore, args) -> None:
    """Audit spending reports against expected effort allocations."""
    from decimal import Decimal

    from ..audit import audit_project, format_audit_report

    config_path = Path(args.data_dir) / "projects" / "personnel_config.yaml"

    if not config_path.exists():
        print(f"Error: Personnel config not found: {config_path}")
        return

    # Get all personnel allocations from reports
    tracker = store.get_personnel_tracker()
    all_allocations = []
    for name in tracker.get_all_personnel():
        all_allocations.extend(tracker.get_person_effort(name))

    # Determine which projects to audit
    if args.project:
        # Resolve project - could be index or name
        projects = store.list_projects()
        if args.project.isdigit():
            idx = int(args.project)
            if 1 <= idx <= len(projects):
                project_ids = [projects[idx - 1]]
            else:
                print(f"Error: Index {idx} out of range (1-{len(projects)})")
                return
        else:
            if args.project not in projects:
                print(f"Project not found: {args.project}")
                return
            project_ids = [args.project]
    else:
        project_ids = store.list_projects()

    # Run audit for each project — use audit_project directly for now
    # since format_audit_report needs the AuditReport dataclass.
    # The API's audit() method is used by MCP; CLI uses the richer formatter.
    threshold = Decimal(str(args.threshold))
    use_color = Colors.enabled()
    aliases = load_aliases(args.data_dir)

    for project_id in project_ids:
        report = audit_project(
            project_id=project_id,
            config_path=config_path,
            actual_allocations=all_allocations,
            months_back=args.months,
            threshold_pct=threshold,
            aliases=aliases,
        )

        # Skip projects with no findings unless verbose
        if not report.findings and not args.verbose:
            if len(project_ids) > 1:
                print(
                    f"{color(project_id, Colors.GREEN)}: ✓ No issues ({len(report.periods)} periods)"
                )
            continue

        # Format and print report
        output = format_audit_report(report, use_color=use_color)
        print(output)
