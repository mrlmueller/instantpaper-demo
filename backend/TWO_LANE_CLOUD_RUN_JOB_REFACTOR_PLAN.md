# Two-Lane Sources Pipeline to Cloud Run Job

Date: 2026-03-12

This document is the implementation and operations plan for moving the Quellen-Finder two-lane sources pipeline out of the FastAPI request process and into a dedicated Cloud Run Job that is deployed automatically from GitHub.

The plan is intentionally concrete. It covers:

- the backend refactor
- the target Cloud Run architecture
- the GitHub Actions deployment model
- the IAM model
- step-by-step setup for Workload Identity Federation (WIF)
- step-by-step setup for Firebase Admin Application Default Credentials (ADC)
- rollout, testing, and rollback

It also separates:

- what should be changed in code
- what should be changed in GitHub / Google Cloud
- what can be done from the terminal
- what must be done manually in the Google Cloud Console or GitHub UI

## 1. Final Decisions

These decisions are already fixed and this plan assumes them:

- The frontend keeps calling `POST /api/quellen-finder/sources-two-lane/start`.
- The FastAPI endpoint becomes a launcher only. It must no longer run the pipeline with `BackgroundTasks`.
- The pipeline runs in a dedicated Cloud Run Job.
- The run doc must persist an immutable snapshot of the chapter input and the two-lane settings used for that run.
- Reject a new two-lane run if the same chapter already has a `queued` or `running` two-lane run.
- Cancellation can remain cooperative via Firestore `cancelRequestedAt`.
- Scope stays strictly limited to the two-lane sources pipeline.
- Use one shared backend image for both the FastAPI service and the Cloud Run Job.
- Use one GitHub Actions workflow that builds the image once and deploys both the service and the job.
- Use Workload Identity Federation for GitHub deployments.
- Use Firebase Admin ADC on Cloud Run runtime identities.
- Use separate service accounts for:
  - GitHub deployment
  - FastAPI runtime
  - Cloud Run Job runtime
- Baseline job sizing:
  - region: `europe-west3`
  - cpu: `4`
  - memory: `16Gi`
  - tasks: `1`
  - parallelism: `1`
  - timeout: `2h`
  - retries: `0`

## 2. Current State

### 2.1 Frontend trigger

The frontend starts the pipeline from `app/components/quellen-finder/QuellenFinder.tsx` by calling:

- `POST /api/quellen-finder/sources-two-lane/start`

The UI already watches Firestore for:

- run status
- progress
- results
- telemetry

This is good news. The frontend does not need a major architecture change. It already behaves like a job-monitoring UI.

### 2.2 FastAPI backend behavior today

The current start endpoint in `backend/main.py` does this:

1. validates user, project, and chapter
2. creates a run doc in Firestore
3. constructs runtime settings in memory
4. calls `background_tasks.add_task(...)`
5. runs the full pipeline inside the FastAPI Cloud Run service container

That last point is the deployment problem. The HTTP request returns quickly, but the actual work still lives in the Cloud Run service instance.

### 2.3 Current deployment behavior today

The repo currently has one workflow:

- `.github/workflows/deploy-backend.yml`

It currently:

- authenticates with `GCP_SA_KEY`
- builds the backend image from `./fastapi`
- pushes it to Artifact Registry
- deploys the HTTP service `instantpaper-api`

It does not:

- create or update a Cloud Run Job
- execute a Cloud Run Job
- use WIF

### 2.4 Current Firebase Admin auth today

`backend/services/firebase_service.py` currently initializes Firebase Admin using:

- `FIREBASE_PROJECT_ID`
- `FIREBASE_CLIENT_EMAIL`
- `FIREBASE_PRIVATE_KEY`

That means the Cloud Run runtime currently depends on a long-lived service-account private key secret. That is what we want to remove for Cloud Run runtime.

### 2.5 Current two-lane provider env usage today

The two-lane pipeline reads provider env vars from `backend/services/two_lane_sources/pipeline.py`:

- `OPENAI_API_KEY`
- `OPENALEX_API_KEY`
- `OPENALEX_EMAIL` or `OPENALEX_MAILTO`
- `SEMANTICSCHOLAR_API_KEY`

Important: the current deployment workflow does not inject the OpenAlex and Semantic Scholar secrets.

## 3. Target Architecture

### 3.1 High-level flow

The new flow should be:

1. User presses "Suche Starten" in the frontend.
2. Frontend calls the existing FastAPI start endpoint.
3. FastAPI validates the request.
4. FastAPI checks whether there is already an active two-lane run for that chapter.
5. FastAPI creates a Firestore run doc with:
   - immutable chapter snapshot
   - immutable chapter input snapshot
   - immutable two-lane settings snapshot
   - job metadata
6. FastAPI executes the Cloud Run Job using the Cloud Run Admin API with execution overrides.
7. FastAPI stores the returned execution name on the run doc.
8. FastAPI returns `202 Accepted`.
9. The Cloud Run Job starts, reads the run doc, runs the pipeline, and writes progress/results/telemetry back to Firestore.
10. The frontend continues to watch Firestore exactly as it does today.

### 3.2 Why this architecture is the right one

