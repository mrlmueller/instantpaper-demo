export type GliederungDraftStatus = 'running' | 'success' | 'error';

export type GliederungStudienbriefLabel = 'Hauptquelle' | 'Ergänzend' | 'Nur knapp';

export interface GliederungStudienbriefKapitelRef {
  nummer: string;
  titel: string;
  label: GliederungStudienbriefLabel;
}

export interface GliederungDraftKapitel {
  id: string;
  reviewed: boolean;
  nummer: string;
  titel: string;
  beschreibung: string;
  seitenumfang: string;
  relevanteStudienbriefKapitel: GliederungStudienbriefKapitelRef[];
  externeQuellenErforderlich: boolean;
}

export interface GliederungDraftOutput {
  kapitel: GliederungDraftKapitel[];
  kurzbegruendung: string[];
  verwendeteStudienbriefKapitelUnique: Array<{ nummer: string; titel: string }>;
  annahmen: string[];
}

export interface GliederungDraftInputs {
  aufgabenstellung: string;
  gliederungStudienbriefMitSeiten: string;
  extraKontext: string;
}

export type GliederungDraftUsage = Partial<{
  inputTokens: number;
  cachedInputTokens: number;
  outputTokens: number;
  reasoningTokens: number;
  totalTokens: number;
}>;

export interface GliederungDraft {
  id: string;
  projektId: string;
  status: GliederungDraftStatus;
  errorMessage?: string | null;
  model: 'gpt-5-nano' | 'gpt-5-mini' | 'gpt-5.2' | string;
  promptTemplateId: string;
  inputs: GliederungDraftInputs;
  output?: GliederungDraftOutput | null;
  usage?: GliederungDraftUsage | null;
  costUsd?: number | null;
  operationId?: string | null;
  keySource?: string | null;
  appliedAt?: Date | null;
  appliedKapitelIds?: string[] | null;
  createdAt: Date;
  updatedAt: Date;
  archived: boolean;
  archivedAt?: Date | null;
}
