# InstantPaper - Plan für Public Beta (100+ Nutzer)

Ziel dieses Dokuments: Eine rein theoretische, umsetzungsorientierte Roadmap (ohne Code), um InstantPaper von „App für mich & Freunde“ zu einem Produkt für viele unbekannte Nutzer zu entwickeln – mit Credits, Stripe‑Billing, Freischaltung, besserem Profil/Billing und statischen Public Pages.

---

## 1) Ausgangslage (heute)

Aktuell ist InstantPaper stark „Friend‑only“ geprägt:

- **Zugang**: Allowlist über `approved` (Firebase Custom Claim). Nicht‑approved Users werden aktuell faktisch ausgesperrt (Login wird direkt wieder beendet).
- **Kosten/Keys**: Es gibt Logik und UI rund um OpenAI Key (User‑Key oder Platform‑Key) und teilweise $‑Kostenanzeigen.
- **Cost Tracking**: Backend schreibt serverseitig kostengenaue Operationen/Aggregate (intern super, für Endnutzer‑UX oft „zu ehrlich“/zu technisch).

---

## 2) Zielbild (Public Beta)

Für „100+ Studenten, deutschsprachig, Google‑Login“ soll gelten:

- **Login ist erlaubt**, aber ohne Freischaltung ist die App nicht nutzbar (Gate auf `/activate`).
- **Freischaltung**: Self‑serve über Codes (Admin erstellt/verwaltet Codes), plus Admin‑Freischaltung.
- **Billing**: Stripe Checkout + Customer Portal.
- **Credits**:
  - User kaufen Credits (Abo + Top‑ups).
  - **Abo‑Credits** verfallen am Ende des Stripe‑Abrechnungszeitraums; **Top‑up Credits** verfallen nicht.
  - Alle Modelle sind für alle zahlenden Users verfügbar.
- **Kein BYO‑Key**: alle Nutzer laufen über Platform‑OpenAI; „Freunde“/Sonderfälle werden über eine **individuelle Credit‑Rate** (pro User) abgebildet.
- **UX**: Credits/Abrechnung nur im Profil/Billing sichtbar; nicht überall im Dashboard.
- **Admin**: Admin kann pro User Credit‑Rate setzen und manuelle Korrekturen (Gutschrift/Belastung) durchführen – sichtbar im Abrechnungsverlauf.
- **Public Pages**: How it works, Pricing, Terms, Privacy, Impressum (deutsch, student‑zentriert).

---

## 3) Fixierte Produktentscheidungen (aus den Q&A)

- **Sprache/Target**: Deutsch, Studenten.
- **Auth**: Google‑only.

### 3.1 Access / Freischaltung (neu)

- **Custom Claim‑Name (Ziel)**: **`fullAccess = true`** (Vollzugriff/Premium‑Zugriff).
- **Migration**: Legacy Claim `approved` wird vorübergehend wie `fullAccess` behandelt (`approved || fullAccess`), bis alles umgestellt ist.
- **Login ist erlaubt**, aber ohne `fullAccess` ist die App nicht nutzbar:
  - User bleibt eingeloggt, aber wird auf `/activate` erzwungen.
  - Ohne `fullAccess` sind Firestore Reads/Writes und Storage Uploads (Bilder) gesperrt.
- `fullAccess = true` wird gesetzt durch:
  - Access‑Code Redeem
  - erfolgreiche Zahlung (Abo oder Top‑up)
  - Admin (manuell)
- **Admin‑Sperre muss sofort wirken** (nicht nur „nach neuem Login“):
  - Für sofortige Wirkung darf Sperre nicht nur über Claims laufen (Tokens können bis zu ~1h stale sein).
  - Sperre wird zusätzlich serverseitig als Status im User‑Profil gehalten (z.B. `users/{uid}.accountStatus = "blocked"` + `blockedAt`).

### 3.2 Währung & Logik

- OpenAI rechnet in **USD** ab.
- Stripe‑Preise sind in **USD**; EU‑User zahlen faktisch in EUR (Karte/Issuer rechnet um). Intern rechnest du in USD.
- Credits sind eine interne Einheit (Credits sind nicht $).

### 3.3 Billing / Produkte