- It keeps the browser simple.
- It keeps the current frontend contract stable.
- It removes long-running compute from the HTTP service.
- It makes deployment deterministic: one image, one service, one job.
- It makes the run doc the source of truth, which is what a worker process needs.
- It reduces secret sprawl by moving Cloud Run runtime auth to ADC.

### 3.3 Why the run doc must store a snapshot

The worker cannot depend on FastAPI memory. Once the job starts, it must reconstruct everything from Firestore and environment.

For this reason the run doc must persist:

- `kapitelSnapshots`
  - immutable copy of chapter metadata at queue time
- `chapterInputSnapshot`
  - `chapterTitle`
  - `chapterSpecText`
- `twoLaneSettingsRequested`
  - planner model
  - OpenAlex query builder model
  - Semantic Scholar query builder model
  - rerank model
  - embedding model
  - reasoning effort
  - rerank concurrency

If the chapter is edited later, the running job must still use the exact input it was launched with.

## 4. Refactor Plan

### 4.1 New backend responsibilities

#### FastAPI service

The FastAPI service should:

- authenticate the user
- validate access to project and chapter
- reject duplicate active runs for the same chapter
- create the run doc
- launch the Cloud Run Job execution
- persist execution metadata
- return `202`
- keep the cancel endpoint

The FastAPI service should not:

- execute the pipeline
- keep long-running state in memory

#### Cloud Run Job worker

The Cloud Run Job worker should:

- parse execution args or env overrides
- load the run doc
- validate the run kind and status
- no-op safely if the run is already finished
- mark the run as `running`
- execute `run_quellen_finder_sources_two_lane_job(...)`
- write progress/results/telemetry exactly as today
- exit cleanly

### 4.2 Proposed code changes by file

#### A. `backend/main.py`

Replace the current `BackgroundTasks` launch with a Cloud Run Job launch flow.

Changes:

- remove `background_tasks: BackgroundTasks` from `quellen_finder_sources_two_lane_start`
- stop calling `background_tasks.add_task(...)`
- call a new launcher service method instead
- reject duplicate active runs for the same chapter
- persist requested settings on the run doc
- persist chapter input snapshot on the run doc
- persist job execution metadata on the run doc

Recommended endpoint behavior:

1. validate user / project / chapter
2. build chapter snapshot
3. build `chapterInputSnapshot`
4. build `twoLaneSettingsRequested`
5. call Firestore helper to ensure there is no active run for that chapter
6. create run doc with status `queued`
7. call Cloud Run Job `:run` API with overrides
8. store `executionName`
9. return:

```json
{
  "status": "queued",
  "run_id": "...",
  "projekt_id": "...",
  "kapitel_id": "...",
  "job_execution_name": "projects/.../executions/..."
}
```

#### B. `backend/services/quellen_finder_firestore_service.py`

Add new helpers.

Recommended new methods:

- `find_active_two_lane_run_for_kapitel(...)`
- `create_two_lane_run(...)`
- `attach_job_execution(...)`
- `mark_launch_failed(...)`
- `get_two_lane_run(...)`

Recommended run-doc shape additions:

```json
{
  "kind": "sources_two_lane",
  "status": "queued",
  "kapitelIds": ["..."],
  "kapitelSnapshots": [
    {
      "id": "...",
      "nummer": "...",
      "title": "...",
      "ueberschrift": "...",
      "thema": "..."
    }
  ],
  "chapterInputSnapshot": {
    "chapterTitle": "...",
    "chapterSpecText": "..."
  },
  "twoLaneSettingsRequested": {
    "openai_model_planner": "gpt-5-mini",
    "openai_model_openalex_query_builder": "gpt-5-mini",
    "openai_model_s2_query_builder": "gpt-5-mini",
    "openai_model_rerank": "gpt-5-nano",
    "embedding_model": "text-embedding-3-small",
    "openai_reasoning_effort": "high",
    "rerank_concurrency": 20
  },
  "job": {
    "provider": "cloud_run_jobs",
    "region": "europe-west3",
    "jobName": "instantpaper-two-lane-sources",
    "executionName": null,
    "launchedAt": null,
    "launchError": null
  }
}
```

Recommended duplicate-run check:

- query by `kind == "sources_two_lane"` and chapter membership
- filter `status in {"queued", "running"}` in application code if that avoids a new index

Reason:

- lower rollout risk
- no extra Firestore index required on day 1

#### C. `backend/services/quellen_finder_sources_two_lane_job.py`

Keep this module as the main business-logic worker function, but stop treating it as an in-process background task only.

Recommended change:

- keep `run_quellen_finder_sources_two_lane_job(...)`
- add a small wrapper that can load the run settings from Firestore and call it

Recommended new helper:

- `run_quellen_finder_sources_two_lane_job_from_run_doc(user_id, projekt_id, run_id)`

That wrapper should:

1. load the run doc
2. verify `kind == "sources_two_lane"`
3. pull the chapter input snapshot from the run doc
4. pull the requested settings from the run doc
5. derive `kapitel_id` from `kapitelIds[0]`
6. call the existing worker logic

#### D. New file: `backend/services/cloud_run_job_launcher.py`

Create a small dedicated launcher service.

Responsibilities:

- construct the Cloud Run Jobs REST API request
- authenticate with ADC
- execute the configured job
- support execution overrides
- return the execution name

Recommended implementation:

