/*
Category Spending Drift

Where did your spending change the most compared to previous months?

Categories at the top of the list have the largest spending on average.
*/
WITH params AS (
    -- Set your anchor month (Format: 'YYYY-MM')
    SELECT strftime('%Y-%m', 'now') AS anchor_month
),
category_spend AS (
    SELECT
        COALESCE(a.level_2, 'Uncategorized') AS category,
        SUM(CASE WHEN strftime('%Y-%m', v.date) = strftime('%Y-%m', p.anchor_month || '-01', '-5 months') THEN v.market_value ELSE 0 END) AS m5,
        SUM(CASE WHEN strftime('%Y-%m', v.date) = strftime('%Y-%m', p.anchor_month || '-01', '-4 months') THEN v.market_value ELSE 0 END) AS m4,
        SUM(CASE WHEN strftime('%Y-%m', v.date) = strftime('%Y-%m', p.anchor_month || '-01', '-3 months') THEN v.market_value ELSE 0 END) AS m3,
        SUM(CASE WHEN strftime('%Y-%m', v.date) = strftime('%Y-%m', p.anchor_month || '-01', '-2 months') THEN v.market_value ELSE 0 END) AS m2,
        SUM(CASE WHEN strftime('%Y-%m', v.date) = strftime('%Y-%m', p.anchor_month || '-01', '-1 month')  THEN v.market_value ELSE 0 END) AS m1,
        SUM(CASE WHEN strftime('%Y-%m', v.date) = p.anchor_month THEN v.market_value ELSE 0 END) AS m0
    FROM v_postings_valued v
    JOIN accounts a ON v.account = a.name
    CROSS JOIN params p
    WHERE a.root_type = 'expense'
      AND v.date >= date(p.anchor_month || '-01', '-5 months')
      AND v.date <  date(p.anchor_month || '-01', '+1 month')
    GROUP BY a.level_2
)
SELECT
    category,
    ROUND(m5, 2) AS prev_m5,
    ROUND(m4, 2) AS prev_m4,
    ROUND(m3, 2) AS prev_m3,
    ROUND(m2, 2) AS prev_m2,
    ROUND(m1, 2) AS prev_m1,
    ROUND(m0, 2) AS this_month,
    ROUND((m5 + m4 + m3 + m2 + m1 + m0) / 6.0, 2) AS avg_6mo
FROM category_spend
WHERE (m5 + m4 + m3 + m2 + m1 + m0) > 0
ORDER BY avg_6mo DESC;
