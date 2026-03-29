# Main App Multi-Chapter PDF-Scan Integration Plan

## Goal

Integrate the new multi-chapter PDF-scan pipeline from `pdf-scan/` into the main app so that:

- new PDF-scan runs can target one or many chapters in one run
- the main app uses the split production execution path that already exists:
  - CPU job for shared work and chapter-local `D/E`
  - GPU job for chapter-local `F/G` and aggregate `H`
- old historical PDF-scan runs are migrated into the new v2 structure before frontend cutover
- new runs are stored in a clean, chapter-aware Firebase structure
- the frontend exposes all required functionality:
  - multi-chapter input selection
  - run overview across chapters
  - per-chapter result browsing
  - aggregate cross-chapter views
- stale single-chapter-only code is removed after migration and cutover

This document is written as the implementation source of truth for the migration.

## Scope

In scope:

- Firestore schema v2 for PDF-scan runs
- Cloud Storage artifact layout for v2 runs
- FastAPI request/validation/execution/persistence changes
- frontend state model, component structure, and v2-only rendering after migration
- migration script and migration rollout
- rollout, testing, and cleanup

Out of scope:

- changing the underlying `pdf-scan/` local pipeline logic beyond what is required to expose chapter-aware progress/events into FastAPI

## External Constraints That Drive The Design

The data model and rollout should respect the following official Firestore constraints:

- Firestore is built around documents and subcollections, so hierarchical per-run and per-chapter data is a natural fit.
  - Source: <https://firebase.google.com/docs/firestore/data-model>
- Firestore documents have a maximum size of `1 MiB`, so large aggregate JSON payloads must not be stored as one giant document.
  - Source: <https://firebase.google.com/docs/firestore/quotas>
- Firestore best practices recommend exempting large string fields from indexing when they are not queried, to reduce index storage and write costs.
  - Source: <https://firebase.google.com/docs/firestore/best-practices>
- Collection group queries require indexes and extra care. For the first app integration, the design should avoid making the client depend on them.
  - Source: <https://firebase.google.com/docs/firestore/query-data/queries>
- Deleting a parent document does not delete its subcollections. Any “replace results” logic for nested run data must explicitly clear nested subcollections.
  - Source: <https://firebase.google.com/docs/firestore/manage-data/delete-data>
- Batched writes are atomic, which is useful for chunked projection writes, but writes still need to be chunked conservatively for large result sets.
  - Source: <https://firebase.google.com/docs/firestore/manage-data/transactions>

## Current State

### Frontend

Current PDF-scan frontend assumptions live primarily in:

- `app/components/pdf-scan/PdfScanWorkspace.tsx`
- `app/lib/firestore/refs.ts`
- `app/lib/firestore/types.ts`

Current behavior:

- exactly one selected chapter for starting a run
- one flat run result model per `researchRuns/{runId}`
- flat result subcollections:
  - `pdfScanDocs`
  - `pdfScanSections`
- run labels and active state assume `kapitelSnapshots?.[0]`
- the component conflates:
  - chapter selection for creating the next run
  - chapter selection for viewing a past run

This is the main frontend problem to fix. The current `selectedKapitelId` state is doing two incompatible jobs.

### FastAPI

Current PDF-scan API and persistence assumptions live primarily in:

- `fastapi/models/request.py`
- `fastapi/main.py`
- `fastapi/services/pdf_scan/common.py`
- `fastapi/services/pdf_scan/cpu_job.py`
- `fastapi/services/pdf_scan/gpu_job.py`
- `fastapi/services/quellen_finder_firestore_service.py`

Current behavior:

- request model accepts exactly one `kapitel_id`
- route validates exactly one chapter
- CPU job builds a single `Text Thema.md`
- GPU job persists exactly two flat subcollections:
  - `pdfScanDocs`
  - `pdfScanSections`

### Local Pipeline

The local `pdf-scan/` pipeline already supports the target execution model:

- shared `A/B/C` once per run
- shared within-run dense cache
- chapter-parallel `D/E`
- chapter-local `F/G`
- aggregate `H`
- partial success

The canonical result for multi-chapter runs is now:

- `aggregate/output.json`

The app integration should mirror that structure instead of forcing the new pipeline back into the old flat run shape.

## Core Design Decisions

### 1. Use a schema version and migrate all old PDF-scan runs into v2

Decision:

- add `pdfScanSchemaVersion`
- migrate all terminal historical PDF-scan runs from `v1` to `v2`
- all new runs are `v2`

