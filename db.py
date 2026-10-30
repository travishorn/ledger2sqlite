"""SQLite schema creation, normalized inserts, and atomic database replacement."""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
from datetime import date as Date
from decimal import Decimal
from pathlib import Path
from typing import Iterable, cast

from transformer import PriceRecord, TransactionRecord


SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE commodities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL UNIQUE,
    precision INTEGER NOT NULL DEFAULT 2
);

CREATE TABLE accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    parent_id INTEGER REFERENCES accounts(id) ON DELETE RESTRICT,
    depth INTEGER NOT NULL,
    root_type TEXT NOT NULL,
    level_1 TEXT NOT NULL,
    level_2 TEXT,
    level_3 TEXT
);

CREATE TABLE transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    hledger_index INTEGER NOT NULL UNIQUE,
    date TEXT NOT NULL,
    effective_date TEXT,
    status TEXT NOT NULL,
    code TEXT,
    payee TEXT,
    narration TEXT,
    comment TEXT,
    tags TEXT CHECK (tags IS NULL OR (json_valid(tags) AND json_type(tags) = 'object'))
);

CREATE TABLE postings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    transaction_id INTEGER NOT NULL REFERENCES transactions(id) ON DELETE CASCADE,
    account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE RESTRICT,
    amount_int INTEGER NOT NULL,
    amount_str TEXT NOT NULL,
    amount_real REAL GENERATED ALWAYS AS (CAST(amount_str AS REAL)) VIRTUAL,
    commodity_id INTEGER NOT NULL REFERENCES commodities(id) ON DELETE RESTRICT,
    cost_amount_str TEXT,
    cost_commodity_id INTEGER REFERENCES commodities(id) ON DELETE RESTRICT,
    status TEXT NOT NULL,
    comment TEXT,
    tags TEXT CHECK (tags IS NULL OR (json_valid(tags) AND json_type(tags) = 'object'))
);

CREATE TABLE market_prices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    base_commodity_id INTEGER NOT NULL REFERENCES commodities(id) ON DELETE RESTRICT,
    quote_commodity_id INTEGER NOT NULL REFERENCES commodities(id) ON DELETE RESTRICT,
    price_str TEXT NOT NULL,
    price_real REAL GENERATED ALWAYS AS (CAST(price_str AS REAL)) VIRTUAL,
    UNIQUE(date, base_commodity_id, quote_commodity_id)
);

CREATE INDEX idx_tx_date ON transactions(date);
CREATE INDEX idx_postings_account ON postings(account_id);
CREATE INDEX idx_postings_tx ON postings(transaction_id);
CREATE INDEX idx_accounts_root ON accounts(root_type, depth);

CREATE VIEW v_register AS
SELECT t.date, t.effective_date, t.status AS tx_status, t.code, t.payee,
    t.narration, t.comment AS tx_comment, p.comment AS posting_comment,
    a.name AS account, a.root_type, p.amount_str AS amount,
       p.amount_real, c.symbol AS commodity, p.tags AS posting_tags,
       t.tags AS tx_tags
FROM postings p
JOIN transactions t ON p.transaction_id = t.id
JOIN accounts a ON p.account_id = a.id
JOIN commodities c ON p.commodity_id = c.id
ORDER BY t.date, t.id;

CREATE VIEW v_account_balances AS
SELECT a.name AS account_name, a.root_type, a.depth, c.symbol AS commodity,
       ROUND(SUM(p.amount_real), c.precision) AS balance_real,
       COUNT(p.id) AS posting_count
FROM postings p
JOIN accounts a ON p.account_id = a.id
JOIN commodities c ON p.commodity_id = c.id
GROUP BY a.id, c.id;

CREATE VIEW v_postings_valued AS
SELECT p.id AS posting_id, t.date, a.name AS account,
       c_base.symbol AS native_commodity, p.amount_real AS native_amount,
       mp.price_real AS unit_price, c_quote.symbol AS valuation_commodity,
       p.amount_real * COALESCE(mp.price_real, 1.0) AS market_value
FROM postings p
JOIN transactions t ON p.transaction_id = t.id
JOIN accounts a ON p.account_id = a.id
JOIN commodities c_base ON p.commodity_id = c_base.id
LEFT JOIN market_prices mp ON mp.base_commodity_id = c_base.id
    AND mp.date = (
        SELECT MAX(mp_inner.date) FROM market_prices mp_inner
        WHERE mp_inner.base_commodity_id = c_base.id AND mp_inner.date <= t.date
    )
