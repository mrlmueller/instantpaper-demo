# InstantPaper — Firestore Database Integration Audit (Current State)

Generated from repository code (Next.js + FastAPI) on 2025-12-19.

## Scope

- **In scope:** Firebase **Cloud Firestore** usage (reads/writes/updates/deletes, queries, realtime listeners) in:
  - Next.js app (`app/…`)
  - FastAPI backend (`fastapi/…`)
  - Firestore security rules (`firestore.rules`)
- **Out of scope:** Cloud Storage (except where Firestore stores file metadata), Auth UX, non-Firestore persistence.

## Glossary (IDs & naming)

- `userId` / `uid`: Firebase Auth UID (`request.auth.uid`).
- `projektId`: A project document ID in `users/{uid}/projects/{projektId}`.
- `quelleId`: A source document ID in `users/{uid}/quellen/{quelleId}`.
- `kapitelId`: A chapter document ID in `users/{uid}/kapitels/{kapitelId}`.
- `runId`: A processing run document ID in `users/{uid}/kapitels/{kapitelId}/runs/{runId}`.

## Trust boundaries (critical for security + schema decisions)

### Next.js (frontend + server actions)

- Uses the **Firebase Web SDK** (`firebase/firestore`).
- Firestore calls run:
  - **Client-side** in React components (rules apply).
  - **Server actions** using `initializeServerApp(..., { authIdToken })` (rules also apply).
- Result: for Next.js reads/writes, **Firestore rules are the enforcement layer**.

References:

- `app/lib/firebase/config.ts`
- `app/lib/firebase/serverApp.ts`
- `app/lib/firebase/firestoreClient.ts`

### FastAPI backend

- Uses **Firebase Admin SDK** (`firebase_admin`, `firestore.client()`), i.e. **bypasses Firestore rules**.
- Security depends on:
  - Correct token verification (`fastapi/middleware/auth.py`)
  - Correct mapping of `user_id` from token UID (not from request body)
  - Defensive coding in backend services

References:

- `fastapi/services/firebase_service.py`
- `fastapi/middleware/auth.py`
- `fastapi/main.py`

## Firestore rules (current)

Source: `firestore.rules`

High-level behavior:

- Default deny (`match /{document=**} { allow read, write: if false; }`).
- Per-user data is under `users/{userId}` and gated by `request.auth.uid == userId`.
- `users/{userId}/secrets/*` is **fully denied to clients** (`allow read, write: if false;`).
- Text refinement `versions/*` are **readable** to the user but **not writable** by clients (`allow write: if false;`), with an explicit “backend-only writes” note.

## Where Firestore is accessed (code map)

### Next.js — server actions (`app/actions/*`)

- User profile:
  - `app/actions/user.ts` (`createOrUpdateUser`)
- Projects:
  - `app/actions/projects.ts` (`getProjects`, `createProject`, `renameProject`, `deleteProject`, `getOrCreateDefaultProject`)
- Quellen (sources):
  - `app/actions/quellen.ts` (`createQuelle`, `updateQuelle`, `deleteQuelle`, `getQuelle`, `getUserQuellen`, `updateQuelleColor`, `bulkAssignQuellen`, `getKapitelsForQuelle`)
- Kapitels + runs + reading run subcollections:
  - `app/actions/kapitels.ts` (`createKapitel`, `updateKapitelQuellen`, `updateKapitelParent`, `updateKapitelTitle`, `deleteKapitel`, `createKapitelRun`, `getKapitelRuns`, `getUserKapitels`, `getShortenedResult`, `getSummaries`)
- Prompt templates + settings:
  - `app/actions/promptTemplates.ts` (`listPromptTemplates`, `createPromptTemplate`, `updatePromptTemplate`, `deletePromptTemplate`, `setActivePrompt`, `setAskOnEachProcess`, `getActivePromptInstructions`)

### Next.js — client components (`app/components/dashboard/*`)

- Dashboard (direct writes + realtime listeners):
  - `app/components/dashboard/Dashboard.tsx`
