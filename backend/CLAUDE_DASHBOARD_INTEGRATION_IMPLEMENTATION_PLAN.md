# Claude Dashboard Integration Implementation Plan

Status: approved planning document

Prepared on: 2026-04-10

Scope: add Anthropic Claude support to all dashboard LLM operations while preserving the current OpenAI path and the existing credits system.

## 1. Goals

- Add first-class support for `claude-sonnet-4-6` and `claude-opus-4-6`.
- Make Claude selectable anywhere the dashboard currently lets the user run OpenAI-backed processing.
- Keep all existing OpenAI functionality working without behavior regressions.
- Keep the credits system provider-neutral: 1 USD of Claude cost maps to the same credit conversion as 1 USD of OpenAI cost.
- Keep rollout low-risk by disabling Claude prompt caching in v1.
- Support Claude vision for source processing from day one.
- Support Claude for `gliederung` generation from day one.

## 2. Locked Product Decisions

- Supported Claude models in v1:
  - `claude-sonnet-4-6`
  - `claude-opus-4-6`
- Supported operations in v1:
  - `process_quelle`
  - `combine`
  - `summary`
  - `shorten`
  - `lesefluss`
  - all refinement flows
  - `gliederung`
- Claude uses the platform key only.
- Existing documents without `provider` are treated as implicit `openai`.
- Claude prompt caching is disabled for the first rollout.
- Admin and billing surfaces should be generalized now if that reduces long-term confusion.

## 3. Non-Goals for v1

- No bring-your-own Anthropic key flow.
- No Claude prompt caching.
- No batch API integration.
- No provider-specific credit multiplier.
- No mandatory Firestore backfill of historical documents.

## 4. Current-State Audit

The current dashboard implementation is OpenAI-specific in four major layers.

### 4.1 Request and model typing

- `backend/models/request.py`
- `frontend/app/types/ui.ts`
- `frontend/app/actions/kapitels.ts`
- `frontend/app/components/dashboard/ProcessingDialog.tsx`
- `frontend/app/components/dashboard/GliederungCreateDialog.tsx`
- `frontend/app/components/dashboard/GliederungWorkspace.tsx`

Observations:

- Backend request models only accept GPT literals.
- Frontend processing settings only store a GPT model string.
- `createKapitelRun` normalizes the stored run model to OpenAI-only values.
- `shorten` and `lesefluss` inherit the model from the run and therefore are also OpenAI-only.

### 4.2 Execution layer

- `backend/services/openai_service.py`
- `backend/services/gliederung_service.py`

Observations:

- All dashboard execution flows call `AsyncOpenAI.responses.create(...)`.
- The service methods are already centralized, which is the best seam for provider abstraction.
- `gliederung_service.py` uses OpenAI strict JSON schema output and is more provider-specific than the text-only flows.

### 4.3 Cost estimation, reservation, and debit

- `backend/services/cost_service.py`
- `backend/services/openai_estimation_service.py`
- `backend/services/openai_budget_service.py`
- `backend/services/credits_service.py`
- `backend/scripts/seed_pricing_config.py`

Observations:

- Cost tracking is centralized and reusable.
- Estimation and reservation class names are OpenAI-branded, but the core reservation logic is provider-neutral.
- `credits_service.py` already contains a generic `debit_tracked_operation(...)`, but the old `debit_openai_operation(...)` path still exists.
- Pricing resolution currently has a dangerous global fallback model. That is fine in an OpenAI-only system, but unsafe once multiple providers exist.

### 4.4 Firestore documents and rules

- `firestore.rules`

Observations:

- Client-created run docs currently store `model` only.
- Result and artifact docs also store `model` only.
- Rules are strict about allowed fields, so adding `provider` requires explicit rules updates.
- Server-only cost metrics docs are easier to extend.

## 5. Anthropic API Findings That Matter for This Implementation

Verified against Anthropic official docs on 2026-04-10 and with one live test call.

Official docs used:

