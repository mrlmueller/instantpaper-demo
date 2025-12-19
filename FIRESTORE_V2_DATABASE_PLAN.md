# Firestore V2 — Database Redesign Game Plan

This file proposes a new Firestore schema, rules strategy, and migration approach to fix current structural issues and unlock more efficient (mostly realtime) loading patterns in the app.

Scope: Firestore only (but schema choices reference how Next.js + FastAPI use Firestore).

## 0) Constraints (from you)

- Single-user data model forever (no collaboration / sharing).
- Prompt templates stay per-user.
- Add archiving for **projects, quellen, kapitels, runs** (hide archived in UI).
- Keep mostly realtime UX (fetch-on-open is OK; no polling/refresh UX).
- Prefer direct client writes for “normal” CRUD.
- Canonical conventions:
  - **camelCase** fields everywhere
  - **Firestore Timestamps** everywhere (`createdAt`, `updatedAt`, …)
  - Costs stored as **USD floats** (`costUsd`)
- No backwards compatibility needed; we can do a big-bang migration.
 - Max text size policy: **7000 words** (enforced in app code; rules enforce a safe character cap).

## 1) What’s good today (keep the spirit)

- **Per-user namespace** (`users/{uid}/...`) makes rules simple and avoids cross-user leaks.
- **Subcollections per domain** (projects/quellen/kapitels) match the product model.
- **Refinement versions are backend-only writes** (client reads, no client writes): good separation.
- **Selected-run lazy listeners** in the dashboard already exist (results/artifacts are loaded when needed).

## 2) What’s bad today (must change)

1. **Singleton-doc-as-collection pattern**
   - `combined/combined`, `shortened/shortened`, `lesefluss/lesefluss` are modeled as collections but used as “one doc”.
   - Code reads “first doc of collection” (`getDocs(...); docs[0]`), which is wasteful and ambiguous.

2. **Field naming + type drift**
   - snake_case vs camelCase fallbacks throughout the code.
   - timestamps are mixed (Firestore timestamp vs ISO strings).
   - costs are mixed (USD float vs cents int).

3. **Inefficient reads (especially on project load)**
   - Project load currently pulls all `quellen` docs including full `content` for 20–40 sources (and each can be large).
   - Some flows do N+1 subcollection fetches (`getKapitelRuns` fetches runs + multiple subcollections per run).

4. **Multiple write paths for same objects**
   - Some objects (especially Kapitels) are written by both client and server actions with different invariants.

5. **Rules lack strong shape/size constraints**
   - Even with correct per-user gating, missing field validation can become a “cost attack” vector (very large strings + platform key usage).

## 3) Design principles for V2

1. **Separate “lists” from “big blobs”**
   - If a list view doesn’t need a large text field, it should not be forced to read it.

2. **Stable, explicit doc IDs for “singletons”**
   - Use a single document (`docRef`) instead of a collection with one doc.

3. **One canonical schema**
   - camelCase, Timestamp, costUsd float, consistent token usage object.

4. **Client writes allowed, but guarded**
   - Rules should enforce allowed keys, value types, max sizes, and referential checks where possible.
   - Backend-only collections (secrets, refinement versions) remain non-writable by clients.

5. **Realtime at the right level**
   - Keep realtime where it provides UX value (active run, results, artifacts).
   - Avoid “N listeners per Kapitel” patterns by denormalizing small status fields.

## 4) Proposed V2 Firestore structure (path tree)

Everything remains under `users/{uid}` (fits single-user + rules).

```
users/{uid}
  projects/{projectId}
  promptTemplates/{templateId}
  promptSettings/active
  secrets/openai

  quellen/{quelleId}                    // metadata (small)
    content/main                        // big text blob

  kapitels/{kapitelId}
    runs/{runId}
      results/{quelleId}
        versions/{versionId}            // backend-only writes
      artifacts/{artifactId}            // artifactId: combined | shortened | lesefluss
        versions/{versionId}            // backend-only writes
        groups/{groupId}                // only under artifacts/combined (intermediate groups)
      summaries/{sourceKapitelId}
```

Key changes vs today:

