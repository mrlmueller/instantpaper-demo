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
- Cloud Run service: `instantpaper-two-lane-task-worker`
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

TWO_LANE_SOURCES_EXECUTION_BACKEND=local_split_jobs
TWO_LANE_ARTIFACT_BUCKET=
TWO_LANE_ARTIFACT_PREFIX=two-lane-runs
TWO_LANE_OPENALEX_RPS=5
TWO_LANE_SEMANTICSCHOLAR_RPS=1
TWO_LANE_PROVIDER_RATE_LIMIT_BACKEND=firestore
TWO_LANE_PROVIDER_RATE_LIMIT_COLLECTION=quellenFinderProviderRateLimits
TWO_LANE_PROVIDER_RATE_LIMIT_MAX_FUTURE_MS=86400000
TWO_LANE_PROVIDER_RATE_LIMIT_DISPATCH_BUFFER_MS=150
TWO_LANE_PROVIDER_TASK_MAX_RUNTIME_S=480
TWO_LANE_OPENALEX_TASK_MAX_PAGES_PER_TASK=12
TWO_LANE_SEMANTICSCHOLAR_TASK_MAX_PAGES_PER_TASK=5
TWO_LANE_OPENALEX_TASK_MAX_PAGES_TOTAL_PER_QUERY=120
TWO_LANE_SEMANTICSCHOLAR_TASK_MAX_PAGES_TOTAL_PER_QUERY=30
TWO_LANE_PROVIDER_TASK_REQUEST_TIMEOUT_S=30
TWO_LANE_PROVIDER_TASK_REQUEST_MAX_ATTEMPTS=3
TWO_LANE_PROVIDER_TASK_REQUEST_BACKOFF_MAX_S=15
TWO_LANE_TASK_DISPATCH_BACKEND=local_background
TWO_LANE_TASKS_PROJECT=
TWO_LANE_TASKS_LOCATION=europe-west3
TWO_LANE_OPENALEX_TASK_QUEUE=quellen-finder-openalex
TWO_LANE_SEMANTICSCHOLAR_TASK_QUEUE=quellen-finder-semanticscholar
TWO_LANE_TASK_HANDLER_URL=
TWO_LANE_TASK_DISPATCH_DEADLINE_S=630
TWO_LANE_TASK_DISPATCH_TOKEN=
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
- `TWO_LANE_SOURCES_EXECUTION_BACKEND`
  - `local_background` / `cloud_run_job` keep the current monolith
  - `local_split_jobs` / `cloud_run_split_jobs` enable the staged handoff path
- `TWO_LANE_ARTIFACT_BUCKET` / `TWO_LANE_ARTIFACT_PREFIX`
  - GCS location used by the staged two-lane backend for temporary handoff bundles
- `ALLOWED_ORIGINS`
  - comma-separated CORS allowlist
  - must include the frontend origin because large PDF uploads in `/pdf-scan` now go browser -> FastAPI directly
- `ADMIN_BASIC_USER` / `ADMIN_BASIC_PASSWORD`
  - protects the `/approve` HTML admin access surface
- `ADMIN_UIDS`
  - Firebase UID allowlist for `/api/admin/*`
- `OPENALEX_API_KEY` / `SEMANTICSCHOLAR_API_KEY`
  - used by two-lane sources workflows
- `TWO_LANE_OPENALEX_RPS` / `TWO_LANE_SEMANTICSCHOLAR_RPS`
  - provider-level request targets for the shared limiter
- `TWO_LANE_PROVIDER_RATE_LIMIT_BACKEND`
  - `firestore` for shared cross-run throttling, `local` for deterministic offline tests
- `TWO_LANE_PROVIDER_RATE_LIMIT_COLLECTION`
  - Firestore collection used by the shared limiter
- `TWO_LANE_PROVIDER_RATE_LIMIT_MAX_FUTURE_MS`
  - recovery guard if a limiter doc is accidentally pushed too far into the future
- `TWO_LANE_PROVIDER_RATE_LIMIT_DISPATCH_BUFFER_MS`
  - extra safety margin so actual HTTP send times preserve the target spacing under Firestore round-trip latency
- `TWO_LANE_PROVIDER_TASK_MAX_RUNTIME_S`
  - per-provider-task time budget before a bounded continuation task is queued
- `TWO_LANE_OPENALEX_TASK_MAX_PAGES_PER_TASK` / `TWO_LANE_SEMANTICSCHOLAR_TASK_MAX_PAGES_PER_TASK`
  - per-task page caps for the bounded query-chain provider workers; keep these low enough that cloud task handlers finish well below the worker service timeout
- `TWO_LANE_OPENALEX_TASK_MAX_PAGES_TOTAL_PER_QUERY` / `TWO_LANE_SEMANTICSCHOLAR_TASK_MAX_PAGES_TOTAL_PER_QUERY`
  - hard caps for a single provider query chain so one overly broad query cannot monopolize the whole run
- `TWO_LANE_PROVIDER_TASK_REQUEST_TIMEOUT_S`
  - per-request timeout inside a provider worker; keep this well below the Cloud Run request timeout
- `TWO_LANE_PROVIDER_TASK_REQUEST_MAX_ATTEMPTS` / `TWO_LANE_PROVIDER_TASK_REQUEST_BACKOFF_MAX_S`
  - task-local HTTP retry budget; keep this low because Cloud Tasks already retries whole task executions
- `TWO_LANE_TASK_DISPATCH_BACKEND`
  - `local_background` / `local_inline` for local task execution
  - `cloud_tasks` for the queued provider-fetch path on Cloud Run
- `TWO_LANE_TASKS_PROJECT` / `TWO_LANE_TASKS_LOCATION`
  - Cloud Tasks project and location for provider queues
- `TWO_LANE_OPENALEX_TASK_QUEUE` / `TWO_LANE_SEMANTICSCHOLAR_TASK_QUEUE`
  - queue names used for OpenAlex and Semantic Scholar provider query tasks
- `TWO_LANE_TASK_HANDLER_URL`
  - full callback URL for internal provider task execution; in production this should point to the dedicated task worker service, not the public API service
- `TWO_LANE_TASK_DISPATCH_DEADLINE_S`
  - per-task Cloud Tasks dispatch deadline; keep this only slightly above the worker service request timeout
- `TWO_LANE_TASK_DISPATCH_TOKEN`
  - shared secret header required by the internal task endpoint
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

Shared provider limiter tests:

```bash
cd backend
python scripts/test_two_lane_provider_rate_limit.py
python scripts/test_two_lane_provider_pipeline_http.py --backend local --workers 4
```

If local Firestore credentials are available, also run:

```bash
cd backend
python scripts/test_two_lane_provider_rate_limit.py --firestore
python scripts/test_two_lane_provider_pipeline_http.py --backend firestore --workers 4
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

The deploy workflow also sets two-lane rate-limit envs directly on the API service and the two-lane Cloud Run job:

- `TWO_LANE_OPENALEX_RPS`
- `TWO_LANE_SEMANTICSCHOLAR_RPS`
- `TWO_LANE_PROVIDER_RATE_LIMIT_BACKEND`
- `TWO_LANE_PROVIDER_RATE_LIMIT_COLLECTION`
- `TWO_LANE_PROVIDER_RATE_LIMIT_MAX_FUTURE_MS`
- `TWO_LANE_PROVIDER_RATE_LIMIT_DISPATCH_BUFFER_MS`

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
