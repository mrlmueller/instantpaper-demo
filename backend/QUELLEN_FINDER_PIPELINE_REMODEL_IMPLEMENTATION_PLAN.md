# Quellen-Finder Pipeline Remodel Implementation Plan

Date: 2026-03-29

This document is the implementation plan for remodeling the Quellen-Finder `/quellen-finder` two-lane pipeline so that it:

- stops tripping OpenAlex and Semantic Scholar rate limits when many runs overlap
- speeds up the obviously independent parts of the pipeline
- keeps the current frontend contract stable
- matches the current repository and GitHub Actions deployment reality
- uses only components whose behavior was re-verified against current official documentation

This plan extends the existing Cloud Run Job refactor and supersedes it for the queue-based provider orchestration design.

## 1. Verified Current State In This Repo

The current public start endpoint already behaves like a submit endpoint. It validates the request, creates a Firestore run doc, and then launches one Cloud Run Job execution per request from [main.py](main.py) and [services/cloud_run_job_launcher.py](services/cloud_run_job_launcher.py).

Important current facts:

- Duplicate protection is not transactional. The code first looks for an active run and then creates a new run, which leaves a race window when multiple starts happen at the same time. See [main.py](main.py) and [services/quellen_finder_firestore_service.py](services/quellen_finder_firestore_service.py).
- The Cloud Run worker uses a temporary run directory in Cloud Run. That means the current provider cache is per-run and ephemeral, not shared across runs. See [services/two_lane_sources/runner.py](services/two_lane_sources/runner.py).
- Query generation is sequential today. OpenAlex queries are built first, then Semantic Scholar queries. See [services/two_lane_sources/runner.py](services/two_lane_sources/runner.py).
- Retrieval is also sequential today. OpenAlex fetch runs first, then Semantic Scholar fetch. See [services/two_lane_sources/runner.py](services/two_lane_sources/runner.py).
- Provider throttling is only local to one process. `openalex_rps` and `semanticscholar_rps` live in process-local rate limiters in [services/two_lane_sources/pipeline.py](services/two_lane_sources/pipeline.py), so they do not protect against many concurrent jobs.
- Semantic Scholar is called twice in the current pipeline. The first call path is the bulk retrieval in Phase D, and the second is the recommendations expansion in Phase F. See [services/two_lane_sources/pipeline.py](services/two_lane_sources/pipeline.py) and [services/two_lane_sources/phase_f.py](services/two_lane_sources/phase_f.py).
- The current deployment workflow only deploys the public FastAPI service plus Cloud Run Jobs. It does not deploy Cloud Tasks queues or any private Cloud Run task-handler service. See [../.github/workflows/deploy-backend.yml](../.github/workflows/deploy-backend.yml).
- The current backend requirements do not include the Cloud Tasks client library. See [requirements.txt](requirements.txt).
- The PDF scan pipeline already contains a good internal precedent for GCS-based handoff and split-stage job orchestration. See [services/pdf_scan/storage.py](services/pdf_scan/storage.py), [services/pdf_scan/handoff.py](services/pdf_scan/handoff.py), and [services/pdf_scan/cpu_job.py](services/pdf_scan/cpu_job.py).

## 2. Verified External Constraints

The following constraints were re-checked against current official docs on 2026-03-29:

- Cloud Run services have a request timeout that can be extended up to 60 minutes.
- Cloud Run Jobs support much longer task runtimes, up to 168 hours.
- Cloud Tasks is designed for asynchronous HTTP work and for controlling call rates to downstream services, including third-party APIs.
- Cloud Tasks waits for an HTTP response within the configured task timeout, and the maximum timeout for an HTTP task is 30 minutes. For longer work, Google explicitly recommends Cloud Run Jobs.
- Cloud Tasks queues use a token-bucket dispatch model. That means queues can burst if you let bucket depth grow, so `maxConcurrentDispatches` still matters even if `maxDispatchesPerSecond` is set.
- Cloud Tasks is at-least-once delivery. Duplicate task execution can happen, so all task handlers must be idempotent.
- Cloud Tasks supports private Cloud Run targets with OIDC tokens. The task-associated service account needs `roles/run.invoker` on the target service, and the code that enqueues tasks needs permission such as Cloud Tasks Enqueuer.
- Cloud Tasks named-task deduplication exists, but the dedupe window is only up to 24 hours and named tasks add overhead. It is useful as a secondary guard, not as the primary correctness mechanism.
- Firestore transactions are atomic, can be retried automatically on contention, and must not contain non-idempotent external side effects.
- Firestore is a good control plane for this use case. The current free tier remains 1 GiB storage, 50k reads/day, 20k writes/day, and 20k deletes/day.
- Cloud Storage supports streaming uploads when the final object size is not known ahead of time, and resumable uploads remain the robust option for large transfers.
- Cloud Run Jobs can mount Cloud Storage buckets, but the mount is Cloud Storage FUSE. The docs explicitly call out that FUSE does not provide file locking and has non-trivial write semantics and memory/performance caveats. It is best for path-based compatibility, not for multi-writer append-heavy coordination.
- OpenAlex now has API-key-based usage accounting and pricing. It returns cost and rate-limit information in response metadata and headers. If you exceed your daily limit or more than 100 requests per second, you receive `429 Too Many Requests`.
- Semantic Scholar recommends including the API key on every request and states that the introductory authenticated limit is 1 request per second across endpoints.

These constraints are why the recommended design uses:

- Cloud Run Jobs for long CPU-heavy stages
- Cloud Tasks for provider request orchestration
- private HTTP task handlers for fetch work
- Firestore only for control state
- GCS for raw provider payloads and durable artifacts

## 3. Recommendation Summary

The best-practice design for this repo is:

- Keep the existing public FastAPI endpoint as the user-facing submit API.
- Add one new private Cloud Run service for internal task handling. This service is the queue worker and controller.
- Keep Cloud Run Jobs for the long-running pipeline stages.
- Store run state in Firestore.
- Store manifests, raw provider shards, partial stage outputs, and final artifacts in GCS.
- Add a shared cross-run provider cache in GCS keyed by normalized query hash and schema version.
- Put all OpenAlex traffic behind one OpenAlex queue.
- Put all Semantic Scholar traffic behind one S2 queue, including the later recommendations expansion.
- Add a control queue for reconciliation and stage transitions.
- Split Phase F, because the recommendations expansion depends on stage-1 scoring that happens after the first retrieval wave.

The easy speedups the user asked for are valid and should be done:

- After the planner step, build OpenAlex queries and Semantic Scholar queries concurrently.
- Run OpenAlex and Semantic Scholar retrieval concurrently.

In the remodeled architecture, retrieval concurrency happens naturally because the provider queues run in parallel. In the current monolith, it can also be done as a short-term speedup with `asyncio.gather(...)`, but there are a few repo-specific caveats described below.

## 4. One Important Correction To The Originally Proposed Flow

The originally proposed flow was:

- submit
- preprocess
- queue OpenAlex and S2
- fetch both
- one barrier
- one postprocess

That is not fully correct for the current code if you keep the existing Semantic Scholar recommendation booster.

Why:

- The Phase F recommendation step chooses S2 seeds from the stage-1-scored candidates.
- Those seeds only exist after the first retrieval wave has already been normalized and scored.
- Therefore the pipeline needs a second S2 fetch wave after midprocess if recommendations remain enabled.

So the correct stage flow is:

1. submit
2. preprocess job
3. wave-1 provider fetch
4. wave-1 barrier
5. midprocess job
6. optional wave-2 S2 recommendations fetch
7. wave-2 barrier
8. finalize job

If you want a simpler first rollout, the clean fallback is:

- temporarily set `s2_neighbor_seed_count = 0`
- skip wave 2 in v1
- reintroduce recommendation expansion after the queue-based provider control plane is stable

## 5. Target Architecture

### 5.1 Components

Public service:

- `instantpaper-api`
- remains the user-facing submit endpoint
- no longer launches long-running work directly
- creates the run doc and enqueues one control task

Private worker service:

- recommended name: `instantpaper-qf-worker`
- private Cloud Run service, no unauthenticated access
- receives Cloud Tasks pushes
- owns task endpoints for:
  - reconcile
  - OpenAlex fetch units
  - Semantic Scholar fetch units

