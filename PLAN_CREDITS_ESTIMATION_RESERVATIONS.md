# Plan: Credit Pre-Check (Token/Cost Estimation) + Concurrency-Safe Reservations + Admin Visibility

This is an **implementation plan only** (no code in this document).

What we’re building:

1. **Token/cost estimation** for every OpenAI-backed operation (input + estimated output).
2. **Concurrency-safe reservations** (`reservedCredits`) so multiple in-flight jobs don’t overspend.
3. **Admin visibility + controls**: show running/completed OpenAI operations with estimated vs actual tokens/credits; allow manual reservedCredits adjustment.

Decisions already locked in (from you):

- Use **`tiktoken`** for token counting.
- Token counting is **NOT model-dependent** (one fixed encoding for all texts).
- Pricing/cost **IS model-dependent** (use existing pricing logic in `fastapi/services/cost_service.py`).
- Ignore token caching in estimation (treat cached input tokens as 0).
- Do **not** set `max_output_tokens` (min/max are estimation-only).
- Export DOCX: **only** check `availableCredits > 0` (no estimation/reservation).
- Summary calls: estimation must assume they will be needed (ignore cache), but runtime may still skip due to cache; in that case release reservation and mark as `skipped`.

---

## 1.7 Reservation & concurrency model

### 1.7.1 Definitions

- `totalActiveCredits`: normalized subscription credits (0 if expired) + topup credits
- `reservedCredits`: credits “held” for queued/running OpenAI operations
- `availableCredits = totalActiveCredits - reservedCredits`

All checks and reservations are based on **available credits**.

### 1.7.2 Core rules

**Rule A — Reserve before OpenAI calls**

- Before _every_ OpenAI call, we must have a reservation for that operation (idempotent).
- If reservation cannot be created because `availableCredits < estimatedCredits`, the OpenAI call must not happen.

**Rule B — Stop when credits drop to <= 0**

- Before executing the next OpenAI call in a workflow, check `totalActiveCredits > 0` (strict).
- If `totalActiveCredits <= 0`, abort remaining steps, mark them `blocked` or `error`, and release their reservations.

This matches your requirement: “if credits are 0 or less at any point, don’t continue”.

**Rule C — Export DOCX**

- For export: only check `availableCredits > 0` (strict). No estimation/reservation.

### 1.7.3 Reservation lifecycle (single OpenAI call)

For one OpenAI call, the lifecycle is:

1. Build full prompt strings (system + user) and collect image metadata.
2. Compute estimate (input/output words + tokens + costUsd + credits).
3. Reserve credits (Firestore transaction):
   - read/normalize `users/{uid}/billing/balance`
   - compute `availableCredits`
   - if `availableCredits < estimate.credits` → mark op `blocked`, return / abort
   - else:
     - increment `reservedCredits += estimate.credits`
     - create/merge op doc `costMetrics/v1/operations/{operationId}` with `status="reserved"`, `estimate`, `reservation`
4. Mark op `running`.
5. Call OpenAI.
6. On success:
   - compute actual cost via existing pipeline (`calculate_cost` using real usage)
   - write actuals to op doc (via `CostService.log_operation(operation_id=...)`)
7. Always (success/error/skip):
   - release reservation (transaction): `reservedCredits -= reservation.reservedCredits`
   - mark `reservation.releasedAt` + reason

### 1.7.4 Idempotency invariants

We must guarantee:

- same `operationId` will never reserve twice
- same `operationId` will never debit twice (ledger idempotency already exists by operation id)

Reservation transaction must handle:

- if op doc exists with `status in {"reserved","running"}`: treat as already reserved/running, do not increment reservedCredits again.
- if op doc exists with `status in {"success","error","blocked","skipped"}`: treat as finalized and do not reserve again.

### 1.7.5 What can still go wrong (and how we handle without TTL)

Without TTL, a _hard process crash_ can still leave `reservedCredits` stuck.

Mitigations in this plan:

- Minimize “reserve far in advance”: reserve right before executing the step (or right before queueing if you want immediate blocking).
- Always use `try/except/finally` to release on code-level exceptions.
- Provide admin tools to:
  - view outstanding reserved operations
  - manually adjust `reservedCredits`

---

## 1.8 OperationId strategy (stable per OpenAI call)

We need stable, unique `operationId`s for:

- reservation idempotency
- debit idempotency (`openai_{operationId}`)
- matching estimate ↔ actual in admin UI

Recommended:

- Generate a `workflowId = uuid4()` at the start of each top-level request.
- Derive per-step operation ids:
  - `operationId = f\"{workflowId}_{stepKey}\"`

Examples:

- `process_quelle`: `{workflowId}_process_quelle_{quelleId}`
- `combine` single: `{workflowId}_combine_final`
- `combine` hierarchical:
  - `{workflowId}_combine_group_1`, `{workflowId}_combine_group_2`, ..., `{workflowId}_combine_final`
- `shorten`:
  - `{workflowId}_summary_{contextKapitelId}` for each summary
  - `{workflowId}_shorten`
- `lesefluss`:
  - summaries as above
  - `{workflowId}_lesefluss`
- `refine_*`:
  - easiest stable id is `versionId` (already unique and stored). If you want workflow grouping, wrap: `{workflowId}_refine_{versionId}`.

Constraints:

- Firestore doc id must not contain `/`.

---

## 1.9 Prompt capture per operation (what counts as “input”)

You want “the complete prompt we would send”, matching `utils/prompt_dumps.dump_prompt_markdown`.

We will always treat input as:

- system text (the system prompt passed to OpenAI)
- user text (the user prompt passed to OpenAI)
- plus image tile tokens (if images are sent)

### 1.9.1 `process_quelle` (and `refine_result`, which calls process_quelle)

**User text**

- Use the same “instructions” text that ends up in the OpenAI call:
  - rendered template text (stage `process_quelle`)
  - plus `quelle_content_doc["text"]`
  - plus “Grundlegende Informationen” insertion if used by current logic

**System text**

- `PromptService.get_system_prompt_for_template(stage="process_quelle", template_id=...)` (or stage default if None)

**Output words**

- `0.50 * words(quelle_content_doc["text"])`, clamp 50..2000

**Images**

- Sum tile tokens over `quelle.images[]` using stored width/height; missing → 0 tokens.

### 1.9.2 `combine` / `combine_intermediate`

**User text**

- Build `drafts_content` exactly like current code:
  - `"Text 1:\\n{...}\\n\\nText 2:\\n{...}..."`
- Apply combine instructions:
  - if template contains `{DRAFTS}`, replace it with drafts_content
  - else append `[ENTWÜRFE]\\n{drafts_content}`

**System text**

- `PromptService.get_system_prompt_for_template(stage="combine")`

**Output words**

- `0.70 * words(drafts_content)` clamp 50..2000

**Hierarchical final step (unknown intermediate texts)**

- Estimate intermediate outputs’ word counts via same combine rule.
- Create placeholder text with N words for each intermediate output.
- Build final drafts_content using placeholders and tokenize the resulting prompt.

### 1.9.3 `summary`

**User text**

- `PromptService.get_rendered_instructions(stage="summary", payload={"KAPITELTEXT": source_text})`

**System text**

- `PromptService.get_system_prompt_for_template(stage="summary")`

**Output words**

- `0.35 * words(source_text)` clamp 50..2000

### 1.9.4 `shorten`

**User text**

- Render stage `shorten` template with:
  - `KAPITELTEXT` = combined text
  - `GLIEDERUNG_SUMMARY` = gliederung string
  - title/topic fields
- If template doesn’t include inline placeholders, append the fallback sections (as in current code).

**System text**

- `PromptService.get_system_prompt_for_template(stage="shorten")`

**Output words**

- `0.70 * words(KAPITELTEXT)` clamp 50..2000

### 1.9.5 `lesefluss`

