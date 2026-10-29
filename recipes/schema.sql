/*
Stores the chart of accounts organized as a hierarchical tree. Precomputes
account depth, standard accounting root classifications, and path segments to
enable fast group-by reporting without recursive CTE overhead.

Accounting sign convention: 'asset' and 'expense' normally hold positive (debit)
balances. 'liability', 'equity', and 'revenue' normally hold negative (credit)
balances.
*/
CREATE TABLE accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT, -- Unique surrogate account identifier
    name TEXT NOT NULL UNIQUE, -- Full colon-delimited account path (e.g. 'assets:bank:checking')
    parent_id INTEGER REFERENCES accounts(id) ON DELETE RESTRICT, -- Foreign key referencing parent account node (NULL for root)
    depth INTEGER NOT NULL, -- 0-indexed hierarchy depth (0 = top-level root, 1 = subaccount, etc.)
    root_type TEXT NOT NULL, -- Normalized accounting classification: 'asset', 'liability', 'equity', 'revenue', 'expense', or 'other'
    level_1 TEXT NOT NULL, -- Top-level category segment (e.g. 'assets')
    level_2 TEXT, -- Second-level category segment (e.g. 'checking', 'groceries')
    level_3 TEXT -- Third-level category segment if present
);


/*
Directory of all currencies, fiat tokens, equities, or inventory units used
across the journal (e.g., '$', 'EUR', 'AAPL', 'BTC').

Never directly SUM amounts across different commodity IDs without filtering or
converting them via market prices. Adding currencies together directly creates
unitless mathematical errors.

The 'precision' column dictates how many decimal places to scale amounts by when
converting between `amount_str` and `amount_int` (scale factor = 10^precision).
*/
CREATE TABLE commodities (
    id INTEGER PRIMARY KEY AUTOINCREMENT, -- Unique surrogate commodity identifier
    symbol TEXT NOT NULL UNIQUE, -- Currency or commodity ticker symbol (e.g. '$', 'EUR', 'ETH')
    precision INTEGER NOT NULL DEFAULT 2 -- Maximum observed decimal places; defines the scaled-integer multiplier (10^N)
);


/*
Stores historical exchange rates and unit valuations.

Point-in-time portfolio/net worth valuations must join against the latest price
ON OR BEFORE the target balance date, applied against CURRENT native holdings.

Do not sum historical transaction market values to calculate balance sheet net
worth; summing historical exchange rate legs creates ghost balances for traded
assets with capital gains.
*/
CREATE TABLE market_prices (
    id INTEGER PRIMARY KEY AUTOINCREMENT, -- Unique surrogate price entry identifier
    date TEXT NOT NULL, -- Effective date of the price directive in ISO-8601 format ('YYYY-MM-DD')
    base_commodity_id INTEGER NOT NULL REFERENCES commodities(id) ON DELETE RESTRICT, -- Commodity being priced (e.g. BTC, EUR)
    quote_commodity_id INTEGER NOT NULL REFERENCES commodities(id) ON DELETE RESTRICT, -- Currency in which price is denominated (e.g. USD, $)
    price_str TEXT NOT NULL, -- Exact decimal string representation to prevent floating-point drift
    price_real REAL GENERATED ALWAYS AS (CAST(price_str AS REAL)) VIRTUAL, -- Pre-cast virtual float for analytical computations
    UNIQUE(date, base_commodity_id, quote_commodity_id)
);


/*
Represents double-entry transaction headers (envelopes) containing shared
metadata, dates, counterparties, and header-level tags.

Multi-currency transactions (e.g. forex trades or stock purchases) do not sum to
zero within a single commodity symbol; they balance across costs/exchange rates.
*/
CREATE TABLE transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT, -- Unique surrogate transaction identifier
    hledger_index INTEGER NOT NULL UNIQUE, -- Original 1-indexed transaction sequence number from hledger AST
    date TEXT NOT NULL, -- Primary transaction entry date ('YYYY-MM-DD')
    effective_date TEXT, -- Secondary/clearing date if specified ('YYYY-MM-DD')
    status TEXT NOT NULL, -- Reconciliation flag: 'cleared' (*), 'pending' (!), or 'unmarked'
    code TEXT, -- Check number, invoice code, or external transfer reference
    payee TEXT, -- Extracted transaction counterparty or payee name
    narration TEXT, -- Extracted note, memo, or secondary description
    tags TEXT CHECK (tags IS NULL OR (json_valid(tags) AND json_type(tags) = 'object')) -- JSON key-value dictionary of transaction-level metadata
);


/*
Contains the atomic debit and credit legs of each transaction, linking accounts,
exact numeric quantities, commodities, and optional cost basis.

For any single-currency transaction, the sum of all its postings' `amount_int`
values will strictly equal 0.

Use `amount_int` for exact balancing and auditing. Use `amount_real` only for
approximate analytical aggregations and dashboard charts.

Deleting a transaction cascades and drops all corresponding postings
automatically.
*/
CREATE TABLE postings (
    id INTEGER PRIMARY KEY AUTOINCREMENT, -- Unique surrogate posting identifier
    transaction_id INTEGER NOT NULL REFERENCES transactions(id) ON DELETE CASCADE, -- Foreign key linking posting to its parent transaction
    account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE RESTRICT, -- Foreign key linking posting to its debited/credited account
    amount_int INTEGER NOT NULL, -- Scaled integer representation (amount * 10^precision) for zero-loss arithmetic
    amount_str TEXT NOT NULL, -- Exact decimal string representation preserving original journal precision
    amount_real REAL GENERATED ALWAYS AS (CAST(amount_str AS REAL)) VIRTUAL, -- Pre-cast virtual float for ad-hoc SQL aggregation
    commodity_id INTEGER NOT NULL REFERENCES commodities(id) ON DELETE RESTRICT, -- Foreign key referencing the native commodity/currency
    cost_amount_str TEXT, -- Explicit unit or total transaction cost string if conversion occurred
    cost_commodity_id INTEGER REFERENCES commodities(id) ON DELETE RESTRICT, -- Foreign key referencing commodity used for cost basis
    status TEXT NOT NULL, -- Posting-level status override ('cleared', 'pending', or 'unmarked')
    tags TEXT CHECK (tags IS NULL OR (json_valid(tags) AND json_type(tags) = 'object')) -- JSON key-value dictionary of posting-level metadata
);


/*
Performance indexes optimized for common reporting, balance sheets, and joins
*/
CREATE INDEX idx_tx_date ON transactions(date);
CREATE INDEX idx_accounts_root ON accounts(root_type, depth);
CREATE INDEX idx_postings_account ON postings(account_id);
CREATE INDEX idx_postings_tx ON postings(transaction_id);