- Introduce `runs/{runId}/artifacts/{artifactId}` to replace `combined/combined`, `shortened/shortened`, `lesefluss/lesefluss`.
- Split Quelle into:
  - metadata doc (`quellen/{quelleId}`) for lists
  - content doc (`quellen/{quelleId}/content/main`) for large text
- Move `intermediate_groups` under `artifacts/combined/groups`.

## 5) Document schemas (V2)

Notation:
- `ts` = Firestore Timestamp
- Writer:
  - **client** = Next.js client / server actions (rules enforced)
  - **server** = FastAPI Admin SDK (rules bypassed)

### 5.1 `users/{uid}` (profile)

Fields (client):
- `uid: string`
- `email?: string`
- `displayName?: string`
- `photoURL?: string`
- `createdAt: ts`
- `updatedAt: ts`
- `allowPlatformKey?: boolean` (server-managed only; client cannot set/update)

### 5.2 `users/{uid}/projects/{projectId}`

Fields (client):
- `name: string`
- `ownerId: string` (= uid)
- `createdAt: ts`
- `updatedAt: ts`
- `archived: boolean` (default false)
- `archivedAt?: ts`

Behavior:
- “Delete project” becomes **archive project** (UI hides archived).

### 5.3 `users/{uid}/quellen/{quelleId}` (metadata only)

Fields (client):
- `projektId: string`
- `title: string`
- `createdAt: ts`
- `updatedAt: ts`
- `archived: boolean` (default false)
- `archivedAt?: ts`
- `wordCount?: number` (optional convenience; keep updated when saving content)
- `images?: Array<{ url: string; path: string; filename: string; size: number; contentType: string }>`
- optional metadata: `autor?: string`, `jahr?: number`, `typ?: string`, `url?: string`, `zugriffAm?: string`, `color?: string`

### 5.4 `users/{uid}/quellen/{quelleId}/content/main` (big blob)

Fields (client):
- `text: string`
- `wordCount: number` (stored for UI + rule enforcement; computed by client)
- `createdAt: ts`
- `updatedAt: ts`

Notes:
- This is the main enabler for “load only when needed” for Quellen.

### 5.5 `users/{uid}/kapitels/{kapitelId}`

Fields (client):
- `projektId: string`
- `title: string`
- `nummer: string`
- `parentId: string | null` (always present; root = null)
- `order: number` (sortable within same parent)
- `quelleIds: string[]`
- `createdAt: ts`
- `updatedAt: ts`
- `archived: boolean` (default false)
- `archivedAt?: ts`

Denormalized status (server + optional client at run creation):
- `latestRun?: { runId: string; index: number; status: "none"|"running"|"done"; updatedAt: ts }`

### 5.6 `users/{uid}/kapitels/{kapitelId}/runs/{runId}`

Fields (client create; server updates progress):
- `projektId: string`
- `index: number`
- `instruction: string`
- `model: string`
- `createdAt: ts`
- `updatedAt: ts`
- `archived: boolean` (default false)
- `archivedAt?: ts`
- `promptTemplateId?: string | null`
- `promptPayload?: { heading?: string; topic?: string }` (keep small + explicit)
- `autoCombine: boolean`
- `grundlegendeInformationen?: string | null`
- `ueberschrift?: string | null`
- `thema?: string | null`

Progress summary (server-managed; critical for efficient UI):
- `resultsExpectedCount: number`
- `resultsCompletedCount: number`
- `resultsWithContentCount: number`
- `lastResultAt?: ts`
- `artifactsStatus: { combined: "empty"|"running"|"success"|"error"; shortened: ...; lesefluss: ... }`
- `lastActivityAt?: ts`

### 5.7 `.../runs/{runId}/results/{quelleId}`

Writer:
- Create/update by **server** for AI processing.
- Limited update by **client** for “select refinement version” (see rules section).

Fields:
- `quelleId: string`
- `userInput: string`
- `content: string`
- `hasContent: boolean`
- `model: string`
- `usage: { inputTokens: number; cachedInputTokens: number; outputTokens: number; reasoningTokens: number; totalTokens: number }`
- `costUsd: number`
- `keySource?: "user"|"platform"`
- `createdAt: ts`
- `updatedAt?: ts`
- `refinement: { rootVersionId: "root"; activeVersionId: string; maxDepth: number; costTotalUsd: number; initializedAt: ts; selectedAt?: ts }`

