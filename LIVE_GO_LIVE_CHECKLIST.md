# InstantPaper Go-Live Checklist

Verified against the current repo and live infrastructure on **March 27, 2026**.

This checklist is written for the current InstantPaper setup after the `frontend/` and `backend/` split.

## Current Verified State

### Repository

- product frontend lives in `frontend/`
- product backend lives in `backend/`
- non-production research code lives in `testing-scripts/`
- backend deploy workflow is [`.github/workflows/deploy-backend.yml`](.github/workflows/deploy-backend.yml)

### Live backend

- live API URL: `https://instantpaper-api-4dyfq723wq-ey.a.run.app`
- verified health response on 2026-03-27:

```json
{
  "status": "healthy",
  "version": "1.0.0",
  "firebase": "connected",
  "openai": "connected",
  "adminApprovalConfigured": true,
  "firebaseClockSkewSeconds": 5
}
```

### Live Cloud Run resources

- service: `instantpaper-api`
- jobs in `europe-west3`:
  - `instantpaper-two-lane-sources`
  - `instantpaper-pdf-scan-cpu`
- job in `europe-west1`:
  - `instantpaper-pdf-scan-gpu`

### Live Vercel project

Current verified Vercel project state:

- project: `instantpaper`
- Root Directory: `.`
- framework: `Next.js`

This must be changed. The current repo structure expects Vercel to build from `frontend/`.

## Goal

After this checklist is complete:

- Vercel builds from `frontend/`
- Vercel route handlers can reach the live FastAPI backend
- GitHub Actions deploys `backend/` to Cloud Run
- Firebase login works on the live domain
- the split repo layout is actually reflected in production

## Step 1. Push The Latest Branch

If your current work is still only local, push it first:

```bash
git push origin refactor
```

Then merge `refactor` into `master`.

If you use GitHub UI:

1. open the repository on GitHub
2. create a pull request from `refactor` into `master`
3. review it
4. merge it

If you merge locally:

```bash
git checkout master
git pull origin master
git merge refactor
git push origin master
```

Important:

- the backend deploy workflow triggers on pushes to `master`
- your remote default branch is already verified as `master`

## Step 2. Update Vercel Root Directory

In Vercel:

1. open project `instantpaper`
2. go to `Settings`
3. go to `General`
4. find `Root Directory`
5. change it from `.` to `frontend`
6. save

This is currently the single most important missing live change.

If you skip this, Vercel will keep building from the wrong directory.

## Step 3. Fix Vercel Environment Variables

Go to:

`Vercel -> Project -> Settings -> Environment Variables`

### Keep these variables

These are already expected by the current frontend code:

- `NEXT_PUBLIC_FIREBASE_API_KEY`
- `NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN`
- `NEXT_PUBLIC_FIREBASE_PROJECT_ID`
- `NEXT_PUBLIC_FIREBASE_STORAGE_BUCKET`
- `NEXT_PUBLIC_FIREBASE_MESSAGING_SENDER_ID`
- `NEXT_PUBLIC_FIREBASE_APP_ID`
- `NEXT_PUBLIC_FIREBASE_MEASUREMENT_ID`
- `NEXT_PUBLIC_FIREBASE_FUNCTIONS_REGION`

### Add this variable

Add this for all environments you use:

- `FASTAPI_BASE_URL`

Production value:

```env
FASTAPI_BASE_URL=https://instantpaper-api-4dyfq723wq-ey.a.run.app
```

This is required by the current server-side Next proxy layer in `frontend/app/lib/server/fastapi.ts`.

### Optional but recommended

If you want the frontend to be fully explicit instead of falling back to hardcoded defaults, also set:

- `NEXT_PUBLIC_STRIPE_SUBSCRIPTION_PRICE_ID`
- `NEXT_PUBLIC_STRIPE_TOPUP_PRICE_ID`
- `NEXT_PUBLIC_STRIPE_PORTAL_FUNCTION_NAME`

### Remove stale variables

These are no longer the correct source of truth for the current frontend:

- `NEXT_PUBLIC_FASTAPI_URL`
- `COOKIE_SECRET`
- `USE_SECURE_COOKIES`

They are not used by the current frontend runtime path anymore.

## Step 4. Redeploy Vercel

After Root Directory and environment variables are fixed:

1. trigger a new production deployment in Vercel
2. wait for the build to complete
3. confirm the deployment uses `frontend/` as the build root

Recommended quick check after deploy:

- open the live site
- confirm the app renders at all
- confirm route handlers work and do not return backend connectivity errors

## Step 5. Verify Firebase Authorized Domains

Open Firebase Console for project `instantpaper-e80e5`.

Go to:

`Authentication -> Settings -> Authorized domains`

Make sure all live domains are present, for example:

- your Vercel production domain
- your custom domain
- your `www` variant if you use one

If a live domain is missing here, Google login will break even if Vercel and Cloud Run are correct.

## Step 6. Verify GitHub Actions Secrets

Open:

`GitHub -> Repository -> Settings -> Secrets and variables -> Actions`

Make sure these repository secrets exist and are correct:

- `GCP_PROJECT_ID`
- `FIREBASE_PROJECT_ID`
- `GCP_WIF_PROVIDER`
- `GCP_WIF_SERVICE_ACCOUNT`

Expected values conceptually:

- `GCP_PROJECT_ID=instantpaper`
- `FIREBASE_PROJECT_ID=instantpaper-e80e5`