- **Subscription**: 1 Plan, **$25/Monat**.
- **Top‑up**: frei wählbarer Betrag, Minimum **$5**.
- **Checkout**: Stripe Checkout + Customer Portal.

### 3.4 Credits (finales Modell)

Diese Zahlen sind ab jetzt „Source of Truth“:

- **Purchase‑Rate (Kauf)**: `$1 bezahlt -> 3 Credits`
- **Spend‑Rate (Verbrauch, Default)**: `OpenAI $1 Kosten -> 6 Credits`
- **Folge (Default)**: `$1 bezahlt -> $0.50 OpenAI‑Budget`
- Beispiel: `$10` bezahlt -> `30 Credits` -> entspricht `$5` OpenAI‑Budget -> wenn OpenAI‑Kosten `$5`, werden `30 Credits` verbraucht.

Weitere Regeln:

- Credits dürfen **Dezimalstellen** haben.
- Deduction ist **exakt** auf Basis der tatsächlichen OpenAI‑Kosten (nicht „immer aufrunden“) und wird präzise gespeichert (so genau wie praktikabel).
- **User‑Overrides**: pro User kann die Spend‑Rate angepasst werden (z.B. Freunde günstiger als Default).
- **Abo‑Credits** expiren am Period‑End; **Top‑ups** expiren nicht.

### 3.5 UI‑Entscheidung (Kosten/Token)

- Token/$‑Kostenanzeigen werden reduziert.
- Fürs Erste: Credits/Abrechnung **nur** im Profil/Billing und sonst nirgends; Token‑Details fürs Erste nirgends.

---

## 4) Parameter, die „leicht änderbar“ bleiben sollen

Diese Werte sollten so geplant werden, dass du sie später ohne Umbau anpassen kannst:

1. Credits pro $ bezahlt (Startwert 3.0).
2. Default Spend‑Rate (Startwert 6.0).
3. Per‑User Override der Spend‑Rate.
4. Plan‑Preis ($25) und Mindest‑Top‑up ($5).

---

## 5) Kernkonzept: Credits, Rate pro User, Ledger

### 5.1 Begriffe

- **Credit Balance**: Guthaben, das der User verbrauchen kann.
- **Purchase‑Rate**: wie viele Credits pro $ gezahlt gutgeschrieben werden (Default 3.0).
- **Spend‑Rate (pro User)**: wie viele Credits ein OpenAI‑$ kostet (Default 6.0; pro User override möglich).
- **Ledger**: Append‑only Abrechnungsverlauf:
  - Grants: Abo (mit Ablaufdatum), Top‑up (ohne Ablaufdatum)
  - Debits: Verbrauch durch OpenAI‑Operationen
  - Manual Adjustments: Admin Gutschrift/Belastung mit Begründung

### 5.2 Wie Credits in der UX erscheinen

User sieht primär:

- aktuelles Guthaben
- Abo‑Status + Period‑End
- Top‑up (Betrag wählen)
- Abrechnungsverlauf (Ledger)

User sieht nicht ständig Token‑/Dollar‑Kosten in jedem Dialog.

### 5.3 Risiko & Minimal‑Schutz

Minimaler Schutz, der zu deinen Wünschen passt (ohne „zu harte“ Limits):

- Jede OpenAI‑Operation prüft vor dem Call: Balance ist nicht bereits negativ.
- Nach dem Call wird exakt abgebucht. Wenn danach Balance < 0 ist, werden weitere LLM‑Calls blockiert, bis wieder Guthaben vorhanden ist.
- Optional (empfohlen): kleine serverseitige Notbremse (z.B. max parallele Jobs), um Ausreißer zu begrenzen.

---

## 6) Phasenplan (Reihenfolge, warum, Deliverables)

### Phase 1 – Access Codes + Activation Gate

Ziel: Aus „manuelle Allowlist“ wird „Self‑serve Aktivierung“, ohne Login zu blockieren.

Deliverables:

- `/activate` Seite (Code eingeben + Logout).
- Routing‑Gate: eingeloggt aber ohne `fullAccess` -> immer `/activate`.
- Admin kann Codes verwalten:
  - Code erstellen (Name, maxUses)
  - deaktivieren/aktivieren
  - Usage/Audit einsehen (welche Accounts wurden freigeschaltet, wann)