**User text**

- Render stage `lesefluss` template with:
  - `AUFGABENSTELLUNG`
  - `GLIEDERUNG_SUMMARY`
  - `KAPITELTEXT` = shortened text
  - chapter numbers
- Same “fallback append” behavior as current code.

**System text**

- `PromptService.get_system_prompt_for_template(stage="lesefluss")`

**Output words**

- `1.20 * words(KAPITELTEXT)` clamp 50..2500

### 1.9.6 `refine_*`

Refinement uses `openai_service.generate_text(prompt_body, ...)`.

**User text**

- The full refinement “conversation prompt” returned by `_build_refinement_conversation_prompt(...)`.

**System text**

- `REFINEMENT_SYSTEM_PROMPT`

**Output words**

- `words(parent_generated_text)` (no clamp)

Special case:

- `refine_lesefluss` also depends on summaries; your instruction is to include summary operations in estimation (ignore cache).

---

## 1.10 Backend API changes (FastAPI)

### 1.10.1 New backend helpers (services/utils)

Create:

1. `TokenEstimator` (pure estimation; tiktoken + formulas)
2. `OpenAIBudgetService` (reserve/mark running/finalize/release, plus admin helpers)

### 1.10.2 Extend cost logging to use external operationId

Change `CostService.log_operation(...)`:

- accept `operation_id: str | None`
- if provided, write to `operations/{operation_id}` (merge=True)
- ensure credits debit is idempotent by using that id consistently

This allows:

- creating the operation doc at reserve-time (`status=reserved`)
- updating it later with actual cost/tokens (`status=success/error`)

### 1.10.3 New admin endpoints

Add to `fastapi/main.py`:

1. `GET /api/admin/users/{uid}/openai/operations`

- paginated list from `users/{uid}/costMetrics/v1/operations`
- supports:
  - `limit` (default 50, max 200)
  - `cursor` (doc id)
  - optional `status` filter

2. `POST /api/admin/users/{uid}/billing/reserved-credits`

- update `billing/balance.reservedCredits` (set or delta)
- include `note` and `admin_uid` in an audit record (recommended new subcollection)

3. Extend existing `GET /api/admin/users/{uid}` response:

- include `reservedCredits` and `availableCredits` in `billing.balance`

---

## 1.11 Frontend changes (Admin dashboard)

### 1.11.1 Add “OpenAI” tab to admin user detail

In `app/components/admin/AdminUserDetail.tsx`:

- add tab `openai`
- panel shows:
  - current balance (subscription/topup/reserved/available)
  - operation list (running + history)
  - reservedCredits editor (set/delta)

### 1.11.2 Add Next proxy route handlers

Add:

- `app/api/admin/users/[uid]/openai/operations/route.ts`
- `app/api/admin/users/[uid]/billing/reserved-credits/route.ts`

Use the existing `proxyAdminJson` pattern.

---

## 1.12 Image width/height storage (client-side)

Update image upload so every stored image has:

- `widthPx`
- `heightPx`

Location:

- `app/lib/firebase/storage.ts` (client-side upload helper)
- `app/actions/quellen.ts` (ImageMetadata type + Firestore persistence)

Back-compat:

- missing width/height → estimate 0 image tokens.

---

## 1.13 Manual testing checklist (must-pass)

1. **Reserve + release single op**

- Run `process_quelle` and verify:
  - `reservedCredits` increases while running
  - decreases after completion/error
  - ledger debit exists for actual cost

2. **Concurrency block**

- Start op A (reserve X), then op B that needs more than available.
- B must be blocked (no OpenAI call), and reservations must not be double-counted.

3. **Shorten / lesefluss workflow**

- Verify summary ops + final op appear in admin list.
- If cached summary is used, op becomes `skipped` and releases its reservation.

4. **Hierarchical combine**

- With >5 sources, ensure intermediate + final ops appear and finish correctly.

5. **Admin controls**

- Admin OpenAI tab shows estimates vs actuals.
- Admin can set/delta reservedCredits and see updated available credits.

