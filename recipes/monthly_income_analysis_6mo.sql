/*
Monthly Inflow / Income Analysis — six completed months

Shows income by account stream (full account path, so nested income accounts
remain distinct) and commodity, with one row for every stream/month combination
and a six-month average that includes zero-activity months. Revenue postings
are normally negative credits, so income is reported as their negated sum.

This report uses transaction dates and native commodity amounts. It does not
convert currencies; review/group by commodity, or add an explicit target-currency
price policy if a consolidated baseline is needed. amount_real is approximate.
*/
WITH RECURSIVE
params AS (
    SELECT date('now', 'start of month', '-6 months') AS first_month
),
months(month_start, month_number) AS (
    SELECT first_month, 0 FROM params
    UNION ALL
    SELECT date(month_start, '+1 month'), month_number + 1
    FROM months
    WHERE month_number < 5
),
income_activity AS (
    SELECT
        strftime('%Y-%m', t.date) AS month,
        a.name AS income_stream,
        c.symbol AS commodity,
        -SUM(p.amount_real) AS income
    FROM transactions t
    JOIN postings p ON p.transaction_id = t.id
    JOIN accounts a ON a.id = p.account_id
    JOIN commodities c ON c.id = p.commodity_id
    CROSS JOIN params
    WHERE a.root_type = 'revenue'
      AND t.date >= params.first_month
      AND t.date < date(params.first_month, '+6 months')
    GROUP BY strftime('%Y-%m', t.date), a.name, c.symbol
),
streams AS (
    SELECT DISTINCT income_stream, commodity FROM income_activity
),
periods AS (
    SELECT strftime('%Y-%m', month_start) AS month FROM months
)
SELECT
    periods.month,
    streams.income_stream,
    streams.commodity,
    ROUND(COALESCE(activity.income, 0), 2) AS income,
    ROUND(AVG(COALESCE(activity.income, 0)) OVER (
        PARTITION BY streams.income_stream, streams.commodity
    ), 2) AS six_month_average_monthly_income
FROM periods
CROSS JOIN streams
LEFT JOIN income_activity activity
    ON activity.month = periods.month
   AND activity.income_stream = streams.income_stream
   AND activity.commodity = streams.commodity
ORDER BY periods.month DESC, streams.income_stream, streams.commodity;