### 5.8 `.../runs/{runId}/artifacts/{artifactId}`

`artifactId` is one of: `combined` | `shortened` | `lesefluss`.

Writer:
- Create/update by **server** for initial generation.
- Limited update by **client** for “select refinement version” (content + refinement.activeVersionId, etc).

Common fields:
- `artifactId: "combined"|"shortened"|"lesefluss"` (redundant but convenient)
- `content: string`
- `model: string`
- `usage: { ... }`
- `costUsd: number`
- `keySource?: "user"|"platform"`
- `createdAt: ts`
- `updatedAt?: ts`
- `refinement: { rootVersionId: "root"; activeVersionId: string; maxDepth: number; costTotalUsd: number; initializedAt: ts; selectedAt?: ts }`

Combined-specific fields (`artifactId == "combined"`):
- `heading: string`
- `topic: string`
- `sourceQuelleIds: string[]`

Shortened-specific fields:
- `originalLength: number`
- `shortenedLength: number`
- `compressionRatio: number`
- `usedKapitelIds: string[]`
- `explanation?: { lengthDecision: string; omittedTopics: string[]; preservedFocus: string[]; compressionNotes: string }`

Lesefluss-specific fields:
- `aufgabenstellung: string`
- `explanation: string`
- `originalLength: number`
- `leseflussLength: number`
- `usedKapitelIds: string[]`

### 5.9 `.../artifacts/combined/groups/{groupId}` (intermediate groups)

Writer: server only.

Fields:
- `groupNumber: number`
- `content: string`
- `heading: string`
- `topic: string`
- `sourceQuelleIds: string[]`
- `model: string`
- `usage: { ... }`
- `costUsd: number`
- `keySource?: "user"|"platform"`
- `createdAt: ts`

### 5.10 `.../runs/{runId}/summaries/{sourceKapitelId}`

Writer: server only.

Fields:
- `sourceKapitelId: string`
- `sourceRunId: string`
- `sourceType: "combined"|"shortened"`
- `content: string`
- `originalLength: number`
- `summaryLength: number`
- `model: string`
- `usage: { inputTokens: number; outputTokens: number; totalTokens: number }`
- `costUsd: number`
- `keySource?: "user"|"platform"`
- `createdAt: ts`
- `updatedAt?: ts`

### 5.11 Prompt templates + settings (unchanged conceptually)

- `users/{uid}/promptTemplates/{templateId}`:
  - `stage`, `name`, `instructions`, `placeholders`, `createdAt`, `updatedAt`
- `users/{uid}/promptSettings/active`:
  - `activeTemplates`, `askOnEachProcess`, `updatedAt`

### 5.12 Secrets (unchanged)

- `users/{uid}/secrets/openai` remains server-only (client denied).

## 6) Index plan (create in Firestore)

Expected V2 queries:

1. Projects list:
- `projects`: `where(archived == false) orderBy(updatedAt desc)` (or `createdAt`)

2. Quellen list (metadata only):
- `quellen`: `where(projektId == X) where(archived == false) orderBy(createdAt desc)`

3. Kapitels list:
- `kapitels`: `where(projektId == X) where(archived == false) orderBy(order asc)` (recommended) or `createdAt`

4. Kapitels for Quelle:
- `kapitels`: `where(projektId == X) where(quelleIds array-contains quelleId)`

5. Runs list for Kapitel:
- `runs`: `orderBy(index desc) limit N` (+ optional `where(archived == false)`)

You’ll likely need composite indexes for:
- Quellen: `(projektId, archived, createdAt)`
- Kapitels: `(projektId, archived, order)` or `(projektId, archived, createdAt)`
- Kapitels-for-Quelle: `(projektId, quelleIds)` (and maybe `archived` depending on filter)

## 7) Firestore rules V2 (strategy)

Principles:
- Per-user gating (`request.auth.uid == userId`) everywhere.
- Strong allowlists for writable fields.
- Explicit max sizes on large text fields (to avoid “platform key cost attack”).
- Backend-only collections remain client non-writable:
  - `secrets/*`
  - `versions/*`
  - `summaries/*`
  - `artifacts/combined/groups/*`

