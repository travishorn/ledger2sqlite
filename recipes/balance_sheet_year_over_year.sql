/*
Balance Sheet — latest date vs. one year earlier

Returns current and prior-year asset/liability balances by account and
commodity, plus totals and unpriced-balance counts. The as-of date is the
latest transaction date in the ledger; the comparison date is the same month
and day in the prior year, clipped to that month's last day when necessary.

Set target_commodity to the reporting currency used by P price directives.
Only direct prices are used. Unpriced holdings remain visible and prevent
complete totals from being reported. Amounts use amount_real and are approximate.
*/
WITH RECURSIVE
params AS (
    SELECT
        COALESCE(MAX(date), date('now')) AS as_of_date,
        '$' AS target_commodity
    FROM transactions
),
snapshot_dates AS (
    SELECT 'as_of' AS snapshot, as_of_date AS cutoff_date FROM params
    UNION ALL
    SELECT 'prior_year', date(
        strftime('%Y', as_of_date, '-1 year') || '-' || strftime('%m', as_of_date) || '-01',
        '+' || (MIN(
            CAST(strftime('%d', as_of_date) AS INTEGER),
            CAST(strftime('%d', date(
                strftime('%Y', as_of_date, '-1 year') || '-' || strftime('%m', as_of_date) || '-01',
                '+1 month', '-1 day'
            )) AS INTEGER)
        ) - 1) || ' days'
    )
    FROM params
),
account_balances AS (
    SELECT
        sd.snapshot,
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
      AND a.depth > 0
    GROUP BY sd.snapshot, sd.cutoff_date, a.id, a.name, a.root_type,
             p.commodity_id, c.symbol
    HAVING ABS(SUM(p.amount_real)) > 0.000000001
),
valued_balances AS (
    SELECT
        b.*,
        CASE
            WHEN b.native_commodity = params.target_commodity THEN b.native_balance
            WHEN price.price_real IS NOT NULL THEN b.native_balance * price.price_real
            ELSE NULL
        END AS market_value
    FROM account_balances b
    CROSS JOIN params
    LEFT JOIN commodities target ON target.symbol = params.target_commodity
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
snapshot_totals AS (
    SELECT
        sd.snapshot,
        SUM(CASE WHEN b.root_type = 'asset' AND b.market_value IS NOT NULL
                 THEN b.market_value ELSE 0 END) AS assets_partial,
        SUM(CASE WHEN b.root_type = 'liability' AND b.market_value IS NOT NULL
                 THEN b.market_value ELSE 0 END) AS liabilities_signed_partial,
        SUM(CASE WHEN b.root_type = 'asset' AND b.market_value IS NULL THEN 1 ELSE 0 END)
            AS unpriced_asset_balances,
        SUM(CASE WHEN b.root_type = 'liability' AND b.market_value IS NULL THEN 1 ELSE 0 END)
            AS unpriced_liability_balances
    FROM snapshot_dates sd
    LEFT JOIN valued_balances b ON b.snapshot = sd.snapshot
    GROUP BY sd.snapshot
)
SELECT
    sd.snapshot,
    sd.cutoff_date,
    b.root_type,
    b.account_name,
    b.native_commodity,
    b.native_balance,
    b.market_value AS market_value_in_target_commodity,
    CASE WHEN COALESCE(t.unpriced_asset_balances, 0) = 0
         THEN ROUND(COALESCE(t.assets_partial, 0), 2) END AS total_assets,
    CASE WHEN COALESCE(t.unpriced_liability_balances, 0) = 0
         THEN ROUND(-COALESCE(t.liabilities_signed_partial, 0), 2) END AS total_liabilities,
    CASE WHEN COALESCE(t.unpriced_asset_balances, 0) = 0
           AND COALESCE(t.unpriced_liability_balances, 0) = 0
         THEN ROUND(COALESCE(t.assets_partial, 0) + COALESCE(t.liabilities_signed_partial, 0), 2)
    END AS net_worth,
    COALESCE(t.unpriced_asset_balances, 0) AS unpriced_asset_balances,
    COALESCE(t.unpriced_liability_balances, 0) AS unpriced_liability_balances,
    p.target_commodity
FROM snapshot_dates sd
LEFT JOIN valued_balances b ON b.snapshot = sd.snapshot
LEFT JOIN snapshot_totals t ON t.snapshot = sd.snapshot
CROSS JOIN params p
ORDER BY sd.cutoff_date DESC, b.root_type, b.account_name, b.native_commodity;
