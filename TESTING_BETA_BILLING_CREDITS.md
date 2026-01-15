# Beta Branch `beta/billing-credits` — Manual Test Guide (UI + Console)

Dieses Dokument ist eine **Step-by-step Test-Checkliste** für alles, was im Branch `beta/billing-credits` umgesetzt wurde (Credits/Ledger, Stripe Checkout + Portal, Webhook/Grants, Admin Spend-Rate & Adjustments, Blocked-User UX, “kein Guthaben” UX, Entfernen BYO OpenAI Key).

---

## 0) Voraussetzungen (einmalig)

### 0.1 Rollen / Test-Accounts

Für sauberes Testen sind 2–3 Accounts hilfreich:

- **Admin-Account** (UID in Backend-Env `ADMIN_UIDS`), um User zu blocken, Spend-Rate zu setzen und Adjustments zu machen.
- **User A** (normal, nicht blocked) für Billing/Checkout/LLM-Aktionen.
- **User B** (frischer User ohne `fullAccess`) für den `/activate`-Flow + “Paywall-Deadlock” Test.

Tipp: Für parallele Logins Browser-Profile oder Incognito nutzen.

### 0.2 Deployment/Runtime (damit die Tests überhaupt funktionieren)

Du brauchst für diese Branch-Features (mindestens):

- Frontend deployed oder lokal laufend.
- FastAPI Backend deployed oder lokal laufend.
- Firebase **Firestore Rules** aus dem Repo deployed.
- Firebase **Functions** aus dem Repo deployed (Credits-Grants laufen darüber).
- Firebase Extension “Firestore Stripe Payments” (oder äquivalent) ist aktiv und synchronisiert:
  - `customers/{uid}/checkout_sessions/*`
  - `customers/{uid}/subscriptions/*`
  - `customers/{uid}/payments/*`
  - `products/*` + `products/*/prices/*`

### 0.3 Stripe IDs (sollten zu deiner Stripe-Konfiguration passen)

Im Branch sind Fallback-IDs hinterlegt:

- **Top-up price**: `price_1SpqTADXfswW2xixLU9G63O6`
- **Subscription price**: `price_1SpqOYDXfswW2xixZsMQLjUI`

Optional (empfohlen): setze im Frontend:

- `NEXT_PUBLIC_STRIPE_TOPUP_PRICE_ID`
- `NEXT_PUBLIC_STRIPE_SUBSCRIPTION_PRICE_ID`

Damit ist eindeutig, welche Prices du testest.

### 0.4 Credits “Source of Truth” (wichtig fürs Prüfen)

- Kauf: **$1 bezahlt → 3 Credits**
- Verbrauch (Default): **OpenAI $1 Kosten → 6 Credits**
- Subscription: **85 Credits pro Monat** (expiring am period end)
- Top-up: **nicht expiring**
- Ledger:
  - `stripe_subscription` = Grant (expiring)
  - `stripe_topup` = Grant (non-expiring)
  - `openai` = Debit (Credits werden abgezogen)
  - `admin_adjustment` = +/- Credits (non-expiring Bucket)

---

## 1) `/activate` Gate + Kaufen ohne `fullAccess` (Paywall-Deadlock gelöst)

### 1.1 Neuer User ohne Freischaltung

1. Als **User B** einloggen.
2. Erwartung: Du landest auf **`/activate`**.
3. Erwartung: Ohne Access-Code kommst du nicht ins Dashboard.

### 1.2 Access-Code Redeem (Regression/Smoke)

1. Auf `/activate` einen gültigen Code eingeben → **Einlösen**.
2. Erwartung: Nach erfolgreichem Redeem kommst du ins **Dashboard** (ggf. nach Token-Refresh).

### 1.3 Kaufen auf `/activate` (ohne `fullAccess`)

1. Auf `/activate` im Abschnitt “Kein Code? Du kannst auch Credits kaufen.”:
   - **Abo starten ($25/Monat)** oder
   - **Credits aufladen**
2. Erwartung: Es öffnet sich Stripe Checkout.
3. Checkout abschließen und zurück zur App.
4. Auf `/activate` **Neu prüfen** drücken.
5. Erwartung: Du kommst ins **Dashboard** (weil beim ersten erfolgreichen Payment `fullAccess=true` gesetzt wird).

---

## 2) Profil → Billing Tab (User UI)

### 2.1 Billing Tab öffnen

1. Als **User A** zu **`/profil?tab=billing`** gehen.
2. Erwartung: Du siehst:
   - Guthaben (Total)
   - Abo Credits + “Abo bis …” (falls vorhanden)
   - Top-up Credits
   - Subscription Status (Stripe Status + period end / cancelAtPeriodEnd)
   - Ledger Liste (paginiert)

### 2.2 Ledger Pagination

1. Wenn genug Ledger-Einträge existieren: **Mehr laden** klicken.
2. Erwartung: Weitere Einträge werden angehängt; Cursor verschwindet, wenn Ende erreicht.

---

## 3) Stripe Checkout (Subscription + Top-up) + Customer Portal

### 3.1 Subscription Checkout (User)

