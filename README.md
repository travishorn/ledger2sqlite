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

## MCP server

The repository's `.mcp.json` configures a stdio MCP server launched with
`uv run mcp_ledger.py`. It provides `query_ledger` for read-only SQL queries and
`get_ledger_context` for annotated schema guidance and the saved SQL recipes.
The query tool returns JSON rows and limits results to 1,000 rows. By default it
opens `journal.db` in the current working directory; set
`LEDGER2SQLITE_DATABASE` to use a different database path.

The server requires the MCP SDK, installed from the project dependencies by
`uv sync`.

## Tests

Run the tests with `uv run python -m unittest discover -s tests`.
