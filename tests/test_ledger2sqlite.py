from __future__ import annotations

import sqlite3
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from db import build_database
from transformer import PostingRecord, PriceRecord, TransactionRecord, parse_prices, transform_transactions


def make_transaction(
    index: int, postings: list[PostingRecord], tags: str | None = None
) -> TransactionRecord:
    return TransactionRecord(
        hledger_index=index,
        date="2026-01-02",
        effective_date=None,
        status="cleared",
        code=None,
        payee="Example",
        narration=None,
        tags=tags,
        postings=postings,
    )


class Ledger2SQLiteTests(unittest.TestCase):
    def test_transform_uses_exact_mantissa_and_tags(self) -> None:
        raw = [
        {
            "tindex": 1,
            "tdate": "2026-01-02",
            "tdate2": None,
            "tdescription": "Store | Groceries",
            "tstatus": "Cleared",
            "ttags": [["project", "home"]],
            "tpostings": [
                {
                    "paccount": "Expenses:Food",
                    "pamount": [
                        {
                            "acommodity": "$",
                            "aquantity": {"decimalMantissa": -1234, "decimalPlaces": 2},
                        }
                    ],
                    "pstatus": "Unmarked",
                    "ptags": [["receipt", "yes"]],
                }
            ],
        }
        ]
        transactions, precision = transform_transactions(raw)
        transaction = transactions[0]
        self.assertEqual(transaction.payee, "Store")
        self.assertEqual(transaction.narration, "Groceries")
        self.assertEqual(transaction.tags, '{"project": "home"}')
        self.assertEqual(transaction.postings[0].amount_str, "-12.34")
        self.assertEqual(transaction.postings[0].tags, '{"receipt": "yes"}')
        self.assertEqual(precision, {"$": 2})

    def test_parse_prices_supports_adjacent_and_separate_quote(self) -> None:
        prices = parse_prices('P 2026-01-01 ABC $1.25\nP 2026-01-02 "XYZ Coin" 2.5 USD\n')
        self.assertEqual(
            prices,
            [
                PriceRecord("2026-01-01", "ABC", "$", "1.25"),
                PriceRecord("2026-01-02", "XYZ Coin", "USD", "2.5"),
            ],
        )

    def test_database_hierarchy_balances_and_valuation(self) -> None:
        postings = [
            PostingRecord("Assets:Bank:Checking", Decimal("10.25"), "10.25", "USD", None, None, "unmarked", None),
            PostingRecord("Equity:Opening", Decimal("-10.25"), "-10.25", "USD", None, None, "unmarked", None),
        ]
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "journal.db"
            build_database(
                output,
                [make_transaction(1, postings)],
                [PriceRecord("2026-01-01", "USD", "EUR", "0.9")],
                {"USD": 2},
            )
            connection = sqlite3.connect(output)
            try:
                self.assertEqual(connection.execute("SELECT SUM(amount_int) FROM postings").fetchone()[0], 0)
                account = connection.execute(
                    "SELECT parent_id, depth, root_type, level_1, level_2, level_3 "
                    "FROM accounts WHERE name = 'Assets:Bank:Checking'"
                ).fetchone()
                self.assertEqual(account[1:], (2, "asset", "Assets", "Bank", "Checking"))
                self.assertEqual(
                    account[0],
                    connection.execute("SELECT id FROM accounts WHERE name = 'Assets:Bank'").fetchone()[0],
                )
                self.assertEqual(
                    connection.execute(
                        "SELECT SUM(p.amount_int) FROM postings p "
                        "JOIN commodities c ON c.id = p.commodity_id "
                        "WHERE p.transaction_id = 1 AND c.symbol = 'USD'"
                    ).fetchone()[0],
                    0,
                )
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM v_postings_valued").fetchone()[0], 2)
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM v_account_balances").fetchone()[0], 2)
            finally:
                connection.close()

    def test_failed_build_preserves_existing_database(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "journal.db"
            connection = sqlite3.connect(output)
            try:
                connection.execute("CREATE TABLE sentinel(value TEXT)")
                connection.execute("INSERT INTO sentinel VALUES ('untouched')")
                connection.commit()
            finally:
                connection.close()

            invalid = make_transaction(1, [])
            object.__setattr__(invalid, "tags", "not valid JSON")
            with self.assertRaises(ValueError):
                build_database(output, [invalid], [], {})

            connection = sqlite3.connect(output)
            try:
                self.assertEqual(connection.execute("SELECT value FROM sentinel").fetchone()[0], "untouched")
            finally:
                connection.close()
            self.assertEqual(list(Path(directory).glob("*.tmp")), [])


if __name__ == "__main__":
    unittest.main()