# Quellen-Finder Distributed Rate Limit Plan

## Goal

Make provider throttling for Quellen-Finder globally correct across:

- multiple concurrent Cloud Run job executions
- multiple concurrent local runs
- both OpenAlex and Semantic Scholar call paths
- both Phase D retrieval and the extra Semantic Scholar recommendation calls in Phase F

The immediate target is shared global rate limiting without changing the pipeline into a multi-service queue architecture yet.

## Why This Approach First

The current code only rate-limits per process. That means each Cloud Run job independently respects `openalex_rps` and `semanticscholar_rps`, but many jobs together can still exceed provider limits.

For a first production-safe fix, the best tradeoff is:

- keep the current single-job pipeline structure
- insert one shared provider limiter behind the existing HTTP request path
- back that limiter with Firestore transactions so it works in both local and cloud environments

This is smaller and safer than a full Cloud Tasks refactor, and it directly addresses the current production failure mode.

## Non-Goals For This Increment

- no split-stage Cloud Tasks fan-out yet
- no new GCS artifact handoff for Quellen-Finder yet
- no new bucket temp data in this increment

Because this increment does not introduce GCS temporary artifacts for Quellen-Finder, there is no new bucket cleanup path to add here. Bucket cleanup remains part of the later orchestration refactor if we move raw provider payloads into GCS.

## Current Code Paths To Cover

### Phase D OpenAlex retrieval

- `backend/services/two_lane_sources/pipeline.py`
- `fetch_openalex_to_cache(...)`

### Phase D Semantic Scholar retrieval

- `backend/services/two_lane_sources/pipeline.py`
- `fetch_s2_to_cache(...)`

### Phase F Semantic Scholar recommendations

- `backend/services/two_lane_sources/phase_f.py`
- `s2_recommendations_expand(...)`

## Design

### Shared reservation model

Use one Firestore document per provider:

- `quellenFinderProviderRateLimits/openalex`
- `quellenFinderProviderRateLimits/semanticscholar`

Each document stores:

- `nextAllowedAtEpochMs`
- `minIntervalMs`
- `updatedAtEpochMs`
- `lastHolder`
- `lastStage`
- `lastRunId`
- `reservationCount`
- `lastReservedAtEpochMs`

### Reservation algorithm

For each outgoing provider request:

1. start a Firestore transaction
2. read the provider limiter document
3. compute `reservedAtMs = max(nowMs + dispatchBufferMs, nextAllowedAtEpochMs)`
4. compute `newNextAllowedAtMs = reservedAtMs + minIntervalMs`
5. write the new values back in the same transaction
6. sleep until `reservedAtMs` if needed
7. execute the HTTP request

This creates one globally serialized request schedule per provider across all workers.

### Why the dispatch buffer is necessary

Without a small dispatch buffer, the Firestore round trip itself can compress the actual on-wire request gaps even when the reservation timestamps are correct. This showed up in the fake-server integration tests for the Firestore backend. The dispatch buffer fixes that by moving the first reservation in a burst slightly into the future so the actual HTTP send times still preserve the target spacing.

### Why this is sufficient

- OpenAlex and S2 each need their own independent schedule
- concurrency across many workers collapses into one shared request stream per provider
- Firestore transactions automatically retry on contention
- server-side Firestore transactions are suitable for this because the contention point is a single provider document

## Configuration

Add to `PipelineConfig`:

- `provider_rate_limit_backend`: `firestore` or `local`
- `provider_rate_limit_collection`: Firestore collection name
- `provider_rate_limit_max_future_ms`: corruption recovery guard
- `provider_rate_limit_dispatch_buffer_ms`: safety buffer between reservation and wire dispatch

Default behavior:

- use `firestore` by default in both local and cloud runs
- allow explicit local override to `local` for deterministic offline tests

## Implementation Phases

### Phase 0. Write the plan and lock scope

- add this plan file
- keep the change focused on shared throttling only

