# InstantPaper

InstantPaper is a full-stack writing and source-processing system for academic workflows.

This repository is organized as a product monorepo:

- `frontend/` contains the production Next.js application
- `backend/` contains the production FastAPI API and Cloud Run worker runtime
- `testing-scripts/` contains local research, experiments, benchmarks, and internal tooling

The product is designed so that `frontend/` and `backend/` are sufficient to run the application. `testing-scripts/` is intentionally out of the production runtime path.

## Repo Status

Current architecture decisions:

- Production frontend lives in `frontend/`
- Production backend lives in `backend/`
- `testing-scripts/pdf-scan/` and `testing-scripts/sources-v2/` are non-production research trees
- `functions/` is a legacy Firebase Functions package and is not part of the current backend deploy workflow

## High-Level Architecture

```text
Browser
  -> frontend/ (Next.js App Router on Vercel)
     -> Firebase Auth / Firestore / Storage
     -> Next route handlers as BFF
        -> backend/ (FastAPI on Cloud Run)
           -> OpenAI
           -> Firestore / Storage writes
           -> Cloud Run Jobs for heavy async work
```

Billing is split slightly differently:

- checkout session creation happens through Firestore documents consumed by the Firebase Stripe extension
- customer portal access uses the Stripe extension callable function
- backend mirrors billing state and credits from Firebase/Stripe data

## Project Boundaries

This repo currently spans two cloud projects:

- `instantpaper`
  - main GCP project
  - Cloud Run service and Cloud Run Jobs
  - Artifact Registry and workload identity for backend deploys
- `instantpaper-e80e5`
  - Firebase project
  - Firebase Auth, Firestore, Storage
  - Firebase Stripe extension

That split matters when configuring secrets, deployment access, and local credentials.

## Repository Layout

```text
.
|- frontend/                 Next.js product app
|- backend/                  FastAPI API, workers, Dockerfiles
|- testing-scripts/          Non-production research and validation trees
|  |- pdf-scan/
|  `- sources-v2/
|- functions/                Legacy Firebase Functions package
|- .github/workflows/        CI/CD, including Cloud Run deploy workflow
|- firestore.rules           Firestore rules
|- storage.rules             Storage rules
`- FRONTEND_BACKEND_SPLIT_AND_CLEANUP_MASTER_PLAN.md
```

## Quickstart

### 1. Frontend environment

Copy the frontend template and fill in your Firebase web app values:

```bash
cd frontend
cp .env.local.example .env.local
```

Required values live in [frontend/.env.local.example](frontend/.env.local.example):

- Firebase web config
- `FASTAPI_BASE_URL`
- Stripe price IDs and portal function override if needed

### 2. Backend environment

Copy the backend template and fill in your runtime secrets:

```bash
cd backend
cp .env.example .env
```

Required baseline values live in [backend/.env.example](backend/.env.example):

- Firebase Admin credentials or ADC-compatible setup
- `OPENAI_API_KEY`
- admin access settings
- local execution backend settings

### 3. Install dependencies

Frontend:

```bash
cd frontend
npm install
```

Backend:

```bash
cd backend
pip install -r requirements.txt
```

If you use the local Conda environment described during development:

```bash
conda activate instantpaper
```

### 4. Run the backend

```bash
cd backend
python main.py
```

The API defaults to `http://localhost:8000`.

### 5. Run the frontend

```bash
cd frontend
npm run dev
```

The web app defaults to `http://localhost:3000`.

## Where To Read Next

- Frontend setup and architecture: [frontend/README.md](frontend/README.md)
- Backend setup, env vars, workers, and deploys: [backend/README.md](backend/README.md)
- Ongoing migration and cleanup notes: [FRONTEND_BACKEND_SPLIT_AND_CLEANUP_MASTER_PLAN.md](FRONTEND_BACKEND_SPLIT_AND_CLEANUP_MASTER_PLAN.md)

## Runtime Ownership

### `frontend/`

Owns:

- UI and route structure
- Firebase web auth flow
- direct client Firestore and Storage interactions where appropriate
- Next.js route handlers acting as a backend-for-frontend layer for FastAPI

### `backend/`

Owns:

- FastAPI endpoints
- Firebase Admin access
- OpenAI calls
- background orchestration for two-lane sources and PDF scan
- worker entrypoints and Docker images for Cloud Run

### `testing-scripts/`

Owns:

- experiments
- benchmarks
- manual evaluation artifacts
- internal review/dashboard tooling

It should not be required for the production app to boot or serve requests.

## Deployment Overview

### Frontend

- expected platform: Vercel
- required Vercel setting: Root Directory must be `frontend/`
- server-side route handlers must receive `FASTAPI_BASE_URL`

### Backend

- deploy workflow: [deploy-backend.yml](.github/workflows/deploy-backend.yml)
- target platform: Cloud Run
- production API service name: `instantpaper-api`
- production jobs:
  - `instantpaper-two-lane-sources`
  - `instantpaper-pdf-scan-cpu`
  - `instantpaper-pdf-scan-gpu`

### Firebase

The repo contains:

- [firestore.rules](firestore.rules)
- [storage.rules](storage.rules)

The repo currently does not act as a full Firebase CLI project checkout. In particular, `firebase.json` and `.firebaserc` are not part of the committed product setup right now, so Firebase deploy steps are still partly an external/manual concern.

## Important Operational Notes

- Product env files belong in `frontend/.env.local` and `backend/.env`.
- Do not treat the repo-root `.env` as the product source of truth.
- `functions/` is legacy. Do not add new product features there unless you deliberately choose to revive Firebase Functions as a supported production surface.
- `testing-scripts/` can be large and noisy; it is intentionally excluded from Vercel and Docker deploy contexts.

## Common Development Tasks

Start frontend:

```bash
cd frontend
npm run dev
```

Build frontend:

```bash
cd frontend
npm run build
```

Run backend:

```bash
cd backend
python main.py
```

Compile-check backend:

```bash
python -m compileall backend
```

## Known Transitional Items

- the backend still accepts the legacy Firebase claim `approved` in addition to `fullAccess`
- `functions/` still contains unresolved legacy billing/activation logic, but is not in the main backend deploy path
- Firebase infra config is not yet fully codified inside the repo

Those are known migration leftovers, not the intended long-term architecture.