Why:

- one runtime format is cleaner than a permanent dual-read setup
- it allows removal of flat-result readers, refs, and types
- it reduces long-term UI and backend complexity
- migration is safe because old PDF-scan runs are single-chapter by design

### 2. Keep everything under `researchRuns/{runId}`

Decision:

- all new chapter-aware PDF-scan data stays under the existing research run doc path

Why:

- current security rules already allow read access recursively under `researchRuns/{runId}`
- this minimizes rules changes
- it keeps each run self-contained

### 3. Do not rely on collection group queries in the first implementation

Decision:

- frontend reads explicit per-run subcollections by known paths
- no initial client dependency on collection group queries

Why:

- avoids additional composite indexes and rules complexity
- keeps the first rollout simpler and more deterministic

### 4. Persist only UI projections to Firestore

Decision:

- raw run artifacts stay in Cloud Storage
- Firestore stores compact projections for UI rendering

Why:

- avoids hitting the Firestore document size limit
- avoids excessive write and index costs
- keeps the UI data model stable even if artifact JSON evolves

### 5. One codepath for one or many chapters

Decision:

- new runs always use the v2 schema, even if only one chapter is selected

Why:

- avoids maintaining two active runtime formats
- single-chapter behavior remains effectively the same from a user perspective
- simplifies cleanup later

## Target Firebase Structure

This section defines the new canonical v2 structure.

### Firestore Root

Path:

- `users/{uid}/projects/{projectId}/researchRuns/{runId}`

Keep existing fields:

- `kind`
- `status`
- `projektId`
- `kapitelIds`
- `kapitelSnapshots`
- `pdfIds`
- `progress`
- `pipelineStages`
- `billing`
- `job`
- `splitExecution`
- `createdAt`
- `updatedAt`
- `startedAt`
- `finishedAt`
- `hadPartialFailures`
- `errorMessage`

Add or standardize these v2-only fields:

- `pdfScanSchemaVersion: 2`
- `pdfScanMode: "chapter_matrix"`
- `chapterInputMode: "single" | "multi"`
- `pdfScanSummary`
- `pdfScanArtifacts`
- `pdfScanCounts`
- `pdfScanDisplay`

Recommended run-level v2 payload:

```ts
type PdfScanRunSummaryV2 = {
  chapterCount: number;
  completedChapterCount: number;
  failedChapterCount: number;
  documentCount: number;
  usefulPdfCountAnyChapter: number;
  usefulChapterPairCount: number;
  multiChapterSectionCount: number;
  totalVisibleSectionCount: number;
  aggregateStatus: "success" | "partial_success" | "error";
};

type PdfScanRunCountsV2 = {
  aggregateDocCount: number;
  aggregateSectionCount: number;
  chapterDocCount: number;
  chapterSectionCount: number;
};

type PdfScanRunDisplayV2 = {
  runLabel: string;
  chapterPreview: Array<{ chapterId: string; nummer?: string | null; title?: string | null }>;
  chapterCountLabel: string;
};
```

Rules:

- `status` remains one of the current values for compatibility
- represent partial success as:
  - `status = "success"`
  - `hadPartialFailures = true`
  - `pdfScanSummary.aggregateStatus = "partial_success"`

Do not introduce a new root `status` enum unless the rest of the app is updated globally.

### Firestore Subcollections For New Runs

#### 1. Chapter summaries

Path:

- `researchRuns/{runId}/pdfScanChapters/{chapterId}`

Purpose:

- one doc per requested chapter
- chapter-local status, summary, and progress

Recommended fields:

```ts
type PdfScanChapterDoc = {
  chapterId: string;
  chapterOrder: number;
  kapitelSnapshot: KapitelSnapshot;
  status: "queued" | "running" | "success" | "error" | "cancelled";
  errorMessage?: string | null;
  progress?: QuellenFinderProgress | null;
  pipelineStages?: Record<string, QuellenFinderPipelineStage> | null;
  startedAt?: Timestamp | null;
  finishedAt?: Timestamp | null;
  usefulPdfCount: number;
  documentCount: number;
  visibleSectionCount: number;
  topSectionCount: number;
  outputPath?: string | null;
  docFeaturesPath?: string | null;
  sectionScoresPath?: string | null;
  createdAt: Timestamp;
  updatedAt: Timestamp;
};
```

#### 2. Per-chapter document summaries