Key decisions:

1. **Client CRUD allowed**:
- projects, quellen metadata/content, kapitels, runs.

2. **Server-created docs; client can only “select version” updates**:
- results doc update: allow only updates needed for adopting a version (content + refinement.activeVersionId + selectedAt + updatedAt), and enforce size limits.
- artifacts doc update: same idea.

3. **Project archive is a state transition**:
- allow updating `archived` and `archivedAt`.

Recommended max sizes (tune later):
- **Word limit:** 7000 words (rules can’t count words; enforce in app code).
- **Rule character caps (approx safety rail):**
  - Quelle content `text.size() <= 140_000` and `wordCount <= 7000`
  - Result content `content.size() <= 140_000`
  - Artifact content `content.size() <= 140_000`
  - Prompt instructions `instructions.size() <= 50_000`

### 7.1 Rules matrix (who can do what)

| Path | Client read | Client create | Client update | Client delete | Notes |
|---|---:|---:|---:|---:|---|
| `users/{uid}` | ✅ | ✅ | ✅ (restricted) | ✅ (optional) | deny editing `allowPlatformKey` |
| `projects/{projectId}` | ✅ | ✅ | ✅ (archive instead of delete) | 🚫 | project “delete” = archive |
| `quellen/{quelleId}` (meta) | ✅ | ✅ | ✅ | ✅ (optional) | prefer archive if you want reversible deletes |
| `quellen/{quelleId}/content/main` | ✅ | ✅ | ✅ | ✅ (optional) | enforce max text size + `wordCount <= 7000` |
| `kapitels/{kapitelId}` | ✅ | ✅ | ✅ | ✅ (optional) | cycles can’t be prevented in rules → code must guard |
| `runs/{runId}` | ✅ | ✅ | ✅ (restricted) | ✅ (optional) | runs are archivable; server maintains progress counters |
| `results/{quelleId}` | ✅ | 🚫 | ✅ (restricted to “select version”) | 🚫 | server creates; client only adopts |
| `results/{quelleId}/versions/*` | ✅ | 🚫 | 🚫 | 🚫 | backend-only writes |
| `artifacts/{artifactId}` | ✅ | 🚫 | ✅ (restricted to “select version”) | 🚫 | server creates; client only adopts |
| `artifacts/{artifactId}/versions/*` | ✅ | 🚫 | 🚫 | 🚫 | backend-only writes |
| `artifacts/combined/groups/*` | ✅ | 🚫 | 🚫 | 🚫 | server-only |
| `summaries/*` | ✅ | 🚫 | 🚫 | 🚫 | server-only |
| `promptTemplates/*` | ✅ | ✅ | ✅ | ✅ | stage validation + size limits |
| `promptSettings/active` | ✅ | ✅ | ✅ | ✅ | simple |
| `secrets/*` | 🚫 | 🚫 | 🚫 | 🚫 | fully client-denied |

### 7.2 Rules skeleton (near-final structure)

This is intentionally “shape-first” so the real `firestore.rules` rewrite is mechanical.

Helpers:
- `isAuthenticated()`
- `isOwner(userId)`
- `isTs(x)` (timestamp-like check; at minimum ensure the field exists; rules can’t perfectly validate Timestamp type)
- `isNonEmptyString(s, maxSize)`
- `isValidStage(stage)`

Matches to implement:

- `/users/{userId}`
  - read: owner
  - create/update: owner, deny `allowPlatformKey` changes
- `/users/{userId}/projects/{projectId}`
  - read: owner
  - create: owner + required keys (`name`, `ownerId`, `createdAt`, `updatedAt`, `archived`)
  - update: owner + allow toggling `archived`/`archivedAt` + updating `name`/`updatedAt`
  - delete: false
- `/users/{userId}/quellen/{quelleId}`
  - read: owner
  - create/update: owner + validate `projektId` references an existing project (and optionally `archived == false`)
  - enforce small-ish metadata sizes (title length etc)