---

# 2) Commit-by-Commit Implementation Plan

Each commit below is meant to be **self-contained**: it repeats the critical context, expected Firestore shape, and “how to test”, so you can work commit-by-commit without hunting through Section 1.

## Commit 1 — Backend dependency + core token helpers

**Outcome**

- Backend can count words/tokens consistently (tiktoken) and estimate image tile tokens.

**Files**

- `fastapi/requirements.txt`
- New helper module:
  - recommended: `fastapi/utils/token_estimation.py`

**Changes**

- Add `tiktoken` to `fastapi/requirements.txt`.
- Implement:
  - `ENC = tiktoken.get_encoding("o200k_base")`
  - `count_words(text)` using whitespace (`\\S+`)
  - `count_tokens(text)` using `ENC.encode(text)`
  - `estimate_image_tokens(widthPx,heightPx)` per your tile formula (fallback 0 if missing/<=0)

**How to test**

- Start backend locally, import the module in a REPL (`python -c ...`) and confirm it loads.
- Run a quick sanity check: token count increases with longer text; image tokens are 0 when dims missing.

---

## Commit 2 — Backend: implement estimation rules (pure math, no reservations yet)

**Outcome**

- Given a fully built prompt (system text + user text + optional image metadata), the backend can compute:
  - estimated input tokens
  - estimated output tokens (using your per-operation word formulas)
  - estimated USD cost (model pricing)
  - estimated credits (USD \* spendRate)

**Files**

- New service:
  - recommended: `fastapi/services/openai_estimation_service.py`
- Touch (read-only dependency usage): `fastapi/services/cost_service.py`, `fastapi/services/credits_service.py`

**Changes**

- Implement operation-type rules exactly:
  - `summary`: 35% KAPITELTEXT, clamp 50..2000
  - `process_quelle`: 50% QUELLTEXT, clamp 50..2000
  - `combine`: 70% DRAFTS, clamp 50..2000
  - `shorten`: 70% KAPITELTEXT, clamp 50..2000
  - `lesefluss`: 120% KAPITELTEXT, clamp 50..2500
  - `refine_*`: output words = parent words (no clamp), output tokens = parent tokens
- Output token estimation:
  - compute tokens-per-word from the same source text used by the formula (tokenize source text, divide by its word count)
- USD cost estimation:
  - call `CostService.resolve_model_pricing(model)` and compute USD from tokens
- Credits estimation:
  - call `CreditsService.get_spend_rate_for_user(user_id)` and multiply USD

**How to test**

- Add a small local-only test script (optional) that:
  - fetches a known run/quelltext from Firestore
  - runs estimation functions
  - prints result for manual plausibility review

---

## Commit 3 — Backend: store and expose `reservedCredits` + `availableCredits`

**Outcome**

- Balance summary can represent reservations:
  - `reservedCredits` default 0
  - `availableCredits = totalCredits - reservedCredits`

**Files**

- `fastapi/services/credits_service.py`
- `fastapi/main.py` (`_compute_balance_summary`, `/api/billing/balance`)
- (Optional) anywhere else balance is summarized for admin

**Firestore**

- `users/{uid}/billing/balance.reservedCredits` (new; server-written)

**Changes**

- Update `_compute_balance_summary(...)` to include:
  - `reservedCredits`
  - `availableCredits`
- Ensure subscription expiry normalization remains correct (existing behavior).
- Add a helper in `CreditsService`:
  - `get_available_credits(user_id) -> float`

**How to test**

- User with existing balance doc (no reservedCredits):
  - `/api/billing/balance` returns reservedCredits=0 and availableCredits==totalCredits.

---

## Commit 4 — Backend: implement reservation transactions + per-operation doc schema

**Outcome**

- Before an OpenAI call, backend can:
  - reserve credits atomically (transaction)
  - create/update op doc in `costMetrics/v1/operations/{operationId}` as `reserved`/`running`
  - release reservation on finalize