Path:

- `researchRuns/{runId}/pdfScanChapters/{chapterId}/docs/{docId}`

Purpose:

- same conceptual role as old `pdfScanDocs`
- scoped to one chapter

Recommended fields:

- keep all current `PdfScanDocSummaryDoc` fields
- add:
  - `chapterId`
  - `chapterOrder`
  - `chapterRank?: number | null`
  - `chapterTitle?: string | null`

#### 3. Per-chapter section results

Path:

- `researchRuns/{runId}/pdfScanChapters/{chapterId}/sections/{docId__sectionId}`

Purpose:

- same conceptual role as old `pdfScanSections`
- scoped to one chapter

Recommended document ID:

- `{docId}__{sectionId}`

Reason:

- avoids collisions if section IDs are only unique within a document

Recommended fields:

- keep all current `PdfScanResultDoc` fields
- add:
  - `chapterId`
  - `chapterOrder`

#### 4. Aggregate document matrix

Path:

- `researchRuns/{runId}/pdfScanAggregateDocs/{docId}`

Purpose:

- one row per PDF across all chapters
- drives the new overview UI

Recommended fields:

```ts
type PdfScanAggregateDoc = {
  pdfId: string;
  docId: string;
  pdfFilename?: string | null;
  pdfLabel: string;
  docTitle: string;
  usefulForChapters: string[];
  usefulChapterCount: number;
  bestChapterMatch: {
    chapterId: string;
    docMatchProbability?: number | null;
    topSectionScore?: number | null;
    topSectionTitle?: string | null;
  } | null;
  perChapter: Record<
    string,
    {
      hasUsefulInformation: boolean;
      docMatchProbability?: number | null;
      topSectionScore?: number | null;
      topSectionTitle?: string | null;
      abstentionReason?: string | null;
    }
  >;
  createdAt: Timestamp;
};
```

Notes:

- the `perChapter` map is acceptable here because chapter counts are modest
- do not store long evidence text in aggregate docs

#### 5. Aggregate multi-chapter sections

Path:

- `researchRuns/{runId}/pdfScanAggregateSections/{docId__sectionId}`

Purpose:

- sections that are useful for more than one chapter
- supports “cross-chapter overlap” UI

Recommended fields:

```ts
type PdfScanAggregateSection = {
  pdfId: string;
  docId: string;
  docTitle: string;
  sectionId: string;
  title?: string | null;
  sectionType?: string | null;
  pageStart?: number | null;
  pageEnd?: number | null;
  chapterIds: string[];
  chapterCount: number;
  createdAt: Timestamp;
};
```

### Cloud Storage Artifact Structure

Keep the existing bucket-based artifact handoff, but make the final artifact layout explicitly chapter-aware.

Recommended prefix:

- `pdf-scan-runs/{userId}/{projectId}/{runId}/`

Recommended object layout:

- `handoff/manifest.json`
- `handoff/bundle.tar.zst`
- `final/shared/...`
- `final/chapters/{chapterId}/retrieval/...`
- `final/chapters/{chapterId}/rerank/...`
- `final/chapters/{chapterId}/final/...`
- `final/aggregate/output.json`
- `final/aggregate/cross_chapter_matrix.json`

Run doc `pdfScanArtifacts` should store only:

- bucket name
- base prefix
- handoff manifest URI
- final artifacts prefix URI
- a small preview list of uploaded URIs

Do not mirror the entire artifact tree into Firestore.

## Migration Strategy

The app should not carry permanent legacy runtime support for flat PDF-scan results.

The correct target state is:

- all old PDF-scan runs are migrated to v2
- all new PDF-scan runs are written as v2
- the frontend renders only v2
- the backend persists only v2
- old flat subcollections and flat-only code are deleted after migration verification

### Which runs need migration

Migrate every PDF-scan run where:

- `kind == "pdf_scan"`
- `pdfScanSchemaVersion` is missing or `< 2`
- `status` is terminal:
  - `success`
  - `error`
  - `cancelled`

Do not migrate non-terminal runs during the first pass.

For old active runs:

- wait until they finish
- rerun the migration script
- do not cut the frontend to v2-only until no active v1 runs remain

### Migration output target

Each migrated old run becomes a normal v2 run with:

