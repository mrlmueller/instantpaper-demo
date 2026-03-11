import { promises as fs } from "node:fs";
import path from "node:path";

import type {
  CandidateDetail,
  CandidateRow,
  ComparisonOverlap,
  DashboardPayload,
  LabelValue,
  LeaderboardSection,
  OverviewMetric,
  PhaseCard,
  PromptTraceAttempt,
  PromptTraceGroup,
  QueryProviderData,
  QueryRow,
  RetrievalProviderSummary,
  RunComparison,
  RunDetail,
  RunListEntry,
  StageCostRow,
} from "./dashboard-types";
import {
  asArray,
  asNullableNumber,
  asNumber,
  asRecord,
  asString,
  asStringArray,
  CATALOG_LIMIT,
  compact,
  bestResourceUrl,
  getPhaseStatus,
  getTopLevelFileStats,
  readJsonFile,
  readJsonLinesFile,
  readRunCache,
  readTextFile,
  RUNS_DIR,
  safeDate,
  statusLabelFromPhaseCards,
  streamJsonLines,
  TIMELINE_ORDER,
  TOP_LIMIT,
  trimText,
  unique,
  writeRunCache,
} from "./dashboard-utils";

interface RunIndexCacheEntry {
  key: string;
  data: RunListEntry;
}

interface RunDetailCacheEntry {
  key: string;
  data: RunDetail;
}

const runIndexCache = new Map<string, RunIndexCacheEntry>();
const runDetailCache = new Map<string, RunDetailCacheEntry>();

async function getRunDirectories(): Promise<string[]> {
  try {
    const entries = await fs.readdir(path.resolve(process.cwd(), RUNS_DIR), { withFileTypes: true });
    return entries
      .filter((entry) => entry.isDirectory())
      .map((entry) => entry.name)
      .sort((left, right) => right.localeCompare(left));
  } catch {
    return [];
  }
}

function countsFromMetrics(metrics: Record<string, unknown>): RunListEntry["counts"] {
  const stages = asRecord(metrics.stages);
  const retrieval = asRecord(stages.phase_d_retrieval);
  const openAlex = asRecord(retrieval.openalex);
  const semanticScholar = asRecord(retrieval.semanticscholar);
  const candidates = asRecord(stages.phase_e_candidates);
  const candidateCounts = asRecord(candidates.counts);
  const phaseF = asRecord(stages.phase_f);
  const phaseFCounts = asRecord(phaseF.counts);
  const phaseI = asRecord(stages.phase_i_rerank);
  const rerankCounts = asRecord(phaseI.counts);

  return {
    openAlex: asNumber(openAlex.records),
    semanticScholar: asNumber(semanticScholar.records),
    candidates: asNumber(candidateCounts.deduped_candidates),
    stage2: asNumber(phaseFCounts.stage2_shortlist),
    finalScored: asNumber(phaseFCounts.final_scored_rows),
    rerank: asNumber(rerankCounts.tasks_completed) || asNumber(rerankCounts.cache_hits),
  };
}

function sumStageCosts(metrics: Record<string, unknown>): number {
  const stages = asRecord(metrics.stages);
  let total = 0;
  for (const value of Object.values(stages)) {
    const stage = asRecord(value);
    const openai = asRecord(stage.openai);
    const cost = asRecord(openai.cost);
    total += asNumber(cost.total_cost_usd);
  }
  return total;
}

function sumStageDurations(metrics: Record<string, unknown>): number {
  const stages = asRecord(metrics.stages);
  let total = 0;
  for (const value of Object.values(stages)) {
    const stage = asRecord(value);
    total += asNumber(stage.last_duration_s);
  }
  return total;
}

async function buildRunIndexEntry(runId: string): Promise<RunListEntry | null> {
  const runDir = path.resolve(process.cwd(), RUNS_DIR, runId);
  let dirStat;
  try {
    dirStat = await fs.stat(runDir);
  } catch {
    return null;
  }

  const cacheKey = `${dirStat.mtimeMs}:${runId}`;
  const cached = runIndexCache.get(runId);
  if (cached && cached.key === cacheKey) {
    return cached.data;
  }

  const [topEntries, directoryStats, metrics, queryPlan, output] = await Promise.all([
    fs.readdir(runDir, { withFileTypes: true }),
    getTopLevelFileStats(runDir),
    readJsonFile<Record<string, unknown>>(path.join(runDir, "metrics.json")),
    readJsonFile<Record<string, unknown>>(path.join(runDir, "query_plan.json")),
    readJsonFile<Record<string, unknown>>(path.join(runDir, "output.json")),
  ]);

  const topFiles = topEntries.filter((entry) => entry.isFile()).map((entry) => entry.name);
  const topFileSet = new Set(topFiles);
  const metricsRecord = metrics ?? {};
  const counts = countsFromMetrics(metricsRecord);
  const phaseCards = getPhaseStatus(topFileSet, counts);
  const topicSummary =
    asString(queryPlan?.topic_summary_en) ||
    asString(queryPlan?.topic_summary_de) ||
    asString(output?.chapter_spec_text) ||
    "";
  const chapterTitle = asString(output?.chapter_title) || trimText(topicSummary, 90) || runId;
  const totalCostUsd = sumStageCosts(metricsRecord);
  const durationSeconds = sumStageDurations(metricsRecord);
  const completenessScore =
    phaseCards.reduce((sum, card) => sum + (card.status === "complete" ? 1 : card.status === "partial" ? 0.5 : 0), 0) / phaseCards.length;
  const focusTerms = unique(
    compact([
      ...asStringArray(asRecord(queryPlan?.core_object_terms).en).slice(0, 4),
      ...asStringArray(asRecord(queryPlan?.global_canonical_terms).en).slice(0, 4),
    ]),
  ).slice(0, 6);

  const result: RunListEntry = {
    id: runId,
    chapterTitle,
    topicSummary: trimText(topicSummary, 300),
    statusLabel: statusLabelFromPhaseCards(phaseCards),
    modifiedAt: dirStat.mtime.toISOString(),
    fileCount: directoryStats.fileCount,
    artifactCount: topFiles.length,
    totalBytes: directoryStats.totalBytes,
    totalCostUsd,
    durationSeconds,
    completenessScore,
    focusTerms,
    counts,
    phaseCards,
  };

  runIndexCache.set(runId, { key: cacheKey, data: result });
  return result;
}

async function buildPromptGroup(runDir: string, prefix: string, key: string, label: string, blurb: string): Promise<PromptTraceGroup | null> {
  const topFiles = await fs.readdir(runDir);
  const suffixes = [".system_prompt.txt", ".user_prompt.txt", ".output_text.txt", ".openai_meta.json", ".call_meta.json"];
  const bases = unique(
    topFiles
      .filter((file) => suffixes.some((suffix) => file.startsWith(prefix) && file.endsWith(suffix)))
      .map((file) => {
        const suffix = suffixes.find((candidate) => file.endsWith(candidate));
        return suffix ? file.slice(0, -suffix.length) : file;
      })
      .filter((base) => base.includes("_attempt") || base === prefix),
  ).sort((left, right) => {
    const leftAttempt = Number(left.match(/_attempt(\d+)/)?.[1] ?? "999");
    const rightAttempt = Number(right.match(/_attempt(\d+)/)?.[1] ?? "999");
    return leftAttempt - rightAttempt;
  });

  const attempts = await Promise.all(
    bases.map(async (base) => {
      const [systemPrompt, userPrompt, outputText, openAiMeta, callMeta] = await Promise.all([
        readTextFile(path.join(runDir, `${base}.system_prompt.txt`)),
        readTextFile(path.join(runDir, `${base}.user_prompt.txt`)),
        readTextFile(path.join(runDir, `${base}.output_text.txt`)),
        readJsonFile<Record<string, unknown>>(path.join(runDir, `${base}.openai_meta.json`)),
        readJsonFile<Record<string, unknown>>(path.join(runDir, `${base}.call_meta.json`)),
      ]);

      const usage = asRecord(openAiMeta?.usage);
      const cost = asRecord(openAiMeta?.cost_estimate);
      const attemptLabel = base === prefix ? "Resolved output" : `Attempt ${base.match(/_attempt(\d+)/)?.[1] ?? "?"}`;

      return {
        id: base,
        label: attemptLabel,
        model: asString(openAiMeta?.model_used) || asString(openAiMeta?.model_requested) || "—",
        latencySeconds: asNullableNumber(openAiMeta?.latency_s),
        inputTokens: asNumber(usage.input_tokens),
        outputTokens: asNumber(usage.output_tokens),
        reasoningTokens: asNumber(usage.reasoning_tokens),
        cachedInputTokens: asNumber(usage.cached_input_tokens),
        costUsd: asNumber(cost.total_cost_usd),
        status: asString(openAiMeta?.status) || asString(callMeta?.status) || "captured",
        systemPrompt,
        userPrompt,
        outputText,
        errorNote: asString(openAiMeta?.error) || "",
      } satisfies PromptTraceAttempt;
    }),
  );

  if (!attempts.length) {
    return null;
  }

  return {
    key,
    label,
    blurb,
    attempts,
  };
}

