# Main App Multi-Chapter PDF-Scan Integration Plan

## Goal

Integrate the new multi-chapter PDF-scan pipeline from `pdf-scan/` into the main app so that:

- new PDF-scan runs can target one or many chapters in one run
- the main app uses the split production execution path that already exists:
  - CPU job for shared work and chapter-local `D/E`
  - GPU job for chapter-local `F/G` and aggregate `H`
- old historical PDF-scan runs remain readable in the UI without data migration
- new runs are stored in a clean, chapter-aware Firebase structure
- the frontend exposes all required functionality:
  - multi-chapter input selection
  - run overview across chapters
  - per-chapter result browsing
  - aggregate cross-chapter views
- stale single-chapter-only code is removed once the new path is live and stable

This document is written as the implementation source of truth for the migration.

## Scope

In scope:

- Firestore schema v2 for PDF-scan runs
- Cloud Storage artifact layout for v2 runs
- FastAPI request/validation/execution/persistence changes
- frontend state model, component structure, and dual-read logic
- backwards compatibility for old runs
- rollout, testing, and cleanup

Out of scope:

- changing the underlying `pdf-scan/` local pipeline logic beyond what is required to expose chapter-aware progress/events into FastAPI
- migrating old Firestore data into the new schema

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

### 1. Use a schema version instead of trying to mutate old runs

Decision:

- keep old runs exactly as they are
- add `pdfScanSchemaVersion`
- old runs implicitly remain `v1`
- all new runs are `v2`

Why:

- historical runs already render from flat collections
- rewriting them is risky and unnecessary
- the UI can dual-read by schema version with low complexity

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

## Backwards Compatibility Strategy

### Legacy runs

Legacy runs are any PDF-scan run where:

- `pdfScanSchemaVersion` is missing
- or `pdfScanSchemaVersion < 2`

Legacy data shape remains:

- `pdfScanDocs`
- `pdfScanSections`

Frontend behavior for legacy runs:

- continue reading the flat collections
- continue rendering with the current single-chapter result view
- treat `kapitelSnapshots?.[0]` as the active chapter label

### New runs

New runs always have:

- `pdfScanSchemaVersion = 2`

New run behavior:

- frontend reads chapter-aware collections
- if the run has exactly one chapter, UI still looks almost the same as today
- if the run has multiple chapters, UI exposes overview plus chapter-specific browsing

### Important rule

Do not dual-write new runs into both old and new result subcollections.

Reason:

- it doubles write cost
- it preserves stale assumptions
- it keeps dead code alive longer

The correct compatibility model is:

- old runs = old reader
- new runs = new writer + new reader

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

Keep legacy types:

- `PdfScanDocSummaryDoc`
- `PdfScanResultDoc`

Add a discriminant:

```ts
type PdfScanSchemaVersion = 1 | 2;
```

Run helper:

```ts
function getPdfScanSchemaVersion(run: QuellenFinderRunDoc): 1 | 2 {
  return Number(run.pdfScanSchemaVersion || 1) >= 2 ? 2 : 1;
}
```

### Firestore refs

Files:

- `app/lib/firestore/refs.ts`

Keep legacy refs:

- `quellenFinderPdfScanDocsCol`
- `quellenFinderPdfScanSectionsCol`

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
- `PdfScanLegacyRunView.tsx`
  - old flat result rendering
- `PdfScanOverviewView.tsx`
  - aggregate document matrix
- `PdfScanChapterView.tsx`
  - per-chapter doc cards and sections
- `PdfScanOverlapView.tsx`
  - cross-chapter useful sections

Add hooks:

- `usePdfScanRuns(...)`
- `usePdfScanLegacyResults(...)`
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

For v1 runs:

- keep the current single-chapter label based on `kapitelSnapshots?.[0]`

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

For v1 runs:

- keep the current document/section explorer

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

### Phase A. Backend first, dual-read-ready

Implement backend v2 support first:

- request model accepts `kapitel_ids`
- CPU/GPU jobs can execute multi-chapter runs
- Firestore persistence writes v2 schema

At this point the frontend may still be legacy, but no production UI should point at the new start contract yet.

### Phase B. Frontend dual-read

Implement the new frontend readers:

- legacy flat result reader for v1
- new chapter-aware reader for v2

Do not remove legacy display yet.

### Phase C. Frontend start flow

Switch the start UI to send:

- `kapitel_ids`

