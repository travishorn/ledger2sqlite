"""Command-line interface for converting hledger journals to SQLite."""

from __future__ import annotations

import argparse
import logging
import os
import sqlite3
import sys
from pathlib import Path

from db import build_database
from extractor import HledgerError, extract_prices, extract_transactions
from transformer import parse_prices, transform_transactions


LOGGER = logging.getLogger("ledger2sqlite")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ledger2sqlite",
        description="Convert an hledger journal into a normalized SQLite database.",
    )
    parser.add_argument(
        "--journal",
        "-f",
        type=Path,
        default=Path(os.environ.get("LEDGER_FILE", "~/.hledger.journal")).expanduser(),
        help="hledger journal (default: $LEDGER_FILE or ~/.hledger.journal)",
    )
    parser.add_argument(
        "--output", "-o", type=Path, default=Path("journal.db"), help="SQLite output path (default: ./journal.db)"
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="show detailed progress")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s: %(message)s",
    )
    journal = args.journal.expanduser().resolve()
    if not journal.is_file():
        parser.error(f"journal file does not exist: {journal}")
    try:
        LOGGER.info("Extracting transactions from %s", journal)
        raw_transactions = extract_transactions(journal)
        transactions, precision = transform_transactions(raw_transactions)
        prices = parse_prices(extract_prices(journal))
        LOGGER.info(
            "Extracted %d transactions, %d postings, and %d market prices",
            len(transactions),
            sum(len(transaction.postings) for transaction in transactions),
            len(prices),
        )
        build_database(args.output, transactions, prices, precision)
    except (HledgerError, ValueError, ArithmeticError, OSError, sqlite3.Error) as exc:
        print(f"ledger2sqlite: error: {exc}", file=sys.stderr)
        return 1
    LOGGER.info("Database written atomically to %s", args.output.expanduser().resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())