- use REST API `POST https://run.googleapis.com/v2/projects/.../locations/.../jobs/...:run`
- authenticate with `google.auth.default(...)` and an authorized session
- pass args override such as:

```text
--user-id=<uid>
--project-id=<projektId>
--run-id=<runId>
```

Reason for using args override:

- no additional persistent config mutation on the job
- every execution is self-contained
- simple audit trail

This requires the API runtime service account to have:

- `roles/run.jobsExecutorWithOverrides` on the Cloud Run Job

#### E. New file: `backend/run_two_lane_job.py`

Add a dedicated worker entrypoint at the `backend/` root.

Suggested behavior:

```text
python run_two_lane_job.py --user-id <uid> --project-id <projektId> --run-id <runId>
```

Responsibilities:

- parse args
- call `run_quellen_finder_sources_two_lane_job_from_run_doc(...)`
- return a non-zero exit code on failure

Why a dedicated entrypoint is recommended:

- the job should not boot the FastAPI ASGI app
- the Docker image stays shared, but the process entrypoint differs cleanly
- this keeps job startup simpler and easier to reason about

#### F. `backend/Dockerfile`

Keep one shared image.

Recommended changes:

- keep the default `CMD` for the HTTP service
- copy the new entrypoint file into the image

The service deployment should keep the current default command.

The job deployment should override the command to execute the worker entrypoint.

Example job command:

```bash
python run_two_lane_job.py
```

and then per-execution args overrides provide the specific run identifiers.

#### G. `backend/services/firebase_service.py`

Refactor Firebase Admin initialization to support both:

- Cloud Run runtime via ADC
- local development via service-account key env vars

Recommended initialization strategy:

1. If running on Cloud Run:
   - call `firebase_admin.initialize_app(options={...})`
   - do not pass `credentials.Certificate(...)`
   - let ADC resolve automatically from the runtime service account
2. Otherwise:
   - keep the current local-dev certificate path for `.env`

Recommended code shape:

```python
if config.IS_CLOUD_RUN:
    firebase_admin.initialize_app(
        options={
            "projectId": config.FIREBASE_PROJECT_ID or None,
            "storageBucket": config.FIREBASE_STORAGE_BUCKET or None,
        }
    )
else:
    cred = credentials.Certificate(...)
    firebase_admin.initialize_app(
        cred,
        {"storageBucket": config.FIREBASE_STORAGE_BUCKET},
    )
```

Important:

- keep local development working
- do not break scripts that still rely on local env credentials

#### H. `backend/utils/config.py`

Add non-secret config for the job launcher.

Recommended new env vars:

- `GOOGLE_CLOUD_PROJECT`
- `TWO_LANE_CLOUD_RUN_JOB_NAME`
- `TWO_LANE_CLOUD_RUN_JOB_REGION`

Notes:

- `GOOGLE_CLOUD_PROJECT` is commonly available in Google environments, but keeping explicit fallback logic is safer
- `FIREBASE_PROJECT_ID` should remain available as non-secret config
- `FIREBASE_PRIVATE_KEY` and `FIREBASE_CLIENT_EMAIL` should stop being required on Cloud Run

### 4.3 What should not change

The following should stay as-is conceptually:

- Firestore result schema for `twoLaneResults`
- Firestore telemetry schema for `twoLaneTelemetry`
- frontend Firestore listeners
- cooperative cancel via `cancelRequestedAt`
- the core two-lane ranking logic

## 5. Recommended Google Cloud Resource Layout

### 5.1 Runtime resources

- Cloud Run service: `instantpaper-api`
- Cloud Run job: `instantpaper-two-lane-sources`
- Artifact Registry repo: `cloud-run-source-deploy`
- region: `europe-west3`

Reason for staying on `europe-west3` instead of moving to `europe-west10`:

- your current deployment already uses `europe-west3`
- that avoids unnecessary migration risk
- `europe-west3` is already in Germany

If you later want Berlin specifically, that can be a separate infrastructure migration.

### 5.2 Service accounts

Use three separate identities:

#### 1. GitHub deployer

- `instantpaper-github-deploy@PROJECT_ID.iam.gserviceaccount.com`

Purpose:

- GitHub Actions impersonates this account via WIF
- builds, pushes, and deploys the service and the job

#### 2. FastAPI runtime

- `instantpaper-api-runtime@PROJECT_ID.iam.gserviceaccount.com`

Purpose:

- serves HTTP traffic
- accesses Firestore, Firebase Auth admin operations, Storage, and secrets
- executes the Cloud Run Job with overrides

#### 3. Job runtime

- `instantpaper-two-lane-job@PROJECT_ID.iam.gserviceaccount.com`

Purpose:

- runs the two-lane pipeline
- accesses Firestore and secrets
- does not need Firebase Auth admin
- does not need Storage permissions for this pipeline

## 6. IAM Plan

### 6.1 GitHub deployer service account roles

Grant the deployer service account:

- `roles/run.admin`
- `roles/artifactregistry.writer`
- `roles/iam.serviceAccountUser` on:
  - `instantpaper-api-runtime`
  - `instantpaper-two-lane-job`

Why:

- `run.admin` is the simplest reliable role for deploying both services and jobs
- `artifactregistry.writer` is required to push images
- `iam.serviceAccountUser` is required so the deployer can attach the runtime service accounts to the service/job