- `pdfScanSchemaVersion = 2`
- `pdfScanMode = "chapter_matrix"`
- `chapterInputMode = "single"`
- one `pdfScanChapters/{chapterId}` doc
- one `pdfScanChapters/{chapterId}/docs/*` subtree copied from old `pdfScanDocs`
- one `pdfScanChapters/{chapterId}/sections/*` subtree copied from old `pdfScanSections`
- one `pdfScanAggregateDocs/*` projection derived from the old flat doc summaries
- an empty `pdfScanAggregateSections` collection unless there is explicit overlap data to synthesize

This is valid because all historical PDF-scan runs were single-chapter runs.

### Migration metadata

Every migrated run should be stamped with:

```ts
type PdfScanMigrationMeta = {
  migratedFromSchemaVersion: 1;
  migratedToSchemaVersion: 2;
  migrationStatus: "migrated";
  migrationScriptVersion: string;
  migratedAt: Timestamp;
  migratedBy: string;
  sourceFlatDocCount: number;
  sourceFlatSectionCount: number;
  targetChapterDocCount: number;
  targetChapterSectionCount: number;
  targetAggregateDocCount: number;
};
```

Recommended root field:

- `pdfScanMigration`

### Backup policy before deletion

Before deleting legacy subcollections, the migration script should optionally export a compact JSON backup for each migrated run to Cloud Storage.

Recommended backup prefix:

- `pdf-scan-runs/{userId}/{projectId}/{runId}/migration-backup/`

Backup contents:

- root run doc snapshot before migration
- old `pdfScanDocs` collection as JSONL
- old `pdfScanSections` collection as JSONL

This backup is not for the UI. It is a rollback safety net.

### Migration script

Create a server-side admin script:

- `fastapi/scripts/migrate_pdf_scan_runs_to_v2.py`

It must use the Firebase Admin SDK / server credentials, not the client SDK.

Required CLI behavior:

- `--user-id`
- `--project-id`
- `--run-id`
- `--limit`
- `--dry-run`
- `--write-v2`
- `--backup`
- `--delete-legacy`
- `--force`

Recommended execution modes:

1. Dry run

- scan candidate runs
- print what will be migrated
- print expected counts
- do not write

2. Write v2 only

- create v2 structure
- keep old flat data in place temporarily
- stamp `pdfScanMigration`

3. Delete legacy

- only after counts verify
- remove old flat subcollections
- optionally remove flat-only root fields

### Migration algorithm

For each eligible run:

1. Read root run doc.
2. Read old flat `pdfScanDocs`.
3. Read old flat `pdfScanSections`.
4. Resolve the single historical chapter ID from `kapitelIds[0]`.
5. Build one v2 chapter doc.
6. Copy flat doc summaries into `pdfScanChapters/{chapterId}/docs`.
7. Copy flat section docs into `pdfScanChapters/{chapterId}/sections`.
8. Build `pdfScanAggregateDocs` from the old flat doc summaries:
   - `usefulForChapters = [chapterId]` only when `hasUsefulInformation == true`
   - `usefulChapterCount = 1` or `0`
   - `bestChapterMatch.chapterId = chapterId`
   - `perChapter[chapterId]` from the old summary row
9. Build run-level `pdfScanSummary`, `pdfScanCounts`, and `pdfScanDisplay`.
10. Write `pdfScanSchemaVersion = 2`.
11. Verify written counts.
12. If `--delete-legacy` is enabled and verification passes:
    - delete `pdfScanDocs`
    - delete `pdfScanSections`
    - delete flat-only root fields
13. Stamp `pdfScanMigration`.

### Verification rules

The script must fail the run migration if any of these checks fail:

- source flat doc count does not equal target chapter doc count
- source flat section count does not equal target chapter section count
- aggregate doc count does not equal source flat doc count
- the target chapter doc does not exist
- `kapitelIds` is empty or has more than one chapter in a v1 run

### Cutover rule

Do not deploy a v2-only frontend until:

- migration has completed for all terminal old runs
- no v1 run remains in `queued` or `running`
- migration verification reports are clean

## Backend Implementation Plan

### Phase 1. Request model and API contract

Files:

- `fastapi/models/request.py`
- `fastapi/main.py`

Changes:

1. Replace the request contract for new clients:

```ts
type QuellenFinderPdfScanRequestV2 = {
  projekt_id: string;
  kapitel_ids: string[];
  pdf_ids: string[];
  confirm_duplicate_kapitel_run?: boolean;
};
```

2. Keep temporary request compatibility:

- accept `kapitel_id` for old clients
- normalize to `kapitel_ids = [kapitel_id]`

