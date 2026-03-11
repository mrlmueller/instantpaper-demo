import { createReadStream } from "node:fs";
import { promises as fs } from "node:fs";
import path from "node:path";
import { createInterface } from "node:readline";

import type { PhaseCard, PhaseStatus, RunListEntry, Tone } from "./dashboard-types";

export const RUNS_DIR = "../runs";
export const DASHBOARD_CACHE_DIR = ".dashboard-cache";
export const DASHBOARD_CACHE_VERSION = 2;
export const TOP_LIMIT = 20;
export const CATALOG_LIMIT = 180;

export const TIMELINE_ORDER = [
  ["phase_b_query_planner", "B Plan"],
  ["phase_c_openalex_query_builder", "C OA Queries"],
  ["phase_c_s2_query_builder", "C S2 Queries"],
  ["phase_d_retrieval", "D Retrieval"],
  ["phase_e_candidates", "E Candidates"],
  ["phase_f", "F Scoring"],
  ["phase_g", "G Shortlists"],
  ["phase_h_coverage_tags", "H Coverage"],
  ["phase_i_rerank", "I Rerank"],
  ["phase_k_output", "K Output"],
] as const;

interface DirectoryStatsCacheEntry {
  key: string;
  data: { fileCount: number; totalBytes: number };
}

export const directoryStatsCache = new Map<string, DirectoryStatsCacheEntry>();

export function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : {};
}

export function asArray<T = unknown>(value: unknown): T[] {
  return Array.isArray(value) ? (value as T[]) : [];
}

export function asString(value: unknown, fallback = ""): string {
  return typeof value === "string" ? value : fallback;
}

