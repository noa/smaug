"""Shared utilities for the CLI: colors, formatting, name resolution, aliases."""

import re
import sys
from pathlib import Path
from typing import ClassVar


# ANSI color codes for terminal output
class Colors:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"

    # Foreground colors
    RED = "\033[91m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    MAGENTA = "\033[95m"
    CYAN = "\033[96m"
    WHITE = "\033[97m"

    @staticmethod
    def enabled() -> bool:
        """Check if colors should be enabled (not piped/redirected)."""
        return sys.stdout.isatty()


def color(text: str, color_code: str) -> str:
    """Apply color to text if terminal supports it."""
    if Colors.enabled():
        return f"{color_code}{text}{Colors.RESET}"
    return text


def color_pct(pct: float) -> str:
    """Color a percentage based on budget health."""
    pct_str = f"{pct:.0f}%"
    if pct >= 90:
        return color(pct_str, Colors.RED)
    elif pct >= 70:
        return color(pct_str, Colors.YELLOW)
    else:
        return color(pct_str, Colors.GREEN)


def color_remaining(amount, budget) -> str:
    """Color remaining amount based on budget health."""

    amount_str = f"${amount:,.0f}"
    if budget <= 0:
        return amount_str
    pct_remaining = (amount / budget) * 100
    if pct_remaining <= 10:
        return color(amount_str, Colors.RED)
    elif pct_remaining <= 30:
        return color(amount_str, Colors.YELLOW)
    else:
        return color(amount_str, Colors.GREEN)


def parse_date_input(date_str: str) -> str:
    """
    Parse various date formats into YYYY-MM format.

    Accepts:
        - YYYY-MM (2026-06)
        - YYYY-M (2026-6)
        - Month Day, Year (June 30, 2026)
        - Month Year (June 2026)
        - M/D/YYYY (6/30/2026)
        - M/YYYY (6/2026)

    Returns:
        Date string in YYYY-MM format
    """
    date_str = date_str.strip()

    # Already in YYYY-MM or YYYY-M format
    if re.match(r"^\d{4}-\d{1,2}(-\d{1,2})?$", date_str):
        parts = date_str.split("-")
        return f"{parts[0]}-{int(parts[1]):02d}"

    # Month name mappings
    months = {
        "january": 1,
        "jan": 1,
        "february": 2,
        "feb": 2,
        "march": 3,
        "mar": 3,
        "april": 4,
        "apr": 4,
        "may": 5,
        "june": 6,
        "jun": 6,
        "july": 7,
        "jul": 7,
        "august": 8,
        "aug": 8,
        "september": 9,
        "sep": 9,
        "sept": 9,
        "october": 10,
        "oct": 10,
        "november": 11,
        "nov": 11,
        "december": 12,
        "dec": 12,
    }

    # "June 30, 2026" or "June 2026"
    match = re.match(r"^([a-zA-Z]+)\s+(\d{1,2},?\s+)?(\d{4})$", date_str)
    if match:
        month_name = match.group(1).lower()
        year = int(match.group(3))
        if month_name in months:
            return f"{year}-{months[month_name]:02d}"

    # "6/30/2026" or "6/2026"
    match = re.match(r"^(\d{1,2})/(\d{1,2}/)?(\d{4})$", date_str)
    if match:
        month = int(match.group(1))
        year = int(match.group(3))
        return f"{year}-{month:02d}"

    # Return as-is if we can't parse it
    return date_str


def get_role_display(person_type_or_enum) -> str:
    if not person_type_or_enum:
        return "Person"
    val = (
        person_type_or_enum.value
        if hasattr(person_type_or_enum, "value")
        else str(person_type_or_enum)
    )
    val = val.lower()
    if val in ("faculty",):
        return "Faculty"
    elif val in ("postdoc",):
        return "Postdoc"
    elif val in ("grad_student", "phd", "grad"):
        return "PhD"
    elif val in ("staff",):
        return "Staff"
    else:
        return "Person"


class Anonymizer:
    enabled = False
    data_dir = None
    _real_to_anon: ClassVar[dict[str, str]] = {}
    _anon_to_real: ClassVar[dict[str, str]] = {}

    @classmethod
    def save_mapping(cls):
        if cls.data_dir:
            mapping_path = Path(cls.data_dir) / ".anonymizer_mapping.yaml"
            try:
                from ..yaml_utils import yaml_transaction

                with yaml_transaction(mapping_path) as data:
                    data.clear()
                    data.update(cls._real_to_anon)
            except Exception:
                pass

    @classmethod
    def init(cls, store, args):
        import os

        anonymize_env = os.environ.get("SMAUG_ANONYMIZE", "").lower() in ("1", "true", "yes")
        anonymize_arg = getattr(args, "anonymize", False)

        # If SMAUG_ANONYMIZE is explicitly disabled (e.g. 0/false/no), disable even if flag/server asks
        if os.environ.get("SMAUG_ANONYMIZE", "").lower() in ("0", "false", "no"):
            cls.enabled = False
            return

        if not (anonymize_env or anonymize_arg):
            cls.enabled = False
            return

        cls.enabled = True
        cls.data_dir = store.data_dir
        cls._real_to_anon = {}
        cls._anon_to_real = {}

        # Load existing mapping file if it exists
        mapping_path = Path(cls.data_dir) / ".anonymizer_mapping.yaml"
        existing_mapping: dict[str, str] = {}
        if mapping_path.exists():
            try:
                with open(mapping_path, encoding="utf-8") as f:
                    import yaml

                    existing_mapping = yaml.safe_load(f) or {}
            except Exception:
                pass

        cls._real_to_anon = dict(existing_mapping)
        cls._anon_to_real = {v: k for k, v in existing_mapping.items()}

        # Collect all unique personnel names
        all_names = set()

        # Collect from tracker
        tracker = store.get_personnel_tracker()
        all_names.update(tracker.get_all_personnel())

        # Collect from personnel_config.yaml if it exists
        config_path = Path(store.data_dir) / "projects" / "personnel_config.yaml"
        personnel_types = {}

        if config_path.exists():
            from ..projections import load_personnel_config

            try:
                _, config_personnel = load_personnel_config(config_path)
                for p in config_personnel:
                    all_names.add(p.name)
                    personnel_types[p.name] = p.person_type
            except Exception:
                pass

        # Also check tracker allocations to see if we can get types from there
        for name in all_names:
            if name not in personnel_types:
                allocs = tracker.get_person_effort(name)
                if allocs:
                    for a in allocs:
                        if a.employee_type and a.employee_type.value != "unknown":
                            personnel_types[name] = a.employee_type.value
                            break

        # Keep track of counts per role
        role_counters = {"Faculty": 1, "Postdoc": 1, "PhD": 1, "Staff": 1, "Person": 1}

        # Initialize counters based on existing mappings to avoid duplicate numbers
        for anon_name in cls._anon_to_real:
            parts = anon_name.split(" ")
            if len(parts) == 2 and parts[1].isdigit():
                role, num = parts[0], int(parts[1])
                if role in role_counters:
                    role_counters[role] = max(role_counters[role], num + 1)

        # Filter new names that are not already mapped
        new_names = sorted([name for name in all_names if name not in cls._real_to_anon])

        for name in new_names:
            role = get_role_display(personnel_types.get(name))
            num = role_counters[role]
            anon_name = f"{role} {num}"
            role_counters[role] += 1

            cls._real_to_anon[name] = anon_name
            cls._anon_to_real[anon_name] = name

        if new_names:
            cls.save_mapping()

    @classmethod
    def anonymize(cls, name: str | None) -> str | None:
        if not cls.enabled or not name:
            return name
        if name.startswith("[") or "hypothetical" in name.lower():
            return name
        if name in cls._real_to_anon:
            return cls._real_to_anon[name]

        # Lazy/on-the-fly mapping for new/unseen names
        role = "Person"
        name_lower = name.lower()
        if "faculty" in name_lower:
            role = "Faculty"
        elif "postdoc" in name_lower:
            role = "Postdoc"
        elif "phd" in name_lower or "grad" in name_lower:
            role = "PhD"
        elif "staff" in name_lower:
            role = "Staff"

        count = 1
        while f"{role} {count}" in cls._anon_to_real:
            count += 1

        anon_name = f"{role} {count}"
        cls._real_to_anon[name] = anon_name
        cls._anon_to_real[anon_name] = name
        cls.save_mapping()
        return anon_name

    @classmethod
    def resolve(cls, name: str) -> str:
        if not cls.enabled or not name:
            return name
        return cls._anon_to_real.get(name, name)


def resolve_personnel_name(
    name_or_idx: str,
    personnel_list: list[str],
    allow_missing: bool = False,
    aliases: dict[str, str] | None = None,
) -> tuple[str | None, str | None]:
    """
    Resolve a personnel name from index, alias, or fuzzy match.

    Args:
        name_or_idx: Either a numeric index (1-based), alias, or a name/partial name
        personnel_list: List of all personnel names
        allow_missing: If True, return the original input when no match found
                      (useful for external travelers, etc.)
        aliases: Optional dict mapping aliases to real names

    Returns:
        Tuple of (resolved_name, error_message)
        - On success: (name, None)
        - On error: (None, error_message)
        - On allow_missing with no match: (original_input, None)
    """
    # If anonymization is active, perform bidirectional resolution
    if Anonymizer.enabled:
        cleaned_query = name_or_idx.lower().replace(" ", "")
        for anon_name, real_name in Anonymizer._anon_to_real.items():
            if anon_name.lower().replace(" ", "") == cleaned_query:
                name_or_idx = real_name
                break

    # Check if it's a number (index)
    if name_or_idx.isdigit():
        idx = int(name_or_idx)
        if 1 <= idx <= len(personnel_list):
            return personnel_list[idx - 1], None
        else:
            return None, f"Index {idx} out of range (1-{len(personnel_list)})"

    # Check aliases (case-insensitive)
    if aliases:
        query_lower = name_or_idx.lower()
        for alias, real_name in aliases.items():
            if alias.lower() == query_lower:
                # Verify the real name exists
                if real_name in personnel_list:
                    return real_name, None
                # Alias points to unknown person, try fuzzy on real_name
                break

    # Try exact match first
    if name_or_idx in personnel_list:
        return name_or_idx, None

    # Fuzzy match: case-insensitive substring search
    query = name_or_idx.lower()
    matches = [p for p in personnel_list if query in p.lower()]

    if len(matches) == 1:
        return matches[0], None
    elif len(matches) > 1:
        match_list = "\n".join(f"  - {m}" for m in matches)
        return None, f"Multiple personnel matching '{name_or_idx}':\n{match_list}"

    # No matches
    if allow_missing:
        return name_or_idx, None
    return None, f"No personnel found matching '{name_or_idx}'"


def load_aliases(data_dir: str | Path) -> dict[str, str]:
    """Load personnel aliases from aliases.yaml."""
    import yaml

    aliases_path = Path(data_dir) / "projects" / "aliases.yaml"
    if aliases_path.exists():
        with open(aliases_path) as f:
            data = yaml.safe_load(f) or {}
            return data.get("aliases", {})  # type: ignore[no-any-return]
    return {}


def save_aliases(data_dir: str | Path, aliases: dict[str, str]) -> None:
    """Save personnel aliases to aliases.yaml."""
    from ..yaml_utils import yaml_transaction

    aliases_path = Path(data_dir) / "projects" / "aliases.yaml"
    with yaml_transaction(aliases_path) as data:
        data.clear()
        data["aliases"] = aliases