- Refinement dialogs (read versions + update “active version” on base docs):
  - `app/components/dashboard/CombinedRefinementDialog.tsx`
  - `app/components/dashboard/ShortenedRefinementDialog.tsx`
  - `app/components/dashboard/LeseflussRefinementDialog.tsx`
  - `app/components/dashboard/ResultRefinementDialog.tsx`

### FastAPI — direct Firestore client usage

All direct Firestore operations are centralized in:

- `fastapi/services/firebase_service.py`

Other services call into `firebase_service`:

- `fastapi/services/quelle_service.py` (process single Quelle; combine run results; hierarchical combine)
- `fastapi/services/shorten_service.py` (summaries, shorten, lesefluss)
- `fastapi/services/refinement_service.py` (text refinement “versions” flow)
- `fastapi/services/user_key_service.py` (OpenAI key storage in `secrets/openai`)
- `fastapi/services/prompt_service.py` (reads prompt settings/templates)

## Current database structure (path tree)

Everything is nested under a per-user root:

```
users/{uid}                                  // user profile doc
  projects/{projektId}                        // user projects
  quellen/{quelleId}                          // sources (text + optional images metadata)
  kapitels/{kapitelId}                        // chapters
    runs/{runId}                              // processing runs per Kapitel
      results/{quelleId}                      // per-Quelle output for this run
        versions/{versionId}                  // per-result refinement versions (backend writes only)
      combined/combined                        // single “combined output” doc (stored as a collection with one doc)
        versions/{versionId}                  // combined refinement versions (backend writes only)
      intermediate_groups/{groupId}           // optional hierarchical-combine intermediate docs
      shortened/shortened                      // single “shortened output” doc (collection with one doc)
        versions/{versionId}                  // shortened refinement versions (backend writes only)
      lesefluss/lesefluss                      // single “lesefluss output” doc (collection with one doc)
        versions/{versionId}                  // lesefluss refinement versions (backend writes only)
      summaries/{sourceKapitelId}             // cached summaries per source Kapitel
  promptTemplates/{templateId}                // prompt templates per stage
  promptSettings/active                       // active template selections, askOnEachProcess
  secrets/openai                              // encrypted OpenAI key (server-only)
```

## Collection-by-collection details (schema + operations)

### `users/{uid}` (user profile document)

**Observed fields (Next.js writes):**

- `uid`, `email`, `displayName`, `photoURL`
- `createdAt` (Firestore timestamp), `updatedAt` (Firestore timestamp)

**Reads/Writes:**

- Read: none in Next.js (besides auth); FastAPI reads user doc to check `allowPlatformKey`.
- Create (if missing): Next.js server action.
- Update (merge): Next.js server action.
- Delete: allowed by rules but not used in code currently.

**Code references:**

- Create/update: `app/actions/user.ts` (`createOrUpdateUser`)
- Read: `fastapi/services/firebase_service.py` (`get_user_doc`, `get_allow_platform_key`)

**Rule notes:**

- Users can’t set/modify `allowPlatformKey` themselves (explicitly blocked in rules).

---

### `users/{uid}/projects/{projektId}`

**Observed fields (Next.js writes):**

- `name` (string)
- `ownerId` (string, equals `uid`)
- `createdAt`, `updatedAt` (Firestore timestamps)

**Reads/Writes/Deletes:**

- Read:
  - List: `orderBy('createdAt', 'desc')`
  - Get default: `getDoc(users/{uid}/projects/default)`
- Create:
  - Default project uses fixed id `default`.
  - Custom projects use random id (`doc(projectsRef)`).
- Update: rename project sets `name` + `updatedAt` via `setDoc(..., { merge: true })`.
- Delete: deletes only the project doc (no cascade cleanup of related docs in code).

**Code references:**

- `app/actions/projects.ts`

**Notes (current behavior):**

- Many other documents carry a `projektId` field. Deleting a project doc does **not** delete the related Quellen/Kapitels/Runs; they become “orphaned” by project selection logic.

---

### `users/{uid}/quellen/{quelleId}`

**Observed fields (Next.js writes):**