**Files**

- New service:
  - recommended: `fastapi/services/openai_budget_service.py`
- Touch: `fastapi/services/credits_service.py` (reuse normalize logic)

**Firestore**

- `users/{uid}/billing/balance.reservedCredits`
- `users/{uid}/costMetrics/v1/operations/{operationId}` (extended)

**Operation doc fields (minimum)**

- `status`
- `estimate.{inputTokens,outputTokens,totalTokens,inputWords,outputWords,costUsd,credits,model}`
- `reservation.{reservedCredits,reservedAt,releasedAt,releaseReason}`
- `operationType`, `userId`, `userActionId` and related IDs you already store today

**Reservation logic**

- Transaction reads balance + current reservedCredits
- Computes available
- Blocks if `available < estimate.credits`
- Else increments reservedCredits and writes operation doc (merge)
- Idempotency:
  - if doc already exists, do not reserve twice

**How to test**

- Simulate 2 parallel “reserve same operationId” attempts (manual or via script): reservedCredits increases once.
- Simulate “reserve A then reserve B”: B blocked if insufficient.

---

## Commit 5 — Backend: unify estimate/reservation with final cost log (operationId plumbing)

**Outcome**

- The same `operationId` is used for:
  - reservation doc
  - final cost log doc
  - credits debit ledger idempotency

**Files**

- `fastapi/services/cost_service.py`
- Call sites that call `cost_service.log_operation(...)`

**Changes**

- Modify `CostService.log_operation(...)`:
  - accept `operation_id: str | None`
  - if provided:
    - write to `operations/{operation_id}` (use `set(..., merge=True)` to preserve estimate/reservation)
    - do not generate a new uuid
- Ensure `CreditsService.debit_openai_operation(operation_id=...)` is called with the same id.

**How to test**

- Reserve + run a single operation.
- Confirm:
  - one doc id stays constant from `reserved` → `success`
  - ledger debit is idempotent on retries.

---

## Commit 6 — Backend: integrate into `process_quelle` (and `refine_result`)

**Outcome**

- `process_quelle` calls are blocked/reserved and fully visible in admin with estimate vs actual.
- Image tokens are included when width/height exist; otherwise 0.

**Files**

- `fastapi/services/quelle_service.py` (`process_single_quelle`)
- `fastapi/services/refinement_service.py` (`process_result_refinement`)

**Key steps**

1. Generate `workflowId` and per-call `operationId`
2. Build the _exact_ system and user text as current OpenAI call would send
3. Estimate with rules:
   - output = 50% QUELLTEXT, clamp 50..2000
4. Reserve credits (transaction)
5. Mark running
6. Call OpenAI
7. Log operation with same `operationId`
8. Release reservation (success/error)

**How to test**

- Start `process_quelle` with low credits → must block before OpenAI.
- Start with enough credits → operation shows running then success in admin.

---

## Commit 7 — Backend: integrate into combine (single + hierarchical)

**Outcome**

- Combine operations (including intermediates) are estimated/reserved/visible and block correctly.

**Files**

- `fastapi/services/quelle_service.py`

**Key rules**

- combine output = 70% of DRAFTS words (including `Text i:` labels), clamp 50..2000
- hierarchical final input uses placeholder text for intermediate outputs for token estimation

**Implementation details**

- For hierarchical:
  - create one operation per group + one for final
  - reserve per operation idempotently
  - if credits drop to <=0 after some steps, abort remaining ones and release their reservations

**How to test**

- Use >5 eligible results to trigger hierarchical combine.
- Confirm admin shows `combine_group_*` and `combine_final`.

---

## Commit 8 — Backend: integrate into shorten + lesefluss (and summary ops)

**Outcome**

- `shorten` and `lesefluss` workflows:
  - include summary costs in estimation (ignore cache)
  - reserve per summary operation + final operation
  - if summary is cached at runtime, mark `skipped` and release reservation immediately

**Files**

- `fastapi/services/shorten_service.py`

**Key rules**

