# Agent Research Protocol

This file governs research work in this repository. Treat it as the operating contract for agents that inspect, audit, verify, or summarize the library.

## Scope

The catalog is built for shard-based research. Use exported shard CSV files as the normal work surface. Do not make parallel agents query `library.duckdb` directly.

Canonical artifacts:

- `library.duckdb`: canonical DuckDB build artifact for local inspection and rebuild verification.
- `library_cache/manifest.json`: catalog counts, schema version, root paths, and skipped paths.
- `library_cache/agent_shards/manifest.csv`: assignment index for research shards.
- `library_cache/agent_shards/*.csv`: deterministic task shards for agents.
- `library_cache/tables/*.csv`: exported catalog tables for inspection without database locks.
- `library_cache/build.log`: build event log.
- `library_queries/*.sql`: generated query examples; these must remain explicit and provenance-readable.

## Source Of Truth

Do not recreate catalog extraction during research. The exported catalog tables are the source of truth for discovered documents, text units, claims, gaps, topics, quality flags, and batch items.

Required source tables by task type:

- Claim audits use `library_cache/tables/claims.csv`.
- Gap verification uses `library_cache/tables/gaps.csv`.
- Document inventory uses `library_cache/tables/documents.csv`.
- Empty-file and trust checks use `library_cache/tables/quality_flags.csv`.
- Batch membership uses `library_cache/agent_shards/*.csv` and `library_cache/tables/agent_batch_items.csv`.

Prohibited during research:

- Inventing new `claim_id`, `gap_id`, `unit_id`, `doc_id`, or `item_id` values.
- Re-running ad hoc PDF/text extraction to create a competing claim or gap universe.
- Treating a sentence with an internal citation, figure reference, or section reference as externally verified.
- Marking a row `verified` unless the claim was checked against an explicit source.
- Reporting row counts that include CSV headers as work rows.

If local source text must be inspected, use it only as supporting evidence for an existing catalog row. Keep the catalog row identifier unchanged.

## Research DAG

Research work must be authored as a DAG of atomic collector inventories, not as a broad essay, chat summary, or undifferentiated source packet. Research is only complete when it leaves behind usable, source-grounded claims that a downstream writer or verifier can act on without reading chat history.

Canonical research artifact root:

- `research/specs/data/`

Existing research artifact families:

- `research/specs/data/collectors/`: markdown collector inventories.
- `research/specs/data/foundation/`: atomic foundation artifacts.
- `research/specs/data/layer_minus3_uefi/`: atomic Layer -3 UEFI artifacts.
- `research/specs/data/papers/`: existing paper-source breakdowns into atomic components.

New paper research target:

- `research/specs/data/research/$PAPER_SLUG_NAME/`

Existing collector examples:

- `research/specs/data/collectors/layer_0_inventory.md`
- `research/specs/data/collectors/layer_minus1_inventory.md`
- `research/specs/data/collectors/layer_minus2_inventory.md`

Required collector shape:

- `Locus`: exact target path for the collector file.
- `Author`: role or agent that produced the inventory.
- `Date`: generation date.
- `Scope`: what this collector covers and what it refuses to cover.
- `Status`: whether the collector is orientation, preemptive inventory, ready for downstream authorship, or blocked.
- `Mandate`: read-only research, spec authoring, validation, or citation grounding.
- `Sources of truth surveyed`: table of sources, paths or URLs, and exact loci consulted.
- `Findings`: atomic findings that can be consumed independently.
- `Proposed downstream artifacts`: concrete files, specs, records, or citations that a later agent can author.
- `Exclusions`: what not to infer from this collector.
- `Open questions`: unresolved decisions with the smallest possible owner surface.

Research DAG rules:

- One collector file should cover one source, one paper, one standard, one layer, or one tightly bounded source family.
- A collector must name its upstream sources and downstream consumers.
- A collector must not claim publication-ready truth; it inventories evidence and decisions.
- A collector must preserve source boundaries. Do not merge unrelated papers into one narrative just because they support the same theme.
- A collector must be useful if read alone.
- A collector must record negative findings, mismatches, and count discrepancies.
- A collector must separate source facts from agent inferences.
- A collector must not inspect or modify `working/` unless the user explicitly grants paper-work permission in the same turn.
- New research on a specific paper must be written under `research/specs/data/research/$PAPER_SLUG_NAME/`.
- The `$PAPER_SLUG_NAME` directory must be broken into atomic files rather than a single broad packet.
- Atomic files should separate source metadata, claim inventory, term inventory, method inventory, citation targets, exclusions, and downstream artifact proposals when those concerns exist.

Required usable research outputs:

- A source atom must state the exact claim it can support.
- A source atom must state the exact claim it cannot support.
- A writer-facing index must map source atoms to usable sentence-level claims, citation keys, source loci, argument roles, caveats, and next deeper atomization targets.
- A research task is not complete if it only creates scaffolding, a reading list, or a summary without a usable claim index.
- If the source is a position paper, publication page, abstract, or publisher page, mark that evidence level explicitly and do not promote it to empirical proof.

