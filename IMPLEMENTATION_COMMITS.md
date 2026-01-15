# InstantPaper - Komplettguide (Branches + Commits + Setup außerhalb von Code)

Dieses Dokument ist der **vollständige Schritt‑für‑Schritt Leitfaden**, um die Public‑Beta‑Umstellung aus `PLAN_PUBLIC_BETA.md` sauber umzusetzen – inkl. **externer Konfiguration** (Stripe, Firebase, Deployments), nicht nur Code‑Commits.

Ziel: Alles ist in wenige, gut reviewbare Schritte zerlegt, sodass du **Commit für Commit** implementieren kannst, ohne dass „alles gleichzeitig“ bricht.

Constraints:

- Max. **3 Branches**.
- Jeder Commit ist „mergebar“ (App läuft weiterhin), idealerweise mit klarer manueller Checkliste.
- Keine Code‑Snippets in diesem Dokument – nur Arbeitsanweisungen, Scope, Akzeptanzkriterien, Setup‑Schritte.

---

## 0) Finales Credit‑Modell (Source of Truth)

Diese Zahlen sind ab jetzt „Source of Truth“ für alle folgenden Schritte:

- **Purchase-Rate (Kauf)**: `$1 bezahlt -> 3 Credits`
- **Spend-Rate (Verbrauch, Default)**: `OpenAI $1 Kosten -> 6 Credits`
- **Subscription Bonus (Abo)**: +`10 Credits` pro bezahlter Periode (damit `$25` Abo -> `85 Credits` statt `75`)
- **Folge (Default)**: `$1 bezahlt -> $0.50 OpenAI-Budget`
- Beispiel: `$10` bezahlt -> `30 Credits` -> entspricht `$5` OpenAI-Budget -> wenn OpenAI-Kosten `$5`, werden `30 Credits` verbraucht.

Wichtig:

- Stripe läuft in **USD** (OpenAI ebenfalls). EU‑User zahlen faktisch in EUR über Karten‑/Issuer‑Umrechnung; intern rechnest du in USD.
- Credits sind eine **interne Einheit** (nicht „$“). In der UI sollten Credits sichtbar sein, nicht OpenAI‑Dollar.

---

## 1) Branch‑Strategie (nur 3 Branches)

**Branch A – `beta/access-codes`**

- Fokus: Login bleibt erlaubt, aber App ist ohne `fullAccess` nicht nutzbar; `/activate` Gate + Codes + Admin‑Sperre (sofort wirksam).
- Ergebnis: Public Signup ist möglich, aber ohne Freischaltung kommt man nicht „in die App“.

**Branch B – `beta/billing-credits`**

- Fokus: Credits‑Ledger + per‑User Spend‑Rate + Stripe (Abo + Top‑up) + Profil/Billing + Admin‑Adjustments + Entfernen der OpenAI‑Key UI.
- Ergebnis: Monetarisierung ist live, Credits sind „Source of Truth“.

**Branch C – `beta/public-pages`**

- Fokus: Public Pages (How it works, Pricing, Terms, Privacy, Impressum) + Verlinkung.
- Ergebnis: Launch‑würdig „nach außen“.

**Merge‑Reihenfolge**:

1. `beta/access-codes` -> `main`
2. `beta/billing-credits` -> `main`
3. `beta/public-pages` -> `main`

Warum?

- Access‑Codes/Gating lösen zuerst „wer darf rein“ und stabilisieren den Auth‑Flow.
- Billing/Credits ist die größte Änderung – besser erst bauen, wenn Onboarding/Gating sauber ist.
- Public Pages sind relativ unabhängig und können zuletzt (oder parallel) finalisiert werden.

---

## 2) Setup außerhalb von Code (One‑time + pro Umgebung)

Du brauchst idealerweise **2 Umgebungen**:

- **Staging/Test**: Stripe Test Mode + (optional) separates Firebase Project oder zumindest klare Test‑User.
- **Production**: Stripe Live Mode + echtes Firebase Projekt.