- API overview: `https://platform.claude.com/docs/en/api/overview`
- OpenAI compatibility: `https://platform.claude.com/docs/en/api/openai-sdk`
- Pricing: `https://platform.claude.com/docs/en/about-claude/pricing`
- Vision: `https://platform.claude.com/docs/en/build-with-claude/vision`
- Structured outputs: `https://platform.claude.com/docs/en/build-with-claude/structured-outputs`

Important differences from the current OpenAI path:

- Native Claude uses `POST /v1/messages`, not OpenAI Responses API.
- Claude requests use top-level `system`, `messages`, and mandatory `max_tokens`.
- Claude responses return block arrays in `content`, not `output_text`.
- Claude usage includes:
  - `input_tokens`
  - `cache_read_input_tokens`
  - `cache_creation_input_tokens`
  - `output_tokens`
- Anthropic's OpenAI compatibility layer is not the right long-term production path here.
- Anthropic's OpenAI compatibility docs explicitly say it is mainly for testing and comparison.
- Claude prompt caching is a separate concept and pricing model from OpenAI prompt caching.
- Claude vision supports the source-processing use case.
- Claude structured outputs are available natively, but the exact implementation contract differs from the current OpenAI strict-schema request.

Live validation already completed:

- A real request to the Anthropic Messages API succeeded with `claude-opus-4-6`.
- The response usage shape matched the documented token fields.

## 6. High-Level Architecture Decision

Do not bolt Claude conditionals directly into `openai_service.py`.

The lowest-complication durable design is:

1. Keep the business logic and prompt construction in the existing high-level services.
2. Introduce a provider-neutral LLM facade.
3. Keep OpenAI as one adapter.
4. Add Anthropic as a second adapter.
5. Make costs, reservations, and stored documents provider-aware.

This avoids:

- provider conditionals spread across `quelle_service.py`, `shorten_service.py`, and `refinement_service.py`
- billing ambiguity
- admin metrics mislabeled as OpenAI
- a second rewrite when another provider is added later

## 7. Target Data Model

### 7.1 Canonical selection object

Use separate `provider` and `model` fields everywhere.

Proposed canonical values:

- `provider: "openai" | "anthropic"`
- `model: string`

Initial supported values:

- OpenAI:
  - `gpt-5-nano`
  - `gpt-5-mini`
  - `gpt-5.4`
- Anthropic:
  - `claude-sonnet-4-6`
  - `claude-opus-4-6`

Backward compatibility rule:

- If `provider` is missing, treat it as `openai`.
- If a historical model alias is seen, normalize it only at execution and display time, not by mutating historical records.

### 7.2 Firestore document changes

Add `provider` to:

- `users/{uid}/kapitels/{kapitelId}/runs/{runId}`
- `users/{uid}/kapitels/{kapitelId}/runs/{runId}/results/{quelleId}`
- `users/{uid}/kapitels/{kapitelId}/runs/{runId}/artifacts/{artifactId}`
- `users/{uid}/costMetrics/v1/operations/{operationId}`

Rules for old docs:

- Missing `provider` means `openai`.
- Old result and artifact docs remain readable and usable without backfill.

## 8. Detailed Implementation Sequence

### Phase 0: Validation Spikes Before the Main Refactor

Purpose: eliminate unknowns before touching production paths.

Create or extend temporary validation scripts in `backend/tmp/`.

Spike A: plain text request

- Confirm both `claude-sonnet-4-6` and `claude-opus-4-6` work with the chosen SDK or raw HTTP path.
- Capture response parsing shape.

Spike B: vision request

- Confirm image URL based source processing works for both models.
- Verify content ordering that gives best results.

Spike C: token counting

- Validate `POST /v1/messages/count_tokens` behavior for text-only and text+image requests.
- Use this to decide whether the first estimator version uses the counting endpoint or a local heuristic fallback when counting fails.

Spike D: gliederung structured output

- Validate the exact structured-output path for both selected models.
- Preferred implementation: native Claude structured outputs.
- Mandatory fallback: tool-use based schema enforcement if SDK or model behavior is not reliable enough.

Acceptance criteria:

- All four spikes succeed at least once with the platform key.
- The chosen gliederung approach is proven before the refactor starts.

### Phase 1: Shared Provider and Model Contract

Files:

- `backend/models/request.py`
- `frontend/app/types/ui.ts`
- `frontend/app/actions/kapitels.ts`
- `frontend/app/components/dashboard/ProcessingDialog.tsx`
- `frontend/app/components/dashboard/GliederungCreateDialog.tsx`
- `frontend/app/components/dashboard/GliederungWorkspace.tsx`

Tasks:

- Introduce a provider literal type on both backend and frontend.
- Replace OpenAI-only model unions with provider-aware selection structures.
- Update run creation to store both `provider` and `model`.
- Update all payloads sent from the frontend to the backend to include `provider`.
- Update all model label helpers to display provider-specific names.
- Keep missing-provider reads backward compatible.

Implementation note:

- Do not keep `normalizeRunModel(...)` as an OpenAI-only coercion helper.
- Replace it with two helpers:
  - `normalizeRunProvider(...)`
  - `normalizeRunModel(provider, model)`

Acceptance criteria:

- New runs created from the dashboard persist both `provider` and `model`.
- Existing runs with no `provider` still execute as OpenAI.

### Phase 2: Provider-Neutral LLM Facade

New files recommended:

- `backend/services/llm_service.py`
- `backend/services/anthropic_service.py`

Existing files to update:

- `backend/services/openai_service.py`
- `backend/services/quelle_service.py`
- `backend/services/shorten_service.py`
- `backend/services/refinement_service.py`
- `backend/services/gliederung_service.py`

Design:

- Add a shared facade with methods matching the current OpenAI execution surface:
  - `process_quelle`
  - `combine_texts`
  - `summarize_kapitel`
  - `shorten_and_deduplicate`
  - `improve_reading_flow`
  - `generate_text`
- The facade selects the provider adapter based on `provider`.
- OpenAI adapter continues to use the current code path.
- Anthropic adapter implements the same semantic contract.

Why this shape:

- Existing high-level services already construct prompts correctly.
- The facade isolates provider transport, parsing, and usage normalization.

Acceptance criteria:

- High-level business services stop importing an OpenAI-specific execution service directly.
- OpenAI behavior remains unchanged after the refactor.

### Phase 3: Anthropic Adapter

Files:

- new `backend/services/anthropic_service.py`
- `backend/requirements.txt`
- `backend/requirements-gpu.txt`

Tasks:

- Add the official Anthropic Python SDK.
- Implement native Messages API requests.
- Normalize response content into the same return contract used by OpenAI-backed flows.
- Normalize usage into the current cost accounting structure:
  - `input_tokens`
  - `cached_input_tokens`
  - `output_tokens`
- Keep prompt caching disabled:
  - do not set `cache_control`
  - do not use any prompt-caching-only request options
- Capture Anthropic request IDs in logs where possible for easier production debugging.

Important implementation details:

- Anthropic requires `max_tokens`; add a shared per-operation output cap policy.
- Do not use Anthropic's OpenAI compatibility layer for the real implementation.
- For vision requests, keep image support in the Anthropic adapter from the first rollout.

Acceptance criteria:

- Each supported dashboard operation can execute end-to-end through the Anthropic adapter.
- Usage extraction works for both text-only and image-containing requests.

### Phase 4: Gliederung on Claude

Files:

- `backend/services/gliederung_service.py`

Current issue:

- The existing implementation depends on OpenAI strict JSON schema output via `responses.create(...)`.

Plan:

- Refactor `gliederung_service.py` to call the provider-neutral facade.
- For OpenAI:
  - preserve the current strict JSON schema path.
- For Anthropic:
  - use the validated Phase 0 structured-output path.
  - if the native structured-output helper is not reliable enough with the selected SDK or model version, use a forced tool-use fallback that returns the outline object.

Implementation rule:

- Gliederung must still return a parsed Python object, not raw text.
- Failures to parse or validate the structured result should remain fatal and explicit.

Acceptance criteria:

- `gliederung` works with both `claude-sonnet-4-6` and `claude-opus-4-6`.
- The parsed object contract remains unchanged for downstream code.

### Phase 5: Config and Key Resolution

Files:

- `backend/utils/config.py`
- `backend/.env.example`
- `backend/services/user_key_service.py`

Tasks:

- Add `CLAUDE_API_KEY` to config.
- Add `CLAUDE_API_KEY=` to `.env.example`.
- Update required-field handling so Anthropic-backed requests fail clearly if the key is missing.
- Generalize key resolution so callers resolve by provider.

Recommended API:

- `resolve_api_key_for_user(user_id, provider) -> (api_key, key_source)`

Behavior:

- OpenAI resolves to the platform OpenAI key.
- Anthropic resolves to the platform Claude key.
- Own-key flows remain disabled.

Acceptance criteria:

- Backend can resolve the correct platform key for each provider.
- The `keySource` field remains stable and accurate.

### Phase 6: Cost Calculation, Pricing, Estimation, and Reservations

Files:

- `backend/services/cost_service.py`
- `backend/services/openai_estimation_service.py`
- `backend/services/openai_budget_service.py`
- `backend/services/credits_service.py`
- `backend/scripts/seed_pricing_config.py`

### 6.1 Pricing configuration

Use the current flat pricing table in v1 to minimize migration complexity.

Recommended Firestore pricing shape for v1:

- keep `_config/pricing.models` as a flat map keyed by model name
- add Anthropic models to the same map
- add `fallbackModelByProvider`

Example intent:

- `fallbackModelByProvider.openai = "gpt-5-mini"`
- `fallbackModelByProvider.anthropic = "claude-sonnet-4-6"`

Reason:

- Model names are globally unique today.
- This avoids a large pricing schema rewrite.
- It removes the current unsafe single fallback behavior.

Prompt caching note:

- Because Claude prompt caching is disabled in v1, the existing three cost buckets are sufficient:
  - input
  - cached input
  - output
- No cache-write cost fields are required in v1.

### 6.2 Cost service changes

Tasks:

- Add `provider` to operation logs and aggregates.
- Update pricing resolution to accept `provider`.
- Prefer exact provider model pricing and provider-specific fallback over the current global fallback.
- Extend aggregate counters to group by provider as well as by model.

### 6.3 Estimation changes

Tasks:

- Replace the OpenAI-branded estimation service with a provider-neutral version.
- For OpenAI:
  - retain the current `tiktoken`-based path.
- For Anthropic:
  - primary path: call the token counting API for better reservation accuracy
  - fallback path: use the current heuristic structure if counting fails or times out
- Preserve the current spend-rate conversion logic.

### 6.4 Reservation changes

Tasks:

- Rename the OpenAI-branded budget service to a provider-neutral name or add a provider-neutral wrapper.
- Include `provider` in the operation metadata stored during reservation.
- Keep the reservation ledger and release flow unchanged semantically.

### 6.5 Credit debit changes

Tasks:

- Standardize on `debit_tracked_operation(...)`.
- Stop creating new OpenAI-specific ledger records through `debit_openai_operation(...)`.
- Write provider-aware metadata so future admin views can break costs down by provider.

Acceptance criteria:

- A Claude operation reserves credits before execution.
- A successful Claude operation logs accurate provider, model, usage, and USD cost.
- The credit debit amount equals `costUsd * spendRate`.

### Phase 7: Firestore Rules and Backward Compatibility

Files:

- `firestore.rules`

Tasks:

- Permit `provider` on run creation and update.
- Permit `provider` on server-written results and artifacts.
- Keep client update restrictions intact.
- Ensure old documents without `provider` remain valid for reads and do not require migration.

Migration decision:

- Do not backfill historical docs in v1.
- Backward compatibility lives in application code, not a one-time data migration.

Acceptance criteria:

- New docs with `provider` pass rules.
- Existing docs without `provider` still work.

### Phase 8: Frontend Dashboard UX

Files:

