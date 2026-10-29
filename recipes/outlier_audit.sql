/*
Outlier Audit

What were the largest individual transactions this month, and what tags were
attached?

Quickly scan for unauthorized charges, forgot-to-cancel subscriptions, or
misclassified expenses before closing the month.
*/
WITH params AS (
    SELECT strftime('%Y-%m', 'now') AS anchor_month
)
SELECT
    t.date,
    t.payee,
    a.name AS account,
    ROUND(v.market_value, 2) AS amount_usd,
    t.tags AS tx_tags,
    p.tags AS posting_tags
FROM v_postings_valued v
JOIN postings p     ON v.posting_id = p.id
JOIN transactions t ON p.transaction_id = t.id
JOIN accounts a     ON v.account = a.name
CROSS JOIN params p_month
WHERE strftime('%Y-%m', v.date) = p_month.anchor_month
  AND a.root_type = 'expense'
ORDER BY v.market_value DESC
LIMIT 15;