3. Validation rules:

- all chapter IDs must exist
- all chapters must belong to the same project
- all chapters must be unarchived
- deduplicate and preserve order
- reject empty `kapitel_ids`
- reject more than `PDF_SCAN_MAX_PDFS_PER_RUN`

4. Replace the duplicate-run check semantics:

- old meaning: “same chapter already running”
- new meaning: “any requested chapter overlaps an active PDF-scan run”

Return conflict payload:

```json
{
  "code": "overlapping_kapitel_scan_running",
  "message": "...",
  "run_id": "existingRunId",
  "overlapping_kapitel_ids": ["kapA", "kapB"]
}
```

### Phase 2. Run doc creation

Files:

- `fastapi/main.py`
- `fastapi/services/quellen_finder_firestore_service.py`

Changes:

1. Build full ordered `kapitelSnapshots` for every requested chapter.

2. Store the ordered list in the run doc:

- `kapitelIds`
- `kapitelSnapshots`
- `pdfScanSchemaVersion = 2`
- `pdfScanMode = "chapter_matrix"`
- `chapterInputMode = "single"` or `"multi"`

3. Remove `chapterInputSnapshot` as the single source of truth for PDF-scan v2.

Replacement:

- store `chapterInputSnapshots` as an ordered array or map keyed by chapter ID

Recommended root payload:

```ts
chapterInputSnapshots: Array<{
  chapterId: string;
  chapterTitle: string;
  chapterSpecText: string;
  chapterOrder: number;
}>;
```

Keep `chapterInputSnapshot` only as a temporary compatibility field during rollout if needed by old helper code. Delete it once all CPU/GPU helpers are switched.

### Phase 3. CPU job changes

Files:

- `fastapi/services/pdf_scan/common.py`
- `fastapi/services/pdf_scan/cpu_job.py`

Changes:

1. Replace `build_runtime_settings_from_run_doc()` with a v2-aware builder:

- build an ordered chapter list from `chapterInputSnapshots`
- return run-wide settings, not a single chapter

2. CPU job staging:

- create one `chapters/` input folder in temp workdir
- write one markdown file per chapter in the order of `kapitelIds`
- pass that folder to the multi-chapter local pipeline entrypoint

3. CPU run command should now match the local multi-chapter flow:

- use the CPU pipeline entrypoint that already supports chapter folders
- shared `A/B/C`
- chapter-parallel `D/E`

4. CPU job must initialize `pdfScanChapters/{chapterId}` docs early:

- `status = queued`
- chapter snapshot
- chapter order

Then update them to `running` when chapter-local work begins.

### Phase 4. Progress protocol

Files:

- `pdf-scan/run_pipeline_cpu.py`
- `pdf-scan/run_pipeline_gpu.py`
- `fastapi/services/pdf_scan/common.py`
- `fastapi/services/pdf_scan/cpu_job.py`
- `fastapi/services/pdf_scan/gpu_job.py`

The current root-level `RunProgressTracker` is not enough for good multi-chapter UI.

Required change:

- standardize a structured pipeline event format emitted from `pdf-scan/`

Recommended event shape:

```json
{
  "scope": "shared" | "chapter" | "aggregate",
  "chapter_id": "chapter_02",
  "stage": "phase_e",
  "status": "running" | "completed" | "error",
  "current": 4,
  "total": 13,
  "message": "Retrieving candidate sections"
}
```

FastAPI job logic should:

- keep updating run-level `progress` and `pipelineStages`
- also update chapter-level `pdfScanChapters/{chapterId}` progress and stages

Fallback rule:

- if a script only emits root-level events, the backend may still infer chapter completion from produced artifact files
- but the desired end state is explicit chapter-aware events

### Phase 5. GPU job changes

Files:

- `fastapi/services/pdf_scan/gpu_job.py`
- `fastapi/services/pdf_scan/common.py`

Changes:

1. GPU job restores the run dir and executes chapter-local `F/G` plus aggregate `H`.

2. Replace the current flat persistence builder:

- old:
  - `build_persisted_view_docs(...)`
- new:
  - `build_persisted_pdf_scan_v2_view(...)`

New builder output should include:

- run summary update
- chapter docs
- chapter doc summaries
- chapter sections
- aggregate docs
- aggregate sections

3. GPU job persists v2 projections only.

4. GPU job updates:

- run-level `pdfScanSummary`
- run-level `pdfScanCounts`
- run-level `pdfScanArtifacts`
- chapter docs status and summaries

