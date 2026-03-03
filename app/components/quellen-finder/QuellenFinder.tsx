"use client";

import { Fragment, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import Cookies from "js-cookie";
import { AlertTriangle, ArrowLeft, Ban, BarChart3, Check, ChevronDown, ExternalLink, Loader2, Play, SlidersHorizontal, X } from "lucide-react";
import { toast } from "sonner";
import { limit, onSnapshot, orderBy, query } from "firebase/firestore";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Separator } from "@/components/ui/separator";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";

import { useAuth } from "@/app/components/providers/AuthProvider";
import { firestoreClient } from "@/app/lib/firebase/firestoreClient";
import {
  projectResearchRunsCol,
  quellenFinderTwoLaneResultsCol,
  quellenFinderTwoLaneTelemetryCol,
} from "@/app/lib/firestore/refs";
import type {
  QuellenFinderRunDoc,
  TwoLaneLane,
  TwoLanePool,
  TwoLaneResultDoc,
} from "@/app/lib/firestore/types";
import type { Kapitel } from "@/app/actions/kapitels";

const API_BASE_URL = process.env.NEXT_PUBLIC_FASTAPI_URL || "http://localhost:8000";

type WithId<T> = T & { id: string };
type WithDocId<T> = T & { docId: string };
type RunRow = WithId<QuellenFinderRunDoc>;
type TwoLaneRow = WithDocId<TwoLaneResultDoc>;
type TelemetryRow = WithId<Record<string, unknown>>;

type SortDir = "asc" | "desc";
type TwoLaneSortKey = "rank" | "llmScore" | "year" | "citations";
type TwoLaneViewKey = "match_with_abstract" | "match_without_abstract" | "authority_with_abstract" | "authority_without_abstract";

type ToDateLike = { toDate: () => Date };

function hasToDate(value: unknown): value is ToDateLike {
  if (typeof value !== "object" || value === null) return false;
  const rec = value as Record<string, unknown>;
  return typeof rec.toDate === "function";
}

function toDateOrNull(value: unknown): Date | null {
  if (!value) return null;
  if (value instanceof Date) return value;
  if (hasToDate(value)) {
    try {
      const d = value.toDate();
      return d instanceof Date ? d : null;
    } catch {
      return null;
    }
  }
  return null;
}

function formatTimeHm(value: unknown): string {
  const d = toDateOrNull(value);
  if (!d) return "";
  return d.toLocaleTimeString("de-DE", {
    hour: "2-digit",
    minute: "2-digit",
  });
}

