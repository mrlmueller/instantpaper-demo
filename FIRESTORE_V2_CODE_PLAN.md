# Firestore V2 — Code Refactor Game Plan (Next.js + FastAPI)

This file is the companion to `FIRESTORE_V2_DATABASE_PLAN.md`. It describes what to change in the codebase so the app uses the V2 schema efficiently (less over-fetching, fewer listeners, and cleaner invariants) while keeping a mostly realtime UX.

## 0) High-level outcomes we want

1. **No more “singleton doc stored as collection” reads**
   - Replace `getDocs(collection).docs[0]` with explicit `doc()` reads/listens.

2. **Project load stops fetching big texts**
   - Quellen list loads metadata only; content loads on open.

3. **Fewer realtime listeners**
   - Replace the “N Kapitels × (runs + combined)” listener pattern with **one** Kapitel-list listener using denormalized `latestRun` fields.

4. **One canonical schema in code**
   - camelCase only, Timestamp only, `costUsd` only.
   - Remove snake_case fallbacks across transforms.

5. **Rules + code align**
   - Client CRUD stays direct for “normal” docs.
   - Backend-only writes remain backend-only (versions, secrets, summaries, intermediate groups).

## 1) Changes in Next.js (app/)

### 1.1 Introduce a Firestore “refs + types” layer (single source of truth)

Create a dedicated module for:
- Path builders (no more inline string paths everywhere).
- Document converters (typed Firestore docs).
- Shared types for Firestore docs (not UI types).

Suggested location:
- `app/lib/firestore/refs.ts` (path builders)
- `app/lib/firestore/types.ts` (Firestore doc types)
- `app/lib/firestore/converters.ts` (withConverter helpers)

This immediately reduces:
- typo risk in paths
- duplicate logic for refs (client/server)
- schema drift

### 1.1.1 Explicit module touch list (Next.js)

Expect to update at least these areas:
- `app/actions/projects.ts` (archive instead of delete; filter archived)
- `app/actions/quellen.ts` (split meta vs content; new content actions; archive fields)
- `app/actions/kapitels.ts` (runs/artifacts paths; reduce N+1 fetching; archived filters)
- `app/actions/promptTemplates.ts` (mostly unchanged; ensure V2 field names)
- `app/components/dashboard/Dashboard.tsx` (listeners + loading strategy)
- `app/components/dashboard/KapitelWorkspace.tsx` (intermediate groups source)
- `app/components/dashboard/*RefinementDialog.tsx` (artifact refs + version refs)
- `app/lib/transformers/*` (remove snake_case fallbacks; new artifact model)
- `app/types/*` (Firestore doc types vs UI types alignment)

### 1.2 Update dashboard data loading to avoid over-fetching

Current pain:
- `getUserQuellen()` returns full Quelle docs including `content` for every Quelle on project switch.

V2 change:
- `getUserQuellen()` becomes “metadata only”.
- Add explicit actions for content:
  - `getQuelleContent(quelleId)` -> reads `quellen/{id}/content/main`
  - `setQuelleContent(quelleId, text)` -> writes `quellen/{id}/content/main` with `{ text, wordCount, createdAt?, updatedAt }` (+ updates `wordCount` + `updatedAt` on metadata doc)

UI behavior:
- Quellen list view: show title/metadata without loading content.
- Quelle editor/dialog open: fetch content once (or attach a short-lived realtime listener while the editor is open).

Validation:
- Enforce **7000 words max** before writing content.
- Mirror Firestore rules’ character cap to provide friendly client-side errors.

Files impacted:
- `app/actions/quellen.ts`
- components that open/edit Quelle content (dashboard panels/dialogs)

### 1.2.1 Kapitel ordering + hierarchy (fix current “order” pitfalls)

V2 relies on:
- `parentId` always present (null for root)
- queries like `where(parentId == X) orderBy(order)` become possible if you ever need them

Even if you keep “single query then build tree in memory”, standardizing `parentId` avoids the current bug class where ordering was computed incorrectly because the query wasn’t filterable.

### 1.3 Replace per-Kapitel “status listeners” with a single Kapitels listener

Current code:
- `app/components/dashboard/Dashboard.tsx` attaches:
  - 1 listener per Kapitel on `runs` (latest run)
  - plus a listener on `combined` to infer “fertig”

V2 change:
- Store/update small status on Kapitel doc (`latestRun` object).
- Add one listener:
  - `onSnapshot(query(kapitelsRef, where(projektId==X), where(archived==false), orderBy(order)))`
- UI derives status from `kapitel.latestRun.status`.

