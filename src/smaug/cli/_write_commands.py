"""CLI commands that modify YAML configuration files."""

from pathlib import Path

from ..config import get_rates_path
from ..store import ProjectStore
from ..yaml_utils import git_commit_change, yaml_transaction
from ._util import load_aliases, parse_date_input, resolve_personnel_name, save_aliases


def cmd_set_end(store: ProjectStore, args) -> None:
    """Set or clear end date for a person's project assignment."""
    # Check if clearing the end date
    clear_end = args.date.lower() in ("none", "clear", "-")
    if not clear_end:
        # Parse the date input
        args.date = parse_date_input(args.date)

    config_path = Path(args.data_dir) / "projects" / "personnel_config.yaml"

    if not config_path.exists():
        print(f"Error: Personnel config not found: {config_path}")
        return

    # Resolve name - could be an index number or actual name
    tracker = store.get_personnel_tracker()
    personnel = tracker.get_all_personnel()
    aliases = load_aliases(args.data_dir)
    target_name, error = resolve_personnel_name(args.name, personnel, aliases=aliases)

    if error:
        print(f"Error: {error}")
        return

    if target_name != args.name:
        print(f"Resolved '{args.name}' to: {target_name}")

    # Write back via transaction
    try:
        with yaml_transaction(config_path) as config:
            # Find the person and project
            found = False
            for person in config.get("personnel", []):
                if person["name"] == target_name:
                    for assignment in person.get("assignments", []):
                        if assignment["project"] == args.project:
                            if clear_end:
                                if "end" in assignment:
                                    del assignment["end"]
                                    print(f"Cleared end date: {target_name} on {args.project}")
                                else:
                                    print(
                                        f"{target_name} on {args.project} already has no end date"
                                    )
                            else:
                                assignment["end"] = args.date
                                print(f"Updated: {target_name} on {args.project} ends {args.date}")
                            found = True
                            break
                    if not found:
                        # Add new assignment
                        person.setdefault("assignments", []).append(
                            {"project": args.project, "effort": 1.0, "end": args.date}
                        )
                        found = True
                        print(f"Added: {target_name} on {args.project} ends {args.date}")
                    break

            if not found:
                raise ValueError(f"Person '{target_name}' not found in config")
    except ValueError as e:
        print(f"Error: {e}")
        return

    print(f"Config saved to {config_path}")
    git_commit_change(args.data_dir, f"set-end: {target_name} on {args.project} -> {args.date}")


def cmd_set_departure(store: ProjectStore, args) -> None:
    """Set overall departure date for a person (leaves university/graduates)."""
    # Parse the date input
    args.date = parse_date_input(args.date)

    config_path = Path(args.data_dir) / "projects" / "personnel_config.yaml"

    if not config_path.exists():
        print(f"Error: Personnel config not found: {config_path}")
        return

    # Resolve name - could be an index number or actual name
    tracker = store.get_personnel_tracker()
    personnel = tracker.get_all_personnel()
    aliases = load_aliases(args.data_dir)
    target_name, error = resolve_personnel_name(args.name, personnel, aliases=aliases)

    if error:
        print(f"Error: {error}")
        return

    if target_name != args.name:
        print(f"Resolved '{args.name}' to: {target_name}")

    try:
        with yaml_transaction(config_path) as config:
            # Find the person and set departure
            found = False
            for person in config.get("personnel", []):
                if person["name"] == target_name:
                    person["departure"] = args.date
                    found = True
                    print(f"Set departure: {target_name} leaves {args.date}")
                    break

            if not found:
                raise ValueError(f"Person '{target_name}' not found in config")
    except ValueError as e:
        print(f"Error: {e}")
        return

    print(f"Config saved to {config_path}")
    git_commit_change(args.data_dir, f"set-departure: {target_name} -> {args.date}")


