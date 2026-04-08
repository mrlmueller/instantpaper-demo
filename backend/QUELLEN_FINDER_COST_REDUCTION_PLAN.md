# Quellen-Finder Cost Reduction Plan

## Goal

Reduce Quellen-Finder runtime cost without changing functional behavior:

- same pipeline stages
- same provider logic
- same output quality target
- same user-visible workflow

This plan focuses on **where** and **with what resource shape** each stage runs, not on changing retrieval or scoring semantics.

## Scope

In scope:

- Cloud Run Job sizing
- Cloud Run Service sizing
- stage-specific deployment targets
- billing visibility
- discount programs
- cleanup hardening

Out of scope:

- changing provider query logic
- changing rerank/scoring logic
- changing the stage graph
- reducing provider result volume by changing business logic

## Current Baseline

### Observed runtime shape

Current deploy values from [deploy-backend.yml](<projektverzeichnis>/.github/workflows/deploy-backend.yml):

- `instantpaper-two-lane-sources` job:
  - `4 CPU`
  - `16 GiB`
  - all stages use the same job shape
- `instantpaper-two-lane-task-worker` service:
  - `2 CPU`
  - `1 GiB`
  - concurrency `2`
  - timeout `600s`
- `instantpaper-api` service:
  - `1 CPU`
  - `512 MiB`

### Measured March cost drivers

Based on the billing rows the user provided and local analysis artifacts:

- Cloud Run total in March 2026: about `10.18 €`
- Cloud Run jobs in `europe-west3`:
  - CPU: `4.66 €`
  - memory: `2.89 €`
  - subtotal: `7.55 €`
- request-based Cloud Run services:
  - CPU Tier 2: `2.26 €`
  - memory Tier 2: `0.12 €`
  - subtotal: about `2.38 €`

Derived from [two_lane_job_march_breakdown.json](<projektverzeichnis>/backend/.two_lane_artifacts/cloud_checks/two_lane_job_march_breakdown.json):

- `instantpaper-two-lane-sources` dominated by:
  - old monolithic/unknown runs: about `41%` of execution seconds
  - `finalize`: about `33%`
  - `preprocess`: about `20%`
  - `candidates`: about `5%`
  - `openalex_fetch + s2_fetch`: about `1%`

Derived from March 31 request logs:

- `instantpaper-two-lane-task-worker` handled about `1245` requests with about `41,931s` of total request latency on that day alone
- rough request-time cost for the worker on that day was about `1.66 €`
- `instantpaper-api` cost contribution from Quellen-Finder task routing was negligible by comparison

## Main Cost Problem

The current split pipeline is structurally correct, but it is still **overprovisioned**:

1. Every job stage currently pays for the same `4 CPU / 16 GiB` shape.
2. The task worker is sized like compute-heavy code, but most of its time is I/O, provider waits, and storage writes.
3. Cost visibility is still mostly estimated, not exact.
4. March still includes old monolithic and timeout-heavy runs that amplified cost.

The cheapest path is not to redesign the pipeline. The cheapest path is to **right-size each stage**.

## Recommended Plan

## Phase 0: Exact Cost Visibility

### Objective

Make future cost decisions with exact billing data instead of estimation.

### Actions

1. Enable **Cloud Billing export to BigQuery** for the billing account.
2. Export both:
   - standard usage cost table
   - detailed resource table `gcp_billing_export_resource_v1_*`
3. Add a small report script for:
   - cost by Cloud Run job stage
   - cost by Cloud Run service
   - cost per logical Quellen-Finder run

### Why first

Without billing export, exact billed cost per resource is not queryable from `gcloud` alone. Current scripts can estimate, but not reconcile perfectly with invoice totals.

### Success criteria

- exact cost for:
  - `instantpaper-two-lane-sources`
  - `instantpaper-two-lane-task-worker`
  - `instantpaper-api`
- exact cost per day and per run cohort

## Phase 1: Split `instantpaper-two-lane-sources` into Stage-Specific Jobs

### Objective

Keep the pipeline identical but stop paying `4 CPU / 16 GiB` for lightweight stages.

### Current issue

Today all stages run on the same job definition:

- `preprocess`
- `openalex_fetch`
- `s2_fetch`
- `candidates`
- `finalize`

That is wasteful because `fetch` and `candidates` do not need the same resources as `finalize`.

### New job set

Create separate Cloud Run Jobs:

1. `instantpaper-two-lane-preprocess`
2. `instantpaper-two-lane-openalex-fetch`
3. `instantpaper-two-lane-s2-fetch`
4. `instantpaper-two-lane-candidates`
5. `instantpaper-two-lane-finalize`

### Recommended initial sizing

These values are chosen to be conservative, not maximal savings on day one.

1. `preprocess`
- start at `2 CPU / 8 GiB`
- expected saving vs current stage: about `50%`

2. `openalex_fetch`
- start at `1 CPU / 1 GiB`
- this stage mostly seeds provider work and exits

3. `s2_fetch`
- start at `1 CPU / 1 GiB`
- same reasoning as OpenAlex fetch

4. `candidates`
- start at `1 CPU / 2 GiB` or `1 CPU / 4 GiB`
- this stage is short and light in current data

5. `finalize`
- start at `2 CPU / 8 GiB`
- this is the heaviest split stage and should be reduced more cautiously

### Why this is the highest-ROI change

March data shows the meaningful job cost comes from:

- `finalize`
- `preprocess`
- old monolithic runs

`openalex_fetch` and `s2_fetch` are already a tiny share of job spend.

### Expected savings

Rough order of magnitude, assuming runtime stays broadly similar:

- `preprocess`: save about `40-50%`
- `finalize`: save about `35-50%`
- `candidates`: save about `50-75%`

Combined expected savings from stage-specific jobs:

