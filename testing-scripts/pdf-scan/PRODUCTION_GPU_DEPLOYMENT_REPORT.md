# Production GPU Deployment Report

Date: 2026-03-24

## Current State

The local split is a good prototype:

- `run_pipeline_cpu.py` runs Phases `A-E`
- `run_pipeline_gpu.py` resumes from an existing run directory and runs `F-G`

What is already good:

- GPU time is isolated to the expensive rerank stage.
- The GPU runner only needs a subset of the run artifacts.
- The actual phase logic does not need a full redesign to benefit from GPU.

What is still local-dev only:

- Both runners assume one shared local filesystem.
- Inputs are local paths (`--theme-md`, `--pdf-dir`, `--run-dir`).
- There is no storage handoff abstraction.
- There is no durable orchestration/state model for retries and partial failures.
- Secrets are expected in local environment variables.

## Important Cloud Facts

Official references:

- Cloud Run pricing: <https://cloud.google.com/run/pricing>
- Cloud Run jobs with GPU: <https://docs.cloud.google.com/run/docs/configuring/jobs/gpu>
- Cloud Run jobs GPU best practices: <https://docs.cloud.google.com/run/docs/configuring/jobs/gpu-best-practices>
- Cloud Run jobs creation / timeout limits: <https://docs.cloud.google.com/run/docs/create-jobs>
- Cloud Storage pricing: <https://cloud.google.com/storage/pricing>
- Cloud Run Cloud Storage volumes: <https://docs.cloud.google.com/run/docs/configuring/services/cloud-storage-volume-mounts>
- Workflows pricing: <https://cloud.google.com/workflows/pricing>
- Workflows executes Cloud Run jobs: <https://cloud.google.com/workflows/docs/tutorials/execute-cloud-run-jobs>

Key constraints:

- Cloud Run jobs support GPUs.
- L4 GPU requires at least `4 CPU` and `16 GiB` memory.
- Only `1 GPU` can be attached per Cloud Run instance.
- GPU job timeout is capped at `1 hour`.
- GPU jobs are supported only in selected regions.
- In Europe, current L4 job regions are `europe-west1` and `europe-west4`.

Implication:

- If the pipeline needs Cloud Run GPU jobs in Europe, the production region should be `europe-west1` or `europe-west4`.
- If your current Firebase / GCS bucket is in another region, create a dedicated pipeline bucket in one of those GPU-supported regions.

## Recommended Architecture

### Services

1. API / orchestration entrypoint
   - Existing FastAPI backend or a thin orchestration service
   - Receives user request
   - Creates `run_id`
   - Writes run metadata/status
   - Starts workflow

2. CPU batch stage
   - Cloud Run Job
   - Runs Phases `A-E`
   - Uploads artifacts + compact GPU handoff bundle to GCS

3. GPU batch stage
   - Cloud Run Job with `1 x nvidia-l4`
   - Downloads compact handoff bundle
   - Runs Phases `F-G`
   - Uploads rerank/final outputs to GCS

4. Artifact store
   - Google Cloud Storage bucket
   - One prefix per run, for example:
     - `gs://pdf-scan-runs/{run_id}/input/`
     - `gs://pdf-scan-runs/{run_id}/cpu/`
     - `gs://pdf-scan-runs/{run_id}/handoff/`
     - `gs://pdf-scan-runs/{run_id}/gpu/`
     - `gs://pdf-scan-runs/{run_id}/final/`

5. Orchestration
   - Google Cloud Workflows
   - Executes CPU job, waits, then executes GPU job

6. State / status store
   - Firestore or your app database
   - Stores `run_id`, current phase, status, timestamps, bucket prefix, errors

### Why this shape

- Jobs fit the workload better than services because this is batch work, not request/response work.
- Workflows is cheap and gives clean step orchestration without custom glue code.
- GCS is the correct backend abstraction for server-to-server artifacts.
- The GPU container only exists for the short rerank/calibration window.