- Core: `title`, `content`, `projektId`, `createdAt`, `updatedAt`
- Optional: `images[]` (metadata objects) + advanced metadata:
  - `autor`, `jahr`, `typ`, `url`, `zugriffAm`, `color`

**Reads/Writes/Deletes:**

- Read:
  - Single: `getDoc(users/{uid}/quellen/{quelleId})`
  - List by project: `where('projektId','==',projektId).orderBy('createdAt','desc')`
- Create: `addDoc(users/{uid}/quellen, …)`
- Update: `updateDoc(users/{uid}/quellen/{quelleId}, …)`
- Delete:
  - Deletes Firestore doc
  - Also deletes associated files in Cloud Storage (out of scope for this audit, but relevant because Firestore stores the file `path`)

**Code references:**

- `app/actions/quellen.ts` (all operations)
- Read by backend: `fastapi/services/firebase_service.py` (`get_quelle`)

**Notes (current behavior):**

- Quellen are used as the “atomic input” for AI processing. FastAPI reads `quelle.content` (+ optional image URLs) and writes results under `runs/.../results/...`.

---

### `users/{uid}/kapitels/{kapitelId}`

**Observed fields (Next.js writes):**

- `title` (string)
- `projektId` (string)
- `nummer` (string, hierarchical numbering like `"1"`, `"1.1"`, …)
- `quelleIds` (string[])
- Hierarchy/ordering:
  - `parentId` (string|null)
  - `order` (number)
- `createdAt`, `updatedAt` (Firestore timestamps)

**Reads/Writes/Deletes:**

- Read:
  - List by project: `where('projektId','==',projektId).orderBy('createdAt','desc')`
  - Various `getDoc` calls for parent checks / depth / circular reference.
- Create:
  - Server action: `addDoc(users/{uid}/kapitels, …)` (does parent validation, depth check, and attempts to compute `order`)
  - Client component: also directly `addDoc(...)` (simpler, sets `order: Date.now()`)
- Update:
  - Update title/nummer
  - Update assigned Quellen (`quelleIds`)
  - Update hierarchy (`parentId`, `order`)
- Delete:
  - Server action supports `promote` or `cascade` (but finds children by scanning the whole collection client-side in memory).
  - Client component also directly deletes the Kapitel doc (no child handling).

**Code references:**

- Server actions: `app/actions/kapitels.ts`
- Client direct writes: `app/components/dashboard/Dashboard.tsx`

**Notes (current behavior):**

- There are **two** write paths (server action + client direct writes) to the same collection, which can lead to inconsistent enforcement of invariants like “no circular parent chains” and “max depth”.

---

### `users/{uid}/kapitels/{kapitelId}/runs/{runId}`

**Observed fields (Next.js writes):**

- Required-ish: `instruction`, `model`, `projektId`, `index`, `createdAt`
- Optional controls/metadata:
  - `promptTemplateId`
  - `promptPayload` (object; contains fields like `heading`, `topic`)
  - `autoCombine` (boolean)
  - `grundlegendeInformationen` (string|null)
  - `ueberschrift`, `thema` (strings|null)

**Reads/Writes:**

- Read:
  - Next.js:
    - Initial fetch: `getDocs(orderBy('index','desc').limit(N))`
    - Realtime listener: `onSnapshot(query(orderBy('index','desc').limit(N)))`
  - FastAPI:
    - Reads run doc to get processing metadata (e.g., model, `promptPayload`, `grundlegendeInformationen`, `autoCombine`)
- Create: Next.js server action `createKapitelRun` uses `addDoc` with computed `index`.
- Update: not heavily used directly, but fields are read frequently.
- Delete: rules allow delete but not used in code currently.

**Code references:**

- Create: `app/actions/kapitels.ts` (`createKapitelRun`)
- Realtime list: `app/components/dashboard/Dashboard.tsx`
- Read: `fastapi/services/firebase_service.py` (`get_run`, `get_kapitel_runs`, `get_kapitel_run`)

---

## Run subcollections

### `.../results/{quelleId}` (per-Quelle result for a run)

