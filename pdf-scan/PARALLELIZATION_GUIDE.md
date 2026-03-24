# PDF Scan Pipeline — Multi-Chapter Parallelization Guide

> **Goal**: Extend the pipeline from single-chapter to multi-chapter operation,
> running D→E→F→G concurrently across chapters while sharing the expensive
> A→B→C corpus processing and document embeddings.
>
> **Scope**: Only files in `pdf-scan/`. No FastAPI changes.
>
> **Key user decisions**:
>
> - Phases A–C run once, cache a "Section Graph" + embeddings, then fan out D–G per chapter
> - Same section can appear in results for multiple chapters
> - If one chapter fails, others continue
> - Even single-chapter runs use the new `chapters/chapter_01/` layout
> - `.npy` format for embedding cache (same Python runtime)
> - Maximize parallel execution across chapters
> - 3–5 chapters is typical

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [New Directory Layout](#2-new-directory-layout)
3. [Task 1 — Phase A Refactor: Multi-Chapter Config](#task-1--phase-a-refactor-multi-chapter-config)
4. [Task 2 — RunArtifacts & RunContext Update](#task-2--runartifacts--runcontext-update)
5. [Task 3 — Phase C.5: Embedding & BM25 Cache](#task-3--phase-c5-embedding--bm25-cache)
6. [Task 4 — Phase E Refactor: Load Cached Embeddings](#task-4--phase-e-refactor-load-cached-embeddings)
7. [Task 5 — Multi-Chapter Orchestrator](#task-5--multi-chapter-orchestrator)
8. [Task 6 — Phase H: Cross-Chapter Aggregation](#task-6--phase-h-cross-chapter-aggregation)
9. [Concurrency Model](#7-concurrency-model)
10. [Error Handling & Isolation](#8-error-handling--isolation)
11. [Firestore Structure (Future Reference)](#9-firestore-structure-future-reference)
12. [Dependency & Rollout Order](#10-dependency--rollout-order)
13. [Validation Checklist](#11-validation-checklist)

---

## 1. Architecture Overview

### Current Flow (Single Chapter)

```
A → B → C → D → E → F → G
```

All 7 phases run linearly. Document embeddings are created fresh in Phase E every time.

### New Flow (Multi-Chapter)

```
A → B → C → C.5 ─┬─ D₁ → E₁ → F₁ → G₁ ─┐
                  ├─ D₂ → E₂ → F₂ → G₂ ─┤→ H (aggregate)
                  ├─ D₃ → E₃ → F₃ → G₃ ─┤
                  └─ ...                  ─┘
```

- **A→B→C**: Run once for the entire PDF corpus (unchanged)
- **C.5**: New phase — compute and cache document embeddings + BM25 index
- **D→E→F→G per chapter**: Fan out, each chapter gets its own subdirectory
- **H**: New phase — aggregate chapter results into a unified output

### What's Shared vs Per-Chapter

| Artifact                                     | Shared (run once) | Per-chapter  |
| -------------------------------------------- | ----------------- | ------------ |
| PDF manifest                                 | ✅                |              |
| Parser output (`parser/`)                    | ✅                |              |
| Normalized sections/passages (`normalized/`) | ✅                |              |
| Document embeddings (`.npy`)                 | ✅ (Phase C.5)    |              |
| BM25 index                                   | ✅ (Phase C.5)    |              |
| Query plan                                   |                   | ✅ (Phase D) |
| Retrieval lanes                              |                   | ✅ (Phase E) |
| Rerank results                               |                   | ✅ (Phase F) |
| Final scores                                 |                   | ✅ (Phase G) |
| Aggregated output                            |                   | ✅ (Phase H) |

---

## 2. New Directory Layout

```
runs/{run_id}/
├── config.json                    # Multi-chapter config (updated schema)
├── pdf_manifest.json              # Shared PDF manifest
├── metrics.json                   # Global metrics (all chapters)
├── api_calls.jsonl                # Global API call log
├── logs.jsonl                     # Global event log
├── run.log                        # Global log file
│
├── phase_a/                       # Phase A artifacts (unchanged)
│   ├── phase_a_config.json
│   ├── phase_a_runtime.json
│   ├── phase_a_summary.json
│   └── phase_a_assessment.json
│
├── parser/                        # Phase B artifacts (unchanged, shared)
│   ├── phase_b_config.json
│   ├── phase_b_summary.json
│   └── {doc_id}/
│       ├── metadata.json
│       ├── pymupdf_pages.jsonl
│       ├── docling.json
│       └── grobid_summary.json
│
├── normalized/                    # Phase C artifacts (unchanged, shared)
│   ├── phase_c_config.json
│   ├── phase_c_summary.json
│   ├── documents.jsonl
│   ├── sections.jsonl
│   └── passages.jsonl
│
├── embeddings/                    # NEW: Phase C.5 artifacts (shared)
│   ├── phase_c5_config.json
│   ├── phase_c5_runtime.json
│   ├── phase_c5_summary.json
│   ├── section_embeddings.npy     # [num_sections, embed_dim] float32
│   ├── section_ids.json           # ordered list of section_ids matching rows
│   ├── passage_embeddings.npy     # [num_passages, embed_dim] float32
│   ├── passage_ids.json           # ordered list of passage_ids matching rows
│   ├── embedding_metadata.json    # model, dimensions, token counts, cost
│   └── bm25_inputs.json           # Pre-computed tokenized texts for BM25
│
├── chapters/
│   ├── chapter_01/                # Per-chapter artifacts
│   │   ├── chapter_config.json    # chapter_title, chapter_spec_text, chapter_id
│   │   ├── retrieval/             # Phase D + E output
│   │   │   ├── phase_d_config.json
│   │   │   ├── phase_d_summary.json
│   │   │   ├── query_plan.json
│   │   │   ├── query_views.json
│   │   │   ├── phase_e_config.json
│   │   │   ├── phase_e_summary.json
│   │   │   ├── lanes/
│   │   │   │   ├── section_title_lexical.jsonl
│   │   │   │   ├── section_body_lexical.jsonl
│   │   │   │   ├── section_dense.jsonl
│   │   │   │   ├── passage_lexical.jsonl
│   │   │   │   └── passage_dense.jsonl
│   │   │   └── fused_candidates.jsonl
│   │   ├── rerank/                # Phase F output
│   │   │   ├── phase_f_config.json
│   │   │   ├── phase_f_summary.json
│   │   │   ├── rerank_results.jsonl
│   │   │   └── llm_judge_results.jsonl
│   │   └── final/                 # Phase G output
│   │       ├── phase_g_config.json
│   │       ├── phase_g_summary.json
│   │       ├── output.json
│   │       ├── per_pdf_rankings.json
│   │       ├── global_rankings.json
│   │       ├── section_scores.jsonl
│   │       └── doc_features.jsonl
│   │
│   ├── chapter_02/                # Same structure
│   │   └── ...
│   └── chapter_03/
│       └── ...
│
├── aggregate/                     # NEW: Phase H output
│   ├── phase_h_config.json
│   ├── phase_h_summary.json
│   └── output.json                # Unified cross-chapter output
│
└── phase_a_review/                # Phase A review (unchanged)
```

---

## Task 1 — Phase A Refactor: Multi-Chapter Config

### 1.1 Background

**Current `PhaseAConfig`** (phase_a_lab.py, lines 224–292):

```python
class PhaseAConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pipeline_version: str
    input_mode: Literal["small_gold", "manual"]
    chapter_title: str              # ← SINGLE chapter
    chapter_spec_text: str          # ← SINGLE chapter
    runs_root: Path
    openai_api_key_present: bool
    force_rebuild_phase_a: bool
    pdf_sources: List[PdfSource]
    # ... other fields
```

This only supports a single chapter. We need to support a list of chapters.

### 1.2 New Data Models

**Add a `ChapterSpec` model** (before `PhaseAConfig`):

```python
class ChapterSpec(BaseModel):
    """Specification for one chapter in a multi-chapter run."""
    model_config = ConfigDict(extra="forbid")

    chapter_id: str               # e.g. "chapter_01", "chapter_02"
    chapter_title: str
    chapter_spec_text: str

    @field_validator("chapter_id", "chapter_title", "chapter_spec_text", mode="before")
    @classmethod
    def _normalize_non_empty(cls, value: Any) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("Required string field must not be empty.")
        return text
```

### 1.3 Modify `PhaseAConfig`

**Replace the single-chapter fields** with a list of chapters.
Keep backward compatibility by also accepting the old single-chapter form:

```python
class PhaseAConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pipeline_version: str
    input_mode: Literal["small_gold", "manual"]
    chapters: List[ChapterSpec]           # NEW: list of chapters
    runs_root: Path
    openai_api_key_present: bool
    force_rebuild_phase_a: bool
    pdf_sources: List[PdfSource]
    pdf_dir_raw: str = ""
    pdf_glob: str = "*.pdf"
    pdf_recursive: bool = False
    max_pdfs: int = 20
    benchmark_suite_manifest: str = ""
    benchmark_suite_id: str = ""
    benchmark_chapter_id: str = ""
    resolved_source_count: int = 0
    source_discovery_total_count: int = 0

    # Backward-compatible read-only properties
    @property
    def chapter_title(self) -> str:
        """First chapter's title (backward compatibility)."""
        return self.chapters[0].chapter_title if self.chapters else ""

    @property
    def chapter_spec_text(self) -> str:
        """First chapter's spec text (backward compatibility)."""
        return self.chapters[0].chapter_spec_text if self.chapters else ""

    @field_validator("pipeline_version", mode="before")
    @classmethod
    def _normalize_non_empty(cls, value: Any) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("Required string field must not be empty.")
        return text

    @model_validator(mode="after")
    def _validate_config(self) -> "PhaseAConfig":
        if not self.chapters:
            raise ValueError("Phase A requires at least one chapter spec.")
        if not self.pdf_sources:
            raise ValueError("Phase A requires at least one resolved PDF source.")
        self.resolved_source_count = len(self.pdf_sources)
        # Compute SHA for first chapter (backward compat) or combine all
        combined_spec = "\n---\n".join(ch.chapter_spec_text for ch in self.chapters)
        self.chapter_spec_sha256 = sha256_text(combined_spec)
        # Validate unique chapter_ids
        ids = [ch.chapter_id for ch in self.chapters]
        if len(ids) != len(set(ids)):
            raise ValueError("Chapter IDs must be unique.")
        return self

    def to_snapshot(self) -> Dict[str, Any]:
        return {
            "pipeline_version": self.pipeline_version,
            "input_mode": self.input_mode,
            "chapters": [
                {
                    "chapter_id": ch.chapter_id,
                    "chapter_title": ch.chapter_title,
                    "chapter_spec_text_chars": len(ch.chapter_spec_text),
                    "chapter_spec_text_words": len(ch.chapter_spec_text.split()),
                }
                for ch in self.chapters
            ],
            "chapter_count": len(self.chapters),
            "runs_root": str(self.runs_root),
            "openai_api_key_present": self.openai_api_key_present,
            "force_rebuild_phase_a": self.force_rebuild_phase_a,
            "pdf_sources": [{"label": item.label, "path": str(item.path)} for item in self.pdf_sources],
            "resolved_source_count": self.resolved_source_count,
        }
```

### 1.4 Modify `compute_run_id()`

**Current** (line ~695):

```python
def compute_run_id(
    chapter_title: str,
    chapter_spec_text: str,
    pipeline_version: str,
    manifest_rows: List[Dict[str, Any]],
) -> str:
    doc_parts = [f"{row.get('label')}::{row.get('sha256')}" for row in manifest_rows]
    return stable_hash(pipeline_version, chapter_title, chapter_spec_text, "\n".join(doc_parts), length=24)
```

**Replace with**:

```python
def compute_run_id(
    chapters: List[Dict[str, str]],
    pipeline_version: str,
    manifest_rows: List[Dict[str, Any]],
) -> str:
    """Compute deterministic run_id from chapters + documents.

    The run_id now incorporates ALL chapter specs so that the same set of
    chapters + documents always maps to the same run directory.
    """
    chapter_parts = [
        f"{ch['chapter_id']}::{ch['chapter_title']}::{ch['chapter_spec_text']}"
        for ch in sorted(chapters, key=lambda c: c["chapter_id"])
    ]
    doc_parts = [f"{row.get('label')}::{row.get('sha256')}" for row in manifest_rows]
    return stable_hash(
        pipeline_version,
        "\n".join(chapter_parts),
        "\n".join(doc_parts),
        length=24,
    )
```

### 1.5 Update `run_phase_a()` Call Site

**Current** (line ~840):

```python
run_id = compute_run_id(config.chapter_title, config.chapter_spec_text, config.pipeline_version, pdf_manifest_rows)
```

**Replace with**:

```python
run_id = compute_run_id(
    chapters=[
        {"chapter_id": ch.chapter_id, "chapter_title": ch.chapter_title, "chapter_spec_text": ch.chapter_spec_text}
        for ch in config.chapters
    ],
    pipeline_version=config.pipeline_version,
    manifest_rows=pdf_manifest_rows,
)
```

### 1.6 Update callers in `run_phase_a()`

Where PhaseAConfig is currently constructed with `chapter_title=...` and `chapter_spec_text=...`,
wrap in `ChapterSpec` and pass as `chapters=[...]`:

```python
# Old:
config = PhaseAConfig(
    chapter_title=resolved["chapter_title"],
    chapter_spec_text=resolved["chapter_spec_text"],
    ...
)

# New (single-chapter mode uses chapter_01 as ID):
config = PhaseAConfig(
    chapters=[
        ChapterSpec(
            chapter_id="chapter_01",
            chapter_title=resolved["chapter_title"],
            chapter_spec_text=resolved["chapter_spec_text"],
        )
    ],
    ...
)
```

### 1.7 Backward Compatibility

The `chapter_title` and `chapter_spec_text` properties on `PhaseAConfig` ensure that
any code accessing `config.chapter_title` (like Phase D's call in
`run_pdf_scan_pipeline.py`) still works without changes.

---

## Task 2 — RunArtifacts & RunContext Update

### 2.1 Background

**Current `RunArtifacts`** (lines 294–339) is a flat structure:

```python
class RunArtifacts(BaseModel):
    config_json: Path
    pdf_manifest_json: Path
    query_plan_json: Path        # ← Single query plan
    parser_dir: Path
    normalized_dir: Path
    retrieval_dir: Path          # ← Single retrieval dir
    rerank_dir: Path             # ← Single rerank dir
    final_dir: Path              # ← Single final dir
    ...
```

This needs to support:

- Shared paths (parser, normalized, embeddings)
- Per-chapter paths (retrieval, rerank, final)

### 2.2 New `ChapterArtifacts` Class

**Add before `RunArtifacts`**:

```python
class ChapterArtifacts(BaseModel):
    """Artifact paths for a single chapter within a multi-chapter run."""
    model_config = ConfigDict(extra="forbid", frozen=True)

    chapter_id: str
    chapter_dir: Path
    chapter_config_json: Path
    retrieval_dir: Path
    rerank_dir: Path
    final_dir: Path
    query_plan_json: Path

    @classmethod
    def from_chapter_dir(cls, chapter_id: str, chapter_dir: Path) -> "ChapterArtifacts":
        return cls(
            chapter_id=chapter_id,
            chapter_dir=chapter_dir,
            chapter_config_json=chapter_dir / "chapter_config.json",
            retrieval_dir=chapter_dir / "retrieval",
            rerank_dir=chapter_dir / "rerank",
            final_dir=chapter_dir / "final",
            query_plan_json=chapter_dir / "retrieval" / "query_plan.json",
        )

    def create_skeleton(self) -> None:
        """Create the directory structure for this chapter."""
        ensure_dir(self.chapter_dir)
        ensure_dir(self.retrieval_dir)
        ensure_dir(self.rerank_dir)
        ensure_dir(self.final_dir)
```

### 2.3 Modify `RunArtifacts`

**Replace the current class** with one that has shared + chapter-level paths:

```python
class RunArtifacts(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    # Global / shared paths
    config_json: Path
    pdf_manifest_json: Path
    parser_dir: Path
    normalized_dir: Path
    embeddings_dir: Path              # NEW: Phase C.5 output
    chapters_dir: Path                # NEW: parent of all chapter dirs
    aggregate_dir: Path               # NEW: Phase H output
    logs_jsonl: Path
    run_log: Path
    metrics_json: Path
    api_calls_jsonl: Path
    phase_a_dir: Path
    phase_a_config_json: Path
    phase_a_runtime_json: Path
    phase_a_summary_json: Path
    phase_a_assessment_json: Path
    phase_a_review_dir: Path

    # Per-chapter artifacts (populated after config is known)
    chapter_artifacts: Dict[str, ChapterArtifacts] = {}

    # Backward-compatible properties for single-chapter access
    @property
    def query_plan_json(self) -> Path:
        """First chapter's query plan (backward compatibility)."""
        first = next(iter(self.chapter_artifacts.values()), None)
        if first:
            return first.query_plan_json
        # Fallback to old location
        return self.config_json.parent / "query_plan.json"

    @property
    def retrieval_dir(self) -> Path:
        first = next(iter(self.chapter_artifacts.values()), None)
        if first:
            return first.retrieval_dir
        return self.config_json.parent / "retrieval"

    @property
    def rerank_dir(self) -> Path:
        first = next(iter(self.chapter_artifacts.values()), None)
        if first:
            return first.rerank_dir
        return self.config_json.parent / "rerank"

    @property
    def final_dir(self) -> Path:
        first = next(iter(self.chapter_artifacts.values()), None)
        if first:
            return first.final_dir
        return self.config_json.parent / "final"

    @classmethod
    def from_run_dir(cls, run_dir: Path, chapter_ids: Optional[List[str]] = None) -> "RunArtifacts":
        phase_a_dir = run_dir / "phase_a"
        chapters_dir = run_dir / "chapters"

        chapter_artifacts = {}
        for cid in (chapter_ids or []):
            ch_dir = chapters_dir / cid
            chapter_artifacts[cid] = ChapterArtifacts.from_chapter_dir(cid, ch_dir)

        return cls(
            config_json=run_dir / "config.json",
            pdf_manifest_json=run_dir / "pdf_manifest.json",
            parser_dir=run_dir / "parser",
            normalized_dir=run_dir / "normalized",
            embeddings_dir=run_dir / "embeddings",
            chapters_dir=chapters_dir,
            aggregate_dir=run_dir / "aggregate",
            logs_jsonl=run_dir / "logs.jsonl",
            run_log=run_dir / "run.log",
            metrics_json=run_dir / "metrics.json",
            api_calls_jsonl=run_dir / "api_calls.jsonl",
            phase_a_dir=phase_a_dir,
            phase_a_config_json=phase_a_dir / "phase_a_config.json",
            phase_a_runtime_json=phase_a_dir / "phase_a_runtime.json",
            phase_a_summary_json=phase_a_dir / "phase_a_summary.json",
            phase_a_assessment_json=phase_a_dir / "phase_a_assessment.json",
            phase_a_review_dir=run_dir / "phase_a_review",
            chapter_artifacts=chapter_artifacts,
        )
```

### 2.4 Update `RunContext.create_artifact_skeleton()`

Add creation of new directories:

```python
def create_artifact_skeleton(self, overwrite: bool = False) -> None:
    ensure_dir(self.run_dir)
    ensure_dir(self.artifacts.parser_dir)
    ensure_dir(self.artifacts.normalized_dir)
    ensure_dir(self.artifacts.embeddings_dir)       # NEW
    ensure_dir(self.artifacts.chapters_dir)          # NEW
    ensure_dir(self.artifacts.aggregate_dir)          # NEW
    ensure_dir(self.artifacts.phase_a_dir)
    ensure_dir(self.artifacts.phase_a_review_dir)

    # Create per-chapter skeletons
    for ch_artifacts in self.artifacts.chapter_artifacts.values():
        ch_artifacts.create_skeleton()

    # ... rest of placeholder creation stays the same ...
```

### 2.5 Update `from_run_dir` Calls

Wherever `RunArtifacts.from_run_dir(run_dir)` is called, pass the chapter IDs:

```python
# In run_phase_a():
chapter_ids = [ch.chapter_id for ch in config.chapters]
artifacts = RunArtifacts.from_run_dir(run_dir, chapter_ids=chapter_ids)
```

### 2.6 Chapter-Aware RunContext for Per-Chapter Phases

Phase D/E/F/G need a `run_ctx` that points to the chapter-specific directories.
Create a helper method on `RunContext`:

```python
class RunContext(BaseModel):
    # ... existing fields ...

    def for_chapter(self, chapter_id: str) -> "RunContext":
        """Return a shallow copy of RunContext with artifacts pointing to a specific chapter.

        This creates a RunContext where retrieval_dir, rerank_dir, final_dir,
        and query_plan_json resolve to the chapter's subdirectory.
        """
        ch = self.artifacts.chapter_artifacts.get(chapter_id)
        if ch is None:
            raise ValueError(f"Unknown chapter_id: {chapter_id}")

        # Create a modified artifacts that overrides chapter-level paths
        # We use the backward-compat properties, so just ensure that
        # the chapter_artifacts dict has exactly this one chapter first.
        chapter_only_artifacts = RunArtifacts.from_run_dir(
            self.run_dir,
            chapter_ids=[chapter_id],
        )
        return RunContext(
            repo_root=self.repo_root,
            pdf_scan_dir=self.pdf_scan_dir,
            run_id=self.run_id,
            run_dir=self.run_dir,
            artifacts=chapter_only_artifacts,
        )
```

This way, `run_phase_d(run_ctx.for_chapter("chapter_01"), ...)` will write to
`chapters/chapter_01/retrieval/` automatically through the backward-compat properties.

---

## Task 3 — Phase C.5: Embedding & BM25 Cache

### 3.1 Purpose

Compute document-level embeddings and BM25 tokenization **once** after Phase C,
so that per-chapter Phase E runs can load them from disk instead of re-computing.

This saves:

- ~30 seconds of OpenAI embedding API time per chapter (query embeddings still computed per chapter)
- All document embedding API cost for chapters 2–N
- BM25 index construction time

### 3.2 Create New File: `phase_c5_lab.py`

```python
#!/usr/bin/env python3
"""Phase C.5 — Document Embedding & BM25 Cache

Runs once after Phase C. Embeds all sections and passages using the OpenAI
embedding model, saves results as .npy files. Also pre-tokenizes texts for
BM25 so per-chapter Phase E can skip this work.

Outputs (in run_dir/embeddings/):
  - section_embeddings.npy    [num_sections, embed_dim]
  - section_ids.json          ordered list of section_ids
  - passage_embeddings.npy    [num_passages, embed_dim]
  - passage_ids.json          ordered list of passage_ids
  - embedding_metadata.json   model info, costs, timing
  - bm25_inputs.json          pre-tokenized texts for BM25
  - phase_c5_config.json
  - phase_c5_runtime.json
  - phase_c5_summary.json
"""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

# Import from earlier phases
from phase_e_lab import (
    PhaseEOptions,
    build_inputs,
    embed_texts,
    clean_text,
    ensure_dir,
    json_safe,
    read_json,
    read_jsonl_rows,
    tokenize_text,
    utc_now_iso,
    write_json,
)


@dataclass
class PhaseC5Options:
    force_rebuild: bool = False
    openai_embedding_model: str = "text-embedding-3-small"
    openai_timeout_sec: int = 300
    dense_batch_size: int = 64
    dense_section_max_chars: int = 4200
    dense_passage_max_chars: int = 2400
    dense_dimensions: Optional[int] = None

    def normalized(self) -> "PhaseC5Options":
        return PhaseC5Options(
            force_rebuild=bool(self.force_rebuild),
            openai_embedding_model=str(self.openai_embedding_model or "text-embedding-3-small").strip(),
            openai_timeout_sec=max(30, int(self.openai_timeout_sec)),
            dense_batch_size=max(1, int(self.dense_batch_size)),
            dense_section_max_chars=max(400, int(self.dense_section_max_chars)),
            dense_passage_max_chars=max(200, int(self.dense_passage_max_chars)),
            dense_dimensions=None if self.dense_dimensions is None else max(64, int(self.dense_dimensions)),
        )


def run_phase_c5(
    run_ctx: Any,
    *,
    options: PhaseC5Options,
    stable_hash_fn=None,
    log_event_fn=None,
    run_logger=None,
) -> Dict[str, Any]:
    """Compute and cache document embeddings + BM25 inputs.

    Reads Phase C outputs (sections.jsonl, passages.jsonl, documents.jsonl).
    Writes to run_dir/embeddings/.
    """
    opt = options.normalized()
    embeddings_dir = ensure_dir(Path(run_ctx.artifacts.embeddings_dir))
    config_path = embeddings_dir / "phase_c5_config.json"
    runtime_path = embeddings_dir / "phase_c5_runtime.json"
    summary_path = embeddings_dir / "phase_c5_summary.json"

    section_emb_path = embeddings_dir / "section_embeddings.npy"
    section_ids_path = embeddings_dir / "section_ids.json"
    passage_emb_path = embeddings_dir / "passage_embeddings.npy"
    passage_ids_path = embeddings_dir / "passage_ids.json"
    metadata_path = embeddings_dir / "embedding_metadata.json"
    bm25_inputs_path = embeddings_dir / "bm25_inputs.json"

    # Cache check
    if not bool(opt.force_rebuild) and all(
        p.exists()
        for p in [section_emb_path, section_ids_path, passage_emb_path, passage_ids_path, metadata_path, bm25_inputs_path, summary_path]
    ):
        cached = read_json(summary_path)
        if run_logger:
            run_logger.info("Phase C.5 cached — skipping embedding computation")
        return {"status": "cached", "summary": cached}

    write_json(config_path, {"generated_at_utc": utc_now_iso(), "phase": "phase_c5", "options": json_safe(asdict(opt))})
    write_json(runtime_path, {"generated_at_utc": utc_now_iso(), "phase": "phase_c5", "options": json_safe(asdict(opt))})

    # Load Phase C outputs
    normalized_dir = Path(run_ctx.artifacts.normalized_dir)
    documents = read_jsonl_rows(normalized_dir / "documents.jsonl")
    sections = read_jsonl_rows(normalized_dir / "sections.jsonl")
    passages = read_jsonl_rows(normalized_dir / "passages.jsonl")

    # Build inputs using existing Phase E helper
    # We need a PhaseEOptions-like object for build_inputs
    e_opt = PhaseEOptions(
        dense_section_max_chars=opt.dense_section_max_chars,
        dense_passage_max_chars=opt.dense_passage_max_chars,
    )
    sec_lookup, pass_lookup, lane_inputs = build_inputs(sections, passages, e_opt)

    started = time.perf_counter()
    total_api_cost = 0.0
    total_input_tokens = 0

    # ── Embed sections ──
    section_texts = lane_inputs["section_dense"]["texts"]
    section_items = lane_inputs["section_dense"]["items"]
    section_ids = [str(item.get("item_id") or "") for item in section_items]

    if section_texts:
        section_mat, sec_usage, sec_cost = embed_texts(
            section_texts,
            opt.openai_embedding_model,
            opt.dense_batch_size,
            opt.openai_timeout_sec,
            opt.dense_dimensions,
        )
        total_api_cost += float(sec_cost.get("estimated_cost_usd") or 0.0)
        total_input_tokens += int(sec_usage.get("input_tokens") or 0)
    else:
        section_mat = np.zeros((0, 0), dtype=np.float32)

    # ── Embed passages ──
    passage_texts = lane_inputs["passage_dense"]["texts"]
    passage_items = lane_inputs["passage_dense"]["items"]
    passage_ids = [str(item.get("item_id") or "") for item in passage_items]

    if passage_texts:
        passage_mat, pass_usage, pass_cost = embed_texts(
            passage_texts,
            opt.openai_embedding_model,
            opt.dense_batch_size,
            opt.openai_timeout_sec,
            opt.dense_dimensions,
        )
        total_api_cost += float(pass_cost.get("estimated_cost_usd") or 0.0)
        total_input_tokens += int(pass_usage.get("input_tokens") or 0)
    else:
        passage_mat = np.zeros((0, 0), dtype=np.float32)

    embed_elapsed_ms = round((time.perf_counter() - started) * 1000.0, 3)

    # ── BM25 pre-tokenization ──
    bm25_started = time.perf_counter()
    bm25_data = {}
    for lane_name in ["section_title_lexical", "section_body_lexical", "passage_lexical"]:
        lane = lane_inputs.get(lane_name, {})
        texts = lane.get("texts", [])
        items = lane.get("items", [])
        ids = [str(item.get("item_id") or "") for item in items]
        # Tokenize for BM25 (lowercase split — matches Phase E BM25 class)
        tokenized = [tokenize_text(t) for t in texts]
        bm25_data[lane_name] = {
            "ids": ids,
            "tokenized_texts": tokenized,
        }
    bm25_elapsed_ms = round((time.perf_counter() - bm25_started) * 1000.0, 3)

    # ── Save artifacts ──
    np.save(str(section_emb_path), section_mat)
    write_json(section_ids_path, section_ids)
    np.save(str(passage_emb_path), passage_mat)
    write_json(passage_ids_path, passage_ids)

    write_json(metadata_path, {
        "generated_at_utc": utc_now_iso(),
        "model": opt.openai_embedding_model,
        "dimensions": opt.dense_dimensions,
        "section_count": len(section_ids),
        "section_embedding_shape": list(section_mat.shape),
        "passage_count": len(passage_ids),
        "passage_embedding_shape": list(passage_mat.shape),
        "total_input_tokens": total_input_tokens,
        "estimated_cost_usd": round(total_api_cost, 6),
        "embed_elapsed_ms": embed_elapsed_ms,
    })

    write_json(bm25_inputs_path, bm25_data)

    total_elapsed_ms = round((time.perf_counter() - started) * 1000.0, 3)

    summary = {
        "generated_at_utc": utc_now_iso(),
        "phase": "phase_c5",
        "status": "complete",
        "section_count": len(section_ids),
        "passage_count": len(passage_ids),
        "embedding_model": opt.openai_embedding_model,
        "total_input_tokens": total_input_tokens,
        "estimated_cost_usd": round(total_api_cost, 6),
        "embed_elapsed_ms": embed_elapsed_ms,
        "bm25_elapsed_ms": bm25_elapsed_ms,
        "total_elapsed_ms": total_elapsed_ms,
    }
    write_json(summary_path, summary)

    if run_logger:
        run_logger.info(
            "Phase C.5 complete | sections=%d | passages=%d | tokens=%d | cost=$%.4f | elapsed=%dms",
            len(section_ids), len(passage_ids), total_input_tokens, total_api_cost, total_elapsed_ms,
        )

    return {
        "status": "complete",
        "summary": summary,
        "metrics_update": {
            "phase_c5": {
                "section_count": len(section_ids),
                "passage_count": len(passage_ids),
                "total_input_tokens": total_input_tokens,
                "estimated_cost_usd": round(total_api_cost, 6),
                "elapsed_ms": total_elapsed_ms,
            }
        },
    }
```

### 3.3 Important: `tokenize_text()` Function

Phase E's `BM25` class uses a simple tokenizer. We need to ensure the same tokenizer
is used in C.5. Check Phase E for the exact tokenization function used.

If Phase E uses something like:

```python
def tokenize_text(text: str) -> List[str]:
    return [w.lower() for w in re.findall(r'\w+', text)]
```

Then import and reuse it in C.5. If it's inline in the BM25 constructor, extract it
into a named function first.

### 3.4 Notes on `.npy` Format

- `np.save()` produces a single `.npy` file with header + raw float32 data
- `np.load()` reads it back as a numpy array with mmap option for large files
- This is the most efficient format for the same-runtime requirement
- The `section_ids.json` / `passage_ids.json` maintain the row↔ID mapping

---

## Task 4 — Phase E Refactor: Load Cached Embeddings

### 4.1 Background

**Current Phase E** (`phase_e_lab.py`, lines 964–1050) does:

1. Read `sections.jsonl`, `passages.jsonl`, `query_plan.json`
2. Build lane inputs (section texts, passage texts)
3. Run BM25 on 3 lexical lanes
4. Embed queries + sections + passages via OpenAI API
5. Score dense lanes via cosine similarity
6. Fuse via RRF + xQuAD diversification

Steps 4 (document embeddings) is now done in Phase C.5. Phase E only needs to:

- Load cached section/passage embeddings from `.npy` files
- Embed query texts (still needed per chapter)
- Run BM25 using cached tokenization
- Continue with scoring as before

### 4.2 Add `PhaseEOptions` Fields

```python
    # Add to PhaseEOptions:
    use_cached_embeddings: bool = True
    embeddings_dir: Optional[str] = None  # Override path; None = use run_ctx.artifacts.embeddings_dir
```

### 4.3 Modify Embedding Loading in `run_phase_e()`

**Current code** (around line 1010–1045 in `run_phase_e()`):

```python
    if bool(opt.use_openai_dense) and PhaseEOpenAI is not None and PHASE_E_API_KEY and np is not None:
        q_texts = [trunc(v.get("query_text"), opt.dense_query_max_chars) for v in views]
        dense_jobs = [("queries", q_texts)]
        if lane_inputs["section_dense"]["texts"]:
            dense_jobs.append(("sections", list(lane_inputs["section_dense"]["texts"])))
        if lane_inputs["passage_dense"]["texts"]:
            dense_jobs.append(("passages", list(lane_inputs["passage_dense"]["texts"])))
        resolved_dense_task_concurrency = resolve_phase_e_dense_task_concurrency(task_count=len(dense_jobs))
        dense_results: Dict[str, Any] = {}

        def run_dense_job(job_name: str, texts: List[str]):
            mat, usage, cost = embed_texts(texts, ...)
            return job_name, mat, usage, cost

        # ... ThreadPoolExecutor runs all jobs ...

        qmat, qusage, qcost = dense_results["queries"]
        smat, susage, _ = dense_results.get("sections", ...)
        pmat, pusage, _ = dense_results.get("passages", ...)
```

**Replace with cached-aware version**:

```python
    if bool(opt.use_openai_dense) and PhaseEOpenAI is not None and PHASE_E_API_KEY and np is not None:
        q_texts = [trunc(v.get("query_text"), opt.dense_query_max_chars) for v in views]

        # Try loading cached document embeddings from Phase C.5
        cached_loaded = False
        emb_dir = Path(opt.embeddings_dir) if opt.embeddings_dir else Path(run_ctx.artifacts.embeddings_dir)

        if bool(opt.use_cached_embeddings) and emb_dir.exists():
            sec_emb_path = emb_dir / "section_embeddings.npy"
            sec_ids_path = emb_dir / "section_ids.json"
            pass_emb_path = emb_dir / "passage_embeddings.npy"
            pass_ids_path = emb_dir / "passage_ids.json"

            if all(p.exists() for p in [sec_emb_path, sec_ids_path, pass_emb_path, pass_ids_path]):
                cached_sec_ids = read_json(sec_ids_path)
                cached_pass_ids = read_json(pass_ids_path)

                # Verify IDs match current lane inputs
                current_sec_ids = [str(item.get("item_id") or "") for item in lane_inputs["section_dense"]["items"]]
                current_pass_ids = [str(item.get("item_id") or "") for item in lane_inputs["passage_dense"]["items"]]

                if cached_sec_ids == current_sec_ids and cached_pass_ids == current_pass_ids:
                    smat = np.load(str(sec_emb_path))
                    pmat = np.load(str(pass_emb_path))
                    susage = {"input_tokens": 0, "total_tokens": 0, "output_tokens": 0, "source": "cached"}
                    pusage = {"input_tokens": 0, "total_tokens": 0, "output_tokens": 0, "source": "cached"}

                    # Only embed queries (fresh per chapter)
                    qmat, qusage, qcost = embed_texts(
                        q_texts,
                        opt.openai_embedding_model,
                        opt.dense_batch_size,
                        opt.openai_timeout_sec,
                        opt.dense_dimensions,
                    )
                    query_mats = {str(v.get("view_id")): qmat[i : i + 1] for i, v in enumerate(views)}

                    cached_loaded = True
                    dense_trace["dense_mode"] = "cached_c5"
                    if run_logger:
                        run_logger.info("Phase E loaded cached embeddings from Phase C.5 (%d sections, %d passages)", len(cached_sec_ids), len(cached_pass_ids))
                else:
                    if run_logger:
                        run_logger.warning("Phase C.5 cache ID mismatch — re-embedding from scratch")

        if not cached_loaded:
            # Fall back to original embedding logic (unchanged)
            dense_jobs = [("queries", q_texts)]
            if lane_inputs["section_dense"]["texts"]:
                dense_jobs.append(("sections", list(lane_inputs["section_dense"]["texts"])))
            if lane_inputs["passage_dense"]["texts"]:
                dense_jobs.append(("passages", list(lane_inputs["passage_dense"]["texts"])))
            resolved_dense_task_concurrency = resolve_phase_e_dense_task_concurrency(task_count=len(dense_jobs))
            dense_results: Dict[str, Any] = {}

            def run_dense_job(job_name: str, texts: List[str]):
                mat, usage, cost = embed_texts(texts, opt.openai_embedding_model, opt.dense_batch_size, opt.openai_timeout_sec, opt.dense_dimensions)
                return job_name, mat, usage, cost

            if resolved_dense_task_concurrency <= 1:
                for job_name, texts in dense_jobs:
                    _, mat, usage, cost = run_dense_job(job_name, texts)
                    dense_results[job_name] = (mat, usage, cost)
            else:
                with ThreadPoolExecutor(max_workers=resolved_dense_task_concurrency) as executor:
                    future_map = {
                        executor.submit(run_dense_job, job_name, texts): job_name
                        for job_name, texts in dense_jobs
                    }
                    for future in as_completed(future_map):
                        job_name, mat, usage, cost = future.result()
                        dense_results[job_name] = (mat, usage, cost)

            qmat, qusage, qcost = dense_results["queries"]
            query_mats = {str(v.get("view_id")): qmat[i : i + 1] for i, v in enumerate(views)}
            if "sections" in dense_results:
                smat, susage, _ = dense_results["sections"]
            else:
                smat, susage = np.zeros((0, 0), dtype=np.float32), {"input_tokens": None}
            if "passages" in dense_results:
                pmat, pusage, _ = dense_results["passages"]
            else:
                pmat, pusage = np.zeros((0, 0), dtype=np.float32), {"input_tokens": None}
```

### 4.4 BM25 Cache Loading (Optional Enhancement)

Similarly, BM25 tokenization can be loaded from `bm25_inputs.json`. This saves
a few seconds of text tokenization per chapter:

```python
# Before BM25 scoring:
bm25_cache_path = emb_dir / "bm25_inputs.json"
if bool(opt.use_cached_embeddings) and bm25_cache_path.exists():
    bm25_cache = read_json(bm25_cache_path)
    # Use pre-tokenized texts for BM25 construction
    # ... (construct BM25 from cached tokens instead of re-tokenizing)
```

This is a minor optimization (saves ~1-2 seconds) and can be deferred.

### 4.5 Impact Analysis

| Metric              | Before (per chapter)          | After (chapter 2+)    |
| ------------------- | ----------------------------- | --------------------- |
| Embedding API calls | sections + passages + queries | queries only          |
| Embedding API cost  | $0.02–0.05                    | $0.001–0.003          |
| Embedding time      | ~30 sec                       | ~3 sec (queries only) |
| BM25 tokenization   | ~2 sec                        | ~0 sec (cached)       |

For a 5-chapter run: saves ~4 × $0.03 = $0.12 API cost + ~4 × 27s = 108s of time.

---

## Task 5 — Multi-Chapter Orchestrator

### 5.1 Create New File: `run_multi_chapter_pipeline.py`

This orchestrator replaces the sequential `run_pdf_scan_pipeline.py` for multi-chapter runs.

```python
#!/usr/bin/env python3
"""Multi-chapter PDF scan pipeline orchestrator.

Runs phases A→B→C→C.5 once (shared), then fans out D→E→F→G per chapter,
then aggregates with Phase H.

Usage:
    python run_multi_chapter_pipeline.py \
        --chapters-json chapters.json \
        --pdf-dir /path/to/pdfs
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Optional

# Import all phases
from phase_a_lab import (
    PhaseAConfig,
    ChapterSpec,
    RunArtifacts,
    RunContext,
    run_phase_a,
    setup_run_logger,
    stable_hash,
    stage_timer,
    write_json,
    read_json,
)
from phase_b_lab import PhaseBOptions, run_phase_b
from phase_c_lab import PhaseCOptions, run_phase_c
from phase_c5_lab import PhaseC5Options, run_phase_c5
from phase_d_lab import PhaseDOptions, run_phase_d
from phase_e_lab import PhaseEOptions, run_phase_e
from phase_f_lab import PhaseFOptions, run_phase_f
from phase_g_lab import PhaseGOptions, run_phase_g
# from phase_h_lab import PhaseHOptions, run_phase_h  # Task 6


def emit(event_type: str, **kwargs):
    """Emit a structured event to stdout."""
    payload = {"event": event_type, "ts": time.time(), **kwargs}
    print(f"PDF_SCAN_EVENT\t{json.dumps(payload, ensure_ascii=False)}", flush=True)


def run_chapter_pipeline(
    run_ctx: RunContext,
    chapter: ChapterSpec,
    *,
    phase_d_options: PhaseDOptions,
    phase_e_options: PhaseEOptions,
    phase_f_options: PhaseFOptions,
    phase_g_options: PhaseGOptions,
    force_rebuild: bool = False,
) -> Dict[str, Any]:
    """Run D→E→F→G for a single chapter. Thread-safe.

    Returns a dict with chapter_id, status, results, timing, and any error.
    """
    chapter_id = chapter.chapter_id
    started = time.perf_counter()

    try:
        # Get chapter-scoped RunContext
        ch_ctx = run_ctx.for_chapter(chapter_id)
        ch_logger = setup_run_logger(ch_ctx)

        # Write chapter config
        ch_artifacts = run_ctx.artifacts.chapter_artifacts[chapter_id]
        write_json(ch_artifacts.chapter_config_json, {
            "chapter_id": chapter_id,
            "chapter_title": chapter.chapter_title,
            "chapter_spec_text_chars": len(chapter.chapter_spec_text),
        })

        emit("chapter_start", chapter_id=chapter_id, chapter_title=chapter.chapter_title)

        # ── Phase D ──
        emit("stage_start", stage="phase_d", chapter_id=chapter_id)
        d_opts = PhaseDOptions(**{
            **{k: v for k, v in vars(phase_d_options).items() if not k.startswith("_")},
            "force_rebuild": force_rebuild or phase_d_options.force_rebuild,
        })
        with stage_timer(ch_ctx, f"phase_d_{chapter_id}"):
            phase_d_result = run_phase_d(
                ch_ctx,
                chapter_title=chapter.chapter_title,
                chapter_spec_text=chapter.chapter_spec_text,
                options=d_opts,
                stable_hash_fn=stable_hash,
                run_logger=ch_logger,
            )
        emit("stage_complete", stage="phase_d", chapter_id=chapter_id)

        # ── Phase E ──
        emit("stage_start", stage="phase_e", chapter_id=chapter_id)
        e_opts = PhaseEOptions(**{
            **{k: v for k, v in vars(phase_e_options).items() if not k.startswith("_")},
            "force_rebuild": force_rebuild or phase_e_options.force_rebuild,
            "use_cached_embeddings": True,  # Always use C.5 cache
        })
        with stage_timer(ch_ctx, f"phase_e_{chapter_id}"):
            phase_e_result = run_phase_e(
                ch_ctx,
                options=e_opts,
                stable_hash_fn=stable_hash,
                run_logger=ch_logger,
            )
        emit("stage_complete", stage="phase_e", chapter_id=chapter_id)

        # ── Phase F ──
        emit("stage_start", stage="phase_f", chapter_id=chapter_id)
        f_opts = PhaseFOptions(**{
            **{k: v for k, v in vars(phase_f_options).items() if not k.startswith("_")},
            "force_rebuild": force_rebuild or phase_f_options.force_rebuild,
        })
        with stage_timer(ch_ctx, f"phase_f_{chapter_id}"):
            phase_f_result = run_phase_f(
                ch_ctx,
                options=f_opts,
                stable_hash_fn=stable_hash,
                run_logger=ch_logger,
            )
        emit("stage_complete", stage="phase_f", chapter_id=chapter_id)

        # ── Phase G ──
        emit("stage_start", stage="phase_g", chapter_id=chapter_id)
        g_opts = PhaseGOptions(**{
            **{k: v for k, v in vars(phase_g_options).items() if not k.startswith("_")},
            "force_rebuild": force_rebuild or phase_g_options.force_rebuild,
        })
        with stage_timer(ch_ctx, f"phase_g_{chapter_id}"):
            phase_g_result = run_phase_g(
                ch_ctx,
                options=g_opts,
                stable_hash_fn=stable_hash,
                run_logger=ch_logger,
            )
        emit("stage_complete", stage="phase_g", chapter_id=chapter_id)

        elapsed_ms = round((time.perf_counter() - started) * 1000.0, 3)
        emit("chapter_complete", chapter_id=chapter_id, elapsed_ms=elapsed_ms)

        return {
            "chapter_id": chapter_id,
            "status": "complete",
            "elapsed_ms": elapsed_ms,
            "phase_g_result": phase_g_result,
            "error": None,
        }

    except Exception as exc:
        elapsed_ms = round((time.perf_counter() - started) * 1000.0, 3)
        emit("chapter_error", chapter_id=chapter_id, error=str(exc), elapsed_ms=elapsed_ms)
        return {
            "chapter_id": chapter_id,
            "status": "error",
            "elapsed_ms": elapsed_ms,
            "phase_g_result": None,
            "error": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc(),
        }


def resolve_chapter_concurrency(chapter_count: int) -> int:
    """Determine how many chapters to process concurrently.

    Chapters are primarily I/O-bound (OpenAI API calls) in phases D and E,
    and CPU-bound in Phase F (cross-encoder).

    Strategy: Run 2 chapters concurrently. This allows overlapping I/O (D, E)
    with CPU work (F) from other chapters. More than 2 could cause CPU
    contention during cross-encoder inference.
    """
    if chapter_count <= 1:
        return 1
    # Allow 2 concurrent chapters to overlap I/O and CPU
    return min(chapter_count, 2)


def load_chapters_json(path: str) -> List[Dict[str, str]]:
    """Load chapter specifications from a JSON file.

    Expected format:
    [
        {
            "chapter_id": "chapter_01",
            "chapter_title": "Introduction to ML",
            "chapter_spec_text": "This chapter covers..."
        },
        ...
    ]
    """
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, list) or not data:
        raise ValueError("chapters JSON must be a non-empty array")
    chapters = []
    for i, item in enumerate(data):
        if not isinstance(item, dict):
            raise ValueError(f"Chapter {i} must be an object")
        cid = str(item.get("chapter_id") or f"chapter_{i+1:02d}").strip()
        title = str(item.get("chapter_title") or "").strip()
        spec = str(item.get("chapter_spec_text") or "").strip()
        if not title:
            raise ValueError(f"Chapter {i} missing chapter_title")
        if not spec:
            raise ValueError(f"Chapter {i} missing chapter_spec_text")
        chapters.append({"chapter_id": cid, "chapter_title": title, "chapter_spec_text": spec})
    return chapters


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Multi-chapter PDF scan pipeline")
    parser.add_argument("--chapters-json", required=True, help="Path to JSON file with chapter specs")
    parser.add_argument("--pdf-dir", required=True, help="Directory containing PDF files")
    parser.add_argument("--pipeline-version", default="pdf_scan_v3_multi_chapter")
    parser.add_argument("--runs-root", default="")
    parser.add_argument("--pdf-glob", default="*.pdf")
    parser.add_argument("--pdf-recursive", action="store_true")
    parser.add_argument("--max-pdfs", type=int, default=20)
    parser.add_argument("--force-rebuild", action="store_true")
    parser.add_argument("--max-chapter-concurrency", type=int, default=0, help="0=auto")
    parser.add_argument("--grobid-base-url", default="")
    parser.add_argument("--no-openai-dense", action="store_true")
    parser.add_argument("--no-openai-judge", action="store_true")
    parser.add_argument("--no-openai-planner", action="store_true")

    args = parser.parse_args(list(argv or sys.argv[1:]))

    # Load chapters
    raw_chapters = load_chapters_json(args.chapters_json)
    chapter_specs = [
        ChapterSpec(
            chapter_id=ch["chapter_id"],
            chapter_title=ch["chapter_title"],
            chapter_spec_text=ch["chapter_spec_text"],
        )
        for ch in raw_chapters
    ]
    emit("pipeline_start", chapter_count=len(chapter_specs), chapters=[ch["chapter_id"] for ch in raw_chapters])

    pdf_dir = Path(args.pdf_dir).resolve()

    try:
        # ═══════════════════════════════════════════
        # SHARED PHASES: A → B → C → C.5
        # ═══════════════════════════════════════════

        # ── Phase A ──
        emit("stage_start", stage="phase_a", label="Initialization")
        from argparse import Namespace
        phase_a_args = Namespace(
            input_mode="manual",
            pipeline_version=args.pipeline_version,
            force_rebuild=args.force_rebuild,
            runs_root=args.runs_root,
            suite_manifest="", chapter_index=0, doc_limit=None,
            include_doc_id=[], exclude_doc_id=[],
            # Multi-chapter: pass all chapter specs
            chapters=chapter_specs,
            chapter_title=chapter_specs[0].chapter_title,  # backward compat
            chapter_description=chapter_specs[0].chapter_spec_text,  # backward compat
            pdf=[], pdf_dir=str(pdf_dir),
            pdf_glob=args.pdf_glob, pdf_recursive=args.pdf_recursive,
            max_pdfs=args.max_pdfs,
        )
        phase_a_result = run_phase_a(phase_a_args)
        run_ctx = phase_a_result["run_ctx"]
        pdf_manifest = phase_a_result["manifest_rows"]
        emit("run_initialized", pipeline_run_id=str(run_ctx.run_id), document_count=len(pdf_manifest), chapter_count=len(chapter_specs))
        emit("stage_complete", stage="phase_a")

        # ── Phase B ──
        emit("stage_start", stage="phase_b", label="PDF Parsing", total=len(pdf_manifest))
        phase_b_options = PhaseBOptions(
            force_rebuild=args.force_rebuild,
            try_docling=True,
            docling_num_threads=2,  # Speed-up guide Task 4
            try_grobid=True,
            grobid_base_url=args.grobid_base_url,
        )
        phase_b_logger = setup_run_logger(run_ctx)
        with stage_timer(run_ctx, "phase_b"):
            phase_b_result = run_phase_b(run_ctx, pdf_manifest, phase_b_options, stable_hash_fn=stable_hash, run_logger=phase_b_logger)
        emit("stage_complete", stage="phase_b")

        # ── Phase C ──
        emit("stage_start", stage="phase_c", label="Section Normalization")
        phase_c_options = PhaseCOptions(force_rebuild=args.force_rebuild)
        phase_c_logger = setup_run_logger(run_ctx)
        with stage_timer(run_ctx, "phase_c"):
            phase_c_result = run_phase_c(run_ctx, phase_c_options, stable_hash_fn=stable_hash, run_logger=phase_c_logger)
        emit("stage_complete", stage="phase_c")

        # ── Phase C.5 (NEW) ──
        emit("stage_start", stage="phase_c5", label="Embedding Cache")
        phase_c5_options = PhaseC5Options(
            force_rebuild=args.force_rebuild,
            openai_embedding_model="text-embedding-3-small",
        )
        phase_c5_logger = setup_run_logger(run_ctx)
        with stage_timer(run_ctx, "phase_c5"):
            phase_c5_result = run_phase_c5(run_ctx, options=phase_c5_options, stable_hash_fn=stable_hash, run_logger=phase_c5_logger)
        emit("stage_complete", stage="phase_c5")

        # ═══════════════════════════════════════════
        # PER-CHAPTER PHASES: D → E → F → G (parallel)
        # ═══════════════════════════════════════════

        if args.max_chapter_concurrency > 0:
            chapter_concurrency = min(len(chapter_specs), args.max_chapter_concurrency)
        else:
            chapter_concurrency = resolve_chapter_concurrency(len(chapter_specs))

        emit("chapter_fanout_start", chapter_count=len(chapter_specs), concurrency=chapter_concurrency)

        # Shared options for all chapters
        phase_d_options = PhaseDOptions(
            force_rebuild=args.force_rebuild,
            use_openai_planner=not args.no_openai_planner,
        )
        phase_e_options = PhaseEOptions(
            force_rebuild=args.force_rebuild,
            use_openai_dense=not args.no_openai_dense,
            use_cached_embeddings=True,
        )
        phase_f_options = PhaseFOptions(
            force_rebuild=args.force_rebuild,
            use_openai_judge=not args.no_openai_judge,
            cross_encoder_batch_size=32,  # Speed-up guide Task 2
        )
        phase_g_options = PhaseGOptions(
            force_rebuild=args.force_rebuild,
        )

        chapter_results: Dict[str, Dict[str, Any]] = {}

        if chapter_concurrency <= 1:
            # Sequential execution
            for chapter in chapter_specs:
                result = run_chapter_pipeline(
                    run_ctx, chapter,
                    phase_d_options=phase_d_options,
                    phase_e_options=phase_e_options,
                    phase_f_options=phase_f_options,
                    phase_g_options=phase_g_options,
                    force_rebuild=args.force_rebuild,
                )
                chapter_results[chapter.chapter_id] = result
        else:
            # Concurrent execution
            with ThreadPoolExecutor(max_workers=chapter_concurrency) as executor:
                futures = {
                    executor.submit(
                        run_chapter_pipeline,
                        run_ctx, chapter,
                        phase_d_options=phase_d_options,
                        phase_e_options=phase_e_options,
                        phase_f_options=phase_f_options,
                        phase_g_options=phase_g_options,
                        force_rebuild=args.force_rebuild,
                    ): chapter
                    for chapter in chapter_specs
                }
                for future in as_completed(futures):
                    chapter = futures[future]
                    result = future.result()
                    chapter_results[chapter.chapter_id] = result

        emit("chapter_fanout_complete", results={
            cid: {"status": r["status"], "elapsed_ms": r["elapsed_ms"]}
            for cid, r in chapter_results.items()
        })

        # ═══════════════════════════════════════════
        # PHASE H: Aggregate  (Task 6)
        # ═══════════════════════════════════════════

        # TODO: Phase H aggregation (see Task 6 below)
        # For now, emit summary of chapter results

        completed = [r for r in chapter_results.values() if r["status"] == "complete"]
        failed = [r for r in chapter_results.values() if r["status"] == "error"]

        summary = {
            "pipeline_run_id": str(run_ctx.run_id),
            "run_dir": str(run_ctx.run_dir),
            "chapter_count": len(chapter_specs),
            "completed_chapters": len(completed),
            "failed_chapters": len(failed),
            "chapter_results": {
                cid: {
                    "status": r["status"],
                    "elapsed_ms": r["elapsed_ms"],
                    "error": r.get("error"),
                    "useful_pdfs": (
                        len([d for d in (r.get("phase_g_result") or {}).get("doc_feature_rows", []) if d.get("has_useful_information")])
                        if r["status"] == "complete" else None
                    ),
                }
                for cid, r in chapter_results.items()
            },
        }

        emit("run_complete", **summary)
        print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
        return 0 if not failed else 1

    except Exception as exc:
        emit("run_error", error_type=type(exc).__name__, error_message=str(exc))
        raise


if __name__ == "__main__":
    sys.exit(main())
```

### 5.2 Chapter Concurrency Considerations

**Why limit to 2 concurrent chapters?**

- Phase F (cross-encoder) is CPU-bound and takes the most time
- With ONNX (from Speed-Up Guide), cross-encoder still uses all CPU cores
- Running 2 chapters means one is typically in I/O phase (D, E) while the other
  is in CPU phase (F), giving good overlap
- More than 2 could cause CPU thrashing during concurrent F phases

**The user can override** with `--max-chapter-concurrency`:

- `--max-chapter-concurrency 1`: Sequential (safe, no concurrency issues)
- `--max-chapter-concurrency 3`: For machines with 16+ cores
- `--max-chapter-concurrency 5`: For powerful servers

### 5.3 Thread Safety Notes

Each chapter pipeline call is isolated because:

- Each chapter has its own `ChapterArtifacts` with unique directory paths
- File writes are to separate directories (`chapters/chapter_01/`, `chapters/chapter_02/`)
- `run_phase_d/e/f/g` only write to paths derived from `run_ctx.artifacts`
- The shared Phase C.5 embeddings are **read-only** during per-chapter phases
- `log_event()` and `record_api_call()` write to shared `logs.jsonl` / `api_calls.jsonl`
  — these need thread-safe writes (append-mode file writes are atomic on Linux for small sizes)

**Potential issue**: `setup_run_logger()` creates a file handler for `run.log`.
Multiple chapters sharing the same file handler could interleave. Solution:

- Give each chapter its own logger name: `setup_run_logger(ch_ctx, name=f"chapter_{chapter_id}")`
- Or write chapter logs to separate files: `chapters/{chapter_id}/chapter.log`

### 5.4 Input Format: chapters.json

```json
[
  {
    "chapter_id": "chapter_01",
    "chapter_title": "Introduction to Machine Learning",
    "chapter_spec_text": "This chapter provides a comprehensive introduction to machine learning, covering supervised learning, unsupervised learning, and reinforcement learning approaches. Key topics include..."
  },
  {
    "chapter_id": "chapter_02",
    "chapter_title": "Deep Learning Architectures",
    "chapter_spec_text": "This chapter explores modern deep learning architectures including convolutional neural networks, transformers, and generative models..."
  },
  {
    "chapter_id": "chapter_03",
    "chapter_title": "Ethics in AI",
    "chapter_spec_text": "This chapter examines ethical considerations in artificial intelligence, including bias, fairness, transparency, and accountability..."
  }
]
```

---

## Task 6 — Phase H: Cross-Chapter Aggregation

### 6.1 Purpose

After all chapters complete D→E→F→G, Phase H aggregates results into a unified
cross-chapter output. This includes:

1. Per-chapter results summary
2. Cross-chapter document importance (which PDFs are useful for which chapters)
3. Overlap analysis (sections appearing in multiple chapters)
4. Combined metrics and cost tracking

### 6.2 Create New File: `phase_h_lab.py`

```python
#!/usr/bin/env python3
"""Phase H — Cross-Chapter Aggregation

Reads the per-chapter Phase G outputs and produces a unified output that
shows which PDFs are useful for which chapters and identifies overlap.

Outputs (in run_dir/aggregate/):
  - output.json              Unified cross-chapter output
  - phase_h_config.json      Configuration
  - phase_h_summary.json     Summary statistics
  - cross_chapter_matrix.json  PDF × chapter relevance matrix
"""
from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from phase_a_lab import (
    ensure_dir,
    json_safe,
    read_json,
    read_jsonl_rows,
    utc_now_iso,
    write_json,
)


@dataclass
class PhaseHOptions:
    force_rebuild: bool = False

    def normalized(self) -> "PhaseHOptions":
        return PhaseHOptions(force_rebuild=bool(self.force_rebuild))


def run_phase_h(
    run_ctx: Any,
    *,
    chapter_results: Dict[str, Dict[str, Any]],
    options: PhaseHOptions,
    run_logger=None,
) -> Dict[str, Any]:
    """Aggregate per-chapter results into a unified cross-chapter output.

    Args:
        run_ctx: RunContext with artifact paths
        chapter_results: Dict mapping chapter_id → run_chapter_pipeline result
        options: PhaseHOptions
    """
    opt = options.normalized()
    aggregate_dir = ensure_dir(Path(run_ctx.artifacts.aggregate_dir))
    config_path = aggregate_dir / "phase_h_config.json"
    summary_path = aggregate_dir / "phase_h_summary.json"
    output_path = aggregate_dir / "output.json"
    matrix_path = aggregate_dir / "cross_chapter_matrix.json"

    # Cache check
    if not bool(opt.force_rebuild) and output_path.exists() and summary_path.exists():
        return {"status": "cached", "summary": read_json(summary_path)}

    write_json(config_path, {"generated_at_utc": utc_now_iso(), "phase": "phase_h", "options": json_safe(asdict(opt))})

    started = time.perf_counter()

    # Collect per-chapter outputs
    chapter_outputs = {}
    for chapter_id, result in chapter_results.items():
        if result.get("status") != "complete":
            chapter_outputs[chapter_id] = {"status": "error", "error": result.get("error")}
            continue

        ch_artifacts = run_ctx.artifacts.chapter_artifacts.get(chapter_id)
        if ch_artifacts is None:
            continue

        final_output_path = ch_artifacts.final_dir / "output.json"
        doc_features_path = ch_artifacts.final_dir / "doc_features.jsonl"
        section_scores_path = ch_artifacts.final_dir / "section_scores.jsonl"

        if final_output_path.exists():
            chapter_outputs[chapter_id] = {
                "status": "complete",
                "output": read_json(final_output_path),
                "doc_features": read_jsonl_rows(doc_features_path) if doc_features_path.exists() else [],
                "section_scores": read_jsonl_rows(section_scores_path) if section_scores_path.exists() else [],
            }

    # Build cross-chapter document matrix
    # doc_id → { chapter_id → { useful: bool, top_score: float, useful_sections: int } }
    doc_chapter_matrix = defaultdict(dict)
    all_doc_ids = set()

    for chapter_id, ch_out in chapter_outputs.items():
        if ch_out.get("status") != "complete":
            continue
        for doc_row in ch_out.get("doc_features", []):
            doc_id = str(doc_row.get("doc_id") or "")
            if not doc_id:
                continue
            all_doc_ids.add(doc_id)
            doc_chapter_matrix[doc_id][chapter_id] = {
                "has_useful_information": bool(doc_row.get("has_useful_information")),
                "probability": float(doc_row.get("probability") or 0.0),
                "useful_section_count": int(doc_row.get("useful_section_count") or 0),
                "partial_section_count": int(doc_row.get("partial_section_count") or 0),
            }

    # Build section overlap (sections that appear across multiple chapters)
    section_chapters = defaultdict(set)  # section_id → set of chapter_ids
    for chapter_id, ch_out in chapter_outputs.items():
        if ch_out.get("status") != "complete":
            continue
        for sec_row in ch_out.get("section_scores", []):
            section_id = str(sec_row.get("section_id") or "")
            score = float(sec_row.get("calibrated_score") or sec_row.get("final_score") or 0.0)
            if section_id and score > 0.2:  # Only count sections with meaningful scores
                section_chapters[section_id].add(chapter_id)

    multi_chapter_sections = {
        sid: sorted(list(chapters))
        for sid, chapters in section_chapters.items()
        if len(chapters) > 1
    }

    # Compute statistics
    completed_chapters = [cid for cid, ch in chapter_outputs.items() if ch.get("status") == "complete"]
    failed_chapters = [cid for cid, ch in chapter_outputs.items() if ch.get("status") == "error"]

    # Per-doc summary
    doc_summaries = []
    for doc_id in sorted(all_doc_ids):
        chapters_data = doc_chapter_matrix.get(doc_id, {})
        useful_for = [cid for cid, info in chapters_data.items() if info.get("has_useful_information")]
        doc_summaries.append({
            "doc_id": doc_id,
            "useful_for_chapters": sorted(useful_for),
            "useful_chapter_count": len(useful_for),
            "total_chapters_evaluated": len(chapters_data),
            "per_chapter": chapters_data,
        })

    # Sort by how many chapters find the doc useful (most useful first)
    doc_summaries.sort(key=lambda d: (-d["useful_chapter_count"], d["doc_id"]))

    elapsed_ms = round((time.perf_counter() - started) * 1000.0, 3)

    output = {
        "generated_at_utc": utc_now_iso(),
        "run_id": run_ctx.run_id,
        "chapter_count": len(chapter_results),
        "completed_chapters": sorted(completed_chapters),
        "failed_chapters": sorted(failed_chapters),
        "document_count": len(all_doc_ids),
        "documents": doc_summaries,
        "multi_chapter_sections": {
            "count": len(multi_chapter_sections),
            "sections": multi_chapter_sections,
        },
        "per_chapter_summary": {
            cid: {
                "status": ch.get("status"),
                "useful_doc_count": len([d for d in ch.get("doc_features", []) if d.get("has_useful_information")]),
                "total_doc_count": len(ch.get("doc_features", [])),
            }
            for cid, ch in chapter_outputs.items()
        },
    }

    write_json(output_path, output)
    write_json(matrix_path, {"doc_chapter_matrix": dict(doc_chapter_matrix)})

    summary = {
        "generated_at_utc": utc_now_iso(),
        "phase": "phase_h",
        "status": "complete",
        "completed_chapters": len(completed_chapters),
        "failed_chapters": len(failed_chapters),
        "total_documents": len(all_doc_ids),
        "multi_chapter_section_count": len(multi_chapter_sections),
        "elapsed_ms": elapsed_ms,
    }
    write_json(summary_path, summary)

    if run_logger:
        run_logger.info(
            "Phase H complete | chapters=%d/%d | docs=%d | shared_sections=%d | elapsed=%dms",
            len(completed_chapters), len(chapter_results), len(all_doc_ids),
            len(multi_chapter_sections), elapsed_ms,
        )

    return {"status": "complete", "summary": summary, "output": output}
```

### 6.3 The Cross-Chapter Matrix

The key output is a document × chapter relevance matrix:

```json
{
  "doc_chapter_matrix": {
    "doc_abc123": {
      "chapter_01": {
        "has_useful_information": true,
        "probability": 0.87,
        "useful_section_count": 3
      },
      "chapter_02": {
        "has_useful_information": false,
        "probability": 0.12,
        "useful_section_count": 0
      }
    }
  }
}
```

This enables the downstream consumer (FastAPI / Firestore) to answer:

- "Which PDFs are relevant to Chapter 2?"
- "Which PDFs are relevant to multiple chapters?"
- "For each PDF, which chapters find it useful?"

---

## 7. Concurrency Model

### Timeline for 3-Chapter Run (13 PDFs)

```
Time (min)  0    5   10   15   20   25   30   35   40   45   50   55   60   65
Phase A     |=|
Phase B     |████████████████████|
Phase C                          |██|
Phase C.5                            |=|
                                      ├── Chapter 1: D(4m) E(3s) F(25m) G(0s)
                                      ├── Chapter 2: D(4m) E(3s) F(25m) G(0s)
                                      └── Chapter 3: (waits for slot)
                                                     D(4m) E(3s) F(25m) G(0s)
Phase H                                                                     |=|
```

**With 2 concurrent chapters + speed-up optimizations**:

- Shared phases: A(0.1s) + B(20m) + C(1m) + C.5(0.5m) = ~22 min
- Ch 1+2 concurrent: D(4m) + E(3s) + F(25m) + G(0.1s) = ~29 min
- Ch 3 starts when Ch 1 or 2 finishes F: ~29 min
- Phase H: ~1s
- **Total for 3 chapters: ~51 min** (vs 128 min × 3 = 384 min sequential)

### Resource Usage Per Phase

| Phase           | CPU                      | Memory                   | Network                    |
| --------------- | ------------------------ | ------------------------ | -------------------------- |
| B (shared)      | HIGH (Docling ML)        | HIGH (2–4 GB)            | LOW (GROBID HTTP)          |
| C (shared)      | MEDIUM (regex, NLP)      | LOW (500 MB)             | NONE                       |
| C.5 (shared)    | LOW (I/O wait)           | LOW (embedding matrices) | HIGH (OpenAI API)          |
| D (per chapter) | LOW (I/O wait)           | LOW                      | MEDIUM (2 OpenAI calls)    |
| E (per chapter) | MEDIUM (BM25, cosine)    | MEDIUM (embedding mats)  | LOW (query embedding only) |
| F (per chapter) | **HIGH** (cross-encoder) | HIGH (1.5–2.5 GB)        | MEDIUM (judge calls)       |
| G (per chapter) | LOW (arithmetic)         | LOW                      | NONE                       |

### Cross-Encoder Memory: Multiple Chapters

The cross-encoder model is loaded via `@lru_cache` so only one copy exists in memory,
regardless of how many chapters are running. The main concern is that two concurrent
Phase F runs will fight for CPU cores.

With ONNX Runtime, thread control is per-session. To avoid contention:

- Set `sess_options.intra_op_num_threads = max(1, cpu_count // 2)` when running 2 chapters
- Or let ONNX auto-manage (it handles thread sharing well)

---

## 8. Error Handling & Isolation

### Per-Chapter Error Isolation

```python
# In run_chapter_pipeline():
try:
    # ... D → E → F → G ...
    return {"chapter_id": chapter_id, "status": "complete", ...}
except Exception as exc:
    return {"chapter_id": chapter_id, "status": "error", "error": str(exc), ...}
```

If Chapter 2 fails during Phase F, Chapters 1 and 3 continue normally.

### Error Recovery

Because each chapter writes to its own directory, a partially failed chapter can be
re-run independently:

```python
# Re-run only Chapter 2
result = run_chapter_pipeline(run_ctx, chapter_specs[1], ...)
```

The shared phases (A–C.5) are cached and will be skipped.

### Shared Phase Failures

If a shared phase (A, B, C, C.5) fails, the entire pipeline fails — no chapters
can run. This is correct behavior since chapters depend on the shared corpus.

---

## 9. Firestore Structure (Future Reference)

> This section is for future FastAPI integration — NOT implemented in `pdf-scan/`.

### Proposed Firestore Layout

```
users/{userId}/projects/{projektId}/researchRuns/{runId}/
  ├── (run document fields)
  │   ├── kind: "pdfScan"
  │   ├── status: "running" | "complete" | "error"
  │   ├── chapterCount: 3
  │   ├── completedChapters: 2
  │   ├── failedChapters: 0
  │   ├── pipelineStages: { phase_a: {...}, phase_b: {...}, ... }
  │   └── progress: { phase: "phase_f", chapter: "chapter_02", percent: 45 }
  │
  ├── pdfScanDocs/{docId}           # Shared: one document per PDF
  │   ├── fileName, pageCount, sha256, ...
  │   ├── chapters: {               # NEW: per-chapter relevance
  │   │   "chapter_01": { useful: true, probability: 0.87, topSections: [...] },
  │   │   "chapter_02": { useful: false, probability: 0.12 }
  │   │ }
  │   └── usefulForChapterIds: ["chapter_01"]  # Denormalized for queries
  │
  ├── pdfScanSections/{sectionId}   # Shared: one document per section
  │   ├── docId, title, sectionType, pageStart, pageEnd, ...
  │   ├── chapters: {               # Per-chapter scores
  │   │   "chapter_01": { score: 78, rank: 3 },
  │   │   "chapter_02": { score: 12, rank: 45 }
  │   │ }
  │   └── relevantChapterIds: ["chapter_01"]
  │
  └── chapters/{chapterId}           # NEW: per-chapter summary
      ├── chapterTitle, chapterSpecText
      ├── status: "complete" | "error"
      ├── usefulDocCount, totalDocCount
      ├── runElapsedMs
      └── queryPlanSummary: { mustTerms: [...], subpoints: [...] }
```

### Key Firestore Design Principles

1. **Documents are shared**: `pdfScanDocs` and `pdfScanSections` exist once, with
   per-chapter data embedded in a `chapters` map field
2. **Denormalized arrays for queries**: `usefulForChapterIds` enables efficient
   Firestore queries like "give me all docs useful for chapter_01"
3. **Chapter subcollection**: Each chapter has its own summary document
4. **Progressive updates**: As each chapter completes, update the `chapters` map
   in affected documents

---

## 10. Dependency & Rollout Order

```
Task 1 (PhaseAConfig) ──→ Task 2 (RunArtifacts) ──→ Task 3 (Phase C.5)
                                                          │
                                                          ├──→ Task 4 (Phase E refactor)
                                                          │        │
                                                          │        ├──→ Task 5 (Orchestrator)
                                                          │        │         │
                                                          │        │         └──→ Task 6 (Phase H)
                                                          │        │
                                                          └────────┘
```

**Recommended implementation order**:

1. **Task 1** (PhaseAConfig) — Foundation: multi-chapter data model
2. **Task 2** (RunArtifacts/RunContext) — Foundation: chapter-aware paths
3. **Task 3** (Phase C.5) — Embedding cache (provides the data Task 4 needs)
4. **Task 4** (Phase E refactor) — Consume cached embeddings
5. **Task 5** (Orchestrator) — Wire everything together
6. **Task 6** (Phase H) — Aggregation (can be done last)

### Testing Strategy Between Tasks

After **Task 2**: Run old single-chapter pipeline. Verify backward-compat properties
(`artifacts.retrieval_dir`, etc.) resolve to `chapters/chapter_01/retrieval/`.

After **Task 3**: Run pipeline through C.5. Verify `.npy` files created in `embeddings/`.

After **Task 4**: Run Phase E. Verify it loads cached embeddings (`dense_trace.dense_mode == "cached_c5"`).

After **Task 5**: Run full multi-chapter pipeline with `chapters.json`. Verify:

- Shared phases run once
- Each chapter has its own directory
- Chapters run concurrently (check timestamps in logs)

After **Task 6**: Verify `aggregate/output.json` has correct cross-chapter matrix.

---

## 11. Validation Checklist

### Backward Compatibility

- [ ] Single-chapter runs still work with `chapters=[ChapterSpec(chapter_id="chapter_01", ...)]`
- [ ] `config.chapter_title` and `config.chapter_spec_text` properties work
- [ ] `artifacts.retrieval_dir` resolves to `chapters/chapter_01/retrieval/`
- [ ] Old `run_pdf_scan_pipeline.py` (in fastapi/) still works without changes

### Phase C.5

- [ ] `section_embeddings.npy` has shape `[num_sections, embed_dim]`
- [ ] `section_ids.json` matches the section IDs in `sections.jsonl`
- [ ] Embeddings are L2-normalized (norm ≈ 1.0 for each row)
- [ ] Cache check works (second run skips embedding computation)
- [ ] API cost is tracked correctly

### Phase E with Cache

- [ ] Loads cached embeddings when available
- [ ] Falls back to re-embedding when cache missing or IDs mismatch
- [ ] Only makes API calls for query embeddings (not section/passage)
- [ ] Scores match between cached and fresh embedding runs

### Multi-Chapter Orchestrator

- [ ] 3-chapter run completes successfully
- [ ] Each chapter has correct output in `chapters/{chapter_id}/final/output.json`
- [ ] Chapters 2 and 3 produce different results (different query plans)
- [ ] If one chapter errors, others still complete
- [ ] Concurrent execution happens (check log timestamps)
- [ ] Events emitted correctly for monitoring

### Phase H Aggregation

- [ ] `aggregate/output.json` contains all chapter results
- [ ] Cross-chapter matrix shows correct PDF × chapter relationships
- [ ] Multi-chapter sections are identified
- [ ] Failed chapters are reported but don't block aggregation

### Performance

- [ ] 3-chapter run takes < 70 min total (with speed-up optimizations)
- [ ] Document embedding cost incurred only once (check API calls log)
- [ ] Memory stays within 16 GB on Cloud Run (4 vCPU)

---

## Appendix: File-Level Change Summary

| File                            | Task | Action                                                                                     |
| ------------------------------- | ---- | ------------------------------------------------------------------------------------------ |
| `phase_a_lab.py`                | 1, 2 | Add `ChapterSpec`, modify `PhaseAConfig`, `RunArtifacts`, `RunContext`, `compute_run_id()` |
| `phase_c5_lab.py`               | 3    | **New file**: Embedding & BM25 cache                                                       |
| `phase_e_lab.py`                | 4    | Add cached embedding loading logic, new `PhaseEOptions` fields                             |
| `run_multi_chapter_pipeline.py` | 5    | **New file**: Multi-chapter orchestrator                                                   |
| `phase_h_lab.py`                | 6    | **New file**: Cross-chapter aggregation                                                    |

**Files NOT modified**: `phase_b_lab.py`, `phase_c_lab.py`, `phase_d_lab.py`, `phase_f_lab.py`, `phase_g_lab.py`.

All per-chapter phases (D, E, F, G) work unchanged — they receive a chapter-scoped
`RunContext` that makes them write to the correct subdirectory.
