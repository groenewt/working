defmodule ResearchRender.Context do
  @phase_appendix_id "38_appendix_d_research_phases"
  @source_mirror_appendix_id "39_appendix_e_research_source_mirror"
  @research_root_rel "research"
  @research_index_root_rel "research/specs/data/research"
  @catalog_duckdb_slug "catalog_duckdb"
  @catalog_duckdb_source_rel "research/specs/data/research/catalog_duckdb"
  @build_root_rel "research/build/specs/research"
  @working_appendix_root_rel "working/src/appendices"
  @duckdb_projection_rel "working/src/projections/research_catalog_duckdb.tex"
  @duckdb_projection_stage_rel "projections/research_catalog_duckdb.tex"
  @duckdb_projection_build_rel "working/build/research-catalog-duckdb/main.pdf"
  @generated_date "2026-05-14"

  def new(repo_root) do
    repo_root = Path.expand(repo_root)
    stage_root = Path.join(repo_root, @build_root_rel)
    stage_catalog = Path.join(stage_root, @catalog_duckdb_slug)

    %{
      repo_root: repo_root,
      phase_appendix_id: @phase_appendix_id,
      source_mirror_appendix_id: @source_mirror_appendix_id,
      research_root_rel: @research_root_rel,
      research_index_root_rel: @research_index_root_rel,
      catalog_duckdb_slug: @catalog_duckdb_slug,
      catalog_duckdb_root_rel: Path.join(@build_root_rel, @catalog_duckdb_slug),
      catalog_duckdb_source_rel: @catalog_duckdb_source_rel,
      catalog_duckdb_discovery_root_rel: Path.join([@build_root_rel, @catalog_duckdb_slug, "discovery"]),
      build_root_rel: @build_root_rel,
      working_appendix_root_rel: @working_appendix_root_rel,
      duckdb_projection_rel: @duckdb_projection_rel,
      duckdb_projection_stage_rel: Path.join(@build_root_rel, @duckdb_projection_stage_rel),
      duckdb_projection_build_rel: @duckdb_projection_build_rel,
      generated_date: @generated_date,
      research_index_root: Path.join(repo_root, @research_index_root_rel),
      catalog_duckdb_root: stage_catalog,
      catalog_duckdb_discovery_root: Path.join(stage_catalog, "discovery"),
      catalog_duckdb_source_root: Path.join(repo_root, @catalog_duckdb_source_rel),
      stage_root: stage_root,
      stage_bib: Path.join(stage_root, "research_appendix.bib"),
      stage_manifest: Path.join(stage_root, "render_manifest.csv"),
      stage_log: Path.join(stage_root, "render.log"),
      stage_duckdb_projection: Path.join([stage_root, "projections", "research_catalog_duckdb.tex"]),
      working_appendix_root: Path.join(repo_root, @working_appendix_root_rel),
      working_bib: Path.join(repo_root, "working/src/shared/research_appendix.bib"),
      preamble: Path.join(repo_root, "working/src/shared/preamble.tex"),
      projection: Path.join(repo_root, "working/src/projections/local_encyclopedia.tex"),
      duckdb_projection: Path.join(repo_root, @duckdb_projection_rel),
      appendices: appendices(),
      discovery_headers: discovery_headers(),
      manifest_table_keys: manifest_table_keys(),
      local_research_bib_keys: [
        "silmaril-research-index-2026",
        "silmaril-research-phase-01-2026",
        "silmaril-research-phase-02-2026",
        "silmaril-research-phase-03-2026"
      ],
      citation_key_columns: ["citation_key", "citation_key_a", "citation_key_b"],
      diagram_languages: diagram_languages(),
      diagram_file_extensions: diagram_file_extensions(),
      markdown_scalar_field_names: [
        "abstract",
        "body",
        "content",
        "description",
        "markdown",
        "markdown_content",
        "md",
        "notes",
        "summary",
        "text"
      ],
      record_key_columns: [
        "claim_key",
        "relation_key",
        "agent_id",
        "artifact",
        "gap_id",
        "claim_id",
        "source_slug",
        "citation_key",
        "id",
        "name"
      ],
      table_levels: ["\\section", "\\subsection", "\\subsubsection", "\\paragraph", "\\subparagraph"],
      cache_dir_names: ["__pycache__", ".cache", ".mypy_cache", ".pytest_cache", "node_modules", "library_cache"]
    }
  end

  defp appendices do
    [
      %{
        id: @phase_appendix_id,
        title: "Appendix D: Research Phases",
        source_root: "research/specs/data/research/_runs",
        mode: :phases
      },
      %{
        id: @source_mirror_appendix_id,
        title: "Appendix E: research",
        source_root: @research_root_rel,
        mode: :mirror
      }
    ]
  end

  defp discovery_headers do
    %{
      "artifacts.csv" => [
        "artifact_key",
        "citation_key",
        "path",
        "role",
        "bytes",
        "modified_at",
        "sha256",
        "evidence_level",
        "description"
      ],
      "tables.csv" => [
        "object_name",
        "object_type",
        "row_count",
        "manifest_count",
        "reconciled",
        "columns",
        "source_artifact",
        "citation_key",
        "evidence_level"
      ],
      "queries.csv" => [
        "query_key",
        "citation_key",
        "path",
        "role",
        "bytes",
        "modified_at",
        "sha256",
        "sql_rule_status",
        "evidence_level"
      ],
      "shards.csv" => [
        "batch_id",
        "shard_id",
        "shard_path",
        "row_count",
        "source_view",
        "objective",
        "expected_output_shape",
        "quality_constraints",
        "citation_key",
        "evidence_level"
      ],
      "relations.csv" => [
        "relation_key",
        "source_artifact",
        "target_artifact",
        "relation_type",
        "usable_relation",
        "required_caveat",
        "citation_key",
        "evidence_level"
      ]
    }
  end

  defp manifest_table_keys do
    %{
      "agent_batch_items" => "agent_batch_items",
      "agent_batches" => "agent_batches",
      "agent_shards" => "agent_shards",
      "claims" => "claims",
      "documents" => "documents",
      "duplicate_groups" => "duplicate_groups",
      "gaps" => "gaps",
      "text_units" => "document_text_units",
      "topics" => "document_topics"
    }
  end

  defp diagram_languages do
    %{
      "dot" => %{command: "dot", input_extension: "dot"},
      "graphviz" => %{command: "dot", input_extension: "dot"},
      "gv" => %{command: "dot", input_extension: "dot"},
      "plantuml" => %{command: "plantuml", input_extension: "puml"},
      "puml" => %{command: "plantuml", input_extension: "puml"},
      "mermaid" => %{command: "mmdc", input_extension: "mmd"},
      "mmd" => %{command: "mmdc", input_extension: "mmd"}
    }
  end

  defp diagram_file_extensions do
    %{
      ".dot" => "dot",
      ".gv" => "dot",
      ".puml" => "plantuml",
      ".plantuml" => "plantuml",
      ".mmd" => "mermaid",
      ".mermaid" => "mermaid"
    }
  end
end
