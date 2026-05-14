#!/usr/bin/env python3
"""Build the local DuckDB catalog and swarm-safe task shards.

Contract:
- `library.duckdb` is the canonical local catalog build artifact.
- Parallel agents should consume `library_cache/agent_shards/*.csv`, not
  concurrent DuckDB reads.
- Document and task identifiers are deterministic from relative paths and
  local extraction order.
- Empty text files are cataloged as artifacts, flagged, and excluded from
  research-text work except explicit render-lineage auditing.
"""

from __future__ import annotations

import csv
import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    import yaml
except Exception as exc:  # pragma: no cover - runtime dependency check
    print(f"PyYAML is required: {exc}", file=sys.stderr)
    sys.exit(2)


ROOT = Path.cwd().resolve()
DB_PATH = ROOT / "library.duckdb"
CACHE_DIR = ROOT / "library_cache"
TABLE_DIR = CACHE_DIR / "tables"
TEXT_DIR = CACHE_DIR / "text"
PDF_TEXT_DIR = TEXT_DIR / "pdf"
AGENT_SHARD_DIR = CACHE_DIR / "agent_shards"
SQL_PATH = CACHE_DIR / "load_catalog.sql"
MANIFEST_PATH = CACHE_DIR / "manifest.json"
BUILD_LOG_PATH = CACHE_DIR / "build.log"
QUERY_DIR = ROOT / "library_queries"
BUILD_TMP_DIR = CACHE_DIR / ".build_tmp"

SCHEMA_VERSION = "2026-05-13.2"
AGENT_SHARD_SIZE = 100
MAX_HASH_BYTES = 100 * 1024 * 1024
MAX_TEXT_BYTES = 8 * 1024 * 1024
MAX_UNIT_CHARS = 14_000
MAX_CLAIMS_PER_DOC = 24
MAX_GAPS_PER_DOC = 24

SKIP_DIRS = {".git", ".codex", ".agents", ".idea", "__pycache__", "library_cache", "library_queries"}
SKIP_FILES = {"library.duckdb", "library.duckdb.wal"}
BUILD_EXTS = {
    ".aux",
    ".log",
    ".toc",
    ".out",
    ".fls",
    ".fdb_latexmk",
    ".xdv",
}
TEXT_EXTS = {
    ".avsc",
    ".bib",
    ".cls",
    ".html",
    ".j2",
    ".json",
    ".md",
    ".py",
    ".sql",
    ".sty",
    ".tex",
    ".ttl",
    ".txt",
    ".yaml",
    ".yml",
}
NUMERIC_TYPES = {"BIGINT", "INTEGER", "UBIGINT"}

LOGGER = logging.getLogger("library_catalog")


@dataclass(frozen=True)
class ColumnSchema:
    name: str
    sql_type: str
    description: str


@dataclass(frozen=True)
class TableSchema:
    name: str
    description: str
    columns: tuple[ColumnSchema, ...]

    @property
    def fields(self) -> list[str]:
        return [column.name for column in self.columns]


def col(name: str, sql_type: str, description: str) -> ColumnSchema:
    return ColumnSchema(name=name, sql_type=sql_type, description=description)


@dataclass(frozen=True)
class BuildPaths:
    db_path: Path
    table_dir: Path
    text_dir: Path
    pdf_text_dir: Path
    agent_shard_dir: Path
    sql_path: Path
    manifest_path: Path
    build_log_path: Path
    query_dir: Path
    catalog_pdf_text_dir: Path
    catalog_agent_shard_dir: Path


FINAL_PATHS = BuildPaths(
    db_path=DB_PATH,
    table_dir=TABLE_DIR,
    text_dir=TEXT_DIR,
    pdf_text_dir=PDF_TEXT_DIR,
    agent_shard_dir=AGENT_SHARD_DIR,
    sql_path=SQL_PATH,
    manifest_path=MANIFEST_PATH,
    build_log_path=BUILD_LOG_PATH,
    query_dir=QUERY_DIR,
    catalog_pdf_text_dir=PDF_TEXT_DIR,
    catalog_agent_shard_dir=AGENT_SHARD_DIR,
)

ACTIVE_PATHS = FINAL_PATHS


SCHEMAS: dict[str, TableSchema] = {
    "documents": TableSchema(
        "documents",
        "One row per cataloged filesystem artifact under the project root.",
        (
            col("doc_id", "VARCHAR", "Stable identifier `doc_` plus SHA-1 of the relative path."),
            col("abs_path", "VARCHAR", "Absolute filesystem path at build time."),
            col("rel_path", "VARCHAR", "Human-readable path relative to the project root."),
            col("filename", "VARCHAR", "Basename of the artifact."),
            col("dir1", "VARCHAR", "First relative path segment."),
            col("dir2", "VARCHAR", "Second relative path segment, when present."),
            col("extension", "VARCHAR", "Normalized file extension used by the ingester."),
            col("size_bytes", "UBIGINT", "Filesystem byte size."),
            col("mtime_ns", "BIGINT", "Filesystem modification time in nanoseconds."),
            col("sha256", "VARCHAR", "Content SHA-256 when hashing was attempted."),
            col("hash_status", "VARCHAR", "Hashing outcome."),
            col("source_label", "VARCHAR", "Catalog source class used for trust and workflow routing."),
            col("canonical_status", "VARCHAR", "Local canonicality label for this artifact."),
            col("ingest_status", "VARCHAR", "Text ingestion outcome, including `empty_file`."),
            col("text_cache_path", "VARCHAR", "Relative path to cached extracted text, when any."),
            col("title", "VARCHAR", "Best available title or stem."),
            col("detected_title", "VARCHAR", "Title detected from metadata or text."),
            col("pdf_pages", "INTEGER", "PDF page count when available."),
            col("word_count", "INTEGER", "Word count of ingested text."),
            col("line_count", "INTEGER", "Line count of ingested text."),
            col("file_kind", "VARCHAR", "Coarse file kind derived from source label and extension."),
            col("parse_status", "VARCHAR", "Parser status for typed formats."),
            col("parse_error", "TEXT", "Parser or ingestion error details."),
        ),
    ),
    "document_text_units": TableSchema(
        "document_text_units",
        "Chunked text units extracted from non-empty ingested documents.",
        (
            col("unit_id", "VARCHAR", "Stable document-local unit identifier."),
            col("doc_id", "VARCHAR", "Parent document identifier."),
            col("unit_index", "INTEGER", "One-based local unit index within the document."),
            col("unit_kind", "VARCHAR", "Chunking strategy or source section kind."),
            col("heading", "VARCHAR", "Heading or section label for the unit."),
            col("source_locator", "VARCHAR", "Local locator such as page, section, or chunk."),
            col("word_count", "INTEGER", "Unit word count."),
            col("char_count", "INTEGER", "Unit character count."),
            col("text", "TEXT", "Extracted text for the unit."),
        ),
    ),
    "document_topics": TableSchema(
        "document_topics",
        "Coarse deterministic topic hits derived from path, title, and local text.",
        (
            col("doc_id", "VARCHAR", "Document identifier."),
            col("topic", "VARCHAR", "Topic label."),
            col("score", "INTEGER", "Total matched term count."),
            col("matched_terms", "TEXT", "Matched terms and counts."),
        ),
    ),
    "yaml_metadata": TableSchema(
        "yaml_metadata",
        "Selected metadata fields parsed from YAML primary specs.",
        (
            col("doc_id", "VARCHAR", "Document identifier."),
            col("urn", "VARCHAR", "Parsed entity or document URN."),
            col("display_name", "VARCHAR", "Parsed display name."),
            col("name", "VARCHAR", "Parsed name."),
            col("title", "VARCHAR", "Parsed title."),
            col("layer", "VARCHAR", "Parsed layer."),
            col("kind", "VARCHAR", "Parsed kind."),
            col("kind_urn", "VARCHAR", "Parsed kind URN."),
            col("type_node", "VARCHAR", "Parsed type node."),
            col("type_urn", "VARCHAR", "Parsed type URN."),
            col("source_path", "VARCHAR", "Parsed source path."),
            col("locator", "VARCHAR", "Parsed locator."),
            col("spec_version", "VARCHAR", "Parsed spec version."),
            col("version", "VARCHAR", "Parsed version."),
            col("description", "TEXT", "Parsed description."),
        ),
    ),
    "quality_flags": TableSchema(
        "quality_flags",
        "Document-level flags used to route audit and verification work.",
        (
            col("flag_id", "VARCHAR", "Stable document-local quality flag identifier."),
            col("doc_id", "VARCHAR", "Document identifier."),
            col("flag", "VARCHAR", "Machine-readable flag."),
            col("severity", "VARCHAR", "Low, medium, or high severity."),
            col("reason", "TEXT", "Human-readable reason."),
        ),
    ),
    "duplicate_groups": TableSchema(
        "duplicate_groups",
        "Exact content duplicate groups by SHA-256.",
        (
            col("group_id", "VARCHAR", "Stable group identifier within the current build."),
            col("sha256", "VARCHAR", "Duplicate content digest."),
            col("member_count", "INTEGER", "Number of documents with the digest."),
            col("representative_doc_id", "VARCHAR", "Lexicographically first member path."),
            col("group_label", "VARCHAR", "Duplicate grouping method."),
        ),
    ),
    "claims": TableSchema(
        "claims",
        "Local claim candidates extracted from non-empty source text.",
        (
            col("claim_id", "VARCHAR", "Stable document-local claim identifier."),
            col("doc_id", "VARCHAR", "Document identifier."),
            col("claim_text", "TEXT", "Claim text."),
            col("source_locator", "VARCHAR", "Line or sentence locator."),
            col("trust_state", "VARCHAR", "Local or externally-verification-needed trust state."),
            col("claim_type", "VARCHAR", "Claim class used for audit routing."),
            col("evidence_hint", "VARCHAR", "Local hint about available evidence markers."),
        ),
    ),
    "gaps": TableSchema(
        "gaps",
        "Gap, limitation, unsupported, or verification-needed statements.",
        (
            col("gap_id", "VARCHAR", "Stable document-local gap identifier."),
            col("doc_id", "VARCHAR", "Document identifier."),
            col("category", "VARCHAR", "Gap category."),
            col("severity", "VARCHAR", "Low, medium, or high severity."),
            col("gap_text", "TEXT", "Gap or limitation text."),
            col("source_locator", "VARCHAR", "Line or sentence locator."),
            col("matched_terms", "TEXT", "Matched gap-pattern terms."),
        ),
    ),
    "agent_batches": TableSchema(
        "agent_batches",
        "Batch definitions for human and swarm audit work.",
        (
            col("batch_id", "VARCHAR", "Stable batch identifier."),
            col("objective", "TEXT", "Batch objective."),
            col("source_view", "VARCHAR", "DuckDB view that exposes the batch population."),
            col("priority", "INTEGER", "Lower number means higher priority."),
            col("expected_output_shape", "TEXT", "Expected output fields from an agent."),
            col("quality_constraints", "TEXT", "Constraints agents must observe."),
            col("dependency_notes", "TEXT", "Ordering or coordination notes."),
        ),
    ),
    "agent_batch_items": TableSchema(
        "agent_batch_items",
        "Document-level task items assigned to batches.",
        (
            col("batch_item_id", "VARCHAR", "Stable batch item identifier."),
            col("batch_id", "VARCHAR", "Batch identifier."),
            col("doc_id", "VARCHAR", "Document identifier."),
            col("item_reason", "TEXT", "Why the document is in the batch."),
            col("item_priority", "INTEGER", "Lower number means higher item priority."),
        ),
    ),
    "agent_shards": TableSchema(
        "agent_shards",
        "Manifest of swarm-safe CSV task shards exported for each batch.",
        (
            col("batch_id", "VARCHAR", "Batch identifier."),
            col("shard_id", "VARCHAR", "Stable shard identifier."),
            col("shard_path", "VARCHAR", "Relative path to the shard CSV."),
            col("row_count", "INTEGER", "Rows in the shard."),
            col("source_view", "VARCHAR", "DuckDB view represented by the batch."),
            col("objective", "TEXT", "Batch objective copied into the shard contract."),
            col("expected_output_shape", "TEXT", "Expected agent output shape."),
            col("quality_constraints", "TEXT", "Agent constraints copied into the shard contract."),
        ),
    ),
    "ingest_errors": TableSchema(
        "ingest_errors",
        "Non-empty parse and ingestion errors captured during catalog build.",
        (
            col("doc_id", "VARCHAR", "Document identifier."),
            col("rel_path", "VARCHAR", "Relative document path."),
            col("stage", "VARCHAR", "Stage that emitted the error."),
            col("error", "TEXT", "Error details."),
        ),
    ),
    "catalog_notes": TableSchema(
        "catalog_notes",
        "Catalog invariants and operational notes for humans and agents.",
        (
            col("note_id", "VARCHAR", "Stable note identifier."),
            col("note_kind", "VARCHAR", "Invariant, workflow, or trust note kind."),
            col("subject", "VARCHAR", "Subject of the note."),
            col("description", "TEXT", "Human-readable note."),
        ),
    ),
    "build_events": TableSchema(
        "build_events",
        "Structured build log events emitted by the catalog generator.",
        (
            col("event_id", "VARCHAR", "Stable event identifier within the build."),
            col("stage", "VARCHAR", "Build stage."),
            col("level", "VARCHAR", "Log level."),
            col("message", "TEXT", "Event message."),
            col("metric_name", "VARCHAR", "Optional metric name."),
            col("metric_value", "VARCHAR", "Optional metric value."),
        ),
    ),
}


