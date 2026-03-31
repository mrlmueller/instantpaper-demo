# Quellen-Finder Cloud Task Slowdown Investigation

Date: 2026-03-31

## Scope

Investigate why the deployed Quellen-Finder split pipeline is taking more than 2.5 hours on GCP when comparable local runs are around 1 hour.

Focus:

- Cloud Tasks behavior
- Cloud Run task-handler behavior
- current task granularity and queue configuration
- whether Cloud Tasks can be made fast enough in the current design
- what should be changed next

## Live Evidence Captured

Diagnostic artifact:

- `.two_lane_artifacts/cloud_checks/cloud_task_slowdown_analysis_20260331.json`

Live deployment snapshot from that artifact:

- Cloud Run service: `instantpaper-api`
- revision: `instantpaper-api-00134-phq`
- request timeout: `300s`
- container concurrency: `80`
- CPU limit: `1000m`
- max scale: `20`

Queue config:

- `quellen-finder-openalex`
  - `maxDispatchesPerSecond=5`
  - `maxConcurrentDispatches=10`
  - retries: `minBackoff=5s`, `maxBackoff=300s`, `maxAttempts=25`
- `quellen-finder-semanticscholar`
  - `maxDispatchesPerSecond=1`
  - `maxConcurrentDispatches=5`
  - retries: `minBackoff=5s`, `maxBackoff=300s`, `maxAttempts=25`

Current provider-task config:

- `TWO_LANE_PROVIDER_TASK_MAX_RUNTIME_S=900`
- `TWO_LANE_OPENALEX_TASK_MAX_PAGES_PER_TASK=100`
- `TWO_LANE_SEMANTICSCHOLAR_TASK_MAX_PAGES_PER_TASK=25`

Observed request latency on the current revision for the internal task endpoint:

- `202` responses:
  - count: `49`
  - `p50=162.33s`
  - `p90=288.19s`
  - `p95=291.05s`
  - `p99=298.27s`
  - max: `298.27s`
- `504` responses:
  - count: `60`
  - almost all at `~300.00s` exactly

Interpretation:

- successful task handlers are already running right up against the `300s` Cloud Run service timeout
- a large fraction of task attempts cross that line and fail with `504`
- the slow behavior is primarily retry-driven, not only queue-dispatch-driven

## Direct Cloud Task Evidence

One live task that was repeatedly timing out:

- queue: `quellen-finder-openalex`
- task: `oaq-ab5e43fc6418b4abf928b376-0005`
- kind: `openalex_query`
- run: `qf-cloud-check-run-642d2067-01`
- segment index: `5`
- start page index: `177`
- dispatch count observed: `11+`
- response status: `DEADLINE_EXCEEDED(4): HTTP status code 504`

The payload showed that this was not a one-page task. It was a long query-chain continuation task, already deep into pagination.

That task was part of an earlier temporary cloud sanity run and was cleaned up during this investigation:

- deleted from Cloud Tasks
- deleted the Firestore run/project docs
- verified no remaining GCS objects under `two-lane-runs/qf-cloud-check-run-642d2067-01`

## Official Google Cloud Documentation That Matches The Live Behavior

### Cloud Run request timeout

Cloud Run documents that:

- if a response is not returned within the configured request timeout, the network connection is closed and `504` is returned
- the container instance is not necessarily terminated
- the code may keep processing and interfere with other requests
- request timeout for services can be set from `1` to `3600` seconds

Source:

- `https://docs.cloud.google.com/run/docs/configuring/request-timeout`
  - lines `584-585`
  - lines `626-646`

### Cloud Tasks dispatch deadline vs service timeout

Cloud Tasks documents that:

- for HTTP tasks, `dispatch_deadline` can be `15s` to `30m`
- if the worker does not respond by the deadline, the attempt is marked `DEADLINE_EXCEEDED` and retried
- regardless of `dispatch_deadline`, the app handler will not run longer than the target service timeout
- Cloud recommends setting `dispatch_deadline` only a few seconds above the app handler timeout

Source:

- `https://docs.cloud.google.com/tasks/docs/reference/rpc/google.cloud.tasks.v2`
  - lines `1601-1609`