Cloud Run Job:

- continue using the existing two-lane job resource, but make it stage-aware
- recommended stage modes:
  - `preprocess`
  - `midprocess`
  - `finalize`

Cloud Tasks queues:

- `qf-control`
- `qf-openalex-fetch`
- `qf-s2-fetch`

Storage:

- Firestore = control plane
- GCS = artifacts, raw provider payloads, shared cache

### 5.2 State Machine

Recommended run stages:

- `queued`
- `preprocess_running`
- `wave1_fetching`
- `midprocess_running`
- `wave2_fetching`
- `finalize_running`
- `success`
- `error`
- `cancelled`

Wave 2 is skipped when recommendations are disabled or no valid S2 seeds are produced.

## 6. Easy Speedups To Implement

### 6.1 Parallel query building

This is a good change and it is low-risk if implemented carefully.

Current order in [services/two_lane_sources/runner.py](services/two_lane_sources/runner.py):

- planner
- OpenAlex query builder
- S2 query builder

Recommended change:

- keep the planner first
- then launch both provider query builders with `asyncio.gather(...)`

Repo-specific caveat:

- both query-builder functions independently call `load_metrics(...)` and `save_metrics(...)` in [services/two_lane_sources/pipeline.py](services/two_lane_sources/pipeline.py)
- if run concurrently as-is, they can race and overwrite each other's metrics changes

Recommendation:

- add a small metrics merge helper or an async lock around metrics writes for the parallel builder section
- keep provider-specific artifact files separate exactly as they are today, because those files already do not collide

### 6.2 Parallel retrieval

This is also a good change.

Current order in [services/two_lane_sources/runner.py](services/two_lane_sources/runner.py):

- fetch OpenAlex
- fetch S2

Short-term monolith speedup:

- replace the current sequential `asyncio.to_thread(...)` calls with `asyncio.gather(...)`
- keep the current provider-local retry and backoff logic

Repo-specific caveat:

- progress reporting currently assumes one active stage label at a time
- when both provider fetches run concurrently, progress should either:
  - use one combined stage label such as `phase_d_retrieval`, or
  - emit provider-specific sub-status in telemetry instead of overwriting the run doc stage back and forth

Long-term remodeled design:

- do not keep this as one process-level `gather`
- instead, let Cloud Tasks create the provider concurrency boundary across runs

## 7. Recommended Pipeline, Stage By Stage

### 7.1 Submit

The public API keeps the current endpoint contract:

- `POST /api/quellen-finder/sources-two-lane/start`

Recommended behavior:

1. validate user, project, chapter, and settings
2. acquire a transactional chapter-run lock in Firestore
3. create the run doc with immutable snapshots
4. enqueue one `qf-control` task for reconciliation
5. return `202 Accepted` immediately

Recommended change from current code:

- replace the current non-transactional `find_active_two_lane_run_for_kapitel(...)` plus `create_run(...)` flow with a single Firestore transaction using a dedicated lock doc keyed by chapter and run kind

Why:

- Firestore transactions are atomic
- the current implementation can race under concurrent starts

### 7.2 Preprocess job

The preprocess job should do only the parts that are long-running CPU/LLM work and do not depend on provider results.

Recommended contents:

- load the run doc and validate state
- load chapter snapshots and requested settings
- run the planner
- build OpenAlex queries and S2 queries concurrently
- normalize queries
- compute stable query hashes
- write:
  - planner output
  - provider query manifests
  - query-hash index
  - artifact manifest
  to GCS
- initialize wave-1 counters in Firestore
- enqueue provider fetch units into `qf-openalex-fetch` and `qf-s2-fetch`
- move run state to `wave1_fetching`

Recommended artifact outputs:

- `query_plan.json`
- `openalex_queries.json`
- `s2_bulk_queries.json`
- `artifact_manifest.json`

### 7.3 Wave 1 provider fetch

All provider tasks are HTTP tasks pushed by Cloud Tasks to the private worker service.

Recommended design principle:

- task unit = one bounded provider work unit
- not one whole run
- not one whole provider for the run

