# InstantPaper Frontend

This directory contains the production web application for InstantPaper.

Stack:

- Next.js 16 App Router
- React 19
- TypeScript
- Tailwind CSS 4
- Firebase Web SDK

The frontend is responsible for UI, auth/session handling, realtime Firestore views, and the backend-for-frontend route handlers that proxy product API traffic to FastAPI.

## Scope

`frontend/` owns:

- route groups under `app/`
- reusable UI components under `components/`
- Firebase client utilities under `app/lib/firebase/`
- server-side API proxy helpers under `app/lib/server/`
- BFF route handlers under `app/api/`
- auth/access gating in `proxy.ts`

It does not own:

- OpenAI execution
- heavy processing orchestration
- PDF scan worker runtime
- two-lane sources worker runtime

Those live in [backend](../backend).

## Requirements

- Node.js 20+ recommended
- npm
- a working Firebase web app configuration
- a reachable backend URL for `FASTAPI_BASE_URL`

## Environment Variables

Copy the template:

```bash
cp .env.local.example .env.local
```

Current template values:

```env
NEXT_PUBLIC_FIREBASE_API_KEY=
NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN=
NEXT_PUBLIC_FIREBASE_PROJECT_ID=
NEXT_PUBLIC_FIREBASE_STORAGE_BUCKET=
NEXT_PUBLIC_FIREBASE_MESSAGING_SENDER_ID=
NEXT_PUBLIC_FIREBASE_APP_ID=
NEXT_PUBLIC_FIREBASE_MEASUREMENT_ID=
NEXT_PUBLIC_FIREBASE_FUNCTIONS_REGION=europe-west3

FASTAPI_BASE_URL=http://localhost:8000

NEXT_PUBLIC_STRIPE_SUBSCRIPTION_PRICE_ID=
NEXT_PUBLIC_STRIPE_TOPUP_PRICE_ID=
NEXT_PUBLIC_STRIPE_PORTAL_FUNCTION_NAME=
```

What they do:

- `NEXT_PUBLIC_FIREBASE_*`
  - Firebase web config used by the browser client
- `NEXT_PUBLIC_FIREBASE_FUNCTIONS_REGION`
  - region for Firebase callable functions used by billing UI
- `FASTAPI_BASE_URL`
  - server-only base URL for Next route handlers that proxy to FastAPI
- `NEXT_PUBLIC_STRIPE_SUBSCRIPTION_PRICE_ID`
  - frontend default subscription price ID
- `NEXT_PUBLIC_STRIPE_TOPUP_PRICE_ID`
  - frontend default one-time top-up price ID
- `NEXT_PUBLIC_STRIPE_PORTAL_FUNCTION_NAME`
  - override for the Stripe extension portal callable name

Important:

- `FASTAPI_BASE_URL` is intentionally not public
- browser code should not call the FastAPI deployment directly for normal product API flows
- exception: large PDF uploads in `/pdf-scan` bypass the Next BFF and post directly to FastAPI with the current Firebase ID token to avoid Next's proxy body-size ceiling; the backend `ALLOWED_ORIGINS` list must therefore include the frontend origin

## Install and Run

Install dependencies:

```bash
npm install
```

Start dev server:

```bash
npm run dev
```

Build production bundle:

```bash
npm run build
```

Start production server locally:

```bash
npm run start
```

Lint:

```bash
npm run lint
```

## Architecture

### Auth and route gating

[proxy.ts](proxy.ts) enforces the top-level route policy:

- users without a session cookie are redirected to `/login`
- users with a valid session but without access are redirected to `/activate`
- API routes are left alone so they can return JSON errors directly
- the gate accepts `fullAccess` and, during migration, legacy `approved`

### Backend-for-frontend layer

The product now uses Next route handlers as the primary API boundary to FastAPI.

Examples:

- [app/api/process/route.ts](app/api/process/route.ts)
- [app/api/billing/status/route.ts](app/api/billing/status/route.ts)
- [app/api/quellen-finder/pdf-scan/route.ts](app/api/quellen-finder/pdf-scan/route.ts)
- [app/api/admin/users/[uid]/route.ts](app/api/admin/users/[uid]/route.ts)

Shared server helpers:

- [app/api/_fastapiProxy.ts](app/api/_fastapiProxy.ts)
- [app/api/admin/_fastapiProxy.ts](app/api/admin/_fastapiProxy.ts)
- [app/lib/server/fastapi.ts](app/lib/server/fastapi.ts)

This means:

- browser code talks to `/api/...` on the Next app
- Next server code talks to FastAPI using `FASTAPI_BASE_URL`
- auth cookies and headers are normalized in one place
- large PDF uploads for PDF scan are the intentional exception and go browser -> FastAPI directly

### Firebase direct usage

The frontend still talks directly to Firebase for the client-side product state:

- Firebase Auth
- Firestore subscriptions and writes
- Storage uploads/downloads

Billing also uses the Firebase Stripe extension directly for:

- `customers/{uid}/checkout_sessions` document creation
- the callable function `ext-firestore-stripe-payments-createPortalLink`

That logic lives in:

- [app/lib/firebase/stripeCheckout.ts](app/lib/firebase/stripeCheckout.ts)
- [app/lib/firebase/functionsClient.ts](app/lib/firebase/functionsClient.ts)

## Directory Guide

```text
frontend/
|- app/                routes, layouts, server actions, route handlers
|- components/         shared UI and feature components
|- public/             static assets
|- proxy.ts            auth/access gate
|- package.json        frontend scripts and dependencies
`- tsconfig.json       TypeScript config
```

Notable route groups:

- `app/(auth)` login flow
- `app/(gate)` activation flow
- `app/admin` admin UI
- `app/api` BFF route handlers

## Local Development Flow

Typical full-stack local setup:

1. run the backend on `http://localhost:8000`
2. set `FASTAPI_BASE_URL=http://localhost:8000`
3. run `npm run dev`
4. open `http://localhost:3000`

If a user can log in but is redirected to `/activate`, grant access via backend admin tooling or an access code and then refresh the token.

## Deployment

Expected platform: Vercel.

Required Vercel configuration:

- Root Directory: `frontend/`
- install command: `npm install`
- build command: `npm run build`
- output: standard Next.js output

Required environment variables:

- all `NEXT_PUBLIC_FIREBASE_*` values
- `FASTAPI_BASE_URL`
- Stripe-related `NEXT_PUBLIC_*` values if defaults are not desired

The repo-root [`.vercelignore`](../.vercelignore) excludes `backend/` and `testing-scripts/` from the Vercel upload context.

## Verification

Useful checks:

```bash
npm run build
npm run lint
npx tsc --noEmit --pretty false
```

`npm run lint` may still report pre-existing lint debt; treat it as a cleanup signal, not as evidence that the directory move was wrong.

## Known Transitional Details

- route gating still tolerates the legacy Firebase claim `approved`
- billing portal access depends on the Firebase Stripe extension callable function
- the frontend assumes Firebase is the source of truth for most user-facing state

## Related Documentation

- repo overview: [README.md](../README.md)
- backend runtime: [backend/README.md](../backend/README.md)