1. Auf `/profil?tab=billing` → **Abo starten ($25/Monat)**.
2. Stripe Checkout abschließen.
3. Zurück zur App (Return URL ist Profil/Billing).
4. **Aktualisieren** klicken.
5. Erwartung:
   - Ledger enthält einen Eintrag: **“Abo (Stripe)”** mit **+85 Credits** und `expiresAt`.
   - Balance zeigt `subscriptionCredits = 85`, `subscriptionExpiresAt` gesetzt.
   - “Subscription Status” zeigt `active` oder `trialing`, `Period end` gesetzt.

### 3.2 Customer Portal (User)

1. Auf `/profil?tab=billing` → **Abo verwalten (Stripe)**.
2. Erwartung: Stripe Customer Portal öffnet.
3. Im Portal:
   - Zahlungsmethode ändern (wenn aktiviert)
   - Abo kündigen (cancel at period end)
4. Zurück zur App und **Aktualisieren**.
5. Erwartung: `cancelAtPeriodEnd` wird angezeigt, wenn Stripe Sync durch ist.

### 3.3 Top-up Checkout (User)

1. Auf `/profil?tab=billing` → **Credits aufladen**.
2. Im Stripe Checkout den Betrag wählen (je nach Price-Konfiguration: z.B. Menge/Amount im Checkout).
3. Zahlung abschließen.
4. Zurück zur App und **Aktualisieren**.
5. Erwartung:
   - Ledger enthält Eintrag **“Top-up (Stripe)”** mit `expiresAt = null`.
   - Credits entsprechen **paid_usd * 3**.
   - `topupCredits` steigt entsprechend.

---

## 4) Webhook/Grants: Idempotenz + FullAccess-Upgrade nach erster Zahlung

### 4.1 Idempotenz (Top-up)

1. Nach einem Top-up: in Firestore prüfen, dass es einen Ledger Doc gibt:
   - `users/{uid}/creditLedger/stripe_topup_{paymentId}`
2. In Stripe (Test Mode) denselben Event erneut auslösen (z.B. “Send test webhook event” oder Stripe CLI).
3. Erwartung: Es entsteht **kein zweiter** Ledger-Eintrag für denselben `paymentId`.

### 4.2 Idempotenz (Subscription)

1. Nach einer Subscription: Firestore prüfen, dass es einen Ledger Doc gibt:
   - `users/{uid}/creditLedger/stripe_subscription_{subscriptionId}_{periodEndSeconds}`
2. Erwartung: Pro Period-Ende gibt es maximal **einen** Grant.

### 4.3 FullAccess automatisch nach erster Zahlung (User ohne Code)

1. Als **User B** ohne Access-Code auf `/activate` eine Zahlung durchführen (Top-up oder Subscription).
2. Danach **Neu prüfen** klicken.
3. Erwartung: Du kommst ins Dashboard, ohne dass ein Admin manuell freischalten muss.

---

## 5) OpenAI Debit Pipeline → Ledger Debits + Enforcement

### 5.1 Debits entstehen (User)

1. Als **User A** ins Dashboard:
   - Projekt erstellen
   - Mindestens 1 Quelle hinzufügen
2. Einen Run starten (Verarbeitung).
3. Danach `/profil?tab=billing` öffnen und **Aktualisieren**.
4. Erwartung:
   - Ledger enthält neue Einträge **“Verbrauch (OpenAI)”** (negative Credits).
   - Balance sinkt entsprechend.

### 5.2 Weitere OpenAI Aktionen erzeugen Debits

Im Dashboard nacheinander testen (jeweils danach Billing aktualisieren):

- **Combine** (“Texte kombinieren”)
- **Shorten** (“Text wird gekürzt”)
- **Lesefluss**
- **Refinement** (Refinement Dialogs)

Erwartung: Jede Aktion erzeugt Debits im Ledger (Audit: `source=openai`).

---

## 6) “Kein Guthaben” UX (B10)

Ziel: Negative Balance blockt neue OpenAI-Operationen sauber (kein 500er/Permission Chaos).

### 6.1 Negativsaldo erzeugen (einfachste Methode)

1. Als User mit **0 Credits**: eine OpenAI-Aktion starten (z.B. 1 Quelle verarbeiten).
2. Warten bis Debit gebucht ist (Billing Tab aktualisieren).
3. Erwartung: Total kann jetzt **negativ** sein.

### 6.2 Block bei negativem Guthaben (UI)

1. Wenn Balance **negativ** ist: versuche erneut eine OpenAI-Aktion zu starten (z.B. Run starten).
2. Erwartung:
   - Es erscheint ein Toast **“Kein Guthaben”** mit Button **“Billing öffnen”**.
   - Die Aktion startet nicht.

### 6.3 Block während Batch-Verarbeitung

1. Starte Verarbeitung mit mehreren Quellen.
2. Sobald der Server `402` liefert (negativ bereits erreicht), erwartet:
   - Verarbeitung stoppt weitere Quellen
   - UI zeigt “Kein Guthaben” + Link zum Billing

### 6.4 Wieder freischalten

