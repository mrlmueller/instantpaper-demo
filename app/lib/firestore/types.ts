import type { Timestamp } from 'firebase/firestore';

export type ArchiveFields = {
  archived: boolean;
  archivedAt?: Timestamp | null;
};

export type LatestRun = {
  runId: string;
  index: number;
  status: 'none' | 'running' | 'done';
  updatedAt: Timestamp;
};

export type Usage = {
  inputTokens: number;
  cachedInputTokens: number;
  outputTokens: number;
  reasoningTokens: number;
  totalTokens: number;
};

export type RefinementMeta = {
  rootVersionId: 'root';
  activeVersionId: string;
  maxDepth: number;
  costTotalUsd: number;
  initializedAt: Timestamp;
  selectedAt?: Timestamp | null;
};

export type ProjectDoc = ArchiveFields & {
  name: string;
  ownerId: string;
  createdAt: Timestamp;
  updatedAt: Timestamp;
};

export type QuelleImageMetadata = {
  url: string;
  path: string;
  filename: string;
  size: number;
  contentType: string;
  widthPx?: number;
  heightPx?: number;
};

export type QuelleDoc = ArchiveFields & {
  projektId: string;
  title: string;
  createdAt: Timestamp;
  updatedAt: Timestamp;
  wordCount?: number;
  images?: QuelleImageMetadata[];
  autor?: string;
  jahr?: number;
  typ?: 'Book' | 'Article' | 'Website' | 'Thesis' | 'Report';
  url?: string;
  zugriffAm?: string;
  zitat?: string;
  zitatModus?: 'auto' | 'authorYear' | 'full' | 'none';
  color?: 'blue' | 'green' | 'teal' | 'lavender' | 'cream' | 'peach' | 'rose';
};

export type QuelleContentDoc = {
  text: string;
  wordCount: number;
  createdAt: Timestamp;
  updatedAt: Timestamp;
};

export type KapitelDoc = ArchiveFields & {
  projektId: string;
  title: string;
  nummer: string;
  parentId: string | null;
  order: number;
  quelleIds: string[];
  createdAt: Timestamp;
  updatedAt: Timestamp;
  latestRun?: LatestRun;
  activeRunId?: string;
};

export type ArtifactsStatus = {
  combined: 'empty' | 'running' | 'success' | 'error';
  shortened: 'empty' | 'running' | 'success' | 'error';
  lesefluss: 'empty' | 'running' | 'success' | 'error';
};

export type RunDoc = ArchiveFields & {
  projektId: string;
  index: number;
  instruction: string;
  name?: string;
  model: string;
  createdAt: Timestamp;
  updatedAt: Timestamp;
  autoCombine: boolean;
  promptTemplateId?: string;
  promptPayload?: Record<string, unknown>;
  grundlegendeInformationen?: string | null;
  ueberschrift?: string;
  thema?: string;
  resultsExpectedCount?: number;
  resultsCompletedCount?: number;
  resultsWithContentCount?: number;
  lastResultAt?: Timestamp | null;
  artifactsStatus?: ArtifactsStatus;
  lastActivityAt?: Timestamp | null;
};

export type ResultDoc = {
  quelleId: string;
  userInput: string;
  content: string;
  hasContent: boolean;
  model: string;
  usage: Usage;
  costUsd: number;
  keySource: 'platform' | 'user';
  createdAt: Timestamp;
  updatedAt: Timestamp;
  refinement: RefinementMeta;
};

export type CombinedArtifactDoc = {
  artifactId: 'combined';
  content: string;
  heading: string;
  topic: string;
  sourceQuelleIds: string[];
  model: string;
  usage: Usage;
  costUsd: number;
  keySource: 'platform' | 'user';
  createdAt: Timestamp;
  updatedAt: Timestamp;
  refinement: RefinementMeta;
};

export type ShortenedArtifactDoc = {
  artifactId: 'shortened';
  content: string;
  usedKapitelIds: string[];
  originalLength: number;
  shortenedLength: number;
  compressionRatio?: number;
  model: string;
  usage: Usage;
  costUsd: number;
  keySource: 'platform' | 'user';
  createdAt: Timestamp;
  updatedAt: Timestamp;
  refinement: RefinementMeta;
};

export type LeseflussArtifactDoc = {
  artifactId: 'lesefluss';
  content: string;
  usedKapitelIds: string[];
  aufgabenstellung: string;
  leseflussLength: number;
  originalLength?: number;
  model: string;
  usage: Usage;
  costUsd: number;
  keySource: 'platform' | 'user';
  createdAt: Timestamp;
  updatedAt: Timestamp;
  refinement: RefinementMeta;
};

export type ArtifactDoc = CombinedArtifactDoc | ShortenedArtifactDoc | LeseflussArtifactDoc;

export type CombinedGroupDoc = {
  groupNumber: number;
  content: string;
  sourceQuelleIds: string[];
  heading: string;
  topic: string;
  model: string;
  usage: Usage;
  costUsd: number;
  keySource: 'platform' | 'user';
  createdAt: Timestamp;
  updatedAt: Timestamp;
};

export type SummaryDoc = {
  sourceKapitelId: string;
  sourceRunId: string;
  sourceType: 'combined' | 'shortened';
  content: string;
  originalLength: number;
  summaryLength: number;
  model: string;
  usage: Pick<Usage, 'inputTokens' | 'outputTokens' | 'totalTokens'>;
  costUsd: number;
  createdAt: Timestamp;
};