- `/users/{userId}/quellen/{quelleId}/content/{contentId}`
  - allow only `contentId == "main"`
  - read/write: owner + enforce `text.size() <= MAX_QUELLE_TEXT_CHARS` and `wordCount <= 7000`
- `/users/{userId}/kapitels/{kapitelId}`
  - create/update: owner + require `projektId` exists + enforce `parentId` is present (can be null)
- `/users/{userId}/kapitels/{kapitelId}/runs/{runId}`
  - create/update: owner + restrict client-updatable keys (instruction, model, prompt fields, autoCombine, updatedAt)
- `/users/{userId}/kapitels/{kapitelId}/runs/{runId}/results/{quelleId}`
  - read: owner
  - create/delete: false
  - update: owner + only allow adopting fields (content/hasContent/refinement.*/updatedAt) + max size
  - `/versions/{versionId}`: read owner; write false
- `/users/{userId}/kapitels/{kapitelId}/runs/{runId}/artifacts/{artifactId}`
  - `artifactId in ["combined","shortened","lesefluss"]`
  - read: owner
  - create/delete: false
  - update: owner + only allow adopting fields (content/refinement.*/updatedAt + shortened/lesefluss derived fields) + max size
  - `/versions/{versionId}`: read owner; write false
  - `/groups/{groupId}` (only if `artifactId == "combined"`): read owner; write false
- `/users/{userId}/kapitels/{kapitelId}/runs/{runId}/summaries/{summaryId}`
  - read owner; write false

Important limitation (rules can’t solve):
- You cannot reliably enforce Kapitel parent graphs (no cycles) in rules. This remains a code responsibility.

## 8) Migration plan (big-bang)

You said you’re OK with deleting data, but you also want a migration script.
So we plan for a script that can either:
- migrate existing data into V2, OR
- optionally wipe and reseed.

### 8.1 Recommended approach

1. **Maintenance window** (avoid running the app during migration).
2. Run a migration script that:
   - creates V2 documents (new paths + normalized fields)
   - copies versions subcollections to new locations
   - converts all timestamps to Firestore Timestamps
   - converts all costs to USD float
   - deletes old singleton collections (`combined`, `shortened`, `lesefluss`) and moves `intermediate_groups`
3. Deploy:
   - updated `firestore.rules`
   - updated Next.js + FastAPI code

### 8.2 Script implementation outline

Location (suggested): `fastapi/scripts/migrate_firestore_v2.py`

Why Python:
- Repo already has `firebase-admin` in `fastapi/requirements.txt`.
- Reuse existing env config (`FIREBASE_PROJECT_ID`, `FIREBASE_PRIVATE_KEY`, `FIREBASE_CLIENT_EMAIL`).

High-level steps (per user):

1. Add missing archive fields:
   - projects/quellen/kapitels: set `archived=false` if missing.
2. Split Quellen content:
   - read old `users/{uid}/quellen/{quelleId}.content`
   - write `users/{uid}/quellen/{quelleId}` metadata without large content
   - write `users/{uid}/quellen/{quelleId}/content/main.text`
3. Runs migration:
   - For each run:
     - Create `artifacts/{combined|shortened|lesefluss}` from old singleton collections:
       - old `combined/combined` → `artifacts/combined`
       - old `shortened/shortened` → `artifacts/shortened`
       - old `lesefluss/lesefluss` → `artifacts/lesefluss`
     - Convert:
       - `created_at` ISO string → Timestamp
       - `cost` cents → `costUsd = cost/100.0`
       - snake_case fields → camelCase
     - Move versions:
       - old `combined/combined/versions/*` → `artifacts/combined/versions/*`
       - old `shortened/shortened/versions/*` → `artifacts/shortened/versions/*`
       - old `lesefluss/lesefluss/versions/*` → `artifacts/lesefluss/versions/*`
       - result versions keep same path but normalize field names/types
     - Move intermediate groups:
       - old `intermediate_groups/*` → `artifacts/combined/groups/*`
     - Normalize results docs:
       - `result_content` → `content`, `model_used` → `model`, token fields → `usage.*`, `created_at` → `createdAt`
       - add/normalize `refinement` map
     - Normalize summaries:
       - `summary_content` → `content`, costs/timestamps normalized