### 6.2 FastAPI runtime service account roles

Grant the API runtime service account:

- `roles/datastore.user`
- `roles/firebaseauth.admin`
- `roles/storage.objectAdmin`
- `roles/run.jobsExecutorWithOverrides` on the specific Cloud Run Job
- `roles/secretmanager.secretAccessor` on the secrets the API service needs

Why:

- `datastore.user`: Firestore reads/writes through Admin SDK
- `firebaseauth.admin`: admin user lookup, claim changes, session cookie ops
- `storage.objectAdmin`: export and PDF flows in the existing backend
- `run.jobsExecutorWithOverrides`: execute the two-lane job while passing run-specific args
- `secretmanager.secretAccessor`: Cloud Run runtime secret access

### 6.3 Job runtime service account roles

Grant the job runtime service account:

- `roles/datastore.user`
- `roles/secretmanager.secretAccessor` on the job secrets

Why:

- the two-lane job only needs Firestore and secrets
- it should not have Firebase Auth admin privileges
- it should not have Storage access unless a later feature requires it

### 6.4 Secret access model

Recommended split:

#### API service secrets

- `OPENAI_API_KEY`
- `USER_KEY_ENCRYPTION_KEY`
- `ADMIN_BASIC_PASSWORD`

Recommended API non-secret env vars:

- `FIREBASE_PROJECT_ID`
- `FIREBASE_STORAGE_BUCKET`
- `ALLOWED_ORIGINS`
- `ADMIN_UIDS`
- `TWO_LANE_CLOUD_RUN_JOB_NAME`
- `TWO_LANE_CLOUD_RUN_JOB_REGION`

#### Job secrets

- `OPENAI_API_KEY`
- `OPENALEX_API_KEY`
- `OPENALEX_EMAIL`
- `SEMANTICSCHOLAR_API_KEY`

Recommended job non-secret env vars:

- `FIREBASE_PROJECT_ID`
- `FIREBASE_STORAGE_BUCKET`

Note:

- `OPENALEX_EMAIL` is not highly sensitive, but keeping all external-provider config in Secret Manager reduces drift

## 7. Cloud Run Job Configuration

Recommended job config:

- job name: `instantpaper-two-lane-sources`
- region: `europe-west3`
- tasks: `1`
- parallelism: `1`
- cpu: `4`
- memory: `16Gi`
- task timeout: `2h`
- max retries: `0`

Rationale:

- the pipeline is a single long-running process
- it can download and write a large amount of data
- Cloud Run writable temp storage is in-memory and counts against container memory
- `4 CPU / 16Gi` is the lowest-risk starting point for your workload profile

If OOM errors appear, the next step is:

- increase memory to `24Gi` or `32Gi`
- or redesign temporary file handling

## 8. Deployment Workflow Plan

### 8.1 Recommended workflow structure

Keep one workflow file and build one image.

Recommended file:

- replace or rename `.github/workflows/deploy-backend.yml`

Recommended trigger:

- `push` to `master`

Recommended steps:

1. checkout
2. authenticate to Google Cloud with WIF
3. setup gcloud
4. configure docker auth for Artifact Registry
5. build image from `./fastapi`
6. push image
7. deploy Cloud Run service
8. create-or-update Cloud Run job

### 8.2 Recommended deployment order

Deploy the service first, then the job.

Reason:

- if job deployment fails, the API can still remain healthy
- you can roll back the workflow more cleanly

### 8.3 Recommended workflow YAML shape

This is the target pattern:

```yaml
name: Deploy FastAPI and Two-Lane Job

on:
  push:
    branches:
      - master

permissions:
  contents: read
  id-token: write

env:
  GCP_PROJECT_ID: ${{ secrets.GCP_PROJECT_ID }}
  GCP_REGION: europe-west3
  CLOUD_RUN_SERVICE: instantpaper-api
  CLOUD_RUN_JOB: instantpaper-two-lane-sources
  IMAGE_REPOSITORY: cloud-run-source-deploy

jobs:
  deploy:
    runs-on: ubuntu-latest

    steps:
      - name: Checkout repository
        uses: actions/checkout@v4

      - name: Authenticate to Google Cloud
        uses: google-github-actions/auth@v2
        with:
          workload_identity_provider: ${{ secrets.GCP_WIF_PROVIDER }}
          service_account: ${{ secrets.GCP_WIF_SERVICE_ACCOUNT }}

      - name: Set up gcloud
        uses: google-github-actions/setup-gcloud@v2
        with:
          project_id: ${{ env.GCP_PROJECT_ID }}

      - name: Configure Docker auth
        run: gcloud auth configure-docker "${GCP_REGION}-docker.pkg.dev" --quiet

      - name: Build and push image
        run: |
          IMAGE="${GCP_REGION}-docker.pkg.dev/${GCP_PROJECT_ID}/${IMAGE_REPOSITORY}/instantpaper-backend:${GITHUB_SHA}"
          echo "IMAGE=$IMAGE" >> $GITHUB_ENV
          docker build -t "$IMAGE" ./fastapi
          docker push "$IMAGE"

      - name: Deploy API service
        run: |
          gcloud run deploy "$CLOUD_RUN_SERVICE" \
            --region "$GCP_REGION" \
            --image "$IMAGE" \
            --allow-unauthenticated \
            --service-account "instantpaper-api-runtime@${GCP_PROJECT_ID}.iam.gserviceaccount.com" \
            --set-env-vars "FIREBASE_PROJECT_ID=${GCP_PROJECT_ID},FIREBASE_STORAGE_BUCKET=${GCP_PROJECT_ID}.firebasestorage.app,TWO_LANE_CLOUD_RUN_JOB_NAME=${CLOUD_RUN_JOB},TWO_LANE_CLOUD_RUN_JOB_REGION=${GCP_REGION}" \
            --update-env-vars "ALLOWED_ORIGINS=${{ secrets.ALLOWED_ORIGINS }},ADMIN_UIDS=${{ secrets.ADMIN_UIDS }}" \
            --set-secrets "OPENAI_API_KEY=OPENAI_API_KEY:latest,USER_KEY_ENCRYPTION_KEY=USER_KEY_ENCRYPTION_KEY:latest,ADMIN_BASIC_PASSWORD=ADMIN_BASIC_PASSWORD:latest"

      - name: Deploy two-lane Cloud Run Job
        run: |
          if gcloud run jobs describe "$CLOUD_RUN_JOB" --region "$GCP_REGION" >/dev/null 2>&1; then
            gcloud run jobs update "$CLOUD_RUN_JOB" \
              --region "$GCP_REGION" \
              --image "$IMAGE" \
              --service-account "instantpaper-two-lane-job@${GCP_PROJECT_ID}.iam.gserviceaccount.com" \
              --cpu 4 \
              --memory 16Gi \
              --tasks 1 \
              --parallelism 1 \
              --max-retries 0 \
              --task-timeout 2h \
              --command python \
              --args run_two_lane_job.py \
              --set-env-vars "FIREBASE_PROJECT_ID=${GCP_PROJECT_ID},FIREBASE_STORAGE_BUCKET=${GCP_PROJECT_ID}.firebasestorage.app" \
              --set-secrets "OPENAI_API_KEY=OPENAI_API_KEY:latest,OPENALEX_API_KEY=OPENALEX_API_KEY:latest,OPENALEX_EMAIL=OPENALEX_EMAIL:latest,SEMANTICSCHOLAR_API_KEY=SEMANTICSCHOLAR_API_KEY:latest"
          else
            gcloud run jobs create "$CLOUD_RUN_JOB" \
              --region "$GCP_REGION" \
              --image "$IMAGE" \
              --service-account "instantpaper-two-lane-job@${GCP_PROJECT_ID}.iam.gserviceaccount.com" \
              --cpu 4 \
              --memory 16Gi \
              --tasks 1 \
              --parallelism 1 \
              --max-retries 0 \
              --task-timeout 2h \
              --command python \
              --args run_two_lane_job.py \
              --set-env-vars "FIREBASE_PROJECT_ID=${GCP_PROJECT_ID},FIREBASE_STORAGE_BUCKET=${GCP_PROJECT_ID}.firebasestorage.app" \
              --set-secrets "OPENAI_API_KEY=OPENAI_API_KEY:latest,OPENALEX_API_KEY=OPENALEX_API_KEY:latest,OPENALEX_EMAIL=OPENALEX_EMAIL:latest,SEMANTICSCHOLAR_API_KEY=SEMANTICSCHOLAR_API_KEY:latest"
          fi
```

Notes:

- `ALLOWED_ORIGINS` and `ADMIN_UIDS` do not need to live in Secret Manager if you prefer regular GitHub secrets or direct env vars
- the exact secret/env split can be adjusted
- the workflow should remove `GCP_SA_KEY`

## 9. Step-by-Step: Workload Identity Federation Setup

This is the setup you asked to be "idiot proof".

This section assumes:

- your GitHub repo is `OWNER/REPO`
- the deploy branch is `master`
- you can run `gcloud`
- you have project admin rights

### 9.1 What this setup accomplishes

After this is done:

- GitHub Actions no longer needs a long-lived `GCP_SA_KEY`
- GitHub receives a short-lived OIDC token
- Google trusts that token only for your repo and branch
- GitHub impersonates a dedicated deploy service account

### 9.2 One-time preparation

Run these commands from your terminal or Cloud Shell.

Replace placeholders first:

```powershell
$PROJECT_ID="YOUR_PROJECT_ID"
$PROJECT_NUMBER=(gcloud projects describe $PROJECT_ID --format="value(projectNumber)")
$REGION="europe-west3"
$REPO_OWNER="YOUR_GITHUB_OWNER"
$REPO_NAME="instantpaper"
$WIF_POOL="github-actions-pool"
$WIF_PROVIDER="github-actions-provider"
$DEPLOY_SA="instantpaper-github-deploy@$PROJECT_ID.iam.gserviceaccount.com"
$API_SA="instantpaper-api-runtime@$PROJECT_ID.iam.gserviceaccount.com"
$JOB_SA="instantpaper-two-lane-job@$PROJECT_ID.iam.gserviceaccount.com"
```

Set the active project:

```powershell
gcloud config set project $PROJECT_ID
```

### 9.3 Enable required APIs

Run:

```powershell
gcloud services enable `
  run.googleapis.com `
  artifactregistry.googleapis.com `
  iam.googleapis.com `
  iamcredentials.googleapis.com `
  sts.googleapis.com `
  secretmanager.googleapis.com
```

