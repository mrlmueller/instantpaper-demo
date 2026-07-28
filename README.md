# instantpaper

Ein Schreibwerkzeug für wissenschaftliche Arbeiten: Quellen hochladen, verarbeiten
lassen, daraus belegte Textabschnitte erzeugen — und den Weg dorthin
nachvollziehbar halten.

## Das Problem

Wissenschaftliches Schreiben ist zu großen Teilen Quellenarbeit: PDFs sichten,
relevante Stellen finden, Aussagen zuordnen, Belege behalten. Der Textabsatz am
Ende ist der kleinste Teil der Arbeit. instantpaper automatisiert die Schritte
davor, ohne den Beleg zu verlieren.

## Was daran technisch interessant ist

**Zwei Anbieter hinter einer Schnittstelle.** `backend/services/ai_router.py`
verteilt Anfragen auf Anthropic und OpenAI. Ein Ausfall oder eine Preisänderung
bei einem Anbieter legt das Produkt nicht still, und Modellwechsel sind eine
Konfigurationsfrage statt einer Änderung an dreißig Aufrufstellen.

**Kosten sind ein Feature, kein Nebeneffekt.** Bei nutzungsabhängigen
LLM-Kosten entscheidet die Kostenkontrolle über die Marge. Deshalb gibt es
`cost_service`, `credits_service`, `openai_budget_service` und
`openai_estimation_service`: Kosten werden vor dem Aufruf geschätzt, nach dem
Aufruf erfasst und gegen ein Guthaben gebucht.

**Schwere Arbeit läuft nicht im Request.** Die PDF-Verarbeitung braucht Minuten,
nicht Millisekunden. Sie läuft als Cloud Run Job — mit getrennten CPU- und
GPU-Pfaden (`backend/services/pdf_scan/cpu_job.py`, `gpu_job.py`) und einem
definierten Übergabepunkt (`handoff.py`) zwischen den Phasen. Die API nimmt an,
stellt ein, antwortet sofort.

**Gemessen statt geraten.** Unter `testing-scripts/pdf-scan/benchmark/` liegt
ein Auswertungsaufbau mit Kapitelspezifikationen, manuellen Relevanzurteilen und
einer Bewertungsrubrik. Die Pipeline-Varianten wurden dagegen verglichen, nicht
nach Gefühl ausgewählt.

## Architektur

```text
Browser
  └─ frontend/ (Next.js App Router, Vercel)
       ├─ Firebase Auth / Firestore / Storage
       └─ Next Route Handlers als BFF
            └─ backend/ (FastAPI auf Cloud Run)
                 ├─ ai_router → Anthropic / OpenAI
                 ├─ Firestore- und Storage-Schreibzugriffe
                 └─ Cloud Run Jobs für die schwere Verarbeitung
```

Die Abrechnung läuft getrennt: Checkout-Sitzungen entstehen über
Firestore-Dokumente, die die Firebase-Stripe-Erweiterung verarbeitet; das Backend
spiegelt Abrechnungsstand und Guthaben.

## Aufbau

```text
frontend/          Next.js 16, React 19, TypeScript, Tailwind 4
backend/           FastAPI, Worker-Einstiegspunkte, Dockerfiles
testing-scripts/   Experimente, Benchmarks, Auswertungen — nicht im Produktionspfad
functions/         Alte Firebase Functions, nicht mehr im Deploy-Pfad
firestore.rules    Firestore-Regeln
storage.rules      Storage-Regeln
```

`frontend/` und `backend/` genügen, um die Anwendung zu betreiben.
`testing-scripts/` ist bewusst außerhalb — groß, laut und für den Betrieb
irrelevant.

Details stehen in [frontend/README.md](frontend/README.md) und
[backend/README.md](backend/README.md).

## Lokal starten

```bash
cd frontend && cp .env.local.example .env.local && npm install && npm run dev
cd backend  && cp .env.example .env        && pip install -r requirements.txt && python main.py
```

Frontend auf `:3000`, API auf `:8000`. Die erwarteten Konfigurationswerte stehen
in den beiden `.example`-Dateien.

## Deployment

Frontend auf Vercel mit `frontend/` als Wurzelverzeichnis. Backend über
[deploy-backend.yml](.github/workflows/deploy-backend.yml) auf Cloud Run, die
schweren Läufe als eigene Cloud Run Jobs. Die Authentifizierung des Deployments
läuft über Workload Identity Federation statt über hinterlegte Schlüssel.

## Tests

Es gibt **keinen automatisierten Test-Runner** in diesem Repository. Die 18
`test_*.py` sind Skripte für einzelne Integrationsproben, keine Suite. Die
Verifikation lief über den Auswertungsaufbau unter `testing-scripts/` und über
manuelle Proben gegen die laufende Umgebung.

Das ist die ehrliche Auskunft und gleichzeitig das, was ich beim nächsten Projekt
anders gemacht habe — `kochbuch-v3` und `strafwecker-v2` haben beide eine echte
Suite.

## Prompts

Die Prompt-Texte sind in diesem Repository durch Platzhalter ersetzt. Die
Anwendung lädt sie zur Laufzeit aus Firestore, wo sie über einen Admin-Bereich
gepflegt und versioniert werden; im Code standen sie nur als Startwerte.

## Zu diesem Repository

446 Commits von Dezember 2025 bis Mai 2026, veröffentlichte Kopie eines privaten
Repositories, Stand Juli 2026.

**Nicht mehr deployt.** Das Produkt war vollständig gebaut, inklusive Abrechnung
mit Guthaben, Staging- und Produktionsumgebung — vermarktet wurde es nie, zahlende
Nutzer gab es nicht.

Aus der veröffentlichten Fassung entfernt: Betriebsdaten mit personenbezogenen
Angaben, ein internes Betriebshandbuch, die Prompt-Texte und fremde
Verlagsdokumente aus dem Benchmark-Korpus.

## Lizenz

Alle Rechte vorbehalten. Dieses Repository dient als Arbeitsprobe;
Nachnutzung nur nach Absprache.
