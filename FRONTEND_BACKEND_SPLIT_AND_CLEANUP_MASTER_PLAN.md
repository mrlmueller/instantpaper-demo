# Frontend / Backend Split And Cleanup Master Plan

Stand: 2026-03-27

This document is the implementation plan for restructuring this repository into a clean `frontend/` and `backend/` split while also removing stale code, isolating research/testing assets, and fixing deployment/config drift.

It is intentionally broader than a folder-move checklist. The goal is:

1. Separate the repo cleanly into `frontend/` and `backend/`.
2. Make production runtime independent from `pdf-scan/` and `sources-v2/`.
3. Standardize the frontend/backend boundary.
4. Identify and remove stale or legacy code.
5. Make deploys and local setup reproducible.
6. Prepare the repo for accurate new README files later.

## Fixed Decisions From The User

These are already decided and should be treated as hard constraints:

- Root infra may remain at repo root.
- `frontend/` should become the Vercel Root Directory.
- `pdf-scan/` is testing/research only, not production runtime.
- `sources-v2/` is testing/research only, not production runtime.
- If deleting `pdf-scan/` later breaks the app, the refactor failed.
- If deleting `sources-v2/` later breaks the app, the refactor failed.
- Env cleanup is part of this refactor.
- `sources-review-dashboard` is only a local internal tool.
- The refactor should improve code quality, not only move files around.

## Live Infra Truth Verified On 2026-03-26

This section is based on live `gcloud` inspection, not only repo search.

### GCP / Firebase split

There are effectively two active projects:

- Cloud Run / Secret Manager project: `instantpaper`
- Firebase / Firestore / Storage / Stripe extension project: `instantpaper-e80e5`

This matters a lot. The repo is not a single-project deployment story today.

### Cloud Run resources in `instantpaper`

Observed live:

- Cloud Run service: `instantpaper-api` in `europe-west3`
- Cloud Run job: `instantpaper-two-lane-sources` in `europe-west3`
- Cloud Run job: `instantpaper-pdf-scan-cpu` in `europe-west3`
- Cloud Run job: `instantpaper-pdf-scan-gpu` in `europe-west1`

The backend service currently uses:

- `GOOGLE_CLOUD_PROJECT=instantpaper`
- `FIREBASE_PROJECT_ID=instantpaper-e80e5`
- `FIREBASE_STORAGE_BUCKET=instantpaper-e80e5.firebasestorage.app`

So the backend already runs cross-project.

### Cloud Functions in `instantpaper-e80e5`

Observed live in the Firebase project:

- Only Firebase Stripe extension functions are visible.
- I did **not** find custom deployed functions from the repo `functions/` package in the queried live project.

Visible extension functions include:

- `ext-firestore-stripe-payments-createPortalLink`
- `ext-firestore-stripe-payments-handleWebhookEvents`
- related Stripe extension event triggers

Implication:

- The web app definitely relies on the Stripe extension.
- The repo `functions/` folder is **not currently proven to be deployed** to the live Firebase project.
- Therefore `functions/` should be treated as a legacy/investigation item, not assumed production truth.

### Live Firestore indexes

Composite Firestore indexes already exist in `instantpaper-e80e5`, including at least:

- `projects`: `archived ASC`, `createdAt DESC`
- `kapitels`: `projektId ASC`, `archived ASC`, `order ASC`
- `quellen`: `archived ASC`, `projektId ASC`, `createdAt DESC`
- `runs`: `archived ASC`, `index DESC`

Implication:

- `firestore.indexes.json` is not optional documentation.
- It is a real missing repo artifact for reproducible Firebase setup.

## High-Level Recommendation

The clean target state should be:

- `frontend/` contains the only product web app.
- `backend/` contains the only product API/runtime.
- `testing-scripts/pdf-scan/` contains PDF-scan notebooks, research, benchmarks, experiments, local tools.
- `testing-scripts/sources-v2/` contains sources notebook/research code and the local review dashboard.
- Root keeps infra/config/docs only.
- `functions/` remains at root temporarily as a legacy/investigation exception unless explicitly migrated or retired.

I do **not** recommend moving `functions/` into `backend/` right now.

Reason:

- It is not part of the Cloud Run backend runtime.
- It is a separate Firebase/extension/billing concern.
- Live production currently proves Stripe extension usage, but does not prove repo custom Functions deployment.
- Moving it into `backend/` would blur responsibilities and make the repo less clean, not more.

Short version:

- `frontend/` and `backend/` should be the product code roots.
- `testing-scripts/` should hold research/test trees.
- `functions/` should either remain a root infra exception for now, or later be retired/replaced in a dedicated billing/webhooks pass.

## Implementation Progress On 2026-03-27