### Phase 6. Firestore persistence service

Files:

- `fastapi/services/quellen_finder_firestore_service.py`

Add dedicated v2 helpers instead of overloading the legacy flat writer.

Required new methods:

- `clear_pdf_scan_v2_results(...)`
- `write_pdf_scan_v2_chapter_docs(...)`
- `write_pdf_scan_v2_chapter_doc_summaries(...)`
- `write_pdf_scan_v2_chapter_sections(...)`
- `write_pdf_scan_v2_aggregate_docs(...)`
- `write_pdf_scan_v2_aggregate_sections(...)`
- `replace_pdf_scan_v2_results(...)`

Behavior:

- delete old v2 nested collections before rewriting
- use chunked batched writes
- keep write chunk size at `<= 400`

Why:

- consistent with current service behavior
- leaves headroom
- easier failure cleanup

Critical cleanup rule:

- deleting `pdfScanChapters/{chapterId}` alone is not enough
- nested `docs` and `sections` subcollections must be explicitly cleared first

### Phase 7. Cost and billing fields

Keep the existing run-level billing model.

Add only compact v2 summary fields:

- `billing.openaiCostUsd`
- `billing.computeCostUsd`
- `billing.totalCostUsd`
- `billing.secondsCpu`
- `billing.secondsGpu`
- `billing.secondsTotal`

Do not duplicate billing onto chapter docs unless you later decide you need chapter-level cost breakdowns.

## Frontend Implementation Plan

### State model redesign

Files:

- `app/components/pdf-scan/PdfScanWorkspace.tsx`

Current problem:

- `selectedKapitelId` is used both for:
  - choosing input for the next run
  - choosing what chapter result to view

That must be split.

New state model:

- `selectedInputKapitelIds: string[]`
- `activeRunId: string | null`
- `activeResultChapterId: string | null`
- `resultViewMode: "overview" | "chapter" | "overlap"`

Rules:

- input chapter selection is independent from result browsing
- selecting a run does not overwrite the next-run input selection
- selecting a chapter result tab does not change the next-run input selection

### Frontend data types

Files:

- `app/lib/firestore/types.ts`

Add v2 types:

- `PdfScanRunDocV2`
- `PdfScanChapterDoc`
- `PdfScanChapterDocSummaryDoc`
- `PdfScanChapterSectionDoc`
- `PdfScanAggregateDoc`
- `PdfScanAggregateSection`

Add a discriminant:

```ts
type PdfScanSchemaVersion = 2;
```

Run helper:

```ts
function isPdfScanRunV2(run: QuellenFinderRunDoc): boolean {
  return Number(run.pdfScanSchemaVersion || 0) >= 2;
}
```

### Firestore refs

Files:

- `app/lib/firestore/refs.ts`

Add v2 refs:

- `quellenFinderPdfScanChaptersCol`
- `quellenFinderPdfScanChapterDoc`
- `quellenFinderPdfScanChapterDocsCol`
- `quellenFinderPdfScanChapterSectionsCol`
- `quellenFinderPdfScanAggregateDocsCol`
- `quellenFinderPdfScanAggregateSectionsCol`

### Component structure cleanup

`PdfScanWorkspace.tsx` is already too large. Do not keep growing it.

Refactor into:

- `PdfScanWorkspace.tsx`
  - orchestrates state and top-level layout
- `PdfScanStartPanel.tsx`
  - input chapter selection
  - PDF selection
  - start button and duplicate dialog
- `PdfScanRunSidebar.tsx`
  - run list and run status summaries
- `PdfScanRunHeader.tsx`
  - selected run meta, billing, stage summary
- `PdfScanOverviewView.tsx`
  - aggregate document matrix
- `PdfScanChapterView.tsx`
  - per-chapter doc cards and sections
- `PdfScanOverlapView.tsx`
  - cross-chapter useful sections

Add hooks:

- `usePdfScanRuns(...)`
- `usePdfScanV2RunData(...)`
- `usePdfScanChapterResults(...)`

This is important for maintainability. The migration should improve structure, not only add features.

### UI behavior for new runs

#### Start panel

Replace the single chapter `Select` with a multi-select UI.

Recommended behavior:

- show all project chapters in project order
- allow checkbox multi-select
- show selected chapter chips
- show count summary:
  - `3 Kapitel ausgewählt`
- preserve order by project order, not selection click order

