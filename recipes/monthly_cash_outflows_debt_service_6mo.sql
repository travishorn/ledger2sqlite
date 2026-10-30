/*
Monthly Cash Outflows & Debt Service — six completed months

Shows monthly living expenses plus installment-loan principal paid, and their
sum as a planning burn rate. Includes all six months (including zero-activity
months) in the average. This is a cash-flow report: expense postings are
positive debits; principal repayment postings are positive credits to the loan
liability (they reduce its usual negative balance).

IMPORTANT: classify principal repayments explicitly. Set principal_tag_key and
principal_tag_value to a posting tag used only on the repayment-side loan
postings, or leave principal_tag_key empty and maintain the loan account list
below. Do not include all liability postings: loan proceeds and adjustments
are not debt service. Edit installment_accounts to match exact account paths.

All totals are kept by commodity; no implicit exchange-rate conversion occurs.
If you need a single-currency burn rate, convert using a deliberate reporting
currency and price policy before summing.
*/
WITH RECURSIVE
params AS (
    SELECT
        date('now', 'start of month', '-6 months') AS first_month,
        '' AS principal_tag_key,
        'principal' AS principal_tag_value
),
installment_accounts(account_name) AS (
    SELECT 'Liabilities:Mortgages' UNION ALL
    SELECT 'Liabilities:Student Loans'
),
months(month_start, month_number) AS (
    SELECT first_month, 0 FROM params
    UNION ALL
    SELECT date(month_start, '+1 month'), month_number + 1
    FROM months
    WHERE month_number < 5
),
monthly_activity AS (
    SELECT
        strftime('%Y-%m', t.date) AS month,
        c.symbol AS commodity,
        SUM(CASE WHEN a.root_type = 'expense' THEN p.amount_real ELSE 0 END) AS living_expenses,
        SUM(CASE
            WHEN a.root_type = 'liability'
             AND (a.name = ia.account_name OR a.name LIKE ia.account_name || ':%')
             AND (
                 (params.principal_tag_key = '' AND p.amount_real > 0)
                 OR (
                     params.principal_tag_key <> ''
                     AND json_valid(COALESCE(p.tags, '{}'))
                     AND json_extract(p.tags, '$.' || params.principal_tag_key) = params.principal_tag_value
                     AND p.amount_real > 0
                 )
             )
            THEN p.amount_real ELSE 0
        END) AS installment_principal_paid
    FROM transactions t
    JOIN postings p ON p.transaction_id = t.id
    JOIN accounts a ON a.id = p.account_id
    JOIN commodities c ON c.id = p.commodity_id
    CROSS JOIN params
    LEFT JOIN installment_accounts ia ON a.name = ia.account_name OR a.name LIKE ia.account_name || ':%'
    WHERE t.date >= params.first_month
      AND t.date < date(params.first_month, '+6 months')
      AND (a.root_type = 'expense' OR ia.account_name IS NOT NULL)
    GROUP BY strftime('%Y-%m', t.date), c.symbol
),
periods AS (
    SELECT strftime('%Y-%m', month_start) AS month FROM months
),
used_commodities AS (
    SELECT DISTINCT commodity FROM monthly_activity
)
SELECT
    periods.month,
    used_commodities.commodity,
    ROUND(COALESCE(activity.living_expenses, 0), 2) AS living_expenses,
    ROUND(COALESCE(activity.installment_principal_paid, 0), 2) AS installment_principal_paid,
    ROUND(COALESCE(activity.living_expenses, 0) + COALESCE(activity.installment_principal_paid, 0), 2) AS total_burn_rate,
    ROUND(AVG(COALESCE(activity.living_expenses, 0) + COALESCE(activity.installment_principal_paid, 0))
        OVER (PARTITION BY used_commodities.commodity), 2) AS six_month_average_burn_rate
FROM periods
CROSS JOIN used_commodities
LEFT JOIN monthly_activity activity
    ON activity.month = periods.month AND activity.commodity = used_commodities.commodity
ORDER BY periods.month DESC, used_commodities.commodity;