Work has already started. This plan is now a live migration document, not only a proposal.

Completed commits so far:

- `6af05c9` `feat(frontend): route app traffic through next bff`
- `cbcdd9e` `chore(frontend): remove stale auth shell and ui primitives`
- `a371ba6` `chore(frontend): remove unused kapitel skeleton`
- `1cc55ae` `fix(backend): isolate vendored pdf scan runtime`
- `3b8c85c` `refactor: reduce dashboard auth gating and harden pdf runtime defaults`
- `2bd192e` `refactor(repo): move research trees under testing-scripts`
- `3aa3473` `refactor(frontend): move next app into frontend root`
- `fc8069e` `refactor(backend): move fastapi service into backend root`

What is now already true in the repo:

- browser-side absolute FastAPI calls have been removed from the product frontend
- same-origin Next Route Handlers now cover billing, usage insights, gliederung generation/refinement, process, combine, adopt-combined, PDF-scan start/cancel, sources-two-lane start/cancel, and logout revoke
- `PdfScanWorkspace` and `QuellenFinder` no longer send `Authorization: Bearer ...` from the browser into same-origin `/api` calls
- a shared server helper now centralizes backend URL resolution and cookie-token lookup in `frontend/app/lib/server/fastapi.ts`
- several clearly unreferenced frontend components and UI primitives have already been removed
- `pdf-scan/` and `sources-v2/` no longer live at repo root; both have moved under `testing-scripts/`
- the production Next.js app no longer lives at repo root; it now lives under `frontend/`
- the production backend no longer lives in `fastapi/`; it now lives under `backend/`
- the frontend now expects a server-only `FASTAPI_BASE_URL` instead of reading `NEXT_PUBLIC_FASTAPI_URL`
- `frontend/.env.local.example` exists as the new tracked frontend env template
- `backend/.env.example` exists as the new tracked backend env template
- the Cloud Run deployment workflow and backend Dockerfiles now target `backend/`
- research/test scripts that used to read `fastapi/.env` now read `backend/.env`
- `frontend` has been verified with `npx tsc --noEmit` and `npm run build`
- `backend` has been verified with `python -m compileall`, targeted import/path checks, and a repaired prompt inventory generator run

Important remaining work after these commits:

- `Dashboard.tsx` still uses cookies for UI persistence, but the redundant client-side session-auth prechecks have been removed
- root and backend docs still need a proper rewrite around the new `frontend/` / `backend/` split
- backend runtime still contains lab-oriented phase files, even though the dangerous repo-/benchmark-default coupling has now been reduced
- external deployment settings still need to be switched to the new repo layout (`frontend/` in Vercel and `backend/` in any out-of-repo references)
- frontend `eslint` still reports a substantial pre-existing rules backlog (`no-explicit-any`, `set-state-in-effect`, image warnings, and related issues)
- `functions/` still needs a deliberate keep/retire decision with live verification

## Target Repo Layout

Recommended end state:

```text
/
  .github/
  docs/                           # optional later
  functions/                      # temporary legacy/investigation exception
  frontend/
    app/
    components/
    lib/
    public/
    package.json
    tsconfig.json
    next.config.ts
    proxy.ts
    eslint.config.mjs
    postcss.config.mjs
    next-env.d.ts                 # generated, not committed
    .env.local.example            # later
  backend/
    main.py
    middleware/
    models/
    services/
    utils/
    pdf_scan_runtime/
    scripts/
    Dockerfile
    Dockerfile.gpu
    requirements.txt
    requirements-gpu.txt
    README.md
    .env.example                  # later
  testing-scripts/
    pdf-scan/
      benchmark/
      research/
      tools/
      notebooks/
      local-data/                 # gitignored
    sources-v2/
      notebooks/
      extracted/
      tools/
      sources-review-dashboard/
      runs/                       # gitignored
    backend/
      smoke/
      manual/
  firestore.rules
  firestore.indexes.json          # add
  storage.rules
  firebase.json                   # add if Firebase deploys remain
  .firebaserc                     # add if Firebase deploys remain
  README.md                       # rewrite later
```

## Production Source Of Truth

### Frontend

Current production frontend is the root Next.js project, not only `app/`.

Production frontend currently depends on:

- `app/`
- `components/`
- `lib/`
- `public/`
- root `package.json`
- root `tsconfig.json`
- root `next.config.ts`
- root `proxy.ts`
- root `eslint.config.mjs`
- root `postcss.config.mjs`

This means the frontend move must move the **whole Next app**, not only `app/`.

### Backend

Current production backend is the current `backend/` tree only.

Production runtime already excludes:

- `pdf-scan/`
- `sources-v2/`
- `functions/`
- frontend app files