**Created by FastAPI (Admin SDK):**

- Path: `users/{uid}/kapitels/{kapitelId}/runs/{runId}/results/{quelleId}`
- Document id equals `quelleId` (and the doc also redundantly stores `quelle_id`)

**Observed fields (FastAPI writes):**

- `quelle_id` (string, redundant)
- `user_input` (string)
- `result_content` (string)
- `has_content` (bool)
- `model_used` (string)
- `tokens_used` (int)
- `input_tokens`, `cached_input_tokens`, `output_tokens`, `reasoning_tokens` (ints)
- `cost` (**USD float**)
- `key_source` (string, optional)
- `created_at` (Firestore timestamp)

**Client reads (Next.js):**

- Realtime listener on the `results` collection (`onSnapshot(resultsRef)`).
- Also read in server actions via `getDocs(resultsRef)` when building run details.

**Client updates (Next.js):**

- When a refinement version is selected, the client updates the base result doc:
  - `result_content`, `has_content`, `refinement_active_version_id`, `refinement_selected_at`

**Code references:**

- Write: `fastapi/services/firebase_service.py` (`save_result`)
- Orchestration: `fastapi/services/quelle_service.py` (`process_single_quelle`)
- Read (Next.js UI): `app/components/dashboard/Dashboard.tsx`
- Read (Next.js server): `app/actions/kapitels.ts` (`getKapitelRuns`)
- Client update on selection: `app/components/dashboard/ResultRefinementDialog.tsx`

---

### `.../results/{quelleId}/versions/{versionId}` (result refinement versions)

**Created/updated by FastAPI only (Admin SDK):**

- Root version id is always `root` (created lazily by `ensure_result_refinement_root_version`).
- New versions are created as UUIDs with `status: "running"` and later updated to `"success"`/`"error"`.

**Observed fields (FastAPI writes):**

- Common: `parent_version_id`, `depth`, `user_message`, `assistant_text`, `status`, `model`, `cost`, `created_at`
- When finished: `usage` object with token breakdown, `key_source`, `updated_at`
- Error: `error_message`, `updated_at`

**Next.js reads:**

- Client subscribes to the `versions` collection and renders a refinement “tree”.

**Code references:**

- Firestore ops: `fastapi/services/firebase_service.py` (`save_result_refinement_version`, `update_result_refinement_version`, `ensure_result_refinement_root_version`)
- Version queue/process: `fastapi/services/refinement_service.py` (`queue_result_refinement`, `process_result_refinement`)
- Read + UI: `app/components/dashboard/ResultRefinementDialog.tsx`

**Rule note:**

- Rules allow read but deny client writes (`allow write: if false;`).

---

### `.../combined/combined` (combined result, stored as “singleton doc in a collection”)

**Created by FastAPI (Admin SDK):**

- Path: `.../runs/{runId}/combined/combined`

**Observed fields (FastAPI writes):**

- `combined_content` (string)
- `source_quelle_ids` (string[])
- `heading`, `topic` (strings)
- `model_used` (string)
- `tokens_used`, `input_tokens`, `cached_input_tokens`, `output_tokens`, `reasoning_tokens` (ints)
- `cost` (**USD float**)
- `key_source` (optional)
- `created_at` (Firestore timestamp)

**Next.js reads:**

- Typically via `onSnapshot(combinedRef)` on the **collection** and then taking the first doc.
- Server actions also `getDocs(combinedRef)` and take `docs[0]`.

**Next.js updates:**

- When selecting a refinement version:
  - `combined_content`, `refinement_active_version_id`, `refinement_selected_at`

**Code references:**

- Write: `fastapi/services/firebase_service.py` (`save_combined_result`)
- Combine orchestration: `fastapi/services/quelle_service.py` (`combine_run_results`, `_hierarchical_combine`)
- Read: `app/components/dashboard/Dashboard.tsx`, `app/actions/kapitels.ts`
- Client update on selection: `app/components/dashboard/CombinedRefinementDialog.tsx`

**Notes (current behavior):**

