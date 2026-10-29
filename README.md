# ledger2sqlite

`ledger2sqlite` converts an hledger journal into a normalized SQLite database.
It uses the hledger CLI for journal interpretation and only Python's standard
library at runtime.

## Usage

Set `LEDGER_FILE` or pass a journal explicitly, then run:

```text
uv run python main.py --journal path/to/journal.journal --output journal.db
```

The journal defaults to `$LEDGER_FILE` and then `~/.hledger.journal`; the output
defaults to `./journal.db`. Use `-v` for progress messages. Install `hledger`
separately and make sure it is available on `PATH`.

The database is built in a temporary file in the output directory and replaces
the existing database only after a successful commit. It includes native
commodity postings, exact decimal strings and scaled integers, account hierarchy,
historical prices, and the `v_register`, `v_account_balances`, and
`v_postings_valued` views.

## Tests

Run the standard-library test suite with `uv run python -m unittest discover -s tests`.