because the current Docker build context is intentionally filtered to build Cloud Run images from `backend/`.

### PDF scan

Current production PDF scan is the vendored backend runtime:

- `backend/pdf_scan_runtime/`
- `backend/run_pdf_scan_pipeline.py`
- `backend/run_pdf_scan_gpu_pipeline.py`
- `backend/services/pdf_scan/*`
- `backend/services/quellen_finder_pdf_extract_pipeline.py`

`pdf-scan/` is not the production truth and must become purely test/research.

### Sources pipeline

Current production sources pipeline is the backend-safe port:

- `backend/services/two_lane_sources/*`
- `backend/services/quellen_finder_sources_two_lane_job.py`

`sources-v2/` is not the production truth and must become purely test/research.

## What Does Not Fit Together Today

## 1. Frontend/Backend API Boundary Is Split Three Ways

This is the most important architectural inconsistency in the repo.

Current patterns:

1. Browser-direct calls from client components to FastAPI using `NEXT_PUBLIC_FASTAPI_URL`
2. Server-side direct calls from Server Actions / server helpers to FastAPI
3. Proper Next Route Handler proxy/BFF routes under `app/api/...`

### Browser-direct FastAPI callers

Confirmed examples:

- `app/components/quellen-finder/QuellenFinder.tsx`
- `app/components/pdf-scan/PdfScanWorkspace.tsx`
- `app/components/dashboard/Dashboard.tsx`
- `app/components/dashboard/KapitelWorkspace.tsx`
- `app/(account)/profil/page.tsx`

These client components read the `__session` cookie in the browser and send `Authorization: Bearer ...` directly to FastAPI.

Problems:

- Exposes backend base URL concerns to browser code
- Forces CORS to stay correct for browser-to-Cloud-Run traffic
- Duplicates auth/header/error handling
- Makes future hosting changes harder
- Makes the split more brittle because client code knows backend transport details

### Server-side direct FastAPI callers

Confirmed examples:

- `app/actions/kapitels.ts`
- `app/actions/user.ts`
- `app/actions/promptTemplates.ts`
- `app/lib/api/adminServer.ts`
- `app/lib/api/billingClient.ts`

This is less bad than browser-direct calls, but still inconsistent.

Problems:

- Still duplicates base URL handling
- Still keeps frontend code tightly coupled to backend transport
- Still mixes product domain logic with ad hoc HTTP plumbing

### Existing good pattern

Already present and should become the standard:

- `app/api/_fastapiProxy.ts`
- `app/api/admin/_fastapiProxy.ts`
- `app/api/me/route.ts`
- `app/api/projects/[projektId]/route.ts`
- several admin route handlers

### Best-practice direction

Recommended target pattern:

- Browser -> Next Route Handlers (`frontend/app/api/...`) -> FastAPI
- Server Components / Server Actions -> shared server-only backend client, or Route Handlers when that simplifies consistency
- No browser code should call FastAPI directly
- `NEXT_PUBLIC_FASTAPI_URL` should disappear from client-facing code
- A server-only env such as `BACKEND_API_URL` or `FASTAPI_BASE_URL` should replace it

Why this is the right target:

- Next’s own docs explicitly support a Backend-for-Frontend pattern using Route Handlers.
- Only `NEXT_PUBLIC_*` env vars are bundled into browser code.
- FastAPI CORS complexity drops sharply once the browser no longer calls FastAPI directly.

### Missing Route Handlers To Add

These FastAPI endpoints are still called directly and should get first-class Next route handlers:

- `/api/quellen-finder/sources-two-lane/start`
- `/api/quellen-finder/sources-two-lane/cancel`
- `/api/quellen-finder/pdf-scan`
- `/api/quellen-finder/pdf-scan/cancel`
- `/api/billing/balance`
- `/api/billing/ledger`
- `/api/billing/status`
- `/api/usage-insights/run/{run_id}`
- `/api/usage-insights/stats`
- `/api/gliederung/generate`
- `/api/gliederung/refine`
- `/api/process`
- `/api/combine-run`
- `/api/adopt-combined`
- `/api/auth/revoke`

### Required cleanup after standardization

- Remove client-side use of `NEXT_PUBLIC_FASTAPI_URL`
- Remove `NEXT_PUBLIC_API_URL`
- Move all cookie -> auth header translation into server-side code only
- Consolidate error mapping and logging in one proxy/client layer

## 2. The Vendored PDF-Scan Runtime Is Not Yet A Clean Product Package

The backend runtime works, but it still looks like a vendored research tree.

### Current issues