- Data model uses a collection `combined` with a fixed doc id `combined`. Many reads use `collection(..., 'combined')` + “take first doc”, which costs extra reads and assumes only one doc exists.

---

### `.../combined/combined/versions/{versionId}` (combined refinement versions)

Same pattern as result refinement versions:

- Created/updated by FastAPI only.
- Read by Next.js.
- Base `combined/combined` doc is updated client-side when user “adopts” a version.

**Code references:**

- Firestore ops: `fastapi/services/firebase_service.py` (`save_combined_refinement_version`, `update_combined_refinement_version`, `ensure_combined_refinement_root_version`)
- Queue/process: `fastapi/services/refinement_service.py` (`queue_combined_refinement`, `process_combined_refinement`)
- UI: `app/components/dashboard/CombinedRefinementDialog.tsx`

---

### `.../intermediate_groups/{groupId}` (hierarchical combine intermediates)

**Created by FastAPI only (Admin SDK):**

- Document id pattern: `group_{group_number}`

**Observed fields:**

- `group_number` (int)
- `combined_content`, `source_quelle_ids`, `heading`, `topic`
- Token/cost fields similar to combined result
- `cost` (**USD float**)
- `created_at` (Firestore timestamp)

**Reads:**

- FastAPI can stream and sort groups (`get_intermediate_groups`).
- Next.js server action reads via `getDocs(intermediate_groups)` (no ordering).

**Code references:**

- Write: `fastapi/services/firebase_service.py` (`save_intermediate_group_result`)
- Read: `fastapi/services/firebase_service.py` (`get_intermediate_groups`)
- Next.js read: `app/actions/kapitels.ts` (`getKapitelRuns`)

---

### `.../shortened/shortened` (shortened result)

**Created by FastAPI (Admin SDK):**

- Path: `.../runs/{runId}/shortened/shortened`

**Observed fields (FastAPI writes):**

- `shortened_content` (string)
- `explanation` object:
  - `length_decision`, `omitted_topics`, `preserved_focus`, `compression_notes`
- `original_length`, `shortened_length`, `compression_ratio` (numbers)
- `used_kapitel_ids` (string[])
- `model` (string)
- `tokens_used` object: `{ input, cached_input, output }`
- `cost` (**integer cents**)
- `created_at` (ISO string, not Firestore timestamp)
- `key_source` (string)

**Next.js reads:**

- Client `onSnapshot(shortenedRef)` on the collection and then takes the first doc.
- Server action `getShortenedResult` reads the fixed doc directly.

**Next.js updates:**

- When selecting a refinement version:
  - `shortened_content`, `shortened_length`, `refinement_active_version_id`, `refinement_selected_at`

**Code references:**

- Write: `fastapi/services/shorten_service.py` → `fastapi/services/firebase_service.py` (`save_shortened_result`)
- Read: `app/components/dashboard/Dashboard.tsx`, `app/actions/kapitels.ts` (`getKapitelRuns`), `app/actions/kapitels.ts` (`getShortenedResult`)
- Client update on selection: `app/components/dashboard/ShortenedRefinementDialog.tsx`

**Notes (current behavior):**

- This doc mixes **cents** for `cost` and **string** for `created_at`, while other collections often use USD floats + Firestore timestamps.

---

### `.../shortened/shortened/versions/{versionId}` (shortened refinement versions)

- Created/updated by FastAPI only.
- Read by Next.js.
- Metadata fields (`refinement_*`) are set/updated on the base shortened doc.

**Code references:**

- Firestore ops: `fastapi/services/firebase_service.py` (`save_shortened_refinement_version`, `update_shortened_refinement_version`, `ensure_shortened_refinement_root_version`)
- Queue/process: `fastapi/services/refinement_service.py` (`queue_shortened_refinement`, `process_shortened_refinement`)
- UI: `app/components/dashboard/ShortenedRefinementDialog.tsx`

---

### `.../lesefluss/lesefluss` (lesefluss result)

**Created by FastAPI (Admin SDK):**

- Path: `.../runs/{runId}/lesefluss/lesefluss`

**Observed fields (FastAPI writes):**