Why:

- `run.googleapis.com`: Cloud Run service and job deployment
- `artifactregistry.googleapis.com`: container registry
- `iam.googleapis.com`: service account IAM management
- `iamcredentials.googleapis.com`: service account impersonation
- `sts.googleapis.com`: token exchange for WIF
- `secretmanager.googleapis.com`: runtime secrets

### 9.4 Create the deploy service account

Run:

```powershell
gcloud iam service-accounts create instantpaper-github-deploy `
  --display-name="InstantPaper GitHub Deploy"
```

If it already exists, continue.

### 9.5 Grant the deploy service account the deployment roles

Run:

```powershell
gcloud projects add-iam-policy-binding $PROJECT_ID `
  --member="serviceAccount:$DEPLOY_SA" `
  --role="roles/run.admin"

gcloud projects add-iam-policy-binding $PROJECT_ID `
  --member="serviceAccount:$DEPLOY_SA" `
  --role="roles/artifactregistry.writer"
```

Allow it to attach runtime service accounts:

```powershell
gcloud iam service-accounts add-iam-policy-binding $API_SA `
  --member="serviceAccount:$DEPLOY_SA" `
  --role="roles/iam.serviceAccountUser"

gcloud iam service-accounts add-iam-policy-binding $JOB_SA `
  --member="serviceAccount:$DEPLOY_SA" `
  --role="roles/iam.serviceAccountUser"
```

### 9.6 Create the workload identity pool

Run:

```powershell
gcloud iam workload-identity-pools create $WIF_POOL `
  --location="global" `
  --display-name="GitHub Actions Pool"
```

If it already exists, continue.

### 9.7 Create the GitHub OIDC provider

Run:

```powershell
gcloud iam workload-identity-pools providers create-oidc $WIF_PROVIDER `
  --location="global" `
  --workload-identity-pool=$WIF_POOL `
  --display-name="GitHub Actions Provider" `
  --issuer-uri="https://token.actions.githubusercontent.com/" `
  --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository,attribute.repository_owner=assertion.repository_owner,attribute.ref=assertion.ref,attribute.actor=assertion.actor" `
  --attribute-condition="assertion.repository=='$REPO_OWNER/$REPO_NAME' && assertion.repository_owner=='$REPO_OWNER' && assertion.ref=='refs/heads/master'"
```

Why this condition:

- only this repo can use the provider
- only your GitHub owner can use it
- only pushes to `master` satisfy the condition

If later you want preview environments or manual workflow dispatches, relax this condition later. Do not relax it now.

### 9.8 Allow the GitHub principal to impersonate the deploy service account

Run:

```powershell
gcloud iam service-accounts add-iam-policy-binding $DEPLOY_SA `
  --role="roles/iam.workloadIdentityUser" `
  --member="principalSet://iam.googleapis.com/projects/$PROJECT_NUMBER/locations/global/workloadIdentityPools/$WIF_POOL/attribute.repository/$REPO_OWNER/$REPO_NAME"
```

Why this binding uses `attribute.repository`:

- it is easier to reason about than `subject`
- the branch restriction already lives in the provider attribute condition

### 9.9 Add the new GitHub repository secrets

Open GitHub:

- repo
- `Settings`
- `Secrets and variables`
- `Actions`

Create these secrets:

- `GCP_PROJECT_ID`
  - value: your GCP project id
- `GCP_WIF_PROVIDER`
  - value:
    `projects/PROJECT_NUMBER/locations/global/workloadIdentityPools/POOL_ID/providers/PROVIDER_ID`
- `GCP_WIF_SERVICE_ACCOUNT`
  - value:
    `instantpaper-github-deploy@PROJECT_ID.iam.gserviceaccount.com`

Remove this old secret after the new workflow succeeds once:

- `GCP_SA_KEY`

### 9.10 Update the workflow

In the workflow:

- add

```yaml
permissions:
  contents: read
  id-token: write
```

- replace the old auth step:

```yaml
uses: google-github-actions/auth@v2
with:
  workload_identity_provider: ${{ secrets.GCP_WIF_PROVIDER }}
  service_account: ${{ secrets.GCP_WIF_SERVICE_ACCOUNT }}
```

### 9.11 First-time validation

After pushing the workflow change:

1. open GitHub Actions
2. run the deployment
3. confirm the auth step succeeds
4. confirm docker push succeeds
5. confirm Cloud Run deploy succeeds

If auth fails immediately:

- wait 5 minutes
- WIF propagation is not always instant

## 10. Step-by-Step: Firebase Admin ADC Setup

This section covers runtime auth for the FastAPI service and the Cloud Run Job.

### 10.1 What this setup accomplishes

After this is done:

- Cloud Run runtime no longer needs `FIREBASE_PRIVATE_KEY`
- Cloud Run runtime no longer needs `FIREBASE_CLIENT_EMAIL`
- Firebase Admin uses the runtime service account automatically

This only affects Cloud Run runtime.

Local development can still use:

- the current `.env` certificate path
- or a local ADC file via `GOOGLE_APPLICATION_CREDENTIALS`

### 10.2 Keep these non-secret env vars

Do keep:

- `FIREBASE_PROJECT_ID`
- `FIREBASE_STORAGE_BUCKET`

Recommended values:

- `FIREBASE_PROJECT_ID=YOUR_PROJECT_ID`
- `FIREBASE_STORAGE_BUCKET=YOUR_PROJECT_ID.firebasestorage.app`

### 10.3 Create the job runtime service account

Run:

```powershell
gcloud iam service-accounts create instantpaper-two-lane-job `
  --display-name="InstantPaper Two-Lane Job Runtime"
```