## Do Not Use The Whole Run Directory As Handoff

Measured on a real 22-PDF run:

- Whole run directory: about `107 MB`, about `600` files
- Minimal Phase `F/G` handoff: about `16 MB`

Recommended handoff contents:

- `config.json`
- `query_plan.json`
- `normalized/documents.jsonl`
- `normalized/sections.jsonl`
- `normalized/passages.jsonl`
- `retrieval/fused_candidates.jsonl`
- `retrieval/phase_e_subpoint_support.json`
- `handoff_manifest.json`

Recommendation:

- Package those files into one archive such as `handoff.tar.zst`
- Upload that single archive plus a small manifest
- GPU job downloads only that archive

This keeps GPU startup simple and minimizes storage/listing overhead.

## Recommended Code Changes Before Production

### 1. Add a storage abstraction

Create something like:

- `storage_backend.py`

With at least:

- `download_uri(uri, local_path)`
- `upload_file(local_path, uri)`
- `upload_dir(local_dir, uri_prefix)`
- `download_dir(uri_prefix, local_dir)`
- `exists(uri)`
- `write_json(uri, payload)`
- `read_json(uri)`

Backends:

- local filesystem
- GCS

This allows local dev to keep working while production uses GCS.

### 2. Replace local-path-only runner contracts

`run_pipeline_cpu.py` should accept production inputs such as:

- `--theme-uri`
- `--pdf-prefix`
- `--artifact-prefix`
- `--handoff-prefix`
- `--status-uri`

`run_pipeline_gpu.py` should accept:

- `--handoff-uri`
- `--artifact-prefix`
- `--status-uri`

### 3. Add explicit CPU->GPU handoff packaging

After Phase E:

- build compact handoff bundle
- compute checksums
- write `handoff_manifest.json`
- upload bundle + manifest to GCS

Suggested manifest fields:

- `run_id`
- `pipeline_version`
- `image_version`
- `created_at`
- `phase_completed`
- `required_files`
- `sha256`
- `doc_count`
- `section_count`
- `candidate_count`
- `options_snapshot`

### 4. Add durable run status updates

Current local stage timing is useful but not enough for production.

Add status transitions like:

- `queued`
- `cpu_running`
- `cpu_succeeded`
- `gpu_running`
- `gpu_succeeded`
- `completed`
- `failed`

Also persist:

- last error message
- retry count
- started / finished timestamps
- links to artifact prefixes

### 5. Move secrets to Secret Manager

Do not load `.env` in production.

Use:

- Secret Manager for `OPENAI_API_KEY`
- service account IAM for GCS / Cloud Run / Workflows access

### 6. Version the pipeline contract

CPU and GPU stages must agree on artifact schema.

Add:

- `PIPELINE_SCHEMA_VERSION`
- `PIPELINE_IMAGE_VERSION`

Store both in:

- `config.json`
- `handoff_manifest.json`

GPU job should fail fast if the manifest version is unsupported.

### 7. Decide on image strategy

Recommended:

- separate CPU and GPU images

Reason:

- GPU image needs CUDA-enabled PyTorch and likely model assets
- CPU image should stay smaller and faster to build/deploy

### 8. Prepackage the reranker model in the GPU image

Current `phase_f_lab.py` loads the reranker via `AutoTokenizer.from_pretrained(...)` and `AutoModelForSequenceClassification.from_pretrained(...)`.

In production, do not rely on downloading that model from Hugging Face at runtime.

Preferred options:

1. Bake the reranker model into the GPU image
2. Or host it in your own GCS bucket and download it at startup

Because this model is far below the `10 GB` threshold, baking it into the image is the simplest and best option for minimizing billed GPU time.

### 9. Keep report generation out of the critical GPU path if needed

Today the GPU runner executes `F-G`.

That is fine because `G` is cheap.

If later report generation becomes heavy, split it like:

- CPU job A-E
- GPU job F
- CPU postprocess job G + report generation

