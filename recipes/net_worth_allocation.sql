/*
Net Worth & Asset Allocation

What is your exact net worth today, and how is it distributed across asset
classes?

Check your liquid vs. illiquid asset ratios (Cash/Checking vs. Real
Estate/Investments) and ensure liabilities are trending downward over time.
*/
WITH params AS (
    SELECT date('now') AS as_of_date
),
-- Get the actual native quantity balance for every asset/liability account
account_balances AS (
    SELECT
        a.id AS account_id,
        a.root_type,
        COALESCE(a.level_2, 'Other') AS category,
        a.name AS account_name,
        p.commodity_id,
        c.symbol AS commodity,
        SUM(p.amount_real) AS native_qty
    FROM postings p
    JOIN transactions t ON p.transaction_id = t.id
    JOIN accounts a     ON p.account_id = a.id
    JOIN commodities c  ON p.commodity_id = c.id
    CROSS JOIN params pr
    WHERE t.date <= pr.as_of_date
      AND a.root_type IN ('asset', 'liability')
    GROUP BY a.id, p.commodity_id
    HAVING native_qty != 0
),
-- Value each native holding using the latest price as of the cutoff date
holdings_valued AS (
    SELECT
        ab.root_type,
        ab.category,
        ab.account_name,
        ab.native_qty,
        ab.commodity,
        -- If it's already USD ($), price is 1.0; otherwise find the latest
        -- price on or before cutoff date
        CASE
            WHEN ab.commodity = '$' THEN 1.0
            ELSE COALESCE(
                (
                    SELECT mp.price_real
                    FROM market_prices mp
                    CROSS JOIN params pr
                    WHERE mp.base_commodity_id = ab.commodity_id
                      AND mp.date <= pr.as_of_date
                    ORDER BY mp.date DESC
                    LIMIT 1
                ),
                1.0
            )
        END AS current_unit_price
    FROM account_balances ab
)
SELECT
    root_type,
    category,
    ROUND(SUM(native_qty * current_unit_price), 2) AS total_usd,
    ROUND(
        100.0 * SUM(native_qty * current_unit_price) /
        SUM(SUM(native_qty * current_unit_price)) OVER (PARTITION BY root_type),
        1
    ) AS pct_of_root
FROM holdings_valued
GROUP BY root_type, category
ORDER BY
    CASE root_type WHEN 'asset' THEN 1 WHEN 'liability' THEN 2 END,
    total_usd DESC;