Wenn du nur 1 Firebase Projekt nutzt: arbeite zumindest mit separaten Test‑Accounts und sei strikt bei „Live Keys“ vs „Test Keys“.

### 2.1 Firebase – Console Tasks (einmalig)

1. **Authentication**
   - Google Provider aktiv.
   - **Authorized domains**: Vercel Domain + Custom Domain hinzufügen (sonst Login‑Probleme).
2. **Firestore + Storage Rules Deployment Prozess**
   - Stelle sicher, dass du Firestore **und** Storage Rules zuverlässig deployen kannst (Firebase CLI Zugriff).
3. **Admin‑Zugriff**
   - Lege fest, welche Firebase UIDs Admin sind (dein Account, ggf. 1 Backup).
   - Backend‑Env `ADMIN_UIDS` setzen (damit `/admin` funktioniert).
4. **Custom Claims**
   - Ziel‑Claim: `fullAccess` (Vollzugriff).
   - Legacy‑Claim `approved` nur für Migration (zeitlich begrenzen).

### 2.2 Stripe – Dashboard Tasks (Test Mode zuerst)

Diese Schritte sind „außerhalb von Code“. Sie müssen passieren, bevor Stripe‑Flows live funktionieren.

1. **Business / Branding**
   - Business Name, Logo, Support Email, Statement Descriptor prüfen.
2. **Subscription Produkt**
   - Produkt anlegen (z.B. „InstantPaper“).
   - Preis: **$25 / Monat**, recurring monthly, currency USD.
   - **Price ID** notieren (Config/Env).
3. **Customer Portal**
   - Customer Portal aktivieren.
   - Features: kündigen, Zahlungsmethode ändern, Rechnungen anzeigen (mindestens).
4. **Webhooks**
   - Webhook‑Endpoint URL definieren (FastAPI, öffentlich erreichbar, HTTPS).
   - Events auswählen (mindestens: erfolgreiche Zahlungen für Subscription/Top‑up und Subscription Renewal/Status).
   - **Signing Secret** notieren (Config/Env).
5. **Top‑up Strategie**
   - „Custom Amount“ (>= $5). Typisch: Checkout‑Flow, bei dem der Betrag serverseitig gesetzt wird.
   - Optional: „Top‑up“ Produkt für saubere Receipts/Portal‑Darstellung.
6. **Steuern/VAT (DE/EU) – Entscheidung**
   - Optional, aber wichtig: prüfen, ob du VAT/Stripe Tax aktivieren musst.

### 2.3 Hosting/Deploy – Voraussetzungen

1. **FastAPI öffentlich erreichbar**
   - Muss per HTTPS erreichbar sein, sonst können Stripe Webhooks nicht zustellen.
2. **CORS**
   - `ALLOWED_ORIGINS` im Backend muss deine Frontend Domains enthalten.
3. **Environment Variables**
   - Backend (FastAPI): OpenAI Key, Stripe Secret Key, Stripe Webhook Secret, Price IDs, Admin UIDs, Encryption Key usw.
   - Frontend (Vercel): `NEXT_PUBLIC_FASTAPI_URL` (und Firebase Web Config).
4. **Secrets Handling**
   - Stripe Secret Key/Webhook Secret niemals ins Frontend.
   - Test vs Live sauber trennen (auch in Vercel Environments).

---

## 3) Branch A: `beta/access-codes` (Gating + Codes + sofortige Sperre)

### Commit A1 — „Docs: Access‑Logik + Access‑Code Regeln finalisieren“

**Kontext**: Begriffe/Regeln müssen eindeutig sein, bevor Datenmodell, Rules und Admin UI gebaut werden.
**Änderungen (im Repo)**:

- `PLAN_PUBLIC_BETA.md` finalisieren/abgleichen:
  - Claim‑Ziel: `fullAccess`
  - Migration: `approved || fullAccess` akzeptieren (nur temporär).
  - Gate‑Regel: eingeloggt ohne `fullAccess` -> `/activate`.
  - Block‑Regel: serverseitiger User‑Status (z.B. `accountStatus="blocked"`) muss **sofort** neue Aktionen verhindern.