- Admin kann User freischalten/entziehen (`fullAccess`).
- Admin kann User sperren (blocked) und das wirkt **sofort** (neue Aktionen verhindern).

Akzeptanzkriterien:

- Neuer User kann sich einloggen, bleibt eingeloggt, kommt aber ohne Code nicht ins Produkt.
- Code aktiviert Account ohne manuelles Eingreifen.
- Admin kann einen geleakten Code deaktivieren.
- Admin‑Sperre verhindert sofort neue Aktionen.

### Phase 2 – Credits Engine (Ledger + Balance) als Source of Truth

Ziel: Abrechnung ist serverseitig korrekt, auditierbar und nicht manipulierbar.

Deliverables:

- Ledger‑Modell (append‑only, präzise Beträge, Referenzen).
- Balance‑Berechnung (Spending order: erst expiring, dann non‑expiring).
- Per‑User Spend‑Rate (Default + Override; jede Debit speichert verwendete Rate).
- Enforcement: keine OpenAI‑Operationen, wenn Balance bereits negativ ist.

### Phase 3 – Stripe (Checkout + Portal + Webhooks)

Ziel: Zahlungen sind robust (Webhooks als Wahrheit), Credits werden automatisch vergeben.

Deliverables:

- Checkout Flows: Abo $25/mo, Top‑up >= $5.
- Customer Portal.
- Webhook Verarbeitung (idempotent):
  - Zahlung erfolgreich -> Credits grant (Abo expiring, Top‑up non‑expiring)
  - erster erfolgreicher Payment‑Event -> falls noch kein `fullAccess`: `fullAccess = true`
- Billing State pro User (Customer ID, Subscription Status, currentPeriodEnd).

### Phase 4 – Profil/Billing neu ausrichten (user‑zentriert)

Ziel: Profil zeigt, was Nutzer wollen (Guthaben, Abo, Abrechnung), ohne „Kostenstress“.

Deliverables:

- Billing Tab: Balance, Abo‑Status, Manage (Portal), Top‑up, Ledger.
- Entfernen/Reduzieren von Token/$‑Views außerhalb Profil/Billing.

### Phase 5 – Admin (Support‑fähig)

Ziel: Support‑Fälle sind schnell lösbar.

Deliverables:

- Per‑User Spend‑Rate editierbar.
- Manual Credit Adjustments (mit Notiz), sichtbar im User‑Ledger.
- Codes und Block/Unblock zuverlässig bedienbar.

### Phase 6 – Public Pages & Legal (Minimal Launch Set)

Ziel: Produkt wirkt „echt“ und rechtlich sauber.

Seiten:

- `/how-it-works` (statisch)
- `/pricing`
- `/terms`, `/privacy`, `/impressum`

---

## 7) Migration & Rollout

- Bestehende Accounts:
  - Admin kann ihnen `fullAccess` geben.
  - Credit‑Rate für „Freunde“ individuell setzen (z.B. weniger als Default).
- Legacy (OpenAI Keys):
  - alte Daten können bestehen bleiben, werden aber nicht mehr genutzt (BYO entfernt).
- Soft Launch:
  - erst wenige Codes verteilen, Verhalten beobachten, Rate/Plan feinjustieren.

---

## 8) Erfolgsmessung (damit du „richtige Entscheidungen“ triffst)

Minimal sinnvolle Metriken für die ersten 2–4 Wochen:

- Conversion: Code eingelöst -> Abo oder Top‑up?
- Aktivität: Runs pro aktivem User/Woche (nur Anzahl).
- Margin Check (intern): OpenAI‑Kosten vs verkaufte Credits (über Spend‑Rate steuerbar).
- Support: häufigste Abbrüche (z.B. „nicht freigeschaltet“, „kein Guthaben“, „Stripe failed“).

---

## 9) Launch Checklist (praktisch)

- Stripe:
  - Produkte/Preise live, Webhooks eingerichtet, Customer Portal aktiviert.
- Recht:
  - Impressum/Datenschutz/AGB live.
- Admin:
  - mind. 1 Admin Account, Codes können erstellt/deaktiviert werden, Block/Unblock funktioniert.
- Product:
  - Activation Flow funktioniert; Billing und Ledger funktionieren.
- Safety:
  - keine OpenAI‑Calls bei negativem Guthaben; Notfall: User sperren/blocken (soll sofort greifen).

