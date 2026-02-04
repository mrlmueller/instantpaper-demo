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
  createdAt: Timestamp;
  updatedAt: Timestamp;
};

export type QuellenFinderRunKind = 'sources_search' | 'pdf_scan';
export type QuellenFinderRunStatus = 'queued' | 'running' | 'success' | 'error';

export type QuellenFinderProgress = {
  stage: string;
  message?: string;
  current?: number;
  total?: number;
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
  finalScoreCol?: string;
  hadPartialFailures?: boolean;
  errorMessage?: string | null;
  progress?: QuellenFinderProgress;
  createdAt: Timestamp;
  updatedAt: Timestamp;
  startedAt?: Timestamp | null;
  finishedAt?: Timestamp | null;
};

export type QuellenFinderSourceResultDoc = {
  // Curated fields (dev-friendly)
  title: string | null;
  authors: string[];
  year: number | null;
  venue: string | null;
  doi: string | null;
  url: string | null;
  abstract: string | null;
  citationCount: number | null;
  source: 'openalex' | 'semantic_scholar' | 'merged' | string;
  score: number | null;
  rank?: number;
  raw?: Record<string, unknown> | null;
  createdAt: Timestamp;
};

export type PdfScanStage2HitDoc = {
  pdfId: string;
  pdfLabel: string;
  pdfFileId?: string | null;
  subpoint?: string | null;
  tier?: string | null;
  score: number | null;
  anchor: string | null;
  anchorAlt: string | null;
  summary: string | null;
  locatorHint?: string | null;
  coverage?: string | null;
  scoreRationale?: string | null;
  evidenceSnippet?: string | null;
  subpointScores?: Record<string, number> | null;
  diagnostics?: Record<string, unknown>;
  createdAt: Timestamp;
};

export type PdfScanStage3SectionDoc = {
  pdfId: string;
  pdfLabel: string;
  pdfFileId?: string | null;
  anchor: string | null;
  anchorAlt: string | null;
  heading: string | null;
  headingMethod?: string | null;
  anchorPage?: number | null;
  hitCount?: number | null;
  summary?: string | null;
  coveredSubpoints?: string[] | null;
  score: number | null;
  diagnostics?: Record<string, unknown>;
  createdAt: Timestamp;
};
