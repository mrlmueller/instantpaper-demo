// UI Type Definitions
// These types bridge the new design expectations with Firebase data structures

export interface Projekt {
  id: string;
  name: string;
  createdAt: Date;
}

export interface Quelle {
  id: string;
  name: string; // Maps to Firebase 'title' field
  text: string; // Maps to Firebase 'content' field
  projektId: string;
  createdAt: Date;
}

export interface Kapitel {
  id: string;
  title: string;
  nummer: string; // e.g., "1", "1.1", "1.1.1" - hierarchical chapter number
  status: "nicht-verarbeitet" | "in-bearbeitung" | "fertig";
  order: number;
  projektId: string;
  assignedQuellenIds: string[]; // Maps to Firebase 'quelleIds'
}

export interface QuellenErgebnis {
  id: string;
  quelleId: string;
  quelleName: string;
  text: string;
  status: "waiting" | "success" | "no-content";
  cost: number; // Cost in cents (EUR) - Firebase stores in dollars (USD)
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
  cost: number; // Cost in cents (EUR)
  createdAt: Date;
}

export interface Run {
  id: string;
  index?: number;
  kapitelId: string;
  timestamp: Date;
  status: "success" | "error" | "running";
  model: string;
  ueberschrift: string; // Heading for the chapter
  thema: string; // Topic/instruction for processing
  combinedText: string;
  quellenErgebnisse: QuellenErgebnis[];
  quellenCost: number; // Cost for per-source processing in cents
  combinedCost: number; // Cost for combining in cents
  intermediateGroups?: IntermediateGroup[]; // Optional array of intermediate groups
  shortenedText?: string | null; // Shortened and deduplicated text
  shortenedCost?: number; // Cost for shortening in cents
}

export interface ProcessingSettings {
  model: "gpt-5-nano" | "gpt-5-mini" | "gpt-5.1"; // Real model names (not mock)
  ueberschrift: string; // Heading
  thema: string; // Topic/instruction
  grundlegendeInfos: string; // Basic/contextual information
  directCombine: boolean; // Maps to Firebase 'autoCombine'
}

// User and stats types for profile page (currently using mock data)
export interface UserStats {
  totalCost: number; // in cents
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
