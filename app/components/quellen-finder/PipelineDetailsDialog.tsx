"use client";

import { Fragment, useEffect, useMemo, useState } from "react";
import { ChevronDown, X } from "lucide-react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  XAxis,
  YAxis,
} from "recharts";
import { onSnapshot } from "firebase/firestore";

import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { Dialog, DialogClose, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";

import { ChartContainer, ChartLegend, ChartLegendContent, ChartTooltip, ChartTooltipContent } from "@/components/ui/chart";

import { firestoreClient } from "@/app/lib/firebase/firestoreClient";
import { projectResearchRunDoc, quellenFinderTwoLaneTelemetryDoc } from "@/app/lib/firestore/refs";
import type { Kapitel } from "@/app/actions/kapitels";
import type { QuellenFinderRunDoc } from "@/app/lib/firestore/types";

type WithId<T> = T & { id: string };
type RunRow = WithId<QuellenFinderRunDoc>;

type TabKey = "report" | "b_plan" | "c_queries" | "d_retrieval" | "e_candidates" | "f_scoring" | "i_rerank";

const TAB_DEFS: Array<{ key: TabKey; label: string; docId: string }> = [
  { key: "report", label: "Bericht", docId: "v2_report" },
  { key: "b_plan", label: "B: Planung", docId: "v2_b_plan" },
  { key: "c_queries", label: "C: Querries", docId: "v2_c_queries" },
  { key: "d_retrieval", label: "D: Retrival", docId: "v2_d_retrieval" },
  { key: "e_candidates", label: "E: Kandidaten", docId: "v2_e_candidates" },
  { key: "f_scoring", label: "F: Scoring", docId: "v2_f_scoring" },
  { key: "i_rerank", label: "I: Rerank", docId: "v2_i_rerank" },
];

function asRecord(x: unknown): Record<string, unknown> {
  return x && typeof x === "object" ? (x as Record<string, unknown>) : {};
}
function asArray(x: unknown): unknown[] {
  return Array.isArray(x) ? x : [];
}
function asRecordArray(x: unknown): Array<Record<string, unknown>> {
  return asArray(x).filter((v): v is Record<string, unknown> => !!v && typeof v === "object");
}
function asStringArray(x: unknown): string[] {
  return asArray(x)
    .map((v) => (typeof v === "string" ? v : ""))
    .map((s) => s.trim())
    .filter(Boolean);
}

function truncateChars(value: unknown, maxChars: number): string {
  const s = String(value || "").trim();
  if (!s) return "";
  if (s.length <= maxChars) return s;
  if (maxChars <= 1) return "…";
  return `${s.slice(0, Math.max(0, maxChars - 1)).trimEnd()}…`;
}

function formatIntDe(value: unknown): string {
  const n = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(n)) return "—";
  return new Intl.NumberFormat("de-DE").format(Math.round(n));
}

function formatUsd(value: unknown): string {
  const n = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(n)) return "—";
  return `$${n.toFixed(3)}`;
}

type ToDateLike = { toDate: () => Date };
function formatDateTimeDe(value: unknown): string {
  if (!value) return "—";
  const d =
    value instanceof Date
      ? value
      : typeof (value as ToDateLike)?.toDate === "function"
        ? (value as ToDateLike).toDate()
        : null;
  if (!d) return "—";
  return new Intl.DateTimeFormat("de-DE", {
    year: "numeric",
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).format(d);
}

function formatSecondsShort(seconds: unknown): string {
  const s = typeof seconds === "number" ? seconds : Number(seconds);
  if (!Number.isFinite(s)) return "—";
  if (s < 60) return `${s.toFixed(1)}s`;
  const m = Math.floor(s / 60);
  const r = s - m * 60;
  return `${m}m ${r.toFixed(0)}s`;
}

export function PipelineDetailsDialog({
  open,
  onOpenChange,
  uid,
  projektId,
  run,
  kapitel,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  uid: string;
  projektId: string;
  run: RunRow | null;
  kapitel: Kapitel | null;
}) {
  const runId = run?.id ?? null;
  const [activeTab, setActiveTab] = useState<TabKey>("report");
  const [docs, setDocs] = useState<Record<string, Record<string, unknown> | null>>({});
  const [loaded, setLoaded] = useState<Record<string, boolean>>({});

  const tabDocId = useMemo(() => TAB_DEFS.find((t) => t.key === activeTab)?.docId ?? "v2_report", [activeTab]);

  // Always subscribe to v2_report while open.
  useEffect(() => {
    if (!open || !uid || !projektId || !runId) return;
    const ref = quellenFinderTwoLaneTelemetryDoc(firestoreClient, uid, projektId, runId, "v2_report");
    return onSnapshot(
      ref,
      (snap) => {
        setLoaded((p) => ({ ...p, v2_report: true }));
        setDocs((p) => ({ ...p, v2_report: snap.exists() ? (snap.data() as Record<string, unknown>) : null }));
      },
      () => {
        setLoaded((p) => ({ ...p, v2_report: true }));
        setDocs((p) => ({ ...p, v2_report: null }));
      }
    );
  }, [open, uid, projektId, runId]);

  // Subscribe to run doc as well (for live cost + status).
  const [runLive, setRunLive] = useState<RunRow | null>(run);
  useEffect(() => {
    if (!open || !uid || !projektId || !runId) return;
    const ref = projectResearchRunDoc(firestoreClient, uid, projektId, runId);
    return onSnapshot(ref, (snap) => {
      const data = snap.exists() ? (snap.data() as QuellenFinderRunDoc) : null;
      setRunLive(data ? ({ ...data, id: runId } as RunRow) : null);
    });
  }, [open, uid, projektId, runId]);

  // Subscribe to currently active tab doc (except report).
  useEffect(() => {
    if (!open || !uid || !projektId || !runId) return;
    if (!tabDocId || tabDocId === "v2_report") return;
    const ref = quellenFinderTwoLaneTelemetryDoc(firestoreClient, uid, projektId, runId, tabDocId);
    return onSnapshot(
      ref,
      (snap) => {
        setLoaded((p) => ({ ...p, [tabDocId]: true }));
        setDocs((p) => ({ ...p, [tabDocId]: snap.exists() ? (snap.data() as Record<string, unknown>) : null }));
      },
      () => {
        setLoaded((p) => ({ ...p, [tabDocId]: true }));
        setDocs((p) => ({ ...p, [tabDocId]: null }));
      }
    );
  }, [open, uid, projektId, runId, tabDocId]);

  const v2Report = docs["v2_report"];
  const reportLoaded = !!loaded["v2_report"];

  const reportKpis = useMemo(() => asRecord(v2Report ? asRecord(v2Report)["kpis"] : {}), [v2Report]);
  const reportTotalCostUsd = useMemo(() => {
    const fromReport = reportKpis["total_cost_usd"];
    if (typeof fromReport === "number" && Number.isFinite(fromReport)) return fromReport;
    const sum = asRecord(runLive?.summary);
    const c = sum["total_cost_usd"];
    return typeof c === "number" && Number.isFinite(c) ? c : 0;
  }, [reportKpis, runLive?.summary]);

  const resultCount = typeof runLive?.resultCount === "number" ? runLive?.resultCount : null;
  const startedAt = runLive?.startedAt ?? null;
  const finishedAt = runLive?.finishedAt ?? null;
  const secondsTotal = reportKpis["seconds_total"];

  const showLegacyBanner = useMemo(() => {
    if (!reportLoaded) return false;
    if (v2Report) return false;
    const status = String(runLive?.status || "");
    return status === "success" || status === "error" || status === "cancelled";
  }, [reportLoaded, v2Report, runLive?.status]);

  const titleKapitel = String(kapitel?.title || runLive?.kapitelSnapshots?.[0]?.title || "").trim() || "—";

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        showCloseButton={false}
        className="!flex !flex-col !gap-0 !w-[90vw] !max-w-[90vw] sm:!max-w-[90vw] !h-[90vh] !max-h-[90vh] overflow-hidden !p-0"
      >
        <DialogHeader className="px-6 py-4 border-b border-border">
          <div className="flex items-start justify-between gap-4">
            <div className="min-w-0">
              <DialogTitle className="text-base font-semibold truncate">Pipeline Details — {titleKapitel}</DialogTitle>
              <DialogDescription className="text-xs text-muted-foreground mt-1">
                Gestartet: {formatDateTimeDe(startedAt)} | Abgeschlossen: {formatDateTimeDe(finishedAt)} | Dauer:{" "}
                {secondsTotal ? formatSecondsShort(secondsTotal) : "—"}
              </DialogDescription>
            </div>
            <div className="shrink-0 flex items-center gap-3 text-xs">
              <div className="tabular-nums text-muted-foreground">{formatUsd(reportTotalCostUsd)}</div>
              <Badge variant="outline" className="tabular-nums font-normal">
                {resultCount !== null ? `${formatIntDe(resultCount)} Ergebnisse` : "— Ergebnisse"}
              </Badge>
              <DialogClose asChild>
                <button
                  type="button"
                  className="inline-flex h-8 w-8 items-center justify-center rounded-md border border-border bg-background text-muted-foreground transition-colors hover:bg-muted/40 hover:text-foreground focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2 focus:ring-offset-background"
                >
                  <X className="size-4" />
                  <span className="sr-only">Close</span>
                </button>
              </DialogClose>
            </div>
          </div>
        </DialogHeader>

        <div className="flex-1 overflow-y-auto">
          <Tabs
            value={activeTab}
            onValueChange={(v) => {
              const next = v as TabKey;
              setActiveTab(next);
              const nextDocId = TAB_DEFS.find((t) => t.key === next)?.docId;
              if (!nextDocId || nextDocId === "v2_report") return;
              if (loaded[nextDocId] === undefined) {
                setLoaded((p) => ({ ...p, [nextDocId]: false }));
              }
            }}
            className="gap-0"
          >
            <div className="sticky top-0 z-10 bg-background -mt-px px-6 pt-1 pb-2 border-b border-border">
              <TabsList className="bg-transparent p-0 h-auto flex flex-wrap gap-2">
                {TAB_DEFS.map((t) => (
                  <TabsTrigger
                    key={t.key}
                    value={t.key}
                    className="flex-none h-7 px-2 py-1 rounded-md border border-transparent bg-transparent text-xs font-medium text-muted-foreground transition-colors hover:text-foreground data-[state=active]:bg-background data-[state=active]:text-foreground data-[state=active]:border-foreground/30 data-[state=active]:shadow-sm"
                  >
                    {t.label}
                  </TabsTrigger>
                ))}
              </TabsList>
            </div>

            <div className="px-6 py-4">
              {showLegacyBanner ? (
                <div className="mb-4 rounded-md border border-border bg-muted/30 p-3 text-sm">
                  <div className="font-medium">Legacy run</div>
                  <div className="text-muted-foreground text-xs mt-1">
                    Diese Ausführung hat noch keine Telemetry v2 Daten. Bitte starte die Quellen‑Suche erneut, um die neuen Pipeline Details zu sehen.
                  </div>
                </div>
              ) : null}

              <TabsContent value="report" className="mt-0">
                <ReportTab report={v2Report} loading={!reportLoaded} liveCostUsd={reportTotalCostUsd} />
              </TabsContent>
              <TabsContent value="b_plan" className="mt-0">
                <PlanTab doc={docs["v2_b_plan"]} loaded={!!loaded["v2_b_plan"]} />
              </TabsContent>
              <TabsContent value="c_queries" className="mt-0">
                <QueriesTab doc={docs["v2_c_queries"]} loaded={!!loaded["v2_c_queries"]} />
              </TabsContent>
              <TabsContent value="d_retrieval" className="mt-0">
                <RetrievalTab doc={docs["v2_d_retrieval"]} loaded={!!loaded["v2_d_retrieval"]} />
              </TabsContent>
              <TabsContent value="e_candidates" className="mt-0">
                <CandidatesTab doc={docs["v2_e_candidates"]} loaded={!!loaded["v2_e_candidates"]} />
              </TabsContent>
              <TabsContent value="f_scoring" className="mt-0">
                <ScoringTab doc={docs["v2_f_scoring"]} loaded={!!loaded["v2_f_scoring"]} />
              </TabsContent>
              <TabsContent value="i_rerank" className="mt-0">
                <RerankTab doc={docs["v2_i_rerank"]} loaded={!!loaded["v2_i_rerank"]} />
              </TabsContent>
            </div>
          </Tabs>
        </div>
      </DialogContent>
    </Dialog>
  );
}