- Access‑Code Regeln fixieren:
  - Default `maxUses = 1`, aber konfigurierbar.
  - Code kann deaktiviert werden.
  - Admin sieht Name, createdAt, used/maxUses, lastUsedAt, Liste aktivierter Accounts.
  - Redeem ist idempotent (wenn User schon `fullAccess` hat: kein Verbrauch).
  **Akzeptanzkriterien**:
- Du kannst die Regeln in 60 Sekunden erklären, ohne Interpretationslücken.

### Commit A2 — „Auth‑Flow: Login erlaubt, Gate über `fullAccess`“

**Kontext**: Login soll immer möglich sein; ohne `fullAccess` ist die App aber nicht nutzbar.
**Änderungen (im Repo)**:

- Login/Session‑Handling so anpassen, dass:
  - Google Login funktioniert.
  - User nach Login **eingeloggt bleibt**, auch ohne `fullAccess`.
  - Session Cookie wird trotzdem gesetzt (Server Components/Actions brauchen Auth).
  - Access‑Check basiert auf `fullAccess` (Migration optional: `approved || fullAccess`).
- Route Guard:
  - Wenn eingeloggt, aber **kein** `fullAccess`: Redirect auf `/activate`.
  - Whitelist (kein Redirect): `/activate`, `/login`, `/admin` und Public Pages.
  **Manuelle Checks**:
- Neuer User (ohne `fullAccess`) kann sich einloggen und landet auf `/activate`.
- Bestehender User (Legacy `approved`) kommt weiterhin ins Dashboard (bis Migration abgeschlossen ist).

### Commit A3 — „Activation Gate Seite (`/activate`)“

**Kontext**: User ohne `fullAccess` sollen nach Login nicht rausfliegen, aber auch nichts in der App machen können.
**Änderungen (im Repo)**:

- Neue Seite `/activate`:
  - Code Input
  - „Einlösen“ Button
  - „Logout“ Button
  - Optional: „Neu prüfen“/„Weiter“ Button, der Token Refresh triggert (damit Admin‑Freischaltung ohne Re‑Login klappt).
  - Klarer Text, was zu tun ist.
- Routing‑Regel: wenn eingeloggt aber **kein** `fullAccess` -> redirect auf `/activate`.
  **Akzeptanzkriterien**:
- Egal welche geschützte Route: ohne `fullAccess` landet man immer auf `/activate`.
- Nach erfolgreicher Aktivierung (Code oder Admin) kommt man **ohne neues Login** weiter (Token Refresh reicht).

### Commit A4 — „Backend: Redeem‑Code Endpoint (setzt `fullAccess` + loggt Nutzung)“

**Kontext**: `fullAccess` muss serverseitig gesetzt werden; Client darf das nicht. Redeem muss auch ohne `fullAccess` erreichbar sein, sonst kann niemand aktivieren.
**Änderungen (im Repo)**:

- FastAPI Endpoint für Code‑Einlösung:
  - Auth: Firebase Token verifizieren, aber **ohne** `fullAccess`‑Enforcement.
  - Validiert Code (existiert, aktiv, uses nicht überschritten)
  - Loggt Nutzung (Audit)
  - Setzt User Custom Claim `fullAccess = true`
  - Optional: schreibt `activatedAt`/`activatedByCodeId` (oder ähnliche Felder) ins User‑Profil (Admin‑Nachvollziehbarkeit).
  **Manuelle Checks**:
- Gültiger Code -> User bekommt `fullAccess` -> nach Token Refresh kommt man ins Dashboard.
- Ungültiger/ausgeschöpfter/deaktivierter Code -> klare Fehlermeldung, User bleibt auf `/activate`.

### Commit A5 — „Admin UI: Codes erstellen/disable/inspect“