Who updates `latestRun`?
- When a run is created: client can set `latestRun = { runId, index, status: "running", updatedAt }` optimistically.
- When backend writes results/artifacts: backend updates `latestRun.status` and `updatedAt` (or updates run-level status fields that the UI uses).

Files impacted:
- `app/components/dashboard/Dashboard.tsx`
- `app/actions/kapitels.ts` (run creation should optionally update `latestRun`)
- `fastapi/services/firebase_service.py` (backend updates)

### 1.4 Selected run: reduce listeners from 4 -> 2 (+ optional 3rd on demand)

Current selected-run listeners:
- combined collection
- shortened collection
- lesefluss collection
- results collection

V2 selected-run listeners:
1. `onSnapshot(runs/{runId}/artifacts)` (collection of 3 docs: combined/shortened/lesefluss)
2. `onSnapshot(runs/{runId}/results)` (same as today)

Intermediate groups (only relevant sometimes):
- `onSnapshot(runs/{runId}/artifacts/combined/groups)` should be lazy:
  - Only attach when the “Zwischengruppen” UI section is expanded.
  - Fetch-on-open is allowed (no polling/refresh UX).

Files impacted:
- `app/components/dashboard/Dashboard.tsx`
- `app/components/dashboard/KapitelWorkspace.tsx` (intermediate groups source)
- `app/lib/transformers/ui-data.ts` (transformers updated to new structure)

### 1.5 Refinement dialogs: switch base doc from old paths to artifacts

Current:
- `.../runs/{runId}/combined/combined`
- `.../runs/{runId}/shortened/shortened`
- `.../runs/{runId}/lesefluss/lesefluss`

V2:
- `.../runs/{runId}/artifacts/combined`
- `.../runs/{runId}/artifacts/shortened`
- `.../runs/{runId}/artifacts/lesefluss`

Versions:
- move under `artifacts/{artifactId}/versions/*`

Client “use version” write:
- Update the artifact doc:
  - `content`
  - `refinement.activeVersionId`
  - `refinement.selectedAt`
  - plus derived fields (lengths/explanation) for shortened/lesefluss

Files impacted:
- `app/components/dashboard/CombinedRefinementDialog.tsx`
- `app/components/dashboard/ShortenedRefinementDialog.tsx`
- `app/components/dashboard/LeseflussRefinementDialog.tsx`
- `app/components/dashboard/ResultRefinementDialog.tsx` (results path stays; schema changes)

### 1.6 Remove snake_case fallbacks everywhere (after migration)

Once migration is complete, delete “dual read” logic like:
- `foo_bar ?? fooBar`
- `created_at ?? createdAt`

Where it exists today:
- `app/actions/kapitels.ts` (heavy)
- `app/components/dashboard/Dashboard.tsx`
- `app/lib/transformers/*`

### 1.7 Archiving behavior in UI and actions

Projects:
- Replace `deleteProject(projectId)` with `archiveProject(projectId)`:
  - set `archived=true`, `archivedAt=serverTimestamp()`, `updatedAt=serverTimestamp()`
- `getProjects()` filters `archived==false` by default.
- Optional UI: “Archived projects” section (restore action).

Quellen/Kapitels/Runs (required for V2):
- Replace destructive deletes with archive updates:
  - Quellen: `archiveQuelle(quelleId)` (metadata doc; content can remain stored)
  - Kapitels: `archiveKapitel(kapitelId)`
  - Runs: `archiveRun(kapitelId, runId)` (hide archived runs by default)
- Filter list queries by `archived == false`.
- Keep hard-deletes as an Admin-only cleanup (script) if needed.

### 1.8 Server actions vs client writes (keep “fast”, but remove duplication)

Current pattern: “client write first, then server action fallback” duplicated across handlers.

To keep speed while making this senior-review friendly:
- Keep the “client-first” approach for UX/optimism.
- Centralize fallback in one helper (not copy-pasted per handler), e.g. `firestoreWriteWithFallback({ clientWrite, serverWrite })`.
- Make server actions thin and reuse the same ref/type helpers so both paths enforce the same schema.

## 2) Changes in FastAPI (fastapi/)

All Firestore operations stay centralized in `fastapi/services/firebase_service.py`.
The primary refactor is: write/read the new paths and the new field names/types.

### 2.1 Update Quelle reads to new “content blob”

Current:
- `get_quelle()` reads `users/{uid}/quellen/{quelleId}` and expects `.content`.

V2:
- `get_quelle_meta()` reads metadata doc
- `get_quelle_content()` reads `quellen/{id}/content/main.text`
- `process_single_quelle` uses content from the content doc.

Files impacted:
- `fastapi/services/firebase_service.py`
- `fastapi/services/quelle_service.py`
- any refinement code that reads Quelle content