1. Guthaben wieder positiv machen (Top-up oder Admin Adjustment).
2. Erwartung: OpenAI-Aktionen funktionieren wieder (ggf. Seite refreshen).

---

## 7) Blocked User UX (Redirect zu `/profil`, Portal bleibt möglich)

### 7.1 Block setzen (Admin)

1. Als Admin in `/admin` den User finden.
2. User blockieren.
3. Erwartung: Der blockierte User kann keine neuen Aktionen starten.

### 7.2 Verhalten als blockierter User

1. Als blockierter User irgendeine Route öffnen (z.B. `/dashboard`).
2. Erwartung: Du landest immer auf **`/profil`**.
3. In `/profil`:
   - Erwartung: Nur Billing/Portal ist sinnvoll nutzbar (keine Stats/Exports/Prompt-Management).
   - Erwartung: Button “Abo verwalten (Stripe)” funktioniert, damit Kündigung möglich ist.

---

## 8) Admin: Spend Rate Override + Manual Adjustments + Ledger

### 8.1 User Detail → Billing Tab (Admin)

1. `/admin` → User auswählen → Detailseite öffnen.
2. Billing Tab öffnen.
3. Erwartung:
   - Balance Summary sichtbar
   - Subscription Summary sichtbar
   - Ledger listbar (paginiert)

### 8.2 Spend Rate Override testen

1. Setze Spend Rate Override z.B. auf **`4.0`**.
2. Als User 1 OpenAI-Aktion ausführen.
3. Erwartung: Debit Credits sind niedriger (auditierbar über Ledger).
4. Override resetten (leer setzen/Reset benutzen, je nach UI).
5. Erwartung: Default ist wieder **6.0**.

### 8.3 Manual Adjustment testen

1. Admin: Adjustment **+100** mit Note “Promo”.
2. Erwartung:
   - User Balance steigt (Top-up Bucket)
   - User Ledger zeigt “Admin Adjustment” + Note
3. Admin: Adjustment **-50** (Debit).
4. Erwartung: Balance sinkt, Ledger zeigt Debit.

---

## 9) BYO OpenAI Key entfernt (B9)

### 9.1 User UI

1. `/profil` durchklicken:
   - Erwartung: Kein Feld/Tab “API-Schlüssel” mehr.
2. Dashboard-Aktionen starten:
   - Erwartung: Keine “OpenAI Key erforderlich” Toaster/Flows mehr.

### 9.2 Admin UI

1. `/admin` User-Liste:
   - Erwartung: Keine “Platform Key” Toggle/Pill mehr.

---

## 10) Firestore Datenmodell + Rules (Firebase Console UI Tests)

### 10.1 Datenmodell verifizieren (Firestore Database → Data)

Als Admin in Firebase Console (nur “prüfen”, nicht manuell ändern):

- `users/{uid}/billing/balance`
  - `topupCredits`
  - `subscriptionCredits`
  - `subscriptionExpiresAt`
- `users/{uid}/creditLedger/*`
  - `source` ist z.B. `stripe_topup`, `stripe_subscription`, `openai`, `admin_adjustment`
- Stripe Sync:
  - `customers/{uid}/checkout_sessions/*`
  - `customers/{uid}/subscriptions/*`
  - `customers/{uid}/payments/*`
  - `products/*` + `prices/*`

### 10.2 Rules Simulator (Firestore Rules → “Rules Playground”)

Mit `request.auth.uid = <deine uid>` testen:

- **Erlaubt**
  - `read` auf `customers/{uid}/subscriptions/*` und `customers/{uid}/payments/*`
  - `read + write` auf `customers/{uid}/checkout_sessions/*`
  - `read` auf `users/{uid}/billing/balance` und `users/{uid}/creditLedger/*`
- **Nicht erlaubt**
  - `write` auf `users/{uid}/billing/balance`
  - `write` auf `users/{uid}/creditLedger/*`
  - `write` auf `customers/{uid}/subscriptions/*` und `customers/{uid}/payments/*`

Erwartung: Ledger/Billing sind **server-only writes**; Checkout Session ist die einzige Client-Write Ausnahme.

---

## 11) Troubleshooting (wenn etwas nicht wie erwartet ist)

- Checkout “hängt” (keine URL):
  - Prüfe Firestore Rules für `customers/{uid}/checkout_sessions/*` (write muss erlaubt sein).
  - Prüfe, ob die Stripe Extension läuft und Checkout Sessions verarbeitet.
- Credits kommen nicht an:
  - Prüfe, ob `customers/{uid}/payments/*` bzw. `subscriptions/*` in Firestore auftauchen.
  - Prüfe Firebase Functions Logs: `onStripePaymentWrite` / `onStripeSubscriptionWrite`.
- Billing Tab zeigt Fehler:
  - Prüfe `NEXT_PUBLIC_FASTAPI_URL`.
  - Prüfe Backend Logs für `/api/billing/*`.
- “Kein Guthaben” wirkt nicht:
  - Prüfe, ob im Ledger Debits entstehen und Balance wirklich negativ wird.
  - Prüfe Backend: `assert_not_negative_balance` muss `402` liefern, wenn Total < 0.

