"""
Credit card and banking statement ingestion and heuristic classification.

Parses transaction activity exports (such as Chase credit card CSVs) and
classifies transactions into research expense categories (travel, compute/cloud,
lab supplies, software) versus personal/non-reimbursable expenses.
"""

from __future__ import annotations

import csv
import hashlib
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import ClassVar

from .models import CreditCardTransaction, ReimbursementCategory


@dataclass
class ClassificationResult:
    """Heuristic classification result for a transaction."""

    category: ReimbursementCategory
    is_reimbursable: bool
    confidence: str  # "high", "medium", "low"
    reason: str
    suggested_project: str | None = None


# ---------------------------------------------------------------------------
# Heuristic Matcher Patterns
# ---------------------------------------------------------------------------

COMPUTE_PATTERNS = [
    (r"\b(anthropic|claude\s*sub)\b", "Anthropic AI API / Claude subscription"),
    (
        r"\b(gcp|google\s*\*?\s*cloud)\b|\bgoogle\b.*\b(cloud|compute)\b|\b(cloud|compute)\b.*\bgoogle\b",
        "Google Cloud compute",
    ),
    (r"\b(aws|amazon\s*web\s*services)\b", "AWS cloud infrastructure"),
    (r"\b(openai|chatgpt)\b", "OpenAI API / ChatGPT subscription"),
    (
        r"\b(lambda\s*labs|runpod|together\.ai|paperspace|modal|replicate)\b",
        "Cloud GPU / AI provider",
    ),
    (r"\b(azure|microsoft\s*azure)\b", "Microsoft Azure cloud"),
    (r"\b(github|gitlab)\b", "Developer tooling / hosting"),
    (r"\b(wandb|weights\s*&\s*biases|neptune\.ai)\b", "ML experiment tracking"),
    (r"\b(overleaf)\b", "Overleaf LaTeX subscription"),
    (r"\b1password\b", "1Password security software"),
]

TRAVEL_PATTERNS = [
    (
        r"\b(delta\s*air|united\s*air|american\s*air|southwest|jetblue|alaska\s*air|british\s*airways|lufthansa|air\s*france)\b",
        "Airline ticket",
    ),
    (
        r"\b(hilton|marriott|hyatt|comfort\s*inns?|holiday\s*inn|sheraton|westin|airbnb|hotel|motel)\b",
        "Lodging / Hotel",
    ),
    (r"\b(taxi|london\s*taxi|uber|lyft|cab)\b", "Ground transportation / Taxi"),
    (r"\b(amtrak|tfl\s*visitor|eurostar|rail)\b", "Train / Rail / Public transit"),
    (
        r"\b(bwi\s*long\s*term|airport\s*parking|parking|garage)\b",
        "Airport parking / Travel parking",
    ),
    (r"\b(neurips|icml|iclr|emnlp|cvpr|aaai|usenix|acm|ieee|kdd)\b", "Conference registration"),
]

PERSONAL_PATTERNS = [
    (
        r"\b(giant\s*food|sprouts|safeway|trader\s*joe|wegmans|publix|whole\s*foods|h\s*mart|costco)\b",
        "Groceries",
    ),
    (
        r"\b(lawn|landscaping|plumbing|home\s*depot|lowes|furnace|hvac|electric)\b",
        "Home maintenance / Utilities",
    ),
    (
        r"\b(dojo|karate|martial\s*arts|gym|fitness|recreation|dicks\s*sporting)\b",
        "Personal recreation / Sports",
    ),
    (
        r"\b(steam\s*purchase|chewy|petco|petsmart|toy|games)\b",
        "Personal retail / Pet / Games",
    ),
    (r"\b(geico|auto\s*insurance|state\s*farm)\b", "Personal auto insurance"),
    (
        r"\b(nordstrom|uniqlo|carters|target|walmart)\b",
        "Personal clothing / Retail",
    ),
    (
        r"\b(museum|aquarium|science\s*center|cinema|theater|amusement)\b",
        "Entertainment / Family attractions",
    ),
]