**Kontext**: Du willst Codes ohne DB‑Hacking verwalten.
**Änderungen (im Repo)**:

- Admin Sektion „Access Codes“:
  - Create (Name, maxUses, Notiz optional)
  - Enable/Disable
  - Liste + Detailansicht (Audit/Usage)
  **Akzeptanzkriterien**:
- Du kannst einen Code erstellen, teilen, später deaktivieren und Usage nachvollziehen.

### Commit A6 — „Admin: `fullAccess` setzen + User‑Sperre (sofort wirksam)“

**Kontext**: Sperren müssen sofort greifen; Claims allein reichen dafür nicht.
**Änderungen (im Repo)**:

- Admin‑Funktionen erweitern/umbauen:
  - Manuelles Freischalten/Entziehen über Custom Claim `fullAccess` (ersetzt `approved` langfristig).
  - Separater Toggle „User sperren“ (blocked), serverseitig im User‑Profil gespeichert (z.B. `accountStatus`, `blockedAt`).
- Enforcement:
  - Firestore Rules und kritische Backend‑Endpunkte prüfen `accountStatus != "blocked"`, sodass neue Aktionen sofort geblockt werden.
  - Storage Rules: Uploads nur mit `fullAccess` und nicht‑gesperrt (damit kein Image‑Abuse möglich ist).
- UX:
  - Blockierte User bekommen saubere UX (kein „random Permission Error“): Hinweis + Logout, oder Redirect auf `/activate` mit „Account gesperrt“.
  - Wenn Admin `fullAccess` setzt: `/activate` kommt per „Neu prüfen“ ohne Re‑Login weiter.
  **Akzeptanzkriterien**:
- Admin kann User freischalten, ohne dass der User sich neu anmelden muss (Token Refresh reicht).
- Admin kann User sperren und der User kann **sofort** keine neuen Jobs/Schreibaktionen mehr starten.

### Commit A7 — „Hardening: minimaler Missbrauchsschutz (Codes)“

**Kontext**: Codes können geleakt werden; du willst sofort reagieren können.
**Änderungen (im Repo)**:

- Deaktivieren/Enable ist zuverlässig und sofort wirksam.
- Optional: leichter Schutz gegen brute force (serverseitiges Throttling auf Redeem).
  **Akzeptanzkriterien**:
- „Leak“ ist durch Disable sofort entschärft.

### Branch‑A: Externe Schritte nach Merge

1. **Deploy**: Frontend + Backend (damit `/activate` und Redeem live sind).
2. **Deploy Rules**: Firestore Rules + Storage Rules (mindestens in Staging/Test) deployen.
3. **Admin**: Erstelle 1–3 Test‑Codes und teste den Flow mit einem frischen Google‑Account.
4. **Smoke Test**:
   - Login ohne Code -> stuck auf `/activate`.
   - Code einlösen -> Zugang.
   - Admin setzt `fullAccess` -> User kommt ohne Re‑Login weiter (Token Refresh).
   - Admin sperrt User -> neue Aktionen sind sofort geblockt.

---

## 4) Branch B: `beta/billing-credits` (Credits + Stripe)

Dieser Branch ist groß: arbeite in kleinen „vertikalen“ Commits und teste nach jedem Commit.

### Commit B1 — „Docs: Credits Modell (Kauf + Verbrauch) final“

**Kontext**: Credits sind das Herzstück. Ohne klare Regeln wird es später teuer.
**Änderungen (im Repo)**:

- In `PLAN_PUBLIC_BETA.md` prüfen/ergänzen:
  - Kauf: `$1 bezahlt -> 3 Credits`
  - Verbrauch Default: `OpenAI $1 -> 6 Credits`
  - Subscription Bonus: +`10 Credits` pro bezahlter Periode (Abo `$25` -> `85 Credits`)
  - Abo-Credits expiren am period end; Top-up nicht.
  - Ledger zeigt Admin-Adjustments als Gutschrift/Belastung.
  **Akzeptanzkriterien**:
