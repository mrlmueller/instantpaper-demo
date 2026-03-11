"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { type ReactNode, useDeferredValue, useEffect, useMemo, useRef, useState, useTransition } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  Scatter,
  ScatterChart,
  XAxis,
  YAxis,
} from "recharts";
import { ExternalLink } from "lucide-react";

import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from "@/components/ui/accordion";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ChartContainer, ChartLegend, ChartLegendContent, ChartTooltip, ChartTooltipContent } from "@/components/ui/chart";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { cn } from "@/lib/utils";
import type {
  CandidateRow,
  DashboardPayload,
  DashboardTab,
  LabelValue,
  LeaderboardSection,
  OverviewMetric,
  PairwiseDecision,
  PromptTraceAttempt,
  PromptTraceGroup,
  QueryRow,
  RunComparison,
  RunDetail,
} from "@/lib/dashboard-types";

type DetailState =
  | { kind: "prompt"; groupLabel: string; attempt: PromptTraceAttempt }
  | { kind: "query"; row: QueryRow }
  | { kind: "candidate"; candidateId: string }
  | { kind: "pairwise"; decision: PairwiseDecision }
  | null;

const TAB_ORDER: Array<{ id: DashboardTab; label: string }> = [
  { id: "overview", label: "Overview" },
  { id: "plan", label: "B Plan" },
  { id: "queries", label: "C Queries" },
  { id: "retrieval", label: "D Retrieval" },
  { id: "candidates", label: "E Candidates" },
  { id: "scoring", label: "F Scoring" },
  { id: "coverage", label: "G/H Coverage" },
  { id: "rerank", label: "I Rerank" },
  { id: "final", label: "Final" },
  { id: "compare", label: "Compare" },
];

function formatNumber(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) {
    return "—";
  }
  return new Intl.NumberFormat("en-US").format(value);
}

function formatDate(value: string): string {
  if (!value) {
    return "—";
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return "—";
  }
  return new Intl.DateTimeFormat("en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(parsed);
}

function formatCompactBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes <= 0) {
    return "0 MB";
  }
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function scoreBadge(value: number | null): string {
  if (value === null || !Number.isFinite(value)) {
    return "—";
  }
  return value.toFixed(3);
}

function truncateText(value: string, max: number): string {
  const collapsed = value.replace(/\s+/g, " ").trim();
  if (!collapsed) {
    return "";
  }
  if (collapsed.length <= max) {
    return collapsed;
  }
  return `${collapsed.slice(0, max - 1).trimEnd()}…`;
}

function classNames(...values: Array<string | false | null | undefined>): string {
  return values.filter(Boolean).join(" ");
}

function statusBadgeVariant(value: string): "success" | "warning" | "secondary" {
  const lower = value.toLowerCase();
  if (lower.includes("complete")) {
    return "success";
  }
  if (lower.includes("partial")) {
    return "warning";
  }
  return "secondary";
}

function uniqueStrings(values: string[]): string[] {
  return [...new Set(values)];
}

function findCandidateInRun(run: RunDetail, candidateId: string): CandidateRow | null {
  const collections = [
    run.candidates.catalog,
    run.candidates.topCited,
    run.candidates.mergedCandidates,
    run.candidates.noAnchorTopCited,
    run.candidates.econHitCandidates,
    run.candidates.weakestMetadata,
    ...run.scoring.stage1.map((section) => section.rows),
    ...run.scoring.stage2.map((section) => section.rows),
    ...run.scoring.final.map((section) => section.rows),
    ...run.coverage.stageGRankings.map((section) => section.rows),
    run.coverage.coverageRich,
    ...run.rerank.laneRankings.map((section) => section.rows),
    run.rerank.highSignal,
    run.rerank.offTopic,
    run.rerank.insufficient,
    ...run.final.outputs.map((section) => section.rows),
  ];

  for (const rows of collections) {
    const match = rows.find((row) => row.id === candidateId);
    if (match) {
      return match;
    }
  }

  return null;
}

function MetricCard({ metric }: { metric: OverviewMetric }) {
  return (
    <Card className="gap-0 border-border/70 bg-card/95 shadow-sm">
      <CardHeader className="pb-2">
        <CardDescription className="dashboard-card-label">{metric.label}</CardDescription>
        <CardTitle className="dashboard-card-value text-2xl">{metric.value}</CardTitle>
      </CardHeader>
      {metric.detail ? (
        <CardContent className="pt-0">
          <p className="dashboard-card-detail">{metric.detail}</p>
        </CardContent>
      ) : null}
    </Card>
  );
}

function LabelGrid({ items }: { items: LabelValue[] }) {
  return (
    <div className="label-grid">
      {items.map((item) => (
        <Card className="gap-0 border-border/70 bg-muted/35 shadow-none" key={`${item.label}:${item.value}`}>
          <CardContent className="space-y-2 px-4 py-4">
            <div className="label-grid-label">{item.label}</div>
            <div className="label-grid-value">{item.value}</div>
            {item.detail ? <p className="dashboard-card-detail">{item.detail}</p> : null}
          </CardContent>
        </Card>
      ))}
    </div>
  );
}

function SectionHeader({
  eyebrow,
  title,
  description,
  actions,
}: {
  eyebrow?: string;
  title: string;
  description?: string;
  actions?: ReactNode;
}) {
  return (
    <div className="section-header items-start">
      <div>
        {eyebrow ? <div className="section-eyebrow">{eyebrow}</div> : null}
        <h2 className="section-title">{title}</h2>
        {description ? <p className="section-description">{description}</p> : null}
      </div>
      {actions ? <div className="section-actions">{actions}</div> : null}
    </div>
  );
}

function PromptGroupCard({
  group,
  onOpen,
}: {
  group: PromptTraceGroup;
  onOpen: (groupLabel: string, attempt: PromptTraceAttempt) => void;
}) {
  return (
    <Card className="border-border/70 bg-card/95 shadow-sm">
      <CardHeader>
        <CardDescription className="dashboard-card-label">{group.label}</CardDescription>
        <CardTitle className="dashboard-card-value text-2xl">
          {group.attempts.length} trace{group.attempts.length === 1 ? "" : "s"}
        </CardTitle>
        <CardDescription>{group.blurb}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-2">
        {group.attempts.map((attempt) => (
          <Button className="mini-row h-auto w-full justify-between rounded-lg px-3 py-3" key={attempt.id} onClick={() => onOpen(group.label, attempt)} type="button" variant="outline">
            <span>{attempt.label}</span>
            <span className="text-muted-foreground">{attempt.model}</span>
          </Button>
        ))}
      </CardContent>
    </Card>
  );
}

function DataTable({
  columns,
  rows,
  renderRow,
  empty,
}: {
  columns: string[];
  rows: unknown[];
  renderRow: (row: unknown, index: number) => ReactNode;
  empty: string;
}) {
  if (!rows.length) {
    return <div className="dashboard-empty">{empty}</div>;
  }

  return (
    <div className="table-shell rounded-xl border border-border/70">
      <Table className="dashboard-table min-w-[680px]">
        <TableHeader>
          <TableRow>
            {columns.map((column) => (
              <TableHead key={column}>{column}</TableHead>
            ))}
          </TableRow>
        </TableHeader>
        <TableBody>{rows.map((row, index) => renderRow(row, index))}</TableBody>
      </Table>
    </div>
  );
}

function CandidateAccordion({
  title,
  description,
  rows,
  onOpen,
}: {
  title: string;
  description?: string;
  rows: CandidateRow[];
  onOpen?: (candidateId: string) => void;
}) {
  if (!rows.length) {
    return <div className="dashboard-empty">No rows available.</div>;
  }

  return (
    <Card className="border-border/70 bg-card/95 shadow-sm">
      <CardHeader>
        <CardDescription className="dashboard-card-label">{title}</CardDescription>
        {description ? <CardDescription>{description}</CardDescription> : null}
      </CardHeader>
      <CardContent className="pt-0">
        <Accordion className="candidate-accordion-list" type="multiple">
          {rows.map((row, index) => (
            <AccordionItem className="candidate-accordion rounded-xl border border-border/70 bg-card px-4" key={`${title}:${row.id}:${index}`} value={`${title}:${row.id}:${index}`}>
              <AccordionTrigger className="candidate-accordion-summary py-4 hover:no-underline">
                <div className="candidate-title-block">
                  <span className="candidate-rank">#{index + 1}</span>
                  <div className="space-y-1 text-left">
                    <strong className="block text-sm font-semibold leading-6">{row.title}</strong>
                    <div className="muted-copy">
                      {row.year ?? "—"} · {row.venue || "Unknown venue"} · {row.citations} citations
                    </div>
                  </div>
                </div>
                <div className="candidate-summary-metrics">
                  <Badge variant="outline">{row.pool === "with_abstract" ? "with abstract" : "without abstract"}</Badge>
                  <span className="score-pill">{scoreBadge(Math.max(row.rerankMatch ?? -1, row.rerankAuthority ?? -1, row.matchLane ?? -1, row.authorityLane ?? -1))}</span>
                </div>
              </AccordionTrigger>
              <AccordionContent className="candidate-accordion-body pt-1">
                <div className="candidate-grid">
                  <div className="stack gap-3">
                    <p className="copy-block text-sm leading-7">{row.abstractPreview || "No abstract preview stored."}</p>
                    {row.coverageExcerpt ? (
                      <Card className="gap-0 border-border/70 bg-muted/25 shadow-none">
                        <CardHeader className="pb-2">
                          <CardTitle className="text-sm">Coverage excerpt</CardTitle>
                        </CardHeader>
                        <CardContent className="pt-0">
                          <p className="copy-block text-sm">{row.coverageExcerpt}</p>
                        </CardContent>
                      </Card>
                    ) : null}
                    {row.rerankSummary ? (
                      <Card className="gap-0 border-border/70 bg-muted/25 shadow-none">
                        <CardHeader className="pb-2">
                          <CardTitle className="text-sm">Rerank note</CardTitle>
                        </CardHeader>
                        <CardContent className="pt-0">
                          <p className="copy-block text-sm">{row.rerankSummary}</p>
                        </CardContent>
                      </Card>
                    ) : null}
                  </div>
                  <div className="stack gap-3">
                    <LabelGrid
                      items={[
                        { label: "Match", value: scoreBadge(row.matchLane) },
                        { label: "Authority", value: scoreBadge(row.authorityLane) },
                        { label: "Rerank M", value: scoreBadge(row.rerankMatch) },
                        { label: "Rerank A", value: scoreBadge(row.rerankAuthority) },
                        { label: "Req hits", value: `${row.requiredFacetHits}` },
                        { label: "Tags", value: `${row.tagCount}` },
                      ]}
                    />
                    <div className="chip-cloud">
                      {row.topFacets.map((facet, facetIndex) => (
                        <Badge className="data-chip px-3 py-1" key={`${row.id}:facet:${facetIndex}`} variant="secondary">
                          {facet}
                        </Badge>
                      ))}
                    </div>
                    <div className="stack gap-2 text-sm">
                      {row.resourceUrl ? (
                        <Button asChild className="w-fit px-0" variant="link">
                          <a className="resource-link" href={row.resourceUrl} rel="noreferrer" target="_blank">
                            Open resource <ExternalLink className="size-3.5" />
                          </a>
                        </Button>
                      ) : null}
                      {row.doi ? <div className="muted-copy">DOI: {row.doi}</div> : null}
                      {row.authorsLabel ? <div className="muted-copy">Authors: {row.authorsLabel}</div> : null}
                    </div>
                    {row.evidenceSnippets.length ? (
                      <Button onClick={() => onOpen?.(row.id)} type="button" variant="outline">
                        Open focused detail
                      </Button>
                    ) : null}
                  </div>
                </div>
              </AccordionContent>
            </AccordionItem>
          ))}
        </Accordion>
      </CardContent>
    </Card>
  );
}