- `lesefluss_content` (string)
- `aufgabenstellung` (string)
- `explanation` (string)
- `original_length`, `lesefluss_length` (numbers)
- `used_kapitel_ids` (string[])
- `model` (string)
- `tokens_used` object: `{ input, cached_input, output }`
- `cost` (**integer cents**)
- `created_at` (ISO string)
- `key_source` (string)

**Next.js reads:**

- Client listens via `onSnapshot(leseflussRef)` on the collection and takes the first doc.
- Server action reads via `getDocs(leseflussRef)` and takes `docs[0]`.

**Next.js updates:**

- When selecting a refinement version:
  - `lesefluss_content`, `lesefluss_length`, `explanation`, `refinement_active_version_id`, `refinement_selected_at`

**Code references:**

- Write: `fastapi/services/shorten_service.py` → `fastapi/services/firebase_service.py` (`save_lesefluss_result`)
- Read: `app/components/dashboard/Dashboard.tsx`, `app/actions/kapitels.ts` (`getKapitelRuns`)
- Client update on selection: `app/components/dashboard/LeseflussRefinementDialog.tsx`

---

### `.../lesefluss/lesefluss/versions/{versionId}` (lesefluss refinement versions)

Same pattern as other refinement version collections.

**Code references:**

- Firestore ops: `fastapi/services/firebase_service.py` (`save_lesefluss_refinement_version`, `update_lesefluss_refinement_version`, `ensure_lesefluss_refinement_root_version`)
- Queue/process: `fastapi/services/refinement_service.py` (`queue_lesefluss_refinement`, `process_lesefluss_refinement`)
- UI: `app/components/dashboard/LeseflussRefinementDialog.tsx`

---

### `.../summaries/{sourceKapitelId}` (cached summaries)

**Created by FastAPI (Admin SDK):**

- Path: `.../runs/{runId}/summaries/{sourceKapitelId}`
- Doc id is the `source_kapitel_id` (the Kapitel that was summarized).

**Observed fields (FastAPI writes):**

- `summary_content` (string)
- `source_kapitel_id`, `source_run_id` (strings)
- `source_type` (`"combined"` | `"shortened"`)
- `original_length`, `summary_length` (numbers)
- `model` (string)
- `tokens_used` object: `{ input, output }`
- `cost` (**integer cents**)
- `created_at` (ISO string)
- `key_source` (string)

**Next.js reads:**

- Server action `getSummaries` reads entire `summaries` collection via `getDocs()`.

**Code references:**

- Write: `fastapi/services/shorten_service.py` → `fastapi/services/firebase_service.py` (`save_summary_result`)
- Read: `app/actions/kapitels.ts` (`getSummaries`)

---

## Prompt config collections

### `users/{uid}/promptTemplates/{templateId}`

**Created/updated/deleted by Next.js (rules apply).**

**Observed fields:**

- `stage` (`process_quelle` | `combine` | `shorten` | `lesefluss` | `summary`)
- `name`, `instructions`
- `placeholders` (string[])
- `createdAt`, `updatedAt` (Firestore timestamps)

**Reads/Writes:**

- Next.js:
  - list all templates (no filter)
  - enforce per-stage max templates via `where('stage','==',stage)`
  - update without allowing stage change
  - delete and unselect if it was active
- FastAPI reads selected template instructions via prompt settings.

**Code references:**

- Next.js: `app/actions/promptTemplates.ts`
- FastAPI read: `fastapi/services/firebase_service.py` (`get_prompt_template`)

---

### `users/{uid}/promptSettings/active`

**Observed fields (Next.js writes):**

- `activeTemplates`: map `{ [stage: string]: templateId | "default" }`
- `askOnEachProcess`: boolean
- `updatedAt`: Firestore timestamp

**Reads/Writes:**

- Next.js reads and updates this doc frequently to store prompt selections.
- FastAPI reads it to choose instructions (`get_active_prompt_id`).

**Code references:**

- Next.js: `app/actions/promptTemplates.ts`
- FastAPI: `fastapi/services/firebase_service.py` (`get_active_prompt_id`)

