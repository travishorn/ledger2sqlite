/*
Year-end Balance Sheet — five completed calendar years

Returns account-level asset/liability balances and year-level totals for the
five most recently completed year-ends. Balances are cumulative through each
December 31. The anchor is SQLite 'now'; replace params.first_year with an
explicit year if reproducibility or a different reporting horizon is desired.

Set target_commodity to the reporting currency used by the journal's P price
directives (for example '$' or 'USD'). Direct prices are used; there is no
cross-rate conversion. Unpriced holdings remain visible and make affected
totals NULL rather than assuming parity. Amounts use amount_real and are
approximate.
*/
WITH RECURSIVE
params AS (
    SELECT
        '$' AS target_commodity,
        CAST(strftime('%Y', 'now') AS INTEGER) - 5 AS first_year
),
years(year_number) AS (
    SELECT first_year FROM params
    UNION ALL
    SELECT year_number + 1 FROM years
    WHERE year_number < CAST(strftime('%Y', 'now') AS INTEGER) - 1
),
snapshot_dates AS (
    SELECT
        CAST(year_number AS TEXT) AS year,
        date(year_number || '-12-31') AS cutoff_date
    FROM years
),
account_balances AS (
    SELECT
        sd.year,
        sd.cutoff_date,
        a.id AS account_id,
        a.name AS account_name,
        a.root_type,
        p.commodity_id,
        c.symbol AS native_commodity,
        SUM(p.amount_real) AS native_balance
    FROM snapshot_dates sd
    JOIN transactions t ON t.date <= sd.cutoff_date
    JOIN postings p ON p.transaction_id = t.id
    JOIN accounts a ON a.id = p.account_id
    JOIN commodities c ON c.id = p.commodity_id
    WHERE a.root_type IN ('asset', 'liability')
    GROUP BY sd.year, sd.cutoff_date, a.id, a.name, a.root_type, p.commodity_id, c.symbol
    HAVING ABS(SUM(p.amount_real)) > 0.000000001
),
valued_balances AS (
    SELECT
        b.*,
        CASE
            WHEN b.native_commodity = (SELECT target_commodity FROM params)
                THEN b.native_balance
            WHEN price.price_real IS NOT NULL
                THEN b.native_balance * price.price_real
            ELSE NULL
        END AS market_value
    FROM account_balances b
    LEFT JOIN commodities target
        ON target.symbol = (SELECT target_commodity FROM params)
    LEFT JOIN market_prices price
        ON price.base_commodity_id = b.commodity_id
       AND price.quote_commodity_id = target.id
       AND price.date = (
            SELECT MAX(candidate.date)
            FROM market_prices candidate
            WHERE candidate.base_commodity_id = b.commodity_id
              AND candidate.quote_commodity_id = target.id
              AND candidate.date <= b.cutoff_date
       )
),
yearly_totals AS (
    SELECT
        year,
        SUM(CASE WHEN root_type = 'asset' AND market_value IS NOT NULL THEN market_value ELSE 0 END) AS assets_partial,
        SUM(CASE WHEN root_type = 'liability' AND market_value IS NOT NULL THEN market_value ELSE 0 END) AS liabilities_signed_partial,
        SUM(CASE WHEN root_type = 'asset' AND market_value IS NULL THEN 1 ELSE 0 END) AS unpriced_asset_balances,
        SUM(CASE WHEN root_type = 'liability' AND market_value IS NULL THEN 1 ELSE 0 END) AS unpriced_liability_balances
    FROM valued_balances
    GROUP BY year
)
SELECT
    sd.year,
    sd.cutoff_date,
    b.root_type,
    b.account_name,
    b.native_commodity,
    b.native_balance,
    b.market_value AS market_value_in_target_commodity,
    CASE WHEN COALESCE(yt.unpriced_asset_balances, 0) = 0
         THEN ROUND(COALESCE(yt.assets_partial, 0), 2) END AS total_assets,
    CASE WHEN COALESCE(yt.unpriced_liability_balances, 0) = 0
         THEN ROUND(-COALESCE(yt.liabilities_signed_partial, 0), 2) END AS total_liabilities,
    CASE WHEN COALESCE(yt.unpriced_asset_balances, 0) = 0
               AND COALESCE(yt.unpriced_liability_balances, 0) = 0
         THEN ROUND(COALESCE(yt.assets_partial, 0) + COALESCE(yt.liabilities_signed_partial, 0), 2)
    END AS net_worth,
    COALESCE(yt.unpriced_asset_balances, 0) AS unpriced_asset_balances,
    COALESCE(yt.unpriced_liability_balances, 0) AS unpriced_liability_balances,
    (SELECT target_commodity FROM params) AS target_commodity
FROM snapshot_dates sd
LEFT JOIN yearly_totals yt ON yt.year = sd.year
LEFT JOIN valued_balances b ON b.year = sd.year
ORDER BY sd.year DESC, b.root_type, b.account_name, b.native_commodity;
