# Firestore V2 — Hands-on Implementation Steps

This is the concrete execution checklist for implementing Firestore V2. For details, refer to:
- `FIRESTORE_V2_DATABASE_PLAN.md` (schema/rules/migration mapping)
- `FIRESTORE_V2_CODE_PLAN.md` (code refactor plan)
- `FIRESTORE_DATABASE_AUDIT.md` (current-state reference)

## Step-by-step (9 steps)

Status: Steps 1–8 implemented; Step 9 pending cutover.

1) Update the V2 spec to match final decisions (archiving for projects/quellen/kapitels/runs + “7000 words max” policy), to keep implementation consistent:
- `FIRESTORE_V2_DATABASE_PLAN.md:99`
- `FIRESTORE_V2_DATABASE_PLAN.md:320`
- `FIRESTORE_V2_CODE_PLAN.md:24`

2) Implement the V2 Firestore rules in `firestore.rules` using the rules matrix/skeleton:
- `FIRESTORE_V2_DATABASE_PLAN.md:320`
- Mirror the 7000-word limit as a practical string size cap in rules (rules can’t count words) + enforce true word-count limit in app code.

3) Build the big-bang migration script (Admin SDK) with `--dry-run` and `--apply`, using the explicit old→new mapping:
- `FIRESTORE_V2_DATABASE_PLAN.md:420`
- `FIRESTORE_V2_DATABASE_PLAN.md:486`

4) Refactor FastAPI to V2 paths + V2 field naming/types (Quelle content doc, artifacts, groups, normalized costs/timestamps, and run progress counters):
- `FIRESTORE_V2_DATABASE_PLAN.md:67`
- `FIRESTORE_V2_DATABASE_PLAN.md:99`
- `FIRESTORE_V2_CODE_PLAN.md:196`

5) Add a Next.js Firestore refs/types layer and refactor server actions to V2 schema:
- `FIRESTORE_V2_CODE_PLAN.md:24`

6) Update Next.js realtime strategy:
- selected run listens to `artifacts/*` + `results/*`
- Kapitel status comes from denormalized fields (no per-Kapitel run listeners)
- intermediate groups load only when expanded
- `FIRESTORE_V2_CODE_PLAN.md:24`

7) Update refinement dialogs to V2 artifact paths + V2 versions paths and align “adopt version” updates with the new rules:
- `FIRESTORE_V2_CODE_PLAN.md:24`
- `FIRESTORE_V2_DATABASE_PLAN.md:67`

8) Remove legacy fallbacks (snake_case / ISO / cents / old paths), create required indexes, and run smoke checks:
- `FIRESTORE_V2_CODE_PLAN.md:330`
- `FIRESTORE_V2_DATABASE_PLAN.md:67`

9) Cutover (maintenance window):
- run migration
- deploy FastAPI + Next.js
- deploy Firestore rules
- verify end-to-end
- `FIRESTORE_V2_DATABASE_PLAN.md:420`
- `FIRESTORE_V2_CODE_PLAN.md:330`