Canonical writer-facing indices:

- `research/specs/data/research/writer_claim_index.csv`
- `research/specs/data/research/argument_roles.csv`

Canonical relation-facing indices:

- `research/specs/data/research/relation_schema.csv`
- `research/specs/data/research/relation_candidates.csv`

Relation candidates must use this exact header:

```csv
relation_key,source_slug_a,citation_key_a,source_locus_a,atom_or_claim_a,source_slug_b,citation_key_b,source_locus_b,atom_or_claim_b,relation_type,usable_relation,required_caveat,not_for,next_action,origin_agent,origin_file
```

Agents must not invent private relation schemas. If a relation only has one primary source, set the other side to `local_concept` or a concrete source slug and explain the boundary in `required_caveat`.

When researching a paper or standard, create a paper-scoped research directory and keep collector notes separate from atomic data artifacts, for example:

- `research/specs/data/research/spivak_kent_ologs/source.md`
- `research/specs/data/research/spivak_kent_ologs/claims.csv`
- `research/specs/data/research/spivak_kent_ologs/terms.csv`
- `research/specs/data/research/spivak_kent_ologs/downstream.md`
- `research/specs/data/collectors/spivak_kent_ologs_inventory.md`

Each paper research directory should answer:

1. What is this source?
2. Why is it authoritative enough to cite?
3. What exact claims can it support?
4. What claims can it not support?
5. What structured artifacts should downstream agents create from it?
6. What open verification remains?

## Research Render DAG

Research render work is a separate DAG from source research. It exposes the
research phases inside the local encyclopedia without asking writer agents to
reinterpret chat history.

Canonical render entrypoint:

- `Makefile` at the repository root.

Render nodes:

1. `make render-research-appendix` reads canonical research indices, source atom
   directories, and `_runs/*` phase ledgers, then writes generated artifacts
   under `research/specs/data/research/render/out/`.
2. `make install-research-appendix` installs generated appendix TeX under
   `working/src/appendices/38_appendix_d_research_phases/` and generated
   BibLaTeX under `working/src/shared/research_appendix.bib`.
3. `make validate-research-render` checks appendix files, bibliography keys, and
   encyclopedia include wiring.
4. `make render` runs those steps and then delegates the PDF build to
   `make -C working build`.

Generated render artifacts must be reproducible from research CSVs and run
ledgers. Do not hand-edit generated Appendix D files; change the renderer or the
underlying research artifacts instead.

## First Moves

1. Read `library_cache/manifest.json` to confirm the catalog version and row counts.
2. Read `library_cache/agent_shards/manifest.csv` to choose or confirm the assigned batch and shard.
3. Open only the shard CSV needed for the assignment.
4. Record the shard path, `batch_id`, `shard_id`, objective, and expected output shape in your notes before starting analysis.
5. Inspect source files through the `rel_path` values in the shard. Keep `doc_id` with every finding.

Recommended shell commands:

```bash
sed -n '1,80p' library_cache/manifest.json
sed -n '1,20p' library_cache/agent_shards/manifest.csv
sed -n '1,20p' library_cache/agent_shards/B002_claim_audit_shard_000.csv
```

## Research Discipline

Every finding must be traceable to evidence. A usable finding includes:

- `batch_id`
- `shard_id`
- `item_id` when present
- `doc_id`
- `rel_path`
- finding type
- severity or confidence
- short evidence summary
- exact local source reference when available
- external source reference when used
- proposed next action

Separate these categories explicitly:

- Local catalog claim: a claim found in repository content.
- Externally verified fact: a claim checked against an outside source.
- Inference: a conclusion drawn from multiple local facts.
- Gap: missing evidence, missing source, incomplete validation, or unresolved contradiction.

Do not promote generated reports, sidecars, rendered artifacts, or derived summaries into verified facts without external verification.

## Shard Workflow

Use `library_cache/agent_shards/manifest.csv` as the assignment table. Each shard row declares the source view, objective, expected output shape, and quality constraints.

For each assigned shard:

1. Confirm the shard exists.
2. Read the shard header and first records.
3. Work row by row. Do not silently skip rows.
4. If a row cannot be evaluated, record why.
5. Keep findings in the output shape requested by the manifest.
6. Preserve the input identifiers exactly. Do not rename `doc_id`, `item_id`, `batch_id`, or `shard_id`.
7. Join the shard to the relevant exported table before producing findings. For B002, join on `doc_id` to `claims.csv`; for B006, join on `doc_id` to `gaps.csv`.

Empty files are cataloged inventory, not research text. Rows with `ingest_status` equal to `empty_file` or quality flag `empty_file_no_text` should only be audited as artifacts, lineage, or missing-content signals.

## Batch Rules

B002 claim audit:

- Input shard rows are document assignments, not claim rows.
- Expand assigned documents by joining `library_cache/agent_shards/B002_claim_audit_shard_000.csv` to `library_cache/tables/claims.csv` on `doc_id`.
- Output the existing `claims.csv` `claim_id`; never generate `doc_id_001` style IDs.
- `verification_status` must describe verification work actually performed: `externally_verified`, `locally_supported`, `contradicted`, `needs_external_verification`, or `not_evaluated`.
- `source_needed` means an external source is still required; internal citations do not clear this requirement for current facts or external factual claims.
- `confidence` must reflect evidence quality, not the presence of brackets, figures, or section references.

