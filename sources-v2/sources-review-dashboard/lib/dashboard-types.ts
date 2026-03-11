export type DashboardTab =
  | "overview"
  | "plan"
  | "queries"
  | "retrieval"
  | "candidates"
  | "scoring"
  | "coverage"
  | "rerank"
  | "final"
  | "compare";

export type PhaseKey = "plan" | "queries" | "retrieval" | "candidates" | "scoring" | "coverage" | "rerank" | "final";
export type PhaseStatus = "complete" | "partial" | "missing";
export type Tone = "neutral" | "good" | "warn" | "danger";

export interface LabelValue {
  label: string;
  value: string;
  tone?: Tone;
  detail?: string;
}

export interface PhaseCard {
  key: PhaseKey;
  label: string;
  status: PhaseStatus;
  blurb: string;
  value: string;
}

export interface RunListEntry {
  id: string;
  chapterTitle: string;
  topicSummary: string;
  statusLabel: string;
  modifiedAt: string;
  fileCount: number;
  artifactCount: number;
  totalBytes: number;
  totalCostUsd: number;
  durationSeconds: number;
  completenessScore: number;
  focusTerms: string[];
  counts: {
    openAlex: number;
    semanticScholar: number;
    candidates: number;
    stage2: number;
    finalScored: number;
    rerank: number;
  };
  phaseCards: PhaseCard[];
}

export interface OverviewMetric {
  label: string;
  value: string;
  detail?: string;
  tone?: Tone;
}

export interface PromptTraceAttempt {
  id: string;
  label: string;
  model: string;
  latencySeconds: number | null;
  inputTokens: number;
  outputTokens: number;
  reasoningTokens: number;
  cachedInputTokens: number;
  costUsd: number;
  status: string;
  systemPrompt: string;
  userPrompt: string;
  outputText: string;
  errorNote: string;
}

export interface PromptTraceGroup {
  key: string;
  label: string;
  blurb: string;
  attempts: PromptTraceAttempt[];
}

export interface FacetCard {
  id: string;
  label: string;
  labelDe: string;
  type: string;
  group: string;
  importanceWeight: number;
  authorityRole: string;
  queryFamilyPreference: string;
  languageStrategy: string;
  summary: string;
  canonicalTerms: string[];
  canonicalTermsDe: string[];
  neighborTerms: string[];
  exclusions: string[];
}

export interface BlueprintCard {
  kind: string;
  label: string;
  labelDe: string;
  searchBreadth: string;
  languageStrategy: string;
  targets: string[];
  notes: string;
}

export interface QueryRow {
  id: string;
  provider: "openalex" | "semanticscholar";
  intent: string;
  language: string;
  searchField: string;
  queryText: string;
  filters: string;
  sort: string;
  note: string;
  hitCount: number;
  maxRank: number;
  sampleTitles: string[];
  sampleYears: number[];
}

export interface QueryProviderData {
  provider: "openalex" | "semanticscholar";
  label: string;
  queryCount: number;
  totalHits: number;
  zeroHitCount: number;
  duplicateQueryCount: number;
  anchorCoverageHits: number;
  anchorCoverageTotal: number;
  languages: string[];
  intents: string[];
  rows: QueryRow[];
}

export interface RetrievalProviderSummary {
  provider: "openalex" | "semanticscholar";
  label: string;
  totalHits: number;
  queryCount: number;
  zeroHitQueries: number;
  uniqueYears: number;
  strongestQuery: string;
  strongestHits: number;
}

export interface CandidateRow {
  id: string;
  title: string;
  doi: string;
  url: string;
  year: number | null;
  venue: string;
  pool: string;
  citations: number;
  influentialCitations: number;
  language: string;
  providers: string[];
  intents: string[];
  matchLane: number | null;
  authorityLane: number | null;
  semanticStage1: number | null;
  semanticStage2: number | null;
  rerankMatch: number | null;
  rerankAuthority: number | null;
  topFacets: string[];
  authorsLabel: string;
  abstractPreview: string;
  coverageExcerpt: string;
  rerankSummary: string;
  providerLabel: string;
  resourceUrl: string;
  sourceCount: number;
  tagCount: number;
  requiredFacetHits: number;
  hasAbstract: boolean;
  isCrossProvider: boolean;
  evidenceSnippets: string[];
  outputMatchRank: number | null;
  outputAuthorityRank: number | null;
}

export interface CandidateDetail extends CandidateRow {
  authors: string[];
  abstractText: string;
  evidenceSnippets: string[];
  sourceTraces: Array<{
    provider: string;
    queryIndex: number | null;
    intent: string;
    language: string;
    rank: number | null;
  }>;
  scores: Array<LabelValue>;
  coverageTags: Array<{
    label: string;
    score: number;
    excerpt: string;
  }>;
  rerankDecisions: Array<{
    lane: string;
    score: number | null;
    offTopic: boolean;
    insufficientInfo: boolean;
    briefRationale: string;
    rubric: Array<LabelValue>;
  }>;
  rankingPositions: Array<LabelValue>;
}