def cmd_set_salary(store: ProjectStore, args) -> None:
    """Set annual salary for a person."""
    config_path = Path(args.data_dir) / "projects" / "personnel_config.yaml"

    if not config_path.exists():
        print(f"Error: Personnel config not found: {config_path}")
        return

    if getattr(args, "start", None):
        args.start = parse_date_input(args.start)
    if getattr(args, "end", None):
        args.end = parse_date_input(args.end)

    # Parse salary
    try:
        salary = int(args.salary)
    except ValueError:
        print(f"Error: Invalid salary amount: {args.salary}")
        return

    try:
        with yaml_transaction(config_path) as config:
            # Resolve name - could be an index number or actual name
            tracker = store.get_personnel_tracker()
            personnel = tracker.get_all_personnel()
            aliases = load_aliases(args.data_dir)
            target_name, error = resolve_personnel_name(args.name, personnel, aliases=aliases)

            if error:
                # Fallback: search YAML config directly (for newly added people not in reports)
                config_names = [p["name"] for p in config.get("personnel", [])]
                matches = [n for n in config_names if args.name.lower() in n.lower()]
                if len(matches) == 1:
                    target_name = matches[0]
                    error = None
                    if target_name != args.name:
                        print(f"Resolved '{args.name}' to: {target_name}")
                elif len(matches) > 1:
                    match_list = "\n".join(f"  - {m}" for m in matches)
                    raise ValueError(f"Multiple personnel matching '{args.name}':\n{match_list}")
                else:
                    raise ValueError(error)

            if target_name != args.name:
                print(f"Resolved '{args.name}' to: {target_name}")

            # Find the person and set salary
            found = False
            for person in config.get("personnel", []):
                if person["name"] == target_name:
                    found = True
                    target_start = getattr(args, "start", None)
                    target_end = getattr(args, "end", None)

                    if target_start or target_end:
                        is_list = isinstance(person.get("annual_salary"), list)
                        if is_list:
                            found_exact = False
                            for record in person["annual_salary"]:
                                if (
                                    record.get("start") == target_start
                                    and record.get("end") == target_end
                                ):
                                    old_val = record.get("amount", 0)
                                    record["amount"] = salary
                                    found_exact = True
                                    print(
                                        f"Updated salary: {target_name} ({target_start or ''} to {target_end or ''})"
                                    )
                                    print(f"  ${old_val:,} -> ${salary:,}")
                                    break
                            if not found_exact:
                                new_record = {"amount": salary}
                                if target_start:
                                    new_record["start"] = target_start
                                if target_end:
                                    new_record["end"] = target_end
                                person["annual_salary"].append(new_record)
                                print(
                                    f"Added scheduled salary: {target_name} (${salary:,}) from {target_start or ''} to {target_end or ''}"
                                )
                        else:
                            old_salary = person.get("annual_salary", 0)
                            schedule = []
                            if target_start:
                                schedule.append({"amount": old_salary, "end": target_start})

                            new_record = {"amount": salary}
                            if target_start:
                                new_record["start"] = target_start
                            if target_end:
                                new_record["end"] = target_end
                            schedule.append(new_record)
                            person["annual_salary"] = schedule
                            print(
                                f"Converted salary for {target_name} to schedule: new rate ${salary:,} starting {target_start or ''}"
                            )
                    else:
                        old_salary = person.get("annual_salary", 0)
                        person["annual_salary"] = salary
                        print(f"Updated salary: {target_name}")
                        if isinstance(old_salary, int | float):
                            print(f"  ${old_salary:,} -> ${salary:,}")
                        else:
                            print(f"  [Scheduled] -> ${salary:,}")
                    break

            if not found:
                raise ValueError(f"Person '{target_name}' not found in config")
    except ValueError as e:
        print(f"Error: {e}")
        return

    print(f"Config saved to {config_path}")
    git_commit_change(args.data_dir, f"set-salary: {target_name} -> ${salary:,}")