- `backend/pdf_scan_runtime/phase_a_lab.py` still tries to find repo-level `pdf-scan/`
- it still loads root `.env` and `pdf-scan/.env`
- it still contains notebook-era path fallbacks
- it still contains benchmark-oriented defaults and lab naming
- product wrappers import `phase_*_lab.py` modules directly
- there is still a second near-duplicate source tree in `pdf-scan/`

### Why this matters

This is the biggest risk to the “deleting `pdf-scan/` must not break the app” requirement.

Today:

- deployed Cloud Run images already exclude repo-level `pdf-scan/`
- normal production is probably safe
- local product execution is still exposed to legacy path fallback behavior

### Required cleanup

- Make vendored runtime prefer packaged backend runtime first, not repo-level `pdf-scan/`
- Remove repo-level `pdf-scan` path fallback from vendored runtime
- Remove vendored runtime `.env` loading from research folders
- Remove notebook/benchmark default modes from product entrypoints
- Rename or wrap `phase_*_lab.py` product entrypoints so the product package stops looking like notebook lab code
- Decide whether to keep the vendored implementation as the permanent runtime package or extract a cleaner internal package such as `backend/pdf_scan_runtime/engine/*`

### Non-negotiable outcome

Local and deployed product execution must both work without the repo-level `pdf-scan/` directory.

## 3. `sources-v2/` Is Already Mostly Isolated, But Still Needs Reclassification

This area is better than PDF scan.

Current truth:

- production runtime uses `backend/services/two_lane_sources/`
- deployed images exclude `sources-v2/`
- product execution does not depend on the repo-level sources notebook tree

Still messy:

- `sources-v2/` contains a second Next app (`sources-review-dashboard`)
- notebook support code still reaches to root helpers such as `notebook_openai_request_debugger.py`
- there is duplicated generic utility glue such as `cn()`

Required cleanup:

- move `sources-v2/` under `testing-scripts/sources-v2/`
- move `notebook_openai_request_debugger.py` with it
- keep `sources-review-dashboard` nested under `testing-scripts/sources-v2/`
- remove product references that only exist as provenance comments if desired

Deleting `sources-v2/` should be safe after this move.

## 4. There Is Real Stale / Legacy Backend Surface

These are strong cleanup candidates.

### Legacy admin approval / manual ops routes

Candidates:

- `/api/admin/users/approve`
- `/api/admin/approve`
- `/api/admin/quick-approve`
- `/api/admin/quick-revoke`
- `/approve` HTML form
- `/test/auth`
- likely `/api/auth/session` as well, if no external caller exists

These look like migration/manual tooling leftovers rather than current product paths.

Action:

- verify external/manual usage once
- if none exists, delete
- if some remain needed, move them behind a deliberate admin-ops surface and document them

### Legacy access-claim migration still half alive

Current code still accepts both:

- `fullAccess`
- legacy `approved`

This creates long-tail complexity in:

- backend auth
- frontend auth
- admin flows
- rules/docs/debugging

Action:

- finish the migration
- pick `fullAccess` as the only supported access claim
- remove legacy `approved` writers/readers after a one-time migration check

### Orphaned user OpenAI-key feature

This is one of the clearest stale feature clusters.

Evidence:

- backend routes still exist for `/api/user/openai-key`
- backend service methods still exist for encrypted user keys
- README still documents user-managed OpenAI keys
- current UI no longer exposes a tab/component for the feature
- `user_key_service` now returns “Eigene OpenAI-Keys werden nicht mehr unterstützt.”

Action:

- treat this feature as deprecated
- remove or archive:
  - `/api/user/openai-key` routes
  - unused encryption persistence helpers
  - `utils/crypto.py` once no remaining usage exists
  - README references to user-managed keys
- then remove `USER_KEY_ENCRYPTION_KEY` if no other feature needs it

Until then, it remains dead-weight complexity in config and docs.

### Stale/unreferenced frontend components

Confirmed and already removed:

- `app/components/auth/LoginButton.tsx`
- `app/components/auth/Navbar.tsx`
- `app/components/dashboard/KapitelWorkspaceSkeleton.tsx`
- `app/components/auth/LogoutButton.tsx`
- `components/ui/avatar.tsx`
- `components/ui/command.tsx`
- `components/ui/slider.tsx`
- `components/ui/toggle.tsx`

Action:

- keep checking for the next stale cluster, but do not reintroduce these files during the folder move

### Stale function candidate

Strong candidate:

- `functions/index.js` -> `deleteProjectPermanently`

Product behavior today archives projects instead of hard-deleting them.

Action:

- treat as stale unless some external operator flow still calls it

### Unused or questionable backend utilities

Strong candidate:

- `backend/utils/pdf_text_utils.py`

Conditional candidate:

- `backend/utils/crypto.py`

`crypto.py` should only survive if some real encrypted-user-key flow remains after cleanup.

