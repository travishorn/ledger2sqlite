/*
Emergency Runway

If all income stops today, how many months can you survive on your liquid cash?

Most personal finance frameworks target a buffer between 3 and 6 months.
*/
WITH trailing_expenses AS (
    -- Average monthly expense over the last 6 completed months
    SELECT
        SUM(v.market_value) / 6.0 AS avg_monthly_burn
    FROM v_postings_valued v
    JOIN accounts a ON v.account = a.name
    WHERE a.root_type = 'expense'
      AND v.date >= date('now', 'start of month', '-6 months')
      AND v.date <  date('now', 'start of month')
),
liquid_cash AS (
    -- Sum of Checking, Savings, and Cash buckets
    SELECT
        SUM(v.market_value) AS total_liquid
    FROM v_postings_valued v
    JOIN accounts a ON v.account = a.name
    WHERE a.root_type = 'asset'
      AND a.level_2 IN ('Checking', 'Savings', 'Cash', 'Venmo')
)
SELECT
    ROUND(lc.total_liquid, 2) AS liquid_cash_usd,
    ROUND(te.avg_monthly_burn, 2) AS avg_monthly_burn_usd,
    ROUND(lc.total_liquid / NULLIF(te.avg_monthly_burn, 0), 1) AS runway_months
FROM liquid_cash lc
CROSS JOIN trailing_expenses te;
