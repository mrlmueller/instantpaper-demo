# instantpaper Frontend

Die Web-Anwendung von instantpaper: Next.js 16 mit App Router, React 19,
TypeScript und Tailwind 4, deployt auf Vercel. Was das Produkt tut, steht im
[Haupt-README](../README.md), hier steht, wie diese Hälfte gebaut ist.

## Was dieser Teil verantwortet

Das Frontend rendert die Oberfläche, hält die Anmeldung und zeigt die
Live-Daten aus Firestore. Außerdem stellt es die Route Handlers unter
`app/api/`, über die der Browser mit dem Backend spricht: sie prüfen das
Anmelde-Token und reichen die Anfrage an die FastAPI weiter. Der Browser ruft
das Backend also nie direkt, mit einer Ausnahme: große PDF-Uploads im PDF-Scan
gehen direkt an die FastAPI, weil die Weiterleitung über Next eine Grenze für
die Größe des Anfragekörpers hat. Deshalb muss das Backend die
Frontend-Adresse in seiner `ALLOWED_ORIGINS`-Liste führen.

Die Zugangskontrolle auf Seitenebene liegt in [proxy.ts](proxy.ts): ohne
Session-Cookie geht es zur Anmeldung, mit Anmeldung aber ohne Freischaltung
zur Warteseite, und API-Routen bleiben unangetastet, damit sie eigene
JSON-Fehler zurückgeben können.

## Aufbau

```text
frontend/
|- app/                Seiten, Layouts, Server Actions, Route Handlers
|- components/         geteilte UI- und Feature-Komponenten
|- public/             statische Dateien
|- proxy.ts            Zugangs-Gate
`- package.json        Skripte und Abhängigkeiten
```

Die wichtigsten Routengruppen: `app/(auth)` ist der Login, `app/(gate)` die
Freischalt-Warteseite, `app/(protected)` die Arbeitsflächen (Dashboard,
Quellen-Manager, Quellen-Finder, PDF-Scan), `app/admin` der Admin-Bereich und
`app/api` die Route Handlers zum Backend.

Für Anmeldung, Firestore und Storage nutzt der Browser Firebase direkt. Auch
die Bezahlung läuft direkt über Firebase: Checkout-Sitzungen entstehen als
Firestore-Dokumente unter `customers/{uid}/checkout_sessions`, die die
Firebase-Stripe-Erweiterung verarbeitet, und das Kundenportal öffnet eine
Callable Function derselben Erweiterung
([app/lib/firebase/stripeCheckout.ts](app/lib/firebase/stripeCheckout.ts)).

## Lokal starten

```bash
cp .env.local.example .env.local
npm install
npm run dev
```

Die App läuft dann auf `http://localhost:3000` und erwartet das Backend unter
der Adresse aus `FASTAPI_BASE_URL`, standardmäßig `http://localhost:8000`.
Die Firebase-Werte in der `.env.local` kommen aus der Web-App-Konfiguration
des eigenen Firebase-Projekts. `FASTAPI_BASE_URL` ist bewusst keine
`NEXT_PUBLIC_`-Variable, denn sie wird nur serverseitig von den Route
Handlers benutzt.

Bauen und prüfen:

```bash
npm run build
npm run lint
npx tsc --noEmit
```

## Deployment

Vercel mit `frontend/` als Root Directory, Standard-Next-Build. Gebraucht
werden alle `NEXT_PUBLIC_FIREBASE_*`-Werte, `FASTAPI_BASE_URL` und die
Stripe-Preis-IDs. Die Datei [.vercelignore](../.vercelignore) im
Repository-Root hält `backend/` und `testing-scripts/` aus dem Upload heraus.

## Hinweise

Das Zugangs-Gate akzeptiert neben dem Claim `fullAccess` noch den älteren
Claim `approved`, ein Rest der Migration. Die Quelle der Wahrheit für fast
alle Nutzerdaten ist Firebase, das Frontend hält keinen eigenen Zustand
darüber hinaus.
