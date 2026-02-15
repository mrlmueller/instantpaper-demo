# Two-Lane Pipeline Audit — Run `d5a67f10a618dec647502773`

Artifact-only audit (no web checks).

- Run dir: `sources-v2\runs\d5a67f10a618dec647502773`
- Created (UTC): `2026-02-14T17:10:45+00:00`
- Updated (UTC): `2026-02-14T18:34:27+00:00`

## 1. Executive Verdict + Top Issues

**Verdict: Partially working.** The pipeline reliably _retrieves_ many relevant scientific sources and the `match/with_abstract` top ranks contain strong canonical hits, but overall precision is still compromised by (a) lane isolation, (b) paratext/review leakage into the very top results, and (c) an authority lane that is not relevance-safe.

### Top 5 high-impact issues (evidence-based)

1. **Lane isolation breaks the authority lane.** Authority ranking is built from query provenance (`candidate.intents`) rather than from the unified candidate universe. In this run, only **231 / 9,245** candidates are authority-eligible (intents include `authority`). Canonical hits like _The Cambridge Economic History of the Greco-Roman World_ (`10.1017/chol9780521780537`) are `intents=['match']` and therefore **cannot** appear in `authority/*` rankings.
2. **Paratext/review items leak into top-20 rankings.** `Choice Reviews Online` and explicit `Book Review:` titles are not filtered by the current Phase E paratext regex (it only catches a few prefixes like `editorial`, `preface`, etc.). In this run:
   - match/with_abstract rank 6: `10.5860/choice.42-6019` — Late Roman Spain and its cities
   - match/with_abstract rank 11: `10.5860/choice.42-2358` — Approaching late antiquity : the transformation from early to late empire
   - authority/with_abstract rank 6: `10.5860/choice.43-4196` — Hispania in late antiquity: current perspectives
   - `authority/without_abstract` ranks 8–9 include two `Book Review:` records.
3. **Authority lane relevance drift is severe.** Because authority lane does not enforce topical anchors for `with_abstract`, it admits highly-cited but off-topic general social science. Example: `10.1111/ecca.12508` (_why China and Europe diverged_) enters with `intents=['authority']` from OpenAlex authority query `query_i=2` and ends up in the authority top-20.
4. **S2 recommendations expansion adds poorly-traced noise.** Phase F expands `candidates_normalized` (9,245) to `candidates_expanded` (+1,345). All 1,345 added records have `sources=None` (no provenance), and 7 of them reach the final shortlist — mostly irrelevant bibliometric/modern-topic papers (e.g., `10.63822/gt0sws91`).
5. **No single consumable output artifact is produced.** The blueprint expects an `output.json` contract, but this run directory contains only intermediate artifacts (`rankings_stagei.json`, `scores_final.jsonl`, etc.). Users must manually stitch results together.

## 2. Stage-by-Stage Audit (A–I): Intended vs Observed

### 2.1 Artifact inventory (stage → artifact)

| Phase     | Artifact                                | Status |         Size |
| --------- | --------------------------------------- | ------ | -----------: |
| Phase B   | `query_plan.json`                       | OK     |     34,410 B |
| Phase C   | `openalex_queries.json`                 | OK     |     24,186 B |
| Phase C   | `semanticscholar_queries.json`          | OK     |     14,750 B |
| Phase D   | `openalex_raw.jsonl`                    | OK     | 60,390,553 B |
| Phase D   | `semanticscholar_raw.jsonl`             | OK     | 13,175,002 B |
| Phase D   | `semanticscholar_recommendations.jsonl` | OK     |    246,960 B |
| Phase E   | `candidates_normalized.jsonl`           | OK     | 22,181,326 B |
| Phase E   | `candidates_expanded.jsonl`             | OK     | 24,727,811 B |
| Phase F/G | `scores_stage1.jsonl`                   | OK     |  7,306,924 B |
| Phase F   | `scores_stage2.jsonl`                   | OK     |  3,415,625 B |
| Phase G   | `scores_final.jsonl`                    | OK     |  6,255,744 B |
| Phase H   | `coverage_tags.jsonl`                   | OK     |  2,127,840 B |
| Phase G   | `rankings_stageg.json`                  | OK     |     42,396 B |
| Phase I   | `rerank_results.jsonl`                  | OK     |    285,772 B |
| Phase I   | `rankings_stagei.json`                  | OK     |     42,396 B |
| Obs       | `metrics.json`                          | OK     |      9,385 B |
| Obs       | `logs.jsonl`                            | OK     |    185,887 B |
| Obs       | `run.log`                               | OK     |      1,013 B |

### 2.2 Config / invariants snapshot (from notebook + metrics)

- Retrieval queries: OpenAlex=40, S2=33 (EN/DE split present).
- Raw retrieval counts: OpenAlex=8902, S2=8054 (query_failed: OA=0, S2=0).
- Candidate universe: normalized_total=16,671, deduped_candidates=9,245, merges=7,375, pools(with_abs=6,538, without_abs=2,707).
- Stage-2 scoring: stage2_candidates=770 (equals union of lane shortlists with abstracts), stage2_scored=770.
- Final shortlist (`scores_final.jsonl`): 1,091 records (with_abs=770, without_abs=321).
- Rerank: tasks_total=147, api_successes=147, failures=0, rerank_top_k_pre=40 per lane/pool (authority/without_abstract limited by pool size).

### 2.3 Phase-by-phase notes (quality/stability impact only)

- **Phase B (query planning):** Produces 17 facets + bilingual anchors + global exclusions. However, `query_plan.json` does _not_ carry the original chapter title/spec or pipeline version in this run (those exist only in the saved prompt files), weakening reproducibility.
- **Phase C (query generation):** OpenAlex emits 36 `match` queries + 4 `authority` queries; S2 emits 30 `match` + 3 `authority`. OpenAlex authority queries rely on `default.search` for core venues, which appears overly permissive and admits off-topic high-citation social science into `intent='authority'`.
- **Phase D (retrieval):** No HTTP failures in `logs.jsonl`. Retrieval is dominated by a single broad chronology/geography query (OA `query_i=7` contributes 52.3% of OpenAlex records; S2 `query_i=6` contributes 45.4% of S2 records), increasing noise pressure on later pruning.
- **Phase E (normalize/dedup):** Dedup works (7,375 merges, no final id collisions). Paratext filter is too narrow: `Choice Reviews Online`, `Book Review: …`, `New Book Chronicle`, and `From the Editor` remain and can rank highly.
- **Phase F/G (scoring + lane fusion):** Early pruning still uses provenance-based lane eligibility (`lane in candidate.intents`). Authority lane candidate pool is therefore tiny (231 candidates total), making authority rankings fragile and drift-prone.
- **Phase H (coverage tags):** Without-abstract pool uses fallback excerpts (title/venue/year), which can strongly mis-score paratext titles (e.g., `Book Review: Agrarian Change…`).
- **Phase I (LLM rerank):** Rerank completes cleanly in this run (147/147 successes). It materially improves top rankings vs Stage G, but still assigns high scores to `Choice Reviews Online` records because they look like rich summaries/TOCs.

## 3. Output Quality Findings (Representative Samples)

Sampling is taken from `rankings_stagei.json` (post-rerank). Scores come from `scores_final.jsonl`; LLM scores come from `rerank_results.jsonl` when available.

