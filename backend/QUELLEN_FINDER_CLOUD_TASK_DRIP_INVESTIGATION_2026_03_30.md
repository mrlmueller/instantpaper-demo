# Quellen-Finder Cloud Tasks Drip Investigation

Date: 2026-03-30

## Summary

The current Cloud Tasks behavior is not a queue-configuration bug.

The deployed split pipeline currently seeds only the first provider page task for each query during
`openalex_fetch` and `s2_fetch`. Every later provider page task is created only after the previous
page task completes and discovers a `next_cursor` or `next_token`.

This causes task creation to "drip" across the whole provider-fetch window instead of enqueueing the
complete provider workload at the start of the stage.

## Code Path

- Seed stage:
  - `services/two_lane_sources/provider_tasks.py`
  - `seed_openalex_provider_tasks()`
  - `seed_s2_provider_tasks()`
- Recursive follow-up enqueue:
  - `services/two_lane_sources/provider_tasks.py`
  - `process_openalex_page_task()`
  - `process_s2_bulk_page_task()`
- Split job stage entry:
  - `services/quellen_finder_sources_two_lane_job.py`

Current behavior:

1. `openalex_fetch` creates one task per OpenAlex query for page 1 only.
2. `s2_fetch` creates one task per Semantic Scholar query for page 1 only.
3. Each completed provider page task inspects the response for `next_cursor` / `next_token`.
4. If another page exists, the task enqueues exactly one successor page task.
5. This repeats until pagination ends.

## Live Evidence

Artifact:

- `.two_lane_artifacts/cloud_checks/cloud_task_growth_qf_cloud_test_49140fee_01.json`

Observed live run:

- user: `KuMXKLtex9aHHDhCpYqLHImlv3H2`
- project: `qf-cloud-test-49140fee-01`
- run: `qf-cloud-test-run-49140fee-01`

Key numbers:

- OpenAlex:
  - seeded initially: `15`
  - total task docs created: `298`
  - created after seed: `283`
  - task creation span: `3194.725s`
  - max page index seen: `211`
- Semantic Scholar:
  - seeded initially: `17`
  - total task docs created: `327`
  - created after seed: `310`
  - task creation span: `4882.91s`
  - max page index seen: `287`

Interpretation:

- The queue did not receive the full provider workload up front.
- Most tasks were created later by already-running provider tasks.

## Cloud Run Job Logs

Observed log lines from the split fetch stage:

- OpenAlex:
  - `pending_tasks=15 seeded=15`
- Semantic Scholar:
  - `pending_tasks=17 seeded=17`

This matches the seed functions: only page-1 tasks are created during the fetch-stage job.

## Local Regression

Artifact:

- `.two_lane_artifacts/rate_limit_tests/test_two_lane_provider_recursive_enqueue_latest.json`

Script:

- `scripts/test_two_lane_provider_recursive_enqueue.py`

Results:

- OpenAlex:
  - queue size after seed: `1`
  - queue size after first task: `1`
  - `enqueuedTasks` after first task: `2`
- Semantic Scholar:
  - queue size after seed: `1`
  - queue size after first task: `1`
  - `enqueuedTasks` after first task: `2`

Interpretation:

- The recursive enqueue pattern is deterministic and local.
- It is not caused by Cloud Tasks itself.

## Queue Configuration Check

Live queue config is sane and consistent with the intended provider limits:

- `quellen-finder-openalex`
  - `maxDispatchesPerSecond=5`
  - `maxConcurrentDispatches=5`
- `quellen-finder-semanticscholar`
  - `maxDispatchesPerSecond=1`
  - `maxConcurrentDispatches=1`

This is not the primary cause of the "tasks trickle in over time" symptom.

## Important Constraint

At the current page-task granularity, the system cannot enqueue all provider page tasks up front,
because later pages depend on provider-issued pagination state:

- OpenAlex later pages depend on `next_cursor`.
- Semantic Scholar later pages depend on `next_token`.

Those values do not exist before the previous provider response returns.

## Why The Current Architecture Feels Wrong

Operationally, the current design creates the appearance of a constantly refilling queue:

- the split fetch jobs seed only the first page for each query
- page tasks keep spawning more page tasks
- queue depth and task creation stay active throughout provider retrieval

That is why Cloud Tasks appears to be "coming in here and there over and over again".

## Recommended Fix

Change provider work from "one task per page" to "one task per query chain".

Recommended new behavior:

1. `openalex_fetch` enqueues one task per OpenAlex query.
2. `s2_fetch` enqueues one task per Semantic Scholar query.
3. Each query task loops internally through all pages for its query, respecting the shared provider
   rate limiter on every outbound request.
4. No recursive task creation is used for normal pagination.

Benefits:

- all provider tasks are created at the start of the fetch stage
- Cloud Tasks represents the known workload immediately
- queue activity becomes predictable
- Firestore task-doc growth drops from hundreds of page tasks to roughly query-count scale
- the system better matches the intended architecture

## Follow-Up Work

Implementation should update:

- `services/two_lane_sources/provider_tasks.py`
- `services/two_lane_sources/internal_tasks.py`
- provider task tests and orchestration tests

Additional tests to keep:

- local regression proving full query-task seeding
- retry and cancel tests on query tasks
- live cloud sanity run confirming initial seeded task count matches final task-doc count

