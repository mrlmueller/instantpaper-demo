"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import Cookies from "js-cookie";
import { ArrowLeft, Download, Loader2, Search, Trash2, Upload } from "lucide-react";
import { toast } from "sonner";
import { addDoc, deleteDoc, limit, onSnapshot, orderBy, query, serverTimestamp, type CollectionReference } from "firebase/firestore";
import { deleteObject, getStorage, ref, uploadBytes } from "firebase/storage";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Separator } from "@/components/ui/separator";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

import { useAuth } from "@/app/components/providers/AuthProvider";
import { firebaseApp } from "@/app/lib/firebase/config";
import { firestoreClient } from "@/app/lib/firebase/firestoreClient";
import { downloadFileFromStorage } from "@/app/lib/firebase/storage";
import {
  projectPdfDoc,
  projectPdfsCol,
  projectResearchRunsCol,
  quellenFinderPdfStage2Col,
  quellenFinderPdfStage3Col,
  quellenFinderSourcesResultsCol,
} from "@/app/lib/firestore/refs";
import type {
  PdfScanStage2HitDoc,
  PdfScanStage3SectionDoc,
  ProjectPdfDoc,
  QuellenFinderRunDoc,
  QuellenFinderSourceResultDoc,
} from "@/app/lib/firestore/types";
import type { Kapitel } from "@/app/actions/kapitels";

const API_BASE_URL = process.env.NEXT_PUBLIC_FASTAPI_URL || "http://localhost:8000";

type WithId<T> = T & { id: string };
type RunRow = WithId<QuellenFinderRunDoc>;
type PdfRow = WithId<ProjectPdfDoc>;
type SourceRow = WithId<QuellenFinderSourceResultDoc>;
type Stage2Row = WithId<PdfScanStage2HitDoc>;
type Stage3Row = WithId<PdfScanStage3SectionDoc>;

type SortDir = "asc" | "desc";
type SourcesSortKey = "rank" | "score" | "year" | "citationCount";

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