def classify_transaction(tx: CreditCardTransaction) -> ClassificationResult:
    """
    Classify a credit card transaction using regex heuristics.

    Returns ClassificationResult indicating category, whether reimbursable,
    confidence level, and rationale.
    """
    desc = tx.description.lower()
    chase_cat = (tx.category or "").strip().lower()

    # 1. Check for personal exclusions first
    for pattern, label in PERSONAL_PATTERNS:
        if re.search(pattern, desc, re.IGNORECASE):
            return ClassificationResult(
                category=ReimbursementCategory.OTHER,
                is_reimbursable=False,
                confidence="high",
                reason=f"Matches personal pattern: {label}",
            )

    # 2. Check for Compute / AI / Cloud
    for pattern, label in COMPUTE_PATTERNS:
        if re.search(pattern, desc, re.IGNORECASE):
            return ClassificationResult(
                category=ReimbursementCategory.COMPUTE,
                is_reimbursable=True,
                confidence="high",
                reason=f"Matches compute/cloud keyword: {label}",
            )

    # 3. Check for Travel
    for pattern, label in TRAVEL_PATTERNS:
        if re.search(pattern, desc, re.IGNORECASE):
            return ClassificationResult(
                category=ReimbursementCategory.TRAVEL,
                is_reimbursable=True,
                confidence="high",
                reason=f"Matches travel keyword: {label}",
            )

    # 4. Chase statement Category == "Travel" fallback
    if chase_cat == "travel":
        return ClassificationResult(
            category=ReimbursementCategory.TRAVEL,
            is_reimbursable=True,
            confidence="medium",
            reason="Statement categorized as Travel",
        )

    # 5. Food & Drink: generally personal unless travel context, flag as low confidence personal
    if chase_cat in ("food & drink", "groceries"):
        return ClassificationResult(
            category=ReimbursementCategory.OTHER,
            is_reimbursable=False,
            confidence="medium",
            reason=f"Dining/food category ('{tx.category}') typically personal",
        )

    # 6. Default unclassified
    return ClassificationResult(
        category=ReimbursementCategory.OTHER,
        is_reimbursable=False,
        confidence="low",
        reason="No research keywords matched",
    )


# ---------------------------------------------------------------------------
# Statement Parsers
# ---------------------------------------------------------------------------


class StatementParser(ABC):
    """Abstract base class for credit card and bank statement parsers."""

    @abstractmethod
    def name(self) -> str:
        """Name of the parser (e.g. 'Chase Credit Card CSV')."""

    @abstractmethod
    def can_parse(self, file_path: Path) -> bool:
        """Check if file matches parser format."""

    @abstractmethod
    def parse_file(self, file_path: Path) -> list[CreditCardTransaction]:
        """Parse statement into list of CreditCardTransaction items."""


class ChaseCSVParser(StatementParser):
    """Parser for Chase credit card activity CSV exports."""

    EXPECTED_COLUMNS: ClassVar[set[str]] = {
        "Transaction Date",
        "Post Date",
        "Description",
        "Category",
        "Type",
        "Amount",
        "Memo",
    }

    def name(self) -> str:
        return "Chase Credit Card CSV"

    def can_parse(self, file_path: Path) -> bool:
        if file_path.suffix.lower() != ".csv":
            return False
        try:
            with open(file_path, newline="", encoding="utf-8-sig") as f:
                reader = csv.reader(f)
                header = next(reader, None)
                if not header:
                    return False
                header_set = {h.strip() for h in header if h}
                # Check for Chase format: Transaction Date, Description, Category, Amount
                return {"Transaction Date", "Description", "Category", "Amount"}.issubset(
                    header_set
                )
        except Exception:
            return False

    def parse_file(self, file_path: Path) -> list[CreditCardTransaction]:
        transactions: list[CreditCardTransaction] = []
        card_name = file_path.stem

        with open(file_path, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                tx_date_str = (row.get("Transaction Date") or "").strip()
                if not tx_date_str:
                    continue

                try:
                    tx_date = datetime.strptime(tx_date_str, "%m/%d/%Y").date()
                except ValueError:
                    continue

                post_date_str = (row.get("Post Date") or "").strip()
                post_date = None
                if post_date_str:
                    try:
                        post_date = datetime.strptime(post_date_str, "%m/%d/%Y").date()
                    except ValueError:
                        post_date = None

                raw_desc = (row.get("Description") or "").strip()
                raw_cat = (row.get("Category") or "").strip()
                raw_type = (row.get("Type") or "Sale").strip()
                raw_memo = (row.get("Memo") or "").strip()

                raw_amt = (row.get("Amount") or "0").replace("$", "").replace(",", "").strip()
                try:
                    dec_amt = Decimal(raw_amt)
                except InvalidOperation:
                    dec_amt = Decimal("0")

                # In Chase statements, purchases are negative numbers (e.g. -75.16).
                # Convert to positive amount for reimbursable expense tracking.
                positive_amt = abs(dec_amt)

                # Compute unique hash ID for deduplication
                hash_input = f"{tx_date_str}|{post_date_str}|{raw_desc}|{raw_amt}|{card_name}"
                hash_id = hashlib.sha256(hash_input.encode("utf-8")).hexdigest()[:16]

                transactions.append(
                    CreditCardTransaction(
                        transaction_date=tx_date,
                        post_date=post_date,
                        description=raw_desc,
                        category=raw_cat,
                        amount=positive_amt,
                        card_source=card_name,
                        transaction_type=raw_type,
                        memo=raw_memo if raw_memo else None,
                        hash_id=hash_id,
                    )
                )

        return transactions


PARSERS: list[StatementParser] = [
    ChaseCSVParser(),
]


def parse_statement(file_path: str | Path) -> list[CreditCardTransaction]:
    """Parse statement file with matching parser."""
    path = Path(file_path)
    for p in PARSERS:
        if p.can_parse(path):
            return p.parse_file(path)
    raise ValueError(f"No statement parser found for file: {file_path}")