def cmd_set_effort(store: ProjectStore, args) -> None:
    """Set effort allocation for a person on a project."""
    config_path = Path(args.data_dir) / "projects" / "personnel_config.yaml"

    if not config_path.exists():
        print(f"Error: Personnel config not found: {config_path}")
        return

    if getattr(args, "start", None):
        args.start = parse_date_input(args.start)
    if getattr(args, "end", None):
        args.end = parse_date_input(args.end)

    # Resolve name - could be an index number or actual name
    tracker = store.get_personnel_tracker()
    personnel = tracker.get_all_personnel()
    aliases = load_aliases(args.data_dir)
    target_name, error = resolve_personnel_name(args.name, personnel, aliases=aliases)

    if error:
        print(f"Error: {error}")
        return

    if target_name != args.name:
        print(f"Resolved '{args.name}' to: {target_name}")

    # Parse effort
    try:
        effort = float(args.effort)
        if effort > 1:
            effort = effort / 100  # Convert percentage to decimal
    except ValueError:
        print(f"Error: Invalid effort value: {args.effort}")
        return

    try:
        with yaml_transaction(config_path) as config:
            # Find the person and update/add effort
            found_person = False
            for person in config.get("personnel", []):
                if person["name"] == target_name:
                    found_person = True
                    assignments = person.setdefault("assignments", [])

                    # If start/end provided, look for an assignment with the same project and exact same start/end dates
                    if args.start or args.end:
                        found_exact = False
                        for assignment in assignments:
                            if (
                                assignment.get("project") == args.project
                                and assignment.get("start") == args.start
                                and assignment.get("end") == args.end
                            ):
                                old_effort = assignment.get("effort", 0)
                                assignment["effort"] = effort
                                found_exact = True
                                print(
                                    f"Updated effort: {target_name} on {args.project} ({args.start or ''} to {args.end or ''})"
                                )
                                print(f"  {old_effort * 100:.0f}% -> {effort * 100:.0f}%")
                                break
                        if not found_exact:
                            new_assignment = {"project": args.project, "effort": effort}
                            if args.start:
                                new_assignment["start"] = args.start
                            if args.end:
                                new_assignment["end"] = args.end
                            assignments.append(new_assignment)
                            date_range = ""
                            if args.start and args.end:
                                date_range = f" ({args.start} to {args.end})"
                            elif args.start:
                                date_range = f" (from {args.start})"
                            elif args.end:
                                date_range = f" (until {args.end})"
                            print(
                                f"Added: {target_name} to {args.project} at {effort * 100:.0f}%{date_range}"
                            )
                    else:
                        # No dates - look for existing assignment to update
                        found_assignment = False
                        for assignment in assignments:
                            if assignment.get("project") == args.project:
                                old_effort = assignment.get("effort", 0)
                                assignment["effort"] = effort
                                found_assignment = True
                                print(f"Updated effort: {target_name} on {args.project}")
                                print(f"  {old_effort * 100:.0f}% -> {effort * 100:.0f}%")
                                break

                        if not found_assignment:
                            # Add new assignment
                            assignments.append({"project": args.project, "effort": effort})
                            print(f"Added: {target_name} to {args.project} at {effort * 100:.0f}%")
                    break

            if not found_person:
                raise ValueError(f"Person '{target_name}' not found in config")
    except ValueError as e:
        print(f"Error: {e}")
        return

    print(f"Config saved to {config_path}")
    git_commit_change(
        args.data_dir, f"set-effort: {target_name} on {args.project} -> {effort * 100:.0f}%"
    )