---

## Secrets (server-only)

### `users/{uid}/secrets/openai`

**Access model:**

- Firestore rules deny all reads/writes from clients.
- FastAPI uses Admin SDK to read/write anyway.

**Observed fields (FastAPI writes):**

- `iv`, `ciphertext`, `tag` (encryption payload)
- `last4` (string)
- `created_at`, `updated_at` (Firestore timestamps)

**Operations:**

- Set/overwrite (create if missing): `save_user_openai_secret`
- Get: `get_user_openai_secret`
- Delete: `delete_user_openai_secret`

**Code references:**

- Firestore ops: `fastapi/services/firebase_service.py` (secret methods)
- Endpoint surface: `fastapi/main.py` (`/api/user/openai-key` GET/POST/DELETE)

## Realtime listeners (Next.js client)

All current `onSnapshot` listeners:

- Runs list for active Kapitel:
  - `users/{uid}/kapitels/{activeKapitelId}/runs` (query: `orderBy(index desc) limit N`)
  - `app/components/dashboard/Dashboard.tsx`
- Selected run detail listeners (4 parallel listeners):
  - `.../runs/{runId}/combined` (collection)
  - `.../runs/{runId}/shortened` (collection)
  - `.../runs/{runId}/lesefluss` (collection)
  - `.../runs/{runId}/results` (collection)
  - `app/components/dashboard/Dashboard.tsx`
- Per-Kapitel “status” watcher:
  - Latest run per Kapitel: `.../runs` (query: `orderBy(index desc) limit 1`)
  - Combined presence: `.../runs/{latestRunId}/combined` (collection)
  - `app/components/dashboard/Dashboard.tsx`
- Refinement dialogs:
  - Base doc (`combined/combined`, `shortened/shortened`, `lesefluss/lesefluss`, `results/{quelleId}`)
  - Versions collection under that base doc
  - `app/components/dashboard/*RefinementDialog.tsx`

## Cross-cutting inconsistencies observed in code (important for “schema rework” planning)

These are not “fixes” yet — just what the code currently implies:

1. **Field naming drift (snake_case vs camelCase)**

   - Many readers use fallback patterns like `foo_bar ?? fooBar`.
   - Example: `app/actions/kapitels.ts` mapping for combined/results/intermediateGroups/shortened/lesefluss.

2. **Mixed timestamp formats**

   - Some docs use Firestore timestamps: `createdAt`/`updatedAt` or `created_at: SERVER_TIMESTAMP`.
   - Others store ISO strings: e.g. shortened/lesefluss/summaries use `created_at: datetime.utcnow().isoformat()+"Z"`.

3. **Mixed cost units**

   - Results + combined store `cost` as **USD float**.
   - Shortened + lesefluss + summaries store `cost` as **integer cents**.

4. **“Singleton doc stored as collection” pattern**

   - `combined`, `shortened`, `lesefluss` are modeled as collections but typically contain one fixed-id doc.
   - Many reads use `getDocs(collectionRef)` and take `docs[0]` (extra reads; ambiguous if multiple docs appear).

5. **Multiple write paths to same collections**
   - Kapitels are written via server actions **and** direct client writes, with different validation behavior.

## Query patterns & likely index needs (based on code)

Potential composite indexes (exact requirements depend on the Firestore console/index state):

- `users/{uid}/quellen`: `where(projektId == X) + orderBy(createdAt desc)`
- `users/{uid}/kapitels`: `where(projektId == X) + orderBy(createdAt desc)`
- `users/{uid}/kapitels`: `where(projektId == X) + where(quelleIds array-contains Y)` (used in “Kapitels for Quelle”)

## Verification checklist (things to confirm in the live Firestore project)

- Ensure composite indexes exist for the queries above (if you see “requires an index” errors).
- Confirm whether `created_at` fields in shortened/lesefluss/summaries are strings or timestamps in production (readers currently assume both in different places).
- Confirm whether any runs have multiple docs under `combined/` (or `shortened/`, `lesefluss/`) — the UI assumes “first doc”.