## 5. Test / Research Code Is Mixed Into Deployable Backend Content

Current examples inside `backend/`:

- `test_openai_response.py`
- `test_cost_calculation.py`
- `verify_cost_fix.py`

These are not backend runtime code.

Current packaging problem:

- both backend Docker images copy the full `backend/` tree into the image

Action:

- keep true product support scripts in `backend/scripts/`
- move manual/verification/smoke scripts to `testing-scripts/backend/`
- keep Docker build context narrow enough that those files do not ship in production images unless explicitly intended

### Recommended classification rule

Keep in `backend/scripts/`:

- migrations
- backfills
- seeders
- operational repair scripts that are part of maintaining production state

Move to `testing-scripts/backend/`:

- smoke scripts
- cost verification
- ad hoc OpenAI probes
- exploratory/manual debugging scripts

## 6. Env Handling Is Mixed, Leaky, And Not Ready For The Split

Current state is not clean:

- root `.env` mixes frontend-public and backend-secret/provider values
- `backend/.env` also exists
- research/testing code also loads root and backend env files
- frontend server code often uses `NEXT_PUBLIC_FASTAPI_URL`
- legacy `NEXT_PUBLIC_API_URL` still exists for logout only

### Why this is bad

- public-vs-private boundaries are unclear
- testing trees can accidentally depend on production/server env files
- browser code knows backend deployment URL
- documentation cannot stay accurate

### Target env model

Frontend:

- `frontend/.env.local`
- only `NEXT_PUBLIC_*` vars intended for browser use
- server-only frontend vars allowed, but without `NEXT_PUBLIC_`

Backend:

- `backend/.env` for local only
- `backend/.env.example` committed
- runtime secrets managed in Cloud Run / Secret Manager

Testing trees:

- `testing-scripts/pdf-scan/.env.example`
- `testing-scripts/sources-v2/.env.example`
- no implicit loading from backend env files

### Recommended variable split

Frontend browser-safe:

- `NEXT_PUBLIC_FIREBASE_*`
- `NEXT_PUBLIC_FIREBASE_FUNCTIONS_REGION`
- `NEXT_PUBLIC_STRIPE_SUBSCRIPTION_PRICE_ID`
- `NEXT_PUBLIC_STRIPE_TOPUP_PRICE_ID`
- `NEXT_PUBLIC_STRIPE_PORTAL_FUNCTION_NAME`

Frontend server-only:

- `BACKEND_API_URL` or `FASTAPI_BASE_URL`

Backend:

- `OPENAI_API_KEY`
- provider keys for sources pipeline
- `ALLOWED_ORIGINS`
- `ADMIN_UIDS`
- `ADMIN_BASIC_PASSWORD`
- `GOOGLE_CLOUD_PROJECT`
- `FIREBASE_PROJECT_ID`
- storage/job config vars

### Live secret/config inconsistency to fix

Observed live on Cloud Run:

- `ADMIN_BASIC_PASSWORD` is still present as a plain environment variable on the service
- the GitHub Actions workflow does not currently manage it through Secret Manager

Action:

- move `ADMIN_BASIC_PASSWORD` to Secret Manager
- explicitly remove the plain env var from the Cloud Run service during rollout

## 7. Deploy / Build Tooling Is Hard-Coded To The Current Layout

This must be updated deliberately; otherwise the split will break deploys immediately.

### GitHub Actions

Current workflow:

- `.github/workflows/deploy-backend.yml`

Hard-coded assumptions:

- Docker build context is repo root
- backend Dockerfiles live in `backend/`
- deployed service/job names are injected from root workflow env

Required changes:

- move Dockerfiles to `backend/`
- change workflow file paths from `backend/Dockerfile*` to `backend/Dockerfile*`
- decide whether Docker build context should become `backend/` instead of repo root
- if context becomes `backend/`, rework `.dockerignore` accordingly

### Docker ignore strategy

Current root `.dockerignore` excludes frontend, `pdf-scan`, `sources-v2`, `functions`, docs, etc.

That only makes sense because the build context is currently repo root.

Recommended target:

- use `backend/` as Docker build context
- keep a backend-local `.dockerignore`
- stop relying on a repo-root `.dockerignore` to simulate backend-only builds

### Vercel

User decision: Vercel should point directly to `frontend/`.

Required changes:

- change Vercel Root Directory to `frontend/`
- ensure frontend install/build commands run inside `frontend/`
- move frontend env vars to the `frontend/` project configuration
- remove any remaining assumptions that the Next app lives at repo root

### Firebase deploy reproducibility

Current repo gap:

- no committed `firebase.json`
- no committed `.firebaserc`
- no committed `firestore.indexes.json`
- no committed Firebase deploy workflow