- Keine Interpretationsfragen mehr.

### Commit B2 — „Datenmodell + Firestore Rules Update (Billing/Ledger/Rate)“

**Kontext**: Du brauchst einen stabilen Source of Truth.
**Änderungen (im Repo)**:

- Datenmodell festlegen für:
  - Stripe Customer/Subscription State (pro User)
  - Credit Ledger (append-only, pro User)
  - Credit Balances (entweder berechnet oder gecached)
  - Per-User Spend-Rate Override
  - Firestore-Pfade (konkret):
    - Stripe (Firebase Extension): `/customers/{uid}` (read), `/customers/{uid}/checkout_sessions/*` (user write), `/customers/{uid}/subscriptions/*` + `/customers/{uid}/payments/*` (read)
    - Stripe Catalog: `/products/*` + `/products/*/prices/*` (read)
    - Credits Ledger: `users/{uid}/creditLedger/*` (server-only writes, user read)
    - Credits Balance Cache: `users/{uid}/billing/balance` (server-only writes, user read)
    - Spend-Rate Override: `users/{uid}.spendRate` (server/admin setzt; Default 6.0)
- Firestore Rules erweitern:
  - Neue Collections: User darf lesen, aber nicht schreiben.
  - Server-only Writes sind der Standard.
  **Externe Schritte (direkt nach dem Commit)**:
- Deploy Firestore Rules in Staging/Test (oder Production, wenn du keine Staging hast).
  **Akzeptanzkriterien**:
- Keine Client‑Writes in Ledger/Billing möglich.

### Commit B3 — „Backend Read APIs: Balance + Ledger + Billing Status“

**Kontext**: UI braucht stabile Read‑Endpoints, bevor Checkout/Webhooks kommen.
**Änderungen (im Repo)**:

- Endpoints für:
  - Balance anzeigen
  - Ledger paginiert lesen
  - Subscription Status (aktiv? period end?)
  **Manuelle Checks**:
- Als User: Balance/Ledger lesbar.
- Keine Secrets im Response.

### Commit B4 — „Backend Debit Pipeline: OpenAI Cost -> Credits Debit + Enforcement“

**Kontext**: Jede OpenAI‑Operation muss Credits exakt abziehen.
**Änderungen (im Repo)**:

- Für jede OpenAI‑Operation:
  - Debit‑Ledger Entry schreiben: `credits = openai_cost_usd * spend_rate`
  - spend_rate im Entry speichern (Audit)
  - Enforcement: Wenn Balance bereits negativ -> block und auf Billing verweisen.
  **Akzeptanzkriterien**:
- Jede OpenAI‑Operation erzeugt genau 1 Debit.
- Bei negativem Guthaben keine neuen OpenAI Calls.

### Commit B5 — „Stripe Checkout: Subscription + Top‑up + Customer Portal“

**Kontext**: User müssen Credits kaufen können (auch wenn sie aktuell auf `/activate` hängen).
**Änderungen (im Repo)**:

- Checkout Session Creation:
  - Subscription: $25/Monat (Price ID aus Stripe)
  - Top‑up: custom amount (>= $5)
- Auth: diese Endpoints müssen auch für eingeloggte User **ohne** `fullAccess` funktionieren (sonst Paywall‑Deadlock).
- Portal Session Creation (Customer Portal)
  **Externe Schritte (vor dem Test dieses Commits)**:

1. Stripe Test Mode: Produkt/Price existiert, Price ID bekannt.
2. Backend Env Vars setzen (Test):
   - Stripe Secret Key (Test)
   - Subscription Price ID (Test)
   - Success/Cancel URLs (korrekt für deine Frontend Domain)
3. Frontend Env Vars: Backend URL stimmt.
  **Akzeptanzkriterien**:

- Checkout startet und kehrt sauber zurück.
- Customer Portal öffnet.

### Commit B6 — „Stripe Webhooks: Credits Grants (Abo expiring, Top‑up non‑expiring)“

