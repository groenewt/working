-- Swarm-safe shard manifest.
SELECT
  agent_shards.batch_id AS batch_id,
  agent_shards.shard_id AS shard_id,
  agent_shards.shard_path AS shard_path,
  agent_shards.row_count AS row_count,
  agent_shards.source_view AS source_view,
  agent_shards.objective AS objective,
  agent_shards.expected_output_shape AS expected_output_shape,
  agent_shards.quality_constraints AS quality_constraints
FROM v_agent_shards AS agent_shards;