### Phase 1. Add shared limiter module

Create a new module:

- `backend/services/two_lane_sources/provider_rate_limit.py`

Contents:

- `ProviderRateLimitReservationStore` protocol or base interface
- `InMemoryProviderRateLimitStore`
- `FirestoreProviderRateLimitStore`
- `SharedProviderRateLimiter`
- helper factory to build the right limiter from config

Rules:

- `acquire()` must expose the same behavior needed by the existing request path
- Firestore store must recover if `nextAllowedAtEpochMs` is implausibly far in the future
- per-provider keys must be independent
- local test runs must share one in-process store per collection so concurrent workers actually contend on the same limiter

### Phase 2. Wire Phase D request path

Update:

- `backend/services/two_lane_sources/pipeline.py`

Changes:

- replace local `RateLimiter` construction in `fetch_openalex_to_cache(...)`
- replace local `RateLimiter` construction in `fetch_s2_to_cache(...)`
- keep `request_json(...)` as the single throttled request gateway

### Phase 3. Wire Phase F S2 recommendations

Update:

- `backend/services/two_lane_sources/phase_f.py`

Changes:

- remove direct `time.sleep(1 / semanticscholar_rps)` throttling
- replace custom backoff-only request logic with the shared request path and shared S2 limiter
- ensure recommendation calls and Phase D bulk retrieval share the same S2 provider schedule

### Phase 4. Add deterministic tests

Add custom Python test scripts with no network dependency for core behavior.

Planned tests:

1. single-provider monotonic reservations in memory
2. concurrent reservations in memory across many threads
3. provider independence: OpenAlex does not block S2
4. stale-future recovery guard
5. `request_json(...)` throttling using a local fake HTTP server and a shared in-memory limiter
6. Phase F request path uses the shared limiter instead of raw sleep spacing

### Phase 5. Add Firestore integration tests

Add optional live tests that use the real Firestore backend and clean up after themselves.

Planned tests:

1. concurrent reservations from multiple local worker threads using Firestore
2. verify spacing is globally serialized for one provider document
3. verify OpenAlex and S2 documents move independently
4. verify cleanup removes the test limiter docs after the test

### Phase 6. Add pipeline-level smoke tests

Planned tests:

1. synthetic multi-run local stress test against a fake provider server
2. local Quellen-Finder retrieval smoke using saved queries and the shared limiter
3. optional real-provider smoke with small sampled query sets and low concurrency

### Phase 7. Review and deploy readiness

Before shipping:

- grep for remaining direct `time.sleep(1 / ...rps)` usage in Quellen-Finder provider paths
- inspect logs for reservation ordering
- verify default config works in Cloud Run without extra secrets
- verify local fallback behavior

## Validation Matrix

The implementation should be considered ready only if all of these pass:

1. standalone reservation tests with the in-memory backend
2. standalone reservation tests with the Firestore backend
3. fake-server integration for Phase D using the local backend
4. fake-server integration for Phase D using the Firestore backend
5. fake-server integration for Phase F using the local backend
6. fake-server integration for Phase F using the Firestore backend
7. existing query-builder regression suite
8. at least one real-provider spot check after the change

## Test Philosophy

This change is deceptively simple and easy to get wrong. Tests must prove:

- correctness under contention
- correctness of per-provider isolation
- no hidden bypass in Phase F
- no pathological future-lock condition
- no dependency on Cloud Run only

## Rollout Order

1. land the shared limiter module
2. land Phase D integration
3. land Phase F integration
4. run deterministic tests
5. run Firestore integration tests
6. run local smoke tests
7. deploy to Cloud Run

## Expected Outcome

After this increment:

- concurrent jobs should no longer amplify provider request rate
- both local and cloud executions should share the same provider schedule when Firestore is enabled
- the current lint/query-builder fix remains unchanged
- the later Cloud Tasks refactor remains possible, but is no longer required to stop the immediate rate-limit failures
