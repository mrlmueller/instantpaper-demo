"use client";

import { useEffect, useMemo, useState } from "react";
import { X } from "lucide-react";
import { onSnapshot } from "firebase/firestore";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, XAxis, YAxis } from "recharts";

import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { Dialog, DialogClose, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { firestoreClient } from "@/app/lib/firebase/firestoreClient";
import { quellenFinderPdfScanDetailsDoc } from "@/app/lib/firestore/refs";
import type { PdfScanDetailsDoc, PdfScanDocSummaryDoc } from "@/app/lib/firestore/types";

type WithId<T> = T & { id: string };
type PdfDocRow = WithId<PdfScanDocSummaryDoc>;

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" ? (value as Record<string, unknown>) : {};
}

function asRecordArray(value: unknown): Array<Record<string, unknown>> {
  return Array.isArray(value) ? value.filter((item): item is Record<string, unknown> => !!item && typeof item === "object") : [];
}

function formatNumber(value: unknown, digits = 0): string {
  const n = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(n)) return "—";
  return digits > 0 ? n.toFixed(digits) : new Intl.NumberFormat("de-DE").format(Math.round(n));
}

function KpiCard({ label, value }: { label: string; value: string }) {
  return (
    <Card className="p-4">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="mt-1 text-lg font-semibold tabular-nums">{value}</div>
    </Card>
  );
}