B006 gap verification:

- Input shard rows are document assignments, not final gap findings.
- Expand assigned documents by joining the shard to `library_cache/tables/gaps.csv` on `doc_id`.
- Output the existing `gaps.csv` `gap_id`; never create a replacement ID.
- Classify whether the row is a real blocker, a resolved/deferred design decision, or a catalog false positive caused by words like "gap" in a title, citation, or closure note.

Example B002 expansion:

```sql
-- Expand a B002 shard from assigned documents to catalog claim rows.
WITH shard AS (
  SELECT
    s.batch_id AS batch_id,
    s.shard_id AS shard_id,
    s.item_id AS item_id,
    s.doc_id AS doc_id,
    s.rel_path AS rel_path
  FROM read_csv_auto('library_cache/agent_shards/B002_claim_audit_shard_000.csv') AS s
),
catalog_claims AS (
  SELECT
    c.claim_id AS claim_id,
    c.doc_id AS doc_id,
    c.claim_text AS claim_text,
    c.source_locator AS source_locator,
    c.claim_type AS claim_type,
    c.evidence_hint AS evidence_hint
  FROM read_csv_auto('library_cache/tables/claims.csv') AS c
)
SELECT
  sh.batch_id AS batch_id,
  sh.shard_id AS shard_id,
  sh.item_id AS item_id,
  cc.claim_id AS claim_id,
  sh.doc_id AS doc_id,
  sh.rel_path AS rel_path,
  cc.claim_text AS claim_text,
  cc.source_locator AS source_locator,
  cc.claim_type AS claim_type,
  cc.evidence_hint AS evidence_hint
FROM shard AS sh
INNER JOIN catalog_claims AS cc
  ON cc.doc_id = sh.doc_id
ORDER BY
  sh.rel_path ASC,
  cc.claim_id ASC;
```

## SQL Rules

SQL in this repository must be explicit enough to reconstruct column provenance from the query text.

Required:

- Every table, view, CTE, and subquery must have an alias.
- Every selected column must be qualified by its alias.
- Project named columns only.
- Use named aggregate arguments, such as `COUNT(d.doc_id)`, instead of star-count form.
- Join predicates must be written with qualified aliases.
- Keep output column names stable and descriptive.
- Add a short purpose comment before non-trivial queries.

Prohibited:

- Wildcard projection.
- Unqualified selected columns.
- Implicit column provenance.
- Ambiguous joins.
- Silent query rewrites that change output shape.

When using DuckDB, prefer read-only inspection and avoid concurrent readers during swarm work. For parallel work, use CSV shards and table exports.

Example style:

```sql
-- List non-empty documents assigned to a specific batch shard.
SELECT
  s.batch_id AS batch_id,
  s.shard_id AS shard_id,
  s.item_id AS item_id,
  s.doc_id AS doc_id,
  s.rel_path AS rel_path
FROM read_csv_auto('library_cache/agent_shards/B003_spec_validation_shard_000.csv') AS s
WHERE s.doc_id IS NOT NULL
ORDER BY
  s.item_id ASC;
```

## External Verification

Use external research when a claim is current, historical, legal, medical, financial, safety-critical, or otherwise not verifiable from local repository evidence alone.

External verification notes must include:

- source title or organization
- URL
- publication or access date when available
- checked date
- what claim the source supports or contradicts
- confidence level

Do not paste large copyrighted excerpts. Use short quotes only when necessary and otherwise summarize.

## Notes And Logging

No silent research runs. Each agent should leave a concise research note or final report that includes:

- assignment metadata
- commands or files inspected
- findings in the requested output shape
- unresolved questions
- skipped rows with reasons
- external sources used
- validation performed

If the task writes a file, include a short header with purpose, inputs, and generation date. If the task changes catalog generation code, ensure `library_cache/build.log`, table comments, and manifest outputs remain meaningful after rebuild.

## Mutation Rules

Research assignments are read-only unless the user explicitly asks for edits. Do not delete, move, normalize, or rewrite corpus files during audit work.

Allowed during research:

- reading shard CSVs
- reading exported tables
- reading source files referenced by `rel_path`
- producing notes, findings, or reports

Not allowed without explicit direction:

- changing corpus files
- deleting generated artifacts
- rebuilding the catalog
- altering `library_queries/*.sql`
- changing DuckDB schema or generated DDL

## Completion Checklist

Before reporting done:

1. Confirm every assigned row is handled or explicitly deferred with a reason.
2. Confirm every finding has `doc_id` and `rel_path`.
3. Confirm local claims and externally verified facts are labeled separately.
4. Confirm empty files were not treated as text evidence.
5. Confirm SQL, if written, uses aliases and qualified columns.
6. Confirm the output matches the shard manifest expected shape.
7. Summarize residual risk and next recommended shard or batch.
