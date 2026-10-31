"""Read-only MCP server for querying a ledger2sqlite database."""

from __future__ import annotations

import json
import os
import re
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any, Dict, Tuple

from mcp.server.fastmcp import FastMCP

from db import build_database
from extractor import extract_prices, extract_transactions
from transformer import parse_prices, transform_transactions


mcp = FastMCP("ledger2sqlite")
DEFAULT_DATABASE = Path(os.environ.get("LEDGER2SQLITE_DATABASE", "journal.db"))
MAX_ROWS = 1000


def _database_path() -> Path:
    path = Path(os.environ.get("LEDGER2SQLITE_DATABASE", str(DEFAULT_DATABASE))).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    return path.resolve()


def _resolve_path(value: str) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    return path.resolve()


def _validate_ledger_database(path: Path) -> None:
    if not path.is_file():
        raise FileNotFoundError(f"Ledger database not found at {path}.")
    connection = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True, timeout=5)
    try:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
    except sqlite3.Error as exc:
        raise ValueError(f"Could not read SQLite database at {path}: {exc}") from exc
    finally:
        connection.close()
    required_tables = {"transactions", "postings", "accounts", "commodities", "market_prices"}
    missing = required_tables - tables
    if missing:
        raise ValueError(
            f"Database at {path} is not a ledger2sqlite database; missing tables: "
            f"{', '.join(sorted(missing))}"
        )


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
        sqlite3.SQLITE_RECURSIVE,
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


def _parse_recipe_header(sql_text: str) -> Tuple[str, str]:
    """Extract (title, summary) from the leading /* ... */ comment block."""
    match = re.match(r"^\s*/\*(.*?)\*/", sql_text, re.DOTALL)
    if not match:
        return ("Untitled", "")

    lines = [line.strip() for line in match.group(1).strip().splitlines()]
    non_empty = [line for line in lines if line]

    title = non_empty[0] if non_empty else "Untitled"
    # Take the next sentence or paragraph as the summary
    summary = " ".join(non_empty[1:3]) if len(non_empty) > 1 else ""
    return title, summary

def _json_value(value: Any) -> Any:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


@mcp.tool()
def query_ledger(sql: str, limit: int = 100) -> str:
    """Run a read-only SQL query against a ledger database.

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

    # Use a query-only SQLite connection and EXPLAIN first, which rejects
    # writes, multiple statements, and unsupported SQL before executing the
    # query.
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
def convert_journal_to_sqlite(journal: str, output: str = "journal.db") -> str:
    """Convert an hledger journal to SQLite and configure it for query_ledger.

    Requires the hledger executable to be installed and available on PATH.
    The output database is atomically replaced after a successful conversion.

    Args:
        journal: Path to the hledger journal file.
        output: Destination SQLite path (defaults to ./journal.db).
    """
    journal_path = _resolve_path(journal)
    output_path = _resolve_path(output)
    if not journal_path.is_file():
        raise FileNotFoundError(f"hledger journal not found at {journal_path}.")
    if journal_path == output_path:
        raise ValueError("output database path must not be the journal path")

    raw_transactions = extract_transactions(journal_path)
    transactions, precision = transform_transactions(raw_transactions)
    prices = parse_prices(extract_prices(journal_path))
    build_database(output_path, transactions, prices, precision)

    # MCP calls run in this server process, so subsequent query_ledger calls
    # use the newly built database without requiring a server restart.
    os.environ["LEDGER2SQLITE_DATABASE"] = str(output_path)
    return json.dumps(
        {
            "journal": str(journal_path),
            "database": str(output_path),
            "transaction_count": len(transactions),
            "posting_count": sum(len(transaction.postings) for transaction in transactions),
            "market_price_count": len(prices),
            "configured_environment": "LEDGER2SQLITE_DATABASE",
            "ready_for_query": True,
        },
        ensure_ascii=False,
    )


@mcp.tool()
def set_ledger_database(database: str) -> str:
    """Configure query_ledger to use an existing ledger2sqlite database.

    The environment variable is set in the running MCP server process, so it
    applies to subsequent query_ledger calls without restarting the server.

    Args:
        database: Path to an existing ledger2sqlite SQLite database.
    """
    path = _resolve_path(database)
    _validate_ledger_database(path)
    os.environ["LEDGER2SQLITE_DATABASE"] = str(path)
    return json.dumps(
        {
            "database": str(path),
            "configured_environment": "LEDGER2SQLITE_DATABASE",
            "ready_for_query": True,
        },
        ensure_ascii=False,
    )


@mcp.tool()
def get_ledger_context(include_schema: bool = True) -> str:
    """Return query guidelines and the recipe catalog, optionally including the full schema.

    Set include_schema to false when only the recipe catalog and query guidance are needed.
    """
    root = Path(__file__).resolve().parent
    recipes_dir = root / "recipes"

    catalog: Dict[str, Dict[str, str]] = {}
    for path in sorted(recipes_dir.glob("*.sql")):
        if path.name == "schema.sql":
            continue
        text = path.read_text(encoding="utf-8")
        title, summary = _parse_recipe_header(text)
        catalog[path.stem] = {
            "title": title,
            "summary": summary,
        }

    schema_path = recipes_dir / "schema.sql"
    schema = (
        schema_path.read_text(encoding="utf-8")
        if include_schema and schema_path.exists()
        else None
    )

    return json.dumps(
        {
            "database": str(_database_path()),
            "schema_guidance": schema,
            "recipes_catalog": catalog,
            "query_rules": [
                "Use query_ledger for one read-only SELECT/CTE query at a time.",
                "Filter or group by commodity before adding amount_real or amount_int.",
                "Use v_postings_valued or the recipes' as-of price lookup for valuation.",
                "For net worth, value current asset/liability balances as of the chosen date; do not sum historical posting market values.",
                "To inspect a recipe before running or modifying it, call get_recipe(recipe_name).",
            ],
        },
        ensure_ascii=False,
    )


@mcp.tool()
def get_recipe(recipe_name: str) -> str:
    """Retrieve the full SQL query template for a given recipe name from the catalog."""
    root = Path(__file__).resolve().parent
    recipe_file = (root / "recipes" / f"{recipe_name}.sql").resolve()

    # Safety check to stay inside recipes directory
    if not recipe_file.is_relative_to(root / "recipes") or not recipe_file.exists():
        return f"Error: Recipe '{recipe_name}' not found."

    return recipe_file.read_text(encoding="utf-8")


if __name__ == "__main__":
    mcp.run(transport="stdio")
