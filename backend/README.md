# InstantPaper Backend

This directory contains the production FastAPI backend and worker runtime for InstantPaper.

It is the server-side execution layer for:

- AI processing
- Firebase Admin operations
- billing state mirroring
- export generation
- Quellen-Finder jobs
- PDF scan orchestration

## Scope

`backend/` owns:

- the FastAPI application in [main.py](main.py)
- reusable business logic in `services/`
- auth middleware in `middleware/`
- request/response models in `models/`
- runtime config and utilities in `utils/`
- the vendored production PDF scan runtime in `pdf_scan_runtime/`
- local and Cloud Run worker entrypoints in the root of `backend/`
- Dockerfiles for CPU and GPU worker images

It is intended to be production-sufficient without `testing-scripts/`.

## Runtime Topology

Production backend surfaces:

- Cloud Run service: `instantpaper-api`
- Cloud Run Job: `instantpaper-two-lane-sources`
- Cloud Run Job: `instantpaper-pdf-scan-cpu`
- Cloud Run Job: `instantpaper-pdf-scan-gpu`

Deploy workflow:

- [deploy-backend.yml](../.github/workflows/deploy-backend.yml)

Docker images:

- [Dockerfile](Dockerfile)
- [Dockerfile.gpu](Dockerfile.gpu)

## Requirements

- Python 3.11 recommended
- pip
- access to Firebase Admin credentials or ADC
- OpenAI API key

The local development environment has often been run from the Conda environment named `instantpaper`, but a normal virtual environment also works.

## Install

### Option A: Conda

```bash
conda activate instantpaper
cd backend
pip install -r requirements.txt
```

### Option B: venv

```bash
cd backend
python -m venv .venv
.venv\\Scripts\\activate
pip install -r requirements.txt
```

## Environment Variables

Copy the template:

```bash
cp .env.example .env
```

The template in [backend/.env.example](.env.example) contains the minimum local surface:

```env
FIREBASE_PROJECT_ID=
GOOGLE_CLOUD_PROJECT=
FIREBASE_CLIENT_EMAIL=
FIREBASE_PRIVATE_KEY="-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----\n"
FIREBASE_STORAGE_BUCKET=

OPENAI_API_KEY=
OPENALEX_API_KEY=
SEMANTICSCHOLAR_API_KEY=
USER_KEY_ENCRYPTION_KEY=

PORT=8000
ALLOWED_ORIGINS=http://localhost:3000
DEBUG=true

ADMIN_BASIC_USER=admin
ADMIN_BASIC_PASSWORD=
ADMIN_UIDS=

TWO_LANE_SOURCES_EXECUTION_BACKEND=local_background
PDF_SCAN_EXECUTION_BACKEND=local_split_jobs
```

### Required for a basic local API

- `FIREBASE_PROJECT_ID`
- `OPENAI_API_KEY`
- either:
  - `FIREBASE_PRIVATE_KEY` and `FIREBASE_CLIENT_EMAIL`
  - or `GOOGLE_APPLICATION_CREDENTIALS` pointing to valid ADC credentials

### Commonly important optional settings

- `GOOGLE_CLOUD_PROJECT`
  - explicit GCP project override
- `FIREBASE_STORAGE_BUCKET`
  - bucket override, defaults from project ID when omitted
- `ALLOWED_ORIGINS`
  - comma-separated CORS allowlist
- `ADMIN_BASIC_USER` / `ADMIN_BASIC_PASSWORD`
  - protects the `/approve` HTML admin access surface
- `ADMIN_UIDS`
  - Firebase UID allowlist for `/api/admin/*`
- `OPENALEX_API_KEY` / `SEMANTICSCHOLAR_API_KEY`
  - used by two-lane sources workflows
- `USER_KEY_ENCRYPTION_KEY`
  - used by per-user key encryption features

More advanced runtime options are defined in [utils/config.py](utils/config.py).

Important behavior from config:

- `backend/.env` is loaded regardless of working directory
- Cloud Run automatically flips execution defaults toward job-based backends
- local development defaults to local-background or local-split-job execution

## Run Locally

Start the API:

```bash
cd backend
python main.py
```

Alternative:

```bash
cd backend
python -m uvicorn main:app --reload --port 8000
```

By default the app listens on `http://localhost:8000`.

## Main Endpoint Families

Useful endpoints:

- `GET /health`
- `GET /api/billing/status`
- `POST /api/process`
- `POST /api/quellen-finder/sources-two-lane/start`
- `POST /api/quellen-finder/pdf-scan`
- `POST /api/quellen-finder/pdf-extract`
- `GET /api/admin/users`
- `GET /approve`

The frontend normally reaches these through Next route handlers, not by direct browser-to-FastAPI calls.

## Directory Guide

```text
backend/
|- main.py                  FastAPI entrypoint
|- middleware/              auth and request guards
|- models/                  request/response models
|- services/                business logic and external integrations
|- utils/                   config, logging, helpers
|- pdf_scan_runtime/        production PDF scan runtime
|- scripts/                 maintenance and support scripts
|- Dockerfile               CPU/API image
`- Dockerfile.gpu           GPU worker image
```

Important runtime entrypoints:

- [run_two_lane_job.py](run_two_lane_job.py)
- [run_pdf_scan_cpu_job.py](run_pdf_scan_cpu_job.py)
- [run_pdf_scan_gpu_job.py](run_pdf_scan_gpu_job.py)
- [run_pdf_scan_pipeline.py](run_pdf_scan_pipeline.py)
- [run_pdf_scan_gpu_pipeline.py](run_pdf_scan_gpu_pipeline.py)

## Key Services

Representative service modules:

- `services/firebase_service.py`
  - Firebase Admin init, session cookies, custom claims, admin mutations
- `services/credits_service.py`
  - billing ledger and Stripe-derived credit synchronization
- `services/prompt_service.py`
  - prompt defaults and system prompt templates
- `services/export_service.py`
  - DOCX export generation
- `services/cloud_run_job_launcher.py`
  - Cloud Run Job orchestration
- `services/two_lane_sources/`
  - production two-lane sources runtime
- `services/pdf_scan/`
  - production PDF scan orchestration layer

## Local Verification

Health check:

```bash
curl http://localhost:8000/health
```

Compile-check:

```bash
python -m compileall backend
```

Prompt docs regeneration:

```bash
cd backend
python scripts/generate_prompts_md.py
```

## Deployment

The backend deploy workflow:

- authenticates to the main GCP project with Workload Identity
- builds a CPU/API image from [backend/Dockerfile](Dockerfile)
- builds a GPU image from [backend/Dockerfile.gpu](Dockerfile.gpu)
- deploys the FastAPI service
- creates or updates the Cloud Run Jobs for two-lane sources and PDF scan

Important workflow defaults from [deploy-backend.yml](../.github/workflows/deploy-backend.yml):

- GCP region: `europe-west3`
- PDF scan GPU region: `europe-west1`
- service account-driven deploys
- secrets injected via Cloud Run secret bindings

### Backend deploy secrets and envs

The workflow expects GitHub Actions secrets such as:

- `GCP_PROJECT_ID`
- `FIREBASE_PROJECT_ID`
- `GCP_WIF_PROVIDER`
- `GCP_WIF_SERVICE_ACCOUNT`

It also binds Cloud Run secrets for runtime values such as:

- `OPENAI_API_KEY`
- `ALLOWED_ORIGINS`
- `USER_KEY_ENCRYPTION_KEY`
- `ADMIN_UIDS`
- `OPENALEX_API_KEY`
- `SEMANTICSCHOLAR_API_KEY`

## Relationship To `testing-scripts/`

The backend runtime should not import from `testing-scripts/`.

Specifically:

- `testing-scripts/pdf-scan/` is research and benchmarking
- `backend/pdf_scan_runtime/` is the production PDF scan runtime
- `testing-scripts/sources-v2/` is research and local tooling
- `backend/services/two_lane_sources/` is the production two-lane runtime

If deleting or moving `testing-scripts/` breaks the API, that is a bug.

## Known Transitional Details

- the backend still accepts legacy `approved` claims during migration to `fullAccess`
- the legacy `functions/` package is outside this deploy path
- Firebase rules/index deployment is not managed from inside `backend/`

## Related Documentation

- repo overview: [README.md](../README.md)
- frontend app: [frontend/README.md](../frontend/README.md)
- migration notes: [FRONTEND_BACKEND_SPLIT_AND_CLEANUP_MASTER_PLAN.md](../FRONTEND_BACKEND_SPLIT_AND_CLEANUP_MASTER_PLAN.md)
