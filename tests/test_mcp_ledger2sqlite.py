from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from db import build_database
from mcp_ledger2sqlite import (
    convert_journal_to_sqlite,
    get_ledger_context,
    query_ledger,
    set_ledger_database,
)
from transformer import PostingRecord, TransactionRecord


def make_transaction(transaction_date: str = "2026-01-02") -> TransactionRecord:
    return TransactionRecord(
        hledger_index=1,
        date=transaction_date,
        effective_date=None,
        status="unmarked",
        code=None,
        payee="Example",
        narration=None,
        tags=None,
        postings=[
            PostingRecord("Assets:Cash", Decimal("10.00"), "10.00", "USD", None, None, "unmarked", None),
            PostingRecord("Equity:Opening", Decimal("-10.00"), "-10.00", "USD", None, None, "unmarked", None),
        ],
    )


def create_ledger_database(path: Path) -> None:
    build_database(path, [make_transaction()], [], {"USD": 2})


class LedgerMcpTests(unittest.TestCase):
    def test_query_returns_rows_and_truncation_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "ledger.db"
            import sqlite3

            connection = sqlite3.connect(database)
            try:
                connection.execute("CREATE TABLE sample(value INTEGER)")
                connection.executemany("INSERT INTO sample VALUES (?)", [(1,), (2,), (3,)])
                connection.commit()
            finally:
                connection.close()

            with patch.dict(os.environ, {"LEDGER2SQLITE_DATABASE": str(database)}):
                result = json.loads(query_ledger("SELECT value FROM sample ORDER BY value", limit=2))

        self.assertEqual(result["columns"], ["value"])
        self.assertEqual(result["rows"], [{"value": 1}, {"value": 2}])
        self.assertTrue(result["truncated"])

    def test_query_rejects_writes_and_multiple_statements(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "ledger.db"
            create_ledger_database(database)
            with patch.dict(os.environ, {"LEDGER2SQLITE_DATABASE": str(database)}):
                with self.assertRaisesRegex(ValueError, "query rejected"):
                    query_ledger("DELETE FROM transactions")
                with self.assertRaisesRegex(ValueError, "one statement"):
                    query_ledger("SELECT 1; SELECT 2")

    def test_conversion_builds_database_and_configures_queries(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            journal = Path(directory) / "ledger.journal"
            journal.write_text("; fixture journal", encoding="utf-8")
            database = Path(directory) / "output" / "ledger.db"
            with (
                patch("mcp_ledger2sqlite.extract_transactions", return_value=[]),
                patch("mcp_ledger2sqlite.extract_prices", return_value=""),
                patch.dict(os.environ, {}, clear=True),
            ):
                result = json.loads(convert_journal_to_sqlite(str(journal), str(database)))
                configured_database = os.environ["LEDGER2SQLITE_DATABASE"]
                query_result = json.loads(query_ledger("SELECT COUNT(*) AS count FROM transactions"))

            self.assertEqual(result["database"], str(database.resolve()))
            self.assertTrue(result["ready_for_query"])
            self.assertEqual(configured_database, str(database.resolve()))
            self.assertEqual(query_result["rows"], [{"count": 0}])

    def test_set_database_validates_and_configures_database(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "ledger.db"
            create_ledger_database(database)
            with patch.dict(os.environ, {}, clear=True):
                result = json.loads(set_ledger_database(str(database)))
                query_result = json.loads(query_ledger("SELECT COUNT(*) AS count FROM transactions"))

            self.assertTrue(result["ready_for_query"])
            self.assertEqual(query_result["rows"], [{"count": 1}])

            unrelated = Path(directory) / "unrelated.db"
            connection = sqlite3.connect(unrelated)
            try:
                connection.execute("CREATE TABLE sample(value INTEGER)")
            finally:
                connection.close()
            with self.assertRaisesRegex(ValueError, "not a ledger2sqlite database"):
                set_ledger_database(str(unrelated))

    def test_financial_report_recipes_execute_through_query_tool(self) -> None:
        recipe_directory = Path(__file__).resolve().parents[1] / "recipes"
        recipe_names = (
            "monthly_balance_sheet_6mo.sql",
            "monthly_cash_outflows_debt_service_6mo.sql",
            "monthly_income_analysis_6mo.sql",
            "yearly_balance_sheet_5y.sql",
        )
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "ledger.db"
            today = date.today()
            current_month = today.replace(day=1)
            previous_month_end = date.fromordinal(current_month.toordinal() - 1)
            transaction = make_transaction(previous_month_end.isoformat())
            postings = transaction.postings
            postings.extend(
                [
                    PostingRecord("Expenses:Food", Decimal("10.00"), "10.00", "USD", None, None, "unmarked", None),
                    PostingRecord("Revenues:Salary", Decimal("-50.00"), "-50.00", "USD", None, None, "unmarked", None),
                    PostingRecord("Liabilities:Student Loans", Decimal("20.00"), "20.00", "USD", None, None, "unmarked", None),
                    PostingRecord("Assets:Cash", Decimal("20.00"), "20.00", "USD", None, None, "unmarked", None),
                ]
            )
            transaction = TransactionRecord(
                transaction.hledger_index,
                transaction.date,
                transaction.effective_date,
                transaction.status,
                transaction.code,
                transaction.payee,
                transaction.narration,
                transaction.tags,
                postings,
            )
            build_database(database, [transaction], [], {"USD": 2})
            with patch.dict(os.environ, {"LEDGER2SQLITE_DATABASE": str(database)}):
                results = {
                    name: json.loads(
                        query_ledger((recipe_directory / name).read_text(encoding="utf-8"))
                    )
                    for name in recipe_names
                }

        self.assertEqual(
            len({row["month"] for row in results["monthly_balance_sheet_6mo.sql"]["rows"]}), 6
        )
        self.assertEqual(
            len({row["year"] for row in results["yearly_balance_sheet_5y.sql"]["rows"]}), 5
        )
        cash_rows = results["monthly_cash_outflows_debt_service_6mo.sql"]["rows"]
        self.assertEqual(len(cash_rows), 6)
        latest_cash_month = next(row for row in cash_rows if row["month"] == previous_month_end.strftime("%Y-%m"))
        self.assertEqual(latest_cash_month["living_expenses"], 10)
        self.assertEqual(latest_cash_month["installment_principal_paid"], 20)
        income_rows = results["monthly_income_analysis_6mo.sql"]["rows"]
        self.assertEqual(len(income_rows), 6)
        latest_income_month = next(row for row in income_rows if row["month"] == previous_month_end.strftime("%Y-%m"))
        self.assertEqual(latest_income_month["income"], 50)

    def test_context_includes_schema_and_recipes(self) -> None:
        context = json.loads(get_ledger_context())
        self.assertIn("CREATE TABLE accounts", context["schema_guidance"])
        self.assertIn("cash_flow", context["recipes"])
        self.assertIn("spending_drift", context["recipes"])


if __name__ == "__main__":
    unittest.main()