4. Optionally compute run progress summaries:
   - `resultsExpectedCount` from Kapitel’s `quelleIds` length at run creation time (or from current Kapitel assignment)
   - `resultsCompletedCount` from count of results docs
   - set `artifactsStatus` based on presence of artifacts docs
5. Cleanup old structure:
   - delete `combined/*`, `shortened/*`, `lesefluss/*`, `intermediate_groups/*`
   - (optional) delete legacy fields like `content` on Quelle metadata docs

### 8.4 Field mapping (old → V2)

This makes the migration script mostly “rename + convert”.

**Quelle**
- old `users/{uid}/quellen/{quelleId}.content` → new `users/{uid}/quellen/{quelleId}/content/main.text`
- keep metadata fields on `users/{uid}/quellen/{quelleId}`
- add: `archived=false` if missing

**Result (`runs/{runId}/results/{quelleId}`)**
- `result_content` → `content`
- `has_content` → `hasContent`
- `model_used` → `model`
- `tokens_used` → `usage.totalTokens`
- `input_tokens` → `usage.inputTokens`
- `cached_input_tokens` → `usage.cachedInputTokens`
- `output_tokens` → `usage.outputTokens`
- `reasoning_tokens` → `usage.reasoningTokens`
- `created_at` → `createdAt` (Timestamp)
- `cost` → `costUsd` (already USD float)
- `key_source` → `keySource`

**Combined (`combined/combined`) → `artifacts/combined`**
- `combined_content` → `content`
- `source_quelle_ids` → `sourceQuelleIds`
- `heading`, `topic` → keep
- token + cost fields → `usage.*`, `costUsd`
- `created_at` → `createdAt` (Timestamp)

**Intermediate groups (`intermediate_groups/*`) → `artifacts/combined/groups/*`**
- `group_number` → `groupNumber`
- `combined_content` → `content`
- `source_quelle_ids` → `sourceQuelleIds`
- token + cost → normalize
- `created_at` → `createdAt` (Timestamp)

**Shortened (`shortened/shortened`) → `artifacts/shortened`**
- `shortened_content` → `content`
- `used_kapitel_ids` → `usedKapitelIds`
- `original_length` → `originalLength`
- `shortened_length` → `shortenedLength`
- `tokens_used.input|cached_input|output` → `usage.inputTokens|cachedInputTokens|outputTokens` (set `reasoningTokens=0`)
- `cost` (cents int) → `costUsd = cost / 100.0`
- `created_at` (ISO string) → `createdAt` (Timestamp)

**Lesefluss (`lesefluss/lesefluss`) → `artifacts/lesefluss`**
- `lesefluss_content` → `content`
- `used_kapitel_ids` → `usedKapitelIds`
- `original_length` → `originalLength`
- `lesefluss_length` → `leseflussLength`
- tokens/cost/created_at conversions same as shortened

**Summaries (`summaries/*`)**
- `summary_content` → `content`
- `source_kapitel_id` → `sourceKapitelId`
- `source_run_id` → `sourceRunId`
- `source_type` → `sourceType`
- `tokens_used.input|output` → `usage.inputTokens|outputTokens` (+ `totalTokens = input+output`)
- `cost` (cents int) → `costUsd = cost / 100.0`
- `created_at` (ISO string) → `createdAt` (Timestamp)

**Refinement versions (`versions/*`)**
- `parent_version_id` → `parentVersionId`
- `assistant_text` → `assistantText`
- `user_message` → `userMessage`
- `error_message` → `errorMessage`
- `created_at` → `createdAt` (Timestamp)
- `updated_at` (ISO string) → `updatedAt` (Timestamp)
- `cost` is already USD float in refinement → rename to `costUsd`
- `usage.*` keys → camelCase (`inputTokens`, `cachedInputTokens`, `outputTokens`, `reasoningTokens`, `totalTokens`)

### 8.3 Verification checklist after migration

- For each user:
  - project counts match
  - quellen metadata count matches and each has `content/main`
  - for a sample run:
    - artifacts exist and versions moved
    - intermediate groups show up in UI
    - results docs have camelCase + timestamps
    - summaries readable and timestamps are Timestamp