function formatDateTimeWithSeconds(value: unknown): string {
  const d = toDateOrNull(value);
  if (!d) return "";
  return d.toLocaleString("de-DE", {
    day: "numeric",
    month: "numeric",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function formatDurationMs(ms: number): string {
  const s = Math.max(0, Math.floor(Number(ms) / 1000));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  if (h > 0) return `${h}:${String(m).padStart(2, "0")}:${String(sec).padStart(2, "0")}`;
  return `${m}:${String(sec).padStart(2, "0")}`;
}

function formatElapsedShort(ms: number): string {
  const s = Math.max(0, Math.floor(Number(ms) / 1000));
  if (s < 60) return `${s}s`;
  return formatDurationMs(ms);
}

function formatSecondsShort(seconds: number | null): string {
  if (typeof seconds !== "number" || !Number.isFinite(seconds) || seconds < 0) return "—";
  if (seconds < 60) return `${seconds.toFixed(1)}s`;
  return formatDurationMs(seconds * 1000);
}

async function readFastApiError(res: Response): Promise<string> {
  try {
    const data = (await res.json().catch(() => ({}))) as { detail?: unknown; error?: unknown; message?: unknown };
    const candidates = [data?.detail, data?.error, data?.message];
    for (const c of candidates) {
      if (typeof c === "string" && c.trim()) return c.trim();
    }
  } catch {
    // ignore
  }
  return "Request failed.";
}

function statusBadgeVariant(status: string): "default" | "secondary" | "destructive" | "outline" {
  if (status === "success") return "default";
  if (status === "error") return "destructive";
  if (status === "running") return "secondary";
  if (status === "queued") return "outline";
  return "outline";
}

function progressLabel(run: RunRow | null): string {
  if (!run) return "";
  const stage = String(run.progress?.stage || "");
  const msg = String(run.progress?.message || "");
  const cur = run.progress?.current;
  const total = run.progress?.total;
  const pct = typeof cur === "number" && typeof total === "number" && total > 0 ? ` (${cur}/${total})` : "";
  const head = stage ? stage : "progress";
  return msg ? `${head}${pct}: ${msg}` : `${head}${pct}`;
}

const TWO_LANE_PIPELINE_STEPS: { key: string; label: string }[] = [
  { key: "starting", label: "Start" },
  { key: "phase_b_query_planner", label: "Query Planning" },
  { key: "phase_c_openalex_query_builder", label: "OpenAlex Queries" },
  { key: "phase_c_s2_query_builder", label: "Semantic Scholar Queries" },
  { key: "phase_d_openalex_retrieval", label: "OpenAlex Retrieval" },
  { key: "phase_d_semanticscholar_retrieval", label: "Semantic Scholar Retrieval" },
  { key: "phase_e_candidates", label: "Candidates" },
  { key: "phase_f", label: "Embedding & Scoring" },
  { key: "phase_g", label: "Lane Scoring" },
  { key: "phase_h", label: "Coverage Tags" },
  { key: "phase_i", label: "LLM Rerank" },
  { key: "phase_k", label: "Final Output" },
  { key: "write_results", label: "Saving Results" },
];

const TWO_LANE_VIEW_LABELS: Record<TwoLaneViewKey, string> = {
  match_with_abstract: "Match (mit Abstract)",
  match_without_abstract: "Match (ohne Abstract)",
  authority_with_abstract: "Authority (mit Abstract)",
  authority_without_abstract: "Authority (ohne Abstract)",
};

function parseTwoLaneViewKey(key: TwoLaneViewKey): { lane: TwoLaneLane; pool: TwoLanePool } {
  const lane: TwoLaneLane = key.startsWith("match") ? "match" : "authority";
  const pool: TwoLanePool = key.endsWith("with_abstract") ? "with_abstract" : "without_abstract";
  return { lane, pool };
}

function formatIntDe(value: unknown): string {
  if (typeof value !== "number" || !Number.isFinite(value)) return "";
  return Math.trunc(value).toLocaleString("de-DE");
}

function formatUsd(value: unknown): string {
  if (typeof value !== "number" || !Number.isFinite(value)) return "—";
  const digits = value < 1 ? 3 : 2;
  return `$${value.toFixed(digits)}`;
}

function kapitelDepth(nummer: unknown): number {
  const s = String(nummer || "").trim();
  if (!s) return 0;
  return Math.max(0, (s.match(/\./g) || []).length);
}

function llmScorePillClasses(score: number | null): string {
  if (typeof score !== "number" || !Number.isFinite(score)) {
    return "bg-muted text-muted-foreground";
  }
  if (score >= 90) return "bg-emerald-100 text-emerald-800 dark:bg-emerald-950/40 dark:text-emerald-200";
  if (score >= 70) return "bg-amber-100 text-amber-900 dark:bg-amber-950/40 dark:text-amber-200";
  return "bg-rose-100 text-rose-900 dark:bg-rose-950/40 dark:text-rose-200";
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" ? (value as Record<string, unknown>) : {};
}

function asRecordArray(value: unknown): Record<string, unknown>[] {
  if (!Array.isArray(value)) return [];
  return value.filter((v) => v && typeof v === "object").map((v) => v as Record<string, unknown>);
}

function asStringArray(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  const out: string[] = [];
  for (const v of value) {
    if (typeof v !== "string") continue;
    const s = v.trim();
    if (s) out.push(s);
  }
  return out;
}

function asNumberOrNull(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function asIntOrNull(value: unknown): number | null {
  const n = asNumberOrNull(value);
  if (n === null) return null;
  return Math.trunc(n);
}

function quantile(sorted: number[], q: number): number | null {
  const xs = sorted.filter((v) => typeof v === "number" && Number.isFinite(v)).slice().sort((a, b) => a - b);
  if (!xs.length) return null;
  const qq = Math.max(0, Math.min(1, q));
  const pos = (xs.length - 1) * qq;
  const lo = Math.floor(pos);
  const hi = Math.ceil(pos);
  if (lo === hi) return xs[lo] ?? null;
  const w = pos - lo;
  const a = xs[lo] ?? 0;
  const b = xs[hi] ?? 0;
  return a * (1 - w) + b * w;
}

function summarizeCounts(values: number[]): { mean: number | null; median: number | null; p90: number | null; max: number | null } {
  const xs = values.filter((v) => typeof v === "number" && Number.isFinite(v)).slice();
  if (!xs.length) return { mean: null, median: null, p90: null, max: null };
  xs.sort((a, b) => a - b);
  const mean = xs.reduce((acc, v) => acc + v, 0) / xs.length;
  const median = quantile(xs, 0.5);
  const p90 = quantile(xs, 0.9);
  const max = xs[xs.length - 1] ?? null;
  return { mean, median, p90, max };
}

function TermBadges({ terms, max = 14 }: { terms: string[]; max?: number }) {
  const xs = (terms || []).filter((t) => typeof t === "string" && t.trim()).map((t) => t.trim());
  const head = xs.slice(0, Math.max(0, max));
  const tail = xs.slice(head.length);
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap gap-1">
        {head.map((t, i) => (
          <Badge key={`${t}-${i}`} variant="outline" className="text-[10px]">
            {t}
          </Badge>
        ))}
        {tail.length ? (
          <Badge variant="secondary" className="text-[10px]">
            +{tail.length}
          </Badge>
        ) : null}
      </div>
      {tail.length ? (
        <details>
          <summary className="text-xs text-muted-foreground cursor-pointer select-none">Show all</summary>
          <div className="mt-2 flex flex-wrap gap-1">
            {xs.map((t, i) => (
              <Badge key={`${t}-${i}`} variant="outline" className="text-[10px]">
                {t}
              </Badge>
            ))}
          </div>
        </details>
      ) : null}
    </div>
  );
}

function HistogramBars({ hist, height = 96 }: { hist: unknown; height?: number }) {
  const rec = asRecord(hist);
  const countsRaw = rec["counts"];
  const counts = Array.isArray(countsRaw)
    ? countsRaw.map((v) => (typeof v === "number" && Number.isFinite(v) ? v : 0)).map((v) => Math.max(0, Math.trunc(v)))
    : [];
  const bins = typeof rec["bins"] === "number" && Number.isFinite(rec["bins"]) ? Math.max(1, Math.trunc(rec["bins"])) : counts.length;
  const lo = asNumberOrNull(rec["lo"]) ?? 0;
  const hi = asNumberOrNull(rec["hi"]) ?? Math.max(1, bins);
  const maxCount = Math.max(1, ...counts);
  if (!counts.length) return <div className="text-sm text-muted-foreground">No histogram data yet.</div>;

  const step = bins > 0 ? (hi - lo) / bins : 1;

  return (
    <div className="space-y-1">
      <div className="flex items-end gap-[2px]" style={{ height }}>
        {counts.map((c, i) => {
          const binLo = lo + i * step;
          const binHi = binLo + step;
          return (
            <div
              key={i}
              className="flex-1 bg-muted rounded-sm overflow-hidden"
              title={`${binLo.toFixed(1)}–${binHi.toFixed(1)}: ${c}`}
            >
              <div className="w-full bg-primary/70" style={{ height: `${(c / maxCount) * 100}%` }} />
            </div>
          );
        })}
      </div>
      <div className="flex items-center justify-between text-[10px] text-muted-foreground">
        <span className="tabular-nums">{lo.toFixed(0)}</span>
        <span className="tabular-nums">{hi.toFixed(0)}</span>
      </div>
    </div>
  );
}

function BarList({ rows, maxRows = 80 }: { rows: { label: string; value: number }[]; maxRows?: number }) {
  const xs = (rows || []).filter((r) => r && typeof r.label === "string" && typeof r.value === "number" && Number.isFinite(r.value));
  if (!xs.length) return <div className="text-sm text-muted-foreground">No data yet.</div>;
  const maxVal = Math.max(1, ...xs.map((r) => r.value));
  const view = xs.slice(0, Math.max(0, maxRows));
  return (
    <div className="space-y-1">
      {view.map((r) => (
        <div key={r.label} className="flex items-center gap-2">
          <div className="w-14 text-[10px] font-mono text-muted-foreground tabular-nums">{r.label}</div>
          <div className="flex-1 h-2 bg-muted rounded-sm overflow-hidden">
            <div className="h-2 bg-primary/70" style={{ width: `${(r.value / maxVal) * 100}%` }} />
          </div>
          <div className="w-16 text-[10px] text-right tabular-nums text-muted-foreground">{r.value}</div>
        </div>
      ))}
      {xs.length > view.length ? <div className="text-[10px] text-muted-foreground">+{xs.length - view.length} more</div> : null}
    </div>
  );
}

function ScatterMatchAuthority({ points, height = 280 }: { points: unknown; height?: number }) {
  const xsRaw = Array.isArray(points) ? points : [];
  const xs = xsRaw
    .map((p) => asRecord(p))
    .map((p) => ({
      x: asNumberOrNull(p["match_lane"]) ?? 0,
      y: asNumberOrNull(p["authority_lane"]) ?? 0,
      pool: typeof p["pool"] === "string" ? String(p["pool"]) : "unknown",
    }))
    .filter((p) => p.x >= 0 && p.x <= 1 && p.y >= 0 && p.y <= 1);

  if (!xs.length) return <div className="text-sm text-muted-foreground">No scatter data yet.</div>;

  const color = (pool: string) => {
    if (pool === "with_abstract") return "#3b82f6"; // blue-500
    if (pool === "without_abstract") return "#f97316"; // orange-500
    return "#94a3b8"; // slate-400
  };

  return (
    <div className="space-y-2">
      <svg width="100%" height={height} viewBox="0 0 100 100" preserveAspectRatio="none" className="rounded-md border border-border bg-background">
        <line x1="0" y1="100" x2="100" y2="100" stroke="rgba(148,163,184,0.35)" strokeWidth="0.5" />
        <line x1="0" y1="0" x2="0" y2="100" stroke="rgba(148,163,184,0.35)" strokeWidth="0.5" />
        <line x1="0" y1="50" x2="100" y2="50" stroke="rgba(148,163,184,0.15)" strokeWidth="0.5" />
        <line x1="50" y1="0" x2="50" y2="100" stroke="rgba(148,163,184,0.15)" strokeWidth="0.5" />
        {xs.map((p, i) => (
          <circle key={i} cx={p.x * 100} cy={(1 - p.y) * 100} r="0.9" fill={color(p.pool)} fillOpacity="0.35" />
        ))}
      </svg>
      <div className="flex items-center gap-3 text-[10px] text-muted-foreground">
        <div className="flex items-center gap-1">
          <span className="inline-block h-2 w-2 rounded-sm" style={{ backgroundColor: "#3b82f6" }} />
          with_abstract
        </div>
        <div className="flex items-center gap-1">
          <span className="inline-block h-2 w-2 rounded-sm" style={{ backgroundColor: "#f97316" }} />
          without_abstract
        </div>
      </div>
    </div>
  );
}

export function QuellenFinder({
  initialKapitels,
  projektId,
  projektName,
}: {
  initialKapitels: Kapitel[];
  projektId: string;
  projektName: string;
}) {
  const { user } = useAuth();

  const [selectedKapitelId, setSelectedKapitelId] = useState<string | null>(null);

  const [runs, setRuns] = useState<RunRow[]>([]);
  const [activeTwoLaneRunId, setActiveTwoLaneRunId] = useState<string | null>(null);

  type PlannerModel = "gpt-5-nano" | "gpt-5-mini" | "gpt-5.2";
  type RerankModel = "gpt-5-nano" | "gpt-5-mini";
  type ReasoningEffort = "low" | "medium" | "high";

  const [plannerModel, setPlannerModel] = useState<PlannerModel>("gpt-5-mini");
  const [openalexQueryModel, setOpenalexQueryModel] = useState<PlannerModel>("gpt-5-mini");
  const [s2QueryModel, setS2QueryModel] = useState<PlannerModel>("gpt-5-mini");
  const [rerankModel, setRerankModel] = useState<RerankModel>("gpt-5-nano");
  const [embeddingModel, setEmbeddingModel] = useState("text-embedding-3-small");
  const [reasoningEffort, setReasoningEffort] = useState<ReasoningEffort>("high");
  const [rerankConcurrency, setRerankConcurrency] = useState<number>(20);
  const [settingsOpen, setSettingsOpen] = useState(false);

  const [twoLaneViewKey, setTwoLaneViewKey] = useState<TwoLaneViewKey>("match_with_abstract");

  const [twoLaneResults, setTwoLaneResults] = useState<TwoLaneRow[]>([]);
  const [twoLaneTelemetry, setTwoLaneTelemetry] = useState<TelemetryRow[]>([]);

  const [resultsSortKey, setResultsSortKey] = useState<TwoLaneSortKey>("llmScore");
  const [resultsSortDir, setResultsSortDir] = useState<SortDir>("desc");

  const [activePaperDocId, setActivePaperDocId] = useState<string | null>(null);
  const [telemetryDialogOpen, setTelemetryDialogOpen] = useState(false);
  const [nowMs, setNowMs] = useState(() => Date.now());

  const kapitels = useMemo(() => initialKapitels ?? [], [initialKapitels]);

  const selectedKapitel = useMemo(() => {
    if (!selectedKapitelId) return null;
    return kapitels.find((k) => k.id === selectedKapitelId) ?? null;
  }, [kapitels, selectedKapitelId]);

  const twoLaneRuns = useMemo(() => runs.filter((r) => r.kind === "sources_two_lane"), [runs]);

  const activeTwoLaneRun = useMemo(() => {
    if (activeTwoLaneRunId) {
      const found = twoLaneRuns.find((r) => r.id === activeTwoLaneRunId);
      if (found) return found;
    }
    if (selectedKapitelId) {
      return twoLaneRuns.find((r) => Array.isArray(r.kapitelIds) && r.kapitelIds.includes(selectedKapitelId)) ?? null;
    }
    return twoLaneRuns[0] ?? null;
  }, [twoLaneRuns, activeTwoLaneRunId, selectedKapitelId]);

  useEffect(() => {
    if (selectedKapitelId) return;
    if (activeTwoLaneRun?.kapitelIds?.[0]) {
      setSelectedKapitelId(activeTwoLaneRun.kapitelIds[0]);
      return;
    }
    if (kapitels.length) setSelectedKapitelId(kapitels[0]?.id ?? null);
  }, [selectedKapitelId, activeTwoLaneRun?.kapitelIds, kapitels]);

  useEffect(() => {
    if (!activeTwoLaneRunId) return;
    if (twoLaneRuns.some((r) => r.id === activeTwoLaneRunId)) return;
    setActiveTwoLaneRunId(null);
  }, [twoLaneRuns, activeTwoLaneRunId]);

  useEffect(() => {
    if (!user?.uid || !projektId) return;
    const q = query(projectResearchRunsCol(firestoreClient, user.uid, projektId), orderBy("createdAt", "desc"), limit(50));
    return onSnapshot(
      q,
      (snap) => {
        const next = snap.docs.map((d) => ({ id: d.id, ...(d.data() as QuellenFinderRunDoc) }));
        setRuns(next);
      },
      (err) => {
        console.error("Failed to load researchRuns:", err);
        setRuns([]);
      }
    );
  }, [user?.uid, projektId]);

  useEffect(() => {
    if (!user?.uid || !projektId || !activeTwoLaneRun?.id) {
      setTwoLaneResults([]);
      setTwoLaneTelemetry([]);
      return;
    }

    const resultsCol = quellenFinderTwoLaneResultsCol(firestoreClient, user.uid, projektId, activeTwoLaneRun.id);
    const telemetryCol = quellenFinderTwoLaneTelemetryCol(firestoreClient, user.uid, projektId, activeTwoLaneRun.id);

    const unsubResults = onSnapshot(
      query(resultsCol, limit(250)),
      (snap) => {
        const next = snap.docs.map((d) => ({ docId: d.id, ...(d.data() as TwoLaneResultDoc) }));
        setTwoLaneResults(next);
      },
      (err) => {
        console.error("Failed to load twoLaneResults:", err);
        setTwoLaneResults([]);
      }
    );

    const unsubTelemetry = onSnapshot(
      query(telemetryCol, limit(200)),
      (snap) => {
        const next = snap.docs.map((d) => ({ id: d.id, ...(d.data() as Record<string, unknown>) }));
        setTwoLaneTelemetry(next);
      },
      (err) => {
        console.error("Failed to load twoLaneTelemetry:", err);
        setTwoLaneTelemetry([]);
      }
    );

    return () => {
      unsubResults();
      unsubTelemetry();
    };
  }, [user?.uid, projektId, activeTwoLaneRun?.id]);

  const telemetryById = useMemo(() => {
    const map = new Map<string, TelemetryRow>();
    for (const t of twoLaneTelemetry) map.set(t.id, t);
    return map;
  }, [twoLaneTelemetry]);

  const finalReportView = useMemo(() => {
    const fr = telemetryById.get("final_report") as Record<string, unknown> | undefined;
    const frRec: Record<string, unknown> = fr && typeof fr === "object" ? fr : {};

    const models = (frRec["models"] && typeof frRec["models"] === "object" ? (frRec["models"] as Record<string, unknown>) : {}) as Record<string, unknown>;

    const summary = activeTwoLaneRun?.summary;
    const summaryRec: Record<string, unknown> = summary && typeof summary === "object" ? (summary as Record<string, unknown>) : {};
    const costsFromFinalReport = frRec["costs"] && typeof frRec["costs"] === "object" ? (frRec["costs"] as Record<string, unknown>) : null;
    const costs = (costsFromFinalReport ?? summaryRec) as Record<string, unknown>;

    const stageCosts =
      costs["stage_costs"] && typeof costs["stage_costs"] === "object" ? (costs["stage_costs"] as Record<string, unknown>) : ({} as Record<string, unknown>);
    const durations =
      frRec["durations_s"] && typeof frRec["durations_s"] === "object" ? (frRec["durations_s"] as Record<string, unknown>) : ({} as Record<string, unknown>);
    const counts = (frRec["counts"] && typeof frRec["counts"] === "object" ? (frRec["counts"] as Record<string, unknown>) : {}) as Record<string, unknown>;

    const stageRows = Object.entries(stageCosts).map(([stage, v]) => {
      const rec = v && typeof v === "object" ? (v as Record<string, unknown>) : ({} as Record<string, unknown>);
      const costUsd = typeof rec["cost_usd"] === "number" && Number.isFinite(rec["cost_usd"]) ? (rec["cost_usd"] as number) : null;
      const inputTokens = typeof rec["input_tokens"] === "number" ? (rec["input_tokens"] as number) : null;
      const outputTokens = typeof rec["output_tokens"] === "number" ? (rec["output_tokens"] as number) : null;
      const requests = typeof rec["requests"] === "number" ? (rec["requests"] as number) : null;
      const durationS = typeof durations[stage] === "number" && Number.isFinite(durations[stage]) ? (durations[stage] as number) : null;
      return { stage, costUsd, inputTokens, outputTokens, requests, durationS };
    });
    stageRows.sort((a, b) => (b.costUsd ?? -1) - (a.costUsd ?? -1));

    const totalCostUsd = typeof costs["total_cost_usd"] === "number" ? (costs["total_cost_usd"] as number) : null;
    const budgetCapUsd = typeof costs["budget_cap_usd"] === "number" ? (costs["budget_cap_usd"] as number) : null;
    const keySource = typeof costs["key_source"] === "string" ? (costs["key_source"] as string) : null;

    return { models, costs, stageRows, counts, totalCostUsd, budgetCapUsd, keySource, raw: fr ? frRec : { costs: summaryRec } };
  }, [telemetryById, activeTwoLaneRun?.summary]);

  const phaseBPlan = asRecord(telemetryById.get("phase_b_plan"));
  const phaseCQueries = asRecord(telemetryById.get("phase_c_queries"));
  const phaseDRetrieval = asRecord(telemetryById.get("phase_d_retrieval"));
  const phaseECandidates = asRecord(telemetryById.get("phase_e_candidates"));
  const phaseFScoring = asRecord(telemetryById.get("phase_f_scoring"));
  const phaseIRerank = asRecord(telemetryById.get("phase_i_rerank"));
  const metricsDoc = asRecord(telemetryById.get("metrics"));

  const facets = asRecordArray(phaseBPlan["facets"]);
  const facetLabelById = useMemo(() => {
    const map = new Map<string, string>();
    for (const f of facets) {
      const id = typeof f["facet_id"] === "string" ? String(f["facet_id"]) : "";
      if (!id) continue;
      const labelDe = typeof f["facet_label_de"] === "string" ? String(f["facet_label_de"]) : "";
      const labelEn = typeof f["facet_label_en"] === "string" ? String(f["facet_label_en"]) : "";
      const label = labelDe || labelEn || id;
      map.set(id, label);
    }
    return map;
  }, [facets]);
  const primaryAnchors = asRecord(phaseBPlan["primary_context_anchors"]);
  const primaryAnchorsEn = asStringArray(primaryAnchors["en"]);
  const primaryAnchorsDe = asStringArray(primaryAnchors["de"]);
  const globalCanonicalTerms = asRecord(phaseBPlan["global_canonical_terms"]);
  const globalCanonicalTermsEn = asStringArray(globalCanonicalTerms["en"]);
  const globalCanonicalTermsDe = asStringArray(globalCanonicalTerms["de"]);
  const globalExclusions = asRecord(phaseBPlan["global_exclusions"]);
  const globalExclusionsEn = asStringArray(globalExclusions["en"]);
  const globalExclusionsDe = asStringArray(globalExclusions["de"]);
  const openalexQueries = asRecordArray(phaseCQueries["openalex_queries"]);
  const s2BulkQueries = asRecordArray(phaseCQueries["s2_bulk_queries"]);
  const queryLengths = asRecord(phaseCQueries["query_lengths"]);
  const openalexQueryLenHist = asRecord(asRecord(queryLengths["openalex"])["hist_20bins"]);
  const s2QueryLenHist = asRecord(asRecord(queryLengths["semanticscholar"])["hist_20bins"]);

  const twoLaneCountsByView = useMemo(() => {
    const counts: Record<TwoLaneViewKey, number> = {
      match_with_abstract: 0,
      match_without_abstract: 0,
      authority_with_abstract: 0,
      authority_without_abstract: 0,
    };
    for (const r of twoLaneResults) {
      const k = `${r.lane}_${r.pool}` as TwoLaneViewKey;
      if (k in counts) counts[k] += 1;
    }
    return counts;
  }, [twoLaneResults]);

  const twoLaneFiltered = useMemo(() => {
    const { lane, pool } = parseTwoLaneViewKey(twoLaneViewKey);
    const rows = twoLaneResults.filter((r) => r.lane === lane && r.pool === pool);

    const dir: 1 | -1 = resultsSortDir === "asc" ? 1 : -1;

    const numOrNull = (v: unknown) => (typeof v === "number" && Number.isFinite(v) ? v : null);
    const cmpNum = (a: number | null, b: number | null) => {
      if (a === null && b === null) return 0;
      if (a === null) return 1;
      if (b === null) return -1;
      return dir * (a - b);
    };

    const llmScore = (r: TwoLaneRow) => numOrNull((r.rerank as Record<string, unknown> | null | undefined)?.llm_score_0_100);

    return [...rows].sort((a, b) => {
      if (resultsSortKey === "rank") return dir * ((numOrNull(a.rank) ?? 9999) - (numOrNull(b.rank) ?? 9999));
      if (resultsSortKey === "year") return cmpNum(numOrNull(a.year), numOrNull(b.year));
      if (resultsSortKey === "citations") return cmpNum(numOrNull(a.citations), numOrNull(b.citations));
      return cmpNum(llmScore(a), llmScore(b));
    });
  }, [twoLaneResults, twoLaneViewKey, resultsSortDir, resultsSortKey]);

  useEffect(() => {
    if (!activePaperDocId) return;
    if (twoLaneFiltered.some((r) => r.docId === activePaperDocId)) return;
    setActivePaperDocId(null);
  }, [twoLaneFiltered, activePaperDocId]);

  const runningTwoLane = activeTwoLaneRun?.status === "running" || activeTwoLaneRun?.status === "queued";
  const canRunTwoLane = Boolean(user?.uid && projektId && selectedKapitelId);

  useEffect(() => {
    if (!runningTwoLane) return;
    setNowMs(Date.now());
    const id = window.setInterval(() => setNowMs(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, [runningTwoLane]);

  const lastPipelineStepIndexByRunId = useRef<Map<string, number>>(new Map());
  useEffect(() => {
    if (!activeTwoLaneRun?.id) return;
    const stage = String(activeTwoLaneRun.progress?.stage || "");
    const idx = TWO_LANE_PIPELINE_STEPS.findIndex((s) => s.key === stage);
    if (idx >= 0) lastPipelineStepIndexByRunId.current.set(activeTwoLaneRun.id, idx);
  }, [activeTwoLaneRun?.id, activeTwoLaneRun?.progress?.stage]);

  const lastRunStatus = useRef<{ runId: string; status: string } | null>(null);
  useEffect(() => {
    if (!activeTwoLaneRun) return;
    const prev = lastRunStatus.current;
    if (!prev || prev.runId !== activeTwoLaneRun.id) {
      lastRunStatus.current = { runId: activeTwoLaneRun.id, status: String(activeTwoLaneRun.status || "") };
      return;
    }

    const nextStatus = String(activeTwoLaneRun.status || "");
    if (prev.status !== nextStatus) {
      if (nextStatus === "success") {
        toast.success("Suche abgeschlossen", {
          description: typeof activeTwoLaneRun.resultCount === "number" ? `${formatIntDe(activeTwoLaneRun.resultCount)} Ergebnisse` : undefined,
        });
      } else if (nextStatus === "cancelled") {
        toast.success("Suche abgebrochen", { description: `Run: ${activeTwoLaneRun.id}` });
      } else if (nextStatus === "error") {
        toast.error("Suche fehlgeschlagen", { description: String(activeTwoLaneRun.errorMessage || "").trim() || "Unbekannter Fehler" });
      }
    }

    lastRunStatus.current = { runId: activeTwoLaneRun.id, status: nextStatus };
  }, [activeTwoLaneRun, activeTwoLaneRun?.id, activeTwoLaneRun?.status, activeTwoLaneRun?.resultCount, activeTwoLaneRun?.errorMessage]);

  const startTwoLaneSources = async () => {
    if (!canRunTwoLane) {
      toast.error("Bitte ein Kapitel auswählen.");
      return;
    }
    const token = Cookies.get("__session");
    if (!token) {
      toast.error("Nicht eingeloggt", { description: "Session Token fehlt." });
      return;
    }
    if (!selectedKapitelId) {
      toast.error("Bitte ein Kapitel auswählen.");
      return;
    }
    const kapitelId = selectedKapitelId;

    const res = await fetch(`${API_BASE_URL}/api/quellen-finder/sources-two-lane/start`, {
      method: "POST",
      headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
      body: JSON.stringify({
        projekt_id: projektId,
        kapitel_id: kapitelId,
        planner_model: plannerModel,
        openalex_query_builder_model: openalexQueryModel,
        s2_query_builder_model: s2QueryModel,
        rerank_model: rerankModel,
        embedding_model: embeddingModel,
        reasoning_effort: reasoningEffort,
        rerank_concurrency: rerankConcurrency,
      }),
    });

    if (!res.ok) {
      const detail = await readFastApiError(res);
      if (res.status === 402) {
        toast.error("Nicht genügend Credits", { description: detail });
        return;
      }
      toast.error("Suche fehlgeschlagen", { description: detail });
      return;
    }

    const data = (await res.json().catch(() => ({}))) as Record<string, unknown>;
    const runId = typeof data.run_id === "string" ? String(data.run_id) : "";
    if (runId) setActiveTwoLaneRunId(runId);
    toast.success("Suche gestartet", { description: runId ? `Run: ${runId}` : undefined });
  };

  const cancelTwoLaneSources = async () => {
    if (!activeTwoLaneRun?.id) {
      toast.error("Kein aktiver Run", { description: "Bitte zuerst einen Run auswählen." });
      return;
    }
    const token = Cookies.get("__session");
    if (!token) {
      toast.error("Nicht eingeloggt", { description: "Session Token fehlt." });
      return;
    }

    const res = await fetch(`${API_BASE_URL}/api/quellen-finder/sources-two-lane/cancel`, {
      method: "POST",
      headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
      body: JSON.stringify({ projekt_id: projektId, run_id: activeTwoLaneRun.id }),
    });

    if (!res.ok) {
      const detail = await readFastApiError(res);
      toast.error("Cancel fehlgeschlagen", { description: detail });
      return;
    }

    toast.success("Abbruch angefordert", { description: `Run: ${activeTwoLaneRun.id}` });
  };

  const selectKapitel = (kapitelId: string | null) => {
    setSelectedKapitelId(kapitelId);
    setActivePaperDocId(null);

    if (!kapitelId) {
      setActiveTwoLaneRunId(null);
      return;
    }

    const mostRecentRun = twoLaneRuns.find((r) => Array.isArray(r.kapitelIds) && r.kapitelIds.includes(kapitelId));
    setActiveTwoLaneRunId(mostRecentRun?.id ?? null);
  };

  const selectRun = (run: RunRow) => {
    setActiveTwoLaneRunId(run.id);
    setActivePaperDocId(null);
    const kid = Array.isArray(run.kapitelIds) ? run.kapitelIds[0] : null;
    if (kid) setSelectedKapitelId(kid);
  };

  const toggleResultsSort = (key: TwoLaneSortKey) => {
    setResultsSortKey((prev) => {
      if (prev === key) {
        setResultsSortDir((d) => (d === "asc" ? "desc" : "asc"));
        return prev;
      }
      setResultsSortDir(key === "rank" ? "asc" : "desc");
      return key;
    });
  };

  const activeKapitelSnapshot = activeTwoLaneRun?.kapitelSnapshots?.[0] ?? null;
  const chapterNummer = String(activeKapitelSnapshot?.nummer ?? selectedKapitel?.nummer ?? "").trim();
  const chapterTitle = String(activeKapitelSnapshot?.title ?? selectedKapitel?.title ?? "").trim();
  const chapterHeading = `${chapterNummer ? `${chapterNummer} ` : ""}${chapterTitle || "Kapitel"}`.trim();

  const runStartedAt = toDateOrNull(activeTwoLaneRun?.startedAt) ?? toDateOrNull(activeTwoLaneRun?.createdAt);
  const runFinishedAt = toDateOrNull(activeTwoLaneRun?.finishedAt);
  const runStartMs = runStartedAt?.getTime() ?? nowMs;
  const stageStartMs =
    (toDateOrNull(activeTwoLaneRun?.progress?.stageStartedAt) ?? runStartedAt)?.getTime() ?? runStartMs;
  const elapsedMs = Math.max(0, nowMs - runStartMs);
  const stageElapsedMs = Math.max(0, nowMs - stageStartMs);

  const summaryRec = asRecord(activeTwoLaneRun?.summary);
  const totalCostUsd = typeof finalReportView.totalCostUsd === "number" ? finalReportView.totalCostUsd : asNumberOrNull(summaryRec["total_cost_usd"]);
  const secondsTotal = asNumberOrNull(summaryRec["seconds_total"]);
  const resultCount =
    typeof activeTwoLaneRun?.resultCount === "number" ? activeTwoLaneRun.resultCount : twoLaneResults.length ? twoLaneResults.length : null;
  const candidatesTotal = typeof finalReportView.counts["candidates_total"] === "number" ? (finalReportView.counts["candidates_total"] as number) : null;

  const stageKey = String(activeTwoLaneRun?.progress?.stage || "");
  const stageIdxDirect = TWO_LANE_PIPELINE_STEPS.findIndex((s) => s.key === stageKey);
  const stageIdxRemembered = activeTwoLaneRun?.id ? (lastPipelineStepIndexByRunId.current.get(activeTwoLaneRun.id) ?? -1) : -1;
  const stageIdx = stageIdxDirect >= 0 ? stageIdxDirect : stageIdxRemembered;

  const isDone = activeTwoLaneRun?.status === "success" || stageKey === "done";
  const isError = activeTwoLaneRun?.status === "error" || stageKey === "error";
  const isCancelled = activeTwoLaneRun?.status === "cancelled" || stageKey === "cancelled";
  const isCancelRequested = Boolean(activeTwoLaneRun?.cancelRequestedAt) || stageKey === "cancel_requested";

  const completedSteps = isDone ? TWO_LANE_PIPELINE_STEPS.length : Math.max(0, stageIdx);
  const activeStep = !isDone && stageIdx >= 0 ? stageIdx : -1;
  const activeStepLabel = activeStep >= 0 ? TWO_LANE_PIPELINE_STEPS[activeStep]?.label ?? "" : "";

  const renderPaperDetails = (paper: TwoLaneRow) => {
    const llm =
      typeof paper.rerank?.llm_score_0_100 === "number" && Number.isFinite(paper.rerank.llm_score_0_100)
        ? Math.round(paper.rerank.llm_score_0_100)
        : null;
    const rationale = String(paper.rerank?.rationale || "").trim();
    const covered = Array.isArray(paper.rerank?.covered_facets) ? paper.rerank?.covered_facets : [];
    const topics = [...new Set((covered || []).filter((x) => typeof x === "string" && x.trim()).map((x) => x.trim()))]
      .map((id) => facetLabelById.get(id) ?? id)
      .slice(0, 16);
    const href = paper.doi ? `https://doi.org/${paper.doi}` : String(paper.url || "");
    const linkLabel = paper.doi ? String(paper.doi) : String(paper.url || "");

    return (
      <div className="space-y-4">
        <div className="space-y-1">
          <div className="text-xs text-muted-foreground">Titel</div>
          <div className="text-base font-semibold leading-snug">{paper.title || "(ohne Titel)"}</div>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div className="space-y-1">
            <div className="text-xs text-muted-foreground">Autoren</div>
            <div className="text-sm">{(paper.authors || []).join(", ") || "—"}</div>
          </div>
          <div className="space-y-1">
            <div className="text-xs text-muted-foreground">Venue</div>
            <div className="text-sm">{paper.venue || "—"}</div>
          </div>
        </div>

        <div className="space-y-1">
          <div className="text-xs text-muted-foreground">Abstract</div>
          <div className="text-sm text-muted-foreground whitespace-pre-wrap">{paper.abstract || "—"}</div>
        </div>

        <div className="space-y-1">
          <div className="text-xs text-muted-foreground">LLM‑Bewertung</div>
          <div className="flex items-start gap-3">
            <span className={`inline-flex items-center justify-center px-2 py-0.5 rounded-md text-xs font-semibold tabular-nums ${llmScorePillClasses(llm)}`}>
              {llm !== null ? llm : "—"}
            </span>
            <div className="text-sm text-muted-foreground whitespace-pre-wrap">{rationale || "—"}</div>
          </div>
        </div>

        <div className="space-y-1">
          <div className="text-xs text-muted-foreground">Themen</div>
          <div className="flex flex-wrap gap-2">
            {topics.length ? (
              topics.map((t) => (
                <Badge key={t} variant="outline">
                  {t}
                </Badge>
              ))
            ) : (
              <div className="text-sm text-muted-foreground">—</div>
            )}
          </div>
        </div>

        {href && linkLabel ? (
          <div>
            <Link href={href} target="_blank" rel="noreferrer" className="inline-flex items-center gap-2 text-sm text-primary hover:underline">
              <ExternalLink className="h-4 w-4" />
              {linkLabel}
            </Link>
          </div>
        ) : null}
      </div>
    );
  };

  return (
    <TooltipProvider delayDuration={150}>
      <div className="min-h-screen lg:h-screen lg:overflow-hidden bg-background flex flex-col">
        <div className="border-b border-border px-6 py-4 flex items-center gap-4">
          <Button asChild variant="ghost" size="icon">
            <Link href="/dashboard" aria-label="Back to dashboard">
              <ArrowLeft className="h-5 w-5" />
            </Link>
          </Button>
          <div className="min-w-0">
            <div className="text-lg font-semibold truncate">Quellen-Suche</div>
            <div className="text-sm text-muted-foreground truncate">Wissenschaftliche Literatur automatisch finden und bewerten</div>
          </div>
        </div>

        <div className="flex-1 min-h-0 flex flex-col lg:flex-row">
          <aside className="w-full lg:w-[320px] shrink-0 border-b lg:border-b-0 lg:border-r border-border bg-sidebar flex flex-col text-sidebar-foreground">
            <div className="p-5 border-b border-sidebar-border space-y-4 shrink-0">
              <div className="space-y-2">
                <div className="text-xs font-medium text-sidebar-foreground/70">Kapitel auswählen</div>
                <Select value={selectedKapitelId || ""} onValueChange={(v) => selectKapitel(v || null)}>
                  <SelectTrigger className="w-full h-auto min-h-10 whitespace-normal items-center py-2.5 bg-background shadow-none">
                    <div className="min-w-0 flex-1 text-left">
                      {selectedKapitel ? (
                        <div className="line-clamp-2 leading-snug">
                          <span className="text-muted-foreground tabular-nums mr-2">{selectedKapitel.nummer}</span>
                          {selectedKapitel.title}
                        </div>
                      ) : (
                        <span className="text-muted-foreground">Kapitel auswählen</span>
                      )}
                    </div>
                  </SelectTrigger>
                  <SelectContent align="start" className="max-h-[60vh] w-[var(--radix-select-trigger-width)]">
                    {kapitels.map((k) => {
                      const depth = kapitelDepth(k.nummer);
                      return (
                        <SelectItem key={k.id} value={k.id}>
                          <div className="flex items-start gap-2 min-w-0 w-full" style={{ paddingLeft: depth * 12 }}>
                            <span className="text-muted-foreground tabular-nums shrink-0">{k.nummer}</span>
                            <span className="min-w-0 leading-snug line-clamp-2">{k.title}</span>
                          </div>
                        </SelectItem>
                      );
                    })}
                  </SelectContent>
                </Select>
                {selectedKapitel ? <div className="text-xs text-sidebar-foreground/70 line-clamp-3">{selectedKapitel.thema || ""}</div> : null}
              </div>

              <Collapsible open={settingsOpen} onOpenChange={setSettingsOpen}>
                <CollapsibleTrigger asChild>
                  <button type="button" className="w-full flex items-center justify-between text-xs text-sidebar-foreground/70 hover:text-sidebar-foreground">
                    <span className="flex items-center gap-2">
                      <SlidersHorizontal className="h-4 w-4" />
                      Einstellungen
                    </span>
                    <ChevronDown className={`h-4 w-4 transition-transform ${settingsOpen ? "rotate-180" : ""}`} />
                  </button>
                </CollapsibleTrigger>
                <CollapsibleContent className="pt-3 space-y-3">
                  <div className="grid grid-cols-2 gap-3">
                    <div className="space-y-1">
                      <div className="text-xs text-muted-foreground">Planner model</div>
                      <Select value={plannerModel} onValueChange={(v) => (v === "gpt-5-nano" || v === "gpt-5-mini" || v === "gpt-5.2" ? setPlannerModel(v) : null)}>
                        <SelectTrigger className="h-9">
                          <SelectValue placeholder="Planner" />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="gpt-5-nano">gpt-5-nano</SelectItem>
                          <SelectItem value="gpt-5-mini">gpt-5-mini</SelectItem>
                          <SelectItem value="gpt-5.2">gpt-5.2</SelectItem>
                        </SelectContent>
                      </Select>
                    </div>

                    <div className="space-y-1">
                      <div className="text-xs text-muted-foreground">OpenAlex query model</div>
                      <Select
                        value={openalexQueryModel}
                        onValueChange={(v) => (v === "gpt-5-nano" || v === "gpt-5-mini" || v === "gpt-5.2" ? setOpenalexQueryModel(v) : null)}
                      >
                        <SelectTrigger className="h-9">
                          <SelectValue placeholder="OpenAlex query model" />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="gpt-5-nano">gpt-5-nano</SelectItem>
                          <SelectItem value="gpt-5-mini">gpt-5-mini</SelectItem>
                          <SelectItem value="gpt-5.2">gpt-5.2</SelectItem>
                        </SelectContent>
                      </Select>
                    </div>

                    <div className="space-y-1">
                      <div className="text-xs text-muted-foreground">S2 query model</div>
                      <Select value={s2QueryModel} onValueChange={(v) => (v === "gpt-5-nano" || v === "gpt-5-mini" || v === "gpt-5.2" ? setS2QueryModel(v) : null)}>
                        <SelectTrigger className="h-9">
                          <SelectValue placeholder="S2 query model" />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="gpt-5-nano">gpt-5-nano</SelectItem>
                          <SelectItem value="gpt-5-mini">gpt-5-mini</SelectItem>
                          <SelectItem value="gpt-5.2">gpt-5.2</SelectItem>
                        </SelectContent>
                      </Select>
                    </div>

                    <div className="space-y-1">
                      <div className="text-xs text-muted-foreground">Rerank model</div>
                      <Select value={rerankModel} onValueChange={(v) => (v === "gpt-5-nano" || v === "gpt-5-mini" ? setRerankModel(v) : null)}>
                        <SelectTrigger className="h-9">
                          <SelectValue placeholder="Rerank model" />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="gpt-5-nano">gpt-5-nano</SelectItem>
                          <SelectItem value="gpt-5-mini">gpt-5-mini</SelectItem>
                        </SelectContent>
                      </Select>
                    </div>
                  </div>

                  <div className="grid grid-cols-2 gap-3">
                    <div className="space-y-1">
                      <div className="text-xs text-muted-foreground">Reasoning effort</div>
                      <Select value={reasoningEffort} onValueChange={(v) => (v === "low" || v === "medium" || v === "high" ? setReasoningEffort(v) : null)}>
                        <SelectTrigger className="h-9">
                          <SelectValue placeholder="Effort" />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="low">low</SelectItem>
                          <SelectItem value="medium">medium</SelectItem>
                          <SelectItem value="high">high</SelectItem>
                        </SelectContent>
                      </Select>
                    </div>

                    <div className="space-y-1">
                      <div className="text-xs text-muted-foreground">Rerank concurrency</div>
                      <Input
                        className="h-9"
                        type="number"
                        value={String(rerankConcurrency)}
                        onChange={(e) => {
                          const n = Number(e.target.value);
                          if (Number.isFinite(n)) setRerankConcurrency(Math.max(1, Math.min(50, Math.floor(n))));
                        }}
                      />
                    </div>
                  </div>

                  <div className="space-y-1">
                    <div className="text-xs text-muted-foreground">Embedding model</div>
                    <Select value={embeddingModel} onValueChange={setEmbeddingModel}>
                      <SelectTrigger className="h-9">
                        <SelectValue placeholder="Embedding model" />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="text-embedding-3-small">text-embedding-3-small</SelectItem>
                        <SelectItem value="text-embedding-3-large">text-embedding-3-large</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                </CollapsibleContent>
              </Collapsible>

              <Button size="lg" onClick={startTwoLaneSources} disabled={!canRunTwoLane} className="w-full">
                <Play className="h-4 w-4" />
                Suche starten
              </Button>
            </div>

            <div className="flex-1 overflow-auto divide-y divide-sidebar-border">
              {twoLaneRuns.map((r) => {
                const snap = r.kapitelSnapshots?.[0] ?? null;
                const num = String(snap?.nummer || "").trim();
                const title = String(snap?.title || "").trim();
                const label = `${num ? `${num} ` : ""}${title || ""}`.trim() || r.id;

                const time = formatTimeHm(r.startedAt ?? r.createdAt);
                const sub =
                  r.status === "running" || r.status === "queued"
                    ? `${time}  Läuft…`
                    : r.status === "success"
                      ? `${time}  ${formatIntDe(r.resultCount ?? 0)} Ergebnisse`
                      : r.status === "cancelled"
                        ? `${time}  Abgebrochen`
                        : `${time}  Fehler`;

                const active = r.id === activeTwoLaneRun?.id;

                const icon =
                  r.status === "running" || r.status === "queued" ? (
                    <Loader2 className="h-4 w-4 animate-spin text-orange-500" />
                  ) : r.status === "success" ? (
                    <Check className="h-4 w-4 text-emerald-600" />
                  ) : r.status === "cancelled" ? (
                    <Ban className="h-4 w-4 text-muted-foreground" />
                  ) : (
                    <AlertTriangle className="h-4 w-4 text-red-600" />
                  );

                return (
                  <button
                    key={r.id}
                    type="button"
                    onClick={() => selectRun(r)}
                    className={`w-full text-left px-5 py-3 hover:bg-sidebar-accent/70 transition-colors ${active ? "bg-sidebar-accent" : ""}`}
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <div className="text-sm font-medium truncate">{label}</div>
                        <div className="text-xs text-sidebar-foreground/70 truncate">{sub}</div>
                      </div>
                      <div className="pt-0.5 shrink-0">{icon}</div>
                    </div>
                  </button>
                );
              })}
              {twoLaneRuns.length === 0 ? <div className="px-5 py-3 text-xs text-sidebar-foreground/70">Noch keine Runs.</div> : null}
            </div>
          </aside>

          <div className="flex-1 min-w-0 overflow-auto p-6">
            <div className="space-y-4 min-w-0">
            <div className="flex items-start justify-between gap-4">
              <div className="min-w-0">
                <div className="text-xl font-semibold truncate">{chapterHeading || "Kapitel auswählen"}</div>
                {activeTwoLaneRun ? (
                  <div className="text-xs text-muted-foreground">
                    Gestartet: {formatDateTimeWithSeconds(runStartedAt)}{" "}
                    {runFinishedAt ? <>| Abgeschlossen: {formatDateTimeWithSeconds(runFinishedAt)}</> : null}
                  </div>
                ) : (
                  <div className="text-xs text-muted-foreground">
                    {selectedKapitel ? "Noch keine Quellen‑Suche für dieses Kapitel. Starte links eine neue Suche." : "Wähle links ein Kapitel und starte eine neue Quellen‑Suche."}
                  </div>
                )}
              </div>

              {activeTwoLaneRun ? (
                <div className="flex items-center gap-3 flex-wrap justify-end">
                  {runningTwoLane ? (
                    <>
                      <div className="text-xs text-muted-foreground tabular-nums">
                        {formatElapsedShort(elapsedMs)} | Phase: {formatElapsedShort(stageElapsedMs)} | {formatUsd(totalCostUsd)}
                      </div>
                      <Button size="sm" variant="outline" onClick={cancelTwoLaneSources} disabled={!runningTwoLane || isCancelRequested}>
                        {isCancelRequested ? <Loader2 className="h-4 w-4 animate-spin mr-2" /> : <X className="h-4 w-4 mr-2" />}
                        {isCancelRequested ? "Wird abgebrochen…" : "Abbrechen"}
                      </Button>
                    </>
                  ) : (
                    <>
                      <div className="text-xs text-muted-foreground tabular-nums">{formatUsd(totalCostUsd)}</div>
                      {typeof resultCount === "number" ? (
                        <Badge variant="outline" className="tabular-nums">
                          {formatIntDe(resultCount)} Ergebnisse
                        </Badge>
                      ) : null}
                    </>
                  )}
                </div>
              ) : null}
            </div>

            <Card className="p-4">
              <div className="text-sm font-semibold">Pipeline-Status</div>

              <div className="mt-3 space-y-3">
                <div className="flex gap-1">
                  {TWO_LANE_PIPELINE_STEPS.map((s, idx) => {
                    const isCompleted = isDone || (activeStep >= 0 && idx < activeStep);
                    const isActive = !isDone && idx === activeStep;
                    const cls = isCompleted
                      ? "bg-primary"
                      : isActive
                        ? isError
                          ? "bg-red-500"
                          : "bg-orange-400"
                        : "bg-muted/60";
                    return (
                      <Tooltip key={s.key}>
                        <TooltipTrigger asChild>
                          <div className={`h-2 flex-1 rounded-sm ${cls}`} aria-label={s.label} />
                        </TooltipTrigger>
                        <TooltipContent side="top">{s.label}</TooltipContent>
                      </Tooltip>
                    );
                  })}
                </div>

                <div className="flex items-center justify-between gap-3">
                  <div className="flex items-center gap-2 text-xs text-muted-foreground min-w-0">
                    {isDone ? (
                      <Check className="h-4 w-4 text-emerald-600" />
                    ) : isError ? (
                      <AlertTriangle className="h-4 w-4 text-red-600" />
                    ) : isCancelled ? (
                      <Ban className="h-4 w-4 text-muted-foreground" />
                    ) : (
                      <Loader2 className="h-4 w-4 animate-spin text-orange-500" />
                    )}
                    <span className="truncate">
                      {isDone
                        ? "Abgeschlossen"
                        : isError
                          ? "Fehler"
                          : isCancelled
                            ? "Abgebrochen"
                            : isCancelRequested
                              ? "Abbruch angefordert"
                              : activeStepLabel || "Wartet…"}
                    </span>
                  </div>
                  <div className="text-xs text-muted-foreground tabular-nums shrink-0">
                    {completedSteps} / {TWO_LANE_PIPELINE_STEPS.length} Schritte
                  </div>
                </div>
              </div>

            </Card>

            <div className="flex items-center gap-3 text-xs text-muted-foreground flex-wrap">
              <Button size="sm" variant="outline" onClick={() => setTelemetryDialogOpen(true)} disabled={!activeTwoLaneRun?.id}>
                <BarChart3 className="h-4 w-4 mr-2" />
                Pipeline Details
              </Button>
              <div className="tabular-nums">
                {runningTwoLane ? formatElapsedShort(elapsedMs) : formatSecondsShort(secondsTotal ?? (runFinishedAt ? (runFinishedAt.getTime() - runStartMs) / 1000 : null))}
              </div>
              <span>|</span>
              <div className="tabular-nums">{formatUsd(totalCostUsd)}</div>
              <span>|</span>
              <div className="tabular-nums">{candidatesTotal !== null ? `${formatIntDe(candidatesTotal)} Kandidaten` : "— Kandidaten"}</div>
            </div>

            <Card className="p-4">
              <div className="space-y-3">
                <div className="text-sm font-semibold">Suchergebnisse</div>

                <Tabs
                  value={twoLaneViewKey}
                  onValueChange={(v) => {
                    if (v in TWO_LANE_VIEW_LABELS) {
                      setTwoLaneViewKey(v as TwoLaneViewKey);
                      setActivePaperDocId(null);
                    }
                  }}
                >
                  <TabsList className="h-9 bg-muted/40 p-1 flex flex-wrap">
                    {(Object.keys(TWO_LANE_VIEW_LABELS) as TwoLaneViewKey[]).map((k) => (
                      <TabsTrigger key={k} value={k} className="text-xs">
                        <span className="flex items-center gap-2">
                          {TWO_LANE_VIEW_LABELS[k]}
                          <span className="tabular-nums text-muted-foreground">{twoLaneCountsByView[k] ?? 0}</span>
                        </span>
                      </TabsTrigger>
                    ))}
                  </TabsList>
                </Tabs>

                <div className="rounded-md border border-border overflow-hidden">
                  <div className="overflow-auto">
                    <Table className="table-fixed">
                      <TableHeader>
                        <TableRow>
                          <TableHead className="w-[56px]">#</TableHead>
                          <TableHead>Titel</TableHead>
                          <TableHead className="w-[90px]">
                            <button type="button" onClick={() => toggleResultsSort("year")} className="flex items-center gap-1">
                              Jahr
                              <ChevronDown
                                className={`h-3 w-3 transition-transform ${resultsSortKey === "year" ? "opacity-100" : "opacity-30"} ${resultsSortKey === "year" && resultsSortDir === "asc" ? "rotate-180" : ""}`}
                              />
                            </button>
                          </TableHead>
                          <TableHead className="w-[120px]">
                            <button type="button" onClick={() => toggleResultsSort("citations")} className="flex items-center gap-1">
                              Zitierungen
                              <ChevronDown
                                className={`h-3 w-3 transition-transform ${resultsSortKey === "citations" ? "opacity-100" : "opacity-30"} ${resultsSortKey === "citations" && resultsSortDir === "asc" ? "rotate-180" : ""}`}
                              />
                            </button>
                          </TableHead>
                          <TableHead className="w-[90px]">
                            <button type="button" onClick={() => toggleResultsSort("llmScore")} className="flex items-center gap-1">
                              Score
                              <ChevronDown
                                className={`h-3 w-3 transition-transform ${resultsSortKey === "llmScore" ? "opacity-100" : "opacity-30"} ${resultsSortKey === "llmScore" && resultsSortDir === "asc" ? "rotate-180" : ""}`}
                              />
                            </button>
                          </TableHead>
                          <TableHead className="w-[220px]">Venue</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {twoLaneFiltered.map((r) => {
                          const llm =
                            typeof r.rerank?.llm_score_0_100 === "number" && Number.isFinite(r.rerank.llm_score_0_100)
                              ? Math.round(r.rerank.llm_score_0_100)
                              : null;
                          const rowActive = r.docId === activePaperDocId;
                          return (
                            <Fragment key={r.docId}>
                              <TableRow
                                className={`cursor-pointer ${rowActive ? "bg-muted/40" : ""}`}
                                onClick={() => setActivePaperDocId((prev) => (prev === r.docId ? null : r.docId))}
                              >
                                <TableCell className="tabular-nums">{r.rank}</TableCell>
                                <TableCell className="max-w-0">
                                  <div className="truncate font-medium">{r.title || "(ohne Titel)"}</div>
                                </TableCell>
                                <TableCell className="tabular-nums">{r.year ?? ""}</TableCell>
                                <TableCell className="tabular-nums">{typeof r.citations === "number" ? formatIntDe(r.citations) : ""}</TableCell>
                                <TableCell className="tabular-nums">
                                  <span
                                    className={`inline-flex items-center justify-center px-2 py-0.5 rounded-md text-xs font-semibold tabular-nums ${llmScorePillClasses(
                                      llm
                                    )}`}
                                  >
                                    {llm !== null ? llm : "—"}
                                  </span>
                                </TableCell>
                                <TableCell className="max-w-0">
                                  <div className="truncate text-sm text-muted-foreground">{r.venue || ""}</div>
                                </TableCell>
                              </TableRow>
                              {rowActive ? (
                                <TableRow className="bg-background">
                                  <TableCell colSpan={6} className="p-0">
                                    <div className="border-t border-border p-4 bg-background">{renderPaperDetails(r)}</div>
                                  </TableCell>
                                </TableRow>
                              ) : null}
                            </Fragment>
                          );
                        })}
                        {twoLaneFiltered.length === 0 ? (
                          <TableRow>
                            <TableCell colSpan={6} className="text-sm text-muted-foreground">
                              Keine Ergebnisse.
                            </TableCell>
                          </TableRow>
                        ) : null}
                      </TableBody>
                    </Table>
                  </div>
                </div>

              </div>
            </Card>

            <Dialog open={telemetryDialogOpen} onOpenChange={setTelemetryDialogOpen}>
                <DialogContent className="w-[80vw] max-w-[80vw] sm:max-w-[80vw] h-[80vh] max-h-[80vh] overflow-y-auto">
                  <DialogHeader>
                    <DialogTitle>Two-lane run details</DialogTitle>
                    <DialogDescription>Notebook-style telemetry (tables & plots). Updates while the run is running.</DialogDescription>
                  </DialogHeader>
                  <Tabs defaultValue="overview">
                    <TabsList className="h-8 flex flex-wrap">
                      <TabsTrigger value="overview" className="text-xs">
                        Overview
                      </TabsTrigger>
                      <TabsTrigger value="facets" className="text-xs">
                        Facets
                      </TabsTrigger>
                      <TabsTrigger value="queries" className="text-xs">
                        Queries
                      </TabsTrigger>
                      <TabsTrigger value="retrieval" className="text-xs">
                        Retrieval
                      </TabsTrigger>
                      <TabsTrigger value="candidates" className="text-xs">
                        Candidates
                      </TabsTrigger>
                      <TabsTrigger value="scoring" className="text-xs">
                        Scoring
                      </TabsTrigger>
                      <TabsTrigger value="rerank" className="text-xs">
                        Rerank
                      </TabsTrigger>
                      <TabsTrigger value="metrics" className="text-xs">
                        Metrics
                      </TabsTrigger>
                    </TabsList>

                    <TabsContent value="overview" className="mt-3">
                      <div className="space-y-4">
                        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                          <div className="rounded-md border border-border p-3">
                            <div className="text-xs text-muted-foreground">Total cost</div>
                            <div className="text-sm font-medium tabular-nums">
                              {typeof finalReportView.totalCostUsd === "number" ? `$${finalReportView.totalCostUsd.toFixed(2)}` : "—"}
                              {typeof finalReportView.budgetCapUsd === "number" ? (
                                <span className="text-xs text-muted-foreground"> / ${finalReportView.budgetCapUsd.toFixed(2)} cap</span>
                              ) : null}
                            </div>
                          </div>
                          <div className="rounded-md border border-border p-3">
                            <div className="text-xs text-muted-foreground">Key source</div>
                            <div className="text-sm font-medium">{finalReportView.keySource || "—"}</div>
                          </div>
                          <div className="rounded-md border border-border p-3">
                            <div className="text-xs text-muted-foreground">Candidates</div>
                            <div className="text-sm font-medium tabular-nums">
                              {typeof finalReportView.counts["candidates_total"] === "number" ? String(finalReportView.counts["candidates_total"]) : "—"}
                            </div>
                            <div className="text-xs text-muted-foreground">
                              OA recs:{" "}
                              <span className="tabular-nums">
                                {typeof finalReportView.counts["records_openalex"] === "number" ? String(finalReportView.counts["records_openalex"]) : "—"}
                              </span>{" "}
                              • S2 recs:{" "}
                              <span className="tabular-nums">
                                {typeof finalReportView.counts["records_semanticscholar"] === "number"
                                  ? String(finalReportView.counts["records_semanticscholar"])
                                  : "—"}
                              </span>
                            </div>
                          </div>
                        </div>

                        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                          <div className="rounded-md border border-border p-3">
                            <div className="text-sm font-medium mb-2">Models</div>
                            <div className="text-xs text-muted-foreground space-y-1">
                              <div>
                                Planner: <span className="font-medium text-foreground">{String(finalReportView.models["planner"] ?? "—")}</span>
                              </div>
                              <div>
                                OpenAlex queries:{" "}
                                <span className="font-medium text-foreground">{String(finalReportView.models["openalex_query_builder"] ?? "—")}</span>
                              </div>
                              <div>
                                S2 queries: <span className="font-medium text-foreground">{String(finalReportView.models["s2_query_builder"] ?? "—")}</span>
                              </div>
                              <div>
                                Rerank: <span className="font-medium text-foreground">{String(finalReportView.models["rerank"] ?? "—")}</span>
                              </div>
                              <div>
                                Embedding: <span className="font-medium text-foreground">{String(finalReportView.models["embedding"] ?? "—")}</span>
                              </div>
                            </div>
                          </div>

                          <div className="rounded-md border border-border p-3">
                            <div className="text-sm font-medium mb-2">Queries</div>
                            <div className="text-xs text-muted-foreground space-y-1">
                              <div>
                                OpenAlex:{" "}
                                <span className="font-medium text-foreground tabular-nums">
                                  {typeof finalReportView.counts["queries_openalex"] === "number" ? String(finalReportView.counts["queries_openalex"]) : "—"}
                                </span>
                              </div>
                              <div>
                                Semantic Scholar:{" "}
                                <span className="font-medium text-foreground tabular-nums">
                                  {typeof finalReportView.counts["queries_semanticscholar"] === "number"
                                    ? String(finalReportView.counts["queries_semanticscholar"])
                                    : "—"}
                                </span>
                              </div>
                            </div>
                          </div>
                        </div>

                        <div className="rounded-md border border-border overflow-x-auto">
                          <div className="px-3 py-2 border-b border-border">
                            <div className="text-sm font-medium">Cost & time by stage</div>
                          </div>
                          <Table>
                            <TableHeader>
                              <TableRow>
                                <TableHead>Stage</TableHead>
                                <TableHead className="w-[110px]">Cost</TableHead>
                                <TableHead className="w-[90px] hidden lg:table-cell">Requests</TableHead>
                                <TableHead className="w-[110px] hidden lg:table-cell">In tokens</TableHead>
                                <TableHead className="w-[110px] hidden lg:table-cell">Out tokens</TableHead>
                                <TableHead className="w-[110px]">Seconds</TableHead>
                              </TableRow>
                            </TableHeader>
                            <TableBody>
                              {finalReportView.stageRows.map((r) => (
                                <TableRow key={r.stage}>
                                  <TableCell className="font-mono text-xs">{r.stage}</TableCell>
                                  <TableCell className="tabular-nums">{typeof r.costUsd === "number" ? `$${r.costUsd.toFixed(4)}` : "—"}</TableCell>
                                  <TableCell className="tabular-nums hidden lg:table-cell">{typeof r.requests === "number" ? r.requests : "—"}</TableCell>
                                  <TableCell className="tabular-nums hidden lg:table-cell">{typeof r.inputTokens === "number" ? r.inputTokens : "—"}</TableCell>
                                  <TableCell className="tabular-nums hidden lg:table-cell">{typeof r.outputTokens === "number" ? r.outputTokens : "—"}</TableCell>
                                  <TableCell className="tabular-nums">{typeof r.durationS === "number" ? Math.round(r.durationS) : "—"}</TableCell>
                                </TableRow>
                              ))}
                              {finalReportView.stageRows.length === 0 ? (
                                <TableRow>
                                  <TableCell colSpan={6} className="text-sm text-muted-foreground">
                                    No stage breakdown available.
                                  </TableCell>
                                </TableRow>
                              ) : null}
                            </TableBody>
                          </Table>
                        </div>

                        <details>
                          <summary className="text-xs text-muted-foreground cursor-pointer select-none">Raw JSON</summary>
                          <pre className="mt-2 text-xs overflow-auto max-h-[45vh] whitespace-pre-wrap rounded-md border border-border p-3 bg-muted/30">
                            {JSON.stringify(finalReportView.raw ?? {}, null, 2)}
                          </pre>
                        </details>
                      </div>
                    </TabsContent>
                    <TabsContent value="facets" className="mt-3">
                      <div className="space-y-4">
                        {Object.keys(phaseBPlan).length === 0 ? (
                          <div className="text-sm text-muted-foreground">Waiting for Phase B (facets plan)…</div>
                        ) : null}

                        <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
                          <div className="rounded-md border border-border p-3">
                            <div className="text-sm font-medium mb-1">Topic summary (EN)</div>
                            <div className="text-xs text-muted-foreground whitespace-pre-wrap">
                              {typeof phaseBPlan["topic_summary_en"] === "string" && String(phaseBPlan["topic_summary_en"]).trim()
                                ? String(phaseBPlan["topic_summary_en"])
                                : "—"}
                            </div>
                          </div>
                          <div className="rounded-md border border-border p-3">
                            <div className="text-sm font-medium mb-1">Topic summary (DE)</div>
                            <div className="text-xs text-muted-foreground whitespace-pre-wrap">
                              {typeof phaseBPlan["topic_summary_de"] === "string" && String(phaseBPlan["topic_summary_de"]).trim()
                                ? String(phaseBPlan["topic_summary_de"])
                                : "—"}
                            </div>
                          </div>
                        </div>

                        <div className="grid grid-cols-1 lg:grid-cols-3 gap-3">
                          <div className="rounded-md border border-border p-3">
                            <div className="flex items-center justify-between gap-2">
                              <div className="text-sm font-medium">Primary anchors</div>
                              <Badge variant="outline" className="tabular-nums">
                                {primaryAnchorsEn.length + primaryAnchorsDe.length}
                              </Badge>
                            </div>
                            <div className="mt-2 grid grid-cols-1 md:grid-cols-2 gap-3">
                              <div className="space-y-1">
                                <div className="text-xs text-muted-foreground">EN</div>
                                <TermBadges terms={primaryAnchorsEn} />
                              </div>
                              <div className="space-y-1">
                                <div className="text-xs text-muted-foreground">DE</div>
                                <TermBadges terms={primaryAnchorsDe} />
                              </div>
                            </div>
                          </div>

                          <div className="rounded-md border border-border p-3">
                            <div className="flex items-center justify-between gap-2">
                              <div className="text-sm font-medium">Global terms</div>
                              <Badge variant="outline" className="tabular-nums">
                                {globalCanonicalTermsEn.length + globalCanonicalTermsDe.length}
                              </Badge>
                            </div>
                            <div className="mt-2 grid grid-cols-1 md:grid-cols-2 gap-3">
                              <div className="space-y-1">
                                <div className="text-xs text-muted-foreground">EN</div>
                                <TermBadges terms={globalCanonicalTermsEn} />
                              </div>
                              <div className="space-y-1">
                                <div className="text-xs text-muted-foreground">DE</div>
                                <TermBadges terms={globalCanonicalTermsDe} />
                              </div>
                            </div>
                          </div>

                          <div className="rounded-md border border-border p-3">
                            <div className="flex items-center justify-between gap-2">
                              <div className="text-sm font-medium">Global exclusions</div>
                              <Badge variant="outline" className="tabular-nums">
                                {globalExclusionsEn.length + globalExclusionsDe.length}
                              </Badge>
                            </div>
                            <div className="mt-2 grid grid-cols-1 md:grid-cols-2 gap-3">
                              <div className="space-y-1">
                                <div className="text-xs text-muted-foreground">EN</div>
                                <TermBadges terms={globalExclusionsEn} />
                              </div>
                              <div className="space-y-1">
                                <div className="text-xs text-muted-foreground">DE</div>
                                <TermBadges terms={globalExclusionsDe} />
                              </div>
                            </div>
                          </div>
                        </div>

                        <div className="rounded-md border border-border overflow-x-auto">
                          <div className="px-3 py-2 border-b border-border">
                            <div className="text-sm font-medium">Facets</div>
                            <div className="text-xs text-muted-foreground">Summary table (expand below for full details).</div>
                          </div>
                          <Table>
                            <TableHeader>
                              <TableRow>
                                <TableHead className="w-[70px]">Weight</TableHead>
                                <TableHead className="w-[160px]">Type</TableHead>
                                <TableHead className="w-[260px]">Facet</TableHead>
                                <TableHead className="min-w-[280px]">Label (EN)</TableHead>
                                <TableHead className="min-w-[280px] hidden lg:table-cell">Label (DE)</TableHead>
                              </TableRow>
                            </TableHeader>
                            <TableBody>
                              {facets.map((f, idx) => {
                                const fid = typeof f["facet_id"] === "string" ? String(f["facet_id"]) : "";
                                const weight = asIntOrNull(f["importance_weight"]);
                                const typ = typeof f["facet_type"] === "string" ? String(f["facet_type"]) : "";
                                const labelEn = typeof f["facet_label_en"] === "string" ? String(f["facet_label_en"]) : "";
                                const labelDe = typeof f["facet_label_de"] === "string" ? String(f["facet_label_de"]) : "";
                                return (
                                  <TableRow key={fid || `${idx}`}>
                                    <TableCell className="tabular-nums">{typeof weight === "number" ? weight : "—"}</TableCell>
                                    <TableCell className="text-xs">{typ || "—"}</TableCell>
                                    <TableCell className="font-mono text-xs">{fid || "—"}</TableCell>
                                    <TableCell className="text-xs">{labelEn || "—"}</TableCell>
                                    <TableCell className="text-xs hidden lg:table-cell">{labelDe || "—"}</TableCell>
                                  </TableRow>
                                );
                              })}
                              {facets.length === 0 ? (
                                <TableRow>
                                  <TableCell colSpan={5} className="text-sm text-muted-foreground">
                                    No facets available yet.
                                  </TableCell>
                                </TableRow>
                              ) : null}
                            </TableBody>
                          </Table>
                        </div>

                        <div className="space-y-2">
                          {facets.map((f, idx) => {
                            const fid = typeof f["facet_id"] === "string" ? String(f["facet_id"]) : "";
                            const weight = asIntOrNull(f["importance_weight"]);
                            const typ = typeof f["facet_type"] === "string" ? String(f["facet_type"]) : "";
                            const labelEn = typeof f["facet_label_en"] === "string" ? String(f["facet_label_en"]) : "";
                            const labelDe = typeof f["facet_label_de"] === "string" ? String(f["facet_label_de"]) : "";
                            const textEn = typeof f["text_en"] === "string" ? String(f["text_en"]) : "";
                            const textDe = typeof f["text_de"] === "string" ? String(f["text_de"]) : "";

                            const canonical = asRecord(f["canonical_terms"]);
                            const neighbors = asRecord(f["neighbor_terms"]);
                            const exclusions = asRecord(f["exclusion_terms"]);
                            const canonicalEn = asStringArray(canonical["en"]);
                            const canonicalDe = asStringArray(canonical["de"]);
                            const neighborsEn = asStringArray(neighbors["en"]);
                            const neighborsDe = asStringArray(neighbors["de"]);
                            const exclusionsEn = asStringArray(exclusions["en"]);
                            const exclusionsDe = asStringArray(exclusions["de"]);

                            return (
                              <details key={fid || `${idx}`} className="rounded-md border border-border p-3">
                                <summary className="cursor-pointer select-none">
                                  <div className="flex items-start gap-2">
                                    <Badge variant="secondary" className="tabular-nums">
                                      {typeof weight === "number" ? weight : "—"}
                                    </Badge>
                                    <div className="min-w-0">
                                      <div className="text-sm font-medium">{labelEn || fid || "(facet)"}</div>
                                      <div className="text-xs text-muted-foreground line-clamp-1">
                                        {typ || "—"}
                                        {fid ? ` • ${fid}` : ""}
                                        {labelDe ? ` • ${labelDe}` : ""}
                                      </div>
                                    </div>
                                  </div>
                                </summary>

                                <div className="mt-3 space-y-3">
                                  <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
                                    <div className="rounded-md border border-border p-3 bg-muted/20">
                                      <div className="text-xs text-muted-foreground">Text (EN)</div>
                                      <div className="text-xs whitespace-pre-wrap">{textEn || "—"}</div>
                                    </div>
                                    <div className="rounded-md border border-border p-3 bg-muted/20">
                                      <div className="text-xs text-muted-foreground">Text (DE)</div>
                                      <div className="text-xs whitespace-pre-wrap">{textDe || "—"}</div>
                                    </div>
                                  </div>

                                  <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
                                    <div className="rounded-md border border-border p-3">
                                      <div className="text-sm font-medium mb-2">Terms (EN)</div>
                                      <div className="space-y-3">
                                        <div className="space-y-1">
                                          <div className="text-xs text-muted-foreground">Canonical</div>
                                          <TermBadges terms={canonicalEn} max={18} />
                                        </div>
                                        <div className="space-y-1">
                                          <div className="text-xs text-muted-foreground">Neighbors</div>
                                          <TermBadges terms={neighborsEn} max={18} />
                                        </div>
                                        <div className="space-y-1">
                                          <div className="text-xs text-muted-foreground">Exclusions</div>
                                          <TermBadges terms={exclusionsEn} max={18} />
                                        </div>
                                      </div>
                                    </div>

                                    <div className="rounded-md border border-border p-3">
                                      <div className="text-sm font-medium mb-2">Terms (DE)</div>
                                      <div className="space-y-3">
                                        <div className="space-y-1">
                                          <div className="text-xs text-muted-foreground">Canonical</div>
                                          <TermBadges terms={canonicalDe} max={18} />
                                        </div>
                                        <div className="space-y-1">
                                          <div className="text-xs text-muted-foreground">Neighbors</div>
                                          <TermBadges terms={neighborsDe} max={18} />
                                        </div>
                                        <div className="space-y-1">
                                          <div className="text-xs text-muted-foreground">Exclusions</div>
                                          <TermBadges terms={exclusionsDe} max={18} />
                                        </div>
                                      </div>
                                    </div>
                                  </div>
                                </div>
                              </details>
                            );
                          })}
                          {facets.length === 0 ? <div className="text-sm text-muted-foreground">No facet details yet.</div> : null}
                        </div>

                        <details>
                          <summary className="text-xs text-muted-foreground cursor-pointer select-none">Raw JSON</summary>
                          <pre className="mt-2 text-xs overflow-auto max-h-[45vh] whitespace-pre-wrap rounded-md border border-border p-3 bg-muted/30">
                            {JSON.stringify(phaseBPlan ?? {}, null, 2)}
                          </pre>
                        </details>
                      </div>
                    </TabsContent>
                    <TabsContent value="queries" className="mt-3">
                      <div className="space-y-4">
                        {Object.keys(phaseCQueries).length === 0 ? (
                          <div className="text-sm text-muted-foreground">Waiting for Phase C (queries)…</div>
                        ) : null}

                        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                          <div className="rounded-md border border-border p-3">
                            <div className="flex items-center justify-between gap-2">
                              <div className="text-sm font-medium">OpenAlex query length</div>
                              <Badge variant="outline" className="tabular-nums">
                                {openalexQueries.length}
                              </Badge>
                            </div>
                            <div className="mt-2">
                              <HistogramBars hist={openalexQueryLenHist} height={110} />
                            </div>
                          </div>

                          <div className="rounded-md border border-border p-3">
                            <div className="flex items-center justify-between gap-2">
                              <div className="text-sm font-medium">Semantic Scholar query length</div>
                              <Badge variant="outline" className="tabular-nums">
                                {s2BulkQueries.length}
                              </Badge>
                            </div>
                            <div className="mt-2">
                              <HistogramBars hist={s2QueryLenHist} height={110} />
                            </div>
                          </div>
                        </div>

                        <div className="rounded-md border border-border overflow-x-auto">
                          <div className="px-3 py-2 border-b border-border">
                            <div className="text-sm font-medium">OpenAlex queries</div>
                          </div>
                          <Table>
                            <TableHeader>
                              <TableRow>
                                <TableHead className="w-[64px]">#</TableHead>
                                <TableHead className="w-[120px]">Intent/lang</TableHead>
                                <TableHead className="min-w-[520px]">Query</TableHead>
                                <TableHead className="min-w-[280px] hidden lg:table-cell">Notes</TableHead>
                              </TableRow>
                            </TableHeader>
                            <TableBody>
                              {openalexQueries.map((q, i) => {
                                const intent = typeof q["intent"] === "string" ? String(q["intent"]) : "unknown";
                                const lang = typeof q["language"] === "string" ? String(q["language"]) : "unknown";
                                const qs = typeof q["query_string"] === "string" ? String(q["query_string"]) : "";
                                const notes = typeof q["notes"] === "string" ? String(q["notes"]) : "";
                                const searchField = typeof q["search_field"] === "string" ? String(q["search_field"]) : "";
                                const filters = typeof q["filters"] === "string" ? String(q["filters"]) : "";
                                const sort = typeof q["sort"] === "string" ? String(q["sort"]) : "";
                                const perPage = asIntOrNull(q["per_page"]);
                                return (
                                  <TableRow key={`${intent}-${lang}-${i}`}>
                                    <TableCell className="tabular-nums">{i + 1}</TableCell>
                                    <TableCell className="text-xs">
                                      <Badge variant="outline" className="mr-1">
                                        {intent}
                                      </Badge>
                                      <Badge variant="secondary">{lang}</Badge>
                                    </TableCell>
                                    <TableCell className="text-xs">
                                      <div className="whitespace-pre-wrap">{qs || "—"}</div>
                                      <div className="mt-1 text-[10px] font-mono text-muted-foreground line-clamp-1">
                                        {searchField || "default.search"}
                                        {filters ? ` • ${filters}` : ""}
                                        {sort ? ` • ${sort}` : ""}
                                        {typeof perPage === "number" ? ` • per_page=${perPage}` : ""}
                                      </div>
                                    </TableCell>
                                    <TableCell className="text-xs text-muted-foreground hidden lg:table-cell">{notes || "—"}</TableCell>
                                  </TableRow>
                                );
                              })}
                              {openalexQueries.length === 0 ? (
                                <TableRow>
                                  <TableCell colSpan={4} className="text-sm text-muted-foreground">
                                    No OpenAlex queries yet.
                                  </TableCell>
                                </TableRow>
                              ) : null}
                            </TableBody>
                          </Table>
                        </div>

                        <div className="rounded-md border border-border overflow-x-auto">
                          <div className="px-3 py-2 border-b border-border">
                            <div className="text-sm font-medium">Semantic Scholar bulk queries</div>
                          </div>
                          <Table>
                            <TableHeader>
                              <TableRow>
                                <TableHead className="w-[64px]">#</TableHead>
                                <TableHead className="w-[120px]">Intent/lang</TableHead>
                                <TableHead className="min-w-[520px]">Query</TableHead>
                                <TableHead className="min-w-[280px] hidden lg:table-cell">Notes</TableHead>
                              </TableRow>
                            </TableHeader>
                            <TableBody>
                              {s2BulkQueries.map((q, i) => {
                                const intent = typeof q["intent"] === "string" ? String(q["intent"]) : "unknown";
                                const lang = typeof q["language"] === "string" ? String(q["language"]) : "unknown";
                                const qs = typeof q["query_string"] === "string" ? String(q["query_string"]) : "";
                                const notes = typeof q["notes"] === "string" ? String(q["notes"]) : "";
                                return (
                                  <TableRow key={`${intent}-${lang}-${i}`}>
                                    <TableCell className="tabular-nums">{i + 1}</TableCell>
                                    <TableCell className="text-xs">
                                      <Badge variant="outline" className="mr-1">
                                        {intent}
                                      </Badge>
                                      <Badge variant="secondary">{lang}</Badge>
                                    </TableCell>
                                    <TableCell className="text-xs whitespace-pre-wrap">{qs || "—"}</TableCell>
                                    <TableCell className="text-xs text-muted-foreground hidden lg:table-cell">{notes || "—"}</TableCell>
                                  </TableRow>
                                );
                              })}
                              {s2BulkQueries.length === 0 ? (
                                <TableRow>
                                  <TableCell colSpan={4} className="text-sm text-muted-foreground">
                                    No Semantic Scholar queries yet.
                                  </TableCell>
                                </TableRow>
                              ) : null}
                            </TableBody>
                          </Table>
                        </div>

                        <details>
                          <summary className="text-xs text-muted-foreground cursor-pointer select-none">Raw JSON</summary>
                          <pre className="mt-2 text-xs overflow-auto max-h-[45vh] whitespace-pre-wrap rounded-md border border-border p-3 bg-muted/30">
                            {JSON.stringify(phaseCQueries ?? {}, null, 2)}
                          </pre>
                        </details>
                      </div>
                    </TabsContent>
                    <TabsContent value="retrieval" className="mt-3">
                      {(() => {
                        const oa = asRecord(phaseDRetrieval["openalex"]);
                        const s2 = asRecord(phaseDRetrieval["semanticscholar"]);

                        const buildProvider = (
                          provider: "openalex" | "semanticscholar",
                          label: string,
                          qs: Record<string, unknown>[]
                        ): {
                          label: string;
                          total: number;
                          queryRows: { qid: string; intent: string; lang: string; records: number; share: number | null; queryString: string; notes: string }[];
                          byIntentLang: { key: string; records: number }[];
                          years: { label: string; value: number }[];
                          zeroIds: string[];
                          fetchMeta: { queryFailed: number | null; recordsFetched: number | null };
                          stats: { mean: number | null; median: number | null; p90: number | null; max: number | null };
                        } => {
                          const rec = provider === "openalex" ? oa : s2;
                          const total = asIntOrNull(rec["records_total"]) ?? 0;
                          const byQuery = asRecord(rec["records_by_query_id"]);
                          const byIntentLangRec = asRecord(rec["records_by_intent_lang"]);
                          const byYearRec = asRecord(rec["records_by_year"]);
                          const zeroIds = asStringArray(rec["zero_result_query_ids"]);
                          const fetchMetaRec = asRecord(rec["fetch_meta"]);
                          const queryFailed = asIntOrNull(fetchMetaRec["query_failed"]);
                          const recordsFetched = asIntOrNull(fetchMetaRec["records_fetched"]);

                          const queryRows = qs.map((q, idx0) => {
                            const intent = typeof q["intent"] === "string" ? String(q["intent"]) : "unknown";
                            const lang = typeof q["language"] === "string" ? String(q["language"]) : "unknown";
                            const qid = `${provider}:${idx0 + 1}:${intent}:${lang}`;
                            const records = asIntOrNull(byQuery[qid]) ?? 0;
                            const share = total > 0 ? records / total : null;
                            const queryString = typeof q["query_string"] === "string" ? String(q["query_string"]) : "";
                            const notes = typeof q["notes"] === "string" ? String(q["notes"]) : "";
                            return { qid, intent, lang, records, share, queryString, notes };
                          });

                          const byIntentLang = Object.entries(byIntentLangRec)
                            .map(([k, v]) => ({ key: String(k), records: asIntOrNull(v) ?? 0 }))
                            .filter((r) => r.records > 0)
                            .sort((a, b) => b.records - a.records);

                          const years = Object.entries(byYearRec)
                            .map(([k, v]) => ({ year: Number(k), value: asIntOrNull(v) ?? 0 }))
                            .filter((r) => Number.isFinite(r.year) && r.value > 0)
                            .sort((a, b) => a.year - b.year)
                            .map((r) => ({ label: String(r.year), value: r.value }));

                          const stats = summarizeCounts(queryRows.map((r) => r.records));

                          return { label, total, queryRows, byIntentLang, years, zeroIds, fetchMeta: { queryFailed, recordsFetched }, stats };
                        };

                        const oaView = buildProvider("openalex", "OpenAlex", openalexQueries);
                        const s2View = buildProvider("semanticscholar", "Semantic Scholar", s2BulkQueries);

                        const ProviderBlock = ({
                          view,
                        }: {
                          view: {
                            label: string;
                            total: number;
                            queryRows: { qid: string; intent: string; lang: string; records: number; share: number | null; queryString: string; notes: string }[];
                            byIntentLang: { key: string; records: number }[];
                            years: { label: string; value: number }[];
                            zeroIds: string[];
                            fetchMeta: { queryFailed: number | null; recordsFetched: number | null };
                            stats: { mean: number | null; median: number | null; p90: number | null; max: number | null };
                          };
                        }) => {
                          const queryCount = view.queryRows.length;
                          const zeroCount = view.zeroIds.length;
                          const dominance = view.total > 0 ? ((view.stats.max ?? 0) / view.total) * 100 : null;
                          const broad = [...view.queryRows].sort((a, b) => b.records - a.records).slice(0, 12);
                          const narrow = [...view.queryRows].sort((a, b) => a.records - b.records).slice(0, 12);
                          const yearsTail = view.years.length > 80 ? view.years.slice(-80) : view.years;

                          return (
                            <div className="space-y-4">
                              <div className="flex items-center gap-2">
                                <Badge variant="outline">{view.label}</Badge>
                                <span className="text-xs text-muted-foreground tabular-nums">{view.total} records</span>
                              </div>

                              <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
                                <div className="rounded-md border border-border p-3">
                                  <div className="text-xs text-muted-foreground">Queries</div>
                                  <div className="text-sm font-medium tabular-nums">{queryCount}</div>
                                </div>
                                <div className="rounded-md border border-border p-3">
                                  <div className="text-xs text-muted-foreground">Zero queries</div>
                                  <div className="text-sm font-medium tabular-nums">{zeroCount}</div>
                                  {queryCount ? (
                                    <div className="text-[10px] text-muted-foreground tabular-nums">{((zeroCount / queryCount) * 100).toFixed(1)}%</div>
                                  ) : null}
                                </div>
                                <div className="rounded-md border border-border p-3">
                                  <div className="text-xs text-muted-foreground">Records/query</div>
                                  <div className="text-sm font-medium tabular-nums">
                                    {view.stats.mean !== null ? view.stats.mean.toFixed(1) : "—"}
                                  </div>
                                  <div className="text-[10px] text-muted-foreground tabular-nums">
                                    median {view.stats.median !== null ? view.stats.median.toFixed(0) : "—"} • p90{" "}
                                    {view.stats.p90 !== null ? view.stats.p90.toFixed(0) : "—"} • max{" "}
                                    {view.stats.max !== null ? view.stats.max.toFixed(0) : "—"}
                                  </div>
                                </div>
                                <div className="rounded-md border border-border p-3">
                                  <div className="text-xs text-muted-foreground">Dominance</div>
                                  <div className="text-sm font-medium tabular-nums">{dominance !== null ? `${dominance.toFixed(1)}%` : "—"}</div>
                                  <div className="text-[10px] text-muted-foreground">
                                    failed {view.fetchMeta.queryFailed ?? "—"} • fetched {view.fetchMeta.recordsFetched ?? "—"}
                                  </div>
                                </div>
                              </div>

                              <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
                                <div className="rounded-md border border-border overflow-x-auto">
                                  <div className="px-3 py-2 border-b border-border">
                                    <div className="text-sm font-medium">Records by intent/lang</div>
                                  </div>
                                  <Table>
                                    <TableHeader>
                                      <TableRow>
                                        <TableHead>Intent/lang</TableHead>
                                        <TableHead className="w-[120px]">Records</TableHead>
                                      </TableRow>
                                    </TableHeader>
                                    <TableBody>
                                      {view.byIntentLang.map((r) => (
                                        <TableRow key={r.key}>
                                          <TableCell className="font-mono text-xs">{r.key}</TableCell>
                                          <TableCell className="tabular-nums">{r.records}</TableCell>
                                        </TableRow>
                                      ))}
                                      {view.byIntentLang.length === 0 ? (
                                        <TableRow>
                                          <TableCell colSpan={2} className="text-sm text-muted-foreground">
                                            No records yet.
                                          </TableCell>
                                        </TableRow>
                                      ) : null}
                                    </TableBody>
                                  </Table>
                                </div>

                                <div className="rounded-md border border-border p-3">
                                  <div className="text-sm font-medium mb-2">Records by year</div>
                                  <BarList rows={yearsTail} maxRows={5000} />
                                  {view.years.length > yearsTail.length ? (
                                    <details className="mt-2">
                                      <summary className="text-xs text-muted-foreground cursor-pointer select-none">
                                        Show full distribution ({view.years.length} years)
                                      </summary>
                                      <div className="mt-2">
                                        <BarList rows={view.years} maxRows={5000} />
                                      </div>
                                    </details>
                                  ) : null}
                                </div>
                              </div>

                              <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
                                <div className="rounded-md border border-border overflow-x-auto">
                                  <div className="px-3 py-2 border-b border-border">
                                    <div className="text-sm font-medium">Broad queries (top by records)</div>
                                  </div>
                                  <Table>
                                    <TableHeader>
                                      <TableRow>
                                        <TableHead className="w-[64px]">#</TableHead>
                                        <TableHead className="w-[120px]">Intent/lang</TableHead>
                                        <TableHead className="w-[120px]">Records</TableHead>
                                        <TableHead>Query</TableHead>
                                      </TableRow>
                                    </TableHeader>
                                    <TableBody>
                                      {broad.map((r, i) => (
                                        <TableRow key={r.qid}>
                                          <TableCell className="tabular-nums">{i + 1}</TableCell>
                                          <TableCell className="text-xs">
                                            <Badge variant="outline" className="mr-1">
                                              {r.intent}
                                            </Badge>
                                            <Badge variant="secondary">{r.lang}</Badge>
                                          </TableCell>
                                          <TableCell className="tabular-nums">
                                            {r.records}
                                            {r.share !== null ? <span className="text-[10px] text-muted-foreground"> ({(r.share * 100).toFixed(1)}%)</span> : null}
                                          </TableCell>
                                          <TableCell className="text-xs">
                                            <div className="whitespace-pre-wrap line-clamp-2">{r.queryString || "—"}</div>
                                            {r.notes ? <div className="text-[10px] text-muted-foreground line-clamp-1">{r.notes}</div> : null}
                                          </TableCell>
                                        </TableRow>
                                      ))}
                                      {broad.length === 0 ? (
                                        <TableRow>
                                          <TableCell colSpan={4} className="text-sm text-muted-foreground">
                                            No query stats yet.
                                          </TableCell>
                                        </TableRow>
                                      ) : null}
                                    </TableBody>
                                  </Table>
                                </div>

                                <div className="rounded-md border border-border overflow-x-auto">
                                  <div className="px-3 py-2 border-b border-border">
                                    <div className="text-sm font-medium">Narrow queries (bottom by records)</div>
                                  </div>
                                  <Table>
                                    <TableHeader>
                                      <TableRow>
                                        <TableHead className="w-[64px]">#</TableHead>
                                        <TableHead className="w-[120px]">Intent/lang</TableHead>
                                        <TableHead className="w-[120px]">Records</TableHead>
                                        <TableHead>Query</TableHead>
                                      </TableRow>
                                    </TableHeader>
                                    <TableBody>
                                      {narrow.map((r, i) => (
                                        <TableRow key={r.qid}>
                                          <TableCell className="tabular-nums">{i + 1}</TableCell>
                                          <TableCell className="text-xs">
                                            <Badge variant="outline" className="mr-1">
                                              {r.intent}
                                            </Badge>
                                            <Badge variant="secondary">{r.lang}</Badge>
                                          </TableCell>
                                          <TableCell className="tabular-nums">
                                            {r.records}
                                            {r.share !== null ? <span className="text-[10px] text-muted-foreground"> ({(r.share * 100).toFixed(1)}%)</span> : null}
                                          </TableCell>
                                          <TableCell className="text-xs">
                                            <div className="whitespace-pre-wrap line-clamp-2">{r.queryString || "—"}</div>
                                            {r.notes ? <div className="text-[10px] text-muted-foreground line-clamp-1">{r.notes}</div> : null}
                                          </TableCell>
                                        </TableRow>
                                      ))}
                                      {narrow.length === 0 ? (
                                        <TableRow>
                                          <TableCell colSpan={4} className="text-sm text-muted-foreground">
                                            No query stats yet.
                                          </TableCell>
                                        </TableRow>
                                      ) : null}
                                    </TableBody>
                                  </Table>
                                </div>
                              </div>

                              {view.zeroIds.length ? (
                                <details>
                                  <summary className="text-xs text-muted-foreground cursor-pointer select-none">Zero-result query ids ({view.zeroIds.length})</summary>
                                  <pre className="mt-2 text-xs overflow-auto max-h-[30vh] whitespace-pre-wrap rounded-md border border-border p-3 bg-muted/30">
                                    {view.zeroIds.join("\n")}
                                  </pre>
                                </details>
                              ) : null}
                            </div>
                          );
                        };

                        return (
                          <div className="space-y-6">
                            {Object.keys(phaseDRetrieval).length === 0 ? (
                              <div className="text-sm text-muted-foreground">Waiting for Phase D (retrieval)…</div>
                            ) : null}
                            <ProviderBlock view={oaView} />
                            <Separator />
                            <ProviderBlock view={s2View} />

                            <details>
                              <summary className="text-xs text-muted-foreground cursor-pointer select-none">Raw JSON</summary>
                              <pre className="mt-2 text-xs overflow-auto max-h-[45vh] whitespace-pre-wrap rounded-md border border-border p-3 bg-muted/30">
                                {JSON.stringify(phaseDRetrieval ?? {}, null, 2)}
                              </pre>
                            </details>
                          </div>
                        );
                      })()}
                    </TabsContent>
                    <TabsContent value="candidates" className="mt-3">
                      {(() => {
                        const counts = asRecord(phaseECandidates["counts"]);
                        const byLanePool = asRecord(counts["by_lane_pool"]);
                        const poolCounts = asRecord(counts["pool"]);
                        const total = asIntOrNull(counts["candidates_total"]);
                        const doiPresent = asIntOrNull(counts["doi_present"]);
                        const yearMissing = asIntOrNull(counts["year_missing"]);

                        const byLanePoolRows = Object.entries(byLanePool)
                          .map(([k, v]) => ({ key: String(k), count: asIntOrNull(v) ?? 0 }))
                          .sort((a, b) => b.count - a.count);

                        const topNoAnchors = asRecordArray(phaseECandidates["top_cited_no_anchors"]);
                        const topEcon = asRecordArray(phaseECandidates["top_econ_hit"]);

                        return (
                          <div className="space-y-4">
                            {Object.keys(phaseECandidates).length === 0 ? (
                              <div className="text-sm text-muted-foreground">Waiting for Phase E (candidates)…</div>
                            ) : null}

                            <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
                              <div className="rounded-md border border-border p-3">
                                <div className="text-xs text-muted-foreground">Candidates</div>
                                <div className="text-sm font-medium tabular-nums">{typeof total === "number" ? total : "—"}</div>
                              </div>
                              <div className="rounded-md border border-border p-3">
                                <div className="text-xs text-muted-foreground">Pools</div>
                                <div className="text-xs text-muted-foreground space-y-1 mt-1">
                                  {Object.entries(poolCounts).map(([k, v]) => (
                                    <div key={k} className="flex items-center justify-between gap-2">
                                      <span className="font-mono text-[10px]">{k}</span>
                                      <span className="tabular-nums">{asIntOrNull(v) ?? 0}</span>
                                    </div>
                                  ))}
                                </div>
                              </div>
                              <div className="rounded-md border border-border p-3">
                                <div className="text-xs text-muted-foreground">DOI present</div>
                                <div className="text-sm font-medium tabular-nums">{typeof doiPresent === "number" ? doiPresent : "—"}</div>
                              </div>
                              <div className="rounded-md border border-border p-3">
                                <div className="text-xs text-muted-foreground">Year missing</div>
                                <div className="text-sm font-medium tabular-nums">{typeof yearMissing === "number" ? yearMissing : "—"}</div>
                              </div>
                            </div>

                            <div className="rounded-md border border-border overflow-x-auto">
                              <div className="px-3 py-2 border-b border-border">
                                <div className="text-sm font-medium">Counts by lane/pool</div>
                              </div>
                              <Table>
                                <TableHeader>
                                  <TableRow>
                                    <TableHead>Lane/pool</TableHead>
                                    <TableHead className="w-[120px]">Count</TableHead>
                                  </TableRow>
                                </TableHeader>
                                <TableBody>
                                  {byLanePoolRows.map((r) => (
                                    <TableRow key={r.key}>
                                      <TableCell className="font-mono text-xs">{r.key}</TableCell>
                                      <TableCell className="tabular-nums">{r.count}</TableCell>
                                    </TableRow>
                                  ))}
                                  {byLanePoolRows.length === 0 ? (
                                    <TableRow>
                                      <TableCell colSpan={2} className="text-sm text-muted-foreground">
                                        No lane/pool counts yet.
                                      </TableCell>
                                    </TableRow>
                                  ) : null}
                                </TableBody>
                              </Table>
                            </div>

                            <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
                              <div className="rounded-md border border-border overflow-x-auto">
                                <div className="px-3 py-2 border-b border-border">
                                  <div className="text-sm font-medium">Top cited but NO anchors</div>
                                </div>
                                <Table>
                                  <TableHeader>
                                    <TableRow>
                                      <TableHead className="w-[90px]">Cites</TableHead>
                                      <TableHead className="w-[80px]">Year</TableHead>
                                      <TableHead className="w-[140px]">Pool</TableHead>
                                      <TableHead>Title</TableHead>
                                    </TableRow>
                                  </TableHeader>
                                  <TableBody>
                                    {topNoAnchors.map((r, idx) => {
                                      const id = typeof r["id"] === "string" ? String(r["id"]) : "";
                                      const cites = asIntOrNull(r["citations"]);
                                      const year = asIntOrNull(r["year"]);
                                      const pool = typeof r["pool"] === "string" ? String(r["pool"]) : "";
                                      const title = typeof r["title"] === "string" ? String(r["title"]) : "";
                                      return (
                                        <TableRow key={id || `${idx}`}>
                                          <TableCell className="tabular-nums">{typeof cites === "number" ? cites : "—"}</TableCell>
                                          <TableCell className="tabular-nums">{typeof year === "number" ? year : "—"}</TableCell>
                                          <TableCell className="text-xs font-mono">{pool || "—"}</TableCell>
                                          <TableCell className="text-xs">
                                            <div className="line-clamp-2">{title || id || "—"}</div>
                                          </TableCell>
                                        </TableRow>
                                      );
                                    })}
                                    {topNoAnchors.length === 0 ? (
                                      <TableRow>
                                        <TableCell colSpan={4} className="text-sm text-muted-foreground">
                                          No rows yet.
                                        </TableCell>
                                      </TableRow>
                                    ) : null}
                                  </TableBody>
                                </Table>
                              </div>

                              <div className="rounded-md border border-border overflow-x-auto">
                                <div className="px-3 py-2 border-b border-border">
                                  <div className="text-sm font-medium">Top econ-hit candidates</div>
                                </div>
                                <Table>
                                  <TableHeader>
                                    <TableRow>
                                      <TableHead className="w-[90px]">Hits</TableHead>
                                      <TableHead className="w-[90px]">Cites</TableHead>
                                      <TableHead className="w-[80px]">Year</TableHead>
                                      <TableHead className="w-[140px]">Pool</TableHead>
                                      <TableHead>Title</TableHead>
                                    </TableRow>
                                  </TableHeader>
                                  <TableBody>
                                    {topEcon.map((r, idx) => {
                                      const id = typeof r["id"] === "string" ? String(r["id"]) : "";
                                      const hits = asIntOrNull(r["econ_hits"]);
                                      const cites = asIntOrNull(r["citations"]);
                                      const year = asIntOrNull(r["year"]);
                                      const pool = typeof r["pool"] === "string" ? String(r["pool"]) : "";
                                      const title = typeof r["title"] === "string" ? String(r["title"]) : "";
                                      const anchorHit = Boolean(r["anchor_hit"]);
                                      return (
                                        <TableRow key={id || `${idx}`}>
                                          <TableCell className="tabular-nums">{typeof hits === "number" ? hits : "—"}</TableCell>
                                          <TableCell className="tabular-nums">{typeof cites === "number" ? cites : "—"}</TableCell>
                                          <TableCell className="tabular-nums">{typeof year === "number" ? year : "—"}</TableCell>
                                          <TableCell className="text-xs font-mono">
                                            {pool || "—"}
                                            {anchorHit ? (
                                              <Badge variant="outline" className="ml-2">
                                                anchor
                                              </Badge>
                                            ) : null}
                                          </TableCell>
                                          <TableCell className="text-xs">
                                            <div className="line-clamp-2">{title || id || "—"}</div>
                                          </TableCell>
                                        </TableRow>
                                      );
                                    })}
                                    {topEcon.length === 0 ? (
                                      <TableRow>
                                        <TableCell colSpan={5} className="text-sm text-muted-foreground">
                                          No rows yet.
                                        </TableCell>
                                      </TableRow>
                                    ) : null}
                                  </TableBody>
                                </Table>
                              </div>
                            </div>

                            <details>
                              <summary className="text-xs text-muted-foreground cursor-pointer select-none">Raw JSON</summary>
                              <pre className="mt-2 text-xs overflow-auto max-h-[45vh] whitespace-pre-wrap rounded-md border border-border p-3 bg-muted/30">
                                {JSON.stringify(phaseECandidates ?? {}, null, 2)}
                              </pre>
                            </details>
                          </div>
                        );
                      })()}
                    </TabsContent>
                    <TabsContent value="scoring" className="mt-3">
                      {(() => {
                        const counts = asRecord(phaseFScoring["counts"]);
                        const anchorRate = asRecord(phaseFScoring["anchor_hit_rate_top20"]);
                        const dist = asRecord(phaseFScoring["distributions"]);
                        const matchDist = asRecord(dist["match_lane"]);
                        const authDist = asRecord(dist["authority_lane"]);

                        const candidates = asIntOrNull(counts["candidates"]);
                        const facetsN = asIntOrNull(counts["facets"]);
                        const stage2Candidates = asIntOrNull(counts["stage2_candidates"]);

                        const prune = asRecord(counts["prune"]);
                        const kept = asRecord(prune["kept"]);
                        const keptMatch = asRecord(kept["match"]);
                        const keptAuthority = asRecord(kept["authority"]);
                        const keptRows = [
                          { lane: "match", pool: "with_abstract", n: asIntOrNull(keptMatch["with_abstract"]) ?? 0 },
                          { lane: "match", pool: "without_abstract", n: asIntOrNull(keptMatch["without_abstract"]) ?? 0 },
                          { lane: "authority", pool: "with_abstract", n: asIntOrNull(keptAuthority["with_abstract"]) ?? 0 },
                          { lane: "authority", pool: "without_abstract", n: asIntOrNull(keptAuthority["without_abstract"]) ?? 0 },
                        ];

                        const anchorRows = Object.entries(anchorRate)
                          .map(([k, v]) => {
                            const rec = asRecord(v);
                            const topN = asIntOrNull(rec["top_n"]) ?? 0;
                            const hits = asIntOrNull(rec["anchor_hits"]) ?? 0;
                            const [lane, pool] = String(k).split("/", 2);
                            const rate = topN > 0 ? hits / topN : null;
                            return { key: String(k), lane, pool, topN, hits, rate };
                          })
                          .sort((a, b) => a.key.localeCompare(b.key));

                        return (
                          <div className="space-y-4">
                            {Object.keys(phaseFScoring).length === 0 ? (
                              <div className="text-sm text-muted-foreground">Waiting for Phase F (scoring)…</div>
                            ) : null}

                            <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                              <div className="rounded-md border border-border p-3">
                                <div className="text-xs text-muted-foreground">Candidates</div>
                                <div className="text-sm font-medium tabular-nums">{typeof candidates === "number" ? candidates : "—"}</div>
                              </div>
                              <div className="rounded-md border border-border p-3">
                                <div className="text-xs text-muted-foreground">Facets</div>
                                <div className="text-sm font-medium tabular-nums">{typeof facetsN === "number" ? facetsN : "—"}</div>
                              </div>
                              <div className="rounded-md border border-border p-3">
                                <div className="text-xs text-muted-foreground">Stage2 candidates</div>
                                <div className="text-sm font-medium tabular-nums">{typeof stage2Candidates === "number" ? stage2Candidates : "—"}</div>
                              </div>
                            </div>

                            <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
                              <div className="rounded-md border border-border overflow-x-auto">
                                <div className="px-3 py-2 border-b border-border">
                                  <div className="text-sm font-medium">Kept per lane/pool</div>
                                </div>
                                <Table>
                                  <TableHeader>
                                    <TableRow>
                                      <TableHead>Lane</TableHead>
                                      <TableHead>Pool</TableHead>
                                      <TableHead className="w-[120px]">Kept</TableHead>
                                    </TableRow>
                                  </TableHeader>
                                  <TableBody>
                                    {keptRows.map((r) => (
                                      <TableRow key={`${r.lane}/${r.pool}`}>
                                        <TableCell className="text-xs">
                                          <Badge variant="outline">{r.lane}</Badge>
                                        </TableCell>
                                        <TableCell className="text-xs font-mono">{r.pool}</TableCell>
                                        <TableCell className="tabular-nums">{r.n}</TableCell>
                                      </TableRow>
                                    ))}
                                  </TableBody>
                                </Table>
                              </div>

                              <div className="rounded-md border border-border overflow-x-auto">
                                <div className="px-3 py-2 border-b border-border">
                                  <div className="text-sm font-medium">Anchor hit rate (top-20)</div>
                                </div>
                                <Table>
                                  <TableHeader>
                                    <TableRow>
                                      <TableHead>Lane</TableHead>
                                      <TableHead>Pool</TableHead>
                                      <TableHead className="w-[110px]">Hits</TableHead>
                                      <TableHead className="w-[110px]">Top N</TableHead>
                                      <TableHead className="w-[110px]">Rate</TableHead>
                                    </TableRow>
                                  </TableHeader>
                                  <TableBody>
                                    {anchorRows.map((r) => (
                                      <TableRow key={r.key}>
                                        <TableCell className="text-xs">
                                          <Badge variant="outline">{r.lane || "—"}</Badge>
                                        </TableCell>
                                        <TableCell className="text-xs font-mono">{r.pool || "—"}</TableCell>
                                        <TableCell className="tabular-nums">{r.hits}</TableCell>
                                        <TableCell className="tabular-nums">{r.topN}</TableCell>
                                        <TableCell className="tabular-nums">{r.rate !== null ? `${(r.rate * 100).toFixed(0)}%` : "—"}</TableCell>
                                      </TableRow>
                                    ))}
                                    {anchorRows.length === 0 ? (
                                      <TableRow>
                                        <TableCell colSpan={5} className="text-sm text-muted-foreground">
                                          No anchor stats yet.
                                        </TableCell>
                                      </TableRow>
                                    ) : null}
                                  </TableBody>
                                </Table>
                              </div>
                            </div>

                            <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
                              <div className="rounded-md border border-border p-3">
                                <div className="text-sm font-medium mb-2">Match lane — with abstract</div>
                                <HistogramBars hist={asRecord(matchDist["with_abstract"])} height={110} />
                              </div>
                              <div className="rounded-md border border-border p-3">
                                <div className="text-sm font-medium mb-2">Match lane — without abstract</div>
                                <HistogramBars hist={asRecord(matchDist["without_abstract"])} height={110} />
                              </div>
                              <div className="rounded-md border border-border p-3">
                                <div className="text-sm font-medium mb-2">Authority lane — with abstract</div>
                                <HistogramBars hist={asRecord(authDist["with_abstract"])} height={110} />
                              </div>
                              <div className="rounded-md border border-border p-3">
                                <div className="text-sm font-medium mb-2">Authority lane — without abstract</div>
                                <HistogramBars hist={asRecord(authDist["without_abstract"])} height={110} />
                              </div>
                            </div>

                            <div className="rounded-md border border-border p-3">
                              <div className="text-sm font-medium mb-2">Match vs authority (sample)</div>
                              <ScatterMatchAuthority points={phaseFScoring["scatter_match_vs_authority_sample"]} />
                            </div>

                            <details>
                              <summary className="text-xs text-muted-foreground cursor-pointer select-none">Raw JSON</summary>
                              <pre className="mt-2 text-xs overflow-auto max-h-[45vh] whitespace-pre-wrap rounded-md border border-border p-3 bg-muted/30">
                                {JSON.stringify(phaseFScoring ?? {}, null, 2)}
                              </pre>
                            </details>
                          </div>
                        );
                      })()}
                    </TabsContent>
                    <TabsContent value="rerank" className="mt-3">
                      {(() => {
                        const counts = asRecord(phaseIRerank["counts"]);
                        const modelUsed =
                          typeof counts["model_used"] === "string"
                            ? String(counts["model_used"])
                            : typeof counts["model"] === "string"
                              ? String(counts["model"])
                              : null;
                        const tasksTotal = asIntOrNull(counts["tasks_total"]);
                        const apiCalls = asIntOrNull(counts["api_calls"]);
                        const failures = asIntOrNull(counts["failures"]);
                        const costUsd = asNumberOrNull(counts["cost_usd_total"]) ?? asNumberOrNull(counts["cost_usd_est_total"]);
                        const latencyP50 = asNumberOrNull(counts["latency_s_p50"]);
                        const insufficientTotal = asIntOrNull(phaseIRerank["insufficient_total"]);

                        const insuffByLanePool = asRecord(counts["insufficient_by_lane_pool"]);
                        const insuffRows = Object.entries(insuffByLanePool)
                          .map(([k, v]) => ({ key: String(k), n: asIntOrNull(v) ?? 0 }))
                          .sort((a, b) => b.n - a.n);

                        return (
                          <div className="space-y-4">
                            {Object.keys(phaseIRerank).length === 0 ? (
                              <div className="text-sm text-muted-foreground">Waiting for Phase I (rerank)…</div>
                            ) : null}

                            <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
                              <div className="rounded-md border border-border p-3">
                                <div className="text-xs text-muted-foreground">Model</div>
                                <div className="text-sm font-medium">{modelUsed || "—"}</div>
                              </div>
                              <div className="rounded-md border border-border p-3">
                                <div className="text-xs text-muted-foreground">Tasks</div>
                                <div className="text-sm font-medium tabular-nums">{typeof tasksTotal === "number" ? tasksTotal : "—"}</div>
                                <div className="text-[10px] text-muted-foreground tabular-nums">
                                  calls {typeof apiCalls === "number" ? apiCalls : "—"} • failures {typeof failures === "number" ? failures : "—"}
                                </div>
                              </div>
                              <div className="rounded-md border border-border p-3">
                                <div className="text-xs text-muted-foreground">Cost</div>
                                <div className="text-sm font-medium tabular-nums">{typeof costUsd === "number" ? `$${costUsd.toFixed(4)}` : "—"}</div>
                              </div>
                              <div className="rounded-md border border-border p-3">
                                <div className="text-xs text-muted-foreground">Insufficient</div>
                                <div className="text-sm font-medium tabular-nums">{typeof insufficientTotal === "number" ? insufficientTotal : "—"}</div>
                                <div className="text-[10px] text-muted-foreground tabular-nums">{typeof latencyP50 === "number" ? `p50 ${latencyP50.toFixed(1)}s` : ""}</div>
                              </div>
                            </div>

                            <div className="rounded-md border border-border p-3">
                              <div className="text-sm font-medium mb-2">LLM score distribution</div>
                              <HistogramBars hist={phaseIRerank["llm_score_hist"]} height={120} />
                            </div>

                            {insuffRows.length ? (
                              <div className="rounded-md border border-border overflow-x-auto">
                                <div className="px-3 py-2 border-b border-border">
                                  <div className="text-sm font-medium">Insufficient by lane/pool</div>
                                </div>
                                <Table>
                                  <TableHeader>
                                    <TableRow>
                                      <TableHead>Lane/pool</TableHead>
                                      <TableHead className="w-[120px]">Count</TableHead>
                                    </TableRow>
                                  </TableHeader>
                                  <TableBody>
                                    {insuffRows.map((r) => (
                                      <TableRow key={r.key}>
                                        <TableCell className="font-mono text-xs">{r.key}</TableCell>
                                        <TableCell className="tabular-nums">{r.n}</TableCell>
                                      </TableRow>
                                    ))}
                                  </TableBody>
                                </Table>
                              </div>
                            ) : null}

                            <details>
                              <summary className="text-xs text-muted-foreground cursor-pointer select-none">Raw JSON</summary>
                              <pre className="mt-2 text-xs overflow-auto max-h-[45vh] whitespace-pre-wrap rounded-md border border-border p-3 bg-muted/30">
                                {JSON.stringify(phaseIRerank ?? {}, null, 2)}
                              </pre>
                            </details>
                          </div>
                        );
                      })()}
                    </TabsContent>
                    <TabsContent value="metrics" className="mt-3">
                      {(() => {
                        const stages = asRecord(metricsDoc["stages"]);
                        const rows = Object.entries(stages)
                          .map(([stage, v]) => {
                            const rec = asRecord(v);
                            const dur = asNumberOrNull(rec["last_duration_s"]);
                            const oa = asRecord(rec["openai"]);
                            const modelUsed = typeof oa["model_used"] === "string" ? String(oa["model_used"]) : null;
                            const cost = asNumberOrNull(oa["cost_usd"]);
                            return { stage: String(stage), dur, modelUsed, cost };
                          })
                          .sort((a, b) => (b.dur ?? -1) - (a.dur ?? -1));

                        return (
                          <div className="space-y-4">
                            {Object.keys(metricsDoc).length === 0 ? (
                              <div className="text-sm text-muted-foreground">Waiting for metrics…</div>
                            ) : null}

                            <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                              <div className="rounded-md border border-border p-3">
                                <div className="text-xs text-muted-foreground">Created (UTC)</div>
                                <div className="text-sm font-medium">
                                  {typeof metricsDoc["created_at_utc"] === "string" ? String(metricsDoc["created_at_utc"]) : "—"}
                                </div>
                              </div>
                              <div className="rounded-md border border-border p-3">
                                <div className="text-xs text-muted-foreground">Updated (UTC)</div>
                                <div className="text-sm font-medium">
                                  {typeof metricsDoc["updated_at_utc"] === "string" ? String(metricsDoc["updated_at_utc"]) : "—"}
                                </div>
                              </div>
                              <div className="rounded-md border border-border p-3">
                                <div className="text-xs text-muted-foreground">Stages</div>
                                <div className="text-sm font-medium tabular-nums">{rows.length}</div>
                              </div>
                            </div>

                            <div className="rounded-md border border-border overflow-x-auto">
                              <div className="px-3 py-2 border-b border-border">
                                <div className="text-sm font-medium">Stage timings (metrics.json)</div>
                              </div>
                              <Table>
                                <TableHeader>
                                  <TableRow>
                                    <TableHead>Stage</TableHead>
                                    <TableHead className="w-[120px]">Seconds</TableHead>
                                    <TableHead className="min-w-[240px] hidden lg:table-cell">Model used</TableHead>
                                    <TableHead className="w-[120px] hidden lg:table-cell">Cost</TableHead>
                                  </TableRow>
                                </TableHeader>
                                <TableBody>
                                  {rows.map((r) => (
                                    <TableRow key={r.stage}>
                                      <TableCell className="font-mono text-xs">{r.stage}</TableCell>
                                      <TableCell className="tabular-nums">{typeof r.dur === "number" ? Math.round(r.dur) : "—"}</TableCell>
                                      <TableCell className="text-xs hidden lg:table-cell">{r.modelUsed || "—"}</TableCell>
                                      <TableCell className="tabular-nums hidden lg:table-cell">
                                        {typeof r.cost === "number" ? `$${r.cost.toFixed(4)}` : "—"}
                                      </TableCell>
                                    </TableRow>
                                  ))}
                                  {rows.length === 0 ? (
                                    <TableRow>
                                      <TableCell colSpan={4} className="text-sm text-muted-foreground">
                                        No stage metrics yet.
                                      </TableCell>
                                    </TableRow>
                                  ) : null}
                                </TableBody>
                              </Table>
                            </div>

                            <details>
                              <summary className="text-xs text-muted-foreground cursor-pointer select-none">Raw JSON</summary>
                              <pre className="mt-2 text-xs overflow-auto max-h-[45vh] whitespace-pre-wrap rounded-md border border-border p-3 bg-muted/30">
                                {JSON.stringify(metricsDoc ?? {}, null, 2)}
                              </pre>
                            </details>
                          </div>
                        );
                      })()}
                    </TabsContent>
                  </Tabs>
                </DialogContent>
              </Dialog>
          </div>
        </div>
      </div>
          </div>
        </TooltipProvider>
  );
}