function ChartCard({
  title,
  description,
  children,
  tall = false,
}: {
  title: string;
  description?: string;
  children: ReactNode;
  tall?: boolean;
}) {
  return (
    <Card className="border-border/70 bg-card/95 shadow-sm">
      <CardHeader className="pb-3">
        <CardDescription className="dashboard-card-label">{title}</CardDescription>
        {description ? <CardDescription>{description}</CardDescription> : null}
      </CardHeader>
      <CardContent>
        <div className={classNames("chart-shell", tall && "chart-shell-tall")}>{children}</div>
      </CardContent>
    </Card>
  );
}

function ChartEmpty({ message }: { message: string }) {
  return <div className="chart-empty">{message}</div>;
}

function ChartSurface({
  children,
  loadingMessage = "Preparing chart…",
}: {
  children: (size: { width: number; height: number }) => ReactNode;
  loadingMessage?: string;
}) {
  const ref = useRef<HTMLDivElement | null>(null);
  const [size, setSize] = useState({ width: 0, height: 0 });

  useEffect(() => {
    const element = ref.current;
    if (!element) {
      return;
    }

    let frame = 0;

    const updateSize = () => {
      const next = {
        width: Math.floor(element.clientWidth),
        height: Math.floor(element.clientHeight),
      };
      setSize((current) => {
        if (current.width === next.width && current.height === next.height) {
          return current;
        }
        return next;
      });
    };

    updateSize();

    if (typeof ResizeObserver === "undefined") {
      return;
    }

    const observer = new ResizeObserver(() => {
      window.cancelAnimationFrame(frame);
      frame = window.requestAnimationFrame(updateSize);
    });

    observer.observe(element);

    return () => {
      window.cancelAnimationFrame(frame);
      observer.disconnect();
    };
  }, []);

  const ready = size.width > 0 && size.height > 0;

  return (
    <div className="chart-measure" ref={ref}>
      {ready ? children(size) : <ChartEmpty message={loadingMessage} />}
    </div>
  );
}

function PhaseDurationChart({ run }: { run: RunDetail }) {
  const rows = run.overview.timeline.filter((item) => item.seconds !== null).map((item) => ({ label: item.label, seconds: Number(item.seconds?.toFixed(1) ?? 0) }));
  if (!rows.length) {
    return <ChartEmpty message="No stage durations captured." />;
  }
  return (
    <ChartContainer config={{ seconds: { label: "seconds", color: "var(--chart-1)" } }}>
      <ChartSurface>
        {({ width, height }) => (
          <BarChart data={rows} height={height} width={width}>
            <CartesianGrid vertical={false} strokeDasharray="3 3" />
            <XAxis dataKey="label" tickLine={false} axisLine={false} fontSize={10} interval={0} angle={-20} textAnchor="end" height={56} />
            <YAxis tickLine={false} axisLine={false} fontSize={10} width={42} />
            <ChartTooltip content={<ChartTooltipContent />} />
            <Bar dataKey="seconds" fill="var(--color-seconds)" radius={[6, 6, 0, 0]} />
          </BarChart>
        )}
      </ChartSurface>
    </ChartContainer>
  );
}

function CountBarsChart({
  rows,
  label,
}: {
  rows: Array<{ label: string; value: number }>;
  label: string;
}) {
  if (!rows.length) {
    return <ChartEmpty message="No counts available." />;
  }
  return (
    <ChartContainer config={{ value: { label, color: "var(--chart-2)" } }}>
      <ChartSurface>
        {({ width, height }) => (
          <BarChart data={rows} height={height} width={width}>
            <CartesianGrid vertical={false} strokeDasharray="3 3" />
            <XAxis dataKey="label" tickLine={false} axisLine={false} fontSize={10} interval={0} angle={-16} textAnchor="end" height={52} />
            <YAxis tickLine={false} axisLine={false} fontSize={10} width={42} />
            <ChartTooltip content={<ChartTooltipContent />} />
            <Bar dataKey="value" fill="var(--color-value)" radius={[6, 6, 0, 0]} />
          </BarChart>
        )}
      </ChartSurface>
    </ChartContainer>
  );
}

function ProviderHitsChart({ providers }: { providers: Array<{ label: string; totalHits: number; queryCount: number }> }) {
  const rows = providers.map((provider) => ({
    label: provider.label,
    hits: provider.totalHits,
    queries: provider.queryCount,
  }));
  if (!rows.length) {
    return <ChartEmpty message="No provider summary available." />;
  }
  return (
    <ChartContainer
      config={{
        hits: { label: "hits", color: "var(--chart-1)" },
        queries: { label: "queries", color: "var(--chart-3)" },
      }}
    >
      <ChartSurface>
        {({ width, height }) => (
          <BarChart data={rows} height={height} width={width}>
            <CartesianGrid vertical={false} strokeDasharray="3 3" />
            <XAxis dataKey="label" tickLine={false} axisLine={false} fontSize={10} />
            <YAxis tickLine={false} axisLine={false} fontSize={10} width={42} />
            <ChartTooltip content={<ChartTooltipContent />} />
            <ChartLegend content={<ChartLegendContent />} />
            <Bar dataKey="hits" fill="var(--color-hits)" radius={[6, 6, 0, 0]} />
            <Bar dataKey="queries" fill="var(--color-queries)" radius={[6, 6, 0, 0]} />
          </BarChart>
        )}
      </ChartSurface>
    </ChartContainer>
  );
}

function QueryHitsChart({ rows }: { rows: QueryRow[] }) {
  const plotted = rows.slice(0, 8).map((row, index) => ({
    label: `${row.provider.slice(0, 2).toUpperCase()} ${index + 1}`,
    hits: row.hitCount,
  }));
  if (!plotted.length) {
    return <ChartEmpty message="No query-hit rows available." />;
  }
  return (
    <CountBarsChart label="hits" rows={plotted.map((row) => ({ label: row.label, value: row.hits }))} />
  );
}

function DecadeChart({ rows }: { rows: Array<{ decade: string; count: number }> }) {
  if (!rows.length) {
    return <ChartEmpty message="No publication-year spread available." />;
  }
  return (
    <ChartContainer config={{ count: { label: "count", color: "var(--chart-1)" } }}>
      <ChartSurface>
        {({ width, height }) => (
          <LineChart data={rows} height={height} width={width}>
            <CartesianGrid vertical={false} strokeDasharray="3 3" />
            <XAxis dataKey="decade" tickLine={false} axisLine={false} fontSize={10} />
            <YAxis tickLine={false} axisLine={false} fontSize={10} width={42} />
            <ChartTooltip content={<ChartTooltipContent />} />
            <Line dataKey="count" stroke="var(--color-count)" dot={false} strokeWidth={2.4} />
          </LineChart>
        )}
      </ChartSurface>
    </ChartContainer>
  );
}

function CandidatePoolChart({ run }: { run: RunDetail }) {
  const rows = run.candidates.poolSummary.map((pool) => ({ label: pool.label, value: pool.count }));
  return <CountBarsChart label="candidates" rows={rows} />;
}

function CitationScatterChart({ rows }: { rows: CandidateRow[] }) {
  const relevant = rows
    .filter((row) => (row.matchLane ?? row.authorityLane) !== null)
    .slice(0, 90)
    .map((row) => ({
      title: row.title,
      citations: Math.min(row.citations, 5000),
      lane: Math.max(row.matchLane ?? -1, row.authorityLane ?? -1),
      pool: row.pool,
    }));
  const withAbstract = relevant.filter((row) => row.pool === "with_abstract");
  const withoutAbstract = relevant.filter((row) => row.pool === "without_abstract");
  if (!relevant.length) {
    return <ChartEmpty message="No candidate scatter data available." />;
  }
  return (
    <ChartContainer
      config={{
        with: { label: "with abstract", color: "var(--chart-1)" },
        without: { label: "without abstract", color: "var(--chart-2)" },
      }}
    >
      <ChartSurface>
        {({ width, height }) => (
          <ScatterChart height={height} width={width}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="citations" type="number" tickLine={false} axisLine={false} fontSize={10} />
            <YAxis dataKey="lane" type="number" tickLine={false} axisLine={false} fontSize={10} width={42} />
            <ChartTooltip content={<ChartTooltipContent hideLabel />} />
            <ChartLegend content={<ChartLegendContent />} />
            <Scatter name="with abstract" data={withAbstract} fill="var(--chart-1)" fillOpacity={0.35} />
            <Scatter name="without abstract" data={withoutAbstract} fill="var(--chart-2)" fillOpacity={0.35} />
          </ScatterChart>
        )}
      </ChartSurface>
    </ChartContainer>
  );
}

