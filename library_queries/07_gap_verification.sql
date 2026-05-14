-- Gap and limitation verification surface.
SELECT
  gap_verification.gap_id AS gap_id,
  gap_verification.doc_id AS doc_id,
  gap_verification.rel_path AS rel_path,
  gap_verification.source_label AS source_label,
  gap_verification.title AS title,
  gap_verification.severity AS severity,
  gap_verification.category AS category,
  gap_verification.source_locator AS source_locator,
  gap_verification.matched_terms AS matched_terms,
  gap_verification.gap_text AS gap_text
FROM v_agent_batch_gap_verification AS gap_verification;
