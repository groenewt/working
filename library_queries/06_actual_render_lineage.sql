-- Actual render lineage surface aligned with B005.
SELECT
  actual_render_lineage.doc_id AS doc_id,
  actual_render_lineage.rel_path AS rel_path,
  actual_render_lineage.filename AS filename,
  actual_render_lineage.extension AS extension,
  actual_render_lineage.title AS title,
  actual_render_lineage.source_label AS source_label,
  actual_render_lineage.file_kind AS file_kind,
  actual_render_lineage.ingest_status AS ingest_status,
  actual_render_lineage.render_file_role AS render_file_role,
  actual_render_lineage.is_empty_file AS is_empty_file,
  actual_render_lineage.is_texture_tex AS is_texture_tex,
  actual_render_lineage.is_pdf AS is_pdf,
  actual_render_lineage.has_yoneda_text_hit AS has_yoneda_text_hit,
  actual_render_lineage.has_category_ontology_topic AS has_category_ontology_topic,
  actual_render_lineage.word_count AS word_count,
  actual_render_lineage.topics AS topics,
  actual_render_lineage.flags AS flags
FROM v_agent_batch_actual_render_lineage AS actual_render_lineage;
