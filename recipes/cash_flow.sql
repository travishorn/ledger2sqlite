/*
Month-over-Month Cash Flow & Savings Rate

Did you make more than you spent this month, and how does your savings rate
compare to previous months?

Look for a positive `net_savings`. Comparing it directly against the preceding
months immediately highlights lifestyle inflation or windfalls.
*/
WITH params AS (
    SELECT strftime('%Y-%m', 'now') AS anchor_month
),
monthly_totals AS (
    SELECT
        strftime('%Y-%m', v.date) AS month,
        ROUND(SUM(CASE WHEN a.root_type = 'revenue' THEN -v.market_value ELSE 0 END), 2) AS income,
        ROUND(SUM(CASE WHEN a.root_type = 'expense' THEN v.market_value ELSE 0 END), 2) AS expenses
    FROM v_postings_valued v
    JOIN accounts a ON v.account = a.name
    CROSS JOIN params p
    WHERE v.date >= date(p.anchor_month || '-01', '-11 months')
      AND v.date <  date(p.anchor_month || '-01', '+1 month')
      AND a.root_type IN ('revenue', 'expense')
    GROUP BY strftime('%Y-%m', v.date)
)
SELECT
    month,
    income,
    expenses,
    ROUND(income - expenses, 2) AS net_savings,
    ROUND(((income - expenses) / NULLIF(income, 0)) * 100.0, 1) || '%' AS savings_rate,
    -- Month-over-Month change in net savings compared to the prior month
    ROUND(
        (income - expenses) - LAG(income - expenses) OVER (ORDER BY month),
        2
    ) AS mom_savings_delta
FROM monthly_totals
ORDER BY month DESC;