If it already exists, continue.

### 10.4 Keep or reuse the existing API runtime service account

You already deploy the API service with:

- `instantpaper-api-runtime@PROJECT_ID.iam.gserviceaccount.com`

Do not replace it unless there is a reason. Reuse it and grant the missing roles.

### 10.5 Grant the FastAPI runtime service account the runtime roles

Run:

```powershell
gcloud projects add-iam-policy-binding $PROJECT_ID `
  --member="serviceAccount:$API_SA" `
  --role="roles/datastore.user"

gcloud projects add-iam-policy-binding $PROJECT_ID `
  --member="serviceAccount:$API_SA" `
  --role="roles/firebaseauth.admin"

gcloud projects add-iam-policy-binding $PROJECT_ID `
  --member="serviceAccount:$API_SA" `
  --role="roles/storage.objectAdmin"
```

Important:

- if your API runtime service account already has some of these roles, re-running is harmless

### 10.6 Grant the job runtime service account the runtime roles

Run:

```powershell
gcloud projects add-iam-policy-binding $PROJECT_ID `
  --member="serviceAccount:$JOB_SA" `
  --role="roles/datastore.user"
```

The job runtime does not need:

- `roles/firebaseauth.admin`
- `roles/storage.objectAdmin`

for the two-lane pipeline.

### 10.7 Grant the API runtime service account permission to execute the job

After the job exists, run:

```powershell
gcloud run jobs add-iam-policy-binding instantpaper-two-lane-sources `
  --region=$REGION `
  --member="serviceAccount:$API_SA" `
  --role="roles/run.jobsExecutorWithOverrides"
```

Reason:

- the API must execute the job and pass per-run args

### 10.8 Grant Secret Manager access

For each secret needed by the API runtime:

```powershell
gcloud secrets add-iam-policy-binding OPENAI_API_KEY `
  --member="serviceAccount:$API_SA" `
  --role="roles/secretmanager.secretAccessor"
```

Repeat for:

- `USER_KEY_ENCRYPTION_KEY`
- `ADMIN_BASIC_PASSWORD`

For each secret needed by the job runtime:

```powershell
gcloud secrets add-iam-policy-binding OPENAI_API_KEY `
  --member="serviceAccount:$JOB_SA" `
  --role="roles/secretmanager.secretAccessor"
