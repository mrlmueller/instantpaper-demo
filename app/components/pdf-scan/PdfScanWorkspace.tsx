"use client";

import { memo, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import Cookies from "js-cookie";
import { AlertTriangle, ArrowLeft, Check, ExternalLink, FileUp, Loader2, Play, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { Timestamp, addDoc, deleteDoc, doc, limit, onSnapshot, orderBy, query } from "firebase/firestore";
import { deleteObject, getDownloadURL, getStorage, ref as storageRef, uploadBytes } from "firebase/storage";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Select, SelectContent, SelectItem, SelectTrigger } from "@/components/ui/select";
import { Separator } from "@/components/ui/separator";
import { Switch } from "@/components/ui/switch";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";

import { useAuth } from "@/app/components/providers/AuthProvider";
import { ViewportWarning } from "@/app/components/viewport-warning";
import { PdfExtractDialog, type PdfExtractRequest } from "@/app/components/quellen-finder/PdfExtractDialog";
import { firebaseApp } from "@/app/lib/firebase/config";
import { firestoreClient } from "@/app/lib/firebase/firestoreClient";
import {
  projectPdfsCol,
  projectResearchRunsCol,
  quellenFinderPdfStage2Col,
  quellenFinderPdfStage3Col,
} from "@/app/lib/firestore/refs";
import type {
  PdfScanStage2HitDoc,
  PdfScanStage3SectionDoc,
  ProjectPdfDoc,
  QuellenFinderRunDoc,
} from "@/app/lib/firestore/types";
import type { Kapitel } from "@/app/actions/kapitels";

const API_BASE_URL = process.env.NEXT_PUBLIC_FASTAPI_URL || "http://localhost:8000";

type WithId<T> = T & { id: string };
type WithDocId<T> = T & { docId: string };

type PdfRow = WithId<ProjectPdfDoc>;
type RunRow = WithId<QuellenFinderRunDoc>;
type Stage2Row = WithDocId<PdfScanStage2HitDoc>;
type Stage3Row = WithDocId<PdfScanStage3SectionDoc>;

type ToDateLike = { toDate: () => Date };

function hasToDate(value: unknown): value is ToDateLike {
  if (typeof value !== "object" || value === null) return false;
  const rec = value as Record<string, unknown>;
  return typeof rec.toDate === "function";
}

function toDateOrNull(value: unknown): Date | null {
  if (!value) return null;
  if (value instanceof Date) return value;
  if (hasToDate(value)) return value.toDate();
  return null;
}

function formatIntDe(value: unknown): string {
  if (typeof value !== "number" || !Number.isFinite(value)) return "";
  return Math.trunc(value).toLocaleString("de-DE");
}

function formatTimeHm(value: unknown): string {
  const d = toDateOrNull(value);
  if (!d) return "";
  return d.toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit" });
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

function formatBytes(bytes: unknown): string {
  const n = typeof bytes === "number" && Number.isFinite(bytes) ? bytes : 0;
  const abs = Math.max(0, n);
  if (abs < 1024) return `${Math.round(abs)} B`;
  const kb = abs / 1024;
  if (kb < 1024) return `${kb.toFixed(kb < 10 ? 1 : 0)} KB`;
  const mb = kb / 1024;
  if (mb < 1024) return `${mb.toFixed(mb < 10 ? 1 : 0)} MB`;
  const gb = mb / 1024;
  return `${gb.toFixed(gb < 10 ? 1 : 0)} GB`;
}

function kapitelDepth(nummer: unknown): number {
  const s = String(nummer || "").trim();
  if (!s) return 0;
  return Math.max(0, (s.match(/\./g) || []).length);
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

const PDF_SCAN_PIPELINE_STEPS: { key: string; label: string }[] = [
  { key: "download_pdfs", label: "Download PDFs" },
  { key: "stage0_vector_store", label: "Vector Store" },
  { key: "stage1_preprocess", label: "Preprocess" },
  { key: "stage2_extract", label: "Extractor (Stage 2)" },
  { key: "stage3_curate", label: "Curation (Stage 3)" },
  { key: "write_results", label: "Save results" },
];

const StatusPill = memo(function StatusPill({ status }: { status: string }) {
  const variant =
    status === "success"
      ? "default"
      : status === "running"
        ? "secondary"
        : status === "error"
          ? "destructive"
          : "outline";
  const label =
    status === "queued"
      ? "Queued"
      : status === "running"
        ? "Running"
        : status === "success"
          ? "Success"
          : status === "cancelled"
            ? "Cancelled"
            : status === "error"
              ? "Error"
              : status || "—";

  return (
    <Badge variant={variant} className="tabular-nums">
      {label}
    </Badge>
  );
});

export function PdfScanWorkspace({
  initialKapitels,
  projektId,
  projektName,
}: {
  initialKapitels: Kapitel[];
  projektId: string;
  projektName: string;
}) {
  const { user } = useAuth();

  const kapitels = useMemo(() => initialKapitels ?? [], [initialKapitels]);
  const [selectedKapitelId, setSelectedKapitelId] = useState<string | null>(null);

  const selectedKapitel = useMemo(() => {
    if (!selectedKapitelId) return null;
    return kapitels.find((k) => k.id === selectedKapitelId) ?? null;
  }, [kapitels, selectedKapitelId]);

  const [pdfs, setPdfs] = useState<PdfRow[]>([]);
  const [selectedPdfIds, setSelectedPdfIds] = useState<string[]>([]);
  const selectedPdfIdSet = useMemo(() => new Set(selectedPdfIds), [selectedPdfIds]);

  const [uploading, setUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState<{ done: number; total: number } | null>(null);

  const [preprocessEnabled, setPreprocessEnabled] = useState(true);

  const [runs, setRuns] = useState<RunRow[]>([]);
  const [activeRunId, setActiveRunId] = useState<string | null>(null);

  const pdfScanRuns = useMemo(() => runs.filter((r) => r.kind === "pdf_scan"), [runs]);

  const activeRun = useMemo(() => {
    if (activeRunId) {
      const found = pdfScanRuns.find((r) => r.id === activeRunId);
      if (found) return found;
    }
    if (selectedKapitelId) {
      return pdfScanRuns.find((r) => Array.isArray(r.kapitelIds) && r.kapitelIds.includes(selectedKapitelId)) ?? null;
    }
    return pdfScanRuns[0] ?? null;
  }, [pdfScanRuns, activeRunId, selectedKapitelId]);

  const runningRun = useMemo(() => {
    if (!activeRun) return false;
    return activeRun.status === "running" || activeRun.status === "queued";
  }, [activeRun]);

  const [stage2Hits, setStage2Hits] = useState<Stage2Row[]>([]);
  const [stage3Sections, setStage3Sections] = useState<Stage3Row[]>([]);
  const [stage2Filter, setStage2Filter] = useState("");
  const [stage3Filter, setStage3Filter] = useState("");

  const [extractOpen, setExtractOpen] = useState(false);
  const [extractRequest, setExtractRequest] = useState<PdfExtractRequest | null>(null);

  const pdfMetaById = useMemo(() => {
    const m = new Map<string, PdfRow>();
    for (const p of pdfs) m.set(p.id, p);
    return m;
  }, [pdfs]);

  useEffect(() => {
    if (selectedKapitelId) return;
    if (activeRun?.kapitelIds?.[0]) {
      setSelectedKapitelId(activeRun.kapitelIds[0]);
      return;
    }
    if (kapitels.length) setSelectedKapitelId(kapitels[0]?.id ?? null);
  }, [selectedKapitelId, activeRun?.kapitelIds, kapitels]);

  useEffect(() => {
    if (!activeRunId) return;
    if (pdfScanRuns.some((r) => r.id === activeRunId)) return;
    setActiveRunId(null);
  }, [pdfScanRuns, activeRunId]);

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
    setSelectedPdfIds((prev) => prev.filter((id) => pdfMetaById.has(id)));
  }, [pdfMetaById]);

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
    if (!user?.uid || !projektId || !activeRun?.id) {
      setStage2Hits([]);
      setStage3Sections([]);
      return;
    }

    const stage2Col = quellenFinderPdfStage2Col(firestoreClient, user.uid, projektId, activeRun.id);
    const stage3Col = quellenFinderPdfStage3Col(firestoreClient, user.uid, projektId, activeRun.id);

    const unsub2 = onSnapshot(
      query(stage2Col, orderBy("score", "desc"), limit(500)),
      (snap) => setStage2Hits(snap.docs.map((d) => ({ docId: d.id, ...(d.data() as PdfScanStage2HitDoc) }))),
      (err) => {
        console.error("Failed to load pdfStage2:", err);
        setStage2Hits([]);
      }
    );

    const unsub3 = onSnapshot(
      query(stage3Col, orderBy("score", "desc"), limit(300)),
      (snap) => setStage3Sections(snap.docs.map((d) => ({ docId: d.id, ...(d.data() as PdfScanStage3SectionDoc) }))),
      (err) => {
        console.error("Failed to load pdfStage3:", err);
        setStage3Sections([]);
      }
    );

    return () => {
      unsub2();
      unsub3();
    };
  }, [user?.uid, projektId, activeRun?.id]);

  const lastRunStatus = useRef<{ runId: string; status: string } | null>(null);
  useEffect(() => {
    if (!activeRun?.id) return;
    const prev = lastRunStatus.current;
    if (!prev || prev.runId !== activeRun.id) {
      lastRunStatus.current = { runId: activeRun.id, status: String(activeRun.status || "") };
      return;
    }

    const nextStatus = String(activeRun.status || "");
    if (prev.status !== nextStatus) {
      if (nextStatus === "success") {
        toast.success("PDF‑Scan abgeschlossen", {
          description: typeof activeRun.stage3Count === "number" ? `${formatIntDe(activeRun.stage3Count)} Sections` : undefined,
        });
      } else if (nextStatus === "error") {
        toast.error("PDF‑Scan fehlgeschlagen", { description: String(activeRun.errorMessage || "").trim() || "Unbekannter Fehler" });
      } else if (nextStatus === "cancelled") {
        toast.success("PDF‑Scan abgebrochen", { description: `Run: ${activeRun.id}` });
      }
    }

    lastRunStatus.current = { runId: activeRun.id, status: nextStatus };
  }, [activeRun?.id, activeRun?.status, activeRun?.stage3Count, activeRun?.errorMessage]);

  const togglePdfSelection = (pdfId: string, nextChecked: boolean) => {
    setSelectedPdfIds((prev) => {
      const s = new Set(prev);
      if (nextChecked) s.add(pdfId);
      else s.delete(pdfId);
      return Array.from(s);
    });
  };

  const allSelected = pdfs.length > 0 && selectedPdfIds.length === pdfs.length;
  const someSelected = selectedPdfIds.length > 0 && selectedPdfIds.length < pdfs.length;

  const setSelectAll = (checked: boolean) => {
    if (!checked) {
      setSelectedPdfIds([]);
      return;
    }
    setSelectedPdfIds(pdfs.map((p) => p.id));
  };

  const uploadProjectPdfs = async (files: FileList | null) => {
    if (!files || files.length === 0) return;
    if (!user?.uid || !projektId) {
      toast.error("Nicht eingeloggt", { description: "User fehlt." });
      return;
    }

    const fileArr = Array.from(files);
    const invalid = fileArr.filter((f) => String(f.name || "").toLowerCase().trim().endsWith(".pdf") === false);
    if (invalid.length) {
      toast.error("Nur PDFs erlaubt", {
        description: `Ungültige Dateien: ${invalid
          .map((f) => f.name)
          .slice(0, 3)
          .join(", ")}${invalid.length > 3 ? "…" : ""}`,
      });
      return;
    }

    setUploading(true);
    setUploadProgress({ done: 0, total: fileArr.length });

    const storage = getStorage(firebaseApp);
    const col = projectPdfsCol(firestoreClient, user.uid, projektId);

    try {
      for (let i = 0; i < fileArr.length; i += 1) {
        const file = fileArr[i]!;
        const originalName = String(file.name || "document.pdf").trim() || "document.pdf";
        const safeBase = originalName.replace(/[^a-zA-Z0-9._-]/g, "_");
        const suffix = safeBase.toLowerCase().endsWith(".pdf") ? safeBase : `${safeBase}.pdf`;
        const stamp = `${Date.now()}_${Math.random().toString(36).slice(2, 9)}`;
        const path = `users/${user.uid}/projects/${projektId}/pdfs/${stamp}_${suffix}`.slice(0, 900);

        setUploadProgress({ done: i, total: fileArr.length });
        const r = storageRef(storage, path);
        await uploadBytes(r, file, { contentType: "application/pdf" });

        const now = Timestamp.now();
        await addDoc(col, {
          filename: originalName,
          storagePath: path,
          size: Math.max(0, Math.trunc(file.size)),
          contentType: "application/pdf",
          createdAt: now,
          updatedAt: now,
        });

        setUploadProgress({ done: i + 1, total: fileArr.length });
      }

      toast.success("PDFs hochgeladen", { description: `${fileArr.length} Datei(en)` });
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      toast.error("Upload fehlgeschlagen", { description: msg });
    } finally {
      setUploading(false);
      setUploadProgress(null);
    }
  };

  const deleteProjectPdf = async (pdf: PdfRow) => {
    if (!user?.uid || !projektId) return;
    const ok = window.confirm(`PDF wirklich löschen?\n\n${pdf.filename}`);
    if (!ok) return;

    const storage = getStorage(firebaseApp);
    const path = String(pdf.storagePath || "").trim();

    try {
      if (path) await deleteObject(storageRef(storage, path));
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      toast.error("Storage delete fehlgeschlagen", { description: msg });
      return;
    }

    try {
      await deleteDoc(doc(firestoreClient, "users", user.uid, "projects", projektId, "pdfs", pdf.id));
      toast.success("PDF gelöscht", { description: pdf.filename });
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      toast.error("Firestore delete fehlgeschlagen", { description: msg });
    }
  };

  const startPdfScan = async () => {
    if (!selectedKapitelId) {
      toast.error("Bitte ein Kapitel auswählen.");
      return;
    }
    if (selectedPdfIds.length === 0) {
      toast.error("Bitte mindestens ein PDF auswählen.");
      return;
    }

    const token = Cookies.get("__session");
    if (!token) {
      toast.error("Nicht eingeloggt", { description: "Session Token fehlt." });
      return;
    }

    const res = await fetch(`${API_BASE_URL}/api/quellen-finder/pdf-scan`, {
      method: "POST",
      headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
      body: JSON.stringify({
        projekt_id: projektId,
        kapitel_id: selectedKapitelId,
        pdf_ids: selectedPdfIds,
        preprocess: preprocessEnabled,
      }),
    });

    if (!res.ok) {
      const detail = await readFastApiError(res);
      if (res.status === 402) {
        toast.error("Nicht genügend Credits", { description: detail });
        return;
      }
      if (res.status === 409) {
        toast.error("PDF‑Scan läuft bereits", { description: detail });
        return;
      }
      toast.error("PDF‑Scan fehlgeschlagen", { description: detail });
      return;
    }

    const data = (await res.json().catch(() => ({}))) as Record<string, unknown>;
    const runId = typeof data.run_id === "string" ? String(data.run_id) : "";
    if (runId) setActiveRunId(runId);
    toast.success("PDF‑Scan gestartet", { description: runId ? `Run: ${runId}` : undefined });
  };

  const selectKapitel = (kapitelId: string | null) => {
    setSelectedKapitelId(kapitelId);
    setExtractOpen(false);
    setExtractRequest(null);

    if (!kapitelId) {
      setActiveRunId(null);
      return;
    }

    const mostRecentRun = pdfScanRuns.find((r) => Array.isArray(r.kapitelIds) && r.kapitelIds.includes(kapitelId));
    setActiveRunId(mostRecentRun?.id ?? null);
  };

  const selectRun = (run: RunRow) => {
    setActiveRunId(run.id);
    setExtractOpen(false);
    setExtractRequest(null);
    const kid = Array.isArray(run.kapitelIds) ? run.kapitelIds[0] : null;
    if (kid) setSelectedKapitelId(kid);
  };

  const openExtract = (req: PdfExtractRequest) => {
    setExtractRequest(req);
    setExtractOpen(true);
  };

  const closeExtract = (open: boolean) => {
    setExtractOpen(open);
    if (!open) setExtractRequest(null);
  };

  const activeKapitelSnapshot = activeRun?.kapitelSnapshots?.[0] ?? null;
  const chapterNummer = String(activeKapitelSnapshot?.nummer ?? selectedKapitel?.nummer ?? "").trim();
  const chapterTitle = String(activeKapitelSnapshot?.title ?? selectedKapitel?.title ?? "").trim();
  const chapterHeading = `${chapterNummer ? `${chapterNummer} ` : ""}${chapterTitle || "Kapitel"}`.trim();

  const runStartedAt = toDateOrNull(activeRun?.startedAt) ?? toDateOrNull(activeRun?.createdAt);
  const runFinishedAt = toDateOrNull(activeRun?.finishedAt);

  const stageKey = String(activeRun?.progress?.stage || "");
  const stageIdx = PDF_SCAN_PIPELINE_STEPS.findIndex((s) => s.key === stageKey);
  const isDone = activeRun?.status === "success" || stageKey === "done";
  const isError = activeRun?.status === "error" || stageKey === "error";

  const stage2Rows = useMemo(() => {
    const q = stage2Filter.trim().toLowerCase();
    const rows = stage2Hits.slice();
    if (!q) return rows;
    return rows.filter((r) => {
      const hay = `${r.pdfLabel || ""}\n${r.subpoint || ""}\n${r.summary || ""}\n${r.coverage || ""}\n${r.evidenceSnippet || ""}`.toLowerCase();
      return hay.includes(q);
    });
  }, [stage2Hits, stage2Filter]);

  const stage3Rows = useMemo(() => {
    const q = stage3Filter.trim().toLowerCase();
    const rows = stage3Sections.slice();
    if (!q) return rows;
    return rows.filter((r) => {
      const covered = Array.isArray(r.coveredSubpoints) ? r.coveredSubpoints.join(", ") : "";
      const hay = `${r.pdfLabel || ""}\n${r.heading || ""}\n${r.summary || ""}\n${covered}`.toLowerCase();
      return hay.includes(q);
    });
  }, [stage3Sections, stage3Filter]);

  const canStart = Boolean(selectedKapitelId) && selectedPdfIds.length > 0 && !uploading;

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
            <div className="text-lg font-semibold truncate">PDF‑Scan</div>
            <div className="text-sm text-muted-foreground truncate">
              Durchsuche deine Projekt‑PDFs nach passenden Abschnitten für ein Kapitel
            </div>
          </div>
        </div>

        <div className="flex-1 min-h-0 flex flex-row">
          <aside className="w-[360px] shrink-0 border-r border-border bg-sidebar flex flex-col text-sidebar-foreground">
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
                {selectedKapitel ? (
                  <div className="text-xs text-sidebar-foreground/70 line-clamp-3">{selectedKapitel.thema || ""}</div>
                ) : null}
              </div>

              <Separator className="bg-sidebar-border" />

              <div className="space-y-2">
                <div className="flex items-center justify-between gap-2">
                  <div className="text-xs font-medium text-sidebar-foreground/70">Projekt‑PDFs</div>
                  <Button variant="outline" size="sm" asChild disabled={uploading}>
                    <label className="cursor-pointer">
                      {uploading ? <Loader2 className="h-4 w-4 mr-2 animate-spin" /> : <FileUp className="h-4 w-4 mr-2" />}
                      Upload
                      <input
                        type="file"
                        accept="application/pdf,.pdf"
                        multiple
                        className="hidden"
                        onChange={(e) => {
                          const files = e.target.files;
                          void uploadProjectPdfs(files);
                          e.currentTarget.value = "";
                        }}
                      />
                    </label>
                  </Button>
                </div>

                <div className="flex items-center justify-between gap-3">
                  <div className="flex items-center gap-2">
                    <Checkbox
                      checked={allSelected ? true : someSelected ? "indeterminate" : false}
                      onCheckedChange={(v) => setSelectAll(Boolean(v))}
                      aria-label="Alle PDFs auswählen"
                    />
                    <div className="text-xs text-sidebar-foreground/70 tabular-nums">
                      {formatIntDe(selectedPdfIds.length)} / {formatIntDe(pdfs.length)} ausgewählt
                    </div>
                  </div>
                  {uploadProgress ? (
                    <div className="text-xs text-sidebar-foreground/70 tabular-nums">
                      {uploadProgress.done}/{uploadProgress.total}
                    </div>
                  ) : null}
                </div>

                <div className="rounded-md border border-border bg-background overflow-hidden">
                  <ScrollArea className="h-[220px]">
                    <div className="divide-y divide-border">
                      {pdfs.map((p) => {
                        const checked = selectedPdfIdSet.has(p.id);
                        return (
                          <div key={p.id} className="flex items-start gap-3 px-3 py-2 hover:bg-muted/30">
                            <Checkbox
                              checked={checked}
                              onCheckedChange={(v) => togglePdfSelection(p.id, Boolean(v))}
                              className="mt-0.5"
                              aria-label={`PDF auswählen: ${p.filename}`}
                            />
                            <div className="min-w-0 flex-1">
                              <div className="text-sm font-medium truncate" title={p.filename}>
                                {p.filename}
                              </div>
                              <div className="text-xs text-muted-foreground tabular-nums">
                                {formatBytes(p.size)} • {formatTimeHm(p.createdAt)}
                              </div>
                            </div>
                            <div className="shrink-0 flex items-center gap-1">
                              <Tooltip>
                                <TooltipTrigger asChild>
                                  <Button
                                    type="button"
                                    size="icon"
                                    variant="ghost"
                                    className="h-8 w-8"
                                    onClick={() => {
                                      const path = String(p.storagePath || "").trim();
                                      if (!path) {
                                        toast.error("Kein Storage-Pfad", { description: "storagePath fehlt." });
                                        return;
                                      }
                                      const storage = getStorage(firebaseApp);
                                      const url = storageRef(storage, path);
                                      void (async () => {
                                        try {
                                          const href = await getDownloadURL(url);
                                          window.open(href, "_blank", "noopener,noreferrer");
                                        } catch (err: unknown) {
                                          toast.error("PDF konnte nicht geöffnet werden", {
                                            description: err instanceof Error ? err.message : String(err),
                                          });
                                        }
                                      })();
                                    }}
                                    aria-label="PDF öffnen"
                                  >
                                    <ExternalLink className="h-4 w-4" />
                                  </Button>
                                </TooltipTrigger>
                                <TooltipContent>Öffnen</TooltipContent>
                              </Tooltip>

                              <Tooltip>
                                <TooltipTrigger asChild>
                                  <Button
                                    type="button"
                                    size="icon"
                                    variant="ghost"
                                    className="h-8 w-8 text-destructive hover:text-destructive"
                                    onClick={() => void deleteProjectPdf(p)}
                                    aria-label="PDF löschen"
                                  >
                                    <Trash2 className="h-4 w-4" />
                                  </Button>
                                </TooltipTrigger>
                                <TooltipContent>Löschen</TooltipContent>
                              </Tooltip>
                            </div>
                          </div>
                        );
                      })}
                      {pdfs.length === 0 ? (
                        <div className="px-3 py-3 text-xs text-muted-foreground">Noch keine PDFs. Lade oben welche hoch.</div>
                      ) : null}
                    </div>
                  </ScrollArea>
                </div>
              </div>

              <div className="rounded-md border border-sidebar-border bg-sidebar-accent/40 p-3">
                <div className="flex items-center justify-between gap-3">
                  <div className="min-w-0">
                    <Label className="text-xs font-medium text-sidebar-foreground/70">Preprocess (Stage 1)</Label>
                    <div className="text-xs text-sidebar-foreground/70">
                      Optimiert Kapitel‑Keywords (schneller, meist bessere Treffer)
                    </div>
                  </div>
                  <Switch checked={preprocessEnabled} onCheckedChange={setPreprocessEnabled} />
                </div>
              </div>

              <Button size="lg" onClick={startPdfScan} disabled={!canStart} className="w-full">
                {runningRun ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
                Scan starten
              </Button>

              <div className="text-[11px] text-sidebar-foreground/70">
                Projekt: <span className="font-medium text-sidebar-foreground">{projektName}</span>
              </div>
            </div>

            <div className="flex-1 overflow-auto divide-y divide-sidebar-border">
              {pdfScanRuns.map((r) => {
                const snap = r.kapitelSnapshots?.[0] ?? null;
                const num = String(snap?.nummer || "").trim();
                const title = String(snap?.title || "").trim();
                const label = `${num ? `${num} ` : ""}${title || ""}`.trim() || r.id;

                const time = formatTimeHm(r.startedAt ?? r.createdAt);
                const sub =
                  r.status === "running" || r.status === "queued"
                    ? `${time}  Läuft…`
                    : r.status === "success"
                      ? `${time}  ${formatIntDe(r.stage3Count ?? 0)} Sections`
                      : r.status === "cancelled"
                        ? `${time}  Abgebrochen`
                        : `${time}  Fehler`;

                const active = r.id === activeRun?.id;

                const icon =
                  r.status === "running" || r.status === "queued" ? (
                    <Loader2 className="h-4 w-4 animate-spin text-orange-500" />
                  ) : r.status === "success" ? (
                    <Check className="h-4 w-4 text-emerald-600" />
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
              {pdfScanRuns.length === 0 ? <div className="px-5 py-3 text-xs text-sidebar-foreground/70">Noch keine PDF‑Scans.</div> : null}
            </div>
          </aside>

          <div className="flex-1 min-w-0 overflow-auto p-6">
            <div className="space-y-4 min-w-0">
              <div className="flex items-start justify-between gap-4">
                <div className="min-w-0">
                  <div className="text-xl font-semibold truncate">{chapterHeading || "Kapitel auswählen"}</div>
                  {activeRun ? (
                    <div className="text-xs text-muted-foreground">
                      Gestartet: {formatDateTimeWithSeconds(runStartedAt)}{" "}
                      {runFinishedAt ? <>| Abgeschlossen: {formatDateTimeWithSeconds(runFinishedAt)}</> : null}
                    </div>
                  ) : (
                    <div className="text-xs text-muted-foreground">
                      {selectedKapitel
                        ? "Noch kein PDF‑Scan für dieses Kapitel. Starte links einen neuen Scan."
                        : "Wähle links ein Kapitel und starte einen PDF‑Scan."}
                    </div>
                  )}
                </div>

                {activeRun ? (
                  <div className="flex items-center gap-3 flex-wrap justify-end">
                    <StatusPill status={String(activeRun.status || "")} />
                    {typeof activeRun.stage2Count === "number" ? (
                      <Badge variant="outline" className="tabular-nums">
                        {formatIntDe(activeRun.stage2Count)} Hits
                      </Badge>
                    ) : null}
                    {typeof activeRun.stage3Count === "number" ? (
                      <Badge variant="outline" className="tabular-nums">
                        {formatIntDe(activeRun.stage3Count)} Sections
                      </Badge>
                    ) : null}
                  </div>
                ) : null}
              </div>

              {activeRun ? (
                <Card className="p-4">
                  <div className="flex items-start justify-between gap-4">
                    <div className="min-w-0">
                      <div className="text-sm font-semibold">Pipeline‑Status</div>
                      <div className="text-xs text-muted-foreground">
                        {activeRun.progress?.message ? String(activeRun.progress?.message) : "—"}
                        {activeRun.progress?.current != null && activeRun.progress?.total != null ? (
                          <span className="tabular-nums">
                            {" "}
                            ({formatIntDe(activeRun.progress?.current)}/{formatIntDe(activeRun.progress?.total)})
                          </span>
                        ) : null}
                      </div>
                    </div>
                    <div className="shrink-0 text-right">
                      {activeRun.hadPartialFailures ? (
                        <Badge
                          variant="outline"
                          className="text-amber-700 border-amber-300 bg-amber-50 dark:bg-amber-950/20 dark:text-amber-200 dark:border-amber-800"
                        >
                          Partial failures
                        </Badge>
                      ) : null}
                    </div>
                  </div>

                  <div className="mt-4 grid grid-cols-1 md:grid-cols-2 gap-3">
                    {PDF_SCAN_PIPELINE_STEPS.map((s, idx) => {
                      const done = isDone ? true : stageIdx > idx;
                      const active = !isDone && !isError && idx === stageIdx;
                      return (
                        <div
                          key={s.key}
                          className={`flex items-center justify-between gap-3 rounded-md border px-3 py-2 ${
                            done
                              ? "bg-emerald-50 border-emerald-200 dark:bg-emerald-950/20 dark:border-emerald-800"
                              : active
                                ? "bg-muted/30 border-border"
                                : "bg-background border-border"
                          }`}
                        >
                          <div className="min-w-0">
                            <div className="text-xs font-medium truncate">{s.label}</div>
                            <div className="text-[11px] text-muted-foreground truncate">{s.key}</div>
                          </div>
                          <div className="shrink-0">
                            {done ? (
                              <Check className="h-4 w-4 text-emerald-600" />
                            ) : active ? (
                              <Loader2 className="h-4 w-4 animate-spin text-orange-500" />
                            ) : (
                              <div className="h-4 w-4 rounded-full border border-muted-foreground/30" />
                            )}
                          </div>
                        </div>
                      );
                    })}
                  </div>

                  {isError ? (
                    <div className="mt-3 text-sm text-destructive">
                      {String(activeRun.errorMessage || "").trim() || "Unbekannter Fehler"}
                    </div>
                  ) : null}
                </Card>
              ) : null}

              <Tabs defaultValue="stage3" className="w-full">
                <div className="flex items-center justify-between gap-4 flex-wrap">
                  <TabsList className="bg-muted/30">
                    <TabsTrigger value="stage3" className="text-xs">
                      Stage 3 (Sections)
                    </TabsTrigger>
                    <TabsTrigger value="stage2" className="text-xs">
                      Stage 2 (Hits)
                    </TabsTrigger>
                  </TabsList>

                  <div className="flex items-center gap-2">
                    <Badge variant="outline" className="text-xs tabular-nums">
                      {formatIntDe(stage3Rows.length)} Sections
                    </Badge>
                    <Badge variant="outline" className="text-xs tabular-nums">
                      {formatIntDe(stage2Rows.length)} Hits
                    </Badge>
                  </div>
                </div>

                <TabsContent value="stage3" className="mt-4">
                  <Card className="p-4">
                    <div className="flex items-start justify-between gap-3 flex-wrap">
                      <div className="min-w-0">
                        <div className="text-sm font-semibold">Sections</div>
                        <div className="text-xs text-muted-foreground">Kuratiert + gruppiert (ideal zum Zitieren).</div>
                      </div>
                      <Input
                        value={stage3Filter}
                        onChange={(e) => setStage3Filter(e.target.value)}
                        placeholder="Filtern… (PDF, Heading, Summary)"
                        className="h-9 w-full sm:w-72"
                      />
                    </div>

                    <div className="mt-4 overflow-auto rounded-md border border-border">
                      <Table>
                        <TableHeader>
                          <TableRow>
                            <TableHead className="w-[90px]">Score</TableHead>
                            <TableHead className="w-[240px]">PDF</TableHead>
                            <TableHead>Heading</TableHead>
                            <TableHead className="w-[170px]">Subpoints</TableHead>
                            <TableHead className="w-[120px] text-right">Aktion</TableHead>
                          </TableRow>
                        </TableHeader>
                        <TableBody>
                          {stage3Rows.map((r) => {
                            const score = typeof r.score === "number" ? r.score : null;
                            const pdfLabel = String(r.pdfLabel || r.pdfId || "").trim() || "—";
                            const heading = String(r.heading || "").trim() || "—";
                            const subs = Array.isArray(r.coveredSubpoints) ? r.coveredSubpoints : [];
                            const meta = r.pdfId ? pdfMetaById.get(String(r.pdfId)) : null;
                            return (
                              <TableRow key={r.docId}>
                                <TableCell className="tabular-nums">
                                  {score != null ? (
                                    <Badge variant="outline" className="tabular-nums">
                                      {score}
                                    </Badge>
                                  ) : (
                                    <span className="text-muted-foreground">—</span>
                                  )}
                                </TableCell>
                                <TableCell className="truncate" title={pdfLabel}>
                                  {pdfLabel}
                                </TableCell>
                                <TableCell className="min-w-[360px]">
                                  <div className="font-medium truncate" title={heading}>
                                    {heading}
                                  </div>
                                  {r.summary ? (
                                    <div className="text-xs text-muted-foreground line-clamp-2 mt-0.5">{String(r.summary)}</div>
                                  ) : null}
                                </TableCell>
                                <TableCell className="text-xs text-muted-foreground">
                                  {subs.length ? subs.slice(0, 3).join(", ") : "—"}
                                  {subs.length > 3 ? "…" : ""}
                                </TableCell>
                                <TableCell className="text-right">
                                  <Button
                                    size="sm"
                                    variant="outline"
                                    onClick={() =>
                                      openExtract({
                                        projektId,
                                        runId: String(activeRun?.id || ""),
                                        stage: "stage3",
                                        docId: r.docId,
                                        pdfId: String(r.pdfId || "") || undefined,
                                        pdfFilename: meta?.filename || pdfLabel,
                                        storagePath: meta?.storagePath,
                                        anchorPage: typeof r.anchorPage === "number" ? r.anchorPage : undefined,
                                      })
                                    }
                                    disabled={!activeRun?.id}
                                  >
                                    Preview
                                  </Button>
                                </TableCell>
                              </TableRow>
                            );
                          })}
                          {stage3Rows.length === 0 ? (
                            <TableRow>
                              <TableCell colSpan={5} className="text-sm text-muted-foreground">
                                Keine Sections vorhanden (noch nicht fertig oder keine Treffer).
                              </TableCell>
                            </TableRow>
                          ) : null}
                        </TableBody>
                      </Table>
                    </div>
                  </Card>
                </TabsContent>

                <TabsContent value="stage2" className="mt-4">
                  <Card className="p-4">
                    <div className="flex items-start justify-between gap-3 flex-wrap">
                      <div className="min-w-0">
                        <div className="text-sm font-semibold">Hits</div>
                        <div className="text-xs text-muted-foreground">Alle Treffer aus dem Evidence‑Extractor.</div>
                      </div>
                      <Input
                        value={stage2Filter}
                        onChange={(e) => setStage2Filter(e.target.value)}
                        placeholder="Filtern… (PDF, Subpoint, Summary)"
                        className="h-9 w-full sm:w-72"
                      />
                    </div>

                    <div className="mt-4 overflow-auto rounded-md border border-border">
                      <Table>
                        <TableHeader>
                          <TableRow>
                            <TableHead className="w-[90px]">Score</TableHead>
                            <TableHead className="w-[240px]">PDF</TableHead>
                            <TableHead className="w-[220px]">Subpoint</TableHead>
                            <TableHead>Summary</TableHead>
                            <TableHead className="w-[120px] text-right">Aktion</TableHead>
                          </TableRow>
                        </TableHeader>
                        <TableBody>
                          {stage2Rows.map((r) => {
                            const score = typeof r.score === "number" ? r.score : null;
                            const pdfLabel = String(r.pdfLabel || r.pdfId || "").trim() || "—";
                            const meta = r.pdfId ? pdfMetaById.get(String(r.pdfId)) : null;
                            return (
                              <TableRow key={r.docId}>
                                <TableCell className="tabular-nums">
                                  {score != null ? (
                                    <Badge variant="outline" className="tabular-nums">
                                      {score}
                                    </Badge>
                                  ) : (
                                    <span className="text-muted-foreground">—</span>
                                  )}
                                </TableCell>
                                <TableCell className="truncate" title={pdfLabel}>
                                  {pdfLabel}
                                </TableCell>
                                <TableCell className="truncate" title={String(r.subpoint || "")}>
                                  {r.subpoint ? String(r.subpoint) : <span className="text-muted-foreground">—</span>}
                                </TableCell>
                                <TableCell className="min-w-[360px]">
                                  <div className="font-medium truncate" title={String(r.summary || "")}>
                                    {r.summary ? String(r.summary) : "—"}
                                  </div>
                                  {r.coverage ? (
                                    <div className="text-xs text-muted-foreground line-clamp-2 mt-0.5">{String(r.coverage)}</div>
                                  ) : null}
                                </TableCell>
                                <TableCell className="text-right">
                                  <Button
                                    size="sm"
                                    variant="outline"
                                    onClick={() =>
                                      openExtract({
                                        projektId,
                                        runId: String(activeRun?.id || ""),
                                        stage: "stage2",
                                        docId: r.docId,
                                        pdfId: String(r.pdfId || "") || undefined,
                                        pdfFilename: meta?.filename || pdfLabel,
                                        storagePath: meta?.storagePath,
                                      })
                                    }
                                    disabled={!activeRun?.id}
                                  >
                                    Preview
                                  </Button>
                                </TableCell>
                              </TableRow>
                            );
                          })}
                          {stage2Rows.length === 0 ? (
                            <TableRow>
                              <TableCell colSpan={5} className="text-sm text-muted-foreground">
                                Keine Hits vorhanden (noch nicht fertig oder keine Treffer).
                              </TableCell>
                            </TableRow>
                          ) : null}
                        </TableBody>
                      </Table>
                    </div>
                  </Card>
                </TabsContent>
              </Tabs>
            </div>
          </div>
        </div>

        <PdfExtractDialog open={extractOpen} onOpenChange={closeExtract} request={extractRequest} />
      </div>
      <ViewportWarning />
    </TooltipProvider>
  );
}
