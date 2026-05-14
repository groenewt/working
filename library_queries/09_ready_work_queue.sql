-- Unified work queue; prefer shard CSVs for parallel work.
SELECT
  ready_work_queue.batch_id AS batch_id,
  ready_work_queue.objective AS objective,
  ready_work_queue.batch_priority AS batch_priority,
  ready_work_queue.item_priority AS item_priority,
  ready_work_queue.batch_item_id AS batch_item_id,
  ready_work_queue.doc_id AS doc_id,
  ready_work_queue.rel_path AS rel_path,
  ready_work_queue.source_label AS source_label,
  ready_work_queue.title AS title,
  ready_work_queue.item_reason AS item_reason,
  ready_work_queue.expected_output_shape AS expected_output_shape,
  ready_work_queue.quality_constraints AS quality_constraints
FROM v_agent_ready_work_queue AS ready_work_queue;