### 3.1 match/with_abstract — Top ranks

| rank | id                                        | year | cites |  best | match |  auth | llm | flags  | title                                                                                      | venue                                    |
| ---: | ----------------------------------------- | ---: | ----: | ----: | ----: | ----: | --: | ------ | ------------------------------------------------------------------------------------------ | ---------------------------------------- |
|    1 | 10.1093/oso/9780199244409.001.0001        | 2002 |   140 | 0.482 | 0.395 | 0.808 |  86 |        | Agrarian Change in Late Antiquity Gold, Labour, and Aristocratic Dominance                 |                                          |
|    2 | 10.1017/chol9780521780537                 | 2007 |   632 | 0.512 | 0.412 | 0.849 |  85 |        | The Cambridge Economic History of the Greco-Roman World                                    | Cambridge University Press eBooks        |
|    3 | 10.1515/9783110260779                     | 2013 |    19 | 0.553 | 0.435 | 0.656 |  85 |        | Gallien in Spätantike und Frühmittelalter : Kulturgeschichte einer Region                  |                                          |
|    4 | 10.1017/9781009172585                     | 2024 |     3 | 0.547 | 0.433 | 0.734 |  78 |        | The Colonate in the Roman Empire                                                           | Cambridge University Press eBooks        |
|    5 | 10.1163/9789047401490                     | 2003 |   206 | 0.486 | 0.396 | 0.830 |  77 |        | Theory and Practice in Late Antique Archaeology                                            |                                          |
|    6 | 10.5860/choice.42-6019                    | 2004 |   114 | 0.520 | 0.408 | 0.829 |  72 | CHOICE | Late Roman Spain and its cities                                                            | Choice Reviews Online                    |
|    7 | 10.4081/ija.2023.2184                     | 2023 |     9 | 0.545 | 0.429 | 0.861 |  70 |        | The green granary of the Empire? Insights into olive agroforestry in Sicily (Italy) from … | Italian Journal of Agronomy              |
|    8 | 10.1007/s12520-020-01251-7                | 2021 |    35 | 0.480 | 0.387 | 0.915 |  70 |        | New trajectories or accelerating change? Zooarchaeological evidence for Roman transformat… | Archaeological and Anthropological Scie… |
|    9 | 10.1017/9781139030236                     | 2018 |    51 | 0.492 | 0.390 | 0.836 |  65 |        | The Roman Empire in Late Antiquity: A Political and Military History                       | Cambridge University Press eBooks        |
|   10 | 10.4324/9781315261010                     | 2016 |    74 | 0.476 | 0.386 | 0.830 |  65 |        | Byzantine Trade, 4th-12th Centuries : The Archaeology of Local, Regional and Internationa… |                                          |
|   11 | 10.5860/choice.42-2358                    | 2004 |   240 | 0.563 | 0.430 | 0.867 |  64 | CHOICE | Approaching late antiquity : the transformation from early to late empire                  | Choice Reviews Online                    |
|   12 | cand_41fee57943b9b27351ad97bf             | 1994 |   129 | 0.557 | 0.433 | 0.782 |  60 |        | Land and Power: Studies in Italian and European Social History, 400-1200                   |                                          |
|   13 | 10.1371/journal.pone.0269869              | 2022 |    13 | 0.470 | 0.390 | 0.863 |  60 |        | Division of labor, specialization and diversity in the ancient Roman cities: A quantitati… | PLoS ONE                                 |
|   14 | 10.1093/oso/9780190067250.001.0001        | 2019 |    53 | 0.505 | 0.395 | 0.858 |  55 |        | Religious Dissent in Late Antiquity, 350-450                                               |                                          |
|   15 | 10.14795/j.v8i4.695                       | 2021 |    37 | 0.471 | 0.375 | 0.888 |  50 |        | A STREET WITH A VIEW OVER THE CENTURIES. THE CERAMIC MATERIAL FROM THE STREET A IN FRONT … | Journal of Ancient History and Archeolo… |
|   16 | 10.5871/bacad/9780197264027.001.0001      | 2007 |    71 | 0.537 | 0.416 | 0.772 |  46 |        | The Transition to Late Antiquity, on the Danube and Beyond                                 | British Academy eBooks                   |
|   17 | 10.1017/cbo9781139048101                  | 2012 |   185 | 0.527 | 0.400 | 0.841 |  40 |        | Staying Roman: Conquest and Identity in Africa and the Mediterranean, 439?700              | Cambridge University Press eBooks        |
|   18 | 10.1093/oso/9780199768998.001.0001        | 2015 |    32 | 0.519 | 0.413 | 0.750 |  60 |        | Contested Monarchy                                                                         |                                          |
|   19 | 10.1093/acprof:oso/9780199297375.001.0001 | 2006 |   121 | 0.553 | 0.433 | 0.810 |  55 |        | Approaching Late Antiquity                                                                 | Oxford University Press eBooks           |
|   20 | cand_689a98c147141a170006e94c             | 2012 |    23 | 0.576 | 0.453 | 0.672 |  55 |        | The production, supply and use of late Roman and early Byzantine copper coinage in the ea… | ORCA Online Research @Cardiff (Cardiff … |

### 3. match/without_abstract — Top ranks

| rank | id                              | year | cites |  best | match |  auth | llm | flags | title                                                                                      | venue                                    |
| ---: | ------------------------------- | ---: | ----: | ----: | ----: | ----: | --: | ----- | ------------------------------------------------------------------------------------------ | ---------------------------------------- |
|    1 | cand_0c24681c4ff2f09968f8f4f6   | 2015 |    16 | 0.430 | 0.341 | 0.659 |  60 |       | Local Economies? Production and Exchange of Inland Regions in Late Antiquity               |                                          |
|    2 | 10.1016/j.quascirev.2015.07.022 | 2015 |   143 | 0.385 | 0.306 | 0.876 |  30 |       | The environmental, archaeological and historical evidence for regional climatic changes a… | Quaternary Science Reviews               |
|    3 | cand_5d608c0edda256419032a79c   | 2012 |    21 | 0.428 | 0.333 | 0.711 |  42 |       | Comparative issues in the archaeology of the Roman rural landscape: Site classification b… |                                          |
|    4 | cand_276f0b2d2176772fc02bcb08   | 2001 |   180 | 0.484 | 0.378 | 0.821 |  40 |       | Agrarian Change in Late Antiquity: Gold, Labour, and Aristocratic Dominance                |                                          |
|    5 | 10.1017/cbo9781107050693        | 2002 |   500 | 0.419 | 0.334 | 0.847 |  40 |       | Origins of the European economy : communications and commerce, A.D. 300-900                |                                          |
|    6 | 10.2307/301432                  | 1997 |    60 | 0.439 | 0.343 | 0.711 |  40 |       | Towns in transition : urban evolution in late antiquity and the early Middle Ages          | Journal of Roman Studies                 |
|    7 | 10.3200/hist.34.2.65-67         | 2006 |    24 | 0.472 | 0.351 | 0.626 |  40 |       | History and Geography in Late Antiquity                                                    |                                          |
|    8 | 10.1017/eaa.2017.22             | 2017 |    49 | 0.422 | 0.328 | 0.816 |  35 |       | Animal Husbandry across the Western Roman Empire: Changes and Continuities                 | European Journal of Archaeology          |
|    9 | 10.1163/1568520041262288        | 2004 |    48 | 0.432 | 0.339 | 0.713 |  35 |       | Economic Boundaries? Late Antiquity and Early Islam                                        |                                          |
|   10 | cand_88baa27290006529fb78bb02   | 2007 |    98 | 0.371 | 0.300 | 0.798 |  35 |       | Changing townscapes in North Africa from late antiquity to the Arab conquest.              | Durham Research Online (Durham Universi… |
|   11 | 10.1017/cbo9780511496370.013    | 2005 |   143 | 0.455 | 0.349 | 0.816 |  30 |       | History and geography in late antiquity                                                    |                                          |
|   12 | 10.2307/527025                  | 1992 |   139 | 0.468 | 0.355 | 0.783 |  30 |       | The City in Late Antiquity                                                                 | Britannia                                |
|   13 | cand_ad6fe0e128c05030c8f16592   | 2000 |    55 | 0.465 | 0.362 | 0.712 |  30 |       | Towns and their territories between late antiquity and the early middle ages               |                                          |
|   14 | cand_3d7e2973d6b8ddda022ddf73   | 2004 |    83 | 0.438 | 0.344 | 0.774 |  30 |       | Recent research on the late antique countryside                                            |                                          |
|   15 | 10.2307/1087939                 | 1978 |   289 | 0.438 | 0.327 | 0.810 |  30 |       | The making of late antiquity                                                               |                                          |
|   16 | cand_096e47d57622d6a9ea15f393   | 1971 |   134 | 0.469 | 0.344 | 0.728 |  30 |       | The World of Late Antiquity: AD 150-750                                                    |                                          |
|   17 | cand_66d9c8362779b668961cff30   | 2018 |    20 | 0.431 | 0.339 | 0.748 |  30 |       | The Roman villa in the Mediterranean Basin: late republic to late antiquity                |                                          |
|   18 | 10.1086/422372                  | 2003 |    61 | 0.437 | 0.340 | 0.736 |  30 |       | Rome in Late Antiquity: Clientship, Urban Topography, and Prosopography                    | Classical Philology                      |
|   19 | 10.2307/25528462                | 2006 |    23 | 0.465 | 0.364 | 0.620 |  30 |       | From Roman Provinces to Medieval Kingdoms                                                  |                                          |
|   20 | cand_55c84e61d671f8f6cb28ff84   | 2012 |    16 | 0.484 | 0.356 | 0.616 |  30 |       | The fall of the Western Roman Empire: an archaeological and historical perspective         |                                          |

### 3. authority/with_abstract — Top ranks

| rank | id                                   | year | cites |  best | match |  auth | llm | flags  | title                                                                                      | venue                                    |
| ---: | ------------------------------------ | ---: | ----: | ----: | ----: | ----: | --: | ------ | ------------------------------------------------------------------------------------------ | ---------------------------------------- |
|    1 | 10.1093/oso/9780199244409.001.0001   | 2002 |   140 | 0.482 | 0.395 | 0.808 |  78 |        | Agrarian Change in Late Antiquity Gold, Labour, and Aristocratic Dominance                 |                                          |
|    2 | 10.1371/journal.pone.0273241         | 2022 |    15 | 0.410 | 0.330 | 0.881 |  75 |        | Food security in Roman Palmyra (Syria) in light of paleoclimatological evidence and its h… | PLoS ONE                                 |
|    3 | 10.4324/9781315608969                | 2015 |   121 | 0.446 | 0.362 | 0.843 |  70 |        | Shifting Genres in Late Antiquity                                                          |                                          |
|    4 | 10.1371/journal.pone.0239227         | 2020 |    17 | 0.432 | 0.348 | 0.817 |  70 |        | Byzantine—Early Islamic resource management detected through micro-geoarchaeological inve… | PLoS ONE                                 |
|    5 | 10.21237/c7clio10243683              | 2019 |    11 | 0.480 | 0.374 | 0.727 |  70 |        | The Growth and Decline of the Western Roman Empire: Quantifying the Dynamics of Army Size… | Cliodynamics The Journal of Quantitativ… |
|    6 | 10.5860/choice.43-4196               | 2006 |    35 | 0.529 | 0.416 | 0.711 |  65 | CHOICE | Hispania in late antiquity: current perspectives                                           | Choice Reviews Online                    |
|    7 | 10.1017/cbo9780511496264             | 2004 |   244 | 0.400 | 0.325 | 0.837 |  60 |        | Housing the Stranger in the Mediterranean World: Lodging, Trade, and Travel in Late Antiq… | Cambridge University Press eBooks        |
|    8 | 10.1007/978-3-030-94137-6_16         | 2022 |     5 | 0.490 | 0.384 | 0.735 |  60 |        | Managing the Roman Empire for the Long Term: Risk Assessment and Management Policy in the… | Risk, systems and decisions              |
|    9 | 10.4337/9781839108235                | 2022 |    13 | 0.451 | 0.356 | 0.833 |  55 |        | Research Companion to Construction Economics                                               | Edward Elgar Publishing eBooks           |
|   10 | 10.1146/annurev-anthro-041320-013018 | 2022 |    15 | 0.399 | 0.322 | 0.881 |  48 |        | The Fundamentals of the State                                                              | Annual Review of Anthropology            |
|   11 | 10.15184/aqy.2018.110                | 2018 |    38 | 0.275 | 0.217 | 0.846 |  45 |        | Alpine ice-core evidence for the transformation of the European monetary system, AD 640–6… | Antiquity                                |
|   12 | 10.1111/ecca.12508                   | 2023 |     7 | 0.428 | 0.330 | 0.827 |  40 |        | Social organizations and political institutions: why China and Europe diverged             | Economica                                |
|   13 | 10.1353/pgn.2018.0025                | 2018 |    15 | 0.414 | 0.339 | 0.758 |  30 |        | The Introduction of Christianity into the Early Medieval Insular World: Converting the Is… | Parergon                                 |
|   14 | 10.5617/acta.5688                    | 1970 |   114 | 0.447 | 0.351 | 0.711 |  30 |        | Roman Senators and Absent Emperors in Late Antiquity                                       | Acta ad archaeologiam et artium histori… |
|   15 | 10.15184/aqy.2021.154                | 2021 |     6 | 0.399 | 0.322 | 0.717 |  30 |        | Reimagining urban success: rhythms of activity at Gabii, 800 BC–AD 600                     | Antiquity                                |
|   16 | 10.1002/gea.21631                    | 2017 |    56 | 0.314 | 0.247 | 0.856 |  10 |        | Holocene fluvial history of the Nile's west bank at ancient Thebes, Luxor, Egypt, and its… | Geoarchaeology                           |
|   17 | 10.1017/chol9780521302005.010        | 1997 |    88 | 0.517 | 0.396 | 0.754 |  60 |        | Rural life in the later Roman empire                                                       | Cambridge University Press eBooks        |
|   18 | cand_689a98c147141a170006e94c        | 2012 |    23 | 0.576 | 0.453 | 0.672 |  45 |        | The production, supply and use of late Roman and early Byzantine copper coinage in the ea… | ORCA Online Research @Cardiff (Cardiff … |
|   19 | 10.14795/j.v8i4.695                  | 2021 |    37 | 0.471 | 0.375 | 0.888 |  40 |        | A STREET WITH A VIEW OVER THE CENTURIES. THE CERAMIC MATERIAL FROM THE STREET A IN FRONT … | Journal of Ancient History and Archeolo… |
|   20 | 10.5325/jeasmedarcherstu.10.3-4.0379 | 2022 |     6 | 0.485 | 0.392 | 0.726 |  40 |        | Caliphs and Merchants: Cities and Economies of Power in the Near East (700–950)            | Journal of Eastern Mediterranean Archae… |

### 3. authority/without_abstract — Top ranks

| rank | id                              | year | cites |  best | match |  auth | llm | flags       | title                                                                                      | venue                                    |
| ---: | ------------------------------- | ---: | ----: | ----: | ----: | ----: | --: | ----------- | ------------------------------------------------------------------------------------------ | ---------------------------------------- |
|    1 | cand_74d616a90c15987a510d9569   | 2011 |     4 | 0.413 | 0.323 | 0.367 |  40 |             | Between taxation and rent: fiscal problems from late Antiquity to early Middle Ages = Ent… |                                          |
|    2 | 10.11588/jrgzm.2013.2.20317     | 2015 |     9 | 0.348 | 0.281 | 0.615 |  35 |             | Centres of the Late Roman Military Supply Network in the Balkans: a Survey of horrea       |                                          |
|    3 | 10.1007/s10669-020-09778-9      | 2020 |    39 | 0.359 | 0.282 | 0.894 |  30 |             | Lessons from the past, policies for the future: resilience and sustainability in past cri… | Environment Systems & Decisions          |
|    4 | 10.1038/s41467-023-41367-7      | 2023 |     9 | 0.298 | 0.239 | 0.861 |  30 |             | Drought as a possible contributor to the Visigothic Kingdom crisis and Islamic expansion … | Nature Communications                    |
|    5 | 10.1007/s10816-024-09686-1      | 2025 |     1 | 0.420 | 0.327 | 0.660 |  30 |             | Consumption Trends, Trading Patterns and Economic Development in Italy Across Centuries: … | Journal of Archaeological Method and Th… |
|    6 | cand_08c7b8661adc0aae3e2ebc57   | 2011 |     6 | 0.411 | 0.320 | 0.442 |  30 |             | Frontiers in the Roman World. Proceedings of the Ninth Workshop of the International Netw… |                                          |
|    7 | cand_715a4d5ecbad09cf6fc90bbd   | 2013 |     5 | 0.387 | 0.314 | 0.434 |  30 |             | Sicily between the 5th and the 10th century: villae, villages, towns and beyond. Stabilit… |                                          |
|    8 | cand_5fbd9470fbd09e5a7c99f5ea   | 2003 |     0 | 0.411 | 0.320 | 0.050 |  30 | BOOK_REVIEW | Book Review: Agrarian Change in Late Antiquity: Gold, Labour, and Aristocratic Dominance.… |                                          |
|    9 | cand_1a3102717379e97ef6b5e6e9   | 2008 |     0 | 0.360 | 0.278 | 0.050 |  30 | BOOK_REVIEW | Book Review: The Grain Market in the Roman Empire: A Social, Political and Economic Study… |                                          |
|   10 | 10.1080/10848770600842911       | 2006 |     1 | 0.410 | 0.329 | 0.037 |  30 |             | The “Ancient Economy” and Its Countryside                                                  |                                          |
|   11 | 10.1007/s10745-018-0002-2       | 2018 |    57 | 0.347 | 0.269 | 0.872 |  25 |             | The Social Burden of Resilience: A Historical Perspective                                  | Human Ecology                            |
|   12 | 10.1007/s00004-018-0388-6       | 2018 |    10 | 0.298 | 0.232 | 0.680 |  25 |             | A Metrological Study of the Late Roman Fort of Umm al-Dabadib, Kharga Oasis (Egypt)        | Nexus Network Journal                    |
|   13 | cand_54e32958f52e411426672b85   | 2017 |     2 | 0.417 | 0.321 | 0.333 |  25 |             | Castra and towns in the hinterland of the limes during Late Antiquity: Pannonia and the p… |                                          |
|   14 | 10.1007/978-3-319-62348-1_100-1 | 2019 |     1 | 0.335 | 0.258 | 0.250 |  25 |             | Management in Antiquity: Part 2 – Success and Failure in the Hellenic and Roman Worlds     |                                          |
|   15 | 10.1017/s0009840x16003012       | 2016 |     0 | 0.434 | 0.331 | 0.011 |  25 |             | QUESTIONS OF LANDED PROPERTY IN THE ROMAN EAST                                             | The Classical Review                     |
|   16 | 10.1093/cr/53.2.444             | 2003 |     0 | 0.360 | 0.277 | 0.000 |  25 |             | TOWNS IN LATE ANTIQUITY                                                                    | The Classical Review                     |
|   17 | 10.1038/s41597-022-01462-8      | 2022 |    33 | 0.321 | 0.246 | 0.940 |  20 |             | Presenting the Compendium Isotoporum Medii Aevi, a Multi-Isotope Database for Medieval Eu… | Scientific Data                          |
|   18 | 10.1016/j.jas.2013.07.017       | 2013 |    28 | 0.334 | 0.254 | 0.744 |  20 |             | Glass and metal analyses of gold leaf tesserae from 1st to 9th century mosaics. A contrib… | Journal of Archaeological Science        |
|   19 | 10.1007/978-3-319-62114-2_100   | 2020 |     0 | 0.336 | 0.259 | 0.057 |  20 |             | Management in Antiquity: Part 2 – Success and Failure in the Hellenic and Roman Worlds     |                                          |
|   20 | 10.1111/ehr.12149               | 2015 |     0 | 0.415 | 0.322 | 0.037 |  20 |             | LarryNeal and Jeffrey G.Williamson, eds., The Cambridge history of capitalism, volume 1, … | The Economic History Review              |

### 3.x match/with_abstract — Mid sample (starting rank 200)

| rank | id                           | year | cites |  best | match |  auth | llm | flags  | title                                                                                      | venue                                    |
| ---: | ---------------------------- | ---: | ----: | ----: | ----: | ----: | --: | ------ | ------------------------------------------------------------------------------------------ | ---------------------------------------- |
|  200 | 10.1163/22134522-12340030    | 2013 |    16 | 0.463 | 0.370 | 0.628 |     |        | How Much Trade was Local, Regional and Inter-Regional? A Comparative Perspective on the L… |                                          |
|  201 | 10.5860/choice.46-2238       | 2008 |   475 | 0.396 | 0.308 | 0.878 |     | CHOICE | Hellenism in Byzantium: the transformations of Greek identity and the reception of the cl… | Choice Reviews Online                    |
|  202 | 10.7560/760783               | 2015 |    67 | 0.412 | 0.323 | 0.815 |     |        | The Restoration of the Roman Forum in Late Antiquity: Transforming Public Space            | University of Texas Press eBooks         |
|  203 | 10.1016/j.culher.2022.01.007 | 2022 |    18 | 0.386 | 0.302 | 0.897 |     |        | Roman brick production technologies in Padua (Northern Italy) along the Late Antiquity an… | Journal of Cultural Heritage             |
|  204 | 10.1073/pnas.1719880115      | 2018 |   148 | 0.378 | 0.300 | 0.903 |     |        | Population genomic analysis of elongated skulls reveals extensive female-biased immigrati… | Proceedings of the National Academy of … |
|  205 | 10.1353/pgn.2021.0112        | 2021 |    15 | 0.403 | 0.323 | 0.810 |     |        | Historiography and Identity, I: Ancient and Early Christian Narratives of Community ed. b… | Parergon                                 |
|  206 | 10.1515/9781400824854        | 2009 |   360 | 0.405 | 0.313 | 0.847 |     |        | Imperialism and Jewish Society                                                             | Princeton University Press eBooks        |
|  207 | 10.1111/emed.12396           | 2020 |     4 | 0.488 | 0.382 | 0.572 |     |        | Interpreting Transformations of People and Landscapes in Late Antiquity and the Early Mid… | Early Medieval Europe                    |
|  208 | 10.1017/9781108333047        | 2020 |    24 | 0.414 | 0.318 | 0.826 |     |        | The Fragmentary Latin Histories of Late Antiquity (AD 300–620)                             | Cambridge University Press eBooks        |
|  209 | 10.1002/ajpa.20530           | 2006 |   168 | 0.394 | 0.310 | 0.858 |     |        | Continuity or discontinuity of the life-style in central Italy during the Roman Imperial … | American Journal of Physical Anthropolo… |
|  210 | 10.1163/22134522-12340055    | 2015 |    10 | 0.483 | 0.379 | 0.580 |     |        | Vegetation and Land-Use Change in Northern Europe During Late Antiquity: A Regional-Scale… | Late Antique Archaeology                 |

### 3.x match/with_abstract — Tail sample (last 10)

| rank | id                           | year | cites |  best | match |  auth | llm | flags | title                                                                                      | venue                                    |
| ---: | ---------------------------- | ---: | ----: | ----: | ----: | ----: | --: | ----- | ------------------------------------------------------------------------------------------ | ---------------------------------------- |
|  591 | 10.4324/9781315588414        | 2014 |     7 | 0.323 | 0.254 | 0.508 |     |       | Individuality in Late Antiquity                                                            |                                          |
|  592 | 10.1017/s1047759414002116    | 2014 |    19 | 0.267 | 0.201 | 0.668 |     |       | Ancient Jewish art and archaeology: What do we know and where do we go from here? - LEE I… | Journal of Roman Archaeology             |
|  593 | 10.1515/hzhz-2020-1452       | 2020 |     2 | 0.326 | 0.254 | 0.443 |     |       | Tabea L. Meurer, Vergangenes verhandeln. Spätantike Statusdiskurse senatorischer Eliten i… | Historische Zeitschrift                  |
|  594 | 10.4000/droitcultures.3005   | 2013 |    11 | 0.278 | 0.220 | 0.564 |     |       | The episcopalis audientia in Late Antiquity                                                | Droit et Cultures                        |
|  595 | 10.17104/9783406682346-187   | 2015 |     0 | 0.459 | 0.359 | 0.007 |     |       | 4. Villenwirtschaft des 3./2. Jahrhunderts v. Chr. – das Kleinbauerntum und die Agrarinve… |                                          |
|  596 | 10.1525/sla.2021.5.1.128     | 2021 |     4 | 0.260 | 0.206 | 0.614 |     |       | Restoring “Syncretism” in the History of Christianity                                      | Studies in Late Antiquity                |
|  597 | 10.1111/emed.12520           | 2022 |     4 | 0.252 | 0.195 | 0.660 |     |       | Wartime rape in late antiquity: consecrated virgins and victim bias in the fifth‐century … | Early Medieval Europe                    |
|  598 | 10.1127/0003-5548/2012/0218  | 2012 |    24 | 0.228 | 0.182 | 0.708 |     |       | Mummies and skeletons from the Coptic monastery complex Deir el-Bachit in Thebes-West, Eg… | Anthropologischer Anzeiger; Bericht ube… |
|  599 | 10.1515/9783110240887        | 2011 |     3 | 0.356 | 0.273 | 0.290 |     |       | Spätantiker Staat und religiöser Konflikt : imperiale und lokale Verwaltung und die Gewal… |                                          |
|  600 | 10.1017/cbo9781316182314.007 | 2015 |    22 | 0.156 | 0.124 | 0.700 |     |       | Precious metal coinages and monetary expansion in late antiquity                           | Cambridge University Press eBooks        |

### 3.x match/without_abstract — Mid sample (starting rank 150)

| rank | id                             | year | cites |  best | match |  auth | llm | flags          | title                                                                                      | venue                                |
| ---: | ------------------------------ | ---: | ----: | ----: | ----: | ----: | --: | -------------- | ------------------------------------------------------------------------------------------ | ------------------------------------ |
|  150 | 10.2307/3268607                | 2001 |   254 | 0.295 | 0.226 | 0.835 |     |                | The Beginnings of Jewishness: Boundaries, Varieties, Uncertainties                         |                                      |
|  151 | 10.1080/15564894.2015.1057349  | 2016 |   161 | 0.281 | 0.220 | 0.855 |     |                | The Making of the Middle Sea: A History of the Mediterranean From the Beginning to the Em… |                                      |
|  152 | 10.1007/s11457-019-09235-y     | 2019 |    12 | 0.315 | 0.249 | 0.740 |     |                | Disheveled Tenacity: The North Bay of Roman and Byzantine Dor                              | Journal of Maritime Archaeology      |
|  153 | 10.1007/s00334-007-0113-y      | 2007 |    26 | 0.342 | 0.264 | 0.677 |     |                | Crops and agriculture during the Iron Age and late antiquity in Cerdanyola del Vallès (Ca… | Vegetation History and Archaeobotany |
|  154 | 10.1007/s12685-012-0054-y      | 2012 |    25 | 0.331 | 0.254 | 0.712 |     |                | Ruling the waters: managing the water supply of Constantinople, ad 330–1204                | Water History                        |
|  155 | 10.1080/14790718.2025.2507726  | 2026 |     1 | 0.317 | 0.244 | 0.750 |     | S2_RECOMMENDED | The shifting knowledge frontiers: a bibliometric analysis of linguistic landscape researc… |                                      |
|  156 | 10.1080/03612759.2001.10527863 | 2001 |    75 | 0.307 | 0.244 | 0.752 |     |                | Libraries in the Ancient World                                                             |                                      |
|  157 | cand_a97d0244c3c11ca12437583b  | 2018 |     9 | 0.350 | 0.271 | 0.639 |     |                | Age of Conquests: The Greek World from Alexander to Hadrian                                |                                      |
|  158 | cand_08c7b8661adc0aae3e2ebc57  | 2011 |     6 | 0.411 | 0.320 | 0.442 |     |                | Frontiers in the Roman World. Proceedings of the Ninth Workshop of the International Netw… |                                      |
|  159 | 10.2307/27638412               | 2005 |    36 | 0.345 | 0.260 | 0.678 |     |                | The Provenance of the Pseudepigrapha: Jewish, Christian, or Other?                         |                                      |
|  160 | 10.2139/ssrn.2313801           | 2006 |    15 | 0.381 | 0.292 | 0.548 |     |                | Paths of Western Law after Justinian                                                       | SSRN Electronic Journal              |

### 3.x match/without_abstract — Tail sample (last 10)

| rank | id                            | year | cites |  best | match |  auth | llm | flags       | title                                                                                      | venue                            |
| ---: | ----------------------------- | ---: | ----: | ----: | ----: | ----: | --: | ----------- | ------------------------------------------------------------------------------------------ | -------------------------------- |
|  291 | 10.1007/s12565-014-0270-x     | 2015 |    38 | 0.227 | 0.183 | 0.850 |     | BOOK_REVIEW | Normal anatomy and anatomic variants of vascular foramens in the cervical vertebrae: a pa… | Anatomical Science International |
|  292 | cand_097dba4230e91be9a741ec8b | 2017 |     6 | 0.341 | 0.260 | 0.543 |     |             | IMPORTS AT OSTIA IN THE IMPERIAL PERIOD AND LATE ANTIQUITY: THE AMPHORA EVIDENCE FROM THE… |                                  |
|  293 | 10.1163/9789004294141         | 1999 |    31 | 0.318 | 0.240 | 0.621 |     |             | Judaism in Late Antiquity: Part 4, Death, Life-after-Death, Resurrection and the World-to… |                                  |
|  294 | cand_4d2c88e91b4586dd7e0c9e84 |      |     1 | 0.426 | 0.336 | 0.237 |     |             | From the Late Antique City to the Early Medieval Town in Central and Northern Italy. Mode… |                                  |
|  295 | 10.1484/j.at.5.116750         | 2018 |     2 | 0.389 | 0.306 | 0.358 |     |             | La législation impériale sur les gouvernements municipaux dans l'Antiquité tardive         |                                  |
|  296 | 10.4000/mefrm.3692            | 2017 |     4 | 0.352 | 0.277 | 0.472 |     |             | Metalworking in the ‘Post-Classical’ phases of Roman villas in Italy (5th-7th centuries A… |                                  |
|  297 | 10.1007/s11457-017-9173-z     | 2017 |    18 | 0.258 | 0.210 | 0.738 |     |             | The Plurality of Harbors at Caesarea: The Southern Anchorage in Late Antiquity             | Journal of Maritime Archaeology  |
|  298 | 10.1515/mill-2015-0106        | 2015 |     4 | 0.372 | 0.286 | 0.433 |     |             | The Last Dance of the Salians: the Pagan Élite of Rome and Christian Emperors in the Four… |                                  |
|  299 | 10.5860/choice.196855         | 2016 |     8 | 0.323 | 0.253 | 0.562 |     |             | Spiritual Taxonomies and Ritual Authority: Platonists, Priests, and Gnostics in the Third… |                                  |
|  300 | 10.5040/9781474219235         | 2015 |    12 | 0.299 | 0.239 | 0.619 |     |             | The moving city : processions, passages and promenades in ancient Rome                     |                                  |

### 3.x authority/with_abstract — Mid sample (starting rank 100)

| rank | id                            | year | cites |  best | match |  auth | llm | flags | title                                                                                      | venue                                    |
| ---: | ----------------------------- | ---: | ----: | ----: | ----: | ----: | --: | ----- | ------------------------------------------------------------------------------------------ | ---------------------------------------- |
|  100 | 10.3390/socsci14090536        | 2025 |     0 | 0.429 | 0.355 | 0.162 |     |       | Plague and Climate in the Collapse of an Ancient World-System: Afro-Eurasia, 2nd Century … | Social Sciences                          |
|  101 | cand_6e052586ca777de13a6944d2 | 2025 |     0 | 0.567 | 0.467 | 0.132 |     |       | Monetary Reforms and Economic Processes in Late Antiquity: A Perspective from the Study o… | RAI - Repository of the Institute of Ar… |
|  102 | 10.11648/j.ija.20251301.19    | 2025 |     0 | 0.405 | 0.333 | 0.162 |     |       | From Ancient to Medieval Periods of the Mediterranean World: Trading Patterns &amp; Dynam… | International Journal of Archaeology     |
|  103 | 10.1353/tcj.2024.a919683      | 2024 |     0 | 0.360 | 0.284 | 0.173 |     |       | Education in Late Antiquity: Challenges, Dynamism, and Reinterpretation, 300–550 CE by Ja… | The Classical Journal                    |
|  104 | cand_a3ef5e30cbe596737aea4934 | 2016 |     1 | 0.451 | 0.365 | 0.151 |     |       | Iron production in the Western Roman Empire: A diachronic study of technology and society… | UCL Discovery (University College Londo… |
|  105 | 10.1057/s41599-023-02503-2    | 2024 |     0 | 0.427 | 0.332 | 0.153 |     |       | Exploring an extinct society through the lens of Habitus-Field theory and the Tocharian t… | Humanities and Social Sciences Communic… |
|  106 | 10.16995/trac2007_63_73       | 2008 |     2 | 0.184 | 0.141 | 0.197 |     |       | Roman Archaeology in an Epoch of Neoliberalism and Imperialist War                         | Theoretical Roman Archaeology Journal    |
|  107 | 10.1017/s1380203815000227     | 2015 |     1 | 0.355 | 0.285 | 0.160 |     |       | Urbanity as social practice                                                                | Archaeological Dialogues                 |
|  108 | 10.1080/14662035.2023.2322205 | 2023 |     0 | 0.419 | 0.333 | 0.140 |     |       | Settlement and Territories: Early and Middle Saxon Settlements and the Antiquity of Hundr… | Landscapes                               |
|  109 | 10.11588/ak.2010.2.28075      | 2016 |     1 | 0.356 | 0.281 | 0.151 |     |       | Balneum, Horreum, Granarium – on the interpretation of a building in Rannersdorf (Styria)  | University Library Heidelberg            |
|  110 | 10.1553/978oeaw95894          | 2025 |     0 | 0.452 | 0.354 | 0.132 |     |       | Fundmünzen aus Usbekistan, Band 2. Schatzfunde kushano-sasanidischer Kupfermünzen und ihr… | Verlag der österreichischen Akademie de… |

### 3.x authority/with_abstract — Tail sample (last 10)

| rank | id                               | year | cites |  best | match |  auth | llm | flags | title                                                                                      | venue                                    |
| ---: | -------------------------------- | ---: | ----: | ----: | ----: | ----: | --: | ----- | ------------------------------------------------------------------------------------------ | ---------------------------------------- |
|  186 | 10.1057/9780230005518_1          | 2004 |     0 | 0.387 | 0.309 | 0.000 |     |       | Polemic: Before the Rise of the East                                                       | Palgrave Macmillan UK eBooks             |
|  187 | 10.1111/j.1467-8314.2009.01196.x | 2009 |     0 | 0.386 | 0.304 | 0.000 |     |       | II Late Antiquity and the Early Middle Ages (300–900)                                      | Annual Bulletin of Historical Literature |
|  188 | 10.1353/jla.2014.0011            | 2014 |     0 | 0.352 | 0.282 | 0.004 |     |       | From the Editor                                                                            | Journal of late antiquity                |
|  189 | cand_e05b51667f87a2898100a047    | 2013 |     0 | 0.343 | 0.275 | 0.003 |     |       | Senators of curials?: some debatable "nobiles" in Late Antique Hispania                    | Hispania Antiqua                         |
|  190 | 10.16995/trac2005_12_24          | 2006 |     0 | 0.184 | 0.141 | 0.030 |     |       | Romanization in Southern Epirus: A Ceramic Perspective                                     | Theoretical Roman Archaeology Journal    |
|  191 | 10.16995/trac2002_101_112        | 2003 |     0 | 0.184 | 0.141 | 0.030 |     |       | Late Roman Economic Systems: Their Implication in the Interpretation of Social Organizati… | Theoretical Roman Archaeology Journal    |
|  192 | 10.16995/trac1998_86_95          | 1999 |     0 | 0.184 | 0.141 | 0.030 |     |       | Christianity and the End of Roman Britain                                                  | Theoretical Roman Archaeology Journal    |
|  193 | cand_05ff58de61f3b0fd36139670    | 2011 |     0 | 0.157 | 0.122 | 0.031 |     |       | From Theodosius to Constans II: Church, Settlement and Economy in Late Roman and Byzantin… | Clinical Orthopaedics and Related Resea… |
|  194 | 10.1353/trd.2002.0003            | 2002 |     0 | 0.287 | 0.227 | 0.000 |     |       | Judaism: From Heresy to Pharisee in Early Medieval Christian Literature                    | Traditio                                 |
|  195 | 10.1007/978-1-349-26924-2_1      | 1998 |     0 | 0.263 | 0.200 | 0.000 |     |       | The Frankish Inheritance                                                                   |                                          |

### 3.y Deep-dive examples (where the pipeline is clearly wrong)

- **`10.5860/choice.42-6019`** — Late Roman Spain and its cities
  - lane/pool: `match` / `with_abstract`
  - venue: Choice Reviews Online
  - year/citations: 2004 / 114
  - scores: best=0.520 match=0.408 auth=0.829 match_lane=0.492 auth_lane=0.745
  - intents (provenance): `['match']`
  - first source: provider=openalex query_i=7 intent=match rank=72
  - rerank: llm_score_0_100=72 insufficient_info=False
  - rerank rationale (snippet): Kulikowski’s Late Roman Spain and its cities (2004; abstract present) is a strong topical fit for the chapter: excerpts explicitly support chronology/geography (history of Spain in late antiquity; 300–600), regional comparison (prompts reassessments of provinces), urban demography/trade (challenges…
  - top coverage tag: `chronology_and_geography` score=0.520 excerpt=The history of Spain in late antiquity offers important insights into the dissolution of the western Roman empire and the emergence of medieval Europe. Nonetheless, scholarship on Spain in this period has lagged behind …
- **`10.5860/choice.42-2358`** — Approaching late antiquity : the transformation from early to late empire
  - lane/pool: `match` / `with_abstract`
  - venue: Choice Reviews Online
  - year/citations: 2004 / 240
  - scores: best=0.563 match=0.430 auth=0.867 match_lane=0.517 auth_lane=0.779
  - intents (provenance): `['match']`
  - first source: provider=openalex query_i=7 intent=match rank=75
  - rerank: llm_score_0_100=64 insufficient_info=False
  - rerank rationale (snippet): The metadata (title) and the provided excerpt/TOC line — “Economic Change and the Transition to Late Antiquity; A New Golden Age? The Northern Praefactura Urbi from the Severans to Diocletian; Transition and Change in Diocletian's Egypt: Province and Empire…” — explicitly support several required f…
  - top coverage tag: `chronology_and_geography` score=0.563 excerpt=1. Introduction 2. Economic Change and the Transition to Late Antiquity 3. A New Golden Age? The Northern Praefactura Urbi from the Severans to Diocletian 4. Transition and Change in Diocletian's Egypt: Province and Emp…

- **`10.1111/ecca.12508`** — Social organizations and political institutions: why China and Europe diverged
  - lane/pool: `authority` / `with_abstract`
  - venue: Economica
  - year/citations: 2023 / 7
  - scores: best=0.428 match=0.330 auth=0.827 match_lane=0.430 auth_lane=0.727
  - intents (provenance): `['authority']`
  - first source: provider=openalex query_i=2 intent=authority rank=31
  - rerank: llm_score_0_100=40 insufficient_info=False
  - rerank rationale (snippet): Metadata and coverage tags (abstract present) show the paper addresses the historical divergence of political institutions in China and Western Europe and the role of social/corporate organizations. Excerpts: 'The paper discusses the many ways in which corporate organizations contributed to the eme…
  - top coverage tag: `political_economy_links` score=0.428 excerpt=The paper discusses the many ways in which corporate organizations contributed to the emergence of representative institutions and gave prominence to the Rule of Law in the early stages of state formation in Europe, and…

- **`cand_5fbd9470fbd09e5a7c99f5ea`** — Book Review: Agrarian Change in Late Antiquity: Gold, Labour, and Aristocratic Dominance. By Jairus Banaji.
  - lane/pool: `authority` / `without_abstract`
  - venue: (missing)
  - year/citations: 2003 / 0
  - scores: best=0.411 match=0.320 auth=0.050 match_lane=0.266 auth_lane=0.104
  - intents (provenance): `['authority', 'match']`
  - first source: provider=semanticscholar query_i=1 intent=authority rank=1
  - rerank: llm_score_0_100=30 insufficient_info=True
  - rerank rationale (snippet): The record is a book review of Jairus Banaji's 'Agrarian Change in Late Antiquity: Gold, Labour, and Aristocratic Dominance' (metadata/title). The title and the provided coverage tags explicitly point to agrarian/land issues and labour/social structure, so only 'land_production_structure' and 'labo…
  - top coverage tag: `land_production_structure` score=0.411 excerpt=Book Review: Agrarian Change in Late Antiquity: Gold, Labour, and Aristocratic Dominance. By Jairus Banaji. | 2003
- **`cand_1a3102717379e97ef6b5e6e9`** — Book Review: The Grain Market in the Roman Empire: A Social, Political and Economic Study by Paul Erdkamp
  - lane/pool: `authority` / `without_abstract`
  - venue: (missing)
  - year/citations: 2008 / 0
  - scores: best=0.360 match=0.278 auth=0.050 match_lane=0.232 auth_lane=0.096
  - intents (provenance): `['authority', 'match']`
  - first source: provider=semanticscholar query_i=1 intent=authority rank=34
  - rerank: llm_score_0_100=30 insufficient_info=True
  - rerank rationale (snippet): Available evidence is limited to the metadata (title/author/year) and one coverage excerpt. Metadata: 'Book Review: The Grain Market in the Roman Empire: A Social, Political and Economic Study by Paul Erdkamp' (D. Hollander, 2008); abstract absent. Coverage tag explicitly links the excerpt to 'land…
  - top coverage tag: `land_production_structure` score=0.360 excerpt=Book Review: The Grain Market in the Roman Empire: A Social, Political and Economic Study by Paul Erdkamp | 2008

- **S2-recommended candidates reaching final shortlist (examples):**
  - `10.1007/s11212-025-09825-8` — Civilizational dissonance: Alexander Dugin and the limits of Sino-Russian ideological convergence (best=0.326)
  - `10.1038/s43247-025-03111-5` — Regional responses to oceanic variability constrain global drought synchrony (best=0.299)
  - `10.1080/14790718.2025.2507726` — The shifting knowledge frontiers: a bibliometric analysis of linguistic landscape research trends and scholarly influen… (best=0.317)
  - `10.1080/23311886.2025.2553224` — Mapping the evolution of agricultural E-commerce: insights from a bibliometric study (best=0.294)
  - `10.1111/bre.70077` — The Temporal and Geometrical Evolution of a Middle Carboniferous Extensional Basin in the Eastern Campine Basin ( NE … (best=0.383)
  - `10.5040/9798216415817` — Bibliometrics and Citation Analysis (best=0.393)
  - `10.63822/gt0sws91` — Public Financial Management: A Bibliometric Analysis of Research Trends and Influential Publications (best=0.425)

## 4. Stability / Run Health (Updated Logs)

### 4.1 Metrics summary

- Stage durations (sum of recorded phases): ~1149.4s
- OpenAI costs (approx): planner+query_builders=$0.145, embeddings=$0.019, rerank=$0.936, total≈$1.101
- Rerank completeness: 147/147 successes; failures=0 (this is now clean)

### 4.2 logs.jsonl summary

- Unique events: 5 (http_request=201, cache_write=79, openai_call_failed=3, run_initialized=1, aggregate_rebuilt=1)
- Error-like events: 3 (all are `openai_call_failed` in OpenAlex query builder retries)
- Error samples:
  - 2026-02-14T17:17:27+00:00 `phase_c_openalex_query_builder` `openai_call_failed` attempt=1 — OpenAI response had no output_text. status='incomplete' incomplete_reason='max_output_tokens' response_id='resp_0668e66a6338d244006990ad73b…
  - 2026-02-14T17:20:36+00:00 `phase_c_openalex_query_builder` `openai_call_failed` attempt=2 — Unterminated string starting at: line 217 column 23 (char 10761)
  - 2026-02-14T17:23:55+00:00 `phase_c_openalex_query_builder` `openai_call_failed` attempt=3 — Expecting ',' delimiter: line 32 column 422 (char 15735)

### 4.3 Observability gaps

- `run.log` is incomplete in this run dir (it contains only Phase A + early OpenAlex query builder errors). `logs.jsonl` + `metrics.json` are the reliable observability artifacts here.

## 5. High-Impact Recommendations (Prioritized)

Only structural/high-leverage changes (no weight-tweaking).

1. **Remove provenance-based lane eligibility (`lane in candidate.intents`).**
   - Impact: fixes authority lane recall; prevents 'canonical match-only' sources from being invisible to authority ranking.
   - Change: build both lanes from the unified candidate universe; differentiate lanes by scoring + topical gating, not by query provenance.

2. **Add hard source hygiene filters (pre-scoring + pre-rerank).**
   - Impact: immediately improves top-20 precision and usability.
   - Change: expand paratext detection beyond current `_PARATEXT_RE` to catch: `Choice Reviews Online`, `Book Review:`, `Review of`, `Recension/Rezension`, `From the Editor`, `New Book Chronicle`, and TOC-like abstracts (dense numbered chapter lists / 'Contents').

3. **Make the authority lane relevance-safe with explicit anchor gating.**
   - Impact: stops high-cited off-topic social science from surfacing in authority top ranks.
   - Change: require at least one primary context anchor in title+abstract (and optionally one economy/fiscal anchor) for `authority/with_abstract` too, not only for `authority/without_abstract`.

4. **Fix/replace OpenAlex authority query `default.search` patterns.**
   - Impact: reduces upstream authority noise that later stages must fight.
   - Change: prefer `title_and_abstract.search` for authority queries; enforce phrase anchors that are actually chapter-specific; incorporate negative exclusions where supported.

5. **Either annotate or disable S2 recommendations until they are provenance-complete and relevance-gated.**
   - Impact: avoids injecting modern/bibliometric noise and improves debuggability.
   - Change: when adding rec-derived candidates, set `sources=[{provider:'semanticscholar_recommendations', seed_paperId, rank, intent:'match'}]` (or similar) and run the same anchor/exclusion gates.

6. **Implement the missing output contract (`output.json`) per blueprint.**
   - Impact: makes the system usable for chapter writing without manual stitching.
   - Change: emit a single artifact containing top-N per lane/pool + coverage tags + excerpts + provenance + rerank rationale.

---

### Appendix A — Query effectiveness quick stats

- OpenAlex: 40 queries; raw records=8,902; zero-hit queries=8 → [4, 16, 34, 35, 36, 37, 38, 40]
- S2: 33 queries; raw records=8,054; zero-hit queries=3 → [13, 23, 33]

OpenAlex top contributing queries:

- query_i=7: 4,655 (52.3%) intent=match lang=en q=("Late Antiquity" OR "Western Roman Empire") AND ("fourth century" OR "fifth century" OR "sixth century" OR "provincial…
- query_i=11: 1,553 (17.4%) intent=match lang=en q=("Late Antiquity" OR "Late Roman West") AND (numismatics OR "coin hoards" OR papyrology OR epigraphy OR archaeology OR …
- query_i=29: 1,083 (12.2%) intent=match lang=en q=("Late Antiquity" OR "Late Roman West") AND ("empirical finding" OR interpretation OR "causal inference" OR "correlatio…
- query_i=31: 251 (2.8%) intent=match lang=en q=("Late Antiquity" OR "Western Roman Empire") AND ("elite competition" OR "imperial legitimacy" OR "administrative refor…
- query_i=25: 187 (2.1%) intent=match lang=en q=("Late Antiquity" OR "Western Roman Empire") AND ("barbarian invasions" OR "migration waves" OR "climate variability" O…

S2 top contributing queries:

- query_i=6: 3,659 (45.4%) intent=match lang=en q=+("Late Antiquity" | "Western Roman Empire" | "Late Roman West") +("fourth century" | "fifth century" | "sixth century"…
- query_i=10: 1,550 (19.2%) intent=match lang=en q=+("Late Antiquity" | "Western Roman Empire" | "Late Roman West") +("numismatics" | "coin hoards" | "papyrology" | "epig…
- query_i=26: 1,076 (13.4%) intent=match lang=en q=+("Late Antiquity" | "Western Roman Empire" | "Late Roman West") +("Italy" | "Gaul" | "Hispania" | "North Africa" | "pr…
- query_i=28: 928 (11.5%) intent=match lang=en q=+("Late Antiquity" | "Western Roman Empire" | "Late Roman West") +("empirical finding" | "interpretation" | "causal inf…
- query_i=30: 155 (1.9%) intent=match lang=en q=+("Late Antiquity" | "Western Roman Empire" | "Late Roman West") +("elite competition" | "imperial legitimacy" | "admin…

### Appendix B — Candidate universe stats

- Candidates: 9,245
- Pools: {'without_abstract': 2707, 'with_abstract': 6538}
- Provider combos: {('semanticscholar',): 3014, ('openalex', 'semanticscholar'): 2463, ('openalex',): 3768}
- Intent combos: {('match',): 9014, ('authority', 'match'): 144, ('authority',): 87}
- Noise indicators (in candidates_normalized): {'choice': 50, 'book_review_title': 87, 'new_book_chronicle': 2, 'from_the_editor': 19}
- Missingness indicators: {'missing_abstract': 2707, 'missing_venue': 3344, 'missing_year': 44, 'missing_doi': 1691}

### Appendix C — Rerank task breakdown

- authority/with_abstract: 40
- authority/without_abstract: 27
- match/with_abstract: 40
- match/without_abstract: 40
