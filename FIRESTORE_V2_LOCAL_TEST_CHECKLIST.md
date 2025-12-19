# Firestore V2 — Local Cutover & Smoke Checklist (no deploy)

This is Step 9 for local testing with a wiped database.

## Preconditions
- Firestore is empty (you already wiped it).
- `firestore.rules` already match V2.
- FastAPI + Next.js are pointing at the same Firebase project.

## 1) Create required composite indexes (if needed)
The V2 code uses queries that can require composite indexes (e.g. Kapitels by `projektId+archived` ordered by `order`, Quellen by `projektId+archived` ordered by `createdAt`).

- If you see a Firestore error like “The query requires an index”, open the provided console link and create it.
- The canonical definition is in `firestore.indexes.json`.

## 2) Start FastAPI locally
- From `fastapi/`, start your server the same way you normally do (uvicorn).
- Ensure the Firebase Admin credentials/env vars are present (whatever you already use in `fastapi/.env`).

## 3) Start Next.js locally
- `npm run dev`

## 4) Smoke flows (should work end-to-end)
- Open `/dashboard` (default project should auto-create).
- Create a Quelle and verify:
  - metadata doc exists at `users/{uid}/quellen/{quelleId}`
  - content doc exists at `users/{uid}/quellen/{quelleId}/content/main`
- Create a Kapitel and assign Quellen.
- Create a run and verify the V2 write layout:
  - run doc: `users/{uid}/kapitels/{kapitelId}/runs/{runId}`
  - results: `.../runs/{runId}/results/{quelleId}`
  - artifacts: `.../runs/{runId}/artifacts/{combined|shortened|lesefluss}`
- Expand “Zwischengruppen” and verify groups only load on expand:
  - `.../runs/{runId}/artifacts/combined/groups/*`
- Open refinement dialogs and verify:
  - versions are under `.../artifacts/{artifactId}/versions/*` (and for result: `.../results/{quelleId}/versions/*`)
  - “Version übernehmen” updates only `content`, `updatedAt`, and `refinement.*` on the root doc.
- Archive behavior:
  - deleting a project/quelle/kapitel/run archives it (no hard delete).