function formatRunTime(value: unknown): string {
  const d = toDateOrNull(value);
  if (!d) return "";
  return d.toLocaleString("de-DE", {
    day: "2-digit",
    month: "2-digit",
    year: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
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

function normalizeFilename(name: string): string {
  const base = String(name || "").trim() || "document.pdf";
  const sanitized = base.replace(/[^a-zA-Z0-9._-]/g, "_");
  return sanitized.toLowerCase().endsWith(".pdf") ? sanitized : `${sanitized}.pdf`;
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
  const uploadInputRef = useRef<HTMLInputElement | null>(null);

  const [kapitelQuery, setKapitelQuery] = useState("");
  const [selectedKapitelIds, setSelectedKapitelIds] = useState<string[]>([]);

  const [runs, setRuns] = useState<RunRow[]>([]);
  const [activeSourcesRunId, setActiveSourcesRunId] = useState<string | null>(null);
  const [activePdfRunId, setActivePdfRunId] = useState<string | null>(null);

  const [pdfs, setPdfs] = useState<PdfRow[]>([]);
  const [selectedPdfIds, setSelectedPdfIds] = useState<Set<string>>(new Set());
  const [uploadingPdfs, setUploadingPdfs] = useState(false);

  const [blueprintModel, setBlueprintModel] = useState<"gpt-5-nano" | "gpt-5-mini" | "gpt-5.2">("gpt-5-mini");

  const [sources, setSources] = useState<SourceRow[]>([]);
  const [sourcesQuery, setSourcesQuery] = useState("");
  const [sourcesSortKey, setSourcesSortKey] = useState<SourcesSortKey>("rank");
  const [sourcesSortDir, setSourcesSortDir] = useState<SortDir>("asc");
  const [expandedSourceIds, setExpandedSourceIds] = useState<Set<string>>(new Set());

  const [stage2, setStage2] = useState<Stage2Row[]>([]);
  const [stage3, setStage3] = useState<Stage3Row[]>([]);
  const [pdfStageTab, setPdfStageTab] = useState<"stage2" | "stage3">("stage3");

  const kapitels = useMemo(() => initialKapitels ?? [], [initialKapitels]);

  const filteredKapitels = useMemo(() => {
    const q = kapitelQuery.trim().toLowerCase();
    if (!q) return kapitels;
    return kapitels.filter((k) => {
      const title = String(k.title || "").toLowerCase();
      const nummer = String(k.nummer || "").toLowerCase();
      return title.includes(q) || nummer.includes(q);
    });
  }, [kapitels, kapitelQuery]);

  const selectedKapitel = useMemo(() => {
    if (selectedKapitelIds.length !== 1) return null;
    return kapitels.find((k) => k.id === selectedKapitelIds[0]) ?? null;
  }, [kapitels, selectedKapitelIds]);

  const sourcesRuns = useMemo(() => runs.filter((r) => r.kind === "sources_search"), [runs]);
  const pdfRuns = useMemo(() => runs.filter((r) => r.kind === "pdf_scan"), [runs]);

  const activeSourcesRun = useMemo(() => {
    if (!activeSourcesRunId) return sourcesRuns[0] ?? null;
    return sourcesRuns.find((r) => r.id === activeSourcesRunId) ?? sourcesRuns[0] ?? null;
  }, [sourcesRuns, activeSourcesRunId]);

  const activePdfRun = useMemo(() => {
    if (!activePdfRunId) return pdfRuns[0] ?? null;
    return pdfRuns.find((r) => r.id === activePdfRunId) ?? pdfRuns[0] ?? null;
  }, [pdfRuns, activePdfRunId]);

  useEffect(() => {
    if (!activeSourcesRunId && sourcesRuns.length) setActiveSourcesRunId(sourcesRuns[0].id);
    if (activeSourcesRunId && !sourcesRuns.some((r) => r.id === activeSourcesRunId)) {
      setActiveSourcesRunId(sourcesRuns[0]?.id ?? null);
    }
  }, [sourcesRuns, activeSourcesRunId]);

  useEffect(() => {
    if (!activePdfRunId && pdfRuns.length) setActivePdfRunId(pdfRuns[0].id);
    if (activePdfRunId && !pdfRuns.some((r) => r.id === activePdfRunId)) {
      setActivePdfRunId(pdfRuns[0]?.id ?? null);
    }
  }, [pdfRuns, activePdfRunId]);

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
    if (!user?.uid || !projektId) return;
    const q = query(projectPdfsCol(firestoreClient, user.uid, projektId), orderBy("createdAt", "desc"), limit(200));
    return onSnapshot(
      q,
      (snap) => {
        const next = snap.docs.map((d) => ({ id: d.id, ...(d.data() as ProjectPdfDoc) }));
        setPdfs(next);
      },
      (err) => {
        console.error("Failed to load project pdfs:", err);
        setPdfs([]);
      }
    );
  }, [user?.uid, projektId]);

  useEffect(() => {
    if (!user?.uid || !projektId || !activeSourcesRun?.id) {
      setSources([]);
      return;
    }
    const col = quellenFinderSourcesResultsCol(firestoreClient, user.uid, projektId, activeSourcesRun.id);
    const q = query(col, limit(60));
    return onSnapshot(
      q,
      (snap) => {
        const next = snap.docs.map((d) => ({ id: d.id, ...(d.data() as QuellenFinderSourceResultDoc) }));
        setSources(next);
      },
      (err) => {
        console.error("Failed to load sourcesResults:", err);
        setSources([]);
      }
    );
  }, [user?.uid, projektId, activeSourcesRun?.id]);

  useEffect(() => {
    if (!user?.uid || !projektId || !activePdfRun?.id) {
      setStage2([]);
      setStage3([]);
      return;
    }
    const stage2Col = quellenFinderPdfStage2Col(firestoreClient, user.uid, projektId, activePdfRun.id);
    const stage3Col = quellenFinderPdfStage3Col(firestoreClient, user.uid, projektId, activePdfRun.id);
    const unsub2 = onSnapshot(
      query(stage2Col, limit(400)),
      (snap) => setStage2(snap.docs.map((d) => ({ id: d.id, ...(d.data() as PdfScanStage2HitDoc) }))),
      (err) => {
        console.error("Failed to load pdfStage2:", err);
        setStage2([]);
      }
    );
    const unsub3 = onSnapshot(
      query(stage3Col, limit(200)),
      (snap) => setStage3(snap.docs.map((d) => ({ id: d.id, ...(d.data() as PdfScanStage3SectionDoc) }))),
      (err) => {
        console.error("Failed to load pdfStage3:", err);
        setStage3([]);
      }
    );
    return () => {
      unsub2();
      unsub3();
    };
  }, [user?.uid, projektId, activePdfRun?.id]);

  const sourcesFiltered = useMemo(() => {
    const q = sourcesQuery.trim().toLowerCase();
    let rows = sources;
    if (q) {
      rows = rows.filter((r) => {
        const title = String(r.title || "").toLowerCase();
        const authors = Array.isArray(r.authors) ? r.authors.join("; ").toLowerCase() : "";
        const venue = String(r.venue || "").toLowerCase();
        return title.includes(q) || authors.includes(q) || venue.includes(q);
      });
    }

    const dir = sourcesSortDir === "asc" ? 1 : -1;
    const byNum = (v: unknown) => (typeof v === "number" && Number.isFinite(v) ? v : -Infinity);
    const byRank = (v: unknown) => (typeof v === "number" && Number.isFinite(v) ? v : 9999);

    return [...rows].sort((a, b) => {
      if (sourcesSortKey === "rank") return dir * (byRank(a.rank) - byRank(b.rank));
      if (sourcesSortKey === "year") return dir * (byNum(a.year) - byNum(b.year));
      if (sourcesSortKey === "citationCount") return dir * (byNum(a.citationCount) - byNum(b.citationCount));
      return dir * (byNum(a.score) - byNum(b.score));
    });
  }, [sources, sourcesQuery, sourcesSortDir, sourcesSortKey]);

  const canRunSources = Boolean(user?.uid && projektId && selectedKapitelIds.length === 1);
  const canRunPdfScan = Boolean(user?.uid && projektId && selectedKapitelIds.length === 1 && selectedPdfIds.size > 0);

  const runningSources = activeSourcesRun?.status === "running" || activeSourcesRun?.status === "queued";
  const runningPdfScan = activePdfRun?.status === "running" || activePdfRun?.status === "queued";

  const toggleKapitel = (id: string) => {
    setSelectedKapitelIds((prev) => {
      const has = prev.includes(id);
      if (has) return prev.filter((x) => x !== id);
      return [...prev, id];
    });
  };

  const togglePdf = (id: string) => {
    setSelectedPdfIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const handleUploadClick = () => uploadInputRef.current?.click();

  const handleUploadPdfs = async (files: FileList | null) => {
    if (!files || files.length === 0) return;
    if (!user?.uid) return;

    setUploadingPdfs(true);
    const storage = getStorage(firebaseApp);
    const col = projectPdfsCol(firestoreClient, user.uid, projektId) as unknown as CollectionReference<Record<string, unknown>>;

    try {
      for (const file of Array.from(files)) {
        const sizeOk = file.size < 60 * 1024 * 1024;
        const isPdfName = String(file.name || "").toLowerCase().endsWith(".pdf");
        if (!sizeOk) {
          toast.error("PDF zu groß", { description: `${file.name} ist größer als 60MB.` });
          continue;
        }
        if (!isPdfName) {
          toast.error("Nur PDFs erlaubt", { description: `${file.name} hat keine .pdf Endung.` });
          continue;
        }

        const timestamp = Date.now();
        const storageName = `${timestamp}_${normalizeFilename(file.name)}`;
        const storagePath = `users/${user.uid}/projects/${projektId}/pdfs/${storageName}`;

        const storageRef = ref(storage, storagePath);
        await uploadBytes(storageRef, file, { contentType: "application/pdf" });

        await addDoc(col, {
          filename: String(file.name || "document.pdf"),
          storagePath,
          size: Number(file.size || 0),
          contentType: "application/pdf",
          createdAt: serverTimestamp(),
          updatedAt: serverTimestamp(),
        });
      }

      toast.success("PDFs hochgeladen");
    } catch (err: unknown) {
      console.error("PDF upload failed:", err);
      toast.error("PDF Upload fehlgeschlagen", { description: err instanceof Error ? err.message : "Unbekannter Fehler" });
    } finally {
      setUploadingPdfs(false);
      if (uploadInputRef.current) uploadInputRef.current.value = "";
    }
  };

  const handleDeletePdf = async (pdf: PdfRow) => {
    if (!user?.uid) return;
    const ok = window.confirm(`PDF wirklich löschen?\n\n${pdf.filename}`);
    if (!ok) return;

    const storage = getStorage(firebaseApp);
    try {
      const storagePath = String(pdf.storagePath || "");
      if (storagePath) {
        await deleteObject(ref(storage, storagePath)).catch((e) => {
          const errCode =
            typeof e === "object" && e && "code" in e && typeof (e as { code?: unknown }).code === "string"
              ? String((e as { code?: unknown }).code)
              : null;
          if (errCode !== "storage/object-not-found") throw e;
        });
      }
      await deleteDoc(projectPdfDoc(firestoreClient, user.uid, projektId, pdf.id));
      setSelectedPdfIds((prev) => {
        const next = new Set(prev);
        next.delete(pdf.id);
        return next;
      });
      toast.success("PDF gelöscht");
    } catch (err: unknown) {
      console.error("Delete PDF failed:", err);
      toast.error("PDF löschen fehlgeschlagen", { description: err instanceof Error ? err.message : "Unbekannter Fehler" });
    }
  };

  const startSourcesSearch = async () => {
    if (!canRunSources) {
      toast.error("Bitte genau ein Kapitel auswählen.");
      return;
    }
    const token = Cookies.get("__session");
    if (!token) {
      toast.error("Nicht eingeloggt", { description: "Session Token fehlt." });
      return;
    }
    const kapitelId = selectedKapitelIds[0];

    const res = await fetch(`${API_BASE_URL}/api/quellen-finder/sources-search`, {
      method: "POST",
      headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
      body: JSON.stringify({ projekt_id: projektId, kapitel_id: kapitelId, blueprint_model: blueprintModel }),
    });

    if (!res.ok) {
      const detail = await readFastApiError(res);
      if (res.status === 402) {
        toast.error("Nicht genügend Credits", { description: detail });
        return;
      }
      toast.error("Paper Search fehlgeschlagen", { description: detail });
      return;
    }

    const data = (await res.json().catch(() => ({}))) as Record<string, unknown>;
    const runId = typeof data.run_id === "string" ? String(data.run_id) : "";
    if (runId) setActiveSourcesRunId(runId);
    toast.success("Paper Search gestartet", { description: runId ? `Run: ${runId}` : undefined });
  };

  const startPdfScan = async () => {
    if (!canRunPdfScan) {
      toast.error("Bitte genau ein Kapitel auswählen und mindestens ein PDF markieren.");
      return;
    }
    const token = Cookies.get("__session");
    if (!token) {
      toast.error("Nicht eingeloggt", { description: "Session Token fehlt." });
      return;
    }
    const kapitelId = selectedKapitelIds[0];
    const pdfIds = Array.from(selectedPdfIds);

    const res = await fetch(`${API_BASE_URL}/api/quellen-finder/pdf-scan`, {
      method: "POST",
      headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
      body: JSON.stringify({ projekt_id: projektId, kapitel_id: kapitelId, pdf_ids: pdfIds, preprocess: true }),
    });

    if (!res.ok) {
      const detail = await readFastApiError(res);
      if (res.status === 402) {
        toast.error("Nicht genügend Credits", { description: detail });
        return;
      }
      toast.error("PDF Scan fehlgeschlagen", { description: detail });
      return;
    }

    const data = (await res.json().catch(() => ({}))) as Record<string, unknown>;
    const runId = typeof data.run_id === "string" ? String(data.run_id) : "";
    if (runId) setActivePdfRunId(runId);
    toast.success("PDF Scan gestartet", { description: runId ? `Run: ${runId}` : undefined });
  };

  return (
    <div className="min-h-screen bg-background">
      <div className="border-b border-border px-6 py-4 flex items-center gap-4">
        <Button asChild variant="ghost" size="icon">
          <Link href="/dashboard" aria-label="Back to dashboard">
            <ArrowLeft className="h-5 w-5" />
          </Link>
        </Button>
        <div className="min-w-0">
          <div className="text-lg font-semibold truncate">Quellen-Finder</div>
          <div className="text-sm text-muted-foreground truncate">Projekt: {projektName}</div>
        </div>
      </div>

      <div className="px-6 py-4">
        <div className="grid grid-cols-1 lg:grid-cols-[320px_1fr] gap-4 items-start">
          <Card className="p-4">
            <div className="flex items-center gap-2 mb-3">
              <Search className="h-4 w-4 text-muted-foreground" />
              <Input value={kapitelQuery} onChange={(e) => setKapitelQuery(e.target.value)} placeholder="Kapitel suchen (Nr/Titel)" />
            </div>
            <div className="text-xs text-muted-foreground mb-3">
              Ausgewählt: <span className="font-medium">{selectedKapitelIds.length}</span> (derzeit nur 1 Kapitel pro Run)
            </div>
            <div className="space-y-2 max-h-[65vh] overflow-auto pr-1">
              {filteredKapitels.map((k) => {
                const checked = selectedKapitelIds.includes(k.id);
                return (
                  <div
                    key={k.id}
                    onClick={() => toggleKapitel(k.id)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault();
                        toggleKapitel(k.id);
                      }
                    }}
                    role="button"
                    tabIndex={0}
                    className="w-full text-left rounded-md border border-border hover:bg-muted/40 transition-colors px-3 py-2"
                  >
                    <div className="flex items-start gap-2">
                      <div className="pt-0.5">
                        <Checkbox
                          checked={checked}
                          onClick={(e) => e.stopPropagation()}
                          onCheckedChange={() => toggleKapitel(k.id)}
                        />
                      </div>
                      <div className="min-w-0">
                        <div className="text-sm font-medium truncate">
                          {k.nummer} — {k.title}
                        </div>
                        <div className="text-xs text-muted-foreground line-clamp-2">{k.thema || ""}</div>
                      </div>
                    </div>
                  </div>
                );
              })}
              {filteredKapitels.length === 0 ? <div className="text-sm text-muted-foreground">Keine Kapitel gefunden.</div> : null}
            </div>
          </Card>

          <div className="space-y-4">
            <Card className="p-4">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="text-sm font-semibold">Aktives Kapitel</div>
                  <div className="text-xs text-muted-foreground">Kapitelüberschrift + Thema &amp; Anweisungen werden verwendet.</div>
                </div>
                {selectedKapitel ? <Badge variant="outline">{selectedKapitel.nummer}</Badge> : null}
              </div>
              <Separator className="my-3" />
              {selectedKapitel ? (
                <div className="space-y-2">
                  <div className="text-sm font-medium">{selectedKapitel.title}</div>
                  <div className="text-xs text-muted-foreground whitespace-pre-wrap">{selectedKapitel.thema || ""}</div>
                </div>
              ) : (
                <div className="text-sm text-muted-foreground">Bitte genau ein Kapitel auswählen.</div>
              )}
            </Card>

            <Card className="p-4">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="text-sm font-semibold">1) Paper Search (Top 30)</div>
                  <div className="text-xs text-muted-foreground">Speichert nur die finalen Top-30 Ergebnisse (Firestore).</div>
                </div>
                <div className="flex items-center gap-2">
                  <Select
                    value={blueprintModel}
                    onValueChange={(v) => {
                      if (v === "gpt-5-nano" || v === "gpt-5-mini" || v === "gpt-5.2") setBlueprintModel(v);
                    }}
                  >
                    <SelectTrigger className="w-[140px] h-8">
                      <SelectValue placeholder="Model" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="gpt-5-nano">gpt-5-nano</SelectItem>
                      <SelectItem value="gpt-5-mini">gpt-5-mini</SelectItem>
                      <SelectItem value="gpt-5.2">gpt-5.2</SelectItem>
                    </SelectContent>
                  </Select>
                  <Button size="sm" onClick={startSourcesSearch} disabled={!canRunSources || runningSources}>
                    {runningSources ? <Loader2 className="h-4 w-4 animate-spin mr-2" /> : null}
                    Search Papers
                  </Button>
                </div>
              </div>

              <div className="mt-3 flex items-center gap-2 flex-wrap">
                <div className="text-xs text-muted-foreground">Run:</div>
                <Select value={activeSourcesRun?.id || ""} onValueChange={(v) => setActiveSourcesRunId(v || null)} disabled={sourcesRuns.length === 0}>
                  <SelectTrigger className="w-[320px] h-8">
                    <SelectValue placeholder="(keine Runs)" />
                  </SelectTrigger>
                  <SelectContent>
                    {sourcesRuns.map((r) => (
                      <SelectItem key={r.id} value={r.id}>
                        {formatRunTime(r.createdAt) || r.id} — {r.status}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                {activeSourcesRun ? (
                  <>
                    <Badge variant={statusBadgeVariant(activeSourcesRun.status)}>{activeSourcesRun.status}</Badge>
                    {activeSourcesRun.hadPartialFailures ? <Badge variant="outline">partial</Badge> : null}
                    <span className="text-xs text-muted-foreground">{progressLabel(activeSourcesRun)}</span>
                  </>
                ) : null}
              </div>

              <Separator className="my-3" />

              <div className="flex items-center gap-2 flex-wrap">
                <Input value={sourcesQuery} onChange={(e) => setSourcesQuery(e.target.value)} placeholder="Filter: Titel, Autoren, Venue…" className="h-8 max-w-[320px]" />
                <Select
                  value={sourcesSortKey}
                  onValueChange={(v) => {
                    if (v === "rank" || v === "score" || v === "year" || v === "citationCount") setSourcesSortKey(v);
                  }}
                >
                  <SelectTrigger className="w-[160px] h-8">
                    <SelectValue placeholder="Sort" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="rank">Rank</SelectItem>
                    <SelectItem value="score">Score</SelectItem>
                    <SelectItem value="year">Year</SelectItem>
                    <SelectItem value="citationCount">Citations</SelectItem>
                  </SelectContent>
                </Select>
                <Select
                  value={sourcesSortDir}
                  onValueChange={(v) => {
                    if (v === "asc" || v === "desc") setSourcesSortDir(v);
                  }}
                >
                  <SelectTrigger className="w-[120px] h-8">
                    <SelectValue placeholder="Dir" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="asc">Asc</SelectItem>
                    <SelectItem value="desc">Desc</SelectItem>
                  </SelectContent>
                </Select>
                <div className="text-xs text-muted-foreground">
                  Rows: <span className="font-medium">{sourcesFiltered.length}</span>
                </div>
              </div>

              <div className="mt-3 overflow-auto border border-border rounded-md">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead className="w-[64px]">#</TableHead>
                      <TableHead>Title</TableHead>
                      <TableHead className="w-[80px]">Year</TableHead>
                      <TableHead className="w-[90px]">Cites</TableHead>
                      <TableHead className="w-[90px]">Score</TableHead>
                      <TableHead className="w-[90px]">Raw</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {sourcesFiltered.map((r) => {
                      const expanded = expandedSourceIds.has(r.id);
                      return (
                        <>
                          <TableRow key={r.id}>
                            <TableCell className="tabular-nums">{r.rank ?? r.id}</TableCell>
                            <TableCell className="min-w-[360px]">
                              <div className="font-medium">{r.title || "(untitled)"}</div>
                              <div className="text-xs text-muted-foreground line-clamp-1">
                                {(r.authors || []).slice(0, 6).join(", ")}
                                {r.venue ? ` • ${r.venue}` : ""}
                                {r.doi ? ` • DOI: ${r.doi}` : ""}
                              </div>
                            </TableCell>
                            <TableCell className="tabular-nums">{r.year ?? ""}</TableCell>
                            <TableCell className="tabular-nums">{r.citationCount ?? ""}</TableCell>
                            <TableCell className="tabular-nums">{typeof r.score === "number" ? r.score.toFixed(3) : ""}</TableCell>
                            <TableCell>
                              <Button
                                size="sm"
                                variant="outline"
                                onClick={() =>
                                  setExpandedSourceIds((prev) => {
                                    const next = new Set(prev);
                                    if (next.has(r.id)) next.delete(r.id);
                                    else next.add(r.id);
                                    return next;
                                  })
                                }
                              >
                                {expanded ? "Hide" : "Show"}
                              </Button>
                            </TableCell>
                          </TableRow>
                          {expanded ? (
                            <TableRow key={`${r.id}__raw`}>
                              <TableCell colSpan={6} className="bg-muted/30">
                                <pre className="text-xs overflow-auto max-h-[320px] whitespace-pre-wrap">{JSON.stringify(r.raw ?? {}, null, 2)}</pre>
                              </TableCell>
                            </TableRow>
                          ) : null}
                        </>
                      );
                    })}
                    {sourcesFiltered.length === 0 ? (
                      <TableRow>
                        <TableCell colSpan={6} className="text-sm text-muted-foreground">
                          Keine Ergebnisse.
                        </TableCell>
                      </TableRow>
                    ) : null}
                  </TableBody>
                </Table>
              </div>
            </Card>

            <Card className="p-4">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="text-sm font-semibold">2) PDF Library + Scan</div>
                  <div className="text-xs text-muted-foreground">Upload in Firebase Storage, danach Download durch Backend. Stage 2 + Stage 3 werden gespeichert.</div>
                </div>
                <div className="flex items-center gap-2">
                  <input ref={uploadInputRef} type="file" accept="application/pdf" multiple className="hidden" onChange={(e) => void handleUploadPdfs(e.target.files)} />
                  <Button size="sm" variant="outline" onClick={handleUploadClick} disabled={!user?.uid || uploadingPdfs}>
                    {uploadingPdfs ? <Loader2 className="h-4 w-4 animate-spin mr-2" /> : <Upload className="h-4 w-4 mr-2" />}
                    Upload PDFs
                  </Button>
                  <Button size="sm" onClick={startPdfScan} disabled={!canRunPdfScan || runningPdfScan}>
                    {runningPdfScan ? <Loader2 className="h-4 w-4 animate-spin mr-2" /> : null}
                    Scan PDFs
                  </Button>
                </div>
              </div>

              <div className="mt-3 grid grid-cols-1 xl:grid-cols-[420px_1fr] gap-4 items-start">
                <div>
                  <div className="text-xs text-muted-foreground mb-2">
                    Ausgewählt: <span className="font-medium">{selectedPdfIds.size}</span> PDFs
                  </div>
                  <div className="space-y-2 max-h-[320px] overflow-auto pr-1">
                    {pdfs.map((p) => {
                      const checked = selectedPdfIds.has(p.id);
                      return (
                        <div key={p.id} className="flex items-start gap-2 rounded-md border border-border px-3 py-2">
                          <div className="pt-0.5">
                            <Checkbox checked={checked} onCheckedChange={() => togglePdf(p.id)} />
                          </div>
                          <div className="min-w-0 flex-1">
                            <div className="text-sm font-medium truncate">{p.filename}</div>
                            <div className="text-xs text-muted-foreground truncate">{p.storagePath}</div>
                            <div className="text-xs text-muted-foreground tabular-nums">{(Number(p.size || 0) / (1024 * 1024)).toFixed(1)} MB</div>
                          </div>
                          <div className="flex items-center gap-1">
                            <Button size="icon" variant="ghost" onClick={() => void downloadFileFromStorage(String(p.storagePath || ""), String(p.filename || "document.pdf"))} title="Download">
                              <Download className="h-4 w-4" />
                            </Button>
                            <Button size="icon" variant="ghost" onClick={() => void handleDeletePdf(p)} title="Delete">
                              <Trash2 className="h-4 w-4 text-destructive" />
                            </Button>
                          </div>
                        </div>
                      );
                    })}
                    {pdfs.length === 0 ? <div className="text-sm text-muted-foreground">Noch keine PDFs hochgeladen.</div> : null}
                  </div>

                  <div className="mt-3 flex items-center gap-2 flex-wrap">
                    <div className="text-xs text-muted-foreground">Run:</div>
                    <Select value={activePdfRun?.id || ""} onValueChange={(v) => setActivePdfRunId(v || null)} disabled={pdfRuns.length === 0}>
                      <SelectTrigger className="w-[320px] h-8">
                        <SelectValue placeholder="(keine Runs)" />
                      </SelectTrigger>
                      <SelectContent>
                        {pdfRuns.map((r) => (
                          <SelectItem key={r.id} value={r.id}>
                            {formatRunTime(r.createdAt) || r.id} — {r.status}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                    {activePdfRun ? (
                      <>
                        <Badge variant={statusBadgeVariant(activePdfRun.status)}>{activePdfRun.status}</Badge>
                        {activePdfRun.hadPartialFailures ? <Badge variant="outline">partial</Badge> : null}
                        <span className="text-xs text-muted-foreground">{progressLabel(activePdfRun)}</span>
                      </>
                    ) : null}
                  </div>
                  {activePdfRun ? (
                    <div className="mt-2 text-xs text-muted-foreground">
                      Stage2: {Number(activePdfRun.stage2Count ?? 0)} • Stage3: {Number(activePdfRun.stage3Count ?? 0)} • Run: <span className="font-mono">{activePdfRun.id}</span>
                    </div>
                  ) : null}
                </div>

                <div>
                  <Tabs
                    value={pdfStageTab}
                    onValueChange={(v) => {
                      if (v === "stage2" || v === "stage3") setPdfStageTab(v);
                    }}
                  >
                    <TabsList>
                      <TabsTrigger value="stage3">Stage 3 (Sections)</TabsTrigger>
                      <TabsTrigger value="stage2">Stage 2 (Hits)</TabsTrigger>
                    </TabsList>

                    <TabsContent value="stage3" className="mt-3">
                      <div className="overflow-auto border border-border rounded-md">
                        <Table>
                          <TableHeader>
                            <TableRow>
                              <TableHead className="w-[220px]">PDF</TableHead>
                              <TableHead>Heading</TableHead>
                              <TableHead className="w-[90px]">Score</TableHead>
                              <TableHead className="w-[280px]">Anchor</TableHead>
                              <TableHead className="w-[220px]">Subpoints</TableHead>
                            </TableRow>
                          </TableHeader>
                          <TableBody>
                            {stage3.map((r) => (
                              <TableRow key={r.id}>
                                <TableCell className="min-w-[220px]">{r.pdfLabel}</TableCell>
                                <TableCell className="min-w-[260px]">{r.heading || ""}</TableCell>
                                <TableCell className="tabular-nums">{r.score ?? ""}</TableCell>
                                <TableCell className="min-w-[280px]">
                                  <div className="text-xs whitespace-pre-wrap line-clamp-3">{r.anchor || ""}</div>
                                </TableCell>
                                <TableCell className="min-w-[220px]">
                                  <div className="text-xs text-muted-foreground whitespace-pre-wrap line-clamp-3">{(r.coveredSubpoints || []).join(", ")}</div>
                                </TableCell>
                              </TableRow>
                            ))}
                            {stage3.length === 0 ? (
                              <TableRow>
                                <TableCell colSpan={5} className="text-sm text-muted-foreground">
                                  Keine Stage-3 Ergebnisse.
                                </TableCell>
                              </TableRow>
                            ) : null}
                          </TableBody>
                        </Table>
                      </div>
                    </TabsContent>

                    <TabsContent value="stage2" className="mt-3">
                      <div className="overflow-auto border border-border rounded-md">
                        <Table>
                          <TableHeader>
                            <TableRow>
                              <TableHead className="w-[220px]">PDF</TableHead>
                              <TableHead className="w-[90px]">Score</TableHead>
                              <TableHead className="w-[140px]">Subpoint</TableHead>
                              <TableHead className="w-[110px]">Tier</TableHead>
                              <TableHead>Anchor</TableHead>
                            </TableRow>
                          </TableHeader>
                          <TableBody>
                            {stage2.map((r) => (
                                <TableRow key={r.id}>
                                  <TableCell className="min-w-[220px]">{r.pdfLabel}</TableCell>
                                  <TableCell className="tabular-nums">{r.score ?? ""}</TableCell>
                                <TableCell className="min-w-[140px]">{r.subpoint || ""}</TableCell>
                                <TableCell className="min-w-[110px]">{r.tier || ""}</TableCell>
                                <TableCell className="min-w-[360px]">
                                  <div className="text-xs whitespace-pre-wrap line-clamp-3">{r.anchor || ""}</div>
                                  {r.locatorHint ? <div className="text-xs text-muted-foreground line-clamp-2 mt-1">Locator: {r.locatorHint}</div> : null}
                                </TableCell>
                              </TableRow>
                            ))}
                            {stage2.length === 0 ? (
                              <TableRow>
                                <TableCell colSpan={5} className="text-sm text-muted-foreground">
                                  Keine Stage-2 Ergebnisse.
                                </TableCell>
                              </TableRow>
                            ) : null}
                          </TableBody>
                        </Table>
                      </div>
                    </TabsContent>
                  </Tabs>
                </div>
              </div>
            </Card>
          </div>
        </div>
      </div>
    </div>
  );
}