- about `2.0 €` to `3.0 €` per month at the current March usage level
- more if testing volume continues to be high

## Phase 2: Shrink the Task Worker Service

### Objective

Lower request-based service cost without changing task semantics.

### Current issue

`instantpaper-two-lane-task-worker` currently runs at:

- `2 CPU`
- `1 GiB`
- concurrency `2`

But its work is mostly:

- provider HTTP
- retries
- rate-limit waits
- page artifact writes

This is not a `2 CPU` workload most of the time.

### Recommended rollout

1. Step down to:
- `1 CPU`
- `512 MiB`
- concurrency `2`

2. Re-run cloud concurrency tests.

3. If stable, test:
- `0.5 CPU`
- `512 MiB`
- concurrency `1` or `2`

### Why not go directly to minimum

The worker still performs Python JSON work, storage I/O, and retries. The safe path is to reduce in two steps.

### Expected savings

Compared with `2 CPU / 1 GiB`:

- `1 CPU / 512 MiB` cuts the dominant service cost materially
- if stable, `0.5 CPU / 512 MiB` can cut it even further

Based on the measured March 31 request profile, the worker alone likely offers the largest service-side savings lever.

## Phase 3: Keep API Service Cheap and Isolated

### Objective

Make sure `instantpaper-api` stays a thin control plane and does not inherit expensive worker behavior again.

### Actions

1. Keep all provider task handling on the dedicated worker service.
2. Do not move provider task execution back onto `instantpaper-api`.
3. Keep `instantpaper-api` at the current small shape unless app latency proves otherwise.

### Expected savings

No direct big savings, but this prevents reintroducing the previous blended service cost problem.

## Phase 4: Introduce Cloud Run CUDs Only After Sizing Stabilizes

### Objective

Use discounts only after the new baseline is stable.

### Why later

If commitments are purchased before right-sizing, you can lock in the wrong spend profile.

### Relevant Google policy

According to Google Cloud documentation:

- Cloud Run jobs and Cloud Run services with instance-based billing are eligible for higher compute flexible CUD rates
- Cloud Run services with request-based billing are eligible for lower discount treatment depending on the model

### Recommendation

After 2-4 weeks of stable usage on the new sizing:

1. measure average monthly spend for:
   - stage jobs
   - task worker
2. if usage is steady enough, evaluate:
   - `1-year` compute flexible CUD first
   - only for the stable portion of the spend

### Expected savings

Potentially meaningful, but only after resource right-sizing is done first.

## Phase 5: Optional Lower-Cost Compute Target for Heavy Stages

### Objective

Have a second cost lever if Cloud Run remains too expensive after right-sizing.

### Candidate

Move only the heavy stages to a cheaper batch target while keeping the same pipeline graph:

- `preprocess`
- `finalize`

Potential targets:

- Google Batch
- Compute Engine Spot-backed batch execution

### Why only optional

This keeps semantics the same, but adds operational complexity:

- image management
- retries
- preemption handling
- monitoring

### When to consider it

Only if, after Phases 1-4:

- runtime cost is still too high
- and Cloud Run simplicity is no longer worth the premium

### Risk

Higher ops burden. This should not be the first move.

## Suggested Rollout Order

1. Enable Billing export to BigQuery.
2. Split the single two-lane job into stage-specific jobs.
3. Resize jobs conservatively:
   - preprocess: `2 CPU / 8 GiB`
   - openalex_fetch: `1 CPU / 1 GiB`
   - s2_fetch: `1 CPU / 1 GiB`
   - candidates: `1 CPU / 2-4 GiB`
   - finalize: `2 CPU / 8 GiB`
4. Re-run:
   - 1 cloud run
   - 3 concurrent cloud runs
   - 5 concurrent cloud runs
5. Shrink worker to `1 CPU / 512 MiB`.
6. Re-run the same cloud tests.
7. If stable, test worker at `0.5 CPU / 512 MiB`.
8. After 2-4 weeks, evaluate CUDs.
9. Only if needed, consider Batch / Spot for heavy stages.

## Validation Matrix

For every sizing change, rerun:

1. one single cloud sanity run
2. three concurrent runs
3. five concurrent runs
4. compare:
   - success rate
   - wall-clock runtime
   - OpenAlex/S2 queue drain behavior
   - result count
   - final stage timing
   - cost per logical run

Reject a change if it causes:

- higher timeout rate
- materially worse wall-clock runtime
- memory kills
- result drift

## Recommended First Implementation

If the goal is highest savings for lowest engineering risk, do exactly this first:

1. create separate Cloud Run Jobs per stage
2. set:
   - preprocess: `2 CPU / 8 GiB`
   - finalize: `2 CPU / 8 GiB`
   - candidates: `1 CPU / 2 GiB`
   - openalex_fetch: `1 CPU / 1 GiB`
   - s2_fetch: `1 CPU / 1 GiB`
3. reduce task worker to:
   - `1 CPU / 512 MiB`
   - concurrency `2`
4. enable Billing export

This preserves the exact pipeline behavior and should yield the biggest immediate cost drop.

## Sources

- Cloud Run pricing: https://cloud.google.com/run/pricing
- Cloud Billing export to BigQuery: https://cloud.google.com/billing/docs/how-to/export-data-bigquery-tables
- Cloud Run jobs CPU limits: https://cloud.google.com/run/docs/configuring/jobs/cpu
- Cloud Run jobs memory limits: https://cloud.google.com/run/docs/configuring/jobs/memory-limits
- Cloud Run services CPU limits: https://cloud.google.com/run/docs/configuring/services/cpu
- Compute flexible CUDs for Cloud Run: https://docs.cloud.google.com/compute/docs/instances/committed-use-discounts-overview
- Spot VMs: https://docs.cloud.google.com/compute/docs/instances/spot
