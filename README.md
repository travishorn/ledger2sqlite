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
defaults to `./journal.db`.

The output database includes native commodity postings, exact decimal strings
and scaled integers, account hierarchy, historical prices, and the `v_register`,
`v_account_balances`, and `v_postings_valued` views.

Use `-v` for progress messages. Install `hledger` separately and make sure it is
available on `PATH`.

## MCP server

As a bonus feature, this repository also implements an MCP server. It provides
`query_ledger` for read-only SQL queries and `get_ledger_context` for annotated
schema guidance and the saved SQL recipes.

By default it opens `journal.db` in the current working directory; set
`LEDGER2SQLITE_DATABASE` to use a different database path.

The server requires the MCP SDK, which you can install from the project
dependencies by running `uv sync`.

## Tests

Run the tests with `uv run python -m unittest discover -s tests`.

## License

The MIT License

Copyright 2026 Travis Horn

Permission is hereby granted, free of charge, to any person obtaining a copy of
this software and associated documentation files (the “Software”), to deal in
the Software without restriction, including without limitation the rights to
use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of
the Software, and to permit persons to whom the Software is furnished to do so,
subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED “AS IS”, WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS
FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR
COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER
IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN
CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
