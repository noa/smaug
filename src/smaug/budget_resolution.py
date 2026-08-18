"""
Centralized budget resolution for Smaug.

Resolves authoritative project budgets and budget_config.yaml paths across all
contractual YAML, Excel, manifest, and report sources.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .store import ProjectStore


def resolve_budget_config_path(
    store: ProjectStore, project_id: str, data_dir: str | Path
) -> Path | None:
    """Resolve the path to a project's budget_config.yaml.

    Returns the path (which may or may not exist yet), or None if the
    project itself is not found.
    """
    data = store.get_project(project_id)
    if not data:
        return None

    data_dir_path = Path(data_dir)

    if data.project.budget_dir:
        b_path = Path(data.project.budget_dir)
        if b_path.is_absolute():
            return b_path / "budget_config.yaml"
        # Check relative to data_dir first
        candidate1 = data_dir_path / b_path / "budget_config.yaml"
        if candidate1.exists():
            return candidate1
        candidate2 = data_dir_path / "projects" / project_id / "budget_config.yaml"
        if candidate2.exists():
            return candidate2
        return data_dir_path / b_path / "budget_config.yaml"

    # Default convention: projects/<PROJECT>/budget_config.yaml under data_dir
    return data_dir_path / "projects" / project_id / "budget_config.yaml"


def resolve_project_budget(
    store: ProjectStore,
    project_id: str,
    data_dir: str | Path,
) -> tuple[Decimal, str]:
    """Resolve the authoritative budget for a project.

    Checks sources in priority order:
    1. Contractual budget YAML (budget_config.yaml) — total_budget across periods
    2. Excel budget file (*Budget*.xlsx) in budget_dir
    3. manifest.yaml total_budget
    4. Latest report funded_ceiling

    Returns:
        tuple[Decimal, str]: (budget_amount, source_description)
    """
    data = store.get_project(project_id)
    if not data:
        return Decimal("0"), "none"

    # 1. Contractual budget YAML
    b_path = resolve_budget_config_path(store, project_id, data_dir)
    if b_path and b_path.exists():
        from .contractual_budget import load_contractual_budget

        contract = load_contractual_budget(b_path)
        if contract and contract.total_budget > Decimal("0"):
            return contract.total_budget, "contractual_budget"

    # 2. Excel budget
    if data.budget and data.budget.total_budget > Decimal("0"):
        return data.budget.total_budget, "excel_budget"

    # 3. Manifest budget
    if data.project.total_budget and data.project.total_budget > Decimal("0"):
        return data.project.total_budget, "manifest"

    # 4. Latest spending report funded_ceiling
    if data.spending:
        latest = max(data.spending, key=lambda r: (r.year, r.month))
        if latest.funded_ceiling and latest.funded_ceiling > Decimal("0"):
            return latest.funded_ceiling, "funded_ceiling"

    return Decimal("0"), "none"
