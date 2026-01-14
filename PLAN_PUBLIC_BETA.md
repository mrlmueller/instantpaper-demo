# InstantPaper – Public Beta Access (Regeln)

## Begriffe

- **Login**: Firebase Auth ist gültig (User ist eingeloggt).
- **Vollzugriff**: Custom Claim **`fullAccess = true`** (Premium/aktive Freischaltung).
- **Legacy-Claim** (Migration): **`approved = true`** wird vorübergehend wie `fullAccess` behandelt (`approved || fullAccess`).
- **Blocked (Sperre)**: Firestore-Status im User-Profil **`users/{uid}.accountStatus = "blocked"`** (harte Sperre, sofort wirksam).
- **Access Code**: Ein einmaliger/mehrfach nutzbarer Code, der `fullAccess` serverseitig setzt.

## Login- & Access-Regeln (ohne Interpretationslücken)

1. **Login ist immer erlaubt.**
2. **Kein `fullAccess` (und kein Legacy `approved`) ⇒ Gate:**  
   User bleibt eingeloggt, aber wird für jede geschützte Route auf **`/activate`** umgeleitet.
3. **`fullAccess = true` wird gesetzt durch:**  
   - Access Code Redeem  
   - Zahlung (Abo/Top‑Up)  
   - Admin (manuell)
4. **`fullAccess` kann wieder entzogen werden** (Soft‑Gate). Wirksam nach Token‑Refresh/neu minten.
5. **Blocked überschreibt alles (Hard‑Gate) und muss sofort greifen:**  
   - Blocked verhindert **jede neue** Firestore‑/Backend‑Schreibaktion **sofort** (ohne Logout/Login).  
   - Blocked verhindert auch Redeem/Payment, bis Admin entblockt.
   - Storage‑Uploads werden über Claims geschützt; **stale Tokens bis Ablauf (~1h) sind akzeptiert**.

## Access‑Code Regeln

- **Default:** `maxUses = 1` (konfigurierbar, z.B. 10).
- **Uses zählen pro unique UID** (1× pro Account).  
  Ein User, der denselben Code erneut nutzt (z.B. nach Entzug von `fullAccess`), zählt **nicht** als zusätzlicher Use.
- **Idempotenz:** Hat der User bereits `fullAccess`, dann ist Redeem ein **No‑op** (kein Use‑Verbrauch).
- **Disable:** Ein Code kann deaktiviert werden und ist dann **sofort** nicht mehr einlösbar.  
  Bereits aktivierte Accounts bleiben aktiv.

## Admin‑Ansicht (Access Codes)

Pro Code sichtbar:

- `name`, `createdAt`, `disabled`
- `used / maxUses`, `lastUsedAt`
- Liste aktivierter Accounts (mind.: `uid`, `email`, `displayName`, `activatedAt`, `ip`, `userAgent`)

## Hardening (Minimal)

- Redeem ist serverseitig gedrosselt (UID + IP), z.B. **UID 5/5min** und **IP 20/5min**.
- Audit‑Log speichert erfolgreiche und fehlgeschlagene Redeem‑Versuche (inkl. IP/UA).