function humanizeEvent(event: string): string {
  switch (event) {
    case "run_initialized":
      return "Run initialized";
    case "lint_failed":
      return "Planner lint failed";
    case "plan_repaired":
      return "Planner repaired";
    case "cache_write":
      return "Artifact cached";
    case "http_request":
      return "Provider request";
    default:
      return event.replace(/_/g, " ");
  }
}

function humanizeStage(stage: string): string {
  return stage
    .replace(/^phase_/, "")
    .replace(/_/g, " ")
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

async function readNotableEvents(runDir: string): Promise<RunDetail["overview"]["notableEvents"]> {
  const logRows = await readJsonLinesFile<Record<string, unknown>>(path.join(runDir, "logs.jsonl"));
  return logRows
    .filter((row) => {
      const event = asString(row.event);
      return ["run_initialized", "lint_failed", "plan_repaired", "cache_write", "http_request"].includes(event);
    })
    .slice(0, 18)
    .map((row) => {
      const event = asString(row.event);
      const detail = trimText(
        asString(row.error) ||
          asString(row.path) ||
          asString(row.url) ||
          asString(row.model_used) ||
          asString(row.msg),
        180,
      );
      return {
        ts: asString(row.ts),
        stage: humanizeStage(asString(row.stage)),
        label: humanizeEvent(event),
        detail,
      };
    });
}

function createQueryRow(
  provider: "openalex" | "semanticscholar",
  index: number,
  row: Record<string, unknown>,
): QueryRow {
  return {
    id: `${provider}:${index}`,
    provider,
    intent: asString(row.intent),
    language: asString(row.language),
    searchField: asString(row.search_field) || (provider === "semanticscholar" ? "bulk query" : ""),
    queryText: asString(row.query_string),
    filters: asString(row.filters),
    sort: asString(row.sort),
    note: asString(row.notes),
    hitCount: 0,
    maxRank: 0,
    sampleTitles: [],
    sampleYears: [],
  };
}

function decadeLabel(year: number): string {
  const decade = Math.floor(year / 10) * 10;
  return `${decade}s`;
}

function queryIncludesAnchor(queryText: string, anchorTerms: string[]): boolean {
  const lower = queryText.toLowerCase();
  return anchorTerms.some((anchor) => anchor && lower.includes(anchor.toLowerCase()));
}

async function enrichQueryHits(
  runDir: string,
  provider: "openalex" | "semanticscholar",
  rows: QueryRow[],
  decadeCounts: Map<string, number>,
): Promise<void> {
  const fileName = provider === "openalex" ? "openalex_raw.jsonl" : "semanticscholar_raw.jsonl";
  const byIndex = new Map<number, QueryRow>();
  rows.forEach((row, index) => byIndex.set(index, row));

  await streamJsonLines(path.join(runDir, fileName), async (payload) => {
    const queryIndex = asNumber(payload.query_i, -1);
    const row = byIndex.get(queryIndex);
    if (!row) {
      return;
    }
    row.hitCount += 1;
    row.maxRank = Math.max(row.maxRank, asNumber(payload.rank));

    const carrier = provider === "openalex" ? asRecord(payload.work) : asRecord(payload.paper);
    const title = asString(carrier.display_name) || asString(carrier.title);
    if (title && row.sampleTitles.length < 3) {
      row.sampleTitles.push(title);
    }
    const year = asNumber(carrier.publication_year) || asNumber(carrier.year);
    if (year) {
      if (row.sampleYears.length < 4) {
        row.sampleYears.push(year);
      }
      const bucket = decadeLabel(year);
      decadeCounts.set(bucket, (decadeCounts.get(bucket) ?? 0) + 1);
    }
  });
}

function buildProviderSummary(provider: QueryProviderData): RetrievalProviderSummary {
  const strongest = [...provider.rows].sort((left, right) => right.hitCount - left.hitCount)[0];
  const uniqueYears = unique(provider.rows.flatMap((row) => row.sampleYears)).length;
  return {
    provider: provider.provider,
    label: provider.label,
    totalHits: provider.totalHits,
    queryCount: provider.queryCount,
    zeroHitQueries: provider.zeroHitCount,
    uniqueYears,
    strongestQuery: trimText(strongest?.queryText ?? "", 88),
    strongestHits: strongest?.hitCount ?? 0,
  };
}

async function buildQueryAndRetrievalData(
  runDir: string,
  anchorTerms: string[],
): Promise<{
  queryProviders: QueryProviderData[];
  retrievalProviders: RetrievalProviderSummary[];
  decadeBuckets: Array<{ decade: string; count: number }>;
  topQueries: QueryRow[];
  zeroHitQueries: QueryRow[];
}> {
  const openAlexRaw = await readJsonFile<Record<string, unknown>>(path.join(runDir, "openalex_queries.json"));
  const s2Raw = await readJsonFile<Record<string, unknown>>(path.join(runDir, "semanticscholar_queries.json"));
  const openAlexRows = asArray<Record<string, unknown>>(asRecord(openAlexRaw).openalex_queries).map((row, index) =>
    createQueryRow("openalex", index, row),
  );
  const s2Rows = asArray<Record<string, unknown>>(asRecord(s2Raw).s2_bulk_queries).map((row, index) =>
    createQueryRow("semanticscholar", index, row),
  );
  const decadeCounts = new Map<string, number>();

  await Promise.all([
    enrichQueryHits(runDir, "openalex", openAlexRows, decadeCounts),
    enrichQueryHits(runDir, "semanticscholar", s2Rows, decadeCounts),
  ]);

  const providers: QueryProviderData[] = [
    {
      provider: "openalex" as const,
      label: "OpenAlex",
      queryCount: openAlexRows.length,
      totalHits: openAlexRows.reduce((sum, row) => sum + row.hitCount, 0),
      zeroHitCount: openAlexRows.filter((row) => row.hitCount === 0).length,
      duplicateQueryCount: Math.max(0, openAlexRows.length - unique(openAlexRows.map((row) => `${row.intent}:${row.language}:${row.queryText}`)).length),
      anchorCoverageHits: openAlexRows.filter((row) => row.intent === "match" && queryIncludesAnchor(row.queryText, anchorTerms)).length,
      anchorCoverageTotal: openAlexRows.filter((row) => row.intent === "match").length,
      languages: unique(openAlexRows.map((row) => row.language).filter(Boolean)),
      intents: unique(openAlexRows.map((row) => row.intent).filter(Boolean)),
      rows: openAlexRows,
    },
    {
      provider: "semanticscholar" as const,
      label: "Semantic Scholar",
      queryCount: s2Rows.length,
      totalHits: s2Rows.reduce((sum, row) => sum + row.hitCount, 0),
      zeroHitCount: s2Rows.filter((row) => row.hitCount === 0).length,
      duplicateQueryCount: Math.max(0, s2Rows.length - unique(s2Rows.map((row) => `${row.intent}:${row.language}:${row.queryText}`)).length),
      anchorCoverageHits: s2Rows.filter((row) => row.intent === "match" && queryIncludesAnchor(row.queryText, anchorTerms)).length,
      anchorCoverageTotal: s2Rows.filter((row) => row.intent === "match").length,
      languages: unique(s2Rows.map((row) => row.language).filter(Boolean)),
      intents: unique(s2Rows.map((row) => row.intent).filter(Boolean)),
      rows: s2Rows,
    },
  ].filter((provider) => provider.queryCount > 0);

  const queryRows = providers.flatMap((provider) => provider.rows);
  const retrievalProviders = providers.map(buildProviderSummary);
  const topQueries = [...queryRows].sort((left, right) => right.hitCount - left.hitCount).slice(0, 8);
  const zeroHitQueries = queryRows.filter((row) => row.hitCount === 0).slice(0, 8);
  const decadeBuckets = [...decadeCounts.entries()]
    .sort((left, right) => left[0].localeCompare(right[0]))
    .map(([decade, count]) => ({ decade, count }))
    .slice(-12);

  return {
    queryProviders: providers,
    retrievalProviders,
    decadeBuckets,
    topQueries,
    zeroHitQueries,
  };
}

interface MutableCandidate extends CandidateRow {
  authors: string[];
  abstractText: string;
  externalIdKeys: string[];
  venueIsCore: boolean | null;
  sourceTraces: CandidateDetail["sourceTraces"];
  evidenceSnippets: string[];
  coverageTags: CandidateDetail["coverageTags"];
  coverageTagIds: string[];
  rerankDecisions: CandidateDetail["rerankDecisions"];
  rankingPositions: CandidateDetail["rankingPositions"];
  requiredFacetHits: number;
  scoresMeta: {
    match: number | null;
    authority: number | null;
    best: number | null;
    topM: number | null;
    cov: number | null;
    facetAux: number | null;
  };
}

function makeCandidateRecord(candidate: Record<string, unknown>): MutableCandidate {
  const authors = asStringArray(candidate.authors);
  const doi = asString(candidate.doi);
  const url = asString(candidate.url);
  return {
    id: asString(candidate.id),
    title: asString(candidate.title),
    doi,
    url,
    year: asNullableNumber(candidate.year),
    venue: asString(candidate.venue),
    pool: asString(candidate.pool) || "with_abstract",
    citations: asNumber(candidate.citations),
    influentialCitations: asNumber(candidate.influential_citations),
    language: asString(candidate.language),
    providers: Object.keys(asRecord(candidate.provider_ids)),
    intents: asStringArray(candidate.intents),
    matchLane: null,
    authorityLane: null,
    semanticStage1: null,
    semanticStage2: null,
    rerankMatch: null,
    rerankAuthority: null,
    topFacets: [],
    authorsLabel: authors.slice(0, 3).join(", "),
    abstractPreview: trimText(asString(candidate.abstract), 420),
    coverageExcerpt: "",
    rerankSummary: "",
    providerLabel: Object.keys(asRecord(candidate.provider_ids)).join(" + "),
    resourceUrl: bestResourceUrl(url, doi),
    sourceCount: asArray<Record<string, unknown>>(candidate.sources).length,
    tagCount: 0,
    requiredFacetHits: 0,
    hasAbstract: Boolean(asString(candidate.abstract).trim()),
    isCrossProvider: Object.keys(asRecord(candidate.provider_ids)).length > 1,
    evidenceSnippets: [],
    outputMatchRank: null,
    outputAuthorityRank: null,
    authors,
    abstractText: asString(candidate.abstract),
    externalIdKeys: Object.keys(asRecord(candidate.external_ids)),
    venueIsCore: typeof candidate.venue_is_core === "boolean" ? (candidate.venue_is_core as boolean) : null,
    sourceTraces: asArray<Record<string, unknown>>(candidate.sources).map((row) => ({
      provider: asString(row.provider),
      queryIndex: asNullableNumber(row.query_i),
      intent: asString(row.intent),
      language: asString(row.language),
      rank: asNullableNumber(row.rank),
    })),
    coverageTags: [],
    coverageTagIds: [],
    rerankDecisions: [],
    rankingPositions: [],
    scoresMeta: {
      match: null,
      authority: null,
      best: null,
      topM: null,
      cov: null,
      facetAux: null,
    },
  };
}

function addRankingPosition(record: MutableCandidate, label: string, value: number | null): void {
  if (value === null) {
    return;
  }
  record.rankingPositions = [
    ...record.rankingPositions.filter((item) => item.label !== label),
    { label, value: `#${value}` },
  ];
}

function candidateRowFromMutable(record: MutableCandidate): CandidateRow {
  const bestRerank = [...record.rerankDecisions]
    .sort((left, right) => (right.score ?? -1) - (left.score ?? -1))[0];
  return {
    id: record.id,
    title: record.title,
    doi: record.doi,
    url: record.url,
    year: record.year,
    venue: record.venue,
    pool: record.pool,
    citations: record.citations,
    influentialCitations: record.influentialCitations,
    language: record.language,
    providers: record.providers,
    intents: record.intents,
    matchLane: record.matchLane,
    authorityLane: record.authorityLane,
    semanticStage1: record.semanticStage1,
    semanticStage2: record.semanticStage2,
    rerankMatch: record.rerankMatch,
    rerankAuthority: record.rerankAuthority,
    topFacets: record.topFacets,
    authorsLabel: record.authors.slice(0, 3).join(", "),
    abstractPreview: trimText(record.abstractText, 420),
    coverageExcerpt: trimText(record.coverageTags[0]?.excerpt ?? "", 240),
    rerankSummary: trimText(bestRerank?.briefRationale ?? "", 240),
    providerLabel: record.providers.join(" + "),
    resourceUrl: bestResourceUrl(record.url, record.doi),
    sourceCount: record.sourceTraces.length,
    tagCount: record.coverageTags.length,
    requiredFacetHits: record.requiredFacetHits,
    hasAbstract: Boolean(record.abstractText.trim()),
    isCrossProvider: record.providers.length > 1,
    evidenceSnippets: record.evidenceSnippets.slice(0, 2),
    outputMatchRank: record.outputMatchRank,
    outputAuthorityRank: record.outputAuthorityRank,
  };
}

function getOrCreateCandidate(map: Map<string, MutableCandidate>, row: Record<string, unknown>): MutableCandidate | null {
  const id = asString(row.id);
  if (!id) {
    return null;
  }
  const existing = map.get(id);
  if (existing) {
    return existing;
  }
  const created = makeCandidateRecord(row);
  map.set(id, created);
  return created;
}

function applyRankings(
  candidateMap: Map<string, MutableCandidate>,
  rankingsRoot: Record<string, unknown> | null,
  labelPrefix: string,
): Record<string, string[]> {
  const result: Record<string, string[]> = {};
  const rankings = asRecord(rankingsRoot?.rankings ?? rankingsRoot);
  for (const [lane, lanePayload] of Object.entries(rankings)) {
    const laneRecord = asRecord(lanePayload);
    for (const [pool, idsValue] of Object.entries(laneRecord)) {
      const ids = asStringArray(idsValue);
      const sectionKey = `${lane}:${pool}`;
      result[sectionKey] = ids;
      ids.forEach((id, index) => {
        const record = candidateMap.get(id);
        if (!record) {
          return;
        }
        const label = `${labelPrefix} ${lane} ${pool === "with_abstract" ? "abs" : "no abs"}`;
        addRankingPosition(record, label, index + 1);
      });
    }
  }
  return result;
}

function sortByScore(rows: CandidateRow[], pick: (row: CandidateRow) => number | null): CandidateRow[] {
  return [...rows].sort((left, right) => {
    const leftScore = pick(left) ?? -1;
    const rightScore = pick(right) ?? -1;
    return rightScore - leftScore;
  });
}

function buildLeaderboard(
  id: string,
  label: string,
  subtitle: string,
  rows: CandidateRow[],
  pick: (row: CandidateRow) => number | null,
  pool?: string,
): LeaderboardSection {
  const filtered = pool ? rows.filter((row) => row.pool === pool) : rows;
  return {
    id,
    label,
    subtitle,
    rows: sortByScore(filtered, pick).slice(0, TOP_LIMIT),
  };
}

function candidateAnchorHit(row: MutableCandidate, anchorTerms: string[]): boolean {
  if (!anchorTerms.length) {
    return false;
  }
  const text = `${row.title} ${row.abstractText}`.toLowerCase();
  return anchorTerms.some((term) => term && text.includes(term.toLowerCase()));
}

function candidateEconHits(row: MutableCandidate, econTerms: string[]): number {
  if (!econTerms.length) {
    return 0;
  }
  const text = `${row.title} ${row.abstractText}`.toLowerCase();
  return econTerms.reduce((sum, term) => (term && text.includes(term.toLowerCase()) ? sum + 1 : sum), 0);
}

async function buildCandidateData(
  runDir: string,
  options: {
    requiredFacetIds: string[];
    anchorTerms: string[];
    econTerms: string[];
  },
): Promise<{
  candidateCatalog: CandidateRow[];
  funnel: OverviewMetric[];
  poolSummary: Array<{ label: string; count: number; detail: string }>;
  providerMix: LabelValue[];
  idCoverage: LabelValue[];
  topCited: CandidateRow[];
  mergedCandidates: CandidateRow[];
  noAnchorTopCited: CandidateRow[];
  econHitCandidates: CandidateRow[];
  weakestMetadata: CandidateRow[];
  scoring: RunDetail["scoring"];
  coverage: RunDetail["coverage"];
  rerank: RunDetail["rerank"];
  final: RunDetail["final"];
  comparisonBasis: RunDetail["comparisonBasis"];
}> {
  const [
    normalizedCandidates,
    stage1Rows,
    stage2Rows,
    finalRows,
    scoringDebugRows,
    coverageRows,
    rerankRows,
    mmrDebug,
    hygieneReport,
    facetsIndex,
    rankingsStageG,
    rankingsStageI,
    output,
  ] = await Promise.all([
    readJsonLinesFile<Record<string, unknown>>(path.join(runDir, "candidates_normalized.jsonl")),
    readJsonLinesFile<Record<string, unknown>>(path.join(runDir, "scores_stage1.jsonl")),
    readJsonLinesFile<Record<string, unknown>>(path.join(runDir, "scores_stage2.jsonl")),
    readJsonLinesFile<Record<string, unknown>>(path.join(runDir, "scores_final.jsonl")),
    readJsonLinesFile<Record<string, unknown>>(path.join(runDir, "phase_f_scoring_debug.jsonl")),
    readJsonLinesFile<Record<string, unknown>>(path.join(runDir, "coverage_tags.jsonl")),
    readJsonLinesFile<Record<string, unknown>>(path.join(runDir, "rerank_results.jsonl")),
    readJsonFile<Record<string, unknown>>(path.join(runDir, "phase_f_mmr_debug.json")),
    readJsonFile<Record<string, unknown>>(path.join(runDir, "phase_f_candidate_hygiene_report.json")),
    readJsonFile<Record<string, unknown>>(path.join(runDir, "facets_index.json")),
    readJsonFile<Record<string, unknown>>(path.join(runDir, "rankings_stageg.json")),
    readJsonFile<Record<string, unknown>>(path.join(runDir, "rankings_stagei.json")),
    readJsonFile<Record<string, unknown>>(path.join(runDir, "output.json")),
  ]);

  const candidateMap = new Map<string, MutableCandidate>();
  const requiredFacetIdSet = new Set(options.requiredFacetIds);
  const facetLabelById = new Map(
    asArray<Record<string, unknown>>(facetsIndex?.facets).map((facet) => [
      asString(facet.facet_id),
      asString(facet.facet_label_en) || asString(facet.facet_label_de) || asString(facet.facet_id),
    ]),
  );
  normalizedCandidates.forEach((candidate) => {
    const record = makeCandidateRecord(candidate);
    candidateMap.set(record.id, record);
  });

  stage1Rows.forEach((row) => {
    const record = getOrCreateCandidate(candidateMap, row);
    if (!record) {
      return;
    }
    record.semanticStage1 = asNullableNumber(row.semantic_stage1);
    record.matchLane = asNullableNumber(row.match_lane);
    record.authorityLane = asNullableNumber(row.authority_lane);
    record.scoresMeta.best = asNullableNumber(row.best);
    record.scoresMeta.topM = asNullableNumber(row.top_m);
    record.scoresMeta.cov = asNullableNumber(row.cov);
  });

  stage2Rows.forEach((row) => {
    const record = getOrCreateCandidate(candidateMap, row);
    if (!record) {
      return;
    }
    record.semanticStage2 = asNullableNumber(row.semantic_stage2);
    record.evidenceSnippets = asStringArray(row.evidence_chunks).slice(0, 4);
    if (!record.evidenceSnippets.length) {
      const chunk = asString(row.semantic_evidence_chunk);
      if (chunk) {
        record.evidenceSnippets = [chunk];
      }
    }
  });

  finalRows.forEach((row) => {
    const record = getOrCreateCandidate(candidateMap, row);
    if (!record) {
      return;
    }
    const scores = asRecord(row.scores);
    record.matchLane = asNullableNumber(scores.match_lane) ?? record.matchLane;
    record.authorityLane = asNullableNumber(scores.authority_lane) ?? record.authorityLane;
    record.semanticStage1 = asNullableNumber(scores.semantic_stage1) ?? record.semanticStage1;
    record.semanticStage2 = asNullableNumber(scores.semantic_stage2) ?? record.semanticStage2;
    record.scoresMeta.match = asNullableNumber(scores.match);
    record.scoresMeta.authority = asNullableNumber(scores.authority);
    record.scoresMeta.best = asNullableNumber(scores.best) ?? record.scoresMeta.best;
    record.scoresMeta.topM = asNullableNumber(scores.top_m) ?? record.scoresMeta.topM;
    record.scoresMeta.cov = asNullableNumber(scores.cov) ?? record.scoresMeta.cov;
    record.scoresMeta.facetAux = asNullableNumber(scores.facet_match_aux);
  });

  scoringDebugRows.forEach((row) => {
    const record = candidateMap.get(asString(row.id));
    if (!record) {
      return;
    }
    record.semanticStage1 = asNullableNumber(row.semantic_stage1) ?? record.semanticStage1;
    record.semanticStage2 = asNullableNumber(row.semantic_stage2) ?? record.semanticStage2;
    record.matchLane = asNullableNumber(row.match_lane) ?? record.matchLane;
    record.authorityLane = asNullableNumber(row.authority_lane) ?? record.authorityLane;
  });

  coverageRows.forEach((row) => {
    const record = candidateMap.get(asString(row.id));
    if (!record) {
      return;
    }
    const tags = asArray<Record<string, unknown>>(row.coverage_tags)
      .map((tag) => ({
        facetId: asString(tag.facet_id),
        label: asString(tag.facet_label_en),
        score: asNumber(tag.score),
        excerpt: asString(tag.excerpt),
      }))
      .sort((left, right) => right.score - left.score);
    record.coverageTags = tags.slice(0, 6).map((tag) => ({
      label: tag.label,
      score: tag.score,
      excerpt: tag.excerpt,
    }));
    record.coverageTagIds = unique(tags.map((tag) => tag.facetId).filter(Boolean));
    record.requiredFacetHits = record.coverageTagIds.filter((facetId) => requiredFacetIdSet.has(facetId)).length;
    record.topFacets = tags.slice(0, 3).map((tag) => tag.label);
  });

  rerankRows.forEach((row) => {
    const record = candidateMap.get(asString(row.id));
    if (!record) {
      return;
    }
    const lane = asString(row.lane);
    const rerank = asRecord(row.rerank);
    const score = asNullableNumber(rerank.llm_score_0_100);
    if (lane === "match") {
      record.rerankMatch = score;
    }
    if (lane === "authority") {
      record.rerankAuthority = score;
    }
    record.rerankDecisions.push({
      lane,
      score,
      offTopic: Boolean(rerank.off_topic),
      insufficientInfo: Boolean(rerank.insufficient_info),
      briefRationale: asString(rerank.brief_rationale) || asString(rerank.rationale),
      rubric: Object.entries(asRecord(rerank.rubric)).map(([label, value]) => ({
        label: label.replace(/_/g, " "),
        value: `${asNumber(value)}`,
      })),
    });
  });

  const stageGRankings = applyRankings(candidateMap, rankingsStageG, "Stage G");
  const stageIRankings = applyRankings(candidateMap, asRecord(rankingsStageI?.rankings), "Stage I");

  const outputTopSections: LeaderboardSection[] = [];
  const topIdsBySection: Record<string, string[]> = {};
  const top = asRecord(output?.top);
  for (const [lane, lanePayload] of Object.entries(top)) {
    for (const [pool, itemsValue] of Object.entries(asRecord(lanePayload))) {
      const items = asArray<Record<string, unknown>>(itemsValue);
      const sectionId = `${lane}:${pool}`;
      const rows = items.map((item, index) => {
        const id = asString(item.id);
        const existing = candidateMap.get(id);
        if (existing) {
          if (lane === "match") {
            existing.outputMatchRank = index + 1;
            addRankingPosition(existing, "Final output match", index + 1);
          }
          if (lane === "authority") {
            existing.outputAuthorityRank = index + 1;
            addRankingPosition(existing, "Final output authority", index + 1);
          }
        }
        return existing ? candidateRowFromMutable(existing) : candidateRowFromMutable(makeCandidateRecord(item));
      });
      topIdsBySection[sectionId] = rows.map((row) => row.id);
      const abstractCount = rows.filter((row) => row.hasAbstract).length;
      const reqHitMean =
        rows.length > 0 ? rows.reduce((sum, row) => sum + row.requiredFacetHits, 0) / rows.length : 0;
      const linkedCount = rows.filter((row) => Boolean(row.resourceUrl)).length;
      outputTopSections.push({
        id: sectionId,
        label: `${lane === "match" ? "Match lane" : "Authority lane"} / ${pool === "with_abstract" ? "with abstract" : "without abstract"}`,
        subtitle: "Final output list",
        metrics: [
          { label: "Rows", value: `${rows.length}` },
          { label: "Abstract", value: rows.length ? `${Math.round((abstractCount / rows.length) * 100)}%` : "0%" },
          { label: "Req-hit mean", value: reqHitMean ? reqHitMean.toFixed(1) : "0.0" },
          { label: "Links", value: `${linkedCount}` },
        ],
        rows,
      });
    }
  }

  const candidateValues = [...candidateMap.values()];
  const candidateRows = candidateValues.map(candidateRowFromMutable);

  const topCited = [...candidateRows].sort((left, right) => right.citations - left.citations).slice(0, 12);
  const weakestMetadata = [...candidateRows]
    .filter((row) => row.pool === "without_abstract" || !row.language || row.providers.length === 1)
    .sort((left, right) => (right.authorityLane ?? -1) - (left.authorityLane ?? -1))
    .slice(0, 12);

  const providerMix: LabelValue[] = [
    { label: "OpenAlex id", value: `${candidateValues.filter((row) => row.providers.includes("openalex")).length}` },
    { label: "S2 id", value: `${candidateValues.filter((row) => row.providers.includes("semanticscholar")).length}` },
    { label: "Both providers", value: `${candidateValues.filter((row) => row.providers.length > 1).length}` },
    { label: "Cross-provider", value: `${candidateValues.filter((row) => row.providers.includes("openalex") && row.providers.includes("semanticscholar")).length}` },
  ];

  const idCoverage: LabelValue[] = [
    { label: "DOI", value: `${candidateValues.filter((row) => Boolean(row.doi)).length}` },
    { label: "PMID", value: `${candidateValues.filter((row) => row.externalIdKeys.includes("pmid")).length}` },
    { label: "PMCID", value: `${candidateValues.filter((row) => row.externalIdKeys.includes("pmcid")).length}` },
    { label: "ArXiv", value: `${candidateValues.filter((row) => row.externalIdKeys.includes("arxiv")).length}` },
  ];

  const mergedCandidates = candidateValues
    .filter((row) => row.sourceTraces.length > 1)
    .sort((left, right) => {
      if (left.isCrossProvider !== right.isCrossProvider) {
        return left.isCrossProvider ? -1 : 1;
      }
      return (right.citations ?? 0) - (left.citations ?? 0);
    })
    .slice(0, 16)
    .map(candidateRowFromMutable);

  const noAnchorTopCited = candidateValues
    .filter((row) => !candidateAnchorHit(row, options.anchorTerms))
    .sort((left, right) => right.citations - left.citations)
    .slice(0, 16)
    .map(candidateRowFromMutable);

  const econHitCandidates = candidateValues
    .map((row) => ({ row, hits: candidateEconHits(row, options.econTerms) }))
    .filter((entry) => entry.hits > 0)
    .sort((left, right) => {
      if (right.hits !== left.hits) {
        return right.hits - left.hits;
      }
      return right.row.citations - left.row.citations;
    })
    .slice(0, 16)
    .map((entry) => candidateRowFromMutable(entry.row));

  const poolSummary = [
    {
      label: "With abstract",
      count: candidateRows.filter((row) => row.pool === "with_abstract").length,
      detail: `${candidateRows.filter((row) => row.pool === "with_abstract" && row.semanticStage2 !== null).length} stage2-scored`,
    },
    {
      label: "Without abstract",
      count: candidateRows.filter((row) => row.pool === "without_abstract").length,
      detail: `${candidateRows.filter((row) => row.pool === "without_abstract" && row.rerankMatch !== null).length} reranked`,
    },
  ];

  const funnel = compact<OverviewMetric>([
    normalizedCandidates.length ? { label: "Normalized candidates", value: `${normalizedCandidates.length}`, detail: "deduped provider rows that survived normalization" } : null,
    stage1Rows.length ? { label: "Stage 1 scored", value: `${stage1Rows.length}`, detail: "semantic first pass across full pool" } : null,
    stage2Rows.length ? { label: "Stage 2 rescored", value: `${stage2Rows.length}`, detail: "facet chunk expansion shortlist" } : null,
    finalRows.length ? { label: "Final scored", value: `${finalRows.length}`, detail: "rows kept for ranking and output" } : null,
    rerankRows.length ? { label: "Rerank calls", value: `${rerankRows.length}`, detail: "pointwise lane rerank decisions" } : null,
  ]);

  const allRowsSorted = [...candidateRows].sort((left, right) => {
    const leftScore = Math.max(left.matchLane ?? -1, left.authorityLane ?? -1);
    const rightScore = Math.max(right.matchLane ?? -1, right.authorityLane ?? -1);
    return rightScore - leftScore;
  });

  const scoring: RunDetail["scoring"] = {
    hygiene: Object.entries(hygieneReport ?? {}).map(([label, value]) => ({
      label: label.replace(/_/g, " "),
      value: `${value}`,
    })),
    mmr: compact<LabelValue>([
      mmrDebug ? { label: "MMR enabled", value: Boolean(mmrDebug.enabled) ? "yes" : "no" } : null,
      mmrDebug ? { label: "Lambda", value: `${asNumber(mmrDebug.lambda)}` } : null,
      mmrDebug ? { label: "Top-k", value: `${asNumber(mmrDebug.top_k)}` } : null,
    ]),
    stage1: [
      buildLeaderboard("stage1-match-abs", "Stage 1 / Match / With abstract", "highest match lane after first pass", candidateRows, (row) => row.matchLane, "with_abstract"),
      buildLeaderboard("stage1-authority-abs", "Stage 1 / Authority / With abstract", "highest authority lane after first pass", candidateRows, (row) => row.authorityLane, "with_abstract"),
      buildLeaderboard("stage1-match-noabs", "Stage 1 / Match / Without abstract", "no-abstract candidates retained by lane score", candidateRows, (row) => row.matchLane, "without_abstract"),
      buildLeaderboard("stage1-authority-noabs", "Stage 1 / Authority / Without abstract", "no-abstract authority picks", candidateRows, (row) => row.authorityLane, "without_abstract"),
    ],
    stage2: [
      buildLeaderboard("stage2-match", "Stage 2 / Match", "semantic chunk reranking shortlist", candidateRows.filter((row) => row.semanticStage2 !== null), (row) => row.semanticStage2),
      buildLeaderboard("stage2-authority", "Stage 2 / Authority", "authority lane rows with stage2 evidence", candidateRows.filter((row) => row.semanticStage2 !== null), (row) => row.authorityLane),
    ],
    final: [
      buildLeaderboard("final-match", "Final / Match lane", "final match-lane leaders", candidateRows, (row) => row.matchLane),
      buildLeaderboard("final-authority", "Final / Authority lane", "final authority-lane leaders", candidateRows, (row) => row.authorityLane),
    ],
  };

  const facetCoverageAccumulator = new Map<string, { label: string; count: number; scoreTotal: number; sampleTitle: string }>();
  [...candidateMap.values()].forEach((record) => {
    record.coverageTags.forEach((tag) => {
      const key = tag.label || "Unknown facet";
      const existing = facetCoverageAccumulator.get(key) ?? {
        label: key,
        count: 0,
        scoreTotal: 0,
        sampleTitle: record.title,
      };
      existing.count += 1;
      existing.scoreTotal += tag.score;
      if (!existing.sampleTitle) {
        existing.sampleTitle = record.title;
      }
      facetCoverageAccumulator.set(key, existing);
    });
  });

  const outputSectionRequiredStats = Object.entries(topIdsBySection).map(([sectionId, ids]) => {
    const hits = ids.map((id) => candidateMap.get(id)?.requiredFacetHits ?? 0);
    const covered = new Set(
      ids.flatMap((id) => candidateMap.get(id)?.coverageTagIds ?? []).filter((facetId) => requiredFacetIdSet.has(facetId)),
    );
    const missing = options.requiredFacetIds.filter((facetId) => !covered.has(facetId));
    return {
      sectionId,
      label: sectionId.replace(":", " / "),
      reqHitMean: hits.length ? hits.reduce((sum, value) => sum + value, 0) / hits.length : 0,
      missing,
    };
  });

  const coveredRequiredFacetCount = new Set(outputSectionRequiredStats.flatMap((row) => options.requiredFacetIds.filter((facetId) => !row.missing.includes(facetId)))).size;
  const bestReqHitMean = Math.max(...outputSectionRequiredStats.map((row) => row.reqHitMean), 0);

  const coverage: RunDetail["coverage"] = {
    facetCoverage: [...facetCoverageAccumulator.entries()]
      .map(([facetId, value]) => ({
        facetId,
        label: value.label,
        hitCount: value.count,
        avgScore: Math.round((value.scoreTotal / Math.max(value.count, 1)) * 100) / 100,
        sampleTitle: value.sampleTitle,
      }))
      .sort((left, right) => right.hitCount - left.hitCount)
      .slice(0, 12),
    requiredFacetSummary: compact([
      options.requiredFacetIds.length ? { label: "Required facets", value: `${options.requiredFacetIds.length}` } : null,
      options.requiredFacetIds.length ? { label: "Covered in outputs", value: `${coveredRequiredFacetCount}` } : null,
      options.requiredFacetIds.length ? { label: "Missing in outputs", value: `${Math.max(0, options.requiredFacetIds.length - coveredRequiredFacetCount)}` } : null,
      outputSectionRequiredStats.length ? { label: "Best req-hit mean", value: bestReqHitMean.toFixed(1) } : null,
    ]),
    missingRequiredBySection: outputSectionRequiredStats
      .filter((row) => row.missing.length > 0)
      .map((row) => ({
        sectionId: row.sectionId,
        label: row.label,
        missingCount: row.missing.length,
        examples: row.missing.slice(0, 6).map((facetId) => facetLabelById.get(facetId) || facetId),
      })),
    stageGRankings: Object.entries(stageGRankings).map(([sectionId, ids]) => ({
      id: `stageg:${sectionId}`,
      label: `${sectionId.replace(":", " / ")}`,
      subtitle: "Stage G shortlist after MMR",
      rows: ids
        .map((id) => candidateMap.get(id))
        .filter((row): row is MutableCandidate => Boolean(row))
        .slice(0, TOP_LIMIT)
        .map(candidateRowFromMutable),
    })),
    coverageRich: [...candidateRows]
      .sort((left, right) => (right.topFacets.length || 0) - (left.topFacets.length || 0))
      .slice(0, 16),
  };

  const pairwiseSummaryRecord = asRecord(asRecord(rankingsStageI?.pairwise_refinement).summary);
  const pairwiseSummary = Object.entries(pairwiseSummaryRecord).map(([label, value]) => ({
    label: label.replace(/_/g, " "),
    value: `${value}`,
  }));

  const pairwiseDecisions: RunDetail["rerank"]["pairwiseDecisions"] = [];
  const pairwiseDir = path.join(runDir, "cache", "rerank_pairwise");
  try {
    const pairwiseFiles = (await fs.readdir(pairwiseDir)).filter((file) => file.endsWith(".json")).slice(0, 60);
    const pairwiseRows = await Promise.all(
      pairwiseFiles.map((file) => readJsonFile<Record<string, unknown>>(path.join(pairwiseDir, file))),
    );
    pairwiseRows.forEach((row) => {
      if (!row) {
        return;
      }
      const openai = asRecord(row.openai);
      const costEstimate = asRecord(openai.cost_estimate);
      const pairwise = asRecord(row.pairwise);
      pairwiseDecisions.push({
        lane: asString(row.lane),
        pool: asString(row.pool),
        leftId: asString(row.id_left),
        rightId: asString(row.id_right),
        winnerId: asString(pairwise.winner_cid),
        confidence: asNullableNumber(pairwise.confidence_0_3),
        briefRationale: trimText(asString(pairwise.brief_rationale), 240),
        latencySeconds: asNullableNumber(openai.latency_s),
        costUsd: asNumber(costEstimate.total_cost_usd),
      });
    });
  } catch {
    // ignore missing pairwise cache
  }

  const rerankMetrics: OverviewMetric[] = compact([
    rerankRows.length ? { label: "Rerank rows", value: `${rerankRows.length}`, detail: "pointwise lane rerank decisions captured" } : null,
    pairwiseSummary.length ? { label: "Pairwise comparisons", value: pairwiseSummary.find((item) => item.label.includes("completed"))?.value ?? "captured", detail: "top-k pairwise refinement across lane pools" } : null,
    rerankRows.length ? { label: "Off topic", value: `${rerankRows.filter((row) => Boolean(asRecord(row.rerank).off_topic)).length}`, detail: "rows explicitly rejected as off topic", tone: "warn" } : null,
    rerankRows.length ? { label: "Insufficient info", value: `${rerankRows.filter((row) => Boolean(asRecord(row.rerank).insufficient_info)).length}`, detail: "rows where evidence was too thin for the model" } : null,
  ]);

  const rerankRowsMapped = rerankRows
    .map((row) => candidateMap.get(asString(row.id)))
    .filter((row): row is MutableCandidate => Boolean(row))
    .map(candidateRowFromMutable);

  const rerank: RunDetail["rerank"] = {
    metrics: rerankMetrics,
    laneRankings: Object.entries(stageIRankings).map(([sectionId, ids]) => ({
      id: `stagei:${sectionId}`,
      label: `${sectionId.replace(":", " / ")}`,
      subtitle: "post-rerank lane ordering",
      rows: ids
        .map((id) => candidateMap.get(id))
        .filter((row): row is MutableCandidate => Boolean(row))
        .slice(0, TOP_LIMIT)
        .map(candidateRowFromMutable),
    })),
    highSignal: sortByScore(rerankRowsMapped, (row) => Math.max(row.rerankMatch ?? -1, row.rerankAuthority ?? -1)).slice(0, 16),
    offTopic: rerankRows
      .filter((row) => Boolean(asRecord(row.rerank).off_topic))
      .map((row) => candidateMap.get(asString(row.id)))
      .filter((row): row is MutableCandidate => Boolean(row))
      .slice(0, 16)
      .map(candidateRowFromMutable),
    insufficient: rerankRows
      .filter((row) => Boolean(asRecord(row.rerank).insufficient_info))
      .map((row) => candidateMap.get(asString(row.id)))
      .filter((row): row is MutableCandidate => Boolean(row))
      .slice(0, 16)
      .map(candidateRowFromMutable),
    pairwiseSummary,
    pairwiseDecisions: pairwiseDecisions.slice(0, 24),
  };

  const comparisonBasis: RunDetail["comparisonBasis"] = {
    queryStrings: [],
    zeroHitQueries: [],
    topIdsBySection: {
      ...topIdsBySection,
      ...Object.fromEntries(Object.entries(stageIRankings).map(([key, ids]) => [`stagei:${key}`, ids.slice(0, TOP_LIMIT)])),
    },
  };

  return {
    candidateCatalog: allRowsSorted.slice(0, CATALOG_LIMIT),
    funnel,
    poolSummary,
    providerMix,
    idCoverage,
    topCited,
    mergedCandidates,
    noAnchorTopCited,
    econHitCandidates,
    weakestMetadata,
    scoring,
    coverage,
    rerank,
    final: {
      outputs: outputTopSections,
    },
    comparisonBasis,
  };
}

function buildHeaderStats(run: RunListEntry): OverviewMetric[] {
  return [
    {
      label: "Tracked artifacts",
      value: `${(run.totalBytes / (1024 * 1024)).toFixed(1)} MB`,
      detail: `${run.fileCount} top-level files in the run folder`,
    },
    {
      label: "Total cost",
      value: `$${run.totalCostUsd.toFixed(3)}`,
      detail: "summed from stage OpenAI metadata",
    },
    {
      label: "Duration",
      value: `${run.durationSeconds.toFixed(1)} s`,
      detail: `${run.statusLabel} pipeline state`,
    },
    {
      label: "Candidate pool",
      value: `${run.counts.candidates}`,
      detail: `${run.counts.finalScored} final-scored and ${run.counts.rerank} reranked`,
    },
  ];
}

function buildTimeline(metrics: Record<string, unknown>, phaseCards: PhaseCard[]): RunDetail["overview"]["timeline"] {
  const stages = asRecord(metrics.stages);
  return TIMELINE_ORDER.map(([key, label]) => {
    const stage = asRecord(stages[key]);
    const correspondingCard = phaseCards.find((card) => {
      if (key.startsWith("phase_b")) return card.key === "plan";
      if (key.startsWith("phase_c")) return card.key === "queries";
      if (key.startsWith("phase_d")) return card.key === "retrieval";
      if (key.startsWith("phase_e")) return card.key === "candidates";
      if (key.startsWith("phase_f")) return card.key === "scoring";
      if (key.startsWith("phase_g") || key.startsWith("phase_h")) return card.key === "coverage";
      if (key.startsWith("phase_i")) return card.key === "rerank";
      if (key.startsWith("phase_k")) return card.key === "final";
      return false;
    });
    return {
      key,
      label,
      status: correspondingCard?.status ?? "missing",
      seconds: asNullableNumber(stage.last_duration_s),
      note:
        trimText(
          asString(asRecord(stage.openai).model_used) ||
            asString(asRecord(stage.openai).model_requested) ||
            correspondingCard?.blurb ||
            "",
          64,
        ) || correspondingCard?.blurb || "",
    };
  });
}

function buildArtifacts(topFiles: Set<string>): RunDetail["overview"]["artifacts"] {
  const definitions = [
    ["Planner output", "query_plan.json", "planner schema and facet design"],
    ["OpenAlex queries", "openalex_queries.json", "retrieval query set for OpenAlex"],
    ["Semantic Scholar queries", "semanticscholar_queries.json", "bulk query set for S2"],
    ["Normalized candidates", "candidates_normalized.jsonl", "deduped candidate pool"],
    ["Scoring debug", "phase_f_scoring_debug.jsonl", "candidate-level score diagnostics"],
    ["MMR debug", "phase_f_mmr_debug.json", "before / after shortlist swaps"],
    ["Coverage tags", "coverage_tags.jsonl", "facet coverage snippets"],
    ["Rerank decisions", "rerank_results.jsonl", "pointwise lane rerank cache"],
    ["Final output", "output.json", "merged final top lists"],
  ] as const;

  return definitions.map(([label, fileName, detail]) => ({
    label,
    status: topFiles.has(fileName) ? "complete" : "missing",
    detail,
  }));
}

const STAGE_COST_LABELS: Array<[string, string]> = [
  ["phase_b_query_planner", "B Plan"],
  ["phase_c_openalex_query_builder", "C OpenAlex queries"],
  ["phase_c_s2_query_builder", "C S2 queries"],
  ["phase_d_retrieval", "D Retrieval"],
  ["phase_e_candidates", "E Candidates"],
  ["phase_f", "F Scoring + embeddings"],
  ["phase_g", "G Shortlists"],
  ["phase_h_coverage_tags", "H Coverage"],
  ["phase_i_rerank", "I Rerank"],
  ["phase_k_output", "K Output"],
];

function buildStageCostRows(metrics: Record<string, unknown>, output: Record<string, unknown>): StageCostRow[] {
  const stages = asRecord(metrics.stages);
  const cacheStatusMap = asRecord(asRecord(asRecord(output.run_costs).cache_status));

  return STAGE_COST_LABELS.map(([stageName, label]) => {
    const stage = asRecord(stages[stageName]);
    const openai = asRecord(stage.openai);
    const usage = asRecord(openai.usage);
    const costEstimate = asRecord(openai.cost_estimate);
    const counts = asRecord(stage.counts);
    let model = "";
    let costRunUsd = 0;
    let costArtifactsUsd = 0;
    let tokensInRun = 0;
    let tokensOutRun = 0;
    let tokensInArtifacts = 0;
    let tokensOutArtifacts = 0;
    let info = "";

    if (Object.keys(openai).length > 0) {
      model = asString(openai.model_used) || asString(openai.model_requested);
      costArtifactsUsd = asNumber(costEstimate.total_cost_usd);
      const cacheStatus = asString(cacheStatusMap[stageName]);
      costRunUsd = cacheStatus === "hit" ? 0 : costArtifactsUsd;
      tokensInArtifacts = asNumber(usage.input_tokens) + asNumber(usage.cached_input_tokens);
      tokensOutArtifacts = asNumber(usage.output_tokens);
      tokensInRun = cacheStatus === "hit" ? 0 : tokensInArtifacts;
      tokensOutRun = cacheStatus === "hit" ? 0 : tokensOutArtifacts;
    } else if (stageName === "phase_i_rerank") {
      model = asString(counts.model_used) || asString(counts.model);
      costRunUsd = asNumber(counts.cost_usd_new) || asNumber(counts.cost_usd_est_new);
      costArtifactsUsd = asNumber(counts.cost_usd_total) || asNumber(counts.cost_usd_est_total);
      tokensInRun = asNumber(counts.tokens_in_new) + asNumber(counts.tokens_cached_in_new);
      tokensOutRun = asNumber(counts.tokens_out_new);
      tokensInArtifacts = asNumber(counts.tokens_in_total) + asNumber(counts.tokens_cached_in_total);
      tokensOutArtifacts = asNumber(counts.tokens_out_total);
      info = `tasks=${asNumber(counts.tasks_total)} cache=${asNumber(counts.cache_hits)} api=${asNumber(counts.api_calls)} fail=${asNumber(counts.failures)}`;
    } else if (stageName === "phase_f") {
      const embeddingsTotal = asRecord(stage.embeddings_total);
      const embeddings = asRecord(stage.embeddings);
      model =
        asString(asRecord(embeddings.meta).model) ||
        asString(asRecord(embeddings.facet).model) ||
        asString(asRecord(embeddings.chunk).model);
      costRunUsd = asNumber(embeddingsTotal.cost_usd) || asNumber(embeddingsTotal.cost_usd_est);
      costArtifactsUsd = costRunUsd;
      tokensInRun = asNumber(embeddingsTotal.prompt_tokens);
      tokensInArtifacts = tokensInRun;
      const hygiene = asRecord(counts.hygiene);
      info = `stage2=${asNumber(counts.stage2_candidates)} noabs_keep=${asNumber(hygiene.noabs_keep_effective)} mmr=${Boolean(hygiene.mmr_enabled) ? "on" : "off"}`;
    } else if (stageName === "phase_d_retrieval") {
      info = `oa=${asNumber(asRecord(stage.openalex).records)} s2=${asNumber(asRecord(stage.semanticscholar).records)}`;
    } else if (stageName === "phase_e_candidates") {
      const poolCounts = asRecord(counts.pool_counts);
      info = `deduped=${asNumber(counts.deduped_candidates)} merges=${asNumber(counts.merges)} with_abs=${asNumber(poolCounts.with_abstract)} noabs=${asNumber(poolCounts.without_abstract)}`;
    } else if (stageName === "phase_g") {
      info = `shortlist=${asNumber(counts.shortlist_unique_ids)} stage2=${asNumber(counts.stage2_available)}`;
    } else if (stageName === "phase_h_coverage_tags") {
      info = `rows=${asNumber(counts.records_scored_final)} tags=${asNumber(counts.coverage_tags_total)}`;
    } else if (stageName === "phase_k_output") {
      info = `top_n=${asNumber(counts.top_n)} rerank=${asNumber(counts.rerank_rows_loaded)}`;
    }

    return {
      stage: stageName,
      label,
      durationSeconds: asNullableNumber(stage.last_duration_s),
      cacheStatus: asString(cacheStatusMap[stageName]),
      model,
      costRunUsd,
      costArtifactsUsd,
      tokensInRun,
      tokensOutRun,
      tokensInArtifacts,
      tokensOutArtifacts,
      info,
    };
  }).filter((row) => {
    return (
      row.durationSeconds !== null ||
      row.costRunUsd > 0 ||
      row.costArtifactsUsd > 0 ||
      row.tokensInArtifacts > 0 ||
      row.tokensOutArtifacts > 0 ||
      row.info
    );
  });
}

function buildOverviewMetrics(run: RunListEntry): OverviewMetric[] {
  return [
    { label: "OpenAlex rows", value: `${run.counts.openAlex}`, detail: "retrieved raw rows written to cache" },
    { label: "Semantic Scholar rows", value: `${run.counts.semanticScholar}`, detail: "bulk search and recommendations combined" },
    { label: "Candidates", value: `${run.counts.candidates}`, detail: "deduped candidates after normalization" },
    { label: "Stage 2 shortlist", value: `${run.counts.stage2}`, detail: "chunk expansion shortlist entering final scoring" },
    { label: "Final scored rows", value: `${run.counts.finalScored}`, detail: "rows available for stage G onward" },
    { label: "Rerank rows", value: `${run.counts.rerank}`, detail: "pointwise rerank tasks completed or cached" },
  ];
}

async function buildRunDetail(run: RunListEntry): Promise<RunDetail> {
  const runDir = path.resolve(process.cwd(), RUNS_DIR, run.id);
  const stat = await fs.stat(runDir);
  const cacheKey = `${stat.mtimeMs}:${run.id}`;
  const cached = runDetailCache.get(run.id);
  if (cached && cached.key === cacheKey) {
    return cached.data;
  }

  const diskCached = await readRunCache<RunDetail>(run.id, "detail", cacheKey);
  if (diskCached) {
    runDetailCache.set(run.id, { key: cacheKey, data: diskCached });
    return diskCached;
  }

  const [metrics, queryPlan, output, topEntries, notableEvents, plannerPrompts, openAlexPrompts, s2Prompts] = await Promise.all([
    readJsonFile<Record<string, unknown>>(path.join(runDir, "metrics.json")),
    readJsonFile<Record<string, unknown>>(path.join(runDir, "query_plan.json")),
    readJsonFile<Record<string, unknown>>(path.join(runDir, "output.json")),
    fs.readdir(runDir, { withFileTypes: true }),
    readNotableEvents(runDir),
    buildPromptGroup(runDir, "query_plan", "query-plan", "Planner traces", "prompt, response, and output text from the query planner"),
    buildPromptGroup(runDir, "openalex_queries", "openalex-builder", "OpenAlex builder traces", "query builder attempts and outputs for OpenAlex"),
    buildPromptGroup(runDir, "s2_bulk_queries", "s2-builder", "Semantic Scholar builder traces", "bulk query builder attempts and outputs for Semantic Scholar"),
  ]);

  const queryPlanRecord = queryPlan ?? {};
  const anchorTerms = unique([
    ...asStringArray(asRecord(queryPlanRecord.primary_context_anchors).en),
    ...asStringArray(asRecord(queryPlanRecord.primary_context_anchors).de),
  ]);
  const econTerms = unique([
    ...asStringArray(asRecord(queryPlanRecord.core_object_terms).en),
    ...asStringArray(asRecord(queryPlanRecord.core_object_terms).de),
    ...asStringArray(asRecord(queryPlanRecord.global_canonical_terms).en),
    ...asStringArray(asRecord(queryPlanRecord.global_canonical_terms).de),
  ]).slice(0, 40);
  const requiredFacetIds = asArray<Record<string, unknown>>(queryPlanRecord.facets)
    .filter((facet) => asNumber(facet.importance_weight) >= 4)
    .map((facet) => asString(facet.facet_id))
    .filter(Boolean);

  const [queryData, candidateData] = await Promise.all([
    buildQueryAndRetrievalData(runDir, anchorTerms),
    buildCandidateData(runDir, {
      requiredFacetIds,
      anchorTerms,
      econTerms,
    }),
  ]);
  const topFiles = new Set(topEntries.filter((entry) => entry.isFile()).map((entry) => entry.name));

  const detail: RunDetail = {
    id: run.id,
    chapterTitle: run.chapterTitle,
    topicSummary: run.topicSummary,
    statusLabel: run.statusLabel,
    modifiedAt: run.modifiedAt,
    headerStats: buildHeaderStats(run),
    phaseCards: run.phaseCards,
    overview: {
      metrics: buildOverviewMetrics(run),
      stageCosts: buildStageCostRows(metrics ?? {}, output ?? {}),
      timeline: buildTimeline(metrics ?? {}, run.phaseCards),
      artifacts: buildArtifacts(topFiles),
      notableEvents,
    },
    plan: {
      summaryEn: asString(queryPlanRecord.topic_summary_en),
      summaryDe: asString(queryPlanRecord.topic_summary_de),
      anchorsEn: asStringArray(asRecord(queryPlanRecord.primary_context_anchors).en),
      anchorsDe: asStringArray(asRecord(queryPlanRecord.primary_context_anchors).de),
      coreTermsEn: asStringArray(asRecord(queryPlanRecord.core_object_terms).en),
      coreTermsDe: asStringArray(asRecord(queryPlanRecord.core_object_terms).de),
      canonicalTermsEn: asStringArray(asRecord(queryPlanRecord.global_canonical_terms).en),
      canonicalTermsDe: asStringArray(asRecord(queryPlanRecord.global_canonical_terms).de),
      exclusionsEn: asStringArray(asRecord(queryPlanRecord.global_exclusions).en),
      exclusionsDe: asStringArray(asRecord(queryPlanRecord.global_exclusions).de),
      constraints: asStringArray(queryPlanRecord.must_keep_constraints),
      driftRisks: asStringArray(queryPlanRecord.drift_risks),
      facets: asArray<Record<string, unknown>>(queryPlanRecord.facets).map((facet) => ({
        id: asString(facet.facet_id),
        label: asString(facet.facet_label_en),
        labelDe: asString(facet.facet_label_de),
        type: asString(facet.facet_type),
        group: asString(facet.facet_group),
        importanceWeight: asNumber(facet.importance_weight),
        authorityRole: asString(facet.authority_role),
        queryFamilyPreference: asString(facet.query_family_preference),
        languageStrategy: asString(facet.language_strategy),
        summary: asString(facet.text_en),
        canonicalTerms: asStringArray(asRecord(facet.canonical_terms).en).slice(0, 8),
        canonicalTermsDe: asStringArray(asRecord(facet.canonical_terms).de).slice(0, 8),
        neighborTerms: asStringArray(asRecord(facet.neighbor_terms).en).slice(0, 6),
        exclusions: asStringArray(asRecord(facet.exclusion_terms).en).slice(0, 6),
      })),
      blueprints: asArray<Record<string, unknown>>(queryPlanRecord.authority_blueprints).map((blueprint) => ({
        kind: asString(blueprint.authority_kind),
        label: asString(blueprint.label_en),
        labelDe: asString(blueprint.label_de),
        searchBreadth: asString(blueprint.search_breadth),
        languageStrategy: asString(blueprint.language_strategy),
        targets: asStringArray(blueprint.target_facet_ids),
        notes: asString(blueprint.notes_en),
      })),
      promptGroups: compact([plannerPrompts]),
    },
    queries: {
      providers: queryData.queryProviders,
      promptGroups: compact([openAlexPrompts, s2Prompts]),
    },
    retrieval: {
      providers: queryData.retrievalProviders,
      decadeBuckets: queryData.decadeBuckets,
      topQueries: queryData.topQueries,
      zeroHitQueries: queryData.zeroHitQueries,
    },
    candidates: {
      funnel: candidateData.funnel,
      poolSummary: candidateData.poolSummary,
      providerMix: candidateData.providerMix,
      idCoverage: candidateData.idCoverage,
      topCited: candidateData.topCited,
      mergedCandidates: candidateData.mergedCandidates,
      noAnchorTopCited: candidateData.noAnchorTopCited,
      econHitCandidates: candidateData.econHitCandidates,
      weakestMetadata: candidateData.weakestMetadata,
      catalog: candidateData.candidateCatalog,
    },
    scoring: candidateData.scoring,
    coverage: candidateData.coverage,
    rerank: candidateData.rerank,
    final: candidateData.final,
    comparisonBasis: {
      ...candidateData.comparisonBasis,
      queryStrings: queryData.queryProviders.flatMap((provider) => provider.rows.map((row) => row.queryText)),
      zeroHitQueries: queryData.zeroHitQueries.map((row) => row.queryText),
    },
  };

  runDetailCache.set(run.id, { key: cacheKey, data: detail });
  await writeRunCache(run.id, "detail", cacheKey, detail);
  return detail;
}

function findCandidateRow(detail: RunDetail, id: string): CandidateRow | null {
  const pools = [
    detail.candidates.catalog,
    detail.candidates.topCited,
    detail.candidates.mergedCandidates,
    detail.candidates.noAnchorTopCited,
    detail.candidates.econHitCandidates,
    detail.candidates.weakestMetadata,
    ...detail.scoring.stage1.map((section) => section.rows),
    ...detail.scoring.stage2.map((section) => section.rows),
    ...detail.scoring.final.map((section) => section.rows),
    ...detail.coverage.stageGRankings.map((section) => section.rows),
    detail.coverage.coverageRich,
    ...detail.rerank.laneRankings.map((section) => section.rows),
    detail.rerank.highSignal,
    detail.rerank.offTopic,
    detail.rerank.insufficient,
    ...detail.final.outputs.map((section) => section.rows),
  ];

  for (const rows of pools) {
    const match = rows.find((row) => row.id === id);
    if (match) {
      return match;
    }
  }
  return null;
}

function titleForComparison(detail: RunDetail, id: string): string {
  return findCandidateRow(detail, id)?.title || id;
}

function buildComparison(selected: RunDetail, compare: RunDetail, compareRun: RunListEntry): RunComparison {
  const selectedQuerySet = new Set(selected.comparisonBasis.queryStrings);
  const compareQuerySet = new Set(compare.comparisonBasis.queryStrings);
  const sharedQueries = [...selectedQuerySet].filter((query) => compareQuerySet.has(query)).length;
  const selectedOnlyQueries = [...selectedQuerySet].filter((query) => !compareQuerySet.has(query)).length;
  const compareOnlyQueries = [...compareQuerySet].filter((query) => !selectedQuerySet.has(query)).length;

  const overlaps: ComparisonOverlap[] = unique([
    ...Object.keys(selected.comparisonBasis.topIdsBySection),
    ...Object.keys(compare.comparisonBasis.topIdsBySection),
  ]).map((sectionId) => {
    const selectedIds = selected.comparisonBasis.topIdsBySection[sectionId] ?? [];
    const compareIds = compare.comparisonBasis.topIdsBySection[sectionId] ?? [];
    const shared = selectedIds.filter((id) => compareIds.includes(id));
    const sharedShifts = shared
      .map((id) => ({
        id,
        title: titleForComparison(selected, id) || titleForComparison(compare, id),
        selectedRank: selectedIds.indexOf(id) + 1,
        compareRank: compareIds.indexOf(id) + 1,
        delta: (compareIds.indexOf(id) + 1) - (selectedIds.indexOf(id) + 1),
      }))
      .sort((left, right) => Math.abs(right.delta) - Math.abs(left.delta))
      .slice(0, 6);

    const onlySelected = selectedIds
      .filter((id) => !compareIds.includes(id))
      .slice(0, 6)
      .map((id) => findCandidateRow(selected, id))
      .filter((row): row is CandidateRow => Boolean(row));

    const onlyCompare = compareIds
      .filter((id) => !selectedIds.includes(id))
      .slice(0, 6)
      .map((id) => findCandidateRow(compare, id))
      .filter((row): row is CandidateRow => Boolean(row));

    return {
      id: sectionId,
      label: sectionId.replace(/:/g, " / "),
      overlapCount: shared.length,
      sharedShifts,
      onlySelected,
      onlyCompare,
    };
  });

  return {
    compareRun,
    metrics: [
      { label: "Shared queries", value: `${sharedQueries}`, detail: `${selectedOnlyQueries} only in selected, ${compareOnlyQueries} only in compare` },
      { label: "Zero-hit delta", value: `${selected.comparisonBasis.zeroHitQueries.length - compare.comparisonBasis.zeroHitQueries.length}`, detail: `${selected.comparisonBasis.zeroHitQueries.length} vs ${compare.comparisonBasis.zeroHitQueries.length}` },
      { label: "Candidate pool delta", value: `${selected.candidates.catalog.length - compare.candidates.catalog.length}`, detail: `${selected.candidates.catalog.length} vs ${compare.candidates.catalog.length}` },
      { label: "Final output sections", value: `${selected.final.outputs.length}`, detail: `compared against ${compare.final.outputs.length} output sections` },
    ],
    queryDiffs: [
      { label: "Shared queries", value: `${sharedQueries}` },
      { label: "Selected-only queries", value: `${selectedOnlyQueries}` },
      { label: "Compare-only queries", value: `${compareOnlyQueries}` },
      { label: "Selected zero-hit queries", value: `${selected.comparisonBasis.zeroHitQueries.length}` },
      { label: "Compare zero-hit queries", value: `${compare.comparisonBasis.zeroHitQueries.length}` },
    ],
    overlaps,
  };
}

function getDefaultSelectedRunId(runs: RunListEntry[]): string | null {
  if (!runs.length) {
    return null;
  }
  return [...runs]
    .sort((left, right) => {
      if (right.completenessScore !== left.completenessScore) {
        return right.completenessScore - left.completenessScore;
      }
      return safeDate(right.modifiedAt) - safeDate(left.modifiedAt);
    })[0]?.id ?? null;
}

export async function getDashboardPayload(selectedRunId?: string | null, compareRunId?: string | null): Promise<DashboardPayload> {
  const runIds = await getRunDirectories();
  const runs = compact(await Promise.all(runIds.map((runId) => buildRunIndexEntry(runId)))).sort((left, right) => {
    if (right.completenessScore !== left.completenessScore) {
      return right.completenessScore - left.completenessScore;
    }
    return safeDate(right.modifiedAt) - safeDate(left.modifiedAt);
  });

  const selectedId = runs.some((run) => run.id === selectedRunId) ? selectedRunId ?? null : getDefaultSelectedRunId(runs);
  const compareId = compareRunId && compareRunId !== selectedId && runs.some((run) => run.id === compareRunId) ? compareRunId : null;

  const selectedRunEntry = runs.find((run) => run.id === selectedId) ?? null;
  const compareRunEntry = runs.find((run) => run.id === compareId) ?? null;

  const [selectedRun, compareRun] = await Promise.all([
    selectedRunEntry ? buildRunDetail(selectedRunEntry) : Promise.resolve(null),
    compareRunEntry ? buildRunDetail(compareRunEntry) : Promise.resolve(null),
  ]);

  return {
    runs,
    selectedRunId: selectedRunEntry?.id ?? null,
    compareRunId: compareRunEntry?.id ?? null,
    selectedRun,
    compareRun,
    comparison: selectedRun && compareRun && compareRunEntry ? buildComparison(selectedRun, compareRun, compareRunEntry) : null,
  };
}