- `frontend/app/types/ui.ts`
- `frontend/app/actions/kapitels.ts`
- `frontend/app/components/dashboard/ProcessingDialog.tsx`
- `frontend/app/components/dashboard/ShortenDialog.tsx`
- `frontend/app/components/dashboard/LeseflussDialog.tsx`
- `frontend/app/components/dashboard/GliederungCreateDialog.tsx`
- `frontend/app/components/dashboard/GliederungWorkspace.tsx`
- `frontend/app/components/dashboard/Dashboard.tsx`

Tasks:

- Replace hardcoded GPT-only selections with provider-aware model options.
- Expose Claude model choices in the processing dialog and gliederung dialog.
- Ensure `shorten` and `lesefluss` continue to reuse the provider/model stored on the run.
- Update display labels so the current run clearly shows the selected provider/model.
- Rename `ensureOpenAIAccess` to a provider-neutral concept because it is really checking credits access.

UX recommendation:

- Present provider and model in one list for v1 to minimize UI churn.
- Example labels:
  - `OpenAI - GPT-5 nano`
  - `OpenAI - GPT-5 mini`
  - `OpenAI - GPT-5.4`
  - `Anthropic - Claude Sonnet 4.6`
  - `Anthropic - Claude Opus 4.6`

Acceptance criteria:

- Users can choose Claude during run creation.
- The selected provider/model persists and is reused by downstream operations.
- Existing runs display correctly even if they only have `model`.

### Phase 9: Admin and Billing Neutralization

Files:

- `frontend/app/api/admin/users/[uid]/openai/operations/route.ts`
- `frontend/app/api/admin/costs/summary/route.ts`
- `frontend/app/api/admin/costs/operations/route.ts`
- any matching backend admin routes

Plan:

- Generalize OpenAI-branded admin surfaces now, because provider-mixed costs under an OpenAI label will be misleading immediately.
- Introduce provider-neutral routes and UI labels.
- Keep the old OpenAI-specific route as a temporary alias if needed during migration.

Recommended naming:

- use `llm` or `ai` consistently
- avoid using `openai` in shared billing surfaces once Claude is live

Acceptance criteria:

- Admin cost views can distinguish OpenAI spend from Anthropic spend.
- Claude operations do not appear under OpenAI-only labels.

### Phase 10: Prompt Dumps and Diagnostics

Files:

- `backend/utils/prompt_dumps.py`
- `backend/utils/config.py`

Tasks:

- Make prompt dump filenames provider-aware.
- Keep old env names as compatibility aliases if desired.

Recommended output naming:

- `openai_<stage>_...md`
- `anthropic_<stage>_...md`

Reason:

- Debugging mixed-provider issues will be painful if prompt dumps remain OpenAI-branded.

### Phase 11: Test Plan

### 11.1 Unit tests

Add or update tests for:

- provider/model normalization
- fallback-to-openai behavior when `provider` is missing
- pricing resolution with `fallbackModelByProvider`
- Anthropic usage normalization
- credit reservation for Anthropic operations
- provider-aware debit logging
- gliederung parse validation for both providers

### 11.2 Integration tests

Use small live requests with the platform key to validate:

- OpenAI baseline still works
- Claude Sonnet 4.6 for each operation
- Claude Opus 4.6 for each operation
- vision processing on Claude
- gliederung on Claude
- reservation blocked flow
- error mapping for invalid model or missing key

### 11.3 Regression tests

Regression focus:

- OpenAI processing output unchanged
- billing totals unchanged for OpenAI runs
- old runs with missing `provider` still execute and render correctly

### Phase 12: Rollout Strategy

Recommended rollout order:

1. Land the provider/model storage and backend facade with OpenAI only still active.
2. Land Anthropic config and adapter behind internal testing.
3. Run validation spikes against both Claude 4.6 models.
4. Land pricing, reservation, and provider-aware logging.
5. Land frontend provider selection.
6. Land admin neutralization.
7. Run live end-to-end QA on a staging environment.
8. Deploy.

Recommended release safety checks:

- Confirm Firestore rules are deployed before frontend users can write `provider`.
- Confirm `_config/pricing` contains Anthropic model entries before Claude is exposed in UI.
- Confirm `CLAUDE_API_KEY` is present in each target environment before rollout.