export interface LeaderboardSection {
  id: string;
  label: string;
  subtitle: string;
  metrics?: LabelValue[];
  rows: CandidateRow[];
}

export interface StageCostRow {
  stage: string;
  label: string;
  durationSeconds: number | null;
  cacheStatus: string;
  model: string;
  costRunUsd: number;
  costArtifactsUsd: number;
  tokensInRun: number;
  tokensOutRun: number;
  tokensInArtifacts: number;
  tokensOutArtifacts: number;
  info: string;
}

export interface FacetCoverageRow {
  facetId: string;
  label: string;
  hitCount: number;
  avgScore: number;
  sampleTitle: string;
}

export interface PairwiseDecision {
  lane: string;
  pool: string;
  leftId: string;
  rightId: string;
  winnerId: string;
  confidence: number | null;
  briefRationale: string;
  latencySeconds: number | null;
  costUsd: number;
}

export interface RunDetail {
  id: string;
  chapterTitle: string;
  topicSummary: string;
  statusLabel: string;
  modifiedAt: string;
  headerStats: OverviewMetric[];
  phaseCards: PhaseCard[];
  overview: {
    metrics: OverviewMetric[];
    stageCosts: StageCostRow[];
    timeline: Array<{
      key: string;
      label: string;
      status: PhaseStatus;
      seconds: number | null;
      note: string;
    }>;
    artifacts: Array<{
      label: string;
      status: PhaseStatus;
      detail: string;
    }>;
    notableEvents: Array<{
      ts: string;
      stage: string;
      label: string;
      detail: string;
    }>;
  };
  plan: {
    summaryEn: string;
    summaryDe: string;
    anchorsEn: string[];
    anchorsDe: string[];
    coreTermsEn: string[];
    coreTermsDe: string[];
    canonicalTermsEn: string[];
    canonicalTermsDe: string[];
    exclusionsEn: string[];
    exclusionsDe: string[];
    constraints: string[];
    driftRisks: string[];
    facets: FacetCard[];
    blueprints: BlueprintCard[];
    promptGroups: PromptTraceGroup[];
  };
  queries: {
    providers: QueryProviderData[];
    promptGroups: PromptTraceGroup[];
  };
  retrieval: {
    providers: RetrievalProviderSummary[];
    decadeBuckets: Array<{ decade: string; count: number }>;
    topQueries: QueryRow[];
    zeroHitQueries: QueryRow[];
  };
  candidates: {
    funnel: OverviewMetric[];
    poolSummary: Array<{ label: string; count: number; detail: string }>;
    providerMix: LabelValue[];
    idCoverage: LabelValue[];
    topCited: CandidateRow[];
    mergedCandidates: CandidateRow[];
    noAnchorTopCited: CandidateRow[];
    econHitCandidates: CandidateRow[];
    weakestMetadata: CandidateRow[];
    catalog: CandidateRow[];
  };
  scoring: {
    hygiene: LabelValue[];
    mmr: LabelValue[];
    stage1: LeaderboardSection[];
    stage2: LeaderboardSection[];
    final: LeaderboardSection[];
  };
  coverage: {
    facetCoverage: FacetCoverageRow[];
    requiredFacetSummary: LabelValue[];
    missingRequiredBySection: Array<{
      sectionId: string;
      label: string;
      missingCount: number;
      examples: string[];
    }>;
    stageGRankings: LeaderboardSection[];
    coverageRich: CandidateRow[];
  };
  rerank: {
    metrics: OverviewMetric[];
    laneRankings: LeaderboardSection[];
    highSignal: CandidateRow[];
    offTopic: CandidateRow[];
    insufficient: CandidateRow[];
    pairwiseSummary: LabelValue[];
    pairwiseDecisions: PairwiseDecision[];
  };
  final: {
    outputs: LeaderboardSection[];
  };
  comparisonBasis: {
    queryStrings: string[];
    zeroHitQueries: string[];
    topIdsBySection: Record<string, string[]>;
  };
}

export interface ComparisonOverlap {
  id: string;
  label: string;
  overlapCount: number;
  sharedShifts: Array<{
    id: string;
    title: string;
    selectedRank: number;
    compareRank: number;
    delta: number;
  }>;
  onlySelected: CandidateRow[];
  onlyCompare: CandidateRow[];
}

export interface RunComparison {
  compareRun: RunListEntry;
  metrics: OverviewMetric[];
  queryDiffs: LabelValue[];
  overlaps: ComparisonOverlap[];
}

export interface DashboardPayload {
  runs: RunListEntry[];
  selectedRunId: string | null;
  compareRunId: string | null;
  selectedRun: RunDetail | null;
  compareRun: RunDetail | null;
  comparison: RunComparison | null;
}