TOPIC_TERMS: dict[str, list[str]] = {
    "silmaril_core": [
        "silmaril",
        "graphatlas",
        "avogadro",
        "bashattack",
        "pybrain",
        "cassander",
        "monolith",
        "existence tree",
    ],
    "category_ontology": [
        "yoneda",
        "category",
        "categorical",
        "sheaf",
        "olog",
        "functor",
        "monad",
        "colimit",
        "rdf",
        "owl",
        "shacl",
        "linkml",
        "ontology",
    ],
    "data_governance": [
        "ranger",
        "atlas",
        "gravitino",
        "governance",
        "lineage",
        "authorization",
        "policy",
        "metadata",
    ],
    "streaming_lakehouse": [
        "kafka",
        "storm",
        "hudi",
        "ozone",
        "hdfs",
        "iceberg",
        "flink",
        "spark",
        "solr",
        "lakehouse",
    ],
    "geospatial": [
        "sedona",
        "geospatial",
        "spatial",
        "tiger",
        "census",
        "geoparquet",
        "geometry",
    ],
    "infra_ops": [
        "debian",
        "podman",
        "quadlet",
        "kerberos",
        "spnego",
        "slurm",
        "airflow",
        "guix",
        "mahout",
        "nutt",
        "nginx",
        "systemd",
    ],
    "ai_ml": [
        " ai ",
        "lora",
        "moe",
        "inference",
        "fine-tuning",
        "llm",
        "rocm",
        "cuda",
        "jepa",
        "vector",
        "embedding",
    ],
    "politics_society": [
        "usaid",
        "patriarchy",
        "feminist",
        "gender",
        "playboy",
        "minx",
        "capitalism",
        "palantir",
        "foreign aid",
    ],
    "pdf_extraction": [
        "tika",
        "tabula",
        "pdfbox",
        "ocr",
        "pdf",
        "table extraction",
    ],
    "economics_market": [
        "ibm",
        "intel",
        "amd",
        "valuation",
        "demand",
        "market",
        "capital",
        "revenue",
    ],
    "pybrain_herodotus": [
        "herodotus",
        "observation",
        "trifecta",
        "avroprojection",
        "recordedobservation",
        "witness",
    ],
    "uefi_isa_kernel": [
        "uefi",
        "riscv",
        "x86",
        "arm",
        "kernel",
        "io_uring",
        "syscall",
        "isa",
    ],
}

GAP_PATTERNS = [
    "gap",
    "limitation",
    "not supported",
    "no official",
    "proof-of-concept",
    "fragile",
    "insecure",
    "aspirational",
    "not battle-tested",
    "todo",
    "workaround",
    "contradict",
    "unsupported",
    "unverified",
    "must verify",
    "cannot validate",
]

CLAIM_CUES = [
    "central claim",
    "must",
    "should",
    "requires",
    "provides",
    "enforces",
    "is ",
    "are ",
    "will ",
    "can ",
    "not supported",
    "no official",
    "proof-of-concept",
    "fragile",
    "aspirational",
]


@dataclass
class Document:
    doc_id: str
    abs_path: Path
    rel_path: str
    filename: str
    dir1: str
    dir2: str
    extension: str
    size_bytes: int
    mtime_ns: int
    sha256: str
    hash_status: str
    source_label: str
    canonical_status: str
    ingest_status: str = "not_attempted"
    text_cache_path: str = ""
    title: str = ""
    detected_title: str = ""
    pdf_pages: str = ""
    word_count: int = 0
    line_count: int = 0
    file_kind: str = ""
    parse_status: str = "not_parsed"
    parse_error: str = ""


class BuildRecorder:
    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []

    def emit(self, stage: str, level: str, message: str, metric_name: str = "", metric_value: Any = "") -> None:
        row = {
            "event_id": f"event_{len(self.rows) + 1:04d}",
            "stage": stage,
            "level": level.upper(),
            "message": message,
            "metric_name": metric_name,
            "metric_value": "" if metric_value == "" else str(metric_value),
        }
        self.rows.append(row)
        log_fn = getattr(LOGGER, level.lower(), LOGGER.info)
        metric = f" {metric_name}={metric_value}" if metric_name else ""
        log_fn("%s: %s%s", stage, message, metric)

    def write_log(self) -> None:
        lines = [
            f"{row['event_id']} {row['level']} {row['stage']} {row['message']}"
            + (f" {row['metric_name']}={row['metric_value']}" if row["metric_name"] else "")
            for row in self.rows
        ]
        ACTIVE_PATHS.build_log_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def rel(path: Path) -> str:
    return path.resolve().relative_to(ROOT).as_posix()


def stable_doc_id(rel_path: str) -> str:
    return f"doc_{hashlib.sha1(rel_path.encode('utf-8')).hexdigest()}"


def set_active_paths(paths: BuildPaths) -> None:
    global ACTIVE_PATHS
    ACTIVE_PATHS = paths


def make_stage_paths() -> BuildPaths:
    stage_root = BUILD_TMP_DIR / f"run_{os.getpid()}"
    return BuildPaths(
        db_path=stage_root / "library.duckdb",
        table_dir=stage_root / "tables",
        text_dir=stage_root / "text",
        pdf_text_dir=stage_root / "text" / "pdf",
        agent_shard_dir=stage_root / "agent_shards",
        sql_path=stage_root / "load_catalog.sql",
        manifest_path=stage_root / "manifest.json",
        build_log_path=stage_root / "build.log",
        query_dir=stage_root / "library_queries",
        catalog_pdf_text_dir=FINAL_PATHS.pdf_text_dir,
        catalog_agent_shard_dir=FINAL_PATHS.agent_shard_dir,
    )


def prepare_cache(recorder: BuildRecorder) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    if BUILD_TMP_DIR.exists():
        shutil.rmtree(BUILD_TMP_DIR)
    for generated_dir in (
        ACTIVE_PATHS.table_dir,
        ACTIVE_PATHS.text_dir,
        ACTIVE_PATHS.pdf_text_dir,
        ACTIVE_PATHS.agent_shard_dir,
        ACTIVE_PATHS.query_dir,
    ):
        generated_dir.mkdir(parents=True, exist_ok=True)
    recorder.emit("prepare", "info", "Prepared staged generated cache directories.", "stage_root", rel(ACTIVE_PATHS.table_dir.parent))


def iter_files() -> list[Path]:
    files: list[Path] = []
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        parts = set(path.relative_to(ROOT).parts)
        if parts & SKIP_DIRS:
            continue
        if path.name in SKIP_FILES:
            continue
        files.append(path)
    return sorted(files, key=lambda item: item.relative_to(ROOT).as_posix())


def normalized_extension(path: Path) -> str:
    if path.name.endswith(".fdb_latexmk"):
        return ".fdb_latexmk"
    if path.name.endswith(".synctex.gz"):
        return ".gz"
    return path.suffix.lower()