At the moment this is optional, not required.

## Recommended Production Flow

1. API uploads PDFs + theme file to GCS
2. API creates run record in database
3. API starts Workflow with:
   - `run_id`
   - input bucket prefix
   - output bucket prefix
4. Workflow starts CPU Cloud Run Job
5. CPU job downloads inputs, runs `A-E`, uploads handoff bundle
6. Workflow starts GPU Cloud Run Job
7. GPU job downloads handoff bundle, runs `F-G`, uploads final outputs
8. Workflow marks run complete
9. API/UI reads status + results from DB/GCS

## Why GCS, Not Firebase Storage API, For Backend Handoff

If you already use Firebase Storage, the underlying storage is still Google Cloud Storage.

For backend pipeline jobs, use GCS semantics directly:

- cleaner IAM
- clearer service account permissions
- direct control over bucket region and object layout
- easier interop with Cloud Run / Workflows

Practical recommendation:

- you can use the same physical bucket if it is in the right region
- but treat it as a GCS bucket from the backend side

## Cost Estimates

Using official Cloud Run Tier 1 prices:

- CPU: `$0.000011244` per vCPU-second
- Memory: `$0.000001235` per GiB-second
- L4 GPU (no zonal redundancy): `$0.0001867` per second

### CPU stage example: 4 CPU / 16 GiB

Per second:

- CPU = `4 * 0.000011244 = 0.000044976`
- RAM = `16 * 0.000001235 = 0.000019760`
- Total = `0.000064736 / second`

Per minute:

- about `$0.003884`

10 minutes:

- about `$0.0388`

### GPU stage example: 4 CPU / 16 GiB / 1 L4

Per second:

- CPU = `0.000044976`
- RAM = `0.000019760`
- GPU = `0.000186700`
- Total = `0.000251436 / second`

Per minute:

- about `$0.015086`

Example durations:

- 3 minutes: about `$0.0453`
- 5 minutes: about `$0.0754`
- 10 minutes: about `$0.1509`
- 15 minutes: about `$0.2263`

### If you overprovision the GPU job: 8 CPU / 32 GiB / 1 L4

Per minute:

- about `$0.01897`

10 minutes:

- about `$0.1897`

### Storage handoff cost

For a `16 MB` handoff bundle in a single-region Standard bucket:

- storage for 1 day is effectively negligible (about `$0.00001`)
- a few upload/download operations are also negligible (fractions of a cent)

Conclusion:

- storage is not the cost problem
- GPU minutes are the real lever

## Region Recommendation

For Europe, prefer one of:

- `europe-west1`
- `europe-west4`

Reason:

- supported for Cloud Run L4 GPU jobs
- Tier 1 Cloud Run pricing
- same-region Cloud Run <-> Google Cloud data transfer is not charged

Do not assume Berlin or Frankfurt are okay for GPU jobs just because they are close; the official GPU jobs region list matters more than geographic preference.

## Image / Build Recommendation

### CPU image

- slim Python base
- no CUDA
- only pipeline CPU dependencies

### GPU image

- CUDA-capable base image
- CUDA-enabled PyTorch
- reranker model baked into image
- pipeline code + GPU runner only

Store both in Artifact Registry.

## Biggest Risks Still Open

1. Schema drift between CPU and GPU stages
2. Region mismatch between bucket and GPU job
3. Runtime model download from public internet
4. Missing idempotency on retries
5. Lack of durable run status for the app
6. Large report/upload work accidentally extending GPU runtime

## Final Recommendation

If you want the cleanest production path:

- CPU stage: Cloud Run Job
- GPU stage: Cloud Run Job with L4
- Orchestration: Workflows
- Artifacts: GCS bucket in `europe-west1` or `europe-west4`
- Status: Firestore or app DB
- Images: separate CPU and GPU images
- GPU model delivery: bake reranker into image

This is the lowest-complexity path that still matches your local split and keeps GPU time tightly bounded.