function KpiCard({ label, value, tooltip }: { label: string; value: React.ReactNode; tooltip?: React.ReactNode }) {
  const card = (
    <Card className="p-4">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="text-lg font-semibold tabular-nums mt-1">{value}</div>
    </Card>
  );
  if (!tooltip) return card;
  return (
    <Tooltip>
      <TooltipTrigger asChild>{card}</TooltipTrigger>
      <TooltipContent className="max-w-[60vw]">{tooltip}</TooltipContent>
    </Tooltip>
  );
}

function ReportTab({
  report,
  loading,
  liveCostUsd,
}: {
  report: Record<string, unknown> | null | undefined;
  loading: boolean;
  liveCostUsd: number;
}) {
  if (loading) {
    return (
      <div className="space-y-4">
        <div className="grid grid-cols-1 md:grid-cols-3 lg:grid-cols-6 gap-3">
          {Array.from({ length: 6 }).map((_, i) => (
            <Card key={i} className="p-4">
              <Skeleton className="h-3 w-20" />
              <Skeleton className="h-6 w-24 mt-3" />
            </Card>
          ))}
        </div>
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
          <Card className="p-4">
            <Skeleton className="h-3 w-40" />
            <Skeleton className="h-40 w-full mt-4" />
          </Card>
          <Card className="p-4">
            <Skeleton className="h-3 w-40" />
            <Skeleton className="h-40 w-full mt-4" />
          </Card>
        </div>
      </div>
    );
  }

  if (!report) {
    return <div className="text-sm text-muted-foreground">Warte auf Telemetry v2…</div>;
  }

  const r = asRecord(report);
  const kpis = asRecord(r["kpis"]);
  const stageTables = asRecord(r["stage_tables"]);
  const durations = asRecordArray(stageTables["durations"]);
  const costs = asRecordArray(stageTables["costs"]);
  const models = asRecord(r["models"]);
  const plots = asRecord(r["plots"]);
  const byRank = asRecord(plots["lane_score_by_rank_top200"]);

  const costUsd = liveCostUsd;

  return (
    <TooltipProvider delayDuration={200}>
      <div className="space-y-4">
        <div className="grid grid-cols-1 md:grid-cols-3 lg:grid-cols-6 gap-3">
          <KpiCard label="Gesamtdauer" value={formatSecondsShort(kpis["seconds_total"])} />
          <KpiCard label="Gesamtkosten" value={formatUsd(costUsd)} />
          <KpiCard
            label="Records abgerufen"
            value={formatIntDe(kpis["records_total"])}
            tooltip={
              <div className="grid gap-1 text-xs">
                <div className="flex items-center justify-between gap-6">
                  <span className="text-muted-foreground">OpenAlex</span>
                  <span className="tabular-nums">{formatIntDe(kpis["records_openalex"])}</span>
                </div>
                <div className="flex items-center justify-between gap-6">
                  <span className="text-muted-foreground">S2</span>
                  <span className="tabular-nums">{formatIntDe(kpis["records_semanticscholar"])}</span>
                </div>
              </div>
            }
          />
          <KpiCard label="Kandidaten" value={formatIntDe(kpis["candidates_total"])} />
          <KpiCard label="Facetten" value={formatIntDe(kpis["facets_count"])} />
          <KpiCard
            label="Queries"
            value={formatIntDe(kpis["queries_total"])}
            tooltip={
              <div className="grid gap-1 text-xs">
                <div className="flex items-center justify-between gap-6">
                  <span className="text-muted-foreground">OpenAlex</span>
                  <span className="tabular-nums">{formatIntDe(kpis["queries_openalex"])}</span>
                </div>
                <div className="flex items-center justify-between gap-6">
                  <span className="text-muted-foreground">S2</span>
                  <span className="tabular-nums">{formatIntDe(kpis["queries_semanticscholar"])}</span>
                </div>
              </div>
            }
          />
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
          <Card className="p-4">
            <div className="text-sm font-medium mb-3">Dauer pro Phase</div>
            <ScrollArea className="h-[280px]">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="w-[60%]">Phase</TableHead>
                    <TableHead className="text-right">Dauer</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {durations.length ? (
                    durations.map((row, idx) => (
                      <TableRow key={String(row["key"] || row["label"] || idx)}>
                        <TableCell className="text-sm">{String(row["label"] || row["key"] || "—")}</TableCell>
                        <TableCell className="text-right tabular-nums text-sm">{formatSecondsShort(row["duration_s"])}</TableCell>
                      </TableRow>
                    ))
                  ) : (
                    <TableRow>
                      <TableCell colSpan={2} className="text-sm text-muted-foreground">
                        Noch keine Daten.
                      </TableCell>
                    </TableRow>
                  )}
                </TableBody>
              </Table>
            </ScrollArea>
          </Card>

          <Card className="p-4">
            <div className="text-sm font-medium mb-3">Kosten pro Phase</div>
            <ScrollArea className="h-[280px]">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="w-[40%]">Phase</TableHead>
                    <TableHead className="text-right">Kosten</TableHead>
                    <TableHead className="text-right hidden xl:table-cell">Req.</TableHead>
                    <TableHead className="text-right hidden xl:table-cell">Input Tok.</TableHead>
                    <TableHead className="text-right hidden 2xl:table-cell">Cached Tok.</TableHead>
                    <TableHead className="text-right hidden xl:table-cell">Output Tok.</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {costs.length ? (
                    costs.map((row, idx) => (
                      <TableRow key={String(row["key"] || row["label"] || idx)}>
                        <TableCell className="text-sm">{String(row["label"] || row["key"] || "—")}</TableCell>
                        <TableCell className="text-right tabular-nums text-sm">{formatUsd(row["cost_usd"])}</TableCell>
                        <TableCell className="text-right tabular-nums text-sm hidden xl:table-cell">{formatIntDe(row["requests"])}</TableCell>
                        <TableCell className="text-right tabular-nums text-sm hidden xl:table-cell">{formatIntDe(row["input_tokens"])}</TableCell>
                        <TableCell className="text-right tabular-nums text-sm hidden 2xl:table-cell">{formatIntDe(row["cached_input_tokens"])}</TableCell>
                        <TableCell className="text-right tabular-nums text-sm hidden xl:table-cell">{formatIntDe(row["output_tokens"])}</TableCell>
                      </TableRow>
                    ))
                  ) : (
                    <TableRow>
                      <TableCell colSpan={6} className="text-sm text-muted-foreground">
                        Noch keine Daten.
                      </TableCell>
                    </TableRow>
                  )}
                </TableBody>
              </Table>
            </ScrollArea>
          </Card>
        </div>

        <Card className="p-4">
          <div className="text-sm font-medium mb-3">Verwendete Modelle</div>
          <div className="flex flex-wrap gap-2">
            {[
              ["Planner", models["planner"]],
              ["OpenAlex Queries", models["openalex_queries"]],
              ["S2 Queries", models["s2_queries"]],
              ["Rerank", models["rerank"]],
              ["Embedding", models["embedding"]],
            ].map(([label, v]) => (
              <div key={String(label)} className="rounded-md border border-border px-3 py-2 text-xs">
                <div className="text-muted-foreground">{String(label)}</div>
                <div className="font-medium mt-1">{typeof v === "string" && v.trim() ? v : "—"}</div>
              </div>
            ))}
          </div>
        </Card>

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-3">
          <ChartCard title="Publication Year (Ranked IDs)">
            <YearBarChart data={asRecordArray(asRecord(plots["publication_year"])["data"])} />
          </ChartCard>
          <ChartCard title="Citations (log10(1+cites))">
            <HistogramTwoPools data={asRecordArray(asRecord(plots["citations_log10"])["data"])} />
          </ChartCard>
          <ChartCard title="Coverage Tags Count">
            <CoverageTagsCountChart data={asRecordArray(asRecord(plots["coverage_tags_count"])["data"])} />
          </ChartCard>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
          <ChartCard title="LLM Rerank Score Distribution">
            <HistogramTwoPools data={asRecordArray(asRecord(plots["llm_score_distribution"])["data"])} />
          </ChartCard>
          <ChartCard title="LLM Score vs Lane Score">
            <LlmVsLaneScatter data={asRecordArray(asRecord(plots["llm_score_vs_lane_score"])["data"])} />
          </ChartCard>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
          <ChartCard title="Match Lane Distribution">
            <HistogramTwoPools data={asRecordArray(asRecord(plots["match_lane_distribution"])["data"])} />
          </ChartCard>
          <ChartCard title="Match vs Authority (Top 500)">
            <MatchVsAuthorityScatter data={asRecordArray(asRecord(plots["match_vs_authority_top500"])["data"])} />
          </ChartCard>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
          <ChartCard title="match: lane_score by rank (top 200)">
            <LaneScoreByRankChart
              withData={asRecordArray(byRank["match_with"])}
              withoutData={asRecordArray(byRank["match_without"])}
            />
          </ChartCard>
          <ChartCard title="authority: lane_score by rank (top 200)">
            <LaneScoreByRankChart
              withData={asRecordArray(byRank["authority_with"])}
              withoutData={asRecordArray(byRank["authority_without"])}
            />
          </ChartCard>
        </div>

        <ChartCard title="Coverage Tags">
          <CoverageTagsTopChart data={asRecordArray(asRecord(plots["coverage_tags_top"])["data"])} />
        </ChartCard>
      </div>
    </TooltipProvider>
  );
}

