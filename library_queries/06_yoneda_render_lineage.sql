-- Compatibility alias for previous Yoneda render-lineage query name.
SELECT
  yoneda_render_lineage.doc_id AS doc_id,
  yoneda_render_lineage.rel_path AS rel_path,
  yoneda_render_lineage.filename AS filename,
  yoneda_render_lineage.extension AS extension,
  yoneda_render_lineage.title AS title,
  yoneda_render_lineage.source_label AS source_label,
  yoneda_render_lineage.file_kind AS file_kind,
  yoneda_render_lineage.ingest_status AS ingest_status,
  yoneda_render_lineage.render_file_role AS render_file_role,
  yoneda_render_lineage.is_empty_file AS is_empty_file,
  yoneda_render_lineage.is_texture_tex AS is_texture_tex,
  yoneda_render_lineage.is_pdf AS is_pdf,
  yoneda_render_lineage.has_yoneda_text_hit AS has_yoneda_text_hit,
  yoneda_render_lineage.has_category_ontology_topic AS has_category_ontology_topic,
  yoneda_render_lineage.word_count AS word_count,
  yoneda_render_lineage.topics AS topics,
  yoneda_render_lineage.flags AS flags
FROM v_agent_batch_yoneda_render_lineage AS yoneda_render_lineage;