def cmd_remove_effort(store: ProjectStore, args) -> None:
    """Remove a person's assignment to a project."""
    config_path = Path(args.data_dir) / "projects" / "personnel_config.yaml"

    if not config_path.exists():
        print(f"Error: Personnel config not found: {config_path}")
        return

    if getattr(args, "start", None):
        args.start = parse_date_input(args.start)
    if getattr(args, "end", None):
        args.end = parse_date_input(args.end)

    # Resolve name - could be an index number or actual name
    tracker = store.get_personnel_tracker()
    personnel = tracker.get_all_personnel()
    aliases = load_aliases(args.data_dir)
    target_name, error = resolve_personnel_name(args.name, personnel, aliases=aliases)

    if error:
        print(f"Error: {error}")
        return

    if target_name != args.name:
        print(f"Resolved '{args.name}' to: {target_name}")

    try:
        with yaml_transaction(config_path) as config:
            # Find the person and remove assignment
            found_person = False
            removed = False
            for person in config.get("personnel", []):
                if person["name"] == target_name:
                    found_person = True
                    assignments = person.get("assignments", [])

                    # Find and remove the assignment
                    for i, assignment in enumerate(assignments):
                        if assignment.get("project") == args.project:
                            # Match start and end dates if provided
                            match_dates = True
                            target_start = getattr(args, "start", None)
                            target_end = getattr(args, "end", None)

                            if target_start and assignment.get("start") != target_start:
                                match_dates = False
                            if target_end and assignment.get("end") != target_end:
                                match_dates = False

                            if match_dates:
                                old_effort = assignment.get("effort", 0)
                                assignments.pop(i)
                                removed = True
                                date_info = ""
                                if assignment.get("start") or assignment.get("end"):
                                    date_info = f" ({assignment.get('start') or ''} to {assignment.get('end') or ''})"
                                print(
                                    f"Removed: {target_name} from {args.project}{date_info} (was {old_effort * 100:.0f}%)"
                                )
                                break
                    break

            if not found_person:
                raise ValueError(f"Person '{target_name}' not found in config")

            if not removed:
                raise ValueError(f"{target_name} has no assignment to {args.project}")
    except ValueError as e:
        print(f"Error: {e}")
        return

    print(f"Config saved to {config_path}")
    git_commit_change(args.data_dir, f"remove-effort: {target_name} from {args.project}")


def cmd_add_person(store: ProjectStore, args) -> None:
    """Add a new person to personnel_config.yaml."""
    config_path = Path(args.data_dir) / "projects" / "personnel_config.yaml"

    if not config_path.exists():
        print(f"Error: Personnel config not found: {config_path}")
        return

    # Validate type
    valid_types = ["faculty", "postdoc", "grad_student", "staff"]
    person_type = args.type.lower()
    type_map = {"phd": "grad_student", "grad": "grad_student"}
    person_type = type_map.get(person_type, person_type)

    if person_type not in valid_types:
        print(
            f"Error: Invalid type '{args.type}'. Must be one of: {', '.join(valid_types)} (or phd/grad)"
        )
        return

    import yaml

    # Determine salary
    if args.salary:
        try:
            salary = int(args.salary)
        except ValueError:
            try:
                salary = float(args.salary)  # type: ignore[assignment]
            except ValueError:
                print(f"Error: Invalid salary: {args.salary}")
                return
    elif person_type == "grad_student":
        # Default to configured stipend
        rates_path = get_rates_path(Path(args.data_dir))
        if rates_path.exists():
            with open(rates_path) as f:
                rates_config = yaml.safe_load(f)
            salary = rates_config.get("grad_student_costs", {}).get("stipend", 47000)
        else:
            salary = 47000
        print(f"Using default grad student stipend: ${salary:,.0f}")
    else:
        print(f"Error: --salary is required for {person_type} personnel.")
        return

    # Parse effort
    try:
        effort = float(args.effort)
        if effort > 1:
            effort = effort / 100
    except ValueError:
        print(f"Error: Invalid effort: {args.effort}")
        return

    try:
        with yaml_transaction(config_path) as config:
            # Check for duplicate names
            for p in config.get("personnel", []):
                if p["name"].lower() == args.name.lower():
                    raise ValueError(
                        f"Person '{args.name}' already exists. Use set-effort to add assignments."
                    )

            # Build entry
            assignment = {
                "project": args.project,
                "effort": effort,
            }
            if args.start:
                assignment["start"] = args.start
            if args.end:
                assignment["end"] = args.end

            new_person = {
                "name": args.name,
                "type": person_type,
                "annual_salary": salary,
                "assignments": [assignment],
            }

            config.setdefault("personnel", []).append(new_person)
    except ValueError as e:
        print(f"Error: {e}")
        return

    date_info = ""
    if args.start:
        date_info = f" (from {args.start})"
    if args.end:
        date_info += f" (until {args.end})"

    print(f"Added: {args.name} ({person_type})")
    print(f"  Salary: ${salary:,}")
    print(f"  Assignment: {args.project} at {effort * 100:.0f}%{date_info}")
    print(f"Config saved to {config_path}")
    git_commit_change(args.data_dir, f"add-person: {args.name} ({person_type})")