function ChartCard({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <Card className="p-4">
      <div className="text-sm font-medium mb-3">{title}</div>
      <div className="h-[260px]">{children}</div>
    </Card>
  );
}

function YearBarChart({ data }: { data: Array<Record<string, unknown>> }) {
  const rows = Array.isArray(data) ? data : [];
  return (
    <ChartContainer
      config={{
        with_abstract: { label: "with_abstract", color: "var(--chart-1)" },
        without_abstract: { label: "without_abstract", color: "var(--chart-2)" },
      }}
      className="h-full"
    >
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={rows}>
          <CartesianGrid vertical={false} strokeDasharray="3 3" />
          <XAxis dataKey="year" tickLine={false} axisLine={false} fontSize={10} />
          <YAxis tickLine={false} axisLine={false} fontSize={10} width={36} />
          <ChartTooltip content={<ChartTooltipContent />} />
          <ChartLegend content={<ChartLegendContent />} />
          <Bar dataKey="with_abstract" fill="var(--color-with_abstract)" radius={[3, 3, 0, 0]} />
          <Bar dataKey="without_abstract" fill="var(--color-without_abstract)" radius={[3, 3, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </ChartContainer>
  );
}

function HistogramTwoPools({ data }: { data: Array<Record<string, unknown>> }) {
  const rows = Array.isArray(data) ? data : [];
  const mapped = rows.map((r) => ({
    ...r,
    bin:
      typeof r["bin_lo"] === "number" && typeof r["bin_hi"] === "number"
        ? `${r["bin_lo"]}-${r["bin_hi"]}`
        : String(r["tag_count"] ?? r["bin"] ?? ""),
  }));
  const maxTicks = 10;
  const interval = Math.max(0, Math.ceil(mapped.length / maxTicks) - 1);

  const tickFormatter = (v: unknown) => {
    const s = String(v ?? "").trim();
    if (!s) return "";
    if (s.includes("+")) return s;
    if (!s.includes("-")) return s;

    const parts = s.split("-");
    if (parts.length < 2) return s;

    const lo = Number(parts[0]);
    const hi = Number(parts[1]);
    if (!Number.isFinite(lo) || !Number.isFinite(hi)) return s;

    const maxAbs = Math.max(Math.abs(lo), Math.abs(hi));
    const decimals = maxAbs <= 1 ? 2 : maxAbs <= 10 ? 1 : 0;
    const s2 = lo.toFixed(decimals);
    return s2.replace(/(\.\d*?[1-9])0+$/, "$1").replace(/\.0+$/, "");
  };
  return (
    <ChartContainer
      config={{
        with_abstract: { label: "with_abstract", color: "var(--chart-1)" },
        without_abstract: { label: "without_abstract", color: "var(--chart-2)" },
      }}
      className="h-full"
    >
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={mapped}>
          <CartesianGrid vertical={false} strokeDasharray="3 3" />
          <XAxis
            dataKey="bin"
            tickLine={false}
            axisLine={false}
            fontSize={10}
            interval={interval}
            tickFormatter={tickFormatter}
            minTickGap={8}
          />
          <YAxis tickLine={false} axisLine={false} fontSize={10} width={36} />
          <ChartTooltip content={<ChartTooltipContent hideLabel labelFormatter={(l) => <span className="font-mono">{String(l)}</span>} />} />
          <ChartLegend content={<ChartLegendContent />} />
          <Bar dataKey="with_abstract" fill="var(--color-with_abstract)" radius={[3, 3, 0, 0]} />
          <Bar dataKey="without_abstract" fill="var(--color-without_abstract)" radius={[3, 3, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </ChartContainer>
  );
}

function CoverageTagsCountChart({ data }: { data: Array<Record<string, unknown>> }) {
  const rows = Array.isArray(data) ? data : [];
  const mapped = rows.map((r) => ({
    ...r,
    bin: String(r["tag_count"] ?? ""),
  }));
  return <HistogramTwoPools data={mapped} />;
}

function LlmVsLaneScatter({ data }: { data: Array<Record<string, unknown>> }) {
  const rows = Array.isArray(data) ? data : [];
  const withData = rows.filter((r) => String(r["pool"] || "") === "with_abstract");
  const withoutData = rows.filter((r) => String(r["pool"] || "") === "without_abstract");
  return (
    <ChartContainer
      config={{
        with: { label: "with_abstract", color: "var(--chart-1)" },
        without: { label: "without_abstract", color: "var(--chart-2)" },
      }}
      className="h-full"
    >
      <ResponsiveContainer width="100%" height="100%">
        <ScatterChart>
          <CartesianGrid strokeDasharray="3 3" />
          <XAxis dataKey="lane_score" type="number" tickLine={false} axisLine={false} fontSize={10} />
          <YAxis dataKey="llm_score" type="number" tickLine={false} axisLine={false} fontSize={10} width={36} />
          <ChartTooltip
            content={
              <ChartTooltipContent
                hideLabel
                labelFormatter={() => null}
              />
            }
          />
          <Scatter name="with_abstract" data={withData} fill="var(--chart-1)" fillOpacity={0.35} />
          <Scatter name="without_abstract" data={withoutData} fill="var(--chart-2)" fillOpacity={0.35} />
        </ScatterChart>
      </ResponsiveContainer>
    </ChartContainer>
  );
}

function MatchVsAuthorityScatter({ data }: { data: Array<Record<string, unknown>> }) {
  const rows = Array.isArray(data) ? data : [];
  const withData = rows.filter((r) => String(r["pool"] || "") === "with_abstract");
  const withoutData = rows.filter((r) => String(r["pool"] || "") === "without_abstract");
  return (
    <ChartContainer
      config={{
        with: { label: "with_abstract", color: "var(--chart-1)" },
        without: { label: "without_abstract", color: "var(--chart-2)" },
      }}
      className="h-full"
    >
      <ResponsiveContainer width="100%" height="100%">
        <ScatterChart>
          <CartesianGrid strokeDasharray="3 3" />
          <XAxis dataKey="match" type="number" tickLine={false} axisLine={false} fontSize={10} />
          <YAxis dataKey="authority" type="number" tickLine={false} axisLine={false} fontSize={10} width={36} />
          <ChartTooltip content={<ChartTooltipContent hideLabel />} />
          <Scatter name="with_abstract" data={withData} fill="var(--chart-1)" fillOpacity={0.35} />
          <Scatter name="without_abstract" data={withoutData} fill="var(--chart-2)" fillOpacity={0.35} />
        </ScatterChart>
      </ResponsiveContainer>
    </ChartContainer>
  );
}

function LaneScoreByRankChart({
  withData,
  withoutData,
}: {
  withData: Array<Record<string, unknown>>;
  withoutData: Array<Record<string, unknown>>;
}) {
  return (
    <ChartContainer
      config={{
        withLine: { label: "with_abstract", color: "var(--chart-1)" },
        withoutLine: { label: "without_abstract", color: "var(--chart-2)" },
      }}
      className="h-full"
    >
      <ResponsiveContainer width="100%" height="100%">
        <LineChart>
          <CartesianGrid vertical={false} strokeDasharray="3 3" />
          <XAxis dataKey="rank" type="number" tickLine={false} axisLine={false} fontSize={10} />
          <YAxis dataKey="lane_score" tickLine={false} axisLine={false} fontSize={10} width={36} />
          <ChartTooltip content={<ChartTooltipContent hideLabel />} />
          <Line data={Array.isArray(withData) ? withData : []} dataKey="lane_score" name="with_abstract" stroke="var(--chart-1)" dot={false} strokeWidth={2} />
          <Line data={Array.isArray(withoutData) ? withoutData : []} dataKey="lane_score" name="without_abstract" stroke="var(--chart-2)" dot={false} strokeWidth={2} />
        </LineChart>
      </ResponsiveContainer>
    </ChartContainer>
  );
}

function CoverageTagsTopChart({ data }: { data: Array<Record<string, unknown>> }) {
  const rows = (Array.isArray(data) ? data : []).map((r) => ({
    ...r,
    label: String(r["label"] || r["facet_id"] || ""),
    count: typeof r["count"] === "number" ? (r["count"] as number) : Number(r["count"] || 0),
  }));
  return (
    <ChartContainer
      config={{
        count: { label: "Count", color: "var(--chart-1)" },
      }}
      className="h-full"
    >
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={rows} layout="vertical" margin={{ left: 8, right: 12 }}>
          <CartesianGrid horizontal={false} strokeDasharray="3 3" />
          <XAxis type="number" tickLine={false} axisLine={false} fontSize={10} />
          <YAxis type="category" dataKey="label" tickLine={false} axisLine={false} fontSize={10} width={140} />
          <ChartTooltip content={<ChartTooltipContent hideLabel />} />
          <Bar dataKey="count" fill="var(--chart-1)" radius={[0, 3, 3, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </ChartContainer>
  );
}

function TabSkeleton() {
  return (
    <div className="space-y-3">
      <Card className="p-4">
        <Skeleton className="h-4 w-36" />
        <Skeleton className="h-24 w-full mt-4" />
      </Card>
    </div>
  );
}

function TermBadges({
  terms,
  limit = 0,
  variant = "secondary",
  badgeClassName,
  moreBadgeClassName,
}: {
  terms: string[];
  limit?: number;
  variant?: "secondary" | "outline" | "default" | "destructive";
  badgeClassName?: string;
  moreBadgeClassName?: string;
}) {
  const xs = Array.isArray(terms) ? terms : [];
  const shown = limit > 0 ? xs.slice(0, limit) : xs;
  const hidden = limit > 0 ? Math.max(0, xs.length - shown.length) : 0;
  return (
    <div className="flex flex-wrap gap-1.5">
      {shown.map((t) => (
        <Badge key={t} variant={variant} className={`text-[11px] font-normal ${badgeClassName || ""}`}>
          {t}
        </Badge>
      ))}
      {hidden ? (
        <Badge variant="outline" className={`text-[11px] font-normal tabular-nums ${moreBadgeClassName || ""}`}>
          +{hidden}
        </Badge>
      ) : null}
      {!xs.length ? <span className="text-xs text-muted-foreground">—</span> : null}
    </div>
  );
}

function PlanTab({ doc, loaded }: { doc: Record<string, unknown> | null | undefined; loaded: boolean }) {
  const [expandedFacetId, setExpandedFacetId] = useState<string | null>(null);
  const [showAllGlobalTerms, setShowAllGlobalTerms] = useState(false);

  if (!loaded) return <TabSkeleton />;
  if (!doc) return <div className="text-sm text-muted-foreground">Noch keine Daten für B: Planung.</div>;

  const d = asRecord(doc);
  const topicDe = String(d["topic_summary_de"] || "").trim();
  const topicEn = String(d["topic_summary_en"] || "").trim();
  const primary = asRecord(d["primary_context_anchors"]);
  const globalTerms = asRecord(d["global_canonical_terms"]);
  const exclusions = asRecord(d["global_exclusions"]);
  const facets = asRecordArray(d["facets"]);

  const primaryEn = asStringArray(primary["en"]);
  const primaryDe = asStringArray(primary["de"]);
  const globalTermsEn = asStringArray(globalTerms["en"]);
  const globalTermsDe = asStringArray(globalTerms["de"]);
  const exclusionsEn = asStringArray(exclusions["en"]);
  const exclusionsDe = asStringArray(exclusions["de"]);

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
        <Card className="p-4">
          <div className="text-sm font-medium mb-2">Topic Summary (DE)</div>
          <div className="text-sm leading-relaxed text-muted-foreground whitespace-pre-wrap">{topicDe || "—"}</div>
        </Card>
        <Card className="p-4">
          <div className="text-sm font-medium mb-2">Topic Summary (EN)</div>
          <div className="text-sm leading-relaxed text-muted-foreground whitespace-pre-wrap">{topicEn || "—"}</div>
        </Card>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-3">
        <Card className="p-4">
          <div className="flex items-center justify-between gap-2">
            <div className="text-sm font-medium">Primary Anchors</div>
            <Badge variant="outline" className="tabular-nums text-[11px] font-normal">
              {primaryEn.length + primaryDe.length}
            </Badge>
          </div>
          <div className="mt-3 space-y-3">
            <div>
              <div className="text-[11px] text-muted-foreground mb-1">EN</div>
              <TermBadges terms={primaryEn} />
            </div>
            <div>
              <div className="text-[11px] text-muted-foreground mb-1">DE</div>
              <TermBadges terms={primaryDe} />
            </div>
          </div>
        </Card>

        <Card className="p-4">
          <div className="flex items-center justify-between gap-2">
            <div className="text-sm font-medium">Global Terms</div>
            <Badge variant="outline" className="tabular-nums text-[11px] font-normal">
              {globalTermsEn.length + globalTermsDe.length}
            </Badge>
          </div>
          <div className="mt-3 space-y-3">
            <div>
              <div className="text-[11px] text-muted-foreground mb-1">EN</div>
              <TermBadges terms={globalTermsEn} limit={showAllGlobalTerms ? 0 : 10} />
            </div>
            <div>
              <div className="text-[11px] text-muted-foreground mb-1">DE</div>
              <TermBadges terms={globalTermsDe} limit={showAllGlobalTerms ? 0 : 10} />
            </div>
            {globalTermsEn.length > 10 || globalTermsDe.length > 10 ? (
              <button
                type="button"
                className="text-xs text-muted-foreground hover:text-foreground underline underline-offset-4"
                onClick={() => setShowAllGlobalTerms((v) => !v)}
              >
                {showAllGlobalTerms ? "Weniger anzeigen" : "Alle anzeigen"}
              </button>
            ) : null}
          </div>
        </Card>

        <Card className="p-4">
          <div className="flex items-center justify-between gap-2">
            <div className="text-sm font-medium">Global Exclusions</div>
            <Badge variant="outline" className="tabular-nums text-[11px] font-normal">
              {exclusionsEn.length + exclusionsDe.length}
            </Badge>
          </div>
          <div className="mt-3 space-y-3">
            <div>
              <div className="text-[11px] text-muted-foreground mb-1">EN</div>
              <TermBadges
                terms={exclusionsEn}
                variant="outline"
                badgeClassName="border-red-200 text-red-600"
                moreBadgeClassName="border-red-200 text-red-600"
              />
            </div>
            <div>
              <div className="text-[11px] text-muted-foreground mb-1">DE</div>
              <TermBadges
                terms={exclusionsDe}
                variant="outline"
                badgeClassName="border-red-200 text-red-600"
                moreBadgeClassName="border-red-200 text-red-600"
              />
            </div>
          </div>
        </Card>
      </div>

      <Card className="p-4">
        <div className="flex items-center justify-between gap-3 mb-3">
          <div className="text-sm font-medium">Facets</div>
          <div className="text-xs text-muted-foreground">Summary table (expand below for full details).</div>
        </div>
        <div className="overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-[80px]">Weight</TableHead>
                <TableHead className="w-[120px]">Type</TableHead>
                <TableHead className="w-[220px]">Facet</TableHead>
                <TableHead>Label (EN)</TableHead>
                <TableHead>Label (DE)</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {facets.map((f, idx) => {
                const facetId = String(f["facet_id"] || "");
                const isOpen = expandedFacetId === facetId;
                return (
                  <Fragment key={facetId || idx}>
                    <TableRow
                      className={`cursor-pointer ${isOpen ? "bg-muted/30" : ""}`}
                      onClick={() => setExpandedFacetId((prev) => (prev === facetId ? null : facetId))}
                    >
                      <TableCell className="tabular-nums">{formatIntDe(f["importance_weight"])}</TableCell>
                      <TableCell className="text-xs">{String(f["facet_type"] || "—")}</TableCell>
                      <TableCell className="font-mono text-xs">{facetId || "—"}</TableCell>
                      <TableCell className="text-xs">{String(f["facet_label_en"] || "—")}</TableCell>
                      <TableCell className="text-xs">{String(f["facet_label_de"] || "—")}</TableCell>
                    </TableRow>
                    {isOpen ? (
                      <TableRow className="bg-background">
                        <TableCell colSpan={5} className="p-0">
                          <div className="border-t border-border p-4 grid grid-cols-1 lg:grid-cols-2 gap-4">
                            <div>
                              <div className="text-xs font-medium mb-1">Text (DE)</div>
                              <div className="text-xs text-muted-foreground whitespace-pre-wrap">{String(f["text_de"] || "—")}</div>
                              <div className="text-xs font-medium mt-4 mb-1">Terms (DE)</div>
                              <div className="space-y-2">
                                <div>
                                  <div className="text-[11px] text-muted-foreground mb-1">Canonical</div>
                                  <TermBadges terms={asStringArray(asRecord(f["canonical_terms"])["de"])} />
                                </div>
                                <div>
                                  <div className="text-[11px] text-muted-foreground mb-1">Neighbors</div>
                                  <TermBadges terms={asStringArray(asRecord(f["neighbor_terms"])["de"])} variant="outline" />
                                </div>
                                <div>
                                  <div className="text-[11px] text-muted-foreground mb-1">Exclusions</div>
                                  <TermBadges terms={asStringArray(asRecord(f["exclusion_terms"])["de"])} variant="outline" />
                                </div>
                              </div>
                            </div>
                            <div>
                              <div className="text-xs font-medium mb-1">Text (EN)</div>
                              <div className="text-xs text-muted-foreground whitespace-pre-wrap">{String(f["text_en"] || "—")}</div>
                              <div className="text-xs font-medium mt-4 mb-1">Terms (EN)</div>
                              <div className="space-y-2">
                                <div>
                                  <div className="text-[11px] text-muted-foreground mb-1">Canonical</div>
                                  <TermBadges terms={asStringArray(asRecord(f["canonical_terms"])["en"])} />
                                </div>
                                <div>
                                  <div className="text-[11px] text-muted-foreground mb-1">Neighbors</div>
                                  <TermBadges terms={asStringArray(asRecord(f["neighbor_terms"])["en"])} variant="outline" />
                                </div>
                                <div>
                                  <div className="text-[11px] text-muted-foreground mb-1">Exclusions</div>
                                  <TermBadges terms={asStringArray(asRecord(f["exclusion_terms"])["en"])} variant="outline" />
                                </div>
                              </div>
                            </div>
                          </div>
                        </TableCell>
                      </TableRow>
                    ) : null}
                  </Fragment>
                );
              })}
              {!facets.length ? (
                <TableRow>
                  <TableCell colSpan={5} className="text-sm text-muted-foreground">
                    Keine Facets.
                  </TableCell>
                </TableRow>
              ) : null}
            </TableBody>
          </Table>
        </div>
      </Card>
    </div>
  );
}

function QueriesTab({ doc, loaded }: { doc: Record<string, unknown> | null | undefined; loaded: boolean }) {
  const [provider, setProvider] = useState<"openalex" | "semanticscholar">("openalex");
  if (!loaded) return <TabSkeleton />;
  if (!doc) return <div className="text-sm text-muted-foreground">Noch keine Daten für C: Querries.</div>;

  const d = asRecord(doc);
  const counts = asRecord(d["counts"]);
  const dist = asRecord(d["length_distribution"]);
  const distRows = asRecordArray(dist["data"]);
  const oaQueries = asRecordArray(d["openalex_queries"]);
  const s2Queries = asRecordArray(d["s2_queries"]);

  const list = provider === "openalex" ? oaQueries : s2Queries;

  return (
    <TooltipProvider delayDuration={150}>
      <div className="space-y-4">
        <div className="grid grid-cols-1 md:grid-cols-3 lg:grid-cols-6 gap-3">
          <KpiCard
            label="OpenAlex Queries"
            value={formatIntDe(counts["openalex_total"])}
            tooltip={
              <div className="text-xs">
                <span className="text-muted-foreground">Zero‑result queries:</span>{" "}
                <span className="tabular-nums">{formatIntDe(counts["openalex_zero_result_queries"])}</span>
              </div>
            }
          />
          <KpiCard
            label="S2 Queries"
            value={formatIntDe(counts["s2_total"])}
            tooltip={
              <div className="text-xs">
                <span className="text-muted-foreground">Zero‑result queries:</span>{" "}
                <span className="tabular-nums">{formatIntDe(counts["s2_zero_result_queries"])}</span>
              </div>
            }
          />
          <KpiCard label="Authority" value={formatIntDe(counts["authority_total"])} />
          <KpiCard label="Match" value={formatIntDe(counts["match_total"])} />
          <KpiCard label="Median Length" value={counts["median_length"] ? `${Math.round(Number(counts["median_length"]))} chars` : "—"} />
          <KpiCard label="Max Length" value={counts["max_length"] ? `${formatIntDe(counts["max_length"])} chars` : "—"} />
        </div>

        <ChartCard title="Query String Length Distribution">
          <QueryLengthDistributionChart data={distRows} />
        </ChartCard>

        <Card className="p-4">
            <div className="flex items-center justify-between gap-3 mb-3">
              <div className="text-sm font-medium">Generated Queries</div>
            <Tabs value={provider} onValueChange={(v) => setProvider(v as "openalex" | "semanticscholar")}>
              <TabsList className="h-8">
                <TabsTrigger value="openalex" className="text-xs">
                  OpenAlex ({oaQueries.length})
                </TabsTrigger>
                <TabsTrigger value="semanticscholar" className="text-xs">
                  Semantic Scholar ({s2Queries.length})
                </TabsTrigger>
              </TabsList>
            </Tabs>
          </div>

          <ScrollArea className="h-[520px]">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-[60px]">#</TableHead>
                  <TableHead className="w-[140px]">Intent / Lang</TableHead>
                  <TableHead>Query</TableHead>
                  <TableHead className="w-[260px] hidden xl:table-cell">Notes</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {list.map((q, idx) => {
                  const i = typeof q["i"] === "number" ? (q["i"] as number) : idx + 1;
                  const intent = String(q["intent"] || "unknown");
                  const lang = String(q["language"] || "unknown");
                  const qs = String(q["query_string"] || "");
                  const notes = String(q["notes"] || "");
                  const extraLine =
                    provider === "openalex"
                      ? `search_field=${String(q["search_field"] || "—")} | filters=${truncateChars(q["filters"], 120) || "—"} | sort=${String(q["sort"] || "—")} | per_page=${String(q["per_page"] || "—")}`
                      : "";

                  return (
                    <TableRow key={String(q["query_id"] || i)}>
                      <TableCell className="tabular-nums text-sm">{i}</TableCell>
                      <TableCell className="space-x-1">
                        <Badge variant="secondary" className="text-[11px] font-normal">
                          {intent}
                        </Badge>
                        <Badge variant="outline" className="text-[11px] font-normal">
                          {lang}
                        </Badge>
                      </TableCell>
                      <TableCell className="max-w-0">
                        <Tooltip>
                        <TooltipTrigger asChild>
                          <button type="button" className="w-full text-left">
                              <div className="text-sm leading-snug line-clamp-2 break-words">{qs || "—"}</div>
                              {provider === "openalex" ? (
                                <div className="mt-1 text-[11px] text-muted-foreground truncate">{extraLine}</div>
                              ) : null}
                            </button>
                          </TooltipTrigger>
                          <TooltipContent className="max-w-[60vw]">
                            <div className="text-xs font-mono whitespace-pre-wrap">{qs || "—"}</div>
                          </TooltipContent>
                        </Tooltip>
                      </TableCell>
                      <TableCell className="hidden xl:table-cell text-xs text-muted-foreground max-w-[260px] align-top">
                        <div className="line-clamp-2 leading-snug break-words">{notes || "—"}</div>
                      </TableCell>
                    </TableRow>
                  );
                })}
                {!list.length ? (
                  <TableRow>
                    <TableCell colSpan={4} className="text-sm text-muted-foreground">
                      Keine Queries.
                    </TableCell>
                  </TableRow>
                ) : null}
              </TableBody>
            </Table>
          </ScrollArea>
        </Card>
      </div>
    </TooltipProvider>
  );
}

function QueryLengthDistributionChart({ data }: { data: Array<Record<string, unknown>> }) {
  const rows = (Array.isArray(data) ? data : []).map((r) => ({
    bin_lo: typeof r["bin_lo"] === "number" ? (r["bin_lo"] as number) : Number(r["bin_lo"] || 0),
    bin_hi: typeof r["bin_hi"] === "number" ? (r["bin_hi"] as number) : Number(r["bin_hi"] || 0),
    openalex: typeof r["openalex"] === "number" ? (r["openalex"] as number) : Number(r["openalex"] || 0),
    semanticscholar: typeof r["semanticscholar"] === "number" ? (r["semanticscholar"] as number) : Number(r["semanticscholar"] || 0),
  }));
  return (
    <ChartContainer
      config={{
        openalex: { label: "OpenAlex", color: "var(--chart-1)" },
        semanticscholar: { label: "S2", color: "var(--chart-2)" },
      }}
      className="h-full"
    >
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={rows}>
          <CartesianGrid vertical={false} strokeDasharray="3 3" />
          <XAxis dataKey="bin_lo" tickLine={false} axisLine={false} fontSize={10} tickFormatter={(v) => String(v)} />
          <YAxis tickLine={false} axisLine={false} fontSize={10} width={36} />
          <ChartTooltip
            content={
              <ChartTooltipContent
                labelFormatter={(v) => (
                  <span className="font-mono text-xs">
                    {String(v)}–{String(Number(v) + 10)} chars
                  </span>
                )}
              />
            }
          />
          <ChartLegend content={<ChartLegendContent />} />
          <Bar dataKey="openalex" fill="var(--color-openalex)" radius={[3, 3, 0, 0]} />
          <Bar dataKey="semanticscholar" fill="var(--color-semanticscholar)" radius={[3, 3, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </ChartContainer>
  );
}

function RetrievalTab({ doc, loaded }: { doc: Record<string, unknown> | null | undefined; loaded: boolean }) {
  const [zeroProvider, setZeroProvider] = useState<"openalex" | "semanticscholar">("openalex");
  if (!loaded) return <TabSkeleton />;
  if (!doc) return <div className="text-sm text-muted-foreground">Noch keine Daten für D: Retrival.</div>;

  const d = asRecord(doc);
  const totals = asRecord(d["provider_totals"]);
  const oa = asRecord(totals["openalex"]);
  const s2 = asRecord(totals["semanticscholar"]);

  const year = asRecord(d["year_distribution"]);
  const yearRows = asRecordArray(year["data"]);

  const providerSummary = asRecordArray(d["provider_summary"]);
  const ril = asRecord(d["records_by_intent_lang"]);
  const rilOa = asRecordArray(ril["openalex"]);
  const rilS2 = asRecordArray(ril["semanticscholar"]);

  const top = asRecord(d["top_queries"]);
  const bottom = asRecord(d["bottom_queries_nonzero"]);
  const zero = asRecord(d["zero_result_queries"]);

  const topRows = asRecordArray(top["data"]);
  const bottomRows = asRecordArray(bottom["data"]);
  const zeroRows = asRecordArray(zero["data"]);

  const truncated = !!zero["truncated"];
  const zeroTotal = typeof zero["total"] === "number" ? (zero["total"] as number) : zeroRows.length;
  const zeroOpenalex = zeroRows.filter((r) => String(r["provider"] || "") === "openalex");
  const zeroS2 = zeroRows.filter((r) => String(r["provider"] || "") === "semanticscholar");
  const zeroList = zeroProvider === "openalex" ? zeroOpenalex : zeroS2;

  return (
    <TooltipProvider delayDuration={150}>
      <div className="space-y-4">
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
          <Card className="p-3">
            <div className="flex items-center justify-between gap-2">
              <div className="text-sm font-medium flex items-center gap-2">
                <span className="inline-block h-2 w-2 rounded-full" style={{ background: "var(--chart-1)" }} />
                OpenAlex
              </div>
              <div className="text-xs text-muted-foreground tabular-nums">{formatIntDe(oa["records_total"])} Records</div>
            </div>
            <div className="mt-3 grid grid-cols-2 gap-4">
              <div>
                <div className="text-[11px] text-muted-foreground">Authority</div>
                <div className="text-lg font-semibold tabular-nums mt-1">{formatIntDe(oa["authority"])}</div>
              </div>
              <div>
                <div className="text-[11px] text-muted-foreground">Match</div>
                <div className="text-lg font-semibold tabular-nums mt-1">{formatIntDe(oa["match"])}</div>
              </div>
            </div>
            <div className="mt-2 text-xs text-muted-foreground tabular-nums">
              Abstract: {formatIntDe(oa["with_abstract"])} · Ohne: {formatIntDe(oa["without_abstract"])}
            </div>
          </Card>

          <Card className="p-3">
            <div className="flex items-center justify-between gap-2">
              <div className="text-sm font-medium flex items-center gap-2">
                <span className="inline-block h-2 w-2 rounded-full" style={{ background: "var(--chart-2)" }} />
                Semantic Scholar
              </div>
              <div className="text-xs text-muted-foreground tabular-nums">{formatIntDe(s2["records_total"])} Records</div>
            </div>
            <div className="mt-3 grid grid-cols-2 gap-4">
              <div>
                <div className="text-[11px] text-muted-foreground">Authority</div>
                <div className="text-lg font-semibold tabular-nums mt-1">{formatIntDe(s2["authority"])}</div>
              </div>
              <div>
                <div className="text-[11px] text-muted-foreground">Match</div>
                <div className="text-lg font-semibold tabular-nums mt-1">{formatIntDe(s2["match"])}</div>
              </div>
            </div>
            <div className="mt-2 text-xs text-muted-foreground tabular-nums">
              Abstract: {formatIntDe(s2["with_abstract"])} · Ohne: {formatIntDe(s2["without_abstract"])}
            </div>
          </Card>
        </div>

        <Card className="p-3">
          <div className="text-sm font-medium mb-2">Phase D — Provider Summary</div>
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Provider</TableHead>
                  <TableHead className="text-right">Queries</TableHead>
                  <TableHead className="text-right">Failed</TableHead>
                  <TableHead className="text-right hidden xl:table-cell">Failed %</TableHead>
                  <TableHead className="text-right">Records</TableHead>
                  <TableHead className="text-right hidden xl:table-cell">Zero Q</TableHead>
                  <TableHead className="text-right hidden xl:table-cell">Zero %</TableHead>
                  <TableHead className="text-right hidden xl:table-cell">Mean</TableHead>
                  <TableHead className="text-right hidden xl:table-cell">Median</TableHead>
                  <TableHead className="text-right hidden xl:table-cell">p90</TableHead>
                  <TableHead className="text-right hidden xl:table-cell">Max</TableHead>
                  <TableHead className="text-right hidden xl:table-cell">Dominance</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {providerSummary.map((r, idx) => (
                  <TableRow key={`${r["provider"]}-${idx}`}>
                    <TableCell className="text-sm">{String(r["provider"] || "—")}</TableCell>
                    <TableCell className="text-right tabular-nums text-sm">{formatIntDe(r["queries"])}</TableCell>
                    <TableCell className="text-right tabular-nums text-sm">{formatIntDe(r["failed"])}</TableCell>
                    <TableCell className="text-right tabular-nums text-sm hidden xl:table-cell">
                      {typeof r["failed_rate"] === "number" ? `${(Number(r["failed_rate"]) * 100).toFixed(1)}%` : "—"}
                    </TableCell>
                    <TableCell className="text-right tabular-nums text-sm">{formatIntDe(r["records"])}</TableCell>
                    <TableCell className="text-right tabular-nums text-sm hidden xl:table-cell">{formatIntDe(r["zero_q"])}</TableCell>
                    <TableCell className="text-right tabular-nums text-sm hidden xl:table-cell">
                      {typeof r["zero_rate"] === "number" ? `${(Number(r["zero_rate"]) * 100).toFixed(1)}%` : "—"}
                    </TableCell>
                    <TableCell className="text-right tabular-nums text-sm hidden xl:table-cell">{formatIntDe(r["mean"])}</TableCell>
                    <TableCell className="text-right tabular-nums text-sm hidden xl:table-cell">{formatIntDe(r["median"])}</TableCell>
                    <TableCell className="text-right tabular-nums text-sm hidden xl:table-cell">{formatIntDe(r["p90"])}</TableCell>
                    <TableCell className="text-right tabular-nums text-sm hidden xl:table-cell">{formatIntDe(r["max"])}</TableCell>
                    <TableCell className="text-right tabular-nums text-sm hidden xl:table-cell">
                      {typeof r["dominance"] === "number" ? `${(Number(r["dominance"]) * 100).toFixed(1)}%` : "—"}
                    </TableCell>
                  </TableRow>
                ))}
                {!providerSummary.length ? (
                  <TableRow>
                    <TableCell colSpan={12} className="text-sm text-muted-foreground">
                      Keine Daten.
                    </TableCell>
                  </TableRow>
                ) : null}
              </TableBody>
            </Table>
          </div>
        </Card>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
          <Card className="p-3">
            <div className="text-sm font-medium mb-2">OpenAlex — Records by intent/lang</div>
            <ScrollArea className="max-h-[160px]">
              <IntentLangTable rows={rilOa} />
            </ScrollArea>
          </Card>
          <Card className="p-3">
            <div className="text-sm font-medium mb-2">Semantic Scholar — Records by intent/lang</div>
            <ScrollArea className="max-h-[160px]">
              <IntentLangTable rows={rilS2} />
            </ScrollArea>
          </Card>
        </div>

        <ChartCard title="Year Distribution of Retrieved Records">
          <YearProviderChart data={yearRows} />
        </ChartCard>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
          <Card className="p-4">
            <div className="text-sm font-medium mb-3">Top 10 Queries (Most Results)</div>
            <ScrollArea className="h-[360px]">
              <QueryCountTable rows={topRows} />
            </ScrollArea>
          </Card>
          <Card className="p-4">
            <div className="text-sm font-medium mb-3">Bottom 10 Queries (Fewest Results)</div>
            <ScrollArea className="h-[360px]">
              <QueryCountTable rows={bottomRows} />
            </ScrollArea>
          </Card>
        </div>

        <Card className="p-4">
          <div className="flex items-center justify-between gap-3 mb-3">
            <div className="text-sm font-medium">Zero‑Result Queries</div>
            <div className="flex items-center gap-2">
              <Badge variant="outline" className="tabular-nums text-[11px] font-normal">
                {formatIntDe(zeroList.length)}
                {truncated ? ` von ${formatIntDe(zeroTotal)}` : ""}
              </Badge>
              <Tabs value={zeroProvider} onValueChange={(v) => setZeroProvider(v as "openalex" | "semanticscholar")}>
                <TabsList className="h-8">
                  <TabsTrigger value="openalex" className="text-xs">
                    OpenAlex ({zeroOpenalex.length})
                  </TabsTrigger>
                  <TabsTrigger value="semanticscholar" className="text-xs">
                    Semantic Scholar ({zeroS2.length})
                  </TabsTrigger>
                </TabsList>
              </Tabs>
            </div>
          </div>

          <ScrollArea className="h-[320px]">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-[60px]">#</TableHead>
                  <TableHead className="w-[160px]">Intent / Lang</TableHead>
                  <TableHead>Query ID</TableHead>
                  <TableHead className="text-right w-[60px]">Rec.</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {zeroList.map((r, idx) => {
                  const intent = String(r["intent"] || "");
                  const lang = String(r["lang"] || "");
                  const qid = String(r["query_id"] || "");
                  const qs = String(r["query_string"] || "");
                  return (
                    <TableRow key={qid || idx}>
                      <TableCell className="tabular-nums text-sm">{idx + 1}</TableCell>
                      <TableCell className="space-x-1">
                        <Badge variant="secondary" className="text-[11px] font-normal">
                          {intent || "—"}
                        </Badge>
                        <Badge variant="outline" className="text-[11px] font-normal">
                          {lang || "—"}
                        </Badge>
                      </TableCell>
                      <TableCell className="max-w-0">
                        <Tooltip>
                          <TooltipTrigger asChild>
                            <button type="button" className="w-full text-left">
                              <div className="font-mono text-xs truncate">{qid || "—"}</div>
                            </button>
                          </TooltipTrigger>
                          <TooltipContent className="max-w-[60vw]">
                            <div className="text-xs font-mono whitespace-pre-wrap">{qs || "—"}</div>
                          </TooltipContent>
                        </Tooltip>
                      </TableCell>
                      <TableCell className="text-right tabular-nums text-sm text-muted-foreground">0</TableCell>
                    </TableRow>
                  );
                })}
                {!zeroList.length ? (
                  <TableRow>
                    <TableCell colSpan={4} className="text-sm text-muted-foreground">
                      Keine Zero‑Result Queries.
                    </TableCell>
                  </TableRow>
                ) : null}
              </TableBody>
            </Table>
          </ScrollArea>

          {truncated ? (
            <div className="mt-2 text-xs text-muted-foreground">+ weitere {formatIntDe(Math.max(0, zeroTotal - zeroRows.length))}…</div>
          ) : null}
        </Card>
      </div>
    </TooltipProvider>
  );
}

function IntentLangTable({ rows }: { rows: Array<Record<string, unknown>> }) {
  const xs = Array.isArray(rows) ? rows : [];
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Intent</TableHead>
          <TableHead>Lang</TableHead>
          <TableHead className="text-right">Records</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {xs.map((r, idx) => (
          <TableRow key={`${r["intent"]}-${r["lang"]}-${idx}`}>
            <TableCell className="text-sm">{String(r["intent"] || "—")}</TableCell>
            <TableCell className="text-sm">{String(r["lang"] || "—")}</TableCell>
            <TableCell className="text-right tabular-nums text-sm">{formatIntDe(r["records"])}</TableCell>
          </TableRow>
        ))}
        {!xs.length ? (
          <TableRow>
            <TableCell colSpan={3} className="text-sm text-muted-foreground">
              Keine Daten.
            </TableCell>
          </TableRow>
        ) : null}
      </TableBody>
    </Table>
  );
}

function YearProviderChart({ data }: { data: Array<Record<string, unknown>> }) {
  const rows = (Array.isArray(data) ? data : []).map((r) => ({
    year: String(r["year"] ?? ""),
    openalex: typeof r["openalex"] === "number" ? (r["openalex"] as number) : Number(r["openalex"] || 0),
    semanticscholar: typeof r["semanticscholar"] === "number" ? (r["semanticscholar"] as number) : Number(r["semanticscholar"] || 0),
  }));
  return (
    <ChartContainer
      config={{
        openalex: { label: "OpenAlex", color: "var(--chart-1)" },
        semanticscholar: { label: "S2", color: "var(--chart-2)" },
      }}
      className="h-full"
    >
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={rows}>
          <CartesianGrid vertical={false} strokeDasharray="3 3" />
          <XAxis dataKey="year" tickLine={false} axisLine={false} fontSize={10} />
          <YAxis tickLine={false} axisLine={false} fontSize={10} width={36} />
          <ChartTooltip content={<ChartTooltipContent />} />
          <ChartLegend content={<ChartLegendContent />} />
          <Bar dataKey="openalex" fill="var(--color-openalex)" radius={[3, 3, 0, 0]} />
          <Bar dataKey="semanticscholar" fill="var(--color-semanticscholar)" radius={[3, 3, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </ChartContainer>
  );
}

function QueryCountTable({ rows }: { rows: Array<Record<string, unknown>> }) {
  const xs = Array.isArray(rows) ? rows : [];
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead className="w-[60px]">#</TableHead>
          <TableHead>Query</TableHead>
          <TableHead className="text-right w-[90px]">Records</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {xs.map((r, idx) => {
          const provider = String(r["provider"] || "");
          const intent = String(r["intent"] || "");
          const lang = String(r["lang"] || "");
          const qid = String(r["query_id"] || "");
          const qs = String(r["query_string"] || "");
          const records = r["records"];
          return (
            <TableRow key={qid || idx}>
              <TableCell className="tabular-nums text-sm">{idx + 1}</TableCell>
              <TableCell className="min-w-0">
                <Tooltip>
                  <TooltipTrigger asChild>
                    <div className="flex items-center gap-2 min-w-0 cursor-default">
                      <Badge variant="secondary" className="text-[11px] font-normal">
                        {intent || "—"}
                      </Badge>
                      <Badge variant="outline" className="text-[11px] font-normal">
                        {lang || "—"}
                      </Badge>
                      <span className="text-xs text-muted-foreground truncate">{provider}</span>
                      <span className="font-mono text-xs truncate">{qid}</span>
                    </div>
                  </TooltipTrigger>
                  <TooltipContent className="max-w-[60vw]">
                    <div className="text-xs font-mono whitespace-pre-wrap">{qs || "—"}</div>
                  </TooltipContent>
                </Tooltip>
              </TableCell>
              <TableCell className="text-right tabular-nums text-sm">{formatIntDe(records)}</TableCell>
            </TableRow>
          );
        })}
        {!xs.length ? (
          <TableRow>
            <TableCell colSpan={3} className="text-sm text-muted-foreground">
              Keine Daten.
            </TableCell>
          </TableRow>
        ) : null}
      </TableBody>
    </Table>
  );
}

function CandidatesTab({ doc, loaded }: { doc: Record<string, unknown> | null | undefined; loaded: boolean }) {
  const [openId, setOpenId] = useState<string | null>(null);
  if (!loaded) return <TabSkeleton />;
  if (!doc) return <div className="text-sm text-muted-foreground">Noch keine Daten für E: Kandidaten.</div>;

  const d = asRecord(doc);
  const counts = asRecord(d["counts"]);
  const poolDist = asRecord(d["pool_distribution"]);
  const poolRows = asRecordArray(poolDist["data"]);

  const withRow = poolRows.find((r) => String(r["pool"]) === "with_abstract");
  const withoutRow = poolRows.find((r) => String(r["pool"]) === "without_abstract");
  const nWith = typeof withRow?.["n"] === "number" ? (withRow?.["n"] as number) : Number(withRow?.["n"] || 0);
  const nWithout = typeof withoutRow?.["n"] === "number" ? (withoutRow?.["n"] as number) : Number(withoutRow?.["n"] || 0);
  const totalPools = Math.max(0, nWith + nWithout);
  const pctWith = totalPools ? (nWith / totalPools) * 100 : 0;
  const pctWithout = totalPools ? (nWithout / totalPools) * 100 : 0;

  const topCited = asRecordArray(d["top_cited"]);
  const topNoAnchors = asRecordArray(d["top_cited_no_anchors"]);
  const topEcon = asRecordArray(d["top_econ_hit"]);

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 md:grid-cols-3 lg:grid-cols-5 gap-3">
        <KpiCard label="Gesamt" value={formatIntDe(counts["candidates_total"])} />
        <KpiCard label="Normalized" value={formatIntDe(counts["normalized_total"])} />
        <KpiCard label="Duplikate entfernt" value={formatIntDe(counts["duplicates_removed"])} />
        <KpiCard label="Merged" value={formatIntDe(counts["merges"])} />
        <KpiCard label="DOI vorhanden" value={formatIntDe(counts["doi_present"])} />
      </div>

      <Card className="p-4">
        <div className="text-sm font-medium mb-2">Pool‑Verteilung</div>
        <div className="h-3 w-full rounded-full bg-muted overflow-hidden flex">
          <div style={{ width: `${pctWith}%`, background: "var(--chart-1)" }} />
          <div style={{ width: `${pctWithout}%`, background: "var(--chart-2)" }} />
        </div>
        <div className="mt-2 flex items-center justify-between text-xs text-muted-foreground">
          <div className="flex items-center gap-2 min-w-0">
            <span className="inline-block h-2 w-2 rounded-sm" style={{ background: "var(--chart-1)" }} />
            <span className="truncate">
              Mit Abstract ({totalPools ? pctWith.toFixed(1) : "0.0"}%)
            </span>
          </div>
          <div className="flex items-center gap-2 min-w-0">
            <span className="inline-block h-2 w-2 rounded-sm" style={{ background: "var(--chart-2)" }} />
            <span className="truncate">
              Ohne Abstract ({totalPools ? pctWithout.toFixed(1) : "0.0"}%)
            </span>
          </div>
        </div>
      </Card>

      <Card className="p-4">
        <div className="text-sm font-medium mb-3">Top‑zitierte Kandidaten</div>
        <ExpandableCandidateList items={topCited} openId={openId} onToggle={setOpenId} />
      </Card>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
        <Card className="p-4">
          <div className="text-sm font-medium mb-3">Top Cited but NO Anchors</div>
          <ScrollArea className="h-[360px] pr-2">
            <ExpandableCandidateList items={topNoAnchors} openId={openId} onToggle={setOpenId} compact />
          </ScrollArea>
        </Card>
        <Card className="p-4">
          <div className="text-sm font-medium mb-3">Top Econ‑Hit Candidates</div>
          <ScrollArea className="h-[360px] pr-2">
            <ExpandableCandidateList items={topEcon} openId={openId} onToggle={setOpenId} compact />
          </ScrollArea>
        </Card>
      </div>
    </div>
  );
}

function ExpandableCandidateList({
  items,
  openId,
  onToggle,
  compact = false,
}: {
  items: Array<Record<string, unknown>>;
  openId: string | null;
  onToggle: (id: string | null) => void;
  compact?: boolean;
}) {
  const xs = Array.isArray(items) ? items : [];
  return (
    <div className="divide-y divide-border rounded-md border border-border bg-card overflow-hidden">
      {xs.map((it, idx) => {
        const id = String(it["id"] || `${idx}`);
        const isOpen = openId === id;
        const title = String(it["title"] || "—");
        const authors = String(it["authors_preview"] || "—");
        const venue = String(it["venue"] || "—");
        const doi = String(it["doi"] || "");
        const year = it["year"];
        const citations = it["citations"];
        const pool = String(it["pool"] || "");
        const doiHref = doi ? `https://doi.org/${doi}` : "";
        const citeStr = typeof citations === "number" ? `${formatIntDe(citations)} cit.` : "";
        const yearStr = typeof year === "number" ? String(year) : "";
        const citeYear = citeStr && yearStr ? `${citeStr} ${yearStr}` : citeStr || yearStr;
        return (
          <div key={id} className="bg-card">
            <button
              type="button"
              className={`w-full text-left pl-3 pr-4 ${compact ? "py-2" : "py-2.5"} flex items-center gap-3 hover:bg-muted/20 ${isOpen ? "ring-1 ring-primary/40" : ""}`}
              onClick={() => onToggle(isOpen ? null : id)}
            >
              <div className="w-8 shrink-0 text-xs text-muted-foreground tabular-nums">{idx + 1}.</div>
              <div className="min-w-0 flex-1">
                <div className="text-sm truncate">{title}</div>
              </div>
              <div className="shrink-0 flex flex-wrap items-center justify-end gap-x-3 gap-y-1 text-xs text-muted-foreground tabular-nums">
                {citeYear ? <span>{citeYear}</span> : null}
                {pool ? (
                  <Badge variant="outline" className="text-[11px] font-normal">
                    {pool}
                  </Badge>
                ) : null}
                <ChevronDown className={`size-4 transition-transform ${isOpen ? "rotate-180" : ""}`} />
              </div>
            </button>
            {isOpen ? (
              <div className={`pl-11 pr-4 ${compact ? "py-2" : "py-3"} text-xs`}>
                <div className="grid gap-3">
                  <div>
                    <div className="text-[11px] text-muted-foreground">Title</div>
                    <div className="text-foreground break-words whitespace-normal">{title}</div>
                  </div>
                  <div>
                    <div className="text-[11px] text-muted-foreground">Author</div>
                    <div className="text-foreground break-words whitespace-normal">{authors}</div>
                  </div>
                  <div>
                    <div className="text-[11px] text-muted-foreground">Venue</div>
                    <div className="text-foreground break-words whitespace-normal">{venue}</div>
                  </div>
                  {doiHref ? (
                    <div>
                      <div className="text-[11px] text-muted-foreground">DOI</div>
                      <a
                        href={doiHref}
                        target="_blank"
                        rel="noreferrer"
                        className="text-primary underline underline-offset-4 break-words whitespace-normal"
                      >
                        {truncateChars(doi, 120)}
                      </a>
                    </div>
                  ) : null}
                </div>
              </div>
            ) : null}
          </div>
        );
      })}
      {!xs.length ? <div className="text-sm text-muted-foreground">Keine Kandidaten.</div> : null}
    </div>
  );
}

function ScoringTab({ doc, loaded }: { doc: Record<string, unknown> | null | undefined; loaded: boolean }) {
  if (!loaded) return <TabSkeleton />;
  if (!doc) return <div className="text-sm text-muted-foreground">Noch keine Daten für F: Scoring.</div>;

  const d = asRecord(doc);
  const kpis = asRecord(d["kpis"]);
  const hitRows = asRecordArray(d["anchor_hit_rate_top20"]);
  const matchRows = asRecordArray(asRecord(d["match_lane_distribution"])["data"]);
  const authorityRows = asRecordArray(asRecord(d["authority_lane_distribution"])["data"]);

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 md:grid-cols-3 lg:grid-cols-5 gap-3">
        <KpiCard label="Stage‑2 Candidates" value={formatIntDe(kpis["stage2_candidates"])} />
        <KpiCard label="Facets Used" value={formatIntDe(kpis["facets_used"])} />
        <KpiCard label="Kosten" value={formatUsd(kpis["cost_usd"])} />
        <KpiCard label="Stage‑2 Scored" value={formatIntDe(kpis["stage2_scored"])} />
        <KpiCard label="Pruning Kept" value={formatIntDe(kpis["pruning_kept_total"])} />
      </div>

      <Card className="p-4">
        <div className="text-sm font-medium mb-3">Anchor Hit Rate (Top 20)</div>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Lane</TableHead>
              <TableHead>Pool</TableHead>
              <TableHead className="text-right">Hit</TableHead>
              <TableHead className="text-right">Total</TableHead>
              <TableHead className="text-right">Pct</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {hitRows.map((r, idx) => {
              const pctRaw = typeof r["pct"] === "number" ? (r["pct"] as number) : Number(r["pct"] || NaN);
              const pctPercent = Number.isFinite(pctRaw) ? (pctRaw <= 1 ? pctRaw * 100 : pctRaw) : NaN;
              const pctCls = pctPercent >= 80 ? "text-emerald-600" : pctPercent >= 40 ? "text-amber-600" : "text-red-600";
              return (
                <TableRow key={`${r["lane"]}-${r["pool"]}-${idx}`}>
                  <TableCell className="text-sm">{String(r["lane"] || "—")}</TableCell>
                  <TableCell className="text-sm">{String(r["pool"] || "—")}</TableCell>
                  <TableCell className="text-right tabular-nums text-sm">{formatIntDe(r["hit"])}</TableCell>
                  <TableCell className="text-right tabular-nums text-sm">{formatIntDe(r["total"])}</TableCell>
                  <TableCell className={`text-right tabular-nums text-sm ${pctCls}`}>
                    {Number.isFinite(pctPercent) ? `${pctPercent.toFixed(1)}%` : "—"}
                  </TableCell>
                </TableRow>
              );
            })}
            {!hitRows.length ? (
              <TableRow>
                <TableCell colSpan={5} className="text-sm text-muted-foreground">
                  Keine Daten.
                </TableCell>
              </TableRow>
            ) : null}
          </TableBody>
        </Table>
      </Card>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
        <ChartCard title="Authority Lane Distribution">
          <HistogramTwoPools data={authorityRows} />
        </ChartCard>
        <ChartCard title="Match Lane Distribution">
          <HistogramTwoPools data={matchRows} />
        </ChartCard>
      </div>
    </div>
  );
}

function RerankTab({ doc, loaded }: { doc: Record<string, unknown> | null | undefined; loaded: boolean }) {
  if (!loaded) return <TabSkeleton />;
  if (!doc) return <div className="text-sm text-muted-foreground">Noch keine Daten für I: Rerank.</div>;

  const d = asRecord(doc);
  const kpis = asRecord(d["kpis"]);
  const distRows = asRecordArray(asRecord(d["llm_score_distribution"])["data"]);
  const tokens = asRecord(d["token_usage"]);

  const calls = formatIntDe(kpis["api_calls"]);
  const failures = formatIntDe(kpis["failures"]);
  const latency = typeof kpis["latency_s_p50"] === "number" ? (kpis["latency_s_p50"] as number) : Number(kpis["latency_s_p50"] || NaN);

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 md:grid-cols-3 lg:grid-cols-6 gap-3">
        <KpiCard label="Model" value={String(kpis["model"] || "—")} />
        <KpiCard label="Tasks" value={formatIntDe(kpis["tasks_total"])} />
        <KpiCard label="Calls / Failures" value={`${calls} / ${failures}`} />
        <KpiCard label="Kosten" value={formatUsd(kpis["cost_usd_total"])} />
        <KpiCard label="Insufficient" value={formatIntDe(kpis["insufficient_total"])} />
        <KpiCard label="p50 Latency" value={Number.isFinite(latency) ? `${latency.toFixed(1)}s` : "—"} />
      </div>

      <ChartCard title="LLM Score Distribution (0‑100)">
        <HistogramTwoPools data={distRows} />
      </ChartCard>

      <Card className="p-4">
        <div className="text-sm font-medium mb-3">Token Usage</div>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          <KpiCard label="Input Tokens" value={formatIntDe(tokens["input_tokens_total"])} />
          <KpiCard label="Output Tokens" value={formatIntDe(tokens["output_tokens_total"])} />
        </div>
      </Card>
    </div>
  );
}
