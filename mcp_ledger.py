"""Read-only MCP server for querying a ledger2sqlite database."""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP


mcp = FastMCP("ledger2sqlite")
DEFAULT_DATABASE = Path(os.environ.get("LEDGER2SQLITE_DATABASE", "journal.db"))
MAX_ROWS = 1000


def _database_path() -> Path:
    path = Path(os.environ.get("LEDGER2SQLITE_DATABASE", str(DEFAULT_DATABASE))).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    return path.resolve()


def _open_readonly_database() -> sqlite3.Connection:
    path = _database_path()
    if not path.is_file():
        raise FileNotFoundError(
            f"Ledger database not found at {path}. Create it with 'uv run python main.py' "
            "or set LEDGER2SQLITE_DATABASE."
        )
    connection = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True, timeout=5)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only = ON")
    return connection


def _read_authorizer(
    action: int,
    arg1: str | None,
    arg2: str | None,
    database: str | None,
    source: str | None,
) -> int:
    """Allow only reads, SELECTs, scalar functions, and recursive CTEs."""
    del source
    allowed_actions = {
        sqlite3.SQLITE_SELECT,
        sqlite3.SQLITE_READ,
        sqlite3.SQLITE_FUNCTION,
    }
    if action not in allowed_actions:
        return sqlite3.SQLITE_DENY
    if action == sqlite3.SQLITE_READ and database not in {None, "main"}:
        return sqlite3.SQLITE_DENY
    function_name = (arg2 or arg1 or "").casefold()
    if action == sqlite3.SQLITE_FUNCTION and function_name in {
        "load_extension",
        "writefile",
        "readfile",
    }:
        return sqlite3.SQLITE_DENY
    return sqlite3.SQLITE_OK


def _json_value(value: Any) -> Any:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


@mcp.tool()
def query_ledger(sql: str, limit: int = 100) -> str:
    """Run a read-only SQL query against the personal-finance ledger database.

    Query tables such as transactions, postings, accounts, commodities, and
    market_prices, or views v_register, v_account_balances, and
    v_postings_valued. Use named columns rather than SELECT * where practical.
    Never add native amounts across different commodities: filter/group by
    commodity, or use v_postings_valued for historical market valuation.

    Helpful SQL recipes and annotated schema are in the local recipes/ folder.
    Recipe queries can be used as a starting point and should be reviewed for
    relevant date/currency choices before execution.

    Args:
        sql: One read-only SQLite SELECT or WITH ... SELECT statement.
        limit: Maximum rows returned (1-1000; defaults to 100).
    """
    if not 1 <= limit <= MAX_ROWS:
        raise ValueError(f"limit must be between 1 and {MAX_ROWS}")
    if not sql.strip() or "\x00" in sql:
        raise ValueError("sql must contain one non-empty read-only SELECT query")

    # Use a query-only SQLite connection and EXPLAIN first, which rejects writes,
    # multiple statements, and unsupported SQL before executing the query.
    with closing(_open_readonly_database()) as connection:
        connection.set_authorizer(_read_authorizer)
        try:
            connection.execute(f"EXPLAIN QUERY PLAN {sql}").fetchall()
            cursor = connection.execute(sql)
            if cursor.description is None:
                raise ValueError("query must return rows (use a SELECT statement)")
            columns = [item[0] for item in cursor.description]
            rows = cursor.fetchmany(limit + 1)
        except sqlite3.Error as exc:
            raise ValueError(f"query rejected or failed: {exc}") from exc

    truncated = len(rows) > limit
    result = {
        "database": str(_database_path()),
        "columns": columns,
        "row_count": min(len(rows), limit),
        "truncated": truncated,
        "rows": [
            {key: _json_value(value) for key, value in zip(columns, tuple(row), strict=True)}
            for row in rows[:limit]
        ],
        "notes": [
            "Amounts are native to their commodity unless a valuation view/query is used.",
            "Do not sum different commodities without converting them to a common valuation currency.",
        ],
    }
    return json.dumps(result, ensure_ascii=False, default=str)


@mcp.tool()
def get_ledger_context() -> str:
    """Return concise database schema guidance and available saved SQL recipes."""
    root = Path(__file__).resolve().parent
    recipes_dir = root / "recipes"
    recipe_files = sorted(recipes_dir.glob("*.sql"))
    recipes = {
        path.stem: path.read_text(encoding="utf-8")
        for path in recipe_files
        if path.name != "schema.sql"
    }
    schema_path = recipes_dir / "schema.sql"
    schema = schema_path.read_text(encoding="utf-8") if schema_path.exists() else ""
    return json.dumps(
        {
            "database": str(_database_path()),
            "schema_guidance": schema,
            "recipes": recipes,
            "query_rules": [
                "Use query_ledger for one read-only SELECT/CTE query at a time.",
                "Filter or group by commodity before adding amount_real or amount_int.",
                "Use v_postings_valued or the recipes' as-of price lookup for valuation.",
                "For net worth, value current asset/liability balances as of the chosen date; do not sum historical posting market values.",
            ],
        },
        ensure_ascii=False,
    )


if __name__ == "__main__":
    mcp.run(transport="stdio")
