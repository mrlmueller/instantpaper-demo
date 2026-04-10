"use client";

import { Fragment, memo, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { AlertTriangle, ArrowLeft, Ban, BarChart3, BookOpen, Check, ChevronDown, ExternalLink, Loader2, Play, Search, SlidersHorizontal, X } from "lucide-react";
import { toast } from "sonner";
import { limit, onSnapshot, query, where } from "firebase/firestore";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";

import { useAuth } from "@/app/components/providers/AuthProvider";
import { ViewportWarning } from "@/app/components/viewport-warning";
import { firestoreClient } from "@/app/lib/firebase/firestoreClient";
import {
  projectResearchRunsCol,
  quellenFinderTwoLaneResultsCol,
  quellenFinderTwoLaneTelemetryDoc,
} from "@/app/lib/firestore/refs";
import type {
  QuellenFinderRunDoc,
  TwoLaneLane,
  TwoLanePool,
  TwoLaneResultDoc,
} from "@/app/lib/firestore/types";
import type { Kapitel } from "@/app/actions/kapitels";

import { PipelineDetailsDialog } from "./PipelineDetailsDialog";

type WithId<T> = T & { id: string };
type WithDocId<T> = T & { docId: string };
type RunRow = WithId<QuellenFinderRunDoc>;
type TwoLaneRow = WithDocId<TwoLaneResultDoc>;

type SortDir = "asc" | "desc";
type TwoLaneSortKey = "rank" | "llmScore" | "year" | "citations";
type TwoLaneViewKey = "match_with_abstract" | "match_without_abstract" | "authority_with_abstract" | "authority_without_abstract";

type ToDateLike = { toDate: () => Date };

type PaperDetailsProps = {
  paper: TwoLaneRow;
  facetLabelById: Map<string, string>;
};

const PaperDetails = memo(function PaperDetails({ paper, facetLabelById }: PaperDetailsProps) {
  const truncateChars = (value: string, maxChars: number) => {
    const s = String(value || "");
    if (s.length <= maxChars) return s;
    if (maxChars <= 3) return s.slice(0, maxChars);
    return `${s.slice(0, Math.max(0, maxChars - 3)).trimEnd()}...`;
  };

  const llm =
    typeof paper.rerank?.llm_score_0_100 === "number" && Number.isFinite(paper.rerank.llm_score_0_100) ? Math.round(paper.rerank.llm_score_0_100) : null;
  const rationale = String(paper.rerank?.rationale || "").trim();
  const covered = Array.isArray(paper.rerank?.covered_facets) ? paper.rerank?.covered_facets : [];
  const topics = [...new Set((covered || []).filter((x) => typeof x === "string" && x.trim()).map((x) => x.trim()))]
    .map((id) => facetLabelById.get(id) ?? id)
    .slice(0, 16);
  const authorsRaw = (paper.authors || []).join(", ").trim();
  const authors = authorsRaw ? truncateChars(authorsRaw, 200) : "—";
  const venueRaw = String(paper.venue || "").trim();
  const venue = venueRaw ? truncateChars(venueRaw, 200) : "—";
  const href = paper.doi ? `https://doi.org/${paper.doi}` : String(paper.url || "");
  const linkLabel = paper.doi ? String(paper.doi) : String(paper.url || "");

  return (
    <div className="space-y-4 whitespace-normal">
      <div className="space-y-1">
        <div className="text-xs text-muted-foreground">Titel</div>
        <div className="text-base font-semibold leading-snug break-words">{paper.title || "(ohne Titel)"}</div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div className="space-y-1">
          <div className="text-xs text-muted-foreground">Autoren</div>
          <div className="text-sm break-words">{authors}</div>
        </div>
        <div className="space-y-1">
          <div className="text-xs text-muted-foreground">Venue</div>
          <div className="text-sm break-words">{venue}</div>
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
});

const PaperDetailsSkeleton = memo(function PaperDetailsSkeleton() {
  return (
    <div className="space-y-4" aria-label="Loading paper details">
      <div className="space-y-2">
        <Skeleton className="h-3 w-14" />
        <Skeleton className="h-5 w-3/4" />
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div className="space-y-2">
          <Skeleton className="h-3 w-16" />
          <Skeleton className="h-4 w-full" />
        </div>
        <div className="space-y-2">
          <Skeleton className="h-3 w-14" />
          <Skeleton className="h-4 w-2/3" />
        </div>
      </div>

      <div className="space-y-2">
        <Skeleton className="h-3 w-16" />
        <Skeleton className="h-4 w-full" />
        <Skeleton className="h-4 w-11/12" />
        <Skeleton className="h-4 w-10/12" />
      </div>

      <div className="space-y-2">
        <Skeleton className="h-3 w-24" />
        <div className="flex items-start gap-3">
          <Skeleton className="h-5 w-10 rounded-md" />
          <div className="flex-1 space-y-2">
            <Skeleton className="h-4 w-full" />
            <Skeleton className="h-4 w-10/12" />
          </div>
        </div>
      </div>

      <div className="space-y-2">
        <Skeleton className="h-3 w-16" />
        <div className="flex flex-wrap gap-2">
          <Skeleton className="h-6 w-24 rounded-md" />
          <Skeleton className="h-6 w-20 rounded-md" />
          <Skeleton className="h-6 w-28 rounded-md" />
        </div>
      </div>

      <Skeleton className="h-4 w-48" />
    </div>
  );
});

const SidebarEmptyState = memo(function SidebarEmptyState({ hasSelectedKapitel }: { hasSelectedKapitel: boolean }) {
  return (
    <div className="flex h-full min-h-[280px] items-center justify-center px-6 py-10">
      <div className="flex max-w-[220px] flex-col items-center text-center">
        <div className="flex h-12 w-12 items-center justify-center rounded-full bg-muted/40">
          <Search className="h-5 w-5 text-muted-foreground/60" />
        </div>
        <div className="mt-5 text-[28px] font-semibold leading-none text-sidebar-foreground/75">Noch keine Suchen</div>
        <div className="mt-3 text-sm leading-6 text-sidebar-foreground/60">
          {hasSelectedKapitel ? "Starte eine Suche für dieses Kapitel." : "Wähle ein Kapitel und starte die Suche."}
        </div>
      </div>
    </div>
  );
});

const MainEmptyState = memo(function MainEmptyState() {
  return (
    <div className="flex h-full min-h-[560px] items-center justify-center px-8">
      <div className="flex max-w-[540px] flex-col items-center text-center">
        <div className="flex h-16 w-16 items-center justify-center rounded-full bg-muted/30">
          <BookOpen className="h-8 w-8 text-muted-foreground/40" />
        </div>
        <div className="mt-6 text-[42px] font-semibold leading-tight tracking-[-0.02em] text-foreground/90">Literatursuche starten</div>
        <div className="mt-4 text-lg leading-9 text-muted-foreground">
          Wähle links ein Kapitel aus und starte eine Suche. Die Pipeline durchläuft mehrere Phasen, um die relevantesten
          wissenschaftlichen Arbeiten zu finden.
        </div>
      </div>
    </div>
  );
});

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

  type PlannerModel = "gpt-5-nano" | "gpt-5-mini" | "gpt-5.4";
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
  const [startConfirmOpen, setStartConfirmOpen] = useState(false);

  const [twoLaneViewKey, setTwoLaneViewKey] = useState<TwoLaneViewKey>("match_with_abstract");

  const [twoLaneResults, setTwoLaneResults] = useState<TwoLaneRow[]>([]);
  const [twoLaneReport, setTwoLaneReport] = useState<Record<string, unknown> | null>(null);
  const [twoLanePlan, setTwoLanePlan] = useState<Record<string, unknown> | null>(null);

  const [resultsSortKey, setResultsSortKey] = useState<TwoLaneSortKey>("llmScore");
  const [resultsSortDir, setResultsSortDir] = useState<SortDir>("desc");

  const [activePaperDocId, setActivePaperDocId] = useState<string | null>(null);
  const [paperDetailsOpen, setPaperDetailsOpen] = useState(false);
  const [paperDetailsReadyDocId, setPaperDetailsReadyDocId] = useState<string | null>(null);
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
    return null;
  }, [twoLaneRuns, activeTwoLaneRunId, selectedKapitelId]);

  useEffect(() => {
    if (!activeTwoLaneRunId) return;
    if (twoLaneRuns.some((r) => r.id === activeTwoLaneRunId)) return;
    setActiveTwoLaneRunId(null);
  }, [twoLaneRuns, activeTwoLaneRunId]);

  useEffect(() => {
    if (!user?.uid || !projektId) return;
    const q = query(
      projectResearchRunsCol(firestoreClient, user.uid, projektId),
      where("kind", "==", "sources_two_lane"),
      limit(50)
    );
    return onSnapshot(
      q,
      (snap) => {
        const next = snap.docs
          .map((d) => ({ id: d.id, ...(d.data() as QuellenFinderRunDoc) }))
          .sort(
            (a, b) =>
              (toDateOrNull(b.createdAt)?.getTime() ?? 0) - (toDateOrNull(a.createdAt)?.getTime() ?? 0)
          );
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
      setTwoLaneReport(null);
      setTwoLanePlan(null);
      return;
    }

    const resultsCol = quellenFinderTwoLaneResultsCol(firestoreClient, user.uid, projektId, activeTwoLaneRun.id);

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

    const reportDoc = quellenFinderTwoLaneTelemetryDoc(firestoreClient, user.uid, projektId, activeTwoLaneRun.id, "v2_report");
    const planDoc = quellenFinderTwoLaneTelemetryDoc(firestoreClient, user.uid, projektId, activeTwoLaneRun.id, "v2_b_plan");

    const unsubReport = onSnapshot(
      reportDoc,
      (snap) => setTwoLaneReport(snap.exists() ? (snap.data() as Record<string, unknown>) : null),
      (err) => {
        console.error("Failed to load v2_report:", err);
        setTwoLaneReport(null);
      }
    );

    const unsubPlan = onSnapshot(
      planDoc,
      (snap) => setTwoLanePlan(snap.exists() ? (snap.data() as Record<string, unknown>) : null),
      (err) => {
        console.error("Failed to load v2_b_plan:", err);
        setTwoLanePlan(null);
      }
    );

    return () => {
      unsubResults();
      unsubReport();
      unsubPlan();
    };
  }, [user?.uid, projektId, activeTwoLaneRun?.id]);

  const visibleTwoLaneResults = useMemo(() => (activeTwoLaneRun ? twoLaneResults : []), [activeTwoLaneRun, twoLaneResults]);
  const visibleTwoLaneReport = useMemo(() => (activeTwoLaneRun ? twoLaneReport : null), [activeTwoLaneRun, twoLaneReport]);
  const visibleTwoLanePlan = useMemo(() => (activeTwoLaneRun ? twoLanePlan : null), [activeTwoLaneRun, twoLanePlan]);

  const facets = useMemo(() => asRecordArray(asRecord(visibleTwoLanePlan)["facets"]), [visibleTwoLanePlan]);
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

  const twoLaneCountsByView = useMemo(() => {
    const counts: Record<TwoLaneViewKey, number> = {
      match_with_abstract: 0,
      match_without_abstract: 0,
      authority_with_abstract: 0,
      authority_without_abstract: 0,
    };
    for (const r of visibleTwoLaneResults) {
      const k = `${r.lane}_${r.pool}` as TwoLaneViewKey;
      if (k in counts) counts[k] += 1;
    }
    return counts;
  }, [visibleTwoLaneResults]);

  const twoLaneFiltered = useMemo(() => {
    const { lane, pool } = parseTwoLaneViewKey(twoLaneViewKey);
    const rows = visibleTwoLaneResults.filter((r) => r.lane === lane && r.pool === pool);

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
  }, [visibleTwoLaneResults, twoLaneViewKey, resultsSortDir, resultsSortKey]);

  useEffect(() => {
    if (!activePaperDocId) return;
    if (twoLaneFiltered.some((r) => r.docId === activePaperDocId)) return;
    setPaperDetailsOpen(false);
    setPaperDetailsReadyDocId(null);
    setActivePaperDocId(null);
  }, [twoLaneFiltered, activePaperDocId]);

  useEffect(() => {
    if (!paperDetailsOpen || !activePaperDocId) return;
    if (paperDetailsReadyDocId === activePaperDocId) return;
    const id = window.requestAnimationFrame(() => setPaperDetailsReadyDocId(activePaperDocId));
    return () => window.cancelAnimationFrame(id);
  }, [paperDetailsOpen, activePaperDocId, paperDetailsReadyDocId]);

  const runningTwoLane = activeTwoLaneRun?.status === "running" || activeTwoLaneRun?.status === "queued";
  const canRunTwoLane = Boolean(user?.uid && projektId && selectedKapitelId);

  useEffect(() => {
    if (!runningTwoLane) return;
    setNowMs(Date.now());
    const id = window.setInterval(() => setNowMs(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, [runningTwoLane]);

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
    if (!selectedKapitelId) {
      toast.error("Bitte ein Kapitel auswählen.");
      return;
    }
    setStartConfirmOpen(true);
  };

  const confirmStartTwoLaneSources = async () => {
    if (!selectedKapitelId) {
      toast.error("Bitte ein Kapitel auswählen.");
      return;
    }
    const kapitelId = selectedKapitelId;
    setStartConfirmOpen(false);

    const res = await fetch("/api/quellen-finder/sources-two-lane/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
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
    const res = await fetch("/api/quellen-finder/sources-two-lane/cancel", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ projekt_id: projektId, run_id: activeTwoLaneRun.id }),
    });

    if (!res.ok) {
      const detail = await readFastApiError(res);
      toast.error("Cancel fehlgeschlagen", { description: detail });
      return;
    }

    toast.success("Abbruch angefordert", { description: `Run: ${activeTwoLaneRun.id}` });
  };

  const resetPaperDetails = () => {
    setPaperDetailsOpen(false);
    setPaperDetailsReadyDocId(null);
    setActivePaperDocId(null);
  };

  const togglePaperDetails = (docId: string) => {
    if (activePaperDocId === docId) {
      if (paperDetailsOpen) {
        setPaperDetailsOpen(false);
        return;
      }
      setPaperDetailsReadyDocId(null);
      setPaperDetailsOpen(true);
      return;
    }
    setActivePaperDocId(docId);
    setPaperDetailsReadyDocId(null);
    setPaperDetailsOpen(true);
  };

  const selectKapitel = (kapitelId: string | null) => {
    setSelectedKapitelId(kapitelId);
    resetPaperDetails();

    if (!kapitelId) {
      setActiveTwoLaneRunId(null);
      return;
    }

    const mostRecentRun = twoLaneRuns.find((r) => Array.isArray(r.kapitelIds) && r.kapitelIds.includes(kapitelId));
    setActiveTwoLaneRunId(mostRecentRun?.id ?? null);
  };

  const selectRun = (run: RunRow) => {
    setActiveTwoLaneRunId(run.id);
    resetPaperDetails();
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
  const chapterHeading = `${chapterNummer ? `${chapterNummer} ` : ""}${chapterTitle}`.trim();

  const runStartedAt = toDateOrNull(activeTwoLaneRun?.startedAt) ?? toDateOrNull(activeTwoLaneRun?.createdAt);
  const runFinishedAt = toDateOrNull(activeTwoLaneRun?.finishedAt);
  const runStartMs = runStartedAt?.getTime() ?? nowMs;
  const stageStartMs =
    (toDateOrNull(activeTwoLaneRun?.progress?.stageStartedAt) ?? runStartedAt)?.getTime() ?? runStartMs;
  const elapsedMs = Math.max(0, nowMs - runStartMs);
  const stageElapsedMs = Math.max(0, nowMs - stageStartMs);

  const summaryRec = asRecord(activeTwoLaneRun?.summary);
  const reportKpis = asRecord(asRecord(visibleTwoLaneReport)["kpis"]);
  const totalCostUsd = asNumberOrNull(summaryRec["total_cost_usd"]) ?? asNumberOrNull(reportKpis["total_cost_usd"]);
  const secondsTotal = asNumberOrNull(summaryRec["seconds_total"]);
  const resultCount =
    typeof activeTwoLaneRun?.resultCount === "number" ? activeTwoLaneRun.resultCount : visibleTwoLaneResults.length ? visibleTwoLaneResults.length : null;
  const candidatesTotal = typeof reportKpis["candidates_total"] === "number" ? (reportKpis["candidates_total"] as number) : null;

  const stageKey = String(activeTwoLaneRun?.progress?.stage || "");
  const stageIdxDirect = TWO_LANE_PIPELINE_STEPS.findIndex((s) => s.key === stageKey);
  const stageIdx = stageIdxDirect;

  const isDone = activeTwoLaneRun?.status === "success" || stageKey === "done";
  const isError = activeTwoLaneRun?.status === "error" || stageKey === "error";
  const isCancelled = activeTwoLaneRun?.status === "cancelled" || stageKey === "cancelled";
  const isCancelRequested = Boolean(activeTwoLaneRun?.cancelRequestedAt) || stageKey === "cancel_requested";

  const completedSteps = isDone ? TWO_LANE_PIPELINE_STEPS.length : Math.max(0, stageIdx);
  const activeStep = !isDone && stageIdx >= 0 ? stageIdx : -1;
  const activeStepLabel = activeStep >= 0 ? TWO_LANE_PIPELINE_STEPS[activeStep]?.label ?? "" : "";
  const pipelineStatusLabel = activeTwoLaneRun
    ? isDone
      ? "Abgeschlossen"
      : isError
        ? "Fehler"
        : isCancelled
          ? "Abgebrochen"
          : isCancelRequested
            ? "Abbruch angefordert"
            : activeStepLabel || "Wartet…"
    : selectedKapitel
      ? "Noch kein Run für dieses Kapitel."
      : "Kein Kapitel ausgewählt.";
  const pipelineStatusIcon = activeTwoLaneRun ? (
    isDone ? (
      <Check className="h-4 w-4 text-emerald-600" />
    ) : isError ? (
      <AlertTriangle className="h-4 w-4 text-red-600" />
    ) : isCancelled ? (
      <Ban className="h-4 w-4 text-muted-foreground" />
    ) : (
      <Loader2 className="h-4 w-4 animate-spin text-orange-500" />
    )
  ) : (
    <div className="h-2.5 w-2.5 rounded-full bg-muted-foreground/30" aria-hidden />
  );
  const pipelineCompletedSteps = activeTwoLaneRun ? completedSteps : 0;

  return (
    <TooltipProvider delayDuration={150}>
      <div className="min-h-screen h-screen overflow-hidden bg-background flex flex-col">
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

        <div className="flex-1 min-h-0 flex flex-row">
          <aside className="w-[320px] shrink-0 border-r border-border bg-sidebar flex flex-col text-sidebar-foreground">
            <div className="p-5 border-b border-sidebar-border space-y-4 shrink-0">
              <div className="space-y-2">
                <div className="text-xs font-medium text-sidebar-foreground/70">Kapitel auswählen</div>
                <Select value={selectedKapitelId || ""} onValueChange={(v) => selectKapitel(v || null)}>
                  <SelectTrigger className="w-full h-auto min-h-10 whitespace-normal items-center px-4 py-3 bg-background shadow-none">
                    <div className="min-w-0 flex-1 text-left">
                      {selectedKapitel ? (
                        <div className="line-clamp-2 leading-snug">
                          <span className="text-muted-foreground tabular-nums mr-2">{selectedKapitel.nummer}</span>
                          {selectedKapitel.title}
                        </div>
                      ) : (
                        <span className="text-muted-foreground">Kapitel wählen...</span>
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
                      <Select value={plannerModel} onValueChange={(v) => (v === "gpt-5-nano" || v === "gpt-5-mini" || v === "gpt-5.4" ? setPlannerModel(v) : null)}>
                        <SelectTrigger className="h-9">
                          <SelectValue placeholder="Planner" />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="gpt-5-nano">gpt-5-nano</SelectItem>
                          <SelectItem value="gpt-5-mini">gpt-5-mini</SelectItem>
                          <SelectItem value="gpt-5.4">gpt-5.4</SelectItem>
                        </SelectContent>
                      </Select>
                    </div>

                    <div className="space-y-1">
                      <div className="text-xs text-muted-foreground">OpenAlex query model</div>
                      <Select
                        value={openalexQueryModel}
                        onValueChange={(v) => (v === "gpt-5-nano" || v === "gpt-5-mini" || v === "gpt-5.4" ? setOpenalexQueryModel(v) : null)}
                      >
                        <SelectTrigger className="h-9">
                          <SelectValue placeholder="OpenAlex query model" />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="gpt-5-nano">gpt-5-nano</SelectItem>
                          <SelectItem value="gpt-5-mini">gpt-5-mini</SelectItem>
                          <SelectItem value="gpt-5.4">gpt-5.4</SelectItem>
                        </SelectContent>
                      </Select>
                    </div>

                    <div className="space-y-1">
                      <div className="text-xs text-muted-foreground">S2 query model</div>
                      <Select value={s2QueryModel} onValueChange={(v) => (v === "gpt-5-nano" || v === "gpt-5-mini" || v === "gpt-5.4" ? setS2QueryModel(v) : null)}>
                        <SelectTrigger className="h-9">
                          <SelectValue placeholder="S2 query model" />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="gpt-5-nano">gpt-5-nano</SelectItem>
                          <SelectItem value="gpt-5-mini">gpt-5-mini</SelectItem>
                          <SelectItem value="gpt-5.4">gpt-5.4</SelectItem>
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
              {twoLaneRuns.length === 0 ? (
                <SidebarEmptyState hasSelectedKapitel={Boolean(selectedKapitel)} />
              ) : (
                twoLaneRuns.map((r) => {
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
                })
              )}
            </div>
          </aside>

          <div className="flex-1 min-w-0 overflow-auto">
            {activeTwoLaneRun ? (
              <div className="space-y-4 min-w-0 p-6">
                <div className="flex items-start justify-between gap-4">
                  <div className="min-w-0">
                    <div className="text-xl font-semibold truncate">{chapterHeading || "Kapitel auswählen"}</div>
                    <div className="text-xs text-muted-foreground">
                      Gestartet: {formatDateTimeWithSeconds(runStartedAt)}{" "}
                      {runFinishedAt ? <>| Abgeschlossen: {formatDateTimeWithSeconds(runFinishedAt)}</> : null}
                    </div>
                  </div>

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
                        {pipelineStatusIcon}
                        <span className="truncate">{pipelineStatusLabel}</span>
                      </div>
                      <div className="text-xs text-muted-foreground tabular-nums shrink-0">
                        {pipelineCompletedSteps} / {TWO_LANE_PIPELINE_STEPS.length} Schritte
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
                          resetPaperDetails();
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
                              const rowSelected = r.docId === activePaperDocId;
                              const rowOpen = rowSelected && paperDetailsOpen;
                              const rowReady = rowSelected && paperDetailsReadyDocId === r.docId;
                              return (
                                <Fragment key={r.docId}>
                                  <TableRow
                                    className={`cursor-pointer ${rowOpen ? "bg-muted/40" : ""}`}
                                    onClick={() => togglePaperDetails(r.docId)}
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
                                  {rowSelected ? (
                                    <TableRow className={`bg-background ${rowOpen ? "" : "hidden"}`}>
                                      <TableCell colSpan={6} className="p-0">
                                        <div className="border-t border-border p-4 bg-background">
                                          {rowReady ? <PaperDetails paper={r} facetLabelById={facetLabelById} /> : <PaperDetailsSkeleton />}
                                        </div>
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
              </div>
            ) : (
              <MainEmptyState />
            )}

            <PipelineDetailsDialog
              key={activeTwoLaneRun?.id ?? "none"}
              open={telemetryDialogOpen}
              onOpenChange={setTelemetryDialogOpen}
              uid={user?.uid || ""}
              projektId={projektId}
              run={activeTwoLaneRun}
              kapitel={selectedKapitel}
            />

            <AlertDialog open={startConfirmOpen} onOpenChange={setStartConfirmOpen}>
              <AlertDialogContent>
                <AlertDialogHeader>
                  <AlertDialogTitle>Quellen-Suche starten?</AlertDialogTitle>
                  <AlertDialogDescription className="space-y-2 text-sm text-muted-foreground">
                    <span className="block">Die Suche wird als neuer Lauf gestartet.</span>
                    <span className="block">
                      Kapitel: <span className="font-medium text-foreground">{chapterHeading || selectedKapitelId || "—"}</span>
                    </span>
                  </AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter>
                  <AlertDialogCancel>Abbrechen</AlertDialogCancel>
                  <AlertDialogAction
                    onClick={(event) => {
                      event.preventDefault();
                      void confirmStartTwoLaneSources();
                    }}
                    className="rounded-[4px] border-[#1680cd] bg-[#1680cd] text-white hover:bg-[#0f76c2]"
                  >
                    Suche starten
                  </AlertDialogAction>
                </AlertDialogFooter>
              </AlertDialogContent>
            </AlertDialog>
          </div>
        </div>
      </div>
        <ViewportWarning />
      </TooltipProvider>
  );
}