- summary output = 35% source text, clamp 50..2000
- shorten output = 70% KAPITELTEXT, clamp 50..2000
- lesefluss output = 120% KAPITELTEXT, clamp 50..2500

**How to test**

- Run shorten with multiple context chapters.
- Confirm:
  - reservations created for summaries + final shorten
  - cached summaries become `skipped` and release reservations

---

## Commit 9 — Backend: integrate into refinement flows (+ refine_lesefluss summaries)

**Outcome**

- Refinement calls are estimated/reserved and show estimate vs actual.
- refine_lesefluss includes summary ops in estimation/reservation (ignore cache).

**Files**

- `fastapi/services/refinement_service.py`

**Refine estimation**

- input tokens = tokenize(REFINEMENT_SYSTEM_PROMPT) + tokenize(prompt_body)
- output tokens estimate = tokenize(parent_text)

**How to test**

- Trigger a refinement step and verify it appears in admin list with estimate/actual.

---

## Commit 10 — Backend: export-docx uses strict `availableCredits > 0` check only

**Outcome**

- Export is blocked when available credits are 0 or below (strict), but does not do estimation/reservations.

**Files**

- `fastapi/main.py` (`/api/export-docx`)
- `fastapi/services/export_service.py` (before `call_llm_fixups`, optionally re-check available > 0)

**How to test**

- Set user available credits to 0 (or reserve everything) and try export → should block immediately.

---

## Commit 11 — Admin backend: list operations + adjust reserved credits

**Outcome**

- Admin can inspect per-operation estimate/actual and fix reservedCredits manually.

**Files**

- `fastapi/main.py`

**Endpoints**

- `GET /api/admin/users/{uid}/openai/operations` (paginated)
- `POST /api/admin/users/{uid}/billing/reserved-credits` (set/delta + audit note)
- Extend `GET /api/admin/users/{uid}` to include reserved/available in billing summary

**How to test**

- Admin loads user detail page: balance shows reserved+available.
- Admin calls adjust endpoint: reservedCredits changes accordingly.

---

## Commit 12 — Admin frontend: OpenAI tab + reserved editor

**Outcome**

- Admin user detail page shows OpenAI operations and can tweak reservedCredits.

**Files**

- `app/components/admin/AdminUserDetail.tsx` (new tab)
- New component: `app/components/admin/AdminUserOpenAIOperationsPanel.tsx`
- Proxy routes:
  - `app/api/admin/users/[uid]/openai/operations/route.ts`
  - `app/api/admin/users/[uid]/billing/reserved-credits/route.ts`

**UI requirements (from you)**

- Show:
  - running status
  - estimated credits + actual credits
  - estimated input/output tokens + actual input/output tokens
- Provide a manual reservedCredits adjustment UI (set/delta) with clear labeling.

**How to test**

- Open `/admin/users/{uid}` and verify OpenAI tab lists operations and shows numbers.
- Adjust reservedCredits and verify numbers update after refresh.

---

## Commit 13 — Frontend: store image width/height; backend: use it for image token estimation

**Outcome**

- New uploads store `widthPx/heightPx`, enabling image token estimation.
- Old images (without dims) estimate 0 tokens.

**Files**

- `app/lib/firebase/storage.ts` (compute dimensions before returning metadata)
- `app/actions/quellen.ts` (extend ImageMetadata type + persist)
- Backend: use dims in estimation when present

**How to test**

- Upload a Quelle with an image → Firestore Quelle doc now includes width/height.
- process_quelle estimation includes non-zero image tokens for that image.

---

## Commit 14 — Docs: update beta billing test guide

**Outcome**

- Manual test steps exist for reservations + admin observability.

**Files**

- `TESTING_BETA_BILLING_CREDITS.md`

**Add sections**

- reservedCredits behavior
- concurrency blocking scenario
- admin OpenAI tab verification

## 1) Complete Implementation Plan

### 1.1 Goals

**Billing correctness**