export function asNumber(value: unknown, fallback = 0): number {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

export function asNullableNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

export function asStringArray(value: unknown): string[] {
  return asArray(value)
    .map((item) => asString(item).trim())
    .filter(Boolean);
}

export function compact<T>(values: Array<T | null | undefined | false>): T[] {
  return values.filter(Boolean) as T[];
}

export function trimText(value: string, max = 360): string {
  const collapsed = value.replace(/\s+/g, " ").trim();
  if (!collapsed) {
    return "";
  }
  if (collapsed.length <= max) {
    return collapsed;
  }
  return `${collapsed.slice(0, max - 1).trimEnd()}…`;
}

export function round2(value: number | null): number | null {
  if (value === null || !Number.isFinite(value)) {
    return null;
  }
  return Math.round(value * 100) / 100;
}

export function scoreLabel(value: number | null): string {
  if (value === null || !Number.isFinite(value)) {
    return "—";
  }
  return value.toFixed(3);
}

export function unique<T>(values: T[]): T[] {
  return [...new Set(values)];
}

export function makeDoiUrl(doi: string): string {
  const normalized = doi.trim();
  return normalized ? `https://doi.org/${normalized}` : "";
}

export function bestResourceUrl(url: string, doi: string): string {
  return url.trim() || makeDoiUrl(doi);
}

export function statusTone(status: PhaseStatus): Tone {
  if (status === "complete") {
    return "good";
  }
  if (status === "partial") {
    return "warn";
  }
  return "neutral";
}

export function safeDate(value: string): number {
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

export async function fileExists(filePath: string): Promise<boolean> {
  try {
    const stat = await fs.stat(filePath);
    return stat.isFile();
  } catch {
    return false;
  }
}

export async function readJsonFile<T>(filePath: string): Promise<T | null> {
  try {
    const content = await fs.readFile(filePath, "utf8");
    if (!content.trim()) {
      return null;
    }
    return JSON.parse(content) as T;
  } catch {
    return null;
  }
}

export async function readTextFile(filePath: string): Promise<string> {
  try {
    return await fs.readFile(filePath, "utf8");
  } catch {
    return "";
  }
}

export async function readJsonLinesFile<T>(filePath: string): Promise<T[]> {
  try {
    const content = await fs.readFile(filePath, "utf8");
    if (!content.trim()) {
      return [];
    }
    return content
      .split(/\r?\n/)
      .map((line) => line.trim())
      .filter(Boolean)
      .map((line) => JSON.parse(line) as T);
  } catch {
    return [];
  }
}

export async function streamJsonLines(
  filePath: string,
  onRow: (row: Record<string, unknown>) => void | Promise<void>,
): Promise<void> {
  if (!(await fileExists(filePath))) {
    return;
  }
  const input = createReadStream(filePath, { encoding: "utf8" });
  const rl = createInterface({ input, crlfDelay: Infinity });
  for await (const line of rl) {
    const trimmed = line.trim();
    if (!trimmed) {
      continue;
    }
    try {
      await onRow(JSON.parse(trimmed) as Record<string, unknown>);
    } catch {
      continue;
    }
  }
}

export async function getDirectoryStats(dirPath: string): Promise<{ fileCount: number; totalBytes: number }> {
  let stat;
  try {
    stat = await fs.stat(dirPath);
  } catch {
    return { fileCount: 0, totalBytes: 0 };
  }

  const cacheKey = `${stat.mtimeMs}:${dirPath}`;
  const cached = directoryStatsCache.get(dirPath);
  if (cached && cached.key === cacheKey) {
    return cached.data;
  }

  const entries = await fs.readdir(dirPath, { withFileTypes: true });
  let fileCount = 0;
  let totalBytes = 0;

  await Promise.all(
    entries.map(async (entry) => {
      const fullPath = `${dirPath}/${entry.name}`;
      if (entry.isDirectory()) {
        const child = await getDirectoryStats(fullPath);
        fileCount += child.fileCount;
        totalBytes += child.totalBytes;
        return;
      }
      if (entry.isFile()) {
        try {
          const childStat = await fs.stat(fullPath);
          fileCount += 1;
          totalBytes += childStat.size;
        } catch {
          return;
        }
      }
    }),
  );

  const result = { fileCount, totalBytes };
  directoryStatsCache.set(dirPath, { key: cacheKey, data: result });
  return result;
}

export async function getTopLevelFileStats(dirPath: string): Promise<{ fileCount: number; totalBytes: number }> {
  try {
    const entries = await fs.readdir(dirPath, { withFileTypes: true });
    let fileCount = 0;
    let totalBytes = 0;
    await Promise.all(
      entries.map(async (entry) => {
        if (!entry.isFile()) {
          return;
        }
        try {
          const stat = await fs.stat(path.join(dirPath, entry.name));
          fileCount += 1;
          totalBytes += stat.size;
        } catch {
          return;
        }
      }),
    );
    return { fileCount, totalBytes };
  } catch {
    return { fileCount: 0, totalBytes: 0 };
  }
}

function runCachePath(runId: string, kind: string): string {
  return path.resolve(process.cwd(), DASHBOARD_CACHE_DIR, "runs", `${runId}.${kind}.json`);
}

export async function readRunCache<T>(runId: string, kind: string, key: string): Promise<T | null> {
  try {
    const raw = await fs.readFile(runCachePath(runId, kind), "utf8");
    const parsed = JSON.parse(raw) as { version?: number; key?: string; data?: T };
    if (parsed.version !== DASHBOARD_CACHE_VERSION || parsed.key !== key || parsed.data === undefined) {
      return null;
    }
    return parsed.data;
  } catch {
    return null;
  }
}

export async function writeRunCache<T>(runId: string, kind: string, key: string, data: T): Promise<void> {
  const filePath = runCachePath(runId, kind);
  await fs.mkdir(path.dirname(filePath), { recursive: true });
  await fs.writeFile(
    filePath,
    JSON.stringify(
      {
        version: DASHBOARD_CACHE_VERSION,
        key,
        data,
      },
      null,
      2,
    ),
    "utf8",
  );
}

export function getPhaseStatus(files: Set<string>, counts: RunListEntry["counts"]): PhaseCard[] {
  const plan = files.has("query_plan.json") ? "complete" : "missing";
  const queries =
    files.has("openalex_queries.json") || files.has("semanticscholar_queries.json") ? "complete" : plan === "complete" ? "partial" : "missing";
  const retrieval = counts.openAlex > 0 || counts.semanticScholar > 0 ? "complete" : files.has("openalex_raw.jsonl") || files.has("semanticscholar_raw.jsonl") ? "partial" : "missing";
  const candidates = counts.candidates > 0 ? "complete" : files.has("candidates_normalized.jsonl") ? "partial" : "missing";
  const scoring = counts.finalScored > 0 ? "complete" : counts.stage2 > 0 || files.has("scores_stage1.jsonl") ? "partial" : "missing";
  const coverage = files.has("coverage_tags.jsonl") || files.has("rankings_stageg.json") ? "complete" : files.has("phase_f_scoring_debug.jsonl") ? "partial" : "missing";
  const rerank = counts.rerank > 0 || files.has("rankings_stagei.json") ? "complete" : files.has("rerank_results.jsonl") ? "partial" : "missing";
  const final = files.has("output.json") ? "complete" : rerank === "complete" ? "partial" : "missing";

  return [
    { key: "plan", label: "B Plan", status: plan, blurb: "planner, anchors, facets", value: files.has("query_plan.json") ? "available" : "missing" },
    { key: "queries", label: "C Queries", status: queries, blurb: "OpenAlex and S2 builders", value: files.has("openalex_queries.json") || files.has("semanticscholar_queries.json") ? "available" : "missing" },
    { key: "retrieval", label: "D Retrieval", status: retrieval, blurb: "provider hit counts and raw pulls", value: `${counts.openAlex + counts.semanticScholar} rows` },
    { key: "candidates", label: "E Candidates", status: candidates, blurb: "dedupe and candidate pool", value: counts.candidates ? `${counts.candidates} candidates` : "missing" },
    { key: "scoring", label: "F Scoring", status: scoring, blurb: "stage1, stage2, final scores", value: counts.finalScored ? `${counts.finalScored} final` : counts.stage2 ? `${counts.stage2} stage2` : "missing" },
    { key: "coverage", label: "G/H Coverage", status: coverage, blurb: "shortlists, MMR, coverage tags", value: files.has("coverage_tags.jsonl") ? "coverage ready" : files.has("rankings_stageg.json") ? "shortlists ready" : "missing" },
    { key: "rerank", label: "I Rerank", status: rerank, blurb: "pointwise and pairwise rerank", value: counts.rerank ? `${counts.rerank} reranked` : files.has("rankings_stagei.json") ? "rankings only" : "missing" },
    { key: "final", label: "Final", status: final, blurb: "output top lists", value: files.has("output.json") ? "output ready" : "missing" },
  ];
}

export function statusLabelFromPhaseCards(phaseCards: PhaseCard[]): string {
  const complete = phaseCards.filter((card) => card.status === "complete").length;
  if (complete === phaseCards.length) {
    return "Complete";
  }
  if (complete >= 3) {
    return "Partial";
  }
  return "Cache / Early";
}
