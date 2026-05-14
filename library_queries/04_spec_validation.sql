-- Primary spec validation surface.
SELECT
  spec_validation.doc_id AS doc_id,
  spec_validation.rel_path AS rel_path,
  spec_validation.title AS title,
  spec_validation.urn AS urn,
  spec_validation.layer AS layer,
  spec_validation.type_node AS type_node,
  spec_validation.source_path AS source_path,
  spec_validation.locator AS locator,
  spec_validation.flag AS flag,
  spec_validation.severity AS severity,
  spec_validation.reason AS reason
FROM v_agent_batch_spec_validation AS spec_validation;