Best-practice unit:

- OpenAlex: one request/page unit using cursor continuation
- S2 bulk search: one request unit, with follow-up units for search-page continuation and batch detail fetches as needed

Why this is the best-practice unit size:

- it makes queue dispatch rate correspond to real downstream provider call rate
- it keeps each task safely inside Cloud Tasks' 30 minute maximum HTTP deadline
- it makes retries cheaper and more targeted

If this is too much for the first production cut, the acceptable simpler fallback is:

- query-sized tasks
- conservative `maxConcurrentDispatches`
- provider-local limiter kept in the handler

That simpler variant is still much better than the current whole-run design, but it is less exact than request-sized tasking.

### 7.4 Shared provider cache

The queue-based design should include a shared cross-run cache in GCS.

Recommended cache key:

- `provider`
- normalized query hash
- schema version
- provider request mode

Examples:

- `openalex/v1/<query_hash>.jsonl.gz`
- `s2-search/v1/<query_hash>.jsonl.gz`
- `s2-recommendations/v1/<seed_hash>_<limit>.jsonl.gz`

Why this is worth doing:

- it reduces provider rate pressure
- it reduces OpenAlex billable usage
- it reduces total latency for repeated topics and chapter reruns

This repo already has a stable query hash helper in [services/two_lane_sources/pipeline.py](services/two_lane_sources/pipeline.py), so this is a natural extension of the current code.

### 7.5 Wave 1 barrier and reconcile

Do not let individual provider tasks launch the next job directly based on ad-hoc checks.

Recommended pattern:

- provider tasks update Firestore counters and metadata only
- after each meaningful state change, enqueue or trigger a small reconcile task on `qf-control`
- the reconcile handler is the only place that decides whether the next stage should start

Recommended Firestore transaction behavior in reconcile:

- read the run doc
- check current state
- check whether the next stage is ready
- if ready and not yet claimed, atomically claim the transition
- commit
- only after the transaction succeeds, call the Cloud Run Jobs API

Why:

- Firestore transactions can retry
- external side effects must happen outside the transaction
- duplicate reconcile tasks are harmless if the state machine is idempotent

### 7.6 Midprocess job

This stage exists because Phase F recommendations cannot be decided until after the first retrieval wave has already been normalized and stage-1 scored.

Recommended contents:

- download or stream wave-1 raw provider shards from GCS
- reconstruct the aggregate raw JSONL files expected by the current pipeline, or teach Phase E to read manifest-driven GCS shards directly
- run Phase E
- split Phase F into an early part that:
  - sanitizes candidates
  - computes facet embeddings
  - computes chapter target embedding
  - computes metadata embeddings
  - computes stage-1 scores
  - selects S2 seeds
- if no seeds or recommendations disabled:
  - mark wave 2 as skipped
  - enqueue finalize
- otherwise:
  - write `s2_recommendation_seeds.json`
  - initialize wave-2 counters
  - enqueue wave-2 S2 fetch tasks on the same `qf-s2-fetch` queue
  - move state to `wave2_fetching`

This requires splitting [services/two_lane_sources/phase_f.py](services/two_lane_sources/phase_f.py) into:

- pre-recommendation Phase F
- post-recommendation Phase F

### 7.7 Wave 2 S2 recommendations fetch

All recommendation requests must flow through the same S2 queue as the earlier S2 search traffic.

Reason:

- the provider limit is shared
- the current code path in [services/two_lane_sources/phase_f.py](services/two_lane_sources/phase_f.py) uses the same provider and would otherwise bypass the new rate control plane

### 7.8 Finalize job

Recommended contents:

- download or stream the wave-2 recommendation artifacts if present
- merge recommendation papers
- finish the later half of Phase F
- run Phase G
- run Phase H
- run Phase I
- run Phase K
- write final results and telemetry to Firestore
- write final artifacts to GCS
- release the chapter-run lock

## 8. Why The Private Worker Service Is Better Than Reusing The Public API Service

You can technically put task endpoints on the public FastAPI service, but it is not the best operational design.

Reasons to prefer a separate private worker service:

- it isolates queue-driven background traffic from user-facing traffic
- it gives you separate scaling and concurrency knobs
- it avoids mixing public and internal endpoints on the same service revision
- it lets you keep provider API secrets only on the private worker, not on the public API service

Recommended deployment shape:

- public API service stays `--allow-unauthenticated`
- private worker service is deployed without unauthenticated access
- Cloud Tasks pushes to the private worker using OIDC

## 9. Firestore Control-Plane Schema

Recommended new run-doc fields:

```json
{
  "kind": "sources_two_lane",
  "status": "queued",
  "state": {
    "stage": "queued",
    "version": 2
  },
  "chapterLock": {
    "lockKey": "sources_two_lane:<kapitel_id>",
    "ownedByRunId": "<run_id>"
  },
  "artifacts": {
    "bucket": "<bucket>",
    "basePrefix": "quellen-finder-runs/<run_id>",
    "manifestUri": "gs://.../artifact_manifest.json",
    "queryPlanUri": "gs://.../query_plan.json",
    "openAlexQueriesUri": "gs://.../openalex_queries.json",
    "s2QueriesUri": "gs://.../s2_bulk_queries.json",
    "s2RecommendationSeedsUri": null
  },
  "wave1": {
    "openalex": {
      "planned": 0,
      "completed": 0,
      "failed": 0,
      "cacheHits": 0
    },
    "s2": {
      "planned": 0,
      "completed": 0,
      "failed": 0,
      "cacheHits": 0
    }
  },
  "midprocess": {
    "state": "pending",
    "executionName": null
  },
  "wave2": {
    "enabled": false,
    "planned": 0,
    "completed": 0,
    "failed": 0
  },
  "finalize": {
    "state": "pending",
    "executionName": null
  }
}
```

Recommended rule:

- keep Firestore as metadata and control state only
- never store large provider payloads in Firestore

## 10. GCS Artifact Layout

Recommended per-run prefix:

- `quellen-finder-runs/<run_id>/...`

Recommended layout:

- `.../manifests/query_plan.json`
- `.../manifests/openalex_queries.json`
- `.../manifests/s2_bulk_queries.json`
- `.../wave1/openalex/...`
- `.../wave1/s2/...`
- `.../wave2/s2_recommendations/...`
- `.../stage_e/...`
- `.../stage_f/...`
- `.../final/output.json`
- `.../final/metrics.json`

Recommended shared-cache prefix:

- `quellen-finder-cache/...`

Recommended write rule:

- each task writes its own object or shard
- do not have multiple tasks append to one shared mounted file

That rule avoids the Cloud Storage FUSE file-locking and write-behavior problems.

## 11. Rate-Limit Strategy

### 11.1 OpenAlex

Verified current OpenAlex behavior:

- API key recommended
- response headers expose usage status
- responses include `meta.cost_usd`
- `429` occurs if you exceed your daily limit or more than 100 requests per second

Operational recommendation:

- start well below 100 RPS
- treat OpenAlex daily budget as a real constraint, not just RPS
- add shared cache before raising dispatch rate
- log `X-RateLimit-*` headers and `meta.cost_usd` into telemetry

### 11.2 Semantic Scholar

Verified current Semantic Scholar behavior:

- use API key on every request
- introductory authenticated limit is 1 RPS

Operational recommendation:

- put both wave-1 S2 traffic and wave-2 recommendation traffic through the same queue
- start with `maxDispatchesPerSecond=1`
- start with `maxConcurrentDispatches=1`
- keep provider-local retry and `Retry-After` handling in the task handler

### 11.3 Cloud Tasks settings

Recommended queue set:

- `qf-control`
- `qf-openalex-fetch`
- `qf-s2-fetch`

Recommended initial settings:

- `qf-control`: low rate, low concurrency
- `qf-s2-fetch`: `1` dispatch per second, `1` concurrent dispatch
- `qf-openalex-fetch`: start conservatively and raise gradually only after measuring 429s, cost, and backlog

Important Cloud Tasks behavior:

- queues use token-bucket dispatch
- queues can burst
- new queues should be ramped carefully
- named tasks add overhead, so if you use fixed task names for best-effort dedupe, use a well-distributed hash prefix