If these are wrong, `deploy-backend.yml` will either fail or deploy against the wrong project.

## Step 7. Run The Backend Deploy

Once the merged code is on `master`, the backend deploy should trigger automatically.

You can also trigger it manually:

1. open GitHub Actions
2. select `Deploy Backend and Workers`
3. use `Run workflow`

Then verify:

- the workflow builds `backend/Dockerfile`
- the workflow builds `backend/Dockerfile.gpu`
- the workflow deploys `instantpaper-api`
- the workflow updates or creates:
  - `instantpaper-two-lane-sources`
  - `instantpaper-pdf-scan-cpu`
  - `instantpaper-pdf-scan-gpu`

## Step 8. Verify Cloud Run Runtime Config

The live backend already has the major runtime variables wired correctly, but you should verify them after deploy.

### Service

Cloud Run service:

- `instantpaper-api`

Should point to:

- `GOOGLE_CLOUD_PROJECT=instantpaper`
- `FIREBASE_PROJECT_ID=instantpaper-e80e5`
- `FIREBASE_STORAGE_BUCKET=instantpaper-e80e5.firebasestorage.app`
- `TWO_LANE_SOURCES_EXECUTION_BACKEND=cloud_run_job`
- `PDF_SCAN_EXECUTION_BACKEND=cloud_run_split_jobs`

### Jobs

Cloud Run jobs should still reference:

- correct project IDs
- correct storage bucket
- correct service account
- correct OpenAI and data-provider secrets

## Step 9. Verify Secret Manager / Runtime Secrets

Current backend deploy expects these runtime secrets to exist in GCP:

- `OPENAI_API_KEY`
- `ALLOWED_ORIGINS`
- `USER_KEY_ENCRYPTION_KEY`
- `ADMIN_UIDS`
- `OPENALEX_API_KEY`
- `SEMANTICSCHOLAR_API_KEY`

After deploy, verify that these still exist and are readable by the runtime service accounts.

If one of these is missing, the deploy may succeed but runtime behavior will partially fail.

## Step 10. Fix `ALLOWED_ORIGINS`

This one is easy to miss.

The backend reads `ALLOWED_ORIGINS` from Secret Manager, not from the repo.

That secret should include at least:

- `http://localhost:3000`
- your Vercel production domain
- your custom domain
- your `www` domain if used

Example shape:

```text
http://localhost:3000,https://your-vercel-domain.vercel.app,https://instantpaper.de,https://www.instantpaper.de
```

If your live frontend origin is missing here, browser requests to FastAPI-backed features can fail with CORS issues.

## Step 11. Perform Production Smoke Tests

Do these in the live app after Vercel and backend deploy are both complete.

### Auth

- open the live frontend
- log in with Google
- verify no authorized-domain error appears
- verify access gate behaves correctly

### Main app

- open dashboard
- open project list
- open a project
- open Quellen manager

### Processing

- run a small normal processing task
- verify `/api/process` path works end-to-end
- verify results appear in the UI

### Quellen-Finder

- start a two-lane sources search
- start a PDF scan
- verify both queue successfully

### Billing

- open profile billing tab
- verify balance/status load
- verify checkout session can be created
- verify customer portal opens

### Admin

- open admin UI with an allowed UID
- verify user list loads
- verify cost/admin endpoints respond

## Step 12. Optional But Strongly Recommended Hardening

These are not strict blockers for first go-live, but they should be done soon.

### Move `ADMIN_BASIC_PASSWORD` into Secret Manager

Current verified state on 2026-03-27:

- `ADMIN_BASIC_PASSWORD` is currently present directly as a normal Cloud Run env var
- it is not yet managed as a bound secret by the deploy workflow

Recommended follow-up:

1. create a Secret Manager secret for `ADMIN_BASIC_PASSWORD`
2. update `deploy-backend.yml` to bind it like the other secrets
3. remove the plain env var from the Cloud Run service

### Commit Firebase Infra Config

The repo still does not contain:

- `firebase.json`
- `.firebaserc`
- `firestore.indexes.json`

Current reality:

- live Firestore indexes do exist
- but the Firebase infra is not yet fully reproducible from the repo

Recommended follow-up:

1. export or recreate the Firebase config files
2. commit them
3. make rules and index deploys reproducible

### Resolve Legacy `functions/`

`functions/` is currently a legacy package and not part of the main backend deploy path.

Recommended follow-up:

1. decide whether the remaining Stripe-triggered activation logic is still needed
2. migrate or retire it deliberately
3. do not silently leave it undocumented

## Fastest Possible Go-Live Path

If you want the shortest correct path, do these first:

1. push `refactor`
2. merge into `master`
3. set Vercel Root Directory to `frontend`
4. add `FASTAPI_BASE_URL=https://instantpaper-api-4dyfq723wq-ey.a.run.app`
5. remove stale Vercel env vars
6. verify Firebase Authorized Domains
7. redeploy Vercel
8. let GitHub Actions deploy backend from `master`
9. run smoke tests

## Final Completion Check

You are effectively live when all of these are true:

- Vercel builds from `frontend/`
- frontend has `FASTAPI_BASE_URL`
- backend deploy succeeds on `master`
- Firebase login works on the live domain
- dashboard loads
- processing works
- Quellen-Finder works
- billing works
- admin works

If you want, the next step can be a second file that is even more operational and shorter, for example a one-page `GO_LIVE_RUNBOOK.md` with only the exact clicks and commands in execution order.