```

Repeat for:

- `OPENALEX_API_KEY`
- `OPENALEX_EMAIL`
- `SEMANTICSCHOLAR_API_KEY`

### 10.9 Refactor the code to prefer ADC on Cloud Run

In code, the runtime detection should be:

- Cloud Run:
  - `firebase_admin.initialize_app(...)`
  - no explicit certificate
- local dev:
  - existing env-key path stays available

This lets you:

- remove `FIREBASE_CLIENT_EMAIL` from Cloud Run deployment config
- remove `FIREBASE_PRIVATE_KEY` from Cloud Run deployment config

### 10.10 Local development after ADC refactor

You have two safe local-dev options.

#### Option A: keep the current `.env` key path locally

This is the least disruptive local-dev path.

Keep in `backend/.env`:

- `FIREBASE_PROJECT_ID`
- `FIREBASE_CLIENT_EMAIL`
- `FIREBASE_PRIVATE_KEY`
- `FIREBASE_STORAGE_BUCKET`

Cloud Run will ignore those because Cloud Run will use ADC.

#### Option B: use local ADC

If you want local development without embedding the key in `.env`:

1. download a service account JSON once
2. set:

```powershell
$env:GOOGLE_APPLICATION_CREDENTIALS="C:\path\to\firebase-admin.json"
```

3. keep these in `.env`:

- `FIREBASE_PROJECT_ID`
- `FIREBASE_STORAGE_BUCKET`

This is cleaner, but it is a local workflow change.

## 11. Manual Setup Checklist

These are the things I cannot do from this terminal because they require your cloud account, GitHub permissions, or live production resources.

### Google Cloud Console or gcloud

- create the deploy service account if it does not exist
- create the job runtime service account
- create the workload identity pool
- create the workload identity provider
- bind `roles/iam.workloadIdentityUser`
- bind runtime IAM roles
- create the required Secret Manager secrets if they do not already exist
- grant secret access to the runtime service accounts

### GitHub UI

- create `GCP_WIF_PROVIDER`
- create `GCP_WIF_SERVICE_ACCOUNT`
- delete `GCP_SA_KEY` after the new deployment path is confirmed

## 12. Implementation Order

Use this exact order to minimize risk.

### Phase 1. Code refactor on a branch

1. add the worker entrypoint
2. add the Cloud Run job launcher service
3. refactor the start endpoint to create run docs and launch jobs
4. add duplicate-run rejection
5. refactor Firebase Admin init to support ADC
6. update config handling
7. update Dockerfile

### Phase 2. Infrastructure setup

1. create / verify service accounts
2. grant IAM roles
3. create Secret Manager secrets for provider keys
4. configure WIF
5. add GitHub secrets

### Phase 3. Workflow update

1. replace `GCP_SA_KEY` auth with WIF
2. add Cloud Run Job deployment step
3. keep service deployment in the same workflow

### Phase 4. Deploy infrastructure

1. merge the workflow change
2. run GitHub Actions deployment
3. verify service deploy
4. verify job deploy

### Phase 5. Smoke test

1. start a two-lane run from the frontend
2. confirm the API returns `202`
3. confirm the run doc gets an execution name
4. confirm the job starts and marks the run `running`
5. confirm progress updates keep appearing
6. confirm results are written
7. confirm cancel still works cooperatively

### Phase 6. Cleanup

After production is stable:

- remove `FIREBASE_CLIENT_EMAIL` from Cloud Run deployment config
- remove `FIREBASE_PRIVATE_KEY` from Cloud Run deployment config
- remove `GCP_SA_KEY` from GitHub secrets

## 13. Rollout Validation Checklist

Use this checklist after deployment.

### API service checks

- `GET /health` works
- login still works
- admin endpoints still work
- export and PDF endpoints still work

### Two-lane start checks

- starting a run returns `202`
- duplicate active run is rejected
- run doc contains:
  - `chapterInputSnapshot`
  - `twoLaneSettingsRequested`
  - `job.executionName`

### Job execution checks

- Cloud Run Job execution starts in `europe-west3`
- logs show the worker entrypoint, not uvicorn
- run transitions `queued -> running -> success`
- results appear in `twoLaneResults`
- telemetry appears in `twoLaneTelemetry`

### Cancel checks

- cancel endpoint sets `cancelRequestedAt`
- the job exits at the next cooperative checkpoint
- run transitions to `cancelled`

## 14. Rollback Plan

If the deployment works but job launch fails:

- keep the new image
- fix IAM or job config
- redeploy

If the new API launch logic is broken:

- roll back the FastAPI service to the previous revision
- leave the Cloud Run Job deployed but unused

If ADC causes Firebase runtime failures:

- temporarily re-add `FIREBASE_CLIENT_EMAIL` and `FIREBASE_PRIVATE_KEY` to the service/job deployment
- then debug runtime service-account IAM separately

Do not remove the old secrets until:

- the API service has been stable in production
- at least one full two-lane run succeeded through the Cloud Run Job

## 15. What I Can Do From the Terminal vs What You Must Do

### What I can do in code

- refactor the FastAPI start endpoint
- add the job launcher module
- add the worker entrypoint
- refactor Firebase Admin init for ADC
- update the Dockerfile
- update the GitHub Actions workflow
- add any supporting config and Firestore helpers

### What I cannot safely do from this terminal

- create or modify your real GCP service accounts
- grant IAM roles in your real project
- create or update your real Secret Manager secrets
- create the workload identity provider in your real project
- add GitHub repository secrets in your repo settings

That is why this document includes exact commands and UI steps.

## 16. Suggested Next Implementation Diff

When the actual code implementation starts, the first patch should touch roughly these files:

- `backend/main.py`
- `backend/services/quellen_finder_firestore_service.py`
- `backend/services/quellen_finder_sources_two_lane_job.py`
- `backend/services/firebase_service.py`
- `backend/utils/config.py`
- `backend/Dockerfile`
- `.github/workflows/deploy-backend.yml`

and add roughly these files:

- `backend/services/cloud_run_job_launcher.py`
- `backend/run_two_lane_job.py`

## 17. Why This Plan Minimizes Problems

- The frontend contract stays stable.
- The run doc becomes the source of truth before the worker is launched.
- One image reduces drift between service and worker.
- One workflow reduces deployment skew.
- WIF removes the most fragile long-lived GitHub credential.
- ADC removes the most fragile long-lived Cloud Run runtime credential.
- Separate service accounts reduce blast radius.
- `europe-west3` avoids an unnecessary region migration while still staying in Germany.

## 18. Official Documentation Used

- Cloud Run execute jobs:
  - https://cloud.google.com/run/docs/execute/jobs
- Cloud Run create jobs:
  - https://cloud.google.com/run/docs/create-jobs
- Cloud Run manage job executions:
  - https://cloud.google.com/run/docs/managing/job-executions
- Cloud Run job service identity:
  - https://cloud.google.com/run/docs/configuring/jobs/service-identity
- Cloud Run job memory limits:
  - https://cloud.google.com/run/docs/configuring/jobs/memory-limits
- Cloud Run job task timeout:
  - https://cloud.google.com/run/docs/configuring/task-timeout
- Cloud Run locations:
  - https://cloud.google.com/run/docs/locations
- Cloud Run IAM roles:
  - https://cloud.google.com/iam/docs/roles-permissions/run
- Workload Identity Federation with deployment pipelines:
  - https://cloud.google.com/iam/docs/workload-identity-federation-with-deployment-pipelines
- Google GitHub auth action:
  - https://github.com/google-github-actions/auth
- Cloud Run service identity:
  - https://cloud.google.com/run/docs/securing/service-identity
- Firebase Admin setup:
  - https://firebase.google.com/docs/admin/setup
- Firebase Admin Python reference:
  - https://firebase.google.com/docs/reference/admin/python/firebase_admin

