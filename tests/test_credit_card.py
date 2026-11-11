"""
Unit tests for credit card statement parsing and heuristic classification.
"""

from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory

from smaug.credit_card import (
    ChaseCSVParser,
    classify_transaction,
    parse_statement,
)
from smaug.models import CreditCardTransaction, Date, ReimbursementCategory

SAMPLE_CHASE_CSV = """Transaction Date,Post Date,Description,Category,Type,Amount,Memo
09/15/2026,09/16/2026,GIANT FOOD INC #100,Groceries,Sale,-80.00,
09/07/2026,09/08/2026,ANTHROPIC* CLAUDE SUB,Shopping,Sale,-200.00,
09/06/2026,09/07/2026,ANTHROPIC,Shopping,Sale,-100.00,
09/01/2026,09/02/2026,GOOGLE *CLOUD ABC123,Bills & Utilities,Sale,-350.00,
08/06/2026,08/09/2026,HILTON HOTEL PARKING,Travel,Sale,-50.00,
08/05/2026,08/07/2026,AIRPORT PARKING GARAGE,Travel,Sale,-150.00,
07/22/2026,07/23/2026,CITY TAXI 12345,Travel,Sale,-45.00,
07/17/2026,07/19/2026,1PASSWORD,Shopping,Sale,-70.00,
06/23/2026,06/24/2026,DELTA AIR   0060000000000,Travel,Sale,-850.00,
06/04/2026,06/07/2026,COMFORT INNS,Travel,Sale,-240.00,
06/01/2026,06/02/2026,DOWNTOWN FITNESS GYM,Education,Sale,-120.00,
06/02/2026,06/02/2026,ACME LAWN & LANDSCAPING,Home,Sale,-300.00,
"""


def test_chase_parser_can_parse():
    parser = ChaseCSVParser()
    with TemporaryDirectory() as tmpdir:
        csv_file = Path(tmpdir) / "Chase_Activity.csv"
        csv_file.write_text(SAMPLE_CHASE_CSV)
        assert parser.can_parse(csv_file) is True

        txt_file = Path(tmpdir) / "notes.txt"
        txt_file.write_text("not a csv")
        assert parser.can_parse(txt_file) is False


def test_chase_parser_extracts_transactions():
    with TemporaryDirectory() as tmpdir:
        csv_file = Path(tmpdir) / "Chase1234_Activity.csv"
        csv_file.write_text(SAMPLE_CHASE_CSV)

        txs = parse_statement(csv_file)
        assert len(txs) == 12

        # Check positive amounts
        anthropic = next(t for t in txs if "ANTHROPIC* CLAUDE SUB" in t.description)
        assert anthropic.amount == Decimal("200.00")
        assert anthropic.transaction_date == Date(2026, 9, 7)
        assert anthropic.post_date == Date(2026, 9, 8)
        assert anthropic.card_source == "Chase1234_Activity"
        assert len(anthropic.hash_id) == 16


def test_classification_compute():
    tx = CreditCardTransaction(
        transaction_date=Date(2026, 9, 1),
        post_date=None,
        description="GOOGLE *CLOUD ABC123",
        category="Bills & Utilities",
        amount=Decimal("350.00"),
    )
    res = classify_transaction(tx)
    assert res.is_reimbursable is True
    assert res.category == ReimbursementCategory.COMPUTE
    assert res.confidence == "high"


def test_classification_travel():
    tx = CreditCardTransaction(
        transaction_date=Date(2026, 6, 23),
        post_date=None,
        description="DELTA AIR   0060000000000",
        category="Travel",
        amount=Decimal("850.00"),
    )
    res = classify_transaction(tx)
    assert res.is_reimbursable is True
    assert res.category == ReimbursementCategory.TRAVEL
    assert res.confidence == "high"

    # Taxi
    taxi_tx = CreditCardTransaction(
        transaction_date=Date(2026, 7, 22),
        post_date=None,
        description="CITY TAXI 12345",
        category="Travel",
        amount=Decimal("45.00"),
    )
    res_taxi = classify_transaction(taxi_tx)
    assert res_taxi.is_reimbursable is True
    assert res_taxi.category == ReimbursementCategory.TRAVEL


def test_classification_personal():
    tx_groceries = CreditCardTransaction(
        transaction_date=Date(2026, 9, 15),
        post_date=None,
        description="GIANT FOOD INC #100",
        category="Groceries",
        amount=Decimal("80.00"),
    )
    res = classify_transaction(tx_groceries)
    assert res.is_reimbursable is False
    assert res.confidence == "high"

    tx_gym = CreditCardTransaction(
        transaction_date=Date(2026, 6, 1),
        post_date=None,
        description="DOWNTOWN FITNESS GYM",
        category="Education",
        amount=Decimal("120.00"),
    )
    res_gym = classify_transaction(tx_gym)
    assert res_gym.is_reimbursable is False