### Cloud Tasks retry behavior

Cloud Tasks documents the retry backoff progression and retry attempt behavior.

Source:

- `https://docs.cloud.google.com/tasks/docs/reference/rpc/google.cloud.tasks.v2`
  - lines `1478-1527`

### Cloud Tasks scaling behavior

Cloud Tasks documents that:

- queues ramp up dispatch gradually, especially when new or cold
- sudden traffic spikes can reduce dispatch rate
- named tasks add significant performance overhead

Source:

- `https://docs.cloud.google.com/tasks/docs/manage-cloud-task-scaling`
  - lines `131-162`
  - lines `203-205`

### Cloud Run concurrency guidance

Cloud Run documents that:

- default concurrency is often `80`
- if code cannot process parallel requests well, concurrency should be lowered, potentially to `1`
- starting with lower concurrency such as `8` is recommended when high concurrency can cause resource constraints or unintended behavior

Source:

- `https://docs.cloud.google.com/run/docs/about-concurrency`
  - lines `588-592`
  - lines `603-610`
  - lines `611-627`

## Root Cause

This is not one single bug. It is a combination of five design mismatches.

### 1. The task handler is longer than the target service timeout

The Cloud Task dispatcher is configured with:

- `dispatch_deadline=1800s`

But the actual target service is configured with:

- `timeoutSeconds=300`

So Cloud Tasks may wait up to 30 minutes, but Cloud Run closes the request after 5 minutes.

Result:

- task attempt gets `504`
- Cloud Tasks retries
- total run time stretches dramatically

### 2. Task granularity is still too large for the configured provider limits

Current configured bounds:

- OpenAlex:
  - `100` pages per task
  - `1` provider call per page
  - queue concurrency `10`
  - provider rate `5 rps`
- Semantic Scholar:
  - `25` pages per task
  - about `2` provider calls per page (`bulk` + `batch`)
  - queue concurrency `5`
  - provider rate `1 rps`

Simple lower-bound model under saturation:

- OpenAlex:
  - `100 calls * 10 concurrent / 5 rps = 200s`
- Semantic Scholar:
  - `50 calls * 5 concurrent / 1 rps = 250s`

These are optimistic lower bounds before:

- network latency
- GCS writes
- Firestore updates
- retry backoff
- Python overhead

That matches the live evidence extremely well:

- successful tasks p95 is already around `291s`
- many tasks cross `300s` and fail

### 3. The shared rate limiter sleeps inside the HTTP task handler

The current worker code calls the shared provider rate limiter inside the running HTTP request and uses blocking `time.sleep(...)` during backoff and rate-limit waits.

Result:

- a task can occupy a Cloud Tasks dispatch slot while doing no external work
- a task can occupy a Cloud Run request slot while waiting
- queue concurrency is consumed by sleeping work

This is one reason the queue feels slow even when it is technically dispatching.

### 4. The task target is the public API service

Cloud Tasks currently targets:

- `instantpaper-api`

That service also serves user-facing traffic and is configured as:

- `1 vCPU`
- concurrency `80`

The internal task route is an `async` FastAPI endpoint, but the provider work inside it is blocking:

- synchronous `requests`
- blocking `time.sleep(...)`
- blocking artifact writes

This is a poor fit for a public API revision with high request concurrency.

### 5. The desire to “enqueue all pagination work up front” is not achievable

For later provider pages, the pagination state is only known after the previous provider response returns:

- OpenAlex later pages need `next_cursor`
- Semantic Scholar later pages need `next_token`

So it is not possible to create every future page task at the start of the fetch stage.

The best possible model is:

- enqueue every initial query task up front
- keep continuation tasks bounded and relatively short

## What Is Not The Main Problem

These are secondary, not primary:

- queue creation itself
- queue rate-limit configuration syntax
- provider API keys being absent
  - this was a real earlier problem, but it is not the main reason for the current 2.5h behavior anymore
- named task overhead
  - still real per docs, but not large enough to explain the current `300s` timeout pattern by itself

## Can Cloud Tasks Be Fast Enough Here?

Yes, but not with the current task shape.

Cloud Tasks can work for this pipeline if:

- the handler is short enough to complete comfortably below the service timeout
- the target is a worker-appropriate service, not the public API revision
- continuation tasks are bounded tightly enough that p95 stays far from the timeout

Cloud Tasks is not the bottleneck by itself. The current task duration is.

## Recommended Changes

### Recommendation A: Fix the current Cloud Tasks architecture instead of abandoning it

This is the most practical next step.

1. Move the task target off the public API service.

Create a dedicated worker service, for example:

- `instantpaper-two-lane-task-worker`

Suggested initial settings:

- request timeout: `600s` or `900s`
- concurrency: `1` to `4`
- CPU: `2`
- memory: `1Gi` or higher if needed

Why:

- isolates long provider work from user-facing API traffic
- allows a worker-specific timeout and concurrency policy
- makes debugging much cleaner

2. Reduce continuation segment size substantially.

Suggested starting values:

- OpenAlex:
  - `10-15` pages per task
- Semantic Scholar:
  - `4-6` pages per task

Why:

- with current provider rates, these bounds should push task p95 much lower
- fewer retries
- more predictable queue behavior

3. Lower queue concurrency to match actual useful parallelism.

Suggested starting values:

- OpenAlex queue concurrency: `5`
- Semantic Scholar queue concurrency: `2`

Why:

- with a shared global rate limiter, extra concurrency mostly creates more waiting tasks
- lowering concurrency reduces the number of sleeping handlers occupying request slots

4. Align `dispatch_deadline` with the worker timeout.

If the worker timeout is `600s`, use a dispatch deadline only slightly above it, for example:

- `630s`

This matches Google’s recommendation and makes retry semantics easier to reason about.

5. Add structured logs to every task.

At minimum:

- task kind
- provider
- run id
- query hash
- segment index
- start page
- end page
- pages processed
- provider calls made
- total sleep time from rate limiting
- total sleep time from backoff
- total wall time
- whether continuation was enqueued

Without these logs, diagnosis is too expensive.

### Recommendation B: If you want even less idle worker time

If the requirement is very strict that handlers should not spend much time waiting inside requests, the only way forward is to make the task unit smaller again.

That means:

- one task does only a small page bundle
- continuation tasks are expected and normal

You cannot have all three at once:

- all future pagination tasks known up front
- no continuation tasks
- no long-lived waiting handlers

Because later pagination state is unknown until the provider answers.

### Recommendation C: Do not point Cloud Tasks directly at the public API for long provider work

Even if the timeout is raised, this remains a bad operational fit.

If the dedicated worker service still behaves poorly, the next alternative to evaluate is:

- Cloud Tasks only enqueues short “launch work” messages
- a dedicated worker service or worker pool pulls and executes provider segments

I would not recommend switching provider query segments back to Cloud Run Jobs immediately, because job startup overhead and job lifecycle cost would become a new bottleneck.

## Concrete Next-Step Settings To Try

If the goal is to get the current design into an acceptable state quickly:

- create dedicated task-worker service
- set worker timeout to `600s`
- set worker concurrency to `2`
- set OpenAlex queue concurrency to `5`
- set S2 queue concurrency to `2`
- set `TWO_LANE_OPENALEX_TASK_MAX_PAGES_PER_TASK=12`
- set `TWO_LANE_SEMANTICSCHOLAR_TASK_MAX_PAGES_PER_TASK=5`
- set task `dispatch_deadline` to about `630s`
- add structured per-task logs before retesting

That is the most defensible next experiment.

## Temporary Artifacts Created During This Investigation

Code:

- `scripts/analyze_two_lane_cloud_task_slowdown.py`

Artifacts:

- `.two_lane_artifacts/cloud_checks/cloud_task_slowdown_analysis_20260331.json`

Temporary production run cleaned up:

- project: `qf-cloud-check-642d2067-01`
- run: `qf-cloud-check-run-642d2067-01`

Cleanup verification:

- OpenAlex queue empty after deletion
- project doc deleted
- run doc deleted
- no GCS objects found under `two-lane-runs/qf-cloud-check-run-642d2067-01`

No new temporary Cloud Run services, Cloud Run jobs, or Cloud Tasks queues were created in this investigation.
