# PDF Scan – Verbesserungs-Ideen (Accuracy vs. Aufwand)

Skalen:

- **Complexity (1–5)**: 1 = sehr leicht, 5 = groß/architektonisch
- **Accuracy impact (1–5)**: 1 = kleiner Effekt, 5 = sehr großer Effekt

Kontext: `pdf-scan.ipynb` nutzt OpenAI Vector Stores + `file_search`, liefert **Suchanker** (für Strg+F) statt Seitenzahlen.

## Ideen (priorisiert)

| Idee                                           | Complexity | Accuracy impact | Kurzbeschreibung                                                                                                                                           |
| ---------------------------------------------- | ---------: | --------------: | ---------------------------------------------------------------------------------------------------------------------------------------------------------- |
| OCR-Pipeline für gescannte PDFs                |          3 |               5 | Automatisch erkennen, ob Text extrahierbar ist; sonst OCR (z.B. `ocrmypdf`) vor Indexing.                                                                  |
| Hybrid Retrieval (BM25 + Embeddings)           |          4 |               5 | Kombiniere Keyword-Suche (für exakte Term-Matches) mit Vektor-Suche (für semantische Treffer); merge + rerank.                                             |
| Subpoint-Decomposition (pro Unterpunkt suchen) |          2 |               4 | Für (2.1)…(2.7) jeweils eigene Retrieval-Query, dann Ergebnisse zusammenführen; reduziert “Topic drift”.                                                   |
| Reranking der Top-Chunks                       |          3 |               4 | Erst viele Kandidaten (z.B. 50–100) holen, dann mit Re-Ranker/LLM auf Relevanz reranken.                                                                   |
| Anchor-Validierung gegen Retrieval-Text        |          2 |               4 | Nach dem LLM-Output prüfen, ob der Suchanker exakt in den zurückgegebenen Chunks vorkommt; sonst automatisch “repair”-Pass.                                |
| “Strictness knob” (Thresholds/Rules)           |          2 |               4 | Einstellbare Mindest-Scores/Heuristiken pro Unterpunkt; lieber 0 Treffer als schwache Treffer erzwingen.                                                   |
| Headings/Structure-Extraction                  |          4 |               4 | Vor dem Indexing Überschriften/Kapitelstruktur extrahieren und als Metadaten in den Chunk-Text einbetten, damit Anchors häufiger echte Überschriften sind. |
| Duplicate-/Near-Duplicate-Filter               |          2 |               3 | Wenn mehrere Treffer denselben Absatz/Anker liefern: zusammenführen, Score konsolidieren.                                                                  |
| “Evidence-first” Output                        |          2 |               3 | Statt nur Zusammenfassung: zusätzlich 1–2 kurze Original-Zitate (≤25 Wörter) pro Treffer als Beleg (weiterhin ohne Seitenzahlen).                          |
| Query-Expansion (Synonyme/DE+EN)               |          2 |               3 | Automatisch deutsche/englische Synonyme (z.B. “multi-homing”, “switching costs”) in die Retrieval-Queries aufnehmen.                                       |
| Domain-Guardrails im Preprocessing             |          1 |               3 | Beim Preprocessing eine klare “Nicht suchen”-Liste generieren und im Retrieval stärker gewichten.                                                          |
| Vector Store Reuse (Hash-basiert)              |          2 |               2 | PDF-Hash berechnen und nur neu hochladen/indexen, wenn sich Datei geändert hat.                                                                            |
| Storage-Kosten sichtbar machen                 |          2 |               2 | `usage_bytes`/Dateigröße aus dem Vector Store auslesen (falls verfügbar) und als grobe Storage-Kostenschätzung pro Tag anzeigen.                           |
| Bessere Chunk-Parameter (adaptive)             |          3 |               3 | Chunk-Größe dynamisch nach Layout/Absatzlänge wählen (zu kurze/zu lange Chunks vermeiden).                                                                 |
| “Ask-clarifying-questions” Mode                |          2 |               2 | Wenn Beschreibung unklar ist: vor der Suche 2–3 Rückfragen generieren (optional).                                                                          |
| Multi-PDF Library                              |          4 |               4 | Ein Vector Store pro Projekt oder pro Themengebiet; Suche über mehrere PDFs hinweg mit Quellen-Attribution.                                                |
| Lokale/On-Prem Alternative                     |          5 |               4 | Voll offline: PDF → lokale Embeddings (z.B. sentence-transformers) + FAISS; optional LLM nur fürs Schreiben.                                               |
| Evaluation Harness                             |          4 |               3 | Kleines Benchmark-Set (Kapitelbeschreibung → erwartete Stellen) + Regression-Checks zur Qualitätsmessung.                                                  |
| UI/Workflow-Integration                        |          5 |               3 | In die App integrieren: PDF hochladen, Kapitel auswählen, Treffer anklicken (mit Highlight), Export der Treffer.                                           |

## Bereits umgesetzt (in `pdf-scan.ipynb`)

- Freie Eingabe von `CHAPTER_TITLE` und `CHAPTER_DESCRIPTION_RAW`
- Optionales LLM-Preprocessing (kompakte Search-Spec + Unterpunkte + Keywords)
- Strukturierte Ausgabe via JSON Schema (stabileres Format)
- Token-basierte Kostenschätzung für `gpt-5-nano`, `gpt-5-mini`, `gpt-5.2`