function ScoreTrendChart({ sections }: { sections: LeaderboardSection[] }) {
  const series = sections.slice(0, 4).map((section) => ({
    key: section.id,
    label: section.label,
    points: section.rows.map((row, index) => ({
      rank: index + 1,
      score:
        section.id.includes("authority") ? row.authorityLane ?? row.rerankAuthority ?? 0 : row.matchLane ?? row.rerankMatch ?? 0,
    })),
  }));
  const maxLength = Math.max(...series.map((item) => item.points.length), 0);
  const rows = Array.from({ length: maxLength }, (_, index) => {
    const row: Record<string, number | null> = { rank: index + 1 };
    series.forEach((item) => {
      row[item.key] = item.points[index]?.score ?? null;
    });
    return row;
  });
  if (!rows.length) {
    return <ChartEmpty message="No leaderboard trend data available." />;
  }
  const colors = ["var(--chart-1)", "var(--chart-2)", "var(--chart-3)", "var(--chart-4)"];
  const config = Object.fromEntries(series.map((item, index) => [item.key, { label: item.label, color: colors[index] }]));
  return (
    <ChartContainer config={config}>
      <ChartSurface>
        {({ width, height }) => (
          <LineChart data={rows} height={height} width={width}>
            <CartesianGrid vertical={false} strokeDasharray="3 3" />
            <XAxis dataKey="rank" tickLine={false} axisLine={false} fontSize={10} />
            <YAxis tickLine={false} axisLine={false} fontSize={10} width={42} />
            <ChartTooltip content={<ChartTooltipContent />} />
            <ChartLegend content={<ChartLegendContent />} />
            {series.map((item, index) => (
              <Line dataKey={item.key} dot={false} key={item.key} stroke={colors[index]} strokeWidth={2.2} />
            ))}
          </LineChart>
        )}
      </ChartSurface>
    </ChartContainer>
  );
}

function FacetCoverageChart({ run }: { run: RunDetail }) {
  const rows = run.coverage.facetCoverage.map((item) => ({ label: truncateText(item.label, 28), count: item.hitCount }));
  if (!rows.length) {
    return <ChartEmpty message="No facet coverage data available." />;
  }
  return (
    <ChartContainer config={{ count: { label: "count", color: "var(--chart-1)" } }}>
      <ChartSurface>
        {({ width, height }) => (
          <BarChart data={rows} height={height} layout="vertical" margin={{ left: 0, right: 8 }} width={width}>
            <CartesianGrid horizontal={false} strokeDasharray="3 3" />
            <XAxis type="number" tickLine={false} axisLine={false} fontSize={10} />
            <YAxis dataKey="label" type="category" tickLine={false} axisLine={false} fontSize={10} width={120} />
            <ChartTooltip content={<ChartTooltipContent hideLabel />} />
            <Bar dataKey="count" fill="var(--color-count)" radius={[0, 6, 6, 0]} />
          </BarChart>
        )}
      </ChartSurface>
    </ChartContainer>
  );
}

function RerankScatterChart({ rows }: { rows: CandidateRow[] }) {
  const relevant = rows
    .filter((row) => row.rerankMatch !== null || row.rerankAuthority !== null)
    .map((row) => ({
      pool: row.pool,
      lane: Math.max(row.matchLane ?? -1, row.authorityLane ?? -1),
      rerank: Math.max(row.rerankMatch ?? -1, row.rerankAuthority ?? -1),
    }));
  const withAbstract = relevant.filter((row) => row.pool === "with_abstract");
  const withoutAbstract = relevant.filter((row) => row.pool === "without_abstract");
  if (!relevant.length) {
    return <ChartEmpty message="No rerank scatter data available." />;
  }
  return (
    <ChartContainer
      config={{
        with: { label: "with abstract", color: "var(--chart-1)" },
        without: { label: "without abstract", color: "var(--chart-2)" },
      }}
    >
      <ChartSurface>
        {({ width, height }) => (
          <ScatterChart height={height} width={width}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="lane" type="number" tickLine={false} axisLine={false} fontSize={10} />
            <YAxis dataKey="rerank" type="number" tickLine={false} axisLine={false} fontSize={10} width={42} />
            <ChartTooltip content={<ChartTooltipContent hideLabel />} />
            <ChartLegend content={<ChartLegendContent />} />
            <Scatter name="with abstract" data={withAbstract} fill="var(--chart-1)" fillOpacity={0.35} />
            <Scatter name="without abstract" data={withoutAbstract} fill="var(--chart-2)" fillOpacity={0.35} />
          </ScatterChart>
        )}
      </ChartSurface>
    </ChartContainer>
  );
}

function CompareOverlapChart({ comparison }: { comparison: RunComparison }) {
  const rows = comparison.overlaps.slice(0, 8).map((overlap) => ({
    label: truncateText(overlap.label.replace("stagei:", "").replace(":", " / "), 18),
    shared: overlap.overlapCount,
    selectedOnly: overlap.onlySelected.length,
    compareOnly: overlap.onlyCompare.length,
  }));
  if (!rows.length) {
    return <ChartEmpty message="No overlap data available." />;
  }
  return (
    <ChartContainer
      config={{
        shared: { label: "shared", color: "var(--chart-1)" },
        selectedOnly: { label: "selected only", color: "var(--chart-3)" },
        compareOnly: { label: "compare only", color: "var(--chart-2)" },
      }}
    >
      <ChartSurface>
        {({ width, height }) => (
          <BarChart data={rows} height={height} width={width}>
            <CartesianGrid vertical={false} strokeDasharray="3 3" />
            <XAxis dataKey="label" tickLine={false} axisLine={false} fontSize={10} interval={0} angle={-16} textAnchor="end" height={48} />
            <YAxis tickLine={false} axisLine={false} fontSize={10} width={42} />
            <ChartTooltip content={<ChartTooltipContent />} />
            <ChartLegend content={<ChartLegendContent />} />
            <Bar dataKey="shared" fill="var(--color-shared)" radius={[6, 6, 0, 0]} />
            <Bar dataKey="selectedOnly" fill="var(--color-selectedOnly)" radius={[6, 6, 0, 0]} />
            <Bar dataKey="compareOnly" fill="var(--color-compareOnly)" radius={[6, 6, 0, 0]} />
          </BarChart>
        )}
      </ChartSurface>
    </ChartContainer>
  );
}

function PlannerCompositionChart({ run }: { run: RunDetail }) {
  const rows = [
    { label: "Anchors", value: run.plan.anchorsEn.length + run.plan.anchorsDe.length },
    { label: "Core terms", value: run.plan.coreTermsEn.length + run.plan.coreTermsDe.length },
    { label: "Constraints", value: run.plan.constraints.length },
    { label: "Drift risks", value: run.plan.driftRisks.length },
    { label: "Blueprints", value: run.plan.blueprints.length },
    { label: "Facets", value: run.plan.facets.length },
  ].filter((row) => row.value > 0);

  return <CountBarsChart label="items" rows={rows} />;
}

function FacetDensityChart({ run }: { run: RunDetail }) {
  const rows = run.plan.facets.slice(0, 8).map((facet) => ({
    label: truncateText(facet.label, 18),
    canonical: facet.canonicalTerms.length + facet.canonicalTermsDe.length,
    neighbors: facet.neighborTerms.length,
    exclusions: facet.exclusions.length,
  }));

  if (!rows.length) {
    return <ChartEmpty message="No facet design data available." />;
  }

  return (
    <ChartContainer
      config={{
        canonical: { label: "canonical", color: "var(--chart-1)" },
        neighbors: { label: "neighbors", color: "var(--chart-3)" },
        exclusions: { label: "exclusions", color: "var(--chart-5)" },
      }}
    >
      <ChartSurface>
        {({ width, height }) => (
          <BarChart data={rows} height={height} width={width}>
            <CartesianGrid vertical={false} strokeDasharray="3 3" />
            <XAxis dataKey="label" tickLine={false} axisLine={false} fontSize={10} interval={0} angle={-16} textAnchor="end" height={52} />
            <YAxis tickLine={false} axisLine={false} fontSize={10} width={42} />
            <ChartTooltip content={<ChartTooltipContent />} />
            <ChartLegend content={<ChartLegendContent />} />
            <Bar dataKey="canonical" fill="var(--color-canonical)" radius={[6, 6, 0, 0]} />
            <Bar dataKey="neighbors" fill="var(--color-neighbors)" radius={[6, 6, 0, 0]} />
            <Bar dataKey="exclusions" fill="var(--color-exclusions)" radius={[6, 6, 0, 0]} />
          </BarChart>
        )}
      </ChartSurface>
    </ChartContainer>
  );
}