- Block starting OpenAI work when `availableCredits` is insufficient for the estimated credits of the operation.
- Allow small overdraft only when actual > estimate (acceptable).

**Concurrency**

- Multiple parallel jobs must not overspend shared credits (reserved credits must be reflected immediately).
- Support sequences like: 4 jobs running → 2 finish → 2 more start, all correctly reflected.

**Observability + recovery**

- Admin can inspect each OpenAI operation:
  - running/success/error
  - estimated vs actual input/output tokens
  - estimated vs actual credits
- Admin can manually adjust `reservedCredits` if something goes wrong.

### 1.2 Non-goals

- Do not change the real cost/debit pipeline (keep `CostService.calculate_cost()` + `CreditsService.debit_openai_operation()` as the source of truth for actual spend).
- Do not show estimate details in the regular user UI.
- No TTL-based reservation expiry (we rely on correct finalize/release paths + admin recovery tools).

---

## 1.3 Current code reality (where to integrate)

### 1.3.1 Where OpenAI calls happen

- `fastapi/services/openai_service.py`
  - `process_quelle(...)`
  - `combine_texts(...)`
  - `summarize_kapitel(...)`
  - `shorten_and_deduplicate(...)`
  - `improve_reading_flow(...)`
  - `generate_text(...)`
- `fastapi/services/export_service.py`
  - `call_llm_fixups(...)` (Responses API call with `max_output_tokens=1200` today)

### 1.3.2 Where credits are debited today

- `fastapi/services/cost_service.py`
  - `calculate_cost(...)` (USD from token usage + model pricing)
  - `log_operation(...)` (writes `users/{uid}/costMetrics/v1/operations/{operationId}` and aggregates; then calls credits debit)
- `fastapi/services/credits_service.py`
  - `debit_openai_operation(...)` (subscription first, then topup)
  - `assert_not_negative_balance(...)` (currently: only blocks if total is already negative)

### 1.3.3 Multi-step workflows (must include summaries / intermediates)

- `fastapi/services/quelle_service.py`
  - `combine_run_results(...)` can be single-level or `_hierarchical_combine(...)` (many OpenAI calls)
- `fastapi/services/shorten_service.py`
  - `process_shorten_request(...)` (summary calls + shorten call)
  - `process_lesefluss_request(...)` (summary calls + lesefluss call)
  - `get_or_create_summary(...)` (cache exists; estimation ignores cache, runtime can still skip)
- `fastapi/services/refinement_service.py`
  - `process_*_refinement(...)` (generates long “conversation prompt” and calls `generate_text(...)`)
  - `process_result_refinement(...)` calls `process_quelle(...)` again (includes images)

---

## 1.4 Data model changes (Firestore)

### 1.4.1 Add `reservedCredits` to `users/{uid}/billing/balance`

Add a server-only float field:

- `reservedCredits: number` (default 0)

Definitions:

- `totalActiveCredits = subscriptionActiveCredits (0 if expired) + topupCredits`
- `availableCredits = totalActiveCredits - reservedCredits`

Notes:

- We keep the existing debit order (subscription first, then topup) as implemented in `CreditsService.debit_openai_operation(...)`.

### 1.4.2 Per-operation docs (reservation + estimate + actual)

We need “per-operation reservation docs” and a timeline (reserved → running → success/error) visible in admin.

Recommended: reuse the existing server-written collection and upgrade it:

- `users/{uid}/costMetrics/v1/operations/{operationId}`

Extend schema with:

**`estimate` (new)**

- `estimate.inputWords`, `estimate.outputWords`
- `estimate.inputTokens`, `estimate.outputTokens`, `estimate.totalTokens`
- `estimate.costUsd`
- `estimate.credits` (USD \* spendRate)
- `estimate.model` (model used for pricing)

**`reservation` (new)**

- `reservation.reservedCredits` (usually equals `estimate.credits`)
- `reservation.reservedAt`, `reservation.releasedAt`
- `reservation.releaseReason` (`success|error|blocked|skipped|admin_adjustment|unknown`)