def sha256_file(path: Path, size: int) -> tuple[str, str]:
    if size > MAX_HASH_BYTES:
        return "", "skipped_too_large"
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest(), "ok"
    except OSError as exc:
        return "", f"error:{exc}"


def source_label_for(path: Path, size: int, ext: str) -> tuple[str, str]:
    parts = path.relative_to(ROOT).parts
    dir1 = parts[0] if parts else ""
    rel_path = path.relative_to(ROOT).as_posix()

    if dir1 in {"library_scripts", "library_queries"}:
        return "librarian_artifact", "tooling_artifact"
    if path.name == ".vscode-ctags" or size > 200 * 1024 * 1024:
        return "noise_index_artifact", "not_canonical"
    if ext == ".gz" or ext in BUILD_EXTS:
        return "build_artifact", "not_canonical"
    if dir1 == "actual":
        return "render_attempt", "render_lineage"
    if dir1 == "working":
        return "static_projection", "current_static_projection"
    if dir1 == "research":
        return "primary_spec", "candidate_primary"
    if dir1 == "md":
        return "generated_report_text", "generated_report"
    if dir1 == "pdf":
        if ext == ".pdf":
            return "generated_report_pdf", "generated_report"
        if ext in TEXT_EXTS:
            return "generated_report_sidecar", "generated_report"
        return "uncategorized_pdf_dir_file", "unknown"
    if rel_path == "SILMARIL_ARCHITECTURE.md":
        return "primary_architecture", "candidate_primary"
    if rel_path in {"Silmaril_Whitepaper.pdf", "Silmaril_Architecture_Whitepaper.pdf"}:
        return "static_whitepaper_pdf", "static_projection"
    return "uncategorized_local_file", "unknown"


def file_kind(ext: str, label: str) -> str:
    if label == "noise_index_artifact":
        return "noise"
    if label == "build_artifact":
        return "build"
    if ext == ".pdf":
        return "pdf"
    if ext in {".yaml", ".yml"}:
        return "yaml"
    if ext == ".avsc":
        return "avro_schema"
    if ext == ".ttl":
        return "turtle"
    if ext == ".tex":
        return "latex"
    if ext == ".md":
        return "markdown_source"
    if ext == ".bib":
        return "bibtex"
    return ext.lstrip(".") or "unknown"


def run_capture(cmd: list[str]) -> tuple[int, str, str]:
    try:
        proc = subprocess.run(cmd, check=False, capture_output=True, text=True)
        return proc.returncode, proc.stdout, proc.stderr
    except FileNotFoundError as exc:
        return 127, "", str(exc)


def pdfinfo(path: Path) -> dict[str, str]:
    code, stdout, stderr = run_capture(["pdfinfo", str(path)])
    if code != 0:
        return {"_error": stderr.strip()}
    result: dict[str, str] = {}
    for line in stdout.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        result[key.strip()] = value.strip()
    return result


def extract_pdf_text(doc: Document) -> str:
    cache_name = f"{doc.doc_id}_{safe_cache_name(doc.filename)}.txt"
    cache_path = ACTIVE_PATHS.pdf_text_dir / cache_name
    code, _, stderr = run_capture(["pdftotext", str(doc.abs_path), str(cache_path)])
    if code != 0:
        doc.ingest_status = "pdf_text_error"
        doc.parse_error = stderr.strip()
        return ""
    try:
        text = cache_path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        doc.ingest_status = "pdf_text_read_error"
        doc.parse_error = str(exc)
        return ""
    doc.text_cache_path = rel(ACTIVE_PATHS.catalog_pdf_text_dir / cache_name)
    if normalize_text(text):
        doc.ingest_status = "text_ingested"
    else:
        doc.ingest_status = "pdf_no_text"
    return text