## 12. IAM And Secret Boundaries

Recommended service accounts:

- `instantpaper-api-runtime`
- `instantpaper-qf-worker`
- `instantpaper-two-lane-job`
- `instantpaper-qf-task-invoker`

Recommended responsibilities:

- public API runtime:
  - Firestore access
  - control-queue enqueue permission
- private worker runtime:
  - Firestore access
  - GCS artifact access
  - provider API secrets
  - Cloud Tasks enqueue permission
  - Cloud Run Job execute permission
- job runtime:
  - Firestore access
  - GCS artifact access
  - OpenAI secret access
- task-invoker service account:
  - `roles/run.invoker` on the private worker service

Recommended secret placement:

- public API service:
  - no provider API secrets
- private worker service:
  - `OPENALEX_API_KEY`
  - `SEMANTICSCHOLAR_API_KEY`
  - `OPENALEX_EMAIL` if used
- Cloud Run Job:
  - `OPENAI_API_KEY`

This is better than the current monolith job because provider secrets no longer need to be present on stages that do not call those providers.

## 13. Repo Changes Required

### 13.1 Code

Files to update:

- [main.py](main.py)
- [services/quellen_finder_firestore_service.py](services/quellen_finder_firestore_service.py)
- [services/cloud_run_job_launcher.py](services/cloud_run_job_launcher.py)
- [services/two_lane_sources/runner.py](services/two_lane_sources/runner.py)
- [services/two_lane_sources/pipeline.py](services/two_lane_sources/pipeline.py)
- [services/two_lane_sources/phase_f.py](services/two_lane_sources/phase_f.py)
- [utils/config.py](utils/config.py)
- [requirements.txt](requirements.txt)
- [README.md](README.md)
- [backend/.env.example](.env.example)

New code recommended:

- a small artifact-store module for Quellen-Finder, likely extracted from or modeled after [services/pdf_scan/storage.py](services/pdf_scan/storage.py)
- a queue-enqueue helper
- a reconcile/controller module
- private task endpoints for OpenAlex fetch, S2 fetch, and reconcile
- a stage-aware worker entrypoint for preprocess, midprocess, and finalize

### 13.2 Dependencies

Add:

- `google-cloud-tasks`

### 13.3 Config

Recommended new env surface:

- `TWO_LANE_WORKER_SERVICE_NAME`
- `TWO_LANE_TASKS_LOCATION`
- `TWO_LANE_CONTROL_QUEUE_NAME`
- `TWO_LANE_OPENALEX_QUEUE_NAME`
- `TWO_LANE_S2_QUEUE_NAME`
- `TWO_LANE_TASK_INVOKER_SERVICE_ACCOUNT`
- `TWO_LANE_ARTIFACT_BUCKET`
- `TWO_LANE_ARTIFACT_PREFIX`
- `TWO_LANE_SHARED_CACHE_PREFIX`
- `TWO_LANE_FETCH_MAX_PROVIDER_CALLS_PER_TASK`
- `TWO_LANE_OPENALEX_RPS`
- `TWO_LANE_SEMANTICSCHOLAR_RPS`

Current gap:

- `PipelineConfig.from_env(...)` in [services/two_lane_sources/pipeline.py](services/two_lane_sources/pipeline.py) currently loads secrets, but not the provider RPS knobs you need for safe tuning

## 14. GitHub Actions And Deployment Changes

The current workflow in [../.github/workflows/deploy-backend.yml](../.github/workflows/deploy-backend.yml) already uses Workload Identity Federation. Any older doc that still talks about a raw JSON key is stale for the current repo state.

Recommended workflow changes:

1. keep building the backend image once
2. continue deploying `instantpaper-api`
3. deploy the new private worker service
4. continue deploying the stage-aware Cloud Run Job
5. create or update the three Cloud Tasks queues
6. bind `roles/run.invoker` on the private worker service to the task-invoker service account
7. inject provider secrets only into the private worker service
8. inject `OPENAI_API_KEY` only into the Cloud Run Job

Recommended queue deployment commands:

- `gcloud tasks queues create ...` when absent
- `gcloud tasks queues update ... --max-dispatches-per-second=... --max-concurrent-dispatches=...` on every deploy