function SimpleTable({
  rows,
  columns,
}: {
  rows: Array<Record<string, unknown>>;
  columns: Array<{ key: string; label: string }>;
}) {
  if (rows.length === 0) {
    return <div className="text-sm text-muted-foreground">Keine Daten.</div>;
  }
  return (
    <div className="rounded-md border border-border overflow-auto">
      <Table>
        <TableHeader>
          <TableRow>
            {columns.map((column) => (
              <TableHead key={column.key}>{column.label}</TableHead>
            ))}
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((row, idx) => (
            <TableRow key={idx}>
              {columns.map((column) => (
                <TableCell key={column.key} className="align-top">
                  {Array.isArray(row[column.key])
                    ? (row[column.key] as unknown[]).join(", ")
                    : typeof row[column.key] === "boolean"
                      ? row[column.key]
                        ? "Ja"
                        : "Nein"
                      : String(row[column.key] ?? "—")}
                </TableCell>
              ))}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

function TinyBarChart({
  rows,
  dataKey,
  labelKey,
}: {
  rows: Array<Record<string, unknown>>;
  dataKey: string;
  labelKey: string;
}) {
  if (rows.length === 0) {
    return <div className="text-sm text-muted-foreground">Keine Chart-Daten.</div>;
  }
  return (
    <div className="h-56">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={rows}>
          <CartesianGrid strokeDasharray="3 3" vertical={false} />
          <XAxis dataKey={labelKey} tickLine={false} axisLine={false} fontSize={12} />
          <YAxis tickLine={false} axisLine={false} allowDecimals={false} fontSize={12} />
          <Bar dataKey={dataKey} fill="hsl(var(--primary))" radius={[6, 6, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

export function PdfScanDetailsDialog({
  open,
  onOpenChange,
  uid,
  projektId,
  runId,
  pdfDoc,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  uid: string;
  projektId: string;
  runId: string;
  pdfDoc: PdfDocRow | null;
}) {
  const [details, setDetails] = useState<PdfScanDetailsDoc | null>(null);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    if (!open || !uid || !projektId || !runId || !pdfDoc?.id) return;
    const ref = quellenFinderPdfScanDetailsDoc(firestoreClient, uid, projektId, runId, pdfDoc.id);
    return onSnapshot(
      ref,
      (snap) => {
        setLoaded(true);
        setDetails(snap.exists() ? (snap.data() as PdfScanDetailsDoc) : null);
      },
      () => {
        setLoaded(true);
        setDetails(null);
      }
    );
  }, [open, uid, projektId, runId, pdfDoc?.id]);

  const overview = useMemo(() => asRecord(details?.overview), [details?.overview]);
  const charts = useMemo(() => asRecord(details?.charts), [details?.charts]);
  const phaseC = useMemo(() => asRecord(details?.phaseC), [details?.phaseC]);
  const phaseE = useMemo(() => asRecord(details?.phaseE), [details?.phaseE]);
  const phaseF = useMemo(() => asRecord(details?.phaseF), [details?.phaseF]);
  const phaseG = useMemo(() => asRecord(details?.phaseG), [details?.phaseG]);

  const scoreBands = asRecordArray(charts["scoreBands"]);
  const sectionTypes = asRecordArray(charts["sectionTypes"]);
  const subpointCoverage = asRecordArray(charts["subpointCoverage"]);
  const headingsPreview = asRecordArray(phaseC["headingsPreview"]);
  const sectionPreview = asRecordArray(phaseC["sectionPreview"]);
  const topCandidates = asRecordArray(phaseE["topCandidates"]);
  const topReranked = asRecordArray(phaseF["topReranked"]);
  const finalSections = asRecordArray(phaseG["finalSectionsPreview"]);

  const title = pdfDoc?.docTitle || pdfDoc?.pdfLabel || "Pipeline Details";

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        showCloseButton={false}
        className="!flex !flex-col !gap-0 !w-[92vw] !max-w-[92vw] !h-[90vh] !max-h-[90vh] overflow-hidden !p-0"
      >
        <DialogHeader className="px-6 py-4 border-b border-border">
          <div className="flex items-start justify-between gap-4">
            <div className="min-w-0">
              <DialogTitle className="text-base font-semibold truncate">Pipeline Details — {title}</DialogTitle>
              <DialogDescription className="mt-1 text-xs text-muted-foreground">
                {pdfDoc?.pdfFilename || pdfDoc?.pdfLabel || "PDF"} • {formatNumber(pdfDoc?.topSectionScore, 1)} Score •{" "}
                {formatNumber(pdfDoc?.visibleSectionCount)} sichtbare Sections
              </DialogDescription>
            </div>
            <div className="shrink-0 flex items-center gap-3">
              {typeof pdfDoc?.docMatchProbability === "number" ? (
                <Badge variant="outline" className="tabular-nums">
                  p={formatNumber(pdfDoc.docMatchProbability, 3)}
                </Badge>
              ) : null}
              <DialogClose asChild>
                <button
                  type="button"
                  className="inline-flex h-8 w-8 items-center justify-center rounded-md border border-border bg-background text-muted-foreground transition-colors hover:bg-muted/40 hover:text-foreground"
                >
                  <X className="size-4" />
                </button>
              </DialogClose>
            </div>
          </div>
        </DialogHeader>

        <ScrollArea className="flex-1">
          <div className="px-6 py-4">
            {!loaded ? (
              <div className="space-y-4">
                <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-3">
                  {Array.from({ length: 8 }).map((_, idx) => (
                    <Card key={idx} className="p-4">
                      <Skeleton className="h-3 w-16" />
                      <Skeleton className="mt-3 h-7 w-24" />
                    </Card>
                  ))}
                </div>
                <Card className="p-4">
                  <Skeleton className="h-40 w-full" />
                </Card>
              </div>
            ) : !details ? (
              <div className="text-sm text-muted-foreground">Für dieses PDF sind noch keine Detaildaten vorhanden.</div>
            ) : (
              <Tabs defaultValue="overview" className="space-y-4">
                <TabsList className="h-auto flex-wrap">
                  <TabsTrigger value="overview">Überblick</TabsTrigger>
                  <TabsTrigger value="structure">Struktur</TabsTrigger>
                  <TabsTrigger value="retrieval">Retrieval</TabsTrigger>
                  <TabsTrigger value="final">Finale Scores</TabsTrigger>
                </TabsList>

                <TabsContent value="overview" className="space-y-4 mt-0">
                  <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-3">
                    <KpiCard label="Seiten" value={formatNumber(overview["pageCount"])} />
                    <KpiCard label="Sections gesamt" value={formatNumber(overview["sectionCount"])} />
                    <KpiCard label="Sichtbare Sections" value={formatNumber(overview["visibleSectionCount"])} />
                    <KpiCard label="Top Score" value={formatNumber(overview["topSectionScore"], 1)} />
                    <KpiCard label="Doc Match p" value={formatNumber(overview["docMatchProbability"], 3)} />
                    <KpiCard label="Akzeptierte Headings" value={formatNumber(overview["acceptedHeadingCount"])} />
                    <KpiCard label="Docling Status" value={String(overview["doclingStatus"] ?? "—")} />
                    <KpiCard label="Strategie" value={String(overview["strategy"] ?? "—")} />
                  </div>

                  <div className="grid grid-cols-1 xl:grid-cols-3 gap-4">
                    <Card className="p-4">
                      <div className="text-sm font-semibold">Score Bands</div>
                      <TinyBarChart rows={scoreBands} dataKey="count" labelKey="band" />
                    </Card>
                    <Card className="p-4">
                      <div className="text-sm font-semibold">Section Types</div>
                      <TinyBarChart rows={sectionTypes} dataKey="count" labelKey="type" />
                    </Card>
                    <Card className="p-4">
                      <div className="text-sm font-semibold">Subpoint Coverage</div>
                      <TinyBarChart rows={subpointCoverage} dataKey="count" labelKey="id" />
                    </Card>
                  </div>
                </TabsContent>

                <TabsContent value="structure" className="space-y-4 mt-0">
                  <Card className="p-4 space-y-3">
                    <div className="text-sm font-semibold">Accepted Headings</div>
                    <SimpleTable
                      rows={headingsPreview}
                      columns={[
                        { key: "page", label: "Seite" },
                        { key: "source", label: "Quelle" },
                        { key: "title", label: "Titel" },
                        { key: "anchorMethod", label: "Anchor" },
                      ]}
                    />
                  </Card>
                  <Card className="p-4 space-y-3">
                    <div className="text-sm font-semibold">Section Preview</div>
                    <SimpleTable
                      rows={sectionPreview}
                      columns={[
                        { key: "pages", label: "Seiten" },
                        { key: "type", label: "Typ" },
                        { key: "eligible", label: "Eligible" },
                        { key: "title", label: "Titel" },
                        { key: "flags", label: "Flags" },
                      ]}
                    />
                  </Card>
                </TabsContent>

                <TabsContent value="retrieval" className="space-y-4 mt-0">
                  <Card className="p-4 space-y-3">
                    <div className="text-sm font-semibold">Top Candidate Packs</div>
                    <SimpleTable
                      rows={topCandidates}
                      columns={[
                        { key: "rank", label: "#" },
                        { key: "pages", label: "Seiten" },
                        { key: "title", label: "Titel" },
                        { key: "fusedScore", label: "Fused" },
                        { key: "selectionScore", label: "Select" },
                        { key: "subpoints", label: "Subpoints" },
                      ]}
                    />
                  </Card>
                  <Card className="p-4 space-y-3">
                    <div className="text-sm font-semibold">Top Reranked Sections</div>
                    <SimpleTable
                      rows={topReranked}
                      columns={[
                        { key: "rank", label: "#" },
                        { key: "pages", label: "Seiten" },
                        { key: "title", label: "Titel" },
                        { key: "rerankScore", label: "Rerank" },
                        { key: "crossEncoderScore", label: "Cross" },
                        { key: "judgeScore", label: "Judge" },
                      ]}
                    />
                  </Card>
                </TabsContent>

                <TabsContent value="final" className="space-y-4 mt-0">
                  <Card className="p-4 space-y-3">
                    <div className="text-sm font-semibold">Finale Section Scores</div>
                    <SimpleTable
                      rows={finalSections}
                      columns={[
                        { key: "globalRank", label: "Global" },
                        { key: "docRank", label: "Doc" },
                        { key: "score0To100", label: "Score" },
                        { key: "scoreBand", label: "Band" },
                        { key: "pages", label: "Seiten" },
                        { key: "title", label: "Titel" },
                        { key: "coverage", label: "Coverage" },
                      ]}
                    />
                  </Card>
                </TabsContent>
              </Tabs>
            )}
          </div>
        </ScrollArea>
      </DialogContent>
    </Dialog>
  );
}