def safe_cache_name(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", name)[:120]


def read_text_file(path: Path, size: int) -> tuple[str, str, str]:
    if size > MAX_TEXT_BYTES:
        return "", "skipped_too_large", ""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return "", "text_read_error", str(exc)
    if size == 0 or not normalize_text(text):
        return "", "empty_file", ""
    return text, "text_ingested", ""


def title_from_text(ext: str, text: str) -> str:
    if not text:
        return ""
    if ext == ".md":
        for line in text.splitlines()[:80]:
            match = re.match(r"^\s*#\s+(.+?)\s*$", line)
            if match:
                return clean_title(match.group(1))
    if ext == ".tex":
        match = re.search(r"\\title\{(.{1,240})", text, re.S)
        if match:
            return clean_title(match.group(1))
        match = re.search(r"\\(?:section|chapter)\{(.{1,180}?)\}", text, re.S)
        if match:
            return clean_title(match.group(1))
    if ext in {".yaml", ".yml"}:
        try:
            data = yaml.safe_load(text)
            if isinstance(data, dict):
                entity = data.get("entity")
                for obj in (entity, data):
                    if isinstance(obj, dict):
                        for key in ("title", "name", "display_name", "id"):
                            value = obj.get(key)
                            if isinstance(value, str) and value.strip():
                                return clean_title(value)
        except Exception:
            return ""
    if ext in {".json", ".avsc"}:
        try:
            data = json.loads(text)
            if isinstance(data, dict):
                for key in ("title", "name", "namespace"):
                    value = data.get(key)
                    if isinstance(value, str) and value.strip():
                        return clean_title(value)
        except Exception:
            return ""
    return ""


def clean_title(value: str) -> str:
    value = re.sub(r"\\[A-Za-z]+\*?(?:\[[^\]]*\])?\{?", "", value)
    value = value.replace("}", " ")
    value = re.sub(r"\s+", " ", value)
    return value.strip(" -\t\n\r")[:300]


def parse_yaml_metadata(text: str) -> tuple[dict[str, str], str, str]:
    if not text:
        return {}, "not_parsed", ""
    try:
        data = yaml.safe_load(text)
    except Exception as exc:
        return {}, "yaml_error", str(exc)
    if not isinstance(data, dict):
        return {}, "yaml_non_object", ""
    entity = data.get("entity") if isinstance(data.get("entity"), dict) else {}
    meta: dict[str, str] = {}
    for key in (
        "urn",
        "display_name",
        "name",
        "title",
        "layer",
        "kind",
        "kind_urn",
        "type_node",
        "type_urn",
        "source_path",
        "locator",
        "description",
        "spec_version",
        "version",
    ):
        value = entity.get(key, data.get(key))
        if isinstance(value, (str, int, float)):
            meta[key] = str(value)
    if isinstance(entity.get("content"), str):
        meta["entity_content"] = entity["content"]
    return meta, "yaml_ok", ""


def split_units(doc: Document, text: str, yaml_meta: dict[str, str]) -> list[dict[str, Any]]:
    if not text:
        return []
    if doc.extension == ".pdf":
        return split_pdf_pages(doc, text)
    if doc.extension == ".md":
        return split_by_markdown_heading(doc, text)
    if doc.extension == ".tex":
        return split_by_tex_heading(doc, text)
    if doc.extension in {".yaml", ".yml"} and yaml_meta.get("entity_content"):
        return chunk_plain(doc, yaml_meta["entity_content"], "yaml_entity_content")
    return chunk_plain(doc, text, "file_text")


def split_pdf_pages(doc: Document, text: str) -> list[dict[str, Any]]:
    units: list[dict[str, Any]] = []
    for page_index, page in enumerate(text.split("\f"), start=1):
        page = normalize_text(page)
        if not page:
            continue
        for chunk_index, chunk in enumerate(chunk_text(page), start=1):
            units.append(
                make_unit(
                    doc,
                    len(units) + 1,
                    "pdf_page",
                    f"page {page_index}",
                    chunk,
                    f"page:{page_index}:chunk:{chunk_index}",
                )
            )
    return units


def split_by_markdown_heading(doc: Document, text: str) -> list[dict[str, Any]]:
    sections: list[tuple[str, list[str]]] = []
    current_heading = "front_matter"
    current_lines: list[str] = []
    for line in text.splitlines():
        match = re.match(r"^\s{0,3}(#{1,3})\s+(.+?)\s*$", line)
        if match and current_lines:
            sections.append((current_heading, current_lines))
            current_heading = clean_title(match.group(2))
            current_lines = [line]
        elif match:
            current_heading = clean_title(match.group(2))
            current_lines = [line]
        else:
            current_lines.append(line)
    if current_lines:
        sections.append((current_heading, current_lines))
    return split_sections(doc, sections, "markdown_section")


def split_by_tex_heading(doc: Document, text: str) -> list[dict[str, Any]]:
    marker = re.compile(r"^\s*\\(section|subsection|chapter)\*?\{(.+?)\}\s*$")
    sections: list[tuple[str, list[str]]] = []
    current_heading = "front_matter"
    current_lines: list[str] = []
    for line in text.splitlines():
        match = marker.match(line)
        if match and current_lines:
            sections.append((current_heading, current_lines))
            current_heading = clean_title(match.group(2))
            current_lines = [line]
        elif match:
            current_heading = clean_title(match.group(2))
            current_lines = [line]
        else:
            current_lines.append(line)
    if current_lines:
        sections.append((current_heading, current_lines))
    return split_sections(doc, sections, "tex_section")


def split_sections(doc: Document, sections: list[tuple[str, list[str]]], kind: str) -> list[dict[str, Any]]:
    units: list[dict[str, Any]] = []
    for heading, lines in sections:
        section_text = normalize_text("\n".join(lines))
        if not section_text:
            continue
        for chunk_index, chunk in enumerate(chunk_text(section_text), start=1):
            units.append(
                make_unit(
                    doc,
                    len(units) + 1,
                    kind,
                    heading,
                    chunk,
                    f"section:{heading}:chunk:{chunk_index}",
                )
            )
    return units


def chunk_plain(doc: Document, text: str, kind: str) -> list[dict[str, Any]]:
    text = normalize_text(text)
    if not text:
        return []
    return [
        make_unit(doc, index, kind, kind, chunk, f"chunk:{index}")
        for index, chunk in enumerate(chunk_text(text), start=1)
    ]


def chunk_text(text: str) -> list[str]:
    if len(text) <= MAX_UNIT_CHARS:
        return [text]
    chunks: list[str] = []
    paragraphs = re.split(r"\n{2,}", text)
    current = ""
    for paragraph in paragraphs:
        if len(current) + len(paragraph) + 2 <= MAX_UNIT_CHARS:
            current = f"{current}\n\n{paragraph}".strip()
            continue
        if current:
            chunks.append(current)
        if len(paragraph) <= MAX_UNIT_CHARS:
            current = paragraph
        else:
            for start in range(0, len(paragraph), MAX_UNIT_CHARS):
                chunks.append(paragraph[start : start + MAX_UNIT_CHARS])
            current = ""
    if current:
        chunks.append(current)
    return chunks


def normalize_text(text: str) -> str:
    text = text.replace("\x00", " ")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{4,}", "\n\n\n", text)
    return text.strip()


def make_unit(doc: Document, index: int, kind: str, heading: str, text: str, locator: str) -> dict[str, Any]:
    return {
        "unit_id": f"{doc.doc_id}_u{index:04d}",
        "doc_id": doc.doc_id,
        "unit_index": index,
        "unit_kind": kind,
        "heading": heading[:300],
        "source_locator": locator[:500],
        "word_count": count_words(text),
        "char_count": len(text),
        "text": text,
    }


def count_words(text: str) -> int:
    return len(re.findall(r"\b[\w'-]+\b", text))


def detect_topics(doc: Document, text: str) -> list[dict[str, Any]]:
    haystack = f"{doc.rel_path}\n{doc.title}\n{text[:250000]}".lower()
    rows: list[dict[str, Any]] = []
    for topic, terms in TOPIC_TERMS.items():
        counts: Counter[str] = Counter()
        for term in terms:
            term_lower = term.lower()
            if term_lower.strip() != term_lower:
                count = haystack.count(term_lower)
            else:
                count = len(re.findall(rf"\b{re.escape(term_lower)}\b", haystack))
            if count:
                counts[term.strip()] = count
        score = sum(counts.values())
        if score:
            rows.append(
                {
                    "doc_id": doc.doc_id,
                    "topic": topic,
                    "score": score,
                    "matched_terms": "; ".join(f"{term}:{count}" for term, count in counts.most_common(12)),
                }
            )
    return rows


def extract_gap_rows(doc: Document, text: str) -> list[dict[str, Any]]:
    if not text:
        return []
    rows: list[dict[str, Any]] = []
    for line_no, line in enumerate(iter_sentences_and_lines(text), start=1):
        low = line.lower()
        matched = [pattern for pattern in GAP_PATTERNS if pattern in low]
        if not matched:
            continue
        rows.append(
            {
                "gap_id": f"{doc.doc_id}_g{len(rows) + 1:03d}",
                "doc_id": doc.doc_id,
                "category": "gap_or_limitation",
                "severity": gap_severity(low),
                "gap_text": line[:2000],
                "source_locator": f"line_or_sentence:{line_no}",
                "matched_terms": "; ".join(matched[:8]),
            }
        )
        if len(rows) >= MAX_GAPS_PER_DOC:
            break
    return rows


def extract_claim_rows(doc: Document, text: str) -> list[dict[str, Any]]:
    if not text or doc.source_label in {"build_artifact", "noise_index_artifact"}:
        return []
    rows: list[dict[str, Any]] = []
    for line_no, line in enumerate(iter_sentences_and_lines(text), start=1):
        if len(line) < 60:
            continue
        low = line.lower()
        if not any(cue in low for cue in CLAIM_CUES):
            continue
        rows.append(
            {
                "claim_id": f"{doc.doc_id}_c{len(rows) + 1:03d}",
                "doc_id": doc.doc_id,
                "claim_text": line[:2400],
                "source_locator": f"line_or_sentence:{line_no}",
                "trust_state": "needs_external_verification"
                if needs_external_verification(doc, line)
                else "local_corpus_claim",
                "claim_type": claim_type(low),
                "evidence_hint": evidence_hint(doc, line),
            }
        )
        if len(rows) >= MAX_CLAIMS_PER_DOC:
            break
    return rows


def iter_sentences_and_lines(text: str) -> list[str]:
    candidates: list[str] = []
    for raw in text.splitlines():
        line = re.sub(r"\s+", " ", raw).strip()
        if not line:
            continue
        if len(line) > 350:
            candidates.extend(re.split(r"(?<=[.!?])\s+(?=[A-Z0-9])", line))
        else:
            candidates.append(line)
    cleaned = []
    for candidate in candidates:
        candidate = candidate.strip(" -\t")
        if 20 <= len(candidate) <= 2500:
            cleaned.append(candidate)
    return cleaned


def needs_external_verification(doc: Document, line: str) -> bool:
    if doc.source_label in {
        "generated_report_pdf",
        "generated_report_text",
        "generated_report_sidecar",
        "static_whitepaper_pdf",
    }:
        return True
    low = line.lower()
    if any(token in low for token in ("latest", "current", "2025", "2026", "record", "valuation", "gartner")):
        return True
    if re.search(r"\b\d+(?:\.\d+)?\s*(?:%|million|billion|trillion|x)\b", low):
        return True
    return False


def claim_type(low: str) -> str:
    if any(term in low for term in ("not supported", "no official", "fragile", "aspirational", "gap", "limitation")):
        return "risk_or_gap_claim"
    if any(term in low for term in ("must", "requires", "enforces")):
        return "normative_or_contract_claim"
    if any(term in low for term in ("2025", "2026", "%", "million", "billion", "trillion")):
        return "current_fact_or_metric"
    return "descriptive_claim"


def gap_severity(low: str) -> str:
    if any(term in low for term in ("fragile", "insecure", "not supported", "no official", "not battle-tested")):
        return "high"
    if any(term in low for term in ("limitation", "gap", "workaround", "unsupported")):
        return "medium"
    return "low"


def evidence_hint(doc: Document, line: str) -> str:
    if "[Source]" in line or "http" in line or "arxiv" in line.lower() or "doi" in line.lower():
        return "has_inline_source_marker"
    if doc.source_label.startswith("primary"):
        return "primary_local_spec"
    return "local_text_only"


def quality_flags_for(doc: Document, text: str, yaml_meta: dict[str, str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if doc.source_label in {
        "generated_report_pdf",
        "generated_report_text",
        "generated_report_sidecar",
        "static_whitepaper_pdf",
    }:
        rows.append(
            flag(
                doc,
                "externally_unverified_report",
                "medium",
                "Generated/report-like material needs source verification for external facts.",
            )
        )
    if doc.ingest_status == "empty_file":
        rows.append(flag(doc, "empty_file_no_text", "low", "Text file is zero bytes or normalizes to empty text."))
    if doc.source_label == "render_attempt":
        rows.append(
            flag(
                doc,
                "render_lineage_not_canonical",
                "medium",
                "Render lineage artifact; reconcile before citing as canonical.",
            )
        )
    if doc.source_label == "build_artifact":
        rows.append(flag(doc, "build_artifact_noise", "low", "Build output is cataloged but not treated as source evidence."))
    if doc.source_label == "noise_index_artifact":
        rows.append(flag(doc, "noise_or_index_artifact", "high", "Large/noisy index artifact is not text-ingested."))
    if doc.parse_status == "yaml_error":
        rows.append(flag(doc, "malformed_yaml", "high", doc.parse_error[:1000]))
    if doc.ingest_status.endswith("error"):
        rows.append(flag(doc, "text_ingest_error", "medium", doc.parse_error[:1000]))
    if doc.source_label != "librarian_artifact" and ("$ENV_" in text or "$HOME/" in text):
        rows.append(
            flag(
                doc,
                "environment_path_reference",
                "medium",
                "Contains environment-relative source paths that may need reconciliation.",
            )
        )
    if doc.source_label != "librarian_artifact" and any(pattern in text.lower() for pattern in GAP_PATTERNS):
        rows.append(
            flag(
                doc,
                "contains_gap_or_limitation_language",
                "medium",
                "Document includes gap/limitation/unsupported language.",
            )
        )
    if yaml_meta.get("source_path", "").startswith("$ENV_"):
        rows.append(flag(doc, "source_path_outside_pwd_or_env", "medium", yaml_meta["source_path"][:1000]))
    return rows


def flag(doc: Document, name: str, severity: str, reason: str) -> dict[str, str]:
    return {
        "flag_id": f"{doc.doc_id}_{name}",
        "doc_id": doc.doc_id,
        "flag": name,
        "severity": severity,
        "reason": reason,
    }


def build_documents(files: list[Path], recorder: BuildRecorder) -> dict[str, list[dict[str, Any]] | list[Document]]:
    documents: list[Document] = []
    units: list[dict[str, Any]] = []
    topics: list[dict[str, Any]] = []
    yaml_rows: list[dict[str, Any]] = []
    flags: list[dict[str, Any]] = []
    claims: list[dict[str, Any]] = []
    gaps: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    for path in files:
        rel_path = path.relative_to(ROOT).as_posix()
        try:
            stat = path.stat()
        except FileNotFoundError as exc:
            errors.append(
                {
                    "doc_id": stable_doc_id(rel_path),
                    "rel_path": rel_path,
                    "stage": "scan_stat",
                    "error": str(exc)[:2000],
                }
            )
            recorder.emit("scan", "warning", "Skipped file that disappeared after scan.", "rel_path", rel_path)
            continue
        ext = normalized_extension(path)
        label, canonical = source_label_for(path, stat.st_size, ext)
        parts = path.relative_to(ROOT).parts
        doc = Document(
            doc_id=stable_doc_id(rel_path),
            abs_path=path,
            rel_path=rel_path,
            filename=path.name,
            dir1=parts[0] if len(parts) > 0 else "",
            dir2=parts[1] if len(parts) > 1 else "",
            extension=ext,
            size_bytes=stat.st_size,
            mtime_ns=stat.st_mtime_ns,
            sha256="",
            hash_status="not_attempted",
            source_label=label,
            canonical_status=canonical,
            file_kind=file_kind(ext, label),
        )
        doc.sha256, doc.hash_status = sha256_file(path, stat.st_size)

        text = ""
        yaml_meta: dict[str, str] = {}
        if ext == ".pdf" and label != "noise_index_artifact":
            info = pdfinfo(path)
            doc.pdf_pages = info.get("Pages", "")
            doc.detected_title = info.get("Title", "")
            text = extract_pdf_text(doc)
            doc.title = clean_title(doc.detected_title) or path.stem
            doc.parse_status = "pdf_ok" if normalize_text(text) else doc.ingest_status
        elif ext in TEXT_EXTS and label not in {"build_artifact", "noise_index_artifact"}:
            text, doc.ingest_status, read_error = read_text_file(path, stat.st_size)
            doc.parse_error = read_error
            doc.title = path.stem
            if doc.ingest_status == "empty_file":
                doc.parse_status = "empty_file"
            else:
                doc.detected_title = title_from_text(ext, text)
                doc.title = doc.detected_title or path.stem
                if ext in {".yaml", ".yml"}:
                    yaml_meta, doc.parse_status, yaml_error = parse_yaml_metadata(text)
                    doc.parse_error = yaml_error or doc.parse_error
                    yaml_rows.append(yaml_metadata_row(doc.doc_id, yaml_meta))
                    if yaml_meta.get("name") and not doc.title:
                        doc.title = yaml_meta["name"]
                else:
                    doc.parse_status = "text_ok" if text else doc.ingest_status
        else:
            doc.ingest_status = "skipped"
            doc.title = path.stem
            doc.parse_status = "not_parsed"

        doc.word_count = count_words(text)
        doc.line_count = text.count("\n") + 1 if text else 0

        if doc.source_label != "librarian_artifact":
            units.extend(split_units(doc, text, yaml_meta))
            topics.extend(detect_topics(doc, text))
            claims.extend(extract_claim_rows(doc, text))
            gaps.extend(extract_gap_rows(doc, text))
        flags.extend(quality_flags_for(doc, text, yaml_meta))
        if doc.parse_error:
            errors.append(
                {
                    "doc_id": doc.doc_id,
                    "rel_path": doc.rel_path,
                    "stage": doc.parse_status,
                    "error": doc.parse_error[:2000],
                }
            )
        documents.append(doc)

    recorder.emit("ingest", "info", "Cataloged filesystem artifacts.", "documents", len(documents))
    recorder.emit("ingest", "info", "Extracted text units.", "text_units", len(units))
    return {
        "documents": documents,
        "document_text_units": units,
        "document_topics": topics,
        "yaml_metadata": yaml_rows,
        "quality_flags": flags,
        "claims": claims,
        "gaps": gaps,
        "ingest_errors": errors,
    }


def yaml_metadata_row(doc_id: str, yaml_meta: dict[str, str]) -> dict[str, Any]:
    return {
        "doc_id": doc_id,
        "urn": yaml_meta.get("urn", ""),
        "display_name": yaml_meta.get("display_name", ""),
        "name": yaml_meta.get("name", ""),
        "title": yaml_meta.get("title", ""),
        "layer": yaml_meta.get("layer", ""),
        "kind": yaml_meta.get("kind", ""),
        "kind_urn": yaml_meta.get("kind_urn", ""),
        "type_node": yaml_meta.get("type_node", ""),
        "type_urn": yaml_meta.get("type_urn", ""),
        "source_path": yaml_meta.get("source_path", ""),
        "locator": yaml_meta.get("locator", ""),
        "spec_version": yaml_meta.get("spec_version", ""),
        "version": yaml_meta.get("version", ""),
        "description": yaml_meta.get("description", ""),
    }


def document_rows(documents: list[Document]) -> list[dict[str, Any]]:
    return [
        {
            "doc_id": doc.doc_id,
            "abs_path": doc.abs_path.as_posix(),
            "rel_path": doc.rel_path,
            "filename": doc.filename,
            "dir1": doc.dir1,
            "dir2": doc.dir2,
            "extension": doc.extension,
            "size_bytes": doc.size_bytes,
            "mtime_ns": doc.mtime_ns,
            "sha256": doc.sha256,
            "hash_status": doc.hash_status,
            "source_label": doc.source_label,
            "canonical_status": doc.canonical_status,
            "ingest_status": doc.ingest_status,
            "text_cache_path": doc.text_cache_path,
            "title": doc.title,
            "detected_title": doc.detected_title,
            "pdf_pages": doc.pdf_pages,
            "word_count": doc.word_count,
            "line_count": doc.line_count,
            "file_kind": doc.file_kind,
            "parse_status": doc.parse_status,
            "parse_error": doc.parse_error,
        }
        for doc in documents
    ]


def duplicate_groups(documents: list[Document], flags: list[dict[str, Any]], recorder: BuildRecorder) -> tuple[list[dict[str, Any]], set[str]]:
    groups: list[dict[str, Any]] = []
    duplicate_docs: set[str] = set()
    hashes: dict[str, list[Document]] = defaultdict(list)
    for doc in documents:
        if doc.sha256:
            hashes[doc.sha256].append(doc)

    for group_index, (digest, members) in enumerate(
        ((digest, members) for digest, members in sorted(hashes.items(), key=lambda item: (-len(item[1]), item[0])) if len(members) > 1),
        start=1,
    ):
        group_id = f"dup_{group_index:04d}"
        representative = sorted(members, key=lambda doc: doc.rel_path)[0]
        groups.append(
            {
                "group_id": group_id,
                "sha256": digest,
                "member_count": len(members),
                "representative_doc_id": representative.doc_id,
                "group_label": "exact_file_duplicate",
            }
        )
        for doc in members:
            duplicate_docs.add(doc.doc_id)
            flags.append(flag(doc, "exact_file_duplicate", "medium", f"Duplicate member of {group_id}."))

    recorder.emit("dedupe", "info", "Computed exact duplicate groups.", "duplicate_groups", len(groups))
    return groups, duplicate_docs


def agent_batches() -> list[dict[str, Any]]:
    return [
        {
            "batch_id": "B001_source_dedupe",
            "objective": "Collapse duplicate source/export records and identify representative files.",
            "source_view": "v_agent_batch_source_dedupe",
            "priority": 1,
            "expected_output_shape": "rows: group_id, representative_doc_id, duplicate_doc_ids, action",
            "quality_constraints": "Do not delete files; propose representative and lineage only.",
            "dependency_notes": "Run before claim audit so duplicate reports do not inflate evidence.",
        },
        {
            "batch_id": "B002_claim_audit",
            "objective": "Audit high-risk and current-fact claims for external verification needs.",
            "source_view": "v_agent_batch_claim_audit",
            "priority": 2,
            "expected_output_shape": "rows: claim_id, verification_status, source_needed, confidence",
            "quality_constraints": "Separate local claims from externally verified facts.",
            "dependency_notes": "Use dedupe results to avoid checking the same generated report twice.",
        },
        {
            "batch_id": "B003_spec_validation",
            "objective": "Validate primary specs for schema consistency, source paths, and layer/type sanity.",
            "source_view": "v_agent_batch_spec_validation",
            "priority": 2,
            "expected_output_shape": "rows: doc_id, issue_type, severity, proposed_fix",
            "quality_constraints": "Do not mutate specs during audit; record findings only.",
            "dependency_notes": "Prioritize YAML parse errors and environment path reconciliation.",
        },
        {
            "batch_id": "B004_pdf_report_triage",
            "objective": "Classify PDFs into research shelves and mark generated/current-fact risk.",
            "source_view": "v_agent_batch_pdf_report_triage",
            "priority": 3,
            "expected_output_shape": "rows: doc_id, shelf, trust_label, summary_vector",
            "quality_constraints": "Use local text only unless a later task explicitly permits web checks.",
            "dependency_notes": "Can run in parallel with spec validation.",
        },
        {
            "batch_id": "B005_actual_render_lineage",
            "objective": "Audit actual render lineage artifacts across texture files, PDFs, support files, and empty files.",
            "source_view": "v_agent_batch_actual_render_lineage",
            "priority": 2,
            "expected_output_shape": "rows: lineage_group, representative_doc_id, superseded_doc_ids, differences",
            "quality_constraints": "Treat render attempts as non-canonical until reconciled.",
            "dependency_notes": "Feeds static projection and source-map reconciliation.",
        },
        {
            "batch_id": "B006_gap_verification",
            "objective": "Verify and rank local gap/limitation/unsupported statements.",
            "source_view": "v_agent_batch_gap_verification",
            "priority": 2,
            "expected_output_shape": "rows: gap_id, real_blocker, mitigation, verification_need",
            "quality_constraints": "Keep aspirational claims separate from production-ready claims.",
            "dependency_notes": "Pairs with claim audit.",
        },
    ]


def build_agent_items(
    documents: list[Document],
    duplicate_docs: set[str],
    flags: list[dict[str, Any]],
    recorder: BuildRecorder,
) -> list[dict[str, Any]]:
    flags_by_doc: dict[str, set[str]] = defaultdict(set)
    for row in flags:
        flags_by_doc[row["doc_id"]].add(row["flag"])

    items: list[dict[str, Any]] = []
    for doc in documents:
        is_empty = doc.ingest_status == "empty_file"
        is_librarian_artifact = doc.source_label == "librarian_artifact"
        if not is_empty and not is_librarian_artifact and doc.doc_id in duplicate_docs and doc.source_label != "build_artifact":
            items.append(batch_item("B001_source_dedupe", doc, "duplicate hash group member", 1))
        if not is_empty and not is_librarian_artifact and doc.source_label in {
            "generated_report_pdf",
            "generated_report_text",
            "generated_report_sidecar",
            "static_whitepaper_pdf",
        }:
            items.append(batch_item("B002_claim_audit", doc, "generated/current-fact report claim surface", 2))
            if doc.extension == ".pdf":
                items.append(batch_item("B004_pdf_report_triage", doc, "pdf report triage candidate", 3))
        if not is_empty and not is_librarian_artifact and doc.source_label == "primary_spec":
            priority = 1 if flags_by_doc.get(doc.doc_id) else 3
            items.append(batch_item("B003_spec_validation", doc, "primary spec validation candidate", priority))
        if doc.source_label == "render_attempt":
            reason = "actual render lineage empty artifact" if is_empty else "actual render lineage artifact"
            items.append(batch_item("B005_actual_render_lineage", doc, reason, 2))
        if not is_empty and not is_librarian_artifact and "contains_gap_or_limitation_language" in flags_by_doc.get(doc.doc_id, set()):
            items.append(batch_item("B006_gap_verification", doc, "contains gap/limitation language", 2))

    recorder.emit("batches", "info", "Generated agent batch items.", "agent_batch_items", len(items))
    return items


def batch_item(batch_id: str, doc: Document, reason: str, priority: int, local_index: int = 1) -> dict[str, Any]:
    return {
        "batch_item_id": f"{batch_id}_{doc.doc_id}_i{local_index:03d}",
        "batch_id": batch_id,
        "doc_id": doc.doc_id,
        "item_reason": reason,
        "item_priority": priority,
    }


def write_agent_shards(
    batches: list[dict[str, Any]],
    items: list[dict[str, Any]],
    documents: list[Document],
    recorder: BuildRecorder,
    shard_size: int = AGENT_SHARD_SIZE,
) -> list[dict[str, Any]]:
    docs_by_id = {doc.doc_id: doc for doc in documents}
    items_by_batch: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in items:
        items_by_batch[item["batch_id"]].append(item)

    shard_rows_for_manifest: list[dict[str, Any]] = []
    shard_fields = [
        "batch_id",
        "shard_id",
        "item_id",
        "doc_id",
        "rel_path",
        "objective",
        "source_view",
        "expected_output_shape",
        "quality_constraints",
    ]

    for batch in batches:
        batch_id = batch["batch_id"]
        sorted_items = sorted(
            items_by_batch.get(batch_id, []),
            key=lambda item: (
                int(item.get("item_priority") or 999),
                docs_by_id[item["doc_id"]].rel_path if item["doc_id"] in docs_by_id else "",
                item["batch_item_id"],
            ),
        )
        chunks = [sorted_items[start : start + shard_size] for start in range(0, len(sorted_items), shard_size)] or [[]]
        for shard_index, chunk in enumerate(chunks):
            shard_id = f"{batch_id}_shard_{shard_index:03d}"
            shard_path = ACTIVE_PATHS.agent_shard_dir / f"{shard_id}.csv"
            shard_rows = []
            for item in chunk:
                doc = docs_by_id[item["doc_id"]]
                shard_rows.append(
                    {
                        "batch_id": batch_id,
                        "shard_id": shard_id,
                        "item_id": item["batch_item_id"],
                        "doc_id": item["doc_id"],
                        "rel_path": doc.rel_path,
                        "objective": batch["objective"],
                        "source_view": batch["source_view"],
                        "expected_output_shape": batch["expected_output_shape"],
                        "quality_constraints": batch["quality_constraints"],
                    }
                )
            write_csv_file(shard_path, shard_rows, shard_fields)
            shard_rows_for_manifest.append(
                {
                    "batch_id": batch_id,
                    "shard_id": shard_id,
                    "shard_path": rel(ACTIVE_PATHS.catalog_agent_shard_dir / f"{shard_id}.csv"),
                    "row_count": len(shard_rows),
                    "source_view": batch["source_view"],
                    "objective": batch["objective"],
                    "expected_output_shape": batch["expected_output_shape"],
                    "quality_constraints": batch["quality_constraints"],
                }
            )

    write_csv_file(ACTIVE_PATHS.agent_shard_dir / "manifest.csv", shard_rows_for_manifest, SCHEMAS["agent_shards"].fields)
    recorder.emit("shards", "info", "Exported swarm-safe agent shard CSVs.", "agent_shards", len(shard_rows_for_manifest))
    return shard_rows_for_manifest


def catalog_notes() -> list[dict[str, Any]]:
    return [
        {
            "note_id": "note_001",
            "note_kind": "invariant",
            "subject": "stable_document_ids",
            "description": "doc_id is doc_ plus SHA-1 of rel_path; rel_path remains the human locator.",
        },
        {
            "note_id": "note_002",
            "note_kind": "invariant",
            "subject": "document_local_ids",
            "description": "claim_id, gap_id, unit_id, and batch_item_id derive from stable doc_id plus document-local indices.",
        },
        {
            "note_id": "note_003",
            "note_kind": "workflow",
            "subject": "empty_files",
            "description": "Zero-byte or normalized-empty text files are cataloged with ingest_status=empty_file, flagged empty_file_no_text, and excluded from research text batches.",
        },
        {
            "note_id": "note_004",
            "note_kind": "workflow",
            "subject": "actual_render_lineage",
            "description": "B005 covers all render_attempt artifacts under actual/ and exposes roles for texture.tex, support files, PDFs, and empty files.",
        },
        {
            "note_id": "note_005",
            "note_kind": "trust",
            "subject": "externally_unverified_reports",
            "description": "generated_report_pdf, generated_report_text, generated_report_sidecar, and static_whitepaper_pdf receive externally_unverified_report.",
        },
        {
            "note_id": "note_006",
            "note_kind": "workflow",
            "subject": "swarm_access",
            "description": "Parallel agents should read library_cache/agent_shards/*.csv instead of opening library.duckdb concurrently.",
        },
        {
            "note_id": "note_007",
            "note_kind": "invariant",
            "subject": "librarian_artifacts",
            "description": "Librarian tooling is cataloged for inventory and provenance, but it is not treated as research evidence and produces no text units, topics, claims, gaps, or batch items.",
        },
    ]


def write_csv_file(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})
    return path


def write_table_csv(table_name: str, rows: list[dict[str, Any]]) -> Path:
    return write_csv_file(ACTIVE_PATHS.table_dir / f"{table_name}.csv", rows, SCHEMAS[table_name].fields)


def sql_ident(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def csv_sql_path(path: Path) -> str:
    return path.as_posix().replace("'", "''")


def build_sql(csv_paths: dict[str, Path]) -> str:
    statements = ["PRAGMA threads=4;"]
    for table_name, schema in SCHEMAS.items():
        path = csv_paths[table_name]
        column_defs = ",\n  ".join(f"{sql_ident(column.name)} {column.sql_type}" for column in schema.columns)
        select_exprs = ",\n  ".join(csv_cast_expr(column) for column in schema.columns)
        statements.append(
            f"""
CREATE OR REPLACE TABLE {sql_ident(table_name)} (
  {column_defs}
);

COMMENT ON TABLE {sql_ident(table_name)} IS {sql_literal(schema.description)};
{column_comments_sql(schema)}

INSERT INTO {sql_ident(table_name)}
SELECT
  {select_exprs}
FROM read_csv('{csv_sql_path(path)}', header=true, all_varchar=true, sample_size=-1) AS csv_source;
"""
        )
    statements.append(VIEWS_SQL)
    return "\n".join(statements)


def csv_cast_expr(column: ColumnSchema) -> str:
    name = sql_ident(column.name)
    if column.sql_type in NUMERIC_TYPES:
        return f"TRY_CAST(NULLIF(csv_source.{name}, '') AS {column.sql_type}) AS {name}"
    return f"COALESCE(csv_source.{name}, '') AS {name}"


def column_comments_sql(schema: TableSchema) -> str:
    return "\n".join(
        f"COMMENT ON COLUMN {sql_ident(schema.name)}.{sql_ident(column.name)} IS {sql_literal(column.description)};"
        for column in schema.columns
    )


VIEWS_SQL = r"""
CREATE OR REPLACE VIEW v_documents AS
SELECT
  documents_catalog.doc_id AS doc_id,
  documents_catalog.rel_path AS rel_path,
  documents_catalog.filename AS filename,
  documents_catalog.dir1 AS dir1,
  documents_catalog.dir2 AS dir2,
  documents_catalog.extension AS extension,
  documents_catalog.size_bytes AS size_bytes,
  documents_catalog.source_label AS source_label,
  documents_catalog.canonical_status AS canonical_status,
  documents_catalog.ingest_status AS ingest_status,
  documents_catalog.title AS title,
  documents_catalog.detected_title AS detected_title,
  documents_catalog.pdf_pages AS pdf_pages,
  documents_catalog.word_count AS word_count,
  documents_catalog.line_count AS line_count,
  documents_catalog.file_kind AS file_kind,
  documents_catalog.parse_status AS parse_status,
  documents_catalog.text_cache_path AS text_cache_path,
  documents_catalog.sha256 AS sha256,
  documents_catalog.hash_status AS hash_status
FROM documents AS documents_catalog;

COMMENT ON VIEW v_documents IS 'Typed document inventory view for common catalog queries.';

CREATE OR REPLACE VIEW v_document_inventory AS
SELECT
  documents_catalog.dir1 AS dir1,
  documents_catalog.source_label AS source_label,
  documents_catalog.file_kind AS file_kind,
  COUNT(documents_catalog.doc_id) AS files,
  SUM(documents_catalog.size_bytes) AS bytes,
  SUM(documents_catalog.word_count) AS words
FROM documents AS documents_catalog
GROUP BY
  documents_catalog.dir1,
  documents_catalog.source_label,
  documents_catalog.file_kind
ORDER BY
  bytes DESC,
  files DESC;

COMMENT ON VIEW v_document_inventory IS 'Rollup of file counts, bytes, and words by directory/source/kind.';

CREATE OR REPLACE VIEW v_agent_batch_source_dedupe AS
WITH filtered AS (
  SELECT
    duplicate_groups_catalog.group_id AS group_id,
    duplicate_groups_catalog.group_label AS group_label,
    documents_catalog.doc_id AS doc_id,
    documents_catalog.rel_path AS rel_path,
    documents_catalog.source_label AS source_label,
    documents_catalog.title AS title,
    documents_catalog.sha256 AS sha256
  FROM duplicate_groups AS duplicate_groups_catalog
  JOIN documents AS documents_catalog
    ON documents_catalog.sha256 = duplicate_groups_catalog.sha256
  WHERE documents_catalog.source_label NOT IN ('build_artifact', 'librarian_artifact')
    AND documents_catalog.ingest_status <> 'empty_file'
),
ranked AS (
  SELECT
    filtered.group_id AS group_id,
    filtered.group_label AS group_label,
    filtered.doc_id AS doc_id,
    filtered.rel_path AS rel_path,
    filtered.source_label AS source_label,
    filtered.title AS title,
    filtered.sha256 AS sha256,
    COUNT(filtered.doc_id) OVER (PARTITION BY filtered.group_id) AS filtered_member_count
  FROM filtered AS filtered
)
SELECT
  ranked.group_id AS group_id,
  ranked.filtered_member_count AS member_count,
  ranked.group_label AS group_label,
  ranked.doc_id AS doc_id,
  ranked.rel_path AS rel_path,
  ranked.source_label AS source_label,
  ranked.title AS title,
  ranked.sha256 AS sha256
FROM ranked AS ranked
WHERE ranked.filtered_member_count > 1
ORDER BY
  ranked.filtered_member_count DESC,
  ranked.group_id,
  ranked.rel_path;

COMMENT ON VIEW v_agent_batch_source_dedupe IS 'Source dedupe tasks excluding build, librarian, and empty-file artifacts.';

CREATE OR REPLACE VIEW v_agent_batch_claim_audit AS
SELECT
  claims_catalog.claim_id AS claim_id,
  claims_catalog.doc_id AS doc_id,
  documents_catalog.rel_path AS rel_path,
  documents_catalog.source_label AS source_label,
  documents_catalog.title AS title,
  claims_catalog.claim_type AS claim_type,
  claims_catalog.trust_state AS trust_state,
  claims_catalog.source_locator AS source_locator,
  claims_catalog.evidence_hint AS evidence_hint,
  claims_catalog.claim_text AS claim_text
FROM claims AS claims_catalog
JOIN documents AS documents_catalog
  ON documents_catalog.doc_id = claims_catalog.doc_id
WHERE claims_catalog.trust_state = 'needs_external_verification'
   OR claims_catalog.claim_type IN ('risk_or_gap_claim', 'current_fact_or_metric')
ORDER BY
  CASE claims_catalog.claim_type
    WHEN 'risk_or_gap_claim' THEN 1
    WHEN 'current_fact_or_metric' THEN 2
    ELSE 3
  END,
  documents_catalog.rel_path,
  claims_catalog.claim_id;

COMMENT ON VIEW v_agent_batch_claim_audit IS 'Claim audit work surface for externally risky or current-fact claims.';

CREATE OR REPLACE VIEW v_agent_batch_spec_validation AS
SELECT
  documents_catalog.doc_id AS doc_id,
  documents_catalog.rel_path AS rel_path,
  documents_catalog.title AS title,
  yaml_metadata_catalog.urn AS urn,
  yaml_metadata_catalog.layer AS layer,
  yaml_metadata_catalog.type_node AS type_node,
  yaml_metadata_catalog.source_path AS source_path,
  yaml_metadata_catalog.locator AS locator,
  COALESCE(quality_flags_catalog.flag, '') AS flag,
  COALESCE(quality_flags_catalog.severity, '') AS severity,
  COALESCE(quality_flags_catalog.reason, '') AS reason
FROM documents AS documents_catalog
LEFT JOIN yaml_metadata AS yaml_metadata_catalog
  ON yaml_metadata_catalog.doc_id = documents_catalog.doc_id
LEFT JOIN quality_flags AS quality_flags_catalog
  ON quality_flags_catalog.doc_id = documents_catalog.doc_id
WHERE documents_catalog.source_label = 'primary_spec'
  AND documents_catalog.ingest_status <> 'empty_file'
ORDER BY
  documents_catalog.rel_path,
  quality_flags_catalog.severity DESC;

COMMENT ON VIEW v_agent_batch_spec_validation IS 'Primary-spec validation surface with parsed YAML metadata and quality flags.';

CREATE OR REPLACE VIEW v_agent_batch_pdf_report_triage AS
SELECT
  documents_view.doc_id AS doc_id,
  documents_view.rel_path AS rel_path,
  documents_view.title AS title,
  documents_view.pdf_pages AS pdf_pages,
  documents_view.word_count AS word_count,
  COALESCE(string_agg(DISTINCT document_topics_catalog.topic, ', '), '') AS topics,
  COALESCE(string_agg(DISTINCT quality_flags_catalog.flag, ', '), '') AS flags
FROM v_documents AS documents_view
LEFT JOIN document_topics AS document_topics_catalog
  ON document_topics_catalog.doc_id = documents_view.doc_id
LEFT JOIN quality_flags AS quality_flags_catalog
  ON quality_flags_catalog.doc_id = documents_view.doc_id
WHERE documents_view.extension = '.pdf'
  AND documents_view.source_label IN ('generated_report_pdf', 'static_whitepaper_pdf')
GROUP BY
  documents_view.doc_id,
  documents_view.rel_path,
  documents_view.title,
  documents_view.pdf_pages,
  documents_view.word_count
ORDER BY
  documents_view.word_count DESC NULLS LAST,
  documents_view.rel_path;

COMMENT ON VIEW v_agent_batch_pdf_report_triage IS 'PDF report triage surface for generated and static report PDFs.';

CREATE OR REPLACE VIEW v_agent_batch_actual_render_lineage AS
SELECT
  documents_view.doc_id AS doc_id,
  documents_view.rel_path AS rel_path,
  documents_view.filename AS filename,
  documents_view.extension AS extension,
  documents_view.title AS title,
  documents_view.source_label AS source_label,
  documents_view.file_kind AS file_kind,
  documents_view.ingest_status AS ingest_status,
  CASE
    WHEN documents_view.extension = '.pdf' THEN 'pdf'
    WHEN documents_view.filename = 'texture.tex' THEN 'texture_tex'
    WHEN documents_view.extension IN ('.tex', '.sty', '.cls', '.bib') THEN 'support_text'
    ELSE 'support_file'
  END AS render_file_role,
  CASE WHEN documents_view.ingest_status = 'empty_file' THEN true ELSE false END AS is_empty_file,
  CASE WHEN documents_view.filename = 'texture.tex' THEN true ELSE false END AS is_texture_tex,
  CASE WHEN documents_view.extension = '.pdf' THEN true ELSE false END AS is_pdf,
  CASE WHEN lower(COALESCE(documents_view.title, '') || ' ' || documents_view.rel_path) LIKE '%yoneda%' THEN true ELSE false END AS has_yoneda_text_hit,
  CASE WHEN SUM(CASE WHEN document_topics_catalog.topic = 'category_ontology' THEN 1 ELSE 0 END) > 0 THEN true ELSE false END AS has_category_ontology_topic,
  documents_view.word_count AS word_count,
  COALESCE(string_agg(DISTINCT document_topics_catalog.topic, ', '), '') AS topics,
  COALESCE(string_agg(DISTINCT quality_flags_catalog.flag, ', '), '') AS flags
FROM v_documents AS documents_view
LEFT JOIN document_topics AS document_topics_catalog
  ON document_topics_catalog.doc_id = documents_view.doc_id
LEFT JOIN quality_flags AS quality_flags_catalog
  ON quality_flags_catalog.doc_id = documents_view.doc_id
WHERE documents_view.rel_path LIKE 'actual/%'
  AND documents_view.source_label = 'render_attempt'
GROUP BY
  documents_view.doc_id,
  documents_view.rel_path,
  documents_view.filename,
  documents_view.extension,
  documents_view.title,
  documents_view.source_label,
  documents_view.file_kind,
  documents_view.ingest_status,
  documents_view.word_count
ORDER BY
  documents_view.rel_path;

COMMENT ON VIEW v_agent_batch_actual_render_lineage IS 'Actual render-lineage surface aligned with B005.';

CREATE OR REPLACE VIEW v_agent_batch_yoneda_render_lineage AS
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

COMMENT ON VIEW v_agent_batch_yoneda_render_lineage IS 'Compatibility alias for the B005 actual render-lineage surface.';

CREATE OR REPLACE VIEW v_agent_batch_gap_verification AS
SELECT
  gaps_catalog.gap_id AS gap_id,
  gaps_catalog.doc_id AS doc_id,
  documents_catalog.rel_path AS rel_path,
  documents_catalog.source_label AS source_label,
  documents_catalog.title AS title,
  gaps_catalog.severity AS severity,
  gaps_catalog.category AS category,
  gaps_catalog.source_locator AS source_locator,
  gaps_catalog.matched_terms AS matched_terms,
  gaps_catalog.gap_text AS gap_text
FROM gaps AS gaps_catalog
JOIN documents AS documents_catalog
  ON documents_catalog.doc_id = gaps_catalog.doc_id
ORDER BY
  CASE gaps_catalog.severity WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END,
  documents_catalog.rel_path,
  gaps_catalog.gap_id;

COMMENT ON VIEW v_agent_batch_gap_verification IS 'Gap verification work surface from non-empty ingested text.';

CREATE OR REPLACE VIEW v_agent_ready_work_queue AS
SELECT
  agent_batch_items_catalog.batch_id AS batch_id,
  agent_batches_catalog.objective AS objective,
  agent_batches_catalog.priority AS batch_priority,
  agent_batch_items_catalog.item_priority AS item_priority,
  agent_batch_items_catalog.batch_item_id AS batch_item_id,
  agent_batch_items_catalog.doc_id AS doc_id,
  documents_catalog.rel_path AS rel_path,
  documents_catalog.source_label AS source_label,
  documents_catalog.title AS title,
  agent_batch_items_catalog.item_reason AS item_reason,
  agent_batches_catalog.expected_output_shape AS expected_output_shape,
  agent_batches_catalog.quality_constraints AS quality_constraints
FROM agent_batch_items AS agent_batch_items_catalog
JOIN agent_batches AS agent_batches_catalog
  ON agent_batches_catalog.batch_id = agent_batch_items_catalog.batch_id
LEFT JOIN documents AS documents_catalog
  ON documents_catalog.doc_id = agent_batch_items_catalog.doc_id
ORDER BY
  agent_batches_catalog.priority,
  agent_batch_items_catalog.item_priority,
  agent_batch_items_catalog.batch_id,
  documents_catalog.rel_path;

COMMENT ON VIEW v_agent_ready_work_queue IS 'Unified typed work queue; shard CSVs are preferred for parallel agents.';

CREATE OR REPLACE VIEW v_agent_shards AS
SELECT
  agent_shards_catalog.batch_id AS batch_id,
  agent_shards_catalog.shard_id AS shard_id,
  agent_shards_catalog.shard_path AS shard_path,
  agent_shards_catalog.row_count AS row_count,
  agent_shards_catalog.source_view AS source_view,
  agent_shards_catalog.objective AS objective,
  agent_shards_catalog.expected_output_shape AS expected_output_shape,
  agent_shards_catalog.quality_constraints AS quality_constraints
FROM agent_shards AS agent_shards_catalog
ORDER BY
  agent_shards_catalog.batch_id,
  agent_shards_catalog.shard_id;

COMMENT ON VIEW v_agent_shards IS 'Shard manifest view for swarm-safe CSV task handoff.';
"""


def load_duckdb(sql: str, recorder: BuildRecorder) -> None:
    ACTIVE_PATHS.sql_path.write_text(sql, encoding="utf-8")
    recorder.emit("duckdb", "info", "Wrote explicit DDL/load SQL.", "sql_path", rel(FINAL_PATHS.sql_path))
    write_table_csv("build_events", recorder.rows)
    with ACTIVE_PATHS.sql_path.open("rb") as handle:
        subprocess.run(["duckdb", str(ACTIVE_PATHS.db_path)], stdin=handle, check=True)
    recorder.emit("duckdb", "info", "Loaded typed catalog into DuckDB.", "database", FINAL_PATHS.db_path.as_posix())
    refresh_build_events_table(recorder)


def refresh_build_events_table(recorder: BuildRecorder) -> None:
    path = write_table_csv("build_events", recorder.rows)
    schema = SCHEMAS["build_events"]
    select_exprs = ",\n  ".join(csv_cast_expr(column) for column in schema.columns)
    sql = f"""
DELETE FROM {sql_ident(schema.name)};

INSERT INTO {sql_ident(schema.name)}
SELECT
  {select_exprs}
FROM read_csv('{csv_sql_path(path)}', header=true, all_varchar=true, sample_size=-1) AS csv_source;
"""
    subprocess.run(["duckdb", str(ACTIVE_PATHS.db_path)], input=sql, text=True, check=True)


def write_queries(recorder: BuildRecorder) -> None:
    query_dir = ACTIVE_PATHS.query_dir
    query_dir.mkdir(parents=True, exist_ok=True)
    queries = {
        "01_document_inventory.sql": """-- Roll up catalog inventory by source class.
SELECT
  document_inventory.dir1 AS dir1,
  document_inventory.source_label AS source_label,
  document_inventory.file_kind AS file_kind,
  document_inventory.files AS files,
  document_inventory.bytes AS bytes,
  document_inventory.words AS words
FROM v_document_inventory AS document_inventory;
""",
        "02_source_dedupe.sql": """-- Duplicate source/export records for representative selection.
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
""",
        "03_claim_audit.sql": """-- Claims that need audit or external verification.
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
""",
        "04_spec_validation.sql": """-- Primary spec validation surface.
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
""",
        "05_pdf_report_triage.sql": """-- PDF report triage surface.
SELECT
  pdf_report_triage.doc_id AS doc_id,
  pdf_report_triage.rel_path AS rel_path,
  pdf_report_triage.title AS title,
  pdf_report_triage.pdf_pages AS pdf_pages,
  pdf_report_triage.word_count AS word_count,
  pdf_report_triage.topics AS topics,
  pdf_report_triage.flags AS flags
FROM v_agent_batch_pdf_report_triage AS pdf_report_triage;
""",
        "06_actual_render_lineage.sql": """-- Actual render lineage surface aligned with B005.
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
""",
        "06_yoneda_render_lineage.sql": """-- Compatibility alias for previous Yoneda render-lineage query name.
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
""",
        "07_gap_verification.sql": """-- Gap and limitation verification surface.
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
""",
        "08_agent_shards.sql": """-- Swarm-safe shard manifest.
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
""",
        "09_ready_work_queue.sql": """-- Unified work queue; prefer shard CSVs for parallel work.
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
""",
    }
    for filename, sql in queries.items():
        (query_dir / filename).write_text(sql, encoding="utf-8")
    recorder.emit("queries", "info", "Wrote documented library query files.", "queries", len(queries))


def write_manifest(counts: dict[str, Any], recorder: BuildRecorder) -> None:
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "root": ROOT.as_posix(),
        "database": FINAL_PATHS.db_path.as_posix(),
        "cache": CACHE_DIR.as_posix(),
        "agent_shard_dir": FINAL_PATHS.agent_shard_dir.as_posix(),
        "agent_shard_size": AGENT_SHARD_SIZE,
        "skipped_dirs": sorted(SKIP_DIRS),
        "skipped_files": sorted(SKIP_FILES),
        **counts,
    }
    ACTIVE_PATHS.manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    recorder.emit("manifest", "info", "Wrote catalog manifest.", "manifest", rel(FINAL_PATHS.manifest_path))


def csv_paths_for(paths: BuildPaths) -> dict[str, Path]:
    return {table_name: paths.table_dir / f"{table_name}.csv" for table_name in SCHEMAS}


def promote_staged_build(stage_paths: BuildPaths) -> None:
    backup_root = BUILD_TMP_DIR / f"backup_{os.getpid()}"
    promoted: list[Path] = []
    backups: list[tuple[Path, Path]] = []

    def backup_existing(destination: Path) -> None:
        if not destination.exists():
            return
        backup_path = backup_root / destination.relative_to(ROOT)
        backup_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(destination), str(backup_path))
        backups.append((backup_path, destination))

    def remove_path(path: Path) -> None:
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        elif path.exists():
            path.unlink()

    artifacts = [
        (stage_paths.table_dir, FINAL_PATHS.table_dir),
        (stage_paths.pdf_text_dir, FINAL_PATHS.pdf_text_dir),
        (stage_paths.agent_shard_dir, FINAL_PATHS.agent_shard_dir),
        (stage_paths.query_dir, FINAL_PATHS.query_dir),
        (stage_paths.sql_path, FINAL_PATHS.sql_path),
        (stage_paths.manifest_path, FINAL_PATHS.manifest_path),
        (stage_paths.build_log_path, FINAL_PATHS.build_log_path),
        (stage_paths.db_path, FINAL_PATHS.db_path),
    ]

    try:
        wal_path = FINAL_PATHS.db_path.with_name(f"{FINAL_PATHS.db_path.name}.wal")
        backup_existing(wal_path)
        for source, destination in artifacts:
            destination.parent.mkdir(parents=True, exist_ok=True)
            backup_existing(destination)
            shutil.move(str(source), str(destination))
            promoted.append(destination)
    except Exception:
        for destination in reversed(promoted):
            remove_path(destination)
        for backup_path, destination in reversed(backups):
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(backup_path), str(destination))
        raise
    else:
        shutil.rmtree(BUILD_TMP_DIR, ignore_errors=True)


