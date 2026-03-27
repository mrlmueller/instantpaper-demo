# InstantPaper (Next.js Frontend)

Temporary migration note: the product frontend now lives in `frontend/`, while the product backend is still in `fastapi/` until the backend move batch lands. This root README has not been fully rewritten yet, so treat path references below as transitional unless they already mention `frontend/`.

InstantPaper is a Next.js (App Router) web app for academic writing workflows:

- Manage sources ("Quellen") with text and optional images
- Organize sources into chapters ("Kapitels") inside projects ("Projekte")
- Start processing runs ("Runs") that call the FastAPI backend to generate results and derived artifacts (combined / shortened / lesefluss)
- Track usage and costs and export DOCX files

This repo contains both the frontend (`frontend/`) and the backend (`fastapi/`). Start here for the UI; see `fastapi/README.md` for backend setup and API docs.

---

## Table of contents

- [Quickstart (local dev)](#quickstart-local-dev)
- [Frontend scripts](#frontend-scripts)
- [Tech stack](#tech-stack)
- [Concepts / glossary](#concepts--glossary)
- [Feature tour (screens)](#feature-tour-screens)
- [Architecture (how it fits together)](#architecture-how-it-fits-together)
- [Data flow and realtime updates](#data-flow-and-realtime-updates)
- [Authentication flow](#authentication-flow)
- [Processing models and prompts](#processing-models-and-prompts)
- [Run lifecycle and statuses](#run-lifecycle-and-statuses)
- [Data limits and validation](#data-limits-and-validation)
- [Environment variables (frontend)](#environment-variables-frontend)
- [Firebase setup checklist](#firebase-setup-checklist)
- [Development workflow](#development-workflow)
- [Admin setup](#admin-setup)
- [Project structure (frontend)](#project-structure-frontend)
- [Next.js API routes](#nextjs-api-routes)
- [Firestore data model (frontend)](#firestore-data-model-frontend)
- [Images, storage, and exports](#images-storage-and-exports)
- [Local state and preferences](#local-state-and-preferences)
- [Security and privacy notes](#security-and-privacy-notes)
- [Deployment notes](#deployment-notes)
- [Testing](#testing)
- [Troubleshooting / FAQ](#troubleshooting--faq)

---

## Quickstart (local dev)

### Requirements

- Node.js 18.18+ (or 20+) and npm
- A Firebase project (Authentication + Firestore + Storage)
- For full stack dev: Python 3.10+ (backend), see `fastapi/README.md`

### 1) Install dependencies

```bash
cd frontend
npm install
```

### 2) Configure `.env.local`

Create `frontend/.env.local`:

```env
# Firebase Web App config (client-side)
NEXT_PUBLIC_FIREBASE_API_KEY=...
NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN=...
NEXT_PUBLIC_FIREBASE_PROJECT_ID=...
NEXT_PUBLIC_FIREBASE_STORAGE_BUCKET=...
NEXT_PUBLIC_FIREBASE_MESSAGING_SENDER_ID=...
NEXT_PUBLIC_FIREBASE_APP_ID=...
NEXT_PUBLIC_FIREBASE_MEASUREMENT_ID=...

# Backend base URL for server-side Next route handlers
FASTAPI_BASE_URL=http://localhost:8000
```

### 3) Start the backend

Follow `fastapi/README.md` to run FastAPI locally (default: `http://localhost:8000`).

### 4) Start the frontend

```bash
cd frontend
npm run dev
```

Open `http://localhost:3000`.

### 5) Grant access (`fullAccess`)

Login is always allowed. Without access, users are redirected to `/activate`.

Grant access by setting the Firebase custom claim `fullAccess: true` (legacy `approved: true` is accepted during migration):

- Use the backend access UI (`GET http://localhost:8000/approve`) or the admin endpoints described in `fastapi/README.md`.
- Then refresh the token (or sign out and sign in again) so the claim is applied.

---

## Frontend scripts

```bash
cd frontend
npm run dev     # start Next.js dev server (http://localhost:3000)
npm run build   # build for production
npm run start   # start production server
npm run lint    # eslint
```

---

## Tech stack

Frontend:

- Next.js 16 (App Router)
- React 19 + TypeScript
- Tailwind CSS 4
- shadcn/ui + Radix UI primitives
- Firebase Web SDK (Auth, Firestore, Storage)

Other notable libraries:

- `lucide-react` (icons)
- `sonner` (toasts)
- `next-themes` (theme handling)

Backend:

- FastAPI (Python) in `fastapi/`
- Firebase Admin SDK
- OpenAI Responses API

---

## Concepts / glossary

InstantPaper uses German domain terms in the UI and Firestore schema:

- **Projekt**: Top level container. You can have multiple projects.
- **Quelle**: A source document. Contains metadata (title, author, year, etc.), optional images, and the main text stored separately.
- **Kapitel**: A chapter within a project that references multiple Quellen.
- **Run**: A single processing run for a Kapitel. A run has settings (model, heading/topic, prompt selections, etc.) and produces:
  - **Results**: per-Quelle generated outputs (`runs/{runId}/results/{quelleId}`)
  - **Artifacts**: derived aggregated texts (`combined`, `shortened`, `lesefluss`)
- **Prompt templates**:
  - **User prompt templates**: per-user templates stored in Firestore and editable in the UI.
  - **System prompt templates**: server-managed templates (admin controlled) that can optionally be duplicated into a user's library (permission-gated).
- **Export**: A background job that produces a DOCX and uploads it to Firebase Storage.

---

## Feature tour (screens)

Main routes you will use while working with InstantPaper:

- `/login`  
  Google sign-in. Login is always allowed; access is gated via `fullAccess`.
- `/activate`  
  Activation gate (logged in, but no access): redeem Access Code or refresh token after admin grant.
- `/dashboard`  
  Main workspace: project selection, Kapitel list, Quellen panel, run creation, processing state, and artifacts (combined/shortened/lesefluss).
- `/quellen-manager`  
  Dedicated Quelle management (bulk edits, assignments, metadata).
- `/profil`  
  OpenAI key management, prompt templates, export history, and usage stats.
- `/admin`  
  Admin UI for users, access codes, and permissions (requires backend admin access).

---

## Architecture (how it fits together)

The system is split into three main parts:

1) **Next.js app (`frontend/`)**
- Handles UI, login, and most Firestore reads/writes.
- Server Actions in `app/actions/` mutate data and revalidate pages.
- Client components subscribe to Firestore for realtime updates.
- Calls the backend API for AI operations and admin functions.

2) **FastAPI backend (`fastapi/`)**
- Verifies Firebase auth.
- Runs OpenAI calls (including background tasks).
- Writes results/artifacts/exports back to Firestore/Storage.

3) **Firebase**
- Firestore stores all domain data (Quellen, Kapitels, Runs, Results, Artifacts, Exports, Prompt templates, cost metrics).
- Storage stores uploaded images and exported DOCX files.

High level data flow:

```
Browser UI
  -> Next.js (server actions + client components)
  -> Firestore (source-of-truth state)
  -> FastAPI (Bearer token) -> OpenAI
  -> Firestore/Storage (results, artifacts, exports)
  -> UI listens and updates
```

---

## Data flow and realtime updates

The UI is designed to be reactive:

- After a run starts, the frontend writes the run document and then queues per-Quelle processing calls to FastAPI.
- The backend updates result and artifact documents in Firestore as jobs complete.
- The UI uses Firestore `onSnapshot` listeners to stream updates in real time:
  - Run list
  - Results per Quelle
  - Artifacts (combined/shortened/lesefluss)
  - Refinement versions
  - Exports

This makes the UI responsive even while backend tasks are running.

---

## Authentication flow

InstantPaper uses Firebase Auth (Google provider) and an access gate.

- Client login uses Firebase Web SDK (`app/lib/firebase/auth.ts`).
- The current Firebase ID token is stored in the `__session` cookie (used by Next.js Server Components).
- Protected routes use the `app/(protected)/layout.tsx` server layout, which calls `requireFullAccess()`.
  - If there is no cookie: redirect to `/login`.
  - If a cookie exists but the token is expired: pages render and the client refreshes the token automatically.
- If logged in but missing access (`fullAccess` or legacy `approved`): redirect to `/activate` (user stays logged in).
- Hard blocks are stored in Firestore (`users/{uid}.accountStatus = "blocked"`) and are enforced immediately (Firestore rules + backend).

---

## Processing models and prompts

### Models

Available processing models in the UI:

- `gpt-5-nano`
- `gpt-5-mini`
- `gpt-5.2`

Default selection:

- Development: `gpt-5-nano`
- Production: `gpt-5.2`

The selected model is stored on the run and the backend may override a request to match the run model.

### Prompt stages

Prompt stages used throughout the app:

- `process_quelle`
- `combine`
- `summary`
- `shorten`
- `lesefluss`

Prompt selection details:

- User templates are stored under `users/{uid}/promptTemplates`.
- Active selections live in `users/{uid}/promptSettings/active.activeTemplates`.
- If `askOnEachProcess` is true, the UI asks for prompt selection each time a run starts.
- System prompt templates are fetched from the backend; if the backend is unreachable, the UI hides them (fail closed).
- Required placeholders are enforced per stage (see `app/lib/prompts/promptConfig.ts`).

---

## Run lifecycle and statuses

Runs are the unit of AI processing for a Kapitel.

### Creating a run

- A run is created in Firestore under `users/{uid}/kapitels/{kapitelId}/runs/{runId}`.
- The run stores settings such as model, heading, topic, prompt selections, and `autoCombine` (direct combine).

### Processing a run

- The frontend queues each Quelle for processing (current UI concurrency is limited to 3).
- For each Quelle, FastAPI writes a placeholder result doc with `status=running`.
- When OpenAI finishes, the result doc is updated to `success`, `error`, or `no-content`.

### Artifacts

Artifacts are derived texts created from a run:

- `combined`: merges all results
- `shortened`: shorter, deduplicated Kapitel text
- `lesefluss`: improves reading flow across chapters

Artifact docs follow the same status scheme as results.

### Status values

Common status fields:

- Results: `running` | `success` | `error` | `no-content`
- Artifacts: `running` | `success` | `error`

The run document also tracks counters for UI progress:

- `resultsExpectedCount`
- `resultsCompletedCount`
- `resultsWithContentCount`
- `resultsRunningCount`
- `artifactsStatus` and `artifactsRunningCount`
- `refinementRunningCount` (used by refinement dialogs)

---

## Data limits and validation

These limits are enforced in server actions and the UI:

- Quelle content length:  
  - max 7,000 words  
  - max 140,000 characters  
  (see `app/actions/quellen.ts`)
- Prompt template limits:  
  - max 10 templates per stage  
  - name length 3 to 80 characters  
  - required placeholders must be present for each stage  
  (see `app/lib/prompts/promptConfig.ts`)
- External image proxy (`/api/external-image`):  
  - max 8 MB per image  
  - max 3 redirects  
  - 10s timeout  
  - http/https only  
  - blocks private/local IPs (SSRF protection)

Archiving behavior:

- Projects, Quellen, and Kapitels are archived instead of hard deleted.
- Archived items can be restored later from the UI.

---

## Environment variables (frontend)

All frontend env vars live in `.env.local` (root) and must start with `NEXT_PUBLIC_` if they are used in client components.

### Firebase web config

Used by `app/lib/firebase/config.ts`.

- `NEXT_PUBLIC_FIREBASE_API_KEY`
- `NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN`
- `NEXT_PUBLIC_FIREBASE_PROJECT_ID`
- `NEXT_PUBLIC_FIREBASE_STORAGE_BUCKET`
- `NEXT_PUBLIC_FIREBASE_MESSAGING_SENDER_ID`
- `NEXT_PUBLIC_FIREBASE_APP_ID`
- `NEXT_PUBLIC_FIREBASE_MEASUREMENT_ID` (optional but recommended)

### Backend base URL

Used in various client/server helpers when calling FastAPI.

- `NEXT_PUBLIC_FASTAPI_URL` (preferred; default fallback is `http://localhost:8000`)
- `NEXT_PUBLIC_API_URL` (legacy fallback for a small subset of calls; set it to the same value)

---

## Firebase setup checklist

This is the minimal Firebase setup required for local dev and production.

### 1) Create Firebase project

In Firebase Console:

- Create a project
- Enable **Authentication**:
  - Sign-in method: **Google**
  - Add your app domain(s) to authorized domains (for production)
- Create a **Web app** and copy the config values into `.env.local`
- Enable **Firestore** (Native mode)
- Enable **Storage**

### 2) Rules

This repo contains rules files:

- Firestore rules: `firestore.rules`
- Storage rules: `storage.rules`

How you deploy rules depends on your Firebase CLI setup. If you do not have a `firebase.json` yet:

```bash
firebase init
firebase deploy --only firestore:rules,storage
```

---

## Development workflow

### Run both servers

- Terminal 1 (frontend): `npm run dev` (http://localhost:3000)
- Terminal 2 (backend): see `fastapi/README.md` (http://localhost:8000)

### Typical flow in the UI

1) Create or select a Projekt
2) Add Quellen (text, optional images, metadata)
3) Create or select a Kapitel and assign Quellen
4) Start a Run and choose model and options
5) The UI calls FastAPI per Quelle and shows progress while Firestore updates stream in
6) Optionally combine, shorten, or improve lesefluss and export DOCX

---

## Admin setup

There are two "admin" mechanisms:

1) **Approving users (allowlist)** via backend Basic Auth endpoints  
   - Requires `fastapi/.env` `ADMIN_BASIC_PASSWORD` (and optionally `ADMIN_BASIC_USER`).
   - Use `http://localhost:8000/approve` to approve or revoke by email.

2) **Admin UI in Next.js (`/admin`)** via Firebase UID allowlist  
   - Requires `fastapi/.env` `ADMIN_UIDS` (comma-separated Firebase Auth UIDs).
   - To find your UID:
     - Firebase Console -> Authentication -> Users (UID column), or
     - read it from the UI/Firestore user doc after first login (InstantPaper writes `users/{uid}`).

Admin UI controls:

- Approve or revoke users
- Allow or block the platform OpenAI key per user
- Allow or block system prompt duplication per user
- Manage system prompt templates (server managed prompts)

---

## Project structure (frontend)

Key folders/files:

- `app/`: Next.js routes + server actions
  - `app/(auth)/login`: login page
  - `app/(protected)/dashboard`: main UI (protected)
  - `app/(protected)/profil`: profile (OpenAI key, exports, stats, prompt manager)
  - `app/(protected)/quellen-manager`: Quellen management
  - `app/admin`: admin UI (requires backend admin access)
  - `app/actions/`: Firestore mutations (server actions)
  - `app/components/`: UI components and dialogs
  - `app/lib/`: Firebase setup, helpers, Firestore refs, prompt config
  - `app/types/`: shared types
- `components/ui/`: shadcn/ui components
  - Do not edit manually; use the shadcn CLI if you need changes
- `lib/`: shared helpers (frontend)
- `public/`: static assets
- `proxy.ts`: route gate logic (used for auth checks)

Related docs:

- `CLAUDE.md`: repo-level development notes and architecture overview
- `fastapi/README.md`: backend setup and API docs

---

## Next.js API routes

Route handlers under `app/api/` provide thin server-side wrappers or security gates:

- `GET/POST /api/prompt-templates`  
  List and create user prompt templates (server actions).
- `GET/POST /api/prompt-templates/active`  
  Read or set the active template per stage.
- `GET/POST /api/prompt-templates/settings`  
  Read or update prompt UI settings (e.g. ask on each process).
- `POST /api/system-prompt-templates/duplicate`  
  Proxy to FastAPI to duplicate a system prompt into the user library.
- `GET/POST /api/admin/system-prompt-templates`  
  Admin-only proxy to manage system prompt templates in FastAPI.
- `GET /api/external-image?url=...`  
  SSRF-protected image proxy for external sources.

These routes use the `__session` cookie for auth and run on the server.

---

## Firestore data model (frontend)

Firestore paths are centralized in `app/lib/firestore/refs.ts`. The most important collections:

```
users/{uid}
  projects/{projectId}
  quellen/{quelleId}
    content/main
  kapitels/{kapitelId}
    runs/{runId}
      results/{quelleId}
      artifacts/{artifactId}   # combined | shortened | lesefluss
  exports/{exportId}
  promptTemplates/{templateId}
  promptSettings/active
```

Additional backend-driven collections:

- `users/{uid}/costMetrics/v1/*` (usage and cost aggregates)
- `users/{uid}/secrets/openai` (encrypted OpenAI key)
- `systemPromptTemplates/*` (server managed prompt templates)

Notes:

- Quelle text is stored in `quellen/{quelleId}/content/main` (separate doc) so the main Quelle doc can stay small and fast.
- The backend also writes into this structure (results, artifacts, exports), so Firestore is the shared state between frontend and backend.
- Optional Quelle metadata fields include: `autor`, `jahr`, `typ` (Book/Article/Website/Thesis/Report), `url`, `zugriffAm`, `zitat`, `zitatModus`, `color`, and `images[]`.

---

## Images, storage, and exports

### Image uploads (Quellen)

- Images are uploaded client-side to Firebase Storage under:
  - `users/{uid}/quellen/{tempId}/{timestamp}_{index}_{filename}`
- The Quelle document stores metadata: `url`, `path`, `filename`, `size`, `contentType`.
- If Quelle creation fails, uploaded images are cleaned up.
- The backend reads stored image URLs and can include them in OpenAI calls.

### Exports

- DOCX exports are created by the backend and uploaded to Storage.
- The UI downloads exports via authenticated `getBlob` to respect Storage rules.

### External images

- External URLs are fetched through `GET /api/external-image?url=...`.
- The proxy rejects private IPs, enforces size limits, and allows only http/https.

---

## Local state and preferences

The frontend stores a few UI preferences locally:

- Cookies:
  - `instantpaper_active_project`
  - `instantpaper_active_kapitel_<projectId>`
- localStorage:
  - `instantpaper_quellen_panel_open`
  - `instantpaper_quellen_mode_advanced`
  - `instantpaper_lesefluss_aufgabenstellung_<projectId>`

Firebase auth uses the `__session` cookie to share the current ID token between client and server components.

---

## Security and privacy notes

- OpenAI keys are never stored in the frontend; they are sent to the backend and encrypted at rest.
- The app is gated via the Firebase custom claim `fullAccess` (legacy `approved` accepted during migration).
  - Without access, users are redirected to `/activate` and Firestore/Storage/Backend access is denied.
  - Hard blocks are stored in Firestore (`users/{uid}.accountStatus = "blocked"`) and are enforced immediately for new actions.
- External images are proxied with SSRF protection.
- `.env.local` is ignored by git and should never be committed.

For backend security details, see `fastapi/README.md`.

---

## Deployment notes

### Frontend (Vercel / Node hosting)

- Set all `.env.local` values as production environment variables in your hosting provider.
- Ensure the backend URL is reachable from the browser (public HTTPS URL) and set `NEXT_PUBLIC_FASTAPI_URL`.

### Backend

- Deploy the backend separately (see `fastapi/README.md`).
- Ensure `fastapi/.env` `ALLOWED_ORIGINS` contains your frontend production origin(s).

---

## Testing

There are no dedicated frontend test suites in this repo. Suggested checks:

```bash
npm run lint
```

For end to end validation, run both servers locally and walk through:

1) Login and activation / access grant
2) Create a project, sources, and a run
3) Process sources and verify results and artifacts update
4) Export DOCX and download

---

## Troubleshooting / FAQ

### "Firebase ist nicht konfiguriert ..."

- Missing or empty `NEXT_PUBLIC_FIREBASE_*` env vars. Create `.env.local` and restart `npm run dev`.

### 403 "Account not authorized"

- Your Firebase user has no access (`fullAccess`) or is blocked.
  - Grant/revoke access in `/admin` or via `fastapi/README.md` and refresh the token.
  - If blocked, unblock first (hard gate).

### Firestore permission errors

- Check your Firestore rules (`firestore.rules`) and confirm you are using the correct Firebase project.

### CORS errors when calling FastAPI

- Add your frontend origin to `fastapi/.env` `ALLOWED_ORIGINS` (comma-separated) and restart FastAPI.

### Prompt template errors (missing placeholders)

- Each prompt stage requires specific placeholders. See `app/lib/prompts/promptConfig.ts` for the required list.

### Protected pages show a loading skeleton forever

- Often indicates an expired or invalid `__session` cookie that cannot be refreshed.
- Try signing out (or clear the `__session` cookie) and sign in again.

### "Kein OpenAI API Key hinterlegt"

- Add a user OpenAI key in the Profile page, or allow platform key for the user via the admin UI/backend.

### Image preview or download problems

- External images are fetched via `GET /api/external-image?url=...` with SSRF protections.
- If an image host resolves to private IP ranges or redirects too often, it is blocked by design.

### Export stuck in "running"

- Check FastAPI logs and the export doc under `users/{uid}/exports/{exportId}`.
- Restarting the backend stops background tasks; re-trigger the export if needed.

### "Network error" / backend unreachable

- Confirm FastAPI is running and `NEXT_PUBLIC_FASTAPI_URL` points to it.
