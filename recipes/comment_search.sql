/*
Comment Search & Posting Drill-down

Search transaction-level and posting-level hledger comments and return the
matching transaction's postings with account, amount, commodity, payee, and
narration for review. A transaction comment match returns all of that
transaction's postings; a posting-comment match returns only the posting whose
comment matched.

Edit note_pattern to a SQLite LIKE pattern (for example '%teflon%'). Percent
and underscore are LIKE wildcards. Set date_from/date_through to ISO dates or
leave them NULL. Comments are distinct from description-derived payee/narration.
Amounts are native to each posting's commodity and should not be summed across
commodities.
*/
WITH params AS (
    SELECT
        '%teflon%' AS note_pattern,
        NULL AS date_from,
        NULL AS date_through
),
matched_transactions AS (
    SELECT t.id
    FROM transactions t
    CROSS JOIN params
    WHERE (params.date_from IS NULL OR t.date >= params.date_from)
      AND (params.date_through IS NULL OR t.date <= params.date_through)
      AND COALESCE(t.comment, '') LIKE params.note_pattern
),
matched_postings AS (
    SELECT p.id
    FROM postings p
    JOIN transactions t ON t.id = p.transaction_id
    CROSS JOIN params
    WHERE (params.date_from IS NULL OR t.date >= params.date_from)
      AND (params.date_through IS NULL OR t.date <= params.date_through)
      AND COALESCE(p.comment, '') LIKE params.note_pattern
)
SELECT
    t.date,
    t.payee,
    t.narration,
    a.name AS account,
    p.amount_str AS amount,
    c.symbol AS commodity,
    t.comment AS tx_comment,
    p.comment AS posting_comment,
    p.tags AS posting_tags,
    t.tags AS tx_tags
FROM transactions t
JOIN postings p ON p.transaction_id = t.id
JOIN accounts a ON a.id = p.account_id
JOIN commodities c ON c.id = p.commodity_id
WHERE t.id IN (SELECT id FROM matched_transactions)
   OR p.id IN (SELECT id FROM matched_postings)
ORDER BY t.date DESC, t.id, p.id;