def maybe_fail_before_commit() -> None:
    if os.environ.get("LIBRARY_CATALOG_FAIL_BEFORE_COMMIT") == "1":
        raise RuntimeError("Controlled failure before catalog artifact promotion.")


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    stage_paths = make_stage_paths()
    set_active_paths(stage_paths)
    recorder = BuildRecorder()
    recorder.emit("start", "info", "Starting catalog build from current filesystem.")
    prepare_cache(recorder)

    files = iter_files()
    recorder.emit("scan", "info", "Discovered candidate files after skip rules.", "files", len(files))
    rows_by_name = build_documents(files, recorder)
    documents = rows_by_name.pop("documents")
    if not all(isinstance(doc, Document) for doc in documents):
        raise TypeError("documents payload corrupted")
    typed_documents = list(documents)

    flags = rows_by_name["quality_flags"]
    if not isinstance(flags, list):
        raise TypeError("quality_flags payload corrupted")
    duplicate_rows, duplicate_doc_ids = duplicate_groups(typed_documents, flags, recorder)
    batches = agent_batches()
    batch_items = build_agent_items(typed_documents, duplicate_doc_ids, flags, recorder)
    shard_rows = write_agent_shards(batches, batch_items, typed_documents, recorder)

    table_rows: dict[str, list[dict[str, Any]]] = {
        "documents": document_rows(typed_documents),
        "document_text_units": rows_by_name["document_text_units"],
        "document_topics": rows_by_name["document_topics"],
        "yaml_metadata": rows_by_name["yaml_metadata"],
        "quality_flags": flags,
        "duplicate_groups": duplicate_rows,
        "claims": rows_by_name["claims"],
        "gaps": rows_by_name["gaps"],
        "agent_batches": batches,
        "agent_batch_items": batch_items,
        "agent_shards": shard_rows,
        "ingest_errors": rows_by_name["ingest_errors"],
        "catalog_notes": catalog_notes(),
        "build_events": recorder.rows,
    }

    csv_paths = {table_name: write_table_csv(table_name, table_rows[table_name]) for table_name in SCHEMAS}
    recorder.emit("csv", "info", "Wrote typed table CSV files.", "tables", len(csv_paths))
    table_rows["build_events"] = recorder.rows
    csv_paths["build_events"] = write_table_csv("build_events", table_rows["build_events"])

    write_queries(recorder)
    table_rows["build_events"] = recorder.rows
    csv_paths["build_events"] = write_table_csv("build_events", table_rows["build_events"])

    counts = {
        "documents": len(typed_documents),
        "text_units": len(table_rows["document_text_units"]),
        "topics": len(table_rows["document_topics"]),
        "claims": len(table_rows["claims"]),
        "gaps": len(table_rows["gaps"]),
        "duplicate_groups": len(duplicate_rows),
        "agent_batches": len(batches),
        "agent_batch_items": len(batch_items),
        "agent_shards": len(shard_rows),
        "empty_files": sum(1 for doc in typed_documents if doc.ingest_status == "empty_file"),
    }
    write_manifest(counts, recorder)
    table_rows["build_events"] = recorder.rows
    csv_paths["build_events"] = write_table_csv("build_events", table_rows["build_events"])

    load_duckdb(build_sql(csv_paths), recorder)
    recorder.emit("commit", "info", "Staged catalog build passed; promoting artifacts.", "stage_root", rel(stage_paths.table_dir.parent))
    table_rows["build_events"] = recorder.rows
    csv_paths["build_events"] = write_table_csv("build_events", table_rows["build_events"])
    refresh_build_events_table(recorder)

    ACTIVE_PATHS.sql_path.write_text(build_sql(csv_paths_for(FINAL_PATHS)), encoding="utf-8")
    recorder.write_log()
    maybe_fail_before_commit()
    promote_staged_build(stage_paths)
    set_active_paths(FINAL_PATHS)
    print(json.dumps(counts, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