## 9. File-by-File Change Inventory

Backend:

- `backend/models/request.py`
- `backend/services/openai_service.py`
- `backend/services/anthropic_service.py`
- `backend/services/llm_service.py`
- `backend/services/gliederung_service.py`
- `backend/services/quelle_service.py`
- `backend/services/shorten_service.py`
- `backend/services/refinement_service.py`
- `backend/services/cost_service.py`
- `backend/services/openai_estimation_service.py` or replacement
- `backend/services/openai_budget_service.py` or replacement
- `backend/services/credits_service.py`
- `backend/services/user_key_service.py`
- `backend/utils/config.py`
- `backend/utils/prompt_dumps.py`
- `backend/scripts/seed_pricing_config.py`
- `backend/requirements.txt`
- `backend/requirements-gpu.txt`
- `backend/.env.example`

Frontend:

- `frontend/app/types/ui.ts`
- `frontend/app/actions/kapitels.ts`
- `frontend/app/components/dashboard/ProcessingDialog.tsx`
- `frontend/app/components/dashboard/ShortenDialog.tsx`
- `frontend/app/components/dashboard/LeseflussDialog.tsx`
- `frontend/app/components/dashboard/GliederungCreateDialog.tsx`
- `frontend/app/components/dashboard/GliederungWorkspace.tsx`
- `frontend/app/components/dashboard/Dashboard.tsx`
- admin route proxies and any admin views that display provider/model or costs

Infra and rules:

- `firestore.rules`

Tests and validation scripts:

- new Anthropic validation scripts under `backend/tmp/`
- update existing backend tests to cover provider-aware paths

## 10. Risk Register and Mitigations

Risk: incorrect Claude billing due to provider fallback hitting an OpenAI model price.

Mitigation:

- add `fallbackModelByProvider`
- require provider-aware pricing resolution
- fail loudly if Anthropic pricing is missing instead of silently using an OpenAI fallback

Risk: gliederung structured outputs behave differently between models or SDK versions.

Mitigation:

- complete the structured-output spike before refactoring the production code
- keep forced tool-use fallback ready

Risk: Firestore rules reject new docs with `provider`.

Mitigation:

- update and deploy rules before frontend rollout
- verify with emulator or staging writes

Risk: admin UI becomes misleading during partial rollout.

Mitigation:

- generalize admin terminology in the same implementation
- keep route aliases only as compatibility shims

Risk: Anthropic `max_tokens` caps are too low and truncate outputs.

Mitigation:

- centralize per-operation output caps
- validate with long-ish staging examples for each operation class

Risk: local or staging envs expose Claude in the UI without a configured key.

Mitigation:

- validate env configuration before rollout
- if needed, add a lightweight backend capability endpoint or keep the UI exposure tied to environment readiness

## 11. Recommended Order of Execution for the Actual Work

1. Run the four validation spikes.
2. Implement provider/model contract changes and Firestore rules.
3. Introduce the provider-neutral LLM facade.
4. Add the Anthropic adapter with plain text and vision support.
5. Refactor gliederung onto the facade using the validated Claude structured-output path.
6. Generalize pricing resolution, estimation, reservation, and debit logging.
7. Update frontend dialogs and run persistence.
8. Generalize admin and billing surfaces.
9. Run unit, integration, and staging regression tests.
10. Deploy with pricing config and env readiness verified first.

## 12. Definition of Done

The implementation is complete when all of the following are true:

- Users can choose `claude-sonnet-4-6` and `claude-opus-4-6` from the dashboard.
- New runs store both `provider` and `model`.
- Old runs without `provider` still execute as OpenAI.
- Claude works for all agreed operations, including `gliederung`.
- Claude vision works for source processing.
- Cost logs record accurate USD spend for Claude operations.
- Credits are reserved and debited correctly for Claude operations.
- Admin views distinguish OpenAI from Anthropic.
- Firestore rules accept the new document shape.
- OpenAI behavior remains intact.
