# PDF Scan – Verbesserungs-Ideen (Accuracy vs. Aufwand)

Skalen:

- **Complexity (1–5)**: 1 = sehr leicht, 5 = groß/architektonisch
- **Accuracy impact (1–5)**: 1 = kleiner Effekt, 5 = sehr großer Effekt
- **Reliability impact (1–5)**: 1 = kleiner Effekt, 5 = sehr großer Effekt

Ziel: möglichst vollständige, thematisch präzise Evidence-Pakete aus PDFs, damit die spätere Kapitel-Schreibphase maximal belastbar ist.

---

## Architektur (Ist-Stand)

- **Stage 0 (Input)**: Kapitel-Titel + Rohbeschreibung + PDFs (lokal oder `file_id`)
- **Stage 1 (Preprocess)**: LLM erzeugt Retrieval-Spezifikation (Keywords, Subpoints, Exclusions, Scope Notes)
- **Stage 2 (Evidence Extractor)**: `vector_stores.search` → EVIDENCE → LLM extrahiert Treffer (strict: nur EVIDENCE)
- **Stage 3 (Curation)**: viele Treffer → wenige **einzigartige** PDF-Sections (divers + importance-gewichtet)
- **Stage 4 (Text Extract)**: aus lokaler PDF via Anchor+Heading den Volltext des Abschnitts ziehen (best effort)

Dateien:

- `pdf-scan/pdf-scan-test.ipynb` (Stage 0–3)
- `pdf-scan/text-extract.ipynb` (Stage 4)
- `pdf-scan/pdf_text_utils.py` (Shared Normalization/Anchor-Validation)

---

## 0) Was bereits umgesetzt ist (Status)

**In `pdf-scan/pdf-scan-test.ipynb`**

- Multi-PDF Upload/Reuse: lokale Pfade oder `file_id` (ein Vector Store).
- Stage-Model Overrides: `STAGE_MODELS` + `OPENAI_MODEL_<STAGE>`.
- Stage 1 Preprocess (LLM, strict JSON Schema): `optimized_description`, `must_terms`, `should_terms`, `subpoints` (inkl. keywords/exclusions), `hard_exclusions`, `scope_notes`.
- Retrieval: `vector_stores.search` (capped `max_num_results <= 50`).
- Balanced Retrieval (Option A): global Search + per-PDF “Top-up” via Filters + optional Subpoint-Top-up (importance-basiert).
- Stage 2 Evidence Extractor (LLM): **Hard rule: nur EVIDENCE**; `anchor` + `anchor_alt` + Summary + Score + `subpoint_scores` (Multi-Subpoint).
- Postprocess: robuste Anchor-Validierung (NFKC, Quotes, Soft-Hyphen, Case, Ligaturen) + “snap-to-evidence”; Treffer werden nicht still gedroppt, sondern als “UNVERIFIED_ANCHOR” markiert.
- Ausgabe: pro PDF (Debug), nach Unterpunkt (aggregiert), plus Stage-3-Curation Views.
- Kosten: pro Stage + pro PDF + Total (actual per `model_used` + what-if für `gpt-5-nano`/`gpt-5-mini`/`gpt-5.2`).
- Stage 3 Curation: Auswahl **einzigartiger** PDF-Sections (TOC/Strict-Headings best effort), importance-gewichtete Targets, kein “min=1”-Bug, PyMuPDF-Docs werden geschlossen.

**In `pdf-scan/text-extract.ipynb`**

- Robust anchor locate (word-based, survives line breaks).
- Strict heading detection (font-size/numbering heuristics) + section extraction by heading bounds, fallback “window around anchor”.
- Shared Normalization aus `pdf_text_utils.py`.

---

## 1) Fix-first: mögliche Bugs / Unsaubere Stellen (Status + Fix)

Diese Punkte sind die wahrscheinlichsten Ursachen für “es gibt Infos im PDF, aber Pipeline findet sie nicht zuverlässig” oder “Output ist verwirrend”.

| Problem / Code-Smell | Warum relevant | Wo | Fix | Status | Complexity | Reliability impact |
| --- | --- | --- | --- | :---: | ---: | ---: |
| Relative Pfade hängen am Notebook-CWD (z.B. `.env`, `PDF_DIR`) | `.env`/PDFs werden “nicht gefunden”; Heading-Extraction fällt still aus | `pdf-scan/pdf-scan-test.ipynb` | Repo-Root Discovery + Pfade relativ dazu auflösen | DEFERRED (Notebook ist temporär) | 2 | 5 |
| Hardcoded IDs überschreiben Env | “Warum wird neu hochgeladen / falscher Store?” | `pdf-scan/pdf-scan-test.ipynb` | `USE_HARDCODED_REUSE_IDS` Toggle; sonst Env priorisieren | DONE | 1 | 4 |
| One-call Retrieval kann PDFs “verhungern” lassen | Global Top-50 kann von 1 PDF dominiert werden → andere PDFs bekommen `no_evidence` | `pdf-scan/pdf-scan-test.ipynb` | Balanced Retrieval (global + per-PDF top-up via filters + optional subpoint top-up) | DONE | 3 | 5 |
| API-Limits (`max_num_results`, `limit`) werden überschritten | Hard failures/400 → `no_evidence` obwohl Inhalte existieren | `pdf-scan/pdf-scan-test.ipynb` | Maxima konsequent cappen (Search <= 50), Warnungen mit “weiterlaufen” | DONE | 1 | 5 |
| Anchor Checks zu “streng” (Case/Quotes/Whitespace) | Gute Treffer werden gedroppt → “keine passenden Stellen” | `pdf-scan/pdf-scan-test.ipynb`, `pdf-scan/text-extract.ipynb` | Einheitliche Normalisierung + word-based matching + “unverified” statt drop | DONE | 2 | 5 |
| Stage 3 Targets erzwingen min=1 (soft_total/desired) | Verwirrung bei 0 Treffern; außerdem fehlende importance-Verteilung | `pdf-scan/pdf-scan-test.ipynb` | Auto-Targets + importance-gewichtete per-subpoint Budgets; 0 möglich | DONE | 2 | 4 |
| PyMuPDF docs nicht geschlossen | File Locks / Kernel instabil bei vielen PDFs | `pdf-scan/pdf-scan-test.ipynb`, `pdf-scan/text-extract.ipynb` | Close am Ende der Stage (Reliability > Speed) | DONE | 1 | 5 |

