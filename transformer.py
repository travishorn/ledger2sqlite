"""Convert hledger output into normalized, exact database records."""

from __future__ import annotations

import json
import re
import shlex
from dataclasses import dataclass
from datetime import date as Date
from decimal import Decimal
from typing import Any


@dataclass(frozen=True)
class PostingRecord:
    account: str
    amount: Decimal
    amount_str: str
    commodity: str
    cost_amount_str: str | None
    cost_commodity: str | None
    status: str
    tags: str | None


@dataclass(frozen=True)
class TransactionRecord:
    hledger_index: int
    date: str
    effective_date: str | None
    status: str
    code: str | None
    payee: str | None
    narration: str | None
    tags: str | None
    postings: list[PostingRecord]


@dataclass(frozen=True)
class PriceRecord:
    date: str
    base_commodity: str
    quote_commodity: str
    price_str: str


def _tag_json(raw: Any) -> str | None:
    if not raw:
        return None
    if isinstance(raw, dict):
        tags = {str(key): str(value) for key, value in raw.items()}
    else:
        tags = {}
        for item in raw:
            if isinstance(item, (list, tuple)) and len(item) >= 2:
                tags[str(item[0])] = str(item[1])
    return json.dumps(tags, ensure_ascii=False, sort_keys=True) if tags else None


def _amount_string(quantity: dict[str, Any]) -> str:
    places = int(quantity.get("decimalPlaces") or 0)
    mantissa = quantity.get("decimalMantissa")
    if mantissa is not None:
        value = Decimal(int(mantissa)).scaleb(-places)
        return f"{value:.{places}f}"
    floating = quantity.get("floatingPoint")
    if floating is None:
        raise ValueError("hledger amount has no decimal quantity")
    return f"{Decimal(str(floating)):.{places}f}"


def _decimal_places(value: Decimal) -> int:
    exponent = value.as_tuple().exponent
    return max(0, -exponent) if isinstance(exponent, int) else 0


def _posting_records(raw_posting: dict[str, Any]) -> list[PostingRecord]:
    result: list[PostingRecord] = []
    for amount in raw_posting.get("pamount") or []:
        commodity = str(amount["acommodity"])
        quantity = amount.get("aquantity") or {}
        amount_str = _amount_string(quantity)
        cost = amount.get("acost")
        cost_contents = cost.get("contents") if isinstance(cost, dict) else None
        cost_amount_str = None
        cost_commodity = None
        if isinstance(cost_contents, dict):
            cost_amount_str = _amount_string(cost_contents.get("aquantity") or {})
            cost_commodity = str(cost_contents["acommodity"])
        result.append(
            PostingRecord(
                account=str(raw_posting["paccount"]),
                amount=Decimal(amount_str),
                amount_str=amount_str,
                commodity=commodity,
                cost_amount_str=cost_amount_str,
                cost_commodity=cost_commodity,
                status=str(raw_posting.get("pstatus") or "Unmarked").lower(),
                tags=_tag_json(raw_posting.get("ptags")),
            )
        )
    return result


def transform_transactions(raw_transactions: list[dict[str, Any]]) -> tuple[list[TransactionRecord], dict[str, int]]:
    """Map raw JSON and compute each commodity's greatest observed scale."""
    transactions: list[TransactionRecord] = []
    precision: dict[str, int] = {}
    for raw in raw_transactions:
        postings: list[PostingRecord] = []
        for raw_posting in raw.get("tpostings") or []:
            converted = _posting_records(raw_posting)
            postings.extend(converted)
            for posting in converted:
                places = _decimal_places(posting.amount)
                precision[posting.commodity] = max(precision.get(posting.commodity, 0), places)
                if posting.cost_commodity is not None and posting.cost_amount_str is not None:
                    cost_places = _decimal_places(Decimal(posting.cost_amount_str))
                    precision[posting.cost_commodity] = max(precision.get(posting.cost_commodity, 0), cost_places)
        description = str(raw.get("tdescription") or "").strip()
        if "|" in description:
            payee_part, narration_part = description.split("|", 1)
            payee = payee_part.strip() or None
            narration = narration_part.strip() or None
        else:
            payee, narration = description or None, None
        transactions.append(
            TransactionRecord(
                hledger_index=int(raw["tindex"]),
                date=str(raw["tdate"]),
                effective_date=str(raw["tdate2"]) if raw.get("tdate2") else None,
                status=str(raw.get("tstatus") or "Unmarked").lower(),
                code=str(raw.get("tcode") or "") or None,
                payee=payee,
                narration=narration,
                tags=_tag_json(raw.get("ttags")),
                postings=postings,
            )
        )
    return transactions, precision


_PRICE_TOKEN = re.compile(r"^(.+?)([-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?)$")


def parse_prices(output: str) -> list[PriceRecord]:
    """Parse hledger's P directives, supporting both commodity price forms."""
    prices: list[PriceRecord] = []
    for line_number, line in enumerate(output.splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith(";"):
            continue
        try:
            tokens = shlex.split(stripped)
        except ValueError as exc:
            raise ValueError(f"Invalid hledger price directive on line {line_number}: {exc}") from exc
        if not tokens or tokens[0] != "P":
            continue
        if len(tokens) < 4:
            raise ValueError(f"Incomplete hledger price directive on line {line_number}: {stripped}")
        base = tokens[2]
        try:
            Date.fromisoformat(tokens[1])
        except ValueError as exc:
            raise ValueError(f"Invalid hledger price date on line {line_number}: {tokens[1]!r}") from exc
        price_date = tokens[1]
        amount_token = tokens[3]
        starts_as_number = amount_token[:1] in {"+", "-", "."} or amount_token[:1].isdigit()
        match = None if starts_as_number else _PRICE_TOKEN.match(amount_token)
        if match and match.group(1):
            quote, value = match.groups()
        elif len(tokens) >= 5:
            value, quote = tokens[3], tokens[4]
        else:
            value, quote = amount_token, ""
        value = value.strip()
        if not quote:
            raise ValueError(f"Price directive lacks a quote commodity on line {line_number}: {stripped}")
        try:
            normalized_value = str(Decimal(value))
        except ArithmeticError as exc:
            raise ValueError(f"Invalid price on line {line_number}: {value!r}") from exc
        prices.append(PriceRecord(price_date, base, quote, normalized_value))
    return prices