**Kontext**: Webhooks sind die Wahrheit. Credits dürfen nicht über Client‑Events vergeben werden.
**Änderungen (im Repo)**:

- Webhook Handler (idempotent!) für:
  - Subscription Renewal / Invoice Paid -> Grant (expiring)
  - Top‑up Payment Succeeded -> Grant (non‑expiring)
  - Payment failed/canceled -> Billing State update (keine Grants)
  - Erster erfolgreicher Payment‑Event -> falls User noch kein `fullAccess`: `fullAccess = true` setzen (damit er aus `/activate` rauskommt).
- Grant Regel fixieren:
  - Top-up: `credits_granted = paid_usd * 3`
  - Abo: `credits_granted = paid_usd * 3 + 10` (bei `$25` -> `85 Credits`)
  - Expiry nur für Abo‑Grants (period end)
  - `fullAccess` nicht automatisch entziehen bei Kündigung/0 Credits (User muss sonst nicht mehr nachkaufen können); Sperre bleibt Admin‑Tool.
  **Externe Schritte (vor dem Test dieses Commits)**:

1. Stripe Webhook Endpoint in Test Mode anlegen:
   - URL = dein öffentlich erreichbares Backend (HTTPS)
   - Signing Secret notieren und als Env setzen
2. Webhook Events im Dashboard aktivieren (passend zu deinem Handler).
  **Akzeptanzkriterien**:

- Derselbe Stripe Event kann mehrfach kommen, erzeugt aber keine doppelten Credits.

### Commit B7 — „Profil: Billing Tab (Balance, Manage, Top‑up, Ledger)“

**Kontext**: Credits sollen nur im Profil/Billing sichtbar sein.
**Änderungen (im Repo)**:

- Profil so umbauen, dass:
  - Billing Tab: Guthaben, Subscription Status, Portal Link, Top‑up
  - Ledger Liste (Gutschrift/Belastung klar)
- Entferne/entkopple „Kosten‑Charts“/Token‑Overviews für normale User (kein $‑Stress).
  **Akzeptanzkriterien**:
- Ein User versteht sein Guthaben ohne Token/$.

### Commit B8 — „Admin: Spend‑Rate pro User + Manual Adjustments“

**Kontext**: Freunde/Promos/Support sollen über Rate & Adjustments laufen.
**Änderungen (im Repo)**:

- Admin User Detail:
  - Spend‑Rate editierbar (Default 6.0, pro User override)
  - Manual Adjustment erstellen (Betrag +/- + Notiz) -> erscheint im Ledger
  - Billing Status sichtbar
  **Akzeptanzkriterien**:
- Admin kann Rate ändern und Credits korrigieren; User sieht es im Ledger.

### Commit B9 — „Remove OpenAI Key UI (kein BYO‑Key mehr)“

**Kontext**: Produkt soll nicht nach „bring your key“ aussehen.
**Änderungen (im Repo)**:

- Entferne OpenAI‑Key UI und alle „Key required“ Toaster/Flows.
- Admin „allowPlatformKey“ Logik sauber entfernen/auf deprecated setzen (kein UI‑Dead‑End).
  **Akzeptanzkriterien**:
- Kein normaler User sieht „OpenAI Key hinzufügen“.

### Commit B10 — „Polish: klare UX bei ‚kein Guthaben‘“

**Kontext**: „Kein Guthaben“ muss wie ein normaler Zustand wirken.
**Änderungen (im Repo)**:

- Einheitliche Fehlermeldungen + Link zum Billing.
  **Akzeptanzkriterien**:
- Keine verwirrenden 500er/Permission‑Errors im UI, wenn Guthaben fehlt.

### Branch‑B: Externe Schritte für Live Go‑Live (nach Merge vorbereiten)

Wichtig: Test Mode -> Live Mode. Plane mindestens 1–2 Stunden Release‑Window.