If Firebase rules/functions/extensions remain part of the product story, this is not acceptable long-term.

Action:

- add `firebase.json`
- add `.firebaserc`
- export and commit `firestore.indexes.json`
- add explicit deploy instructions or workflow for rules/indexes/functions as applicable

## 8. README And Documentation Drift Is Already Significant

The repo already contains meaningful doc drift.

Examples:

- README still documents `NEXT_PUBLIC_API_URL`
- README still advertises user OpenAI key management
- README still references `users/{uid}/secrets/openai`
- README still assumes the root frontend layout
- README only partially explains the two-project deployment reality
- README implies Firebase setup but deploy config is not committed

Implication:

- the split should not start with README rewrites
- it should start with architecture cleanup and precise inventory
- after the refactor, all READMEs should be rewritten from scratch

## 9. `functions/` Needs A Deliberate Decision, Not A Blind Move

Current status:

- repo code exists for custom Firebase Functions
- live Firebase project currently shows Stripe extension functions, not the repo custom functions
- frontend product usage is clearly tied to the Stripe extension
- repo custom functions therefore look unresolved: legacy, undeployed, or deployed elsewhere

Important additional finding from deeper audit:

- `functions/index.js` still contains the clearest code path that auto-sets `users/{uid}.fullAccess` after Stripe payment/subscription events
- FastAPI now mirrors billing ledger/balance state from Stripe extension collections, but I did not find an equivalent automatic `fullAccess` grant path there
- this means `functions/` is likely legacy overall, but may still encode one business-critical behavior that must be replaced or explicitly proven unused before retirement

### Recommendation

Do **not** move `functions/` into `backend/`.

Choose one of these paths explicitly:

### Option A: Preferred long-term

Retire custom Firebase Functions and move remaining billing activation/webhook logic into a documented backend/billing architecture.

That likely means:

- Stripe webhooks handled in a deliberate backend or webhook service
- access activation logic moved out of ad hoc Firebase Functions code
- `functions/` deleted once behavior is fully replaced

### Option B: Safer short-term

Keep `functions/` at repo root as a temporary legacy/integration package.

If doing this:

- add Firebase deploy config
- verify whether the package is actually still deployed anywhere
- document its project/region
- remove clearly stale exports such as `deleteProjectPermanently`

## 10. Recommended Folder Ownership After The Split

### Move into `frontend/`

- `app/`
- `components/`
- `lib/`
- `public/`
- `package.json`
- `package-lock.json`
- `tsconfig.json`
- `next.config.ts`
- `proxy.ts`
- `eslint.config.mjs`
- `postcss.config.mjs`

Do not move:

- `.next/`
- `next-env.d.ts`

Those are generated/local.

### Move into `backend/`

Move the **contents** of current `backend/` to `backend/`, not a nested `backend/backend/`, because the user wants a clean two-root product structure.

This includes:

- `main.py`
- `middleware/`
- `models/`
- `services/`
- `utils/`
- `pdf_scan_runtime/`
- `scripts/`
- `Dockerfile`
- `Dockerfile.gpu`
- `requirements.txt`
- `requirements-gpu.txt`
- backend README/docs that are still valid

### Move into `testing-scripts/pdf-scan/`

Move the entire repo-level `pdf-scan/` tree there, then clean it internally.

Recommended internal cleanup later:

- `notebooks/`
- `benchmark/`
- `research/`
- `tools/`
- `runs/` gitignored
- `paper-dump/` gitignored

### Move into `testing-scripts/sources-v2/`

Move:

- `sources-v2/`
- `sources-review-dashboard/` nested with it
- `notebook_openai_request_debugger.py` into this area

### Keep at repo root

- `.github/`
- `firestore.rules`
- `storage.rules`
- `functions/` temporarily
- future `firebase.json`
- future `.firebaserc`
- future `firestore.indexes.json`
- root README and docs

## 11. Concrete Cleanup Backlog Before Or During The Move

This is the actual implementation backlog.

### API boundary cleanup

1. Add missing Next Route Handlers for all direct FastAPI browser paths.
2. Migrate client components to same-origin `/api/...` only.
3. Remove client-side cookie-to-auth-header logic.
4. Replace `NEXT_PUBLIC_FASTAPI_URL` with a server-only backend URL env.
5. Remove `NEXT_PUBLIC_API_URL`.
6. Consolidate repeated prompt/admin proxy logic onto shared proxy helpers.

### Backend cleanup