### 2.1.1 Explicit module touch list (FastAPI)

Expect to update at least:
- `fastapi/services/firebase_service.py` (all refs + all schemas)
- `fastapi/services/quelle_service.py` (process Quelle; combine; hierarchical groups)
- `fastapi/services/shorten_service.py` (reads artifacts; writes artifacts; summaries)
- `fastapi/services/refinement_service.py` (uses artifact versions paths)
- `fastapi/services/prompt_service.py` (reads prompt settings/templates; mostly unchanged)
- `fastapi/services/user_key_service.py` (secrets unchanged)
- request/response models if they assume old field names

### 2.2 Results + run progress counters (denormalization for UI)

When FastAPI writes a result doc:
- Write `runs/{runId}/results/{quelleId}` in V2 schema (camelCase, timestamps, usage object, `costUsd` float).
- Atomically update the run doc:
  - increment `resultsCompletedCount`
  - increment `resultsWithContentCount` if `hasContent`
  - update `lastResultAt`, `lastActivityAt`
  - update `kapitels/{kapitelId}.latestRun` (recommended)

This powers the dashboard’s single Kapitel-list listener.

Files impacted:
- `fastapi/services/firebase_service.py` (`save_result`)
- `fastapi/services/quelle_service.py` (orchestration)

### 2.3 Combined/Shortened/Lesefluss become artifacts

Replace:
- `combined/combined`
- `shortened/shortened`
- `lesefluss/lesefluss`

With:
- `artifacts/combined`
- `artifacts/shortened`
- `artifacts/lesefluss`

Also:
- intermediate groups move to `artifacts/combined/groups/*`

Backend writes should also update run status fields:
- `artifactsStatus.combined = "success" | "error"`
- same for shortened/lesefluss
- `lastActivityAt`
- (optional) `kapitel.latestRun.status = "done"` when combined is ready (or when all expected artifacts are ready)

Files impacted:
- `fastapi/services/firebase_service.py` (paths + schemas)
- `fastapi/services/quelle_service.py`
- `fastapi/services/shorten_service.py`

### 2.4 Refinement service updates (versions under artifacts)

Current refinement versions live under:
- `combined/combined/versions/*`
- `shortened/shortened/versions/*`
- `lesefluss/lesefluss/versions/*`
- `results/{quelleId}/versions/*`

V2:
- `artifacts/{artifactId}/versions/*`
- results path stays but schema changes

Key behavior:
- `ensure_*_refinement_root_version` uses artifact doc `content` (or result doc `content`) as the root version’s `assistantText`.
- cost totals update:
  - `artifact.refinement.costTotalUsd` (and equivalent for results)

Files impacted:
- `fastapi/services/firebase_service.py` (refinement helpers)
- `fastapi/services/refinement_service.py` (queue/process logic)

### 2.5 Shorten + Lesefluss read paths

Shorten/lesefluss currently reads:
- combined doc
- shortened doc
- lesefluss doc
- summaries per run

V2:
- read artifacts instead
- summaries stay under runs but normalized (timestamps + `costUsd` float)

Files impacted:
- `fastapi/services/shorten_service.py`

## 3) Firestore rules update (implementation notes)

Rules are specified in `FIRESTORE_V2_DATABASE_PLAN.md` (strategy + constraints).

Code must align to rules by ensuring:
- client does not create server-owned docs (results/artifacts/summaries/groups/versions)
- client updates only the allowed fields for “select refinement version”
- large text writes respect limits (client-side validation mirrors rules)

## 4) Migration execution order (practical)

Because we’re not keeping backwards compatibility:
1. Stop traffic / maintenance window.
2. Run the migration script (creates V2 paths + normalizes fields; deletes old).
3. Deploy:
   - new FastAPI
   - new Next.js
   - new Firestore rules
4. Smoke test end-to-end flows (see checklist below).

## 5) Smoke-test checklist (must pass)

### Core CRUD
- Create project -> appears; archive project -> disappears; restore (if implemented) -> appears.
- Create Quelle (metadata + content) -> list shows title; opening Quelle loads content; editing content persists.
- Create Kapitel; assign Quellen; reorder hierarchy; archive Kapitel.
- Archive run -> hidden in run history (by default).

### Processing pipeline
- Create run -> progress counters update while results come in.
- After all results:
  - combine run produces `artifacts/combined`
  - intermediate groups show (when hierarchical combine triggers)
- Shorten produces `artifacts/shortened`
- Lesefluss produces `artifacts/lesefluss`

### Refinement
- Open refinement dialog -> versions stream in.
- Select a version -> base artifact/result updates; downstream operations use the selected content.
