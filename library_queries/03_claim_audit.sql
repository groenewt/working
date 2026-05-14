-- Claims that need audit or external verification.
SELECT
  claim_audit.claim_id AS claim_id,
  claim_audit.doc_id AS doc_id,
  claim_audit.rel_path AS rel_path,
  claim_audit.source_label AS source_label,
  claim_audit.title AS title,
  claim_audit.claim_type AS claim_type,
  claim_audit.trust_state AS trust_state,
  claim_audit.source_locator AS source_locator,
  claim_audit.evidence_hint AS evidence_hint,
  claim_audit.claim_text AS claim_text
FROM v_agent_batch_claim_audit AS claim_audit;