**`status` values**

- `reserved`, `running`, `success`, `error`, `blocked`, `skipped`

Actuals already exist in the doc today via:

- `tokens.*`, `costs.*`, `pricingPerMillion.*`, etc.
  We’ll add optional convenience fields for admin:
- `actual.credits` and `actual.spendRate`

### 1.4.3 Image metadata enrichment (for image token estimation)

Client stores image metadata today as:

- `url`, `path`, `filename`, `size`, `contentType`

Add:

- `widthPx: number`
- `heightPx: number`

Back-compat rule (your request):

- if width/height missing → image tokens estimate is 0

---

## 1.5 Token counting & word counting

### 1.5.1 Tokenizer choice

Use `tiktoken` server-side and pick **one fixed encoding** (no model branching, no fallback chains).

Recommended encoding to standardize on:

- `o200k_base`

Implementation detail:

- instantiate the encoder once (module-level singleton) to avoid repeated heavy init.

### 1.5.2 Word counting

Use the same definition as in `app/actions/quellen.ts`:

- split on whitespace: `len(re.findall(r"\\S+", text.strip()))`

This is what all min/max word clamps and “% of text” formulas apply to.

### 1.5.3 Image token estimation

Use exactly this function (math-only; no image fetching):

```py
def estimate_image_tokens(width_px: int, height_px: int, tokens_per_512_tile: int = 85) -> int:
    tiles_w = math.ceil(width_px / 512)
    tiles_h = math.ceil(height_px / 512)
    return tiles_w * tiles_h * tokens_per_512_tile
```

Back-compat:

- if widthPx/heightPx missing or <= 0 → 0 image tokens.

---

## 1.6 Estimation rules (words → tokens → USD → credits)

### 1.6.1 Output word formulas (final)

Clamps are estimation-only (do not set `max_output_tokens`).

| Operation                          |           Output words formula | Min |  Max |
| ---------------------------------- | -----------------------------: | --: | ---: |
| `summary`                          |    `0.35 * words(KAPITELTEXT)` |  50 | 2000 |
| `refine_*`                         | `words(parent_generated_text)` |   — |    — |
| `process_quelle`                   |      `0.50 * words(QUELLTEXT)` |  50 | 2000 |
| `combine` / `combine_intermediate` |         `0.70 * words(DRAFTS)` |  50 | 2000 |
| `shorten`                          |    `0.70 * words(KAPITELTEXT)` |  50 | 2000 |
| `lesefluss`                        |    `1.20 * words(KAPITELTEXT)` |  50 | 2500 |

Notes:

- For combine, `DRAFTS` includes `Text i:` labels (your request).
- For refine, no clamp.

### 1.6.2 Output token estimation method (tokenizer-based, no global ratio)

We only know output **word count**, not exact output text.

Use a per-operation tokens/word factor from the _source text used in the formula_:

- `tokens_per_word = tokenize(source_text).tokens / max(words(source_text), 1)`
- `estimated_output_tokens = round(estimated_output_words * tokens_per_word)`

For refinement:

- estimate output tokens as `tokenize(parent_generated_text).tokens` (since output length ~= parent text length).

### 1.6.3 Input token estimation (“capture full prompt”)

For each OpenAI call, compute input tokens by tokenizing:

- the **system text** that is passed to Responses API
- the **user text** that is passed to Responses API
- plus image tile tokens (if any)

Store both words + tokens for system and user so admin can debug sizing without storing raw prompts.

### 1.6.4 Convert tokens → USD (model pricing) → credits (spend rate)

Steps:

1. Resolve pricing via `CostService.resolve_model_pricing(model)`.
2. Compute USD estimate (cached tokens ignored):
   - `usd = (input_tokens/1e6)*input_price + (output_tokens/1e6)*output_price`
3. Spend rate via `CreditsService.get_spend_rate_for_user(user_id)`.
4. Credits estimate:
   - `credits = usd * spend_rate`

---