Single-chapter behavior:

- if exactly one chapter is selected, the experience should still feel like today

#### Run list

For v2 runs:

- show a multi-chapter label:
  - `3 Kapitel`
- show first one or two chapter titles, then `+N`
- show `hadPartialFailures` visibly

#### Run detail

For v2 runs, add tabs:

- `Übersicht`
- `Kapitel`
- `Überschneidungen`

`Übersicht`:

- render `pdfScanAggregateDocs`
- show chapter usefulness matrix or badges
- show best matching chapter per PDF

`Kapitel`:

- chapter selector inside the selected run
- render `pdfScanChapters/{chapterId}/docs`
- when one doc is expanded, load `sections` for that chapter

`Überschneidungen`:

- render `pdfScanAggregateSections`
- highlight sections useful for more than one chapter

### Live listeners and performance

Do not open listeners for every chapter subcollection at once.

Recommended strategy:

- always listen to the run doc
- if run is v2:
  - listen to `pdfScanChapters`
  - listen to `pdfScanAggregateDocs` when overview tab is active
  - listen to `pdfScanAggregateSections` only when overlap tab is active
  - listen to `pdfScanChapters/{chapterId}/docs` only for the active result chapter
  - listen to `pdfScanChapters/{chapterId}/sections` only when needed for expanded docs

This keeps the client efficient and avoids unnecessary listener fan-out.

### Preview / SSR support

If `PdfScanWorkspacePreview` is still used, add a v2 preview shape:

- run summaries
- optional aggregate docs
- optional selected chapter docs

Do not try to preload every chapter’s sections server-side.

## Firestore Rules Plan

If the new subcollections remain under:

- `users/{uid}/projects/{projectId}/researchRuns/{runId}/...`

then the existing rule:

- `match /researchRuns/{runId}/{doc=**} { allow read: if canReadResearchRun(...) }`

already covers client reads.

Therefore:

- no functional read-rule redesign is required
- no client write rules are required because PDF-scan run artifacts remain server-written

Still review the rules file after implementation to confirm no new top-level collection paths were introduced by accident.

## Indexing Plan

### First implementation

Avoid requiring new composite indexes by:

- reading explicit known subcollections
- not using collection group queries
- not querying aggregate docs by complex compound filters

### Index exemptions

After v2 fields are live, add index exemptions for large non-query fields, especially:

- long evidence preview text
- long error/debug fields
- any stored summary blobs that are not filtered or ordered on

If the project currently does not check in index configuration, add:

- `firestore.indexes.json`

and manage index exemptions there going forward.

## Rollout Plan

### Phase A. Backend v2 writer + migration tooling

Implement backend v2 support first:

- request model accepts `kapitel_ids`
- CPU/GPU jobs can execute multi-chapter runs
- Firestore persistence writes v2 schema
- migration script exists and is safe to run in dry-run mode

Do not cut the frontend yet.

### Phase B. Migration dry run

Run the migration script in dry-run mode:

- collect candidate runs
- verify count mappings
- verify that all old runs are single-chapter
- verify that no active v1 runs remain unaccounted for

### Phase C. Write migrated v2 data

Execute migration with:

- backup enabled
- v2 write enabled
- legacy deletion disabled on the first pass

Then verify:

- root `pdfScanSchemaVersion`
- `pdfScanChapters`
- `pdfScanAggregateDocs`
- `pdfScanSummary`
- `pdfScanCounts`

### Phase D. Delete legacy Firestore data

Run the cleanup mode of the migration script:

- delete old `pdfScanDocs`
- delete old `pdfScanSections`
- delete flat-only root fields where no longer needed

Only do this after verification passes.

### Phase E. Frontend cutover

Switch the main app UI to v2 only:

- no flat reader
- no legacy result components
- multi-chapter start flow active
- v2 overview and chapter views active

### Phase F. Final cleanup

After cutover is stable:

- remove old backend flat write path
- remove old frontend flat read path
- remove temporary migration compatibility branches

## Detailed Cleanup Plan

### Remove after migration and cutover

Backend:

- temporary request normalization branches for `kapitel_id`
- `build_persisted_view_docs(...)` once nothing calls it
- `replace_pdf_scan_results(...)`
- single-chapter helper logic in `build_runtime_settings_from_run_doc(...)`
- migration-only verification helpers once the migration window is closed

Frontend:

