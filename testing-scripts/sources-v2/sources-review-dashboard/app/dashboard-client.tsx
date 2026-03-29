"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { type ReactNode, useDeferredValue, useEffect, useEffectEvent, useMemo, useRef, useState, useTransition } from "react";
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
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
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

interface RunFingerprintPayload {
  fingerprint: string;
  generatedAt: string;
  runCount: number;
}

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

const COMPARE_SECTION_PRIORITY = ["match:with_abstract", "match:without_abstract", "authority:with_abstract", "authority:without_abstract"] as const;

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

function parseMetricNumber(value: string): number {
  const parsed = Number(String(value).replace(/[^\d.-]/g, ""));
  return Number.isFinite(parsed) ? parsed : 0;
}

function scoreBadge(value: number | null): string {
  if (value === null || !Number.isFinite(value)) {
    return "—";
  }
  return value.toFixed(3);
}

function compareScoreBadge(value: number | null): string {
  if (value === null || !Number.isFinite(value)) {
    return "—";
  }
  if (Math.abs(value) >= 1) {
    return value.toFixed(0);
  }
  return value.toFixed(3);
}

function formatPercent(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) {
    return "—";
  }
  return `${(value * 100).toFixed(1)}%`;
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

function orderedCompareSections(values: string[]): string[] {
  return uniqueStrings(values).sort((left, right) => {
    const leftIndex = COMPARE_SECTION_PRIORITY.indexOf(left as (typeof COMPARE_SECTION_PRIORITY)[number]);
    const rightIndex = COMPARE_SECTION_PRIORITY.indexOf(right as (typeof COMPARE_SECTION_PRIORITY)[number]);
    return (leftIndex === -1 ? Number.MAX_SAFE_INTEGER : leftIndex) - (rightIndex === -1 ? Number.MAX_SAFE_INTEGER : rightIndex);
  });
}

function compareSectionShortLabel(sectionId: string): string {
  const [lane, pool] = sectionId.split(":");
  const laneLabel = lane === "authority" ? "Authority" : "Match";
  const poolLabel = pool === "without_abstract" ? "ohne Abstract" : "mit Abstract";
  return `${laneLabel} (${poolLabel})`;
}

function finalSectionForRun(run: RunDetail, sectionId: string): LeaderboardSection | null {
  return run.final.outputs.find((section) => section.id === sectionId) ?? null;
}

function compareSectionScore(sectionId: string, row: CandidateRow): number | null {
  return sectionId.startsWith("authority:") ? row.rerankAuthority ?? row.authorityLane : row.rerankMatch ?? row.matchLane;
}

