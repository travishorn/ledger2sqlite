from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mcp_ledger import get_ledger_context, query_ledger


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
        with self.assertRaisesRegex(ValueError, "query rejected"):
            query_ledger("DELETE FROM transactions")
        with self.assertRaisesRegex(ValueError, "one statement"):
            query_ledger("SELECT 1; SELECT 2")

    def test_context_includes_schema_and_recipes(self) -> None:
        context = json.loads(get_ledger_context())
        self.assertIn("CREATE TABLE accounts", context["schema_guidance"])
        self.assertIn("cash_flow", context["recipes"])
        self.assertIn("spending_drift", context["recipes"])


if __name__ == "__main__":
    unittest.main()
