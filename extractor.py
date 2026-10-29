"""Run hledger and decode its machine-readable output."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any


class HledgerError(RuntimeError):
    """Raised when hledger cannot be run or reports an error."""


def _run_hledger(journal: Path, *arguments: str) -> str:
    executable = shutil.which("hledger")
    if executable is None:
        raise HledgerError("hledger was not found; install it and ensure it is on PATH.")
    try:
        result = subprocess.run(
            [executable, "-f", str(journal), *arguments],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except OSError as exc:
        raise HledgerError(f"Could not start hledger: {exc}") from exc
    if result.returncode:
        detail = result.stderr.strip() or result.stdout.strip() or "unknown error"
        raise HledgerError(f"hledger {' '.join(arguments)} failed: {detail}")
    return result.stdout


def extract_transactions(journal: Path) -> list[dict[str, Any]]:
    """Extract transactions and postings from hledger's JSON output."""
    output = _run_hledger(journal, "print", "-O", "json")
    try:
        data = json.loads(output)
    except json.JSONDecodeError as exc:
        raise HledgerError(f"hledger returned invalid transaction JSON: {exc}") from exc
    if not isinstance(data, list):
        raise HledgerError("hledger returned unexpected transaction JSON (expected a list).")
    return data


def extract_prices(journal: Path) -> str:
    """Return hledger's textual historical price directives."""
    return _run_hledger(journal, "prices")