function bestCandidateScore(row: CandidateRow): number | null {
  const values = [row.rerankMatch, row.rerankAuthority, row.matchLane, row.authorityLane].filter(
    (value): value is number => value !== null && Number.isFinite(value),
  );
  if (!values.length) {
    return null;
  }
  return Math.max(...values);
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

function InlineStatRow({ items }: { items: LabelValue[] }) {
  if (!items.length) {
    return null;
  }

  return (
    <div className="inline-stat-row">
      {items.map((item, index) => (
        <div className="inline-stat" key={`${item.label}:${item.value}:${index}`}>
          <span className="inline-stat-label">{item.label}</span>
          <strong className="inline-stat-value">{item.value}</strong>
        </div>
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

function PlannerSectionCard({
  title,
  count,
  children,
  note,
}: {
  title: string;
  count?: number;
  children: ReactNode;
  note?: string;
}) {
  return (
    <Card className="planner-panel border-border/70 bg-card/95 shadow-sm">
      <CardHeader className="planner-panel-header">
        <div className="planner-panel-title-row">
          <CardTitle className="planner-panel-title">{title}</CardTitle>
          {typeof count === "number" ? <span className="planner-count-pill">{count}</span> : null}
        </div>
        {note ? <CardDescription className="planner-panel-note">{note}</CardDescription> : null}
      </CardHeader>
      <CardContent className="planner-panel-body">{children}</CardContent>
    </Card>
  );
}

function PlannerTermGroup({
  label,
  terms,
  tone = "default",
  limit = 999,
}: {
  label: string;
  terms: string[];
  tone?: "default" | "warn";
  limit?: number;
}) {
  const normalizedTerms = useMemo(() => uniqueStrings(terms.filter(Boolean)), [terms]);
  const [expanded, setExpanded] = useState(false);
  const canExpand = normalizedTerms.length > limit;
  const visibleTerms = !canExpand || expanded ? normalizedTerms : normalizedTerms.slice(0, limit);
  const hiddenCount = normalizedTerms.length - visibleTerms.length;

  return (
    <div className="planner-term-group">
      <div className="planner-language-label">{label}</div>
      {visibleTerms.length ? (
        <div className="planner-chip-cloud">
          {visibleTerms.map((term, index) => (
            <span className={cn("planner-chip", tone === "warn" && "planner-chip-warn")} key={`${label}:${term}:${index}`}>
              {term}
            </span>
          ))}
          {!expanded && hiddenCount > 0 ? <span className="planner-chip planner-chip-muted">+{hiddenCount}</span> : null}
        </div>
      ) : (
        <p className="planner-empty-copy">No terms captured.</p>
      )}
      {canExpand ? (
        <Button className="planner-inline-link" onClick={() => setExpanded((current) => !current)} type="button" variant="link">
          {expanded ? "Show less" : "Show all"}
        </Button>
      ) : null}
    </div>
  );
}

function PlannerSummaryCard({
  title,
  text,
}: {
  title: string;
  text: string;
}) {
  return (
    <PlannerSectionCard title={title}>
      <p className="planner-summary-copy">{text || "No planner summary captured."}</p>
    </PlannerSectionCard>
  );
}

function PlannerFacetDetail({
  facet,
  blueprintLabels,
}: {
  facet: RunDetail["plan"]["facets"][number];
  blueprintLabels: string[];
}) {
  return (
    <div className="planner-facet-detail">
      <div className="planner-facet-detail-header">
        <div>
          <div className="planner-facet-kicker">{facet.id}</div>
          <h3 className="planner-facet-title">
            {facet.label} <span className="planner-facet-title-de">/ {facet.labelDe}</span>
          </h3>
        </div>
        <div className="planner-meta-row">
          <span className="planner-meta-pill">Weight {facet.importanceWeight}</span>
          <span className="planner-meta-pill">{facet.type || "type n/a"}</span>
          <span className="planner-meta-pill">{facet.group || "group n/a"}</span>
          {facet.authorityRole ? <span className="planner-meta-pill">{facet.authorityRole}</span> : null}
        </div>
      </div>

      <div className="planner-facet-columns">
        <div className="planner-facet-language-card">
          <div className="planner-language-title">Text (DE)</div>
          <p className="planner-facet-copy">{facet.summaryDe || "No German facet text captured."}</p>
          <PlannerTermGroup label="Canonical" terms={facet.canonicalTermsDe} />
          <PlannerTermGroup label="Neighbors" terms={facet.neighborTermsDe} />
          <PlannerTermGroup label="Exclusions" terms={facet.exclusionsDe} tone="warn" />
        </div>
        <div className="planner-facet-language-card">
          <div className="planner-language-title">Text (EN)</div>
          <p className="planner-facet-copy">{facet.summary || "No English facet text captured."}</p>
          <PlannerTermGroup label="Canonical" terms={facet.canonicalTerms} />
          <PlannerTermGroup label="Neighbors" terms={facet.neighborTerms} />
          <PlannerTermGroup label="Exclusions" terms={facet.exclusions} tone="warn" />
        </div>
      </div>

      <div className="planner-facet-footer">
        <div className="planner-meta-row">
          {facet.queryFamilyPreference ? <span className="planner-meta-pill">Query family: {facet.queryFamilyPreference}</span> : null}
          {facet.languageStrategy ? <span className="planner-meta-pill">Language: {facet.languageStrategy}</span> : null}
        </div>
        {blueprintLabels.length ? (
          <div className="planner-facet-blueprints">
            <span className="planner-language-label">Authority blueprints</span>
            <div className="planner-chip-cloud">
              {blueprintLabels.map((label, index) => (
                <span className="planner-chip planner-chip-muted" key={`${facet.id}:blueprint:${label}:${index}`}>
                  {label}
                </span>
              ))}
            </div>
          </div>
        ) : null}
      </div>
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
        <Accordion className="candidate-accordion-list" collapsible type="single">
          {rows.map((row, index) => (
            <AccordionItem className="candidate-accordion candidate-row-shell rounded-xl border border-border/70 bg-card" key={`${title}:${row.id}:${index}`} value={`${title}:${row.id}:${index}`}>
              <AccordionTrigger className="candidate-accordion-summary candidate-row-summary px-6 py-4 hover:no-underline">
                <div className="candidate-row-main">
                  <span className="candidate-rank">{index + 1}.</span>
                  <div className="candidate-row-copy">
                    <strong className="candidate-row-title">{row.title}</strong>
                    <div className="candidate-row-meta">
                      {row.year ?? "—"} · {row.venue || "Unknown venue"} · {formatNumber(row.citations)} citations
                    </div>
                  </div>
                </div>
                <div className="candidate-row-side">
                  <div className="candidate-row-citation-meta">
                    {formatNumber(row.citations)} cit. {row.year ?? "—"}
                  </div>
                  <Badge className="candidate-pool-badge" variant="outline">
                    {row.pool === "with_abstract" ? "with abstract" : "without abstract"}
                  </Badge>
                  <span className="score-pill candidate-score-pill">{scoreBadge(bestCandidateScore(row))}</span>
                </div>
              </AccordionTrigger>
              <AccordionContent className="candidate-accordion-body candidate-row-body pt-0">
                <div className="candidate-detail-grid">
                  <div className="stack gap-4">
                    <div className="candidate-detail-fields">
                      <div className="candidate-detail-field">
                        <span className="candidate-detail-label">Title</span>
                        <span className="candidate-detail-value">{row.title}</span>
                      </div>
                      {row.authorsLabel ? (
                        <div className="candidate-detail-field">
                          <span className="candidate-detail-label">Author</span>
                          <span className="candidate-detail-value">{row.authorsLabel}</span>
                        </div>
                      ) : null}
                      <div className="candidate-detail-field">
                        <span className="candidate-detail-label">Venue</span>
                        <span className="candidate-detail-value">{row.venue || "—"}</span>
                      </div>
                      {row.doi ? (
                        <div className="candidate-detail-field">
                          <span className="candidate-detail-label">DOI</span>
                          {row.resourceUrl ? (
                            <a className="resource-link candidate-detail-link" href={row.resourceUrl} rel="noreferrer" target="_blank">
                              {row.doi}
                            </a>
                          ) : (
                            <span className="candidate-detail-value">{row.doi}</span>
                          )}
                        </div>
                      ) : null}
                    </div>
                    {row.abstractPreview ? <p className="copy-block text-sm leading-7">{row.abstractPreview}</p> : null}
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
                  <div className="stack gap-4">
                    <div className="candidate-metric-grid">
                      {[
                        { label: "Match", value: scoreBadge(row.matchLane) },
                        { label: "Authority", value: scoreBadge(row.authorityLane) },
                        { label: "Rerank M", value: scoreBadge(row.rerankMatch) },
                        { label: "Rerank A", value: scoreBadge(row.rerankAuthority) },
                        { label: "Req hits", value: `${row.requiredFacetHits}` },
                        { label: "Tags", value: `${row.tagCount}` },
                      ].map((item, metricIndex) => (
                        <div className="candidate-metric-card" key={`${row.id}:metric:${item.label}:${metricIndex}`}>
                          <span className="candidate-metric-label">{item.label}</span>
                          <strong className="candidate-metric-value">{item.value}</strong>
                        </div>
                      ))}
                    </div>
                    <div className="candidate-chip-cloud">
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
                    </div>
                    {row.evidenceSnippets.length ? (
                      <Button className="w-fit" onClick={() => onOpen?.(row.id)} type="button" variant="outline">
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

function MetricBarsChart({
  items,
  valueLabel,
}: {
  items: LabelValue[];
  valueLabel: string;
}) {
  const rows = items
    .map((item) => ({
      label: truncateText(item.label, 22),
      value: parseMetricNumber(item.value),
    }))
    .filter((item) => item.value > 0);

  return <CountBarsChart label={valueLabel} rows={rows} />;
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

function StageCostChart({ rows }: { rows: RunDetail["overview"]["stageCosts"] }) {
  const plotted = rows
    .filter((row) => row.costRunUsd > 0 || row.costArtifactsUsd > 0)
    .map((row) => ({
      label: truncateText(row.label, 18),
      run: Number(row.costRunUsd.toFixed(4)),
      artifact: Number(row.costArtifactsUsd.toFixed(4)),
    }));

  if (!plotted.length) {
    return <ChartEmpty message="No stage costs captured." />;
  }

  return (
    <ChartContainer
      config={{
        run: { label: "run", color: "var(--chart-1)" },
        artifact: { label: "artifact", color: "var(--chart-2)" },
      }}
    >
      <ChartSurface>
        {({ width, height }) => (
          <BarChart data={plotted} height={height} width={width}>
            <CartesianGrid vertical={false} strokeDasharray="3 3" />
            <XAxis dataKey="label" tickLine={false} axisLine={false} fontSize={10} interval={0} angle={-18} textAnchor="end" height={52} />
            <YAxis tickLine={false} axisLine={false} fontSize={10} width={44} />
            <ChartTooltip content={<ChartTooltipContent />} />
            <ChartLegend content={<ChartLegendContent />} />
            <Bar dataKey="run" fill="var(--color-run)" radius={[6, 6, 0, 0]} />
            <Bar dataKey="artifact" fill="var(--color-artifact)" radius={[6, 6, 0, 0]} />
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

function QueryHealthChart({ providers }: { providers: RunDetail["queries"]["providers"] }) {
  const rows = providers.map((provider) => ({
    label: provider.label,
    queries: provider.queryCount,
    zeroHit: provider.zeroHitCount,
    duplicates: provider.duplicateQueryCount,
    uncovered: Math.max(0, provider.anchorCoverageTotal - provider.anchorCoverageHits),
  }));

  if (!rows.length) {
    return <ChartEmpty message="No query health data available." />;
  }

  return (
    <ChartContainer
      config={{
        queries: { label: "queries", color: "var(--chart-1)" },
        zeroHit: { label: "zero-hit", color: "var(--chart-2)" },
        duplicates: { label: "duplicates", color: "var(--chart-4)" },
        uncovered: { label: "anchor misses", color: "var(--chart-5)" },
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
            <Bar dataKey="queries" fill="var(--color-queries)" radius={[6, 6, 0, 0]} />
            <Bar dataKey="zeroHit" fill="var(--color-zeroHit)" radius={[6, 6, 0, 0]} />
            <Bar dataKey="duplicates" fill="var(--color-duplicates)" radius={[6, 6, 0, 0]} />
            <Bar dataKey="uncovered" fill="var(--color-uncovered)" radius={[6, 6, 0, 0]} />
          </BarChart>
        )}
      </ChartSurface>
    </ChartContainer>
  );
}

function QueryLengthDistributionChart({ providers }: { providers: RunDetail["queries"]["providers"] }) {
  const bucketSize = 10;
  const allRows = providers.flatMap((provider) => provider.rows);
  if (!allRows.length) {
    return <ChartEmpty message="No query strings available." />;
  }

  const lengths = allRows.map((row) => row.queryText.trim().length).filter((value) => value > 0);
  if (!lengths.length) {
    return <ChartEmpty message="No query strings available." />;
  }

  const maxLength = Math.max(...lengths);
  const maxBucket = Math.ceil(maxLength / bucketSize) * bucketSize;
  const bucketRows = Array.from({ length: Math.floor(maxBucket / bucketSize) + 1 }, (_, index) => ({
    label: `${index * bucketSize}`,
    openalex: 0,
    s2: 0,
  }));

  providers.forEach((provider) => {
    provider.rows.forEach((row) => {
      const length = row.queryText.trim().length;
      if (!length) {
        return;
      }
      const bucketIndex = Math.floor(length / bucketSize);
      const bucket = bucketRows[bucketIndex];
      if (!bucket) {
        return;
      }
      if (provider.provider === "openalex") {
        bucket.openalex += 1;
      } else {
        bucket.s2 += 1;
      }
    });
  });

  return (
    <ChartContainer
      config={{
        openalex: { label: "OpenAlex", color: "var(--chart-1)" },
        s2: { label: "S2", color: "var(--chart-2)" },
      }}
    >
      <ChartSurface>
        {({ width, height }) => (
          <BarChart data={bucketRows} height={height} width={width}>
            <CartesianGrid vertical={false} strokeDasharray="3 3" />
            <XAxis dataKey="label" tickLine={false} axisLine={false} fontSize={10} interval={bucketRows.length > 40 ? 2 : 0} minTickGap={4} />
            <YAxis tickLine={false} axisLine={false} fontSize={10} width={34} />
            <ChartTooltip content={<ChartTooltipContent />} />
            <ChartLegend content={<ChartLegendContent />} />
            <Bar dataKey="openalex" fill="var(--color-openalex)" radius={[4, 4, 0, 0]} />
            <Bar dataKey="s2" fill="var(--color-s2)" radius={[4, 4, 0, 0]} />
          </BarChart>
        )}
      </ChartSurface>
    </ChartContainer>
  );
}

function YearDistributionChart({ rows }: { rows: RunDetail["retrieval"]["yearBuckets"] }) {
  if (!rows.length) {
    return <ChartEmpty message="No publication-year spread available." />;
  }
  const tickInterval = rows.length > 36 ? Math.floor(rows.length / 18) : 0;
  return (
    <ChartContainer
      config={{
        openalex: { label: "OpenAlex", color: "var(--chart-1)" },
        semanticscholar: { label: "S2", color: "var(--chart-2)" },
      }}
    >
      <ChartSurface>
        {({ width, height }) => (
          <BarChart data={rows} height={height} width={width}>
            <CartesianGrid vertical={false} strokeDasharray="3 3" />
            <XAxis dataKey="year" tickLine={false} axisLine={false} fontSize={10} interval={tickInterval} minTickGap={4} />
            <YAxis tickLine={false} axisLine={false} fontSize={10} width={42} />
            <ChartTooltip content={<ChartTooltipContent />} />
            <ChartLegend content={<ChartLegendContent />} />
            <Bar dataKey="openalex" fill="var(--color-openalex)" radius={[4, 4, 0, 0]} />
            <Bar dataKey="semanticscholar" fill="var(--color-semanticscholar)" radius={[4, 4, 0, 0]} />
          </BarChart>
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

function LlmVsLaneScatterChart({ data }: { data: RunDetail["final"]["diagnostics"]["llmScoreVsLaneScore"] }) {
  const withData = data.filter((row) => row.pool === "with_abstract");
  const withoutData = data.filter((row) => row.pool === "without_abstract");
  if (!data.length) {
    return <ChartEmpty message="No rerank scatter data available." />;
  }

  return (
    <ChartContainer
      config={{
        with: { label: "with_abstract", color: "var(--chart-1)" },
        without: { label: "without_abstract", color: "var(--chart-2)" },
      }}
    >
      <ChartSurface>
        {({ width, height }) => (
          <ScatterChart height={height} width={width}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="lane_score" type="number" tickLine={false} axisLine={false} fontSize={10} />
            <YAxis dataKey="llm_score" type="number" tickLine={false} axisLine={false} fontSize={10} width={36} />
            <ChartTooltip content={<ChartTooltipContent hideLabel labelFormatter={() => null} />} />
            <Scatter data={withData} fill="var(--chart-1)" fillOpacity={0.35} name="with_abstract" />
            <Scatter data={withoutData} fill="var(--chart-2)" fillOpacity={0.35} name="without_abstract" />
          </ScatterChart>
        )}
      </ChartSurface>
    </ChartContainer>
  );
}

function MatchVsAuthorityChart({ data }: { data: RunDetail["final"]["diagnostics"]["matchVsAuthorityTop500"] }) {
  const withData = data.filter((row) => row.pool === "with_abstract");
  const withoutData = data.filter((row) => row.pool === "without_abstract");
  if (!data.length) {
    return <ChartEmpty message="No match-vs-authority sample is available." />;
  }

  return (
    <ChartContainer
      config={{
        with: { label: "with_abstract", color: "var(--chart-1)" },
        without: { label: "without_abstract", color: "var(--chart-2)" },
      }}
    >
      <ChartSurface>
        {({ width, height }) => (
          <ScatterChart height={height} width={width}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="match" type="number" tickLine={false} axisLine={false} fontSize={10} />
            <YAxis dataKey="authority" type="number" tickLine={false} axisLine={false} fontSize={10} width={36} />
            <ChartTooltip content={<ChartTooltipContent hideLabel />} />
            <Scatter data={withData} fill="var(--chart-1)" fillOpacity={0.35} name="with_abstract" />
            <Scatter data={withoutData} fill="var(--chart-2)" fillOpacity={0.35} name="without_abstract" />
          </ScatterChart>
        )}
      </ChartSurface>
    </ChartContainer>
  );
}

function LaneScoreByRankChart({
  withData,
  withoutData,
}: {
  withData: RunDetail["final"]["diagnostics"]["laneScoreByRankTop200"]["matchWith"];
  withoutData: RunDetail["final"]["diagnostics"]["laneScoreByRankTop200"]["matchWithout"];
}) {
  if (!withData.length && !withoutData.length) {
    return <ChartEmpty message="No rank-trend data is available." />;
  }

  return (
    <ChartContainer
      config={{
        withLine: { label: "with_abstract", color: "var(--chart-1)" },
        withoutLine: { label: "without_abstract", color: "var(--chart-2)" },
      }}
    >
      <ChartSurface>
        {({ width, height }) => (
          <LineChart height={height} width={width}>
            <CartesianGrid vertical={false} strokeDasharray="3 3" />
            <XAxis dataKey="rank" type="number" tickLine={false} axisLine={false} fontSize={10} />
            <YAxis dataKey="lane_score" tickLine={false} axisLine={false} fontSize={10} width={36} />
            <ChartTooltip content={<ChartTooltipContent hideLabel />} />
            <Line data={withData} dataKey="lane_score" dot={false} name="with_abstract" stroke="var(--chart-1)" strokeWidth={2} />
            <Line data={withoutData} dataKey="lane_score" dot={false} name="without_abstract" stroke="var(--chart-2)" strokeWidth={2} />
          </LineChart>
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

function FacetWeightChart({ run }: { run: RunDetail }) {
  const rows = [...run.plan.facets]
    .sort((left, right) => right.importanceWeight - left.importanceWeight)
    .slice(0, 10)
    .map((facet) => ({
      label: truncateText(facet.label, 24),
      weight: facet.importanceWeight,
      canonical: facet.canonicalTerms.length,
    }));

  if (!rows.length) {
    return <ChartEmpty message="No facet definitions available." />;
  }

  return (
    <ChartContainer
      config={{
        weight: { label: "weight", color: "var(--chart-2)" },
        canonical: { label: "canonical", color: "var(--chart-3)" },
      }}
    >
      <ChartSurface>
        {({ width, height }) => (
          <BarChart data={rows} height={height} width={width}>
            <CartesianGrid vertical={false} strokeDasharray="3 3" />
            <XAxis dataKey="label" tickLine={false} axisLine={false} fontSize={10} interval={0} angle={-18} textAnchor="end" height={52} />
            <YAxis tickLine={false} axisLine={false} fontSize={10} width={42} />
            <ChartTooltip content={<ChartTooltipContent />} />
            <ChartLegend content={<ChartLegendContent />} />
            <Bar dataKey="weight" fill="var(--color-weight)" radius={[6, 6, 0, 0]} />
            <Bar dataKey="canonical" fill="var(--color-canonical)" radius={[6, 6, 0, 0]} />
          </BarChart>
        )}
      </ChartSurface>
    </ChartContainer>
  );
}

function CoverageGapChart({ rows }: { rows: RunDetail["coverage"]["missingRequiredBySection"] }) {
  const plotted = rows.map((row) => ({
    label: truncateText(row.label, 22),
    missing: row.missingCount,
  }));

  if (!plotted.length) {
    return <ChartEmpty message="No required facet gaps were detected." />;
  }

  return (
    <ChartContainer config={{ missing: { label: "missing", color: "var(--chart-5)" } }}>
      <ChartSurface>
        {({ width, height }) => (
          <BarChart data={plotted} height={height} width={width}>
            <CartesianGrid vertical={false} strokeDasharray="3 3" />
            <XAxis dataKey="label" tickLine={false} axisLine={false} fontSize={10} interval={0} angle={-18} textAnchor="end" height={52} />
            <YAxis tickLine={false} axisLine={false} fontSize={10} width={42} />
            <ChartTooltip content={<ChartTooltipContent />} />
            <Bar dataKey="missing" fill="var(--color-missing)" radius={[6, 6, 0, 0]} />
          </BarChart>
        )}
      </ChartSurface>
    </ChartContainer>
  );
}

function RerankDecisionChart({ run }: { run: RunDetail }) {
  const rows = [
    { label: "High signal", value: run.rerank.highSignal.length },
    { label: "Off topic", value: run.rerank.offTopic.length },
    { label: "Insufficient", value: run.rerank.insufficient.length },
    { label: "Pairwise", value: run.rerank.pairwiseDecisions.length },
  ];

  return <CountBarsChart label="rows" rows={rows} />;
}

function FinalOutputHealthChart({ run }: { run: RunDetail }) {
  const rows = run.final.outputs.map((section) => {
    const rowsMetric = section.metrics?.find((item) => item.label === "Rows")?.value ?? `${section.rows.length}`;
    const linksMetric = section.metrics?.find((item) => item.label === "Links")?.value ?? "0";
    return {
      label: truncateText(section.label, 18),
      rows: parseMetricNumber(rowsMetric),
      links: parseMetricNumber(linksMetric),
    };
  });

  if (!rows.length) {
    return <ChartEmpty message="No final output metrics available." />;
  }

  return (
    <ChartContainer
      config={{
        rows: { label: "rows", color: "var(--chart-1)" },
        links: { label: "links", color: "var(--chart-3)" },
      }}
    >
      <ChartSurface>
        {({ width, height }) => (
          <BarChart data={rows} height={height} width={width}>
            <CartesianGrid vertical={false} strokeDasharray="3 3" />
            <XAxis dataKey="label" tickLine={false} axisLine={false} fontSize={10} interval={0} angle={-18} textAnchor="end" height={52} />
            <YAxis tickLine={false} axisLine={false} fontSize={10} width={42} />
            <ChartTooltip content={<ChartTooltipContent />} />
            <ChartLegend content={<ChartLegendContent />} />
            <Bar dataKey="rows" fill="var(--color-rows)" radius={[6, 6, 0, 0]} />
            <Bar dataKey="links" fill="var(--color-links)" radius={[6, 6, 0, 0]} />
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
  const [compareSectionId, setCompareSectionId] = useState<string | null>(null);
  const [selectedFacetId, setSelectedFacetId] = useState<string | null>(null);
  const fingerprintRef = useRef("");

  const deferredRunSearch = useDeferredValue(runSearch);
  const deferredCandidateSearch = useDeferredValue(candidateSearch);
  const noCompareValue = "__none__";

  const selectedRun = initialData.selectedRun;
  const compareRun = initialData.compareRun;
  const comparison = initialData.comparison;
  const localRunFingerprint = useMemo(() => {
    return [...initialData.runs]
      .map((run) => `${run.id}:${run.modifiedAt}`)
      .sort((left, right) => left.localeCompare(right))
      .join("|");
  }, [initialData.runs]);

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

  function refreshDashboard() {
    startTransition(() => {
      router.refresh();
    });
  }

  const checkForRunUpdates = useEffectEvent(async () => {
    try {
      const response = await fetch("/api/run-fingerprint", {
        cache: "no-store",
      });
      if (!response.ok) {
        return;
      }

      const payload = (await response.json()) as RunFingerprintPayload;
      if (payload.fingerprint && payload.fingerprint !== fingerprintRef.current) {
        fingerprintRef.current = payload.fingerprint;
        refreshDashboard();
      }
    } catch {
      return;
    }
  });

  useEffect(() => {
    fingerprintRef.current = localRunFingerprint;
  }, [localRunFingerprint]);

  useEffect(() => {
    const handleFocus = () => {
      void checkForRunUpdates();
    };

    const handleVisibilityChange = () => {
      if (document.visibilityState === "visible") {
        void checkForRunUpdates();
      }
    };

    const interval = window.setInterval(() => {
      if (document.visibilityState === "visible") {
        void checkForRunUpdates();
      }
    }, 15000);

    window.addEventListener("focus", handleFocus);
    document.addEventListener("visibilitychange", handleVisibilityChange);

    return () => {
      window.clearInterval(interval);
      window.removeEventListener("focus", handleFocus);
      document.removeEventListener("visibilitychange", handleVisibilityChange);
    };
  }, []);

  return (
    <div className="dashboard-page">
      <div className="dashboard-main">
        {isPending ? <div className="loading-strip rounded-xl border border-border/70 bg-card/90 shadow-sm">Loading run data…</div> : null}
        {selectedRun ? (
          <>
            <Card className="hero-panel hero-panel-flat rounded-[28px] border-border/70 bg-card/95 p-6 shadow-sm">
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
                  <div className="stack gap-2 items-end">
                    <Button onClick={refreshDashboard} size="sm" type="button" variant="outline">
                      {isPending ? "Refreshing…" : "Refresh runs"}
                    </Button>
                    <p className="muted-copy max-w-[18rem] text-right text-xs">New notebook runs are detected automatically when the dashboard regains focus.</p>
                  </div>
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
                <AccordionTrigger className="px-6 py-5 hover:no-underline">
                  <div className="text-left">
                    <div className="section-eyebrow">Run browser</div>
                    <div className="text-sm font-semibold">Browse cached runs</div>
                  </div>
                </AccordionTrigger>
                <AccordionContent className="px-6 pb-6">
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

              <Card className="content-panel content-panel-wide rounded-[24px] border-border/70 bg-card/95 p-6 shadow-sm">
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
                compareSectionId,
                onCompareSectionChange: setCompareSectionId,
                selectedFacetId,
                onFacetSelect: setSelectedFacetId,
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
  compareSectionId,
  onCompareSectionChange,
  selectedFacetId,
  onFacetSelect,
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
  compareSectionId: string | null;
  onCompareSectionChange: (value: string) => void;
  selectedFacetId: string | null;
  onFacetSelect: (value: string) => void;
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
        <details className="expand-shell" open>
          <summary>Visual diagnostics</summary>
          <div className="stack gap-4">
            <div className="split-grid">
              <ChartCard description="Measured stage durations from the notebook metrics cache." title="Stage duration profile">
                <PhaseDurationChart run={run} />
              </ChartCard>
              <ChartCard description="Direct stage cost comparison between runtime telemetry and artifact cache metadata." title="Stage cost profile">
                <StageCostChart rows={run.overview.stageCosts} />
              </ChartCard>
            </div>
            <div className="split-grid">
              <ChartCard description="Core retrieval and ranking counts at a glance." title="Pipeline counts">
                <CountBarsChart
                  label="count"
                  rows={run.overview.metrics.map((metric) => ({
                    label: metric.label.replace(" rows", "").replace(" ", "\n"),
                    value: parseMetricNumber(metric.value),
                  }))}
                />
              </ChartCard>
              <ChartCard description="How many phases are complete, partial, or still missing." title="Phase status mix">
                <CountBarsChart
                  label="phases"
                  rows={[
                    { label: "complete", value: run.phaseCards.filter((card) => card.status === "complete").length },
                    { label: "partial", value: run.phaseCards.filter((card) => card.status === "partial").length },
                    { label: "missing", value: run.phaseCards.filter((card) => card.status === "missing").length },
                  ]}
                />
              </ChartCard>
            </div>
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
    const selectedFacet = run.plan.facets.find((facet) => facet.id === selectedFacetId) ?? run.plan.facets[0] ?? null;
    const selectedFacetBlueprints = selectedFacet
      ? run.plan.blueprints.filter((blueprint) => blueprint.targets.includes(selectedFacet.id)).map((blueprint) => blueprint.label)
      : [];
    const anchorCount = uniqueStrings([...run.plan.anchorsEn, ...run.plan.anchorsDe]).length;
    const globalTermsCount = uniqueStrings([...run.plan.coreTermsEn, ...run.plan.coreTermsDe, ...run.plan.canonicalTermsEn, ...run.plan.canonicalTermsDe]).length;
    const exclusionCount = uniqueStrings([...run.plan.exclusionsEn, ...run.plan.exclusionsDe]).length;

    return (
      <div className="stack gap-6">
        <SectionHeader title="Planner output" description="Topic framing, object anchors, facet design, and constraint hygiene before retrieval starts." />
        <div className="planner-summary-grid">
          <PlannerSummaryCard text={run.plan.summaryDe} title="Topic Summary (DE)" />
          <PlannerSummaryCard text={run.plan.summaryEn} title="Topic Summary (EN)" />
        </div>
        <div className="planner-term-grid">
          <PlannerSectionCard count={anchorCount} title="Primary Anchors">
            <div className="planner-language-stack">
              <PlannerTermGroup label="EN" terms={run.plan.anchorsEn} />
              <PlannerTermGroup label="DE" terms={run.plan.anchorsDe} />
            </div>
          </PlannerSectionCard>
          <PlannerSectionCard count={globalTermsCount} title="Global Terms">
            <div className="planner-language-stack">
              <PlannerTermGroup label="EN" limit={10} terms={[...run.plan.coreTermsEn, ...run.plan.canonicalTermsEn]} />
              <PlannerTermGroup label="DE" limit={10} terms={[...run.plan.coreTermsDe, ...run.plan.canonicalTermsDe]} />
            </div>
          </PlannerSectionCard>
          <PlannerSectionCard count={exclusionCount} title="Global Exclusions">
            <div className="planner-language-stack">
              <PlannerTermGroup label="EN" terms={run.plan.exclusionsEn} tone="warn" />
              <PlannerTermGroup label="DE" terms={run.plan.exclusionsDe} tone="warn" />
            </div>
          </PlannerSectionCard>
        </div>
        <PlannerSectionCard note="Summary table (click a facet row below for full details)." title="Facets">
          {run.plan.facets.length ? (
            <>
              <div className="table-shell planner-facet-table-shell">
                <Table className="dashboard-table planner-facet-table min-w-[920px]">
                  <TableHeader>
                    <TableRow>
                      <TableHead>Weight</TableHead>
                      <TableHead>Type</TableHead>
                      <TableHead>Facet</TableHead>
                      <TableHead>Label (EN)</TableHead>
                      <TableHead>Label (DE)</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {run.plan.facets.map((facet) => {
                      const isActive = facet.id === selectedFacet?.id;
                      return (
                        <TableRow
                          className={cn("clickable-row planner-facet-row", isActive && "planner-facet-row-active")}
                          key={facet.id}
                          onClick={() => onFacetSelect(facet.id)}
                          onKeyDown={(event) => {
                            if (event.key === "Enter" || event.key === " ") {
                              event.preventDefault();
                              onFacetSelect(facet.id);
                            }
                          }}
                          tabIndex={0}
                        >
                          <TableCell className="planner-facet-weight-cell">{facet.importanceWeight}</TableCell>
                          <TableCell>{facet.type || "—"}</TableCell>
                          <TableCell className="planner-facet-id-cell">{facet.id}</TableCell>
                          <TableCell>{facet.label}</TableCell>
                          <TableCell>{facet.labelDe || "—"}</TableCell>
                        </TableRow>
                      );
                    })}
                  </TableBody>
                </Table>
              </div>
              {selectedFacet ? <PlannerFacetDetail blueprintLabels={selectedFacetBlueprints} facet={selectedFacet} /> : null}
            </>
          ) : (
            <div className="dashboard-empty">No facets available.</div>
          )}
        </PlannerSectionCard>
        <details className="expand-shell">
          <summary>Planner diagnostics</summary>
          <div className="stack gap-4">
            <div className="split-grid">
              <PlannerSectionCard count={run.plan.constraints.length} title="Must-keep constraints">
                <div className="planner-note-list">
                  {run.plan.constraints.length ? (
                    run.plan.constraints.map((item, index) => (
                      <div className="planner-note-row" key={`constraint:${item}:${index}`}>
                        {item}
                      </div>
                    ))
                  ) : (
                    <p className="planner-empty-copy">No must-keep constraints captured.</p>
                  )}
                </div>
              </PlannerSectionCard>
              <PlannerSectionCard count={run.plan.driftRisks.length} title="Drift risks">
                <div className="planner-note-list">
                  {run.plan.driftRisks.length ? (
                    run.plan.driftRisks.map((item, index) => (
                      <div className="planner-note-row" key={`drift:${item}:${index}`}>
                        {item}
                      </div>
                    ))
                  ) : (
                    <p className="planner-empty-copy">No drift risks captured.</p>
                  )}
                </div>
              </PlannerSectionCard>
            </div>
            {run.plan.blueprints.length ? (
              <PlannerSectionCard count={run.plan.blueprints.length} title="Authority blueprints">
                <div className="planner-blueprint-grid">
                  {run.plan.blueprints.map((blueprint, index) => (
                    <div className="planner-blueprint-card" key={`${blueprint.label}:${index}`}>
                      <div className="planner-blueprint-topline">
                        <strong>{blueprint.label}</strong>
                        <span className="planner-count-pill planner-count-pill-soft">{blueprint.targets.length}</span>
                      </div>
                      <div className="planner-meta-row">
                        {blueprint.kind ? <span className="planner-meta-pill">{blueprint.kind}</span> : null}
                        {blueprint.searchBreadth ? <span className="planner-meta-pill">{blueprint.searchBreadth}</span> : null}
                        {blueprint.languageStrategy ? <span className="planner-meta-pill">{blueprint.languageStrategy}</span> : null}
                      </div>
                      <p className="planner-blueprint-copy">{blueprint.notes || blueprint.labelDe || "No blueprint notes captured."}</p>
                      <div className="planner-chip-cloud">
                        {blueprint.targets.map((target, targetIndex) => (
                          <span className="planner-chip planner-chip-muted" key={`${blueprint.label}:target:${target}:${targetIndex}`}>
                            {target}
                          </span>
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
              </PlannerSectionCard>
            ) : null}
          </div>
        </details>
        <details className="expand-shell">
          <summary>Visual diagnostics and traces</summary>
          <div className="stack gap-4">
            <div className="split-grid">
              <ChartCard description="How much structure the planner produced before retrieval starts." title="Planner surface area">
                <PlannerCompositionChart run={run} />
              </ChartCard>
              <ChartCard description="Canonical, neighboring, and exclusion term density for the first facet set." title="Facet design density" tall>
                <FacetDensityChart run={run} />
              </ChartCard>
            </div>
            <div className="split-grid">
              <ChartCard description="Top-weighted facets to quickly spot over- or under-emphasized planner branches." title="Facet weight balance">
                <FacetWeightChart run={run} />
              </ChartCard>
              <ChartCard description="How many retrieval targets each authority blueprint is trying to cover." title="Blueprint target breadth">
                <CountBarsChart
                  label="targets"
                  rows={run.plan.blueprints.map((blueprint) => ({
                    label: truncateText(blueprint.label, 22),
                    value: blueprint.targets.length,
                  }))}
                />
              </ChartCard>
            </div>
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
        <details className="expand-shell" open>
          <summary>Visual diagnostics</summary>
          <div className="stack gap-4">
            <div className="split-grid">
              <ChartCard description="Total hit yield and query volume by provider." title="Provider query yield">
                <ProviderHitsChart providers={run.queries.providers} />
              </ChartCard>
              <ChartCard description="Zero-hit, duplicate, and anchor-coverage misses per provider." title="Query health flags">
                <QueryHealthChart providers={run.queries.providers} />
              </ChartCard>
            </div>
            <ChartCard description="Character-count distribution of generated query strings, separated by provider." title="Query string length distribution" tall>
              <QueryLengthDistributionChart providers={run.queries.providers} />
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
        <SectionHeader title="Retrieval outcomes" description="Provider totals, hit distributions, and publication-year spread across raw retrieval." />
        <div className="metric-grid">
          {run.retrieval.providers.map((provider) => (
            <MetricCard
              key={provider.provider}
              metric={{
                label: provider.label,
                value: `${provider.totalHits} hits`,
                detail: `${provider.queryCount} queries, ${provider.failedQueries} failed, ${provider.zeroHitQueries} zero-hit, strongest query hit ${provider.strongestHits}`,
              }}
            />
          ))}
        </div>
        <details className="expand-shell" open>
          <summary>Visual diagnostics</summary>
          <div className="split-grid">
            <ChartCard description="Raw hit volume and query counts per provider." title="Retrieval provider totals">
              <ProviderHitsChart providers={run.retrieval.providers} />
            </ChartCard>
            <ChartCard description="Publication-year spread across retrieved records, separated by provider." title="Year Distribution of Retrieved Records" tall>
              <YearDistributionChart rows={run.retrieval.yearBuckets} />
            </ChartCard>
          </div>
        </details>
        <article className="dashboard-card">
          <div className="dashboard-card-label">Phase D - Provider summary</div>
          <DataTable
            columns={["Provider", "Queries", "Failed", "Failed %", "Records", "Zero Q", "Zero %", "Mean", "Median", "p90", "Max", "Dominance"]}
            empty="No provider summary available."
            renderRow={(value) => {
              const provider = value as RunDetail["retrieval"]["providers"][number];
              return (
                <tr key={provider.provider}>
                  <td>{provider.label}</td>
                  <td>{formatNumber(provider.queryCount)}</td>
                  <td>{formatNumber(provider.failedQueries)}</td>
                  <td>{formatPercent(provider.failedRate)}</td>
                  <td>{formatNumber(provider.totalHits)}</td>
                  <td>{formatNumber(provider.zeroHitQueries)}</td>
                  <td>{formatPercent(provider.zeroHitRate)}</td>
                  <td>{formatNumber(Math.round(provider.meanHits))}</td>
                  <td>{formatNumber(provider.medianHits)}</td>
                  <td>{formatNumber(provider.p90Hits)}</td>
                  <td>{formatNumber(provider.maxHits)}</td>
                  <td>{provider.dominanceShare === null ? "—" : formatPercent(provider.dominanceShare)}</td>
                </tr>
              );
            }}
            rows={run.retrieval.providers}
          />
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
        <article className="dashboard-card candidate-identifier-card">
          <div className="dashboard-card-label">Identifier coverage</div>
          <InlineStatRow items={run.candidates.idCoverage.map((item) => ({ label: item.label, value: item.value }))} />
        </article>
        <details className="expand-shell" open>
          <summary>Visual diagnostics</summary>
          <div className="stack gap-4">
            <div className="candidate-diagnostics-primary">
              <ChartCard description="Citation count against strongest lane score for the current candidate sample." title="Citations vs lane score" tall>
                <CitationScatterChart rows={run.candidates.catalog} />
              </ChartCard>
              <ChartCard description="How many rows survive into each candidate pool." title="Pool size split" tall>
                <CandidatePoolChart run={run} />
              </ChartCard>
            </div>
            <div className="candidate-diagnostics-tertiary">
              <ChartCard description="Provider mixing and cross-provider joins across the candidate pool." title="Provider signal mix">
                <MetricBarsChart items={run.candidates.providerMix} valueLabel="rows" />
              </ChartCard>
              <ChartCard description="Identifier coverage to spot brittle rows before scoring." title="Identifier coverage">
                <MetricBarsChart items={run.candidates.idCoverage} valueLabel="rows" />
              </ChartCard>
            </div>
          </div>
        </details>
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
        <details className="expand-shell" open>
          <summary>Visual diagnostics</summary>
          <div className="stack gap-4">
            <div className="split-grid">
              <ChartCard description="Top leaderboard score decay across the current scoring stages." title="Score trends by rank" tall>
                <ScoreTrendChart sections={[...run.scoring.stage2, ...run.scoring.final]} />
              </ChartCard>
              <ChartCard description="Top stage-1 leaderboard score decay across pools and lanes." title="Stage-1 shape" tall>
                <ScoreTrendChart sections={run.scoring.stage1} />
              </ChartCard>
            </div>
            <ChartCard description="How many rows make it into each leaderboard slice across stage 1, stage 2, and final scoring." title="Leaderboard row counts">
              <CountBarsChart
                label="rows"
                rows={[...run.scoring.stage1, ...run.scoring.stage2, ...run.scoring.final].map((section) => ({
                  label: truncateText(section.label, 22),
                  value: section.rows.length,
                }))}
              />
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
        <details className="expand-shell" open>
          <summary>Visual diagnostics</summary>
          <div className="split-grid">
            <ChartCard description="Most frequently surfaced chapter facets across coverage-tagged rows." title="Facet concentration" tall>
              <FacetCoverageChart run={run} />
            </ChartCard>
            <ChartCard description="Which final-output sections still miss the most required facets." title="Required facet gaps" tall>
              <CoverageGapChart rows={run.coverage.missingRequiredBySection} />
            </ChartCard>
          </div>
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
        <details className="expand-shell" open>
          <summary>Visual diagnostics</summary>
          <div className="stack gap-4">
            <div className="split-grid">
              <ChartCard description="Post-rerank top-list score decay across the lane sections." title="Rerank score trends" tall>
                <ScoreTrendChart sections={run.rerank.laneRankings} />
              </ChartCard>
              <ChartCard description="High-signal, off-topic, insufficient-info, and pairwise volumes in one glance." title="Rerank decision mix">
                <RerankDecisionChart run={run} />
              </ChartCard>
            </div>
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
    const rankSourceLabel =
      run.final.diagnostics.laneScoreByRankTop200.source === "stage_i"
        ? "Uses Stage I rerank ordering, matching the production dialog."
        : run.final.diagnostics.laneScoreByRankTop200.source === "stage_g"
          ? "Uses Stage G shortlist ordering because no rerank ranking is available."
          : "No ranking series available.";

    return (
      <div className="stack gap-6">
        <SectionHeader title="Final output lists" description="The exact lane and pool lists that would normally be surfaced downstream, shown as expandable result cards with the most useful audit signals inline." />
        <details className="expand-shell" open>
          <summary>Visual diagnostics</summary>
          <div className="stack gap-4">
            <div className="split-grid">
              <ChartCard description="Production-compatible rerank scatter: lane score on x, LLM rerank score on y, colored by pool." title="LLM Score vs Lane Score" tall>
                <LlmVsLaneScatterChart data={run.final.diagnostics.llmScoreVsLaneScore} />
              </ChartCard>
              <ChartCard description="Production-compatible top-500 scatter: x uses match_stage1, y uses authority, selected by highest match_lane." title="Match vs Authority (Top 500)" tall>
                <MatchVsAuthorityChart data={run.final.diagnostics.matchVsAuthorityTop500} />
              </ChartCard>
            </div>
            <div className="split-grid">
              <ChartCard description={`${rankSourceLabel} Match lane score is plotted against rank for with_abstract and without_abstract.`} title="match: lane_score by rank (top 200)" tall>
                <LaneScoreByRankChart
                  withData={run.final.diagnostics.laneScoreByRankTop200.matchWith}
                  withoutData={run.final.diagnostics.laneScoreByRankTop200.matchWithout}
                />
              </ChartCard>
              <ChartCard description={`${rankSourceLabel} Authority lane score is plotted against rank for with_abstract and without_abstract.`} title="authority: lane_score by rank (top 200)" tall>
                <LaneScoreByRankChart
                  withData={run.final.diagnostics.laneScoreByRankTop200.authorityWith}
                  withoutData={run.final.diagnostics.laneScoreByRankTop200.authorityWithout}
                />
              </ChartCard>
            </div>
            <div className="split-grid">
              <ChartCard description="How many final output rows are emitted per lane and pool section." title="Final output section sizes">
                <CountBarsChart label="rows" rows={run.final.outputs.map((section) => ({ label: truncateText(section.label, 18), value: section.rows.length }))} />
              </ChartCard>
              <ChartCard description="Score shape inside the final top lists." title="Final rank trends" tall>
                <ScoreTrendChart sections={run.final.outputs} />
              </ChartCard>
            </div>
            <ChartCard description="Direct view of how many linkable records survive into each final section." title="Final output link coverage">
              <FinalOutputHealthChart run={run} />
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
    const finalSectionIds = orderedCompareSections([...run.final.outputs.map((section) => section.id), ...compareRun.final.outputs.map((section) => section.id)]);
    const activeCompareSectionId = compareSectionId && finalSectionIds.includes(compareSectionId) ? compareSectionId : finalSectionIds[0] ?? null;
    const activeLeftSection = activeCompareSectionId ? finalSectionForRun(run, activeCompareSectionId) : null;
    const activeRightSection = activeCompareSectionId ? finalSectionForRun(compareRun, activeCompareSectionId) : null;

    return (
      <div className="stack gap-6">
        <SectionHeader title="Run comparison" description="Focused side-by-side comparison for the key phase metrics and final lane outcomes." />
        <InlineStatRow items={comparison.metrics.map((metric) => ({ label: metric.label, value: metric.value }))} />
        <div className="compare-page-grid">
          {[run, compareRun].map((entry, index) => (
            <Card className="compare-overview-card border-border/70 bg-card/95 shadow-sm" key={`${entry.id}:${index}`}>
              <CardHeader className="space-y-3 pb-3">
                <div className="compare-overview-topline">
                  <div className="section-eyebrow">{index === 0 ? "Selected run" : "Comparison run"}</div>
                  <Badge variant={statusBadgeVariant(entry.statusLabel)}>{entry.statusLabel}</Badge>
                </div>
                <CardTitle className="text-[1.05rem] leading-6">{entry.chapterTitle}</CardTitle>
                <CardDescription>{truncateText(entry.topicSummary, 220)}</CardDescription>
                <div className="hero-meta">
                  <span>{entry.id}</span>
                  <span>{formatDate(entry.modifiedAt)}</span>
                </div>
              </CardHeader>
              <CardContent className="space-y-4 pt-0">
                <InlineStatRow items={entry.headerStats.map((metric) => ({ label: metric.label, value: metric.value }))} />
                <div className="compare-summary-note">{index === 0 ? "Primary baseline for the notebook run." : "Side-by-side reference run for quick drift checks."}</div>
              </CardContent>
            </Card>
          ))}
        </div>
        <Card className="border-border/70 bg-card/95 shadow-sm">
          <CardHeader className="pb-3">
            <CardDescription className="dashboard-card-label">Stage-by-stage cost and duration</CardDescription>
          </CardHeader>
          <CardContent className="pt-0">
            <div className="table-shell compare-stage-shell">
              <Table className="compare-compact-table">
                <TableHeader>
                  <TableRow>
                    <TableHead>Stage</TableHead>
                    <TableHead>Left duration</TableHead>
                    <TableHead>Left cost</TableHead>
                    <TableHead>Right duration</TableHead>
                    <TableHead>Right cost</TableHead>
                    <TableHead>Model / info</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {stageKeys.map((stageKey, index) => {
                    const left = run.overview.stageCosts.find((row) => row.stage === stageKey);
                    const right = compareRun.overview.stageCosts.find((row) => row.stage === stageKey);
                    const label = left?.label || right?.label || stageKey;
                    const leftTotalCost = (left?.costRunUsd ?? 0) + (left?.costArtifactsUsd ?? 0);
                    const rightTotalCost = (right?.costRunUsd ?? 0) + (right?.costArtifactsUsd ?? 0);
                    return (
                      <TableRow key={`${stageKey}:${index}`}>
                        <td className="compare-stage-name-cell">
                          <div className="compare-stage-name">{label}</div>
                          <div className="compare-stage-subtle">{stageKey}</div>
                        </td>
                        <td>{left?.durationSeconds !== null && left?.durationSeconds !== undefined ? `${left.durationSeconds.toFixed(1)} s` : "—"}</td>
                        <td>${leftTotalCost.toFixed(4)}</td>
                        <td>{right?.durationSeconds !== null && right?.durationSeconds !== undefined ? `${right.durationSeconds.toFixed(1)} s` : "—"}</td>
                        <td>${rightTotalCost.toFixed(4)}</td>
                        <td className="compare-stage-model-cell">{truncateText(left?.model || right?.model || left?.info || right?.info || "—", 44)}</td>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            </div>
          </CardContent>
        </Card>
        <Card className="border-border/70 bg-card/95 shadow-sm">
          <CardHeader className="pb-3">
            <CardDescription className="dashboard-card-label">Result lanes</CardDescription>
            <div className="compare-lane-strip">
              {finalSectionIds.map((sectionId) => {
                const left = finalSectionForRun(run, sectionId);
                const count = left?.rows.length ?? finalSectionForRun(compareRun, sectionId)?.rows.length ?? 0;
                return (
                  <Button
                    className="compare-lane-button"
                    key={sectionId}
                    onClick={() => onCompareSectionChange(sectionId)}
                    size="sm"
                    type="button"
                    variant={activeCompareSectionId === sectionId ? "secondary" : "ghost"}
                  >
                    {compareSectionShortLabel(sectionId)} <span className="compare-lane-count">{count}</span>
                  </Button>
                );
              })}
            </div>
          </CardHeader>
          <CardContent className="pt-0">
            {activeCompareSectionId ? (
              <div className="compare-results-grid">
                {[
                  { entry: run, section: activeLeftSection, label: "Selected run" },
                  { entry: compareRun, section: activeRightSection, label: "Comparison run" },
                ].map(({ entry, section, label }, sideIndex) => (
                  <Card className="compare-results-card gap-0 border-border/70 bg-background shadow-none" key={`${label}:${sideIndex}`}>
                    <CardHeader className="pb-3">
                      <div className="compare-overview-topline">
                        <div className="section-eyebrow">{label}</div>
                        <Badge variant={sideIndex === 0 ? "outline" : "secondary"}>{compareSectionShortLabel(activeCompareSectionId)}</Badge>
                      </div>
                      <CardTitle className="text-base leading-6">{entry.chapterTitle}</CardTitle>
                      <InlineStatRow items={section?.metrics ?? []} />
                    </CardHeader>
                    <CardContent className="pt-0">
                      {section?.rows?.length ? (
                        <div className="table-shell compare-results-shell">
                          <Table className="compare-results-table">
                            <TableHeader>
                              <TableRow>
                                <TableHead>#</TableHead>
                                <TableHead>Titel</TableHead>
                                <TableHead>Jahr</TableHead>
                                <TableHead>Zitierungen</TableHead>
                                <TableHead>Score</TableHead>
                                <TableHead>Venue</TableHead>
                              </TableRow>
                            </TableHeader>
                            <TableBody>
                              {section.rows.map((row, rowIndex) => (
                                <TableRow className="clickable-row" key={`${activeCompareSectionId}:${row.id}:${rowIndex}`} onClick={() => onCandidateOpen(row.id)}>
                                  <td className="compare-rank-cell">{rowIndex + 1}</td>
                                  <td className="compare-title-cell">
                                    {row.resourceUrl ? (
                                      <a className="compare-title-link" href={row.resourceUrl} onClick={(event) => event.stopPropagation()} rel="noreferrer" target="_blank">
                                        {truncateText(row.title, 108)}
                                      </a>
                                    ) : (
                                      <span>{truncateText(row.title, 108)}</span>
                                    )}
                                  </td>
                                  <td>{row.year ?? "—"}</td>
                                  <td>{formatNumber(row.citations)}</td>
                                  <td>
                                    <span className="compare-score-badge">{compareScoreBadge(compareSectionScore(activeCompareSectionId, row))}</span>
                                  </td>
                                  <td className="compare-venue-cell">{truncateText(row.venue || "—", 36)}</td>
                                </TableRow>
                              ))}
                            </TableBody>
                          </Table>
                        </div>
                      ) : (
                        <div className="dashboard-empty">No rows available in this lane.</div>
                      )}
                    </CardContent>
                  </Card>
                ))}
              </div>
            ) : (
              <div className="dashboard-empty">No comparable final output lanes found.</div>
            )}
          </CardContent>
        </Card>
        <div className="compare-query-summary">
          <Card className="border-border/70 bg-card/95 shadow-sm">
            <CardHeader className="pb-3">
              <CardDescription className="dashboard-card-label">Query diff summary</CardDescription>
            </CardHeader>
            <CardContent className="pt-0">
              <InlineStatRow items={comparison.queryDiffs} />
            </CardContent>
          </Card>
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
