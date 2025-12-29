// UI Type Definitions
// These types bridge the new design expectations with Firebase data structures

export interface Projekt {
  id: string;
  name: string;
  createdAt: Date;
  archived?: boolean;
}

export interface Quelle {
  id: string;
  name: string; // Maps to Firebase 'title' field
  text: string; // Maps to Firebase 'content' field
  wordCount?: number;
  projektId: string;
  createdAt: Date;
  images?: string[]; // Optional array of image URLs/data
  // Advanced metadata fields
  autor?: string;
  jahr?: number;
  typ?: 'Book' | 'Article' | 'Website' | 'Thesis' | 'Report';
  url?: string;
  zugriffAm?: string;
  color?: 'blue' | 'green' | 'teal' | 'lavender' | 'cream' | 'peach' | 'rose' | null;
}

export interface Kapitel {
  id: string;
  title: string;
  nummer: string; // e.g., "1", "1.1", "1.1.1" - hierarchical chapter number
  status: "nicht-verarbeitet" | "in-bearbeitung" | "fertig";
  order: number;
  projektId: string;
  assignedQuellenIds: string[]; // Maps to Firebase 'quelleIds'
  parentId?: string | null;
  activeRunId?: string;
}

export interface QuellenErgebnis {
  id: string;
  quelleId: string;
  quelleName: string;
  text: string;
  status: "waiting" | "success" | "no-content" | "error";
  cost: number; // Cost in cents (USD)
  costUsd?: number; // Cost in USD (high precision, for display/aggregation)
}

export interface IntermediateGroup {
  id: string;
  groupNumber: number;
  combinedContent: string;
  sourceQuelleIds: string[];
  sourceCount: number; // Convenience field = sourceQuelleIds.length
  heading: string;
  topic: string;
  modelUsed: string;
  tokensUsed: number;
  cost: number; // Cost in cents (USD)
  costUsd?: number; // Cost in USD (high precision, for display/aggregation)
  createdAt: Date;
}

export interface Run {
  id: string;
  index?: number;
  name?: string;
  kapitelId: string;
  timestamp: Date;
  status: "success" | "error" | "running";
  model: string;
  ueberschrift: string; // Heading for the chapter
  thema: string; // Topic/instruction for processing
  combinedText: string;
  quellenErgebnisse: QuellenErgebnis[];
  quellenCost: number; // Cost for per-source processing in cents
  quellenCostUsd?: number; // Cost for per-source processing in USD (high precision)
  combinedCost: number; // Cost for combining in cents
  combinedCostUsd?: number; // Cost for combining in USD (high precision)
  combinedStatus?: "empty" | "running" | "success" | "error";
  combinedRefinementCost?: number; // Total cost for combined text refinements (in cents)
  combinedRefinementCostUsd?: number; // Total cost for combined text refinements (USD, high precision)
  shortenedRefinementCost?: number; // Total cost for shortened text refinements (in cents)
  shortenedRefinementCostUsd?: number; // Total cost for shortened text refinements (USD, high precision)
  intermediateGroups?: IntermediateGroup[]; // Optional array of intermediate groups
  shortenedText?: string | null; // Shortened and deduplicated text
  shortenedCost?: number; // Cost for shortening in cents
  shortenedCostUsd?: number; // Cost for shortening in USD (high precision)
  shortenedStatus?: "empty" | "running" | "success" | "error";
  shortenedOriginalLength?: number; // Original word count before shortening
  shortenedLength?: number; // Word count after shortening
  leseflussText?: string | null;
  leseflussAufgabenstellung?: string;
  leseflussOriginalLength?: number;
  leseflussLength?: number;
  leseflussCost?: number;
  leseflussCostUsd?: number; // Cost for lesefluss in USD (high precision)
  leseflussStatus?: "empty" | "running" | "success" | "error";
  leseflussRefinementCost?: number; // Total cost for lesefluss text refinements (in cents)
  leseflussRefinementCostUsd?: number; // Total cost for lesefluss text refinements (USD, high precision)
}

export interface ProcessingSettings {
  model: "gpt-5-nano" | "gpt-5-mini" | "gpt-5.2"; // Real model names (not mock)
  ueberschrift: string; // Heading
  thema: string; // Topic/instruction
  grundlegendeInfos: string; // Basic/contextual information
  directCombine: boolean; // Maps to Firebase 'autoCombine'
  promptChoice?: Partial<Record<import("./prompts").PromptStage, string | "default">>; // Optional user-selected prompts
}

// User and stats types for profile page (currently using mock data)
export interface UserStats {
  totalCost: number; // in cents (USD)
  totalRuns: number;
  totalProjekte: number;
  totalKapitel: number;
  totalQuellen: number;
  totalWords: number;
  runsByMonth: { month: string; runs: number; cost: number }[];
  costByProjekt: { projektName: string; cost: number }[];
  modelUsage: { model: string; count: number }[];
  memberSince: Date;
}

export interface User {
  id: string;
  name: string;
  email: string;
  avatarUrl?: string;
  memberSince: Date;
}
