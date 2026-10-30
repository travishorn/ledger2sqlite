/*
Monthly Balance Sheet — six completed month-ends

Returns account-level asset/liability balances and month-level totals for the
six completed calendar months before the current month. Balances are cumulative
through each month-end, not sums of the month's activity.

Set target_commodity to the reporting currency used by the journal's P price
directives (for example '$' or 'USD'). Direct prices are used; there is no
cross-rate conversion. Unpriced holdings remain visible and make the affected
totals NULL instead of silently assuming parity. Amounts use amount_real and
are therefore approximate.
*/
WITH RECURSIVE
params AS (
    SELECT
        '$' AS target_commodity,
        date('now', 'start of month', '-6 months') AS first_month
),
months(month_start, month_number) AS (
    SELECT first_month, 0 FROM params
    UNION ALL
    SELECT date(month_start, '+1 month'), month_number + 1
    FROM months
    WHERE month_number < 5
),
snapshot_dates AS (
    SELECT
        strftime('%Y-%m', month_start) AS month,
        date(month_start, '+1 month', '-1 day') AS cutoff_date
    FROM months
),
account_balances AS (
    SELECT
        sd.month,
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
    GROUP BY sd.month, sd.cutoff_date, a.id, a.name, a.root_type, p.commodity_id, c.symbol
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
monthly_totals AS (
    SELECT
        month,
        SUM(CASE WHEN root_type = 'asset' AND market_value IS NOT NULL THEN market_value ELSE 0 END) AS assets_partial,
        SUM(CASE WHEN root_type = 'liability' AND market_value IS NOT NULL THEN market_value ELSE 0 END) AS liabilities_signed_partial,
        SUM(CASE WHEN root_type = 'asset' AND market_value IS NULL THEN 1 ELSE 0 END) AS unpriced_asset_balances,
        SUM(CASE WHEN root_type = 'liability' AND market_value IS NULL THEN 1 ELSE 0 END) AS unpriced_liability_balances
    FROM valued_balances
    GROUP BY month
)
SELECT
    sd.month,
    sd.cutoff_date,
    b.root_type,
    b.account_name,
    b.native_commodity,
    b.native_balance,
    b.market_value AS market_value_in_target_commodity,
    CASE WHEN COALESCE(mt.unpriced_asset_balances, 0) = 0
         THEN ROUND(COALESCE(mt.assets_partial, 0), 2) END AS total_assets,
    CASE WHEN COALESCE(mt.unpriced_liability_balances, 0) = 0
         THEN ROUND(-COALESCE(mt.liabilities_signed_partial, 0), 2) END AS total_liabilities,
    CASE WHEN COALESCE(mt.unpriced_asset_balances, 0) = 0
               AND COALESCE(mt.unpriced_liability_balances, 0) = 0
         THEN ROUND(COALESCE(mt.assets_partial, 0) + COALESCE(mt.liabilities_signed_partial, 0), 2)
    END AS net_worth,
    COALESCE(mt.unpriced_asset_balances, 0) AS unpriced_asset_balances,
    COALESCE(mt.unpriced_liability_balances, 0) AS unpriced_liability_balances,
    (SELECT target_commodity FROM params) AS target_commodity
FROM snapshot_dates sd
LEFT JOIN monthly_totals mt ON mt.month = sd.month
LEFT JOIN valued_balances b ON b.month = sd.month
ORDER BY sd.month DESC, b.root_type, b.account_name, b.native_commodity;