- state logic that auto-binds `selectedKapitelId` to `activeRun`
- run labeling that assumes `kapitelSnapshots?.[0]`
- flat result loading as the default path
- legacy-only run rendering components and hooks
- legacy Firestore refs for flat result collections
- legacy Firestore TS types for flat PDF-scan docs and sections

### Code organization target

By the end of cleanup:

- new code should live in explicit v2 modules or generic modules
- there should be no active v1 PDF-scan read/write path in the main app
- migration code should live in explicit `scripts/` or `admin/` locations, not in the main runtime path

Do not leave mixed migration/runtime branches scattered through unrelated files.

## Implementation File Checklist

### Backend

- `fastapi/models/request.py`
- `fastapi/main.py`
- `fastapi/services/pdf_scan/common.py`
- `fastapi/services/pdf_scan/cpu_job.py`
- `fastapi/services/pdf_scan/gpu_job.py`
- `fastapi/services/quellen_finder_firestore_service.py`
- `fastapi/scripts/migrate_pdf_scan_runs_to_v2.py`

Potential new backend helper files:

- `fastapi/services/pdf_scan/persistence_v2.py`
- `fastapi/services/pdf_scan/progress_v2.py`

### Frontend

- `app/components/pdf-scan/PdfScanWorkspace.tsx`
- `app/lib/firestore/refs.ts`
- `app/lib/firestore/types.ts`

Recommended new frontend files:

- `app/components/pdf-scan/PdfScanStartPanel.tsx`
- `app/components/pdf-scan/PdfScanRunSidebar.tsx`
- `app/components/pdf-scan/PdfScanRunHeader.tsx`
- `app/components/pdf-scan/PdfScanOverviewView.tsx`
- `app/components/pdf-scan/PdfScanChapterView.tsx`
- `app/components/pdf-scan/PdfScanOverlapView.tsx`
- `app/components/pdf-scan/hooks/usePdfScanRuns.ts`
- `app/components/pdf-scan/hooks/usePdfScanV2RunData.ts`

### Local pipeline touchpoints

Only if needed to expose chapter-aware progress:

- `pdf-scan/run_pipeline_cpu.py`
- `pdf-scan/run_pipeline_gpu.py`

## Acceptance Criteria

The integration is done only when all of the following are true:

1. A new single-chapter PDF-scan run works end to end in the main app using the v2 schema.
2. A new multi-chapter PDF-scan run works end to end in the main app using the v2 schema.
3. All historical terminal PDF-scan runs have been migrated to the v2 schema.
4. The UI can:
   - start a run with multiple chapters
   - show aggregate run results
   - show per-chapter results
   - show overlapping sections across chapters
5. Cancelling a run still works.
6. A run with one failed chapter renders as successful with partial failures visible.
7. The migration script can:
   - dry-run
   - back up
   - write v2
   - verify counts
   - delete legacy flat data safely
8. No frontend runtime code reads flat `pdfScanDocs` / `pdfScanSections`.
9. No backend runtime code writes flat `pdfScanDocs` / `pdfScanSections`.
10. Firestore writes are chunked and cleanly replace nested v2 subcollections.
11. No active `pdf_scan` run remains on schema v1 after cutover.

## Recommended Implementation Order

1. Add v2 Firestore types and refs.
2. Add backend request normalization for `kapitel_ids`.
3. Implement v2 run doc creation.
4. Implement CPU runtime settings builder for multi-chapter runs.
5. Implement GPU persistence builder for v2 projections.
6. Implement Firestore v2 write helpers.
7. Implement `migrate_pdf_scan_runs_to_v2.py`.
8. Add chapter-aware progress updates.
9. Dry-run migration and verify candidate runs.
10. Execute migration with backups and verification.
11. Delete legacy flat run data.
12. Refactor frontend state model.
13. Build v2-only overview and chapter views.
14. Switch start flow to multi-select.
15. Run full migration, cutover, and live-progress tests.
16. Remove dead v1 code.

## Final Recommendation

Do not treat this as a small extension to the current single-chapter screen.

The correct implementation is:

- keep the run root stable
- add a clean v2 chapter-aware subtree under it
- migrate old flat runs once instead of carrying permanent dual-read logic
- decouple input selection state from result browsing state
- delete flat-only runtime code after migration verifies cleanly

That gives you a system that is:

- internally consistent
- structurally aligned with the real local pipeline
- safe for future cleanup because there is only one active runtime format
- much easier to maintain than the current flat single-chapter assumptions