export function DashboardClient({
  initialData,
  initialTab,
}: {
  initialData: DashboardPayload;
  initialTab: DashboardTab;
}) {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const [isPending, startTransition] = useTransition();
  const [activeTab, setActiveTab] = useState<DashboardTab>(initialTab);
  const [runSearch, setRunSearch] = useState("");
  const [candidateSearch, setCandidateSearch] = useState("");
  const [detail, setDetail] = useState<DetailState>(null);

  const deferredRunSearch = useDeferredValue(runSearch);
  const deferredCandidateSearch = useDeferredValue(candidateSearch);
  const noCompareValue = "__none__";

  const selectedRun = initialData.selectedRun;
  const compareRun = initialData.compareRun;
  const comparison = initialData.comparison;

  const availableTabs = useMemo(() => {
    return TAB_ORDER.filter((tab) => tab.id !== "compare" || comparison);
  }, [comparison]);

  const filteredRuns = useMemo(() => {
    const query = deferredRunSearch.trim().toLowerCase();
    if (!query) {
      return initialData.runs;
    }
    return initialData.runs.filter((run) => {
      return [run.id, run.chapterTitle, run.topicSummary, ...run.focusTerms].join(" ").toLowerCase().includes(query);
    });
  }, [deferredRunSearch, initialData.runs]);

  const filteredCatalog = useMemo(() => {
    if (!selectedRun) {
      return [];
    }
    const query = deferredCandidateSearch.trim().toLowerCase();
    if (!query) {
      return selectedRun.candidates.catalog;
    }
    return selectedRun.candidates.catalog.filter((row) => {
      return [row.id, row.title, row.venue, ...row.topFacets].join(" ").toLowerCase().includes(query);
    });
  }, [deferredCandidateSearch, selectedRun]);

  function updateParams(next: { run?: string | null; compare?: string | null; tab?: DashboardTab }) {
    const params = new URLSearchParams(searchParams.toString());
    if (next.run === null) {
      params.delete("run");
    } else if (next.run) {
      params.set("run", next.run);
    }
    if (next.compare === null) {
      params.delete("compare");
    } else if (next.compare) {
      params.set("compare", next.compare);
    }
    if (next.tab) {
      params.set("tab", next.tab);
    }
    startTransition(() => {
      router.replace(`${pathname}?${params.toString()}`, { scroll: false });
    });
  }

  function selectRun(runId: string) {
    const compare = initialData.compareRunId === runId ? null : initialData.compareRunId;
    updateParams({ run: runId, compare, tab: activeTab === "compare" && !compare ? "overview" : activeTab });
  }

  function toggleCompare(runId: string) {
    const nextCompare = initialData.compareRunId === runId ? null : runId;
    updateParams({ run: initialData.selectedRunId, compare: runId === initialData.selectedRunId ? null : nextCompare, tab: nextCompare ? "compare" : activeTab === "compare" ? "overview" : activeTab });
  }

  function selectTab(tab: DashboardTab) {
    setActiveTab(tab);
    updateParams({ run: initialData.selectedRunId, compare: initialData.compareRunId, tab });
  }

  const selectedCandidate = detail?.kind === "candidate" && selectedRun ? findCandidateInRun(selectedRun, detail.candidateId) : null;

  return (
    <div className="dashboard-page">
      <div className="dashboard-main">
        {isPending ? <div className="loading-strip rounded-xl border border-border/70 bg-card/90 shadow-sm">Loading run data…</div> : null}
        {selectedRun ? (
          <>
            <Card className="hero-panel hero-panel-flat rounded-[28px] border-border/70 bg-card/95 shadow-sm">
              <div className="hero-topline">
                <div>
                  <div className="section-eyebrow">Notebook run review</div>
                  <h1 className="hero-title">{selectedRun.chapterTitle}</h1>
                  <p className="hero-copy">{selectedRun.topicSummary}</p>
                  <div className="hero-meta">
                    <span>{selectedRun.id}</span>
                    <span>{selectedRun.statusLabel}</span>
                    <span>{formatDate(selectedRun.modifiedAt)}</span>
                  </div>
                </div>
                <div className="hero-side">
                  <Badge className="run-chip" variant={statusBadgeVariant(selectedRun.statusLabel)}>
                    {selectedRun.statusLabel}
                  </Badge>
                  {compareRun ? (
                    <Badge className="compare-chip" variant="outline">
                      Compare active
                    </Badge>
                  ) : null}
                </div>
              </div>

              <div className="toolbar-grid">
                <label className="search-control">
                  <span>Primary run</span>
                  <Select onValueChange={selectRun} value={initialData.selectedRunId ?? ""}>
                    <SelectTrigger>
                      <SelectValue placeholder="Select run" />
                    </SelectTrigger>
                    <SelectContent>
                      {initialData.runs.map((run) => (
                        <SelectItem key={run.id} value={run.id}>
                          {run.chapterTitle}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </label>
                <label className="search-control">
                  <span>Compare run</span>
                  <Select
                    onValueChange={(value) =>
                      updateParams({
                        run: initialData.selectedRunId,
                        compare: value === noCompareValue ? null : value,
                        tab: value === noCompareValue ? (activeTab === "compare" ? "overview" : activeTab) : "compare",
                      })
                    }
                    value={initialData.compareRunId ?? noCompareValue}
                  >
                    <SelectTrigger>
                      <SelectValue placeholder="No comparison" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value={noCompareValue}>No comparison</SelectItem>
                      {initialData.runs
                        .filter((run) => run.id !== initialData.selectedRunId)
                        .map((run) => (
                          <SelectItem key={run.id} value={run.id}>
                            {run.chapterTitle}
                          </SelectItem>
                        ))}
                    </SelectContent>
                  </Select>
                </label>
                <label className="search-control">
                  <span>Find cached run</span>
                  <Input onChange={(event) => setRunSearch(event.target.value)} placeholder="chapter, topic, run id" value={runSearch} />
                </label>
              </div>

              <div className="hero-actions hero-actions-grid">
                {selectedRun.headerStats.map((metric, index) => (
                  <MetricCard key={`${metric.label}:${index}`} metric={metric} />
                ))}
              </div>
            </Card>

            <Accordion className="w-full" collapsible type="single">
              <AccordionItem className="overflow-hidden rounded-2xl border border-border/70 bg-card shadow-sm" value="runs">
                <AccordionTrigger className="px-5 py-4 hover:no-underline">
                  <div className="text-left">
                    <div className="section-eyebrow">Run browser</div>
                    <div className="text-sm font-semibold">Browse cached runs</div>
                  </div>
                </AccordionTrigger>
                <AccordionContent className="px-5 pb-5">
                  <ScrollArea className="max-h-[32rem]">
                    <div className="run-browser-grid pr-3">
                      {filteredRuns.map((run, index) => (
                        <Card className={cn("run-card border-border/70 bg-card shadow-sm", initialData.selectedRunId === run.id && "run-card-active border-primary/40")} key={`${run.id}:${index}`}>
                          <CardContent className="space-y-4 px-4 py-4">
                            <button className="run-card-main" onClick={() => selectRun(run.id)} type="button">
                              <div className="run-card-topline">
                                <Badge className="run-chip" variant={statusBadgeVariant(run.statusLabel)}>
                                  {run.statusLabel}
                                </Badge>
                                <span className="run-id">{run.id.slice(0, 8)}</span>
                              </div>
                              <h2>{run.chapterTitle}</h2>
                              <p>{truncateText(run.topicSummary, 170)}</p>
                              <div className="run-meta">
                                <span>{formatCompactBytes(run.totalBytes)}</span>
                                <span>{formatNumber(run.counts.candidates)} candidates</span>
                                <span>{formatDate(run.modifiedAt)}</span>
                              </div>
                            </button>
                            <div className="run-card-actions">
                              <Button onClick={() => selectRun(run.id)} type="button" variant="outline">
                                Open
                              </Button>
                              <Button onClick={() => toggleCompare(run.id)} type="button" variant="ghost">
                                {initialData.compareRunId === run.id ? "Clear compare" : "Compare"}
                              </Button>
                            </div>
                          </CardContent>
                        </Card>
                      ))}
                    </div>
                  </ScrollArea>
                </AccordionContent>
              </AccordionItem>
            </Accordion>

            <Tabs className="gap-4" onValueChange={(value) => selectTab(value as DashboardTab)} value={activeTab}>
              <TabsList className="tab-strip h-auto w-full justify-start overflow-x-auto rounded-2xl border border-border/70 bg-card p-1 shadow-sm">
                {availableTabs.map((tab, index) => (
                  <TabsTrigger className="tab-button min-h-10 flex-none rounded-xl px-4" key={`${tab.id}:${index}`} value={tab.id}>
                    {tab.label}
                  </TabsTrigger>
                ))}
              </TabsList>

              <Card className="content-panel content-panel-wide rounded-[24px] border-border/70 bg-card/95 shadow-sm">
                {renderTabContent({
                  activeTab,
                  comparison,
                  compareRun,
                  filteredCatalog,
                  onCandidateOpen: (candidateId) => setDetail({ kind: "candidate", candidateId }),
                  onPairwiseOpen: (decision) => setDetail({ kind: "pairwise", decision }),
                  onPromptOpen: (groupLabel, attempt) => setDetail({ kind: "prompt", groupLabel, attempt }),
                  onQueryOpen: (row) => setDetail({ kind: "query", row }),
                  run: selectedRun,
                  candidateSearch,
                  onCandidateSearch: setCandidateSearch,
                })}
              </Card>
            </Tabs>
          </>
        ) : (
          <Card className="border-border/70 bg-card/95 shadow-sm">
            <CardContent className="py-10">
              <div className="dashboard-empty">No runs found in `sources-v2/runs`.</div>
            </CardContent>
          </Card>
        )}
        <footer className="dashboard-footer">
          <span>Read-only view over local notebook artifacts in `sources-v2/runs`.</span>
          <span>No production FastAPI or Next.js state is involved.</span>
        </footer>
      </div>
      <Dialog onOpenChange={(open) => (!open ? setDetail(null) : undefined)} open={Boolean(detail)}>
        <DialogContent className="detail-modal max-h-[85vh] overflow-hidden border-border/70 bg-background p-0 shadow-xl">
          <DialogHeader className="border-b px-6 pt-6 pb-4">
            <DialogTitle>Run detail</DialogTitle>
            <DialogDescription>Focused inspection of the selected trace, query, candidate, or pairwise rerank decision.</DialogDescription>
          </DialogHeader>
          <ScrollArea className="max-h-[calc(85vh-88px)] px-6 py-5">{detail ? renderDetailPanel(detail, selectedCandidate) : null}</ScrollArea>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function renderTabContent({
  run,
  activeTab,
  comparison,
  compareRun,
  filteredCatalog,
  onCandidateOpen,
  onPairwiseOpen,
  onPromptOpen,
  onQueryOpen,
  candidateSearch,
  onCandidateSearch,
}: {
  run: RunDetail;
  activeTab: DashboardTab;
  comparison: RunComparison | null;
  compareRun: RunDetail | null;
  filteredCatalog: CandidateRow[];
  onCandidateOpen: (candidateId: string) => void;
  onPairwiseOpen: (decision: PairwiseDecision) => void;
  onPromptOpen: (groupLabel: string, attempt: PromptTraceAttempt) => void;
  onQueryOpen: (row: QueryRow) => void;
  candidateSearch: string;
  onCandidateSearch: (value: string) => void;
}) {
  if (activeTab === "overview") {
    return (
      <div className="stack gap-6">
        <SectionHeader title="Pipeline health" description="Run health, phase completion, notebook-style cost breakdown, and the most useful artifacts to inspect next." />
        <div className="metric-grid">
          {run.overview.metrics.map((metric, index) => (
            <MetricCard key={`${metric.label}:${index}`} metric={metric} />
          ))}
        </div>
        <details className="expand-shell">
          <summary>Visual diagnostics</summary>
          <div className="split-grid">
            <ChartCard description="Measured stage durations from the notebook metrics cache." title="Stage duration profile">
              <PhaseDurationChart run={run} />
            </ChartCard>
            <ChartCard description="Core retrieval and ranking counts at a glance." title="Pipeline counts">
              <CountBarsChart
                label="count"
                rows={run.overview.metrics.map((metric) => ({
                  label: metric.label.replace(" rows", "").replace(" ", "\n"),
                  value: Number(metric.value.replace(/[^\d.-]/g, "")) || 0,
                }))}
              />
            </ChartCard>
          </div>
        </details>
        <div className="split-grid">
          <article className="dashboard-card">
            <div className="dashboard-card-label">Phase timeline</div>
            <div className="timeline-list">
              {run.overview.timeline.map((item) => (
                <div className="timeline-row" key={item.key}>
                  <div>
                    <div className="timeline-title">{item.label}</div>
                    <div className="timeline-copy">{item.note}</div>
                  </div>
                  <div className="timeline-meta">
                    <span className={`status-pill status-${item.status}`}>{item.status}</span>
                    <span>{item.seconds ? `${item.seconds.toFixed(1)} s` : "—"}</span>
                  </div>
                </div>
              ))}
            </div>
          </article>
          <article className="dashboard-card">
            <div className="dashboard-card-label">Cost breakdown by stage</div>
            <DataTable
              columns={["Stage", "Duration", "Run cost", "Artifact cost", "Info"]}
              empty="No stage cost rows available."
              renderRow={(value) => {
                const row = value as RunDetail["overview"]["stageCosts"][number];
                return (
                  <tr key={row.stage}>
                    <td>{row.label}</td>
                    <td>{row.durationSeconds !== null ? `${row.durationSeconds.toFixed(1)} s` : "—"}</td>
                    <td>${row.costRunUsd.toFixed(4)}</td>
                    <td>${row.costArtifactsUsd.toFixed(4)}</td>
                    <td>{truncateText(row.info || row.model || "—", 96)}</td>
                  </tr>
                );
              }}
              rows={run.overview.stageCosts}
            />
          </article>
        </div>
        <article className="dashboard-card">
          <div className="dashboard-card-label">Artifact inventory</div>
          <div className="timeline-list">
            {run.overview.artifacts.map((artifact, index) => (
              <div className="timeline-row" key={`${artifact.label}:${index}`}>
                <div>
                  <div className="timeline-title">{artifact.label}</div>
                  <div className="timeline-copy">{artifact.detail}</div>
                </div>
                <span className={`status-pill status-${artifact.status}`}>{artifact.status}</span>
              </div>
            ))}
          </div>
        </article>
        <article className="dashboard-card">
          <div className="dashboard-card-label">Notable events</div>
          <div className="timeline-list">
            {run.overview.notableEvents.map((event, index) => (
              <div className="timeline-row" key={`${event.ts}:${event.stage}:${event.label}:${index}`}>
                <div>
                  <div className="timeline-title">
                    {event.label} <span className="muted-inline">{event.stage}</span>
                  </div>
                  <div className="timeline-copy">{event.detail || "No extra detail captured."}</div>
                </div>
                <span>{formatDate(event.ts)}</span>
              </div>
            ))}
          </div>
        </article>
      </div>
    );
  }

  if (activeTab === "plan") {
    return (
      <div className="stack gap-6">
        <SectionHeader title="Planner output" description="Topic framing, object anchors, facet design, and constraint hygiene before retrieval starts." />
        <div className="split-grid">
          <ChartCard description="How much structure the planner produced before retrieval starts." title="Planner surface area">
            <PlannerCompositionChart run={run} />
          </ChartCard>
          <ChartCard description="Canonical, neighboring, and exclusion term density for the first facet set." title="Facet design density" tall>
            <FacetDensityChart run={run} />
          </ChartCard>
        </div>
        <div className="split-grid">
          <article className="dashboard-card">
            <div className="dashboard-card-label">English summary</div>
            <p className="copy-block">{run.plan.summaryEn || "No planner summary captured."}</p>
          </article>
          <article className="dashboard-card">
            <div className="dashboard-card-label">German summary</div>
            <p className="copy-block">{run.plan.summaryDe || "No German planner summary captured."}</p>
          </article>
        </div>
        <div className="split-grid">
          <article className="dashboard-card">
            <div className="dashboard-card-label">Primary anchors</div>
            <div className="chip-cloud">
              {[...run.plan.anchorsEn, ...run.plan.anchorsDe].map((item, index) => (
                <span className="data-chip" key={`anchor:${item}:${index}`}>
                  {item}
                </span>
              ))}
            </div>
          </article>
          <article className="dashboard-card">
            <div className="dashboard-card-label">Must-keep constraints</div>
            <div className="stack gap-2">
              {run.plan.constraints.map((item, index) => (
                <div className="list-row" key={`constraint:${item}:${index}`}>
                  {item}
                </div>
              ))}
            </div>
          </article>
        </div>
        <div className="split-grid">
          <article className="dashboard-card">
            <div className="dashboard-card-label">Drift risks</div>
            <div className="stack gap-2">
              {run.plan.driftRisks.map((item, index) => (
                <div className="list-row" key={`drift:${item}:${index}`}>
                  {item}
                </div>
              ))}
            </div>
          </article>
          <article className="dashboard-card">
            <div className="dashboard-card-label">Canonical vocabulary</div>
            <div className="chip-cloud">
              {[...run.plan.coreTermsEn, ...run.plan.coreTermsDe, ...run.plan.canonicalTermsEn.slice(0, 8)].map((item, index) => (
                <span className="data-chip" key={`term:${item}:${index}`}>
                  {item}
                </span>
              ))}
            </div>
          </article>
        </div>
        <article className="dashboard-card">
          <div className="dashboard-card-label">Global exclusions</div>
          <div className="chip-cloud">
            {[...run.plan.exclusionsEn, ...run.plan.exclusionsDe].map((item, index) => (
              <span className="data-chip data-chip-warn" key={`exclusion:${item}:${index}`}>
                {item}
              </span>
            ))}
          </div>
        </article>
        <article className="dashboard-card">
          <div className="dashboard-card-label">Facet summary</div>
          <DataTable
            columns={["Weight", "Type", "Facet", "Label (EN)", "Label (DE)"]}
            empty="No facets available."
            renderRow={(value) => {
              const facet = value as RunDetail["plan"]["facets"][number];
              return (
                <tr key={facet.id}>
                  <td>{facet.importanceWeight}</td>
                  <td>{facet.type}</td>
                  <td>{facet.id}</td>
                  <td>{facet.label}</td>
                  <td>{facet.labelDe}</td>
                </tr>
              );
            }}
            rows={run.plan.facets}
          />
        </article>
        <details className="expand-shell">
          <summary>Authority blueprints and full facet details</summary>
          <div className="stack gap-6">
            <article className="dashboard-card">
              <div className="dashboard-card-label">Authority blueprints</div>
              <div className="stack gap-3">
                {run.plan.blueprints.map((blueprint, index) => (
                  <div className="detail-card" key={`${blueprint.label}:${index}`}>
                    <div className="detail-card-header">
                      <h3>{blueprint.label}</h3>
                      <span className="muted-inline">{blueprint.kind}</span>
                    </div>
                    <p className="copy-block">{blueprint.notes}</p>
                    <div className="chip-cloud">
                      {blueprint.targets.map((target, targetIndex) => (
                        <span className="data-chip" key={`${blueprint.label}:target:${target}:${targetIndex}`}>
                          {target}
                        </span>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            </article>
            <article className="dashboard-card">
              <div className="dashboard-card-label">Expanded facet details</div>
              <div className="stack gap-3">
                {run.plan.facets.map((facet) => (
                  <div className="detail-card" key={facet.id}>
                    <div className="detail-card-header">
                      <h3>{facet.label}</h3>
                      <span className="muted-inline">
                        {facet.group} / {facet.type}
                      </span>
                    </div>
                    <p className="copy-block">{facet.summary}</p>
                    <div className="chip-cloud">
                      {facet.canonicalTerms.map((term, termIndex) => (
                        <span className="data-chip" key={`${facet.id}:term:${term}:${termIndex}`}>
                          {term}
                        </span>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            </article>
            {run.plan.promptGroups.length ? (
              <div className="metric-grid">
                {run.plan.promptGroups.map((group) => (
                  <PromptGroupCard group={group} key={group.key} onOpen={onPromptOpen} />
                ))}
              </div>
            ) : null}
          </div>
        </details>
      </div>
    );
  }

  if (activeTab === "queries") {
    return (
      <div className="stack gap-6">
        <SectionHeader title="Generated retrieval queries" description="OpenAlex and Semantic Scholar query sets with zero-hit checks and sample retrieval evidence." />
        <div className="metric-grid">
          {run.queries.providers.map((provider) => (
            <MetricCard
              key={provider.provider}
              metric={{
                label: provider.label,
                value: `${provider.queryCount} queries / ${provider.totalHits} hits`,
                detail: `${provider.zeroHitCount} zero-hit, ${provider.duplicateQueryCount} duplicate, anchor coverage ${provider.anchorCoverageHits}/${provider.anchorCoverageTotal || 0}`,
              }}
            />
          ))}
        </div>
        <details className="expand-shell">
          <summary>Visual diagnostics</summary>
          <div className="split-grid">
            <ChartCard description="Total hit yield and query volume by provider." title="Provider query yield">
              <ProviderHitsChart providers={run.queries.providers} />
            </ChartCard>
            <ChartCard description="Top hit-producing generated queries." title="Top query hit counts">
              <QueryHitsChart rows={run.queries.providers.flatMap((provider) => provider.rows).sort((left, right) => right.hitCount - left.hitCount)} />
            </ChartCard>
          </div>
        </details>
        {run.queries.promptGroups.length ? (
          <div className="metric-grid">
            {run.queries.promptGroups.map((group) => (
              <PromptGroupCard group={group} key={group.key} onOpen={onPromptOpen} />
            ))}
          </div>
        ) : null}
        {run.queries.providers.map((provider) => (
          <article className="dashboard-card" key={provider.provider}>
            <div className="dashboard-card-label">{provider.label}</div>
            <DataTable
              columns={["Intent", "Lang", "Hits", "Query", "Notes"]}
              empty="No queries captured for this provider."
              renderRow={(value, index) => {
                const row = value as QueryRow;
                return (
                  <tr className="clickable-row" key={`${row.id}:${index}`} onClick={() => onQueryOpen(row)}>
                    <td>{row.intent}</td>
                    <td>{row.language}</td>
                    <td>{formatNumber(row.hitCount)}</td>
                    <td>{truncateText(row.queryText, 120)}</td>
                    <td>{truncateText(row.note, 70)}</td>
                  </tr>
                );
              }}
              rows={provider.rows}
            />
          </article>
        ))}
      </div>
    );
  }

  if (activeTab === "retrieval") {
    return (
      <div className="stack gap-6">
        <SectionHeader title="Retrieval outcomes" description="Provider totals, query quality, and publication-year spread across raw retrieval." />
        <div className="metric-grid">
          {run.retrieval.providers.map((provider) => (
            <MetricCard
              key={provider.provider}
              metric={{
                label: provider.label,
                value: `${provider.totalHits} hits`,
                detail: `${provider.queryCount} queries, ${provider.zeroHitQueries} zero-hit, strongest query hit ${provider.strongestHits}`,
              }}
            />
          ))}
        </div>
        <details className="expand-shell">
          <summary>Visual diagnostics</summary>
          <div className="split-grid">
            <ChartCard description="Raw hit volume and query counts per provider." title="Retrieval provider totals">
              <ProviderHitsChart providers={run.retrieval.providers} />
            </ChartCard>
            <ChartCard description="Publication-year spread across sampled retrieval hits." title="Retrieval by decade">
              <DecadeChart rows={run.retrieval.decadeBuckets} />
            </ChartCard>
          </div>
        </details>
        <article className="dashboard-card">
          <div className="dashboard-card-label">Publication decades</div>
          <div className="bucket-list">
            {run.retrieval.decadeBuckets.map((bucket) => (
              <div className="bucket-row" key={bucket.decade}>
                <span>{bucket.decade}</span>
                <strong>{bucket.count}</strong>
              </div>
            ))}
          </div>
        </article>
        <div className="split-grid">
          <article className="dashboard-card">
            <div className="dashboard-card-label">Top hit queries</div>
            <DataTable
              columns={["Provider", "Hits", "Query", "Samples"]}
              empty="No retrieval rows available."
              renderRow={(value, index) => {
                const row = value as QueryRow;
                return (
                  <tr className="clickable-row" key={`${row.id}:${index}`} onClick={() => onQueryOpen(row)}>
                    <td>{row.provider}</td>
                    <td>{row.hitCount}</td>
                    <td>{truncateText(row.queryText, 90)}</td>
                    <td>{truncateText(row.sampleTitles.join(" | "), 70)}</td>
                  </tr>
                );
              }}
              rows={run.retrieval.topQueries}
            />
          </article>
          <article className="dashboard-card">
            <div className="dashboard-card-label">Zero-hit queries</div>
            <DataTable
              columns={["Provider", "Lang", "Intent", "Query"]}
              empty="No zero-hit queries."
              renderRow={(value, index) => {
                const row = value as QueryRow;
                return (
                  <tr className="clickable-row" key={`${row.id}:${index}`} onClick={() => onQueryOpen(row)}>
                    <td>{row.provider}</td>
                    <td>{row.language}</td>
                    <td>{row.intent}</td>
                    <td>{truncateText(row.queryText, 100)}</td>
                  </tr>
                );
              }}
              rows={run.retrieval.zeroHitQueries}
            />
          </article>
        </div>
      </div>
    );
  }

  if (activeTab === "candidates") {
    return (
      <div className="stack gap-6">
        <SectionHeader
          title="Candidate pool"
          description="Normalized candidates, provider overlap, and the notebook-style sanity checks that usually matter before you touch the live FastAPI port."
          actions={
            <label className="search-control inline-search">
              <span>Candidate filter</span>
              <Input onChange={(event) => onCandidateSearch(event.target.value)} placeholder="title, doi, facet" value={candidateSearch} />
            </label>
          }
        />
        <div className="metric-grid">
          {run.candidates.funnel.map((metric, index) => (
            <MetricCard key={`${metric.label}:${index}`} metric={metric} />
          ))}
        </div>
        <div className="split-grid">
          <article className="dashboard-card">
            <div className="dashboard-card-label">Pool balance</div>
            <div className="stack gap-2">
              {run.candidates.poolSummary.map((pool, index) => (
                <div className="list-row" key={`${pool.label}:${index}`}>
                  <strong>{pool.label}</strong>
                  <span>
                    {pool.count} rows, {pool.detail}
                  </span>
                </div>
              ))}
            </div>
          </article>
          <article className="dashboard-card">
            <div className="dashboard-card-label">Provider overlap</div>
            <LabelGrid items={run.candidates.providerMix} />
          </article>
        </div>
        <div className="split-grid">
          <article className="dashboard-card">
            <div className="dashboard-card-label">Identifier coverage</div>
            <LabelGrid items={run.candidates.idCoverage} />
          </article>
          <details className="expand-shell">
            <summary>Visual diagnostics</summary>
            <div className="split-grid">
              <ChartCard description="How many rows survive into each candidate pool." title="Pool size split">
                <CandidatePoolChart run={run} />
              </ChartCard>
              <ChartCard description="Citation count against strongest lane score for the current candidate sample." title="Citations vs lane score" tall>
                <CitationScatterChart rows={run.candidates.catalog} />
              </ChartCard>
            </div>
          </details>
        </div>
        <CandidateAccordion description="Highest citation counts across the normalized candidate pool." rows={run.candidates.topCited} title="Top cited candidates" onOpen={onCandidateOpen} />
        <div className="split-grid">
          <CandidateAccordion description="Rows merged from multiple source traces, with cross-provider joins surfaced first." rows={run.candidates.mergedCandidates} title="Merged candidates" onOpen={onCandidateOpen} />
          <CandidateAccordion description="Highly cited rows that never hit the anchor terms in title or abstract." rows={run.candidates.noAnchorTopCited} title="Top cited but no anchors" onOpen={onCandidateOpen} />
        </div>
        <CandidateAccordion description="Heuristic economic-term hits from the notebook report, useful for spotting thematic drift and coverage gaps." rows={run.candidates.econHitCandidates} title="Top econ-hit candidates" onOpen={onCandidateOpen} />
        <article className="dashboard-card">
          <div className="dashboard-card-label">Candidate catalog</div>
          <DataTable
            columns={["Title", "Pool", "Top facets", "Req hits", "Match", "Authority", "Link"]}
            empty="No candidates passed the current filter."
            renderRow={(value, index) => {
              const row = value as CandidateRow;
              return (
                <tr className="clickable-row" key={`${row.id}:${index}`} onClick={() => onCandidateOpen(row.id)}>
                  <td>{truncateText(row.title, 100)}</td>
                  <td>{row.pool === "with_abstract" ? "with abstract" : "without abstract"}</td>
                  <td>{truncateText(row.topFacets.join(", "), 70) || "—"}</td>
                  <td>{row.requiredFacetHits}</td>
                  <td>{scoreBadge(row.matchLane)}</td>
                  <td>{scoreBadge(row.authorityLane)}</td>
                  <td>{row.resourceUrl ? "yes" : "—"}</td>
                </tr>
              );
            }}
            rows={filteredCatalog}
          />
        </article>
      </div>
    );
  }

  if (activeTab === "scoring") {
    return (
      <div className="stack gap-6">
        <SectionHeader title="Scoring and pruning" description="Hygiene gates, MMR settings, and the highest-ranked rows across stage 1, stage 2, and final scoring." />
        <div className="split-grid">
          <article className="dashboard-card">
            <div className="dashboard-card-label">Candidate hygiene</div>
            <LabelGrid items={run.scoring.hygiene} />
          </article>
          <article className="dashboard-card">
            <div className="dashboard-card-label">MMR settings</div>
            <LabelGrid items={run.scoring.mmr} />
          </article>
        </div>
        <details className="expand-shell">
          <summary>Visual diagnostics</summary>
          <div className="split-grid">
            <ChartCard description="Top leaderboard score decay across the current scoring stages." title="Score trends by rank" tall>
              <ScoreTrendChart sections={[...run.scoring.stage2, ...run.scoring.final]} />
            </ChartCard>
            <ChartCard description="Top stage-1 leaderboard score decay across pools and lanes." title="Stage-1 shape" tall>
              <ScoreTrendChart sections={run.scoring.stage1} />
            </ChartCard>
          </div>
        </details>
        {[...run.scoring.stage1, ...run.scoring.stage2, ...run.scoring.final].map((section) => (
          <article className="dashboard-card" key={section.id}>
            <div className="dashboard-card-label">{section.label}</div>
            <p className="dashboard-card-detail">{section.subtitle}</p>
            <DataTable
              columns={["Title", "Year", "Top facets", "Match", "Authority"]}
              empty="No rows in this leaderboard."
              renderRow={(value, index) => {
                const row = value as CandidateRow;
                return (
                  <tr className="clickable-row" key={`${row.id}:${index}`} onClick={() => onCandidateOpen(row.id)}>
                    <td>{truncateText(row.title, 90)}</td>
                    <td>{row.year ?? "—"}</td>
                    <td>{truncateText(row.topFacets.join(", "), 60) || "—"}</td>
                    <td>{scoreBadge(row.matchLane)}</td>
                    <td>{scoreBadge(row.authorityLane)}</td>
                  </tr>
                );
              }}
              rows={section.rows}
            />
          </article>
        ))}
      </div>
    );
  }

  if (activeTab === "coverage") {
    return (
      <div className="stack gap-6">
        <SectionHeader title="Shortlists and coverage" description="Facet coverage density, stage-G shortlist composition, and rows with broad chapter coverage." />
        <div className="split-grid">
          <article className="dashboard-card">
            <div className="dashboard-card-label">Facet coverage leaders</div>
            <DataTable
              columns={["Facet", "Hits", "Avg score", "Sample"]}
              empty="No coverage tags available."
              renderRow={(value) => {
                const row = value as RunDetail["coverage"]["facetCoverage"][number];
                return (
                  <tr key={row.facetId}>
                    <td>{row.label}</td>
                    <td>{row.hitCount}</td>
                    <td>{row.avgScore.toFixed(2)}</td>
                    <td>{truncateText(row.sampleTitle, 70)}</td>
                  </tr>
                );
              }}
              rows={run.coverage.facetCoverage}
            />
          </article>
          <article className="dashboard-card">
            <div className="dashboard-card-label">Required facet coverage</div>
            <LabelGrid items={run.coverage.requiredFacetSummary} />
            {run.coverage.missingRequiredBySection.length ? (
              <div className="stack gap-2">
                {run.coverage.missingRequiredBySection.map((row, index) => (
                  <div className="list-row wrap" key={`${row.sectionId}:${index}`}>
                    <strong>{row.label}</strong>
                    <span>{row.missingCount} missing</span>
                    <p className="timeline-copy">{row.examples.join(", ")}</p>
                  </div>
                ))}
              </div>
            ) : null}
          </article>
        </div>
        <details className="expand-shell">
          <summary>Visual diagnostics</summary>
          <ChartCard description="Most frequently surfaced chapter facets across coverage-tagged rows." title="Facet concentration" tall>
            <FacetCoverageChart run={run} />
          </ChartCard>
        </details>
        <div className="split-grid">
          <article className="dashboard-card">
            <div className="dashboard-card-label">Coverage-rich candidates</div>
            <DataTable
              columns={["Title", "Facets", "Match", "Authority"]}
              empty="No coverage rows available."
              renderRow={(value, index) => {
                const row = value as CandidateRow;
                return (
                  <tr className="clickable-row" key={`${row.id}:${index}`} onClick={() => onCandidateOpen(row.id)}>
                    <td>{truncateText(row.title, 90)}</td>
                    <td>{row.topFacets.length}</td>
                    <td>{scoreBadge(row.matchLane)}</td>
                    <td>{scoreBadge(row.authorityLane)}</td>
                  </tr>
                );
              }}
              rows={run.coverage.coverageRich}
            />
          </article>
        </div>
        {run.coverage.stageGRankings.map((section) => (
          <article className="dashboard-card" key={section.id}>
            <div className="dashboard-card-label">{section.label}</div>
            <p className="dashboard-card-detail">{section.subtitle}</p>
            <DataTable
              columns={["Title", "Top facets", "Match", "Authority"]}
              empty="No shortlist rows in this section."
              renderRow={(value, index) => {
                const row = value as CandidateRow;
                return (
                  <tr className="clickable-row" key={`${row.id}:${index}`} onClick={() => onCandidateOpen(row.id)}>
                    <td>{truncateText(row.title, 90)}</td>
                    <td>{truncateText(row.topFacets.join(", "), 60) || "—"}</td>
                    <td>{scoreBadge(row.matchLane)}</td>
                    <td>{scoreBadge(row.authorityLane)}</td>
                  </tr>
                );
              }}
              rows={section.rows}
            />
          </article>
        ))}
      </div>
    );
  }

  if (activeTab === "rerank") {
    return (
      <div className="stack gap-6">
        <SectionHeader title="Rerank layer" description="Pointwise rerank decisions, post-rerank lane orderings, and pairwise refinement traces where available." />
        <div className="metric-grid">
          {run.rerank.metrics.map((metric, index) => (
            <MetricCard key={`${metric.label}:${index}`} metric={metric} />
          ))}
        </div>
        <details className="expand-shell">
          <summary>Visual diagnostics</summary>
          <div className="split-grid">
            <ChartCard description="Highest available rerank score against strongest lane score." title="Lane score vs rerank score" tall>
              <RerankScatterChart rows={run.candidates.catalog} />
            </ChartCard>
            <ChartCard description="Post-rerank top-list score decay across the lane sections." title="Rerank score trends" tall>
              <ScoreTrendChart sections={run.rerank.laneRankings} />
            </ChartCard>
          </div>
        </details>
        <div className="split-grid">
          <article className="dashboard-card">
            <div className="dashboard-card-label">High-signal rerank rows</div>
            <DataTable
              columns={["Title", "Match rerank", "Authority rerank", "Top facets"]}
              empty="No rerank rows available."
              renderRow={(value, index) => {
                const row = value as CandidateRow;
                return (
                  <tr className="clickable-row" key={`${row.id}:${index}`} onClick={() => onCandidateOpen(row.id)}>
                    <td>{truncateText(row.title, 90)}</td>
                    <td>{row.rerankMatch ?? "—"}</td>
                    <td>{row.rerankAuthority ?? "—"}</td>
                    <td>{truncateText(row.topFacets.join(", "), 60) || "—"}</td>
                  </tr>
                );
              }}
              rows={run.rerank.highSignal}
            />
          </article>
          <article className="dashboard-card">
            <div className="dashboard-card-label">Pairwise summary</div>
            <LabelGrid items={run.rerank.pairwiseSummary} />
          </article>
        </div>
        {run.rerank.laneRankings.map((section) => (
          <article className="dashboard-card" key={section.id}>
            <div className="dashboard-card-label">{section.label}</div>
            <p className="dashboard-card-detail">{section.subtitle}</p>
            <DataTable
              columns={["Title", "Rerank", "Match", "Authority"]}
              empty="No rows available for this rerank section."
              renderRow={(value, index) => {
                const row = value as CandidateRow;
                return (
                  <tr className="clickable-row" key={`${row.id}:${index}`} onClick={() => onCandidateOpen(row.id)}>
                    <td>{truncateText(row.title, 90)}</td>
                    <td>{row.rerankMatch ?? row.rerankAuthority ?? "—"}</td>
                    <td>{scoreBadge(row.matchLane)}</td>
                    <td>{scoreBadge(row.authorityLane)}</td>
                  </tr>
                );
              }}
              rows={section.rows}
            />
          </article>
        ))}
        <div className="split-grid">
          <article className="dashboard-card">
            <div className="dashboard-card-label">Off-topic decisions</div>
            <DataTable
              columns={["Title", "Authority", "Match"]}
              empty="No off-topic rerank rows."
              renderRow={(value, index) => {
                const row = value as CandidateRow;
                return (
                  <tr className="clickable-row" key={`${row.id}:${index}`} onClick={() => onCandidateOpen(row.id)}>
                    <td>{truncateText(row.title, 90)}</td>
                    <td>{scoreBadge(row.authorityLane)}</td>
                    <td>{scoreBadge(row.matchLane)}</td>
                  </tr>
                );
              }}
              rows={run.rerank.offTopic}
            />
          </article>
          <article className="dashboard-card">
            <div className="dashboard-card-label">Pairwise decisions</div>
            <DataTable
              columns={["Lane", "Winner", "Confidence", "Rationale"]}
              empty="No pairwise cache captured."
              renderRow={(value, index) => {
                const row = value as PairwiseDecision;
                return (
                  <tr className="clickable-row" key={`${row.leftId}:${row.rightId}:${index}`} onClick={() => onPairwiseOpen(row)}>
                    <td>{row.lane}</td>
                    <td>{truncateText(row.winnerId, 26)}</td>
                    <td>{row.confidence ?? "—"}</td>
                    <td>{truncateText(row.briefRationale, 70)}</td>
                  </tr>
                );
              }}
              rows={run.rerank.pairwiseDecisions}
            />
          </article>
        </div>
      </div>
    );
  }

  if (activeTab === "final") {
    return (
      <div className="stack gap-6">
        <SectionHeader title="Final output lists" description="The exact lane and pool lists that would normally be surfaced downstream, shown as expandable result cards with the most useful audit signals inline." />
        <details className="expand-shell">
          <summary>Visual diagnostics</summary>
          <div className="split-grid">
            <ChartCard description="How many final output rows are emitted per lane and pool section." title="Final output section sizes">
              <CountBarsChart label="rows" rows={run.final.outputs.map((section) => ({ label: truncateText(section.label, 18), value: section.rows.length }))} />
            </ChartCard>
            <ChartCard description="Score shape inside the final top lists." title="Final rank trends" tall>
              <ScoreTrendChart sections={run.final.outputs} />
            </ChartCard>
          </div>
        </details>
        {run.final.outputs.map((section) => (
          <div className="stack gap-3" key={section.id}>
            <article className="dashboard-card">
              <div className="dashboard-card-label">{section.label}</div>
              {section.metrics?.length ? <LabelGrid items={section.metrics} /> : null}
            </article>
            <CandidateAccordion description={section.subtitle} rows={section.rows} title={section.label} onOpen={onCandidateOpen} />
          </div>
        ))}
      </div>
    );
  }

  if (compareRun && comparison && activeTab === "compare") {
    const stageKeys = uniqueStrings([...run.overview.stageCosts.map((row) => row.stage), ...compareRun.overview.stageCosts.map((row) => row.stage)]);
    const finalSectionIds = uniqueStrings([...run.final.outputs.map((section) => section.id), ...compareRun.final.outputs.map((section) => section.id)]);

    return (
      <div className="stack gap-6">
        <SectionHeader title="Run comparison" description="Focused side-by-side comparison for the key phase metrics and final lane outcomes." />
        <div className="metric-grid">
          {comparison.metrics.map((metric, index) => (
            <MetricCard key={`${metric.label}:${index}`} metric={metric} />
          ))}
        </div>
        <div className="compare-run-grid">
          {[run, compareRun].map((entry, index) => (
            <article className="dashboard-card compare-run-card" key={`${entry.id}:${index}`}>
              <div className="section-eyebrow">{index === 0 ? "Selected run" : "Comparison run"}</div>
              <h3 className="section-title">{entry.chapterTitle}</h3>
              <p className="dashboard-card-detail">{entry.topicSummary}</p>
              <div className="hero-meta">
                <span>{entry.id}</span>
                <span>{entry.statusLabel}</span>
                <span>{formatDate(entry.modifiedAt)}</span>
              </div>
              <LabelGrid items={entry.headerStats.map((metric) => ({ label: metric.label, value: metric.value, detail: metric.detail }))} />
            </article>
          ))}
        </div>
        <article className="dashboard-card">
          <div className="dashboard-card-label">Stage-by-stage cost and duration</div>
          <div className="compare-stage-list">
            {stageKeys.map((stageKey, index) => {
              const left = run.overview.stageCosts.find((row) => row.stage === stageKey);
              const right = compareRun.overview.stageCosts.find((row) => row.stage === stageKey);
              const label = left?.label || right?.label || stageKey;
              return (
                <div className="compare-stage-row" key={`${stageKey}:${index}`}>
                  <div className="compare-stage-label">
                    <strong>{label}</strong>
                  </div>
                  {[left, right].map((row, sideIndex) => (
                    <div className="compare-stage-cell" key={`${stageKey}:side:${sideIndex}`}>
                      <div className="compare-stage-metric">
                        <span>Duration</span>
                        <strong>{row?.durationSeconds !== null && row?.durationSeconds !== undefined ? `${row.durationSeconds.toFixed(1)} s` : "—"}</strong>
                      </div>
                      <div className="compare-stage-metric">
                        <span>Run cost</span>
                        <strong>${(row?.costRunUsd ?? 0).toFixed(4)}</strong>
                      </div>
                      <div className="compare-stage-metric">
                        <span>Artifact cost</span>
                        <strong>${(row?.costArtifactsUsd ?? 0).toFixed(4)}</strong>
                      </div>
                      <div className="compare-stage-note">{row?.info || row?.model || "No extra data"}</div>
                    </div>
                  ))}
                </div>
              );
            })}
          </div>
        </article>
        <div className="compare-run-grid">
          {finalSectionIds.map((sectionId, index) => {
            const left = run.final.outputs.find((section) => section.id === sectionId) ?? null;
            const right = compareRun.final.outputs.find((section) => section.id === sectionId) ?? null;
            return (
              <article className="dashboard-card" key={`${sectionId}:${index}`}>
                <div className="dashboard-card-label">{left?.label || right?.label || sectionId}</div>
                <div className="compare-final-grid">
                  {[left, right].map((section, sideIndex) => (
                    <div className="compare-final-column" key={`${sectionId}:column:${sideIndex}`}>
                      <div className="section-eyebrow">{sideIndex === 0 ? "Selected" : "Compare"}</div>
                      {section?.metrics?.length ? <LabelGrid items={section.metrics} /> : <div className="dashboard-empty">No section data.</div>}
                      <div className="stack gap-2">
                        {(section?.rows ?? []).slice(0, 5).map((row, rowIndex) => (
                          <div className="list-row wrap" key={`${sectionId}:${row.id}:${rowIndex}`}>
                            <strong>{truncateText(row.title, 84)}</strong>
                            <span>{row.year ?? "—"}</span>
                            {row.resourceUrl ? (
                              <a href={row.resourceUrl} rel="noreferrer" target="_blank">
                                Link
                              </a>
                            ) : null}
                          </div>
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
              </article>
            );
          })}
        </div>
        <details className="expand-shell">
          <summary>Overlap diagnostics</summary>
          <div className="stack gap-4">
            <ChartCard description="Shared versus run-specific top-list members across compared sections." title="Overlap by section" tall>
              <CompareOverlapChart comparison={comparison} />
            </ChartCard>
            <article className="dashboard-card">
              <div className="dashboard-card-label">Query diff summary</div>
              <LabelGrid items={comparison.queryDiffs} />
            </article>
          </div>
        </details>
      </div>
    );
  }

  return <div className="dashboard-empty">This tab has no available data for the selected run.</div>;
}

function renderDetailPanel(detail: DetailState, selectedCandidate: CandidateRow | null) {
  if (!detail) {
    return (
      <Card className="border-border/70 shadow-none">
        <CardHeader>
          <CardTitle>Inspector</CardTitle>
          <CardDescription>Open a prompt trace, query row, candidate, or pairwise decision to inspect it here without leaving the current stage.</CardDescription>
        </CardHeader>
      </Card>
    );
  }

  if (detail.kind === "prompt") {
    return (
      <div className="stack gap-4">
        <SectionHeader eyebrow={detail.groupLabel} title={detail.attempt.label} description={`${detail.attempt.model} · ${detail.attempt.status}`} />
        <LabelGrid
          items={[
            { label: "Input tokens", value: `${detail.attempt.inputTokens}` },
            { label: "Output tokens", value: `${detail.attempt.outputTokens}` },
            { label: "Reasoning tokens", value: `${detail.attempt.reasoningTokens}` },
            { label: "Cost", value: `$${detail.attempt.costUsd.toFixed(4)}` },
          ]}
        />
        <Card className="detail-card border-border/70 shadow-none">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">System prompt</CardTitle>
          </CardHeader>
          <CardContent className="pt-0">
            <pre className="text-block">{detail.attempt.systemPrompt || "No system prompt stored."}</pre>
          </CardContent>
        </Card>
        <Card className="detail-card border-border/70 shadow-none">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">User prompt</CardTitle>
          </CardHeader>
          <CardContent className="pt-0">
            <pre className="text-block">{detail.attempt.userPrompt || "No user prompt stored."}</pre>
          </CardContent>
        </Card>
        <Card className="detail-card border-border/70 shadow-none">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">Output text</CardTitle>
          </CardHeader>
          <CardContent className="pt-0">
            <pre className="text-block">{detail.attempt.outputText || detail.attempt.errorNote || "No output text stored."}</pre>
          </CardContent>
        </Card>
      </div>
    );
  }

  if (detail.kind === "query") {
    return (
      <div className="stack gap-4">
        <SectionHeader eyebrow={detail.row.provider} title={`${detail.row.intent} · ${detail.row.language}`} description={`${detail.row.hitCount} hits, max rank ${detail.row.maxRank || "—"}`} />
        <Card className="detail-card border-border/70 shadow-none">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">Query</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 pt-0">
            <p className="copy-block">{detail.row.queryText}</p>
            {detail.row.filters ? <p className="muted-copy">Filters: {detail.row.filters}</p> : null}
            {detail.row.sort ? <p className="muted-copy">Sort: {detail.row.sort}</p> : null}
          </CardContent>
        </Card>
        <Card className="detail-card border-border/70 shadow-none">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">Notes</CardTitle>
          </CardHeader>
          <CardContent className="pt-0">
            <p className="copy-block">{detail.row.note || "No notes captured."}</p>
          </CardContent>
        </Card>
        <Card className="detail-card border-border/70 shadow-none">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">Sample hits</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 pt-0">
            {detail.row.sampleTitles.map((title, index) => (
              <div className="list-row" key={`${title}:${index}`}>
                {title}
              </div>
            ))}
          </CardContent>
        </Card>
      </div>
    );
  }

  if (detail.kind === "pairwise") {
    return (
      <div className="stack gap-4">
        <SectionHeader eyebrow={`${detail.decision.lane} / ${detail.decision.pool}`} title="Pairwise decision" description={`Winner: ${detail.decision.winnerId}`} />
        <LabelGrid
          items={[
            { label: "Left", value: detail.decision.leftId },
            { label: "Right", value: detail.decision.rightId },
            { label: "Confidence", value: detail.decision.confidence !== null ? `${detail.decision.confidence}` : "—" },
            { label: "Cost", value: `$${detail.decision.costUsd.toFixed(4)}` },
          ]}
        />
        <Card className="detail-card border-border/70 shadow-none">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">Rationale</CardTitle>
          </CardHeader>
          <CardContent className="pt-0">
            <p className="copy-block">{detail.decision.briefRationale || "No rationale stored."}</p>
          </CardContent>
        </Card>
      </div>
    );
  }

  if (detail.kind === "candidate" && selectedCandidate) {
    return (
      <div className="stack gap-4">
        <SectionHeader eyebrow={selectedCandidate.id} title={selectedCandidate.title} description={`${selectedCandidate.year ?? "—"} · ${selectedCandidate.venue || "Unknown venue"}`} />
        <LabelGrid
          items={[
            { label: "Match lane", value: scoreBadge(selectedCandidate.matchLane) },
            { label: "Authority lane", value: scoreBadge(selectedCandidate.authorityLane) },
            { label: "Rerank match", value: scoreBadge(selectedCandidate.rerankMatch) },
            { label: "Rerank authority", value: scoreBadge(selectedCandidate.rerankAuthority) },
            { label: "Coverage tags", value: `${selectedCandidate.tagCount}` },
            { label: "Required facets", value: `${selectedCandidate.requiredFacetHits}` },
          ]}
        />
        <Card className="detail-card border-border/70 shadow-none">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">Top facets</CardTitle>
          </CardHeader>
          <CardContent className="pt-0">
            <div className="chip-cloud">
              {selectedCandidate.topFacets.map((facet, index) => (
                <Badge className="data-chip px-3 py-1" key={`${selectedCandidate.id}:facet:${index}`} variant="secondary">
                  {facet}
                </Badge>
              ))}
            </div>
          </CardContent>
        </Card>
        <Card className="detail-card border-border/70 shadow-none">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">Coverage excerpt</CardTitle>
          </CardHeader>
          <CardContent className="pt-0">
            <p className="copy-block">{selectedCandidate.coverageExcerpt || "No coverage excerpt stored."}</p>
          </CardContent>
        </Card>
        <Card className="detail-card border-border/70 shadow-none">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">Evidence snippets</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 pt-0">
            {selectedCandidate.evidenceSnippets.map((snippet, index) => (
              <pre className="text-block compact" key={index}>
                {snippet}
              </pre>
            ))}
          </CardContent>
        </Card>
        <Card className="detail-card border-border/70 shadow-none">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">Abstract preview</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 pt-0">
            <p className="copy-block">{selectedCandidate.abstractPreview || "No abstract captured."}</p>
            {selectedCandidate.rerankSummary ? <p className="muted-copy">Rerank: {selectedCandidate.rerankSummary}</p> : null}
            {selectedCandidate.resourceUrl ? (
              <Button asChild className="w-fit px-0" variant="link">
                <a href={selectedCandidate.resourceUrl} rel="noreferrer" target="_blank">
                  {selectedCandidate.resourceUrl}
                </a>
              </Button>
            ) : null}
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <Card className="border-border/70 shadow-none">
      <CardHeader>
        <CardTitle>Inspector</CardTitle>
        <CardDescription>The selected row has no expanded detail available.</CardDescription>
      </CardHeader>
    </Card>
  );
}
