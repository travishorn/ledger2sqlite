/*
Monthly Income & Expense Comparison — current month vs trailing 12-month average

Returns income and expenses by top-level account category/stream and native
commodity. The report date is the latest transaction date in the ledger (or
today when the ledger is empty). The current month is compared with the average
monthly activity over the 12 calendar months ending in that month, including
zero-activity months. Expense and revenue signs are normalized to positive
outflow/inflow. Filter or group by commodity; no currency conversion is done.
Amounts use amount_real and are approximate.
*/
WITH
params AS (
    SELECT COALESCE(MAX(date), date('now')) AS as_of_date
    FROM transactions
),
period AS (
    SELECT
        as_of_date,
        date(as_of_date, 'start of month') AS current_month_start,
        date(as_of_date, 'start of month', '-11 months') AS first_month_start
    FROM params
),
months(month_start, month_number) AS (
    SELECT first_month_start, 0 FROM period
    UNION ALL
    SELECT date(month_start, '+1 month'), month_number + 1
    FROM months
    WHERE month_number < 11
),
streams AS (
    SELECT DISTINCT
        CASE a.root_type WHEN 'expense' THEN 'expense' ELSE 'income' END AS measure,
        COALESCE(a.level_2, 'Uncategorized') AS category,
        c.symbol AS commodity
    FROM postings p
    JOIN accounts a ON a.id = p.account_id
    JOIN commodities c ON c.id = p.commodity_id
    JOIN transactions t ON t.id = p.transaction_id
    CROSS JOIN period
    WHERE a.root_type IN ('expense', 'revenue')
      AND a.depth > 0
      AND t.date >= period.first_month_start
      AND t.date < date(period.current_month_start, '+1 month')
),
activity AS (
    SELECT
        CASE a.root_type WHEN 'expense' THEN 'expense' ELSE 'income' END AS measure,
        COALESCE(a.level_2, 'Uncategorized') AS category,
        c.symbol AS commodity,
        strftime('%Y-%m', t.date) AS month,
        SUM(CASE a.root_type WHEN 'expense' THEN p.amount_real ELSE -p.amount_real END)
            AS amount
    FROM transactions t
    JOIN postings p ON p.transaction_id = t.id
    JOIN accounts a ON a.id = p.account_id
    JOIN commodities c ON c.id = p.commodity_id
    CROSS JOIN period
    WHERE a.root_type IN ('expense', 'revenue')
      AND a.depth > 0
      AND t.date >= period.first_month_start
      AND t.date < date(period.current_month_start, '+1 month')
    GROUP BY measure, category, c.symbol, strftime('%Y-%m', t.date)
),
category_months AS (
    SELECT
        streams.measure,
        streams.category,
        streams.commodity,
        strftime('%Y-%m', months.month_start) AS month,
        COALESCE(activity.amount, 0) AS amount
    FROM streams
    CROSS JOIN months
    LEFT JOIN activity
        ON activity.measure = streams.measure
       AND activity.category = streams.category
       AND activity.commodity = streams.commodity
       AND activity.month = strftime('%Y-%m', months.month_start)
),
category_totals AS (
    SELECT
        measure,
        category,
        commodity,
        SUM(CASE WHEN month = strftime('%Y-%m', (SELECT current_month_start FROM period))
                 THEN amount ELSE 0 END) AS current_month_amount,
        AVG(amount) AS average_monthly_amount
    FROM category_months
    GROUP BY measure, category, commodity
),
report_rows AS (
    SELECT measure, category, commodity, current_month_amount,
           average_monthly_amount, 0 AS is_total
    FROM category_totals
    UNION ALL
    SELECT measure, 'TOTAL', commodity, SUM(current_month_amount),
           SUM(average_monthly_amount), 1
    FROM category_totals
    GROUP BY measure, commodity
)
SELECT
    period.as_of_date,
    strftime('%Y-%m', period.current_month_start) AS report_month,
    report_rows.measure,
    report_rows.category,
    report_rows.commodity,
    ROUND(report_rows.current_month_amount, 2) AS current_month_amount,
    ROUND(report_rows.average_monthly_amount, 2) AS trailing_12_month_average,
    ROUND(report_rows.current_month_amount - report_rows.average_monthly_amount, 2) AS difference_from_average,
    12 AS average_month_count,
    report_rows.is_total
FROM report_rows
CROSS JOIN period
ORDER BY report_rows.measure, report_rows.is_total DESC, report_rows.category, report_rows.commodity;