1. Remove product dependence on repo-level `pdf-scan/`.
2. Remove research env/path fallback from vendored PDF-scan runtime.
3. Decide whether to rename/clean the `phase_*_lab.py` naming in product runtime.
4. Move non-runtime test scripts out of backend root.
5. Delete legacy admin/manual routes once validated unused.
6. Finish the `approved` -> `fullAccess` migration and remove legacy claim handling.
7. Remove the orphaned user OpenAI-key feature.

### Testing/research cleanup

1. Move `pdf-scan/` under `testing-scripts/`.
2. Move `sources-v2/` under `testing-scripts/`.
3. Move notebook-only helpers there too.
4. Keep testing trees self-contained and stop implicit env loading from backend.

### Docs/config cleanup

1. Commit Firebase deploy config if Firebase remains in scope.
2. Export and commit Firestore indexes.
3. Rework root README only after code/infra changes are real.

## 12. Phase-By-Phase Implementation Plan

## Phase 0: Freeze And Inventory

Goal:

- finish the inventory before any move

Tasks:

- create this master plan
- capture live infra/resource truth
- list stale candidates
- identify all route/proxy gaps

Exit criteria:

- no major unknown remains about runtime ownership

## Phase 1: Standardize The API Boundary Before Moving Folders

Goal:

- stop browser code from knowing FastAPI transport details

Tasks:

- add missing `frontend/app/api/...` route handlers
- migrate browser code off direct FastAPI URLs
- keep auth token handling server-side only
- introduce one server-only backend base URL env for frontend runtime
- remove `NEXT_PUBLIC_API_URL`

Status update:

- mostly implemented already in commit `6af05c9`
- redundant `__session` gating in `Dashboard.tsx` has been removed in commit `3b8c85c`
- remaining cleanup is mainly:
  - keep client-side cookies limited to UI state/persistence only
  - rewrite setup docs/env docs away from the old public-backend-URL assumptions
  - decide whether server-side direct FastAPI callers outside `app/api` stay as an intentional server integration layer or get further consolidated

Exit criteria:

- no client component calls FastAPI directly
- browser code no longer reads `NEXT_PUBLIC_FASTAPI_URL`

## Phase 2: Isolate Product Runtime From Research Trees

Goal:

- guarantee product runtime survives deleting test folders

Tasks:

- remove vendored PDF-scan fallback to repo-level `pdf-scan/`
- stop vendored runtime from loading research env files
- remove notebook/benchmark defaults from product entrypoints
- confirm sources runtime uses only backend ported package

Status update:

- the highest-priority blocker in vendored PDF-scan runtime has already been fixed in commit `1cc55ae`
- `backend/pdf_scan_runtime/phase_a_lab.py` no longer searches for a repo-level `pdf-scan/` directory and now resolves its runtime roots from the vendored backend package itself
- vendored phase CLI defaults have been hardened in commit `3b8c85c`: `input_mode` now defaults to `manual` and `suite_manifest` defaults to empty instead of pointing at benchmark assets
- `sources-v2/` appears technically isolated from the production backend already; remaining references are provenance comments, not runtime imports
- remaining work in this phase is mostly structural cleanup: deciding whether some lab-oriented phase entrypoints should stay vendored in `backend/` at all or later move to `testing-scripts/`

Exit criteria:

- backend unit/smoke paths work without repo-level `pdf-scan/`
- backend works without repo-level `sources-v2/`

## Phase 3: Backend Cleanup

Goal:

- make `backend/` a real product runtime, not a mixed lab tree

Tasks:

- move manual test files out
- prune dead routes
- remove user OpenAI-key dead paths
- simplify access claim handling
- prune unused utilities

Exit criteria:

- backend tree contains runtime code, operational scripts, and nothing obviously stale

## Phase 4: Physical Folder Move

Goal:

- perform the actual split only after behavior is already cleaner

Tasks:

- move root Next app into `frontend/`
- move current `backend/` contents into `backend/`
- move `pdf-scan/` and `sources-v2/` into `testing-scripts/`
- update imports, path aliases, Dockerfiles, workflow paths, docs, ignore files

Exit criteria:

- local frontend and backend both boot from new roots

## Phase 5: Deploy / Infra Refactor

Goal:

- make deployment match the new layout and the real two-project architecture

Tasks:

- update GitHub Actions workflow
- switch Docker context to `backend/`
- update Vercel Root Directory to `frontend/`
- migrate/clean service env vars and secrets
- add Firebase config/index files if kept

Exit criteria:

- frontend deploys from `frontend/`
- backend deploys from `backend/`
- Firebase rules/indexes/functions story is documented and reproducible

## Phase 6: Stale Code Removal

Goal:

- delete or quarantine code that no longer serves the product

Priority order:

1. direct browser FastAPI plumbing
2. `NEXT_PUBLIC_API_URL`
3. user OpenAI-key feature
4. legacy access claim support
5. unused components/helpers
6. stale functions/routes