LEFT JOIN commodities c_quote ON mp.quote_commodity_id = c_quote.id;
"""


ROOT_TYPES = {
    "assets": "asset",
    "liabilities": "liability",
    "equity": "equity",
    "revenues": "revenue",
    "income": "revenue",
    "expenses": "expense",
}


def _decimal_places(value: Decimal) -> int:
    exponent = value.as_tuple().exponent
    return max(0, -exponent) if isinstance(exponent, int) else 0


def _validate_tags(tags: str | None, owner: str) -> None:
    if tags is None:
        return
    try:
        value = json.loads(tags)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{owner} tags must contain valid JSON") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{owner} tags must be a JSON object")


def initialize_schema(connection: sqlite3.Connection) -> None:
    """Create all tables, indexes, and views in a fresh connection."""
    connection.executescript(SCHEMA)


def _get_or_create_commodity(connection: sqlite3.Connection, symbol: str, precision: int) -> int:
    connection.execute(
        "INSERT INTO commodities(symbol, precision) VALUES (?, ?) "
        "ON CONFLICT(symbol) DO UPDATE SET precision = MAX(precision, excluded.precision)",
        (symbol, precision),
    )
    row = connection.execute("SELECT id FROM commodities WHERE symbol = ?", (symbol,)).fetchone()
    assert row is not None
    return int(row[0])


def _get_or_create_account(connection: sqlite3.Connection, name: str) -> int:
    existing = connection.execute("SELECT id FROM accounts WHERE name = ?", (name,)).fetchone()
    if existing is not None:
        return int(existing[0])

    parts = name.split(":")
    parent_id = _get_or_create_account(connection, ":".join(parts[:-1])) if len(parts) > 1 else None
    normalized_root = parts[0].casefold()
    root_type = ROOT_TYPES.get(normalized_root, "other")
    values = (
        name,
        parent_id,
        len(parts) - 1,
        root_type,
        parts[0],
        parts[1] if len(parts) > 1 else None,
        parts[2] if len(parts) > 2 else None,
    )
    cursor = connection.execute(
        "INSERT INTO accounts(name, parent_id, depth, root_type, level_1, level_2, level_3) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        values,
    )
    return int(cast(int, cursor.lastrowid))


def populate_database(
    connection: sqlite3.Connection,
    transactions: Iterable[TransactionRecord],
    prices: Iterable[PriceRecord],
    precision: dict[str, int],
) -> None:
    """Insert normalized data into a newly initialized database."""
    transaction_list = list(transactions)
    price_list = list(prices)
    commodity_precision = dict(precision)
    for transaction in transaction_list:
        for posting in transaction.postings:
            _validate_tags(posting.tags, "posting")
            if posting.cost_amount_str is not None:
                Decimal(posting.cost_amount_str)
            if posting.commodity not in commodity_precision:
                commodity_precision[posting.commodity] = 0
            amount_places = _decimal_places(posting.amount)
            commodity_precision[posting.commodity] = max(
                commodity_precision[posting.commodity], amount_places
            )
            if posting.cost_commodity is not None and posting.cost_amount_str is not None:
                cost_places = _decimal_places(Decimal(posting.cost_amount_str))
                commodity_precision[posting.cost_commodity] = max(
                    commodity_precision.get(posting.cost_commodity, 0), cost_places
                )
    for price in price_list:
        try:
            Date.fromisoformat(price.date)
        except ValueError as exc:
            raise ValueError(f"invalid market price date: {price.date!r}") from exc
        price_value = Decimal(price.price_str)
        if price.base_commodity not in commodity_precision:
            commodity_precision[price.base_commodity] = 0
        if price.quote_commodity not in commodity_precision:
            commodity_precision[price.quote_commodity] = _decimal_places(price_value)
    commodity_ids = {
        symbol: _get_or_create_commodity(connection, symbol, places)
        for symbol, places in commodity_precision.items()
    }

    for transaction in transaction_list:
        _validate_tags(transaction.tags, "transaction")
        cursor = connection.execute(
            "INSERT INTO transactions(hledger_index, date, effective_date, status, code, payee, narration, comment, tags) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                transaction.hledger_index,
                transaction.date,
                transaction.effective_date,
                transaction.status,
                transaction.code,
                transaction.payee,
                transaction.narration,
                transaction.comment,
                transaction.tags,
            ),
        )
        transaction_id = int(cast(int, cursor.lastrowid))
        for posting in transaction.postings:
            amount_precision = commodity_precision.get(posting.commodity, 0)
            amount_int = int(posting.amount * (10**amount_precision))
            cost_commodity_id = None
            if posting.cost_commodity is not None:
                cost_precision = commodity_precision.get(posting.cost_commodity, 0)
                cost_commodity_id = _get_or_create_commodity(
                    connection, posting.cost_commodity, cost_precision
                )
            connection.execute(
                "INSERT INTO postings(transaction_id, account_id, amount_int, amount_str, commodity_id, "
                "cost_amount_str, cost_commodity_id, status, comment, tags) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    transaction_id,
                    _get_or_create_account(connection, posting.account),
                    amount_int,
                    posting.amount_str,
                    commodity_ids[posting.commodity],
                    posting.cost_amount_str,
                    cost_commodity_id,
                    posting.status,
                    posting.comment,
                    posting.tags,
                ),
            )

    for price in price_list:
        base_id = commodity_ids.get(price.base_commodity)
        if base_id is None:
            base_id = _get_or_create_commodity(connection, price.base_commodity, 0)
            commodity_ids[price.base_commodity] = base_id
        quote_id = commodity_ids.get(price.quote_commodity)
        if quote_id is None:
            quote_id = _get_or_create_commodity(connection, price.quote_commodity, 0)
            commodity_ids[price.quote_commodity] = quote_id
        connection.execute(
            "INSERT INTO market_prices(date, base_commodity_id, quote_commodity_id, price_str) "
            "VALUES (?, ?, ?, ?) ON CONFLICT(date, base_commodity_id, quote_commodity_id) "
            "DO UPDATE SET price_str = excluded.price_str",
            (price.date, base_id, quote_id, price.price_str),
        )

def build_database(
    output_path: Path,
    transactions: Iterable[TransactionRecord],
    prices: Iterable[PriceRecord],
    precision: dict[str, int],
) -> None:
    """Build a complete temporary database, then atomically replace the target."""
    output_path = output_path.expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{output_path.name}.", suffix=".tmp", dir=output_path.parent
    )
    os.close(fd)
    temporary_path = Path(temporary_name)
    try:
        connection = sqlite3.connect(temporary_path)
        try:
            connection.execute("PRAGMA foreign_keys = ON")
            initialize_schema(connection)
            with connection:
                populate_database(connection, transactions, prices, precision)
            connection.close()
        except BaseException:
            connection.close()
            raise
        os.replace(temporary_path, output_path)
    finally:
        temporary_path.unlink(missing_ok=True)