Recommended service deployment:

- public API stays public
- private worker is deployed without unauthenticated access

## 15. Recommended Rollout Order

### Phase 0

Low-risk improvements first:

- add transactional chapter lock
- add env-driven provider throttling
- parallelize provider query building in the current monolith
- parallelize current retrieval in the current monolith
- add provider-header telemetry

### Phase 1

Introduce infrastructure:

- add GCS artifact store for Quellen-Finder
- add private worker service
- add Cloud Tasks queues
- add `google-cloud-tasks`
- move the public submit endpoint to enqueue one reconcile task instead of directly launching work

### Phase 2

Split the pipeline into:

- preprocess job
- wave-1 provider fetch
- midprocess job
- finalize job

At this stage, set `s2_neighbor_seed_count=0` if you want to reduce complexity for first release.

### Phase 3

Reintroduce or preserve recommendation expansion cleanly:

- split Phase F into pre-recommendation and post-recommendation halves
- add wave-2 S2 fetch through the same S2 queue

### Phase 4

Add shared cross-run provider cache and lifecycle cleanup.

## 16. Pros And Cons Of The Final Design

Pros:

- true cross-run provider protection
- queue-level control instead of uncontrolled job-level parallelism
- easy speedup from parallel independent stages
- lower OpenAlex usage cost because cache hits avoid paid calls
- cleaner secret boundaries
- stable frontend contract
- strong fit with the already-existing PDF scan split-stage pattern in this repo

Cons:

- more orchestration state
- more moving parts in deploy
- need strong idempotency on task handlers and reconcile logic
- Phase F must be split if recommendations remain enabled
- request-sized tasking is more work than simple query-sized tasking

## 17. Recommended Final Decision

I recommend this concrete direction:

- keep the current public submit endpoint
- add a private task-worker Cloud Run service
- use Cloud Tasks for provider work and reconcile work
- keep Cloud Run Jobs for preprocess, midprocess, and finalize
- make OpenAlex and S2 query generation parallel after the planner
- make provider retrieval parallel by queue orchestration
- route all S2 traffic, including recommendations, through the same queue
- add a shared GCS provider cache
- use Firestore transactions only for control-plane state transitions, never for large payloads

If you want the fastest safe first cut, the best staged compromise is:

- implement transactional locking
- parallelize the current monolith query-build and retrieval steps
- ship the queue-based wave-1 fetch control plane
- temporarily disable Phase F recommendations
- then add the second S2 wave in the next increment

## 18. Official Sources Checked

- Cloud Run request timeout: https://cloud.google.com/run/docs/configuring/request-timeout
- Cloud Run Job task timeout: https://cloud.google.com/run/docs/configuring/task-timeout
- Cloud Run async tasks with Cloud Tasks: https://cloud.google.com/run/docs/triggering/using-tasks
- Cloud Tasks overview: https://cloud.google.com/tasks/docs/dual-overview
- Cloud Tasks queue configuration: https://cloud.google.com/tasks/docs/configuring-queues
- Cloud Tasks quotas and dedupe window: https://cloud.google.com/tasks/docs/quotas
- Cloud Tasks scaling and named-task caveats: https://cloud.google.com/tasks/docs/manage-cloud-task-scaling
- Cloud Tasks HTTP target creation with OIDC: https://cloud.google.com/tasks/docs/creating-http-target-tasks
- Cloud Run Jobs execution and required roles: https://cloud.google.com/run/docs/execute/jobs
- Firestore transactions: https://cloud.google.com/firestore/docs/manage-data/transactions
- Firestore pricing and free tier: https://cloud.google.com/firestore/pricing
- Cloud Storage streaming uploads: https://cloud.google.com/storage/docs/streaming-uploads
- Cloud Run Cloud Storage volume mounts for jobs: https://cloud.google.com/run/docs/configuring/jobs/cloud-storage-volume-mounts
- OpenAlex authentication, pricing, usage headers, and limits: https://developers.openalex.org/api-reference/authentication
- Semantic Scholar API overview and limits: https://www.semanticscholar.org/product/api
