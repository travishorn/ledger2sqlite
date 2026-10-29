WITH params AS (
    SELECT strftime('%Y-%m', 'now') AS anchor_month
),
-- Generate 6 month-end cutoff dates
snapshot_offsets(offset_str) AS (
    SELECT '-5 months' UNION ALL
    SELECT '-4 months' UNION ALL
    SELECT '-3 months' UNION ALL
    SELECT '-2 months' UNION ALL
    SELECT '-1 month'  UNION ALL
    SELECT '+0 months'
),
snapshot_dates AS (
    SELECT 
        strftime('%Y-%m', p.anchor_month || '-01', so.offset_str) AS month,
        date(p.anchor_month || '-01', so.offset_str, '+1 month', '-1 day') AS cutoff_date
    FROM params p
    CROSS JOIN snapshot_offsets so
),
-- Calculate native holdings as of each month-end
monthly_holdings_valued AS (
    SELECT 
        sd.month,
        a.root_type,
        SUM(p.amount_real) AS native_qty,
        CASE 
            WHEN c.symbol = '$' THEN 1.0
            ELSE COALESCE(
                (
                    SELECT mp.price_real
                    FROM market_prices mp
                    WHERE mp.base_commodity_id = p.commodity_id
                      AND mp.date <= sd.cutoff_date
                    ORDER BY mp.date DESC
                    LIMIT 1
                ),
                1.0
            )
        END AS unit_price
    FROM snapshot_dates sd
    JOIN transactions t ON t.date <= sd.cutoff_date
    JOIN postings p     ON p.transaction_id = t.id
    JOIN accounts a     ON p.account_id = a.id
    JOIN commodities c  ON p.commodity_id = c.id
    WHERE a.root_type IN ('asset', 'liability')
    GROUP BY sd.month, a.root_type, a.id, p.commodity_id
    HAVING native_qty != 0
),
-- Aggregate into Assets, Liabilities, and Net Worth per month
monthly_summary AS (
    SELECT 
        month,
        ROUND(SUM(CASE WHEN root_type = 'asset' THEN native_qty * unit_price ELSE 0 END), 2) AS total_assets,
        -- Liabilities stored as negative credits; converted to positive debt value
        ROUND(ABS(SUM(CASE WHEN root_type = 'liability' THEN native_qty * unit_price ELSE 0 END)), 2) AS total_liabilities,
        ROUND(
            SUM(CASE WHEN root_type = 'asset' THEN native_qty * unit_price ELSE 0 END) +
            SUM(CASE WHEN root_type = 'liability' THEN native_qty * unit_price ELSE 0 END),
            2
        ) AS net_worth
    FROM monthly_holdings_valued
    GROUP BY month
)
SELECT 
    month,
    total_assets,
    total_liabilities,
    net_worth,
    -- Dollar change in Net Worth compared to the preceding month
    ROUND(net_worth - LAG(net_worth) OVER (ORDER BY month), 2) AS net_worth_growth
FROM monthly_summary
ORDER BY month DESC;
