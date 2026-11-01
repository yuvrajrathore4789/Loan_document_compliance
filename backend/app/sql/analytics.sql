-- Analytical queries (portable SQL: SQLite and PostgreSQL). Each block starts with "-- name: <query_name>".
-- Run through SQLAlchemy text() with bound parameters (see services/analytics.py).
-- Demonstrates joins, grouping/aggregation, CASE, CTEs and window functions (RANK, SUM OVER, LAG).

-- name: applications_with_missing_documents
-- Applications that currently have unresolved "Missing Document" exceptions (JOIN + GROUP BY).
SELECT a.id AS application_id, a.applicant_name, a.application_type, a.status,
       COUNT(e.id) AS open_missing_document_exceptions
FROM applications a
JOIN exceptions e ON e.application_id = a.id
WHERE e.category = 'Missing Document' AND e.status <> 'RESOLVED'
GROUP BY a.id, a.applicant_name, a.application_type, a.status
ORDER BY open_missing_document_exceptions DESC, a.id;

-- name: applications_with_high_severity_exceptions
-- Unresolved HIGH severity exceptions per application, ranked (window function RANK).
SELECT a.id AS application_id, a.applicant_name, COUNT(e.id) AS high_open_exceptions,
       RANK() OVER (ORDER BY COUNT(e.id) DESC) AS rank_by_high_exceptions
FROM applications a
JOIN exceptions e ON e.application_id = a.id
WHERE e.severity = 'HIGH' AND e.status <> 'RESOLVED'
GROUP BY a.id, a.applicant_name
ORDER BY high_open_exceptions DESC, a.id;

-- name: documents_processed_by_category
-- Documents per category with share of total and mean OCR confidence (SUM() OVER ()).
SELECT d.category, COUNT(*) AS documents,
       100.0 * COUNT(*) / SUM(COUNT(*)) OVER () AS share_pct,
       AVG(d.ocr_confidence) AS avg_ocr_confidence,
       SUM(CASE WHEN d.processing_error IS NOT NULL THEN 1 ELSE 0 END) AS processing_failures
FROM documents d
GROUP BY d.category
ORDER BY documents DESC;

-- name: exception_frequency_by_rule
-- Exceptions per rule with percentage and running cumulative share (LEFT JOIN keeps rules with zero hits).
SELECT r.id AS rule_id, r.name AS rule_name, r.severity AS rule_severity, COUNT(e.id) AS exceptions,
       100.0 * COUNT(e.id) / NULLIF(SUM(COUNT(e.id)) OVER (), 0) AS share_pct,
       SUM(COUNT(e.id)) OVER (ORDER BY COUNT(e.id) DESC, r.id) AS cumulative_exceptions
FROM verification_rules r
LEFT JOIN exceptions e ON e.rule_id = r.id
GROUP BY r.id, r.name, r.severity
ORDER BY exceptions DESC, r.id;

-- name: average_processing_time
-- Mean/max document processing seconds per category (documents that were processed).
SELECT d.category, COUNT(*) AS documents, AVG(d.processing_seconds) AS avg_seconds,
       MAX(d.processing_seconds) AS max_seconds,
       AVG(CASE WHEN d.ocr_confidence IS NOT NULL THEN d.processing_seconds END) AS avg_seconds_ocr_only
FROM documents d
WHERE d.processing_seconds IS NOT NULL
GROUP BY d.category
ORDER BY avg_seconds DESC;

-- name: resolved_vs_unresolved
-- Resolved vs unresolved exceptions by severity (CASE + conditional aggregation).
SELECT e.severity,
       SUM(CASE WHEN e.status = 'RESOLVED' THEN 1 ELSE 0 END) AS resolved,
       SUM(CASE WHEN e.status <> 'RESOLVED' THEN 1 ELSE 0 END) AS unresolved,
       COUNT(*) AS total
FROM exceptions e
GROUP BY e.severity
ORDER BY CASE e.severity WHEN 'HIGH' THEN 1 WHEN 'MEDIUM' THEN 2 ELSE 3 END;

-- name: reviewer_workload
-- Workload per reviewer, ranked by open items (COALESCE, window RANK).
SELECT COALESCE(e.assigned_reviewer, 'Unassigned') AS reviewer,
       COUNT(*) AS assigned_total,
       SUM(CASE WHEN e.status <> 'RESOLVED' THEN 1 ELSE 0 END) AS open_items,
       SUM(CASE WHEN e.status = 'RESOLVED' THEN 1 ELSE 0 END) AS resolved_items,
       AVG(e.resolution_seconds) AS avg_resolution_seconds,
       RANK() OVER (ORDER BY SUM(CASE WHEN e.status <> 'RESOLVED' THEN 1 ELSE 0 END) DESC) AS workload_rank
FROM exceptions e
GROUP BY COALESCE(e.assigned_reviewer, 'Unassigned')
ORDER BY open_items DESC;

-- name: monthly_verification_statistics
-- Monthly verification volume and flag rate with month-over-month change (CTE + LAG).
WITH monthly AS (
    SELECT SUBSTR(CAST(v.created_at AS TEXT), 1, 7) AS month,
           COUNT(DISTINCT v.run_id) AS verification_runs,
           COUNT(*) AS rule_results,
           SUM(CASE WHEN v.outcome IN ('FAIL', 'WARN') THEN 1 ELSE 0 END) AS flagged_results
    FROM verification_results v
    GROUP BY SUBSTR(CAST(v.created_at AS TEXT), 1, 7)
)
SELECT month, verification_runs, rule_results, flagged_results,
       100.0 * flagged_results / NULLIF(rule_results, 0) AS flagged_pct,
       LAG(verification_runs) OVER (ORDER BY month) AS previous_month_runs,
       verification_runs - LAG(verification_runs) OVER (ORDER BY month) AS runs_change
FROM monthly
ORDER BY month;