def cmd_alias(store: ProjectStore, args) -> None:
    """Manage personnel aliases/nicknames."""
    aliases = load_aliases(args.data_dir)

    if args.action == "list":
        if not aliases:
            print("No aliases defined.")
            print("\nTo add an alias: ./smaug alias add <nickname> <person>")
            return

        print("\n=== Personnel Aliases ===\n")
        print(f"{'Alias':<20} {'Resolves To':<40}")
        print("-" * 60)
        for alias, real_name in sorted(aliases.items()):
            print(f"{alias:<20} {real_name:<40}")

    elif args.action == "add":
        # Resolve the target person using fuzzy matching
        tracker = store.get_personnel_tracker()
        personnel = tracker.get_all_personnel()
        target_name, error = resolve_personnel_name(args.person, personnel, aliases=aliases)

        if error:
            print(f"Error: {error}")
            return

        if target_name != args.person:
            print(f"Resolved '{args.person}' to: {target_name}")

        # Check if alias already exists
        alias_lower = args.alias.lower()
        for existing_alias in aliases:
            if existing_alias.lower() == alias_lower:
                old_target = aliases[existing_alias]
                print(f"Updating alias '{existing_alias}': {old_target} -> {target_name}")
                del aliases[existing_alias]
                break

        aliases[args.alias] = target_name  # type: ignore[assignment]
        save_aliases(args.data_dir, aliases)
        print(f"Added alias: '{args.alias}' -> '{target_name}'")
        git_commit_change(args.data_dir, f"add-alias: {args.alias} -> {target_name}")

    elif args.action == "remove":
        # Find the alias (case-insensitive)
        alias_lower = args.alias.lower()
        found_alias = None
        for existing_alias in aliases:
            if existing_alias.lower() == alias_lower:
                found_alias = existing_alias
                break

        if not found_alias:
            print(f"Error: Alias '{args.alias}' not found")
            return

        old_target = aliases.pop(found_alias)
        save_aliases(args.data_dir, aliases)
        print(f"Removed alias: '{found_alias}' (was -> '{old_target}')")
        git_commit_change(args.data_dir, f"remove-alias: {found_alias}")


def cmd_add_project(store: ProjectStore, args) -> None:
    """Add a new project to the manifest."""
    manifest_path = Path(args.data_dir) / "projects" / "manifest.yaml"

    if not manifest_path.exists():
        print(f"Error: Manifest not found: {manifest_path}")
        return

    # Determine which section to add to
    section_key = "discretionary" if args.type == "discretionary" else "projects"

    if args.budget:
        try:
            budget_val = int(args.budget)
        except ValueError:
            print(f"Error: Invalid budget amount: {args.budget}")
            return
    else:
        budget_val = None

    try:
        with yaml_transaction(manifest_path) as manifest:
            # Ensure section exists
            if section_key not in manifest:
                manifest[section_key] = {}

            # Check if project already exists in either section
            all_projects = list(manifest.get("projects", {}).keys()) + list(
                manifest.get("discretionary", {}).keys()
            )
            if args.name in all_projects:
                raise ValueError(f"Project '{args.name}' already exists")

            # Create project entry
            project = {"name": args.description or args.name}

            if budget_val is not None:
                project["total_budget"] = budget_val

            if args.grant:
                project["grant_number"] = args.grant

            manifest[section_key][args.name] = project

            # Set status (only for sponsored projects)
            project_status = getattr(args, "status", None)
            if project_status and section_key == "projects":
                project["status"] = project_status
    except ValueError as e:
        print(f"Error: {e}")
        return

    print(f"Added project: {args.name}")
    print(f"  Type: {args.type}")
    if project_status:
        print(f"  Status: {project_status}")
    if args.budget:
        print(f"  Budget: ${int(args.budget):,}")
    print(f"Manifest saved to {manifest_path}")
    git_commit_change(args.data_dir, f"add-project: {args.name} ({args.type})")