export type ProjectPdfDoc = {
  filename: string;
  storagePath: string;
  size: number;
  contentType: string;
  pageCount?: number | null;
  fileHash?: string | null;
  createdAt: Timestamp;
  updatedAt: Timestamp;
};

export type QuellenFinderRunKind = 'sources_two_lane' | 'pdf_scan';
export type QuellenFinderRunStatus = 'queued' | 'running' | 'success' | 'error' | 'cancelled';

export type QuellenFinderProgress = {
  stage: string;
  message?: string;
  current?: number;
  total?: number;
  stageStartedAt?: Timestamp | null;
};

export type KapitelSnapshot = {
  id: string;
  nummer?: string;
  title?: string;
  ueberschrift?: string;
  thema?: string;
};

export type QuellenFinderRunDoc = ArchiveFields & {
  kind: QuellenFinderRunKind;
  status: QuellenFinderRunStatus;
  projektId: string;
  kapitelIds: string[];
  pdfIds?: string[];
  kapitelSnapshots?: KapitelSnapshot[];
  model?: string;
  resultCount?: number;
  stage2Count?: number;
  stage3Count?: number;
  pdfScanDocCount?: number;
  pdfScanSectionCount?: number;
  usefulPdfCount?: number;
  finalScoreCol?: string;
  hadPartialFailures?: boolean;
  errorMessage?: string | null;
  progress?: QuellenFinderProgress;
  cancelRequestedAt?: Timestamp | null;
  cancelledAt?: Timestamp | null;
  twoLaneSettings?: Record<string, unknown>;
  summary?: Record<string, unknown>;
  createdAt: Timestamp;
  updatedAt: Timestamp;
  startedAt?: Timestamp | null;
  finishedAt?: Timestamp | null;
};

export type TwoLaneLane = 'match' | 'authority';
export type TwoLanePool = 'with_abstract' | 'without_abstract';

export type TwoLaneCoverageTag = {
  facet_id: string;
  score: number;
  excerpt: string;
};

export type TwoLaneRerank = {
  llm_score_0_100: number | null;
  covered_facets: string[];
  rationale: string | null;
  insufficient_info: boolean | null;
};

export type TwoLaneScores = {
  match: number | null;
  authority: number | null;
  match_lane: number | null;
  authority_lane: number | null;
  best?: number | null;
  top_m?: number | null;
  cov?: number | null;
};

export type TwoLaneResultDoc = {
  lane: TwoLaneLane;
  pool: TwoLanePool;
  rank: number;
  id: string;
  doi?: string | null;
  title: string | null;
  authors: string[];
  year: number | null;
  venue: string | null;
  url: string | null;
  language?: string | null;
  abstract: string | null;
  citations?: number | null;
  influential_citations?: number | null;
  provider?: string | null;
  provider_ids?: Record<string, unknown> | null;
  external_ids?: Record<string, unknown> | null;
  sources?: Record<string, unknown>[] | null;
  scores: TwoLaneScores;
  coverage_tags?: TwoLaneCoverageTag[] | null;
  rerank?: TwoLaneRerank | null;
  createdAt: Timestamp;
};

export type PdfScanPreviewSection = {
  sectionId?: string | null;
  title?: string | null;
  pageStart?: number | null;
  pageEnd?: number | null;
  score0To100?: number | null;
  scoreBand?: string | null;
};

export type PdfScanDocSummaryDoc = {
  pdfId: string;
  docId: string;
  pdfFilename?: string | null;
  pdfLabel: string;
  docTitle: string;
  pageCount?: number | null;
  sectionCount?: number | null;
  acceptedHeadingCount?: number | null;
  strategy?: string | null;
  doclingStatus?: string | null;
  hasOutline?: boolean | null;
  outlineCount?: number | null;
  qualityFlags?: string[] | null;
  hasUsefulInformation?: boolean | null;
  docMatchProbability?: number | null;
  topSectionScore?: number | null;
  topSectionTitle?: string | null;
  visibleSectionCount?: number | null;
  previewSections?: PdfScanPreviewSection[] | null;
  createdAt: Timestamp;
};

export type PdfScanResultDoc = {
  pdfId: string;
  docId: string;
  pdfFilename?: string | null;
  pdfLabel: string;
  docTitle: string;
  sectionId: string;
  title: string | null;
  sectionPath?: string[] | null;
  sectionPathText?: string | null;
  sectionType?: string | null;
  pageStart?: number | null;
  pageEnd?: number | null;
  score0To100?: number | null;
  scoreBand?: string | null;
  supportStrength?: number | null;
  supportingPassageCount?: number | null;
  subpointCoverageIds?: string[] | null;
  qualityFlags?: string[] | null;
  globalRank?: number | null;
  docRank?: number | null;
  anchorPage?: number | null;
  headingAnchor?: {
    page?: number | null;
    blockIndex?: number | null;
    absBlockIndex?: number | null;
    method?: string | null;
    confidence?: number | null;
  } | null;
  span?: {
    startAbsBlockIndex?: number | null;
    endAbsBlockIndex?: number | null;
    blockCount?: number | null;
  } | null;
  evidencePreview?: Array<{
    pageStart?: number | null;
    pageEnd?: number | null;
    lanes?: string[] | null;
    text?: string | null;
  }> | null;
  createdAt: Timestamp;
};