1. Stripe Live Mode spiegeln:
   - Produkt/Price live anlegen (oder aus Test übertragen).
   - Live Price ID in Prod‑Env setzen.
   - Live Webhook Endpoint anlegen, Signing Secret setzen.
2. Backend Prod Env:
   - Live Stripe Secret Key
   - Live Webhook Secret
   - Live Price ID
   - Admin UIDs gesetzt
3. Smoke Test in Production:
   - Test‑User via Access Code aktivieren
   - Subscription Checkout -> Credits kommen über Webhook
   - Top‑up (>= $5) -> Credits kommen über Webhook
   - 1–2 OpenAI Aktionen -> Debit sichtbar im Ledger
4. Admin Test:
   - Spend‑Rate ändern (z.B. 4.0) und 1 Debit prüfen
   - Manual Adjustment (+/‑) prüfen

---

## 5) Branch C: `beta/public-pages` (Public Pages + Content)

### Commit C1 — „Scaffold: Public Routes + Verlinkung“

**Kontext**: Seiten müssen erreichbar und verlinkt sein.
**Änderungen (im Repo)**:

- Routen: `/how-it-works`, `/pricing`, `/terms`, `/privacy`, `/impressum`
- Links (Login/Footer) auf Terms/Privacy/Impressum
  **Akzeptanzkriterien**:
- Alle Seiten laden ohne Auth.

### Commit C2 — „Content: How it works (deutsch, student‑zentriert)“

**Änderungen (im Repo)**:

- Struktur:
  - Workflow (Quellen -> Kapitel -> Export)
  - Best Practices
  - Grenzen/Verantwortung (akademische Integrität)
  **Akzeptanzkriterien**:
- Neuer User versteht den Workflow ohne Support.

### Commit C3 — „Content: Pricing + Credits Erklärung (klar, nicht token‑nerdy)“

**Änderungen (im Repo)**:

- $25/Monat Plan erklären
- Top‑up erklären (min $5)
- Credits kurz erklären:
  - Kauf: `$1 -> 3 Credits`
  - Abo‑Credits verfallen am period end, Top‑up nicht
  **Akzeptanzkriterien**:
- Keine Rückfragen „verfallen Top‑ups?“ / „wie kaufe ich?“.

### Commit C4 — „Legal Pages finalisieren (AGB/Datenschutz/Impressum)“

**Kontext**: Für DE Launch‑kritisch.
**Außerhalb von Code (vor diesem Commit sammeln)**:

- Finale Texte/Angaben (Firma/Adresse/Email, Datenschutz, AGB).
- Optional: juristischer Check.
  **Akzeptanzkriterien**:
- Du kannst live gehen, ohne „rechtliches Loch“.

---

## 6) Gesamt Go‑Live Checklist (Final)

1. Branch A merged und getestet (Activation Gate + Block).
2. Branch B merged in Prod:
   - Stripe Live Keys + Webhook live
   - Firestore/Storage Rules live
   - Billing Tab zeigt Balance/Ledger
3. Branch C merged:
   - Public Pages erreichbar und verlinkt
4. Operativ:
   - Erste Codes erstellt (z.B. 20 Stück, maxUses=1)
   - Admin UIDs gesetzt (inkl. Backup Admin)
   - Monitoring/Logs geprüft (mind. Stripe Webhooks und OpenAI Calls)
5. Smoke Tests (Prod):
   - Neuer User: Login -> /activate -> Code -> Dashboard
   - Subscription Kauf -> Credits -> 1 Run -> Debit
   - Top‑up -> Credits -> Debit
   - Admin Adjustment sichtbar im User Ledger

---

## Optional (empfohlen, aber nicht zwingend)

- „Kill Switch“: serverseitige Option, um Stripe/LLM Calls temporär zu stoppen (bei Incident).
- Stripe Tax/VAT sauber aktivieren (wenn du B2C in EU richtig machen willst).
- Staging Firebase Projekt, um Regeln & Datenmodell ohne Risiko zu testen.