---

## 2) Retrieval / Search (Accuracy)

| Idee | Kurzbeschreibung | Complexity | Accuracy impact | Reliability impact |
| --- | --- | ---: | ---: | ---: |
| Multi-Query pro Subpoint (systematisch) | Für jeden Subpoint eigene Query (must/should/keywords) + merge/rerank; reduziert Topic Drift | 2 | 4 | 4 |
| Hybrid Retrieval (BM25 + Embeddings) | Keyword + Vektor kombinieren (z.B. BM25 lokal + embeddings) | 4 | 5 | 4 |
| Reranking der Kandidaten | Erst breit holen, dann LLM/Reranker auf Relevanz reranken (evidence-only) | 3 | 4 | 3 |
| Coverage-driven Top-up | Wenn Subpoint “missing/weak”, automatisch Zusatz-Searches mit gezielten Terms | 3 | 4 | 4 |

---

## 3) Stage 2 (Evidence Extractor) – Stabilität/Qualität

| Idee | Kurzbeschreibung | Complexity | Accuracy impact | Reliability impact |
| --- | --- | ---: | ---: | ---: |
| Score-Kalibrierung weiter schärfen | Weniger 9/10, konsistentere 7–8; kurze `score_rationale` nutzen | 2 | 3 | 3 |
| Locator-Hints erweitern | Zusätzlich “section signature” (2–3 Keywords) für robustes Wiederfinden | 2 | 3 | 4 |
| “Repair pass” bei JSON/Schema Fail | Wenn parsing/strict schema fails: 1 Repair-Call mit “return JSON only” | 2 | 2 | 4 |

---

## 4) Stage 4 (Text Extraction) – Robustheit

| Idee | Kurzbeschreibung | Complexity | Accuracy impact | Reliability impact |
| --- | --- | ---: | ---: | ---: |
| Text Cleanup Pipeline | Ligaturen, Soft-Hyphens, line-break-hyphenation, Header/Footer Removal, References-Block erkennen | 3 | 4 | 4 |
| Extraction Boundaries verbessern | Nicht nur “heading bounds”: TOC ranges + heuristisch “next heading” + window fallback | 3 | 4 | 4 |
| Export “Evidence Pack” | Pro Section: `{pdf_label, pdf_heading, anchors, extracted_text, covered_subpoints}` als JSON/MD | 2 | 3 | 5 |

---

## 5) Writing Stage (nach Evidence Pack)

| Idee | Kurzbeschreibung | Complexity | Accuracy impact | Reliability impact |
| --- | --- | ---: | ---: | ---: |
| Evidence-only Drafting | Kapitel-Entwurf NUR aus extrahierten Section-Texten (keine externen Fakten) | 3 | 4 | 4 |
| Citation/Source Map | Jede Aussage bekommt `{pdf_label, pdf_heading, anchor}` als Source-Ref | 2 | 4 | 5 |
| Gap Analysis | Vor dem Schreiben: pro Subpoint “covered / weak / missing” + welche PDFs fehlen | 2 | 4 | 5 |
| Consistency/Contradiction Check | Widersprüche markieren statt glätten; “needs adjudication” | 3 | 3 | 4 |
| Outline Builder | Aus Subpoints + Evidence Pack ein Outline + Bullet Notes je Subpoint | 2 | 3 | 4 |

---

## 6) Workflow / Engineering

| Idee | Kurzbeschreibung | Complexity | Accuracy impact | Reliability impact |
| --- | --- | ---: | ---: | ---: |
| Run Artifacts speichern | Pro Run JSON + Logs nach `pdf-scan/runs/<timestamp>/...` | 2 | 2 | 5 |
| Hash-basierte Reuse Map | Lokaler Cache: `pdf_hash -> file_id` + `vector_store_id`; Upload nur wenn PDF geändert | 2 | 2 | 5 |
| Config als YAML/JSON | PDF-Liste + Subpoint-Importance + Model Overrides in Datei statt Notebook edits | 3 | 2 | 4 |
| CLI/Script Wrapper | `python -m pdf_scan ...` für Runs ohne Notebook | 4 | 2 | 4 |
| Evaluation Harness | Golden-Set + Regression (Recall/Precision), damit Prompt-Änderungen messbar sind | 4 | 3 | 4 |

---

## 7) Langfristig / Optional

- Offline/On-Prem Alternative: lokale Embeddings + FAISS + optional LLM nur fürs Schreiben (Complexity 5, Accuracy 4, Reliability 4).
- Project-level Knowledge Base: ein Vector Store pro Projekt, PDFs versioniert; Kapitel-Queries über Projekt-Bibliothek.
- Active Learning: du bestätigst “good/bad” Treffer → Retrieval/Curator lernt (z.B. weight tuning, prompt tuning).

