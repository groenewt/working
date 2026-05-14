-- Duplicate source/export records for representative selection.
SELECT
  source_dedupe.group_id AS group_id,
  source_dedupe.member_count AS member_count,
  source_dedupe.group_label AS group_label,
  source_dedupe.doc_id AS doc_id,
  source_dedupe.rel_path AS rel_path,
  source_dedupe.source_label AS source_label,
  source_dedupe.title AS title,
  source_dedupe.sha256 AS sha256
FROM v_agent_batch_source_dedupe AS source_dedupe;