def cmd_set_status(store: ProjectStore, args) -> None:
    """Set the lifecycle status of a project."""
    from ..models import ProjectStatus

    # Validate the target status
    valid = [s.value for s in ProjectStatus]
    if args.status not in valid:
        print(f"Error: Invalid status '{args.status}'. Options: {', '.join(valid)}")
        return

    manifest_path = Path(args.data_dir) / "projects" / "manifest.yaml"
    if not manifest_path.exists():
        print(f"Error: Manifest not found: {manifest_path}")
        return

    try:
        with yaml_transaction(manifest_path) as manifest:
            # Find project in either section
            found = False
            for section in ["projects", "discretionary"]:
                if section in manifest and args.project in manifest[section]:
                    # Discretionary accounts can only be active or completed
                    if section == "discretionary" and args.status not in ("active", "completed"):
                        raise ValueError(
                            "Discretionary accounts can only be 'active' or 'completed'"
                        )

                    old_status = manifest[section][args.project].get("status", "active")
                    manifest[section][args.project]["status"] = args.status
                    found = True
                    print(f"Status updated: {args.project}")
                    print(f"  {old_status} → {args.status}")
                    break

            if not found:
                raise ValueError(f"Project '{args.project}' not found")
    except ValueError as e:
        print(f"Error: {e}")
        return

    print(f"Manifest saved to {manifest_path}")
    git_commit_change(args.data_dir, f"set-status: {args.project} -> {args.status}")


def cmd_set_project_end(store: ProjectStore, args) -> None:
    """Set end date for a project."""
    # Parse the date input
    args.date = parse_date_input(args.date)

    manifest_path = Path(args.data_dir) / "projects" / "manifest.yaml"

    if not manifest_path.exists():
        print(f"Error: Manifest not found: {manifest_path}")
        return

    try:
        with yaml_transaction(manifest_path) as manifest:
            # Find project in either section
            found = False
            for section in ["projects", "discretionary"]:
                if section in manifest and args.project in manifest[section]:
                    manifest[section][args.project]["end_date"] = args.date
                    found = True
                    print(f"Set end date: {args.project} ends {args.date}")
                    break

            if not found:
                raise ValueError(f"Project '{args.project}' not found")
    except ValueError as e:
        print(f"Error: {e}")
        return

    print(f"Manifest saved to {manifest_path}")
    git_commit_change(args.data_dir, f"set-project-end: {args.project} -> {args.date}")


def cmd_set_budget(store: ProjectStore, args) -> None:
    """Set budget for a project."""
    manifest_path = Path(args.data_dir) / "projects" / "manifest.yaml"

    if not manifest_path.exists():
        print(f"Error: Manifest not found: {manifest_path}")
        return

    # Parse budget
    try:
        budget = int(args.budget)
    except ValueError:
        print(f"Error: Invalid budget amount: {args.budget}")
        return

    try:
        with yaml_transaction(manifest_path) as manifest:
            # Find project in either section
            found = False
            for section in ["projects", "discretionary"]:
                if section in manifest and args.project in manifest[section]:
                    old_budget = manifest[section][args.project].get("total_budget", 0)
                    manifest[section][args.project]["total_budget"] = budget
                    found = True
                    print(f"Updated budget: {args.project}")
                    print(f"  ${old_budget:,} -> ${budget:,}")
                    break

            if not found:
                raise ValueError(f"Project '{args.project}' not found")
    except ValueError as e:
        print(f"Error: {e}")
        return

    print(f"Manifest saved to {manifest_path}")
    git_commit_change(args.data_dir, f"set-budget: {args.project} -> ${budget:,}")


def cmd_set_idc(store: ProjectStore, args) -> None:
    """Set the Indirect Cost (F&A) rate in rates.yaml."""
    rates_path = get_rates_path(Path(args.data_dir))

    if not rates_path.exists():
        print(f"Error: Rates file not found: {rates_path}")
        return

    # Parse rate - accept either decimal (0.55) or percentage (55)
    try:
        rate = float(args.rate)
        if rate > 1:
            rate = rate / 100  # Treat as percentage
    except ValueError:
        # Strip trailing % if present
        cleaned = args.rate.rstrip("%")
        try:
            rate = float(cleaned) / 100
        except ValueError:
            print(f"Error: Invalid IDC rate: {args.rate}")
            return

    try:
        with yaml_transaction(rates_path) as config:
            old_rate = config.get("idc_rate", 0)
            config["idc_rate"] = rate
    except Exception as e:
        print(f"Error: {e}")
        return

    print(f"Updated IDC rate: {old_rate * 100:.2f}% -> {rate * 100:.2f}%")
    print(f"Config saved to {rates_path}")
    git_commit_change(args.data_dir, f"set-idc: {rate * 100:.2f}%")


