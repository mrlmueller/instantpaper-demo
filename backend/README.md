# instantpaper Backend

Die Server-Seite von instantpaper: eine FastAPI-Anwendung auf Cloud Run, dazu
die Worker für die schwere Verarbeitung. Was das Produkt tut, steht im
[Haupt-README](../README.md), hier steht, wie diese Hälfte gebaut ist.

## Was dieser Teil verantwortet

Das Backend führt alle Modellaufrufe aus, schreibt nach Firestore und
Storage, spiegelt den Abrechnungsstand aus der Stripe-Erweiterung ins
Guthaben, erzeugt die DOCX-Exporte und orchestriert die Läufe von
Quellen-Finder und PDF-Scan. Alle 90 API-Routen liegen in
[main.py](main.py), die Geschäftslogik in `services/`, die
Authentifizierung in `middleware/`, Konfiguration und Helfer in `utils/`.

In Produktion sind das mehrere Cloud-Run-Oberflächen: der API-Dienst, ein
Task-Worker für die Provider-Abfragen des Quellen-Finders und je ein Cloud
Run Job für den Quellen-Finder sowie den CPU- und den GPU-Teil des
PDF-Scans. Die Einstiegspunkte der Jobs liegen direkt in `backend/`
([run_two_lane_job.py](run_two_lane_job.py),
[run_pdf_scan_cpu_job.py](run_pdf_scan_cpu_job.py),
[run_pdf_scan_gpu_job.py](run_pdf_scan_gpu_job.py)), gebaut werden sie aus
[Dockerfile](Dockerfile) und [Dockerfile.gpu](Dockerfile.gpu).

## Aufbau

```text
backend/
|- main.py                  FastAPI-Anwendung mit allen Routen
|- middleware/              Auth-Prüfungen (Firebase-Token, Admin, Basic Auth)
|- models/                  Request- und Response-Modelle
|- services/                Geschäftslogik und externe Dienste
|- utils/                   Konfiguration, Logging, Helfer
|- pdf_scan_runtime/        Produktions-Laufzeit des PDF-Scans
|- scripts/                 Wartungs- und Prüf-Skripte
|- Dockerfile               CPU- und API-Image
`- Dockerfile.gpu           GPU-Worker-Image
```

Die wichtigsten Services: `firebase_service` kapselt Admin-SDK,
Session-Cookies und Custom Claims, `credits_service` führt das Guthaben als
Konto mit Buchungsjournal, `cost_service` protokolliert Token und Kosten
jedes Modellaufrufs, `openai_estimation_service` und `openai_budget_service`
schätzen und reservieren vor teuren Läufen, `prompt_service` lädt die
Prompts aus Firestore, `export_service` baut die DOCX-Dateien mit echten
Word-Fußnoten, und `cloud_run_job_launcher` startet die Jobs. Die
Produktions-Pipelines von Quellen-Finder und PDF-Scan liegen unter
`services/two_lane_sources/` und `services/pdf_scan/`.

## Lokal starten

```bash
cd backend
cp .env.example .env
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

Die API läuft dann auf `http://localhost:8000`, eine Statusprobe gibt
`GET /health`. Für einen nutzbaren lokalen Betrieb braucht die `.env`
mindestens das Firebase-Projekt mit Service-Account-Zugang
(`FIREBASE_PROJECT_ID`, `FIREBASE_CLIENT_EMAIL`, `FIREBASE_PRIVATE_KEY`)
und einen `OPENAI_API_KEY`, für Anthropic-Modelle zusätzlich
`CLAUDE_API_KEY`. Alles Weitere in der [.env.example](.env.example) steuert
Feinheiten, vor allem die vielen `TWO_LANE_*`-Werte: sie regeln, ob die
Quellen-Finder-Läufe lokal im Hintergrund oder als Cloud-Run-Jobs laufen,
und drosseln die Abfragen gegen OpenAlex und Semantic Scholar über einen
geteilten Limiter in Firestore, damit parallele Läufe die
Anbieter-Rate-Limits nicht gemeinsam überschreiten. Die vollständige Liste
der Optionen steht in [utils/config.py](utils/config.py). Auf Cloud Run
wechseln die Ausführungs-Voreinstellungen automatisch auf die Job-Varianten,
lokal bleibt es bei Hintergrund-Ausführung im API-Prozess.

## Zugriffsschutz

Jede Produkt-Route verlangt ein Firebase-Token oder Session-Cookie mit dem
Claim `fullAccess` (übergangsweise auch noch der ältere Claim `approved`),
geprüft in `middleware/auth.py`. Die Admin-Routen unter `/api/admin/*`
verlangen zusätzlich, dass die Nutzer-ID in `ADMIN_UIDS` steht. Daneben gibt
es die passwortgeschützte Freischaltseite `GET /approve`, die über
`ADMIN_BASIC_USER` und `ADMIN_BASIC_PASSWORD` abgesichert ist. Der interne
Task-Endpunkt des Quellen-Finders ist über einen geteilten geheimen Header
abgesichert, den nur der Task-Dispatcher kennt.

## Prüfen

```bash
curl http://localhost:8000/health
python -m compileall backend
python scripts/test_two_lane_provider_rate_limit.py
python scripts/test_two_lane_provider_pipeline_http.py --backend local --workers 4
```

Die `test_*.py`-Skripte prüfen einzelne Integrationen und laufen nicht
automatisch, einen Test-Runner gibt es nicht.

## Deployment

Der Workflow [deploy-backend.yml](../.github/workflows/deploy-backend.yml)
meldet sich per Workload Identity Federation am GCP-Projekt an, baut die
beiden Images und deployt den API-Dienst und die Cloud Run Jobs, Region
`europe-west3`, nur der GPU-Job läuft in `europe-west1`. Schlüssel liegen
als Cloud-Run-Secrets, nicht im Repository.

## Abgrenzung zu testing-scripts/

Das Backend importiert nichts aus `testing-scripts/`. Dort liegen die
Experimente und Benchmarks, hier liegt die Produktions-Laufzeit
(`pdf_scan_runtime/` und `services/two_lane_sources/` sind die
produktiven Gegenstücke zur Forschung unter `testing-scripts/`). Wenn das
Löschen von `testing-scripts/` die API bricht, ist das ein Bug.