## Phase 7: README Rewrite

Only after all previous phases are real.

Then create:

- root architecture README
- `frontend/README.md`
- `backend/README.md`
- `testing-scripts/pdf-scan/README.md`
- `testing-scripts/sources-v2/README.md`
- `functions/README.md` if it still exists

## 13. External / Manual Changes Outside The Code

These are the changes you will need to make outside pure code edits.

### Vercel

- set project Root Directory to `frontend/`
- move frontend env vars into that project
- ensure build/install commands use `frontend/package.json`
- verify preview/prod both point to the moved app

### Cloud Run / GitHub Actions

- update workflow file paths to `backend/Dockerfile` and `backend/Dockerfile.gpu`
- preferably build with `backend/` as Docker context
- re-test Cloud Run deploy in:
  - service `instantpaper-api`
  - job `instantpaper-two-lane-sources`
  - job `instantpaper-pdf-scan-cpu`
  - job `instantpaper-pdf-scan-gpu`

### Secrets / config

- move `ADMIN_BASIC_PASSWORD` to Secret Manager if it is still needed
- remove plaintext `ADMIN_BASIC_PASSWORD` env from live service
- decide whether `USER_KEY_ENCRYPTION_KEY` still needs to exist after user-key cleanup
- audit which vars belong to `instantpaper` vs `instantpaper-e80e5`

### Firebase

If Firebase remains part of the deployment story:

- add `firebase.json`
- add `.firebaserc`
- export and commit `firestore.indexes.json`
- document the Stripe extension dependency and region
- document whether `functions/` is still used at all

### IAM / project boundaries

Document clearly:

- Cloud Run project: `instantpaper`
- Firebase project: `instantpaper-e80e5`
- which deploy commands run against which project
- which secrets live in which project
- which service accounts need cross-project access

This must be explicit in later docs.

## 14. Validation Checklist

Use this after each major phase.

### Frontend validation

- `frontend` dev server boots
- auth login/logout still works
- profile page works
- billing page works
- sources-two-lane start/cancel works
- PDF scan start/cancel works
- admin pages work

### Backend validation

- `backend` boots locally
- Cloud Run service deploy succeeds
- two-lane job launch succeeds
- PDF scan CPU job launch succeeds
- PDF scan GPU handoff succeeds
- deleting/moving test trees does not break runtime

### Infra validation

- Vercel deploys from `frontend/`
- GitHub Action deploys from `backend/`
- Firestore queries still satisfy index requirements
- Stripe portal still works
- checkout session creation still works

### Delete-safety validation

Before finalizing, verify:

- temporarily remove or rename repo-level `pdf-scan/`
- temporarily remove or rename repo-level `sources-v2/`
- backend and frontend product flows still work

That is the hard acceptance test for this cleanup.

## 15. Recommended Order Of Actual Deletions

Delete only after replacement/validation.

### Safe early deletes

- `NEXT_PUBLIC_API_URL`
- duplicated prompt proxy route logic
- unreferenced frontend components after one final grep

### Delete after feature confirmation

- legacy admin approval/manual routes
- `/test/auth`
- `/api/auth/session`
- `/api/user/openai-key`
- encrypted-user-key helpers
- `functions/deleteProjectPermanently`

### Delete only after runtime isolation work

- any repo-level `pdf-scan` assumptions from backend runtime
- any notebook helper still imported from product/runtime paths

## 16. Official Best-Practice References Used

These informed the architecture recommendation:

- Next.js Backend-for-Frontend guide:
  - https://nextjs.org/docs/app/guides/backend-for-frontend
- Next.js environment variables:
  - https://nextjs.org/docs/app/guides/environment-variables
- Next.js Route Handlers:
  - https://nextjs.org/docs/app/building-your-application/routing/route-handlers
- Vercel monorepo Root Directory / workspace behavior:
  - https://vercel.com/docs/monorepos
- FastAPI CORS:
  - https://fastapi.tiangolo.com/tutorial/cors/

Key conclusions applied here:

- only `NEXT_PUBLIC_*` vars belong in browser bundles
- Route Handlers are the right place for BFF/proxy logic
- Vercel Root Directory should match the actual app root in a split repo
- if browser credentials are involved, FastAPI CORS needs explicit origins; removing browser-direct FastAPI calls reduces that complexity materially

## Final Recommendation Summary

The refactor should **not** begin with moving folders.

It should begin with:

1. standardizing the frontend/backend boundary
2. isolating backend runtime from research trees
3. pruning stale legacy surface

Only then should the physical move happen.

If you do it in that order, the later folder move becomes a mechanical consequence of an already cleaner architecture, instead of a risky repository shuffle.