def cmd_set_healthcare(store: ProjectStore, args) -> None:
    """Set annual health & dental cost for grad students in rates.yaml."""
    rates_path = get_rates_path(Path(args.data_dir))

    if not rates_path.exists():
        print(f"Error: Rates file not found: {rates_path}")
        return

    try:
        amount = float(args.amount)
    except ValueError:
        print(f"Error: Invalid amount: {args.amount}")
        return

    try:
        with yaml_transaction(rates_path) as config:
            gs_costs = config.setdefault("grad_student_costs", {})
            old_amount = gs_costs.get("health_dental", 0)
            gs_costs["health_dental"] = amount
    except Exception as e:
        print(f"Error: {e}")
        return

    print(f"Updated health & dental: ${old_amount:,.2f} -> ${amount:,.2f} (annual)")
    print(f"  Monthly per student at 100%: ${amount / 12:,.2f}")
    print(f"Config saved to {rates_path}")
    git_commit_change(args.data_dir, f"set-healthcare: ${amount:,.2f}")


def cmd_set_tuition(store: ProjectStore, args) -> None:
    """Set per-semester tuition cost for grad students in rates.yaml."""
    rates_path = get_rates_path(Path(args.data_dir))

    if not rates_path.exists():
        print(f"Error: Rates file not found: {rates_path}")
        return

    try:
        amount = float(args.amount)
    except ValueError:
        print(f"Error: Invalid amount: {args.amount}")
        return

    try:
        with yaml_transaction(rates_path) as config:
            tb = config.setdefault("tuition_billing", {})
            old_amount = tb.get("per_semester", 0)
            tb["per_semester"] = amount
    except Exception as e:
        print(f"Error: {e}")
        return

    print(f"Updated tuition per semester: ${old_amount:,.2f} -> ${amount:,.2f}")
    print(f"  Annual (2 semesters): ${amount * 2:,.2f}")
    print(f"Config saved to {rates_path}")
    git_commit_change(args.data_dir, f"set-tuition: ${amount:,.2f}")


def cmd_set_fringe(store: ProjectStore, args) -> None:
    """Set fringe benefit rate for a personnel type in rates.yaml."""
    rates_path = get_rates_path(Path(args.data_dir))

    if not rates_path.exists():
        print(f"Error: Rates file not found: {rates_path}")
        return

    # Normalize type
    person_type = args.type.lower()
    type_map = {"phd": "grad_student", "grad": "grad_student"}
    person_type = type_map.get(person_type, person_type)

    valid_types = ["faculty", "postdoc", "grad_student", "staff", "part_time", "visiting"]
    if person_type not in valid_types:
        print(f"Error: Invalid type '{args.type}'. Must be one of: {', '.join(valid_types)}")
        return

    # Parse rate - accept decimal (0.315) or percentage (31.5)
    try:
        rate = float(args.rate)
        if rate > 1:
            rate = rate / 100
    except ValueError:
        cleaned = args.rate.rstrip("%")
        try:
            rate = float(cleaned) / 100
        except ValueError:
            print(f"Error: Invalid rate: {args.rate}")
            return

    try:
        with yaml_transaction(rates_path) as config:
            fringe_rates = config.setdefault("fringe_rates", {})
            old_rate = fringe_rates.get(person_type, 0)
            fringe_rates[person_type] = rate
    except Exception as e:
        print(f"Error: {e}")
        return

    print(f"Updated fringe rate for {person_type}: {old_rate * 100:.2f}% -> {rate * 100:.2f}%")
    print(f"Config saved to {rates_path}")
    git_commit_change(args.data_dir, f"set-fringe: {person_type} -> {rate * 100:.2f}%")