Keep backend fallback support for `kapitel_id` for one stabilization window.

### Phase D. Stabilization

Smoke-test all of these:

- new single-chapter run
- new multi-chapter run
- old historical run rendering
- run cancellation
- partial success with one failed chapter
- live progress while run is active

### Phase E. Cleanup

After the new path is verified:

- remove old backend write path for flat PDF-scan results
- remove single-chapter-only request handling if no longer needed
- keep legacy read adapter for historical runs

## Detailed Cleanup Plan

### Remove after v2 is stable

Backend:

- legacy single-chapter PDF-scan request documentation and validation branches
- `build_persisted_view_docs(...)` once nothing calls it
- `replace_pdf_scan_results(...)` once no active code writes flat results
- single-chapter helper logic in `build_runtime_settings_from_run_doc(...)`

Frontend:

- state logic that auto-binds `selectedKapitelId` to `activeRun`
- run labeling that assumes `kapitelSnapshots?.[0]`
- flat result loading as the default path

### Keep for backwards compatibility

Do not delete these until you intentionally stop supporting historical run display:

- legacy Firestore refs for:
  - `pdfScanDocs`
  - `pdfScanSections`
- legacy Firestore TS types
- legacy run rendering component

The correct approach is to isolate these in a clear `legacy` adapter, not to pretend they are dead code.

### Code organization target

By the end of cleanup:

- new code should live in explicit v2 modules or generic modules
- legacy code should be isolated behind:
  - `legacy`
  - `v1`
  - or `adapter`

Do not leave mixed v1/v2 branches scattered through unrelated files.

## Implementation File Checklist

### Backend

- `fastapi/models/request.py`
- `fastapi/main.py`
- `fastapi/services/pdf_scan/common.py`
- `fastapi/services/pdf_scan/cpu_job.py`
- `fastapi/services/pdf_scan/gpu_job.py`
- `fastapi/services/quellen_finder_firestore_service.py`

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
- `app/components/pdf-scan/PdfScanLegacyRunView.tsx`
- `app/components/pdf-scan/hooks/usePdfScanRuns.ts`
- `app/components/pdf-scan/hooks/usePdfScanV2RunData.ts`
- `app/components/pdf-scan/hooks/usePdfScanLegacyResults.ts`

### Local pipeline touchpoints

Only if needed to expose chapter-aware progress:

- `pdf-scan/run_pipeline_cpu.py`
- `pdf-scan/run_pipeline_gpu.py`

## Acceptance Criteria

The integration is done only when all of the following are true:

1. A new single-chapter PDF-scan run works end to end in the main app using the v2 schema.
2. A new multi-chapter PDF-scan run works end to end in the main app using the v2 schema.
3. The UI can still open and display an old flat PDF-scan run correctly.
4. The UI can:
   - start a run with multiple chapters
   - show aggregate run results
   - show per-chapter results
   - show overlapping sections across chapters
5. Cancelling a run still works.
6. A run with one failed chapter renders as successful with partial failures visible.
7. No new frontend code depends on `kapitelSnapshots?.[0]` for v2 runs.
8. No new backend code writes flat `pdfScanDocs` / `pdfScanSections` for v2 runs.
9. Firestore writes are chunked and cleanly replace nested v2 subcollections.
10. Historical runs do not require migration to render.

## Recommended Implementation Order

1. Add v2 Firestore types and refs.
2. Add backend request normalization for `kapitel_ids`.
3. Implement v2 run doc creation.
4. Implement CPU runtime settings builder for multi-chapter runs.
5. Implement GPU persistence builder for v2 projections.
6. Implement Firestore v2 write helpers.
7. Add chapter-aware progress updates.
8. Refactor frontend state model.
9. Build new overview and chapter views.
10. Add legacy adapter view.
11. Switch start flow to multi-select.
12. Run full compatibility and live-progress tests.
13. Remove dead v1 write code.

## Final Recommendation

Do not treat this as a small extension to the current single-chapter screen.

The correct implementation is:

- keep the run root stable
- add a clean v2 chapter-aware subtree under it
- dual-read old and new runs in the UI
- decouple input selection state from result browsing state
- isolate legacy code instead of mixing legacy assumptions into the new implementation

That gives you a system that is:

- backwards compatible
- structurally aligned with the real local pipeline
- safe for future cleanup
- much easier to maintain than the current flat single-chapter assumptions
